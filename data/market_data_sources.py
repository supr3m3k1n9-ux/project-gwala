"""Track where local market-data CSV files came from.

The candle filenames stay compatible with the existing workflow, but this
metadata keeps the provider visible for audits and the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ


SOURCE_COLUMNS = [
    "refreshed_at_et",
    "provider",
    "symbol",
    "timeframe",
    "path",
    "rows",
    "latest_candle_utc",
    "start_date",
    "end_date",
    "status",
    "message",
]


def read_sources(path: Path) -> pd.DataFrame:
    """Read existing source metadata."""

    if not path.exists():
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    for column in SOURCE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[SOURCE_COLUMNS]


def latest_source_for(path: Path, symbol: str, timeframe: str) -> dict[str, object]:
    """Return the newest successful source row for a symbol/timeframe."""

    sources = read_sources(path)
    if sources.empty:
        return {}
    mask = (
        sources["symbol"].astype(str).str.upper().eq(symbol.upper())
        & sources["timeframe"].astype(str).str.upper().eq(timeframe.upper())
    )
    matches = sources[mask]
    if matches.empty:
        return {}
    if "status" in matches.columns:
        successful = matches[matches["status"].astype(str) == "ok"]
        if not successful.empty:
            matches = successful
    return matches.iloc[-1].to_dict()


def source_row(
    *,
    provider: str,
    symbol: str,
    timeframe: str,
    candle_path: Path,
    candles: pd.DataFrame | None,
    start_date: str,
    end_date: str,
    status: str,
    message: str = "",
    refreshed_at: datetime | None = None,
) -> dict[str, object]:
    """Build one source metadata row."""

    refreshed = refreshed_at or datetime.now(MARKET_TZ)
    latest = ""
    rows = 0
    if candles is not None and not candles.empty:
        rows = int(len(candles))
        latest = str(candles["datetime"].iloc[-1]) if "datetime" in candles.columns else ""

    return {
        "refreshed_at_et": refreshed.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "provider": provider,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "path": str(candle_path),
        "rows": rows,
        "latest_candle_utc": latest,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "message": message,
    }


def append_sources(path: Path, rows: list[dict[str, object]]) -> pd.DataFrame:
    """Append source metadata rows and save them."""

    existing = read_sources(path)
    new_rows = pd.DataFrame(rows, columns=SOURCE_COLUMNS)
    combined = pd.concat([existing, new_rows], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return combined
