"""Portfolio-style simulator for approved playbook trades.

This is still research/backtesting only. It takes the combined playbook trade
log and applies portfolio-level rules such as max open positions, max trades
per day, and max daily realized R loss.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics, calculate_metrics_by_group
from run_playbook import markdown_table


PROFILE_PRESETS = {
    "default": {
        "name": "approved",
        "max_open_positions": 3,
        "max_open_per_symbol": 1,
        "max_trades_per_day": 5,
        "max_daily_loss_r": -3.0,
        "max_monthly_loss_r": None,
    },
    "monthly_stop_3r": {
        "name": "approved_monthly_stop_3r",
        "max_open_positions": 3,
        "max_open_per_symbol": 1,
        "max_trades_per_day": 5,
        "max_daily_loss_r": -3.0,
        "max_monthly_loss_r": -3.0,
    },
    "strict": {
        "name": "approved_strict",
        "max_open_positions": 2,
        "max_open_per_symbol": 1,
        "max_trades_per_day": 4,
        "max_daily_loss_r": -2.0,
        "max_monthly_loss_r": None,
    },
}

TRADE_FILTER_PRESETS = {
    "none": "No extra trade filtering.",
    "weakness_v1": (
        "Block the first weakness-analysis filter set: NVDA short 11am entries, "
        "NVDA short middle relative-volume pockets, and SPY long 0.75-1.0R room-to-target entries."
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply portfolio rules to a playbook trade log.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_PRESETS),
        default="default",
        help="Named portfolio rule preset to use.",
    )
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/playbook_approved_trades.csv"),
        help="Combined playbook trade log to simulate.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where portfolio reports are saved.")
    parser.add_argument("--name", default=None, help="Name used in output filenames.")
    parser.add_argument(
        "--trade-filter",
        choices=sorted(TRADE_FILTER_PRESETS),
        default="none",
        help="Optional research filter applied before portfolio simulation.",
    )
    parser.add_argument("--max-open-positions", type=int, default=None, help="Maximum simultaneous open positions.")
    parser.add_argument(
        "--max-open-per-symbol",
        type=int,
        default=None,
        help="Maximum simultaneous open positions per symbol.",
    )
    parser.add_argument("--max-trades-per-day", type=int, default=None, help="Maximum accepted entries per trading day.")
    parser.add_argument(
        "--max-daily-loss-r",
        type=float,
        default=None,
        help="Stop accepting new trades once realized daily R is at or below this value.",
    )
    parser.add_argument(
        "--max-monthly-loss-r",
        type=float,
        default=None,
        help="Optional: stop accepting new trades once realized monthly R is at or below this value.",
    )
    args = parser.parse_args()
    apply_profile_defaults(args)
    if args.trade_filter != "none" and args.name == PROFILE_PRESETS[args.profile]["name"]:
        args.name = f"{args.name}_{args.trade_filter}"
    return args


def apply_profile_defaults(args: argparse.Namespace) -> None:
    """Fill any missing portfolio rule values from the selected preset."""

    preset = PROFILE_PRESETS[args.profile]
    for key, value in preset.items():
        if getattr(args, key) is None:
            setattr(args, key, value)


def add_session_date(trades: pd.DataFrame) -> pd.DataFrame:
    """Add New York session dates for portfolio daily limits."""

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["exit_time"] = pd.to_datetime(result["exit_time"], utc=True)
    result["portfolio_session_date"] = result["entry_time"].dt.tz_convert("America/New_York").dt.date.astype(str)
    result["portfolio_month"] = result["entry_time"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    return result


def apply_trade_filter(trades: pd.DataFrame, filter_name: str) -> tuple[pd.DataFrame, int]:
    """Apply optional entry-known research filters before portfolio simulation."""

    if filter_name == "none":
        return trades.copy(), 0

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["entry_hour_et"] = result["entry_time"].dt.tz_convert("America/New_York").dt.hour
    result["relative_volume"] = result["relative_volume"].astype(float)
    result["room_to_resistance_r"] = result["room_to_resistance_r"].astype(float)

    if filter_name == "weakness_v1":
        nvda_short = (result["symbol"] == "NVDA") & (result["playbook_setup"] == "Setup B Short")
        spy_long = (result["symbol"] == "SPY") & (result["playbook_setup"] == "Setup A Long")

        nvda_weak_relvol = (
            ((result["relative_volume"] >= 0.75) & (result["relative_volume"] < 1.0))
            | ((result["relative_volume"] >= 1.25) & (result["relative_volume"] < 1.5))
        )
        nvda_weak_time = result["entry_hour_et"] == 11
        spy_limited_room = (result["room_to_resistance_r"] >= 0.75) & (result["room_to_resistance_r"] < 1.0)

        keep = ~((nvda_short & (nvda_weak_relvol | nvda_weak_time)) | (spy_long & spy_limited_room))
        return result.loc[keep].drop(columns=["entry_hour_et"]), int((~keep).sum())

    raise ValueError(f"Unknown trade filter: {filter_name}")


def close_finished_positions(
    open_positions: list[dict],
    timestamp: pd.Timestamp,
    realized_by_day: dict[str, float],
    realized_by_month: dict[str, float],
) -> list[dict]:
    """Move positions that have exited into realized daily R."""

    still_open = []
    for position in open_positions:
        if position["exit_time"] <= timestamp:
            day = position["portfolio_session_date"]
            month = position["portfolio_month"]
            realized_by_day[day] = realized_by_day.get(day, 0.0) + float(position["r_result"])
            realized_by_month[month] = realized_by_month.get(month, 0.0) + float(position["r_result"])
        else:
            still_open.append(position)
    return still_open


def simulate_portfolio(
    trades: pd.DataFrame,
    max_open_positions: int,
    max_open_per_symbol: int,
    max_trades_per_day: int,
    max_daily_loss_r: float,
    max_monthly_loss_r: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Accept or skip playbook trades using portfolio-level risk rules."""

    trades = add_session_date(trades)
    trades = trades.sort_values(["entry_time", "symbol", "playbook_setup"]).reset_index(drop=True)

    accepted_rows = []
    skipped_rows = []
    open_positions: list[dict] = []
    realized_by_day: dict[str, float] = {}
    realized_by_month: dict[str, float] = {}
    accepted_count_by_day: dict[str, int] = {}

    for _, row in trades.iterrows():
        row_dict = row.to_dict()
        timestamp = row["entry_time"]
        session_date = row["portfolio_session_date"]
        portfolio_month = row["portfolio_month"]
        open_positions = close_finished_positions(open_positions, timestamp, realized_by_day, realized_by_month)

        realized_today = realized_by_day.get(session_date, 0.0)
        realized_this_month = realized_by_month.get(portfolio_month, 0.0)
        trades_today = accepted_count_by_day.get(session_date, 0)
        open_same_symbol = sum(1 for position in open_positions if position["symbol"] == row["symbol"])

        skip_reason = None
        if realized_today <= max_daily_loss_r:
            skip_reason = "daily_loss_limit"
        elif max_monthly_loss_r is not None and realized_this_month <= max_monthly_loss_r:
            skip_reason = "monthly_loss_limit"
        elif trades_today >= max_trades_per_day:
            skip_reason = "max_trades_per_day"
        elif len(open_positions) >= max_open_positions:
            skip_reason = "max_open_positions"
        elif open_same_symbol >= max_open_per_symbol:
            skip_reason = "max_open_per_symbol"

        if skip_reason:
            row_dict["portfolio_status"] = "skipped"
            row_dict["portfolio_skip_reason"] = skip_reason
            row_dict["open_positions_at_signal"] = len(open_positions)
            row_dict["realized_daily_r_at_signal"] = round(realized_today, 4)
            row_dict["realized_monthly_r_at_signal"] = round(realized_this_month, 4)
            skipped_rows.append(row_dict)
            continue

        row_dict["portfolio_status"] = "accepted"
        row_dict["portfolio_skip_reason"] = ""
        row_dict["open_positions_at_signal"] = len(open_positions)
        row_dict["realized_daily_r_at_signal"] = round(realized_today, 4)
        row_dict["realized_monthly_r_at_signal"] = round(realized_this_month, 4)
        accepted_rows.append(row_dict)
        open_positions.append(row_dict)
        accepted_count_by_day[session_date] = trades_today + 1

    # Close anything left after the final signal so daily summaries include all
    # accepted trade outcomes.
    for position in open_positions:
        day = position["portfolio_session_date"]
        month = position["portfolio_month"]
        realized_by_day[day] = realized_by_day.get(day, 0.0) + float(position["r_result"])
        realized_by_month[month] = realized_by_month.get(month, 0.0) + float(position["r_result"])

    accepted = pd.DataFrame(accepted_rows)
    skipped = pd.DataFrame(skipped_rows)
    daily_rows = []
    for day in sorted(set(list(realized_by_day) + list(accepted_count_by_day))):
        daily_rows.append(
            {
                "portfolio_session_date": day,
                "accepted_trades": accepted_count_by_day.get(day, 0),
                "realized_r": round(realized_by_day.get(day, 0.0), 4),
            }
        )
    daily = pd.DataFrame(daily_rows)
    return accepted, skipped, daily


def group_metrics(trades: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Return friendly metrics by group."""

    if trades.empty:
        return pd.DataFrame()
    metrics = calculate_metrics_by_group(trades, group_column)
    if metrics.empty:
        return metrics
    return metrics[[group_column, "trades", "win_rate", "expectancy_r", "profit_factor", "max_drawdown_r", "average_r"]]


def build_equity_curve(accepted: pd.DataFrame) -> pd.DataFrame:
    """Build a trade-by-trade equity curve in R units."""

    if accepted.empty:
        return pd.DataFrame()

    curve = accepted.copy()
    curve["entry_time"] = pd.to_datetime(curve["entry_time"], utc=True)
    curve["exit_time"] = pd.to_datetime(curve["exit_time"], utc=True)
    curve = curve.sort_values(["exit_time", "entry_time", "symbol", "playbook_setup"]).reset_index(drop=True)
    curve["trade_number"] = curve.index + 1
    curve["r_result"] = curve["r_result"].astype(float)
    curve["cumulative_r"] = curve["r_result"].cumsum().round(4)
    curve["running_peak_r"] = curve["cumulative_r"].cummax().round(4)
    curve["drawdown_r"] = (curve["cumulative_r"] - curve["running_peak_r"]).round(4)
    return curve[
        [
            "trade_number",
            "symbol",
            "playbook_setup",
            "playbook_direction",
            "entry_time",
            "exit_time",
            "r_result",
            "cumulative_r",
            "running_peak_r",
            "drawdown_r",
            "exit_reason",
        ]
    ]


def monthly_summary(accepted: pd.DataFrame) -> pd.DataFrame:
    """Summarize accepted trades by calendar month."""

    if accepted.empty:
        return pd.DataFrame()

    trades = accepted.copy()
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True)
    trades["month"] = trades["exit_time"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    rows = []
    for month, group in trades.groupby("month"):
        metrics = calculate_metrics(group)
        rows.append(
            {
                "month": month,
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "total_r": round(float(group["r_result"].astype(float).sum()), 4),
                "max_drawdown_r": metrics["max_drawdown_r"],
            }
        )
    return pd.DataFrame(rows).sort_values("month")


def drawdown_stretches(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Find drawdown stretches between equity-curve highs."""

    if equity_curve.empty:
        return pd.DataFrame()

    stretches = []
    in_drawdown = False
    start_row = None
    trough_row = None

    for _, row in equity_curve.iterrows():
        drawdown = float(row["drawdown_r"])
        if drawdown < 0 and not in_drawdown:
            in_drawdown = True
            start_row = row
            trough_row = row
        elif drawdown < 0 and in_drawdown:
            if drawdown < float(trough_row["drawdown_r"]):
                trough_row = row
        elif drawdown == 0 and in_drawdown:
            stretches.append(
                {
                    "start_trade": int(start_row["trade_number"]),
                    "start_time": str(start_row["exit_time"]),
                    "trough_trade": int(trough_row["trade_number"]),
                    "trough_time": str(trough_row["exit_time"]),
                    "recovery_trade": int(row["trade_number"]),
                    "recovery_time": str(row["exit_time"]),
                    "max_drawdown_r": round(float(trough_row["drawdown_r"]), 4),
                    "duration_trades": int(row["trade_number"] - start_row["trade_number"] + 1),
                }
            )
            in_drawdown = False
            start_row = None
            trough_row = None

    if in_drawdown and start_row is not None and trough_row is not None:
        last_row = equity_curve.iloc[-1]
        stretches.append(
            {
                "start_trade": int(start_row["trade_number"]),
                "start_time": str(start_row["exit_time"]),
                "trough_trade": int(trough_row["trade_number"]),
                "trough_time": str(trough_row["exit_time"]),
                "recovery_trade": "",
                "recovery_time": "not recovered",
                "max_drawdown_r": round(float(trough_row["drawdown_r"]), 4),
                "duration_trades": int(last_row["trade_number"] - start_row["trade_number"] + 1),
            }
        )

    if not stretches:
        return pd.DataFrame()
    return pd.DataFrame(stretches).sort_values("max_drawdown_r").reset_index(drop=True)


def skip_reason_summary(skipped: pd.DataFrame) -> pd.DataFrame:
    """Count skipped trades by reason."""

    if skipped.empty:
        return pd.DataFrame()
    return (
        skipped.groupby("portfolio_skip_reason")
        .size()
        .reset_index(name="skipped_trades")
        .sort_values("skipped_trades", ascending=False)
    )


def write_summary(
    path: Path,
    name: str,
    constraints: dict,
    accepted: pd.DataFrame,
    skipped: pd.DataFrame,
    daily: pd.DataFrame,
    equity_curve: pd.DataFrame,
    monthly: pd.DataFrame,
    drawdowns: pd.DataFrame,
) -> None:
    """Write the portfolio Markdown summary."""

    metrics = calculate_metrics(accepted)
    by_setup = group_metrics(accepted, "playbook_setup")
    by_symbol = group_metrics(accepted, "symbol")
    by_direction = group_metrics(accepted, "playbook_direction")
    skips = skip_reason_summary(skipped)
    worst_days = daily.sort_values("realized_r").head(10) if not daily.empty else pd.DataFrame()
    worst_months = monthly.sort_values("total_r").head(10) if not monthly.empty else pd.DataFrame()
    worst_drawdowns = drawdowns.head(10) if not drawdowns.empty else pd.DataFrame()
    final_r = 0.0 if equity_curve.empty else equity_curve.iloc[-1]["cumulative_r"]

    path.write_text(
        f"""# Portfolio {name.title()} Simulation

This report applies portfolio-level rules to the approved playbook trades.

Important: this is still research/backtesting only. It does not place orders,
create alerts, or connect to broker execution.

## Constraints

| Rule | Value |
| --- | ---: |
| Max open positions | {constraints["max_open_positions"]} |
| Max open positions per symbol | {constraints["max_open_per_symbol"]} |
| Max trades per day | {constraints["max_trades_per_day"]} |
| Max daily realized loss R | {constraints["max_daily_loss_r"]} |
| Max monthly realized loss R | {constraints["max_monthly_loss_r"]} |
| Trade filter | {constraints["trade_filter"]} |
| Raw trades blocked by filter | {constraints["blocked_trade_rows"]} |

## Overall Metrics

| Metric | Value |
| --- | ---: |
| Accepted trades | {metrics.get("trades", 0)} |
| Skipped trades | {len(skipped)} |
| Win rate | {metrics.get("win_rate", 0)} |
| Expectancy R | {metrics.get("expectancy_r", 0)} |
| Profit factor | {metrics.get("profit_factor", 0)} |
| Max drawdown R | {metrics.get("max_drawdown_r", 0)} |
| Final cumulative R | {final_r} |
| Average R | {metrics.get("average_r", 0)} |

## Metrics By Setup

{markdown_table(by_setup)}

## Metrics By Symbol

{markdown_table(by_symbol)}

## Metrics By Direction

{markdown_table(by_direction)}

## Skipped Trades

{markdown_table(skips)}

## Worst Days

{markdown_table(worst_days)}

## Worst Months

{markdown_table(worst_months)}

## Worst Drawdown Stretches

{markdown_table(worst_drawdowns)}

## Files

```text
logs/portfolio_{name}_accepted_trades.csv
logs/portfolio_{name}_skipped_trades.csv
logs/portfolio_{name}_daily_summary.csv
logs/portfolio_{name}_equity_curve.csv
logs/portfolio_{name}_monthly_summary.csv
logs/portfolio_{name}_drawdown_stretches.csv
logs/portfolio_{name}_summary.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = pd.read_csv(args.trades_csv)
    trades, blocked_trade_rows = apply_trade_filter(trades, args.trade_filter)
    accepted, skipped, daily = simulate_portfolio(
        trades,
        max_open_positions=args.max_open_positions,
        max_open_per_symbol=args.max_open_per_symbol,
        max_trades_per_day=args.max_trades_per_day,
        max_daily_loss_r=args.max_daily_loss_r,
        max_monthly_loss_r=args.max_monthly_loss_r,
    )

    accepted_path = args.output_dir / f"portfolio_{args.name}_accepted_trades.csv"
    skipped_path = args.output_dir / f"portfolio_{args.name}_skipped_trades.csv"
    daily_path = args.output_dir / f"portfolio_{args.name}_daily_summary.csv"
    equity_path = args.output_dir / f"portfolio_{args.name}_equity_curve.csv"
    monthly_path = args.output_dir / f"portfolio_{args.name}_monthly_summary.csv"
    drawdown_path = args.output_dir / f"portfolio_{args.name}_drawdown_stretches.csv"
    summary_path = args.output_dir / f"portfolio_{args.name}_summary.md"

    equity_curve = build_equity_curve(accepted)
    monthly = monthly_summary(accepted)
    drawdowns = drawdown_stretches(equity_curve)

    accepted.to_csv(accepted_path, index=False)
    skipped.to_csv(skipped_path, index=False)
    daily.to_csv(daily_path, index=False)
    equity_curve.to_csv(equity_path, index=False)
    monthly.to_csv(monthly_path, index=False)
    drawdowns.to_csv(drawdown_path, index=False)
    write_summary(
        summary_path,
        args.name,
        {
            "max_open_positions": args.max_open_positions,
            "max_open_per_symbol": args.max_open_per_symbol,
            "max_trades_per_day": args.max_trades_per_day,
            "max_daily_loss_r": args.max_daily_loss_r,
            "max_monthly_loss_r": args.max_monthly_loss_r,
            "trade_filter": args.trade_filter,
            "blocked_trade_rows": blocked_trade_rows,
        },
        accepted,
        skipped,
        daily,
        equity_curve,
        monthly,
        drawdowns,
    )

    metrics = calculate_metrics(accepted)
    print(f"Saved accepted trades: {accepted_path}")
    print(f"Saved skipped trades: {skipped_path}")
    print(f"Saved daily summary: {daily_path}")
    print(f"Saved equity curve: {equity_path}")
    print(f"Saved monthly summary: {monthly_path}")
    print(f"Saved drawdown stretches: {drawdown_path}")
    print(f"Saved portfolio summary: {summary_path}")
    print(
        f"Accepted trades={metrics['trades']} expectancy={metrics['expectancy_r']}R "
        f"skipped={len(skipped)} blocked_by_filter={blocked_trade_rows}"
    )


if __name__ == "__main__":
    main()
