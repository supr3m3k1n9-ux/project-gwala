"""Collect Opening Range Breakout shadow samples."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import STRATEGY
from config.runtime_paths import runtime_data_path
from config.symbol_playbook import playbook_symbols
from data.market_data import load_candles_from_csv
from run_opening_range_breakout import add_research_columns, find_breakout_exit
from run_research_strategy_sample_lane import SampleLaneSpec, number_value, run_shadow_lane


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Opening Range Breakout shadow samples.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to inspect.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where saved Webull candles live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--shadow-csv", type=Path, default=runtime_data_path("opening_range_breakout_shadow_samples.csv"))
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


def load_frames(symbol: str, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    entry = load_candles_from_csv(args.data_dir / f"webull_{symbol}_{args.entry_timeframe}_candles.csv", symbol)
    exits = load_candles_from_csv(args.data_dir / f"webull_{symbol}_{args.exit_timeframe}_candles.csv", symbol)
    return add_research_columns(entry, exits)


def passes_filters(row: pd.Series, args: argparse.Namespace) -> bool:
    quality_score = int(number_value(row.get("or_breakout_quality_score")))
    relative_volume = number_value(row.get("or_breakout_relative_volume"))
    trend_gap_pct = number_value(row.get("or_breakout_trend_gap_pct"))
    return (
        quality_score >= args.min_quality_score
        and args.min_relative_volume <= relative_volume <= args.max_relative_volume
        and trend_gap_pct <= args.max_trend_gap_pct
    )


def plan_for_row(row: pd.Series, direction: str, args: argparse.Namespace) -> dict[str, Any] | None:
    entry = float(row["close"])
    if direction == "long":
        stop = min(float(row["low"]), float(row["opening_range_high"])) * (1 - STRATEGY.stop_buffer_pct)
        risk_per_share = entry - stop
        target = entry + (risk_per_share * args.target_r_multiple)
    else:
        stop = max(float(row["high"]), float(row["opening_range_low"])) * (1 + STRATEGY.stop_buffer_pct)
        risk_per_share = stop - entry
        target = entry - (risk_per_share * args.target_r_multiple)
    if risk_per_share <= 0:
        return None
    reward_multiple = abs(target - entry) / risk_per_share
    if reward_multiple < args.reward_multiple_floor:
        return None
    return {
        "planned_entry": round(entry, 4),
        "planned_stop": round(stop, 4),
        "planned_target": round(target, 4),
        "risk_per_share": round(risk_per_share, 4),
        "reward_multiple": round(float(reward_multiple), 4),
    }


SPEC = SampleLaneSpec(
    strategy_id="opening_range_breakout",
    strategy_name="Opening Range Breakout",
    stem="opening_range_breakout",
    signal_pairs=[("long", "or_breakout_long_signal"), ("short", "or_breakout_short_signal")],
    load_frames=load_frames,
    passes_filters=passes_filters,
    plan_for_row=plan_for_row,
    find_exit=find_breakout_exit,
    quality_score_column="or_breakout_quality_score",
    quality_grade_column="or_breakout_quality_grade",
    relative_volume_column="or_breakout_relative_volume",
    trend_gap_column="or_breakout_trend_gap_pct",
    gap_column=None,
    range_width_column="or_breakout_range_width_pct",
)


def main() -> None:
    args = parse_args()
    result = run_shadow_lane(SPEC, args)
    print(f"Opening Range Breakout shadow append status: {result['append_status']}")
    print(f"Recent strategy shadow candidates: {result['candidates']}")
    print(f"New strategy shadow samples appended: {result['appended']}")
    print(f"Matured strategy shadow outcomes: {result['matured']}")
    print(f"Saved strategy shadow report: {result['report_path']}")


if __name__ == "__main__":
    main()
