"""Local paper execution helpers.

This module intentionally does not call Webull trading endpoints. It converts
eligible scanner/sizing rows into local paper order tickets and open rows in
`data/paper_trades.csv` so the workflow can practice order lifecycle handling
before any broker integration exists.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_paper_import import PAPER_COLUMNS, read_existing


PAPER_ORDER_COLUMNS = [
    "paper_order_id",
    "created_at_et",
    "trade_date",
    "entry_time_et",
    "symbol",
    "setup",
    "direction",
    "side",
    "order_type",
    "limit_price",
    "stop_price",
    "target_price",
    "shares",
    "vehicle",
    "risk_tier",
    "planned_option_premium",
    "status",
    "source",
    "notes",
    "invalid_for_validation",
    "invalid_reason",
    "invalidated_at_et",
    "original_creation_timestamp",
    "incident_id",
    "source_contract_gate_identity",
]


def read_orders(path: Path) -> pd.DataFrame:
    """Read the local paper order ledger or create an empty one."""

    if not path.exists():
        return pd.DataFrame(columns=PAPER_ORDER_COLUMNS)
    orders = pd.read_csv(path)
    for column in PAPER_ORDER_COLUMNS:
        if column not in orders.columns:
            orders[column] = ""
    return orders[PAPER_ORDER_COLUMNS]


def eligible_sizing_rows(sizing: pd.DataFrame) -> pd.DataFrame:
    """Return rows that are eligible for local paper execution."""

    if sizing.empty or "sizing_status" not in sizing.columns:
        return pd.DataFrame(columns=sizing.columns)
    return sizing[
        (sizing["sizing_status"] == "size_ok")
        & (sizing["scanner_status"] == "allowed")
        & (sizing["signal_freshness"] == "current_candle")
        & (pd.to_numeric(sizing["suggested_shares"], errors="coerce") > 0)
    ].copy()


def row_key(frame: pd.DataFrame) -> pd.Series:
    """Build a duplicate-prevention key for paper order/trade rows."""

    return frame[["trade_date", "entry_time_et", "symbol", "setup", "direction"]].astype(str).agg("|".join, axis=1)


def attach_trade_dates(rows: pd.DataFrame) -> pd.DataFrame:
    """Add trade_date and entry_time_et from latest_signal_et."""

    result = rows.copy()
    signal_times = pd.to_datetime(result["latest_signal_et"], errors="coerce")
    result["trade_date"] = signal_times.dt.date.astype(str)
    result["entry_time_et"] = signal_times.dt.strftime("%H:%M")
    return result


def build_local_paper_orders(rows: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Create local paper order tickets from eligible sizing rows."""

    if rows.empty:
        return pd.DataFrame(columns=PAPER_ORDER_COLUMNS)

    now = now or datetime.now(MARKET_TZ)
    timestamp = now.astimezone(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    prepared = attach_trade_dates(rows)
    orders = []
    for _, row in prepared.iterrows():
        direction = str(row["direction"]).lower()
        side = "BUY" if direction == "long" else "SELL_SHORT"
        order_id = f"PG-PAPER-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        orders.append(
            {
                "paper_order_id": order_id,
                "created_at_et": timestamp,
                "trade_date": row["trade_date"],
                "entry_time_et": row["entry_time_et"],
                "symbol": row["symbol"],
                "setup": row["setup"],
                "direction": direction,
                "side": side,
                "order_type": "LOCAL_LIMIT_SIM",
                "limit_price": row["planned_entry"],
                "stop_price": row["planned_stop"],
                "target_price": row["planned_target"],
                "shares": int(row["suggested_shares"]),
                "vehicle": "options",
                "risk_tier": str(row.get("scale_tier", "")),
                "planned_option_premium": "",
                "status": "local_paper_filled",
                "source": "position_sizing_size_ok",
                "notes": "Local paper simulation only; no broker order was sent.",
                "invalid_for_validation": "",
                "invalid_reason": "",
                "invalidated_at_et": "",
                "original_creation_timestamp": "",
                "incident_id": "",
                "source_contract_gate_identity": "",
            }
        )
    return pd.DataFrame(orders, columns=PAPER_ORDER_COLUMNS)


def orders_to_open_paper_trades(orders: pd.DataFrame) -> pd.DataFrame:
    """Convert local paper orders into open paper-trade log rows."""

    rows = []
    for _, row in orders.iterrows():
        rows.append(
            {
                "trade_date": row["trade_date"],
                "entry_time_et": row["entry_time_et"],
                "exit_time_et": "",
                "symbol": row["symbol"],
                "setup": row["setup"],
                "direction": row["direction"],
                "signal_status": "allowed",
                "planned_entry": row["limit_price"],
                "planned_stop": row["stop_price"],
                "planned_target": row["target_price"],
                "actual_entry": row["limit_price"],
                "actual_exit": "",
                "shares": row["shares"],
                "vehicle": row.get("vehicle", "options"),
                "risk_tier": row.get("risk_tier", ""),
                "planned_option_premium": row.get("planned_option_premium", ""),
                "outcome_r": "",
                "followed_plan": "",
                "exit_reason": "",
                "notes": f"Opened by local paper simulator; order_id={row['paper_order_id']}",
                "invalid_for_validation": row.get("invalid_for_validation", ""),
                "invalid_reason": row.get("invalid_reason", ""),
                "invalidated_at_et": row.get("invalidated_at_et", ""),
                "original_creation_timestamp": row.get("original_creation_timestamp", ""),
                "incident_id": row.get("incident_id", ""),
                "source_contract_gate_identity": row.get("source_contract_gate_identity", ""),
            }
        )
    return pd.DataFrame(rows, columns=PAPER_COLUMNS)


def filter_new_orders(existing_orders: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Keep only paper orders that are not already in the order ledger."""

    if orders.empty or existing_orders.empty:
        return orders.copy()
    existing_keys = set(row_key(existing_orders))
    order_keys = row_key(orders)
    return orders[~order_keys.isin(existing_keys)].copy()


def filter_new_trades(existing_trades: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """Keep only open paper trades that are not already in the trade log."""

    if trades.empty or existing_trades.empty:
        return trades.copy()
    existing_keys = set(row_key(existing_trades))
    trade_keys = row_key(trades)
    return trades[~trade_keys.isin(existing_keys)].copy()


def write_open_paper_trades(path: Path, new_trades: pd.DataFrame) -> pd.DataFrame:
    """Append open local paper trades to the manual paper log."""

    existing = read_existing(path)
    filtered = filter_new_trades(existing, new_trades)
    combined = pd.concat([existing, filtered], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return filtered
