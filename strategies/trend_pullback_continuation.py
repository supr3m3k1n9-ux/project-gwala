"""Trend pullback continuation research signals.

This strategy studies the second-chance entry after a trend is already in
motion. Instead of buying the first opening breakout, it waits for price to
pull back into the 9/21 EMA area while VWAP and the macro trend still agree.

Research/backtesting only.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings
from strategies.vwap_mean_reversion import candle_location


def add_trend_pullback_continuation_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add long/short trend-pullback continuation research signals."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"
    regime = f"ema_{settings.regime_ema_length}"

    ema_band_low = result[[fast, slow]].min(axis=1)
    ema_band_high = result[[fast, slow]].max(axis=1)
    result["trend_pullback_close_location"] = candle_location(result)
    result["trend_pullback_relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    result["trend_pullback_trend_gap_pct"] = ((result[fast] - result[slow]).abs() / result["close"]).fillna(0.0)
    result["trend_pullback_vwap_gap_pct"] = ((result["close"] - result["vwap"]).abs() / result["close"]).fillna(0.0)
    result["trend_pullback_touched_ema_band"] = (result["low"] <= ema_band_high) & (result["high"] >= ema_band_low)

    result["trend_pullback_long_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & (result["close"] > result["vwap"])
        & (result["close"] > result[regime])
        & (result[fast] >= result[slow])
        & result["trend_pullback_touched_ema_band"]
        & (result["close"] >= result[fast])
        & (result["trend_pullback_close_location"] >= 0.55)
    ).fillna(False)
    result["trend_pullback_short_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & (result["close"] < result["vwap"])
        & (result["close"] < result[regime])
        & (result[fast] <= result[slow])
        & result["trend_pullback_touched_ema_band"]
        & (result["close"] <= result[fast])
        & (result["trend_pullback_close_location"] <= 0.45)
    ).fillna(False)

    result["trend_pullback_quality_score"] = (
        (result["trend_pullback_relative_volume"] >= 0.70).astype(int)
        + (result["trend_pullback_relative_volume"] <= 2.40).astype(int)
        + (result["trend_pullback_trend_gap_pct"] <= 0.010).astype(int)
        + (result["trend_pullback_vwap_gap_pct"] <= 0.020).astype(int)
        + result["trend_pullback_touched_ema_band"].astype(int)
        + (result["trend_pullback_long_signal"] | result["trend_pullback_short_signal"]).astype(int)
    )
    result["trend_pullback_quality_grade"] = "C"
    result.loc[result["trend_pullback_quality_score"] >= 4, "trend_pullback_quality_grade"] = "B"
    result.loc[result["trend_pullback_quality_score"] >= 5, "trend_pullback_quality_grade"] = "A"
    return result
