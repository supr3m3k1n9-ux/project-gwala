"""Run Project Gwala's current-candle capture workflow on a market-hours loop.

This is research and paper workflow only. The loop refreshes data, runs the
scanner, sizing, pre-entry, paper gate, contract gate, and validation preview on
a schedule. It does not place orders, create broker alerts, confirm new paper
entries, or connect to trade execution.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, time as clock_time
from pathlib import Path

import pandas as pd

from config.settings import STRATEGY
from config.market_calendar import MARKET_TZ, market_session_for_date
from config.symbol_playbook import playbook_symbols
from run_playbook import markdown_table


DEFAULT_SYMBOLS = sorted(playbook_symbols("approved_plus_watch"))


def parse_clock(value: str) -> clock_time:
    """Parse HH:MM settings into a time object."""

    hour, minute = value.split(":")
    return clock_time(hour=int(hour), minute=int(minute), tzinfo=MARKET_TZ)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Project Gwala intraday paper loop.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--interval-minutes", type=int, default=5, help="Minutes between production scans.")
    parser.add_argument("--once", action="store_true", help="Run at most one scan/check and exit.")
    parser.add_argument("--force", action="store_true", help="Run even outside regular market hours.")
    parser.add_argument(
        "--append-current-signals",
        action="store_true",
        help="Deprecated safety stop: ignored. Paper imports must happen after manual candidate review.",
    )
    parser.add_argument("--account-size", type=float, default=10_000.0, help="Paper account size for sizing.")
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.005, help="Paper risk per trade.")
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Webull requests during refresh.")
    parser.add_argument(
        "--auto-confirm-paper-exits",
        action="store_true",
        help="Automatically write local paper exit updates from saved 5m candles. No broker orders are placed.",
    )
    return parser.parse_args()


def now_et() -> datetime:
    """Return current New York time."""

    return datetime.now(tz=MARKET_TZ)


def is_market_day(moment: datetime) -> bool:
    """Return True if the local market calendar says this is a market day."""

    session = session_for_moment(moment)
    return session.is_market_day


def is_market_open(moment: datetime) -> bool:
    """Return True during the configured regular session."""

    session = session_for_moment(moment)
    if not session.is_market_day or session.market_open is None or session.market_close is None:
        return False
    local = moment.astimezone(MARKET_TZ)
    return session.market_open <= local <= session.market_close


def session_has_ended(moment: datetime) -> bool:
    """Return True after the close of an otherwise valid trading session."""

    session = session_for_moment(moment)
    return bool(
        session.is_market_day
        and session.market_close is not None
        and moment.astimezone(MARKET_TZ) > session.market_close
    )


def session_for_moment(moment: datetime):
    """Return the market session for moment's New York date."""

    local = moment.astimezone(MARKET_TZ)
    return market_session_for_date(
        local.date(),
        regular_open=parse_clock(STRATEGY.market_open),
        regular_close=parse_clock(STRATEGY.market_close),
    )


def seconds_until_next_scan(moment: datetime, interval_minutes: int) -> int:
    """Calculate seconds until the next interval boundary."""

    interval_seconds = interval_minutes * 60
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((moment - midnight).total_seconds())
    next_boundary = ((elapsed // interval_seconds) + 1) * interval_seconds
    return max(next_boundary - elapsed, 1)


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read CSV output if it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def run_step(command: list[str]) -> None:
    """Run one command and stop if it fails."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, check=True)


def workflow_command(args: argparse.Namespace) -> list[str]:
    """Build the current-candle capture command used by each scan."""

    command = [
        sys.executable,
        "run_current_candle_capture.py",
        "--output-dir",
        str(args.output_dir),
        "--symbols",
        *DEFAULT_SYMBOLS,
        "--pause",
        str(args.pause),
        "--account-size",
        str(args.account_size),
        "--risk-per-trade-pct",
        str(args.risk_per_trade_pct),
    ]
    if getattr(args, "auto_confirm_paper_exits", False):
        command.append("--auto-confirm-paper-exits")
    return command


def summarize_scan(output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return current candidates and eligible sizes after a scan."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")

    if scanner.empty:
        current_candidates = pd.DataFrame()
    else:
        current_candidates = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]

    if sizing.empty:
        eligible_sizes = pd.DataFrame()
    else:
        eligible_sizes = sizing[sizing["sizing_status"] == "size_ok"]

    return current_candidates, eligible_sizes


def write_loop_status(
    output_dir: Path,
    status: str,
    message: str,
    current_candidates: pd.DataFrame | None = None,
    eligible_sizes: pd.DataFrame | None = None,
) -> Path:
    """Write the latest loop status to Markdown."""

    current_candidates = current_candidates if current_candidates is not None else pd.DataFrame()
    eligible_sizes = eligible_sizes if eligible_sizes is not None else pd.DataFrame()
    path = output_dir / "intraday_loop_status.md"
    path.write_text(
        f"""# Intraday Loop Status

This is the Project Gwala market-hours paper loop status.

Important: this is research/paper workflow only. It does not place orders,
create broker alerts, or connect to trade execution.

## Status

```text
{status}
```

## Message

```text
{message}
```

## Current-Candle Candidates

{markdown_table(current_candidates)}

## Eligible Position Sizes

{markdown_table(eligible_sizes)}
""",
        encoding="utf-8",
    )
    return path


def run_one_scan(args: argparse.Namespace) -> None:
    """Run one refresh + scan cycle and print the result."""

    run_step(workflow_command(args))
    current_candidates, eligible_sizes = summarize_scan(args.output_dir)

    if not eligible_sizes.empty:
        message = f"{len(eligible_sizes)} current-candle candidate(s) have eligible paper sizes."
    elif not current_candidates.empty:
        message = f"{len(current_candidates)} current-candle candidate(s), but no eligible size_ok rows."
    else:
        message = "No current-candle candidates."

    print(f"\n{now_et().strftime('%Y-%m-%d %H:%M ET')} scan complete: {message}", flush=True)
    status_path = write_loop_status(args.output_dir, "scan_complete", message, current_candidates, eligible_sizes)
    print(f"Saved loop status: {status_path}")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    while True:
        moment = now_et()
        if args.force or is_market_open(moment):
            run_one_scan(args)
            if args.once:
                return
            sleep_seconds = seconds_until_next_scan(now_et(), args.interval_minutes)
            print(f"Sleeping {sleep_seconds} seconds until next scan.", flush=True)
            time.sleep(sleep_seconds)
            continue

        message = (
            f"Market is closed at {moment.strftime('%Y-%m-%d %H:%M ET')} "
            f"({session_for_moment(moment).reason}). "
            "Use --force to run anyway, or run during regular market hours."
        )
        print(message)
        status = "session_complete" if session_has_ended(moment) else "market_closed"
        status_path = write_loop_status(args.output_dir, status, message)
        print(f"Saved loop status: {status_path}")
        if args.once or session_has_ended(moment):
            return

        # Before the session opens, wait for the next boundary and check again.
        time.sleep(seconds_until_next_scan(moment, args.interval_minutes))


if __name__ == "__main__":
    main()
