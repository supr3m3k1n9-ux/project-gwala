"""Compare strategy variants against matching controls.

This report answers a narrow research question: did a filter improve the same
symbol/setup, or did it only reduce trades and make the headline look cleaner?
It is backtesting research only and does not alter the active playbook.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from run_playbook import markdown_table
from run_research_confidence import metric, use_baseline_metrics


SOURCE_FILES = [
    ("Setup A Long", "best_plus_market_watchlist_backtest_summary.csv"),
    ("Setup B Short", "setup_b_watchlist_backtest_summary.csv"),
]

COMPARISONS = [
    ("Setup A Long", "current", "quality_entry", "quality filter vs baseline"),
    ("Setup A Long", "current", "market_confirmed", "market filter vs baseline"),
    (
        "Setup A Long",
        "market_confirmed",
        "quality_entry_market_confirmed",
        "quality filter inside market-confirmed trades",
    ),
    ("Setup B Short", "setup_b_short", "setup_b_quality_short", "short quality filter vs short baseline"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build controlled variant comparison reports.")
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=Path("logs/deeper_research"),
        help="Folder containing watchlist backtest summary CSVs.",
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


def candidate_metrics(row: pd.Series) -> dict[str, Any]:
    """Return the intended metric set for a baseline or quality variant."""

    variant = str(row.get("variant", ""))
    prefix = "baseline" if use_baseline_metrics(variant) else "elite"
    return {
        "trades": int(metric(row.get(f"{prefix}_trades", 0))),
        "win_rate": metric(row.get(f"{prefix}_win_rate", 0)),
        "expectancy_r": metric(row.get(f"{prefix}_expectancy_r", 0)),
        "profit_factor": metric(row.get(f"{prefix}_profit_factor", 0)),
        "summary_report": str(row.get("summary_report", "")),
    }


def load_candidates(research_dir: Path) -> pd.DataFrame:
    """Load Setup A and Setup B candidate rows with their intended metrics."""

    rows = []
    for setup, filename in SOURCE_FILES:
        frame = read_csv_or_empty(research_dir / filename)
        if frame.empty:
            continue
        for _, row in frame.iterrows():
            variant = str(row.get("variant", ""))
            exit_profile = str(row.get("exit_profile", ""))
            metrics = candidate_metrics(row)
            rows.append(
                {
                    "symbol": str(row.get("symbol", "")),
                    "setup": setup,
                    "variant": variant,
                    "exit_profile": exit_profile,
                    "candidate": f"{variant} + {exit_profile}",
                    **metrics,
                }
            )
    return pd.DataFrame(rows)


def comparison_decision(
    control_trades: int,
    variant_trades: int,
    expectancy_delta: float,
    profit_factor_delta: float,
    retention: float,
    variant_expectancy: float,
    variant_profit_factor: float,
) -> tuple[str, str]:
    """Label whether the tested variant earned its complexity."""

    if control_trades < 10 or variant_trades < 10:
        return "inconclusive", "One side has fewer than 10 trades."
    if retention < 0.25:
        return "too_selective", "The filter kept fewer than 25% of control trades."
    if expectancy_delta >= 0.05 and profit_factor_delta >= 0 and variant_expectancy >= 0.10:
        return "improves", "Variant improved expectancy without hurting profit factor."
    if expectancy_delta <= -0.05 or variant_profit_factor < 1.0:
        return "weakens", "Variant reduced expectancy or failed the profit-factor floor."
    if expectancy_delta > 0:
        return "mixed_small_improvement", "Variant improved slightly, but not enough to treat as proven."
    return "neutral", "Variant did not materially improve the control."


def build_controlled_review(research_dir: Path) -> pd.DataFrame:
    """Build comparison rows for all symbols with matching controls."""

    candidates = load_candidates(research_dir)
    if candidates.empty:
        return pd.DataFrame()

    rows = []
    for setup, control_variant, tested_variant, comparison in COMPARISONS:
        subset = candidates[candidates["setup"] == setup]
        for symbol, group in subset.groupby("symbol", sort=True):
            controls = group[group["variant"] == control_variant]
            tested = group[group["variant"] == tested_variant]
            if controls.empty or tested.empty:
                continue

            control = controls.iloc[0]
            variant = tested.iloc[0]
            control_trades = int(control["trades"])
            variant_trades = int(variant["trades"])
            retention = 0.0 if control_trades == 0 else round(variant_trades / control_trades, 4)
            expectancy_delta = round(float(variant["expectancy_r"]) - float(control["expectancy_r"]), 4)
            win_rate_delta = round(float(variant["win_rate"]) - float(control["win_rate"]), 4)
            profit_factor_delta = round(float(variant["profit_factor"]) - float(control["profit_factor"]), 4)
            decision, reason = comparison_decision(
                control_trades,
                variant_trades,
                expectancy_delta,
                profit_factor_delta,
                retention,
                float(variant["expectancy_r"]),
                float(variant["profit_factor"]),
            )
            rows.append(
                {
                    "decision": decision,
                    "symbol": symbol,
                    "setup": setup,
                    "comparison": comparison,
                    "control": str(control["candidate"]),
                    "variant": str(variant["candidate"]),
                    "control_trades": control_trades,
                    "variant_trades": variant_trades,
                    "trade_retention": retention,
                    "control_expectancy_r": round(float(control["expectancy_r"]), 4),
                    "variant_expectancy_r": round(float(variant["expectancy_r"]), 4),
                    "expectancy_delta": expectancy_delta,
                    "control_profit_factor": round(float(control["profit_factor"]), 4),
                    "variant_profit_factor": round(float(variant["profit_factor"]), 4),
                    "profit_factor_delta": profit_factor_delta,
                    "win_rate_delta": win_rate_delta,
                    "reason": reason,
                }
            )

    if not rows:
        return pd.DataFrame()
    order = {
        "improves": 0,
        "mixed_small_improvement": 1,
        "neutral": 2,
        "too_selective": 3,
        "inconclusive": 4,
        "weakens": 5,
    }
    result = pd.DataFrame(rows)
    result["_order"] = result["decision"].map(order).fillna(9)
    result = result.sort_values(
        ["_order", "expectancy_delta", "variant_expectancy_r", "variant_trades"],
        ascending=[True, False, False, False],
    )
    return result.drop(columns=["_order"]).reset_index(drop=True)


def write_report(path: Path, review: pd.DataFrame, research_dir: Path) -> None:
    """Write the controlled variant Markdown report."""

    if review.empty:
        body = "No matching controlled variant rows were found yet."
    else:
        counts = review.groupby("decision").size().reset_index(name="comparisons")
        body = f"""## Decision Counts

{markdown_table(counts)}

## Controlled Comparisons

{markdown_table(review)}
"""

    path.write_text(
        f"""# Controlled Variant Review

This report compares each variant against a matching control from the same
symbol, setup, exit profile, and data folder.

Important: this is still research/backtesting only. It does not change scanner
rules, paper-watch candidates, alerts, broker settings, or live execution.

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

    review = build_controlled_review(args.research_dir)
    csv_path = args.output_dir / "controlled_variant_review.csv"
    md_path = args.output_dir / "controlled_variant_review.md"
    review.to_csv(csv_path, index=False)
    write_report(md_path, review, args.research_dir)
    print(f"Saved controlled variant CSV: {csv_path}")
    print(f"Saved controlled variant report: {md_path}")


if __name__ == "__main__":
    main()
