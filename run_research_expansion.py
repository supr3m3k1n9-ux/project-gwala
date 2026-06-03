"""Run broad research-universe backtests.

This is research/backtesting only. It does not change the approved playbook,
scan live candidates, create alerts, or place trades. Use it to gather more
historical evidence before promoting any symbol/setup into the active workflow.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from config.research_universe import RESEARCH_UNIVERSES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run broad Project Gwala research expansion.")
    parser.add_argument(
        "--universe",
        choices=sorted(RESEARCH_UNIVERSES),
        default="liquid_options",
        help="Research universe to test.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs/universe_expansion"))
    parser.add_argument("--reuse-csv", action="store_true", help="Reuse existing CSVs instead of fetching Webull data.")
    parser.add_argument("--entry-pages", type=int, default=2, help="30m history pages.")
    parser.add_argument("--exit-pages", type=int, default=6, help="5m history pages.")
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Webull requests.")
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    """Run one research command."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    symbols = RESEARCH_UNIVERSES[args.universe]
    base_command = [
        sys.executable,
        "run_webull_watchlist.py",
        "--symbols",
        *symbols,
        "--entry-pages",
        str(args.entry_pages),
        "--exit-pages",
        str(args.exit_pages),
        "--pause",
        str(args.pause),
        "--output-dir",
        str(args.output_dir),
    ]
    if args.reuse_csv:
        base_command.append("--reuse-csv")

    run_step([*base_command, "--candidate-preset", "best_plus_market"])
    run_step([*base_command, "--reuse-csv", "--candidate-preset", "setup_b"])
    run_step([sys.executable, "run_research_confidence.py", "--output-dir", str(args.output_dir)])

    print("\nResearch expansion complete.")
    print(f"Symbols tested: {', '.join(symbols)}")
    print(f"Reports saved in: {args.output_dir}")


if __name__ == "__main__":
    main()
