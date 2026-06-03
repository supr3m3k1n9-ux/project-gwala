"""Run the approved symbol/setup playbook.

This runner answers a different question than the broad watchlist runner:

    If we only trade the currently approved setup for each symbol, what does
    the combined research playbook look like?

It remains backtesting-only. It does not place orders, create alerts, or talk
to a broker execution API.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics, calculate_metrics_by_group
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from run_webull_watchlist import (
    MARKET_CONFIRMED_VARIANTS,
    normalize_metric,
    run_symbol_backtest,
    settings_for_variant,
    use_baseline_candidate_metrics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the current approved setup playbook.")
    parser.add_argument(
        "--mode",
        choices=sorted(PLAYBOOKS),
        default="approved",
        help="Which playbook entries to run.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull CSV files are stored.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where playbook reports are saved.")
    parser.add_argument(
        "--market-regime-symbol",
        default="SPY",
        help="Market symbol used by market-confirmed long variants.",
    )
    return parser.parse_args()


def selected_trade_log_path(entry: PlaybookEntry, output_dir: Path) -> Path:
    """Return the trade CSV path that represents this playbook entry."""

    settings = settings_for_variant(entry.variant)
    output_stem = (
        f"{entry.symbol}_{entry.variant}_{entry.exit_profile}_webull_"
        f"{settings.execution_interval}_entry_{settings.exit_interval}_exit"
    )
    trade_type = "baseline" if use_baseline_candidate_metrics(entry.variant) else "elite"
    return output_dir / f"{output_stem}_{trade_type}_trades.csv"


def markdown_table(frame: pd.DataFrame) -> str:
    """Convert a small DataFrame to a Markdown table."""

    if frame.empty:
        return "No rows."

    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def metrics_frame_by_group(trades: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Calculate metrics by a playbook column and keep column order friendly."""

    grouped = calculate_metrics_by_group(trades, group_column)
    if grouped.empty:
        return grouped

    ordered = [
        group_column,
        "trades",
        "win_rate",
        "expectancy_r",
        "profit_factor",
        "max_drawdown_r",
        "average_r",
    ]
    return grouped[ordered]


def write_playbook_summary(
    path: Path,
    mode: str,
    entries: list[dict],
    trades: pd.DataFrame,
    overall_metrics: dict,
) -> None:
    """Write the plain-English playbook summary."""

    entries_frame = pd.DataFrame(entries)
    by_setup = metrics_frame_by_group(trades, "playbook_setup")
    by_symbol = metrics_frame_by_group(trades, "symbol")
    by_direction = metrics_frame_by_group(trades, "playbook_direction")

    path.write_text(
        f"""# Playbook {mode.title()} Summary

This report combines only the selected setup/symbol pairs for playbook mode
`{mode}`.

Important: this is still research/backtesting only. It is not live trading,
paper trading, or broker execution.

## Overall Metrics

| Metric | Value |
| --- | ---: |
| Trades | {overall_metrics.get("trades", 0)} |
| Win rate | {overall_metrics.get("win_rate", 0)} |
| Expectancy R | {overall_metrics.get("expectancy_r", 0)} |
| Profit factor | {overall_metrics.get("profit_factor", 0)} |
| Max drawdown R | {overall_metrics.get("max_drawdown_r", 0)} |
| Average R | {overall_metrics.get("average_r", 0)} |

## Entries

{markdown_table(entries_frame)}

## Metrics By Setup

{markdown_table(by_setup)}

## Metrics By Symbol

{markdown_table(by_symbol)}

## Metrics By Direction

{markdown_table(by_direction)}

## Files

```text
logs/playbook_{mode}_trades.csv
logs/playbook_{mode}_summary.csv
logs/playbook_{mode}_summary.md
```
""",
        encoding="utf-8",
    )


def run_entry(entry: PlaybookEntry, data_dir: Path, output_dir: Path, market_regime_symbol: str) -> tuple[dict, pd.DataFrame]:
    """Run one playbook entry and return its summary row plus selected trades."""

    entry_csv = data_dir / f"webull_{entry.symbol}_M30_candles.csv"
    exit_csv = data_dir / f"webull_{entry.symbol}_M5_candles.csv"
    market_csv = None
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        market_csv = data_dir / f"webull_{market_regime_symbol.upper()}_M30_candles.csv"

    result = run_symbol_backtest(
        symbol=entry.symbol,
        entry_csv=entry_csv,
        exit_csv=exit_csv,
        output_dir=output_dir,
        variant=entry.variant,
        exit_profile_name=entry.exit_profile,
        market_csv=market_csv,
        market_symbol=market_regime_symbol.upper(),
    )

    trade_log = selected_trade_log_path(entry, output_dir)
    trades = pd.read_csv(trade_log)
    trades["playbook_setup"] = entry.setup_name
    trades["playbook_variant"] = entry.variant
    trades["playbook_exit_profile"] = entry.exit_profile
    trades["playbook_status"] = entry.status
    trades["playbook_direction"] = "short" if entry.variant.startswith("setup_b") else "long"
    trades["playbook_notes"] = entry.notes

    if use_baseline_candidate_metrics(entry.variant):
        trades_count = result["baseline_trades"]
        win_rate = result["baseline_win_rate"]
        expectancy = result["baseline_expectancy_r"]
        profit_factor = result["baseline_profit_factor"]
    else:
        trades_count = result["elite_trades"]
        win_rate = result["elite_win_rate"]
        expectancy = result["elite_expectancy_r"]
        profit_factor = result["elite_profit_factor"]

    summary_row = {
        "symbol": entry.symbol,
        "setup": entry.setup_name,
        "variant": entry.variant,
        "exit_profile": entry.exit_profile,
        "status": entry.status,
        "trades": trades_count,
        "win_rate": win_rate,
        "expectancy_r": expectancy,
        "profit_factor": profit_factor,
        "notes": entry.notes,
    }
    return {key: normalize_metric(value) for key, value in summary_row.items()}, trades


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    entries = PLAYBOOKS[args.mode]
    summary_rows = []
    trade_frames = []

    for entry in entries:
        print(f"=== {entry.symbol}: {entry.setup_name} / {entry.variant} / {entry.exit_profile} ===", flush=True)
        summary_row, trades = run_entry(entry, args.data_dir, args.output_dir, args.market_regime_symbol)
        summary_rows.append(summary_row)
        trade_frames.append(trades)

    combined_trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    if not combined_trades.empty:
        combined_trades["entry_time"] = pd.to_datetime(combined_trades["entry_time"])
        combined_trades = combined_trades.sort_values(["entry_time", "symbol", "playbook_setup"])

    overall_metrics = calculate_metrics(combined_trades)
    overall_metrics = {key: normalize_metric(value) for key, value in overall_metrics.items()}

    trades_path = args.output_dir / f"playbook_{args.mode}_trades.csv"
    summary_csv_path = args.output_dir / f"playbook_{args.mode}_summary.csv"
    summary_md_path = args.output_dir / f"playbook_{args.mode}_summary.md"

    combined_trades.to_csv(trades_path, index=False)
    pd.DataFrame(summary_rows).to_csv(summary_csv_path, index=False)
    write_playbook_summary(summary_md_path, args.mode, summary_rows, combined_trades, overall_metrics)

    print(f"\nSaved playbook trades: {trades_path}")
    print(f"Saved playbook CSV summary: {summary_csv_path}")
    print(f"Saved playbook Markdown summary: {summary_md_path}")
    print(f"Overall trades={overall_metrics['trades']} expectancy={overall_metrics['expectancy_r']}R")


if __name__ == "__main__":
    main()
