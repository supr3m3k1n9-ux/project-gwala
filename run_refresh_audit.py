"""Append one audit entry per symbol after a requested Webull data refresh.

This command records local-file evidence after a refresh workflow completes.
It is data audit only and never fetches data, imports paper trades, or places
orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_data_integrity import inspect_file
from run_playbook import markdown_table


AUDIT_COLUMNS = [
    "refresh_run_at_et",
    "symbol",
    "m30_status",
    "m30_latest_session",
    "m30_latest_bar_et",
    "m5_status",
    "m5_latest_session",
    "m5_latest_bar_et",
    "m5_session_coverage",
    "refresh_evidence_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record the outcome evidence of a requested market-data refresh.")
    parser.add_argument("--symbols", nargs="+", default=[], help="Symbols requested by the refresh workflow.")
    parser.add_argument("--record", action="store_true", help="Append a new audit event for the provided symbols.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where refreshed candle CSVs live.")
    parser.add_argument("--audit-csv", type=Path, default=Path("data/market_refresh_audit.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where the report is saved.")
    return parser.parse_args()


def read_existing(path: Path) -> pd.DataFrame:
    """Read existing refresh audit entries."""

    if not path.exists():
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    return pd.read_csv(path)


def audit_rows(symbols: list[str], data_dir: Path, run_at: str | None = None) -> pd.DataFrame:
    """Build audit evidence rows for one completed refresh request."""

    run_at = run_at or datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    rows = []
    for symbol in [value.upper() for value in symbols]:
        m30 = inspect_file(symbol, "M30", data_dir / f"webull_{symbol}_M30_candles.csv")
        m5 = inspect_file(symbol, "M5", data_dir / f"webull_{symbol}_M5_candles.csv")
        if m30["status"] not in {"ok", "warning"} or m5["status"] not in {"ok", "warning"}:
            evidence_status = "failed_or_missing_file"
        elif m30["latest_session"] != m5["latest_session"]:
            evidence_status = "timeframe_session_mismatch"
        elif m5["session_coverage"] == "in_progress":
            evidence_status = "current_session_in_progress"
        elif m5["session_coverage"] == "provider_final_bar":
            evidence_status = "files_present_provider_final_bar"
        elif m5["session_coverage"] != "complete":
            evidence_status = "latest_session_incomplete"
        else:
            evidence_status = "files_present_and_complete"
        rows.append(
            {
                "refresh_run_at_et": run_at,
                "symbol": symbol,
                "m30_status": m30["status"],
                "m30_latest_session": m30["latest_session"],
                "m30_latest_bar_et": m30["latest_bar_et"],
                "m5_status": m5["status"],
                "m5_latest_session": m5["latest_session"],
                "m5_latest_bar_et": m5["latest_bar_et"],
                "m5_session_coverage": m5["session_coverage"],
                "refresh_evidence_status": evidence_status,
            }
        )
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def write_report(path: Path, audit: pd.DataFrame) -> None:
    """Write refresh audit report."""

    recent = audit.tail(40) if not audit.empty else pd.DataFrame()
    status = audit.groupby("refresh_evidence_status").size().reset_index(name="symbol_checks") if not audit.empty else pd.DataFrame()
    path.write_text(
        f"""# Market Data Refresh Audit

This append-only audit records local candle-file evidence after deliberate
Webull refresh workflow runs.

Important: this report does not fetch data, create signals, import paper
trades, or connect to broker execution.

## Status Summary

{markdown_table(status)}

## Latest Audit Entries

{markdown_table(recent)}

## Files

```text
data/market_refresh_audit.csv
logs/market_refresh_audit.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_existing(args.audit_csv)
    if args.record and not args.symbols:
        raise ValueError("Use --symbols when recording a refresh audit event.")
    new_rows = audit_rows(args.symbols, args.data_dir) if args.record else pd.DataFrame(columns=AUDIT_COLUMNS)
    combined = pd.concat([existing, new_rows], ignore_index=True)
    if args.record or not args.audit_csv.exists():
        args.audit_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.audit_csv, index=False)
    report_path = args.output_dir / "market_refresh_audit.md"
    write_report(report_path, combined)
    print(f"Refresh audit rows appended: {len(new_rows)}")
    journal_action = "Saved refresh audit CSV" if args.record else "Refresh audit CSV unchanged"
    print(f"{journal_action}: {args.audit_csv}")
    print(f"Saved refresh audit report: {report_path}")


if __name__ == "__main__":
    main()
