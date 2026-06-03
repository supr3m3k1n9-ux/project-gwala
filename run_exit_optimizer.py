"""Test exit-profile upgrades against the approved portfolio.

This is research/backtesting only. The script keeps the approved playbook
structure intact, changes one entry's exit at a time, then runs the portfolio
monthly-loss-stop rules so exit changes are judged by whole-portfolio behavior.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics
from config.symbol_playbook import PLAYBOOKS, PlaybookEntry
from run_playbook import markdown_table, selected_trade_log_path
from run_portfolio import PROFILE_PRESETS, build_equity_curve, simulate_portfolio
from run_webull_watchlist import (
    EXIT_PROFILES,
    MARKET_CONFIRMED_VARIANTS,
    normalize_metric,
    run_symbol_backtest,
    use_baseline_candidate_metrics,
)


DEFAULT_EXIT_PROFILES = [
    "no_vwap_exit",
    "current",
    "target_1_5r",
    "two_vwap_closes",
    "bearish_vwap_loss",
    "ema9_exit",
    "breakeven_after_1r",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize playbook exits through portfolio rules.")
    parser.add_argument("--mode", choices=sorted(PLAYBOOKS), default="approved", help="Playbook entries to test.")
    parser.add_argument(
        "--portfolio-profile",
        choices=sorted(PROFILE_PRESETS),
        default="monthly_stop_3r",
        help="Portfolio profile used to score each exit test.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull CSV files are stored.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--exit-profiles",
        nargs="+",
        default=DEFAULT_EXIT_PROFILES,
        choices=sorted(EXIT_PROFILES),
        help="Exit profiles to test.",
    )
    parser.add_argument(
        "--market-regime-symbol",
        default="SPY",
        help="Market symbol used by market-confirmed long variants.",
    )
    return parser.parse_args()


def load_entry_trades(
    entry: PlaybookEntry,
    data_dir: Path,
    output_dir: Path,
    market_regime_symbol: str,
    cache: dict[tuple[str, str, str], pd.DataFrame],
) -> pd.DataFrame:
    """Run or reuse one symbol/setup/exit backtest and return its selected trades."""

    cache_key = (entry.symbol, entry.variant, entry.exit_profile)
    if cache_key in cache:
        return cache[cache_key].copy()

    entry_csv = data_dir / f"webull_{entry.symbol}_M30_candles.csv"
    exit_csv = data_dir / f"webull_{entry.symbol}_M5_candles.csv"
    market_csv = None
    if entry.variant in MARKET_CONFIRMED_VARIANTS:
        market_csv = data_dir / f"webull_{market_regime_symbol.upper()}_M30_candles.csv"

    run_symbol_backtest(
        symbol=entry.symbol,
        entry_csv=entry_csv,
        exit_csv=exit_csv,
        output_dir=output_dir,
        variant=entry.variant,
        exit_profile_name=entry.exit_profile,
        market_csv=market_csv,
        market_symbol=market_regime_symbol.upper(),
    )

    trade_log = selected_trade_log_path(entry, output_dir)
    trades = pd.read_csv(trade_log)
    trades["playbook_setup"] = entry.setup_name
    trades["playbook_variant"] = entry.variant
    trades["playbook_exit_profile"] = entry.exit_profile
    trades["playbook_status"] = entry.status
    trades["playbook_direction"] = "short" if entry.variant.startswith("setup_b") else "long"
    trades["playbook_notes"] = entry.notes
    cache[cache_key] = trades
    return trades.copy()


def combine_entries(
    entries: list[PlaybookEntry],
    data_dir: Path,
    output_dir: Path,
    market_regime_symbol: str,
    cache: dict[tuple[str, str, str], pd.DataFrame],
) -> pd.DataFrame:
    """Build one combined playbook trade log for a candidate entry list."""

    frames = [
        load_entry_trades(entry, data_dir, output_dir, market_regime_symbol, cache)
        for entry in entries
    ]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if combined.empty:
        return combined

    combined["entry_time"] = pd.to_datetime(combined["entry_time"])
    return combined.sort_values(["entry_time", "symbol", "playbook_setup"]).reset_index(drop=True)


def score_portfolio(trades: pd.DataFrame, profile_name: str) -> dict:
    """Apply portfolio rules and return the scoring metrics."""

    profile = PROFILE_PRESETS[profile_name]
    accepted, skipped, _daily = simulate_portfolio(
        trades,
        max_open_positions=profile["max_open_positions"],
        max_open_per_symbol=profile["max_open_per_symbol"],
        max_trades_per_day=profile["max_trades_per_day"],
        max_daily_loss_r=profile["max_daily_loss_r"],
        max_monthly_loss_r=profile["max_monthly_loss_r"],
    )
    metrics = calculate_metrics(accepted)
    equity = build_equity_curve(accepted)
    final_r = 0.0 if equity.empty else float(equity.iloc[-1]["cumulative_r"])
    return {
        "accepted_trades": metrics.get("trades", 0),
        "skipped_trades": len(skipped),
        "win_rate": metrics.get("win_rate", 0),
        "expectancy_r": metrics.get("expectancy_r", 0),
        "profit_factor": metrics.get("profit_factor", 0),
        "max_drawdown_r": metrics.get("max_drawdown_r", 0),
        "final_cumulative_r": round(final_r, 4),
    }


def write_report(path: Path, results: pd.DataFrame, profile_name: str) -> None:
    """Write a plain-English optimizer report."""

    best = results.sort_values(
        ["expectancy_delta", "drawdown_delta", "final_r_delta"],
        ascending=[False, False, False],
    ).head(15)
    positive = results[results["expectancy_delta"] > 0].sort_values(
        ["expectancy_delta", "drawdown_delta"],
        ascending=[False, False],
    )

    path.write_text(
        f"""# Exit Optimizer Report

This report tests one exit-profile change at a time against the `{profile_name}`
portfolio profile.

Important: this is still research/backtesting only. It does not place orders,
create alerts, or connect to broker execution.

## Best One-Change Tests

{markdown_table(best)}

## Positive Expectancy Changes

{markdown_table(positive)}

## Files

```text
logs/exit_optimizer_results.csv
logs/exit_optimizer_report.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    base_entries = PLAYBOOKS[args.mode]
    cache: dict[tuple[str, str, str], pd.DataFrame] = {}

    print("=== Scoring current playbook ===", flush=True)
    base_trades = combine_entries(base_entries, args.data_dir, args.output_dir, args.market_regime_symbol, cache)
    base_score = score_portfolio(base_trades, args.portfolio_profile)

    rows = []
    for index, base_entry in enumerate(base_entries):
        for exit_profile in args.exit_profiles:
            if exit_profile == base_entry.exit_profile:
                continue

            test_entries = list(base_entries)
            test_entry = replace(base_entry, exit_profile=exit_profile)
            test_entries[index] = test_entry

            print(
                f"=== Testing {base_entry.symbol} {base_entry.setup_name}: "
                f"{base_entry.exit_profile} -> {exit_profile} ===",
                flush=True,
            )
            trades = combine_entries(test_entries, args.data_dir, args.output_dir, args.market_regime_symbol, cache)
            score = score_portfolio(trades, args.portfolio_profile)
            rows.append(
                {
                    "symbol": base_entry.symbol,
                    "setup": base_entry.setup_name,
                    "variant": base_entry.variant,
                    "old_exit": base_entry.exit_profile,
                    "new_exit": exit_profile,
                    **score,
                    "expectancy_delta": round(score["expectancy_r"] - base_score["expectancy_r"], 4),
                    "profit_factor_delta": round(score["profit_factor"] - base_score["profit_factor"], 4),
                    "drawdown_delta": round(score["max_drawdown_r"] - base_score["max_drawdown_r"], 4),
                    "final_r_delta": round(score["final_cumulative_r"] - base_score["final_cumulative_r"], 4),
                }
            )

    results = pd.DataFrame(rows)
    if not results.empty:
        results = results.apply(lambda column: column.map(normalize_metric))
        results = results.sort_values(
            ["expectancy_delta", "drawdown_delta", "final_r_delta"],
            ascending=[False, False, False],
        )

    csv_path = args.output_dir / "exit_optimizer_results.csv"
    report_path = args.output_dir / "exit_optimizer_report.md"
    results.to_csv(csv_path, index=False)
    write_report(report_path, results, args.portfolio_profile)

    print(f"\nBaseline {args.portfolio_profile}: {base_score}")
    print(f"Saved optimizer CSV: {csv_path}")
    print(f"Saved optimizer report: {report_path}")


if __name__ == "__main__":
    main()
