"""Tests for the research-only Parameter Lab."""

from __future__ import annotations

import unittest

import pandas as pd

from config.filter_policy import PAPER_GATE_THRESHOLDS
from reports.parameter_lab import parameter_inventory, run_threshold_experiment


class ParameterLabTest(unittest.TestCase):
    """Focused tests for Parameter Lab behavior."""

    def test_inventory_tracks_paper_gate_thresholds(self) -> None:
        inventory = parameter_inventory()
        row = inventory[inventory["parameter_id"] == "paper_gate.a_min_check_score"].iloc[0]

        self.assertEqual(row["current_value"], PAPER_GATE_THRESHOLDS["a_min_check_score"])
        self.assertEqual(row["source"], "Engineering assumption")
        self.assertEqual(row["experiment_status"], "experiment_ready")

    def test_threshold_experiment_is_read_only_and_filters_candidates(self) -> None:
        candidates = pd.DataFrame(
            [
                {
                    "lane": "A",
                    "check_score": 0.70,
                    "quality_score": 6,
                    "relative_volume": 1.0,
                    "room_to_target_r": 1.0,
                    "r_result": -1.0,
                    "mae_r": 1.0,
                    "mfe_r": 0.2,
                },
                {
                    "lane": "A",
                    "check_score": 0.80,
                    "quality_score": 8,
                    "relative_volume": 1.3,
                    "room_to_target_r": 1.5,
                    "r_result": 2.0,
                    "mae_r": 0.4,
                    "mfe_r": 2.2,
                },
                {
                    "lane": "B",
                    "check_score": 0.90,
                    "quality_score": 8,
                    "relative_volume": 1.5,
                    "room_to_target_r": 2.0,
                    "r_result": 1.0,
                    "mae_r": 0.3,
                    "mfe_r": 1.4,
                },
            ]
        )

        result = run_threshold_experiment(candidates, "paper_gate.a_min_check_score", [0.70, 0.78])

        low = result[result["tested_value"] == 0.70].iloc[0]
        current = result[result["tested_value"] == 0.78].iloc[0]

        self.assertEqual(low["candidate_count"], 2)
        self.assertEqual(current["candidate_count"], 1)
        self.assertEqual(current["average_r"], 2.0)
        self.assertEqual(PAPER_GATE_THRESHOLDS["a_min_check_score"], 0.78)


if __name__ == "__main__":
    unittest.main()
