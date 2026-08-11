"""Central filter policy for Project Gwala ship mode.

The goal is not to make every rule loose. The goal is to make the difference
between safety, trade quality, and experimental filters explicit so paper
validation can produce enough samples without hiding risk.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SAFETY_CRITICAL = "safety-critical"
TRADE_QUALITY = "trade-quality"
EXPERIMENTAL = "experimental"

DEFAULT_PAPER_TRADE_FILTER = "none"
EXPERIMENTAL_FILTERS_ENABLED_BY_DEFAULT = False

PAPER_GATE_THRESHOLDS = {
    "a_min_check_score": 0.78,
    "a_min_quality_score": 7.0,
    "b_min_check_score": 0.65,
    "b_min_quality_score": 5.0,
    "b_min_room_to_target_r": 0.0,
    "a_risk_pct": 0.005,
    "b_risk_pct": 0.001,
}

OPTIONS_CONTRACT_THRESHOLDS = {
    "min_abs_delta": 0.40,
    "max_abs_delta": 0.70,
    "max_bid_ask_spread_pct": 0.15,
    "min_volume": 100,
    "min_open_interest": 500,
    "min_dte": 0,
    "max_dte": 5,
}


@dataclass(frozen=True)
class FilterDefinition:
    """One known filter and how ship mode treats it."""

    filter_id: str
    category: str
    family: str
    default_state: str
    configurable: bool
    threshold_source: str
    notes: str


FILTER_CATALOG: tuple[FilterDefinition, ...] = (
    FilterDefinition(
        "kill_switch",
        SAFETY_CRITICAL,
        "emergency_control",
        "missing_for_live_required_before_broker",
        False,
        "future live/paper writer guard",
        "No global kill switch exists yet; broker execution is still disabled.",
    ),
    FilterDefinition(
        "max_daily_loss",
        SAFETY_CRITICAL,
        "risk_limit",
        "strict",
        True,
        "run_position_sizer.py --max-daily-loss-r",
        "Blocks new sizing when realized daily R breaches the stop.",
    ),
    FilterDefinition(
        "position_size_limit",
        SAFETY_CRITICAL,
        "risk_limit",
        "strict",
        True,
        "run_position_sizer.py --risk-per-trade-pct",
        "Controls local paper size from account risk and risk per share.",
    ),
    FilterDefinition(
        "duplicate_order_prevention",
        SAFETY_CRITICAL,
        "order_integrity",
        "strict",
        False,
        "execution/paper_trader.py row keys",
        "Prevents duplicate local paper order/trade rows.",
    ),
    FilterDefinition(
        "broker_disconnect_handling",
        SAFETY_CRITICAL,
        "broker_integrity",
        "missing_until_broker_phase",
        False,
        "future broker adapter",
        "Not applicable to current local-only paper mode; required before live.",
    ),
    FilterDefinition(
        "data_freshness",
        SAFETY_CRITICAL,
        "data_integrity",
        "strict",
        True,
        "refresh status, preflight, Data Flow Sentinel",
        "Current-session data is mandatory for countable paper entries.",
    ),
    FilterDefinition(
        "trend_strength",
        TRADE_QUALITY,
        "chart_structure",
        "configurable",
        True,
        "config/settings.py and strategy adapters",
        "EMA, VWAP, higher-timeframe, close-location, and trend structure checks.",
    ),
    FilterDefinition(
        "regime_confidence",
        TRADE_QUALITY,
        "market_regime",
        "configurable",
        True,
        "run_market_regime_router.py",
        "Routes candidates by broad market regime and direction match.",
    ),
    FilterDefinition(
        "volume_confirmation",
        TRADE_QUALITY,
        "participation",
        "configurable",
        True,
        "config/settings.py min_relative_volume",
        "Relative volume should be tunable, not treated as a safety stop.",
    ),
    FilterDefinition(
        "volatility_threshold",
        TRADE_QUALITY,
        "volatility",
        "research_only",
        True,
        "strategy vault regime reports",
        "Volatility labels exist in research; they should not block paper by default.",
    ),
    FilterDefinition(
        "spread_threshold",
        TRADE_QUALITY,
        "contract_quality",
        "configurable",
        True,
        "OPTIONS_CONTRACT_THRESHOLDS",
        "Wide bid/ask spread blocks official options validation samples.",
    ),
    FilterDefinition(
        "liquidity_threshold",
        TRADE_QUALITY,
        "contract_quality",
        "configurable",
        True,
        "OPTIONS_CONTRACT_THRESHOLDS",
        "Volume and open interest protect paper samples from untradable contracts.",
    ),
    FilterDefinition(
        "time_of_day_rule",
        TRADE_QUALITY,
        "timing",
        "configurable",
        True,
        "config/settings.py entry windows",
        "Entry windows and late-day caution are quality filters, not core safety.",
    ),
    FilterDefinition(
        "gamma_filter",
        EXPERIMENTAL,
        "options_flow",
        "disabled",
        True,
        "not implemented",
        "Gamma filters are out of scope for ship mode.",
    ),
    FilterDefinition(
        "options_flow_filter",
        EXPERIMENTAL,
        "options_flow",
        "disabled",
        True,
        "not implemented",
        "Options-flow confirmation is out of scope for ship mode.",
    ),
    FilterDefinition(
        "advanced_regime_logic",
        EXPERIMENTAL,
        "market_regime",
        "disabled_by_default",
        True,
        "router/activation research reports",
        "Evidence routing can inform review but should not starve paper samples by surprise.",
    ),
    FilterDefinition(
        "extra_confirmation_stacking",
        EXPERIMENTAL,
        "historical_weakness",
        "disabled_by_default",
        True,
        "run_daily_scanner.py --trade-filter weakness_v1",
        "The weakness_v1 overlay is useful research, but paper scan default is none.",
    ),
)


def filter_catalog_records() -> list[dict[str, Any]]:
    """Return the known filter catalog as rows for reports."""

    return [asdict(item) for item in FILTER_CATALOG]


def classify_filter_reason(reason: object, stage: str = "") -> dict[str, str]:
    """Classify one rejection reason into ship-mode filter families."""

    raw = "" if reason is None else str(reason).strip()
    lower = raw.lower()
    stage_lower = stage.lower()

    if not raw:
        return _row("unknown", TRADE_QUALITY, "unknown", "")
    if any(token in lower for token in ["kill switch", "emergency shutdown"]):
        return _row("kill_switch", SAFETY_CRITICAL, "emergency_control", raw)
    if any(token in lower for token in ["daily stop", "daily loss", "monthly stop", "monthly loss", "risk guard"]):
        return _row("max_daily_loss", SAFETY_CRITICAL, "risk_limit", raw)
    if any(
        token in lower
        for token in [
            "position sizing",
            "size_ok",
            "suggested shares",
            "risk per share",
            "missing entry/stop/target",
            "valid bid/ask",
            "valid premium",
            "valid strike",
        ]
    ):
        return _row("position_size_limit", SAFETY_CRITICAL, "risk_limit", raw)
    if "duplicate" in lower:
        return _row("duplicate_order_prevention", SAFETY_CRITICAL, "order_integrity", raw)
    if "disconnect" in lower or "broker connection" in lower:
        return _row("broker_disconnect_handling", SAFETY_CRITICAL, "broker_integrity", raw)
    if any(
        token in lower
        for token in [
            "market is closed",
            "not current_candle",
            "not from today's session",
            "current-session",
            "not fresh",
            "stale",
            "refresh",
            "earlier_today",
            "outside regular hours",
        ]
    ):
        return _row("data_freshness", SAFETY_CRITICAL, "data_integrity", raw)
    if any(token in lower for token in ["blocked_nvda", "blocked_spy", "weakness_v1"]):
        return _row("extra_confirmation_stacking", EXPERIMENTAL, "historical_weakness", raw)
    if any(token in lower for token in ["shadow", "research_only", "paper-watch lane", "activation", "strategy selector"]):
        return _row("advanced_regime_logic", EXPERIMENTAL, "market_regime", raw)
    if any(token in lower for token in ["caution_review", "late-day", "late day"]):
        return _row("advanced_regime_logic", EXPERIMENTAL, "market_regime", raw)
    if "gamma" in lower:
        return _row("gamma_filter", EXPERIMENTAL, "options_flow", raw)
    if "options flow" in lower or "option flow" in lower:
        return _row("options_flow_filter", EXPERIMENTAL, "options_flow", raw)
    if any(token in lower for token in ["relative volume", "relvol"]):
        return _row("volume_confirmation", TRADE_QUALITY, "participation", raw)
    if any(token in lower for token in ["spread", "bid/ask"]):
        return _row("spread_threshold", TRADE_QUALITY, "contract_quality", raw)
    if any(token in lower for token in ["volume below", "open interest", "liquidity"]):
        return _row("liquidity_threshold", TRADE_QUALITY, "contract_quality", raw)
    if any(token in lower for token in ["delta", "dte", "option_type", "earnings", "contract"]):
        return _row("contract_quality", TRADE_QUALITY, "contract_quality", raw)
    if any(token in lower for token in ["regime", "router", "direction conflicts"]):
        return _row("regime_confidence", TRADE_QUALITY, "market_regime", raw)
    if any(token in lower for token in ["entry window", "regular session", "time bucket", "11am"]):
        return _row("time_of_day_rule", TRADE_QUALITY, "timing", raw)
    if any(
        token in lower
        for token in [
            "vwap",
            "ema",
            "trend",
            "opening range",
            "1h",
            "pullback",
            "reclaim",
            "rejection",
            "room to target",
            "quality score",
            "scanner did not mark",
            "scanner rules",
            "signal",
        ]
    ):
        return _row("trend_strength", TRADE_QUALITY, "chart_structure", raw)
    if "volatility" in lower:
        return _row("volatility_threshold", TRADE_QUALITY, "volatility", raw)
    if stage_lower in {"paper_gate", "scanner", "pre_entry"}:
        return _row("trend_strength", TRADE_QUALITY, "chart_structure", raw)
    return _row("unknown", TRADE_QUALITY, "unknown", raw)


def _row(filter_id: str, category: str, family: str, reason: str) -> dict[str, str]:
    """Build one classification row."""

    return {
        "filter_id": filter_id,
        "category": category,
        "family": family,
        "normalized_reason": reason,
    }
