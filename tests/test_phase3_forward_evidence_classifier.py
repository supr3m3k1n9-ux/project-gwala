"""Tests for Phase 3 forward evidence classification.

These tests use isolated fixture artifacts only. They do not mutate production
candidate, trade, validation, ORB, or Cohort 1 evidence.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from run_phase3_forward_evidence_classifier import (
    DATA_CONTRACT_VERSION,
    LEDGER_COLUMNS,
    ORB_ID,
    P3_H006_ID,
    QQQ_SETUP_B_ID,
    HypothesisSpec,
    build_payload,
    classify_rows,
    merge_idempotent,
    write_outputs,
)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fields or sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def candidate(**overrides: object) -> dict[str, object]:
    row = {
        "trade_date": "2026-08-18",
        "source_signal_et": "2026-08-18 10:00:00 EDT",
        "candidate_entry_et": "2026-08-18 10:00:00 EDT",
        "first_seen_at": "2026-08-18 10:01:00 EDT",
        "scan_timestamp": "2026-08-18 10:01:00 EDT",
        "symbol": "SPY",
        "setup": "Setup A Long",
        "direction": "long",
        "freshness_lane": "current_candle",
        "scanner_status": "allowed",
        "sizing_status": "size_ok",
        "sizing_reason": "",
        "paper_gate_status": "ready_for_validation_sample",
        "router_status": "paper_watch",
        "quality_grade": "A",
        "variant": "v1",
    }
    row.update(overrides)
    return row


class Phase3ForwardEvidenceClassifierTests(unittest.TestCase):
    def specs(self) -> dict[str, HypothesisSpec]:
        return {
            P3_H006_ID: HypothesisSpec(P3_H006_ID, "SPY Opening-Hour Setup A Long", "vwap_ema_trend_continuation", "2026-08-17T23:00:00+00:00"),
            QQQ_SETUP_B_ID: HypothesisSpec(QQQ_SETUP_B_ID, "QQQ Setup B Short / late-day behavior", "vwap_ema_trend_continuation", "2026-08-17T23:00:00+00:00"),
        }

    def test_p3_h006_post_adoption_opening_hour_classifies(self) -> None:
        rows = classify_rows(
            candidate_rows=[candidate()],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
            classification_timestamp="2026-08-18 12:00:00 EDT",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hypothesis_id"], P3_H006_ID)
        self.assertEqual(rows[0]["time_bucket"], "opening_hour")
        self.assertTrue(rows[0]["counts_as_forward_observation"])
        self.assertEqual(rows[0]["data_contract_version"], DATA_CONTRACT_VERSION)

    def test_pre_adoption_candidate_is_excluded_from_forward_confirmation(self) -> None:
        rows = classify_rows(
            candidate_rows=[candidate(trade_date="2026-08-17", first_seen_at="2026-08-17 10:01:00 EDT", source_signal_et="2026-08-17 10:00:00 EDT")],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        self.assertEqual(rows, [])

    def test_historical_seen_rows_do_not_enter_forward_ledger(self) -> None:
        rows = classify_rows(
            candidate_rows=[
                candidate(trade_date="2026-07-01", first_seen_at="2026-07-01 10:01:00 EDT", source_signal_et="2026-07-01 10:00:00 EDT"),
                candidate(trade_date="2026-08-18", first_seen_at="2026-08-18 10:01:00 EDT", source_signal_et="2026-08-18 10:00:00 EDT"),
            ],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_date"] if "trade_date" in rows[0] else rows[0]["entry_timestamp_et"][:10], "2026-08-18")

    def test_qqq_setup_b_late_day_classifies(self) -> None:
        rows = classify_rows(
            candidate_rows=[
                candidate(
                    symbol="QQQ",
                    setup="Setup B Short",
                    direction="short",
                    source_signal_et="2026-08-18 15:00:00 EDT",
                    candidate_entry_et="2026-08-18 15:00:00 EDT",
                    first_seen_at="2026-08-18 15:01:00 EDT",
                )
            ],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hypothesis_id"], QQQ_SETUP_B_ID)
        self.assertEqual(rows[0]["time_bucket"], "late_day")

    def test_qqq_setup_b_non_late_day_excluded(self) -> None:
        rows = classify_rows(
            candidate_rows=[candidate(symbol="QQQ", setup="Setup B Short", direction="short")],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        self.assertEqual(rows, [])

    def test_rerun_dedupes_by_forward_evidence_id(self) -> None:
        current = classify_rows(
            candidate_rows=[candidate()],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        merged = merge_idempotent(current, current)
        self.assertEqual(len(merged), 1)

    def test_outcome_reconciles_from_authoritative_validation_ledger(self) -> None:
        sample = {
            "sample_date": "2026-08-18",
            "entry_time_et": "10:00",
            "symbol": "SPY",
            "setup": "Setup A Long",
            "direction": "long",
            "sample_status": "completed",
            "outcome_r": "1.25",
            "exit_time_et": "2026-08-18 11:15:00 EDT",
            "invalid_for_validation": "false",
        }
        rows = classify_rows(
            candidate_rows=[candidate()],
            sample_rows=[sample],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        self.assertEqual(rows[0]["outcome_state"], "completed")
        self.assertEqual(rows[0]["outcome_r"], "1.25")
        self.assertTrue(rows[0]["counts_as_forward_completed_trade"])

    def test_rejected_or_gated_candidates_remain_visible_with_reason(self) -> None:
        rows = classify_rows(
            candidate_rows=[candidate(sizing_status="size_blocked", sizing_reason="not_current_session", paper_gate_status="blocked")],
            sample_rows=[],
            event_rows=[],
            specs=self.specs(),
            source_artifact=Path("data/candidate_window_ledger.csv"),
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["counts_as_forward_observation"])
        self.assertFalse(rows[0]["counts_as_forward_completed_trade"])
        self.assertIn("not_current_session", rows[0]["exclusion_reason"])
        self.assertIn("blocked", rows[0]["exclusion_reason"])

    def test_dependence_duplicates_count_one_independent_opportunity(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            candidate_csv = root / "candidate_window_ledger.csv"
            samples_csv = root / "paper_validation_samples.csv"
            events_csv = root / "candidate_ledger_event_state.csv"
            orb_csv = root / "morning_index_orb_manual_paper_trades.csv"
            logs_dir = root / "logs"
            write_csv(
                candidate_csv,
                [
                    candidate(candidate_entry_et="2026-08-18 10:00:00 EDT"),
                    candidate(candidate_entry_et="2026-08-18 10:05:00 EDT"),
                ],
            )
            write_csv(samples_csv, [])
            write_csv(events_csv, [])
            write_csv(orb_csv, [])

            payload = build_payload(
                output_dir=logs_dir,
                candidate_ledger_csv=candidate_csv,
                samples_csv=samples_csv,
                event_state_csv=events_csv,
                orb_ledger_csv=orb_csv,
                orb_status_json=logs_dir / "missing.json",
                phase3_forward_ledger_csv=root / "phase3_forward_evidence.csv",
                logs_dir=logs_dir,
            )

            p3 = next(row for row in payload["scorecard"] if row["hypothesis_id"] == P3_H006_ID)
            self.assertEqual(p3["raw_forward_observations"], 2)
            self.assertEqual(p3["independent_opportunities"], 1)

    def test_orb_authority_is_summarized_but_not_replaced(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            candidate_csv = root / "candidate_window_ledger.csv"
            samples_csv = root / "paper_validation_samples.csv"
            events_csv = root / "candidate_ledger_event_state.csv"
            orb_csv = root / "morning_index_orb_manual_paper_trades.csv"
            orb_status = root / "logs" / "morning_index_orb_manual_paper_watch.json"
            write_csv(candidate_csv, [])
            write_csv(samples_csv, [])
            write_csv(events_csv, [])
            write_csv(orb_csv, [{"status": "completed", "outcome_r": "0.4"}])
            orb_status.parent.mkdir(parents=True)
            orb_status.write_text(json.dumps({"manual_paper_watch_status": "READY", "metrics": {"completed_count": 1, "open_count": 0, "qualified_today": 1}}), encoding="utf-8")

            payload = build_payload(
                output_dir=orb_status.parent,
                candidate_ledger_csv=candidate_csv,
                samples_csv=samples_csv,
                event_state_csv=events_csv,
                orb_ledger_csv=orb_csv,
                orb_status_json=orb_status,
                phase3_forward_ledger_csv=root / "phase3_forward_evidence.csv",
                logs_dir=orb_status.parent,
            )

            orb = next(row for row in payload["scorecard"] if row["hypothesis_id"] == ORB_ID)
            self.assertEqual(orb["authority"], str(orb_csv))
            self.assertEqual(orb["completed_outcomes"], 1)
            self.assertEqual(payload["ledger_rows"], [])

    def test_write_error_failure_is_watch_not_production_stopping(self) -> None:
        from run_phase3_forward_evidence_classifier import write_error

        with TemporaryDirectory() as raw:
            root = Path(raw)
            write_error(root / "logs", root / "data" / "phase3_forward_evidence.csv", RuntimeError("fixture failure"))
            payload = json.loads((root / "logs" / "phase3_forward_evidence_classifier.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["status"], "WATCH")
            self.assertIn("must not stop production workflow", payload["guardrail"])

    def test_write_outputs_preserves_existing_ledger_on_rerun(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            ledger_csv = root / "phase3_forward_evidence.csv"
            payload = {
                "generated_at_et": "2026-08-18 12:00:00 EDT",
                "status": "PASS",
                "ledger_csv": str(ledger_csv),
                "scorecard": [{"hypothesis_id": P3_H006_ID, "raw_forward_observations": 1}],
                "hypothesis_boundaries": {P3_H006_ID: "2026-08-17T23:00:00+00:00", QQQ_SETUP_B_ID: "2026-08-17T23:00:00+00:00"},
                "pre_hypothesis_contamination": 0,
                "pre_hypothesis_matching_candidates_seen_but_excluded": 117,
                "duplicate_forward_records": 0,
                "cohort_1": {"observations": 30, "independent_opportunities": 21},
                "production_isolated": True,
                "ledger_rows": [
                    {
                        **{column: "" for column in LEDGER_COLUMNS},
                        "forward_evidence_id": "P3-H006|fixture",
                        "hypothesis_id": P3_H006_ID,
                    }
                ],
            }

            write_outputs(root / "logs", dict(payload), ledger_csv)
            write_outputs(root / "logs", dict(payload), ledger_csv)

            self.assertEqual(len(read_csv(ledger_csv)), 1)

    def test_cohort_1_defaults_remain_30_and_21(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            candidate_csv = root / "candidate_window_ledger.csv"
            samples_csv = root / "paper_validation_samples.csv"
            events_csv = root / "candidate_ledger_event_state.csv"
            orb_csv = root / "morning_index_orb_manual_paper_trades.csv"
            write_csv(candidate_csv, [])
            write_csv(samples_csv, [])
            write_csv(events_csv, [])
            write_csv(orb_csv, [])

            payload = build_payload(
                output_dir=root / "logs",
                candidate_ledger_csv=candidate_csv,
                samples_csv=samples_csv,
                event_state_csv=events_csv,
                orb_ledger_csv=orb_csv,
                orb_status_json=root / "logs" / "missing.json",
                phase3_forward_ledger_csv=root / "phase3_forward_evidence.csv",
                logs_dir=root / "logs",
            )

            self.assertEqual(payload["cohort_1"]["observations"], 30)
            self.assertEqual(payload["cohort_1"]["independent_opportunities"], 21)

    def test_async_lane_runs_classifier_after_orb_paper_watch(self) -> None:
        source = Path("run_market_async_lane.py").read_text(encoding="utf-8")

        orb_index = source.index("run_morning_index_orb_manual_paper_watch.py")
        classifier_index = source.index("run_phase3_forward_evidence_classifier.py")
        refresh_index = source.index("run_refresh_status.py")

        self.assertLess(orb_index, classifier_index)
        self.assertLess(classifier_index, refresh_index)


if __name__ == "__main__":
    unittest.main()
