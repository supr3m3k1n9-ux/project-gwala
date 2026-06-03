"""Higher-timeframe context helpers."""

from __future__ import annotations

import pandas as pd

from indicators.trend import add_core_indicators


def pandas_intraday_interval(interval: str) -> str:
    """Translate data-vendor interval names into pandas resample names."""

    if interval.endswith("m"):
        return interval.replace("m", "min")
    return interval


def add_higher_timeframe_bias(
    execution_candles: pd.DataFrame,
    thesis_interval: str,
    fast_length: int,
    slow_length: int,
    regime_length: int,
) -> pd.DataFrame:
    """Merge higher-timeframe trend context onto execution candles.

    The execution candles remain the candles we trade from. The 1H candles only
    answer whether the broader thesis is bullish enough to allow long trades.
    """

    ohlcv = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "symbol": "last",
    }

    thesis = execution_candles.resample(pandas_intraday_interval(thesis_interval)).agg(ohlcv).dropna()
    thesis = add_core_indicators(thesis, fast_length, slow_length, regime_length)

    fast = f"ema_{fast_length}"
    slow = f"ema_{slow_length}"
    regime = f"ema_{regime_length}"

    thesis["htf_bullish_bias"] = (
        (thesis["close"] > thesis[regime])
        & (thesis[fast] > thesis[slow])
        & (thesis["close"] > thesis["vwap"])
    )
    thesis["htf_bearish_bias"] = (
        (thesis["close"] < thesis[regime])
        & (thesis[fast] < thesis[slow])
        & (thesis["close"] < thesis["vwap"])
    )

    # merge_asof gives each 30m candle the most recent completed/available 1H
    # context. This is how the bot keeps thesis and execution separated.
    merged = pd.merge_asof(
        execution_candles.sort_index(),
        thesis[["htf_bullish_bias", "htf_bearish_bias"]].sort_index(),
        left_index=True,
        right_index=True,
        direction="backward",
    )
    merged["htf_bullish_bias"] = merged["htf_bullish_bias"].fillna(False)
    merged["htf_bearish_bias"] = merged["htf_bearish_bias"].fillna(False)
    return merged
