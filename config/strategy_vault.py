"""Strategy vault definitions.

The vault is a research router. It does not approve trades by itself. Each
strategy describes the market regimes where it should be studied, watched, or
used for manual paper review after the normal scanner and sizing gates pass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VaultStrategy:
    """One strategy family in the research vault."""

    strategy_id: str
    name: str
    status: str
    family: str
    ideal_regimes: tuple[str, ...]
    caution_regimes: tuple[str, ...]
    ideal_volatility: tuple[str, ...]
    description: str
    evidence_source: str
    next_research_step: str


STRATEGY_VAULT: list[VaultStrategy] = [
    VaultStrategy(
        strategy_id="vwap_ema_trend_continuation",
        name="VWAP + EMA Trend Continuation",
        status="active_paper_watch",
        family="trend_continuation",
        ideal_regimes=("bullish_trend", "bearish_trend", "risk_on_trend", "risk_off_trend"),
        caution_regimes=("mixed_chop", "range_chop", "late_day_chop"),
        ideal_volatility=("normal_volatility", "high_volatility"),
        description="The current Project Gwala setup: trade clean continuation after VWAP/EMA structure confirms.",
        evidence_source="Existing backtests, setup health, forward samples, and paper-validation gates.",
        next_research_step="Keep paper-validating only fresh current-candle candidates.",
    ),
    VaultStrategy(
        strategy_id="vwap_mean_reversion",
        name="VWAP Mean Reversion",
        status="research_backlog",
        family="mean_reversion",
        ideal_regimes=("mixed_chop", "range_chop", "late_day_chop"),
        caution_regimes=("bullish_trend", "bearish_trend", "gap_and_go"),
        ideal_volatility=("normal_volatility", "low_volatility"),
        description="Study fades back toward VWAP when trend-continuation conditions are not clean.",
        evidence_source="Not implemented yet. Needs backtest rules, shadow samples, and promotion gates.",
        next_research_step="Define entry/stop/target rules and run a no-lookahead backtest.",
    ),
    VaultStrategy(
        strategy_id="opening_range_breakout",
        name="Opening Range Breakout",
        status="research_backlog",
        family="breakout",
        ideal_regimes=("gap_and_go", "bullish_trend", "bearish_trend"),
        caution_regimes=("range_chop", "mixed_chop"),
        ideal_volatility=("high_volatility", "normal_volatility"),
        description="Study early expansion through the opening range with strong relative volume.",
        evidence_source="Not implemented yet. Needs OR breakout-specific backtests and forward samples.",
        next_research_step="Add OR breakout strategy module and compare against the current continuation setup.",
    ),
    VaultStrategy(
        strategy_id="opening_range_failure",
        name="Opening Range Failure",
        status="research_backlog",
        family="failed_breakout",
        ideal_regimes=("range_chop", "mixed_chop", "late_day_chop"),
        caution_regimes=("gap_and_go", "risk_on_trend", "risk_off_trend"),
        ideal_volatility=("normal_volatility", "high_volatility"),
        description="Study failed opening-range breaks that reverse back through VWAP or the range midpoint.",
        evidence_source="Not implemented yet. Needs failure-pattern labels and backtests.",
        next_research_step="Define failure trigger and compare with near-miss/blocked continuation rows.",
    ),
]


def vault_by_id() -> dict[str, VaultStrategy]:
    """Return strategies keyed by stable strategy id."""

    return {strategy.strategy_id: strategy for strategy in STRATEGY_VAULT}
