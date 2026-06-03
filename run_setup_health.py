"""Score approved setup health from the playbook backtest log.

This is research/paper workflow only. It reads historical simulated trades and
summarizes whether each approved setup still looks healthy enough to keep
forward paper-tracking. It does not fetch data, place orders, create alerts, or
connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics
from run_playbook import markdown_table


MIN_RELIABLE_TRADES = 30
MIN_WATCH_TRADES = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build setup health scores from approved playbook trades.")
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/playbook_approved_trades.csv"),
        help="Combined approved playbook trade log.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def profit_factor_number(value) -> float:
    """Convert profit factor values to numbers for scoring."""

    if value == "inf":
        return 999.0
    return float(value)


def recent_metrics(trades: pd.DataFrame) -> dict:
    """Score the newest trades for one setup.

    For small samples, use the newest half. For bigger samples, use the newest
    10 trades. This keeps the recent read useful without pretending it is a
    statistically complete sample.
    """

    ordered = trades.sort_values("entry_time").copy()
    if len(ordered) < 4:
        recent = ordered
    else:
        recent_count = min(10, max(3, len(ordered) // 2))
        recent = ordered.tail(recent_count)

    metrics = calculate_metrics(recent)
    return {
        "recent_trades": metrics["trades"],
        "recent_expectancy_r": metrics["expectancy_r"],
        "recent_profit_factor": metrics["profit_factor"],
        "recent_win_rate": metrics["win_rate"],
    }


def health_points(metrics: dict) -> tuple[int, list[str]]:
    """Return a simple 0-100 health score and plain-English flags."""

    points = 0
    flags: list[str] = []

    trades = int(metrics["trades"])
    expectancy = float(metrics["expectancy_r"])
    profit_factor = profit_factor_number(metrics["profit_factor"])
    drawdown = float(metrics["max_drawdown_r"])
    recent_expectancy = float(metrics["recent_expectancy_r"])
    recent_profit_factor = profit_factor_number(metrics["recent_profit_factor"])

    if trades >= MIN_RELIABLE_TRADES:
        points += 25
    elif trades >= MIN_WATCH_TRADES:
        points += 15
        flags.append("sample still developing")
    else:
        points += 5
        flags.append("very small sample")

    if expectancy >= 0.15:
        points += 25
    elif expectancy > 0:
        points += 15
    else:
        flags.append("negative or flat expectancy")

    if profit_factor >= 1.5:
        points += 20
    elif profit_factor > 1:
        points += 12
    else:
        flags.append("profit factor below 1")

    if drawdown >= -3:
        points += 15
    elif drawdown >= -6:
        points += 8
        flags.append("moderate drawdown")
    else:
        flags.append("large drawdown")

    if recent_expectancy > 0 and recent_profit_factor > 1:
        points += 15
    else:
        flags.append("recent trades are weak")

    return min(points, 100), flags


def health_status(score: int, trades: int, expectancy: float, profit_factor: float) -> str:
    """Translate score into an operating label."""

    if trades < MIN_WATCH_TRADES:
        return "watch_more"
    if expectancy <= 0 or profit_factor <= 1:
        return "caution"
    if trades < MIN_RELIABLE_TRADES:
        return "watch"
    if score >= 80:
        return "healthy"
    if score >= 60:
        return "watch"
    return "caution"


def build_health(trades: pd.DataFrame) -> pd.DataFrame:
    """Build one health row per approved symbol/setup/variant/exit profile."""

    if trades.empty:
        return pd.DataFrame()

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)

    group_columns = [
        "symbol",
        "playbook_setup",
        "playbook_direction",
        "playbook_variant",
        "playbook_exit_profile",
    ]

    rows = []
    for group_values, group in result.groupby(group_columns, sort=True):
        metrics = calculate_metrics(group)
        recent = recent_metrics(group)
        combined = {**metrics, **recent}
        score, flags = health_points(combined)
        pf = profit_factor_number(metrics["profit_factor"])

        rows.append(
            {
                "symbol": group_values[0],
                "setup": group_values[1],
                "direction": group_values[2],
                "variant": group_values[3],
                "exit_profile": group_values[4],
                "health_status": health_status(score, int(metrics["trades"]), float(metrics["expectancy_r"]), pf),
                "health_score": score,
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown_r": metrics["max_drawdown_r"],
                "recent_trades": recent["recent_trades"],
                "recent_expectancy_r": recent["recent_expectancy_r"],
                "recent_profit_factor": recent["recent_profit_factor"],
                "flags": "; ".join(flags) if flags else "none",
            }
        )

    health = pd.DataFrame(rows)
    status_order = {"healthy": 0, "watch": 1, "watch_more": 2, "caution": 3}
    health["status_order"] = health["health_status"].map(status_order)
    health = health.sort_values(["status_order", "health_score", "expectancy_r"], ascending=[True, False, False])
    return health.drop(columns=["status_order"])


def write_report(path: Path, health: pd.DataFrame) -> None:
    """Write the setup health Markdown report."""

    if health.empty:
        status_counts = pd.DataFrame()
        cautions = pd.DataFrame()
    else:
        status_counts = health.groupby("health_status").size().reset_index(name="setups").sort_values("health_status")
        cautions = health[health["health_status"].isin(["watch_more", "caution"])].copy()

    path.write_text(
        f"""# Setup Health Report

This report scores each approved playbook setup using historical backtest
trades.

Important: this is research/paper workflow only. A healthy score means "keep
forward paper-tracking," not "trade with real money."

## Score Meaning

```text
healthy = strong enough to keep paper-tracking
watch = positive but needs monitoring
watch_more = promising but under-sampled
caution = weak math or recent weakness
```

## Status Counts

{markdown_table(status_counts)}

## Setup Health

{markdown_table(health)}

## Watch And Caution List

{markdown_table(cautions)}

## Files

```text
logs/setup_health.csv
logs/setup_health.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = pd.read_csv(args.trades_csv) if args.trades_csv.exists() else pd.DataFrame()
    health = build_health(trades)

    csv_path = args.output_dir / "setup_health.csv"
    report_path = args.output_dir / "setup_health.md"
    health.to_csv(csv_path, index=False)
    write_report(report_path, health)

    print(f"Saved setup health CSV: {csv_path}")
    print(f"Saved setup health report: {report_path}")


if __name__ == "__main__":
    main()
