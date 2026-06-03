"""Grade matured forward observations using local 5m candle data.

This is research and paper workflow only. It applies the recorded plan and
approved exit profile to observed signals after their session has completed.
The results are hypothetical observations, not paper trades or orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtesting.engine import find_exit, find_short_exit
from config.market_calendar import MARKET_TZ
from config.settings import STRATEGY
from data.market_data import load_candles_from_csv
from indicators.session import add_session_columns
from indicators.trend import add_core_indicators
from run_data_integrity import session_coverage_for_latest
from run_playbook import markdown_table
from run_webull_watchlist import EXIT_PROFILES


RESULT_COLUMNS = [
    "observed_at_et",
    "scan_date",
    "signal_time_et",
    "symbol",
    "setup",
    "direction",
    "scanner_status",
    "signal_status",
    "block_reason",
    "exit_profile",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "evaluation_status",
    "hypothetical_exit_time_et",
    "hypothetical_exit_price",
    "hypothetical_r",
    "hypothetical_exit_reason",
    "evaluation_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade matured forward signal observations.")
    parser.add_argument(
        "--observations-csv",
        type=Path,
        default=Path("data/forward_signal_observations.csv"),
        help="Append-only observation journal.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where local Webull candle CSVs live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where review outputs are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read CSV data without failing on a header-only journal."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def entry_timestamp_et(value: object) -> pd.Timestamp:
    """Parse an observation signal timestamp as New York trading time."""

    timestamp = pd.Timestamp(str(value))
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(MARKET_TZ)
    return timestamp.tz_convert(MARKET_TZ)


def session_has_closed_data(candles: pd.DataFrame, session_date) -> bool:
    """Return whether local candles cover the completed observed session."""

    session = candles[candles["session_date"] == session_date]
    if session.empty:
        return False

    latest_bar = pd.to_datetime(session["local_time"]).max()
    coverage = session_coverage_for_latest(session_date, latest_bar.to_pydatetime())
    return coverage in {"complete", "provider_final_bar"}


def load_exit_candles(symbol: str, data_dir: Path) -> pd.DataFrame:
    """Load and enrich 5m candles required by existing exit logic."""

    path = data_dir / f"webull_{symbol}_M5_candles.csv"
    candles = load_candles_from_csv(path, symbol)
    candles = add_core_indicators(
        candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    return add_session_columns(candles, STRATEGY)


def base_result(row: pd.Series) -> dict:
    """Keep recorded observation fields in the review output."""

    return {column: row.get(column, "") for column in RESULT_COLUMNS if column in row.index}


def grade_observation(row: pd.Series, data_dir: Path, candle_cache: dict[str, pd.DataFrame]) -> dict:
    """Grade one observation after complete 5m session data exists."""

    result = base_result(row)
    result.update(
        {
            "evaluation_status": "pending",
            "hypothetical_exit_time_et": "",
            "hypothetical_exit_price": "",
            "hypothetical_r": "",
            "hypothetical_exit_reason": "",
            "evaluation_note": "",
        }
    )
    symbol = str(row.get("symbol", "")).upper()
    try:
        signal_time = entry_timestamp_et(row.get("signal_time_et", ""))
        session_date = signal_time.date()
        if symbol not in candle_cache:
            candle_cache[symbol] = load_exit_candles(symbol, data_dir)
        exit_candles = candle_cache[symbol]
    except (FileNotFoundError, ValueError, TypeError) as error:
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = str(error)
        return result

    if not session_has_closed_data(exit_candles, session_date):
        result["evaluation_status"] = "awaiting_complete_session_data"
        result["evaluation_note"] = "Complete regular-session 5m candles are not yet available."
        return result

    entry = float(row["planned_entry"])
    stop = float(row["planned_stop"])
    target = float(row["planned_target"])
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = "Recorded planned risk per share is zero."
        return result

    profile_name = str(row.get("exit_profile", "current"))
    profile = EXIT_PROFILES.get(profile_name)
    if profile is None:
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = f"Unknown exit profile: {profile_name}"
        return result

    if str(row.get("direction", "")).lower() == "short":
        exit_result = find_short_exit(signal_time, entry, stop, target, risk_per_share, session_date, exit_candles, profile)
    else:
        exit_result = find_exit(signal_time, entry, stop, target, risk_per_share, session_date, exit_candles, profile)

    if exit_result is None:
        result["evaluation_status"] = "no_future_exit_candle"
        result["evaluation_note"] = "No regular-session 5m candle exists after the recorded signal."
        return result

    exit_time, _, exit_price, r_result, exit_reason = exit_result
    result.update(
        {
            "evaluation_status": "matured",
            "hypothetical_exit_time_et": exit_time.tz_convert(MARKET_TZ).strftime("%Y-%m-%d %H:%M"),
            "hypothetical_exit_price": round(float(exit_price), 4),
            "hypothetical_r": round(float(r_result), 4),
            "hypothetical_exit_reason": exit_reason,
            "evaluation_note": "Observed hypothetical outcome; not a paper trade.",
        }
    )
    return result


def build_results(observations: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Grade all preserved observations."""

    if observations.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    cache: dict[str, pd.DataFrame] = {}
    results = [grade_observation(row, data_dir, cache) for _, row in observations.iterrows()]
    frame = pd.DataFrame(results)
    for column in RESULT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[RESULT_COLUMNS]


def matured_summary(results: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Summarize hypothetical outcomes for matured observations."""

    matured = results[results["evaluation_status"] == "matured"].copy() if not results.empty else pd.DataFrame()
    if matured.empty:
        return pd.DataFrame()
    matured["hypothetical_r"] = pd.to_numeric(matured["hypothetical_r"])
    rows = []
    for values, group in matured.groupby(group_columns, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        r = group["hypothetical_r"]
        row = {column: value for column, value in zip(group_columns, values)}
        row.update({"observations": len(group), "win_rate": round(float((r > 0).mean()), 4), "avg_r": round(float(r.mean()), 4), "total_r": round(float(r.sum()), 4)})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("avg_r", ascending=False)


def write_report(path: Path, results: pd.DataFrame, observations_csv: Path, results_csv: Path) -> None:
    """Write a readable observation outcome report."""

    status = results.groupby("evaluation_status").size().reset_index(name="observations") if not results.empty else pd.DataFrame()
    matured = results[results["evaluation_status"] == "matured"].tail(30) if not results.empty else pd.DataFrame()
    path.write_text(
        f"""# Forward Observation Review

This report grades preserved forward scanner observations from completed local
5m sessions.

Important: every outcome here is an observed hypothetical outcome, not a paper
trade. This report does not place orders, create alerts, or connect to broker execution.

## Evaluation Status

{markdown_table(status)}

## Allowed Versus Watch-Only Outcomes

{markdown_table(matured_summary(results, ["signal_status"]))}

## By Setup

{markdown_table(matured_summary(results, ["symbol", "setup", "signal_status"]))}

## By Block Reason

{markdown_table(matured_summary(results[results["signal_status"] == "blocked"] if not results.empty else results, ["block_reason"]))}

## Latest Matured Observations

{markdown_table(matured)}

## Files

```text
{observations_csv}
{results_csv}
{path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    observations = read_csv_or_empty(args.observations_csv)
    results = build_results(observations, args.data_dir)
    results_csv = args.output_dir / "forward_observation_results.csv"
    report_path = args.output_dir / "forward_observation_review.md"
    results.to_csv(results_csv, index=False)
    write_report(report_path, results, args.observations_csv, results_csv)
    matured = int((results["evaluation_status"] == "matured").sum()) if not results.empty else 0
    print(f"Forward observations reviewed: {len(results)}")
    print(f"Matured hypothetical outcomes: {matured}")
    print(f"Saved observation results: {results_csv}")
    print(f"Saved observation review: {report_path}")


if __name__ == "__main__":
    main()
