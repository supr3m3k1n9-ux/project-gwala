"""Shared paper-watch gate for Strategy Vault research families.

This module is intentionally small and boring: it reads the existing research
reports for one strategy family and checks whether that strategy has enough
evidence for manual paper-watch review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def average_r(frame: pd.DataFrame) -> float:
    """Return average hypothetical R for matured rows."""

    if frame.empty or "hypothetical_r" not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame["hypothetical_r"], errors="coerce").dropna()
    return round(float(values.mean()), 4) if not values.empty else 0.0


def gate_row(name: str, current: Any, required: Any, passed: bool, reason: str) -> dict[str, Any]:
    """Return one checklist row."""

    return {
        "check": name,
        "status": "pass" if passed else "blocked",
        "current": current,
        "required": required,
        "reason": reason,
    }


def build_gate_for_strategy(
    *,
    strategy_id: str,
    strategy_name: str,
    stem: str,
    args: Any,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build a paper-watch gate payload for one standard research strategy."""

    output_dir = args.output_dir
    summary = read_csv_or_empty(output_dir / f"{stem}_summary.csv")
    walk_forward = read_csv_or_empty(output_dir / f"{stem}_walk_forward.csv")
    shadow = read_csv_or_empty(output_dir / f"{stem}_shadow_outcomes.csv")
    forward = read_csv_or_empty(output_dir / f"{stem}_forward_observation_results.csv")

    tightened = (
        summary[summary["tightened_review"] == "passes_tightened_research"].copy()
        if not summary.empty and "tightened_review" in summary.columns
        else pd.DataFrame()
    )
    watch_more = (
        summary[summary["research_status"].astype(str).isin(["promising", "watch_more"])].copy()
        if not summary.empty and "research_status" in summary.columns
        else pd.DataFrame()
    )
    walk_holding = (
        walk_forward[walk_forward["decision"] == "holding_up"].copy()
        if not walk_forward.empty and "decision" in walk_forward.columns
        else pd.DataFrame()
    )
    matured_shadow = (
        shadow[shadow["evaluation_status"] == "matured"].copy()
        if not shadow.empty and "evaluation_status" in shadow.columns
        else pd.DataFrame()
    )
    matured_forward = (
        forward[forward["evaluation_status"] == "matured"].copy()
        if not forward.empty and "evaluation_status" in forward.columns
        else pd.DataFrame()
    )
    shadow_avg = average_r(matured_shadow)
    forward_avg = average_r(matured_forward)

    rows = [
        gate_row(
            "Tightened research pass",
            len(tightened),
            args.min_tightened_pass_rows,
            len(tightened) >= args.min_tightened_pass_rows,
            "At least one row must pass tightened review; seed watch-more rows only collect evidence.",
        ),
        gate_row(
            "Walk-forward holding up",
            len(walk_holding),
            args.min_walk_forward_holding_rows,
            len(walk_holding) >= args.min_walk_forward_holding_rows,
            "The newer half must still hold up.",
        ),
        gate_row(
            "Shadow samples logged",
            len(shadow),
            args.min_shadow_samples,
            len(shadow) >= args.min_shadow_samples,
            "Collect enough strategy-specific shadow sightings.",
        ),
        gate_row(
            "Matured shadow outcomes",
            len(matured_shadow),
            args.min_matured_shadow_samples,
            len(matured_shadow) >= args.min_matured_shadow_samples,
            "Enough shadow samples must have completed outcomes.",
        ),
        gate_row(
            "Shadow average R",
            shadow_avg,
            args.min_shadow_average_r,
            shadow_avg >= args.min_shadow_average_r and len(matured_shadow) >= args.min_matured_shadow_samples,
            "Matured shadow outcomes must be positive enough.",
        ),
        gate_row(
            "Forward observations logged",
            len(forward),
            args.min_forward_observations,
            len(forward) >= args.min_forward_observations,
            "Collect enough real-time strategy observations.",
        ),
        gate_row(
            "Matured forward outcomes",
            len(matured_forward),
            args.min_matured_forward_observations,
            len(matured_forward) >= args.min_matured_forward_observations,
            "Enough forward observations must have completed outcomes.",
        ),
        gate_row(
            "Forward average R",
            forward_avg,
            args.min_forward_average_r,
            forward_avg >= args.min_forward_average_r and len(matured_forward) >= args.min_matured_forward_observations,
            "Matured forward observations must be positive enough.",
        ),
    ]
    checklist = pd.DataFrame(rows)
    blocked = checklist[checklist["status"] != "pass"].copy()
    decision = "paper_watch_eligible" if blocked.empty else "not_ready"
    next_blocker = str(blocked.iloc[0]["check"]) if not blocked.empty else "None"
    payload = {
        "strategy_id": strategy_id,
        "strategy": strategy_name,
        "decision": decision,
        "checks": checklist.to_dict("records"),
        "blocked_count": int(len(blocked)),
        "next_blocker": next_blocker,
        "tightened_pass_rows": int(len(tightened)),
        "watch_more_rows": int(len(watch_more)),
        "walk_forward_holding_rows": int(len(walk_holding)),
        "shadow_samples": int(len(shadow)),
        "matured_shadow_samples": int(len(matured_shadow)),
        "shadow_average_r": shadow_avg,
        "forward_observations": int(len(forward)),
        "matured_forward_observations": int(len(matured_forward)),
        "forward_average_r": forward_avg,
        "guardrail": "Manual paper-watch review only. No broker orders, no alerts, no live execution.",
    }
    return payload, checklist


def write_gate_report(path: Path, payload: dict[str, Any], checklist: pd.DataFrame) -> None:
    """Write the Markdown gate report."""

    strategy_name = str(payload["strategy"])
    path.write_text(
        f"""# {strategy_name} Paper-Watch Gate

This report decides whether {strategy_name} has enough evidence to be
considered for manual paper-watch review.

Important: even `paper_watch_eligible` would not place orders, create broker
alerts, or enable real-money trading. It only means the strategy can be
reviewed for manual paper validation.

## Decision

```text
Decision: {payload["decision"]}
Blocked checks: {payload["blocked_count"]}
Next blocker: {payload["next_blocker"]}
```

## Gate Checklist

{markdown_table(checklist)}

## Evidence Summary

```text
Tightened pass rows: {payload["tightened_pass_rows"]}
Seed watch-more rows: {payload["watch_more_rows"]}
Walk-forward holding rows: {payload["walk_forward_holding_rows"]}
Shadow samples: {payload["shadow_samples"]} logged / {payload["matured_shadow_samples"]} matured / {payload["shadow_average_r"]:+.2f}R avg
Forward observations: {payload["forward_observations"]} logged / {payload["matured_forward_observations"]} matured / {payload["forward_average_r"]:+.2f}R avg
```

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def write_gate_outputs(output_dir: Path, stem: str, payload: dict[str, Any], checklist: pd.DataFrame) -> None:
    """Write JSON, CSV, and Markdown gate outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}_paper_watch_gate.json"
    csv_path = output_dir / f"{stem}_paper_watch_gate.csv"
    md_path = output_dir / f"{stem}_paper_watch_gate.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    checklist.to_csv(csv_path, index=False)
    write_gate_report(md_path, payload, checklist)
