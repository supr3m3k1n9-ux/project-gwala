"""Update a manually logged paper trade with its outcome.

This is research and paper workflow only. It edits data/paper_trades.csv and
calculates the trade's R result from actual entry, actual exit, planned stop,
and direction. It does not place orders or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_paper_import import PAPER_COLUMNS, read_existing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update one paper-trade log row.")
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"), help="Paper trade log.")
    parser.add_argument("--list-open", action="store_true", help="List rows missing an outcome and exit.")
    parser.add_argument("--row", type=int, help="One-based row number from the CSV data rows, not counting the header.")
    parser.add_argument("--actual-entry", type=float, help="Actual paper entry price.")
    parser.add_argument("--actual-exit", type=float, help="Actual paper exit price.")
    parser.add_argument("--exit-time", help="Exit time in ET, for example 11:30.")
    parser.add_argument("--shares", type=int, help="Paper share count.")
    parser.add_argument("--vehicle", choices=["shares", "options"], help="Trade vehicle used for this paper row.")
    parser.add_argument(
        "--risk-tier",
        choices=["reduced", "standard", "strong", "best-tier", "no_scale"],
        help="Manual risk tier used for this paper row.",
    )
    parser.add_argument("--planned-option-premium", type=float, help="Planned option premium in dollars.")
    parser.add_argument("--followed-plan", choices=["yes", "no"], help="Whether the trade followed the plan.")
    parser.add_argument("--exit-reason", help="Exit reason, such as profit_target, stop_loss, manual_exit.")
    parser.add_argument("--notes", help="Extra notes to append/replace for this row.")
    parser.add_argument("--append-notes", action="store_true", help="Append notes instead of replacing them.")
    return parser.parse_args()


def text_value(value: object) -> str:
    """Return clean text for CSV fields."""

    if pd.isna(value):
        return ""
    return str(value)


def number_or_none(value: object) -> float | None:
    """Convert CSV values to float when possible."""

    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def calculate_outcome_r(row: pd.Series) -> float:
    """Calculate R from actual prices and the planned stop."""

    actual_entry = number_or_none(row.get("actual_entry"))
    actual_exit = number_or_none(row.get("actual_exit"))
    planned_stop = number_or_none(row.get("planned_stop"))
    direction = text_value(row.get("direction")).lower()

    if actual_entry is None or actual_exit is None or planned_stop is None:
        raise ValueError("actual_entry, actual_exit, and planned_stop are required to calculate outcome_r.")

    risk = abs(actual_entry - planned_stop)
    if risk == 0:
        raise ValueError("Risk per share is zero. Check actual_entry and planned_stop.")

    if direction == "short":
        return round((actual_entry - actual_exit) / risk, 4)
    if direction == "long":
        return round((actual_exit - actual_entry) / risk, 4)
    raise ValueError(f"Unknown direction: {direction}")


def open_rows(trades: pd.DataFrame) -> pd.DataFrame:
    """Return rows that still need outcome details."""

    if trades.empty:
        return trades
    missing_outcome = trades["outcome_r"].isna() | (trades["outcome_r"].astype(str).str.strip() == "")
    missing_exit = trades["actual_exit"].isna() | (trades["actual_exit"].astype(str).str.strip() == "")
    result = trades[missing_outcome | missing_exit].copy()
    result.insert(0, "row", result.index + 1)
    keep = [
        "row",
        "trade_date",
        "entry_time_et",
        "symbol",
        "setup",
        "direction",
        "signal_status",
        "planned_entry",
        "planned_stop",
        "planned_target",
        "actual_entry",
        "actual_exit",
        "vehicle",
        "risk_tier",
        "planned_option_premium",
        "outcome_r",
        "notes",
    ]
    return result[keep]


def update_trade(trades: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """Apply command-line updates to one paper-trade row."""

    if args.row is None:
        raise ValueError("Use --row to choose which paper-trade row to update.")

    row_index = args.row - 1
    if row_index < 0 or row_index >= len(trades):
        raise IndexError(f"--row {args.row} is outside the paper log range 1-{len(trades)}.")

    result = trades.copy().astype(object)
    updates = {
        "actual_entry": args.actual_entry,
        "actual_exit": args.actual_exit,
        "exit_time_et": args.exit_time,
        "shares": args.shares,
        "vehicle": args.vehicle,
        "risk_tier": args.risk_tier,
        "planned_option_premium": args.planned_option_premium,
        "followed_plan": args.followed_plan,
        "exit_reason": args.exit_reason,
    }
    for column, value in updates.items():
        if value is not None:
            result.at[row_index, column] = value

    if args.notes is not None:
        if args.append_notes:
            existing = text_value(result.at[row_index, "notes"])
            result.at[row_index, "notes"] = f"{existing} | {args.notes}" if existing else args.notes
        else:
            result.at[row_index, "notes"] = args.notes

    result.at[row_index, "outcome_r"] = calculate_outcome_r(result.loc[row_index])
    return result


def main() -> None:
    args = parse_args()
    trades = read_existing(args.paper_csv)

    if args.list_open:
        rows = open_rows(trades)
        if rows.empty:
            print("No open paper-trade rows.")
        else:
            print(rows.to_string(index=False))
        return

    updated = update_trade(trades, args)
    updated.to_csv(args.paper_csv, index=False)
    row = updated.iloc[args.row - 1]
    print(f"Updated row {args.row}: {row['symbol']} {row['setup']} outcome_r={row['outcome_r']}")


if __name__ == "__main__":
    main()
