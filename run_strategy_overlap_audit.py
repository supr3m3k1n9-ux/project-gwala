"""Audit Project Gwala against a professional trend-following framework.

This report is intentionally diagnostic. It does not change scanner behavior,
paper logs, broker settings, Webull settings, or execution state.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table


HANDOFF_PATH = Path("/Users/roy/Downloads/project_gwala_strategy_upgrade_handoff.md")


@dataclass(frozen=True)
class AuditRow:
    """One framework requirement compared against current code."""

    area: str
    framework_goal: str
    status: str
    current_evidence: str
    gap: str
    priority: str
    recommended_next_step: str


def build_audit_rows() -> pd.DataFrame:
    """Return the strategy overlap audit table."""

    rows = [
        AuditRow(
            area="Core strategy direction",
            framework_goal="Systematic VWAP/EMA trend-following pullback continuation.",
            status="exists",
            current_evidence="strategies/opening_trend_continuation.py and strategies/opening_trend_continuation_short.py implement VWAP/EMA pullback/reclaim logic.",
            gap="No major gap; keep this as the core strategy instead of adding unrelated indicators.",
            priority="keep",
            recommended_next_step="Preserve the current VWAP/EMA strategy and compare upgrades against the baseline.",
        ),
        AuditRow(
            area="Multi-timeframe structure",
            framework_goal="Use higher timeframe thesis, 30m entries, and lower timeframe exits.",
            status="exists",
            current_evidence="config/settings.py defines thesis_interval=60m, execution_interval=30m, exit_interval=5m; run_webull_watchlist.py adds higher-timeframe bias.",
            gap="No major gap for the current research workflow.",
            priority="keep",
            recommended_next_step="Keep testing whether higher-timeframe bias improves results per symbol/setup.",
        ),
        AuditRow(
            area="Broad market regime filter",
            framework_goal="Filter or classify long exposure using SPY/QQQ trend regime and volatility state.",
            status="partial",
            current_evidence="run_webull_watchlist.py has market_confirmed variants using a broad-market bullish bias; run_regime_review.py labels bullish/choppy/bearish and volatility regimes.",
            gap="The regime engine exists as research/review logic, but it is not yet a single reusable module used consistently by scanner, sizing, dashboard, and reports.",
            priority="high",
            recommended_next_step="Promote regime labeling into a shared module and add a daily regime report before changing trade eligibility.",
        ),
        AuditRow(
            area="Stock-level trend filter",
            framework_goal="Require price above/below 200 EMA, 9/21 EMA alignment, and VWAP control.",
            status="exists",
            current_evidence="Long and short strategy modules require regime EMA, EMA stack, VWAP control, and reclaim/reject behavior.",
            gap="Rules are implemented, but not summarized in a single user-facing rule audit per candidate.",
            priority="medium",
            recommended_next_step="Expose per-candidate rule pass/fail details in strategy audit or scanner output.",
        ),
        AuditRow(
            area="Pullback entry logic",
            framework_goal="Wait for pullback toward VWAP/21 EMA and confirmation candle.",
            status="exists",
            current_evidence="opening_trend_continuation.py uses pullback_to_value and bullish_reclaim; short module mirrors this with short_pullback_to_value and bearish_reject.",
            gap="No major gap for baseline logic.",
            priority="keep",
            recommended_next_step="Keep comparing baseline pullback entries with quality_entry variants.",
        ),
        AuditRow(
            area="Relative volume filter",
            framework_goal="Require meaningful relative volume, with thresholds tested independently.",
            status="exists",
            current_evidence="strategies/quality_filters.py calculates relative_volume and strong_relative_volume; config/settings.py exposes min_relative_volume; run_webull_watchlist.py has relvol variants.",
            gap="Threshold sensitivity exists, but the dashboard could make rel-volume blocker impact easier to read.",
            priority="medium",
            recommended_next_step="Add a filter impact report showing performance at 1.0x, 1.2x, 1.5x, and 2.0x when enough sample exists.",
        ),
        AuditRow(
            area="Liquidity and spread filter",
            framework_goal="Avoid illiquid names, low dollar volume, and wide spreads.",
            status="missing",
            current_evidence="Approved universe uses liquid large-cap symbols, but no explicit average dollar-volume or spread filter was found.",
            gap="No formal liquidity/spread gate. Spread may need broker quote data that is not currently in saved candle CSVs.",
            priority="medium",
            recommended_next_step="Start with candle-based dollar-volume filter; add spread only when reliable quote data is available.",
        ),
        AuditRow(
            area="Reward-to-risk validation",
            framework_goal="Require at least 2:1 reward-to-risk before allowing trades.",
            status="partial",
            current_evidence="risk_management/rules.py builds targets from reward_multiple; quality filters estimate room_to_resistance_r/support; settings.reward_multiple defaults to 2.0.",
            gap="The target is 2R by construction, but the scanner needs a stricter explicit eligibility gate for clean room-to-target and nearby resistance/support.",
            priority="high",
            recommended_next_step="Create an explicit reward_to_risk_status field in scanner/sizing and block trades below the approved threshold.",
        ),
        AuditRow(
            area="Risk-based position sizing",
            framework_goal="Size by account risk and distance from entry to stop, not fixed shares.",
            status="exists",
            current_evidence="run_position_sizer.py calculates risk budget, risk per share, suggested shares, estimated risk, and session gates.",
            gap="No major gap for local paper validation.",
            priority="keep",
            recommended_next_step="Keep broker execution disabled and continue using local paper sizing gates.",
        ),
        AuditRow(
            area="Structured stop loss logic",
            framework_goal="Use VWAP/EMA/swing/ATR structure stops, not arbitrary stops.",
            status="partial",
            current_evidence="risk_management/rules.py places buffered stops around VWAP/EMA references; backtesting engine applies those stops in 5m management.",
            gap="ATR and swing-low/swing-high stop variants are not yet implemented as controlled comparisons.",
            priority="medium",
            recommended_next_step="Add stop-model variants only after regime/R:R reporting is stable.",
        ),
        AuditRow(
            area="Exit model comparison",
            framework_goal="Compare fixed 2R, fixed 3R, partial+runner, ATR trail, and trailing exits.",
            status="partial",
            current_evidence="backtesting/engine.py supports ExitProfile variants such as no_vwap_exit, two_vwap_closes, EMA9 exit, breakeven after 1R, and reward multiple changes.",
            gap="Fixed 3R can be tested via reward_multiple, but partial+runner and ATR trail are not implemented.",
            priority="medium",
            recommended_next_step="Next exit upgrade should be a controlled partial+runner simulation, not a scanner change.",
        ),
        AuditRow(
            area="Trade quality scoring",
            framework_goal="Score setups instead of only binary yes/no signals.",
            status="exists",
            current_evidence="strategies/quality_filters.py creates quality_score, quality_grade, elite_filter_pass, and quality_entry_signal.",
            gap="Score is currently 0-10 style rather than 0-100, but functionally covers the same concept.",
            priority="keep",
            recommended_next_step="Keep existing score scale unless dashboard readability calls for a 0-100 display mapping.",
        ),
        AuditRow(
            area="Backtest metrics in R",
            framework_goal="Report expectancy, profit factor, drawdown, win rate, and grouped performance.",
            status="exists",
            current_evidence="backtesting/metrics.py reports expectancy_r, profit_factor, max_drawdown_r, sharpe_like, and grouped exit breakdowns.",
            gap="Monthly return/drawdown and longest losing streak can be expanded, but core R metrics exist.",
            priority="medium",
            recommended_next_step="Add monthly/streak metrics after the audit/report workflow is stable.",
        ),
        AuditRow(
            area="Controlled filter testing",
            framework_goal="Test each filter independently and in combination against baseline.",
            status="partial",
            current_evidence="run_webull_watchlist.py has variants; run_controlled_variant_review.py, run_entry_optimizer.py, and run_exit_optimizer.py compare candidates.",
            gap="No single filter-impact matrix maps each professional-framework filter to performance deltas.",
            priority="high",
            recommended_next_step="Build a filter impact report after formalizing the regime and R:R status fields.",
        ),
        AuditRow(
            area="Paper validation before execution",
            framework_goal="Paper trade for at least 30 trading days/trades before live deployment.",
            status="exists",
            current_evidence="Dashboard/paper workflow has local paper session cycle, candidate alerts, open paper monitor, exit audit, and 30/60 trade gates.",
            gap="Sample is currently 0 completed paper trades, so the process is ready but the evidence is not collected yet.",
            priority="active",
            recommended_next_step="Use the dashboard paper preview during live sessions and collect the first 30 allowed completed paper trades.",
        ),
        AuditRow(
            area="Broker execution safety",
            framework_goal="Do not scale to live trading until strategy and paper execution are proven.",
            status="exists",
            current_evidence="System state and dashboard actions keep live_trading_enabled, broker_order_execution_enabled, and real_money_ready disabled.",
            gap="No gap. This is an intentional safety boundary.",
            priority="keep",
            recommended_next_step="Do not add broker order placement until paper validation gates are passed and explicitly approved.",
        ),
    ]
    return pd.DataFrame([asdict(row) for row in rows])


def summary_counts(audit: pd.DataFrame) -> pd.DataFrame:
    """Return count by implementation status."""

    return audit.groupby("status", sort=True).size().reset_index(name="items")


def priority_plan(audit: pd.DataFrame) -> pd.DataFrame:
    """Return high-priority missing or partial work."""

    order = {"high": 0, "medium": 1, "active": 2, "keep": 3}
    plan = audit[audit["priority"].isin(["high", "medium", "active"])].copy()
    plan["_order"] = plan["priority"].map(order).fillna(9)
    return plan.sort_values(["_order", "area"]).drop(columns=["_order"])[
        ["priority", "area", "status", "recommended_next_step"]
    ]


def write_report(path: Path, audit: pd.DataFrame, source_path: Path = HANDOFF_PATH) -> None:
    """Write the Markdown strategy overlap audit."""

    counts = summary_counts(audit)
    plan = priority_plan(audit)
    exists_count = int((audit["status"] == "exists").sum())
    partial_count = int((audit["status"] == "partial").sum())
    missing_count = int((audit["status"] == "missing").sum())
    source_note = str(source_path) if source_path.exists() else "Handoff source file was not found locally."

    path.write_text(
        f"""# Strategy Overlap Audit

This report compares Project Gwala's current VWAP/EMA strategy code against
the professional systematic trend-following framework from the supplied
handoff.

Important: this is research and paper-validation only. It does not alter
scanner rules, paper logs, broker settings, Webull settings, or execution
state.

```text
Framework source: {source_note}
Current strategy posture: keep the VWAP/EMA pullback-continuation core, then improve selectivity and measurement.
```

## Executive Summary

```text
Exists: {exists_count}
Partial: {partial_count}
Missing: {missing_count}
Highest-value next move: formalize shared market regime + explicit reward-to-risk status before adding more entry rules.
```

## Status Counts

{markdown_table(counts)}

## Recommended Priority Plan

{markdown_table(plan)}

## Full Audit Matrix

{markdown_table(audit)}

## Recommended Implementation Order

```text
1. Promote market regime labeling into a shared reusable module and daily report.
2. Add explicit reward_to_risk_status to scanner/sizing outputs.
3. Add candle-based liquidity/dollar-volume filter.
4. Build filter impact matrix for regime, relative volume, liquidity, and R:R.
5. Add controlled partial+runner exit simulation after measurement is stable.
6. Keep collecting local paper trades; do not add broker execution yet.
```
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Project Gwala against the strategy upgrade framework.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where the audit report is saved.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit = build_audit_rows()
    csv_path = args.output_dir / "strategy_overlap_audit.csv"
    md_path = args.output_dir / "strategy_overlap_audit.md"
    audit.to_csv(csv_path, index=False)
    write_report(md_path, audit)
    print(f"Saved strategy overlap CSV: {csv_path}")
    print(f"Saved strategy overlap report: {md_path}")


if __name__ == "__main__":
    main()
