"""Regular-session and opening-range helpers."""

from __future__ import annotations

from datetime import time

import pandas as pd

from config.settings import StrategySettings


def parse_clock(clock: str) -> time:
    """Convert a HH:MM string into a Python time object."""

    hour, minute = clock.split(":")
    return time(hour=int(hour), minute=int(minute))


def add_session_columns(candles: pd.DataFrame, settings: StrategySettings) -> pd.DataFrame:
    """Add regular-session and entry-window columns.

    The data provider may return timestamps in UTC. The strategy rules are easier
    to reason about in New York time, so this function adds local session fields
    without changing the original index.
    """

    result = candles.copy()
    local_index = result.index

    if local_index.tz is None:
        local_index = local_index.tz_localize(settings.market_timezone)
    else:
        local_index = local_index.tz_convert(settings.market_timezone)

    local_times = pd.Series(local_index.time, index=result.index)

    market_open = parse_clock(settings.market_open)
    market_close = parse_clock(settings.market_close)
    entry_start = parse_clock(settings.entry_start_time)
    latest_entry = parse_clock(settings.latest_entry_time)
    force_exit = parse_clock(settings.force_exit_time)

    result["local_time"] = local_index
    result["session_date"] = local_index.date
    result["regular_session"] = (local_times >= market_open) & (local_times <= market_close)
    result["entry_window"] = (local_times >= entry_start) & (local_times <= latest_entry)
    result["force_exit_window"] = local_times >= force_exit
    return result


def add_opening_range(
    execution_candles: pd.DataFrame,
    lower_timeframe_candles: pd.DataFrame,
    settings: StrategySettings,
) -> pd.DataFrame:
    """Merge each day's opening range onto execution candles.

    The opening range is calculated from the lower timeframe so the first
    30-minute range is precise even when entries use 30-minute candles.
    """

    lower = add_session_columns(lower_timeframe_candles, settings)
    local_times = pd.Series(pd.to_datetime(lower["local_time"]).dt.time.values, index=lower.index)

    market_open = parse_clock(settings.market_open)
    opening_range_end = (
        pd.Timestamp.combine(pd.Timestamp.today(), market_open)
        + pd.Timedelta(minutes=settings.opening_range_minutes)
    ).time()

    opening_candles = lower[
        lower["regular_session"]
        & (local_times >= market_open)
        & (local_times < opening_range_end)
    ]

    ranges = opening_candles.groupby("session_date").agg(
        opening_range_high=("high", "max"),
        opening_range_low=("low", "min"),
    )

    result = execution_candles.copy()
    result = result.join(ranges, on="session_date")
    result["above_opening_range"] = result["close"] > result["opening_range_high"]
    result["below_opening_range"] = result["close"] < result["opening_range_low"]
    return result
