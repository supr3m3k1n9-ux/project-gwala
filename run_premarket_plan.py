"""Build the Project Gwala pre-market paper plan.

This is research and paper workflow only. It creates a daily plan from the
market calendar, approved playbook, scanner state, sizing state, and paper
validation progress. It does not fetch data, create alerts, place orders, or
connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.runtime_paths import runtime_data_path
from config.settings import ACCOUNT, STRATEGY
from config.symbol_playbook import APPROVED_PLAYBOOK, WATCH_PLAYBOOK
from reports.refresh_status import market_refresh_state
from run_dashboard import paper_progress, read_csv_or_empty
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the daily pre-market paper plan.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=runtime_data_path("paper_trades.csv"), help="Paper log CSV.")
    parser.add_argument("--date", help="Plan date in YYYY-MM-DD. Defaults to today's New York date.")
    parser.add_argument("--account-size", type=float, default=ACCOUNT.starting_equity, help="Paper account size.")
    parser.add_argument("--risk-per-trade-pct", type=float, default=ACCOUNT.risk_per_trade_pct)
    parser.add_argument("--max-daily-loss-r", type=float, default=-3.0)
    return parser.parse_args()


def plan_date(value: str | None) -> date:
    """Return the requested plan date."""

    if value:
        return date.fromisoformat(value)
    return datetime.now(MARKET_TZ).date()


def playbook_frame(entries: list) -> pd.DataFrame:
    """Convert playbook entries into a readable table."""

    rows = []
    for entry in entries:
        rows.append(
            {
                "symbol": entry.symbol,
                "setup": entry.setup_name,
                "variant": entry.variant,
                "exit_profile": entry.exit_profile,
                "notes": entry.notes,
            }
        )
    return pd.DataFrame(rows)


def candidate_table(scanner: pd.DataFrame, target_date: date, market: dict[str, object]) -> pd.DataFrame:
    """Return candidates only when this plan describes the active open session."""

    if (
        scanner.empty
        or not market.get("market_is_open", False)
        or str(target_date) != str(market.get("today", ""))
    ):
        return pd.DataFrame()
    current = scanner[
        scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
        & (scanner["signal_freshness"] == "current_candle")
        & (scanner["scan_date"].astype(str) == str(target_date))
    ].copy()
    keep = [
        "symbol",
        "setup",
        "direction",
        "scanner_status",
        "planned_entry",
        "planned_stop",
        "planned_target",
        "risk_per_share",
        "quality_score",
        "notes",
    ]
    return current[[column for column in keep if column in current.columns]]


def sizing_table(sizing: pd.DataFrame, target_date: date, market: dict[str, object]) -> pd.DataFrame:
    """Return eligible sizes only when this plan describes the active session."""

    if (
        sizing.empty
        or "sizing_status" not in sizing.columns
        or not market.get("market_is_open", False)
        or str(target_date) != str(market.get("today", ""))
    ):
        return pd.DataFrame()
    eligible = sizing[sizing["sizing_status"] == "size_ok"].copy()
    keep = [
        "symbol",
        "setup",
        "direction",
        "planned_entry",
        "planned_stop",
        "suggested_shares",
        "estimated_risk_dollars",
        "sizing_reason",
    ]
    return eligible[[column for column in keep if column in eligible.columns]]


def write_plan(path: Path, args: argparse.Namespace) -> None:
    """Write the Markdown plan."""

    target_date = plan_date(args.date)
    session = market_session_for_date(
        target_date,
        datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ),
        datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ),
    )
    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    paper_log = read_csv_or_empty(args.paper_csv)
    paper_review = read_csv_or_empty(args.output_dir / "paper_review_clean_trades.csv")
    progress = paper_progress(paper_log, paper_review)
    market = market_refresh_state()
    candidates = candidate_table(scanner, target_date, market)
    eligible_sizes = sizing_table(sizing, target_date, market) if not candidates.empty else pd.DataFrame()

    if session.is_market_day and session.market_open and session.market_close:
        session_text = f"{session.reason}: {session.market_open:%H:%M} to {session.market_close:%H:%M} ET"
    else:
        session_text = f"Market closed: {session.reason}"

    risk_budget = args.account_size * args.risk_per_trade_pct
    path.write_text(
        f"""# Project Gwala Pre-Market Plan

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## Session

```text
Plan date: {target_date}
Session: {session_text}
```

## Risk Box

```text
Paper account size: ${args.account_size:,.2f}
Risk per paper trade: {args.risk_per_trade_pct:.4f}
Risk budget per trade: ${risk_budget:,.2f}
Daily stop: {args.max_daily_loss_r}R
Force exit time: {STRATEGY.force_exit_time} ET
No averaging down. No stop removal. No revenge trades.
```

## Current Paper Progress

{markdown_table(pd.DataFrame([
    {"checkpoint": "paper rows logged", "value": progress["logged_rows"]},
    {"checkpoint": "completed paper trades", "value": progress["completed_rows"]},
    {"checkpoint": "allowed completed trades", "value": progress["allowed_count"]},
    {"checkpoint": "allowed average R", "value": progress["allowed_avg_r"]},
    {"checkpoint": "trades until 30-trade gate", "value": progress["first_gate_remaining"]},
]))}

## Approved Playbook

{markdown_table(playbook_frame(APPROVED_PLAYBOOK))}

## Watch-Only Research List

{markdown_table(playbook_frame(WATCH_PLAYBOOK))}

## Current-Candle Candidates

{markdown_table(candidates)}

## Eligible Paper Sizes

{markdown_table(eligible_sizes)}

## Trade Permission Rules

```text
Only consider current-candle scanner candidates.
Only allowed candidates can be paper traded.
Blocked/watch-only candidates can be journaled, not traded.
Use the planned entry, planned stop, and position sizing sheet.
Skip if the candidate is stale, position size is not size_ok, or the daily stop is hit.
```

## Files To Check

```text
logs/daily_paper_signal_scanner.md
logs/position_sizing.md
logs/trade_entry_checklist.md
data/paper_trades.csv
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "daily_trade_plan.md"
    write_plan(path, args)
    print(f"Saved pre-market plan: {path}")


if __name__ == "__main__":
    main()
