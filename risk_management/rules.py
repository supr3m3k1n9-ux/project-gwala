"""Risk management helpers.

The backtester expresses risk in R. One R is the planned loss if the stop is hit.
This keeps the research honest across different tickers and prices.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TradeRisk:
    entry: float
    stop: float
    target: float
    risk_per_share: float


def build_long_risk(entry: float, stop_reference: float, stop_buffer_pct: float, reward_multiple: float) -> TradeRisk:
    """Create a long trade stop and target.

    The stop is placed slightly below a reference level such as VWAP, EMA, or a
    candle low. The target is calculated as a multiple of that risk.
    """

    stop = stop_reference * (1 - stop_buffer_pct)
    risk_per_share = entry - stop

    if risk_per_share <= 0:
        raise ValueError("Long trade stop must be below entry.")

    target = entry + (risk_per_share * reward_multiple)
    return TradeRisk(entry=entry, stop=stop, target=target, risk_per_share=risk_per_share)


def build_short_risk(entry: float, stop_reference: float, stop_buffer_pct: float, reward_multiple: float) -> TradeRisk:
    """Create a short trade stop and target.

    A short trade is the mirror image of a long trade. The stop goes slightly
    above the reference level, and the target is below entry by a multiple of
    the planned risk.
    """

    stop = stop_reference * (1 + stop_buffer_pct)
    risk_per_share = stop - entry

    if risk_per_share <= 0:
        raise ValueError("Short trade stop must be above entry.")

    target = entry - (risk_per_share * reward_multiple)
    return TradeRisk(entry=entry, stop=stop, target=target, risk_per_share=risk_per_share)
