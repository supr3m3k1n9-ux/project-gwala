"""Run the fast current-candle paper-candidate capture pass.

This is the narrow market-hours workflow for the paper gate. It refreshes
Webull candles, scans the approved/watch playbook, and immediately rebuilds the
existing sizing, routing, pre-entry, Paper Gate v2, Options Contract Gate, and
validation-import preview reports. It also records Opening Range Breakout as a
shadow-only secondary research lane after the fresh Webull refresh.

It does not add strategies, loosen filters, import paper trades, place broker
orders, create broker alerts, or enable real-money execution.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols
from run_playbook import markdown_table


DEFAULT_SYMBOLS = sorted(playbook_symbols("approved_plus_watch"))
PROJECT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class StepResult:
    """One command result in the capture pass."""

    step: str
    status: str
    command: str
    output: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fast current-candle capture pass.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to refresh and scan.")
    parser.add_argument("--skip-refresh", action="store_true", help="Use existing candle CSVs instead of refreshing.")
    parser.add_argument("--entry-count", type=int, default=1200, help="30m candles per Webull page.")
    parser.add_argument("--exit-count", type=int, default=1200, help="5m candles per Webull page.")
    parser.add_argument("--entry-pages", type=int, default=1, help="30m history pages for refresh.")
    parser.add_argument("--exit-pages", type=int, default=1, help="5m history pages for refresh.")
    parser.add_argument("--chart-m1-count", type=int, default=240, help="1m chart-only candles per Webull page.")
    parser.add_argument("--chart-m15-count", type=int, default=400, help="15m chart-only candles per Webull page.")
    parser.add_argument("--chart-m60-count", type=int, default=400, help="1h chart-only candles per Webull page.")
    parser.add_argument("--chart-d-count", type=int, default=260, help="Daily chart-only candles per Webull page.")
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Webull requests.")
    parser.add_argument("--account-size", type=float, default=10_000.0, help="Paper account size.")
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.005, help="Paper risk per trade.")
    parser.add_argument(
        "--auto-confirm-paper-exits",
        action="store_true",
        help="Write local paper exit updates only. New entries and validation imports stay preview/manual.",
    )
    return parser.parse_args()


def normalized_symbols(symbols: list[str]) -> list[str]:
    """Return stable uppercase symbols."""

    return [symbol.upper() for symbol in symbols]


def refresh_commands(args: argparse.Namespace, python: str) -> list[tuple[str, list[str]]]:
    """Return the focused Webull refresh commands."""

    symbols = normalized_symbols(args.symbols)
    base_command = [
        python,
        "run_webull_watchlist.py",
        "--symbols",
        *symbols,
        "--entry-count",
        str(args.entry_count),
        "--exit-count",
        str(args.exit_count),
        "--entry-pages",
        str(args.entry_pages),
        "--exit-pages",
        str(args.exit_pages),
        "--pause",
        str(args.pause),
        "--chart-m1-count",
        str(args.chart_m1_count),
        "--chart-m15-count",
        str(args.chart_m15_count),
        "--chart-m60-count",
        str(args.chart_m60_count),
        "--chart-d-count",
        str(args.chart_d_count),
        "--output-dir",
        str(args.output_dir),
    ]
    return [
        ("Refresh Webull best/market setups", [*base_command, "--candidate-preset", "best_plus_market"]),
        ("Reuse Webull candles for Setup B", [*base_command, "--reuse-csv", "--candidate-preset", "setup_b"]),
        ("Reuse Webull candles for full-session setups", [*base_command, "--reuse-csv", "--candidate-preset", "full_session"]),
        (
            "Repair M30 from lower timeframe",
            [
                python,
                "run_repair_m30_from_lower_timeframe.py",
                "--symbols",
                *symbols,
                "--data-dir",
                str(args.output_dir),
                "--output-dir",
                str(args.output_dir),
            ],
        ),
        (
            "Record refresh audit",
            [
                python,
                "run_refresh_audit.py",
                "--record",
                "--provider",
                "webull",
                "--symbols",
                *symbols,
                "--output-dir",
                str(args.output_dir),
            ],
        ),
        (
            "Provider stability audit",
            [
                python,
                "run_provider_stability_audit.py",
                "--provider",
                "webull",
                "--symbols",
                *symbols,
                "--output-dir",
                str(args.output_dir),
            ],
        ),
    ]


def gate_commands(args: argparse.Namespace, python: str) -> list[tuple[str, list[str]]]:
    """Return the ordered current-candle capture gate commands."""

    symbols = normalized_symbols(args.symbols)
    commands: list[tuple[str, list[str]]] = [
        (
            "Scanner",
            [
                python,
                "run_daily_scanner.py",
                "--mode",
                "approved_plus_watch",
                "--symbols",
                *symbols,
                "--output-dir",
                str(args.output_dir),
            ],
        ),
        (
            "Position Sizing",
            [
                python,
                "run_position_sizer.py",
                "--output-dir",
                str(args.output_dir),
                "--account-size",
                str(args.account_size),
                "--risk-per-trade-pct",
                str(args.risk_per_trade_pct),
            ],
        ),
        ("Strategy Vault snapshot", [python, "run_strategy_vault.py", "--output-dir", str(args.output_dir)]),
        ("Paper activation rules", [python, "run_paper_activation_rules.py", "--output-dir", str(args.output_dir)]),
        ("Market Regime Router", [python, "run_market_regime_router.py", "--output-dir", str(args.output_dir)]),
        ("Pre-Entry Review", [python, "run_pre_entry_review.py", "--output-dir", str(args.output_dir)]),
        ("Paper Entry Packet", [python, "run_paper_entry_packet.py", "--output-dir", str(args.output_dir)]),
        (
            "Paper Gate v2",
            [
                python,
                "run_paper_gate_v2.py",
                "--output-dir",
                str(args.output_dir),
                "--account-size",
                str(args.account_size),
            ],
        ),
        ("Candidate-Window Ledger + Event Dispatch", [python, "run_candidate_window_ledger.py", "--output-dir", str(args.output_dir)]),
        ("Validation Import Preview", [python, "run_paper_validation_sample_import.py", "--output-dir", str(args.output_dir)]),
        ("Daily Ship Report", [python, "run_daily_ship_report.py", "--output-dir", str(args.output_dir)]),
        ("Filter Rejection Report", [python, "run_filter_rejection_report.py", "--output-dir", str(args.output_dir)]),
        ("Historical Bucket Sync", [python, "run_historical_bucket_sync.py", "--output-dir", str(args.output_dir)]),
        (
            "Opening Range Breakout Shadow Evidence",
            [
                python,
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
                python,
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
        (
            "Opening Range Breakout Paper-Watch Gate",
            [python, "run_opening_range_breakout_paper_watch_gate.py", "--output-dir", str(args.output_dir)],
        ),
        (
            "Morning Index ORB Manual Paper-Watch",
            [python, "run_morning_index_orb_manual_paper_watch.py", "--output-dir", str(args.output_dir)],
        ),
    ]
    if args.auto_confirm_paper_exits:
        commands.append(
            (
                "Open Paper Monitor",
                [python, "run_open_paper_monitor.py", "--output-dir", str(args.output_dir), "--confirm-updates"],
            )
        )
        commands.append(("Paper Review", [python, "run_paper_review.py", "--output-dir", str(args.output_dir)]))
    commands.extend(
        [
            ("Refresh Status", [python, "run_refresh_status.py", "--output-dir", str(args.output_dir)]),
            ("System State", [python, "run_system_state.py", "--output-dir", str(args.output_dir)]),
            ("Dashboard Data Preflight", [python, "run_dashboard_data_preflight.py", "--output-dir", str(args.output_dir)]),
            ("Data Flow Sentinel", [python, "run_data_flow_sentinel.py", "--output-dir", str(args.output_dir)]),
            ("Final System State", [python, "run_system_state.py", "--output-dir", str(args.output_dir)]),
        ]
    )
    return commands


def build_commands(args: argparse.Namespace, python: str = sys.executable) -> list[tuple[str, list[str]]]:
    """Build the full capture command list."""

    commands: list[tuple[str, list[str]]] = []
    if not args.skip_refresh:
        commands.extend(refresh_commands(args, python))
    commands.extend(gate_commands(args, python))
    return commands


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read CSV output or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json_or_empty(path: Path) -> dict:
    """Read JSON output or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def opening_range_breakout_summary(output_dir: Path) -> dict[str, object]:
    """Return shadow-only ORB evidence progress from its paper-watch gate."""

    gate = read_json_or_empty(output_dir / "opening_range_breakout_paper_watch_gate.json")
    checks = gate.get("checks", [])
    by_check = {
        str(item.get("check", "")): item
        for item in checks
        if isinstance(item, dict)
    }

    def current_required(check: str) -> tuple[float, float, float]:
        row = by_check.get(check, {})
        current = float(row.get("current", 0) or 0)
        required = float(row.get("required", 0) or 0)
        return current, required, max(required - current, 0.0)

    shadow_current, shadow_required, shadow_remaining = current_required("Shadow samples logged")
    forward_current, forward_required, forward_remaining = current_required("Forward observations logged")
    matured_shadow_current, matured_shadow_required, matured_shadow_remaining = current_required("Matured shadow outcomes")
    matured_forward_current, matured_forward_required, matured_forward_remaining = current_required("Matured forward outcomes")
    return {
        "orb_collection_mode": "shadow_only",
        "orb_decision": gate.get("decision", "missing"),
        "orb_next_blocker": gate.get("next_blocker", "missing"),
        "orb_blocked_count": int(gate.get("blocked_count", 0) or 0),
        "orb_shadow_samples": int(shadow_current),
        "orb_shadow_samples_required": int(shadow_required),
        "orb_shadow_samples_remaining": int(shadow_remaining),
        "orb_matured_shadow_outcomes": int(matured_shadow_current),
        "orb_matured_shadow_outcomes_required": int(matured_shadow_required),
        "orb_matured_shadow_outcomes_remaining": int(matured_shadow_remaining),
        "orb_forward_observations": int(forward_current),
        "orb_forward_observations_required": int(forward_required),
        "orb_forward_observations_remaining": int(forward_remaining),
        "orb_matured_forward_outcomes": int(matured_forward_current),
        "orb_matured_forward_outcomes_required": int(matured_forward_required),
        "orb_matured_forward_outcomes_remaining": int(matured_forward_remaining),
        "orb_guardrail": gate.get(
            "guardrail",
            "Shadow-only evidence collection. No official Paper Gate, contract review, validation import, or live execution.",
        ),
    }


def morning_index_orb_summary(output_dir: Path) -> dict[str, object]:
    """Return promoted ORB Manual Paper-Watch progress."""

    payload = read_json_or_empty(output_dir / "morning_index_orb_manual_paper_watch.json")
    metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
    return {
        "morning_index_orb_collection_mode": payload.get("collection_mode", "missing"),
        "morning_index_orb_status": payload.get("manual_paper_watch_status", "missing"),
        "morning_index_orb_candidates_detected_today": int(metrics.get("candidates_detected_today", 0) or 0),
        "morning_index_orb_qualified_today": int(metrics.get("qualified_today", 0) or 0),
        "morning_index_orb_operator_reviewed_today": int(metrics.get("operator_reviewed_today", 0) or 0),
        "morning_index_orb_contract_passed_today": int(metrics.get("contract_passed_today", 0) or 0),
        "morning_index_orb_completed_count": int(metrics.get("completed_count", 0) or 0),
        "morning_index_orb_open_count": int(metrics.get("open_count", 0) or 0),
        "morning_index_orb_remaining_to_20": int(metrics.get("remaining_to_20", 20) or 20),
        "morning_index_orb_guardrail": payload.get(
            "guardrail",
            "Morning Index ORB Manual Paper-Watch is paper-only and separate from VWAP validation.",
        ),
    }


def capture_count_summary(output_dir: Path) -> dict[str, object]:
    """Return counts across the official paper-candidate funnel."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    router = read_csv_or_empty(output_dir / "market_regime_router_candidates.csv")
    pre_entry = read_csv_or_empty(output_dir / "pre_entry_review.csv")
    paper_gate = read_json_or_empty(output_dir / "paper_gate_v2.json")
    contract_gate = read_json_or_empty(output_dir / "options_contract_gate.json")
    validation_import = read_json_or_empty(output_dir / "paper_validation_sample_import.json")

    scanner_total = int(len(scanner))
    current_allowed = 0
    grace_allowed = 0
    earlier_allowed = 0
    if not scanner.empty and {"scanner_status", "signal_freshness"}.issubset(scanner.columns):
        allowed = scanner["scanner_status"].astype(str).eq("allowed")
        current_allowed = int((allowed & scanner["signal_freshness"].astype(str).eq("current_candle")).sum())
        grace_allowed = int((allowed & scanner["signal_freshness"].astype(str).eq("grace_candle")).sum())
        earlier_allowed = int((allowed & scanner["signal_freshness"].astype(str).eq("earlier_today")).sum())
    paper_validation_allowed = current_allowed + grace_allowed

    size_ok = int(sizing["sizing_status"].astype(str).eq("size_ok").sum()) if "sizing_status" in sizing.columns else 0
    router_review_supported = (
        int(router["candidate_route"].astype(str).isin(["review_first", "caution_review"]).sum())
        if "candidate_route" in router.columns
        else 0
    )
    pre_ready = (
        int(pre_entry["review_status"].astype(str).eq("ready_for_manual_review").sum())
        if "review_status" in pre_entry.columns
        else 0
    )
    gate_ready = int(paper_gate.get("ready_sample_count", 0) or 0)
    contract_pass = int(contract_gate.get("passed_contract_count", 0) or 0)
    validation_new = int(validation_import.get("new_rows", 0) or 0)

    stages = [
        ("scanner_paper_validation_allowed", paper_validation_allowed),
        ("position_size_ok", size_ok),
        ("router_review_supported", router_review_supported),
        ("pre_entry_ready", pre_ready),
        ("paper_gate_ready", gate_ready),
        ("contract_gate_passed", contract_pass),
        ("validation_import_new_rows", validation_new),
    ]
    bottleneck = next((name for name, count in stages if count == 0), "none")
    if bottleneck == "scanner_paper_validation_allowed" and earlier_allowed:
        bottleneck_reason = (
            f"{earlier_allowed} allowed candidate(s) were found earlier today, but none were current A-tier or one-M30 B-tier grace."
        )
    elif bottleneck == "none":
        bottleneck_reason = "The capture path has at least one row at every stage."
    else:
        bottleneck_reason = f"The first zero-count stage is {bottleneck}."

    return {
        "scanner_rows": scanner_total,
        "scanner_current_allowed": current_allowed,
        "scanner_grace_allowed": grace_allowed,
        "scanner_paper_validation_allowed": paper_validation_allowed,
        "scanner_earlier_today_allowed": earlier_allowed,
        "position_size_ok": size_ok,
        "router_review_supported": router_review_supported,
        "pre_entry_ready": pre_ready,
        "paper_gate_ready": gate_ready,
        "contract_gate_passed": contract_pass,
        "validation_import_new_rows": validation_new,
        "first_bottleneck": bottleneck,
        "bottleneck_reason": bottleneck_reason,
        "paper_gate_status": paper_gate.get("status", "missing"),
        "contract_gate_status": contract_gate.get("status", "missing"),
        "validation_import_mode": validation_import.get("mode", "missing"),
        **opening_range_breakout_summary(output_dir),
        **morning_index_orb_summary(output_dir),
    }


def failed_step_result(step: str, command: list[str], error: subprocess.CalledProcessError) -> StepResult:
    """Return a bounded failed step result for the capture report."""

    output = "\n".join(part.strip() for part in [error.stdout, error.stderr] if part and str(part).strip())
    if not output:
        output = f"Command exited with status {error.returncode}."
    return StepResult(step=step, status=f"failed:{error.returncode}", command=" ".join(command), output=output[-8000:])


def run_step(step: str, command: list[str]) -> StepResult:
    """Run one local capture command."""

    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    output = "\n".join(part.strip() for part in [completed.stdout, completed.stderr] if part.strip())
    return StepResult(step=step, status="ok", command=" ".join(command), output=output)


def write_report(output_dir: Path, results: list[StepResult], payload: dict[str, object], args: argparse.Namespace) -> Path:
    """Write JSON and Markdown reports for the capture pass."""

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    json_payload = {
        "generated_at_et": generated_at,
        "symbols": normalized_symbols(args.symbols),
        "refresh_ran": not args.skip_refresh,
        "auto_confirm_paper_exits": bool(args.auto_confirm_paper_exits),
        "capture_status": "failed" if any(result.status.startswith("failed") for result in results) else "ok",
        "failed_step": next((result.step for result in results if result.status.startswith("failed")), ""),
        **payload,
        "guardrail": (
            "A/current + B/grace capture is local paper-validation only. It never places broker orders, "
            "creates broker alerts, confirms new paper entries, or loosens freshness gates."
        ),
    }
    (output_dir / "current_candle_capture.json").write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    steps = pd.DataFrame([{"step": result.step, "status": result.status, "command": result.command} for result in results])
    counts = pd.DataFrame(
        [
            {"stage": "Scanner rows", "count": payload["scanner_rows"]},
            {"stage": "Scanner current-candle allowed", "count": payload["scanner_current_allowed"]},
            {"stage": "Scanner B-tier grace allowed", "count": payload["scanner_grace_allowed"]},
            {"stage": "Scanner paper-validation allowed", "count": payload["scanner_paper_validation_allowed"]},
            {"stage": "Scanner earlier-today allowed", "count": payload["scanner_earlier_today_allowed"]},
            {"stage": "Position size_ok", "count": payload["position_size_ok"]},
            {"stage": "Router review-supported", "count": payload["router_review_supported"]},
            {"stage": "Pre-entry ready", "count": payload["pre_entry_ready"]},
            {"stage": "Paper Gate ready", "count": payload["paper_gate_ready"]},
            {"stage": "Contract Gate passed", "count": payload["contract_gate_passed"]},
            {"stage": "Validation import new rows", "count": payload["validation_import_new_rows"]},
        ]
    )
    orb_counts = pd.DataFrame(
        [
            {
                "metric": "Collection mode",
                "current": payload["orb_collection_mode"],
                "required": "shadow_only",
                "remaining": "N/A",
            },
            {
                "metric": "Shadow samples",
                "current": payload["orb_shadow_samples"],
                "required": payload["orb_shadow_samples_required"],
                "remaining": payload["orb_shadow_samples_remaining"],
            },
            {
                "metric": "Matured shadow outcomes",
                "current": payload["orb_matured_shadow_outcomes"],
                "required": payload["orb_matured_shadow_outcomes_required"],
                "remaining": payload["orb_matured_shadow_outcomes_remaining"],
            },
            {
                "metric": "Forward observations",
                "current": payload["orb_forward_observations"],
                "required": payload["orb_forward_observations_required"],
                "remaining": payload["orb_forward_observations_remaining"],
            },
            {
                "metric": "Matured forward outcomes",
                "current": payload["orb_matured_forward_outcomes"],
                "required": payload["orb_matured_forward_outcomes_required"],
                "remaining": payload["orb_matured_forward_outcomes_remaining"],
            },
        ]
    )
    output_blocks = "\n\n".join(
        f"### {result.step}\n\n```text\n{result.output or 'No output.'}\n```" for result in results
    )
    report_path = output_dir / "current_candle_capture.md"
    report_path.write_text(
        f"""# Current/Grace Capture

Generated: {generated_at}

This is the fast market-hours pass for catching official paper candidates while
they are still A/current or B/one-M30 grace eligible.

Important: this is local paper-validation only. It does not place broker
orders, create broker alerts, confirm new paper entries, or loosen freshness
gates.

## Summary

```text
Refresh ran: {not args.skip_refresh}
Symbols: {', '.join(normalized_symbols(args.symbols))}
First bottleneck: {payload["first_bottleneck"]}
Bottleneck reason: {payload["bottleneck_reason"]}
Paper Gate status: {payload["paper_gate_status"]}
Options Contract Gate status: {payload["contract_gate_status"]}
Validation import mode: {payload["validation_import_mode"]}
```

## Funnel Counts

{markdown_table(counts)}

## Opening Range Breakout Shadow Evidence

```text
Decision: {payload["orb_decision"]}
Next blocker: {payload["orb_next_blocker"]}
Blocked checks: {payload["orb_blocked_count"]}
Guardrail: {payload["orb_guardrail"]}
```

{markdown_table(orb_counts)}

## Command Steps

{markdown_table(steps)}

## Command Output

{output_blocks}

## Files

```text
logs/current_candle_capture.json
logs/current_candle_capture.md
logs/daily_paper_signal_scanner.csv
logs/position_sizing.csv
logs/market_regime_router_candidates.csv
logs/pre_entry_review.csv
logs/paper_gate_v2.json
data/candidate_window_ledger.csv
logs/candidate_window_ledger.json
logs/options_contract_gate.json
logs/paper_validation_sample_import.json
logs/DAILY_SHIP_REPORT.md
logs/opening_range_breakout_shadow_samples.md
logs/opening_range_breakout_forward_observations.md
logs/opening_range_breakout_paper_watch_gate.json
logs/morning_index_orb_manual_paper_watch.md
```
""",
        encoding="utf-8",
    )
    return report_path


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    failed: subprocess.CalledProcessError | None = None
    for step, command in build_commands(args):
        print(f"Running: {step}", flush=True)
        try:
            results.append(run_step(step, command))
        except subprocess.CalledProcessError as error:
            results.append(failed_step_result(step, command, error))
            failed = error
            break
    payload = capture_count_summary(args.output_dir)
    report_path = write_report(args.output_dir, results, payload, args)
    print(f"Current/grace capture complete. Saved report: {report_path}")
    print(f"First bottleneck: {payload['first_bottleneck']}")
    if failed is not None:
        raise SystemExit(failed.returncode)


if __name__ == "__main__":
    main()
