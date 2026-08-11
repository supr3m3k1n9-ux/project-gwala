"""Research-only inventory and experiments for engineering thresholds.

The Parameter Lab measures numeric implementation parameters without changing
production settings. It helps separate Roy's trading philosophy from later
engineering thresholds that should earn evidence over time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from backtesting.engine import find_exit, find_short_exit
from config.filter_policy import OPTIONS_CONTRACT_THRESHOLDS, PAPER_GATE_THRESHOLDS
from config.settings import ACCOUNT, STRATEGY
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from run_grace_lane_backtest import (
    combined_exit_candles,
    enriched_candles,
    next_same_session_row,
    plan_for,
)
from run_webull_watchlist import EXIT_PROFILES
from strategies.scanner_adapters import scanner_adapter_for_entry, selected_signal_column


ACCOUNT_SIZE = 10_000.0
LAB_VERSION = "parameter_lab_v1"


@dataclass(frozen=True)
class ParameterDefinition:
    """One numeric engineering parameter tracked by the lab."""

    parameter_id: str
    current_value: float
    why_it_exists: str
    date_introduced: str
    source: str
    confidence_level: str
    last_tested: str
    historical_performance: str
    experiment_status: str
    experiment_metric: str
    comparison: str
    default_test_values: tuple[float, ...]


@dataclass(frozen=True)
class LabCandidate:
    """One replayed candidate window used for threshold experiments."""

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
    r_result: float
    mae_r: float
    mfe_r: float
    exit_reason: str


def parameter_inventory() -> pd.DataFrame:
    """Return the current Parameter Lab inventory."""

    rows = [
        ParameterDefinition(
            "paper_gate.a_min_check_score",
            float(PAPER_GATE_THRESHOLDS["a_min_check_score"]),
            "Require most current-candle scanner conditions to align before A-tier validation.",
            "Paper Gate v2 threshold; documented by 2026-06-25 Signal Origin Audit",
            "Engineering assumption",
            "weak",
            "2026-06-25 Signal Origin Audit",
            "No isolated proof for 0.78; broader playbook has positive expectancy.",
            "experiment_ready",
            "check_score",
            ">=",
            (0.70, 0.72, 0.74, 0.76, 0.78, 0.80),
        ),
        ParameterDefinition(
            "paper_gate.a_min_quality_score",
            float(PAPER_GATE_THRESHOLDS["a_min_quality_score"]),
            "Keep A-tier current-candle samples high quality without requiring every elite filter.",
            "Paper Gate v2 threshold; documented by 2026-06-25 Signal Origin Audit",
            "Quality improvement",
            "weak",
            "2026-06-25 Signal Origin Audit",
            "Quality-entry evidence is mixed by symbol; threshold is not isolated yet.",
            "experiment_ready",
            "quality_score",
            ">=",
            (4.0, 5.0, 6.0, 7.0, 8.0),
        ),
        ParameterDefinition(
            "paper_gate.b_min_check_score",
            float(PAPER_GATE_THRESHOLDS["b_min_check_score"]),
            "Let B-tier collect delayed samples while requiring majority condition alignment.",
            "2026-06-16 grace-lane implementation",
            "Quality improvement",
            "medium",
            "2026-06-16 grace-lane replay",
            "Grace lane replay supported throughput with quality, but not this exact cutoff.",
            "experiment_ready",
            "check_score",
            ">=",
            (0.55, 0.60, 0.65, 0.70, 0.75),
        ),
        ParameterDefinition(
            "paper_gate.b_min_quality_score",
            float(PAPER_GATE_THRESHOLDS["b_min_quality_score"]),
            "Stop B-tier grace from becoming a low-quality timing rescue.",
            "2026-06-16 grace-lane implementation",
            "Quality improvement",
            "weak",
            "2026-06-25 Signal Origin Audit",
            "No isolated proof for 5; supports grace-lane quality discipline.",
            "experiment_ready",
            "quality_score",
            ">=",
            (3.0, 4.0, 5.0, 6.0, 7.0),
        ),
        ParameterDefinition(
            "paper_gate.b_min_room_to_target_r",
            float(PAPER_GATE_THRESHOLDS["b_min_room_to_target_r"]),
            "Require positive reward room for B-tier validation.",
            "Paper Gate v2 threshold; documented by 2026-06-25 Signal Origin Audit",
            "Risk reduction",
            "medium",
            "2026-05-22 weakness analysis and 2026-06-25 audit",
            "Room-to-target matters in weak-pocket evidence, but exact >0R is not isolated.",
            "experiment_ready",
            "room_to_target_r",
            ">",
            (-0.25, 0.0, 0.25, 0.50, 0.75, 1.0),
        ),
        ParameterDefinition(
            "strategy.min_relative_volume",
            float(STRATEGY.min_relative_volume),
            "Require participation for stricter quality signals.",
            "Initial quality-filter implementation",
            "Quality improvement",
            "weak",
            "2026-05-22 weakness and quality-entry reviews",
            "Relative-volume pockets show mixed symbol-specific evidence.",
            "experiment_ready",
            "relative_volume",
            ">=",
            (0.50, 0.70, 0.90, 1.00, 1.20, 1.50),
        ),
        ParameterDefinition(
            "strategy.min_room_to_resistance_r",
            float(STRATEGY.min_room_to_resistance_r),
            "Require enough room to target/resistance for stricter quality signals.",
            "Initial quality-filter implementation",
            "Quality improvement",
            "medium",
            "2026-05-22 weakness analysis",
            "SPY room 0.75R-1.0R was a weak pocket; exact 1.25R needs isolation.",
            "experiment_ready",
            "room_to_target_r",
            ">=",
            (0.0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50),
        ),
        ParameterDefinition(
            "account.risk_per_trade_pct",
            float(ACCOUNT.risk_per_trade_pct),
            "Keep paper sizing conservative while collecting evidence.",
            "Initial risk/account setting",
            "Risk reduction",
            "strong",
            "Ongoing paper workflow",
            "Risk control protects drawdown; not an expectancy-alpha parameter.",
            "inventory_only",
            "",
            "",
            (),
        ),
        ParameterDefinition(
            "options.max_bid_ask_spread_pct",
            float(OPTIONS_CONTRACT_THRESHOLDS["max_bid_ask_spread_pct"]),
            "Avoid untradable or unreliable options fills in official validation samples.",
            "2026-06-15 Options Contract Gate",
            "Risk reduction",
            "weak",
            "Never independently validated",
            "Execution-quality assumption; no isolated R evidence yet.",
            "inventory_only",
            "",
            "",
            (),
        ),
        ParameterDefinition(
            "options.min_volume",
            float(OPTIONS_CONTRACT_THRESHOLDS["min_volume"]),
            "Require basic contract liquidity.",
            "2026-06-15 Options Contract Gate",
            "Risk reduction",
            "weak",
            "Never independently validated",
            "Execution-quality assumption; no isolated R evidence yet.",
            "inventory_only",
            "",
            "",
            (),
        ),
        ParameterDefinition(
            "options.min_open_interest",
            float(OPTIONS_CONTRACT_THRESHOLDS["min_open_interest"]),
            "Require basic open interest for credible options paper samples.",
            "2026-06-15 Options Contract Gate",
            "Risk reduction",
            "weak",
            "Never independently validated",
            "Execution-quality assumption; no isolated R evidence yet.",
            "inventory_only",
            "",
            "",
            (),
        ),
        ParameterDefinition(
            "candidate_selection.min_approved_trades",
            10.0,
            "Prevent tiny backtest samples from being labeled approved.",
            "2026-05-22 confidence filter",
            "Risk reduction",
            "medium",
            "2026-05-22 deeper history review",
            "More history made several promising names reject, preventing overtrust.",
            "inventory_only",
            "",
            "",
            (),
        ),
    ]
    return pd.DataFrame([asdict(row) for row in rows])


def inventory_row(parameter_id: str) -> pd.Series:
    """Return one inventory row by id."""

    inventory = parameter_inventory()
    matches = inventory[inventory["parameter_id"] == parameter_id]
    if matches.empty:
        raise ValueError(f"Unknown Parameter Lab parameter: {parameter_id}")
    return matches.iloc[0]


def number(value: object, default: float = 0.0) -> float:
    """Return a finite number."""

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return default
    return float(parsed)


def condition_score(row: pd.Series, entry: PlaybookEntry, signal_column: str) -> float:
    """Return the scanner condition pass ratio for one candle."""

    checks = scanner_adapter_for_entry(entry).condition_checks(row, entry, signal_column)
    total = len(checks)
    if total <= 0:
        return 0.0
    passed = sum(1 for _, passed_check in checks if passed_check)
    return round(passed / total, 4)


def mfe_r(
    *,
    direction: str,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    session_date: object,
    entry_price: float,
    risk_per_share: float,
    exit_candles: pd.DataFrame,
) -> float:
    """Return maximum favorable excursion in R."""

    future = exit_candles[
        (exit_candles.index > entry_time)
        & (exit_candles.index <= exit_time)
        & (exit_candles["session_date"] == session_date)
        & (exit_candles["regular_session"])
    ]
    if future.empty or risk_per_share <= 0:
        return 0.0
    if direction == "short":
        favorable = (entry_price - float(future["low"].min())) / risk_per_share
    else:
        favorable = (float(future["high"].max()) - entry_price) / risk_per_share
    return round(max(0.0, favorable), 4)


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
    """Return maximum adverse excursion in R."""

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
) -> LabCandidate | None:
    """Simulate one candidate without applying Parameter Lab thresholds."""

    plan = plan_for(row, entry)
    if plan is None:
        return None

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
    return LabCandidate(
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
        check_score=condition_score(row, entry, signal_column),
        relative_volume=round(float(fields.relative_volume), 4),
        room_to_target_r=round(float(fields.room_to_target_r), 4),
        planned_entry=round(plan["planned_entry"], 4),
        planned_stop=round(plan["planned_stop"], 4),
        planned_target=round(plan["planned_target"], 4),
        risk_per_share=round(plan["risk_per_share"], 4),
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
        mfe_r=mfe_r(
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


def build_candidate_universe(
    *,
    data_dir: Path,
    playbook: str,
    lookback_days: int,
    market_regime_symbol: str = "SPY",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Replay candidate windows for Parameter Lab experiments."""

    candidates: list[LabCandidate] = []
    errors: list[dict[str, str]] = []
    coverage: dict[str, dict[str, str]] = {}
    exit_cache: dict[str, pd.DataFrame] = {}
    lookback_end: pd.Timestamp | None = None

    for entry in PLAYBOOKS[playbook]:
        try:
            entry_candles, exit_candles = enriched_candles(entry, data_dir, market_regime_symbol, exit_cache)
        except Exception as error:  # noqa: BLE001 - experiments should report data gaps instead of stopping.
            errors.append({"symbol": entry.symbol, "setup": entry.setup_name, "error": str(error)})
            continue

        if entry_candles.empty:
            continue
        if lookback_end is None or entry_candles.index.max() > lookback_end:
            lookback_end = entry_candles.index.max()

        cutoff = entry_candles.index.max() - pd.Timedelta(days=lookback_days)
        replay_rows = entry_candles[entry_candles.index >= cutoff]
        signal_column = selected_signal_column(entry)
        signal_rows = replay_rows[replay_rows[signal_column].fillna(False).astype(bool)]

        coverage[f"{entry.symbol.upper()} {entry.setup_name}"] = {
            "m30_start": str(entry_candles.index.min()),
            "m30_end": str(entry_candles.index.max()),
            "m30_rows": str(len(entry_candles)),
            "m5_start": str(exit_candles.index.min()),
            "m5_end": str(exit_candles.index.max()),
            "m5_rows": str(len(exit_candles)),
        }

        for signal_time, signal_row in signal_rows.iterrows():
            current = simulate_candidate(
                lane="A",
                source_signal_time=signal_time,
                candidate_time=signal_time,
                row=signal_row,
                entry=entry,
                exit_candles=exit_candles,
                signal_column=signal_column,
            )
            if current is not None:
                candidates.append(current)

            next_row = next_same_session_row(entry_candles, signal_time, signal_row.get("session_date"))
            if next_row is None:
                continue
            grace_time, grace_row = next_row
            grace = simulate_candidate(
                lane="B",
                source_signal_time=signal_time,
                candidate_time=grace_time,
                row=grace_row,
                entry=entry,
                exit_candles=exit_candles,
                signal_column=signal_column,
            )
            if grace is not None:
                candidates.append(grace)

    detail = pd.DataFrame([asdict(candidate) for candidate in candidates])
    metadata = {
        "lab_version": LAB_VERSION,
        "playbook": playbook,
        "lookback_days": lookback_days,
        "lookback_end": str(lookback_end) if lookback_end is not None else "",
        "lookback_start": str(lookback_end - pd.Timedelta(days=lookback_days)) if lookback_end is not None else "",
        "coverage": coverage,
        "errors": errors,
        "guardrail": (
            "Parameter Lab is research-only. It never changes production thresholds, "
            "paper logs, broker orders, alerts, or trading philosophy."
        ),
    }
    return detail, metadata


def finite_profit_factor(r: pd.Series) -> float | str:
    """Return profit factor from R results."""

    wins = r[r > 0]
    losses = r[r < 0]
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    if gross_loss <= 0:
        return "inf" if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 4)


def summarize_performance(frame: pd.DataFrame) -> dict[str, Any]:
    """Return the experiment metrics for one threshold value."""

    if frame.empty:
        return {
            "candidate_count": 0,
            "win_rate": 0.0,
            "average_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "average_mae_r": 0.0,
            "average_mfe_r": 0.0,
        }
    r = frame["r_result"].astype(float)
    equity = r.cumsum()
    drawdown = equity - equity.cummax()
    return {
        "candidate_count": int(len(frame)),
        "win_rate": round(float((r > 0).mean()), 4),
        "average_r": round(float(r.mean()), 4),
        "profit_factor": finite_profit_factor(r),
        "max_drawdown_r": round(float(drawdown.min()), 4),
        "average_mae_r": round(float(frame["mae_r"].astype(float).mean()), 4),
        "average_mfe_r": round(float(frame["mfe_r"].astype(float).mean()), 4),
    }


def apply_threshold(frame: pd.DataFrame, metric: str, comparison: str, threshold: float) -> pd.DataFrame:
    """Return candidate rows passing one lab threshold."""

    values = pd.to_numeric(frame[metric], errors="coerce")
    if comparison == ">":
        return frame[values > threshold].copy()
    if comparison == ">=":
        return frame[values >= threshold].copy()
    if comparison == "<=":
        return frame[values <= threshold].copy()
    if comparison == "<":
        return frame[values < threshold].copy()
    raise ValueError(f"Unsupported Parameter Lab comparison: {comparison}")


def experiment_values(parameter: pd.Series, override_values: Iterable[float] | None = None) -> list[float]:
    """Return sorted unique test values for one parameter."""

    if override_values is not None:
        return sorted({float(value) for value in override_values})
    raw = parameter.get("default_test_values", ())
    if isinstance(raw, str):
        raw_values = [item.strip() for item in raw.strip("()[]").split(",") if item.strip()]
        return sorted({float(value) for value in raw_values})
    return sorted({float(value) for value in raw})


def run_threshold_experiment(
    candidates: pd.DataFrame,
    parameter_id: str,
    values: Iterable[float] | None = None,
) -> pd.DataFrame:
    """Run one isolated threshold experiment over the candidate universe."""

    parameter = inventory_row(parameter_id)
    if parameter["experiment_status"] != "experiment_ready":
        raise ValueError(f"Parameter is inventory-only and has no threshold experiment: {parameter_id}")

    frame = candidates.copy()
    if parameter_id.startswith("paper_gate.a_"):
        frame = frame[frame["lane"] == "A"].copy()
    elif parameter_id.startswith("paper_gate.b_"):
        frame = frame[frame["lane"] == "B"].copy()

    metric = str(parameter["experiment_metric"])
    comparison = str(parameter["comparison"])
    rows: list[dict[str, Any]] = []
    for value in experiment_values(parameter, values):
        passed = apply_threshold(frame, metric, comparison, value)
        rows.append(
            {
                "parameter_id": parameter_id,
                "tested_value": value,
                "current_value": float(parameter["current_value"]),
                "is_current_value": value == float(parameter["current_value"]),
                "metric": metric,
                "comparison": comparison,
                **summarize_performance(passed),
            }
        )
    return pd.DataFrame(rows)


def evidence_groups(inventory: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split inventory into the requested evidence sections."""

    return {
        "strong": inventory[inventory["confidence_level"] == "strong"].copy(),
        "weak": inventory[inventory["confidence_level"] == "weak"].copy(),
        "never": inventory[inventory["last_tested"].astype(str).str.contains("Never", case=False, na=False)].copy(),
    }

