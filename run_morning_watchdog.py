"""Report whether the scheduled morning paper workflow actually ran.

This is a local watchdog for the research and paper-validation workflow. It
does not fetch market data, import paper trades, place broker orders, or create
alerts. It only reads the workflow artifacts already written by other scripts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.settings import STRATEGY
from run_autonomous_paper_workflow import parse_clock
from run_playbook import markdown_table


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the morning autonomous workflow watchdog report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def now_et() -> datetime:
    """Return the current New York time."""

    return datetime.now(MARKET_TZ)


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object if it exists and is valid."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV file if it exists."""

    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def modified_at_et(path: Path) -> datetime | None:
    """Return file modification time in New York time."""

    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=MARKET_TZ)


def parse_et_datetime(value: object) -> datetime | None:
    """Parse a saved ET timestamp from reports."""

    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace(" EDT", "-04:00").replace(" EST", "-05:00")
    parsed = pd.to_datetime(normalized, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = parsed.to_pydatetime()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=MARKET_TZ)
    return timestamp.astimezone(MARKET_TZ)


def same_et_day(value: datetime | None, day: object) -> bool:
    """Return True when value lands on the supplied ET date."""

    return bool(value and value.astimezone(MARKET_TZ).date() == day)


def scanner_session_today(scanner: pd.DataFrame, today: object) -> bool:
    """Return True if scanner rows belong to today's session."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return False
    dates = pd.to_datetime(scanner["scan_date"], errors="coerce").dropna()
    if dates.empty:
        return False
    return dates.dt.date.max() == today


def current_candidate_counts(scanner: pd.DataFrame) -> dict[str, int]:
    """Count current-candle scanner rows and reviewable rows."""

    if scanner.empty:
        return {"current": 0, "reviewable": 0, "allowed": 0}
    current = scanner
    if "signal_freshness" in scanner.columns:
        current = scanner[scanner["signal_freshness"].eq("current_candle")]
    if "scanner_status" not in current.columns:
        return {"current": int(len(current)), "reviewable": 0, "allowed": 0}
    allowed = current[current["scanner_status"].eq("allowed")]
    reviewable = current[current["scanner_status"].isin(["allowed", "blocked_watch_only"])]
    return {"current": int(len(current)), "reviewable": int(len(reviewable)), "allowed": int(len(allowed))}


def latest_refresh_today(refresh_audit: pd.DataFrame, today: object) -> tuple[bool, int, str]:
    """Summarize whether the data refresh audit has current-session rows."""

    if refresh_audit.empty or "refresh_run_at_et" not in refresh_audit.columns:
        return False, 0, ""

    audit = refresh_audit.copy()
    audit["_refresh_dt"] = audit["refresh_run_at_et"].map(parse_et_datetime)
    today_rows = audit[audit["_refresh_dt"].map(lambda value: same_et_day(value, today))]
    if today_rows.empty:
        return False, 0, ""

    symbol_count = int(today_rows.get("symbol", pd.Series(dtype=str)).nunique())
    latest_run = max(value for value in today_rows["_refresh_dt"].dropna())
    session_ok = True
    if "m30_latest_session" in today_rows.columns and "m5_latest_session" in today_rows.columns:
        session_ok = bool(
            today_rows["m30_latest_session"].astype(str).eq(str(today)).any()
            and today_rows["m5_latest_session"].astype(str).eq(str(today)).any()
        )
    return session_ok, symbol_count, latest_run.strftime("%Y-%m-%d %H:%M:%S %Z")


def scheduled_market_scan_due(moment: datetime) -> bool:
    """Return True after the first scheduled regular-session scan should have run."""

    session = market_session_for_date(
        moment.date(),
        regular_open=parse_clock(STRATEGY.market_open),
        regular_close=parse_clock(STRATEGY.market_close),
    )
    if not session.is_market_day or session.market_open is None:
        return False
    first_scan_grace = session.market_open + timedelta(minutes=5)
    return moment >= first_scan_grace


def build_watchdog(output_dir: Path, *, moment: datetime | None = None, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Build a plain-English watchdog state from existing workflow artifacts."""

    current_time = moment or now_et()
    today = current_time.date()
    autonomous_status = read_json_or_empty(output_dir / "autonomous_paper_workflow_status.json")
    refresh_status = read_json_or_empty(output_dir / "refresh_status.json")
    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    refresh_audit = read_csv_or_empty(data_dir / "market_refresh_audit.csv")

    autonomous_time = parse_et_datetime(autonomous_status.get("generated_at_et"))
    workflow_summary_time = modified_at_et(output_dir / "daily_workflow_summary.md")
    scanner_time = modified_at_et(output_dir / "daily_paper_signal_scanner.csv")
    status_action = str(autonomous_status.get("decision", "") or autonomous_status.get("action", "")).strip()
    market_scan_ran_today = same_et_day(workflow_summary_time, today) or (
        same_et_day(autonomous_time, today) and status_action == "market_scan"
    )
    refresh_today, refreshed_symbol_count, latest_refresh = latest_refresh_today(refresh_audit, today)
    scanner_today = scanner_session_today(scanner, today)
    candidate_counts = current_candidate_counts(scanner)
    due = scheduled_market_scan_due(current_time)

    if market_scan_ran_today and refresh_today and scanner_today:
        status = "pass"
        headline = "Morning scheduled workflow ran today."
        next_action = "Watch current candidates and the sample queue; paper entry still requires manual review."
    elif not due:
        status = "pending"
        headline = "Morning scheduled workflow is not due yet."
        next_action = "Keep the laptop awake for the first 6:30 AM PT scheduled run."
    elif market_scan_ran_today and not refresh_today:
        status = "warn"
        headline = "Workflow ran, but today's market-data refresh is not confirmed."
        next_action = "Run Refresh Market Data from the dashboard or run the daily workflow with --refresh-data."
    elif market_scan_ran_today and not scanner_today:
        status = "warn"
        headline = "Workflow ran, but scanner output is not from today's session."
        next_action = "Run the market-data refresh again before reviewing paper candidates."
    else:
        status = "warn"
        headline = "Morning scheduled workflow has not been confirmed today."
        next_action = "Confirm the laptop is awake, then run the dashboard Refresh Webull Data action if needed."

    return {
        "generated_at_et": current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "watchdog_date": str(today),
        "status": status,
        "headline": headline,
        "next_action": next_action,
        "autonomous_status": {
            "ran_today": same_et_day(autonomous_time, today),
            "latest_action": status_action or "unknown",
            "generated_at_et": autonomous_status.get("generated_at_et", ""),
        },
        "market_scan": {
            "due": due,
            "ran_today": market_scan_ran_today,
            "daily_workflow_summary_modified_et": workflow_summary_time.strftime("%Y-%m-%d %H:%M:%S %Z")
            if workflow_summary_time
            else "",
        },
        "data_refresh": {
            "confirmed_today": refresh_today,
            "refreshed_symbol_count": refreshed_symbol_count,
            "latest_refresh_at_et": latest_refresh,
            "refresh_status": refresh_status.get("status", "missing"),
        },
        "scanner": {
            "session_is_today": scanner_today,
            "scanner_modified_et": scanner_time.strftime("%Y-%m-%d %H:%M:%S %Z") if scanner_time else "",
            "current_candidate_count": candidate_counts["current"],
            "reviewable_candidate_count": candidate_counts["reviewable"],
            "allowed_candidate_count": candidate_counts["allowed"],
        },
        "guardrail": (
            "Watchdog is status-only. It does not place orders, create broker alerts, "
            "or import paper trades."
        ),
    }


def write_report(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown watchdog reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "morning_run_watchdog.json"
    md_path = output_dir / "morning_run_watchdog.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rows = pd.DataFrame(
        [
            {"check": "Autonomous status wrote today", "value": payload["autonomous_status"]["ran_today"]},
            {"check": "Latest autonomous action", "value": payload["autonomous_status"]["latest_action"]},
            {"check": "Market scan due", "value": payload["market_scan"]["due"]},
            {"check": "Market scan ran today", "value": payload["market_scan"]["ran_today"]},
            {"check": "Market-data refresh confirmed today", "value": payload["data_refresh"]["confirmed_today"]},
            {"check": "Refreshed symbols", "value": payload["data_refresh"]["refreshed_symbol_count"]},
            {"check": "Scanner session is today", "value": payload["scanner"]["session_is_today"]},
            {"check": "Current candidates", "value": payload["scanner"]["current_candidate_count"]},
            {"check": "Reviewable candidates", "value": payload["scanner"]["reviewable_candidate_count"]},
            {"check": "Allowed candidates", "value": payload["scanner"]["allowed_candidate_count"]},
        ]
    )
    md_path.write_text(
        f"""# Morning Run Watchdog

This report answers one question: did the scheduled morning paper workflow run
and refresh the app's evidence for today?

Important: this is status-only. It does not place orders, create broker alerts,
import paper trades, or connect to broker execution.

## Verdict

```text
{payload["status"]}: {payload["headline"]}
```

## Next Action

```text
{payload["next_action"]}
```

## Checks

{markdown_table(rows)}

## Latest Timestamps

```text
Generated: {payload["generated_at_et"]}
Autonomous status: {payload["autonomous_status"]["generated_at_et"] or "missing"}
Daily workflow summary: {payload["market_scan"]["daily_workflow_summary_modified_et"] or "missing"}
Latest refresh audit: {payload["data_refresh"]["latest_refresh_at_et"] or "missing"}
Scanner CSV: {payload["scanner"]["scanner_modified_et"] or "missing"}
```

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
logs/morning_run_watchdog.json
logs/morning_run_watchdog.md
logs/autonomous_paper_workflow_status.json
logs/daily_workflow_summary.md
data/market_refresh_audit.csv
logs/daily_paper_signal_scanner.csv
```
""",
        encoding="utf-8",
    )
    return json_path, md_path


def main() -> None:
    args = parse_args()
    payload = build_watchdog(args.output_dir)
    json_path, md_path = write_report(payload, args.output_dir)
    print(f"Saved morning watchdog JSON: {json_path}")
    print(f"Saved morning watchdog report: {md_path}")


if __name__ == "__main__":
    main()
