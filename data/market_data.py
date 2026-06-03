"""Historical market data loading.

The first implementation uses yfinance because it is easy to start with. Later,
this module can be swapped for Alpaca, Polygon.io, Interactive Brokers, or
another broker/data vendor without rewriting the strategy.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf


REQUIRED_CSV_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]


def download_candles(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Download historical OHLCV candles.

    Args:
        symbol: Ticker symbol, for example "SPY" or "NVDA".
        period: yfinance lookback period, for example "60d".
        interval: Candle interval, for example "30m" or "60m".

    Returns:
        A clean DataFrame with datetime index and lowercase OHLCV columns.
    """

    raw = yf.download(
        tickers=symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=True,
        progress=False,
    )

    if raw.empty:
        raise ValueError(f"No data returned for {symbol} {period} {interval}.")

    # yfinance can return multi-index columns. Flatten them for beginner-friendly
    # downstream code.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [column[0] for column in raw.columns]

    candles = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )

    candles.index = pd.to_datetime(candles.index)
    candles = candles[["open", "high", "low", "close", "volume"]].dropna()
    candles["symbol"] = symbol.upper()
    return candles


def load_candles_from_csv(path: Path, symbol: str) -> pd.DataFrame:
    """Load OHLCV candles from a local CSV file.

    The CSV route lets the research continue even when an internet data vendor
    is unavailable. Expected columns are:

    datetime,open,high,low,close,volume
    """

    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    raw = pd.read_csv(path)
    missing_columns = [column for column in REQUIRED_CSV_COLUMNS if column not in raw.columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"{path} is missing required column(s): {missing}")

    candles = raw[REQUIRED_CSV_COLUMNS].copy()
    candles["datetime"] = pd.to_datetime(candles["datetime"], errors="coerce")

    for column in ["open", "high", "low", "close", "volume"]:
        candles[column] = pd.to_numeric(candles[column], errors="coerce")

    candles = candles.dropna(subset=REQUIRED_CSV_COLUMNS)
    if candles.empty:
        raise ValueError(f"No valid candles found in {path}.")

    candles = candles.sort_values("datetime").set_index("datetime")
    candles = candles[["open", "high", "low", "close", "volume"]]
    candles["symbol"] = symbol.upper()
    return candles


def save_candles(candles: pd.DataFrame, path: Path) -> None:
    """Save candles to CSV so research runs can be inspected later."""

    path.parent.mkdir(parents=True, exist_ok=True)
    candles.to_csv(path)
