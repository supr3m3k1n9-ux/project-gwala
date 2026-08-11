"""Refresh readiness state for Project Gwala.

This module decides whether the system is ready to refresh Webull data and
whether paper importing should stay blocked. It is research/paper workflow
only and does not fetch data, place orders, create alerts, or connect to broker
execution.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.runtime_paths import runtime_data_root
from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from data.candle_cache import preferred_candle_path
from data.market_data_sources import read_sources
from reports.system_state import file_state, latest_scan_date, read_csv_or_empty, regular_market_times


REFRESH_COMMAND = "python run_daily_workflow.py --refresh-data --data-provider webull"
VALID_REFRESH_EVIDENCE = {"files_present_and_complete", "current_session_in_progress"}
# Webull refreshes the watchlist sequentially and may omit still-forming bars.
# These thresholds are for dashboard freshness warnings, not signal approval.
M5_STALE_MINUTES = 25
M30_STALE_MINUTES = 75


def approved_symbols() -> list[str]:
    """Return approved and watch playbook symbols once each."""

    return sorted(playbook_symbols("approved_plus_watch"))


def market_refresh_state() -> dict[str, Any]:
    """Return market timing details used by refresh decisions."""

    open_time, close_time = regular_market_times()
    now = datetime.now(MARKET_TZ)
    today = market_session_for_date(now.date(), open_time, close_time)
    upcoming = next_market_session(now, open_time, close_time)

    market_is_open = bool(
        today.is_market_day
        and today.market_open is not None
        and today.market_close is not None
        and today.market_open <= now <= today.market_close
    )

    if market_is_open:
        status = "market_open"
        reason = "Regular market session is open."
    elif today.is_market_day and today.market_open is not None and now < today.market_open:
        status = "before_open"
        reason = f"Market opens at {today.market_open:%H:%M} ET."
    elif today.is_market_day and today.market_close is not None and now > today.market_close:
        status = "after_close"
        reason = f"Market closed at {today.market_close:%H:%M} ET."
    else:
        status = "market_closed"
        reason = today.reason

    return {
        "now_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "today": str(now.date()),
        "market_status": status,
        "market_status_reason": reason,
        "market_is_open": market_is_open,
        "next_market_session": str(upcoming.session_date),
        "next_market_session_status": upcoming.reason,
    }


def webull_csv_states(output_dir: Path) -> list[dict[str, Any]]:
    """Return M30/M5 CSV file states for approved and watch symbols."""

    rows = []
    now = datetime.now(MARKET_TZ)
    for symbol in approved_symbols():
        entry_path = preferred_candle_path(output_dir, symbol, "M30")
        exit_path = preferred_candle_path(output_dir, symbol, "M5")
        entry = file_state(entry_path)
        exit_ = file_state(exit_path)
        entry_candle = latest_candle_state(entry_path, now)
        exit_candle = latest_candle_state(exit_path, now)
        rows.append(
            {
                "symbol": symbol,
                "m30_exists": entry["exists"],
                "m30_modified_et": entry["modified_et"],
                "m30_latest_bar_et": entry_candle["latest_bar_et"],
                "m30_bar_age_minutes": entry_candle["bar_age_minutes"],
                "m30_freshness_status": freshness_status(entry_candle["bar_age_minutes"], M30_STALE_MINUTES),
                "m5_exists": exit_["exists"],
                "m5_modified_et": exit_["modified_et"],
                "m5_latest_bar_et": exit_candle["latest_bar_et"],
                "m5_bar_age_minutes": exit_candle["bar_age_minutes"],
                "m5_freshness_status": freshness_status(exit_candle["bar_age_minutes"], M5_STALE_MINUTES),
            }
        )
    return rows


def latest_candle_state(path: Path, now: datetime) -> dict[str, Any]:
    """Return the latest saved candle timestamp and its age.

    Invalid placeholder CSVs are treated as unknown instead of failing the
    refresh-status report. The dashboard should warn, not crash.
    """

    if not path.exists():
        return {"latest_bar_et": "", "bar_age_minutes": None}
    try:
        candles = pd.read_csv(path, usecols=["datetime"])
    except (ValueError, pd.errors.EmptyDataError):
        return {"latest_bar_et": "", "bar_age_minutes": None}
    if candles.empty:
        return {"latest_bar_et": "", "bar_age_minutes": None}

    latest = pd.to_datetime(candles["datetime"].dropna().iloc[-1], utc=True, errors="coerce")
    if pd.isna(latest):
        return {"latest_bar_et": "", "bar_age_minutes": None}

    latest_et = latest.tz_convert(MARKET_TZ)
    age = max(round((now - latest_et).total_seconds() / 60, 1), 0)
    return {
        "latest_bar_et": latest_et.strftime("%Y-%m-%d %H:%M %Z"),
        "bar_age_minutes": age,
    }


def freshness_status(age_minutes: float | None, threshold_minutes: int) -> str:
    """Classify one candle stream against a market-hours age threshold."""

    if age_minutes is None:
        return "unknown"
    return "fresh" if age_minutes <= threshold_minutes else "stale"


def candle_freshness_summary(csv_states: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any]:
    """Summarize 5m/30m candle age so the dashboard can warn clearly."""

    m5_ages = [row["m5_bar_age_minutes"] for row in csv_states if row.get("m5_bar_age_minutes") is not None]
    m30_ages = [row["m30_bar_age_minutes"] for row in csv_states if row.get("m30_bar_age_minutes") is not None]
    stale_5m = [row["symbol"] for row in csv_states if row.get("m5_freshness_status") == "stale"]
    stale_30m = [row["symbol"] for row in csv_states if row.get("m30_freshness_status") == "stale"]
    unknown = [
        row["symbol"]
        for row in csv_states
        if row.get("m5_freshness_status") == "unknown" or row.get("m30_freshness_status") == "unknown"
    ]

    if market.get("market_is_open", False) and (stale_5m or stale_30m):
        status = "stale"
    elif market.get("market_is_open", False):
        status = "unknown" if unknown else "fresh"
    else:
        status = "unknown" if unknown else "outside_market_hours"

    return {
        "status": status,
        "m5_threshold_minutes": M5_STALE_MINUTES,
        "m30_threshold_minutes": M30_STALE_MINUTES,
        "max_m5_age_minutes": max(m5_ages) if m5_ages else None,
        "max_m30_age_minutes": max(m30_ages) if m30_ages else None,
        "stale_m5_symbols": stale_5m,
        "stale_m30_symbols": stale_30m,
        "unknown_symbols": sorted(set(unknown)),
    }


def latest_provider_refresh_summary(source_csv: Path, market: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether the latest provider refresh produced current-session bars.

    A data provider can refresh successfully while still returning only the
    previous session's aggregate bars. That is useful historical data, but it
    is not enough for current-candle paper validation during market hours.
    """

    sources = read_sources(source_csv)
    if sources.empty:
        return {
            "status": "not_recorded",
            "provider": "unknown",
            "latest_refreshed_at_et": "",
            "ok_rows": 0,
            "required_rows": 0,
            "current_session_rows": 0,
            "previous_session_rows": 0,
            "message": "No provider refresh metadata has been recorded yet.",
        }

    today = str(market["today"])
    required_symbols = approved_symbols()
    required_timeframes = {"M5", "M30"}
    latest_rows: list[pd.Series] = []
    for symbol in required_symbols:
        for timeframe in required_timeframes:
            matches = sources[
                sources["symbol"].astype(str).str.upper().eq(symbol.upper())
                & sources["timeframe"].astype(str).str.upper().eq(timeframe)
            ]
            if matches.empty:
                continue
            latest_rows.append(matches.iloc[-1])

    required_count = len(required_symbols) * len(required_timeframes)
    if not latest_rows:
        return {
            "status": "not_recorded",
            "provider": "unknown",
            "latest_refreshed_at_et": "",
            "ok_rows": 0,
            "required_rows": required_count,
            "current_session_rows": 0,
            "previous_session_rows": 0,
            "message": "No matching provider refresh rows were found for M5/M30 candles.",
        }

    latest = pd.DataFrame(latest_rows)
    ok = latest[latest["status"].astype(str) == "ok"].copy()
    provider = str(latest["provider"].dropna().iloc[-1]) if "provider" in latest.columns else "unknown"
    latest_refreshed = str(latest["refreshed_at_et"].dropna().iloc[-1]) if "refreshed_at_et" in latest.columns else ""
    current_rows = 0
    previous_rows = 0
    if not ok.empty and "latest_candle_utc" in ok.columns:
        candle_times = pd.to_datetime(ok["latest_candle_utc"], utc=True, errors="coerce")
        candle_dates = candle_times.dt.tz_convert(MARKET_TZ).dt.date.astype(str)
        current_rows = int((candle_dates == today).sum())
        previous_rows = int((candle_dates < today).sum())

    if len(ok) < required_count:
        status = "partial_refresh"
        message = "The latest provider refresh is missing one or more required M5/M30 rows."
    elif current_rows == len(ok):
        status = "current_session_bars"
        message = "The latest provider refresh includes current-session M5/M30 bars."
    elif market.get("market_is_open", False) and previous_rows == len(ok):
        status = "provider_previous_session_bars"
        message = (
            "The provider refreshed successfully, but the latest saved M5/M30 bars "
            "are still from the previous session."
        )
    else:
        status = "mixed_or_stale"
        message = "The latest provider refresh has mixed or stale M5/M30 bar dates."

    return {
        "status": status,
        "provider": provider,
        "latest_refreshed_at_et": latest_refreshed,
        "ok_rows": int(len(ok)),
        "required_rows": required_count,
        "current_session_rows": current_rows,
        "previous_session_rows": previous_rows,
        "message": message,
    }


def scanner_refresh_state(output_dir: Path) -> dict[str, Any]:
    """Return scanner freshness and current candidate counts."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    current_count = 0
    allowed_current_symbols: list[str] = []
    if not scanner.empty:
        current = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]
        current_count = len(current)
        allowed_current = current[current["scanner_status"] == "allowed"]
        allowed_current_symbols = sorted(set(allowed_current["symbol"].astype(str).str.upper()))

    return {
        "latest_scanner_session": latest_scan_date(scanner) or "unknown",
        "scanner_rows": int(len(scanner)),
        "current_candidate_count": int(current_count),
        "allowed_current_candidate_count": int(len(allowed_current_symbols)),
        "allowed_current_candidate_symbols": allowed_current_symbols,
    }


def build_refresh_status(
    output_dir: Path = Path("logs"),
    audit_csv: Path | None = None,
    source_csv: Path | None = None,
) -> dict[str, Any]:
    """Build refresh and paper-import readiness state."""

    audit_csv = audit_csv or runtime_data_root() / "market_refresh_audit.csv"
    market = market_refresh_state()
    scanner = scanner_refresh_state(output_dir)
    csv_states = webull_csv_states(output_dir)
    candle_freshness = candle_freshness_summary(csv_states, market)
    provider_refresh = latest_provider_refresh_summary(source_csv or output_dir / "market_data_sources.csv", market)
    missing = [
        row["symbol"]
        for row in csv_states
        if not row["m30_exists"] or not row["m5_exists"]
    ]
    audit = read_csv_or_empty(audit_csv)
    audited_symbols: set[str] = set()
    required_audit_columns = {"symbol", "m30_latest_session", "m5_latest_session", "refresh_evidence_status"}
    if required_audit_columns.issubset(audit.columns):
        current_audit = audit[
            (audit["m30_latest_session"].astype(str) == market["today"])
            & (audit["m5_latest_session"].astype(str) == market["today"])
            & (audit["refresh_evidence_status"].isin(VALID_REFRESH_EVIDENCE))
        ]
        audited_symbols = set(current_audit["symbol"].astype(str).str.upper())

    if missing:
        status = "blocked_missing_csv"
        reason = f"Missing Webull CSV files for: {', '.join(missing)}."
    elif not market["market_is_open"]:
        status = "prep_only"
        reason = f"Market is not open: {market['market_status_reason']}"
    elif (
        candle_freshness.get("status") == "stale"
        and provider_refresh.get("status") == "provider_previous_session_bars"
    ):
        status = "blocked_provider_previous_session_bars"
        provider = str(provider_refresh.get("provider") or "The provider").strip()
        reason = (
            f"{provider} refresh metadata exists, but the latest saved intraday bars "
            "are still from the previous session."
        )
    else:
        status = "ready_to_refresh"
        reason = "Market is open and required local CSV paths are present."

    data_is_fresh_today = scanner["latest_scanner_session"] == market["today"] and market["market_is_open"]
    allowed_symbols = set(scanner["allowed_current_candidate_symbols"])
    has_allowed_candidates = scanner["allowed_current_candidate_count"] > 0
    has_refresh_evidence = bool(allowed_symbols) and allowed_symbols.issubset(audited_symbols)
    paper_import_blocked = (not data_is_fresh_today) or (not has_allowed_candidates) or (not has_refresh_evidence)
    if not data_is_fresh_today or not has_allowed_candidates:
        paper_import_reason = "Blocked until refreshed current-session data creates current-candle candidates."
    elif not has_refresh_evidence:
        paper_import_reason = "Blocked until current-session Webull refresh evidence is recorded for allowed candidates."
    else:
        paper_import_reason = "Current-session current-candle candidates exist; review checklist before importing."

    if status == "blocked_provider_previous_session_bars":
        next_action = (
            "Keep paper import blocked. Try the refresh again later or use a data provider "
            "that returns current-session intraday bars."
        )
    elif status == "ready_to_refresh":
        next_action = f"Run {REFRESH_COMMAND}, then review app/dashboard outputs."
    else:
        next_action = f"On {market['next_market_session']} during market hours, run {REFRESH_COMMAND}."

    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "refresh_command": REFRESH_COMMAND,
        "paper_import_blocked": paper_import_blocked,
        "paper_import_reason": paper_import_reason,
        "market": market,
        "scanner": scanner,
        "candle_freshness": candle_freshness,
        "provider_refresh": provider_refresh,
        "webull_csvs": csv_states,
    }
