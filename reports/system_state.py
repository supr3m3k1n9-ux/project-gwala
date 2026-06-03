"""App-ready system state for Project Gwala.

This module gathers the current research and paper-workflow status into one
plain Python dictionary. Command-line reports and a future local app can use
this same source of truth instead of scraping Markdown files.

It does not fetch data, place orders, create alerts, or connect to broker
execution.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_data_integrity import coverage_is_issue

from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.settings import STRATEGY
from run_forward_sample_queue import build_queue as build_forward_sample_queue
from run_forward_sample_queue import queue_payload as forward_sample_queue_payload


FIRST_PAPER_GATE = 30
STRONG_PAPER_GATE = 60


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and is parseable."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def file_state(path: Path) -> dict[str, Any]:
    """Return app-friendly file freshness details."""

    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "modified_et": "",
            "size_bytes": 0,
        }

    modified = datetime.fromtimestamp(path.stat().st_mtime, MARKET_TZ)
    return {
        "path": str(path),
        "exists": True,
        "modified_et": modified.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "size_bytes": int(path.stat().st_size),
    }


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object if it exists and is parseable."""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def premarket_verification_state(verification: dict[str, Any], path: Path) -> dict[str, Any]:
    """Summarize the latest pre-market verification for the local app."""

    if not verification:
        return {
            "status": "not_run",
            "probe_status": "not_run",
            "integrity_status": "not_run",
            "paper_import_gate_status": "not_run",
            "modified_et": "",
        }

    checks = verification.get("checks", [])
    checks_by_area = {
        str(check.get("area", "")): str(check.get("status", "missing"))
        for check in checks
        if isinstance(check, dict)
    }
    failed = any(status == "fail" for status in checks_by_area.values())
    probe_status = checks_by_area.get("Webull data-only access", "missing")
    if failed:
        status = "failed"
    elif probe_status in {"pass", "previous_pass"}:
        status = "passed"
    else:
        status = "local_pass"

    return {
        "status": status,
        "probe_status": probe_status,
        "integrity_status": checks_by_area.get("Candle integrity", "missing"),
        "paper_import_gate_status": checks_by_area.get("Paper import gate", "missing"),
        "modified_et": file_state(path)["modified_et"],
    }


def regular_market_times() -> tuple:
    """Return configured market open/close times with NY timezone info."""

    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    return open_time, close_time


def status_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    """Return value counts for a status column."""

    if frame.empty or column not in frame.columns:
        return {}
    counts = frame.groupby(column).size().to_dict()
    return {str(key): int(value) for key, value in counts.items()}


def latest_scan_date(scanner: pd.DataFrame) -> str:
    """Return the latest scanner session date."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return ""
    values = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
    return values[-1] if values else ""


def market_state() -> dict[str, Any]:
    """Build market calendar state for today and the next session."""

    open_time, close_time = regular_market_times()
    now = datetime.now(MARKET_TZ)
    today = market_session_for_date(now.date(), open_time, close_time)
    next_session = next_market_session(now, open_time, close_time)
    market_is_open = bool(
        today.is_market_day
        and today.market_open is not None
        and today.market_close is not None
        and today.market_open <= now <= today.market_close
    )
    if market_is_open:
        session_status = "market_open"
    elif today.is_market_day and today.market_open is not None and now < today.market_open:
        session_status = "before_open"
    elif today.is_market_day and today.market_close is not None and now > today.market_close:
        session_status = "after_close"
    else:
        session_status = "market_closed"

    return {
        "now_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "today": str(now.date()),
        "is_market_day": bool(today.is_market_day),
        "today_status": today.reason,
        "market_status": session_status,
        "market_is_open": market_is_open,
        "next_market_session": str(next_session.session_date),
        "next_market_session_status": next_session.reason,
    }


def data_freshness_state(scanner: pd.DataFrame, market: dict[str, Any]) -> dict[str, Any]:
    """Classify scanner data freshness for paper-trading decisions."""

    latest = latest_scan_date(scanner)
    today = str(market["today"])
    next_session = str(market["next_market_session"])

    if not latest:
        status = "missing"
        action = "Run python run_daily_workflow.py after data exists."
    elif latest == today and market.get("market_is_open", False):
        status = "fresh_for_today"
        action = "Current-candle candidates may be reviewed for paper trading."
    elif latest == today and market["is_market_day"]:
        status = "outside_market_hours"
        action = (
            f"Today's scanner data is no longer actionable. On {next_session}, run "
            "python run_daily_workflow.py --refresh-data before importing or sizing any paper trade."
        )
    else:
        status = "stale"
        action = f"Prep only. On {next_session}, run python run_daily_workflow.py --refresh-data before importing or sizing any paper trade."

    return {
        "latest_scanner_session": latest or "unknown",
        "data_status": status,
        "action": action,
    }


def scanner_state(scanner: pd.DataFrame) -> dict[str, Any]:
    """Summarize the latest scanner output."""

    current_count = 0
    allowed_count = 0
    blocked_count = 0
    if not scanner.empty:
        current = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]
        allowed = scanner[scanner["scanner_status"] == "allowed"]
        blocked = scanner[scanner["scanner_status"] == "blocked_watch_only"]
        current_count = len(current)
        allowed_count = len(allowed)
        blocked_count = len(blocked)

    return {
        "rows": int(len(scanner)),
        "status_counts": status_counts(scanner, "scanner_status"),
        "current_candidate_count": int(current_count),
        "allowed_rows": int(allowed_count),
        "blocked_watch_only_rows": int(blocked_count),
    }


def sizing_state(sizing: pd.DataFrame) -> dict[str, Any]:
    """Summarize position sizing output."""

    eligible = 0
    if not sizing.empty and "sizing_status" in sizing.columns:
        eligible = len(sizing[sizing["sizing_status"] == "size_ok"])
    return {
        "rows": int(len(sizing)),
        "status_counts": status_counts(sizing, "sizing_status"),
        "eligible_size_count": int(eligible),
    }


def forward_observation_state(observations: pd.DataFrame) -> dict[str, Any]:
    """Summarize preserved forward scanner sightings."""

    allowed_rows = 0
    blocked_rows = 0
    latest_observed_at_et = ""
    if not observations.empty and "signal_status" in observations.columns:
        allowed_rows = int((observations["signal_status"] == "allowed").sum())
        blocked_rows = int((observations["signal_status"] == "blocked").sum())
        if "observed_at_et" in observations.columns and not observations["observed_at_et"].dropna().empty:
            latest_observed_at_et = str(observations["observed_at_et"].dropna().iloc[-1])

    return {
        "rows": int(len(observations)),
        "status_counts": status_counts(observations, "signal_status"),
        "allowed_rows": allowed_rows,
        "blocked_rows": blocked_rows,
        "latest_observed_at_et": latest_observed_at_et,
    }


def forward_validation_state(results: pd.DataFrame, reconciliation: pd.DataFrame, integrity: pd.DataFrame, refresh_audit: pd.DataFrame) -> dict[str, Any]:
    """Summarize forward outcome evidence and data audit state."""

    matured = results[results["evaluation_status"] == "matured"].copy() if not results.empty and "evaluation_status" in results.columns else pd.DataFrame()
    allowed = matured[matured["signal_status"] == "allowed"] if not matured.empty else pd.DataFrame()
    blocked = matured[matured["signal_status"] == "blocked"] if not matured.empty else pd.DataFrame()
    reconciled_status = status_counts(reconciliation, "reconciliation_status")
    issue_count = 0
    if not integrity.empty:
        issues = integrity.apply(lambda row: coverage_is_issue(row["status"], row["session_coverage"]), axis=1)
        issue_count = int(issues.sum())
    return {
        "reviewed_observations": int(len(results)),
        "matured_outcomes": int(len(matured)),
        "pending_outcomes": int(len(results) - len(matured)),
        "allowed_matured": int(len(allowed)),
        "allowed_average_r": round(float(pd.to_numeric(allowed["hypothetical_r"]).mean()), 4) if not allowed.empty else 0.0,
        "blocked_matured": int(len(blocked)),
        "blocked_average_r": round(float(pd.to_numeric(blocked["hypothetical_r"]).mean()), 4) if not blocked.empty else 0.0,
        "reconciliation_status_counts": reconciled_status,
        "integrity_issue_count": issue_count,
        "refresh_audit_rows": int(len(refresh_audit)),
    }


def forward_evidence_bridge_state(
    paper: dict[str, Any],
    observations: dict[str, Any],
    validation: dict[str, Any],
    shadow_samples: pd.DataFrame,
    shadow_outcomes: pd.DataFrame,
    candidate_aging: pd.DataFrame,
    queue: dict[str, Any],
) -> dict[str, Any]:
    """Summarize which evidence lanes count toward paper validation."""

    matured_shadow = (
        shadow_outcomes[shadow_outcomes["evaluation_status"] == "matured"]
        if not shadow_outcomes.empty and "evaluation_status" in shadow_outcomes.columns
        else pd.DataFrame()
    )
    shadow_average = (
        round(float(pd.to_numeric(matured_shadow["hypothetical_r"], errors="coerce").mean()), 4)
        if not matured_shadow.empty and "hypothetical_r" in matured_shadow.columns
        else 0.0
    )
    late_day = (
        candidate_aging[candidate_aging["age_bucket"] == "late_day"]
        if not candidate_aging.empty and "age_bucket" in candidate_aging.columns
        else pd.DataFrame()
    )
    late_result_column = "outcome_r" if "outcome_r" in late_day.columns else "r_result" if "r_result" in late_day.columns else ""
    if not late_day.empty and late_result_column:
        late_day_outcomes = late_day[pd.to_numeric(late_day[late_result_column], errors="coerce").notna()]
    else:
        late_day_outcomes = pd.DataFrame()
    late_day_average = (
        round(float(pd.to_numeric(late_day_outcomes[late_result_column], errors="coerce").mean()), 4)
        if not late_day_outcomes.empty and late_result_column
        else 0.0
    )
    aging_status = "late_day_caution" if not late_day_outcomes.empty and late_day_average < 0 else "timing_watch"
    summary = queue.get("summary", {}) if isinstance(queue, dict) else {}

    return {
        "official_paper_trades": int(paper.get("allowed_completed_trades", 0) or 0),
        "official_total_completed": int(paper.get("completed_paper_trades", 0) or 0),
        "remaining_to_30": int(paper.get("first_gate_remaining", FIRST_PAPER_GATE) or FIRST_PAPER_GATE),
        "forward_observations": int(observations.get("rows", 0) or 0),
        "matured_observations": int(validation.get("matured_outcomes", 0) or 0),
        "allowed_observation_average_r": float(validation.get("allowed_average_r", 0.0) or 0.0),
        "shadow_samples": int(len(shadow_samples)),
        "matured_shadow_samples": int(len(matured_shadow)),
        "shadow_average_r": shadow_average,
        "candidate_aging_rows": int(len(candidate_aging)),
        "late_day_rows": int(len(late_day)),
        "late_day_outcomes": int(len(late_day_outcomes)),
        "late_day_average_r": late_day_average,
        "aging_status": aging_status,
        "current_ready_queue": int(summary.get("ready_for_review", 0) or 0),
        "almost_ready": int(summary.get("almost_ready", 0) or 0),
        "counts_toward_gate": "official_paper_trades_only",
        "message": "Only completed allowed paper trades count toward the 30/60 gates. Historical, observation, and shadow lanes stay separate.",
    }


def data_reliability_state(freshness: dict[str, Any], refresh_status: dict[str, Any], automation_timeline: dict[str, Any]) -> dict[str, Any]:
    """Summarize data reliability without requiring raw log reading."""

    possible_failures = []
    if isinstance(automation_timeline, dict):
        possible_failures = automation_timeline.get("recent_possible_failures") or automation_timeline.get("recent_failures") or []
    timeline_status = str(automation_timeline.get("status", "")) if isinstance(automation_timeline, dict) else ""
    digest_action = str(automation_timeline.get("post_scan_digest", {}).get("action", "")) if isinstance(automation_timeline, dict) else ""
    watchdog_status = str(automation_timeline.get("morning_watchdog", {}).get("status", "")) if isinstance(automation_timeline, dict) else ""
    recovered = bool(possible_failures) and watchdog_status == "pass" and digest_action not in {"data_issue", "missing"}

    if bool(possible_failures) and not recovered:
        status = "warn"
        headline = "Current automation reliability needs attention."
        next_action = "If the next market scan fails, run the refresh status check and Webull refresh manually."
    elif recovered:
        status = "recovered_warn"
        headline = "Earlier automation errors were detected, but the latest structured workflow completed."
        next_action = "No emergency action. If tomorrow's first scan fails, run refresh status and Webull refresh manually."
    elif freshness.get("data_status") == "fresh_for_today":
        status = "pass"
        headline = "Scanner data is fresh for today's open session."
        next_action = "Candidates may be reviewed manually if they also pass sizing and checklist gates."
    else:
        status = "watch"
        headline = str(freshness.get("action", "Refresh data before reviewing candidates."))
        next_action = "Refresh during the next open market session before logging paper trades."

    return {
        "status": status,
        "headline": headline,
        "next_action": next_action,
        "latest_scanner_session": freshness.get("latest_scanner_session", "unknown"),
        "refresh_status": refresh_status.get("status", "unknown") if isinstance(refresh_status, dict) else "unknown",
        "possible_failure_count": len(possible_failures),
        "timeline_status": timeline_status,
        "latest_watchdog_status": watchdog_status,
        "latest_post_scan_action": digest_action,
    }


def app_value(value: object) -> object:
    """Return a JSON-safe scalar value for app cards."""

    if pd.isna(value):
        return ""
    return value.item() if hasattr(value, "item") else value


def app_float(value: object, default: float = 0.0) -> float:
    """Return a plain float from scanner/sizing values."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def risk_guard_state(paper: dict[str, Any]) -> dict[str, Any]:
    """Return forward-paper risk limits based on completed sample count."""

    allowed = int(paper.get("allowed_completed_trades", 0) or 0)
    if allowed < FIRST_PAPER_GATE:
        return {
            "status": "conservative_only",
            "allowed_completed_trades": allowed,
            "next_gate": FIRST_PAPER_GATE,
            "remaining_to_next_gate": FIRST_PAPER_GATE - allowed,
            "max_forward_risk_pct": 0.5,
            "scale_allowed": False,
            "message": "Forward scale-up is locked until 30 allowed completed paper trades are logged.",
        }
    if allowed < STRONG_PAPER_GATE:
        return {
            "status": "first_gate_passed",
            "allowed_completed_trades": allowed,
            "next_gate": STRONG_PAPER_GATE,
            "remaining_to_next_gate": STRONG_PAPER_GATE - allowed,
            "max_forward_risk_pct": 0.75,
            "scale_allowed": True,
            "message": "First paper gate passed. Strong setups may be capped at 0.75% paper risk.",
        }
    return {
        "status": "strong_gate_passed",
        "allowed_completed_trades": allowed,
        "next_gate": STRONG_PAPER_GATE,
        "remaining_to_next_gate": 0,
        "max_forward_risk_pct": 1.0,
        "scale_allowed": True,
        "message": "Strong paper gate passed. Best-tier paper setups may be capped at 1.0% paper risk.",
    }


def apply_risk_guard(guidance: dict[str, Any], risk_guard: dict[str, Any] | None) -> dict[str, Any]:
    """Cap forward-paper scale guidance until enough paper samples exist."""

    if not risk_guard:
        return guidance

    max_risk = float(risk_guard.get("max_forward_risk_pct", 0.5) or 0.5)
    suggested = float(guidance.get("suggested_risk_pct", 0.0) or 0.0)
    if suggested <= max_risk:
        return guidance

    capped = guidance.copy()
    capped["suggested_risk_pct"] = max_risk
    capped["option_premium_cap_pct"] = min(float(capped.get("option_premium_cap_pct", 0.0) or 0.0), max_risk * 4)
    capped["scale_tier"] = "standard" if max_risk <= 0.5 else "capped_scale"
    capped["scale_label"] = "Standard Risk" if max_risk <= 0.5 else "Capped Scale"
    capped["scale_reason"] = (
        f"{risk_guard['message']} This setup quality is strong, but forward paper risk is capped at "
        f"{max_risk:.2f}% until the next validation gate."
    )
    return capped


def scale_guidance(
    row: pd.Series,
    ready_for_review: bool,
    risk_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Suggest a paper-risk tier without changing any actual sizing.

    The goal is to press only cleaner research setups while keeping the app in
    manual paper-validation mode. This is guidance, not execution.
    """

    quality_score = app_float(row.get("quality_score", 0))
    quality_grade = str(row.get("quality_grade", "")).upper()
    relative_volume = app_float(row.get("relative_volume", 0))
    room_to_target = app_float(row.get("room_to_target_r", row.get("room_to_resistance_r", 0)))

    if not ready_for_review:
        return {
            "scale_tier": "no_scale",
            "scale_label": "No Scale",
            "suggested_risk_pct": 0.0,
            "option_premium_cap_pct": 0.0,
            "scale_reason": "Do not increase size until the setup is fresh, allowed, size-ok, and manually reviewed.",
        }

    elite_quality = quality_grade == "A" and quality_score >= 9 and relative_volume >= 1.5 and room_to_target >= 2.0
    standard_quality = quality_grade == "A" and quality_score >= 8 and relative_volume >= 1.2 and room_to_target >= 1.25

    if elite_quality:
        return apply_risk_guard(
            {
            "scale_tier": "paper_scale",
            "scale_label": "Paper Scale Candidate",
            "suggested_risk_pct": 1.0,
            "option_premium_cap_pct": 2.5,
            "scale_reason": "A-grade, strong volume, and enough room. Consider up to 1% paper risk only after the options checklist passes.",
            },
            risk_guard,
        )
    if standard_quality:
        return apply_risk_guard(
            {
            "scale_tier": "standard",
            "scale_label": "Standard Risk",
            "suggested_risk_pct": 0.5,
            "option_premium_cap_pct": 2.0,
            "scale_reason": "Clean enough for normal paper risk. Do not press it unless forward evidence improves.",
            },
            risk_guard,
        )
    return {
        "scale_tier": "reduced",
        "scale_label": "Reduced Risk",
        "suggested_risk_pct": 0.25,
        "option_premium_cap_pct": 1.0,
        "scale_reason": "Setup is reviewable but not strong enough to press. Keep size smaller or skip.",
    }


def candidate_priority(
    row: pd.Series,
    setup_health: pd.DataFrame,
    promotion_review: pd.DataFrame,
    candidate_aging: pd.DataFrame,
) -> dict[str, Any]:
    """Score how strongly a current candidate should be prioritized for paper review."""

    symbol = str(row.get("symbol", "")).upper()
    setup = str(row.get("setup", ""))
    health_status = "unknown"
    health_flags = ""
    if not setup_health.empty and {"symbol", "setup", "health_status"}.issubset(setup_health.columns):
        matches = setup_health[
            (setup_health["symbol"].astype(str).str.upper() == symbol)
            & (setup_health["setup"].astype(str) == setup)
        ]
        if not matches.empty:
            health_status = str(matches.iloc[0].get("health_status", "unknown"))
            health_flags = str(matches.iloc[0].get("flags", ""))

    historical_trades = 0
    historical_expectancy = 0.0
    if not promotion_review.empty and {"symbol", "setup", "promotion_decision"}.issubset(promotion_review.columns):
        promoted = promotion_review[
            (promotion_review["symbol"].astype(str).str.upper() == symbol)
            & (promotion_review["setup"].astype(str) == setup)
            & (promotion_review["promotion_decision"].astype(str) == "paper_watch_candidate")
        ].copy()
        if not promoted.empty:
            promoted["expectancy_r"] = pd.to_numeric(promoted.get("expectancy_r", 0), errors="coerce").fillna(0.0)
            promoted["trades"] = pd.to_numeric(promoted.get("trades", 0), errors="coerce").fillna(0).astype(int)
            best = promoted.sort_values(["expectancy_r", "trades"], ascending=[False, False]).iloc[0]
            historical_trades = int(best.get("trades", 0) or 0)
            historical_expectancy = round(float(best.get("expectancy_r", 0.0) or 0.0), 4)

    late_day_average = 0.0
    late_day_outcomes = pd.DataFrame()
    if not candidate_aging.empty and "age_bucket" in candidate_aging.columns:
        late = candidate_aging[candidate_aging["age_bucket"] == "late_day"].copy()
        result_column = "r_result" if "r_result" in late.columns else "outcome_r" if "outcome_r" in late.columns else ""
        if result_column:
            late_day_outcomes = late[pd.to_numeric(late[result_column], errors="coerce").notna()]
            if not late_day_outcomes.empty:
                late_day_average = round(float(pd.to_numeric(late_day_outcomes[result_column], errors="coerce").mean()), 4)
    time_of_day_caution = int(len(late_day_outcomes)) >= 5 and late_day_average < 0

    reasons: list[str] = []
    priority = "standard_watch"
    if historical_trades >= 20 and historical_expectancy >= 0.14 and health_status in {"healthy", "watch"}:
        priority = "high_evidence"
        reasons.append("Promoted historical setup with enough samples and positive expectancy.")
    elif health_status == "caution" or (historical_trades > 0 and historical_expectancy <= 0):
        priority = "caution_only"
        reasons.append("Setup health or promoted expectancy says caution.")
    elif health_status == "watch_more" or historical_trades < 10:
        priority = "needs_more_samples"
        reasons.append("Promising but under-sampled.")
    else:
        reasons.append("Standard paper-watch candidate.")

    if time_of_day_caution:
        reasons.append(f"Late-day candidate evidence is weak so far ({late_day_average:+.2f}R).")
    if health_flags and health_flags != "none":
        reasons.append(health_flags)

    return {
        "priority": priority,
        "reason": " ".join(reasons),
        "historical_expectancy_r": historical_expectancy,
        "historical_trades": historical_trades,
        "setup_health_status": health_status,
        "time_of_day_caution": bool(time_of_day_caution),
    }


def current_candidate_state(
    scanner: pd.DataFrame,
    sizing: pd.DataFrame,
    freshness: dict[str, Any],
    refresh_status: dict[str, Any],
    risk_guard: dict[str, Any] | None = None,
    setup_health: pd.DataFrame | None = None,
    promotion_review: pd.DataFrame | None = None,
    candidate_aging: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build app cards for current-candle scanner candidates.

    Candidate data already belongs to the scanner and position-sizing outputs.
    This function only joins those existing read-only outputs for display.
    """

    if scanner.empty:
        return {"count": 0, "ready_for_review_count": 0, "cards": []}

    candidates = scanner[
        scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
        & (scanner["signal_freshness"] == "current_candle")
    ].copy()
    if candidates.empty:
        return {"count": 0, "ready_for_review_count": 0, "cards": []}

    cards = []
    for _, row in candidates.iterrows():
        matching_size = pd.DataFrame()
        if not sizing.empty:
            matching_size = sizing[
                (sizing["symbol"] == row.get("symbol"))
                & (sizing["setup"] == row.get("setup"))
                & (sizing["direction"] == row.get("direction"))
            ]
        size = matching_size.iloc[0] if not matching_size.empty else pd.Series(dtype=object)

        scanner_allowed = row.get("scanner_status") == "allowed"
        data_fresh = freshness["data_status"] == "fresh_for_today"
        sizing_ok = size.get("sizing_status", "") == "size_ok"
        paper_import_unblocked = refresh_status.get("paper_import_blocked", True) is False
        ready_for_review = scanner_allowed and data_fresh and sizing_ok and paper_import_unblocked

        blockers = []
        if not scanner_allowed:
            blockers.append("Watch-only signal; not eligible for a paper trade.")
        if not data_fresh:
            blockers.append("Scanner data is not fresh for today.")
        if not sizing_ok:
            blockers.append(str(size.get("sizing_reason", "No eligible paper size is available.")))
        if not paper_import_unblocked:
            blockers.append("Paper import remains blocked until a reviewed current-session candidate is eligible.")

        scaling = scale_guidance(row, ready_for_review, risk_guard)
        priority = candidate_priority(
            row,
            setup_health if setup_health is not None else pd.DataFrame(),
            promotion_review if promotion_review is not None else pd.DataFrame(),
            candidate_aging if candidate_aging is not None else pd.DataFrame(),
        )
        cards.append(
            {
                "symbol": str(row.get("symbol", "")),
                "setup": str(row.get("setup", "")),
                "direction": str(row.get("direction", "")),
                "scanner_status": str(row.get("scanner_status", "")),
                "signal_time_et": str(row.get("latest_signal_et", "")),
                "entry": app_value(row.get("planned_entry", "")),
                "stop": app_value(row.get("planned_stop", "")),
                "target": app_value(row.get("planned_target", "")),
                "risk_per_share": app_value(row.get("risk_per_share", "")),
                "suggested_shares": app_value(size.get("suggested_shares", "")),
                "estimated_risk_dollars": app_value(size.get("estimated_risk_dollars", "")),
                "sizing_status": str(size.get("sizing_status", "missing")),
                "quality_grade": str(row.get("quality_grade", "")),
                "quality_score": app_value(row.get("quality_score", "")),
                "relative_volume": app_value(row.get("relative_volume", "")),
                "room_to_target_r": app_value(row.get("room_to_target_r", row.get("room_to_resistance_r", ""))),
                "scale_tier": scaling["scale_tier"],
                "scale_label": scaling["scale_label"],
                "suggested_risk_pct": scaling["suggested_risk_pct"],
                "option_premium_cap_pct": scaling["option_premium_cap_pct"],
                "scale_reason": scaling["scale_reason"],
                "risk_guard_status": str(risk_guard.get("status", "")) if risk_guard else "",
                "risk_guard_message": str(risk_guard.get("message", "")) if risk_guard else "",
                "evidence_priority": priority["priority"],
                "priority_reason": priority["reason"],
                "historical_expectancy_r": priority["historical_expectancy_r"],
                "historical_trades": priority["historical_trades"],
                "setup_health_status": priority["setup_health_status"],
                "time_of_day_caution": priority["time_of_day_caution"],
                "notes": str(row.get("notes", "")),
                "ready_for_review": ready_for_review,
                "blockers": blockers,
                "checklist_flags": [
                    {"label": "Current-candle signal", "passed": True},
                    {"label": "Scanner status allowed", "passed": scanner_allowed},
                    {"label": "Fresh current session data", "passed": data_fresh},
                    {"label": "Position sizing is size_ok", "passed": sizing_ok},
                    {"label": "Paper import review available", "passed": paper_import_unblocked},
                ],
            }
        )

    return {
        "count": len(cards),
        "ready_for_review_count": sum(bool(card["ready_for_review"]) for card in cards),
        "cards": cards,
    }


def paper_state(paper_log: pd.DataFrame, paper_review: pd.DataFrame) -> dict[str, Any]:
    """Summarize forward paper-validation progress."""

    allowed = pd.DataFrame()
    blocked = pd.DataFrame()
    if not paper_review.empty and "signal_status" in paper_review.columns:
        allowed = paper_review[paper_review["signal_status"] == "allowed"]
        blocked = paper_review[paper_review["signal_status"] == "blocked"]

    allowed_count = len(allowed)
    blocked_count = len(blocked)
    allowed_avg = float(allowed["review_r"].mean()) if allowed_count else 0.0
    blocked_avg = float(blocked["review_r"].mean()) if blocked_count else 0.0

    return {
        "paper_rows_logged": int(len(paper_log)),
        "completed_paper_trades": int(len(paper_review)),
        "allowed_completed_trades": int(allowed_count),
        "blocked_completed_trades": int(blocked_count),
        "allowed_average_r": round(allowed_avg, 4),
        "blocked_average_r": round(blocked_avg, 4),
        "first_gate_remaining": max(FIRST_PAPER_GATE - allowed_count, 0),
        "strong_gate_remaining": max(STRONG_PAPER_GATE - allowed_count, 0),
    }


def metric_summary(frame: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
    """Summarize completed paper results for app comparison cards."""

    if frame.empty or group_column not in frame.columns:
        return []

    rows = []
    for label, group in frame.groupby(group_column, dropna=False):
        results = group["review_r"].astype(float)
        rows.append(
            {
                "label": str(label),
                "trades": int(len(group)),
                "average_r": round(float(results.mean()), 4),
                "total_r": round(float(results.sum()), 4),
                "win_rate": round(float((results > 0).mean()), 4),
            }
        )
    return rows


def paper_visualization_state(paper_review: pd.DataFrame) -> dict[str, Any]:
    """Build chart-ready forward paper-progress data for the app.

    This deliberately uses completed forward paper trades only. Historical
    backtests remain separate from the paper-validation visualization.
    """

    empty_state = {
        "completed_trades": 0,
        "allowed_completed_trades": 0,
        "first_gate_percent": 0.0,
        "strong_gate_percent": 0.0,
        "total_r": 0.0,
        "cumulative_r_points": [],
        "by_signal_status": [],
        "by_plan_adherence": [],
    }
    if paper_review.empty or "review_r" not in paper_review.columns:
        return empty_state

    completed = paper_review.copy()
    completed["review_r"] = pd.to_numeric(completed["review_r"], errors="coerce")
    completed = completed.dropna(subset=["review_r"]).copy()
    if completed.empty:
        return empty_state

    date_column = "entry_time_et" if "entry_time_et" in completed.columns else "trade_date"
    completed["_sort_time"] = pd.to_datetime(completed[date_column], errors="coerce")
    completed = completed.sort_values("_sort_time", na_position="last").reset_index(drop=True)
    completed["cumulative_r"] = completed["review_r"].cumsum()

    points = []
    for index, row in completed.iterrows():
        points.append(
            {
                "trade_number": index + 1,
                "symbol": str(row.get("symbol", "")),
                "signal_status": str(row.get("signal_status", "")),
                "result_r": round(float(row["review_r"]), 4),
                "cumulative_r": round(float(row["cumulative_r"]), 4),
            }
        )

    allowed_count = int((completed["signal_status"] == "allowed").sum()) if "signal_status" in completed.columns else 0
    return {
        "completed_trades": int(len(completed)),
        "allowed_completed_trades": allowed_count,
        "first_gate_percent": round(min(allowed_count / FIRST_PAPER_GATE, 1.0) * 100, 1),
        "strong_gate_percent": round(min(allowed_count / STRONG_PAPER_GATE, 1.0) * 100, 1),
        "total_r": round(float(completed["review_r"].sum()), 4),
        "cumulative_r_points": points,
        "by_signal_status": metric_summary(completed, "signal_status"),
        "by_vehicle": metric_summary(completed, "vehicle"),
        "by_risk_tier": metric_summary(completed, "risk_tier"),
        "by_plan_adherence": metric_summary(completed, "followed_plan"),
    }


def setup_health_state(setup_health: pd.DataFrame) -> dict[str, Any]:
    """Summarize setup health scoring."""

    attention = []
    action_plan = []
    if not setup_health.empty:
        attention_frame = setup_health[setup_health["health_status"].isin(["watch_more", "caution"])].copy()
        keep = [
            "symbol",
            "setup",
            "direction",
            "health_status",
            "health_score",
            "trades",
            "expectancy_r",
            "profit_factor",
            "flags",
        ]
        attention = attention_frame[keep].to_dict("records") if not attention_frame.empty else []
        for item in attention:
            status = str(item.get("health_status", ""))
            trades_value = pd.to_numeric(item.get("trades", 0), errors="coerce")
            expectancy_value = pd.to_numeric(item.get("expectancy_r", 0), errors="coerce")
            trades = 0 if pd.isna(trades_value) else int(trades_value)
            expectancy = 0.0 if pd.isna(expectancy_value) else float(expectancy_value)
            if status == "caution":
                action = "Caution-only. Do not prioritize for new paper entries until the math improves."
            elif trades < 10:
                action = "Collect more shadow/forward samples before trusting this setup."
            elif expectancy > 0:
                action = "Paper-watch only with standard risk cap; sample is still developing."
            else:
                action = "Study only until expectancy turns positive."
            action_plan.append({**item, "action": action})

    return {
        "rows": int(len(setup_health)),
        "status_counts": status_counts(setup_health, "health_status"),
        "attention_count": int(len(attention)),
        "attention_setups": attention,
        "action_plan": action_plan,
    }


def clean_backtest_number(value: Any, *, percent: bool = False) -> float:
    """Convert backtest values to app-friendly finite numbers."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    result = float(number)
    if result == float("inf"):
        return 999.0
    if result == float("-inf"):
        return -999.0
    if percent:
        result *= 100
    return round(result, 2 if percent else 4)


def backtest_performance_state(output_dir: Path) -> dict[str, Any]:
    """Summarize latest watchlist backtest success for the app."""

    sources = [
        ("Setup A Long", output_dir / "best_plus_market_watchlist_backtest_summary.csv"),
        ("Setup B Short", output_dir / "setup_b_watchlist_backtest_summary.csv"),
    ]
    rows: list[dict[str, Any]] = []
    source_files = []
    for setup_family, path in sources:
        source_files.append(file_state(path))
        frame = read_csv_or_empty(path)
        if frame.empty:
            continue
        for _, row in frame.iterrows():
            trades = int(clean_backtest_number(row.get("baseline_trades", 0)))
            if trades <= 0:
                continue
            win_rate_pct = clean_backtest_number(row.get("baseline_win_rate", 0), percent=True)
            expectancy = clean_backtest_number(row.get("baseline_expectancy_r", 0))
            profit_factor = clean_backtest_number(row.get("baseline_profit_factor", 0))
            rows.append(
                {
                    "setup_family": setup_family,
                    "symbol": str(row.get("symbol", "")),
                    "candidate": f"{row.get('variant', '')} + {row.get('exit_profile', '')}",
                    "trades": trades,
                    "win_rate_pct": win_rate_pct,
                    "expectancy_r": expectancy,
                    "profit_factor": profit_factor,
                    "summary_report": str(row.get("summary_report", "")),
                    "baseline_trade_log": str(row.get("summary_report", "")).replace("_summary.md", "_baseline_trades.csv"),
                    "elite_trade_log": str(row.get("summary_report", "")).replace("_summary.md", "_elite_trades.csv"),
                }
            )

    rows = sorted(
        rows,
        key=lambda item: (item["expectancy_r"], item["profit_factor"], item["trades"]),
        reverse=True,
    )
    total_trades = sum(int(row["trades"]) for row in rows)
    positive_rows = [row for row in rows if float(row["expectancy_r"]) > 0]
    best = rows[0] if rows else {}

    return {
        "source_files": source_files,
        "candidate_count": int(len(rows)),
        "positive_expectancy_count": int(len(positive_rows)),
        "total_trades": int(total_trades),
        "best_candidate": best,
        "top_candidates": rows[:8],
    }


def research_confidence_state(output_dir: Path) -> dict[str, Any]:
    """Summarize broad research-universe confidence scores for the app."""

    research_dir = output_dir / "universe_expansion"
    research_csv = research_dir / "research_confidence.csv"
    research_md = research_dir / "research_confidence.md"
    frame = read_csv_or_empty(research_csv)

    rows: list[dict[str, Any]] = []
    if not frame.empty:
        keep = [
            "research_status",
            "readiness_score",
            "symbol",
            "setup",
            "candidate",
            "duplicate_rows_collapsed",
            "trades",
            "win_rate_pct",
            "expectancy_r",
            "profit_factor",
            "summary_report",
        ]
        for column in keep:
            if column not in frame.columns:
                frame[column] = ""
        for _, row in frame.head(10).iterrows():
            rows.append(
                {
                    "research_status": str(row.get("research_status", "")),
                    "readiness_score": int(clean_backtest_number(row.get("readiness_score", 0))),
                    "symbol": str(row.get("symbol", "")),
                    "setup": str(row.get("setup", "")),
                    "candidate": str(row.get("candidate", "")),
                    "trades": int(clean_backtest_number(row.get("trades", 0))),
                    "win_rate_pct": clean_backtest_number(row.get("win_rate_pct", 0)),
                    "expectancy_r": clean_backtest_number(row.get("expectancy_r", 0)),
                    "profit_factor": clean_backtest_number(row.get("profit_factor", 0)),
                    "summary_report": str(row.get("summary_report", "")),
                }
            )

    return {
        "source_csv": file_state(research_csv),
        "source_report": file_state(research_md),
        "tested_symbols": int(frame["symbol"].nunique()) if not frame.empty and "symbol" in frame.columns else 0,
        "candidate_count": int(len(frame)),
        "research_ready_count": int((frame["research_status"] == "research_ready").sum())
        if not frame.empty and "research_status" in frame.columns
        else 0,
        "promising_count": int((frame["research_status"] == "promising").sum())
        if not frame.empty and "research_status" in frame.columns
        else 0,
        "watch_more_count": int((frame["research_status"] == "watch_more").sum())
        if not frame.empty and "research_status" in frame.columns
        else 0,
        "top_candidates": rows,
    }


def promotion_review_state(output_dir: Path) -> dict[str, Any]:
    """Summarize the promotion-review gate for the app."""

    review_csv = output_dir / "promotion_review.csv"
    review_md = output_dir / "promotion_review.md"
    frame = read_csv_or_empty(review_csv)

    rows: list[dict[str, Any]] = []
    if not frame.empty:
        keep = [
            "promotion_decision",
            "symbol",
            "setup",
            "candidate",
            "trades",
            "expectancy_r",
            "profit_factor",
            "max_drawdown_r",
            "positive_months",
            "months_tested",
            "largest_win_share",
            "alternate_candidates",
            "promotion_reason",
            "trade_log",
        ]
        for column in keep:
            if column not in frame.columns:
                frame[column] = ""
        for _, row in frame.head(10).iterrows():
            rows.append(
                {
                    "promotion_decision": str(row.get("promotion_decision", "")),
                    "symbol": str(row.get("symbol", "")),
                    "setup": str(row.get("setup", "")),
                    "candidate": str(row.get("candidate", "")),
                    "duplicate_rows_collapsed": int(clean_backtest_number(row.get("duplicate_rows_collapsed", 1))),
                    "trades": int(clean_backtest_number(row.get("trades", 0))),
                    "expectancy_r": clean_backtest_number(row.get("expectancy_r", 0)),
                    "profit_factor": clean_backtest_number(row.get("profit_factor", 0)),
                    "max_drawdown_r": clean_backtest_number(row.get("max_drawdown_r", 0)),
                    "positive_months": int(clean_backtest_number(row.get("positive_months", 0))),
                    "months_tested": int(clean_backtest_number(row.get("months_tested", 0))),
                    "largest_win_share": clean_backtest_number(row.get("largest_win_share", 0), percent=True),
                    "alternate_candidates": str(row.get("alternate_candidates", "")),
                    "promotion_reason": str(row.get("promotion_reason", "")),
                    "trade_log": str(row.get("trade_log", "")),
                }
            )

    return {
        "source_csv": file_state(review_csv),
        "source_report": file_state(review_md),
        "candidate_count": int(len(frame)),
        "paper_watch_count": int((frame["promotion_decision"] == "paper_watch_candidate").sum())
        if not frame.empty and "promotion_decision" in frame.columns
        else 0,
        "needs_more_samples_count": int((frame["promotion_decision"] == "needs_more_samples").sum())
        if not frame.empty and "promotion_decision" in frame.columns
        else 0,
        "needs_review_count": int(
            frame["promotion_decision"].isin(
                ["needs_more_stability", "needs_outlier_review", "needs_risk_review"]
            ).sum()
        )
        if not frame.empty and "promotion_decision" in frame.columns
        else 0,
        "top_candidates": rows,
    }


def readiness_verdict(
    market: dict[str, Any],
    freshness: dict[str, Any],
    scanner: dict[str, Any],
    sizing: dict[str, Any],
    paper: dict[str, Any],
) -> str:
    """Choose the highest-level operating verdict."""

    if freshness["data_status"] != "fresh_for_today":
        return freshness["action"]
    if scanner["current_candidate_count"] > 0 and sizing["eligible_size_count"] > 0:
        return "Review the checklist and position sizing before any paper trade."
    if paper["allowed_completed_trades"] < FIRST_PAPER_GATE:
        return "Keep collecting valid current-candle paper trades toward the 30-trade checkpoint."
    if not market["is_market_day"]:
        return "Market is closed. Prep only."
    return "No current paper candidate is ready. Keep the workflow refreshed."


def build_system_state(
    output_dir: Path = Path("logs"),
    paper_csv: Path = Path("data/paper_trades.csv"),
) -> dict[str, Any]:
    """Build the full system state dictionary."""

    scanner_csv = output_dir / "daily_paper_signal_scanner.csv"
    sizing_csv = output_dir / "position_sizing.csv"
    forward_observations_csv = Path("data/forward_signal_observations.csv")
    shadow_samples_csv = Path("data/shadow_samples.csv")
    vwap_mean_reversion_shadow_samples_csv = Path("data/vwap_mean_reversion_shadow_samples.csv")
    vwap_mean_reversion_forward_observations_csv = Path("data/vwap_mean_reversion_forward_observations.csv")
    forward_observations_md = output_dir / "forward_signal_observations.md"
    near_miss_csv = Path("data/near_miss_observations.csv")
    near_miss_md = output_dir / "near_miss_analytics.md"
    forward_results_csv = output_dir / "forward_observation_results.csv"
    shadow_outcomes_csv = output_dir / "shadow_sample_outcomes.csv"
    vwap_mean_reversion_shadow_outcomes_csv = output_dir / "vwap_mean_reversion_shadow_outcomes.csv"
    vwap_mean_reversion_forward_results_csv = output_dir / "vwap_mean_reversion_forward_observation_results.csv"
    candidate_aging_csv = output_dir / "candidate_aging.csv"
    forward_review_md = output_dir / "forward_observation_review.md"
    reconciliation_csv = output_dir / "observation_paper_reconciliation.csv"
    reconciliation_md = output_dir / "observation_paper_reconciliation.md"
    integrity_csv = output_dir / "candle_data_integrity.csv"
    integrity_md = output_dir / "candle_data_integrity.md"
    refresh_audit_csv = Path("data/market_refresh_audit.csv")
    refresh_audit_md = output_dir / "market_refresh_audit.md"
    paper_review_csv = output_dir / "paper_review_clean_trades.csv"
    pre_entry_review_json = output_dir / "pre_entry_review.json"
    pre_entry_review_md = output_dir / "pre_entry_review.md"
    pre_entry_review_csv = output_dir / "pre_entry_review.csv"
    setup_health_csv = output_dir / "setup_health.csv"
    promotion_review_csv = output_dir / "promotion_review.csv"
    strategy_improvement_plan_json = output_dir / "strategy_improvement_plan.json"
    strategy_improvement_plan_md = output_dir / "strategy_improvement_plan.md"
    strategy_vault_json = output_dir / "strategy_vault.json"
    strategy_vault_md = output_dir / "strategy_vault.md"
    vwap_mean_reversion_json = output_dir / "vwap_mean_reversion.json"
    vwap_mean_reversion_md = output_dir / "vwap_mean_reversion.md"
    vwap_mean_reversion_summary_csv = output_dir / "vwap_mean_reversion_summary.csv"
    vwap_mean_reversion_walk_forward_json = output_dir / "vwap_mean_reversion_walk_forward.json"
    vwap_mean_reversion_walk_forward_md = output_dir / "vwap_mean_reversion_walk_forward.md"
    vwap_mean_reversion_walk_forward_csv = output_dir / "vwap_mean_reversion_walk_forward.csv"
    vwap_mean_reversion_shadow_md = output_dir / "vwap_mean_reversion_shadow_samples.md"
    vwap_mean_reversion_forward_md = output_dir / "vwap_mean_reversion_forward_observations.md"
    vwap_mean_reversion_paper_watch_gate_json = output_dir / "vwap_mean_reversion_paper_watch_gate.json"
    vwap_mean_reversion_paper_watch_gate_md = output_dir / "vwap_mean_reversion_paper_watch_gate.md"
    vwap_mean_reversion_paper_watch_gate_csv = output_dir / "vwap_mean_reversion_paper_watch_gate.csv"
    opening_range_breakout_json = output_dir / "opening_range_breakout.json"
    opening_range_breakout_md = output_dir / "opening_range_breakout.md"
    opening_range_breakout_summary_csv = output_dir / "opening_range_breakout_summary.csv"
    opening_range_failure_json = output_dir / "opening_range_failure.json"
    opening_range_failure_md = output_dir / "opening_range_failure.md"
    opening_range_failure_summary_csv = output_dir / "opening_range_failure_summary.csv"
    strategy_evidence_accumulator_json = output_dir / "strategy_evidence_accumulator.json"
    strategy_evidence_accumulator_md = output_dir / "strategy_evidence_accumulator.md"
    strategy_evidence_accumulator_csv = output_dir / "strategy_evidence_accumulator.csv"
    paper_activation_rules_json = output_dir / "paper_activation_rules.json"
    paper_activation_rules_md = output_dir / "paper_activation_rules.md"
    paper_activation_rules_csv = output_dir / "paper_activation_rules.csv"
    feature_wiring_audit_json = output_dir / "feature_wiring_audit.json"
    feature_wiring_audit_md = output_dir / "feature_wiring_audit.md"
    dashboard_md = output_dir / "project_gwala_dashboard.md"
    readiness_md = output_dir / "readiness_check.md"
    system_state_json = output_dir / "system_state.json"
    system_state_md = output_dir / "system_state.md"
    refresh_status_json = output_dir / "refresh_status.json"
    refresh_status_md = output_dir / "refresh_status.md"
    forward_sample_queue_csv = output_dir / "forward_sample_queue.csv"
    forward_sample_queue_md = output_dir / "forward_sample_queue.md"
    almost_ready_breakout_json = output_dir / "almost_ready_breakout.json"
    almost_ready_breakout_md = output_dir / "almost_ready_breakout.md"
    post_scan_digest_json = output_dir / "post_scan_digest.json"
    post_scan_digest_md = output_dir / "post_scan_digest.md"
    premarket_verification_json = output_dir / "premarket_verification.json"
    premarket_verification_md = output_dir / "premarket_verification.md"
    setup_replay_json = output_dir / "setup_replay.json"
    setup_replay_md = output_dir / "setup_replay.md"
    autonomous_status_md = output_dir / "autonomous_paper_workflow_status.md"
    autonomous_status_json = output_dir / "autonomous_paper_workflow_status.json"
    morning_watchdog_json = output_dir / "morning_run_watchdog.json"
    morning_watchdog_md = output_dir / "morning_run_watchdog.md"
    automation_timeline_json = output_dir / "daily_automation_timeline.json"
    automation_timeline_md = output_dir / "daily_automation_timeline.md"

    scanner_frame = read_csv_or_empty(scanner_csv)
    sizing_frame = read_csv_or_empty(sizing_csv)
    forward_observations = read_csv_or_empty(forward_observations_csv)
    shadow_samples = read_csv_or_empty(shadow_samples_csv)
    vwap_mean_reversion_shadow_samples = read_csv_or_empty(vwap_mean_reversion_shadow_samples_csv)
    vwap_mean_reversion_forward_observations = read_csv_or_empty(vwap_mean_reversion_forward_observations_csv)
    forward_results = read_csv_or_empty(forward_results_csv)
    shadow_outcomes = read_csv_or_empty(shadow_outcomes_csv)
    vwap_mean_reversion_shadow_outcomes = read_csv_or_empty(vwap_mean_reversion_shadow_outcomes_csv)
    vwap_mean_reversion_forward_results = read_csv_or_empty(vwap_mean_reversion_forward_results_csv)
    candidate_aging = read_csv_or_empty(candidate_aging_csv)
    reconciliation = read_csv_or_empty(reconciliation_csv)
    integrity = read_csv_or_empty(integrity_csv)
    refresh_audit = read_csv_or_empty(refresh_audit_csv)
    paper_log = read_csv_or_empty(paper_csv)
    paper_review = read_csv_or_empty(paper_review_csv)
    setup_health = read_csv_or_empty(setup_health_csv)
    promotion_review_frame = read_csv_or_empty(promotion_review_csv)
    strategy_improvement_plan = read_json_or_empty(strategy_improvement_plan_json)
    strategy_vault = read_json_or_empty(strategy_vault_json)
    feature_wiring_audit = read_json_or_empty(feature_wiring_audit_json)
    refresh_status = read_json_or_empty(refresh_status_json)
    premarket_verification = read_json_or_empty(premarket_verification_json)
    setup_replay = read_json_or_empty(setup_replay_json)
    almost_ready_breakout = read_json_or_empty(almost_ready_breakout_json)
    morning_watchdog = read_json_or_empty(morning_watchdog_json)
    post_scan_digest = read_json_or_empty(post_scan_digest_json)
    automation_timeline = read_json_or_empty(automation_timeline_json)

    market = market_state()
    freshness = data_freshness_state(scanner_frame, market)
    scanner = scanner_state(scanner_frame)
    sizing = sizing_state(sizing_frame)
    observations = forward_observation_state(forward_observations)
    forward_validation = forward_validation_state(forward_results, reconciliation, integrity, refresh_audit)
    paper = paper_state(paper_log, paper_review)
    risk_guard = risk_guard_state(paper)
    current_candidates = current_candidate_state(
        scanner_frame,
        sizing_frame,
        freshness,
        refresh_status,
        risk_guard,
        setup_health=setup_health,
        promotion_review=promotion_review_frame,
        candidate_aging=candidate_aging,
    )
    forward_sample_queue = forward_sample_queue_payload(
        build_forward_sample_queue(scanner_frame, sizing_frame, market),
        paper_review,
        forward_observations,
    )
    forward_evidence_bridge = forward_evidence_bridge_state(
        paper,
        observations,
        forward_validation,
        shadow_samples,
        shadow_outcomes,
        candidate_aging,
        forward_sample_queue,
    )
    data_reliability = data_reliability_state(freshness, refresh_status, automation_timeline)
    paper_visualization = paper_visualization_state(paper_review)
    health = setup_health_state(setup_health)
    backtests = backtest_performance_state(output_dir)
    research_confidence = research_confidence_state(output_dir)
    promotion_review = promotion_review_state(output_dir)
    premarket = premarket_verification_state(premarket_verification, premarket_verification_json)
    now = datetime.now(MARKET_TZ)
    source_files = {
        "scanner_csv": str(scanner_csv),
        "sizing_csv": str(sizing_csv),
        "forward_observations_csv": str(forward_observations_csv),
        "shadow_samples_csv": str(shadow_samples_csv),
        "vwap_mean_reversion_shadow_samples_csv": str(vwap_mean_reversion_shadow_samples_csv),
        "vwap_mean_reversion_forward_observations_csv": str(vwap_mean_reversion_forward_observations_csv),
        "near_miss_csv": str(near_miss_csv),
        "forward_results_csv": str(forward_results_csv),
        "reconciliation_csv": str(reconciliation_csv),
        "integrity_csv": str(integrity_csv),
        "refresh_audit_csv": str(refresh_audit_csv),
        "paper_csv": str(paper_csv),
        "paper_review_csv": str(paper_review_csv),
        "pre_entry_review_json": str(pre_entry_review_json),
        "setup_health_csv": str(setup_health_csv),
        "research_confidence_csv": str(output_dir / "universe_expansion" / "research_confidence.csv"),
        "promotion_review_csv": str(promotion_review_csv),
        "strategy_improvement_plan_json": str(strategy_improvement_plan_json),
        "strategy_vault_json": str(strategy_vault_json),
        "vwap_mean_reversion_json": str(vwap_mean_reversion_json),
        "vwap_mean_reversion_walk_forward_json": str(vwap_mean_reversion_walk_forward_json),
        "feature_wiring_audit_json": str(feature_wiring_audit_json),
        "forward_sample_queue_csv": str(forward_sample_queue_csv),
        "almost_ready_breakout_json": str(almost_ready_breakout_json),
        "shadow_outcomes_csv": str(shadow_outcomes_csv),
        "vwap_mean_reversion_shadow_outcomes_csv": str(vwap_mean_reversion_shadow_outcomes_csv),
        "vwap_mean_reversion_forward_observation_results_csv": str(vwap_mean_reversion_forward_results_csv),
        "vwap_mean_reversion_paper_watch_gate_json": str(vwap_mean_reversion_paper_watch_gate_json),
        "opening_range_breakout_json": str(opening_range_breakout_json),
        "opening_range_failure_json": str(opening_range_failure_json),
        "strategy_evidence_accumulator_json": str(strategy_evidence_accumulator_json),
        "paper_activation_rules_json": str(paper_activation_rules_json),
        "candidate_aging_csv": str(candidate_aging_csv),
        "post_scan_digest_json": str(post_scan_digest_json),
        "refresh_status_json": str(refresh_status_json),
        "premarket_verification_json": str(premarket_verification_json),
        "setup_replay_json": str(setup_replay_json),
        "autonomous_status_md": str(autonomous_status_md),
        "autonomous_status_json": str(autonomous_status_json),
        "morning_watchdog_json": str(morning_watchdog_json),
        "automation_timeline_json": str(automation_timeline_json),
    }

    return {
        "schema_version": 1,
        "generated_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "project_phase": "research_and_paper_validation",
        "safety": {
            "live_trading_enabled": False,
            "broker_order_execution_enabled": False,
            "real_money_ready": False,
        },
        "market": market,
        "data_freshness": freshness,
        "scanner": scanner,
        "position_sizing": sizing,
        "forward_observations": observations,
        "forward_validation": forward_validation,
        "forward_evidence_bridge": forward_evidence_bridge,
        "data_reliability": data_reliability,
        "current_candidates": current_candidates,
        "forward_sample_queue": forward_sample_queue,
        "almost_ready_breakout": almost_ready_breakout,
        "post_scan_digest": post_scan_digest,
        "paper_progress": paper,
        "risk_guard": risk_guard,
        "paper_visualization": paper_visualization,
        "setup_health": health,
        "backtest_performance": backtests,
        "research_confidence": research_confidence,
        "promotion_review": promotion_review,
        "strategy_improvement_plan": strategy_improvement_plan,
        "strategy_vault": strategy_vault,
        "feature_wiring_audit": feature_wiring_audit,
        "refresh_status": refresh_status,
        "premarket_verification": premarket,
        "morning_watchdog": morning_watchdog,
        "automation_timeline": automation_timeline,
        "setup_replay": {
            "count": int(setup_replay.get("count", 0)),
            "cards": setup_replay.get("cards", []) if isinstance(setup_replay.get("cards", []), list) else [],
        },
        "readiness_verdict": readiness_verdict(market, freshness, scanner, sizing, paper),
        "app_health": {
            "generated_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "source_file_states": {
                "scanner_csv": file_state(scanner_csv),
                "sizing_csv": file_state(sizing_csv),
                "forward_observations_csv": file_state(forward_observations_csv),
                "shadow_samples_csv": file_state(shadow_samples_csv),
                "vwap_mean_reversion_shadow_samples_csv": file_state(vwap_mean_reversion_shadow_samples_csv),
                "vwap_mean_reversion_forward_observations_csv": file_state(vwap_mean_reversion_forward_observations_csv),
                "forward_observations_md": file_state(forward_observations_md),
                "near_miss_csv": file_state(near_miss_csv),
                "near_miss_md": file_state(near_miss_md),
                "forward_results_csv": file_state(forward_results_csv),
                "forward_review_md": file_state(forward_review_md),
                "reconciliation_csv": file_state(reconciliation_csv),
                "reconciliation_md": file_state(reconciliation_md),
                "integrity_csv": file_state(integrity_csv),
                "integrity_md": file_state(integrity_md),
                "refresh_audit_csv": file_state(refresh_audit_csv),
                "refresh_audit_md": file_state(refresh_audit_md),
                "paper_csv": file_state(paper_csv),
                "paper_review_csv": file_state(paper_review_csv),
                "pre_entry_review_json": file_state(pre_entry_review_json),
                "pre_entry_review_md": file_state(pre_entry_review_md),
                "pre_entry_review_csv": file_state(pre_entry_review_csv),
                "setup_health_csv": file_state(setup_health_csv),
                "research_confidence_csv": research_confidence["source_csv"],
                "research_confidence_md": research_confidence["source_report"],
                "promotion_review_csv": promotion_review["source_csv"],
                "promotion_review_md": promotion_review["source_report"],
                "strategy_improvement_plan_json": file_state(strategy_improvement_plan_json),
                "strategy_improvement_plan_md": file_state(strategy_improvement_plan_md),
                "strategy_vault_json": file_state(strategy_vault_json),
                "strategy_vault_md": file_state(strategy_vault_md),
                "vwap_mean_reversion_json": file_state(vwap_mean_reversion_json),
                "vwap_mean_reversion_md": file_state(vwap_mean_reversion_md),
                "vwap_mean_reversion_summary_csv": file_state(vwap_mean_reversion_summary_csv),
                "vwap_mean_reversion_walk_forward_json": file_state(vwap_mean_reversion_walk_forward_json),
                "vwap_mean_reversion_walk_forward_md": file_state(vwap_mean_reversion_walk_forward_md),
                "vwap_mean_reversion_walk_forward_csv": file_state(vwap_mean_reversion_walk_forward_csv),
                "vwap_mean_reversion_shadow_md": file_state(vwap_mean_reversion_shadow_md),
                "vwap_mean_reversion_shadow_outcomes_csv": file_state(vwap_mean_reversion_shadow_outcomes_csv),
                "vwap_mean_reversion_forward_md": file_state(vwap_mean_reversion_forward_md),
                "vwap_mean_reversion_forward_observation_results_csv": file_state(vwap_mean_reversion_forward_results_csv),
                "vwap_mean_reversion_paper_watch_gate_json": file_state(vwap_mean_reversion_paper_watch_gate_json),
                "vwap_mean_reversion_paper_watch_gate_md": file_state(vwap_mean_reversion_paper_watch_gate_md),
                "vwap_mean_reversion_paper_watch_gate_csv": file_state(vwap_mean_reversion_paper_watch_gate_csv),
                "opening_range_breakout_json": file_state(opening_range_breakout_json),
                "opening_range_breakout_md": file_state(opening_range_breakout_md),
                "opening_range_breakout_summary_csv": file_state(opening_range_breakout_summary_csv),
                "opening_range_failure_json": file_state(opening_range_failure_json),
                "opening_range_failure_md": file_state(opening_range_failure_md),
                "opening_range_failure_summary_csv": file_state(opening_range_failure_summary_csv),
                "strategy_evidence_accumulator_json": file_state(strategy_evidence_accumulator_json),
                "strategy_evidence_accumulator_md": file_state(strategy_evidence_accumulator_md),
                "strategy_evidence_accumulator_csv": file_state(strategy_evidence_accumulator_csv),
                "paper_activation_rules_json": file_state(paper_activation_rules_json),
                "paper_activation_rules_md": file_state(paper_activation_rules_md),
                "paper_activation_rules_csv": file_state(paper_activation_rules_csv),
                "feature_wiring_audit_json": file_state(feature_wiring_audit_json),
                "feature_wiring_audit_md": file_state(feature_wiring_audit_md),
                "dashboard_md": file_state(dashboard_md),
                "readiness_md": file_state(readiness_md),
                "refresh_status_json": file_state(refresh_status_json),
                "refresh_status_md": file_state(refresh_status_md),
                "forward_sample_queue_csv": file_state(forward_sample_queue_csv),
                "almost_ready_breakout_json": file_state(almost_ready_breakout_json),
                "almost_ready_breakout_md": file_state(almost_ready_breakout_md),
                "shadow_outcomes_csv": file_state(shadow_outcomes_csv),
                "candidate_aging_csv": file_state(candidate_aging_csv),
                "forward_sample_queue_md": file_state(forward_sample_queue_md),
                "post_scan_digest_json": file_state(post_scan_digest_json),
                "post_scan_digest_md": file_state(post_scan_digest_md),
                "premarket_verification_json": file_state(premarket_verification_json),
                "premarket_verification_md": file_state(premarket_verification_md),
                "setup_replay_json": file_state(setup_replay_json),
                "setup_replay_md": file_state(setup_replay_md),
                "autonomous_status_md": file_state(autonomous_status_md),
                "autonomous_status_json": file_state(autonomous_status_json),
                "morning_watchdog_json": file_state(morning_watchdog_json),
                "morning_watchdog_md": file_state(morning_watchdog_md),
                "automation_timeline_json": file_state(automation_timeline_json),
                "automation_timeline_md": file_state(automation_timeline_md),
                "system_state_json": file_state(system_state_json),
                "system_state_md": file_state(system_state_md),
            },
        },
        "source_files": source_files,
    }
