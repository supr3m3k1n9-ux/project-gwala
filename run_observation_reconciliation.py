"""Match manually logged paper trades to preserved forward observations."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile paper trades with forward observations.")
    parser.add_argument("--observations-csv", type=Path, default=Path("data/forward_signal_observations.csv"))
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if present."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def observation_key(frame: pd.DataFrame) -> pd.Series:
    """Build the shared key used for observation/paper matching."""

    return (
        frame["signal_time_et"].astype(str)
        + "|"
        + frame["symbol"].astype(str)
        + "|"
        + frame["setup"].astype(str)
        + "|"
        + frame["direction"].astype(str)
    )


def paper_key(frame: pd.DataFrame) -> pd.Series:
    """Build observation-style keys from manually logged paper rows."""

    signal_time = frame["trade_date"].astype(str) + " " + frame["entry_time_et"].astype(str)
    return signal_time + "|" + frame["symbol"].astype(str) + "|" + frame["setup"].astype(str) + "|" + frame["direction"].astype(str)


def reconcile(observations: pd.DataFrame, paper: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return observation rows with paper status plus unmatched paper rows."""

    if observations.empty:
        return pd.DataFrame(), paper.copy()

    result = observations.copy()
    result["_key"] = observation_key(result)
    paper_copy = paper.copy()
    if not paper_copy.empty:
        paper_copy["_key"] = paper_key(paper_copy)
        paper_copy["paper_logged"] = True
        paper_columns = paper_copy[["_key", "paper_logged", "outcome_r", "followed_plan", "exit_reason"]].drop_duplicates("_key")
        result = result.merge(paper_columns, on="_key", how="left")
        matched_keys = set(result["_key"]) & set(paper_copy["_key"])
        unmatched = paper_copy[~paper_copy["_key"].isin(matched_keys)].drop(columns=["_key"])
    else:
        result["paper_logged"] = False
        result["outcome_r"] = ""
        result["followed_plan"] = ""
        result["exit_reason"] = ""
        unmatched = pd.DataFrame()

    logged = result["paper_logged"].fillna(False).astype(bool)
    taken = result["outcome_r"].notna() & (result["outcome_r"].astype(str).str.strip() != "")
    result["reconciliation_status"] = "observed_not_taken"
    result.loc[result["signal_status"] == "blocked", "reconciliation_status"] = "watch_only_observed"
    result.loc[logged, "reconciliation_status"] = "paper_logged_open"
    result.loc[taken, "reconciliation_status"] = "paper_outcome_recorded"
    return result.drop(columns=["_key"]), unmatched


def write_report(path: Path, reconciled: pd.DataFrame, unmatched: pd.DataFrame) -> None:
    """Write reconciliation report."""

    status = reconciled.groupby("reconciliation_status").size().reset_index(name="signals") if not reconciled.empty else pd.DataFrame()
    untaken_allowed = (
        reconciled[(reconciled["signal_status"] == "allowed") & (reconciled["reconciliation_status"] == "observed_not_taken")]
        if not reconciled.empty
        else pd.DataFrame()
    )
    path.write_text(
        f"""# Observation To Paper Reconciliation

This report distinguishes observed signals from manually logged paper results.

Important: an observed signal is not a trade. Only rows with a manually
recorded paper outcome are treated as paper results.

## Status Summary

{markdown_table(status)}

## Allowed Observations Not Taken

{markdown_table(untaken_allowed.tail(30))}

## Paper Rows Without Matching Observation

{markdown_table(unmatched)}

## Files

```text
data/forward_signal_observations.csv
data/paper_trades.csv
logs/observation_paper_reconciliation.csv
logs/observation_paper_reconciliation.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    observations = read_csv_or_empty(args.observations_csv)
    paper = read_csv_or_empty(args.paper_csv)
    reconciled, unmatched = reconcile(observations, paper)
    csv_path = args.output_dir / "observation_paper_reconciliation.csv"
    report_path = args.output_dir / "observation_paper_reconciliation.md"
    reconciled.to_csv(csv_path, index=False)
    write_report(report_path, reconciled, unmatched)
    print(f"Observations reconciled: {len(reconciled)}")
    print(f"Unmatched paper rows: {len(unmatched)}")
    print(f"Saved reconciliation CSV: {csv_path}")
    print(f"Saved reconciliation report: {report_path}")


if __name__ == "__main__":
    main()
