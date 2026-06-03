"""Backtest Opening Range Failure as a Strategy Vault candidate.

This is research-only. It reuses saved Webull candles and writes reports so we
can decide whether OR failure deserves deeper development. It does not create
scanner candidates, import paper trades, place orders, or connect to broker
execution.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_exit_reason_breakdown, calculate_metrics
from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from data.market_data import load_candles_from_csv, save_candles
from indicators.multitimeframe import add_higher_timeframe_bias
from indicators.session import add_opening_range, add_session_columns
from indicators.trend import add_core_indicators
from run_playbook import markdown_table
from strategies.opening_range_failure import add_opening_range_failure_signals


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


@dataclass
class OpeningRangeFailureTrade:
    """One simulated opening-range failure trade."""

    symbol: str
    direction: str
    entry_time: str
    exit_time: str
    setup_type: str
    signal_column: str
    quality_grade: str
    quality_score: int
    entry: float
    stop: float
    target: float
    risk_per_share: float
    exit_price: float
    r_result: float
    exit_reason: str
    close: float
    vwap: float
    opening_range_high: float
    opening_range_low: float
    opening_range_midpoint: float
    relative_volume: float
    trend_gap_pct: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Opening Range Failure research strategy.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to test from saved Webull CSVs.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--entry-timeframe", default="M30", help="Saved Webull entry timeframe.")
    parser.add_argument("--exit-timeframe", default="M5", help="Saved Webull exit-management timeframe.")
    parser.add_argument("--reward-multiple-floor", type=float, default=0.50, help="Minimum target distance in R.")
    parser.add_argument("--min-quality-score", type=int, default=4, help="Minimum OR failure quality score.")
    parser.add_argument("--min-relative-volume", type=float, default=0.50)
    parser.add_argument("--max-relative-volume", type=float, default=1.80)
    parser.add_argument("--max-trend-gap-pct", type=float, default=0.0060)
    parser.add_argument("--promotion-min-trades", type=int, default=10)
    parser.add_argument("--promotion-min-expectancy-r", type=float, default=0.10)
    parser.add_argument("--promotion-min-profit-factor", type=float, default=1.30)
    parser.add_argument("--promotion-max-drawdown-r", type=float, default=-3.0)
    return parser.parse_args()


def add_research_columns(entry: pd.DataFrame, exit_candles: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add indicators, session context, opening range, and OR failure signals."""

    entry = add_core_indicators(
        entry,
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
    entry = add_session_columns(entry, STRATEGY)
    exit_candles = add_session_columns(exit_candles, STRATEGY)
    entry = add_opening_range(entry, exit_candles, STRATEGY)
    entry = add_higher_timeframe_bias(
        entry,
        thesis_interval=STRATEGY.thesis_interval,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    return add_opening_range_failure_signals(entry, STRATEGY), exit_candles


def find_failure_exit(
    *,
    direction: str,
    entry_time: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    risk_per_share: float,
    session_date: Any,
    exit_candles: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Series, float, float, str] | None:
    """Find the first 5m stop, target, or end-of-day exit."""

    future = exit_candles[
        (exit_candles.index > entry_time)
        & (exit_candles["session_date"] == session_date)
        & (exit_candles["regular_session"])
    ]
    if future.empty:
        return None

    last_timestamp = future.index[-1]
    last_row = future.iloc[-1]
    for timestamp, row in future.iterrows():
        exit_price = None
        exit_reason = None
        if direction == "long":
            if row["low"] <= stop:
                exit_price = stop
                exit_reason = "or_failure_stop_5m"
            elif row["high"] >= target:
                exit_price = target
                exit_reason = "or_failure_target_5m"
        else:
            if row["high"] >= stop:
                exit_price = stop
                exit_reason = "or_failure_stop_5m"
            elif row["low"] <= target:
                exit_price = target
                exit_reason = "or_failure_target_5m"

        if exit_price is None and bool(row.get("force_exit_window", False)):
            exit_price = row["close"]
            exit_reason = "end_of_day_exit"

        if exit_price is not None:
            r_result = ((exit_price - entry) / risk_per_share) if direction == "long" else ((entry - exit_price) / risk_per_share)
            return timestamp, row, float(exit_price), float(r_result), str(exit_reason)

    r_result = ((last_row["close"] - entry) / risk_per_share) if direction == "long" else ((entry - last_row["close"]) / risk_per_share)
    return last_timestamp, last_row, float(last_row["close"]), float(r_result), "last_available_exit"


def target_for_row(row: pd.Series, direction: str) -> float:
    """Use the more conservative of VWAP and opening-range midpoint as target."""

    midpoint = float(row["opening_range_midpoint"])
    vwap = float(row["vwap"])
    entry = float(row["close"])
    if direction == "long":
        candidates = [value for value in [midpoint, vwap] if value > entry]
        return min(candidates) if candidates else max(midpoint, vwap)
    candidates = [value for value in [midpoint, vwap] if value < entry]
    return max(candidates) if candidates else min(midpoint, vwap)


def simulate_direction(
    entry_candles: pd.DataFrame,
    exit_candles: pd.DataFrame,
    *,
    direction: str,
    signal_column: str,
    args: argparse.Namespace,
) -> pd.DataFrame:
    """Simulate one OR failure direction."""

    trades: list[OpeningRangeFailureTrade] = []
    active_until = None
    trades_today = 0
    daily_r = 0.0
    consecutive_losses = 0
    current_day = None
    rows = list(entry_candles.iterrows())

    for index, (timestamp, row) in enumerate(rows):
        session_day = row["session_date"]
        if session_day != current_day:
            current_day = session_day
            trades_today = 0
            daily_r = 0.0
            consecutive_losses = 0

        if active_until is not None and timestamp <= active_until:
            continue
        if index >= len(rows) - 1 or not bool(row.get(signal_column, False)):
            continue

        quality_score = int(row.get("or_failure_quality_score", 0) or 0)
        relative_volume = float(row.get("or_failure_relative_volume", 0) or 0)
        trend_gap_pct = float(row.get("or_failure_trend_gap_pct", 0) or 0)
        if (
            quality_score < args.min_quality_score
            or relative_volume < args.min_relative_volume
            or relative_volume > args.max_relative_volume
            or trend_gap_pct > args.max_trend_gap_pct
        ):
            continue
        if (
            trades_today >= STRATEGY.max_trades_per_day
            or consecutive_losses >= STRATEGY.max_consecutive_losses
            or daily_r <= STRATEGY.max_daily_loss_r
        ):
            continue

        entry = float(row["close"])
        if direction == "long":
            stop = float(row["low"]) * (1 - STRATEGY.stop_buffer_pct)
            target = target_for_row(row, direction)
            risk_per_share = entry - stop
            reward_per_share = target - entry
        else:
            stop = float(row["high"]) * (1 + STRATEGY.stop_buffer_pct)
            target = target_for_row(row, direction)
            risk_per_share = stop - entry
            reward_per_share = entry - target

        if risk_per_share <= 0 or reward_per_share <= 0:
            continue
        if reward_per_share / risk_per_share < args.reward_multiple_floor:
            continue

        exit_result = find_failure_exit(
            direction=direction,
            entry_time=timestamp,
            entry=entry,
            stop=stop,
            target=target,
            risk_per_share=risk_per_share,
            session_date=session_day,
            exit_candles=exit_candles,
        )
        if exit_result is None:
            continue
        exit_time, exit_row, exit_price, r_result, exit_reason = exit_result
        trades.append(
            OpeningRangeFailureTrade(
                symbol=str(row["symbol"]),
                direction=direction,
                entry_time=str(timestamp),
                exit_time=str(exit_time),
                setup_type="opening_range_failure",
                signal_column=signal_column,
                quality_grade=str(row.get("or_failure_quality_grade", "")),
                quality_score=quality_score,
                entry=round(entry, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_per_share=round(risk_per_share, 4),
                exit_price=round(exit_price, 4),
                r_result=round(r_result, 4),
                exit_reason=exit_reason,
                close=round(float(exit_row["close"]), 4),
                vwap=round(float(exit_row["vwap"]), 4),
                opening_range_high=round(float(row["opening_range_high"]), 4),
                opening_range_low=round(float(row["opening_range_low"]), 4),
                opening_range_midpoint=round(float(row["opening_range_midpoint"]), 4),
                relative_volume=round(relative_volume, 4),
                trend_gap_pct=round(trend_gap_pct, 4),
            )
        )
        active_until = exit_time
        trades_today += 1
        daily_r += r_result
        consecutive_losses = consecutive_losses + 1 if r_result < 0 else 0

    return pd.DataFrame([asdict(trade) for trade in trades])


def finite_number(value: Any) -> float:
    """Return finite numeric values for JSON/dashboard summaries."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def research_status(metrics: dict[str, Any]) -> str:
    """Classify whether an OR failure row deserves deeper research."""

    trades = int(metrics.get("trades", 0) or 0)
    expectancy = float(metrics.get("expectancy_r", 0) or 0)
    profit_factor = finite_number(metrics.get("profit_factor", 0))
    if trades < 8:
        return "too_few_trades"
    if expectancy > 0.10 and profit_factor >= 1.30:
        return "promising"
    if expectancy > 0 and profit_factor > 1.0:
        return "watch_more"
    return "not_ready"


def promotion_review_status(metrics: dict[str, Any], args: argparse.Namespace) -> tuple[str, str]:
    """Return pass/fail review for an OR failure row."""

    trades = int(metrics.get("trades", 0) or 0)
    expectancy = float(metrics.get("expectancy_r", 0) or 0)
    profit_factor = finite_number(metrics.get("profit_factor", 0))
    max_drawdown = float(metrics.get("max_drawdown_r", 0) or 0)
    blockers = []
    if trades < args.promotion_min_trades:
        blockers.append(f"needs {args.promotion_min_trades - trades} more trades")
    if expectancy < args.promotion_min_expectancy_r:
        blockers.append(f"expectancy below {args.promotion_min_expectancy_r:.2f}R")
    if profit_factor < args.promotion_min_profit_factor:
        blockers.append(f"profit factor below {args.promotion_min_profit_factor:.2f}")
    if max_drawdown < args.promotion_max_drawdown_r:
        blockers.append(f"drawdown worse than {args.promotion_max_drawdown_r:.1f}R")
    if blockers:
        return "needs_more_evidence", "; ".join(blockers)
    return "passes_tightened_research", "Passed first-review thresholds. Still requires walk-forward, shadow, and forward evidence."


def summarize_trades(symbol: str, direction: str, trades: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    """Build one summary row."""

    metrics = calculate_metrics(trades)
    review_status, review_reason = promotion_review_status(metrics, args)
    return {
        "symbol": symbol,
        "direction": direction,
        "trades": metrics["trades"],
        "win_rate": metrics["win_rate"],
        "expectancy_r": metrics["expectancy_r"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown_r": metrics["max_drawdown_r"],
        "research_status": research_status(metrics),
        "tightened_review": review_status,
        "review_reason": review_reason,
    }


def run_symbol(symbol: str, output_dir: Path, args: argparse.Namespace) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Run OR failure research for one symbol."""

    entry_csv = output_dir / f"webull_{symbol}_{args.entry_timeframe}_candles.csv"
    exit_csv = output_dir / f"webull_{symbol}_{args.exit_timeframe}_candles.csv"
    if not entry_csv.exists() or not exit_csv.exists():
        return pd.DataFrame(), [
            {
                "symbol": symbol,
                "direction": "both",
                "trades": 0,
                "win_rate": 0.0,
                "expectancy_r": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_r": 0.0,
                "research_status": "missing_candles",
            }
        ]

    entry = load_candles_from_csv(entry_csv, symbol)
    exits = load_candles_from_csv(exit_csv, symbol)
    entry, exits = add_research_columns(entry, exits)
    output_stem = f"{symbol}_opening_range_failure_{args.entry_timeframe}_entry_{args.exit_timeframe}_exit"
    save_candles(entry, output_dir / f"{output_stem}_entry_candles.csv")
    save_candles(exits, output_dir / f"{output_stem}_exit_candles.csv")

    long_trades = simulate_direction(entry, exits, direction="long", signal_column="or_failure_long_signal", args=args)
    short_trades = simulate_direction(entry, exits, direction="short", signal_column="or_failure_short_signal", args=args)
    long_trades.to_csv(output_dir / f"{output_stem}_long_trades.csv", index=False)
    short_trades.to_csv(output_dir / f"{output_stem}_short_trades.csv", index=False)
    all_trades = pd.concat([long_trades, short_trades], ignore_index=True)
    all_trades.to_csv(output_dir / f"{output_stem}_all_trades.csv", index=False)
    calculate_exit_reason_breakdown(all_trades).to_csv(output_dir / f"{output_stem}_by_exit_reason.csv", index=False)

    return all_trades, [
        summarize_trades(symbol, "long", long_trades, args),
        summarize_trades(symbol, "short", short_trades, args),
        summarize_trades(symbol, "combined", all_trades, args),
    ]


def write_report(output_dir: Path, summary: pd.DataFrame, all_trades: pd.DataFrame, args: argparse.Namespace) -> None:
    """Write Markdown and JSON Strategy Vault evidence reports."""

    promising = summary[summary["research_status"].isin(["promising", "watch_more"])].copy() if not summary.empty else pd.DataFrame()
    tightened_pass = summary[summary["tightened_review"] == "passes_tightened_research"].copy() if not summary.empty else pd.DataFrame()
    best = summary.sort_values(["expectancy_r", "trades"], ascending=[False, False]).head(8) if not summary.empty else pd.DataFrame()
    payload = {
        "strategy_id": "opening_range_failure",
        "generated_from": "saved Webull CSV candles",
        "entry_timeframe": args.entry_timeframe,
        "exit_timeframe": args.exit_timeframe,
        "reward_multiple_floor": args.reward_multiple_floor,
        "filters": {
            "min_quality_score": args.min_quality_score,
            "min_relative_volume": args.min_relative_volume,
            "max_relative_volume": args.max_relative_volume,
            "max_trend_gap_pct": args.max_trend_gap_pct,
        },
        "promotion_thresholds": {
            "min_trades": args.promotion_min_trades,
            "min_expectancy_r": args.promotion_min_expectancy_r,
            "min_profit_factor": args.promotion_min_profit_factor,
            "max_drawdown_r": args.promotion_max_drawdown_r,
        },
        "summary_rows": int(len(summary)),
        "total_trades": int(len(all_trades)),
        "promising_rows": int(len(promising)),
        "tightened_pass_rows": int(len(tightened_pass)),
        "best_rows": best.to_dict("records") if not best.empty else [],
        "guardrail": "Research/backtesting only. Does not approve paper trades or alter scanner gates.",
    }
    (output_dir / "opening_range_failure.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary.to_csv(output_dir / "opening_range_failure_summary.csv", index=False)
    all_trades.to_csv(output_dir / "opening_range_failure_trades.csv", index=False)
    (output_dir / "opening_range_failure.md").write_text(
        f"""# Opening Range Failure Research

This report tests the failed-breakout strategy in the Strategy Vault.

Important: this is research/backtesting only. It does not create scanner
candidates, import paper trades, place broker orders, create broker alerts, or
bypass the paper gate.

## Rules Tested

```text
Entry timeframe: {args.entry_timeframe}
Exit timeframe: {args.exit_timeframe}
Short trigger: high breaks above OR high, close reclaims below OR high
Long trigger: low breaks below OR low, close reclaims above OR low
Target: conservative VWAP / opening-range midpoint mean
Stop: signal candle extreme plus buffer
Minimum target distance: {args.reward_multiple_floor}R
Minimum quality score: {args.min_quality_score}
Relative volume band: {args.min_relative_volume} to {args.max_relative_volume}
Maximum EMA 9/21 trend gap: {args.max_trend_gap_pct:.4%}
```

## Summary

{markdown_table(summary)}

## Best Rows

{markdown_table(best)}

## Promising / Watch-More Rows

{markdown_table(promising)}

## Tightened Pass Rows

{markdown_table(tightened_pass)}

## Files

```text
logs/opening_range_failure.json
logs/opening_range_failure_summary.csv
logs/opening_range_failure_trades.csv
logs/opening_range_failure.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_trade_frames = []
    summary_rows = []
    for symbol in [symbol.upper() for symbol in args.symbols]:
        trades, rows = run_symbol(symbol, args.output_dir, args)
        if not trades.empty:
            all_trade_frames.append(trades)
        summary_rows.extend(rows)

    summary = pd.DataFrame(summary_rows)
    all_trades = pd.concat(all_trade_frames, ignore_index=True) if all_trade_frames else pd.DataFrame()
    write_report(args.output_dir, summary, all_trades, args)
    print(f"Saved OR failure summary: {args.output_dir / 'opening_range_failure_summary.csv'}")
    print(f"Saved OR failure report: {args.output_dir / 'opening_range_failure.md'}")


if __name__ == "__main__":
    main()
