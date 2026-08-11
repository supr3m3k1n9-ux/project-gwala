"""Safety and readiness tests for the paper-validation workflow."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
import json
import os
import plistlib
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.filter_policy import classify_filter_reason
from config.settings import STRATEGY
from config.strategy_registry import chart_marker_label_for_setup, strategy_id_for_scanner, strategy_vault_trade_logs
from execution.paper_trader import build_local_paper_orders, eligible_sizing_rows, orders_to_open_paper_trades
from reports.refresh_status import build_refresh_status
from reports.system_state import (
    build_system_state,
    current_candidate_state,
    data_freshness_state,
    evidence_maturity_progress_state,
    market_data_source_state,
    paper_trade_command_center_state,
    premarket_verification_state,
    risk_guard_state,
)
import run_app
from run_autonomous_paper_workflow import choose_action, commands_for_action, sleep_after_action
from run_autonomous_a_tier_lifecycle import build_lifecycle as build_autonomous_a_tier_lifecycle
from run_autonomous_a_tier_lifecycle import run_exit_monitor as run_autonomous_a_tier_exit_monitor
from run_after_close_evidence_maturity import OUTCOME_FILES, refresh_report_commands
from run_accelerated_paper_validation import build_report_payload, workflow_command as accelerated_workflow_command
from run_candidate_alerts import build_alert_rows
from run_controlled_variant_review import build_controlled_review
from run_current_candle_capture import build_commands as build_current_candle_capture_commands
from run_current_candle_capture import capture_count_summary as current_candle_capture_count_summary
from run_daily_workflow import enforce_manual_paper_import, provider_acceptance_command, refresh_data, research_snapshot_commands
from run_daily_automation_timeline import build_timeline as build_automation_timeline
from run_data_flow_sentinel import build_data_flow_sentinel
from run_dashboard_data_preflight import build_checks as build_dashboard_data_preflight
from run_historical_bucket_sync import build_historical_bucket_sync
from run_data_integrity import inspect_file
from run_daily_scanner import (
    entry_direction,
    playbook_entries_for_scan,
    scanner_freshness_frame,
    selected_signal_column,
    write_import_template,
)
from run_daily_ship_report import build_ship_report, official_sample_progress
from run_forward_observations import OBSERVATION_COLUMNS, dedupe, scanner_is_fresh_for_open_market, scanner_to_observations
from run_candidate_aging import build_aging as build_candidate_aging
from run_candidate_aging import bucket_summary as candidate_aging_bucket_summary
from run_forward_evidence import build_evidence as build_forward_evidence
from run_forward_sample_queue import build_queue as build_forward_sample_queue
from run_forward_sample_queue import queue_payload as forward_sample_queue_payload
from run_feature_wiring_audit import build_payload as build_feature_wiring_payload
from run_filter_rejection_report import build_events as build_filter_rejection_events
from run_filter_rejection_report import build_summary as build_filter_rejection_summary
from run_holdout_validation import add_entry_dates, stability_summary, validation_windows
from run_import_candles_csv import import_candles, normalize_external_candles
from data.candle_cache import candle_cache_path, legacy_candle_cache_path, preferred_candle_path, save_candle_cache
from data.market_data_sources import append_sources, latest_source_for, source_row
from data.polygon_data import normalize_polygon_aggs, polygon_aggs_url, timeframe_to_polygon
from run_intraday_loop import is_market_open, parse_args as parse_intraday_loop_args, session_has_ended
from run_candidate_window_ledger import build_ledger as build_candidate_window_ledger
from run_candidate_ledger_event_dispatcher import build_dispatch as build_candidate_ledger_event_dispatch
from run_controlled_universe_expansion import build_payload as build_controlled_universe_expansion
from run_market_regime_router import build_router as build_market_regime_router
from run_market_sprint_mode import build_payload as build_market_sprint_payload
from run_morning_watchdog import build_watchdog as build_morning_watchdog
from run_production_alert import build_alert as build_production_alert
from run_production_alert import internal_severity, notification_title
from run_production_heartbeat import build_heartbeat as build_production_heartbeat
from run_executive_report import DeliveryResult, build_eod_payload, deliver_report, eod_markdown, rows_from_csv, save_report
from notification_format import executive_report_notification, production_alert_notification
from tools.build_executive_report_launchd_plists import build_eod_plist, build_opening_plist
from tools.build_production_alert_launchd_plist import build_plist as build_production_alert_plist
from tools.build_production_alert_launchd_plist import calendar_entries as production_alert_calendar_entries
from deploy.linux.write_host_systemd_health import DEFAULT_UNITS as HOST_SYSTEMD_HEALTH_UNITS
from deploy.linux.write_host_systemd_health import unit_health as host_systemd_unit_health
from run_near_miss_analytics import (
    almost_ready_outcomes,
    build_near_miss_payload,
    dedupe as dedupe_near_misses,
    near_miss_rows,
    scanner_is_fresh_for_open_market as near_miss_scanner_is_fresh,
)
from run_no_trade_analysis import build_analysis as build_no_trade_analysis
from run_observation_reconciliation import reconcile
from run_exit_audit import build_audit
from run_open_paper_monitor import apply_updates, build_updates, open_paper_rows
from run_opening_range_relaxation_review import build_review as build_opening_range_review
from run_paper_import import paper_import_is_allowed
from run_paper_entry_packet import build_packets as build_paper_entry_packets
from run_paper_gate_v2 import build_payload as build_paper_gate_v2, sample_counts
from run_option_chain_import import CHAIN_COLUMNS as OPTION_CHAIN_COLUMNS
from run_option_chain_import import metadata_path_for as option_chain_metadata_path
from run_option_chain_import import build_import as build_option_chain_import
from run_options_chain_review import build_payload as build_options_chain_review
from run_options_chain_review import validate_chain_provenance
from run_options_contract_gate import build_gate as build_options_contract_gate
from run_options_contract_gate import trigger_autonomous_lifecycle
from run_paper_session_cycle import build_commands as build_paper_session_commands
from run_paper_validation_sample_import import build_import as build_validation_sample_import
from run_provider_acceptance import build_acceptance_report
from run_provider_stability_audit import build_provider_stability_audit
from run_post_scan_digest import build_digest as build_post_scan_digest
from run_position_sizer import apply_session_gate, build_sizing, realized_r_from_paper_log, risk_status
from run_premarket_plan import candidate_table as plan_candidate_table
from run_premarket_verification import build_checks, has_failed_checks, run_webull_probe, write_report
from run_paper_activation_rules import build_activation_payload
from run_phase_milestones import build_milestones
from run_pre_entry_review import review_row as pre_entry_review_row
from run_promotion_review import build_review as build_promotion_review
from run_probation_watch import build_payload as build_probation_watch
from run_research_confidence import build_rows as build_research_confidence_rows, readiness_status
from run_regime_review import build_regime_review
from run_refresh_audit import source_metadata_rows
from run_repair_m30_from_lower_timeframe import repair_symbol
from run_shadow_samples import shadow_status_for_row
from run_strategy_evidence_accumulator import summarize_lane
from run_strategy_backtest_coverage import build_coverage
from run_research_strategy_tightened_review import build_all_reviews as build_research_strategy_tightened_reviews
from run_trend_pullback_tightened_review import build_review as build_trend_pullback_tightened_review
from run_trend_pullback_continuation_shadow_samples import sample_row as trend_pullback_shadow_sample_row
from run_strategy_walk_forward_matrix import build_payload as build_strategy_walk_forward_payload
from run_strategy_overlap_audit import build_audit_rows, priority_plan
from run_strategy_triage import build_triage
from run_strategy_vault import build_selector
from run_validation_deepening_queue import build_queue as build_validation_deepening_queue
from run_gap_fill_fade_paper_watch_gate import build_gate as build_gap_fill_gate
from run_gap_fill_fade_shadow_samples import SPEC as GAP_FILL_SAMPLE_SPEC
from run_gap_fill_fade import research_status as gap_fill_research_status
from run_opening_range_breakout_paper_watch_gate import build_gate as build_opening_range_breakout_gate
from run_opening_range_breakout_walk_forward_deepening import build_review as build_opening_range_breakout_deep_walk_forward
from run_opening_range_breakout_shadow_samples import SPEC as OR_BREAKOUT_SAMPLE_SPEC
from run_opening_range_breakout import research_status as opening_range_breakout_research_status
from run_opening_range_failure_walk_forward_deepening import build_review as build_opening_range_failure_deep_walk_forward
from run_opening_range_failure_paper_watch_gate import build_gate as build_opening_range_failure_gate
from run_opening_range_failure import research_status as opening_range_failure_research_status
from run_research_strategy_sample_lane import sample_row as research_strategy_sample_row
from run_vwap_mean_reversion_shadow_samples import sample_row as mean_reversion_sample_row
from run_vwap_reclaim_reject_forward_observations import observation_dedupe as vwap_reclaim_observation_dedupe
from run_vwap_reclaim_reject_forward_observations import shadow_to_observations as vwap_reclaim_shadow_to_observations
from run_vwap_reclaim_reject_shadow_samples import sample_row as vwap_reclaim_shadow_sample_row
from run_vwap_reclaim_reject_shadow_samples import SAMPLE_COLUMNS as VWAP_RECLAIM_SAMPLE_COLUMNS
from run_trend_pullback_continuation_forward_observations import observation_dedupe as trend_pullback_observation_dedupe
from run_trend_pullback_continuation_forward_observations import shadow_to_observations as trend_pullback_shadow_to_observations
from run_trend_pullback_continuation_shadow_samples import SAMPLE_COLUMNS as TREND_PULLBACK_SAMPLE_COLUMNS
from run_trend_pullback_continuation_paper_watch_gate import build_gate as build_trend_pullback_gate
from run_vwap_reclaim_reject_paper_watch_gate import build_gate as build_vwap_reclaim_gate
from run_vwap_reclaim_reject_evidence_maturity import build_review as build_vwap_reclaim_maturity_review
from run_vwap_reclaim_reject_walk_forward import build_review as build_vwap_reclaim_walk_forward
from run_walk_forward_review import build_walk_forward_review
from run_trade_checklist import current_candidates as checklist_candidates
from run_webull_watchlist import (
    fetch_and_save,
    fetch_chart_only_timeframes,
    is_setup_b_short_variant,
    settings_for_variant,
    signal_column_for_variant,
    use_baseline_candidate_metrics,
    write_candidate_selection_report,
)
from strategies.gap_fill_fade import add_gap_fill_fade_signals
from strategies.opening_range_breakout import add_opening_range_breakout_signals
from strategies.trend_pullback_continuation import add_trend_pullback_continuation_signals
from strategies.vwap_reclaim_reject import add_vwap_reclaim_reject_signals


MACOS_NATIVE_RUNTIME = {"platform_name": "Darwin", "in_docker": False}
LINUX_DOCKER_SHADOW_ENV = {
    "GWALA_DEPLOYMENT_MODE": "shadow",
    "GWALA_SHADOW_MODE": "true",
    "GWALA_DISABLE_BROKER_EXECUTION": "true",
    "GWALA_LIVE_TRADING_ENABLED": "false",
    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
    "GWALA_REAL_MONEY_READY": "false",
}


def scanner_row(**updates: object) -> dict[str, object]:
    """Return one scanner row suitable for workflow tests."""

    row: dict[str, object] = {
        "scan_date": "2026-05-26",
        "latest_signal_et": "2026-05-26 10:30",
        "latest_candle_et": "2026-05-26 10:30",
        "symbol": "SPY",
        "setup": "Setup A Long",
        "direction": "long",
        "variant": "current",
        "exit_profile": "no_vwap_exit",
        "scanner_status": "allowed",
        "signal_freshness": "current_candle",
        "block_reason": "",
        "planned_entry": 100.0,
        "planned_stop": 99.0,
        "planned_target": 102.0,
        "risk_per_share": 1.0,
        "quality_score": 8,
        "quality_grade": "A",
        "relative_volume": 1.4,
        "room_to_target_r": 2.0,
        "notes": "test candidate",
    }
    row.update(updates)
    return row


def refresh_audit_row(**updates: object) -> dict[str, object]:
    """Return one recorded current-session Webull refresh evidence row."""

    row: dict[str, object] = {
        "symbol": "SPY",
        "m30_latest_session": "2026-05-26",
        "m5_latest_session": "2026-05-26",
        "refresh_evidence_status": "current_session_in_progress",
    }
    row.update(updates)
    return row


def a_tier_ledger_row(**updates: object) -> dict[str, object]:
    """Return one preserved A-tier Candidate Ledger row."""

    row: dict[str, object] = {
        "trade_date": "2026-05-26",
        "symbol": "SPY",
        "setup": "Setup A Long",
        "direction": "long",
        "source_signal_et": "2026-05-26 10:30",
        "candidate_entry_et": "2026-05-26 10:30",
        "freshness_lane": "current_candle",
        "first_seen_at": "2026-05-26 10:35:00 EDT",
        "scan_timestamp": "2026-05-26 10:35:00 EDT",
        "scanner_status": "allowed",
        "sizing_status": "size_ok",
        "router_status": "review_first",
        "paper_gate_status": "ready_for_validation_sample",
        "paper_gate_tier": "A",
        "entry": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "size": 5,
        "latest_candle_et": "2026-05-26 10:30",
        "strategy_id": "vwap_ema_trend_continuation",
        "variant": "current",
        "exit_profile": "no_vwap_exit",
        "quality_grade": "A",
        "quality_score": 8,
        "check_score": 0.8889,
        "room_to_target_r": 2.0,
        "relative_volume": 1.4,
        "risk_per_share": 1.0,
        "paper_gate_reason": "A-tier: current M30 signal.",
    }
    row.update(updates)
    return row


def clean_contract_audit_row(**updates: object) -> dict[str, object]:
    """Return one Contract Gate-passing manual contract audit row."""

    row: dict[str, object] = {
        "sample_date": "2026-05-26",
        "entry_time_et": "10:30",
        "symbol": "SPY",
        "setup": "Setup A Long",
        "direction": "long",
        "strategy_id": "vwap_ema_trend_continuation",
        "sample_tier": "A",
        "contract_symbol": "SPY260526C00500000",
        "option_type": "CALL",
        "expiration": "2026-05-26",
        "dte": 0,
        "strike": 500,
        "delta": 0.55,
        "bid": 1.20,
        "ask": 1.30,
        "mid": 1.25,
        "spread_pct": 0.08,
        "volume": 1200,
        "open_interest": 4000,
        "implied_volatility": 0.24,
        "premium": 1.30,
        "earnings_within_window": "no",
        "notes": "liquid test contract",
    }
    row.update(updates)
    return row


def option_chain_row(**updates: object) -> dict[str, object]:
    """Return one provenance-complete option-chain row."""

    row: dict[str, object] = {
        "contract_symbol": "SPY260526C00500000",
        "option_type": "CALL",
        "expiration": "2026-05-26",
        "dte": 0,
        "strike": 500,
        "delta": 0.55,
        "bid": 1.20,
        "ask": 1.30,
        "mid": 1.25,
        "spread_pct": 0.08,
        "volume": 1200,
        "open_interest": 4000,
        "implied_volatility": 0.24,
        "premium": 1.30,
        "earnings_within_window": False,
        "provider": "yfinance",
        "trading_session_date": "2026-05-26",
        "chain_retrieval_timestamp": "2026-05-26 10:35:00 EDT",
        "quote_timestamp": "2026-05-26 10:35:00 EDT",
        "underlying_price": 500.0,
        "underlying_price_timestamp": "2026-05-26 10:35:00 EDT",
        "delta_source": "modeled_black_scholes",
        "delta_model_name": "black_scholes",
        "risk_free_rate": 0.04,
        "implied_volatility_source": "provider_impliedVolatility",
        "underlying_price_for_delta": 500.0,
        "calculation_timestamp": "2026-05-26 10:35:00 EDT",
    }
    row.update(updates)
    return row


def option_chain_metadata(chain_path: Path, **updates: object) -> dict[str, object]:
    """Return one provenance-complete option-chain metadata payload."""

    metadata: dict[str, object] = {
        "provider": "yfinance",
        "symbol": "SPY",
        "chain_file": str(chain_path),
        "import_status": "success",
        "trading_session_date": "2026-05-26",
        "chain_retrieval_timestamp": "2026-05-26 10:35:00 EDT",
        "source_file_generation_timestamp": "2026-05-26 10:35:00 EDT",
        "underlying_price_used": 500.0,
        "underlying_price_timestamp": "2026-05-26 10:35:00 EDT",
        "expirations_queried": ["2026-05-26"],
        "delta_source": "modeled_black_scholes",
        "delta_model_name": "black_scholes",
        "risk_free_rate_used": 0.04,
        "implied_volatility_source": "provider_impliedVolatility",
        "underlying_price_used_for_delta": 500.0,
        "calculation_timestamp": "2026-05-26 10:35:00 EDT",
        "row_count": 1,
    }
    metadata.update(updates)
    return metadata


def write_option_chain_with_metadata(path: Path, rows: list[dict[str, object]] | None = None, **metadata_updates: object) -> None:
    """Write a test active option-chain CSV and companion metadata."""

    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows or [option_chain_row()], columns=OPTION_CHAIN_COLUMNS).to_csv(path, index=False)
    option_chain_metadata_path(path).write_text(
        json.dumps(option_chain_metadata(path, **metadata_updates), indent=2),
        encoding="utf-8",
    )


def write_green_heartbeat(output_dir: Path, moment: datetime) -> None:
    """Write a GREEN same-session heartbeat fixture for lifecycle safety checks."""

    output_dir.mkdir(parents=True, exist_ok=True)
    generated = moment.strftime("%Y-%m-%d %H:%M:%S %Z")
    (output_dir / "production_heartbeat.json").write_text(
        json.dumps(
            {
                "generated_at_et": generated,
                "heartbeat_date": moment.date().isoformat(),
                "status": "GREEN",
                "experiment_valid_today": True,
            }
        ),
        encoding="utf-8",
    )


def write_lifecycle_safety_artifacts(output_dir: Path, data_dir: Path, moment: datetime) -> Path:
    """Write heartbeat and option-chain fixtures needed before autonomous paper entry."""

    write_green_heartbeat(output_dir, moment)
    chain_dir = data_dir / "options_chains" / "active"
    timestamp = moment.strftime("%Y-%m-%d %H:%M:%S %Z")
    write_option_chain_with_metadata(
        chain_dir / "SPY.csv",
        rows=[
            option_chain_row(
                trading_session_date=moment.date().isoformat(),
                chain_retrieval_timestamp=timestamp,
                quote_timestamp=timestamp,
                underlying_price_timestamp=timestamp,
                calculation_timestamp=timestamp,
            )
        ],
        trading_session_date=moment.date().isoformat(),
        chain_retrieval_timestamp=timestamp,
        source_file_generation_timestamp=timestamp,
        underlying_price_timestamp=timestamp,
        calculation_timestamp=timestamp,
    )
    return chain_dir


def write_healthy_heartbeat_artifacts(logs_dir: Path, data_dir: Path, moment: datetime) -> None:
    """Write current-day production artifacts for heartbeat tests."""

    today = moment.date().isoformat()
    generated = moment.strftime("%Y-%m-%d %H:%M:%S %Z")
    pd.DataFrame([scanner_row(scan_date=today)]).to_csv(logs_dir / "daily_paper_signal_scanner.csv", index=False)
    pd.DataFrame(
        [
            refresh_audit_row(
                refresh_run_at_et=generated,
                m30_latest_session=today,
                m5_latest_session=today,
            )
        ]
    ).to_csv(data_dir / "market_refresh_audit.csv", index=False)
    (logs_dir / "current_candle_capture.json").write_text(
        json.dumps({"generated_at_et": generated, "scanner_rows": 1}),
        encoding="utf-8",
    )
    (logs_dir / "candidate_window_ledger.json").write_text(
        json.dumps({"generated_at_et": generated, "ledger_rows": 0}),
        encoding="utf-8",
    )
    (logs_dir / "dashboard_data_preflight.json").write_text(
        json.dumps({"generated_at_et": generated, "status": "pass"}),
        encoding="utf-8",
    )
    timestamp = moment.timestamp()
    for path in [
        logs_dir / "daily_paper_signal_scanner.csv",
        data_dir / "market_refresh_audit.csv",
        logs_dir / "current_candle_capture.json",
        logs_dir / "candidate_window_ledger.json",
        logs_dir / "dashboard_data_preflight.json",
    ]:
        os.utime(path, (timestamp, timestamp))


def write_host_systemd_health_artifact(path: Path, moment: datetime, status: str = "GREEN") -> None:
    """Write a synthetic host-systemd artifact for Linux/Docker heartbeat tests."""

    payload: dict[str, object] = {
        "generated_at_et": moment.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "reason": "All Project Gwala host systemd units are healthy.",
    }
    if status == "RED":
        payload.update(
            {
                "reason": "One or more Project Gwala host systemd units are unhealthy.",
                "red_component": "project-gwala-autonomous-paper.timer",
                "red_reason": "ActiveState=failed",
            }
        )
    path.write_text(json.dumps(payload), encoding="utf-8")


def heartbeat_fixture(status: str, *, component: str = "", reason: str = "") -> dict[str, object]:
    """Return a production heartbeat fixture for alerting tests."""

    red = status == "RED"
    return {
        "generated_at_et": "2026-05-26 10:00:00 EDT",
        "heartbeat_date": "2026-05-26",
        "decision": "BUILD" if red else "VERIFY",
        "founder_time": "5-15 min" if red else "Under 5 min",
        "business_impact": "High",
        "status": status,
        "reason": reason or ("Production artifacts are current and the scheduler is healthy." if not red else "failed"),
        "next_action": "BUILD: fix the failing production component before treating today as valid." if red else "WAIT",
        "experiment_valid_today": not red,
        "red_component": component if red else "",
        "red_reason": reason if red else "",
        "checks": [
            {
                "component": component or "Production",
                "status": status,
                "reason": reason or status,
            }
        ],
        "guardrail": "Status-only production heartbeat. No strategy, gate, or trading behavior changes.",
    }


class MarketCalendarTests(unittest.TestCase):
    def test_memorial_day_is_closed_and_tuesday_is_next_session(self) -> None:
        open_time = time(9, 30, tzinfo=MARKET_TZ)
        close_time = time(16, 0, tzinfo=MARKET_TZ)

        memorial_day = market_session_for_date(date(2026, 5, 25), open_time, close_time)
        next_session = next_market_session(
            datetime(2026, 5, 25, 10, 0, tzinfo=MARKET_TZ),
            open_time,
            close_time,
        )

        self.assertFalse(memorial_day.is_market_day)
        self.assertEqual(memorial_day.reason, "Memorial Day")
        self.assertEqual(next_session.session_date, date(2026, 5, 26))
        self.assertEqual(next_session.reason, "Regular session")

    def test_intraday_loop_recognizes_close_as_terminal_for_the_session(self) -> None:
        during_market = datetime(2026, 5, 26, 15, 30, tzinfo=MARKET_TZ)
        after_close = datetime(2026, 5, 26, 16, 1, tzinfo=MARKET_TZ)

        self.assertTrue(is_market_open(during_market))
        self.assertFalse(session_has_ended(during_market))
        self.assertFalse(is_market_open(after_close))
        self.assertTrue(session_has_ended(after_close))

    def test_intraday_loop_defaults_to_five_minute_production_scans(self) -> None:
        with patch("sys.argv", ["run_intraday_loop.py"]):
            args = parse_intraday_loop_args()

        self.assertEqual(args.interval_minutes, 5)

    def test_autonomous_supervisor_selects_premarket_check(self) -> None:
        moment = datetime(2026, 5, 26, 9, 20, tzinfo=MARKET_TZ)

        decision = choose_action(moment, interval_minutes=5, premarket_minutes_before_open=15)

        self.assertEqual(decision.action, "premarket_check")

    def test_autonomous_supervisor_selects_market_scan(self) -> None:
        moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)

        decision = choose_action(moment, interval_minutes=5, premarket_minutes_before_open=15)

        self.assertEqual(decision.action, "market_scan")

    def test_autonomous_supervisor_selects_after_close_recap(self) -> None:
        moment = datetime(2026, 5, 26, 16, 5, tzinfo=MARKET_TZ)

        decision = choose_action(moment, interval_minutes=5, premarket_minutes_before_open=15)

        self.assertEqual(decision.action, "after_close_recap")

    def test_after_close_recap_runs_evidence_maturity_first(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            symbols=[],
            full_universe=False,
            pause=5.0,
            account_size=10_000.0,
            risk_per_trade_pct=0.005,
            auto_confirm_paper_exits=False,
        )

        commands = commands_for_action("after_close_recap", args)
        command_text = " ".join(commands[0])

        self.assertIn("run_after_close_evidence_maturity.py", command_text)
        self.assertNotIn("run_paper_import.py", " ".join(" ".join(command) for command in commands))

    def test_after_close_maturity_refresh_does_not_call_append_collectors(self) -> None:
        command_text = " ".join(" ".join(command) for command in refresh_report_commands(Path("logs")))

        self.assertNotIn("run_vwap_mean_reversion_shadow_samples.py", command_text)
        self.assertNotIn("run_vwap_mean_reversion_forward_observations.py", command_text)
        self.assertNotIn("run_vwap_reclaim_reject_shadow_samples.py", command_text)
        self.assertNotIn("run_vwap_reclaim_reject_forward_observations.py", command_text)
        self.assertNotIn("run_trend_pullback_continuation_shadow_samples.py", command_text)
        self.assertNotIn("run_trend_pullback_continuation_forward_observations.py", command_text)
        self.assertNotIn("run_gap_fill_fade_shadow_samples.py", command_text)
        self.assertNotIn("run_gap_fill_fade_forward_observations.py", command_text)
        self.assertNotIn("run_opening_range_breakout_shadow_samples.py", command_text)
        self.assertNotIn("run_opening_range_breakout_forward_observations.py", command_text)
        self.assertNotIn("run_opening_range_failure_shadow_samples.py", command_text)
        self.assertNotIn("run_opening_range_failure_forward_observations.py", command_text)
        self.assertIn("run_paper_activation_rules.py", command_text)

    def test_after_close_maturity_tracks_new_strategy_outcome_files(self) -> None:
        paths = {item["path"] for item in OUTCOME_FILES}

        self.assertIn("gap_fill_fade_shadow_outcomes.csv", paths)
        self.assertIn("gap_fill_fade_forward_observation_results.csv", paths)
        self.assertIn("opening_range_breakout_shadow_outcomes.csv", paths)
        self.assertIn("opening_range_breakout_forward_observation_results.csv", paths)
        self.assertIn("opening_range_failure_shadow_outcomes.csv", paths)
        self.assertIn("opening_range_failure_forward_observation_results.csv", paths)

    def test_dashboard_data_preflight_rejects_browser_invalid_json(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "system_state.json").write_text('{"profit_factor": Infinity}', encoding="utf-8")
            (output_dir / "refresh_status.json").write_text('{"status": "prep_only"}', encoding="utf-8")

            payload = build_dashboard_data_preflight(output_dir)

        self.assertEqual(payload["status"], "fail")
        self.assertTrue(any(row["area"] == "System state JSON" for row in payload["checks"]))

    def test_dashboard_data_preflight_accepts_after_close_valid_state(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "system_state.json").write_text(
                json.dumps({"app_health": {"generated_at_et": "2026-06-10 16:11:00 EDT"}}),
                encoding="utf-8",
            )
            (output_dir / "refresh_status.json").write_text(
                json.dumps(
                    {
                        "status": "prep_only",
                        "market": {"market_is_open": False},
                        "provider_refresh": {"provider": "webull", "status": "current_session_bars"},
                        "candle_freshness": {
                            "status": "outside_market_hours",
                            "stale_m5_symbols": [],
                            "stale_m30_symbols": [],
                            "unknown_symbols": [],
                        },
                        "scanner": {"latest_scanner_session": "2026-06-10", "current_candidate_count": 1},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dashboard_data_preflight(output_dir)

        self.assertEqual(payload["status"], "pass")

    def test_market_regime_router_keeps_big_net_but_routes_by_regime(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "regime": {"market_regime": "bearish_trend", "volatility_regime": "normal_volatility"},
                        "strategies": [
                            {
                                "strategy_id": "vwap_ema_trend_continuation",
                                "name": "VWAP + EMA Trend Continuation",
                                "status": "active_paper_watch",
                                "family": "trend_continuation",
                                "decision": "active",
                            },
                            {
                                "strategy_id": "trend_pullback_continuation",
                                "name": "Trend Pullback Continuation",
                                "status": "research_backlog",
                                "family": "trend_pullback",
                                "decision": "research_priority",
                                "paper_watch_decision": "paper_watch_eligible",
                            },
                            {
                                "strategy_id": "opening_range_breakout",
                                "name": "Opening Range Breakout",
                                "status": "research_backlog",
                                "family": "breakout",
                                "decision": "research_priority",
                                "paper_watch_decision": "not_ready",
                            },
                            {
                                "strategy_id": "vwap_mean_reversion",
                                "name": "VWAP Mean Reversion",
                                "status": "research_backlog",
                                "family": "mean_reversion",
                                "decision": "research_backlog",
                                "paper_watch_decision": "not_ready",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "trend_pullback_continuation",
                                "activation_decision": "paper_watch_eligible",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "age_bucket": "late_day",
                        "r_result": 0.25,
                    }
                ]
            ).to_csv(output_dir / "candidate_aging.csv", index=False)
            pd.DataFrame([scanner_row(setup="Setup B Short", direction="short")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )

            payload, strategies, candidates = build_market_regime_router(output_dir)

        routes = dict(zip(strategies["strategy_id"], strategies["route"]))
        self.assertEqual(payload["regime"]["market_regime"], "bearish_trend")
        self.assertEqual(routes["vwap_ema_trend_continuation"], "active_today")
        self.assertEqual(routes["trend_pullback_continuation"], "active_today")
        self.assertEqual(routes["opening_range_breakout"], "shadow_today")
        self.assertEqual(routes["vwap_mean_reversion"], "research_only")
        self.assertEqual(candidates.iloc[0]["candidate_route"], "review_first")

    def test_market_regime_router_makes_negative_late_day_current_signals_caution_only(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "regime": {"market_regime": "bearish_trend", "volatility_regime": "normal_volatility"},
                        "strategies": [
                            {
                                "strategy_id": "vwap_ema_trend_continuation",
                                "name": "VWAP + EMA Trend Continuation",
                                "status": "active_paper_watch",
                                "family": "trend_continuation",
                                "decision": "active",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {"age_bucket": "late_day", "r_result": -0.25},
                    {"age_bucket": "late_day", "r_result": -0.10},
                ]
            ).to_csv(output_dir / "candidate_aging.csv", index=False)
            pd.DataFrame(
                [
                    scanner_row(
                        setup="Setup C Full-Session Short",
                        direction="short",
                        variant="setup_b_quality_full_session",
                        latest_signal_et="2026-06-10 15:30",
                    )
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            payload, _, candidates = build_market_regime_router(output_dir)

        self.assertEqual(payload["late_day"]["late_day_mode"], "caution_only")
        self.assertEqual(candidates.iloc[0]["candidate_route"], "caution_review")

    def test_market_sprint_mode_prioritizes_trend_pullback_without_importing_trades(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "trend_pullback_continuation",
                                "name": "Trend Pullback Continuation",
                                "status": "research_backlog",
                                "paper_watch_decision": "paper_watch_eligible",
                                "evidence_note": "Paper-watch gate passed.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "trend_pullback_continuation",
                                "activation_decision": "paper_watch_eligible",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "market_regime_router.json").write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "symbol": "SPY",
                                "setup": "Trend Pullback Long",
                                "strategy_id": "trend_pullback_continuation",
                                "candidate_route": "review_first",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            payload = build_market_sprint_payload(output_dir, output_dir / "paper.csv")

        self.assertEqual(payload["status"], "ready_to_review_primary_lane")
        self.assertEqual(payload["primary_lane"]["strategy_id"], "trend_pullback_continuation")
        self.assertEqual(payload["paper_progress"]["official_paper_trades"], 0)
        self.assertIn("never loosens scanner rules", payload["guardrail"])

    def test_controlled_universe_expansion_blocks_stale_symbols(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            expansion_dir = output_dir / "universe_expansion"
            expansion_dir.mkdir()
            for timeframe in ["M30", "M5"]:
                (expansion_dir / f"webull_DIA_{timeframe}_candles.csv").write_text(
                    "2026-05-28T19:30:00.000+0000,507,508,506,507,1000\n",
                    encoding="utf-8",
                )

            payload = build_controlled_universe_expansion(output_dir, expansion_dir)

        dia = next(row for row in payload["rows"] if row["symbol"] == "DIA")
        self.assertEqual(payload["status"], "blocked_until_refresh")
        self.assertEqual(dia["status"], "stale_data")
        self.assertFalse(dia["active_scanner_enabled"])
        self.assertFalse(dia["counts_toward_30"])

    def test_probation_watch_tracks_near_ready_without_counting_paper_trades(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger = output_dir / "probation.csv"
            (output_dir / "almost_ready_breakout.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "action": "collect_more_evidence",
                                "symbol": "TSLA",
                                "setup": "Setup A Long",
                                "direction": "long",
                                "check_score_pct": 90.0,
                                "quality": "C 6",
                                "relative_volume": 0.5,
                                "room_to_target_r": 0.65,
                                "core_blockers": "generic timing/freshness only",
                                "reason": "Close enough to track.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "symbol": "TSLA",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "latest_candle_et": "2026-06-15 13:30",
                        "scanner_status": "not_ready",
                        "signal_freshness": "",
                    }
                ]
            ).to_csv(output_dir / "forward_sample_queue.csv", index=False)

            payload = build_probation_watch(output_dir, ledger)
            duplicate_payload = build_probation_watch(output_dir, ledger)

        self.assertEqual(payload["current_probation_rows"], 1)
        self.assertEqual(payload["new_ledger_rows"], 1)
        self.assertEqual(duplicate_payload["new_ledger_rows"], 0)
        self.assertFalse(payload["rows"][0]["counts_toward_30"])
        self.assertIn("never count toward the 30", payload["guardrail"])

    def test_paper_gate_v2_allows_one_candle_b_tier_grace_without_live_readiness(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            scanner = pd.DataFrame(
                [
                    scanner_row(
                        scanner_status="allowed",
                        latest_signal_et="2026-05-26 10:30",
                        source_signal_et="2026-05-26 10:30",
                        candidate_entry_et="2026-05-26 11:00",
                        latest_candle_et="2026-05-26 11:00",
                        signal_freshness="grace_candle",
                        validation_lane="B",
                        fresh_plan_source="latest_grace_candle",
                        quality_score=6,
                        quality_grade="B",
                        relative_volume=0.55,
                        room_to_target_r=0.6,
                        passed_condition_count=7,
                        condition_count=9,
                        missing_conditions="relative volume >= 1.0; above opening range high",
                    )
                ]
            )
            scanner.to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            (output_dir / "market_regime_router.json").write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "symbol": "SPY",
                                "setup": "Setup A Long",
                                "direction": "long",
                                "variant": "current",
                                "exit_profile": "no_vwap_exit",
                                "candidate_route": "caution_review",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_paper_gate_v2(output_dir, output_dir / "daily_paper_signal_scanner.csv", output_dir / "samples.csv")

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["b_tier_ready"], 1)
        row = payload["ready_samples"][0]
        self.assertEqual(row["sample_tier"], "B")
        self.assertEqual(row["signal_freshness"], "grace_candle")
        self.assertEqual(row["validation_lane"], "B")
        self.assertEqual(row["source_signal_et"], "2026-05-26 10:30")
        self.assertEqual(row["candidate_entry_et"], "2026-05-26 11:00")
        self.assertTrue(row["counts_toward_30"])
        self.assertFalse(row["counts_toward_live_readiness"])
        self.assertTrue(row["manual_review_required"])
        self.assertEqual(row["sample_risk_pct"], 0.001)

    def test_paper_gate_v2_does_not_promote_current_candle_quality_miss_to_b(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            pd.DataFrame(
                [
                    scanner_row(
                        scanner_status="allowed",
                        signal_freshness="current_candle",
                        quality_score=6,
                        quality_grade="B",
                        room_to_target_r=0.6,
                        passed_condition_count=7,
                        condition_count=9,
                        missing_conditions="relative volume >= 1.0",
                    )
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_paper_gate_v2(output_dir, output_dir / "daily_paper_signal_scanner.csv", output_dir / "samples.csv")

        self.assertEqual(payload["ready_sample_count"], 0)
        self.assertEqual(payload["b_tier_ready"], 0)
        self.assertEqual(payload["rows"][0]["sample_tier"], "C")

    def test_paper_gate_v2_removes_duplicate_b_window_when_a_is_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            pd.DataFrame(
                [
                    scanner_row(
                        latest_signal_et="2026-05-26 11:00",
                        candidate_entry_et="2026-05-26 11:00",
                        signal_freshness="current_candle",
                        validation_lane="A",
                        fresh_plan_source="current_signal_candle",
                        quality_score=8,
                        passed_condition_count=8,
                        condition_count=9,
                    ),
                    scanner_row(
                        latest_signal_et="2026-05-26 10:30",
                        source_signal_et="2026-05-26 10:30",
                        candidate_entry_et="2026-05-26 11:00",
                        latest_candle_et="2026-05-26 11:00",
                        signal_freshness="grace_candle",
                        validation_lane="B",
                        fresh_plan_source="latest_grace_candle",
                        quality_score=6,
                        passed_condition_count=7,
                        condition_count=9,
                    ),
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_paper_gate_v2(output_dir, output_dir / "daily_paper_signal_scanner.csv", output_dir / "samples.csv")

        self.assertEqual(payload["a_tier_ready"], 1)
        self.assertEqual(payload["b_tier_ready"], 0)
        duplicate = [row for row in payload["rows"] if row["signal_freshness"] == "grace_candle"][0]
        self.assertEqual(duplicate["sample_tier"], "C")
        self.assertIn("duplicates", duplicate["reason"])

    def test_candidate_window_ledger_persists_current_candle_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            pd.DataFrame([scanner_row()]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_freshness": "current_candle",
                        "candidate_entry_et": "2026-05-26 10:30",
                        "sizing_status": "size_ok",
                        "suggested_shares": 50,
                        "sizing_reason": "Eligible for paper sizing.",
                    }
                ]
            ).to_csv(output_dir / "position_sizing.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "candidate_route": "review_first",
                        "action": "Review first.",
                    }
                ]
            ).to_csv(output_dir / "market_regime_router_candidates.csv", index=False)
            pd.DataFrame(
                [
                    {
                        **scanner_row(),
                        "source_signal_et": "2026-05-26 10:30",
                        "candidate_entry_et": "2026-05-26 10:30",
                        "sample_status": "ready_for_validation_sample",
                        "sample_tier": "A",
                        "check_score": 0.8889,
                        "reason": "A-tier: current M30 signal.",
                    }
                ]
            ).to_csv(output_dir / "paper_gate_v2.csv", index=False)

            ledger, additions = build_candidate_window_ledger(
                output_dir,
                ledger_csv,
                seen_at="2026-05-26 10:35:00 EDT",
            )

        self.assertEqual(len(additions), 1)
        self.assertEqual(len(ledger), 1)
        row = ledger.iloc[0]
        self.assertEqual(row["freshness_lane"], "current_candle")
        self.assertEqual(row["paper_gate_status"], "ready_for_validation_sample")
        self.assertEqual(row["paper_gate_tier"], "A")
        self.assertEqual(row["first_seen_at"], "2026-05-26 10:35:00 EDT")
        self.assertEqual(row["sizing_status"], "size_ok")
        self.assertEqual(row["router_status"], "review_first")

    def test_candidate_window_ledger_persists_grace_candle_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            grace = scanner_row(
                latest_signal_et="2026-05-26 10:30",
                source_signal_et="2026-05-26 10:30",
                candidate_entry_et="2026-05-26 11:00",
                latest_candle_et="2026-05-26 11:00",
                signal_freshness="grace_candle",
                validation_lane="B",
            )
            pd.DataFrame([grace]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_freshness": "grace_candle",
                        "candidate_entry_et": "2026-05-26 11:00",
                        "sizing_status": "size_ok",
                        "suggested_shares": 10,
                    }
                ]
            ).to_csv(output_dir / "position_sizing.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "candidate_route": "caution_review",
                    }
                ]
            ).to_csv(output_dir / "market_regime_router_candidates.csv", index=False)
            pd.DataFrame(
                [
                    {
                        **grace,
                        "sample_status": "ready_for_validation_sample",
                        "sample_tier": "B",
                        "check_score": 0.7778,
                        "reason": "B-tier grace.",
                    }
                ]
            ).to_csv(output_dir / "paper_gate_v2.csv", index=False)

            ledger, additions = build_candidate_window_ledger(
                output_dir,
                ledger_csv,
                seen_at="2026-05-26 11:05:00 EDT",
            )

        self.assertEqual(len(additions), 1)
        self.assertEqual(len(ledger), 1)
        row = ledger.iloc[0]
        self.assertEqual(row["freshness_lane"], "grace_candle")
        self.assertEqual(row["source_signal_et"], "2026-05-26 10:30")
        self.assertEqual(row["candidate_entry_et"], "2026-05-26 11:00")
        self.assertEqual(row["paper_gate_tier"], "B")

    def test_candidate_window_ledger_dedupes_duplicate_scans(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            pd.DataFrame([scanner_row()]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame([scanner_row(sample_status="study_only", sample_tier="C")]).to_csv(
                output_dir / "paper_gate_v2.csv",
                index=False,
            )

            first, _ = build_candidate_window_ledger(output_dir, ledger_csv, seen_at="2026-05-26 10:35:00 EDT")
            second, _ = build_candidate_window_ledger(output_dir, ledger_csv, seen_at="2026-05-26 10:40:00 EDT")

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(second.iloc[0]["first_seen_at"], "2026-05-26 10:35:00 EDT")

    def test_candidate_window_ledger_keeps_candidate_after_later_snapshot_moves_on(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            pd.DataFrame([scanner_row()]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        **scanner_row(),
                        "sample_status": "ready_for_validation_sample",
                        "sample_tier": "A",
                        "reason": "A-tier: current M30 signal.",
                    }
                ]
            ).to_csv(output_dir / "paper_gate_v2.csv", index=False)
            build_candidate_window_ledger(output_dir, ledger_csv, seen_at="2026-05-26 10:35:00 EDT")

            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([scanner_row(signal_freshness="earlier_today", sample_status="study_only", sample_tier="C")]).to_csv(
                output_dir / "paper_gate_v2.csv",
                index=False,
            )
            ledger, additions = build_candidate_window_ledger(output_dir, ledger_csv, seen_at="2026-05-26 11:30:00 EDT")

        self.assertEqual(len(additions), 0)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger.iloc[0]["freshness_lane"], "current_candle")
        self.assertEqual(ledger.iloc[0]["paper_gate_status"], "ready_for_validation_sample")

    def test_candidate_window_ledger_preserves_first_paper_gate_ready_state(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            pd.DataFrame([scanner_row()]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        **scanner_row(),
                        "sample_status": "ready_for_validation_sample",
                        "sample_tier": "A",
                        "reason": "A-tier: current M30 signal.",
                    }
                ]
            ).to_csv(output_dir / "paper_gate_v2.csv", index=False)
            build_candidate_window_ledger(output_dir, ledger_csv, seen_at="2026-05-26 10:35:00 EDT")

            pd.DataFrame(
                [
                    {
                        **scanner_row(),
                        "sample_status": "study_only",
                        "sample_tier": "C",
                        "reason": "C-tier: later snapshot should not demote ledger.",
                    }
                ]
            ).to_csv(output_dir / "paper_gate_v2.csv", index=False)
            ledger, _ = build_candidate_window_ledger(output_dir, ledger_csv, seen_at="2026-05-26 10:40:00 EDT")

        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger.iloc[0]["paper_gate_status"], "ready_for_validation_sample")
        self.assertEqual(ledger.iloc[0]["paper_gate_tier"], "A")
        self.assertIn("A-tier", ledger.iloc[0]["paper_gate_reason"])

    def test_candidate_ledger_event_dispatch_triggers_contract_gate_for_new_a_tier_row(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            state_csv = data_dir / "candidate_ledger_event_state.csv"
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)

            with patch(
                "run_candidate_ledger_event_dispatcher.build_option_chain_import",
                return_value={
                    "status": "ready",
                    "ready_a_tier_samples": 1,
                    "symbols_requested": 1,
                    "chains_imported": 1,
                    "errors": 0,
                    "rows": [],
                    "columns": [],
                    "guardrail": "test",
                },
            ) as import_builder, patch(
                "run_candidate_ledger_event_dispatcher.write_option_chain_import_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_options_chain_review",
                return_value={
                    "status": "ready",
                    "ready_sample_count": 1,
                    "selected_contract_count": 1,
                    "write_audit": True,
                    "contract_audit_csv": str(data_dir / "options_contract_audit.csv"),
                    "filters": {},
                    "selected_contracts": [],
                    "rows": [],
                    "guardrail": "test",
                },
            ) as review_builder, patch(
                "run_candidate_ledger_event_dispatcher.write_options_chain_review_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_options_contract_gate",
                return_value={
                    "status": "ready",
                    "passed_contract_count": 1,
                    "ready_sample_count": 1,
                    "missing_contract_reviews": 0,
                    "blocked_contract_count": 0,
                    "rows": [],
                    "template_rows": [],
                    "guardrail": "test",
                },
            ) as contract_builder, patch(
                "run_candidate_ledger_event_dispatcher.write_options_contract_gate_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_autonomous_lifecycle",
                return_value={"mode": "autonomous_a_tier_only"},
            ) as lifecycle_builder:
                payload = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=state_csv,
                    chain_dir=data_dir / "options_chains" / "active",
                    contract_audit_csv=data_dir / "options_contract_audit.csv",
                    samples_csv=data_dir / "paper_validation_samples.csv",
                    market={"market_is_open": True, "today": "2026-05-26"},
                )

        self.assertEqual(payload["dispatched_event_count"], 1)
        self.assertEqual(payload["rows"][0]["status"], "completed")
        import_builder.assert_called_once()
        review_builder.assert_called_once()
        contract_builder.assert_called_once()
        lifecycle_builder.assert_called_once()

    def test_candidate_ledger_event_dispatch_does_not_need_current_candle_capture_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)

            with patch(
                "run_candidate_ledger_event_dispatcher.build_option_chain_import",
                return_value={"status": "waiting_for_chain_data", "ready_a_tier_samples": 1, "symbols_requested": 1, "chains_imported": 0, "errors": 0, "rows": [], "columns": [], "guardrail": "test"},
            ) as import_builder, patch(
                "run_candidate_ledger_event_dispatcher.write_option_chain_import_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_options_chain_review",
                return_value={"status": "waiting_for_eligible_contract", "ready_sample_count": 1, "selected_contract_count": 0, "write_audit": True, "contract_audit_csv": "", "filters": {}, "selected_contracts": [], "rows": [], "guardrail": "test"},
            ), patch(
                "run_candidate_ledger_event_dispatcher.write_options_chain_review_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_options_contract_gate",
                return_value={"status": "waiting_for_contract_review", "passed_contract_count": 0, "ready_sample_count": 1, "missing_contract_reviews": 1, "blocked_contract_count": 0, "rows": [], "template_rows": [], "guardrail": "test"},
            ) as contract_builder, patch(
                "run_candidate_ledger_event_dispatcher.write_options_contract_gate_outputs"
            ):
                payload = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=data_dir / "candidate_ledger_event_state.csv",
                    chain_dir=data_dir / "options_chains" / "active",
                    contract_audit_csv=data_dir / "options_contract_audit.csv",
                    samples_csv=data_dir / "paper_validation_samples.csv",
                    market={"market_is_open": True, "today": "2026-05-26"},
                )

        self.assertFalse((output_dir / "current_candle_capture.json").exists())
        self.assertEqual(payload["dispatched_event_count"], 1)
        import_builder.assert_called_once()
        contract_builder.assert_called_once()

    def test_candidate_ledger_event_dispatch_is_idempotent_for_duplicate_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            state_csv = data_dir / "candidate_ledger_event_state.csv"
            pd.DataFrame([a_tier_ledger_row(), a_tier_ledger_row()]).to_csv(ledger_csv, index=False)

            with patch(
                "run_candidate_ledger_event_dispatcher.build_option_chain_import",
                return_value={"status": "ready", "ready_a_tier_samples": 1, "symbols_requested": 1, "chains_imported": 1, "errors": 0, "rows": [], "columns": [], "guardrail": "test"},
            ) as import_builder, patch(
                "run_candidate_ledger_event_dispatcher.write_option_chain_import_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_options_chain_review",
                return_value={"status": "ready", "ready_sample_count": 1, "selected_contract_count": 1, "write_audit": True, "contract_audit_csv": "", "filters": {}, "selected_contracts": [], "rows": [], "guardrail": "test"},
            ), patch(
                "run_candidate_ledger_event_dispatcher.write_options_chain_review_outputs"
            ), patch(
                "run_candidate_ledger_event_dispatcher.build_options_contract_gate",
                return_value={"status": "ready", "passed_contract_count": 0, "ready_sample_count": 1, "missing_contract_reviews": 0, "blocked_contract_count": 0, "rows": [], "template_rows": [], "guardrail": "test"},
            ), patch(
                "run_candidate_ledger_event_dispatcher.write_options_contract_gate_outputs"
            ):
                first = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=state_csv,
                    market={"market_is_open": True, "today": "2026-05-26"},
                )
                second = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=state_csv,
                    market={"market_is_open": True, "today": "2026-05-26"},
                )

        self.assertEqual(first["dispatched_event_count"], 1)
        self.assertEqual(second["dispatched_event_count"], 0)
        import_builder.assert_called_once()

    def test_candidate_ledger_event_dispatch_ignores_stale_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            pd.DataFrame(
                [
                    a_tier_ledger_row(trade_date="2026-05-25"),
                    a_tier_ledger_row(freshness_lane="grace_candle"),
                ]
            ).to_csv(ledger_csv, index=False)

            with patch("run_candidate_ledger_event_dispatcher.build_options_contract_gate") as contract_builder:
                payload = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=data_dir / "candidate_ledger_event_state.csv",
                    market={"market_is_open": True, "today": "2026-05-26"},
                )

        self.assertEqual(payload["eligible_event_count"], 0)
        self.assertEqual(payload["dispatched_event_count"], 0)
        contract_builder.assert_not_called()

    def test_candidate_ledger_event_dispatch_blocks_after_close_replay(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)

            with patch("run_candidate_ledger_event_dispatcher.build_options_contract_gate") as contract_builder, patch(
                "run_candidate_ledger_event_dispatcher.build_autonomous_lifecycle"
            ) as lifecycle_builder:
                payload = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=data_dir / "candidate_ledger_event_state.csv",
                    market={"market_is_open": False, "today": "2026-05-26"},
                )

        self.assertEqual(payload["dispatched_event_count"], 1)
        self.assertEqual(payload["rows"][0]["status"], "blocked_market_closed")
        contract_builder.assert_not_called()
        lifecycle_builder.assert_not_called()

    def test_candidate_ledger_event_dispatch_zero_eligible_candidates_triggers_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            pd.DataFrame([a_tier_ledger_row(paper_gate_status="study_only")]).to_csv(ledger_csv, index=False)

            with patch("run_candidate_ledger_event_dispatcher.build_option_chain_import") as import_builder:
                payload = build_candidate_ledger_event_dispatch(
                    output_dir=output_dir,
                    ledger_csv=ledger_csv,
                    event_state_csv=data_dir / "candidate_ledger_event_state.csv",
                    market={"market_is_open": True, "today": "2026-05-26"},
                )

        self.assertEqual(payload["eligible_event_count"], 0)
        self.assertEqual(payload["dispatched_event_count"], 0)
        import_builder.assert_not_called()

    def test_options_contract_gate_requires_manual_contract_review(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            scanner = pd.DataFrame(
                [
                    scanner_row(
                        passed_condition_count=8,
                        condition_count=9,
                    )
                ]
            )
            scanner.to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_options_contract_gate(
                    output_dir,
                    output_dir / "missing_contract_audit.csv",
                    output_dir / "samples.csv",
                )

        self.assertEqual(payload["status"], "waiting_for_contract_review")
        self.assertEqual(payload["ready_sample_count"], 1)
        self.assertEqual(payload["missing_contract_reviews"], 1)
        self.assertFalse(payload["rows"][0]["contract_gate_pass"])
        self.assertEqual(payload["template_rows"][0]["option_type"], "CALL")

    def test_options_contract_gate_passes_clean_manual_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            contract_csv = output_dir / "options_contract_audit.csv"
            pd.DataFrame(
                [
                    scanner_row(
                        passed_condition_count=8,
                        condition_count=9,
                    )
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "sample_date": "2026-05-26",
                        "entry_time_et": "10:30",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "strategy_id": "vwap_ema_trend_continuation",
                        "sample_tier": "A",
                        "contract_symbol": "SPY260526C00500000",
                        "option_type": "CALL",
                        "expiration": "2026-05-26",
                        "dte": 0,
                        "strike": 500,
                        "delta": 0.55,
                        "bid": 1.20,
                        "ask": 1.30,
                        "mid": 1.25,
                        "spread_pct": 0.08,
                        "volume": 1200,
                        "open_interest": 4000,
                        "implied_volatility": 0.24,
                        "premium": 1.30,
                        "earnings_within_window": "no",
                        "notes": "liquid test contract",
                    }
                ]
            ).to_csv(contract_csv, index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_options_contract_gate(output_dir, contract_csv, output_dir / "samples.csv")

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["passed_contract_count"], 1)
        row = payload["passed_samples"][0]
        self.assertEqual(row["contract_gate_status"], "contract_pass")
        self.assertEqual(row["contract_symbol"], "SPY260526C00500000")
        self.assertAlmostEqual(row["spread_pct"], 0.08)

    def test_options_contract_gate_uses_preserved_candidate_ledger_state_after_scanner_ages(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            contract_csv = output_dir / "options_contract_audit.csv"
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-26",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "source_signal_et": "2026-05-26 10:30",
                        "candidate_entry_et": "2026-05-26 10:30",
                        "freshness_lane": "current_candle",
                        "first_seen_at": "2026-05-26 10:35:00 EDT",
                        "scan_timestamp": "2026-05-26 10:35:00 EDT",
                        "scanner_status": "allowed",
                        "sizing_status": "size_ok",
                        "router_status": "review_first",
                        "paper_gate_status": "ready_for_validation_sample",
                        "paper_gate_tier": "A",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "size": 5,
                        "latest_candle_et": "2026-05-26 10:30",
                        "strategy_id": "vwap_ema_trend_continuation",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "quality_grade": "A",
                        "quality_score": 8,
                        "check_score": 0.8889,
                        "room_to_target_r": 2.0,
                        "relative_volume": 1.4,
                        "risk_per_share": 1.0,
                        "paper_gate_reason": "A-tier: current M30 signal.",
                    }
                ]
            ).to_csv(ledger_csv, index=False)
            pd.DataFrame(
                [
                    {
                        "sample_date": "2026-05-26",
                        "entry_time_et": "10:30",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "strategy_id": "vwap_ema_trend_continuation",
                        "sample_tier": "A",
                        "contract_symbol": "SPY260526C00500000",
                        "option_type": "CALL",
                        "expiration": "2026-05-26",
                        "dte": 0,
                        "strike": 500,
                        "delta": 0.55,
                        "bid": 1.20,
                        "ask": 1.30,
                        "mid": 1.25,
                        "spread_pct": 0.08,
                        "volume": 1200,
                        "open_interest": 4000,
                        "implied_volatility": 0.24,
                        "premium": 1.30,
                        "earnings_within_window": "no",
                        "notes": "liquid test contract",
                    }
                ]
            ).to_csv(contract_csv, index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_options_contract_gate(
                    output_dir,
                    contract_csv,
                    output_dir / "samples.csv",
                    ledger_csv,
                )

        self.assertEqual(payload["promotion_source"], "candidate_window_ledger")
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["ready_sample_count"], 1)
        self.assertEqual(payload["passed_contract_count"], 1)
        row = payload["passed_samples"][0]
        self.assertEqual(row["signal_freshness"], "current_candle")
        self.assertEqual(row["candidate_entry_et"], "2026-05-26 10:30")
        self.assertEqual(row["contract_gate_status"], "contract_pass")

    def test_option_chain_import_feeds_existing_contract_gate_without_manual_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            chain_dir = data_dir / "options_chains"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            samples_csv = data_dir / "paper_validation_samples.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            current_stamp = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
            fetched_chain = pd.DataFrame(
                [
                    option_chain_row(
                        chain_retrieval_timestamp=current_stamp,
                        quote_timestamp=current_stamp,
                        underlying_price_timestamp=current_stamp,
                        calculation_timestamp=current_stamp,
                    )
                ],
                columns=OPTION_CHAIN_COLUMNS,
            )

            with patch(
                "run_option_chain_import.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_option_chain_import.fetch_yfinance_chain",
                return_value=fetched_chain,
            ):
                import_payload = build_option_chain_import(
                    output_dir=output_dir,
                    chain_dir=chain_dir,
                    samples_csv=samples_csv,
                    candidate_ledger_csv=ledger_csv,
                )
                review_payload = build_options_chain_review(
                    argparse.Namespace(
                        output_dir=output_dir,
                        chain_csv=None,
                        chain_dir=chain_dir,
                        symbol=None,
                        tier=["A"],
                        max_dte=0,
                        contract_audit_csv=contract_csv,
                        write_audit=True,
                        allow_missing_option_type=False,
                        samples_csv=samples_csv,
                        candidate_ledger_csv=ledger_csv,
                        account_size=10_000.0,
                        max_chain_age_minutes=20,
                    )
                )
                gate_payload = build_options_contract_gate(
                    output_dir,
                    contract_csv,
                    samples_csv,
                    ledger_csv,
                )

            self.assertEqual(import_payload["status"], "ready")
            self.assertEqual(import_payload["chains_imported"], 1)
            self.assertTrue((chain_dir / "SPY.csv").exists())
            imported = pd.read_csv(chain_dir / "SPY.csv").iloc[0]
            self.assertEqual(imported["delta_source"], "modeled_black_scholes")
            self.assertEqual(imported["delta_model_name"], "black_scholes")
            self.assertEqual(float(imported["risk_free_rate"]), 0.04)
            self.assertEqual(imported["implied_volatility_source"], "provider_impliedVolatility")
            self.assertEqual(float(imported["underlying_price_for_delta"]), 500.0)
            self.assertEqual(imported["calculation_timestamp"], current_stamp)
            self.assertEqual(review_payload["promotion_source"], "candidate_window_ledger")
            self.assertEqual(review_payload["selected_contract_count"], 1)
            self.assertTrue(contract_csv.exists())
            self.assertEqual(gate_payload["passed_contract_count"], 1)
            self.assertEqual(gate_payload["rows"][0]["contract_gate_status"], "contract_pass")

    def test_contract_gate_pass_triggers_autonomous_lifecycle(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            contract_audit_csv=Path("data/options_contract_audit.csv"),
            samples_csv=Path("data/paper_validation_samples.csv"),
            candidate_ledger_csv=Path("data/candidate_window_ledger.csv"),
            account_size=10_000.0,
            skip_autonomous_lifecycle=False,
        )

        with patch("run_options_contract_gate.subprocess.run") as runner:
            triggered = trigger_autonomous_lifecycle(args, {"passed_contract_count": 1})

        self.assertTrue(triggered)
        command = runner.call_args.args[0]
        self.assertIn("run_autonomous_a_tier_lifecycle.py", command)
        self.assertIn("--contract-audit-csv", command)
        self.assertIn("data/options_contract_audit.csv", command)

    def test_contract_gate_without_pass_does_not_trigger_autonomous_lifecycle(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            contract_audit_csv=Path("data/options_contract_audit.csv"),
            samples_csv=Path("data/paper_validation_samples.csv"),
            candidate_ledger_csv=Path("data/candidate_window_ledger.csv"),
            account_size=10_000.0,
            skip_autonomous_lifecycle=False,
        )

        with patch("run_options_contract_gate.subprocess.run") as runner:
            triggered = trigger_autonomous_lifecycle(args, {"passed_contract_count": 0})

        self.assertFalse(triggered)
        runner.assert_not_called()

    def test_option_chain_import_failure_cannot_reuse_previous_active_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            chain_dir = data_dir / "options_chains" / "active"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            chain_path = chain_dir / "SPY.csv"
            write_option_chain_with_metadata(chain_path)
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)

            with patch(
                "run_option_chain_import.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_option_chain_import.fetch_yfinance_chain",
                side_effect=RuntimeError("provider unavailable"),
            ):
                payload = build_option_chain_import(
                    output_dir=output_dir,
                    chain_dir=chain_dir,
                    candidate_ledger_csv=ledger_csv,
                )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["chains_imported"], 0)
            self.assertFalse(chain_path.exists())
            self.assertFalse(option_chain_metadata_path(chain_path).exists())
            self.assertTrue(list((data_dir / "options_chains" / "archive" / "2026-05-26").glob("SPY_*")))

    def test_option_chain_provenance_accepts_fresh_current_session_chain(self) -> None:
        with TemporaryDirectory() as tmp:
            chain_path = Path(tmp) / "active" / "SPY.csv"
            write_option_chain_with_metadata(chain_path)
            chain = pd.read_csv(chain_path)
            ok, reason, _ = validate_chain_provenance(
                chain_path=chain_path,
                chain=chain,
                sample={"symbol": "SPY", "scan_date": "2026-05-26"},
                max_age_minutes=20,
                now=datetime(2026, 5, 26, 10, 40, tzinfo=MARKET_TZ),
            )

        self.assertTrue(ok)
        self.assertEqual(reason, "pass")

    def test_option_chain_provenance_rejects_prior_session_file(self) -> None:
        with TemporaryDirectory() as tmp:
            chain_path = Path(tmp) / "active" / "SPY.csv"
            write_option_chain_with_metadata(chain_path, trading_session_date="2026-05-25")
            chain = pd.read_csv(chain_path)
            ok, reason, _ = validate_chain_provenance(
                chain_path=chain_path,
                chain=chain,
                sample={"symbol": "SPY", "scan_date": "2026-05-26"},
                max_age_minutes=20,
                now=datetime(2026, 5, 26, 10, 40, tzinfo=MARKET_TZ),
            )

        self.assertFalse(ok)
        self.assertIn("blocked_stale_option_chain", reason)

    def test_option_chain_provenance_rejects_same_session_over_age_chain(self) -> None:
        with TemporaryDirectory() as tmp:
            chain_path = Path(tmp) / "active" / "SPY.csv"
            write_option_chain_with_metadata(chain_path)
            chain = pd.read_csv(chain_path)
            ok, reason, _ = validate_chain_provenance(
                chain_path=chain_path,
                chain=chain,
                sample={"symbol": "SPY", "scan_date": "2026-05-26"},
                max_age_minutes=20,
                now=datetime(2026, 5, 26, 11, 10, tzinfo=MARKET_TZ),
            )

        self.assertFalse(ok)
        self.assertIn("over age tolerance", reason)

    def test_option_chain_provenance_rejects_missing_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            chain_path = Path(tmp) / "active" / "SPY.csv"
            chain_path.parent.mkdir(parents=True)
            pd.DataFrame([option_chain_row()], columns=OPTION_CHAIN_COLUMNS).to_csv(chain_path, index=False)
            chain = pd.read_csv(chain_path)
            ok, reason, _ = validate_chain_provenance(
                chain_path=chain_path,
                chain=chain,
                sample={"symbol": "SPY", "scan_date": "2026-05-26"},
                max_age_minutes=20,
                now=datetime(2026, 5, 26, 10, 40, tzinfo=MARKET_TZ),
            )

        self.assertFalse(ok)
        self.assertIn("missing option-chain metadata", reason)

    def test_option_chain_provenance_rejects_symbol_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            chain_path = Path(tmp) / "active" / "SPY.csv"
            write_option_chain_with_metadata(chain_path, symbol="QQQ")
            chain = pd.read_csv(chain_path)
            ok, reason, _ = validate_chain_provenance(
                chain_path=chain_path,
                chain=chain,
                sample={"symbol": "SPY", "scan_date": "2026-05-26"},
                max_age_minutes=20,
                now=datetime(2026, 5, 26, 10, 40, tzinfo=MARKET_TZ),
            )

        self.assertFalse(ok)
        self.assertIn("symbol mismatch", reason)

    def test_option_chain_provenance_rejects_missing_modeled_delta_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            chain_path = Path(tmp) / "active" / "SPY.csv"
            write_option_chain_with_metadata(chain_path, rows=[option_chain_row(underlying_price_for_delta="")])
            chain = pd.read_csv(chain_path)
            ok, reason, _ = validate_chain_provenance(
                chain_path=chain_path,
                chain=chain,
                sample={"symbol": "SPY", "scan_date": "2026-05-26"},
                max_age_minutes=20,
                now=datetime(2026, 5, 26, 10, 40, tzinfo=MARKET_TZ),
            )

        self.assertFalse(ok)
        self.assertIn("modeled delta inputs missing", reason)

    def test_candidate_ledger_promotion_expires_previous_session_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-25",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "source_signal_et": "2026-05-25 10:30",
                        "candidate_entry_et": "2026-05-25 10:30",
                        "freshness_lane": "current_candle",
                        "scanner_status": "allowed",
                        "paper_gate_status": "ready_for_validation_sample",
                        "paper_gate_tier": "A",
                    }
                ]
            ).to_csv(ledger_csv, index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_options_contract_gate(
                    output_dir,
                    output_dir / "missing_contract_audit.csv",
                    output_dir / "samples.csv",
                    ledger_csv,
                )

        self.assertEqual(payload["promotion_source"], "scanner_snapshot")
        self.assertEqual(payload["status"], "waiting_for_chart_candidate")
        self.assertEqual(payload["ready_sample_count"], 0)

    def test_candidate_ledger_promotion_skips_already_imported_samples(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ledger_csv = output_dir / "candidate_window_ledger.csv"
            samples_csv = output_dir / "samples.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-26",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "source_signal_et": "2026-05-26 10:30",
                        "candidate_entry_et": "2026-05-26 10:30",
                        "freshness_lane": "current_candle",
                        "scanner_status": "allowed",
                        "paper_gate_status": "ready_for_validation_sample",
                        "paper_gate_tier": "A",
                    }
                ]
            ).to_csv(ledger_csv, index=False)
            pd.DataFrame(
                [
                    {
                        "sample_date": "2026-05-26",
                        "entry_time_et": "10:30",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                    }
                ]
            ).to_csv(samples_csv, index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_options_contract_gate(
                    output_dir,
                    output_dir / "missing_contract_audit.csv",
                    samples_csv,
                    ledger_csv,
                )

        self.assertEqual(payload["promotion_source"], "scanner_snapshot")
        self.assertEqual(payload["ready_sample_count"], 0)

    def test_autonomous_a_tier_lifecycle_opens_and_imports_clean_contract_pass_after_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            samples_csv = data_dir / "paper_validation_samples.csv"
            paper_csv = data_dir / "paper_trades.csv"
            orders_csv = data_dir / "paper_orders.csv"
            approvals_csv = data_dir / "paper_command_center_approvals.csv"
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            data_dir.mkdir()
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=samples_csv,
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=orders_csv,
                    paper_csv=paper_csv,
                    approvals_csv=approvals_csv,
                    option_chain_dir=chain_dir,
                    now=now,
                )

            self.assertEqual(payload["contract_passed_candidates"], 1)
            self.assertEqual(payload["auto_approvals_written"], 1)
            self.assertEqual(payload["paper_orders_written"], 1)
            self.assertEqual(payload["open_paper_trades_written"], 1)
            self.assertEqual(payload["validation_rows_written"], 1)
            self.assertTrue(approvals_csv.exists())
            self.assertTrue(orders_csv.exists())
            self.assertTrue(paper_csv.exists())
            self.assertTrue(samples_csv.exists())
            trade = pd.read_csv(paper_csv).iloc[0]
            sample = pd.read_csv(samples_csv).iloc[0]
            self.assertEqual(trade["symbol"], "SPY")
            self.assertEqual(sample["sample_tier"], "A")
            self.assertEqual(sample["contract_gate_status"], "contract_pass")

    def test_autonomous_a_tier_lifecycle_duplicate_prevention_keeps_single_entry_and_sample(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            samples_csv = data_dir / "paper_validation_samples.csv"
            paper_csv = data_dir / "paper_trades.csv"
            orders_csv = data_dir / "paper_orders.csv"
            approvals_csv = data_dir / "paper_command_center_approvals.csv"
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                first = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=samples_csv,
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=orders_csv,
                    paper_csv=paper_csv,
                    approvals_csv=approvals_csv,
                    option_chain_dir=chain_dir,
                    now=now,
                )
                second = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=samples_csv,
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=orders_csv,
                    paper_csv=paper_csv,
                    approvals_csv=approvals_csv,
                    option_chain_dir=chain_dir,
                    now=now,
                )

            self.assertEqual(first["open_paper_trades_written"], 1)
            self.assertEqual(first["validation_rows_written"], 1)
            self.assertEqual(second["open_paper_trades_written"], 0)
            self.assertEqual(second["validation_rows_written"], 0)
            self.assertEqual(len(pd.read_csv(paper_csv)), 1)
            self.assertEqual(len(pd.read_csv(samples_csv)), 1)

    def test_autonomous_lifecycle_blocks_after_hours_contract_pass_without_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            after_close = datetime(2026, 5, 26, 16, 5, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, after_close)
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": False, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": False, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=after_close,
                )

            self.assertEqual(payload["auto_approvals_written"], 0)
            self.assertEqual(payload["paper_orders_written"], 0)
            self.assertEqual(payload["open_paper_trades_written"], 0)
            self.assertEqual(payload["validation_rows_written"], 0)
            self.assertEqual(payload["rows"][0]["reason"], "blocked_market_closed")
            self.assertFalse((data_dir / "orders.csv").exists())
            self.assertFalse((data_dir / "paper.csv").exists())
            self.assertFalse((data_dir / "samples.csv").exists())
            self.assertFalse((data_dir / "approvals.csv").exists())

    def test_autonomous_lifecycle_blocks_expired_entry_window_without_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            late = datetime(2026, 5, 26, 15, 20, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, late)
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=late,
                )

            self.assertEqual(payload["paper_orders_written"], 0)
            self.assertEqual(payload["rows"][0]["reason"], "blocked_entry_window_expired")

    def test_autonomous_lifecycle_blocks_stale_chain_provenance_without_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            write_green_heartbeat(output_dir, now)
            chain_dir = data_dir / "options_chains" / "active"
            stale_ts = "2026-05-26 10:00:00 EDT"
            write_option_chain_with_metadata(
                chain_dir / "SPY.csv",
                rows=[option_chain_row(chain_retrieval_timestamp=stale_ts, underlying_price_timestamp=stale_ts, calculation_timestamp=stale_ts)],
                chain_retrieval_timestamp=stale_ts,
                underlying_price_timestamp=stale_ts,
                calculation_timestamp=stale_ts,
            )
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )

            self.assertEqual(payload["paper_orders_written"], 0)
            self.assertEqual(payload["rows"][0]["reason"], "blocked_stale_contract_chain")

    def test_autonomous_lifecycle_blocks_invalid_heartbeat_without_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            (output_dir / "production_heartbeat.json").write_text(
                json.dumps({"generated_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"), "status": "RED", "experiment_valid_today": False}),
                encoding="utf-8",
            )
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )

            self.assertEqual(payload["paper_orders_written"], 0)
            self.assertEqual(payload["rows"][0]["reason"], "blocked_invalid_session")

    def test_invalidated_retroactive_rows_do_not_count_toward_gate_one(self) -> None:
        samples = pd.DataFrame(
            [
                {
                    "sample_tier": "A",
                    "counts_toward_30": True,
                    "outcome_r": "",
                    "invalid_for_validation": "true",
                    "invalid_reason": "retroactive_after_hours_entry",
                },
                {
                    "sample_tier": "A",
                    "counts_toward_30": True,
                    "outcome_r": "1.0",
                    "invalid_for_validation": "",
                    "invalid_reason": "",
                },
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "trade_date": "2026-07-14",
                    "entry_time_et": "15:00",
                    "actual_exit": "",
                    "outcome_r": "",
                    "invalid_for_validation": "true",
                },
                {
                    "trade_date": "2026-07-14",
                    "entry_time_et": "10:30",
                    "actual_exit": "",
                    "outcome_r": "",
                    "invalid_for_validation": "",
                },
            ]
        )

        ship = official_sample_progress(samples)
        gate = sample_counts(samples)
        open_rows = open_paper_rows(trades)

        self.assertEqual(ship["official_validation_samples"], 1)
        self.assertEqual(ship["completed_official_paper_trades"], 1)
        self.assertEqual(gate["official_validation_samples"], 1)
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(str(open_rows.iloc[0]["entry_time_et"]), "10:30")

    def test_autonomous_lifecycle_leaves_b_tier_manual(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    a_tier_ledger_row(
                        paper_gate_tier="B",
                        freshness_lane="grace_candle",
                        candidate_entry_et="2026-05-26 11:00",
                    )
                ]
            ).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row(sample_tier="B", entry_time_et="11:00")]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )

        self.assertEqual(payload["paper_orders_written"], 0)
        self.assertEqual(payload["rows"][0]["reason"], "blocked_manual_tier")

    def test_autonomous_lifecycle_leaves_stale_rows_manual(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row(trade_date="2026-05-25")]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row(sample_date="2026-05-25")]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )

        self.assertEqual(payload["contract_passed_candidates"], 0)
        self.assertEqual(payload["paper_orders_written"], 0)

    def test_autonomous_lifecycle_leaves_ambiguous_contract_manual(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row(contract_symbol="")]).to_csv(contract_csv, index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                payload = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=data_dir / "paper.csv",
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )

        self.assertEqual(payload["contract_passed_candidates"], 1)
        self.assertEqual(payload["paper_orders_written"], 0)
        self.assertEqual(payload["rows"][0]["reason"], "blocked_ambiguous_contract")

    def test_autonomous_lifecycle_confirms_deterministic_exit_once(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            ledger_csv = data_dir / "candidate_window_ledger.csv"
            contract_csv = data_dir / "options_contract_audit.csv"
            paper_csv = data_dir / "paper_trades.csv"
            now = datetime(2026, 5, 26, 10, 36, tzinfo=MARKET_TZ)
            chain_dir = write_lifecycle_safety_artifacts(output_dir, data_dir, now)
            pd.DataFrame([scanner_row(signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([a_tier_ledger_row()]).to_csv(ledger_csv, index=False)
            pd.DataFrame([clean_contract_audit_row()]).to_csv(contract_csv, index=False)
            pd.DataFrame(
                [
                    {"datetime": "2026-05-26T14:35:00Z", "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1000},
                    {"datetime": "2026-05-26T14:40:00Z", "open": 100.1, "high": 102.2, "low": 100.0, "close": 102.0, "volume": 1200},
                ]
            ).to_csv(output_dir / "webull_SPY_M5_candles.csv", index=False)

            with patch(
                "run_autonomous_a_tier_lifecycle.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ), patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                first = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=paper_csv,
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )
                second = build_autonomous_a_tier_lifecycle(
                    output_dir=output_dir,
                    contract_audit_csv=contract_csv,
                    samples_csv=data_dir / "samples.csv",
                    candidate_ledger_csv=ledger_csv,
                    paper_orders_csv=data_dir / "orders.csv",
                    paper_csv=paper_csv,
                    approvals_csv=data_dir / "approvals.csv",
                    option_chain_dir=chain_dir,
                    now=now,
                )

            trades = pd.read_csv(paper_csv)
            self.assertEqual(first["exit_updates_confirmed"], 1)
            self.assertEqual(second["exit_updates_confirmed"], 0)
            self.assertEqual(trades.iloc[0]["exit_reason"], "profit_target_5m")
            self.assertEqual(float(trades.iloc[0]["outcome_r"]), 2.0)

    def test_autonomous_lifecycle_does_not_confirm_b_tier_exit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            paper_csv = data_dir / "paper_trades.csv"
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-26",
                        "entry_time_et": "10:30",
                        "exit_time_et": "",
                        "symbol": "SPY",
                        "setup": "Setup B Long",
                        "direction": "long",
                        "signal_status": "allowed",
                        "planned_entry": 100.0,
                        "planned_stop": 99.0,
                        "planned_target": 102.0,
                        "actual_entry": 100.0,
                        "actual_exit": "",
                        "shares": 5,
                        "vehicle": "options",
                        "risk_tier": "B",
                        "planned_option_premium": 1.3,
                        "outcome_r": "",
                        "followed_plan": "",
                        "exit_reason": "",
                        "notes": "Manual B-tier paper row.",
                    }
                ]
            ).to_csv(paper_csv, index=False)
            pd.DataFrame(
                [
                    {"datetime": "2026-05-26T14:35:00Z", "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1000},
                    {"datetime": "2026-05-26T14:40:00Z", "open": 100.1, "high": 102.2, "low": 100.0, "close": 102.0, "volume": 1200},
                ]
            ).to_csv(output_dir / "webull_SPY_M5_candles.csv", index=False)

            monitor_updates, exits_confirmed = run_autonomous_a_tier_exit_monitor(output_dir=output_dir, paper_csv=paper_csv)
            trades = pd.read_csv(paper_csv)

        self.assertEqual(monitor_updates, 1)
        self.assertEqual(exits_confirmed, 0)
        self.assertTrue(pd.isna(trades.iloc[0]["actual_exit"]))

    def test_paper_validation_sample_import_requires_contract_gate_and_explicit_confirmation(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            samples = output_dir / "samples.csv"
            contract_csv = output_dir / "options_contract_audit.csv"
            pd.DataFrame(
                [
                    scanner_row(
                        scanner_status="allowed",
                        latest_signal_et="2026-05-26 10:30",
                        source_signal_et="2026-05-26 10:30",
                        candidate_entry_et="2026-05-26 11:00",
                        latest_candle_et="2026-05-26 11:00",
                        signal_freshness="grace_candle",
                        validation_lane="B",
                        fresh_plan_source="latest_grace_candle",
                        quality_score=6,
                        quality_grade="B",
                        room_to_target_r=0.6,
                        passed_condition_count=7,
                        condition_count=9,
                        missing_conditions="relative volume >= 1.0",
                    )
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            with patch(
                "run_paper_gate_v2.market_refresh_state",
                return_value={"market_is_open": True, "today": "2026-05-26"},
            ):
                preview = build_validation_sample_import(output_dir, samples, contract_csv, confirm_samples=False)
                self.assertEqual(preview["mode"], "preview")
                self.assertEqual(preview["ready_candidates"], 1)
                self.assertEqual(preview["contract_ready_candidates"], 0)
                self.assertEqual(preview["new_rows"], 0)
                self.assertFalse(samples.exists())
                pd.DataFrame(
                    [
                        {
                            "sample_date": "2026-05-26",
                            "entry_time_et": "11:00",
                            "symbol": "SPY",
                            "setup": "Setup A Long",
                            "direction": "long",
                            "strategy_id": "vwap_ema_trend_continuation",
                            "sample_tier": "B",
                            "contract_symbol": "SPY260526C00500000",
                            "option_type": "CALL",
                            "expiration": "2026-05-26",
                            "dte": 0,
                            "strike": 500,
                            "delta": 0.55,
                            "bid": 1.20,
                            "ask": 1.30,
                            "mid": 1.25,
                            "spread_pct": 0.08,
                            "volume": 1200,
                            "open_interest": 4000,
                            "implied_volatility": 0.24,
                            "premium": 1.30,
                            "earnings_within_window": "no",
                            "notes": "liquid test contract",
                        }
                    ]
                ).to_csv(contract_csv, index=False)
                confirmed = build_validation_sample_import(output_dir, samples, contract_csv, confirm_samples=True)
                duplicate = build_validation_sample_import(output_dir, samples, contract_csv, confirm_samples=True)

            self.assertEqual(confirmed["new_rows"], 1)
            self.assertIn("generated_at_et", confirmed)
            self.assertTrue(samples.exists())
            self.assertEqual(duplicate["new_rows"], 0)
            ledger = pd.read_csv(samples)
            self.assertEqual(ledger.iloc[0]["sample_tier"], "B")
            self.assertEqual(ledger.iloc[0]["signal_freshness"], "grace_candle")
            self.assertEqual(ledger.iloc[0]["validation_lane"], "B")
            self.assertEqual(ledger.iloc[0]["source_signal_et"], "2026-05-26 10:30")
            self.assertEqual(ledger.iloc[0]["candidate_entry_et"], "2026-05-26 11:00")
            self.assertEqual(ledger.iloc[0]["contract_gate_status"], "contract_pass")
            self.assertEqual(ledger.iloc[0]["contract_symbol"], "SPY260526C00500000")
            self.assertTrue(bool(ledger.iloc[0]["counts_toward_30"]))

    def test_paper_validation_sample_import_syncs_completed_official_trade_outcomes(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            samples = output_dir / "paper_validation_samples.csv"
            paper_csv = output_dir / "paper_trades.csv"
            contract_csv = output_dir / "options_contract_audit.csv"
            pd.DataFrame(
                [
                    {
                        "sample_date": "2026-05-26",
                        "entry_time_et": "10:30",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "sample_tier": "A",
                        "sample_status": "open",
                        "counts_toward_30": True,
                        "counts_toward_live_readiness": True,
                        "actual_entry": "",
                        "actual_exit": "",
                        "exit_time_et": "",
                        "outcome_r": "",
                        "followed_plan": "",
                        "exit_reason": "",
                        "source_contract_gate_identity": "",
                    }
                ]
            ).to_csv(samples, index=False)
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-26",
                        "entry_time_et": "10:30",
                        "exit_time_et": "10:55",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "actual_entry": 100.0,
                        "actual_exit": 99.0,
                        "outcome_r": -1.0,
                        "followed_plan": "yes",
                        "exit_reason": "stop_loss_5m",
                        "source_contract_gate_identity": "2026-05-26|10:30|SPY|setup a long|long",
                    }
                ]
            ).to_csv(paper_csv, index=False)
            pd.DataFrame().to_csv(contract_csv, index=False)

            payload = build_validation_sample_import(
                output_dir,
                samples,
                contract_csv,
                confirm_samples=False,
                paper_csv=paper_csv,
            )
            ledger = pd.read_csv(samples)
            ship = build_ship_report(output_dir, samples)

        self.assertEqual(payload["mode"], "preview")
        self.assertEqual(payload["new_rows"], 0)
        self.assertEqual(payload["synced_outcome_rows"], 1)
        self.assertEqual(ledger.iloc[0]["sample_status"], "completed")
        self.assertEqual(float(ledger.iloc[0]["outcome_r"]), -1.0)
        self.assertEqual(str(ledger.iloc[0]["exit_time_et"]), "10:55")
        self.assertEqual(ledger.iloc[0]["source_contract_gate_identity"], "2026-05-26|10:30|SPY|setup a long|long")
        self.assertEqual(ship["completed_official_paper_trades"], 1)
        self.assertEqual(ship["open_official_paper_trades"], 0)
        self.assertEqual(ship["remaining_to_30"], 29)

    def test_trend_pullback_playbook_entries_are_scanner_visible(self) -> None:
        entries = playbook_entries_for_scan("approved_plus_watch", ["SPY", "QQQ"])
        trend_entries = [entry for entry in entries if entry.variant.startswith("trend_pullback")]

        routes = {(entry.symbol, entry.variant): entry for entry in trend_entries}
        self.assertIn(("SPY", "trend_pullback_long"), routes)
        self.assertIn(("QQQ", "trend_pullback_long"), routes)
        self.assertIn(("SPY", "trend_pullback_short"), routes)
        self.assertIn(("QQQ", "trend_pullback_short"), routes)
        self.assertTrue(all(entry.status == "watch_more" for entry in trend_entries))

    def test_trend_pullback_scanner_uses_strategy_specific_columns_and_direction(self) -> None:
        entries = playbook_entries_for_scan("approved_plus_watch", ["SPY"])
        long_entry = next(entry for entry in entries if entry.variant == "trend_pullback_long")
        short_entry = next(entry for entry in entries if entry.variant == "trend_pullback_short")

        self.assertEqual(long_entry.variant, "trend_pullback_long")
        self.assertEqual(selected_signal_column(long_entry), "trend_pullback_long_signal")
        self.assertEqual(entry_direction(long_entry), "long")
        self.assertEqual(short_entry.variant, "trend_pullback_short")
        self.assertEqual(selected_signal_column(short_entry), "trend_pullback_short_signal")
        self.assertEqual(entry_direction(short_entry), "short")

    def test_strategy_registry_maps_router_simulator_and_chart_contracts(self) -> None:
        trade_logs = {strategy_id: filename for strategy_id, _, filename in strategy_vault_trade_logs()}

        self.assertEqual(
            strategy_id_for_scanner("Trend Pullback Short", "trend_pullback_short"),
            "trend_pullback_continuation",
        )
        self.assertEqual(strategy_id_for_scanner("Setup C Full-Session Short", "setup_b_quality_full_session"), "vwap_ema_trend_continuation")
        self.assertEqual(chart_marker_label_for_setup("Trend Pullback Short", "trend_pullback_short"), "P")
        self.assertEqual(trade_logs["trend_pullback_continuation"], "trend_pullback_continuation_trades.csv")

    def test_app_report_registry_exposes_new_strategy_evidence_lanes(self) -> None:
        self.assertEqual(
            run_app.ALLOWED_REPORTS["gap_fill_fade_shadow_samples"],
            "gap_fill_fade_shadow_samples.md",
        )
        self.assertEqual(
            run_app.ALLOWED_REPORTS["research_strategy_tightened_review"],
            "research_strategy_tightened_review.md",
        )
        self.assertEqual(
            run_app.ALLOWED_REPORTS["gap_fill_fade_tightened_review"],
            "gap_fill_fade_tightened_review.md",
        )
        self.assertEqual(
            run_app.ALLOWED_REPORTS["opening_range_breakout_forward_observations"],
            "opening_range_breakout_forward_observations.md",
        )
        self.assertEqual(
            run_app.ALLOWED_REPORTS["opening_range_breakout_walk_forward_deepening"],
            "opening_range_breakout_walk_forward_deepening.md",
        )
        self.assertEqual(
            run_app.ALLOWED_REPORTS["opening_range_failure_paper_watch_gate"],
            "opening_range_failure_paper_watch_gate.md",
        )
        self.assertEqual(
            run_app.ALLOWED_REPORTS["opening_range_failure_walk_forward_deepening"],
            "opening_range_failure_walk_forward_deepening.md",
        )
        self.assertEqual(run_app.ALLOWED_REPORTS["market_regime_router"], "market_regime_router.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["market_sprint_mode"], "market_sprint_mode.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["probation_watch"], "probation_watch.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["controlled_universe_expansion"], "controlled_universe_expansion.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["paper_gate_v2"], "paper_gate_v2.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["options_contract_gate"], "options_contract_gate.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["paper_validation_sample_import"], "paper_validation_sample_import.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["daily_ship_report"], "DAILY_SHIP_REPORT.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["current_candle_capture"], "current_candle_capture.md")
        self.assertEqual(run_app.ALLOWED_REPORTS["strategy_triage"], "strategy_triage.md")

    def test_system_state_exposes_new_strategy_evidence_file_sources(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)

            state = build_system_state(output_dir=output_dir, paper_csv=output_dir / "paper.csv")

        source_files = state["source_files"]
        source_file_states = state["app_health"]["source_file_states"]
        self.assertIn("gap_fill_fade_shadow_samples_csv", source_files)
        self.assertIn("research_strategy_tightened_review_json", source_files)
        self.assertIn("gap_fill_fade_tightened_review_csv", source_files)
        self.assertIn("opening_range_breakout_forward_observation_results_csv", source_files)
        self.assertIn("opening_range_breakout_walk_forward_deepening_csv", source_files)
        self.assertIn("opening_range_failure_paper_watch_gate_json", source_files)
        self.assertIn("opening_range_failure_walk_forward_deepening_csv", source_files)
        self.assertIn("strategy_triage_json", source_files)
        self.assertIn("market_sprint_mode_json", source_files)
        self.assertIn("controlled_universe_expansion_csv", source_files)
        self.assertIn("probation_watch_ledger_csv", source_files)
        self.assertIn("paper_gate_v2_csv", source_files)
        self.assertIn("options_contract_gate_csv", source_files)
        self.assertIn("options_contract_audit_csv", source_files)
        self.assertIn("paper_validation_samples_csv", source_files)
        self.assertIn("gap_fill_fade_shadow_outcomes_csv", source_file_states)
        self.assertIn("research_strategy_tightened_review_json", source_file_states)
        self.assertIn("gap_fill_fade_tightened_review_csv", source_file_states)
        self.assertIn("opening_range_breakout_forward_observation_results_csv", source_file_states)
        self.assertIn("opening_range_breakout_walk_forward_deepening_csv", source_file_states)
        self.assertIn("opening_range_failure_paper_watch_gate_json", source_file_states)
        self.assertIn("opening_range_failure_walk_forward_deepening_csv", source_file_states)
        self.assertIn("strategy_triage_json", source_file_states)
        self.assertIn("market_sprint_mode_json", source_file_states)
        self.assertIn("controlled_universe_expansion_csv", source_file_states)
        self.assertIn("probation_watch_ledger_csv", source_file_states)
        self.assertIn("paper_gate_v2_csv", source_file_states)
        self.assertIn("options_contract_gate_csv", source_file_states)
        self.assertIn("options_contract_audit_csv", source_file_states)
        self.assertIn("paper_validation_samples_csv", source_file_states)

    def test_feature_wiring_audit_tracks_research_report_files(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.md").write_text("# Strategy Vault\n", encoding="utf-8")

            payload = build_feature_wiring_payload(output_dir, output_dir)

        report_keys = {row["report_key"]: row for row in payload["report_rows"]}
        self.assertEqual(report_keys["strategy_vault"]["status"], "present")
        self.assertEqual(report_keys["options_contract_gate"]["status"], "missing")
        self.assertEqual(report_keys["gap_fill_fade_shadow_samples"]["status"], "missing")
        self.assertIn("gap_fill_fade_shadow_samples", payload["missing_reports"])
        contract_rows = {row["strategy_id"]: row for row in payload["strategy_contract_rows"]}
        self.assertEqual(contract_rows["trend_pullback_continuation"]["chart_marker"], "P")
        self.assertEqual(
            contract_rows["trend_pullback_continuation"]["historical_trade_log"],
            "trend_pullback_continuation_trades.csv",
        )
        self.assertIn("trend_pullback_continuation", payload["missing_strategy_contracts"])
        adapter_rows = {
            (row["symbol"], row["setup"], row["variant"]): row
            for row in payload["scanner_adapter_rows"]
        }
        trend_adapter = adapter_rows[("SPY", "Trend Pullback Short", "trend_pullback_short")]
        self.assertEqual(trend_adapter["registry_strategy_id"], "trend_pullback_continuation")
        self.assertEqual(trend_adapter["adapter_strategy_id"], "trend_pullback_continuation")
        self.assertEqual(trend_adapter["signal_column"], "trend_pullback_short_signal")
        self.assertEqual(trend_adapter["direction"], "short")
        self.assertEqual(payload["missing_scanner_adapters"], [])
        self.assertEqual(payload["status"], "warn")

    def test_home_page_exposes_strategy_contract_status_panel(self) -> None:
        html = Path("app/index.html").read_text(encoding="utf-8")
        script = Path("app/app.js").read_text(encoding="utf-8")

        self.assertIn('id="strategy-contract-status"', html)
        self.assertIn('id="strategy-contract-adapters"', html)
        self.assertIn('id="strategy-contract-missing-contracts"', html)
        self.assertIn("renderStrategyContractStatus", script)
        self.assertIn("feature_wiring_audit", script)

    def test_autonomous_supervisor_recalculates_market_scan_wait_after_run(self) -> None:
        args = argparse.Namespace(interval_minutes=5)
        decision = choose_action(
            datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ),
            interval_minutes=5,
            premarket_minutes_before_open=15,
        )

        with patch(
            "run_autonomous_paper_workflow.now_et",
            return_value=datetime(2026, 5, 26, 10, 7, tzinfo=MARKET_TZ),
        ):
            wait_seconds = sleep_after_action(args, decision)

        self.assertEqual(wait_seconds, 180)

    def test_autonomous_supervisor_commands_do_not_auto_import_paper_trades(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            pause=5.0,
            account_size=10_000.0,
            risk_per_trade_pct=0.005,
            auto_confirm_paper_exits=False,
        )

        command_text = " ".join(" ".join(command) for command in commands_for_action("market_scan", args))

        self.assertIn("run_current_candle_capture.py", command_text)
        self.assertNotIn("--append-current-signals", command_text)
        self.assertNotIn("--auto-confirm-paper-exits", command_text)
        self.assertNotIn("run_paper_import.py", command_text)

    def test_autonomous_supervisor_can_auto_confirm_local_paper_exits_only(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            pause=5.0,
            account_size=10_000.0,
            risk_per_trade_pct=0.005,
            auto_confirm_paper_exits=True,
        )

        command_text = " ".join(" ".join(command) for command in commands_for_action("market_scan", args))

        self.assertIn("run_current_candle_capture.py", command_text)
        self.assertIn("--auto-confirm-paper-exits", command_text)
        self.assertNotIn("--append-current-signals", command_text)
        self.assertNotIn("run_paper_import.py", command_text)

    def test_vwap_reclaim_gate_blocks_without_forward_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "tightened_review": "passes_tightened_research",
                    }
                ]
            ).to_csv(output_dir / "vwap_reclaim_reject_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "decision": "holding_up",
                    }
                ]
            ).to_csv(output_dir / "vwap_reclaim_reject_walk_forward.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "evaluation_status": "matured",
                        "hypothetical_r": 0.35,
                    }
                ]
            ).to_csv(output_dir / "vwap_reclaim_reject_shadow_outcomes.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_tightened_pass_rows=1,
                min_walk_forward_holding_rows=1,
                min_shadow_samples=1,
                min_matured_shadow_samples=1,
                min_shadow_average_r=0.1,
                min_forward_observations=1,
                min_matured_forward_observations=1,
                min_forward_average_r=0.1,
            )

            payload, checklist = build_vwap_reclaim_gate(args)

        self.assertEqual(payload["decision"], "not_ready")
        self.assertEqual(payload["next_blocker"], "Forward observations logged")
        self.assertEqual(payload["tightened_pass_rows"], 1)
        self.assertEqual(payload["walk_forward_holding_rows"], 1)
        self.assertEqual(payload["matured_shadow_samples"], 1)
        self.assertIn("Forward observations logged", checklist["check"].tolist())

    def test_vwap_reclaim_maturity_review_explains_remaining_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "vwap_reclaim_reject_paper_watch_gate.json").write_text(
                json.dumps(
                    {
                        "decision": "not_ready",
                        "blocked_count": 6,
                        "next_blocker": "Shadow samples logged",
                        "tightened_pass_rows": 2,
                        "walk_forward_holding_rows": 2,
                        "shadow_samples": 4,
                        "matured_shadow_samples": 0,
                        "shadow_average_r": 0.0,
                        "forward_observations": 4,
                        "matured_forward_observations": 0,
                        "forward_average_r": 0.0,
                        "checks": [
                            {
                                "check": "Tightened research pass",
                                "status": "pass",
                                "current": 2,
                                "required": 1,
                                "reason": "At least one row must pass.",
                            },
                            {
                                "check": "Walk-forward holding up",
                                "status": "pass",
                                "current": 2,
                                "required": 1,
                                "reason": "The newer half must hold up.",
                            },
                            {
                                "check": "Shadow samples logged",
                                "status": "blocked",
                                "current": 4,
                                "required": 10,
                                "reason": "Collect enough strategy-specific shadow sightings.",
                            },
                            {
                                "check": "Matured shadow outcomes",
                                "status": "blocked",
                                "current": 0,
                                "required": 5,
                                "reason": "Enough shadow samples must have completed outcomes.",
                            },
                            {
                                "check": "Forward observations logged",
                                "status": "blocked",
                                "current": 4,
                                "required": 10,
                                "reason": "Collect enough real-time observations.",
                            },
                            {
                                "check": "Matured forward outcomes",
                                "status": "blocked",
                                "current": 0,
                                "required": 5,
                                "reason": "Enough forward observations must have completed outcomes.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                output_dir=output_dir,
                min_tightened_pass_rows=1,
                min_walk_forward_holding_rows=1,
                min_shadow_samples=10,
                min_matured_shadow_samples=5,
                min_shadow_average_r=0.1,
                min_forward_observations=10,
                min_matured_forward_observations=5,
                min_forward_average_r=0.1,
            )

            payload, checklist = build_vwap_reclaim_maturity_review(output_dir, args)

        self.assertEqual(payload["paper_watch_decision"], "not_ready")
        self.assertEqual(payload["next_blocker"], "Shadow samples logged")
        self.assertEqual(payload["shadow_samples_needed"], 6)
        self.assertEqual(payload["matured_shadow_needed"], 5)
        self.assertEqual(payload["forward_observations_needed"], 6)
        self.assertEqual(payload["matured_forward_needed"], 5)
        self.assertIn("does not place broker orders", payload["guardrail"])
        rows = {row["check"]: row for row in checklist.to_dict("records")}
        self.assertEqual(rows["Shadow samples logged"]["needed"], 6)
        self.assertIn("Collect 6 more", rows["Shadow samples logged"]["next_action"])

    def test_vwap_reclaim_forward_observations_dedupe_repeated_scan(self) -> None:
        shadow_row = {column: "" for column in VWAP_RECLAIM_SAMPLE_COLUMNS}
        shadow_row.update(
            {
                "observed_at_et": "2026-05-26 10:35:00 EDT",
                "scan_date": "2026-05-26",
                "entry_time_et": "2026-05-26 10:30",
                "symbol": "QQQ",
                "strategy": "vwap_reclaim_reject",
                "direction": "long",
                "signal_column": "vwap_reclaim_long_signal",
                "shadow_status": "strategy_shadow_candidate",
                "shadow_reason": "test",
                "planned_entry": 100.0,
                "planned_stop": 99.0,
                "planned_target": 101.25,
                "risk_per_share": 1.0,
            }
        )
        candidates = vwap_reclaim_shadow_to_observations(pd.DataFrame([shadow_row]))
        appended = vwap_reclaim_observation_dedupe(candidates, candidates)

        self.assertTrue(appended.empty)

    def test_trend_pullback_forward_observations_dedupe_repeated_scan(self) -> None:
        shadow_row = {column: "" for column in TREND_PULLBACK_SAMPLE_COLUMNS}
        shadow_row.update(
            {
                "observed_at_et": "2026-06-03 10:05:00 EDT",
                "scan_date": "2026-06-03",
                "entry_time_et": "2026-06-03 10:00",
                "symbol": "QQQ",
                "strategy": "trend_pullback_continuation",
                "direction": "long",
                "signal_column": "trend_pullback_long_signal",
                "shadow_status": "strategy_shadow_candidate",
                "shadow_reason": "test",
                "planned_entry": 100.0,
                "planned_stop": 99.0,
                "planned_target": 101.5,
                "risk_per_share": 1.0,
            }
        )
        candidates = trend_pullback_shadow_to_observations(pd.DataFrame([shadow_row]))
        appended = trend_pullback_observation_dedupe(candidates, candidates)

        self.assertTrue(appended.empty)
        self.assertEqual(candidates.iloc[0]["observation_status"], "strategy_forward_observation")

    def test_trend_pullback_gate_blocks_until_evidence_counts_mature(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {"decision": "provisional_tightened_pass"},
                    {"decision": "provisional_tightened_pass"},
                ]
            ).to_csv(output_dir / "trend_pullback_continuation_tightened_review.csv", index=False)
            pd.DataFrame([{"decision": "holding_up"}]).to_csv(
                output_dir / "trend_pullback_continuation_walk_forward.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {"evaluation_status": "matured", "hypothetical_r": 0.8},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                ]
            ).to_csv(output_dir / "trend_pullback_continuation_shadow_outcomes.csv", index=False)
            pd.DataFrame(
                [
                    {"evaluation_status": "matured", "hypothetical_r": 0.8},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                ]
            ).to_csv(output_dir / "trend_pullback_continuation_forward_observation_results.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_tightened_pass_rows=1,
                min_walk_forward_holding_rows=1,
                min_shadow_samples=10,
                min_matured_shadow_samples=5,
                min_shadow_average_r=0.1,
                min_forward_observations=10,
                min_matured_forward_observations=5,
                min_forward_average_r=0.1,
            )

            payload, checklist = build_trend_pullback_gate(args)

        self.assertEqual(payload["decision"], "not_ready")
        self.assertEqual(payload["tightened_pass_rows"], 2)
        self.assertEqual(payload["provisional_tightened_pass_rows"], 2)
        self.assertEqual(payload["next_blocker"], "Shadow samples logged")
        self.assertIn("No broker orders", payload["guardrail"])
        self.assertIn("Shadow samples logged", checklist[checklist["status"] == "blocked"]["check"].tolist())

    def test_phase_milestones_summarize_roadmap_without_execution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "daily_automation_timeline.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            (output_dir / "refresh_status.json").write_text(
                json.dumps(
                    {
                        "status": "prep_only",
                        "paper_import_blocked": True,
                        "reason": "Market is closed.",
                        "next_action": "Refresh during market hours.",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "pre_entry_review.json").write_text(json.dumps({"ready_for_manual_review": 0}), encoding="utf-8")
            (output_dir / "market_regime_router.json").write_text(
                json.dumps(
                    {
                        "review_first_count": 0,
                        "caution_review_count": 1,
                        "next_action": "Keep scanning.",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps({"eligible_strategy_count": 0}),
                encoding="utf-8",
            )
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "active_strategy_count": 0,
                        "research_priority_count": 4,
                        "selector": {"research_only_strategy_count": 6},
                        "strategies": [{"strategy_id": f"strategy_{index}"} for index in range(7)],
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "vwap_reclaim_reject_paper_watch_gate.json").write_text(
                json.dumps(
                    {
                        "decision": "not_ready",
                        "tightened_pass_rows": 2,
                        "walk_forward_holding_rows": 2,
                        "shadow_samples": 3,
                        "matured_shadow_samples": 0,
                        "forward_observations": 3,
                        "matured_forward_observations": 0,
                        "next_blocker": "Shadow samples logged",
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame([{"symbol": "QQQ", "status": "ok"}]).to_csv(output_dir / "candle_data_integrity.csv", index=False)
            pd.DataFrame([{"queue_status": "almost_ready"}]).to_csv(output_dir / "forward_sample_queue.csv", index=False)
            pd.DataFrame([scanner_row(scanner_status="allowed", signal_freshness="earlier_today")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            pd.DataFrame([{"symbol": "SPY", "sizing_status": "blocked"}]).to_csv(
                output_dir / "position_sizing.csv",
                index=False,
            )

            payload = build_milestones(output_dir)

        self.assertEqual(payload["current_phase"], "Paper Candidate Pipeline")
        self.assertEqual(payload["status"], "in_progress")
        self.assertEqual(payload["queue_almost_ready"], 1)
        self.assertEqual(payload["market_readiness"]["status"], "waiting_for_market_data")
        self.assertTrue(payload["market_readiness"]["pipes_synced"])
        self.assertEqual(payload["market_readiness"]["scanner_rows"], 1)
        self.assertEqual(payload["vwap_reclaim_reject"]["forward_observations"], 3)
        self.assertEqual(payload["strategy_vault"]["strategy_count"], 7)
        self.assertIn("do not approve trades", payload["guardrail"].lower())
        phases = {phase["phase"]: phase for phase in payload["phases"]}
        self.assertEqual(phases["Strategy Vault Expansion"]["status"], "complete")
        self.assertEqual(phases["Strategy Vault Expansion"]["progress"], "7 / 7")
        self.assertIn("Evidence Gates", phases)

    def test_autonomous_launch_agent_schedules_weekday_one_shot_scans(self) -> None:
        plist_path = Path("launchd/com.project-gwala.autonomous-paper.plist")
        with plist_path.open("rb") as file:
            plist = plistlib.load(file)

        arguments = plist["ProgramArguments"]
        entries = plist["StartCalendarInterval"]
        schedule = {(entry["Weekday"], entry["Hour"], entry["Minute"]) for entry in entries}

        self.assertIn("--once", arguments)
        self.assertNotIn("RunAtLoad", plist)
        self.assertEqual(plist.get("EnvironmentVariables", {}).get("PYTHONUNBUFFERED"), "1")
        self.assertEqual(len(entries), 405)
        self.assertIn((1, 6, 15), schedule)
        self.assertIn((1, 6, 30), schedule)
        self.assertIn((1, 13, 0), schedule)
        self.assertIn((1, 13, 5), schedule)
        self.assertIn((5, 6, 30), schedule)
        self.assertIn((5, 13, 5), schedule)

    def test_morning_watchdog_confirms_today_market_scan(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            (logs_dir / "autonomous_paper_workflow_status.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 09:31:00 EDT",
                        "decision": "market_scan",
                        "message": "Run market scan.",
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "daily_workflow_summary.md").write_text("# summary\n", encoding="utf-8")
            scan_time = datetime(2026, 5, 26, 9, 34, tzinfo=MARKET_TZ).timestamp()
            (logs_dir / "daily_workflow_summary.md").touch()
            os.utime(logs_dir / "daily_workflow_summary.md", (scan_time, scan_time))
            pd.DataFrame(
                [
                    scanner_row(
                        scan_date="2026-05-26",
                        signal_freshness="current_candle",
                        scanner_status="allowed",
                    )
                ]
            ).to_csv(logs_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "refresh_run_at_et": "2026-05-26 09:32:00 EDT",
                        "symbol": "SPY",
                        "m30_latest_session": "2026-05-26",
                        "m5_latest_session": "2026-05-26",
                    }
                ]
            ).to_csv(data_dir / "market_refresh_audit.csv", index=False)

            watchdog = build_morning_watchdog(
                logs_dir,
                data_dir=data_dir,
                moment=datetime(2026, 5, 26, 9, 40, tzinfo=MARKET_TZ),
            )

        self.assertEqual(watchdog["status"], "pass")
        self.assertTrue(watchdog["market_scan"]["ran_today"])
        self.assertTrue(watchdog["data_refresh"]["confirmed_today"])
        self.assertEqual(watchdog["scanner"]["allowed_candidate_count"], 1)

    def test_morning_watchdog_warns_when_first_scan_is_missing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()

            watchdog = build_morning_watchdog(
                logs_dir,
                data_dir=data_dir,
                moment=datetime(2026, 5, 26, 9, 40, tzinfo=MARKET_TZ),
            )

        self.assertEqual(watchdog["status"], "warn")
        self.assertFalse(watchdog["market_scan"]["ran_today"])
        self.assertIn("not been confirmed", watchdog["headline"])

    def test_production_heartbeat_returns_green_for_current_day_workflow(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "GREEN")
        self.assertTrue(heartbeat["experiment_valid_today"])

    def test_production_heartbeat_stale_scanner_date_triggers_red(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            pd.DataFrame([scanner_row(scan_date="2026-05-23")]).to_csv(
                logs_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            os.utime(logs_dir / "daily_paper_signal_scanner.csv", (moment.timestamp(), moment.timestamp()))

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "Scanner")
        self.assertFalse(heartbeat["experiment_valid_today"])

    def test_production_heartbeat_slightly_late_scanner_write_is_yellow(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            slightly_late = moment - timedelta(minutes=12, seconds=30)
            os.utime(
                logs_dir / "daily_paper_signal_scanner.csv",
                (slightly_late.timestamp(), slightly_late.timestamp()),
            )

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "YELLOW")
        self.assertTrue(heartbeat["experiment_valid_today"])
        self.assertEqual(heartbeat["checks"][2]["component"], "Scanner")
        self.assertEqual(heartbeat["checks"][2]["status"], "YELLOW")

    def test_production_heartbeat_materially_late_scanner_write_stays_red(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            materially_late = moment - timedelta(minutes=14)
            os.utime(
                logs_dir / "daily_paper_signal_scanner.csv",
                (materially_late.timestamp(), materially_late.timestamp()),
            )

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "Scanner")
        self.assertFalse(heartbeat["experiment_valid_today"])

    def test_production_heartbeat_stale_webull_refresh_triggers_red(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            pd.DataFrame(
                [
                    refresh_audit_row(
                        refresh_run_at_et="2026-05-26 10:00:00 EDT",
                        m30_latest_session="2026-05-23",
                        m5_latest_session="2026-05-23",
                    )
                ]
            ).to_csv(data_dir / "market_refresh_audit.csv", index=False)
            os.utime(data_dir / "market_refresh_audit.csv", (moment.timestamp(), moment.timestamp()))

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "Webull refresh")

    def test_production_heartbeat_launch_agent_failure_triggers_red(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 78: EX_CONFIG\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "LaunchAgent")
        self.assertIn("EX_CONFIG", heartbeat["red_reason"])

    def test_production_heartbeat_macos_launch_agent_path_unchanged(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 78: EX_CONFIG\n",
                platform_name="Darwin",
                in_docker=False,
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "LaunchAgent")
        self.assertEqual(heartbeat["runtime"]["platform"], "Darwin")

    def test_production_heartbeat_linux_docker_healthy_host_artifact_not_false_red(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            host_health = logs_dir / "host_systemd_health.json"
            host_health.write_text(
                json.dumps(
                    {
                        "generated_at_et": moment.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "status": "GREEN",
                        "reason": "All Project Gwala host systemd units are healthy.",
                    }
                ),
                encoding="utf-8",
            )

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                systemd_output="systemd_error: [Errno 2] No such file or directory: 'systemctl'",
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=host_health,
                env={
                    "GWALA_DEPLOYMENT_MODE": "shadow",
                    "GWALA_SHADOW_MODE": "true",
                    "GWALA_DISABLE_BROKER_EXECUTION": "true",
                    "GWALA_LIVE_TRADING_ENABLED": "false",
                    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
                    "GWALA_REAL_MONEY_READY": "false",
                },
            )

        self.assertEqual(heartbeat["status"], "GREEN")
        self.assertEqual(heartbeat["checks"][0]["component"], "host systemd health")
        self.assertEqual(heartbeat["checks"][0]["status"], "GREEN")
        self.assertEqual(heartbeat["runtime"]["in_docker"], True)

    def test_production_heartbeat_linux_docker_unhealthy_host_artifact_triggers_red(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            host_health = logs_dir / "host_systemd_health.json"
            host_health.write_text(
                json.dumps(
                    {
                        "generated_at_et": moment.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "status": "RED",
                        "reason": "One or more Project Gwala host systemd units are unhealthy.",
                        "red_component": "project-gwala-autonomous-paper.timer",
                        "red_reason": "ActiveState=failed",
                    }
                ),
                encoding="utf-8",
            )

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=host_health,
                env={
                    "GWALA_DEPLOYMENT_MODE": "shadow",
                    "GWALA_SHADOW_MODE": "true",
                    "GWALA_DISABLE_BROKER_EXECUTION": "true",
                    "GWALA_LIVE_TRADING_ENABLED": "false",
                    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
                    "GWALA_REAL_MONEY_READY": "false",
                },
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "host systemd health")
        self.assertIn("ActiveState=failed", heartbeat["red_reason"])

    def test_production_heartbeat_linux_docker_missing_host_artifact_is_unknown_not_green(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=logs_dir / "missing_host_health.json",
                env={
                    "GWALA_DEPLOYMENT_MODE": "shadow",
                    "GWALA_SHADOW_MODE": "true",
                    "GWALA_DISABLE_BROKER_EXECUTION": "true",
                    "GWALA_LIVE_TRADING_ENABLED": "false",
                    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
                    "GWALA_REAL_MONEY_READY": "false",
                },
            )

        self.assertEqual(heartbeat["status"], "YELLOW")
        self.assertEqual(heartbeat["checks"][0]["component"], "host systemd health")
        self.assertEqual(heartbeat["checks"][0]["status"], "YELLOW")
        self.assertTrue(heartbeat["experiment_valid_today"])

    def test_production_heartbeat_linux_docker_enforces_shadow_safety_environment(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            host_health = logs_dir / "host_systemd_health.json"
            host_health.write_text(
                json.dumps(
                    {
                        "generated_at_et": moment.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "status": "GREEN",
                        "reason": "All Project Gwala host systemd units are healthy.",
                    }
                ),
                encoding="utf-8",
            )

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=host_health,
                env={
                    "GWALA_DEPLOYMENT_MODE": "shadow",
                    "GWALA_SHADOW_MODE": "true",
                    "GWALA_DISABLE_BROKER_EXECUTION": "true",
                    "GWALA_LIVE_TRADING_ENABLED": "true",
                    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
                    "GWALA_REAL_MONEY_READY": "false",
                },
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertEqual(heartbeat["red_component"], "shadow safety posture")
        self.assertIn("GWALA_LIVE_TRADING_ENABLED=true", heartbeat["red_reason"])

    def test_host_systemd_health_expects_always_on_dashboard_service_without_timer(self) -> None:
        self.assertIn("project-gwala-dashboard.service", HOST_SYSTEMD_HEALTH_UNITS)
        self.assertNotIn("project-gwala-dashboard.timer", HOST_SYSTEMD_HEALTH_UNITS)

        health = host_systemd_unit_health(
            {
                "unit": "project-gwala-dashboard.service",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "active",
                "Result": "success",
                "ExecMainStatus": "0",
            }
        )

        self.assertEqual(health["status"], "GREEN")
        self.assertTrue(health["healthy"])

    def test_host_systemd_health_missing_dashboard_service_is_red(self) -> None:
        health = host_systemd_unit_health(
            {
                "unit": "project-gwala-dashboard.service",
                "returncode": "1",
                "LoadState": "not-found",
                "ActiveState": "inactive",
                "Result": "",
                "ExecMainStatus": "",
            }
        )

        self.assertEqual(health["status"], "RED")
        self.assertIn("LoadState=not-found", health["reason"])

    def test_host_systemd_health_keeps_scheduled_timers_required(self) -> None:
        required_timers = {
            "project-gwala-autonomous-paper.timer",
            "project-gwala-production-alert.timer",
            "project-gwala-opening-executive-report.timer",
            "project-gwala-eod-executive-report.timer",
        }

        self.assertTrue(required_timers.issubset(set(HOST_SYSTEMD_HEALTH_UNITS)))

        inactive_timer = host_systemd_unit_health(
            {
                "unit": "project-gwala-autonomous-paper.timer",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "Result": "success",
                "ExecMainStatus": "0",
            }
        )
        missing_timer = host_systemd_unit_health(
            {
                "unit": "project-gwala-production-alert.timer",
                "returncode": "1",
                "LoadState": "not-found",
                "ActiveState": "inactive",
                "Result": "",
                "ExecMainStatus": "",
            }
        )

        self.assertEqual(inactive_timer["status"], "RED")
        self.assertIn("ActiveState=inactive", inactive_timer["reason"])
        self.assertEqual(missing_timer["status"], "RED")
        self.assertIn("LoadState=not-found", missing_timer["reason"])

    def test_host_systemd_health_allows_production_alert_oneshot_activating_precheck(self) -> None:
        health = host_systemd_unit_health(
            {
                "unit": "project-gwala-production-alert.service",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "activating",
                "Result": "success",
                "ExecMainStatus": "0",
            }
        )

        self.assertEqual(health["status"], "GREEN")
        self.assertEqual(health["type"], "oneshot_service")

    def test_host_systemd_health_allows_successful_completed_oneshot_inactive(self) -> None:
        health = host_systemd_unit_health(
            {
                "unit": "project-gwala-opening-executive-report.service",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "Result": "success",
                "ExecMainStatus": "0",
            }
        )

        self.assertEqual(health["status"], "GREEN")
        self.assertEqual(health["type"], "oneshot_service")

    def test_host_systemd_health_failed_oneshot_is_red(self) -> None:
        health = host_systemd_unit_health(
            {
                "unit": "project-gwala-production-alert.service",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "failed",
                "Result": "exit-code",
                "ExecMainStatus": "1",
            }
        )

        self.assertEqual(health["status"], "RED")
        self.assertIn("ActiveState=failed", health["reason"])
        self.assertIn("Result=exit-code", health["reason"])
        self.assertIn("ExecMainStatus=1", health["reason"])

    def test_host_systemd_health_dashboard_must_be_active(self) -> None:
        activating = host_systemd_unit_health(
            {
                "unit": "project-gwala-dashboard.service",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "activating",
                "Result": "success",
                "ExecMainStatus": "0",
            }
        )
        inactive = host_systemd_unit_health(
            {
                "unit": "project-gwala-dashboard.service",
                "returncode": "0",
                "LoadState": "loaded",
                "ActiveState": "inactive",
                "Result": "success",
                "ExecMainStatus": "0",
            }
        )

        self.assertEqual(activating["status"], "RED")
        self.assertEqual(activating["type"], "always_on_service")
        self.assertIn("ActiveState=activating", activating["reason"])
        self.assertEqual(inactive["status"], "RED")
        self.assertIn("ActiveState=inactive", inactive["reason"])

    def test_production_heartbeat_missing_candidate_ledger_is_yellow(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            (logs_dir / "candidate_window_ledger.json").unlink()

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "YELLOW")
        self.assertTrue(heartbeat["experiment_valid_today"])

    def test_production_heartbeat_red_marks_experiment_invalid(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)

            heartbeat = build_production_heartbeat(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(heartbeat["status"], "RED")
        self.assertFalse(heartbeat["experiment_valid_today"])
        self.assertEqual(heartbeat["decision"], "BUILD")

    def test_production_alert_first_confirmed_failure_is_degraded_not_down(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            notifications: list[tuple[str, str]] = []

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                notifier=lambda title, message: notifications.append((title, message)) is None or True,
                launchctl_output="state = not running\nlast exit code = 78: EX_CONFIG\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(alert["status"], "RED")
        self.assertEqual(alert["internal_severity"], "DEGRADED")
        self.assertEqual(alert["operator_action_required"], "YES")
        self.assertTrue(alert["notification_required"])
        self.assertTrue(alert["notification_sent"])
        self.assertEqual(notifications[0][0], "🟠 GWALA — DEGRADED")
        self.assertIn("Operator action: REVIEW", notifications[0][1])

    def test_production_alert_does_not_notify_on_green(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            notifications: list[tuple[str, str]] = []

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                notifier=lambda title, message: notifications.append((title, message)) is None or True,
                launchctl_output="state = not running\nlast exit code = 0\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertEqual(alert["status"], "GREEN")
        self.assertFalse(alert["notification_required"])
        self.assertFalse(notifications)

    def test_production_alert_linux_docker_follows_healthy_host_systemd_artifact(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            host_health = logs_dir / "host_systemd_health.json"
            write_host_systemd_health_artifact(host_health, moment, status="GREEN")
            notifications: list[tuple[str, str]] = []

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                notifier=lambda title, message: notifications.append((title, message)) is None or True,
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=host_health,
                env=LINUX_DOCKER_SHADOW_ENV,
            )

        self.assertEqual(alert["status"], "GREEN")
        self.assertFalse(alert["notification_required"])
        self.assertFalse(notifications)

    def test_production_alert_linux_docker_follows_unhealthy_host_systemd_artifact(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            host_health = logs_dir / "host_systemd_health.json"
            write_host_systemd_health_artifact(host_health, moment, status="RED")
            notifications: list[tuple[str, str]] = []

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                notifier=lambda title, message: notifications.append((title, message)) is None or True,
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=host_health,
                env=LINUX_DOCKER_SHADOW_ENV,
            )

        self.assertEqual(alert["status"], "RED")
        self.assertEqual(alert["red_component"], "host systemd health")
        self.assertTrue(alert["notification_required"])

    def test_production_alert_linux_docker_missing_host_systemd_artifact_is_watch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            write_healthy_heartbeat_artifacts(logs_dir, data_dir, moment)
            notifications: list[tuple[str, str]] = []

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                notifier=lambda title, message: notifications.append((title, message)) is None or True,
                platform_name="Linux",
                in_docker=True,
                host_systemd_health_path=logs_dir / "missing_host_health.json",
                env=LINUX_DOCKER_SHADOW_ENV,
            )

        self.assertEqual(alert["status"], "YELLOW")
        self.assertEqual(alert["internal_severity"], "WATCH")
        self.assertFalse(alert["notification_required"])
        self.assertFalse(notifications)

    def test_production_alert_dedupes_repeated_unresolved_condition(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            first = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
            second = datetime(2026, 5, 26, 10, 2, tzinfo=MARKET_TZ)
            notifications: list[tuple[str, str]] = []
            notifier = lambda title, message: notifications.append((title, message)) is None or True

            first_alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=first,
                cooldown_minutes=30,
                recheck_seconds=0,
                down_confirmation_failures=3,
                notifier=notifier,
                launchctl_output="state = not running\nlast exit code = 78: EX_CONFIG\n",
                **MACOS_NATIVE_RUNTIME,
            )
            second_alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=second,
                cooldown_minutes=30,
                recheck_seconds=0,
                down_confirmation_failures=3,
                notifier=notifier,
                launchctl_output="state = not running\nlast exit code = 78: EX_CONFIG\n",
                **MACOS_NATIVE_RUNTIME,
            )

        self.assertTrue(first_alert["notification_required"])
        self.assertFalse(second_alert["notification_required"])
        self.assertEqual(len(notifications), 1)

    def test_production_alert_active_scanner_refresh_does_not_emit_down(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ)
            notifications: list[tuple[str, str]] = []
            heartbeats = [
                heartbeat_fixture("RED", component="Scanner", reason="Latest scanner write is not recent."),
                heartbeat_fixture("GREEN"),
            ]

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                notifier=lambda title, message: notifications.append((title, message)) is None or True,
                heartbeat_builder=lambda *args, **kwargs: heartbeats.pop(0),
            )

        self.assertEqual(alert["internal_severity"], "WATCH")
        self.assertEqual(alert["business_impact"], "NO")
        self.assertEqual(alert["operator_action_required"], "NO")
        self.assertFalse(alert["notification_required"])
        self.assertFalse(notifications)

    def test_production_alert_recovered_artifact_is_watch_not_immediate(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ)
            heartbeats = [
                heartbeat_fixture("RED", component="Webull refresh", reason="Webull refresh audit is not recent."),
                heartbeat_fixture("GREEN"),
            ]

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                heartbeat_builder=lambda *args, **kwargs: heartbeats.pop(0),
                notifier=lambda title, message: True,
            )

        self.assertEqual(alert["internal_severity"], "WATCH")
        self.assertEqual(alert["operator_action_required"], "NO")
        self.assertNotIn("IMMEDIATE", alert["notification_body"])

    def test_production_alert_isolated_stale_read_cannot_emit_immediate(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            moment = datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ)

            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=moment,
                recheck_seconds=0,
                heartbeat_builder=lambda *args, **kwargs: heartbeat_fixture(
                    "RED",
                    component="Scanner",
                    reason="Latest scanner write is not recent.",
                ),
                notifier=lambda title, message: True,
            )

        self.assertEqual(alert["internal_severity"], "DEGRADED")
        self.assertNotEqual(alert["internal_severity"], "DOWN")
        self.assertNotIn("Operator action: IMMEDIATE", alert["notification_body"])

    def test_production_alert_down_requires_consecutive_confirmed_failures(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            first = datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ)
            second = datetime(2026, 5, 26, 10, 20, tzinfo=MARKET_TZ)
            notifications: list[tuple[str, str]] = []
            notifier = lambda title, message: notifications.append((title, message)) is None or True
            builder = lambda *args, **kwargs: heartbeat_fixture(
                "RED",
                component="LaunchAgent",
                reason="LaunchAgent is not loaded.",
            )

            first_alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=first,
                recheck_seconds=0,
                notifier=notifier,
                heartbeat_builder=builder,
            )
            second_alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=second,
                recheck_seconds=0,
                notifier=notifier,
                heartbeat_builder=builder,
            )

        self.assertEqual(first_alert["internal_severity"], "DEGRADED")
        self.assertEqual(second_alert["internal_severity"], "DOWN")
        self.assertTrue(second_alert["notification_required"])
        self.assertEqual(notifications[-1][0], "🔴 GWALA — DOWN")
        self.assertIn("Operator action: IMMEDIATE", notifications[-1][1])

    def test_production_alert_recovery_generates_one_clear_recovery_event(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            first = datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ)
            recovered = datetime(2026, 5, 26, 10, 20, tzinfo=MARKET_TZ)
            still_green = datetime(2026, 5, 26, 10, 25, tzinfo=MARKET_TZ)
            notifications: list[tuple[str, str]] = []
            notifier = lambda title, message: notifications.append((title, message)) is None or True

            build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=first,
                recheck_seconds=0,
                down_confirmation_failures=3,
                notifier=notifier,
                heartbeat_builder=lambda *args, **kwargs: heartbeat_fixture(
                    "RED",
                    component="Scanner",
                    reason="Latest scanner write is not recent.",
                ),
            )
            recovery_alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=recovered,
                recheck_seconds=0,
                notifier=notifier,
                heartbeat_builder=lambda *args, **kwargs: heartbeat_fixture("GREEN"),
            )
            repeat_green = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=still_green,
                recheck_seconds=0,
                notifier=notifier,
                heartbeat_builder=lambda *args, **kwargs: heartbeat_fixture("GREEN"),
            )

        self.assertTrue(recovery_alert["notification_required"])
        self.assertEqual(recovery_alert["notification_reason"], "recovery")
        self.assertEqual(notifications[-1][0], "🟢 GWALA — GREEN")
        self.assertFalse(repeat_green["notification_required"])
        self.assertEqual(len(notifications), 2)

    def test_production_alert_sustained_failure_still_produces_down(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            first = datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ)
            sustained = datetime(2026, 5, 26, 10, 21, tzinfo=MARKET_TZ)
            builder = lambda *args, **kwargs: heartbeat_fixture(
                "RED",
                component="LaunchAgent",
                reason="LaunchAgent is not loaded.",
            )

            build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=first,
                recheck_seconds=0,
                outage_threshold_minutes=5,
                down_confirmation_failures=99,
                heartbeat_builder=builder,
                notifier=lambda title, message: True,
            )
            alert = build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=sustained,
                recheck_seconds=0,
                outage_threshold_minutes=5,
                down_confirmation_failures=99,
                heartbeat_builder=builder,
                notifier=lambda title, message: True,
            )

        self.assertEqual(alert["internal_severity"], "DOWN")
        self.assertEqual(alert["operator_action_required"], "YES")
        self.assertIn("Operator action: IMMEDIATE", alert["notification_body"])

    def test_production_alert_does_not_modify_trading_gate_or_lifecycle_files(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            data_dir = root / "data"
            logs_dir.mkdir()
            data_dir.mkdir()
            protected = [
                data_dir / "paper_trades.csv",
                logs_dir / "paper_gate_v2.json",
                logs_dir / "options_contract_gate.json",
                logs_dir / "autonomous_a_tier_lifecycle.json",
            ]
            for path in protected:
                path.write_text("sentinel", encoding="utf-8")

            build_production_alert(
                logs_dir,
                data_dir=data_dir,
                moment=datetime(2026, 5, 26, 10, 15, tzinfo=MARKET_TZ),
                recheck_seconds=0,
                heartbeat_builder=lambda *args, **kwargs: heartbeat_fixture("GREEN"),
                notifier=lambda title, message: True,
            )

            contents = [path.read_text(encoding="utf-8") for path in protected]

        self.assertEqual(contents, ["sentinel", "sentinel", "sentinel", "sentinel"])

    def test_production_alert_launch_agent_runs_offset_from_scan_boundary(self) -> None:
        plist = build_production_alert_plist()
        entries = production_alert_calendar_entries()
        schedule = {(entry["Weekday"], entry["Hour"], entry["Minute"]) for entry in entries}

        self.assertEqual(plist["Label"], "com.project-gwala.production-alert")
        self.assertIn("run_production_alert.py", plist["ProgramArguments"][1])
        self.assertIn((2, 6, 47), schedule)
        self.assertIn((2, 13, 7), schedule)
        self.assertNotIn((2, 6, 45), schedule)
        self.assertNotIn((2, 13, 5), schedule)
        self.assertIn("--recheck-seconds", plist["ProgramArguments"])
        self.assertIn("--outage-threshold-minutes", plist["ProgramArguments"])
        self.assertIn("--down-confirmation-failures", plist["ProgramArguments"])
        self.assertEqual(len(entries), 385)

    def test_post_scan_digest_prioritizes_ready_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "queue_status": "ready_for_review",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "latest_candle_et": "2026-05-26 10:00",
                        "quality_grade": "A",
                        "quality_score": 8,
                        "check_score": 1.0,
                        "room_to_target_r": 2.0,
                        "next_action": "Review checklist.",
                        "blockers": "",
                    }
                ]
            ).to_csv(output_dir / "forward_sample_queue.csv", index=False)
            (output_dir / "refresh_status.json").write_text(json.dumps({"status": "fresh_for_today"}), encoding="utf-8")

            digest = build_post_scan_digest(output_dir, moment=datetime(2026, 5, 26, 10, 1, tzinfo=MARKET_TZ))

        self.assertEqual(digest["action"], "review_candidate")
        self.assertEqual(digest["summary"]["ready_for_review"], 1)
        self.assertEqual(digest["ready_rows"][0]["symbol"], "SPY")

    def test_post_scan_digest_surfaces_one_rule_blocker(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "queue_status": "waiting",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "latest_candle_et": "2026-05-26 10:00",
                        "check_score": 0.8889,
                        "quality_score": 7,
                    }
                ]
            ).to_csv(output_dir / "forward_sample_queue.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "latest_candle_et": "2026-05-26 10:00",
                        "check_score": 0.8889,
                        "missing_count": 1,
                        "quality_grade": "B",
                        "quality_score": 7,
                        "relative_volume": 1.2,
                        "room_to_target_r": 1.5,
                        "missing_condition_list": "above opening range high",
                    }
                ]
            ).to_csv(output_dir / "no_trade_blocker_analysis.csv", index=False)
            (output_dir / "refresh_status.json").write_text(json.dumps({"status": "fresh_for_today"}), encoding="utf-8")

            digest = build_post_scan_digest(output_dir, moment=datetime(2026, 5, 26, 10, 1, tzinfo=MARKET_TZ))

        self.assertEqual(digest["action"], "study_blocker")
        self.assertEqual(digest["summary"]["one_rule_from_passing"], 1)
        self.assertEqual(digest["top_blockers"][0]["blocker"], "above opening range high")

    def test_automation_timeline_tolerates_missing_autonomous_json(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "autonomous_paper_workflow_status.md").write_text(
                "# Autonomous Paper Workflow Status\n", encoding="utf-8"
            )
            (output_dir / "morning_run_watchdog.json").write_text(
                json.dumps({"status": "pending", "headline": "Not due yet."}),
                encoding="utf-8",
            )
            (output_dir / "post_scan_digest.json").write_text(
                json.dumps({"action": "wait", "headline": "No action.", "next_action": "Wait."}),
                encoding="utf-8",
            )

            timeline = build_automation_timeline(
                output_dir,
                moment=datetime(2026, 5, 26, 8, 0, tzinfo=MARKET_TZ),
            )

        self.assertEqual(timeline["status"], "pending")
        self.assertFalse(timeline["files"]["autonomous_status_json"]["exists"])
        self.assertTrue(timeline["files"]["autonomous_status_md"]["exists"])

    def test_automation_timeline_flags_recent_log_failures(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "morning_run_watchdog.json").write_text(
                json.dumps({"status": "pass", "headline": "Ran today."}),
                encoding="utf-8",
            )
            (output_dir / "post_scan_digest.json").write_text(
                json.dumps({"action": "wait", "headline": "No action.", "next_action": "Wait."}),
                encoding="utf-8",
            )
            (output_dir / "autonomous_paper_workflow.launchd.out.log").write_text(
                "=== python run_daily_workflow.py ===\nSaved report\nERROR refresh failed\n",
                encoding="utf-8",
            )
            log_time = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ).timestamp()
            os.utime(output_dir / "autonomous_paper_workflow.launchd.out.log", (log_time, log_time))

            timeline = build_automation_timeline(
                output_dir,
                moment=datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ),
            )

        self.assertEqual(timeline["status"], "warn")
        self.assertEqual(timeline["recent_commands"][0]["command"], "run_daily_workflow.py")
        self.assertTrue(timeline["recent_failures"])

    def test_automation_timeline_ignores_stale_log_failures(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "morning_run_watchdog.json").write_text(
                json.dumps({"status": "pass", "headline": "Ran today."}),
                encoding="utf-8",
            )
            (output_dir / "post_scan_digest.json").write_text(
                json.dumps({"action": "wait", "headline": "No action.", "next_action": "Wait."}),
                encoding="utf-8",
            )
            log_path = output_dir / "autonomous_paper_workflow.launchd.err.log"
            log_path.write_text("Traceback (most recent call last):\nNameResolutionError\n", encoding="utf-8")
            stale_time = datetime(2026, 5, 25, 10, 0, tzinfo=MARKET_TZ).timestamp()
            os.utime(log_path, (stale_time, stale_time))

            timeline = build_automation_timeline(
                output_dir,
                moment=datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ),
            )

        self.assertEqual(timeline["status"], "pass")
        self.assertFalse(timeline["recent_failures"])


class CandleIntegrityTests(unittest.TestCase):
    def write_candles(self, path: Path, final_time: str) -> None:
        pd.DataFrame(
            [
                {
                    "datetime": "2026-05-22T13:30:00Z",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 1000,
                },
                {
                    "datetime": final_time,
                    "open": 100.5,
                    "high": 102,
                    "low": 100,
                    "close": 101,
                    "volume": 1200,
                },
            ]
        ).to_csv(path, index=False)

    def test_complete_and_partial_m5_sessions_are_distinguished(self) -> None:
        with TemporaryDirectory() as temporary:
            complete_path = Path(temporary) / "complete.csv"
            provider_final_path = Path(temporary) / "provider_final.csv"
            partial_path = Path(temporary) / "partial.csv"
            self.write_candles(complete_path, "2026-05-22T19:55:00Z")
            self.write_candles(provider_final_path, "2026-05-22T19:50:00Z")
            self.write_candles(partial_path, "2026-05-22T18:00:00Z")

            complete = inspect_file("SPY", "M5", complete_path)
            provider_final = inspect_file("SPY", "M5", provider_final_path)
            partial = inspect_file("SPY", "M5", partial_path)

        self.assertEqual(complete["session_coverage"], "complete")
        self.assertEqual(provider_final["session_coverage"], "provider_final_bar")
        self.assertEqual(partial["session_coverage"], "partial_session")

    def test_active_session_m5_file_is_expected_in_progress(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "active.csv"
            pd.DataFrame(
                [
                    {
                        "datetime": "2026-05-26T13:30:00Z",
                        "open": 100,
                        "high": 101,
                        "low": 99,
                        "close": 100.5,
                        "volume": 1000,
                    }
                ]
            ).to_csv(path, index=False)
            during_market = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)

            active = inspect_file("SPY", "M5", path, during_market)

        self.assertEqual(active["session_coverage"], "in_progress")

    def test_external_csv_import_normalizes_vendor_columns(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "Date": "2026-05-26 09:30:00-04:00",
                    "Open": "100.00",
                    "High": "101.00",
                    "Low": "99.50",
                    "Close": "100.50",
                    "Vol": "1200",
                },
                {
                    "Date": "2026-05-26 09:35:00-04:00",
                    "Open": "100.50",
                    "High": "102.00",
                    "Low": "100.25",
                    "Close": "101.50",
                    "Vol": "1500",
                },
            ]
        )

        candles = normalize_external_candles(raw)

        self.assertEqual(list(candles.columns), ["datetime", "open", "high", "low", "close", "volume"])
        self.assertEqual(candles.iloc[0]["datetime"], "2026-05-26T13:30:00Z")
        self.assertEqual(candles.iloc[1]["volume"], 1500)

    def test_external_csv_import_writes_reuse_csv_name(self) -> None:
        with TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            source = temporary_path / "provider_export.csv"
            pd.DataFrame(
                [
                    {
                        "timestamp": "2026-05-26T13:30:00Z",
                        "o": 100,
                        "h": 101,
                        "l": 99,
                        "c": 100.5,
                        "v": 1000,
                    }
                ]
            ).to_csv(source, index=False)

            output_path = import_candles(source, "spy", "m30", temporary_path)

            self.assertEqual(output_path.name, "webull_SPY_M30_candles.csv")
            saved = pd.read_csv(output_path)
            self.assertEqual(saved.iloc[0]["close"], 100.5)

    def test_polygon_timeframe_mapping_and_url_are_backtest_cache_ready(self) -> None:
        self.assertEqual(timeframe_to_polygon("M30"), (30, "minute"))
        self.assertEqual(timeframe_to_polygon("M60"), (1, "hour"))

        url = polygon_aggs_url(
            symbol="spy",
            timeframe="M5",
            start_date="2026-06-01",
            end_date="2026-06-04",
            adjusted=True,
            api_key="secret",
            base_url="https://example.test",
        )

        self.assertIn("/v2/aggs/ticker/SPY/range/5/minute/2026-06-01/2026-06-04", url)
        self.assertIn("adjusted=true", url)
        self.assertIn("apiKey=secret", url)

    def test_polygon_aggregate_rows_normalize_to_local_candle_schema(self) -> None:
        payload = {
            "ticker": "SPY",
            "status": "OK",
            "results": [
                {"t": 1780317000000, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1234},
                {"t": 1780317300000, "o": "100.5", "h": "102", "l": "100", "c": "101.5", "v": "1500"},
            ],
        }

        candles = normalize_polygon_aggs(payload)

        self.assertEqual(list(candles.columns), ["datetime", "open", "high", "low", "close", "volume"])
        self.assertEqual(candles.iloc[0]["datetime"], "2026-06-01T12:30:00Z")
        self.assertEqual(candles.iloc[1]["close"], 101.5)
        self.assertEqual(candles.iloc[1]["volume"], 1500)

    def test_provider_acceptance_passes_current_session_polygon_bars(self) -> None:
        def fetcher(_url: str) -> dict:
            return {
                "ticker": "SPY",
                "status": "OK",
                "results": [
                    {
                        "t": int(pd.Timestamp("2026-06-08T14:30:00Z").timestamp() * 1000),
                        "o": 100,
                        "h": 101,
                        "l": 99,
                        "c": 100.5,
                        "v": 1234,
                    }
                ],
            }

        with TemporaryDirectory() as temporary:
            report = build_acceptance_report(
                provider="polygon",
                symbols=["SPY"],
                timeframes=["M5"],
                output_dir=Path(temporary),
                max_lag_minutes=90,
                now=datetime(2026, 6, 8, 10, 35, tzinfo=MARKET_TZ),
                api_key="secret",
                fetcher=fetcher,
            )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"][0]["status"], "ok")
        self.assertEqual(report["checks"][0]["latest_session_et"], "2026-06-08")

    def test_provider_acceptance_fails_previous_session_polygon_bars(self) -> None:
        def fetcher(_url: str) -> dict:
            return {
                "ticker": "SPY",
                "status": "OK",
                "results": [
                    {
                        "t": int(pd.Timestamp("2026-06-05T19:55:00Z").timestamp() * 1000),
                        "o": 100,
                        "h": 101,
                        "l": 99,
                        "c": 100.5,
                        "v": 1234,
                    }
                ],
            }

        with TemporaryDirectory() as temporary:
            report = build_acceptance_report(
                provider="polygon",
                symbols=["SPY", "QQQ"],
                timeframes=["M5", "M30"],
                output_dir=Path(temporary),
                max_lag_minutes=90,
                now=datetime(2026, 6, 8, 10, 35, tzinfo=MARKET_TZ),
                api_key="secret",
                fetcher=fetcher,
            )

        self.assertEqual(report["status"], "fail_provider_not_current")
        self.assertEqual(len(report["checks"]), 4)
        self.assertEqual({row["status"] for row in report["checks"]}, {"previous_session_bars"})

    def test_market_data_source_metadata_tracks_polygon_provider(self) -> None:
        with TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            source_csv = temporary_path / "market_data_sources.csv"
            candles = pd.DataFrame(
                [
                    {
                        "datetime": "2026-06-01T12:30:00Z",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1234,
                    }
                ]
            )
            row = source_row(
                provider="polygon",
                symbol="spy",
                timeframe="m5",
                candle_path=temporary_path / "webull_SPY_M5_candles.csv",
                candles=candles,
                start_date="2026-06-01",
                end_date="2026-06-04",
                status="ok",
            )

            sources = append_sources(source_csv, [row])
            latest = latest_source_for(source_csv, "SPY", "M5")
            state = market_data_source_state(sources)

            self.assertEqual(latest["provider"], "polygon")
            self.assertEqual(latest["rows"], 1)
            self.assertEqual(state["latest_provider"], "polygon")
            self.assertEqual(state["provider_counts"], {"polygon": 1})

    def test_provider_neutral_candle_cache_keeps_legacy_alias(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            candles = pd.DataFrame(
                [
                    {
                        "datetime": "2026-06-01T12:30:00Z",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1234,
                    }
                ]
            )

            output = save_candle_cache(candles, data_dir, "spy", "m5")

            self.assertEqual(output, candle_cache_path(data_dir, "SPY", "M5"))
            self.assertTrue(output.exists())
            self.assertTrue(legacy_candle_cache_path(data_dir, "SPY", "M5").exists())
            self.assertEqual(preferred_candle_path(data_dir, "SPY", "M5"), output)

    def test_webull_fetch_updates_provider_neutral_and_legacy_candle_cache(self) -> None:
        rows = [
            {
                "time": "2026-06-09T14:00:00.000+0000",
                "open": "100.00",
                "high": "101.00",
                "low": "99.00",
                "close": "100.50",
                "volume": "1234",
            }
        ]

        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with patch("run_webull_watchlist.fetch_history_bars_paged", return_value=rows):
                output = fetch_and_save(object(), "SPY", "M5", 10, 1, 0, data_dir)

            canonical = candle_cache_path(data_dir, "SPY", "M5")
            legacy = legacy_candle_cache_path(data_dir, "SPY", "M5")

            self.assertEqual(output, canonical)
            self.assertTrue(canonical.exists())
            self.assertTrue(legacy.exists())
            self.assertEqual(pd.read_csv(canonical).iloc[-1]["datetime"], "2026-06-09T14:00:00.000+0000")
            self.assertEqual(pd.read_csv(legacy).iloc[-1]["datetime"], "2026-06-09T14:00:00.000+0000")

    def test_refresh_audit_builds_webull_source_metadata_from_canonical_cache(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            candles = pd.DataFrame(
                [
                    {
                        "datetime": "2026-06-09T13:30:00Z",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1234,
                    }
                ]
            )
            save_candle_cache(candles, data_dir, "SPY", "M5")
            save_candle_cache(candles, data_dir, "SPY", "M30")

            rows = source_metadata_rows(["SPY"], data_dir, provider="webull")

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["provider"] for row in rows}, {"webull"})
        self.assertEqual({row["status"] for row in rows}, {"ok"})
        self.assertEqual({row["end_date"] for row in rows}, {"2026-06-09"})

    def test_repair_m30_from_lower_timeframe_rebuilds_stale_m30_rows(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            stale_m30 = pd.DataFrame(
                [
                    {
                        "datetime": "2026-06-10T19:30:00.000+0000",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 1000,
                    }
                ]
            )
            fresh_m5 = pd.DataFrame(
                [
                    {
                        "datetime": f"2026-06-11T13:{minute:02d}:00.000+0000",
                        "open": 110.0 + index,
                        "high": 111.0 + index,
                        "low": 109.0 + index,
                        "close": 110.5 + index,
                        "volume": 100 + index,
                    }
                    for index, minute in enumerate([30, 35, 40, 45, 50])
                ]
            )
            save_candle_cache(stale_m30, data_dir, "SPY", "M30")
            save_candle_cache(fresh_m5, data_dir, "SPY", "M5")

            result, repaired, output_path = repair_symbol("SPY", data_dir, "M5", "M30")

            saved = pd.read_csv(candle_cache_path(data_dir, "SPY", "M30"))

        self.assertEqual(result.status, "repaired")
        self.assertEqual(result.target_after_et, "2026-06-11 09:30")
        self.assertEqual(result.derived_rows_added, 1)
        self.assertIsNotNone(repaired)
        self.assertIsNotNone(output_path)
        self.assertEqual(saved.iloc[-1]["datetime"], "2026-06-11T13:30:00.000+0000")
        self.assertEqual(saved.iloc[-1]["open"], 110.0)
        self.assertEqual(saved.iloc[-1]["high"], 115.0)
        self.assertEqual(saved.iloc[-1]["low"], 109.0)
        self.assertEqual(saved.iloc[-1]["close"], 114.5)
        self.assertEqual(saved.iloc[-1]["volume"], 510)


class HoldoutStabilityTests(unittest.TestCase):
    def test_validation_windows_include_calendar_months(self) -> None:
        trades = add_entry_dates(
            pd.DataFrame(
                {
                    "entry_time": [
                        "2026-01-15T15:30:00Z",
                        "2026-02-02T15:30:00Z",
                        "2026-02-20T15:30:00Z",
                    ]
                }
            )
        )

        windows = validation_windows(trades)
        months = [window for window in windows if window["window_type"] == "calendar_month"]

        self.assertEqual([window["window"] for window in months], ["month_2026-01", "month_2026-02"])
        self.assertEqual(str(months[0]["start"]), "2026-01-01 05:00:00+00:00")
        self.assertEqual(str(months[1]["end"]), "2026-03-01 05:00:00+00:00")

    def test_stability_summary_counts_only_affected_months(self) -> None:
        results = pd.DataFrame(
            [
                {
                    "window_type": "calendar_month",
                    "trade_filter": "weakness_v1",
                    "blocked_raw_trades": 2,
                    "expectancy_delta": 0.10,
                    "profit_factor_delta": 0.20,
                    "final_r_delta": 1.0,
                },
                {
                    "window_type": "calendar_month",
                    "trade_filter": "weakness_v1",
                    "blocked_raw_trades": 1,
                    "expectancy_delta": -0.01,
                    "profit_factor_delta": -0.02,
                    "final_r_delta": -0.5,
                },
                {
                    "window_type": "calendar_month",
                    "trade_filter": "weakness_v1",
                    "blocked_raw_trades": 0,
                    "expectancy_delta": 1.0,
                    "profit_factor_delta": 1.0,
                    "final_r_delta": 3.0,
                },
            ]
        )

        summary = stability_summary(results).iloc[0]

        self.assertEqual(summary["months_with_blocks"], 2)
        self.assertEqual(summary["expectancy_improved_months"], 1)
        self.assertEqual(summary["months_with_lower_final_r"], 1)
        self.assertEqual(summary["net_final_r_delta"], 0.5)


class ResearchSelectionTests(unittest.TestCase):
    def test_filter_policy_classifies_safety_quality_and_experimental_filters(self) -> None:
        self.assertEqual(classify_filter_reason("market is closed")["category"], "safety-critical")
        self.assertEqual(classify_filter_reason("strong relative volume")["filter_id"], "volume_confirmation")
        self.assertEqual(classify_filter_reason("blocked_nvda_short_11am_et")["category"], "experimental")

    def test_filter_rejection_report_counts_reasons_by_filter(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    scanner_row(
                        scanner_status="not_ready",
                        missing_conditions="strong relative volume; room to target",
                    ),
                    scanner_row(
                        symbol="NVDA",
                        setup="Setup B Short",
                        direction="short",
                        scanner_status="blocked_watch_only",
                        block_reason="blocked_nvda_short_11am_et",
                    ),
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "sizing_status": "not_current",
                        "sizing_reason": "Signal freshness is earlier_today, not current_candle.",
                    }
                ]
            ).to_csv(output_dir / "position_sizing.csv", index=False)

            events = build_filter_rejection_events(output_dir)
            summary = build_filter_rejection_summary(events)

        categories = set(events["category"])
        filters = set(summary["filter_id"])
        self.assertIn("safety-critical", categories)
        self.assertIn("trade-quality", categories)
        self.assertIn("experimental", categories)
        self.assertIn("data_freshness", filters)
        self.assertIn("extra_confirmation_stacking", filters)

    def test_strategy_overlap_audit_flags_priority_gaps(self) -> None:
        audit = build_audit_rows()
        by_area = audit.set_index("area")
        plan = priority_plan(audit)

        self.assertEqual(by_area.loc["Broad market regime filter", "status"], "partial")
        self.assertEqual(by_area.loc["Liquidity and spread filter", "status"], "missing")
        self.assertEqual(by_area.loc["Paper validation before execution", "status"], "exists")
        self.assertIn("broker_order_execution_enabled", by_area.loc["Broker execution safety", "current_evidence"])
        self.assertEqual(plan.iloc[0]["priority"], "high")

    def test_opening_range_relaxation_requires_symbol_specific_shadow_test(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "variant": "current",
                    "exit_profile": "no_vwap_exit",
                    "baseline_trades": 7,
                    "baseline_win_rate": 0.5714,
                    "baseline_expectancy_r": 0.0502,
                    "baseline_profit_factor": 1.4258,
                    "long_signal_count": 11,
                    "summary_report": "logs/SPY_current.md",
                },
                {
                    "symbol": "SPY",
                    "variant": "no_opening_range",
                    "exit_profile": "no_vwap_exit",
                    "baseline_trades": 11,
                    "baseline_win_rate": 0.4545,
                    "baseline_expectancy_r": 0.0412,
                    "baseline_profit_factor": 1.1666,
                    "long_signal_count": 60,
                    "summary_report": "logs/SPY_relaxed.md",
                },
                {
                    "symbol": "QQQ",
                    "variant": "current",
                    "exit_profile": "no_vwap_exit",
                    "baseline_trades": 6,
                    "baseline_expectancy_r": 0.1958,
                    "baseline_profit_factor": 6.0248,
                    "long_signal_count": 9,
                },
                {
                    "symbol": "QQQ",
                    "variant": "no_opening_range",
                    "exit_profile": "no_vwap_exit",
                    "baseline_trades": 10,
                    "baseline_expectancy_r": -0.1238,
                    "baseline_profit_factor": 0.5632,
                    "long_signal_count": 65,
                },
            ]
        )

        review = build_opening_range_review(summary)
        by_symbol = review.set_index("symbol")

        self.assertEqual(by_symbol.loc["SPY", "decision"], "shadow_test_only")
        self.assertEqual(by_symbol.loc["QQQ", "decision"], "reject_relaxation")
        self.assertEqual(by_symbol.loc["SPY", "added_trades"], 4)

    def test_opening_range_breakout_flags_long_break_above_range(self) -> None:
        candles = pd.DataFrame(
            [
                {
                    "open": 100.9,
                    "high": 102.0,
                    "low": 100.8,
                    "close": 101.5,
                    "volume": 1_000,
                    "vwap": 100.5,
                    "ema_9": 101.0,
                    "ema_21": 100.5,
                    "opening_range_high": 101.0,
                    "opening_range_low": 99.5,
                    "regular_session": True,
                    "entry_window": True,
                }
            ],
            index=[pd.Timestamp("2026-06-02 10:30", tz="America/New_York")],
        )

        signals = add_opening_range_breakout_signals(candles, STRATEGY)

        self.assertTrue(bool(signals.iloc[0]["or_breakout_long_signal"]))
        self.assertFalse(bool(signals.iloc[0]["or_breakout_short_signal"]))
        self.assertGreaterEqual(int(signals.iloc[0]["or_breakout_quality_score"]), 4)

    def test_gap_fill_fade_flags_gap_down_long_rotation(self) -> None:
        candles = pd.DataFrame(
            [
                {
                    "open": 98.5,
                    "high": 99.5,
                    "low": 98.3,
                    "close": 99.2,
                    "volume": 1_000,
                    "vwap": 99.0,
                    "prior_close": 100.0,
                    "session_open": 98.5,
                    "regular_session": True,
                    "entry_window": True,
                }
            ],
            index=[pd.Timestamp("2026-06-02 10:30", tz="America/New_York")],
        )

        signals = add_gap_fill_fade_signals(candles, STRATEGY)

        self.assertTrue(bool(signals.iloc[0]["gap_fade_long_signal"]))
        self.assertFalse(bool(signals.iloc[0]["gap_fade_short_signal"]))
        self.assertGreaterEqual(int(signals.iloc[0]["gap_fade_quality_score"]), 4)

    def test_vwap_reclaim_flags_long_control_flip(self) -> None:
        candles = pd.DataFrame(
            [
                {
                    "open": 99.0,
                    "high": 99.8,
                    "low": 98.8,
                    "close": 99.2,
                    "volume": 1_000,
                    "vwap": 100.0,
                    "ema_9": 99.1,
                    "ema_21": 99.0,
                    "regular_session": True,
                    "entry_window": True,
                },
                {
                    "open": 99.3,
                    "high": 101.0,
                    "low": 99.8,
                    "close": 100.7,
                    "volume": 1_100,
                    "vwap": 100.0,
                    "ema_9": 100.4,
                    "ema_21": 100.1,
                    "regular_session": True,
                    "entry_window": True,
                },
            ],
            index=[
                pd.Timestamp("2026-06-02 10:00", tz="America/New_York"),
                pd.Timestamp("2026-06-02 10:30", tz="America/New_York"),
            ],
        )

        signals = add_vwap_reclaim_reject_signals(candles, STRATEGY)

        self.assertTrue(bool(signals.iloc[1]["vwap_reclaim_long_signal"]))
        self.assertFalse(bool(signals.iloc[1]["vwap_reject_short_signal"]))
        self.assertGreaterEqual(int(signals.iloc[1]["vwap_rr_quality_score"]), 4)

    def test_vwap_reclaim_walk_forward_flags_holding_up_recent_half(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "direction": "combined",
                    "research_status": "promising",
                    "tightened_review": "passes_tightened_research",
                    "expectancy_r": 0.25,
                    "profit_factor": 2.0,
                    "max_drawdown_r": -1.0,
                }
            ]
        )
        trades = pd.DataFrame(
            [
                {"symbol": "QQQ", "direction": "long", "entry_time": "2026-05-01 10:00:00+00:00", "r_result": 0.5},
                {"symbol": "QQQ", "direction": "short", "entry_time": "2026-05-02 10:00:00+00:00", "r_result": -0.2},
                {"symbol": "QQQ", "direction": "long", "entry_time": "2026-05-03 10:00:00+00:00", "r_result": 0.6},
                {"symbol": "QQQ", "direction": "short", "entry_time": "2026-05-04 10:00:00+00:00", "r_result": 0.4},
                {"symbol": "QQQ", "direction": "long", "entry_time": "2026-05-05 10:00:00+00:00", "r_result": 0.3},
                {"symbol": "QQQ", "direction": "short", "entry_time": "2026-05-06 10:00:00+00:00", "r_result": -0.1},
                {"symbol": "QQQ", "direction": "long", "entry_time": "2026-05-07 10:00:00+00:00", "r_result": 0.5},
                {"symbol": "QQQ", "direction": "short", "entry_time": "2026-05-08 10:00:00+00:00", "r_result": 0.2},
            ]
        )
        args = argparse.Namespace(
            min_half_trades=4,
            min_newer_expectancy_r=0.10,
            min_newer_profit_factor=1.20,
        )

        review = build_vwap_reclaim_walk_forward(summary, trades, args)

        self.assertEqual(review.iloc[0]["decision"], "holding_up")
        self.assertEqual(review.iloc[0]["newer_trades"], 4)
        self.assertGreater(review.iloc[0]["newer_expectancy_r"], 0.10)

    def test_vwap_reclaim_shadow_sample_row_builds_valid_plan(self) -> None:
        args = argparse.Namespace(
            target_r_multiple=1.25,
            reward_multiple_floor=0.80,
            min_quality_score=4,
            min_relative_volume=0.70,
            max_relative_volume=2.50,
            max_vwap_gap_pct=0.012,
            max_trend_gap_pct=0.010,
        )
        row = pd.Series(
            {
                "vwap_reclaim_long_signal": True,
                "vwap_rr_quality_score": 6,
                "vwap_rr_quality_grade": "A",
                "vwap_rr_relative_volume": 1.1,
                "vwap_rr_gap_pct": 0.001,
                "vwap_rr_trend_gap_pct": 0.002,
                "close": 101.0,
                "low": 99.8,
                "high": 101.2,
                "vwap": 100.0,
                "ema_9": 100.7,
                "ema_21": 100.2,
            }
        )

        sample = vwap_reclaim_shadow_sample_row(
            symbol="QQQ",
            timestamp=pd.Timestamp("2026-06-02 10:30", tz="America/New_York"),
            row=row,
            direction="long",
            signal_column="vwap_reclaim_long_signal",
            observed_at_et="2026-06-02 10:35:00 EDT",
            args=args,
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample["strategy"], "vwap_reclaim_reject")
        self.assertEqual(sample["direction"], "long")
        self.assertGreaterEqual(sample["reward_multiple"], 0.80)

    def test_trend_pullback_flags_long_recovery_from_ema_band(self) -> None:
        candles = pd.DataFrame(
            [
                {
                    "open": 101.0,
                    "high": 102.0,
                    "low": 100.7,
                    "close": 101.7,
                    "volume": 1_000,
                    "vwap": 100.5,
                    "ema_9": 101.2,
                    "ema_21": 100.9,
                    "ema_200": 99.5,
                    "regular_session": True,
                    "entry_window": True,
                }
            ],
            index=[pd.Timestamp("2026-06-02 11:00", tz="America/New_York")],
        )

        signals = add_trend_pullback_continuation_signals(candles, STRATEGY)

        self.assertTrue(bool(signals.iloc[0]["trend_pullback_long_signal"]))
        self.assertFalse(bool(signals.iloc[0]["trend_pullback_short_signal"]))
        self.assertGreaterEqual(int(signals.iloc[0]["trend_pullback_quality_score"]), 4)

    def test_approved_candidate_is_not_displaced_by_higher_expectancy_small_sample(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "symbol": "COIN",
                    "variant": "current",
                    "exit_profile": "no_vwap_exit",
                    "baseline_trades": 12,
                    "baseline_win_rate": 0.50,
                    "baseline_expectancy_r": 0.0212,
                    "baseline_profit_factor": 1.10,
                    "elite_trades": 0,
                    "elite_win_rate": 0.0,
                    "elite_expectancy_r": 0.0,
                    "elite_profit_factor": 0.0,
                },
                {
                    "symbol": "COIN",
                    "variant": "market_confirmed",
                    "exit_profile": "no_vwap_exit",
                    "baseline_trades": 8,
                    "baseline_win_rate": 0.50,
                    "baseline_expectancy_r": 0.0413,
                    "baseline_profit_factor": 1.30,
                    "elite_trades": 0,
                    "elite_win_rate": 0.0,
                    "elite_expectancy_r": 0.0,
                    "elite_profit_factor": 0.0,
                },
            ]
        )

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "selection.md"
            write_candidate_selection_report(summary, path, min_approved_trades=10)
            report = path.read_text(encoding="utf-8")

        self.assertIn("| COIN | approved | current + no_vwap_exit | 12 |", report)
        self.assertNotIn("| COIN | watch_more | market_confirmed + no_vwap_exit |", report)

    def test_strategy_selector_blocks_research_priority_from_paper_watch(self) -> None:
        selector = build_selector(
            [
                {
                    "strategy_id": "vwap_ema_trend_continuation",
                    "name": "VWAP + EMA Trend Continuation",
                    "status": "active_paper_watch",
                    "decision": "watch",
                    "paper_watch_decision": "not_applicable",
                },
                {
                    "strategy_id": "opening_range_failure",
                    "name": "Opening Range Failure",
                    "status": "research_backlog",
                    "decision": "research_priority",
                    "paper_watch_decision": "not_applicable",
                },
            ]
        )

        self.assertEqual(selector["mode"], "selective_watch")
        self.assertEqual(selector["paper_watch_strategy"], "VWAP + EMA Trend Continuation")
        self.assertEqual(selector["research_strategy"], "Opening Range Failure")
        self.assertIn("Do not paper-trade Opening Range Failure", selector["blocked_actions"][0])

    def test_strategy_evidence_accumulator_counts_today_and_matured_rows(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            journal = base / "journal.csv"
            outcomes = base / "outcomes.csv"
            pd.DataFrame(
                [
                    {"scan_date": "2026-06-02", "observed_at_et": "2026-06-02 10:30:00 EDT"},
                    {"scan_date": "2026-06-01", "observed_at_et": "2026-06-01 10:30:00 EDT"},
                ]
            ).to_csv(journal, index=False)
            pd.DataFrame(
                [
                    {"evaluation_status": "matured", "hypothetical_r": 0.5},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                ]
            ).to_csv(outcomes, index=False)

            lane = summarize_lane(
                strategy="Test Strategy",
                lane="test_lane",
                journal_path=journal,
                outcomes_path=outcomes,
                today="2026-06-02",
                market_is_open=True,
                note="test lane",
            )

        self.assertEqual(lane["status"], "collecting_today")
        self.assertEqual(lane["total_rows"], 2)
        self.assertEqual(lane["today_rows"], 1)
        self.assertEqual(lane["matured_outcomes"], 1)
        self.assertAlmostEqual(lane["average_r"], 0.5)

    def test_paper_activation_rules_require_all_strategy_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            vault = {
                "strategies": [
                    {
                        "strategy_id": "vwap_ema_trend_continuation",
                        "name": "VWAP + EMA Trend Continuation",
                        "status": "active_paper_watch",
                    },
                    {
                        "strategy_id": "vwap_mean_reversion",
                        "name": "VWAP Mean Reversion",
                        "status": "research_backlog",
                        "decision": "research_priority",
                        "paper_watch_decision": "not_ready",
                        "tightened_pass_rows": 1,
                        "walk_forward_holding_rows": 1,
                        "shadow_samples": 10,
                        "matured_shadow_samples": 5,
                        "shadow_average_r": 0.12,
                        "forward_observations": 0,
                        "matured_forward_observations": 0,
                        "forward_average_r": 0.0,
                    },
                ]
            }
            (output_dir / "strategy_vault.json").write_text(json.dumps(vault), encoding="utf-8")

            payload, summary, checklist = build_activation_payload(output_dir)

        self.assertEqual(payload["eligible_strategy_count"], 0)
        self.assertEqual(summary.iloc[0]["activation_decision"], "not_ready")
        self.assertIn("Strategy-specific gate exists", set(checklist[checklist["status"] == "blocked"]["check"]))
        self.assertIn("Strategy forward observations", set(checklist[checklist["status"] == "blocked"]["check"]))

    def test_strategy_backtest_coverage_matrix_marks_evidence_gaps(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            vault = {
                "strategies": [
                    {
                        "strategy_id": "vwap_reclaim_reject",
                        "name": "VWAP Reclaim / Reject",
                        "status": "research_backlog",
                        "decision": "research_priority",
                    },
                    {
                        "strategy_id": "gap_fill_fade",
                        "name": "Gap Fill / Gap Fade",
                        "status": "research_backlog",
                        "decision": "research_priority",
                    },
                ]
            }
            (output_dir / "strategy_vault.json").write_text(json.dumps(vault), encoding="utf-8")
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "activation_decision": "not_ready",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "tightened_review": "passes_tightened_research",
                        "research_status": "promising",
                    }
                ]
            ).to_csv(output_dir / "vwap_reclaim_reject_summary.csv", index=False)
            pd.DataFrame([{"decision": "holding_up"}]).to_csv(
                output_dir / "vwap_reclaim_reject_walk_forward.csv",
                index=False,
            )
            pd.DataFrame(
                [{"evaluation_status": "matured", "hypothetical_r": 0.3} for _ in range(5)]
                + [{"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""} for _ in range(5)]
            ).to_csv(output_dir / "vwap_reclaim_reject_shadow_outcomes.csv", index=False)
            pd.DataFrame(
                [{"evaluation_status": "matured", "hypothetical_r": 0.2} for _ in range(5)]
                + [{"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""} for _ in range(5)]
            ).to_csv(output_dir / "vwap_reclaim_reject_forward_observation_results.csv", index=False)
            (output_dir / "vwap_reclaim_reject_paper_watch_gate.json").write_text(
                json.dumps({"decision": "not_ready"}),
                encoding="utf-8",
            )

            payload = build_coverage(output_dir)

        rows = {row["strategy_id"]: row for row in payload["strategies"]}
        self.assertEqual(payload["strategy_count"], 2)
        self.assertEqual(rows["vwap_reclaim_reject"]["first_pass_backtest"], "complete")
        self.assertEqual(rows["vwap_reclaim_reject"]["walk_forward"], "complete")
        self.assertEqual(rows["vwap_reclaim_reject"]["forward_lane"], "complete")
        self.assertEqual(rows["vwap_reclaim_reject"]["activation_status"], "missing")
        self.assertEqual(rows["gap_fill_fade"]["first_pass_backtest"], "missing")
        self.assertIn("does not run backtests", payload["guardrail"])

    def test_strategy_backtest_coverage_marks_small_evidence_lanes_partial(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "name": "VWAP Reclaim / Reject",
                                "status": "research_backlog",
                                "decision": "research_priority",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame([{"tightened_review": "passes_tightened_research", "research_status": "promising"}]).to_csv(
                output_dir / "vwap_reclaim_reject_summary.csv",
                index=False,
            )
            pd.DataFrame([{"decision": "holding_up"}]).to_csv(
                output_dir / "vwap_reclaim_reject_walk_forward.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {"evaluation_status": "matured", "hypothetical_r": 0.3},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                ]
            ).to_csv(output_dir / "vwap_reclaim_reject_shadow_outcomes.csv", index=False)
            pd.DataFrame(
                [
                    {"evaluation_status": "matured", "hypothetical_r": 0.2},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                    {"evaluation_status": "awaiting_complete_session_data", "hypothetical_r": ""},
                ]
            ).to_csv(output_dir / "vwap_reclaim_reject_forward_observation_results.csv", index=False)
            (output_dir / "vwap_reclaim_reject_paper_watch_gate.json").write_text(
                json.dumps({"decision": "not_ready"}),
                encoding="utf-8",
            )

            payload = build_coverage(output_dir)

        row = payload["strategies"][0]
        self.assertEqual(row["shadow_lane"], "partial")
        self.assertEqual(row["forward_lane"], "partial")
        self.assertEqual(row["next_gap"], "Collect strategy shadow samples (4/10)")
        self.assertIn("Collect strategy shadow samples (4/10)", payload["next_action"])

    def test_research_strategy_tightened_review_marks_provisional_seed_rows(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "trades": 5,
                        "expectancy_r": 0.12,
                        "profit_factor": 1.4,
                        "max_drawdown_r": -1.0,
                        "research_status": "watch_more",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "opening_range_failure_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "decision": "needs_more_sample",
                        "newer_expectancy_r": 0.14,
                        "newer_profit_factor": 1.42,
                    }
                ]
            ).to_csv(output_dir / "opening_range_failure_walk_forward.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_final_trades=10,
                min_provisional_trades=5,
                min_expectancy_r=0.10,
                min_profit_factor=1.30,
                max_drawdown_r=-3.0,
                provisional_expectancy_buffer_r=0.02,
                provisional_profit_factor_buffer=0.05,
            )

            payload, rows = build_research_strategy_tightened_reviews(output_dir, args)

        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["provisional_pass_rows"], 1)
        self.assertEqual(rows.iloc[0]["decision"], "provisional_tightened_pass")
        self.assertIn("No orders", payload["guardrail"])

    def test_gap_fill_fade_seed_rows_can_enter_shadow_collection_only(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "gap_fill_fade",
                                "name": "Gap Fill / Gap Fade",
                                "status": "research_backlog",
                                "decision": "research_priority",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "symbol": "AMD",
                        "direction": "long",
                        "trades": 2,
                        "expectancy_r": 0.86,
                        "profit_factor": 999.0,
                        "max_drawdown_r": 0.0,
                        "research_status": "watch_more",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "gap_fill_fade_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "AMD",
                        "direction": "long",
                        "decision": "needs_more_sample",
                        "newer_expectancy_r": 0.94,
                        "newer_profit_factor": 999.0,
                    }
                ]
            ).to_csv(output_dir / "gap_fill_fade_walk_forward.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_final_trades=10,
                min_provisional_trades=5,
                min_expectancy_r=0.10,
                min_profit_factor=1.30,
                max_drawdown_r=-3.0,
                provisional_expectancy_buffer_r=0.02,
                provisional_profit_factor_buffer=0.05,
                min_seed_trades=2,
                min_seed_expectancy_r=0.20,
                min_seed_profit_factor=1.50,
                min_seed_newer_expectancy_r=0.10,
                min_seed_newer_profit_factor=1.20,
            )

            review_payload, review_rows = build_research_strategy_tightened_reviews(output_dir, args)
            coverage_payload = build_coverage(output_dir)

        coverage_row = coverage_payload["strategies"][0]
        self.assertEqual(review_payload["provisional_pass_rows"], 1)
        self.assertEqual(review_rows.iloc[0]["decision"], "seed_shadow_candidate")
        self.assertIn("not a paper-watch approval", review_rows.iloc[0]["next_action"])
        self.assertEqual(coverage_row["tightened_review"], "complete")
        self.assertEqual(coverage_row["walk_forward"], "complete")
        self.assertEqual(coverage_row["next_gap"], "Collect strategy shadow samples (0/10)")

    def test_strategy_backtest_coverage_uses_generic_tightened_review(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            vault = {
                "strategies": [
                    {
                        "strategy_id": "opening_range_failure",
                        "name": "Opening Range Failure",
                        "status": "research_backlog",
                        "decision": "research_priority",
                    }
                ]
            }
            (output_dir / "strategy_vault.json").write_text(json.dumps(vault), encoding="utf-8")
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "research_status": "watch_more",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "opening_range_failure_summary.csv", index=False)
            pd.DataFrame([{"decision": "provisional_tightened_pass"}]).to_csv(
                output_dir / "opening_range_failure_tightened_review.csv",
                index=False,
            )

            payload = build_coverage(output_dir)

        row = payload["strategies"][0]
        self.assertEqual(row["tightened_review"], "complete")
        self.assertEqual(row["provisional_tightened_pass_rows"], 1)
        self.assertEqual(row["next_gap"], "Add or pass walk-forward")

    def test_opening_range_failure_deep_walk_forward_marks_provisional_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "decision": "needs_more_sample",
                        "full_trades": 5,
                        "full_expectancy_r": 0.14,
                        "full_profit_factor": 1.54,
                        "full_max_drawdown_r": -1.0,
                        "older_trades": 2,
                        "newer_trades": 3,
                        "newer_expectancy_r": 0.14,
                        "newer_profit_factor": 1.42,
                    }
                ]
            ).to_csv(output_dir / "opening_range_failure_walk_forward.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "decision": "provisional_tightened_pass",
                    }
                ]
            ).to_csv(output_dir / "opening_range_failure_tightened_review.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_final_half_trades=4,
                min_provisional_full_trades=5,
                min_newer_expectancy_r=0.10,
                min_newer_profit_factor=1.20,
                max_full_drawdown_r=-3.0,
            )

            payload, rows = build_opening_range_failure_deep_walk_forward(output_dir, args)

        self.assertEqual(payload["provisional_walk_forward_pass_rows"], 1)
        self.assertEqual(rows.iloc[0]["decision"], "provisional_walk_forward_pass")
        self.assertIn("Research-only", payload["guardrail"])

    def test_opening_range_breakout_deep_walk_forward_deprioritizes_weak_newer_slice(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "long",
                        "decision": "mixed",
                        "full_trades": 11,
                        "full_expectancy_r": 0.096,
                        "full_profit_factor": 1.2904,
                        "full_max_drawdown_r": -2.2093,
                        "older_trades": 5,
                        "older_expectancy_r": 0.1981,
                        "newer_trades": 6,
                        "newer_expectancy_r": 0.0108,
                        "newer_profit_factor": 1.027,
                        "expectancy_delta_newer_vs_older": -0.1873,
                    }
                ]
            ).to_csv(output_dir / "opening_range_breakout_walk_forward.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "long",
                        "decision": "provisional_tightened_pass",
                    }
                ]
            ).to_csv(output_dir / "opening_range_breakout_tightened_review.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_final_half_trades=4,
                min_provisional_full_trades=5,
                min_newer_expectancy_r=0.08,
                min_newer_profit_factor=1.20,
                max_full_drawdown_r=-3.0,
            )

            payload, rows = build_opening_range_breakout_deep_walk_forward(output_dir, args)

        self.assertEqual(payload["provisional_walk_forward_pass_rows"], 0)
        self.assertEqual(payload["deprioritized_rows"], 1)
        self.assertEqual(rows.iloc[0]["decision"], "deprioritize_or_wait")
        self.assertIn("newer expectancy below", rows.iloc[0]["blockers"])
        self.assertIn("Research-only", payload["guardrail"])

    def test_strategy_backtest_coverage_uses_opening_range_failure_deep_walk_forward(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "opening_range_failure",
                                "name": "Opening Range Failure",
                                "status": "research_backlog",
                                "decision": "research_priority",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "research_status": "watch_more",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "opening_range_failure_summary.csv", index=False)
            pd.DataFrame([{"decision": "provisional_tightened_pass"}]).to_csv(
                output_dir / "opening_range_failure_tightened_review.csv",
                index=False,
            )
            pd.DataFrame([{"decision": "needs_more_sample"}]).to_csv(
                output_dir / "opening_range_failure_walk_forward.csv",
                index=False,
            )
            pd.DataFrame([{"decision": "provisional_walk_forward_pass"}]).to_csv(
                output_dir / "opening_range_failure_walk_forward_deepening.csv",
                index=False,
            )

            payload = build_coverage(output_dir)

        row = payload["strategies"][0]
        self.assertEqual(row["walk_forward"], "complete")
        self.assertEqual(row["walk_forward_holding_rows"], 1)
        self.assertEqual(row["next_gap"], "Collect strategy shadow samples (0/10)")

    def test_strategy_backtest_coverage_keeps_opening_range_breakout_blocked_without_deep_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "opening_range_breakout",
                                "name": "Opening Range Breakout",
                                "status": "research_backlog",
                                "decision": "research_backlog",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "long",
                        "research_status": "watch_more",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "opening_range_breakout_summary.csv", index=False)
            pd.DataFrame([{"decision": "provisional_tightened_pass"}]).to_csv(
                output_dir / "opening_range_breakout_tightened_review.csv",
                index=False,
            )
            pd.DataFrame([{"decision": "mixed"}]).to_csv(
                output_dir / "opening_range_breakout_walk_forward.csv",
                index=False,
            )
            pd.DataFrame([{"decision": "deprioritize_or_wait"}]).to_csv(
                output_dir / "opening_range_breakout_walk_forward_deepening.csv",
                index=False,
            )

            payload = build_coverage(output_dir)

        row = payload["strategies"][0]
        self.assertEqual(row["walk_forward"], "partial")
        self.assertEqual(row["walk_forward_holding_rows"], 0)
        self.assertEqual(row["next_gap"], "Add or pass walk-forward")

    def test_validation_deepening_queue_ranks_closest_research_task(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "name": "VWAP Reclaim / Reject",
                                "decision": "research_priority",
                                "status": "research_backlog",
                            },
                            {
                                "strategy_id": "gap_fill_fade",
                                "name": "Gap Fill / Gap Fade",
                                "decision": "research_priority",
                                "status": "research_backlog",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_id": "vwap_reclaim_reject", "activation_decision": "not_ready"},
                            {"strategy_id": "gap_fill_fade", "activation_decision": "not_ready"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "strategy_backtest_coverage.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "strategy": "VWAP Reclaim / Reject",
                                "vault_decision": "research_priority",
                                "coverage_points": 5.0,
                                "coverage_percent": 71.4,
                                "next_gap": "Collect strategy shadow samples (4/10)",
                                "tightened_review": "complete",
                                "walk_forward": "complete",
                                "shadow_lane": "partial",
                                "shadow_rows": 4,
                                "matured_shadow": 0,
                                "forward_lane": "partial",
                                "forward_rows": 4,
                                "matured_forward": 0,
                                "paper_watch_gate": "complete",
                                "gate_decision": "not_ready",
                            },
                            {
                                "strategy_id": "gap_fill_fade",
                                "strategy": "Gap Fill / Gap Fade",
                                "vault_decision": "research_priority",
                                "coverage_points": 1.0,
                                "coverage_percent": 14.3,
                                "next_gap": "Tighten review filters",
                                "tightened_review": "missing",
                                "walk_forward": "missing",
                                "shadow_lane": "missing",
                                "shadow_rows": 0,
                                "matured_shadow": 0,
                                "forward_lane": "missing",
                                "forward_rows": 0,
                                "matured_forward": 0,
                                "paper_watch_gate": "missing",
                                "gate_decision": "missing",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            payload = build_validation_deepening_queue(output_dir)

        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["top_strategy_id"], "vwap_reclaim_reject")
        self.assertEqual(payload["top_validation_lane"], "shadow_collection")
        self.assertEqual(payload["top_next_gap"], "Collect strategy shadow samples (4/10)")
        self.assertIn("market-hours scans", payload["top_next_command"])
        self.assertIn("does not run backtests", payload["guardrail"])

    def test_validation_deepening_queue_deprioritizes_weak_deep_walk_forward(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "name": "VWAP Reclaim / Reject",
                                "decision": "research_priority",
                                "status": "research_backlog",
                            },
                            {
                                "strategy_id": "opening_range_breakout",
                                "name": "Opening Range Breakout",
                                "decision": "research_priority",
                                "status": "research_backlog",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_id": "vwap_reclaim_reject", "activation_decision": "not_ready"},
                            {"strategy_id": "opening_range_breakout", "activation_decision": "not_ready"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "strategy_backtest_coverage.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "strategy": "VWAP Reclaim / Reject",
                                "coverage_points": 5.0,
                                "coverage_percent": 71.4,
                                "next_gap": "Collect strategy shadow samples (4/10)",
                                "shadow_lane": "partial",
                                "forward_lane": "partial",
                                "walk_forward": "complete",
                            },
                            {
                                "strategy_id": "opening_range_breakout",
                                "strategy": "Opening Range Breakout",
                                "coverage_points": 4.0,
                                "coverage_percent": 57.1,
                                "next_gap": "Add or pass walk-forward",
                                "shadow_lane": "complete",
                                "forward_lane": "complete",
                                "walk_forward": "partial",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "opening_range_breakout_walk_forward_deepening.json").write_text(
                json.dumps(
                    {
                        "review_rows": 5,
                        "walk_forward_pass_rows": 0,
                        "provisional_walk_forward_pass_rows": 0,
                        "deprioritized_rows": 5,
                        "next_action": "Keep Opening Range Breakout deprioritized until newer slices improve.",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_validation_deepening_queue(output_dir)

        breakout = next(row for row in payload["strategies"] if row["strategy_id"] == "opening_range_breakout")
        self.assertEqual(payload["top_strategy_id"], "vwap_reclaim_reject")
        self.assertEqual(breakout["validation_lane"], "deprioritized")
        self.assertLess(breakout["priority_score"], 0)
        self.assertEqual(breakout["next_gap"], "Deprioritized until evidence improves")

    def test_strategy_triage_separates_market_hours_and_deprioritized_work(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "strategy_vault.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "name": "VWAP Reclaim / Reject",
                                "decision": "research_priority",
                                "status": "research_backlog",
                            },
                            {
                                "strategy_id": "opening_range_breakout",
                                "name": "Opening Range Breakout",
                                "decision": "research_priority",
                                "status": "research_backlog",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_activation_rules.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_id": "vwap_reclaim_reject", "activation_decision": "not_ready"},
                            {"strategy_id": "opening_range_breakout", "activation_decision": "not_ready"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "strategy_backtest_coverage.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_id": "vwap_reclaim_reject",
                                "strategy": "VWAP Reclaim / Reject",
                                "coverage_percent": 71.4,
                                "next_gap": "Collect strategy shadow samples (4/10)",
                                "shadow_rows": 4,
                                "forward_rows": 4,
                            },
                            {
                                "strategy_id": "opening_range_breakout",
                                "strategy": "Opening Range Breakout",
                                "coverage_percent": 57.1,
                                "next_gap": "Add or pass walk-forward",
                                "shadow_rows": 10,
                                "forward_rows": 10,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "opening_range_breakout_walk_forward_deepening.json").write_text(
                json.dumps(
                    {
                        "review_rows": 5,
                        "walk_forward_pass_rows": 0,
                        "provisional_walk_forward_pass_rows": 0,
                        "deprioritized_rows": 5,
                        "next_action": "Keep Opening Range Breakout deprioritized until newer slices improve.",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_triage(output_dir)

        tiers = {row["strategy_id"]: row["triage_tier"] for row in payload["strategies"]}
        self.assertEqual(payload["top_strategy_id"], "vwap_reclaim_reject")
        self.assertEqual(tiers["vwap_reclaim_reject"], "market_hours_collection")
        self.assertEqual(tiers["opening_range_breakout"], "deprioritized")
        self.assertIn("does not fetch data", payload["guardrail"])

    def test_strategy_backtest_coverage_uses_trend_pullback_provisional_review(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            vault = {
                "strategies": [
                    {
                        "strategy_id": "trend_pullback_continuation",
                        "name": "Trend Pullback Continuation",
                        "status": "research_backlog",
                        "decision": "research_priority",
                    }
                ]
            }
            (output_dir / "strategy_vault.json").write_text(json.dumps(vault), encoding="utf-8")
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "research_status": "promising",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "trend_pullback_continuation_summary.csv", index=False)
            pd.DataFrame([{"decision": "holding_up"}]).to_csv(
                output_dir / "trend_pullback_continuation_walk_forward.csv",
                index=False,
            )
            pd.DataFrame([{"decision": "provisional_tightened_pass"}]).to_csv(
                output_dir / "trend_pullback_continuation_tightened_review.csv",
                index=False,
            )

            payload = build_coverage(output_dir)

        row = payload["strategies"][0]
        self.assertEqual(row["tightened_review"], "complete")
        self.assertEqual(row["provisional_tightened_pass_rows"], 1)
        self.assertEqual(row["next_gap"], "Collect strategy shadow samples (0/10)")

    def test_balanced_seed_review_keeps_small_positive_strategy_rows_alive(self) -> None:
        seed_metrics = {
            "trades": 2,
            "expectancy_r": 0.20,
            "profit_factor": 1.50,
            "max_drawdown_r": -1.0,
        }
        weak_metrics = {
            "trades": 2,
            "expectancy_r": -0.05,
            "profit_factor": 0.80,
            "max_drawdown_r": -1.0,
        }

        self.assertEqual(gap_fill_research_status(seed_metrics), "watch_more")
        self.assertEqual(opening_range_failure_research_status(seed_metrics), "watch_more")
        self.assertEqual(opening_range_breakout_research_status(seed_metrics), "watch_more")
        self.assertEqual(gap_fill_research_status(weak_metrics), "too_few_trades")
        self.assertEqual(opening_range_failure_research_status(weak_metrics), "too_few_trades")
        self.assertEqual(opening_range_breakout_research_status(weak_metrics), "too_few_trades")

    def test_new_strategy_paper_watch_gates_block_seed_rows_until_full_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            for stem in ["gap_fill_fade", "opening_range_breakout", "opening_range_failure"]:
                pd.DataFrame(
                    [
                        {
                            "symbol": "AMD",
                            "direction": "long",
                            "trades": 2,
                            "expectancy_r": 0.4,
                            "profit_factor": 2.0,
                            "tightened_review": "needs_more_evidence",
                            "research_status": "watch_more",
                        }
                    ]
                ).to_csv(output_dir / f"{stem}_summary.csv", index=False)
                pd.DataFrame([{"decision": "needs_more_sample"}]).to_csv(
                    output_dir / f"{stem}_walk_forward.csv",
                    index=False,
                )
            args = argparse.Namespace(
                output_dir=output_dir,
                min_tightened_pass_rows=1,
                min_walk_forward_holding_rows=1,
                min_shadow_samples=10,
                min_matured_shadow_samples=5,
                min_shadow_average_r=0.10,
                min_forward_observations=10,
                min_matured_forward_observations=5,
                min_forward_average_r=0.10,
            )

            gates = [
                build_gap_fill_gate(args)[0],
                build_opening_range_breakout_gate(args)[0],
                build_opening_range_failure_gate(args)[0],
            ]

        for payload in gates:
            self.assertEqual(payload["decision"], "not_ready")
            self.assertEqual(payload["watch_more_rows"], 1)
            self.assertEqual(payload["tightened_pass_rows"], 0)
            self.assertEqual(payload["next_blocker"], "Tightened research pass")
            self.assertIn("No broker orders", payload["guardrail"])

    def test_new_strategy_sample_lanes_build_research_only_rows(self) -> None:
        gap_args = argparse.Namespace(
            reward_multiple_floor=0.70,
            min_quality_score=4,
            min_gap_pct=0.004,
            max_gap_pct=0.040,
            min_relative_volume=0.70,
            max_relative_volume=2.80,
        )
        gap_row = pd.Series(
            {
                "gap_fade_long_signal": True,
                "gap_fade_quality_score": 5,
                "gap_fade_quality_grade": "A",
                "gap_fade_relative_volume": 1.1,
                "gap_fade_gap_pct": -0.01,
                "close": 99.0,
                "low": 98.4,
                "high": 99.3,
                "vwap": 98.8,
                "session_open": 98.6,
                "prior_close": 100.0,
                "ema_9": 99.1,
                "ema_21": 99.0,
            }
        )

        sample = research_strategy_sample_row(
            spec=GAP_FILL_SAMPLE_SPEC,
            symbol="AMD",
            timestamp=pd.Timestamp("2026-06-02 10:30", tz="America/New_York"),
            row=gap_row,
            direction="long",
            signal_column="gap_fade_long_signal",
            observed_at_et="2026-06-02 10:35:00 EDT",
            args=gap_args,
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample["strategy"], "gap_fill_fade")
        self.assertEqual(sample["shadow_status"], "strategy_shadow_candidate")
        self.assertGreater(sample["reward_multiple"], 0.70)

        breakout_args = argparse.Namespace(
            target_r_multiple=1.20,
            reward_multiple_floor=0.80,
            min_quality_score=4,
            min_relative_volume=0.80,
            max_relative_volume=2.50,
            max_trend_gap_pct=0.012,
        )
        breakout_row = pd.Series(
            {
                "or_breakout_long_signal": True,
                "or_breakout_quality_score": 5,
                "or_breakout_quality_grade": "A",
                "or_breakout_relative_volume": 1.2,
                "or_breakout_trend_gap_pct": 0.003,
                "or_breakout_range_width_pct": 0.01,
                "close": 101.5,
                "low": 100.8,
                "high": 102.0,
                "vwap": 100.5,
                "opening_range_high": 101.0,
                "opening_range_low": 99.5,
                "ema_9": 101.0,
                "ema_21": 100.5,
            }
        )

        breakout_sample = research_strategy_sample_row(
            spec=OR_BREAKOUT_SAMPLE_SPEC,
            symbol="QQQ",
            timestamp=pd.Timestamp("2026-06-02 10:30", tz="America/New_York"),
            row=breakout_row,
            direction="long",
            signal_column="or_breakout_long_signal",
            observed_at_et="2026-06-02 10:35:00 EDT",
            args=breakout_args,
        )

        self.assertIsNotNone(breakout_sample)
        assert breakout_sample is not None
        self.assertEqual(breakout_sample["strategy"], "opening_range_breakout")
        self.assertEqual(breakout_sample["shadow_status"], "strategy_shadow_candidate")
        self.assertGreaterEqual(breakout_sample["quality_score"], 4)

    def test_trend_pullback_tightened_review_marks_provisional_lane_building(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "trades": 8,
                        "expectancy_r": 0.3,
                        "profit_factor": 2.0,
                        "max_drawdown_r": -1.0,
                        "research_status": "promising",
                        "tightened_review": "needs_more_evidence",
                    }
                ]
            ).to_csv(output_dir / "trend_pullback_continuation_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "decision": "holding_up",
                        "newer_expectancy_r": 0.2,
                        "newer_profit_factor": 1.5,
                    }
                ]
            ).to_csv(output_dir / "trend_pullback_continuation_walk_forward.csv", index=False)
            args = argparse.Namespace(
                min_final_trades=10,
                min_provisional_trades=8,
                min_expectancy_r=0.1,
                min_profit_factor=1.3,
                max_drawdown_r=-3.0,
            )

            payload, rows = build_trend_pullback_tightened_review(output_dir, args)

        self.assertEqual(payload["final_pass_rows"], 0)
        self.assertEqual(payload["provisional_pass_rows"], 1)
        self.assertEqual(rows.iloc[0]["decision"], "provisional_tightened_pass")
        self.assertIn("does not approve paper-watch", payload["guardrail"])

    def test_trend_pullback_shadow_sample_row_builds_valid_plan(self) -> None:
        args = argparse.Namespace(
            target_r_multiple=1.5,
            reward_multiple_floor=0.9,
            min_quality_score=4,
            min_relative_volume=0.7,
            max_relative_volume=2.4,
            max_trend_gap_pct=0.01,
            max_vwap_gap_pct=0.02,
        )
        row = pd.Series(
            {
                "trend_pullback_long_signal": True,
                "trend_pullback_quality_score": 4,
                "trend_pullback_quality_grade": "B",
                "trend_pullback_relative_volume": 1.1,
                "trend_pullback_trend_gap_pct": 0.004,
                "trend_pullback_vwap_gap_pct": 0.006,
                "close": 101.0,
                "low": 100.2,
                "high": 101.4,
                "vwap": 100.6,
                "ema_9": 100.8,
                "ema_21": 100.4,
            }
        )

        sample = trend_pullback_shadow_sample_row(
            symbol="QQQ",
            timestamp=pd.Timestamp("2026-05-28 10:00", tz=MARKET_TZ),
            row=row,
            direction="long",
            signal_column="trend_pullback_long_signal",
            observed_at_et="2026-05-28 10:05:00 EDT",
            args=args,
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample["strategy"], "trend_pullback_continuation")
        self.assertEqual(sample["shadow_status"], "strategy_shadow_candidate")
        self.assertGreater(sample["risk_per_share"], 0)
        self.assertGreaterEqual(sample["reward_multiple"], 0.9)

    def test_strategy_walk_forward_matrix_builds_generic_reviews(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "direction": "combined",
                        "research_status": "promising",
                        "tightened_review": "passes_tightened_research",
                        "expectancy_r": 0.3,
                        "profit_factor": 2.0,
                        "max_drawdown_r": -1.0,
                    }
                ]
            ).to_csv(output_dir / "gap_fill_fade_summary.csv", index=False)
            pd.DataFrame(
                [
                    {"symbol": "QQQ", "direction": "long", "entry_time": f"2026-05-{day:02d} 10:00:00+00:00", "r_result": result}
                    for day, result in zip(range(1, 9), [0.2, -0.1, 0.4, 0.3, 0.5, 0.2, 0.1, 0.4])
                ]
            ).to_csv(output_dir / "gap_fill_fade_trades.csv", index=False)
            args = argparse.Namespace(
                output_dir=output_dir,
                min_half_trades=4,
                min_newer_expectancy_r=0.1,
                min_newer_profit_factor=1.2,
            )

            payload, combined = build_strategy_walk_forward_payload(output_dir, args)

        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["review_rows"], 1)
        self.assertEqual(payload["holding_up_rows"], 1)
        self.assertEqual(combined.iloc[0]["strategy_id"], "gap_fill_fade")
        self.assertEqual(combined.iloc[0]["decision"], "holding_up")

    def test_mean_reversion_recent_window_sample_row_builds_valid_plan(self) -> None:
        args = argparse.Namespace(
            min_quality_score=4,
            min_relative_volume=0.5,
            max_relative_volume=1.4,
            min_vwap_gap_pct=0.0015,
            max_trend_gap_pct=0.004,
            reward_multiple_floor=0.6,
        )
        row = pd.Series(
            {
                "mean_reversion_long_signal": True,
                "mean_reversion_quality_score": 4,
                "mean_reversion_quality_grade": "B",
                "mean_reversion_relative_volume": 1.0,
                "mean_reversion_vwap_gap_pct": 0.01,
                "mean_reversion_trend_gap_pct": 0.001,
                "close": 99.0,
                "low": 98.0,
                "high": 100.0,
                "vwap": 100.0,
                "ema_9": 99.2,
                "ema_21": 99.1,
            }
        )

        sample = mean_reversion_sample_row(
            symbol="QQQ",
            timestamp=pd.Timestamp("2026-06-02 10:30", tz="America/New_York"),
            row=row,
            direction="long",
            signal_column="mean_reversion_long_signal",
            observed_at_et="2026-06-02 10:35:00 EDT",
            args=args,
        )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample["symbol"], "QQQ")
        self.assertEqual(sample["direction"], "long")
        self.assertEqual(sample["scan_date"], "2026-06-02")
        self.assertGreater(sample["reward_multiple"], 0.6)

    def test_research_confidence_scores_broad_universe_without_live_approval(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "variant": "market_confirmed",
                        "exit_profile": "trailing_5m",
                        "baseline_trades": 24,
                        "baseline_win_rate": 0.58,
                        "baseline_expectancy_r": 0.16,
                        "baseline_profit_factor": 1.55,
                        "summary_report": "logs/universe_expansion/QQQ_summary.md",
                    },
                    {
                        "symbol": "SLOW",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "baseline_trades": 4,
                        "baseline_win_rate": 0.25,
                        "baseline_expectancy_r": -0.20,
                        "baseline_profit_factor": 0.60,
                        "summary_report": "logs/universe_expansion/SLOW_summary.md",
                    },
                ]
            ).to_csv(output_dir / "best_plus_market_watchlist_backtest_summary.csv", index=False)

            rows = build_research_confidence_rows(output_dir)

        self.assertEqual(rows.iloc[0]["symbol"], "QQQ")
        self.assertEqual(rows.iloc[0]["research_status"], "research_ready")
        self.assertGreater(rows.iloc[0]["readiness_score"], 50)
        self.assertEqual(readiness_status(24, 0.16, 1.55), "research_ready")

    def test_research_confidence_uses_quality_variant_metrics(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "variant": "quality_entry",
                        "exit_profile": "no_vwap_exit",
                        "baseline_trades": 24,
                        "baseline_win_rate": 0.58,
                        "baseline_expectancy_r": -0.20,
                        "baseline_profit_factor": 0.70,
                        "elite_trades": 12,
                        "elite_win_rate": 0.67,
                        "elite_expectancy_r": 0.25,
                        "elite_profit_factor": 2.20,
                        "summary_report": "logs/universe_expansion/QQQ_quality_summary.md",
                    }
                ]
            ).to_csv(output_dir / "best_plus_market_watchlist_backtest_summary.csv", index=False)

            rows = build_research_confidence_rows(output_dir)

        self.assertEqual(rows.iloc[0]["trades"], 12)
        self.assertEqual(rows.iloc[0]["expectancy_r"], 0.25)
        self.assertEqual(rows.iloc[0]["research_status"], "promising")

    def test_controlled_variant_review_compares_filter_to_control(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "WMT",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "baseline_trades": 30,
                        "baseline_win_rate": 0.50,
                        "baseline_expectancy_r": 0.08,
                        "baseline_profit_factor": 1.20,
                        "elite_trades": 0,
                        "elite_win_rate": 0.0,
                        "elite_expectancy_r": 0.0,
                        "elite_profit_factor": 0.0,
                    },
                    {
                        "symbol": "WMT",
                        "variant": "market_confirmed",
                        "exit_profile": "no_vwap_exit",
                        "baseline_trades": 20,
                        "baseline_win_rate": 0.60,
                        "baseline_expectancy_r": 0.16,
                        "baseline_profit_factor": 1.70,
                        "elite_trades": 0,
                        "elite_win_rate": 0.0,
                        "elite_expectancy_r": 0.0,
                        "elite_profit_factor": 0.0,
                    },
                ]
            ).to_csv(output_dir / "best_plus_market_watchlist_backtest_summary.csv", index=False)

            review = build_controlled_review(output_dir)

        market_row = review[review["comparison"] == "market filter vs baseline"].iloc[0]
        self.assertEqual(market_row["decision"], "improves")
        self.assertAlmostEqual(market_row["expectancy_delta"], 0.08)

    def test_walk_forward_review_flags_fading_recent_half(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            summary = output_dir / "WMT_current_summary.md"
            trade_log = output_dir / "WMT_current_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "symbol": "WMT",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "research_status": "research_ready",
                        "expectancy_r": 0.10,
                        "summary_report": str(summary),
                    }
                ]
            ).to_csv(output_dir / "research_confidence.csv", index=False)
            rows = []
            for day in range(1, 21):
                rows.append(
                    {
                        "entry_time": f"2026-01-{day:02d}T15:00:00Z",
                        "r_result": 0.30 if day <= 10 else -0.20,
                    }
                )
            pd.DataFrame(rows).to_csv(trade_log, index=False)

            review = build_walk_forward_review(output_dir, limit=5)

        self.assertEqual(review.iloc[0]["decision"], "fading")
        self.assertLess(review.iloc[0]["second_expectancy_r"], 0)

    def test_regime_review_scores_trades_by_market_backdrop(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            summary = output_dir / "WMT_current_summary.md"
            trade_log = output_dir / "WMT_current_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "symbol": "WMT",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "research_status": "research_ready",
                        "summary_report": str(summary),
                    }
                ]
            ).to_csv(output_dir / "research_confidence.csv", index=False)
            pd.DataFrame(
                [
                    {"entry_time": "2026-01-02T15:00:00Z", "r_result": 0.30},
                    {"entry_time": "2026-01-02T15:30:00Z", "r_result": 0.20},
                    {"entry_time": "2026-01-02T16:00:00Z", "r_result": 0.40},
                    {"entry_time": "2026-01-02T16:30:00Z", "r_result": 0.10},
                    {"entry_time": "2026-01-02T17:00:00Z", "r_result": 0.30},
                    {"entry_time": "2026-01-02T17:30:00Z", "r_result": 0.20},
                    {"entry_time": "2026-01-02T18:00:00Z", "r_result": 0.10},
                    {"entry_time": "2026-01-02T18:30:00Z", "r_result": 0.30},
                ]
            ).to_csv(trade_log, index=False)
            market_rows = []
            for index in range(20):
                market_rows.append(
                    {
                        "datetime": f"2026-01-02T{14 + index // 2:02d}:{30 if index % 2 == 0 else 0:02d}:00Z",
                        "open": 100 + index,
                        "high": 101 + index,
                        "low": 99 + index,
                        "close": 100.8 + index,
                        "volume": 1000 + index,
                    }
                )
            pd.DataFrame(market_rows).to_csv(output_dir / "webull_SPY_M30_candles.csv", index=False)

            review = build_regime_review(output_dir, "SPY", limit=5)

        market_review = review[review["regime_type"] == "market_regime"]
        self.assertIn("bullish", set(market_review["regime"]))
        self.assertIn("favorable", set(market_review["decision"]))

    def test_system_state_exposes_research_confidence_as_review_only(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            research_dir = output_dir / "universe_expansion"
            research_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "research_status": "research_ready",
                        "readiness_score": 82,
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "market_confirmed + trailing_5m",
                        "trades": 24,
                        "win_rate_pct": 58.0,
                        "expectancy_r": 0.16,
                        "profit_factor": 1.55,
                        "summary_report": "logs/universe_expansion/QQQ_summary.md",
                    }
                ]
            ).to_csv(research_dir / "research_confidence.csv", index=False)
            (research_dir / "research_confidence.md").write_text(
                "research_ready means worth deeper review, not real-money ready.",
                encoding="utf-8",
            )

            state = build_system_state(output_dir=output_dir, paper_csv=output_dir / "paper.csv")

        self.assertFalse(state["safety"]["live_trading_enabled"])
        self.assertFalse(state["safety"]["broker_order_execution_enabled"])
        self.assertEqual(state["research_confidence"]["research_ready_count"], 1)
        self.assertEqual(state["research_confidence"]["top_candidates"][0]["symbol"], "QQQ")

    def test_evidence_maturity_progress_ranks_closest_strategy(self) -> None:
        vault = {
            "strategies": [
                {
                    "strategy_id": "trend_pullback_continuation",
                    "name": "Trend Pullback Continuation",
                    "status": "research_backlog",
                    "paper_watch_decision": "not_ready",
                    "paper_watch_blocker": "Shadow samples logged",
                    "tightened_pass_rows": 4,
                    "walk_forward_holding_rows": 4,
                    "shadow_samples": 4,
                    "matured_shadow_samples": 1,
                    "shadow_average_r": 0.8585,
                    "forward_observations": 4,
                    "matured_forward_observations": 1,
                    "forward_average_r": 0.8585,
                },
                {
                    "strategy_id": "gap_fill_fade",
                    "name": "Gap Fill / Fade",
                    "status": "research_backlog",
                    "paper_watch_decision": "not_applicable",
                    "tightened_pass_rows": 0,
                    "walk_forward_holding_rows": 0,
                    "shadow_samples": 0,
                    "matured_shadow_samples": 0,
                    "forward_observations": 0,
                    "matured_forward_observations": 0,
                },
            ]
        }

        progress = evidence_maturity_progress_state(vault)

        self.assertEqual(progress["nearest_strategy"]["strategy_id"], "trend_pullback_continuation")
        self.assertEqual(progress["nearest_strategy"]["maturity_percent"], 25.0)
        self.assertEqual(progress["nearest_strategy"]["shadow_needed"], 6)
        self.assertEqual(progress["nearest_strategy"]["matured_forward_needed"], 4)
        self.assertIn("paper-validation only", progress["guardrail"])

    def test_promotion_review_promotes_only_stable_paper_watch_candidates(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            summary = output_dir / "QQQ_current_summary.md"
            trade_log = output_dir / "QQQ_current_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "trades": 20,
                        "win_rate_pct": 60.0,
                        "expectancy_r": 0.15,
                        "profit_factor": 1.6,
                        "readiness_score": 70,
                        "research_status": "research_ready",
                        "summary_report": str(summary),
                    },
                    {
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "quality_entry + no_vwap_exit",
                        "trades": 20,
                        "win_rate_pct": 60.0,
                        "expectancy_r": 0.15,
                        "profit_factor": 1.6,
                        "readiness_score": 70,
                        "research_status": "research_ready",
                        "summary_report": str(output_dir / "QQQ_quality_entry_summary.md"),
                    }
                ]
            ).to_csv(output_dir / "research_confidence.csv", index=False)
            pd.DataFrame(
                [
                    {"entry_time": "2026-01-02T15:00:00Z", "r_result": 0.5, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-03T15:00:00Z", "r_result": 0.4, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-04T15:00:00Z", "r_result": -0.2, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-05T15:00:00Z", "r_result": 0.3, "exit_reason": "profit_target_5m"},
                    {"entry_time": "2026-01-06T15:00:00Z", "r_result": 0.2, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-07T15:00:00Z", "r_result": -0.1, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-08T15:00:00Z", "r_result": 0.4, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-09T15:00:00Z", "r_result": 0.2, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-01-10T15:00:00Z", "r_result": -0.3, "exit_reason": "stop_loss_5m"},
                    {"entry_time": "2026-01-11T15:00:00Z", "r_result": 0.6, "exit_reason": "profit_target_5m"},
                    {"entry_time": "2026-02-02T15:00:00Z", "r_result": 0.3, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-02-03T15:00:00Z", "r_result": 0.2, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-02-04T15:00:00Z", "r_result": -0.2, "exit_reason": "stop_loss_5m"},
                    {"entry_time": "2026-02-05T15:00:00Z", "r_result": 0.4, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-02-06T15:00:00Z", "r_result": 0.1, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-02-07T15:00:00Z", "r_result": -0.2, "exit_reason": "stop_loss_5m"},
                    {"entry_time": "2026-02-08T15:00:00Z", "r_result": 0.5, "exit_reason": "profit_target_5m"},
                    {"entry_time": "2026-02-09T15:00:00Z", "r_result": 0.1, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-02-10T15:00:00Z", "r_result": -0.1, "exit_reason": "end_of_day_exit"},
                    {"entry_time": "2026-02-11T15:00:00Z", "r_result": 0.2, "exit_reason": "end_of_day_exit"},
                ]
            ).to_csv(trade_log, index=False)

            review = build_promotion_review(output_dir, limit=5)

        self.assertEqual(review.iloc[0]["promotion_decision"], "paper_watch_candidate")
        self.assertIn("manual paper-watch", review.iloc[0]["promotion_reason"])
        self.assertEqual(len(review), 1)
        self.assertEqual(review.iloc[0]["duplicate_rows_collapsed"], 2)
        self.assertIn("quality_entry", review.iloc[0]["alternate_candidates"])

    def test_system_state_exposes_promotion_review_without_execution(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "promotion_decision": "paper_watch_candidate",
                        "symbol": "AMD",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "trades": 21,
                        "expectancy_r": 0.13,
                        "profit_factor": 1.6,
                        "max_drawdown_r": -2.0,
                        "positive_months": 2,
                        "months_tested": 3,
                        "largest_win_share": 0.25,
                        "promotion_reason": "Eligible for manual paper-watch review, not live trading.",
                        "trade_log": "logs/example.csv",
                    }
                ]
            ).to_csv(output_dir / "promotion_review.csv", index=False)
            (output_dir / "promotion_review.md").write_text("paper watch only", encoding="utf-8")

            state = build_system_state(output_dir=output_dir, paper_csv=output_dir / "paper.csv")

        self.assertFalse(state["safety"]["live_trading_enabled"])
        self.assertEqual(state["promotion_review"]["paper_watch_count"], 1)
        self.assertEqual(state["promotion_review"]["top_candidates"][0]["symbol"], "AMD")


class PaperGuardrailTests(unittest.TestCase):
    def sizing_args(self, freshness: str = "current_candle") -> argparse.Namespace:
        return argparse.Namespace(
            include_watch_only=False,
            freshness=freshness,
            account_size=10_000.0,
            risk_per_trade_pct=0.005,
            daily_realized_r=0.0,
            monthly_realized_r=0.0,
            max_daily_loss_r=-3.0,
            max_monthly_loss_r=-3.0,
        )

    def test_stale_signal_is_not_eligible_for_position_sizing(self) -> None:
        status, _ = risk_status(pd.Series(scanner_row(signal_freshness="earlier_today")), self.sizing_args())
        self.assertEqual(status, "not_current")

    def test_current_allowed_signal_can_be_sized_for_paper_review(self) -> None:
        status, _ = risk_status(pd.Series(scanner_row()), self.sizing_args())
        self.assertEqual(status, "size_ok")

    def test_grace_signal_can_be_sized_only_as_reduced_b_tier_paper_review(self) -> None:
        row = pd.Series(
            scanner_row(
                signal_freshness="grace_candle",
                validation_lane="B",
                fresh_plan_source="latest_grace_candle",
            )
        )

        status, reason = risk_status(row, self.sizing_args(freshness="paper_validation"))
        sized = build_sizing(pd.DataFrame([row]), self.sizing_args(freshness="paper_validation"))

        self.assertEqual(status, "size_ok")
        self.assertIn("B-tier grace", reason)
        self.assertEqual(sized.iloc[0]["sizing_status"], "size_ok")
        self.assertEqual(sized.iloc[0]["risk_per_trade_pct"], 0.001)
        self.assertEqual(sized.iloc[0]["suggested_shares"], 10)

    def test_position_sizing_blocks_current_label_from_stale_or_closed_session(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        sizing = build_sizing(scanner, self.sizing_args())
        closed_market = {"market_is_open": False, "today": "2026-05-26"}

        gated = apply_session_gate(sizing, scanner, closed_market)

        self.assertEqual(gated.iloc[0]["sizing_status"], "not_current_session")
        self.assertEqual(gated.iloc[0]["suggested_shares"], 0)

    def test_position_sizing_does_not_make_earlier_or_watch_only_rows_actionable(self) -> None:
        earlier = pd.DataFrame([scanner_row(signal_freshness="earlier_today")])
        earlier_sizing = build_sizing(earlier, self.sizing_args(freshness="all"))
        open_market = {"market_is_open": True, "today": "2026-05-26"}
        self.assertEqual(apply_session_gate(earlier_sizing, earlier, open_market).iloc[0]["sizing_status"], "not_current")

        watch_args = self.sizing_args()
        watch_args.include_watch_only = True
        watch = pd.DataFrame([scanner_row(scanner_status="blocked_watch_only")])
        watch_sizing = build_sizing(watch, watch_args)
        self.assertEqual(watch_sizing.iloc[0]["sizing_status"], "watch_only_study")

    def test_real_paper_import_requires_current_open_session(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        audit = pd.DataFrame([refresh_audit_row()])
        open_market = {"market_is_open": True, "today": "2026-05-26"}
        closed_market = {"market_is_open": False, "today": "2026-05-26"}

        self.assertTrue(paper_import_is_allowed(scanner, ["allowed"], "current_candle", open_market, audit)[0])
        self.assertFalse(paper_import_is_allowed(scanner, ["allowed"], "current_candle", closed_market, audit)[0])
        self.assertFalse(paper_import_is_allowed(scanner, ["allowed"], "all", open_market, audit)[0])
        self.assertFalse(paper_import_is_allowed(scanner, ["blocked_watch_only"], "current_candle", open_market, audit)[0])
        self.assertFalse(paper_import_is_allowed(scanner, ["allowed"], "current_candle", open_market, pd.DataFrame())[0])

    def test_position_sizing_requires_refresh_evidence_for_actionable_size(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        sizing = build_sizing(scanner, self.sizing_args())
        open_market = {"market_is_open": True, "today": "2026-05-26"}

        unaudited = apply_session_gate(sizing, scanner, open_market, pd.DataFrame())
        audited = apply_session_gate(sizing, scanner, open_market, pd.DataFrame([refresh_audit_row()]))

        self.assertEqual(unaudited.iloc[0]["sizing_status"], "not_refreshed_session")
        self.assertEqual(audited.iloc[0]["sizing_status"], "size_ok")

    def test_scanner_marks_todays_rows_non_actionable_outside_market_hours(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        before_open = datetime(2026, 5, 26, 8, 0, tzinfo=MARKET_TZ)
        during_market = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)

        self.assertEqual(scanner_freshness_frame(scanner, before_open).iloc[0]["data_status"], "outside_market_hours")
        self.assertEqual(scanner_freshness_frame(scanner, during_market).iloc[0]["data_status"], "fresh_for_today")

    def test_import_template_only_contains_open_session_current_rows(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        before_open = datetime(2026, 5, 26, 8, 0, tzinfo=MARKET_TZ)
        during_market = datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "template.csv"
            write_import_template(path, scanner, before_open)
            self.assertTrue(pd.read_csv(path).empty)
            write_import_template(path, scanner, during_market)
            self.assertEqual(len(pd.read_csv(path)), 1)

    def test_plan_and_checklist_hide_current_label_outside_open_session(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        sizing = build_sizing(scanner, self.sizing_args())
        open_market = {"market_is_open": True, "today": "2026-05-26"}
        closed_market = {"market_is_open": False, "today": "2026-05-26"}

        self.assertEqual(len(plan_candidate_table(scanner, date(2026, 5, 26), open_market)), 1)
        self.assertTrue(plan_candidate_table(scanner, date(2026, 5, 26), closed_market).empty)
        self.assertTrue(plan_candidate_table(scanner, date(2026, 5, 27), open_market).empty)
        self.assertEqual(len(checklist_candidates(scanner, sizing, open_market)), 1)
        self.assertTrue(checklist_candidates(scanner, sizing, closed_market).empty)

    def test_daily_workflow_refuses_automatic_paper_import(self) -> None:
        with self.assertRaisesRegex(ValueError, "Automatic paper import is disabled"):
            enforce_manual_paper_import(argparse.Namespace(append_current_signals=True))

    def test_daily_workflow_fetches_once_then_reuses_csv_for_setup_b_and_full_session(self) -> None:
        args = argparse.Namespace(
            symbols=["SPY", "QQQ"],
            entry_count=1200,
            exit_count=1200,
            entry_pages=1,
            exit_pages=1,
            chart_m1_count=240,
            chart_m15_count=400,
            chart_m60_count=400,
            chart_d_count=260,
            pause=5.0,
            output_dir=Path("logs"),
            data_provider="webull",
        )
        commands: list[list[str]] = []

        with patch("run_daily_workflow.run_step", side_effect=commands.append):
            refresh_data("python", args)

        self.assertNotIn("--reuse-csv", commands[0])
        self.assertIn("best_plus_market", commands[0])
        self.assertIn("--reuse-csv", commands[1])
        self.assertIn("setup_b", commands[1])
        self.assertIn("--reuse-csv", commands[2])
        self.assertIn("full_session", commands[2])
        self.assertEqual(commands[3][1], "run_repair_m30_from_lower_timeframe.py")
        self.assertIn("SPY", commands[3])
        self.assertIn("QQQ", commands[3])
        self.assertIn("--chart-m1-count", commands[0])
        self.assertIn("--chart-m15-count", commands[0])
        self.assertIn("--chart-m60-count", commands[0])
        self.assertIn("--chart-d-count", commands[0])

    def test_daily_workflow_polygon_refresh_imports_then_reuses_csv(self) -> None:
        args = argparse.Namespace(
            symbols=["SPY", "QQQ"],
            pause=0.0,
            output_dir=Path("logs"),
            data_provider="polygon",
            polygon_start_date="2026-06-01",
            polygon_end_date="2026-06-04",
            polygon_timeframes=["M5", "M30", "M60", "D"],
        )
        commands: list[list[str]] = []

        with patch("run_daily_workflow.run_step", side_effect=commands.append):
            refresh_data("python", args)

        self.assertEqual(commands[0][1], "run_polygon_watchlist.py")
        self.assertIn("--timeframes", commands[0])
        self.assertIn("M30", commands[0])
        self.assertIn("--start-date", commands[0])
        self.assertIn("2026-06-01", commands[0])
        self.assertIn("--pause", commands[0])
        self.assertIn("13.0", commands[0])
        self.assertIn("--retry-wait", commands[0])
        self.assertIn("65", commands[0])
        self.assertIn("--allow-partial", commands[0])
        self.assertEqual(commands[1][1], "run_webull_watchlist.py")
        self.assertIn("--reuse-csv", commands[1])
        self.assertIn("best_plus_market", commands[1])
        self.assertEqual(commands[2][1], "run_webull_watchlist.py")
        self.assertIn("--reuse-csv", commands[2])
        self.assertIn("setup_b", commands[2])
        self.assertEqual(commands[3][1], "run_webull_watchlist.py")
        self.assertIn("--reuse-csv", commands[3])
        self.assertIn("full_session", commands[3])

    def test_full_session_variants_remove_opening_range_gate_but_stay_regular_session(self) -> None:
        long_settings = settings_for_variant("quality_full_session")
        short_settings = settings_for_variant("setup_b_quality_full_session")

        self.assertEqual(long_settings.entry_start_time, "09:30")
        self.assertEqual(long_settings.latest_entry_time, "15:30")
        self.assertFalse(long_settings.require_above_opening_range)
        self.assertFalse(short_settings.require_above_opening_range)
        self.assertEqual(signal_column_for_variant("quality_full_session"), "quality_entry_signal")
        self.assertEqual(signal_column_for_variant("setup_b_quality_full_session"), "quality_short_signal")
        self.assertFalse(use_baseline_candidate_metrics("quality_full_session"))
        self.assertTrue(is_setup_b_short_variant("setup_b_quality_full_session"))

    def test_focused_scanner_filters_playbook_to_refreshed_symbols(self) -> None:
        entries = playbook_entries_for_scan("approved_plus_watch", ["NVDA", "QQQ", "AAPL", "TSLA", "AMD"])
        symbols = {entry.symbol for entry in entries}
        setup_names = {entry.setup_name for entry in entries}

        self.assertIn("Setup C Full-Session Long", setup_names)
        self.assertIn("Setup C Full-Session Short", setup_names)
        self.assertNotIn("META", symbols)
        self.assertNotIn("MSFT", symbols)

    def test_daily_workflow_provider_acceptance_command_checks_core_intraday_streams(self) -> None:
        args = argparse.Namespace(
            symbols=["AAPL", "SPY", "QQQ"],
            output_dir=Path("logs"),
            data_provider="polygon",
            skip_provider_acceptance=False,
        )

        command = provider_acceptance_command("python", args)

        self.assertEqual(command[1], "run_provider_acceptance.py")
        self.assertIn("--provider", command)
        self.assertIn("polygon", command)
        self.assertIn("--symbols", command)
        self.assertIn("SPY", command)
        self.assertIn("QQQ", command)
        self.assertIn("--timeframes", command)
        self.assertIn("M5", command)
        self.assertIn("M30", command)

    def test_accelerated_validation_uses_webull_without_confirming_entries(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            pause=5.0,
            account_size=10_000.0,
            risk_per_trade_pct=0.005,
            auto_confirm_paper_exits=False,
        )

        command = accelerated_workflow_command(args, python="python")

        self.assertEqual(command[:2], ["python", "run_current_candle_capture.py"])
        self.assertIn("--symbols", command)
        self.assertIn("NVDA", command)
        self.assertIn("QQQ", command)
        self.assertIn("AAPL", command)
        self.assertNotIn("--data-provider", command)
        self.assertNotIn("--confirm-local-paper", command)
        self.assertNotIn("--append-current-signals", command)
        self.assertNotIn("--auto-confirm-paper-exits", command)

    def test_current_candle_capture_runs_only_fast_gate_path(self) -> None:
        args = argparse.Namespace(
            output_dir=Path("logs"),
            symbols=["SPY", "QQQ"],
            skip_refresh=False,
            entry_count=1200,
            exit_count=1200,
            entry_pages=1,
            exit_pages=1,
            chart_m1_count=240,
            chart_m15_count=400,
            chart_m60_count=400,
            chart_d_count=260,
            pause=5.0,
            account_size=10_000.0,
            risk_per_trade_pct=0.005,
            auto_confirm_paper_exits=False,
        )

        commands = build_current_candle_capture_commands(args, python="python")
        steps = [step for step, _ in commands]
        flat = " ".join(" ".join(command) for _, command in commands)

        self.assertEqual(steps[0], "Refresh Webull best/market setups")
        self.assertIn("Scanner", steps)
        self.assertLess(steps.index("Scanner"), steps.index("Position Sizing"))
        self.assertLess(steps.index("Position Sizing"), steps.index("Market Regime Router"))
        self.assertLess(steps.index("Market Regime Router"), steps.index("Pre-Entry Review"))
        self.assertLess(steps.index("Pre-Entry Review"), steps.index("Paper Gate v2"))
        self.assertLess(steps.index("Paper Gate v2"), steps.index("Candidate-Window Ledger + Event Dispatch"))
        self.assertLess(steps.index("Candidate-Window Ledger + Event Dispatch"), steps.index("Validation Import Preview"))
        self.assertLess(steps.index("Validation Import Preview"), steps.index("Daily Ship Report"))
        self.assertLess(steps.index("Daily Ship Report"), steps.index("Historical Bucket Sync"))
        self.assertLess(steps.index("Historical Bucket Sync"), steps.index("Opening Range Breakout Shadow Evidence"))
        self.assertLess(
            steps.index("Opening Range Breakout Shadow Evidence"),
            steps.index("Opening Range Breakout Forward Evidence"),
        )
        self.assertLess(
            steps.index("Opening Range Breakout Forward Evidence"),
            steps.index("Opening Range Breakout Paper-Watch Gate"),
        )
        self.assertLess(steps.index("Opening Range Breakout Paper-Watch Gate"), steps.index("Refresh Status"))
        self.assertIn("run_candidate_window_ledger.py", flat)
        self.assertNotIn("run_option_chain_import.py", flat)
        self.assertNotIn("run_options_chain_review.py", flat)
        self.assertNotIn("run_options_contract_gate.py", flat)
        self.assertIn("run_opening_range_breakout_shadow_samples.py", flat)
        self.assertIn("run_opening_range_breakout_forward_observations.py", flat)
        self.assertIn("run_opening_range_breakout_paper_watch_gate.py", flat)
        self.assertIn("--record-latest-snapshot", flat)
        self.assertIn("run_filter_rejection_report.py", flat)
        self.assertIn("run_daily_ship_report.py", flat)
        self.assertIn("run_historical_bucket_sync.py", flat)
        self.assertIn("run_data_flow_sentinel.py", flat)
        self.assertNotIn("run_daily_workflow.py", flat)
        self.assertNotIn("run_paper_import.py", flat)
        self.assertNotIn("--confirm-samples", flat)
        self.assertNotIn("--confirm-local-paper", flat)

    def test_current_candle_capture_summarizes_orb_shadow_only_trigger_distance(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "opening_range_breakout_paper_watch_gate.json").write_text(
                json.dumps(
                    {
                        "decision": "not_ready",
                        "blocked_count": 4,
                        "next_blocker": "Shadow samples logged",
                        "checks": [
                            {"check": "Shadow samples logged", "status": "blocked", "current": 4, "required": 10},
                            {"check": "Matured shadow outcomes", "status": "blocked", "current": 1, "required": 5},
                            {"check": "Forward observations logged", "status": "blocked", "current": 6, "required": 10},
                            {"check": "Matured forward outcomes", "status": "blocked", "current": 2, "required": 5},
                        ],
                        "guardrail": (
                            "Manual paper-watch review only. No broker orders, no alerts, no live execution."
                        ),
                    }
                ),
                encoding="utf-8",
            )

            payload = current_candle_capture_count_summary(output_dir)

        self.assertEqual(payload["orb_collection_mode"], "shadow_only")
        self.assertEqual(payload["orb_shadow_samples"], 4)
        self.assertEqual(payload["orb_shadow_samples_remaining"], 6)
        self.assertEqual(payload["orb_forward_observations"], 6)
        self.assertEqual(payload["orb_forward_observations_remaining"], 4)
        self.assertIn("No broker orders", payload["orb_guardrail"])

    def test_current_candle_capture_summary_identifies_earlier_today_bottleneck(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "scanner_status": "allowed",
                        "signal_freshness": "earlier_today",
                    }
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "sizing_status": "not_current",
                    }
                ]
            ).to_csv(output_dir / "position_sizing.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "candidate_route": "stale_or_earlier_today",
                    }
                ]
            ).to_csv(output_dir / "market_regime_router_candidates.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "review_status": "blocked",
                    }
                ]
            ).to_csv(output_dir / "pre_entry_review.csv", index=False)
            (output_dir / "paper_gate_v2.json").write_text(json.dumps({"status": "waiting", "ready_sample_count": 0}))
            (output_dir / "options_contract_gate.json").write_text(
                json.dumps({"status": "waiting_for_chart_candidate", "passed_contract_count": 0})
            )
            (output_dir / "paper_validation_sample_import.json").write_text(json.dumps({"mode": "preview", "new_rows": 0}))

            payload = current_candle_capture_count_summary(output_dir)

        self.assertEqual(payload["scanner_rows"], 1)
        self.assertEqual(payload["scanner_current_allowed"], 0)
        self.assertEqual(payload["scanner_grace_allowed"], 0)
        self.assertEqual(payload["scanner_paper_validation_allowed"], 0)
        self.assertEqual(payload["scanner_earlier_today_allowed"], 1)
        self.assertEqual(payload["first_bottleneck"], "scanner_paper_validation_allowed")
        self.assertIn("earlier today", payload["bottleneck_reason"])

    def test_daily_ship_report_surfaces_pipeline_drops_and_completed_gate_progress(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            samples_csv = output_dir / "paper_validation_samples.csv"
            pd.DataFrame(
                [
                    scanner_row(symbol="SPY", scanner_status="allowed"),
                    scanner_row(symbol="QQQ", scanner_status="allowed"),
                    scanner_row(symbol="AAPL", scanner_status="not_ready"),
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            pd.DataFrame(
                [
                    {"symbol": "SPY", "setup": "Setup A Long", "direction": "long", "sizing_status": "size_ok"},
                    {"symbol": "QQQ", "setup": "Setup A Long", "direction": "long", "sizing_status": "not_current"},
                    {"symbol": "AAPL", "setup": "Setup A Long", "direction": "long", "sizing_status": "not_allowed"},
                ]
            ).to_csv(output_dir / "position_sizing.csv", index=False)
            pd.DataFrame(
                [
                    {"symbol": "SPY", "setup": "Setup A Long", "direction": "long", "review_status": "ready_for_manual_review"}
                ]
            ).to_csv(output_dir / "pre_entry_review.csv", index=False)
            (output_dir / "paper_gate_v2.json").write_text(
                json.dumps({"status": "ready", "ready_sample_count": 1}),
                encoding="utf-8",
            )
            (output_dir / "options_contract_gate.json").write_text(
                json.dumps({"status": "ready", "passed_contract_count": 1}),
                encoding="utf-8",
            )
            (output_dir / "paper_validation_sample_import.json").write_text(
                json.dumps({"mode": "preview", "new_rows": 1}),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {"sample_tier": "A", "counts_toward_30": True, "outcome_r": "1.25"},
                    {"sample_tier": "B", "counts_toward_30": True, "outcome_r": ""},
                    {"sample_tier": "C", "counts_toward_30": False, "outcome_r": "2.00"},
                ]
            ).to_csv(samples_csv, index=False)

            payload = build_ship_report(output_dir, samples_csv)

        rows = {row["stage"]: row for row in payload["funnel_rows"]}
        self.assertEqual(rows["Scanner signals"]["count"], 3)
        self.assertEqual(rows["Allowed signals"]["count"], 2)
        self.assertEqual(rows["Allowed signals"]["drop_pct"], "33.3%")
        self.assertEqual(rows["Size-ok signals"]["count"], 1)
        self.assertEqual(rows["Review-ready signals"]["count"], 1)
        self.assertEqual(rows["Paper Gate A/B signals"]["count"], 1)
        self.assertEqual(rows["Contract-passed signals"]["count"], 1)
        self.assertEqual(rows["Validation-imported signals"]["count"], 1)
        self.assertEqual(payload["official_validation_samples"], 2)
        self.assertEqual(payload["completed_official_paper_trades"], 1)
        self.assertEqual(payload["remaining_to_30"], 29)

    def test_paper_trade_command_center_prefers_official_validation_ledger(self) -> None:
        samples = pd.DataFrame(
            [
                {"sample_tier": "A", "counts_toward_30": True, "outcome_r": "1.00"},
                {"sample_tier": "B", "counts_toward_30": True, "outcome_r": "-0.50"},
                {"sample_tier": "A", "counts_toward_30": True, "outcome_r": ""},
                {"sample_tier": "C", "counts_toward_30": False, "outcome_r": "2.00"},
            ]
        )
        payload = paper_trade_command_center_state(
            current_candidates={"count": 3, "ready_for_review_count": 1, "cards": [{"symbol": "SPY"}]},
            paper_progress={"allowed_completed_trades": 9, "allowed_average_r": 0.99},
            paper_validation_samples=samples,
            daily_ship_report={
                "first_bottleneck": "Contract-passed signals",
                "worst_drop": "Contract-passed signals (100.0% drop from previous stage)",
                "funnel_rows": [{"stage": "Scanner signals", "count": 10, "scope": "current_run"}],
            },
            market_regime_router={"regime": {"market_regime": "bullish_trend", "confidence": "medium_high"}},
        )

        self.assertEqual(payload["completed_official_paper_trades"], 2)
        self.assertEqual(payload["official_validation_samples"], 3)
        self.assertEqual(payload["open_official_paper_trades"], 1)
        self.assertEqual(payload["remaining_to_30"], 28)
        self.assertEqual(payload["win_rate_pct"], 50.0)
        self.assertEqual(payload["average_r"], 0.25)
        self.assertEqual(payload["current_bottleneck"], "Contract-passed signals")
        self.assertEqual(payload["market_regime"], "bullish_trend")

    def test_accelerated_validation_ranks_healthier_ready_rows_first(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "queue_status": "ready_for_review",
                        "priority": 1,
                        "symbol": "AAPL",
                        "setup": "Setup B Short",
                        "direction": "short",
                        "quality_grade": "B",
                        "quality_score": 7,
                        "room_to_target_r": -0.2,
                        "check_score": 1.0,
                        "shares": 3,
                        "estimated_risk_dollars": 43.17,
                        "next_action": "Review checklist.",
                        "blockers": "",
                    },
                    {
                        "queue_status": "ready_for_review",
                        "priority": 1,
                        "symbol": "NVDA",
                        "setup": "Setup B Short",
                        "direction": "short",
                        "quality_grade": "B",
                        "quality_score": 8,
                        "room_to_target_r": 1.2,
                        "check_score": 1.0,
                        "shares": 23,
                        "estimated_risk_dollars": 48.96,
                        "next_action": "Review checklist.",
                        "blockers": "",
                    },
                    {
                        "queue_status": "almost_ready",
                        "priority": 3,
                        "symbol": "QQQ",
                        "setup": "Setup B Short",
                        "direction": "short",
                        "quality_grade": "B",
                        "quality_score": 8,
                        "room_to_target_r": 2.5,
                        "check_score": 0.8889,
                        "shares": 0,
                        "estimated_risk_dollars": 0,
                        "next_action": "Watch next scan.",
                        "blockers": "not current",
                    },
                ]
            ).to_csv(output_dir / "forward_sample_queue.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "AAPL",
                        "setup": "Setup B Short",
                        "health_status": "caution",
                        "health_score": 45,
                        "expectancy_r": -0.0129,
                        "profit_factor": 0.9454,
                        "flags": "negative or flat expectancy",
                    },
                    {
                        "symbol": "NVDA",
                        "setup": "Setup B Short",
                        "health_status": "watch",
                        "health_score": 90,
                        "expectancy_r": 0.2272,
                        "profit_factor": 1.9672,
                        "flags": "sample still developing",
                    },
                    {
                        "symbol": "QQQ",
                        "setup": "Setup B Short",
                        "health_status": "watch",
                        "health_score": 90,
                        "expectancy_r": 0.2821,
                        "profit_factor": 3.2213,
                        "flags": "sample still developing",
                    },
                ]
            ).to_csv(output_dir / "setup_health.csv", index=False)
            pd.DataFrame(
                [
                    {"scanner_status": "allowed", "signal_freshness": "current_candle"},
                    {"scanner_status": "allowed", "signal_freshness": "current_candle"},
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            (output_dir / "refresh_status.json").write_text(
                json.dumps(
                    {
                        "provider_refresh": {"provider": "webull", "status": "current_session_bars"},
                        "scanner": {"latest_scanner_session": "2026-06-09"},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_report_payload(output_dir)

        ready = payload["ready"]
        almost = payload["almost"]
        self.assertEqual(payload["provider"], "webull")
        self.assertEqual(payload["current_candidates"], 2)
        self.assertEqual(list(ready["symbol"]), ["NVDA", "AAPL"])
        self.assertEqual(payload["review_first"], 1)
        self.assertEqual(payload["caution_ready"], 1)
        self.assertEqual(payload["review_first_rows"].iloc[0]["symbol"], "NVDA")
        self.assertEqual(payload["caution_ready_rows"].iloc[0]["symbol"], "AAPL")
        self.assertEqual(list(almost["symbol"]), ["QQQ"])

    def test_daily_workflow_research_snapshot_rebuilds_promotion_gate(self) -> None:
        commands = research_snapshot_commands("python", Path("logs"))

        self.assertEqual(commands[0], ["python", "run_research_confidence.py", "--output-dir", "logs/universe_expansion"])
        self.assertEqual(
            commands[1],
            [
                "python",
                "run_promotion_review.py",
                "--output-dir",
                "logs",
                "--research-dir",
                "logs/universe_expansion",
            ],
        )

    def test_chart_only_fetches_do_not_replace_strategy_timeframes(self) -> None:
        args = argparse.Namespace(
            chart_m1_count=10,
            chart_m1_pages=1,
            chart_m15_count=20,
            chart_m15_pages=1,
            chart_m60_count=30,
            chart_m60_pages=1,
            chart_d_count=40,
            chart_d_pages=1,
            pause=0,
        )
        calls: list[tuple[str, int]] = []

        def fake_fetch(data_client, symbol, timespan, count, pages, pause_seconds, output_dir):
            calls.append((timespan, count))
            return output_dir / f"webull_{symbol}_{timespan}_candles.csv"

        with TemporaryDirectory() as temporary, patch("run_webull_watchlist.fetch_and_save", side_effect=fake_fetch):
            fetch_chart_only_timeframes(object(), "SPY", args, Path(temporary))

        self.assertEqual(calls, [("M1", 10), ("M15", 20), ("M60", 30), ("D", 40)])

    def test_position_sizing_derives_allowed_realized_loss_stops_from_paper_log(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "paper.csv"
            pd.DataFrame(
                [
                    {"trade_date": "2026-05-26", "signal_status": "allowed", "outcome_r": -2.0},
                    {"trade_date": "2026-05-26", "signal_status": "allowed", "outcome_r": -1.25},
                    {"trade_date": "2026-05-26", "signal_status": "blocked", "outcome_r": 5.0},
                    {"trade_date": "2026-05-01", "signal_status": "allowed", "outcome_r": 0.5},
                ]
            ).to_csv(path, index=False)
            now = datetime(2026, 5, 26, 11, 0, tzinfo=MARKET_TZ)

            daily, monthly = realized_r_from_paper_log(path, now)

        self.assertEqual(daily, -3.25)
        self.assertEqual(monthly, -2.75)

    def test_local_paper_execution_only_uses_size_ok_current_allowed_rows(self) -> None:
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "scanner_status": "allowed",
                    "signal_freshness": "current_candle",
                    "latest_signal_et": "2026-05-26 10:30",
                    "planned_entry": 100.0,
                    "planned_stop": 99.0,
                    "planned_target": 102.0,
                    "suggested_shares": 50,
                    "scale_tier": "strong",
                    "sizing_status": "size_ok",
                },
                {
                    "symbol": "NVDA",
                    "setup": "Setup B Short",
                    "direction": "short",
                    "scanner_status": "blocked_watch_only",
                    "signal_freshness": "current_candle",
                    "latest_signal_et": "2026-05-26 10:30",
                    "planned_entry": 200.0,
                    "planned_stop": 202.0,
                    "planned_target": 196.0,
                    "suggested_shares": 25,
                    "sizing_status": "watch_only",
                },
                {
                    "symbol": "QQQ",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "scanner_status": "allowed",
                    "signal_freshness": "earlier_today",
                    "latest_signal_et": "2026-05-26 10:00",
                    "planned_entry": 400.0,
                    "planned_stop": 399.0,
                    "planned_target": 402.0,
                    "suggested_shares": 50,
                    "sizing_status": "size_ok",
                },
                {
                    "symbol": "AMD",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "scanner_status": "allowed",
                    "signal_freshness": "grace_candle",
                    "latest_signal_et": "2026-05-26 10:30",
                    "candidate_entry_et": "2026-05-26 11:00",
                    "validation_lane": "B",
                    "planned_entry": 150.0,
                    "planned_stop": 149.0,
                    "planned_target": 152.0,
                    "suggested_shares": 10,
                    "sizing_status": "size_ok",
                },
            ]
        )

        eligible = eligible_sizing_rows(sizing)
        orders = build_local_paper_orders(eligible)
        trades = orders_to_open_paper_trades(orders)

        self.assertEqual(len(eligible), 1)
        self.assertEqual(orders.iloc[0]["symbol"], "SPY")
        self.assertEqual(orders.iloc[0]["status"], "local_paper_filled")
        self.assertEqual(orders.iloc[0]["vehicle"], "options")
        self.assertEqual(orders.iloc[0]["risk_tier"], "strong")
        self.assertEqual(trades.iloc[0]["actual_entry"], 100.0)
        self.assertEqual(trades.iloc[0]["vehicle"], "options")
        self.assertEqual(trades.iloc[0]["risk_tier"], "strong")
        self.assertIn("planned_option_premium", trades.columns)
        self.assertEqual(trades.iloc[0]["outcome_r"], "")

    def test_candidate_alert_requires_allowed_current_size_ok_open_session(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(symbol="SPY"),
                scanner_row(
                    symbol="NVDA",
                    setup="Setup B Short",
                    direction="short",
                    scanner_status="blocked_watch_only",
                    planned_entry=200.0,
                    planned_stop=202.0,
                ),
                scanner_row(symbol="QQQ", signal_freshness="earlier_today"),
            ]
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "suggested_shares": 50,
                    "estimated_risk_dollars": 50.0,
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for paper sizing.",
                },
                {
                    "symbol": "NVDA",
                    "setup": "Setup B Short",
                    "direction": "short",
                    "suggested_shares": 0,
                    "estimated_risk_dollars": 0.0,
                    "sizing_status": "watch_only",
                    "sizing_reason": "Blocked by research filter.",
                },
                {
                    "symbol": "QQQ",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "suggested_shares": 50,
                    "estimated_risk_dollars": 50.0,
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for paper sizing.",
                },
            ]
        )
        market = {"market_is_open": True, "today": "2026-05-26"}

        alerts = build_alert_rows(scanner, sizing, market)

        self.assertEqual(len(alerts), 2)
        ready = alerts[alerts["alert_status"] == "paper_review_ready"]
        blocked = alerts[alerts["alert_status"] != "paper_review_ready"]
        self.assertEqual(ready.iloc[0]["symbol"], "SPY")
        self.assertEqual(blocked.iloc[0]["symbol"], "NVDA")
        self.assertIn("scanner status is not allowed", blocked.iloc[0]["blockers"])

    def test_open_paper_monitor_previews_and_applies_target_exit(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "logs"
            data_dir.mkdir()
            paper = pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-26",
                        "entry_time_et": "10:00",
                        "exit_time_et": "",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_status": "allowed",
                        "planned_entry": 100.0,
                        "planned_stop": 99.0,
                        "planned_target": 102.0,
                        "actual_entry": 100.0,
                        "actual_exit": "",
                        "shares": 50,
                        "outcome_r": "",
                        "followed_plan": "",
                        "exit_reason": "",
                        "notes": "test open paper trade",
                    }
                ]
            )
            pd.DataFrame(
                [
                    {"datetime": "2026-05-26T14:00:00Z", "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1000},
                    {"datetime": "2026-05-26T14:05:00Z", "open": 100.1, "high": 102.2, "low": 100.0, "close": 102.0, "volume": 1200},
                ]
            ).to_csv(data_dir / "webull_SPY_M5_candles.csv", index=False)

            updates = build_updates(paper, data_dir)
            updated = apply_updates(paper, updates)
            audit = build_audit(updated, data_dir)

        self.assertEqual(updates.iloc[0]["monitor_status"], "exit_ready")
        self.assertEqual(updates.iloc[0]["exit_reason"], "profit_target_5m")
        self.assertEqual(updates.iloc[0]["outcome_r"], 2.0)
        self.assertEqual(updated.iloc[0]["actual_exit"], 102.0)
        self.assertEqual(updated.iloc[0]["followed_plan"], "yes")
        self.assertEqual(audit.iloc[0]["audit_status"], "matched")
        self.assertEqual(audit.iloc[0]["expected_exit_reason"], "profit_target_5m")

    def test_paper_session_cycle_requires_explicit_confirm_flags(self) -> None:
        preview_commands = build_paper_session_commands(Path("logs"), python="python")
        confirm_commands = build_paper_session_commands(
            Path("logs"),
            confirm_local_paper=True,
            confirm_exits=True,
            python="python",
        )

        preview_flat = [part for _, command in preview_commands for part in command]
        confirm_flat = [part for _, command in confirm_commands for part in command]

        self.assertNotIn("--confirm-local-paper", preview_flat)
        self.assertNotIn("--confirm-updates", preview_flat)
        self.assertIn("--confirm-local-paper", confirm_flat)
        self.assertIn("--confirm-updates", confirm_flat)
        self.assertEqual(
            [step for step, _ in preview_commands][:11],
            [
                "Candidate alerts",
                "Pre-entry review",
                "Paper entry packet",
                "Paper Gate v2",
                "Options Contract Gate",
                "Validation sample import preview",
                "Daily ship report",
                "Filter rejection report",
                "Local paper execution",
                "Open paper monitor",
                "Exit audit",
            ],
        )
        self.assertEqual(preview_commands[11][0], "Paper review")
        self.assertEqual(preview_commands[12][0], "Forward sample queue")
        self.assertEqual(preview_commands[13][0], "No-trade analysis")
        self.assertEqual(preview_commands[14][0], "Shadow samples")
        self.assertEqual(preview_commands[15][0], "Candidate aging")
        self.assertEqual(preview_commands[16][0], "Forward evidence")
        command_by_step = {step: command for step, command in confirm_commands}
        self.assertIn("--confirm-local-paper", command_by_step["Local paper execution"])
        self.assertIn("--confirm-updates", command_by_step["Open paper monitor"])
        self.assertNotIn("--confirm-local-paper", command_by_step["Paper Gate v2"])
        self.assertNotIn("--confirm-updates", command_by_step["Options Contract Gate"])

    def test_paper_entry_packet_packages_ready_pre_entry_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "pre_entry_review.json").write_text(
                json.dumps(
                    {
                        "ready_for_manual_review": 1,
                        "blocked_candidates": 0,
                        "rows": [
                            {
                                "symbol": "SPY",
                                "setup": "Setup A Long",
                                "direction": "long",
                                "signal_time_et": "2026-05-26 10:30",
                                "signal_freshness": "current_candle",
                                "validation_lane": "A",
                                "suggested_shares": 5,
                                "risk_guard_status": "active",
                                "router_route": "review_first",
                                "review_status": "ready_for_manual_review",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "market": {"market_is_open": True},
                        "data_freshness": {"data_status": "fresh_for_today"},
                        "data_flow_sentinel": {"status": "synced"},
                        "provider_stability_audit": {"status": "stable"},
                        "readiness_verdict": "Review the checklist.",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "market": {"market_is_open": True},
                        "data_freshness": {"data_status": "fresh_for_today"},
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "market": {"market_is_open": True},
                        "data_freshness": {"data_status": "fresh_for_today"},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_paper_entry_packets(output_dir)

        self.assertEqual(payload["ready_packet_count"], 1)
        self.assertEqual(payload["packets"][0]["symbol"], "SPY")
        self.assertEqual(payload["packets"][0]["validation_lane"], "A")
        self.assertIn("--confirm-local-paper", payload["packets"][0]["paper_confirm_command"])
        self.assertIn("Preview first", payload["packets"][0]["notes"])
        self.assertTrue(payload["actionable_session"])

    def test_paper_entry_packet_excludes_b_tier_grace_from_local_entry_commands(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "pre_entry_review.json").write_text(
                json.dumps(
                    {
                        "ready_for_manual_review": 1,
                        "blocked_candidates": 0,
                        "rows": [
                            {
                                "symbol": "SPY",
                                "setup": "Setup A Long",
                                "direction": "long",
                                "signal_time_et": "2026-05-26 10:30",
                                "signal_freshness": "grace_candle",
                                "validation_lane": "B",
                                "suggested_shares": 2,
                                "risk_guard_status": "active",
                                "router_route": "caution_review",
                                "review_status": "ready_for_manual_review",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "market": {"market_is_open": True},
                        "data_freshness": {"data_status": "fresh_for_today"},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_paper_entry_packets(output_dir)

        self.assertEqual(payload["ready_packet_count"], 0)
        self.assertEqual(payload["b_tier_manual_only_count"], 1)
        self.assertEqual(payload["packets"], [])
        self.assertIn("B-tier grace", payload["next_action"])

    def test_paper_entry_packet_stays_empty_for_blocked_candidates(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "pre_entry_review.json").write_text(
                json.dumps(
                    {
                        "ready_for_manual_review": 0,
                        "blocked_candidates": 1,
                        "rows": [
                            {
                                "symbol": "SPY",
                                "setup": "Setup A Long",
                                "direction": "long",
                                "review_status": "blocked",
                                "blockers": "Paper import gate is still blocked.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "market": {"market_is_open": True},
                        "data_freshness": {"data_status": "fresh_for_today"},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_paper_entry_packets(output_dir)

        self.assertEqual(payload["ready_packet_count"], 0)
        self.assertEqual(payload["blocked_candidate_count"], 1)
        self.assertEqual(payload["packets"], [])
        self.assertIn("do not log", payload["next_action"].lower())

    def test_paper_entry_packet_blocks_ready_rows_outside_actionable_session(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            (output_dir / "pre_entry_review.json").write_text(
                json.dumps(
                    {
                        "ready_for_manual_review": 1,
                        "blocked_candidates": 0,
                        "rows": [
                            {
                                "symbol": "SPY",
                                "setup": "Setup A Long",
                                "direction": "long",
                                "review_status": "ready_for_manual_review",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "market": {"market_is_open": False},
                        "data_freshness": {
                            "data_status": "outside_market_hours",
                            "action": "Run during the next open session.",
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_paper_entry_packets(output_dir)

        self.assertEqual(payload["ready_packet_count"], 0)
        self.assertFalse(payload["actionable_session"])
        self.assertIn("next open session", payload["next_action"])

    def test_forward_sample_queue_ranks_ready_and_almost_ready_rows(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(symbol="SPY", passed_condition_count=9, condition_count=10),
                scanner_row(
                    symbol="QQQ",
                    scanner_status="not_ready",
                    signal_freshness="",
                    latest_signal_et="",
                    passed_condition_count=7,
                    condition_count=10,
                    block_reason="Needs opening range break.",
                ),
            ]
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for paper sizing.",
                    "suggested_shares": 50,
                    "estimated_risk_dollars": 50,
                },
                {
                    "symbol": "QQQ",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "sizing_status": "not_allowed",
                    "sizing_reason": "Scanner did not mark this setup as allowed.",
                    "suggested_shares": 0,
                    "estimated_risk_dollars": 0,
                },
            ]
        )
        market = {"market_is_open": True, "today": "2026-05-26"}

        queue = build_forward_sample_queue(scanner, sizing, market)
        payload = forward_sample_queue_payload(queue, pd.DataFrame(), pd.DataFrame())

        self.assertEqual(queue.iloc[0]["queue_status"], "ready_for_review")
        self.assertEqual(queue.iloc[1]["queue_status"], "almost_ready")
        self.assertEqual(payload["summary"]["ready_for_review"], 1)
        self.assertEqual(payload["summary"]["almost_ready"], 1)
        self.assertIn("read-only", payload["guardrail"].lower())

    def test_pre_entry_review_blocks_watch_only_candidates(self) -> None:
        scanner = pd.Series(
            {
                "symbol": "SPY",
                "setup": "Setup A Long",
                "direction": "long",
                "latest_signal_et": "2026-05-26 10:30",
                "scanner_status": "blocked_watch_only",
                "signal_freshness": "current_candle",
                "planned_entry": 100.0,
                "planned_stop": 99.0,
                "planned_target": 102.0,
            }
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "sizing_status": "size_ok",
                    "suggested_shares": 10,
                }
            ]
        )

        row = pre_entry_review_row(
            scanner,
            sizing,
            data_fresh=True,
            import_allowed=True,
            import_reason="eligible",
            selector={"mode": "paper_watch_allowed"},
            risk_guard={"status": "pre_validation"},
        )

        self.assertEqual(row["review_status"], "blocked")
        self.assertIn("Scanner did not mark this candidate allowed.", row["blockers"])

    def test_pre_entry_review_blocks_router_caution_candidates(self) -> None:
        scanner = pd.Series(
            {
                "symbol": "QQQ",
                "setup": "Setup C Full-Session Short",
                "direction": "short",
                "variant": "setup_b_quality_full_session",
                "exit_profile": "no_vwap_exit",
                "latest_signal_et": "2026-05-26 15:30",
                "scanner_status": "allowed",
                "signal_freshness": "current_candle",
                "planned_entry": 100.0,
                "planned_stop": 101.0,
                "planned_target": 98.0,
            }
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "setup": "Setup C Full-Session Short",
                    "direction": "short",
                    "sizing_status": "size_ok",
                    "suggested_shares": 10,
                }
            ]
        )

        row = pre_entry_review_row(
            scanner,
            sizing,
            data_fresh=True,
            import_allowed=True,
            import_reason="eligible",
            selector={"mode": "paper_watch_allowed"},
            risk_guard={"status": "pre_validation"},
            router_row={"candidate_route": "caution_review", "action": "Late-day caution."},
        )

        self.assertEqual(row["review_status"], "blocked")
        self.assertEqual(row["router_route"], "caution_review")
        self.assertIn("Market regime router says caution_review", row["blockers"])

    def test_pre_entry_review_allows_grace_lane_manual_caution_review(self) -> None:
        scanner = pd.Series(
            {
                "symbol": "SPY",
                "setup": "Setup A Long",
                "direction": "long",
                "variant": "current",
                "exit_profile": "no_vwap_exit",
                "latest_signal_et": "2026-05-26 10:30",
                "source_signal_et": "2026-05-26 10:30",
                "candidate_entry_et": "2026-05-26 11:00",
                "scanner_status": "allowed",
                "signal_freshness": "grace_candle",
                "validation_lane": "B",
                "planned_entry": 100.0,
                "planned_stop": 99.0,
                "planned_target": 102.0,
            }
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "sizing_status": "size_ok",
                    "suggested_shares": 10,
                }
            ]
        )

        row = pre_entry_review_row(
            scanner,
            sizing,
            data_fresh=True,
            import_allowed=False,
            import_reason="legacy import is A-only",
            selector={"mode": "paper_watch_allowed"},
            risk_guard={"status": "pre_validation"},
            router_row={"candidate_route": "caution_review", "action": "Manual B-tier grace review only."},
        )

        self.assertEqual(row["review_status"], "ready_for_manual_review")
        self.assertEqual(row["signal_freshness"], "grace_candle")
        self.assertEqual(row["validation_lane"], "B")
        self.assertEqual(row["candidate_entry_et"], "2026-05-26 11:00")

    def test_forward_evidence_keeps_shadow_samples_out_of_official_gate(self) -> None:
        paper_review = pd.DataFrame(
            [
                {"signal_status": "allowed", "review_r": 1.2},
                {"signal_status": "blocked", "review_r": -0.5},
            ]
        )
        observations = pd.DataFrame(
            [
                {"signal_status": "allowed"},
                {"signal_status": "blocked"},
            ]
        )
        observation_results = pd.DataFrame(
            [
                {"signal_status": "allowed", "evaluation_status": "matured", "hypothetical_r": 0.8},
                {"signal_status": "blocked", "evaluation_status": "matured", "hypothetical_r": -1.0},
            ]
        )
        shadow_samples = pd.DataFrame(
            [
                {"shadow_status": "one_rule_miss"},
                {"shadow_status": "close_watch_shadow"},
            ]
        )
        shadow_outcomes = pd.DataFrame(
            [
                {"evaluation_status": "matured", "hypothetical_r": 2.0},
            ]
        )
        queue = pd.DataFrame([{"queue_status": "almost_ready"}])

        evidence = build_forward_evidence(
            paper_review,
            observations,
            observation_results,
            shadow_samples,
            shadow_outcomes,
            queue,
        )

        self.assertEqual(evidence["paper"]["allowed_completed_trades"], 1)
        self.assertEqual(evidence["paper"]["remaining_to_30"], 29)
        self.assertEqual(evidence["shadow"]["shadow_samples_logged"], 2)
        self.assertEqual(evidence["shadow"]["matured_shadow_outcomes"], 1)
        self.assertEqual(evidence["total_learning_rows"], 6)
        self.assertIn("almost-ready", evidence["next_action"])

    def test_candidate_aging_flags_negative_late_day_outcomes(self) -> None:
        aging = build_candidate_aging(
            scanner=pd.DataFrame(),
            observations=pd.DataFrame(
                [
                    {
                        "signal_time_et": "2026-05-28 10:00",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_status": "allowed",
                        "hypothetical_r": 0.5,
                        "evaluation_status": "matured",
                    },
                    {
                        "signal_time_et": "2026-05-28 15:00",
                        "symbol": "TSLA",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_status": "allowed",
                        "hypothetical_r": -0.4,
                        "evaluation_status": "matured",
                    },
                ]
            ),
            shadow=pd.DataFrame(
                [
                    {
                        "entry_time_et": "2026-05-29 15:00",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "shadow_status": "one_rule_miss",
                        "hypothetical_r": -0.1,
                        "evaluation_status": "matured",
                    }
                ]
            ),
            paper=pd.DataFrame(),
        )
        summary = candidate_aging_bucket_summary(aging)
        late = summary[summary["age_bucket"] == "late_day"].iloc[0]

        self.assertEqual(late["outcomes"], 2)
        self.assertLess(late["avg_r"], 0)
        self.assertIn("Caution", late["guidance"])

    def test_no_trade_analysis_identifies_single_rule_relaxation(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    scanner_status="not_ready",
                    symbol="SPY",
                    setup="Setup A Long",
                    direction="long",
                    missing_conditions="above opening range high",
                    passed_condition_count=8,
                    condition_count=9,
                    quality_score=7,
                    quality_grade="B",
                ),
                scanner_row(
                    scanner_status="not_ready",
                    symbol="TSLA",
                    setup="Setup B Short",
                    direction="short",
                    missing_conditions="price below 200 EMA; 1H bearish thesis",
                    passed_condition_count=7,
                    condition_count=9,
                    quality_score=5,
                    quality_grade="C",
                ),
            ]
        )

        analysis = build_no_trade_analysis(scanner)
        impact = analysis["single_relaxation_impact"]
        closest = analysis["closest_setups"]

        self.assertIn("one rule away", analysis["verdict"])
        self.assertEqual(impact.iloc[0]["relaxing_this_rule"], "above opening range high")
        self.assertEqual(impact.iloc[0]["possible_new_candidates"], 1)
        self.assertEqual(closest.iloc[0]["symbol"], "SPY")

    def test_shadow_status_collects_close_misses_without_official_candidates(self) -> None:
        one_rule = pd.Series(
            scanner_row(
                scanner_status="not_ready",
                missing_conditions="above opening range high",
                passed_condition_count=8,
                condition_count=9,
            )
        )
        allowed = pd.Series(scanner_row(scanner_status="allowed", missing_conditions="", passed_condition_count=9, condition_count=9))
        too_far = pd.Series(
            scanner_row(
                scanner_status="not_ready",
                missing_conditions="price below 200 EMA; 1H bearish thesis; bearish rejection candle",
                passed_condition_count=5,
                condition_count=9,
            )
        )

        self.assertEqual(shadow_status_for_row(one_rule)[0], "one_rule_miss")
        self.assertEqual(shadow_status_for_row(allowed)[0], "official_candidate")
        self.assertEqual(shadow_status_for_row(too_far)[0], "not_shadow_candidate")

    def test_observations_require_open_market_and_are_deduplicated(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        open_market = {"market_is_open": True, "today": "2026-05-26"}
        closed_market = {"market_is_open": False, "today": "2026-05-26"}
        candidate = scanner_to_observations(scanner, "2026-05-26 10:31:00 EDT")

        self.assertTrue(scanner_is_fresh_for_open_market(scanner, open_market))
        self.assertFalse(scanner_is_fresh_for_open_market(scanner, closed_market))
        self.assertEqual(len(dedupe(candidate, candidate)), 0)

    def test_paper_trade_reconciliation_marks_recorded_outcome(self) -> None:
        observation = scanner_to_observations(pd.DataFrame([scanner_row()]), "2026-05-26 10:31:00 EDT")
        paper = pd.DataFrame(
            [
                {
                    "trade_date": "2026-05-26",
                    "entry_time_et": "10:30",
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "outcome_r": 1.25,
                    "followed_plan": "yes",
                    "exit_reason": "target",
                }
            ]
        )

        reconciled, unmatched = reconcile(observation, paper)

        self.assertEqual(reconciled.iloc[0]["reconciliation_status"], "paper_outcome_recorded")
        self.assertTrue(unmatched.empty)


class StateAndEndpointTests(unittest.TestCase):
    def write_historical_bucket_fixture(
        self,
        output_dir: Path,
        *,
        target_session: str = "2026-05-26",
        approved_last: str = "2026-05-26",
        promotion_last: str = "2026-05-26",
        vault_last: str = "2026-05-26",
    ) -> None:
        """Write minimal historical simulator bucket inputs."""

        (output_dir / "refresh_status.json").write_text(
            json.dumps(
                {
                    "scanner": {"latest_scanner_session": target_session},
                    "provider_refresh": {"provider": "webull"},
                }
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "promotion_decision": "paper_watch_candidate",
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "candidate": "current + no_vwap_exit",
                    "trade_log": "SPY_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv",
                }
            ]
        ).to_csv(output_dir / "promotion_review.csv", index=False)
        pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "entry_time": f"{promotion_last} 14:00:00+00:00",
                    "exit_time": f"{promotion_last} 15:00:00+00:00",
                    "setup_type": "setup_a",
                    "entry": 100.0,
                    "stop": 99.0,
                    "target": 102.0,
                    "exit_price": 101.0,
                    "r_result": 1.0,
                    "exit_reason": "target_hit",
                }
            ]
        ).to_csv(output_dir / "SPY_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv", index=False)
        pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "entry_time": f"{approved_last} 14:00:00+00:00",
                    "exit_time": f"{approved_last} 15:00:00+00:00",
                    "setup_type": "setup_a",
                    "entry": 100.0,
                    "stop": 99.0,
                    "target": 102.0,
                    "exit_price": 101.5,
                    "r_result": 1.5,
                    "exit_reason": "target_hit",
                    "playbook_setup": "Setup A Long",
                    "playbook_variant": "current",
                    "playbook_exit_profile": "no_vwap_exit",
                }
            ]
        ).to_csv(output_dir / "playbook_approved_trades.csv", index=False)
        pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "entry_time": f"{vault_last} 14:00:00+00:00",
                    "exit_time": f"{vault_last} 15:00:00+00:00",
                    "setup_type": "vwap_reclaim_reject",
                    "entry": 100.0,
                    "stop": 99.0,
                    "target": 102.0,
                    "exit_price": 102.0,
                    "r_result": 2.0,
                    "exit_reason": "target_hit",
                }
            ]
        ).to_csv(output_dir / "vwap_reclaim_reject_trades.csv", index=False)

    def write_synced_data_flow_fixture(self, output_dir: Path) -> None:
        """Write a minimal synced dashboard data-flow fixture."""

        pd.DataFrame([scanner_row()]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
        pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "scanner_status": "allowed",
                    "signal_freshness": "current_candle",
                    "sizing_status": "size_ok",
                    "suggested_shares": 10,
                }
            ]
        ).to_csv(output_dir / "position_sizing.csv", index=False)
        (output_dir / "refresh_status.json").write_text(
            json.dumps(
                {
                    "status": "ready_to_refresh",
                    "market": {"today": "2026-05-26", "market_is_open": True},
                    "scanner": {"latest_scanner_session": "2026-05-26"},
                    "provider_refresh": {"status": "current_session_bars", "provider": "webull"},
                    "candle_freshness": {
                        "status": "fresh",
                        "stale_m5_symbols": [],
                        "stale_m30_symbols": [],
                        "unknown_symbols": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "system_state.json").write_text(
            json.dumps(
                {
                    "market": {"today": "2026-05-26", "market_is_open": True},
                    "scanner": {"rows": 1},
                    "current_candidates": {"count": 1},
                    "app_health": {"generated_at_et": "2026-05-26 10:31:00 EDT"},
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "dashboard_data_preflight.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        (output_dir / "market_regime_router.json").write_text(
            json.dumps({"candidates": [{"symbol": "SPY", "setup": "Setup A Long", "direction": "long"}]}),
            encoding="utf-8",
        )
        (output_dir / "pre_entry_review.json").write_text(json.dumps({"candidate_count": 1}), encoding="utf-8")
        (output_dir / "paper_gate_v2.json").write_text(
            json.dumps(
                {
                    "generated_at_et": "2026-05-26 10:31:00 EDT",
                    "status": "waiting",
                    "ready_sample_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "options_contract_gate.json").write_text(
            json.dumps(
                {
                    "generated_at_et": "2026-05-26 10:31:01 EDT",
                    "status": "waiting_for_chart_candidate",
                    "ready_sample_count": 0,
                    "passed_contract_count": 0,
                    "missing_contract_reviews": 0,
                    "blocked_contract_count": 0,
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "paper_validation_sample_import.json").write_text(
            json.dumps(
                {
                    "generated_at_et": "2026-05-26 10:31:02 EDT",
                    "mode": "preview",
                    "ready_candidates": 0,
                    "contract_ready_candidates": 0,
                    "contract_gate_status": "waiting_for_chart_candidate",
                    "missing_contract_reviews": 0,
                    "blocked_contract_count": 0,
                    "new_rows": 0,
                }
            ),
            encoding="utf-8",
        )
        pd.DataFrame([{"symbol": "SPY", "status": "current_or_not_repairable"}]).to_csv(
            output_dir / "m30_repair_audit.csv",
            index=False,
        )
        (output_dir / "historical_bucket_sync.json").write_text(
            json.dumps(
                {
                    "status": "synced",
                    "target_scanner_session": "2026-05-26",
                    "unified_last_entry": "2026-05-26",
                    "behind_buckets": [],
                    "missing_buckets": [],
                }
            ),
            encoding="utf-8",
        )

    def test_data_flow_sentinel_passes_when_pipeline_is_synced(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)

            payload = build_data_flow_sentinel(output_dir)

        self.assertEqual(payload["status"], "synced")
        self.assertEqual(payload["fail_count"], 0)
        self.assertEqual(payload["contract"]["scanner_rows"], 1)
        self.assertEqual(payload["contract"]["router_candidate_rows"], 1)
        self.assertEqual(payload["contract"]["paper_gate_ready_samples"], 0)
        self.assertEqual(payload["contract"]["validation_import_mode"], "preview")
        self.assertEqual(payload["contract"]["historical_bucket_status"], "synced")

    def test_data_flow_sentinel_allows_scanner_snapshot_zero_with_candidate_ledger_ready(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)
            (output_dir / "paper_gate_v2.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:00 EDT",
                        "status": "waiting",
                        "ready_sample_count": 0,
                        "promotion_source": "scanner_snapshot",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "options_contract_gate.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:01 EDT",
                        "status": "ready",
                        "ready_sample_count": 2,
                        "passed_contract_count": 1,
                        "missing_contract_reviews": 1,
                        "blocked_contract_count": 0,
                        "promotion_source": "candidate_window_ledger",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_validation_sample_import.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:02 EDT",
                        "mode": "preview",
                        "ready_candidates": 2,
                        "contract_ready_candidates": 1,
                        "contract_gate_status": "ready",
                        "missing_contract_reviews": 1,
                        "blocked_contract_count": 0,
                        "new_rows": 1,
                    }
                ),
                encoding="utf-8",
            )

            payload = build_data_flow_sentinel(output_dir)

        failed_areas = {row["area"] for row in payload["checks"] if row["status"] == "fail"}
        self.assertEqual(payload["status"], "synced")
        self.assertNotIn("Validation gate sequence", failed_areas)
        self.assertEqual(payload["contract"]["paper_gate_candidate_source"], "scanner_snapshot")
        self.assertEqual(payload["contract"]["paper_gate_ready_samples"], 0)
        self.assertEqual(payload["contract"]["candidate_ledger_paper_gate_candidate_source"], "candidate_window_ledger")
        self.assertEqual(payload["contract"]["candidate_ledger_paper_gate_ready_samples"], 2)
        self.assertEqual(payload["contract"]["options_contract_passed"], 1)
        self.assertEqual(payload["contract"]["validation_import_mode"], "preview")

    def test_data_flow_sentinel_blocks_true_same_source_paper_contract_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)
            (output_dir / "paper_gate_v2.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:00 EDT",
                        "status": "ready",
                        "ready_sample_count": 1,
                        "promotion_source": "candidate_window_ledger",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "options_contract_gate.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:01 EDT",
                        "status": "ready",
                        "ready_sample_count": 2,
                        "passed_contract_count": 1,
                        "missing_contract_reviews": 0,
                        "blocked_contract_count": 0,
                        "promotion_source": "candidate_window_ledger",
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "paper_validation_sample_import.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:02 EDT",
                        "mode": "preview",
                        "ready_candidates": 2,
                        "contract_ready_candidates": 1,
                        "contract_gate_status": "ready",
                        "missing_contract_reviews": 0,
                        "blocked_contract_count": 0,
                        "new_rows": 1,
                    }
                ),
                encoding="utf-8",
            )

            payload = build_data_flow_sentinel(output_dir)

        failed_checks = [row for row in payload["checks"] if row["status"] == "fail"]
        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(any(row["area"] == "Validation gate sequence" for row in failed_checks))
        self.assertTrue(any("Same-source Paper Gate ready 1 vs Contract Gate ready 2" in row["detail"] for row in failed_checks))

    def test_historical_bucket_sync_marks_all_current_buckets_synced(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_historical_bucket_fixture(output_dir, target_session="2026-05-26")

            payload = build_historical_bucket_sync(output_dir)

        statuses = {row["bucket"]: row["status"] for row in payload["bucket_rows"]}
        self.assertEqual(payload["status"], "synced")
        self.assertEqual(payload["target_scanner_session"], "2026-05-26")
        self.assertEqual(payload["unified_last_entry"], "2026-05-26")
        self.assertEqual(statuses["Approved Playbook"], "current")
        self.assertEqual(statuses["Promotion Review"], "current")
        self.assertEqual(statuses["Strategy Vault Research"], "current")

    def test_historical_bucket_sync_identifies_stale_source_lane(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_historical_bucket_fixture(
                output_dir,
                target_session="2026-06-16",
                approved_last="2026-06-16",
                promotion_last="2026-05-28",
                vault_last="2026-06-16",
            )

            payload = build_historical_bucket_sync(output_dir)

        statuses = {row["bucket"]: row["status"] for row in payload["bucket_rows"]}
        self.assertEqual(payload["status"], "watch")
        self.assertEqual(payload["unified_last_entry"], "2026-06-16")
        self.assertEqual(statuses["Promotion Review"], "behind")
        self.assertEqual(statuses["Strategy Vault Research"], "current")
        self.assertIn("Promotion Review", payload["behind_buckets"])

    def test_data_flow_sentinel_blocks_when_validation_gate_sequence_is_mismatched(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)
            (output_dir / "options_contract_gate.json").write_text(
                json.dumps(
                    {
                        "generated_at_et": "2026-05-26 10:31:01 EDT",
                        "status": "ready",
                        "ready_sample_count": 1,
                        "passed_contract_count": 1,
                        "missing_contract_reviews": 0,
                        "blocked_contract_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            payload = build_data_flow_sentinel(output_dir)

        failed_areas = {row["area"] for row in payload["checks"] if row["status"] == "fail"}
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("Validation gate sequence", failed_areas)
        self.assertEqual(payload["contract"]["options_contract_gate_status"], "ready")

    def test_data_flow_sentinel_blocks_when_sizing_loses_scanner_row(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)
            pd.DataFrame(columns=["symbol", "setup", "direction"]).to_csv(
                output_dir / "position_sizing.csv",
                index=False,
            )

            payload = build_data_flow_sentinel(output_dir)

        failed_areas = {row["area"] for row in payload["checks"] if row["status"] == "fail"}
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("Scanner to sizing", failed_areas)

    def test_data_flow_sentinel_blocks_unrepaired_provider_session_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)
            pd.DataFrame(
                [
                    {
                        "refresh_run_at_et": "2026-05-26 10:31:00 EDT",
                        "provider": "webull",
                        "symbol": "SPY",
                        "m30_status": "ok",
                        "m30_latest_session": "2026-05-25",
                        "m5_status": "ok",
                        "m5_latest_session": "2026-05-26",
                        "refresh_evidence_status": "timeframe_session_mismatch",
                    }
                ]
            ).to_csv(output_dir / "market_refresh_audit.csv", index=False)

            payload = build_data_flow_sentinel(output_dir)

        failed_areas = {row["area"] for row in payload["checks"] if row["status"] == "fail"}
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("Provider/session stability", failed_areas)
        self.assertEqual(payload["contract"]["provider_stability_status"], "mixed_session")

    def test_data_flow_sentinel_warns_when_provider_session_mismatch_was_repaired(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_synced_data_flow_fixture(output_dir)
            pd.DataFrame([{"symbol": "SPY", "status": "repaired"}]).to_csv(
                output_dir / "m30_repair_audit.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {
                        "refresh_run_at_et": "2026-05-26 10:31:00 EDT",
                        "provider": "webull",
                        "symbol": "SPY",
                        "m30_status": "ok",
                        "m30_latest_session": "2026-05-25",
                        "m5_status": "ok",
                        "m5_latest_session": "2026-05-26",
                        "refresh_evidence_status": "timeframe_session_mismatch",
                    }
                ]
            ).to_csv(output_dir / "market_refresh_audit.csv", index=False)

            payload = build_data_flow_sentinel(output_dir)

        warned_areas = {row["area"] for row in payload["checks"] if row["status"] == "warn"}
        self.assertEqual(payload["status"], "watch")
        self.assertIn("Provider/session stability", warned_areas)
        self.assertEqual(payload["contract"]["provider_stability_status"], "watch_repaired")

    def test_provider_stability_audit_marks_stable_refresh(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            audit_csv = output_dir / "market_refresh_audit.csv"
            pd.DataFrame(
                [
                    refresh_audit_row(
                        symbol="SPY",
                        refresh_run_at_et="2026-05-26 10:31:00 EDT",
                        m30_latest_session="2026-05-26",
                        m5_latest_session="2026-05-26",
                        refresh_evidence_status="current_session_in_progress",
                    )
                ]
            ).to_csv(audit_csv, index=False)
            pd.DataFrame([{"symbol": "SPY", "status": "current_or_not_repairable"}]).to_csv(
                output_dir / "m30_repair_audit.csv",
                index=False,
            )

            payload = build_provider_stability_audit(
                output_dir=output_dir,
                audit_csv=audit_csv,
                provider="webull",
                symbols=["SPY"],
                refresh_started_at="2026-05-26 10:30:00 EDT",
                refresh_ended_at="2026-05-26 10:31:00 EDT",
            )

        self.assertEqual(payload["status"], "stable")
        self.assertEqual(payload["refresh_started_at_et"], "2026-05-26 10:30:00 EDT")
        self.assertEqual(payload["mismatch_symbols"], [])
        self.assertEqual(payload["evidence_counts"]["current_session_in_progress"], 1)

    def test_provider_stability_audit_blocks_unrepaired_mixed_session(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            audit_csv = output_dir / "market_refresh_audit.csv"
            pd.DataFrame(
                [
                    refresh_audit_row(
                        symbol="SPY",
                        refresh_run_at_et="2026-05-26 10:31:00 EDT",
                        m30_latest_session="2026-05-25",
                        m5_latest_session="2026-05-26",
                        refresh_evidence_status="timeframe_session_mismatch",
                    )
                ]
            ).to_csv(audit_csv, index=False)
            pd.DataFrame([{"symbol": "SPY", "status": "current_or_not_repairable"}]).to_csv(
                output_dir / "m30_repair_audit.csv",
                index=False,
            )

            payload = build_provider_stability_audit(
                output_dir=output_dir,
                audit_csv=audit_csv,
                provider="webull",
                symbols=["SPY"],
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["mismatch_symbols"], ["SPY"])
        self.assertIn("Refresh again", payload["next_action"])

    def write_replay_chart_fixture(self, output_dir: Path, include_exit_session_m5: bool = True) -> None:
        """Write one historical card and the stored candles used by its chart."""

        replay = {
            "cards": [
                {
                    "replay_id": 1,
                    "symbol": "SPY",
                    "entry_time": "2026-05-26 14:00:00+00:00",
                    "exit_time": "2026-05-26 14:10:00+00:00",
                    "entry": 102.5,
                    "stop": 101.0,
                    "target": 105.5,
                }
            ]
        }
        (output_dir / "setup_replay.json").write_text(json.dumps(replay), encoding="utf-8")
        m30_rows = [
            {"datetime": "2026-05-26T13:30:00Z", "open": 100, "high": 102, "low": 99.5, "close": 101, "volume": 1000},
            {"datetime": "2026-05-26T14:00:00Z", "open": 101, "high": 103, "low": 100.8, "close": 102.5, "volume": 1300},
            {"datetime": "2026-05-26T14:30:00Z", "open": 102.5, "high": 106, "low": 102, "close": 105.5, "volume": 1400},
        ]
        m5_rows = [
            {"datetime": "2026-05-26T13:30:00Z", "open": 100, "high": 101, "low": 99.5, "close": 100.5, "volume": 300},
            {"datetime": "2026-05-26T13:35:00Z", "open": 100.5, "high": 102, "low": 100, "close": 101, "volume": 320},
            {"datetime": "2026-05-26T14:00:00Z", "open": 101, "high": 103, "low": 100.8, "close": 102.5, "volume": 500},
            {"datetime": "2026-05-26T14:05:00Z", "open": 102.5, "high": 104, "low": 102, "close": 103.7, "volume": 520},
            {"datetime": "2026-05-26T14:10:00Z", "open": 103.7, "high": 105, "low": 103.5, "close": 104.8, "volume": 540},
        ]
        if not include_exit_session_m5:
            m5_rows = [
                {"datetime": "2026-05-22T13:30:00Z", "open": 100, "high": 101, "low": 99.5, "close": 100.5, "volume": 300}
            ]
        pd.DataFrame(m30_rows).to_csv(output_dir / "webull_SPY_M30_candles.csv", index=False)
        pd.DataFrame(m5_rows).to_csv(output_dir / "webull_SPY_M5_candles.csv", index=False)

    def test_trading_workspace_returns_read_only_webull_chart_for_approved_symbol(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            candle_rows = [
                {"datetime": "2026-05-22T13:30:00Z", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
                {"datetime": "2026-05-22T13:35:00Z", "open": 100.5, "high": 101.2, "low": 100, "close": 101, "volume": 1200},
                {"datetime": "2026-05-26T13:30:00Z", "open": 102, "high": 103, "low": 101.5, "close": 102.5, "volume": 1400},
                {"datetime": "2026-05-26T13:35:00Z", "open": 102.5, "high": 104, "low": 102, "close": 103.5, "volume": 1600},
            ]
            pd.DataFrame(candle_rows).to_csv(output_dir / "webull_SPY_M5_candles.csv", index=False)

            chart = run_app.build_trading_workspace_data(output_dir, "SPY", "M5")

        self.assertEqual(chart["symbol"], "SPY")
        self.assertEqual(chart["latest_session"], "2026-05-26")
        self.assertEqual(chart["last_price"], 103.5)
        self.assertIn("market-data", chart["source"])
        self.assertIn("Setup A Long", chart["approved_setups"])
        self.assertIn("vwap", chart["candles"][-1])

    def test_replay_chart_hides_future_candles_until_outcome_is_revealed(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_replay_chart_fixture(output_dir)

            concealed = run_app.build_replay_chart_data(output_dir, 1, revealed=False)
            revealed = run_app.build_replay_chart_data(output_dir, 1, revealed=True)

        self.assertEqual(concealed["timeframe"], "M30")
        self.assertEqual(concealed["candles"][-1]["time_et"], "05/26 10:00")
        self.assertEqual([marker["label"] for marker in concealed["markers"]], ["E"])
        self.assertEqual(revealed["timeframe"], "M5")
        self.assertEqual(revealed["candles"][-1]["time_et"], "05/26 10:10")
        self.assertEqual([marker["label"] for marker in revealed["markers"]], ["E", "X"])

    def test_revealed_replay_chart_uses_m30_fallback_when_m5_session_is_missing(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_replay_chart_fixture(output_dir, include_exit_session_m5=False)

            chart = run_app.build_replay_chart_data(output_dir, 1, revealed=True)

        self.assertEqual(chart["timeframe"], "M30")
        self.assertIn("M30", chart["source"])

    def test_replay_management_releases_only_the_requested_exit_candle_step(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.write_replay_chart_fixture(output_dir)

            ready = run_app.build_replay_chart_data(output_dir, 1, step=0)
            first_bar = run_app.build_replay_chart_data(output_dir, 1, step=1)
            completed = run_app.build_replay_chart_data(output_dir, 1, step=99)

        self.assertEqual(ready["timeframe"], "M5")
        self.assertEqual(ready["step"], 0)
        self.assertIsNone(ready["available_steps"])
        self.assertEqual(ready["candles"][-1]["time_et"], "05/26 10:00")
        self.assertIsNone(ready["current_r"])
        self.assertEqual(first_bar["step"], 1)
        self.assertIsNone(first_bar["available_steps"])
        self.assertEqual(first_bar["candles"][-1]["time_et"], "05/26 10:05")
        self.assertFalse(first_bar["management_complete"])
        self.assertEqual(completed["step"], 2)
        self.assertEqual(completed["available_steps"], 2)
        self.assertEqual(completed["candles"][-1]["time_et"], "05/26 10:10")
        self.assertTrue(completed["management_complete"])
        self.assertEqual([marker["label"] for marker in completed["markers"]], ["E"])

    def test_trading_workspace_rejects_symbol_outside_approved_universe(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in the approved"):
            run_app.build_trading_workspace_data(Path("logs"), "NFLX", "M5")

    def test_setup_readiness_exposes_rule_checks_and_prior_signal_marker(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    scanner_row(
                        setup="Setup A Long",
                        scanner_status="allowed",
                        signal_freshness="earlier_today",
                        latest_signal_et="2026-05-26 10:00",
                        latest_candle_notes="signal found earlier_today; latest candle gaps: above opening range high",
                        passed_conditions="regular session; price above 200 EMA",
                        missing_conditions="above opening range high",
                        passed_condition_count=2,
                        condition_count=3,
                    )
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            readiness = run_app.build_setup_readiness_data(output_dir, "SPY")

        self.assertEqual(readiness["setups"][0]["status_label"], "Triggered Earlier")
        self.assertEqual(readiness["setups"][0]["passed_conditions"], ["regular session", "price above 200 EMA"])
        self.assertEqual(readiness["setups"][0]["missing_conditions"], ["above opening range high"])
        self.assertEqual(readiness["signal_markers"][0]["time_et"], "05/26 10:00")
        self.assertIn("do not create signals", readiness["guardrail"])

    def test_setup_readiness_uses_strategy_contract_marker_labels(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    scanner_row(
                        setup="Trend Pullback Short",
                        variant="trend_pullback_short",
                        scanner_status="allowed",
                        signal_freshness="earlier_today",
                        latest_signal_et="2026-05-26 10:00",
                    )
                ]
            ).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)

            readiness = run_app.build_setup_readiness_data(output_dir, "SPY")

        self.assertEqual(readiness["signal_markers"][0]["label"], "P")

    def test_setup_readiness_rejects_symbol_outside_approved_universe(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in the approved"):
            run_app.build_setup_readiness_data(Path("logs"), "NFLX")

    def test_near_miss_analytics_counts_missing_conditions_without_creating_signals(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    symbol="QQQ",
                    setup="Setup A Long",
                    scanner_status="not_ready",
                    latest_candle_et="2026-05-26 15:30",
                    missing_conditions="bullish reclaim candle; room to target",
                    passed_condition_count=7,
                    condition_count=9,
                ),
                scanner_row(symbol="SPY", scanner_status="allowed"),
            ]
        )

        snapshot = near_miss_rows(scanner)
        payload = build_near_miss_payload(scanner, pd.DataFrame())

        self.assertEqual(len(snapshot), 2)
        self.assertEqual(payload["basis"], "latest_saved_scanner_snapshot")
        self.assertEqual(payload["snapshot_blocker_rows"], 2)
        self.assertIn("never changes signal eligibility", payload["guardrail"])

    def test_near_miss_tracker_links_later_allowed_observation_result(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    scanner_status="not_ready",
                    latest_candle_et="2026-05-26 10:00",
                    missing_conditions="bullish reclaim candle",
                    passed_condition_count=7,
                    condition_count=10,
                )
            ]
        )
        near_misses = near_miss_rows(scanner)
        results = pd.DataFrame(
            [
                {
                    "scan_date": "2026-05-26",
                    "signal_time_et": "2026-05-26 10:30",
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "signal_status": "allowed",
                    "evaluation_status": "matured",
                    "hypothetical_r": 1.25,
                    "hypothetical_exit_reason": "profit_target_5m",
                    "evaluation_note": "Observed hypothetical outcome.",
                }
            ]
        )

        outcomes = almost_ready_outcomes(near_misses, results)
        payload = build_near_miss_payload(scanner, near_misses, results)

        self.assertEqual(outcomes[0]["resolution"], "later_allowed_matured")
        self.assertEqual(outcomes[0]["hypothetical_r"], 1.25)
        self.assertEqual(payload["missed_summary"]["later_allowed_matured"], 1)
        self.assertEqual(payload["missed_summary"]["later_allowed_avg_r"], 1.25)

    def test_near_miss_observations_only_record_open_session_and_dedupe(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    scanner_status="not_ready",
                    missing_conditions="above opening range high",
                    latest_candle_et="2026-05-26 10:30",
                )
            ]
        )
        open_market = {"market_is_open": True, "today": "2026-05-26"}
        closed_market = {"market_is_open": False, "today": "2026-05-26"}
        rows = near_miss_rows(scanner, "2026-05-26 10:31:00 EDT")

        self.assertTrue(near_miss_scanner_is_fresh(scanner, open_market))
        self.assertFalse(near_miss_scanner_is_fresh(scanner, closed_market))
        self.assertTrue(dedupe_near_misses(rows, rows).empty)

    def test_investment_narrative_is_context_only_for_approved_symbol(self) -> None:
        narrative = run_app.build_investment_narrative_data("NVDA")

        self.assertEqual(narrative["symbol"], "NVDA")
        self.assertEqual(narrative["scope"], "Long-term context only")
        self.assertEqual(narrative["source_status"], "sources_not_connected")
        self.assertIn("excluded from strategy scoring", narrative["guardrail"])
        self.assertTrue(narrative["monitoring_themes"])

    def test_investment_narrative_rejects_symbol_outside_approved_universe(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in the approved"):
            run_app.build_investment_narrative_data("NFLX")

    def test_system_state_keeps_execution_flags_disabled(self) -> None:
        with TemporaryDirectory() as temporary:
            state = build_system_state(output_dir=Path(temporary), paper_csv=Path(temporary) / "paper.csv")

        self.assertFalse(state["safety"]["live_trading_enabled"])
        self.assertFalse(state["safety"]["broker_order_execution_enabled"])
        self.assertFalse(state["safety"]["real_money_ready"])

    def test_system_state_summarizes_backtest_performance(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            summary = pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "baseline_trades": 12,
                        "baseline_win_rate": 0.5833,
                        "baseline_expectancy_r": 0.18,
                        "baseline_profit_factor": 1.7,
                        "summary_report": "logs/QQQ_summary.md",
                    },
                    {
                        "symbol": "SPY",
                        "variant": "current",
                        "exit_profile": "no_vwap_exit",
                        "baseline_trades": 8,
                        "baseline_win_rate": 0.5,
                        "baseline_expectancy_r": -0.08,
                        "baseline_profit_factor": 0.7,
                        "summary_report": "logs/SPY_summary.md",
                    },
                ]
            )
            summary.to_csv(output_dir / "best_plus_market_watchlist_backtest_summary.csv", index=False)

            state = build_system_state(output_dir=output_dir, paper_csv=output_dir / "paper.csv")

        backtests = state["backtest_performance"]
        self.assertEqual(backtests["candidate_count"], 2)
        self.assertEqual(backtests["positive_expectancy_count"], 1)
        self.assertEqual(backtests["total_trades"], 20)
        self.assertEqual(backtests["best_candidate"]["symbol"], "QQQ")
        self.assertEqual(backtests["best_candidate"]["win_rate_pct"], 58.33)

    def test_system_state_marks_todays_scanner_non_actionable_after_close(self) -> None:
        scanner = pd.DataFrame([scanner_row()])
        market = {
            "today": "2026-05-26",
            "is_market_day": True,
            "market_status": "after_close",
            "market_is_open": False,
            "next_market_session": "2026-05-27",
        }

        freshness = data_freshness_state(scanner, market)

        self.assertEqual(freshness["data_status"], "outside_market_hours")
        self.assertIn("2026-05-27", freshness["action"])

    def test_system_state_summarizes_previously_passed_premarket_probe(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "premarket_verification.json"
            path.write_text("{}", encoding="utf-8")
            state = premarket_verification_state(
                {
                    "checks": [
                        {"area": "Webull data-only access", "status": "previous_pass"},
                        {"area": "Candle integrity", "status": "pass"},
                        {"area": "Paper import gate", "status": "pass"},
                    ]
                },
                path,
            )

        self.assertEqual(state["status"], "passed")
        self.assertEqual(state["probe_status"], "previous_pass")

    def test_current_candidate_state_adds_manual_scale_guidance(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    quality_grade="A",
                    quality_score=9,
                    relative_volume=1.8,
                    room_to_target_r=2.3,
                )
            ]
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "suggested_shares": 50,
                    "estimated_risk_dollars": 50.0,
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for paper sizing.",
                }
            ]
        )
        freshness = {"data_status": "fresh_for_today"}
        refresh_status = {"paper_import_blocked": False}

        state = current_candidate_state(scanner, sizing, freshness, refresh_status)

        card = state["cards"][0]
        self.assertEqual(card["scale_tier"], "paper_scale")
        self.assertEqual(card["scale_label"], "Paper Scale Candidate")
        self.assertEqual(card["suggested_risk_pct"], 1.0)
        self.assertIn("options checklist", card["scale_reason"])

    def test_current_candidate_state_adds_router_route_and_blocks_caution_review(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    symbol="QQQ",
                    setup="Setup C Full-Session Short",
                    direction="short",
                    variant="setup_b_quality_full_session",
                    exit_profile="no_vwap_exit",
                )
            ]
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "QQQ",
                    "setup": "Setup C Full-Session Short",
                    "direction": "short",
                    "suggested_shares": 50,
                    "estimated_risk_dollars": 50.0,
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for paper sizing.",
                }
            ]
        )
        router = {
            "candidates": [
                {
                    "symbol": "QQQ",
                    "setup": "Setup C Full-Session Short",
                    "direction": "short",
                    "variant": "setup_b_quality_full_session",
                    "exit_profile": "no_vwap_exit",
                    "strategy_id": "vwap_ema_trend_continuation",
                    "candidate_route": "caution_review",
                    "time_bucket": "late_day",
                    "action": "Manual caution review only.",
                }
            ]
        }
        freshness = {"data_status": "fresh_for_today"}
        refresh_status = {"paper_import_blocked": False}

        state = current_candidate_state(
            scanner,
            sizing,
            freshness,
            refresh_status,
            market_regime_router=router,
        )

        card = state["cards"][0]
        self.assertFalse(card["ready_for_review"])
        self.assertEqual(card["router_route"], "caution_review")
        self.assertIn("Market regime router says caution_review", " ".join(card["blockers"]))

    def test_current_candidate_state_marks_grace_lane_manual_review_ready(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    latest_signal_et="2026-05-26 10:30",
                    source_signal_et="2026-05-26 10:30",
                    candidate_entry_et="2026-05-26 11:00",
                    signal_freshness="grace_candle",
                    validation_lane="B",
                    manual_review_required=True,
                )
            ]
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "suggested_shares": 10,
                    "estimated_risk_dollars": 10.0,
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for reduced B-tier grace paper sizing.",
                }
            ]
        )
        router = {
            "candidates": [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "variant": "current",
                    "exit_profile": "no_vwap_exit",
                    "candidate_route": "caution_review",
                    "action": "Manual B-tier grace review only.",
                }
            ]
        }
        freshness = {"data_status": "fresh_for_today"}
        refresh_status = {"paper_import_blocked": True}

        state = current_candidate_state(scanner, sizing, freshness, refresh_status, market_regime_router=router)

        card = state["cards"][0]
        self.assertTrue(card["ready_for_review"])
        self.assertEqual(card["signal_freshness"], "grace_candle")
        self.assertEqual(card["validation_lane"], "B")
        self.assertEqual(card["candidate_entry_et"], "2026-05-26 11:00")

    def test_current_candidate_state_caps_scale_before_paper_gate(self) -> None:
        scanner = pd.DataFrame(
            [
                scanner_row(
                    quality_grade="A",
                    quality_score=9,
                    relative_volume=1.8,
                    room_to_target_r=2.3,
                )
            ]
        )
        sizing = pd.DataFrame(
            [
                {
                    "symbol": "SPY",
                    "setup": "Setup A Long",
                    "direction": "long",
                    "suggested_shares": 50,
                    "estimated_risk_dollars": 50.0,
                    "sizing_status": "size_ok",
                    "sizing_reason": "Eligible for paper sizing.",
                }
            ]
        )
        freshness = {"data_status": "fresh_for_today"}
        refresh_status = {"paper_import_blocked": False}
        guard = risk_guard_state({"allowed_completed_trades": 0})

        state = current_candidate_state(scanner, sizing, freshness, refresh_status, guard)

        card = state["cards"][0]
        self.assertEqual(card["scale_tier"], "standard")
        self.assertEqual(card["scale_label"], "Standard Risk")
        self.assertEqual(card["suggested_risk_pct"], 0.5)
        self.assertIn("scale-up is locked", card["scale_reason"])

    def test_current_candidate_state_never_scales_unready_setups(self) -> None:
        scanner = pd.DataFrame([scanner_row(scanner_status="blocked_watch_only")])
        sizing = pd.DataFrame()
        freshness = {"data_status": "fresh_for_today"}
        refresh_status = {"paper_import_blocked": False}

        state = current_candidate_state(scanner, sizing, freshness, refresh_status)

        card = state["cards"][0]
        self.assertEqual(card["scale_tier"], "no_scale")
        self.assertEqual(card["suggested_risk_pct"], 0.0)

    def test_refresh_status_blocks_paper_import_when_scanner_is_stale(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            for symbol in ["AAPL", "AMD", "META", "MSFT", "NVDA", "QQQ", "SPY", "TSLA"]:
                (output_dir / f"webull_{symbol}_M30_candles.csv").write_text("test", encoding="utf-8")
                (output_dir / f"webull_{symbol}_M5_candles.csv").write_text("test", encoding="utf-8")
            pd.DataFrame([scanner_row(scan_date="2026-05-22")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            market = {
                "now_et": "2026-05-26 10:30:00 EDT",
                "today": "2026-05-26",
                "market_status": "market_open",
                "market_status_reason": "Regular market session is open.",
                "market_is_open": True,
                "next_market_session": "2026-05-26",
                "next_market_session_status": "Regular session",
            }
            with patch("reports.refresh_status.market_refresh_state", return_value=market):
                status = build_refresh_status(output_dir)

        self.assertTrue(status["paper_import_blocked"])
        self.assertIn("Blocked until refreshed current-session data", status["paper_import_reason"])

    def test_refresh_status_requires_current_refresh_audit_for_allowed_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            for symbol in ["AAPL", "AMD", "META", "MSFT", "NVDA", "QQQ", "SPY", "TSLA"]:
                (output_dir / f"webull_{symbol}_M30_candles.csv").write_text("test", encoding="utf-8")
                (output_dir / f"webull_{symbol}_M5_candles.csv").write_text("test", encoding="utf-8")
            pd.DataFrame([scanner_row()]).to_csv(output_dir / "daily_paper_signal_scanner.csv", index=False)
            audit_path = output_dir / "audit.csv"
            market = {
                "now_et": "2026-05-26 10:30:00 EDT",
                "today": "2026-05-26",
                "market_status": "market_open",
                "market_status_reason": "Regular market session is open.",
                "market_is_open": True,
                "next_market_session": "2026-05-26",
                "next_market_session_status": "Regular session",
            }
            with patch("reports.refresh_status.market_refresh_state", return_value=market):
                without_audit = build_refresh_status(output_dir, audit_path)
                pd.DataFrame([refresh_audit_row()]).to_csv(audit_path, index=False)
                with_audit = build_refresh_status(output_dir, audit_path)

        self.assertTrue(without_audit["paper_import_blocked"])
        self.assertIn("refresh evidence", without_audit["paper_import_reason"])
        self.assertFalse(with_audit["paper_import_blocked"])

    def test_refresh_status_reports_stale_candle_age(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            now = datetime.now(MARKET_TZ)
            fresh_bar = (now - timedelta(minutes=5)).isoformat()
            stale_bar = (now - timedelta(minutes=35)).isoformat()
            m30_bar = (now - timedelta(minutes=30)).isoformat()
            for symbol in ["AAPL", "AMD", "NVDA", "QQQ", "SPY", "TSLA"]:
                pd.DataFrame(
                    [{"datetime": m30_bar, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 100}]
                ).to_csv(output_dir / f"webull_{symbol}_M30_candles.csv", index=False)
                latest_m5 = stale_bar if symbol == "SPY" else fresh_bar
                pd.DataFrame(
                    [{"datetime": latest_m5, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 100}]
                ).to_csv(output_dir / f"webull_{symbol}_M5_candles.csv", index=False)
            pd.DataFrame([scanner_row(scan_date=str(now.date()))]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            market = {
                "now_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "today": str(now.date()),
                "market_status": "market_open",
                "market_status_reason": "Regular market session is open.",
                "market_is_open": True,
                "next_market_session": str(now.date()),
                "next_market_session_status": "Regular session",
            }
            with patch("reports.refresh_status.market_refresh_state", return_value=market):
                status = build_refresh_status(output_dir)

        self.assertEqual(status["candle_freshness"]["status"], "stale")
        self.assertIn("SPY", status["candle_freshness"]["stale_m5_symbols"])
        spy_state = next(row for row in status["webull_csvs"] if row["symbol"] == "SPY")
        self.assertEqual(spy_state["m5_freshness_status"], "stale")
        self.assertIn("m30_latest_bar_et", spy_state)

    def test_refresh_status_names_provider_previous_session_bar_blocker(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            now = datetime(2026, 5, 26, 10, 30, tzinfo=MARKET_TZ)
            previous_m5 = "2026-05-25T23:55:00Z"
            previous_m30 = "2026-05-25T23:30:00Z"
            source_rows = []
            for symbol in ["AAPL", "AMD", "META", "MSFT", "NVDA", "QQQ", "SPY", "TSLA"]:
                pd.DataFrame(
                    [{"datetime": previous_m30, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 100}]
                ).to_csv(output_dir / f"webull_{symbol}_M30_candles.csv", index=False)
                pd.DataFrame(
                    [{"datetime": previous_m5, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 100}]
                ).to_csv(output_dir / f"webull_{symbol}_M5_candles.csv", index=False)
                source_rows.append(
                    source_row(
                        provider="polygon",
                        symbol=symbol,
                        timeframe="M30",
                        candle_path=output_dir / f"webull_{symbol}_M30_candles.csv",
                        candles=pd.DataFrame([{"datetime": previous_m30}]),
                        start_date="2026-03-27",
                        end_date="2026-05-26",
                        status="ok",
                        refreshed_at=now,
                    )
                )
                source_rows.append(
                    source_row(
                        provider="polygon",
                        symbol=symbol,
                        timeframe="M5",
                        candle_path=output_dir / f"webull_{symbol}_M5_candles.csv",
                        candles=pd.DataFrame([{"datetime": previous_m5}]),
                        start_date="2026-03-27",
                        end_date="2026-05-26",
                        status="ok",
                        refreshed_at=now,
                    )
                )
            source_path = output_dir / "market_data_sources.csv"
            append_sources(source_path, source_rows)
            pd.DataFrame([scanner_row(scan_date="2026-05-25")]).to_csv(
                output_dir / "daily_paper_signal_scanner.csv",
                index=False,
            )
            market = {
                "now_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "today": "2026-05-26",
                "market_status": "market_open",
                "market_status_reason": "Regular market session is open.",
                "market_is_open": True,
                "next_market_session": "2026-05-26",
                "next_market_session_status": "Regular session",
            }
            with patch("reports.refresh_status.market_refresh_state", return_value=market):
                status = build_refresh_status(output_dir, source_csv=source_path)

        self.assertEqual(status["status"], "blocked_provider_previous_session_bars")
        self.assertEqual(status["provider_refresh"]["status"], "provider_previous_session_bars")
        self.assertIn("current-session intraday bars", status["next_action"])

    def test_system_state_verdict_uses_blocked_refresh_status_action(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            next_action = (
                "Keep paper import blocked. Try the refresh again later or use a data provider "
                "that returns current-session intraday bars."
            )
            (output_dir / "refresh_status.json").write_text(
                json.dumps(
                    {
                        "status": "blocked_provider_previous_session_bars",
                        "next_action": next_action,
                        "paper_import_blocked": True,
                    }
                ),
                encoding="utf-8",
            )

            state = build_system_state(output_dir=output_dir, paper_csv=output_dir / "paper.csv")

        self.assertEqual(state["readiness_verdict"], next_action)

    def test_dashboard_refresh_action_only_runs_status_report_commands(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            expected_state = {
                "project_phase": "research_and_paper_validation",
                "safety": {
                    "live_trading_enabled": False,
                    "broker_order_execution_enabled": False,
                    "real_money_ready": False,
                },
            }
            (logs_dir / "system_state.json").write_text(json.dumps(expected_state), encoding="utf-8")
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir), patch("run_app.subprocess.run") as runner:
                handler.run_refresh_status_action()

        commands = [call.args[0][1] for call in runner.call_args_list]
        self.assertEqual(
            commands,
            [
                "run_refresh_status.py",
                "run_phase_milestones.py",
                "run_historical_bucket_sync.py",
                "run_system_state.py",
                "run_provider_stability_audit.py",
                "run_paper_entry_packet.py",
                "run_paper_gate_v2.py",
                "run_options_chain_review.py",
                "run_options_contract_gate.py",
                "run_paper_validation_sample_import.py",
                "run_daily_ship_report.py",
                "run_system_state.py",
                "run_dashboard_data_preflight.py",
                "run_data_flow_sentinel.py",
                "run_controlled_universe_expansion.py",
                "run_probation_watch.py",
                "run_market_sprint_mode.py",
                "run_system_state.py",
            ],
        )
        self.assertEqual(responses[0][1], 200)
        self.assertIn("No market data was fetched", responses[0][0]["message"])

    def test_dashboard_state_endpoint_rebuilds_lightweight_state_only(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            expected_state = {
                "project_phase": "research_and_paper_validation",
                "safety": {
                    "live_trading_enabled": False,
                    "broker_order_execution_enabled": False,
                    "real_money_ready": False,
                },
            }
            (logs_dir / "system_state.json").write_text(json.dumps(expected_state), encoding="utf-8")
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir), patch("run_app.subprocess.run") as runner:
                handler.serve_system_state()

        commands = [call.args[0][1] for call in runner.call_args_list]
        self.assertEqual(
            commands,
            [
                "run_refresh_status.py",
                "run_phase_milestones.py",
                "run_historical_bucket_sync.py",
                "run_system_state.py",
                "run_provider_stability_audit.py",
                "run_paper_entry_packet.py",
                "run_paper_gate_v2.py",
                "run_options_chain_review.py",
                "run_options_contract_gate.py",
                "run_paper_validation_sample_import.py",
                "run_daily_ship_report.py",
                "run_system_state.py",
                "run_dashboard_data_preflight.py",
                "run_data_flow_sentinel.py",
                "run_controlled_universe_expansion.py",
                "run_probation_watch.py",
                "run_market_sprint_mode.py",
                "run_system_state.py",
            ],
        )
        self.assertEqual(responses[0][1], 200)
        self.assertFalse(responses[0][0]["safety"]["broker_order_execution_enabled"])

    def test_dashboard_state_endpoint_rebuilds_research_gate_when_inputs_exist(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            research_dir = logs_dir / "universe_expansion"
            research_dir.mkdir()
            (research_dir / "best_plus_market_watchlist_backtest_summary.csv").write_text("symbol\nQQQ\n", encoding="utf-8")
            expected_state = {
                "project_phase": "research_and_paper_validation",
                "safety": {
                    "live_trading_enabled": False,
                    "broker_order_execution_enabled": False,
                    "real_money_ready": False,
                },
            }
            (logs_dir / "system_state.json").write_text(json.dumps(expected_state), encoding="utf-8")
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir), patch("run_app.subprocess.run") as runner:
                handler.serve_system_state()

        commands = [call.args[0][1] for call in runner.call_args_list]
        self.assertEqual(
            commands,
            [
                "run_refresh_status.py",
                "run_research_confidence.py",
                "run_promotion_review.py",
                "run_phase_milestones.py",
                "run_historical_bucket_sync.py",
                "run_system_state.py",
                "run_provider_stability_audit.py",
                "run_paper_entry_packet.py",
                "run_paper_gate_v2.py",
                "run_options_chain_review.py",
                "run_options_contract_gate.py",
                "run_paper_validation_sample_import.py",
                "run_daily_ship_report.py",
                "run_system_state.py",
                "run_dashboard_data_preflight.py",
                "run_data_flow_sentinel.py",
                "run_controlled_universe_expansion.py",
                "run_probation_watch.py",
                "run_market_sprint_mode.py",
                "run_system_state.py",
            ],
        )
        self.assertIn(str(research_dir), runner.call_args_list[1].args[0])
        self.assertEqual(responses[0][1], 200)

    def test_dashboard_premarket_action_is_local_only(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            (logs_dir / "system_state.json").write_text(json.dumps({"premarket_verification": {"status": "passed"}}), encoding="utf-8")
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir), patch("run_app.subprocess.run") as runner:
                handler.run_premarket_check_action()

        command = runner.call_args.args[0]
        self.assertEqual(command[1:], ["run_premarket_verification.py"])
        self.assertNotIn("--probe-webull", command)
        self.assertIn("No market data was fetched", responses[0][0]["message"])

    def test_dashboard_webull_refresh_runs_research_workflow_only(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            (logs_dir / "system_state.json").write_text(
                json.dumps({"project_phase": "research_and_paper_validation"}),
                encoding="utf-8",
            )
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with (
                patch.object(run_app, "LOGS_DIR", logs_dir),
                patch("run_app.workflow_python", return_value="/tmp/webull-python"),
                patch("run_app.subprocess.run") as runner,
            ):
                handler.run_refresh_webull_data_action()

        command = runner.call_args.args[0]
        self.assertEqual(command, ["/tmp/webull-python", "run_current_candle_capture.py"])
        self.assertNotIn("--append-current-signals", command)
        self.assertNotIn("--data-provider", command)
        self.assertIn("no broker orders or real trades", responses[0][0]["message"])

    def test_dashboard_paper_session_actions_are_local_only(self) -> None:
        modes = {
            "preview": [],
            "confirm_entry": ["--confirm-local-paper"],
            "confirm_exits": ["--confirm-exits"],
        }
        for mode, expected_flags in modes.items():
            with self.subTest(mode=mode), TemporaryDirectory() as temporary:
                logs_dir = Path(temporary)
                (logs_dir / "system_state.json").write_text(json.dumps({"safety": {"broker_order_execution_enabled": False}}), encoding="utf-8")
                responses: list[tuple[dict, int]] = []
                handler = object.__new__(run_app.ProjectGwalaHandler)
                handler.send_json = lambda payload, status=200: responses.append((payload, status))

                with patch.object(run_app, "LOGS_DIR", logs_dir), patch("run_app.subprocess.run") as runner:
                    handler.run_paper_session_action(mode)

            command = runner.call_args.args[0]
            self.assertEqual(command[1:2], ["run_paper_session_cycle.py"])
            self.assertEqual(command[2:], expected_flags)
            self.assertNotIn("--probe-webull", command)
            self.assertIn("No broker orders", responses[0][0]["message"])

    def test_dashboard_open_trade_logger_lists_local_open_rows(self) -> None:
        with TemporaryDirectory() as temporary:
            paper_csv = Path(temporary) / "paper_trades.csv"
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-28",
                        "entry_time_et": "10:30",
                        "exit_time_et": "",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_status": "allowed",
                        "planned_entry": 100.0,
                        "planned_stop": 99.0,
                        "planned_target": 102.0,
                        "actual_entry": 100.0,
                        "actual_exit": "",
                        "shares": 1,
                        "vehicle": "options",
                        "risk_tier": "standard",
                        "planned_option_premium": 120.0,
                        "outcome_r": "",
                        "followed_plan": "",
                        "exit_reason": "",
                        "notes": "test open row",
                    }
                ]
            ).to_csv(paper_csv, index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "PAPER_CSV", paper_csv):
                handler.serve_open_paper_trades()

        payload, status = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["rows"][0]["vehicle"], "options")
        self.assertEqual(payload["rows"][0]["risk_tier"], "standard")

    def test_dashboard_trade_logger_updates_local_paper_row_only(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs_dir = root / "logs"
            logs_dir.mkdir()
            paper_csv = root / "paper_trades.csv"
            (logs_dir / "system_state.json").write_text(
                json.dumps({"safety": {"broker_order_execution_enabled": False}}),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-05-28",
                        "entry_time_et": "10:30",
                        "exit_time_et": "",
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_status": "allowed",
                        "planned_entry": 100.0,
                        "planned_stop": 99.0,
                        "planned_target": 102.0,
                        "actual_entry": 100.0,
                        "actual_exit": "",
                        "shares": "",
                        "vehicle": "",
                        "risk_tier": "",
                        "planned_option_premium": "",
                        "outcome_r": "",
                        "followed_plan": "",
                        "exit_reason": "",
                        "notes": "",
                    }
                ]
            ).to_csv(paper_csv, index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))
            handler.read_json_body = lambda: {
                "row": 1,
                "actual_entry": 100.0,
                "actual_exit": 101.0,
                "exit_time": "11:15",
                "shares": 1,
                "vehicle": "options",
                "risk_tier": "standard",
                "planned_option_premium": 120.0,
                "followed_plan": "yes",
                "exit_reason": "profit_target",
                "notes": "clean exit",
            }

            with (
                patch.object(run_app, "PAPER_CSV", paper_csv),
                patch.object(run_app, "LOGS_DIR", logs_dir),
                patch("run_app.subprocess.run") as runner,
            ):
                handler.run_update_paper_trade_action()

            updated = pd.read_csv(paper_csv)
            commands = [call.args[0][1] for call in runner.call_args_list]

        self.assertEqual(responses[0][1], 200)
        self.assertEqual(updated.iloc[0]["vehicle"], "options")
        self.assertEqual(updated.iloc[0]["risk_tier"], "standard")
        self.assertEqual(updated.iloc[0]["planned_option_premium"], 120.0)
        self.assertEqual(updated.iloc[0]["outcome_r"], 1.0)
        self.assertEqual(
            commands,
            [
                "run_paper_review.py",
                "run_refresh_status.py",
                "run_phase_milestones.py",
                "run_historical_bucket_sync.py",
                "run_system_state.py",
                "run_provider_stability_audit.py",
                "run_paper_entry_packet.py",
                "run_paper_gate_v2.py",
                "run_options_chain_review.py",
                "run_options_contract_gate.py",
                "run_paper_validation_sample_import.py",
                "run_daily_ship_report.py",
                "run_system_state.py",
                "run_dashboard_data_preflight.py",
                "run_data_flow_sentinel.py",
                "run_controlled_universe_expansion.py",
                "run_probation_watch.py",
                "run_market_sprint_mode.py",
                "run_system_state.py",
            ],
        )
        self.assertIn("No broker orders", responses[0][0]["message"])

    def test_dashboard_backtest_trade_log_serves_allowed_simulated_csv(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "entry_time": "2026-05-28 14:00:00+00:00",
                        "exit_time": "2026-05-28 19:55:00+00:00",
                        "quality_grade": "B",
                        "quality_score": 9,
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "exit_price": 101.0,
                        "r_result": 1.0,
                        "exit_reason": "target_hit",
                        "relative_volume": 1.4,
                        "room_to_resistance_r": 2.0,
                        "private_extra": "should not leak",
                    }
                ]
            ).to_csv(
                logs_dir / "QQQ_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv",
                index=False,
            )
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir):
                handler.serve_backtest_trades(
                    "file=QQQ_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv"
                    "&starting_equity=5000&risk_per_trade_pct=0.01"
                )

        payload, status = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["rows"][0]["symbol"], "QQQ")
        self.assertEqual(payload["rows"][0]["r_result"], 1.0)
        self.assertEqual(payload["account"]["starting_equity"], 5000.0)
        self.assertEqual(payload["account"]["ending_equity"], 5050.0)
        self.assertEqual(payload["rows"][0]["risk_dollars"], 50.0)
        self.assertEqual(payload["rows"][0]["pnl_dollars"], 50.0)
        self.assertEqual(payload["rows"][0]["account_equity_after"], 5050.0)
        self.assertNotIn("private_extra", payload["columns"])

    def test_dashboard_backtest_trade_log_rejects_unapproved_file(self) -> None:
        responses: list[tuple[dict, int]] = []
        handler = object.__new__(run_app.ProjectGwalaHandler)
        handler.send_json = lambda payload, status=200: responses.append((payload, status))

        handler.serve_backtest_trades("file=paper_trades.csv")

        self.assertEqual(responses[0][1], 404)

    def test_dashboard_backtest_portfolio_simulates_promoted_trade_logs(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            trade_file = "QQQ_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "promotion_decision": "paper_watch_candidate",
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "trade_log": trade_file,
                    }
                ]
            ).to_csv(logs_dir / "promotion_review.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "entry_time": "2026-05-28 14:00:00+00:00",
                        "exit_time": "2026-05-28 15:00:00+00:00",
                        "setup_type": "setup_a",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "exit_price": 101.0,
                        "r_result": 1.0,
                        "exit_reason": "target_hit",
                    },
                    {
                        "symbol": "QQQ",
                        "entry_time": "2026-05-28 16:00:00+00:00",
                        "exit_time": "2026-05-28 17:00:00+00:00",
                        "setup_type": "setup_a",
                        "entry": 102.0,
                        "stop": 101.0,
                        "target": 104.0,
                        "exit_price": 101.0,
                        "r_result": -1.0,
                        "exit_reason": "stop_loss",
                    },
                ]
            ).to_csv(logs_dir / trade_file, index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir):
                handler.serve_backtest_portfolio("starting_equity=5000&risk_per_trade_pct=0.01")

        payload, status = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(payload["account"]["source_candidates"], 1)
        self.assertEqual(payload["account"]["source_files"], 1)
        self.assertEqual(payload["account"]["ending_equity"], 4999.5)
        self.assertEqual(payload["account"]["timeline"]["last_entry"], "2026-05-28")
        self.assertEqual(payload["account"]["source_bucket_timelines"]["Promotion Review"]["last_entry"], "2026-05-28")
        self.assertEqual(payload["account"]["source_bucket_timelines"]["Promotion Review"]["row_count"], 2)
        self.assertEqual(payload["rows"][0]["source_candidate"], "current + no_vwap_exit")
        self.assertGreater(payload["rows"][0]["entry_sort_ms"], 0)
        self.assertLess(payload["rows"][0]["entry_sort_ms"], payload["rows"][1]["entry_sort_ms"])
        self.assertIn("entry_sort_ms", payload["columns"])
        self.assertNotIn("private_extra", payload["columns"])

    def test_dashboard_backtest_portfolio_returns_full_row_set_for_timeline_sync(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            trade_file = "QQQ_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "promotion_decision": "paper_watch_candidate",
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "trade_log": trade_file,
                    }
                ]
            ).to_csv(logs_dir / "promotion_review.csv", index=False)
            rows = []
            for index in range(505):
                entry = pd.Timestamp("2026-01-01 14:00:00+00:00") + pd.Timedelta(days=index)
                rows.append(
                    {
                        "symbol": "QQQ",
                        "entry_time": str(entry),
                        "exit_time": str(entry + pd.Timedelta(minutes=30)),
                        "setup_type": "setup_a",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "exit_price": 101.0,
                        "r_result": 0.25,
                        "exit_reason": "target_hit",
                    }
                )
            pd.DataFrame(rows).to_csv(logs_dir / trade_file, index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir):
                handler.serve_backtest_portfolio("starting_equity=5000&risk_per_trade_pct=0.005")

        payload, status = responses[0]
        latest_entry = max(pd.to_datetime(row["entry_time"], utc=True) for row in payload["rows"])
        self.assertEqual(status, 200)
        self.assertEqual(payload["row_count"], 505)
        self.assertEqual(len(payload["rows"]), 505)
        self.assertEqual(payload["account"]["timeline"]["last_entry"], latest_entry.date().isoformat())

    def test_dashboard_backtest_portfolio_includes_strategy_vault_trade_logs(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            promotion_trade_file = "QQQ_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "promotion_decision": "paper_watch_candidate",
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "trade_log": promotion_trade_file,
                    }
                ]
            ).to_csv(logs_dir / "promotion_review.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "entry_time": "2026-05-28 14:00:00+00:00",
                        "exit_time": "2026-05-28 15:00:00+00:00",
                        "setup_type": "setup_a",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "exit_price": 101.0,
                        "r_result": 1.0,
                        "exit_reason": "target_hit",
                    }
                ]
            ).to_csv(logs_dir / promotion_trade_file, index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "entry_time": "2026-06-04 14:00:00+00:00",
                        "exit_time": "2026-06-04 15:00:00+00:00",
                        "setup_type": "vwap_mean_reversion",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 101.5,
                        "exit_price": 101.0,
                        "r_result": 0.75,
                        "exit_reason": "end_of_day_exit",
                    }
                ]
            ).to_csv(logs_dir / "vwap_mean_reversion_trades.csv", index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir):
                handler.serve_backtest_portfolio("starting_equity=5000&risk_per_trade_pct=0.005")

        payload, status = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(payload["account"]["promotion_source_files"], 1)
        self.assertEqual(payload["account"]["strategy_vault_source_files"], 1)
        self.assertEqual(payload["account"]["timeline"]["last_entry"], "2026-06-04")
        self.assertEqual(payload["account"]["source_bucket_counts"]["Promotion Review"], 1)
        self.assertEqual(payload["account"]["source_bucket_counts"]["Strategy Vault Research"], 1)
        self.assertEqual(payload["account"]["evidence_tier_counts"]["promoted_research"], 1)
        self.assertEqual(payload["account"]["evidence_tier_counts"]["research_backtest"], 1)
        self.assertEqual(payload["account"]["source_bucket_timelines"]["Promotion Review"]["last_entry"], "2026-05-28")
        self.assertEqual(payload["account"]["source_bucket_timelines"]["Strategy Vault Research"]["last_entry"], "2026-06-04")
        self.assertEqual(
            payload["account"]["source_bucket_timelines"]["Strategy Vault Research"]["latest_trade_log"],
            "vwap_mean_reversion_trades.csv",
        )
        buckets = {row["source_bucket"] for row in payload["rows"]}
        self.assertIn("Promotion Review", buckets)
        self.assertIn("Strategy Vault Research", buckets)
        tiers = {row["evidence_tier"] for row in payload["rows"]}
        self.assertIn("promoted_research", tiers)
        self.assertIn("research_backtest", tiers)
        self.assertIn("source_display_label", payload["columns"])
        self.assertIn("source_disclaimer", payload["columns"])

    def test_dashboard_backtest_portfolio_includes_approved_playbook_rows(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            pd.DataFrame(columns=["promotion_decision", "trade_log"]).to_csv(
                logs_dir / "promotion_review.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "entry_time": "2026-06-09 14:00:00+00:00",
                        "exit_time": "2026-06-09 15:00:00+00:00",
                        "setup_type": "full_session",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "exit_price": 102.0,
                        "r_result": 2.0,
                        "exit_reason": "profit_target_5m",
                        "playbook_setup": "Setup C Full-Session Long",
                        "playbook_variant": "full_session",
                        "playbook_exit_profile": "no_vwap_exit",
                    }
                ]
            ).to_csv(logs_dir / "playbook_approved_trades.csv", index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir):
                handler.serve_backtest_portfolio("starting_equity=5000&risk_per_trade_pct=0.005")

        payload, status = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["account"]["approved_playbook_source_files"], 1)
        self.assertEqual(payload["account"]["promotion_source_files"], 0)
        self.assertEqual(payload["account"]["source_bucket_counts"]["Approved Playbook"], 1)
        self.assertEqual(payload["account"]["evidence_tier_counts"]["approved_historical"], 1)
        self.assertEqual(payload["rows"][0]["source_bucket"], "Approved Playbook")
        self.assertEqual(payload["rows"][0]["source_display_label"], "Approved Historical")
        self.assertEqual(payload["rows"][0]["evidence_tier"], "approved_historical")
        self.assertEqual(payload["rows"][0]["source_setup"], "Setup C Full-Session Long")
        self.assertEqual(payload["rows"][0]["source_candidate"], "full_session + no_vwap_exit")

    def test_dashboard_backtest_portfolio_supports_tiered_risk_model(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            trade_file = "QQQ_current_no_vwap_exit_webull_30m_entry_5m_exit_baseline_trades.csv"
            pd.DataFrame(
                [
                    {
                        "promotion_decision": "paper_watch_candidate",
                        "symbol": "QQQ",
                        "setup": "Setup A Long",
                        "candidate": "current + no_vwap_exit",
                        "readiness_score": 83,
                        "expectancy_r": 0.2,
                        "win_rate_pct": 60,
                        "max_drawdown_r": -2.0,
                        "trade_log": trade_file,
                    }
                ]
            ).to_csv(logs_dir / "promotion_review.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "symbol": "QQQ",
                        "entry_time": "2026-05-28 14:00:00+00:00",
                        "exit_time": "2026-05-28 15:00:00+00:00",
                        "setup_type": "setup_a",
                        "entry": 100.0,
                        "stop": 99.0,
                        "target": 102.0,
                        "exit_price": 101.0,
                        "r_result": 1.0,
                        "exit_reason": "target_hit",
                    }
                ]
            ).to_csv(logs_dir / trade_file, index=False)
            responses: list[tuple[dict, int]] = []
            handler = object.__new__(run_app.ProjectGwalaHandler)
            handler.send_json = lambda payload, status=200: responses.append((payload, status))

            with patch.object(run_app, "LOGS_DIR", logs_dir):
                handler.serve_backtest_portfolio("starting_equity=5000&risk_per_trade_pct=0.005&risk_model=tiered")

        payload, status = responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["account"]["risk_model"], "tiered")
        self.assertEqual(payload["account"]["ending_equity"], 5050.0)
        self.assertEqual(payload["account"]["max_risk_per_trade_pct"], 0.01)
        self.assertEqual(payload["rows"][0]["research_risk_tier"], "best_tier")
        self.assertEqual(payload["rows"][0]["applied_risk_per_trade_pct"], 0.01)

    def test_trading_workspace_exposes_chart_only_timeframes(self) -> None:
        with TemporaryDirectory() as temporary:
            logs_dir = Path(temporary)
            rows = [
                {"datetime": "2026-05-28T13:30:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
                {"datetime": "2026-05-28T13:35:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1200},
            ]
            for timeframe in ["M1", "M5", "M15", "M30", "M60"]:
                pd.DataFrame(rows).to_csv(logs_dir / f"webull_SPY_{timeframe}_candles.csv", index=False)
            daily_rows = [
                {"datetime": "2026-05-27T04:00:00Z", "open": 99, "high": 102, "low": 98, "close": 101, "volume": 5000},
                {"datetime": "2026-05-28T04:00:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 5500},
            ]
            pd.DataFrame(daily_rows).to_csv(logs_dir / "webull_SPY_D_candles.csv", index=False)

            payload = run_app.build_trading_workspace_data(logs_dir, "SPY", "M15")
            daily_payload = run_app.build_trading_workspace_data(logs_dir, "SPY", "D")

        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(payload["timeframe_role"], "chart-only review timeframe")
        self.assertIn("data_lag_minutes", payload)
        self.assertEqual(daily_payload["timeframe"], "D")
        self.assertEqual(daily_payload["timeframe_role"], "chart-only review timeframe")
        self.assertEqual(len(daily_payload["candles"]), 2)
        available = {row["timeframe"]: row for row in payload["available_timeframes"]}
        self.assertEqual(set(available), {"M1", "M5", "M15", "M30", "M60", "D"})
        self.assertEqual(available["M30"]["role"], "signal")
        self.assertEqual(available["M15"]["role"], "chart_only")

    def test_premarket_checks_require_disabled_safety_and_blocked_paper_import(self) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            env_path = output_dir / ".env"
            env_path.write_text("WEBULL_APP_KEY=test\nWEBULL_APP_SECRET=test\n", encoding="utf-8")
            (output_dir / "refresh_status.json").write_text(
                json.dumps({"paper_import_blocked": True, "status": "prep_only", "next_action": "Wait."}),
                encoding="utf-8",
            )
            (output_dir / "system_state.json").write_text(
                json.dumps(
                    {
                        "safety": {
                            "live_trading_enabled": False,
                            "broker_order_execution_enabled": False,
                            "real_money_ready": False,
                        }
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame([{"status": "ok", "session_coverage": "complete"}]).to_csv(
                output_dir / "candle_data_integrity.csv",
                index=False,
            )
            args = argparse.Namespace(output_dir=output_dir, env_file=env_path)
            checks, _ = build_checks(args, {"status": "not_requested", "detail": "Not requested."})

        status_by_area = {row["area"]: row["status"] for row in checks}
        self.assertEqual(status_by_area["Safety flags"], "pass")
        self.assertEqual(status_by_area["Paper import gate"], "pass")
        self.assertEqual(status_by_area["Candle integrity"], "pass")

    def test_premarket_report_renders_session_summary(self) -> None:
        summary = {
            "probe": {"status": "not_requested", "detail": "Not requested."},
            "refresh_status": {
                "paper_import_blocked": True,
                "market": {"next_market_session": "2026-05-26"},
            },
            "system_state": {
                "project_phase": "research_and_paper_validation",
                "data_freshness": {"data_status": "stale", "latest_scanner_session": "2026-05-22"},
                "scanner": {"current_candidate_count": 0},
            },
        }
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "premarket_verification.md"
            write_report(path, [{"area": "Safety flags", "status": "pass", "detail": "Disabled."}], summary)
            report = path.read_text(encoding="utf-8")

        self.assertIn("Pre-Market Verification", report)
        self.assertIn("Next-Session Operating Rule", report)
        self.assertNotIn("Tuesday Operating Rule", report)
        self.assertIn("research_and_paper_validation", report)
        self.assertIn("2026-05-26", report)
        self.assertIn(".venv/bin/python run_premarket_verification.py", report)

    def test_premarket_failure_status_fails_the_gate(self) -> None:
        self.assertTrue(has_failed_checks([{"status": "fail"}]))
        self.assertFalse(has_failed_checks([{"status": "pass"}, {"status": "not_requested"}]))

    def test_local_premarket_check_preserves_prior_probe_pass_without_request(self) -> None:
        args = argparse.Namespace(probe_webull=False)
        probe = run_webull_probe(args, {"probe": {"status": "pass"}})
        self.assertEqual(probe["status"], "previous_pass")

    def test_eod_executive_report_waits_for_final_m5_reconciliation(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            trading_day = date(2026, 7, 22)
            pd.DataFrame(
                [
                    {
                        "sample_date": trading_day.isoformat(),
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_time": "2026-07-22 11:00",
                        "sample_status": "ready_for_validation_sample",
                        "counts_toward_30": True,
                        "outcome": "",
                    }
                ]
            ).to_csv(data_dir / "paper_validation_samples.csv", index=False)
            pd.DataFrame(
                [
                    {"timestamp": "2026-07-22T19:50:00Z", "open": 1, "high": 1, "low": 1, "close": 1},
                ]
            ).to_csv(output_dir / "webull_SPY_M5_candles.csv", index=False)
            (output_dir / "production_heartbeat.json").write_text(
                json.dumps({"status": "GREEN", "checks": []}),
                encoding="utf-8",
            )
            (output_dir / "data_flow_sentinel.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

            def runner(*_args, **_kwargs):
                raise AssertionError("reconciliation commands must not run before final M5 data is present")

            payload = build_eod_payload(
                output_dir,
                data_dir,
                trading_day,
                datetime(2026, 7, 22, 16, 5, tzinfo=MARKET_TZ),
                runner=runner,
            )

        self.assertEqual(payload["report_status"], "PENDING_RECONCILIATION")
        self.assertEqual(payload["missing_final_m5_symbols"], ["SPY"])
        self.assertIn("No trade is labeled normally open overnight", payload["note"])

    def test_eod_executive_report_runs_final_accounting_sequence_when_m5_ready(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            trading_day = date(2026, 7, 22)
            samples_path = data_dir / "paper_validation_samples.csv"
            pd.DataFrame(
                [
                    {
                        "sample_date": trading_day.isoformat(),
                        "symbol": "SPY",
                        "setup": "Setup A Long",
                        "direction": "long",
                        "signal_time": "2026-07-22 11:00",
                        "sample_status": "ready_for_validation_sample",
                        "counts_toward_30": True,
                        "outcome": "",
                        "realized_r": "",
                    }
                ]
            ).to_csv(samples_path, index=False)
            pd.DataFrame(
                [
                    {"timestamp": "2026-07-22T19:55:00Z", "open": 1, "high": 1, "low": 1, "close": 1},
                ]
            ).to_csv(output_dir / "webull_SPY_M5_candles.csv", index=False)
            (output_dir / "production_heartbeat.json").write_text(json.dumps({"status": "GREEN"}), encoding="utf-8")
            (output_dir / "data_flow_sentinel.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            commands: list[str] = []

            def runner(command, **_kwargs):
                commands.append(" ".join(command))
                if "run_paper_validation_sample_import.py" in command:
                    frame = pd.read_csv(samples_path)
                    frame["outcome"] = frame["outcome"].astype("object")
                    frame.loc[0, "outcome"] = "win"
                    frame.loc[0, "realized_r"] = 2.0
                    frame.loc[0, "exit_time"] = "2026-07-22 15:55"
                    frame.loc[0, "exit_reason"] = "end_of_day_exit"
                    frame.to_csv(samples_path, index=False)
                return subprocess.CompletedProcess(command, 0, "", "")

            payload = build_eod_payload(
                output_dir,
                data_dir,
                trading_day,
                datetime(2026, 7, 22, 16, 10, tzinfo=MARKET_TZ),
                runner=runner,
            )

        self.assertEqual(payload["report_status"], "FINAL")
        flat = "\n".join(commands)
        self.assertIn("run_open_paper_monitor.py", flat)
        self.assertIn("run_paper_validation_sample_import.py", flat)
        self.assertIn("run_daily_ship_report.py", flat)
        self.assertIn("run_data_flow_sentinel.py", flat)
        self.assertEqual(payload["trading_activity"]["autonomous_paper_trades_closed"], 1)

    def test_eod_executive_report_includes_orb_shadow_only_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "logs"
            data_dir = root / "data"
            output_dir.mkdir()
            data_dir.mkdir()
            trading_day = date(2026, 7, 22)
            pd.DataFrame([], columns=["sample_date", "symbol", "sample_status"]).to_csv(
                data_dir / "paper_validation_samples.csv",
                index=False,
            )
            (output_dir / "production_heartbeat.json").write_text(json.dumps({"status": "GREEN"}), encoding="utf-8")
            (output_dir / "data_flow_sentinel.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            (output_dir / "opening_range_breakout_paper_watch_gate.json").write_text(
                json.dumps(
                    {
                        "strategy": "Opening Range Breakout",
                        "decision": "not_ready",
                        "blocked_count": 2,
                        "next_blocker": "Forward observations logged",
                        "checks": [
                            {"check": "Shadow samples logged", "status": "pass", "current": 10, "required": 10},
                            {"check": "Forward observations logged", "status": "blocked", "current": 7, "required": 10},
                            {"check": "Matured forward outcomes", "status": "blocked", "current": 1, "required": 5},
                        ],
                        "guardrail": (
                            "Manual paper-watch review only. No broker orders, no alerts, no live execution."
                        ),
                    }
                ),
                encoding="utf-8",
            )

            payload = build_eod_payload(
                output_dir,
                data_dir,
                trading_day,
                datetime(2026, 7, 22, 16, 10, tzinfo=MARKET_TZ),
                runner=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
            )
            markdown = eod_markdown(payload)

        self.assertEqual(payload["opening_range_breakout"]["collection_mode"], "shadow_only")
        self.assertEqual(payload["opening_range_breakout"]["forward_observations"]["remaining"], 3)
        self.assertIn("Opening Range Breakout Shadow Evidence", markdown)
        self.assertIn("Collection Mode: shadow_only", markdown)
        self.assertIn("Forward Observations: 7.0 / 10.0", markdown)
        self.assertIn("No broker orders", markdown)

    def test_executive_reports_are_deduped_and_delivery_is_logged(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "opening",
                "report_status": "FINAL",
                "trading_date": "2026-07-22",
                "generated_at_et": "2026-07-22T06:20:00-04:00",
                "report_version": "opening-v1.0",
                "production_status": "WATCH",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "production_readiness": "WATCH",
                "data_freshness": {},
                "scanner_readiness": [],
                "unresolved_open_trades": [],
                "blocking_issues": [],
            }
            _, md_path, created = save_report(payload, reports_dir)
            _, _, duplicate_created = save_report(payload, reports_dir)
            notifications: list[tuple[str, str, str]] = []
            result = deliver_report(
                payload,
                md_path,
                reports_dir,
                notifier=lambda title, message, subtitle="": notifications.append((title, subtitle, message)) is None or True,
            )
            delivery_log_exists = (reports_dir / "delivery_log.csv").exists()

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertTrue(result.success)
        self.assertEqual(notifications[0][0], "🟡 GWALA — WATCH")
        self.assertEqual(notifications[0][1], "Opening Executive Report")
        self.assertIn("Operator action: NONE", notifications[0][2])
        self.assertTrue(delivery_log_exists)

    def test_final_executive_report_delivers_exactly_once(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "eod",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T16:05:00-04:00",
                "report_version": "eod-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "trading_activity": {
                    "candidates_detected": 0,
                    "candidates_promoted": 0,
                    "contract_gate_passes": 0,
                    "autonomous_paper_trades_opened": 0,
                    "autonomous_paper_trades_closed": 0,
                    "open_paper_trades": 0,
                    "official_validation_trade_count": 0,
                },
                "completed_trades": [],
                "open_trades": [],
                "research_metrics": {
                    "running_win_rate": "N/A",
                    "average_r": "N/A",
                    "total_validation_trades": 0,
                    "opportunity_frequency": 0,
                    "strategy_breakdown": {},
                    "market_regime_breakdown": {},
                    "current_drawdown": "N/A",
                },
                "operational_health": [],
                "engineering_assessment": {
                    "production_defect": "NO",
                    "reporting_defect": "NO",
                    "exactly_one_improvement": "NO",
                    "highest_priority_task": "No engineering changes earned today.",
                },
                "research_assessment": {
                    "what_did_today_teach_us": "N/A",
                    "assumptions_gained_evidence": "N/A",
                    "assumptions_lost_evidence": "N/A",
                    "continue_to_observe": "N/A",
                },
                "tomorrow_readiness": {
                    "production_ready": "YES",
                    "reporting_ready": "YES",
                    "required_actions_before_market_open": "None",
                    "operational_concerns": "None",
                },
                "ceo_action_required": "None",
            }
            _, md_path, _ = save_report(payload, reports_dir)
            notifications: list[tuple[str, str, str]] = []
            notifier = lambda title, message, subtitle="": notifications.append((title, subtitle, message)) is None or True

            first = deliver_report(payload, md_path, reports_dir, notifier=notifier)
            second = deliver_report(payload, md_path, reports_dir, notifier=notifier)
            third = deliver_report(payload, md_path, reports_dir, notifier=notifier)
            delivery_rows = rows_from_csv(reports_dir / "delivery_log.csv")

        self.assertTrue(first.attempted)
        self.assertTrue(first.success)
        self.assertFalse(second.attempted)
        self.assertFalse(third.attempted)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(len(delivery_rows), 1)

    def test_final_executive_report_delivers_email_once_with_macos_backup(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "opening",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T09:20:00-04:00",
                "report_version": "opening-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "production_readiness": "GREEN",
                "data_freshness": {},
                "scanner_readiness": [],
                "unresolved_open_trades": [],
                "blocking_issues": [],
            }
            _, md_path, _ = save_report(payload, reports_dir)
            notifications: list[str] = []
            emails: list[Path] = []

            def email_sender(sent_payload: dict[str, object], sent_md: Path) -> DeliveryResult:
                emails.append(sent_md)
                return DeliveryResult(True, True, "email_smtp", "sent")

            with patch.dict(os.environ, {"GWALA_EMAIL_ENABLED": "true"}):
                first = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
                second = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
            delivery_rows = rows_from_csv(reports_dir / "delivery_log.csv")

        self.assertTrue(first.attempted)
        self.assertTrue(first.success)
        self.assertFalse(second.attempted)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(emails, [md_path])
        self.assertEqual([row["method"] for row in delivery_rows], ["macos_notification", "email_smtp"])

    def test_failed_email_retries_without_repeating_successful_macos_notification(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "opening",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T09:20:00-04:00",
                "report_version": "opening-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "production_readiness": "GREEN",
                "data_freshness": {},
                "scanner_readiness": [],
                "unresolved_open_trades": [],
                "blocking_issues": [],
            }
            _, md_path, _ = save_report(payload, reports_dir)
            notifications: list[str] = []
            email_results = [
                DeliveryResult(True, False, "email_smtp", "temporary smtp failure"),
                DeliveryResult(True, True, "email_smtp", "sent"),
            ]

            def email_sender(sent_payload: dict[str, object], sent_md: Path) -> DeliveryResult:
                return email_results.pop(0)

            with patch.dict(os.environ, {"GWALA_EMAIL_ENABLED": "true"}):
                first = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
                second = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
                third = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
            delivery_rows = rows_from_csv(reports_dir / "delivery_log.csv")

        self.assertFalse(first.success)
        self.assertTrue(second.attempted)
        self.assertTrue(second.success)
        self.assertFalse(third.attempted)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(
            [(row["method"], row["success"]) for row in delivery_rows],
            [("macos_notification", "True"), ("email_smtp", "False"), ("email_smtp", "True")],
        )

    def test_failed_macos_notification_retries_without_duplicate_email(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "opening",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T09:20:00-04:00",
                "report_version": "opening-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "production_readiness": "GREEN",
                "data_freshness": {},
                "scanner_readiness": [],
                "unresolved_open_trades": [],
                "blocking_issues": [],
            }
            _, md_path, _ = save_report(payload, reports_dir)
            notifications: list[str] = []
            emails: list[Path] = []

            def email_sender(sent_payload: dict[str, object], sent_md: Path) -> DeliveryResult:
                emails.append(sent_md)
                return DeliveryResult(True, True, "email_smtp", "sent")

            with patch.dict(os.environ, {"GWALA_EMAIL_ENABLED": "true"}):
                first = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None and False,
                    email_sender=email_sender,
                )
                second = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
                third = deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": notifications.append(title) is None or True,
                    email_sender=email_sender,
                )
            delivery_rows = rows_from_csv(reports_dir / "delivery_log.csv")

        self.assertFalse(first.success)
        self.assertTrue(second.success)
        self.assertFalse(third.attempted)
        self.assertEqual(len(notifications), 2)
        self.assertEqual(emails, [md_path])
        self.assertEqual(
            [(row["method"], row["success"]) for row in delivery_rows],
            [("macos_notification", "False"), ("email_smtp", "True"), ("macos_notification", "True")],
        )

    def test_email_delivery_failure_does_not_log_credentials(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "opening",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T09:20:00-04:00",
                "report_version": "opening-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "production_readiness": "GREEN",
                "data_freshness": {},
                "scanner_readiness": [],
                "unresolved_open_trades": [],
                "blocking_issues": [],
            }
            _, md_path, _ = save_report(payload, reports_dir)

            def email_sender(sent_payload: dict[str, object], sent_md: Path) -> DeliveryResult:
                raise RuntimeError("login failed for user@gmail.com with secret-app-password")

            with patch.dict(
                os.environ,
                {
                    "GWALA_EMAIL_ENABLED": "true",
                    "GWALA_SMTP_USERNAME": "user@gmail.com",
                    "GWALA_SMTP_PASSWORD": "secret-app-password",
                    "GWALA_EMAIL_TO": "ops@example.com",
                },
            ):
                deliver_report(
                    payload,
                    md_path,
                    reports_dir,
                    notifier=lambda title, message, subtitle="": True,
                    email_sender=email_sender,
                )
            delivery_rows = rows_from_csv(reports_dir / "delivery_log.csv")

        email_row = [row for row in delivery_rows if row["method"] == "email_smtp"][0]
        self.assertNotIn("secret-app-password", email_row["message"])
        self.assertNotIn("user@gmail.com", email_row["message"])
        self.assertIn("[redacted]", email_row["message"])

    def test_failed_final_report_delivery_retries_until_success(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "eod",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T16:05:00-04:00",
                "report_version": "eod-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "trading_activity": {
                    "candidates_detected": 0,
                    "candidates_promoted": 0,
                    "contract_gate_passes": 0,
                    "autonomous_paper_trades_opened": 0,
                    "autonomous_paper_trades_closed": 0,
                    "open_paper_trades": 0,
                    "official_validation_trade_count": 0,
                },
                "completed_trades": [],
                "open_trades": [],
                "research_metrics": {
                    "running_win_rate": "N/A",
                    "average_r": "N/A",
                    "total_validation_trades": 0,
                    "opportunity_frequency": 0,
                    "strategy_breakdown": {},
                    "market_regime_breakdown": {},
                    "current_drawdown": "N/A",
                },
                "operational_health": [],
                "engineering_assessment": {
                    "production_defect": "NO",
                    "reporting_defect": "NO",
                    "exactly_one_improvement": "NO",
                    "highest_priority_task": "No engineering changes earned today.",
                },
                "research_assessment": {
                    "what_did_today_teach_us": "N/A",
                    "assumptions_gained_evidence": "N/A",
                    "assumptions_lost_evidence": "N/A",
                    "continue_to_observe": "N/A",
                },
                "tomorrow_readiness": {
                    "production_ready": "YES",
                    "reporting_ready": "YES",
                    "required_actions_before_market_open": "None",
                    "operational_concerns": "None",
                },
                "ceo_action_required": "None",
            }
            _, md_path, _ = save_report(payload, reports_dir)
            attempts: list[str] = []

            first = deliver_report(
                payload,
                md_path,
                reports_dir,
                notifier=lambda title, message, subtitle="": attempts.append(title) is None and False,
            )
            second = deliver_report(
                payload,
                md_path,
                reports_dir,
                notifier=lambda title, message, subtitle="": attempts.append(title) is None or True,
            )
            third = deliver_report(
                payload,
                md_path,
                reports_dir,
                notifier=lambda title, message, subtitle="": attempts.append(title) is None or True,
            )
            delivery_rows = rows_from_csv(reports_dir / "delivery_log.csv")

        self.assertTrue(first.attempted)
        self.assertFalse(first.success)
        self.assertTrue(second.attempted)
        self.assertTrue(second.success)
        self.assertFalse(third.attempted)
        self.assertEqual(len(attempts), 2)
        self.assertEqual([row["success"] for row in delivery_rows], ["False", "True"])

    def test_new_final_report_artifact_can_deliver_after_prior_final_delivery(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "eod",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T16:05:00-04:00",
                "report_version": "eod-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "trading_activity": {
                    "candidates_detected": 0,
                    "candidates_promoted": 0,
                    "contract_gate_passes": 0,
                    "autonomous_paper_trades_opened": 0,
                    "autonomous_paper_trades_closed": 0,
                    "open_paper_trades": 0,
                    "official_validation_trade_count": 0,
                },
                "completed_trades": [],
                "open_trades": [],
                "research_metrics": {
                    "running_win_rate": "N/A",
                    "average_r": "N/A",
                    "total_validation_trades": 0,
                    "opportunity_frequency": 0,
                    "strategy_breakdown": {},
                    "market_regime_breakdown": {},
                    "current_drawdown": "N/A",
                },
                "operational_health": [],
                "engineering_assessment": {
                    "production_defect": "NO",
                    "reporting_defect": "NO",
                    "exactly_one_improvement": "NO",
                    "highest_priority_task": "No engineering changes earned today.",
                },
                "research_assessment": {
                    "what_did_today_teach_us": "N/A",
                    "assumptions_gained_evidence": "N/A",
                    "assumptions_lost_evidence": "N/A",
                    "continue_to_observe": "N/A",
                },
                "tomorrow_readiness": {
                    "production_ready": "YES",
                    "reporting_ready": "YES",
                    "required_actions_before_market_open": "None",
                    "operational_concerns": "None",
                },
                "ceo_action_required": "None",
            }
            _, first_md, _ = save_report(payload, reports_dir)
            changed_payload = dict(payload)
            changed_payload["generated_at_et"] = "2026-07-23T16:30:00-04:00"
            changed_payload["reporting_status"] = "WATCH"
            _, second_md, _ = save_report(changed_payload, reports_dir, force=True)
            notifications: list[str] = []
            notifier = lambda title, message, subtitle="": notifications.append(title) is None or True

            first = deliver_report(payload, first_md, reports_dir, notifier=notifier)
            second = deliver_report(changed_payload, second_md, reports_dir, notifier=notifier)

        self.assertNotEqual(first_md, second_md)
        self.assertTrue(first.attempted)
        self.assertTrue(second.attempted)
        self.assertEqual(len(notifications), 2)

    def test_pending_executive_report_delivery_is_not_final_deduped(self) -> None:
        with TemporaryDirectory() as temporary:
            reports_dir = Path(temporary) / "reports"
            payload = {
                "report_type": "eod",
                "report_status": "PENDING_RECONCILIATION",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T16:05:00-04:00",
                "report_version": "eod-v1.0",
                "production_status": "GREEN",
                "reporting_status": "WATCH",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "missing_final_m5_symbols": ["SPY"],
            }
            _, md_path, _ = save_report(payload, reports_dir)
            notifications: list[str] = []
            notifier = lambda title, message, subtitle="": notifications.append(title) is None or True

            first = deliver_report(payload, md_path, reports_dir, notifier=notifier)
            second = deliver_report(payload, md_path, reports_dir, notifier=notifier)

        self.assertTrue(first.attempted)
        self.assertTrue(second.attempted)
        self.assertEqual(len(notifications), 2)

    def test_executive_report_delivery_does_not_touch_trading_state_files(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports_dir = root / "reports"
            protected = [
                root / "paper_trades.csv",
                root / "paper_gate_v2.json",
                root / "options_contract_gate.json",
                root / "autonomous_a_tier_lifecycle.json",
                root / "paper_validation_samples.csv",
            ]
            for path in protected:
                path.write_text("sentinel", encoding="utf-8")
            payload = {
                "report_type": "opening",
                "report_status": "FINAL",
                "trading_date": "2026-07-23",
                "generated_at_et": "2026-07-23T09:20:00-04:00",
                "report_version": "opening-v1.0",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "business_impact": "NO",
                "operator_action_required": "NO",
                "production_readiness": "GREEN",
                "data_freshness": {},
                "scanner_readiness": [],
                "unresolved_open_trades": [],
                "blocking_issues": [],
            }
            _, md_path, _ = save_report(payload, reports_dir)

            deliver_report(payload, md_path, reports_dir, notifier=lambda title, message, subtitle="": True)
            contents = [path.read_text(encoding="utf-8") for path in protected]

        self.assertEqual(contents, ["sentinel", "sentinel", "sentinel", "sentinel", "sentinel"])

    def test_production_alert_uses_true_internal_severity_titles(self) -> None:
        self.assertEqual(internal_severity("YELLOW"), "WATCH")
        self.assertEqual(notification_title("WATCH"), "🟡 GWALA — WATCH")
        self.assertNotIn("DOWN", notification_title("WATCH"))
        self.assertNotIn("🔴", notification_title("WATCH"))

    def test_gwala_notification_format_covers_all_four_severities(self) -> None:
        expected = {
            "GREEN": "🟢 GWALA — GREEN",
            "WATCH": "🟡 GWALA — WATCH",
            "DEGRADED": "🟠 GWALA — DEGRADED",
            "DOWN": "🔴 GWALA — DOWN",
        }
        for severity, title in expected.items():
            notification = production_alert_notification(
                {
                    "internal_severity": severity,
                    "red_component": "TEST",
                    "reason": "Safe formatting test.",
                }
            )
            self.assertEqual(notification.title, title)
            self.assertEqual(notification.subtitle, "Production Alert")
            self.assertIn("Operator action:", notification.body)

    def test_opening_eod_and_production_alert_notification_formatting(self) -> None:
        opening = executive_report_notification(
            {
                "report_type": "opening",
                "report_status": "FINAL",
                "production_status": "GREEN",
                "reporting_status": "GREEN",
                "operator_action_required": "NO",
                "blocking_issues": [],
                "unresolved_open_trades": [],
            }
        )
        eod = executive_report_notification(
            {
                "report_type": "eod",
                "report_status": "PENDING_RECONCILIATION",
                "production_status": "GREEN",
                "reporting_status": "WATCH",
                "operator_action_required": "YES",
                "missing_final_m5_symbols": ["SPY"],
            }
        )
        alert = production_alert_notification(
            {
                "internal_severity": "DOWN",
                "red_component": "Scanner",
                "business_impact": "YES",
                "operator_action_required": "YES",
            }
        )

        self.assertEqual(opening.title, "🟢 GWALA — GREEN")
        self.assertEqual(opening.subtitle, "Opening Executive Report")
        self.assertIn("Production ready", opening.body)
        self.assertIn("Operator action: NONE", opening.body)
        self.assertEqual(eod.title, "🟡 GWALA — WATCH")
        self.assertEqual(eod.subtitle, "Pending Reconciliation")
        self.assertIn("pending final M5 reconciliation", eod.body)
        self.assertIn("Operator action: REVIEW", eod.body)
        self.assertEqual(alert.title, "🔴 GWALA — DOWN")
        self.assertEqual(alert.subtitle, "Production Alert")
        self.assertIn("Candidate generation has stopped.", alert.body)
        self.assertIn("Operator action: IMMEDIATE", alert.body)

    def test_executive_report_launchd_plists_run_report_only_commands(self) -> None:
        opening = build_opening_plist()
        eod = build_eod_plist()
        eod_schedule = {(entry["Weekday"], entry["Hour"], entry["Minute"]) for entry in eod["StartCalendarInterval"]}
        self.assertIn("run_executive_report.py", opening["ProgramArguments"][1])
        self.assertIn("--report-type", opening["ProgramArguments"])
        self.assertIn("opening", opening["ProgramArguments"])
        self.assertIn("eod", eod["ProgramArguments"])
        self.assertNotIn("run_current_candle_capture.py", " ".join(eod["ProgramArguments"]))
        self.assertEqual(
            {(weekday, 13, minute) for weekday in range(1, 6) for minute in [5, 10, 15, 20, 30]},
            eod_schedule,
        )


if __name__ == "__main__":
    unittest.main()
