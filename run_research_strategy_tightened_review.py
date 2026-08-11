"""Build tightened reviews for research Strategy Vault seed families.

This report reviews first-pass summary rows against walk-forward evidence so
newer Strategy Vault ideas do not stay stuck at a vague "tighten filters"
status. It is research-only. It does not create scanner candidates, append live
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


STRATEGIES = [
    {
        "strategy_id": "gap_fill_fade",
        "name": "Gap Fill / Gap Fade",
        "stem": "gap_fill_fade",
    },
    {
        "strategy_id": "opening_range_breakout",
        "name": "Opening Range Breakout",
        "stem": "opening_range_breakout",
    },
    {
        "strategy_id": "opening_range_failure",
        "name": "Opening Range Failure",
        "stem": "opening_range_failure",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build research strategy tightened reviews.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--min-final-trades", type=int, default=10, help="Trades needed for a final tightened pass.")
    parser.add_argument("--min-provisional-trades", type=int, default=5, help="Trades needed for provisional lane-building.")
    parser.add_argument("--min-expectancy-r", type=float, default=0.10)
    parser.add_argument("--min-profit-factor", type=float, default=1.30)
    parser.add_argument("--max-drawdown-r", type=float, default=-3.0)
    parser.add_argument(
        "--provisional-expectancy-buffer-r",
        type=float,
        default=0.02,
        help="Small expectancy cushion so near-threshold rows can keep collecting evidence.",
    )
    parser.add_argument(
        "--provisional-profit-factor-buffer",
        type=float,
        default=0.05,
        help="Small PF cushion so near-threshold rows can keep collecting evidence.",
    )
    parser.add_argument("--min-seed-trades", type=int, default=2, help="Tiny positive rows allowed into shadow-only seed collection.")
    parser.add_argument("--min-seed-expectancy-r", type=float, default=0.20)
    parser.add_argument("--min-seed-profit-factor", type=float, default=1.50)
    parser.add_argument("--min-seed-newer-expectancy-r", type=float, default=0.10)
    parser.add_argument("--min-seed-newer-profit-factor", type=float, default=1.20)
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


def matching_walk_forward(summary_row: pd.Series, walk_forward: pd.DataFrame) -> pd.Series | None:
    """Return the walk-forward row matching symbol and direction."""

    required = {"symbol", "direction"}
    if walk_forward.empty or not required.issubset(walk_forward.columns):
        return None
    matches = walk_forward[
        (walk_forward["symbol"].astype(str) == str(summary_row.get("symbol", "")))
        & (walk_forward["direction"].astype(str) == str(summary_row.get("direction", "")))
    ].copy()
    if matches.empty:
        return None
    return matches.iloc[0]


def candidate_rows(summary: pd.DataFrame) -> pd.DataFrame:
    """Return summary rows worth tightened review."""

    if summary.empty or "research_status" not in summary.columns:
        return pd.DataFrame()
    return summary[
        summary["research_status"].isin(["promising", "watch_more"])
        | (summary.get("tightened_review", pd.Series(index=summary.index, dtype=str)) == "passes_tightened_research")
    ].copy()


def review_row(strategy: dict[str, str], row: pd.Series, walk_forward: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    """Build one tightened-review decision row."""

    trades = int(finite_number(row.get("trades", 0)))
    expectancy = finite_number(row.get("expectancy_r", 0))
    profit_factor = finite_number(row.get("profit_factor", 0))
    max_drawdown = finite_number(row.get("max_drawdown_r", 0))
    walk = matching_walk_forward(row, walk_forward)
    walk_decision = str(walk.get("decision", "missing")) if walk is not None else "missing"
    newer_expectancy = finite_number(walk.get("newer_expectancy_r", 0)) if walk is not None else 0.0
    newer_profit_factor = finite_number(walk.get("newer_profit_factor", 0)) if walk is not None else 0.0

    final_blockers = []
    if trades < args.min_final_trades:
        final_blockers.append(f"needs {args.min_final_trades - trades} more trades for final pass")
    if expectancy < args.min_expectancy_r:
        final_blockers.append(f"expectancy below {args.min_expectancy_r:.2f}R")
    if profit_factor < args.min_profit_factor:
        final_blockers.append(f"profit factor below {args.min_profit_factor:.2f}")
    if max_drawdown < args.max_drawdown_r:
        final_blockers.append(f"drawdown worse than {args.max_drawdown_r:.1f}R")
    if walk_decision != "holding_up":
        final_blockers.append("walk-forward is not holding up")

    provisional_floor_r = args.min_expectancy_r - args.provisional_expectancy_buffer_r
    provisional_floor_pf = args.min_profit_factor - args.provisional_profit_factor_buffer
    provisional_blockers = []
    if trades < args.min_provisional_trades:
        provisional_blockers.append(f"needs {args.min_provisional_trades - trades} more trades for provisional review")
    if expectancy < provisional_floor_r:
        provisional_blockers.append(f"expectancy below provisional floor {provisional_floor_r:.2f}R")
    if profit_factor < provisional_floor_pf:
        provisional_blockers.append(f"profit factor below provisional floor {provisional_floor_pf:.2f}")
    if max_drawdown < args.max_drawdown_r:
        provisional_blockers.append(f"drawdown worse than {args.max_drawdown_r:.1f}R")
    if walk_decision in {"fading", "weak", "missing_trade_log", "missing"}:
        provisional_blockers.append("walk-forward is weak, fading, or missing")

    seed_blockers = []
    min_seed_trades = int(getattr(args, "min_seed_trades", 2))
    min_seed_expectancy = float(getattr(args, "min_seed_expectancy_r", 0.20))
    min_seed_profit_factor = float(getattr(args, "min_seed_profit_factor", 1.50))
    min_seed_newer_expectancy = float(getattr(args, "min_seed_newer_expectancy_r", 0.10))
    min_seed_newer_profit_factor = float(getattr(args, "min_seed_newer_profit_factor", 1.20))
    if trades < min_seed_trades:
        seed_blockers.append(f"needs {min_seed_trades - trades} more trades for seed review")
    if expectancy < min_seed_expectancy:
        seed_blockers.append(f"expectancy below seed floor {min_seed_expectancy:.2f}R")
    if profit_factor < min_seed_profit_factor:
        seed_blockers.append(f"profit factor below seed floor {min_seed_profit_factor:.2f}")
    if max_drawdown < args.max_drawdown_r:
        seed_blockers.append(f"drawdown worse than {args.max_drawdown_r:.1f}R")
    if walk_decision in {"fading", "weak", "missing_trade_log", "missing"}:
        seed_blockers.append("walk-forward is weak, fading, or missing")
    if walk is not None and walk_decision == "needs_more_sample":
        if newer_expectancy < min_seed_newer_expectancy:
            seed_blockers.append(f"newer expectancy below seed floor {min_seed_newer_expectancy:.2f}R")
        if newer_profit_factor < min_seed_newer_profit_factor:
            seed_blockers.append(f"newer profit factor below seed floor {min_seed_newer_profit_factor:.2f}")

    if not final_blockers:
        decision = "passes_tightened_research"
        blockers = []
        next_action = "Eligible for shadow and forward evidence lanes; still blocked from paper-watch until activation rules pass."
    elif not provisional_blockers:
        decision = "provisional_tightened_pass"
        blockers = final_blockers
        next_action = "Keep collecting shadow/forward evidence, but do not promote to paper-watch yet."
    elif not seed_blockers:
        decision = "seed_shadow_candidate"
        blockers = final_blockers
        next_action = "Collect shadow/forward evidence only; this seed is not a paper-watch approval."
    else:
        decision = "needs_more_evidence"
        blockers = provisional_blockers
        next_action = "Keep in research and collect more historical/live observations before promotion review."

    return {
        "strategy_id": strategy["strategy_id"],
        "strategy": strategy["name"],
        "symbol": str(row.get("symbol", "")),
        "direction": str(row.get("direction", "")),
        "decision": decision,
        "research_status": str(row.get("research_status", "")),
        "first_pass_review": str(row.get("tightened_review", "")),
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


def build_review_for_strategy(
    strategy: dict[str, str],
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build one strategy tightened-review payload and table."""

    stem = strategy["stem"]
    summary = read_csv_or_empty(output_dir / f"{stem}_summary.csv")
    walk_forward = read_csv_or_empty(output_dir / f"{stem}_walk_forward.csv")
    candidates = candidate_rows(summary)
    rows = pd.DataFrame([review_row(strategy, row, walk_forward, args) for _, row in candidates.iterrows()])
    if not rows.empty:
        order = {"passes_tightened_research": 0, "provisional_tightened_pass": 1, "needs_more_evidence": 2}
        rows["_order"] = rows["decision"].map(order).fillna(9)
        rows = rows.sort_values(["_order", "expectancy_r", "trades"], ascending=[True, False, False])
        rows = rows.drop(columns=["_order"]).reset_index(drop=True)

    final = rows[rows["decision"] == "passes_tightened_research"].copy() if not rows.empty else pd.DataFrame()
    provisional = (
        rows[rows["decision"].isin(["provisional_tightened_pass", "seed_shadow_candidate"])].copy()
        if not rows.empty
        else pd.DataFrame()
    )
    payload = {
        "strategy_id": strategy["strategy_id"],
        "strategy": strategy["name"],
        "status": "complete" if not rows.empty else "missing_candidates",
        "review_rows": int(len(rows)),
        "final_pass_rows": int(len(final)),
        "provisional_pass_rows": int(len(provisional)),
        "min_final_trades": args.min_final_trades,
        "min_provisional_trades": args.min_provisional_trades,
        "min_expectancy_r": args.min_expectancy_r,
        "min_profit_factor": args.min_profit_factor,
        "max_drawdown_r": args.max_drawdown_r,
        "next_action": (
            "Continue shadow/forward evidence lanes for provisional or final pass rows."
            if not final.empty or not provisional.empty
            else "Keep in research; do not advance this strategy until evidence quality improves."
        ),
        "guardrail": (
            "Research-only tightened review. It does not approve paper-watch, create scanner candidates, "
            "place orders, create broker alerts, import paper trades, or enable execution."
        ),
        "rows": rows.to_dict("records") if not rows.empty else [],
    }
    return payload, rows


def write_strategy_outputs(output_dir: Path, payload: dict[str, Any], rows: pd.DataFrame) -> None:
    """Write per-strategy JSON, CSV, and Markdown tightened-review files."""

    stem = str(payload["strategy_id"])
    json_path = output_dir / f"{stem}_tightened_review.json"
    csv_path = output_dir / f"{stem}_tightened_review.csv"
    md_path = output_dir / f"{stem}_tightened_review.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# {payload["strategy"]} Tightened Review

This report checks whether first-pass backtest rows are strong enough to keep
building shadow and forward evidence lanes.

Important: this is research-only. It does not approve paper-watch status,
create scanner candidates, import paper trades, place broker orders, create
broker alerts, or enable execution.

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


def build_all_reviews(output_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build tightened reviews for all configured seed strategies."""

    payloads = []
    frames = []
    for strategy in STRATEGIES:
        payload, rows = build_review_for_strategy(strategy, output_dir, args)
        write_strategy_outputs(output_dir, payload, rows)
        payloads.append(payload)
        if not rows.empty:
            frames.append(rows)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    final_pass_rows = int(sum(payload["final_pass_rows"] for payload in payloads))
    provisional_pass_rows = int(sum(payload["provisional_pass_rows"] for payload in payloads))
    payload = {
        "status": "complete",
        "strategy_count": len(payloads),
        "review_rows": int(len(combined)),
        "final_pass_rows": final_pass_rows,
        "provisional_pass_rows": provisional_pass_rows,
        "strategies": payloads,
        "guardrail": "Research-only. No orders, alerts, paper imports, or execution.",
    }
    return payload, combined


def write_combined_outputs(output_dir: Path, payload: dict[str, Any], rows: pd.DataFrame) -> None:
    """Write combined tightened-review matrix files."""

    json_path = output_dir / "research_strategy_tightened_review.json"
    csv_path = output_dir / "research_strategy_tightened_review.csv"
    md_path = output_dir / "research_strategy_tightened_review.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Research Strategy Tightened Review Matrix

This report summarizes tightened-review decisions for seed Strategy Vault
families that are still research-only.

Important: this does not approve paper-watch status, create scanner candidates,
import paper trades, place broker orders, create broker alerts, or enable
execution.

## Summary

```text
Status: {payload["status"]}
Strategies reviewed: {payload["strategy_count"]}
Review rows: {payload["review_rows"]}
Final tightened pass rows: {payload["final_pass_rows"]}
Provisional tightened pass rows: {payload["provisional_pass_rows"]}
```

## Matrix

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
    payload, rows = build_all_reviews(args.output_dir, args)
    write_combined_outputs(args.output_dir, payload, rows)
    print(f"Research tightened reviews complete: {payload['review_rows']} rows")
    print(f"Final pass rows: {payload['final_pass_rows']}")
    print(f"Provisional pass rows: {payload['provisional_pass_rows']}")


if __name__ == "__main__":
    main()
