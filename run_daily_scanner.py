"""Build a daily paper signal scanner from local Webull CSV candles.

This is research and paper workflow only. It reads local candle files, applies
the approved playbook rules, and writes a daily checklist. It does not fetch
data, place orders, create alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtesting.engine import ExitProfile
from config.filter_policy import DEFAULT_PAPER_TRADE_FILTER
from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.settings import STRATEGY
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from data.candle_cache import preferred_candle_path
from data.market_data import load_candles_from_csv
from run_playbook import markdown_table
from run_signal_journal import weakness_v1_block_reason
from run_webull_watchlist import (
    EXIT_PROFILES,
    MARKET_CONFIRMED_VARIANTS,
    add_strategy_columns,
    apply_market_confirmation,
    settings_for_variant,
)
from strategies.scanner_adapters import (
    entry_direction,
    scanner_adapter_for_entry,
    selected_signal_column,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a daily Project Gwala paper signal scanner.")
    parser.add_argument("--mode", choices=sorted(PLAYBOOKS), default="approved", help="Playbook mode to scan.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull CSV files are stored.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where scanner reports are saved.")
    parser.add_argument("--scan-date", help="Optional session date to scan, formatted YYYY-MM-DD.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=[],
        help="Optional symbols to scan. Use this when a focused data refresh only updated part of the playbook.",
    )
    parser.add_argument(
        "--trade-filter",
        choices=["none", "weakness_v1"],
        default=DEFAULT_PAPER_TRADE_FILTER,
        help=(
            "Optional research filter used to mark paper candidates versus watch-only signals. "
            "Ship-mode default is none; weakness_v1 is experimental and must be requested explicitly."
        ),
    )
    parser.add_argument("--market-regime-symbol", default="SPY", help="Market symbol for market-confirmed variants.")
    return parser.parse_args()


def playbook_entries_for_scan(mode: str, symbols: list[str] | None = None) -> list[PlaybookEntry]:
    """Return playbook entries for the requested mode and optional symbols."""

    allowed_symbols = {symbol.upper() for symbol in symbols or []}
    return [
        entry
        for entry in PLAYBOOKS[mode]
        if not allowed_symbols or entry.symbol.upper() in allowed_symbols
    ]


def format_et(timestamp: pd.Timestamp) -> str:
    """Format a timestamp in New York time for the trading checklist."""

    return timestamp.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")


def regular_market_times() -> tuple:
    """Return configured market open/close times with NY timezone info."""

    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    return open_time, close_time


def scanner_latest_date(scanner: pd.DataFrame) -> str:
    """Return the latest session date represented in scanner output."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return ""
    values = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
    return values[-1] if values else ""


def scanner_freshness_frame(scanner: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Build a small stale-data warning table for the scanner report."""

    open_time, close_time = regular_market_times()
    now = now or datetime.now(MARKET_TZ)
    today_session = market_session_for_date(now.date(), open_time, close_time)
    next_session = next_market_session(now, open_time, close_time)
    latest = scanner_latest_date(scanner)
    market_is_open = bool(
        today_session.is_market_day
        and today_session.market_open is not None
        and today_session.market_close is not None
        and today_session.market_open <= now <= today_session.market_close
    )

    if not latest:
        status = "missing"
        action = "Run the daily workflow after market-data candles exist."
    elif latest == str(now.date()) and market_is_open:
        status = "fresh_for_today"
        action = "Current-candle candidates can be reviewed for paper trading."
    elif latest == str(now.date()) and today_session.is_market_day:
        status = "outside_market_hours"
        action = "Today's data exists, but do not import or size a new paper trade outside regular hours."
    else:
        status = "stale_or_prep_only"
        action = f"Do not import paper trades until market data is refreshed on {next_session.session_date}."

    return pd.DataFrame(
        [
            {
                "latest_scanner_session": latest or "unknown",
                "market_today": str(now.date()),
                "market_today_status": today_session.reason,
                "next_market_session": str(next_session.session_date),
                "next_market_session_status": next_session.reason,
                "data_status": status,
                "action": action,
            }
        ]
    )


def scanner_block_reason(row: pd.Series, entry: PlaybookEntry) -> str:
    """Return the weakness_v1 block reason for a scanner signal."""

    relative_volume, room_to_target = scanner_adapter_for_entry(entry).block_metrics(row, entry)

    journal_style_row = pd.Series(
        {
            "symbol": entry.symbol,
            "playbook_setup": entry.setup_name,
            "entry_hour_et": row.name.tz_convert("America/New_York").hour,
            "relative_volume": relative_volume,
            "room_to_resistance_r": room_to_target,
        }
    )
    return weakness_v1_block_reason(journal_style_row)


def plan_for_signal(row: pd.Series, entry: PlaybookEntry, exit_profile: ExitProfile) -> dict:
    """Build planned entry, stop, target, and risk through the strategy adapter."""

    return scanner_adapter_for_entry(entry).plan_for_signal(row, entry, exit_profile)


def signal_freshness_for_session(session: pd.DataFrame, signal_time: pd.Timestamp, latest_time: pd.Timestamp) -> str:
    """Return the paper-validation freshness lane for a signal.

    A-tier remains the latest/current M30 candle. B-tier grace is exactly one
    M30 candle later. Anything older remains study/shadow context.
    """

    if pd.isna(signal_time):
        return ""
    if signal_time == latest_time:
        return "current_candle"

    try:
        latest_position = list(session.index).index(latest_time)
    except ValueError:
        return "earlier_today"
    if latest_position <= 0:
        return "earlier_today"

    previous_time = session.index[latest_position - 1]
    if signal_time == previous_time and latest_time - signal_time <= pd.Timedelta(minutes=45):
        return "grace_candle"
    return "earlier_today"


def latest_session_slice(candles: pd.DataFrame, scan_date: str | None) -> pd.DataFrame:
    """Return candles for the requested session or the latest available session."""

    if candles.empty:
        return candles

    if scan_date:
        target = pd.to_datetime(scan_date).date()
    else:
        target = candles["session_date"].dropna().iloc[-1]

    return candles[candles["session_date"] == target].copy()


def load_enriched_candles(entry: PlaybookEntry, data_dir: Path, market_regime_symbol: str) -> pd.DataFrame:
    """Load candles and add all strategy columns needed by the scanner."""

    settings = settings_for_variant(entry.variant)
    entry_csv = preferred_candle_path(data_dir, entry.symbol, "M30")
    exit_csv = preferred_candle_path(data_dir, entry.symbol, "M5")
    market_candles = None
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        market_csv = preferred_candle_path(data_dir, market_regime_symbol.upper(), "M30")
        market_candles = load_candles_from_csv(market_csv, market_regime_symbol.upper())

    entry_candles = load_candles_from_csv(entry_csv, entry.symbol)
    exit_candles = load_candles_from_csv(exit_csv, entry.symbol)
    enriched, _ = add_strategy_columns(
        entry_candles,
        exit_candles,
        settings,
        market_candles=market_candles,
        market_symbol=market_regime_symbol.upper(),
    )
    enriched = scanner_adapter_for_entry(entry).add_columns(enriched, entry)
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        enriched = apply_market_confirmation(enriched)
    return enriched


def scan_entry(entry: PlaybookEntry, data_dir: Path, scan_date: str | None, trade_filter: str, market_symbol: str) -> dict:
    """Scan one playbook entry and return one checklist row."""

    signal_column = selected_signal_column(entry)
    exit_profile = EXIT_PROFILES[entry.exit_profile]
    adapter = scanner_adapter_for_entry(entry)

    try:
        candles = load_enriched_candles(entry, data_dir, market_symbol)
        session = latest_session_slice(candles, scan_date)
        if session.empty:
            raise ValueError("No candles available for requested scan date.")

        latest_time = session.index[-1]
        latest_row = session.iloc[-1]
        signal_rows = session[session[signal_column].fillna(False).astype(bool)]
        signal_time = pd.NaT
        signal_row = latest_row
        if not signal_rows.empty:
            signal_time = signal_rows.index[-1]
            signal_row = signal_rows.iloc[-1]

        has_signal = not signal_rows.empty
        block_reason = ""
        scanner_status = "not_ready"
        action = "wait"
        signal_freshness = ""
        source_signal_time = signal_time
        candidate_time = pd.NaT
        plan_row = signal_row
        plan_source = ""
        if has_signal:
            signal_freshness = signal_freshness_for_session(session, signal_time, latest_time)
            if signal_freshness == "grace_candle":
                candidate_time = latest_time
                plan_row = latest_row
                plan_source = "latest_grace_candle"
            elif signal_freshness == "current_candle":
                candidate_time = signal_time
                plan_row = signal_row
                plan_source = "current_signal_candle"
            else:
                candidate_time = signal_time
                plan_row = signal_row
                plan_source = "historical_signal_candle"
            if trade_filter == "weakness_v1":
                block_reason = scanner_block_reason(signal_row, entry)
            if block_reason:
                scanner_status = "blocked_watch_only"
                action = (
                    "log_watch_only"
                    if signal_freshness == "current_candle"
                    else "manual_grace_watch_only"
                    if signal_freshness == "grace_candle"
                    else "review_watch_only_signal"
                )
            else:
                scanner_status = "allowed"
                action = (
                    "paper_trade_candidate"
                    if signal_freshness == "current_candle"
                    else "manual_b_tier_grace_review"
                    if signal_freshness == "grace_candle"
                    else "review_allowed_signal"
                )

        condition_checks = adapter.condition_checks(latest_row, entry, signal_column)
        direction = adapter.direction(entry)
        fields = adapter.scanner_fields(latest_row, entry)
        passed = [label for label, is_met in condition_checks if is_met]
        missing = [label for label, is_met in condition_checks if not is_met]

        plan = {"planned_entry": "", "planned_stop": "", "planned_target": "", "risk_per_share": ""}
        if has_signal:
            plan = adapter.plan_for_signal(plan_row, entry, exit_profile)

        if not missing:
            latest_notes = "ready on latest candle"
        elif has_signal:
            latest_notes = f"signal found {signal_freshness}; latest candle gaps: " + "; ".join(missing)
        else:
            latest_notes = "; ".join(missing)

        if signal_freshness == "grace_candle":
            validation_lane = "B"
        elif signal_freshness == "current_candle":
            validation_lane = "A"
        else:
            validation_lane = "study"

        return {
            "symbol": entry.symbol,
            "setup": entry.setup_name,
            "direction": direction,
            "strategy_id": adapter.strategy_id,
            "variant": entry.variant,
            "exit_profile": entry.exit_profile,
            "scanner_status": scanner_status,
            "action": action,
            "signal_column": signal_column,
            "scan_date": str(session["session_date"].iloc[-1]),
            "latest_candle_et": format_et(latest_time),
            "latest_signal_et": "" if pd.isna(signal_time) else format_et(signal_time),
            "source_signal_et": "" if pd.isna(source_signal_time) else format_et(source_signal_time),
            "candidate_entry_et": "" if pd.isna(candidate_time) else format_et(candidate_time),
            "signal_freshness": signal_freshness,
            "validation_lane": validation_lane,
            "manual_review_required": bool(signal_freshness in {"current_candle", "grace_candle"}),
            "fresh_plan_source": plan_source,
            "grace_candle_minutes": 30 if signal_freshness == "grace_candle" else 0,
            "block_reason": block_reason,
            "latest_candle_notes": latest_notes,
            "passed_conditions": "; ".join(passed),
            "missing_conditions": "; ".join(missing),
            "passed_condition_count": len(passed),
            "condition_count": len(condition_checks),
            "close": round(float(latest_row["close"]), 4),
            **plan,
            "quality_score": fields.quality_score,
            "quality_grade": fields.quality_grade,
            "relative_volume": round(fields.relative_volume, 4),
            "room_to_target_r": round(fields.room_to_target_r, 4),
            "notes": entry.notes,
        }
    except Exception as error:
        return {
            "symbol": entry.symbol,
            "setup": entry.setup_name,
            "direction": entry_direction(entry),
            "strategy_id": scanner_adapter_for_entry(entry).strategy_id,
            "variant": entry.variant,
            "exit_profile": entry.exit_profile,
            "scanner_status": "data_error",
            "action": "fix_data",
            "signal_column": signal_column,
            "scan_date": scan_date or "",
            "latest_candle_et": "",
            "latest_signal_et": "",
            "source_signal_et": "",
            "candidate_entry_et": "",
            "signal_freshness": "",
            "validation_lane": "study",
            "manual_review_required": False,
            "fresh_plan_source": "",
            "grace_candle_minutes": 0,
            "block_reason": "",
            "latest_candle_notes": str(error),
            "passed_conditions": "",
            "missing_conditions": "",
            "passed_condition_count": 0,
            "condition_count": 0,
            "close": "",
            "planned_entry": "",
            "planned_stop": "",
            "planned_target": "",
            "risk_per_share": "",
            "quality_score": "",
            "quality_grade": "",
            "relative_volume": "",
            "room_to_target_r": "",
            "notes": entry.notes,
        }


def write_import_template(path: Path, scanner: pd.DataFrame, now: datetime | None = None) -> None:
    """Write only currently reviewable paper-trade import rows."""

    columns = [
        "trade_date",
        "entry_time_et",
        "exit_time_et",
        "symbol",
        "setup",
        "direction",
        "signal_status",
        "planned_entry",
        "planned_stop",
        "planned_target",
        "actual_entry",
        "actual_exit",
        "shares",
        "outcome_r",
        "followed_plan",
        "exit_reason",
        "notes",
    ]
    freshness = scanner_freshness_frame(scanner, now)
    if str(freshness.iloc[0]["data_status"]) == "fresh_for_today":
        candidates = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ].copy()
    else:
        candidates = scanner.iloc[0:0].copy()
    rows = []
    for _, row in candidates.iterrows():
        rows.append(
            {
                "trade_date": str(row["scan_date"]),
                "entry_time_et": str(row["latest_signal_et"])[11:16],
                "exit_time_et": "",
                "symbol": row["symbol"],
                "setup": row["setup"],
                "direction": row["direction"],
                "signal_status": "blocked" if row["scanner_status"] == "blocked_watch_only" else "allowed",
                "planned_entry": row["planned_entry"],
                "planned_stop": row["planned_stop"],
                "planned_target": row["planned_target"],
                "actual_entry": "",
                "actual_exit": "",
                "shares": "",
                "outcome_r": "",
                "followed_plan": "",
                "exit_reason": "",
                "notes": row["block_reason"] or row["notes"],
            }
        )
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def write_report(path: Path, scanner: pd.DataFrame, mode: str, trade_filter: str) -> None:
    """Write the daily scanner Markdown report."""

    status_counts = scanner.groupby("scanner_status").size().reset_index(name="count").sort_values("scanner_status")
    candidates = scanner[scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])]
    not_ready = scanner[scanner["scanner_status"] == "not_ready"]
    freshness = scanner_freshness_frame(scanner)
    data_status = str(freshness.iloc[0]["data_status"])
    if data_status == "fresh_for_today":
        candidate_heading = "Paper Candidates And Watch-Only Signals"
        candidate_note = "These candidates are from today's scanner output."
    else:
        candidate_heading = "Historical Candidates And Watch-Only Signals"
        candidate_note = "Prep only. Do not import, size, or paper trade these rows until market data is refreshed during the next open session."

    path.write_text(
        f"""# Daily Paper Signal Scanner

This scanner checks the current local market-data candle files against the Project
Gwala playbook.

Important: this is research/paper workflow only. It does not fetch data, place
orders, create alerts, or connect to broker execution.

## Settings

```text
Playbook mode: {mode}
Trade filter: {trade_filter}
```

## Status Counts

{markdown_table(status_counts)}

## Data Freshness

{markdown_table(freshness)}

## {candidate_heading}

```text
{candidate_note}
```

{markdown_table(candidates)}

## Not Ready

{markdown_table(not_ready)}

## Files

```text
logs/daily_paper_signal_scanner.csv
logs/daily_paper_signal_scanner.md
logs/daily_paper_trade_import_template.csv
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    entries = playbook_entries_for_scan(args.mode, args.symbols)
    rows = [
        scan_entry(entry, args.data_dir, args.scan_date, args.trade_filter, args.market_regime_symbol)
        for entry in entries
    ]
    scanner = pd.DataFrame(rows)
    scanner = scanner.sort_values(["scanner_status", "symbol", "setup"])

    csv_path = args.output_dir / "daily_paper_signal_scanner.csv"
    report_path = args.output_dir / "daily_paper_signal_scanner.md"
    template_path = args.output_dir / "daily_paper_trade_import_template.csv"

    scanner.to_csv(csv_path, index=False)
    write_import_template(template_path, scanner)
    write_report(report_path, scanner, args.mode, args.trade_filter)

    print(f"Saved daily scanner CSV: {csv_path}")
    print(f"Saved daily scanner report: {report_path}")
    print(f"Saved paper trade import template: {template_path}")


if __name__ == "__main__":
    main()
