"""Backtest Gap Fill / Gap Fade as a Strategy Vault candidate.

This is research-only. It reuses saved Webull daily and intraday candles, then
writes reports so we can decide whether gap fades deserve deeper development.
It does not create scanner candidates, import paper trades, place orders, or
connect to broker execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_exit_reason_breakdown, calculate_metrics
from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from data.market_data import load_candles_from_csv, save_candles
from indicators.session import add_session_columns
from indicators.trend import add_core_indicators
from run_playbook import markdown_table
from strategies.gap_fill_fade import add_gap_fill_fade_signals


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Gap Fill / Gap Fade research strategy.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to test from saved Webull CSVs.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--entry-timeframe", default="M30", help="Saved Webull entry timeframe.")
    parser.add_argument("--exit-timeframe", default="M5", help="Saved Webull exit-management timeframe.")
    parser.add_argument("--daily-timeframe", default="D", help="Saved Webull daily timeframe.")
    parser.add_argument("--reward-multiple-floor", type=float, default=0.70, help="Minimum target distance in R.")
    parser.add_argument("--min-quality-score", type=int, default=4, help="Minimum gap-fade quality score.")
    parser.add_argument("--min-gap-pct", type=float, default=0.004)
    parser.add_argument("--max-gap-pct", type=float, default=0.040)
    parser.add_argument("--min-relative-volume", type=float, default=0.70)
    parser.add_argument("--max-relative-volume", type=float, default=2.80)
    parser.add_argument("--promotion-min-trades", type=int, default=10)
    parser.add_argument("--promotion-min-expectancy-r", type=float, default=0.10)
    parser.add_argument("--promotion-min-profit-factor", type=float, default=1.30)
    parser.add_argument("--promotion-max-drawdown-r", type=float, default=-3.0)
    return parser.parse_args()


def daily_prior_close_by_session(daily_candles: pd.DataFrame) -> dict[Any, float]:
    """Return prior daily close keyed by local session date."""

    daily = add_session_columns(daily_candles, STRATEGY).copy()
    daily["prior_close"] = daily["close"].shift(1)
    return {
        row["session_date"]: float(row["prior_close"])
        for _, row in daily.iterrows()
        if pd.notna(row["prior_close"])
    }


def attach_gap_context(entry: pd.DataFrame, daily_candles: pd.DataFrame) -> pd.DataFrame:
    """Attach prior close and regular-session open to entry candles."""

    result = entry.copy()
    prior_close = daily_prior_close_by_session(daily_candles)
    result["prior_close"] = result["session_date"].map(prior_close)
    regular = result[result["regular_session"]]
    session_opens = regular.groupby("session_date")["open"].first()
    result["session_open"] = result["session_date"].map(session_opens)
    return result


def add_research_columns(
    entry: pd.DataFrame,
    exit_candles: pd.DataFrame,
    daily_candles: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add indicators, session context, gap context, and fade signals."""

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
    entry = attach_gap_context(entry, daily_candles)
    return add_gap_fill_fade_signals(entry, STRATEGY), exit_candles


def find_gap_fade_exit(
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
    """Find the first 5m stop, prior-close target, or end-of-day exit."""

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
                exit_reason = "gap_fade_stop_5m"
            elif row["high"] >= target:
                exit_price = target
                exit_reason = "gap_fill_target_5m"
        else:
            if row["high"] >= stop:
                exit_price = stop
                exit_reason = "gap_fade_stop_5m"
            elif row["low"] <= target:
                exit_price = target
                exit_reason = "gap_fill_target_5m"

        if exit_price is None and bool(row.get("force_exit_window", False)):
            exit_price = row["close"]
            exit_reason = "end_of_day_exit"

        if exit_price is not None:
            r_result = ((exit_price - entry) / risk_per_share) if direction == "long" else ((entry - exit_price) / risk_per_share)
            return timestamp, row, float(exit_price), float(r_result), str(exit_reason)

    r_result = ((last_row["close"] - entry) / risk_per_share) if direction == "long" else ((entry - last_row["close"]) / risk_per_share)
    return last_timestamp, last_row, float(last_row["close"]), float(r_result), "last_available_exit"


def simulate_direction(
    entry_candles: pd.DataFrame,
    exit_candles: pd.DataFrame,
    *,
    direction: str,
    signal_column: str,
    args: argparse.Namespace,
) -> pd.DataFrame:
    """Simulate one gap-fade direction."""

    trades: list[dict[str, Any]] = []
    active_until = None
    trades_today = 0
    daily_r = 0.0
    consecutive_losses = 0
    current_day = None

    for index, (timestamp, row) in enumerate(entry_candles.iterrows()):
        session_day = row["session_date"]
        if session_day != current_day:
            current_day = session_day
            trades_today = 0
            daily_r = 0.0
            consecutive_losses = 0

        if active_until is not None and timestamp <= active_until:
            continue
        if index >= len(entry_candles) - 1 or not bool(row.get(signal_column, False)):
            continue

        quality_score = int(row.get("gap_fade_quality_score", 0) or 0)
        relative_volume = float(row.get("gap_fade_relative_volume", 0) or 0)
        gap_pct = float(row.get("gap_fade_gap_pct", 0) or 0)
        abs_gap_pct = abs(gap_pct)
        if (
            quality_score < args.min_quality_score
            or abs_gap_pct < args.min_gap_pct
            or abs_gap_pct > args.max_gap_pct
            or relative_volume < args.min_relative_volume
            or relative_volume > args.max_relative_volume
        ):
            continue
        if (
            trades_today >= STRATEGY.max_trades_per_day
            or consecutive_losses >= STRATEGY.max_consecutive_losses
            or daily_r <= STRATEGY.max_daily_loss_r
        ):
            continue

        entry = float(row["close"])
        target = float(row["prior_close"])
        if direction == "long":
            stop = min(float(row["low"]), float(row["session_open"])) * (1 - STRATEGY.stop_buffer_pct)
            risk_per_share = entry - stop
            reward_multiple = (target - entry) / risk_per_share if risk_per_share > 0 else 0.0
        else:
            stop = max(float(row["high"]), float(row["session_open"])) * (1 + STRATEGY.stop_buffer_pct)
            risk_per_share = stop - entry
            reward_multiple = (entry - target) / risk_per_share if risk_per_share > 0 else 0.0

        if risk_per_share <= 0 or reward_multiple < args.reward_multiple_floor:
            continue

        exit_result = find_gap_fade_exit(
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
            {
                "symbol": str(row["symbol"]),
                "direction": direction,
                "entry_time": str(timestamp),
                "exit_time": str(exit_time),
                "setup_type": "gap_fill_fade",
                "signal_column": signal_column,
                "quality_grade": str(row.get("gap_fade_quality_grade", "")),
                "quality_score": quality_score,
                "entry": round(entry, 4),
                "stop": round(stop, 4),
                "target": round(target, 4),
                "risk_per_share": round(risk_per_share, 4),
                "reward_multiple": round(reward_multiple, 4),
                "exit_price": round(exit_price, 4),
                "r_result": round(r_result, 4),
                "exit_reason": exit_reason,
                "close": round(float(exit_row["close"]), 4),
                "vwap": round(float(exit_row["vwap"]), 4),
                "session_open": round(float(row["session_open"]), 4),
                "prior_close": round(float(row["prior_close"]), 4),
                "gap_pct": round(gap_pct, 4),
                "relative_volume": round(relative_volume, 4),
            }
        )
        active_until = exit_time
        trades_today += 1
        daily_r += r_result
        consecutive_losses = consecutive_losses + 1 if r_result < 0 else 0

    return pd.DataFrame(trades)


def finite_number(value: Any) -> float:
    """Return finite numeric values for JSON/dashboard summaries."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def research_status(metrics: dict[str, Any]) -> str:
    """Classify whether a gap-fade row deserves deeper research."""

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
    """Return pass/fail review for a gap-fade row."""

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
    """Run gap-fade research for one symbol."""

    entry_csv = output_dir / f"webull_{symbol}_{args.entry_timeframe}_candles.csv"
    exit_csv = output_dir / f"webull_{symbol}_{args.exit_timeframe}_candles.csv"
    daily_csv = output_dir / f"webull_{symbol}_{args.daily_timeframe}_candles.csv"
    if not entry_csv.exists() or not exit_csv.exists() or not daily_csv.exists():
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
    daily = load_candles_from_csv(daily_csv, symbol)
    entry, exits = add_research_columns(entry, exits, daily)
    output_stem = f"{symbol}_gap_fill_fade_{args.entry_timeframe}_entry_{args.exit_timeframe}_exit"
    save_candles(entry, output_dir / f"{output_stem}_entry_candles.csv")
    save_candles(exits, output_dir / f"{output_stem}_exit_candles.csv")

    long_trades = simulate_direction(entry, exits, direction="long", signal_column="gap_fade_long_signal", args=args)
    short_trades = simulate_direction(entry, exits, direction="short", signal_column="gap_fade_short_signal", args=args)
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
        "strategy_id": "gap_fill_fade",
        "generated_from": "saved Webull daily and intraday CSV candles",
        "entry_timeframe": args.entry_timeframe,
        "exit_timeframe": args.exit_timeframe,
        "daily_timeframe": args.daily_timeframe,
        "reward_multiple_floor": args.reward_multiple_floor,
        "filters": {
            "min_quality_score": args.min_quality_score,
            "min_gap_pct": args.min_gap_pct,
            "max_gap_pct": args.max_gap_pct,
            "min_relative_volume": args.min_relative_volume,
            "max_relative_volume": args.max_relative_volume,
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
    (output_dir / "gap_fill_fade.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary.to_csv(output_dir / "gap_fill_fade_summary.csv", index=False)
    all_trades.to_csv(output_dir / "gap_fill_fade_trades.csv", index=False)
    (output_dir / "gap_fill_fade.md").write_text(
        f"""# Gap Fill / Gap Fade Research

This report tests the gap-fill mean-reversion strategy in the Strategy Vault.

Important: this is research/backtesting only. It does not create scanner
candidates, import paper trades, place broker orders, create broker alerts, or
bypass the paper gate.

## Rules Tested

```text
Entry timeframe: {args.entry_timeframe}
Exit timeframe: {args.exit_timeframe}
Daily context: {args.daily_timeframe} prior close
Gap-up short trigger: open gaps above prior close, price rotates below VWAP/session open, target prior close
Gap-down long trigger: open gaps below prior close, price rotates above VWAP/session open, target prior close
Stop: signal candle / session open plus buffer
Minimum target distance: {args.reward_multiple_floor}R
Minimum quality score: {args.min_quality_score}
Gap band: {args.min_gap_pct:.4%} to {args.max_gap_pct:.4%}
Relative volume band: {args.min_relative_volume} to {args.max_relative_volume}
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
logs/gap_fill_fade.json
logs/gap_fill_fade_summary.csv
logs/gap_fill_fade_trades.csv
logs/gap_fill_fade.md
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
    print(f"Saved gap fade summary: {args.output_dir / 'gap_fill_fade_summary.csv'}")
    print(f"Saved gap fade report: {args.output_dir / 'gap_fill_fade.md'}")


if __name__ == "__main__":
    main()
