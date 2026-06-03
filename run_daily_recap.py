"""Build an end-of-day paper workflow recap.

This is research and paper workflow only. It summarizes scanner output,
position sizing, paper trade progress, and mistake tracking. It does not fetch
data, place orders, create alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_dashboard import paper_progress, read_csv_or_empty
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the daily Project Gwala recap.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"), help="Paper log CSV.")
    parser.add_argument("--mistake-csv", type=Path, default=Path("data/paper_mistakes.csv"))
    return parser.parse_args()


def counts(frame: pd.DataFrame, column: str, name: str) -> pd.DataFrame:
    """Count values in a column."""

    if frame.empty or column not in frame.columns:
        return pd.DataFrame()
    return frame.groupby(column).size().reset_index(name=name).sort_values(column)


def completed_today(paper_review: pd.DataFrame, scanner: pd.DataFrame) -> pd.DataFrame:
    """Return completed paper trades from scanner dates when possible."""

    if paper_review.empty:
        return pd.DataFrame()
    if scanner.empty or "scan_date" not in scanner.columns:
        return paper_review.tail(10)
    latest = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
    if not latest or "trade_date" not in paper_review.columns:
        return paper_review.tail(10)
    return paper_review[paper_review["trade_date"].astype(str) == latest[-1]]


def recap_notes(scanner: pd.DataFrame, sizing: pd.DataFrame, progress: dict[str, object]) -> str:
    """Create short recap notes."""

    notes = []
    if scanner.empty:
        notes.append("Scanner output is missing. Run the daily workflow before using this recap.")
    else:
        current = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]
        notes.append(f"Current-candle candidate count: {len(current)}.")

    eligible = pd.DataFrame()
    if not sizing.empty and "sizing_status" in sizing.columns:
        eligible = sizing[sizing["sizing_status"] == "size_ok"]
    notes.append(f"Eligible paper size count: {len(eligible)}.")
    notes.append(f"Allowed completed paper trades: {progress['allowed_count']} of 30 for the first checkpoint.")
    return "\n".join(f"- {note}" for note in notes)


def write_recap(path: Path, args: argparse.Namespace) -> None:
    """Write the recap report."""

    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    paper_log = read_csv_or_empty(args.paper_csv)
    paper_review = read_csv_or_empty(args.output_dir / "paper_review_clean_trades.csv")
    mistakes = read_csv_or_empty(args.mistake_csv)
    progress = paper_progress(paper_log, paper_review)

    path.write_text(
        f"""# Daily Paper Recap

Important: this is research/paper workflow only. It does not fetch data, place
orders, create alerts, or connect to broker execution.

## Recap Notes

{recap_notes(scanner, sizing, progress)}

## Scanner Status

{markdown_table(counts(scanner, "scanner_status", "setups"))}

## Signal Freshness

{markdown_table(counts(scanner, "signal_freshness", "setups"))}

## Position Sizing Status

{markdown_table(counts(sizing, "sizing_status", "setups"))}

## Completed Paper Trades Today

{markdown_table(completed_today(paper_review, scanner))}

## Paper Progress

{markdown_table(pd.DataFrame([
    {"checkpoint": "paper rows logged", "value": progress["logged_rows"]},
    {"checkpoint": "completed paper trades", "value": progress["completed_rows"]},
    {"checkpoint": "allowed completed trades", "value": progress["allowed_count"]},
    {"checkpoint": "allowed average R", "value": progress["allowed_avg_r"]},
    {"checkpoint": "trades until 30-trade gate", "value": progress["first_gate_remaining"]},
]))}

## Mistakes Logged

{markdown_table(counts(mistakes, "mistake_type", "count"))}

## Next Session Focus

```text
Wait for current-candle allowed candidates.
Use the checklist before any paper entry.
Update paper outcomes after exits.
Log process mistakes only when they actually happened.
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "daily_recap.md"
    write_recap(path, args)
    print(f"Saved daily recap: {path}")


if __name__ == "__main__":
    main()
