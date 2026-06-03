"""Collect VWAP mean-reversion shadow samples.

This is the forward-style observation lane for the Strategy Vault's VWAP mean
reversion candidate. It records qualifying mean-reversion signals from saved
Webull candles, then grades them after complete 5m session data exists.

Important: these rows are not paper trades, broker alerts, or execution
instructions. They do not count toward the official 30/60 paper-trade gates.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table
from run_vwap_mean_reversion import (
    add_research_columns,
    find_mean_reversion_exit,
    load_candles_from_csv,
)


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")
SAMPLE_COLUMNS = [
    "observed_at_et",
    "scan_date",
    "entry_time_et",
    "symbol",
    "strategy",
    "direction",
    "signal_column",
    "shadow_status",
    "shadow_reason",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "risk_per_share",
    "reward_multiple",
    "quality_score",
    "quality_grade",
    "relative_volume",
    "vwap_gap_pct",
    "trend_gap_pct",
    "close",
    "vwap",
    "ema_9",
    "ema_21",
]
KEY_COLUMNS = ["entry_time_et", "symbol", "direction", "signal_column"]
OUTCOME_COLUMNS = [
    *SAMPLE_COLUMNS,
    "evaluation_status",
    "hypothetical_exit_time_et",
    "hypothetical_exit_price",
    "hypothetical_r",
    "hypothetical_exit_reason",
    "evaluation_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect VWAP mean-reversion shadow samples.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to inspect.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where saved Webull candles live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--shadow-csv",
        type=Path,
        default=Path("data/vwap_mean_reversion_shadow_samples.csv"),
        help="Append-only mean-reversion shadow journal.",
    )
    parser.add_argument("--entry-timeframe", default="M30", help="Saved entry timeframe.")
    parser.add_argument("--exit-timeframe", default="M5", help="Saved exit timeframe.")
    parser.add_argument("--reward-multiple-floor", type=float, default=0.60)
    parser.add_argument("--min-quality-score", type=int, default=4)
    parser.add_argument("--min-relative-volume", type=float, default=0.50)
    parser.add_argument("--max-relative-volume", type=float, default=1.40)
    parser.add_argument("--min-vwap-gap-pct", type=float, default=0.0015)
    parser.add_argument("--max-trend-gap-pct", type=float, default=0.0040)
    parser.add_argument(
        "--lookback-candles",
        type=int,
        default=16,
        help="Recent entry candles to inspect for missed same-session strategy samples.",
    )
    parser.add_argument(
        "--record-latest-snapshot",
        action="store_true",
        help="Append latest qualifying saved-candle samples even outside open-market freshness gates.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV or return an empty frame with the requested columns."""

    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns or [])
    if columns:
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]
    return frame


def number_value(value: Any, default: float = 0.0) -> float:
    """Return a float from CSV/pandas values."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def parse_entry_timestamp(value: object) -> pd.Timestamp:
    """Parse a stored ET timestamp."""

    timestamp = pd.Timestamp(str(value))
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(MARKET_TZ)
    return timestamp.tz_convert(MARKET_TZ)


def sample_is_fresh_for_open_market(samples: pd.DataFrame, market: dict[str, object]) -> bool:
    """Return whether latest saved sample rows are from today's open market."""

    if samples.empty or "scan_date" not in samples.columns:
        return False
    sample_dates = {str(value) for value in samples["scan_date"].dropna().unique()}
    return bool(market.get("market_is_open", False)) and sample_dates == {str(market.get("today", ""))}


def passes_tightened_filters(row: pd.Series, args: argparse.Namespace) -> bool:
    """Apply the same first-review filters as the research backtest."""

    quality_score = int(number_value(row.get("mean_reversion_quality_score")))
    relative_volume = number_value(row.get("mean_reversion_relative_volume"))
    vwap_gap_pct = number_value(row.get("mean_reversion_vwap_gap_pct"))
    trend_gap_pct = number_value(row.get("mean_reversion_trend_gap_pct"))
    return (
        quality_score >= args.min_quality_score
        and args.min_relative_volume <= relative_volume <= args.max_relative_volume
        and vwap_gap_pct >= args.min_vwap_gap_pct
        and trend_gap_pct <= args.max_trend_gap_pct
    )


def plan_for_row(row: pd.Series, direction: str, args: argparse.Namespace) -> dict[str, Any] | None:
    """Return the mean-reversion plan for a signal row."""

    entry = float(row["close"])
    if direction == "long":
        stop = float(row["low"]) * (1 - STRATEGY.stop_buffer_pct)
        target = float(row["vwap"])
        risk_per_share = entry - stop
        reward_per_share = target - entry
    else:
        stop = float(row["high"]) * (1 + STRATEGY.stop_buffer_pct)
        target = float(row["vwap"])
        risk_per_share = stop - entry
        reward_per_share = entry - target
    if risk_per_share <= 0 or reward_per_share <= 0:
        return None
    reward_multiple = reward_per_share / risk_per_share
    if reward_multiple < args.reward_multiple_floor:
        return None
    return {
        "planned_entry": round(entry, 4),
        "planned_stop": round(stop, 4),
        "planned_target": round(target, 4),
        "risk_per_share": round(risk_per_share, 4),
        "reward_multiple": round(float(reward_multiple), 4),
    }


def load_symbol_frames(symbol: str, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and enrich saved entry/exit candles for one symbol."""

    entry_path = args.data_dir / f"webull_{symbol}_{args.entry_timeframe}_candles.csv"
    exit_path = args.data_dir / f"webull_{symbol}_{args.exit_timeframe}_candles.csv"
    entry = load_candles_from_csv(entry_path, symbol)
    exits = load_candles_from_csv(exit_path, symbol)
    return add_research_columns(entry, exits)


def sample_row(
    *,
    symbol: str,
    timestamp: pd.Timestamp,
    row: pd.Series,
    direction: str,
    signal_column: str,
    observed_at_et: str,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    """Return one strategy sample row if the candle passes every rule."""

    if not bool(row.get(signal_column, False)) or not passes_tightened_filters(row, args):
        return None
    plan = plan_for_row(row, direction, args)
    if plan is None:
        return None
    return {
        "observed_at_et": observed_at_et,
        "scan_date": timestamp.tz_convert(MARKET_TZ).strftime("%Y-%m-%d")
        if getattr(timestamp, "tzinfo", None)
        else str(timestamp.date()),
        "entry_time_et": timestamp.tz_convert(MARKET_TZ).strftime("%Y-%m-%d %H:%M")
        if getattr(timestamp, "tzinfo", None)
        else str(timestamp),
        "symbol": symbol,
        "strategy": "vwap_mean_reversion",
        "direction": direction,
        "signal_column": signal_column,
        "shadow_status": "strategy_shadow_candidate",
        "shadow_reason": "Recent saved candle passed tightened mean-reversion shadow filters.",
        **plan,
        "quality_score": int(number_value(row.get("mean_reversion_quality_score"))),
        "quality_grade": str(row.get("mean_reversion_quality_grade", "")),
        "relative_volume": round(number_value(row.get("mean_reversion_relative_volume")), 4),
        "vwap_gap_pct": round(number_value(row.get("mean_reversion_vwap_gap_pct")), 4),
        "trend_gap_pct": round(number_value(row.get("mean_reversion_trend_gap_pct")), 4),
        "close": round(float(row["close"]), 4),
        "vwap": round(float(row["vwap"]), 4),
        "ema_9": round(number_value(row.get("ema_9")), 4),
        "ema_21": round(number_value(row.get("ema_21")), 4),
    }


def latest_signal_samples_for_symbol(symbol: str, args: argparse.Namespace, observed_at_et: str) -> pd.DataFrame:
    """Return recent mean-reversion shadow samples for one symbol."""

    try:
        entry, _ = load_symbol_frames(symbol, args)
    except (FileNotFoundError, ValueError):
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    if entry.empty:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)

    recent = entry.tail(max(int(args.lookback_candles), 1)).copy()
    rows: list[dict[str, Any]] = []
    for timestamp, row in recent.iterrows():
        for direction, signal_column in [
            ("long", "mean_reversion_long_signal"),
            ("short", "mean_reversion_short_signal"),
        ]:
            sample = sample_row(
                symbol=symbol,
                timestamp=timestamp,
                row=row,
                direction=direction,
                signal_column=signal_column,
                observed_at_et=observed_at_et,
                args=args,
            )
            if sample is not None:
                rows.append(sample)
    return pd.DataFrame(rows, columns=SAMPLE_COLUMNS)


def build_latest_samples(args: argparse.Namespace) -> pd.DataFrame:
    """Build recent shadow sample candidates for all configured symbols."""

    observed_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    frames = [
        latest_signal_samples_for_symbol(symbol.upper(), args, observed_at)
        for symbol in args.symbols
    ]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SAMPLE_COLUMNS)


def dedupe(existing: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Avoid appending duplicate strategy shadow samples."""

    if candidates.empty:
        return candidates
    existing_keys = set(existing[KEY_COLUMNS].astype(str).agg("|".join, axis=1))
    candidate_keys = candidates[KEY_COLUMNS].astype(str).agg("|".join, axis=1)
    return candidates[~candidate_keys.isin(existing_keys)].drop_duplicates(KEY_COLUMNS).copy()


def session_has_complete_data(exit_candles: pd.DataFrame, session_date: object) -> bool:
    """Return whether a session has closed 5m regular-session candles."""

    session = exit_candles[exit_candles["session_date"] == session_date]
    if session.empty:
        return False
    last_local = pd.to_datetime(session["local_time"]).max()
    return last_local.hour > 15 or (last_local.hour == 15 and last_local.minute >= 55)


def grade_sample(row: pd.Series, args: argparse.Namespace, cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> dict[str, Any]:
    """Grade one mean-reversion shadow sample."""

    result = {column: row.get(column, "") for column in SAMPLE_COLUMNS}
    result.update(
        {
            "evaluation_status": "pending",
            "hypothetical_exit_time_et": "",
            "hypothetical_exit_price": "",
            "hypothetical_r": "",
            "hypothetical_exit_reason": "",
            "evaluation_note": "",
        }
    )
    symbol = str(row.get("symbol", "")).upper()
    try:
        if symbol not in cache:
            cache[symbol] = load_symbol_frames(symbol, args)
        _, exits = cache[symbol]
        entry_time = parse_entry_timestamp(row.get("entry_time_et"))
        session_date = entry_time.date()
        entry = float(row["planned_entry"])
        stop = float(row["planned_stop"])
        target = float(row["planned_target"])
        risk_per_share = float(row["risk_per_share"])
    except (FileNotFoundError, ValueError, TypeError) as error:
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = str(error)
        return result

    if not session_has_complete_data(exits, session_date):
        result["evaluation_status"] = "awaiting_complete_session_data"
        result["evaluation_note"] = "Complete regular-session 5m candles are not yet available."
        return result

    exit_result = find_mean_reversion_exit(
        direction=str(row.get("direction", "")),
        entry_time=entry_time,
        entry=entry,
        stop=stop,
        target=target,
        risk_per_share=risk_per_share,
        session_date=session_date,
        exit_candles=exits,
    )
    if exit_result is None:
        result["evaluation_status"] = "no_future_exit_candle"
        result["evaluation_note"] = "No regular-session 5m candle exists after the shadow entry."
        return result

    exit_time, _, exit_price, r_result, exit_reason = exit_result
    result.update(
        {
            "evaluation_status": "matured",
            "hypothetical_exit_time_et": exit_time.tz_convert(MARKET_TZ).strftime("%Y-%m-%d %H:%M"),
            "hypothetical_exit_price": round(float(exit_price), 4),
            "hypothetical_r": round(float(r_result), 4),
            "hypothetical_exit_reason": exit_reason,
            "evaluation_note": "Mean-reversion shadow outcome only; not an official paper trade.",
        }
    )
    return result


def build_outcomes(samples: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """Grade all stored mean-reversion shadow samples."""

    if samples.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)
    cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    rows = [grade_sample(row, args, cache) for _, row in samples.iterrows()]
    frame = pd.DataFrame(rows)
    for column in OUTCOME_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[OUTCOME_COLUMNS]


def matured_summary(outcomes: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Summarize matured mean-reversion shadow outcomes."""

    matured = outcomes[outcomes["evaluation_status"] == "matured"].copy() if not outcomes.empty else pd.DataFrame()
    if matured.empty:
        return pd.DataFrame()
    matured["hypothetical_r"] = pd.to_numeric(matured["hypothetical_r"], errors="coerce")
    rows = []
    for values, group in matured.groupby(group_columns, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        r = group["hypothetical_r"].dropna()
        row = {column: value for column, value in zip(group_columns, values)}
        row.update(
            {
                "samples": int(len(group)),
                "win_rate": round(float((r > 0).mean()), 4) if not r.empty else 0.0,
                "avg_r": round(float(r.mean()), 4) if not r.empty else 0.0,
                "total_r": round(float(r.sum()), 4) if not r.empty else 0.0,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["avg_r", "samples"], ascending=[False, False])


def write_report(
    path: Path,
    candidates: pd.DataFrame,
    appended: pd.DataFrame,
    samples: pd.DataFrame,
    outcomes: pd.DataFrame,
    append_status: str,
    shadow_csv: Path,
    outcomes_csv: Path,
) -> None:
    """Write a readable mean-reversion shadow report."""

    status = outcomes.groupby("evaluation_status").size().reset_index(name="samples") if not outcomes.empty else pd.DataFrame()
    recent_samples = samples.tail(20) if not samples.empty else pd.DataFrame(columns=SAMPLE_COLUMNS)
    recent_outcomes = outcomes[outcomes["evaluation_status"] == "matured"].tail(20) if not outcomes.empty else pd.DataFrame(columns=OUTCOME_COLUMNS)
    path.write_text(
        f"""# VWAP Mean Reversion Shadow Samples

This report collects forward-style shadow samples for the Strategy Vault's
VWAP Mean Reversion candidate.

Important: this is research and paper-validation only. These samples do not
count toward official paper gates, place broker orders, create broker alerts,
or change scanner rules.

## Latest Collection Attempt

```text
Append status: {append_status}
Recent strategy shadow candidates: {len(candidates)}
New strategy shadow samples appended: {len(appended)}
Total stored strategy shadow samples: {len(samples)}
```

## Recent Strategy Shadow Candidates

{markdown_table(candidates)}

## Evaluation Status

{markdown_table(status)}

## Outcome By Symbol And Direction

{markdown_table(matured_summary(outcomes, ["symbol", "direction"]))}

## Recent Stored Samples

{markdown_table(recent_samples)}

## Recent Matured Outcomes

{markdown_table(recent_outcomes)}

## Guardrail

```text
Mean-reversion shadow samples stay separate from official paper trades.
They are used only to decide whether this strategy deserves paper-watch review.
```

## Files

```text
{shadow_csv}
{outcomes_csv}
{path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_csv_or_empty(args.shadow_csv, SAMPLE_COLUMNS)
    candidates = build_latest_samples(args)
    market = market_refresh_state()
    appended = pd.DataFrame(columns=SAMPLE_COLUMNS)
    if args.record_latest_snapshot or sample_is_fresh_for_open_market(candidates, market):
        appended = dedupe(existing, candidates)
        append_status = "appended_new_strategy_shadow_samples" if not appended.empty else "no_append_duplicate_strategy_shadow_samples"
    else:
        append_status = "no_append_candles_not_fresh_during_open_market"

    combined = pd.concat([existing, appended], ignore_index=True)
    if not appended.empty or not args.shadow_csv.exists():
        args.shadow_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.shadow_csv, index=False)

    outcomes = build_outcomes(combined, args)
    outcomes_csv = args.output_dir / "vwap_mean_reversion_shadow_outcomes.csv"
    report_path = args.output_dir / "vwap_mean_reversion_shadow_samples.md"
    outcomes.to_csv(outcomes_csv, index=False)
    write_report(report_path, candidates, appended, combined, outcomes, append_status, args.shadow_csv, outcomes_csv)

    matured = int((outcomes["evaluation_status"] == "matured").sum()) if not outcomes.empty else 0
    print(f"Mean reversion shadow append status: {append_status}")
    print(f"Recent strategy shadow candidates: {len(candidates)}")
    print(f"New strategy shadow samples appended: {len(appended)}")
    print(f"Matured strategy shadow outcomes: {matured}")
    print(f"Saved strategy shadow outcomes CSV: {outcomes_csv}")
    print(f"Saved strategy shadow report: {report_path}")


if __name__ == "__main__":
    main()
