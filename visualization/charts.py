"""Charting helpers for reviewing strategy behavior."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_trades(candles: pd.DataFrame, trades: pd.DataFrame, path: Path) -> None:
    """Create a simple price chart with indicators and trade markers."""

    path.parent.mkdir(parents=True, exist_ok=True)

    recent = candles.tail(250).copy()
    fig, ax = plt.subplots(figsize=(14, 7))

    ax.plot(recent.index, recent["close"], label="Close", linewidth=1.2)
    ax.plot(recent.index, recent["vwap"], label="VWAP", linewidth=1.0)
    ax.plot(recent.index, recent["ema_9"], label="9 EMA", linewidth=0.9)
    ax.plot(recent.index, recent["ema_21"], label="21 EMA", linewidth=0.9)
    ax.plot(recent.index, recent["ema_200"], label="200 EMA", linewidth=0.9)

    if not trades.empty:
        trades = trades.copy()
        trades["entry_time"] = pd.to_datetime(trades["entry_time"])
        trades["exit_time"] = pd.to_datetime(trades["exit_time"])
        visible = trades[trades["entry_time"].isin(recent.index)]

        ax.scatter(visible["entry_time"], visible["entry"], marker="^", color="green", label="Entry", zorder=3)
        ax.scatter(visible["exit_time"], visible["exit_price"], marker="v", color="red", label="Exit", zorder=3)

    ax.set_title("VWAP + EMA Trend Continuation Backtest")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
