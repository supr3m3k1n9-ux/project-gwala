"""Validate that app-facing data pipes are synchronized.

This is a local research/paper guardrail. It checks the saved outputs that feed
Home, Paper Progress, scanner review, sizing, router, and dashboard preflight.
It does not fetch data, import paper trades, place orders, create alerts, or
connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_root
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Project Gwala data-flow synchronization.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where workflow outputs live.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when the data-flow contract is blocked.",
    )
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def file_mtime(path: Path) -> float:
    """Return a file modification timestamp or 0 when missing."""

    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def int_field(payload: dict[str, Any], key: str, default: int = 0) -> int:
    """Return a safe integer from a JSON payload field."""

    value = payload.get(key, default)
    if value is None or value == "":
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalized_candidate_source(payload: dict[str, Any], default: str = "unknown") -> str:
    """Return the authoritative candidate population source for a gate payload."""

    source = str(payload.get("promotion_source") or payload.get("candidate_source") or default)
    if source == "candidate_ledger":
        return "candidate_window_ledger"
    if source in {"scanner", "scanner_csv"}:
        return "scanner_snapshot"
    return source


def check_row(area: str, status: str, detail: str, action: str = "") -> dict[str, str]:
    """Build one sentinel check row."""

    return {"area": area, "status": status, "detail": detail, "action": action}


def latest_scan_date(scanner: pd.DataFrame) -> str:
    """Return the newest scan_date in the scanner CSV."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return ""
    values = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
    return values[-1] if values else ""


def row_keys(frame: pd.DataFrame, columns: list[str]) -> set[tuple[str, ...]]:
    """Return stable row identity keys from a frame."""

    if frame.empty or any(column not in frame.columns for column in columns):
        return set()
    return {
        tuple(str(row[column]) for column in columns)
        for _, row in frame[columns].dropna(how="all").iterrows()
    }


def scanner_pre_entry_candidates(scanner: pd.DataFrame) -> pd.DataFrame:
    """Return scanner rows that should flow into pre-entry review."""

    if scanner.empty:
        return pd.DataFrame()
    required = {"scanner_status", "signal_freshness"}
    if not required.issubset(scanner.columns):
        return pd.DataFrame()
    return scanner[
        scanner["scanner_status"].astype(str).isin(["allowed", "blocked_watch_only"])
        & scanner["signal_freshness"].astype(str).isin(["current_candle", "grace_candle", "earlier_today"])
    ].copy()


def repair_summary(output_dir: Path) -> dict[str, Any]:
    """Summarize the latest M30 repair audit."""

    audit = read_csv_or_empty(output_dir / "m30_repair_audit.csv")
    if audit.empty or "status" not in audit.columns:
        return {"status": "not_run", "repaired_symbols": [], "message": "No repair audit found."}
    repaired = audit[audit["status"].astype(str) == "repaired"]
    symbols = sorted(set(repaired["symbol"].astype(str).str.upper())) if "symbol" in repaired.columns else []
    if symbols:
        return {
            "status": "repair_applied",
            "repaired_symbols": symbols,
            "message": f"Repaired M30 from lower timeframe for: {', '.join(symbols)}.",
        }
    return {"status": "no_repair_needed", "repaired_symbols": [], "message": "No stale M30 repair was needed."}


def latest_refresh_audit(output_dir: Path) -> pd.DataFrame:
    """Return the latest refresh-audit rows when available.

    The daily workflow writes the audit CSV under data/ for the real app, while
    tests and one-off checks may place it beside the other output files.
    """

    local_path = output_dir / "market_refresh_audit.csv"
    audit_path = local_path
    if not audit_path.exists() and output_dir.name == "logs":
        audit_path = runtime_data_root() / "market_refresh_audit.csv"
    audit = read_csv_or_empty(audit_path)
    if audit.empty or "refresh_run_at_et" not in audit.columns:
        return pd.DataFrame()
    latest_run = str(audit["refresh_run_at_et"].dropna().iloc[-1])
    return audit[audit["refresh_run_at_et"].astype(str) == latest_run].copy()


def provider_stability_summary(output_dir: Path, repair: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether the latest provider refresh looked internally stable."""

    provider_audit = read_json_or_empty(output_dir / "provider_stability_audit.json")
    if provider_audit:
        status = str(provider_audit.get("status", "not_recorded"))
        audit_repair = provider_audit.get("repair", {}) if isinstance(provider_audit.get("repair"), dict) else {}
        if status == "stable":
            sentinel_status = "stable"
        elif status == "watch":
            sentinel_status = "watch_repaired" if audit_repair.get("status") == "repair_applied" else "watch"
        elif status == "blocked":
            sentinel_status = "mixed_session"
        else:
            sentinel_status = status
        return {
            "status": sentinel_status,
            "mismatch_symbols": provider_audit.get("mismatch_symbols", []),
            "latest_refresh_run_at_et": provider_audit.get("latest_refresh_run_at_et", ""),
            "evidence_counts": provider_audit.get("evidence_counts", {}),
            "message": provider_audit.get("next_action") or "Provider stability audit is available.",
        }

    audit = latest_refresh_audit(output_dir)
    repair_applied = str(repair.get("status", "")) == "repair_applied"
    if audit.empty:
        return {
            "status": "not_recorded",
            "mismatch_symbols": [],
            "latest_refresh_run_at_et": "",
            "message": "No refresh-audit CSV was available for provider/session stability checks.",
        }

    evidence_counts = (
        audit["refresh_evidence_status"].astype(str).value_counts().to_dict()
        if "refresh_evidence_status" in audit.columns
        else {}
    )
    mismatches = audit[
        audit.get("refresh_evidence_status", pd.Series(dtype=str)).astype(str) == "timeframe_session_mismatch"
    ]
    mismatch_symbols = sorted(set(mismatches["symbol"].astype(str).str.upper())) if "symbol" in mismatches.columns else []
    latest_run = str(audit["refresh_run_at_et"].dropna().iloc[-1]) if "refresh_run_at_et" in audit.columns else ""

    if mismatch_symbols and repair_applied:
        status = "watch_repaired"
        message = (
            "Latest audit saw M5/M30 session mismatch, but the M30 repair guardrail produced "
            "current-session rows before the dashboard contract was checked."
        )
    elif mismatch_symbols:
        status = "mixed_session"
        message = "Latest audit still has M5/M30 session mismatch rows."
    else:
        status = "stable"
        message = "Latest audit rows agree on current provider/session evidence."

    return {
        "status": status,
        "mismatch_symbols": mismatch_symbols,
        "latest_refresh_run_at_et": latest_run,
        "evidence_counts": {str(key): int(value) for key, value in evidence_counts.items()},
        "message": message,
    }


def build_data_flow_sentinel(output_dir: Path = Path("logs")) -> dict[str, Any]:
    """Build the data-flow contract and check results."""

    refresh = read_json_or_empty(output_dir / "refresh_status.json")
    system = read_json_or_empty(output_dir / "system_state.json")
    preflight = read_json_or_empty(output_dir / "dashboard_data_preflight.json")
    historical_sync = read_json_or_empty(output_dir / "historical_bucket_sync.json")
    router = read_json_or_empty(output_dir / "market_regime_router.json")
    pre_entry = read_json_or_empty(output_dir / "pre_entry_review.json")
    paper_gate_path = output_dir / "paper_gate_v2.json"
    options_gate_path = output_dir / "options_contract_gate.json"
    validation_import_path = output_dir / "paper_validation_sample_import.json"
    paper_gate = read_json_or_empty(paper_gate_path)
    options_gate = read_json_or_empty(options_gate_path)
    validation_import = read_json_or_empty(validation_import_path)
    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    repair = repair_summary(output_dir)
    provider_stability = provider_stability_summary(output_dir, repair)

    market = refresh.get("market", {}) if refresh else system.get("market", {})
    today = str(market.get("today") or system.get("market", {}).get("today") or "")
    market_open = bool(market.get("market_is_open") or system.get("market", {}).get("market_is_open"))
    refresh_scanner = refresh.get("scanner", {}) if isinstance(refresh.get("scanner"), dict) else {}
    provider = refresh.get("provider_refresh", {}) if isinstance(refresh.get("provider_refresh"), dict) else {}
    candle = refresh.get("candle_freshness", {}) if isinstance(refresh.get("candle_freshness"), dict) else {}
    system_scanner = system.get("scanner", {}) if isinstance(system.get("scanner"), dict) else {}
    system_candidates = system.get("current_candidates", {}) if isinstance(system.get("current_candidates"), dict) else {}

    checks: list[dict[str, str]] = []
    checks.append(
        check_row(
            "Refresh status",
            "pass" if refresh else "fail",
            f"Status: {refresh.get('status', 'missing') if refresh else 'missing'}.",
            "Run python run_refresh_status.py --output-dir logs.",
        )
    )
    checks.append(
        check_row(
            "System state",
            "pass" if system else "fail",
            f"Generated: {system.get('app_health', {}).get('generated_at_et', 'missing') if system else 'missing'}.",
            "Run python run_system_state.py --output-dir logs.",
        )
    )

    preflight_status = str(preflight.get("status", "missing"))
    checks.append(
        check_row(
            "Dashboard preflight",
            "pass" if preflight_status == "pass" else "fail",
            f"Preflight status: {preflight_status}.",
            "Run python run_dashboard_data_preflight.py --output-dir logs and fix listed blockers.",
        )
    )

    provider_status = str(provider.get("status", "missing"))
    if market_open and provider_status != "current_session_bars":
        checks.append(
            check_row(
                "Provider freshness",
                "fail",
                f"Market is open but provider status is {provider_status}.",
                "Run python run_daily_workflow.py --refresh-data --data-provider webull.",
            )
        )
    else:
        checks.append(check_row("Provider freshness", "pass", f"Provider status: {provider_status}."))

    candle_status = str(candle.get("status", "missing"))
    stale_m5 = candle.get("stale_m5_symbols", []) or []
    stale_m30 = candle.get("stale_m30_symbols", []) or []
    unknown = candle.get("unknown_symbols", []) or []
    if market_open and (candle_status != "fresh" or stale_m5 or stale_m30 or unknown):
        checks.append(
            check_row(
                "Candle freshness",
                "fail",
                f"Status {candle_status}; stale M5 {stale_m5}; stale M30 {stale_m30}; unknown {unknown}.",
                "Refresh Webull data; the workflow will repair stale M30 when lower-timeframe candles are current.",
            )
        )
    else:
        checks.append(check_row("Candle freshness", "pass", f"Status: {candle_status}; no blocking stale symbols."))

    scanner_session = latest_scan_date(scanner)
    refresh_session = str(refresh_scanner.get("latest_scanner_session", ""))
    if market_open and scanner_session != today:
        checks.append(
            check_row(
                "Scanner session",
                "fail",
                f"Scanner session {scanner_session or 'missing'} does not match today {today}.",
                "Run the daily workflow after market data refresh.",
            )
        )
    elif refresh_session and scanner_session and refresh_session != scanner_session:
        checks.append(
            check_row(
                "Scanner session",
                "fail",
                f"Refresh status sees {refresh_session}, scanner CSV sees {scanner_session}.",
                "Rebuild refresh status and system state after scanner generation.",
            )
        )
    else:
        checks.append(check_row("Scanner session", "pass", f"Scanner session: {scanner_session or 'unknown'}."))

    scanner_rows = int(len(scanner))
    system_scanner_rows = int(system_scanner.get("rows", -1) or 0) if system else -1
    if system and scanner_rows != system_scanner_rows:
        checks.append(
            check_row(
                "Scanner to system state",
                "fail",
                f"Scanner CSV has {scanner_rows} rows but system_state reports {system_scanner_rows}.",
                "Run python run_system_state.py --output-dir logs after scanner rebuild.",
            )
        )
    else:
        checks.append(check_row("Scanner to system state", "pass", f"{scanner_rows} scanner rows represented."))

    scanner_keys = row_keys(scanner, ["symbol", "setup", "direction"])
    sizing_keys = row_keys(sizing, ["symbol", "setup", "direction"])
    missing_sizing = sorted(scanner_keys - sizing_keys)
    if scanner_rows and missing_sizing:
        checks.append(
            check_row(
                "Scanner to sizing",
                "fail",
                f"{len(missing_sizing)} scanner row(s) are missing sizing rows.",
                "Run python run_position_sizer.py --output-dir logs.",
            )
        )
    else:
        checks.append(check_row("Scanner to sizing", "pass", f"Sizing rows cover {len(scanner_keys)} scanner keys."))

    router_rows = router.get("candidates", []) if isinstance(router.get("candidates"), list) else []
    if scanner_rows and len(router_rows) != scanner_rows:
        checks.append(
            check_row(
                "Scanner to router",
                "fail",
                f"Router has {len(router_rows)} candidates; scanner has {scanner_rows}.",
                "Run python run_market_regime_router.py --output-dir logs.",
            )
        )
    else:
        checks.append(check_row("Scanner to router", "pass", f"Router candidates: {len(router_rows)}."))

    pre_entry_candidates = scanner_pre_entry_candidates(scanner)
    pre_entry_count = int(pre_entry.get("candidate_count", -1) or 0) if pre_entry else -1
    if pre_entry and pre_entry_count != len(pre_entry_candidates):
        checks.append(
            check_row(
                "Scanner to pre-entry",
                "fail",
                f"Pre-entry reviewed {pre_entry_count}; scanner has {len(pre_entry_candidates)} review candidate row(s).",
                "Run python run_pre_entry_review.py --output-dir logs after scanner/sizing/router rebuild.",
            )
        )
    else:
        checks.append(check_row("Scanner to pre-entry", "pass", f"Pre-entry reviewed {max(pre_entry_count, 0)} scanner review row(s)."))

    current_candidate_count = int(system_candidates.get("count", -1) or 0) if system else -1
    scanner_current_count = 0
    if not scanner.empty and {"scanner_status", "signal_freshness"}.issubset(scanner.columns):
        scanner_current_count = int(
            len(
                scanner[
                    scanner["scanner_status"].astype(str).isin(["allowed", "blocked_watch_only"])
                    & scanner["signal_freshness"].astype(str).isin(["current_candle", "grace_candle"])
                ]
            )
        )
    if system and current_candidate_count != scanner_current_count:
        checks.append(
            check_row(
                "Current candidate panel",
                "fail",
                f"System state has {current_candidate_count}; scanner has {scanner_current_count} A-current/B-grace candidate row(s).",
                "Rebuild system state after scanner and sizing.",
            )
        )
    else:
        checks.append(check_row("Current candidate panel", "pass", f"{scanner_current_count} A-current/B-grace candidate row(s) in sync."))

    missing_gate_reports = []
    if not paper_gate:
        missing_gate_reports.append("paper_gate_v2.json")
    if not options_gate:
        missing_gate_reports.append("options_contract_gate.json")
    if not validation_import:
        missing_gate_reports.append("paper_validation_sample_import.json")
    paper_ready = int_field(paper_gate, "ready_sample_count", 0)
    options_ready = int_field(options_gate, "ready_sample_count", -1)
    options_passed = int_field(options_gate, "passed_contract_count", -1)
    import_ready = int_field(validation_import, "ready_candidates", -1)
    import_contract_ready = int_field(validation_import, "contract_ready_candidates", -1)
    import_missing_reviews = int_field(validation_import, "missing_contract_reviews", -1)
    import_blocked = int_field(validation_import, "blocked_contract_count", -1)
    options_missing_reviews = int_field(options_gate, "missing_contract_reviews", -1)
    options_blocked = int_field(options_gate, "blocked_contract_count", -1)
    options_status = str(options_gate.get("status", "missing"))
    import_gate_status = str(validation_import.get("contract_gate_status", "missing"))
    paper_source = normalized_candidate_source(paper_gate, "scanner_snapshot") if paper_gate else "missing"
    options_source = normalized_candidate_source(options_gate, "candidate_window_ledger") if options_gate else "missing"
    import_source = normalized_candidate_source(validation_import, options_source) if validation_import else "missing"
    scanner_snapshot_population = "current scanner snapshot; market-state signal only"
    candidate_ledger_population = "preserved actionable candidate windows; validation sequence source"
    if missing_gate_reports:
        checks.append(
            check_row(
                "Validation gate sequence",
                "fail",
                f"Missing gate report(s): {', '.join(missing_gate_reports)}.",
                "Run paper gate, options contract gate, validation sample import, then rebuild preflight/sentinel/system state.",
            )
        )
    else:
        gate_mismatches = []
        if paper_source == options_source and options_ready != paper_ready:
            gate_mismatches.append(
                f"Same-source Paper Gate ready {paper_ready} vs Contract Gate ready {options_ready} ({options_source})"
            )
        if import_ready != options_ready:
            gate_mismatches.append(f"Import ready {import_ready} vs Contract Gate ready {options_ready}")
        if import_contract_ready != options_passed:
            gate_mismatches.append(f"Import contract-ready {import_contract_ready} vs Contract Gate pass {options_passed}")
        if import_gate_status != options_status:
            gate_mismatches.append(f"Import gate status {import_gate_status} vs Contract Gate status {options_status}")
        if import_missing_reviews != options_missing_reviews:
            gate_mismatches.append(
                f"Import missing reviews {import_missing_reviews} vs Contract Gate missing {options_missing_reviews}"
            )
        if import_blocked != options_blocked:
            gate_mismatches.append(f"Import blocked {import_blocked} vs Contract Gate blocked {options_blocked}")
        paper_mtime = file_mtime(paper_gate_path)
        options_mtime = file_mtime(options_gate_path)
        import_mtime = file_mtime(validation_import_path)
        if paper_source == options_source and paper_mtime and options_mtime and options_mtime < paper_mtime:
            gate_mismatches.append("Contract Gate report is older than Paper Gate v2")
        if options_mtime and import_mtime and import_mtime < options_mtime:
            gate_mismatches.append("Validation Sample Import report is older than Options Contract Gate")
        if gate_mismatches:
            checks.append(
                check_row(
                    "Validation gate sequence",
                    "fail",
                    "; ".join(gate_mismatches) + ".",
                    "Re-run Paper Gate v2, Options Contract Gate, and Validation Sample Import in order.",
                )
            )
        else:
            checks.append(
                check_row(
                    "Validation gate sequence",
                    "pass",
                    (
                        f"Candidate-ledger paper ready {options_ready}; contract pass {options_passed}; "
                        f"import new rows {int_field(validation_import, 'new_rows', 0)}. "
                        f"Scanner-snapshot paper ready {paper_ready} is tracked separately."
                    ),
                )
            )

    repair_status = str(repair.get("status", "not_run"))
    repair_check_status = "warn" if repair_status == "repair_applied" else "pass"
    checks.append(check_row("M30 repair guardrail", repair_check_status, str(repair.get("message", ""))))

    provider_stability_status = str(provider_stability.get("status", "not_recorded"))
    if provider_stability_status == "mixed_session":
        checks.append(
            check_row(
                "Provider/session stability",
                "fail",
                str(provider_stability.get("message", "")),
                "Run market-data refresh again; do not trust paper-review rows until M5/M30 sessions agree.",
            )
        )
    elif provider_stability_status == "watch_repaired":
        checks.append(
            check_row(
                "Provider/session stability",
                "warn",
                str(provider_stability.get("message", "")),
                "Usable after repair, but keep watching for repeated provider/session mismatches.",
            )
        )
    else:
        checks.append(
            check_row(
                "Provider/session stability",
                "pass",
                str(provider_stability.get("message", "")),
            )
        )

    historical_status = str(historical_sync.get("status", "missing"))
    historical_target = str(historical_sync.get("target_scanner_session", "unknown"))
    historical_behind = historical_sync.get("behind_buckets", [])
    historical_missing = historical_sync.get("missing_buckets", [])
    if historical_status == "synced":
        checks.append(
            check_row(
                "Historical bucket sync",
                "pass",
                f"Historical buckets are synced through scanner session {historical_target}.",
            )
        )
    else:
        checks.append(
            check_row(
                "Historical bucket sync",
                "warn",
                (
                    f"Historical bucket status {historical_status}; behind {historical_behind}; "
                    f"missing {historical_missing}."
                ),
                "Run python run_historical_bucket_sync.py --output-dir logs after historical producers rebuild.",
            )
        )

    fail_count = sum(1 for row in checks if row["status"] == "fail")
    warn_count = sum(1 for row in checks if row["status"] == "warn")
    status = "blocked" if fail_count else "watch" if warn_count else "synced"
    if status == "blocked":
        next_action = "Do not trust current dashboard candidates until the failed data-flow checks are rebuilt."
    elif status == "watch":
        next_action = "Data is usable, but review the repair/audit note before paper review."
    else:
        next_action = "Data pipes are synchronized; use router and pre-entry gates for paper-review decisions."

    contract = {
        "market_open": market_open,
        "today": today,
        "provider_status": provider_status,
        "candle_status": candle_status,
        "scanner_session": scanner_session or "unknown",
        "scanner_rows": scanner_rows,
        "sizing_rows": int(len(sizing)),
        "router_candidate_rows": len(router_rows),
        "pre_entry_candidate_count": max(pre_entry_count, 0),
        "current_candidate_count": scanner_current_count,
        "system_current_candidate_count": max(current_candidate_count, 0),
        "dashboard_preflight_status": preflight_status,
        "paper_gate_status": paper_gate.get("status", "missing") if paper_gate else "missing",
        "paper_gate_ready_samples": paper_ready if paper_gate else 0,
        "paper_gate_candidate_source": paper_source,
        "paper_gate_promotion_source": paper_gate.get("promotion_source", "missing") if paper_gate else "missing",
        "paper_gate_artifact_timestamp": paper_gate.get("generated_at_et", "") if paper_gate else "",
        "paper_gate_population_meaning": (
            scanner_snapshot_population if paper_source == "scanner_snapshot" else candidate_ledger_population
        ),
        "scanner_snapshot_paper_gate_ready_samples": paper_ready if paper_source == "scanner_snapshot" else 0,
        "scanner_snapshot_paper_gate_population_meaning": scanner_snapshot_population,
        "candidate_ledger_paper_gate_ready_samples": max(options_ready, 0) if options_gate else 0,
        "candidate_ledger_paper_gate_candidate_source": options_source if options_gate else "missing",
        "candidate_ledger_paper_gate_artifact_timestamp": options_gate.get("generated_at_et", "") if options_gate else "",
        "candidate_ledger_paper_gate_population_meaning": candidate_ledger_population,
        "options_contract_gate_status": options_status if options_gate else "missing",
        "options_contract_gate_candidate_source": options_source,
        "options_contract_gate_promotion_source": options_gate.get("promotion_source", "missing") if options_gate else "missing",
        "options_contract_gate_artifact_timestamp": options_gate.get("generated_at_et", "") if options_gate else "",
        "options_contract_gate_population_meaning": candidate_ledger_population,
        "options_contract_passed": max(options_passed, 0),
        "validation_import_mode": validation_import.get("mode", "missing") if validation_import else "missing",
        "validation_import_candidate_source": import_source,
        "validation_import_promotion_source": validation_import.get("promotion_source", "missing") if validation_import else "missing",
        "validation_import_artifact_timestamp": validation_import.get("generated_at_et", "") if validation_import else "",
        "validation_import_population_meaning": candidate_ledger_population,
        "validation_import_new_rows": max(int_field(validation_import, "new_rows", 0), 0),
        "repair_status": repair_status,
        "repair_symbols": repair.get("repaired_symbols", []),
        "provider_stability_status": provider_stability_status,
        "provider_stability_detail": provider_stability.get("message", ""),
        "provider_mismatch_symbols": provider_stability.get("mismatch_symbols", []),
        "latest_refresh_run_at_et": provider_stability.get("latest_refresh_run_at_et", ""),
        "historical_bucket_status": historical_status,
        "historical_bucket_target_session": historical_target,
        "historical_bucket_unified_last_entry": historical_sync.get("unified_last_entry", ""),
        "historical_bucket_behind": historical_behind,
        "historical_bucket_missing": historical_missing,
    }

    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "next_action": next_action,
        "contract": contract,
        "checks": checks,
        "guardrail": "Local data-flow sentinel only. No broker actions, alerts, or paper imports.",
    }


def write_reports(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write sentinel JSON, contract JSON, and Markdown report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data_flow_sentinel.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "data_flow_contract.json").write_text(json.dumps(payload["contract"], indent=2, allow_nan=False), encoding="utf-8")
    checks = pd.DataFrame(payload["checks"])
    contract = pd.DataFrame([payload["contract"]])
    (output_dir / "data_flow_sentinel.md").write_text(
        f"""# Data Flow Sentinel

This report verifies that the app-facing data pipes are synchronized before
Home or Paper Progress should be trusted.

Important: this is research/paper workflow only. It does not fetch data, place
orders, import paper trades, create broker alerts, or connect to broker
execution.

## Status

```text
{payload["status"]}
```

## Next Action

```text
{payload["next_action"]}
```

## Contract

{markdown_table(contract)}

## Checks

{markdown_table(checks)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_data_flow_sentinel(args.output_dir)
    write_reports(args.output_dir, payload)
    print(f"Data flow sentinel: {payload['status']}")
    print(f"Saved data flow sentinel: {args.output_dir / 'data_flow_sentinel.md'}")
    if args.strict and payload["status"] == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
