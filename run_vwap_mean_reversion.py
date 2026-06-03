"""Backtest VWAP mean reversion as a strategy-vault candidate.

This is research-only. It reuses saved Webull candles and writes reports so we
can decide whether mean reversion deserves deeper development. It does not
create scanner candidates, import paper trades, place orders, or connect to
broker execution.
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
from strategies.vwap_mean_reversion import add_vwap_mean_reversion_signals


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


@dataclass
class MeanReversionTrade:
    """One simulated VWAP mean-reversion trade."""

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
    ema_9: float
    ema_21: float
    relative_volume: float
    vwap_gap_pct: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest VWAP mean-reversion research strategy.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to test from saved Webull CSVs.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--entry-timeframe", default="M30", help="Saved Webull entry timeframe.")
    parser.add_argument("--exit-timeframe", default="M5", help="Saved Webull exit-management timeframe.")
    parser.add_argument("--reward-multiple-floor", type=float, default=0.60, help="Minimum VWAP target distance in R.")
    return parser.parse_args()


def add_research_columns(entry: pd.DataFrame, exit_candles: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add indicators, session context, and mean-reversion signals."""

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
    return add_vwap_mean_reversion_signals(entry, STRATEGY), exit_candles


def find_mean_reversion_exit(
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
    """Find the first 5m stop, VWAP target, or end-of-day exit."""

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
                exit_reason = "mean_reversion_stop_5m"
            elif row["high"] >= target:
                exit_price = target
                exit_reason = "vwap_mean_target_5m"
        else:
            if row["high"] >= stop:
                exit_price = stop
                exit_reason = "mean_reversion_stop_5m"
            elif row["low"] <= target:
                exit_price = target
                exit_reason = "vwap_mean_target_5m"

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
    reward_multiple_floor: float,
) -> pd.DataFrame:
    """Simulate one mean-reversion direction."""

    trades: list[MeanReversionTrade] = []
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
        if (
            trades_today >= STRATEGY.max_trades_per_day
            or consecutive_losses >= STRATEGY.max_consecutive_losses
            or daily_r <= STRATEGY.max_daily_loss_r
        ):
            continue

        entry = float(row["close"])
        if direction == "long":
            stop = float(row["low"]) * (1 - STRATEGY.stop_buffer_pct)
            target = float(row["vwap"])
            risk_per_share = entry - stop
            reward_per_share = target - entry
        else:
            stop = float(row["high"]) * (1 + STRATEGY.stop_buffer_pct)
            target = float(row["vwap"])
            risk_per_share = stop - entry
            reward_per_share = entry - target

        if risk_per_share <= 0 or reward_per_share <= 0:
            continue
        if reward_per_share / risk_per_share < reward_multiple_floor:
            continue

        exit_result = find_mean_reversion_exit(
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
            MeanReversionTrade(
                symbol=str(row["symbol"]),
                direction=direction,
                entry_time=str(timestamp),
                exit_time=str(exit_time),
                setup_type="vwap_mean_reversion",
                signal_column=signal_column,
                quality_grade=str(row.get("mean_reversion_quality_grade", "")),
                quality_score=int(row.get("mean_reversion_quality_score", 0)),
                entry=round(entry, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                risk_per_share=round(risk_per_share, 4),
                exit_price=round(exit_price, 4),
                r_result=round(r_result, 4),
                exit_reason=exit_reason,
                close=round(float(exit_row["close"]), 4),
                vwap=round(float(exit_row["vwap"]), 4),
                ema_9=round(float(exit_row.get("ema_9", 0)), 4),
                ema_21=round(float(exit_row.get("ema_21", 0)), 4),
                relative_volume=round(float(row.get("mean_reversion_relative_volume", 0)), 4),
                vwap_gap_pct=round(float(row.get("mean_reversion_vwap_gap_pct", 0)), 4),
            )
        )
        active_until = exit_time
        trades_today += 1
        daily_r += r_result
        consecutive_losses = consecutive_losses + 1 if r_result < 0 else 0

    return pd.DataFrame([asdict(trade) for trade in trades])


def finite_number(value: Any) -> float:
    """Return finite numeric values for JSON/dashboard summaries."""

    if value == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def summarize_trades(symbol: str, direction: str, trades: pd.DataFrame) -> dict[str, Any]:
    """Build one summary row."""

    metrics = calculate_metrics(trades)
    return {
        "symbol": symbol,
        "direction": direction,
        "trades": metrics["trades"],
        "win_rate": metrics["win_rate"],
        "expectancy_r": metrics["expectancy_r"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown_r": metrics["max_drawdown_r"],
        "research_status": research_status(metrics),
    }


def research_status(metrics: dict[str, Any]) -> str:
    """Classify whether a mean-reversion result deserves deeper research."""

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


def run_symbol(symbol: str, output_dir: Path, args: argparse.Namespace) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Run mean-reversion research for one symbol."""

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
    output_stem = f"{symbol}_vwap_mean_reversion_{args.entry_timeframe}_entry_{args.exit_timeframe}_exit"
    save_candles(entry, output_dir / f"{output_stem}_entry_candles.csv")
    save_candles(exits, output_dir / f"{output_stem}_exit_candles.csv")

    long_trades = simulate_direction(
        entry,
        exits,
        direction="long",
        signal_column="mean_reversion_long_signal",
        reward_multiple_floor=args.reward_multiple_floor,
    )
    short_trades = simulate_direction(
        entry,
        exits,
        direction="short",
        signal_column="mean_reversion_short_signal",
        reward_multiple_floor=args.reward_multiple_floor,
    )
    long_trades.to_csv(output_dir / f"{output_stem}_long_trades.csv", index=False)
    short_trades.to_csv(output_dir / f"{output_stem}_short_trades.csv", index=False)
    all_trades = pd.concat([long_trades, short_trades], ignore_index=True)
    all_trades.to_csv(output_dir / f"{output_stem}_all_trades.csv", index=False)
    calculate_exit_reason_breakdown(all_trades).to_csv(output_dir / f"{output_stem}_by_exit_reason.csv", index=False)

    return all_trades, [
        summarize_trades(symbol, "long", long_trades),
        summarize_trades(symbol, "short", short_trades),
        summarize_trades(symbol, "combined", all_trades),
    ]


def write_report(output_dir: Path, summary: pd.DataFrame, all_trades: pd.DataFrame, args: argparse.Namespace) -> None:
    """Write Markdown and JSON strategy-vault evidence reports."""

    promising = summary[summary["research_status"].isin(["promising", "watch_more"])].copy() if not summary.empty else pd.DataFrame()
    best = summary.sort_values(["expectancy_r", "trades"], ascending=[False, False]).head(8) if not summary.empty else pd.DataFrame()
    payload = {
        "strategy_id": "vwap_mean_reversion",
        "generated_from": "saved Webull CSV candles",
        "entry_timeframe": args.entry_timeframe,
        "exit_timeframe": args.exit_timeframe,
        "reward_multiple_floor": args.reward_multiple_floor,
        "summary_rows": int(len(summary)),
        "total_trades": int(len(all_trades)),
        "promising_rows": int(len(promising)),
        "best_rows": best.to_dict("records") if not best.empty else [],
        "guardrail": "Research/backtesting only. Does not approve paper trades or alter scanner gates.",
    }
    (output_dir / "vwap_mean_reversion.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary.to_csv(output_dir / "vwap_mean_reversion_summary.csv", index=False)
    all_trades.to_csv(output_dir / "vwap_mean_reversion_trades.csv", index=False)
    (output_dir / "vwap_mean_reversion.md").write_text(
        f"""# VWAP Mean Reversion Research

This report tests the first complementary strategy in the Strategy Vault.

Important: this is research/backtesting only. It does not create scanner
candidates, import paper trades, place broker orders, create broker alerts, or
bypass the paper gate.

## Rules Tested

```text
Entry timeframe: {args.entry_timeframe}
Exit timeframe: {args.exit_timeframe}
Target: VWAP mean reversion
Stop: signal candle extreme plus buffer
Minimum target distance: {args.reward_multiple_floor}R
```

## Summary

{markdown_table(summary)}

## Best Rows

{markdown_table(best)}

## Promising / Watch-More Rows

{markdown_table(promising)}

## Files

```text
logs/vwap_mean_reversion.json
logs/vwap_mean_reversion_summary.csv
logs/vwap_mean_reversion_trades.csv
logs/vwap_mean_reversion.md
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
    print(f"Saved mean reversion summary: {args.output_dir / 'vwap_mean_reversion_summary.csv'}")
    print(f"Saved mean reversion report: {args.output_dir / 'vwap_mean_reversion.md'}")


if __name__ == "__main__":
    main()
