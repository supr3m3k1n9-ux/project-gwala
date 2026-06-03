"""Trade quality scoring.

This module is the "top-tier trader" layer. It does not try to predict the
future. It asks whether a setup has the traits disciplined traders usually wait
for: trend alignment, volume, VWAP control, opening strength, and room to move.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings


def boolean_column(result: pd.DataFrame, name: str) -> pd.Series:
    """Return an existing boolean column or a False column if missing."""

    if name in result.columns:
        return result[name].fillna(False).astype(bool)
    return pd.Series(False, index=result.index)


def add_quality_filters(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add score, grade, and strict-signal columns."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"
    regime = f"ema_{settings.regime_ema_length}"

    result["relative_volume"] = result["volume"] / result["volume"].rolling(
        settings.relative_volume_lookback,
        min_periods=1,
    ).mean()
    result["strong_relative_volume"] = result["relative_volume"] >= settings.min_relative_volume

    # Trend quality is stronger when price, VWAP, and the EMA stack all agree.
    result["ema_21_rising"] = result[slow] > result[slow].shift(1)
    result["clean_bull_trend"] = (
        (result["close"] > result["vwap"])
        & (result["close"] > result[fast])
        & (result[fast] > result[slow])
        & (result[slow] > result[regime])
        & result["ema_21_rising"]
    )

    # Market regime filter: trend continuation strategies should be pickier in
    # chop. This basic version requires VWAP control and a rising 21 EMA.
    result["trend_day_regime"] = (
        result["buyers_control_vwap"]
        & result["bullish_ema_stack"]
        & result["ema_21_rising"]
        & boolean_column(result, "htf_bullish_bias")
    )

    prior_resistance = result["high"].rolling(settings.resistance_lookback, min_periods=2).max().shift(1)
    result["near_resistance"] = result["close"] >= prior_resistance * 0.995

    # Approximate whether there is room to reach a 2R target before running into
    # recent resistance. The actual stop/target are calculated in the backtester;
    # this keeps the signal layer simple and explainable.
    stop_reference = result[["vwap", fast, slow]].min(axis=1)
    estimated_risk = result["close"] - (stop_reference * (1 - settings.stop_buffer_pct))
    room_to_resistance = prior_resistance - result["close"]
    result["room_to_resistance_r"] = room_to_resistance / estimated_risk
    result["has_room_to_target"] = result["room_to_resistance_r"] >= settings.min_room_to_resistance_r
    result["has_room_to_target"] = result["has_room_to_target"].fillna(True)

    score_parts = [
        result["bullish_regime"].astype(int),
        result["bullish_ema_stack"].astype(int),
        result["buyers_control_vwap"].astype(int),
        boolean_column(result, "htf_bullish_bias").astype(int),
        boolean_column(result, "above_opening_range").astype(int),
        result["strong_relative_volume"].astype(int),
        result["clean_bull_trend"].astype(int),
        result["trend_day_regime"].astype(int),
        result["has_room_to_target"].astype(int),
        result["bullish_reclaim"].astype(int),
    ]

    result["quality_score"] = sum(score_parts)
    result["elite_filter_pass"] = (
        (result["quality_score"] >= settings.elite_min_score)
        & result["strong_relative_volume"]
        & result["clean_bull_trend"]
        & result["trend_day_regime"]
        & result["has_room_to_target"]
    )
    result["quality_grade"] = "C"
    result.loc[result["quality_score"] >= 7, "quality_grade"] = "B"
    result.loc[result["elite_filter_pass"], "quality_grade"] = "A"

    result["elite_long_signal"] = (
        result["long_signal"]
        & result["elite_filter_pass"]
    ).fillna(False)

    # Research variant: allow high-quality trend continuation conditions to
    # trigger directly, instead of also requiring the baseline pullback/reclaim
    # candle. This helps test whether the baseline entry timing is too narrow.
    result["quality_entry_signal"] = (
        result["regular_session"]
        & result["entry_window"]
        & result["elite_filter_pass"]
    ).fillna(False)

    return result
