"""Audit app feature wiring against the approved/watch playbook.

This is a read-only guardrail report. It checks whether the dashboard-facing
features are using the same symbol universe and whether local candle files are
present for chart/research review. It does not fetch data or place orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols, setup_labels_for_symbol
from run_playbook import markdown_table


WORKSPACE_TIMEFRAMES = ["M1", "M5", "M15", "M30", "M60", "D"]
SIGNAL_TIMEFRAMES = ["M5", "M30"]


def file_state(path: Path) -> dict[str, Any]:
    """Return simple file-state details."""

    if not path.exists():
        return {"exists": False, "modified_et": "", "size_bytes": 0}
    modified = datetime.fromtimestamp(path.stat().st_mtime, MARKET_TZ)
    return {
        "exists": True,
        "modified_et": modified.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "size_bytes": int(path.stat().st_size),
    }


def symbol_rows(data_dir: Path) -> list[dict[str, Any]]:
    """Build per-symbol wiring rows."""

    rows = []
    approved = set(playbook_symbols("approved"))
    watch = set(playbook_symbols("watch"))
    for symbol in playbook_symbols("approved_plus_watch"):
        missing = []
        states = {}
        for timeframe in WORKSPACE_TIMEFRAMES:
            state = file_state(data_dir / f"webull_{symbol}_{timeframe}_candles.csv")
            states[timeframe] = state
            if not state["exists"]:
                missing.append(timeframe)
        status = "approved" if symbol in approved else "watch_more" if symbol in watch else "unknown"
        rows.append(
            {
                "symbol": symbol,
                "status": status,
                "setups": ", ".join(setup_labels_for_symbol(symbol, "approved_plus_watch")),
                "workspace_files": "pass" if not missing else "missing",
                "missing_timeframes": ", ".join(missing) if missing else "none",
                "signal_files": "pass"
                if all(states[timeframe]["exists"] for timeframe in SIGNAL_TIMEFRAMES)
                else "missing",
                "latest_m5_modified_et": states["M5"]["modified_et"],
                "latest_m30_modified_et": states["M30"]["modified_et"],
            }
        )
    return rows


def build_payload(data_dir: Path) -> dict[str, Any]:
    """Build the audit payload."""

    rows = symbol_rows(data_dir)
    missing_symbols = [row["symbol"] for row in rows if row["workspace_files"] != "pass"]
    signal_missing_symbols = [row["symbol"] for row in rows if row["signal_files"] != "pass"]
    status = "pass" if not missing_symbols and not signal_missing_symbols else "warn"
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "approved_symbols": playbook_symbols("approved"),
        "watch_symbols": playbook_symbols("watch"),
        "workspace_symbols": playbook_symbols("approved_plus_watch"),
        "workspace_timeframes": WORKSPACE_TIMEFRAMES,
        "signal_timeframes": SIGNAL_TIMEFRAMES,
        "missing_workspace_symbols": missing_symbols,
        "missing_signal_symbols": signal_missing_symbols,
        "rows": rows,
        "guardrail": "Read-only wiring audit. It never fetches data or places orders.",
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    """Write the audit report."""

    summary = pd.DataFrame(
        [
            {"field": "status", "value": payload["status"]},
            {"field": "approved_symbols", "value": ", ".join(payload["approved_symbols"])},
            {"field": "watch_symbols", "value": ", ".join(payload["watch_symbols"])},
            {"field": "workspace_symbols", "value": ", ".join(payload["workspace_symbols"])},
            {"field": "missing_workspace_symbols", "value": ", ".join(payload["missing_workspace_symbols"]) or "none"},
            {"field": "missing_signal_symbols", "value": ", ".join(payload["missing_signal_symbols"]) or "none"},
        ]
    )
    rows = pd.DataFrame(payload["rows"])
    path.write_text(
        f"""# Feature Wiring Audit

Generated: {payload["generated_at_et"]}

This report checks whether dashboard-facing features are wired to the same
approved/watch symbol universe.

## Summary

{markdown_table(summary)}

## Symbol Wiring

{markdown_table(rows)}

## Guardrail

{payload["guardrail"]}
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit dashboard feature wiring.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull candle CSVs live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.data_dir)
    (args.output_dir / "feature_wiring_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown(args.output_dir / "feature_wiring_audit.md", payload)
    print(f"Wrote {args.output_dir / 'feature_wiring_audit.md'}")


if __name__ == "__main__":
    main()
