"""Build the Project Gwala market-open readiness check.

This is research and paper workflow only. It checks whether the local paper
workflow has the files and state needed for the next market session. It does
not fetch data, create alerts, place orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from reports.system_state import build_system_state
from run_dashboard import paper_progress, read_csv_or_empty
from run_paper_import import PAPER_COLUMNS, read_existing
from run_playbook import markdown_table
from run_update_paper_trade import open_rows


@dataclass(frozen=True)
class CheckResult:
    """One readiness check result."""

    area: str
    status: str
    detail: str
    action: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the market-open readiness report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"), help="Paper trade log.")
    parser.add_argument("--mistake-csv", type=Path, default=Path("data/paper_mistakes.csv"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Local environment file.")
    parser.add_argument("--date", help="Readiness date in YYYY-MM-DD. Defaults to today's New York date.")
    return parser.parse_args()


def regular_market_times() -> tuple:
    """Return configured market open/close times with NY timezone info."""

    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    return open_time, close_time


def target_date(value: str | None) -> date:
    """Return the readiness date."""

    if value:
        return date.fromisoformat(value)
    return datetime.now(MARKET_TZ).date()


def result(area: str, status: str, detail: str, action: str = "") -> CheckResult:
    """Create one check result."""

    return CheckResult(area, status, detail, action)


def file_state(path: Path) -> str:
    """Return a short file presence/mtime description."""

    if not path.exists():
        return "missing"
    modified = datetime.fromtimestamp(path.stat().st_mtime, MARKET_TZ)
    return f"present, modified {modified:%Y-%m-%d %H:%M ET}"


def env_has_webull_keys(path: Path) -> bool:
    """Check that expected Webull key names exist without printing values."""

    if not path.exists():
        return False
    required = {"WEBULL_APP_KEY", "WEBULL_APP_SECRET"}
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        if key.strip() in required and value.strip():
            found.add(key.strip())
    return required.issubset(found)


def scanner_latest_date(scanner: pd.DataFrame) -> str:
    """Return latest scanner date as text."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return ""
    values = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
    return values[-1] if values else ""


def current_candidate_count(scanner: pd.DataFrame) -> int:
    """Count current-candle allowed/watch scanner candidates."""

    if scanner.empty:
        return 0
    current = scanner[
        scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
        & (scanner["signal_freshness"] == "current_candle")
    ]
    return len(current)


def eligible_size_count(sizing: pd.DataFrame) -> int:
    """Count current eligible paper sizes."""

    if sizing.empty or "sizing_status" not in sizing.columns:
        return 0
    return len(sizing[sizing["sizing_status"] == "size_ok"])


def approved_symbols() -> list[str]:
    """Return unique approved and watch playbook symbols."""

    return sorted(playbook_symbols("approved_plus_watch"))


def webull_file_check(output_dir: Path) -> tuple[CheckResult, pd.DataFrame]:
    """Check local Webull CSV presence for approved and watch symbols."""

    rows = []
    for symbol in approved_symbols():
        entry_path = output_dir / f"webull_{symbol}_M30_candles.csv"
        exit_path = output_dir / f"webull_{symbol}_M5_candles.csv"
        rows.append(
            {
                "symbol": symbol,
                "m30_csv": "present" if entry_path.exists() else "missing",
                "m5_csv": "present" if exit_path.exists() else "missing",
            }
        )
    frame = pd.DataFrame(rows)
    missing = frame[(frame["m30_csv"] == "missing") | (frame["m5_csv"] == "missing")]
    if missing.empty:
        return result("Webull CSVs", "pass", "All approved/watch-symbol M30/M5 CSV files are present."), frame
    symbols = ", ".join(missing["symbol"].astype(str))
    return result("Webull CSVs", "warn", f"Missing local CSV files for: {symbols}.", "Run daily workflow with --refresh-data."), frame


def paper_log_check(paper_csv: Path) -> tuple[CheckResult, pd.DataFrame]:
    """Check the paper log schema and open rows."""

    trades = read_existing(paper_csv)
    missing_columns = [column for column in PAPER_COLUMNS if column not in trades.columns]
    if missing_columns:
        return result("Paper log", "block", f"Missing columns: {', '.join(missing_columns)}.", "Repair data/paper_trades.csv."), trades
    open_frame = open_rows(trades)
    if open_frame.empty:
        return result("Paper log", "pass", "Paper log schema is clean and no open rows need outcome updates."), trades
    return (
        result(
            "Paper log",
            "warn",
            f"{len(open_frame)} paper row(s) still need outcome details.",
            "Run python run_update_paper_trade.py --list-open.",
        ),
        trades,
    )


def support_file_checks(output_dir: Path, mistake_csv: Path) -> list[CheckResult]:
    """Check the generated operating reports."""

    files = [
        output_dir / "project_gwala_dashboard.md",
        output_dir / "system_state.json",
        output_dir / "system_state.md",
        output_dir / "daily_trade_plan.md",
        output_dir / "trade_entry_checklist.md",
        output_dir / "daily_recap.md",
        output_dir / "paper_validation_checkpoint.md",
        output_dir / "paper_mistake_tracker.md",
        mistake_csv,
    ]
    checks = []
    for path in files:
        if path.exists():
            checks.append(result("Support files", "pass", f"{path}: {file_state(path)}"))
        else:
            checks.append(result("Support files", "warn", f"{path}: missing", "Run python run_daily_workflow.py."))
    return checks


def market_check(session_date: date) -> tuple[CheckResult, str]:
    """Check market calendar status and next session."""

    open_time, close_time = regular_market_times()
    session = market_session_for_date(session_date, open_time, close_time)
    now = datetime.now(MARKET_TZ)
    next_session = next_market_session(now, open_time, close_time)

    if session.is_market_day and session.market_open and session.market_close:
        detail = f"{session.reason}: {session.market_open:%H:%M} to {session.market_close:%H:%M} ET."
        return result("Market calendar", "pass", detail), f"{next_session.session_date} {next_session.reason}"
    return result("Market calendar", "warn", f"Market closed on {session_date}: {session.reason}."), f"{next_session.session_date} {next_session.reason}"


def scanner_check(scanner: pd.DataFrame, session_date: date) -> CheckResult:
    """Check scanner presence and freshness."""

    if scanner.empty:
        return result("Scanner", "block", "Scanner output is missing.", "Run python run_daily_workflow.py.")
    latest = scanner_latest_date(scanner)
    count = current_candidate_count(scanner)
    if latest == str(session_date):
        return result("Scanner", "pass", f"Scanner date is {latest}; current-candle candidate count is {count}.")
    return result(
        "Scanner",
        "warn",
        f"Scanner latest local session is {latest or 'unknown'}, not {session_date}; current-candle candidate count is {count}.",
        "Refresh data during market hours, then run python run_daily_workflow.py.",
    )


def sizing_check(sizing: pd.DataFrame) -> CheckResult:
    """Check position sizing output."""

    if sizing.empty:
        return result("Position sizing", "block", "Position sizing output is missing.", "Run python run_daily_workflow.py.")
    count = eligible_size_count(sizing)
    if count:
        return result("Position sizing", "pass", f"{count} eligible paper size(s) are available.")
    return result("Position sizing", "warn", "No eligible current-candle paper sizes right now.")


def credential_check(env_file: Path) -> CheckResult:
    """Check whether local Webull credential names are present."""

    if env_has_webull_keys(env_file):
        return result("Webull credentials", "pass", "Webull key names are present in .env. Values were not printed.")
    return result("Webull credentials", "warn", "Webull key names were not found in .env.", "Add WEBULL_APP_KEY and WEBULL_APP_SECRET.")


def next_action(checks: list[CheckResult], scanner: pd.DataFrame, sizing: pd.DataFrame, session_date: date) -> str:
    """Choose the next operational step."""

    statuses = {check.status for check in checks}
    if "block" in statuses:
        return "Fix blocked readiness items before paper trading."
    if current_candidate_count(scanner) > 0 and eligible_size_count(sizing) > 0:
        return "Review daily_trade_plan.md and trade_entry_checklist.md before any paper trade."
    if any(check.area == "Scanner" and check.status == "warn" for check in checks):
        return "During market hours, run `python run_daily_workflow.py --refresh-data` and wait for current-candle candidates."
    if any(check.area == "Market calendar" and check.status == "warn" for check in checks):
        return "Market is closed for the selected date. Prep only; run the workflow on the next open session."
    return f"No paper candidate is ready yet for {session_date}. Keep the workflow ready and wait."


def system_state_snapshot(system_state: dict) -> pd.DataFrame:
    """Return the app-state fields most relevant to readiness."""

    return pd.DataFrame(
        [
            {"field": "project_phase", "value": system_state["project_phase"]},
            {"field": "data_status", "value": system_state["data_freshness"]["data_status"]},
            {"field": "latest_scanner_session", "value": system_state["data_freshness"]["latest_scanner_session"]},
            {"field": "current_candidate_count", "value": system_state["scanner"]["current_candidate_count"]},
            {"field": "eligible_size_count", "value": system_state["position_sizing"]["eligible_size_count"]},
            {"field": "allowed_completed_trades", "value": system_state["paper_progress"]["allowed_completed_trades"]},
            {"field": "setup_health_attention_count", "value": system_state["setup_health"]["attention_count"]},
            {"field": "live_trading_enabled", "value": system_state["safety"]["live_trading_enabled"]},
            {"field": "real_money_ready", "value": system_state["safety"]["real_money_ready"]},
        ]
    )


def readiness_verdict(checks: list[CheckResult], system_state: dict) -> str:
    """Use app system state for the normal verdict, while honoring blockers."""

    if any(check.status == "block" for check in checks):
        return "Fix blocked readiness items before paper trading."
    return system_state["readiness_verdict"]


def write_report(path: Path, args: argparse.Namespace) -> None:
    """Write the readiness Markdown report."""

    session_date = target_date(args.date)
    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    paper_review = read_csv_or_empty(args.output_dir / "paper_review_clean_trades.csv")

    market_result, next_session_text = market_check(session_date)
    webull_result, webull_table = webull_file_check(args.output_dir)
    paper_result, paper_log = paper_log_check(args.paper_csv)
    progress = paper_progress(paper_log, paper_review)
    system_state = build_system_state(output_dir=args.output_dir, paper_csv=args.paper_csv)

    checks = [
        market_result,
        credential_check(args.env_file),
        webull_result,
        scanner_check(scanner, session_date),
        sizing_check(sizing),
        paper_result,
        *support_file_checks(args.output_dir, args.mistake_csv),
    ]
    check_table = pd.DataFrame([check.__dict__ for check in checks])

    path.write_text(
        f"""# Market-Open Readiness Check

Important: this is research/paper workflow only. It does not fetch data, place
orders, create alerts, or connect to broker execution.

## Verdict

```text
{readiness_verdict(checks, system_state)}
```

## Session

```text
Readiness date: {session_date}
Next market session: {next_session_text}
```

## Checks

{markdown_table(check_table)}

## App System State

{markdown_table(system_state_snapshot(system_state))}

## Webull CSV Coverage

{markdown_table(webull_table)}

## Paper Progress

{markdown_table(pd.DataFrame([
    {"checkpoint": "paper rows logged", "value": progress["logged_rows"]},
    {"checkpoint": "completed paper trades", "value": progress["completed_rows"]},
    {"checkpoint": "allowed completed trades", "value": progress["allowed_count"]},
    {"checkpoint": "allowed average R", "value": progress["allowed_avg_r"]},
    {"checkpoint": "trades until 30-trade gate", "value": progress["first_gate_remaining"]},
]))}

## Operating Flow

```text
1. Run this readiness check.
2. Run daily workflow during market hours.
3. Read daily_trade_plan.md.
4. Use trade_entry_checklist.md before any paper trade.
5. Log/import the paper trade.
6. Update outcome after exit.
7. Review daily_recap.md and paper_validation_checkpoint.md.
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "readiness_check.md"
    write_report(path, args)
    print(f"Saved readiness check: {path}")


if __name__ == "__main__":
    main()
