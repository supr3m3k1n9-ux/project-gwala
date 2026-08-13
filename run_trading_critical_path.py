"""Run the market-hours trading critical path only.

This lane protects entry and exit timing from charting, research, reporting,
dashboard, and full-assurance work. It is paper/shadow only and never places
broker orders or enables live execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_root
from config.symbol_playbook import playbook_symbols


DEFAULT_SYMBOLS = sorted(playbook_symbols("approved_plus_watch"))
PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Project Gwala's trading critical path.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"))
    parser.add_argument("--data-dir", type=Path, default=runtime_data_root())
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--interval-minutes", type=int, default=5)
    parser.add_argument("--pause", type=float, default=5.0)
    parser.add_argument("--account-size", type=float, default=10_000.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.005)
    parser.add_argument("--auto-confirm-paper-exits", action="store_true")
    parser.add_argument("--entry-budget-seconds", type=float, default=240.0)
    parser.add_argument("--exit-budget-seconds", type=float, default=120.0)
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    """Run one command in the project root."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    workflow_run_id = f"tcp-{datetime.now(MARKET_TZ).strftime('%Y%m%dT%H%M%S')}"
    command = [
        sys.executable,
        "run_current_candle_capture.py",
        "--critical-path-only",
        "--workflow-run-id",
        workflow_run_id,
        "--output-dir",
        str(args.output_dir),
        "--data-dir",
        str(args.data_dir),
        "--symbols",
        *[symbol.upper() for symbol in args.symbols],
        "--pause",
        str(args.pause),
        "--chart-m1-count",
        "0",
        "--chart-m15-count",
        "0",
        "--chart-m60-count",
        "0",
        "--chart-d-count",
        "0",
        "--account-size",
        str(args.account_size),
        "--risk-per-trade-pct",
        str(args.risk_per_trade_pct),
        "--entry-budget-seconds",
        str(args.entry_budget_seconds),
        "--exit-budget-seconds",
        str(args.exit_budget_seconds),
    ]
    if args.auto_confirm_paper_exits:
        command.append("--auto-confirm-paper-exits")
    run_step(command)
    run_step(
        [
            sys.executable,
            "run_production_heartbeat.py",
            "--output-dir",
            str(args.output_dir),
            "--data-dir",
            str(args.data_dir),
            "--interval-minutes",
            str(args.interval_minutes),
        ]
    )
    payload = {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "workflow_run_id": workflow_run_id,
        "status": "ok",
        "guardrail": "Trading critical path only. Paper/shadow mode; no broker orders or live execution.",
    }
    (args.output_dir / "trading_critical_path.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
