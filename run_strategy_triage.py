"""Build a strategy triage report.

This report separates strategy families into practical next-action buckets:
collect market-hours evidence, keep deepening offline, deprioritize, or keep
under active paper-watch review.

It is research and paper-validation guidance only. It does not fetch data,
append samples, import paper trades, place orders, create broker alerts, or
enable execution.
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
    parser = argparse.ArgumentParser(description="Build strategy triage report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def rows_by_id(payload: dict[str, Any], key: str = "strategies") -> dict[str, dict[str, Any]]:
    """Return payload rows keyed by strategy_id."""

    rows = payload.get(key, []) if isinstance(payload.get(key, []), list) else []
    return {str(row.get("strategy_id", "")): row for row in rows}


def deepening_status(strategy_id: str, output_dir: Path) -> dict[str, Any]:
    """Return explicit deepening status for strategies with reports."""

    filename = DEEPENING_REPORTS.get(strategy_id)
    if not filename:
        return {
            "deepening_decision": "",
            "deepening_report": "",
            "deepening_note": "",
        }
    report = read_json_or_empty(output_dir / filename)
    if not report:
        return {
            "deepening_decision": "missing",
            "deepening_report": filename.replace(".json", ".md"),
            "deepening_note": "Run the strategy-specific deepening report.",
        }
    final_rows = int(report.get("walk_forward_pass_rows", 0) or 0)
    provisional_rows = int(report.get("provisional_walk_forward_pass_rows", 0) or 0)
    deprioritized_rows = int(report.get("deprioritized_rows", 0) or 0)
    review_rows = int(report.get("review_rows", 0) or 0)
    if final_rows > 0:
        decision = "walk_forward_pass"
    elif provisional_rows > 0:
        decision = "provisional_walk_forward_pass"
    elif deprioritized_rows >= review_rows and review_rows > 0:
        decision = "deprioritized"
    else:
        decision = "needs_more_evidence"
    return {
        "deepening_decision": decision,
        "deepening_report": filename.replace(".json", ".md"),
        "deepening_note": str(report.get("next_action", "")),
    }


def triage_tier(coverage: dict[str, Any], activation: dict[str, Any], deepening: dict[str, Any]) -> tuple[str, str]:
    """Return tier and next action for one strategy."""

    if str(coverage.get("vault_status", "")) == "active_paper_watch":
        return "active_paper_watch", "Keep active setup under normal manual paper-review guardrails."
    if deepening.get("deepening_decision") == "deprioritized":
        return "deprioritized", str(deepening.get("deepening_note") or "Wait for stronger newer-slice evidence.")
    if str(activation.get("activation_decision", "")) == "paper_watch_eligible":
        return "manual_paper_watch_review", "Review manually before allowing any paper-watch route."
    next_gap = str(coverage.get("next_gap", ""))
    if next_gap.startswith("Collect strategy shadow") or next_gap.startswith("Collect strategy forward"):
        return "market_hours_collection", "Run market-hours scans; collect only qualifying strategy-specific observations."
    if next_gap.startswith("Mature"):
        return "after_close_maturity", "Run after-close evidence maturity once session candles are complete."
    if next_gap in {"Tighten review filters", "Add or pass walk-forward", "Run first-pass backtest"}:
        return "offline_deepening", "Use offline reports/backtests to decide whether this strategy deserves more evidence."
    return "blocked_or_waiting", str(activation.get("next_blocker", "") or next_gap or "Review coverage matrix.")


def build_triage(output_dir: Path) -> dict[str, Any]:
    """Build the strategy triage payload."""

    coverage_payload = read_json_or_empty(output_dir / "strategy_backtest_coverage.json")
    activation_payload = read_json_or_empty(output_dir / "paper_activation_rules.json")
    vault_payload = read_json_or_empty(output_dir / "strategy_vault.json")
    activation_by_id = rows_by_id(activation_payload)
    vault_by_id = rows_by_id(vault_payload)
    coverage_rows = coverage_payload.get("strategies", []) if isinstance(coverage_payload.get("strategies", []), list) else []

    rows = []
    for coverage in coverage_rows:
        strategy_id = str(coverage.get("strategy_id", ""))
        activation = activation_by_id.get(strategy_id, {})
        vault = vault_by_id.get(strategy_id, {})
        deepening = deepening_status(strategy_id, output_dir)
        tier, next_action = triage_tier(coverage, activation, deepening)
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy": coverage.get("strategy", vault.get("name", "")),
                "triage_tier": tier,
                "next_action": next_action,
                "vault_decision": coverage.get("vault_decision", vault.get("decision", "")),
                "activation_decision": activation.get("activation_decision", coverage.get("activation_decision", "")),
                "coverage_percent": coverage.get("coverage_percent", 0),
                "next_gap": coverage.get("next_gap", ""),
                "tightened_review": coverage.get("tightened_review", ""),
                "walk_forward": coverage.get("walk_forward", ""),
                "shadow_rows": coverage.get("shadow_rows", 0),
                "forward_rows": coverage.get("forward_rows", 0),
                "deepening_decision": deepening.get("deepening_decision", ""),
                "deepening_report": deepening.get("deepening_report", ""),
            }
        )

    order = {
        "manual_paper_watch_review": 0,
        "market_hours_collection": 1,
        "after_close_maturity": 2,
        "offline_deepening": 3,
        "active_paper_watch": 4,
        "blocked_or_waiting": 5,
        "deprioritized": 6,
    }
    rows.sort(key=lambda row: (order.get(str(row["triage_tier"]), 9), -float(row.get("coverage_percent", 0)), str(row["strategy"])))
    counts = pd.DataFrame(rows).groupby("triage_tier").size().reset_index(name="strategies") if rows else pd.DataFrame()
    top = rows[0] if rows else {}
    return {
        "status": "complete" if rows else "missing_coverage",
        "strategy_count": int(len(rows)),
        "top_strategy_id": top.get("strategy_id", ""),
        "top_strategy": top.get("strategy", ""),
        "top_tier": top.get("triage_tier", ""),
        "top_next_action": top.get("next_action", "Run strategy coverage first."),
        "tier_counts": counts.to_dict("records") if not counts.empty else [],
        "guardrail": (
            "Strategy triage is guidance only. It does not fetch data, append samples, "
            "import paper trades, place orders, create broker alerts, or enable execution."
        ),
        "strategies": rows,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown strategy triage outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "strategy_triage.json"
    csv_path = output_dir / "strategy_triage.csv"
    md_path = output_dir / "strategy_triage.md"
    rows = pd.DataFrame(payload["strategies"])
    counts = pd.DataFrame(payload["tier_counts"])
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Strategy Triage

This report ranks strategy families by what they actually need next: market
hours evidence, offline deepening, maturity grading, or deprioritization.

Important: this is research and paper-validation guidance only. It does not
fetch data, append samples, import paper trades, place broker orders, create
broker alerts, or enable execution.

## Summary

```text
Status: {payload["status"]}
Strategies checked: {payload["strategy_count"]}
Top strategy: {payload["top_strategy"]}
Top tier: {payload["top_tier"]}
Top next action: {payload["top_next_action"]}
```

## Tier Counts

{markdown_table(counts)}

## Triage Matrix

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
    payload = build_triage(args.output_dir)
    write_outputs(args.output_dir, payload)
    print(f"Strategy triage status: {payload['status']}")
    print(f"Top tier: {payload['top_tier']}")


if __name__ == "__main__":
    main()
