"""VWAP reclaim / reject research signals.

This strategy studies intraday control flips around VWAP. A reclaim is a long
idea after price was below VWAP and closes back above it. A reject is a short
idea after price was above VWAP and closes back below it.

Research/backtesting only.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings
from strategies.vwap_mean_reversion import candle_location


def add_vwap_reclaim_reject_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add long/short VWAP reclaim/reject research signals."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"

    result["vwap_rr_close_location"] = candle_location(result)
    result["vwap_rr_relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    result["vwap_rr_gap_pct"] = ((result["close"] - result["vwap"]).abs() / result["close"]).fillna(0.0)
    result["vwap_rr_trend_gap_pct"] = ((result[fast] - result[slow]).abs() / result["close"]).fillna(0.0)
    result["vwap_rr_prior_below_vwap"] = result["close"].shift(1) < result["vwap"].shift(1)
    result["vwap_rr_prior_above_vwap"] = result["close"].shift(1) > result["vwap"].shift(1)
    result["vwap_rr_touched_vwap"] = (result["low"] <= result["vwap"]) & (result["high"] >= result["vwap"])

    result["vwap_reclaim_long_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & result["vwap_rr_prior_below_vwap"]
        & result["vwap_rr_touched_vwap"]
        & (result["close"] > result["vwap"])
        & (result[fast] >= result[slow])
        & (result["vwap_rr_close_location"] >= 0.55)
    ).fillna(False)
    result["vwap_reject_short_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & result["vwap_rr_prior_above_vwap"]
        & result["vwap_rr_touched_vwap"]
        & (result["close"] < result["vwap"])
        & (result[fast] <= result[slow])
        & (result["vwap_rr_close_location"] <= 0.45)
    ).fillna(False)

    result["vwap_rr_quality_score"] = (
        (result["vwap_rr_relative_volume"] >= 0.70).astype(int)
        + (result["vwap_rr_relative_volume"] <= 2.50).astype(int)
        + (result["vwap_rr_gap_pct"] <= 0.012).astype(int)
        + (result["vwap_rr_trend_gap_pct"] <= 0.010).astype(int)
        + result["vwap_rr_touched_vwap"].astype(int)
        + (result["vwap_reclaim_long_signal"] | result["vwap_reject_short_signal"]).astype(int)
    )
    result["vwap_rr_quality_grade"] = "C"
    result.loc[result["vwap_rr_quality_score"] >= 4, "vwap_rr_quality_grade"] = "B"
    result.loc[result["vwap_rr_quality_score"] >= 5, "vwap_rr_quality_grade"] = "A"
    return result
