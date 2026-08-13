"""Audit saved production candle data for freshness and structural integrity.

This is an evidence-integrity guardrail. It reads existing candle and refresh
artifacts, writes an audit report, and never fetches market data or mutates
paper-trading evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.runtime_paths import runtime_data_root
from config.settings import STRATEGY
from data.candle_cache import preferred_candle_path
from run_production_heartbeat import previous_market_session_date, session_context


SYMBOLS = ["SPY", "QQQ", "AAPL", "AMD", "META", "MSFT", "NVDA", "TSLA"]
TIMEFRAMES = ["M1", "M5", "M15", "M30", "M60", "D"]
TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "M60": 60}
REQUIRED_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
PROVIDER_FINAL_TOLERANCE_MINUTES = 5
TIMEFRAME_DEPENDENCIES = {
    "M1": {
        "production_role": "display_chart",
        "component": "Command Center chart lookback",
        "entry_decision": False,
        "exit_management": False,
        "context_only": False,
        "chart_display": True,
        "decision_critical": False,
    },
    "M5": {
        "production_role": "exit_management",
        "component": "paper lifecycle exit management",
        "entry_decision": False,
        "exit_management": True,
        "context_only": False,
        "chart_display": False,
        "decision_critical": True,
    },
    "M15": {
        "production_role": "display_chart",
        "component": "Command Center chart lookback",
        "entry_decision": False,
        "exit_management": False,
        "context_only": False,
        "chart_display": True,
        "decision_critical": False,
    },
    "M30": {
        "production_role": "entry_decision",
        "component": "scanner/current-candle entry decisions",
        "entry_decision": True,
        "exit_management": False,
        "context_only": False,
        "chart_display": False,
        "decision_critical": True,
    },
    "M60": {
        "production_role": "supporting_context",
        "component": "higher-timeframe review context",
        "entry_decision": False,
        "exit_management": False,
        "context_only": True,
        "chart_display": True,
        "decision_critical": False,
    },
    "D": {
        "production_role": "completed_daily_context",
        "component": "daily context/display only",
        "entry_decision": False,
        "exit_management": False,
        "context_only": True,
        "chart_display": True,
        "decision_critical": False,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit saved market-data freshness and continuity.")
    parser.add_argument("--data-dir", type=Path, default=runtime_data_root(), help="Durable runtime data directory.")
    parser.add_argument("--candle-dir", type=Path, default=Path("logs"), help="Directory containing saved candle cache files.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Directory for audit artifacts.")
    parser.add_argument("--now", default="", help="Optional ET timestamp for deterministic audits/tests.")
    return parser.parse_args()


def parse_moment(value: str) -> datetime | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid --now timestamp: {value}")
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(MARKET_TZ)
    return timestamp.tz_convert(MARKET_TZ).to_pydatetime()


def regular_session(moment: datetime):
    local = moment.astimezone(MARKET_TZ)
    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    return market_session_for_date(local.date(), open_time, close_time)


def expected_latest_bucket(moment: datetime, timeframe: str, expected_date: object) -> datetime | None:
    """Return the expected latest completed candle start for the session context."""

    if timeframe == "D":
        context = session_context(moment)
        expected_daily_date = expected_date
        if context["phase"] in {"premarket", "regular_session"}:
            expected_daily_date = previous_market_session_date(moment)
        return datetime.combine(expected_daily_date, datetime.min.time()).replace(tzinfo=MARKET_TZ)
    minutes = TIMEFRAME_MINUTES[timeframe]
    session = market_session_for_date(
        expected_date,
        datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ),
        datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ),
    )
    if session.market_open is None or session.market_close is None:
        return None
    context = session_context(moment)
    if context["phase"] == "regular_session" and context["requires_recency"]:
        elapsed = max(int((moment.astimezone(MARKET_TZ) - session.market_open).total_seconds() // 60), 0)
        complete_buckets = max(elapsed // minutes - 1, 0)
        return min(session.market_open + timedelta(minutes=complete_buckets * minutes), session.market_close - timedelta(minutes=minutes))
    if context["phase"] in {"after_close", "closed_day"}:
        return session.market_close - timedelta(minutes=minutes)
    return session.market_open


def expected_session_buckets(expected_date: object, timeframe: str, latest_expected: datetime | None) -> list[pd.Timestamp]:
    if timeframe == "D" or latest_expected is None:
        return []
    minutes = TIMEFRAME_MINUTES[timeframe]
    session = market_session_for_date(
        expected_date,
        datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ),
        datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ),
    )
    if session.market_open is None:
        return []
    buckets = []
    current = pd.Timestamp(session.market_open)
    latest = pd.Timestamp(latest_expected)
    while current <= latest:
        buckets.append(current)
        current += pd.Timedelta(minutes=minutes)
    return buckets


def load_refresh_audit(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "market_refresh_audit.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def refresh_status_for(audit: pd.DataFrame, symbol: str, timeframe: str) -> dict[str, str]:
    if audit.empty:
        return {"status": "unknown", "detail": "market_refresh_audit.csv unavailable"}
    frame = audit.copy()
    candidates = frame
    if "symbol" in candidates.columns:
        candidates = candidates[candidates["symbol"].astype(str).str.upper().eq(symbol)]
    if timeframe.lower() + "_latest_session" in candidates.columns:
        column = timeframe.lower() + "_latest_session"
    else:
        column = "latest_session" if "latest_session" in candidates.columns else ""
    if candidates.empty:
        return {"status": "unknown", "detail": "no refresh rows for symbol"}
    latest = candidates.iloc[-1]
    detail = str(latest.get(column, "")) if column else "refresh row present"
    status = str(latest.get("status", latest.get("refresh_status", "ok")) or "ok").lower()
    return {"status": status, "detail": detail}


def read_candle_frame(path: Path) -> tuple[pd.DataFrame, str]:
    if not path.exists():
        return pd.DataFrame(), "missing"
    try:
        raw = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), "empty"
    except (OSError, pd.errors.ParserError):
        return pd.DataFrame(), "unreadable"
    return raw, "ok"


def inspect_stream(
    symbol: str,
    timeframe: str,
    candle_dir: Path,
    moment: datetime,
    refresh_audit: pd.DataFrame,
) -> dict[str, Any]:
    context = session_context(moment)
    expected_date = context["expected_artifact_date"]
    path = preferred_candle_path(candle_dir, symbol, timeframe)
    dependency = TIMEFRAME_DEPENDENCIES[timeframe]
    base: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "FAIL",
        "path": str(path),
        "session_date": "",
        "latest_timestamp_et": "",
        "expected_latest_timestamp_et": "",
        "lag_minutes": None,
        "missing_count": 0,
        "missing_intervals": [],
        "duplicate_bars": 0,
        "out_of_order_bars": 0,
        "malformed_rows": 0,
        "mixed_session_rows": 0,
        "provider_final": False,
        "file_mtime_et": "",
        "refresh_audit_status": "",
        "explanation": "",
        "freshness_status": "FAIL",
        "production_role": dependency["production_role"],
        "consumer_component": dependency["component"],
        "entry_decision_required": dependency["entry_decision"],
        "exit_management_required": dependency["exit_management"],
        "context_only": dependency["context_only"],
        "chart_display_only": dependency["chart_display"],
        "decision_critical": dependency["decision_critical"],
    }
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=MARKET_TZ)
        base["file_mtime_et"] = mtime.strftime("%Y-%m-%d %H:%M:%S %Z")
    raw, load_status = read_candle_frame(path)
    refresh = refresh_status_for(refresh_audit, symbol, timeframe)
    base["refresh_audit_status"] = refresh["status"]
    if load_status != "ok":
        return {**base, "explanation": f"Candle file is {load_status}."}
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing_columns:
        return {**base, "malformed_rows": int(len(raw)), "explanation": f"Missing columns: {', '.join(missing_columns)}."}

    frame = raw[REQUIRED_COLUMNS].copy()
    parsed = pd.to_datetime(frame["datetime"], errors="coerce", utc=True)
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    malformed = int(parsed.isna().sum() + numeric.isna().any(axis=1).sum())
    valid = frame[parsed.notna()].copy()
    if valid.empty:
        return {**base, "malformed_rows": malformed, "explanation": "No parseable candle timestamps."}
    local_times = parsed[parsed.notna()].dt.tz_convert(MARKET_TZ)
    latest = local_times.max()
    expected_latest = expected_latest_bucket(moment, timeframe, expected_date)
    base["latest_timestamp_et"] = latest.strftime("%Y-%m-%d %H:%M:%S %Z")
    base["session_date"] = str(latest.date())
    if expected_latest is not None:
        base["expected_latest_timestamp_et"] = expected_latest.strftime("%Y-%m-%d %H:%M:%S %Z")
        base["lag_minutes"] = max(round((expected_latest - latest.to_pydatetime()).total_seconds() / 60, 1), 0)

    duplicates = int(local_times.duplicated().sum())
    out_of_order = int((local_times.sort_index().diff().dropna() < pd.Timedelta(0)).sum())
    base["duplicate_bars"] = duplicates
    base["out_of_order_bars"] = out_of_order
    base["malformed_rows"] = malformed
    if duplicates:
        return {**base, "explanation": "Duplicate candle timestamps found."}
    if out_of_order:
        return {**base, "explanation": "Candle timestamps are out of order."}
    if malformed:
        return {**base, "explanation": "Malformed timestamp or OHLCV rows found."}
    expected_latest_date = expected_latest.date() if expected_latest is not None else expected_date
    if latest.date() != expected_latest_date:
        status = "FAIL" if dependency["decision_critical"] else "WATCH"
        return {
            **base,
            "status": status,
            "freshness_status": "FAIL",
            "explanation": f"Latest candle belongs to {latest.date()}, expected {expected_latest_date}.",
        }

    if timeframe != "D":
        session_times = local_times[local_times.dt.date == expected_date]
        expected_buckets = expected_session_buckets(expected_date, timeframe, expected_latest)
        present = {pd.Timestamp(value).floor("min") for value in session_times}
        missing = [bucket for bucket in expected_buckets if bucket not in present]
        base["missing_count"] = len(missing)
        base["missing_intervals"] = [bucket.strftime("%H:%M") for bucket in missing[:40]]
        if missing:
            if not dependency["decision_critical"]:
                base["status"] = "WATCH"
                base["freshness_status"] = "FAIL"
                base["explanation"] = f"Non-decision {timeframe} stream is missing {len(missing)} expected interval(s)."
                return base
            final_tolerance = context["phase"] in {"after_close", "closed_day"} and latest >= (expected_latest - timedelta(minutes=PROVIDER_FINAL_TOLERANCE_MINUTES))
            if final_tolerance and len(missing) <= 1:
                base["status"] = "WATCH"
                base["freshness_status"] = "WATCH"
                base["provider_final"] = True
                base["explanation"] = "Provider appears to have omitted only the final tolerated bar."
                return base
            return {**base, "explanation": f"Missing {len(missing)} expected {timeframe} interval(s)."}

    lag = float(base["lag_minutes"] or 0)
    if context["phase"] == "regular_session" and context["requires_recency"] and lag > max(TIMEFRAME_MINUTES.get(timeframe, 1), 2):
        if not dependency["decision_critical"]:
            return {
                **base,
                "status": "WATCH",
                "freshness_status": "FAIL",
                "explanation": f"Non-decision {timeframe} stream is stale by {lag:g} minutes during market hours.",
            }
        return {**base, "explanation": f"{timeframe} is stale by {lag:g} minutes during market hours."}
    if str(refresh["status"]).lower() in {"fail", "failed", "red"}:
        return {**base, "explanation": f"Refresh audit reports failure: {refresh['detail']}."}
    base["status"] = "PASS"
    base["freshness_status"] = "PASS"
    base["explanation"] = "Candle stream is structurally valid for the expected session."
    return base


def aggregate_streams(streams: list[dict[str, Any]]) -> tuple[str, str]:
    critical_statuses = {stream["status"] for stream in streams if stream.get("decision_critical")}
    all_statuses = {stream["status"] for stream in streams}
    raw_statuses = {stream.get("freshness_status", stream["status"]) for stream in streams}
    if "FAIL" in critical_statuses:
        return "FAIL", "INVALID"
    if "FAIL" in raw_statuses or "WATCH" in all_statuses:
        return "WATCH", "PARTIAL"
    return "PASS", "CLEAN"


def build_audit(data_dir: Path, moment: datetime | None = None, candle_dir: Path | None = None) -> dict[str, Any]:
    now = (moment or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    context = session_context(now)
    refresh_audit = load_refresh_audit(data_dir)
    candles = candle_dir or data_dir
    streams = [
        inspect_stream(symbol, timeframe, candles, now, refresh_audit)
        for symbol in SYMBOLS
        for timeframe in TIMEFRAMES
    ]
    continuity, evidence = aggregate_streams(streams)
    non_green = [stream for stream in streams if stream["status"] != "PASS"]
    raw_non_green = [stream for stream in streams if stream.get("freshness_status", stream["status"]) != "PASS"]
    return {
        "generated_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": continuity,
        "data_continuity": continuity,
        "session_evidence": evidence,
        "market_phase": context["phase"],
        "expected_session_date": str(context["expected_artifact_date"]),
        "symbols": SYMBOLS,
        "timeframes": TIMEFRAMES,
        "timeframe_dependencies": TIMEFRAME_DEPENDENCIES,
        "streams": streams,
        "matrix": {
            symbol: {stream["timeframe"]: stream for stream in streams if stream["symbol"] == symbol}
            for symbol in SYMBOLS
        },
        "needs_attention": [
            {
                "symbol": stream["symbol"],
                "timeframe": stream["timeframe"],
                "status": stream["status"],
                "freshness_status": stream.get("freshness_status", stream["status"]),
                "production_role": stream.get("production_role", ""),
                "decision_critical": stream.get("decision_critical", False),
                "explanation": stream["explanation"],
                "lag_minutes": stream["lag_minutes"],
            }
            for stream in non_green[:20]
        ],
        "raw_freshness_attention": [
            {
                "symbol": stream["symbol"],
                "timeframe": stream["timeframe"],
                "status": stream.get("freshness_status", stream["status"]),
                "production_status": stream["status"],
                "production_role": stream.get("production_role", ""),
                "decision_critical": stream.get("decision_critical", False),
                "explanation": stream["explanation"],
                "lag_minutes": stream["lag_minutes"],
            }
            for stream in raw_non_green[:40]
        ],
        "last_successful_refresh": latest_refresh_timestamp(refresh_audit),
        "last_full_continuity_pass": now.strftime("%Y-%m-%d %H:%M:%S %Z") if continuity == "PASS" else "",
        "guardrail": "Read-only market-data audit. No Webull fetches, strategy changes, or evidence mutations.",
    }


def latest_refresh_timestamp(audit: pd.DataFrame) -> str:
    if audit.empty:
        return ""
    for column in ("refresh_run_at_et", "generated_at_et", "timestamp_et"):
        if column in audit.columns:
            values = audit[column].astype(str).replace("", pd.NA).dropna()
            return str(values.iloc[-1]) if not values.empty else ""
    return ""


def write_audit(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data_freshness_audit.json"
    md_path = output_dir / "data_freshness_audit.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    attention = payload.get("needs_attention", [])
    lines = [
        "# Data Freshness & Integrity Audit",
        "",
        f"Generated: {payload.get('generated_at_et', '')}",
        f"DATA CONTINUITY: {payload.get('data_continuity', payload.get('status', 'UNKNOWN'))}",
        f"SESSION EVIDENCE: {payload.get('session_evidence', 'UNKNOWN')}",
        f"Market phase: {payload.get('market_phase', 'UNKNOWN')}",
        f"Expected session: {payload.get('expected_session_date', 'UNKNOWN')}",
        "",
        "## Needs Attention",
        "",
    ]
    if attention:
        lines.extend(
            f"- {item.get('status', 'FAIL')} {item.get('symbol', '--')} {item.get('timeframe', '--')}: {item.get('explanation', 'Review stream.')}"
            for item in attention
        )
    else:
        lines.append("- PASS: All audited streams are current and structurally valid.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    args = parse_args()
    payload = build_audit(args.data_dir, parse_moment(args.now), candle_dir=args.candle_dir)
    json_path, md_path = write_audit(payload, args.output_dir)
    print(f"DATA CONTINUITY: {payload['data_continuity']}")
    print(f"SESSION EVIDENCE: {payload['session_evidence']}")
    print(f"Saved freshness JSON: {json_path}")
    print(f"Saved freshness report: {md_path}")
    if payload["data_continuity"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
