"""Shared Project Gwala macOS notification formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SEVERITY_EMOJI = {
    "GREEN": "🟢",
    "WATCH": "🟡",
    "DEGRADED": "🟠",
    "DOWN": "🔴",
}

SEVERITY_ORDER = {"GREEN": 0, "WATCH": 1, "DEGRADED": 2, "DOWN": 3}


@dataclass(frozen=True)
class GwalaNotification:
    """Formatted macOS notification content."""

    title: str
    subtitle: str
    body: str
    severity: str
    operator_action: str
    takeaway: str


def text(value: object) -> str:
    """Return a clean string for notification text."""

    return "" if value is None else str(value).strip()


def normalize_severity(value: object) -> str:
    """Normalize status values to the four executive severities."""

    status = text(value).upper()
    if status == "YELLOW":
        return "WATCH"
    if status == "RED":
        return "DOWN"
    if status in SEVERITY_EMOJI:
        return status
    return "WATCH"


def worst_severity(*values: object) -> str:
    """Return the highest severity from a list of status values."""

    severities = [normalize_severity(value) for value in values if text(value)]
    if not severities:
        return "WATCH"
    return max(severities, key=lambda value: SEVERITY_ORDER[value])


def notification_title(severity: object) -> str:
    """Return the required Project Gwala title format."""

    normalized = normalize_severity(severity)
    return f"{SEVERITY_EMOJI[normalized]} GWALA — {normalized}"


def operator_action(severity: object, explicit: object = "") -> str:
    """Return NONE, REVIEW, or IMMEDIATE for a notification."""

    value = text(explicit).upper()
    if value in {"NONE", "REVIEW", "IMMEDIATE"}:
        return value
    if value in {"NO", "FALSE", "0"}:
        return "NONE"
    if value in {"YES", "TRUE", "1"}:
        return "IMMEDIATE" if normalize_severity(severity) == "DOWN" else "REVIEW"

    normalized = normalize_severity(severity)
    if normalized in {"GREEN", "WATCH"}:
        return "NONE"
    if normalized == "DEGRADED":
        return "REVIEW"
    return "IMMEDIATE"


def business_impact_for_severity(severity: object) -> str:
    """Return whether the severity normally implies business impact."""

    return "YES" if normalize_severity(severity) in {"DEGRADED", "DOWN"} else "NO"


def notification_type(report_type: object, report_status: object = "") -> str:
    """Return the required notification type label."""

    kind = text(report_type).lower()
    status = text(report_status).upper()
    if status == "PENDING_RECONCILIATION":
        return "Pending Reconciliation"
    if kind == "opening":
        return "Opening Executive Report"
    if kind == "eod":
        return "End-of-Day Executive Report"
    return "Production Alert"


def executive_report_takeaway(payload: dict[str, Any], severity: str) -> str:
    """Build the one-line takeaway for opening and EOD reports."""

    report_type = text(payload.get("report_type")).lower()
    if report_type == "opening":
        return opening_takeaway(payload, severity)
    return eod_takeaway(payload, severity)


def opening_takeaway(payload: dict[str, Any], severity: str) -> str:
    """Opening report takeaway priority: readiness, blockers, trades, data."""

    production = normalize_severity(payload.get("production_status"))
    blocking = [text(item) for item in payload.get("blocking_issues", []) if text(item)]
    open_trades = payload.get("unresolved_open_trades", []) or []
    if production == "GREEN":
        return "Opening report: Production ready for today's session."
    if blocking:
        return f"Opening report: {blocking[0]}"
    if open_trades:
        count = len(open_trades)
        noun = "trade" if count == 1 else "trades"
        return f"Opening report: {count} unresolved open paper {noun} need review."
    if severity == "WATCH":
        return "Opening report: Data freshness or readiness needs observation."
    return f"Opening report: Production readiness is {severity}."


def eod_takeaway(payload: dict[str, Any], severity: str) -> str:
    """EOD takeaway priority: impact, pending/open trades, completed, engineering."""

    if text(payload.get("business_impact")).upper() == "YES":
        return "End-of-day report: Business-impact incident requires review."
    if text(payload.get("report_status")).upper() == "PENDING_RECONCILIATION":
        symbols = payload.get("missing_final_m5_symbols", []) or []
        if symbols:
            return f"End-of-day report: {len(symbols)} symbol(s) pending final M5 reconciliation."
        return "End-of-day report: Final reconciliation is pending."
    open_trades = payload.get("open_trades", []) or []
    if open_trades:
        count = len(open_trades)
        noun = "trade is" if count == 1 else "trades are"
        return f"End-of-day report: {count} paper {noun} pending final reconciliation."
    activity = payload.get("trading_activity", {}) if isinstance(payload.get("trading_activity"), dict) else {}
    completed = activity.get("autonomous_paper_trades_closed")
    if text(completed):
        return f"End-of-day report: {completed} autonomous paper trade(s) closed."
    assessment = payload.get("engineering_assessment", {})
    if isinstance(assessment, dict) and text(assessment.get("exactly_one_improvement")).upper() == "YES":
        return "End-of-day report: Engineering review was earned today."
    return "End-of-day report: No operator action required."


def production_alert_takeaway(alert: dict[str, Any], severity: str) -> str:
    """Production alert takeaway priority: component, impact, recovery."""

    component = text(alert.get("red_component")) or text(alert.get("component")) or "Production"
    reason = text(alert.get("red_reason")) or text(alert.get("reason"))
    business_impact = text(alert.get("business_impact")).upper()
    auto_recovered = text(alert.get("auto_recovered")).upper()
    if severity == "DOWN":
        if component.lower() == "scanner":
            return "Candidate generation has stopped."
        return f"{component} is DOWN."
    if business_impact == "YES":
        return f"{component} has business impact."
    if auto_recovered == "YES":
        return f"{component} issue auto-recovered."
    if reason:
        return reason[:110]
    return f"{component} requires observation."


def executive_report_notification(payload: dict[str, Any]) -> GwalaNotification:
    """Format an opening, EOD, or pending-reconciliation report notification."""

    severity = worst_severity(payload.get("production_status"), payload.get("reporting_status"))
    action = operator_action(severity, payload.get("operator_action_required"))
    label = notification_type(payload.get("report_type"), payload.get("report_status"))
    takeaway = executive_report_takeaway(payload, severity)
    return GwalaNotification(
        title=notification_title(severity),
        subtitle=label,
        body=f"{takeaway}\nOperator action: {action}",
        severity=severity,
        operator_action=action,
        takeaway=takeaway,
    )


def production_alert_notification(alert: dict[str, Any]) -> GwalaNotification:
    """Format a production alert notification."""

    severity = normalize_severity(alert.get("internal_severity") or alert.get("status"))
    action = operator_action(severity, alert.get("operator_action_required"))
    takeaway = production_alert_takeaway(alert, severity)
    return GwalaNotification(
        title=notification_title(severity),
        subtitle="Production Alert",
        body=f"{takeaway}\nOperator action: {action}",
        severity=severity,
        operator_action=action,
        takeaway=takeaway,
    )
