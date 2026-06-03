"""Find weak spots inside the current approved portfolio.

This is research/backtesting only. It reads accepted portfolio trades and
summarizes where performance is leaking by symbol, setup, month, entry time,
quality score, relative volume, room to target, and exit reason.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze weak spots in accepted portfolio trades.")
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/portfolio_approved_monthly_stop_3r_accepted_trades.csv"),
        help="Accepted portfolio trades to analyze.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--focus-symbols",
        nargs="+",
        default=["SPY", "NVDA"],
        help="Symbols to spotlight in the focused section.",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=4,
        help="Minimum trades required for a group to appear in weakness tables.",
    )
    return parser.parse_args()


def add_analysis_columns(trades: pd.DataFrame) -> pd.DataFrame:
    """Add plain-English grouping columns for diagnostics."""

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["exit_time"] = pd.to_datetime(result["exit_time"], utc=True)
    ny_entry = result["entry_time"].dt.tz_convert("America/New_York")
    result["entry_month"] = ny_entry.dt.strftime("%Y-%m")
    result["entry_hour_et"] = ny_entry.dt.hour
    result["entry_time_bucket"] = pd.cut(
        result["entry_hour_et"],
        bins=[9, 10, 11, 12, 13, 14, 15, 16],
        labels=["09-10", "10-11", "11-12", "12-13", "13-14", "14-15", "15-16"],
        right=False,
    ).astype(str)

    result["r_result"] = result["r_result"].astype(float)
    result["relative_volume"] = result["relative_volume"].astype(float)
    result["quality_score"] = result["quality_score"].astype(float)
    result["room_to_resistance_r"] = result["room_to_resistance_r"].astype(float)

    result["relative_volume_bucket"] = pd.cut(
        result["relative_volume"],
        bins=[-float("inf"), 0.75, 1.0, 1.25, 1.5, 2.0, float("inf")],
        labels=["<0.75", "0.75-1.0", "1.0-1.25", "1.25-1.5", "1.5-2.0", "2.0+"],
    ).astype(str)
    result["quality_score_bucket"] = pd.cut(
        result["quality_score"],
        bins=[-float("inf"), 5, 6, 7, 8, 9, float("inf")],
        labels=["<=5", "6", "7", "8", "9", "10+"],
    ).astype(str)
    result["room_to_target_bucket"] = pd.cut(
        result["room_to_resistance_r"],
        bins=[-float("inf"), 0.75, 1.0, 1.25, 1.5, 2.0, float("inf")],
        labels=["<0.75", "0.75-1.0", "1.0-1.25", "1.25-1.5", "1.5-2.0", "2.0+"],
    ).astype(str)
    return result


def summarize_group(trades: pd.DataFrame, group_columns: list[str], min_trades: int) -> pd.DataFrame:
    """Calculate metrics for one grouping shape."""

    rows = []
    for group_value, group in trades.groupby(group_columns, dropna=False):
        metrics = calculate_metrics(group)
        if metrics["trades"] < min_trades:
            continue

        if not isinstance(group_value, tuple):
            group_value = (group_value,)

        row = {column: value for column, value in zip(group_columns, group_value)}
        row.update(
            {
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "total_r": round(float(group["r_result"].sum()), 4),
                "average_loss_r": round(float(group.loc[group["r_result"] < 0, "r_result"].mean()), 4)
                if (group["r_result"] < 0).any()
                else 0.0,
                "loss_count": int((group["r_result"] < 0).sum()),
            }
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["expectancy_r", "total_r", "trades"], ascending=[True, True, False])


def worst_rows(frame: pd.DataFrame, count: int = 12) -> pd.DataFrame:
    """Return the worst rows from a summary frame."""

    if frame.empty:
        return frame
    return frame.head(count)


def focus_symbol_report(trades: pd.DataFrame, symbols: list[str], min_trades: int) -> dict[str, pd.DataFrame]:
    """Build focused weakness tables for selected symbols."""

    focus = trades[trades["symbol"].isin([symbol.upper() for symbol in symbols])]
    return {
        "focus_by_month": worst_rows(summarize_group(focus, ["symbol", "playbook_setup", "entry_month"], min_trades)),
        "focus_by_time": worst_rows(summarize_group(focus, ["symbol", "playbook_setup", "entry_time_bucket"], min_trades)),
        "focus_by_quality": worst_rows(
            summarize_group(focus, ["symbol", "playbook_setup", "quality_score_bucket"], min_trades)
        ),
        "focus_by_relvol": worst_rows(
            summarize_group(focus, ["symbol", "playbook_setup", "relative_volume_bucket"], min_trades)
        ),
        "focus_by_room": worst_rows(
            summarize_group(focus, ["symbol", "playbook_setup", "room_to_target_bucket"], min_trades)
        ),
        "focus_by_exit": worst_rows(summarize_group(focus, ["symbol", "playbook_setup", "exit_reason"], min_trades)),
    }


def write_report(
    path: Path,
    trades: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    focus_symbols: list[str],
    min_trades: int,
) -> None:
    """Write the Markdown report."""

    overall = calculate_metrics(trades)
    body = f"""# Weakness Analyzer Report

This report inspects accepted trades from the current portfolio and highlights
where the strategy is leaking R.

Important: this is still research/backtesting only. It does not place orders,
create alerts, or connect to broker execution.

## Inputs

```text
Focus symbols: {", ".join(focus_symbols)}
Minimum trades per group: {min_trades}
Total accepted trades analyzed: {overall["trades"]}
Portfolio expectancy: {overall["expectancy_r"]}R
Portfolio profit factor: {overall["profit_factor"]}
```

## Worst Symbol/Setup Groups

{markdown_table(tables["symbol_setup"])}

## Worst Symbol/Setup/Month Groups

{markdown_table(tables["symbol_setup_month"])}

## Worst Symbol/Setup/Time Groups

{markdown_table(tables["symbol_setup_time"])}

## Focus Symbols By Month

{markdown_table(tables["focus_by_month"])}

## Focus Symbols By Time

{markdown_table(tables["focus_by_time"])}

## Focus Symbols By Quality Score

{markdown_table(tables["focus_by_quality"])}

## Focus Symbols By Relative Volume

{markdown_table(tables["focus_by_relvol"])}

## Focus Symbols By Room To Target

{markdown_table(tables["focus_by_room"])}

## Focus Symbols By Exit Reason

{markdown_table(tables["focus_by_exit"])}

## Files

```text
logs/weakness_*.csv
logs/weakness_analyzer_report.md
```
"""
    path.write_text(body, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = pd.read_csv(args.trades_csv)
    trades = add_analysis_columns(trades)

    tables = {
        "symbol_setup": worst_rows(summarize_group(trades, ["symbol", "playbook_setup"], args.min_trades)),
        "symbol_setup_month": worst_rows(
            summarize_group(trades, ["symbol", "playbook_setup", "entry_month"], args.min_trades)
        ),
        "symbol_setup_time": worst_rows(
            summarize_group(trades, ["symbol", "playbook_setup", "entry_time_bucket"], args.min_trades)
        ),
    }
    tables.update(focus_symbol_report(trades, args.focus_symbols, args.min_trades))

    for name, table in tables.items():
        table.to_csv(args.output_dir / f"weakness_{name}.csv", index=False)

    report_path = args.output_dir / "weakness_analyzer_report.md"
    write_report(report_path, trades, tables, args.focus_symbols, args.min_trades)
    print(f"Saved weakness report: {report_path}")


if __name__ == "__main__":
    main()
