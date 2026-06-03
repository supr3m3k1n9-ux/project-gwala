"""Command-line entry point for the research framework."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("logs") / ".matplotlib"))

from backtesting.engine import run_long_backtest
from backtesting.metrics import calculate_metrics, calculate_metrics_by_group
from config.settings import STRATEGY
from data.market_data import download_candles, load_candles_from_csv, save_candles
from indicators.multitimeframe import add_higher_timeframe_bias
from indicators.session import add_opening_range, add_session_columns
from indicators.trend import add_core_indicators
from reports.summary import generate_summary_report
from strategies.opening_trend_continuation import add_long_signals
from visualization.charts import plot_trades


def print_metrics(title: str, metrics: dict) -> None:
    """Print a compact metric block."""

    print(f"\n{title}")
    print("-" * len(title))
    for name, value in metrics.items():
        print(f"{name}: {value}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest VWAP + EMA trend continuation.")
    parser.add_argument("--symbol", default="SPY", help="Ticker symbol to test.")
    parser.add_argument("--period", default="60d", help="Historical lookback, for example 60d.")
    parser.add_argument(
        "--entry-csv",
        type=Path,
        help="Optional local CSV for entry candles, normally 30m.",
    )
    parser.add_argument(
        "--exit-csv",
        type=Path,
        help="Optional local CSV for exit candles, normally 5m.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbol = args.symbol.upper()

    if bool(args.entry_csv) != bool(args.exit_csv):
        raise ValueError("Use --entry-csv and --exit-csv together so entries and exits stay aligned.")

    if args.entry_csv and args.exit_csv:
        print(f"Loading {symbol} entry candles from {args.entry_csv}...")
        entry_candles = load_candles_from_csv(args.entry_csv, symbol=symbol)
        print(f"Loading {symbol} exit candles from {args.exit_csv}...")
        exit_candles = load_candles_from_csv(args.exit_csv, symbol=symbol)
        data_label = "csv"
        report_period = f"CSV files: {args.entry_csv} and {args.exit_csv}"
    else:
        print(f"Downloading {symbol} entry and exit candles...")
        entry_candles = download_candles(symbol=symbol, period=args.period, interval=STRATEGY.execution_interval)
        exit_candles = download_candles(symbol=symbol, period=args.period, interval=STRATEGY.exit_interval)
        data_label = args.period
        report_period = args.period

    entry_candles = add_core_indicators(
        entry_candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    exit_candles = add_core_indicators(
        exit_candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )

    entry_candles = add_session_columns(entry_candles, STRATEGY)
    exit_candles = add_session_columns(exit_candles, STRATEGY)
    entry_candles = add_opening_range(entry_candles, exit_candles, STRATEGY)
    entry_candles = add_higher_timeframe_bias(
        entry_candles,
        thesis_interval=STRATEGY.thesis_interval,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    entry_candles = add_long_signals(entry_candles, STRATEGY)

    baseline_trades = run_long_backtest(
        entry_candles,
        exit_candles,
        STRATEGY,
        signal_column="long_signal",
        setup_type="baseline_vwap_ema_trend_continuation",
    )
    elite_trades = run_long_backtest(
        entry_candles,
        exit_candles,
        STRATEGY,
        signal_column="elite_long_signal",
        setup_type="elite_a_setup_vwap_ema_trend_continuation",
    )
    baseline_metrics = calculate_metrics(baseline_trades)
    elite_metrics = calculate_metrics(elite_trades)
    baseline_grade_metrics = calculate_metrics_by_group(baseline_trades, "quality_grade")

    output_stem = f"{symbol}_{data_label}_{STRATEGY.execution_interval}_entry_{STRATEGY.exit_interval}_exit"
    output_files = {
        "entry_candles": f"logs/{output_stem}_entry_candles.csv",
        "exit_candles": f"logs/{output_stem}_exit_candles.csv",
        "baseline_trades": f"logs/{output_stem}_baseline_trades.csv",
        "elite_trades": f"logs/{output_stem}_elite_trades.csv",
        "grade_report": f"logs/{output_stem}_baseline_by_grade.csv",
        "baseline_chart": f"logs/{output_stem}_baseline_chart.png",
        "elite_chart": f"logs/{output_stem}_elite_chart.png",
        "summary_report": f"logs/{output_stem}_summary.md",
    }

    save_candles(entry_candles, Path(output_files["entry_candles"]))
    save_candles(exit_candles, Path(output_files["exit_candles"]))
    baseline_trades.to_csv(Path(output_files["baseline_trades"]), index=False)
    elite_trades.to_csv(Path(output_files["elite_trades"]), index=False)
    baseline_grade_metrics.to_csv(Path(output_files["grade_report"]), index=False)
    plot_trades(entry_candles, baseline_trades, Path(output_files["baseline_chart"]))
    plot_trades(entry_candles, elite_trades, Path(output_files["elite_chart"]))
    generate_summary_report(
        Path(output_files["summary_report"]),
        symbol=symbol,
        period=report_period,
        baseline_metrics=baseline_metrics,
        elite_metrics=elite_metrics,
        grade_metrics=baseline_grade_metrics,
        output_files=output_files,
    )

    print_metrics("Baseline Strategy Metrics", baseline_metrics)
    print_metrics("Elite A-Setup Metrics", elite_metrics)

    print(f"\nSaved summary report: {output_files['summary_report']}")
    print(f"Saved entry candles: {output_files['entry_candles']}")
    print(f"Saved exit candles: {output_files['exit_candles']}")
    print(f"Saved baseline trade log: {output_files['baseline_trades']}")
    print(f"Saved elite trade log: {output_files['elite_trades']}")
    print(f"Saved baseline grade report: {output_files['grade_report']}")
    print(f"Saved baseline chart: {output_files['baseline_chart']}")
    print(f"Saved elite chart: {output_files['elite_chart']}")


if __name__ == "__main__":
    main()
