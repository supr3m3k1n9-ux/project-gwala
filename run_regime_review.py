"""Review candidate performance by market regime.

This report labels each historical trade with the broad-market backdrop at the
entry candle, then scores whether the setup worked better in bullish, bearish,
or choppy conditions. It is research-only and does not alter the scanner,
paper log, alerts, broker settings, or live execution.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from backtesting.metrics import calculate_metrics
from config.settings import STRATEGY
from data.market_data import load_candles_from_csv
from indicators.trend import add_core_indicators
from run_playbook import markdown_table
from run_promotion_review import read_csv_or_empty
from run_walk_forward_review import add_entry_time, finite_profit_factor, trade_log_path


REVIEW_STATUSES = {"research_ready", "promising"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market regime review.")
    parser.add_argument(
        "--research-dir",
        type=Path,
        default=Path("logs/deeper_research"),
        help="Folder containing research_confidence.csv, trade logs, and market candles.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--market-symbol", default="SPY", help="Market symbol used for regime labels.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum confidence rows to inspect.")
    return parser.parse_args()


def true_range_percent(candles: pd.DataFrame) -> pd.Series:
    """Return true range as a percentage of close."""

    previous_close = candles["close"].shift(1)
    true_range = pd.concat(
        [
            candles["high"] - candles["low"],
            (candles["high"] - previous_close).abs(),
            (candles["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range / candles["close"].replace(0, pd.NA)


def label_market_regime(candles: pd.DataFrame) -> pd.DataFrame:
    """Add broad trend and volatility regime labels to market candles."""

    market = add_core_indicators(
        candles,
        fast_length=STRATEGY.fast_ema_length,
        slow_length=STRATEGY.slow_ema_length,
        regime_length=STRATEGY.regime_ema_length,
    )
    fast = f"ema_{STRATEGY.fast_ema_length}"
    slow = f"ema_{STRATEGY.slow_ema_length}"

    bullish = (market["close"] > market["vwap"]) & (market["close"] > market[slow]) & (market[fast] > market[slow])
    bearish = (market["close"] < market["vwap"]) & (market["close"] < market[slow]) & (market[fast] < market[slow])
    market["market_regime"] = "choppy"
    market.loc[bullish, "market_regime"] = "bullish"
    market.loc[bearish, "market_regime"] = "bearish"

    market["true_range_pct"] = true_range_percent(market).fillna(0.0)
    rolling_median = market["true_range_pct"].rolling(50, min_periods=10).median()
    market["volatility_regime"] = "normal_volatility"
    market.loc[market["true_range_pct"] > (rolling_median * 1.35), "volatility_regime"] = "high_volatility"
    market.loc[market["true_range_pct"] < (rolling_median * 0.70), "volatility_regime"] = "low_volatility"
    return market[["market_regime", "volatility_regime", "true_range_pct"]].sort_index()


def load_market_regimes(research_dir: Path, market_symbol: str) -> pd.DataFrame:
    """Load and label market candles from the research folder."""

    path = research_dir / f"webull_{market_symbol.upper()}_M30_candles.csv"
    candles = load_candles_from_csv(path, market_symbol.upper())
    regimes = label_market_regime(candles)
    regimes.index = pd.to_datetime(regimes.index, utc=True)
    return regimes


def attach_regimes(trades: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """Attach nearest prior market regime labels to each trade entry."""

    if trades.empty:
        return trades
    ordered_trades = trades.sort_values("entry_time").copy()
    regime_rows = regimes.sort_index().reset_index().rename(columns={"datetime": "regime_time"})
    if "index" in regime_rows.columns:
        regime_rows = regime_rows.rename(columns={"index": "regime_time"})
    regime_rows["regime_time"] = pd.to_datetime(regime_rows["regime_time"], utc=True)
    return pd.merge_asof(
        ordered_trades,
        regime_rows,
        left_on="entry_time",
        right_on="regime_time",
        direction="backward",
    )


def regime_decision(trades: int, expectancy: float, profit_factor: float) -> tuple[str, str]:
    """Label one candidate/regime result."""

    if trades < 5:
        return "too_few_trades", "Fewer than 5 trades in this regime."
    if trades < 8:
        return "needs_more_sample", "Some evidence, but fewer than 8 trades."
    if expectancy >= 0.10 and profit_factor >= 1.30:
        return "favorable", "Regime stayed above the research-ready math floor."
    if expectancy <= 0:
        return "avoid", "Regime was flat or negative."
    return "mixed", "Regime was positive but below the stronger confidence floor."


def score_group(
    symbol: str,
    setup: str,
    candidate: str,
    regime_type: str,
    regime: str,
    trades: pd.DataFrame,
) -> dict[str, Any]:
    """Score one candidate in one regime bucket."""

    metrics = calculate_metrics(trades)
    expectancy = float(metrics["expectancy_r"])
    profit_factor = finite_profit_factor(metrics["profit_factor"])
    decision, reason = regime_decision(int(metrics["trades"]), expectancy, profit_factor)
    return {
        "decision": decision,
        "symbol": symbol,
        "setup": setup,
        "candidate": candidate,
        "regime_type": regime_type,
        "regime": regime,
        "trades": int(metrics["trades"]),
        "win_rate": float(metrics["win_rate"]),
        "expectancy_r": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_r": float(metrics["max_drawdown_r"]),
        "reason": reason,
    }


def review_candidate(row: pd.Series, regimes: pd.DataFrame) -> list[dict[str, Any]]:
    """Return regime score rows for one research candidate."""

    candidate = str(row.get("candidate", ""))
    path = trade_log_path(str(row.get("summary_report", "")), candidate)
    trades = add_entry_time(read_csv_or_empty(path))
    trades = attach_regimes(trades, regimes)
    if trades.empty:
        return []

    rows = []
    for regime_type in ["market_regime", "volatility_regime"]:
        for regime, group in trades.dropna(subset=[regime_type]).groupby(regime_type, sort=True):
            rows.append(
                score_group(
                    str(row.get("symbol", "")),
                    str(row.get("setup", "")),
                    candidate,
                    regime_type,
                    str(regime),
                    group,
                )
            )
    return rows


def build_regime_review(research_dir: Path, market_symbol: str, limit: int) -> pd.DataFrame:
    """Build the full regime review table."""

    confidence = read_csv_or_empty(research_dir / "research_confidence.csv")
    if confidence.empty:
        return pd.DataFrame()

    regimes = load_market_regimes(research_dir, market_symbol)
    candidates = confidence[confidence["research_status"].isin(REVIEW_STATUSES)].head(limit)
    rows = []
    for _, row in candidates.iterrows():
        rows.extend(review_candidate(row, regimes))
    if not rows:
        return pd.DataFrame()

    order = {
        "favorable": 0,
        "mixed": 1,
        "needs_more_sample": 2,
        "too_few_trades": 3,
        "avoid": 4,
    }
    result = pd.DataFrame(rows)
    result["_order"] = result["decision"].map(order).fillna(9)
    result = result.sort_values(
        ["_order", "expectancy_r", "trades"],
        ascending=[True, False, False],
    )
    return result.drop(columns=["_order"]).reset_index(drop=True)


def candidate_summary(review: pd.DataFrame) -> pd.DataFrame:
    """Summarize best and weakest market regimes per candidate."""

    if review.empty:
        return pd.DataFrame()
    market_rows = review[review["regime_type"] == "market_regime"].copy()
    rows = []
    for (symbol, setup, candidate), group in market_rows.groupby(["symbol", "setup", "candidate"], sort=True):
        summary_group = group[group["trades"] >= 5].copy()
        if summary_group.empty:
            summary_group = group.copy()
        best = summary_group.sort_values(["expectancy_r", "trades"], ascending=[False, False]).iloc[0]
        weakest = summary_group.sort_values(["expectancy_r", "trades"], ascending=[True, False]).iloc[0]
        rows.append(
            {
                "symbol": symbol,
                "setup": setup,
                "candidate": candidate,
                "best_market_regime": best["regime"],
                "best_expectancy_r": best["expectancy_r"],
                "best_trades": best["trades"],
                "weakest_market_regime": weakest["regime"],
                "weakest_expectancy_r": weakest["expectancy_r"],
                "weakest_trades": weakest["trades"],
            }
        )
    return pd.DataFrame(rows).sort_values(["best_expectancy_r", "best_trades"], ascending=[False, False])


def write_report(path: Path, review: pd.DataFrame, research_dir: Path, market_symbol: str) -> None:
    """Write the market regime Markdown report."""

    if review.empty:
        body = "No regime rows were available."
    else:
        counts = review.groupby(["regime_type", "decision"]).size().reset_index(name="rows")
        summary = candidate_summary(review)
        body = f"""## Decision Counts

{markdown_table(counts)}

## Candidate Regime Summary

{markdown_table(summary)}

## Regime Detail

{markdown_table(review)}
"""

    path.write_text(
        f"""# Regime Review

This report scores candidate trade logs by the broad-market backdrop at entry.
The market backdrop currently uses `{market_symbol.upper()}` 30-minute candles.

Important: this is research/backtesting only. It does not change the scanner,
paper log, alerts, broker settings, or live execution.

```text
Research folder: {research_dir}
Market symbol: {market_symbol.upper()}
```

{body}
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    review = build_regime_review(args.research_dir, args.market_symbol.upper(), args.limit)
    csv_path = args.output_dir / "regime_review.csv"
    md_path = args.output_dir / "regime_review.md"
    review.to_csv(csv_path, index=False)
    write_report(md_path, review, args.research_dir, args.market_symbol.upper())
    print(f"Saved regime CSV: {csv_path}")
    print(f"Saved regime report: {md_path}")


if __name__ == "__main__":
    main()
