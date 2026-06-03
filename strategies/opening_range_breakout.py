"""Opening-range breakout research signals.

This complementary strategy studies early-session expansion through the
opening range. A long breakout requires price to close above the opening range
high with positive structure; a short breakout is the mirror image.

Research/backtesting only.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings
from strategies.vwap_mean_reversion import candle_location


def add_opening_range_breakout_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add long/short opening-range breakout research signals."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"

    result["or_breakout_close_location"] = candle_location(result)
    result["or_breakout_trend_gap_pct"] = ((result[fast] - result[slow]).abs() / result["close"]).fillna(0.0)
    result["or_breakout_relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    range_width = (result["opening_range_high"] - result["opening_range_low"]).abs()
    result["or_breakout_range_width_pct"] = (range_width / result["close"]).fillna(0.0)
    result["or_breakout_above_vwap"] = result["close"] > result["vwap"]
    result["or_breakout_below_vwap"] = result["close"] < result["vwap"]

    has_range = result["opening_range_high"].notna() & result["opening_range_low"].notna()
    result["or_breakout_long_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & has_range
        & (result["close"] > result["opening_range_high"])
        & result["or_breakout_above_vwap"]
        & (result[fast] >= result[slow])
        & (result["or_breakout_close_location"] >= 0.55)
    ).fillna(False)
    result["or_breakout_short_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & has_range
        & (result["close"] < result["opening_range_low"])
        & result["or_breakout_below_vwap"]
        & (result[fast] <= result[slow])
        & (result["or_breakout_close_location"] <= 0.45)
    ).fillna(False)

    result["or_breakout_quality_score"] = (
        (result["or_breakout_relative_volume"] >= 0.80).astype(int)
        + (result["or_breakout_relative_volume"] <= 2.50).astype(int)
        + (result["or_breakout_trend_gap_pct"] <= 0.012).astype(int)
        + (result["or_breakout_range_width_pct"] >= 0.001).astype(int)
        + (result["or_breakout_range_width_pct"] <= 0.035).astype(int)
        + (result["or_breakout_long_signal"] | result["or_breakout_short_signal"]).astype(int)
    )
    result["or_breakout_quality_grade"] = "C"
    result.loc[result["or_breakout_quality_score"] >= 4, "or_breakout_quality_grade"] = "B"
    result.loc[result["or_breakout_quality_score"] >= 5, "or_breakout_quality_grade"] = "A"
    return result
