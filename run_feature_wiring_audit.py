"""Audit app feature wiring against the approved/watch playbook.

This is a read-only guardrail report. It checks whether the dashboard-facing
features are using the same symbol universe and whether local candle files are
present for chart/research review. It does not fetch data or place orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import PLAYBOOKS, playbook_symbols, setup_labels_for_symbol
from config.strategy_registry import STRATEGY_CONTRACTS, strategy_id_for_scanner
from data.candle_cache import preferred_candle_path
from run_playbook import markdown_table
from run_app import build_backtest_portfolio_simulation
from strategies.scanner_adapters import scanner_adapter_for_entry


WORKSPACE_TIMEFRAMES = ["M1", "M5", "M15", "M30", "M60", "D"]
SIGNAL_TIMEFRAMES = ["M5", "M30"]
RESEARCH_REPORTS = [
    ("strategy_vault", "Strategy Vault", "strategy_vault.md"),
    ("market_sprint_mode", "Market Sprint Mode", "market_sprint_mode.md"),
    ("controlled_universe_expansion", "Controlled Universe Expansion", "controlled_universe_expansion.md"),
    ("probation_watch", "Probation Watch", "probation_watch.md"),
    ("paper_gate_v2", "Paper Gate v2", "paper_gate_v2.md"),
    ("options_contract_gate", "Options Contract Gate", "options_contract_gate.md"),
    ("paper_validation_sample_import", "Paper Validation Sample Import", "paper_validation_sample_import.md"),
    ("strategy_evidence_accumulator", "Strategy Evidence Accumulator", "strategy_evidence_accumulator.md"),
    ("research_strategy_tightened_review", "Research Strategy Tightened Review", "research_strategy_tightened_review.md"),
    ("strategy_backtest_coverage", "Strategy Backtest Coverage", "strategy_backtest_coverage.md"),
    ("validation_deepening_queue", "Validation Deepening Queue", "validation_deepening_queue.md"),
    ("strategy_triage", "Strategy Triage", "strategy_triage.md"),
    ("vwap_mean_reversion", "VWAP Mean Reversion", "vwap_mean_reversion.md"),
    ("vwap_mean_reversion_shadow_samples", "VWAP Mean Reversion Shadow Samples", "vwap_mean_reversion_shadow_samples.md"),
    (
        "vwap_mean_reversion_forward_observations",
        "VWAP Mean Reversion Forward Observations",
        "vwap_mean_reversion_forward_observations.md",
    ),
    ("vwap_mean_reversion_paper_watch_gate", "VWAP Mean Reversion Paper-Watch Gate", "vwap_mean_reversion_paper_watch_gate.md"),
    ("vwap_reclaim_reject", "VWAP Reclaim / Reject", "vwap_reclaim_reject.md"),
    ("vwap_reclaim_reject_shadow_samples", "VWAP Reclaim / Reject Shadow Samples", "vwap_reclaim_reject_shadow_samples.md"),
    (
        "vwap_reclaim_reject_forward_observations",
        "VWAP Reclaim / Reject Forward Observations",
        "vwap_reclaim_reject_forward_observations.md",
    ),
    ("vwap_reclaim_reject_paper_watch_gate", "VWAP Reclaim / Reject Paper-Watch Gate", "vwap_reclaim_reject_paper_watch_gate.md"),
    ("trend_pullback_continuation", "Trend Pullback Continuation", "trend_pullback_continuation.md"),
    (
        "trend_pullback_continuation_shadow_samples",
        "Trend Pullback Continuation Shadow Samples",
        "trend_pullback_continuation_shadow_samples.md",
    ),
    (
        "trend_pullback_continuation_forward_observations",
        "Trend Pullback Continuation Forward Observations",
        "trend_pullback_continuation_forward_observations.md",
    ),
    (
        "trend_pullback_continuation_paper_watch_gate",
        "Trend Pullback Continuation Paper-Watch Gate",
        "trend_pullback_continuation_paper_watch_gate.md",
    ),
    ("gap_fill_fade", "Gap Fill / Gap Fade", "gap_fill_fade.md"),
    ("gap_fill_fade_tightened_review", "Gap Fill / Gap Fade Tightened Review", "gap_fill_fade_tightened_review.md"),
    ("gap_fill_fade_shadow_samples", "Gap Fill / Gap Fade Shadow Samples", "gap_fill_fade_shadow_samples.md"),
    ("gap_fill_fade_forward_observations", "Gap Fill / Gap Fade Forward Observations", "gap_fill_fade_forward_observations.md"),
    ("gap_fill_fade_paper_watch_gate", "Gap Fill / Gap Fade Paper-Watch Gate", "gap_fill_fade_paper_watch_gate.md"),
    ("opening_range_breakout", "Opening Range Breakout", "opening_range_breakout.md"),
    ("opening_range_breakout_tightened_review", "Opening Range Breakout Tightened Review", "opening_range_breakout_tightened_review.md"),
    (
        "opening_range_breakout_walk_forward_deepening",
        "Opening Range Breakout Walk-Forward Deepening",
        "opening_range_breakout_walk_forward_deepening.md",
    ),
    ("opening_range_breakout_shadow_samples", "Opening Range Breakout Shadow Samples", "opening_range_breakout_shadow_samples.md"),
    (
        "opening_range_breakout_forward_observations",
        "Opening Range Breakout Forward Observations",
        "opening_range_breakout_forward_observations.md",
    ),
    ("opening_range_breakout_paper_watch_gate", "Opening Range Breakout Paper-Watch Gate", "opening_range_breakout_paper_watch_gate.md"),
    ("opening_range_failure", "Opening Range Failure", "opening_range_failure.md"),
    ("opening_range_failure_tightened_review", "Opening Range Failure Tightened Review", "opening_range_failure_tightened_review.md"),
    (
        "opening_range_failure_walk_forward_deepening",
        "Opening Range Failure Walk-Forward Deepening",
        "opening_range_failure_walk_forward_deepening.md",
    ),
    ("opening_range_failure_shadow_samples", "Opening Range Failure Shadow Samples", "opening_range_failure_shadow_samples.md"),
    (
        "opening_range_failure_forward_observations",
        "Opening Range Failure Forward Observations",
        "opening_range_failure_forward_observations.md",
    ),
    ("opening_range_failure_paper_watch_gate", "Opening Range Failure Paper-Watch Gate", "opening_range_failure_paper_watch_gate.md"),
]


def file_state(path: Path) -> dict[str, Any]:
    """Return simple file-state details."""

    if not path.exists():
        return {"exists": False, "modified_et": "", "size_bytes": 0}
    modified = datetime.fromtimestamp(path.stat().st_mtime, MARKET_TZ)
    return {
        "exists": True,
        "modified_et": modified.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "size_bytes": int(path.stat().st_size),
    }


def symbol_rows(data_dir: Path) -> list[dict[str, Any]]:
    """Build per-symbol wiring rows."""

    rows = []
    approved = set(playbook_symbols("approved"))
    watch = set(playbook_symbols("watch"))
    for symbol in playbook_symbols("approved_plus_watch"):
        missing = []
        states = {}
        for timeframe in WORKSPACE_TIMEFRAMES:
            state = file_state(preferred_candle_path(data_dir, symbol, timeframe))
            states[timeframe] = state
            if not state["exists"]:
                missing.append(timeframe)
        status = "approved" if symbol in approved else "watch_more" if symbol in watch else "unknown"
        rows.append(
            {
                "symbol": symbol,
                "status": status,
                "setups": ", ".join(setup_labels_for_symbol(symbol, "approved_plus_watch")),
                "workspace_files": "pass" if not missing else "missing",
                "missing_timeframes": ", ".join(missing) if missing else "none",
                "signal_files": "pass"
                if all(states[timeframe]["exists"] for timeframe in SIGNAL_TIMEFRAMES)
                else "missing",
                "latest_m5_modified_et": states["M5"]["modified_et"],
                "latest_m30_modified_et": states["M30"]["modified_et"],
            }
        )
    return rows


def report_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Build report-file wiring rows for dashboard research lanes."""

    rows = []
    for report_key, report_label, filename in RESEARCH_REPORTS:
        state = file_state(output_dir / filename)
        rows.append(
            {
                "report_key": report_key,
                "report": report_label,
                "filename": filename,
                "status": "present" if state["exists"] else "missing",
                "modified_et": state["modified_et"],
                "size_bytes": state["size_bytes"],
            }
        )
    return rows


def portfolio_simulator_state(output_dir: Path) -> dict[str, Any]:
    """Return whether the historical simulator includes current approved rows."""

    playbook_path = output_dir / "playbook_approved_trades.csv"
    playbook = pd.DataFrame()
    if playbook_path.exists():
        try:
            playbook = pd.read_csv(playbook_path)
        except pd.errors.EmptyDataError:
            playbook = pd.DataFrame()
    try:
        trades, account = build_backtest_portfolio_simulation(output_dir)
    except FileNotFoundError:
        trades = pd.DataFrame()
        account = {}
    buckets = trades.groupby("source_bucket").size().to_dict() if not trades.empty and "source_bucket" in trades.columns else {}
    approved_rows = int(buckets.get("Approved Playbook", 0))
    expected_rows = int(len(playbook))
    status = "pass" if expected_rows == approved_rows else "warn"
    setup_c_rows = 0
    if not trades.empty and {"source_bucket", "source_setup"}.issubset(trades.columns):
        setup_c_rows = int(
            len(
                trades[
                    trades["source_bucket"].eq("Approved Playbook")
                    & trades["source_setup"].astype(str).str.contains("Setup C Full-Session", na=False)
                ]
            )
        )
    return {
        "status": status,
        "approved_playbook_rows_expected": expected_rows,
        "approved_playbook_rows_in_simulator": approved_rows,
        "setup_c_full_session_rows_in_simulator": setup_c_rows,
        "source_buckets": {str(key): int(value) for key, value in buckets.items()},
        "source_files": int(account.get("source_files", 0) or 0),
        "approved_playbook_source_files": int(account.get("approved_playbook_source_files", 0) or 0),
    }


def strategy_contract_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Return end-to-end wiring state for every registered strategy family."""

    rows = []
    for contract in STRATEGY_CONTRACTS:
        report_exists = file_state(output_dir / contract.report_file)["exists"]
        trade_log_exists = True if not contract.trade_log else file_state(output_dir / contract.trade_log)["exists"]
        scanner_contract = bool(contract.scanner_setups or contract.scanner_variants)
        status = "pass" if scanner_contract and report_exists and trade_log_exists else "warn"
        rows.append(
            {
                "strategy_id": contract.strategy_id,
                "strategy": contract.name,
                "family": contract.family,
                "scanner_contract": "pass" if scanner_contract else "missing",
                "router_contract": "pass",
                "chart_marker": contract.chart_marker_label,
                "historical_trade_log": contract.trade_log or "approved_playbook",
                "historical_trade_log_status": "present" if trade_log_exists else "missing",
                "report_file": contract.report_file,
                "report_status": "present" if report_exists else "missing",
                "directions": ", ".join(contract.directions),
                "status": status,
            }
        )
    return rows


def scanner_adapter_rows() -> list[dict[str, Any]]:
    """Return adapter wiring for every approved/watch playbook entry."""

    rows = []
    for entry in PLAYBOOKS["approved_plus_watch"]:
        adapter = scanner_adapter_for_entry(entry)
        registry_strategy_id = strategy_id_for_scanner(entry.setup_name, entry.variant)
        try:
            signal_column = adapter.signal_column(entry)
            direction = adapter.direction(entry)
            status = "pass" if adapter.strategy_id == registry_strategy_id and signal_column and direction in {"long", "short"} else "warn"
        except Exception as error:
            signal_column = ""
            direction = ""
            status = "warn"
            registry_strategy_id = f"{registry_strategy_id} ({error})"
        rows.append(
            {
                "symbol": entry.symbol,
                "setup": entry.setup_name,
                "variant": entry.variant,
                "exit_profile": entry.exit_profile,
                "registry_strategy_id": registry_strategy_id,
                "adapter_strategy_id": adapter.strategy_id,
                "signal_column": signal_column,
                "direction": direction,
                "status": status,
            }
        )
    return rows


def build_payload(data_dir: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Build the audit payload."""

    if output_dir is None:
        output_dir = data_dir
    rows = symbol_rows(data_dir)
    reports = report_rows(output_dir)
    portfolio = portfolio_simulator_state(output_dir)
    strategy_contracts = strategy_contract_rows(output_dir)
    scanner_adapters = scanner_adapter_rows()
    missing_symbols = [row["symbol"] for row in rows if row["workspace_files"] != "pass"]
    signal_missing_symbols = [row["symbol"] for row in rows if row["signal_files"] != "pass"]
    missing_reports = [row["report_key"] for row in reports if row["status"] != "present"]
    missing_strategy_contracts = [row["strategy_id"] for row in strategy_contracts if row["status"] != "pass"]
    missing_scanner_adapters = [
        f"{row['symbol']} {row['setup']} {row['variant']}"
        for row in scanner_adapters
        if row["status"] != "pass"
    ]
    status = (
        "pass"
        if (
            not missing_symbols
            and not signal_missing_symbols
            and not missing_reports
            and not missing_strategy_contracts
            and not missing_scanner_adapters
            and portfolio["status"] == "pass"
        )
        else "warn"
    )
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "approved_symbols": playbook_symbols("approved"),
        "watch_symbols": playbook_symbols("watch"),
        "workspace_symbols": playbook_symbols("approved_plus_watch"),
        "workspace_timeframes": WORKSPACE_TIMEFRAMES,
        "signal_timeframes": SIGNAL_TIMEFRAMES,
        "missing_workspace_symbols": missing_symbols,
        "missing_signal_symbols": signal_missing_symbols,
        "missing_reports": missing_reports,
        "missing_strategy_contracts": missing_strategy_contracts,
        "missing_scanner_adapters": missing_scanner_adapters,
        "portfolio_simulator": portfolio,
        "strategy_contract_rows": strategy_contracts,
        "scanner_adapter_rows": scanner_adapters,
        "rows": rows,
        "report_rows": reports,
        "guardrail": "Read-only wiring audit. It never fetches data or places orders.",
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    """Write the audit report."""

    summary = pd.DataFrame(
        [
            {"field": "status", "value": payload["status"]},
            {"field": "approved_symbols", "value": ", ".join(payload["approved_symbols"])},
            {"field": "watch_symbols", "value": ", ".join(payload["watch_symbols"])},
            {"field": "workspace_symbols", "value": ", ".join(payload["workspace_symbols"])},
            {"field": "missing_workspace_symbols", "value": ", ".join(payload["missing_workspace_symbols"]) or "none"},
            {"field": "missing_signal_symbols", "value": ", ".join(payload["missing_signal_symbols"]) or "none"},
            {"field": "missing_reports", "value": ", ".join(payload["missing_reports"]) or "none"},
            {"field": "missing_strategy_contracts", "value": ", ".join(payload["missing_strategy_contracts"]) or "none"},
            {"field": "missing_scanner_adapters", "value": ", ".join(payload["missing_scanner_adapters"]) or "none"},
            {"field": "portfolio_simulator", "value": payload["portfolio_simulator"]["status"]},
            {
                "field": "approved_playbook_rows_in_simulator",
                "value": (
                    f"{payload['portfolio_simulator']['approved_playbook_rows_in_simulator']} / "
                    f"{payload['portfolio_simulator']['approved_playbook_rows_expected']}"
                ),
            },
            {
                "field": "setup_c_full_session_rows_in_simulator",
                "value": payload["portfolio_simulator"]["setup_c_full_session_rows_in_simulator"],
            },
        ]
    )
    rows = pd.DataFrame(payload["rows"])
    reports = pd.DataFrame(payload["report_rows"])
    strategy_contracts = pd.DataFrame(payload["strategy_contract_rows"])
    scanner_adapters = pd.DataFrame(payload["scanner_adapter_rows"])
    path.write_text(
        f"""# Feature Wiring Audit

Generated: {payload["generated_at_et"]}

This report checks whether dashboard-facing features are wired to the same
approved/watch symbol universe.

## Summary

{markdown_table(summary)}

## Symbol Wiring

{markdown_table(rows)}

## Report Wiring

{markdown_table(reports)}

## Strategy Contract Wiring

{markdown_table(strategy_contracts)}

## Scanner Adapter Wiring

{markdown_table(scanner_adapters)}

## Portfolio Simulator Wiring

{markdown_table(pd.DataFrame([payload["portfolio_simulator"]]))}

## Guardrail

{payload["guardrail"]}
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit dashboard feature wiring.")
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull candle CSVs live.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.data_dir, args.output_dir)
    (args.output_dir / "feature_wiring_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown(args.output_dir / "feature_wiring_audit.md", payload)
    print(f"Wrote {args.output_dir / 'feature_wiring_audit.md'}")


if __name__ == "__main__":
    main()
