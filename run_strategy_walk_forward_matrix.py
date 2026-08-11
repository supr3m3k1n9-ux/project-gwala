"""Build walk-forward reviews for research strategy backtests.

This report checks whether newer historical trades still support older samples
for Strategy Vault families that already have first-pass backtests. It is
research-only and does not create scanner candidates, append observations,
import paper trades, place orders, create broker alerts, or enable execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table


STRATEGIES = [
    {
        "strategy_id": "gap_fill_fade",
        "name": "Gap Fill / Gap Fade",
        "stem": "gap_fill_fade",
    },
    {
        "strategy_id": "opening_range_failure",
        "name": "Opening Range Failure",
        "stem": "opening_range_failure",
    },
    {
        "strategy_id": "opening_range_breakout",
        "name": "Opening Range Breakout",
        "stem": "opening_range_breakout",
    },
    {
        "strategy_id": "trend_pullback_continuation",
        "name": "Trend Pullback Continuation",
        "stem": "trend_pullback_continuation",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build strategy walk-forward matrix.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--min-half-trades", type=int, default=4, help="Minimum trades required in each half.")
    parser.add_argument("--min-newer-expectancy-r", type=float, default=0.10, help="Minimum newer-half expectancy.")
    parser.add_argument("--min-newer-profit-factor", type=float, default=1.20, help="Minimum newer-half profit factor.")
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
    """Return finite numbers so JSON/dashboard consumers do not receive inf."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def clean_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Return trades sorted chronologically with usable numeric R results."""

    if trades.empty or "entry_time" not in trades.columns or "r_result" not in trades.columns:
        return pd.DataFrame()
    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True, errors="coerce")
    result["r_result"] = pd.to_numeric(result["r_result"], errors="coerce")
    result = result.dropna(subset=["entry_time", "r_result"]).sort_values("entry_time")
    return result.reset_index(drop=True)


def score_slice(label: str, trades: pd.DataFrame) -> dict[str, Any]:
    """Score one chronological slice."""

    metrics = calculate_metrics(trades)
    return {
        f"{label}_trades": int(metrics["trades"]),
        f"{label}_win_rate": float(metrics["win_rate"]),
        f"{label}_expectancy_r": float(metrics["expectancy_r"]),
        f"{label}_profit_factor": finite_number(metrics["profit_factor"]),
        f"{label}_max_drawdown_r": float(metrics["max_drawdown_r"]),
    }


def walk_forward_decision(first: dict[str, Any], second: dict[str, Any], args: argparse.Namespace) -> tuple[str, str]:
    """Label whether the newer half supports the older half."""

    if first["older_trades"] < args.min_half_trades or second["newer_trades"] < args.min_half_trades:
        return "needs_more_sample", f"Each half needs at least {args.min_half_trades} trades."
    if second["newer_expectancy_r"] >= args.min_newer_expectancy_r and second["newer_profit_factor"] >= args.min_newer_profit_factor:
        return "holding_up", "Newer half stayed above the early durability floor."
    if first["older_expectancy_r"] > 0 and second["newer_expectancy_r"] <= 0:
        return "fading", "Older half was positive, but newer half is flat or negative."
    if first["older_expectancy_r"] <= 0 and second["newer_expectancy_r"] > 0:
        return "improving_recently", "Newer half improved after a weak older half."
    if second["newer_expectancy_r"] > 0:
        return "mixed", "Newer half is positive but below the stronger durability floor."
    return "weak", "Newer half does not show enough edge yet."


def candidate_summary_rows(summary: pd.DataFrame) -> pd.DataFrame:
    """Return summary rows worth walk-forward review."""

    if summary.empty:
        return pd.DataFrame()
    if "research_status" not in summary.columns or "tightened_review" not in summary.columns:
        return pd.DataFrame()
    return summary[
        summary["research_status"].isin(["promising", "watch_more"])
        | (summary["tightened_review"] == "passes_tightened_research")
    ].copy()


def trade_subset(trades: pd.DataFrame, symbol: str, direction: str) -> pd.DataFrame:
    """Return the trade subset for a symbol and direction summary row."""

    if trades.empty or "symbol" not in trades.columns or "direction" not in trades.columns:
        return pd.DataFrame()
    result = trades[trades["symbol"].astype(str) == symbol].copy()
    if direction != "combined":
        result = result[result["direction"].astype(str) == direction].copy()
    return result


def review_row(strategy: dict[str, str], summary_row: pd.Series, trades: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    """Build one walk-forward row."""

    symbol = str(summary_row.get("symbol", ""))
    direction = str(summary_row.get("direction", ""))
    subset = clean_trades(trade_subset(trades, symbol, direction))
    if subset.empty:
        empty = score_slice("older", pd.DataFrame())
        empty.update(score_slice("newer", pd.DataFrame()))
        return {
            "strategy_id": strategy["strategy_id"],
            "strategy": strategy["name"],
            "decision": "missing_trade_log",
            "symbol": symbol,
            "direction": direction,
            "research_status": str(summary_row.get("research_status", "")),
            "tightened_review": str(summary_row.get("tightened_review", "")),
            "full_trades": 0,
            "full_expectancy_r": 0.0,
            **empty,
            "expectancy_delta_newer_vs_older": 0.0,
            "first_trade": "",
            "last_trade": "",
            "reason": "Trade log was missing or empty.",
        }

    midpoint = len(subset) // 2
    older = subset.iloc[:midpoint].copy()
    newer = subset.iloc[midpoint:].copy()
    older_score = score_slice("older", older)
    newer_score = score_slice("newer", newer)
    decision, reason = walk_forward_decision(older_score, newer_score, args)
    return {
        "strategy_id": strategy["strategy_id"],
        "strategy": strategy["name"],
        "decision": decision,
        "symbol": symbol,
        "direction": direction,
        "research_status": str(summary_row.get("research_status", "")),
        "tightened_review": str(summary_row.get("tightened_review", "")),
        "full_trades": int(len(subset)),
        "full_expectancy_r": float(pd.to_numeric(summary_row.get("expectancy_r", 0), errors="coerce") or 0.0),
        "full_profit_factor": finite_number(summary_row.get("profit_factor", 0)),
        "full_max_drawdown_r": float(pd.to_numeric(summary_row.get("max_drawdown_r", 0), errors="coerce") or 0.0),
        **older_score,
        **newer_score,
        "expectancy_delta_newer_vs_older": round(
            float(newer_score["newer_expectancy_r"]) - float(older_score["older_expectancy_r"]),
            4,
        ),
        "first_trade": subset["entry_time"].iloc[0].strftime("%Y-%m-%d"),
        "last_trade": subset["entry_time"].iloc[-1].strftime("%Y-%m-%d"),
        "reason": reason,
    }


def build_review_for_strategy(strategy: dict[str, str], output_dir: Path, args: argparse.Namespace) -> pd.DataFrame:
    """Build walk-forward rows for one strategy."""

    stem = strategy["stem"]
    summary = read_csv_or_empty(output_dir / f"{stem}_summary.csv")
    trades = read_csv_or_empty(output_dir / f"{stem}_trades.csv")
    candidates = candidate_summary_rows(summary)
    if candidates.empty:
        return pd.DataFrame()
    rows = [review_row(strategy, row, trades, args) for _, row in candidates.iterrows()]
    result = pd.DataFrame(rows)
    order = {
        "holding_up": 0,
        "improving_recently": 1,
        "mixed": 2,
        "needs_more_sample": 3,
        "fading": 4,
        "weak": 5,
        "missing_trade_log": 6,
    }
    result["_order"] = result["decision"].map(order).fillna(9)
    result = result.sort_values(
        ["_order", "newer_expectancy_r", "full_trades"],
        ascending=[True, False, False],
    )
    return result.drop(columns=["_order"]).reset_index(drop=True)


def write_individual_outputs(strategy: dict[str, str], output_dir: Path, review: pd.DataFrame, args: argparse.Namespace) -> None:
    """Write per-strategy walk-forward files used by coverage reports."""

    stem = strategy["stem"]
    csv_path = output_dir / f"{stem}_walk_forward.csv"
    json_path = output_dir / f"{stem}_walk_forward.json"
    md_path = output_dir / f"{stem}_walk_forward.md"
    review.to_csv(csv_path, index=False)
    counts = review.groupby("decision").size().reset_index(name="rows") if not review.empty else pd.DataFrame()
    holding = review[review["decision"] == "holding_up"].copy() if not review.empty else pd.DataFrame()
    payload = {
        "strategy_id": strategy["strategy_id"],
        "strategy": strategy["name"],
        "review_type": "walk_forward",
        "min_half_trades": args.min_half_trades,
        "min_newer_expectancy_r": args.min_newer_expectancy_r,
        "min_newer_profit_factor": args.min_newer_profit_factor,
        "review_rows": int(len(review)),
        "holding_up_rows": int(len(holding)),
        "decision_counts": counts.to_dict("records") if not counts.empty else [],
        "guardrail": "Research/backtesting only. Does not approve paper trades or alter scanner gates.",
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(
        f"""# {strategy["name"]} Walk-Forward Review

This report checks whether newer historical trades still support the older
sample for this Strategy Vault family.

Important: this is research/backtesting only. It does not create scanner
candidates, import paper trades, place broker orders, create broker alerts, or
bypass the paper gate.

## Summary

```text
Review rows: {payload["review_rows"]}
Holding-up rows: {payload["holding_up_rows"]}
Minimum half trades: {args.min_half_trades}
Minimum newer expectancy: {args.min_newer_expectancy_r:.2f}R
Minimum newer profit factor: {args.min_newer_profit_factor:.2f}
```

## Decision Counts

{markdown_table(counts)}

## Walk-Forward Rows

{markdown_table(review)}

## Files

```text
{json_path}
{csv_path}
{md_path}
```
""",
        encoding="utf-8",
    )


def build_payload(output_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build and write all per-strategy reviews."""

    frames = []
    summary_rows = []
    for strategy in STRATEGIES:
        review = build_review_for_strategy(strategy, output_dir, args)
        write_individual_outputs(strategy, output_dir, review, args)
        if not review.empty:
            frames.append(review)
        summary_rows.append(
            {
                "strategy_id": strategy["strategy_id"],
                "strategy": strategy["name"],
                "review_rows": int(len(review)),
                "holding_up_rows": int((review["decision"] == "holding_up").sum()) if not review.empty else 0,
                "needs_more_sample_rows": int((review["decision"] == "needs_more_sample").sum()) if not review.empty else 0,
                "weak_or_fading_rows": int(review["decision"].isin(["weak", "fading"]).sum()) if not review.empty else 0,
                "next_action": "Use holding-up rows for deeper evidence lanes." if not review.empty and (review["decision"] == "holding_up").any() else "Keep in research; needs more durable walk-forward evidence.",
            }
        )
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    summary = pd.DataFrame(summary_rows)
    payload = {
        "status": "complete",
        "strategy_count": len(STRATEGIES),
        "review_rows": int(len(combined)),
        "holding_up_rows": int((combined["decision"] == "holding_up").sum()) if not combined.empty else 0,
        "summary": summary_rows,
        "guardrail": "Research/backtesting only. Does not approve paper trades or alter scanner gates.",
    }
    return payload, combined


def write_matrix_outputs(output_dir: Path, payload: dict[str, Any], combined: pd.DataFrame) -> None:
    """Write combined walk-forward matrix files."""

    json_path = output_dir / "strategy_walk_forward_matrix.json"
    csv_path = output_dir / "strategy_walk_forward_matrix.csv"
    md_path = output_dir / "strategy_walk_forward_matrix.md"
    summary = pd.DataFrame(payload["summary"])
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    combined.to_csv(csv_path, index=False)
    md_path.write_text(
        f"""# Strategy Walk-Forward Matrix

This report builds walk-forward reviews for Strategy Vault families that have
first-pass backtest trade logs but do not yet have deeper evidence lanes.

Important: this is research/backtesting only. It does not create scanner
candidates, import paper trades, place broker orders, create broker alerts, or
bypass the paper gate.

## Summary

```text
Strategies reviewed: {payload["strategy_count"]}
Review rows: {payload["review_rows"]}
Holding-up rows: {payload["holding_up_rows"]}
```

## Strategy Summary

{markdown_table(summary)}

## Combined Walk-Forward Rows

{markdown_table(combined)}

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
    payload, combined = build_payload(args.output_dir, args)
    write_matrix_outputs(args.output_dir, payload, combined)
    print(f"Strategy walk-forward status: {payload['status']}")
    print(f"Review rows: {payload['review_rows']}")
    print(f"Holding-up rows: {payload['holding_up_rows']}")
    print(f"Saved strategy walk-forward matrix: {args.output_dir / 'strategy_walk_forward_matrix.md'}")


if __name__ == "__main__":
    main()
