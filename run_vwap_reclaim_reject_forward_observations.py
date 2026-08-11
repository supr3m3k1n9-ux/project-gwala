"""Collect VWAP reclaim/reject forward observations.

This records qualifying VWAP reclaim/reject signals from the latest saved
candles into a strategy-specific forward observation journal. It is separate
from official paper trades and from the shadow-sample journal.

Important: observations are not paper trades, broker alerts, or execution
instructions. They do not count toward the official 30/60 paper-trade gates.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table
from run_vwap_reclaim_reject_shadow_samples import (
    DEFAULT_SYMBOLS,
    OUTCOME_COLUMNS as SHADOW_OUTCOME_COLUMNS,
    SAMPLE_COLUMNS as SHADOW_SAMPLE_COLUMNS,
    build_latest_samples,
    build_outcomes as build_shadow_outcomes,
    dedupe,
    matured_summary,
    read_csv_or_empty,
    sample_is_fresh_for_open_market,
)


OBSERVATION_COLUMNS = [
    column.replace("shadow_status", "observation_status").replace("shadow_reason", "observation_reason")
    for column in SHADOW_SAMPLE_COLUMNS
]
OUTCOME_COLUMNS = [
    column.replace("shadow_status", "observation_status").replace("shadow_reason", "observation_reason")
    for column in SHADOW_OUTCOME_COLUMNS
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect VWAP reclaim/reject forward observations.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to inspect.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where saved Webull candles live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--observations-csv",
        type=Path,
        default=Path("data/vwap_reclaim_reject_forward_observations.csv"),
        help="Append-only VWAP reclaim/reject forward observation journal.",
    )
    parser.add_argument("--entry-timeframe", default="M30", help="Saved entry timeframe.")
    parser.add_argument("--exit-timeframe", default="M5", help="Saved exit timeframe.")
    parser.add_argument("--target-r-multiple", type=float, default=1.25)
    parser.add_argument("--reward-multiple-floor", type=float, default=0.80)
    parser.add_argument("--min-quality-score", type=int, default=4)
    parser.add_argument("--min-relative-volume", type=float, default=0.70)
    parser.add_argument("--max-relative-volume", type=float, default=2.50)
    parser.add_argument("--max-vwap-gap-pct", type=float, default=0.0120)
    parser.add_argument("--max-trend-gap-pct", type=float, default=0.0100)
    parser.add_argument(
        "--lookback-candles",
        type=int,
        default=16,
        help="Recent entry candles to inspect for missed same-session strategy observations.",
    )
    parser.add_argument(
        "--record-latest-snapshot",
        action="store_true",
        help="Append latest qualifying saved-candle observations even outside open-market freshness gates.",
    )
    return parser.parse_args()


def shadow_to_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert shadow-shaped candidate rows to forward-observation rows."""

    if frame.empty:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    result = frame.rename(
        columns={
            "shadow_status": "observation_status",
            "shadow_reason": "observation_reason",
        }
    ).copy()
    result["observation_status"] = "strategy_forward_observation"
    result["observation_reason"] = "Recent saved candle passed tightened VWAP reclaim/reject forward-observation filters."
    for column in OBSERVATION_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[OBSERVATION_COLUMNS]


def observations_to_shadow(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert observation rows back to the shared grader schema."""

    if frame.empty:
        return pd.DataFrame(columns=SHADOW_SAMPLE_COLUMNS)
    result = frame.rename(
        columns={
            "observation_status": "shadow_status",
            "observation_reason": "shadow_reason",
        }
    ).copy()
    for column in SHADOW_SAMPLE_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[SHADOW_SAMPLE_COLUMNS]


def shadow_outcomes_to_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert shared grader outcomes to forward-observation outcome rows."""

    if frame.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)
    result = frame.rename(
        columns={
            "shadow_status": "observation_status",
            "shadow_reason": "observation_reason",
        }
    ).copy()
    result["evaluation_note"] = result["evaluation_note"].astype(str).str.replace(
        "VWAP reclaim/reject shadow outcome only",
        "VWAP reclaim/reject forward observation outcome only",
        regex=False,
    )
    for column in OUTCOME_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[OUTCOME_COLUMNS]


def observation_outcomes_to_shadow(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert observation outcome rows back to the shared summary schema."""

    if frame.empty:
        return pd.DataFrame(columns=SHADOW_OUTCOME_COLUMNS)
    result = frame.rename(
        columns={
            "observation_status": "shadow_status",
            "observation_reason": "shadow_reason",
        }
    ).copy()
    for column in SHADOW_OUTCOME_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result[SHADOW_OUTCOME_COLUMNS]


def observation_dedupe(existing: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate observation rows using the same signal identity keys."""

    if candidates.empty:
        return candidates
    shadow_existing = observations_to_shadow(existing)
    shadow_candidates = observations_to_shadow(candidates)
    return shadow_to_observations(dedupe(shadow_existing, shadow_candidates))


def build_outcomes(observations: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """Grade all stored forward observations."""

    shadow_rows = observations_to_shadow(observations)
    return shadow_outcomes_to_observations(build_shadow_outcomes(shadow_rows, args))


def write_report(
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
    matured = outcomes[outcomes["evaluation_status"] == "matured"].copy() if not outcomes.empty else pd.DataFrame()
    recent_matured = matured.tail(20) if not matured.empty else pd.DataFrame(columns=OUTCOME_COLUMNS)
    path.write_text(
        f"""# VWAP Reclaim / Reject Forward Observations

This report collects forward observations for the Strategy Vault's VWAP
Reclaim / Reject candidate when the latest saved candles pass the tightened
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
VWAP reclaim/reject forward observations stay separate from official paper
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


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_csv_or_empty(args.observations_csv, OBSERVATION_COLUMNS)
    candidates = shadow_to_observations(build_latest_samples(args))
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

    outcomes = build_outcomes(combined, args)
    outcomes_csv = args.output_dir / "vwap_reclaim_reject_forward_observation_results.csv"
    report_path = args.output_dir / "vwap_reclaim_reject_forward_observations.md"
    outcomes.to_csv(outcomes_csv, index=False)
    write_report(report_path, candidates, appended, combined, outcomes, append_status, args.observations_csv, outcomes_csv)

    matured = int((outcomes["evaluation_status"] == "matured").sum()) if not outcomes.empty else 0
    print(f"VWAP reclaim/reject forward observation status: {append_status}")
    print(f"Recent forward observation candidates: {len(candidates)}")
    print(f"New forward observations appended: {len(appended)}")
    print(f"Matured forward observation outcomes: {matured}")
    print(f"Saved forward observation outcomes CSV: {outcomes_csv}")
    print(f"Saved forward observation report: {report_path}")


if __name__ == "__main__":
    main()
