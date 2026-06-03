"""Analyze candidate timing and late-day outcome drag.

This is research and paper-validation only. It studies when candidates,
forward observations, and shadow samples appear during the trading day. It
does not change scanner rules, create trades, place orders, or connect to
broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_forward_evidence import read_csv_or_empty
from run_playbook import markdown_table


AGING_COLUMNS = [
    "source",
    "symbol",
    "setup",
    "direction",
    "candidate_time_et",
    "age_bucket",
    "status",
    "r_result",
    "outcome_status",
    "exit_reason",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Project Gwala candidate aging report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--observations-csv",
        type=Path,
        default=Path("logs/forward_observation_results.csv"),
        help="Forward observation outcome CSV.",
    )
    parser.add_argument(
        "--shadow-outcomes-csv",
        type=Path,
        default=Path("logs/shadow_sample_outcomes.csv"),
        help="Shadow sample outcome CSV.",
    )
    parser.add_argument(
        "--scanner-csv",
        type=Path,
        default=Path("logs/daily_paper_signal_scanner.csv"),
        help="Latest scanner CSV.",
    )
    parser.add_argument(
        "--paper-review-csv",
        type=Path,
        default=Path("logs/paper_review_clean_trades.csv"),
        help="Completed local paper review CSV.",
    )
    return parser.parse_args()


def parse_time(value: object) -> pd.Timestamp | None:
    """Parse a local ET candidate timestamp from reports."""

    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    timestamp = pd.Timestamp(str(value))
    return timestamp


def first_text(*values: object) -> object:
    """Return the first non-empty CSV value."""

    for value in values:
        if value is not None and not pd.isna(value) and str(value).strip() != "":
            return value
    return ""


def minutes_after_open(timestamp: pd.Timestamp | None) -> float | None:
    """Return minutes after the 9:30 ET regular-session open."""

    if timestamp is None:
        return None
    open_time = timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
    return (timestamp - open_time).total_seconds() / 60


def age_bucket(timestamp: pd.Timestamp | None) -> str:
    """Bucket a candidate by when it appeared in the regular session."""

    minutes = minutes_after_open(timestamp)
    if minutes is None:
        return "unknown"
    if minutes < 60:
        return "opening_hour"
    if minutes < 180:
        return "midday"
    if minutes < 300:
        return "afternoon"
    return "late_day"


def clean_r(value: object) -> float | None:
    """Return an R value when available."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return float(number)


def scanner_rows(scanner: pd.DataFrame) -> list[dict[str, object]]:
    """Return aging rows for the latest scanner snapshot."""

    if scanner.empty:
        return []
    rows = []
    for _, row in scanner.iterrows():
        timestamp = parse_time(first_text(row.get("latest_signal_et"), row.get("latest_candle_et")))
        rows.append(
            {
                "source": "latest_scanner",
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "candidate_time_et": timestamp.strftime("%Y-%m-%d %H:%M") if timestamp is not None else "",
                "age_bucket": age_bucket(timestamp),
                "status": row.get("scanner_status", ""),
                "r_result": "",
                "outcome_status": "not_outcome",
                "exit_reason": "",
                "notes": row.get("missing_conditions", ""),
            }
        )
    return rows


def observation_rows(observations: pd.DataFrame) -> list[dict[str, object]]:
    """Return aging rows for forward observations with outcomes."""

    rows = []
    for _, row in observations.iterrows():
        timestamp = parse_time(row.get("signal_time_et"))
        result = clean_r(row.get("hypothetical_r"))
        rows.append(
            {
                "source": "forward_observation",
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "candidate_time_et": timestamp.strftime("%Y-%m-%d %H:%M") if timestamp is not None else "",
                "age_bucket": age_bucket(timestamp),
                "status": row.get("signal_status", ""),
                "r_result": "" if result is None else round(result, 4),
                "outcome_status": row.get("evaluation_status", ""),
                "exit_reason": row.get("hypothetical_exit_reason", ""),
                "notes": row.get("evaluation_note", ""),
            }
        )
    return rows


def shadow_rows(shadow: pd.DataFrame) -> list[dict[str, object]]:
    """Return aging rows for shadow sample outcomes."""

    rows = []
    for _, row in shadow.iterrows():
        timestamp = parse_time(row.get("entry_time_et"))
        result = clean_r(row.get("hypothetical_r"))
        rows.append(
            {
                "source": "shadow_sample",
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "candidate_time_et": timestamp.strftime("%Y-%m-%d %H:%M") if timestamp is not None else "",
                "age_bucket": age_bucket(timestamp),
                "status": row.get("shadow_status", ""),
                "r_result": "" if result is None else round(result, 4),
                "outcome_status": row.get("evaluation_status", ""),
                "exit_reason": row.get("hypothetical_exit_reason", ""),
                "notes": row.get("missing_conditions", ""),
            }
        )
    return rows


def paper_rows(paper: pd.DataFrame) -> list[dict[str, object]]:
    """Return aging rows for official completed paper trades."""

    rows = []
    for _, row in paper.iterrows():
        timestamp = parse_time(row.get("entry_time_et"))
        result = clean_r(row.get("review_r"))
        rows.append(
            {
                "source": "official_paper",
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "candidate_time_et": timestamp.strftime("%Y-%m-%d %H:%M") if timestamp is not None else "",
                "age_bucket": age_bucket(timestamp),
                "status": row.get("signal_status", ""),
                "r_result": "" if result is None else round(result, 4),
                "outcome_status": "completed",
                "exit_reason": row.get("exit_reason", ""),
                "notes": row.get("notes", ""),
            }
        )
    return rows


def build_aging(
    scanner: pd.DataFrame,
    observations: pd.DataFrame,
    shadow: pd.DataFrame,
    paper: pd.DataFrame,
) -> pd.DataFrame:
    """Build one combined aging table."""

    rows = [
        *scanner_rows(scanner),
        *observation_rows(observations),
        *shadow_rows(shadow),
        *paper_rows(paper),
    ]
    return pd.DataFrame(rows, columns=AGING_COLUMNS)


def outcome_rows(aging: pd.DataFrame) -> pd.DataFrame:
    """Return rows with an R outcome."""

    if aging.empty:
        return pd.DataFrame(columns=AGING_COLUMNS)
    result = aging.copy()
    result["r_result"] = pd.to_numeric(result["r_result"], errors="coerce")
    return result[result["r_result"].notna()].copy()


def bucket_summary(aging: pd.DataFrame) -> pd.DataFrame:
    """Summarize candidate count and R by time bucket."""

    if aging.empty:
        return pd.DataFrame()
    outcomes = outcome_rows(aging)
    rows = []
    for bucket, group in aging.groupby("age_bucket", dropna=False):
        bucket_outcomes = outcomes[outcomes["age_bucket"] == bucket]
        r = bucket_outcomes["r_result"] if not bucket_outcomes.empty else pd.Series(dtype=float)
        rows.append(
            {
                "age_bucket": bucket,
                "candidates": len(group),
                "outcomes": len(bucket_outcomes),
                "win_rate": round(float((r > 0).mean()), 4) if len(r) else "",
                "avg_r": round(float(r.mean()), 4) if len(r) else "",
                "total_r": round(float(r.sum()), 4) if len(r) else "",
                "guidance": guidance_for_bucket(bucket, r),
            }
        )
    order = {"opening_hour": 1, "midday": 2, "afternoon": 3, "late_day": 4, "unknown": 5}
    return pd.DataFrame(rows).sort_values("age_bucket", key=lambda column: column.map(order).fillna(99))


def guidance_for_bucket(bucket: str, r: pd.Series) -> str:
    """Return a plain-English caution for a time bucket."""

    if len(r) == 0:
        return "No outcome sample yet."
    average = float(r.mean())
    if bucket == "late_day" and average < 0:
        return "Caution: late-day evidence is negative. Do not loosen rules for this bucket yet."
    if average < 0:
        return "Caution: current evidence is negative."
    return "Evidence is constructive, but sample size still matters."


def setup_summary(aging: pd.DataFrame) -> pd.DataFrame:
    """Summarize outcomes by setup and time bucket."""

    outcomes = outcome_rows(aging)
    if outcomes.empty:
        return pd.DataFrame()
    rows = []
    for values, group in outcomes.groupby(["symbol", "setup", "direction", "age_bucket"], dropna=False):
        r = group["r_result"]
        rows.append(
            {
                "symbol": values[0],
                "setup": values[1],
                "direction": values[2],
                "age_bucket": values[3],
                "outcomes": len(group),
                "win_rate": round(float((r > 0).mean()), 4),
                "avg_r": round(float(r.mean()), 4),
                "total_r": round(float(r.sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values(["avg_r", "outcomes"], ascending=[True, False])


def late_day_rows(aging: pd.DataFrame) -> pd.DataFrame:
    """Return late-day rows that deserve operator attention."""

    if aging.empty:
        return pd.DataFrame()
    result = aging[aging["age_bucket"] == "late_day"].copy()
    if result.empty:
        return result
    result["_r"] = pd.to_numeric(result["r_result"], errors="coerce")
    return result.sort_values(["_r", "source"], ascending=[True, True]).drop(columns=["_r"])


def verdict(aging: pd.DataFrame) -> str:
    """Return the report verdict."""

    outcomes = outcome_rows(aging)
    if outcomes.empty:
        return "No aged outcomes yet. Start collecting forward evidence."
    late = outcomes[outcomes["age_bucket"] == "late_day"]
    if not late.empty and float(late["r_result"].mean()) < 0:
        return "Late-day candidates are negative so far. Treat late signals as caution-only until more evidence improves."
    if len(outcomes) < 30:
        return "Aging evidence is useful but still early. Keep collecting before changing rules."
    return "Aging evidence has enough rows for a deeper rule review."


def write_report(path: Path, aging: pd.DataFrame, csv_path: Path) -> None:
    """Write the candidate aging Markdown report."""

    path.write_text(
        f"""# Candidate Aging Review

This report checks whether candidates appear early enough to have useful room
to work, or whether late-day entries are dragging outcomes.

Important: this is research and paper-validation only. It does not change
scanner rules, create paper trades, place orders, or connect to broker
execution.

## Verdict

```text
{verdict(aging)}
```

## Time Bucket Summary

{markdown_table(bucket_summary(aging))}

## Outcome By Setup And Age

{markdown_table(setup_summary(aging))}

## Late-Day Candidates

{markdown_table(late_day_rows(aging))}

## Recent Aging Rows

{markdown_table(aging.tail(30) if not aging.empty else aging)}

## Bucket Definitions

```text
opening_hour = 09:30 to 10:29 ET
midday = 10:30 to 12:29 ET
afternoon = 12:30 to 14:29 ET
late_day = 14:30 ET or later
```

## Files

```text
{csv_path}
{path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    aging = build_aging(
        scanner=read_csv_or_empty(args.scanner_csv),
        observations=read_csv_or_empty(args.observations_csv),
        shadow=read_csv_or_empty(args.shadow_outcomes_csv),
        paper=read_csv_or_empty(args.paper_review_csv),
    )
    csv_path = args.output_dir / "candidate_aging.csv"
    report_path = args.output_dir / "candidate_aging.md"
    aging.to_csv(csv_path, index=False)
    write_report(report_path, aging, csv_path)

    outcomes = outcome_rows(aging)
    print(f"Candidate aging rows: {len(aging)}")
    print(f"Aged outcome rows: {len(outcomes)}")
    print(f"Verdict: {verdict(aging)}")
    print(f"Saved candidate aging CSV: {csv_path}")
    print(f"Saved candidate aging report: {report_path}")


if __name__ == "__main__":
    main()
