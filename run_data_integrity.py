"""Check local candle files used by forward paper-validation reports.

This is research and paper workflow only. It identifies missing, duplicated,
malformed, stale, or incomplete candle data before observations are trusted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from run_playbook import markdown_table


REQUIRED_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
PROVIDER_FINAL_BAR_TOLERANCE_MINUTES = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check local Webull candle-data integrity.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull candle CSVs live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def approved_symbols() -> list[str]:
    """Return symbols currently used by the approved/watch playbook."""

    return sorted(playbook_symbols("approved_plus_watch"))


def expected_final_bar(session_date) -> datetime | None:
    """Return the expected last 5m bar timestamp for a market session."""

    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    session = market_session_for_date(session_date, open_time, close_time)
    return None if session.market_close is None else session.market_close - timedelta(minutes=5)


def provider_final_bar(session_date) -> datetime | None:
    """Return the latest bar that is complete enough for providers ending early.

    Some Webull refreshes return the 15:50 ET bar as the final available 5m
    candle for a 16:00 ET close. That bar still gives closed-session outcome
    evidence, but it is weaker than full 15:55 force-exit coverage.
    """

    expected = expected_final_bar(session_date)
    if expected is None:
        return None
    return expected - timedelta(minutes=PROVIDER_FINAL_BAR_TOLERANCE_MINUTES)


def session_coverage_for_latest(latest_session, latest_time: datetime, now: datetime | None = None) -> str:
    """Classify 5m coverage for the latest available regular-session bar."""

    expected = expected_final_bar(latest_session)
    if expected is not None and latest_time >= expected:
        return "complete"

    provider_expected = provider_final_bar(latest_session)
    if provider_expected is not None and latest_time >= provider_expected:
        return "provider_final_bar"

    now = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    session = market_session_for_date(latest_session, open_time, close_time)
    active_session = bool(
        latest_session == now.date()
        and session.market_open is not None
        and session.market_close is not None
        and session.market_open <= now <= session.market_close
    )
    return "in_progress" if active_session else "partial_session"


def coverage_is_issue(status: object, session_coverage: object) -> bool:
    """Return whether a file status should count as an integrity issue."""

    return str(status) != "ok" or str(session_coverage) == "partial_session"


def inspect_file(symbol: str, timeframe: str, path: Path, now: datetime | None = None) -> dict:
    """Inspect one local candle CSV."""

    base = {"symbol": symbol, "timeframe": timeframe, "path": str(path)}
    if not path.exists():
        return {**base, "status": "missing", "rows": 0, "duplicate_timestamps": 0, "invalid_rows": 0, "latest_session": "", "latest_bar_et": "", "session_coverage": "missing"}

    try:
        raw = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return {**base, "status": "empty", "rows": 0, "duplicate_timestamps": 0, "invalid_rows": 0, "latest_session": "", "latest_bar_et": "", "session_coverage": "empty"}

    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing:
        return {**base, "status": "missing_columns", "rows": len(raw), "duplicate_timestamps": 0, "invalid_rows": len(raw), "latest_session": "", "latest_bar_et": "", "session_coverage": ", ".join(missing)}

    frame = raw[REQUIRED_COLUMNS].copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce", utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    numeric_invalid = frame[REQUIRED_COLUMNS].isna().any(axis=1)
    ohlc_invalid = (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (frame["low"] > frame[["open", "close", "high"]].min(axis=1)) | (frame["volume"] < 0)
    invalid_rows = int((numeric_invalid | ohlc_invalid).sum())
    duplicates = int(frame["datetime"].duplicated().sum())
    valid = frame.dropna(subset=["datetime"])
    if valid.empty:
        return {**base, "status": "invalid", "rows": len(raw), "duplicate_timestamps": duplicates, "invalid_rows": invalid_rows, "latest_session": "", "latest_bar_et": "", "session_coverage": "no valid datetimes"}

    local = valid["datetime"].dt.tz_convert(MARKET_TZ)
    latest_time = local.max()
    latest_session = latest_time.date()
    coverage = "not_applicable"
    if timeframe == "M5":
        coverage = session_coverage_for_latest(latest_session, latest_time, now=now)
    status = "ok"
    if duplicates or invalid_rows:
        status = "warning"
    return {
        **base,
        "status": status,
        "rows": int(len(raw)),
        "duplicate_timestamps": duplicates,
        "invalid_rows": invalid_rows,
        "latest_session": str(latest_session),
        "latest_bar_et": latest_time.strftime("%Y-%m-%d %H:%M"),
        "session_coverage": coverage,
    }


def build_integrity(data_dir: Path) -> pd.DataFrame:
    """Inspect all local M30/M5 files for approved symbols."""

    rows = []
    for symbol in approved_symbols():
        for timeframe in ["M30", "M5"]:
            rows.append(inspect_file(symbol, timeframe, data_dir / f"webull_{symbol}_{timeframe}_candles.csv"))
    return pd.DataFrame(rows)


def write_report(path: Path, integrity: pd.DataFrame) -> None:
    """Write data integrity report."""

    issues = integrity[
        integrity.apply(lambda row: coverage_is_issue(row["status"], row["session_coverage"]), axis=1)
    ] if not integrity.empty else pd.DataFrame()
    path.write_text(
        f"""# Candle Data Integrity

This report checks local market-data files used by the paper-validation
workflow.

Important: this is research/paper workflow only. A data warning means review
or refresh data before trusting observation grading.

## Issues Requiring Attention

{markdown_table(issues)}

## All Checked Files

{markdown_table(integrity)}

## Checks Performed

```text
required OHLCV columns
parseable timestamps and numeric values
duplicate candle timestamps
valid high/low relationships and non-negative volume
latest 5m session coverage through its expected final regular-session bar
provider_final_bar means the final returned 5m candle is one bar before the
configured force-exit bar; outcomes can be graded, but the report keeps this
provider convention visible
```

## Files

```text
logs/candle_data_integrity.csv
logs/candle_data_integrity.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    integrity = build_integrity(args.data_dir)
    csv_path = args.output_dir / "candle_data_integrity.csv"
    report_path = args.output_dir / "candle_data_integrity.md"
    integrity.to_csv(csv_path, index=False)
    write_report(report_path, integrity)
    issue_count = int(
        integrity.apply(lambda row: coverage_is_issue(row["status"], row["session_coverage"]), axis=1).sum()
    ) if not integrity.empty else 0
    print(f"Candle files checked: {len(integrity)}")
    print(f"Integrity warnings: {issue_count}")
    print(f"Saved integrity CSV: {csv_path}")
    print(f"Saved integrity report: {report_path}")


if __name__ == "__main__":
    main()
