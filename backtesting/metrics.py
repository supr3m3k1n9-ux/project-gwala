"""Performance statistics for backtest results."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def calculate_metrics(trades: pd.DataFrame) -> dict:
    """Calculate core strategy metrics from a trade log."""

    if trades.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "sharpe_like": 0.0,
            "average_r": 0.0,
        }

    r = trades["r_result"].astype(float)
    wins = r[r > 0]
    losses = r[r < 0]
    equity_curve = r.cumsum()
    running_high = equity_curve.cummax()
    drawdown = equity_curve - running_high

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf

    # This is not a formal daily Sharpe ratio. It is a quick research metric
    # showing average R compared with the volatility of R outcomes.
    sharpe_like = r.mean() / r.std(ddof=0) if r.std(ddof=0) > 0 else 0.0

    return {
        "trades": int(len(trades)),
        "win_rate": round(float((r > 0).mean()), 4),
        "expectancy_r": round(float(r.mean()), 4),
        "profit_factor": round(float(profit_factor), 4) if np.isfinite(profit_factor) else "inf",
        "max_drawdown_r": round(float(drawdown.min()), 4),
        "sharpe_like": round(float(sharpe_like), 4),
        "average_r": round(float(r.mean()), 4),
    }


def calculate_metrics_by_group(trades: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Calculate metrics split by a trade-log column, such as quality grade."""

    if trades.empty or group_column not in trades.columns:
        return pd.DataFrame()

    rows = []
    for group_value, group_trades in trades.groupby(group_column):
        row = calculate_metrics(group_trades)
        row[group_column] = group_value
        rows.append(row)

    return pd.DataFrame(rows).sort_values(group_column)


def calculate_exit_reason_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize performance by exit reason."""

    if trades.empty or "exit_reason" not in trades.columns:
        return pd.DataFrame()

    rows = []
    for exit_reason, group_trades in trades.groupby("exit_reason"):
        metrics = calculate_metrics(group_trades)
        rows.append(
            {
                "exit_reason": exit_reason,
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "average_r": metrics["average_r"],
            }
        )

    return pd.DataFrame(rows).sort_values("trades", ascending=False)
