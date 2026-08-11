"""Polygon market-data helpers.

This module is data-only. It reads candles from Polygon and writes the same
local CSV shape the existing research workflow already uses. It does not place
orders, connect to a broker, create alerts, or import paper trades.
"""

from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import certifi
import pandas as pd

from data.candle_cache import save_candle_cache
from data.market_data import REQUIRED_CSV_COLUMNS
from data.webull_data import load_env_file


POLYGON_BASE_URL = "https://api.polygon.io"
TIMEFRAME_MAP = {
    "M1": (1, "minute"),
    "M5": (5, "minute"),
    "M15": (15, "minute"),
    "M30": (30, "minute"),
    "M60": (1, "hour"),
    "D": (1, "day"),
}


def polygon_api_key() -> str:
    """Return the Polygon API key from .env without printing it."""

    load_env_file()
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key or key.startswith("paste_") or key.startswith("your_"):
        raise SystemExit("Missing POLYGON_API_KEY. Add it to .env before running Polygon data tools.")
    return key


def timeframe_to_polygon(timeframe: str) -> tuple[int, str]:
    """Return Polygon multiplier/timespan for a local timeframe label."""

    normalized = timeframe.upper()
    if normalized not in TIMEFRAME_MAP:
        supported = ", ".join(sorted(TIMEFRAME_MAP))
        raise ValueError(f"Unsupported timeframe {timeframe}. Supported values: {supported}.")
    return TIMEFRAME_MAP[normalized]


def polygon_aggs_url(
    *,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    adjusted: bool,
    api_key: str,
    base_url: str = POLYGON_BASE_URL,
) -> str:
    """Build the Polygon aggregate-bars URL."""

    multiplier, timespan = timeframe_to_polygon(timeframe)
    query = urlencode(
        {
            "adjusted": str(adjusted).lower(),
            "sort": "asc",
            "limit": 50000,
            "apiKey": api_key,
        }
    )
    return (
        f"{base_url}/v2/aggs/ticker/{symbol.upper()}/range/"
        f"{multiplier}/{timespan}/{start_date}/{end_date}?{query}"
    )


def fetch_polygon_aggs(url: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch one Polygon aggregate response."""

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlopen(url, timeout=timeout, context=ssl_context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Polygon returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Polygon request failed: {exc.reason}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Polygon returned an unexpected response shape.")
    return payload


def normalize_polygon_aggs(payload: dict[str, Any]) -> pd.DataFrame:
    """Normalize Polygon aggregate rows to local candle CSV columns."""

    rows = payload.get("results", [])
    if not isinstance(rows, list) or not rows:
        status = payload.get("status", "unknown")
        ticker = payload.get("ticker", "unknown")
        raise ValueError(f"No Polygon candles returned for {ticker}; status={status}.")

    candles = pd.DataFrame(
        {
            "datetime": pd.to_datetime([row.get("t") for row in rows], unit="ms", utc=True, errors="coerce"),
            "open": [row.get("o") for row in rows],
            "high": [row.get("h") for row in rows],
            "low": [row.get("l") for row in rows],
            "close": [row.get("c") for row in rows],
            "volume": [row.get("v") for row in rows],
        }
    )
    for column in ["open", "high", "low", "close", "volume"]:
        candles[column] = pd.to_numeric(candles[column], errors="coerce")

    candles = candles.dropna(subset=REQUIRED_CSV_COLUMNS)
    if candles.empty:
        raise ValueError("Polygon response did not contain any valid candle rows.")

    candles = candles.drop_duplicates(subset=["datetime"], keep="last")
    candles = candles.sort_values("datetime")
    candles["datetime"] = candles["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return candles[REQUIRED_CSV_COLUMNS]


def import_polygon_candles(
    *,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    adjusted: bool = True,
    api_key: str | None = None,
) -> Path:
    """Fetch Polygon candles and save them to the local reuse-csv cache."""

    key = api_key or polygon_api_key()
    url = polygon_aggs_url(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        adjusted=adjusted,
        api_key=key,
    )
    payload = fetch_polygon_aggs(url)
    candles = normalize_polygon_aggs(payload)

    output_dir.mkdir(parents=True, exist_ok=True)
    return save_candle_cache(candles, output_dir, symbol, timeframe, write_legacy_alias=True)
