"""Review research candidates before promoting them to paper watch.

This is a research gate. It does not change the active playbook, create alerts,
place orders, or connect to broker execution. The goal is to separate setups
with repeatable evidence from noisy backtest rows.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table


PROMOTION_STATUSES = {"research_ready", "promising"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Project Gwala promotion review.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where app reports are saved.")
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=Path("logs/universe_expansion"),
        help="Folder containing research_confidence.csv and trade logs.",
    )
    parser.add_argument("--limit", type=int, default=30, help="Maximum research rows to review.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def finite_number(value: Any) -> float:
    """Convert report values to app-safe finite floats."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def uses_elite_trade_log(candidate: str) -> bool:
    """Return True when the candidate's intended trades are the elite log."""

    return candidate.startswith("quality_entry") or candidate.startswith("setup_b_quality_short")


def trade_log_path(summary_report: str, candidate: str) -> Path:
    """Return the intended trade-log path for a summary report."""

    suffix = "_elite_trades.csv" if uses_elite_trade_log(candidate) else "_baseline_trades.csv"
    return Path(summary_report.replace("_summary.md", suffix))


def add_months(trades: pd.DataFrame) -> pd.DataFrame:
    """Add New York calendar-month labels to a trade log."""

    result = trades.copy()
    if result.empty or "entry_time" not in result.columns or "r_result" not in result.columns:
        result["entry_month_et"] = []
        result["r_result"] = []
        return result
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["entry_month_et"] = result["entry_time"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    result["r_result"] = pd.to_numeric(result["r_result"], errors="coerce").fillna(0.0)
    return result


def monthly_stability(trades: pd.DataFrame) -> dict[str, Any]:
    """Summarize whether results appear across multiple months."""

    if trades.empty:
        return {
            "months_tested": 0,
            "positive_months": 0,
            "negative_months": 0,
            "worst_month_r": 0.0,
            "best_month_r": 0.0,
        }

    monthly = trades.groupby("entry_month_et")["r_result"].sum()
    return {
        "months_tested": int(len(monthly)),
        "positive_months": int((monthly > 0).sum()),
        "negative_months": int((monthly < 0).sum()),
        "worst_month_r": round(float(monthly.min()), 4),
        "best_month_r": round(float(monthly.max()), 4),
    }


def largest_win_share(trades: pd.DataFrame) -> float:
    """Return how much total profit came from the single biggest winner."""

    wins = trades.loc[trades["r_result"] > 0, "r_result"]
    if wins.empty:
        return 0.0
    total_wins = float(wins.sum())
    if total_wins <= 0:
        return 0.0
    return round(float(wins.max()) / total_wins, 4)


def exit_mix(trades: pd.DataFrame) -> dict[str, float]:
    """Return simple exit reason rates."""

    if trades.empty or "exit_reason" not in trades.columns:
        return {"stop_loss_rate": 0.0, "target_rate": 0.0, "end_of_day_rate": 0.0}
    exit_reason = trades["exit_reason"].astype(str)
    total = max(len(exit_reason), 1)
    return {
        "stop_loss_rate": round(float(exit_reason.str.contains("stop", case=False, na=False).sum()) / total, 4),
        "target_rate": round(float(exit_reason.str.contains("target", case=False, na=False).sum()) / total, 4),
        "end_of_day_rate": round(float(exit_reason.str.contains("end_of_day", case=False, na=False).sum()) / total, 4),
    }


def promotion_decision(row: dict[str, Any]) -> tuple[str, str]:
    """Choose the review decision for one candidate."""

    if row["trades"] < 20:
        return "needs_more_samples", "Trade sample is still below the 20-trade paper-watch gate."
    if row["expectancy_r"] < 0.10 or row["profit_factor"] < 1.30:
        return "reject_noise", "Backtest math is not strong enough after stability review."
    if row["positive_months"] < 2:
        return "needs_more_stability", "Needs positive evidence across at least two separate months."
    if row["max_drawdown_r"] < -4.0:
        return "needs_risk_review", "Drawdown is too deep for immediate paper-watch promotion."
    if row["largest_win_share"] > 0.55:
        return "needs_outlier_review", "Too much profit came from one winner; inspect for outlier risk."
    return "paper_watch_candidate", "Eligible for manual paper-watch review, not live trading."


def setup_key(candidate: str) -> str:
    """Return the base setup label before quality-only naming differences."""

    return candidate.replace("quality_entry_", "").replace("quality_entry", "current").replace(
        "setup_b_quality_short", "setup_b_short"
    )


def review_candidate(row: pd.Series) -> dict[str, Any]:
    """Build one promotion review row."""

    candidate = str(row.get("candidate", ""))
    path = trade_log_path(str(row.get("summary_report", "")), candidate)
    trades = add_months(read_csv_or_empty(path))
    metrics = calculate_metrics(trades)
    stability = monthly_stability(trades)
    exits = exit_mix(trades)
    review = {
        "symbol": str(row.get("symbol", "")),
        "setup": str(row.get("setup", "")),
        "candidate": candidate,
        "setup_key": setup_key(candidate),
        "research_status": str(row.get("research_status", "")),
        "readiness_score": int(finite_number(row.get("readiness_score", 0))),
        "trades": int(metrics.get("trades", 0)),
        "win_rate_pct": round(float(metrics.get("win_rate", 0)) * 100, 2),
        "expectancy_r": float(metrics.get("expectancy_r", 0)),
        "profit_factor": finite_number(metrics.get("profit_factor", 0)),
        "max_drawdown_r": float(metrics.get("max_drawdown_r", 0)),
        "months_tested": stability["months_tested"],
        "positive_months": stability["positive_months"],
        "negative_months": stability["negative_months"],
        "worst_month_r": stability["worst_month_r"],
        "best_month_r": stability["best_month_r"],
        "largest_win_share": largest_win_share(trades),
        "trade_log": str(path),
        **exits,
    }
    decision, reason = promotion_decision(review)
    review["promotion_decision"] = decision
    review["promotion_reason"] = reason
    return review


def dedupe_review_rows(review: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate labels that point to the same setup idea."""

    if review.empty:
        return review

    rows = []
    for _, group in review.groupby(["symbol", "setup", "setup_key"], sort=False):
        ordered = group.sort_values(["readiness_score", "expectancy_r", "trades"], ascending=[False, False, False])
        best = ordered.iloc[0].to_dict()
        candidates = sorted(str(value) for value in group["candidate"].dropna().unique())
        best["candidate"] = candidates[0] if len(candidates) == 1 else " / ".join(candidates)
        best["alternate_candidates"] = ", ".join(candidates)
        best["duplicate_rows_collapsed"] = int(len(group))
        rows.append(best)

    return pd.DataFrame(rows)


def build_review(research_dir: Path, limit: int) -> pd.DataFrame:
    """Build the promotion review table."""

    confidence = read_csv_or_empty(research_dir / "research_confidence.csv")
    if confidence.empty:
        return pd.DataFrame()

    candidates = confidence[confidence["research_status"].isin(PROMOTION_STATUSES)].head(limit)
    rows = [review_candidate(row) for _, row in candidates.iterrows()]
    if not rows:
        return pd.DataFrame()

    decision_order = {
        "paper_watch_candidate": 0,
        "needs_more_stability": 1,
        "needs_outlier_review": 2,
        "needs_risk_review": 3,
        "needs_more_samples": 4,
        "reject_noise": 5,
    }
    result = dedupe_review_rows(pd.DataFrame(rows))
    result["_decision_order"] = result["promotion_decision"].map(decision_order).fillna(9)
    result = result.sort_values(
        ["_decision_order", "readiness_score", "expectancy_r", "trades"],
        ascending=[True, False, False, False],
    )
    return result.drop(columns=["_decision_order"]).reset_index(drop=True)


def write_report(path: Path, review: pd.DataFrame) -> None:
    """Write the Markdown promotion review."""

    if review.empty:
        body = "No research confidence rows are ready for promotion review yet."
    else:
        counts = review.groupby("promotion_decision").size().reset_index(name="candidates")
        display_columns = [
            "promotion_decision",
            "symbol",
            "setup",
            "candidate",
            "duplicate_rows_collapsed",
            "trades",
            "expectancy_r",
            "profit_factor",
            "max_drawdown_r",
            "positive_months",
            "months_tested",
            "largest_win_share",
            "alternate_candidates",
            "promotion_reason",
        ]
        body = f"""## Decision Counts

{markdown_table(counts)}

## Review Queue

{markdown_table(review[display_columns])}
"""

    path.write_text(
        f"""# Promotion Review

This report is the checkpoint between broad backtesting and active paper watch.

Important: `paper_watch_candidate` means the setup may be reviewed for forward
paper validation. It does not mean real-money ready, and it does not change the
approved scanner/playbook by itself.

{body}

## How To Use This

```text
1. Review paper_watch_candidate rows first.
2. Promote only a small number to the active paper watchlist.
3. Keep needs_more_samples rows in research.
4. Reject or redesign noisy rows before they reach the scanner.
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    review = build_review(args.research_dir, args.limit)
    csv_path = args.output_dir / "promotion_review.csv"
    md_path = args.output_dir / "promotion_review.md"
    review.to_csv(csv_path, index=False)
    write_report(md_path, review)
    print(f"Saved promotion review CSV: {csv_path}")
    print(f"Saved promotion review report: {md_path}")


if __name__ == "__main__":
    main()
