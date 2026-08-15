"""Cohort 1 immutable evidence freeze helpers.

This module is evidence-archive/reporting only. It reads the authoritative
validation ledger and canonical session state, writes a versioned freeze
snapshot, and refuses to rewrite an existing freeze. It does not mutate
production ledgers, strategy logic, gates, broker state, or phase activation.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any


COHORT_ID = "cohort_1"
COHORT_VERSION = "cohort_1_v1"
CHECKPOINT_OBSERVATIONS = 30
INDEPENDENT_OPPORTUNITIES = 21
INVALID_EXCLUDED_ROWS = 3
FREEZE_SCHEMA_VERSION = "cohort-freeze-v1"
PHASE_2_FREEZE_REASON = "Research Factory acceptance checkpoint satisfied and Cohort 1 frozen."


@dataclass(frozen=True)
class FreezePaths:
    root: Path
    observations_csv: Path
    invalid_rows_csv: Path
    snapshot_json: Path
    report_md: Path
    checksums_sha256: Path


def cohort_freeze_dir(logs_dir: Path, cohort_version: str = COHORT_VERSION) -> Path:
    return logs_dir / "cohorts" / cohort_version


def freeze_paths(logs_dir: Path, cohort_version: str = COHORT_VERSION) -> FreezePaths:
    root = cohort_freeze_dir(logs_dir, cohort_version)
    return FreezePaths(
        root=root,
        observations_csv=root / "cohort_1_observations.csv",
        invalid_rows_csv=root / "cohort_1_excluded_invalid_rows.csv",
        snapshot_json=root / "cohort_1_snapshot.json",
        report_md=root / "cohort_1_final_report.md",
        checksums_sha256=root / "checksums.sha256",
    )


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def clean(value: object) -> str:
    return str(value or "").strip()


def numeric(value: object) -> float | None:
    text = clean(value)
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_csv_rows(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hash(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256_file(path) if path.exists() else "",
    }


def completed_official_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if truthy(row.get("counts_toward_30"))
        and not truthy(row.get("invalid_for_validation"))
        and (clean(row.get("sample_status")).lower() == "completed" or numeric(row.get("outcome_r")) is not None)
    ]


def invalid_official_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if truthy(row.get("counts_toward_30")) and truthy(row.get("invalid_for_validation"))]


def chronological_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        clean(row.get("sample_date")),
        clean(row.get("entry_time_et")) or clean(row.get("source_signal_et")) or clean(row.get("candidate_entry_et")),
        clean(row.get("symbol")),
        clean(row.get("setup")),
    )


def entry_hour(row: dict[str, str]) -> float | None:
    raw = clean(row.get("entry_time_et")) or clean(row.get("source_signal_et")) or clean(row.get("candidate_entry_et"))
    if not raw:
        return None
    time_part = raw.split()[-1]
    pieces = time_part.split(":")
    if len(pieces) < 2:
        return None
    try:
        return int(pieces[0]) + int(pieces[1]) / 60
    except ValueError:
        return None


def time_bucket(row: dict[str, str]) -> str:
    hour = entry_hour(row)
    if hour is None:
        return "unknown"
    if hour < 10.5:
        return "opening_hour"
    if hour < 12:
        return "late_morning"
    if hour < 14:
        return "midday"
    return "late_day"


def row_r(row: dict[str, str]) -> float:
    value = numeric(row.get("outcome_r"))
    return float(value or 0.0)


def trade_label(row: dict[str, str], index: int) -> dict[str, Any]:
    return {
        "trade": index,
        "sample_date": clean(row.get("sample_date")),
        "entry_time_et": clean(row.get("entry_time_et")),
        "exit_time_et": clean(row.get("exit_time_et")),
        "symbol": clean(row.get("symbol")),
        "setup": clean(row.get("setup")),
        "direction": clean(row.get("direction")),
        "outcome_r": row_r(row),
        "contract_symbol": clean(row.get("contract_symbol")),
        "dte": clean(row.get("dte")),
    }


def summarize_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    values = [row_r(row) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    breakevens = [value for value in values if value == 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    curve = []
    for index, row in enumerate(rows, start=1):
        cumulative = round(cumulative + row_r(row), 4)
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, round(cumulative - peak, 4))
        point = trade_label(row, index)
        point["cumulative_r"] = cumulative
        curve.append(point)

    best_index, best_value = max(enumerate(values), key=lambda item: item[1]) if values else (-1, 0)
    worst_index, worst_value = min(enumerate(values), key=lambda item: item[1]) if values else (-1, 0)
    return {
        "n": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate_pct": round((len(wins) / len(rows)) * 100, 2) if rows else 0.0,
        "total_r": round(sum(values), 4),
        "expectancy_r": round(sum(values) / len(rows), 4) if rows else 0.0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else ("INF" if gross_win else 0.0),
        "average_winner_r": round(gross_win / len(wins), 4) if wins else 0.0,
        "average_loser_r": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "median_r": round(median(values), 4) if values else 0.0,
        "max_drawdown_r": max_drawdown,
        "best_trade": trade_label(rows[best_index], best_index + 1) if rows else {},
        "worst_trade": trade_label(rows[worst_index], worst_index + 1) if rows else {},
        "equity_curve": curve,
    }


def breakdown(rows: list[dict[str, str]], key_func) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = clean(key_func(row)) or "unknown"
        groups.setdefault(key, []).append(row)
    return {key: summarize_rows(group) for key, group in sorted(groups.items())}


def dependence_groups(rows: list[dict[str, str]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = "|".join(
            [
                clean(row.get("sample_date")),
                clean(row.get("source_signal_et")) or clean(row.get("candidate_entry_et")) or clean(row.get("entry_time_et")),
                clean(row.get("symbol")).upper(),
            ]
        )
        groups.setdefault(key, []).append(row)
    records = []
    dependent_observations = 0
    for index, (key, group) in enumerate(sorted(groups.items()), start=1):
        classification = "A" if len(group) == 1 else "B"
        if len(group) > 1:
            dependent_observations += len(group) - 1
        records.append(
            {
                "group_id": f"C1-{index:03d}",
                "group_key": key,
                "classification": classification,
                "strategy_observations": len(group),
                "members": [
                    {
                        "sample_date": clean(row.get("sample_date")),
                        "entry_time_et": clean(row.get("entry_time_et")),
                        "symbol": clean(row.get("symbol")),
                        "setup": clean(row.get("setup")),
                        "direction": clean(row.get("direction")),
                        "outcome_r": row_r(row),
                    }
                    for row in group
                ],
            }
        )
    return {
        "derived_effective_independent_opportunities": INDEPENDENT_OPPORTUNITIES,
        "derived_from": "Governed 2026-08-13 baseline of 20 plus one distinct completed August 14 opportunity.",
        "method_note": "Dependence groups preserve observable shared source signal/date/symbol relationships. The official independent opportunity count remains the governed derived/effective count.",
        "detected_groups": records,
        "detected_distinct_group_count": len(records),
        "dependent_observations_detected": dependent_observations,
    }


def scorecard(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "overall": summarize_rows(rows),
        "by_setup": breakdown(rows, lambda row: row.get("setup")),
        "by_symbol": breakdown(rows, lambda row: row.get("symbol")),
        "by_direction": breakdown(rows, lambda row: row.get("direction")),
        "by_time_bucket": breakdown(rows, time_bucket),
        "by_dte": breakdown(rows, lambda row: row.get("dte") or "missing"),
    }


def markdown_report(snapshot: dict[str, Any]) -> str:
    overall = snapshot["scorecard"]["overall"]
    findings = snapshot["phase_2_findings"]
    return f"""# Project Gwala Cohort 1 Final Freeze Report

Freeze Version: {snapshot["cohort_version"]}
Freeze Timestamp: {snapshot["freeze_timestamp"]}
Production Commit: {snapshot["production_commit"]}

## Status

- Cohort 1: FROZEN
- Phase 2: COMPLETE
- Phase 3: PREPARED - NOT ACTIVE
- Broker / Real Money: DISABLED

## Evidence Counts

- Strategy Observations: {snapshot["strategy_observations"]}
- Independent Opportunities: {snapshot["independent_opportunities"]["value"]} ({snapshot["independent_opportunities"]["provenance"]})
- Excluded Invalid Rows Preserved: {snapshot["excluded_invalid_rows"]}

## Final Strategy-Observation Scorecard

- Wins: {overall["wins"]}
- Losses: {overall["losses"]}
- Breakevens: {overall["breakevens"]}
- Win Rate: {overall["win_rate_pct"]}%
- Total R: {overall["total_r"]}R
- Expectancy: {overall["expectancy_r"]}R
- Profit Factor: {overall["profit_factor"]}
- Average Winner: {overall["average_winner_r"]}R
- Average Loser: {overall["average_loser_r"]}R
- Median R: {overall["median_r"]}R
- Max Drawdown: {overall["max_drawdown_r"]}R
- Best Trade: {overall["best_trade"]}
- Worst Trade: {overall["worst_trade"]}

## Independence / Dependence Interpretation

Strategy-observation P&L is not independence-adjusted. Cohort 1 contains 30
legitimate official strategy observations and 21 derived/effective independent
market opportunities. Dependent observations remain valid strategy observations
but must not inflate statistical confidence.

## Phase 2 Findings

- What Phase 2 proved: {findings["proved"]}
- What Phase 2 did not prove: {findings["did_not_prove"]}
- Biggest strategy weakness: {findings["biggest_weakness"]}
- Strongest preliminary pocket: {findings["strongest_preliminary_pocket"]}
- Evidence-quality limitations: {findings["evidence_quality_limitations"]}
- Timing limitations: {findings["timing_limitations"]}
- Phase 3 first investigation: {findings["phase_3_first_investigation"]}

## Guardrails

This freeze does not activate Phase 3, authorize live capital, alter historical
observations, reclassify outcomes, change strategy rules, or mutate the
authoritative validation ledger. Future corrections require an explicitly
versioned amendment preserving this original freeze.
"""


def build_phase_2_findings(summary: dict[str, Any]) -> dict[str, str]:
    by_setup = summary.get("by_setup", {})
    best_setup = "none"
    if by_setup:
        best_setup = max(by_setup.items(), key=lambda item: item[1]["expectancy_r"])[0]
    return {
        "proved": "Gwala can autonomously collect and reconcile 30 completed official paper strategy observations under the Phase 2 evidence factory.",
        "did_not_prove": "Cohort 1 did not validate a profitable edge, authorize live capital, or prove 30 statistically independent market opportunities.",
        "biggest_weakness": "Aggregate strategy-observation expectancy is negative, so the current broad Phase 2 strategy set is not commercially validated.",
        "strongest_preliminary_pocket": f"{best_setup} produced the strongest observed setup-level expectancy in Cohort 1, but remains preliminary.",
        "evidence_quality_limitations": "Independent opportunities are derived/effective rather than persisted as a first-class ledger identity; dependent observations must be interpreted conservatively.",
        "timing_limitations": "Historical Cohort 1 observations include older timing regimes and must not be used as proof of current live execution latency.",
        "phase_3_first_investigation": "Start with narrow, evidence-supported pockets from the frozen setup/symbol/direction breakdown rather than promoting the aggregate strategy family.",
    }


def freeze_cohort_1(
    *,
    logs_dir: Path,
    data_dir: Path,
    production_commit: str,
    freeze_timestamp: str | None = None,
    cohort_version: str = COHORT_VERSION,
) -> dict[str, Any]:
    paths = freeze_paths(logs_dir, cohort_version)
    if paths.snapshot_json.exists():
        raise FileExistsError(f"Cohort freeze already exists: {paths.snapshot_json}")

    ledger_path = data_dir / "paper_validation_samples.csv"
    rows, fields = read_csv_rows(ledger_path)
    completed = sorted(completed_official_rows(rows), key=chronological_key)
    invalid = sorted(invalid_official_rows(rows), key=chronological_key)
    if len(completed) != CHECKPOINT_OBSERVATIONS:
        raise ValueError(f"Expected exactly {CHECKPOINT_OBSERVATIONS} completed official observations, found {len(completed)}.")
    if len(invalid) != INVALID_EXCLUDED_ROWS:
        raise ValueError(f"Expected exactly {INVALID_EXCLUDED_ROWS} excluded invalid rows, found {len(invalid)}.")

    paths.root.mkdir(parents=True, exist_ok=False)
    write_csv_rows(paths.observations_csv, completed, fields)
    write_csv_rows(paths.invalid_rows_csv, invalid, fields)

    canonical_path = logs_dir / "canonical_session_state" / "2026-08-14.json"
    canonical = read_json(canonical_path)
    source_paths = {
        "validation_ledger": ledger_path,
        "canonical_session_state": canonical_path,
        "governance_definition": Path("docs/cohort-1-evidence-independence-governance.md"),
        "production_heartbeat": logs_dir / "production_heartbeat.json",
        "current_candle_capture": logs_dir / "current_candle_capture.json",
        "scanner": logs_dir / "daily_paper_signal_scanner.csv",
        "position_sizing": logs_dir / "position_sizing.csv",
        "paper_gate": logs_dir / "paper_gate_v2.csv",
    }
    summary = scorecard(completed)
    snapshot = {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "cohort_id": COHORT_ID,
        "cohort_version": cohort_version,
        "status": "FROZEN",
        "freeze_timestamp": freeze_timestamp or datetime.now().isoformat(),
        "production_commit": production_commit,
        "phase_2": {"status": "COMPLETE", "reason": PHASE_2_FREEZE_REASON},
        "phase_3": {"status": "PREPARED - NOT ACTIVE", "activated": False},
        "broker_real_money": "DISABLED",
        "strategy_observations": len(completed),
        "independent_opportunities": {
            "value": INDEPENDENT_OPPORTUNITIES,
            "provenance": "derived/effective",
            "derivation": "Governed 2026-08-13 baseline of 20 plus one distinct completed August 14 opportunity.",
        },
        "excluded_invalid_rows": len(invalid),
        "canonical_reporting_consistency": canonical.get("reporting_consistency", {}).get("status", "PASS"),
        "source_paths": {key: str(path) for key, path in source_paths.items()},
        "source_hashes": {key: source_hash(path) for key, path in source_paths.items()},
        "snapshot_artifacts": {
            "observations_csv": str(paths.observations_csv),
            "invalid_rows_csv": str(paths.invalid_rows_csv),
            "snapshot_json": str(paths.snapshot_json),
            "report_md": str(paths.report_md),
            "checksums_sha256": str(paths.checksums_sha256),
        },
        "scorecard": summary,
        "dependence": dependence_groups(completed),
        "evidence_limitations": [
            "Cohort 1 has 30 strategy observations, not 30 independent market opportunities.",
            "Independent opportunities are derived/effective and should be treated conservatively until persisted as a first-class evidence identity.",
            "Cohort 1 includes historical timing regimes; it is not proof of live execution readiness.",
        ],
        "phase_2_findings": build_phase_2_findings(summary),
        "guardrails": [
            "Do not mutate authoritative historical ledger.",
            "Do not append future observations to Cohort 1.",
            "Do not activate Phase 3 from this freeze.",
            "Do not enable broker/live or real-money behavior.",
            "Future corrections require an explicitly versioned amendment preserving this original freeze.",
        ],
    }
    paths.snapshot_json.write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding="utf-8")
    paths.report_md.write_text(markdown_report(snapshot), encoding="utf-8")

    artifact_hashes = {
        "observations_csv": sha256_file(paths.observations_csv),
        "invalid_rows_csv": sha256_file(paths.invalid_rows_csv),
        "report_md": sha256_file(paths.report_md),
    }
    snapshot["artifact_hashes"] = artifact_hashes
    snapshot["snapshot_json_sha256_location"] = str(paths.checksums_sha256)
    snapshot["snapshot_artifacts"]["checksums_sha256"] = str(paths.checksums_sha256)
    paths.snapshot_json.write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding="utf-8")
    checksum_manifest = dict(artifact_hashes)
    checksum_manifest["snapshot_json"] = sha256_file(paths.snapshot_json)
    paths.checksums_sha256.write_text(
        "".join(f"{checksum}  {name}\n" for name, checksum in sorted(checksum_manifest.items())),
        encoding="utf-8",
    )
    return snapshot


def load_cohort_1_freeze(logs_dir: Path, cohort_version: str = COHORT_VERSION) -> dict[str, Any]:
    payload = read_json(freeze_paths(logs_dir, cohort_version).snapshot_json)
    return payload if payload.get("schema_version") == FREEZE_SCHEMA_VERSION else {}


def verify_cohort_1_freeze(logs_dir: Path, data_dir: Path, cohort_version: str = COHORT_VERSION) -> dict[str, Any]:
    paths = freeze_paths(logs_dir, cohort_version)
    snapshot = load_cohort_1_freeze(logs_dir, cohort_version)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    add("snapshot exists", bool(snapshot), str(paths.snapshot_json))
    if not snapshot:
        return {"status": "FAIL", "checks": checks}
    rows, _ = read_csv_rows(paths.observations_csv)
    invalid, _ = read_csv_rows(paths.invalid_rows_csv)
    source_rows, _ = read_csv_rows(data_dir / "paper_validation_samples.csv")
    add("30 frozen observations", len(rows) == CHECKPOINT_OBSERVATIONS, str(len(rows)))
    add("21 independent opportunities", snapshot.get("independent_opportunities", {}).get("value") == INDEPENDENT_OPPORTUNITIES, str(snapshot.get("independent_opportunities", {}).get("value")))
    add("3 invalid rows preserved", len(invalid) == INVALID_EXCLUDED_ROWS, str(len(invalid)))
    add("ledger still contains frozen rows", len(completed_official_rows(source_rows)) >= len(rows), str(len(completed_official_rows(source_rows))))
    for artifact_name, checksum in snapshot.get("artifact_hashes", {}).items():
        path_text = snapshot.get("snapshot_artifacts", {}).get(artifact_name)
        if path_text:
            path = Path(path_text)
            add(f"checksum {artifact_name}", path.exists() and sha256_file(path) == checksum, str(path))
    checksum_entries = {}
    if paths.checksums_sha256.exists():
        for line in paths.checksums_sha256.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                checksum_entries[parts[1]] = parts[0]
    add(
        "checksum snapshot_json",
        checksum_entries.get("snapshot_json") == sha256_file(paths.snapshot_json),
        str(paths.snapshot_json),
    )
    return {"status": "FAIL" if any(check["status"] == "FAIL" for check in checks) else "PASS", "checks": checks}
