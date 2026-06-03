"""Opening trend continuation strategy.

This strategy turns discretionary concepts into testable conditions:

1. Price is in a bullish regime.
2. Short-term EMA structure is bullish.
3. Buyers control the session above VWAP.
4. Price pulls near VWAP/EMA and then closes strong.

Only long signals are implemented first. Short logic can be added once the long
side is understood and tested.
"""

from __future__ import annotations

import pandas as pd

from config.settings import StrategySettings
from strategies.quality_filters import add_quality_filters


def add_long_signals(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add signal columns to a candle DataFrame."""

    result = candles.copy()
    fast = f"ema_{settings.fast_ema_length}"
    slow = f"ema_{settings.slow_ema_length}"
    regime = f"ema_{settings.regime_ema_length}"

    result["bullish_regime"] = result["close"] > result[regime]
    result["bullish_ema_stack"] = result[fast] > result[slow]
    result["buyers_control_vwap"] = result["close"] > result["vwap"]

    # Pullback condition: price touched or dipped below a key trend reference
    # during the candle, but did not fully lose the bullish thesis by close.
    result["pullback_to_value"] = (
        (result["low"] <= result["vwap"])
        | (result["low"] <= result[fast])
        | (result["low"] <= result[slow])
    )

    # Reclaim candle: price closes in the upper half of the candle. This is a
    # simple way to require buyers to show up after the pullback.
    candle_range = (result["high"] - result["low"]).replace(0, pd.NA)
    result["close_location"] = (result["close"] - result["low"]) / candle_range
    result["bullish_reclaim"] = result["close_location"] >= 0.6

    conditions = []
    if settings.require_above_regime_ema:
        conditions.append(result["bullish_regime"])
    if settings.require_fast_above_slow:
        conditions.append(result["bullish_ema_stack"])
    if settings.require_above_vwap:
        conditions.append(result["buyers_control_vwap"])
    if settings.require_higher_timeframe_bias and "htf_bullish_bias" in result.columns:
        conditions.append(result["htf_bullish_bias"])
    if settings.require_above_opening_range and "above_opening_range" in result.columns:
        conditions.append(result["above_opening_range"])

    conditions.extend([result["entry_window"], result["regular_session"], result["pullback_to_value"], result["bullish_reclaim"]])

    signal = conditions[0]
    for condition in conditions[1:]:
        signal = signal & condition

    result["long_signal"] = signal.fillna(False)
    result = add_quality_filters(result, settings)
    return result
