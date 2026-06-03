"""Create a paper-trade-style signal journal from approved playbook signals.

This is research/paper workflow only. It does not place orders, create live
alerts, or connect to broker execution. The journal turns backtested signals
into the same fields a trader would record before paper trading.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_playbook import markdown_table
from run_portfolio import TRADE_FILTER_PRESETS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a paper-trade-style signal journal.")
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/playbook_approved_trades.csv"),
        help="Approved playbook signal/trade log.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where journal files are saved.")
    parser.add_argument(
        "--trade-filter",
        choices=sorted(TRADE_FILTER_PRESETS),
        default="weakness_v1",
        help="Research filter used to label allowed versus blocked signals.",
    )
    parser.add_argument("--latest", type=int, default=25, help="How many latest signals to show in the Markdown report.")
    return parser.parse_args()


def weakness_v1_block_reason(row: pd.Series) -> str:
    """Return the reason a signal is blocked by weakness_v1, or blank if allowed."""

    symbol = row["symbol"]
    setup = row["playbook_setup"]
    entry_hour = int(row["entry_hour_et"])
    relative_volume = float(row["relative_volume"])
    room_to_target = float(row["room_to_resistance_r"])

    if symbol == "NVDA" and setup == "Setup B Short":
        if entry_hour == 11:
            return "blocked_nvda_short_11am_et"
        if 0.75 <= relative_volume < 1.0:
            return "blocked_nvda_short_relvol_0_75_to_1_0"
        if 1.25 <= relative_volume < 1.5:
            return "blocked_nvda_short_relvol_1_25_to_1_5"

    if symbol == "SPY" and setup == "Setup A Long" and 0.75 <= room_to_target < 1.0:
        return "blocked_spy_long_room_0_75_to_1_0"

    return ""


def add_journal_columns(trades: pd.DataFrame, trade_filter: str) -> pd.DataFrame:
    """Add paper-journal fields and filter labels."""

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["exit_time"] = pd.to_datetime(result["exit_time"], utc=True)
    result["entry_time_et"] = result["entry_time"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d %H:%M")
    result["entry_hour_et"] = result["entry_time"].dt.tz_convert("America/New_York").dt.hour
    result["planned_risk_per_share"] = (result["entry"].astype(float) - result["stop"].astype(float)).abs().round(4)

    if trade_filter == "weakness_v1":
        result["block_reason"] = result.apply(weakness_v1_block_reason, axis=1)
    else:
        result["block_reason"] = ""

    result["signal_status"] = result["block_reason"].apply(lambda reason: "blocked" if reason else "allowed")
    result["paper_action"] = result["signal_status"].apply(
        lambda status: "paper_watch_only" if status == "blocked" else "paper_trade_candidate"
    )
    return result


def journal_view(journal: pd.DataFrame) -> pd.DataFrame:
    """Keep the fields useful for a paper-trade journal."""

    columns = [
        "entry_time_et",
        "symbol",
        "playbook_setup",
        "playbook_direction",
        "paper_action",
        "signal_status",
        "block_reason",
        "entry",
        "stop",
        "target",
        "planned_risk_per_share",
        "playbook_exit_profile",
        "quality_score",
        "relative_volume",
        "room_to_resistance_r",
        "r_result",
        "exit_reason",
    ]
    return journal[columns].sort_values("entry_time_et")


def summary_by_status(journal: pd.DataFrame) -> pd.DataFrame:
    """Summarize allowed versus blocked signals."""

    rows = []
    for status, group in journal.groupby("signal_status"):
        rows.append(
            {
                "signal_status": status,
                "signals": len(group),
                "symbols": ", ".join(sorted(group["symbol"].unique())),
                "avg_historical_r": round(float(group["r_result"].astype(float).mean()), 4),
                "total_historical_r": round(float(group["r_result"].astype(float).sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("signal_status")


def summary_by_block_reason(journal: pd.DataFrame) -> pd.DataFrame:
    """Summarize blocked signals by reason."""

    blocked = journal[journal["signal_status"] == "blocked"]
    if blocked.empty:
        return pd.DataFrame()

    rows = []
    for reason, group in blocked.groupby("block_reason"):
        rows.append(
            {
                "block_reason": reason,
                "signals": len(group),
                "avg_historical_r": round(float(group["r_result"].astype(float).mean()), 4),
                "total_historical_r": round(float(group["r_result"].astype(float).sum()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("total_historical_r")


def write_report(path: Path, journal: pd.DataFrame, latest: int, trade_filter: str) -> None:
    """Write the Markdown journal report."""

    latest_signals = journal_view(journal).tail(latest)
    status_summary = summary_by_status(journal)
    block_summary = summary_by_block_reason(journal)

    path.write_text(
        f"""# Paper Signal Journal

This report turns approved playbook signals into a paper-trade-style journal.

Important: this is research/paper workflow only. It does not place orders,
create alerts, or connect to broker execution.

## Settings

```text
Trade filter: {trade_filter}
Latest signals shown: {latest}
```

## Signal Status Summary

{markdown_table(status_summary)}

## Blocked Signal Summary

{markdown_table(block_summary)}

## Latest Signals

{markdown_table(latest_signals)}

## Files

```text
logs/paper_signal_journal.csv
logs/paper_signal_journal.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = pd.read_csv(args.trades_csv)
    journal = add_journal_columns(trades, args.trade_filter)
    view = journal_view(journal)

    csv_path = args.output_dir / "paper_signal_journal.csv"
    report_path = args.output_dir / "paper_signal_journal.md"
    view.to_csv(csv_path, index=False)
    write_report(report_path, journal, args.latest, args.trade_filter)

    print(f"Saved paper signal journal CSV: {csv_path}")
    print(f"Saved paper signal journal report: {report_path}")


if __name__ == "__main__":
    main()
