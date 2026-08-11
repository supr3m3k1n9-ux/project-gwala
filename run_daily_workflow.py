"""Run the daily Project Gwala paper workflow.

This is research and paper workflow only. It can optionally refresh local
market-data CSVs, then runs the daily scanner and paper review. It does not
place orders, create live alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import subprocess
import sys
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols
from run_playbook import markdown_table


DEFAULT_SYMBOLS = playbook_symbols("approved_plus_watch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the daily Project Gwala paper workflow.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS, help="Symbols to refresh when requested.")
    parser.add_argument("--refresh-data", action="store_true", help="Refresh local market-data CSV candles first.")
    parser.add_argument(
        "--data-provider",
        choices=["webull", "polygon"],
        default="webull",
        help="Market-data provider used when --refresh-data is set.",
    )
    parser.add_argument(
        "--polygon-start-date",
        default="",
        help="Polygon refresh start date in YYYY-MM-DD format. Defaults to 60 calendar days ago.",
    )
    parser.add_argument(
        "--polygon-end-date",
        default="",
        help="Polygon refresh end date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--polygon-timeframes",
        nargs="+",
        default=["M5", "M30", "M60", "D"],
        help="Polygon timeframes to refresh.",
    )
    parser.add_argument(
        "--skip-provider-acceptance",
        action="store_true",
        help="Skip the current-session provider preflight. Use only for offline historical maintenance.",
    )
    parser.add_argument("--entry-count", type=int, default=1200, help="30m candles per Webull page.")
    parser.add_argument("--exit-count", type=int, default=1200, help="5m candles per Webull page.")
    parser.add_argument("--entry-pages", type=int, default=1, help="30m history pages for daily refresh.")
    parser.add_argument("--exit-pages", type=int, default=1, help="5m history pages for daily refresh.")
    parser.add_argument("--chart-m1-count", type=int, default=240, help="1m chart-only candles per Webull page.")
    parser.add_argument("--chart-m15-count", type=int, default=400, help="15m chart-only candles per Webull page.")
    parser.add_argument("--chart-m60-count", type=int, default=400, help="1h chart-only candles per Webull page.")
    parser.add_argument("--chart-d-count", type=int, default=260, help="Daily chart-only candles per Webull page.")
    parser.add_argument("--pause", type=float, default=5.0, help="Seconds between Webull requests.")
    parser.add_argument(
        "--append-current-signals",
        action="store_true",
        help="Deprecated safety stop: paper imports must be run separately after candidate review.",
    )
    parser.add_argument("--account-size", type=float, default=10_000.0, help="Paper account size for sizing.")
    parser.add_argument(
        "--risk-per-trade-pct",
        type=float,
        default=0.005,
        help="Paper account percentage risked per trade. 0.005 means 0.5%%.",
    )
    parser.add_argument(
        "--auto-confirm-paper-exits",
        action="store_true",
        help=(
            "Write local paper exit updates when saved 5m candles hit stop, target, or end-of-day rules. "
            "This is local paper-log automation only; it never places broker orders."
        ),
    )
    return parser.parse_args()


def enforce_manual_paper_import(args: argparse.Namespace) -> None:
    """Prevent an automated workflow run from declaring a reviewed paper trade."""

    if args.append_current_signals:
        raise ValueError(
            "Automatic paper import is disabled. Run the workflow, review the current-candle candidate, "
            "then run python run_paper_import.py separately."
        )


def run_step(command: list[str]) -> None:
    """Run one workflow command and fail fast if it errors."""

    print(f"\n=== {' '.join(command)} ===", flush=True)
    subprocess.run(command, check=True)


def default_polygon_dates(args: argparse.Namespace) -> tuple[str, str]:
    """Return the Polygon date window for a workflow refresh."""

    today = datetime.now(MARKET_TZ).date()
    start = args.polygon_start_date or str(today - timedelta(days=60))
    end = args.polygon_end_date or str(today)
    return start, end


def refresh_webull_data(python: str, args: argparse.Namespace) -> None:
    """Refresh Webull CSVs once, then evaluate both approved setup families."""

    base_command = [
        python,
        "run_webull_watchlist.py",
        "--symbols",
        *[symbol.upper() for symbol in args.symbols],
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
    run_step([*base_command, "--candidate-preset", "best_plus_market"])
    # Setup B uses the same newly fetched candles, so a second API pull only
    # adds delay and request volume without adding information.
    run_step([*base_command, "--reuse-csv", "--candidate-preset", "setup_b"])
    # Setup C studies the whole regular session, including late-day volume,
    # while still keeping entries research/paper-review only.
    run_step([*base_command, "--reuse-csv", "--candidate-preset", "full_session"])
    run_step(
        [
            python,
            "run_repair_m30_from_lower_timeframe.py",
            "--symbols",
            *[symbol.upper() for symbol in args.symbols],
            "--data-dir",
            str(args.output_dir),
            "--output-dir",
            str(args.output_dir),
        ]
    )


def refresh_polygon_data(python: str, args: argparse.Namespace) -> None:
    """Refresh Polygon CSVs once, then evaluate both approved setup families."""

    start_date, end_date = default_polygon_dates(args)
    # Polygon rate-limits bursts on small plans, so the default dashboard path
    # uses a provider-safe pace even if the general Webull pause is lower.
    pause_seconds = max(float(args.pause), 13.0)
    run_step(
        [
            python,
            "run_polygon_watchlist.py",
            "--symbols",
            *[symbol.upper() for symbol in args.symbols],
            "--timeframes",
            *[timeframe.upper() for timeframe in args.polygon_timeframes],
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--output-dir",
            str(args.output_dir),
            "--pause",
            str(pause_seconds),
            "--max-retries",
            "1",
            "--retry-wait",
            "65",
            "--allow-partial",
        ]
    )
    base_command = [
        python,
        "run_webull_watchlist.py",
        "--symbols",
        *[symbol.upper() for symbol in args.symbols],
        "--output-dir",
        str(args.output_dir),
        "--reuse-csv",
    ]
    run_step([*base_command, "--candidate-preset", "best_plus_market"])
    run_step([*base_command, "--candidate-preset", "setup_b"])
    run_step([*base_command, "--candidate-preset", "full_session"])


def refresh_data(python: str, args: argparse.Namespace) -> None:
    """Refresh market-data CSVs using the selected provider."""

    if args.data_provider == "polygon":
        refresh_polygon_data(python, args)
        return
    refresh_webull_data(python, args)


def provider_acceptance_command(python: str, args: argparse.Namespace) -> list[str]:
    """Return the provider preflight command for market-hours refreshes."""

    if args.data_provider != "polygon" or getattr(args, "skip_provider_acceptance", False):
        return []
    symbols = [symbol.upper() for symbol in args.symbols]
    acceptance_symbols = [symbol for symbol in ["SPY", "QQQ"] if symbol in symbols]
    if not acceptance_symbols:
        acceptance_symbols = symbols[:2]
    return [
        python,
        "run_provider_acceptance.py",
        "--provider",
        "polygon",
        "--symbols",
        *acceptance_symbols,
        "--timeframes",
        "M5",
        "M30",
        "--output-dir",
        str(args.output_dir),
    ]


def run_provider_acceptance(python: str, args: argparse.Namespace) -> None:
    """Fail fast if the selected provider is not returning current-session bars."""

    command = provider_acceptance_command(python, args)
    if command:
        run_step(command)


def research_snapshot_commands(python: str, output_dir: Path) -> list[list[str]]:
    """Return local research-gate rebuild commands for the app snapshot."""

    research_dir = output_dir / "universe_expansion"
    return [
        [python, "run_research_confidence.py", "--output-dir", str(research_dir)],
        [python, "run_promotion_review.py", "--output-dir", str(output_dir), "--research-dir", str(research_dir)],
    ]


def rebuild_research_snapshot(python: str, output_dir: Path) -> None:
    """Rebuild research confidence and promotion review from saved backtests."""

    for command in research_snapshot_commands(python, output_dir):
        run_step(command)


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists."""

    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def write_summary(output_dir: Path, refreshed: bool, appended: bool) -> Path:
    """Write a compact daily workflow summary."""

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(output_dir / "position_sizing.csv")
    paper_review = read_csv_or_empty(output_dir / "paper_review_clean_trades.csv")
    observations = read_csv_or_empty(Path("data") / "forward_signal_observations.csv")

    if scanner.empty:
        scanner_counts = pd.DataFrame()
        current_candidates = pd.DataFrame()
    else:
        scanner_counts = scanner.groupby("scanner_status").size().reset_index(name="setups")
        current_candidates = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]

    if paper_review.empty:
        paper_snapshot = pd.DataFrame()
    else:
        paper_snapshot = (
            paper_review.groupby("signal_status")["review_r"]
            .agg(paper_trades="count", avg_r="mean", total_r="sum")
            .reset_index()
            .round(4)
        )

    if observations.empty:
        observation_snapshot = pd.DataFrame()
    else:
        observation_snapshot = observations.groupby("signal_status").size().reset_index(name="observations")

    if sizing.empty:
        sizing_snapshot = pd.DataFrame()
        eligible_sizes = pd.DataFrame()
    else:
        sizing_snapshot = sizing.groupby("sizing_status").size().reset_index(name="setups")
        eligible_sizes = sizing[sizing["sizing_status"] == "size_ok"]

    path = output_dir / "daily_workflow_summary.md"
    path.write_text(
        f"""# Daily Workflow Summary

This is the daily Project Gwala paper workflow.

Important: this is research/paper workflow only. It does not place orders,
create live alerts, or connect to broker execution.

## Run Settings

```text
Refreshed market data: {refreshed}
Appended current-candle signals: {appended}
```

## Scanner Status

{markdown_table(scanner_counts)}

## Current-Candle Candidates

{markdown_table(current_candidates)}

## Position Sizing Snapshot

{markdown_table(sizing_snapshot)}

## Eligible Paper Sizes

{markdown_table(eligible_sizes)}

## Forward Signal Observations

{markdown_table(observation_snapshot)}

## Paper Review Snapshot

{markdown_table(paper_snapshot)}

## Main Files

```text
logs/daily_paper_signal_scanner.md
logs/forward_signal_observations.md
data/forward_signal_observations.csv
logs/position_sizing.md
logs/forward_sample_queue.md
logs/filter_rejection_report.md
logs/system_state.md
logs/daily_paper_trade_import_template.csv
data/paper_trades.csv
logs/paper_exit_audit.md
logs/paper_review_summary.md
```
""",
        encoding="utf-8",
    )
    return path


def main() -> None:
    args = parse_args()
    enforce_manual_paper_import(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    refresh_started_at = ""
    refresh_ended_at = ""

    if args.refresh_data:
        run_provider_acceptance(python, args)
        refresh_started_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        refresh_data(python, args)
        refresh_ended_at = datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        run_step(
            [
                python,
                "run_refresh_audit.py",
                "--record",
                "--provider",
                args.data_provider,
                "--symbols",
                *[symbol.upper() for symbol in args.symbols],
                "--output-dir",
                str(args.output_dir),
            ]
        )
    else:
        run_step([python, "run_refresh_audit.py", "--output-dir", str(args.output_dir)])
    run_step(
        [
            python,
            "run_provider_stability_audit.py",
            "--provider",
            args.data_provider,
            "--symbols",
            *[symbol.upper() for symbol in args.symbols],
            "--output-dir",
            str(args.output_dir),
            "--refresh-started-at",
            refresh_started_at,
            "--refresh-ended-at",
            refresh_ended_at,
        ]
    )

    run_step(
        [
            python,
            "run_daily_scanner.py",
            "--mode",
            "approved_plus_watch",
            "--symbols",
            *[symbol.upper() for symbol in args.symbols],
            "--output-dir",
            str(args.output_dir),
        ]
    )
    run_step([python, "run_near_miss_analytics.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_data_integrity.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_forward_observation_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_near_miss_analytics.py", "--output-dir", str(args.output_dir)])
    run_step(
        [
            python,
            "run_position_sizer.py",
            "--output-dir",
            str(args.output_dir),
            "--account-size",
            str(args.account_size),
            "--risk-per-trade-pct",
            str(args.risk_per_trade_pct),
        ]
    )
    run_step([python, "run_pre_entry_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_entry_packet.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_gate_v2.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_candidate_window_ledger.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_validation_sample_import.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_execution_simulator.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_candidate_alerts.py", "--output-dir", str(args.output_dir)])
    open_monitor_command = [python, "run_open_paper_monitor.py", "--output-dir", str(args.output_dir)]
    if args.auto_confirm_paper_exits:
        open_monitor_command.append("--confirm-updates")
    run_step(open_monitor_command)

    run_step([python, "run_exit_audit.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_forward_sample_queue.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_no_trade_analysis.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_post_scan_digest.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_observation_reconciliation.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_checkpoint_report.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_candidate_aging.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_forward_evidence.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_setup_health.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_mean_reversion.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_mean_reversion_walk_forward.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_mean_reversion_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_mean_reversion_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_mean_reversion_paper_watch_gate.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_gap_fill_fade.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_gap_fill_fade_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_gap_fill_fade_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_reclaim_reject.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_reclaim_reject_walk_forward.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_reclaim_reject_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_reclaim_reject_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_reclaim_reject_paper_watch_gate.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_vwap_reclaim_reject_evidence_maturity.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_breakout.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_breakout_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_breakout_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trend_pullback_continuation.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trend_pullback_continuation_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trend_pullback_continuation_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_failure.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_failure_shadow_samples.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_failure_forward_observations.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_strategy_walk_forward_matrix.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_research_strategy_tightened_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_failure_walk_forward_deepening.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_breakout_walk_forward_deepening.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_gap_fill_fade_paper_watch_gate.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_breakout_paper_watch_gate.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_opening_range_failure_paper_watch_gate.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trend_pullback_tightened_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trend_pullback_continuation_paper_watch_gate.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_strategy_evidence_accumulator.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_strategy_vault.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_activation_rules.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_market_regime_router.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_pre_entry_review.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_entry_packet.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_gate_v2.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_candidate_window_ledger.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_validation_sample_import.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_filter_rejection_report.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_strategy_backtest_coverage.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_validation_deepening_queue.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_strategy_triage.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_phase_milestones.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_almost_ready_breakout.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_probation_watch.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_controlled_universe_expansion.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_refresh_status.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_market_sprint_mode.py", "--output-dir", str(args.output_dir)])
    rebuild_research_snapshot(python, args.output_dir)
    run_step([python, "run_historical_bucket_sync.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_setup_replay.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_system_state.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_strategy_improvement_plan.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_feature_wiring_audit.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_system_state.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_dashboard.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_premarket_plan.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_trade_checklist.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_mistake_tracker.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_daily_recap.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_readiness_check.py", "--output-dir", str(args.output_dir)])
    summary_path = write_summary(args.output_dir, refreshed=args.refresh_data, appended=args.append_current_signals)
    # Refresh the app snapshot after every supporting report has been rebuilt,
    # so its app-health timestamps describe this completed workflow run.
    run_step([python, "run_system_state.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_morning_watchdog.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_daily_automation_timeline.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_phase_milestones.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_gate_v2.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_candidate_window_ledger.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_paper_validation_sample_import.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_filter_rejection_report.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_daily_ship_report.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_historical_bucket_sync.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_market_sprint_mode.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_system_state.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_dashboard_data_preflight.py", "--output-dir", str(args.output_dir)])
    run_step([python, "run_data_flow_sentinel.py", "--output-dir", str(args.output_dir), "--strict"])
    run_step([python, "run_system_state.py", "--output-dir", str(args.output_dir)])
    print(f"\nSaved daily workflow summary: {summary_path}")


if __name__ == "__main__":
    main()
