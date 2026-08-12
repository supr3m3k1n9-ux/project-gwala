"""Tests for source/package paths versus durable runtime data paths."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import runtime_paths
from deploy.linux.verify_docker_runtime_boundary import (
    docker_permission_message,
    extract_sha256_line,
    load_compose_config,
    validate_compose_boundary,
    validate_compose_template_env_file,
    validate_deployment_roots,
)
from deploy.linux.verify_vps_production import docker_boundary_check
from deploy.linux.verify_vps_production import dashboard_http_check
from deploy.linux.verify_vps_production import extract_json_line
from deploy.linux.verify_vps_production import parse_artifact_timestamp
from deploy.linux.write_host_security_health import container_security_warnings
from run_refresh_audit import default_audit_csv, parse_args as parse_refresh_audit_args


class RuntimePathTests(unittest.TestCase):
    def test_docker_runtime_data_root_is_not_source_package_path(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, "running_in_docker", return_value=True):
            self.assertEqual(runtime_paths.project_root(), Path("/app"))
            self.assertEqual(runtime_paths.runtime_data_root(), Path("/app/runtime_data"))
            self.assertNotEqual(runtime_paths.runtime_data_root(), Path("/app/data"))

    def test_local_macos_runtime_data_root_preserves_project_data_path(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, "running_in_docker", return_value=False), patch(
            "platform.system",
            return_value="Darwin",
        ):
            self.assertEqual(runtime_paths.runtime_data_root(), runtime_paths.MACOS_PROJECT_ROOT / "data")

    def test_runtime_data_root_env_override_preserves_existing_filenames(self) -> None:
        with TemporaryDirectory() as raw:
            runtime_root = Path(raw) / "runtime_data"
            with patch.dict(os.environ, {"GWALA_DATA_DIR": str(runtime_root)}, clear=True):
                path = runtime_paths.runtime_data_root() / "paper_validation_samples.csv"
                path.parent.mkdir(parents=True)
                path.write_text("symbol\nSPY\n", encoding="utf-8")

                self.assertEqual(path, runtime_root / "paper_validation_samples.csv")
                self.assertTrue(path.exists())

    def test_refresh_audit_docker_default_uses_runtime_data_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, "running_in_docker", return_value=True):
            self.assertEqual(default_audit_csv(), Path("/app/runtime_data/market_refresh_audit.csv"))

    def test_refresh_audit_local_default_uses_project_data_dir(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, "running_in_docker", return_value=False), patch(
            "platform.system",
            return_value="Darwin",
        ):
            self.assertEqual(default_audit_csv(), runtime_paths.MACOS_PROJECT_ROOT / "data" / "market_refresh_audit.csv")

    def test_refresh_audit_explicit_audit_csv_override_wins(self) -> None:
        with TemporaryDirectory() as raw:
            override = Path(raw) / "custom_refresh_audit.csv"
            with patch("sys.argv", ["run_refresh_audit.py", "--audit-csv", str(override)]):
                args = parse_refresh_audit_args()

            self.assertEqual(args.audit_csv, override)

    def test_refresh_audit_default_never_targets_app_data_in_docker(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, "running_in_docker", return_value=True):
            self.assertNotEqual(default_audit_csv().parent, Path("/app/data"))

    def test_refresh_audit_related_defaults_use_runtime_data_in_docker(self) -> None:
        from reports.refresh_status import build_refresh_status
        from run_morning_index_orb_manual_paper_watch import default_refresh_audit_csv as orb_audit_csv
        from run_paper_import import parse_args as parse_paper_import_args
        from run_paper_gate_v2 import parse_args as parse_paper_gate_args
        from run_update_paper_trade import parse_args as parse_update_paper_args
        from run_open_paper_monitor import parse_args as parse_open_monitor_args
        from run_dashboard import parse_args as parse_dashboard_args
        from run_daily_recap import parse_args as parse_daily_recap_args
        from run_readiness_check import parse_args as parse_readiness_args
        from run_premarket_plan import parse_args as parse_premarket_args
        from run_system_state import parse_args as parse_system_state_args
        from run_position_sizer import parse_args as parse_position_sizer_args
        from run_pre_entry_review import parse_args as parse_pre_entry_args
        from run_provider_stability_audit import (
            build_provider_stability_audit,
            default_refresh_audit_csv as provider_audit_csv,
            parse_args as parse_provider_args,
        )

        with patch.dict(os.environ, {}, clear=True), patch.object(runtime_paths, "running_in_docker", return_value=True):
            expected = Path("/app/runtime_data/market_refresh_audit.csv")

            with patch("sys.argv", ["run_paper_import.py"]):
                self.assertEqual(parse_paper_import_args().refresh_audit_csv, expected)
            with patch("sys.argv", ["run_paper_gate_v2.py"]):
                self.assertEqual(parse_paper_gate_args().samples_csv, Path("/app/runtime_data/paper_validation_samples.csv"))
            with patch("sys.argv", ["run_update_paper_trade.py"]):
                self.assertEqual(parse_update_paper_args().paper_csv, Path("/app/runtime_data/paper_trades.csv"))
            with patch("sys.argv", ["run_open_paper_monitor.py"]):
                self.assertEqual(parse_open_monitor_args().paper_csv, Path("/app/runtime_data/paper_trades.csv"))
            with patch("sys.argv", ["run_dashboard.py"]):
                self.assertEqual(parse_dashboard_args().paper_csv, Path("/app/runtime_data/paper_trades.csv"))
            with patch("sys.argv", ["run_daily_recap.py"]):
                daily_args = parse_daily_recap_args()
                self.assertEqual(daily_args.paper_csv, Path("/app/runtime_data/paper_trades.csv"))
                self.assertEqual(daily_args.mistake_csv, Path("/app/runtime_data/paper_mistakes.csv"))
            with patch("sys.argv", ["run_readiness_check.py"]):
                readiness_args = parse_readiness_args()
                self.assertEqual(readiness_args.paper_csv, Path("/app/runtime_data/paper_trades.csv"))
                self.assertEqual(readiness_args.mistake_csv, Path("/app/runtime_data/paper_mistakes.csv"))
            with patch("sys.argv", ["run_premarket_plan.py"]):
                self.assertEqual(parse_premarket_args().paper_csv, Path("/app/runtime_data/paper_trades.csv"))
            with patch("sys.argv", ["run_system_state.py"]):
                self.assertEqual(parse_system_state_args().paper_csv, Path("/app/runtime_data/paper_trades.csv"))
            with patch("sys.argv", ["run_position_sizer.py"]):
                self.assertEqual(parse_position_sizer_args().refresh_audit_csv, expected)
            with patch("sys.argv", ["run_pre_entry_review.py"]):
                self.assertEqual(parse_pre_entry_args().refresh_audit_csv, expected)
            with patch("sys.argv", ["run_provider_stability_audit.py"]):
                self.assertEqual(parse_provider_args().audit_csv, expected)

            self.assertEqual(provider_audit_csv(), expected)
            self.assertEqual(orb_audit_csv(), expected)

            with patch(
                "reports.refresh_status.market_refresh_state",
                return_value={
                    "today": "2026-08-11",
                    "market_is_open": False,
                    "market_status_reason": "test session closed",
                    "next_market_session": "2026-08-12",
                },
            ):
                status = build_refresh_status(audit_csv=None)
            self.assertIn("paper_import_blocked", status)

            payload = build_provider_stability_audit(audit_csv=None, symbols=[])
            self.assertEqual(payload["status"], "not_recorded")

    def test_repository_compose_mounts_runtime_data_not_source_package(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("${GWALA_APP_DIR:-.}", text)
        self.assertIn("${GWALA_STACK_DIR:-.}/config/gwala.env", text)
        self.assertIn("${GWALA_STACK_DIR:-.}/data:/app/runtime_data", text)
        self.assertNotIn(":/app/data", text)
        self.assertNotIn(":/app/config", text)
        self.assertIn("${GWALA_STACK_DIR:-.}/config/webull_tokens:/app/.webull_tokens", text)
        self.assertIn("GWALA_DATA_DIR: /app/runtime_data", text)

    def test_deploy_verifier_rejects_data_source_shadowing(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [{"source": "/srv/projects/gwala/data", "target": "/app/data"}],
                }
            }
        }

        errors = validate_compose_boundary(payload)

        self.assertTrue(any("/app/data must not be a bind mount" in error for error in errors))

    def test_deploy_verifier_rejects_config_source_shadowing(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/config", "target": "/app/config"},
                    ],
                }
            }
        }

        errors = validate_compose_boundary(payload)

        self.assertTrue(any("/app/config must not be a bind mount" in error for error in errors))

    def test_deploy_verifier_accepts_runtime_data_mount(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/logs", "target": "/app/logs"},
                        {"source": "/srv/projects/gwala/config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        self.assertEqual(validate_compose_boundary(payload), [])

    def test_deploy_verifier_accepts_production_app_stack_roots(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "build": {"context": "/srv/projects/gwala/app", "dockerfile": "Dockerfile"},
                    "env_file": ["/srv/projects/gwala/config/gwala.env"],
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/logs", "target": "/app/logs"},
                        {"source": "/srv/projects/gwala/backups", "target": "/app/backups"},
                        {"source": "/srv/projects/gwala/config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        errors = validate_deployment_roots(payload, Path("/srv/projects/gwala/app"), Path("/srv/projects/gwala"))

        self.assertEqual(errors, [])

    def test_deploy_verifier_accepts_rendered_compose_without_env_file_field(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "build": {"context": "/srv/projects/gwala/app", "dockerfile": "Dockerfile"},
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/logs", "target": "/app/logs"},
                        {"source": "/srv/projects/gwala/backups", "target": "/app/backups"},
                        {"source": "/srv/projects/gwala/config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        errors = validate_deployment_roots(payload, Path("/srv/projects/gwala/app"), Path("/srv/projects/gwala"))

        self.assertEqual(errors, [])

    def test_compose_template_requires_stack_root_env_file(self) -> None:
        root = Path(__file__).resolve().parents[1]

        errors = validate_compose_template_env_file(root / "compose.yaml")

        self.assertEqual(errors, [])

    def test_deploy_verifier_resolves_relative_env_file_against_stack_root(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "build": {"context": "/srv/projects/gwala/app", "dockerfile": "Dockerfile"},
                    "env_file": ["config/gwala.env"],
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "data", "target": "/app/runtime_data"},
                        {"source": "logs", "target": "/app/logs"},
                        {"source": "backups", "target": "/app/backups"},
                        {"source": "config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        errors = validate_deployment_roots(payload, Path("/srv/projects/gwala/app"), Path("/srv/projects/gwala"))

        self.assertEqual(errors, [])

    def test_compose_render_sets_app_and_stack_roots_independent_of_cwd(self) -> None:
        rendered = {
            "services": {
                "gwala": {
                    "build": {"context": "/srv/projects/gwala/app"},
                    "env_file": ["/srv/projects/gwala/config/gwala.env"],
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/logs", "target": "/app/logs"},
                        {"source": "/srv/projects/gwala/backups", "target": "/app/backups"},
                        {"source": "/srv/projects/gwala/config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        def fake_run(command, check, capture_output, text, timeout, env):
            self.assertEqual(env["GWALA_APP_DIR"], "/srv/projects/gwala/app")
            self.assertEqual(env["GWALA_STACK_DIR"], "/srv/projects/gwala")

            class Completed:
                returncode = 0
                stdout = __import__("json").dumps(rendered)
                stderr = ""

            return Completed()

        with patch("deploy.linux.verify_docker_runtime_boundary.subprocess.run", side_effect=fake_run), patch(
            "os.getcwd",
            return_value="/tmp/not-the-stack",
        ):
            payload = load_compose_config(
                Path("/srv/projects/gwala/compose.yaml"),
                app_dir=Path("/srv/projects/gwala/app"),
                stack_dir=Path("/srv/projects/gwala"),
            )

        self.assertEqual(payload["services"]["gwala"]["build"]["context"], "/srv/projects/gwala/app")

    def test_docker_permission_denial_message_is_actionable(self) -> None:
        text = "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock"

        message = docker_permission_message(text)

        self.assertIsNotNone(message)
        self.assertIn("sudo", message or "")

    def test_checksum_probe_extracts_hash_from_noisy_compose_output(self) -> None:
        checksum = "a" * 64
        text = f"Container gwala Creating\n{checksum} /app/data/webull_data.py\nContainer gwala Removing"

        self.assertEqual(extract_sha256_line(text), checksum)

    def test_vps_readiness_docker_permission_denial_is_actionable(self) -> None:
        with patch(
            "deploy.linux.verify_vps_production.run",
            return_value=(1, "permission denied while trying to connect to /var/run/docker.sock"),
        ):
            check = docker_boundary_check(Path("/srv/projects/gwala/app"), Path("/srv/projects/gwala"))

        self.assertEqual(check.status, "FAIL")
        self.assertIn("sudo", check.reason)

    def test_vps_readiness_parses_host_systemd_et_timestamp(self) -> None:
        parsed = parse_artifact_timestamp("2026-08-11 19:38:43 EDT")

        self.assertIsNotNone(parsed)
        self.assertEqual(str(parsed.date()), "2026-08-11")

    def test_vps_readiness_extracts_json_from_noisy_container_output(self) -> None:
        payload = extract_json_line('Container Creating\n{"status": "GREEN", "reason": "ok"}\nContainer Removing')

        self.assertEqual(payload, {"status": "GREEN", "reason": "ok"})

    def test_host_security_ignores_no_new_privileges_warning_for_transient_run_container(self) -> None:
        warnings = container_security_warnings("gwala-gwala-run-abc123", {"SecurityOpt": []})

        self.assertEqual(warnings, [])

    def test_deploy_verifier_rejects_build_context_from_stack_runtime_root(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "build": {"context": "/srv/projects/gwala", "dockerfile": "Dockerfile"},
                    "env_file": ["/srv/projects/gwala/config/gwala.env"],
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/logs", "target": "/app/logs"},
                        {"source": "/srv/projects/gwala/backups", "target": "/app/backups"},
                        {"source": "/srv/projects/gwala/config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        errors = validate_deployment_roots(payload, Path("/srv/projects/gwala/app"), Path("/srv/projects/gwala"))

        self.assertTrue(any("Docker build context must be APP_DIR" in error for error in errors))

    def test_deploy_verifier_rejects_runtime_mount_from_app_source_root(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "build": {"context": "/srv/projects/gwala/app", "dockerfile": "Dockerfile"},
                    "env_file": ["/srv/projects/gwala/config/gwala.env"],
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [
                        {"source": "/srv/projects/gwala/app/data", "target": "/app/runtime_data"},
                        {"source": "/srv/projects/gwala/logs", "target": "/app/logs"},
                        {"source": "/srv/projects/gwala/backups", "target": "/app/backups"},
                        {"source": "/srv/projects/gwala/config/webull_tokens", "target": "/app/.webull_tokens"},
                    ],
                }
            }
        }

        errors = validate_deployment_roots(payload, Path("/srv/projects/gwala/app"), Path("/srv/projects/gwala"))

        self.assertTrue(any("Compose /app/runtime_data source must be" in error for error in errors))

    def test_deploy_scripts_preserve_app_and_stack_boundary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        deploy_text = (root / "deploy_latest.sh").read_text(encoding="utf-8")
        wrapper_text = (root / "run_in_docker.sh").read_text(encoding="utf-8")

        self.assertIn('cd "$APP_DIR"', deploy_text)
        self.assertIn('docker compose -f "$COMPOSE_FILE" build gwala', deploy_text)
        self.assertIn("verify_vps_production.py", deploy_text)
        self.assertIn('export GWALA_APP_DIR="$APP_DIR"', wrapper_text)
        self.assertIn('cd "$STACK_DIR"', wrapper_text)

    def test_dashboard_systemd_service_publishes_compose_service_ports(self) -> None:
        text = Path("deploy/linux/systemd/project-gwala-dashboard.service").read_text(encoding="utf-8")
        self.assertIn("GWALA_APP_DIR=/srv/projects/gwala/app", text)
        self.assertIn("GWALA_STACK_DIR=/srv/projects/gwala", text)
        self.assertIn("--service-ports gwala python run_app.py --host 0.0.0.0 --port 8765", text)
        self.assertNotIn("/srv/projects/gwala/run_in_docker.sh python run_app.py", text)

    def test_compose_dashboard_binds_container_all_interfaces_but_host_localhost_only(self) -> None:
        text = Path("compose.yaml").read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1:8765:8765"', text)
        self.assertIn('"0.0.0.0"', text)

    def test_vps_verifier_dashboard_http_check_passes_on_command_center_payload(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'{"guardrail": "Read-only observability. No trading controls."}'

        with patch("deploy.linux.verify_vps_production.urlopen", return_value=FakeResponse()):
            check = dashboard_http_check()

        self.assertEqual(check.status, "PASS")

    def test_vps_verifier_dashboard_http_check_fails_when_unreachable(self) -> None:
        with patch("deploy.linux.verify_vps_production.urlopen", side_effect=OSError("connection refused")):
            check = dashboard_http_check()

        self.assertEqual(check.status, "FAIL")
        self.assertIn("dashboard endpoint unreachable", check.reason)

    def test_linux_systemd_docker_services_use_runtime_data_mount(self) -> None:
        systemd_dir = Path("deploy/linux/systemd")
        for name in [
            "project-gwala-production-alert.service",
            "project-gwala-opening-executive-report.service",
            "project-gwala-eod-executive-report.service",
        ]:
            text = (systemd_dir / name).read_text(encoding="utf-8")
            self.assertIn("/srv/projects/gwala/run_in_docker.sh", text)
            self.assertIn("--data-dir /app/runtime_data", text)
            self.assertNotIn("--data-dir data", text)

    def test_deploy_latest_syncs_systemd_units_without_timer_state_changes(self) -> None:
        text = Path("deploy_latest.sh").read_text(encoding="utf-8")
        self.assertIn("project-gwala-*.service", text)
        self.assertIn("project-gwala-*.timer", text)
        self.assertIn("systemctl daemon-reload", text)
        self.assertIn("systemctl try-restart project-gwala-dashboard.service", text)
        self.assertNotIn("systemctl enable", text)
        self.assertNotIn("systemctl start", text)
        self.assertNotIn("systemctl stop", text)

    def test_data_source_package_imports_remain_available(self) -> None:
        from data.webull_data import disable_sdk_default_logging

        self.assertTrue(callable(disable_sdk_default_logging))

    def test_config_source_package_imports_remain_available(self) -> None:
        from config.runtime_paths import runtime_data_root
        import config.filter_policy
        import config.strategy_registry
        import config.symbol_playbook

        self.assertTrue(callable(runtime_data_root))
        self.assertIsNotNone(config.filter_policy)
        self.assertIsNotNone(config.strategy_registry)
        self.assertIsNotNone(config.symbol_playbook)


if __name__ == "__main__":
    unittest.main()
