"""Fetch Webull candles and backtest a watchlist.

This is a research/backtesting runner only. It fetches market data, writes CSV
files, runs the existing strategy simulation, and creates combined reports.
It does not place orders or connect to any live execution workflow.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import math
import os
import time
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

os.environ.setdefault("MPLCONFIGDIR", str(Path("logs") / ".matplotlib"))

from backtesting.engine import ExitProfile, run_long_backtest, run_short_backtest
from backtesting.metrics import calculate_exit_reason_breakdown, calculate_metrics
from config.settings import STRATEGY
from data.candle_cache import preferred_candle_path, save_candle_cache
from data.market_data import load_candles_from_csv, save_candles
from data.webull_data import build_data_client, fetch_history_bars_paged, write_backtest_csv, write_raw_json
from indicators.multitimeframe import add_higher_timeframe_bias
from indicators.session import add_opening_range, add_session_columns
from indicators.trend import add_core_indicators
from reports.diagnostics import summarize_signal_diagnostics, write_diagnostics_report
from reports.summary import generate_summary_report
from strategies.opening_trend_continuation import add_long_signals
from strategies.opening_trend_continuation_short import add_short_signals
from visualization.charts import plot_trades


DEFAULT_SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "AMD", "AAPL", "META", "MSFT"]

STRATEGY_VARIANTS = {
    "current": {},
    "elite_score_6": {"elite_min_score": 6},
    "relvol_1_0": {"min_relative_volume": 1.0},
    "room_0_75": {"min_room_to_resistance_r": 0.75},
    "no_opening_range": {"require_above_opening_range": False},
    "full_session": {
        "entry_start_time": "09:30",
        "latest_entry_time": "15:30",
        "require_above_opening_range": False,
    },
    "quality_full_session": {
        "entry_start_time": "09:30",
        "latest_entry_time": "15:30",
        "require_above_opening_range": False,
        "elite_min_score": 6,
        "min_relative_volume": 1.0,
        "min_room_to_resistance_r": 0.75,
    },
    "balanced_relaxed": {
        "elite_min_score": 6,
        "min_relative_volume": 1.0,
        "min_room_to_resistance_r": 0.75,
    },
    "quality_entry": {
        "elite_min_score": 6,
        "min_relative_volume": 1.0,
        "min_room_to_resistance_r": 0.75,
    },
    "market_confirmed": {},
    "quality_entry_market_confirmed": {
        "elite_min_score": 6,
        "min_relative_volume": 1.0,
        "min_room_to_resistance_r": 0.75,
    },
    "setup_b_short": {},
    "setup_b_quality_short": {
        "elite_min_score": 6,
        "min_relative_volume": 1.0,
        "min_room_to_resistance_r": 0.75,
    },
    "setup_b_full_session": {
        "entry_start_time": "09:30",
        "latest_entry_time": "15:30",
        "require_above_opening_range": False,
    },
    "setup_b_quality_full_session": {
        "entry_start_time": "09:30",
        "latest_entry_time": "15:30",
        "require_above_opening_range": False,
        "elite_min_score": 6,
        "min_relative_volume": 1.0,
        "min_room_to_resistance_r": 0.75,
    },
    "trend_pullback_long": {
        "entry_start_time": "09:30",
        "latest_entry_time": "15:30",
        "require_above_opening_range": False,
    },
    "trend_pullback_short": {
        "entry_start_time": "09:30",
        "latest_entry_time": "15:30",
        "require_above_opening_range": False,
    },
}

MARKET_CONFIRMED_VARIANTS = {"market_confirmed", "quality_entry_market_confirmed"}
SETUP_B_SHORT_VARIANTS = {
    "setup_b_short",
    "setup_b_quality_short",
    "setup_b_full_session",
    "setup_b_quality_full_session",
}

EXIT_PROFILES = {
    "current": ExitProfile(name="current"),
    "target_1_5r": ExitProfile(name="target_1_5r", reward_multiple=1.5),
    "no_vwap_exit": ExitProfile(name="no_vwap_exit", use_vwap_exit=False),
    "two_vwap_closes": ExitProfile(name="two_vwap_closes", vwap_exit_consecutive_closes=2),
    "bearish_vwap_loss": ExitProfile(name="bearish_vwap_loss", require_bearish_vwap_loss=True),
    "ema9_exit": ExitProfile(name="ema9_exit", use_vwap_exit=False, use_ema9_exit=True),
    "breakeven_after_1r": ExitProfile(name="breakeven_after_1r", move_stop_to_breakeven_after_r=1.0),
}

CANDIDATE_PRESETS = {
    "best": [
        ("current", "no_vwap_exit"),
        ("quality_entry", "no_vwap_exit"),
    ],
    "market": [
        ("market_confirmed", "no_vwap_exit"),
        ("quality_entry_market_confirmed", "no_vwap_exit"),
    ],
    "best_plus_market": [
        ("current", "no_vwap_exit"),
        ("quality_entry", "no_vwap_exit"),
        ("market_confirmed", "no_vwap_exit"),
        ("quality_entry_market_confirmed", "no_vwap_exit"),
    ],
    "setup_b": [
        ("setup_b_short", "no_vwap_exit"),
        ("setup_b_quality_short", "no_vwap_exit"),
    ],
    "full_session": [
        ("full_session", "no_vwap_exit"),
        ("quality_full_session", "no_vwap_exit"),
        ("setup_b_full_session", "no_vwap_exit"),
        ("setup_b_quality_full_session", "no_vwap_exit"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Webull CSV backtests for a watchlist.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to test.")
    parser.add_argument("--entry-count", type=int, default=1200, help="30m candles to request. Webull max is 1200.")
    parser.add_argument("--exit-count", type=int, default=1200, help="5m candles to request. Webull max is 1200.")
    parser.add_argument("--entry-pages", type=int, default=1, help="How many older 30m pages to request.")
    parser.add_argument("--exit-pages", type=int, default=1, help="How many older 5m pages to request.")
    parser.add_argument("--chart-m1-count", type=int, default=240, help="1m chart-only candles to request. Use 0 to skip.")
    parser.add_argument("--chart-m1-pages", type=int, default=1, help="How many older 1m chart-only pages to request.")
    parser.add_argument("--chart-m15-count", type=int, default=400, help="15m chart-only candles to request. Use 0 to skip.")
    parser.add_argument("--chart-m15-pages", type=int, default=1, help="How many older 15m chart-only pages to request.")
    parser.add_argument("--chart-m60-count", type=int, default=400, help="1h chart-only candles to request. Use 0 to skip.")
    parser.add_argument("--chart-m60-pages", type=int, default=1, help="How many older 1h chart-only pages to request.")
    parser.add_argument("--chart-d-count", type=int, default=260, help="Daily chart-only candles to request. Use 0 to skip.")
    parser.add_argument("--chart-d-pages", type=int, default=1, help="How many older daily chart-only pages to request.")
    parser.add_argument("--pause", type=float, default=8.0, help="Seconds to wait between Webull requests.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports and CSV files are saved.")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["current"],
        choices=sorted(STRATEGY_VARIANTS),
        help="Strategy variants to compare.",
    )
    parser.add_argument(
        "--exit-profiles",
        nargs="+",
        default=["current"],
        choices=sorted(EXIT_PROFILES),
        help="Exit profiles to compare.",
    )
    parser.add_argument(
        "--reuse-csv",
        action="store_true",
        help="Skip Webull downloads and reuse existing logs/webull_SYMBOL_M30/M5 CSV files.",
    )
    parser.add_argument(
        "--chart-only",
        action="store_true",
        help="Fetch chart/context-only M1/M15/M60/D candles and skip strategy backtests.",
    )
    parser.add_argument(
        "--candidate-preset",
        choices=sorted(CANDIDATE_PRESETS),
        help="Use a curated set of variant/exit combinations, such as 'best'.",
    )
    parser.add_argument(
        "--min-approved-trades",
        type=int,
        default=10,
        help="Minimum trades required before a passing candidate is marked approved.",
    )
    parser.add_argument(
        "--market-regime-symbol",
        default="SPY",
        help="Symbol used as the broad-market confirmation filter for market variants.",
    )
    return parser.parse_args()


def settings_for_variant(variant: str):
    """Return strategy settings for a named research variant."""

    return replace(STRATEGY, **STRATEGY_VARIANTS[variant])


def add_strategy_columns(
    entry_candles: pd.DataFrame,
    exit_candles: pd.DataFrame,
    settings,
    market_candles: pd.DataFrame | None = None,
    market_symbol: str = "SPY",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add indicators, session fields, opening range, thesis, and signals."""

    entry_candles = add_core_indicators(
        entry_candles,
        fast_length=settings.fast_ema_length,
        slow_length=settings.slow_ema_length,
        regime_length=settings.regime_ema_length,
    )
    exit_candles = add_core_indicators(
        exit_candles,
        fast_length=settings.fast_ema_length,
        slow_length=settings.slow_ema_length,
        regime_length=settings.regime_ema_length,
    )

    entry_candles = add_session_columns(entry_candles, settings)
    exit_candles = add_session_columns(exit_candles, settings)
    entry_candles = add_opening_range(entry_candles, exit_candles, settings)
    entry_candles = add_higher_timeframe_bias(
        entry_candles,
        thesis_interval=settings.thesis_interval,
        fast_length=settings.fast_ema_length,
        slow_length=settings.slow_ema_length,
        regime_length=settings.regime_ema_length,
    )
    entry_candles = add_long_signals(entry_candles, settings)
    entry_candles = add_short_signals(entry_candles, settings)

    if market_candles is not None:
        entry_candles = add_market_regime_filter(entry_candles, market_candles, settings, market_symbol)

    return entry_candles, exit_candles


def add_market_regime_filter(
    entry_candles: pd.DataFrame,
    market_candles: pd.DataFrame,
    settings,
    market_symbol: str,
) -> pd.DataFrame:
    """Add a broad-market bullish filter to the symbol being tested.

    This is intentionally simple: the traded symbol can only enter when the
    market symbol is above VWAP, above the 21 EMA, and has the 9 EMA above the
    21 EMA on the same 30m timeframe. The filter is a research condition, not a
    prediction engine.
    """

    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"

    market = add_core_indicators(
        market_candles,
        fast_length=settings.fast_ema_length,
        slow_length=settings.slow_ema_length,
        regime_length=settings.regime_ema_length,
    )
    market["market_bullish_bias"] = (
        (market["close"] > market["vwap"])
        & (market["close"] > market[slow])
        & (market[fast] > market[slow])
    )

    merged = pd.merge_asof(
        entry_candles.sort_index(),
        market[["market_bullish_bias"]].sort_index(),
        left_index=True,
        right_index=True,
        direction="backward",
    )
    merged["market_bullish_bias"] = merged["market_bullish_bias"].fillna(False)
    merged["market_regime_symbol"] = market_symbol
    return merged


def apply_market_confirmation(candles: pd.DataFrame) -> pd.DataFrame:
    """Require broad-market confirmation for all long signal columns."""

    result = candles.copy()
    market_ok = result["market_bullish_bias"].fillna(False).astype(bool)
    for signal_column in ["long_signal", "elite_long_signal", "quality_entry_signal"]:
        if signal_column in result.columns:
            result[signal_column] = (result[signal_column].fillna(False) & market_ok).fillna(False)
    return result


def signal_column_for_variant(variant: str) -> str:
    """Return the stricter signal column used for the variant comparison."""

    if variant in {"quality_entry", "quality_entry_market_confirmed", "quality_full_session"}:
        return "quality_entry_signal"
    if variant in {"setup_b_short", "setup_b_full_session"}:
        return "elite_short_signal"
    if variant in {"setup_b_quality_short", "setup_b_quality_full_session"}:
        return "quality_short_signal"
    if variant == "trend_pullback_long":
        return "trend_pullback_long_signal"
    if variant == "trend_pullback_short":
        return "trend_pullback_short_signal"
    return "elite_long_signal"


def use_baseline_candidate_metrics(variant: str) -> bool:
    """Return True when the variant's main candidate is the baseline signal."""

    return variant in {"current", "market_confirmed", "setup_b_short", "full_session", "setup_b_full_session"}


def is_setup_b_short_variant(variant: str) -> bool:
    """Return True when the variant should be simulated as a short setup."""

    return variant in SETUP_B_SHORT_VARIANTS


def run_symbol_backtest(
    symbol: str,
    entry_csv: Path,
    exit_csv: Path,
    output_dir: Path,
    variant: str,
    exit_profile_name: str,
    market_csv: Path | None = None,
    market_symbol: str = "SPY",
) -> dict:
    """Run baseline and elite backtests for one symbol and save per-symbol files."""

    settings = settings_for_variant(variant)
    exit_profile = EXIT_PROFILES[exit_profile_name]
    entry_candles = load_candles_from_csv(entry_csv, symbol=symbol)
    exit_candles = load_candles_from_csv(exit_csv, symbol=symbol)
    market_candles = load_candles_from_csv(market_csv, symbol=market_symbol) if market_csv is not None else None
    entry_candles, exit_candles = add_strategy_columns(
        entry_candles,
        exit_candles,
        settings,
        market_candles=market_candles,
        market_symbol=market_symbol,
    )
    if variant in MARKET_CONFIRMED_VARIANTS:
        entry_candles = apply_market_confirmation(entry_candles)

    if is_setup_b_short_variant(variant):
        baseline_trades = run_short_backtest(
            entry_candles,
            exit_candles,
            settings,
            signal_column="short_signal",
            setup_type=f"{variant}_{exit_profile_name}_baseline_short_vwap_ema_trend_continuation",
            exit_profile=exit_profile,
        )
        elite_trades = run_short_backtest(
            entry_candles,
            exit_candles,
            settings,
            signal_column=signal_column_for_variant(variant),
            setup_type=f"{variant}_{exit_profile_name}_quality_short_vwap_ema_trend_continuation",
            exit_profile=exit_profile,
        )
    else:
        baseline_trades = run_long_backtest(
            entry_candles,
            exit_candles,
            settings,
            signal_column="long_signal",
            setup_type=f"{variant}_{exit_profile_name}_baseline_vwap_ema_trend_continuation",
            exit_profile=exit_profile,
        )
        elite_trades = run_long_backtest(
            entry_candles,
            exit_candles,
            settings,
            signal_column=signal_column_for_variant(variant),
            setup_type=f"{variant}_{exit_profile_name}_elite_a_setup_vwap_ema_trend_continuation",
            exit_profile=exit_profile,
        )

    baseline_metrics = calculate_metrics(baseline_trades)
    elite_metrics = calculate_metrics(elite_trades)
    grade_metrics = calculate_grade_metrics(baseline_trades)
    baseline_exit_metrics = calculate_exit_reason_breakdown(baseline_trades)
    elite_exit_metrics = calculate_exit_reason_breakdown(elite_trades)
    diagnostics = summarize_signal_diagnostics(entry_candles)

    output_stem = f"{symbol}_{variant}_{exit_profile_name}_webull_{settings.execution_interval}_entry_{settings.exit_interval}_exit"
    output_files = {
        "entry_candles": str(output_dir / f"{output_stem}_entry_candles.csv"),
        "exit_candles": str(output_dir / f"{output_stem}_exit_candles.csv"),
        "baseline_trades": str(output_dir / f"{output_stem}_baseline_trades.csv"),
        "elite_trades": str(output_dir / f"{output_stem}_elite_trades.csv"),
        "grade_report": str(output_dir / f"{output_stem}_baseline_by_grade.csv"),
        "baseline_exit_report": str(output_dir / f"{output_stem}_baseline_by_exit_reason.csv"),
        "elite_exit_report": str(output_dir / f"{output_stem}_elite_by_exit_reason.csv"),
        "diagnostics": str(output_dir / f"{output_stem}_diagnostics.csv"),
        "diagnostics_report": str(output_dir / f"{output_stem}_diagnostics.md"),
        "baseline_chart": str(output_dir / f"{output_stem}_baseline_chart.png"),
        "elite_chart": str(output_dir / f"{output_stem}_elite_chart.png"),
        "summary_report": str(output_dir / f"{output_stem}_summary.md"),
    }

    save_candles(entry_candles, Path(output_files["entry_candles"]))
    save_candles(exit_candles, Path(output_files["exit_candles"]))
    baseline_trades.to_csv(Path(output_files["baseline_trades"]), index=False)
    elite_trades.to_csv(Path(output_files["elite_trades"]), index=False)
    grade_metrics.to_csv(Path(output_files["grade_report"]), index=False)
    baseline_exit_metrics.to_csv(Path(output_files["baseline_exit_report"]), index=False)
    elite_exit_metrics.to_csv(Path(output_files["elite_exit_report"]), index=False)
    diagnostics.to_csv(Path(output_files["diagnostics"]), index=False)
    write_diagnostics_report(
        diagnostics,
        Path(output_files["diagnostics_report"]),
        title=f"{symbol} {variant} Signal Diagnostics",
    )
    plot_trades(entry_candles, baseline_trades, Path(output_files["baseline_chart"]))
    plot_trades(entry_candles, elite_trades, Path(output_files["elite_chart"]))
    generate_summary_report(
        Path(output_files["summary_report"]),
        symbol=symbol,
        period=f"Webull CSV files: {entry_csv} and {exit_csv}",
        baseline_metrics=baseline_metrics,
        elite_metrics=elite_metrics,
        grade_metrics=grade_metrics,
        output_files=output_files,
        baseline_exit_metrics=baseline_exit_metrics,
        elite_exit_metrics=elite_exit_metrics,
    )

    return {
        "symbol": symbol,
        "variant": variant,
        "exit_profile": exit_profile_name,
        "entry_candles": len(entry_candles),
        "exit_candles": len(exit_candles),
        "baseline_trades": baseline_metrics["trades"],
        "baseline_win_rate": baseline_metrics["win_rate"],
        "baseline_expectancy_r": baseline_metrics["expectancy_r"],
        "baseline_profit_factor": baseline_metrics["profit_factor"],
        "elite_trades": elite_metrics["trades"],
        "elite_win_rate": elite_metrics["win_rate"],
        "elite_expectancy_r": elite_metrics["expectancy_r"],
        "elite_profit_factor": elite_metrics["profit_factor"],
        "long_signal_count": int(entry_candles["long_signal"].fillna(False).sum()),
        "elite_signal_count": int(entry_candles["elite_long_signal"].fillna(False).sum()),
        "quality_entry_signal_count": int(entry_candles["quality_entry_signal"].fillna(False).sum()),
        "short_signal_count": int(entry_candles["short_signal"].fillna(False).sum()),
        "elite_short_signal_count": int(entry_candles["elite_short_signal"].fillna(False).sum()),
        "quality_short_signal_count": int(entry_candles["quality_short_signal"].fillna(False).sum()),
        "market_bullish_count": int(entry_candles.get("market_bullish_bias", pd.Series(False, index=entry_candles.index)).fillna(False).sum()),
        "diagnostics_report": output_files["diagnostics_report"],
        "summary_report": output_files["summary_report"],
    }


def calculate_grade_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Calculate grade metrics without importing from main.py."""

    from backtesting.metrics import calculate_metrics_by_group

    return calculate_metrics_by_group(trades, "quality_grade")


def fetch_and_save(
    data_client,
    symbol: str,
    timespan: str,
    count: int,
    pages: int,
    pause_seconds: float,
    output_dir: Path,
) -> Path:
    """Fetch one Webull timespan and save raw + normalized files."""

    rows = fetch_history_bars_paged(
        data_client=data_client,
        symbol=symbol,
        timespan=timespan,
        count=count,
        pages=pages,
        trading_sessions=["RTH"],
        pause_seconds=pause_seconds,
    )

    raw_path = output_dir / f"webull_probe_{symbol}_{timespan}.json"
    csv_path = output_dir / f"webull_{symbol}_{timespan}_candles.csv"
    write_raw_json(rows, raw_path)
    write_backtest_csv(rows, csv_path)
    candles = pd.read_csv(csv_path)
    return save_candle_cache(candles, output_dir, symbol, timespan, write_legacy_alias=True)


def fetch_chart_only_timeframes(data_client, symbol: str, args: argparse.Namespace, output_dir: Path) -> None:
    """Fetch extra chart-review candles without changing strategy signals."""

    chart_timeframes = [
        ("M1", args.chart_m1_count, args.chart_m1_pages),
        ("M15", args.chart_m15_count, args.chart_m15_pages),
        ("M60", args.chart_m60_count, args.chart_m60_pages),
        ("D", args.chart_d_count, args.chart_d_pages),
    ]
    for timespan, count, pages in chart_timeframes:
        if count <= 0 or pages <= 0:
            continue
        print(f"=== {symbol}: fetching {timespan} chart-only candles ===", flush=True)
        chart_csv = fetch_and_save(
            data_client,
            symbol,
            timespan,
            count,
            pages,
            args.pause,
            output_dir,
        )
        print(f"Saved {chart_csv}", flush=True)
        time.sleep(args.pause)


def write_combined_markdown(summary: pd.DataFrame, path: Path) -> None:
    """Write a plain-English watchlist summary."""

    if summary.empty:
        body = "No successful backtests were completed."
    else:
        columns = list(summary.columns)
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for _, row in summary.iterrows():
            values = [str(row[column]) for column in columns]
            lines.append("| " + " | ".join(values) + " |")
        body = "\n".join(lines)

    path.write_text(
        f"""# Webull Watchlist Backtest Summary

This report combines the latest Webull CSV backtests.

Important: small or recent samples are not proof of edge. Treat low trade
counts as inconclusive.

{body}
""",
        encoding="utf-8",
    )


def write_best_candidates_report(summary: pd.DataFrame, path: Path) -> None:
    """Write a smaller report for the two main research candidates."""

    path.parent.mkdir(parents=True, exist_ok=True)

    if summary.empty:
        body = "No candidate results were available."
    else:
        rows = []
        for _, row in summary.iterrows():
            candidate = f"{row['variant']} + {row['exit_profile']}"
            if use_baseline_candidate_metrics(row["variant"]):
                trades = row["baseline_trades"]
                win_rate = row["baseline_win_rate"]
                expectancy = row["baseline_expectancy_r"]
                profit_factor = row["baseline_profit_factor"]
            else:
                trades = row["elite_trades"]
                win_rate = row["elite_win_rate"]
                expectancy = row["elite_expectancy_r"]
                profit_factor = row["elite_profit_factor"]

            rows.append(
                {
                    "symbol": row["symbol"],
                    "candidate": candidate,
                    "trades": trades,
                    "win_rate": win_rate,
                    "expectancy_r": expectancy,
                    "profit_factor": profit_factor,
                }
            )

        candidate_summary = pd.DataFrame(rows)
        columns = list(candidate_summary.columns)
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for _, row in candidate_summary.iterrows():
            lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
        body = "\n".join(lines)

    path.write_text(
        f"""# Best Candidate Summary

These are the current research candidates included in the latest run.

```text
current + no_vwap_exit = more active baseline candidate
quality_entry + no_vwap_exit = more selective quality candidate
market_confirmed + no_vwap_exit = baseline candidate with SPY market confirmation
quality_entry_market_confirmed + no_vwap_exit = quality candidate with SPY market confirmation
setup_b_short + no_vwap_exit = bearish baseline candidate
setup_b_quality_short + no_vwap_exit = bearish quality candidate
full_session + no_vwap_exit = regular-session baseline candidate without the opening-range break requirement
quality_full_session + no_vwap_exit = regular-session quality candidate without the opening-range break requirement
setup_b_full_session + no_vwap_exit = regular-session bearish candidate without the opening-range break requirement
setup_b_quality_full_session + no_vwap_exit = regular-session bearish quality candidate without the opening-range break requirement
```

These are still research candidates, not live-trading rules.

{body}
""",
        encoding="utf-8",
    )


def write_candidate_selection_report(summary: pd.DataFrame, path: Path, min_approved_trades: int) -> None:
    """Choose the best passing candidate per symbol."""

    path.parent.mkdir(parents=True, exist_ok=True)

    if summary.empty:
        body = "No candidate results were available."
    else:
        candidate_rows = []
        for _, row in summary.iterrows():
            if use_baseline_candidate_metrics(row["variant"]):
                trades = row["baseline_trades"]
                expectancy = row["baseline_expectancy_r"]
                profit_factor = row["baseline_profit_factor"]
                win_rate = row["baseline_win_rate"]
            else:
                trades = row["elite_trades"]
                expectancy = row["elite_expectancy_r"]
                profit_factor = row["elite_profit_factor"]
                win_rate = row["elite_win_rate"]

            profit_factor_value = 999.0 if profit_factor == "inf" else float(profit_factor)
            candidate_rows.append(
                {
                    "symbol": row["symbol"],
                    "candidate": f"{row['variant']} + {row['exit_profile']}",
                    "trades": int(trades),
                    "win_rate": win_rate,
                    "expectancy_r": float(expectancy),
                    "profit_factor": profit_factor,
                    "passes": float(expectancy) > 0 and profit_factor_value > 1,
                }
            )

        candidates = pd.DataFrame(candidate_rows)
        selected_rows = []
        for symbol, group in candidates.groupby("symbol"):
            passing = group[group["passes"]]
            if passing.empty:
                best = group.sort_values("expectancy_r", ascending=False).iloc[0]
                status = "reject"
            else:
                approved = passing[passing["trades"] >= min_approved_trades]
                if approved.empty:
                    best = passing.sort_values("expectancy_r", ascending=False).iloc[0]
                    status = "watch_more"
                else:
                    # A higher expectancy from a tiny sample should not replace
                    # a candidate that has already reached the confidence floor.
                    best = approved.sort_values("expectancy_r", ascending=False).iloc[0]
                    status = "approved"

            selected_rows.append(
                {
                    "symbol": symbol,
                    "status": status,
                    "selected_candidate": best["candidate"],
                    "trades": best["trades"],
                    "win_rate": best["win_rate"],
                    "expectancy_r": round(float(best["expectancy_r"]), 4),
                    "profit_factor": best["profit_factor"],
                }
            )

        status_order = {"approved": 0, "watch_more": 1, "reject": 2}
        selected = pd.DataFrame(selected_rows)
        selected["status_order"] = selected["status"].map(status_order)
        selected = selected.sort_values(["status_order", "expectancy_r"], ascending=[True, False])
        selected = selected.drop(columns=["status_order"])
        columns = list(selected.columns)
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for _, row in selected.iterrows():
            lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
        body = "\n".join(lines)

    path.write_text(
        f"""# Candidate Selection Report

This report selects the best passing candidate per symbol and applies a
sample-size confidence filter.

Math pass rule:

```text
expectancy_r > 0
profit_factor > 1
```

Confidence rule:

```text
approved = passes math rule and trades >= {min_approved_trades}
watch_more = passes math rule but trades < {min_approved_trades}
reject = fails math rule
```

Symbols marked `approved` are the current research candidates for this run.
Symbols marked `watch_more` are promising but need more historical trades.
Symbols marked `reject` should not be treated as candidates for this setup yet.

{body}
""",
        encoding="utf-8",
    )


def write_preset_reports(
    summary: pd.DataFrame,
    output_dir: Path,
    preset_name: str,
    min_approved_trades: int,
) -> None:
    """Save preset-labeled reports so Setup A/B research does not get mixed.

    The generic report names are still useful for the most recent run. These
    preset copies preserve the latest result for a named research family, such
    as ``setup_b``.
    """

    prefix = preset_name.lower()
    csv_path = output_dir / f"{prefix}_watchlist_backtest_summary.csv"
    md_path = output_dir / f"{prefix}_watchlist_backtest_summary.md"
    best_path = output_dir / f"{prefix}_candidate_summary.md"
    selection_path = output_dir / f"{prefix}_candidate_selection_report.md"

    summary.to_csv(csv_path, index=False)
    write_combined_markdown(summary, md_path)
    write_best_candidates_report(summary, best_path)
    write_candidate_selection_report(summary, selection_path, min_approved_trades)

    print(f"Saved preset CSV summary: {csv_path}")
    print(f"Saved preset Markdown summary: {md_path}")
    print(f"Saved preset candidate summary: {best_path}")
    print(f"Saved preset candidate selection report: {selection_path}")


def normalize_metric(value):
    """Keep CSV output readable when metrics include infinity."""

    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return value


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    data_client = None if args.reuse_csv else build_data_client()
    if args.chart_only:
        if args.reuse_csv:
            print("Chart-only refresh skipped because --reuse-csv was supplied.")
            return
        for symbol in [item.upper() for item in args.symbols]:
            fetch_chart_only_timeframes(data_client, symbol, args, output_dir)
        print("Chart-only Webull refresh complete.")
        return
    results = []
    candidate_pairs = None
    if args.candidate_preset:
        candidate_pairs = CANDIDATE_PRESETS[args.candidate_preset]

    for symbol in [item.upper() for item in args.symbols]:
        try:
            if args.reuse_csv:
                entry_csv = preferred_candle_path(output_dir, symbol, "M30")
                exit_csv = preferred_candle_path(output_dir, symbol, "M5")
                print(f"\n=== {symbol}: reusing {entry_csv} and {exit_csv} ===", flush=True)
            else:
                print(f"\n=== {symbol}: fetching M30 entry candles ===", flush=True)
                entry_csv = fetch_and_save(
                    data_client,
                    symbol,
                    "M30",
                    args.entry_count,
                    args.entry_pages,
                    args.pause,
                    output_dir,
                )
                print(f"Saved {entry_csv}", flush=True)
                time.sleep(args.pause)

                print(f"=== {symbol}: fetching M5 exit candles ===", flush=True)
                exit_csv = fetch_and_save(
                    data_client,
                    symbol,
                    "M5",
                    args.exit_count,
                    args.exit_pages,
                    args.pause,
                    output_dir,
                )
                print(f"Saved {exit_csv}", flush=True)
                time.sleep(args.pause)
                fetch_chart_only_timeframes(data_client, symbol, args, output_dir)

            pairs = candidate_pairs
            if pairs is None:
                pairs = [(variant, exit_profile) for variant in args.variants for exit_profile in args.exit_profiles]

            for variant, exit_profile_name in pairs:
                market_csv = None
                if variant in MARKET_CONFIRMED_VARIANTS:
                    market_csv = preferred_candle_path(output_dir, args.market_regime_symbol.upper(), "M30")
                    if not market_csv.exists():
                        raise FileNotFoundError(
                            f"Market regime CSV not found: {market_csv}. "
                            "Fetch that symbol first or use --reuse-csv after it exists."
                        )
                print(f"=== {symbol}: running {variant} / {exit_profile_name} backtest ===", flush=True)
                result = run_symbol_backtest(
                    symbol,
                    entry_csv,
                    exit_csv,
                    output_dir,
                    variant,
                    exit_profile_name,
                    market_csv=market_csv,
                    market_symbol=args.market_regime_symbol.upper(),
                )
                results.append({key: normalize_metric(value) for key, value in result.items()})
                print(
                    f"{symbol} {variant} {exit_profile_name}: "
                    f"baseline trades={result['baseline_trades']} "
                    f"expectancy={result['baseline_expectancy_r']}R; "
                    f"elite trades={result['elite_trades']} "
                    f"expectancy={result['elite_expectancy_r']}R",
                    flush=True,
                )
        except Exception as exc:
            print(f"{symbol}: skipped after error: {exc}", flush=True)
            time.sleep(args.pause * 2)

    summary = pd.DataFrame(results)
    csv_path = output_dir / "webull_watchlist_backtest_summary.csv"
    md_path = output_dir / "webull_watchlist_backtest_summary.md"
    best_path = output_dir / "best_candidate_summary.md"
    selection_path = output_dir / "candidate_selection_report.md"
    summary.to_csv(csv_path, index=False)
    write_combined_markdown(summary, md_path)
    write_best_candidates_report(summary, best_path)
    write_candidate_selection_report(summary, selection_path, args.min_approved_trades)

    print(f"\nSaved combined CSV summary: {csv_path}")
    print(f"Saved combined Markdown summary: {md_path}")
    print(f"Saved best candidate summary: {best_path}")
    print(f"Saved candidate selection report: {selection_path}")

    if args.candidate_preset:
        write_preset_reports(summary, output_dir, args.candidate_preset, args.min_approved_trades)


if __name__ == "__main__":
    main()
