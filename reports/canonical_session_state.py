"""Canonical founder-facing session reconciliation.

This module is reporting/evidence-integrity only. It reads authoritative
artifacts and normalizes the founder-critical metrics that reports and the
Command Center must agree on. It does not change strategy, gates, risk,
broker state, ledgers, or paper evidence.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from reports.cohort_freeze import COHORT_VERSION
from reports.cohort_freeze import load_cohort_1_freeze


CANONICAL_SCHEMA_VERSION = "canonical-session-state-v1"
UNKNOWN = "UNKNOWN"
CHECKPOINT_TARGET = 30
INDEPENDENT_OPPORTUNITY_BASELINE = 20
INDEPENDENT_OPPORTUNITY_BASELINE_DATE = "2026-08-13"


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def clean_text(value: object) -> str:
    return str(value or "").strip()


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str], str]:
    if not path.exists():
        return [], [], "missing"
    try:
        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            return list(reader), list(reader.fieldnames or []), ""
    except Exception as error:
        return [], [], f"read_error: {error}"


def read_json(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return {}, f"read_error: {error}"
    return payload if isinstance(payload, dict) else {}, ""


def numeric(value: object) -> float | None:
    text = clean_text(value)
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def metric(
    name: str,
    value: object,
    *,
    owner: str,
    source: str,
    definition: str,
    session_scope: str,
    freshness: str = "session-scoped",
    status: str = "OK",
    reason: str = "",
    schema: str = CANONICAL_SCHEMA_VERSION,
    provenance: str = "authoritative",
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "status": status,
        "reason": reason,
        "owner": owner,
        "source": source,
        "definition": definition,
        "schema": schema,
        "session_scope": session_scope,
        "freshness_requirement": freshness,
        "unavailable_behavior": "Return UNKNOWN with reason; never silently coerce unreadable sources to zero.",
        "provenance": provenance,
    }


def unknown_metric(name: str, *, source: str, reason: str, definition: str, session_scope: str) -> dict[str, Any]:
    return metric(
        name,
        UNKNOWN,
        owner="Validation/Reconciliation",
        source=source,
        definition=definition,
        session_scope=session_scope,
        status="UNKNOWN",
        reason=reason,
        provenance="unavailable",
    )


def validation_reconciliation(data_dir: Path, trading_day: date) -> dict[str, Any]:
    source = data_dir / "paper_validation_samples.csv"
    rows, fields, error = read_csv_rows(source)
    required = {"counts_toward_30", "invalid_for_validation", "sample_status", "outcome_r", "sample_date"}
    if error:
        reason = f"validation source {error}"
        return {
            "status": "UNKNOWN",
            "source": str(source),
            "reason": reason,
            "metrics": {
                key: unknown_metric(
                    key,
                    source=str(source),
                    reason=reason,
                    definition="Unavailable because the authoritative validation ledger could not be read.",
                    session_scope="all-time",
                )
                for key in [
                    "total_rows",
                    "valid_completed_observations",
                    "valid_open_observations",
                    "invalid_excluded_rows",
                    "new_official_observations_today",
                    "new_completed_observations_today",
                    "checkpoint",
                    "today_r",
                ]
            },
            "completed_rows": [],
            "today_completed_rows": [],
        }
    missing = sorted(required - set(fields))
    if missing:
        reason = f"validation schema mismatch; missing required fields: {', '.join(missing)}"
        return {
            "status": "UNKNOWN",
            "source": str(source),
            "reason": reason,
            "metrics": {
                key: unknown_metric(
                    key,
                    source=str(source),
                    reason=reason,
                    definition="Unavailable because validation schema drift was detected.",
                    session_scope="all-time",
                )
                for key in [
                    "total_rows",
                    "valid_completed_observations",
                    "valid_open_observations",
                    "invalid_excluded_rows",
                    "new_official_observations_today",
                    "new_completed_observations_today",
                    "checkpoint",
                    "today_r",
                ]
            },
            "completed_rows": [],
            "today_completed_rows": [],
        }

    official = [row for row in rows if truthy(row.get("counts_toward_30"))]
    invalid = [row for row in official if truthy(row.get("invalid_for_validation"))]
    valid = [row for row in official if not truthy(row.get("invalid_for_validation"))]
    completed = [
        row
        for row in valid
        if clean_text(row.get("sample_status")).lower() == "completed" or numeric(row.get("outcome_r")) is not None
    ]
    open_rows = [row for row in valid if row not in completed]
    today = trading_day.isoformat()
    today_official = [row for row in valid if clean_text(row.get("sample_date")) == today]
    today_completed = [row for row in completed if clean_text(row.get("sample_date")) == today]
    today_r = round(sum(numeric(row.get("outcome_r")) or 0.0 for row in today_completed), 4)
    completed_r = [numeric(row.get("outcome_r")) for row in completed]
    completed_r = [value for value in completed_r if value is not None]

    metrics = {
        "total_rows": metric(
            "Total Validation Ledger Rows",
            len(rows),
            owner="Validation/Reconciliation",
            source=str(source),
            definition="All rows physically present in paper_validation_samples.csv.",
            session_scope="all-time",
        ),
        "valid_completed_observations": metric(
            "Completed Official Strategy Observations",
            len(completed),
            owner="Validation/Reconciliation",
            source=str(source),
            definition="sample_status=completed OR outcome_r numeric, AND counts_toward_30, AND NOT invalid_for_validation.",
            session_scope="all-time",
        ),
        "valid_open_observations": metric(
            "Valid Open Official Observations",
            len(open_rows),
            owner="Validation/Reconciliation",
            source=str(source),
            definition="counts_toward_30 AND NOT invalid_for_validation AND not completed.",
            session_scope="all-time",
        ),
        "invalid_excluded_rows": metric(
            "Invalid/Excluded Official Rows",
            len(invalid),
            owner="Validation/Reconciliation",
            source=str(source),
            definition="counts_toward_30 AND invalid_for_validation.",
            session_scope="all-time",
        ),
        "new_official_observations_today": metric(
            "New Official Strategy Observations Today",
            len(today_official),
            owner="Validation/Reconciliation",
            source=str(source),
            definition="Official non-invalid rows where sample_date equals the reconciled trading session.",
            session_scope=today,
        ),
        "new_completed_observations_today": metric(
            "New Completed Official Observations Today",
            len(today_completed),
            owner="Validation/Reconciliation",
            source=str(source),
            definition="Completed official observations where sample_date equals the reconciled trading session.",
            session_scope=today,
        ),
        "checkpoint": metric(
            "Phase 2 Official Checkpoint",
            f"{len(completed)} / {CHECKPOINT_TARGET}",
            owner="Validation/Reconciliation",
            source=str(source),
            definition="Completed official strategy observations against the original Phase 2 checkpoint.",
            session_scope="all-time",
        ),
        "today_r": metric(
            "Completed Official R Today",
            today_r,
            owner="Validation/Reconciliation",
            source=str(source),
            definition="Sum of outcome_r for completed official observations on the reconciled trading session.",
            session_scope=today,
        ),
    }
    return {
        "status": "OK",
        "source": str(source),
        "reason": "",
        "schema_fields": fields,
        "metrics": metrics,
        "completed_rows": completed,
        "today_completed_rows": today_completed,
        "completed_r": completed_r,
    }


def derived_independent_opportunities(validation: dict[str, Any], trading_day: date) -> dict[str, Any]:
    today_completed = validation.get("today_completed_rows") or []
    value: object = UNKNOWN
    status = "DERIVED"
    reason = (
        "Independent opportunities are not yet persisted authoritatively. "
        "Using governed 2026-08-13 baseline plus distinct completed official opportunities after that date."
    )
    if validation.get("status") == "OK":
        after_baseline = {
            (
                clean_text(row.get("sample_date")),
                clean_text(row.get("entry_time_et")),
                clean_text(row.get("symbol")).upper(),
                clean_text(row.get("direction")).lower(),
            )
            for row in today_completed
            if clean_text(row.get("sample_date")) > INDEPENDENT_OPPORTUNITY_BASELINE_DATE
        }
        value = INDEPENDENT_OPPORTUNITY_BASELINE + len(after_baseline)
    return metric(
        "Independent Market Opportunities",
        value,
        owner="Governance/Reconciliation",
        source="docs/cohort-1-evidence-independence-governance.md + paper_validation_samples.csv",
        definition="Governed audited baseline plus distinct post-baseline market opportunities; not interchangeable with strategy observations.",
        session_scope="all-time",
        status=status if value != UNKNOWN else "UNKNOWN",
        reason=reason,
        provenance="derived/effective",
    )


def candidate_funnel(logs_dir: Path, data_dir: Path, trading_day: date, validation: dict[str, Any]) -> dict[str, Any]:
    scanner_rows, _, scanner_error = read_csv_rows(logs_dir / "daily_paper_signal_scanner.csv")
    sizing_rows, _, sizing_error = read_csv_rows(logs_dir / "position_sizing.csv")
    paper_gate_rows, _, paper_error = read_csv_rows(logs_dir / "paper_gate_v2.csv")
    capture, capture_error = read_json(logs_dir / "current_candle_capture.json")
    today = trading_day.isoformat()

    def scanner_count(status: str) -> int | str:
        if scanner_error:
            return UNKNOWN
        return sum(1 for row in scanner_rows if clean_text(row.get("scanner_status")).lower() == status)

    def sizing_count(status: str) -> int | str:
        if sizing_error:
            return UNKNOWN
        return sum(1 for row in sizing_rows if clean_text(row.get("sizing_status")).lower() == status)

    def paper_ready() -> int | str:
        if paper_error:
            return UNKNOWN
        return sum(
            1
            for row in paper_gate_rows
            if clean_text(row.get("sample_status")).lower() in {"ready_for_validation_sample", "open"}
            and truthy(row.get("counts_toward_30"))
        )

    def metric_for(name: str, value: object, source: Path, definition: str, reason: str = "") -> dict[str, Any]:
        return metric(
            name,
            value,
            owner="Session Reconciliation",
            source=str(source),
            definition=definition,
            session_scope=today,
            status="UNKNOWN" if value == UNKNOWN else "OK",
            reason=reason,
        )

    official_imports = validation["metrics"]["new_official_observations_today"]["value"]
    completed_today = validation["metrics"]["new_completed_observations_today"]["value"]
    return {
        "scanner": metric_for("Scanner Rows", UNKNOWN if scanner_error else len(scanner_rows), logs_dir / "daily_paper_signal_scanner.csv", "Rows in session scanner artifact.", scanner_error),
        "allowed": metric_for("Allowed Scanner Rows", scanner_count("allowed"), logs_dir / "daily_paper_signal_scanner.csv", "Rows where scanner_status=allowed.", scanner_error),
        "current_candle": metric_for("Current-Candle Allowed", capture.get("scanner_current_allowed", UNKNOWN), logs_dir / "current_candle_capture.json", "Current-candle allowed count from current-candle capture.", capture_error),
        "earlier_today": metric_for("Earlier-Today Allowed", capture.get("scanner_earlier_today_allowed", UNKNOWN), logs_dir / "current_candle_capture.json", "Earlier-today allowed count from current-candle capture.", capture_error),
        "size_ok": metric_for("Size OK", sizing_count("size_ok"), logs_dir / "position_sizing.csv", "Rows where sizing_status=size_ok.", sizing_error),
        "paper_gate_ready_final_snapshot": metric_for("Paper Gate Ready Final Snapshot", paper_ready(), logs_dir / "paper_gate_v2.csv", "Final snapshot count ready for official validation sample.", paper_error),
        "contract_gate_pass": metric_for("Contract Gate Pass", capture.get("contract_gate_passed", UNKNOWN), logs_dir / "current_candle_capture.json", "Contract-passed count from session current-candle capture.", capture_error),
        "validation_preview_import_signal": metric_for("Validation Preview/Import Signal", capture.get("validation_import_new_rows", UNKNOWN), logs_dir / "current_candle_capture.json", "Validation import signal from session current-candle capture.", capture_error),
        "official_imports": metric_for("Official Imports", official_imports, data_dir / "paper_validation_samples.csv", "New official observations in authoritative validation ledger for the session."),
        "completed_official_trades": metric_for("Completed Official Trades", completed_today, data_dir / "paper_validation_samples.csv", "New completed official observations in authoritative validation ledger for the session."),
    }


def orb_reconciliation(logs_dir: Path, data_dir: Path, trading_day: date) -> dict[str, Any]:
    capture, capture_error = read_json(logs_dir / "current_candle_capture.json")
    gate, gate_error = read_json(logs_dir / "opening_range_breakout_paper_watch_gate.json")
    shadow_rows, _, shadow_error = read_csv_rows(data_dir / "opening_range_breakout_shadow_samples.csv")
    forward_rows, _, forward_error = read_csv_rows(data_dir / "opening_range_breakout_forward_observations.csv")
    source_capture = logs_dir / "current_candle_capture.json"

    def capture_or_count(key: str, rows: list[dict[str, str]], error: str) -> object:
        if key in capture:
            return capture.get(key)
        if error:
            return UNKNOWN
        return len(rows)

    accumulated = {
        "shadow_samples": metric(
            "ORB Accumulated Shadow Samples",
            capture_or_count("orb_shadow_samples", shadow_rows, shadow_error),
            owner="ORB/Reconciliation",
            source=str(source_capture if "orb_shadow_samples" in capture else data_dir / "opening_range_breakout_shadow_samples.csv"),
            definition="Accumulated broad ORB shadow observations; separate from paper-watch readiness.",
            session_scope="all-time",
            status="UNKNOWN" if capture_error and shadow_error else "OK",
            reason=capture_error or shadow_error,
        ),
        "forward_observations": metric(
            "ORB Accumulated Forward Observations",
            capture_or_count("orb_forward_observations", forward_rows, forward_error),
            owner="ORB/Reconciliation",
            source=str(source_capture if "orb_forward_observations" in capture else data_dir / "opening_range_breakout_forward_observations.csv"),
            definition="Accumulated broad ORB forward observations; separate from paper-watch readiness.",
            session_scope="all-time",
            status="UNKNOWN" if capture_error and forward_error else "OK",
            reason=capture_error or forward_error,
        ),
        "matured_shadow_outcomes": metric(
            "ORB Matured Shadow Outcomes",
            capture.get("orb_matured_shadow_outcomes", UNKNOWN),
            owner="ORB/Reconciliation",
            source=str(source_capture),
            definition="Matured broad ORB shadow outcomes from current-candle capture summary.",
            session_scope="all-time",
            status="UNKNOWN" if capture.get("orb_matured_shadow_outcomes", UNKNOWN) == UNKNOWN else "OK",
            reason=capture_error,
        ),
        "matured_forward_outcomes": metric(
            "ORB Matured Forward Outcomes",
            capture.get("orb_matured_forward_outcomes", UNKNOWN),
            owner="ORB/Reconciliation",
            source=str(source_capture),
            definition="Matured broad ORB forward outcomes from current-candle capture summary.",
            session_scope="all-time",
            status="UNKNOWN" if capture.get("orb_matured_forward_outcomes", UNKNOWN) == UNKNOWN else "OK",
            reason=capture_error,
        ),
    }
    return {
        "accumulated_evidence": accumulated,
        "paper_watch_readiness": {
            "decision": gate.get("decision", UNKNOWN),
            "next_blocker": gate.get("next_blocker", UNKNOWN),
            "blocked_count": gate.get("blocked_count", UNKNOWN),
            "checks": gate.get("checks", []) if isinstance(gate.get("checks", []), list) else [],
            "source": str(logs_dir / "opening_range_breakout_paper_watch_gate.json"),
            "status": "UNKNOWN" if gate_error else "OK",
            "reason": gate_error,
            "definition": "Paper-watch readiness checks; not accumulated ORB evidence.",
        },
    }


def production_reconciliation(logs_dir: Path) -> dict[str, Any]:
    heartbeat, hb_error = read_json(logs_dir / "production_heartbeat.json")
    capture, cap_error = read_json(logs_dir / "current_candle_capture.json")
    status = heartbeat.get("status", UNKNOWN)
    timing = (capture.get("timing") or {}) if isinstance(capture.get("timing"), dict) else {}
    return {
        "status": status,
        "source": str(logs_dir / "production_heartbeat.json"),
        "reason": heartbeat.get("reason", hb_error),
        "evidence": "CLEAN" if status == "GREEN" and heartbeat.get("experiment_valid_today", False) else "PARTIAL",
        "critical_path": {
            "entry_critical_path_seconds": timing.get("entry_critical_path_seconds", UNKNOWN),
            "entry_budget_seconds": timing.get("entry_budget_seconds", UNKNOWN),
            "entry_timing_margin_seconds": timing.get("entry_timing_margin_seconds", UNKNOWN),
            "entry_timing_status": timing.get("entry_timing_status", UNKNOWN),
            "source": str(logs_dir / "current_candle_capture.json"),
            "reason": cap_error,
        },
    }


def reporting_status_from_sections(*sections: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    for section in sections:
        text = json.dumps(section, default=str)
        if '"status": "UNKNOWN"' in text or f'"value": "{UNKNOWN}"' in text:
            reasons.append("One or more canonical metrics are UNKNOWN.")
            break
    return ("WATCH", reasons) if reasons else ("GREEN", [])


def metric_contracts() -> list[dict[str, str]]:
    return [
        {
            "metric": "Completed Official Strategy Observations",
            "owner": "Validation/Reconciliation",
            "authoritative_source": "paper_validation_samples.csv",
            "definition": "sample_status=completed OR outcome_r numeric; counts_toward_30; not invalid_for_validation",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "session_scope": "all-time",
            "freshness_requirement": "latest durable validation ledger",
            "unavailable_behavior": "UNKNOWN, never false zero",
        },
        {
            "metric": "New Completed Official Observations Today",
            "owner": "Validation/Reconciliation",
            "authoritative_source": "paper_validation_samples.csv",
            "definition": "Completed Official Strategy Observations where sample_date=session date",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "session_scope": "trading-date",
            "freshness_requirement": "latest durable validation ledger",
            "unavailable_behavior": "UNKNOWN, never false zero",
        },
        {
            "metric": "Candidate Funnel",
            "owner": "Session Reconciliation",
            "authoritative_source": "scanner, current-candle capture, sizing, paper gate, validation ledger",
            "definition": "Session-scoped funnel using stage-owner artifacts; missing source returns UNKNOWN",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "session_scope": "trading-date",
            "freshness_requirement": "artifact must correspond to reconciled session",
            "unavailable_behavior": "UNKNOWN with source/reason",
        },
        {
            "metric": "ORB Accumulated Evidence",
            "owner": "ORB/Reconciliation",
            "authoritative_source": "current-candle capture summary and ORB shadow/forward ledgers",
            "definition": "Accumulated ORB evidence, separate from paper-watch readiness",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "session_scope": "all-time",
            "freshness_requirement": "latest durable ORB evidence artifacts",
            "unavailable_behavior": "UNKNOWN with source/reason",
        },
        {
            "metric": "Independent Market Opportunities",
            "owner": "Governance/Reconciliation",
            "authoritative_source": "governance baseline plus derived post-baseline ledger groups",
            "definition": "Derived/effective count; not a persisted authoritative ledger field yet",
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "session_scope": "all-time",
            "freshness_requirement": "governance baseline and validation ledger",
            "unavailable_behavior": "UNKNOWN with provenance",
        },
    ]


def build_canonical_session_state(logs_dir: Path, data_dir: Path, trading_day: date) -> dict[str, Any]:
    validation = validation_reconciliation(data_dir, trading_day)
    independent = derived_independent_opportunities(validation, trading_day)
    funnel = candidate_funnel(logs_dir, data_dir, trading_day, validation)
    orb = orb_reconciliation(logs_dir, data_dir, trading_day)
    production = production_reconciliation(logs_dir)
    freeze = load_cohort_1_freeze(logs_dir)
    reporting_status, reporting_reasons = reporting_status_from_sections(validation, funnel, orb)
    completed = validation["metrics"]["valid_completed_observations"]["value"]
    checkpoint_reached = completed != UNKNOWN and int(completed) >= CHECKPOINT_TARGET
    cohort_frozen = freeze.get("status") == "FROZEN"
    return {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "trading_date": trading_day.isoformat(),
        "phase_state": {
            "phase_2": "COMPLETE" if cohort_frozen else ("CHECKPOINT REACHED / FREEZE PENDING" if checkpoint_reached else "ACTIVE"),
            "phase_2_reason": freeze.get("phase_2", {}).get("reason", "") if cohort_frozen else "",
            "phase_3": "PREPARED - NOT ACTIVE",
            "broker_real_money": "DISABLED",
            "cohort_1_frozen": cohort_frozen,
        },
        "cohort_1": {
            "status": "FROZEN" if cohort_frozen else "NOT FROZEN",
            "cohort_version": freeze.get("cohort_version", COHORT_VERSION),
            "snapshot_path": str(logs_dir / "cohorts" / COHORT_VERSION / "cohort_1_snapshot.json"),
            "observations": freeze.get("strategy_observations", completed if completed != UNKNOWN else UNKNOWN),
            "independent_opportunities": freeze.get("independent_opportunities", {}).get("value", independent.get("value")),
            "provenance": freeze.get("independent_opportunities", {}).get("provenance", independent.get("provenance")),
            "freeze_timestamp": freeze.get("freeze_timestamp", ""),
            "guardrail": "Cohort 1 membership is closed once frozen; future observations require new cohort/experiment identities.",
        },
        "production": production,
        "reporting": {"status": reporting_status, "reasons": reporting_reasons},
        "validation": validation,
        "independent_opportunities": independent,
        "candidate_funnel": funnel,
        "orb": orb,
        "metric_contracts": metric_contracts(),
        "guardrail": "Canonical reconciliation is read/report-only and does not mutate trading, evidence, broker, or phase state.",
    }


def canonical_session_state_path(logs_dir: Path, trading_day: date) -> Path:
    return logs_dir / "canonical_session_state" / f"{trading_day.isoformat()}.json"


def write_canonical_session_state(state: dict[str, Any], logs_dir: Path, trading_day: date) -> Path:
    path = canonical_session_state_path(logs_dir, trading_day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, allow_nan=False), encoding="utf-8")
    latest = logs_dir / "canonical_session_state.json"
    latest.write_text(json.dumps(state, indent=2, allow_nan=False), encoding="utf-8")
    return path


def load_or_build_canonical_session_state(logs_dir: Path, data_dir: Path, trading_day: date) -> dict[str, Any]:
    path = canonical_session_state_path(logs_dir, trading_day)
    payload, error = read_json(path)
    if payload and payload.get("schema_version") == CANONICAL_SCHEMA_VERSION:
        freeze = load_cohort_1_freeze(logs_dir)
        if freeze.get("status") == "FROZEN" and not payload.get("phase_state", {}).get("cohort_1_frozen"):
            return build_canonical_session_state(logs_dir, data_dir, trading_day)
        return payload
    return build_canonical_session_state(logs_dir, data_dir, trading_day)


def audit_report_consistency(
    canonical: dict[str, Any],
    *,
    eod_payload: dict[str, Any] | None = None,
    command_center_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    canonical_completed = canonical["validation"]["metrics"]["valid_completed_observations"]["value"]
    canonical_today = canonical["validation"]["metrics"]["new_completed_observations_today"]["value"]
    canonical_checkpoint = canonical["validation"]["metrics"]["checkpoint"]["value"]

    def add(surface: str, metric_name: str, surface_value: object, canonical_value: object) -> None:
        status = "PASS" if str(surface_value) == str(canonical_value) else "FAIL"
        checks.append(
            {
                "surface": surface,
                "metric": metric_name,
                "canonical_value": canonical_value,
                "surface_value": surface_value,
                "status": status,
            }
        )

    if eod_payload:
        validation = eod_payload.get("validation_summary", {})
        add("EOD Executive Report", "Completed Official Strategy Observations", validation.get("completed_official_observations"), canonical_completed)
        add("EOD Executive Report", "New Completed Official Observations Today", validation.get("new_completed_observations_today"), canonical_today)
        add("EOD Executive Report", "Phase 2 Checkpoint", validation.get("checkpoint"), canonical_checkpoint)
    if command_center_payload:
        validation = command_center_payload.get("validation", {})
        add("Command Center", "Completed Official Strategy Observations", validation.get("completed_trades"), canonical_completed)
        add("Command Center", "Phase 2 Checkpoint", f"{validation.get('completed_trades')} / 30", canonical_checkpoint)
    failures = [check for check in checks if check["status"] != "PASS"]
    return {
        "status": "FAIL" if failures else "PASS",
        "checks": checks,
        "failures": failures,
        "guardrail": "Consistency audit is read-only. It does not modify production evidence or reports.",
    }
