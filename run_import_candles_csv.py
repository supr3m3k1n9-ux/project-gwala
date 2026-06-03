"""Import external candle CSV files into the local backtest cache.

This is a research helper only. It does not fetch data, place trades, or talk
to a broker. Its job is to take candles from a paid data export or another
tool and save them in the same shape the Webull backtest runner already uses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from data.market_data import REQUIRED_CSV_COLUMNS


TIMEFRAME_CHOICES = ["M1", "M5", "M15", "M30", "M60", "D"]

COLUMN_ALIASES = {
    "datetime": ["datetime", "date", "time", "timestamp", "bar_time", "start_time"],
    "open": ["open", "o"],
    "high": ["high", "h"],
    "low": ["low", "l"],
    "close": ["close", "c", "last"],
    "volume": ["volume", "vol", "v"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize an external candle CSV for local backtests.")
    parser.add_argument("--symbol", required=True, help="Ticker symbol, for example SPY.")
    parser.add_argument("--timeframe", required=True, choices=TIMEFRAME_CHOICES, help="Candle timeframe.")
    parser.add_argument("--source-csv", type=Path, required=True, help="CSV file to import.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where normalized candles are saved.")
    return parser.parse_args()


def normalized_column_map(columns: list[str]) -> dict[str, str]:
    """Match common vendor column names to the local candle schema."""

    lookup = {column.strip().lower(): column for column in columns}
    mapping = {}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[target] = lookup[alias]
                break
    return mapping


def normalize_external_candles(raw: pd.DataFrame) -> pd.DataFrame:
    """Return clean candles with datetime, OHLC, and volume columns."""

    mapping = normalized_column_map(list(raw.columns))
    missing = [column for column in REQUIRED_CSV_COLUMNS if column not in mapping]
    if missing:
        available = ", ".join(str(column) for column in raw.columns)
        raise ValueError(
            "Source CSV is missing required candle column(s): "
            f"{', '.join(missing)}. Available columns: {available}"
        )

    candles = pd.DataFrame()
    for target in REQUIRED_CSV_COLUMNS:
        candles[target] = raw[mapping[target]]

    candles["datetime"] = pd.to_datetime(candles["datetime"], errors="coerce", utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        candles[column] = pd.to_numeric(candles[column], errors="coerce")

    candles = candles.dropna(subset=REQUIRED_CSV_COLUMNS)
    if candles.empty:
        raise ValueError("Source CSV did not contain any valid candle rows.")

    candles = candles.drop_duplicates(subset=["datetime"], keep="last")
    candles = candles.sort_values("datetime")
    candles["datetime"] = candles["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return candles[REQUIRED_CSV_COLUMNS]


def import_candles(source_csv: Path, symbol: str, timeframe: str, output_dir: Path) -> Path:
    """Normalize one CSV and save it where reuse-csv backtests expect it."""

    if not source_csv.exists():
        raise FileNotFoundError(f"Source CSV not found: {source_csv}")

    raw = pd.read_csv(source_csv)
    candles = normalize_external_candles(raw)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"webull_{symbol.upper()}_{timeframe.upper()}_candles.csv"
    candles.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    args = parse_args()
    output_path = import_candles(args.source_csv, args.symbol, args.timeframe, args.output_dir)
    print(f"Imported normalized candles: {output_path}")
    print("Next step: run run_webull_watchlist.py with --reuse-csv against this output directory.")


if __name__ == "__main__":
    main()
