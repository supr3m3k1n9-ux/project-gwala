"""Small Webull OpenAPI market-data connection test.

This script is intentionally data-only. It does not import order/trading
clients and it does not place, modify, or cancel orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.webull_data import (
    build_data_client,
    fetch_history_bars,
    print_safe_webull_error,
    write_backtest_csv,
    write_raw_json,
)


OUTPUT_DIR = PROJECT_ROOT / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test Webull market-data access.")
    parser.add_argument("--symbol", default="SPY", help="Ticker to request, for example SPY.")
    parser.add_argument(
        "--timespan",
        default="M5",
        choices=["M1", "M5", "M15", "M30", "M60", "D"],
        help="Webull candle size to request.",
    )
    parser.add_argument("--count", default="20", help="Number of candles to request.")
    parser.add_argument(
        "--sessions",
        nargs="*",
        default=["RTH"],
        help="Trading sessions to request. Common values: PRE RTH ATH OVN.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Where probe-only output files are saved.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        data_client = build_data_client()
        payload = fetch_history_bars(
            data_client=data_client,
            symbol=args.symbol,
            timespan=args.timespan,
            count=int(args.count),
            trading_sessions=args.sessions,
        )
    except Exception as exc:
        print_safe_webull_error(exc)

    output_path = args.output_dir / f"webull_probe_{args.symbol.upper()}_{args.timespan}.json"
    write_raw_json(payload, output_path)
    print(f"Saved raw Webull response: {output_path}")

    if payload:
        # A connectivity probe must never replace full workflow candle caches.
        csv_path = args.output_dir / f"webull_probe_{args.symbol.upper()}_{args.timespan}_candles.csv"
        write_backtest_csv(payload, csv_path)
        print(f"Saved backtester-ready CSV: {csv_path}")

    print("HTTP status: 200")
    print("Response preview:")
    print(json.dumps(payload[:3], indent=2, sort_keys=True)[:2000])


if __name__ == "__main__":
    main()
