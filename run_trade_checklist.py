"""Build a paper trade entry checklist from current scanner candidates.

This is research and paper workflow only. It creates a checklist to review
before a paper trade. It does not place orders, create alerts, or connect to
broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from reports.refresh_status import market_refresh_state
from run_dashboard import read_csv_or_empty
from run_playbook import markdown_table


CHECKS = [
    "Current-candle signal, not an earlier-today signal.",
    "Scanner status is allowed.",
    "Position sizing status is size_ok.",
    "Entry is not chased beyond the planned entry area.",
    "Stop is accepted before entry.",
    "Target and force-exit time are known before entry.",
    "Daily and monthly loss stops have not been hit.",
    "No earnings/news/event reason to skip.",
    "This is a paper trade, not real-money execution.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the paper trade entry checklist.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def current_candidates(
    scanner: pd.DataFrame,
    sizing: pd.DataFrame,
    market: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Join candidates with sizing status only for an active open session."""

    market = market or market_refresh_state()
    if scanner.empty or not market.get("market_is_open", False):
        return pd.DataFrame()

    current = scanner[
        scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
        & (scanner["signal_freshness"] == "current_candle")
        & (scanner["scan_date"].astype(str) == str(market.get("today", "")))
    ].copy()
    if current.empty:
        return current

    if sizing.empty:
        current["sizing_status"] = ""
        current["suggested_shares"] = ""
        current["estimated_risk_dollars"] = ""
        return current

    join_keys = ["symbol", "setup", "direction", "planned_entry", "planned_stop"]
    available_keys = [column for column in join_keys if column in current.columns and column in sizing.columns]
    sizing_keep = available_keys + [
        column for column in ["sizing_status", "suggested_shares", "estimated_risk_dollars", "sizing_reason"] if column in sizing.columns
    ]
    return current.merge(sizing[sizing_keep], on=available_keys, how="left") if available_keys else current


def write_checklist(path: Path, candidates: pd.DataFrame) -> None:
    """Write the Markdown checklist."""

    checklist = "\n".join(f"- [ ] {item}" for item in CHECKS)
    table_columns = [
        "symbol",
        "setup",
        "direction",
        "scanner_status",
        "signal_freshness",
        "planned_entry",
        "planned_stop",
        "planned_target",
        "suggested_shares",
        "sizing_status",
        "notes",
    ]
    candidate_table = candidates[[column for column in table_columns if column in candidates.columns]]

    path.write_text(
        f"""# Paper Trade Entry Checklist

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## Current Candidates

{markdown_table(candidate_table)}

## Required Checks

{checklist}

## Decision

```text
Take the paper trade only if every required check passes.
If any item fails, skip the trade or log it as watch-only.
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    candidates = current_candidates(scanner, sizing)

    path = args.output_dir / "trade_entry_checklist.md"
    write_checklist(path, candidates)
    print(f"Saved trade checklist: {path}")


if __name__ == "__main__":
    main()
