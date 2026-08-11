"""Track near-ready rows without promoting them to official paper trades.

Probation watch is for rows that deserve attention on the next scan but still
failed the real paper gate. It creates a small evidence ledger and keeps those
rows out of the 30 official paper-trade count.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_playbook import markdown_table


TRACKED_ACTIONS = {
    "paper_watch_if_next_scan_confirms": "watch_next_fresh_scan",
    "soften_for_shadow_only": "shadow_only_probe",
    "collect_more_evidence": "evidence_probe",
}
LEDGER_COLUMNS = [
    "first_seen_et",
    "last_seen_et",
    "symbol",
    "setup",
    "direction",
    "latest_candle_et",
    "action",
    "probation_status",
    "check_score_pct",
    "quality",
    "relative_volume",
    "room_to_target_r",
    "core_blockers",
    "reason",
    "counts_toward_30",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build probation-watch tracking.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/probation_watch_observations.csv"),
        help="Long-running probation-watch ledger.",
    )
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV if it exists."""

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


def queue_lookup(queue: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Return latest queue details keyed by symbol/setup/direction."""

    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    if queue.empty:
        return lookup
    for _, row in queue.iterrows():
        key = (
            str(row.get("symbol", "")).upper(),
            str(row.get("setup", "")),
            str(row.get("direction", "")),
        )
        lookup[key] = row.to_dict()
    return lookup


def build_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Build current probation rows from almost-ready breakout."""

    breakout = read_json_or_empty(output_dir / "almost_ready_breakout.json")
    queue = read_csv_or_empty(output_dir / "forward_sample_queue.csv")
    details = queue_lookup(queue)
    rows = breakout.get("rows", [])
    if not isinstance(rows, list):
        return []

    probation_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action", ""))
        if action not in TRACKED_ACTIONS:
            continue
        key = (
            str(row.get("symbol", "")).upper(),
            str(row.get("setup", "")),
            str(row.get("direction", "")),
        )
        queue_row = details.get(key, {})
        probation_rows.append(
            {
                "symbol": key[0],
                "setup": key[1],
                "direction": key[2],
                "latest_candle_et": str(queue_row.get("latest_candle_et", "")),
                "scanner_status": str(queue_row.get("scanner_status", "")),
                "signal_freshness": str(queue_row.get("signal_freshness", "")),
                "action": action,
                "probation_status": TRACKED_ACTIONS[action],
                "check_score_pct": row.get("check_score_pct", ""),
                "quality": row.get("quality", ""),
                "relative_volume": row.get("relative_volume", ""),
                "room_to_target_r": row.get("room_to_target_r", ""),
                "core_blockers": row.get("core_blockers", ""),
                "reason": row.get("reason", ""),
                "next_confirmation_needed": "fresh current-candle scanner pass with normal sizing/checklist gates",
                "counts_toward_30": False,
            }
        )
    return probation_rows


def append_ledger(ledger_path: Path, rows: list[dict[str, Any]], now_text: str) -> tuple[pd.DataFrame, int]:
    """Append non-duplicate probation rows to the long-running ledger."""

    existing = read_csv_or_empty(ledger_path, LEDGER_COLUMNS)
    new_rows = []
    existing_keys = set()
    if not existing.empty:
        for _, row in existing.iterrows():
            existing_keys.add(
                (
                    str(row.get("symbol", "")).upper(),
                    str(row.get("setup", "")),
                    str(row.get("direction", "")),
                    str(row.get("latest_candle_et", "")),
                    str(row.get("action", "")),
                )
            )

    for row in rows:
        key = (
            str(row.get("symbol", "")).upper(),
            str(row.get("setup", "")),
            str(row.get("direction", "")),
            str(row.get("latest_candle_et", "")),
            str(row.get("action", "")),
        )
        if key in existing_keys:
            if not existing.empty:
                mask = (
                    existing["symbol"].astype(str).str.upper().eq(key[0])
                    & existing["setup"].astype(str).eq(key[1])
                    & existing["direction"].astype(str).eq(key[2])
                    & existing["latest_candle_et"].astype(str).eq(key[3])
                    & existing["action"].astype(str).eq(key[4])
                )
                existing.loc[mask, "last_seen_et"] = now_text
            continue
        new_rows.append(
            {
                "first_seen_et": now_text,
                "last_seen_et": now_text,
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "latest_candle_et": row.get("latest_candle_et", ""),
                "action": row.get("action", ""),
                "probation_status": row.get("probation_status", ""),
                "check_score_pct": row.get("check_score_pct", ""),
                "quality": row.get("quality", ""),
                "relative_volume": row.get("relative_volume", ""),
                "room_to_target_r": row.get("room_to_target_r", ""),
                "core_blockers": row.get("core_blockers", ""),
                "reason": row.get("reason", ""),
                "counts_toward_30": False,
            }
        )
        existing_keys.add(key)

    combined = existing
    if new_rows:
        combined = pd.concat([existing, pd.DataFrame(new_rows, columns=LEDGER_COLUMNS)], ignore_index=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(ledger_path, index=False)
    return combined, len(new_rows)


def build_payload(output_dir: Path, ledger_path: Path = Path("data/probation_watch_observations.csv")) -> dict[str, Any]:
    """Build probation-watch payload and update the ledger."""

    now_text = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    rows = build_rows(output_dir)
    ledger, appended = append_ledger(ledger_path, rows, now_text)
    counts = pd.Series([row["probation_status"] for row in rows]).value_counts().to_dict() if rows else {}
    payload = {
        "generated_at_et": now_text,
        "status": "watch" if rows else "empty",
        "current_probation_rows": int(len(rows)),
        "new_ledger_rows": int(appended),
        "ledger_rows": int(len(ledger)),
        "summary": {str(key): int(value) for key, value in counts.items()},
        "rows": rows,
        "ledger_path": str(ledger_path),
        "next_action": (
            "Watch these rows only if the next scan creates a fresh current-candle pass. They are not official paper trades."
            if rows
            else "No probation rows right now. Keep normal scans running."
        ),
        "guardrail": (
            "Probation watch is evidence tracking only. Rows never count toward the 30 official paper trades "
            "unless a later fresh scanner pass is manually reviewed and logged through the normal paper process."
        ),
    }
    return payload


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown outputs."""

    rows = pd.DataFrame(payload["rows"])
    (output_dir / "probation_watch.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    rows.to_csv(output_dir / "probation_watch.csv", index=False)
    summary = pd.DataFrame([payload["summary"]]) if payload["summary"] else pd.DataFrame()
    (output_dir / "probation_watch.md").write_text(
        f"""# Probation Watch

Generated: {payload["generated_at_et"]}

Status: `{payload["status"]}`

This tracks near-ready rows that may deserve a closer next scan, while keeping
the official paper-trade count clean.

## Summary

{markdown_table(summary)}

## Current Probation Rows

{markdown_table(rows)}

## Next Action

```text
{payload["next_action"]}
```

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.output_dir, args.ledger)
    write_outputs(args.output_dir, payload)
    print(f"Probation rows: {payload['current_probation_rows']}")
    print(f"Saved {args.output_dir / 'probation_watch.md'}")


if __name__ == "__main__":
    main()
