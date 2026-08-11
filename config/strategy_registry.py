"""Shared strategy wiring registry.

This file is the contract for adding strategy families end to end. A strategy
is not considered wired until the registry names its router mapping, reports,
historical simulation source, scanner variants, and chart marker label.

Research and paper workflow only. This registry does not create signals, place
orders, or approve trades.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyContract:
    """One end-to-end wiring contract for a strategy family."""

    strategy_id: str
    name: str
    family: str
    scanner_setups: tuple[str, ...]
    scanner_variants: tuple[str, ...]
    trade_log: str
    report_key: str
    report_file: str
    chart_marker_label: str
    directions: tuple[str, ...]


STRATEGY_CONTRACTS: tuple[StrategyContract, ...] = (
    StrategyContract(
        strategy_id="vwap_ema_trend_continuation",
        name="VWAP + EMA Trend Continuation",
        family="trend_continuation",
        scanner_setups=("Setup A", "Setup B", "Setup C"),
        scanner_variants=(
            "current",
            "quality_entry",
            "market_confirmed",
            "quality_entry_market_confirmed",
            "full_session",
            "quality_full_session",
            "setup_b_short",
            "setup_b_quality_short",
            "setup_b_full_session",
            "setup_b_quality_full_session",
        ),
        trade_log="",
        report_key="strategy_vault",
        report_file="strategy_vault.md",
        chart_marker_label="V",
        directions=("long", "short"),
    ),
    StrategyContract(
        strategy_id="vwap_mean_reversion",
        name="VWAP Mean Reversion",
        family="mean_reversion",
        scanner_setups=("VWAP Mean Reversion",),
        scanner_variants=(),
        trade_log="vwap_mean_reversion_trades.csv",
        report_key="vwap_mean_reversion",
        report_file="vwap_mean_reversion.md",
        chart_marker_label="M",
        directions=("long", "short"),
    ),
    StrategyContract(
        strategy_id="gap_fill_fade",
        name="Gap Fill / Gap Fade",
        family="gap_fade",
        scanner_setups=("Gap Fill", "Gap Fade"),
        scanner_variants=(),
        trade_log="gap_fill_fade_trades.csv",
        report_key="gap_fill_fade",
        report_file="gap_fill_fade.md",
        chart_marker_label="G",
        directions=("long", "short"),
    ),
    StrategyContract(
        strategy_id="vwap_reclaim_reject",
        name="VWAP Reclaim / Reject",
        family="vwap_control",
        scanner_setups=("VWAP Reclaim", "VWAP Reject"),
        scanner_variants=(),
        trade_log="vwap_reclaim_reject_trades.csv",
        report_key="vwap_reclaim_reject",
        report_file="vwap_reclaim_reject.md",
        chart_marker_label="R",
        directions=("long", "short"),
    ),
    StrategyContract(
        strategy_id="opening_range_breakout",
        name="Opening Range Breakout",
        family="breakout",
        scanner_setups=("Opening Range Breakout",),
        scanner_variants=(),
        trade_log="opening_range_breakout_trades.csv",
        report_key="opening_range_breakout",
        report_file="opening_range_breakout.md",
        chart_marker_label="O",
        directions=("long", "short"),
    ),
    StrategyContract(
        strategy_id="trend_pullback_continuation",
        name="Trend Pullback Continuation",
        family="trend_pullback",
        scanner_setups=("Trend Pullback",),
        scanner_variants=("trend_pullback_long", "trend_pullback_short"),
        trade_log="trend_pullback_continuation_trades.csv",
        report_key="trend_pullback_continuation",
        report_file="trend_pullback_continuation.md",
        chart_marker_label="P",
        directions=("long", "short"),
    ),
    StrategyContract(
        strategy_id="opening_range_failure",
        name="Opening Range Failure",
        family="failed_breakout",
        scanner_setups=("Opening Range Failure",),
        scanner_variants=(),
        trade_log="opening_range_failure_trades.csv",
        report_key="opening_range_failure",
        report_file="opening_range_failure.md",
        chart_marker_label="F",
        directions=("long", "short"),
    ),
)


def strategy_contracts_by_id() -> dict[str, StrategyContract]:
    """Return strategy contracts keyed by stable strategy id."""

    return {contract.strategy_id: contract for contract in STRATEGY_CONTRACTS}


def strategy_id_for_scanner(setup: str, variant: str) -> str:
    """Return the owning strategy id for a scanner setup/variant pair."""

    setup_text = setup.lower()
    variant_text = variant.lower()
    for contract in STRATEGY_CONTRACTS:
        if variant_text and variant_text in contract.scanner_variants:
            return contract.strategy_id
        if any(token.lower() in setup_text for token in contract.scanner_setups):
            return contract.strategy_id
    return "vwap_ema_trend_continuation"


def chart_marker_label_for_setup(setup: str, variant: str = "") -> str:
    """Return the compact chart marker label for a scanner row."""

    strategy_id = strategy_id_for_scanner(setup, variant)
    return strategy_contracts_by_id()[strategy_id].chart_marker_label


def strategy_vault_trade_logs() -> list[tuple[str, str, str]]:
    """Return Strategy Vault trade logs used by the historical simulator."""

    return [
        (contract.strategy_id, contract.name, contract.trade_log)
        for contract in STRATEGY_CONTRACTS
        if contract.trade_log
    ]
