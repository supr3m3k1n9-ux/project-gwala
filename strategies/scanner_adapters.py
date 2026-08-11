"""Scanner adapters for strategy-specific live candidate behavior.

The daily scanner should coordinate the workflow, not own every strategy's
signal column, checklist, score fields, and risk plan. These adapters keep that
wiring explicit so new strategies must define how they flow into the same
scanner/router/pre-entry/dashboard shape.

Research and paper workflow only. No broker orders or live execution.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtesting.engine import ExitProfile
from config.symbol_playbook import PlaybookEntry
from risk_management.rules import build_long_risk, build_short_risk
from run_webull_watchlist import (
    MARKET_CONFIRMED_VARIANTS,
    is_setup_b_short_variant,
    settings_for_variant,
    signal_column_for_variant,
    use_baseline_candidate_metrics,
)
from strategies.trend_pullback_continuation import add_trend_pullback_continuation_signals


def bool_checks(checks: list[tuple[str, object]]) -> list[tuple[str, bool]]:
    """Convert loosely typed checklist values to booleans."""

    return [(label, bool(passed)) for label, passed in checks]


@dataclass(frozen=True)
class ScannerFields:
    """Dashboard-facing fields calculated from one scanner row."""

    quality_score: int
    quality_grade: str
    relative_volume: float
    room_to_target_r: float


class BaseScannerAdapter:
    """Base adapter for one strategy family."""

    strategy_id = "vwap_ema_trend_continuation"

    def owns(self, entry: PlaybookEntry) -> bool:
        """Return True if this adapter owns the playbook entry."""

        return False

    def signal_column(self, entry: PlaybookEntry) -> str:
        """Return the signal column to scan."""

        raise NotImplementedError

    def direction(self, entry: PlaybookEntry) -> str:
        """Return long or short for this playbook entry."""

        raise NotImplementedError

    def add_columns(self, candles: pd.DataFrame, entry: PlaybookEntry) -> pd.DataFrame:
        """Add any strategy-specific columns after shared indicators."""

        return candles

    def condition_checks(self, row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[tuple[str, bool]]:
        """Return current-candle checklist rows."""

        raise NotImplementedError

    def plan_for_signal(self, row: pd.Series, entry: PlaybookEntry, exit_profile: ExitProfile) -> dict:
        """Build planned entry, stop, target, and risk for a valid signal."""

        raise NotImplementedError

    def scanner_fields(self, row: pd.Series, entry: PlaybookEntry) -> ScannerFields:
        """Return dashboard fields for quality and room-to-target."""

        raise NotImplementedError

    def block_metrics(self, row: pd.Series, entry: PlaybookEntry) -> tuple[float, float]:
        """Return relative volume and room-to-target for watch-only filters."""

        fields = self.scanner_fields(row, entry)
        return fields.relative_volume, fields.room_to_target_r


class VwapEmaTrendContinuationAdapter(BaseScannerAdapter):
    """Adapter for existing Setup A/B/C VWAP + EMA continuation lanes."""

    strategy_id = "vwap_ema_trend_continuation"

    def owns(self, entry: PlaybookEntry) -> bool:
        return True

    def signal_column(self, entry: PlaybookEntry) -> str:
        if is_setup_b_short_variant(entry.variant):
            return "short_signal" if use_baseline_candidate_metrics(entry.variant) else signal_column_for_variant(entry.variant)
        return "long_signal" if use_baseline_candidate_metrics(entry.variant) else signal_column_for_variant(entry.variant)

    def direction(self, entry: PlaybookEntry) -> str:
        return "short" if is_setup_b_short_variant(entry.variant) else "long"

    def condition_checks(self, row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[tuple[str, bool]]:
        if self.direction(entry) == "short":
            return self.short_condition_checks(row, entry, signal_column)
        return self.long_condition_checks(row, entry, signal_column)

    def long_condition_checks(self, row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[tuple[str, bool]]:
        """Return long-setup rule checks for dashboard explanations."""

        settings = settings_for_variant(entry.variant)
        checks = [
            ("regular session", row.get("regular_session", False)),
            ("inside entry window", row.get("entry_window", False)),
            ("price above 200 EMA", row.get("bullish_regime", False)),
            ("9 EMA above 21 EMA", row.get("bullish_ema_stack", False)),
            ("close above VWAP", row.get("buyers_control_vwap", False)),
            ("1H bullish thesis", row.get("htf_bullish_bias", False)),
            ("pulled back to VWAP/EMA value", row.get("pullback_to_value", False)),
            ("bullish reclaim candle", row.get("bullish_reclaim", False)),
        ]
        if settings.require_above_opening_range:
            checks.insert(6, ("above opening range high", row.get("above_opening_range", False)))
        if signal_column in {"elite_long_signal", "quality_entry_signal"}:
            checks.extend(
                [
                    ("strong relative volume", row.get("strong_relative_volume", False)),
                    ("clean bull trend", row.get("clean_bull_trend", False)),
                    ("trend-day regime", row.get("trend_day_regime", False)),
                    ("room to target", row.get("has_room_to_target", False)),
                ]
            )
        if entry.variant in MARKET_CONFIRMED_VARIANTS:
            checks.append(("SPY market confirmation", row.get("market_bullish_bias", False)))
        return bool_checks(checks)

    def short_condition_checks(self, row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[tuple[str, bool]]:
        """Return short-setup rule checks for dashboard explanations."""

        settings = settings_for_variant(entry.variant)
        checks = [
            ("regular session", row.get("regular_session", False)),
            ("inside entry window", row.get("entry_window", False)),
            ("price below 200 EMA", row.get("bearish_regime", False)),
            ("9 EMA below 21 EMA", row.get("bearish_ema_stack", False)),
            ("close below VWAP", row.get("sellers_control_vwap", False)),
            ("1H bearish thesis", row.get("htf_bearish_bias", False)),
            ("pulled back into VWAP/EMA value", row.get("short_pullback_to_value", False)),
            ("bearish rejection candle", row.get("bearish_reject", False)),
        ]
        if settings.require_above_opening_range:
            checks.insert(6, ("below opening range low", row.get("below_opening_range", False)))
        if signal_column == "quality_short_signal":
            checks.extend(
                [
                    ("strong relative volume", row.get("strong_relative_volume", False)),
                    ("clean bear trend", row.get("clean_bear_trend", False)),
                    ("bear trend-day regime", row.get("bear_trend_day_regime", False)),
                    ("room to short target", row.get("has_room_to_short_target", False)),
                ]
            )
        return bool_checks(checks)

    def plan_for_signal(self, row: pd.Series, entry: PlaybookEntry, exit_profile: ExitProfile) -> dict:
        settings = settings_for_variant(entry.variant)
        reward_multiple = exit_profile.reward_multiple
        if reward_multiple is None:
            reward_multiple = settings.reward_multiple

        if self.direction(entry) == "short":
            stop_reference = max(row["vwap"], row[f"ema_{settings.fast_ema_length}"], row[f"ema_{settings.slow_ema_length}"])
            trade_risk = build_short_risk(
                entry=float(row["close"]),
                stop_reference=float(stop_reference),
                stop_buffer_pct=settings.stop_buffer_pct,
                reward_multiple=reward_multiple,
            )
        else:
            stop_reference = min(row["vwap"], row[f"ema_{settings.fast_ema_length}"], row[f"ema_{settings.slow_ema_length}"])
            trade_risk = build_long_risk(
                entry=float(row["close"]),
                stop_reference=float(stop_reference),
                stop_buffer_pct=settings.stop_buffer_pct,
                reward_multiple=reward_multiple,
            )

        return {
            "planned_entry": round(trade_risk.entry, 4),
            "planned_stop": round(trade_risk.stop, 4),
            "planned_target": round(trade_risk.target, 4),
            "risk_per_share": round(trade_risk.risk_per_share, 4),
        }

    def scanner_fields(self, row: pd.Series, entry: PlaybookEntry) -> ScannerFields:
        if self.direction(entry) == "short":
            return ScannerFields(
                quality_score=int(row.get("short_quality_score", 0)),
                quality_grade=str(row.get("short_quality_grade", "")),
                relative_volume=float(row.get("relative_volume", 0)),
                room_to_target_r=float(row.get("room_to_support_r", 0)),
            )
        return ScannerFields(
            quality_score=int(row.get("quality_score", 0)),
            quality_grade=str(row.get("quality_grade", "")),
            relative_volume=float(row.get("relative_volume", 0)),
            room_to_target_r=float(row.get("room_to_resistance_r", 0)),
        )


class TrendPullbackContinuationAdapter(BaseScannerAdapter):
    """Adapter for Trend Pullback Continuation live scanner lanes."""

    strategy_id = "trend_pullback_continuation"
    variants = {"trend_pullback_long", "trend_pullback_short"}

    def owns(self, entry: PlaybookEntry) -> bool:
        return entry.variant in self.variants

    def signal_column(self, entry: PlaybookEntry) -> str:
        return signal_column_for_variant(entry.variant)

    def direction(self, entry: PlaybookEntry) -> str:
        return "short" if entry.variant == "trend_pullback_short" else "long"

    def add_columns(self, candles: pd.DataFrame, entry: PlaybookEntry) -> pd.DataFrame:
        return add_trend_pullback_continuation_signals(candles, settings_for_variant(entry.variant))

    def condition_checks(self, row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[tuple[str, bool]]:
        settings = settings_for_variant(entry.variant)
        fast = f"ema_{settings.fast_ema_length}"
        slow = f"ema_{settings.slow_ema_length}"
        regime = f"ema_{settings.regime_ema_length}"
        quality_score = float(row.get("trend_pullback_quality_score", 0))
        relative_volume = float(row.get("trend_pullback_relative_volume", 0))
        trend_gap = float(row.get("trend_pullback_trend_gap_pct", 1))
        vwap_gap = float(row.get("trend_pullback_vwap_gap_pct", 1))

        if self.direction(entry) == "short":
            directional_checks = [
                ("close below VWAP", row.get("close", 0) < row.get("vwap", 0)),
                ("price below 200 EMA", row.get("close", 0) < row.get(regime, 0)),
                ("9 EMA below 21 EMA", row.get(fast, 0) <= row.get(slow, 0)),
                ("reclaimed below 9 EMA", row.get("close", 0) <= row.get(fast, 0)),
                ("bearish close location", row.get("trend_pullback_close_location", 1) <= 0.45),
            ]
        else:
            directional_checks = [
                ("close above VWAP", row.get("close", 0) > row.get("vwap", 0)),
                ("price above 200 EMA", row.get("close", 0) > row.get(regime, 0)),
                ("9 EMA above 21 EMA", row.get(fast, 0) >= row.get(slow, 0)),
                ("reclaimed above 9 EMA", row.get("close", 0) >= row.get(fast, 0)),
                ("bullish close location", row.get("trend_pullback_close_location", 0) >= 0.55),
            ]

        checks = [
            ("regular session", row.get("regular_session", False)),
            ("inside full-session entry window", row.get("entry_window", False)),
            *directional_checks,
            ("pulled into 9/21 EMA band", row.get("trend_pullback_touched_ema_band", False)),
            ("usable relative volume", 0.70 <= relative_volume <= 2.40),
            ("tight EMA trend gap", trend_gap <= 0.010),
            ("not overextended from VWAP", vwap_gap <= 0.020),
            ("Trend Pullback quality score 4+", quality_score >= 4),
        ]
        return bool_checks(checks)

    def plan_for_signal(self, row: pd.Series, entry: PlaybookEntry, exit_profile: ExitProfile) -> dict:
        settings = settings_for_variant(entry.variant)
        reward_multiple = 1.5
        if self.direction(entry) == "short":
            stop_reference = max(row["high"], row[f"ema_{settings.slow_ema_length}"])
            trade_risk = build_short_risk(
                entry=float(row["close"]),
                stop_reference=float(stop_reference),
                stop_buffer_pct=settings.stop_buffer_pct,
                reward_multiple=reward_multiple,
            )
        else:
            stop_reference = min(row["low"], row[f"ema_{settings.slow_ema_length}"])
            trade_risk = build_long_risk(
                entry=float(row["close"]),
                stop_reference=float(stop_reference),
                stop_buffer_pct=settings.stop_buffer_pct,
                reward_multiple=reward_multiple,
            )

        return {
            "planned_entry": round(trade_risk.entry, 4),
            "planned_stop": round(trade_risk.stop, 4),
            "planned_target": round(trade_risk.target, 4),
            "risk_per_share": round(trade_risk.risk_per_share, 4),
        }

    def scanner_fields(self, row: pd.Series, entry: PlaybookEntry) -> ScannerFields:
        return ScannerFields(
            quality_score=int(row.get("trend_pullback_quality_score", 0)),
            quality_grade=str(row.get("trend_pullback_quality_grade", "")),
            relative_volume=float(row.get("trend_pullback_relative_volume", row.get("relative_volume", 0))),
            room_to_target_r=1.5,
        )


SCANNER_ADAPTERS: tuple[BaseScannerAdapter, ...] = (
    TrendPullbackContinuationAdapter(),
    VwapEmaTrendContinuationAdapter(),
)


def scanner_adapter_for_entry(entry: PlaybookEntry) -> BaseScannerAdapter:
    """Return the scanner adapter for a playbook entry."""

    for adapter in SCANNER_ADAPTERS:
        if adapter.owns(entry):
            return adapter
    return SCANNER_ADAPTERS[-1]


def selected_signal_column(entry: PlaybookEntry) -> str:
    """Return the playbook signal column used for this entry."""

    return scanner_adapter_for_entry(entry).signal_column(entry)


def is_trend_pullback_variant(variant: str) -> bool:
    """Return True for Trend Pullback Continuation scanner variants."""

    return variant in TrendPullbackContinuationAdapter.variants


def is_short_entry_variant(variant: str) -> bool:
    """Return True when the playbook entry should be reviewed as a short."""

    return is_setup_b_short_variant(variant) or variant == "trend_pullback_short"


def entry_direction(entry: PlaybookEntry) -> str:
    """Return the intended direction for a playbook entry."""

    return scanner_adapter_for_entry(entry).direction(entry)
