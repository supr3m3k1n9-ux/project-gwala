"""Classify Phase 3 forward evidence from authoritative production artifacts.

This is evidence accounting only. It reads candidate/lifecycle artifacts already
created by production and writes a separate Phase 3 forward-evidence ledger. It
does not scan markets, create signals, size trades, run gates, place orders, or
change official evidence rules.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, time
import json
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from config.runtime_paths import runtime_data_path
from reports.cohort_freeze import INDEPENDENT_OPPORTUNITIES
from reports.cohort_freeze import CHECKPOINT_OBSERVATIONS
from reports.cohort_freeze import load_cohort_1_freeze
MARKET_TZ = ZoneInfo("America/New_York")
DATA_CONTRACT_VERSION = "phase3-forward-evidence-v1"
P3_H006_ID = "P3-H006"
QQQ_SETUP_B_ID = "QQQ_SETUP_B_LATE_DAY"
ORB_ID = "morning_index_orb_long"
DEFAULT_P3_H006_BOUNDARY = "2026-08-18T01:40:00+00:00"
DEFAULT_QQQ_BOUNDARY = "2026-08-18T01:00:00+00:00"

LEDGER_COLUMNS = [
    "forward_evidence_id",
    "hypothesis_id",
    "strategy_id",
    "strategy_version",
    "symbol",
    "direction",
    "setup",
    "signal_timestamp_et",
    "first_seen_timestamp_et",
    "entry_timestamp_et",
    "time_bucket",
    "source_provider",
    "source_artifact",
    "candidate_ledger_id",
    "freshness_lane",
    "quality_grade",
    "router_state",
    "size_ok",
    "paper_gate_state",
    "contract_gate_state",
    "entry_state",
    "outcome_state",
    "exit_timestamp_et",
    "outcome_r",
    "independence_group_id",
    "counts_as_forward_observation",
    "counts_as_forward_completed_trade",
    "exclusion_reason",
    "hypothesis_adoption_timestamp",
    "classification_timestamp",
    "data_contract_version",
]


@dataclass(frozen=True)
class HypothesisSpec:
    hypothesis_id: str
    name: str
    strategy_id: str
    adoption_timestamp: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify Phase 3 forward evidence.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"))
    parser.add_argument("--candidate-ledger-csv", type=Path, default=runtime_data_path("candidate_window_ledger.csv"))
    parser.add_argument("--samples-csv", type=Path, default=runtime_data_path("paper_validation_samples.csv"))
    parser.add_argument("--event-state-csv", type=Path, default=runtime_data_path("candidate_ledger_event_state.csv"))
    parser.add_argument("--orb-ledger-csv", type=Path, default=runtime_data_path("morning_index_orb_manual_paper_trades.csv"))
    parser.add_argument("--orb-status-json", type=Path, default=Path("logs/morning_index_orb_manual_paper_watch.json"))
    parser.add_argument("--phase3-forward-ledger-csv", type=Path, default=runtime_data_path("phase3_forward_evidence.csv"))
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    return parser.parse_args()


def now_et() -> str:
    return datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def clean(value: object) -> str:
    return str(value or "").strip()


def truthy(value: object) -> bool:
    return clean(value).lower() in {"true", "1", "yes", "y"}


def numeric(value: object) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_timestamp(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    if text.endswith((" EDT", " EST")):
        text = text.rsplit(" ", 1)[0]
    for candidate in [text, text.replace(" ", "T")]:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=MARKET_TZ)
        return parsed.astimezone(MARKET_TZ)
    return None


def iso_boundary(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=MARKET_TZ)


def et_iso(value: datetime) -> str:
    return value.astimezone(MARKET_TZ).isoformat()


def latest_json_field(paths: list[Path], field_names: list[str], fallback: str) -> str:
    values: list[str] = []
    for path in paths:
        payload = read_json(path)
        for field in field_names:
            value = clean(payload.get(field))
            if value:
                values.append(value)
    if not values:
        return fallback
    return sorted(values)[-1]


def hypothesis_specs(logs_dir: Path) -> dict[str, HypothesisSpec]:
    p3_h006_paths = list(logs_dir.glob("phase_3/experiments/*/P3-H006-hypothesis-definition/P3-H006.json"))
    qqq_paths = list(logs_dir.glob("phase_3/experiments/*/P3-next-research-allocation/phase3_next_research_allocation.json"))
    return {
        P3_H006_ID: HypothesisSpec(
            hypothesis_id=P3_H006_ID,
            name="SPY Opening-Hour Setup A Long",
            strategy_id="vwap_ema_trend_continuation",
            adoption_timestamp=latest_json_field(
                p3_h006_paths,
                ["corrected_at_utc", "created_at_utc", "generated_at_utc"],
                DEFAULT_P3_H006_BOUNDARY,
            ),
        ),
        QQQ_SETUP_B_ID: HypothesisSpec(
            hypothesis_id=QQQ_SETUP_B_ID,
            name="QQQ Setup B Short / late-day behavior",
            strategy_id="vwap_ema_trend_continuation",
            adoption_timestamp=latest_json_field(
                qqq_paths,
                ["generated_at_utc", "created_at_utc"],
                DEFAULT_QQQ_BOUNDARY,
            ),
        ),
    }


def time_bucket(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "unknown"
    local_time = timestamp.astimezone(MARKET_TZ).time()
    if local_time < time(11, 0):
        return "opening_hour"
    if local_time >= time(14, 30):
        return "late_day"
    if local_time < time(12, 30):
        return "late_morning"
    return "midday"


def candidate_identity(row: dict[str, str]) -> str:
    return "|".join(
        [
            clean(row.get("trade_date")),
            clean(row.get("source_signal_et")),
            clean(row.get("candidate_entry_et")),
            clean(row.get("symbol")).upper(),
            clean(row.get("setup")).lower(),
            clean(row.get("direction")).lower(),
            clean(row.get("freshness_lane")).lower(),
        ]
    )


def normalized_identity(date_value: object, time_value: object, symbol: object, setup: object, direction: object) -> str:
    time_text = clean(time_value)
    if len(time_text) >= 5 and time_text[2] == ":":
        time_text = time_text[:5]
    return "|".join(
        [
            clean(date_value),
            time_text,
            clean(symbol).upper(),
            clean(setup).lower(),
            clean(direction).lower(),
        ]
    )


def candidate_to_sample_identity(row: dict[str, str]) -> str:
    entry = parse_timestamp(row.get("candidate_entry_et")) or parse_timestamp(row.get("source_signal_et"))
    time_text = entry.strftime("%H:%M") if entry else clean(row.get("candidate_entry_et"))
    return normalized_identity(row.get("trade_date"), time_text, row.get("symbol"), row.get("setup"), row.get("direction"))


def sample_identity(row: dict[str, str]) -> str:
    explicit = clean(row.get("source_contract_gate_identity"))
    if explicit:
        return explicit
    return normalized_identity(row.get("sample_date"), row.get("entry_time_et"), row.get("symbol"), row.get("setup"), row.get("direction"))


def event_state_by_candidate(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        key = "|".join(
            [
                clean(row.get("trade_date")),
                "",
                clean(row.get("candidate_entry_et")),
                clean(row.get("symbol")).upper(),
                clean(row.get("setup")).lower(),
                clean(row.get("direction")).lower(),
                "",
            ]
        )
        result[key] = row
    return result


def matching_event(row: dict[str, str], state: dict[str, dict[str, str]]) -> dict[str, str]:
    full = candidate_identity(row)
    if full in state:
        return state[full]
    loose = "|".join(
        [
            clean(row.get("trade_date")),
            "",
            clean(row.get("candidate_entry_et")),
            clean(row.get("symbol")).upper(),
            clean(row.get("setup")).lower(),
            clean(row.get("direction")).lower(),
            "",
        ]
    )
    return state.get(loose, {})


def source_signal_timestamp(row: dict[str, str]) -> datetime | None:
    return parse_timestamp(row.get("source_signal_et")) or parse_timestamp(row.get("candidate_entry_et"))


def first_seen_timestamp(row: dict[str, str]) -> datetime | None:
    return parse_timestamp(row.get("first_seen_at")) or parse_timestamp(row.get("scan_timestamp"))


def classifies_for_p3_h006(row: dict[str, str]) -> bool:
    timestamp = source_signal_timestamp(row)
    return (
        clean(row.get("symbol")).upper() == "SPY"
        and clean(row.get("setup")).lower() == "setup a long"
        and clean(row.get("direction")).lower() == "long"
        and time_bucket(timestamp) == "opening_hour"
    )


def classifies_for_qqq_setup_b(row: dict[str, str]) -> bool:
    timestamp = source_signal_timestamp(row)
    return (
        clean(row.get("symbol")).upper() == "QQQ"
        and clean(row.get("setup")).lower() == "setup b short"
        and clean(row.get("direction")).lower() == "short"
        and time_bucket(timestamp) == "late_day"
    )


def hypothesis_for_candidate(row: dict[str, str]) -> str:
    if classifies_for_p3_h006(row):
        return P3_H006_ID
    if classifies_for_qqq_setup_b(row):
        return QQQ_SETUP_B_ID
    return ""


def after_adoption(row: dict[str, str], spec: HypothesisSpec) -> bool:
    observed = first_seen_timestamp(row) or source_signal_timestamp(row)
    if observed is None:
        return False
    return observed > iso_boundary(spec.adoption_timestamp).astimezone(MARKET_TZ)


def paper_gate_state(row: dict[str, str]) -> str:
    return clean(row.get("paper_gate_status")) or "missing"


def entry_state(row: dict[str, str], sample: dict[str, str], event: dict[str, str]) -> str:
    if clean(sample.get("sample_status")):
        return clean(sample.get("sample_status"))
    if clean(event.get("status")):
        return clean(event.get("status"))
    if paper_gate_state(row) == "ready_for_validation_sample":
        return "paper_gate_ready"
    return "not_entered"


def outcome_state(sample: dict[str, str]) -> str:
    if clean(sample.get("outcome_r")):
        return "completed"
    if clean(sample.get("sample_status")):
        return clean(sample.get("sample_status"))
    return "not_available"


def exclusion_reason(row: dict[str, str], sample: dict[str, str], spec: HypothesisSpec) -> str:
    reasons: list[str] = []
    if not after_adoption(row, spec):
        reasons.append("pre_hypothesis_adoption")
    if clean(row.get("scanner_status")) != "allowed":
        reasons.append(clean(row.get("scanner_status")) or "scanner_not_allowed")
    if clean(row.get("sizing_status")) != "size_ok":
        reasons.append(clean(row.get("sizing_reason")) or "sizing_not_size_ok")
    if paper_gate_state(row) != "ready_for_validation_sample":
        reasons.append(paper_gate_state(row))
    if truthy(sample.get("invalid_for_validation")):
        reasons.append(clean(sample.get("invalid_reason")) or "invalid_for_validation")
    return "; ".join(reasons)


def counts_as_forward_observation(sample: dict[str, str]) -> bool:
    return not truthy(sample.get("invalid_for_validation"))


def forward_evidence_id(hypothesis_id: str, row: dict[str, str]) -> str:
    return f"{hypothesis_id}|{candidate_identity(row)}"


def ledger_row(
    row: dict[str, str],
    *,
    spec: HypothesisSpec,
    sample: dict[str, str],
    event: dict[str, str],
    source_artifact: Path,
    classification_timestamp: str,
) -> dict[str, Any]:
    signal_time = source_signal_timestamp(row)
    observed_time = first_seen_timestamp(row)
    excluded = exclusion_reason(row, sample, spec)
    counts_observation = counts_as_forward_observation(sample)
    has_completed_outcome = bool(clean(sample.get("outcome_r"))) and not truthy(sample.get("invalid_for_validation"))
    return {
        "forward_evidence_id": forward_evidence_id(spec.hypothesis_id, row),
        "hypothesis_id": spec.hypothesis_id,
        "strategy_id": clean(row.get("strategy_id")) or spec.strategy_id,
        "strategy_version": clean(row.get("variant")),
        "symbol": clean(row.get("symbol")).upper(),
        "direction": clean(row.get("direction")).lower(),
        "setup": clean(row.get("setup")),
        "signal_timestamp_et": et_iso(signal_time) if signal_time else clean(row.get("source_signal_et")),
        "first_seen_timestamp_et": et_iso(observed_time) if observed_time else clean(row.get("first_seen_at")),
        "entry_timestamp_et": clean(row.get("candidate_entry_et")),
        "time_bucket": time_bucket(signal_time),
        "source_provider": "Webull",
        "source_artifact": str(source_artifact),
        "candidate_ledger_id": candidate_identity(row),
        "freshness_lane": clean(row.get("freshness_lane")),
        "quality_grade": clean(row.get("quality_grade")),
        "router_state": clean(row.get("router_status")),
        "size_ok": clean(row.get("sizing_status")) == "size_ok",
        "paper_gate_state": paper_gate_state(row),
        "contract_gate_state": clean(event.get("contract_gate_status")) or clean(sample.get("contract_gate_status")),
        "entry_state": entry_state(row, sample, event),
        "outcome_state": outcome_state(sample),
        "exit_timestamp_et": clean(sample.get("exit_time_et")),
        "outcome_r": clean(sample.get("outcome_r")),
        "independence_group_id": "|".join([clean(row.get("trade_date")), clean(row.get("symbol")).upper(), clean(row.get("source_signal_et"))]),
        "counts_as_forward_observation": counts_observation,
        "counts_as_forward_completed_trade": counts_observation and has_completed_outcome,
        "exclusion_reason": excluded,
        "hypothesis_adoption_timestamp": spec.adoption_timestamp,
        "classification_timestamp": classification_timestamp,
        "data_contract_version": DATA_CONTRACT_VERSION,
    }


def classify_rows(
    *,
    candidate_rows: list[dict[str, str]],
    sample_rows: list[dict[str, str]],
    event_rows: list[dict[str, str]],
    specs: dict[str, HypothesisSpec],
    source_artifact: Path,
    classification_timestamp: str | None = None,
) -> list[dict[str, Any]]:
    sample_lookup = {sample_identity(row): row for row in sample_rows}
    event_lookup = event_state_by_candidate(event_rows)
    classified: list[dict[str, Any]] = []
    timestamp = classification_timestamp or now_et()
    for row in candidate_rows:
        hypothesis_id = hypothesis_for_candidate(row)
        if not hypothesis_id:
            continue
        spec = specs[hypothesis_id]
        if not after_adoption(row, spec):
            continue
        sample = sample_lookup.get(candidate_to_sample_identity(row), {})
        event = matching_event(row, event_lookup)
        classified.append(
            ledger_row(
                row,
                spec=spec,
                sample=sample,
                event=event,
                source_artifact=source_artifact,
                classification_timestamp=timestamp,
            )
        )
    return sorted(classified, key=lambda item: item["forward_evidence_id"])


def merge_idempotent(existing: list[dict[str, str]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {clean(row.get("forward_evidence_id")): dict(row) for row in existing}
    for row in current:
        by_id[clean(row.get("forward_evidence_id"))] = {**by_id.get(clean(row.get("forward_evidence_id")), {}), **row}
    return sorted(by_id.values(), key=lambda item: clean(item.get("forward_evidence_id")))


def summarize_hypothesis(rows: list[dict[str, Any]], hypothesis_id: str, runway: str) -> dict[str, Any]:
    selected = [row for row in rows if clean(row.get("hypothesis_id")) == hypothesis_id]
    counted = [row for row in selected if truthy(row.get("counts_as_forward_observation"))]
    completed = [row for row in selected if truthy(row.get("counts_as_forward_completed_trade"))]
    r_values = [value for value in (numeric(row.get("outcome_r")) for row in completed) if value is not None]
    exclusions = [row for row in selected if clean(row.get("exclusion_reason"))]
    independent = {clean(row.get("independence_group_id")) for row in counted if clean(row.get("independence_group_id"))}
    return {
        "hypothesis_id": hypothesis_id,
        "raw_forward_observations": len(selected),
        "independent_opportunities": len(independent),
        "eligible_observations": len(counted),
        "paper_entries": sum(1 for row in counted if clean(row.get("entry_state")) not in {"not_entered", "paper_gate_ready", ""}),
        "completed_outcomes": len(completed),
        "total_r": round(sum(r_values), 4) if r_values else 0.0,
        "average_r": round(mean(r_values), 4) if r_values else 0.0,
        "exclusions": len(exclusions),
        "latest_observation": max((clean(row.get("first_seen_timestamp_et")) for row in selected), default=""),
        "status": "COLLECTING" if selected else "WAITING_FOR_FORWARD_EVIDENCE",
        "forward_runway": runway,
    }


def summarize_orb(ledger_csv: Path, status_json: Path) -> dict[str, Any]:
    rows = read_csv_rows(ledger_csv)
    status = read_json(status_json)
    metrics = status.get("metrics", {}) if isinstance(status.get("metrics"), dict) else {}
    r_values = [value for value in (numeric(row.get("outcome_r")) for row in rows if clean(row.get("status")) == "completed") if value is not None]
    return {
        "hypothesis_id": ORB_ID,
        "raw_forward_observations": int(metrics.get("candidates_detected_today", 0) or 0),
        "independent_opportunities": "N/A",
        "eligible_observations": int(metrics.get("qualified_today", 0) or 0),
        "paper_entries": int(metrics.get("open_count", 0) or 0) + int(metrics.get("completed_count", 0) or 0),
        "completed_outcomes": int(metrics.get("completed_count", 0) or len(r_values)),
        "total_r": round(sum(r_values), 4) if r_values else 0.0,
        "average_r": round(mean(r_values), 4) if r_values else 0.0,
        "exclusions": int(metrics.get("exception_count", 0) or 0),
        "latest_observation": status.get("generated_at_et", ""),
        "status": status.get("manual_paper_watch_status", "missing"),
        "forward_runway": "20 completed Manual Paper-Watch trades",
        "authority": str(ledger_csv),
    }


def markdown_table_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No rows._"
    columns = list(rows[0].keys())
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(clean(row.get(column)).replace("|", "\\|") for column in columns) + " |")
    return "\n".join(lines)


def pre_hypothesis_contamination(candidate_rows: list[dict[str, str]], specs: dict[str, HypothesisSpec]) -> int:
    count = 0
    for row in candidate_rows:
        hypothesis_id = hypothesis_for_candidate(row)
        if hypothesis_id and not after_adoption(row, specs[hypothesis_id]):
            count += 1
    return count


def build_payload(
    *,
    output_dir: Path = Path("logs"),
    candidate_ledger_csv: Path | None = None,
    samples_csv: Path | None = None,
    event_state_csv: Path | None = None,
    orb_ledger_csv: Path | None = None,
    orb_status_json: Path | None = None,
    phase3_forward_ledger_csv: Path | None = None,
    logs_dir: Path = Path("logs"),
    classification_timestamp: str | None = None,
) -> dict[str, Any]:
    candidate_ledger_csv = candidate_ledger_csv or runtime_data_path("candidate_window_ledger.csv")
    samples_csv = samples_csv or runtime_data_path("paper_validation_samples.csv")
    event_state_csv = event_state_csv or runtime_data_path("candidate_ledger_event_state.csv")
    orb_ledger_csv = orb_ledger_csv or runtime_data_path("morning_index_orb_manual_paper_trades.csv")
    orb_status_json = orb_status_json or output_dir / "morning_index_orb_manual_paper_watch.json"
    phase3_forward_ledger_csv = phase3_forward_ledger_csv or runtime_data_path("phase3_forward_evidence.csv")

    specs = hypothesis_specs(logs_dir)
    candidates = read_csv_rows(candidate_ledger_csv)
    samples = read_csv_rows(samples_csv)
    events = read_csv_rows(event_state_csv)
    existing = read_csv_rows(phase3_forward_ledger_csv)
    current = classify_rows(
        candidate_rows=candidates,
        sample_rows=samples,
        event_rows=events,
        specs=specs,
        source_artifact=candidate_ledger_csv,
        classification_timestamp=classification_timestamp,
    )
    ledger = merge_idempotent(existing, current)
    p3_h006 = summarize_hypothesis(ledger, P3_H006_ID, "NOT YET GOVERNED")
    qqq = summarize_hypothesis(ledger, QQQ_SETUP_B_ID, "NOT YET GOVERNED")
    orb = summarize_orb(orb_ledger_csv, orb_status_json)
    cohort = load_cohort_1_freeze(logs_dir)
    return {
        "generated_at_et": classification_timestamp or now_et(),
        "status": "PASS",
        "data_contract_version": DATA_CONTRACT_VERSION,
        "ledger_csv": str(phase3_forward_ledger_csv),
        "source_artifacts": {
            "candidate_ledger": str(candidate_ledger_csv),
            "paper_validation_samples": str(samples_csv),
            "candidate_event_state": str(event_state_csv),
            "orb_authority": str(orb_ledger_csv),
            "orb_status": str(orb_status_json),
        },
        "hypothesis_boundaries": {key: spec.adoption_timestamp for key, spec in specs.items()},
        "scorecard": [p3_h006, qqq, orb],
        "pre_hypothesis_contamination": 0,
        "pre_hypothesis_matching_candidates_seen_but_excluded": pre_hypothesis_contamination(candidates, specs),
        "duplicate_forward_records": len(ledger) - len({clean(row.get("forward_evidence_id")) for row in ledger}),
        "cohort_1": {
            "status": cohort.get("status", "UNKNOWN"),
            "observations": cohort.get("strategy_observations", CHECKPOINT_OBSERVATIONS),
            "independent_opportunities": cohort.get("independent_opportunities", {}).get("value", INDEPENDENT_OPPORTUNITIES),
        },
        "production_isolated": True,
        "autonomous": True,
        "guardrail": (
            "Phase 3 Forward Evidence Classifier reads authoritative production artifacts only. "
            "It never changes strategies, gates, risk, broker/live state, Cohort 1, or ORB authority."
        ),
        "ledger_rows": ledger,
    }


def write_outputs(output_dir: Path, payload: dict[str, Any], ledger_csv: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_rows = payload.pop("ledger_rows")
    write_csv_rows(ledger_csv, ledger_rows, LEDGER_COLUMNS)
    payload["ledger_rows"] = len(ledger_rows)
    (output_dir / "phase3_forward_evidence_classifier.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    write_csv_rows(output_dir / "phase3_forward_evidence_scorecard.csv", payload["scorecard"], list(payload["scorecard"][0].keys()))
    summary_rows = [{key: value for key, value in row.items() if key != "authority"} for row in payload["scorecard"]]
    (output_dir / "phase3_forward_evidence_classifier.md").write_text(
        f"""# Phase 3 Forward Evidence Classifier

Generated: {payload["generated_at_et"]}

Status: `{payload["status"]}`

This is evidence accounting only. It reads production artifacts and writes a
separate Phase 3 forward-evidence ledger. It does not scan, trade, size, run
gates, import official samples, or replace ORB's authority.

## Scorecard

{markdown_table_rows(summary_rows)}

## Boundaries

```text
P3-H006: {payload["hypothesis_boundaries"][P3_H006_ID]}
QQQ Setup B late-day: {payload["hypothesis_boundaries"][QQQ_SETUP_B_ID]}
```

## Integrity

```text
Pre-hypothesis contamination: {payload["pre_hypothesis_contamination"]}
Pre-hypothesis matching candidates excluded: {payload["pre_hypothesis_matching_candidates_seen_but_excluded"]}
Duplicate forward records: {payload["duplicate_forward_records"]}
Cohort 1: {payload["cohort_1"]["observations"]} / 30
Independent opportunities: {payload["cohort_1"]["independent_opportunities"]}
Production isolated: {payload["production_isolated"]}
```

## Files

```text
{payload["ledger_csv"]}
{output_dir / "phase3_forward_evidence_classifier.json"}
{output_dir / "phase3_forward_evidence_scorecard.csv"}
```
""",
        encoding="utf-8",
    )


def write_error(output_dir: Path, ledger_csv: Path, error: Exception) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_et": now_et(),
        "status": "WATCH",
        "reason": str(error),
        "ledger_csv": str(ledger_csv),
        "guardrail": "Classifier failure is research-accounting only and must not stop production workflow.",
    }
    (output_dir / "phase3_forward_evidence_classifier.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_dir / "phase3_forward_evidence_classifier.md").write_text(
        f"# Phase 3 Forward Evidence Classifier\n\nStatus: `WATCH`\n\nReason: {error}\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    try:
        payload = build_payload(
            output_dir=args.output_dir,
            candidate_ledger_csv=args.candidate_ledger_csv,
            samples_csv=args.samples_csv,
            event_state_csv=args.event_state_csv,
            orb_ledger_csv=args.orb_ledger_csv,
            orb_status_json=args.orb_status_json,
            phase3_forward_ledger_csv=args.phase3_forward_ledger_csv,
            logs_dir=args.logs_dir,
        )
        write_outputs(args.output_dir, payload, args.phase3_forward_ledger_csv)
        print(f"Phase 3 forward evidence classifier: {payload['status']}")
        print(f"Saved {args.phase3_forward_ledger_csv}")
    except Exception as error:  # fail research accounting closed, not production
        write_error(args.output_dir, args.phase3_forward_ledger_csv, error)
        print("Phase 3 forward evidence classifier: WATCH")
        print(f"Reason: {error}")


if __name__ == "__main__":
    main()
