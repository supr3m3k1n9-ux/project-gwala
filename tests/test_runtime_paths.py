"""Tests for source/package paths versus durable runtime data paths."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import runtime_paths
from deploy.linux.verify_docker_runtime_boundary import validate_compose_boundary
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

        self.assertIn("./data:/app/runtime_data", text)
        self.assertNotIn("./data:/app/data", text)
        self.assertNotIn("./config:/app/config", text)
        self.assertIn("./config/webull_tokens:/app/.webull_tokens", text)
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
