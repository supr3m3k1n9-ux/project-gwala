"""Build the Trend Pullback provisional tightened review.

This report decides whether Trend Pullback Continuation has enough historical
and walk-forward evidence to justify shadow/forward evidence lanes. It does not
approve paper-watch status, create scanner candidates, import paper trades,
place orders, create broker alerts, or enable execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Trend Pullback tightened review.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--min-final-trades", type=int, default=10, help="Trades required for a final tightened pass.")
    parser.add_argument("--min-provisional-trades", type=int, default=8, help="Trades required for provisional lane-building.")
    parser.add_argument("--min-expectancy-r", type=float, default=0.10)
    parser.add_argument("--min-profit-factor", type=float, default=1.30)
    parser.add_argument("--max-drawdown-r", type=float, default=-3.0)
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
    """Return finite numeric values for comparisons."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def review_row(row: pd.Series, walk_forward: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    """Return one tightened review row."""

    symbol = str(row.get("symbol", ""))
    direction = str(row.get("direction", ""))
    trades = int(finite_number(row.get("trades", 0)))
    expectancy = finite_number(row.get("expectancy_r", 0))
    profit_factor = finite_number(row.get("profit_factor", 0))
    max_drawdown = finite_number(row.get("max_drawdown_r", 0))
    matching_walk = walk_forward[
        (walk_forward["symbol"].astype(str) == symbol)
        & (walk_forward["direction"].astype(str) == direction)
    ].copy() if not walk_forward.empty and {"symbol", "direction"}.issubset(walk_forward.columns) else pd.DataFrame()
    walk_decision = str(matching_walk.iloc[0]["decision"]) if not matching_walk.empty and "decision" in matching_walk.columns else "missing"
    newer_expectancy = finite_number(matching_walk.iloc[0].get("newer_expectancy_r", 0)) if not matching_walk.empty else 0.0
    newer_profit_factor = finite_number(matching_walk.iloc[0].get("newer_profit_factor", 0)) if not matching_walk.empty else 0.0

    blockers = []
    if expectancy < args.min_expectancy_r:
        blockers.append(f"expectancy below {args.min_expectancy_r:.2f}R")
    if profit_factor < args.min_profit_factor:
        blockers.append(f"profit factor below {args.min_profit_factor:.2f}")
    if max_drawdown < args.max_drawdown_r:
        blockers.append(f"drawdown worse than {args.max_drawdown_r:.1f}R")
    if walk_decision != "holding_up":
        blockers.append("walk-forward is not holding up")

    if trades >= args.min_final_trades and not blockers:
        decision = "passes_tightened_research"
        next_action = "Eligible for strategy-specific evidence lanes; still not paper-watch approved."
    elif trades >= args.min_provisional_trades and not blockers:
        decision = "provisional_tightened_pass"
        next_action = "Build shadow/forward lanes, but keep paper-watch blocked until more historical and forward evidence matures."
    else:
        if trades < args.min_provisional_trades:
            blockers.append(f"needs {args.min_provisional_trades - trades} more trades for provisional review")
        decision = "not_ready"
        next_action = "Keep in research until historical sample and walk-forward quality improve."

    return {
        "strategy_id": "trend_pullback_continuation",
        "symbol": symbol,
        "direction": direction,
        "decision": decision,
        "trades": trades,
        "expectancy_r": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_drawdown,
        "walk_forward_decision": walk_decision,
        "newer_expectancy_r": newer_expectancy,
        "newer_profit_factor": newer_profit_factor,
        "blockers": "; ".join(blockers) if blockers else "None",
        "next_action": next_action,
    }


def build_review(output_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build the Trend Pullback tightened review payload and rows."""

    summary = read_csv_or_empty(output_dir / "trend_pullback_continuation_summary.csv")
    walk_forward = read_csv_or_empty(output_dir / "trend_pullback_continuation_walk_forward.csv")
    if summary.empty:
        rows = pd.DataFrame()
    else:
        candidates = summary[
            summary["research_status"].isin(["promising", "watch_more"])
            | (summary["tightened_review"] == "passes_tightened_research")
        ].copy() if {"research_status", "tightened_review"}.issubset(summary.columns) else pd.DataFrame()
        rows = pd.DataFrame(review_row(row, walk_forward, args) for _, row in candidates.iterrows())

    provisional = rows[rows["decision"] == "provisional_tightened_pass"].copy() if not rows.empty else pd.DataFrame()
    final = rows[rows["decision"] == "passes_tightened_research"].copy() if not rows.empty else pd.DataFrame()
    payload = {
        "strategy_id": "trend_pullback_continuation",
        "status": "complete" if not rows.empty else "missing_candidates",
        "review_rows": int(len(rows)),
        "final_pass_rows": int(len(final)),
        "provisional_pass_rows": int(len(provisional)),
        "next_action": (
            "Build Trend Pullback shadow/forward lanes for provisional pass rows."
            if not provisional.empty or not final.empty
            else "Keep Trend Pullback in research until tightened criteria improve."
        ),
        "guardrail": (
            "This review only decides whether to build evidence lanes. It does not approve paper-watch, "
            "place orders, create broker alerts, import paper trades, or enable execution."
        ),
        "rows": rows.to_dict("records") if not rows.empty else [],
    }
    return payload, rows


def write_outputs(output_dir: Path, payload: dict[str, Any], rows: pd.DataFrame) -> None:
    """Write JSON, CSV, and Markdown reports."""

    json_path = output_dir / "trend_pullback_continuation_tightened_review.json"
    csv_path = output_dir / "trend_pullback_continuation_tightened_review.csv"
    md_path = output_dir / "trend_pullback_continuation_tightened_review.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Trend Pullback Continuation Tightened Review

This report checks whether Trend Pullback Continuation is strong enough to
justify building strategy-specific shadow and forward evidence lanes.

Important: this does not approve paper-watch status, create scanner candidates,
import paper trades, place broker orders, create broker alerts, or enable
execution.

## Summary

```text
Status: {payload["status"]}
Review rows: {payload["review_rows"]}
Final tightened pass rows: {payload["final_pass_rows"]}
Provisional tightened pass rows: {payload["provisional_pass_rows"]}
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
    print(f"Trend Pullback tightened status: {payload['status']}")
    print(f"Final pass rows: {payload['final_pass_rows']}")
    print(f"Provisional pass rows: {payload['provisional_pass_rows']}")
    print(f"Saved Trend Pullback tightened review: {args.output_dir / 'trend_pullback_continuation_tightened_review.md'}")


if __name__ == "__main__":
    main()
