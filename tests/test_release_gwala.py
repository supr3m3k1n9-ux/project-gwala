"""Tests for the Mac-side Project Gwala release script."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCRIPT = PROJECT_ROOT / "release_gwala.sh"


def run_sourced(command: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Source release_gwala.sh and run a helper command."""

    script = f"source {shlex.quote(str(RELEASE_SCRIPT))}; {command}"
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True)


def init_gwala_repo(root: Path, origin: str = "https://github.com/supr3m3k1n9-ux/project-gwala.git") -> None:
    """Create a minimal Project Gwala-shaped Git repository."""

    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=root, check=True)
    (root / "deploy" / "linux").mkdir(parents=True)
    (root / "AGENTS.md").write_text("Project Gwala\n", encoding="utf-8")
    (root / "run_continuous_assurance.py").write_text("VALUE = 1\n", encoding="utf-8")


class ReleaseGwalaScriptTests(unittest.TestCase):
    def test_protected_path_rules_block_secrets_logs_runtime_data_and_active_chains(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            checks = {
                ".env": "yes",
                ".webull_tokens/token.txt": "yes",
                "webull_data_sdk.log": "yes",
                "config/gwala.env": "yes",
                "logs/production.log": "yes",
                "data/paper_trades.csv": "yes",
                "data/incidents/outage.json": "yes",
                "data/options_chains/SPY.csv": "yes",
                "data/options_chains/active/SPY.csv": "yes",
                "data/webull_data.py": "no",
                ".env.example": "no",
                "data/options_chains/templates/SPY_template.csv": "no",
            }
            command = "; ".join(
                f"protected_path {shlex.quote(path)} && echo {path}=yes || echo {path}=no"
                for path in checks
            )
            completed = run_sourced(command, cwd=root)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = dict(line.split("=", 1) for line in completed.stdout.splitlines())
        self.assertEqual(observed, checks)

    def test_expected_origin_accepts_project_gwala_and_rejects_other_repos(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            init_gwala_repo(root)
            accepted = run_sourced("assert_expected_origin", cwd=root)
            subprocess.run(
                ["git", "remote", "set-url", "origin", "https://github.com/example/not-gwala.git"],
                cwd=root,
                check=True,
            )
            rejected = run_sourced("assert_expected_origin", cwd=root)

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("origin does not point", rejected.stderr)

    def test_stage_release_changes_excludes_protected_paths_without_ignored_force_adds(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            init_gwala_repo(root)
            paths = [
                "release_me.py",
                ".env",
                "logs/runtime.log",
                "data/webull_data.py",
                "data/paper_trades.csv",
                "data/options_chains/templates/SPY_template.csv",
                "data/options_chains/active/SPY.csv",
            ]
            for relpath in paths:
                path = root / relpath
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VALUE = 1\n", encoding="utf-8")
            completed = run_sourced("stage_release_changes; git diff --cached --name-only", cwd=root)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        staged = set(completed.stdout.splitlines())
        self.assertIn("release_me.py", staged)
        self.assertIn("data/webull_data.py", staged)
        self.assertIn("data/options_chains/templates/SPY_template.csv", staged)
        self.assertNotIn(".env", staged)
        self.assertNotIn("logs/runtime.log", staged)
        self.assertNotIn("data/paper_trades.csv", staged)
        self.assertNotIn("data/options_chains/active/SPY.csv", staged)

    def test_secret_audit_redacts_values(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            init_gwala_repo(root)
            secret_value = "live_secret_value_12345"
            settings = root / "config" / "settings.py"
            settings.parent.mkdir()
            settings.write_text(f"WEBULL_APP_SECRET={secret_value}\n", encoding="utf-8")
            completed = run_sourced("audit_candidate_files pre", cwd=root)

        combined = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Potential secret assignment", combined)
        self.assertNotIn(secret_value, combined)


if __name__ == "__main__":
    unittest.main()
