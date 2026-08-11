"""Approved research playbook.

This file is the bridge between broad testing and an organized trading plan.
It does not place trades. It only tells the backtest runner which approved
setup/symbol pairs should be combined into one playbook report.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybookEntry:
    """One approved setup for one symbol."""

    symbol: str
    setup_name: str
    variant: str
    exit_profile: str
    status: str
    notes: str


APPROVED_PLAYBOOK: list[PlaybookEntry] = [
    PlaybookEntry(
        symbol="SPY",
        setup_name="Setup A Long",
        variant="current",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Original long setup; strongest sample size in Setup A.",
    ),
    PlaybookEntry(
        symbol="QQQ",
        setup_name="Setup A Long",
        variant="quality_entry",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Selective long entry is better than broad long entry.",
    ),
    PlaybookEntry(
        symbol="TSLA",
        setup_name="Setup A Long",
        variant="market_confirmed",
        exit_profile="two_vwap_closes",
        status="approved",
        notes="Long setup improves with SPY confirmation and a two-close VWAP exit.",
    ),
    PlaybookEntry(
        symbol="AAPL",
        setup_name="Setup A Long",
        variant="market_confirmed",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Long setup is only approved with SPY market confirmation.",
    ),
    PlaybookEntry(
        symbol="TSLA",
        setup_name="Setup B Short",
        variant="setup_b_short",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Bearish continuation setup.",
    ),
    PlaybookEntry(
        symbol="AMD",
        setup_name="Setup B Short",
        variant="setup_b_short",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Bearish continuation setup.",
    ),
    PlaybookEntry(
        symbol="QQQ",
        setup_name="Setup B Short",
        variant="setup_b_short",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Bearish continuation setup.",
    ),
    PlaybookEntry(
        symbol="NVDA",
        setup_name="Setup B Short",
        variant="setup_b_short",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Rejected by Setup A long, approved by Setup B short.",
    ),
    PlaybookEntry(
        symbol="AAPL",
        setup_name="Setup B Short",
        variant="setup_b_short",
        exit_profile="two_vwap_closes",
        status="approved",
        notes="Bearish continuation setup improves with a two-close VWAP reclaim exit.",
    ),
    PlaybookEntry(
        symbol="SPY",
        setup_name="Setup C Full-Session Long",
        variant="full_session",
        exit_profile="no_vwap_exit",
        status="approved",
        notes="Symbol-specific full-session continuation lane; passed first research filter with 10 trades.",
    ),
]


WATCH_PLAYBOOK: list[PlaybookEntry] = [
    PlaybookEntry(
        symbol="QQQ",
        setup_name="Setup C Full-Session Long",
        variant="quality_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="All-day regular-session long continuation; does not require an opening-range break.",
    ),
    PlaybookEntry(
        symbol="NVDA",
        setup_name="Setup C Full-Session Long",
        variant="quality_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="All-day regular-session long continuation; does not require an opening-range break.",
    ),
    PlaybookEntry(
        symbol="AAPL",
        setup_name="Setup C Full-Session Long",
        variant="quality_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="All-day regular-session long continuation; does not require an opening-range break.",
    ),
    PlaybookEntry(
        symbol="TSLA",
        setup_name="Setup C Full-Session Short",
        variant="setup_b_quality_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="All-day regular-session short continuation; does not require an opening-range breakdown.",
    ),
    PlaybookEntry(
        symbol="AMD",
        setup_name="Setup C Full-Session Short",
        variant="setup_b_quality_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="All-day regular-session short continuation; does not require an opening-range breakdown.",
    ),
    PlaybookEntry(
        symbol="QQQ",
        setup_name="Setup C Full-Session Short",
        variant="setup_b_quality_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="All-day regular-session short continuation; does not require an opening-range breakdown.",
    ),
    PlaybookEntry(
        symbol="MSFT",
        setup_name="Setup C Full-Session Short",
        variant="setup_b_full_session",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Promising but under-sampled all-day regular-session short continuation.",
    ),
    PlaybookEntry(
        symbol="AMD",
        setup_name="Setup A Long",
        variant="quality_entry",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Strong long stats, but one qualifying trade short of approval.",
    ),
    PlaybookEntry(
        symbol="META",
        setup_name="Setup B Short",
        variant="setup_b_quality_short",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Strong quality-short stats, but one qualifying trade short of approval.",
    ),
    PlaybookEntry(
        symbol="MSFT",
        setup_name="Setup B Short",
        variant="setup_b_quality_short",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Promising quality-short stats, but under-sampled.",
    ),
    PlaybookEntry(
        symbol="SPY",
        setup_name="Trend Pullback Long",
        variant="trend_pullback_long",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Router-controlled paper-watch lane for second-chance trend continuation longs.",
    ),
    PlaybookEntry(
        symbol="QQQ",
        setup_name="Trend Pullback Long",
        variant="trend_pullback_long",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Router-controlled paper-watch lane for second-chance trend continuation longs.",
    ),
    PlaybookEntry(
        symbol="SPY",
        setup_name="Trend Pullback Short",
        variant="trend_pullback_short",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Router-controlled paper-watch lane for second-chance trend continuation shorts.",
    ),
    PlaybookEntry(
        symbol="QQQ",
        setup_name="Trend Pullback Short",
        variant="trend_pullback_short",
        exit_profile="no_vwap_exit",
        status="watch_more",
        notes="Router-controlled paper-watch lane for second-chance trend continuation shorts.",
    ),
]


PLAYBOOKS = {
    "approved": APPROVED_PLAYBOOK,
    "watch": WATCH_PLAYBOOK,
    "approved_plus_watch": APPROVED_PLAYBOOK + WATCH_PLAYBOOK,
}


def playbook_symbols(mode: str = "approved_plus_watch") -> list[str]:
    """Return unique symbols for a playbook mode, preserving playbook order."""

    entries = PLAYBOOKS[mode]
    return list(dict.fromkeys(entry.symbol.upper() for entry in entries))


def setup_labels_for_symbol(symbol: str, mode: str = "approved_plus_watch") -> list[str]:
    """Return setup labels for one symbol.

    Watch-more setups are labeled so the dashboard can show them for research
    context without pretending they are fully approved.
    """

    labels = []
    for entry in PLAYBOOKS[mode]:
        if entry.symbol.upper() != symbol.upper():
            continue
        label = entry.setup_name
        if entry.status != "approved":
            label = f"{label} ({entry.status})"
        labels.append(label)
    return labels
