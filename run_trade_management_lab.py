"""Research trade-management overlays for the approved playbook.

This is research/backtesting only. It studies completed playbook trades and
their 5m candle paths to compare R-based management ideas such as fixed
targets, partial profits, and breakeven-after-1R. It does not place orders,
create alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics
from data.market_data import load_candles_from_csv
from run_playbook import markdown_table


MANAGEMENT_PROFILES = [
    "current",
    "full_target_1r",
    "full_target_1_5r",
    "full_target_2r",
    "partial_half_1r_rest_current",
    "partial_half_1r_rest_2r",
    "breakeven_after_1r",
    "breakeven_after_1_5r",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare paper trade-management profiles.")
    parser.add_argument(
        "--trades-csv",
        type=Path,
        default=Path("logs/playbook_approved_trades.csv"),
        help="Approved playbook trade log.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("logs"), help="Where Webull M5 CSV files are stored.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def trade_direction(row: pd.Series) -> str:
    """Return long or short from the playbook row."""

    direction = str(row.get("playbook_direction", "")).lower()
    if direction in {"long", "short"}:
        return direction
    setup = str(row.get("playbook_setup", "")).lower()
    return "short" if "short" in setup else "long"


def load_exit_candles(symbol: str, data_dir: Path, cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Load symbol M5 candles once."""

    symbol = symbol.upper()
    if symbol not in cache:
        cache[symbol] = load_candles_from_csv(data_dir / f"webull_{symbol}_M5_candles.csv", symbol)
    return cache[symbol]


def add_trade_path_stats(trades: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """Add MFE/MAE in R from the 5m path between entry and exit."""

    cache: dict[str, pd.DataFrame] = {}
    rows = []

    for _, row in trades.iterrows():
        result = row.to_dict()
        symbol = str(row["symbol"]).upper()
        direction = trade_direction(row)
        entry_time = pd.to_datetime(row["entry_time"], utc=True)
        exit_time = pd.to_datetime(row["exit_time"], utc=True)
        entry = float(row["entry"])
        stop = float(row["stop"])
        risk = abs(entry - stop)

        exit_candles = load_exit_candles(symbol, data_dir, cache)
        path = exit_candles[(exit_candles.index > entry_time) & (exit_candles.index <= exit_time)]

        if path.empty or risk <= 0:
            result["mfe_r"] = float(row["r_result"])
            result["mae_r"] = float(row["r_result"])
        elif direction == "short":
            result["mfe_r"] = round(float(((entry - path["low"]) / risk).max()), 4)
            result["mae_r"] = round(float(((entry - path["high"]) / risk).min()), 4)
        else:
            result["mfe_r"] = round(float(((path["high"] - entry) / risk).max()), 4)
            result["mae_r"] = round(float(((path["low"] - entry) / risk).min()), 4)

        rows.append(result)

    return pd.DataFrame(rows)


def managed_r(row: pd.Series, profile: str) -> float:
    """Estimate final R under a management overlay.

    The sequence is intentionally conservative:
    - If the path touched -1R, the trade is treated as stopped unless the
      profile's breakeven trigger was reached first. Without tick order inside
      the candle, this avoids overstating results.
    - Partial profiles only pay the partial if MFE reached the partial level.
    """

    current_r = float(row["r_result"])
    mfe = float(row["mfe_r"])
    mae = float(row["mae_r"])

    if profile == "current":
        return round(current_r, 4)

    if profile == "full_target_1r":
        if mae <= -1:
            return -1.0
        return 1.0 if mfe >= 1 else round(current_r, 4)

    if profile == "full_target_1_5r":
        if mae <= -1:
            return -1.0
        return 1.5 if mfe >= 1.5 else round(current_r, 4)

    if profile == "full_target_2r":
        if mae <= -1:
            return -1.0
        return 2.0 if mfe >= 2 else round(current_r, 4)

    if profile == "partial_half_1r_rest_current":
        if mae <= -1:
            return -1.0
        if mfe >= 1:
            return round((0.5 * 1.0) + (0.5 * current_r), 4)
        return round(current_r, 4)

    if profile == "partial_half_1r_rest_2r":
        if mae <= -1:
            return -1.0
        if mfe >= 2:
            return 1.5
        if mfe >= 1:
            runner = max(min(current_r, 2.0), -1.0)
            return round((0.5 * 1.0) + (0.5 * runner), 4)
        return round(current_r, 4)

    if profile == "breakeven_after_1r":
        if mfe >= 1 and current_r < 0:
            return 0.0
        return round(current_r, 4)

    if profile == "breakeven_after_1_5r":
        if mfe >= 1.5 and current_r < 0:
            return 0.0
        return round(current_r, 4)

    raise ValueError(f"Unknown management profile: {profile}")


def build_profile_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Expand trades across management profiles."""

    frames = []
    for profile in MANAGEMENT_PROFILES:
        managed = trades.copy()
        managed["management_profile"] = profile
        managed["original_r_result"] = managed["r_result"].astype(float)
        managed["r_result"] = managed.apply(lambda row: managed_r(row, profile), axis=1)
        frames.append(managed)
    return pd.concat(frames, ignore_index=True)


def summarize_by_profile(profile_trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize all management profiles."""

    rows = []
    for profile, group in profile_trades.groupby("management_profile"):
        metrics = calculate_metrics(group)
        rows.append(
            {
                "management_profile": profile,
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown_r": metrics["max_drawdown_r"],
                "average_r": metrics["average_r"],
            }
        )
    return pd.DataFrame(rows).sort_values(["expectancy_r", "max_drawdown_r"], ascending=[False, False])


def summarize_by_group(profile_trades: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Find best management profile by symbol or setup."""

    rows = []
    for (group_value, profile), group in profile_trades.groupby([group_column, "management_profile"]):
        metrics = calculate_metrics(group)
        rows.append(
            {
                group_column: group_value,
                "management_profile": profile,
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown_r": metrics["max_drawdown_r"],
            }
        )
    results = pd.DataFrame(rows)
    if results.empty:
        return results
    return results.sort_values([group_column, "expectancy_r", "max_drawdown_r"], ascending=[True, False, False])


def best_by_group(group_summary: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Return the top profile per group."""

    if group_summary.empty:
        return group_summary
    return group_summary.groupby(group_column, as_index=False).head(1).reset_index(drop=True)


def write_report(
    path: Path,
    overall: pd.DataFrame,
    best_symbol: pd.DataFrame,
    best_setup: pd.DataFrame,
    profile_trades: pd.DataFrame,
) -> None:
    """Write the Markdown management lab report."""

    current = overall[overall["management_profile"] == "current"]
    best = overall.head(1)
    current_expectancy = float(current.iloc[0]["expectancy_r"]) if not current.empty else 0.0
    best_expectancy = float(best.iloc[0]["expectancy_r"]) if not best.empty else 0.0
    best_profile = str(best.iloc[0]["management_profile"]) if not best.empty else "n/a"

    path.write_text(
        f"""# Trade Management Lab

This report compares R-based trade-management overlays on approved playbook
trades using each trade's 5m candle path.

Important: this is research/backtesting only. It does not place orders, create
alerts, or connect to broker execution.

## Plain-English Read

```text
Current playbook expectancy: {current_expectancy:.4f}R
Best tested management profile: {best_profile}
Best tested expectancy: {best_expectancy:.4f}R
```

These profiles are research overlays. They estimate how different take-profit
and stop-management rules would have behaved using 5m candle highs/lows.

## Overall Profile Comparison

{markdown_table(overall)}

## Best Profile By Symbol

{markdown_table(best_symbol)}

## Best Profile By Setup

{markdown_table(best_setup)}

## Profile Definitions

```text
current = keep the existing approved playbook result
full_target_1r = exit full position at 1R if reached
full_target_1_5r = exit full position at 1.5R if reached
full_target_2r = exit full position at 2R if reached
partial_half_1r_rest_current = take half at 1R, keep the rest on current result
partial_half_1r_rest_2r = take half at 1R, cap runner at 2R
breakeven_after_1r = if trade reached 1R but finished negative, mark it 0R
breakeven_after_1_5r = if trade reached 1.5R but finished negative, mark it 0R
```

## Conservative Assumption

```text
If a 5m path touched -1R, fixed-target and partial profiles count the stop
before the target. This avoids overstating edge when intrabar order is unknown.
```

## Files

```text
logs/trade_management_profile_trades.csv
logs/trade_management_overall.csv
logs/trade_management_by_symbol.csv
logs/trade_management_by_setup.csv
logs/trade_management_lab.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trades = pd.read_csv(args.trades_csv)
    trades_with_path = add_trade_path_stats(trades, args.data_dir)
    profile_trades = build_profile_trades(trades_with_path)
    overall = summarize_by_profile(profile_trades)
    by_symbol = summarize_by_group(profile_trades, "symbol")
    by_setup = summarize_by_group(profile_trades, "playbook_setup")
    best_symbol = best_by_group(by_symbol, "symbol")
    best_setup = best_by_group(by_setup, "playbook_setup")

    profile_trades.to_csv(args.output_dir / "trade_management_profile_trades.csv", index=False)
    overall.to_csv(args.output_dir / "trade_management_overall.csv", index=False)
    by_symbol.to_csv(args.output_dir / "trade_management_by_symbol.csv", index=False)
    by_setup.to_csv(args.output_dir / "trade_management_by_setup.csv", index=False)
    write_report(args.output_dir / "trade_management_lab.md", overall, best_symbol, best_setup, profile_trades)

    print(f"Saved trade management lab report: {args.output_dir / 'trade_management_lab.md'}")


if __name__ == "__main__":
    main()
