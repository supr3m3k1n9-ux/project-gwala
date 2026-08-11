"""Preflight checks for Project Gwala Ubuntu shadow deployment.

This command is read-only. It verifies runtime wiring and safety posture before
systemd timers are enabled on a VPS.
"""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen


PROJECT_ROOT = Path(os.environ.get("GWALA_PROJECT_ROOT", "/opt/project-gwala"))
REQUIRED_MODULES = ["pandas", "numpy", "matplotlib", "yfinance", "webull"]
REQUIRED_ENV = ["WEBULL_APP_KEY", "WEBULL_APP_SECRET", "WEBULL_REGION_ID"]
SAFETY_ENV = {
    "GWALA_DEPLOYMENT_MODE": "shadow",
    "GWALA_SHADOW_MODE": "true",
    "GWALA_DISABLE_BROKER_EXECUTION": "true",
    "GWALA_LIVE_TRADING_ENABLED": "false",
    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
    "GWALA_REAL_MONEY_READY": "false",
}
UNIT_FILES = [
    "project-gwala-dashboard.service",
    "project-gwala-autonomous-paper.service",
    "project-gwala-autonomous-paper.timer",
    "project-gwala-production-alert.service",
    "project-gwala-production-alert.timer",
    "project-gwala-opening-executive-report.service",
    "project-gwala-opening-executive-report.timer",
    "project-gwala-eod-executive-report.service",
    "project-gwala-eod-executive-report.timer",
]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def result(name: str, ok: bool, detail: str) -> tuple[str, bool, str]:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")
    return name, ok, detail


def check_python() -> tuple[str, bool, str]:
    version = sys.version_info
    ok = version.major == 3 and version.minor == 11
    return result("Python version", ok, platform.python_version())


def check_dependencies() -> tuple[str, bool, str]:
    missing = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    return result("Dependencies", not missing, "missing: " + ", ".join(missing) if missing else "required modules import")


def check_env() -> tuple[str, bool, str]:
    missing = []
    for name in REQUIRED_ENV:
        value = os.environ.get(name, "").strip()
        if not value or value.startswith("your_") or value.startswith("paste_"):
            missing.append(name)
    return result("Environment variables", not missing, "missing: " + ", ".join(missing) if missing else "required env present")


def check_safety_env() -> tuple[str, bool, str]:
    wrong = []
    for name, expected in SAFETY_ENV.items():
        actual = os.environ.get(name, "").strip().lower()
        if actual != expected:
            wrong.append(f"{name}={actual or '<unset>'}")
    return result("Paper-only safety state", not wrong, "wrong: " + ", ".join(wrong) if wrong else "shadow mode enforced")


def check_directories() -> tuple[str, bool, str]:
    data_root = Path(os.environ.get("GWALA_DATA_DIR", str(PROJECT_ROOT / "data")))
    project_missing = not PROJECT_ROOT.exists()
    project_unreadable = PROJECT_ROOT.exists() and not os.access(PROJECT_ROOT, os.R_OK | os.X_OK)
    writable_paths = [PROJECT_ROOT / "logs", data_root]
    missing = [str(path) for path in writable_paths if not path.exists()]
    unwritable = [str(path) for path in writable_paths if path.exists() and not os.access(path, os.W_OK)]
    ok = not project_missing and not project_unreadable and not missing and not unwritable
    details = []
    if project_missing:
        details.append(f"missing project root: {PROJECT_ROOT}")
    if project_unreadable:
        details.append(f"project root is not readable/searchable: {PROJECT_ROOT}")
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unwritable:
        details.append("not writable: " + ", ".join(unwritable))
    return result(
        "Directories and permissions",
        ok,
        "; ".join(details) if details else "project root readable; logs and data writable",
    )


def check_connectivity(skip_network: bool) -> tuple[str, bool, str]:
    if skip_network:
        return result("External API connectivity", True, "skipped")
    targets = ["api.polygon.io", "query1.finance.yahoo.com"]
    failures = []
    for host in targets:
        try:
            socket.create_connection((host, 443), timeout=5).close()
        except OSError as exc:
            failures.append(f"{host}: {exc}")
    return result("External API connectivity", not failures, "; ".join(failures) if failures else "HTTPS reachable")


def check_webull(skip_network: bool) -> tuple[str, bool, str]:
    if skip_network:
        return result("Webull authentication", True, "skipped")
    try:
        from data.webull_data import build_data_client

        build_data_client()
    except Exception as exc:
        return result("Webull authentication", False, f"{type(exc).__name__}: {exc}")
    return result("Webull authentication", True, "data client initialized")


def check_systemd_units(skip_systemd_verify: bool) -> tuple[str, bool, str]:
    unit_dir = PROJECT_ROOT / "deploy" / "linux" / "systemd"
    missing = [name for name in UNIT_FILES if not (unit_dir / name).exists()]
    if missing:
        return result("systemd unit files", False, "missing: " + ", ".join(missing))
    if skip_systemd_verify:
        return result("systemd unit files", True, "files present; systemd-analyze skipped")
    command = ["systemd-analyze", "verify", *[str(unit_dir / name) for name in UNIT_FILES]]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    ok = completed.returncode == 0
    detail = "systemd-analyze verify passed" if ok else (completed.stderr or completed.stdout).strip()[-500:]
    return result("systemd unit validity", ok, detail)


def check_no_public_dashboard() -> tuple[str, bool, str]:
    host = os.environ.get("GWALA_DASHBOARD_HOST", "127.0.0.1").strip()
    ok = host in {"127.0.0.1", "localhost", "::1"}
    return result("Dashboard exposure", ok, f"GWALA_DASHBOARD_HOST={host}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Project Gwala Linux shadow deployment readiness.")
    parser.add_argument("--env-file", type=Path, default=Path("/etc/project-gwala/gwala.env"))
    parser.add_argument("--skip-network", action="store_true")
    parser.add_argument("--skip-systemd-verify", action="store_true")
    args = parser.parse_args()

    load_env_file(args.env_file)
    checks = [
        check_python(),
        check_dependencies(),
        check_env(),
        check_safety_env(),
        check_directories(),
        check_connectivity(args.skip_network),
        check_webull(args.skip_network),
        check_systemd_units(args.skip_systemd_verify),
        check_no_public_dashboard(),
    ]
    if not all(ok for _, ok, _ in checks):
        raise SystemExit(1)
    print("Project Gwala Linux preflight passed.")


if __name__ == "__main__":
    main()
