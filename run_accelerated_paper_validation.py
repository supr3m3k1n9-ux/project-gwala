"""Run an accelerated market-hours paper-validation loop.

This is a faster learning loop for Project Gwala. It refreshes Webull data,
rebuilds research/paper reports, and ranks manual-review candidates. It does
not import paper entries, place broker orders, create broker alerts, or enable
real-money execution.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols
from run_intraday_loop import is_market_open, seconds_until_next_scan
from run_playbook import markdown_table


PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the accelerated Project Gwala paper-validation loop.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--interval-minutes", type=int, default=5, help="Minutes between market-hours scans.")
    parser.add_argument("--once", action="store_true", help="Run one accelerated scan and exit.")
    parser.add_argument("--report-only", action="store_true", help="Rebuild the ranked report without refreshing data.")
    parser.add_argument("--force", action="store_true", help="Run even outside regular market hours.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=[],
        help=(
            "Optional focused symbols for faster scans. Defaults to every approved/watch symbol so "
            "dashboard freshness checks stay aligned."
        ),
    )
    parser.add_argument("--full-universe", action="store_true", help="Scan every approved/watch symbol.")
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Webull requests during refresh.")
    parser.add_argument("--account-size", type=float, default=10_000.0, help="Paper account size for sizing.")
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.005, help="Paper risk per trade.")
    parser.add_argument(
        "--auto-confirm-paper-exits",
        action="store_true",
        help="Optionally write local paper exit updates only. New paper entries still require manual confirmation.",
    )
    return parser.parse_args()


def scan_symbols(args: argparse.Namespace) -> list[str]:
    """Return the symbol list for one accelerated scan."""

    if getattr(args, "full_universe", False):
        return sorted(playbook_symbols("approved_plus_watch"))
    raw_symbols = getattr(args, "symbols", []) or sorted(playbook_symbols("approved_plus_watch"))
    return [symbol.upper() for symbol in raw_symbols]


def now_et() -> datetime:
    """Return current New York time."""

    return datetime.now(tz=MARKET_TZ)


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV output if it exists."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def workflow_command(args: argparse.Namespace, python: str = sys.executable) -> list[str]:
    """Build the current-candle capture command for one accelerated scan."""

    command = [
        python,
        "run_current_candle_capture.py",
        "--output-dir",
        str(args.output_dir),
        "--symbols",
        *scan_symbols(args),
        "--pause",
        str(args.pause),
        "--account-size",
        str(args.account_size),
        "--risk-per-trade-pct",
        str(args.risk_per_trade_pct),
    ]
    if getattr(args, "auto_confirm_paper_exits", False):
        command.append("--auto-confirm-paper-exits")
    return command


def run_step(command: list[str]) -> None:
    """Run one command and fail fast if it errors."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


def merge_health(queue: pd.DataFrame, health: pd.DataFrame) -> pd.DataFrame:
    """Attach setup-health context to queue rows."""

    if queue.empty:
        return queue
    enriched = queue.copy()
    if health.empty:
        enriched["health_status"] = ""
        enriched["health_score"] = 0
        enriched["expectancy_r"] = 0.0
        enriched["profit_factor"] = 0.0
        return enriched

    health_columns = ["symbol", "setup", "health_status", "health_score", "expectancy_r", "profit_factor", "flags"]
    available = [column for column in health_columns if column in health.columns]
    merged = enriched.merge(health[available], on=["symbol", "setup"], how="left")
    for column, default in [
        ("health_status", ""),
        ("health_score", 0),
        ("expectancy_r", 0.0),
        ("profit_factor", 0.0),
        ("flags", ""),
    ]:
        if column not in merged.columns:
            merged[column] = default
        merged[column] = merged[column].fillna(default)
    return merged


def rank_queue(queue: pd.DataFrame, health: pd.DataFrame) -> pd.DataFrame:
    """Rank ready and near-ready rows for fast manual review."""

    if queue.empty:
        return pd.DataFrame()

    ranked = merge_health(queue, health)
    for column in ["priority", "quality_score", "room_to_target_r", "check_score", "health_score", "expectancy_r"]:
        if column in ranked.columns:
            ranked[column] = pd.to_numeric(ranked[column], errors="coerce").fillna(0)
        else:
            ranked[column] = 0

    ranked["rank_bucket"] = ranked["queue_status"].map({"ready_for_review": 0, "almost_ready": 1}).fillna(2)
    ranked["caution_penalty"] = ranked["health_status"].astype(str).str.lower().eq("caution").astype(int)
    ranked["review_rank"] = (
        ranked["rank_bucket"] * 1000
        + ranked["caution_penalty"] * 100
        - ranked["health_score"]
        - ranked["quality_score"]
        - ranked["check_score"]
    )
    ranked["review_decision"] = ranked.apply(review_decision_for_row, axis=1)
    ranked["decision_reason"] = ranked.apply(review_reason_for_row, axis=1)
    ranked = ranked.sort_values(["review_rank", "priority", "symbol", "setup"]).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1

    columns = [
        "rank",
        "review_decision",
        "queue_status",
        "symbol",
        "setup",
        "direction",
        "signal_time_et",
        "quality_grade",
        "quality_score",
        "health_status",
        "health_score",
        "expectancy_r",
        "profit_factor",
        "room_to_target_r",
        "shares",
        "estimated_risk_dollars",
        "decision_reason",
        "next_action",
        "blockers",
    ]
    display = ranked[[column for column in columns if column in ranked.columns]].copy()
    display = display.fillna("")
    return display


def review_decision_for_row(row: pd.Series) -> str:
    """Return the manual-review priority for a ranked queue row."""

    queue_status = str(row.get("queue_status", ""))
    health_status = str(row.get("health_status", "")).lower()
    room_to_target = float(row.get("room_to_target_r", 0) or 0)
    expectancy = float(row.get("expectancy_r", 0) or 0)
    if queue_status == "almost_ready":
        return "watch_next_scan"
    if health_status == "caution" or expectancy <= 0 or room_to_target <= 0:
        return "caution_review"
    return "review_first"


def review_reason_for_row(row: pd.Series) -> str:
    """Explain the manual-review priority in plain language."""

    queue_status = str(row.get("queue_status", ""))
    health_status = str(row.get("health_status", "")).lower()
    room_to_target = float(row.get("room_to_target_r", 0) or 0)
    expectancy = float(row.get("expectancy_r", 0) or 0)
    reasons = []
    if queue_status == "almost_ready":
        reasons.append("not a current allowed paper candidate yet")
    if health_status == "caution":
        reasons.append("setup health is caution")
    if expectancy <= 0:
        reasons.append("historical expectancy is not positive")
    if room_to_target <= 0:
        reasons.append("room-to-target is not positive")
    if not reasons:
        reasons.append("ready row with positive setup health context")
    return "; ".join(reasons)


def build_report_payload(
    output_dir: Path,
    args: argparse.Namespace | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Build the accelerated validation summary from current workflow outputs."""

    generated = generated_at or now_et()
    queue = read_csv_or_empty(output_dir / "forward_sample_queue.csv")
    health = read_csv_or_empty(output_dir / "setup_health.csv")
    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    refresh_status = {}
    refresh_path = output_dir / "refresh_status.json"
    if refresh_path.exists():
        refresh_status = json.loads(refresh_path.read_text(encoding="utf-8"))

    ranked = rank_queue(queue, health)
    ready = ranked[ranked["queue_status"].eq("ready_for_review")] if not ranked.empty else pd.DataFrame()
    review_first = ready[ready["review_decision"].eq("review_first")] if not ready.empty else pd.DataFrame()
    caution_ready = ready[ready["review_decision"].eq("caution_review")] if not ready.empty else pd.DataFrame()
    almost = ranked[ranked["queue_status"].eq("almost_ready")] if not ranked.empty else pd.DataFrame()
    current_candidates = 0
    if not scanner.empty and {"scanner_status", "signal_freshness"}.issubset(scanner.columns):
        current_candidates = int(
            len(
                scanner[
                    scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
                    & scanner["signal_freshness"].eq("current_candle")
                ]
            )
        )

    return {
        "generated_at_et": generated.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "provider": refresh_status.get("provider_refresh", {}).get("provider", "unknown"),
        "provider_status": refresh_status.get("provider_refresh", {}).get("status", "unknown"),
        "data_status": refresh_status.get("scanner", {}).get("latest_scanner_session", "unknown"),
        "current_candidates": current_candidates,
        "review_first": int(len(review_first)),
        "caution_ready": int(len(caution_ready)),
        "ready_for_review": int(len(ready)),
        "almost_ready": int(len(almost)),
        "scan_symbols": scan_symbols(args) if args is not None else sorted(playbook_symbols("approved_plus_watch")),
        "ranked": ranked,
        "ready": ready,
        "review_first_rows": review_first,
        "caution_ready_rows": caution_ready,
        "almost": almost,
        "guardrail": "Manual paper review only. No broker orders, broker alerts, or automatic paper entries.",
    }


def write_report(output_dir: Path, payload: dict[str, object]) -> Path:
    """Write accelerated validation JSON and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "accelerated_paper_validation.json"
    serializable = {
        key: value
        for key, value in payload.items()
        if key not in {"ranked", "ready", "review_first_rows", "caution_ready_rows", "almost"}
    }
    json_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    report_path = output_dir / "accelerated_paper_validation.md"
    report_path.write_text(
        f"""# Accelerated Paper Validation

This report is the fast market-hours learning view for Project Gwala.

Important: this is research and paper-validation only. It does not import paper
entries, place broker orders, create broker alerts, or enable real-money
execution.

## Summary

| field | value |
| --- | --- |
| generated_at_et | {payload['generated_at_et']} |
| provider | {payload['provider']} |
| provider_status | {payload['provider_status']} |
| scanner_session | {payload['data_status']} |
| current_candidates | {payload['current_candidates']} |
| review_first | {payload['review_first']} |
| caution_ready | {payload['caution_ready']} |
| ready_for_review | {payload['ready_for_review']} |
| almost_ready | {payload['almost_ready']} |
| scan_symbols | {', '.join(payload['scan_symbols'])} |

## Review First

{markdown_table(payload['review_first_rows'])}

## Caution Ready Rows

{markdown_table(payload['caution_ready_rows'])}

## Almost Ready Watchlist

{markdown_table(payload['almost'])}

## Guardrail

```text
{payload['guardrail']}
```

## Files

```text
logs/accelerated_paper_validation.json
logs/accelerated_paper_validation.md
logs/forward_sample_queue.csv
logs/setup_health.csv
logs/daily_paper_signal_scanner.csv
```
""",
        encoding="utf-8",
    )
    return report_path


def run_one_scan(args: argparse.Namespace) -> Path:
    """Run one accelerated scan and write the ranked report."""

    run_step(workflow_command(args))
    payload = build_report_payload(args.output_dir, args)
    report_path = write_report(args.output_dir, payload)
    print(f"Saved accelerated validation report: {report_path}")
    return report_path


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.report_only:
        report_path = write_report(args.output_dir, build_report_payload(args.output_dir, args))
        print(f"Saved accelerated validation report: {report_path}")
        return

    while True:
        moment = now_et()
        if args.force or is_market_open(moment):
            run_one_scan(args)
            if args.once:
                return
            sleep_seconds = seconds_until_next_scan(now_et(), args.interval_minutes)
            print(f"Sleeping {sleep_seconds} seconds until next accelerated scan.", flush=True)
            time.sleep(sleep_seconds)
            continue

        payload = build_report_payload(args.output_dir, args, generated_at=moment)
        payload["guardrail"] = "Market is closed. No accelerated scan was run."
        report_path = write_report(args.output_dir, payload)
        print(f"Market is closed at {moment.strftime('%Y-%m-%d %H:%M ET')}. Saved report: {report_path}")
        return


if __name__ == "__main__":
    main()
