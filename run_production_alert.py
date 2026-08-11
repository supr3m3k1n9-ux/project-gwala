"""Send a local Mac notification when production heartbeat requires attention.

This notifier is deliberately separate from the autonomous paper workflow. If
the main LaunchAgent fails, this script can still run from its own LaunchAgent
and warn Roy that the session is invalid.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from config.market_calendar import MARKET_TZ
from notification_format import (
    business_impact_for_severity as formatted_business_impact_for_severity,
    normalize_severity,
    notification_title,
    operator_action,
    production_alert_notification,
)
from run_production_heartbeat import DATA_DIR, build_heartbeat, write_report as write_heartbeat_report


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_RECHECK_SECONDS = 25
DEFAULT_OUTAGE_THRESHOLD_MINUTES = 5
DEFAULT_DOWN_CONFIRMATION_FAILURES = 2
SEVERITY_RANK = {"GREEN": 0, "WATCH": 1, "DEGRADED": 2, "DOWN": 3}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Notify locally when the production heartbeat is RED.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Where durable data artifacts are stored.")
    parser.add_argument("--interval-minutes", type=int, default=5, help="Expected production scan interval.")
    parser.add_argument("--cooldown-minutes", type=int, default=30, help="Minimum minutes between repeated RED alerts.")
    parser.add_argument(
        "--recheck-seconds",
        type=int,
        default=DEFAULT_RECHECK_SECONDS,
        help="Seconds to wait before confirming an apparent outage.",
    )
    parser.add_argument(
        "--outage-threshold-minutes",
        type=int,
        default=DEFAULT_OUTAGE_THRESHOLD_MINUTES,
        help="Minutes a confirmed failure must persist before DOWN is allowed.",
    )
    parser.add_argument(
        "--down-confirmation-failures",
        type=int,
        default=DEFAULT_DOWN_CONFIRMATION_FAILURES,
        help="Consecutive confirmed failures required before DOWN is allowed.",
    )
    return parser.parse_args()


def now_et() -> datetime:
    """Return current New York time."""

    return datetime.now(tz=MARKET_TZ)


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object if present."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_saved_time(value: object) -> datetime | None:
    """Parse a saved ET timestamp."""

    text = str(value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MARKET_TZ)
    return parsed.astimezone(MARKET_TZ)


def send_mac_notification(title: str, message: str, subtitle: str = "") -> bool:
    """Send a local macOS notification with osascript."""

    if platform.system() != "Darwin":
        return False
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    safe_subtitle = subtitle.replace("\\", "\\\\").replace('"', '\\"')
    subtitle_part = f' subtitle "{safe_subtitle}"' if safe_subtitle else ""
    script = f'display notification "{safe_message}" with title "{safe_title}"{subtitle_part} sound name "Basso"'
    completed = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    return completed.returncode == 0


def internal_severity(status: str) -> str:
    """Map heartbeat status to the executive severity vocabulary."""

    return normalize_severity(status)


def business_impact_for_severity(severity: str) -> str:
    """Return whether the severity normally implies direct business impact."""

    return formatted_business_impact_for_severity(severity)


def operator_action_for_severity(severity: str) -> str:
    """Return whether an operator should intervene immediately."""

    action = operator_action(severity)
    return "YES" if action in {"REVIEW", "IMMEDIATE"} else "NO"


def incident_key(heartbeat: dict[str, Any]) -> str:
    """Return a stable key for deduping one unresolved production condition."""

    component = str(heartbeat.get("red_component") or heartbeat.get("component") or "Production")
    reason = str(heartbeat.get("red_reason") or heartbeat.get("reason") or "unknown")
    return f"{component}|{reason}"


def previous_incident_key(previous_state: dict[str, Any]) -> str:
    """Return the active incident key, including pre-confirmation-state files."""

    key = str(previous_state.get("active_incident_key", ""))
    previous_severity = str(previous_state.get("active_incident_severity") or previous_state.get("last_internal_severity") or "GREEN")
    if not key and previous_severity in {"DEGRADED", "DOWN"}:
        return incident_key(previous_state)
    return key


def severity_increased(current: str, previous: object) -> bool:
    """Return True when current severity is higher than previous."""

    return SEVERITY_RANK.get(current, 0) > SEVERITY_RANK.get(str(previous or "GREEN"), 0)


def first_observed_time(previous_state: dict[str, Any], key: str, moment: datetime) -> datetime:
    """Return when this unresolved condition was first observed."""

    if previous_state.get("active_incident_key") == key:
        parsed = parse_saved_time(previous_state.get("active_incident_first_observed_at_et"))
        if parsed is not None:
            return parsed
    return moment


def confirmed_failure_count(previous_state: dict[str, Any], key: str) -> int:
    """Return the previous confirmed failure count for this incident key."""

    if previous_state.get("active_incident_key") != key:
        return 0
    try:
        return int(previous_state.get("confirmed_failure_count", 0))
    except (TypeError, ValueError):
        return 0


def classify_confirmed_heartbeat(
    initial: dict[str, Any],
    confirmed: dict[str, Any],
    previous_state: dict[str, Any],
    *,
    moment: datetime,
    outage_threshold_minutes: int,
    down_confirmation_failures: int,
) -> dict[str, Any]:
    """Classify a heartbeat after the provisional RED recheck."""

    initial_severity = internal_severity(str(initial.get("status", "")))
    confirmed_severity = internal_severity(str(confirmed.get("status", "")))
    if initial_severity == "DOWN" and confirmed_severity != "DOWN":
        recovered_existing_incident = bool(previous_state.get("active_incident_key")) and confirmed_severity == "GREEN"
        severity = "GREEN" if recovered_existing_incident else "WATCH"
        return {
            "heartbeat": confirmed,
            "status": confirmed.get("status", "GREEN") if recovered_existing_incident else "YELLOW",
            "internal_severity": severity,
            "business_impact": "NO",
            "operator_action_required": "NO",
            "reason": "Transient artifact freshness delay recovered during confirmation recheck.",
            "next_action": "WAIT: continue collecting production evidence.",
            "experiment_valid_today": True,
            "auto_recovered": "YES",
            "active_incident_key": "",
            "confirmed_failure_count": 0,
            "active_incident_first_observed_at_et": "",
        }

    if confirmed_severity != "DOWN":
        severity = confirmed_severity
        return {
            "heartbeat": confirmed,
            "status": confirmed.get("status", ""),
            "internal_severity": severity,
            "business_impact": business_impact_for_severity(severity),
            "operator_action_required": operator_action_for_severity(severity),
            "reason": confirmed.get("reason", ""),
            "next_action": confirmed.get("next_action", ""),
            "experiment_valid_today": confirmed.get("experiment_valid_today", True),
            "auto_recovered": "NO",
            "active_incident_key": "",
            "confirmed_failure_count": 0,
            "active_incident_first_observed_at_et": "",
        }

    key = incident_key(confirmed)
    first_seen = first_observed_time(previous_state, key, moment)
    failures = confirmed_failure_count(previous_state, key) + 1
    outage_age = moment - first_seen
    severity = "DOWN" if (
        failures >= down_confirmation_failures
        or outage_age >= timedelta(minutes=outage_threshold_minutes)
    ) else "DEGRADED"
    return {
        "heartbeat": confirmed,
        "status": confirmed.get("status", ""),
        "internal_severity": severity,
        "business_impact": business_impact_for_severity(severity),
        "operator_action_required": operator_action_for_severity(severity),
        "reason": confirmed.get("reason", ""),
        "next_action": (
            "REVIEW: production artifact is still delayed after confirmation."
            if severity == "DEGRADED"
            else confirmed.get("next_action", "")
        ),
        "experiment_valid_today": severity != "DOWN",
        "auto_recovered": "NO",
        "active_incident_key": key,
        "confirmed_failure_count": failures,
        "active_incident_first_observed_at_et": first_seen.isoformat(),
    }


def should_notify(
    classification: dict[str, Any],
    previous_state: dict[str, Any],
) -> tuple[bool, str]:
    """Return whether to notify without storming on repeated checks."""

    severity = str(classification["internal_severity"])
    key = str(classification.get("active_incident_key", ""))
    previous_severity = str(previous_state.get("active_incident_severity") or previous_state.get("last_internal_severity") or "GREEN")
    previous_key = previous_incident_key(previous_state)

    if severity == "GREEN":
        if previous_key and previous_state.get("recovery_notified_for") != previous_key:
            return True, "recovery"
        return False, "none"
    if severity == "WATCH" and not key:
        return False, "transient_recovered"
    if not key:
        return False, "none"
    if key != previous_key:
        return True, "initial"
    if severity_increased(severity, previous_severity):
        return True, "escalation"
    return False, "deduped"


def build_alert(
    output_dir: Path,
    *,
    data_dir: Path = DATA_DIR,
    interval_minutes: int = 5,
    cooldown_minutes: int = 30,
    recheck_seconds: int = DEFAULT_RECHECK_SECONDS,
    outage_threshold_minutes: int = DEFAULT_OUTAGE_THRESHOLD_MINUTES,
    down_confirmation_failures: int = DEFAULT_DOWN_CONFIRMATION_FAILURES,
    moment: datetime | None = None,
    notifier: Callable[[str, str], bool] = send_mac_notification,
    launchctl_output: str | None = None,
    platform_name: str | None = None,
    in_docker: bool | None = None,
    host_systemd_health_path: Path | None = None,
    env: dict[str, str] | None = None,
    heartbeat_builder: Callable[..., dict[str, Any]] = build_heartbeat,
) -> dict[str, Any]:
    """Build heartbeat, possibly notify, and return alert state."""

    current_time = moment or now_et()
    output_dir.mkdir(parents=True, exist_ok=True)
    heartbeat = heartbeat_builder(
        output_dir,
        data_dir=data_dir,
        moment=current_time,
        interval_minutes=interval_minutes,
        launchctl_output=launchctl_output,
        platform_name=platform_name,
        in_docker=in_docker,
        host_systemd_health_path=host_systemd_health_path,
        env=env,
    )
    write_heartbeat_report(heartbeat, output_dir)
    state_path = output_dir / "production_alert_state.json"
    previous_state = read_json_or_empty(state_path)
    confirmed_heartbeat = heartbeat
    confirmed_time = current_time
    if internal_severity(str(heartbeat.get("status", ""))) == "DOWN":
        if recheck_seconds > 0:
            time.sleep(recheck_seconds)
            confirmed_time = now_et() if moment is None else current_time + timedelta(seconds=recheck_seconds)
        confirmed_heartbeat = heartbeat_builder(
            output_dir,
            data_dir=data_dir,
            moment=confirmed_time,
            interval_minutes=interval_minutes,
            launchctl_output=launchctl_output,
            platform_name=platform_name,
            in_docker=in_docker,
            host_systemd_health_path=host_systemd_health_path,
            env=env,
        )
        write_heartbeat_report(confirmed_heartbeat, output_dir)

    classification = classify_confirmed_heartbeat(
        heartbeat,
        confirmed_heartbeat,
        previous_state,
        moment=confirmed_time,
        outage_threshold_minutes=outage_threshold_minutes,
        down_confirmation_failures=down_confirmation_failures,
    )
    heartbeat_for_state = classification["heartbeat"]
    notify, notification_reason = should_notify(classification, previous_state)
    notification_sent = False
    severity = str(classification["internal_severity"])
    business_impact = str(classification["business_impact"])
    operator_action_required = str(classification["operator_action_required"])
    title = notification_title(severity)
    notification = production_alert_notification(
        {
            "status": classification.get("status", ""),
            "internal_severity": severity,
            "business_impact": business_impact,
            "operator_action_required": operator_action_required,
            "red_component": heartbeat_for_state.get("red_component", ""),
            "red_reason": heartbeat_for_state.get("red_reason", ""),
            "reason": classification.get("reason", ""),
            "auto_recovered": classification.get("auto_recovered", ""),
        }
    )
    if notify:
        try:
            notification_sent = notifier(notification.title, notification.body[:180], notification.subtitle)
        except TypeError:
            notification_sent = notifier(notification.title, notification.body[:180])

    state = {
        "generated_at_et": confirmed_time.isoformat(),
        "status": classification["status"],
        "internal_severity": severity,
        "business_impact": business_impact,
        "operator_action_required": operator_action_required,
        "experiment_valid_today": classification["experiment_valid_today"],
        "notification_required": notify,
        "notification_sent": notification_sent,
        "notification_reason": notification_reason,
        "notification_title": notification.title,
        "notification_subtitle": notification.subtitle,
        "notification_body": notification.body,
        "last_status": classification["status"],
        "last_internal_severity": severity,
        "last_notified_at_et": current_time.isoformat()
        if notify
        else previous_state.get("last_notified_at_et", ""),
        "active_incident_key": classification.get("active_incident_key", ""),
        "active_incident_severity": severity if classification.get("active_incident_key") else "",
        "active_incident_first_observed_at_et": classification.get("active_incident_first_observed_at_et", ""),
        "confirmed_failure_count": classification.get("confirmed_failure_count", 0),
        "recheck_seconds": recheck_seconds,
        "outage_threshold_minutes": outage_threshold_minutes,
        "down_confirmation_failures": down_confirmation_failures,
        "auto_recovered": classification.get("auto_recovered", "NO"),
        "red_component": heartbeat_for_state.get("red_component", ""),
        "red_reason": heartbeat_for_state.get("red_reason", ""),
        "reason": classification.get("reason", ""),
        "next_action": classification.get("next_action", ""),
        "guardrail": "Local notification only. No trading behavior changes.",
    }
    if notification_reason == "recovery":
        state["recovery_notified_for"] = previous_incident_key(previous_state)
    else:
        state["recovery_notified_for"] = previous_state.get("recovery_notified_for", "")
    if severity == "GREEN":
        state["last_notified_at_et"] = ""
        state["active_incident_key"] = ""
        state["active_incident_severity"] = ""
        state["active_incident_first_observed_at_et"] = ""
        state["confirmed_failure_count"] = 0
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    write_alert_report(output_dir, state)
    return state


def write_alert_report(output_dir: Path, state: dict[str, Any]) -> Path:
    """Write a short human-readable alert report."""

    path = output_dir / "production_alert.md"
    path.write_text(
        f"""# Production Alert

Status: {state["status"]}
Internal Severity: {state["internal_severity"]}
Business Impact: {state["business_impact"]}
Operator Action Required: {state["operator_action_required"]}
Experiment Valid Today: {state["experiment_valid_today"]}
Notification Required: {state["notification_required"]}
Notification Sent: {state["notification_sent"]}
Notification Reason: {state["notification_reason"]}
Reason: {state["reason"]}
Next Action: {state["next_action"]}
Recheck Seconds: {state["recheck_seconds"]}
Outage Threshold Minutes: {state["outage_threshold_minutes"]}
Confirmed Failure Count: {state["confirmed_failure_count"]}

Generated: {state["generated_at_et"]}

Guardrail: {state["guardrail"]}
""",
        encoding="utf-8",
    )
    return path


def main() -> None:
    args = parse_args()
    state = build_alert(
        args.output_dir,
        data_dir=args.data_dir,
        interval_minutes=args.interval_minutes,
        cooldown_minutes=args.cooldown_minutes,
        recheck_seconds=args.recheck_seconds,
        outage_threshold_minutes=args.outage_threshold_minutes,
        down_confirmation_failures=args.down_confirmation_failures,
    )
    print(f"Production alert status: {state['status']}")
    print(f"Notification sent: {state['notification_sent']}")


if __name__ == "__main__":
    main()
