"""Rank the next validation task for each Strategy Vault family.

This report answers: "What should we deepen next?" It reads existing reports
and builds a queue of research-only tasks such as collecting shadow samples,
waiting for matured outcomes, tightening filters, or adding walk-forward.

It does not run backtests, fetch data, append samples, import paper trades,
place orders, create broker alerts, or enable execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


DEEPENING_REPORTS = {
    "opening_range_breakout": "opening_range_breakout_walk_forward_deepening.json",
    "opening_range_failure": "opening_range_failure_walk_forward_deepening.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build validation deepening queue.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
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
    """Return a float for queue math."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def strategy_rows_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return strategy rows keyed by strategy_id."""

    rows = payload.get("strategies", []) if isinstance(payload.get("strategies", []), list) else []
    return {str(row.get("strategy_id", "")): row for row in rows}


def deepening_deprioritizes(strategy_id: str, output_dir: Path) -> bool:
    """Return True when a deep walk-forward report explicitly weakens priority."""

    filename = DEEPENING_REPORTS.get(strategy_id)
    if not filename:
        return False
    report = read_json_or_empty(output_dir / filename)
    if not report:
        return False
    review_rows = int(number_value(report.get("review_rows", 0)))
    deprioritized_rows = int(number_value(report.get("deprioritized_rows", 0)))
    pass_rows = int(number_value(report.get("walk_forward_pass_rows", 0)))
    provisional_rows = int(number_value(report.get("provisional_walk_forward_pass_rows", 0)))
    return review_rows > 0 and deprioritized_rows >= review_rows and pass_rows == 0 and provisional_rows == 0


def command_for_gap(strategy_id: str, next_gap: str) -> str:
    """Return the safest command or action for a queue row."""

    if next_gap.startswith("Collect strategy shadow") or next_gap.startswith("Collect strategy forward"):
        return "Run market-hours scans; collectors append only qualifying live observations."
    if next_gap.startswith("Mature"):
        return "After the session, run python run_after_close_evidence_maturity.py --output-dir logs."
    if next_gap == "Tighten review filters":
        return f"Review logs/{strategy_id}.md and tighten the strategy-specific first-review thresholds."
    if next_gap == "Add or pass walk-forward":
        return "Run python run_strategy_walk_forward_matrix.py --output-dir logs."
    if next_gap == "Run first-pass backtest":
        return f"Run python run_{strategy_id}.py --output-dir logs."
    if next_gap == "Build paper-watch gate":
        return "Build or refresh the strategy-specific paper-watch gate before promotion."
    if next_gap == "Activation rules blocked":
        return "Run python run_paper_activation_rules.py --output-dir logs and inspect blocked checks."
    if next_gap == "None":
        return "No deepening task needed; keep the active paper-watch strategy under normal review."
    if next_gap == "Deprioritized until evidence improves":
        return "Do not prioritize new evidence until newer-slice expectancy and profit factor improve."
    return "Inspect the coverage matrix and strategy vault before changing routing."


def validation_lane(next_gap: str) -> str:
    """Return the validation lane for one next gap."""

    if next_gap.startswith("Collect strategy shadow"):
        return "shadow_collection"
    if next_gap.startswith("Collect strategy forward"):
        return "forward_collection"
    if next_gap.startswith("Mature"):
        return "outcome_maturity"
    if next_gap == "Tighten review filters":
        return "tightened_review"
    if next_gap == "Add or pass walk-forward":
        return "walk_forward"
    if next_gap == "Run first-pass backtest":
        return "first_pass_backtest"
    if next_gap == "Build paper-watch gate":
        return "paper_watch_gate"
    if next_gap == "Activation rules blocked":
        return "activation_rules"
    if next_gap == "None":
        return "complete_or_active"
    if next_gap == "Deprioritized until evidence improves":
        return "deprioritized"
    return "manual_review"


def priority_score(coverage: dict[str, Any], vault: dict[str, Any], deprioritized: bool = False) -> float:
    """Score rows so the closest useful validation task rises first."""

    if deprioritized:
        return -50.0
    if str(coverage.get("activation_status", "")) == "complete":
        return -100.0
    score = number_value(coverage.get("coverage_points", 0)) * 10
    decision = str(vault.get("decision", ""))
    status = str(vault.get("status", ""))
    if decision == "research_priority":
        score += 8
    if status == "active_paper_watch":
        score -= 20
    if str(coverage.get("shadow_lane", "")) == "partial" or str(coverage.get("forward_lane", "")) == "partial":
        score += 4
    if str(coverage.get("walk_forward", "")) == "complete":
        score += 2
    return round(score, 2)


def build_queue(output_dir: Path) -> dict[str, Any]:
    """Build the validation deepening queue payload."""

    vault = read_json_or_empty(output_dir / "strategy_vault.json")
    coverage = read_json_or_empty(output_dir / "strategy_backtest_coverage.json")
    activation = read_json_or_empty(output_dir / "paper_activation_rules.json")

    vault_by_id = strategy_rows_by_id(vault)
    activation_by_id = strategy_rows_by_id(activation)
    coverage_rows = coverage.get("strategies", []) if isinstance(coverage.get("strategies", []), list) else []

    rows = []
    for coverage_row in coverage_rows:
        strategy_id = str(coverage_row.get("strategy_id", ""))
        vault_row = vault_by_id.get(strategy_id, {})
        activation_row = activation_by_id.get(strategy_id, {})
        next_gap = str(coverage_row.get("next_gap", "") or "Manual review")
        is_deprioritized = deepening_deprioritizes(strategy_id, output_dir)
        if is_deprioritized:
            next_gap = "Deprioritized until evidence improves"
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy": coverage_row.get("strategy", ""),
                "priority_score": priority_score(coverage_row, vault_row, is_deprioritized),
                "validation_lane": validation_lane(next_gap),
                "next_gap": next_gap,
                "next_command": command_for_gap(strategy_id, next_gap),
                "vault_decision": vault_row.get("decision", coverage_row.get("vault_decision", "")),
                "activation_decision": activation_row.get("activation_decision", coverage_row.get("activation_decision", "")),
                "coverage_percent": coverage_row.get("coverage_percent", 0),
                "tightened_review": coverage_row.get("tightened_review", ""),
                "walk_forward": coverage_row.get("walk_forward", ""),
                "shadow_lane": coverage_row.get("shadow_lane", ""),
                "shadow_rows": int(number_value(coverage_row.get("shadow_rows", 0))),
                "matured_shadow": int(number_value(coverage_row.get("matured_shadow", 0))),
                "forward_lane": coverage_row.get("forward_lane", ""),
                "forward_rows": int(number_value(coverage_row.get("forward_rows", 0))),
                "matured_forward": int(number_value(coverage_row.get("matured_forward", 0))),
                "paper_watch_gate": coverage_row.get("paper_watch_gate", ""),
                "gate_decision": coverage_row.get("gate_decision", ""),
            }
        )

    rows.sort(key=lambda row: (-float(row["priority_score"]), str(row["strategy"])))
    top = rows[0] if rows else {}
    return {
        "status": "complete" if rows else "missing_coverage",
        "strategy_count": int(len(rows)),
        "top_strategy_id": top.get("strategy_id", ""),
        "top_strategy": top.get("strategy", ""),
        "top_validation_lane": top.get("validation_lane", ""),
        "top_next_gap": top.get("next_gap", "Run strategy coverage first."),
        "top_next_command": top.get("next_command", "Run python run_strategy_backtest_coverage.py --output-dir logs."),
        "guardrail": (
            "Validation deepening is research/paper validation only. It does not run backtests, fetch data, "
            "append samples, import paper trades, place orders, create broker alerts, or enable execution."
        ),
        "strategies": rows,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown queue outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "validation_deepening_queue.json"
    csv_path = output_dir / "validation_deepening_queue.csv"
    md_path = output_dir / "validation_deepening_queue.md"
    rows = pd.DataFrame(payload["strategies"])

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Validation Deepening Queue

This report ranks the next research-only validation task for each strategy.
It helps decide whether to collect shadow samples, collect forward observations,
wait for matured outcomes, tighten filters, or refresh walk-forward evidence.

Important: this report does not run backtests, fetch data, append samples,
import paper trades, place broker orders, create broker alerts, or enable
execution.

## Summary

```text
Status: {payload["status"]}
Strategies ranked: {payload["strategy_count"]}
Top strategy: {payload["top_strategy"]}
Top lane: {payload["top_validation_lane"]}
Top next gap: {payload["top_next_gap"]}
Top next command: {payload["top_next_command"]}
```

## Queue

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
    payload = build_queue(args.output_dir)
    write_outputs(args.output_dir, payload)
    print(f"Validation queue status: {payload['status']}")
    print(f"Top next gap: {payload['top_next_gap']}")
    print(f"Saved validation queue report: {args.output_dir / 'validation_deepening_queue.md'}")


if __name__ == "__main__":
    main()
