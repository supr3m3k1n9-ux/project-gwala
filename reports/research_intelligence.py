"""Canonical read-only Strategy Intelligence summary for Command Center.

This module turns existing research artifacts into one display payload. It does
not create research decisions, recalculate strategy truth in the browser, fetch
market data, or mutate production evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
STRATEGY_INTELLIGENCE_DIR = PROJECT_DIR / "data" / "strategy_intelligence"
PHASE3_EXPERIMENTS_DIR = PROJECT_DIR / "logs" / "phase_3" / "experiments"
LOGS_DIR = PROJECT_DIR / "logs"

UNKNOWN = "UNKNOWN"
NA = "N/A"

STATUS_TAXONOMY = [
    {"status": "SOURCED", "meaning": "Known strategy/effect; not yet formalized for Gwala testing."},
    {"status": "FORMALIZATION REQUIRED", "meaning": "Needs exact no-lookahead mechanics before any screen."},
    {"status": "PRE-REGISTERED", "meaning": "Frozen hypothesis definition exists; no P&L inspected yet."},
    {"status": "READY FOR SCREEN", "meaning": "Eligible for historical quick screen under current data contract."},
    {"status": "SCREENING", "meaning": "Historical screen authorized or in progress."},
    {"status": "INVESTIGATE", "meaning": "Potential signal, but one bounded diagnostic question remains."},
    {"status": "ADVANCE", "meaning": "Passed quick-screen gates; eligible for next governed evidence stage."},
    {"status": "WAITING FOR FORWARD EVIDENCE", "meaning": "Historical/research state is waiting on fresh forward observations."},
    {"status": "RESEARCH HOLD", "meaning": "Known idea parked until a higher-priority blocker clears."},
    {"status": "SHELVED", "meaning": "Failed current evidence gates; not a validated edge."},
    {"status": "FORWARD CANDIDATE", "meaning": "Paper/forward collection candidate; not validated."},
    {"status": "VALIDATED EDGE", "meaning": "Passed governed validation. No current record has this status unless explicit."},
    {"status": "DATA INSUFFICIENT", "meaning": "Not enough governed observations to decide."},
    {"status": "DEFINITION INCOMPLETE", "meaning": "Cannot test without inventing missing mechanics."},
]

EVIDENCE_TYPE_TAXONOMY = [
    {"type": "HISTORICAL DISCOVERY", "meaning": "Offline historical quick screen; hypothesis-generating unless later validated."},
    {"type": "SEEN / HYPOTHESIS-GENERATING", "meaning": "Catalog or observation only; not tradable evidence by itself."},
    {"type": "HISTORICAL FALSIFICATION", "meaning": "Stress/falsification evidence used to reject or challenge a hypothesis."},
    {"type": "FORWARD WEBULL", "meaning": "Fresh Webull-forward observations; separate from historical discovery."},
    {"type": "PAPER", "meaning": "Official or local paper trade outcomes; not live capital."},
    {"type": "TINY LIVE", "meaning": "Explicitly approved tiny-live evidence only."},
    {"type": "LIVE", "meaning": "Explicitly approved live-capital evidence only."},
]


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_json(root: Path, filename: str) -> tuple[Path | None, dict[str, Any]]:
    if not root.exists():
        return None, {}
    matches = sorted(root.glob(f"**/{filename}"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        return None, {}
    return matches[0], _safe_json(matches[0])


def _value(value: Any, default: str = UNKNOWN) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else default
    return value


def _metric(metrics: dict[str, Any], key: str) -> Any:
    value = metrics.get(key)
    return value if value is not None else NA


def _display_status(raw: Any) -> str:
    text = str(_value(raw)).replace("_", " ").replace("-", " ").upper()
    aliases = {
        "CATALOGED": "SOURCED",
        "NOT SCREENED": "SOURCED",
        "SHELVE": "SHELVED",
        "RESEARCH HOLD": "RESEARCH HOLD",
        "RESEARCH_HOLD": "RESEARCH HOLD",
        "DATA_INSUFFICIENT": "DATA INSUFFICIENT",
        "DEFINITION_INCOMPLETE": "DEFINITION INCOMPLETE",
        "FORMALIZATION INCOMPLETE": "FORMALIZATION REQUIRED",
        "REJECTED BEFORE TEST": "DEFINITION INCOMPLETE",
        "WAIT FOR FORWARD EVIDENCE": "WAITING FOR FORWARD EVIDENCE",
        "ACTIVE PAPER WATCH": "FORWARD CANDIDATE",
        "RESEARCH BACKLOG": "RESEARCH HOLD",
        "NOT VALIDATED EDGE": "SOURCED",
    }
    return aliases.get(text, text)


def _evidence_grade_meaning(grade: Any) -> str:
    grade_text = str(_value(grade)).upper()
    meanings = {
        "A": "External/academic or strongly established market effect, still requiring Gwala validation.",
        "B": "Plausible external or internal evidence; useful for queueing, not validation by itself.",
        "C": "Weak, anecdotal, or underspecified evidence.",
    }
    return meanings.get(grade_text, "Evidence grade unavailable.")


def _source_type(record: dict[str, Any]) -> str:
    if record.get("source_class"):
        return str(record["source_class"])
    refs = record.get("source_references") or []
    if refs and isinstance(refs[0], dict):
        return str(refs[0].get("source_type") or UNKNOWN)
    return UNKNOWN


def _provenance(record: dict[str, Any]) -> list[dict[str, str]]:
    refs = record.get("source_references") or []
    out = []
    for ref in refs[:4]:
        if not isinstance(ref, dict):
            continue
        out.append(
            {
                "title": str(_value(ref.get("source_title"), UNKNOWN)),
                "type": str(_value(ref.get("source_type"), UNKNOWN)),
                "reference": str(_value(ref.get("publication_or_reference"), UNKNOWN)),
                "claim": str(_value(ref.get("source_claim"), UNKNOWN)),
            }
        )
    return out


def _status_from_record(record: dict[str, Any], batch_update: dict[str, Any] | None) -> str:
    if batch_update:
        return _display_status(batch_update.get("new_research_status"))
    if str(record.get("validated_status", "")).lower() == "validated_edge":
        return "VALIDATED EDGE"
    if record.get("research_status"):
        return _display_status(record["research_status"])
    if record.get("pre_registration_status") == "PRE_REGISTERED":
        return "READY FOR SCREEN"
    if record.get("formalization_status") not in {"formalized", "existing_governed_definition"}:
        return "FORMALIZATION REQUIRED"
    return "SOURCED"


def _next_action(record: dict[str, Any], status: str) -> str:
    if record.get("next_action"):
        return str(record["next_action"])
    if record.get("notes"):
        return str(record["notes"])
    defaults = {
        "SOURCED": "Formalize only if prioritized by Investment Committee.",
        "FORMALIZATION REQUIRED": "Define no-lookahead mechanics before testing.",
        "READY FOR SCREEN": "Await explicit quick-screen authorization.",
        "SHELVED": "No action unless Investment Committee reopens with a new non-optimizing question.",
        "DEFINITION INCOMPLETE": "Return to formalization before any P&L screen.",
        "WAITING FOR FORWARD EVIDENCE": "Collect governed forward/paper evidence only.",
        "FORWARD CANDIDATE": "Continue the authorized paper/forward evidence lane.",
        "RESEARCH HOLD": "Hold until higher-priority work clears.",
    }
    return defaults.get(status, "Await next governed Investment Committee decision.")


def _forward_evidence(record: dict[str, Any], canonical: dict[str, Any]) -> dict[str, Any]:
    strategy_id = record.get("strategy_intelligence_id")
    if strategy_id == "gwala_morning_index_orb_long":
        capture = _safe_json(LOGS_DIR / "current_candle_capture.json")
        return {
            "evidence_type": "FORWARD WEBULL",
            "observations": _value(capture.get("morning_index_orb_candidates_detected_today"), NA),
            "independent_opportunities": NA,
            "completed_outcomes": _value(capture.get("morning_index_orb_completed_count"), 0),
            "forward_r": NA,
            "detail": _value(capture.get("morning_index_orb_guardrail"), "Manual paper-watch lane; no broker orders."),
        }
    if strategy_id == "gwala_vwap_ema_trend_continuation":
        validation = canonical.get("validation", {}).get("metrics", {})
        completed = validation.get("completed_official_trades", {}).get("value")
        return {
            "evidence_type": "PAPER",
            "observations": _value(completed, NA),
            "independent_opportunities": NA,
            "completed_outcomes": _value(completed, NA),
            "forward_r": NA,
            "detail": "Official paper validation remains the primary KPI.",
        }
    return {
        "evidence_type": "SEEN / HYPOTHESIS-GENERATING",
        "observations": NA,
        "independent_opportunities": NA,
        "completed_outcomes": NA,
        "forward_r": NA,
        "detail": "No governed forward evidence artifact linked.",
    }


def build_research_intelligence_summary(
    root: Path | None = None,
    canonical_session_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return canonical Command Center Strategy Index data."""

    project_root = root or PROJECT_DIR
    data_dir = project_root / "data" / "strategy_intelligence"
    logs_dir = project_root / "logs"
    registry = _safe_json(data_dir / "registry.json")
    queue = _safe_json(data_dir / "research_queue.json")
    coverage = _safe_json(data_dir / "coverage_report.json")
    batch_path, latest_batch = _latest_json(logs_dir / "phase_3" / "experiments" / "external_batch_001", "external_batch_001_historical_screen.json")
    canonical = canonical_session_state or _safe_json(logs_dir / "canonical_session_state.json")

    batch_packets = {
        packet.get("strategy_intelligence_id"): packet
        for packet in latest_batch.get("candidate_packets", [])
        if isinstance(packet, dict)
    }
    batch_updates = {
        update.get("strategy_intelligence_id"): update
        for update in latest_batch.get("strategy_intelligence_updates", [])
        if isinstance(update, dict)
    }
    queue_by_id = {
        item.get("strategy_intelligence_id"): item
        for item in queue.get("queue", [])
        if isinstance(item, dict)
    }

    strategies = []
    for record in registry.get("records", []):
        if not isinstance(record, dict):
            continue
        strategy_id = str(_value(record.get("strategy_intelligence_id")))
        packet = batch_packets.get(strategy_id, {})
        update = batch_updates.get(strategy_id)
        metrics = packet.get("metrics", {}) if isinstance(packet.get("metrics"), dict) else {}
        recent = packet.get("recent_12_month", {}) if isinstance(packet.get("recent_12_month"), dict) else {}
        status = _status_from_record(record, update)
        forward = _forward_evidence(record, canonical)
        evidence_type = "HISTORICAL DISCOVERY" if packet else forward["evidence_type"]
        historical_detail = (
            f"{packet.get('canonical_name')} quick-screen result from {packet.get('discovery_snapshot_id')}."
            if packet
            else "No linked historical quick-screen metrics."
        )
        strategies.append(
            {
                "display_name": str(_value(record.get("canonical_name"))),
                "strategy_intelligence_id": strategy_id,
                "research_hypothesis_id": str(_value(packet.get("hypothesis_id") or record.get("research_hypothesis_id"), NA)),
                "family": str(_value(record.get("family"), "Unclassified")),
                "subfamily": str(_value(record.get("subfamily"), "Unclassified")),
                "source_type": _source_type(record),
                "source_class": str(_value(record.get("source_class"), UNKNOWN)),
                "evidence_grade": str(_value(record.get("evidence_grade"), UNKNOWN)),
                "evidence_grade_meaning": _evidence_grade_meaning(record.get("evidence_grade")),
                "current_status": status,
                "data_compatibility": str(_value(record.get("current_data_compatible") or record.get("data_compatibility_notes"))),
                "historical": {
                    "evidence_type": "HISTORICAL DISCOVERY" if packet else "SEEN / HYPOTHESIS-GENERATING",
                    "observations": _metric(metrics, "observations"),
                    "dependence_aware_n": _metric(metrics, "independent_opportunities"),
                    "expectancy_r": _metric(metrics, "expectancy_r"),
                    "profit_factor": _metric(metrics, "profit_factor"),
                    "max_drawdown_r": _metric(metrics, "max_drawdown_r"),
                    "recent_expectancy_r": _metric(recent, "expectancy_r"),
                    "detail": historical_detail,
                },
                "forward": forward,
                "validated_status": str(_value((update or {}).get("validated_status") or record.get("validated_status"))),
                "next_action": _next_action(record, status),
                "priority": _value(queue_by_id.get(strategy_id, {}).get("research_priority") or record.get("research_priority"), UNKNOWN),
                "priority_score": _value(queue_by_id.get(strategy_id, {}).get("research_priority_score") or record.get("research_priority_score"), NA),
                "is_external": str(record.get("source_class", "")).startswith("external"),
                "is_internal": not str(record.get("source_class", "")).startswith("external"),
                "requires": {
                    "level2": bool(record.get("requires_level2")),
                    "quotes": bool(record.get("requires_quotes")),
                    "ticks": bool(record.get("requires_ticks")),
                    "options": bool(record.get("requires_options_data")),
                    "volume": bool(record.get("requires_volume")),
                    "market_regime": bool(record.get("requires_market_regime")),
                },
                "detail": {
                    "what_it_is": str(_value(record.get("description") or record.get("original_definition_summary"))),
                    "how_it_works": str(_value(record.get("original_definition_summary") or record.get("description"))),
                    "why_it_might_work": str(_value(record.get("behavioral_thesis") or record.get("evidence_summary"))),
                    "source_provenance": _provenance(record),
                    "evidence_quality": f"{_value(record.get('evidence_grade'))}: {_evidence_grade_meaning(record.get('evidence_grade'))}",
                    "gwala_evidence": historical_detail,
                    "forward_evidence": forward["detail"],
                    "risk_weaknesses": str(
                        _value(
                            packet.get("cost_plausibility")
                            or packet.get("extra", {}).get("reason")
                            or record.get("rejection_reason")
                            or "No dedicated weakness artifact linked.",
                            "No dedicated weakness artifact linked.",
                        )
                    ),
                    "current_decision": status,
                    "decision_reason": str(
                        _value(
                            packet.get("verdict")
                            or record.get("research_status")
                            or record.get("historical_screen_status"),
                            "No current decision artifact linked.",
                        )
                    ),
                    "next_step": _next_action(record, status),
                },
                "linked_artifacts": {
                    "registry": str(data_dir / "registry.json"),
                    "research_queue": str(data_dir / "research_queue.json") if queue else "",
                    "coverage_report": str(data_dir / "coverage_report.json") if coverage else "",
                    "latest_external_batch": str(batch_path) if batch_path else "",
                },
                "evidence_type": evidence_type,
            }
        )

    statuses: dict[str, int] = {}
    families: dict[str, int] = {}
    for strategy in strategies:
        statuses[strategy["current_status"]] = statuses.get(strategy["current_status"], 0) + 1
        families[strategy["family"]] = families.get(strategy["family"], 0) + 1

    return {
        "schema_version": "research-intelligence-command-center-summary-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "registry": str(data_dir / "registry.json"),
            "research_queue": str(data_dir / "research_queue.json"),
            "coverage_report": str(data_dir / "coverage_report.json"),
            "latest_external_batch": str(batch_path) if batch_path else "",
            "canonical_session_state": str(logs_dir / "canonical_session_state.json"),
        },
        "source_availability": {
            "registry": bool(registry),
            "research_queue": bool(queue),
            "coverage_report": bool(coverage),
            "latest_external_batch": bool(latest_batch),
            "canonical_session_state": bool(canonical),
        },
        "counts": {
            "strategies_known": len(strategies),
            "externally_sourced": sum(1 for strategy in strategies if strategy["is_external"]),
            "internal_original": sum(1 for strategy in strategies if strategy["is_internal"]),
            "high_priority": len(queue.get("queue", [])),
            "high_priority_known": sum(1 for strategy in strategies if str(strategy.get("priority")).upper() == "HIGH"),
            "ready_for_screen": coverage.get("ready_for_screen", UNKNOWN),
            "waiting_for_forward": coverage.get("waiting_for_forward", UNKNOWN),
            "validated": coverage.get("validated", UNKNOWN),
        },
        "status_counts": dict(sorted(statuses.items())),
        "family_counts": dict(sorted(families.items())),
        "status_taxonomy": STATUS_TAXONOMY,
        "evidence_type_taxonomy": EVIDENCE_TYPE_TAXONOMY,
        "filter_groups": {
            "status": ["ALL", "ACTIVE RESEARCH", "FORWARD EVIDENCE", "PRE-REGISTERED", "RESEARCH HOLD", "SHELVED", "VALIDATED", "EXTERNAL INTAKE", "INTERNAL / ORIGINAL"],
            "family": ["ALL", *sorted(families)],
        },
        "strategies": sorted(strategies, key=lambda row: (row["current_status"], row["family"], row["display_name"])),
        "guardrail": "Display-only research intelligence. Historical, forward, paper, tiny-live, and live evidence labels are not interchangeable.",
    }
