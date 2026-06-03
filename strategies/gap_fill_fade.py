"""Gap fill / gap fade research signals.

This strategy studies mornings where price opens away from the prior daily
close, then starts rotating back toward that prior close. A gap-up fade is a
short idea; a gap-down fade is a long idea.

Research/backtesting only.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings
from strategies.vwap_mean_reversion import candle_location


def add_gap_fill_fade_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add long/short gap-fill fade research signals."""

    result = candles.copy()
    result["gap_fade_close_location"] = candle_location(result)
    result["gap_fade_relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    result["gap_fade_gap_pct"] = ((result["session_open"] - result["prior_close"]) / result["prior_close"]).fillna(0.0)
    result["gap_fade_abs_gap_pct"] = result["gap_fade_gap_pct"].abs()
    result["gap_fade_distance_to_prior_close_pct"] = ((result["close"] - result["prior_close"]).abs() / result["close"]).fillna(0.0)

    has_gap_context = result["prior_close"].notna() & result["session_open"].notna()
    result["gap_fade_short_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & has_gap_context
        & (result["gap_fade_gap_pct"] >= 0.004)
        & (result["close"] < result["vwap"])
        & (result["close"] < result["session_open"])
        & (result["close"] > result["prior_close"])
        & (result["gap_fade_close_location"] <= 0.45)
    ).fillna(False)
    result["gap_fade_long_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & has_gap_context
        & (result["gap_fade_gap_pct"] <= -0.004)
        & (result["close"] > result["vwap"])
        & (result["close"] > result["session_open"])
        & (result["close"] < result["prior_close"])
        & (result["gap_fade_close_location"] >= 0.55)
    ).fillna(False)

    result["gap_fade_quality_score"] = (
        (result["gap_fade_abs_gap_pct"] >= 0.004).astype(int)
        + (result["gap_fade_abs_gap_pct"] <= 0.040).astype(int)
        + (result["gap_fade_relative_volume"] >= 0.70).astype(int)
        + (result["gap_fade_relative_volume"] <= 2.80).astype(int)
        + (result["gap_fade_distance_to_prior_close_pct"] >= 0.001).astype(int)
        + (result["gap_fade_long_signal"] | result["gap_fade_short_signal"]).astype(int)
    )
    result["gap_fade_quality_grade"] = "C"
    result.loc[result["gap_fade_quality_score"] >= 4, "gap_fade_quality_grade"] = "B"
    result.loc[result["gap_fade_quality_score"] >= 5, "gap_fade_quality_grade"] = "A"
    return result
