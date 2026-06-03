"""Walk-forward review for VWAP reclaim/reject research.

This report checks whether the newest VWAP reclaim/reject trades still support
the older backtest sample. It is research-only: it does not create scanner
candidates, paper trades, broker alerts, or execution instructions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build VWAP reclaim/reject walk-forward review.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--trade-log",
        type=Path,
        default=Path("logs/vwap_reclaim_reject_trades.csv"),
        help="Consolidated VWAP reclaim/reject trade log.",
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=Path("logs/vwap_reclaim_reject_summary.csv"),
        help="VWAP reclaim/reject summary rows to review.",
    )
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


def trade_subset(trades: pd.DataFrame, symbol: str, direction: str) -> pd.DataFrame:
    """Return the trade subset for a symbol and direction summary row."""

    result = trades[trades["symbol"].astype(str) == symbol].copy()
    if direction != "combined":
        result = result[result["direction"].astype(str) == direction].copy()
    return result


def review_row(summary_row: pd.Series, trades: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    """Build one walk-forward review row from a VWAP reclaim/reject summary row."""

    symbol = str(summary_row.get("symbol", ""))
    direction = str(summary_row.get("direction", ""))
    subset = clean_trades(trade_subset(trades, symbol, direction))
    if subset.empty:
        empty = score_slice("older", pd.DataFrame())
        empty.update(score_slice("newer", pd.DataFrame()))
        return {
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


def build_review(summary: pd.DataFrame, trades: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """Build walk-forward rows for useful VWAP reclaim/reject summary rows."""

    if summary.empty or trades.empty:
        return pd.DataFrame()
    candidates = summary[
        summary["research_status"].isin(["promising", "watch_more"])
        | (summary["tightened_review"] == "passes_tightened_research")
    ].copy()
    if candidates.empty:
        return pd.DataFrame()

    rows = [review_row(row, trades, args) for _, row in candidates.iterrows()]
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


def write_outputs(output_dir: Path, review: pd.DataFrame, args: argparse.Namespace) -> None:
    """Write JSON, CSV, and Markdown reports."""

    csv_path = output_dir / "vwap_reclaim_reject_walk_forward.csv"
    json_path = output_dir / "vwap_reclaim_reject_walk_forward.json"
    md_path = output_dir / "vwap_reclaim_reject_walk_forward.md"
    review.to_csv(csv_path, index=False)

    counts = review.groupby("decision").size().reset_index(name="rows") if not review.empty else pd.DataFrame()
    holding = review[review["decision"] == "holding_up"].copy() if not review.empty else pd.DataFrame()
    fading = review[review["decision"] == "fading"].copy() if not review.empty else pd.DataFrame()
    payload = {
        "strategy_id": "vwap_reclaim_reject",
        "review_type": "walk_forward",
        "min_half_trades": args.min_half_trades,
        "min_newer_expectancy_r": args.min_newer_expectancy_r,
        "min_newer_profit_factor": args.min_newer_profit_factor,
        "review_rows": int(len(review)),
        "holding_up_rows": int(len(holding)),
        "fading_rows": int(len(fading)),
        "decision_counts": counts.to_dict("records") if not counts.empty else [],
        "holding_up": holding.to_dict("records") if not holding.empty else [],
        "guardrail": "Research/backtesting only. Does not approve paper trades or alter scanner gates.",
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if review.empty:
        body = "No promising VWAP reclaim/reject rows were available for walk-forward review."
    else:
        body = f"""## Decision Counts

{markdown_table(counts)}

## Walk-Forward Rows

{markdown_table(review)}
"""

    md_path.write_text(
        f"""# VWAP Reclaim / Reject Walk-Forward Review

This report splits each promising VWAP reclaim/reject row into an older half
and a newer half. The goal is to see whether the newer trades still support
the strategy before it gets closer to forward paper validation.

Important: this is research/backtesting only. It does not create scanner
candidates, paper trades, broker alerts, or execution instructions.

```text
Trade log: {args.trade_log}
Summary CSV: {args.summary_csv}
Minimum trades per half: {args.min_half_trades}
Newer-half expectancy floor: {args.min_newer_expectancy_r:.2f}R
Newer-half profit-factor floor: {args.min_newer_profit_factor:.2f}
```

{body}

## Files

```text
logs/vwap_reclaim_reject_walk_forward.json
logs/vwap_reclaim_reject_walk_forward.csv
logs/vwap_reclaim_reject_walk_forward.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = read_csv_or_empty(args.summary_csv)
    trades = read_csv_or_empty(args.trade_log)
    review = build_review(summary, trades, args)
    write_outputs(args.output_dir, review, args)
    print(f"Saved VWAP reclaim/reject walk-forward CSV: {args.output_dir / 'vwap_reclaim_reject_walk_forward.csv'}")
    print(f"Saved VWAP reclaim/reject walk-forward report: {args.output_dir / 'vwap_reclaim_reject_walk_forward.md'}")


if __name__ == "__main__":
    main()
