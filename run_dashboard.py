"""Build the Project Gwala mission-control dashboard.

This is research and paper workflow only. It gathers the existing scanner,
position-sizing, paper-review, holdout, portfolio, and trade-management reports
into one plain-English dashboard. It does not fetch data, create alerts, place
orders, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ, market_session_for_date, next_market_session
from config.settings import STRATEGY
from reports.system_state import build_system_state
from run_playbook import markdown_table


ALLOWED_BASELINE_R = 0.1965
FIRST_PAPER_GATE = 30
STRONG_PAPER_GATE = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Project Gwala dashboard.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--paper-csv",
        type=Path,
        default=Path("data/paper_trades.csv"),
        help="Manual paper-trade log.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV if it exists and is parseable."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_metric_table(path: Path) -> dict[str, str]:
    """Read the small metric table from a Markdown portfolio report."""

    if not path.exists():
        return {}

    metrics: dict[str, str] = {}
    in_metrics = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Overall Metrics":
            in_metrics = True
            continue
        if in_metrics and line.startswith("## "):
            break
        if in_metrics and line.startswith("|") and "---" not in line and "Metric" not in line:
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) == 2:
                metrics[parts[0]] = parts[1]
    return metrics


def regular_market_times() -> tuple:
    """Return configured market open/close times with NY timezone info."""

    open_time = datetime.strptime(STRATEGY.market_open, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    close_time = datetime.strptime(STRATEGY.market_close, "%H:%M").time().replace(tzinfo=MARKET_TZ)
    return open_time, close_time


def market_context() -> dict[str, object]:
    """Return today's market status and the next open session."""

    open_time, close_time = regular_market_times()
    now = datetime.now(MARKET_TZ)
    today_session = market_session_for_date(now.date(), open_time, close_time)
    next_session = next_market_session(now, open_time, close_time)
    return {
        "today": now.date(),
        "today_reason": today_session.reason,
        "is_market_day": today_session.is_market_day,
        "next_session_date": next_session.session_date,
        "next_session_reason": next_session.reason,
    }


def scanner_latest_date(scanner: pd.DataFrame) -> str:
    """Return the latest scanner session date."""

    if scanner.empty or "scan_date" not in scanner.columns:
        return ""
    values = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
    return values[-1] if values else ""


def scanner_data_state(scanner: pd.DataFrame, context: dict[str, object]) -> dict[str, object]:
    """Classify whether scanner data is fresh enough to act on."""

    latest = scanner_latest_date(scanner)
    today = str(context["today"])
    next_session_date = str(context["next_session_date"])

    if not latest:
        status = "missing"
        action = "Run the daily workflow before using the scanner."
    elif latest == today and context["is_market_day"]:
        status = "fresh_for_today"
        action = "Current-candle candidates can be reviewed for paper trading."
    elif latest == next_session_date:
        status = "prepared_for_next_session"
        action = "Review only until the session is open and data has been refreshed."
    else:
        status = "stale"
        action = f"Refresh market data on {next_session_date} before importing or sizing any paper trade."

    return {
        "latest_scanner_session": latest or "unknown",
        "market_today": today,
        "market_today_status": context["today_reason"],
        "next_market_session": next_session_date,
        "next_market_session_status": context["next_session_reason"],
        "data_status": status,
        "action": action,
    }


def status_counts(frame: pd.DataFrame, column: str, count_name: str) -> pd.DataFrame:
    """Summarize a status column."""

    if frame.empty or column not in frame.columns:
        return pd.DataFrame()
    return frame.groupby(column).size().reset_index(name=count_name).sort_values(column)


def paper_progress(paper_log: pd.DataFrame, paper_review: pd.DataFrame) -> dict[str, object]:
    """Calculate paper-trading progress toward confidence gates."""

    logged_rows = 0 if paper_log.empty else len(paper_log)
    completed_rows = 0 if paper_review.empty else len(paper_review)

    allowed = pd.DataFrame()
    blocked = pd.DataFrame()
    if not paper_review.empty and "signal_status" in paper_review.columns:
        allowed = paper_review[paper_review["signal_status"] == "allowed"]
        blocked = paper_review[paper_review["signal_status"] == "blocked"]

    allowed_count = len(allowed)
    allowed_avg = float(allowed["review_r"].mean()) if allowed_count else 0.0
    blocked_count = len(blocked)
    blocked_avg = float(blocked["review_r"].mean()) if blocked_count else 0.0

    return {
        "logged_rows": logged_rows,
        "completed_rows": completed_rows,
        "allowed_count": allowed_count,
        "allowed_avg_r": round(allowed_avg, 4),
        "blocked_count": blocked_count,
        "blocked_avg_r": round(blocked_avg, 4),
        "first_gate_remaining": max(FIRST_PAPER_GATE - allowed_count, 0),
        "strong_gate_remaining": max(STRONG_PAPER_GATE - allowed_count, 0),
    }


def progress_frame(progress: dict[str, object]) -> pd.DataFrame:
    """Build a dashboard table for paper progress."""

    return pd.DataFrame(
        [
            {"checkpoint": "paper rows logged", "value": progress["logged_rows"]},
            {"checkpoint": "completed paper trades", "value": progress["completed_rows"]},
            {"checkpoint": "allowed completed trades", "value": progress["allowed_count"]},
            {"checkpoint": "allowed average R", "value": progress["allowed_avg_r"]},
            {"checkpoint": "blocked/watch-only completed", "value": progress["blocked_count"]},
            {"checkpoint": "blocked average R", "value": progress["blocked_avg_r"]},
            {"checkpoint": "trades until 30-trade gate", "value": progress["first_gate_remaining"]},
            {"checkpoint": "trades until 60-trade gate", "value": progress["strong_gate_remaining"]},
        ]
    )


def dashboard_data_state(system_state: dict) -> dict[str, object]:
    """Adapt app system state to the dashboard data-freshness table."""

    market = system_state["market"]
    freshness = system_state["data_freshness"]
    return {
        "latest_scanner_session": freshness["latest_scanner_session"],
        "market_today": market["today"],
        "market_today_status": market["today_status"],
        "next_market_session": market["next_market_session"],
        "next_market_session_status": market["next_market_session_status"],
        "data_status": freshness["data_status"],
        "action": freshness["action"],
    }


def dashboard_progress(system_state: dict) -> dict[str, object]:
    """Adapt app system state to the dashboard paper-progress table."""

    paper = system_state["paper_progress"]
    return {
        "logged_rows": paper["paper_rows_logged"],
        "completed_rows": paper["completed_paper_trades"],
        "allowed_count": paper["allowed_completed_trades"],
        "allowed_avg_r": paper["allowed_average_r"],
        "blocked_count": paper["blocked_completed_trades"],
        "blocked_avg_r": paper["blocked_average_r"],
        "first_gate_remaining": paper["first_gate_remaining"],
        "strong_gate_remaining": paper["strong_gate_remaining"],
    }


def holdout_snapshot(holdout: pd.DataFrame) -> pd.DataFrame:
    """Keep the main weakness_v1 holdout rows."""

    if holdout.empty:
        return pd.DataFrame()
    filtered = holdout[holdout["trade_filter"] == "weakness_v1"].copy()
    keep = [
        "window",
        "accepted_trades",
        "expectancy_r",
        "profit_factor",
        "max_drawdown_r",
        "final_cumulative_r",
        "expectancy_delta",
        "final_r_delta",
    ]
    return filtered[keep]


def portfolio_snapshot(output_dir: Path) -> pd.DataFrame:
    """Read base and weakness portfolio metrics into a comparison table."""

    base = read_metric_table(output_dir / "portfolio_approved_monthly_stop_3r_summary.md")
    weakness = read_metric_table(output_dir / "portfolio_approved_monthly_stop_3r_weakness_v1_summary.md")
    rows = []
    for metric in ["Accepted trades", "Win rate", "Expectancy R", "Profit factor", "Max drawdown R", "Final cumulative R"]:
        rows.append(
            {
                "metric": metric,
                "base_monthly_stop_3r": base.get(metric, ""),
                "weakness_v1": weakness.get(metric, ""),
            }
        )
    return pd.DataFrame(rows)


def management_snapshot(management: pd.DataFrame) -> pd.DataFrame:
    """Return the top management profiles."""

    if management.empty:
        return pd.DataFrame()
    return management.head(5)


def setup_health_snapshot(health: pd.DataFrame) -> pd.DataFrame:
    """Return the setup health rows that most need attention."""

    if health.empty:
        return pd.DataFrame()

    attention = health[health["health_status"].isin(["watch_more", "caution"])].copy()
    if attention.empty:
        attention = health.copy()

    keep = [
        "symbol",
        "setup",
        "direction",
        "health_status",
        "health_score",
        "trades",
        "expectancy_r",
        "profit_factor",
        "recent_expectancy_r",
        "flags",
    ]
    return attention[keep].head(12)


def build_warnings(
    scanner: pd.DataFrame,
    sizing: pd.DataFrame,
    progress: dict[str, object],
    holdout: pd.DataFrame,
    data_state: dict[str, object],
    setup_health: pd.DataFrame,
) -> list[str]:
    """Create dashboard warnings."""

    warnings: list[str] = []

    if scanner.empty:
        warnings.append("No scanner output found. Run python run_daily_workflow.py.")
    else:
        if data_state["data_status"] == "stale":
            warnings.append(
                "Scanner data is stale. Do not import or size paper trades until market data is refreshed on the next market session."
            )
        elif data_state["data_status"] == "prepared_for_next_session":
            warnings.append("Scanner data is for a future/next session state. Treat it as prep-only until refreshed during market hours.")

        current = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]
        if current.empty:
            warnings.append("No current-candle paper candidates right now.")
        else:
            warnings.append("Current-candle candidates exist. Use them only if the data status says fresh_for_today.")

    if sizing.empty or sizing[sizing.get("sizing_status", "") == "size_ok"].empty:
        warnings.append("No eligible current-candle position sizes.")

    if int(progress["allowed_count"]) < FIRST_PAPER_GATE:
        warnings.append("Paper sample is too small. Need 30 allowed completed paper trades for the first useful checkpoint.")

    if int(progress["blocked_count"]) > 0 and float(progress["blocked_avg_r"]) > float(progress["allowed_avg_r"]):
        warnings.append("Blocked/watch-only trades are outperforming allowed paper trades. Retest weakness_v1 if this persists.")

    if not holdout.empty:
        second_half = holdout[(holdout["trade_filter"] == "weakness_v1") & (holdout["window"] == "second_half")]
        if not second_half.empty and float(second_half.iloc[0]["final_r_delta"]) < 0:
            warnings.append("Holdout note: weakness_v1 had lower final R in the second half despite slightly better expectancy.")

    if not setup_health.empty:
        caution_count = len(setup_health[setup_health["health_status"].isin(["watch_more", "caution"])])
        if caution_count:
            warnings.append(f"Setup health note: {caution_count} approved setup(s) need watch/caution review.")

    return warnings


def next_action(scanner: pd.DataFrame, sizing: pd.DataFrame, progress: dict[str, object], data_state: dict[str, object]) -> str:
    """Choose a plain-English next action."""

    if scanner.empty:
        return "Run `python run_daily_workflow.py` to generate the scanner, sizing, and paper review."

    if data_state["data_status"] == "stale":
        return f"Prep only. On {data_state['next_market_session']}, run `python run_daily_workflow.py --refresh-data` before importing or sizing any paper trade."

    if data_state["data_status"] == "prepared_for_next_session":
        return "Prep only until the market is open. Refresh during market hours before acting on any candidate."

    eligible = pd.DataFrame()
    if not sizing.empty and "sizing_status" in sizing.columns:
        eligible = sizing[sizing["sizing_status"] == "size_ok"]

    if not eligible.empty:
        return "Current-candle paper candidate exists. Review `logs/position_sizing.md`, then paper trade only if the plan still looks valid."

    if int(progress["allowed_count"]) < FIRST_PAPER_GATE:
        return "Keep running the daily workflow and log valid current-candle paper trades until the 30-trade checkpoint."

    return "Review paper performance against the baseline, then decide whether to continue paper validation or retest filters."


def write_dashboard(
    path: Path,
    scanner: pd.DataFrame,
    sizing: pd.DataFrame,
    paper_log: pd.DataFrame,
    paper_review: pd.DataFrame,
    holdout: pd.DataFrame,
    management: pd.DataFrame,
    setup_health: pd.DataFrame,
    system_state: dict,
    output_dir: Path,
) -> None:
    """Write the dashboard Markdown report."""

    data_state = dashboard_data_state(system_state)
    progress = dashboard_progress(system_state)
    current_candidates = pd.DataFrame()
    if not scanner.empty and data_state["data_status"] == "fresh_for_today":
        current_candidates = scanner[
            scanner["scanner_status"].isin(["allowed", "blocked_watch_only"])
            & (scanner["signal_freshness"] == "current_candle")
        ]

    eligible_sizes = pd.DataFrame()
    if not sizing.empty and "sizing_status" in sizing.columns and data_state["data_status"] == "fresh_for_today":
        eligible_sizes = sizing[sizing["sizing_status"] == "size_ok"]

    warnings = build_warnings(scanner, sizing, progress, holdout, data_state, setup_health)
    warning_text = "\n".join(f"- {warning}" for warning in warnings) if warnings else "No warnings."

    path.write_text(
        f"""# Project Gwala Dashboard

This is the mission-control report for the current research and paper workflow.

Important: this is research/paper workflow only. It does not fetch data, place
orders, create alerts, or connect to broker execution.

## Today's Action

```text
{system_state["readiness_verdict"]}
```

## Warnings

{warning_text}

## Data Freshness

{markdown_table(pd.DataFrame([data_state]))}

## Current-Candle Candidates

{markdown_table(current_candidates)}

## Eligible Position Sizes

{markdown_table(eligible_sizes)}

## Paper Progress

{markdown_table(progress_frame(progress))}

## Scanner Status

{markdown_table(status_counts(scanner, "scanner_status", "setups"))}

## Position Sizing Status

{markdown_table(status_counts(sizing, "sizing_status", "setups"))}

## Portfolio Health

{markdown_table(portfolio_snapshot(output_dir))}

## Holdout Health

{markdown_table(holdout_snapshot(holdout))}

## Setup Health

{markdown_table(setup_health_snapshot(setup_health))}

## Trade Management Health

{markdown_table(management_snapshot(management))}

## Main Files

```text
logs/daily_workflow_summary.md
logs/daily_paper_signal_scanner.md
logs/position_sizing.md
logs/paper_review_summary.md
logs/holdout_validation_report.md
logs/setup_health.md
logs/trade_management_lab.md
logs/project_gwala_dashboard.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    scanner = read_csv_or_empty(args.output_dir / "daily_paper_signal_scanner.csv")
    sizing = read_csv_or_empty(args.output_dir / "position_sizing.csv")
    paper_log = read_csv_or_empty(args.paper_csv)
    paper_review = read_csv_or_empty(args.output_dir / "paper_review_clean_trades.csv")
    holdout = read_csv_or_empty(args.output_dir / "holdout_validation_results.csv")
    management = read_csv_or_empty(args.output_dir / "trade_management_overall.csv")
    setup_health = read_csv_or_empty(args.output_dir / "setup_health.csv")
    system_state = build_system_state(output_dir=args.output_dir, paper_csv=args.paper_csv)

    dashboard_path = args.output_dir / "project_gwala_dashboard.md"
    write_dashboard(
        dashboard_path,
        scanner,
        sizing,
        paper_log,
        paper_review,
        holdout,
        management,
        setup_health,
        system_state,
        args.output_dir,
    )
    print(f"Saved dashboard: {dashboard_path}")


if __name__ == "__main__":
    main()
