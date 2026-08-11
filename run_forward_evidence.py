"""Build the forward evidence dashboard report.

This is research and paper-validation only. It combines official paper
progress, forward observations, sample queue status, and shadow samples into
one readable proof-trail report. It does not place orders, create broker
alerts, import trades, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from config.runtime_paths import runtime_data_path
from run_playbook import markdown_table


FIRST_GATE = 30
STRONG_GATE = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Project Gwala forward evidence report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=runtime_data_path("paper_trades.csv"), help="Raw local paper log.")
    parser.add_argument(
        "--observations-csv",
        type=Path,
        default=runtime_data_path("forward_signal_observations.csv"),
        help="Append-only forward observation journal.",
    )
    parser.add_argument(
        "--shadow-csv",
        type=Path,
        default=runtime_data_path("shadow_samples.csv"),
        help="Append-only shadow sample journal.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and return an empty frame otherwise."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def number_value(value: object, default: float = 0.0) -> float:
    """Return a CSV value as a float when possible."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def pct(part: float, whole: float) -> float:
    """Return a rounded percentage, protected from divide-by-zero."""

    if whole <= 0:
        return 0.0
    return round(min(max(part / whole, 0.0), 1.0) * 100, 1)


def paper_progress(paper_review: pd.DataFrame) -> dict[str, Any]:
    """Summarize completed official paper trades."""

    if paper_review.empty:
        return {
            "completed_trades": 0,
            "allowed_completed_trades": 0,
            "blocked_completed_trades": 0,
            "total_r": 0.0,
            "average_r": 0.0,
            "first_gate_percent": 0.0,
            "strong_gate_percent": 0.0,
            "remaining_to_30": FIRST_GATE,
            "remaining_to_60": STRONG_GATE,
        }

    completed = paper_review.copy()
    allowed = completed[completed.get("signal_status", "") == "allowed"] if "signal_status" in completed.columns else completed.iloc[0:0]
    r_values = pd.to_numeric(completed.get("review_r", pd.Series(dtype=float)), errors="coerce").dropna()
    total_r = round(float(r_values.sum()), 4) if not r_values.empty else 0.0
    average_r = round(float(r_values.mean()), 4) if not r_values.empty else 0.0
    allowed_count = int(len(allowed))
    return {
        "completed_trades": int(len(completed)),
        "allowed_completed_trades": allowed_count,
        "blocked_completed_trades": int(len(completed) - allowed_count),
        "total_r": total_r,
        "average_r": average_r,
        "first_gate_percent": pct(allowed_count, FIRST_GATE),
        "strong_gate_percent": pct(allowed_count, STRONG_GATE),
        "remaining_to_30": max(FIRST_GATE - allowed_count, 0),
        "remaining_to_60": max(STRONG_GATE - allowed_count, 0),
    }


def observation_progress(observations: pd.DataFrame, results: pd.DataFrame) -> dict[str, Any]:
    """Summarize allowed/watch-only forward observations and outcomes."""

    allowed_observations = 0
    watch_observations = 0
    if not observations.empty and "signal_status" in observations.columns:
        allowed_observations = int((observations["signal_status"] == "allowed").sum())
        watch_observations = int((observations["signal_status"] == "blocked").sum())

    matured = results[results["evaluation_status"] == "matured"].copy() if "evaluation_status" in results.columns else pd.DataFrame()
    allowed_matured = matured[matured["signal_status"] == "allowed"] if not matured.empty and "signal_status" in matured.columns else pd.DataFrame()
    blocked_matured = matured[matured["signal_status"] == "blocked"] if not matured.empty and "signal_status" in matured.columns else pd.DataFrame()

    def avg_r(frame: pd.DataFrame) -> float:
        if frame.empty:
            return 0.0
        values = pd.to_numeric(frame["hypothetical_r"], errors="coerce").dropna()
        if values.empty:
            return 0.0
        return round(float(values.mean()), 4)

    return {
        "observations_logged": int(len(observations)),
        "allowed_observations": allowed_observations,
        "watch_only_observations": watch_observations,
        "matured_observation_outcomes": int(len(matured)),
        "allowed_matured_outcomes": int(len(allowed_matured)),
        "watch_matured_outcomes": int(len(blocked_matured)),
        "allowed_average_r": avg_r(allowed_matured),
        "watch_average_r": avg_r(blocked_matured),
    }


def shadow_progress(shadow_samples: pd.DataFrame, shadow_outcomes: pd.DataFrame) -> dict[str, Any]:
    """Summarize near-miss shadow evidence."""

    statuses = shadow_samples.groupby("shadow_status").size().to_dict() if "shadow_status" in shadow_samples.columns and not shadow_samples.empty else {}
    matured = (
        shadow_outcomes[shadow_outcomes["evaluation_status"] == "matured"].copy()
        if "evaluation_status" in shadow_outcomes.columns and not shadow_outcomes.empty
        else pd.DataFrame()
    )
    avg_r = 0.0
    if not matured.empty:
        values = pd.to_numeric(matured["hypothetical_r"], errors="coerce").dropna()
        avg_r = round(float(values.mean()), 4) if not values.empty else 0.0
    return {
        "shadow_samples_logged": int(len(shadow_samples)),
        "one_rule_miss": int(statuses.get("one_rule_miss", 0)),
        "close_watch_shadow": int(statuses.get("close_watch_shadow", 0)),
        "matured_shadow_outcomes": int(len(matured)),
        "shadow_average_r": avg_r,
    }


def queue_progress(queue: pd.DataFrame) -> dict[str, Any]:
    """Summarize current forward queue status."""

    counts = queue.groupby("queue_status").size().to_dict() if "queue_status" in queue.columns and not queue.empty else {}
    return {
        "ready_for_review": int(counts.get("ready_for_review", 0)),
        "blocked_current": int(counts.get("blocked_current", 0)),
        "almost_ready": int(counts.get("almost_ready", 0)),
        "waiting": int(counts.get("waiting", 0)),
    }


def aging_progress(candidate_aging: pd.DataFrame) -> dict[str, Any]:
    """Summarize candidate timing evidence."""

    if candidate_aging.empty:
        return {
            "aging_rows": 0,
            "aged_outcomes": 0,
            "late_day_rows": 0,
            "late_day_outcomes": 0,
            "late_day_average_r": 0.0,
            "aging_status": "missing",
        }
    rows = candidate_aging.copy()
    rows["r_result"] = pd.to_numeric(rows.get("r_result", pd.Series(dtype=float)), errors="coerce")
    outcomes = rows[rows["r_result"].notna()]
    late = rows[rows["age_bucket"] == "late_day"] if "age_bucket" in rows.columns else pd.DataFrame()
    late_outcomes = late[late["r_result"].notna()] if not late.empty else pd.DataFrame()
    late_average = round(float(late_outcomes["r_result"].mean()), 4) if not late_outcomes.empty else 0.0
    if late_outcomes.empty:
        status = "collect_more"
    elif late_average < 0:
        status = "late_day_caution"
    else:
        status = "late_day_constructive"
    return {
        "aging_rows": int(len(rows)),
        "aged_outcomes": int(len(outcomes)),
        "late_day_rows": int(len(late)),
        "late_day_outcomes": int(len(late_outcomes)),
        "late_day_average_r": late_average,
        "aging_status": status,
    }


def next_action(paper: dict[str, Any], observations: dict[str, Any], shadow: dict[str, Any], queue: dict[str, Any]) -> str:
    """Return the most useful next action for forward evidence collection."""

    if queue["ready_for_review"] > 0:
        return "Review the ready candidate checklist, then use local paper confirm only if the plan matches."
    if queue["blocked_current"] > 0:
        return "Study the current blocker. Do not confirm a local paper trade."
    if queue["almost_ready"] > 0:
        return "Keep scanning during open market hours; almost-ready rows may become official candidates."
    if observations["observations_logged"] == 0 and shadow["shadow_samples_logged"] == 0:
        return "Run the daily workflow during an open market session to capture the first forward evidence rows."
    if paper["allowed_completed_trades"] < FIRST_GATE:
        return "Keep collecting official paper trades and shadow samples until evidence reaches the first gate."
    return "First evidence gate reached. Review expectancy, mistakes, and stability before any next phase."


def build_evidence(
    paper_review: pd.DataFrame,
    observations: pd.DataFrame,
    observation_results: pd.DataFrame,
    shadow_samples: pd.DataFrame,
    shadow_outcomes: pd.DataFrame,
    queue: pd.DataFrame,
    candidate_aging: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build the combined evidence payload used by the report and tests."""

    paper = paper_progress(paper_review)
    observation = observation_progress(observations, observation_results)
    shadow = shadow_progress(shadow_samples, shadow_outcomes)
    queue_state = queue_progress(queue)
    aging = aging_progress(candidate_aging if candidate_aging is not None else pd.DataFrame())
    total_learning_rows = (
        paper["completed_trades"]
        + observation["observations_logged"]
        + shadow["shadow_samples_logged"]
    )
    return {
        "paper": paper,
        "observations": observation,
        "shadow": shadow,
        "queue": queue_state,
        "aging": aging,
        "total_learning_rows": int(total_learning_rows),
        "first_gate_percent": paper["first_gate_percent"],
        "strong_gate_percent": paper["strong_gate_percent"],
        "next_action": next_action(paper, observation, shadow, queue_state),
        "guardrail": "Forward evidence is research/paper validation only. No broker orders are placed.",
    }


def status_table(evidence: dict[str, Any]) -> pd.DataFrame:
    """Return the main progress table."""

    return pd.DataFrame(
        [
            {"lane": "Official paper trades", "count": evidence["paper"]["allowed_completed_trades"], "status": f"{evidence['paper']['first_gate_percent']}% to 30 gate"},
            {"lane": "Forward observations", "count": evidence["observations"]["observations_logged"], "status": f"{evidence['observations']['matured_observation_outcomes']} matured outcomes"},
            {"lane": "Shadow samples", "count": evidence["shadow"]["shadow_samples_logged"], "status": f"{evidence['shadow']['matured_shadow_outcomes']} matured outcomes"},
            {"lane": "Candidate aging", "count": evidence["aging"]["aging_rows"], "status": evidence["aging"]["aging_status"]},
            {"lane": "Current ready queue", "count": evidence["queue"]["ready_for_review"], "status": "manual checklist required"},
            {"lane": "Total learning rows", "count": evidence["total_learning_rows"], "status": "official and shadow lanes stay separate"},
        ]
    )


def write_report(path: Path, evidence: dict[str, Any], files: dict[str, Path]) -> None:
    """Write the readable forward evidence report."""

    path.write_text(
        f"""# Forward Evidence Dashboard

This report combines the proof trail for Project Gwala's forward validation.

Important: this is research and paper-validation only. It does not place
broker orders, create Webull paper orders, import trades automatically, or
connect to live execution.

## Evidence Progress

{markdown_table(status_table(evidence))}

## Official Paper Gate

{markdown_table(pd.DataFrame([evidence["paper"]]))}

## Forward Observation Evidence

{markdown_table(pd.DataFrame([evidence["observations"]]))}

## Shadow Sample Evidence

{markdown_table(pd.DataFrame([evidence["shadow"]]))}

## Current Sample Queue

{markdown_table(pd.DataFrame([evidence["queue"]]))}

## Candidate Aging

{markdown_table(pd.DataFrame([evidence["aging"]]))}

## Next Action

```text
{evidence["next_action"]}
```

## Guardrail

```text
{evidence["guardrail"]}
Shadow samples do not count toward official paper gates.
Only completed allowed paper trades count toward 30/60 gates.
```

## Files

```text
{files["paper_review"]}
{files["observations"]}
{files["observation_results"]}
{files["shadow_samples"]}
{files["shadow_outcomes"]}
{files["queue"]}
{files["candidate_aging"]}
{path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    paper_review_path = args.output_dir / "paper_review_clean_trades.csv"
    observation_results_path = args.output_dir / "forward_observation_results.csv"
    shadow_outcomes_path = args.output_dir / "shadow_sample_outcomes.csv"
    queue_path = args.output_dir / "forward_sample_queue.csv"
    candidate_aging_path = args.output_dir / "candidate_aging.csv"

    evidence = build_evidence(
        read_csv_or_empty(paper_review_path),
        read_csv_or_empty(args.observations_csv),
        read_csv_or_empty(observation_results_path),
        read_csv_or_empty(args.shadow_csv),
        read_csv_or_empty(shadow_outcomes_path),
        read_csv_or_empty(queue_path),
        candidate_aging=read_csv_or_empty(candidate_aging_path),
    )

    report_path = args.output_dir / "forward_evidence.md"
    write_report(
        report_path,
        evidence,
        {
            "paper_review": paper_review_path,
            "observations": args.observations_csv,
            "observation_results": observation_results_path,
            "shadow_samples": args.shadow_csv,
            "shadow_outcomes": shadow_outcomes_path,
            "queue": queue_path,
            "candidate_aging": candidate_aging_path,
        },
    )

    print(f"Official paper gate: {evidence['paper']['allowed_completed_trades']} / {FIRST_GATE}")
    print(f"Forward observations: {evidence['observations']['observations_logged']}")
    print(f"Shadow samples: {evidence['shadow']['shadow_samples_logged']}")
    print(f"Next action: {evidence['next_action']}")
    print(f"Saved forward evidence report: {report_path}")


if __name__ == "__main__":
    main()
