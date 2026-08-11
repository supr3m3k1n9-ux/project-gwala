"""Define the research-to-paper-watch activation contract.

This report is the universal graduation checklist for Project Gwala strategy
families. It does not promote strategies automatically, place broker orders,
create broker alerts, or enable real-money trading. It only makes the rules
explicit so a research strategy cannot quietly become paper-watch eligible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


ACTIVATION_RULES = [
    {
        "check": "Strategy-specific gate exists",
        "field": "paper_watch_decision",
        "required": "paper_watch_eligible",
        "reason": "A dedicated strategy gate must explicitly approve manual paper-watch review.",
    },
    {
        "check": "Tightened research pass",
        "field": "tightened_pass_rows",
        "required": 1,
        "reason": "At least one tightened backtest row must survive first-review thresholds.",
    },
    {
        "check": "Walk-forward holding up",
        "field": "walk_forward_holding_rows",
        "required": 1,
        "reason": "The newer half must still hold up before forward paper review.",
    },
    {
        "check": "Strategy shadow samples",
        "field": "shadow_samples",
        "required": 10,
        "reason": "The strategy needs enough strategy-specific shadow sightings.",
    },
    {
        "check": "Matured shadow outcomes",
        "field": "matured_shadow_samples",
        "required": 5,
        "reason": "Enough shadow samples must have completed outcomes.",
    },
    {
        "check": "Shadow average R",
        "field": "shadow_average_r",
        "required": 0.10,
        "reason": "Matured shadow evidence must be positive enough.",
    },
    {
        "check": "Strategy forward observations",
        "field": "forward_observations",
        "required": 10,
        "reason": "The strategy needs enough real-time forward observations.",
    },
    {
        "check": "Matured forward outcomes",
        "field": "matured_forward_observations",
        "required": 5,
        "reason": "Enough forward observations must have completed outcomes.",
    },
    {
        "check": "Forward average R",
        "field": "forward_average_r",
        "required": 0.10,
        "reason": "Matured forward evidence must be positive enough.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build paper activation rules report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON file or return an empty dict."""

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def number_value(value: object) -> float:
    """Return a float for numeric gate comparisons."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def rule_passes(strategy: dict[str, Any], rule: dict[str, Any]) -> bool:
    """Return whether one strategy row passes one activation rule."""

    field = str(rule["field"])
    required = rule["required"]
    current = strategy.get(field, "")
    if field == "paper_watch_decision":
        return str(current) == str(required)
    return number_value(current) >= float(required)


def rule_row(strategy: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    """Return one activation checklist row."""

    field = str(rule["field"])
    current = strategy.get(field, "")
    passed = rule_passes(strategy, rule)
    return {
        "strategy_id": strategy.get("strategy_id", ""),
        "strategy": strategy.get("name", ""),
        "check": rule["check"],
        "status": "pass" if passed else "blocked",
        "current": current,
        "required": rule["required"],
        "reason": rule["reason"],
    }


def activation_decision(rows: pd.DataFrame) -> tuple[str, int, str]:
    """Return activation decision, blocked count, and first blocker."""

    blocked = rows[rows["status"] != "pass"].copy() if not rows.empty else pd.DataFrame()
    if blocked.empty:
        return "paper_watch_eligible", 0, "None"
    return "not_ready", int(len(blocked)), str(blocked.iloc[0]["check"])


def build_activation_payload(output_dir: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Build activation payload plus strategy/rule tables."""

    vault = read_json_or_empty(output_dir / "strategy_vault.json")
    strategies = vault.get("strategies", []) if isinstance(vault.get("strategies", []), list) else []
    research_strategies = [row for row in strategies if row.get("status") != "active_paper_watch"]

    checklist_rows = []
    summary_rows = []
    for strategy in research_strategies:
        strategy_rows = pd.DataFrame(rule_row(strategy, rule) for rule in ACTIVATION_RULES)
        decision, blocked_count, next_blocker = activation_decision(strategy_rows)
        if next_blocker == "Strategy-specific gate exists" and strategy.get("paper_watch_decision") == "not_ready":
            next_blocker = str(strategy.get("paper_watch_blocker", next_blocker) or next_blocker)
        checklist_rows.extend(strategy_rows.to_dict("records"))
        summary_rows.append(
            {
                "strategy_id": strategy.get("strategy_id", ""),
                "strategy": strategy.get("name", ""),
                "vault_decision": strategy.get("decision", ""),
                "activation_decision": decision,
                "blocked_count": blocked_count,
                "next_blocker": next_blocker,
                "paper_watch_decision": strategy.get("paper_watch_decision", ""),
                "paper_watch_blocker": strategy.get("paper_watch_blocker", ""),
                "tightened_pass_rows": strategy.get("tightened_pass_rows", 0),
                "walk_forward_holding_rows": strategy.get("walk_forward_holding_rows", 0),
                "shadow_samples": strategy.get("shadow_samples", 0),
                "forward_observations": strategy.get("forward_observations", 0),
            }
        )

    summary = pd.DataFrame(summary_rows)
    checklist = pd.DataFrame(checklist_rows)
    eligible = int((summary["activation_decision"] == "paper_watch_eligible").sum()) if not summary.empty else 0
    blocked = int((summary["activation_decision"] != "paper_watch_eligible").sum()) if not summary.empty else 0
    next_action = (
        "A research strategy is eligible for manual paper-watch review. Review it manually before changing any scanner route."
        if eligible
        else "No research strategy is eligible for manual paper-watch review yet. Keep collecting strategy-specific evidence."
    )
    payload = {
        "eligible_strategy_count": eligible,
        "blocked_strategy_count": blocked,
        "next_action": next_action,
        "guardrail": (
            "Activation means manual paper-watch review only. It does not place orders, "
            "create broker alerts, enable Webull execution, or approve real-money trading."
        ),
        "rules": ACTIVATION_RULES,
        "strategies": summary_rows,
    }
    return payload, summary, checklist


def write_outputs(output_dir: Path, payload: dict[str, Any], summary: pd.DataFrame, checklist: pd.DataFrame) -> None:
    """Write activation rule outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "paper_activation_rules.json"
    summary_csv = output_dir / "paper_activation_rules.csv"
    checklist_csv = output_dir / "paper_activation_checklist.csv"
    md_path = output_dir / "paper_activation_rules.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary.to_csv(summary_csv, index=False)
    checklist.to_csv(checklist_csv, index=False)
    md_path.write_text(
        f"""# Paper Trading Activation Rules

This report defines the exact contract a research strategy must satisfy before
it can move from research-only to manual paper-watch review.

Important: this does not approve real-money trading, place broker orders,
create broker alerts, or connect to Webull execution.

## Summary

```text
Eligible research strategies: {payload["eligible_strategy_count"]}
Blocked research strategies: {payload["blocked_strategy_count"]}
Next action: {payload["next_action"]}
```

## Strategy Decisions

{markdown_table(summary)}

## Activation Checklist

{markdown_table(checklist)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
{json_path}
{summary_csv}
{checklist_csv}
{md_path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload, summary, checklist = build_activation_payload(args.output_dir)
    write_outputs(args.output_dir, payload, summary, checklist)
    print(f"Eligible research strategies: {payload['eligible_strategy_count']}")
    print(f"Blocked research strategies: {payload['blocked_strategy_count']}")
    print(f"Saved paper activation rules report: {args.output_dir / 'paper_activation_rules.md'}")


if __name__ == "__main__":
    main()
