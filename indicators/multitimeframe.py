"""Higher-timeframe context helpers."""

from __future__ import annotations

import pandas as pd

from indicators.trend import add_core_indicators


def pandas_intraday_interval(interval: str) -> str:
    """Translate data-vendor interval names into pandas resample names."""

    if interval.endswith("m"):
        return interval.replace("m", "min")
    return interval


def interval_to_timedelta(interval: str) -> pd.Timedelta:
    """Return the wall-clock duration for a project timeframe label."""

    normalized = interval.strip().lower()
    if normalized.endswith("m"):
        return pd.Timedelta(minutes=int(normalized[:-1]))
    if normalized.endswith("h"):
        return pd.Timedelta(hours=int(normalized[:-1]))
    if normalized.endswith("d"):
        return pd.Timedelta(days=int(normalized[:-1]))
    raise ValueError(f"Unsupported timeframe interval: {interval}")


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

    thesis_duration = interval_to_timedelta(thesis_interval)
    thesis = execution_candles.resample(pandas_intraday_interval(thesis_interval)).agg(ohlcv).dropna()
    thesis = add_core_indicators(thesis, fast_length, slow_length, regime_length)

    fast = f"ema_{fast_length}"
    slow = f"ema_{slow_length}"
    regime = f"ema_{regime_length}"

    thesis["htf_context_bucket_start"] = thesis.index
    thesis["htf_context_available_at"] = thesis.index + thesis_duration

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

    # A higher-timeframe candle is not available at its bucket label. For
    # example, a 10:00 60m bucket can include the 10:30 30m candle, so it only
    # becomes usable at 11:00. Merging on this explicit availability timestamp
    # prevents historical decisions from seeing future lower-timeframe bars.
    thesis_for_merge = thesis[
        [
            "htf_bullish_bias",
            "htf_bearish_bias",
            "htf_context_bucket_start",
            "htf_context_available_at",
        ]
    ].copy()
    thesis_for_merge = thesis_for_merge.set_index("htf_context_available_at", drop=False).sort_index()

    merged = pd.merge_asof(
        execution_candles.sort_index(),
        thesis_for_merge,
        left_index=True,
        right_index=True,
        direction="backward",
    )
    merged["htf_bullish_bias"] = merged["htf_bullish_bias"].fillna(False)
    merged["htf_bearish_bias"] = merged["htf_bearish_bias"].fillna(False)
    return merged
