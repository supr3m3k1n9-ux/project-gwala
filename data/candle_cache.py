"""Provider-neutral candle cache paths.

The project originally used `webull_SYMBOL_TIMEFRAME_candles.csv` filenames.
Those files remain as compatibility aliases, but the canonical cache now lives
under `logs/candles/SYMBOL/TIMEFRAME.csv`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def candle_cache_path(data_dir: Path, symbol: str, timeframe: str) -> Path:
    """Return the provider-neutral candle cache path."""

    return data_dir / "candles" / symbol.upper() / f"{timeframe.upper()}.csv"


def legacy_candle_cache_path(data_dir: Path, symbol: str, timeframe: str) -> Path:
    """Return the old compatibility candle cache path."""

    return data_dir / f"webull_{symbol.upper()}_{timeframe.upper()}_candles.csv"


def preferred_candle_path(data_dir: Path, symbol: str, timeframe: str) -> Path:
    """Return the best available cache path for a symbol/timeframe."""

    canonical = candle_cache_path(data_dir, symbol, timeframe)
    if canonical.exists():
        return canonical
    return legacy_candle_cache_path(data_dir, symbol, timeframe)


def save_candle_cache(
    candles: pd.DataFrame,
    data_dir: Path,
    symbol: str,
    timeframe: str,
    write_legacy_alias: bool = True,
) -> Path:
    """Save candles to the canonical cache and optional legacy alias."""

    canonical = candle_cache_path(data_dir, symbol, timeframe)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    candles.to_csv(canonical, index=False)

    if write_legacy_alias:
        legacy = legacy_candle_cache_path(data_dir, symbol, timeframe)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        candles.to_csv(legacy, index=False)

    return canonical

