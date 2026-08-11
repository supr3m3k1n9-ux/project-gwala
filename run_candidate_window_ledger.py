"""Persist every live current/grace candidate window seen by production scans.

This is a research/paper audit ledger. It records what the existing scanner,
sizer, router, and Paper Gate already decided at scan time. It does not change
strategy logic, thresholds, routing, Paper Gate, Contract Gate, or trade state.
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


LEDGER_COLUMNS = [
    "trade_date",
    "symbol",
    "setup",
    "direction",
    "source_signal_et",
    "candidate_entry_et",
    "freshness_lane",
    "first_seen_at",
    "scan_timestamp",
    "scanner_status",
    "sizing_status",
    "router_status",
    "paper_gate_status",
    "paper_gate_tier",
    "entry",
    "stop",
    "target",
    "size",
    "blocker_reason",
    "latest_candle_et",
    "strategy_id",
    "variant",
    "exit_profile",
    "quality_grade",
    "quality_score",
    "check_score",
    "room_to_target_r",
    "relative_volume",
    "risk_per_share",
    "sizing_reason",
    "router_action",
    "paper_gate_reason",
]
PAPER_VALIDATION_FRESHNESS = {"current_candle", "grace_candle"}
DEDUP_COLUMNS = [
    "trade_date",
    "symbol",
    "setup",
    "direction",
    "source_signal_et",
    "candidate_entry_et",
    "freshness_lane",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append current/grace candidate windows to the durable ledger.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where scanner/gate reports are saved.")
    parser.add_argument(
        "--ledger-csv",
        type=Path,
        default=Path("data/candidate_window_ledger.csv"),
        help="Durable candidate-window ledger CSV.",
    )
    parser.add_argument(
        "--skip-event-dispatch",
        action="store_true",
        help="Write the ledger only. Production runs should leave event dispatch enabled.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV file or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def text(value: object) -> str:
    """Return stable text for maybe-empty values."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number(value: object) -> float | str:
    """Return a float when possible; otherwise an empty string for the ledger."""

    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return float(parsed)


def current_timestamp() -> str:
    """Return the ledger timestamp in market time."""

    return datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def source_signal_time(row: pd.Series | dict[str, Any]) -> str:
    """Return the source signal timestamp used for candidate identity."""

    return text(row.get("source_signal_et")) or text(row.get("latest_signal_et"))


def candidate_entry_time(row: pd.Series | dict[str, Any]) -> str:
    """Return the active candidate entry timestamp used for candidate identity."""

    return text(row.get("candidate_entry_et")) or text(row.get("latest_signal_et"))


def row_identity(row: pd.Series | dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    """Return the stable candidate-window dedupe key."""

    return (
        text(row.get("scan_date") or row.get("trade_date")),
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")),
        source_signal_time(row),
        candidate_entry_time(row),
        text(row.get("signal_freshness") or row.get("freshness_lane")),
    )


def lookup_by_identity(frame: pd.DataFrame) -> dict[tuple[str, str, str, str, str, str, str], pd.Series]:
    """Return rows keyed by the stable candidate-window identity."""

    if frame.empty:
        return {}
    return {row_identity(row): row for _, row in frame.iterrows()}


def sizing_lookup(frame: pd.DataFrame) -> dict[tuple[str, str, str, str, str], pd.Series]:
    """Return sizing rows keyed by the fields emitted by position sizing."""

    if frame.empty:
        return {}
    result: dict[tuple[str, str, str, str, str], pd.Series] = {}
    for _, row in frame.iterrows():
        key = (
            text(row.get("symbol")).upper(),
            text(row.get("setup")),
            text(row.get("direction")),
            candidate_entry_time(row),
            text(row.get("signal_freshness") or row.get("freshness_lane")),
        )
        result[key] = row
    return result


def sizing_key(row: pd.Series) -> tuple[str, str, str, str, str]:
    """Return the key used by position sizing rows."""

    return (
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")),
        candidate_entry_time(row),
        text(row.get("signal_freshness") or row.get("freshness_lane")),
    )


def router_lookup(router: pd.DataFrame) -> dict[tuple[str, str, str, str, str], pd.Series]:
    """Return router rows keyed by scanner row identity."""

    if router.empty:
        return {}
    result: dict[tuple[str, str, str, str, str], pd.Series] = {}
    for _, row in router.iterrows():
        key = (
            text(row.get("symbol")).upper(),
            text(row.get("setup")),
            text(row.get("direction")),
            text(row.get("variant")),
            text(row.get("exit_profile")),
        )
        result[key] = row
    return result


def router_key(row: pd.Series) -> tuple[str, str, str, str, str]:
    """Return the key used by market regime router candidates."""

    return (
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")),
        text(row.get("variant")),
        text(row.get("exit_profile")),
    )


def blocker_reason(scanner: pd.Series, sizing: pd.Series | None, router: pd.Series | None, gate: pd.Series | None) -> str:
    """Return the first useful reason explaining why the row was not promoted."""

    gate_status = text(gate.get("sample_status")) if gate is not None else ""
    if gate_status == "ready_for_validation_sample":
        return ""
    for row, column in [
        (gate, "reason"),
        (sizing, "sizing_reason"),
        (router, "action"),
        (scanner, "missing_conditions"),
        (scanner, "scanner_status"),
    ]:
        if row is not None and text(row.get(column)):
            return text(row.get(column))
    return "No promotion reason was emitted by the current production reports."


def ledger_row(
    scanner: pd.Series,
    *,
    sizing: pd.Series | None,
    router: pd.Series | None,
    gate: pd.Series | None,
    seen_at: str,
) -> dict[str, object]:
    """Build one immutable candidate-window ledger row."""

    return {
        "trade_date": text(scanner.get("scan_date")),
        "symbol": text(scanner.get("symbol")).upper(),
        "setup": text(scanner.get("setup")),
        "direction": text(scanner.get("direction")),
        "source_signal_et": source_signal_time(scanner),
        "candidate_entry_et": candidate_entry_time(scanner),
        "freshness_lane": text(scanner.get("signal_freshness")),
        "first_seen_at": seen_at,
        "scan_timestamp": seen_at,
        "scanner_status": text(scanner.get("scanner_status")),
        "sizing_status": text(sizing.get("sizing_status")) if sizing is not None else "missing",
        "router_status": text(router.get("candidate_route")) if router is not None else "missing",
        "paper_gate_status": text(gate.get("sample_status")) if gate is not None else "missing",
        "paper_gate_tier": text(gate.get("sample_tier")) if gate is not None else "",
        "entry": number(scanner.get("planned_entry")),
        "stop": number(scanner.get("planned_stop")),
        "target": number(scanner.get("planned_target")),
        "size": number(sizing.get("suggested_shares")) if sizing is not None else "",
        "blocker_reason": blocker_reason(scanner, sizing, router, gate),
        "latest_candle_et": text(scanner.get("latest_candle_et")),
        "strategy_id": text(scanner.get("strategy_id")),
        "variant": text(scanner.get("variant")),
        "exit_profile": text(scanner.get("exit_profile")),
        "quality_grade": text(scanner.get("quality_grade")),
        "quality_score": number(scanner.get("quality_score")),
        "check_score": number(gate.get("check_score")) if gate is not None else "",
        "room_to_target_r": number(scanner.get("room_to_target_r")),
        "relative_volume": number(scanner.get("relative_volume")),
        "risk_per_share": number(scanner.get("risk_per_share")),
        "sizing_reason": text(sizing.get("sizing_reason")) if sizing is not None else "",
        "router_action": text(router.get("action")) if router is not None else "",
        "paper_gate_reason": text(gate.get("reason")) if gate is not None else "",
    }


def build_candidate_rows(
    scanner: pd.DataFrame,
    sizing: pd.DataFrame,
    router: pd.DataFrame,
    paper_gate: pd.DataFrame,
    *,
    seen_at: str | None = None,
) -> pd.DataFrame:
    """Build ledger rows from the latest production snapshot."""

    if scanner.empty or "signal_freshness" not in scanner.columns:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    seen_at = seen_at or current_timestamp()
    current_or_grace = scanner[scanner["signal_freshness"].astype(str).isin(PAPER_VALIDATION_FRESHNESS)].copy()
    if current_or_grace.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    sizing_rows = sizing_lookup(sizing)
    gate_rows = lookup_by_identity(paper_gate)
    router_rows = router_lookup(router)
    rows = []
    for _, row in current_or_grace.iterrows():
        identity = row_identity(row)
        rows.append(
            ledger_row(
                row,
                sizing=sizing_rows.get(sizing_key(row)),
                router=router_rows.get(router_key(row)),
                gate=gate_rows.get(identity),
                seen_at=seen_at,
            )
        )
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


def dedupe_ledger(existing: pd.DataFrame, additions: pd.DataFrame) -> pd.DataFrame:
    """Append new candidate windows without rewriting existing history."""

    if existing.empty:
        combined = additions.copy()
    elif additions.empty:
        combined = existing.copy()
    else:
        combined = pd.concat([existing, additions], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    for column in LEDGER_COLUMNS:
        if column not in combined.columns:
            combined[column] = ""
    combined = combined[LEDGER_COLUMNS]
    return combined.drop_duplicates(subset=DEDUP_COLUMNS, keep="first").reset_index(drop=True)


def write_report(output_dir: Path, ledger_csv: Path, additions: pd.DataFrame, ledger: pd.DataFrame) -> Path:
    """Write a small report summarizing the ledger append."""

    output_dir.mkdir(parents=True, exist_ok=True)
    ready_count = int((ledger.get("paper_gate_status", pd.Series(dtype=str)).astype(str) == "ready_for_validation_sample").sum())
    payload = {
        "generated_at_et": current_timestamp(),
        "ledger_csv": str(ledger_csv),
        "new_snapshot_candidate_rows": int(len(additions)),
        "ledger_rows": int(len(ledger)),
        "paper_gate_ready_rows": ready_count,
        "guardrail": (
            "Candidate-window ledger is append-only paper research state. It preserves existing production "
            "decisions and never changes strategy, thresholds, router rules, Paper Gate, Contract Gate, or trades."
        ),
    }
    (output_dir / "candidate_window_ledger.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    preview = ledger.tail(20) if not ledger.empty else pd.DataFrame(columns=LEDGER_COLUMNS)
    path = output_dir / "candidate_window_ledger.md"
    path.write_text(
        f"""# Candidate-Window Ledger

Generated: {payload["generated_at_et"]}

This report preserves every production `current_candle` and `grace_candle`
candidate window seen by the market-hours capture workflow.

## Summary

```text
Ledger CSV: {ledger_csv}
New current/grace rows in latest snapshot: {payload["new_snapshot_candidate_rows"]}
Ledger rows: {payload["ledger_rows"]}
Paper Gate-ready rows preserved: {payload["paper_gate_ready_rows"]}
```

## Latest Ledger Rows

{markdown_table(preview)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )
    return path


def build_ledger(
    output_dir: Path = Path("logs"),
    ledger_csv: Path = Path("data/candidate_window_ledger.csv"),
    *,
    seen_at: str | None = None,
    dispatch_events: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Append the latest current/grace snapshot rows to the durable ledger."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    router = read_csv_or_empty(output_dir / "market_regime_router_candidates.csv")
    paper_gate = read_csv_or_empty(output_dir / "paper_gate_v2.csv")
    additions = build_candidate_rows(scanner, sizing, router, paper_gate, seen_at=seen_at)
    existing = read_csv_or_empty(ledger_csv)
    ledger = dedupe_ledger(existing, additions)
    ledger_csv.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(ledger_csv, index=False)
    write_report(output_dir, ledger_csv, additions, ledger)
    if dispatch_events:
        from run_candidate_ledger_event_dispatcher import build_dispatch

        build_dispatch(output_dir=output_dir, ledger_csv=ledger_csv)
    return ledger, additions


def main() -> None:
    args = parse_args()
    ledger, additions = build_ledger(args.output_dir, args.ledger_csv)
    if not args.skip_event_dispatch:
        from run_candidate_ledger_event_dispatcher import build_dispatch

        build_dispatch(output_dir=args.output_dir, ledger_csv=args.ledger_csv)
    print(f"Candidate-window ledger rows: {len(ledger)}")
    print(f"Current/grace rows in latest snapshot: {len(additions)}")
    print(f"Saved {args.ledger_csv}")


if __name__ == "__main__":
    main()
