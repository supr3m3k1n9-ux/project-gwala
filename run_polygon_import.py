"""Import Polygon candles into the local Project Gwala candle cache.

This is a data-only research helper. It does not place broker orders, create
alerts, import paper trades, or enable execution. The output CSV names match
the existing Webull cache shape so current scanners/backtests can reuse them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from data.polygon_data import TIMEFRAME_MAP, import_polygon_candles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Polygon aggregate candles into the local cache.")
    parser.add_argument("--symbol", required=True, help="Ticker symbol, for example SPY.")
    parser.add_argument("--timeframe", required=True, choices=sorted(TIMEFRAME_MAP), help="Local timeframe label.")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where normalized candles are saved.")
    parser.add_argument("--unadjusted", action="store_true", help="Request unadjusted bars instead of adjusted bars.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = import_polygon_candles(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        adjusted=not args.unadjusted,
    )
    print(f"Imported Polygon candles: {output_path}")
    print("Next step: run the scanner/backtest with --reuse-csv against this output directory.")


if __name__ == "__main__":
    main()
