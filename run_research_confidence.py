"""Score broad backtest results for research readiness.

This report helps answer: which symbols/setups deserve more attention? It is
not a trading approval system. Active paper candidates still come from the
approved playbook and forward paper-validation workflow.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


SOURCE_FILES = [
    ("Setup A Long", "best_plus_market_watchlist_backtest_summary.csv"),
    ("Setup B Short", "setup_b_watchlist_backtest_summary.csv"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score Project Gwala research confidence.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs/universe_expansion"))
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def metric(value: object) -> float:
    """Convert CSV metric values to finite floats."""

    if str(value).lower() == "inf":
        return 999.0
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0.0
    return float(number)


def readiness_status(trades: int, expectancy: float, profit_factor: float) -> str:
    """Classify one symbol/setup candidate."""

    if trades >= 20 and expectancy >= 0.10 and profit_factor >= 1.30:
        return "research_ready"
    if trades >= 10 and expectancy > 0 and profit_factor >= 1.05:
        return "promising"
    if expectancy > 0:
        return "watch_more"
    return "reject"


def readiness_score(trades: int, expectancy: float, profit_factor: float, win_rate: float) -> int:
    """Return a simple 0-100 research score."""

    sample_score = min(trades / 30, 1.0) * 35
    expectancy_score = max(min(expectancy / 0.25, 1.0), 0.0) * 30
    profit_score = max(min((profit_factor - 1.0) / 1.0, 1.0), 0.0) * 20
    win_score = max(min((win_rate - 0.45) / 0.20, 1.0), 0.0) * 15
    return int(round(sample_score + expectancy_score + profit_score + win_score))


def use_baseline_metrics(variant: str) -> bool:
    """Return True when the variant's headline result is the baseline log."""

    return variant in {"current", "market_confirmed", "setup_b_short"}


def row_metric(row: pd.Series, variant: str, name: str) -> float:
    """Read the correct baseline or elite metric for a candidate row."""

    prefix = "baseline" if use_baseline_metrics(variant) else "elite"
    return metric(row.get(f"{prefix}_{name}", row.get(f"baseline_{name}", 0)))


def build_rows(output_dir: Path) -> pd.DataFrame:
    """Combine Setup A and Setup B summary CSVs into one readiness table."""

    rows = []
    for setup_family, filename in SOURCE_FILES:
        frame = read_csv_or_empty(output_dir / filename)
        if frame.empty:
            continue
        for _, row in frame.iterrows():
            variant = str(row.get("variant", ""))
            trades = int(row_metric(row, variant, "trades"))
            if trades <= 0:
                continue
            win_rate = row_metric(row, variant, "win_rate")
            expectancy = row_metric(row, variant, "expectancy_r")
            profit_factor = row_metric(row, variant, "profit_factor")
            status = readiness_status(trades, expectancy, profit_factor)
            rows.append(
                {
                    "symbol": str(row.get("symbol", "")),
                    "setup": setup_family,
                    "candidate": f"{variant} + {row.get('exit_profile', '')}",
                    "trades": trades,
                    "win_rate_pct": round(win_rate * 100, 2),
                    "expectancy_r": round(expectancy, 4),
                    "profit_factor": round(profit_factor, 4),
                    "readiness_score": readiness_score(trades, expectancy, profit_factor, win_rate),
                    "research_status": status,
                    "summary_report": str(row.get("summary_report", "")),
                }
            )

    if not rows:
        return pd.DataFrame()
    status_order = {"research_ready": 0, "promising": 1, "watch_more": 2, "reject": 3}
    result = pd.DataFrame(rows)
    result["_status_order"] = result["research_status"].map(status_order).fillna(9)
    result = result.sort_values(
        ["_status_order", "readiness_score", "expectancy_r", "trades"],
        ascending=[True, False, False, False],
    )
    return result.drop(columns=["_status_order"]).reset_index(drop=True)


def write_report(path: Path, rows: pd.DataFrame, output_dir: Path) -> None:
    """Write the Markdown readiness report."""

    if rows.empty:
        body = "No research backtest summary rows were found yet."
        top = pd.DataFrame()
    else:
        top = rows.head(15)
        status_counts = rows.groupby("research_status").size().reset_index(name="candidates")
        body = f"""## Status Counts

{markdown_table(status_counts)}

## Top Research Candidates

{markdown_table(top)}
"""

    path.write_text(
        f"""# Research Confidence

This report scores broad backtest candidates so we can speed up research
confidence without changing the approved paper-trading playbook.

Important: `research_ready` means worth deeper review and forward paper
validation. It does not mean real-money ready.

{body}

## How To Use This

```text
1. Promote nothing directly to live trading.
2. Review research_ready and promising rows first.
3. Add only the strongest rows to the watch playbook.
4. Require forward paper trades before increasing trust.
```

## Source Folder

```text
{output_dir}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_rows(args.output_dir)
    csv_path = args.output_dir / "research_confidence.csv"
    md_path = args.output_dir / "research_confidence.md"
    rows.to_csv(csv_path, index=False)
    write_report(md_path, rows, args.output_dir)
    print(f"Saved research confidence CSV: {csv_path}")
    print(f"Saved research confidence report: {md_path}")


if __name__ == "__main__":
    main()
