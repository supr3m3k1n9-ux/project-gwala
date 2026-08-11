"""Build the Strategy Backtest Coverage Matrix.

This report audits every strategy in the vault and shows which evidence layers
exist: first-pass backtest, tightened review, walk-forward, shadow lane,
forward lane, paper-watch gate, and activation status.

It does not run backtests, fetch data, append signals, place orders, create
broker alerts, import paper trades, or enable execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


STRATEGY_STEMS = {
    "vwap_mean_reversion": "vwap_mean_reversion",
    "gap_fill_fade": "gap_fill_fade",
    "vwap_reclaim_reject": "vwap_reclaim_reject",
    "opening_range_breakout": "opening_range_breakout",
    "trend_pullback_continuation": "trend_pullback_continuation",
    "opening_range_failure": "opening_range_failure",
}

MIN_SHADOW_ROWS = 10
MIN_MATURED_SHADOW_ROWS = 5
MIN_FORWARD_ROWS = 10
MIN_MATURED_FORWARD_ROWS = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build strategy backtest coverage matrix.")
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


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV file or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def status_label(passed: bool, partial: bool = False) -> str:
    """Return a compact coverage status."""

    if passed:
        return "complete"
    if partial:
        return "partial"
    return "missing"


def count_rows(frame: pd.DataFrame, column: str, value: str) -> int:
    """Count rows where column equals value."""

    if frame.empty or column not in frame.columns:
        return 0
    return int((frame[column].astype(str) == value).sum())


def tightened_counts(strategy_id: str, output_dir: Path, summary: pd.DataFrame) -> tuple[int, int]:
    """Return final and provisional tightened pass counts for a strategy."""

    final_pass_rows = count_rows(summary, "tightened_review", "passes_tightened_research")
    provisional_pass_rows = 0
    if strategy_id == "trend_pullback_continuation":
        review = read_csv_or_empty(output_dir / "trend_pullback_continuation_tightened_review.csv")
        final_pass_rows += count_rows(review, "decision", "passes_tightened_research")
        provisional_pass_rows = count_rows(review, "decision", "provisional_tightened_pass")
    elif strategy_id in {"gap_fill_fade", "opening_range_breakout", "opening_range_failure"}:
        review = read_csv_or_empty(output_dir / f"{strategy_id}_tightened_review.csv")
        final_pass_rows += count_rows(review, "decision", "passes_tightened_research")
        provisional_pass_rows = count_rows(review, "decision", "provisional_tightened_pass")
        provisional_pass_rows += count_rows(review, "decision", "seed_shadow_candidate")
    return final_pass_rows, provisional_pass_rows


def walk_forward_holding_count(strategy_id: str, output_dir: Path, walk_forward: pd.DataFrame) -> int:
    """Return final/provisional walk-forward pass rows for a strategy."""

    holding = count_rows(walk_forward, "decision", "holding_up")
    if strategy_id == "opening_range_failure":
        deepening = read_csv_or_empty(output_dir / "opening_range_failure_walk_forward_deepening.csv")
        holding += count_rows(deepening, "decision", "walk_forward_pass")
        holding += count_rows(deepening, "decision", "provisional_walk_forward_pass")
    elif strategy_id == "opening_range_breakout":
        deepening = read_csv_or_empty(output_dir / "opening_range_breakout_walk_forward_deepening.csv")
        holding += count_rows(deepening, "decision", "walk_forward_pass")
        holding += count_rows(deepening, "decision", "provisional_walk_forward_pass")
    elif strategy_id == "gap_fill_fade":
        review = read_csv_or_empty(output_dir / "gap_fill_fade_tightened_review.csv")
        holding += count_rows(review, "decision", "seed_shadow_candidate")
    return holding


def activation_by_strategy(output_dir: Path) -> dict[str, dict[str, Any]]:
    """Return paper activation summary rows keyed by strategy id."""

    activation = read_json_or_empty(output_dir / "paper_activation_rules.json")
    rows = activation.get("strategies", []) if isinstance(activation.get("strategies", []), list) else []
    return {str(row.get("strategy_id", "")): row for row in rows}


def coverage_row(strategy: dict[str, Any], output_dir: Path, activation: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build one coverage row from vault strategy plus evidence files."""

    strategy_id = str(strategy.get("strategy_id", ""))
    stem = STRATEGY_STEMS.get(strategy_id)
    active_paper = str(strategy.get("status", "")) == "active_paper_watch"
    summary = read_csv_or_empty(output_dir / f"{stem}_summary.csv") if stem else pd.DataFrame()
    walk_forward = read_csv_or_empty(output_dir / f"{stem}_walk_forward.csv") if stem else pd.DataFrame()
    shadow = read_csv_or_empty(output_dir / f"{stem}_shadow_outcomes.csv") if stem else pd.DataFrame()
    forward = read_csv_or_empty(output_dir / f"{stem}_forward_observation_results.csv") if stem else pd.DataFrame()
    gate = read_json_or_empty(output_dir / f"{stem}_paper_watch_gate.json") if stem else {}
    activation_row = activation.get(strategy_id, {})

    first_pass_rows = int(len(summary))
    final_tightened_pass_rows, provisional_tightened_pass_rows = tightened_counts(strategy_id, output_dir, summary)
    tightened_pass_rows = final_tightened_pass_rows + provisional_tightened_pass_rows
    promising_rows = count_rows(summary, "research_status", "promising") + count_rows(summary, "research_status", "watch_more")
    walk_forward_holding = walk_forward_holding_count(strategy_id, output_dir, walk_forward)
    shadow_rows = int(len(shadow))
    matured_shadow = count_rows(shadow, "evaluation_status", "matured")
    forward_rows = int(len(forward))
    matured_forward = count_rows(forward, "evaluation_status", "matured")
    gate_decision = str(gate.get("decision", "not_applicable" if active_paper else "missing") or "")
    activation_decision = str(activation_row.get("activation_decision", "active_paper_watch" if active_paper else "missing") or "")

    first_pass_status = status_label(first_pass_rows > 0 or active_paper)
    tightened_status = status_label(tightened_pass_rows > 0 or active_paper, promising_rows > 0)
    walk_forward_status = status_label(walk_forward_holding > 0 or active_paper, not walk_forward.empty)
    shadow_ready = shadow_rows >= MIN_SHADOW_ROWS and matured_shadow >= MIN_MATURED_SHADOW_ROWS
    forward_ready = forward_rows >= MIN_FORWARD_ROWS and matured_forward >= MIN_MATURED_FORWARD_ROWS
    shadow_status = status_label(shadow_ready, shadow_rows > 0 or matured_shadow > 0)
    forward_status = status_label(forward_ready, forward_rows > 0 or matured_forward > 0)
    gate_status = status_label(gate_decision in {"paper_watch_eligible", "not_ready"} or active_paper)
    activation_status = status_label(activation_decision in {"paper_watch_eligible", "active_paper_watch"})

    statuses = [
        first_pass_status,
        tightened_status,
        walk_forward_status,
        shadow_status,
        forward_status,
        gate_status,
        activation_status,
    ]
    complete_count = sum(1 for status in statuses if status == "complete")
    partial_count = sum(1 for status in statuses if status == "partial")
    coverage_points = complete_count + (partial_count * 0.5)
    if activation_status == "complete":
        next_gap = "None"
    elif first_pass_status == "missing":
        next_gap = "Run first-pass backtest"
    elif tightened_status != "complete":
        next_gap = "Tighten review filters"
    elif walk_forward_status != "complete":
        next_gap = "Add or pass walk-forward"
    elif shadow_status != "complete":
        if shadow_rows < MIN_SHADOW_ROWS:
            next_gap = f"Collect strategy shadow samples ({shadow_rows}/{MIN_SHADOW_ROWS})"
        else:
            next_gap = f"Mature shadow outcomes ({matured_shadow}/{MIN_MATURED_SHADOW_ROWS})"
    elif forward_status != "complete":
        if forward_rows < MIN_FORWARD_ROWS:
            next_gap = f"Collect strategy forward observations ({forward_rows}/{MIN_FORWARD_ROWS})"
        else:
            next_gap = f"Mature forward outcomes ({matured_forward}/{MIN_MATURED_FORWARD_ROWS})"
    elif gate_status != "complete":
        next_gap = "Build paper-watch gate"
    else:
        next_gap = "Activation rules blocked"

    return {
        "strategy_id": strategy_id,
        "strategy": strategy.get("name", ""),
        "vault_status": strategy.get("status", ""),
        "vault_decision": strategy.get("decision", ""),
        "first_pass_backtest": first_pass_status,
        "tested_rows": first_pass_rows,
        "tightened_review": tightened_status,
        "tightened_pass_rows": tightened_pass_rows,
        "final_tightened_pass_rows": final_tightened_pass_rows,
        "provisional_tightened_pass_rows": provisional_tightened_pass_rows,
        "walk_forward": walk_forward_status,
        "walk_forward_holding_rows": walk_forward_holding,
        "shadow_lane": shadow_status,
        "shadow_rows": shadow_rows,
        "matured_shadow": matured_shadow,
        "forward_lane": forward_status,
        "forward_rows": forward_rows,
        "matured_forward": matured_forward,
        "paper_watch_gate": gate_status,
        "gate_decision": gate_decision,
        "activation_status": activation_status,
        "activation_decision": activation_decision,
        "coverage_points": coverage_points,
        "coverage_percent": round((coverage_points / 7) * 100, 1),
        "next_gap": next_gap,
    }


def build_coverage(output_dir: Path) -> dict[str, Any]:
    """Build the coverage matrix payload."""

    vault = read_json_or_empty(output_dir / "strategy_vault.json")
    strategies = vault.get("strategies", []) if isinstance(vault.get("strategies", []), list) else []
    activation = activation_by_strategy(output_dir)
    rows = [coverage_row(strategy, output_dir, activation) for strategy in strategies]
    matrix = pd.DataFrame(rows)
    coverage_percent = round(float(matrix["coverage_percent"].mean()), 1) if not matrix.empty else 0.0
    fully_covered = int((matrix["coverage_percent"] >= 100).sum()) if not matrix.empty else 0
    gate_ready = int((matrix["activation_status"] == "complete").sum()) if not matrix.empty else 0
    missing_forward = int((matrix["forward_lane"] == "missing").sum()) if not matrix.empty else 0
    next_gap = str(matrix.sort_values(["coverage_points", "strategy"], ascending=[False, True]).iloc[0]["next_gap"]) if not matrix.empty else "Run strategy vault."
    return {
        "status": "complete" if not matrix.empty else "missing_vault",
        "strategy_count": int(len(matrix)),
        "average_coverage_percent": coverage_percent,
        "fully_covered_count": fully_covered,
        "activation_ready_count": gate_ready,
        "missing_forward_lane_count": missing_forward,
        "next_action": (
            "Prioritize the highest-coverage blocked strategy's next gap: "
            f"{next_gap}."
            if not matrix.empty
            else "Run the strategy vault before building coverage."
        ),
        "guardrail": (
            "Coverage is research/paper validation only. It does not run backtests, place orders, "
            "create broker alerts, import paper trades, or enable execution."
        ),
        "strategies": rows,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "strategy_backtest_coverage.json"
    csv_path = output_dir / "strategy_backtest_coverage.csv"
    md_path = output_dir / "strategy_backtest_coverage.md"
    rows = pd.DataFrame(payload["strategies"])

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Strategy Backtest Coverage Matrix

This report audits whether each Strategy Vault family has the evidence layers
needed before it can be taken seriously for paper-watch review.

Important: this is research and paper-validation only. It does not run
backtests, fetch data, append signals, import paper trades, place broker
orders, create broker alerts, or enable execution.

## Summary

```text
Status: {payload["status"]}
Strategies checked: {payload["strategy_count"]}
Average coverage: {payload["average_coverage_percent"]}%
Fully covered strategies: {payload["fully_covered_count"]}
Activation-ready strategies: {payload["activation_ready_count"]}
Strategies missing forward lanes: {payload["missing_forward_lane_count"]}
Next action: {payload["next_action"]}
```

## Coverage Matrix

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
    payload = build_coverage(args.output_dir)
    write_outputs(args.output_dir, payload)
    print(f"Coverage status: {payload['status']}")
    print(f"Strategies checked: {payload['strategy_count']}")
    print(f"Average coverage: {payload['average_coverage_percent']}%")
    print(f"Saved strategy coverage report: {args.output_dir / 'strategy_backtest_coverage.md'}")


if __name__ == "__main__":
    main()
