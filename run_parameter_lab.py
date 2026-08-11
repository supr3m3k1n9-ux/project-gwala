"""Run the Project Gwala Parameter Lab.

This is a research-only subsystem. It inventories numeric engineering
thresholds and can run isolated experiments without changing production
settings, paper logs, broker orders, alerts, or trading philosophy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from reports.parameter_lab import (
    build_candidate_universe,
    evidence_groups,
    parameter_inventory,
    run_threshold_experiment,
)

DEFAULT_EXPERIMENTS = [
    "paper_gate.a_min_check_score",
    "paper_gate.a_min_quality_score",
    "paper_gate.b_min_check_score",
    "paper_gate.b_min_quality_score",
    "paper_gate.b_min_room_to_target_r",
    "strategy.min_relative_volume",
    "strategy.min_room_to_resistance_r",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Parameter Lab inventory and threshold experiments.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Directory containing candle caches.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Directory for lab outputs.")
    parser.add_argument("--playbook", default="approved_plus_watch")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--market-regime-symbol", default="SPY")
    parser.add_argument(
        "--parameter",
        action="append",
        choices=DEFAULT_EXPERIMENTS,
        help="Parameter id to experiment. Omit to run the default experiment set.",
    )
    parser.add_argument("--values", nargs="*", type=float, help="Override test values for a single --parameter.")
    parser.add_argument("--inventory-only", action="store_true", help="Write inventory and skip candle replay.")
    return parser.parse_args()


def clean_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return JSON-safe records."""

    records: list[dict[str, Any]] = []
    for item in frame.to_dict("records"):
        clean: dict[str, Any] = {}
        for key, value in item.items():
            if value is None:
                clean[key] = ""
            elif isinstance(value, (list, tuple)):
                clean[key] = list(value)
            elif pd.isna(value):
                clean[key] = ""
            else:
                clean[key] = value
        records.append(clean)
    return records


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Render a small markdown table from records."""

    if not rows:
        return "No rows.\n"
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join([header, divider, *body]) + "\n"


def table_records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    """Return table records, tolerating intentionally empty frames."""

    if frame.empty:
        return []
    usable = frame.copy()
    for column in columns:
        if column not in usable.columns:
            usable[column] = ""
    return usable[columns].to_dict("records")


def write_outputs(
    *,
    output_dir: Path,
    inventory: pd.DataFrame,
    experiments: pd.DataFrame,
    candidates: pd.DataFrame,
    metadata: dict[str, Any],
) -> None:
    """Write Parameter Lab CSV, JSON, and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = output_dir / "parameter_lab_inventory.csv"
    experiments_path = output_dir / "parameter_lab_experiments.csv"
    candidates_path = output_dir / "parameter_lab_candidate_universe.csv"
    json_path = output_dir / "parameter_lab.json"
    md_path = output_dir / "parameter_lab.md"

    inventory.to_csv(inventory_path, index=False)
    experiments.to_csv(experiments_path, index=False)
    candidates.to_csv(candidates_path, index=False)

    groups = evidence_groups(inventory)
    payload = {
        "metadata": metadata,
        "inventory": clean_records(inventory),
        "experiments": clean_records(experiments),
        "candidate_count": int(len(candidates)),
        "guardrail": (
            "Parameter Lab is research-only. Roy must explicitly approve every "
            "production threshold change. This report never changes live or paper behavior."
        ),
    }
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")

    inventory_columns = [
        "parameter_id",
        "current_value",
        "source",
        "confidence_level",
        "last_tested",
        "experiment_status",
    ]
    experiment_columns = [
        "parameter_id",
        "tested_value",
        "candidate_count",
        "win_rate",
        "average_r",
        "profit_factor",
        "max_drawdown_r",
        "average_mae_r",
        "average_mfe_r",
    ]
    recommended_rows = [
        {
            "experiment": "A/B check-score sweeps",
            "reason": "Exact check-score thresholds have weak isolated evidence.",
            "next_step": "Continue comparing candidate quality, R, MAE, and MFE over fresh sessions.",
        },
        {
            "experiment": "Quality-score threshold sweeps",
            "reason": "Quality-entry evidence is mixed by symbol.",
            "next_step": "Split by setup/symbol after enough candidate windows accumulate.",
        },
        {
            "experiment": "Options spread/liquidity thresholds",
            "reason": "Contract gates are execution-quality assumptions with no R evidence yet.",
            "next_step": "After contract audits exist, compare paper outcomes by spread, volume, and OI buckets.",
        },
    ]

    md_path.write_text(
        f"""# Parameter Lab

This is a research-only subsystem. It measures numeric engineering thresholds
without changing production behavior, paper trading, broker routing, alerts, or
Roy's original trading philosophy.

## Guardrails

- Never automatically modify production thresholds.
- Never modify the original trading philosophy.
- Only propose changes backed by statistical evidence.
- Roy must explicitly approve every production threshold change.

## Run Context

- Playbook: `{metadata.get("playbook", "")}`
- Lookback days: `{metadata.get("lookback_days", "")}`
- Candidate windows replayed: `{len(candidates)}`
- Replay start: `{metadata.get("lookback_start", "")}`
- Replay end: `{metadata.get("lookback_end", "")}`

## 1. Parameter Inventory

{markdown_table(table_records(inventory, inventory_columns), inventory_columns)}
## 2. Parameters With Strong Evidence

{markdown_table(table_records(groups["strong"], inventory_columns), inventory_columns)}
## 3. Parameters With Weak Evidence

{markdown_table(table_records(groups["weak"], inventory_columns), inventory_columns)}
## 4. Parameters Never Independently Validated

{markdown_table(table_records(groups["never"], inventory_columns), inventory_columns)}
## Isolated Experiment Results

{markdown_table(table_records(experiments, experiment_columns), experiment_columns)}
## 5. Recommended Future Experiments

{markdown_table(recommended_rows, ["experiment", "reason", "next_step"])}
## Files

```text
logs/parameter_lab_inventory.csv
logs/parameter_lab_candidate_universe.csv
logs/parameter_lab_experiments.csv
logs/parameter_lab.json
logs/parameter_lab.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    inventory = parameter_inventory()
    metadata: dict[str, Any] = {
        "playbook": args.playbook,
        "lookback_days": args.lookback_days,
        "inventory_only": args.inventory_only,
    }
    candidates = pd.DataFrame()
    experiments = pd.DataFrame()

    if not args.inventory_only:
        candidates, metadata = build_candidate_universe(
            data_dir=args.data_dir,
            playbook=args.playbook,
            lookback_days=args.lookback_days,
            market_regime_symbol=args.market_regime_symbol,
        )
        selected = args.parameter or DEFAULT_EXPERIMENTS
        rows = []
        for parameter_id in selected:
            values = args.values if args.values and len(selected) == 1 else None
            rows.append(run_threshold_experiment(candidates, parameter_id, values))
        experiments = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

    write_outputs(
        output_dir=args.output_dir,
        inventory=inventory,
        experiments=experiments,
        candidates=candidates,
        metadata=metadata,
    )
    print(f"Saved Parameter Lab report: {args.output_dir / 'parameter_lab.md'}")
    print(f"Inventory parameters: {len(inventory)}")
    print(f"Candidate windows replayed: {len(candidates)}")
    print(f"Experiment rows: {len(experiments)}")


if __name__ == "__main__":
    main()
