"""Paper-watch gate for VWAP mean reversion.

This report answers whether the Strategy Vault's VWAP Mean Reversion candidate
has enough evidence to be considered for manual paper-watch review.

Important: passing this gate would not place orders, create broker alerts, or
enable real-money trading. It is a research-to-paper-watch checklist only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build VWAP mean-reversion paper-watch gate.")
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


def build_gate(args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build the paper-watch gate payload and checklist rows."""

    output_dir = args.output_dir
    summary = read_csv_or_empty(output_dir / "vwap_mean_reversion_summary.csv")
    walk_forward = read_csv_or_empty(output_dir / "vwap_mean_reversion_walk_forward.csv")
    shadow = read_csv_or_empty(output_dir / "vwap_mean_reversion_shadow_outcomes.csv")
    forward = read_csv_or_empty(output_dir / "vwap_mean_reversion_forward_observation_results.csv")

    tightened = (
        summary[summary["tightened_review"] == "passes_tightened_research"].copy()
        if not summary.empty and "tightened_review" in summary.columns
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
            "At least one row must pass the tightened backtest review.",
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
        "strategy_id": "vwap_mean_reversion",
        "decision": decision,
        "checks": checklist.to_dict("records"),
        "blocked_count": int(len(blocked)),
        "next_blocker": next_blocker,
        "tightened_pass_rows": int(len(tightened)),
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


def write_report(path: Path, payload: dict[str, Any], checklist: pd.DataFrame) -> None:
    """Write the Markdown gate report."""

    path.write_text(
        f"""# VWAP Mean Reversion Paper-Watch Gate

This report decides whether VWAP Mean Reversion has enough evidence to be
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


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload, checklist = build_gate(args)
    json_path = args.output_dir / "vwap_mean_reversion_paper_watch_gate.json"
    csv_path = args.output_dir / "vwap_mean_reversion_paper_watch_gate.csv"
    md_path = args.output_dir / "vwap_mean_reversion_paper_watch_gate.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    checklist.to_csv(csv_path, index=False)
    write_report(md_path, payload, checklist)
    print(f"Mean reversion paper-watch decision: {payload['decision']}")
    print(f"Next blocker: {payload['next_blocker']}")
    print(f"Saved paper-watch gate report: {md_path}")


if __name__ == "__main__":
    main()
