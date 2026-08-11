"""Tests for source/package paths versus durable runtime data paths."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import runtime_paths
from deploy.linux.verify_docker_runtime_boundary import validate_compose_boundary


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

    def test_repository_compose_mounts_runtime_data_not_source_package(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("./data:/app/runtime_data", text)
        self.assertNotIn("./data:/app/data", text)
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

    def test_deploy_verifier_accepts_runtime_data_mount(self) -> None:
        payload = {
            "services": {
                "gwala": {
                    "environment": {"GWALA_DATA_DIR": "/app/runtime_data"},
                    "volumes": [{"source": "/srv/projects/gwala/data", "target": "/app/runtime_data"}],
                }
            }
        }

        self.assertEqual(validate_compose_boundary(payload), [])

    def test_data_source_package_imports_remain_available(self) -> None:
        from data.webull_data import disable_sdk_default_logging

        self.assertTrue(callable(disable_sdk_default_logging))


if __name__ == "__main__":
    unittest.main()
