"""Setup B: bearish VWAP + EMA trend continuation signals.

This is the short-side research path. It mirrors the long setup without
changing Setup A, so we can test whether rejected long symbols behave better
when the market structure is bearish.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings


def boolean_column(result: pd.DataFrame, name: str) -> pd.Series:
    """Return an existing boolean column or a False column if missing."""

    if name in result.columns:
        return result[name].fillna(False).astype(bool)
    return pd.Series(False, index=result.index)


def add_short_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add Setup B short signal columns to a candle DataFrame."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"
    regime = f"ema_{settings.regime_ema_length}"

    result["bearish_regime"] = result["close"] < result[regime]
    result["bearish_ema_stack"] = result[fast] < result[slow]
    result["sellers_control_vwap"] = result["close"] < result["vwap"]

    # Short pullback condition: price pushed up into a trend reference but
    # sellers held control by the close.
    result["short_pullback_to_value"] = (
        (result["high"] >= result["vwap"])
        | (result["high"] >= result[fast])
        | (result["high"] >= result[slow])
    )

    candle_range = (result["high"] - result["low"]).replace(0, pd.NA)
    result["short_close_location"] = (result["close"] - result["low"]) / candle_range
    result["bearish_reject"] = result["short_close_location"] <= 0.4

    conditions = [
        result["entry_window"],
        result["regular_session"],
        result["short_pullback_to_value"],
        result["bearish_reject"],
    ]
    if settings.require_above_regime_ema:
        conditions.append(result["bearish_regime"])
    if settings.require_fast_above_slow:
        conditions.append(result["bearish_ema_stack"])
    if settings.require_above_vwap:
        conditions.append(result["sellers_control_vwap"])
    if settings.require_higher_timeframe_bias and "htf_bearish_bias" in result.columns:
        conditions.append(result["htf_bearish_bias"])
    if settings.require_above_opening_range and "below_opening_range" in result.columns:
        conditions.append(result["below_opening_range"])

    signal = conditions[0]
    for condition in conditions[1:]:
        signal = signal & condition
    result["short_signal"] = signal.fillna(False)

    result["relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    result["strong_relative_volume"] = result["relative_volume"] >= settings.min_relative_volume
    result["ema_21_falling"] = result[slow] < result[slow].shift(1)
    result["clean_bear_trend"] = (
        (result["close"] < result["vwap"])
        & (result["close"] < result[fast])
        & (result[fast] < result[slow])
        & (result[slow] < result[regime])
        & result["ema_21_falling"]
    )
    result["bear_trend_day_regime"] = (
        result["sellers_control_vwap"]
        & result["bearish_ema_stack"]
        & result["ema_21_falling"]
        & boolean_column(result, "htf_bearish_bias")
    )

    prior_support = result["low"].rolling(settings.resistance_lookback, min_periods=2).min().shift(1)
    result["near_support"] = result["close"] <= prior_support * 1.005
    stop_reference = result[["vwap", fast, slow]].max(axis=1)
    estimated_risk = (stop_reference * (1 + settings.stop_buffer_pct)) - result["close"]
    room_to_support = result["close"] - prior_support
    result["room_to_support_r"] = room_to_support / estimated_risk
    result["has_room_to_short_target"] = result["room_to_support_r"] >= settings.min_room_to_resistance_r
    result["has_room_to_short_target"] = result["has_room_to_short_target"].fillna(True)

    score_parts = [
        result["bearish_regime"].astype(int),
        result["bearish_ema_stack"].astype(int),
        result["sellers_control_vwap"].astype(int),
        boolean_column(result, "htf_bearish_bias").astype(int),
        boolean_column(result, "below_opening_range").astype(int),
        result["strong_relative_volume"].astype(int),
        result["clean_bear_trend"].astype(int),
        result["bear_trend_day_regime"].astype(int),
        result["has_room_to_short_target"].astype(int),
        result["bearish_reject"].astype(int),
    ]

    result["short_quality_score"] = sum(score_parts)
    result["short_elite_filter_pass"] = (
        (result["short_quality_score"] >= settings.elite_min_score)
        & result["strong_relative_volume"]
        & result["clean_bear_trend"]
        & result["bear_trend_day_regime"]
        & result["has_room_to_short_target"]
    )
    result["short_quality_grade"] = "C"
    result.loc[result["short_quality_score"] >= 7, "short_quality_grade"] = "B"
    result.loc[result["short_elite_filter_pass"], "short_quality_grade"] = "A"

    result["elite_short_signal"] = (result["short_signal"] & result["short_elite_filter_pass"]).fillna(False)
    result["quality_short_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & result["short_elite_filter_pass"]
    ).fillna(False)

    return result
