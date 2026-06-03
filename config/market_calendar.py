"""Simple NYSE market calendar helpers.

This calendar is intentionally local and dependency-free. It covers the regular
NYSE full-day holidays and common early closes used by this project. It is a
paper-workflow guardrail, not an official exchange calendar feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta
from zoneinfo import ZoneInfo


MARKET_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketSession:
    """Market session status for one date."""

    session_date: date
    is_market_day: bool
    market_open: datetime | None
    market_close: datetime | None
    reason: str
    is_early_close: bool = False


def observed_fixed_holiday(year: int, month: int, day: int) -> date:
    """Return the exchange-observed date for a fixed-date holiday."""

    actual = date(year, month, day)
    if actual.weekday() == 5:  # Saturday observed Friday.
        return actual - timedelta(days=1)
    if actual.weekday() == 6:  # Sunday observed Monday.
        return actual + timedelta(days=1)
    return actual


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth weekday in a month. Monday is 0."""

    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last weekday in a month. Monday is 0."""

    if month == 12:
        current = date(year, 12, 31)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def easter_date(year: int) -> date:
    """Return Western Easter Sunday using the Meeus/Jones/Butcher algorithm."""

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nyse_full_day_holidays(year: int) -> dict[date, str]:
    """Return regular NYSE full-day holidays for a year."""

    holidays = {
        observed_fixed_holiday(year, 1, 1): "New Year's Day",
        nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        easter_date(year) - timedelta(days=2): "Good Friday",
        last_weekday(year, 5, 0): "Memorial Day",
        observed_fixed_holiday(year, 6, 19): "Juneteenth National Independence Day",
        observed_fixed_holiday(year, 7, 4): "Independence Day",
        nth_weekday(year, 9, 0, 1): "Labor Day",
        nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
        observed_fixed_holiday(year, 12, 25): "Christmas Day",
    }
    return holidays


def nyse_early_closes(year: int) -> dict[date, str]:
    """Return common 1pm ET early closes for a year."""

    early_closes: dict[date, str] = {}

    day_after_thanksgiving = nth_weekday(year, 11, 3, 4) + timedelta(days=1)
    if day_after_thanksgiving.weekday() < 5:
        early_closes[day_after_thanksgiving] = "Day after Thanksgiving early close"

    christmas_eve = date(year, 12, 24)
    if christmas_eve.weekday() < 5 and christmas_eve not in nyse_full_day_holidays(year):
        early_closes[christmas_eve] = "Christmas Eve early close"

    july_third = date(year, 7, 3)
    if july_third.weekday() < 5 and july_third not in nyse_full_day_holidays(year):
        early_closes[july_third] = "Independence Day early close"

    return early_closes


def market_session_for_date(
    session_date: date,
    regular_open: clock_time,
    regular_close: clock_time,
) -> MarketSession:
    """Return NYSE session details for a date."""

    if session_date.weekday() >= 5:
        return MarketSession(session_date, False, None, None, "Weekend")

    holidays = nyse_full_day_holidays(session_date.year)
    if session_date in holidays:
        return MarketSession(session_date, False, None, None, holidays[session_date])

    early_closes = nyse_early_closes(session_date.year)
    is_early_close = session_date in early_closes
    close_time = clock_time(13, 0, tzinfo=MARKET_TZ) if is_early_close else regular_close
    reason = early_closes[session_date] if is_early_close else "Regular session"
    open_dt = datetime.combine(session_date, regular_open).astimezone(MARKET_TZ)
    close_dt = datetime.combine(session_date, close_time).astimezone(MARKET_TZ)
    return MarketSession(session_date, True, open_dt, close_dt, reason, is_early_close)


def next_market_session(
    moment: datetime,
    regular_open: clock_time,
    regular_close: clock_time,
    max_days: int = 14,
) -> MarketSession:
    """Return the next market session on or after moment's date."""

    local = moment.astimezone(MARKET_TZ)
    current = local.date()
    for offset in range(max_days + 1):
        candidate = market_session_for_date(current + timedelta(days=offset), regular_open, regular_close)
        if candidate.is_market_day and (offset > 0 or candidate.market_close is None or local <= candidate.market_close):
            return candidate
    raise ValueError("No market session found in the search window.")
