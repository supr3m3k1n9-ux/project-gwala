"""Build the daily ship-mode funnel report.

This report makes the paper-validation bottleneck visible after every workflow
run. It reads existing scanner, sizing, review, Paper Gate, Options Contract
Gate, and validation-import outputs. It does not fetch data, import samples,
place orders, create broker alerts, or change trading logic.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from run_playbook import markdown_table


FIRST_GATE = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Project Gwala DAILY_SHIP_REPORT.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where workflow reports live.")
    parser.add_argument(
        "--samples-csv",
        type=Path,
        default=runtime_data_path("paper_validation_samples.csv"),
        help="Official paper-validation sample ledger.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV report or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON report or return an empty object."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def truthy_series(series: pd.Series) -> pd.Series:
    """Return a bool mask for CSV truthy values."""

    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def nonblank_series(series: pd.Series) -> pd.Series:
    """Return a bool mask for populated CSV values."""

    return series.notna() & series.astype(str).str.strip().ne("")


def count_column_value(frame: pd.DataFrame, column: str, value: str) -> int:
    """Count rows where a column equals a string value."""

    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].astype(str).eq(value).sum())


def paper_validation_allowed_count(scanner: pd.DataFrame) -> int:
    """Return allowed rows still inside A/current or B/grace validation windows."""

    if scanner.empty or not {"scanner_status", "signal_freshness"}.issubset(scanner.columns):
        return 0
    allowed = scanner["scanner_status"].astype(str).eq("allowed")
    fresh = scanner["signal_freshness"].astype(str).isin(["current_candle", "grace_candle"])
    return int((allowed & fresh).sum())


def paper_gate_ab_count(output_dir: Path, paper_gate: dict[str, Any]) -> int:
    """Return current Paper Gate A/B ready count."""

    if paper_gate:
        return int(paper_gate.get("ready_sample_count", 0) or 0)
    gate_rows = read_csv_or_empty(output_dir / "paper_gate_v2.csv")
    if gate_rows.empty:
        return 0
    required = {"sample_tier", "sample_status"}
    if not required.issubset(gate_rows.columns):
        return 0
    ready = gate_rows["sample_status"].astype(str).eq("ready_for_validation_sample")
    official = gate_rows["sample_tier"].astype(str).str.upper().isin({"A", "B"})
    return int((ready & official).sum())


def contract_passed_count(output_dir: Path, contract_gate: dict[str, Any]) -> int:
    """Return current Options Contract Gate pass count."""

    if contract_gate:
        return int(contract_gate.get("passed_contract_count", 0) or 0)
    rows = read_csv_or_empty(output_dir / "options_contract_gate.csv")
    if rows.empty or "contract_gate_pass" not in rows.columns:
        return 0
    return int(truthy_series(rows["contract_gate_pass"]).sum())


def official_sample_progress(samples: pd.DataFrame) -> dict[str, int | float]:
    """Return cumulative official paper-validation progress."""

    if samples.empty:
        return {
            "official_validation_samples": 0,
            "completed_official_paper_trades": 0,
            "open_official_paper_trades": 0,
            "remaining_to_30": FIRST_GATE,
            "completed_progress_pct": 0.0,
            "ledger_completion_pct": 0.0,
        }

    if "counts_toward_30" in samples.columns:
        official = truthy_series(samples["counts_toward_30"])
    elif "sample_tier" in samples.columns:
        official = samples["sample_tier"].astype(str).str.upper().isin({"A", "B"})
    else:
        official = pd.Series([False] * len(samples), index=samples.index)
    if "invalid_for_validation" in samples.columns:
        official = official & ~truthy_series(samples["invalid_for_validation"])

    completed = nonblank_series(samples["outcome_r"]) if "outcome_r" in samples.columns else pd.Series(
        [False] * len(samples),
        index=samples.index,
    )
    official_count = int(official.sum())
    completed_count = int((official & completed).sum())
    open_count = max(official_count - completed_count, 0)
    return {
        "official_validation_samples": official_count,
        "completed_official_paper_trades": completed_count,
        "open_official_paper_trades": open_count,
        "remaining_to_30": max(FIRST_GATE - completed_count, 0),
        "completed_progress_pct": round(min(completed_count / FIRST_GATE, 1.0) * 100, 1),
        "ledger_completion_pct": round(completed_count / official_count * 100, 1) if official_count else 0.0,
    }


def pct_text(value: float | None) -> str:
    """Return a report-friendly percent string."""

    if value is None:
        return "n/a"
    return f"{round(value, 1)}%"


def stage_rows(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach previous-stage survival/drop percentages to stage records."""

    rows: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for stage in stages:
        count = int(stage["count"])
        comparable = previous is not None and previous.get("scope") == stage.get("scope")
        previous_count = int(previous["count"]) if previous is not None else None
        if comparable and previous_count and previous_count > 0:
            survival_pct = round(count / previous_count * 100, 1)
            drop_pct = round(100.0 - survival_pct, 1)
        else:
            survival_pct = None
            drop_pct = None
        rows.append(
            {
                "stage": stage["stage"],
                "count": count,
                "previous_stage": previous["stage"] if previous is not None else "",
                "previous_count": previous_count if previous_count is not None else "",
                "survival_pct": pct_text(survival_pct),
                "drop_pct": pct_text(drop_pct),
                "scope": stage.get("scope", "current_run"),
                "notes": stage.get("notes", ""),
            }
        )
        previous = stage
    return rows


def first_bottleneck(rows: list[dict[str, Any]]) -> str:
    """Return the first zero-count current-run stage after scanner input."""

    for row in rows:
        if row["scope"] != "current_run":
            continue
        if row["stage"] == "Scanner signals":
            continue
        if int(row["count"]) == 0:
            return row["stage"]
    return "none"


def worst_drop(rows: list[dict[str, Any]]) -> str:
    """Return the largest comparable drop stage."""

    parsed: list[tuple[float, str]] = []
    for row in rows:
        raw = str(row.get("drop_pct", "n/a"))
        if raw == "n/a":
            continue
        try:
            parsed.append((float(raw.rstrip("%")), str(row["stage"])))
        except ValueError:
            continue
    if not parsed:
        return "n/a"
    drop, stage = max(parsed, key=lambda item: item[0])
    return f"{stage} ({round(drop, 1)}% drop from previous stage)"


def grace_lane_throughput(output_dir: Path) -> dict[str, Any]:
    """Return researched grace-lane throughput evidence when available."""

    payload = read_json_or_empty(output_dir / "grace_lane_backtest.json")
    increase = payload.get("candidate_increase", {}) if isinstance(payload.get("candidate_increase"), dict) else {}
    current = payload.get("current_system", {}) if isinstance(payload.get("current_system"), dict) else {}
    grace = payload.get("grace_lane_b", {}) if isinstance(payload.get("grace_lane_b"), dict) else {}
    return {
        "current_a_tier_windows": int(current.get("candidates", 0) or 0),
        "raw_b_tier_windows": int(increase.get("raw_b_tier_windows", 0) or 0),
        "incremental_b_tier_windows": int(increase.get("incremental_b_tier_windows", 0) or 0),
        "b_windows_that_duplicate_current_a": int(increase.get("b_windows_that_duplicate_current_a", 0) or 0),
        "increase_vs_current_pct": float(increase.get("increase_vs_current_pct", 0.0) or 0.0),
        "b_win_rate_pct": grace.get("win_rate_pct", ""),
        "b_average_r": grace.get("average_r", ""),
        "source": str(output_dir / "grace_lane_backtest.json") if payload else "",
    }


def morning_index_orb_progress(output_dir: Path) -> dict[str, Any]:
    """Return promoted ORB Manual Paper-Watch progress when available."""

    payload = read_json_or_empty(output_dir / "morning_index_orb_manual_paper_watch.json")
    metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
    return {
        "status": payload.get("manual_paper_watch_status", "missing"),
        "candidates_detected_today": int(metrics.get("candidates_detected_today", 0) or 0),
        "operator_reviewed_today": int(metrics.get("operator_reviewed_today", 0) or 0),
        "approved_today": int(metrics.get("approved_today", 0) or 0),
        "rejected_today": int(metrics.get("rejected_today", 0) or 0),
        "contract_passed_today": int(metrics.get("contract_passed_today", 0) or 0),
        "contract_failed_today": int(metrics.get("contract_failed_today", 0) or 0),
        "paper_entries_opened": int(metrics.get("paper_entries_opened", 0) or 0),
        "trades_completed": int(metrics.get("trades_completed", 0) or 0),
        "open_count": int(metrics.get("open_count", 0) or 0),
        "average_r": metrics.get("average_r", 0.0),
        "completed_count": int(metrics.get("completed_count", 0) or 0),
        "checkpoint_trades": int(payload.get("checkpoint_trades", 20) or 20),
        "remaining_to_20": int(metrics.get("remaining_to_20", 20) or 20),
        "estimated_time_to_checkpoint": metrics.get("estimated_time_to_checkpoint", "missing"),
        "evidence_confidence": metrics.get("evidence_confidence_distribution", {}),
        "biggest_operational_bottleneck": payload.get("biggest_operational_bottleneck", "missing"),
        "source": str(output_dir / "morning_index_orb_manual_paper_watch.json") if payload else "",
    }


def build_ship_report(output_dir: Path = Path("logs"), samples_csv: Path | None = None) -> dict[str, Any]:
    """Build the ship-mode funnel payload."""

    samples_csv = samples_csv or runtime_data_path("paper_validation_samples.csv")
    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    pre_entry = read_csv_or_empty(output_dir / "pre_entry_review.csv")
    paper_gate = read_json_or_empty(output_dir / "paper_gate_v2.json")
    contract_gate = read_json_or_empty(output_dir / "options_contract_gate.json")
    validation_import = read_json_or_empty(output_dir / "paper_validation_sample_import.json")
    samples = read_csv_or_empty(samples_csv)
    grace_lane = grace_lane_throughput(output_dir)
    morning_index_orb = morning_index_orb_progress(output_dir)

    validation_mode = str(validation_import.get("mode", "missing"))
    validation_new_rows = int(validation_import.get("new_rows", 0) or 0)
    progress = official_sample_progress(samples)

    stages = [
        {
            "stage": "Scanner signals",
            "count": int(len(scanner)),
            "scope": "current_run",
            "notes": "Rows emitted by the latest scanner CSV.",
        },
        {
            "stage": "Allowed signals",
            "count": count_column_value(scanner, "scanner_status", "allowed"),
            "scope": "current_run",
            "notes": "Scanner rows marked allowed.",
        },
        {
            "stage": "A/B paper-validation allowed",
            "count": paper_validation_allowed_count(scanner),
            "scope": "current_run",
            "notes": "Allowed scanner rows that are still A/current or B/one-M30 grace.",
        },
        {
            "stage": "Size-ok signals",
            "count": count_column_value(sizing, "sizing_status", "size_ok"),
            "scope": "current_run",
            "notes": "Position sizing accepted risk and produced shares.",
        },
        {
            "stage": "Review-ready signals",
            "count": count_column_value(pre_entry, "review_status", "ready_for_manual_review"),
            "scope": "current_run",
            "notes": "Pre-entry review passed. Manual chart review is still required.",
        },
        {
            "stage": "Paper Gate A/B signals",
            "count": paper_gate_ab_count(output_dir, paper_gate),
            "scope": "current_run",
            "notes": "Paper Gate v2 ready A/B validation samples.",
        },
        {
            "stage": "Contract-passed signals",
            "count": contract_passed_count(output_dir, contract_gate),
            "scope": "current_run",
            "notes": "Options Contract Gate v1 pass rows.",
        },
        {
            "stage": "Validation-imported signals",
            "count": validation_new_rows,
            "scope": "current_run",
            "notes": f"Import mode is {validation_mode}; preview rows are not appended unless confirmed.",
        },
        {
            "stage": "Completed official paper trades",
            "count": int(progress["completed_official_paper_trades"]),
            "scope": "cumulative_ledger",
            "notes": "Cumulative countable A/B validation samples with outcomes recorded.",
        },
    ]
    funnel_rows = stage_rows(stages)
    generated_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    return {
        "generated_at_et": generated_at,
        "first_bottleneck": first_bottleneck(funnel_rows),
        "worst_drop": worst_drop(funnel_rows),
        "validation_import_mode": validation_mode,
        "validation_import_new_rows": validation_new_rows,
        **progress,
        "grace_lane_throughput": grace_lane,
        "morning_index_orb_manual_paper_watch": morning_index_orb,
        "funnel_rows": funnel_rows,
        "source_files": {
            "scanner": str(output_dir / "daily_paper_signal_scanner.csv"),
            "position_sizing": str(output_dir / "position_sizing.csv"),
            "pre_entry_review": str(output_dir / "pre_entry_review.csv"),
            "paper_gate_v2": str(output_dir / "paper_gate_v2.json"),
            "options_contract_gate": str(output_dir / "options_contract_gate.json"),
            "paper_validation_sample_import": str(output_dir / "paper_validation_sample_import.json"),
            "paper_validation_samples": str(samples_csv),
            "morning_index_orb_manual_paper_watch": str(output_dir / "morning_index_orb_manual_paper_watch.json"),
        },
        "guardrail": (
            "DAILY_SHIP_REPORT is observability only. It does not fetch data, import samples, "
            "place orders, create broker alerts, or change trading rules."
        ),
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Write JSON, CSV, and Markdown ship reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame(payload["funnel_rows"])
    source_files = pd.DataFrame(
        [{"source": key, "path": value} for key, value in payload["source_files"].items()]
    )
    progress = pd.DataFrame(
        [
            {"metric": "official_validation_samples", "value": payload["official_validation_samples"]},
            {"metric": "completed_official_paper_trades", "value": payload["completed_official_paper_trades"]},
            {"metric": "open_official_paper_trades", "value": payload["open_official_paper_trades"]},
            {"metric": "remaining_to_30", "value": payload["remaining_to_30"]},
            {"metric": "completed_progress_pct", "value": f"{payload['completed_progress_pct']}%"},
            {"metric": "ledger_completion_pct", "value": f"{payload['ledger_completion_pct']}%"},
        ]
    )
    grace_lane = pd.DataFrame(
        [{"metric": key, "value": value} for key, value in payload["grace_lane_throughput"].items()]
    )
    morning_index_orb = pd.DataFrame(
        [{"metric": key, "value": value} for key, value in payload["morning_index_orb_manual_paper_watch"].items()]
    )

    (output_dir / "DAILY_SHIP_REPORT.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    rows.to_csv(output_dir / "DAILY_SHIP_REPORT.csv", index=False)
    report_path = output_dir / "DAILY_SHIP_REPORT.md"
    report_path.write_text(
        f"""# DAILY_SHIP_REPORT

Generated: {payload["generated_at_et"]}

This report makes the paper-validation funnel visible after each workflow run.

Important: this is observability only. It does not fetch data, import samples,
place orders, create broker alerts, or change trading rules.

## Summary

```text
First bottleneck: {payload["first_bottleneck"]}
Worst drop: {payload["worst_drop"]}
Validation import mode: {payload["validation_import_mode"]}
Validation import new rows: {payload["validation_import_new_rows"]}
Completed official paper trades: {payload["completed_official_paper_trades"]}/{FIRST_GATE}
Remaining to paper gate: {payload["remaining_to_30"]}
```

## Funnel

{markdown_table(rows)}

## Official Paper Progress

{markdown_table(progress)}

## Grace Lane Throughput Evidence

{markdown_table(grace_lane)}

## Morning Index ORB Manual Paper-Watch

{markdown_table(morning_index_orb)}

## Source Files

{markdown_table(source_files)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )
    return report_path


def main() -> None:
    args = parse_args()
    payload = build_ship_report(args.output_dir, args.samples_csv)
    report_path = write_outputs(args.output_dir, payload)
    print(f"Saved DAILY_SHIP_REPORT: {report_path}")
    print(f"First bottleneck: {payload['first_bottleneck']}")
    print(f"Worst drop: {payload['worst_drop']}")


if __name__ == "__main__":
    main()
