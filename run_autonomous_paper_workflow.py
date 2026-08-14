"""Run the paper-validation workflow whenever the market schedule calls for it.

This is a local research supervisor. It can run pre-market checks, market-hours
current-candle capture cycles, and after-close recap reports on a schedule. It never
places orders, creates broker alerts, or imports reviewed paper trades.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path

from config.market_calendar import MARKET_TZ, MarketSession, market_session_for_date, next_market_session
from config.settings import STRATEGY


@dataclass(frozen=True)
class SupervisorDecision:
    """The next safe workflow action for the current market moment."""

    action: str
    message: str
    sleep_seconds: int = 0


def parse_clock(value: str) -> clock_time:
    """Parse HH:MM settings into a market-time clock."""

    hour, minute = value.split(":")
    return clock_time(hour=int(hour), minute=int(minute), tzinfo=MARKET_TZ)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the autonomous Project Gwala paper supervisor.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--interval-minutes", type=int, default=5, help="Minutes between market-hours scans.")
    parser.add_argument(
        "--premarket-minutes-before-open",
        type=int,
        default=15,
        help="How many minutes before the open the pre-market check should run.",
    )
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Webull requests during refresh.")
    parser.add_argument("--account-size", type=float, default=10_000.0, help="Paper account size for sizing.")
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.005, help="Paper risk per trade.")
    parser.add_argument(
        "--auto-confirm-paper-exits",
        action="store_true",
        help="Automatically write local paper exit updates from saved 5m candles. No broker orders are placed.",
    )
    parser.add_argument("--once", action="store_true", help="Make one schedule decision, run it if due, and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Write the decision without running commands.")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Persist the current supervisor decision and exit without running workflow commands.",
    )
    return parser.parse_args()


def now_et() -> datetime:
    """Return current New York time."""

    return datetime.now(tz=MARKET_TZ)


def session_for_moment(moment: datetime) -> MarketSession:
    """Return the market session for moment's local New York date."""

    local = moment.astimezone(MARKET_TZ)
    return market_session_for_date(
        local.date(),
        regular_open=parse_clock(STRATEGY.market_open),
        regular_close=parse_clock(STRATEGY.market_close),
    )


def seconds_until(target: datetime, moment: datetime) -> int:
    """Return whole seconds from moment until target."""

    return max(int((target - moment).total_seconds()), 1)


def seconds_until_next_scan(moment: datetime, interval_minutes: int) -> int:
    """Calculate seconds until the next interval boundary."""

    interval_seconds = interval_minutes * 60
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((moment - midnight).total_seconds())
    next_boundary = ((elapsed // interval_seconds) + 1) * interval_seconds
    return max(next_boundary - elapsed, 1)


def choose_action(
    moment: datetime,
    *,
    interval_minutes: int,
    premarket_minutes_before_open: int,
) -> SupervisorDecision:
    """Choose the safest workflow action for the current moment."""

    local = moment.astimezone(MARKET_TZ)
    session = session_for_moment(local)

    if not session.is_market_day:
        next_session = next_market_session(local, parse_clock(STRATEGY.market_open), parse_clock(STRATEGY.market_close))
        message = f"Market closed today ({session.reason}). Next session: {next_session.session_date}."
        return SupervisorDecision("market_closed", message, seconds_until(next_session.market_open, local))

    if session.market_open is None or session.market_close is None:
        return SupervisorDecision("market_closed", f"Market closed today ({session.reason}).", 3600)

    premarket_time = session.market_open - timedelta(minutes=premarket_minutes_before_open)

    if local < premarket_time:
        message = f"Waiting for pre-market check at {premarket_time.strftime('%Y-%m-%d %H:%M ET')}."
        return SupervisorDecision("wait", message, seconds_until(premarket_time, local))

    if premarket_time <= local < session.market_open:
        message = "Run pre-market verification before the regular session opens."
        return SupervisorDecision("premarket_check", message, seconds_until(session.market_open, local))

    if session.market_open <= local < session.market_close:
        message = "Run market-hours current-candle capture, gates, and dashboard sync checks."
        return SupervisorDecision("market_scan", message, seconds_until_next_scan(local, interval_minutes))

    message = "Regular session has closed; run recap and readiness reports."
    return SupervisorDecision("after_close_recap", message, 0)


def run_step(command: list[str]) -> None:
    """Run one supervisor command and fail fast if it errors."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, check=True)


def daily_workflow_command(args: argparse.Namespace) -> list[str]:
    """Build the market-hours trading critical-path command."""

    command = [
        sys.executable,
        "run_trading_critical_path.py",
        "--output-dir",
        str(args.output_dir),
        "--interval-minutes",
        str(getattr(args, "interval_minutes", 5)),
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


def commands_for_action(action: str, args: argparse.Namespace) -> list[list[str]]:
    """Return the safe commands for a scheduled action."""

    if action == "premarket_check":
        return [[sys.executable, "run_premarket_verification.py", "--output-dir", str(args.output_dir)]]
    if action == "market_scan":
        return [daily_workflow_command(args)]
    if action == "after_close_recap":
        return [
            [sys.executable, "run_after_close_evidence_maturity.py", "--output-dir", str(args.output_dir)],
            [sys.executable, "run_daily_recap.py", "--output-dir", str(args.output_dir)],
            [sys.executable, "run_readiness_check.py", "--output-dir", str(args.output_dir)],
            [sys.executable, "run_system_state.py", "--output-dir", str(args.output_dir)],
        ]
    return []


def write_status(output_dir: Path, decision: SupervisorDecision, *, dry_run: bool) -> Path:
    """Write the latest autonomous supervisor status."""

    path = output_dir / "autonomous_paper_workflow_status.md"
    generated_at = now_et().strftime("%Y-%m-%d %H:%M:%S %Z")
    json_path = output_dir / "autonomous_paper_workflow_status.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at_et": generated_at,
                "decision": decision.action,
                "message": decision.message,
                "dry_run": dry_run,
                "status_only": False,
                "suggested_next_wait_seconds": decision.sleep_seconds,
                "guardrail": (
                    "Local research and paper-validation only. No broker orders, "
                    "broker alerts, or automatic paper imports."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    path.write_text(
        f"""# Autonomous Paper Workflow Status

This is a local research and paper-validation supervisor.

Important: it does not place orders, create broker alerts, import reviewed
paper trades, or connect to broker execution.

## Decision

```text
{decision.action}
```

## Generated

```text
{generated_at}
```

## Message

```text
{decision.message}
```

## Dry Run

```text
{dry_run}
```

## Suggested Next Wait

```text
{decision.sleep_seconds} seconds
```
""",
        encoding="utf-8",
    )
    return path


def write_current_status_only(args: argparse.Namespace) -> Path:
    """Persist the current schedule decision without running production workflow commands."""

    decision = choose_action(
        now_et(),
        interval_minutes=args.interval_minutes,
        premarket_minutes_before_open=args.premarket_minutes_before_open,
    )
    path = write_status(args.output_dir, decision, dry_run=True)
    json_path = args.output_dir / "autonomous_paper_workflow_status.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["status_only"] = True
    payload["guardrail"] = (
        "Supervisor state persistence only. No scanner, gates, validation, broker orders, "
        "broker alerts, report generation, or paper imports were run."
    )
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n## Status Only\n\n```text\ntrue\n```\n",
        encoding="utf-8",
    )
    return path


def run_due_action(args: argparse.Namespace, decision: SupervisorDecision) -> None:
    """Run commands for a due action unless dry-run is enabled."""

    if args.dry_run:
        return
    for command in commands_for_action(decision.action, args):
        run_step(command)


def sleep_after_action(args: argparse.Namespace, decision: SupervisorDecision) -> int:
    """Return the next wait after any due commands have finished."""

    if decision.action == "market_scan":
        return seconds_until_next_scan(now_et(), args.interval_minutes)
    return decision.sleep_seconds


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.status_only:
        status_path = write_current_status_only(args)
        print(f"status_only: saved supervisor status: {status_path}")
        return

    while True:
        decision = choose_action(
            now_et(),
            interval_minutes=args.interval_minutes,
            premarket_minutes_before_open=args.premarket_minutes_before_open,
        )
        status_path = write_status(args.output_dir, decision, dry_run=args.dry_run)
        print(f"{decision.action}: {decision.message}")
        print(f"Saved supervisor status: {status_path}")
        run_due_action(args, decision)
        if not args.dry_run:
            if decision.action == "market_scan":
                run_step(
                    [
                        sys.executable,
                        "run_production_heartbeat.py",
                        "--output-dir",
                        str(args.output_dir),
                        "--interval-minutes",
                        str(args.interval_minutes),
                    ]
                )
            run_step([sys.executable, "run_morning_watchdog.py", "--output-dir", str(args.output_dir)])
            run_step([sys.executable, "run_daily_automation_timeline.py", "--output-dir", str(args.output_dir)])
            run_step([sys.executable, "run_system_state.py", "--output-dir", str(args.output_dir)])
            run_step([sys.executable, "run_dashboard_data_preflight.py", "--output-dir", str(args.output_dir)])

        if args.once or decision.action == "after_close_recap":
            return

        time.sleep(sleep_after_action(args, decision))


if __name__ == "__main__":
    main()
