"""Review whether relaxing the opening-range filter is worth testing further.

This is a focused response to the no-trade blocker report. It compares the
current long setup against the existing `no_opening_range` research variant.

It is research/backtesting only. It does not change scanner rules, create
paper trades, place broker orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


REQUIRED_VARIANTS = {"current", "no_opening_range"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review opening-range relaxation results.")
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=Path("logs/webull_watchlist_backtest_summary.csv"),
        help="Backtest summary containing current and no_opening_range variants.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_summary(path: Path) -> pd.DataFrame:
    """Read the watchlist summary used for comparison."""

    if not path.exists():
        raise FileNotFoundError(f"Backtest summary not found: {path}")
    return pd.read_csv(path)


def metric(value: object) -> float:
    """Return numeric metrics safely."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def decision_for_row(row: pd.Series) -> tuple[str, str]:
    """Decide how to treat an opening-range relaxation result."""

    relaxed_trades = int(row["relaxed_trades"])
    current_trades = int(row["current_trades"])
    relaxed_expectancy = float(row["relaxed_expectancy_r"])
    expectancy_delta = float(row["expectancy_delta"])
    relaxed_profit_factor = float(row["relaxed_profit_factor"])
    profit_factor_delta = float(row["profit_factor_delta"])
    added_trades = int(row["added_trades"])

    if relaxed_trades < 10:
        return "needs_more_sample", "Relaxed variant still has fewer than 10 trades."
    if added_trades <= 0:
        return "no_frequency_gain", "Relaxing opening range did not add trades."
    if relaxed_expectancy >= 0.10 and relaxed_profit_factor >= 1.30 and expectancy_delta >= -0.02:
        return "paper_watch_candidate", "Relaxed variant adds trades while keeping a usable expectancy floor."
    if relaxed_expectancy > 0 and expectancy_delta >= -0.03 and profit_factor_delta >= -0.35:
        return "shadow_test_only", "Relaxed variant is positive but weaker; collect as shadow paper evidence first."
    if relaxed_expectancy > float(row["current_expectancy_r"]) and relaxed_expectancy < 0:
        return "less_bad_but_not_tradeable", "Relaxed variant improved a losing setup but remains negative."
    return "reject_relaxation", "Relaxing opening range weakened expectancy or profit factor too much."


def build_review(summary: pd.DataFrame) -> pd.DataFrame:
    """Compare current vs no-opening-range rows symbol by symbol."""

    if summary.empty:
        return pd.DataFrame()
    work = summary[
        (summary["variant"].isin(REQUIRED_VARIANTS))
        & (summary["exit_profile"].astype(str) == "no_vwap_exit")
    ].copy()
    rows = []
    for symbol, group in work.groupby("symbol", sort=True):
        current = group[group["variant"] == "current"]
        relaxed = group[group["variant"] == "no_opening_range"]
        if current.empty or relaxed.empty:
            continue
        current_row = current.iloc[0]
        relaxed_row = relaxed.iloc[0]
        row = {
            "symbol": symbol,
            "current_trades": int(metric(current_row.get("baseline_trades", 0))),
            "relaxed_trades": int(metric(relaxed_row.get("baseline_trades", 0))),
            "added_trades": int(metric(relaxed_row.get("baseline_trades", 0)) - metric(current_row.get("baseline_trades", 0))),
            "current_win_rate": metric(current_row.get("baseline_win_rate", 0)),
            "relaxed_win_rate": metric(relaxed_row.get("baseline_win_rate", 0)),
            "current_expectancy_r": metric(current_row.get("baseline_expectancy_r", 0)),
            "relaxed_expectancy_r": metric(relaxed_row.get("baseline_expectancy_r", 0)),
            "expectancy_delta": round(
                metric(relaxed_row.get("baseline_expectancy_r", 0)) - metric(current_row.get("baseline_expectancy_r", 0)),
                4,
            ),
            "current_profit_factor": metric(current_row.get("baseline_profit_factor", 0)),
            "relaxed_profit_factor": metric(relaxed_row.get("baseline_profit_factor", 0)),
            "profit_factor_delta": round(
                metric(relaxed_row.get("baseline_profit_factor", 0)) - metric(current_row.get("baseline_profit_factor", 0)),
                4,
            ),
            "current_signal_count": int(metric(current_row.get("long_signal_count", 0))),
            "relaxed_signal_count": int(metric(relaxed_row.get("long_signal_count", 0))),
            "summary_report": str(relaxed_row.get("summary_report", "")),
        }
        decision, reason = decision_for_row(pd.Series(row))
        row["decision"] = decision
        row["reason"] = reason
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    order = {
        "paper_watch_candidate": 0,
        "shadow_test_only": 1,
        "needs_more_sample": 2,
        "less_bad_but_not_tradeable": 3,
        "no_frequency_gain": 4,
        "reject_relaxation": 5,
    }
    result = pd.DataFrame(rows)
    result["_order"] = result["decision"].map(order).fillna(9)
    return result.sort_values(
        ["_order", "expectancy_delta", "relaxed_expectancy_r", "added_trades"],
        ascending=[True, False, False, False],
    ).drop(columns=["_order"]).reset_index(drop=True)


def write_report(path: Path, review: pd.DataFrame, source: Path) -> None:
    """Write the opening-range relaxation review."""

    if review.empty:
        body = "No current/no_opening_range comparison rows were available."
        verdict = "Run the current vs no_opening_range backtest comparison first."
    else:
        counts = review.groupby("decision").size().reset_index(name="symbols")
        total_added = int(review["added_trades"].sum())
        best = review.iloc[0]
        verdict = (
            f"Opening-range relaxation added {total_added} historical trades across this run. "
            f"Best decision is {best['decision']} for {best['symbol']}; do not globally loosen the scanner yet."
        )
        body = f"""## Decision Counts

{markdown_table(counts)}

## Symbol Comparison

{markdown_table(review)}
"""

    path.write_text(
        f"""# Opening Range Relaxation Review

This report tests whether removing the opening-range requirement can help
Gwala collect more paper samples without destroying expectancy.

Important: this is research/backtesting only. It does not change scanner
rules, create paper trades, place broker orders, or connect to broker
execution.

```text
Source summary: {source}
Compared variants: current + no_vwap_exit vs no_opening_range + no_vwap_exit
```

## Verdict

```text
{verdict}
```

{body}

## Recommendation

```text
Do not remove the opening-range rule globally.
If no-trade analysis keeps showing one-rule opening-range misses, collect them as shadow/watch evidence first.
Only promote a relaxed opening-range rule after it improves expectancy or paper-watch outcomes for the specific symbol/setup.
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = read_summary(args.summary_csv)
    review = build_review(summary)
    csv_path = args.output_dir / "opening_range_relaxation_review.csv"
    report_path = args.output_dir / "opening_range_relaxation_review.md"
    review.to_csv(csv_path, index=False)
    write_report(report_path, review, args.summary_csv)
    print(f"Saved opening-range relaxation CSV: {csv_path}")
    print(f"Saved opening-range relaxation report: {report_path}")


if __name__ == "__main__":
    main()
