"""Build a pre-entry review gate for local paper candidates.

This report hardens the last step before a local paper entry is logged. It
joins scanner rows, position sizing, refresh state, strategy selector, and risk
guard context into one explicit checklist.

Important: this is local paper validation only. It does not place orders,
create broker alerts, connect to Webull execution, or approve real-money trades.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from reports.refresh_status import market_refresh_state
from reports.system_state import data_freshness_state, market_state, paper_state, risk_guard_state
from run_paper_import import paper_import_is_allowed
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pre-entry paper review gate.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"), help="Paper trade log.")
    parser.add_argument(
        "--refresh-audit-csv",
        type=Path,
        default=Path("data/market_refresh_audit.csv"),
        help="Refresh evidence required before paper review.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read JSON or return an empty dict."""

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def text_value(value: object) -> str:
    """Return stable text from a maybe-empty value."""

    if value is None or pd.isna(value):
        return ""
    return str(value)


def matching_size(row: pd.Series, sizing: pd.DataFrame) -> pd.Series:
    """Return the matching position-size row for a scanner row."""

    if sizing.empty:
        return pd.Series(dtype=object)
    matches = sizing[
        (sizing["symbol"].astype(str) == text_value(row.get("symbol")))
        & (sizing["setup"].astype(str) == text_value(row.get("setup")))
        & (sizing["direction"].astype(str) == text_value(row.get("direction")))
    ]
    return matches.iloc[0] if not matches.empty else pd.Series(dtype=object)


def review_row(
    row: pd.Series,
    sizing: pd.DataFrame,
    *,
    data_fresh: bool,
    import_allowed: bool,
    import_reason: str,
    selector: dict[str, Any],
    risk_guard: dict[str, Any],
) -> dict[str, Any]:
    """Build one pre-entry checklist row."""

    size = matching_size(row, sizing)
    scanner_allowed = text_value(row.get("scanner_status")) == "allowed"
    current_candle = text_value(row.get("signal_freshness")) == "current_candle"
    sizing_ok = text_value(size.get("sizing_status")) == "size_ok"
    plan_complete = all(text_value(row.get(column)) for column in ["planned_entry", "planned_stop", "planned_target"])
    shares = pd.to_numeric(size.get("suggested_shares", 0), errors="coerce")
    shares_ready = bool(not pd.isna(shares) and float(shares) > 0)
    strategy_mode = text_value(selector.get("mode"))
    strategy_ok = strategy_mode in {"paper_watch_allowed", "selective_watch", "stand_aside"}
    risk_ok = text_value(risk_guard.get("status")) not in {"daily_stop_hit", "monthly_stop_hit"}

    blockers = []
    if not scanner_allowed:
        blockers.append("Scanner did not mark this candidate allowed.")
    if not current_candle:
        blockers.append("Signal is not current_candle.")
    if not data_fresh:
        blockers.append("Scanner data is not fresh for today.")
    if not sizing_ok:
        blockers.append(text_value(size.get("sizing_reason")) or "Position sizing is not size_ok.")
    if not import_allowed:
        blockers.append(import_reason)
    if not plan_complete:
        blockers.append("Entry, stop, or target is missing.")
    if not shares_ready:
        blockers.append("Suggested shares are missing or zero.")
    if not strategy_ok:
        blockers.append("Strategy selector has no paper-watch lane available.")
    if not risk_ok:
        blockers.append(text_value(risk_guard.get("message")) or "Risk guard blocks new entries.")

    return {
        "symbol": text_value(row.get("symbol")),
        "setup": text_value(row.get("setup")),
        "direction": text_value(row.get("direction")),
        "signal_time_et": text_value(row.get("latest_signal_et")),
        "scanner_status": text_value(row.get("scanner_status")),
        "signal_freshness": text_value(row.get("signal_freshness")),
        "sizing_status": text_value(size.get("sizing_status")) or "missing",
        "suggested_shares": int(float(shares)) if not pd.isna(shares) else 0,
        "strategy_selector_mode": strategy_mode or "missing",
        "risk_guard_status": text_value(risk_guard.get("status")) or "missing",
        "review_status": "ready_for_manual_review" if not blockers else "blocked",
        "blocker_count": len(blockers),
        "blockers": " ".join(blockers),
    }


def build_review(output_dir: Path, paper_csv: Path, refresh_audit_csv: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Build the pre-entry review payload and rows."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    refresh_audit = read_csv_or_empty(refresh_audit_csv)
    paper_log = read_csv_or_empty(paper_csv)
    paper_review = read_csv_or_empty(output_dir / "paper_review_clean_trades.csv")
    strategy_vault = read_json_or_empty(output_dir / "strategy_vault.json")
    market = market_refresh_state()
    dashboard_market = market_state()
    freshness = data_freshness_state(scanner, dashboard_market)
    paper = paper_state(paper_log, paper_review)
    risk_guard = risk_guard_state(paper)
    selector = strategy_vault.get("selector", {}) if isinstance(strategy_vault.get("selector", {}), dict) else {}

    if scanner.empty:
        rows = pd.DataFrame()
    else:
        candidates = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"].isin(["current_candle", "earlier_today"]))
        ].copy()
        import_allowed, import_reason = paper_import_is_allowed(
            scanner,
            ["allowed"],
            "current_candle",
            market,
            refresh_audit,
        )
        rows = pd.DataFrame(
            [
                review_row(
                    row,
                    sizing,
                    data_fresh=freshness["data_status"] == "fresh_for_today",
                    import_allowed=import_allowed,
                    import_reason=import_reason,
                    selector=selector,
                    risk_guard=risk_guard,
                )
                for _, row in candidates.iterrows()
            ]
        )

    ready_count = int((rows["review_status"] == "ready_for_manual_review").sum()) if not rows.empty else 0
    blocked_count = int((rows["review_status"] == "blocked").sum()) if not rows.empty else 0
    payload = {
        "ready_for_manual_review": ready_count,
        "blocked_candidates": blocked_count,
        "candidate_count": int(len(rows)),
        "strategy_selector_mode": text_value(selector.get("mode")) or "missing",
        "risk_guard_status": text_value(risk_guard.get("status")) or "missing",
        "next_action": (
            "A candidate passed the pre-entry review gate. Manual chart review is still required before logging local paper."
            if ready_count
            else "No candidate passed the pre-entry review gate. Do not log a local paper entry."
        ),
        "guardrail": "Pre-entry ready means manual local paper review only. No broker orders or alerts are created.",
    }
    return payload, rows


def write_outputs(output_dir: Path, payload: dict[str, Any], rows: pd.DataFrame) -> None:
    """Write pre-entry review outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "pre_entry_review.json"
    csv_path = output_dir / "pre_entry_review.csv"
    md_path = output_dir / "pre_entry_review.md"
    json_path.write_text(json.dumps({**payload, "rows": rows.to_dict("records")}, indent=2), encoding="utf-8")
    rows.to_csv(csv_path, index=False)
    status = rows.groupby("review_status").size().reset_index(name="candidates") if not rows.empty else pd.DataFrame()
    md_path.write_text(
        f"""# Pre-Entry Review Gate

This report hardens the final review step before a local paper entry is logged.

Important: this is local paper validation only. It does not place broker
orders, create broker alerts, connect to Webull execution, or approve
real-money trades.

## Summary

```text
Candidates reviewed: {payload["candidate_count"]}
Ready for manual review: {payload["ready_for_manual_review"]}
Blocked candidates: {payload["blocked_candidates"]}
Strategy selector mode: {payload["strategy_selector_mode"]}
Risk guard status: {payload["risk_guard_status"]}
Next action: {payload["next_action"]}
```

## Status Counts

{markdown_table(status)}

## Candidate Checklist

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
{json_path}
{csv_path}
{md_path}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload, rows = build_review(args.output_dir, args.paper_csv, args.refresh_audit_csv)
    write_outputs(args.output_dir, payload, rows)
    print(f"Pre-entry candidates reviewed: {payload['candidate_count']}")
    print(f"Ready for manual review: {payload['ready_for_manual_review']}")
    print(f"Saved pre-entry review report: {args.output_dir / 'pre_entry_review.md'}")


if __name__ == "__main__":
    main()
