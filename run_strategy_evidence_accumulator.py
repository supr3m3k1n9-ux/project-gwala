"""Summarize whether strategy evidence lanes are accumulating samples.

This script is a control-panel report for the research vault. It does not
generate signals, approve paper trades, place broker orders, or change strategy
rules. It only reads the existing sample/observation files and answers:

- Which lanes are collecting during open market hours?
- How many samples exist today?
- How many outcomes have matured?
- Which research strategies still need a dedicated forward evidence lane?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize strategy evidence accumulation.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV file or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def text_value(value: object) -> str:
    """Return a clean string from a possibly missing value."""

    if value is None or pd.isna(value):
        return ""
    return str(value)


def date_series(frame: pd.DataFrame) -> pd.Series:
    """Return the best available date series for an evidence journal."""

    if frame.empty:
        return pd.Series(dtype=str)
    if "scan_date" in frame.columns:
        return frame["scan_date"].astype(str)
    if "observed_at_et" in frame.columns:
        return pd.to_datetime(frame["observed_at_et"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "entry_time_et" in frame.columns:
        return pd.to_datetime(frame["entry_time_et"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "observed_at" in frame.columns:
        return pd.to_datetime(frame["observed_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    return pd.Series([""] * len(frame), dtype=str)


def latest_timestamp(frame: pd.DataFrame) -> str:
    """Return the latest human-readable timestamp from a journal."""

    for column in ["observed_at_et", "observed_at", "entry_time_et", "latest_signal_et"]:
        if column in frame.columns and not frame[column].dropna().empty:
            return text_value(frame[column].dropna().iloc[-1])
    return ""


def matured_count(outcomes: pd.DataFrame) -> int:
    """Count matured rows in an outcome file."""

    if outcomes.empty or "evaluation_status" not in outcomes.columns:
        return 0
    return int((outcomes["evaluation_status"].astype(str) == "matured").sum())


def average_r(outcomes: pd.DataFrame) -> float:
    """Return average R for matured outcomes."""

    if outcomes.empty or "evaluation_status" not in outcomes.columns:
        return 0.0
    matured = outcomes[outcomes["evaluation_status"].astype(str) == "matured"].copy()
    r_column = "hypothetical_r" if "hypothetical_r" in matured.columns else "r_result"
    if matured.empty or r_column not in matured.columns:
        return 0.0
    values = pd.to_numeric(matured[r_column], errors="coerce").dropna()
    return round(float(values.mean()), 4) if not values.empty else 0.0


def lane_status(total_rows: int, today_rows: int, market_is_open: bool) -> str:
    """Describe whether a lane is collecting right now."""

    if market_is_open and today_rows > 0:
        return "collecting_today"
    if market_is_open:
        return "watching_no_sample_yet"
    if total_rows > 0:
        return "stored_evidence"
    return "no_samples_yet"


def summarize_lane(
    *,
    strategy: str,
    lane: str,
    journal_path: Path,
    outcomes_path: Path,
    today: str,
    market_is_open: bool,
    note: str,
) -> dict[str, Any]:
    """Summarize one append-only evidence lane."""

    journal = read_csv_or_empty(journal_path)
    outcomes = read_csv_or_empty(outcomes_path)
    dates = date_series(journal)
    today_rows = int((dates == today).sum()) if not dates.empty else 0
    total_rows = int(len(journal))
    return {
        "strategy": strategy,
        "lane": lane,
        "status": lane_status(total_rows, today_rows, market_is_open),
        "total_rows": total_rows,
        "today_rows": today_rows,
        "matured_outcomes": matured_count(outcomes),
        "average_r": average_r(outcomes),
        "latest_timestamp": latest_timestamp(journal),
        "journal": str(journal_path),
        "outcomes": str(outcomes_path),
        "note": note,
    }


def build_payload(output_dir: Path) -> dict[str, Any]:
    """Build the evidence accumulation payload."""

    market = market_refresh_state()
    today = str(market.get("today", ""))
    market_is_open = bool(market.get("market_is_open", False))
    rows = [
        summarize_lane(
            strategy="VWAP + EMA Trend Continuation",
            lane="generic_forward_observations",
            journal_path=Path("data/forward_signal_observations.csv"),
            outcomes_path=output_dir / "forward_observation_results.csv",
            today=today,
            market_is_open=market_is_open,
            note="Official forward observation lane for current scanner signals.",
        ),
        summarize_lane(
            strategy="VWAP + EMA Trend Continuation",
            lane="generic_shadow_samples",
            journal_path=Path("data/shadow_samples.csv"),
            outcomes_path=output_dir / "shadow_sample_outcomes.csv",
            today=today,
            market_is_open=market_is_open,
            note="Near-miss shadow lane for current scanner blockers.",
        ),
        summarize_lane(
            strategy="VWAP Mean Reversion",
            lane="strategy_shadow_samples",
            journal_path=Path("data/vwap_mean_reversion_shadow_samples.csv"),
            outcomes_path=output_dir / "vwap_mean_reversion_shadow_outcomes.csv",
            today=today,
            market_is_open=market_is_open,
            note="Strategy-specific shadow lane used by the mean-reversion promotion gate.",
        ),
        summarize_lane(
            strategy="VWAP Mean Reversion",
            lane="strategy_forward_observations",
            journal_path=Path("data/vwap_mean_reversion_forward_observations.csv"),
            outcomes_path=output_dir / "vwap_mean_reversion_forward_observation_results.csv",
            today=today,
            market_is_open=market_is_open,
            note="Strategy-specific forward lane used by the mean-reversion promotion gate.",
        ),
        summarize_lane(
            strategy="Trend Pullback Continuation",
            lane="strategy_shadow_samples",
            journal_path=Path("data/trend_pullback_continuation_shadow_samples.csv"),
            outcomes_path=output_dir / "trend_pullback_continuation_shadow_outcomes.csv",
            today=today,
            market_is_open=market_is_open,
            note="Strategy-specific shadow lane opened after provisional tightened review.",
        ),
        summarize_lane(
            strategy="Trend Pullback Continuation",
            lane="strategy_forward_observations",
            journal_path=Path("data/trend_pullback_continuation_forward_observations.csv"),
            outcomes_path=output_dir / "trend_pullback_continuation_forward_observation_results.csv",
            today=today,
            market_is_open=market_is_open,
            note="Strategy-specific forward lane opened after shadow evidence started.",
        ),
        {
            "strategy": "Opening Range Failure",
            "lane": "strategy_forward_observations",
            "status": "not_built_yet",
            "total_rows": 0,
            "today_rows": 0,
            "matured_outcomes": 0,
            "average_r": 0.0,
            "latest_timestamp": "",
            "journal": "",
            "outcomes": "",
            "note": "First-pass backtest exists; add this lane only after more evidence justifies it.",
        },
    ]

    collecting = sum(1 for row in rows if row["status"] == "collecting_today")
    watching = sum(1 for row in rows if row["status"] == "watching_no_sample_yet")
    next_action = (
        "Evidence lanes are collecting today; keep the market-hours workflow running."
        if collecting
        else "Market is open but no strategy evidence sample has appeared yet; keep scanning."
        if market_is_open and watching
        else "Run the market-hours workflow during the next open session to accumulate samples."
    )

    return {
        "market": market,
        "today": today,
        "market_is_open": market_is_open,
        "collecting_lane_count": collecting,
        "watching_lane_count": watching,
        "total_evidence_rows": int(sum(int(row["total_rows"]) for row in rows)),
        "today_evidence_rows": int(sum(int(row["today_rows"]) for row in rows)),
        "matured_outcomes": int(sum(int(row["matured_outcomes"]) for row in rows)),
        "next_action": next_action,
        "guardrail": "Evidence accumulation is research/paper validation only. It does not approve trades or place orders.",
        "lanes": rows,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "strategy_evidence_accumulator.json"
    csv_path = output_dir / "strategy_evidence_accumulator.csv"
    md_path = output_dir / "strategy_evidence_accumulator.md"
    rows = pd.DataFrame(payload["lanes"])

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Strategy Evidence Accumulator

This report checks whether Project Gwala's research evidence lanes are
accumulating samples during market-hours workflow runs.

Important: this is research and paper-validation only. It does not approve
paper trades, place broker orders, create broker alerts, or change strategy
rules.

## Summary

```text
Market open: {payload["market_is_open"]}
Today: {payload["today"]}
Collecting lanes today: {payload["collecting_lane_count"]}
Watching lanes today: {payload["watching_lane_count"]}
Total evidence rows: {payload["total_evidence_rows"]}
Today evidence rows: {payload["today_evidence_rows"]}
Matured outcomes: {payload["matured_outcomes"]}
Next action: {payload["next_action"]}
```

## Evidence Lanes

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
{json_path}
{csv_path}
{md_path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_payload(args.output_dir)
    write_outputs(args.output_dir, payload)
    print(f"Saved strategy evidence accumulator JSON: {args.output_dir / 'strategy_evidence_accumulator.json'}")
    print(f"Saved strategy evidence accumulator CSV: {args.output_dir / 'strategy_evidence_accumulator.csv'}")
    print(f"Saved strategy evidence accumulator report: {args.output_dir / 'strategy_evidence_accumulator.md'}")


if __name__ == "__main__":
    main()
