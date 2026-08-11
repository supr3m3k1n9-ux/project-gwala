"""Autonomously handle clean A-tier local paper-trade lifecycle steps.

This runner starts after Options Contract Gate. It only acts on A-tier rows that
already passed Contract Gate and meet deterministic safety checks. It writes
local paper artifacts only; it never calls broker endpoints or places real or
broker-paper orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime, time
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import uuid

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from config.settings import STRATEGY
from execution.paper_trader import (
    PAPER_ORDER_COLUMNS,
    filter_new_orders,
    orders_to_open_paper_trades,
    read_orders,
    write_open_paper_trades,
)
from reports.refresh_status import market_refresh_state
from run_options_chain_review import read_chain, validate_chain_provenance
from run_options_contract_gate import build_gate as build_options_contract_gate
from run_paper_validation_sample_import import SAMPLE_COLUMNS, dedupe as dedupe_samples, read_existing as read_samples
from run_paper_validation_sample_import import sample_rows_from_gate
from run_playbook import markdown_table


PROJECT_DIR = Path(__file__).resolve().parent
APPROVAL_COLUMNS = [
    "sample_key",
    "approved_at_et",
    "decision",
    "symbol",
    "setup",
    "direction",
    "sample_tier",
    "candidate_entry_et",
    "notes",
    "invalid_for_validation",
    "invalid_reason",
    "invalidated_at_et",
    "original_creation_timestamp",
    "incident_id",
    "source_contract_gate_identity",
]
REPORT_COLUMNS = [
    "sample_key",
    "symbol",
    "setup",
    "direction",
    "sample_tier",
    "candidate_entry_et",
    "contract_gate_status",
    "action_status",
    "reason",
    "safety_status",
    "approval_written",
    "orders_written",
    "open_trades_written",
    "validation_rows_written",
]
VALID_EXIT_REASONS = {"stop_loss_5m", "profit_target_5m", "end_of_day_exit"}
OPTION_CHAIN_ACTIVE_DIR = runtime_data_path("options_chains", "active")
OPTION_CHAIN_MAX_AGE_MINUTES = 20.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run autonomous clean A-tier local paper lifecycle.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--contract-audit-csv", type=Path, default=runtime_data_path("options_contract_audit.csv"))
    parser.add_argument("--samples-csv", type=Path, default=runtime_data_path("paper_validation_samples.csv"))
    parser.add_argument("--candidate-ledger-csv", type=Path, default=runtime_data_path("candidate_window_ledger.csv"))
    parser.add_argument("--paper-orders-csv", type=Path, default=runtime_data_path("paper_orders.csv"))
    parser.add_argument("--paper-csv", type=Path, default=runtime_data_path("paper_trades.csv"))
    parser.add_argument("--approvals-csv", type=Path, default=runtime_data_path("paper_command_center_approvals.csv"))
    parser.add_argument("--account-size", type=float, default=10_000.0)
    parser.add_argument("--option-chain-dir", type=Path, default=OPTION_CHAIN_ACTIVE_DIR)
    return parser.parse_args()


def text(value: object) -> str:
    """Return stable text for CSV/JSON values."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number(value: object) -> float | None:
    """Return a finite float or None."""

    if value is None or pd.isna(value) or text(value) == "":
        return None
    try:
        parsed = float(text(value).replace("%", ""))
    except ValueError:
        return None
    return parsed if pd.notna(parsed) else None


def truthy(value: object) -> bool:
    """Return True for common true values."""

    return text(value).lower() in {"1", "true", "yes", "y"}


def falsy_invalid(frame: pd.DataFrame) -> pd.Series:
    """Return rows that have not been invalidated for validation/accounting."""

    if frame.empty or "invalid_for_validation" not in frame.columns:
        return pd.Series([True] * len(frame), index=frame.index)
    return ~frame["invalid_for_validation"].map(truthy)


def sample_key(row: dict[str, Any]) -> str:
    """Return the stable key used across approval, contract, order, and sample artifacts."""

    return "|".join(
        [
            text(row.get("sample_date")).lower(),
            text(row.get("entry_time_et")).lower(),
            text(row.get("symbol")).upper(),
            text(row.get("setup")).lower(),
            text(row.get("direction")).lower(),
        ]
    )


def read_approvals(path: Path) -> pd.DataFrame:
    """Read chart approval audit rows."""

    if not path.exists():
        return pd.DataFrame(columns=APPROVAL_COLUMNS)
    try:
        approvals = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=APPROVAL_COLUMNS)
    for column in APPROVAL_COLUMNS:
        if column not in approvals.columns:
            approvals[column] = ""
    return approvals[APPROVAL_COLUMNS]


def latest_approval(approvals: pd.DataFrame, key: str) -> dict[str, Any]:
    """Return the latest approval row for one sample key."""

    if approvals.empty:
        return {}
    matches = approvals[approvals["sample_key"].astype(str) == key]
    if matches.empty:
        return {}
    return matches.iloc[-1].fillna("").to_dict()


def approval_row(row: dict[str, Any], key: str) -> dict[str, Any]:
    """Build an auto chart-approval audit row."""

    return {
        "sample_key": key,
        "approved_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "decision": "approved",
        "symbol": text(row.get("symbol")).upper(),
        "setup": text(row.get("setup")),
        "direction": text(row.get("direction")).lower(),
        "sample_tier": text(row.get("sample_tier")).upper(),
        "candidate_entry_et": text(row.get("candidate_entry_et")),
        "notes": "Auto-approved: clean A-tier Contract Gate pass with complete same-session context.",
        "invalid_for_validation": "",
        "invalid_reason": "",
        "invalidated_at_et": "",
        "original_creation_timestamp": "",
        "incident_id": "",
        "source_contract_gate_identity": "",
    }


def append_approval_if_needed(path: Path, approvals: pd.DataFrame, row: dict[str, Any], key: str) -> tuple[pd.DataFrame, bool]:
    """Append an approval audit row unless an approval already exists."""

    latest = latest_approval(approvals, key)
    if latest.get("decision") == "rejected":
        return approvals, False
    if latest.get("decision") == "approved":
        return approvals, False
    path.parent.mkdir(parents=True, exist_ok=True)
    updated = pd.concat([approvals, pd.DataFrame([approval_row(row, key)], columns=APPROVAL_COLUMNS)], ignore_index=True)
    updated.to_csv(path, index=False)
    return updated, True


def complete_plan(row: dict[str, Any]) -> bool:
    """Return whether the row has a complete trade plan and positive size."""

    entry = number(row.get("planned_entry"))
    stop = number(row.get("planned_stop"))
    target = number(row.get("planned_target"))
    shares = number(row.get("suggested_shares"))
    if any(value is None or value <= 0 for value in [entry, stop, target, shares]):
        return False
    return abs(float(entry) - float(stop)) > 0


def same_session(row: dict[str, Any], today: str) -> bool:
    """Return whether row timestamps all belong to today's session."""

    sample_date = text(row.get("sample_date"))
    candidate = text(row.get("candidate_entry_et"))
    source = text(row.get("source_signal_et"))
    return bool(sample_date == today and candidate.startswith(today) and (not source or source.startswith(today)))


def contract_complete(row: dict[str, Any]) -> bool:
    """Return whether Contract Gate passed with non-ambiguous contract details."""

    required_text = ["contract_symbol", "option_type", "expiration"]
    required_numbers = ["strike", "bid", "ask", "mid", "premium", "volume", "open_interest"]
    delta = number(row.get("delta"))
    return all(text(row.get(column)) for column in required_text) and delta is not None and abs(delta) > 0 and all(
        number(row.get(column)) is not None and number(row.get(column)) > 0 for column in required_numbers
    )


def parse_hhmm(value: str) -> time:
    """Parse configured HH:MM market times."""

    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute), tzinfo=MARKET_TZ)


def parse_candidate_timestamp(value: object) -> pd.Timestamp | None:
    """Return an ET timestamp for candidate and gate times."""

    raw = text(value)
    if not raw:
        return None
    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed) and raw.endswith((" EDT", " EST")):
        parsed = pd.to_datetime(raw.rsplit(" ", 1)[0], errors="coerce")
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(MARKET_TZ)
    return parsed.tz_convert(MARKET_TZ)


def in_entry_window(moment: datetime | pd.Timestamp) -> bool:
    """Return whether a moment is inside the configured autonomous entry window."""

    local = pd.Timestamp(moment).tz_convert(MARKET_TZ)
    start = parse_hhmm(STRATEGY.entry_start_time)
    latest = parse_hhmm(STRATEGY.latest_entry_time)
    return start <= local.timetz() <= latest


def production_heartbeat_valid(output_dir: Path, today: str) -> tuple[bool, str]:
    """Require current-session production heartbeat evidence before paper writes."""

    path = output_dir / "production_heartbeat.json"
    if not path.exists():
        return False, "blocked_invalid_session"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "blocked_invalid_session"
    status = text(payload.get("status")).upper()
    valid = payload.get("experiment_valid_today", payload.get("experiment_valid", False))
    generated = text(payload.get("generated_at_et"))
    if status != "GREEN" or not truthy(valid):
        return False, "blocked_invalid_session"
    if generated and not generated.startswith(today):
        return False, "blocked_invalid_session"
    return True, "pass"


def contract_chain_fresh(row: dict[str, Any], option_chain_dir: Path, now: datetime) -> tuple[bool, str]:
    """Require active current-session option-chain provenance at entry time."""

    symbol = text(row.get("symbol")).upper()
    if not symbol:
        return False, "blocked_stale_contract_chain"
    chain_path = option_chain_dir / f"{symbol}.csv"
    chain = read_chain(chain_path)
    sample = {"symbol": symbol, "scan_date": text(row.get("sample_date"))}
    ok, reason, _metadata = validate_chain_provenance(
        chain_path=chain_path,
        chain=chain,
        sample=sample,
        max_age_minutes=OPTION_CHAIN_MAX_AGE_MINUTES,
        now=now,
    )
    if not ok:
        return False, "blocked_stale_contract_chain" if "stale" in reason else "blocked_incomplete_provenance"
    return True, "pass"


def duplicate_or_invalid_artifact(
    row: dict[str, Any],
    key: str,
    approvals: pd.DataFrame,
    *,
    paper_orders_csv: Path,
    paper_csv: Path,
    samples_csv: Path,
) -> tuple[bool, str]:
    """Return whether any existing lifecycle artifact blocks another paper write."""

    latest = latest_approval(approvals, key)
    if latest.get("decision") == "rejected":
        return True, "blocked_candidate_rejected"
    if latest and truthy(latest.get("invalid_for_validation")):
        return True, "blocked_candidate_invalidated"
    if latest.get("decision") == "approved":
        return True, "blocked_duplicate"

    key_tuple = (
        text(row.get("sample_date")),
        text(row.get("entry_time_et")),
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")).lower(),
    )

    orders = read_orders(paper_orders_csv)
    for _, existing in orders.iterrows():
        order_key = (
            text(existing.get("trade_date")),
            text(existing.get("entry_time_et")),
            text(existing.get("symbol")).upper(),
            text(existing.get("setup")),
            text(existing.get("direction")).lower(),
        )
        if order_key == key_tuple:
            return True, "blocked_candidate_invalidated" if truthy(existing.get("invalid_for_validation")) else "blocked_duplicate"

    trades = pd.read_csv(paper_csv) if paper_csv.exists() else pd.DataFrame()
    for _, existing in trades.iterrows():
        trade_key = (
            text(existing.get("trade_date")),
            text(existing.get("entry_time_et")),
            text(existing.get("symbol")).upper(),
            text(existing.get("setup")),
            text(existing.get("direction")).lower(),
        )
        if trade_key == key_tuple:
            return True, "blocked_candidate_invalidated" if truthy(existing.get("invalid_for_validation")) else "blocked_duplicate"

    samples = read_samples(samples_csv)
    for _, existing in samples.iterrows():
        sample_tuple = (
            text(existing.get("sample_date")),
            text(existing.get("entry_time_et")),
            text(existing.get("symbol")).upper(),
            text(existing.get("setup")),
            text(existing.get("direction")).lower(),
        )
        if sample_tuple == key_tuple:
            return True, "blocked_candidate_invalidated" if truthy(existing.get("invalid_for_validation")) else "blocked_duplicate"

    return False, "pass"


def auto_eligible(row: dict[str, Any], today: str) -> tuple[bool, str]:
    """Return whether a Contract Gate row is safe for autonomous A-tier lifecycle."""

    if text(row.get("sample_tier")).upper() != "A":
        return False, "blocked_manual_tier"
    if text(row.get("signal_freshness")) != "current_candle":
        return False, "blocked_grace_or_stale_freshness"
    if not truthy(row.get("contract_gate_pass")) or text(row.get("contract_gate_status")) != "contract_pass":
        return False, "blocked_contract_gate_not_passed"
    if text(row.get("contract_gate_reason")).lower() != "pass":
        return False, "blocked_contract_gate_not_passed"
    if not truthy(row.get("counts_toward_30")) or not truthy(row.get("counts_toward_live_readiness")):
        return False, "blocked_not_countable"
    if not same_session(row, today):
        return False, "blocked_invalid_session"
    if not complete_plan(row):
        return False, "blocked_incomplete_trade_plan"
    if not contract_complete(row):
        return False, "blocked_ambiguous_contract"
    return True, "clean_a_tier_contract_pass"


def lifecycle_safety_check(
    row: dict[str, Any],
    *,
    key: str,
    today: str,
    market: dict[str, Any],
    gate_generated_at_et: str,
    approvals: pd.DataFrame,
    output_dir: Path,
    option_chain_dir: Path,
    paper_orders_csv: Path,
    paper_csv: Path,
    samples_csv: Path,
    now: datetime,
) -> tuple[bool, str]:
    """Fail closed before any autonomous paper write."""

    eligible, reason = auto_eligible(row, today)
    if not eligible:
        return False, reason
    if not bool(market.get("market_is_open", False)):
        return False, "blocked_market_closed"
    if not in_entry_window(now):
        return False, "blocked_entry_window_expired"
    candidate_time = parse_candidate_timestamp(row.get("candidate_entry_et"))
    if candidate_time is None or not in_entry_window(candidate_time):
        return False, "blocked_entry_window_expired"
    pass_time = parse_candidate_timestamp(gate_generated_at_et) or pd.Timestamp(now).tz_convert(MARKET_TZ)
    if text(row.get("sample_date")) != today or str(candidate_time.date()) != today:
        return False, "blocked_invalid_session"
    if not in_entry_window(pass_time):
        return False, "blocked_contract_pass_delayed"
    chain_ok, chain_reason = contract_chain_fresh(row, option_chain_dir, now)
    if not chain_ok:
        return False, chain_reason
    heartbeat_ok, heartbeat_reason = production_heartbeat_valid(output_dir, today)
    if not heartbeat_ok:
        return False, heartbeat_reason
    blocked, duplicate_reason = duplicate_or_invalid_artifact(
        row,
        key,
        approvals,
        paper_orders_csv=paper_orders_csv,
        paper_csv=paper_csv,
        samples_csv=samples_csv,
    )
    if blocked:
        return False, duplicate_reason
    return True, "pass"


def paper_order_from_row(row: dict[str, Any], now: datetime | None = None) -> pd.DataFrame:
    """Convert one clean Contract Gate row into one local paper order."""

    candidate_time = pd.to_datetime(row.get("candidate_entry_et"), errors="coerce")
    if pd.isna(candidate_time):
        raise ValueError("Candidate entry time is missing.")
    if candidate_time.tzinfo is None:
        candidate_time = candidate_time.tz_localize(MARKET_TZ)
    else:
        candidate_time = candidate_time.tz_convert(MARKET_TZ)
    direction = text(row.get("direction")).lower()
    now = now or datetime.now(MARKET_TZ)
    order = {
        "paper_order_id": f"PG-PAPER-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "created_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "trade_date": candidate_time.date().isoformat(),
        "entry_time_et": candidate_time.strftime("%H:%M"),
        "symbol": text(row.get("symbol")).upper(),
        "setup": text(row.get("setup")),
        "direction": direction,
        "side": "BUY" if direction == "long" else "SELL_SHORT",
        "order_type": "LOCAL_LIMIT_SIM",
        "limit_price": row.get("planned_entry", ""),
        "stop_price": row.get("planned_stop", ""),
        "target_price": row.get("planned_target", ""),
        "shares": int(number(row.get("suggested_shares")) or 0),
        "vehicle": "options",
        "risk_tier": "A",
        "planned_option_premium": row.get("premium", ""),
        "status": "local_paper_filled",
        "source": "autonomous_a_tier_contract_gate_pass",
        "notes": f"Autonomous A-tier local paper only; sample_key={sample_key(row)}; no broker order was sent.",
        "invalid_for_validation": "",
        "invalid_reason": "",
        "invalidated_at_et": "",
        "original_creation_timestamp": "",
        "incident_id": "",
        "source_contract_gate_identity": sample_key(row),
    }
    return pd.DataFrame([order], columns=PAPER_ORDER_COLUMNS)


def write_order_and_trade(row: dict[str, Any], *, paper_orders_csv: Path, paper_csv: Path, now: datetime) -> tuple[int, int]:
    """Write deduped local paper order and open trade rows."""

    order = paper_order_from_row(row, now=now)
    existing_orders = read_orders(paper_orders_csv)
    new_orders = filter_new_orders(existing_orders, order)
    paper_orders_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([existing_orders, new_orders], ignore_index=True).to_csv(paper_orders_csv, index=False)
    open_trades = orders_to_open_paper_trades(new_orders)
    written_trades = write_open_paper_trades(paper_csv, open_trades)
    return int(len(new_orders)), int(len(written_trades))


def matching_trade_exists(row: dict[str, Any], paper_csv: Path) -> bool:
    """Return whether the official local paper entry exists."""

    if not paper_csv.exists():
        return False
    try:
        trades = pd.read_csv(paper_csv)
    except pd.errors.EmptyDataError:
        return False
    if trades.empty:
        return False
    key = (
        text(row.get("sample_date")),
        text(row.get("entry_time_et")),
        text(row.get("symbol")).upper(),
        text(row.get("setup")),
        text(row.get("direction")).lower(),
    )
    for _, trade in trades.iterrows():
        trade_key = (
            text(trade.get("trade_date")),
            text(trade.get("entry_time_et")),
            text(trade.get("symbol")).upper(),
            text(trade.get("setup")),
            text(trade.get("direction")).lower(),
        )
        if trade_key == key:
            return True
    return False


def import_validation_after_entry(row: dict[str, Any], *, samples_csv: Path, paper_csv: Path) -> int:
    """Import validation sample only after the matching official paper entry exists."""

    if not matching_trade_exists(row, paper_csv):
        return 0
    existing = read_samples(samples_csv)
    candidate = sample_rows_from_gate({"passed_samples": [row]})
    new_rows = dedupe_samples(existing, candidate)
    if new_rows.empty:
        return 0
    samples_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([existing, new_rows], ignore_index=True).to_csv(samples_csv, index=False)
    return int(len(new_rows))


def deterministic_exit_rows(updates: pd.DataFrame, paper_csv: Path) -> pd.DataFrame:
    """Return exit-ready rows that are safe to confirm automatically."""

    if updates.empty or not paper_csv.exists():
        return pd.DataFrame(columns=updates.columns)
    ready = updates[
        (updates["monitor_status"].astype(str) == "exit_ready")
        & (updates["exit_reason"].astype(str).isin(VALID_EXIT_REASONS))
    ].copy()
    if ready.empty:
        return ready
    trades = pd.read_csv(paper_csv)
    safe_indexes = []
    for index, update in ready.iterrows():
        row_index = int(update["row"]) - 1
        if row_index < 0 or row_index >= len(trades):
            continue
        trade = trades.iloc[row_index]
        if truthy(trade.get("invalid_for_validation")):
            continue
        same_day = text(trade.get("trade_date")) == text(update.get("trade_date"))
        a_tier = text(trade.get("risk_tier")).upper() == "A"
        risk = abs((number(trade.get("actual_entry")) or number(trade.get("planned_entry")) or 0) - (number(trade.get("planned_stop")) or 0))
        if same_day and a_tier and risk > 0 and text(update.get("actual_exit")):
            safe_indexes.append(index)
    return ready.loc[safe_indexes].copy()


def run_exit_monitor(*, output_dir: Path, paper_csv: Path) -> tuple[int, int]:
    """Run deterministic monitor preview and confirm safe exit rows exactly once."""

    from run_open_paper_monitor import apply_updates, build_updates
    from run_paper_import import read_existing as read_paper_trades

    trades = read_paper_trades(paper_csv)
    updates = build_updates(trades, output_dir)
    safe = deterministic_exit_rows(updates, paper_csv)
    if not safe.empty:
        updated = apply_updates(trades, safe)
        updated.to_csv(paper_csv, index=False)
    return int(len(updates)), int(len(safe))


def build_lifecycle(
    *,
    output_dir: Path = Path("logs"),
    contract_audit_csv: Path | None = None,
    samples_csv: Path | None = None,
    candidate_ledger_csv: Path | None = None,
    paper_orders_csv: Path | None = None,
    paper_csv: Path | None = None,
    approvals_csv: Path | None = None,
    account_size: float = 10_000.0,
    option_chain_dir: Path = OPTION_CHAIN_ACTIVE_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run autonomous A-tier lifecycle and return an audit payload."""

    contract_audit_csv = contract_audit_csv or runtime_data_path("options_contract_audit.csv")
    samples_csv = samples_csv or runtime_data_path("paper_validation_samples.csv")
    candidate_ledger_csv = candidate_ledger_csv or runtime_data_path("candidate_window_ledger.csv")
    paper_orders_csv = paper_orders_csv or runtime_data_path("paper_orders.csv")
    paper_csv = paper_csv or runtime_data_path("paper_trades.csv")
    approvals_csv = approvals_csv or runtime_data_path("paper_command_center_approvals.csv")
    output_dir.mkdir(parents=True, exist_ok=True)
    current_time = now or datetime.now(MARKET_TZ)
    market = market_refresh_state()
    today = text(market.get("today"))
    gate = build_options_contract_gate(
        output_dir,
        contract_audit_csv,
        samples_csv,
        candidate_ledger_csv,
        account_size=account_size,
    )
    approvals = read_approvals(approvals_csv)
    rows: list[dict[str, Any]] = []
    approvals_written = orders_written = trades_written = samples_written = 0

    for row in gate.get("passed_samples", []):
        key = sample_key(row)
        safe, safety_status = lifecycle_safety_check(
            row,
            key=key,
            today=today,
            market=market,
            gate_generated_at_et=current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
            if now is not None
            else text(gate.get("generated_at_et")) or current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            approvals=approvals,
            output_dir=output_dir,
            option_chain_dir=option_chain_dir,
            paper_orders_csv=paper_orders_csv,
            paper_csv=paper_csv,
            samples_csv=samples_csv,
            now=current_time,
        )
        report = {
            "sample_key": key,
            "symbol": text(row.get("symbol")).upper(),
            "setup": text(row.get("setup")),
            "direction": text(row.get("direction")).lower(),
            "sample_tier": text(row.get("sample_tier")).upper(),
            "candidate_entry_et": text(row.get("candidate_entry_et")),
            "contract_gate_status": text(row.get("contract_gate_status")),
            "action_status": "blocked",
            "reason": safety_status,
            "safety_status": safety_status,
            "approval_written": 0,
            "orders_written": 0,
            "open_trades_written": 0,
            "validation_rows_written": 0,
        }
        if not safe:
            rows.append(report)
            continue
        approvals, approval_created = append_approval_if_needed(approvals_csv, approvals, row, key)
        order_count, trade_count = write_order_and_trade(row, paper_orders_csv=paper_orders_csv, paper_csv=paper_csv, now=current_time)
        sample_count = import_validation_after_entry(row, samples_csv=samples_csv, paper_csv=paper_csv)
        approvals_written += int(approval_created)
        orders_written += order_count
        trades_written += trade_count
        samples_written += sample_count
        report.update(
            {
                "action_status": "auto_entered" if trade_count else "duplicate",
                "reason": "Autonomous clean A-tier lifecycle completed through open paper entry.",
                "safety_status": "pass",
                "approval_written": int(approval_created),
                "orders_written": order_count,
                "open_trades_written": trade_count,
                "validation_rows_written": sample_count,
            }
        )
        rows.append(report)

    monitor_updates, exits_confirmed = run_exit_monitor(output_dir=output_dir, paper_csv=paper_csv)
    for command in [
        [sys.executable, "run_paper_review.py", "--output-dir", str(output_dir)],
        [sys.executable, "run_open_paper_monitor.py", "--output-dir", str(output_dir)],
        [sys.executable, "run_daily_ship_report.py", "--output-dir", str(output_dir)],
        [sys.executable, "run_system_state.py", "--output-dir", str(output_dir)],
    ]:
        subprocess.run(command, cwd=PROJECT_DIR, check=False, capture_output=True, text=True, timeout=120)

    return {
        "generated_at_et": current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "mode": "autonomous_a_tier_only",
        "promotion_source": gate.get("promotion_source", ""),
        "contract_gate_status": gate.get("status", ""),
        "contract_passed_candidates": int(len(gate.get("passed_samples", []))),
        "auto_approvals_written": approvals_written,
        "paper_orders_written": orders_written,
        "open_paper_trades_written": trades_written,
        "validation_rows_written": samples_written,
        "monitor_updates": monitor_updates,
        "exit_updates_confirmed": exits_confirmed,
        "rows": rows,
        "guardrail": (
            "A-tier local paper automation only. Requires Contract Gate pass, same-session current-candle context, "
            "market-open entry timing, fresh contract-chain provenance, valid heartbeat, complete plan and contract "
            "details, duplicate checks, and deterministic exits. No broker orders are placed."
        ),
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write lifecycle audit outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame(payload["rows"], columns=REPORT_COLUMNS)
    (output_dir / "autonomous_a_tier_lifecycle.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    rows.to_csv(output_dir / "autonomous_a_tier_lifecycle.csv", index=False)
    summary = pd.DataFrame(
        [
            {"metric": "contract_passed_candidates", "value": payload["contract_passed_candidates"]},
            {"metric": "auto_approvals_written", "value": payload["auto_approvals_written"]},
            {"metric": "paper_orders_written", "value": payload["paper_orders_written"]},
            {"metric": "open_paper_trades_written", "value": payload["open_paper_trades_written"]},
            {"metric": "validation_rows_written", "value": payload["validation_rows_written"]},
            {"metric": "exit_updates_confirmed", "value": payload["exit_updates_confirmed"]},
        ]
    )
    (output_dir / "autonomous_a_tier_lifecycle.md").write_text(
        f"""# Autonomous A-Tier Lifecycle

Generated: {payload["generated_at_et"]}

## Summary

{markdown_table(summary)}

## Rows

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_lifecycle(
        output_dir=args.output_dir,
        contract_audit_csv=args.contract_audit_csv,
        samples_csv=args.samples_csv,
        candidate_ledger_csv=args.candidate_ledger_csv,
        paper_orders_csv=args.paper_orders_csv,
        paper_csv=args.paper_csv,
        approvals_csv=args.approvals_csv,
        account_size=args.account_size,
        option_chain_dir=args.option_chain_dir,
    )
    write_outputs(args.output_dir, payload)
    print(f"Autonomous A-tier lifecycle: {payload['open_paper_trades_written']} open paper trade(s) written")
    print(f"Exit updates confirmed: {payload['exit_updates_confirmed']}")
    print(f"Saved {args.output_dir / 'autonomous_a_tier_lifecycle.md'}")


if __name__ == "__main__":
    main()
