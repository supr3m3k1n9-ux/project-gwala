"""Build the 30/60 trade paper-validation checkpoint report.

This is research and paper workflow only. It reviews completed paper trades
against the current Project Gwala confidence gates. It does not place orders,
create alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_paper_review import ALLOWED_BASELINE_R, BLOCKED_BASELINE_R
from run_playbook import markdown_table


FIRST_GATE = 30
STRONG_GATE = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the paper-validation checkpoint report.")
    parser.add_argument(
        "--paper-review-csv",
        type=Path,
        default=Path("logs/paper_review_clean_trades.csv"),
        help="Completed paper trade review CSV.",
    )
    parser.add_argument(
        "--paper-csv",
        type=Path,
        default=Path("data/paper_trades.csv"),
        help="Raw paper trade log.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def summarize_status(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize completed paper trades by allowed/blocked status."""

    if trades.empty:
        return pd.DataFrame()

    rows = []
    for status, group in trades.groupby("signal_status"):
        r = group["review_r"].astype(float)
        rows.append(
            {
                "signal_status": status,
                "trades": len(group),
                "win_rate": round(float((r > 0).mean()), 4),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
                "best_r": round(float(r.max()), 4),
                "worst_r": round(float(r.min()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("signal_status")


def summarize_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize completed allowed paper trades by symbol."""

    if trades.empty:
        return pd.DataFrame()

    allowed = trades[trades["signal_status"] == "allowed"]
    if allowed.empty:
        return pd.DataFrame()

    rows = []
    for symbol, group in allowed.groupby("symbol"):
        r = group["review_r"].astype(float)
        rows.append(
            {
                "symbol": symbol,
                "trades": len(group),
                "win_rate": round(float((r > 0).mean()), 4),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values(["avg_r", "total_r"], ascending=[False, False])


def summarize_plan(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize plan discipline."""

    if trades.empty:
        return pd.DataFrame()

    rows = []
    for followed_plan, group in trades.groupby("followed_plan"):
        r = group["review_r"].astype(float)
        rows.append(
            {
                "followed_plan": followed_plan,
                "trades": len(group),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("followed_plan")


def gate_status(allowed_count: int) -> str:
    """Return the current validation gate label."""

    if allowed_count >= STRONG_GATE:
        return "strong checkpoint reached"
    if allowed_count >= FIRST_GATE:
        return "first checkpoint reached"
    return "building sample"


def recommendation(allowed_count: int, allowed_avg: float, blocked_count: int, blocked_avg: float) -> str:
    """Create the next recommendation."""

    if allowed_count < FIRST_GATE:
        remaining = FIRST_GATE - allowed_count
        return f"Keep collecting paper trades. Need {remaining} more allowed completed trades for the first checkpoint."

    if allowed_avg < ALLOWED_BASELINE_R:
        return "Pause strategy promotion. Paper average R is below the fresh-data baseline; review execution quality and market regime."

    if blocked_count > 0 and blocked_avg > allowed_avg:
        return "Review weakness_v1. Blocked/watch-only trades are outperforming allowed trades."

    if allowed_count < STRONG_GATE:
        remaining = STRONG_GATE - allowed_count
        return f"First checkpoint is acceptable. Continue toward the stronger 60-trade checkpoint; {remaining} allowed trades remaining."

    return "Strong checkpoint reached. Review whether paper results justify the next research phase."


def write_report(
    path: Path,
    raw_log: pd.DataFrame,
    review: pd.DataFrame,
    paper_csv: Path | None = None,
    paper_review_csv: Path | None = None,
) -> None:
    """Write the checkpoint report."""

    paper_csv = paper_csv or Path("data/paper_trades.csv")
    paper_review_csv = paper_review_csv or Path("logs/paper_review_clean_trades.csv")
    allowed = review[review["signal_status"] == "allowed"] if not review.empty else pd.DataFrame()
    blocked = review[review["signal_status"] == "blocked"] if not review.empty else pd.DataFrame()
    allowed_count = len(allowed)
    blocked_count = len(blocked)
    allowed_avg = float(allowed["review_r"].mean()) if allowed_count else 0.0
    blocked_avg = float(blocked["review_r"].mean()) if blocked_count else 0.0

    progress = pd.DataFrame(
        [
            {"checkpoint": "raw paper rows", "value": len(raw_log)},
            {"checkpoint": "completed paper trades", "value": len(review)},
            {"checkpoint": "allowed completed trades", "value": allowed_count},
            {"checkpoint": "blocked completed trades", "value": blocked_count},
            {"checkpoint": "allowed avg R", "value": round(allowed_avg, 4)},
            {"checkpoint": "allowed baseline R", "value": ALLOWED_BASELINE_R},
            {"checkpoint": "blocked avg R", "value": round(blocked_avg, 4)},
            {"checkpoint": "blocked baseline R", "value": BLOCKED_BASELINE_R},
            {"checkpoint": "trades until 30 gate", "value": max(FIRST_GATE - allowed_count, 0)},
            {"checkpoint": "trades until 60 gate", "value": max(STRONG_GATE - allowed_count, 0)},
            {"checkpoint": "gate status", "value": gate_status(allowed_count)},
        ]
    )

    path.write_text(
        f"""# Paper Validation Checkpoint

This report tracks Project Gwala's forward paper-validation progress.

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## Recommendation

```text
{recommendation(allowed_count, allowed_avg, blocked_count, blocked_avg)}
```

## Progress

{markdown_table(progress)}

## Completed Trade Status

{markdown_table(summarize_status(review))}

## Allowed Trades By Symbol

{markdown_table(summarize_symbol(review))}

## Plan Discipline

{markdown_table(summarize_plan(review))}

## Gate Rules

```text
30 allowed completed paper trades = first useful checkpoint
60 allowed completed paper trades = stronger checkpoint
Allowed paper average should stay near or above +{ALLOWED_BASELINE_R}R
Blocked/watch-only trades should not consistently outperform allowed trades
```

## Files

```text
{paper_csv}
{paper_review_csv}
{path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw_log = read_csv_or_empty(args.paper_csv)
    review = read_csv_or_empty(args.paper_review_csv)
    report_path = args.output_dir / "paper_validation_checkpoint.md"
    write_report(report_path, raw_log, review, args.paper_csv, args.paper_review_csv)
    print(f"Saved checkpoint report: {report_path}")


if __name__ == "__main__":
    main()
