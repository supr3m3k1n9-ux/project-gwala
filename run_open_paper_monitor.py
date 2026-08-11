"""Monitor open local paper trades against saved 5m candles.

This is research and paper-validation only. It previews or applies paper-trade
exit updates from local Webull candle files. It does not place orders, create
broker alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.settings import STRATEGY
from data.market_data import load_candles_from_csv
from indicators.session import add_session_columns
from run_paper_import import read_existing
from run_playbook import markdown_table


UPDATE_COLUMNS = [
    "row",
    "trade_date",
    "symbol",
    "setup",
    "direction",
    "entry_time_et",
    "exit_time_et",
    "actual_entry",
    "actual_exit",
    "shares",
    "outcome_r",
    "exit_reason",
    "monitor_status",
    "monitor_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor open Project Gwala paper trades.")
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"), help="Paper trade log.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Directory with Webull M5 candle CSVs.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where monitor reports are saved.")
    parser.add_argument(
        "--confirm-updates",
        action="store_true",
        help="Write completed monitor updates to data/paper_trades.csv. Defaults to preview only.",
    )
    return parser.parse_args()


def text_value(value: object) -> str:
    """Return clean text from a CSV value."""

    if pd.isna(value):
        return ""
    return str(value).strip()


def number_or_none(value: object) -> float | None:
    """Convert a CSV value to float when possible."""

    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def open_paper_rows(trades: pd.DataFrame) -> pd.DataFrame:
    """Return paper rows that still need an exit outcome."""

    if trades.empty:
        return trades.copy()
    missing_exit = trades["actual_exit"].isna() | (trades["actual_exit"].astype(str).str.strip() == "")
    missing_r = trades["outcome_r"].isna() | (trades["outcome_r"].astype(str).str.strip() == "")
    rows = trades[missing_exit | missing_r].copy()
    if "invalid_for_validation" in rows.columns:
        invalid = rows["invalid_for_validation"].astype(str).str.lower().isin(["1", "true", "yes", "y"])
        rows = rows[~invalid].copy()
    rows.insert(0, "row", rows.index + 1)
    return rows


def r_result(direction: str, entry: float, exit_price: float, stop: float) -> float:
    """Calculate R for a paper trade."""

    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("Risk per share must be greater than zero.")
    if direction == "short":
        return round((entry - exit_price) / risk, 4)
    return round((exit_price - entry) / risk, 4)


def local_entry_timestamp(trade_date: str, entry_time_et: str) -> pd.Timestamp:
    """Return an ET timestamp for the paper entry."""

    return pd.Timestamp(f"{trade_date} {entry_time_et}", tz=MARKET_TZ)


def load_symbol_m5(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Load saved Webull M5 candles for a symbol and add session columns."""

    path = data_dir / f"webull_{symbol}_M5_candles.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing M5 candles for {symbol}: {path}")
    candles = load_candles_from_csv(path, symbol)
    return add_session_columns(candles, STRATEGY)


def monitor_trade(row: pd.Series, data_dir: Path) -> dict[str, object]:
    """Preview the next paper outcome update for one open trade."""

    symbol = text_value(row["symbol"]).upper()
    direction = text_value(row["direction"]).lower()
    trade_date = text_value(row["trade_date"])
    entry_time = text_value(row["entry_time_et"])
    entry = number_or_none(row.get("actual_entry")) or number_or_none(row.get("planned_entry"))
    stop = number_or_none(row.get("planned_stop"))
    target = number_or_none(row.get("planned_target"))
    shares = text_value(row.get("shares"))

    base = {
        "row": int(row["row"]),
        "trade_date": trade_date,
        "symbol": symbol,
        "setup": text_value(row["setup"]),
        "direction": direction,
        "entry_time_et": entry_time,
        "exit_time_et": "",
        "actual_entry": entry if entry is not None else "",
        "actual_exit": "",
        "shares": shares,
        "outcome_r": "",
        "exit_reason": "",
        "monitor_status": "open",
        "monitor_note": "",
    }

    if entry is None or stop is None or target is None:
        base["monitor_status"] = "blocked"
        base["monitor_note"] = "Missing actual/planned entry, stop, or target."
        return base

    candles = load_symbol_m5(data_dir, symbol)
    entry_ts = local_entry_timestamp(trade_date, entry_time)
    future = candles[
        (candles.index > entry_ts)
        & (candles["session_date"].astype(str) == trade_date)
        & (candles["regular_session"])
    ]
    if future.empty:
        base["monitor_note"] = "No post-entry 5m candles are available yet."
        return base

    last_ts = future.index[-1]
    last_row = future.iloc[-1]
    for timestamp, candle in future.iterrows():
        exit_price = None
        exit_reason = None

        if direction == "short":
            if float(candle["high"]) >= stop:
                exit_price = stop
                exit_reason = "stop_loss_5m"
            elif float(candle["low"]) <= target:
                exit_price = target
                exit_reason = "profit_target_5m"
        else:
            if float(candle["low"]) <= stop:
                exit_price = stop
                exit_reason = "stop_loss_5m"
            elif float(candle["high"]) >= target:
                exit_price = target
                exit_reason = "profit_target_5m"

        if exit_price is None and bool(candle.get("force_exit_window", False)):
            exit_price = float(candle["close"])
            exit_reason = "end_of_day_exit"

        if exit_price is not None:
            base.update(
                {
                    "exit_time_et": timestamp.tz_convert(MARKET_TZ).strftime("%H:%M"),
                    "actual_exit": round(float(exit_price), 4),
                    "outcome_r": r_result(direction, float(entry), float(exit_price), float(stop)),
                    "exit_reason": exit_reason,
                    "monitor_status": "exit_ready",
                    "monitor_note": "Exit condition found in saved M5 candles.",
                }
            )
            return base

    base["monitor_note"] = (
        f"Trade still open through latest saved candle "
        f"{last_ts.tz_convert(MARKET_TZ).strftime('%H:%M')} at close {round(float(last_row['close']), 4)}."
    )
    return base


def build_updates(trades: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Build monitor updates for all open paper trades."""

    rows = open_paper_rows(trades)
    if rows.empty:
        return pd.DataFrame(columns=UPDATE_COLUMNS)
    updates = []
    for _, row in rows.iterrows():
        try:
            updates.append(monitor_trade(row, data_dir))
        except (FileNotFoundError, ValueError) as error:
            updates.append(
                {
                    "row": int(row["row"]),
                    "trade_date": text_value(row.get("trade_date")),
                    "symbol": text_value(row.get("symbol")).upper(),
                    "setup": text_value(row.get("setup")),
                    "direction": text_value(row.get("direction")),
                    "entry_time_et": text_value(row.get("entry_time_et")),
                    "exit_time_et": "",
                    "actual_entry": text_value(row.get("actual_entry")),
                    "actual_exit": "",
                    "shares": text_value(row.get("shares")),
                    "outcome_r": "",
                    "exit_reason": "",
                    "monitor_status": "blocked",
                    "monitor_note": str(error),
                }
            )
    return pd.DataFrame(updates, columns=UPDATE_COLUMNS)


def apply_updates(trades: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    """Apply completed exit updates to the paper trade log."""

    result = trades.copy().astype(object)
    ready = updates[updates["monitor_status"] == "exit_ready"]
    for _, update in ready.iterrows():
        index = int(update["row"]) - 1
        for column in ["exit_time_et", "actual_entry", "actual_exit", "shares", "outcome_r", "exit_reason"]:
            result.at[index, column] = update[column]
        note = text_value(result.at[index, "notes"])
        monitor_note = f"Monitor updated {datetime.now(MARKET_TZ).strftime('%Y-%m-%d %H:%M %Z')}: {update['exit_reason']}"
        result.at[index, "notes"] = f"{note} | {monitor_note}" if note else monitor_note
        if not text_value(result.at[index, "followed_plan"]):
            result.at[index, "followed_plan"] = "yes"
    return result


def write_report(path: Path, updates: pd.DataFrame, confirmed: bool) -> None:
    """Write monitor preview report."""

    ready = updates[updates["monitor_status"] == "exit_ready"] if not updates.empty else pd.DataFrame()
    open_rows = updates[updates["monitor_status"] == "open"] if not updates.empty else pd.DataFrame()
    blocked = updates[updates["monitor_status"] == "blocked"] if not updates.empty else pd.DataFrame()

    path.write_text(
        f"""# Open Paper Trade Monitor

This report previews or records paper-trade exits from saved Webull M5 candles.

Important: this is research and paper-validation only. It does not place
orders, create broker alerts, call Webull order endpoints, or connect to broker
execution.

## Run Mode

```text
Confirmed updates: {confirmed}
```

## Exit Updates Ready

{markdown_table(ready)}

## Still Open

{markdown_table(open_rows)}

## Blocked / Needs Review

{markdown_table(blocked)}

## Write Command

```bash
.venv/bin/python run_open_paper_monitor.py --confirm-updates
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trades = read_existing(args.paper_csv)
    updates = build_updates(trades, args.data_dir)

    if args.confirm_updates and not updates.empty:
        updated = apply_updates(trades, updates)
        updated.to_csv(args.paper_csv, index=False)

    csv_path = args.output_dir / "open_paper_trade_monitor.csv"
    report_path = args.output_dir / "open_paper_trade_monitor.md"
    updates.to_csv(csv_path, index=False)
    write_report(report_path, updates, args.confirm_updates)

    ready_count = int((updates["monitor_status"] == "exit_ready").sum()) if not updates.empty else 0
    open_count = int((updates["monitor_status"] == "open").sum()) if not updates.empty else 0
    print(f"Exit updates ready: {ready_count}")
    print(f"Still open: {open_count}")
    print(f"Saved open paper monitor CSV: {csv_path}")
    print(f"Saved open paper monitor report: {report_path}")


if __name__ == "__main__":
    main()
