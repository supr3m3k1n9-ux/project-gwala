"""Opening-range failure research signals.

This complementary strategy studies failed early-session breakouts. A failed
break above the opening range can become a short back toward VWAP/range
midpoint; a failed break below can become a long back toward VWAP/range
midpoint.

Research/backtesting only.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings
from strategies.vwap_mean_reversion import candle_location


def add_opening_range_failure_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add long/short opening-range failure signals."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"

    result["or_failure_close_location"] = candle_location(result)
    result["or_failure_trend_gap_pct"] = ((result[fast] - result[slow]).abs() / result["close"]).fillna(0.0)
    result["or_failure_relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    result["opening_range_midpoint"] = (result["opening_range_high"] + result["opening_range_low"]) / 2

    has_range = result["opening_range_high"].notna() & result["opening_range_low"].notna()
    range_width = (result["opening_range_high"] - result["opening_range_low"]).abs()
    result["or_failure_range_width_pct"] = (range_width / result["close"]).fillna(0.0)

    # Failure short: price pokes above the OR high but closes back below it
    # with weak candle location. Failure long is the mirror image.
    result["or_failure_short_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & has_range
        & (result["high"] > result["opening_range_high"])
        & (result["close"] < result["opening_range_high"])
        & (result["or_failure_close_location"] <= 0.45)
    ).fillna(False)
    result["or_failure_long_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & has_range
        & (result["low"] < result["opening_range_low"])
        & (result["close"] > result["opening_range_low"])
        & (result["or_failure_close_location"] >= 0.55)
    ).fillna(False)

    result["or_failure_quality_score"] = (
        (result["or_failure_relative_volume"] >= 0.50).astype(int)
        + (result["or_failure_relative_volume"] <= 1.80).astype(int)
        + (result["or_failure_trend_gap_pct"] <= 0.006).astype(int)
        + (result["or_failure_range_width_pct"] >= 0.001).astype(int)
        + (result["or_failure_range_width_pct"] <= 0.025).astype(int)
        + (
            result["or_failure_short_signal"] | result["or_failure_long_signal"]
        ).astype(int)
    )
    result["or_failure_quality_grade"] = "C"
    result.loc[result["or_failure_quality_score"] >= 4, "or_failure_quality_grade"] = "B"
    result.loc[result["or_failure_quality_score"] >= 5, "or_failure_quality_grade"] = "A"
    return result
