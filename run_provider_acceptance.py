"""Verify that a market-data provider is returning usable current bars.

This is a data-quality preflight for the research/paper workflow. It does not
save candle caches, run scanners, place orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time as clock_time
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from data.polygon_data import fetch_polygon_aggs, normalize_polygon_aggs, polygon_aggs_url, polygon_api_key


Fetcher = Callable[[str], dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether provider intraday bars are current enough to trust.")
    parser.add_argument("--provider", choices=["polygon"], default="polygon", help="Market-data provider to test.")
    parser.add_argument("--symbols", nargs="+", default=["SPY", "QQQ"], help="Symbols to test before refresh.")
    parser.add_argument("--timeframes", nargs="+", default=["M5", "M30"], help="Timeframes to test before refresh.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where acceptance reports are saved.")
    parser.add_argument(
        "--max-lag-minutes",
        type=float,
        default=90.0,
        help="Maximum allowed lag once a current-session bar is present.",
    )
    parser.add_argument(
        "--today",
        default="",
        help="Override expected market session date for tests, YYYY-MM-DD. Defaults to current ET date.",
    )
    return parser.parse_args()


def regular_market_session(now: datetime) -> dict[str, Any]:
    """Return the local regular-session timing used for acceptance decisions."""

    open_time = clock_time(9, 30, tzinfo=MARKET_TZ)
    close_time = clock_time(16, 0, tzinfo=MARKET_TZ)
    local_now = now.astimezone(MARKET_TZ)
    session = market_session_for_date(local_now.date(), open_time, close_time)
    market_has_opened = bool(session.is_market_day and session.market_open and local_now >= session.market_open)
    market_is_open = bool(market_has_opened and session.market_close and local_now <= session.market_close)
    return {
        "now_et": local_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "today": str(local_now.date()),
        "market_is_open": market_is_open,
        "market_has_opened": market_has_opened,
        "market_open_et": session.market_open.strftime("%Y-%m-%d %H:%M:%S %Z") if session.market_open else "",
        "market_close_et": session.market_close.strftime("%Y-%m-%d %H:%M:%S %Z") if session.market_close else "",
        "market_reason": session.reason,
        "is_market_day": session.is_market_day,
    }


def latest_candle_details(candles: pd.DataFrame, now: datetime) -> dict[str, Any]:
    """Return readable details for the newest candle in a normalized frame."""

    latest = pd.to_datetime(candles["datetime"].iloc[-1], utc=True, errors="coerce")
    if pd.isna(latest):
        raise ValueError("Latest provider candle timestamp could not be parsed.")
    latest_et = latest.tz_convert(MARKET_TZ)
    latest_volume = pd.to_numeric(candles["volume"].iloc[-1], errors="coerce")
    lag = max(round((now.astimezone(MARKET_TZ) - latest_et).total_seconds() / 60, 1), 0)
    return {
        "latest_bar_utc": latest.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_bar_et": latest_et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "latest_session_et": str(latest_et.date()),
        "latest_volume": float(latest_volume) if pd.notna(latest_volume) else None,
        "volume_present": bool(pd.notna(latest_volume) and latest_volume > 0),
        "lag_minutes": lag,
    }


def check_polygon_pair(
    *,
    symbol: str,
    timeframe: str,
    session_date: str,
    api_key: str,
    now: datetime,
    max_lag_minutes: float,
    fetcher: Fetcher = fetch_polygon_aggs,
) -> dict[str, Any]:
    """Fetch one tiny Polygon sample and classify whether it is acceptable."""

    url = polygon_aggs_url(
        symbol=symbol,
        timeframe=timeframe,
        start_date=session_date,
        end_date=session_date,
        adjusted=True,
        api_key=api_key,
    )
    try:
        payload = fetcher(url)
        candles = normalize_polygon_aggs(payload)
        details = latest_candle_details(candles, now)
    except Exception as exc:  # noqa: BLE001 - provider diagnostics should survive varied API failures.
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "status": "error",
            "message": str(exc),
            "latest_bar_utc": "",
            "latest_bar_et": "",
            "latest_session_et": "",
            "latest_volume": None,
            "volume_present": False,
            "lag_minutes": None,
        }

    is_current_session = details["latest_session_et"] == session_date
    lag_ok = details["lag_minutes"] <= max_lag_minutes
    volume_ok = details["volume_present"]
    if is_current_session and lag_ok and volume_ok:
        status = "ok"
        message = "Provider returned current-session candles."
    elif not is_current_session:
        status = "previous_session_bars"
        message = "Provider response did not include current-session candles."
    elif not volume_ok:
        status = "missing_volume"
        message = "Provider response has no usable latest-bar volume."
    else:
        status = "too_lagged"
        message = f"Latest provider bar is more than {max_lag_minutes:g} minutes old."

    return {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "status": status,
        "message": message,
        **details,
    }


def build_acceptance_report(
    *,
    provider: str,
    symbols: list[str],
    timeframes: list[str],
    output_dir: Path,
    max_lag_minutes: float,
    now: datetime | None = None,
    today: str = "",
    api_key: str = "",
    fetcher: Fetcher = fetch_polygon_aggs,
) -> dict[str, Any]:
    """Build a provider acceptance report and write JSON/Markdown outputs."""

    current = now or datetime.now(MARKET_TZ)
    market = regular_market_session(current)
    session_date = today or market["today"]
    rows: list[dict[str, Any]] = []

    if provider != "polygon":
        raise ValueError(f"Unsupported provider acceptance check: {provider}")

    if market["market_has_opened"]:
        key = api_key or polygon_api_key()
        for symbol in symbols:
            for timeframe in timeframes:
                rows.append(
                    check_polygon_pair(
                        symbol=symbol,
                        timeframe=timeframe,
                        session_date=session_date,
                        api_key=key,
                        now=current,
                        max_lag_minutes=max_lag_minutes,
                        fetcher=fetcher,
                    )
                )
    else:
        rows = []

    failures = [row for row in rows if row["status"] != "ok"]
    if not market["market_has_opened"]:
        status = "prep_only"
        message = "Market has not opened today; current-session intraday acceptance is not required yet."
    elif not rows:
        status = "fail_request_error"
        message = "No provider acceptance checks ran."
    elif failures:
        failure_statuses = sorted(set(row["status"] for row in failures))
        if failure_statuses == ["previous_session_bars"]:
            status = "fail_provider_not_current"
            message = "Provider is returning previous-session bars for the tested intraday streams."
        else:
            status = "fail_provider_acceptance"
            message = "Provider acceptance failed for one or more tested intraday streams."
    else:
        status = "pass"
        message = "Provider returned usable current-session intraday bars for the tested streams."

    report = {
        "generated_at_et": current.astimezone(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "provider": provider,
        "status": status,
        "message": message,
        "session_date": session_date,
        "max_lag_minutes": max_lag_minutes,
        "market": market,
        "checks": rows,
    }
    write_reports(output_dir, report)
    return report


def write_reports(output_dir: Path, report: dict[str, Any]) -> None:
    """Write provider acceptance JSON and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "provider_acceptance.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Provider Acceptance",
        "",
        f"Status: {report['status']}",
        f"Provider: {report['provider']}",
        f"Session date: {report['session_date']}",
        f"Generated: {report['generated_at_et']}",
        "",
        report["message"],
        "",
        "## Checks",
        "",
        "| Symbol | Timeframe | Status | Latest bar ET | Lag min | Message |",
        "|---|---:|---|---|---:|---|",
    ]
    for row in report["checks"]:
        lag = "" if row["lag_minutes"] is None else f"{row['lag_minutes']:.1f}"
        lines.append(
            "| "
            f"{row['symbol']} | {row['timeframe']} | {row['status']} | "
            f"{row['latest_bar_et']} | {lag} | {row['message']} |"
        )
    if not report["checks"]:
        lines.append("| - | - | prep_only | - | - | Market has not opened today. |")
    (output_dir / "provider_acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    report = build_acceptance_report(
        provider=args.provider,
        symbols=[symbol.upper() for symbol in args.symbols],
        timeframes=[timeframe.upper() for timeframe in args.timeframes],
        output_dir=args.output_dir,
        max_lag_minutes=args.max_lag_minutes,
        today=args.today,
    )
    if report["status"].startswith("fail"):
        raise SystemExit(report["message"])
    print(f"Saved provider acceptance report: {args.output_dir / 'provider_acceptance.md'}")


if __name__ == "__main__":
    main()
