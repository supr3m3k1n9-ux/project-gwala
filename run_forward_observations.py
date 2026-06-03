"""Append fresh scanner sightings to the forward observation journal.

This is research and paper workflow only. It records fresh allowed and
watch-only scanner signals so forward evidence is not lost between refreshes.
It does not create paper trades, place orders, create alerts, or connect to
broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from reports.refresh_status import market_refresh_state
from run_playbook import markdown_table


OBSERVATION_COLUMNS = [
    "observed_at_et",
    "scan_date",
    "signal_time_et",
    "latest_candle_et",
    "symbol",
    "setup",
    "direction",
    "variant",
    "exit_profile",
    "scanner_status",
    "signal_status",
    "block_reason",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "risk_per_share",
    "quality_score",
    "quality_grade",
    "relative_volume",
    "room_to_target_r",
    "notes",
]
OBSERVATION_KEY_COLUMNS = ["signal_time_et", "symbol", "setup", "direction"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record fresh forward signal observations.")
    parser.add_argument(
        "--scanner-csv",
        type=Path,
        default=Path("logs/daily_paper_signal_scanner.csv"),
        help="Daily scanner CSV to observe.",
    )
    parser.add_argument(
        "--observations-csv",
        type=Path,
        default=Path("data/forward_signal_observations.csv"),
        help="Append-only forward observation journal.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_existing(path: Path) -> pd.DataFrame:
    """Read the observation journal or return its empty schema."""

    if not path.exists():
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    try:
        existing = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=OBSERVATION_COLUMNS)
    for column in OBSERVATION_COLUMNS:
        if column not in existing.columns:
            existing[column] = ""
    return existing[OBSERVATION_COLUMNS]


def candidate_rows(scanner: pd.DataFrame) -> pd.DataFrame:
    """Return current-candle observations worth preserving."""

    required = {"scanner_status", "signal_freshness"}
    if scanner.empty or not required.issubset(scanner.columns):
        return pd.DataFrame(columns=scanner.columns)
    return scanner[
        scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
        & (scanner["signal_freshness"] == "current_candle")
    ].copy()


def scanner_is_fresh_for_open_market(scanner: pd.DataFrame, market: dict) -> bool:
    """Return whether scanner rows can be recorded as fresh observations."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return False
    scanner_dates = {str(value) for value in scanner["scan_date"].dropna().unique()}
    return market["market_is_open"] and scanner_dates == {market["today"]}


def scanner_to_observations(scanner: pd.DataFrame, observed_at_et: str) -> pd.DataFrame:
    """Convert selected scanner rows to immutable observation fields."""

    rows = []
    for _, row in candidate_rows(scanner).iterrows():
        rows.append(
            {
                "observed_at_et": observed_at_et,
                "scan_date": row.get("scan_date", ""),
                "signal_time_et": row.get("latest_signal_et", ""),
                "latest_candle_et": row.get("latest_candle_et", ""),
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "variant": row.get("variant", ""),
                "exit_profile": row.get("exit_profile", ""),
                "scanner_status": row.get("scanner_status", ""),
                "signal_status": "blocked" if row.get("scanner_status") == "blocked_watch_only" else "allowed",
                "block_reason": row.get("block_reason", ""),
                "planned_entry": row.get("planned_entry", ""),
                "planned_stop": row.get("planned_stop", ""),
                "planned_target": row.get("planned_target", ""),
                "risk_per_share": row.get("risk_per_share", ""),
                "quality_score": row.get("quality_score", ""),
                "quality_grade": row.get("quality_grade", ""),
                "relative_volume": row.get("relative_volume", ""),
                "room_to_target_r": row.get("room_to_target_r", ""),
                "notes": row.get("notes", ""),
            }
        )
    return pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)


def dedupe(existing: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Return candidate sightings not already in the append-only journal."""

    if candidates.empty:
        return candidates
    existing_keys = set(existing[OBSERVATION_KEY_COLUMNS].astype(str).agg("|".join, axis=1))
    candidate_keys = candidates[OBSERVATION_KEY_COLUMNS].astype(str).agg("|".join, axis=1)
    return candidates[~candidate_keys.isin(existing_keys)].drop_duplicates(OBSERVATION_KEY_COLUMNS).copy()


def summary_by_status(observations: pd.DataFrame) -> pd.DataFrame:
    """Count allowed and watch-only observations."""

    if observations.empty:
        return pd.DataFrame()
    return observations.groupby("signal_status").size().reset_index(name="observations").sort_values("signal_status")


def summary_by_setup(observations: pd.DataFrame) -> pd.DataFrame:
    """Count observations by setup and status."""

    if observations.empty:
        return pd.DataFrame()
    return (
        observations.groupby(["symbol", "setup", "direction", "signal_status"])
        .size()
        .reset_index(name="observations")
        .sort_values(["observations", "symbol"], ascending=[False, True])
    )


def write_report(
    path: Path,
    observations: pd.DataFrame,
    append_status: str,
    scanner_candidates: int,
    appended_rows: int,
    market: dict,
    observations_csv: Path,
) -> None:
    """Write a readable forward observation audit report."""

    recent = observations.tail(30) if not observations.empty else pd.DataFrame()
    path.write_text(
        f"""# Forward Signal Observations

This append-only journal preserves fresh scanner sightings during paper
validation, including allowed candidates and blocked/watch-only signals.

Important: this is research/paper workflow only. Observations are not paper
trades and do not place orders, create alerts, or connect to broker execution.

## Latest Journal Attempt

```text
Status: {append_status}
Market status: {market["market_status"]}
Market date: {market["today"]}
Fresh current-candle candidates found: {scanner_candidates}
New observations appended: {appended_rows}
```

## Observation Status Summary

{markdown_table(summary_by_status(observations))}

## By Setup

{markdown_table(summary_by_setup(observations))}

## Latest Observations

{markdown_table(recent)}

## Deduplication Rule

```text
Repeated refreshes do not append the same symbol + setup + direction + signal timestamp twice.
Only fresh current-candle candidates during an open market session are recorded.
```

## Files

```text
{observations_csv}
{path}
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
    existing = read_existing(args.observations_csv)
    market = market_refresh_state()
    selected = candidate_rows(scanner)
    appended = pd.DataFrame(columns=OBSERVATION_COLUMNS)

    if not scanner_is_fresh_for_open_market(scanner, market):
        append_status = "no_append_scanner_not_fresh_during_open_market"
    elif selected.empty:
        append_status = "no_append_no_current_candle_candidates"
    else:
        observed_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        appended = dedupe(existing, scanner_to_observations(scanner, observed_at))
        append_status = "appended_new_observations" if not appended.empty else "no_append_duplicate_observations"

    combined = pd.concat([existing, appended], ignore_index=True)
    wrote_journal = not appended.empty or not args.observations_csv.exists()
    if wrote_journal:
        args.observations_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.observations_csv, index=False)

    report_path = args.output_dir / "forward_signal_observations.md"
    write_report(
        report_path,
        combined,
        append_status,
        len(selected),
        len(appended),
        market,
        args.observations_csv,
    )
    print(f"Forward observation status: {append_status}")
    print(f"New observations appended: {len(appended)}")
    journal_action = "Saved observation journal" if wrote_journal else "Observation journal unchanged"
    print(f"{journal_action}: {args.observations_csv}")
    print(f"Saved observation report: {report_path}")


if __name__ == "__main__":
    main()
