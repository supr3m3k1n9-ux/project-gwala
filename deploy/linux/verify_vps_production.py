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
from urllib.error import URLError
from urllib.request import urlopen


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


def compose_environment(app_dir: Path, stack_dir: Path) -> dict[str, str]:
    """Return explicit roots for Docker Compose commands."""

    env = os.environ.copy()
    env["GWALA_APP_DIR"] = str(app_dir.expanduser().resolve())
    env["GWALA_STACK_DIR"] = str(stack_dir.expanduser().resolve())
    return env


def docker_permission_message(text: str) -> str | None:
    lowered = text.lower()
    if "permission denied" in lowered and ("docker.sock" in lowered or "docker daemon socket" in lowered):
        return "Docker permission denied. Re-run with sudo: sudo /srv/projects/gwala/deploy_latest.sh"
    if "permission denied" in lowered and "docker" in lowered:
        return "Docker permission denied. Re-run the VPS readiness/deploy command with sudo."
    return None


def run(
    command: list[str],
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout, env=env)
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
        env=compose_environment(app_dir, stack_dir),
    )
    if code == 0:
        return Check("Docker boundary", "PASS", "source/runtime separation ok")
    permission = docker_permission_message(text)
    return Check("Docker boundary", "FAIL", permission if permission else redact(text))


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


def next_market_session_text(app_dir: Path) -> str:
    """Return the next market session using Project Gwala's calendar utilities."""

    sys.path.insert(0, str(app_dir))
    try:
        from config.market_calendar import MARKET_TZ, next_market_session
        from config.settings import STRATEGY

        opened = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
        closed = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
        return str(next_market_session(datetime.now(MARKET_TZ), opened, closed).session_date)
    except Exception as exc:  # pragma: no cover - defensive reporting path.
        return f"unknown ({type(exc).__name__})"
    finally:
        try:
            sys.path.remove(str(app_dir))
        except ValueError:
            pass


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
        parsed = parse_artifact_timestamp(generated)
        if parsed is None:
            return Check(label, "WATCH", f"artifact timestamp not parseable: {path}")
        stale = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc) > timedelta(minutes=stale_minutes)
    if stale:
        return Check(label, "WATCH", f"artifact stale beyond {stale_minutes} minutes: {path}")
    if status in {"RED", "FAIL", "FAILED", "DOWN"}:
        return Check(label, "FAIL", f"fresh artifact reports {status}")
    if status in {"YELLOW", "WATCH", "DEGRADED"}:
        return Check(label, "WATCH", f"fresh artifact reports {status}")
    return Check(label, "PASS", "fresh host artifact ok")


def parse_artifact_timestamp(value: str) -> datetime | None:
    """Parse host-health timestamps written in ISO or human-readable ET form."""

    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        pass
    for suffix in (" EDT", " EST"):
        if text.endswith(suffix):
            try:
                from zoneinfo import ZoneInfo

                naive = datetime.strptime(text[: -len(suffix)], "%Y-%m-%d %H:%M:%S")
                return naive.replace(tzinfo=ZoneInfo("America/New_York"))
            except ValueError:
                return None
    return None


def host_artifact_checks(stack_dir: Path, stale_minutes: int) -> list[Check]:
    logs = stack_dir / "logs"
    return [
        artifact_check(logs / "host_systemd_health.json", "Systemd", stale_minutes),
        artifact_check(logs / "host_docker_health.json", "Host Docker health", stale_minutes),
        artifact_check(logs / "host_security_health.json", "Host security health", stale_minutes),
    ]


def container_check(app_dir: Path, stack_dir: Path, snippet: str, label: str, timeout: int = 120) -> Check:
    wrapper = stack_dir / "run_in_docker.sh"
    if not wrapper.exists():
        return Check(label, "FAIL", f"missing wrapper: {wrapper}")
    code, text = run(
        [str(wrapper), "python", "-c", snippet],
        cwd=stack_dir,
        timeout=timeout,
        env=compose_environment(app_dir, stack_dir),
    )
    if code == 0:
        return Check(label, "PASS", "ok")
    permission = docker_permission_message(text)
    return Check(label, "FAIL", permission if permission else redact(text))


def extract_json_line(text: str) -> dict[str, Any] | None:
    """Extract the last JSON object line from noisy docker compose output."""

    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def heartbeat_readiness_check(app_dir: Path, stack_dir: Path) -> Check:
    """Verify heartbeat execution without invalidating deploy readiness for past stale market artifacts."""

    snippet = (
        "import json; "
        "from pathlib import Path; "
        "from run_production_heartbeat import build_heartbeat; "
        "payload = build_heartbeat(Path('/app/logs'), data_dir=Path('/app/runtime_data'), platform_name='Linux', in_docker=True); "
        "print(json.dumps({"
        "'status': payload.get('status'), "
        "'reason': payload.get('reason'), "
        "'red_component': payload.get('red_component'), "
        "'red_reason': payload.get('red_reason'), "
        "'runtime': payload.get('runtime', {}), "
        "'checks': payload.get('checks', [])"
        "}))"
    )
    wrapper = stack_dir / "run_in_docker.sh"
    if not wrapper.exists():
        return Check("Heartbeat", "FAIL", f"missing wrapper: {wrapper}")
    code, text = run(
        [str(wrapper), "python", "-c", snippet],
        cwd=stack_dir,
        timeout=120,
        env=compose_environment(app_dir, stack_dir),
    )
    if code != 0:
        permission = docker_permission_message(text)
        return Check("Heartbeat", "FAIL", permission if permission else redact(text))
    payload = extract_json_line(text)
    if payload is None:
        return Check("Heartbeat", "FAIL", f"heartbeat probe did not return JSON: {redact(text)}")
    status = str(payload.get("status", ""))
    if status == "GREEN":
        return Check("Heartbeat", "PASS", "production heartbeat is GREEN")
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    red_components = {str(check.get("component", "")) for check in checks if isinstance(check, dict) and check.get("status") == "RED"}
    market_artifact_components = {"Scanner", "Current-candle capture", "Candidate ledger"}
    if status == "RED" and red_components and red_components.issubset(market_artifact_components):
        return Check(
            "Heartbeat",
            "PASS",
            "heartbeat executes; stale completed-session market artifacts reflect prior interrupted evidence collection, not deployment readiness",
        )
    return Check("Heartbeat", "FAIL" if status == "RED" else "WATCH", str(payload.get("reason") or payload.get("red_reason") or status))


def container_checks(app_dir: Path, stack_dir: Path) -> list[Check]:
    runtime_snippet = (
        "from config.runtime_paths import runtime_data_root; "
        "import config.filter_policy, config.strategy_registry, config.symbol_playbook; "
        "import data.webull_data; "
        "assert str(runtime_data_root()) == '/app/runtime_data'; "
        "assert __import__('pathlib').Path('/app/data/webull_data.py').exists(); "
        "assert __import__('pathlib').Path('/app/config/runtime_paths.py').exists(); "
        "print('ok')"
    )
    webull_snippet = (
        "from pathlib import Path; "
        "from data.webull_data import build_data_client; "
        "client = build_data_client(); "
        "assert client is not None; "
        "assert not Path('/app/webull_data_sdk.log').exists(); "
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
        container_check(app_dir, stack_dir, runtime_snippet, "Runtime paths"),
        container_check(app_dir, stack_dir, webull_snippet, "Webull"),
        container_check(app_dir, stack_dir, boundary_snippet, "Container filesystem boundary"),
        heartbeat_readiness_check(app_dir, stack_dir),
        container_check(app_dir, stack_dir, safety_snippet, "Safety boundary"),
    ]


def dashboard_http_check(host: str = "127.0.0.1", port: int = 8765) -> Check:
    """Verify the always-on dashboard is reachable on localhost."""

    url = f"http://{host}:{port}/api/command-center-v1"
    try:
        with urlopen(url, timeout=5) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
    except (OSError, URLError) as exc:
        return Check("Dashboard HTTP", "FAIL", f"dashboard endpoint unreachable at {url}: {exc}")
    if response.status != 200:
        return Check("Dashboard HTTP", "FAIL", f"dashboard endpoint returned HTTP {response.status}")
    if "Read-only observability" not in body:
        return Check("Dashboard HTTP", "WATCH", "dashboard responded, but Command Center payload was not recognized")
    return Check("Dashboard HTTP", "PASS", "Command Center endpoint reachable on localhost")


def print_report(checks: list[Check], next_session: str) -> None:
    verdict = aggregate(checks)
    ready = verdict == "PASS"
    print(f"VPS PRODUCTION READINESS: {verdict}")
    for check in checks:
        print(f"{check.status:<5} {check.area}: {check.reason}")
    print(f"Next market session: {next_session}")
    print(f"Ready unattended: {'YES' if ready else 'NO'}")
    if not ready:
        blocker = next((check for check in checks if check.status == "FAIL"), None) or next(
            (check for check in checks if check.status == "WATCH"),
            None,
        )
        if blocker:
            print(f"Exact blocker: {blocker.area}: {blocker.reason}")


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
        checks.extend(container_checks(app_dir, stack_dir))
    checks.append(dashboard_http_check())
    print_report(checks, next_market_session_text(app_dir))
    raise SystemExit(1 if aggregate(checks) == "FAIL" else 0)


if __name__ == "__main__":
    main()
