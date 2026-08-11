"""Verify that autonomous paper production is actually alive.

This is an operational heartbeat for the paper-collection experiment. It only
reads scheduler state and workflow artifacts. It does not change strategy
logic, thresholds, gates, paper trades, or broker behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.runtime_paths import runtime_data_root
from config.settings import STRATEGY
from run_autonomous_paper_workflow import parse_clock
from run_playbook import markdown_table


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = runtime_data_root()
LAUNCH_AGENT_LABEL = "com.project-gwala.autonomous-paper"
SYSTEMD_SERVICE = "project-gwala-autonomous-paper.service"
SCANNER_TRANSIENT_TOLERANCE_SECONDS = 90
HOST_SYSTEMD_HEALTH_PATH = Path(os.environ.get("GWALA_HOST_SYSTEMD_HEALTH_JSON", "logs/host_systemd_health.json"))
REQUIRED_SHADOW_ENV = {
    "GWALA_DEPLOYMENT_MODE": "shadow",
    "GWALA_SHADOW_MODE": "true",
    "GWALA_DISABLE_BROKER_EXECUTION": "true",
    "GWALA_LIVE_TRADING_ENABLED": "false",
    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
    "GWALA_REAL_MONEY_READY": "false",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the production heartbeat report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Where durable data artifacts are stored.")
    parser.add_argument("--interval-minutes", type=int, default=5, help="Expected production scan interval.")
    parser.add_argument(
        "--host-systemd-health-json",
        type=Path,
        default=HOST_SYSTEMD_HEALTH_PATH,
        help="Host-generated systemd health artifact for Docker/Linux shadow deployments.",
    )
    return parser.parse_args()


def now_et() -> datetime:
    """Return current New York time."""

    return datetime.now(tz=MARKET_TZ)


def resolve_host_systemd_health_path(path: Path | None = None) -> Path:
    """Return the host systemd artifact path for Linux/Docker heartbeats."""

    if path is not None:
        return path
    configured = os.environ.get("GWALA_HOST_SYSTEMD_HEALTH_JSON", "").strip()
    if configured:
        return Path(configured)
    if running_in_docker():
        return Path("/app/logs/host_systemd_health.json")
    return HOST_SYSTEMD_HEALTH_PATH


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object if it exists and is valid."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and is valid."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def modified_at_et(path: Path) -> datetime | None:
    """Return a file modification timestamp in market time."""

    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=MARKET_TZ)


def parse_et_datetime(value: object) -> datetime | None:
    """Parse a saved ET timestamp."""

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


def is_today(value: datetime | None, today: object) -> bool:
    """Return True when value falls on today's market date."""

    return bool(value and value.astimezone(MARKET_TZ).date() == today)


def recent_enough(value: datetime | None, moment: datetime, max_age_minutes: int) -> bool:
    """Return True when a timestamp is recent enough for market-hours heartbeat."""

    if value is None:
        return False
    age = moment - value.astimezone(MARKET_TZ)
    return timedelta(seconds=0) <= age <= timedelta(minutes=max_age_minutes)


def within_transient_tolerance(
    value: datetime | None,
    moment: datetime,
    max_age_minutes: int,
    tolerance_seconds: int,
) -> bool:
    """Return True when an artifact is only slightly past its expected refresh window."""

    if value is None:
        return False
    age = moment - value.astimezone(MARKET_TZ)
    return timedelta(minutes=max_age_minutes) < age <= timedelta(minutes=max_age_minutes, seconds=tolerance_seconds)


def expected_scan_due(moment: datetime) -> bool:
    """Return True after the first regular-session scan should have completed."""

    session = market_session_for_date(
        moment.date(),
        regular_open=parse_clock(STRATEGY.market_open),
        regular_close=parse_clock(STRATEGY.market_close),
    )
    if not session.is_market_day or session.market_open is None:
        return False
    return moment >= session.market_open + timedelta(minutes=5)


def market_scan_recency_required(moment: datetime) -> bool:
    """Return True while production should still be scanning every interval."""

    return session_context(moment)["requires_recency"]


def previous_market_session_date(moment: datetime, max_days: int = 14) -> object:
    """Return the most recent completed market-session date before moment."""

    local = moment.astimezone(MARKET_TZ)
    regular_open = parse_clock(STRATEGY.market_open)
    regular_close = parse_clock(STRATEGY.market_close)
    for offset in range(1, max_days + 1):
        candidate = market_session_for_date(local.date() - timedelta(days=offset), regular_open, regular_close)
        if candidate.is_market_day:
            return candidate.session_date
    return local.date()


def session_context(moment: datetime) -> dict[str, Any]:
    """Return heartbeat artifact expectations for the current market phase."""

    local = moment.astimezone(MARKET_TZ)
    session = market_session_for_date(
        local.date(),
        regular_open=parse_clock(STRATEGY.market_open),
        regular_close=parse_clock(STRATEGY.market_close),
    )
    if not session.is_market_day or session.market_open is None or session.market_close is None:
        return {
            "phase": "closed_day",
            "expected_artifact_date": previous_market_session_date(local),
            "requires_recency": False,
            "reason": session.reason,
        }
    if local < session.market_open:
        return {
            "phase": "premarket",
            "expected_artifact_date": session.session_date,
            "requires_recency": False,
            "reason": "Before regular session open.",
        }
    if local <= session.market_close:
        return {
            "phase": "regular_session",
            "expected_artifact_date": session.session_date,
            "requires_recency": local >= session.market_open + timedelta(minutes=5),
            "reason": session.reason,
        }
    return {
        "phase": "after_close",
        "expected_artifact_date": session.session_date,
        "requires_recency": False,
        "reason": "Regular session has closed.",
    }


def launchctl_text() -> str:
    """Read launchd state for the autonomous paper LaunchAgent."""

    command = ["launchctl", "print", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"]
    try:
        return subprocess.run(command, check=False, text=True, capture_output=True).stdout
    except OSError as exc:
        return f"launchctl_error: {exc}"


def systemd_text(service_name: str = SYSTEMD_SERVICE) -> str:
    """Read systemd state for the autonomous paper service."""

    command = ["systemctl", "show", service_name, "--no-page"]
    try:
        return subprocess.run(command, check=False, text=True, capture_output=True).stdout
    except OSError as exc:
        return f"systemd_error: {exc}"


def running_in_docker() -> bool:
    """Return True when this process appears to be running inside a container."""

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


def launch_agent_check(text: str) -> dict[str, Any]:
    """Classify the LaunchAgent state."""

    if not text.strip():
        return {
            "status": "RED",
            "component": "LaunchAgent",
            "reason": "LaunchAgent state is missing.",
            "details": "",
        }
    if "Could not find service" in text or "launchctl_error:" in text:
        return {
            "status": "RED",
            "component": "LaunchAgent",
            "reason": "LaunchAgent is not loaded.",
            "details": text.strip().splitlines()[0],
        }
    if "last exit code = 0" in text or "last exit code = (never exited)" in text or "state = running" in text:
        return {
            "status": "GREEN",
            "component": "LaunchAgent",
            "reason": "LaunchAgent is loaded and has no failing exit code.",
            "details": "",
        }
    for line in text.splitlines():
        if "last exit code =" in line:
            return {
                "status": "RED",
                "component": "LaunchAgent",
                "reason": f"LaunchAgent has failing {line.strip()}.",
                "details": line.strip(),
            }
    return {
        "status": "YELLOW",
        "component": "LaunchAgent",
        "reason": "LaunchAgent is loaded but exit state is unclear.",
        "details": "",
    }


def systemd_service_check(text: str, service_name: str = SYSTEMD_SERVICE) -> dict[str, Any]:
    """Classify the systemd unit state."""

    if not text.strip():
        return {
            "status": "RED",
            "component": "systemd service",
            "reason": f"{service_name} state is missing.",
            "details": "",
        }
    if "systemd_error:" in text:
        return {
            "status": "RED",
            "component": "systemd service",
            "reason": "systemctl is unavailable or failed.",
            "details": text.strip().splitlines()[0],
        }
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    load_state = fields.get("LoadState", "")
    active_state = fields.get("ActiveState", "")
    result = fields.get("Result", "")
    exec_status = fields.get("ExecMainStatus", "")
    if load_state == "not-found":
        return {
            "status": "RED",
            "component": "systemd service",
            "reason": f"{service_name} is not installed.",
            "details": "LoadState=not-found",
        }
    if result not in {"", "success"} or exec_status not in {"", "0"}:
        return {
            "status": "RED",
            "component": "systemd service",
            "reason": f"{service_name} has failing Result={result or 'unknown'} ExecMainStatus={exec_status or 'unknown'}.",
            "details": f"ActiveState={active_state}; LoadState={load_state}",
        }
    if active_state in {"active", "inactive"} and load_state == "loaded":
        return {
            "status": "GREEN",
            "component": "systemd service",
            "reason": f"{service_name} is loaded and has no failing exit code.",
            "details": f"ActiveState={active_state}",
        }
    return {
        "status": "YELLOW",
        "component": "systemd service",
        "reason": f"{service_name} is loaded but state is unclear.",
        "details": f"ActiveState={active_state}; LoadState={load_state}; Result={result}",
    }


def host_systemd_artifact_check(path: Path, moment: datetime, max_age_minutes: int) -> dict[str, Any]:
    """Classify host systemd health from a host-generated JSON artifact."""

    payload = read_json_or_empty(path)
    mtime = modified_at_et(path)
    if not payload:
        return {
            "status": "YELLOW",
            "component": "host systemd health",
            "reason": "Host systemd health artifact is missing inside the container.",
            "details": str(path),
        }
    generated = parse_et_datetime(payload.get("generated_at_et") or payload.get("generated_at"))
    artifact_time = generated or mtime
    if not recent_enough(artifact_time, moment, max_age_minutes):
        return {
            "status": "YELLOW",
            "component": "host systemd health",
            "reason": "Host systemd health artifact is stale.",
            "details": str(path),
        }
    status = str(payload.get("status", "")).upper()
    if status == "RED":
        failing = payload.get("red_component") or payload.get("failing_unit") or "Project Gwala host systemd unit"
        reason = payload.get("red_reason") or payload.get("reason") or "Host systemd health artifact reports failure."
        return {
            "status": "RED",
            "component": "host systemd health",
            "reason": str(reason),
            "details": str(failing),
        }
    if status in {"GREEN", "YELLOW"}:
        return {
            "status": status,
            "component": "host systemd health",
            "reason": str(payload.get("reason") or f"Host systemd health artifact reports {status}."),
            "details": str(path),
        }
    return {
        "status": "YELLOW",
        "component": "host systemd health",
        "reason": "Host systemd health artifact has an unknown status.",
        "details": str(path),
    }


def shadow_safety_check(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Verify Linux/Docker shadow mode cannot represent live-capital readiness."""

    values = env if env is not None else os.environ
    mismatches = [
        f"{key}={values.get(key, '') or '<missing>'}"
        for key, expected in REQUIRED_SHADOW_ENV.items()
        if str(values.get(key, "")).lower() != expected
    ]
    if mismatches:
        detail = "; ".join(mismatches)
        return {
            "status": "RED",
            "component": "shadow safety posture",
            "reason": f"Required shadow-mode broker/live safety environment is not enforced: {detail}",
            "details": detail,
        }
    return {
        "status": "GREEN",
        "component": "shadow safety posture",
        "reason": "Shadow-mode broker/live safety environment is enforced.",
        "details": "",
    }


def scheduler_check(
    launchctl_output: str | None = None,
    systemd_output: str | None = None,
    *,
    platform_name: str | None = None,
    in_docker: bool | None = None,
    host_systemd_health_path: Path | None = HOST_SYSTEMD_HEALTH_PATH,
    moment: datetime | None = None,
    max_age_minutes: int = 12,
) -> dict[str, Any]:
    """Use launchctl on macOS and systemd on Linux."""

    system_name = platform_name or platform.system()
    if system_name == "Linux":
        containerized = running_in_docker() if in_docker is None else in_docker
        if containerized:
            resolved_path = resolve_host_systemd_health_path(host_systemd_health_path)
            return host_systemd_artifact_check(resolved_path, moment or now_et(), max_age_minutes)
        return systemd_service_check(systemd_output if systemd_output is not None else systemd_text())
    return launch_agent_check(launchctl_output if launchctl_output is not None else launchctl_text())


def scanner_check(output_dir: Path, expected_session_date: object, moment: datetime, max_age_minutes: int) -> dict[str, Any]:
    """Verify scanner rows belong to the expected session and are recent when market-hours scans are active."""

    path = output_dir / "daily_paper_signal_scanner.csv"
    scanner = read_csv_or_empty(path)
    mtime = modified_at_et(path)
    if scanner.empty or "scan_date" not in scanner.columns:
        return {"status": "RED", "component": "Scanner", "reason": "Scanner output is missing or unreadable."}
    dates = pd.to_datetime(scanner["scan_date"], errors="coerce").dropna()
    if dates.empty or dates.dt.date.max() != expected_session_date:
        return {"status": "RED", "component": "Scanner", "reason": "Scanner session date is stale."}
    if market_scan_recency_required(moment) and not recent_enough(mtime, moment, max_age_minutes):
        if within_transient_tolerance(mtime, moment, max_age_minutes, SCANNER_TRANSIENT_TOLERANCE_SECONDS):
            return {
                "status": "YELLOW",
                "component": "Scanner",
                "reason": "Scanner write is slightly delayed but still within the transient tolerance window.",
                "rows": int(len(scanner)),
                "modified_at_et": mtime.strftime("%Y-%m-%d %H:%M:%S %Z") if mtime else "",
            }
        return {"status": "RED", "component": "Scanner", "reason": "Latest scanner write is not recent."}
    return {
        "status": "GREEN",
        "component": "Scanner",
        "reason": "Scanner artifact matches the expected market session.",
        "rows": int(len(scanner)),
        "modified_at_et": mtime.strftime("%Y-%m-%d %H:%M:%S %Z") if mtime else "",
    }


def webull_check(data_dir: Path, expected_session_date: object, moment: datetime, max_age_minutes: int) -> dict[str, Any]:
    """Verify Webull refresh audit has expected-session rows."""

    path = data_dir / "market_refresh_audit.csv"
    audit = read_csv_or_empty(path)
    mtime = modified_at_et(path)
    required = {"refresh_run_at_et", "m30_latest_session", "m5_latest_session"}
    if audit.empty or not required.issubset(set(audit.columns)):
        return {"status": "RED", "component": "Webull refresh", "reason": "Webull refresh audit is missing."}
    audit = audit.copy()
    audit["_run_at"] = audit["refresh_run_at_et"].map(parse_et_datetime)
    today_rows = audit[audit["_run_at"].map(lambda value: is_today(value, expected_session_date))]
    if today_rows.empty:
        return {"status": "RED", "component": "Webull refresh", "reason": "No Webull refresh rows exist for the expected session."}
    if not (
        today_rows["m30_latest_session"].astype(str).eq(str(expected_session_date)).any()
        and today_rows["m5_latest_session"].astype(str).eq(str(expected_session_date)).any()
    ):
        return {"status": "RED", "component": "Webull refresh", "reason": "Webull data is previous-session."}
    if market_scan_recency_required(moment) and not recent_enough(mtime, moment, max_age_minutes):
        return {"status": "RED", "component": "Webull refresh", "reason": "Webull refresh audit is not recent."}
    return {
        "status": "GREEN",
        "component": "Webull refresh",
        "reason": "Webull refresh has expected-session evidence.",
        "rows_today": int(len(today_rows)),
        "modified_at_et": mtime.strftime("%Y-%m-%d %H:%M:%S %Z") if mtime else "",
    }


def json_artifact_check(
    path: Path,
    *,
    component: str,
    expected_session_date: object,
    moment: datetime,
    max_age_minutes: int,
    required_status: str | None = None,
    missing_status: str = "RED",
) -> dict[str, Any]:
    """Verify a JSON artifact exists, belongs to the expected session, and is recent when required."""

    payload = read_json_or_empty(path)
    mtime = modified_at_et(path)
    generated = parse_et_datetime(payload.get("generated_at_et") or payload.get("generated_at"))
    artifact_time = generated or mtime
    if not payload:
        return {"status": missing_status, "component": component, "reason": f"{component} artifact is missing."}
    if required_status and str(payload.get("status", "")).lower() != required_status.lower():
        return {
            "status": "RED",
            "component": component,
            "reason": f"{component} status is {payload.get('status', 'missing')}, not {required_status}.",
        }
    if not is_today(artifact_time, expected_session_date):
        return {"status": missing_status, "component": component, "reason": f"{component} artifact is stale."}
    if market_scan_recency_required(moment) and not recent_enough(mtime, moment, max_age_minutes):
        return {"status": missing_status, "component": component, "reason": f"{component} artifact is not recent."}
    return {
        "status": "GREEN",
        "component": component,
        "reason": f"{component} artifact is current.",
        "modified_at_et": mtime.strftime("%Y-%m-%d %H:%M:%S %Z") if mtime else "",
    }


def after_close_supervisor_check(output_dir: Path, expected_session_date: object) -> dict[str, Any]:
    """Verify the autonomous supervisor transitioned into the after-close workflow."""

    path = output_dir / "autonomous_paper_workflow_status.json"
    payload = read_json_or_empty(path)
    if not payload:
        return {
            "status": "YELLOW",
            "component": "After-close supervisor",
            "reason": "After-close supervisor status artifact is missing.",
        }
    generated = parse_et_datetime(payload.get("generated_at_et") or payload.get("generated_at"))
    if not is_today(generated, expected_session_date):
        return {
            "status": "YELLOW",
            "component": "After-close supervisor",
            "reason": "After-close supervisor status artifact is stale.",
        }
    decision = str(payload.get("decision", "") or payload.get("action", "")).strip()
    if decision != "after_close_recap":
        return {
            "status": "YELLOW",
            "component": "After-close supervisor",
            "reason": f"Autonomous supervisor decision is {decision or 'missing'}, not after_close_recap.",
        }
    return {
        "status": "GREEN",
        "component": "After-close supervisor",
        "reason": "Autonomous supervisor completed the after-close recap transition.",
    }


def aggregate_status(checks: list[dict[str, Any]]) -> str:
    """Return the overall heartbeat status."""

    statuses = {check["status"] for check in checks}
    if "RED" in statuses:
        return "RED"
    if "YELLOW" in statuses:
        return "YELLOW"
    return "GREEN"


def build_heartbeat(
    output_dir: Path,
    *,
    data_dir: Path = DATA_DIR,
    moment: datetime | None = None,
    interval_minutes: int = 5,
    launchctl_output: str | None = None,
    systemd_output: str | None = None,
    platform_name: str | None = None,
    in_docker: bool | None = None,
    host_systemd_health_path: Path | None = HOST_SYSTEMD_HEALTH_PATH,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build production heartbeat state from scheduler state and artifacts."""

    current_time = moment or now_et()
    today = current_time.date()
    context = session_context(current_time)
    expected_session_date = context["expected_artifact_date"]
    max_age_minutes = max(interval_minutes * 2 + 2, 12)
    system_name = platform_name or platform.system()
    containerized = running_in_docker() if in_docker is None else in_docker
    resolved_host_systemd_health_path = resolve_host_systemd_health_path(host_systemd_health_path)
    checks = [
        scheduler_check(
            launchctl_output=launchctl_output,
            systemd_output=systemd_output,
            platform_name=system_name,
            in_docker=containerized,
            host_systemd_health_path=resolved_host_systemd_health_path,
            moment=current_time,
            max_age_minutes=max_age_minutes,
        ),
        webull_check(data_dir, expected_session_date, current_time, max_age_minutes),
        scanner_check(output_dir, expected_session_date, current_time, max_age_minutes),
        json_artifact_check(
            output_dir / "current_candle_capture.json",
            component="Current-candle capture",
            expected_session_date=expected_session_date,
            moment=current_time,
            max_age_minutes=max_age_minutes,
        ),
        json_artifact_check(
            output_dir / "candidate_window_ledger.json",
            component="Candidate ledger",
            expected_session_date=expected_session_date,
            moment=current_time,
            max_age_minutes=max_age_minutes,
            missing_status="YELLOW",
        ),
        json_artifact_check(
            output_dir / "dashboard_data_preflight.json",
            component="Dashboard preflight",
            expected_session_date=expected_session_date,
            moment=current_time,
            max_age_minutes=max_age_minutes,
            required_status="pass",
        ),
    ]
    if context["phase"] == "after_close":
        checks.append(after_close_supervisor_check(output_dir, expected_session_date))
    if system_name == "Linux" and (containerized or str((env or os.environ).get("GWALA_DEPLOYMENT_MODE", "")).lower() == "shadow"):
        checks.append(shadow_safety_check(env))
    status = aggregate_status(checks)
    failing = [check for check in checks if check["status"] == "RED"]
    degraded = [check for check in checks if check["status"] == "YELLOW"]
    if status == "GREEN":
        reason = "Production artifacts are current and the scheduler is healthy."
        next_action = "WAIT: continue collecting production evidence."
        decision = "VERIFY"
    elif status == "YELLOW":
        reason = degraded[0]["reason"] if degraded else "Production is degraded but running."
        next_action = "VERIFY: inspect degraded heartbeat component before trusting the session."
        decision = "VERIFY"
    else:
        reason = failing[0]["reason"]
        next_action = "BUILD: fix the failing production component before treating today as valid."
        decision = "BUILD"

    return {
        "generated_at_et": current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "heartbeat_date": str(today),
        "decision": decision,
        "founder_time": "Under 5 min" if status != "RED" else "5-15 min",
        "business_impact": "High",
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "experiment_valid_today": status != "RED",
        "red_component": failing[0]["component"] if failing else "",
        "red_reason": failing[0]["reason"] if failing else "",
        "checks": checks,
        "guardrail": "Status-only production heartbeat. No strategy, gate, or trading behavior changes.",
        "runtime": {
            "platform": system_name,
            "in_docker": bool(containerized),
            "host_systemd_health_path": str(resolved_host_systemd_health_path),
            "market_phase": str(context["phase"]),
            "expected_artifact_date": str(expected_session_date),
        },
    }


def write_report(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write heartbeat JSON and CEO summary Markdown."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "production_heartbeat.json"
    md_path = output_dir / "production_heartbeat.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    checks = pd.DataFrame(
        [
            {"component": check["component"], "status": check["status"], "reason": check["reason"]}
            for check in payload["checks"]
        ]
    )
    invalid_text = ""
    if payload["status"] == "RED":
        invalid_text = (
            f"\nToday experiment invalid: {payload['red_component']} failed because "
            f"{payload['red_reason']}\n"
        )
    md_path.write_text(
        f"""# Production Heartbeat

Decision: {payload["decision"]}
Founder Time: {payload["founder_time"]}
Business Impact: {payload["business_impact"]}
Status: {payload["status"]}
Reason: {payload["reason"]}
Next Action: {payload["next_action"]}

Experiment Valid Today: {payload["experiment_valid_today"]}
{invalid_text}
## Checks

{markdown_table(checks)}

## Generated

```text
{payload["generated_at_et"]}
```

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )
    return json_path, md_path


def main() -> None:
    args = parse_args()
    payload = build_heartbeat(
        args.output_dir,
        data_dir=args.data_dir,
        interval_minutes=args.interval_minutes,
        host_systemd_health_path=args.host_systemd_health_json,
    )
    json_path, md_path = write_report(payload, args.output_dir)
    print(f"Production heartbeat: {payload['status']}")
    print(f"Saved heartbeat JSON: {json_path}")
    print(f"Saved heartbeat report: {md_path}")
    if payload["status"] == "RED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
