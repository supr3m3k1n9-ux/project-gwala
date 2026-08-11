"""Append daily scanner candidates into the manual paper-trade log.

This is research and paper workflow only. It copies planned paper-trade rows
from the daily scanner into data/paper_trades.csv. It does not place orders,
create alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config.runtime_paths import runtime_data_path
from config.runtime_paths import runtime_data_root
from reports.refresh_status import market_refresh_state


PAPER_COLUMNS = [
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
    "vehicle",
    "risk_tier",
    "planned_option_premium",
    "outcome_r",
    "followed_plan",
    "exit_reason",
    "notes",
    "invalid_for_validation",
    "invalid_reason",
    "invalidated_at_et",
    "original_creation_timestamp",
    "incident_id",
    "source_contract_gate_identity",
]
VALID_REFRESH_EVIDENCE = {"files_present_and_complete", "current_session_in_progress"}


def default_refresh_audit_csv() -> Path:
    """Return the durable refresh-audit CSV path."""

    return runtime_data_root() / "market_refresh_audit.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append daily scanner candidates to the paper log.")
    parser.add_argument(
        "--scanner-csv",
        type=Path,
        default=Path("logs/daily_paper_signal_scanner.csv"),
        help="Daily scanner CSV to import from.",
    )
    parser.add_argument(
        "--paper-csv",
        type=Path,
        default=runtime_data_path("paper_trades.csv"),
        help="Manual paper-trade log to append to.",
    )
    parser.add_argument(
        "--refresh-audit-csv",
        type=Path,
        default=default_refresh_audit_csv(),
        help="Refresh evidence required before a real paper import.",
    )
    parser.add_argument(
        "--statuses",
        nargs="+",
        choices=["allowed", "blocked_watch_only"],
        default=["allowed"],
        help="Scanner statuses to append.",
    )
    parser.add_argument(
        "--freshness",
        choices=["current_candle", "earlier_today", "all"],
        default="current_candle",
        help="Only import fresh current-candle signals by default.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be appended without writing.")
    return parser.parse_args()


def read_existing(path: Path) -> pd.DataFrame:
    """Read the paper log or create an empty one with the standard columns."""

    if not path.exists():
        return pd.DataFrame(columns=PAPER_COLUMNS)
    existing = pd.read_csv(path)
    for column in PAPER_COLUMNS:
        if column not in existing.columns:
            existing[column] = ""
    return existing[PAPER_COLUMNS]


def scanner_to_paper_rows(scanner: pd.DataFrame, statuses: list[str], freshness: str) -> pd.DataFrame:
    """Convert scanner rows into blank-outcome paper-log rows."""

    selected = scanner[scanner["scanner_status"].isin(statuses)].copy()
    if freshness != "all":
        selected = selected[selected["signal_freshness"] == freshness]

    rows = []
    for _, row in selected.iterrows():
        rows.append(
            {
                "trade_date": row["scan_date"],
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
                "vehicle": "options",
                "risk_tier": "",
                "planned_option_premium": "",
                "outcome_r": "",
                "followed_plan": "",
                "exit_reason": "",
                "notes": row["block_reason"] if pd.notna(row["block_reason"]) and row["block_reason"] else row["notes"],
            }
        )
    return pd.DataFrame(rows, columns=PAPER_COLUMNS)


def dedupe(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows that are not already present in the paper log."""

    if new_rows.empty:
        return new_rows

    key_columns = [
        "trade_date",
        "entry_time_et",
        "symbol",
        "setup",
        "direction",
        "signal_status",
        "planned_entry",
        "planned_stop",
        "planned_target",
    ]
    existing_keys = set(existing[key_columns].astype(str).agg("|".join, axis=1))
    new_keys = new_rows[key_columns].astype(str).agg("|".join, axis=1)
    return new_rows[~new_keys.isin(existing_keys)].copy()


def paper_import_is_allowed(
    scanner: pd.DataFrame,
    statuses: list[str],
    freshness: str,
    market: dict,
    refresh_audit: pd.DataFrame,
) -> tuple[bool, str]:
    """Require same-session open-market evidence before writing the paper log."""

    if set(statuses) != {"allowed"}:
        return False, "Real paper import only accepts allowed candidates. Watch-only signals belong in observations."
    if freshness != "current_candle":
        return False, "Real paper import only accepts current_candle signals. Use --dry-run for historical review."
    if not market["market_is_open"]:
        return False, "Real paper import is blocked outside regular market hours."
    if "scan_date" not in scanner.columns:
        return False, "Scanner output has no scan_date column."
    scanner_dates = {str(value) for value in scanner["scan_date"].dropna().unique()}
    if scanner_dates != {market["today"]}:
        return False, "Real paper import requires scanner rows from today's open market session."
    candidates = scanner[
        scanner["scanner_status"].isin(statuses)
        & (scanner["signal_freshness"] == freshness)
    ]
    required_symbols = set(candidates["symbol"].astype(str).str.upper())
    audit = refresh_audit.copy()
    required_columns = {"symbol", "m30_latest_session", "m5_latest_session", "refresh_evidence_status"}
    if audit.empty or not required_columns.issubset(audit.columns):
        return False, "Real paper import requires recorded current-session Webull refresh evidence."
    audited = audit[
        (audit["m30_latest_session"].astype(str) == market["today"])
        & (audit["m5_latest_session"].astype(str) == market["today"])
        & (audit["refresh_evidence_status"].isin(VALID_REFRESH_EVIDENCE))
    ]
    audited_symbols = set(audited["symbol"].astype(str).str.upper())
    if not required_symbols.issubset(audited_symbols):
        return False, "Real paper import requires current-session Webull refresh evidence for each candidate symbol."
    return True, "Current-session scanner evidence is eligible for manual paper import review."


def main() -> None:
    args = parse_args()
    if not args.scanner_csv.exists():
        raise FileNotFoundError(f"Scanner CSV not found: {args.scanner_csv}")

    scanner = pd.read_csv(args.scanner_csv)
    existing = read_existing(args.paper_csv)
    candidates = scanner_to_paper_rows(scanner, args.statuses, args.freshness)
    new_rows = dedupe(existing, candidates)

    print(f"Scanner candidates matched: {len(candidates)}")
    print(f"New rows after duplicate check: {len(new_rows)}")

    if args.dry_run:
        if new_rows.empty:
            print("No rows would be appended.")
        else:
            print(new_rows.to_string(index=False))
        return

    if not new_rows.empty:
        refresh_audit = pd.read_csv(args.refresh_audit_csv) if args.refresh_audit_csv.exists() else pd.DataFrame()
        allowed, reason = paper_import_is_allowed(
            scanner,
            args.statuses,
            args.freshness,
            market_refresh_state(),
            refresh_audit,
        )
        if not allowed:
            raise ValueError(reason)

    args.paper_csv.parent.mkdir(parents=True, exist_ok=True)
    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined.to_csv(args.paper_csv, index=False)
    print(f"Updated paper log: {args.paper_csv}")


if __name__ == "__main__":
    main()
