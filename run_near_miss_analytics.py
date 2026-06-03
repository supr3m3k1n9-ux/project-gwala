"""Track why approved setups were close but not ready during paper sessions.

This is research and paper workflow only. It records scanner condition gaps
during fresh open-market scans. It does not create signals, import paper
trades, size positions, place orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table


NEAR_MISS_COLUMNS = [
    "observed_at_et",
    "scan_date",
    "latest_candle_et",
    "symbol",
    "setup",
    "direction",
    "missing_condition",
    "passed_condition_count",
    "condition_count",
    "quality_score",
    "quality_grade",
    "relative_volume",
    "room_to_target_r",
]
NEAR_MISS_KEY_COLUMNS = [
    "scan_date",
    "latest_candle_et",
    "symbol",
    "setup",
    "direction",
    "missing_condition",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track read-only setup near-miss conditions.")
    parser.add_argument("--scanner-csv", type=Path, default=Path("logs/daily_paper_signal_scanner.csv"))
    parser.add_argument("--observations-csv", type=Path, default=Path("data/near_miss_observations.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where the Markdown report is saved.")
    return parser.parse_args()


def condition_list(value: object) -> list[str]:
    """Split scanner condition text into individual condition names."""

    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def missing_conditions(row: pd.Series) -> list[str]:
    """Return structured conditions, with support for older scanner rows."""

    structured = condition_list(row.get("missing_conditions"))
    if structured:
        return structured
    notes = str(row.get("latest_candle_notes", ""))
    if "latest candle gaps:" in notes:
        notes = notes.split("latest candle gaps:", 1)[1]
    return condition_list(notes)


def near_miss_rows(scanner: pd.DataFrame, observed_at_et: str = "") -> pd.DataFrame:
    """Explode non-ready scanner rows into one row per missing condition."""

    if scanner.empty or "scanner_status" not in scanner.columns:
        return pd.DataFrame(columns=NEAR_MISS_COLUMNS)

    rows = []
    for _, row in scanner[scanner["scanner_status"] == "not_ready"].iterrows():
        for condition in missing_conditions(row):
            rows.append(
                {
                    "observed_at_et": observed_at_et,
                    "scan_date": row.get("scan_date", ""),
                    "latest_candle_et": row.get("latest_candle_et", ""),
                    "symbol": row.get("symbol", ""),
                    "setup": row.get("setup", ""),
                    "direction": row.get("direction", ""),
                    "missing_condition": condition,
                    "passed_condition_count": row.get("passed_condition_count", ""),
                    "condition_count": row.get("condition_count", ""),
                    "quality_score": row.get("quality_score", ""),
                    "quality_grade": row.get("quality_grade", ""),
                    "relative_volume": row.get("relative_volume", ""),
                    "room_to_target_r": row.get("room_to_target_r", ""),
                }
            )
    return pd.DataFrame(rows, columns=NEAR_MISS_COLUMNS)


def read_observations(path: Path) -> pd.DataFrame:
    """Read the append-only observation journal or return its empty schema."""

    if not path.exists():
        return pd.DataFrame(columns=NEAR_MISS_COLUMNS)
    try:
        observations = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=NEAR_MISS_COLUMNS)
    for column in NEAR_MISS_COLUMNS:
        if column not in observations.columns:
            observations[column] = ""
    return observations[NEAR_MISS_COLUMNS]


def scanner_is_fresh_for_open_market(scanner: pd.DataFrame, market: dict) -> bool:
    """Only append genuine near-miss observations during a live paper session."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return False
    dates = {str(value) for value in scanner["scan_date"].dropna().unique()}
    return bool(market.get("market_is_open")) and dates == {str(market.get("today"))}


def dedupe(existing: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Avoid counting the same scanner candle and blocker more than once."""

    if candidates.empty:
        return candidates
    existing_keys = set(existing[NEAR_MISS_KEY_COLUMNS].astype(str).agg("|".join, axis=1))
    candidate_keys = candidates[NEAR_MISS_KEY_COLUMNS].astype(str).agg("|".join, axis=1)
    return candidates[~candidate_keys.isin(existing_keys)].drop_duplicates(NEAR_MISS_KEY_COLUMNS).copy()


def blocker_summary(rows: pd.DataFrame) -> list[dict[str, object]]:
    """Return the most common missing requirements."""

    if rows.empty:
        return []
    summary = (
        rows.groupby("missing_condition")
        .size()
        .reset_index(name="occurrences")
        .sort_values(["occurrences", "missing_condition"], ascending=[False, True])
    )
    return summary.head(8).to_dict(orient="records")


def closest_setups(scanner: pd.DataFrame) -> list[dict[str, object]]:
    """Rank latest non-ready setup rows by how many checks currently pass."""

    if scanner.empty or "scanner_status" not in scanner.columns:
        return []
    candidates = scanner[scanner["scanner_status"] == "not_ready"].copy()
    if candidates.empty:
        return []
    for column in ["passed_condition_count", "condition_count"]:
        values = candidates[column] if column in candidates.columns else pd.Series(0, index=candidates.index)
        candidates[column] = pd.to_numeric(values, errors="coerce").fillna(0).astype(int)
    candidates["missing_count"] = candidates.apply(lambda row: len(missing_conditions(row)), axis=1)
    candidates = candidates.sort_values(
        ["passed_condition_count", "missing_count", "symbol", "setup"],
        ascending=[False, True, True, True],
    )
    return [
        {
            "symbol": str(row["symbol"]),
            "setup": str(row["setup"]),
            "direction": str(row["direction"]),
            "passed_condition_count": int(row["passed_condition_count"]),
            "condition_count": int(row["condition_count"]),
            "missing_conditions": missing_conditions(row),
        }
        for _, row in candidates.head(6).iterrows()
    ]


def timestamp_or_none(value: object) -> pd.Timestamp | None:
    """Parse scanner/report timestamps as New York time when possible."""

    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(MARKET_TZ)
    return timestamp.tz_convert(MARKET_TZ)


def matching_later_result(row: pd.Series, results: pd.DataFrame) -> pd.Series:
    """Return the first later allowed observation result for a near-ready row."""

    if results.empty:
        return pd.Series(dtype=object)
    required = {"scan_date", "symbol", "setup", "direction", "signal_status", "signal_time_et"}
    if not required.issubset(results.columns):
        return pd.Series(dtype=object)

    base_time = timestamp_or_none(row.get("latest_candle_et"))
    matches = results[
        (results["scan_date"].astype(str) == str(row.get("scan_date", "")))
        & (results["symbol"].astype(str).str.upper() == str(row.get("symbol", "")).upper())
        & (results["setup"].astype(str) == str(row.get("setup", "")))
        & (results["direction"].astype(str) == str(row.get("direction", "")))
        & (results["signal_status"].astype(str) == "allowed")
    ].copy()
    if matches.empty:
        return pd.Series(dtype=object)

    matches["_signal_ts"] = matches["signal_time_et"].apply(timestamp_or_none)
    matches = matches.dropna(subset=["_signal_ts"]).sort_values("_signal_ts")
    if base_time is not None:
        matches = matches[matches["_signal_ts"] > base_time]
    return matches.iloc[0] if not matches.empty else pd.Series(dtype=object)


def almost_ready_outcomes(rows: pd.DataFrame, results: pd.DataFrame) -> list[dict[str, object]]:
    """Track whether almost-ready rows later turned into allowed observations."""

    if rows.empty:
        return []
    grouped_columns = ["scan_date", "latest_candle_et", "symbol", "setup", "direction"]
    work = rows.copy()
    for column in ["passed_condition_count", "condition_count"]:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0)
    setup_rows = (
        work.groupby(grouped_columns, dropna=False)
        .agg(
            missing_conditions=("missing_condition", lambda values: sorted({str(value) for value in values if str(value)})),
            passed_condition_count=("passed_condition_count", "max"),
            condition_count=("condition_count", "max"),
            quality_grade=("quality_grade", "last"),
            quality_score=("quality_score", "max"),
            relative_volume=("relative_volume", "max"),
            room_to_target_r=("room_to_target_r", "max"),
        )
        .reset_index()
    )
    setup_rows["check_score"] = setup_rows.apply(
        lambda row: round(float(row["passed_condition_count"]) / float(row["condition_count"]), 4)
        if float(row["condition_count"] or 0) > 0
        else 0.0,
        axis=1,
    )
    almost = setup_rows[setup_rows["check_score"] >= 0.55].sort_values(
        ["check_score", "quality_score"],
        ascending=[False, False],
    )

    outcomes: list[dict[str, object]] = []
    for _, row in almost.head(12).iterrows():
        later = matching_later_result(row, results)
        if later.empty:
            resolution = "not_confirmed_later"
            result_r = ""
            result_note = "No later allowed observation was found for this setup/date."
            later_signal = ""
        elif str(later.get("evaluation_status", "")) == "matured":
            resolution = "later_allowed_matured"
            result_r = later.get("hypothetical_r", "")
            result_note = f"Later allowed observation matured via {later.get('hypothetical_exit_reason', '')}."
            later_signal = later.get("signal_time_et", "")
        else:
            resolution = "later_allowed_pending"
            result_r = ""
            result_note = str(later.get("evaluation_note", "Later allowed observation exists but is not matured yet."))
            later_signal = later.get("signal_time_et", "")
        outcomes.append(
            {
                "resolution": resolution,
                "symbol": str(row["symbol"]),
                "setup": str(row["setup"]),
                "direction": str(row["direction"]),
                "near_miss_time_et": str(row["latest_candle_et"]),
                "later_signal_time_et": later_signal,
                "check_score": round(float(row["check_score"]), 4),
                "missing_conditions": row["missing_conditions"],
                "hypothetical_r": result_r,
                "result_note": result_note,
            }
        )
    return outcomes


def build_near_miss_payload(scanner: pd.DataFrame, observations: pd.DataFrame, results: pd.DataFrame | None = None) -> dict:
    """Build dashboard-ready analytics without modifying trading behavior."""

    snapshot = near_miss_rows(scanner)
    basis = "accumulated_open_session_observations" if not observations.empty else "latest_saved_scanner_snapshot"
    analyzed = observations if not observations.empty else snapshot
    missed = almost_ready_outcomes(analyzed, results if results is not None else pd.DataFrame())
    matured = [row for row in missed if row["resolution"] == "later_allowed_matured"]
    return {
        "basis": basis,
        "basis_label": (
            "Accumulated Open-Session Observations"
            if basis == "accumulated_open_session_observations"
            else "Latest Saved Scanner Snapshot"
        ),
        "observed_rows": int(len(observations)),
        "snapshot_blocker_rows": int(len(snapshot)),
        "top_blockers": blocker_summary(analyzed),
        "closest_setups": closest_setups(scanner),
        "missed_opportunities": missed,
        "missed_summary": {
            "almost_ready_tracked": len(missed),
            "later_allowed": sum(row["resolution"].startswith("later_allowed") for row in missed),
            "later_allowed_matured": len(matured),
            "later_allowed_avg_r": round(
                float(pd.to_numeric(pd.Series([row["hypothetical_r"] for row in matured]), errors="coerce").dropna().mean()),
                4,
            )
            if matured
            else 0.0,
        },
        "message": (
            "Open-session near-miss observations are accumulating across workflow scans."
            if not observations.empty
            else "No open-session near-miss journal entries yet. Showing the latest stored scanner snapshot only."
        ),
        "guardrail": "Near-miss analytics explains blocked setup conditions only; it never changes signal eligibility.",
    }


def write_report(path: Path, payload: dict) -> None:
    """Write a compact research-only near-miss report."""

    blockers = pd.DataFrame(payload["top_blockers"])
    setups = pd.DataFrame(payload["closest_setups"])
    missed = pd.DataFrame(payload.get("missed_opportunities", []))
    missed_summary = pd.DataFrame([payload.get("missed_summary", {})])
    path.write_text(
        f"""# Near-Miss Analytics

This report tracks which existing scanner requirements prevent approved setups
from being ready during paper-validation monitoring.

Important: this is research/paper workflow only. It does not create signals,
import paper trades, size positions, place orders, or connect to execution.

## Evidence Basis

```text
{payload["basis_label"]}
{payload["message"]}
Recorded open-session blocker rows: {payload["observed_rows"]}
Latest snapshot blocker rows: {payload["snapshot_blocker_rows"]}
```

## Most Frequent Blockers

{markdown_table(blockers)}

## Closest Latest Setups

{markdown_table(setups)}

## Almost-Ready Outcome Tracker

This section tracks close-but-blocked rows and checks whether they later became
allowed observations. A near-miss row only receives an R outcome after a later
allowed observation exists with a valid entry, stop, and target.

{markdown_table(missed_summary)}

## Almost-Ready Rows

{markdown_table(missed)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
data/near_miss_observations.csv
logs/forward_observation_results.csv
logs/near_miss_analytics.md
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
    existing = read_observations(args.observations_csv)
    market = market_refresh_state()
    candidates = near_miss_rows(scanner, datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"))
    appended = pd.DataFrame(columns=NEAR_MISS_COLUMNS)
    if scanner_is_fresh_for_open_market(scanner, market):
        appended = dedupe(existing, candidates)
        combined = pd.concat([existing, appended], ignore_index=True)
        args.observations_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.observations_csv, index=False)
        status = "appended_new_observations" if not appended.empty else "no_append_duplicate_snapshot"
    else:
        combined = existing
        status = "no_append_scanner_not_fresh_during_open_market"

    results = pd.read_csv(args.output_dir / "forward_observation_results.csv") if (args.output_dir / "forward_observation_results.csv").exists() else pd.DataFrame()
    payload = build_near_miss_payload(scanner, combined, results)
    report_path = args.output_dir / "near_miss_analytics.md"
    write_report(report_path, payload)
    print(f"Near-miss observation status: {status}")
    print(f"New blocker rows appended: {len(appended)}")
    print(f"Saved near-miss report: {report_path}")


if __name__ == "__main__":
    main()
