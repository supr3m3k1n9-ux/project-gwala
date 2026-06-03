"""Explain why the paper workflow is not producing trades.

This report is designed for the moment when Gwala is too quiet. It shows which
scanner rules are blocking setups, which setups are closest, and which single
relaxations would create more forward-paper review candidates.

It is research and paper-validation only. It does not change scanner rules,
size positions, create paper trades, place orders, or connect to broker
execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_near_miss_analytics import missing_conditions
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build no-trade/blocker analysis for Project Gwala.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and is parseable."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def number_value(value: object, default: float = 0.0) -> float:
    """Return a clean float from scanner CSV values."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def text_value(value: object) -> str:
    """Return a clean report string."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def latest_scanner_rows(scanner: pd.DataFrame) -> pd.DataFrame:
    """Return rows from the latest scanner session."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return pd.DataFrame()
    latest = sorted(str(value) for value in scanner["scan_date"].dropna().unique())[-1]
    return scanner[scanner["scan_date"].astype(str) == latest].copy()


def add_blocker_fields(rows: pd.DataFrame) -> pd.DataFrame:
    """Add missing-condition counts and check scores."""

    if rows.empty:
        return rows
    result = rows.copy()
    result["missing_condition_list"] = result.apply(missing_conditions, axis=1)
    result["missing_count"] = result["missing_condition_list"].apply(len)
    result["passed_condition_count"] = pd.to_numeric(result.get("passed_condition_count", 0), errors="coerce").fillna(0)
    result["condition_count"] = pd.to_numeric(result.get("condition_count", 0), errors="coerce").fillna(0)
    result["check_score"] = result.apply(
        lambda row: round(float(row["passed_condition_count"]) / float(row["condition_count"]), 4)
        if float(row["condition_count"] or 0) > 0
        else 0.0,
        axis=1,
    )
    result["relative_volume"] = pd.to_numeric(result.get("relative_volume", 0), errors="coerce").fillna(0)
    result["room_to_target_r"] = pd.to_numeric(result.get("room_to_target_r", 0), errors="coerce").fillna(0)
    result["quality_score"] = pd.to_numeric(result.get("quality_score", 0), errors="coerce").fillna(0)
    return result


def status_counts(rows: pd.DataFrame) -> pd.DataFrame:
    """Count scanner statuses in the latest snapshot."""

    if rows.empty or "scanner_status" not in rows.columns:
        return pd.DataFrame()
    return (
        rows.groupby("scanner_status")
        .size()
        .reset_index(name="rows")
        .sort_values(["rows", "scanner_status"], ascending=[False, True])
    )


def blocker_counts(rows: pd.DataFrame) -> pd.DataFrame:
    """Count individual missing conditions."""

    if rows.empty:
        return pd.DataFrame()
    exploded = rows[["symbol", "setup", "direction", "missing_condition_list"]].explode("missing_condition_list")
    exploded = exploded[exploded["missing_condition_list"].astype(str).str.strip() != ""]
    if exploded.empty:
        return pd.DataFrame()
    return (
        exploded.groupby("missing_condition_list")
        .size()
        .reset_index(name="blocked_rows")
        .rename(columns={"missing_condition_list": "blocker"})
        .sort_values(["blocked_rows", "blocker"], ascending=[False, True])
    )


def single_relaxation_impact(rows: pd.DataFrame) -> pd.DataFrame:
    """Show which one-rule relaxation would create a scanner pass."""

    if rows.empty:
        return pd.DataFrame()
    one_missing = rows[(rows["scanner_status"] == "not_ready") & (rows["missing_count"] == 1)].copy()
    if one_missing.empty:
        return pd.DataFrame()
    one_missing["relaxing_this_rule"] = one_missing["missing_condition_list"].apply(lambda values: values[0])
    return (
        one_missing.groupby("relaxing_this_rule")
        .agg(
            possible_new_candidates=("symbol", "count"),
            symbols=("symbol", lambda values: ", ".join(sorted(set(str(value) for value in values)))),
            best_check_score=("check_score", "max"),
            best_quality_score=("quality_score", "max"),
        )
        .reset_index()
        .sort_values(["possible_new_candidates", "best_check_score"], ascending=[False, False])
    )


def closest_setups(rows: pd.DataFrame) -> pd.DataFrame:
    """Rank close setups that are not currently allowed."""

    if rows.empty:
        return pd.DataFrame()
    candidates = rows[rows["scanner_status"] != "allowed"].copy()
    if candidates.empty:
        return pd.DataFrame()
    candidates["missing_conditions"] = candidates["missing_condition_list"].apply(lambda values: "; ".join(values))
    columns = [
        "symbol",
        "setup",
        "direction",
        "scanner_status",
        "check_score",
        "passed_condition_count",
        "condition_count",
        "missing_count",
        "quality_grade",
        "quality_score",
        "relative_volume",
        "room_to_target_r",
        "missing_conditions",
    ]
    for column in columns:
        if column not in candidates.columns:
            candidates[column] = ""
    return candidates.sort_values(
        ["check_score", "missing_count", "quality_score", "relative_volume"],
        ascending=[False, True, False, False],
    )[columns].head(12)


def responsible_relaxation_lanes(rows: pd.DataFrame) -> pd.DataFrame:
    """Classify near-ready rows by how aggressive relaxation would be."""

    if rows.empty:
        return pd.DataFrame()
    candidates = rows[rows["scanner_status"] != "allowed"].copy()
    if candidates.empty:
        return pd.DataFrame()

    lane_rows = []
    for _, row in candidates.iterrows():
        missing = list(row["missing_condition_list"])
        if row["missing_count"] <= 1 and row["check_score"] >= 0.85:
            lane = "one_rule_from_passing"
            guidance = "Best candidate for research relaxation. Review chart manually before any rule change."
        elif row["missing_count"] <= 2 and row["check_score"] >= 0.75:
            lane = "close_watch"
            guidance = "Worth tracking. Do not loosen both rules without backtest comparison."
        elif row["check_score"] >= 0.55:
            lane = "learning_sample"
            guidance = "Useful for near-miss evidence, not a paper entry."
        else:
            lane = "too_far"
            guidance = "Not close enough. Leave blocked."
        lane_rows.append(
            {
                "lane": lane,
                "symbol": text_value(row.get("symbol")).upper(),
                "setup": text_value(row.get("setup")),
                "direction": text_value(row.get("direction")),
                "check_score": row["check_score"],
                "missing_count": int(row["missing_count"]),
                "quality_score": row["quality_score"],
                "relative_volume": round(float(row["relative_volume"]), 4),
                "room_to_target_r": round(float(row["room_to_target_r"]), 4),
                "missing_conditions": "; ".join(missing),
                "guidance": guidance,
            }
        )
    return pd.DataFrame(lane_rows).sort_values(
        ["lane", "check_score", "quality_score"],
        ascending=[True, False, False],
    )


def verdict(rows: pd.DataFrame, impact: pd.DataFrame) -> str:
    """Return a plain-English no-trade verdict."""

    if rows.empty:
        return "No scanner rows were available. Refresh data before judging trade frequency."
    allowed = int((rows["scanner_status"] == "allowed").sum())
    if allowed:
        return f"{allowed} scanner row(s) are allowed. If no paper trade exists, inspect sizing/session gates next."
    one_rule = int(impact["possible_new_candidates"].sum()) if not impact.empty else 0
    if one_rule:
        return f"No trades are allowed, but {one_rule} row(s) are one rule away from passing. Test relaxations before adding more filters."
    close = int(((rows["scanner_status"] != "allowed") & (rows["check_score"] >= 0.75)).sum())
    if close:
        return f"No trades are allowed, but {close} row(s) are close. The rules may be slightly too tight for sample collection."
    return "No trades are allowed and the latest rows are not especially close. Wait for better conditions or broaden research universe carefully."


def build_analysis(scanner: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    """Build all no-trade analysis tables."""

    latest = add_blocker_fields(latest_scanner_rows(scanner))
    impact = single_relaxation_impact(latest)
    return {
        "latest": latest,
        "status_counts": status_counts(latest),
        "blocker_counts": blocker_counts(latest),
        "single_relaxation_impact": impact,
        "closest_setups": closest_setups(latest),
        "relaxation_lanes": responsible_relaxation_lanes(latest),
        "verdict": verdict(latest, impact),
    }


def write_report(path: Path, analysis: dict[str, pd.DataFrame | str]) -> None:
    """Write the no-trade analysis report."""

    latest = analysis["latest"]
    snapshot = pd.DataFrame(
        [
            {
                "latest_rows": len(latest) if isinstance(latest, pd.DataFrame) else 0,
                "allowed_rows": int((latest["scanner_status"] == "allowed").sum()) if isinstance(latest, pd.DataFrame) and not latest.empty else 0,
                "one_rule_from_passing": int((latest["missing_count"] == 1).sum()) if isinstance(latest, pd.DataFrame) and not latest.empty else 0,
                "close_rows_75pct_plus": int((latest["check_score"] >= 0.75).sum()) if isinstance(latest, pd.DataFrame) and not latest.empty else 0,
            }
        ]
    )

    path.write_text(
        f"""# No-Trade Blocker Analysis

This report explains why Project Gwala is not producing paper candidates and
which filters are most responsible.

Important: this is research and paper-validation only. It does not change
scanner rules, size positions, create paper trades, place broker orders, or
connect to broker execution.

## Verdict

```text
{analysis["verdict"]}
```

## Snapshot

{markdown_table(snapshot)}

## Scanner Status Counts

{markdown_table(analysis["status_counts"])}

## Top Blockers

{markdown_table(analysis["blocker_counts"])}

## Single-Rule Relaxation Impact

These are the rules where relaxing exactly one condition would have created a
passing scanner row in the latest snapshot. This is not permission to trade;
it is a research shortlist for backtest comparison.

{markdown_table(analysis["single_relaxation_impact"])}

## Closest Setups

{markdown_table(analysis["closest_setups"])}

## Responsible Relaxation Lanes

{markdown_table(analysis["relaxation_lanes"])}

## Recommended Use

```text
If the same blocker repeatedly creates one-rule misses, test that relaxation against baseline.
Do not loosen multiple structural trend rules at once.
Prefer more sample collection over instant real execution.
The goal is faster profitability, but only through measured rule changes.
```

## Files

```text
logs/no_trade_blocker_analysis.md
logs/no_trade_blocker_analysis.csv
logs/daily_paper_signal_scanner.csv
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    analysis = build_analysis(scanner)
    csv_path = args.output_dir / "no_trade_blocker_analysis.csv"
    report_path = args.output_dir / "no_trade_blocker_analysis.md"
    latest = analysis["latest"]
    if isinstance(latest, pd.DataFrame):
        csv_latest = latest.copy()
        if "missing_condition_list" in csv_latest.columns:
            csv_latest["missing_condition_list"] = csv_latest["missing_condition_list"].apply(lambda values: "; ".join(values))
        csv_latest.to_csv(csv_path, index=False)
    else:
        pd.DataFrame().to_csv(csv_path, index=False)
    write_report(report_path, analysis)
    print(f"Saved no-trade blocker CSV: {csv_path}")
    print(f"Saved no-trade blocker report: {report_path}")


if __name__ == "__main__":
    main()
