"""Plain-English backtest reports.

The CSV files are useful, but they can feel like raw bookkeeping. This module
creates a readable report that explains what the user should look at first.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def format_percent(value: float) -> str:
    """Turn a decimal win rate into a readable percentage."""

    return f"{value * 100:.2f}%"


def strategy_verdict(metrics: dict) -> str:
    """Give a simple research verdict based on core stats."""

    trades = metrics.get("trades", 0)
    expectancy = metrics.get("expectancy_r", 0)
    profit_factor = metrics.get("profit_factor", 0)

    if trades < 20:
        return "Not enough trades yet. Treat this as an early sample, not proof."

    if isinstance(profit_factor, str):
        profit_factor_value = 999.0
    else:
        profit_factor_value = float(profit_factor)

    if expectancy > 0 and profit_factor_value >= 1.3:
        return "Promising. This version may deserve more testing across symbols and longer history."

    if expectancy > 0 and profit_factor_value > 1.0:
        return "Slightly positive. Keep testing, but do not treat it as ready yet."

    return "Not ready. The rules need more filtering, better exits, or different market conditions."


def metric_table(metrics: dict) -> str:
    """Build a Markdown table for one metrics dictionary."""

    win_rate = metrics.get("win_rate", 0)
    rows = [
        ("Trades", metrics.get("trades", 0), "How many simulated trades were taken."),
        ("Win rate", format_percent(win_rate), "How often the trade closed above breakeven."),
        ("Expectancy (R)", metrics.get("expectancy_r", 0), "Average R gained or lost per trade."),
        ("Profit factor", metrics.get("profit_factor", 0), "Total winning R divided by total losing R."),
        ("Max drawdown (R)", metrics.get("max_drawdown_r", 0), "Worst peak-to-trough losing stretch."),
        ("Average R", metrics.get("average_r", 0), "Same as expectancy, shown for quick review."),
    ]

    lines = ["| Metric | Value | What it means |", "|---|---:|---|"]
    for name, value, meaning in rows:
        lines.append(f"| {name} | {value} | {meaning} |")
    return "\n".join(lines)


def grade_table(grade_metrics: pd.DataFrame) -> str:
    """Build a short Markdown table showing A/B/C performance."""

    if grade_metrics.empty:
        return "No grade breakdown was produced because there were no baseline trades."

    lines = ["| Grade | Trades | Win rate | Expectancy (R) | Profit factor | Max drawdown (R) |", "|---|---:|---:|---:|---:|---:|"]
    for _, row in grade_metrics.iterrows():
        lines.append(
            "| "
            f"{row.get('quality_grade', '')} | "
            f"{int(row.get('trades', 0))} | "
            f"{format_percent(float(row.get('win_rate', 0)))} | "
            f"{row.get('expectancy_r', 0)} | "
            f"{row.get('profit_factor', 0)} | "
            f"{row.get('max_drawdown_r', 0)} |"
        )
    return "\n".join(lines)


def exit_reason_table(exit_metrics: pd.DataFrame) -> str:
    """Build a Markdown table showing why trades exited."""

    if exit_metrics.empty:
        return "No exit breakdown was produced because there were no trades."

    lines = ["| Exit reason | Trades | Win rate | Expectancy (R) | Profit factor | Average R |", "|---|---:|---:|---:|---:|---:|"]
    for _, row in exit_metrics.iterrows():
        lines.append(
            "| "
            f"{row.get('exit_reason', '')} | "
            f"{int(row.get('trades', 0))} | "
            f"{format_percent(float(row.get('win_rate', 0)))} | "
            f"{row.get('expectancy_r', 0)} | "
            f"{row.get('profit_factor', 0)} | "
            f"{row.get('average_r', 0)} |"
        )
    return "\n".join(lines)


def generate_summary_report(
    path: Path,
    symbol: str,
    period: str,
    baseline_metrics: dict,
    elite_metrics: dict,
    grade_metrics: pd.DataFrame,
    output_files: dict,
    baseline_exit_metrics: pd.DataFrame | None = None,
    elite_exit_metrics: pd.DataFrame | None = None,
) -> None:
    """Write a readable Markdown report to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)

    report = f"""# {symbol} Backtest Summary

Data tested: `{period}`

This report compares your baseline VWAP/EMA continuation strategy against the stricter elite A-setup filter.

## Quick Verdict

Baseline: {strategy_verdict(baseline_metrics)}

Elite A-setup: {strategy_verdict(elite_metrics)}

## Baseline Strategy

{metric_table(baseline_metrics)}

## Elite A-Setup Strategy

{metric_table(elite_metrics)}

## Baseline Performance By Grade

{grade_table(grade_metrics)}

## Baseline Exit Reasons

{exit_reason_table(baseline_exit_metrics if baseline_exit_metrics is not None else pd.DataFrame())}

## Elite Exit Reasons

{exit_reason_table(elite_exit_metrics if elite_exit_metrics is not None else pd.DataFrame())}

## How To Read This

- `Expectancy (R)` is the most important number. Positive means the average trade made money in risk units.
- `Profit factor` should ideally be above 1.0, and stronger systems are often above 1.3.
- `Max drawdown (R)` shows how painful the worst losing stretch was.
- `Elite A-setup` should usually take fewer trades than baseline. That is normal.
- If elite has too few trades, test more symbols or more history before judging it.

## Files Created

- Entry candles: `{output_files["entry_candles"]}`
- Exit candles: `{output_files["exit_candles"]}`
- Baseline trade log: `{output_files["baseline_trades"]}`
- Elite trade log: `{output_files["elite_trades"]}`
- Grade report: `{output_files["grade_report"]}`
- Baseline exit report: `{output_files.get("baseline_exit_report", "")}`
- Elite exit report: `{output_files.get("elite_exit_report", "")}`
- Baseline chart: `{output_files["baseline_chart"]}`
- Elite chart: `{output_files["elite_chart"]}`

## Review Checklist

1. Check whether elite expectancy is better than baseline.
2. Check whether A-grade trades outperform B/C-grade trades.
3. Open the chart and visually inspect entries and exits.
4. If the system is negative, review the losing trades before changing rules.
5. Repeat on multiple symbols before drawing conclusions.
"""

    path.write_text(report, encoding="utf-8")
