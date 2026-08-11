"""Refresh Polygon candles for the Project Gwala watchlist.

This is a data-only runner. It writes local candle CSV files that the existing
research and paper-validation workflow can reuse. It does not place orders,
create broker alerts, import paper trades, or enable execution.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from config.symbol_playbook import playbook_symbols
from data.candle_cache import candle_cache_path
from data.market_data_sources import append_sources, source_row
from data.polygon_data import TIMEFRAME_MAP, import_polygon_candles
from run_playbook import markdown_table


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")
DEFAULT_TIMEFRAMES = ["M5", "M30", "M60", "D"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Polygon market-data CSVs for a watchlist.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to refresh.")
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=DEFAULT_TIMEFRAMES,
        choices=sorted(TIMEFRAME_MAP),
        help="Timeframes to refresh.",
    )
    parser.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where candle CSVs are saved.")
    parser.add_argument(
        "--source-csv",
        type=Path,
        default=Path("logs") / "market_data_sources.csv",
        help="Provider metadata audit CSV.",
    )
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds to wait between Polygon requests.")
    parser.add_argument("--max-retries", type=int, default=2, help="Retries per symbol/timeframe when Polygon rate-limits.")
    parser.add_argument("--retry-wait", type=float, default=15.0, help="Seconds to wait after a Polygon rate limit.")
    parser.add_argument("--unadjusted", action="store_true", help="Request unadjusted Polygon bars.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Exit successfully when some requests fail. The failed rows are still recorded "
            "for integrity checks, but downstream reports can rebuild from the last saved cache."
        ),
    )
    return parser.parse_args()


def read_candles(path: Path) -> pd.DataFrame:
    """Read a just-written candle CSV for metadata."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def write_report(path: Path, rows: pd.DataFrame, source_csv: Path) -> None:
    """Write a plain-English Polygon refresh report."""

    ok_rows = rows[rows["status"] == "ok"] if not rows.empty else pd.DataFrame()
    failed_rows = rows[rows["status"] != "ok"] if not rows.empty else pd.DataFrame()
    status = rows.groupby("status").size().reset_index(name="requests") if not rows.empty else pd.DataFrame()
    path.write_text(
        f"""# Polygon Watchlist Refresh

This report records a Polygon data-only refresh for local research and paper
validation.

Important: this does not place orders, create broker alerts, import paper
trades, or enable live execution.

## Status Summary

{markdown_table(status)}

## Successful Imports

{markdown_table(ok_rows)}

## Failed Imports

{markdown_table(failed_rows)}

## Files

```text
{source_csv}
{path}
```
""",
        encoding="utf-8",
    )


def refresh_watchlist(args: argparse.Namespace) -> pd.DataFrame:
    """Refresh all requested symbol/timeframe combinations."""

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    symbols = [symbol.upper() for symbol in args.symbols]
    timeframes = [timeframe.upper() for timeframe in args.timeframes]
    for symbol in symbols:
        for timeframe in timeframes:
            candle_path = candle_cache_path(args.output_dir, symbol, timeframe)
            attempts = 0
            try:
                while True:
                    attempts += 1
                    try:
                        output_path = import_polygon_candles(
                            symbol=symbol,
                            timeframe=timeframe,
                            start_date=args.start_date,
                            end_date=args.end_date,
                            output_dir=args.output_dir,
                            adjusted=not args.unadjusted,
                        )
                        break
                    except RuntimeError as exc:
                        rate_limited = "HTTP 429" in str(exc)
                        if not rate_limited or attempts > args.max_retries + 1:
                            raise
                        print(
                            f"Polygon rate limit for {symbol} {timeframe}; "
                            f"waiting {args.retry_wait:g}s before retry {attempts}/{args.max_retries + 1}."
                        )
                        time.sleep(args.retry_wait)
                candles = read_candles(output_path)
                row = source_row(
                    provider="polygon",
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_path=output_path,
                    candles=candles,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    status="ok",
                    message=f"attempts={attempts}",
                )
                print(f"Imported Polygon {symbol} {timeframe}: {output_path} ({len(candles)} rows)")
            except Exception as exc:
                row = source_row(
                    provider="polygon",
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_path=candle_path,
                    candles=None,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    status="failed",
                    message=f"{exc}; attempts={attempts}",
                )
                print(f"Failed Polygon {symbol} {timeframe}: {exc}")
            rows.append(row)
            if args.pause:
                time.sleep(args.pause)
    append_sources(args.source_csv, rows)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    rows = refresh_watchlist(args)
    report_path = args.output_dir / "polygon_watchlist_refresh.md"
    write_report(report_path, rows, args.source_csv)
    failures = int((rows["status"] != "ok").sum()) if not rows.empty else 0
    print(f"Polygon refresh requests: {len(rows)}")
    print(f"Polygon refresh failures: {failures}")
    print(f"Saved source metadata: {args.source_csv}")
    print(f"Saved Polygon refresh report: {report_path}")
    if failures and args.allow_partial:
        print("Continuing after partial Polygon refresh; downstream integrity checks will flag missing or stale caches.")
    elif failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
