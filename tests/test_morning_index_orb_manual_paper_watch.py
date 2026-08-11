"""Tests for the promoted Morning SPY/QQQ Long ORB Manual Paper-Watch lane."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from run_morning_index_orb_manual_paper_watch import (
    CONTRACT_AUDIT_COLUMNS,
    LEDGER_COLUMNS,
    REVIEW_COLUMNS,
    build_payload,
    write_outputs,
)


MONDAY_MARKET = {"today": "2026-08-10", "market_is_open": True}


def observation(
    *,
    symbol: str = "QQQ",
    direction: str = "long",
    entry_time: str = "2026-08-10 10:15",
    scan_date: str = "2026-08-10",
    observed_at: str = "2026-08-10 10:16:00 EDT",
) -> dict[str, object]:
    return {
        "observed_at_et": observed_at,
        "scan_date": scan_date,
        "entry_time_et": entry_time,
        "symbol": symbol,
        "strategy": "opening_range_breakout",
        "direction": direction,
        "signal_column": "or_breakout_long_signal" if direction == "long" else "or_breakout_short_signal",
        "observation_status": "strategy_forward_observation",
        "observation_reason": "test",
        "planned_entry": 500.0,
        "planned_stop": 498.0,
        "planned_target": 502.4,
        "risk_per_share": 2.0,
        "reward_multiple": 1.2,
        "quality_score": 6,
        "quality_grade": "A",
        "relative_volume": 1.1,
        "trend_gap_pct": 0.001,
        "gap_pct": 0.0,
        "range_width_pct": 0.002,
        "close": 500.0,
        "vwap": 499.5,
        "ema_9": 499.8,
        "ema_21": 499.0,
    }


def refresh_rows() -> list[dict[str, object]]:
    return [
        {
            "symbol": symbol,
            "m30_latest_session": "2026-08-10",
            "m5_latest_session": "2026-08-10",
            "refresh_evidence_status": "current_session_in_progress",
        }
        for symbol in ["SPY", "QQQ"]
    ]


def approved_review(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "trading_date": "2026-08-10",
        "signal_timestamp_et": "2026-08-10 10:15",
        "symbol": "QQQ",
        "operator_review_status": "approved",
        "operator_review_reason": "manual paper-watch test approval",
        "reviewed_at_et": "2026-08-10 10:17:00 EDT",
    }


def clean_contract(*, symbol: str = "QQQ", entry_time: str = "10:15") -> dict[str, object]:
    return {
        "sample_date": "2026-08-10",
        "entry_time_et": entry_time,
        "symbol": symbol,
        "setup": "Morning Index ORB Long",
        "direction": "long",
        "strategy_id": "morning_index_orb_long",
        "sample_tier": "ORB_MANUAL",
        "contract_symbol": f"{symbol}260814C00500000",
        "option_type": "CALL",
        "expiration": "2026-08-14",
        "dte": 4,
        "strike": 500,
        "delta": 0.5,
        "bid": 3.00,
        "ask": 3.03,
        "mid": 3.015,
        "spread_pct": 0.01,
        "volume": 1000,
        "open_interest": 1000,
        "implied_volatility": 0.20,
        "premium": 3.03,
        "earnings_within_window": "False",
        "notes": "clean paper-watch contract",
    }


def candidate_id_for_qqq_1015() -> str:
    return "morning_index_orb_long|2026-08-10|QQQ|long|2026-08-10T10:15"


class MorningIndexOrbManualPaperWatchTest(unittest.TestCase):
    def test_promoted_lane_accepts_only_morning_spy_qqq_longs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observations = [
                observation(symbol="QQQ", direction="long", entry_time="2026-08-10 10:15"),
                observation(symbol="SPY", direction="long", entry_time="2026-08-10 11:30"),
                observation(symbol="QQQ", direction="short", entry_time="2026-08-10 10:15"),
                observation(symbol="SPY", direction="short", entry_time="2026-08-10 10:15"),
                observation(symbol="AMD", direction="long", entry_time="2026-08-10 10:15"),
                observation(symbol="TSLA", direction="long", entry_time="2026-08-10 10:15"),
                observation(symbol="SPY", direction="long", entry_time="2026-08-10 12:00"),
                observation(symbol="QQQ", direction="long", entry_time="2026-08-07 10:15", scan_date="2026-08-07"),
            ]
            observations_csv = root / "observations.csv"
            refresh_csv = root / "refresh.csv"
            pd.DataFrame(observations).to_csv(observations_csv, index=False)
            pd.DataFrame(refresh_rows()).to_csv(refresh_csv, index=False)

            payload = build_payload(
                output_dir=root,
                observations_csv=observations_csv,
                review_csv=root / "reviews.csv",
                contract_audit_csv=root / "contracts.csv",
                ledger_csv=root / "ledger.csv",
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )

            queue = pd.DataFrame(payload["queue_rows"])
            qualified = queue[queue["qualification_status"] == "qualified"]
            rejected = queue[queue["qualification_status"] == "not_promoted"]

            self.assertEqual(set(qualified["symbol"]), {"QQQ", "SPY"})
            self.assertEqual(len(qualified), 2)
            self.assertEqual(len(rejected), 6)
            self.assertIn("direction_not_long", " ".join(rejected["disqualification_reason"].astype(str)))
            self.assertIn("symbol_not_spy_or_qqq", " ".join(rejected["disqualification_reason"].astype(str)))
            self.assertIn("signal_at_or_after_12_et", " ".join(rejected["disqualification_reason"].astype(str)))
            self.assertIn("stale_or_not_current_session", " ".join(rejected["disqualification_reason"].astype(str)))

    def test_autonomous_paper_path_reaches_orb_ledger_without_review_or_vwap_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observations_csv = root / "observations.csv"
            outcomes_csv = root / "outcomes.csv"
            refresh_csv = root / "refresh.csv"
            contracts_csv = root / "contracts.csv"
            ledger_csv = root / "ledger.csv"
            vwap_samples = root / "paper_validation_samples.csv"

            pd.DataFrame([observation()]).to_csv(observations_csv, index=False)
            pd.DataFrame([{**observation(), "evaluation_status": "matured", "hypothetical_exit_time_et": "2026-08-10 11:00", "hypothetical_exit_price": 502.4, "hypothetical_r": 1.2, "hypothetical_exit_reason": "target_hit", "evaluation_note": "test"}]).to_csv(outcomes_csv, index=False)
            pd.DataFrame(refresh_rows()).to_csv(refresh_csv, index=False)
            pd.DataFrame([clean_contract()], columns=CONTRACT_AUDIT_COLUMNS).to_csv(contracts_csv, index=False)
            pd.DataFrame([{"counts_toward_30": True, "outcome_r": 0.5}]).to_csv(vwap_samples, index=False)

            before_vwap = pd.read_csv(vwap_samples).copy()
            payload = build_payload(
                output_dir=root,
                observations_csv=observations_csv,
                outcomes_csv=outcomes_csv,
                review_csv=root / "missing_reviews.csv",
                contract_audit_csv=contracts_csv,
                ledger_csv=ledger_csv,
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )
            write_outputs(root, payload, review_csv=root / "missing_reviews.csv", contract_audit_csv=contracts_csv, ledger_csv=ledger_csv)

            queue = pd.DataFrame(payload["queue_rows"])
            ledger = pd.DataFrame(payload["ledger_rows"], columns=LEDGER_COLUMNS)
            after_vwap = pd.read_csv(vwap_samples)

            self.assertEqual(len(queue), 1)
            self.assertEqual(queue.iloc[0]["qualification_status"], "qualified")
            self.assertEqual(queue.iloc[0]["operator_review_status"], "not_required")
            self.assertEqual(queue.iloc[0]["sizing_status"], "size_ok")
            self.assertEqual(queue.iloc[0]["contract_review_status"], "contract_pass")
            self.assertTrue(queue.iloc[0]["contract_gate_pass"])
            self.assertEqual(queue.iloc[0]["paper_entry_status"], "ready_for_paper_entry")
            self.assertEqual(len(ledger), 1)
            self.assertEqual(ledger.iloc[0]["status"], "completed")
            self.assertEqual(float(ledger.iloc[0]["outcome_r"]), 1.2)
            self.assertFalse(bool(ledger.iloc[0]["counts_toward_vwap_30"]))
            self.assertTrue(bool(ledger.iloc[0]["counts_toward_orb_20"]))
            pd.testing.assert_frame_equal(before_vwap, after_vwap)
            self.assertFalse(payload["safety_assertions"]["broker_orders_enabled"])
            self.assertFalse(payload["safety_assertions"]["real_money_execution_enabled"])

    def test_spy_and_qqq_autonomous_acceptance_and_broad_orb_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observations_csv = root / "observations.csv"
            refresh_csv = root / "refresh.csv"
            contracts_csv = root / "contracts.csv"
            pd.DataFrame(
                [
                    observation(symbol="QQQ", direction="long", entry_time="2026-08-10 10:15"),
                    observation(symbol="SPY", direction="long", entry_time="2026-08-10 11:30"),
                    observation(symbol="QQQ", direction="short", entry_time="2026-08-10 10:15"),
                    observation(symbol="SPY", direction="short", entry_time="2026-08-10 10:15"),
                    observation(symbol="AMD", direction="long", entry_time="2026-08-10 10:15"),
                    observation(symbol="TSLA", direction="long", entry_time="2026-08-10 10:15"),
                    observation(symbol="SPY", direction="long", entry_time="2026-08-10 12:00"),
                ]
            ).to_csv(observations_csv, index=False)
            pd.DataFrame(refresh_rows()).to_csv(refresh_csv, index=False)
            pd.DataFrame(
                [
                    clean_contract(symbol="QQQ", entry_time="10:15"),
                    clean_contract(symbol="SPY", entry_time="11:30"),
                ],
                columns=CONTRACT_AUDIT_COLUMNS,
            ).to_csv(contracts_csv, index=False)

            payload = build_payload(
                output_dir=root,
                observations_csv=observations_csv,
                review_csv=root / "missing_reviews.csv",
                contract_audit_csv=contracts_csv,
                ledger_csv=root / "ledger.csv",
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )

            queue = pd.DataFrame(payload["queue_rows"])
            ledger = pd.DataFrame(payload["ledger_rows"], columns=LEDGER_COLUMNS)
            qualified = queue[queue["qualification_status"] == "qualified"]
            rejected = queue[queue["qualification_status"] == "not_promoted"]

            self.assertEqual(len(qualified), 2)
            self.assertEqual(set(qualified["symbol"]), {"QQQ", "SPY"})
            self.assertTrue((qualified["sizing_status"] == "size_ok").all())
            self.assertTrue(qualified["contract_gate_pass"].map(bool).all())
            self.assertEqual(len(ledger), 2)
            self.assertEqual(set(ledger["symbol"]), {"QQQ", "SPY"})
            self.assertTrue((ledger["counts_toward_vwap_30"] == False).all())
            self.assertEqual(len(rejected), 5)
            self.assertEqual(payload["broad_orb_status"], "unchanged_shadow_forward")

    def test_blocks_missing_contract_stale_sizing_failure_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refresh_csv = root / "refresh.csv"
            pd.DataFrame(refresh_rows()).to_csv(refresh_csv, index=False)

            missing_contract_obs = root / "missing_contract_obs.csv"
            pd.DataFrame([observation()]).to_csv(missing_contract_obs, index=False)
            missing_contract_payload = build_payload(
                output_dir=root,
                observations_csv=missing_contract_obs,
                contract_audit_csv=root / "missing_contracts.csv",
                ledger_csv=root / "missing_contract_ledger.csv",
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )
            missing_row = pd.DataFrame(missing_contract_payload["queue_rows"]).iloc[0]
            self.assertEqual(missing_row["contract_review_status"], "missing_contract_review")
            self.assertEqual(len(pd.DataFrame(missing_contract_payload["ledger_rows"], columns=LEDGER_COLUMNS)), 0)
            self.assertIn("contract_data", {row["blocked_stage"] for row in missing_contract_payload["exception_rows"]})

            stale_obs = root / "stale_obs.csv"
            pd.DataFrame([observation(scan_date="2026-08-07", entry_time="2026-08-07 10:15")]).to_csv(stale_obs, index=False)
            stale_payload = build_payload(
                output_dir=root,
                observations_csv=stale_obs,
                contract_audit_csv=root / "contracts.csv",
                ledger_csv=root / "stale_ledger.csv",
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )
            stale_row = pd.DataFrame(stale_payload["queue_rows"]).iloc[0]
            self.assertEqual(stale_row["qualification_status"], "not_promoted")
            self.assertIn("stale_or_not_current_session", stale_row["disqualification_reason"])

            bad_size_obs = root / "bad_size_obs.csv"
            pd.DataFrame([{**observation(), "risk_per_share": 0.0}]).to_csv(bad_size_obs, index=False)
            bad_size_payload = build_payload(
                output_dir=root,
                observations_csv=bad_size_obs,
                contract_audit_csv=root / "contracts.csv",
                ledger_csv=root / "bad_size_ledger.csv",
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )
            bad_size_row = pd.DataFrame(bad_size_payload["queue_rows"]).iloc[0]
            self.assertEqual(bad_size_row["sizing_status"], "bad_risk")

            duplicate_obs = root / "duplicate_obs.csv"
            contracts_csv = root / "duplicate_contracts.csv"
            duplicate_ledger = root / "duplicate_ledger.csv"
            candidate_id = candidate_id_for_qqq_1015()
            pd.DataFrame([observation()]).to_csv(duplicate_obs, index=False)
            pd.DataFrame([clean_contract()], columns=CONTRACT_AUDIT_COLUMNS).to_csv(contracts_csv, index=False)
            pd.DataFrame([{**{column: "" for column in LEDGER_COLUMNS}, "candidate_id": candidate_id, "trade_id": candidate_id, "status": "open"}], columns=LEDGER_COLUMNS).to_csv(duplicate_ledger, index=False)
            duplicate_payload = build_payload(
                output_dir=root,
                observations_csv=duplicate_obs,
                contract_audit_csv=contracts_csv,
                ledger_csv=duplicate_ledger,
                refresh_audit_csv=refresh_csv,
                market=MONDAY_MARKET,
            )
            duplicate_row = pd.DataFrame(duplicate_payload["queue_rows"]).iloc[0]
            duplicate_result = pd.DataFrame(duplicate_payload["ledger_rows"], columns=LEDGER_COLUMNS)
            self.assertEqual(duplicate_row["paper_entry_status"], "duplicate_existing_orb_entry")
            self.assertEqual(len(duplicate_result), 1)


if __name__ == "__main__":
    unittest.main()
