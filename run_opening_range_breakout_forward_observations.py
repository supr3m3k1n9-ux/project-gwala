"""Collect Opening Range Breakout forward observations."""

from __future__ import annotations

import argparse
from pathlib import Path

from config.symbol_playbook import playbook_symbols
from run_opening_range_breakout_shadow_samples import SPEC
from run_research_strategy_sample_lane import run_forward_lane


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Opening Range Breakout forward observations.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to inspect.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where saved Webull candles live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--observations-csv", type=Path, default=Path("data/opening_range_breakout_forward_observations.csv"))
    parser.add_argument("--entry-timeframe", default="M30")
    parser.add_argument("--exit-timeframe", default="M5")
    parser.add_argument("--target-r-multiple", type=float, default=1.20)
    parser.add_argument("--reward-multiple-floor", type=float, default=0.80)
    parser.add_argument("--min-quality-score", type=int, default=4)
    parser.add_argument("--min-relative-volume", type=float, default=0.80)
    parser.add_argument("--max-relative-volume", type=float, default=2.50)
    parser.add_argument("--max-trend-gap-pct", type=float, default=0.0120)
    parser.add_argument("--lookback-candles", type=int, default=16)
    parser.add_argument("--record-latest-snapshot", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_forward_lane(SPEC, args)
    print(f"Opening Range Breakout forward observation status: {result['append_status']}")
    print(f"Recent forward observation candidates: {result['candidates']}")
    print(f"New forward observations appended: {result['appended']}")
    print(f"Matured forward observation outcomes: {result['matured']}")
    print(f"Saved forward observation report: {result['report_path']}")


if __name__ == "__main__":
    main()
