"""Safety and readiness tests for the paper-validation workflow."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
import json
import os
import plistlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.settings import STRATEGY
from execution.paper_trader import build_local_paper_orders, eligible_sizing_rows, orders_to_open_paper_trades
from reports.refresh_status import build_refresh_status
from reports.system_state import (
    build_system_state,
    current_candidate_state,
    data_freshness_state,
    premarket_verification_state,
    risk_guard_state,
)
import run_app
from run_autonomous_paper_workflow import choose_action, commands_for_action, sleep_after_action
from run_candidate_alerts import build_alert_rows
from run_controlled_variant_review import build_controlled_review
from run_daily_workflow import enforce_manual_paper_import, refresh_data
from run_daily_automation_timeline import build_timeline as build_automation_timeline
from run_data_integrity import inspect_file
from run_daily_scanner import scanner_freshness_frame, write_import_template
from run_forward_observations import OBSERVATION_COLUMNS, dedupe, scanner_is_fresh_for_open_market, scanner_to_observations
from run_candidate_aging import build_aging as build_candidate_aging
from run_candidate_aging import bucket_summary as candidate_aging_bucket_summary
from run_forward_evidence import build_evidence as build_forward_evidence
from run_forward_sample_queue import build_queue as build_forward_sample_queue
from run_forward_sample_queue import queue_payload as forward_sample_queue_payload
from run_holdout_validation import add_entry_dates, stability_summary, validation_windows
from run_import_candles_csv import import_candles, normalize_external_candles
from run_intraday_loop import is_market_open, session_has_ended
from run_morning_watchdog import build_watchdog as build_morning_watchdog
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
from run_open_paper_monitor import apply_updates, build_updates
from run_opening_range_relaxation_review import build_review as build_opening_range_review
from run_paper_import import paper_import_is_allowed
from run_paper_session_cycle import build_commands as build_paper_session_commands
from run_post_scan_digest import build_digest as build_post_scan_digest
from run_position_sizer import apply_session_gate, build_sizing, realized_r_from_paper_log, risk_status
from run_premarket_plan import candidate_table as plan_candidate_table
from run_premarket_verification import build_checks, has_failed_checks, run_webull_probe, write_report
from run_paper_activation_rules import build_activation_payload
from run_pre_entry_review import review_row as pre_entry_review_row
from run_promotion_review import build_review as build_promotion_review
from run_research_confidence import build_rows as build_research_confidence_rows, readiness_status
from run_regime_review import build_regime_review
from run_shadow_samples import shadow_status_for_row
from run_strategy_evidence_accumulator import summarize_lane
from run_strategy_overlap_audit import build_audit_rows, priority_plan
from run_strategy_vault import build_selector
from run_vwap_mean_reversion_shadow_samples import sample_row as mean_reversion_sample_row
from run_walk_forward_review import build_walk_forward_review
from run_trade_checklist import current_candidates as checklist_candidates
from run_webull_watchlist import fetch_chart_only_timeframes, write_candidate_selection_report
from strategies.gap_fill_fade import add_gap_fill_fade_signals
from strategies.opening_range_breakout import add_opening_range_breakout_signals
from strategies.trend_pullback_continuation import add_trend_pullback_continuation_signals
from strategies.vwap_reclaim_reject import add_vwap_reclaim_reject_signals


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

        self.assertIn("run_daily_workflow.py", command_text)
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

        self.assertIn("--auto-confirm-paper-exits", command_text)
        self.assertNotIn("--append-current-signals", command_text)
        self.assertNotIn("run_paper_import.py", command_text)

    def test_autonomous_launch_agent_starts_weekday_market_loop(self) -> None:
        plist_path = Path("launchd/com.project-gwala.autonomous-paper.plist")
        with plist_path.open("rb") as file:
            plist = plistlib.load(file)

        arguments = plist["ProgramArguments"]
        entries = plist["StartCalendarInterval"]
        schedule = {(entry["Weekday"], entry["Hour"], entry["Minute"]) for entry in entries}

        self.assertNotIn("--once", arguments)
        self.assertEqual(plist.get("RunAtLoad"), False)
        self.assertEqual(len(entries), 5)
        self.assertIn((1, 6, 15), schedule)
        self.assertIn((2, 6, 15), schedule)
        self.assertIn((3, 6, 15), schedule)
        self.assertIn((4, 6, 15), schedule)
        self.assertIn((5, 6, 15), schedule)
        self.assertNotIn((1, 6, 30), schedule)

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

            timeline = build_automation_timeline(
                output_dir,
                moment=datetime(2026, 5, 26, 10, 0, tzinfo=MARKET_TZ),
            )

        self.assertEqual(timeline["status"], "warn")
        self.assertEqual(timeline["recent_commands"][0]["command"], "run_daily_workflow.py")
        self.assertTrue(timeline["recent_failures"])


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

    def test_daily_workflow_fetches_once_then_reuses_csv_for_setup_b(self) -> None:
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
        )
        commands: list[list[str]] = []

        with patch("run_daily_workflow.run_step", side_effect=commands.append):
            refresh_data("python", args)

        self.assertNotIn("--reuse-csv", commands[0])
        self.assertIn("best_plus_market", commands[0])
        self.assertIn("--reuse-csv", commands[1])
        self.assertIn("setup_b", commands[1])
        self.assertIn("--chart-m1-count", commands[0])
        self.assertIn("--chart-m15-count", commands[0])
        self.assertIn("--chart-m60-count", commands[0])
        self.assertIn("--chart-d-count", commands[0])

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
            [step for step, _ in preview_commands][:7],
            [
                "Candidate alerts",
                "Pre-entry review",
                "Local paper execution",
                "Open paper monitor",
                "Exit audit",
                "Paper review",
                "Forward sample queue",
            ],
        )
        self.assertEqual(preview_commands[7][0], "No-trade analysis")
        self.assertEqual(preview_commands[8][0], "Shadow samples")
        self.assertEqual(preview_commands[9][0], "Candidate aging")
        self.assertEqual(preview_commands[10][0], "Forward evidence")

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
            for symbol in ["AAPL", "AMD", "NVDA", "QQQ", "SPY", "TSLA"]:
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
            for symbol in ["AAPL", "AMD", "NVDA", "QQQ", "SPY", "TSLA"]:
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
            stale_bar = (now - timedelta(minutes=20)).isoformat()
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
        self.assertEqual(commands, ["run_refresh_status.py", "run_system_state.py"])
        self.assertEqual(responses[0][1], 200)
        self.assertIn("No market data was fetched", responses[0][0]["message"])

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
        self.assertEqual(command, ["/tmp/webull-python", "run_daily_workflow.py", "--refresh-data"])
        self.assertNotIn("--append-current-signals", command)
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
        self.assertEqual(commands, ["run_paper_review.py", "run_refresh_status.py", "run_system_state.py"])
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
        self.assertEqual(payload["rows"][0]["source_candidate"], "current + no_vwap_exit")
        self.assertNotIn("private_extra", payload["columns"])

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


if __name__ == "__main__":
    unittest.main()
