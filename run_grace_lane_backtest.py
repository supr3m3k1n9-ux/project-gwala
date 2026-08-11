"""Backtest the proposed one-candle grace lane.

This is a research report only. It does not alter Paper Gate v2, write paper
trades, create broker alerts, place orders, or enable live execution.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.engine import find_exit, find_short_exit
from config.filter_policy import PAPER_GATE_THRESHOLDS
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from data.candle_cache import preferred_candle_path
from data.market_data import load_candles_from_csv
from run_webull_watchlist import (
    EXIT_PROFILES,
    MARKET_CONFIRMED_VARIANTS,
    add_strategy_columns,
    apply_market_confirmation,
    settings_for_variant,
)
from strategies.scanner_adapters import scanner_adapter_for_entry, selected_signal_column


ACCOUNT_SIZE = 10_000.0
MARKET_TZ = "America/New_York"


@dataclass(frozen=True)
class GraceLaneCandidate:
    """One simulated candidate window."""

    lane: str
    symbol: str
    setup: str
    variant: str
    exit_profile: str
    direction: str
    source_signal_time: str
    candidate_entry_time: str
    exit_time: str
    quality_score: float
    quality_grade: str
    check_score: float
    relative_volume: float
    room_to_target_r: float
    planned_entry: float
    planned_stop: float
    planned_target: float
    risk_per_share: float
    suggested_shares: int
    r_result: float
    mae_r: float
    exit_reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest current-candle versus one-M30 grace lane.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Directory containing candle caches.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Directory for report outputs.")
    parser.add_argument("--playbook", choices=sorted(PLAYBOOKS), default="approved_plus_watch")
    parser.add_argument("--lookback-days", type=int, default=90, help="Calendar-day lookback for the replay.")
    parser.add_argument("--market-regime-symbol", default="SPY")
    return parser.parse_args()


def read_candles(path: Path, symbol: str) -> pd.DataFrame:
    """Read a candle CSV, returning an empty frame when it cannot be used."""

    try:
        return load_candles_from_csv(path, symbol)
    except (FileNotFoundError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def combined_exit_candles(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Return the widest local 5m candle set available for a symbol."""

    frames: list[pd.DataFrame] = []
    canonical = preferred_candle_path(data_dir, symbol, "M5")
    frames.append(read_candles(canonical, symbol))

    for path in sorted(data_dir.glob(f"{symbol.upper()}_*_webull_30m_entry_5m_exit_exit_candles.csv")):
        frame = read_candles(path, symbol)
        if not frame.empty:
            frames.append(frame)

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise FileNotFoundError(f"No usable M5 candles found for {symbol}.")

    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined


def load_entry_candles(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Load the current canonical 30m entry candles for a symbol."""

    path = preferred_candle_path(data_dir, symbol, "M30")
    candles = read_candles(path, symbol)
    if candles.empty:
        raise FileNotFoundError(f"No usable M30 candles found for {symbol}.")
    return candles


def enriched_candles(
    entry: PlaybookEntry,
    data_dir: Path,
    market_symbol: str,
    exit_cache: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and enrich candles using the same strategy wiring as the scanner."""

    settings = settings_for_variant(entry.variant)
    entry_candles = load_entry_candles(data_dir, entry.symbol)
    exit_candles = exit_cache.setdefault(entry.symbol.upper(), combined_exit_candles(data_dir, entry.symbol))

    market_candles = None
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        market_candles = load_entry_candles(data_dir, market_symbol.upper())

    enriched_entry, enriched_exit = add_strategy_columns(
        entry_candles,
        exit_candles,
        settings,
        market_candles=market_candles,
        market_symbol=market_symbol.upper(),
    )
    adapter = scanner_adapter_for_entry(entry)
    enriched_entry = adapter.add_columns(enriched_entry, entry)
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        enriched_entry = apply_market_confirmation(enriched_entry)
    return enriched_entry, enriched_exit


def number(value: object, default: float = 0.0) -> float:
    """Return a finite float."""

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return default
    return float(parsed)


def condition_summary(row: pd.Series, entry: PlaybookEntry, signal_column: str) -> tuple[float, int, int]:
    """Return check score, passed checks, and total checks for a row."""

    checks = scanner_adapter_for_entry(entry).condition_checks(row, entry, signal_column)
    total = len(checks)
    passed = sum(1 for _, is_met in checks if is_met)
    score = round(passed / total, 4) if total else 0.0
    return score, passed, total


def plan_for(row: pd.Series, entry: PlaybookEntry) -> dict[str, float] | None:
    """Build a fresh planned trade for the selected row."""

    try:
        plan = scanner_adapter_for_entry(entry).plan_for_signal(row, entry, EXIT_PROFILES[entry.exit_profile])
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None

    parsed = {key: number(value) for key, value in plan.items()}
    values = [parsed.get("planned_entry", 0), parsed.get("planned_stop", 0), parsed.get("planned_target", 0)]
    if not all(value > 0 for value in values) or parsed.get("risk_per_share", 0) <= 0:
        return None
    return parsed


def shares_for_lane(lane: str, risk_per_share: float) -> int:
    """Return Paper Gate-style share count for A or B validation risk."""

    risk_pct = (
        float(PAPER_GATE_THRESHOLDS["a_risk_pct"])
        if lane == "A"
        else float(PAPER_GATE_THRESHOLDS["b_risk_pct"])
    )
    if risk_per_share <= 0:
        return 0
    return max(0, math.floor((ACCOUNT_SIZE * risk_pct) / risk_per_share))


def lane_threshold_passes(lane: str, row: pd.Series, entry: PlaybookEntry, signal_column: str, plan: dict[str, float]) -> bool:
    """Return whether a row qualifies for the A or B grace-lane tier."""

    adapter = scanner_adapter_for_entry(entry)
    fields = adapter.scanner_fields(row, entry)
    check_score, _, _ = condition_summary(row, entry, signal_column)
    quality_score = float(fields.quality_score)
    room_to_target = float(fields.room_to_target_r)
    shares = shares_for_lane(lane, plan["risk_per_share"])
    if shares < 1:
        return False
    if lane == "A":
        return (
            check_score >= float(PAPER_GATE_THRESHOLDS["a_min_check_score"])
            and quality_score >= float(PAPER_GATE_THRESHOLDS["a_min_quality_score"])
        )
    return (
        check_score >= float(PAPER_GATE_THRESHOLDS["b_min_check_score"])
        and quality_score >= float(PAPER_GATE_THRESHOLDS["b_min_quality_score"])
        and room_to_target > float(PAPER_GATE_THRESHOLDS["b_min_room_to_target_r"])
    )


def mae_r(
    *,
    direction: str,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    session_date: object,
    entry_price: float,
    risk_per_share: float,
    exit_candles: pd.DataFrame,
) -> float:
    """Return maximum adverse excursion in R for a simulated trade."""

    future = exit_candles[
        (exit_candles.index > entry_time)
        & (exit_candles.index <= exit_time)
        & (exit_candles["session_date"] == session_date)
        & (exit_candles["regular_session"])
    ]
    if future.empty or risk_per_share <= 0:
        return 0.0
    if direction == "short":
        adverse = (float(future["high"].max()) - entry_price) / risk_per_share
    else:
        adverse = (entry_price - float(future["low"].min())) / risk_per_share
    return round(max(0.0, adverse), 4)


def simulate_candidate(
    *,
    lane: str,
    source_signal_time: pd.Timestamp,
    candidate_time: pd.Timestamp,
    row: pd.Series,
    entry: PlaybookEntry,
    exit_candles: pd.DataFrame,
    signal_column: str,
    plan: dict[str, float],
) -> GraceLaneCandidate | None:
    """Simulate one candidate window using the existing 5m exit logic."""

    adapter = scanner_adapter_for_entry(entry)
    fields = adapter.scanner_fields(row, entry)
    direction = adapter.direction(entry)
    exit_profile = EXIT_PROFILES[entry.exit_profile]
    session_date = row.get("session_date")

    if direction == "short":
        exit_result = find_short_exit(
            entry_time=candidate_time,
            entry=plan["planned_entry"],
            stop=plan["planned_stop"],
            target=plan["planned_target"],
            risk_per_share=plan["risk_per_share"],
            session_date=session_date,
            exit_candles=exit_candles,
            exit_profile=exit_profile,
        )
    else:
        exit_result = find_exit(
            entry_time=candidate_time,
            entry=plan["planned_entry"],
            stop=plan["planned_stop"],
            target=plan["planned_target"],
            risk_per_share=plan["risk_per_share"],
            session_date=session_date,
            exit_candles=exit_candles,
            exit_profile=exit_profile,
        )

    if exit_result is None:
        return None

    exit_time, _, _, r_result, exit_reason = exit_result
    check_score, _, _ = condition_summary(row, entry, signal_column)
    return GraceLaneCandidate(
        lane=lane,
        symbol=entry.symbol.upper(),
        setup=entry.setup_name,
        variant=entry.variant,
        exit_profile=entry.exit_profile,
        direction=direction,
        source_signal_time=str(source_signal_time),
        candidate_entry_time=str(candidate_time),
        exit_time=str(exit_time),
        quality_score=float(fields.quality_score),
        quality_grade=str(fields.quality_grade),
        check_score=check_score,
        relative_volume=round(float(fields.relative_volume), 4),
        room_to_target_r=round(float(fields.room_to_target_r), 4),
        planned_entry=round(plan["planned_entry"], 4),
        planned_stop=round(plan["planned_stop"], 4),
        planned_target=round(plan["planned_target"], 4),
        risk_per_share=round(plan["risk_per_share"], 4),
        suggested_shares=shares_for_lane(lane, plan["risk_per_share"]),
        r_result=round(float(r_result), 4),
        mae_r=mae_r(
            direction=direction,
            entry_time=candidate_time,
            exit_time=exit_time,
            session_date=session_date,
            entry_price=plan["planned_entry"],
            risk_per_share=plan["risk_per_share"],
            exit_candles=exit_candles,
        ),
        exit_reason=str(exit_reason),
    )


def next_same_session_row(candles: pd.DataFrame, signal_time: pd.Timestamp, session_date: object) -> tuple[pd.Timestamp, pd.Series] | None:
    """Return the next 30m row in the same session."""

    later = candles[(candles.index > signal_time) & (candles["session_date"] == session_date)]
    if later.empty:
        return None
    candidate_time = later.index[0]
    if candidate_time - signal_time > pd.Timedelta(minutes=45):
        return None
    return candidate_time, later.iloc[0]


def run_backtest(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run the grace-lane replay and return detail rows plus metadata."""

    entries = PLAYBOOKS[args.playbook]
    exit_cache: dict[str, pd.DataFrame] = {}
    candidates: list[GraceLaneCandidate] = []
    errors: list[dict[str, str]] = []
    coverage: dict[str, dict[str, str]] = {}
    lookback_end: pd.Timestamp | None = None

    for entry in entries:
        try:
            entry_candles, exit_candles = enriched_candles(
                entry,
                args.data_dir,
                args.market_regime_symbol,
                exit_cache,
            )
        except Exception as error:  # noqa: BLE001 - report data wiring issues instead of stopping the whole audit.
            errors.append({"symbol": entry.symbol, "setup": entry.setup_name, "error": str(error)})
            continue

        if entry_candles.empty:
            continue

        if lookback_end is None or entry_candles.index.max() > lookback_end:
            lookback_end = entry_candles.index.max()

        signal_column = selected_signal_column(entry)
        adapter = scanner_adapter_for_entry(entry)
        cutoff = entry_candles.index.max() - pd.Timedelta(days=args.lookback_days)
        replay_rows = entry_candles[entry_candles.index >= cutoff].copy()
        signal_rows = replay_rows[replay_rows[signal_column].fillna(False).astype(bool)]

        symbol_key = entry.symbol.upper()
        coverage[symbol_key] = {
            "m30_start": str(entry_candles.index.min()),
            "m30_end": str(entry_candles.index.max()),
            "m30_rows": str(len(entry_candles)),
            "m5_start": str(exit_candles.index.min()),
            "m5_end": str(exit_candles.index.max()),
            "m5_rows": str(len(exit_candles)),
        }

        for signal_time, signal_row in signal_rows.iterrows():
            a_plan = plan_for(signal_row, entry)
            if a_plan is not None and lane_threshold_passes("A", signal_row, entry, signal_column, a_plan):
                candidate = simulate_candidate(
                    lane="A",
                    source_signal_time=signal_time,
                    candidate_time=signal_time,
                    row=signal_row,
                    entry=entry,
                    exit_candles=exit_candles,
                    signal_column=signal_column,
                    plan=a_plan,
                )
                if candidate is not None:
                    candidates.append(candidate)

            next_row = next_same_session_row(entry_candles, signal_time, signal_row.get("session_date"))
            if next_row is None:
                continue

            grace_time, grace_row = next_row
            b_plan = plan_for(grace_row, entry)
            if b_plan is None or not lane_threshold_passes("B", grace_row, entry, signal_column, b_plan):
                continue

            candidate = simulate_candidate(
                lane="B",
                source_signal_time=signal_time,
                candidate_time=grace_time,
                row=grace_row,
                entry=entry,
                exit_candles=exit_candles,
                signal_column=signal_column,
                plan=b_plan,
            )
            if candidate is not None:
                candidates.append(candidate)

    detail = annotate_incremental_candidates(pd.DataFrame([asdict(candidate) for candidate in candidates]))
    metadata = {
        "playbook": args.playbook,
        "lookback_days": args.lookback_days,
        "lookback_end": str(lookback_end) if lookback_end is not None else "",
        "lookback_start": str(lookback_end - pd.Timedelta(days=args.lookback_days)) if lookback_end is not None else "",
        "thresholds": PAPER_GATE_THRESHOLDS,
        "coverage": coverage,
        "errors": errors,
    }
    return detail, metadata


def candidate_identity(frame: pd.DataFrame) -> pd.Series:
    """Return a stable identity for one candidate window.

    B-tier can be a legitimate one-candle grace window, but if the same setup is
    also A-tier on that next candle, it is not incremental throughput. In live
    review, the current A window would be the cleaner label.
    """

    columns = ["symbol", "setup", "variant", "exit_profile", "direction", "candidate_entry_time"]
    return frame[columns].astype(str).agg("|".join, axis=1)


def annotate_incremental_candidates(detail: pd.DataFrame) -> pd.DataFrame:
    """Flag B-tier windows that add real throughput beyond current A windows."""

    if detail.empty:
        return detail
    result = detail.copy()
    result["candidate_identity"] = candidate_identity(result)
    a_identities = set(result.loc[result["lane"] == "A", "candidate_identity"])
    result["incremental_to_current_system"] = (
        (result["lane"] == "A")
        | ((result["lane"] == "B") & ~result["candidate_identity"].isin(a_identities))
    )
    result["b_window_type"] = ""
    result.loc[result["lane"] == "B", "b_window_type"] = "incremental"
    result.loc[
        (result["lane"] == "B") & result["candidate_identity"].isin(a_identities),
        "b_window_type",
    ] = "duplicates_current_a_window"
    return result


def summarize_lane(frame: pd.DataFrame) -> dict[str, Any]:
    """Summarize one lane cohort."""

    if frame.empty:
        return {
            "candidates": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "average_r": 0.0,
            "average_mae_r": 0.0,
            "median_mae_r": 0.0,
            "max_mae_r": 0.0,
        }

    wins = int((frame["r_result"] > 0).sum())
    losses = int((frame["r_result"] < 0).sum())
    return {
        "candidates": int(len(frame)),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / len(frame) * 100, 1),
        "average_r": round(float(frame["r_result"].mean()), 4),
        "average_mae_r": round(float(frame["mae_r"].mean()), 4),
        "median_mae_r": round(float(frame["mae_r"].median()), 4),
        "max_mae_r": round(float(frame["mae_r"].max()), 4),
    }


def build_summary(detail: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    """Build top-level report numbers."""

    a_frame = detail[detail["lane"] == "A"] if not detail.empty else pd.DataFrame()
    b_frame = detail[detail["lane"] == "B"] if not detail.empty else pd.DataFrame()
    incremental_b = (
        detail[(detail["lane"] == "B") & detail["incremental_to_current_system"]]
        if not detail.empty
        else pd.DataFrame()
    )
    combined = (
        detail[detail["incremental_to_current_system"]].copy()
        if not detail.empty
        else pd.DataFrame()
    )

    a = summarize_lane(a_frame)
    raw_b = summarize_lane(b_frame)
    b = summarize_lane(incremental_b)
    grace = summarize_lane(combined)
    a_count = max(a["candidates"], 0)
    b_count = max(b["candidates"], 0)
    increase_pct = round((b_count / a_count * 100), 1) if a_count else 0.0

    b_quality_ok = (
        b_count > 0
        and b["average_r"] >= a["average_r"] - 0.25
        and b["win_rate_pct"] >= a["win_rate_pct"] - 10.0
        and b["average_mae_r"] <= a["average_mae_r"] + 0.25
    )
    materially_increases = b_count >= max(3, math.ceil(a_count * 0.25))

    return {
        "generated_report": "grace_lane_backtest",
        "metadata": metadata,
        "current_system": {
            "definition": "A-tier only; evaluated on the signal/current M30 candle.",
            **a,
        },
        "grace_lane_b": {
            "definition": (
                "Incremental B-tier rescue lane; evaluated one M30 candle after the source signal, "
                "with fresh plan, fresh sizing, manual review required, and A-window duplicates removed."
            ),
            **b,
        },
        "raw_grace_lane_b_windows": {
            "definition": "All one-candle-late B review windows before removing windows duplicated by current A.",
            **raw_b,
        },
        "grace_system_candidate_windows": {
            "definition": "A current windows plus incremental B one-candle-late review windows.",
            **grace,
        },
        "candidate_increase": {
            "raw_b_tier_windows": int(raw_b["candidates"]),
            "incremental_b_tier_windows": b_count,
            "b_windows_that_duplicate_current_a": int(raw_b["candidates"] - b_count),
            "increase_vs_current_pct": increase_pct,
        },
        "differences": {
            "b_minus_a_win_rate_pct_points": round(b["win_rate_pct"] - a["win_rate_pct"], 1),
            "b_minus_a_average_r": round(b["average_r"] - a["average_r"], 4),
            "b_minus_a_average_mae_r": round(b["average_mae_r"] - a["average_mae_r"], 4),
            "b_minus_a_max_mae_r": round(b["max_mae_r"] - a["max_mae_r"], 4),
            "grace_minus_a_win_rate_pct_points": round(grace["win_rate_pct"] - a["win_rate_pct"], 1),
            "grace_minus_a_average_r": round(grace["average_r"] - a["average_r"], 4),
            "grace_minus_a_average_mae_r": round(grace["average_mae_r"] - a["average_mae_r"], 4),
            "grace_minus_a_max_mae_r": round(grace["max_mae_r"] - a["max_mae_r"], 4),
        },
        "verdict": {
            "materially_increases_throughput": bool(materially_increases),
            "maintains_trade_quality": bool(b_quality_ok),
            "recommendation": (
                "Promote to manual B-tier grace research lane only."
                if materially_increases and b_quality_ok
                else "Do not promote as an official paper lane yet; keep as research/shadow evidence."
            ),
        },
    }


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Render a small markdown table."""

    if not rows:
        return "| " + " | ".join(columns) + " |\n| " + " | ".join(["---"] * len(columns)) + " |\n"
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join([header, divider, *body]) + "\n"


def write_outputs(output_dir: Path, detail: pd.DataFrame, summary: dict[str, Any]) -> None:
    """Write CSV, JSON, and Markdown outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / "grace_lane_backtest.csv"
    json_path = output_dir / "grace_lane_backtest.json"
    md_path = output_dir / "grace_lane_backtest.md"
    detail.to_csv(detail_path, index=False)
    json_path.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")

    current = summary["current_system"]
    b = summary["grace_lane_b"]
    raw_b = summary["raw_grace_lane_b_windows"]
    grace = summary["grace_system_candidate_windows"]
    diffs = summary["differences"]
    verdict = summary["verdict"]
    meta = summary["metadata"]

    rows = [
        {"system": "Current A-tier", **current},
        {"system": "Raw B-tier windows", **raw_b},
        {"system": "Incremental B-tier", **b},
        {"system": "Grace A + incremental B", **grace},
    ]
    comparison = markdown_table(
        rows,
        ["system", "candidates", "win_rate_pct", "average_r", "average_mae_r", "median_mae_r", "max_mae_r"],
    )

    coverage_rows = []
    for symbol, row in sorted(meta["coverage"].items()):
        coverage_rows.append(
            {
                "symbol": symbol,
                "m30": f"{row['m30_start']} -> {row['m30_end']}",
                "m5": f"{row['m5_start']} -> {row['m5_end']}",
                "m30_rows": row["m30_rows"],
                "m5_rows": row["m5_rows"],
            }
        )

    md_path.write_text(
        f"""# Grace Lane Backtest

Generated from local Webull CSV candles.

This report is research-only. It does not change Paper Gate v2, write official
paper samples, place broker orders, or enable live trading.

## Window

- Playbook: `{meta["playbook"]}`
- Lookback days: `{meta["lookback_days"]}`
- Replay start: `{meta["lookback_start"]}`
- Replay end: `{meta["lookback_end"]}`

## Definitions

- Current System: A-tier only, evaluated on the signal/current M30 candle.
- Grace System: A-tier remains current M30 only. B-tier is evaluated one M30
  candle after the source signal and requires fresh plan, fresh sizing, fresh
  stop/target, and manual review.
- Incremental B-tier removes delayed B windows that duplicate a current A-tier
  opportunity on the same setup/time.
- The combined grace count is candidate windows, not permission to double-enter
  the same source signal.

## Results

{comparison}
## Differences

- B minus A win rate: `{diffs["b_minus_a_win_rate_pct_points"]}` percentage points
- B minus A average R: `{diffs["b_minus_a_average_r"]}`
- B minus A average MAE R: `{diffs["b_minus_a_average_mae_r"]}`
- B minus A max MAE R: `{diffs["b_minus_a_max_mae_r"]}`
- Grace combined minus A win rate: `{diffs["grace_minus_a_win_rate_pct_points"]}` percentage points
- Grace combined minus A average R: `{diffs["grace_minus_a_average_r"]}`
- Grace combined minus A average MAE R: `{diffs["grace_minus_a_average_mae_r"]}`
- Grace combined minus A max MAE R: `{diffs["grace_minus_a_max_mae_r"]}`
- Raw B-tier windows: `{summary["candidate_increase"]["raw_b_tier_windows"]}`
- Incremental B-tier windows: `{summary["candidate_increase"]["incremental_b_tier_windows"]}`
- B windows that duplicate a current A window: `{summary["candidate_increase"]["b_windows_that_duplicate_current_a"]}`
- Increase versus current candidate windows: `{summary["candidate_increase"]["increase_vs_current_pct"]}%`

## Verdict

- Materially increases throughput: `{verdict["materially_increases_throughput"]}`
- Maintains trade quality: `{verdict["maintains_trade_quality"]}`
- Recommendation: **{verdict["recommendation"]}**

## Data Coverage

{markdown_table(coverage_rows, ["symbol", "m30_rows", "m5_rows", "m30", "m5"])}
## Notes

- MAE is maximum adverse excursion in R from the first 5m candle after entry
  through the simulated exit candle.
- Exits reuse Gwala's existing 5m exit engine with conservative stop-first
  sequencing when stop and target touch in the same 5m bar.
- B-tier is a manual review lane. Earlier-today signals outside the one-M30
  grace window remain research/shadow only.
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    detail, metadata = run_backtest(args)
    summary = build_summary(detail, metadata)
    write_outputs(args.output_dir, detail, summary)

    current = summary["current_system"]
    b = summary["grace_lane_b"]
    verdict = summary["verdict"]
    print(f"Grace lane backtest wrote logs/grace_lane_backtest.md")
    print(f"A-tier candidates: {current['candidates']} | win {current['win_rate_pct']}% | avg R {current['average_r']}")
    print(f"B-tier candidates: {b['candidates']} | win {b['win_rate_pct']}% | avg R {b['average_r']}")
    print(f"Verdict: {verdict['recommendation']}")


if __name__ == "__main__":
    main()
