"""Check whether research candidates hold up in newer trade slices.

This is a simple walk-forward-style stability report. It reads candidate trade
logs, splits them chronologically, and compares the older slice to the newer
slice. It is research-only and does not promote anything to execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table
from run_promotion_review import read_csv_or_empty


REVIEW_STATUSES = {"research_ready", "promising"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build walk-forward research review.")
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=Path("logs/deeper_research"),
        help="Folder containing research_confidence.csv and trade logs.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum confidence rows to inspect.")
    return parser.parse_args()


def uses_elite_trade_log(candidate: str) -> bool:
    """Return True when the candidate's intended trades are the elite log."""

    return candidate.startswith("quality_entry") or candidate.startswith("setup_b_quality_short")


def trade_log_path(summary_report: str, candidate: str) -> Path:
    """Return the intended trade-log path for a candidate row."""

    suffix = "_elite_trades.csv" if uses_elite_trade_log(candidate) else "_baseline_trades.csv"
    return Path(summary_report.replace("_summary.md", suffix))


def add_entry_time(trades: pd.DataFrame) -> pd.DataFrame:
    """Return trades sorted by entry time with numeric R results."""

    if trades.empty or "entry_time" not in trades.columns or "r_result" not in trades.columns:
        return pd.DataFrame()
    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True, errors="coerce")
    result["r_result"] = pd.to_numeric(result["r_result"], errors="coerce")
    result = result.dropna(subset=["entry_time", "r_result"]).sort_values("entry_time")
    return result.reset_index(drop=True)


def finite_profit_factor(value: Any) -> float:
    """Convert metric profit factor to a finite report number."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def score_slice(label: str, trades: pd.DataFrame) -> dict[str, Any]:
    """Score one chronological trade slice."""

    metrics = calculate_metrics(trades)
    return {
        f"{label}_trades": int(metrics["trades"]),
        f"{label}_win_rate": float(metrics["win_rate"]),
        f"{label}_expectancy_r": float(metrics["expectancy_r"]),
        f"{label}_profit_factor": finite_profit_factor(metrics["profit_factor"]),
        f"{label}_max_drawdown_r": float(metrics["max_drawdown_r"]),
    }


def walk_forward_decision(first: dict[str, Any], second: dict[str, Any]) -> tuple[str, str]:
    """Label whether newer results support the older sample."""

    if first["first_trades"] < 8 or second["second_trades"] < 8:
        return "needs_more_sample", "One half has fewer than 8 trades."
    if first["first_expectancy_r"] > 0 and second["second_expectancy_r"] >= 0.10 and second["second_profit_factor"] >= 1.30:
        return "holding_up", "Newer half stayed above the research-ready math floor."
    if first["first_expectancy_r"] > 0 and second["second_expectancy_r"] <= 0:
        return "fading", "Older half was positive but newer half was flat or negative."
    if first["first_expectancy_r"] <= 0 and second["second_expectancy_r"] > 0:
        return "improving_recently", "Newer half improved after a weak older half."
    if second["second_expectancy_r"] > 0:
        return "mixed", "Newer half is positive but below the stronger confidence floor."
    return "weak", "Both halves failed to show enough edge."


def review_candidate(row: pd.Series) -> dict[str, Any]:
    """Build one walk-forward row from a research confidence candidate."""

    candidate = str(row.get("candidate", ""))
    path = trade_log_path(str(row.get("summary_report", "")), candidate)
    trades = add_entry_time(read_csv_or_empty(path))
    if trades.empty:
        return {
            "decision": "missing_trade_log",
            "symbol": str(row.get("symbol", "")),
            "setup": str(row.get("setup", "")),
            "candidate": candidate,
            "trade_log": str(path),
            "full_trades": 0,
            "full_expectancy_r": 0.0,
            "first_trades": 0,
            "first_win_rate": 0.0,
            "first_expectancy_r": 0.0,
            "first_profit_factor": 0.0,
            "first_max_drawdown_r": 0.0,
            "second_trades": 0,
            "second_win_rate": 0.0,
            "second_expectancy_r": 0.0,
            "second_profit_factor": 0.0,
            "second_max_drawdown_r": 0.0,
            "expectancy_delta_second_vs_first": 0.0,
            "reason": "Trade log was missing or empty.",
        }

    midpoint = len(trades) // 2
    first_trades = trades.iloc[:midpoint].copy()
    second_trades = trades.iloc[midpoint:].copy()
    first = score_slice("first", first_trades)
    second = score_slice("second", second_trades)
    decision, reason = walk_forward_decision(first, second)
    return {
        "decision": decision,
        "symbol": str(row.get("symbol", "")),
        "setup": str(row.get("setup", "")),
        "candidate": candidate,
        "research_status": str(row.get("research_status", "")),
        "full_trades": int(len(trades)),
        "full_expectancy_r": float(pd.to_numeric(row.get("expectancy_r", 0), errors="coerce")),
        **first,
        **second,
        "expectancy_delta_second_vs_first": round(
            float(second["second_expectancy_r"]) - float(first["first_expectancy_r"]), 4
        ),
        "trade_log": str(path),
        "reason": reason,
    }


def build_walk_forward_review(research_dir: Path, limit: int) -> pd.DataFrame:
    """Build walk-forward rows from research confidence candidates."""

    confidence = read_csv_or_empty(research_dir / "research_confidence.csv")
    if confidence.empty:
        return pd.DataFrame()

    candidates = confidence[confidence["research_status"].isin(REVIEW_STATUSES)].head(limit)
    rows = [review_candidate(row) for _, row in candidates.iterrows()]
    if not rows:
        return pd.DataFrame()

    order = {
        "holding_up": 0,
        "improving_recently": 1,
        "mixed": 2,
        "needs_more_sample": 3,
        "fading": 4,
        "weak": 5,
        "missing_trade_log": 6,
    }
    result = pd.DataFrame(rows)
    result["_order"] = result["decision"].map(order).fillna(9)
    result = result.sort_values(
        ["_order", "second_expectancy_r", "full_trades"],
        ascending=[True, False, False],
        na_position="last",
    )
    return result.drop(columns=["_order"]).reset_index(drop=True)


def write_report(path: Path, review: pd.DataFrame, research_dir: Path) -> None:
    """Write the walk-forward Markdown report."""

    if review.empty:
        body = "No research confidence rows were available for walk-forward review."
    else:
        counts = review.groupby("decision").size().reset_index(name="candidates")
        body = f"""## Decision Counts

{markdown_table(counts)}

## Walk-Forward Rows

{markdown_table(review)}
"""

    path.write_text(
        f"""# Walk-Forward Research Review

This report splits each candidate's trade log into older and newer halves. The
goal is to see whether the setup is still working in the newer half instead of
only looking good over the full sample.

Important: this is research/backtesting only. It does not change the active
scanner, paper log, alerts, broker settings, or live execution.

```text
Research folder: {research_dir}
```

{body}
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    review = build_walk_forward_review(args.research_dir, args.limit)
    csv_path = args.output_dir / "walk_forward_review.csv"
    md_path = args.output_dir / "walk_forward_review.md"
    review.to_csv(csv_path, index=False)
    write_report(md_path, review, args.research_dir)
    print(f"Saved walk-forward CSV: {csv_path}")
    print(f"Saved walk-forward report: {md_path}")


if __name__ == "__main__":
    main()
