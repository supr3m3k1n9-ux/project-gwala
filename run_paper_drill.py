"""Run a sandbox paper-trade workflow drill.

This is research and paper workflow only. It creates a fake completed trade
from the latest scanner output, reviews it, and builds a checkpoint report in
logs/paper_drill/. It does not touch data/paper_trades.csv, place orders, or
connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_checkpoint_report import write_report as write_checkpoint_report
from run_paper_import import PAPER_COLUMNS, scanner_to_paper_rows
from run_paper_review import load_paper_trades, write_report as write_paper_review
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a sandbox paper workflow drill.")
    parser.add_argument(
        "--scanner-csv",
        type=Path,
        default=Path("logs/daily_paper_signal_scanner.csv"),
        help="Daily scanner CSV to use as the source candidate.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("logs/paper_drill"),
        help="Sandbox output directory. The real paper journal is not modified.",
    )
    parser.add_argument(
        "--freshness",
        choices=["current_candle", "earlier_today", "all"],
        default="all",
        help="Candidate freshness to drill. Defaults to all so the drill works outside market hours.",
    )
    parser.add_argument(
        "--status",
        choices=["allowed", "blocked_watch_only"],
        default="allowed",
        help="Scanner status to rehearse.",
    )
    parser.add_argument(
        "--outcome-r",
        type=float,
        default=1.0,
        help="Fake completed-trade outcome in R for the drill.",
    )
    parser.add_argument(
        "--scenario",
        choices=["single", "full_set"],
        default="full_set",
        help="single uses --outcome-r. full_set rehearses win, loss, breakeven, and plan-break rows.",
    )
    parser.add_argument("--shares", type=int, default=1, help="Fake paper share count for the drill row.")
    parser.add_argument("--exit-time", default="15:55", help="Fake exit time in ET.")
    return parser.parse_args()


def pick_candidate(scanner: pd.DataFrame, status: str, freshness: str) -> pd.DataFrame:
    """Pick one scanner candidate for a deterministic workflow rehearsal."""

    candidates = scanner_to_paper_rows(scanner, [status], freshness)
    if candidates.empty:
        raise ValueError(
            f"No scanner candidates matched status={status!r} and freshness={freshness!r}. "
            "Run the daily scanner first or loosen --freshness for the drill."
        )

    sort_columns = ["trade_date", "entry_time_et", "symbol", "setup"]
    return candidates.sort_values(sort_columns).head(1).reset_index(drop=True)


def apply_fake_outcome(
    row: pd.Series,
    outcome_r: float,
    shares: int,
    exit_time: str,
    label: str = "simulated",
    followed_plan: str = "yes",
) -> pd.DataFrame:
    """Fill one paper-log row with a fake completed outcome."""

    result = pd.DataFrame([row.to_dict()], columns=PAPER_COLUMNS).astype(object)
    entry = float(result.at[0, "planned_entry"])
    stop = float(result.at[0, "planned_stop"])
    risk = abs(entry - stop)
    if risk == 0:
        raise ValueError("Candidate has zero planned risk. Cannot run the drill.")

    direction = str(result.at[0, "direction"]).lower()
    if direction == "short":
        exit_price = entry - (outcome_r * risk)
    else:
        exit_price = entry + (outcome_r * risk)

    result.at[0, "actual_entry"] = round(entry, 4)
    result.at[0, "actual_exit"] = round(exit_price, 4)
    result.at[0, "exit_time_et"] = exit_time
    result.at[0, "shares"] = shares
    result.at[0, "outcome_r"] = round(outcome_r, 4)
    result.at[0, "followed_plan"] = followed_plan
    result.at[0, "exit_reason"] = f"paper_drill_{label}"
    existing_notes = str(result.at[0, "notes"]).strip()
    drill_note = f"SANDBOX DRILL ONLY - {label} case, not a real paper trade."
    result.at[0, "notes"] = f"{drill_note} {existing_notes}" if existing_notes else drill_note
    return result


def build_drill_trades(candidate: pd.Series, args: argparse.Namespace) -> pd.DataFrame:
    """Build one or more fake completed trades for the drill."""

    if args.scenario == "single":
        return apply_fake_outcome(candidate, args.outcome_r, args.shares, args.exit_time)

    cases = [
        ("planned_win", 1.0, "yes"),
        ("planned_loss", -1.0, "yes"),
        ("breakeven", 0.0, "yes"),
        ("plan_break", -1.5, "no"),
    ]
    rows = [
        apply_fake_outcome(candidate, outcome_r, args.shares, args.exit_time, label, followed_plan)
        for label, outcome_r, followed_plan in cases
    ]
    result = pd.concat(rows, ignore_index=True)
    result["trade_date"] = result["trade_date"].astype(str)
    return result[PAPER_COLUMNS]


def write_drill_summary(path: Path, drill_trade: pd.DataFrame, review: pd.DataFrame, output_dir: Path) -> None:
    """Write a small command-center summary for the drill run."""

    row = drill_trade.iloc[0]
    status_summary = (
        review.groupby("signal_status")["review_r"]
        .agg(trades="count", avg_r="mean", total_r="sum")
        .reset_index()
    )
    if not status_summary.empty:
        status_summary["avg_r"] = status_summary["avg_r"].round(4)
        status_summary["total_r"] = status_summary["total_r"].round(4)

    path.write_text(
        f"""# Paper Workflow Drill

This is a sandbox rehearsal only. It does not modify `data/paper_trades.csv`.

## Drill Trade

```text
Symbol: {row["symbol"]}
Setup: {row["setup"]}
Direction: {row["direction"]}
Signal status: {row["signal_status"]}
Planned entry: {row["planned_entry"]}
Planned stop: {row["planned_stop"]}
First fake outcome: {row["outcome_r"]}R
Drill rows: {len(drill_trade)}
```

## Review Snapshot

{markdown_table(status_summary)}

## Files Created

```text
{output_dir / "paper_drill_trades.csv"}
{output_dir / "paper_review_clean_trades.csv"}
{output_dir / "paper_review_summary.md"}
{output_dir / "paper_validation_checkpoint.md"}
{output_dir / "paper_drill_summary.md"}
```

## What This Proves

```text
The scanner candidate can become completed paper-log rows.
The paper review can calculate/confirm R.
The checkpoint report can read the sandbox review and update gate progress.
The real paper journal stays untouched.
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    if not args.scanner_csv.exists():
        raise FileNotFoundError(f"Scanner CSV not found: {args.scanner_csv}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scanner = pd.read_csv(args.scanner_csv)
    candidate = pick_candidate(scanner, args.status, args.freshness)
    drill_trade = build_drill_trades(candidate.iloc[0], args)

    paper_csv = args.output_dir / "paper_drill_trades.csv"
    review_csv = args.output_dir / "paper_review_clean_trades.csv"
    review_report = args.output_dir / "paper_review_summary.md"
    checkpoint_report = args.output_dir / "paper_validation_checkpoint.md"
    drill_summary = args.output_dir / "paper_drill_summary.md"

    drill_trade.to_csv(paper_csv, index=False)
    review = load_paper_trades(paper_csv)
    review.to_csv(review_csv, index=False)
    write_paper_review(review_report, review, paper_csv, args.output_dir)
    write_checkpoint_report(checkpoint_report, drill_trade, review, paper_csv, review_csv)
    write_drill_summary(drill_summary, drill_trade, review, args.output_dir)

    print(f"Saved sandbox paper drill trade: {paper_csv}")
    print(f"Saved sandbox paper review: {review_report}")
    print(f"Saved sandbox checkpoint: {checkpoint_report}")
    print(f"Saved sandbox drill summary: {drill_summary}")


if __name__ == "__main__":
    main()
