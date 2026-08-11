"""Deepen Opening Range Breakout walk-forward review.

This report decides whether Opening Range Breakout deserves more evidence
collection or should be deprioritized after newer historical slices weaken.

It is research-only. It does not create scanner candidates, append live
samples, import paper trades, place orders, create broker alerts, or enable
execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deepen Opening Range Breakout walk-forward review.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--min-final-half-trades", type=int, default=4)
    parser.add_argument("--min-provisional-full-trades", type=int, default=5)
    parser.add_argument("--min-newer-expectancy-r", type=float, default=0.08)
    parser.add_argument("--min-newer-profit-factor", type=float, default=1.20)
    parser.add_argument("--max-full-drawdown-r", type=float, default=-3.0)
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and has rows."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def finite_number(value: Any) -> float:
    """Return finite numeric values for comparisons and JSON."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def tightened_by_key(tightened: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Return tightened-review decisions keyed by symbol/direction."""

    if tightened.empty or not {"symbol", "direction", "decision"}.issubset(tightened.columns):
        return {}
    return {
        (str(row["symbol"]), str(row["direction"])): str(row["decision"])
        for _, row in tightened.iterrows()
    }


def deepening_row(row: pd.Series, tightened_decisions: dict[tuple[str, str], str], args: argparse.Namespace) -> dict[str, Any]:
    """Return one OR Breakout durability decision row."""

    symbol = str(row.get("symbol", ""))
    direction = str(row.get("direction", ""))
    tightened_decision = tightened_decisions.get((symbol, direction), "missing")
    generic_decision = str(row.get("decision", ""))
    full_trades = int(finite_number(row.get("full_trades", 0)))
    older_trades = int(finite_number(row.get("older_trades", 0)))
    newer_trades = int(finite_number(row.get("newer_trades", 0)))
    full_expectancy = finite_number(row.get("full_expectancy_r", 0))
    full_profit_factor = finite_number(row.get("full_profit_factor", 0))
    full_drawdown = finite_number(row.get("full_max_drawdown_r", 0))
    older_expectancy = finite_number(row.get("older_expectancy_r", 0))
    newer_expectancy = finite_number(row.get("newer_expectancy_r", 0))
    newer_profit_factor = finite_number(row.get("newer_profit_factor", 0))

    final_blockers = []
    if older_trades < args.min_final_half_trades:
        final_blockers.append(f"older half needs {args.min_final_half_trades - older_trades} more trade(s)")
    if newer_trades < args.min_final_half_trades:
        final_blockers.append(f"newer half needs {args.min_final_half_trades - newer_trades} more trade(s)")
    if newer_expectancy < args.min_newer_expectancy_r:
        final_blockers.append(f"newer expectancy below {args.min_newer_expectancy_r:.2f}R")
    if newer_profit_factor < args.min_newer_profit_factor:
        final_blockers.append(f"newer PF below {args.min_newer_profit_factor:.2f}")
    if full_drawdown < args.max_full_drawdown_r:
        final_blockers.append(f"full drawdown worse than {args.max_full_drawdown_r:.1f}R")
    if tightened_decision not in {"passes_tightened_research", "provisional_tightened_pass"}:
        final_blockers.append("tightened review is not provisional/final pass")

    provisional_blockers = []
    if full_trades < args.min_provisional_full_trades:
        provisional_blockers.append(f"needs {args.min_provisional_full_trades - full_trades} more full-sample trade(s)")
    if newer_trades < 1:
        provisional_blockers.append("needs at least one newer-half trade")
    if newer_expectancy < args.min_newer_expectancy_r:
        provisional_blockers.append(f"newer expectancy below {args.min_newer_expectancy_r:.2f}R")
    if newer_profit_factor < args.min_newer_profit_factor:
        provisional_blockers.append(f"newer PF below {args.min_newer_profit_factor:.2f}")
    if full_expectancy < args.min_newer_expectancy_r:
        provisional_blockers.append(f"full expectancy below {args.min_newer_expectancy_r:.2f}R")
    if full_profit_factor < args.min_newer_profit_factor:
        provisional_blockers.append(f"full PF below {args.min_newer_profit_factor:.2f}")
    if full_drawdown < args.max_full_drawdown_r:
        provisional_blockers.append(f"full drawdown worse than {args.max_full_drawdown_r:.1f}R")
    if generic_decision in {"fading", "weak"}:
        provisional_blockers.append("generic walk-forward is fading or weak")
    if tightened_decision not in {"passes_tightened_research", "provisional_tightened_pass"}:
        provisional_blockers.append("tightened review is not provisional/final pass")

    if not final_blockers:
        decision = "walk_forward_pass"
        blockers = []
        next_action = "Eligible to continue shadow/forward evidence collection; still not paper-watch approved."
    elif not provisional_blockers:
        decision = "provisional_walk_forward_pass"
        blockers = final_blockers
        next_action = "Collect OR Breakout shadow/forward samples, then re-run this review after more trades mature."
    else:
        decision = "deprioritize_or_wait"
        blockers = provisional_blockers
        next_action = "Deprioritize OR Breakout until newer-slice expectancy and PF improve."

    return {
        "strategy_id": "opening_range_breakout",
        "strategy": "Opening Range Breakout",
        "symbol": symbol,
        "direction": direction,
        "decision": decision,
        "generic_walk_forward_decision": generic_decision,
        "tightened_decision": tightened_decision,
        "full_trades": full_trades,
        "older_trades": older_trades,
        "newer_trades": newer_trades,
        "full_expectancy_r": full_expectancy,
        "full_profit_factor": full_profit_factor,
        "full_max_drawdown_r": full_drawdown,
        "older_expectancy_r": older_expectancy,
        "newer_expectancy_r": newer_expectancy,
        "newer_profit_factor": newer_profit_factor,
        "expectancy_delta_newer_vs_older": finite_number(row.get("expectancy_delta_newer_vs_older", 0)),
        "sample_deficit_for_final": max(0, args.min_final_half_trades - older_trades)
        + max(0, args.min_final_half_trades - newer_trades),
        "blockers": "; ".join(blockers) if blockers else "None",
        "next_action": next_action,
    }


def build_review(output_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build Opening Range Breakout deep walk-forward review."""

    walk_forward = read_csv_or_empty(output_dir / "opening_range_breakout_walk_forward.csv")
    tightened = read_csv_or_empty(output_dir / "opening_range_breakout_tightened_review.csv")
    decisions = tightened_by_key(tightened)
    if walk_forward.empty:
        rows = pd.DataFrame()
    else:
        rows = pd.DataFrame(deepening_row(row, decisions, args) for _, row in walk_forward.iterrows())
        order = {"walk_forward_pass": 0, "provisional_walk_forward_pass": 1, "deprioritize_or_wait": 2}
        rows["_order"] = rows["decision"].map(order).fillna(9)
        rows = rows.sort_values(["_order", "newer_expectancy_r", "full_trades"], ascending=[True, False, False])
        rows = rows.drop(columns=["_order"]).reset_index(drop=True)

    final_pass = rows[rows["decision"] == "walk_forward_pass"].copy() if not rows.empty else pd.DataFrame()
    provisional = rows[rows["decision"] == "provisional_walk_forward_pass"].copy() if not rows.empty else pd.DataFrame()
    deprioritized = rows[rows["decision"] == "deprioritize_or_wait"].copy() if not rows.empty else pd.DataFrame()
    payload = {
        "strategy_id": "opening_range_breakout",
        "strategy": "Opening Range Breakout",
        "status": "complete" if not rows.empty else "missing_walk_forward",
        "review_rows": int(len(rows)),
        "walk_forward_pass_rows": int(len(final_pass)),
        "provisional_walk_forward_pass_rows": int(len(provisional)),
        "deprioritized_rows": int(len(deprioritized)),
        "next_action": (
            "Collect Opening Range Breakout shadow/forward evidence for provisional pass rows."
            if not final_pass.empty or not provisional.empty
            else "Deprioritize Opening Range Breakout until newer-slice evidence improves."
        ),
        "guardrail": (
            "Research-only walk-forward deepening. It does not approve paper-watch, create scanner candidates, "
            "place orders, create broker alerts, import paper trades, or enable execution."
        ),
        "rows": rows.to_dict("records") if not rows.empty else [],
    }
    return payload, rows


def write_outputs(output_dir: Path, payload: dict[str, Any], rows: pd.DataFrame) -> None:
    """Write JSON, CSV, and Markdown outputs."""

    json_path = output_dir / "opening_range_breakout_walk_forward_deepening.json"
    csv_path = output_dir / "opening_range_breakout_walk_forward_deepening.csv"
    md_path = output_dir / "opening_range_breakout_walk_forward_deepening.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Opening Range Breakout Walk-Forward Deepening

This report checks whether Opening Range Breakout has enough newer-slice
durability to keep collecting shadow and forward evidence.

Important: this is research-only. It does not approve paper-watch status,
create scanner candidates, import paper trades, place broker orders, create
broker alerts, or enable execution.

## Summary

```text
Status: {payload["status"]}
Review rows: {payload["review_rows"]}
Walk-forward pass rows: {payload["walk_forward_pass_rows"]}
Provisional walk-forward pass rows: {payload["provisional_walk_forward_pass_rows"]}
Deprioritized rows: {payload["deprioritized_rows"]}
Next action: {payload["next_action"]}
```

## Review Rows

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
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload, rows = build_review(args.output_dir, args)
    write_outputs(args.output_dir, payload, rows)
    print(f"Opening Range Breakout walk-forward deepening: {payload['status']}")
    print(f"Provisional pass rows: {payload['provisional_walk_forward_pass_rows']}")
    print(f"Deprioritized rows: {payload['deprioritized_rows']}")


if __name__ == "__main__":
    main()
