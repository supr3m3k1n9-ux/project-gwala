"""Audit local paper exits against saved 5m candles.

This is research and paper-validation only. It does not place orders, close
orders, create broker alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config.runtime_paths import runtime_data_path
from run_open_paper_monitor import monitor_trade, text_value
from run_paper_import import read_existing
from run_playbook import markdown_table


AUDIT_COLUMNS = [
    "row",
    "trade_date",
    "symbol",
    "setup",
    "direction",
    "entry_time_et",
    "recorded_exit_time_et",
    "expected_exit_time_et",
    "recorded_exit",
    "expected_exit",
    "recorded_r",
    "expected_r",
    "recorded_exit_reason",
    "expected_exit_reason",
    "audit_status",
    "audit_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Project Gwala local paper exits.")
    parser.add_argument("--paper-csv", type=Path, default=runtime_data_path("paper_trades.csv"), help="Paper trade log.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Directory with saved Webull M5 candles.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where audit reports are saved.")
    return parser.parse_args()


def number_or_none(value: object) -> float | None:
    """Convert a CSV value to float when possible."""

    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def close_enough(left: float | None, right: float | None, tolerance: float = 0.01) -> bool:
    """Return whether two numbers match within a small price/R tolerance."""

    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) <= tolerance


def expected_exit_for_recorded_trade(row: pd.Series, data_dir: Path) -> dict[str, object]:
    """Run the monitor logic on a completed row to rebuild its expected exit."""

    probe = row.copy()
    probe["actual_exit"] = ""
    probe["outcome_r"] = ""
    return monitor_trade(probe, data_dir)


def audit_row(row: pd.Series, data_dir: Path) -> dict[str, object]:
    """Audit one paper row against the saved 5m exit rules."""

    recorded_exit = number_or_none(row.get("actual_exit"))
    recorded_r = number_or_none(row.get("outcome_r"))
    recorded_reason = text_value(row.get("exit_reason"))
    recorded_time = text_value(row.get("exit_time_et"))

    base = {
        "row": int(row["row"]),
        "trade_date": text_value(row.get("trade_date")),
        "symbol": text_value(row.get("symbol")).upper(),
        "setup": text_value(row.get("setup")),
        "direction": text_value(row.get("direction")),
        "entry_time_et": text_value(row.get("entry_time_et")),
        "recorded_exit_time_et": recorded_time,
        "expected_exit_time_et": "",
        "recorded_exit": recorded_exit if recorded_exit is not None else "",
        "expected_exit": "",
        "recorded_r": recorded_r if recorded_r is not None else "",
        "expected_r": "",
        "recorded_exit_reason": recorded_reason,
        "expected_exit_reason": "",
        "audit_status": "needs_review",
        "audit_note": "",
    }

    if recorded_exit is None or recorded_r is None or not recorded_reason:
        base["audit_status"] = "open_or_incomplete"
        base["audit_note"] = "Paper row does not have a complete recorded exit yet."
        return base

    try:
        expected = expected_exit_for_recorded_trade(row, data_dir)
    except (FileNotFoundError, ValueError) as error:
        base["audit_status"] = "blocked"
        base["audit_note"] = str(error)
        return base

    if expected.get("monitor_status") != "exit_ready":
        base["audit_status"] = "needs_review"
        base["audit_note"] = text_value(expected.get("monitor_note")) or "No expected exit was found in saved 5m candles."
        return base

    expected_exit = number_or_none(expected.get("actual_exit"))
    expected_r = number_or_none(expected.get("outcome_r"))
    expected_reason = text_value(expected.get("exit_reason"))
    expected_time = text_value(expected.get("exit_time_et"))
    base.update(
        {
            "expected_exit_time_et": expected_time,
            "expected_exit": expected_exit if expected_exit is not None else "",
            "expected_r": expected_r if expected_r is not None else "",
            "expected_exit_reason": expected_reason,
        }
    )

    matches = [
        recorded_time == expected_time,
        close_enough(recorded_exit, expected_exit),
        close_enough(recorded_r, expected_r, tolerance=0.0001),
        recorded_reason == expected_reason,
    ]
    if all(matches):
        base["audit_status"] = "matched"
        base["audit_note"] = "Recorded paper exit matches saved 5m candle rules."
    else:
        base["audit_status"] = "mismatch"
        base["audit_note"] = "Recorded exit differs from the saved 5m candle rule result."
    return base


def build_audit(trades: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Build the exit audit table for local paper rows."""

    if trades.empty:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    rows = trades.copy()
    rows.insert(0, "row", rows.index + 1)
    audits = [audit_row(row, data_dir) for _, row in rows.iterrows()]
    return pd.DataFrame(audits, columns=AUDIT_COLUMNS)


def write_report(path: Path, audit: pd.DataFrame) -> None:
    """Write the exit audit Markdown report."""

    if audit.empty:
        status_counts = pd.DataFrame(columns=["audit_status", "rows"])
        matched = pd.DataFrame(columns=AUDIT_COLUMNS)
        review = pd.DataFrame(columns=AUDIT_COLUMNS)
    else:
        status_counts = audit.groupby("audit_status").size().reset_index(name="rows")
        matched = audit[audit["audit_status"] == "matched"]
        review = audit[audit["audit_status"] != "matched"]

    path.write_text(
        f"""# Local Paper Exit Audit

This report checks local paper-trade exits against saved Webull 5m candles.

Important: this is research and paper-validation only. It does not place,
close, or modify broker orders.

## Status Counts

{markdown_table(status_counts)}

## Needs Review

{markdown_table(review)}

## Matched Exits

{markdown_table(matched)}

## Files

```text
logs/paper_exit_audit.csv
logs/paper_exit_audit.md
data/paper_trades.csv
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trades = read_existing(args.paper_csv)
    audit = build_audit(trades, args.data_dir)

    csv_path = args.output_dir / "paper_exit_audit.csv"
    report_path = args.output_dir / "paper_exit_audit.md"
    audit.to_csv(csv_path, index=False)
    write_report(report_path, audit)

    matched = int((audit["audit_status"] == "matched").sum()) if not audit.empty else 0
    mismatched = int((audit["audit_status"] == "mismatch").sum()) if not audit.empty else 0
    print(f"Matched exits: {matched}")
    print(f"Mismatched exits: {mismatched}")
    print(f"Saved exit audit CSV: {csv_path}")
    print(f"Saved exit audit report: {report_path}")


if __name__ == "__main__":
    main()
