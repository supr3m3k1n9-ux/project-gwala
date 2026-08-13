"""Run the local Project Gwala app shell.

This serves a small dashboard for the research and paper workflow. It reads
`logs/system_state.json`, serves static files from `app/`, and exposes local
status-only actions that rebuild readiness reports.

It does not fetch market data, import paper trades, place orders, create
alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import socketserver
import subprocess
import sys
import threading
import uuid
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from config.settings import STRATEGY
from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_root
from config.investment_narratives import INVESTMENT_NARRATIVES
from config.symbol_playbook import playbook_symbols, setup_labels_for_symbol
from config.strategy_registry import chart_marker_label_for_setup, strategy_vault_trade_logs
from data.candle_cache import preferred_candle_path
from data.market_data import load_candles_from_csv
from data.market_data_sources import latest_source_for
from indicators.session import add_opening_range, add_session_columns
from indicators.trend import add_core_indicators
from run_data_freshness_audit import build_audit as build_data_freshness_audit
from run_data_freshness_audit import write_audit as write_data_freshness_audit
from execution.paper_trader import (
    PAPER_ORDER_COLUMNS,
    filter_new_orders,
    orders_to_open_paper_trades,
    read_orders,
    write_open_paper_trades,
)
from run_near_miss_analytics import build_near_miss_payload, read_observations
from run_options_contract_gate import (
    CONTRACT_AUDIT_COLUMNS,
    CONTRACT_AUDIT_CSV,
    build_gate as build_options_contract_gate,
    contract_key,
    read_csv_or_empty as read_contract_csv_or_empty,
    sample_template_row,
)
from run_paper_gate_v2 import build_payload as build_paper_gate_payload
from run_paper_import import read_existing
from run_paper_validation_sample_import import build_import as build_validation_sample_import
from run_update_paper_trade import open_rows as open_paper_rows
from run_update_paper_trade import update_trade as update_paper_trade


PROJECT_DIR = Path(__file__).resolve().parent
APP_DIR = PROJECT_DIR / "app"
LOGS_DIR = PROJECT_DIR / "logs"
RUNTIME_DATA_DIR = runtime_data_root()
PAPER_CSV = RUNTIME_DATA_DIR / "paper_trades.csv"
PAPER_ORDERS_CSV = RUNTIME_DATA_DIR / "paper_orders.csv"
COMMAND_CENTER_APPROVALS_CSV = RUNTIME_DATA_DIR / "paper_command_center_approvals.csv"
STATUS_ACTION_LOCK = threading.Lock()
LIGHTWEIGHT_STATE_COMMANDS = [
    [sys.executable, "run_refresh_status.py"],
]
DEFAULT_BACKTEST_STARTING_EQUITY = 5_000.0
DEFAULT_BACKTEST_RISK_PER_TRADE_PCT = 0.005
STRATEGY_VAULT_TRADE_LOGS = strategy_vault_trade_logs()
SIMULATION_BUCKET_LABELS = {
    "Approved Playbook": {
        "source_category": "approved_historical_simulation",
        "evidence_tier": "approved_historical",
        "display_label": "Approved Historical",
        "disclaimer": "Approved playbook backtest rows. Research context only; not official paper trades.",
    },
    "Promotion Review": {
        "source_category": "promoted_research_simulation",
        "evidence_tier": "promoted_research",
        "display_label": "Promoted Research",
        "disclaimer": "Promotion-review backtest rows. Useful context; paper validation remains separate.",
    },
    "Strategy Vault Research": {
        "source_category": "strategy_vault_research_simulation",
        "evidence_tier": "research_backtest",
        "display_label": "Strategy Vault Research",
        "disclaimer": "Broad strategy-vault research backtest rows. Not paper-approved by itself.",
    },
}
TRADING_WORKSPACE_TIMEFRAMES = {
    "M1": "M1",
    "M5": "M5",
    "M15": "M15",
    "M30": "M30",
    "M60": "M60",
    "D": "D",
}
TRADING_SIGNAL_TIMEFRAMES = {"M5", "M30"}
TRADING_WORKSPACE_SYMBOLS = playbook_symbols("approved_plus_watch")
COMMAND_CENTER_SYMBOLS = ["SPY", "QQQ", "AAPL", "AMD", "META", "MSFT", "NVDA", "TSLA"]
WEBULL_PYTHON = PROJECT_DIR / ".venv-webull" / "bin" / "python"
ALLOWED_REPORTS = {
    "dashboard": "project_gwala_dashboard.md",
    "scanner": "daily_paper_signal_scanner.md",
    "observations": "forward_signal_observations.md",
    "near_misses": "near_miss_analytics.md",
    "observation_review": "forward_observation_review.md",
    "reconciliation": "observation_paper_reconciliation.md",
    "integrity": "candle_data_integrity.md",
    "refresh_audit": "market_refresh_audit.md",
    "setup_health": "setup_health.md",
    "paper_session": "paper_session_cycle.md",
    "current_candle_capture": "current_candle_capture.md",
    "paper_entry_packet": "paper_entry_packet.md",
    "paper_gate_v2": "paper_gate_v2.md",
    "options_contract_gate": "options_contract_gate.md",
    "paper_validation_sample_import": "paper_validation_sample_import.md",
    "daily_ship_report": "DAILY_SHIP_REPORT.md",
    "filter_rejection_report": "filter_rejection_report.md",
    "pre_entry_review": "pre_entry_review.md",
    "paper_execution": "local_paper_execution_simulator.md",
    "candidate_alerts": "paper_candidate_alerts.md",
    "forward_sample_queue": "forward_sample_queue.md",
    "almost_ready_breakout": "almost_ready_breakout.md",
    "market_sprint_mode": "market_sprint_mode.md",
    "probation_watch": "probation_watch.md",
    "post_scan_digest": "post_scan_digest.md",
    "forward_evidence": "forward_evidence.md",
    "candidate_aging": "candidate_aging.md",
    "no_trade_analysis": "no_trade_blocker_analysis.md",
    "shadow_samples": "shadow_samples.md",
    "open_paper_monitor": "open_paper_trade_monitor.md",
    "exit_audit": "paper_exit_audit.md",
    "readiness": "readiness_check.md",
    "checkpoint": "paper_validation_checkpoint.md",
    "refresh_status": "refresh_status.md",
    "data_freshness_audit": "data_freshness_audit.md",
    "provider_stability_audit": "provider_stability_audit.md",
    "provider_acceptance": "provider_acceptance.md",
    "accelerated_paper_validation": "accelerated_paper_validation.md",
    "morning_watchdog": "morning_run_watchdog.md",
    "automation_timeline": "daily_automation_timeline.md",
    "after_close_evidence_maturity": "after_close_evidence_maturity.md",
    "phase_milestones": "phase_milestones.md",
    "historical_bucket_sync": "historical_bucket_sync.md",
    "premarket": "premarket_verification.md",
    "setup_replay": "setup_replay.md",
    "strategy_vault": "strategy_vault.md",
    "market_regime_router": "market_regime_router.md",
    "controlled_universe_expansion": "controlled_universe_expansion.md",
    "vwap_mean_reversion": "vwap_mean_reversion.md",
    "vwap_mean_reversion_walk_forward": "vwap_mean_reversion_walk_forward.md",
    "vwap_mean_reversion_shadow_samples": "vwap_mean_reversion_shadow_samples.md",
    "vwap_mean_reversion_forward_observations": "vwap_mean_reversion_forward_observations.md",
    "vwap_mean_reversion_paper_watch_gate": "vwap_mean_reversion_paper_watch_gate.md",
    "gap_fill_fade": "gap_fill_fade.md",
    "gap_fill_fade_tightened_review": "gap_fill_fade_tightened_review.md",
    "gap_fill_fade_shadow_samples": "gap_fill_fade_shadow_samples.md",
    "gap_fill_fade_forward_observations": "gap_fill_fade_forward_observations.md",
    "gap_fill_fade_paper_watch_gate": "gap_fill_fade_paper_watch_gate.md",
    "vwap_reclaim_reject": "vwap_reclaim_reject.md",
    "vwap_reclaim_reject_walk_forward": "vwap_reclaim_reject_walk_forward.md",
    "vwap_reclaim_reject_shadow_samples": "vwap_reclaim_reject_shadow_samples.md",
    "vwap_reclaim_reject_evidence_maturity": "vwap_reclaim_reject_evidence_maturity.md",
    "opening_range_breakout": "opening_range_breakout.md",
    "opening_range_breakout_tightened_review": "opening_range_breakout_tightened_review.md",
    "opening_range_breakout_walk_forward_deepening": "opening_range_breakout_walk_forward_deepening.md",
    "opening_range_breakout_shadow_samples": "opening_range_breakout_shadow_samples.md",
    "opening_range_breakout_forward_observations": "opening_range_breakout_forward_observations.md",
    "opening_range_breakout_paper_watch_gate": "opening_range_breakout_paper_watch_gate.md",
    "trend_pullback_continuation": "trend_pullback_continuation.md",
    "trend_pullback_continuation_tightened_review": "trend_pullback_continuation_tightened_review.md",
    "trend_pullback_continuation_shadow_samples": "trend_pullback_continuation_shadow_samples.md",
    "trend_pullback_continuation_forward_observations": "trend_pullback_continuation_forward_observations.md",
    "trend_pullback_continuation_paper_watch_gate": "trend_pullback_continuation_paper_watch_gate.md",
    "opening_range_failure": "opening_range_failure.md",
    "opening_range_failure_tightened_review": "opening_range_failure_tightened_review.md",
    "opening_range_failure_walk_forward_deepening": "opening_range_failure_walk_forward_deepening.md",
    "opening_range_failure_shadow_samples": "opening_range_failure_shadow_samples.md",
    "opening_range_failure_forward_observations": "opening_range_failure_forward_observations.md",
    "opening_range_failure_paper_watch_gate": "opening_range_failure_paper_watch_gate.md",
    "strategy_evidence_accumulator": "strategy_evidence_accumulator.md",
    "paper_activation_rules": "paper_activation_rules.md",
    "strategy_walk_forward_matrix": "strategy_walk_forward_matrix.md",
    "research_strategy_tightened_review": "research_strategy_tightened_review.md",
    "strategy_backtest_coverage": "strategy_backtest_coverage.md",
    "validation_deepening_queue": "validation_deepening_queue.md",
    "strategy_triage": "strategy_triage.md",
    "strategy_improvement_plan": "strategy_improvement_plan.md",
    "feature_wiring_audit": "feature_wiring_audit.md",
    "research_confidence": "universe_expansion/research_confidence.md",
    "promotion_review": "promotion_review.md",
    "controlled_variant_review": "controlled_variant_review.md",
    "walk_forward_review": "walk_forward_review.md",
    "regime_review": "regime_review.md",
    "strategy_overlap_audit": "strategy_overlap_audit.md",
    "opening_range_relaxation": "opening_range_relaxation_review.md",
    "deep_research_confidence": "deeper_research/research_confidence.md",
    "deep_promotion_review": "deeper_research/promotion_review.md",
    "deep_controlled_variant_review": "deeper_research/controlled_variant_review.md",
    "deep_walk_forward_review": "deeper_research/walk_forward_review.md",
    "deep_regime_review": "deeper_research/regime_review.md",
    "system_state": "system_state.md",
    "dashboard_data_preflight": "dashboard_data_preflight.md",
}


def json_safe(value):
    """Return a JSON-safe copy of app data.

    Python's JSON encoder can emit Infinity/NaN by default, but browsers reject
    those values with JSON.parse. Keep the dashboard strict so one unusual
    metric cannot block every widget from loading.
    """

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def text_value(value: object, default: str = "") -> str:
    """Return stripped dashboard text without leaking pandas NaN."""

    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else default


def bool_value(value: object) -> bool:
    """Interpret common artifact booleans."""

    return text_value(value).lower() in {"1", "true", "yes", "y", "pass", "passed"}


def safe_read_json(path: Path) -> dict:
    """Read one JSON artifact, returning metadata instead of raising."""

    if not path.exists():
        return {"_available": False, "_path": str(path), "_error": "missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"_available": False, "_path": str(path), "_error": str(error)}
    if not isinstance(payload, dict):
        return {"_available": False, "_path": str(path), "_error": "not an object"}
    payload["_available"] = True
    payload["_path"] = str(path)
    return payload


def safe_read_csv(path: Path) -> pd.DataFrame:
    """Read one CSV artifact as strings without treating missing files as zero."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def artifact_state(path: Path) -> dict:
    """Return lightweight artifact availability for the Command Center."""

    if not path.exists():
        return {"status": "UNAVAILABLE", "path": str(path), "updated_at": None}
    updated = datetime.fromtimestamp(path.stat().st_mtime, tz=MARKET_TZ)
    return {
        "status": "AVAILABLE",
        "path": str(path),
        "updated_at": updated.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "updated_iso": updated.isoformat(),
    }


def current_trading_date(moment: datetime | None = None) -> date:
    """Return the market-local date used for daily dashboard counts."""

    return (moment or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ).date()


def official_validation_frame(samples_csv: Path | None = None) -> pd.DataFrame:
    """Return official non-invalid validation rows from the authoritative ledger."""

    path = samples_csv or RUNTIME_DATA_DIR / "paper_validation_samples.csv"
    samples = safe_read_csv(path)
    if samples.empty:
        return samples
    if "counts_toward_30" in samples.columns:
        official = samples["counts_toward_30"].map(bool_value)
    else:
        official = samples.get("sample_tier", pd.Series([""] * len(samples))).astype(str).str.upper().isin({"A", "B"})
    if "invalid_for_validation" in samples.columns:
        official &= ~samples["invalid_for_validation"].map(bool_value)
    return samples[official].copy()


def completed_official_validation_frame(samples_csv: Path | None = None) -> pd.DataFrame:
    """Return official validation rows with recorded R outcomes."""

    frame = official_validation_frame(samples_csv)
    if frame.empty or "outcome_r" not in frame.columns:
        return pd.DataFrame()
    numeric_r = pd.to_numeric(frame["outcome_r"], errors="coerce")
    completed = frame[numeric_r.notna()].copy()
    completed["_outcome_r"] = numeric_r[numeric_r.notna()].astype(float)
    time_columns = ["exit_time_et", "exit_time", "entry_time_et", "entry_time", "signal_time", "sample_date"]
    for column in time_columns:
        if column in completed.columns:
            parsed = pd.to_datetime(completed[column], errors="coerce", utc=True)
            if parsed.notna().any():
                completed["_sort_time"] = parsed
                break
    if "_sort_time" not in completed.columns:
        completed["_sort_time"] = pd.RangeIndex(len(completed))
    return completed.sort_values("_sort_time").reset_index(drop=True)


def max_drawdown_r(values: list[float]) -> float:
    """Return maximum peak-to-trough drawdown for cumulative R."""

    peak = 0.0
    drawdown = 0.0
    cumulative = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return round(drawdown, 2)


def founder_validation_scorecard(samples_csv: Path | None = None) -> dict:
    """Build the founder-facing official validation scorecard."""

    ledger_path = samples_csv or RUNTIME_DATA_DIR / "paper_validation_samples.csv"
    official = official_validation_frame(ledger_path)
    completed = completed_official_validation_frame(ledger_path)
    r_values = completed["_outcome_r"].astype(float).tolist() if not completed.empty else []
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    breakevens = [value for value in r_values if value == 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    cumulative = []
    running = 0.0
    for index, row in completed.iterrows():
        running += float(row["_outcome_r"])
        cumulative.append(
            {
                "trade": int(index) + 1,
                "symbol": text_value(row.get("symbol"), "--"),
                "setup": text_value(row.get("setup"), "--"),
                "r": round(float(row["_outcome_r"]), 2),
                "cumulative_r": round(running, 2),
            }
        )
    latest = cumulative[-1] if cumulative else {}
    return {
        "ledger_available": ledger_path.exists(),
        "ledger_path": str(ledger_path),
        "official_rows": int(len(official)),
        "completed_trades": int(len(completed)),
        "open_trades": max(int(len(official) - len(completed)), 0),
        "remaining_to_30": max(30 - int(len(completed)), 0),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate": round(len(wins) / len(r_values) * 100, 1) if r_values else None,
        "total_r": round(sum(r_values), 2) if r_values else 0.0,
        "expectancy_r": round(sum(r_values) / len(r_values), 3) if r_values else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_r": max_drawdown_r(r_values),
        "equity_curve": cumulative,
        "latest_completed_trade": latest,
    }


def count_or_unavailable(frame: pd.DataFrame, predicate=None) -> dict:
    """Return a count with explicit unavailable status."""

    if frame.empty:
        return {"status": "UNAVAILABLE", "count": None}
    if predicate is None:
        return {"status": "AVAILABLE", "count": int(len(frame))}
    try:
        return {"status": "AVAILABLE", "count": int(predicate(frame).sum())}
    except Exception as error:  # defensive for malformed artifacts
        return {"status": "PARTIAL", "count": None, "reason": str(error)}


def founder_today_funnel(logs_dir: Path | None = None, runtime_dir: Path | None = None) -> dict:
    """Return today's evidence funnel from saved artifacts without changing state."""

    logs = logs_dir or LOGS_DIR
    runtime = runtime_dir or RUNTIME_DATA_DIR
    today = current_trading_date().isoformat()
    scanner = safe_read_csv(logs / "daily_paper_signal_scanner.csv")
    sizing = safe_read_csv(logs / "position_sizing.csv")
    paper_gate = safe_read_csv(logs / "paper_gate_v2.csv")
    contract_gate = safe_read_csv(logs / "options_contract_gate.csv")
    samples = official_validation_frame(runtime / "paper_validation_samples.csv")
    capture = safe_read_json(logs / "current_candle_capture.json")
    import_preview = safe_read_json(logs / "paper_validation_sample_import.json")

    def scanner_status(frame: pd.DataFrame, value: str):
        column = "scanner_status" if "scanner_status" in frame.columns else "signal_status"
        return frame[column].astype(str).str.lower().eq(value)

    def today_rows(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        for column in ("sample_date", "trade_date", "session_date", "entry_date"):
            if column in frame.columns:
                return frame[frame[column].astype(str).str.startswith(today)].copy()
        return frame

    today_samples = today_rows(samples)
    today_completed = (
        today_samples[pd.to_numeric(today_samples.get("outcome_r", pd.Series([], dtype=str)), errors="coerce").notna()]
        if not today_samples.empty
        else today_samples
    )
    stages = [
        {"name": "Scanner", **count_or_unavailable(scanner)},
        {"name": "Allowed", **count_or_unavailable(scanner, lambda df: scanner_status(df, "allowed"))},
        {
            "name": "Current Candle",
            "status": "AVAILABLE" if capture.get("_available") else "UNAVAILABLE",
            "count": capture.get("current_candle_count") or capture.get("current_session_count"),
            "detail": capture.get("summary") or capture.get("_error", ""),
        },
        {"name": "Size OK", **count_or_unavailable(sizing, lambda df: df.get("sizing_status", "").astype(str).str.lower().eq("size_ok"))},
        {
            "name": "Paper Gate",
            **count_or_unavailable(
                paper_gate,
                lambda df: df.get("sample_status", "").astype(str).str.lower().eq("ready_for_validation_sample"),
            ),
        },
        {
            "name": "Contract Gate",
            **count_or_unavailable(
                contract_gate,
                lambda df: df.get("contract_gate_pass", "").map(bool_value),
            ),
        },
        {"name": "Official Validation", "status": "AVAILABLE" if not samples.empty else "UNAVAILABLE", "count": int(len(today_samples)) if not samples.empty else None},
    ]
    return {
        "trading_date": today,
        "stages": stages,
        "new_official_trades": int(len(today_samples)) if not samples.empty else None,
        "completed_trades": int(len(today_completed)) if not today_samples.empty else 0,
        "today_r": round(pd.to_numeric(today_completed.get("outcome_r", pd.Series(dtype=str)), errors="coerce").sum(), 2)
        if not today_completed.empty
        else 0.0,
        "artifacts": {
            "scanner": artifact_state(logs / "daily_paper_signal_scanner.csv"),
            "current_candle_capture": artifact_state(logs / "current_candle_capture.json"),
            "candidate_ledger": artifact_state(runtime / "candidate_window_ledger.csv"),
            "paper_gate": artifact_state(logs / "paper_gate_v2.csv"),
            "contract_gate": artifact_state(logs / "options_contract_gate.csv"),
            "validation_import_preview": {
                "status": "AVAILABLE" if import_preview.get("_available") else "UNAVAILABLE",
                "path": str(logs / "paper_validation_sample_import.json"),
            },
        },
    }


def founder_candidate_timeline(logs_dir: Path | None = None, symbol: str = "SPY") -> list[dict]:
    """Normalize visible candidate events for the Markets timeline."""

    logs = logs_dir or LOGS_DIR
    symbol = symbol.upper()
    events: list[dict] = []
    sources = [
        ("Scanner", logs / "daily_paper_signal_scanner.csv", "scanner_status"),
        ("Position Sizing", logs / "position_sizing.csv", "sizing_status"),
        ("Paper Gate", logs / "paper_gate_v2.csv", "sample_status"),
        ("Contract Gate", logs / "options_contract_gate.csv", "contract_gate_status"),
    ]
    for stage, path, status_column in sources:
        frame = safe_read_csv(path)
        if frame.empty or "symbol" not in frame.columns:
            continue
        for _, row in frame[frame["symbol"].astype(str).str.upper().eq(symbol)].tail(15).iterrows():
            timestamp = (
                text_value(row.get("signal_time_et"))
                or text_value(row.get("candidate_entry_et"))
                or text_value(row.get("entry_time_et"))
                or text_value(row.get("signal_time"))
            )
            events.append(
                {
                    "stage": stage,
                    "timestamp": timestamp or "latest",
                    "symbol": symbol,
                    "setup": text_value(row.get("setup"), "--"),
                    "direction": text_value(row.get("direction"), "--"),
                    "status": text_value(row.get(status_column), text_value(row.get("status"), "--")),
                    "reason": text_value(row.get("reason"), text_value(row.get("blocker"), "")),
                }
            )
    return events[-40:]


def founder_report_events(logs_dir: Path | None = None) -> list[dict]:
    """Return a normalized read-only executive/report inbox."""

    logs = logs_dir or LOGS_DIR
    events: list[dict] = []
    report_paths = sorted(
        list(logs.glob("executive_reports/**/*.md")) + list(logs.glob("*executive_report*.md")) + list(logs.glob("production_heartbeat.md")),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    seen: set[str] = set()
    for path in report_paths:
        if str(path) in seen or not path.exists():
            continue
        seen.add(str(path))
        updated = datetime.fromtimestamp(path.stat().st_mtime, tz=MARKET_TZ)
        name = path.stem.replace("_", " ").replace("-", " ").title()
        category = "Executive" if "executive" in str(path).lower() else "Alerts"
        try:
            content = path.read_text(encoding="utf-8")
            lines = [line.strip("# ").strip() for line in content.splitlines() if line.strip()]
        except OSError:
            content = ""
            lines = []
        events.append(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, str(path))),
                "timestamp": updated.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "timestamp_iso": updated.isoformat(),
                "category": category,
                "importance": "Important" if any(word in " ".join(lines[:12]).upper() for word in ("WATCH", "FAIL", "RED", "ACTION")) else "Normal",
                "title": name,
                "summary": lines[1] if len(lines) > 1 else (lines[0] if lines else "Report archived."),
                "path": str(path),
                "content": content[:24000],
            }
        )
    heartbeat = safe_read_json(logs / "production_heartbeat.json")
    if heartbeat.get("_available"):
        events.insert(
            0,
            {
                "id": "production-heartbeat",
                "timestamp": text_value(heartbeat.get("generated_at_et"), "latest"),
                "category": "Alerts",
                "importance": "Important" if text_value(heartbeat.get("status")).upper() not in {"GREEN", "PASS"} else "Normal",
                "title": "Production Health",
                "summary": f"Status {text_value(heartbeat.get('status'), 'UNKNOWN')}",
                "path": str(logs / "production_heartbeat.json"),
                "content": json.dumps({k: v for k, v in heartbeat.items() if k != "_path"}, indent=2)[:8000],
            },
        )
    return events[:60]


def founder_research_payload(samples_csv: Path | None = None) -> dict:
    """Return strategy portfolio state without creating new strategy decisions."""

    scorecard = founder_validation_scorecard(samples_csv)
    return {
        "primary": {
            "name": "VWAP official paper validation",
            "allocation": "Primary",
            "status": "CONTINUE",
            "evidence": f"{scorecard['completed_trades']} / 30 completed official paper trades",
            "next_trigger": f"{scorecard['remaining_to_30']} completed trade(s) to checkpoint",
        },
        "secondary": {
            "name": "Morning SPY/QQQ Long ORB",
            "allocation": "Secondary",
            "status": "WATCH",
            "evidence": "Manual Paper-Watch lane. Evidence remains separate from VWAP.",
            "next_trigger": "Awaiting Manual Paper-Watch completed outcomes.",
        },
        "placeholders": [
            {"name": "Phase 3 Tiny Live", "status": "Awaiting Phase 3 Evidence"},
            {"name": "Capital Scaling", "status": "Awaiting Phase 3 Evidence"},
        ],
    }


def founder_system_payload(logs_dir: Path | None = None) -> dict:
    """Return infrastructure status from existing authoritative artifacts."""

    logs = logs_dir or LOGS_DIR
    freshness_path = logs / "data_freshness_audit.json"
    if not freshness_path.exists():
        try:
            write_data_freshness_audit(build_data_freshness_audit(RUNTIME_DATA_DIR), logs)
        except Exception:
            pass
    freshness = safe_read_json(logs / "data_freshness_audit.json")
    artifacts = {
        "Production Health": safe_read_json(logs / "production_heartbeat.json"),
        "Data Freshness": freshness,
        "Host systemd": safe_read_json(logs / "host_systemd_health.json"),
        "Docker": safe_read_json(logs / "host_docker_health.json"),
        "Host Security": safe_read_json(logs / "host_security_health.json"),
        "Runtime Assurance": safe_read_json(logs / "continuous_assurance.json"),
        "Dashboard Preflight": safe_read_json(logs / "dashboard_data_preflight.json"),
        "Autonomous Workflow": safe_read_json(logs / "autonomous_paper_workflow_status.json"),
    }
    cards = []
    for label, payload in artifacts.items():
        status = text_value(payload.get("status"), "UNAVAILABLE").upper() if payload.get("_available") else "UNAVAILABLE"
        if status == "GREEN":
            status = "PASS"
        if status == "YELLOW":
            status = "WATCH"
        if status == "RED":
            status = "FAIL"
        cards.append(
            {
                "name": label,
                "status": status,
                "detail": text_value(payload.get("red_reason"), text_value(payload.get("message"), text_value(payload.get("_error"), "No current artifact."))),
                "path": str(payload.get("_path", "")),
            }
        )
    return {
        "cards": cards,
        "data_freshness": freshness if freshness.get("_available") else {},
        "deployment_commit": text_value(safe_read_json(logs / "production_readiness.json").get("commit"), ""),
        "logs_dir": str(logs),
        "runtime_data_dir": str(RUNTIME_DATA_DIR),
    }


def founder_command_center_payload() -> dict:
    """Build the read-only founder-facing Command Center V1 payload."""

    validation = founder_validation_scorecard()
    funnel = founder_today_funnel()
    system = founder_system_payload()
    production_status = next((card["status"] for card in system["cards"] if card["name"] == "Production Health"), "UNAVAILABLE")
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "overview": {
            "production": production_status,
            "evidence": "CLEAN" if validation["completed_trades"] >= 30 else "PARTIAL",
            "market_state": text_value(safe_read_json(LOGS_DIR / "autonomous_paper_workflow_status.json").get("decision"), "UNKNOWN"),
            "current_phase": "Phase 2: Discover first commercially viable edge",
            "official_validation": f"{validation['completed_trades']} / 30",
            "last_autonomous_run": text_value(safe_read_json(LOGS_DIR / "autonomous_paper_workflow_status.json").get("generated_at_et"), "UNAVAILABLE"),
            "next_autonomous_run": "Systemd timer cadence",
        },
        "today": funnel,
        "validation": validation,
        "markets": {
            "symbols": COMMAND_CENTER_SYMBOLS,
            "primary_symbols": ["SPY", "QQQ"],
            "timeframes": list(TRADING_WORKSPACE_TIMEFRAMES.keys()),
        },
        "inbox": {"events": founder_report_events()},
        "research": founder_research_payload(),
        "system": system,
        "guardrail": "Read-only observability. No trading controls, no broker orders, and no evidence mutations.",
    }


def founder_command_center_chart_payload(symbol: str = "SPY", timeframe: str = "M30") -> dict:
    """Return Command Center chart plus candidate timeline."""

    payload = build_trading_workspace_data(LOGS_DIR, symbol, timeframe)
    payload["timeline"] = founder_candidate_timeline(LOGS_DIR, symbol)
    return payload


def command_center_sample_key(row: dict | pd.Series) -> str:
    """Return the stable key used across chart approval, contract review, and entry."""

    template = sample_template_row(row)
    return "|".join(contract_key(template))


def read_command_center_approvals() -> pd.DataFrame:
    """Read local operator chart approvals."""

    columns = [
        "sample_key",
        "approved_at_et",
        "decision",
        "symbol",
        "setup",
        "direction",
        "sample_tier",
        "candidate_entry_et",
        "notes",
    ]
    if not COMMAND_CENTER_APPROVALS_CSV.exists():
        return pd.DataFrame(columns=columns)
    try:
        approvals = pd.read_csv(COMMAND_CENTER_APPROVALS_CSV)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in approvals.columns:
            approvals[column] = ""
    return approvals[columns]


def latest_command_center_approval(sample_key: str) -> dict:
    """Return the latest chart-review decision for one sample."""

    approvals = read_command_center_approvals()
    if approvals.empty:
        return {}
    matches = approvals[approvals["sample_key"].astype(str) == sample_key]
    if matches.empty:
        return {}
    return matches.iloc[-1].fillna("").to_dict()


def append_command_center_approval(sample: dict, decision: str, notes: str = "") -> dict:
    """Record an operator chart approval or rejection without changing gates."""

    key = command_center_sample_key(sample)
    row = {
        "sample_key": key,
        "approved_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "decision": decision,
        "symbol": str(sample.get("symbol", "")).upper(),
        "setup": str(sample.get("setup", "")),
        "direction": str(sample.get("direction", "")).lower(),
        "sample_tier": str(sample.get("sample_tier", "")),
        "candidate_entry_et": str(sample.get("candidate_entry_et", sample.get("latest_signal_et", ""))),
        "notes": notes,
    }
    existing = read_command_center_approvals()
    COMMAND_CENTER_APPROVALS_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([existing, pd.DataFrame([row])], ignore_index=True).to_csv(COMMAND_CENTER_APPROVALS_CSV, index=False)
    return row


def command_center_ready_samples() -> list[dict]:
    """Return current Paper Gate survivor rows using the existing Paper Gate."""

    payload = build_paper_gate_payload(
        output_dir=LOGS_DIR,
        scanner_csv=LOGS_DIR / "daily_paper_signal_scanner.csv",
        samples_csv=RUNTIME_DATA_DIR / "paper_validation_samples.csv",
    )
    samples = payload.get("ready_samples", [])
    return samples if isinstance(samples, list) else []


def command_center_sample_by_key(sample_key: str) -> dict:
    """Find one current Paper Gate survivor by key."""

    for sample in command_center_ready_samples():
        if command_center_sample_key(sample) == sample_key:
            return sample
    raise ValueError("That Paper Gate survivor is no longer ready. Refresh the workflow and review the current candidate.")


def command_center_contract_row(sample_key: str) -> dict:
    """Return the current Contract Gate row for a sample key."""

    gate = build_options_contract_gate(output_dir=LOGS_DIR, contract_audit_csv=CONTRACT_AUDIT_CSV)
    for row in gate.get("rows", []):
        if command_center_sample_key(row) == sample_key:
            return row
    return {}


def command_center_option_chain_state(sample: dict) -> dict:
    """Return the expected local option-chain CSV state for one sample."""

    symbol = str(sample.get("symbol", "")).strip().upper()
    path = RUNTIME_DATA_DIR / "options_chains" / f"{symbol}.csv"
    exists = path.exists() and path.stat().st_size > 0
    return {
        "symbol": symbol,
        "path": str(path.relative_to(PROJECT_DIR)),
        "exists": exists,
        "status": "available" if exists else "missing",
        "message": (
            f"Option-chain CSV available: {path.relative_to(PROJECT_DIR)}"
            if exists
            else f"Missing {symbol} option-chain CSV: {path.relative_to(PROJECT_DIR)}"
        ),
    }


def command_center_payload() -> dict:
    """Build the four-decision Paper Trade Command Center payload."""

    samples = command_center_ready_samples()
    gate = build_options_contract_gate(output_dir=LOGS_DIR, contract_audit_csv=CONTRACT_AUDIT_CSV)
    gate_rows = {command_center_sample_key(row): row for row in gate.get("rows", [])}
    approvals = read_command_center_approvals()
    latest_approvals = {}
    if not approvals.empty:
        for _, row in approvals.iterrows():
            latest_approvals[str(row.get("sample_key", ""))] = row.fillna("").to_dict()

    candidates = []
    for sample in samples:
        key = command_center_sample_key(sample)
        contract = gate_rows.get(key, {})
        approval = latest_approvals.get(key, {})
        option_chain = command_center_option_chain_state(sample)
        chart_approved = approval.get("decision") == "approved"
        contract_passed = bool(contract.get("contract_gate_pass", False))
        if not chart_approved:
            status = "waiting_for_chart_review"
            next_action = "Approve or reject the chart plan."
        elif not contract:
            status = "waiting_for_contract_review"
            next_action = "Enter contract details and run Contract Gate."
        elif not contract_passed:
            status = "waiting_for_contract_review"
            next_action = contract.get("contract_gate_reason") or "Contract has not passed."
        else:
            status = "ready_for_paper_entry"
            next_action = "Confirm official paper trade."
        candidates.append(
            {
                "sample_key": key,
                "status": status,
                "next_action": next_action,
                "chart_approval": approval,
                "contract": contract,
                "option_chain_csv": option_chain,
                **sample,
            }
        )

    trades = read_existing(PAPER_CSV)
    open_trades = open_paper_rows(trades)
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "open_trade_count": int(len(open_trades)),
        "open_trades": open_trades.fillna("").to_dict("records"),
        "contract_gate_status": gate.get("status", "missing"),
        "guardrail": (
            "Workflow consolidation only. Paper Gate, chart approval, Contract Gate, paper entry confirmation, "
            "and exit confirmation remain required. No broker orders are placed."
        ),
    }


def append_contract_audit_row(sample: dict, payload: dict) -> dict:
    """Write one operator-selected contract row, then let Contract Gate judge it."""

    template = sample_template_row(sample)
    allowed_fields = set(CONTRACT_AUDIT_COLUMNS)
    contract_values = {column: payload.get(column, template.get(column, "")) for column in CONTRACT_AUDIT_COLUMNS}
    for key in CONTRACT_AUDIT_COLUMNS[:7]:
        value = template.get(key, "")
        contract_values[key] = value
    for key, value in payload.items():
        if key in allowed_fields and key not in template:
            contract_values[key] = value
    audit = read_contract_csv_or_empty(CONTRACT_AUDIT_CSV, CONTRACT_AUDIT_COLUMNS)
    CONTRACT_AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([audit, pd.DataFrame([contract_values], columns=CONTRACT_AUDIT_COLUMNS)], ignore_index=True).to_csv(
        CONTRACT_AUDIT_CSV,
        index=False,
    )
    return contract_values


def paper_order_from_contract_sample(sample: dict, contract: dict) -> pd.DataFrame:
    """Convert a Contract Gate-passed sample into one local paper order row."""

    now = datetime.now(MARKET_TZ)
    candidate_time = pd.to_datetime(sample.get("candidate_entry_et") or sample.get("latest_signal_et"), errors="coerce")
    if pd.isna(candidate_time):
        raise ValueError("Candidate entry time is missing; cannot create a paper order.")
    if candidate_time.tzinfo is None:
        candidate_time = candidate_time.tz_localize(MARKET_TZ)
    else:
        candidate_time = candidate_time.tz_convert(MARKET_TZ)

    row = {
        "paper_order_id": f"PG-PAPER-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "created_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "trade_date": candidate_time.date().isoformat(),
        "entry_time_et": candidate_time.strftime("%H:%M"),
        "symbol": str(sample.get("symbol", "")).upper(),
        "setup": sample.get("setup", ""),
        "direction": str(sample.get("direction", "")).lower(),
        "side": "BUY" if str(sample.get("direction", "")).lower() == "long" else "SELL_SHORT",
        "order_type": "LOCAL_LIMIT_SIM",
        "limit_price": sample.get("planned_entry", ""),
        "stop_price": sample.get("planned_stop", ""),
        "target_price": sample.get("planned_target", ""),
        "shares": int(float(sample.get("suggested_shares", 0) or 0)),
        "vehicle": "options",
        "risk_tier": str(sample.get("sample_tier", "")).upper(),
        "planned_option_premium": contract.get("premium", ""),
        "status": "local_paper_filled",
        "source": "paper_command_center_contract_pass",
        "notes": (
            f"Official paper workflow; contract={contract.get('contract_symbol', '')}; "
            "local paper simulation only; no broker order was sent."
        ),
    }
    return pd.DataFrame([row], columns=PAPER_ORDER_COLUMNS)


def workflow_python() -> str:
    """Use the provider SDK environment for market-data refreshes when it exists."""

    if WEBULL_PYTHON.exists():
        return str(WEBULL_PYTHON)
    return sys.executable


def lightweight_state_commands() -> list[list[str]]:
    """Return the local-only commands needed for one coherent dashboard state."""

    commands = list(LIGHTWEIGHT_STATE_COMMANDS)
    research_dir = LOGS_DIR / "universe_expansion"
    research_inputs = [
        research_dir / "best_plus_market_watchlist_backtest_summary.csv",
        research_dir / "setup_b_watchlist_backtest_summary.csv",
    ]
    if research_dir.exists() and any(path.exists() for path in research_inputs):
        commands.extend(
            [
                [sys.executable, "run_research_confidence.py", "--output-dir", str(research_dir)],
                [sys.executable, "run_promotion_review.py", "--output-dir", str(LOGS_DIR), "--research-dir", str(research_dir)],
            ]
        )
    commands.append([sys.executable, "run_phase_milestones.py"])
    commands.append([sys.executable, "run_historical_bucket_sync.py"])
    commands.append([sys.executable, "run_system_state.py"])
    commands.append([sys.executable, "run_provider_stability_audit.py"])
    commands.append([sys.executable, "run_paper_entry_packet.py"])
    commands.append([sys.executable, "run_paper_gate_v2.py"])
    commands.append([sys.executable, "run_options_chain_review.py", "--tier", "A", "--write-audit"])
    commands.append([sys.executable, "run_options_contract_gate.py"])
    commands.append([sys.executable, "run_paper_validation_sample_import.py"])
    commands.append([sys.executable, "run_daily_ship_report.py"])
    commands.append([sys.executable, "run_system_state.py"])
    commands.append([sys.executable, "run_dashboard_data_preflight.py"])
    commands.append([sys.executable, "run_data_flow_sentinel.py"])
    commands.append([sys.executable, "run_controlled_universe_expansion.py"])
    commands.append([sys.executable, "run_probation_watch.py"])
    commands.append([sys.executable, "run_market_sprint_mode.py"])
    commands.append([sys.executable, "run_system_state.py"])
    return commands


def saved_candle_source_label(logs_dir: Path, symbol: str, timeframe: str, context: str) -> str:
    """Return a user-facing source label for saved candle files."""

    source = latest_source_for(logs_dir / "market_data_sources.csv", symbol, timeframe)
    provider = str(source.get("provider", "market-data")).strip() or "market-data"
    return f"Saved {provider.title()} {timeframe} {context} candles"


def app_number(value: object) -> float | None:
    """Convert chart values to clean JSON numbers."""

    if pd.isna(value):
        return None
    return round(float(value), 4)


def app_positive_float(value: object, default: float, maximum: float | None = None) -> float:
    """Read a positive app input while keeping unsafe values at a sane default."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    if maximum is not None:
        return min(number, maximum)
    return number


def trade_sort_millis(trades: pd.DataFrame) -> pd.Series:
    """Return stable UTC millisecond timestamps for browser-side sorting."""

    if trades.empty:
        return pd.Series(dtype="Int64")

    if "entry_time" in trades.columns:
        timestamps = pd.to_datetime(trades["entry_time"], errors="coerce", utc=True)
    else:
        timestamps = pd.Series([pd.NaT] * len(trades), index=trades.index)

    if "exit_time" in trades.columns:
        exit_timestamps = pd.to_datetime(trades["exit_time"], errors="coerce", utc=True)
        timestamps = timestamps.fillna(exit_timestamps)

    return timestamps.map(lambda value: int(value.timestamp() * 1000) if pd.notna(value) else 0).astype("Int64")


def add_retro_account_simulation(
    trades: pd.DataFrame,
    starting_equity: float = DEFAULT_BACKTEST_STARTING_EQUITY,
    risk_per_trade_pct: float = DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
    risk_pct_column: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Apply a simple paper-account model to historical R-multiple trades."""

    summary = {
        "starting_equity": round(starting_equity, 2),
        "ending_equity": round(starting_equity, 2),
        "total_pnl": 0.0,
        "return_pct": 0.0,
        "max_drawdown": 0.0,
        "risk_per_trade_pct": round(risk_per_trade_pct, 6),
        "average_risk_per_trade_pct": round(risk_per_trade_pct, 6),
        "max_risk_per_trade_pct": round(risk_per_trade_pct, 6),
    }
    if trades.empty or "r_result" not in trades.columns:
        return trades.copy(), summary

    simulated = trades.copy()
    if "entry_time" in simulated.columns:
        simulated = simulated.sort_values("entry_time")

    equity = starting_equity
    peak_equity = starting_equity
    max_drawdown = 0.0
    equity_before: list[float] = []
    risk_dollars: list[float] = []
    pnl_dollars: list[float] = []
    equity_after: list[float] = []
    r_results = pd.to_numeric(simulated["r_result"], errors="coerce").fillna(0.0)

    risk_pcts = (
        pd.to_numeric(simulated[risk_pct_column], errors="coerce").fillna(risk_per_trade_pct).clip(lower=0.0001, upper=0.10)
        if risk_pct_column and risk_pct_column in simulated.columns
        else pd.Series([risk_per_trade_pct] * len(simulated), index=simulated.index)
    )
    applied_risk_pct: list[float] = []

    for r_result, trade_risk_pct in zip(r_results, risk_pcts):
        trade_risk = equity * float(trade_risk_pct)
        trade_pnl = float(r_result) * trade_risk
        applied_risk_pct.append(round(float(trade_risk_pct), 6))
        equity_before.append(round(equity, 2))
        risk_dollars.append(round(trade_risk, 2))
        pnl_dollars.append(round(trade_pnl, 2))
        equity = equity + trade_pnl
        equity_after.append(round(equity, 2))
        peak_equity = max(peak_equity, equity)
        max_drawdown = min(max_drawdown, equity - peak_equity)

    simulated["account_equity_before"] = equity_before
    simulated["applied_risk_per_trade_pct"] = applied_risk_pct
    simulated["risk_dollars"] = risk_dollars
    simulated["pnl_dollars"] = pnl_dollars
    simulated["account_equity_after"] = equity_after
    timeline: dict[str, object] = {}
    if "entry_time" in simulated.columns:
        dates = pd.to_datetime(simulated["entry_time"], errors="coerce", utc=True).dropna()
        if not dates.empty:
            timeline = {
                "first_entry": dates.min().date().isoformat(),
                "last_entry": dates.max().date().isoformat(),
                "active_trade_dates": int(dates.dt.date.nunique()),
                "active_months": int(dates.dt.strftime("%Y-%m").nunique()),
            }
    summary.update(
        {
            "ending_equity": round(equity, 2),
            "total_pnl": round(equity - starting_equity, 2),
            "return_pct": round(((equity - starting_equity) / starting_equity) * 100, 2),
            "max_drawdown": round(max_drawdown, 2),
            "average_risk_per_trade_pct": round(float(pd.Series(applied_risk_pct).mean()), 6),
            "max_risk_per_trade_pct": round(float(pd.Series(applied_risk_pct).max()), 6),
            "timeline": timeline,
        }
    )
    return simulated, summary


def source_bucket_timelines(trades: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Return freshness timelines for each historical simulation source lane."""

    if trades.empty or "entry_time" not in trades.columns or "source_bucket" not in trades.columns:
        return {}

    working = trades.copy()
    working["_entry_dt"] = pd.to_datetime(working["entry_time"], errors="coerce", utc=True)
    working = working.dropna(subset=["_entry_dt"])
    if working.empty:
        return {}

    timelines: dict[str, dict[str, object]] = {}
    for bucket in SIMULATION_BUCKET_LABELS:
        subset = working[working["source_bucket"].eq(bucket)].copy()
        if subset.empty:
            continue
        latest = subset.sort_values("_entry_dt").iloc[-1]
        dates = subset["_entry_dt"]
        timelines[bucket] = {
            "row_count": int(len(subset)),
            "first_entry": dates.min().date().isoformat(),
            "last_entry": dates.max().date().isoformat(),
            "active_trade_dates": int(dates.dt.date.nunique()),
            "active_months": int(dates.dt.strftime("%Y-%m").nunique()),
            "latest_symbol": str(latest.get("symbol", "") or ""),
            "latest_setup": str(latest.get("source_setup", "") or ""),
            "latest_candidate": str(latest.get("source_candidate", "") or ""),
            "latest_trade_log": str(latest.get("source_trade_log", "") or ""),
        }
    return timelines


def promotion_risk_tier(row: pd.Series, base_risk_pct: float) -> tuple[str, float, str]:
    """Assign conservative research risk tiers from objective promotion evidence."""

    score = float(row.get("readiness_score", 0) or 0)
    expectancy = float(row.get("expectancy_r", 0) or 0)
    win_rate = float(row.get("win_rate_pct", 0) or 0)
    drawdown = float(row.get("max_drawdown_r", 0) or 0)

    if score >= 80 and expectancy >= 0.18 and win_rate >= 58 and drawdown >= -2.25:
        return "best_tier", min(base_risk_pct * 2.0, 0.02), "Score 80+, expectancy 0.18R+, win rate 58%+, drawdown no worse than -2.25R."
    if score >= 70 and expectancy >= 0.14 and win_rate >= 52 and drawdown >= -2.75:
        return "strong", min(base_risk_pct * 1.5, 0.015), "Score 70+, expectancy 0.14R+, win rate 52%+, drawdown no worse than -2.75R."
    return "standard", base_risk_pct, "Standard promoted setup risk."


def read_trade_log(path: Path) -> pd.DataFrame:
    """Read one historical trade log if it exists and has R results."""

    if not path.exists():
        return pd.DataFrame()
    try:
        trades = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if trades.empty or "r_result" not in trades.columns:
        return pd.DataFrame()
    return trades.copy()


def apply_simulation_source_labels(trades: pd.DataFrame, source_bucket: str) -> pd.DataFrame:
    """Add explicit evidence labels to historical simulator rows."""

    labels = SIMULATION_BUCKET_LABELS[source_bucket]
    result = trades.copy()
    result["source_bucket"] = source_bucket
    result["source_category"] = labels["source_category"]
    result["evidence_tier"] = labels["evidence_tier"]
    result["source_display_label"] = labels["display_label"]
    result["source_disclaimer"] = labels["disclaimer"]
    return result


def promoted_research_frames(
    logs_dir: Path,
    selected: pd.DataFrame,
    risk_per_trade_pct: float,
    risk_model: str,
) -> tuple[list[pd.DataFrame], int]:
    """Load trade logs promoted by the broad research promotion review."""

    logs_dir = logs_dir.resolve()
    frames: list[pd.DataFrame] = []
    source_files = 0
    for _, row in selected.iterrows():
        trade_log = str(row.get("trade_log", "")).strip()
        if not trade_log:
            continue
        trade_path = PROJECT_DIR / trade_log
        trade_path = trade_path.resolve()
        if not (trade_path.exists() and logs_dir in trade_path.parents):
            trade_path = logs_dir / Path(trade_log).name
        trades = read_trade_log(trade_path)
        if trades.empty:
            continue
        trades["source_candidate"] = row.get("candidate", "")
        trades["source_setup"] = row.get("setup", "")
        trades = apply_simulation_source_labels(trades, "Promotion Review")
        trades["source_trade_log"] = trade_path.name
        tier, tier_risk_pct, tier_reason = promotion_risk_tier(row, risk_per_trade_pct)
        trades["research_risk_tier"] = tier if risk_model == "tiered" else "fixed"
        trades["research_risk_reason"] = tier_reason if risk_model == "tiered" else "Fixed risk model selected."
        trades["research_risk_pct"] = tier_risk_pct if risk_model == "tiered" else risk_per_trade_pct
        frames.append(trades)
        source_files += 1
    return frames, source_files


def strategy_vault_frames(logs_dir: Path, risk_per_trade_pct: float) -> tuple[list[pd.DataFrame], int]:
    """Load Strategy Vault research trade logs into the unified simulator."""

    logs_dir = logs_dir.resolve()
    frames: list[pd.DataFrame] = []
    source_files = 0
    for strategy_id, strategy_name, filename in STRATEGY_VAULT_TRADE_LOGS:
        trade_path = logs_dir / filename
        trades = read_trade_log(trade_path)
        if trades.empty:
            continue
        trades["source_candidate"] = strategy_name
        trades["source_setup"] = "Strategy Vault"
        trades = apply_simulation_source_labels(trades, "Strategy Vault Research")
        trades["source_strategy_id"] = strategy_id
        trades["source_trade_log"] = trade_path.name
        trades["research_risk_tier"] = "strategy_research"
        trades["research_risk_reason"] = "Fixed risk for Strategy Vault research simulation; not paper-approved sizing."
        trades["research_risk_pct"] = risk_per_trade_pct
        frames.append(trades)
        source_files += 1
    return frames, source_files


def approved_playbook_frames(logs_dir: Path, risk_per_trade_pct: float) -> tuple[list[pd.DataFrame], int]:
    """Load the current approved playbook into the unified simulator."""

    logs_dir = logs_dir.resolve()
    trade_path = logs_dir / "playbook_approved_trades.csv"
    trades = read_trade_log(trade_path)
    if trades.empty:
        return [], 0
    result = trades.copy()
    variant = result.get("playbook_variant", pd.Series("", index=result.index)).fillna("").astype(str)
    exit_profile = result.get("playbook_exit_profile", pd.Series("", index=result.index)).fillna("").astype(str)
    result["source_candidate"] = (variant + " + " + exit_profile).str.strip(" +")
    result["source_setup"] = result.get("playbook_setup", pd.Series("Approved Playbook", index=result.index))
    result = apply_simulation_source_labels(result, "Approved Playbook")
    result["source_trade_log"] = trade_path.name
    result["research_risk_tier"] = "approved_playbook"
    result["research_risk_reason"] = "Fixed risk for the current approved playbook simulation; paper entries still require manual review."
    result["research_risk_pct"] = risk_per_trade_pct
    return [result], 1


def build_backtest_portfolio_simulation(
    logs_dir: Path,
    starting_equity: float = DEFAULT_BACKTEST_STARTING_EQUITY,
    risk_per_trade_pct: float = DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
    risk_model: str = "fixed",
) -> tuple[pd.DataFrame, dict]:
    """Build a deduped account simulation from promoted and Vault research rows."""

    logs_dir = logs_dir.resolve()
    promotion_path = logs_dir / "promotion_review.csv"
    if not promotion_path.exists():
        raise FileNotFoundError("logs/promotion_review.csv was not found. Run promotion review first.")

    promotion = pd.read_csv(promotion_path)
    if not promotion.empty and "trade_log" in promotion.columns and "promotion_decision" in promotion.columns:
        selected = promotion[promotion["promotion_decision"].eq("paper_watch_candidate")].copy()
    elif not promotion.empty and "trade_log" in promotion.columns:
        selected = promotion.copy()
    else:
        selected = pd.DataFrame()

    playbook_frames, playbook_source_files = approved_playbook_frames(logs_dir, risk_per_trade_pct)
    promoted_frames, promoted_source_files = promoted_research_frames(logs_dir, selected, risk_per_trade_pct, risk_model)
    vault_frames, vault_source_files = strategy_vault_frames(logs_dir, risk_per_trade_pct)
    frames = [*playbook_frames, *promoted_frames, *vault_frames]
    source_files = playbook_source_files + promoted_source_files + vault_source_files

    if not frames:
        empty, account = add_retro_account_simulation(pd.DataFrame(), starting_equity, risk_per_trade_pct)
        account.update(
            {
                "source_candidates": int(len(selected)),
                "source_files": 0,
                "approved_playbook_source_files": 0,
                "promotion_source_files": 0,
                "strategy_vault_source_files": 0,
                "duplicates_collapsed": 0,
                "source_bucket_counts": {},
                "evidence_tier_counts": {},
                "source_bucket_timelines": {},
                "simulation_scope": "approved_plus_promoted_plus_strategy_vault",
                "simulation_guardrail": "Historical simulation only. Official paper progress is counted from manually logged paper trades.",
            }
        )
        return empty, account

    combined = pd.concat(frames, ignore_index=True)
    before_dedupe = len(combined)
    dedupe_columns = [
        column
        for column in ["symbol", "entry_time", "exit_time", "setup_type", "entry", "stop", "target", "r_result"]
        if column in combined.columns
    ]
    if dedupe_columns:
        combined = combined.drop_duplicates(subset=dedupe_columns, keep="first")
    combined, account = add_retro_account_simulation(
        combined,
        starting_equity,
        risk_per_trade_pct,
        risk_pct_column="research_risk_pct" if risk_model == "tiered" else None,
    )
    account.update(
        {
            "source_candidates": int(len(selected)),
            "source_files": int(source_files),
            "approved_playbook_source_files": int(playbook_source_files),
            "promotion_source_files": int(promoted_source_files),
            "strategy_vault_source_files": int(vault_source_files),
            "duplicates_collapsed": int(before_dedupe - len(combined)),
            "risk_model": risk_model,
            "source_bucket_counts": {
                str(key): int(value)
                for key, value in combined.get("source_bucket", pd.Series(dtype=str)).value_counts().to_dict().items()
            },
            "evidence_tier_counts": {
                str(key): int(value)
                for key, value in combined.get("evidence_tier", pd.Series(dtype=str)).value_counts().to_dict().items()
            },
            "source_bucket_timelines": source_bucket_timelines(combined),
            "simulation_scope": "approved_plus_promoted_plus_strategy_vault",
            "simulation_guardrail": "Historical simulation only. Official paper progress is counted from manually logged paper trades.",
        }
    )
    return combined, account


def approved_setup_labels(symbol: str) -> list[str]:
    """Return the approved setup directions shown beside a chart symbol."""

    return setup_labels_for_symbol(symbol, "approved_plus_watch")


def build_trading_workspace_data(
    logs_dir: Path,
    symbol: str = "SPY",
    timeframe: str = "M5",
) -> dict:
    """Build a read-only chart snapshot from locally saved market-data candles."""

    symbol = symbol.upper()
    timeframe = timeframe.upper()
    if symbol not in TRADING_WORKSPACE_SYMBOLS:
        raise ValueError(f"{symbol} is not in the approved/watch paper-validation universe.")
    if timeframe not in TRADING_WORKSPACE_TIMEFRAMES:
        supported = ", ".join(TRADING_WORKSPACE_TIMEFRAMES)
        raise ValueError(f"Supported chart timeframes are {supported}.")

    candle_path = preferred_candle_path(logs_dir, symbol, TRADING_WORKSPACE_TIMEFRAMES[timeframe])
    opening_range_path = preferred_candle_path(logs_dir, symbol, "M5")
    if not candle_path.exists() or not opening_range_path.exists():
        raise FileNotFoundError(f"Saved market-data candles are missing for {symbol}.")

    candles = load_candles_from_csv(candle_path, symbol)
    lower_candles = load_candles_from_csv(opening_range_path, symbol)
    candles = add_core_indicators(
        candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    candles = add_session_columns(candles, STRATEGY)
    candles = add_opening_range(candles, lower_candles, STRATEGY)
    if timeframe != "D":
        candles = candles[candles["regular_session"]].copy()
    if candles.empty:
        raise ValueError(f"No chart candles are available for {symbol}.")

    latest_session = candles["session_date"].iloc[-1]
    display_limits = {"M1": 120, "M5": 90, "M15": 96, "M30": 80, "M60": 90, "D": 130}
    display_limit = display_limits.get(timeframe, 80)
    if timeframe in {"M1", "M5", "M15"}:
        display = candles[candles["session_date"] == latest_session].tail(display_limit)
    else:
        display = candles.tail(display_limit)
    latest = candles.iloc[-1]
    earlier_sessions = candles[candles["session_date"] < latest_session]
    if not earlier_sessions.empty:
        reference_close = earlier_sessions.iloc[-1]["close"]
    elif len(candles) > 1:
        reference_close = candles.iloc[-2]["close"]
    else:
        reference_close = latest["close"]
    change = float(latest["close"]) - float(reference_close)
    change_pct = change / float(reference_close) * 100 if float(reference_close) else 0.0

    rows = []
    for timestamp, row in display.iterrows():
        rows.append(
            {
                "time_et": timestamp.tz_convert(STRATEGY.market_timezone).strftime("%m/%d %H:%M"),
                "session_date": str(row["session_date"]),
                "open": app_number(row["open"]),
                "high": app_number(row["high"]),
                "low": app_number(row["low"]),
                "close": app_number(row["close"]),
                "volume": int(row["volume"]),
                "vwap": app_number(row["vwap"]),
                "ema_9": app_number(row[f"ema_{STRATEGY.fast_ema_length}"]),
                "ema_21": app_number(row[f"ema_{STRATEGY.slow_ema_length}"]),
                "ema_200": app_number(row[f"ema_{STRATEGY.regime_ema_length}"]),
                "opening_range_high": app_number(row["opening_range_high"]),
                "opening_range_low": app_number(row["opening_range_low"]),
            }
        )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": saved_candle_source_label(logs_dir, symbol, timeframe, "market-data"),
        "timeframe_role": "strategy signal timeframe" if timeframe in TRADING_SIGNAL_TIMEFRAMES else "chart-only review timeframe",
        "latest_session": str(latest_session),
        "latest_bar_et": latest["local_time"].strftime("%Y-%m-%d %H:%M %Z"),
        "latest_bar_iso": latest["local_time"].isoformat(),
        "data_lag_minutes": max(
            round((pd.Timestamp.now(tz=STRATEGY.market_timezone) - latest["local_time"]).total_seconds() / 60, 1),
            0,
        ),
        "last_price": app_number(latest["close"]),
        "day_change": round(change, 4),
        "day_change_pct": round(change_pct, 2),
        "approved_setups": approved_setup_labels(symbol),
        "available_symbols": [
            {
                "symbol": allowed_symbol,
                "setups": approved_setup_labels(allowed_symbol),
            }
            for allowed_symbol in TRADING_WORKSPACE_SYMBOLS
        ],
        "available_timeframes": [
            {
                "timeframe": label,
                "label": "1h" if label == "M60" else "Daily" if label == "D" else label.replace("M", "") + "m",
                "exists": preferred_candle_path(logs_dir, symbol, saved).exists(),
                "role": "signal" if label in TRADING_SIGNAL_TIMEFRAMES else "chart_only",
            }
            for label, saved in TRADING_WORKSPACE_TIMEFRAMES.items()
        ],
        "candles": rows,
    }


def build_replay_chart_data(
    logs_dir: Path,
    replay_id: int,
    revealed: bool = False,
    step: int | None = None,
) -> dict:
    """Build a concealed or revealed historical chart for one replay card.

    Before reveal, the payload ends at the entry bar so later price action is
    not shown during the practice decision. During step-by-step management,
    only the requested number of saved management bars is returned. After
    reveal, saved 5-minute bars are preferred because that is the
    exit-management timeframe.
    """

    replay_path = logs_dir / "setup_replay.json"
    if not replay_path.exists():
        raise FileNotFoundError("Saved setup replay cards are missing.")

    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    cards = replay.get("cards", [])
    card = next((item for item in cards if int(item.get("replay_id", -1)) == replay_id), None)
    if card is None:
        raise ValueError(f"Replay {replay_id} is not available.")

    symbol = str(card["symbol"]).upper()
    entry_time = pd.to_datetime(card["entry_time"], utc=True)
    exit_time = pd.to_datetime(card["exit_time"], utc=True)
    session_date = entry_time.tz_convert(STRATEGY.market_timezone).date()

    def load_timeframe(timeframe: str) -> pd.DataFrame:
        candle_path = preferred_candle_path(logs_dir, symbol, timeframe)
        opening_range_path = preferred_candle_path(logs_dir, symbol, "M5")
        if not candle_path.exists() or not opening_range_path.exists():
            raise FileNotFoundError(f"Saved market-data candles are missing for {symbol}.")

        candles = load_candles_from_csv(candle_path, symbol)
        lower_candles = load_candles_from_csv(opening_range_path, symbol)
        candles = add_core_indicators(
            candles,
            fast_length=STRATEGY.fast_ema_length,
            slow_length=STRATEGY.slow_ema_length,
            regime_length=STRATEGY.regime_ema_length,
        )
        candles = add_session_columns(candles, STRATEGY)
        candles = add_opening_range(candles, lower_candles, STRATEGY)
        return candles[candles["regular_session"]].copy()

    if step is not None and step < 0:
        raise ValueError("Replay candle step must be zero or greater.")

    management_active = step is not None
    timeframe = "M30"
    candles = load_timeframe(timeframe)
    if revealed or management_active:
        exit_candles = load_timeframe("M5")
        session_exit_candles = exit_candles[exit_candles["session_date"] == session_date]
        if not session_exit_candles.empty and session_exit_candles.index.min() <= entry_time:
            timeframe = "M5"
            candles = exit_candles

    session_candles = candles[candles["session_date"] == session_date].copy()
    management_candles = session_candles[(session_candles.index > entry_time) & (session_candles.index <= exit_time)]
    available_steps = int(len(management_candles))
    visible_step = min(step or 0, available_steps)
    if revealed:
        cutoff = exit_time
    elif management_active and visible_step:
        cutoff = management_candles.index[visible_step - 1]
    else:
        cutoff = entry_time
    display = candles[(candles["session_date"] == session_date) & (candles.index <= cutoff)].copy()
    if display.empty:
        raise ValueError(f"No saved chart bars are available for replay {replay_id}.")

    rows = []
    for timestamp, row in display.iterrows():
        rows.append(
            {
                "time_et": timestamp.tz_convert(STRATEGY.market_timezone).strftime("%m/%d %H:%M"),
                "session_date": str(row["session_date"]),
                "open": app_number(row["open"]),
                "high": app_number(row["high"]),
                "low": app_number(row["low"]),
                "close": app_number(row["close"]),
                "volume": int(row["volume"]),
                "vwap": app_number(row["vwap"]),
                "ema_9": app_number(row[f"ema_{STRATEGY.fast_ema_length}"]),
                "ema_21": app_number(row[f"ema_{STRATEGY.slow_ema_length}"]),
                "ema_200": app_number(row[f"ema_{STRATEGY.regime_ema_length}"]),
                "opening_range_high": app_number(row["opening_range_high"]),
                "opening_range_low": app_number(row["opening_range_low"]),
            }
        )

    def marker(event_time: pd.Timestamp, label: str, kind: str) -> dict:
        eligible = display[display.index <= event_time]
        timestamp = eligible.index[-1] if not eligible.empty else display.index[0]
        return {
            "time_et": timestamp.tz_convert(STRATEGY.market_timezone).strftime("%m/%d %H:%M"),
            "label": label,
            "kind": kind,
        }

    markers = [marker(entry_time, "E", "entry")]
    if revealed:
        markers.append(marker(exit_time, "X", "exit"))

    current_r = None
    current_price = None
    if management_active and visible_step:
        current_price = float(display.iloc[-1]["close"])
        entry_price = float(card["entry"])
        risk = abs(entry_price - float(card["stop"]))
        if risk:
            direction_multiplier = 1 if str(card.get("direction", "")).lower() == "long" else -1
            current_r = round(((current_price - entry_price) / risk) * direction_multiplier, 4)

    return {
        "replay_id": replay_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "outcome_revealed": revealed,
        "management_active": management_active,
        "step": visible_step if management_active else None,
        "available_steps": available_steps if revealed or (management_active and visible_step >= available_steps) else None,
        "management_complete": management_active and visible_step >= available_steps,
        "current_price": app_number(current_price) if current_price is not None else None,
        "current_r": current_r,
        "source": saved_candle_source_label(logs_dir, symbol, timeframe, "historical"),
        "chart_note": (
            f"Outcome shown through exit on the {timeframe} chart."
            if revealed
            else (
                (
                    f"No additional stored {timeframe} management bars are available; comparison is ready."
                    if not available_steps
                    else "Final stored management candle reached. Historical outcome remains hidden."
                    if visible_step >= available_steps
                    else f"Management candle {visible_step} is visible. Historical outcome remains hidden."
                    if visible_step
                    else f"Management view ready on {timeframe}. Advance one candle at a time."
                )
                if management_active
                else "Decision view ends at the entry bar. Future historical bars remain hidden."
            )
        ),
        "candles": rows,
        "markers": markers,
        "plan_levels": [
            {"label": "Entry", "value": app_number(card["entry"]), "kind": "entry"},
            {"label": "Stop", "value": app_number(card["stop"]), "kind": "stop"},
            {"label": "Target", "value": app_number(card["target"]), "kind": "target"},
        ],
    }


def build_investment_narrative_data(symbol: str = "SPY") -> dict:
    """Return long-term research prompts without creating trade signals."""

    symbol = symbol.upper()
    if symbol not in TRADING_WORKSPACE_SYMBOLS:
        raise ValueError(f"{symbol} is not in the approved paper-validation universe.")

    narrative = INVESTMENT_NARRATIVES.get(symbol, {})
    return {
        "symbol": symbol,
        "asset_type": narrative.get("asset_type", "Approved research symbol"),
        "scope": "Long-term context only",
        "source_status": "sources_not_connected",
        "source_status_label": "Sources Not Connected",
        "summary": (
            "No live headline or X source is connected yet. Once an approved source is configured, "
            "this area can summarize sourced developments and trend themes for long-term review."
        ),
        "thesis_focus": narrative.get(
            "thesis_focus",
            "Monitor durable business or market developments before forming a long-term investment thesis.",
        ),
        "monitoring_themes": narrative.get("monitoring_themes", []),
        "review_questions": narrative.get("review_questions", []),
        "source_slots": [
            {
                "label": "Market news and company reports",
                "status": "Not connected",
                "detail": "Connect a licensed or approved news source before generating summaries.",
            },
            {
                "label": "X public-post trends",
                "status": "Not connected",
                "detail": "Use the official X API with refresh and spending limits when enabled.",
            },
        ],
        "guardrail": (
            "Narrative context is excluded from strategy scoring, entries, exits, "
            "position sizing, and paper-trade eligibility."
        ),
    }


def split_scanner_conditions(value: object) -> list[str]:
    """Convert scanner condition text into dashboard checklist entries."""

    if value is None or pd.isna(value):
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def build_setup_readiness_data(logs_dir: Path, symbol: str = "SPY") -> dict:
    """Return read-only setup explanations and signal markers from scanner output."""

    symbol = symbol.upper()
    if symbol not in TRADING_WORKSPACE_SYMBOLS:
        raise ValueError(f"{symbol} is not in the approved paper-validation universe.")

    scanner_path = logs_dir / "daily_paper_signal_scanner.csv"
    if not scanner_path.exists():
        return {
            "symbol": symbol,
            "status": "missing_scanner",
            "setups": [],
            "signal_markers": [],
            "message": "Run the local daily scanner to populate setup readiness.",
            "guardrail": "Readiness explanations do not create or approve paper trades.",
        }

    scanner = pd.read_csv(scanner_path)
    selected = scanner[scanner["symbol"].astype(str).str.upper() == symbol]
    setups = []
    markers = []
    for _, row in selected.iterrows():
        scanner_status = str(row.get("scanner_status", "not_ready"))
        signal_freshness = "" if pd.isna(row.get("signal_freshness")) else str(row.get("signal_freshness", ""))
        signal_time = "" if pd.isna(row.get("latest_signal_et")) else str(row.get("latest_signal_et", ""))
        if scanner_status == "allowed" and signal_freshness == "current_candle":
            status_label = "Current Signal"
            status_tone = "healthy"
        elif scanner_status == "allowed" and signal_freshness == "grace_candle":
            status_label = "B Grace Review"
            status_tone = "review_only"
        elif scanner_status == "blocked_watch_only" and signal_freshness == "current_candle":
            status_label = "Watch Only"
            status_tone = "watch"
        elif scanner_status == "blocked_watch_only" and signal_freshness == "grace_candle":
            status_label = "B Grace Watch"
            status_tone = "watch"
        elif scanner_status == "allowed" and signal_freshness == "earlier_today":
            status_label = "Triggered Earlier"
            status_tone = "review_only"
        elif scanner_status == "blocked_watch_only" and signal_freshness == "earlier_today":
            status_label = "Watch Signal Earlier"
            status_tone = "watch"
        elif scanner_status == "data_error":
            status_label = "Data Error"
            status_tone = "caution"
        else:
            status_label = "Not Ready"
            status_tone = "watch"

        missing = split_scanner_conditions(row.get("missing_conditions"))
        passed = split_scanner_conditions(row.get("passed_conditions"))
        if not missing and "latest candle gaps:" in str(row.get("latest_candle_notes", "")):
            missing = split_scanner_conditions(str(row["latest_candle_notes"]).split("latest candle gaps:", 1)[1])
        elif not missing and scanner_status == "not_ready":
            missing = split_scanner_conditions(row.get("latest_candle_notes"))

        setups.append(
            {
                "setup": str(row["setup"]),
                "direction": str(row["direction"]),
                "status_label": status_label,
                "status_tone": status_tone,
                "latest_candle_et": str(row.get("latest_candle_et", "")),
                "latest_signal_et": signal_time,
                "signal_freshness": signal_freshness,
                "quality_grade": "" if pd.isna(row.get("quality_grade")) else str(row.get("quality_grade", "")),
                "quality_score": app_number(row.get("quality_score")),
                "relative_volume": app_number(row.get("relative_volume")),
                "room_to_target_r": app_number(row.get("room_to_target_r")),
                "passed_conditions": passed,
                "missing_conditions": missing,
                "condition_count": int(row.get("condition_count", len(passed) + len(missing)) or 0),
                "passed_condition_count": int(row.get("passed_condition_count", len(passed)) or 0),
                "notes": str(row.get("notes", "")),
            }
        )
        if signal_time:
            markers.append(
                {
                    "time_et": pd.to_datetime(signal_time).strftime("%m/%d %H:%M"),
                    "setup": str(row["setup"]),
                    "label": chart_marker_label_for_setup(str(row["setup"]), str(row.get("variant", ""))),
                    "direction": str(row["direction"]),
                    "scanner_status": scanner_status,
                    "signal_freshness": signal_freshness,
                }
            )

    return {
        "symbol": symbol,
        "status": "available",
        "setups": setups,
        "signal_markers": markers,
        "message": "Conditions reflect the latest saved scanner candle. Markers show scanner signals found in the stored session.",
        "guardrail": "Readiness explanations do not create signals, approve paper trades, or alter position sizing.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Project Gwala app shell.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to serve.")
    return parser.parse_args()


class ProjectGwalaHandler(SimpleHTTPRequestHandler):
    """Serve static app files and tightly scoped local JSON actions."""

    def end_headers(self) -> None:
        """Keep the local dashboard from reusing stale app assets."""

        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/system-state":
            self.serve_system_state()
            return
        if parsed.path == "/api/command-center-v1":
            self.serve_founder_command_center()
            return
        if parsed.path == "/api/command-center-v1/chart":
            self.serve_founder_command_center_chart(parsed.query)
            return
        if parsed.path == "/api/trading-workspace":
            self.serve_trading_workspace(parsed.query)
            return
        if parsed.path == "/api/investment-narrative":
            self.serve_investment_narrative(parsed.query)
            return
        if parsed.path == "/api/setup-readiness":
            self.serve_setup_readiness(parsed.query)
            return
        if parsed.path == "/api/replay-chart":
            self.serve_replay_chart(parsed.query)
            return
        if parsed.path == "/api/near-miss-analytics":
            self.serve_near_miss_analytics()
            return
        if parsed.path == "/api/backtest-trades":
            self.serve_backtest_trades(parsed.query)
            return
        if parsed.path == "/api/backtest-portfolio":
            self.serve_backtest_portfolio(parsed.query)
            return
        if parsed.path == "/api/open-paper-trades":
            self.serve_open_paper_trades()
            return
        if parsed.path == "/api/paper-command-center":
            self.serve_paper_command_center()
            return
        if parsed.path == "/api/report":
            self.serve_report(parsed.query)
            return
        if parsed.path.startswith("/logs/"):
            self.serve_log_file()
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/actions/refresh-status":
            self.run_refresh_status_action()
            return
        if parsed.path == "/api/actions/refresh-webull-data":
            self.run_refresh_webull_data_action()
            return
        if parsed.path == "/api/actions/premarket-check":
            self.run_premarket_check_action()
            return
        if parsed.path == "/api/actions/paper-session-preview":
            self.run_paper_session_action("preview")
            return
        if parsed.path == "/api/actions/paper-session-confirm-entry":
            self.run_paper_session_action("confirm_entry")
            return
        if parsed.path == "/api/actions/paper-session-confirm-exits":
            self.run_paper_session_action("confirm_exits")
            return
        if parsed.path == "/api/actions/paper-command-center/chart-approval":
            self.run_command_center_chart_approval()
            return
        if parsed.path == "/api/actions/paper-command-center/contract-approval":
            self.run_command_center_contract_approval()
            return
        if parsed.path == "/api/actions/paper-command-center/auto-select-contract":
            self.run_command_center_auto_select_contract()
            return
        if parsed.path == "/api/actions/paper-command-center/confirm-entry":
            self.run_command_center_confirm_entry()
            return
        if parsed.path == "/api/actions/paper-command-center/confirm-exit":
            self.run_command_center_confirm_exit()
            return
        if parsed.path == "/api/actions/update-paper-trade":
            self.run_update_paper_trade_action()
            return
        self.send_error(404, "Action is not allowed.")

    def send_json(self, payload: dict, status: int = 200) -> None:
        """Write a JSON API response without browser caching."""

        body = json.dumps(json_safe(payload), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        """Read a small JSON POST body."""

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        return data if isinstance(data, dict) else {}

    def serve_system_state(self) -> None:
        """Return the current app-ready system state JSON."""

        self.rebuild_lightweight_system_state()
        path = LOGS_DIR / "system_state.json"
        if not path.exists():
            self.send_error(404, "logs/system_state.json not found. Run python run_system_state.py first.")
            return

        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.send_error(500, "logs/system_state.json is invalid. Run python run_system_state.py again.")
            return
        self.send_json(state)

    def serve_founder_command_center(self) -> None:
        """Return the read-only founder-facing Command Center payload."""

        try:
            self.send_json(founder_command_center_payload())
        except Exception as error:
            self.send_json({"error": f"Command Center unavailable: {error}"}, status=500)

    def serve_founder_command_center_chart(self, query: str) -> None:
        """Return read-only chart data for the founder Command Center."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        timeframe = params.get("timeframe", ["M30"])[0]
        try:
            payload = founder_command_center_chart_payload(symbol, timeframe)
        except (FileNotFoundError, ValueError) as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def rebuild_lightweight_system_state(self) -> None:
        """Refresh local status files before serving app state.

        This keeps the dashboard timestamp current without fetching market data,
        importing paper trades, placing orders, or creating broker alerts.
        """

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            return
        try:
            for command in lightweight_state_commands():
                subprocess.run(
                    command,
                    cwd=PROJECT_DIR,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Lightweight app-state refresh failed: {error}")
        finally:
            STATUS_ACTION_LOCK.release()

    def serve_trading_workspace(self, query: str) -> None:
        """Return read-only chart data derived from locally saved Webull bars."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        timeframe = params.get("timeframe", ["M5"])[0]
        try:
            payload = build_trading_workspace_data(LOGS_DIR, symbol, timeframe)
        except (FileNotFoundError, ValueError) as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_investment_narrative(self, query: str) -> None:
        """Return non-signal long-term research context for an approved symbol."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        try:
            payload = build_investment_narrative_data(symbol)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_setup_readiness(self, query: str) -> None:
        """Return setup conditions and in-session signal markers for the chart."""

        params = parse_qs(query)
        symbol = params.get("symbol", ["SPY"])[0]
        try:
            payload = build_setup_readiness_data(LOGS_DIR, symbol)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_replay_chart(self, query: str) -> None:
        """Return saved historical chart bars for process-only replay practice."""

        params = parse_qs(query)
        try:
            replay_id = int(params.get("id", [""])[0])
            revealed = params.get("revealed", ["false"])[0].lower() == "true"
            step = int(params["step"][0]) if "step" in params else None
            payload = build_replay_chart_data(LOGS_DIR, replay_id, revealed, step)
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError) as error:
            self.send_json({"error": str(error)}, status=404)
            return
        self.send_json(payload)

    def serve_near_miss_analytics(self) -> None:
        """Return blocker patterns without changing scanner or paper state."""

        scanner_path = LOGS_DIR / "daily_paper_signal_scanner.csv"
        if not scanner_path.exists():
            self.send_json({"error": "Run the local daily scanner to populate near-miss analytics."}, status=404)
            return
        scanner = pd.read_csv(scanner_path)
        observations = read_observations(RUNTIME_DATA_DIR / "near_miss_observations.csv")
        results_path = LOGS_DIR / "forward_observation_results.csv"
        results = pd.read_csv(results_path) if results_path.exists() else pd.DataFrame()
        self.send_json(build_near_miss_payload(scanner, observations, results))

    def serve_report(self, query: str) -> None:
        """Return an allowed Markdown report as JSON for the app."""

        params = parse_qs(query)
        report_key = params.get("name", [""])[0]
        filename = ALLOWED_REPORTS.get(report_key)
        if filename is None:
            self.send_error(404, "Report is not allowed.")
            return

        path = LOGS_DIR / filename
        if not path.exists():
            self.send_error(404, f"{filename} not found.")
            return

        payload = {
            "name": report_key,
            "filename": filename,
            "content": path.read_text(encoding="utf-8"),
        }
        self.send_json(payload)

    def serve_backtest_trades(self, query: str) -> None:
        """Return a safe simulated backtest trade CSV for dashboard review."""

        params = parse_qs(query)
        raw_name = params.get("file", [""])[0]
        starting_equity = app_positive_float(
            params.get("starting_equity", [DEFAULT_BACKTEST_STARTING_EQUITY])[0],
            DEFAULT_BACKTEST_STARTING_EQUITY,
            maximum=1_000_000.0,
        )
        risk_per_trade_pct = app_positive_float(
            params.get("risk_per_trade_pct", [DEFAULT_BACKTEST_RISK_PER_TRADE_PCT])[0],
            DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
            maximum=0.10,
        )
        safe_name = Path(raw_name).name
        if not safe_name.endswith(("_baseline_trades.csv", "_elite_trades.csv")):
            self.send_json({"error": "Backtest trade file is not allowed."}, status=404)
            return

        path = LOGS_DIR / safe_name
        if not path.exists():
            self.send_json({"error": f"{safe_name} was not found."}, status=404)
            return

        try:
            trades = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            trades = pd.DataFrame()

        trades, account = add_retro_account_simulation(trades, starting_equity, risk_per_trade_pct)
        if not trades.empty:
            trades = trades.copy()
            trades["entry_sort_ms"] = trade_sort_millis(trades)
        columns = [
            "symbol",
            "entry_time",
            "entry_sort_ms",
            "exit_time",
            "quality_grade",
            "quality_score",
            "entry",
            "stop",
            "target",
            "exit_price",
            "r_result",
            "risk_dollars",
            "pnl_dollars",
            "account_equity_after",
            "exit_reason",
            "relative_volume",
            "room_to_resistance_r",
        ]
        available = [column for column in columns if column in trades.columns]
        payload = {
            "filename": safe_name,
            "row_count": int(len(trades)),
            "account": account,
            "columns": available,
            "rows": trades[available].head(200).fillna("").to_dict("records") if available else [],
        }
        self.send_json(payload)

    def serve_backtest_portfolio(self, query: str) -> None:
        """Return a deduped promoted-backtest research account simulation."""

        params = parse_qs(query)
        starting_equity = app_positive_float(
            params.get("starting_equity", [DEFAULT_BACKTEST_STARTING_EQUITY])[0],
            DEFAULT_BACKTEST_STARTING_EQUITY,
            maximum=1_000_000.0,
        )
        risk_per_trade_pct = app_positive_float(
            params.get("risk_per_trade_pct", [DEFAULT_BACKTEST_RISK_PER_TRADE_PCT])[0],
            DEFAULT_BACKTEST_RISK_PER_TRADE_PCT,
            maximum=0.10,
        )
        risk_model = params.get("risk_model", ["fixed"])[0]
        if risk_model not in {"fixed", "tiered"}:
            risk_model = "fixed"
        try:
            trades, account = build_backtest_portfolio_simulation(
                LOGS_DIR,
                starting_equity,
                risk_per_trade_pct,
                risk_model=risk_model,
            )
        except FileNotFoundError as error:
            self.send_json({"error": str(error)}, status=404)
            return

        if not trades.empty:
            trades = trades.copy()
            trades["entry_sort_ms"] = trade_sort_millis(trades)

        columns = [
            "symbol",
            "entry_time",
            "entry_sort_ms",
            "exit_time",
            "source_setup",
            "source_candidate",
            "source_bucket",
            "source_category",
            "evidence_tier",
            "source_display_label",
            "source_strategy_id",
            "quality_grade",
            "quality_score",
            "entry",
            "stop",
            "target",
            "exit_price",
            "r_result",
            "research_risk_tier",
            "applied_risk_per_trade_pct",
            "risk_dollars",
            "pnl_dollars",
            "account_equity_after",
            "exit_reason",
            "relative_volume",
            "research_risk_reason",
            "source_trade_log",
            "source_disclaimer",
        ]
        available = [column for column in columns if column in trades.columns]
        payload = {
            "row_count": int(len(trades)),
            "account": account,
            "columns": available,
            "rows": trades[available].fillna("").to_dict("records") if available else [],
            "guardrail": "Promoted historical backtest simulation only. This is not the live paper log or broker execution.",
        }
        self.send_json(payload)

    def serve_open_paper_trades(self) -> None:
        """Return paper-trade rows that still need outcome logging."""

        trades = read_existing(PAPER_CSV)
        rows = open_paper_rows(trades)
        self.send_json(
            {
                "row_count": int(len(rows)),
                "rows": rows.fillna("").to_dict("records"),
                "guardrail": "Local paper log only. This endpoint does not place broker orders.",
            }
        )

    def serve_paper_command_center(self) -> None:
        """Return the four-decision paper workflow state."""

        try:
            self.send_json(command_center_payload())
        except (OSError, ValueError, pd.errors.EmptyDataError) as error:
            self.send_json({"error": f"Paper Trade Command Center unavailable: {error}"}, status=500)

    def run_command_center_chart_approval(self) -> None:
        """Record the required operator chart-review decision."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A command-center action is already running."}, status=409)
            return
        try:
            payload = self.read_json_body()
            sample = command_center_sample_by_key(str(payload.get("sample_key", "")))
            decision = str(payload.get("decision", "approved")).strip().lower()
            if decision not in {"approved", "rejected"}:
                raise ValueError("decision must be approved or rejected")
            approval = append_command_center_approval(sample, decision, str(payload.get("notes", "")).strip())
            self.send_json(
                {
                    "action": "chart_approval",
                    "message": f"Chart review recorded as {decision}. No gates or trading rules were changed.",
                    "approval": approval,
                    "command_center": command_center_payload(),
                }
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": f"Chart approval rejected: {error}"}, status=400)
        finally:
            STATUS_ACTION_LOCK.release()

    def run_command_center_contract_approval(self) -> None:
        """Write the selected contract row and rerun the existing Contract Gate."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A command-center action is already running."}, status=409)
            return
        try:
            payload = self.read_json_body()
            sample = command_center_sample_by_key(str(payload.get("sample_key", "")))
            append_contract_audit_row(sample, payload)
            for command in [
                [sys.executable, "run_options_contract_gate.py"],
                [sys.executable, "run_paper_validation_sample_import.py"],
                [sys.executable, "run_system_state.py"],
            ]:
                subprocess.run(command, cwd=PROJECT_DIR, check=True, capture_output=True, text=True, timeout=120)
            row = command_center_contract_row(command_center_sample_key(sample))
            self.send_json(
                {
                    "action": "contract_approval",
                    "message": (
                        "Contract details saved and checked by the existing Contract Gate. "
                        f"Result: {row.get('contract_gate_status', 'missing')}."
                    ),
                    "contract": row,
                    "command_center": command_center_payload(),
                }
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.SubprocessError) as error:
            self.send_json({"error": f"Contract approval rejected: {error}"}, status=400)
        finally:
            STATUS_ACTION_LOCK.release()

    def run_command_center_auto_select_contract(self) -> None:
        """Select an A-tier contract from local chain CSVs, then rerun existing gates."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A command-center action is already running."}, status=409)
            return
        try:
            payload = self.read_json_body()
            sample = command_center_sample_by_key(str(payload.get("sample_key", "")))
            sample_tier = str(sample.get("sample_tier", "")).strip().upper()
            if sample_tier != "A":
                raise ValueError("Automatic contract selection is limited to A-tier Paper Gate survivors.")
            symbol = str(sample.get("symbol", "")).strip().upper()
            for command in [
                [
                    sys.executable,
                    "run_options_chain_review.py",
                    "--output-dir",
                    str(LOGS_DIR),
                    "--symbol",
                    symbol,
                    "--tier",
                    "A",
                    "--write-audit",
                ],
                [sys.executable, "run_options_contract_gate.py"],
                [sys.executable, "run_paper_validation_sample_import.py"],
                [sys.executable, "run_system_state.py"],
            ]:
                subprocess.run(command, cwd=PROJECT_DIR, check=True, capture_output=True, text=True, timeout=120)
            chain_review_path = LOGS_DIR / "options_chain_review.json"
            chain_review = json.loads(chain_review_path.read_text(encoding="utf-8")) if chain_review_path.exists() else {}
            if int(chain_review.get("selected_contract_count", 0) or 0) < 1:
                status = chain_review.get("status", "missing_chain")
                raise ValueError(
                    f"No eligible A-tier contract was selected ({status}). "
                    f"Add a local option-chain CSV at data/options_chains/{symbol}.csv."
                )
            row = command_center_contract_row(command_center_sample_key(sample))
            if not row:
                raise ValueError(
                    f"No eligible contract was selected. Add a local option-chain CSV at data/options_chains/{symbol}.csv."
                )
            self.send_json(
                {
                    "action": "auto_select_contract",
                    "message": (
                        "Auto-selected the best A-tier contract that passed the existing Contract Gate. "
                        f"Result: {row.get('contract_gate_status', 'missing')}. No broker order was placed."
                    ),
                    "contract": row,
                    "command_center": command_center_payload(),
                }
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.SubprocessError) as error:
            self.send_json({"error": f"Automatic contract selection rejected: {error}"}, status=400)
        finally:
            STATUS_ACTION_LOCK.release()

    def run_command_center_confirm_entry(self) -> None:
        """Confirm one Contract Gate-passed candidate as an official local paper trade."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A command-center action is already running."}, status=409)
            return
        try:
            payload = self.read_json_body()
            sample_key = str(payload.get("sample_key", ""))
            sample = command_center_sample_by_key(sample_key)
            approval = latest_command_center_approval(sample_key)
            if approval.get("decision") != "approved":
                raise ValueError("Chart approval is required before confirming an official paper trade.")
            contract = command_center_contract_row(sample_key)
            if not bool(contract.get("contract_gate_pass", False)):
                raise ValueError(contract.get("contract_gate_reason") or "Contract Gate has not passed for this sample.")

            build_validation_sample_import(
                output_dir=LOGS_DIR,
                samples_csv=RUNTIME_DATA_DIR / "paper_validation_samples.csv",
                contract_audit_csv=CONTRACT_AUDIT_CSV,
                confirm_samples=True,
            )
            order = paper_order_from_contract_sample(sample, contract)
            existing_orders = read_orders(PAPER_ORDERS_CSV)
            new_orders = filter_new_orders(existing_orders, order)
            PAPER_ORDERS_CSV.parent.mkdir(parents=True, exist_ok=True)
            pd.concat([existing_orders, new_orders], ignore_index=True).to_csv(PAPER_ORDERS_CSV, index=False)
            open_trades = orders_to_open_paper_trades(new_orders)
            written_trades = write_open_paper_trades(PAPER_CSV, open_trades)

            for command in [
                [sys.executable, "run_paper_review.py"],
                [sys.executable, "run_open_paper_monitor.py"],
                [sys.executable, "run_daily_ship_report.py"],
                [sys.executable, "run_system_state.py"],
            ]:
                subprocess.run(command, cwd=PROJECT_DIR, check=True, capture_output=True, text=True, timeout=120)
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "confirm_official_paper_trade",
                    "message": (
                        f"Official local paper trade confirmed. Orders written: {len(new_orders)}; "
                        f"open paper trades written: {len(written_trades)}. No broker orders were placed."
                    ),
                    "state": state,
                    "command_center": command_center_payload(),
                }
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.SubprocessError) as error:
            self.send_json({"error": f"Official paper entry rejected: {error}"}, status=400)
        finally:
            STATUS_ACTION_LOCK.release()

    def run_command_center_confirm_exit(self) -> None:
        """Confirm exit-ready local paper rows using the existing exit monitor."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A command-center action is already running."}, status=409)
            return
        try:
            subprocess.run(
                [sys.executable, "run_open_paper_monitor.py", "--confirm-updates"],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            for command in [
                [sys.executable, "run_exit_audit.py"],
                [sys.executable, "run_paper_review.py"],
                [sys.executable, "run_daily_ship_report.py"],
                [sys.executable, "run_system_state.py"],
            ]:
                subprocess.run(command, cwd=PROJECT_DIR, check=True, capture_output=True, text=True, timeout=120)
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "confirm_paper_exit",
                    "message": "Exit confirmation completed through the existing open-paper monitor. No broker orders were placed.",
                    "state": state,
                    "command_center": command_center_payload(),
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            self.send_json({"error": f"Exit confirmation failed: {error}"}, status=500)
        finally:
            STATUS_ACTION_LOCK.release()

    def run_update_paper_trade_action(self) -> None:
        """Update one local paper row from the dashboard logger."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A paper-log update is already running."}, status=409)
            return

        try:
            payload = self.read_json_body()
            args = argparse.Namespace(
                row=int(payload.get("row", 0)),
                actual_entry=float(payload["actual_entry"]),
                actual_exit=float(payload["actual_exit"]),
                exit_time=str(payload.get("exit_time", "")).strip() or None,
                shares=int(payload["shares"]) if str(payload.get("shares", "")).strip() else None,
                vehicle=str(payload.get("vehicle", "")).strip() or None,
                risk_tier=str(payload.get("risk_tier", "")).strip() or None,
                planned_option_premium=(
                    float(payload["planned_option_premium"])
                    if str(payload.get("planned_option_premium", "")).strip()
                    else None
                ),
                followed_plan=str(payload.get("followed_plan", "")).strip() or None,
                exit_reason=str(payload.get("exit_reason", "")).strip() or None,
                notes=str(payload.get("notes", "")).strip() or None,
                append_notes=bool(payload.get("append_notes", True)),
            )
            trades = read_existing(PAPER_CSV)
            updated = update_paper_trade(trades, args)
            PAPER_CSV.parent.mkdir(parents=True, exist_ok=True)
            updated.to_csv(PAPER_CSV, index=False)

            for command in [[sys.executable, "run_paper_review.py"], *lightweight_state_commands()]:
                subprocess.run(
                    command,
                    cwd=PROJECT_DIR,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            row = updated.iloc[args.row - 1]
            self.send_json(
                {
                    "action": "update_paper_trade",
                    "message": (
                        f"Updated local paper row {args.row}: {row['symbol']} {row['setup']} "
                        f"outcome_r={row['outcome_r']}. No broker orders were placed."
                    ),
                    "state": state,
                }
            )
        except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as error:
            self.send_json({"error": f"Paper-log update rejected: {error}"}, status=400)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Paper-log update failed: {error}")
            self.send_json(
                {"error": "Paper-log update failed after writing. Review data/paper_trades.csv and logs."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_refresh_status_action(self) -> None:
        """Rebuild readiness reports only; this never fetches market data."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A refresh-status update is already running."}, status=409)
            return

        try:
            for command in lightweight_state_commands():
                subprocess.run(
                    command,
                    cwd=PROJECT_DIR,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "refresh_status",
                    "message": "Refresh status updated. No market data was fetched and no paper trades were imported.",
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Refresh-status action failed: {error}")
            self.send_json(
                {"error": "Refresh-status update failed. Run python run_refresh_status.py in the terminal."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_refresh_webull_data_action(self) -> None:
        """Refresh market-data CSVs and rebuild reports; never trade."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A market-data refresh is already running."}, status=409)
            return

        try:
            result = subprocess.run(
                [workflow_python(), "run_current_candle_capture.py"],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=900,
            )
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "refresh_market_data",
                    "message": (
                        "Webull market-data refresh completed. Reports were rebuilt, paper import stayed manual, "
                        "and no broker orders or real trades were placed."
                    ),
                    "output_tail": (result.stdout or "")[-2000:],
                    "state": state,
                }
            )
        except subprocess.CalledProcessError as error:
            detail = "\n".join(part for part in [error.stdout, error.stderr] if part).strip()
            print(f"Market-data refresh action failed: {detail or error}")
            self.send_json(
                {
                    "error": "Webull market-data refresh failed.",
                    "detail": (detail or str(error))[-3000:],
                },
                status=500,
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Market-data refresh action failed: {error}")
            self.send_json(
                {"error": "Webull market-data refresh failed.", "detail": str(error)},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_premarket_check_action(self) -> None:
        """Run local pre-market checks only; never request Webull data."""

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A readiness update is already running."}, status=409)
            return

        try:
            subprocess.run(
                [sys.executable, "run_premarket_verification.py"],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": "premarket_check",
                    "message": "Local pre-market verification updated. No market data was fetched and no paper trades were imported.",
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Pre-market check action failed: {error}")
            self.send_json(
                {"error": "Pre-market verification failed. Review logs/premarket_verification.md."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def run_paper_session_action(self, mode: str) -> None:
        """Run the local paper session cycle with an explicitly allowed mode."""

        allowed_modes = {
            "preview": {
                "flags": [],
                "message": "Paper session preview updated. No local paper entries or exits were written.",
            },
            "confirm_entry": {
                "flags": ["--confirm-local-paper"],
                "message": "Local paper entry cycle completed. This wrote local paper rows only if eligible rows were present.",
            },
            "confirm_exits": {
                "flags": ["--confirm-exits"],
                "message": "Local paper exit cycle completed. This wrote local paper exits only if completed exits were present.",
            },
        }
        selected = allowed_modes.get(mode)
        if selected is None:
            self.send_json({"error": "Paper session mode is not allowed."}, status=404)
            return

        if not STATUS_ACTION_LOCK.acquire(blocking=False):
            self.send_json({"error": "A paper session cycle is already running."}, status=409)
            return

        try:
            subprocess.run(
                [sys.executable, "run_paper_session_cycle.py", *selected["flags"]],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=240,
            )
            state = json.loads((LOGS_DIR / "system_state.json").read_text(encoding="utf-8"))
            self.send_json(
                {
                    "action": f"paper_session_{mode}",
                    "message": f"{selected['message']} No broker orders, Webull paper orders, or real trades were placed.",
                    "state": state,
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Paper session action failed: {error}")
            self.send_json(
                {"error": "Paper session cycle failed. Review logs/paper_session_cycle.md or run it in the terminal."},
                status=500,
            )
        finally:
            STATUS_ACTION_LOCK.release()

    def serve_log_file(self) -> None:
        """Serve selected read-only log files used by the dashboard links."""

        raw_name = unquote(urlparse(self.path).path.removeprefix("/logs/"))
        safe_name = Path(raw_name).name
        path = LOGS_DIR / safe_name
        if not path.exists() or path.suffix not in {".md", ".csv", ".json"}:
            self.send_error(404, "Log file not found.")
            return

        content_type = {
            ".md": "text/markdown; charset=utf-8",
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }[path.suffix]

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def log_message(self, format: str, *args) -> None:
        """Keep server output compact."""

        print(f"{self.address_string()} - {format % args}")


class LocalDashboardHTTPServer(ThreadingHTTPServer):
    """Bind the local dashboard without reverse-DNS lookup.

    Python's default HTTPServer asks macOS for a fully-qualified host name
    during startup. On this machine that lookup can hang for 127.0.0.1, which
    prevents the LaunchAgent from reaching the listen step.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def main() -> None:
    args = parse_args()
    if not APP_DIR.exists():
        raise FileNotFoundError("app/ folder is missing.")

    handler = lambda *handler_args, **handler_kwargs: ProjectGwalaHandler(
        *handler_args,
        directory=str(APP_DIR),
        **handler_kwargs,
    )
    server = LocalDashboardHTTPServer((args.host, args.port), handler)
    print(f"Project Gwala app: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProject Gwala app stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
