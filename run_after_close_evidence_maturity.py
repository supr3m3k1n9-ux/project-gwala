"""Run the after-close strategy evidence maturity pass.

This command re-grades stored shadow samples and forward observations after
regular-session 5m candles are complete. It does not fetch data, append new
signals, import paper trades, place orders, create broker alerts, or enable
execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

from run_playbook import markdown_table
from run_vwap_mean_reversion_forward_observations import (
    OBSERVATION_COLUMNS as MEAN_REVERSION_FORWARD_COLUMNS,
)
from run_vwap_mean_reversion_forward_observations import build_outcomes as build_mean_reversion_forward_outcomes
from run_vwap_mean_reversion_shadow_samples import SAMPLE_COLUMNS as MEAN_REVERSION_SHADOW_COLUMNS
from run_vwap_mean_reversion_shadow_samples import build_outcomes as build_mean_reversion_shadow_outcomes
from run_vwap_reclaim_reject_forward_observations import (
    OBSERVATION_COLUMNS as RECLAIM_REJECT_FORWARD_COLUMNS,
)
from run_vwap_reclaim_reject_forward_observations import build_outcomes as build_reclaim_reject_forward_outcomes
from run_vwap_reclaim_reject_shadow_samples import SAMPLE_COLUMNS as RECLAIM_REJECT_SHADOW_COLUMNS
from run_vwap_reclaim_reject_shadow_samples import build_outcomes as build_reclaim_reject_shadow_outcomes
from run_gap_fill_fade_shadow_samples import SPEC as GAP_FILL_SPEC
from run_opening_range_breakout_shadow_samples import SPEC as OPENING_RANGE_BREAKOUT_SPEC
from run_opening_range_failure_shadow_samples import SPEC as OPENING_RANGE_FAILURE_SPEC
from run_research_strategy_sample_lane import (
    OBSERVATION_COLUMNS as RESEARCH_OBSERVATION_COLUMNS,
    SAMPLE_COLUMNS as RESEARCH_SAMPLE_COLUMNS,
    build_observation_outcomes as build_research_observation_outcomes,
    build_outcomes as build_research_shadow_outcomes,
)


OUTCOME_FILES = [
    {
        "strategy": "VWAP Mean Reversion",
        "lane": "shadow_samples",
        "path": "vwap_mean_reversion_shadow_outcomes.csv",
    },
    {
        "strategy": "VWAP Mean Reversion",
        "lane": "forward_observations",
        "path": "vwap_mean_reversion_forward_observation_results.csv",
    },
    {
        "strategy": "VWAP Reclaim / Reject",
        "lane": "shadow_samples",
        "path": "vwap_reclaim_reject_shadow_outcomes.csv",
    },
    {
        "strategy": "VWAP Reclaim / Reject",
        "lane": "forward_observations",
        "path": "vwap_reclaim_reject_forward_observation_results.csv",
    },
    {
        "strategy": "Gap Fill / Gap Fade",
        "lane": "shadow_samples",
        "path": "gap_fill_fade_shadow_outcomes.csv",
    },
    {
        "strategy": "Gap Fill / Gap Fade",
        "lane": "forward_observations",
        "path": "gap_fill_fade_forward_observation_results.csv",
    },
    {
        "strategy": "Opening Range Breakout",
        "lane": "shadow_samples",
        "path": "opening_range_breakout_shadow_outcomes.csv",
    },
    {
        "strategy": "Opening Range Breakout",
        "lane": "forward_observations",
        "path": "opening_range_breakout_forward_observation_results.csv",
    },
    {
        "strategy": "Opening Range Failure",
        "lane": "shadow_samples",
        "path": "opening_range_failure_shadow_outcomes.csv",
    },
    {
        "strategy": "Opening Range Failure",
        "lane": "forward_observations",
        "path": "opening_range_failure_forward_observation_results.csv",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run after-close evidence maturity pass.")
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


def frame_with_columns(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a CSV and guarantee expected columns exist."""

    frame = read_csv_or_empty(path)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]


def average_matured_r(frame: pd.DataFrame) -> float:
    """Return average R for matured outcome rows."""

    if frame.empty or "evaluation_status" not in frame.columns or "hypothetical_r" not in frame.columns:
        return 0.0
    matured = frame[frame["evaluation_status"].astype(str) == "matured"].copy()
    values = pd.to_numeric(matured["hypothetical_r"], errors="coerce").dropna()
    return round(float(values.mean()), 4) if not values.empty else 0.0


def outcome_snapshot(output_dir: Path) -> list[dict[str, Any]]:
    """Summarize the current outcome files."""

    rows = []
    for item in OUTCOME_FILES:
        path = output_dir / item["path"]
        frame = read_csv_or_empty(path)
        statuses = frame["evaluation_status"].astype(str) if not frame.empty and "evaluation_status" in frame.columns else pd.Series(dtype=str)
        rows.append(
            {
                "strategy": item["strategy"],
                "lane": item["lane"],
                "outcome_file": str(path),
                "total_rows": int(len(frame)),
                "matured": int((statuses == "matured").sum()),
                "awaiting_complete_session_data": int((statuses == "awaiting_complete_session_data").sum()),
                "data_errors": int((statuses == "data_error").sum()),
                "no_future_exit_candle": int((statuses == "no_future_exit_candle").sum()),
                "average_matured_r": average_matured_r(frame),
            }
        )
    return rows


def run_step(command: list[str]) -> None:
    """Run one maturity command."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, check=True)


def grader_args(output_dir: Path) -> argparse.Namespace:
    """Return the shared args needed by strategy outcome graders."""

    return argparse.Namespace(
        data_dir=output_dir,
        output_dir=output_dir,
        entry_timeframe="M30",
        exit_timeframe="M5",
        daily_timeframe="D",
    )


def rebuild_strategy_outcomes(output_dir: Path) -> None:
    """Re-grade stored journals without appending any new observations."""

    args = grader_args(output_dir)
    mean_shadow = frame_with_columns(Path("data/vwap_mean_reversion_shadow_samples.csv"), MEAN_REVERSION_SHADOW_COLUMNS)
    mean_forward = frame_with_columns(
        Path("data/vwap_mean_reversion_forward_observations.csv"),
        MEAN_REVERSION_FORWARD_COLUMNS,
    )
    reclaim_shadow = frame_with_columns(Path("data/vwap_reclaim_reject_shadow_samples.csv"), RECLAIM_REJECT_SHADOW_COLUMNS)
    reclaim_forward = frame_with_columns(
        Path("data/vwap_reclaim_reject_forward_observations.csv"),
        RECLAIM_REJECT_FORWARD_COLUMNS,
    )

    build_mean_reversion_shadow_outcomes(mean_shadow, args).to_csv(
        output_dir / "vwap_mean_reversion_shadow_outcomes.csv",
        index=False,
    )
    build_mean_reversion_forward_outcomes(mean_forward, args).to_csv(
        output_dir / "vwap_mean_reversion_forward_observation_results.csv",
        index=False,
    )
    build_reclaim_reject_shadow_outcomes(reclaim_shadow, args).to_csv(
        output_dir / "vwap_reclaim_reject_shadow_outcomes.csv",
        index=False,
    )
    build_reclaim_reject_forward_outcomes(reclaim_forward, args).to_csv(
        output_dir / "vwap_reclaim_reject_forward_observation_results.csv",
        index=False,
    )
    for spec in [GAP_FILL_SPEC, OPENING_RANGE_BREAKOUT_SPEC, OPENING_RANGE_FAILURE_SPEC]:
        shadow = frame_with_columns(Path(f"data/{spec.stem}_shadow_samples.csv"), RESEARCH_SAMPLE_COLUMNS)
        forward = frame_with_columns(Path(f"data/{spec.stem}_forward_observations.csv"), RESEARCH_OBSERVATION_COLUMNS)
        build_research_shadow_outcomes(spec, shadow, args).to_csv(
            output_dir / f"{spec.stem}_shadow_outcomes.csv",
            index=False,
        )
        build_research_observation_outcomes(spec, forward, args).to_csv(
            output_dir / f"{spec.stem}_forward_observation_results.csv",
            index=False,
        )


def refresh_report_commands(output_dir: Path) -> list[list[str]]:
    """Return downstream reports to refresh after maturity grading."""

    python = sys.executable
    return [
        [python, "run_strategy_walk_forward_matrix.py", "--output-dir", str(output_dir)],
        [python, "run_research_strategy_tightened_review.py", "--output-dir", str(output_dir)],
        [python, "run_opening_range_failure_walk_forward_deepening.py", "--output-dir", str(output_dir)],
        [python, "run_opening_range_breakout_walk_forward_deepening.py", "--output-dir", str(output_dir)],
        [python, "run_gap_fill_fade_paper_watch_gate.py", "--output-dir", str(output_dir)],
        [python, "run_opening_range_breakout_paper_watch_gate.py", "--output-dir", str(output_dir)],
        [python, "run_opening_range_failure_paper_watch_gate.py", "--output-dir", str(output_dir)],
        [python, "run_trend_pullback_tightened_review.py", "--output-dir", str(output_dir)],
        [python, "run_vwap_mean_reversion_paper_watch_gate.py", "--output-dir", str(output_dir)],
        [python, "run_vwap_reclaim_reject_paper_watch_gate.py", "--output-dir", str(output_dir)],
        [python, "run_vwap_reclaim_reject_evidence_maturity.py", "--output-dir", str(output_dir)],
        [python, "run_trend_pullback_continuation_paper_watch_gate.py", "--output-dir", str(output_dir)],
        [python, "run_strategy_evidence_accumulator.py", "--output-dir", str(output_dir)],
        [python, "run_strategy_vault.py", "--output-dir", str(output_dir)],
        [python, "run_paper_activation_rules.py", "--output-dir", str(output_dir)],
        [python, "run_strategy_backtest_coverage.py", "--output-dir", str(output_dir)],
        [python, "run_validation_deepening_queue.py", "--output-dir", str(output_dir)],
        [python, "run_strategy_triage.py", "--output-dir", str(output_dir)],
        [python, "run_phase_milestones.py", "--output-dir", str(output_dir)],
    ]


def build_payload(output_dir: Path, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the maturity summary payload."""

    before_by_key = {(row["strategy"], row["lane"]): row for row in before}
    rows = []
    for row in after:
        previous = before_by_key.get((row["strategy"], row["lane"]), {})
        rows.append(
            {
                **row,
                "newly_matured": int(row["matured"]) - int(previous.get("matured", 0) or 0),
                "awaiting_delta": int(row["awaiting_complete_session_data"])
                - int(previous.get("awaiting_complete_session_data", 0) or 0),
            }
        )

    return {
        "status": "complete",
        "total_matured": int(sum(int(row["matured"]) for row in rows)),
        "newly_matured": int(sum(int(row["newly_matured"]) for row in rows)),
        "awaiting_complete_session_data": int(sum(int(row["awaiting_complete_session_data"]) for row in rows)),
        "next_action": (
            "Review paper activation rules if newly matured evidence improved a strategy gate."
            if sum(int(row["newly_matured"]) for row in rows) > 0
            else "No new matured outcomes yet. Run this again after complete 5m session candles are available."
        ),
        "guardrail": (
            "After-close maturity is research/paper validation only. It does not fetch data, "
            "append new signals, import paper trades, place orders, create broker alerts, or enable execution."
        ),
        "lanes": rows,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown maturity reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "after_close_evidence_maturity.json"
    csv_path = output_dir / "after_close_evidence_maturity.csv"
    md_path = output_dir / "after_close_evidence_maturity.md"
    rows = pd.DataFrame(payload["lanes"])

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# After-Close Evidence Maturity

This report re-grades stored strategy shadow samples and forward observations
after complete regular-session 5m candles are available.

Important: this is research and paper-validation only. It does not fetch data,
append new signals, import paper trades, place orders, create broker alerts, or
enable execution.

## Summary

```text
Status: {payload["status"]}
Total matured outcomes: {payload["total_matured"]}
Newly matured outcomes this run: {payload["newly_matured"]}
Still awaiting complete session data: {payload["awaiting_complete_session_data"]}
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
    args.output_dir.mkdir(parents=True, exist_ok=True)
    before = outcome_snapshot(args.output_dir)
    rebuild_strategy_outcomes(args.output_dir)
    for command in refresh_report_commands(args.output_dir):
        run_step(command)
    after = outcome_snapshot(args.output_dir)
    payload = build_payload(args.output_dir, before, after)
    write_outputs(args.output_dir, payload)
    run_step([sys.executable, "run_system_state.py", "--output-dir", str(args.output_dir)])
    print(f"After-close maturity status: {payload['status']}")
    print(f"Newly matured outcomes: {payload['newly_matured']}")
    print(f"Still awaiting complete session data: {payload['awaiting_complete_session_data']}")
    print(f"Saved after-close evidence report: {args.output_dir / 'after_close_evidence_maturity.md'}")


if __name__ == "__main__":
    main()
