"""Paper-watch gate for Opening Range Breakout.

This report is research-to-paper-watch only. It does not place orders, create
broker alerts, or enable live execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from run_research_strategy_paper_watch_gate import build_gate_for_strategy, write_gate_outputs


STRATEGY_ID = "opening_range_breakout"
STRATEGY_NAME = "Opening Range Breakout"
STEM = "opening_range_breakout"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Opening Range Breakout paper-watch gate.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--min-tightened-pass-rows", type=int, default=1)
    parser.add_argument("--min-walk-forward-holding-rows", type=int, default=1)
    parser.add_argument("--min-shadow-samples", type=int, default=10)
    parser.add_argument("--min-matured-shadow-samples", type=int, default=5)
    parser.add_argument("--min-shadow-average-r", type=float, default=0.10)
    parser.add_argument("--min-forward-observations", type=int, default=10)
    parser.add_argument("--min-matured-forward-observations", type=int, default=5)
    parser.add_argument("--min-forward-average-r", type=float, default=0.10)
    return parser.parse_args()


def build_gate(args: argparse.Namespace):
    """Build the Opening Range Breakout paper-watch gate."""

    return build_gate_for_strategy(
        strategy_id=STRATEGY_ID,
        strategy_name=STRATEGY_NAME,
        stem=STEM,
        args=args,
    )


def main() -> None:
    args = parse_args()
    payload, checklist = build_gate(args)
    write_gate_outputs(args.output_dir, STEM, payload, checklist)
    print(f"{STRATEGY_NAME} paper-watch decision: {payload['decision']}")
    print(f"Next blocker: {payload['next_blocker']}")
    print(f"Saved paper-watch gate report: {args.output_dir / f'{STEM}_paper_watch_gate.md'}")


if __name__ == "__main__":
    main()
