"""Regime diagnostics and risk-off filter tests.

This script looks for broad-market conditions that may explain weak portfolio
periods. It uses SPY 30m candles as the market regime proxy and only tests
filters based on the prior month, so the research avoids lookahead bias.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtesting.metrics import calculate_metrics
from data.market_data import load_candles_from_csv
from indicators.trend import add_core_indicators
from run_portfolio import simulate_portfolio, monthly_summary, markdown_table


OUTPUT_DIR = Path("logs")
PLAYBOOK_TRADES = OUTPUT_DIR / "playbook_approved_trades.csv"
SPY_M30 = OUTPUT_DIR / "webull_SPY_M30_candles.csv"


def load_spy_regime() -> pd.DataFrame:
    """Create monthly SPY regime stats from 30m candles."""

    spy = load_candles_from_csv(SPY_M30, symbol="SPY")
    spy = add_core_indicators(spy, fast_length=9, slow_length=21, regime_length=200)
    spy["month"] = spy.index.tz_convert("America/New_York").strftime("%Y-%m")
    spy["above_ema200"] = spy["close"] > spy["ema_200"]
    spy["bullish_stack"] = spy["ema_9"] > spy["ema_21"]
    spy["above_vwap"] = spy["close"] > spy["vwap"]

    rows = []
    for month, group in spy.groupby("month"):
        rows.append(
            {
                "month": month,
                "spy_bars": len(group),
                "spy_month_return_pct": round(((group["close"].iloc[-1] / group["open"].iloc[0]) - 1) * 100, 4),
                "spy_above_ema200_pct": round(float(group["above_ema200"].mean()), 4),
                "spy_bullish_stack_pct": round(float(group["bullish_stack"].mean()), 4),
                "spy_above_vwap_pct": round(float(group["above_vwap"].mean()), 4),
            }
        )

    regime = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    for column in [
        "spy_month_return_pct",
        "spy_above_ema200_pct",
        "spy_bullish_stack_pct",
        "spy_above_vwap_pct",
    ]:
        regime[f"prior_{column}"] = regime[column].shift(1)
    return regime


def add_trade_month(trades: pd.DataFrame) -> pd.DataFrame:
    """Add New York entry month to playbook trades."""

    result = trades.copy()
    result["entry_time"] = pd.to_datetime(result["entry_time"], utc=True)
    result["month"] = result["entry_time"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m")
    return result


def portfolio_monthly_with_regime(trades: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Join accepted-trade monthly performance with SPY regime stats."""

    portfolio_monthly = monthly_summary(trades)
    return portfolio_monthly.merge(regime, on="month", how="left")


def risk_off_masks(trades: pd.DataFrame) -> dict[str, pd.Series]:
    """Return candidate no-lookahead risk-off masks.

    True means the trade should be blocked.
    """

    prior_return = trades["prior_spy_month_return_pct"]
    prior_above_ema200 = trades["prior_spy_above_ema200_pct"]
    prior_stack = trades["prior_spy_bullish_stack_pct"]

    return {
        "prior_spy_down": prior_return < 0,
        "prior_spy_trend_weak": prior_above_ema200 < 0.50,
        "prior_spy_stack_weak": prior_stack < 0.50,
        "prior_spy_down_or_trend_weak": (prior_return < 0) | (prior_above_ema200 < 0.50),
        "prior_spy_down_and_trend_weak": (prior_return < 0) & (prior_above_ema200 < 0.50),
    }


def test_risk_off_filters(trades: pd.DataFrame) -> pd.DataFrame:
    """Simulate portfolio after blocking trades from each candidate filter."""

    rows = []
    masks = {"no_filter": pd.Series(False, index=trades.index)}
    masks.update(risk_off_masks(trades))

    for filter_name, block_mask in masks.items():
        filtered_trades = trades[~block_mask.fillna(False)].copy()
        accepted, skipped, _ = simulate_portfolio(
            filtered_trades,
            max_open_positions=3,
            max_open_per_symbol=1,
            max_trades_per_day=5,
            max_daily_loss_r=-3.0,
        )
        metrics = calculate_metrics(accepted)
        rows.append(
            {
                "filter": filter_name,
                "blocked_before_portfolio_rules": int(block_mask.fillna(False).sum()),
                "accepted_trades": metrics["trades"],
                "portfolio_skipped_trades": len(skipped),
                "win_rate": metrics["win_rate"],
                "expectancy_r": metrics["expectancy_r"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown_r": metrics["max_drawdown_r"],
                "total_r": round(float(accepted["r_result"].astype(float).sum()), 4) if not accepted.empty else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["expectancy_r", "profit_factor"], ascending=False)


def write_report(monthly: pd.DataFrame, filter_tests: pd.DataFrame) -> None:
    """Write the regime diagnostics Markdown report."""

    worst_months = monthly.sort_values("total_r").head(12)
    best_filters = filter_tests.head(10)

    report_path = OUTPUT_DIR / "regime_diagnostics_report.md"
    report_path.write_text(
        f"""# Regime Diagnostics Report

This report checks whether prior-month SPY conditions help explain weak
portfolio periods. Filters use only prior-month SPY stats to avoid lookahead.

## Worst Portfolio Months With SPY Regime

{markdown_table(worst_months)}

## Risk-Off Filter Tests

{markdown_table(best_filters)}

## Files

```text
logs/regime_monthly_diagnostics.csv
logs/regime_filter_tests.csv
logs/regime_diagnostics_report.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    regime = load_spy_regime()
    trades = add_trade_month(pd.read_csv(PLAYBOOK_TRADES))
    trades_with_regime = trades.merge(regime, on="month", how="left")

    monthly = portfolio_monthly_with_regime(trades, regime)
    filter_tests = test_risk_off_filters(trades_with_regime)

    monthly.to_csv(OUTPUT_DIR / "regime_monthly_diagnostics.csv", index=False)
    filter_tests.to_csv(OUTPUT_DIR / "regime_filter_tests.csv", index=False)
    write_report(monthly, filter_tests)

    print("Saved monthly diagnostics: logs/regime_monthly_diagnostics.csv")
    print("Saved filter tests: logs/regime_filter_tests.csv")
    print("Saved report: logs/regime_diagnostics_report.md")
    print(filter_tests.to_string(index=False))


if __name__ == "__main__":
    main()
