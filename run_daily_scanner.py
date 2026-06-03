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
from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.settings import STRATEGY
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from data.market_data import load_candles_from_csv
from risk_management.rules import build_long_risk, build_short_risk
from run_playbook import markdown_table
from run_signal_journal import weakness_v1_block_reason
from run_webull_watchlist import (
    EXIT_PROFILES,
    MARKET_CONFIRMED_VARIANTS,
    add_strategy_columns,
    apply_market_confirmation,
    is_setup_b_short_variant,
    settings_for_variant,
    signal_column_for_variant,
    use_baseline_candidate_metrics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a daily Project Gwala paper signal scanner.")
    parser.add_argument("--mode", choices=sorted(PLAYBOOKS), default="approved", help="Playbook mode to scan.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull CSV files are stored.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where scanner reports are saved.")
    parser.add_argument("--scan-date", help="Optional session date to scan, formatted YYYY-MM-DD.")
    parser.add_argument(
        "--trade-filter",
        choices=["none", "weakness_v1"],
        default="weakness_v1",
        help="Research filter used to mark paper candidates versus watch-only signals.",
    )
    parser.add_argument("--market-regime-symbol", default="SPY", help="Market symbol for market-confirmed variants.")
    return parser.parse_args()


def selected_signal_column(entry: PlaybookEntry) -> str:
    """Return the playbook signal column used for this entry."""

    if is_setup_b_short_variant(entry.variant):
        return "short_signal" if use_baseline_candidate_metrics(entry.variant) else signal_column_for_variant(entry.variant)
    return "long_signal" if use_baseline_candidate_metrics(entry.variant) else signal_column_for_variant(entry.variant)


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
        action = "Run the daily workflow after Webull data exists."
    elif latest == str(now.date()) and market_is_open:
        status = "fresh_for_today"
        action = "Current-candle candidates can be reviewed for paper trading."
    elif latest == str(now.date()) and today_session.is_market_day:
        status = "outside_market_hours"
        action = "Today's data exists, but do not import or size a new paper trade outside regular hours."
    else:
        status = "stale_or_prep_only"
        action = f"Do not import paper trades until Webull data is refreshed on {next_session.session_date}."

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


def long_condition_checks(row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[tuple[str, bool]]:
    """Return the current long-setup rule checks for dashboard explanations."""

    checks = [
        ("regular session", row.get("regular_session", False)),
        ("inside entry window", row.get("entry_window", False)),
        ("price above 200 EMA", row.get("bullish_regime", False)),
        ("9 EMA above 21 EMA", row.get("bullish_ema_stack", False)),
        ("close above VWAP", row.get("buyers_control_vwap", False)),
        ("1H bullish thesis", row.get("htf_bullish_bias", False)),
        ("above opening range high", row.get("above_opening_range", False)),
        ("pulled back to VWAP/EMA value", row.get("pullback_to_value", False)),
        ("bullish reclaim candle", row.get("bullish_reclaim", False)),
    ]
    if signal_column in {"elite_long_signal", "quality_entry_signal"}:
        checks.extend(
            [
                ("strong relative volume", row.get("strong_relative_volume", False)),
                ("clean bull trend", row.get("clean_bull_trend", False)),
                ("trend-day regime", row.get("trend_day_regime", False)),
                ("room to target", row.get("has_room_to_target", False)),
            ]
        )
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        checks.append(("SPY market confirmation", row.get("market_bullish_bias", False)))

    return [(label, bool(passed)) for label, passed in checks]


def missing_long_reasons(row: pd.Series, entry: PlaybookEntry, signal_column: str) -> list[str]:
    """Explain why a long setup is not ready on the latest candle."""

    return [label for label, passed in long_condition_checks(row, entry, signal_column) if not passed]


def short_condition_checks(row: pd.Series, signal_column: str) -> list[tuple[str, bool]]:
    """Return the current short-setup rule checks for dashboard explanations."""

    checks = [
        ("regular session", row.get("regular_session", False)),
        ("inside entry window", row.get("entry_window", False)),
        ("price below 200 EMA", row.get("bearish_regime", False)),
        ("9 EMA below 21 EMA", row.get("bearish_ema_stack", False)),
        ("close below VWAP", row.get("sellers_control_vwap", False)),
        ("1H bearish thesis", row.get("htf_bearish_bias", False)),
        ("below opening range low", row.get("below_opening_range", False)),
        ("pulled back into VWAP/EMA value", row.get("short_pullback_to_value", False)),
        ("bearish rejection candle", row.get("bearish_reject", False)),
    ]
    if signal_column == "quality_short_signal":
        checks.extend(
            [
                ("strong relative volume", row.get("strong_relative_volume", False)),
                ("clean bear trend", row.get("clean_bear_trend", False)),
                ("bear trend-day regime", row.get("bear_trend_day_regime", False)),
                ("room to short target", row.get("has_room_to_short_target", False)),
            ]
        )
    return [(label, bool(passed)) for label, passed in checks]


def missing_short_reasons(row: pd.Series, signal_column: str) -> list[str]:
    """Explain why a short setup is not ready on the latest candle."""

    return [label for label, passed in short_condition_checks(row, signal_column) if not passed]


def plan_for_signal(row: pd.Series, entry: PlaybookEntry, exit_profile: ExitProfile) -> dict:
    """Build planned entry, stop, target, and risk for a valid signal."""

    settings = settings_for_variant(entry.variant)
    reward_multiple = exit_profile.reward_multiple
    if reward_multiple is None:
        reward_multiple = settings.reward_multiple

    if is_setup_b_short_variant(entry.variant):
        stop_reference = max(row["vwap"], row[f"ema_{settings.fast_ema_length}"], row[f"ema_{settings.slow_ema_length}"])
        trade_risk = build_short_risk(
            entry=float(row["close"]),
            stop_reference=float(stop_reference),
            stop_buffer_pct=settings.stop_buffer_pct,
            reward_multiple=reward_multiple,
        )
    else:
        stop_reference = min(row["vwap"], row[f"ema_{settings.fast_ema_length}"], row[f"ema_{settings.slow_ema_length}"])
        trade_risk = build_long_risk(
            entry=float(row["close"]),
            stop_reference=float(stop_reference),
            stop_buffer_pct=settings.stop_buffer_pct,
            reward_multiple=reward_multiple,
        )

    return {
        "planned_entry": round(trade_risk.entry, 4),
        "planned_stop": round(trade_risk.stop, 4),
        "planned_target": round(trade_risk.target, 4),
        "risk_per_share": round(trade_risk.risk_per_share, 4),
    }


def scanner_block_reason(row: pd.Series, entry: PlaybookEntry) -> str:
    """Return the weakness_v1 block reason for a scanner signal."""

    journal_style_row = pd.Series(
        {
            "symbol": entry.symbol,
            "playbook_setup": entry.setup_name,
            "entry_hour_et": row.name.tz_convert("America/New_York").hour,
            "relative_volume": row.get("relative_volume", 0),
            "room_to_resistance_r": row.get("room_to_resistance_r", row.get("room_to_support_r", 0)),
        }
    )
    return weakness_v1_block_reason(journal_style_row)


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
    entry_csv = data_dir / f"webull_{entry.symbol}_M30_candles.csv"
    exit_csv = data_dir / f"webull_{entry.symbol}_M5_candles.csv"
    market_candles = None
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        market_csv = data_dir / f"webull_{market_regime_symbol.upper()}_M30_candles.csv"
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
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        enriched = apply_market_confirmation(enriched)
    return enriched


def scan_entry(entry: PlaybookEntry, data_dir: Path, scan_date: str | None, trade_filter: str, market_symbol: str) -> dict:
    """Scan one playbook entry and return one checklist row."""

    signal_column = selected_signal_column(entry)
    exit_profile = EXIT_PROFILES[entry.exit_profile]

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
        if has_signal:
            signal_freshness = "current_candle" if signal_time == latest_time else "earlier_today"
            if trade_filter == "weakness_v1":
                block_reason = scanner_block_reason(signal_row, entry)
            if block_reason:
                scanner_status = "blocked_watch_only"
                action = "log_watch_only" if signal_freshness == "current_candle" else "review_watch_only_signal"
            else:
                scanner_status = "allowed"
                action = "paper_trade_candidate" if signal_freshness == "current_candle" else "review_allowed_signal"

        if is_setup_b_short_variant(entry.variant):
            condition_checks = short_condition_checks(latest_row, signal_column)
            direction = "short"
            score = int(latest_row.get("short_quality_score", 0))
            grade = str(latest_row.get("short_quality_grade", ""))
            room = float(latest_row.get("room_to_support_r", 0))
        else:
            condition_checks = long_condition_checks(latest_row, entry, signal_column)
            direction = "long"
            score = int(latest_row.get("quality_score", 0))
            grade = str(latest_row.get("quality_grade", ""))
            room = float(latest_row.get("room_to_resistance_r", 0))
        passed = [label for label, is_met in condition_checks if is_met]
        missing = [label for label, is_met in condition_checks if not is_met]

        plan = {"planned_entry": "", "planned_stop": "", "planned_target": "", "risk_per_share": ""}
        if has_signal:
            plan = plan_for_signal(signal_row, entry, exit_profile)

        if not missing:
            latest_notes = "ready on latest candle"
        elif has_signal:
            latest_notes = f"signal found {signal_freshness}; latest candle gaps: " + "; ".join(missing)
        else:
            latest_notes = "; ".join(missing)

        return {
            "symbol": entry.symbol,
            "setup": entry.setup_name,
            "direction": direction,
            "variant": entry.variant,
            "exit_profile": entry.exit_profile,
            "scanner_status": scanner_status,
            "action": action,
            "signal_column": signal_column,
            "scan_date": str(session["session_date"].iloc[-1]),
            "latest_candle_et": format_et(latest_time),
            "latest_signal_et": "" if pd.isna(signal_time) else format_et(signal_time),
            "signal_freshness": signal_freshness,
            "block_reason": block_reason,
            "latest_candle_notes": latest_notes,
            "passed_conditions": "; ".join(passed),
            "missing_conditions": "; ".join(missing),
            "passed_condition_count": len(passed),
            "condition_count": len(condition_checks),
            "close": round(float(latest_row["close"]), 4),
            **plan,
            "quality_score": score,
            "quality_grade": grade,
            "relative_volume": round(float(latest_row.get("relative_volume", 0)), 4),
            "room_to_target_r": round(room, 4),
            "notes": entry.notes,
        }
    except Exception as error:
        return {
            "symbol": entry.symbol,
            "setup": entry.setup_name,
            "direction": "short" if is_setup_b_short_variant(entry.variant) else "long",
            "variant": entry.variant,
            "exit_profile": entry.exit_profile,
            "scanner_status": "data_error",
            "action": "fix_data",
            "signal_column": signal_column,
            "scan_date": scan_date or "",
            "latest_candle_et": "",
            "latest_signal_et": "",
            "signal_freshness": "",
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
        candidate_note = "Prep only. Do not import, size, or paper trade these rows until Webull data is refreshed during the next open session."

    path.write_text(
        f"""# Daily Paper Signal Scanner

This scanner checks the current local Webull candle files against the Project
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

    rows = [
        scan_entry(entry, args.data_dir, args.scan_date, args.trade_filter, args.market_regime_symbol)
        for entry in PLAYBOOKS[args.mode]
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
