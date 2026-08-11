"""Preflight a small wider universe without enabling it for paper trading.

The goal is faster evidence discovery, not looser validation. This report only
checks whether a few expansion symbols have clean, current local candles before
they are considered for shadow scanning.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols
from data.candle_cache import preferred_candle_path
from run_playbook import markdown_table


CONTROLLED_EXPANSION_SYMBOLS = ["DIA", "IWM", "AMZN", "NFLX"]
REQUIRED_TIMEFRAMES = ["M30", "M5"]
CANDLE_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build controlled universe expansion preflight.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Main logs directory.")
    parser.add_argument(
        "--expansion-dir",
        type=Path,
        default=None,
        help="Expansion data directory. Defaults to <output-dir>/universe_expansion.",
    )
    return parser.parse_args()


def read_candles(path: Path) -> pd.DataFrame:
    """Read a candle CSV with or without headers."""

    if not path.exists():
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0:1]
    has_header = bool(first_line and "datetime" in first_line[0].lower())
    try:
        if has_header:
            frame = pd.read_csv(path)
        else:
            frame = pd.read_csv(path, header=None, names=CANDLE_COLUMNS)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    if "datetime" not in frame.columns:
        frame.columns = CANDLE_COLUMNS[: len(frame.columns)]
    return frame


def latest_candle_et(path: Path) -> tuple[str, str]:
    """Return latest candle timestamp and freshness status."""

    frame = read_candles(path)
    if frame.empty or "datetime" not in frame.columns:
        return "", "missing"
    parsed = pd.to_datetime(frame["datetime"], errors="coerce", utc=True).dropna()
    if parsed.empty:
        return "", "unparseable"
    latest = parsed.max().tz_convert(MARKET_TZ)
    today = datetime.now(MARKET_TZ).date()
    status = "current_session" if latest.date() == today else "stale"
    return latest.strftime("%Y-%m-%d %H:%M:%S %Z"), status


def candle_path_for(output_dir: Path, expansion_dir: Path, symbol: str, timeframe: str) -> Path:
    """Prefer expansion data, then fall back to the main cache for inspection only."""

    expansion_path = preferred_candle_path(expansion_dir, symbol, timeframe)
    if expansion_path.exists():
        return expansion_path
    return preferred_candle_path(output_dir, symbol, timeframe)


def symbol_row(output_dir: Path, expansion_dir: Path, symbol: str) -> dict[str, Any]:
    """Build one expansion preflight row."""

    approved_symbols = set(playbook_symbols("approved_plus_watch"))
    statuses: dict[str, str] = {}
    latest_values: dict[str, str] = {}
    paths: dict[str, str] = {}
    for timeframe in REQUIRED_TIMEFRAMES:
        path = candle_path_for(output_dir, expansion_dir, symbol, timeframe)
        latest, status = latest_candle_et(path)
        statuses[timeframe] = status
        latest_values[timeframe] = latest
        paths[timeframe] = str(path)

    if symbol in approved_symbols:
        status = "already_in_active_universe"
        action = "Do not treat this as expansion; it is already part of approved/watch scanning."
    elif any(statuses[timeframe] == "missing" for timeframe in REQUIRED_TIMEFRAMES):
        status = "needs_data_refresh"
        action = "Refresh expansion candles before any shadow scan."
    elif any(statuses[timeframe] in {"stale", "unparseable"} for timeframe in REQUIRED_TIMEFRAMES):
        status = "stale_data"
        action = "Do not use old expansion rows. Refresh M30 and M5 candles first."
    else:
        status = "ready_for_shadow_scan"
        action = "Eligible for shadow-only expansion review after manual approval."

    return {
        "symbol": symbol,
        "status": status,
        "m30_status": statuses["M30"],
        "m30_latest_et": latest_values["M30"],
        "m5_status": statuses["M5"],
        "m5_latest_et": latest_values["M5"],
        "active_scanner_enabled": False,
        "counts_toward_30": False,
        "action": action,
        "m30_path": paths["M30"],
        "m5_path": paths["M5"],
    }


def build_payload(output_dir: Path, expansion_dir: Path | None = None) -> dict[str, Any]:
    """Build the controlled expansion payload."""

    expansion_dir = expansion_dir or output_dir / "universe_expansion"
    rows = [symbol_row(output_dir, expansion_dir, symbol) for symbol in CONTROLLED_EXPANSION_SYMBOLS]
    status_counts = pd.Series([row["status"] for row in rows]).value_counts().to_dict() if rows else {}
    ready_count = int(status_counts.get("ready_for_shadow_scan", 0))
    blocked_count = len(rows) - ready_count
    overall_status = "ready_for_shadow_review" if ready_count and not blocked_count else "blocked_until_refresh" if blocked_count else "empty"
    payload = {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": overall_status,
        "symbols": CONTROLLED_EXPANSION_SYMBOLS,
        "required_timeframes": REQUIRED_TIMEFRAMES,
        "ready_for_shadow_scan": ready_count,
        "blocked_or_stale": blocked_count,
        "summary": {str(key): int(value) for key, value in status_counts.items()},
        "rows": rows,
        "next_action": (
            "Refresh expansion candles, then rerun this preflight before adding any symbol to shadow scans."
            if blocked_count
            else "Expansion symbols are clean enough for shadow-only review; manual approval is still required before scanner wiring."
        ),
        "guardrail": (
            "Controlled expansion is preflight-only. It does not add symbols to active scanning, "
            "does not count toward the 30 official paper trades, and does not enable broker execution."
        ),
    }
    return payload


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON, CSV, and Markdown outputs."""

    rows = pd.DataFrame(payload["rows"])
    (output_dir / "controlled_universe_expansion.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    rows.to_csv(output_dir / "controlled_universe_expansion.csv", index=False)
    summary = pd.DataFrame([payload["summary"]]) if payload["summary"] else pd.DataFrame()
    (output_dir / "controlled_universe_expansion.md").write_text(
        f"""# Controlled Universe Expansion

Generated: {payload["generated_at_et"]}

Status: `{payload["status"]}`

This preflight keeps the wider symbol idea separate from official paper
validation until the candle files are current and manually approved.

## Summary

{markdown_table(summary)}

## Symbols

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
    payload = build_payload(args.output_dir, args.expansion_dir)
    write_outputs(args.output_dir, payload)
    print(f"Controlled expansion status: {payload['status']}")
    print(f"Saved {args.output_dir / 'controlled_universe_expansion.md'}")


if __name__ == "__main__":
    main()
