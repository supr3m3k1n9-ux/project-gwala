"""Simple candle-by-candle backtesting engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List

import pandas as pd

from config.settings import StrategySettings
from risk_management.rules import build_long_risk, build_short_risk


@dataclass
class SimulatedTrade:
    symbol: str
    entry_time: str
    exit_time: str
    setup_type: str
    signal_column: str
    quality_grade: str
    quality_score: int
    timeframe: str
    exit_timeframe: str
    entry: float
    stop: float
    target: float
    exit_price: float
    r_result: float
    exit_reason: str
    close: float
    vwap: float
    ema_9: float
    ema_21: float
    ema_200: float
    opening_range_high: float
    opening_range_low: float
    relative_volume: float
    room_to_resistance_r: float
    strong_relative_volume: bool
    clean_bull_trend: bool
    trend_day_regime: bool
    has_room_to_target: bool
    near_resistance: bool


@dataclass
class ExitProfile:
    """Exit behavior to test without changing entry rules."""

    name: str = "current"
    reward_multiple: float | None = None
    use_vwap_exit: bool = True
    vwap_exit_consecutive_closes: int = 1
    require_bearish_vwap_loss: bool = False
    use_ema9_exit: bool = False
    move_stop_to_breakeven_after_r: float | None = None


def find_exit(
    entry_time: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    risk_per_share: float,
    session_date,
    exit_candles: pd.DataFrame,
    exit_profile: ExitProfile | None = None,
) -> tuple[pd.Timestamp, pd.Series, float, float, str] | None:
    """Find the first 5m exit after a 30m entry.

    This is where the framework now mirrors the user's process: the bigger
    candle gives the setup, while the smaller candle manages the trade.
    """

    future = exit_candles[
        (exit_candles.index > entry_time)
        & (exit_candles["session_date"] == session_date)
        & (exit_candles["regular_session"])
    ]

    if future.empty:
        return None

    profile = exit_profile or ExitProfile()
    active_stop = stop
    breakeven_armed = False
    consecutive_vwap_losses = 0
    last_timestamp = future.index[-1]
    last_row = future.iloc[-1]

    for timestamp, row in future.iterrows():
        exit_price = None
        exit_reason = None

        # Conservative sequencing: if a 5m candle touches both stop and target,
        # count the stop first because we do not know the true intrabar order.
        if (
            profile.move_stop_to_breakeven_after_r is not None
            and not breakeven_armed
            and row["high"] >= entry + (risk_per_share * profile.move_stop_to_breakeven_after_r)
        ):
            active_stop = entry
            breakeven_armed = True

        if row["close"] < row["vwap"]:
            consecutive_vwap_losses += 1
        else:
            consecutive_vwap_losses = 0

        bearish_candle = row["close"] < row["open"]
        vwap_exit_ready = (
            profile.use_vwap_exit
            and consecutive_vwap_losses >= profile.vwap_exit_consecutive_closes
            and (not profile.require_bearish_vwap_loss or bearish_candle)
        )

        if row["low"] <= active_stop:
            exit_price = active_stop
            if breakeven_armed and active_stop == entry:
                exit_reason = "breakeven_stop_5m"
            else:
                exit_reason = "stop_loss_5m"
        elif row["high"] >= target:
            exit_price = target
            exit_reason = "profit_target_5m"
        elif vwap_exit_ready:
            exit_price = row["close"]
            if profile.vwap_exit_consecutive_closes > 1:
                exit_reason = f"lost_vwap_{profile.vwap_exit_consecutive_closes}_closes_5m"
            elif profile.require_bearish_vwap_loss:
                exit_reason = "lost_vwap_bearish_5m"
            else:
                exit_reason = "lost_vwap_5m"
        elif profile.use_ema9_exit and row["close"] < row.get("ema_9", row["close"]):
            exit_price = row["close"]
            exit_reason = "lost_ema9_5m"
        elif bool(row.get("force_exit_window", False)):
            exit_price = row["close"]
            exit_reason = "end_of_day_exit"

        if exit_price is not None:
            r_result = (exit_price - entry) / risk_per_share
            return timestamp, row, exit_price, r_result, exit_reason

    r_result = (last_row["close"] - entry) / risk_per_share
    return last_timestamp, last_row, last_row["close"], r_result, "last_available_exit"


def find_short_exit(
    entry_time: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    risk_per_share: float,
    session_date,
    exit_candles: pd.DataFrame,
    exit_profile: ExitProfile | None = None,
) -> tuple[pd.Timestamp, pd.Series, float, float, str] | None:
    """Find the first 5m exit after a short entry."""

    future = exit_candles[
        (exit_candles.index > entry_time)
        & (exit_candles["session_date"] == session_date)
        & (exit_candles["regular_session"])
    ]

    if future.empty:
        return None

    profile = exit_profile or ExitProfile()
    active_stop = stop
    breakeven_armed = False
    consecutive_vwap_reclaims = 0
    last_timestamp = future.index[-1]
    last_row = future.iloc[-1]

    for timestamp, row in future.iterrows():
        exit_price = None
        exit_reason = None

        if (
            profile.move_stop_to_breakeven_after_r is not None
            and not breakeven_armed
            and row["low"] <= entry - (risk_per_share * profile.move_stop_to_breakeven_after_r)
        ):
            active_stop = entry
            breakeven_armed = True

        if row["close"] > row["vwap"]:
            consecutive_vwap_reclaims += 1
        else:
            consecutive_vwap_reclaims = 0

        bullish_candle = row["close"] > row["open"]
        vwap_exit_ready = (
            profile.use_vwap_exit
            and consecutive_vwap_reclaims >= profile.vwap_exit_consecutive_closes
            and (not profile.require_bearish_vwap_loss or bullish_candle)
        )

        if row["high"] >= active_stop:
            exit_price = active_stop
            if breakeven_armed and active_stop == entry:
                exit_reason = "breakeven_stop_5m"
            else:
                exit_reason = "stop_loss_5m"
        elif row["low"] <= target:
            exit_price = target
            exit_reason = "profit_target_5m"
        elif vwap_exit_ready:
            exit_price = row["close"]
            if profile.vwap_exit_consecutive_closes > 1:
                exit_reason = f"reclaimed_vwap_{profile.vwap_exit_consecutive_closes}_closes_5m"
            elif profile.require_bearish_vwap_loss:
                exit_reason = "reclaimed_vwap_bullish_5m"
            else:
                exit_reason = "reclaimed_vwap_5m"
        elif profile.use_ema9_exit and row["close"] > row.get("ema_9", row["close"]):
            exit_price = row["close"]
            exit_reason = "reclaimed_ema9_5m"
        elif bool(row.get("force_exit_window", False)):
            exit_price = row["close"]
            exit_reason = "end_of_day_exit"

        if exit_price is not None:
            r_result = (entry - exit_price) / risk_per_share
            return timestamp, row, exit_price, r_result, exit_reason

    r_result = (entry - last_row["close"]) / risk_per_share
    return last_timestamp, last_row, last_row["close"], r_result, "last_available_exit"


def run_long_backtest(
    entry_candles: pd.DataFrame,
    exit_candles: pd.DataFrame,
    settings: StrategySettings,
    signal_column: str = "long_signal",
    setup_type: str = "baseline_vwap_ema_trend_continuation",
    exit_profile: ExitProfile | None = None,
) -> pd.DataFrame:
    """Simulate long trades from generated signals.

    The engine enters on the close of a 30m signal candle. From the next 5m
    candle forward, it checks whether stop, target, VWAP loss, or end-of-day
    exit happened first.
    """

    trades: List[SimulatedTrade] = []
    profile = exit_profile or ExitProfile()
    active_until = None
    trades_today = 0
    consecutive_losses = 0
    daily_r = 0.0
    current_day = None
    rows = list(entry_candles.iterrows())

    for index, (timestamp, row) in enumerate(rows):
        session_day = row["session_date"]
        if session_day != current_day:
            current_day = session_day
            trades_today = 0
            consecutive_losses = 0
            daily_r = 0.0

        if active_until is not None and timestamp <= active_until:
            continue

        risk_limits_hit = (
            trades_today >= settings.max_trades_per_day
            or consecutive_losses >= settings.max_consecutive_losses
            or daily_r <= settings.max_daily_loss_r
        )

        if risk_limits_hit or not bool(row.get(signal_column, False)):
            continue

        # Do not enter on the final candle because there is no future candle to
        # test the exit.
        if index >= len(rows) - 1:
            continue

        stop_reference = min(row["vwap"], row[f"ema_{settings.fast_ema_length}"], row[f"ema_{settings.slow_ema_length}"])

        try:
            reward_multiple = profile.reward_multiple
            if reward_multiple is None:
                reward_multiple = settings.reward_multiple

            trade_risk = build_long_risk(
                entry=row["close"],
                stop_reference=stop_reference,
                stop_buffer_pct=settings.stop_buffer_pct,
                reward_multiple=reward_multiple,
            )
        except ValueError:
            continue

        exit_result = find_exit(
            entry_time=timestamp,
            entry=trade_risk.entry,
            stop=trade_risk.stop,
            target=trade_risk.target,
            risk_per_share=trade_risk.risk_per_share,
            session_date=session_day,
            exit_candles=exit_candles,
            exit_profile=profile,
        )

        if exit_result is None:
            continue

        exit_time, exit_row, exit_price, r_result, exit_reason = exit_result

        trades.append(
            SimulatedTrade(
                symbol=str(row["symbol"]),
                entry_time=str(timestamp),
                exit_time=str(exit_time),
                setup_type=setup_type,
                signal_column=signal_column,
                quality_grade=str(row.get("quality_grade", "")),
                quality_score=int(row.get("quality_score", 0)),
                timeframe=settings.execution_interval,
                exit_timeframe=settings.exit_interval,
                entry=round(trade_risk.entry, 4),
                stop=round(trade_risk.stop, 4),
                target=round(trade_risk.target, 4),
                exit_price=round(exit_price, 4),
                r_result=round(r_result, 4),
                exit_reason=exit_reason,
                close=round(exit_row["close"], 4),
                vwap=round(exit_row["vwap"], 4),
                ema_9=round(exit_row.get("ema_9", 0), 4),
                ema_21=round(exit_row.get("ema_21", 0), 4),
                ema_200=round(exit_row.get("ema_200", 0), 4),
                opening_range_high=round(row.get("opening_range_high", 0), 4),
                opening_range_low=round(row.get("opening_range_low", 0), 4),
                relative_volume=round(row.get("relative_volume", 0), 4),
                room_to_resistance_r=round(row.get("room_to_resistance_r", 0), 4),
                strong_relative_volume=bool(row.get("strong_relative_volume", False)),
                clean_bull_trend=bool(row.get("clean_bull_trend", False)),
                trend_day_regime=bool(row.get("trend_day_regime", False)),
                has_room_to_target=bool(row.get("has_room_to_target", False)),
                near_resistance=bool(row.get("near_resistance", False)),
            )
        )

        active_until = exit_time
        daily_r += r_result
        consecutive_losses = consecutive_losses + 1 if r_result < 0 else 0
        trades_today += 1

    return pd.DataFrame([asdict(trade) for trade in trades])


def run_short_backtest(
    entry_candles: pd.DataFrame,
    exit_candles: pd.DataFrame,
    settings: StrategySettings,
    signal_column: str = "short_signal",
    setup_type: str = "setup_b_short_vwap_ema_trend_continuation",
    exit_profile: ExitProfile | None = None,
) -> pd.DataFrame:
    """Simulate short trades from generated Setup B signals."""

    trades: List[SimulatedTrade] = []
    profile = exit_profile or ExitProfile()
    active_until = None
    trades_today = 0
    consecutive_losses = 0
    daily_r = 0.0
    current_day = None
    rows = list(entry_candles.iterrows())

    for index, (timestamp, row) in enumerate(rows):
        session_day = row["session_date"]
        if session_day != current_day:
            current_day = session_day
            trades_today = 0
            consecutive_losses = 0
            daily_r = 0.0

        if active_until is not None and timestamp <= active_until:
            continue

        risk_limits_hit = (
            trades_today >= settings.max_trades_per_day
            or consecutive_losses >= settings.max_consecutive_losses
            or daily_r <= settings.max_daily_loss_r
        )

        if risk_limits_hit or not bool(row.get(signal_column, False)):
            continue

        if index >= len(rows) - 1:
            continue

        stop_reference = max(row["vwap"], row[f"ema_{settings.fast_ema_length}"], row[f"ema_{settings.slow_ema_length}"])

        try:
            reward_multiple = profile.reward_multiple
            if reward_multiple is None:
                reward_multiple = settings.reward_multiple

            trade_risk = build_short_risk(
                entry=row["close"],
                stop_reference=stop_reference,
                stop_buffer_pct=settings.stop_buffer_pct,
                reward_multiple=reward_multiple,
            )
        except ValueError:
            continue

        exit_result = find_short_exit(
            entry_time=timestamp,
            entry=trade_risk.entry,
            stop=trade_risk.stop,
            target=trade_risk.target,
            risk_per_share=trade_risk.risk_per_share,
            session_date=session_day,
            exit_candles=exit_candles,
            exit_profile=profile,
        )

        if exit_result is None:
            continue

        exit_time, exit_row, exit_price, r_result, exit_reason = exit_result

        trades.append(
            SimulatedTrade(
                symbol=str(row["symbol"]),
                entry_time=str(timestamp),
                exit_time=str(exit_time),
                setup_type=setup_type,
                signal_column=signal_column,
                quality_grade=str(row.get("short_quality_grade", "")),
                quality_score=int(row.get("short_quality_score", 0)),
                timeframe=settings.execution_interval,
                exit_timeframe=settings.exit_interval,
                entry=round(trade_risk.entry, 4),
                stop=round(trade_risk.stop, 4),
                target=round(trade_risk.target, 4),
                exit_price=round(exit_price, 4),
                r_result=round(r_result, 4),
                exit_reason=exit_reason,
                close=round(exit_row["close"], 4),
                vwap=round(exit_row["vwap"], 4),
                ema_9=round(exit_row.get("ema_9", 0), 4),
                ema_21=round(exit_row.get("ema_21", 0), 4),
                ema_200=round(exit_row.get("ema_200", 0), 4),
                opening_range_high=round(row.get("opening_range_high", 0), 4),
                opening_range_low=round(row.get("opening_range_low", 0), 4),
                relative_volume=round(row.get("relative_volume", 0), 4),
                room_to_resistance_r=round(row.get("room_to_support_r", 0), 4),
                strong_relative_volume=bool(row.get("strong_relative_volume", False)),
                clean_bull_trend=bool(row.get("clean_bear_trend", False)),
                trend_day_regime=bool(row.get("bear_trend_day_regime", False)),
                has_room_to_target=bool(row.get("has_room_to_short_target", False)),
                near_resistance=bool(row.get("near_support", False)),
            )
        )

        active_until = exit_time
        daily_r += r_result
        consecutive_losses = consecutive_losses + 1 if r_result < 0 else 0
        trades_today += 1

    return pd.DataFrame([asdict(trade) for trade in trades])
