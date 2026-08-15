"""Generate Project Gwala opening and end-of-day executive reports.

This script is intentionally report-only. It may run existing reconciliation
and accounting commands, but it does not change strategy, gate, risk, entry, or
exit rules.
"""

from __future__ import annotations

import argparse
import csv
from email.message import EmailMessage
import json
import os
import smtplib
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_root
from config.runtime_paths import runtime_data_path
from config.settings import STRATEGY
from indicators.session import add_session_columns, parse_clock
from notification_format import executive_report_notification
from reports.canonical_session_state import audit_report_consistency
from reports.canonical_session_state import build_canonical_session_state
from reports.canonical_session_state import write_canonical_session_state
from run_production_alert import internal_severity, send_mac_notification


OPENING_REPORT_VERSION = "opening-v1.0"
EOD_REPORT_VERSION = "eod-v1.1-canonical"
REPORTS_DIR = Path("logs/executive_reports")
PAPER_CSV = runtime_data_path("paper_trades.csv")
SAMPLES_CSV = runtime_data_path("paper_validation_samples.csv")
MACOS_DELIVERY_METHOD = "macos_notification"
EMAIL_DELIVERY_METHOD = "email_smtp"


@dataclass(frozen=True)
class EmailConfig:
    """SMTP settings loaded from environment variables."""

    host: str
    port: int
    username: str
    password: str
    from_addr: str
    to_addrs: tuple[str, ...]
    use_starttls: bool
    timeout_seconds: float


@dataclass(frozen=True)
class DeliveryResult:
    """Result of a local report delivery attempt."""

    attempted: bool
    success: bool
    method: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Project Gwala executive reports.")
    parser.add_argument("--report-type", choices=["opening", "eod"], required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("logs"))
    parser.add_argument("--data-dir", type=Path, default=runtime_data_root())
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--trading-date", default="", help="YYYY-MM-DD. Defaults to today's market date.")
    parser.add_argument("--deliver", action="store_true", help="Send the report through the configured local delivery path.")
    parser.add_argument("--deliver-only", action="store_true", help="Deliver an already generated report without rerunning accounting.")
    parser.add_argument("--force", action="store_true", help="Allow regenerating a report that already exists.")
    return parser.parse_args()


def now_et() -> datetime:
    return datetime.now(tz=MARKET_TZ)


def trading_date_from_args(value: str, moment: datetime | None = None) -> date:
    if value:
        return date.fromisoformat(value)
    return (moment or now_et()).date()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def truthy(value: object) -> bool:
    return text(value).lower() in {"true", "1", "yes", "y"}


def report_version(report_type: str) -> str:
    return OPENING_REPORT_VERSION if report_type == "opening" else EOD_REPORT_VERSION


def report_root(reports_dir: Path, trading_day: date) -> Path:
    return reports_dir / trading_day.isoformat()


def manifest_path(reports_dir: Path) -> Path:
    return reports_dir / "report_manifest.csv"


def delivery_log_path(reports_dir: Path) -> Path:
    return reports_dir / "delivery_log.csv"


def rows_from_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def append_csv_row(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            existing_fields = list(reader.fieldnames or [])
            existing_rows = list(reader)
        requested_fields = list(row.keys())
        if existing_fields and existing_fields != requested_fields:
            fields = existing_fields + [field for field in requested_fields if field not in existing_fields]
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                for existing_row in existing_rows:
                    writer.writerow(existing_row)
                writer.writerow({key: "" if row.get(key) is None else row.get(key, "") for key in fields})
            return
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow({key: "" if value is None else value for key, value in row.items()})


def duplicate_report(reports_dir: Path, dedupe_key: str) -> dict[str, str] | None:
    for row in rows_from_csv(manifest_path(reports_dir)):
        if row.get("dedupe_key") == dedupe_key:
            return row
    return None


def path_matches(saved: object, target: Path) -> bool:
    """Return True when a saved report path points to the same artifact."""

    saved_text = text(saved)
    if not saved_text:
        return False
    return Path(saved_text) == target or Path(saved_text).resolve() == target.resolve()


def final_report_already_delivered(
    payload: dict[str, Any],
    md_path: Path,
    reports_dir: Path,
    *,
    method: str | None = None,
) -> bool:
    """Return True after this exact FINAL report artifact was successfully delivered by a channel."""

    if payload.get("report_status") != "FINAL":
        return False
    for row in rows_from_csv(delivery_log_path(reports_dir)):
        if (
            row.get("trading_date") == payload.get("trading_date")
            and row.get("report_type") == payload.get("report_type")
            and row.get("report_version") == payload.get("report_version")
            and row.get("report_status") == payload.get("report_status")
            and (method is None or row.get("method") == method)
            and truthy(row.get("success"))
            and path_matches(row.get("report_md"), md_path)
        ):
            return True
    return False


def official_samples(samples: pd.DataFrame) -> pd.DataFrame:
    if samples.empty:
        return samples
    frame = samples.copy()
    if "counts_toward_30" in frame.columns:
        mask = frame["counts_toward_30"].map(truthy)
    else:
        mask = pd.Series([True] * len(frame), index=frame.index)
    if "invalid_for_validation" in frame.columns:
        mask &= ~frame["invalid_for_validation"].map(truthy)
    elif "invalidated" in frame.columns:
        mask &= ~frame["invalidated"].map(truthy)
    return frame[mask].copy()


def open_official_samples(samples: pd.DataFrame) -> pd.DataFrame:
    official = official_samples(samples)
    if official.empty:
        return official
    if "outcome_r" in official.columns:
        outcomes = pd.to_numeric(official["outcome_r"], errors="coerce")
        return official[outcomes.isna()].copy()
    if "outcome" not in official.columns:
        return official
    return official[official["outcome"].map(text).eq("")].copy()


def completed_official_samples(samples: pd.DataFrame) -> pd.DataFrame:
    official = official_samples(samples)
    if official.empty:
        return pd.DataFrame(columns=official.columns)
    if "outcome_r" in official.columns:
        outcomes = pd.to_numeric(official["outcome_r"], errors="coerce")
        completed = official[outcomes.notna()].copy()
        completed["realized_r"] = outcomes[outcomes.notna()]
        return completed
    if "outcome" not in official.columns:
        return pd.DataFrame(columns=official.columns)
    return official[official["outcome"].map(text).ne("")].copy()


def same_day_open_trades(samples: pd.DataFrame, trading_day: date) -> pd.DataFrame:
    open_samples = open_official_samples(samples)
    if open_samples.empty or "sample_date" not in open_samples.columns:
        return open_samples
    return open_samples[open_samples["sample_date"].map(text).eq(trading_day.isoformat())].copy()


def candle_path(output_dir: Path, symbol: str) -> Path:
    return output_dir / f"webull_{symbol}_M5_candles.csv"


def final_m5_available(output_dir: Path, symbol: str, trading_day: date) -> bool:
    path = candle_path(output_dir, symbol)
    candles = read_csv(path)
    if candles.empty:
        return False
    if "timestamp" in candles.columns:
        candles = candles.set_index(pd.to_datetime(candles["timestamp"], utc=True, errors="coerce"))
    else:
        candles = candles.set_index(pd.to_datetime(candles.index, utc=True, errors="coerce"))
    candles = candles[candles.index.notna()]
    if candles.empty:
        return False
    session = add_session_columns(candles, STRATEGY)
    force_exit = parse_clock(STRATEGY.force_exit_time)
    same_day = session["session_date"].astype(str).eq(trading_day.isoformat())
    regular = session["regular_session"].astype(bool)
    force_ready = pd.to_datetime(session["local_time"]).dt.time >= force_exit
    return bool((same_day & regular & force_ready).any())


def missing_final_m5_symbols(output_dir: Path, samples: pd.DataFrame, trading_day: date) -> list[str]:
    missing: list[str] = []
    for symbol in sorted({text(value).upper() for value in same_day_open_trades(samples, trading_day).get("symbol", []) if text(value)}):
        if not final_m5_available(output_dir, symbol, trading_day):
            missing.append(symbol)
    return missing


def command_sequence(output_dir: Path) -> list[list[str]]:
    python = sys.executable
    return [
        [python, "run_open_paper_monitor.py", "--output-dir", str(output_dir), "--confirm-updates"],
        [python, "run_paper_validation_sample_import.py", "--output-dir", str(output_dir)],
        [python, "run_daily_ship_report.py", "--output-dir", str(output_dir)],
        [python, "run_data_flow_sentinel.py", "--output-dir", str(output_dir)],
        [python, "run_system_state.py", "--output-dir", str(output_dir)],
    ]


def run_commands(commands: Iterable[list[str]], runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        completed = runner(command, check=False, capture_output=True, text=True)
        results.append(
            {
                "command": " ".join(command),
                "returncode": completed.returncode,
                "ok": completed.returncode == 0,
                "stderr": (completed.stderr or "")[-500:],
            }
        )
    return results


def status_from_artifacts(output_dir: Path) -> tuple[str, str]:
    heartbeat = read_json_or_empty(output_dir / "production_heartbeat.json")
    sentinel = read_json_or_empty(output_dir / "data_flow_sentinel.json")
    production = internal_severity(str(heartbeat.get("status", "YELLOW")))
    sentinel_status = text(sentinel.get("status")).lower()
    if sentinel_status in {"pass", "synced", "green"}:
        reporting = "GREEN"
    elif sentinel_status in {"warn", "warning", "watch"}:
        reporting = "WATCH"
    elif sentinel_status in {"blocked", "fail", "failed", "degraded"}:
        reporting = "DEGRADED"
    elif sentinel_status == "down":
        reporting = "DOWN"
    else:
        reporting = "WATCH"
    return production, reporting


def research_metrics(samples: pd.DataFrame) -> dict[str, Any]:
    completed = completed_official_samples(samples)
    total = len(official_samples(samples))
    if completed.empty:
        return {
            "running_win_rate": "N/A",
            "average_r": "N/A",
            "total_validation_trades": total,
            "opportunity_frequency": total,
            "strategy_breakdown": {},
            "market_regime_breakdown": {},
            "current_drawdown": "N/A",
        }
    r_values = pd.to_numeric(completed.get("realized_r", pd.Series(dtype=float)), errors="coerce").dropna()
    wins = int((r_values > 0).sum()) if not r_values.empty else 0
    return {
        "running_win_rate": f"{wins / len(r_values):.1%}" if len(r_values) else "N/A",
        "average_r": round(float(r_values.mean()), 2) if len(r_values) else "N/A",
        "total_validation_trades": total,
        "opportunity_frequency": total,
        "strategy_breakdown": completed.get("setup", pd.Series(dtype=str)).map(text).value_counts().to_dict(),
        "market_regime_breakdown": completed.get("market_regime", pd.Series(dtype=str)).map(text).value_counts().to_dict(),
        "current_drawdown": "N/A",
    }


def completed_trade_rows(samples: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for _, row in completed_official_samples(samples).iterrows():
        rows.append(
            {
                "symbol": text(row.get("symbol")),
                "strategy": text(row.get("setup")),
                "entry_time": text(row.get("signal_time")) or text(row.get("entry_time_et")) or text(row.get("entry_time")),
                "exit_time": text(row.get("exit_time_et")) or text(row.get("exit_time")),
                "direction": text(row.get("direction")),
                "result_r": text(row.get("realized_r")) or text(row.get("outcome_r")),
                "exit_reason": text(row.get("exit_reason")),
                "market_regime": text(row.get("market_regime")) or "N/A",
            }
        )
    return rows


def open_trade_rows(samples: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for _, row in open_official_samples(samples).iterrows():
        rows.append(
            {
                "symbol": text(row.get("symbol")),
                "strategy": text(row.get("setup")),
                "entry_time": text(row.get("signal_time")) or text(row.get("entry_time_et")) or text(row.get("entry_time")),
                "current_status": "open_pending_reconciliation",
                "unrealized_r": text(row.get("unrealized_r")) or "N/A",
                "exit_conditions_remaining": "Stop, target, or force-exit reconciliation.",
            }
        )
    return rows


def trading_activity(samples: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    ship = read_json_or_empty(output_dir / "daily_ship_report.json")
    official = official_samples(samples)
    completed = completed_official_samples(samples)
    open_trades = open_official_samples(samples)
    return {
        "candidates_detected": ship.get("scanner_candidates", "N/A"),
        "candidates_promoted": ship.get("sizing_candidates", "N/A"),
        "contract_gate_passes": ship.get("contract_gate_passes", "N/A"),
        "autonomous_paper_trades_opened": ship.get("open_paper_trades_created", "N/A"),
        "autonomous_paper_trades_closed": len(completed),
        "open_paper_trades": len(open_trades),
        "official_validation_trade_count": len(official),
    }


def metric_value(canonical: dict[str, Any], *path: str) -> Any:
    current: Any = canonical
    for key in path:
        if not isinstance(current, dict):
            return "UNKNOWN"
        current = current.get(key)
    if isinstance(current, dict) and "value" in current:
        return current.get("value")
    return current if current is not None else "UNKNOWN"


def validation_summary_from_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_rows": metric_value(canonical, "validation", "metrics", "total_rows"),
        "completed_official_observations": metric_value(canonical, "validation", "metrics", "valid_completed_observations"),
        "valid_open_observations": metric_value(canonical, "validation", "metrics", "valid_open_observations"),
        "invalid_excluded_rows": metric_value(canonical, "validation", "metrics", "invalid_excluded_rows"),
        "new_official_observations_today": metric_value(canonical, "validation", "metrics", "new_official_observations_today"),
        "new_completed_observations_today": metric_value(canonical, "validation", "metrics", "new_completed_observations_today"),
        "checkpoint": metric_value(canonical, "validation", "metrics", "checkpoint"),
        "today_r": metric_value(canonical, "validation", "metrics", "today_r"),
        "independent_opportunities": metric_value(canonical, "independent_opportunities"),
        "independent_opportunities_provenance": canonical.get("independent_opportunities", {}).get("provenance", "UNKNOWN"),
        "independent_opportunities_reason": canonical.get("independent_opportunities", {}).get("reason", ""),
    }


def trading_activity_from_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
    funnel = canonical.get("candidate_funnel", {})
    validation = validation_summary_from_canonical(canonical)
    return {
        "candidates_detected": metric_value(funnel, "scanner"),
        "candidates_promoted": metric_value(funnel, "size_ok"),
        "current_candle": metric_value(funnel, "current_candle"),
        "earlier_today": metric_value(funnel, "earlier_today"),
        "paper_gate_ready_final_snapshot": metric_value(funnel, "paper_gate_ready_final_snapshot"),
        "contract_gate_passes": metric_value(funnel, "contract_gate_pass"),
        "validation_preview_import_signal": metric_value(funnel, "validation_preview_import_signal"),
        "official_imports": metric_value(funnel, "official_imports"),
        "autonomous_paper_trades_opened": metric_value(funnel, "official_imports"),
        "autonomous_paper_trades_closed": validation["new_completed_observations_today"],
        "open_paper_trades": validation["valid_open_observations"],
        "official_validation_trade_count": validation["completed_official_observations"],
    }


def opening_range_breakout_from_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
    accumulated = canonical.get("orb", {}).get("accumulated_evidence", {})
    readiness = canonical.get("orb", {}).get("paper_watch_readiness", {})
    checks = readiness.get("checks", []) if isinstance(readiness, dict) else []
    by_check = {
        str(item.get("check", "")): item
        for item in checks
        if isinstance(item, dict)
    }

    def progress(check: str) -> dict[str, Any]:
        row = by_check.get(check, {})
        current = float(row.get("current", 0) or 0)
        required = float(row.get("required", 0) or 0)
        return {
            "current": current,
            "required": required,
            "remaining": max(required - current, 0.0),
            "status": text(row.get("status")) or "missing",
        }

    return {
        "strategy": "Opening Range Breakout",
        "strategy_id": "opening_range_breakout",
        "collection_mode": "shadow_only",
        "decision": readiness.get("decision", "UNKNOWN"),
        "next_blocker": readiness.get("next_blocker", "UNKNOWN"),
        "blocked_count": readiness.get("blocked_count", "UNKNOWN"),
        "accumulated_shadow_samples": metric_value(accumulated, "shadow_samples"),
        "accumulated_forward_observations": metric_value(accumulated, "forward_observations"),
        "accumulated_matured_shadow_outcomes": metric_value(accumulated, "matured_shadow_outcomes"),
        "accumulated_matured_forward_outcomes": metric_value(accumulated, "matured_forward_outcomes"),
        "shadow_samples": progress("Shadow samples logged"),
        "matured_shadow_outcomes": progress("Matured shadow outcomes"),
        "forward_observations": progress("Forward observations logged"),
        "matured_forward_outcomes": progress("Matured forward outcomes"),
        "shadow_average_r": progress("Shadow average R"),
        "forward_average_r": progress("Forward average R"),
        "paper_watch_readiness": readiness,
        "guardrail": "Shadow/forward accumulated evidence is separate from paper-watch readiness. No broker orders, alerts, or live execution.",
    }


def opening_range_breakout_evidence(output_dir: Path) -> dict[str, Any]:
    """Return shadow-only ORB evidence counts and paper-watch trigger distance."""

    gate = read_json_or_empty(output_dir / "opening_range_breakout_paper_watch_gate.json")
    checks = gate.get("checks", [])
    by_check = {
        str(item.get("check", "")): item
        for item in checks
        if isinstance(item, dict)
    }

    def progress(check: str) -> dict[str, Any]:
        row = by_check.get(check, {})
        current = float(row.get("current", 0) or 0)
        required = float(row.get("required", 0) or 0)
        return {
            "current": current,
            "required": required,
            "remaining": max(required - current, 0.0),
            "status": text(row.get("status")) or "missing",
        }

    return {
        "strategy": gate.get("strategy", "Opening Range Breakout"),
        "strategy_id": "opening_range_breakout",
        "collection_mode": "shadow_only",
        "decision": gate.get("decision", "missing"),
        "next_blocker": gate.get("next_blocker", "missing"),
        "blocked_count": int(gate.get("blocked_count", 0) or 0),
        "shadow_samples": progress("Shadow samples logged"),
        "matured_shadow_outcomes": progress("Matured shadow outcomes"),
        "forward_observations": progress("Forward observations logged"),
        "matured_forward_outcomes": progress("Matured forward outcomes"),
        "shadow_average_r": progress("Shadow average R"),
        "forward_average_r": progress("Forward average R"),
        "guardrail": gate.get(
            "guardrail",
            "Shadow-only evidence collection. No official Paper Gate, contract review, validation import, or live execution.",
        ),
    }


def morning_index_orb_manual_paper_watch(output_dir: Path) -> dict[str, Any]:
    """Return promoted Morning SPY/QQQ Long ORB Manual Paper-Watch progress."""

    payload = read_json_or_empty(output_dir / "morning_index_orb_manual_paper_watch.json")
    metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
    return {
        "strategy": payload.get("strategy_name", "Morning SPY/QQQ Long ORB"),
        "strategy_id": payload.get("strategy_id", "morning_index_orb_long"),
        "collection_mode": payload.get("collection_mode", "manual_paper_watch"),
        "status": payload.get("manual_paper_watch_status", "missing"),
        "candidates_detected_today": int(metrics.get("candidates_detected_today", 0) or 0),
        "operator_reviewed_today": int(metrics.get("operator_reviewed_today", 0) or 0),
        "approved_today": int(metrics.get("approved_today", 0) or 0),
        "rejected_today": int(metrics.get("rejected_today", 0) or 0),
        "contract_passed_today": int(metrics.get("contract_passed_today", 0) or 0),
        "contract_failed_today": int(metrics.get("contract_failed_today", 0) or 0),
        "paper_entries_opened": int(metrics.get("paper_entries_opened", 0) or 0),
        "trades_completed": int(metrics.get("trades_completed", 0) or 0),
        "open_count": int(metrics.get("open_count", 0) or 0),
        "average_r": metrics.get("average_r", 0.0),
        "completed_count": int(metrics.get("completed_count", 0) or 0),
        "checkpoint_trades": int(payload.get("checkpoint_trades", 20) or 20),
        "remaining_to_20": int(metrics.get("remaining_to_20", 20) or 20),
        "estimated_time_to_checkpoint": metrics.get("estimated_time_to_checkpoint", "missing"),
        "evidence_confidence": metrics.get("evidence_confidence_distribution", {}),
        "biggest_operational_bottleneck": payload.get("biggest_operational_bottleneck", "missing"),
        "guardrail": payload.get(
            "guardrail",
            "Morning Index ORB Manual Paper-Watch is paper-only and separate from VWAP validation.",
        ),
    }


def build_opening_payload(output_dir: Path, data_dir: Path, trading_day: date, generated_at: datetime) -> dict[str, Any]:
    samples = read_csv(data_dir / SAMPLES_CSV.name)
    production, reporting = status_from_artifacts(output_dir)
    open_trades = open_trade_rows(samples)
    blocking = []
    heartbeat = read_json_or_empty(output_dir / "production_heartbeat.json")
    if production in {"DEGRADED", "DOWN"}:
        blocking.append(text(heartbeat.get("reason")) or "Production heartbeat is not ready.")
    readiness = read_json_or_empty(output_dir / "readiness_check.json")
    if text(readiness.get("status")).lower() in {"fail", "blocked", "red"}:
        blocking.append(text(readiness.get("next_action")) or "Readiness check is blocking.")
    return {
        "report_type": "opening",
        "report_status": "FINAL",
        "trading_date": trading_day.isoformat(),
        "generated_at_et": generated_at.isoformat(),
        "report_version": OPENING_REPORT_VERSION,
        "production_status": production,
        "reporting_status": reporting,
        "business_impact": "YES" if production in {"DEGRADED", "DOWN"} else "NO",
        "operator_action_required": "YES" if blocking else "NO",
        "production_readiness": production,
        "data_freshness": read_json_or_empty(output_dir / "refresh_status.json"),
        "scanner_readiness": heartbeat.get("checks", []),
        "unresolved_open_trades": open_trades,
        "blocking_issues": blocking,
        "opening_range_breakout": opening_range_breakout_evidence(output_dir),
        "morning_index_orb_manual_paper_watch": morning_index_orb_manual_paper_watch(output_dir),
        "delivery_method": "macos_notification",
    }


def build_eod_payload(
    output_dir: Path,
    data_dir: Path,
    trading_day: date,
    generated_at: datetime,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    samples_path = data_dir / SAMPLES_CSV.name
    samples = read_csv(samples_path)
    missing_symbols = missing_final_m5_symbols(output_dir, samples, trading_day)
    if missing_symbols:
        production, reporting = status_from_artifacts(output_dir)
        return {
            "report_type": "eod",
            "report_status": "PENDING_RECONCILIATION",
            "trading_date": trading_day.isoformat(),
            "generated_at_et": generated_at.isoformat(),
            "report_version": EOD_REPORT_VERSION,
            "production_status": production,
            "reporting_status": "WATCH",
            "business_impact": "NO",
            "operator_action_required": "NO",
            "pending_reason": "Required end-of-day M5 data is not yet available.",
            "missing_final_m5_symbols": missing_symbols,
            "note": "No trade is labeled normally open overnight while final reconciliation is pending.",
            "commands_ran": [],
            "delivery_method": "macos_notification",
        }

    command_results = run_commands(command_sequence(output_dir), runner=runner)
    samples = read_csv(samples_path)
    production, reporting = status_from_artifacts(output_dir)
    if any(not item["ok"] for item in command_results):
        reporting = "DEGRADED"
    canonical = build_canonical_session_state(output_dir, data_dir, trading_day)
    canonical_path = write_canonical_session_state(canonical, output_dir, trading_day)
    if canonical.get("reporting", {}).get("status") in {"WATCH", "FAIL"} and reporting == "GREEN":
        reporting = "WATCH"
    metrics = research_metrics(samples)
    activity = trading_activity_from_canonical(canonical)
    legacy_activity = trading_activity(samples, output_dir)
    if activity.get("autonomous_paper_trades_closed") == "UNKNOWN":
        activity["autonomous_paper_trades_closed"] = legacy_activity["autonomous_paper_trades_closed"]
        activity["autonomous_paper_trades_closed_source"] = (
            "legacy compatibility fallback; canonical validation summary remains UNKNOWN when current schema is unavailable"
        )
    payload = {
        "report_type": "eod",
        "report_status": "FINAL",
        "trading_date": trading_day.isoformat(),
        "generated_at_et": generated_at.isoformat(),
        "report_version": EOD_REPORT_VERSION,
        "report_revision": "CANONICAL_RECONCILED",
        "canonical_session_state_path": str(canonical_path),
        "canonical_session_state": canonical,
        "production_status": production,
        "reporting_status": reporting,
        "business_impact": "NO" if production in {"GREEN", "WATCH"} else "YES",
        "operator_action_required": "YES" if reporting in {"DEGRADED", "DOWN"} or production in {"DEGRADED", "DOWN"} else "NO",
        "validation_summary": validation_summary_from_canonical(canonical),
        "trading_activity": activity,
        "completed_trades": completed_trade_rows(samples),
        "open_trades": open_trade_rows(samples),
        "research_metrics": metrics,
        "opening_range_breakout": opening_range_breakout_from_canonical(canonical),
        "morning_index_orb_manual_paper_watch": morning_index_orb_manual_paper_watch(output_dir),
        "operational_health": operational_health(output_dir, production, reporting),
        "engineering_assessment": engineering_assessment(production, reporting),
        "research_assessment": {
            "what_did_today_teach_us": "Official validation evidence is available only after completed trades are reconciled into accounting.",
            "assumptions_gained_evidence": "The reporting pipeline can separate production state from reporting reconciliation state.",
            "assumptions_lost_evidence": "N/A",
            "continue_to_observe": "Completed official paper trades, final M5 availability, and accounting synchronization.",
        },
        "tomorrow_readiness": {
            "production_ready": "YES" if production in {"GREEN", "WATCH"} else "NO",
            "reporting_ready": "YES" if reporting in {"GREEN", "WATCH"} else "NO",
            "required_actions_before_market_open": "None" if reporting in {"GREEN", "WATCH"} else "Review reporting blockers.",
            "operational_concerns": "None" if production in {"GREEN", "WATCH"} else "Production heartbeat requires review.",
        },
        "ceo_action_required": "None" if production in {"GREEN", "WATCH"} and reporting in {"GREEN", "WATCH"} else "Investigate Incident",
        "commands_ran": command_results,
        "delivery_method": "macos_notification",
    }
    payload["reporting_consistency"] = audit_report_consistency(canonical, eod_payload=payload)
    return payload


def operational_health(output_dir: Path, production: str, reporting: str) -> list[dict[str, str]]:
    sentinel = read_json_or_empty(output_dir / "data_flow_sentinel.json")
    heartbeat = read_json_or_empty(output_dir / "production_heartbeat.json")
    return [
        {"area": "Scanner", "status": production, "root_cause": text(heartbeat.get("reason")) or "N/A"},
        {"area": "Market Data Feed", "status": production, "root_cause": "See heartbeat and refresh artifacts."},
        {"area": "Candidate Ledger", "status": reporting, "root_cause": "See Data Flow Sentinel."},
        {"area": "Event Dispatcher", "status": reporting, "root_cause": "See Data Flow Sentinel."},
        {"area": "Contract Gate", "status": reporting, "root_cause": "See contract gate artifact."},
        {"area": "Option Chain Import", "status": reporting, "root_cause": "See option chain import artifact."},
        {"area": "Autonomous Lifecycle", "status": production, "root_cause": "See autonomous lifecycle artifact."},
        {"area": "Paper Trading Engine", "status": production, "root_cause": "See open paper monitor artifact."},
        {"area": "Accounting / Validation", "status": reporting, "root_cause": text(sentinel.get("next_action")) or "N/A"},
        {"area": "Data Flow Sentinel", "status": reporting, "root_cause": text(sentinel.get("summary")) or "N/A"},
    ]


def engineering_assessment(production: str, reporting: str) -> dict[str, str]:
    defect = "YES" if production in {"DEGRADED", "DOWN"} else "NO"
    reporting_defect = "YES" if reporting in {"DEGRADED", "DOWN"} else "NO"
    improvement = "YES" if defect == "YES" or reporting_defect == "YES" else "NO"
    task = "No engineering changes earned today."
    if improvement == "YES":
        task = "Review the single failing production or reporting component shown in Operational Health."
    return {
        "production_defect": defect,
        "reporting_defect": reporting_defect,
        "exactly_one_improvement": improvement,
        "highest_priority_task": task,
    }


def markdown_for_payload(payload: dict[str, Any]) -> str:
    if payload["report_type"] == "opening":
        return opening_markdown(payload)
    return eod_markdown(payload)


def opening_range_breakout_markdown(payload: dict[str, Any]) -> str:
    """Render ORB shadow-only evidence for executive reports."""

    orb = payload.get("opening_range_breakout", {})
    if not isinstance(orb, dict):
        orb = {}

    if "accumulated_shadow_samples" in orb:
        readiness = orb.get("paper_watch_readiness", {})
        lines = [
            f"- Strategy: {orb.get('strategy', 'Opening Range Breakout')}",
            f"- Collection Mode: {orb.get('collection_mode', 'shadow_only')}",
            f"- Accumulated Shadow Samples: {orb.get('accumulated_shadow_samples', 'UNKNOWN')}",
            f"- Accumulated Forward Observations: {orb.get('accumulated_forward_observations', 'UNKNOWN')}",
            f"- Matured Shadow Outcomes: {orb.get('accumulated_matured_shadow_outcomes', 'UNKNOWN')}",
            f"- Matured Forward Outcomes: {orb.get('accumulated_matured_forward_outcomes', 'UNKNOWN')}",
            f"- Paper-Watch Decision: {orb.get('decision', 'UNKNOWN')}",
            f"- Paper-Watch Next Blocker: {orb.get('next_blocker', 'UNKNOWN')}",
            f"- Paper-Watch Blocked Checks: {orb.get('blocked_count', 'UNKNOWN')}",
            f"- Paper-Watch Source: {readiness.get('source', 'UNKNOWN') if isinstance(readiness, dict) else 'UNKNOWN'}",
        ]
        for label, key in [
            ("Shadow Samples", "shadow_samples"),
            ("Matured Shadow Outcomes", "matured_shadow_outcomes"),
            ("Forward Observations", "forward_observations"),
            ("Matured Forward Outcomes", "matured_forward_outcomes"),
            ("Shadow Average R", "shadow_average_r"),
            ("Forward Average R", "forward_average_r"),
        ]:
            progress = orb.get(key, {})
            if isinstance(progress, dict) and progress.get("status") != "missing":
                lines.append(
                    f"- {label}: {progress.get('current', 0)} / {progress.get('required', 0)} "
                    f"(remaining {progress.get('remaining', 0)}, status {progress.get('status', 'missing')})"
                )
        lines.append(f"- Guardrail: {orb.get('guardrail', 'Shadow-only evidence collection.')}")
        return "\n".join(lines)

    def line(label: str, key: str) -> str:
        metric = orb.get(key, {})
        if not isinstance(metric, dict):
            metric = {}
        return (
            f"- {label}: {metric.get('current', 0)} / {metric.get('required', 0)} "
            f"(remaining {metric.get('remaining', 0)}, status {metric.get('status', 'missing')})"
        )

    return "\n".join(
        [
            f"- Strategy: {orb.get('strategy', 'Opening Range Breakout')}",
            f"- Collection Mode: {orb.get('collection_mode', 'shadow_only')}",
            f"- Paper-Watch Decision: {orb.get('decision', 'missing')}",
            f"- Next Trigger Blocker: {orb.get('next_blocker', 'missing')}",
            f"- Blocked Checks: {orb.get('blocked_count', 0)}",
            line("Shadow Samples", "shadow_samples"),
            line("Matured Shadow Outcomes", "matured_shadow_outcomes"),
            line("Forward Observations", "forward_observations"),
            line("Matured Forward Outcomes", "matured_forward_outcomes"),
            line("Shadow Average R", "shadow_average_r"),
            line("Forward Average R", "forward_average_r"),
            f"- Guardrail: {orb.get('guardrail', 'Shadow-only evidence collection.')}",
        ]
    )


def morning_index_orb_markdown(payload: dict[str, Any]) -> str:
    """Render promoted ORB Manual Paper-Watch progress for executive reports."""

    orb = payload.get("morning_index_orb_manual_paper_watch", {})
    if not isinstance(orb, dict):
        orb = {}
    return "\n".join(
        [
            f"- Strategy: {orb.get('strategy', 'Morning SPY/QQQ Long ORB')}",
            f"- Strategy ID: {orb.get('strategy_id', 'morning_index_orb_long')}",
            f"- Collection Mode: {orb.get('collection_mode', 'manual_paper_watch')}",
            f"- Status: {orb.get('status', 'missing')}",
            f"- Candidates Detected Today: {orb.get('candidates_detected_today', 0)}",
            f"- Operator Reviewed Today: {orb.get('operator_reviewed_today', 0)}",
            f"- Approved / Rejected: {orb.get('approved_today', 0)} / {orb.get('rejected_today', 0)}",
            f"- Contract Passed / Failed: {orb.get('contract_passed_today', 0)} / {orb.get('contract_failed_today', 0)}",
            f"- Paper Entries Opened: {orb.get('paper_entries_opened', 0)}",
            f"- Trades Completed: {orb.get('trades_completed', 0)}",
            f"- Current Open Trades: {orb.get('open_count', 0)}",
            f"- Average R: {orb.get('average_r', 0.0)}",
            f"- Completed Count: {orb.get('completed_count', 0)} / {orb.get('checkpoint_trades', 20)}",
            f"- Estimated Time to Checkpoint: {orb.get('estimated_time_to_checkpoint', 'missing')}",
            f"- Evidence Confidence: {orb.get('evidence_confidence', {})}",
            f"- Biggest Operational Bottleneck: {orb.get('biggest_operational_bottleneck', 'missing')}",
            f"- Guardrail: {orb.get('guardrail', 'Paper-only; separate from VWAP validation.')}",
        ]
    )


def opening_markdown(payload: dict[str, Any]) -> str:
    blocking = payload.get("blocking_issues") or ["None"]
    open_trades = payload.get("unresolved_open_trades") or []
    open_lines = ["- None"]
    if open_trades:
        open_lines = [
            f"- {row['symbol']} | {row['strategy']} | {row['entry_time']} | {row['current_status']}"
            for row in open_trades
        ]
    return f"""========================================
GWALA OPENING EXECUTIVE REPORT
========================================

Report Version: {payload["report_version"]}
Trading Date: {payload["trading_date"]}
Generated: {payload["generated_at_et"]}

## 1. Readiness
- Production Status: {payload["production_status"]}
- Reporting Status: {payload["reporting_status"]}
- Production Readiness: {payload["production_readiness"]}
- Business Impact: {payload["business_impact"]}
- Operator Action Required: {payload["operator_action_required"]}

## 2. Data Freshness
{json.dumps(payload.get("data_freshness", {}), indent=2)}

## 3. Scanner Readiness
{json.dumps(payload.get("scanner_readiness", []), indent=2)}

## 4. Unresolved Open Trades
{chr(10).join(open_lines)}

## 5. Blocking Issues
{chr(10).join(f"- {item}" for item in blocking)}

## 6. Opening Range Breakout Shadow Evidence
{opening_range_breakout_markdown(payload)}

## 7. Morning Index ORB Manual Paper-Watch
{morning_index_orb_markdown(payload)}
"""


def eod_markdown(payload: dict[str, Any]) -> str:
    if payload["report_status"] == "PENDING_RECONCILIATION":
        return f"""========================================
GWALA END-OF-DAY EXECUTIVE REPORT
========================================

Report Version: {payload["report_version"]}
Trading Date: {payload["trading_date"]}
Generated: {payload["generated_at_et"]}
Report Status: PENDING RECONCILIATION

Required end-of-day M5 data is not yet available for: {", ".join(payload["missing_final_m5_symbols"])}

No trade is labeled normally open overnight while final reconciliation is pending.

Production Status: {payload["production_status"]}
Reporting Status: {payload["reporting_status"]}
Business Impact: {payload["business_impact"]}
Operator Action Required: {payload["operator_action_required"]}
"""

    activity = payload["trading_activity"]
    validation = payload.get("validation_summary", {})
    completed = payload["completed_trades"] or []
    open_trades = payload["open_trades"] or []
    metrics = payload["research_metrics"]
    completed_lines = ["- None"]
    if completed:
        completed_lines = [
            (
                f"- {row['symbol']} | {row['strategy']} | Entry {row['entry_time']} | Exit {row['exit_time']} | "
                f"{row['direction']} | {row['result_r']}R | {row['exit_reason']} | {row['market_regime']}"
            )
            for row in completed
        ]
    open_lines = ["- None"]
    if open_trades:
        open_lines = [
            (
                f"- {row['symbol']} | {row['strategy']} | Entry {row['entry_time']} | {row['current_status']} | "
                f"Unrealized R {row['unrealized_r']} | {row['exit_conditions_remaining']}"
            )
            for row in open_trades
        ]
    health_lines = [
        (
            f"- {row['area']}: {row['status']} | Root cause: {row['root_cause']} | "
            f"Business impact: {'YES' if row['status'] in {'DEGRADED', 'DOWN'} else 'NO'} | "
            f"Auto-recovered: N/A | Operator action required: {'YES' if row['status'] in {'DEGRADED', 'DOWN'} else 'NO'}"
        )
        for row in payload["operational_health"]
    ]
    assessment = payload["engineering_assessment"]
    if assessment["exactly_one_improvement"] == "YES":
        highest_priority_answer = assessment["highest_priority_task"]
        no_engineering_answer = "N/A"
    else:
        highest_priority_answer = "N/A"
        no_engineering_answer = "No engineering changes earned today."
    research = payload["research_assessment"]
    ready = payload["tomorrow_readiness"]
    return f"""========================================
GWALA END-OF-DAY EXECUTIVE REPORT
========================================

## 1. Executive Summary
- Production Status: {payload["production_status"]}
- Reporting Status: {payload["reporting_status"]}
- Report Revision: {payload.get("report_revision", "ORIGINAL")}
- Canonical Session State: {payload.get("canonical_session_state_path", "N/A")}
- Trading Session Completed: Yes
- Business Impact Incidents: {payload["business_impact"]}
- Executive Summary (one paragraph): Project Gwala completed the session report from finalized reconciliation state and separated production health from reporting health.

## 2. Trading Activity
- Candidates Detected: {activity["candidates_detected"]}
- Candidates Promoted: {activity["candidates_promoted"]}
- Current-Candle Allowed: {activity.get("current_candle", "UNKNOWN")}
- Earlier-Today Allowed: {activity.get("earlier_today", "UNKNOWN")}
- Paper Gate Ready Final Snapshot: {activity.get("paper_gate_ready_final_snapshot", "UNKNOWN")}
- Contract Gate Passes: {activity["contract_gate_passes"]}
- Validation Preview / Import Signal: {activity.get("validation_preview_import_signal", "UNKNOWN")}
- Official Imports: {activity.get("official_imports", "UNKNOWN")}
- Autonomous Paper Trades Opened: {activity["autonomous_paper_trades_opened"]}
- Autonomous Paper Trades Closed: {activity["autonomous_paper_trades_closed"]}
- Open Paper Trades: {activity["open_paper_trades"]}
- Official Validation Trade Count: {activity["official_validation_trade_count"]}

## 3. Canonical Validation Summary
- Total Validation Ledger Rows: {validation.get("total_rows", "UNKNOWN")}
- Total Completed Official Strategy Observations: {validation.get("completed_official_observations", "UNKNOWN")}
- New Official Observations Today: {validation.get("new_official_observations_today", "UNKNOWN")}
- New Completed Official Observations Today: {validation.get("new_completed_observations_today", "UNKNOWN")}
- Valid Open Official Observations: {validation.get("valid_open_observations", "UNKNOWN")}
- Invalid / Excluded Rows: {validation.get("invalid_excluded_rows", "UNKNOWN")}
- Phase 2 Checkpoint: {validation.get("checkpoint", "UNKNOWN")}
- Independent Market Opportunities: {validation.get("independent_opportunities", "UNKNOWN")} ({validation.get("independent_opportunities_provenance", "UNKNOWN")})
- Independent Opportunity Provenance: {validation.get("independent_opportunities_reason", "UNKNOWN")}
- Today's Official R: {validation.get("today_r", "UNKNOWN")}R

## 4. Completed Trades
{chr(10).join(completed_lines)}

## 5. Open Trades
{chr(10).join(open_lines)}

## 6. Research Metrics
- Running Win Rate: {metrics["running_win_rate"]}
- Average R: {metrics["average_r"]}
- Total Validation Trades: {metrics["total_validation_trades"]}
- Opportunity Frequency: {metrics["opportunity_frequency"]}
- Strategy Breakdown: {metrics["strategy_breakdown"]}
- Market Regime Breakdown: {metrics["market_regime_breakdown"]}
- Current Drawdown: {metrics["current_drawdown"]}

## 7. Opening Range Breakout Shadow Evidence
{opening_range_breakout_markdown(payload)}

## 8. Morning Index ORB Manual Paper-Watch
{morning_index_orb_markdown(payload)}

## 9. Operational Health
{chr(10).join(health_lines)}

## 10. Engineering Assessment

1. Did today's evidence expose a production defect? {assessment["production_defect"]}
2. Did today's evidence expose a reporting defect? {assessment["reporting_defect"]}
3. Did today's evidence justify exactly ONE engineering improvement? {assessment["exactly_one_improvement"]}
4. If YES, describe the single highest-priority engineering task. {highest_priority_answer}
5. If NO, explicitly state:
   "{no_engineering_answer}"

## 11. Research Assessment

- What did today's session teach us? {research["what_did_today_teach_us"]}
- Which assumptions gained evidence? {research["assumptions_gained_evidence"]}
- Which assumptions lost evidence? {research["assumptions_lost_evidence"]}
- What should continue to be observed? {research["continue_to_observe"]}

## 12. Tomorrow's Readiness

- Production Ready: {ready["production_ready"]}
- Reporting Ready: {ready["reporting_ready"]}
- Required actions before market open: {ready["required_actions_before_market_open"]}
- Operational concerns: {ready["operational_concerns"]}

## 13. Reporting Consistency

- Status: {payload.get("reporting_consistency", {}).get("status", "UNKNOWN")}
- Failures: {payload.get("reporting_consistency", {}).get("failures", [])}

## 14. CEO Action Required

{payload["ceo_action_required"]}

Overall Confidence:
Medium
"""


def save_report(payload: dict[str, Any], reports_dir: Path, *, force: bool = False) -> tuple[Path, Path, bool]:
    trading_day = date.fromisoformat(payload["trading_date"])
    version = payload["report_version"]
    status = payload["report_status"]
    dedupe_key = f"{payload['report_type']}|{payload['trading_date']}|{version}|{status}"
    previous = duplicate_report(reports_dir, dedupe_key)
    if previous and not force:
        return Path(previous["report_json"]), Path(previous["report_md"]), False

    root = report_root(reports_dir, trading_day)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(payload["generated_at_et"]).strftime("%Y%m%dT%H%M%S%z")
    base = f"{payload['report_type']}_{payload['trading_date']}_{stamp}_{version}_{status.lower()}"
    json_path = root / f"{base}.json"
    md_path = root / f"{base}.md"
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    md_path.write_text(markdown_for_payload(payload), encoding="utf-8")
    append_csv_row(
        manifest_path(reports_dir),
        {
            "generated_at_et": payload["generated_at_et"],
            "trading_date": payload["trading_date"],
            "report_type": payload["report_type"],
            "report_version": version,
            "report_status": status,
            "production_status": payload["production_status"],
            "reporting_status": payload["reporting_status"],
            "report_json": json_path,
            "report_md": md_path,
            "dedupe_key": dedupe_key,
        },
    )
    return json_path, md_path, True


def report_severity(payload: dict[str, Any]) -> str:
    order = {"GREEN": 0, "WATCH": 1, "DEGRADED": 2, "DOWN": 3}
    production = payload.get("production_status", "WATCH")
    reporting = payload.get("reporting_status", "WATCH")
    return max([production, reporting], key=lambda value: order.get(value, 1))


def email_delivery_enabled() -> bool:
    return truthy(os.environ.get("GWALA_EMAIL_ENABLED", ""))


def email_config_from_env() -> EmailConfig:
    missing = [
        name
        for name in ("GWALA_SMTP_USERNAME", "GWALA_SMTP_PASSWORD", "GWALA_EMAIL_TO")
        if not text(os.environ.get(name))
    ]
    if missing:
        raise ValueError(f"Missing required email environment variables: {', '.join(missing)}")
    port_text = os.environ.get("GWALA_SMTP_PORT", "587")
    timeout_text = os.environ.get("GWALA_SMTP_TIMEOUT_SECONDS", "20")
    recipients = tuple(
        recipient.strip()
        for recipient in os.environ["GWALA_EMAIL_TO"].split(",")
        if recipient.strip()
    )
    if not recipients:
        raise ValueError("GWALA_EMAIL_TO must include at least one recipient.")
    return EmailConfig(
        host=os.environ.get("GWALA_SMTP_HOST", "smtp.gmail.com"),
        port=int(port_text),
        username=os.environ["GWALA_SMTP_USERNAME"],
        password=os.environ["GWALA_SMTP_PASSWORD"],
        from_addr=os.environ.get("GWALA_EMAIL_FROM", os.environ["GWALA_SMTP_USERNAME"]),
        to_addrs=recipients,
        use_starttls=truthy(os.environ.get("GWALA_SMTP_USE_STARTTLS", "true")),
        timeout_seconds=float(timeout_text),
    )


def report_type_label(payload: dict[str, Any]) -> str:
    return "Opening" if payload.get("report_type") == "opening" else "EOD"


def report_type_subtitle(payload: dict[str, Any]) -> str:
    return "Opening Executive Report" if payload.get("report_type") == "opening" else "End-of-Day Executive Report"


def email_subject(payload: dict[str, Any]) -> str:
    emoji_by_severity = {"GREEN": "🟢", "WATCH": "🟡", "DEGRADED": "🟠", "DOWN": "🔴"}
    severity = report_severity(payload)
    emoji = emoji_by_severity.get(severity, "🟡")
    return f"{emoji} GWALA — {severity} — {report_type_label(payload)} — {payload['trading_date']}"


def email_body(payload: dict[str, Any], md_path: Path) -> str:
    notification = executive_report_notification(payload)
    markdown = md_path.read_text(encoding="utf-8")
    return f"""Report type: {report_type_subtitle(payload)}
Production status: {payload["production_status"]}
Reporting status: {payload["reporting_status"]}
Executive takeaway: {notification.takeaway}
Operator action: {notification.operator_action}

{markdown}
"""


def send_email_report(payload: dict[str, Any], md_path: Path) -> DeliveryResult:
    config = email_config_from_env()
    message = EmailMessage()
    message["From"] = config.from_addr
    message["To"] = ", ".join(config.to_addrs)
    message["Subject"] = email_subject(payload)
    message.set_content(email_body(payload, md_path))

    with smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds) as smtp:
        if config.use_starttls:
            smtp.starttls()
        smtp.login(config.username, config.password)
        smtp.send_message(message)
    return DeliveryResult(True, True, EMAIL_DELIVERY_METHOD, "Email report delivered.")


def sanitized_delivery_message(message: str) -> str:
    secrets = [
        os.environ.get("GWALA_SMTP_PASSWORD", ""),
        os.environ.get("GWALA_SMTP_USERNAME", ""),
    ]
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized[:500]


def append_delivery_result(
    payload: dict[str, Any],
    md_path: Path,
    reports_dir: Path,
    result: DeliveryResult,
    *,
    title: str,
    subtitle: str,
    severity: str,
    operator_action: str,
) -> None:
    append_csv_row(
        delivery_log_path(reports_dir),
        {
            "attempted_at_et": now_et().isoformat(),
            "trading_date": payload["trading_date"],
            "report_type": payload["report_type"],
            "report_version": payload["report_version"],
            "report_status": payload["report_status"],
            "production_status": payload["production_status"],
            "reporting_status": payload["reporting_status"],
            "method": result.method,
            "success": result.success,
            "title": title,
            "subtitle": subtitle,
            "severity": severity,
            "operator_action": operator_action,
            "report_md": md_path,
            "message": sanitized_delivery_message(result.message),
        },
    )


def deliver_report(
    payload: dict[str, Any],
    md_path: Path,
    reports_dir: Path,
    *,
    notifier: Callable[[str, str], bool] = send_mac_notification,
    email_sender: Callable[[dict[str, Any], Path], DeliveryResult] = send_email_report,
) -> DeliveryResult:
    notification = executive_report_notification(payload)
    results: list[DeliveryResult] = []
    if not final_report_already_delivered(payload, md_path, reports_dir, method=MACOS_DELIVERY_METHOD):
        try:
            success = notifier(notification.title, notification.body[:180], notification.subtitle)
        except TypeError:
            success = notifier(notification.title, notification.body[:180])
        result = DeliveryResult(True, success, MACOS_DELIVERY_METHOD, notification.body)
        append_delivery_result(
            payload,
            md_path,
            reports_dir,
            result,
            title=notification.title,
            subtitle=notification.subtitle,
            severity=notification.severity,
            operator_action=notification.operator_action,
        )
        results.append(result)

    if email_delivery_enabled() and not final_report_already_delivered(
        payload,
        md_path,
        reports_dir,
        method=EMAIL_DELIVERY_METHOD,
    ):
        try:
            email_result = email_sender(payload, md_path)
        except Exception as exc:
            email_result = DeliveryResult(
                True,
                False,
                EMAIL_DELIVERY_METHOD,
                f"{type(exc).__name__}: {exc}",
            )
        append_delivery_result(
            payload,
            md_path,
            reports_dir,
            email_result,
            title=email_subject(payload),
            subtitle=report_type_subtitle(payload),
            severity=report_severity(payload),
            operator_action=notification.operator_action,
        )
        results.append(email_result)

    if not results:
        return DeliveryResult(False, True, "all_configured_channels", "Final report already delivered; no notification sent.")
    return DeliveryResult(
        True,
        all(result.success for result in results),
        "configured_channels",
        "; ".join(f"{result.method}: {result.success}" for result in results),
    )


def load_payload_for_delivery(reports_dir: Path, report_type: str, trading_day: date, version: str) -> tuple[dict[str, Any], Path]:
    rows = [
        row
        for row in rows_from_csv(manifest_path(reports_dir))
        if row.get("report_type") == report_type
        and row.get("trading_date") == trading_day.isoformat()
        and row.get("report_version") == version
    ]
    if not rows:
        raise SystemExit("No existing report found for delivery-only mode.")
    rows.sort(key=lambda row: row.get("generated_at_et", ""))
    latest = rows[-1]
    json_path = Path(latest["report_json"])
    payload = read_json_or_empty(json_path)
    if not payload:
        raise SystemExit(f"Could not read report payload: {json_path}")
    return payload, Path(latest["report_md"])


def load_existing_final_report(reports_dir: Path, report_type: str, trading_day: date, version: str) -> tuple[dict[str, Any], Path, Path] | None:
    """Return an existing final report before any idempotent accounting commands run."""

    dedupe_key = f"{report_type}|{trading_day.isoformat()}|{version}|FINAL"
    row = duplicate_report(reports_dir, dedupe_key)
    if not row:
        return None
    json_path = Path(row["report_json"])
    md_path = Path(row["report_md"])
    payload = read_json_or_empty(json_path)
    if not payload:
        return None
    return payload, json_path, md_path


def build_report(
    report_type: str,
    output_dir: Path,
    data_dir: Path,
    trading_day: date,
    generated_at: datetime,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if report_type == "opening":
        return build_opening_payload(output_dir, data_dir, trading_day, generated_at)
    return build_eod_payload(output_dir, data_dir, trading_day, generated_at, runner=runner)


def main() -> None:
    args = parse_args()
    generated_at = now_et()
    trading_day = trading_date_from_args(args.trading_date, generated_at)
    version = report_version(args.report_type)
    if args.deliver_only:
        payload, md_path = load_payload_for_delivery(args.reports_dir, args.report_type, trading_day, version)
        result = deliver_report(payload, md_path, args.reports_dir) if args.deliver else DeliveryResult(False, False, "", "")
        print(f"Executive report delivery success: {result.success}")
        return
    if not args.force:
        existing = load_existing_final_report(args.reports_dir, args.report_type, trading_day, version)
        if existing:
            payload, json_path, md_path = existing
            if args.deliver:
                deliver_report(payload, md_path, args.reports_dir)
            print(f"Executive report status: {payload['report_status']}")
            print("Report created: False")
            print(f"Saved JSON: {json_path}")
            print(f"Saved Markdown: {md_path}")
            return

    payload = build_report(args.report_type, args.output_dir, args.data_dir, trading_day, generated_at)
    json_path, md_path, created = save_report(payload, args.reports_dir, force=args.force)
    if args.deliver:
        deliver_report(payload, md_path, args.reports_dir)
    print(f"Executive report status: {payload['report_status']}")
    print(f"Report created: {created}")
    print(f"Saved JSON: {json_path}")
    print(f"Saved Markdown: {md_path}")


if __name__ == "__main__":
    main()
