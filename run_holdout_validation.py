"""Validate portfolio filters across chronological date windows.

This is research/backtesting only. It compares the base portfolio profile
against optional trade filters across separate historical windows so a filter
does not get promoted just because it fit one sample too closely. These are
internal stability checks, not untouched out-of-sample proof.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table
from run_portfolio import (
    PROFILE_PRESETS,
    TRADE_FILTER_PRESETS,
    apply_trade_filter,
    build_equity_curve,
    simulate_portfolio,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare portfolio filters across date windows.")
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/playbook_approved_trades.csv"),
        help="Combined approved playbook trade log.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_PRESETS),
        default="monthly_stop_3r",
        help="Portfolio profile to validate.",
    )
    parser.add_argument(
        "--trade-filters",
        nargs="+",
        choices=sorted(TRADE_FILTER_PRESETS),
        default=["none", "weakness_v1"],
        help="Trade filters to compare.",
    )
    return parser.parse_args()


def add_entry_dates(trades: pd.DataFrame) -> pd.DataFrame:
    """Add New York entry date fields used by validation windows."""

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    ny_entry = result["entry_time"].dt.tz_convert("America/New_York")
    result["entry_date_et"] = ny_entry.dt.date.astype(str)
    result["entry_year_et"] = ny_entry.dt.year
    result["entry_month_et"] = ny_entry.dt.strftime("%Y-%m")
    return result


def validation_windows(trades: pd.DataFrame) -> list[dict]:
    """Build broad and calendar-period validation windows."""

    ordered = trades.sort_values("entry_time").reset_index(drop=True)
    midpoint = ordered.loc[len(ordered) // 2, "entry_time"]
    start = ordered["entry_time"].min()
    end = ordered["entry_time"].max()

    windows = [
        {"window": "full_sample", "window_type": "summary", "start": start, "end": end},
        {"window": "first_half", "window_type": "half_sample", "start": start, "end": midpoint},
        {"window": "second_half", "window_type": "half_sample", "start": midpoint, "end": end},
    ]
    for year in sorted(trades["entry_year_et"].unique()):
        year_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        year_end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        windows.append({"window": str(year), "window_type": "calendar_year", "start": year_start, "end": year_end})
    for month in sorted(trades["entry_month_et"].unique()):
        month_start_et = pd.Timestamp(f"{month}-01", tz="America/New_York")
        month_end_et = month_start_et + pd.offsets.MonthBegin(1)
        windows.append(
            {
                "window": f"month_{month}",
                "window_type": "calendar_month",
                "start": month_start_et.tz_convert("UTC"),
                "end": month_end_et.tz_convert("UTC"),
            }
        )
    return windows


def trades_for_window(trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, include_end: bool) -> pd.DataFrame:
    """Slice trades by entry time."""

    if include_end:
        return trades[(trades["entry_time"] >= start) & (trades["entry_time"] <= end)].copy()
    return trades[(trades["entry_time"] >= start) & (trades["entry_time"] < end)].copy()


def score_window(trades: pd.DataFrame, profile_name: str, filter_name: str) -> dict:
    """Apply one filter/profile pair and return metrics."""

    filtered, blocked = apply_trade_filter(trades, filter_name)
    profile = PROFILE_PRESETS[profile_name]
    accepted, skipped, _daily = simulate_portfolio(
        filtered,
        max_open_positions=profile["max_open_positions"],
        max_open_per_symbol=profile["max_open_per_symbol"],
        max_trades_per_day=profile["max_trades_per_day"],
        max_daily_loss_r=profile["max_daily_loss_r"],
        max_monthly_loss_r=profile["max_monthly_loss_r"],
    )
    metrics = calculate_metrics(accepted)
    equity = build_equity_curve(accepted)
    final_r = 0.0 if equity.empty else float(equity.iloc[-1]["cumulative_r"])
    return {
        "raw_trades": len(trades),
        "blocked_raw_trades": blocked,
        "accepted_trades": metrics["trades"],
        "skipped_trades": len(skipped),
        "win_rate": metrics["win_rate"],
        "expectancy_r": metrics["expectancy_r"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown_r": metrics["max_drawdown_r"],
        "final_cumulative_r": round(final_r, 4),
    }


def add_deltas(results: pd.DataFrame) -> pd.DataFrame:
    """Compare each filter to the no-filter baseline inside the same window."""

    rows = []
    for window, group in results.groupby("window", sort=False):
        baseline_rows = group[group["trade_filter"] == "none"]
        if baseline_rows.empty:
            rows.extend(group.to_dict("records"))
            continue

        baseline = baseline_rows.iloc[0]
        for _, row in group.iterrows():
            item = row.to_dict()
            item["expectancy_delta"] = round(float(row["expectancy_r"]) - float(baseline["expectancy_r"]), 4)
            item["profit_factor_delta"] = round(float(row["profit_factor"]) - float(baseline["profit_factor"]), 4)
            item["drawdown_delta"] = round(float(row["max_drawdown_r"]) - float(baseline["max_drawdown_r"]), 4)
            item["final_r_delta"] = round(float(row["final_cumulative_r"]) - float(baseline["final_cumulative_r"]), 4)
            rows.append(item)
    return pd.DataFrame(rows)


def stability_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Summarize whether filters improve in months where they block trades."""

    comparison = results[
        (results["window_type"] == "calendar_month")
        & (results["trade_filter"] != "none")
        & (results["blocked_raw_trades"] > 0)
    ].copy()
    rows = []
    for filter_name, group in comparison.groupby("trade_filter", sort=True):
        rows.append(
            {
                "trade_filter": filter_name,
                "months_with_blocks": len(group),
                "expectancy_improved_months": int((group["expectancy_delta"] > 0).sum()),
                "profit_factor_improved_months": int((group["profit_factor_delta"] > 0).sum()),
                "final_r_improved_months": int((group["final_r_delta"] > 0).sum()),
                "months_with_lower_final_r": int((group["final_r_delta"] < 0).sum()),
                "net_final_r_delta": round(float(group["final_r_delta"].sum()), 4),
            }
        )
    return pd.DataFrame(rows)


def stability_interpretation(summary: pd.DataFrame) -> str:
    """Write a cautious explanation of the monthly stability result."""

    if summary.empty:
        return "No filter blocked trades in the available monthly windows, so monthly stability cannot be evaluated yet."

    row = summary.iloc[0]
    months = int(row["months_with_blocks"])
    improved = int(row["expectancy_improved_months"])
    lower_final = int(row["months_with_lower_final_r"])
    net_final = float(row["net_final_r_delta"])
    return (
        f"The filter affected trades in {months} calendar month(s) and improved expectancy in "
        f"{improved} of them. It reduced final R in {lower_final} affected month(s), with a "
        f"net monthly final-R delta of {net_final:+.4f}R. Treat this as a stability check only: "
        "the filter was developed from related historical data and still requires forward paper validation."
    )


def write_report(path: Path, results: pd.DataFrame, profile_name: str) -> None:
    """Write a Markdown validation report."""

    comparison = results[results["trade_filter"] != "none"].copy()
    monthly = comparison[comparison["window_type"] == "calendar_month"].copy()
    summary = stability_summary(results)
    path.write_text(
        f"""# Holdout Validation Report

This report compares trade filters across date windows using the `{profile_name}`
portfolio profile.

Important: this is still research/backtesting only. It does not place orders,
create alerts, or connect to broker execution.

## Validation Limits

```text
These windows re-use available historical data. They measure whether a filter
behaves consistently across time, but they are not untouched out-of-sample
evidence and do not replace forward paper validation.
```

## Monthly Stability Summary

{markdown_table(summary)}

```text
{stability_interpretation(summary)}
```

## Monthly Filter Results

{markdown_table(monthly)}

## Filter Comparison

{markdown_table(comparison)}

## All Window Scores

{markdown_table(results)}

## Files

```text
logs/holdout_validation_results.csv
logs/holdout_validation_report.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = add_entry_dates(pd.read_csv(args.trades_csv))
    windows = validation_windows(trades)

    rows = []
    for window in windows:
        include_end = window["window"] in {"full_sample", "second_half"}
        window_trades = trades_for_window(trades, window["start"], window["end"], include_end)
        if window_trades.empty:
            continue

        for filter_name in args.trade_filters:
            score = score_window(window_trades, args.profile, filter_name)
            rows.append(
                {
                    "window": window["window"],
                    "window_type": window["window_type"],
                    "start": str(window["start"]),
                    "end": str(window["end"]),
                    "trade_filter": filter_name,
                    **score,
                }
            )

    results = add_deltas(pd.DataFrame(rows))
    results_path = args.output_dir / "holdout_validation_results.csv"
    report_path = args.output_dir / "holdout_validation_report.md"
    results.to_csv(results_path, index=False)
    write_report(report_path, results, args.profile)

    print(f"Saved validation CSV: {results_path}")
    print(f"Saved validation report: {report_path}")


if __name__ == "__main__":
    main()
