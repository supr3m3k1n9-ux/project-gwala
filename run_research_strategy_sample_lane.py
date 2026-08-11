"""Shared shadow and forward-observation lanes for research strategies.

The strategy-specific wrappers provide signal rules, plan construction, and
exit simulation. This module handles the boring evidence-lane mechanics:
recent candle inspection, duplicate prevention, outcome grading, and reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from config.market_calendar import MARKET_TZ
from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table
from run_vwap_mean_reversion_shadow_samples import (
    dedupe,
    matured_summary,
    parse_entry_timestamp,
    read_csv_or_empty,
    sample_is_fresh_for_open_market,
    session_has_complete_data,
)


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
    "trend_gap_pct",
    "gap_pct",
    "range_width_pct",
    "close",
    "vwap",
    "ema_9",
    "ema_21",
]
OUTCOME_COLUMNS = [
    *SAMPLE_COLUMNS,
    "evaluation_status",
    "hypothetical_exit_time_et",
    "hypothetical_exit_price",
    "hypothetical_r",
    "hypothetical_exit_reason",
    "evaluation_note",
]
OBSERVATION_COLUMNS = [
    column.replace("shadow_status", "observation_status").replace("shadow_reason", "observation_reason")
    for column in SAMPLE_COLUMNS
]
OBSERVATION_OUTCOME_COLUMNS = [
    column.replace("shadow_status", "observation_status").replace("shadow_reason", "observation_reason")
    for column in OUTCOME_COLUMNS
]


@dataclass(frozen=True)
class SampleLaneSpec:
    """Strategy-specific hooks for the shared sample lane."""

    strategy_id: str
    strategy_name: str
    stem: str
    signal_pairs: list[tuple[str, str]]
    load_frames: Callable[[str, Any], tuple[pd.DataFrame, pd.DataFrame]]
    passes_filters: Callable[[pd.Series, Any], bool]
    plan_for_row: Callable[[pd.Series, str, Any], dict[str, Any] | None]
    find_exit: Callable[..., tuple[pd.Timestamp, pd.Series, float, float, str] | None]
    quality_score_column: str
    quality_grade_column: str
    relative_volume_column: str
    trend_gap_column: str
    gap_column: str | None = None
    range_width_column: str | None = None


def number_value(value: Any, default: float = 0.0) -> float:
    """Return a float from CSV/pandas values."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def metric_value(row: pd.Series, column: str | None) -> float:
    """Return a rounded metric value for optional strategy columns."""

    if not column:
        return 0.0
    return round(number_value(row.get(column)), 4)


def timestamp_to_et(timestamp: pd.Timestamp) -> pd.Timestamp:
    """Return a timestamp converted or localized to market time."""

    if getattr(timestamp, "tzinfo", None):
        return timestamp.tz_convert(MARKET_TZ)
    return timestamp.tz_localize(MARKET_TZ)


def sample_row(
    *,
    spec: SampleLaneSpec,
    symbol: str,
    timestamp: pd.Timestamp,
    row: pd.Series,
    direction: str,
    signal_column: str,
    observed_at_et: str,
    args: Any,
) -> dict[str, Any] | None:
    """Return one strategy sample row if the candle passes every rule."""

    if not bool(row.get(signal_column, False)) or not spec.passes_filters(row, args):
        return None
    plan = spec.plan_for_row(row, direction, args)
    if plan is None:
        return None
    entry_time = timestamp_to_et(timestamp)
    return {
        "observed_at_et": observed_at_et,
        "scan_date": entry_time.strftime("%Y-%m-%d"),
        "entry_time_et": entry_time.strftime("%Y-%m-%d %H:%M"),
        "symbol": symbol,
        "strategy": spec.strategy_id,
        "direction": direction,
        "signal_column": signal_column,
        "shadow_status": "strategy_shadow_candidate",
        "shadow_reason": f"Recent saved candle passed tightened {spec.strategy_name} shadow filters.",
        **plan,
        "quality_score": int(number_value(row.get(spec.quality_score_column))),
        "quality_grade": str(row.get(spec.quality_grade_column, "")),
        "relative_volume": metric_value(row, spec.relative_volume_column),
        "trend_gap_pct": metric_value(row, spec.trend_gap_column),
        "gap_pct": metric_value(row, spec.gap_column),
        "range_width_pct": metric_value(row, spec.range_width_column),
        "close": round(float(row["close"]), 4),
        "vwap": round(float(row["vwap"]), 4),
        "ema_9": round(number_value(row.get("ema_9")), 4),
        "ema_21": round(number_value(row.get("ema_21")), 4),
    }


def latest_signal_samples_for_symbol(
    spec: SampleLaneSpec,
    symbol: str,
    args: Any,
    observed_at_et: str,
) -> pd.DataFrame:
    """Return recent strategy shadow samples for one symbol."""

    try:
        entry, _ = spec.load_frames(symbol, args)
    except (FileNotFoundError, ValueError):
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    if entry.empty:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)

    recent = entry.tail(max(int(args.lookback_candles), 1)).copy()
    rows: list[dict[str, Any]] = []
    for timestamp, row in recent.iterrows():
        for direction, signal_column in spec.signal_pairs:
            sample = sample_row(
                spec=spec,
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


def build_latest_samples(spec: SampleLaneSpec, args: Any) -> pd.DataFrame:
    """Build recent shadow sample candidates for all configured symbols."""

    observed_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    frames = [
        latest_signal_samples_for_symbol(spec, symbol.upper(), args, observed_at)
        for symbol in args.symbols
    ]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SAMPLE_COLUMNS)


def grade_sample(
    spec: SampleLaneSpec,
    row: pd.Series,
    args: Any,
    cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
) -> dict[str, Any]:
    """Grade one strategy sample."""

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
            cache[symbol] = spec.load_frames(symbol, args)
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

    exit_result = spec.find_exit(
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
            "evaluation_note": f"{spec.strategy_name} shadow outcome only; not an official paper trade.",
        }
    )
    return result


def build_outcomes(spec: SampleLaneSpec, samples: pd.DataFrame, args: Any) -> pd.DataFrame:
    """Grade all stored strategy samples."""

    if samples.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)
    cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    rows = [grade_sample(spec, row, args, cache) for _, row in samples.iterrows()]
    frame = pd.DataFrame(rows)
    for column in OUTCOME_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[OUTCOME_COLUMNS]


def shadow_to_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert shadow-shaped candidate rows to forward-observation rows."""

    if frame.empty:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    result = frame.rename(columns={"shadow_status": "observation_status", "shadow_reason": "observation_reason"}).copy()
    result["observation_status"] = "strategy_forward_observation"
    result["observation_reason"] = "Recent saved candle passed tightened strategy forward-observation filters."
    for column in OBSERVATION_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[OBSERVATION_COLUMNS]


def observations_to_shadow(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert observation rows back to the shared grader schema."""

    if frame.empty:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    result = frame.rename(columns={"observation_status": "shadow_status", "observation_reason": "shadow_reason"}).copy()
    for column in SAMPLE_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[SAMPLE_COLUMNS]


def shadow_outcomes_to_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert shared grader outcomes to forward-observation outcome rows."""

    if frame.empty:
        return pd.DataFrame(columns=OBSERVATION_OUTCOME_COLUMNS)
    result = frame.rename(columns={"shadow_status": "observation_status", "shadow_reason": "observation_reason"}).copy()
    result["evaluation_note"] = result["evaluation_note"].astype(str).str.replace(
        "shadow outcome only",
        "forward observation outcome only",
        regex=False,
    )
    for column in OBSERVATION_OUTCOME_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[OBSERVATION_OUTCOME_COLUMNS]


def observation_outcomes_to_shadow(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert observation outcome rows back to the shared summary schema."""

    if frame.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)
    result = frame.rename(columns={"observation_status": "shadow_status", "observation_reason": "shadow_reason"}).copy()
    for column in OUTCOME_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[OUTCOME_COLUMNS]


def observation_dedupe(existing: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate observation rows using the same signal identity keys."""

    if candidates.empty:
        return candidates
    return shadow_to_observations(dedupe(observations_to_shadow(existing), observations_to_shadow(candidates)))


def build_observation_outcomes(spec: SampleLaneSpec, observations: pd.DataFrame, args: Any) -> pd.DataFrame:
    """Grade all stored forward observations."""

    return shadow_outcomes_to_observations(build_outcomes(spec, observations_to_shadow(observations), args))


def write_shadow_report(
    *,
    spec: SampleLaneSpec,
    path: Path,
    candidates: pd.DataFrame,
    appended: pd.DataFrame,
    samples: pd.DataFrame,
    outcomes: pd.DataFrame,
    append_status: str,
    shadow_csv: Path,
    outcomes_csv: Path,
) -> None:
    """Write a readable shadow-sample report."""

    status = outcomes.groupby("evaluation_status").size().reset_index(name="samples") if not outcomes.empty else pd.DataFrame()
    recent_samples = samples.tail(20) if not samples.empty else pd.DataFrame(columns=SAMPLE_COLUMNS)
    recent_outcomes = outcomes[outcomes["evaluation_status"] == "matured"].tail(20) if not outcomes.empty else pd.DataFrame(columns=OUTCOME_COLUMNS)
    path.write_text(
        f"""# {spec.strategy_name} Shadow Samples

This report collects forward-style shadow samples for the Strategy Vault's
{spec.strategy_name} candidate.

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
{spec.strategy_name} shadow samples stay separate from official paper trades.
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


def write_forward_report(
    *,
    spec: SampleLaneSpec,
    path: Path,
    candidates: pd.DataFrame,
    appended: pd.DataFrame,
    observations: pd.DataFrame,
    outcomes: pd.DataFrame,
    append_status: str,
    observations_csv: Path,
    outcomes_csv: Path,
) -> None:
    """Write a readable forward-observation report."""

    status = outcomes.groupby("evaluation_status").size().reset_index(name="observations") if not outcomes.empty else pd.DataFrame()
    recent_observations = observations.tail(20) if not observations.empty else pd.DataFrame(columns=OBSERVATION_COLUMNS)
    recent_matured = outcomes[outcomes["evaluation_status"] == "matured"].tail(20) if not outcomes.empty else pd.DataFrame(columns=OBSERVATION_OUTCOME_COLUMNS)
    path.write_text(
        f"""# {spec.strategy_name} Forward Observations

This report collects forward observations for the Strategy Vault's
{spec.strategy_name} candidate when the latest saved candles pass tightened
strategy filters.

Important: this is research and paper-validation only. These observations do
not count toward official paper gates, place broker orders, create broker
alerts, or change scanner rules.

## Latest Collection Attempt

```text
Append status: {append_status}
Recent forward observation candidates: {len(candidates)}
New forward observations appended: {len(appended)}
Total stored forward observations: {len(observations)}
```

## Recent Forward Observation Candidates

{markdown_table(candidates)}

## Evaluation Status

{markdown_table(status)}

## Outcome By Symbol And Direction

{markdown_table(matured_summary(observation_outcomes_to_shadow(outcomes), ["symbol", "direction"]))}

## Recent Stored Observations

{markdown_table(recent_observations)}

## Recent Matured Outcomes

{markdown_table(recent_matured)}

## Guardrail

```text
{spec.strategy_name} forward observations stay separate from official paper
trades. They are used only to decide whether this strategy deserves paper-watch
review.
```

## Files

```text
{observations_csv}
{outcomes_csv}
{path}
```
""",
        encoding="utf-8",
    )


def run_shadow_lane(spec: SampleLaneSpec, args: Any) -> dict[str, Any]:
    """Run one strategy's shadow-sample lane."""

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_csv_or_empty(args.shadow_csv, SAMPLE_COLUMNS)
    candidates = build_latest_samples(spec, args)
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

    outcomes = build_outcomes(spec, combined, args)
    outcomes_csv = args.output_dir / f"{spec.stem}_shadow_outcomes.csv"
    report_path = args.output_dir / f"{spec.stem}_shadow_samples.md"
    outcomes.to_csv(outcomes_csv, index=False)
    write_shadow_report(
        spec=spec,
        path=report_path,
        candidates=candidates,
        appended=appended,
        samples=combined,
        outcomes=outcomes,
        append_status=append_status,
        shadow_csv=args.shadow_csv,
        outcomes_csv=outcomes_csv,
    )
    return {
        "append_status": append_status,
        "candidates": len(candidates),
        "appended": len(appended),
        "matured": int((outcomes["evaluation_status"] == "matured").sum()) if not outcomes.empty else 0,
        "outcomes_csv": outcomes_csv,
        "report_path": report_path,
    }


def run_forward_lane(spec: SampleLaneSpec, args: Any) -> dict[str, Any]:
    """Run one strategy's forward-observation lane."""

    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_csv_or_empty(args.observations_csv, OBSERVATION_COLUMNS)
    candidates = shadow_to_observations(build_latest_samples(spec, args))
    market = market_refresh_state()
    appended = pd.DataFrame(columns=OBSERVATION_COLUMNS)
    if args.record_latest_snapshot or sample_is_fresh_for_open_market(observations_to_shadow(candidates), market):
        appended = observation_dedupe(existing, candidates)
        append_status = "appended_new_strategy_forward_observations" if not appended.empty else "no_append_duplicate_strategy_forward_observations"
    else:
        append_status = "no_append_candles_not_fresh_during_open_market"

    combined = pd.concat([existing, appended], ignore_index=True)
    if not appended.empty or not args.observations_csv.exists():
        args.observations_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.observations_csv, index=False)

    outcomes = build_observation_outcomes(spec, combined, args)
    outcomes_csv = args.output_dir / f"{spec.stem}_forward_observation_results.csv"
    report_path = args.output_dir / f"{spec.stem}_forward_observations.md"
    outcomes.to_csv(outcomes_csv, index=False)
    write_forward_report(
        spec=spec,
        path=report_path,
        candidates=candidates,
        appended=appended,
        observations=combined,
        outcomes=outcomes,
        append_status=append_status,
        observations_csv=args.observations_csv,
        outcomes_csv=outcomes_csv,
    )
    return {
        "append_status": append_status,
        "candidates": len(candidates),
        "appended": len(appended),
        "matured": int((outcomes["evaluation_status"] == "matured").sum()) if not outcomes.empty else 0,
        "outcomes_csv": outcomes_csv,
        "report_path": report_path,
    }
