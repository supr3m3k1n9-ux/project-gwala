"""Build Project Gwala continuous assurance reports.

This command is a read-only control-plane runner. It coordinates existing
health, safety, preflight, sentinel, and audit checks into durable assurance
artifacts without changing strategy logic, gates, risk rules, research
thresholds, broker behavior, or scheduling.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.runtime_paths import project_root
from run_data_flow_sentinel import build_data_flow_sentinel
from run_dashboard_data_preflight import build_checks as build_dashboard_preflight
from run_playbook import markdown_table


ASSURANCE_ROOT = Path("logs/assurance")
HOST_DOCKER_HEALTH_PATH = Path(os.environ.get("GWALA_HOST_DOCKER_HEALTH_JSON", "logs/host_docker_health.json"))
HOST_SECURITY_HEALTH_PATH = Path(os.environ.get("GWALA_HOST_SECURITY_HEALTH_JSON", "logs/host_security_health.json"))
PRODUCTION_HEARTBEAT_PATH = Path(os.environ.get("GWALA_PRODUCTION_HEARTBEAT_JSON", "logs/production_heartbeat.json"))
SAFETY_ENV = {
    "GWALA_DEPLOYMENT_MODE": "shadow",
    "GWALA_SHADOW_MODE": "true",
    "GWALA_DISABLE_BROKER_EXECUTION": "true",
    "GWALA_LIVE_TRADING_ENABLED": "false",
    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
    "GWALA_REAL_MONEY_READY": "false",
}
AUTHORITATIVE_GOVERNANCE_FILES = [
    "OPERATING_DOCTRINE.md",
    "PROJECT_STATE.md",
    "STRATEGY_STATE.md",
    "DECISION_LOG.md",
    "ROADMAP.md",
    "HANDOFF.md",
]
CRITICAL_MODULES = [
    "run_production_heartbeat.py",
    "run_production_alert.py",
    "run_data_flow_sentinel.py",
    "run_dashboard_data_preflight.py",
    "run_system_state.py",
    "run_readiness_check.py",
    "run_autonomous_paper_workflow.py",
    "run_morning_index_orb_manual_paper_watch.py",
    "deploy/linux/preflight.py",
    "deploy/linux/write_host_docker_health.py",
    "deploy/linux/write_host_systemd_health.py",
]
LEDGER_FILES = {
    "vwap_official_validation": Path("data/paper_validation_samples.csv"),
    "vwap_paper_trades": Path("data/paper_trades.csv"),
    "candidate_window_ledger": Path("data/candidate_window_ledger.csv"),
    "orb_manual_paper_watch": Path("data/morning_index_orb_manual_paper_trades.csv"),
}
SECRET_NAMES = [
    "WEBULL_APP_KEY",
    "WEBULL_APP_SECRET",
    "WEBULL_REGION_ID",
    "POLYGON_API_KEY",
    "SMTP_PASSWORD",
    "SMTP_USERNAME",
    "GWALA_REPORT_EMAIL_TO",
]
REQUIRED_SECRET_ENV = ["WEBULL_APP_KEY", "WEBULL_APP_SECRET", "WEBULL_REGION_ID"]
CODE_SCAN_PATTERNS = [
    ("shell_true", re.compile(r"shell\s*=\s*True")),
    ("eval_call", re.compile(r"(?<![A-Za-z0-9_])eval\s*\(")),
    ("exec_call", re.compile(r"(?<![A-Za-z0-9_])exec\s*\(")),
    ("pickle_load", re.compile(r"pickle\.load\s*\(")),
    ("yaml_load", re.compile(r"yaml\.load\s*\(")),
    ("unsafe_temp", re.compile(r"NamedTemporaryFile\s*\([^)]*delete\s*=\s*False")),
]


@dataclass(frozen=True)
class AssuranceCheck:
    """One assurance control result."""

    component: str
    status: str
    reason: str
    business_impact: str = "None observed."
    research_impact: str = "None observed."
    operator_action_required: str = "NONE"
    engineering_trigger: str = "WAIT"
    affected_session: str = ""
    affected_strategy: str = ""
    recommended_next_action: str = "Continue monitoring."

    def as_dict(self) -> dict[str, str]:
        return {
            "component": self.component,
            "status": self.status,
            "reason": self.reason,
            "business_impact": self.business_impact,
            "research_impact": self.research_impact,
            "operator_action_required": self.operator_action_required,
            "engineering_trigger": self.engineering_trigger,
            "affected_session": self.affected_session,
            "affected_strategy": self.affected_strategy,
            "recommended_next_action": self.recommended_next_action,
        }


def now_et() -> datetime:
    return datetime.now(MARKET_TZ)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (pd.errors.EmptyDataError, OSError):
        return pd.DataFrame()


def parse_et_datetime(value: object) -> datetime | None:
    """Parse a saved ET timestamp without requiring the source module."""

    text = str(value or "").strip()
    if not text:
        return None
    parsed = pd.to_datetime(text.replace(" EDT", "-04:00").replace(" EST", "-05:00"), errors="coerce")
    if pd.isna(parsed):
        return None
    result = parsed.to_pydatetime()
    if result.tzinfo is None:
        result = result.replace(tzinfo=MARKET_TZ)
    return result.astimezone(MARKET_TZ)


def artifact_time(path: Path, payload: dict[str, Any]) -> datetime | None:
    """Return the best available timestamp for an assurance source artifact."""

    generated = parse_et_datetime(payload.get("generated_at_et") or payload.get("generated_at"))
    if generated:
        return generated
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=MARKET_TZ)


def artifact_is_fresh(path: Path, payload: dict[str, Any], moment: datetime, max_age_minutes: int) -> bool:
    """Return True when an artifact is recent enough to represent current state."""

    timestamp = artifact_time(path, payload)
    if timestamp is None:
        return False
    age = moment - timestamp.astimezone(MARKET_TZ)
    return timedelta(seconds=0) <= age <= timedelta(minutes=max_age_minutes)


def running_in_docker() -> bool:
    """Return True when this process appears to run inside a container."""

    if Path("/.dockerenv").exists():
        return True
    cgroup = Path("/proc/1/cgroup")
    if not cgroup.exists():
        return False
    try:
        text = cgroup.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return any(marker in text for marker in ["docker", "containerd", "kubepods"])


def run_command(command: list[str], timeout: int = 45) -> tuple[int, str]:
    """Run a read-only command and return a redacted short result."""

    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, redact_text(f"{type(exc).__name__}: {exc}")
    text = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, redact_text(text[-800:])


def redact_text(text: str) -> str:
    """Redact known secret values from subprocess output."""

    redacted = text
    for name in SECRET_NAMES:
        value = os.environ.get(name, "")
        if value and len(value) >= 4:
            redacted = redacted.replace(value, "<redacted>")
    return redacted


def run_test_command(command: list[str], timeout: int = 240) -> dict[str, Any]:
    """Run tests and preserve useful bounded failure diagnostics."""

    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
        stdout = redact_text(completed.stdout or "")
        stderr = redact_text(completed.stderr or "")
        combined = stdout + "\n" + stderr
        return {
            "return_code": completed.returncode,
            "stdout_tail": stdout[-1200:],
            "stderr_tail": stderr[-2400:],
            "failing_tests": extract_unittest_failures(combined),
            "failure_reason": extract_unittest_reason(combined),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "return_code": 127,
            "stdout_tail": "",
            "stderr_tail": redact_text(f"{type(exc).__name__}: {exc}"),
            "failing_tests": [],
            "failure_reason": redact_text(f"{type(exc).__name__}: {exc}"),
        }


def extract_unittest_failures(text: str) -> list[str]:
    """Extract unittest failure/error names from verbose output."""

    failures: list[str] = []
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith(("FAIL:", "ERROR:")):
            failures.append(clean)
        elif " ... FAIL" in clean or " ... ERROR" in clean:
            failures.append(clean.rsplit(" ... ", 1)[0])
    return failures[:20]


def extract_unittest_reason(text: str) -> str:
    """Return a concise assertion/error reason from unittest output."""

    lines = [line.rstrip() for line in text.splitlines()]
    interesting = []
    capture = False
    for line in lines:
        clean = line.strip()
        if clean.startswith(("FAIL:", "ERROR:")):
            capture = True
            interesting.append(clean)
            continue
        if capture and (
            clean.startswith(("AssertionError", "PermissionError", "FileNotFoundError", "ModuleNotFoundError"))
            or "Traceback" in clean
            or clean.startswith("E   ")
        ):
            interesting.append(clean)
        if capture and clean.startswith(("FAILED ", "OK")):
            capture = False
    if interesting:
        return redact_text(" | ".join(interesting[-8:]))[:1200]
    return redact_text(text[-1200:].strip())


def aggregate_status(checks: list[AssuranceCheck]) -> str:
    statuses = {check.status for check in checks}
    if "RED" in statuses:
        return "RED"
    if "WATCH" in statuses:
        return "WATCH"
    return "GREEN"


def confidence_from_checks(checks: list[AssuranceCheck]) -> str:
    statuses = {check.status for check in checks}
    if "RED" in statuses:
        return "LOW"
    if "WATCH" in statuses:
        return "MEDIUM"
    return "HIGH"


def check_safety_env(env: dict[str, str] | None = None) -> AssuranceCheck:
    values = env if env is not None else os.environ
    wrong = [
        f"{key}=<redacted>"
        for key, expected in SAFETY_ENV.items()
        if str(values.get(key, "")).strip().lower() != expected
    ]
    if wrong:
        return AssuranceCheck(
            "Paper-only safety environment",
            "RED",
            "Required shadow-mode safety flags are missing or not set to the approved values.",
            business_impact="Live-capital boundary cannot be trusted.",
            research_impact="Research may continue only after safety posture is restored.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            affected_strategy="all",
            recommended_next_action="Restore approved shadow-mode environment before autonomous operation.",
        )
    return AssuranceCheck("Paper-only safety environment", "GREEN", "Shadow-mode broker/live safety flags are enforced.")


def check_path_writable(path: Path, name: str) -> AssuranceCheck:
    if not path.exists():
        return AssuranceCheck(
            name,
            "RED",
            f"{path} does not exist.",
            business_impact="Evidence and assurance artifacts may not be saved.",
            research_impact="Research audit trail is incomplete.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Create the expected persistent directory with approved ownership/permissions.",
        )
    if os.access(path, os.W_OK):
        return AssuranceCheck(name, "GREEN", f"{path} is writable.")
    return AssuranceCheck(
        name,
        "RED",
        f"{path} is not writable.",
        business_impact="Evidence and assurance artifacts may not be saved.",
        research_impact="Research audit trail is incomplete.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
        recommended_next_action="Repair directory ownership/permissions.",
    )


def check_disk_capacity(path: Path, minimum_free_gb: float = 2.0) -> AssuranceCheck:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    if free_gb < minimum_free_gb:
        return AssuranceCheck(
            "Disk capacity",
            "RED",
            f"Free disk is {free_gb:.1f} GB, below {minimum_free_gb:.1f} GB.",
            business_impact="Artifacts/logs may stop writing.",
            research_impact="Evidence collection may become incomplete.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Free disk or expand storage.",
        )
    if free_gb < minimum_free_gb * 2:
        return AssuranceCheck(
            "Disk capacity",
            "WATCH",
            f"Free disk is {free_gb:.1f} GB.",
            business_impact="No immediate impact.",
            research_impact="Low storage runway if logs grow.",
            recommended_next_action="Review storage growth outside market hours.",
        )
    return AssuranceCheck("Disk capacity", "GREEN", f"Free disk is {free_gb:.1f} GB.")


def check_memory_pressure() -> AssuranceCheck:
    if platform.system() == "Darwin":
        code, text = run_command(["vm_stat"], timeout=10)
        if code != 0:
            return AssuranceCheck("Memory pressure", "WATCH", "Could not inspect macOS memory pressure.")
        return AssuranceCheck("Memory pressure", "GREEN", "macOS memory stats are inspectable.")
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return AssuranceCheck("Memory pressure", "WATCH", "Memory info is not inspectable on this platform.")
    fields: dict[str, int] = {}
    for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":") and parts[1].isdigit():
            fields[parts[0].rstrip(":")] = int(parts[1])
    total = fields.get("MemTotal", 0)
    available = fields.get("MemAvailable", 0)
    if not total or not available:
        return AssuranceCheck("Memory pressure", "WATCH", "Could not calculate available memory.")
    available_pct = available / total
    if available_pct < 0.08:
        return AssuranceCheck(
            "Memory pressure",
            "RED",
            f"Available memory is {available_pct:.0%}.",
            business_impact="Runtime instability risk is material.",
            research_impact="Scheduled jobs may fail or be killed.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Reduce load or increase VPS memory.",
        )
    if available_pct < 0.15:
        return AssuranceCheck("Memory pressure", "WATCH", f"Available memory is {available_pct:.0%}.")
    return AssuranceCheck("Memory pressure", "GREEN", f"Available memory is {available_pct:.0%}.")


def check_dashboard_localhost(env: dict[str, str] | None = None) -> AssuranceCheck:
    values = env if env is not None else os.environ
    host = str(values.get("GWALA_DASHBOARD_HOST", "127.0.0.1")).strip()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return AssuranceCheck("Dashboard exposure", "GREEN", f"Dashboard host is localhost-only: {host}.")
    return AssuranceCheck(
        "Dashboard exposure",
        "RED",
        f"Dashboard host is not localhost-only: {host}.",
        business_impact="Dashboard may be publicly exposed.",
        research_impact="No direct research impact, but operational security is weakened.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
        recommended_next_action="Bind dashboard to localhost or protect it behind an approved tunnel/proxy.",
    )


def check_host_docker_artifact(path: Path, moment: datetime, max_age_minutes: int = 15) -> AssuranceCheck:
    """Classify host Docker health from a host-generated artifact."""

    payload = read_json(path)
    if not payload:
        return AssuranceCheck(
            "Docker runtime",
            "WATCH",
            f"Host Docker health artifact is missing: {path}.",
            business_impact="Container runtime cannot be confirmed from inside the application container.",
            research_impact="No direct evidence impact if current workflow is running, but host control-plane state is unknown.",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Refresh host Docker health before containerized assurance runs.",
        )
    if not artifact_is_fresh(path, payload, moment, max_age_minutes):
        return AssuranceCheck(
            "Docker runtime",
            "WATCH",
            f"Host Docker health artifact is stale: {path}.",
            business_impact="Container runtime state may not reflect current host state.",
            research_impact="No direct evidence impact unless Docker is actually unhealthy.",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Refresh host Docker health before trusting runtime assurance.",
        )
    status = str(payload.get("status", "")).upper()
    if status == "GREEN":
        return AssuranceCheck("Docker runtime", "GREEN", "Host Docker health artifact reports GREEN.")
    if status in {"WATCH", "YELLOW", "UNKNOWN"}:
        return AssuranceCheck("Docker runtime", "WATCH", f"Host Docker health artifact reports {status}.")
    return AssuranceCheck(
        "Docker runtime",
        "RED",
        str(payload.get("red_reason") or payload.get("reason") or "Host Docker health artifact reports unhealthy Docker state."),
        business_impact="VPS container runtime is unhealthy.",
        research_impact="Autonomous shadow workflow may fail or stop collecting evidence.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
        recommended_next_action=str(payload.get("recommended_next_action") or "Inspect host Docker service and compose state."),
    )


def check_docker_runtime(
    *,
    host_docker_health_path: Path = HOST_DOCKER_HEALTH_PATH,
    moment: datetime | None = None,
    platform_name: str | None = None,
    in_docker: bool | None = None,
) -> AssuranceCheck:
    """Check Docker in the correct place for the current runtime boundary."""

    system_name = platform_name or platform.system()
    if system_name != "Linux":
        return AssuranceCheck("Docker runtime", "GREEN", "Docker runtime check is not required on macOS.")
    containerized = running_in_docker() if in_docker is None else in_docker
    if containerized:
        return check_host_docker_artifact(host_docker_health_path, moment or now_et())
    docker = shutil.which("docker")
    if not docker:
        return AssuranceCheck(
            "Docker runtime",
            "RED",
            "docker command is unavailable.",
            business_impact="VPS container runtime cannot be controlled.",
            research_impact="Autonomous shadow workflow may not run.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Repair Docker installation on the host.",
        )
    code, text = run_command([docker, "info", "--format", "{{json .ServerVersion}}"], timeout=15)
    if code != 0:
        return AssuranceCheck("Docker runtime", "RED", "Docker daemon is unavailable.", operator_action_required="YES")
    return AssuranceCheck("Docker runtime", "GREEN", "Docker daemon is reachable.")


def check_production_heartbeat_artifact(path: Path, moment: datetime, max_age_minutes: int = 15) -> AssuranceCheck:
    """Reuse the existing heartbeat artifact only when it is fresh."""

    payload = read_json(path)
    if not payload:
        return AssuranceCheck(
            "Production heartbeat",
            "WATCH",
            f"Production heartbeat artifact is missing: {path}.",
            business_impact="Current production state cannot be confirmed by assurance.",
            research_impact="Evidence may still be valid, but runtime status is unknown.",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Let the normal production heartbeat job refresh its artifact.",
        )
    status_text = str(payload.get("status", "missing")).upper()
    if not artifact_is_fresh(path, payload, moment, max_age_minutes):
        return AssuranceCheck(
            "Production heartbeat",
            "WATCH",
            f"Production heartbeat artifact is stale; last status was {status_text}.",
            business_impact="Historical heartbeat status is not a current outage signal.",
            research_impact="Do not use stale heartbeat RED to invalidate the current session.",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Wait for or run the approved heartbeat job; do not inherit stale RED as current RED.",
        )
    return summarize_existing_payload("Production heartbeat", payload, {"GREEN"}, {"YELLOW", "WATCH"})


def check_docker_daemon_not_remote() -> AssuranceCheck:
    hosts = os.environ.get("DOCKER_HOST", "").strip()
    if hosts.startswith("tcp://"):
        return AssuranceCheck(
            "Docker daemon exposure",
            "RED",
            "DOCKER_HOST points at a TCP Docker endpoint.",
            business_impact="Docker control plane may be exposed.",
            research_impact="Compromise could alter evidence or runtime state.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Use local Docker socket only unless a secured remote context is explicitly approved.",
        )
    return AssuranceCheck("Docker daemon exposure", "GREEN", "No remote Docker daemon endpoint is configured in this process.")


def summarize_existing_payload(component: str, payload: dict[str, Any], pass_values: set[str], watch_values: set[str]) -> AssuranceCheck:
    status_text = str(payload.get("status", "missing")).upper()
    if status_text in pass_values:
        return AssuranceCheck(component, "GREEN", f"Existing check reports {status_text}.")
    if status_text in watch_values:
        return AssuranceCheck(component, "WATCH", f"Existing check reports {status_text}.")
    return AssuranceCheck(
        component,
        "RED",
        f"Existing check reports {status_text}.",
        business_impact="A production control reported a blocking condition.",
        research_impact="Evidence may be incomplete or untrustworthy until reviewed.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
        affected_strategy="all",
        recommended_next_action=str(payload.get("next_action") or "Inspect the source report."),
    )


def build_runtime_smoke(args: argparse.Namespace) -> dict[str, Any]:
    start = time.monotonic()
    output_dir = args.output_dir
    current_time = now_et()
    checks = [
        check_docker_runtime(host_docker_health_path=args.host_docker_health_json, moment=current_time),
        check_production_heartbeat_artifact(args.production_heartbeat_json, current_time),
        check_path_writable(Path("data"), "Persistent data path"),
        check_path_writable(Path("logs"), "Persistent log path"),
        check_disk_capacity(Path(".")),
        check_memory_pressure(),
        check_safety_env(),
        check_dashboard_localhost(),
        check_docker_daemon_not_remote(),
    ]
    payload = base_payload("runtime_smoke", checks, start)
    payload["reused_components"] = [
        "logs/production_heartbeat.json",
        "logs/host_docker_health.json",
        "run_production_heartbeat.py artifact output",
    ]
    payload["runtime_boundaries"] = {
        "inside_application_container": [
            "data/log writability",
            "disk and memory visibility available to the process",
            "shadow safety environment",
            "dashboard localhost binding environment",
            "current process Docker endpoint environment",
        ],
        "host_os_artifacts": [
            str(args.host_docker_health_json),
            str(args.host_systemd_health_json),
        ],
        "existing_artifacts": [
            str(args.production_heartbeat_json),
        ],
    }
    write_layer_reports(output_dir / "runtime", "runtime_smoke", payload)
    return payload


def compile_critical_modules() -> list[AssuranceCheck]:
    checks: list[AssuranceCheck] = []
    for module in CRITICAL_MODULES:
        path = Path(module)
        if not path.exists():
            checks.append(AssuranceCheck("Python syntax", "RED", f"Critical module is missing: {module}."))
            continue
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            checks.append(
                AssuranceCheck(
                    "Python syntax",
                    "RED",
                    f"{module} has syntax error at line {exc.lineno}: {exc.msg}.",
                    business_impact="Critical workflow command may fail.",
                    research_impact="Session readiness cannot be trusted.",
                    operator_action_required="YES",
                    engineering_trigger="BUILD",
                    recommended_next_action="Fix syntax before market workflow starts.",
                )
            )
        except OSError as exc:
            checks.append(
                AssuranceCheck(
                    "Python syntax",
                    "RED",
                    f"{module} could not be read: {type(exc).__name__}: {exc}.",
                    business_impact="Critical workflow command cannot be audited.",
                    research_impact="Session readiness cannot be trusted.",
                    operator_action_required="YES",
                    engineering_trigger="INVESTIGATE",
                    recommended_next_action="Repair source readability without weakening permissions.",
                )
            )
        else:
            checks.append(
                AssuranceCheck("Python syntax", "GREEN", f"{module} parses without writing bytecode.")
            )
    return checks


def check_file_private(path: Path, label: str, required_if_exists: bool = False) -> AssuranceCheck:
    if not path.exists():
        status = "RED" if required_if_exists else "WATCH"
        return AssuranceCheck(label, status, f"{path} is missing.")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        return AssuranceCheck(
            label,
            "RED",
            f"{path} permissions are {oct(mode)}; group/other access is present.",
            business_impact="Secrets or tokens may be readable by unintended users.",
            research_impact="No direct research impact, but operational security is weakened.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Restrict secret/token file permissions to the service user.",
        )
    return AssuranceCheck(label, "GREEN", f"{path} permissions are {oct(mode)}.")


def check_required_secret_env(env: dict[str, str] | None = None) -> AssuranceCheck:
    """Verify required secret variable names are injected without printing values."""

    values = env if env is not None else os.environ
    missing = []
    placeholders = []
    for name in REQUIRED_SECRET_ENV:
        value = str(values.get(name, "")).strip()
        if not value:
            missing.append(name)
        elif value.lower().startswith(("your_", "paste_", "changeme", "replace_me")):
            placeholders.append(name)
    if missing or placeholders:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if placeholders:
            parts.append("placeholder: " + ", ".join(placeholders))
        return AssuranceCheck(
            "Secret environment variables",
            "RED",
            "; ".join(parts) + ".",
            business_impact="Required data-provider credentials are not available to the container.",
            research_impact="Premarket Webull/data readiness cannot be trusted.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Inject required variables through the approved host Compose env_file.",
        )
    return AssuranceCheck(
        "Secret environment variables",
        "GREEN",
        "Required secret variable names are present and non-placeholder; values redacted.",
    )


def check_host_security_artifact(path: Path, moment: datetime, max_age_minutes: int = 1440) -> AssuranceCheck:
    """Classify host-side security verification."""

    payload = read_json(path)
    if not payload:
        return AssuranceCheck(
            "Host security",
            "WATCH",
            "Host security/permission artifact is missing; Docker/Linux host controls are verified by host artifact.",
            business_impact="Host secret file permissions have not been confirmed by this container run.",
            research_impact="No direct research impact when env vars are injected.",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Run deploy/linux/write_host_security_health.py on the host.",
        )
    if not artifact_is_fresh(path, payload, moment, max_age_minutes):
        return AssuranceCheck(
            "Host security",
            "WATCH",
            f"Host security artifact is stale: {path}.",
            business_impact="Host secret file permission state may have changed.",
            research_impact="No direct research impact when env vars are injected.",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Refresh the host-side security artifact.",
        )
    status = str(payload.get("status", "")).upper()
    if status == "GREEN":
        return AssuranceCheck("Host security", "GREEN", "Host security artifact reports GREEN.")
    if status in {"WATCH", "YELLOW", "UNKNOWN"}:
        return AssuranceCheck("Host security", "WATCH", f"Host security artifact reports {status}.")
    return AssuranceCheck(
        "Host security",
        "RED",
        str(payload.get("red_reason") or payload.get("reason") or "Host security artifact reports unsafe secret permissions."),
        business_impact="Host secrets may be readable more broadly than intended.",
        research_impact="No direct research impact, but operational security is weakened.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
        recommended_next_action=str(payload.get("recommended_next_action") or "Restrict host secret file permissions."),
    )


def secret_configuration_checks(
    *,
    env_file: Path,
    host_security_json: Path,
    moment: datetime,
    platform_name: str | None = None,
    in_docker: bool | None = None,
    env: dict[str, str] | None = None,
) -> list[AssuranceCheck]:
    """Return environment/file secret checks for the active deployment boundary."""

    system_name = platform_name or platform.system()
    containerized = running_in_docker() if in_docker is None else in_docker
    if system_name == "Linux" and containerized:
        return [
            check_required_secret_env(env),
            check_host_security_artifact(host_security_json, moment),
        ]
    return [check_file_private(env_file, "Secret env file permissions", required_if_exists=False)]


def build_premarket_assurance(args: argparse.Namespace) -> dict[str, Any]:
    start = time.monotonic()
    current_time = now_et()
    checks = []
    checks.extend(compile_critical_modules())
    preflight_payload = build_dashboard_preflight(Path("logs"))
    checks.append(summarize_existing_payload("Dashboard data preflight", preflight_payload, {"PASS"}, {"WARN"}))
    checks.append(check_safety_env())
    checks.append(check_dashboard_localhost())
    checks.extend(
        secret_configuration_checks(
            env_file=args.env_file,
            host_security_json=args.host_security_json,
            moment=current_time,
        )
    )
    checks.append(check_file_private(Path(".webull_tokens/token.txt"), "Webull token file permissions", required_if_exists=False))
    if args.run_linux_preflight:
        command = [sys.executable, "deploy/linux/preflight.py", "--env-file", str(args.env_file)]
        if args.skip_network:
            command.append("--skip-network")
        command.append("--skip-systemd-verify")
        code, text = run_command(command, timeout=90)
        checks.append(
            AssuranceCheck(
                "Linux preflight",
                "GREEN" if code == 0 else "RED",
                "Linux preflight passed." if code == 0 else f"Linux preflight failed: {text}",
                operator_action_required="NONE" if code == 0 else "YES",
                engineering_trigger="WAIT" if code == 0 else "INVESTIGATE",
            )
        )
    else:
        checks.append(AssuranceCheck("Linux preflight", "WATCH", "Skipped by runner; enable with --run-linux-preflight."))
    if args.run_tests:
        test_result = run_test_command([sys.executable, "-m", "unittest", "tests.test_workflow_safety", "-v"], timeout=240)
        passed = int(test_result["return_code"]) == 0
        failure_detail = (
            f"return_code={test_result['return_code']}; "
            f"failing_tests={test_result['failing_tests']}; "
            f"reason={test_result['failure_reason']}; "
            f"stdout_tail={test_result['stdout_tail']}; stderr_tail={test_result['stderr_tail']}"
        )
        checks.append(
            AssuranceCheck(
                "Focused workflow safety tests",
                "GREEN" if passed else "RED",
                "Workflow safety tests passed." if passed else f"Workflow safety tests failed: {failure_detail}",
                operator_action_required="NONE" if passed else "YES",
                engineering_trigger="WAIT" if passed else "BUILD",
            )
        )
    else:
        checks.append(AssuranceCheck("Focused workflow safety tests", "WATCH", "Skipped by runner; enable with --run-tests."))
    status = "READY" if aggregate_status(checks) == "GREEN" else "BLOCKED" if aggregate_status(checks) == "RED" else "WATCH"
    payload = base_payload("premarket_assurance", checks, start)
    payload["readiness"] = status
    payload["reused_components"] = ["run_dashboard_data_preflight.py", "deploy/linux/preflight.py", "tests.test_workflow_safety"]
    payload["secret_configuration_model"] = {
        "macos_local": str(args.env_file),
        "docker_linux_container": "required secret names injected into process environment by host Compose env_file",
        "docker_linux_host_file": str(args.host_security_json),
        "expected_vps_host_secret_file": "/srv/projects/gwala/config/gwala.env",
    }
    write_layer_reports(args.output_dir / "premarket", "premarket_assurance", payload)
    return payload


def duplicate_key_check(frame: pd.DataFrame, columns: list[str], label: str) -> AssuranceCheck:
    if frame.empty:
        return AssuranceCheck(label, "WATCH", "Ledger is missing or empty.")
    usable = [column for column in columns if column in frame.columns]
    if not usable:
        return AssuranceCheck(label, "WATCH", "No known identity columns are present.")
    duplicates = frame.duplicated(subset=usable, keep=False).sum()
    if duplicates:
        return AssuranceCheck(
            label,
            "RED",
            f"{int(duplicates)} duplicate row(s) found by {', '.join(usable)}.",
            business_impact="Research counts may be overstated.",
            research_impact="Evidence integrity requires review before runway accounting.",
            operator_action_required="YES",
            engineering_trigger="INVESTIGATE",
            recommended_next_action="Review duplicates before counting the session as clean.",
        )
    return AssuranceCheck(label, "GREEN", f"No duplicate rows by {', '.join(usable)}.")


def timestamp_check(frame: pd.DataFrame, label: str) -> AssuranceCheck:
    if frame.empty:
        return AssuranceCheck(label, "WATCH", "Ledger is missing or empty.")
    candidates = [column for column in frame.columns if "time" in column.lower() or "date" in column.lower() or column.endswith("_at_et")]
    if not candidates:
        return AssuranceCheck(label, "WATCH", "No timestamp/date columns available for audit.")
    impossible = 0
    for column in candidates:
        values = pd.to_datetime(frame[column], errors="coerce")
        future = values.dropna() > (datetime.now() + timedelta(days=1))
        impossible += int(future.sum())
    if impossible:
        return AssuranceCheck(label, "RED", f"{impossible} future timestamp value(s) found.")
    return AssuranceCheck(label, "GREEN", f"Timestamp audit checked {len(candidates)} column(s).")


def contamination_check(vwap: pd.DataFrame, orb: pd.DataFrame) -> AssuranceCheck:
    if vwap.empty or orb.empty:
        return AssuranceCheck("Strategy ledger contamination", "WATCH", "One or both strategy ledgers are empty; contamination check is limited.")
    orb_setup_cols = [column for column in orb.columns if column in {"strategy_id", "strategy", "setup", "setup_family"}]
    vwap_setup_cols = [column for column in vwap.columns if column in {"strategy_id", "strategy", "setup", "setup_family"}]
    orb_text = " ".join(str(value).lower() for column in orb_setup_cols for value in orb[column].dropna().unique())
    vwap_text = " ".join(str(value).lower() for column in vwap_setup_cols for value in vwap[column].dropna().unique())
    if "opening" in vwap_text or "orb" in vwap_text:
        return AssuranceCheck("Strategy ledger contamination", "RED", "VWAP official ledger appears to contain ORB setup labels.")
    if "vwap" in orb_text:
        return AssuranceCheck("Strategy ledger contamination", "RED", "ORB ledger appears to contain VWAP setup labels.")
    return AssuranceCheck("Strategy ledger contamination", "GREEN", "VWAP and ORB ledger labels remain separate.")


def build_eod_integrity(args: argparse.Namespace) -> dict[str, Any]:
    start = time.monotonic()
    sentinel = build_data_flow_sentinel(Path("logs"))
    checks = [summarize_existing_payload("Data Flow Sentinel", sentinel, {"SYNCED"}, {"WATCH"})]
    ledgers = {name: read_csv(path) for name, path in LEDGER_FILES.items()}
    checks.extend(
        [
            duplicate_key_check(ledgers["vwap_official_validation"], ["symbol", "setup", "entry_time_et"], "VWAP official validation duplicates"),
            duplicate_key_check(ledgers["vwap_paper_trades"], ["symbol", "setup", "entry_time_et"], "VWAP paper trade duplicates"),
            duplicate_key_check(ledgers["candidate_window_ledger"], ["symbol", "setup", "latest_signal_et"], "Candidate ledger duplicates"),
            duplicate_key_check(ledgers["orb_manual_paper_watch"], ["symbol", "strategy_id", "entry_time_et"], "ORB manual paper-watch duplicates"),
            timestamp_check(ledgers["vwap_paper_trades"], "VWAP timestamp integrity"),
            timestamp_check(ledgers["orb_manual_paper_watch"], "ORB timestamp integrity"),
            contamination_check(ledgers["vwap_official_validation"], ledgers["orb_manual_paper_watch"]),
        ]
    )
    confidence = confidence_from_checks(checks)
    payload = base_payload("eod_evidence_integrity", checks, start)
    payload["evidence_confidence"] = confidence
    payload["session_valid_for_research_runway"] = "YES" if confidence == "HIGH" else "PARTIAL" if confidence == "MEDIUM" else "NO"
    payload["operational_exception_required"] = confidence == "LOW"
    payload["affected_strategies"] = affected_strategies(checks)
    payload["affected_time_windows"] = []
    payload["ledger_rows"] = {name: int(len(frame)) for name, frame in ledgers.items()}
    payload["reused_components"] = ["run_data_flow_sentinel.py", "authoritative ledger CSV artifacts"]
    write_layer_reports(args.output_dir / "eod", "eod_evidence_integrity", payload)
    return payload


def affected_strategies(checks: list[AssuranceCheck]) -> list[str]:
    values = sorted({check.affected_strategy for check in checks if check.status == "RED" and check.affected_strategy})
    return values


def files_to_scan(root: Path) -> list[Path]:
    ignored_parts = {".git", "__pycache__", ".venv", ".venv-webull", "logs", "data"}
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        if path.suffix in {".py", ".sh", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".service", ".timer"}:
            files.append(path)
    return files


def code_security_scan(root: Path) -> list[AssuranceCheck]:
    findings: dict[str, list[str]] = {name: [] for name, _ in CODE_SCAN_PATTERNS}
    secret_findings: list[str] = []
    for path in files_to_scan(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            for name, pattern in CODE_SCAN_PATTERNS:
                if pattern.search(line):
                    findings[name].append(f"{path}:{index}")
            for secret_name in SECRET_NAMES:
                if secret_name in line and "=" in line and not path.name.endswith(".example"):
                    secret_findings.append(f"{path}:{index}:{secret_name}")
    checks = []
    for name, locations in findings.items():
        if locations:
            checks.append(
                AssuranceCheck(
                    f"Code auditor {name}",
                    "RED",
                    f"{len(locations)} finding(s): {', '.join(locations[:8])}.",
                    business_impact="Security-sensitive code requires review.",
                    research_impact="No direct evidence impact unless runtime path is affected.",
                    operator_action_required="YES",
                    engineering_trigger="INVESTIGATE",
                    recommended_next_action="Review finding without exposing credentials.",
                )
            )
        else:
            checks.append(AssuranceCheck(f"Code auditor {name}", "GREEN", "No findings."))
    if secret_findings:
        checks.append(
            AssuranceCheck(
                "Code auditor hardcoded secret keys",
                "RED",
                f"{len(secret_findings)} potential secret assignment(s) found by key name; values redacted.",
                business_impact="Credentials may be committed or exposed.",
                research_impact="No direct evidence impact, but account security is weakened.",
                operator_action_required="YES",
                engineering_trigger="INVESTIGATE",
                recommended_next_action="Move secrets to environment/file-mounted secrets and rotate if exposed.",
            )
        )
    else:
        checks.append(AssuranceCheck("Code auditor hardcoded secret keys", "GREEN", "No non-example secret assignments found."))
    return checks


def governance_file_check(root: Path) -> list[AssuranceCheck]:
    checks = []
    for name in AUTHORITATIVE_GOVERNANCE_FILES:
        path = root / name
        if path.exists() and path.stat().st_size > 0:
            checks.append(AssuranceCheck(f"Governance file {name}", "GREEN", "Present."))
        else:
            checks.append(AssuranceCheck(f"Governance file {name}", "RED", "Missing or empty.", engineering_trigger="INVESTIGATE"))
    return checks


def git_inventory_check(root: Path) -> AssuranceCheck:
    if not (root / ".git").exists():
        return AssuranceCheck("Git/worktree inventory", "WATCH", "No Git repository found.")
    code, text = run_command(["git", "status", "--short"], timeout=20)
    if code != 0:
        return AssuranceCheck("Git/worktree inventory", "WATCH", "Could not read git status.")
    changed = len([line for line in text.splitlines() if line.strip()])
    status = "WATCH" if changed else "GREEN"
    return AssuranceCheck(
        "Git/worktree inventory",
        status,
        f"{changed} changed/untracked path(s) present.",
        recommended_next_action="Review authorization in DECISION_LOG before deployment." if changed else "Continue.",
    )


def dependency_drift_check(root: Path) -> AssuranceCheck:
    dependency_files = [root / "requirements.txt", root / "requirements-webull.txt"]
    missing = [str(path) for path in dependency_files if not path.exists()]
    if missing:
        return AssuranceCheck("Dependency files", "RED", "Missing dependency file(s): " + ", ".join(missing))
    unpinned = []
    for path in dependency_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#") and "==" not in clean:
                unpinned.append(f"{path.name}:{clean.split()[0]}")
    if unpinned:
        return AssuranceCheck(
            "Dependency pinning",
            "WATCH",
            f"{len(unpinned)} dependency spec(s) are not exact pins.",
            recommended_next_action="Pin or lock dependencies before Tiny Live.",
        )
    return AssuranceCheck("Dependency pinning", "GREEN", "Dependencies are exactly pinned.")


def live_boundary_scan(root: Path) -> AssuranceCheck:
    files = files_to_scan(root)
    references = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "GWALA_LIVE_TRADING_ENABLED" in text or "GWALA_BROKER_ORDER_EXECUTION_ENABLED" in text:
            references.append(str(path))
    if references:
        return AssuranceCheck(
            "Live-capital boundary audit",
            "GREEN",
            f"Live/broker safety flags are referenced in {len(set(references))} file(s).",
        )
    return AssuranceCheck(
        "Live-capital boundary audit",
        "RED",
        "No live/broker safety flag references found.",
        business_impact="Defense-in-depth cannot be confirmed.",
        research_impact="Paper-only safety boundary requires review.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
    )


def build_weekly_deep_assurance(args: argparse.Namespace) -> dict[str, Any]:
    start = time.monotonic()
    root = args.project_root
    checks = []
    checks.extend(compile_critical_modules())
    checks.extend(code_security_scan(root))
    checks.extend(governance_file_check(root))
    checks.append(git_inventory_check(root))
    checks.append(dependency_drift_check(root))
    checks.append(live_boundary_scan(root))
    checks.append(check_safety_env())
    if args.run_tests:
        test_result = run_test_command([sys.executable, "-m", "unittest", "-v"], timeout=420)
        passed = int(test_result["return_code"]) == 0
        failure_detail = (
            f"return_code={test_result['return_code']}; "
            f"failing_tests={test_result['failing_tests']}; "
            f"reason={test_result['failure_reason']}; "
            f"stdout_tail={test_result['stdout_tail']}; stderr_tail={test_result['stderr_tail']}"
        )
        checks.append(
            AssuranceCheck(
                "Complete unittest suite",
                "GREEN" if passed else "RED",
                "Complete unittest suite passed." if passed else f"Complete unittest suite failed: {failure_detail}",
                operator_action_required="NONE" if passed else "YES",
                engineering_trigger="WAIT" if passed else "BUILD",
            )
        )
    else:
        checks.append(AssuranceCheck("Complete unittest suite", "WATCH", "Skipped by runner; enable with --run-tests."))
    payload = base_payload("weekly_deep_assurance", checks, start)
    payload["reused_components"] = ["read-only Python syntax compile()", "unittest", "git status", "governance files", "dependency files"]
    write_layer_reports(args.output_dir / "weekly", "weekly_deep_assurance", payload)
    return payload


def self_monitor(args: argparse.Namespace, layers: list[dict[str, Any]]) -> dict[str, Any]:
    start = time.monotonic()
    expected = [
        ("runtime_smoke", args.output_dir / "runtime" / "runtime_smoke.json", timedelta(minutes=15)),
        ("premarket_assurance", args.output_dir / "premarket" / "premarket_assurance.json", timedelta(days=2)),
        ("eod_evidence_integrity", args.output_dir / "eod" / "eod_evidence_integrity.json", timedelta(days=2)),
        ("weekly_deep_assurance", args.output_dir / "weekly" / "weekly_deep_assurance.json", timedelta(days=8)),
    ]
    checks = []
    current = datetime.now().astimezone()
    for name, path, max_age in expected:
        if any(layer.get("layer") == name for layer in layers):
            checks.append(AssuranceCheck(f"Assurance self-monitor {name}", "GREEN", "Ran in current invocation."))
            continue
        if not path.exists():
            checks.append(
                AssuranceCheck(
                    f"Assurance self-monitor {name}",
                    "WATCH",
                    f"Expected artifact is missing: {path}.",
                    research_impact="Assurance coverage is incomplete.",
                    engineering_trigger="INVESTIGATE",
                    recommended_next_action="Run the missing assurance layer or install reviewed timers.",
                )
            )
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        age = current - modified
        status = "GREEN" if age <= max_age else "RED"
        checks.append(
            AssuranceCheck(
                f"Assurance self-monitor {name}",
                status,
                f"Last run artifact age is {age}.",
                operator_action_required="NONE" if status == "GREEN" else "YES",
                engineering_trigger="WAIT" if status == "GREEN" else "INVESTIGATE",
                recommended_next_action="Investigate missing assurance schedule." if status == "RED" else "Continue.",
            )
        )
    payload = base_payload("assurance_self_monitor", checks, start)
    return payload


def base_payload(layer: str, checks: list[AssuranceCheck], start: float) -> dict[str, Any]:
    status = aggregate_status(checks)
    red_checks = [check for check in checks if check.status == "RED"]
    payload: dict[str, Any] = {
        "layer": layer,
        "status": status,
        "generated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "duration_seconds": round(time.monotonic() - start, 3),
        "checks": [check.as_dict() for check in checks],
        "guardrail": "Read-only assurance. No strategy, gate, risk, research, broker, trading, or scheduling changes.",
    }
    if red_checks:
        first = red_checks[0]
        payload.update(
            {
                "red_component": first.component,
                "red_reason": first.reason,
                "business_impact": first.business_impact,
                "research_impact": first.research_impact,
                "operator_action_required": first.operator_action_required,
                "engineering_trigger": first.engineering_trigger,
                "affected_session": first.affected_session,
                "affected_strategy": first.affected_strategy,
                "recommended_next_action": first.recommended_next_action,
            }
        )
    return payload


def write_layer_reports(directory: Path, stem: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    payload["artifact_path"] = str(json_path)
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    checks = pd.DataFrame(payload["checks"])
    md_path.write_text(
        f"""# Project Gwala Assurance: {stem.replace('_', ' ').title()}

Status: {payload["status"]}
Generated: {payload["generated_at_et"]}
Duration Seconds: {payload["duration_seconds"]}

## Checks

{markdown_table(checks)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )
    return json_path, md_path


def write_state(args: argparse.Namespace, layers: list[dict[str, Any]]) -> dict[str, Any]:
    monitor = self_monitor(args, layers)
    all_layers = layers + [monitor]
    status = aggregate_status([AssuranceCheck(layer["layer"], layer["status"], layer.get("red_reason") or "Layer result.") for layer in all_layers])
    state = {
        "generated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "layers": [
            {
                "layer": layer["layer"],
                "status": layer["status"],
                "last_run": layer.get("generated_at_et", ""),
                "duration_seconds": layer.get("duration_seconds", 0),
                "artifact_path": layer.get("artifact_path", ""),
                "next_expected_run": proposed_next_run(layer["layer"]),
            }
            for layer in all_layers
        ],
        "guardrail": "Assurance state summary only. No production, research, broker, or scheduling changes.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "assurance_state.json"
    md_path = args.output_dir / "assurance_state.md"
    state["artifact_path"] = str(json_path)
    json_path.write_text(json.dumps(state, indent=2, allow_nan=False), encoding="utf-8")
    md_path.write_text(
        f"""# Project Gwala Assurance State

Status: {state["status"]}
Generated: {state["generated_at_et"]}

## Layers

{markdown_table(pd.DataFrame(state["layers"]))}

## Guardrail

```text
{state["guardrail"]}
```
""",
        encoding="utf-8",
    )
    return state


def proposed_next_run(layer: str) -> str:
    return {
        "runtime_smoke": "Every 5 minutes during production hours; lightweight only.",
        "premarket_assurance": "Before market workflow begins, e.g. 06:10 PT.",
        "eod_evidence_integrity": "After final report maturity, e.g. 13:40 PT.",
        "weekly_deep_assurance": "Weekend/non-market hours.",
        "assurance_self_monitor": "Every assurance run.",
    }.get(layer, "Unknown.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Project Gwala continuous assurance.")
    parser.add_argument(
        "--layer",
        choices=["runtime", "premarket", "eod", "weekly", "state", "all"],
        default="runtime",
        help="Assurance layer to run.",
    )
    parser.add_argument("--output-dir", type=Path, default=ASSURANCE_ROOT)
    parser.add_argument("--project-root", type=Path, default=project_root())
    parser.add_argument("--env-file", type=Path, default=Path(os.environ.get("GWALA_ENV_FILE", ".env")))
    parser.add_argument("--host-systemd-health-json", type=Path, default=Path(os.environ.get("GWALA_HOST_SYSTEMD_HEALTH_JSON", "logs/host_systemd_health.json")))
    parser.add_argument("--host-docker-health-json", type=Path, default=HOST_DOCKER_HEALTH_PATH)
    parser.add_argument("--host-security-json", type=Path, default=HOST_SECURITY_HEALTH_PATH)
    parser.add_argument("--production-heartbeat-json", type=Path, default=PRODUCTION_HEARTBEAT_PATH)
    parser.add_argument("--skip-network", action="store_true")
    parser.add_argument("--run-tests", action="store_true", help="Run unittest suites for premarket/weekly layers.")
    parser.add_argument("--run-linux-preflight", action="store_true", help="Run deploy/linux/preflight.py during premarket assurance.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.project_root = args.project_root.resolve()
    layers: list[dict[str, Any]] = []
    if args.layer in {"runtime", "all"}:
        layers.append(build_runtime_smoke(args))
    if args.layer in {"premarket", "all"}:
        layers.append(build_premarket_assurance(args))
    if args.layer in {"eod", "all"}:
        layers.append(build_eod_integrity(args))
    if args.layer in {"weekly", "all"}:
        layers.append(build_weekly_deep_assurance(args))
    state = write_state(args, layers)
    print(f"Assurance status: {state['status']}")
    print(f"Saved assurance state: {args.output_dir / 'assurance_state.json'}")
    if state["status"] == "RED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
