"""Collect and grade shadow samples from near-miss scanner rows.

Shadow samples are observation-only "almost trades." They let us study whether
rules are too strict without polluting the official paper-trade log.

This is research and paper-validation only. It does not create paper trades,
size positions, place orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtesting.engine import find_exit, find_short_exit
from config.market_calendar import MARKET_TZ
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from reports.refresh_status import market_refresh_state
from run_daily_scanner import load_enriched_candles, plan_for_signal
from run_forward_observation_review import load_exit_candles, session_has_closed_data
from run_near_miss_analytics import missing_conditions
from run_playbook import markdown_table
from run_webull_watchlist import EXIT_PROFILES


SHADOW_COLUMNS = [
    "observed_at_et",
    "scan_date",
    "entry_time_et",
    "latest_candle_et",
    "symbol",
    "setup",
    "direction",
    "variant",
    "exit_profile",
    "shadow_status",
    "shadow_reason",
    "missing_conditions",
    "passed_condition_count",
    "condition_count",
    "check_score",
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
SHADOW_KEY_COLUMNS = [
    "scan_date",
    "entry_time_et",
    "symbol",
    "setup",
    "direction",
    "missing_conditions",
]
OUTCOME_COLUMNS = [
    *SHADOW_COLUMNS,
    "evaluation_status",
    "hypothetical_exit_time_et",
    "hypothetical_exit_price",
    "hypothetical_r",
    "hypothetical_exit_reason",
    "evaluation_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and review Project Gwala shadow samples.")
    parser.add_argument("--scanner-csv", type=Path, default=Path("logs/daily_paper_signal_scanner.csv"))
    parser.add_argument("--shadow-csv", type=Path, default=Path("data/shadow_samples.csv"))
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where saved Webull candles live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--record-latest-snapshot",
        action="store_true",
        help="Append the latest scanner snapshot even outside open-market freshness gates. Research backfill only.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns or [])
    if columns:
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]
    return frame


def text_value(value: object) -> str:
    """Return clean text from a CSV value."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number_value(value: object, default: float = 0.0) -> float:
    """Return a float from CSV values."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def check_score(row: pd.Series) -> float:
    """Return the fraction of scanner checks that passed."""

    total = number_value(row.get("condition_count"))
    if total <= 0:
        return 0.0
    return round(number_value(row.get("passed_condition_count")) / total, 4)


def latest_rows(scanner: pd.DataFrame) -> pd.DataFrame:
    """Return the latest scanner session rows."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return pd.DataFrame()
    latest = sorted(str(value) for value in scanner["scan_date"].dropna().unique())[-1]
    return scanner[scanner["scan_date"].astype(str) == latest].copy()


def shadow_status_for_row(row: pd.Series) -> tuple[str, str]:
    """Classify whether a blocked row is useful shadow evidence."""

    missing = missing_conditions(row)
    score = check_score(row)
    if text_value(row.get("scanner_status")) == "allowed":
        return "official_candidate", "Allowed rows belong in the official paper lane, not shadow samples."
    if len(missing) == 1 and score >= 0.80:
        return "one_rule_miss", "One scanner rule away from passing."
    if len(missing) <= 2 and score >= 0.75:
        return "close_watch_shadow", "Close setup with one or two missing rules."
    return "not_shadow_candidate", "Not close enough for shadow collection."


def playbook_lookup() -> dict[tuple[str, str, str, str], PlaybookEntry]:
    """Return playbook entries keyed by scanner identity."""

    entries = PLAYBOOKS["approved_plus_watch"]
    return {
        (entry.symbol.upper(), entry.setup_name, entry.variant, entry.exit_profile): entry
        for entry in entries
    }


def parse_entry_timestamp(value: object) -> pd.Timestamp:
    """Parse scanner local ET timestamp."""

    timestamp = pd.Timestamp(text_value(value))
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(MARKET_TZ)
    return timestamp.tz_convert(MARKET_TZ)


def plan_from_latest_candle(row: pd.Series, data_dir: Path, market_symbol: str = "SPY") -> dict[str, object]:
    """Build a hypothetical plan from the latest scanner candle."""

    lookup = playbook_lookup()
    key = (
        text_value(row.get("symbol")).upper(),
        text_value(row.get("setup")),
        text_value(row.get("variant")),
        text_value(row.get("exit_profile")),
    )
    entry = lookup.get(key)
    if entry is None:
        raise ValueError(f"No playbook entry found for {key}.")
    candles = load_enriched_candles(entry, data_dir, market_symbol)
    entry_time = parse_entry_timestamp(row.get("latest_candle_et"))
    matching = candles[candles.index <= entry_time]
    if matching.empty:
        raise ValueError(f"No enriched candle found at or before {entry_time}.")
    candle = matching.iloc[-1]
    return plan_for_signal(candle, entry, EXIT_PROFILES[entry.exit_profile])


def build_shadow_candidates(scanner: pd.DataFrame, data_dir: Path, observed_at_et: str) -> pd.DataFrame:
    """Build shadow sample rows from the latest scanner snapshot."""

    rows: list[dict[str, object]] = []
    latest = latest_rows(scanner)
    for _, row in latest.iterrows():
        status, reason = shadow_status_for_row(row)
        if status not in {"one_rule_miss", "close_watch_shadow"}:
            continue
        try:
            plan = plan_from_latest_candle(row, data_dir)
        except (FileNotFoundError, ValueError, KeyError) as error:
            plan = {"planned_entry": "", "planned_stop": "", "planned_target": "", "risk_per_share": ""}
            status = "blocked_missing_plan"
            reason = str(error)
        missing = missing_conditions(row)
        rows.append(
            {
                "observed_at_et": observed_at_et,
                "scan_date": row.get("scan_date", ""),
                "entry_time_et": row.get("latest_candle_et", ""),
                "latest_candle_et": row.get("latest_candle_et", ""),
                "symbol": text_value(row.get("symbol")).upper(),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "variant": row.get("variant", ""),
                "exit_profile": row.get("exit_profile", ""),
                "shadow_status": status,
                "shadow_reason": reason,
                "missing_conditions": "; ".join(missing),
                "passed_condition_count": row.get("passed_condition_count", ""),
                "condition_count": row.get("condition_count", ""),
                "check_score": check_score(row),
                **plan,
                "quality_score": row.get("quality_score", ""),
                "quality_grade": row.get("quality_grade", ""),
                "relative_volume": row.get("relative_volume", ""),
                "room_to_target_r": row.get("room_to_target_r", ""),
                "notes": row.get("notes", ""),
            }
        )
    return pd.DataFrame(rows, columns=SHADOW_COLUMNS)


def scanner_is_fresh_for_open_market(scanner: pd.DataFrame, market: dict[str, object]) -> bool:
    """Return whether shadow rows should append automatically."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return False
    dates = {str(value) for value in scanner["scan_date"].dropna().unique()}
    return bool(market.get("market_is_open", False)) and dates == {str(market.get("today", ""))}


def dedupe(existing: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Avoid appending duplicate shadow samples."""

    if candidates.empty:
        return candidates
    existing_keys = set(existing[SHADOW_KEY_COLUMNS].astype(str).agg("|".join, axis=1))
    candidate_keys = candidates[SHADOW_KEY_COLUMNS].astype(str).agg("|".join, axis=1)
    return candidates[~candidate_keys.isin(existing_keys)].drop_duplicates(SHADOW_KEY_COLUMNS).copy()


def grade_shadow_sample(row: pd.Series, data_dir: Path, cache: dict[str, pd.DataFrame]) -> dict[str, object]:
    """Grade one shadow sample using saved 5m candles."""

    result = {column: row.get(column, "") for column in SHADOW_COLUMNS}
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
    if text_value(row.get("shadow_status")) == "blocked_missing_plan":
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = text_value(row.get("shadow_reason"))
        return result

    symbol = text_value(row.get("symbol")).upper()
    try:
        entry_time = parse_entry_timestamp(row.get("entry_time_et"))
        entry = float(row["planned_entry"])
        stop = float(row["planned_stop"])
        target = float(row["planned_target"])
        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            raise ValueError("Shadow sample has zero risk per share.")
        if symbol not in cache:
            cache[symbol] = load_exit_candles(symbol, data_dir)
        candles = cache[symbol]
    except (FileNotFoundError, ValueError, TypeError) as error:
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = str(error)
        return result

    session_date = entry_time.date()
    if not session_has_closed_data(candles, session_date):
        result["evaluation_status"] = "awaiting_complete_session_data"
        result["evaluation_note"] = "Complete regular-session 5m candles are not yet available."
        return result

    profile = EXIT_PROFILES.get(text_value(row.get("exit_profile")) or "current")
    if profile is None:
        result["evaluation_status"] = "data_error"
        result["evaluation_note"] = f"Unknown exit profile: {row.get('exit_profile')}"
        return result

    if text_value(row.get("direction")).lower() == "short":
        exit_result = find_short_exit(entry_time, entry, stop, target, risk_per_share, session_date, candles, profile)
    else:
        exit_result = find_exit(entry_time, entry, stop, target, risk_per_share, session_date, candles, profile)

    if exit_result is None:
        result["evaluation_status"] = "no_future_exit_candle"
        result["evaluation_note"] = "No regular-session 5m candle exists after the shadow entry."
        return result

    exit_time, _, exit_price, r_result, exit_reason = exit_result
    result.update(
        {
            "evaluation_status": "matured",
            "hypothetical_exit_time_et": exit_time.tz_convert(MARKET_TZ).strftime("%Y-%m-%d %H:%M"),
            "hypothetical_exit_price": round(float(exit_price), 4),
            "hypothetical_r": round(float(r_result), 4),
            "hypothetical_exit_reason": exit_reason,
            "evaluation_note": "Shadow outcome only; not an official paper trade.",
        }
    )
    return result


def build_outcomes(samples: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Grade all shadow samples."""

    if samples.empty:
        return pd.DataFrame(columns=OUTCOME_COLUMNS)
    cache: dict[str, pd.DataFrame] = {}
    outcomes = [grade_shadow_sample(row, data_dir, cache) for _, row in samples.iterrows()]
    frame = pd.DataFrame(outcomes)
    for column in OUTCOME_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[OUTCOME_COLUMNS]


def matured_summary(outcomes: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Summarize matured shadow outcomes by a grouping."""

    if outcomes.empty:
        return pd.DataFrame()
    matured = outcomes[outcomes["evaluation_status"] == "matured"].copy()
    if matured.empty:
        return pd.DataFrame()
    matured["hypothetical_r"] = pd.to_numeric(matured["hypothetical_r"], errors="coerce")
    rows = []
    for values, group in matured.groupby(group_columns, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        r = group["hypothetical_r"].dropna()
        row = {column: value for column, value in zip(group_columns, values)}
        row.update(
            {
                "samples": int(len(group)),
                "win_rate": round(float((r > 0).mean()), 4) if not r.empty else 0.0,
                "avg_r": round(float(r.mean()), 4) if not r.empty else 0.0,
                "total_r": round(float(r.sum()), 4) if not r.empty else 0.0,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["avg_r", "samples"], ascending=[False, False])


def write_report(
    path: Path,
    candidates: pd.DataFrame,
    appended: pd.DataFrame,
    samples: pd.DataFrame,
    outcomes: pd.DataFrame,
    append_status: str,
    shadow_csv: Path,
    outcomes_csv: Path,
) -> None:
    """Write the shadow sample report."""

    status = outcomes.groupby("evaluation_status").size().reset_index(name="samples") if not outcomes.empty else pd.DataFrame()
    latest_candidates = candidates if not candidates.empty else pd.DataFrame(columns=SHADOW_COLUMNS)
    recent_samples = samples.tail(20) if not samples.empty else pd.DataFrame(columns=SHADOW_COLUMNS)
    recent_outcomes = outcomes[outcomes["evaluation_status"] == "matured"].tail(20) if not outcomes.empty else pd.DataFrame(columns=OUTCOME_COLUMNS)
    path.write_text(
        f"""# Shadow Sample Collection

Shadow samples are near-miss setups that are watched and scored separately
from official paper trades.

Important: this is research and paper-validation only. Shadow samples do not
count toward the 30/60 official paper-trade gates and do not place orders.

## Latest Collection Attempt

```text
Append status: {append_status}
Latest shadow candidates: {len(candidates)}
New shadow samples appended: {len(appended)}
Total stored shadow samples: {len(samples)}
```

## Latest Shadow Candidates

{markdown_table(latest_candidates)}

## Evaluation Status

{markdown_table(status)}

## Outcome By Missing Rule

{markdown_table(matured_summary(outcomes, ["missing_conditions"]))}

## Outcome By Symbol And Setup

{markdown_table(matured_summary(outcomes, ["symbol", "setup", "direction"]))}

## Recent Stored Samples

{markdown_table(recent_samples)}

## Recent Matured Outcomes

{markdown_table(recent_outcomes)}

## Guardrail

```text
Official paper trades and shadow samples stay separate.
Shadow samples are for rule research only.
Promote a relaxation only after shadow evidence and backtests agree.
```

## Files

```text
{shadow_csv}
{outcomes_csv}
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
    existing = read_csv_or_empty(args.shadow_csv, SHADOW_COLUMNS)
    market = market_refresh_state()
    observed_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    candidates = build_shadow_candidates(scanner, args.data_dir, observed_at)
    appended = pd.DataFrame(columns=SHADOW_COLUMNS)

    if args.record_latest_snapshot or scanner_is_fresh_for_open_market(scanner, market):
        appended = dedupe(existing, candidates)
        append_status = "appended_new_shadow_samples" if not appended.empty else "no_append_duplicate_shadow_samples"
    else:
        append_status = "no_append_scanner_not_fresh_during_open_market"

    combined = pd.concat([existing, appended], ignore_index=True)
    if not appended.empty or not args.shadow_csv.exists():
        args.shadow_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(args.shadow_csv, index=False)

    outcomes = build_outcomes(combined, args.data_dir)
    outcomes_csv = args.output_dir / "shadow_sample_outcomes.csv"
    report_path = args.output_dir / "shadow_samples.md"
    outcomes.to_csv(outcomes_csv, index=False)
    write_report(report_path, candidates, appended, combined, outcomes, append_status, args.shadow_csv, outcomes_csv)

    matured_count = int((outcomes["evaluation_status"] == "matured").sum()) if not outcomes.empty else 0
    print(f"Shadow append status: {append_status}")
    print(f"Latest shadow candidates: {len(candidates)}")
    print(f"New shadow samples appended: {len(appended)}")
    print(f"Matured shadow outcomes: {matured_count}")
    print(f"Saved shadow outcomes CSV: {outcomes_csv}")
    print(f"Saved shadow report: {report_path}")


if __name__ == "__main__":
    main()
