"""Run non-critical market-hours background work.

This lane updates chart/context data, research observations, dashboard payloads,
and diagnostics without blocking the trading critical path.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols


DEFAULT_SYMBOLS = sorted(playbook_symbols("approved_plus_watch"))
PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Project Gwala's async market lane.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"))
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--pause", type=float, default=5.0)
    return parser.parse_args()


def run_step(name: str, command: list[str]) -> dict[str, object]:
    started = datetime.now(MARKET_TZ)
    print(f"\n=== {name}: {' '.join(command)} ===", flush=True)
    completed = subprocess.run(command, cwd=PROJECT_DIR, check=False, capture_output=True, text=True)
    finished = datetime.now(MARKET_TZ)
    return {
        "step": name,
        "status": "ok" if completed.returncode == 0 else f"failed:{completed.returncode}",
        "started_at_et": started.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "completed_at_et": finished.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "command": " ".join(command),
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    symbols = [symbol.upper() for symbol in args.symbols]
    commands = [
        (
            "Chart/context refresh",
            [
                sys.executable,
                "run_webull_watchlist.py",
                "--chart-only",
                "--symbols",
                *symbols,
                "--pause",
                str(args.pause),
                "--output-dir",
                str(args.output_dir),
            ],
        ),
        ("Daily Ship Report", [sys.executable, "run_daily_ship_report.py", "--output-dir", str(args.output_dir)]),
        ("Filter Rejection Report", [sys.executable, "run_filter_rejection_report.py", "--output-dir", str(args.output_dir)]),
        ("Historical Bucket Sync", [sys.executable, "run_historical_bucket_sync.py", "--output-dir", str(args.output_dir)]),
        (
            "Opening Range Breakout Shadow Evidence",
            [
                sys.executable,
                "run_opening_range_breakout_shadow_samples.py",
                "--symbols",
                *symbols,
                "--data-dir",
                str(args.output_dir),
                "--output-dir",
                str(args.output_dir),
                "--record-latest-snapshot",
            ],
        ),
        (
            "Opening Range Breakout Forward Evidence",
            [
                sys.executable,
                "run_opening_range_breakout_forward_observations.py",
                "--symbols",
                *symbols,
                "--data-dir",
                str(args.output_dir),
                "--output-dir",
                str(args.output_dir),
                "--record-latest-snapshot",
            ],
        ),
        ("Opening Range Breakout Paper-Watch Gate", [sys.executable, "run_opening_range_breakout_paper_watch_gate.py", "--output-dir", str(args.output_dir)]),
        ("Morning Index ORB Manual Paper-Watch", [sys.executable, "run_morning_index_orb_manual_paper_watch.py", "--output-dir", str(args.output_dir)]),
        ("Phase 3 Forward Evidence Classifier", [sys.executable, "run_phase3_forward_evidence_classifier.py", "--output-dir", str(args.output_dir)]),
        ("Refresh Status", [sys.executable, "run_refresh_status.py", "--output-dir", str(args.output_dir)]),
        ("System State", [sys.executable, "run_system_state.py", "--output-dir", str(args.output_dir)]),
        ("Dashboard Data Preflight", [sys.executable, "run_dashboard_data_preflight.py", "--output-dir", str(args.output_dir)]),
        ("Data Flow Sentinel", [sys.executable, "run_data_flow_sentinel.py", "--output-dir", str(args.output_dir)]),
        ("Data Freshness Audit", [sys.executable, "run_data_freshness_audit.py", "--output-dir", str(args.output_dir)]),
    ]
    results = [run_step(name, command) for name, command in commands]
    status = "ok" if all(result["status"] == "ok" for result in results) else "degraded"
    payload = {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "steps": results,
        "guardrail": "Async/background lane only. No broker orders, no live execution, no validation confirmation.",
    }
    (args.output_dir / "market_async_lane.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if status != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
