"""Trend indicators used by the strategy."""

from __future__ import annotations

import pandas as pd


def add_ema(candles: pd.DataFrame, length: int, column: str = "close") -> pd.DataFrame:
    """Add an exponential moving average column.

    EMA reacts faster than a simple moving average, which makes it useful for
    measuring trend structure and momentum.
    """

    result = candles.copy()
    result[f"ema_{length}"] = result[column].ewm(span=length, adjust=False).mean()
    return result


def add_vwap(candles: pd.DataFrame) -> pd.DataFrame:
    """Add session VWAP.

    VWAP resets each trading day. The calculation uses typical price weighted
    by volume, which approximates the average price paid by market participants.
    """

    result = candles.copy()
    typical_price = (result["high"] + result["low"] + result["close"]) / 3
    dollar_volume = typical_price * result["volume"]
    session = result.index.date

    result["vwap"] = dollar_volume.groupby(session).cumsum() / result["volume"].groupby(session).cumsum()
    return result


def add_core_indicators(
    candles: pd.DataFrame,
    fast_length: int,
    slow_length: int,
    regime_length: int,
) -> pd.DataFrame:
    """Add the baseline VWAP/EMA indicator set."""

    result = add_vwap(candles)
    result = add_ema(result, fast_length)
    result = add_ema(result, slow_length)
    result = add_ema(result, regime_length)
    return result

