"""Create and summarize a paper-trading mistake tracker.

This is research and paper workflow only. It gives the trader a structured
place to record process mistakes without changing strategy logic or placing
orders.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


MISTAKE_COLUMNS = [
    "trade_date",
    "symbol",
    "setup",
    "mistake_type",
    "severity",
    "cost_r",
    "lesson",
    "fix_next_time",
]

MISTAKE_TYPES = [
    "late_entry",
    "chased_entry",
    "oversized",
    "moved_stop",
    "ignored_stop",
    "early_exit",
    "missed_exit",
    "wrong_setup",
    "stale_signal",
    "news_event_skip_missed",
    "plan_not_followed",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/summarize the paper mistake tracker.")
    parser.add_argument("--mistake-csv", type=Path, default=Path("data/paper_mistakes.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_or_create(path: Path) -> pd.DataFrame:
    """Read the mistake CSV or create an empty template."""

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=MISTAKE_COLUMNS).to_csv(path, index=False)
        return pd.DataFrame(columns=MISTAKE_COLUMNS)

    mistakes = pd.read_csv(path)
    for column in MISTAKE_COLUMNS:
        if column not in mistakes.columns:
            mistakes[column] = ""
    return mistakes[MISTAKE_COLUMNS]


def numeric_cost(frame: pd.DataFrame) -> pd.Series:
    """Return numeric cost R with blanks treated as zero for summaries."""

    if frame.empty:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["cost_r"], errors="coerce").fillna(0.0)


def summarize(mistakes: pd.DataFrame, column: str) -> pd.DataFrame:
    """Summarize mistakes by a column."""

    if mistakes.empty:
        return pd.DataFrame()
    frame = mistakes.copy()
    frame["cost_r_numeric"] = numeric_cost(frame)
    rows = []
    for value, group in frame.groupby(column, dropna=False):
        rows.append(
            {
                column: value if str(value).strip() else "unknown",
                "count": len(group),
                "total_cost_r": round(float(group["cost_r_numeric"].sum()), 4),
                "avg_cost_r": round(float(group["cost_r_numeric"].mean()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values(["total_cost_r", "count"], ascending=[True, False])


def write_report(path: Path, mistake_csv: Path, mistakes: pd.DataFrame) -> None:
    """Write the mistake tracker report."""

    mistake_menu = pd.DataFrame({"mistake_type": MISTAKE_TYPES})
    path.write_text(
        f"""# Paper Mistake Tracker

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## How To Use

```text
After a paper trade, add a row to {mistake_csv} only if there was a process mistake.
Use cost_r as the estimated R damage from the mistake.
If there was no mistake, do not add a row.
```

## Mistake Types

{markdown_table(mistake_menu)}

## Summary By Mistake Type

{markdown_table(summarize(mistakes, "mistake_type"))}

## Summary By Symbol

{markdown_table(summarize(mistakes, "symbol"))}

## Recent Mistakes

{markdown_table(mistakes.tail(20))}
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    mistakes = read_or_create(args.mistake_csv)
    report_path = args.output_dir / "paper_mistake_tracker.md"
    write_report(report_path, args.mistake_csv, mistakes)
    print(f"Saved mistake tracker CSV: {args.mistake_csv}")
    print(f"Saved mistake tracker report: {report_path}")


if __name__ == "__main__":
    main()
