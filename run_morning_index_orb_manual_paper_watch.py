"""Build the Morning SPY/QQQ Long ORB Manual Paper-Watch lane.

This lane promotes only the approved narrow ORB business:
Morning SPY/QQQ Long Opening Range Breakout before noon ET.

It does not change ORB signal logic, VWAP logic, Paper Gate behavior, broker
connectivity, or live execution. Broad ORB remains shadow/forward research.
Clean promoted candidates may advance into local simulated paper evidence
without routine operator approval after all approved gates pass.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from config.runtime_paths import runtime_data_root
from config.settings import ACCOUNT
from reports.refresh_status import market_refresh_state
from run_options_contract_gate import (
    CONTRACT_AUDIT_COLUMNS,
    GATE_COLUMNS,
    contract_key,
    gate_row,
    latest_contract_lookup,
    sample_template_row,
)
from run_playbook import markdown_table
from run_position_sizer import apply_session_gate, build_sizing


STRATEGY_ID = "morning_index_orb_long"
STRATEGY_NAME = "Morning SPY/QQQ Long ORB"
SETUP_NAME = "Morning Index ORB Long"
PROMOTED_SYMBOLS = {"SPY", "QQQ"}
CHECKPOINT_TRADES = 20
BEFORE_NOON_ET = "12:00"

OBSERVATION_CSV = runtime_data_path("opening_range_breakout_forward_observations.csv")
OUTCOME_CSV = Path("logs/opening_range_breakout_forward_observation_results.csv")
REVIEW_CSV = runtime_data_path("morning_index_orb_manual_reviews.csv")
CONTRACT_AUDIT_CSV = runtime_data_path("morning_index_orb_contract_audit.csv")
LEDGER_CSV = runtime_data_path("morning_index_orb_manual_paper_trades.csv")

REVIEW_COLUMNS = [
    "candidate_id",
    "trading_date",
    "signal_timestamp_et",
    "symbol",
    "operator_review_status",
    "operator_review_reason",
    "reviewed_at_et",
]

QUEUE_COLUMNS = [
    "candidate_id",
    "trading_date",
    "detected_timestamp_et",
    "signal_timestamp_et",
    "symbol",
    "direction",
    "strategy_id",
    "strategy_family",
    "orb_subtype",
    "entry_reference",
    "stop_reference",
    "target_reference",
    "risk_per_share",
    "freshness_state",
    "qualification_status",
    "qualification_reason",
    "disqualification_reason",
    "operator_review_status",
    "operator_review_reason",
    "sizing_status",
    "sizing_reason",
    "suggested_shares",
    "sample_risk_pct",
    "contract_review_status",
    "contract_review_reason",
    "contract_gate_pass",
    "paper_entry_status",
    "evidence_confidence",
    "counts_toward_vwap_30",
    "counts_toward_orb_20",
]

LEDGER_COLUMNS = [
    "trade_id",
    "candidate_id",
    "trading_date",
    "entry_time_et",
    "exit_time_et",
    "symbol",
    "strategy_id",
    "direction",
    "status",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "actual_entry",
    "actual_exit",
    "outcome_r",
    "mfe_r",
    "mae_r",
    "exit_reason",
    "suggested_shares",
    "sample_risk_pct",
    "contract_symbol",
    "option_type",
    "expiration",
    "dte",
    "strike",
    "delta",
    "bid",
    "ask",
    "mid",
    "spread_pct",
    "volume",
    "open_interest",
    "implied_volatility",
    "premium",
    "time_window",
    "market_regime",
    "evidence_confidence",
    "completion_timestamp_et",
    "counts_toward_vwap_30",
    "counts_toward_orb_20",
    "notes",
]

EXCEPTION_COLUMNS = [
    "timestamp_et",
    "strategy_id",
    "strategy_name",
    "symbol",
    "candidate_id",
    "blocked_stage",
    "reason",
    "required_operator_action",
]


def default_refresh_audit_csv() -> Path:
    """Return the durable refresh-audit CSV path."""

    return runtime_data_root() / "market_refresh_audit.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Morning Index ORB Manual Paper-Watch lane.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"))
    parser.add_argument("--observations-csv", type=Path, default=OBSERVATION_CSV)
    parser.add_argument("--outcomes-csv", type=Path, default=OUTCOME_CSV)
    parser.add_argument("--review-csv", type=Path, default=REVIEW_CSV)
    parser.add_argument("--contract-audit-csv", type=Path, default=CONTRACT_AUDIT_CSV)
    parser.add_argument("--ledger-csv", type=Path, default=LEDGER_CSV)
    parser.add_argument("--refresh-audit-csv", type=Path, default=default_refresh_audit_csv())
    parser.add_argument("--account-size", type=float, default=ACCOUNT.starting_equity)
    parser.add_argument("--risk-per-trade-pct", type=float, default=ACCOUNT.risk_per_trade_pct)
    parser.set_defaults(confirm_paper_entry=True)
    parser.add_argument(
        "--confirm-paper-entry",
        action="store_true",
        help="Compatibility flag. Clean ORB paper entries are autonomous by default.",
    )
    parser.add_argument(
        "--preview-only",
        dest="confirm_paper_entry",
        action="store_false",
        help="Build the queue and gates without appending local simulated ORB paper entries.",
    )
    return parser.parse_args()


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


def json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in frame.to_dict("records"):
        clean: dict[str, Any] = {}
        for key, value in item.items():
            if value is None or pd.isna(value):
                clean[key] = ""
            else:
                clean[key] = value
        records.append(clean)
    return records


def numeric(value: object) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed) or not math.isfinite(float(parsed)):
        return 0.0
    return float(parsed)


def parse_et_timestamp(value: object) -> pd.Timestamp | None:
    raw = text(value)
    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed) and raw.endswith((" EDT", " EST")):
        parsed = pd.to_datetime(raw.rsplit(" ", 1)[0], errors="coerce")
    if pd.isna(parsed):
        return None
    if getattr(parsed, "tzinfo", None):
        return parsed.tz_convert(MARKET_TZ)
    return parsed.tz_localize(MARKET_TZ)


def candidate_id(row: pd.Series) -> str:
    entry = text(row.get("entry_time_et")).replace(" ", "T")
    return "|".join(
        [
            STRATEGY_ID,
            text(row.get("scan_date")),
            text(row.get("symbol")).upper(),
            text(row.get("direction")).lower(),
            entry,
        ]
    )


def latest_review_lookup(reviews: pd.DataFrame) -> dict[str, pd.Series]:
    lookup: dict[str, pd.Series] = {}
    for _, row in reviews.iterrows():
        lookup[text(row.get("candidate_id"))] = row
    return lookup


def symbol_has_current_refresh(symbol: str, today: str, refresh_audit: pd.DataFrame) -> bool:
    required = {"symbol", "m30_latest_session", "m5_latest_session", "refresh_evidence_status"}
    if not required.issubset(refresh_audit.columns):
        return False
    valid = refresh_audit[
        (refresh_audit["symbol"].astype(str).str.upper() == symbol.upper())
        & (refresh_audit["m30_latest_session"].astype(str) == today)
        & (refresh_audit["m5_latest_session"].astype(str) == today)
        & (refresh_audit["refresh_evidence_status"].isin({"files_present_and_complete", "current_session_in_progress"}))
    ]
    return not valid.empty


def freshness_state(row: pd.Series, market: dict[str, Any], refresh_audit: pd.DataFrame) -> tuple[str, bool]:
    today = text(market.get("today"))
    symbol = text(row.get("symbol")).upper()
    scan_date = text(row.get("scan_date"))
    observed = parse_et_timestamp(row.get("observed_at_et"))
    observed_today = observed is not None and observed.date().isoformat() == today
    if scan_date != today or not observed_today:
        return "stale_or_not_current_session", False
    if not symbol_has_current_refresh(symbol, today, refresh_audit):
        return "missing_current_session_refresh_evidence", False
    if not bool(market.get("market_is_open", False)):
        return "current_session_data_but_market_not_open", False
    return "fresh_current_session", True


def qualification_for_row(
    row: pd.Series,
    market: dict[str, Any],
    refresh_audit: pd.DataFrame,
) -> tuple[str, str, str, str]:
    blockers: list[str] = []
    symbol = text(row.get("symbol")).upper()
    direction = text(row.get("direction")).lower()
    entry_time = parse_et_timestamp(row.get("entry_time_et"))
    freshness, fresh_ok = freshness_state(row, market, refresh_audit)

    if text(row.get("strategy")) != "opening_range_breakout":
        blockers.append("not_existing_orb_logic")
    if symbol not in PROMOTED_SYMBOLS:
        blockers.append("symbol_not_spy_or_qqq")
    if direction != "long":
        blockers.append("direction_not_long")
    if entry_time is None:
        blockers.append("missing_signal_time")
    elif entry_time.strftime("%H:%M") >= BEFORE_NOON_ET:
        blockers.append("signal_at_or_after_12_et")
    if not fresh_ok:
        blockers.append(freshness)

    if blockers:
        return freshness, "not_promoted", "", "; ".join(blockers)
    return freshness, "qualified", "SPY/QQQ long ORB before 12:00 ET from fresh current-session data.", ""


def scanner_row_from_queue(row: pd.Series) -> dict[str, Any]:
    return {
        "scan_date": text(row.get("trading_date")),
        "symbol": text(row.get("symbol")).upper(),
        "setup": SETUP_NAME,
        "direction": "long",
        "validation_lane": "ORB_MANUAL",
        "scanner_status": "allowed",
        "signal_freshness": "current_candle",
        "latest_signal_et": text(row.get("signal_timestamp_et")),
        "candidate_entry_et": text(row.get("signal_timestamp_et")),
        "planned_entry": row.get("entry_reference", ""),
        "planned_stop": row.get("stop_reference", ""),
        "planned_target": row.get("target_reference", ""),
        "risk_per_share": row.get("risk_per_share", ""),
    }


def sizing_for_queue(
    queue: pd.DataFrame,
    *,
    account_size: float,
    risk_per_trade_pct: float,
    market: dict[str, Any],
    refresh_audit: pd.DataFrame,
) -> dict[str, pd.Series]:
    eligible = queue[
        (queue["qualification_status"] == "qualified")
        & (queue["operator_review_status"].astype(str).str.lower() != "rejected")
    ].copy()
    if eligible.empty:
        return {}

    scanner = pd.DataFrame([scanner_row_from_queue(row) for _, row in eligible.iterrows()])
    args = argparse.Namespace(
        account_size=account_size,
        risk_per_trade_pct=risk_per_trade_pct,
        daily_realized_r=0.0,
        monthly_realized_r=0.0,
        max_daily_loss_r=-3.0,
        max_monthly_loss_r=-3.0,
        include_watch_only=False,
        freshness="paper_validation",
    )
    sizing = build_sizing(scanner, args)
    sizing = apply_session_gate(sizing, scanner, market, refresh_audit)
    lookup: dict[str, pd.Series] = {}
    for index, row in eligible.reset_index(drop=True).iterrows():
        if index < len(sizing):
            lookup[text(row.get("candidate_id"))] = sizing.iloc[index]
    return lookup


def contract_sample_from_queue(row: pd.Series) -> dict[str, Any]:
    return {
        "scan_date": text(row.get("trading_date")),
        "entry_time_et": text(row.get("signal_timestamp_et"))[11:16],
        "source_signal_et": text(row.get("signal_timestamp_et")),
        "candidate_entry_et": text(row.get("signal_timestamp_et")),
        "latest_signal_et": text(row.get("signal_timestamp_et")),
        "symbol": text(row.get("symbol")).upper(),
        "setup": SETUP_NAME,
        "direction": "long",
        "strategy_id": STRATEGY_ID,
        "variant": "manual_paper_watch",
        "exit_profile": "orb_existing_plan",
        "sample_tier": "ORB_MANUAL",
        "signal_freshness": "current_candle",
        "validation_lane": "ORB_MANUAL",
        "manual_review_required": False,
        "counts_toward_30": False,
        "counts_toward_live_readiness": False,
        "planned_entry": row.get("entry_reference", ""),
        "planned_stop": row.get("stop_reference", ""),
        "planned_target": row.get("target_reference", ""),
        "suggested_shares": row.get("suggested_shares", ""),
        "sample_risk_pct": row.get("sample_risk_pct", ""),
    }


def contract_gate_for_queue(queue: pd.DataFrame, contract_audit_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    ready = queue[
        (queue["qualification_status"].astype(str) == "qualified")
        & (queue["operator_review_status"].astype(str).str.lower() != "rejected")
        & (queue["sizing_status"].astype(str) == "size_ok")
    ].copy()
    samples = [contract_sample_from_queue(row) for _, row in ready.iterrows()]
    audit = read_csv_or_empty(contract_audit_csv, CONTRACT_AUDIT_COLUMNS)
    lookup = latest_contract_lookup(audit)
    template = pd.DataFrame([sample_template_row(row) for row in samples], columns=CONTRACT_AUDIT_COLUMNS)
    rows = pd.DataFrame(
        [gate_row(row, lookup.get(contract_key(sample_template_row(row)))) for row in samples],
        columns=GATE_COLUMNS,
    )
    return rows, template


def build_queue(
    observations: pd.DataFrame,
    reviews: pd.DataFrame,
    *,
    market: dict[str, Any],
    refresh_audit: pd.DataFrame,
    account_size: float,
    risk_per_trade_pct: float,
) -> pd.DataFrame:
    review_lookup = latest_review_lookup(reviews)
    rows: list[dict[str, Any]] = []
    for _, observation in observations.iterrows():
        cid = candidate_id(observation)
        review = review_lookup.get(cid)
        freshness, status, reason, disqualification = qualification_for_row(observation, market, refresh_audit)
        review_status = text(review.get("operator_review_status")) if review is not None else "not_required"
        review_reason = text(review.get("operator_review_reason")) if review is not None else ""
        rows.append(
            {
                "candidate_id": cid,
                "trading_date": text(observation.get("scan_date")),
                "detected_timestamp_et": text(observation.get("observed_at_et")),
                "signal_timestamp_et": text(observation.get("entry_time_et")),
                "symbol": text(observation.get("symbol")).upper(),
                "direction": text(observation.get("direction")).lower(),
                "strategy_id": STRATEGY_ID,
                "strategy_family": text(observation.get("strategy")),
                "orb_subtype": text(observation.get("signal_column")),
                "entry_reference": observation.get("planned_entry", ""),
                "stop_reference": observation.get("planned_stop", ""),
                "target_reference": observation.get("planned_target", ""),
                "risk_per_share": observation.get("risk_per_share", ""),
                "freshness_state": freshness,
                "qualification_status": status,
                "qualification_reason": reason,
                "disqualification_reason": disqualification,
                "operator_review_status": review_status or "not_required",
                "operator_review_reason": review_reason,
                "sizing_status": "pending_sizing",
                "sizing_reason": "Autonomous local-paper sizing pending.",
                "suggested_shares": 0,
                "sample_risk_pct": 0.0,
                "contract_review_status": "not_ready",
                "contract_review_reason": "Candidate must be qualified and size_ok before contract review.",
                "contract_gate_pass": False,
                "paper_entry_status": "not_ready",
                "evidence_confidence": "HIGH",
                "counts_toward_vwap_30": False,
                "counts_toward_orb_20": False,
            }
        )
    queue = pd.DataFrame(rows, columns=QUEUE_COLUMNS)
    if queue.empty:
        return queue

    rejected = queue["operator_review_status"].astype(str).str.lower() == "rejected"
    queue.loc[rejected, "sizing_status"] = "operator_rejected"
    queue.loc[rejected, "sizing_reason"] = queue.loc[rejected, "operator_review_reason"].replace("", "Operator rejected.")

    not_qualified = queue["qualification_status"] != "qualified"
    queue.loc[not_qualified, "sizing_status"] = "not_qualified"
    queue.loc[not_qualified, "sizing_reason"] = queue.loc[not_qualified, "disqualification_reason"]

    sizing_lookup = sizing_for_queue(
        queue,
        account_size=account_size,
        risk_per_trade_pct=risk_per_trade_pct,
        market=market,
        refresh_audit=refresh_audit,
    )
    for index, row in queue.iterrows():
        sizing = sizing_lookup.get(text(row.get("candidate_id")))
        if sizing is None:
            continue
        queue.at[index, "sizing_status"] = text(sizing.get("sizing_status"))
        queue.at[index, "sizing_reason"] = text(sizing.get("sizing_reason"))
        queue.at[index, "suggested_shares"] = int(numeric(sizing.get("suggested_shares")))
        queue.at[index, "sample_risk_pct"] = numeric(sizing.get("risk_per_trade_pct"))
    return queue[QUEUE_COLUMNS]


def add_contract_status(queue: pd.DataFrame, contract_rows: pd.DataFrame) -> pd.DataFrame:
    if queue.empty:
        return queue
    result = queue.copy()
    by_key: dict[tuple[str, str, str, str, str], pd.Series] = {}
    for _, row in contract_rows.iterrows():
        by_key[contract_key(row)] = row
    for index, row in result.iterrows():
        if text(row.get("qualification_status")) != "qualified":
            continue
        sample = contract_sample_from_queue(row)
        contract = by_key.get(contract_key(sample_template_row(sample)))
        if contract is None:
            continue
        passed = truthy(contract.get("contract_gate_pass"))
        result.at[index, "contract_review_status"] = text(contract.get("contract_gate_status"))
        result.at[index, "contract_review_reason"] = text(contract.get("contract_gate_reason"))
        result.at[index, "contract_gate_pass"] = passed
        result.at[index, "paper_entry_status"] = "ready_for_paper_entry" if passed else "waiting_for_contract_pass"
    return result[QUEUE_COLUMNS]


def load_ledger(path: Path) -> pd.DataFrame:
    return read_csv_or_empty(path, LEDGER_COLUMNS)


def append_confirmed_entries(queue: pd.DataFrame, contract_rows: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    if queue.empty:
        return ledger
    existing_ids = set(ledger["candidate_id"].astype(str)) if "candidate_id" in ledger.columns else set()
    contract_lookup = {contract_key(row): row for _, row in contract_rows.iterrows()}
    rows: list[dict[str, Any]] = []
    ready = queue[
        (queue["qualification_status"] == "qualified")
        &
        (queue["paper_entry_status"] == "ready_for_paper_entry")
        & (queue["operator_review_status"].astype(str).str.lower() != "rejected")
    ]
    now = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    for _, row in ready.iterrows():
        cid = text(row.get("candidate_id"))
        if cid in existing_ids:
            continue
        sample = contract_sample_from_queue(row)
        contract = contract_lookup.get(contract_key(sample_template_row(sample)), pd.Series(dtype=object))
        rows.append(
            {
                "trade_id": cid,
                "candidate_id": cid,
                "trading_date": text(row.get("trading_date")),
                "entry_time_et": text(row.get("signal_timestamp_et")),
                "exit_time_et": "",
                "symbol": text(row.get("symbol")),
                "strategy_id": STRATEGY_ID,
                "direction": "long",
                "status": "open",
                "planned_entry": row.get("entry_reference", ""),
                "planned_stop": row.get("stop_reference", ""),
                "planned_target": row.get("target_reference", ""),
                "actual_entry": row.get("entry_reference", ""),
                "actual_exit": "",
                "outcome_r": "",
                "mfe_r": "",
                "mae_r": "",
                "exit_reason": "",
                "suggested_shares": row.get("suggested_shares", ""),
                "sample_risk_pct": row.get("sample_risk_pct", ""),
                **{column: contract.get(column, "") for column in CONTRACT_AUDIT_COLUMNS[7:]},
                "time_window": "morning_before_12_et",
                "market_regime": "",
                "evidence_confidence": text(row.get("evidence_confidence")) or "HIGH",
                "completion_timestamp_et": "",
                "counts_toward_vwap_30": False,
                "counts_toward_orb_20": False,
                "notes": f"Autonomous ORB local paper entry created at {now}. Paper-only; no broker order was sent.",
            }
        )
    if not rows:
        return ledger[LEDGER_COLUMNS]
    combined = pd.concat([ledger, pd.DataFrame(rows, columns=LEDGER_COLUMNS)], ignore_index=True)
    return combined[LEDGER_COLUMNS]


def update_completed_outcomes(ledger: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty or outcomes.empty:
        return ledger
    result = ledger.copy()
    outcome_lookup = {candidate_id(row): row for _, row in outcomes.iterrows()}
    now = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    for index, row in result.iterrows():
        if text(row.get("status")) == "completed":
            continue
        outcome = outcome_lookup.get(text(row.get("candidate_id")))
        if outcome is None or text(outcome.get("evaluation_status")) != "matured":
            continue
        result.at[index, "status"] = "completed"
        result.at[index, "exit_time_et"] = text(outcome.get("hypothetical_exit_time_et"))
        result.at[index, "actual_exit"] = outcome.get("hypothetical_exit_price", "")
        result.at[index, "outcome_r"] = outcome.get("hypothetical_r", "")
        result.at[index, "exit_reason"] = text(outcome.get("hypothetical_exit_reason"))
        result.at[index, "completion_timestamp_et"] = now
        result.at[index, "counts_toward_orb_20"] = True
        result.at[index, "notes"] = "Completed ORB Manual Paper-Watch evidence. Paper-only; separate from VWAP 30-trade checkpoint."
    return result[LEDGER_COLUMNS]


def apply_duplicate_safety(queue: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    """Block repeat local paper entries for an ORB candidate already in the ledger."""

    if queue.empty or ledger.empty or "candidate_id" not in ledger.columns:
        return queue
    result = queue.copy()
    existing_ids = set(ledger["candidate_id"].astype(str))
    duplicate = result["candidate_id"].astype(str).isin(existing_ids)
    result.loc[duplicate, "paper_entry_status"] = "duplicate_existing_orb_entry"
    result.loc[duplicate, "contract_review_reason"] = "Duplicate blocked: candidate already exists in the ORB paper ledger."
    return result[QUEUE_COLUMNS]


def exception_rows(queue: pd.DataFrame) -> pd.DataFrame:
    """Return operator-actionable exceptions for candidates blocked from safe automation."""

    now = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    rows: list[dict[str, Any]] = []
    for _, row in queue.iterrows():
        symbol = text(row.get("symbol"))
        candidate = text(row.get("candidate_id"))
        direction = text(row.get("direction")).lower()
        signal_time = parse_et_timestamp(row.get("signal_timestamp_et"))
        is_promoted_family = symbol in PROMOTED_SYMBOLS and direction == "long"
        if signal_time is not None:
            is_promoted_family = is_promoted_family and signal_time.strftime("%H:%M") < BEFORE_NOON_ET
        qualification = text(row.get("qualification_status"))
        sizing = text(row.get("sizing_status"))
        contract = text(row.get("contract_review_status"))
        paper_entry = text(row.get("paper_entry_status"))
        review = text(row.get("operator_review_status")).lower()

        blocked_stage = ""
        reason = ""
        action = ""
        if review == "rejected":
            blocked_stage = "operator_exception"
            reason = text(row.get("operator_review_reason")) or "Operator rejected this candidate."
            action = "Review only if the rejection was entered in error."
        elif qualification != "qualified" and is_promoted_family:
            blocked_stage = "qualification"
            reason = text(row.get("disqualification_reason"))
            action = "No action unless promoted-strategy rules were configured incorrectly."
        elif sizing != "size_ok":
            blocked_stage = "position_sizing"
            reason = text(row.get("sizing_reason"))
            action = "Review sizing, freshness, session, or risk-state blocker."
        elif contract == "missing_contract_review":
            blocked_stage = "contract_data"
            reason = text(row.get("contract_review_reason"))
            action = "Add or repair local option-chain/contract data, then rerun the ORB paper workflow."
        elif contract == "contract_blocked":
            blocked_stage = "contract_gate"
            reason = text(row.get("contract_review_reason"))
            action = "Review contract quality only if the data appears wrong."
        elif paper_entry == "duplicate_existing_orb_entry":
            blocked_stage = "duplicate_safety"
            reason = text(row.get("contract_review_reason"))
            action = "No action unless the existing ledger row is erroneous."
        elif paper_entry not in {"ready_for_paper_entry", "not_ready"}:
            blocked_stage = "paper_entry"
            reason = paper_entry
            action = "Review unexpected paper-entry state."

        if blocked_stage:
            rows.append(
                {
                    "timestamp_et": now,
                    "strategy_id": STRATEGY_ID,
                    "strategy_name": STRATEGY_NAME,
                    "symbol": symbol,
                    "candidate_id": candidate,
                    "blocked_stage": blocked_stage,
                    "reason": reason,
                    "required_operator_action": action,
                }
            )
    return pd.DataFrame(rows, columns=EXCEPTION_COLUMNS)


def safety_assertions(ledger_csv: Path) -> dict[str, Any]:
    """Document the hard boundary between local paper research and live execution."""

    return {
        "autonomous_live_execution_enabled": False,
        "broker_orders_enabled": False,
        "webull_order_placement_enabled": False,
        "broker_paper_execution_enabled": False,
        "real_money_execution_enabled": False,
        "local_simulated_artifacts_only": True,
        "orb_ledger": str(ledger_csv),
        "vwap_validation_samples_modified": False,
        "counts_toward_vwap_30": False,
        "broad_orb_autonomous_paper_entry_enabled": False,
    }


def runway_metrics(ledger: pd.DataFrame, queue: pd.DataFrame) -> dict[str, Any]:
    completed = ledger[ledger["status"].astype(str).eq("completed")].copy() if not ledger.empty else pd.DataFrame(columns=LEDGER_COLUMNS)
    open_trades = ledger[ledger["status"].astype(str).eq("open")].copy() if not ledger.empty else pd.DataFrame(columns=LEDGER_COLUMNS)
    completed["outcome_r_numeric"] = pd.to_numeric(completed.get("outcome_r", pd.Series(dtype=float)), errors="coerce")
    r_values = completed["outcome_r_numeric"].dropna()
    wins = r_values[r_values > 0]
    losses = r_values[r_values < 0]
    gross_loss = abs(float(losses.sum())) if not losses.empty else 0.0
    profit_factor: float | str = round(float(wins.sum()) / gross_loss, 4) if gross_loss > 0 else (">100" if not wins.empty else 0.0)
    equity = r_values.cumsum()
    drawdown = equity - equity.cummax() if not equity.empty else pd.Series(dtype=float)
    by_symbol = completed.groupby("symbol")["outcome_r_numeric"].agg(["count", "mean"]).reset_index() if not completed.empty else pd.DataFrame()
    reviewed = queue[queue["operator_review_status"].astype(str).str.lower().isin({"approved", "rejected"})] if not queue.empty else pd.DataFrame()
    approved = queue[queue["operator_review_status"].astype(str).str.lower().eq("approved")] if not queue.empty else pd.DataFrame()
    rejected = queue[queue["operator_review_status"].astype(str).str.lower().eq("rejected")] if not queue.empty else pd.DataFrame()
    contract_passed = queue[queue["contract_gate_pass"].map(truthy)] if not queue.empty else pd.DataFrame()
    contract_failed = queue[queue["contract_review_status"].astype(str).eq("contract_blocked")] if not queue.empty else pd.DataFrame()
    confidence = completed.groupby("evidence_confidence").size().to_dict() if not completed.empty else {}
    return {
        "completed_count": int(len(completed)),
        "open_count": int(len(open_trades)),
        "remaining_to_20": max(CHECKPOINT_TRADES - int(len(completed)), 0),
        "average_r": round(float(r_values.mean()), 4) if not r_values.empty else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown_r": round(float(drawdown.min()), 4) if not drawdown.empty else 0.0,
        "win_rate_pct": round(float((r_values > 0).mean() * 100), 1) if not r_values.empty else 0.0,
        "spy_completed": int((completed["symbol"].astype(str).eq("SPY")).sum()) if not completed.empty else 0,
        "qqq_completed": int((completed["symbol"].astype(str).eq("QQQ")).sum()) if not completed.empty else 0,
        "by_symbol": by_symbol.to_dict("records") if not by_symbol.empty else [],
        "candidates_detected_today": int(len(queue)),
        "qualified_today": int((queue["qualification_status"].eq("qualified")).sum()) if not queue.empty else 0,
        "operator_reviewed_today": int(len(reviewed)),
        "approved_today": int(len(approved)),
        "rejected_today": int(len(rejected)),
        "contract_passed_today": int(len(contract_passed)),
        "contract_failed_today": int(len(contract_failed)),
        "paper_entries_opened": int(len(open_trades)),
        "trades_completed": int(len(completed)),
        "evidence_confidence_distribution": confidence,
    }


def estimated_time_to_checkpoint(metrics: dict[str, Any]) -> str:
    remaining = int(metrics.get("remaining_to_20", CHECKPOINT_TRADES))
    completed = int(metrics.get("completed_count", 0))
    if remaining <= 0:
        return "checkpoint reached; Investment Committee review required"
    if completed == 0:
        return "insufficient manual paper-watch completions; estimate after first completed entries"
    return "track after two or more active Manual Paper-Watch sessions"


def build_payload(
    *,
    output_dir: Path = Path("logs"),
    observations_csv: Path = OBSERVATION_CSV,
    outcomes_csv: Path = OUTCOME_CSV,
    review_csv: Path = REVIEW_CSV,
    contract_audit_csv: Path = CONTRACT_AUDIT_CSV,
    ledger_csv: Path = LEDGER_CSV,
    refresh_audit_csv: Path | None = None,
    account_size: float = ACCOUNT.starting_equity,
    risk_per_trade_pct: float = ACCOUNT.risk_per_trade_pct,
    confirm_paper_entry: bool = True,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market = market or market_refresh_state()
    refresh_audit_csv = refresh_audit_csv or default_refresh_audit_csv()
    observations = read_csv_or_empty(observations_csv)
    reviews = read_csv_or_empty(review_csv, REVIEW_COLUMNS)
    refresh_audit = read_csv_or_empty(refresh_audit_csv)
    queue = build_queue(
        observations,
        reviews,
        market=market,
        refresh_audit=refresh_audit,
        account_size=account_size,
        risk_per_trade_pct=risk_per_trade_pct,
    )
    contract_rows, template = contract_gate_for_queue(queue, contract_audit_csv)
    queue = add_contract_status(queue, contract_rows)
    ledger = load_ledger(ledger_csv)
    queue = apply_duplicate_safety(queue, ledger)
    if confirm_paper_entry:
        ledger = append_confirmed_entries(queue, contract_rows, ledger)
    outcomes = read_csv_or_empty(outcomes_csv)
    ledger = update_completed_outcomes(ledger, outcomes)
    metrics = runway_metrics(ledger, queue)
    metrics["estimated_time_to_checkpoint"] = estimated_time_to_checkpoint(metrics)
    exceptions = exception_rows(queue)
    metrics["exception_count"] = int(len(exceptions))
    bottleneck = "none"
    if metrics["qualified_today"] == 0:
        bottleneck = "promoted_subset_qualification"
    elif metrics["exception_count"] > 0 and metrics["contract_passed_today"] == 0:
        bottleneck = text(exceptions.iloc[0].get("blocked_stage")) if not exceptions.empty else "exception"
    elif not confirm_paper_entry and metrics["contract_passed_today"] > 0:
        bottleneck = "preview_only"

    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "collection_mode": "autonomous_local_paper_research",
        "broad_orb_status": "unchanged_shadow_forward",
        "manual_paper_watch_status": "autonomous_paper_research_ready" if metrics["qualified_today"] else "waiting_for_candidate",
        "checkpoint_trades": CHECKPOINT_TRADES,
        "metrics": metrics,
        "biggest_operational_bottleneck": bottleneck,
        "queue_rows": json_records(queue),
        "contract_rows": json_records(contract_rows),
        "contract_template_rows": json_records(template),
        "exception_rows": json_records(exceptions),
        "ledger_rows": json_records(ledger),
        "source_files": {
            "observations": str(observations_csv),
            "operator_reviews": str(review_csv),
            "contract_audit": str(contract_audit_csv),
            "ledger": str(ledger_csv),
            "broad_orb_forward_outcomes": str(outcomes_csv),
        },
        "guardrail": (
            "Morning Index ORB Manual Paper-Watch is autonomous local-paper research only. It never places broker "
            "orders, never enables live execution, never counts toward VWAP's 30-trade checkpoint, and does not alter "
            "broad ORB shadow/forward collection."
        ),
        "safety_assertions": safety_assertions(ledger_csv),
        "evidence_integrity_note": (
            "2026-08-06 remains MEDIUM-confidence for full-session VWAP opportunity-frequency analysis. "
            "That operational exception does not invalidate the accumulated ORB promotion decision."
        ),
    }


def write_outputs(
    output_dir: Path,
    payload: dict[str, Any],
    *,
    review_csv: Path = REVIEW_CSV,
    contract_audit_csv: Path = CONTRACT_AUDIT_CSV,
    ledger_csv: Path = LEDGER_CSV,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    queue = pd.DataFrame(payload["queue_rows"], columns=QUEUE_COLUMNS)
    contract_rows = pd.DataFrame(payload["contract_rows"], columns=GATE_COLUMNS)
    template = pd.DataFrame(payload["contract_template_rows"], columns=CONTRACT_AUDIT_COLUMNS)
    exceptions = pd.DataFrame(payload["exception_rows"], columns=EXCEPTION_COLUMNS)
    ledger = pd.DataFrame(payload["ledger_rows"], columns=LEDGER_COLUMNS)
    review_template = queue[["candidate_id", "trading_date", "signal_timestamp_et", "symbol"]].copy() if not queue.empty else pd.DataFrame(columns=REVIEW_COLUMNS[:4])
    review_template["operator_review_status"] = "pending"
    review_template["operator_review_reason"] = ""
    review_template["reviewed_at_et"] = ""

    (output_dir / "morning_index_orb_manual_paper_watch.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    queue.to_csv(output_dir / "morning_index_orb_manual_paper_watch_queue.csv", index=False)
    contract_rows.to_csv(output_dir / "morning_index_orb_contract_gate.csv", index=False)
    template.to_csv(output_dir / "morning_index_orb_contract_gate_template.csv", index=False)
    exceptions.to_csv(output_dir / "morning_index_orb_autonomy_exceptions.csv", index=False)
    review_template.to_csv(output_dir / "morning_index_orb_manual_review_template.csv", index=False)
    ledger_csv.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(ledger_csv, index=False)

    metrics = payload["metrics"]
    report_path = output_dir / "morning_index_orb_manual_paper_watch.md"
    report_path.write_text(
        f"""# Morning SPY/QQQ Long ORB Manual Paper-Watch

Generated: {payload["generated_at_et"]}

This is the promoted narrow ORB Manual Paper-Watch lane. Broad ORB remains
shadow/forward research.

## Summary

```text
Strategy ID: {payload["strategy_id"]}
Status: {payload["manual_paper_watch_status"]}
Completed: {metrics["completed_count"]}/{payload["checkpoint_trades"]}
Open: {metrics["open_count"]}
Average R: {metrics["average_r"]}
Profit factor: {metrics["profit_factor"]}
Max drawdown R: {metrics["max_drawdown_r"]}
Win rate: {metrics["win_rate_pct"]}%
Estimated time to checkpoint: {metrics["estimated_time_to_checkpoint"]}
Biggest bottleneck: {payload["biggest_operational_bottleneck"]}
```

## Today

```text
Candidates detected: {metrics["candidates_detected_today"]}
Qualified promoted candidates: {metrics["qualified_today"]}
Operator reviewed: {metrics["operator_reviewed_today"]}
Approved: {metrics["approved_today"]}
Rejected: {metrics["rejected_today"]}
Contract passed: {metrics["contract_passed_today"]}
Contract failed: {metrics["contract_failed_today"]}
Autonomy exceptions: {metrics["exception_count"]}
```

## Queue

{markdown_table(queue)}

## Contract Gate

{markdown_table(contract_rows)}

## Autonomy Exceptions

{markdown_table(exceptions)}

Routine qualifying paper candidates do not require operator approval. Human
review is reserved for stale data, missing contract data, sizing failures,
Contract Gate blocks, duplicate conflicts, data-health issues, or other
unexpected states.

## Files

```text
logs/morning_index_orb_manual_paper_watch_queue.csv
logs/morning_index_orb_contract_gate_template.csv
logs/morning_index_orb_autonomy_exceptions.csv
{contract_audit_csv}
{ledger_csv}
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
    payload = build_payload(
        output_dir=args.output_dir,
        observations_csv=args.observations_csv,
        outcomes_csv=args.outcomes_csv,
        review_csv=args.review_csv,
        contract_audit_csv=args.contract_audit_csv,
        ledger_csv=args.ledger_csv,
        refresh_audit_csv=args.refresh_audit_csv,
        account_size=args.account_size,
        risk_per_trade_pct=args.risk_per_trade_pct,
        confirm_paper_entry=args.confirm_paper_entry,
    )
    write_outputs(
        args.output_dir,
        payload,
        review_csv=args.review_csv,
        contract_audit_csv=args.contract_audit_csv,
        ledger_csv=args.ledger_csv,
    )
    print(f"{STRATEGY_NAME} Manual Paper-Watch status: {payload['manual_paper_watch_status']}")
    print(f"Completed ORB Manual Paper-Watch trades: {payload['metrics']['completed_count']}/{CHECKPOINT_TRADES}")
    print("No broker orders, live orders, or VWAP validation rows were created.")


if __name__ == "__main__":
    main()
