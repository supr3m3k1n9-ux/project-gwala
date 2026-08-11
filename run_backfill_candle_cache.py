"""Backfill provider-neutral candle cache files from legacy aliases.

This is a local file migration helper only. It copies existing compatible
`webull_SYMBOL_TIMEFRAME_candles.csv` files into `logs/candles/SYMBOL/TIMEFRAME.csv`.
It does not fetch data, place orders, or alter paper-trade logs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config.symbol_playbook import playbook_symbols
from data.candle_cache import candle_cache_path, legacy_candle_cache_path, save_candle_cache
from run_playbook import markdown_table


DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "M30", "M60", "D"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill provider-neutral candle cache files.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where candle cache files live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where the migration report is saved.")
    parser.add_argument("--symbols", nargs="+", default=playbook_symbols("approved_plus_watch"), help="Symbols to backfill.")
    parser.add_argument("--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES, help="Timeframes to backfill.")
    return parser.parse_args()


def backfill(args: argparse.Namespace) -> pd.DataFrame:
    """Copy legacy aliases into canonical cache paths."""

    rows = []
    for symbol in [value.upper() for value in args.symbols]:
        for timeframe in [value.upper() for value in args.timeframes]:
            legacy = legacy_candle_cache_path(args.data_dir, symbol, timeframe)
            canonical = candle_cache_path(args.data_dir, symbol, timeframe)
            if not legacy.exists():
                rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": "missing_legacy",
                        "legacy_path": str(legacy),
                        "canonical_path": str(canonical),
                        "rows": 0,
                    }
                )
                continue
            candles = pd.read_csv(legacy)
            output = save_candle_cache(candles, args.data_dir, symbol, timeframe, write_legacy_alias=False)
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "backfilled",
                    "legacy_path": str(legacy),
                    "canonical_path": str(output),
                    "rows": int(len(candles)),
                }
            )
    return pd.DataFrame(rows)


def write_report(path: Path, rows: pd.DataFrame) -> None:
    """Write a compact backfill report."""

    status = rows.groupby("status").size().reset_index(name="files") if not rows.empty else pd.DataFrame()
    path.write_text(
        f"""# Candle Cache Backfill

This report records the local migration from legacy candle filenames to the
provider-neutral candle cache.

Important: this does not fetch data, place orders, or alter paper-trade logs.

## Status Summary

{markdown_table(status)}

## Files

{markdown_table(rows)}
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = backfill(args)
    csv_path = args.output_dir / "candle_cache_backfill.csv"
    md_path = args.output_dir / "candle_cache_backfill.md"
    rows.to_csv(csv_path, index=False)
    write_report(md_path, rows)
    print(f"Backfilled files: {int((rows['status'] == 'backfilled').sum()) if not rows.empty else 0}")
    print(f"Saved backfill CSV: {csv_path}")
    print(f"Saved backfill report: {md_path}")


if __name__ == "__main__":
    main()

