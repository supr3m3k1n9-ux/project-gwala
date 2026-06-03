"""Review manually logged forward paper trades.

This is research and paper workflow only. It reads a CSV that the trader fills
out after paper trades and compares the fresh results against the current
Project Gwala research baselines.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


ALLOWED_BASELINE_R = 0.1965
BLOCKED_BASELINE_R = -0.0023
MINIMUM_CONFIDENCE_TRADES = 30
STRONG_CONFIDENCE_TRADES = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review Project Gwala forward paper trades.")
    parser.add_argument(
        "--paper-csv",
        type=Path,
        default=Path("data/paper_trades.csv"),
        help="Manual paper trade log to review.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def clean_text(value: object) -> str:
    """Return a readable string for grouping and reports."""

    if pd.isna(value) or str(value).strip() == "":
        return "unknown"
    return str(value).strip()


def number_or_none(value: object) -> float | None:
    """Convert a CSV field to a number when possible."""

    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def calculated_r(row: pd.Series) -> float | None:
    """Calculate R from actual entry and exit if outcome_r is blank."""

    existing = number_or_none(row.get("outcome_r"))
    if existing is not None:
        return existing

    entry = number_or_none(row.get("actual_entry"))
    exit_price = number_or_none(row.get("actual_exit"))
    stop = number_or_none(row.get("planned_stop"))
    direction = clean_text(row.get("direction")).lower()
    if entry is None or exit_price is None or stop is None:
        return None

    risk = abs(entry - stop)
    if risk == 0:
        return None

    if direction == "short":
        return round((entry - exit_price) / risk, 4)
    return round((exit_price - entry) / risk, 4)


def load_paper_trades(path: Path) -> pd.DataFrame:
    """Load and normalize the manual paper trade log."""

    if not path.exists():
        raise FileNotFoundError(f"Paper trade log not found: {path}")

    trades = pd.read_csv(path)
    required_columns = [
        "trade_date",
        "symbol",
        "setup",
        "direction",
        "signal_status",
        "actual_entry",
        "actual_exit",
        "planned_stop",
    ]
    missing = [column for column in required_columns if column not in trades.columns]
    if missing:
        raise ValueError(f"Missing required columns in {path}: {', '.join(missing)}")

    trades = trades.copy()
    trades["symbol"] = trades["symbol"].apply(clean_text).str.upper()
    trades["setup"] = trades["setup"].apply(clean_text)
    trades["direction"] = trades["direction"].apply(clean_text).str.lower()
    trades["signal_status"] = trades["signal_status"].apply(clean_text).str.lower()
    trades["vehicle"] = trades.get("vehicle", "unknown").apply(clean_text).str.lower()
    trades["risk_tier"] = trades.get("risk_tier", "unknown").apply(clean_text).str.lower()
    trades["followed_plan"] = trades.get("followed_plan", "unknown").apply(clean_text).str.lower()
    trades["exit_reason"] = trades.get("exit_reason", "unknown").apply(clean_text)
    trades["review_r"] = trades.apply(calculated_r, axis=1)
    return trades.dropna(subset=["review_r"]).copy()


def summarize(trades: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Summarize paper-trade R results by one or more columns."""

    rows = []
    for group_value, group in trades.groupby(group_columns, dropna=False):
        if not isinstance(group_value, tuple):
            group_value = (group_value,)

        r = group["review_r"].astype(float)
        row = {column: value for column, value in zip(group_columns, group_value)}
        row.update(
            {
                "trades": len(group),
                "win_rate": round(float((r > 0).mean()), 4),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
                "best_r": round(float(r.max()), 4),
                "worst_r": round(float(r.min()), 4),
            }
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["avg_r", "total_r"], ascending=[False, False])


def confidence_label(allowed_count: int) -> str:
    """Translate sample size into a beginner-readable confidence level."""

    if allowed_count >= STRONG_CONFIDENCE_TRADES:
        return "stronger paper sample"
    if allowed_count >= MINIMUM_CONFIDENCE_TRADES:
        return "starter paper sample"
    return "too early"


def build_interpretation(trades: pd.DataFrame, by_status: pd.DataFrame) -> str:
    """Create the plain-English read of the paper results."""

    allowed = trades[trades["signal_status"] == "allowed"]
    blocked = trades[trades["signal_status"] == "blocked"]
    confidence = confidence_label(len(allowed))
    plan_breaks = trades[trades["followed_plan"] != "yes"]

    if allowed.empty:
        allowed_text = (
            "No allowed paper trades have been logged yet, so there is no live-style "
            "comparison against the fresh-data allowed baseline."
        )
    else:
        allowed_avg = float(allowed["review_r"].mean())
        allowed_delta = allowed_avg - ALLOWED_BASELINE_R
        allowed_text = (
            f"The allowed group is averaging `{allowed_avg:.4f}R` versus the current fresh-data\n"
            f"allowed baseline of `{ALLOWED_BASELINE_R:.4f}R`. The difference is\n"
            f"`{allowed_delta:.4f}R` per trade."
        )

    if blocked.empty:
        blocked_text = (
            "No blocked/watch-only signals have been logged yet. Keep recording them "
            "so weakness_v1 can be challenged with fresh evidence."
        )
    else:
        blocked_avg = float(blocked["review_r"].mean())
        blocked_text = (
            f"Blocked/watch-only signals logged: `{len(blocked)}`. Their paper average is\n"
            f"`{blocked_avg:.4f}R` versus the fresh-data blocked baseline of\n"
            f"`{BLOCKED_BASELINE_R:.4f}R`."
        )

    return f"""## Plain-English Read

Allowed paper trades: `{len(allowed)}`.
Current confidence level: `{confidence}`.

{allowed_text}

{blocked_text}

Plan breaks logged: `{len(plan_breaks)}`.

## What This Means

```text
If allowed paper trades stay near or above the +0.1965R fresh-data baseline
after 30 to 60 trades, the setup is behaving close to the backtest.

If allowed paper trades fall far below baseline, study execution quality,
market regime, symbol selection, and whether the entries are being taken late.

If blocked/watch-only signals start outperforming allowed signals, weakness_v1
may be too strict for the current regime and should be retested.
```

## Status Snapshot

{markdown_table(by_status)}
"""


def write_report(path: Path, trades: pd.DataFrame, paper_csv: Path | None = None, output_dir: Path | None = None) -> None:
    """Write the paper review Markdown report."""

    by_status = summarize(trades, ["signal_status"])
    by_symbol = summarize(trades, ["symbol", "signal_status"])
    by_setup = summarize(trades, ["setup", "signal_status"])
    by_vehicle = summarize(trades, ["vehicle", "risk_tier"])
    by_plan = summarize(trades, ["followed_plan"])
    by_exit = summarize(trades, ["exit_reason"])
    paper_csv = paper_csv or Path("data/paper_trades.csv")
    output_dir = output_dir or Path("logs")

    path.write_text(
        f"""# Forward Paper Review

This report reviews manually logged paper trades for Project Gwala.

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

{build_interpretation(trades, by_status)}

## By Symbol

{markdown_table(by_symbol)}

## By Setup

{markdown_table(by_setup)}

## By Vehicle And Risk Tier

{markdown_table(by_vehicle)}

## By Plan Discipline

{markdown_table(by_plan)}

## By Exit Reason

{markdown_table(by_exit)}

## Next Review Gate

```text
First useful checkpoint: 30 allowed paper trades.
Stronger checkpoint: 60 allowed paper trades.
Keep blocked signals as watch-only notes so the filter can be challenged with
fresh evidence.
```

## Files

```text
{paper_csv}
{output_dir / "paper_review_summary.md"}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = load_paper_trades(args.paper_csv)
    output_csv = args.output_dir / "paper_review_clean_trades.csv"
    output_report = args.output_dir / "paper_review_summary.md"
    trades.to_csv(output_csv, index=False)
    write_report(output_report, trades, args.paper_csv, args.output_dir)

    print(f"Saved clean paper trade review CSV: {output_csv}")
    print(f"Saved paper review report: {output_report}")


if __name__ == "__main__":
    main()
