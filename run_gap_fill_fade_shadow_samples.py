"""Collect Gap Fill / Gap Fade shadow samples.

Research/paper-validation only. These samples do not place orders, create
broker alerts, or count as official paper trades.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import STRATEGY
from config.symbol_playbook import playbook_symbols
from data.market_data import load_candles_from_csv
from run_gap_fill_fade import add_research_columns, find_gap_fade_exit
from run_research_strategy_sample_lane import SampleLaneSpec, number_value, run_shadow_lane


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Gap Fill / Gap Fade shadow samples.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to inspect.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where saved Webull candles live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--shadow-csv", type=Path, default=Path("data/gap_fill_fade_shadow_samples.csv"))
    parser.add_argument("--entry-timeframe", default="M30")
    parser.add_argument("--exit-timeframe", default="M5")
    parser.add_argument("--daily-timeframe", default="D")
    parser.add_argument("--reward-multiple-floor", type=float, default=0.70)
    parser.add_argument("--min-quality-score", type=int, default=4)
    parser.add_argument("--min-gap-pct", type=float, default=0.004)
    parser.add_argument("--max-gap-pct", type=float, default=0.040)
    parser.add_argument("--min-relative-volume", type=float, default=0.70)
    parser.add_argument("--max-relative-volume", type=float, default=2.80)
    parser.add_argument("--lookback-candles", type=int, default=16)
    parser.add_argument("--record-latest-snapshot", action="store_true")
    return parser.parse_args()


def load_frames(symbol: str, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and enrich saved gap-fill candles for one symbol."""

    entry = load_candles_from_csv(args.data_dir / f"webull_{symbol}_{args.entry_timeframe}_candles.csv", symbol)
    exits = load_candles_from_csv(args.data_dir / f"webull_{symbol}_{args.exit_timeframe}_candles.csv", symbol)
    daily = load_candles_from_csv(args.data_dir / f"webull_{symbol}_{args.daily_timeframe}_candles.csv", symbol)
    return add_research_columns(entry, exits, daily)


def passes_filters(row: pd.Series, args: argparse.Namespace) -> bool:
    """Apply the same gap-fill first-review filters as the backtest."""

    quality_score = int(number_value(row.get("gap_fade_quality_score")))
    relative_volume = number_value(row.get("gap_fade_relative_volume"))
    abs_gap_pct = abs(number_value(row.get("gap_fade_gap_pct")))
    return (
        quality_score >= args.min_quality_score
        and args.min_gap_pct <= abs_gap_pct <= args.max_gap_pct
        and args.min_relative_volume <= relative_volume <= args.max_relative_volume
    )


def plan_for_row(row: pd.Series, direction: str, args: argparse.Namespace) -> dict[str, Any] | None:
    """Return the planned gap-fill entry, stop, target, and R."""

    entry = float(row["close"])
    target = float(row["prior_close"])
    if direction == "long":
        stop = min(float(row["low"]), float(row["session_open"])) * (1 - STRATEGY.stop_buffer_pct)
        risk_per_share = entry - stop
        reward_per_share = target - entry
    else:
        stop = max(float(row["high"]), float(row["session_open"])) * (1 + STRATEGY.stop_buffer_pct)
        risk_per_share = stop - entry
        reward_per_share = entry - target
    if risk_per_share <= 0 or reward_per_share <= 0:
        return None
    reward_multiple = reward_per_share / risk_per_share
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
    strategy_id="gap_fill_fade",
    strategy_name="Gap Fill / Gap Fade",
    stem="gap_fill_fade",
    signal_pairs=[("long", "gap_fade_long_signal"), ("short", "gap_fade_short_signal")],
    load_frames=load_frames,
    passes_filters=passes_filters,
    plan_for_row=plan_for_row,
    find_exit=find_gap_fade_exit,
    quality_score_column="gap_fade_quality_score",
    quality_grade_column="gap_fade_quality_grade",
    relative_volume_column="gap_fade_relative_volume",
    trend_gap_column=None,
    gap_column="gap_fade_gap_pct",
    range_width_column=None,
)


def main() -> None:
    args = parse_args()
    result = run_shadow_lane(SPEC, args)
    print(f"Gap Fill / Gap Fade shadow append status: {result['append_status']}")
    print(f"Recent strategy shadow candidates: {result['candidates']}")
    print(f"New strategy shadow samples appended: {result['appended']}")
    print(f"Matured strategy shadow outcomes: {result['matured']}")
    print(f"Saved strategy shadow report: {result['report_path']}")


if __name__ == "__main__":
    main()
