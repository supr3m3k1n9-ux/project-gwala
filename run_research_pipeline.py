"""Run the repeatable Project Gwala research pipeline.

This is research and paper workflow only. It does not fetch new data by
default, place orders, create live alerts, or connect to broker execution.

The pipeline reruns the current approved playbook, portfolio profiles,
holdout validation, paper signal journal, journal insights, and then writes one
master summary.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

from run_holdout_validation import stability_interpretation, stability_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Project Gwala research pipeline.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--skip-playbook", action="store_true", help="Reuse the existing approved playbook trade log.")
    parser.add_argument("--latest-signals", type=int, default=30, help="Latest signal count for the paper journal.")
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    """Run one pipeline command and fail fast if it errors."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, check=True)


def read_metric_table(path: Path) -> dict:
    """Read key metrics from a portfolio summary Markdown file."""

    if not path.exists():
        return {}

    metrics = {}
    in_metrics = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Overall Metrics":
            in_metrics = True
            continue
        if in_metrics and line.startswith("## "):
            break
        if in_metrics and line.startswith("|") and "---" not in line and "Metric" not in line:
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) == 2:
                metrics[parts[0]] = parts[1]
    return metrics


def read_journal_status(path: Path) -> pd.DataFrame:
    """Read allowed/blocked signal status from the journal CSV."""

    if not path.exists():
        return pd.DataFrame()

    journal = pd.read_csv(path)
    rows = []
    for status, group in journal.groupby("signal_status"):
        r = group["r_result"].astype(float)
        rows.append(
            {
                "signal_status": status,
                "signals": len(group),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("signal_status")


def read_paper_review(path: Path) -> pd.DataFrame:
    """Read the current manual paper-trade review snapshot."""

    if not path.exists():
        return pd.DataFrame()

    trades = pd.read_csv(path)
    if trades.empty:
        return pd.DataFrame()

    rows = []
    for status, group in trades.groupby("signal_status"):
        r = group["review_r"].astype(float)
        rows.append(
            {
                "signal_status": status,
                "paper_trades": len(group),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("signal_status")


def read_daily_scanner(path: Path) -> pd.DataFrame:
    """Read the latest daily scanner status counts."""

    if not path.exists():
        return pd.DataFrame()

    scanner = pd.read_csv(path)
    if scanner.empty:
        return pd.DataFrame()

    return (
        scanner.groupby("scanner_status")
        .size()
        .reset_index(name="setups")
        .sort_values("scanner_status")
    )


def read_management_snapshot(path: Path) -> pd.DataFrame:
    """Read the top trade-management lab results."""

    if not path.exists():
        return pd.DataFrame()

    results = pd.read_csv(path)
    if results.empty:
        return pd.DataFrame()
    return results.head(5)


def markdown_table(frame: pd.DataFrame) -> str:
    """Convert a small DataFrame to Markdown."""

    if frame.empty:
        return "No rows."

    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def build_holdout_snapshot(path: Path) -> pd.DataFrame:
    """Return only weakness_v1 validation rows for the master summary."""

    if not path.exists():
        return pd.DataFrame()

    results = pd.read_csv(path)
    filtered = results[results["trade_filter"] == "weakness_v1"].copy()
    keep = [
        "window",
        "accepted_trades",
        "win_rate",
        "expectancy_r",
        "profit_factor",
        "max_drawdown_r",
        "final_cumulative_r",
        "expectancy_delta",
        "final_r_delta",
    ]
    return filtered[keep]


def write_master_summary(output_dir: Path) -> Path:
    """Write the one-page research pipeline summary."""

    base_metrics = read_metric_table(output_dir / "portfolio_approved_monthly_stop_3r_summary.md")
    weakness_metrics = read_metric_table(output_dir / "portfolio_approved_monthly_stop_3r_weakness_v1_summary.md")
    holdout_path = output_dir / "holdout_validation_results.csv"
    holdout = build_holdout_snapshot(holdout_path)
    holdout_results = pd.read_csv(holdout_path) if holdout_path.exists() else pd.DataFrame()
    holdout_stability = stability_summary(holdout_results) if not holdout_results.empty else pd.DataFrame()
    holdout_interpretation = stability_interpretation(holdout_stability)
    journal_status = read_journal_status(output_dir / "paper_signal_journal.csv")
    scanner_status = read_daily_scanner(output_dir / "daily_paper_signal_scanner.csv")
    management = read_management_snapshot(output_dir / "trade_management_overall.csv")
    paper_review = read_paper_review(output_dir / "paper_review_clean_trades.csv")

    summary_path = output_dir / "research_pipeline_summary.md"
    summary_path.write_text(
        f"""# Research Pipeline Summary

This is the repeatable Project Gwala research and paper-workflow summary.

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## Current Best Profile

```bash
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
```

## Portfolio Comparison

| Metric | Base monthly_stop_3r | weakness_v1 |
| --- | ---: | ---: |
| Accepted trades | {base_metrics.get("Accepted trades", "")} | {weakness_metrics.get("Accepted trades", "")} |
| Skipped trades | {base_metrics.get("Skipped trades", "")} | {weakness_metrics.get("Skipped trades", "")} |
| Win rate | {base_metrics.get("Win rate", "")} | {weakness_metrics.get("Win rate", "")} |
| Expectancy R | {base_metrics.get("Expectancy R", "")} | {weakness_metrics.get("Expectancy R", "")} |
| Profit factor | {base_metrics.get("Profit factor", "")} | {weakness_metrics.get("Profit factor", "")} |
| Max drawdown R | {base_metrics.get("Max drawdown R", "")} | {weakness_metrics.get("Max drawdown R", "")} |
| Final cumulative R | {base_metrics.get("Final cumulative R", "")} | {weakness_metrics.get("Final cumulative R", "")} |

## Holdout Snapshot

{markdown_table(holdout)}

## Monthly Stability Check

{markdown_table(holdout_stability)}

```text
{holdout_interpretation}
```

## Paper Journal Snapshot

{markdown_table(journal_status)}

## Daily Scanner Snapshot

{markdown_table(scanner_status)}

## Trade Management Snapshot

{markdown_table(management)}

## Forward Paper Review Snapshot

{markdown_table(paper_review)}

## Interpretation

```text
weakness_v1 currently improves the aggregate historical profile, but the monthly
stability check must be read before promoting it: the historical filter can
help in one affected month and hurt in another.

The journal should be used for paper workflow:
- allowed signals are paper-trade candidates
- blocked signals are watch-only
- fresh allowed results should be compared against the historical allowed baseline
- fresh blocked results should be compared against the historical blocked baseline
```

## Main Outputs

```text
PLAYBOOK_CHEATSHEET.md
logs/playbook_approved_summary.md
logs/portfolio_approved_monthly_stop_3r_summary.md
logs/portfolio_approved_monthly_stop_3r_weakness_v1_summary.md
logs/holdout_validation_report.md
logs/paper_signal_journal.md
logs/journal_insights.md
logs/daily_paper_signal_scanner.md
logs/trade_management_lab.md
logs/paper_review_summary.md
logs/research_pipeline_summary.md
```
""",
        encoding="utf-8",
    )
    return summary_path


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    if not args.skip_playbook:
        run_step([python, "run_playbook.py", "--mode", "approved", "--output-dir", str(args.output_dir)])

    run_step([python, "run_portfolio.py", "--profile", "monthly_stop_3r", "--output-dir", str(args.output_dir)])
    run_step(
        [
            python,
            "run_portfolio.py",
            "--profile",
            "monthly_stop_3r",
            "--trade-filter",
            "weakness_v1",
            "--output-dir",
            str(args.output_dir),
        ]
    )
    run_step([python, "run_holdout_validation.py", "--output-dir", str(args.output_dir)])
    run_step(
        [
            python,
            "run_signal_journal.py",
            "--trade-filter",
            "weakness_v1",
            "--latest",
            str(args.latest_signals),
            "--output-dir",
            str(args.output_dir),
        ]
    )
    run_step([python, "run_journal_insights.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_daily_scanner.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trade_management_lab.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_checkpoint_report.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_dashboard.py", "--output-dir", str(args.output_dir)])

    summary_path = write_master_summary(args.output_dir)
    # Keep the app-ready snapshot aligned with reports rebuilt by this run.
    run_step([python, "run_system_state.py", "--output-dir", str(args.output_dir)])
    print(f"\nSaved research pipeline summary: {summary_path}")


if __name__ == "__main__":
    main()
