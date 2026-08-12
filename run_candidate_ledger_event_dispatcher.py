"""Dispatch Contract Gate work from durable Candidate Ledger events.

This is a Gate 1 orchestration layer. It treats the Candidate Ledger as the
event source for preserved A-tier current-candle candidates, then runs the
existing option-chain import, option review, Contract Gate, and autonomous
lifecycle path exactly once per eligible ledger row.

It does not change scanner logic, Paper Gate rules, Contract Gate thresholds,
option-chain provenance checks, lifecycle safety checks, or duplicate
prevention.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.filter_policy import OPTIONS_CONTRACT_THRESHOLDS
from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from reports.refresh_status import market_refresh_state
from run_autonomous_a_tier_lifecycle import build_lifecycle as build_autonomous_lifecycle
from run_autonomous_a_tier_lifecycle import write_outputs as write_autonomous_lifecycle_outputs
from run_option_chain_import import build_import as build_option_chain_import
from run_option_chain_import import write_outputs as write_option_chain_import_outputs
from run_options_chain_review import build_payload as build_options_chain_review
from run_options_chain_review import write_outputs as write_options_chain_review_outputs
from run_options_contract_gate import build_gate as build_options_contract_gate
from run_options_contract_gate import write_outputs as write_options_contract_gate_outputs
from run_playbook import markdown_table


EVENT_STATE_COLUMNS = [
    "event_key",
    "trade_date",
    "candidate_entry_et",
    "symbol",
    "setup",
    "direction",
    "status",
    "reason",
    "first_detected_at_et",
    "dispatch_started_at_et",
    "option_chain_import_at_et",
    "option_chain_review_at_et",
    "contract_gate_at_et",
    "lifecycle_at_et",
    "completed_at_et",
    "option_chain_import_status",
    "options_chain_review_status",
    "contract_gate_status",
    "contract_passed_count",
    "lifecycle_status",
    "lifecycle_reason",
    "paper_orders_written",
    "open_paper_trades_written",
    "validation_rows_written",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch Candidate Ledger Contract Gate events.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"))
    parser.add_argument("--ledger-csv", type=Path, default=runtime_data_path("candidate_window_ledger.csv"))
    parser.add_argument("--event-state-csv", type=Path, default=runtime_data_path("candidate_ledger_event_state.csv"))
    parser.add_argument("--chain-dir", type=Path, default=runtime_data_path("options_chains", "active"))
    parser.add_argument("--contract-audit-csv", type=Path, default=runtime_data_path("options_contract_audit.csv"))
    parser.add_argument("--samples-csv", type=Path, default=runtime_data_path("paper_validation_samples.csv"))
    parser.add_argument("--account-size", type=float, default=10_000.0)
    parser.add_argument("--max-chain-age-minutes", type=float, default=20.0)
    return parser.parse_args()


def now_et() -> datetime:
    return datetime.now(tz=MARKET_TZ)


def timestamp(moment: datetime | None = None) -> str:
    return (moment or now_et()).strftime("%Y-%m-%d %H:%M:%S %Z")


def read_csv_or_empty(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
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


def text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def truthy(value: object) -> bool:
    return text(value).lower() in {"1", "true", "yes", "y"}


def event_key(row: pd.Series | dict[str, Any]) -> str:
    return "|".join(
        [
            text(row.get("trade_date")),
            text(row.get("source_signal_et")),
            text(row.get("candidate_entry_et")),
            text(row.get("symbol")).upper(),
            text(row.get("setup")).lower(),
            text(row.get("direction")).lower(),
            text(row.get("freshness_lane")).lower(),
        ]
    )


def event_row_base(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    return {
        "event_key": event_key(row),
        "trade_date": text(row.get("trade_date")),
        "candidate_entry_et": text(row.get("candidate_entry_et")),
        "symbol": text(row.get("symbol")).upper(),
        "setup": text(row.get("setup")),
        "direction": text(row.get("direction")).lower(),
    }


def eligible_candidate_events(ledger: pd.DataFrame, market: dict[str, Any]) -> pd.DataFrame:
    """Return unprocessed same-session A/current ready candidates."""

    if ledger.empty:
        return pd.DataFrame(columns=list(ledger.columns))
    today = text(market.get("today")) or now_et().date().isoformat()
    required = {
        "trade_date",
        "paper_gate_tier",
        "paper_gate_status",
        "freshness_lane",
        "candidate_entry_et",
        "symbol",
        "setup",
        "direction",
    }
    if not required.issubset(set(ledger.columns)):
        return pd.DataFrame(columns=list(ledger.columns))
    frame = ledger.copy()
    mask = (
        frame["trade_date"].astype(str).eq(today)
        & frame["paper_gate_tier"].astype(str).str.upper().eq("A")
        & frame["paper_gate_status"].astype(str).eq("ready_for_validation_sample")
        & frame["freshness_lane"].astype(str).eq("current_candle")
    )
    return frame[mask].copy()


def processed_event_keys(state: pd.DataFrame) -> set[str]:
    if state.empty or "event_key" not in state.columns:
        return set()
    terminal = state["status"].astype(str).isin(["completed", "blocked_market_closed"])
    return set(state[terminal]["event_key"].astype(str))


def lifecycle_write_count(payload: dict[str, Any]) -> int:
    """Return how many official local-paper artifacts lifecycle wrote."""

    return int(payload.get("paper_orders_written", 0) or 0) + int(payload.get("open_paper_trades_written", 0) or 0) + int(
        payload.get("validation_rows_written", 0) or 0
    )


def lifecycle_block_reason(payload: dict[str, Any]) -> str:
    """Return the first lifecycle row reason when no write happened."""

    rows = payload.get("rows", [])
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and text(row.get("reason")):
                return text(row.get("reason"))
    return "lifecycle wrote no paper-validation artifacts"


def append_state(path: Path, rows: list[dict[str, Any]]) -> pd.DataFrame:
    existing = read_csv_or_empty(path, EVENT_STATE_COLUMNS)
    if rows:
        new_rows = pd.DataFrame(rows, columns=EVENT_STATE_COLUMNS)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = existing
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return combined


def review_args(
    *,
    output_dir: Path,
    chain_dir: Path,
    contract_audit_csv: Path,
    samples_csv: Path,
    candidate_ledger_csv: Path,
    account_size: float,
    max_chain_age_minutes: float,
) -> argparse.Namespace:
    return argparse.Namespace(
        output_dir=output_dir,
        chain_csv=None,
        chain_dir=chain_dir,
        symbol=None,
        tier=["A"],
        max_dte=OPTIONS_CONTRACT_THRESHOLDS["max_dte"],
        contract_audit_csv=contract_audit_csv,
        write_audit=True,
        allow_missing_option_type=False,
        samples_csv=samples_csv,
        candidate_ledger_csv=candidate_ledger_csv,
        account_size=account_size,
        max_chain_age_minutes=max_chain_age_minutes,
    )


def dispatch_event(
    row: pd.Series,
    *,
    output_dir: Path,
    ledger_csv: Path,
    chain_dir: Path,
    contract_audit_csv: Path,
    samples_csv: Path,
    account_size: float,
    max_chain_age_minutes: float,
    market: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one Candidate Ledger event through the existing downstream gates."""

    event_time = now or now_et()
    state = {
        **event_row_base(row),
        "status": "started",
        "reason": "",
        "first_detected_at_et": text(row.get("first_seen_at")),
        "dispatch_started_at_et": timestamp(event_time),
        "option_chain_import_at_et": "",
        "option_chain_review_at_et": "",
        "contract_gate_at_et": "",
        "lifecycle_at_et": "",
        "completed_at_et": "",
        "option_chain_import_status": "",
        "options_chain_review_status": "",
        "contract_gate_status": "",
        "contract_passed_count": 0,
        "lifecycle_status": "",
        "lifecycle_reason": "",
        "paper_orders_written": 0,
        "open_paper_trades_written": 0,
        "validation_rows_written": 0,
    }
    if not bool(market.get("market_is_open", False)):
        state.update(
            {
                "status": "blocked_market_closed",
                "reason": "market is closed",
                "completed_at_et": timestamp(event_time),
            }
        )
        return state

    try:
        import_payload = build_option_chain_import(
            output_dir=output_dir,
            chain_dir=chain_dir,
            samples_csv=samples_csv,
            candidate_ledger_csv=ledger_csv,
            account_size=account_size,
        )
        write_option_chain_import_outputs(output_dir, import_payload)
        state["option_chain_import_at_et"] = timestamp()
        state["option_chain_import_status"] = text(import_payload.get("status"))

        review_payload = build_options_chain_review(
            review_args(
                output_dir=output_dir,
                chain_dir=chain_dir,
                contract_audit_csv=contract_audit_csv,
                samples_csv=samples_csv,
                candidate_ledger_csv=ledger_csv,
                account_size=account_size,
                max_chain_age_minutes=max_chain_age_minutes,
            )
        )
        write_options_chain_review_outputs(output_dir, review_payload)
        state["option_chain_review_at_et"] = timestamp()
        state["options_chain_review_status"] = text(review_payload.get("status"))

        gate_payload = build_options_contract_gate(
            output_dir=output_dir,
            contract_audit_csv=contract_audit_csv,
            samples_csv=samples_csv,
            candidate_ledger_csv=ledger_csv,
            account_size=account_size,
        )
        write_options_contract_gate_outputs(output_dir, gate_payload)
        state["contract_gate_at_et"] = timestamp()
        state["contract_gate_status"] = text(gate_payload.get("status"))
        state["contract_passed_count"] = int(gate_payload.get("passed_contract_count", 0) or 0)

        if int(gate_payload.get("passed_contract_count", 0) or 0) > 0:
            lifecycle_payload = build_autonomous_lifecycle(
                output_dir=output_dir,
                contract_audit_csv=contract_audit_csv,
                samples_csv=samples_csv,
                candidate_ledger_csv=ledger_csv,
                account_size=account_size,
                option_chain_dir=chain_dir,
                now=event_time,
            )
            write_autonomous_lifecycle_outputs(output_dir, lifecycle_payload)
            state["lifecycle_at_et"] = timestamp()
            state["lifecycle_status"] = text(lifecycle_payload.get("mode")) or "ran"
            state["lifecycle_reason"] = lifecycle_block_reason(lifecycle_payload)
            state["paper_orders_written"] = int(lifecycle_payload.get("paper_orders_written", 0) or 0)
            state["open_paper_trades_written"] = int(lifecycle_payload.get("open_paper_trades_written", 0) or 0)
            state["validation_rows_written"] = int(lifecycle_payload.get("validation_rows_written", 0) or 0)
            if lifecycle_write_count(lifecycle_payload) <= 0:
                duplicate_reasons = {
                    text(row.get("reason"))
                    for row in lifecycle_payload.get("rows", [])
                    if isinstance(row, dict)
                }
                if duplicate_reasons == {"blocked_duplicate"}:
                    state["status"] = "completed"
                    state["reason"] = "duplicate lifecycle artifact already exists"
                else:
                    state["status"] = "retry_pending"
                    state["reason"] = state["lifecycle_reason"]
                state["completed_at_et"] = timestamp()
                return state
        else:
            state["lifecycle_status"] = "not_triggered_no_contract_pass"

        state["status"] = "completed"
        state["completed_at_et"] = timestamp()
    except Exception as error:  # fail closed while preserving the audit trail
        state["status"] = "failed"
        state["reason"] = str(error)
        state["completed_at_et"] = timestamp()
    return state


def build_dispatch(
    *,
    output_dir: Path = Path("logs"),
    ledger_csv: Path | None = None,
    event_state_csv: Path | None = None,
    chain_dir: Path | None = None,
    contract_audit_csv: Path | None = None,
    samples_csv: Path | None = None,
    account_size: float = 10_000.0,
    max_chain_age_minutes: float = 20.0,
    market: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch every unprocessed eligible Candidate Ledger event."""

    ledger_csv = ledger_csv or runtime_data_path("candidate_window_ledger.csv")
    event_state_csv = event_state_csv or runtime_data_path("candidate_ledger_event_state.csv")
    chain_dir = chain_dir or runtime_data_path("options_chains", "active")
    contract_audit_csv = contract_audit_csv or runtime_data_path("options_contract_audit.csv")
    samples_csv = samples_csv or runtime_data_path("paper_validation_samples.csv")
    output_dir.mkdir(parents=True, exist_ok=True)
    current_market = market or market_refresh_state()
    ledger = read_csv_or_empty(ledger_csv)
    state = read_csv_or_empty(event_state_csv, EVENT_STATE_COLUMNS)
    candidates = eligible_candidate_events(ledger, current_market)
    done = processed_event_keys(state)
    pending = []
    pending_keys = set()
    for _, row in candidates.iterrows():
        key = event_key(row)
        if key in done or key in pending_keys:
            continue
        pending.append(row)
        pending_keys.add(key)
    rows = [
        dispatch_event(
            row,
            output_dir=output_dir,
            ledger_csv=ledger_csv,
            chain_dir=chain_dir,
            contract_audit_csv=contract_audit_csv,
            samples_csv=samples_csv,
            account_size=account_size,
            max_chain_age_minutes=max_chain_age_minutes,
            market=current_market,
            now=now,
        )
        for row in pending
    ]
    state = append_state(event_state_csv, rows)
    payload = {
        "generated_at_et": timestamp(now),
        "ledger_csv": str(ledger_csv),
        "event_state_csv": str(event_state_csv),
        "eligible_event_count": int(len(candidates)),
        "pending_event_count": int(len(pending)),
        "dispatched_event_count": int(len(rows)),
        "market_is_open": bool(current_market.get("market_is_open", False)),
        "today": text(current_market.get("today")),
        "rows": rows,
        "guardrail": (
            "Candidate Ledger event dispatch only changes downstream timing. It does not change strategy, "
            "scanner, Paper Gate, Contract Gate thresholds, lifecycle safety, or broker behavior."
        ),
    }
    write_report(output_dir, payload, state)
    return payload


def write_report(output_dir: Path, payload: dict[str, Any], state: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_ledger_event_dispatch.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    latest = state.tail(20) if not state.empty else pd.DataFrame(columns=EVENT_STATE_COLUMNS)
    rows = pd.DataFrame(payload["rows"], columns=EVENT_STATE_COLUMNS)
    (output_dir / "candidate_ledger_event_dispatch.md").write_text(
        f"""# Candidate Ledger Event Dispatch

Generated: {payload["generated_at_et"]}

## Summary

```text
Eligible events: {payload["eligible_event_count"]}
Pending events: {payload["pending_event_count"]}
Dispatched events: {payload["dispatched_event_count"]}
Market open: {payload["market_is_open"]}
```

## Dispatched Events

{markdown_table(rows)}

## Event State

{markdown_table(latest)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_dispatch(
        output_dir=args.output_dir,
        ledger_csv=args.ledger_csv,
        event_state_csv=args.event_state_csv,
        chain_dir=args.chain_dir,
        contract_audit_csv=args.contract_audit_csv,
        samples_csv=args.samples_csv,
        account_size=args.account_size,
        max_chain_age_minutes=args.max_chain_age_minutes,
    )
    print(f"Candidate Ledger events dispatched: {payload['dispatched_event_count']}")
    print(f"Saved {args.output_dir / 'candidate_ledger_event_dispatch.md'}")


if __name__ == "__main__":
    main()
