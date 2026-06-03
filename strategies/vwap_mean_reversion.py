"""VWAP mean-reversion research signals.

This strategy is meant to complement VWAP/EMA trend continuation. It studies
range or chop conditions where price stretches away from VWAP and then starts
to reject the extreme. It is research/backtesting only.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings


def candle_location(candles: pd.DataFrame) -> pd.Series:
    """Return where the close sits inside each candle, from 0 to 1."""

    candle_range = (candles["high"] - candles["low"]).replace(0, pd.NA)
    return ((candles["close"] - candles["low"]) / candle_range).fillna(0.5)


def add_vwap_mean_reversion_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add long/short VWAP mean-reversion research signals."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"

    result["mean_reversion_close_location"] = candle_location(result)
    result["mean_reversion_trend_gap_pct"] = ((result[fast] - result[slow]).abs() / result["close"]).fillna(0.0)
    result["mean_reversion_vwap_gap_pct"] = ((result["close"] - result["vwap"]).abs() / result["close"]).fillna(0.0)
    result["mean_reversion_relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()

    # Keep the first version focused on chop/range behavior. A very wide EMA
    # gap usually means trend-continuation, not mean-reversion, owns the tape.
    result["mean_reversion_chop_regime"] = (
        (result["mean_reversion_trend_gap_pct"] <= 0.004)
        | (
            (result["low"] <= result["vwap"])
            & (result["high"] >= result["vwap"])
        )
    ).fillna(False)

    result["mean_reversion_long_stretch"] = (
        (result["low"] < result["vwap"])
        & (result["close"] < result["vwap"])
        & (result["mean_reversion_vwap_gap_pct"] >= 0.0015)
    )
    result["mean_reversion_short_stretch"] = (
        (result["high"] > result["vwap"])
        & (result["close"] > result["vwap"])
        & (result["mean_reversion_vwap_gap_pct"] >= 0.0015)
    )

    result["mean_reversion_bullish_reject"] = result["mean_reversion_close_location"] >= 0.55
    result["mean_reversion_bearish_reject"] = result["mean_reversion_close_location"] <= 0.45

    base = result["regular_session"] & result["entry_window"] & result["mean_reversion_chop_regime"]
    result["mean_reversion_long_signal"] = (
        base
        & result["mean_reversion_long_stretch"]
        & result["mean_reversion_bullish_reject"]
    ).fillna(False)
    result["mean_reversion_short_signal"] = (
        base
        & result["mean_reversion_short_stretch"]
        & result["mean_reversion_bearish_reject"]
    ).fillna(False)

    result["mean_reversion_quality_score"] = (
        result["mean_reversion_chop_regime"].astype(int)
        + (result["mean_reversion_relative_volume"] >= 0.70).astype(int)
        + (result["mean_reversion_relative_volume"] <= 1.40).astype(int)
        + result["mean_reversion_bullish_reject"].astype(int)
        + result["mean_reversion_bearish_reject"].astype(int)
        + (result["mean_reversion_vwap_gap_pct"] >= 0.0025).astype(int)
    )
    result["mean_reversion_quality_grade"] = "C"
    result.loc[result["mean_reversion_quality_score"] >= 4, "mean_reversion_quality_grade"] = "B"
    result.loc[result["mean_reversion_quality_score"] >= 5, "mean_reversion_quality_grade"] = "A"
    return result
