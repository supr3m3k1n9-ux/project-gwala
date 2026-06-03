"""Build the forward paper sample queue.

This is research and paper-validation only. It ranks current scanner rows for
review and sample collection. It does not create paper trades, place orders,
or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date
from config.settings import STRATEGY
from run_playbook import markdown_table


QUEUE_COLUMNS = [
    "queue_status",
    "priority",
    "symbol",
    "setup",
    "direction",
    "signal_time_et",
    "latest_candle_et",
    "scanner_status",
    "signal_freshness",
    "sizing_status",
    "quality_grade",
    "quality_score",
    "relative_volume",
    "room_to_target_r",
    "check_score",
    "entry",
    "stop",
    "target",
    "shares",
    "estimated_risk_dollars",
    "next_action",
    "blockers",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Project Gwala forward sample queue.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where queue reports are saved.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and is parseable."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def market_refresh_state() -> dict[str, Any]:
    """Return the small market state needed for queue classification."""

    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    now = datetime.now(MARKET_TZ)
    today = market_session_for_date(now.date(), open_time, close_time)
    market_is_open = bool(
        today.is_market_day
        and today.market_open is not None
        and today.market_close is not None
        and today.market_open <= now <= today.market_close
    )
    if market_is_open:
        status = "market_open"
    elif today.is_market_day and today.market_open is not None and now < today.market_open:
        status = "before_open"
    elif today.is_market_day and today.market_close is not None and now > today.market_close:
        status = "after_close"
    else:
        status = "market_closed"
    return {
        "today": str(now.date()),
        "market_is_open": market_is_open,
        "market_status": status,
    }


def text_value(value: object) -> str:
    """Return a clean string for reports."""

    if pd.isna(value) or str(value).strip() == "":
        return ""
    return str(value).strip()


def number_value(value: object, default: float = 0.0) -> float:
    """Return a float when a CSV value is numeric."""

    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def report_value(value: object) -> object:
    """Return a blank value instead of CSV/Markdown nan."""

    if pd.isna(value):
        return ""
    return value


def matching_size(row: pd.Series, sizing: pd.DataFrame) -> pd.Series:
    """Return the matching sizing row for a scanner row."""

    if sizing.empty:
        return pd.Series(dtype=object)
    matches = sizing[
        (sizing["symbol"] == row.get("symbol"))
        & (sizing["setup"] == row.get("setup"))
        & (sizing["direction"] == row.get("direction"))
    ]
    return matches.iloc[0] if not matches.empty else pd.Series(dtype=object)


def check_score(row: pd.Series) -> float:
    """Return the fraction of setup checks currently passing."""

    passed = number_value(row.get("passed_condition_count"))
    total = number_value(row.get("condition_count"))
    if total <= 0:
        return 0.0
    return round(passed / total, 4)


def status_for_row(row: pd.Series, size: pd.Series, market: dict[str, Any]) -> tuple[str, int, str, list[str]]:
    """Classify a scanner row for the forward sample queue."""

    scanner_status = text_value(row.get("scanner_status"))
    signal_freshness = text_value(row.get("signal_freshness"))
    sizing_status = text_value(size.get("sizing_status"))
    same_session = text_value(row.get("scan_date")) == text_value(market.get("today"))
    market_open = bool(market.get("market_is_open", False))
    current_candle = signal_freshness == "current_candle"
    allowed = scanner_status == "allowed"
    blocked_watch = scanner_status == "blocked_watch_only"
    size_ok = sizing_status == "size_ok"

    blockers: list[str] = []
    if not market_open:
        blockers.append("market is not open")
    if not same_session:
        blockers.append("scanner row is not from today's session")
    if not current_candle:
        blockers.append("not a current-candle signal")
    if not allowed:
        reason = text_value(row.get("block_reason"))
        blockers.append(reason or f"scanner status is {scanner_status or 'missing'}")
    if not size_ok:
        blockers.append(text_value(size.get("sizing_reason")) or "position sizing is not size_ok")

    if market_open and same_session and current_candle and allowed and size_ok:
        return "ready_for_review", 1, "Review checklist, chart, stop, target, and local paper size.", []
    if market_open and same_session and current_candle and (allowed or blocked_watch):
        return "blocked_current", 2, "Study the blocker. Do not confirm local paper entry.", blockers
    if same_session and scanner_status in {"not_ready", "blocked_watch_only"} and check_score(row) >= 0.55:
        return "almost_ready", 3, "Watch the next scan. Conditions are close, but no paper entry is allowed.", blockers
    return "waiting", 4, "No action. Keep collecting clean samples only when the scanner qualifies.", blockers


def build_queue(scanner: pd.DataFrame, sizing: pd.DataFrame, market: dict[str, Any]) -> pd.DataFrame:
    """Build the queue table from scanner and sizing outputs."""

    if scanner.empty:
        return pd.DataFrame(columns=QUEUE_COLUMNS)

    latest_date = ""
    if "scan_date" in scanner.columns and not scanner["scan_date"].dropna().empty:
        latest_date = sorted(str(value) for value in scanner["scan_date"].dropna().unique())[-1]

    rows: list[dict[str, object]] = []
    latest = scanner[scanner["scan_date"].astype(str) == latest_date].copy() if latest_date else scanner.copy()
    for _, row in latest.iterrows():
        size = matching_size(row, sizing)
        queue_status, priority, next_action, blockers = status_for_row(row, size, market)
        sizing_status = text_value(size.get("sizing_status")) or "missing"
        rows.append(
            {
                "queue_status": queue_status,
                "priority": priority,
                "symbol": text_value(row.get("symbol")).upper(),
                "setup": text_value(row.get("setup")),
                "direction": text_value(row.get("direction")),
                "signal_time_et": text_value(row.get("latest_signal_et")),
                "latest_candle_et": text_value(row.get("latest_candle_et")),
                "scanner_status": text_value(row.get("scanner_status")),
                "signal_freshness": text_value(row.get("signal_freshness")),
                "sizing_status": sizing_status,
                "quality_grade": text_value(row.get("quality_grade")),
                "quality_score": number_value(row.get("quality_score")),
                "relative_volume": round(number_value(row.get("relative_volume")), 4),
                "room_to_target_r": round(number_value(row.get("room_to_target_r")), 4),
                "check_score": check_score(row),
                "entry": report_value(row.get("planned_entry", "")),
                "stop": report_value(row.get("planned_stop", "")),
                "target": report_value(row.get("planned_target", "")),
                "shares": report_value(size.get("suggested_shares", "")),
                "estimated_risk_dollars": report_value(size.get("estimated_risk_dollars", "")),
                "next_action": next_action,
                "blockers": "; ".join(blockers) if blockers else "",
            }
        )
        if sizing_status == "missing" and rows[-1]["queue_status"] == "ready_for_review":
            rows[-1]["queue_status"] = "blocked_current"
            rows[-1]["priority"] = 2
            rows[-1]["next_action"] = "Wait for position sizing before review."
            rows[-1]["blockers"] = "position sizing row is missing"

    queue = pd.DataFrame(rows, columns=QUEUE_COLUMNS)
    if queue.empty:
        return queue
    queue["_sort_score"] = pd.to_numeric(queue["check_score"], errors="coerce").fillna(0.0)
    queue = queue.sort_values(["priority", "_sort_score", "quality_score"], ascending=[True, False, False])
    return queue.drop(columns=["_sort_score"]).head(20).reset_index(drop=True)


def queue_summary(queue: pd.DataFrame, paper_review: pd.DataFrame, observations: pd.DataFrame) -> dict[str, Any]:
    """Return compact queue progress stats for the app and report."""

    allowed_completed = 0
    if not paper_review.empty and "signal_status" in paper_review.columns:
        allowed_completed = int((paper_review["signal_status"] == "allowed").sum())

    counts = queue.groupby("queue_status").size().to_dict() if not queue.empty else {}
    return {
        "ready_for_review": int(counts.get("ready_for_review", 0)),
        "blocked_current": int(counts.get("blocked_current", 0)),
        "almost_ready": int(counts.get("almost_ready", 0)),
        "waiting": int(counts.get("waiting", 0)),
        "allowed_completed_trades": allowed_completed,
        "remaining_to_30": max(30 - allowed_completed, 0),
        "remaining_to_60": max(60 - allowed_completed, 0),
        "forward_observations": int(len(observations)),
    }


def queue_payload(queue: pd.DataFrame, paper_review: pd.DataFrame, observations: pd.DataFrame) -> dict[str, Any]:
    """Return JSON-safe queue data."""

    summary = queue_summary(queue, paper_review, observations)
    if summary["ready_for_review"]:
        verdict = "Ready candidate waiting for manual paper checklist."
    elif summary["blocked_current"]:
        verdict = "Current signal exists, but it is blocked from paper entry."
    elif summary["almost_ready"]:
        verdict = "No paper entry yet. Watch the near-ready queue."
    else:
        verdict = "No forward paper candidate is ready right now."
    return {
        "summary": summary,
        "verdict": verdict,
        "rows": queue.fillna("").to_dict("records") if not queue.empty else [],
        "guardrail": "Forward queue is read-only. It does not create paper trades or broker orders.",
    }


def write_report(path: Path, queue: pd.DataFrame, payload: dict[str, Any]) -> None:
    """Write the queue Markdown report."""

    ready = queue[queue["queue_status"] == "ready_for_review"] if not queue.empty else pd.DataFrame()
    blocked = queue[queue["queue_status"] == "blocked_current"] if not queue.empty else pd.DataFrame()
    almost = queue[queue["queue_status"] == "almost_ready"] if not queue.empty else pd.DataFrame()
    summary = pd.DataFrame([payload["summary"]])
    path.write_text(
        f"""# Forward Sample Queue

This report shows what is ready, almost ready, or blocked for forward paper
sample collection.

Important: this is research and paper-validation only. It does not create
paper trades, place broker orders, or connect to broker execution.

## Verdict

```text
{payload["verdict"]}
```

## Queue Summary

{markdown_table(summary)}

## Ready For Manual Paper Checklist

{markdown_table(ready)}

## Blocked Current Signals

{markdown_table(blocked)}

## Almost Ready Watchlist

{markdown_table(almost)}

## Files

```text
logs/forward_sample_queue.csv
logs/forward_sample_queue.md
logs/daily_paper_signal_scanner.csv
logs/position_sizing.csv
data/forward_signal_observations.csv
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    paper_review = read_csv_or_empty(args.output_dir / "paper_review_clean_trades.csv")
    observations = read_csv_or_empty(Path("data/forward_signal_observations.csv"))
    queue = build_queue(scanner, sizing, market_refresh_state())
    payload = queue_payload(queue, paper_review, observations)

    csv_path = args.output_dir / "forward_sample_queue.csv"
    report_path = args.output_dir / "forward_sample_queue.md"
    queue.to_csv(csv_path, index=False)
    write_report(report_path, queue, payload)

    summary = payload["summary"]
    print(f"Ready for review: {summary['ready_for_review']}")
    print(f"Almost ready: {summary['almost_ready']}")
    print(f"Remaining to 30 clean samples: {summary['remaining_to_30']}")
    print(f"Saved forward sample queue CSV: {csv_path}")
    print(f"Saved forward sample queue report: {report_path}")


if __name__ == "__main__":
    main()
