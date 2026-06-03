"""Summarize the latest scan into one paper-action digest.

This digest answers: after the most recent scanner run, is there anything for
the user to review, watch, or ignore? It is status-only and never imports paper
trades, places orders, creates broker alerts, or changes strategy rules.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_playbook import markdown_table


ACTION_ORDER = {
    "review_candidate": 1,
    "watch_almost_ready": 2,
    "study_blocker": 3,
    "wait": 4,
    "data_issue": 5,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the latest post-scan candidate digest.")
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


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object when available."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def now_et() -> datetime:
    """Return current New York time."""

    return datetime.now(MARKET_TZ)


def clean_text(value: object) -> str:
    """Return a report-safe string."""

    if pd.isna(value):
        return ""
    return str(value).strip()


def top_queue_rows(queue: pd.DataFrame, status: str, count: int = 3) -> pd.DataFrame:
    """Return the most relevant rows for one queue status."""

    if queue.empty or "queue_status" not in queue.columns:
        return pd.DataFrame()
    rows = queue[queue["queue_status"].eq(status)].copy()
    if rows.empty:
        return rows
    if "check_score" in rows.columns:
        rows["_score"] = pd.to_numeric(rows["check_score"], errors="coerce").fillna(0.0)
        rows = rows.sort_values("_score", ascending=False)
        rows = rows.drop(columns=["_score"])
    keep = [
        "symbol",
        "setup",
        "direction",
        "latest_candle_et",
        "quality_grade",
        "quality_score",
        "check_score",
        "room_to_target_r",
        "next_action",
        "blockers",
    ]
    return rows[[column for column in keep if column in rows.columns]].head(count)


def top_blockers(no_trade: pd.DataFrame, count: int = 5) -> pd.DataFrame:
    """Return the most common missing scanner conditions."""

    if no_trade.empty or "missing_condition_list" not in no_trade.columns:
        return pd.DataFrame(columns=["blocker", "blocked_rows"])

    blockers: dict[str, int] = {}
    for value in no_trade["missing_condition_list"].dropna():
        for blocker in str(value).split(";"):
            text = blocker.strip()
            if text:
                blockers[text] = blockers.get(text, 0) + 1
    if not blockers:
        return pd.DataFrame(columns=["blocker", "blocked_rows"])
    rows = pd.DataFrame(
        [{"blocker": blocker, "blocked_rows": rows} for blocker, rows in blockers.items()]
    ).sort_values("blocked_rows", ascending=False)
    return rows.head(count).reset_index(drop=True)


def closest_setups(no_trade: pd.DataFrame, count: int = 3) -> pd.DataFrame:
    """Return the closest blocked scanner rows."""

    if no_trade.empty:
        return pd.DataFrame()
    rows = no_trade.copy()
    rows["_check_score"] = pd.to_numeric(rows.get("check_score"), errors="coerce").fillna(0.0)
    rows["_quality_score"] = pd.to_numeric(rows.get("quality_score"), errors="coerce").fillna(0.0)
    rows = rows.sort_values(["_check_score", "_quality_score"], ascending=[False, False])
    keep = [
        "symbol",
        "setup",
        "direction",
        "check_score",
        "missing_count",
        "quality_grade",
        "quality_score",
        "relative_volume",
        "room_to_target_r",
        "missing_condition_list",
    ]
    return rows[[column for column in keep if column in rows.columns]].head(count).reset_index(drop=True)


def latest_scan_time(queue: pd.DataFrame, no_trade: pd.DataFrame) -> str:
    """Find the latest candle timestamp represented by the scan artifacts."""

    for frame, column in [(queue, "latest_candle_et"), (no_trade, "latest_candle_et")]:
        if not frame.empty and column in frame.columns:
            values = [clean_text(value) for value in frame[column].dropna()]
            values = [value for value in values if value]
            if values:
                return sorted(values)[-1]
    return ""


def action_from_queue(queue: pd.DataFrame, no_trade: pd.DataFrame, refresh_status: dict[str, Any]) -> tuple[str, str, str]:
    """Return action, headline, and next step for the latest scan."""

    data_status = str(refresh_status.get("status", "") or "").lower()
    if data_status in {"stale", "missing", "error"}:
        return (
            "data_issue",
            "Data freshness needs attention before candidate review.",
            "Refresh Webull data before using scanner output for paper review.",
        )

    counts = queue.groupby("queue_status").size().to_dict() if not queue.empty and "queue_status" in queue.columns else {}
    if int(counts.get("ready_for_review", 0)) > 0:
        return (
            "review_candidate",
            "A current candidate is ready for manual paper review.",
            "Open the checklist/chart, confirm stop and target, then decide whether to log a local paper entry.",
        )
    if int(counts.get("almost_ready", 0)) > 0:
        return (
            "watch_almost_ready",
            "No entry yet, but at least one setup is almost ready.",
            "Watch the next scan and do not force a paper entry before the rules pass.",
        )
    if not no_trade.empty:
        one_rule = int((pd.to_numeric(no_trade.get("missing_count"), errors="coerce") == 1).sum())
        if one_rule > 0:
            return (
                "study_blocker",
                f"No candidate is ready, but {one_rule} setup(s) are one rule away.",
                "Study the blocker pattern and keep collecting shadow evidence; do not loosen rules live.",
            )
    return (
        "wait",
        "No current paper action from the latest scan.",
        "Wait for the next scheduled scan and keep collecting clean evidence.",
    )


def build_digest(output_dir: Path, *, moment: datetime | None = None) -> dict[str, Any]:
    """Build the post-scan digest payload from existing artifacts."""

    current_time = moment or now_et()
    queue = read_csv_or_empty(output_dir / "forward_sample_queue.csv")
    no_trade = read_csv_or_empty(output_dir / "no_trade_blocker_analysis.csv")
    refresh_status = read_json_or_empty(output_dir / "refresh_status.json")
    watchdog = read_json_or_empty(output_dir / "morning_run_watchdog.json")
    action, headline, next_action = action_from_queue(queue, no_trade, refresh_status)
    counts = queue.groupby("queue_status").size().to_dict() if not queue.empty and "queue_status" in queue.columns else {}
    close_count = 0
    if not no_trade.empty and "missing_count" in no_trade.columns:
        close_count = int((pd.to_numeric(no_trade["missing_count"], errors="coerce") == 1).sum())

    return {
        "generated_at_et": current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "latest_scan_time_et": latest_scan_time(queue, no_trade),
        "action": action,
        "action_priority": ACTION_ORDER.get(action, 9),
        "headline": headline,
        "next_action": next_action,
        "watchdog_status": watchdog.get("status", "missing"),
        "refresh_status": refresh_status.get("status", "missing"),
        "summary": {
            "ready_for_review": int(counts.get("ready_for_review", 0)),
            "blocked_current": int(counts.get("blocked_current", 0)),
            "almost_ready": int(counts.get("almost_ready", 0)),
            "waiting": int(counts.get("waiting", 0)),
            "one_rule_from_passing": close_count,
        },
        "ready_rows": top_queue_rows(queue, "ready_for_review").fillna("").to_dict("records"),
        "almost_ready_rows": top_queue_rows(queue, "almost_ready").fillna("").to_dict("records"),
        "blocked_current_rows": top_queue_rows(queue, "blocked_current").fillna("").to_dict("records"),
        "closest_setups": closest_setups(no_trade).fillna("").to_dict("records"),
        "top_blockers": top_blockers(no_trade).fillna("").to_dict("records"),
        "guardrail": (
            "Post-scan digest is status-only. It does not import paper trades, "
            "place orders, create broker alerts, or change scanner rules."
        ),
    }


def rows_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a JSON row list to a display frame."""

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def write_report(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports for the digest."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "post_scan_digest.json"
    md_path = output_dir / "post_scan_digest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = pd.DataFrame([payload["summary"]])
    md_path.write_text(
        f"""# Post-Scan Candidate Digest

This report summarizes the latest scanner pass into one paper-action decision.

Important: this is research and paper-validation only. It does not import
paper trades, place broker orders, create broker alerts, or change scanner
rules.

## Action

```text
{payload["action"]}: {payload["headline"]}
```

## Next Action

```text
{payload["next_action"]}
```

## Scan Context

```text
Generated: {payload["generated_at_et"]}
Latest scan candle: {payload["latest_scan_time_et"] or "unknown"}
Morning watchdog: {payload["watchdog_status"]}
Refresh status: {payload["refresh_status"]}
```

## Summary

{markdown_table(summary)}

## Ready For Manual Paper Review

{markdown_table(rows_to_frame(payload["ready_rows"]))}

## Almost Ready

{markdown_table(rows_to_frame(payload["almost_ready_rows"]))}

## Blocked Current Signals

{markdown_table(rows_to_frame(payload["blocked_current_rows"]))}

## Closest Blocked Setups

{markdown_table(rows_to_frame(payload["closest_setups"]))}

## Top Blockers

{markdown_table(rows_to_frame(payload["top_blockers"]))}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
logs/post_scan_digest.json
logs/post_scan_digest.md
logs/forward_sample_queue.csv
logs/no_trade_blocker_analysis.csv
logs/refresh_status.json
logs/morning_run_watchdog.json
```
""",
        encoding="utf-8",
    )
    return json_path, md_path


def main() -> None:
    args = parse_args()
    payload = build_digest(args.output_dir)
    json_path, md_path = write_report(payload, args.output_dir)
    print(f"Saved post-scan digest JSON: {json_path}")
    print(f"Saved post-scan digest report: {md_path}")


if __name__ == "__main__":
    main()
