#!/usr/bin/env python3
"""Read-only VPS production readiness verifier for Project Gwala.

This command verifies the Docker/host deployment boundary and paper-only safety
posture. It does not start services, enable timers, generate reports, import
trades, reconcile accounting, or place broker orders.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path(os.environ.get("GWALA_STACK_DIR", "/srv/projects/gwala"))
DEFAULT_APP_DIR = Path(os.environ.get("GWALA_APP_DIR", DEFAULT_STACK_DIR / "app"))
STALE_MINUTES = 15
SAFETY_ENV = {
    "GWALA_DEPLOYMENT_MODE": "shadow",
    "GWALA_SHADOW_MODE": "true",
    "GWALA_DISABLE_BROKER_EXECUTION": "true",
    "GWALA_LIVE_TRADING_ENABLED": "false",
    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
    "GWALA_REAL_MONEY_READY": "false",
}


@dataclass
class Check:
    area: str
    status: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Project Gwala VPS production readiness.")
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--stale-minutes", type=int, default=STALE_MINUTES)
    parser.add_argument(
        "--skip-container-checks",
        action="store_true",
        help="Skip docker compose run checks when only host files should be inspected.",
    )
    return parser.parse_args()


def run(command: list[str], cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()


def redact(text: str, limit: int = 600) -> str:
    bounded = text[-limit:]
    for key in ("WEBULL_APP_KEY", "WEBULL_APP_SECRET", "POLYGON_API_KEY", "SMTP_PASSWORD"):
        bounded = bounded.replace(key, f"{key}")
    return bounded


def normalized(path: Path) -> Path:
    return path.expanduser().resolve()


def aggregate(checks: list[Check]) -> str:
    statuses = {check.status for check in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "WATCH" in statuses:
        return "WATCH"
    return "PASS"


def git_checks(app_dir: Path) -> list[Check]:
    if not (app_dir / ".git").exists():
        return [Check("Git", "FAIL", f"APP_DIR is not a Git checkout: {app_dir}")]
    checks: list[Check] = []
    code, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=app_dir)
    checks.append(Check("Git branch", "PASS" if code == 0 and branch == "main" else "FAIL", f"branch={branch or 'unknown'}"))
    code, status = run(["git", "status", "--porcelain"], cwd=app_dir)
    checks.append(Check("Git worktree", "PASS" if code == 0 and not status else "FAIL", "clean" if not status else "uncommitted changes present"))
    code, sha = run(["git", "rev-parse", "HEAD"], cwd=app_dir)
    checks.append(Check("Git commit", "PASS" if code == 0 else "FAIL", sha[:12] if code == 0 else redact(sha)))
    return checks


def docker_boundary_check(app_dir: Path, stack_dir: Path) -> Check:
    compose_file = stack_dir / "compose.yaml"
    verifier = app_dir / "deploy" / "linux" / "verify_docker_runtime_boundary.py"
    code, text = run(
        [
            sys.executable,
            str(verifier),
            "--compose-file",
            str(compose_file),
            "--app-dir",
            str(app_dir),
            "--stack-dir",
            str(stack_dir),
        ],
        cwd=app_dir,
        timeout=90,
    )
    return Check("Docker boundary", "PASS" if code == 0 else "FAIL", "source/runtime separation ok" if code == 0 else redact(text))


def persistence_checks(stack_dir: Path) -> list[Check]:
    checks: list[Check] = []
    for relative in ("data", "logs", "backups", "config", "config/webull_tokens"):
        path = stack_dir / relative
        if not path.exists():
            checks.append(Check("Persistence", "FAIL", f"missing {path}"))
            continue
        checks.append(Check("Persistence", "PASS", f"exists {path}"))
    for relative in ("data", "logs"):
        path = stack_dir / relative
        checks.append(Check("Persistence write", "PASS" if os.access(path, os.W_OK) else "FAIL", f"{path} writable={os.access(path, os.W_OK)}"))
    return checks


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def artifact_check(path: Path, label: str, stale_minutes: int) -> Check:
    payload = load_json(path)
    if payload is None:
        return Check(label, "WATCH", f"missing or unreadable artifact: {path}")
    generated = str(payload.get("generated_at") or payload.get("generated_at_et") or "")
    status = str(payload.get("status") or payload.get("overall_status") or "").upper()
    stale = False
    if generated:
        try:
            parsed = datetime.fromisoformat(generated.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            stale = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc) > timedelta(minutes=stale_minutes)
        except ValueError:
            return Check(label, "WATCH", f"artifact timestamp not parseable: {path}")
    if stale:
        return Check(label, "WATCH", f"artifact stale beyond {stale_minutes} minutes: {path}")
    if status in {"RED", "FAIL", "FAILED", "DOWN"}:
        return Check(label, "FAIL", f"fresh artifact reports {status}")
    if status in {"YELLOW", "WATCH", "DEGRADED"}:
        return Check(label, "WATCH", f"fresh artifact reports {status}")
    return Check(label, "PASS", "fresh host artifact ok")


def host_artifact_checks(stack_dir: Path, stale_minutes: int) -> list[Check]:
    logs = stack_dir / "logs"
    return [
        artifact_check(logs / "host_systemd_health.json", "Host systemd health", stale_minutes),
        artifact_check(logs / "host_docker_health.json", "Host Docker health", stale_minutes),
        artifact_check(logs / "host_security_health.json", "Host security health", stale_minutes),
    ]


def container_check(stack_dir: Path, snippet: str, label: str, timeout: int = 120) -> Check:
    wrapper = stack_dir / "run_in_docker.sh"
    if not wrapper.exists():
        return Check(label, "FAIL", f"missing wrapper: {wrapper}")
    code, text = run([str(wrapper), "python", "-c", snippet], cwd=stack_dir, timeout=timeout)
    return Check(label, "PASS" if code == 0 else "FAIL", "ok" if code == 0 else redact(text))


def container_checks(stack_dir: Path) -> list[Check]:
    import_snippet = (
        "from config.runtime_paths import runtime_data_root; "
        "import config.filter_policy, config.strategy_registry, config.symbol_playbook; "
        "import data.webull_data; "
        "assert str(runtime_data_root()) == '/app/runtime_data'; "
        "print('ok')"
    )
    safety_snippet = (
        "import os, sys; "
        f"expected={SAFETY_ENV!r}; "
        "bad=[k for k,v in expected.items() if os.environ.get(k) != v]; "
        "sys.exit(1 if bad else 0)"
    )
    boundary_snippet = (
        "from pathlib import Path; "
        "assert Path('/app/data/webull_data.py').exists(); "
        "assert Path('/app/config/runtime_paths.py').exists(); "
        "assert Path('/app/runtime_data').is_dir(); "
        "assert not Path('/app/webull_data_sdk.log').exists(); "
        "print('ok')"
    )
    return [
        container_check(stack_dir, import_snippet, "Container source imports"),
        container_check(stack_dir, safety_snippet, "Paper-only safety env"),
        container_check(stack_dir, boundary_snippet, "Container filesystem boundary"),
    ]


def print_report(checks: list[Check]) -> None:
    verdict = aggregate(checks)
    print(f"VPS PRODUCTION READINESS: {verdict}")
    for check in checks:
        print(f"{check.status:<5} {check.area}: {check.reason}")


def main() -> None:
    args = parse_args()
    app_dir = normalized(args.app_dir)
    stack_dir = normalized(args.stack_dir)
    checks: list[Check] = []
    checks.extend(git_checks(app_dir))
    checks.append(docker_boundary_check(app_dir, stack_dir))
    checks.extend(persistence_checks(stack_dir))
    checks.extend(host_artifact_checks(stack_dir, args.stale_minutes))
    if args.skip_container_checks:
        checks.append(Check("Container runtime", "WATCH", "container checks skipped by operator flag"))
    else:
        checks.extend(container_checks(stack_dir))
    print_report(checks)
    raise SystemExit(1 if aggregate(checks) == "FAIL" else 0)


if __name__ == "__main__":
    main()
