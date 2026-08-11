"""Evidence maturity review for VWAP reclaim/reject.

This report turns the existing paper-watch gate into a plain-English maturity
checklist. It does not create a second approval system; the paper-watch gate
remains the decision source.

Important: this is research and paper-validation only. It does not fetch data,
append signals, place orders, create broker alerts, or enable execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table
from run_vwap_reclaim_reject_paper_watch_gate import build_gate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build VWAP reclaim/reject evidence maturity review.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--min-tightened-pass-rows", type=int, default=1)
    parser.add_argument("--min-walk-forward-holding-rows", type=int, default=1)
    parser.add_argument("--min-shadow-samples", type=int, default=10)
    parser.add_argument("--min-matured-shadow-samples", type=int, default=5)
    parser.add_argument("--min-shadow-average-r", type=float, default=0.10)
    parser.add_argument("--min-forward-observations", type=int, default=10)
    parser.add_argument("--min-matured-forward-observations", type=int, default=5)
    parser.add_argument("--min-forward-average-r", type=float, default=0.10)
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dictionary."""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def number_value(value: object) -> float:
    """Return a float for maturity math."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def needed_value(current: object, required: object) -> float:
    """Return how much more evidence is needed for a numeric check."""

    return round(max(0.0, number_value(required) - number_value(current)), 4)


def action_for_check(check: str, needed: float, status: str) -> str:
    """Return the most useful next action for one blocked check."""

    if status == "pass":
        return "Complete."
    if check == "Shadow samples logged":
        return f"Collect {int(needed)} more VWAP reclaim/reject shadow sample(s)."
    if check == "Matured shadow outcomes":
        return f"Wait for or re-grade {int(needed)} more completed shadow outcome(s) after session candles finish."
    if check == "Forward observations logged":
        return f"Collect {int(needed)} more real-time VWAP reclaim/reject forward observation(s)."
    if check == "Matured forward outcomes":
        return f"Wait for or re-grade {int(needed)} more completed forward outcome(s) after session candles finish."
    if check == "Shadow average R":
        return "Average R is only meaningful after enough shadow outcomes mature."
    if check == "Forward average R":
        return "Average R is only meaningful after enough forward outcomes mature."
    if check == "Tightened research pass":
        return "Re-run or improve the tightened backtest until at least one row passes."
    if check == "Walk-forward holding up":
        return "Re-run walk-forward review and keep only rows that hold up in newer data."
    return "Keep collecting evidence before paper-watch review."


def build_review(output_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build the VWAP reclaim/reject maturity review."""

    gate_path = output_dir / "vwap_reclaim_reject_paper_watch_gate.json"
    gate = read_json_or_empty(gate_path)
    if not gate:
        gate, _ = build_gate(args)

    checklist = pd.DataFrame(gate.get("checks", []))
    if checklist.empty:
        checklist = pd.DataFrame(columns=["check", "status", "current", "required", "reason"])

    checklist["needed"] = checklist.apply(lambda row: needed_value(row.get("current"), row.get("required")), axis=1)
    checklist["next_action"] = checklist.apply(
        lambda row: action_for_check(str(row.get("check", "")), float(row.get("needed", 0.0)), str(row.get("status", ""))),
        axis=1,
    )

    blocked = checklist[checklist["status"] != "pass"].copy() if "status" in checklist.columns else pd.DataFrame()
    next_blocker = str(gate.get("next_blocker") or (blocked.iloc[0]["check"] if not blocked.empty else "None"))
    if blocked.empty:
        next_action = "Review for manual paper-watch only."
    else:
        matching_blockers = blocked[blocked["check"].astype(str) == next_blocker]
        next_action_row = matching_blockers.iloc[0] if not matching_blockers.empty else blocked.iloc[0]
        next_action = str(next_action_row.get("next_action", "Keep collecting evidence before paper-watch review."))
    payload = {
        "strategy_id": "vwap_reclaim_reject",
        "strategy_name": "VWAP Reclaim / Reject",
        "status": "complete",
        "paper_watch_decision": str(gate.get("decision", "not_ready")),
        "blocked_count": int(gate.get("blocked_count", len(blocked)) or 0),
        "next_blocker": next_blocker,
        "tightened_pass_rows": int(gate.get("tightened_pass_rows", 0) or 0),
        "walk_forward_holding_rows": int(gate.get("walk_forward_holding_rows", 0) or 0),
        "shadow_samples": int(gate.get("shadow_samples", 0) or 0),
        "matured_shadow_samples": int(gate.get("matured_shadow_samples", 0) or 0),
        "shadow_average_r": float(gate.get("shadow_average_r", 0.0) or 0.0),
        "forward_observations": int(gate.get("forward_observations", 0) or 0),
        "matured_forward_observations": int(gate.get("matured_forward_observations", 0) or 0),
        "forward_average_r": float(gate.get("forward_average_r", 0.0) or 0.0),
        "shadow_samples_needed": int(max(0, args.min_shadow_samples - int(gate.get("shadow_samples", 0) or 0))),
        "matured_shadow_needed": int(
            max(0, args.min_matured_shadow_samples - int(gate.get("matured_shadow_samples", 0) or 0))
        ),
        "forward_observations_needed": int(
            max(0, args.min_forward_observations - int(gate.get("forward_observations", 0) or 0))
        ),
        "matured_forward_needed": int(
            max(0, args.min_matured_forward_observations - int(gate.get("matured_forward_observations", 0) or 0))
        ),
        "next_action": next_action,
        "guardrail": (
            "Research and paper-validation only. This review does not place broker orders, "
            "create alerts, import paper trades, or enable live execution."
        ),
        "checks": checklist.to_dict("records"),
    }
    return payload, checklist


def write_report(path: Path, payload: dict[str, Any], checklist: pd.DataFrame) -> None:
    """Write the Markdown maturity report."""

    path.write_text(
        f"""# VWAP Reclaim / Reject Evidence Maturity

This report explains how close VWAP Reclaim / Reject is to paper-watch review.
It uses the existing paper-watch gate as the decision source.

Important: this report is research and paper-validation only. It does not place
broker orders, create alerts, import paper trades, or enable live execution.

## Current Status

```text
Paper-watch decision: {payload["paper_watch_decision"]}
Blocked checks: {payload["blocked_count"]}
Next blocker: {payload["next_blocker"]}
Next action: {payload["next_action"]}
```

## Evidence Still Needed

```text
Shadow samples needed: {payload["shadow_samples_needed"]}
Matured shadow outcomes needed: {payload["matured_shadow_needed"]}
Forward observations needed: {payload["forward_observations_needed"]}
Matured forward outcomes needed: {payload["matured_forward_needed"]}
```

## Evidence Snapshot

```text
Tightened pass rows: {payload["tightened_pass_rows"]}
Walk-forward holding rows: {payload["walk_forward_holding_rows"]}
Shadow samples: {payload["shadow_samples"]} logged / {payload["matured_shadow_samples"]} matured / {payload["shadow_average_r"]:+.2f}R avg
Forward observations: {payload["forward_observations"]} logged / {payload["matured_forward_observations"]} matured / {payload["forward_average_r"]:+.2f}R avg
```

## Maturity Checklist

{markdown_table(checklist)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload, checklist = build_review(args.output_dir, args)
    json_path = args.output_dir / "vwap_reclaim_reject_evidence_maturity.json"
    csv_path = args.output_dir / "vwap_reclaim_reject_evidence_maturity.csv"
    md_path = args.output_dir / "vwap_reclaim_reject_evidence_maturity.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    checklist.to_csv(csv_path, index=False)
    write_report(md_path, payload, checklist)
    print(f"VWAP reclaim/reject maturity decision: {payload['paper_watch_decision']}")
    print(f"Next blocker: {payload['next_blocker']}")
    print(f"Saved evidence maturity report: {md_path}")


if __name__ == "__main__":
    main()
