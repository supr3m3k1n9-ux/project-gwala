"""Test entry-filter upgrades against the approved portfolio.

This is research/backtesting only. The script keeps the approved playbook
structure intact, changes one entry variant at a time, then scores the result
through the monthly-loss-stop portfolio profile.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from config.symbol_playbook import PLAYBOOKS
from run_exit_optimizer import combine_entries, score_portfolio
from run_playbook import markdown_table
from run_portfolio import PROFILE_PRESETS
from run_webull_watchlist import normalize_metric


LONG_VARIANTS = [
    "current",
    "quality_entry",
    "market_confirmed",
    "quality_entry_market_confirmed",
]

SHORT_VARIANTS = [
    "setup_b_short",
    "setup_b_quality_short",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize playbook entry variants through portfolio rules.")
    parser.add_argument("--mode", choices=sorted(PLAYBOOKS), default="approved", help="Playbook entries to test.")
    parser.add_argument(
        "--portfolio-profile",
        choices=sorted(PROFILE_PRESETS),
        default="monthly_stop_3r",
        help="Portfolio profile used to score each entry test.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull CSV files are stored.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["SPY", "NVDA"],
        help="Limit optimization to specific weak symbols.",
    )
    parser.add_argument(
        "--market-regime-symbol",
        default="SPY",
        help="Market symbol used by market-confirmed long variants.",
    )
    return parser.parse_args()


def candidate_variants(direction: str) -> list[str]:
    """Return candidate entry variants for the current setup direction."""

    if direction == "short":
        return SHORT_VARIANTS
    return LONG_VARIANTS


def entry_direction(variant: str) -> str:
    """Infer whether a variant is a long or short setup."""

    return "short" if variant.startswith("setup_b") else "long"


def write_report(path: Path, results: pd.DataFrame, profile_name: str, symbols: list[str]) -> None:
    """Write a readable Markdown report."""

    best = results.sort_values(
        ["expectancy_delta", "drawdown_delta", "final_r_delta"],
        ascending=[False, False, False],
    ).head(15)
    positive = results[results["expectancy_delta"] > 0].sort_values(
        ["expectancy_delta", "drawdown_delta"],
        ascending=[False, False],
    )

    path.write_text(
        f"""# Entry Optimizer Report

This report tests one entry-variant change at a time against the `{profile_name}`
portfolio profile.

Symbols tested: {", ".join(symbols)}

Important: this is still research/backtesting only. It does not place orders,
create alerts, or connect to broker execution.

## Best One-Change Tests

{markdown_table(best)}

## Positive Expectancy Changes

{markdown_table(positive)}

## Files

```text
logs/entry_optimizer_results.csv
logs/entry_optimizer_report.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target_symbols = {symbol.upper() for symbol in args.symbols}

    base_entries = PLAYBOOKS[args.mode]
    cache = {}

    print("=== Scoring current playbook ===", flush=True)
    base_trades = combine_entries(base_entries, args.data_dir, args.output_dir, args.market_regime_symbol, cache)
    base_score = score_portfolio(base_trades, args.portfolio_profile)

    rows = []
    for index, base_entry in enumerate(base_entries):
        if base_entry.symbol.upper() not in target_symbols:
            continue

        direction = entry_direction(base_entry.variant)
        for variant in candidate_variants(direction):
            if variant == base_entry.variant:
                continue

            test_entries = list(base_entries)
            test_entry = replace(base_entry, variant=variant)
            test_entries[index] = test_entry

            print(
                f"=== Testing {base_entry.symbol} {base_entry.setup_name}: "
                f"{base_entry.variant} -> {variant} ===",
                flush=True,
            )
            trades = combine_entries(test_entries, args.data_dir, args.output_dir, args.market_regime_symbol, cache)
            score = score_portfolio(trades, args.portfolio_profile)
            rows.append(
                {
                    "symbol": base_entry.symbol,
                    "setup": base_entry.setup_name,
                    "old_variant": base_entry.variant,
                    "new_variant": variant,
                    "exit_profile": base_entry.exit_profile,
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

    csv_path = args.output_dir / "entry_optimizer_results.csv"
    report_path = args.output_dir / "entry_optimizer_report.md"
    results.to_csv(csv_path, index=False)
    write_report(report_path, results, args.portfolio_profile, sorted(target_symbols))

    print(f"\nBaseline {args.portfolio_profile}: {base_score}")
    print(f"Saved optimizer CSV: {csv_path}")
    print(f"Saved optimizer report: {report_path}")


if __name__ == "__main__":
    main()
