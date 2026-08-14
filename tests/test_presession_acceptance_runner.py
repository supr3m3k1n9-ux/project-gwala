"""Security tests for the scoped Linux pre-session acceptance runner."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "deploy" / "linux" / "run_presession_acceptance.sh"


class PreSessionAcceptanceRunnerTests(unittest.TestCase):
    def runner_text(self) -> str:
        return RUNNER.read_text(encoding="utf-8")

    def test_runner_rejects_arbitrary_arguments_before_privileged_work(self) -> None:
        completed = subprocess.run(
            ["bash", str(RUNNER), "python", "-c", "print('bad')"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 64)
        self.assertIn("does not accept arguments", completed.stderr)
        self.assertNotIn("bad", completed.stdout)

    def test_runner_help_is_safe_without_host_paths(self) -> None:
        completed = subprocess.run(["bash", str(RUNNER), "--help"], capture_output=True, text=True)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("fixed, production-safe acceptance suite", completed.stdout)

    def test_runner_is_not_group_or_world_writable_in_repository(self) -> None:
        mode = RUNNER.stat().st_mode

        self.assertFalse(mode & 0o020, oct(mode))
        self.assertFalse(mode & 0o002, oct(mode))

    def test_runner_documents_root_owned_install_boundary(self) -> None:
        text = self.runner_text()

        self.assertIn("roy ALL=(root) NOPASSWD: /srv/projects/gwala/app/deploy/linux/run_presession_acceptance.sh", text)
        self.assertIn("No arbitrary command, Docker, Python, or journal arguments are accepted.", text)

    def test_runner_does_not_forward_arbitrary_arguments(self) -> None:
        text = self.runner_text()

        self.assertNotIn("eval ", text)
        self.assertNotIn("bash -c", text)
        self.assertNotIn("sh -c", text)
        self.assertIn('if [[ "$#" -ne 0 ]]; then', text)
        self.assertIn("exit 64", text)
        self.assertNotIn("docker compose \"$@\"", text)
        self.assertNotIn("python \"$@\"", text)

    def test_docker_invocations_are_fixed_to_compose_gwala_service(self) -> None:
        text = self.runner_text()

        self.assertIn('docker compose -f "$COMPOSE_FILE" run --no-deps gwala', text)
        self.assertNotIn("docker run", text)
        self.assertNotIn("/var/run/docker.sock", text)

    def test_runner_prints_visible_per_check_progress(self) -> None:
        text = self.runner_text()

        self.assertIn("START %s (timeout %ss)", text)
        self.assertIn('print_result "$area" "PASS"', text)
        self.assertIn('print_result "$area" "WATCH"', text)
        self.assertIn('print_result "$area" "FAIL"', text)

    def test_runner_records_check_duration_and_timeout_impact(self) -> None:
        text = self.runner_text()

        self.assertIn("area\\tstatus\\tduration_seconds\\treason", text)
        self.assertIn("WHOLE_RUN_TIMEOUT_SECONDS=1800", text)
        self.assertIn("TIMEOUT after ${duration}s; impact: acceptance cannot prove clean-session readiness", text)
        self.assertIn("TIMEOUT: whole-run timeout reached before check could start", text)

    def test_runner_cleans_only_transient_compose_run_containers(self) -> None:
        text = self.runner_text()

        self.assertIn("cleanup_acceptance_containers", text)
        self.assertIn('docker ps -aq --filter "name=gwala-gwala-run-"', text)
        self.assertIn("docker rm -f $ids", text)
        self.assertNotIn("docker compose down", text)
        self.assertNotIn("docker rm -f gwala-gwala-1", text)

    def test_python_invocations_are_fixed_acceptance_selectors(self) -> None:
        text = self.runner_text()

        self.assertIn("tests.test_workflow_safety.DataFreshnessIntegrityAuditorTests", text)
        self.assertIn("tests.test_runtime_paths.RuntimePathTests", text)
        self.assertIn("tests.test_continuous_assurance.ContinuousAssuranceTests", text)
        self.assertNotIn("python $", text)
        self.assertNotIn("python3 $", text)

    def test_vps_verifier_status_is_parsed_not_only_return_code(self) -> None:
        text = self.runner_text()

        self.assertIn("VPS PRODUCTION READINESS: PASS", text)
        self.assertIn("VPS PRODUCTION READINESS: WATCH", text)
        self.assertIn("VPS PRODUCTION READINESS: FAIL", text)

    def test_journal_units_are_allowlisted(self) -> None:
        text = self.runner_text()
        allowed = {
            "project-gwala-autonomous-paper.service",
            "project-gwala-market-async-lane.service",
            "project-gwala-production-alert.service",
            "project-gwala-dashboard.service",
            "project-gwala-opening-executive-report.service",
            "project-gwala-eod-executive-report.service",
        }

        for unit in allowed:
            self.assertIn(unit, text)
        self.assertIn('journalctl -u "$unit"', text)
        self.assertNotIn("journalctl $", text)

    def test_runner_does_not_target_authoritative_ledger_mutation(self) -> None:
        text = self.runner_text()
        protected = [
            "paper_validation_samples.csv",
            "paper_orders.csv",
            "paper_trades.csv",
            "candidate_window_ledger.csv",
        ]

        for name in protected:
            self.assertNotIn(f"to_csv('/app/runtime_data/{name}'", text)
            self.assertNotIn(f"> /app/runtime_data/{name}", text)
            self.assertNotIn(f" {name} ", text)

    def test_runner_keeps_fixture_outputs_under_presession_acceptance_dir(self) -> None:
        text = self.runner_text()

        self.assertIn("logs/presession_acceptance", text)
        self.assertIn("/app/logs/presession_acceptance/$RUN_ID/premarket_freshness", text)
        self.assertIn("/app/logs/presession_acceptance/$RUN_ID/regular_freshness", text)
        self.assertIn("/app/logs/presession_acceptance/$RUN_ID/afterclose_freshness", text)

    def test_runner_does_not_expose_secret_files_or_values(self) -> None:
        text = self.runner_text()

        self.assertNotIn("cat /srv/projects/gwala/config/gwala.env", text)
        self.assertNotIn("env |", text)
        self.assertNotIn("printenv", text)
        self.assertNotIn(".webull_tokens/token", text)


if __name__ == "__main__":
    unittest.main()
