"""Turn the paper signal journal into plain-English research insights.

This is research/paper workflow only. It summarizes what the journal implies
about the current playbook, the weakness_v1 filter, and paper-trading focus.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate plain-English insights from the paper signal journal.")
    parser.add_argument(
        "--journal-csv",
        type=Path,
        default=Path("logs/paper_signal_journal.csv"),
        help="Paper signal journal CSV.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def summarize(journal: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Summarize R results by one or more journal columns."""

    rows = []
    for group_value, group in journal.groupby(columns, dropna=False):
        if not isinstance(group_value, tuple):
            group_value = (group_value,)
        r = group["r_result"].astype(float)
        row = {column: value for column, value in zip(columns, group_value)}
        row.update(
            {
                "signals": len(group),
                "win_rate": round(float((r > 0).mean()), 4),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
                "loss_count": int((r < 0).sum()),
            }
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["avg_r", "total_r"], ascending=[False, False])


def add_buckets(journal: pd.DataFrame) -> pd.DataFrame:
    """Add readable buckets for insight summaries."""

    result = journal.copy()
    result["r_result"] = result["r_result"].astype(float)
    result["relative_volume"] = result["relative_volume"].astype(float)
    result["room_to_resistance_r"] = result["room_to_resistance_r"].astype(float)
    result["quality_score"] = result["quality_score"].astype(float)

    result["relative_volume_bucket"] = pd.cut(
        result["relative_volume"],
        bins=[-float("inf"), 0.75, 1.0, 1.25, 1.5, 2.0, float("inf")],
        labels=["<0.75", "0.75-1.0", "1.0-1.25", "1.25-1.5", "1.5-2.0", "2.0+"],
    ).astype(str)
    result["room_bucket"] = pd.cut(
        result["room_to_resistance_r"],
        bins=[-float("inf"), 0.75, 1.0, 1.25, 1.5, 2.0, float("inf")],
        labels=["<0.75", "0.75-1.0", "1.0-1.25", "1.25-1.5", "1.5-2.0", "2.0+"],
    ).astype(str)
    result["quality_bucket"] = result["quality_score"].round(0).astype(int).astype(str)
    return result


def top_rows(frame: pd.DataFrame, count: int = 8) -> pd.DataFrame:
    """Return strongest rows."""

    if frame.empty:
        return frame
    return frame.head(count)


def bottom_rows(frame: pd.DataFrame, count: int = 8) -> pd.DataFrame:
    """Return weakest rows."""

    if frame.empty:
        return frame
    return frame.sort_values(["avg_r", "total_r"], ascending=[True, True]).head(count)


def insight_text(journal: pd.DataFrame, by_status: pd.DataFrame, by_symbol_status: pd.DataFrame) -> str:
    """Create concise plain-English implications."""

    allowed = by_status[by_status["signal_status"] == "allowed"].iloc[0]
    blocked = by_status[by_status["signal_status"] == "blocked"].iloc[0]
    blocked_symbols = ", ".join(sorted(journal.loc[journal["signal_status"] == "blocked", "symbol"].unique()))

    strongest_allowed = (
        by_symbol_status[by_symbol_status["signal_status"] == "allowed"]
        .sort_values(["avg_r", "total_r"], ascending=[False, False])
        .iloc[0]
    )
    weakest_allowed = (
        by_symbol_status[by_symbol_status["signal_status"] == "allowed"]
        .sort_values(["avg_r", "total_r"], ascending=[True, True])
        .iloc[0]
    )

    return f"""## Executive Summary

The journal separates signals into two jobs:

```text
Allowed signals are paper-trade candidates.
Blocked signals are watch-only examples of conditions the current filter avoids.
```

The allowed group produced `{allowed["signals"]}` historical signals with
`{allowed["avg_r"]}` average R and `{allowed["total_r"]}` total R. The blocked
group produced `{blocked["signals"]}` historical signals with `{blocked["avg_r"]}`
average R and `{blocked["total_r"]}` total R.

## Main Implications

1. `weakness_v1` is focused, not broad. It only blocks `{blocked["signals"]}`
signals, and those blocks come from `{blocked_symbols}`.

2. The blocked group was meaningfully negative. That supports the idea that the
filter is removing a specific weak pocket rather than randomly reducing trades.

3. The strongest allowed symbol in this journal is `{strongest_allowed["symbol"]}`
with `{strongest_allowed["avg_r"]}` average R. The weakest allowed symbol is
`{weakest_allowed["symbol"]}` with `{weakest_allowed["avg_r"]}` average R.

4. During paper trading, blocked signals should still be logged as watch-only
events. If fresh blocked signals start working, that is evidence the filter may
be overfit or regime-dependent.

5. This remains a research and paper workflow. The journal helps study behavior;
it is not a live execution system.
"""


def write_report(path: Path, journal: pd.DataFrame) -> None:
    """Write the insights Markdown report."""

    journal = add_buckets(journal)
    by_status = summarize(journal, ["signal_status"])
    by_symbol_status = summarize(journal, ["symbol", "signal_status"])
    by_setup_status = summarize(journal, ["playbook_setup", "signal_status"])
    by_block_reason = summarize(journal[journal["signal_status"] == "blocked"], ["block_reason"])
    by_exit = summarize(journal[journal["signal_status"] == "allowed"], ["exit_reason"])
    by_relvol = summarize(journal[journal["signal_status"] == "allowed"], ["symbol", "relative_volume_bucket"])
    by_room = summarize(journal[journal["signal_status"] == "allowed"], ["symbol", "room_bucket"])
    by_quality = summarize(journal[journal["signal_status"] == "allowed"], ["symbol", "quality_bucket"])

    path.write_text(
        f"""# Journal Insights Report

This report contextualizes the paper signal journal and summarizes what the
current research profile implies.

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

{insight_text(journal, by_status, by_symbol_status)}

## Status Summary

{markdown_table(by_status)}

## Symbol Notes

{markdown_table(by_symbol_status)}

## Setup Notes

{markdown_table(by_setup_status)}

## Blocked Signal Lessons

{markdown_table(by_block_reason)}

## Allowed Exit Behavior

{markdown_table(by_exit)}

## Strongest Allowed Relative-Volume Buckets

{markdown_table(top_rows(by_relvol))}

## Weakest Allowed Relative-Volume Buckets

{markdown_table(bottom_rows(by_relvol))}

## Strongest Allowed Room-To-Target Buckets

{markdown_table(top_rows(by_room))}

## Weakest Allowed Room-To-Target Buckets

{markdown_table(bottom_rows(by_room))}

## Strongest Allowed Quality Buckets

{markdown_table(top_rows(by_quality))}

## Weakest Allowed Quality Buckets

{markdown_table(bottom_rows(by_quality))}

## Paper Trading Watch Points

```text
1. Track every allowed signal, even if it feels uncomfortable.
2. Track every blocked signal as watch-only.
3. Compare fresh allowed average R against the historical +0.1202R journal baseline.
4. Compare fresh blocked average R against the historical -0.3469R blocked baseline.
5. Pay special attention to NVDA blocked short conditions and SPY room-to-target blocks.
6. If blocked signals start outperforming allowed signals on fresh data, review weakness_v1.
```

## Files

```text
logs/journal_insights.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    journal = pd.read_csv(args.journal_csv)
    report_path = args.output_dir / "journal_insights.md"
    write_report(report_path, journal)
    print(f"Saved journal insights report: {report_path}")


if __name__ == "__main__":
    main()
