# Codex Project Instructions

This project is a beginner-readable Python research and backtesting framework
for a VWAP + EMA opening trend continuation trading strategy.

## Current Phase

Stay in research and backtesting mode.

Do not add live Webull execution, real-money trading, broker order placement,
or automated trade execution unless the user explicitly asks after backtesting
and paper-trading work is complete.

## Project Context

The strategy uses:

- 1H timeframe for higher-timeframe thesis.
- 30m timeframe for entry signals.
- 5m timeframe for exit management.
- VWAP for intraday control.
- 9 EMA for short-term momentum.
- 21 EMA for trend structure.
- 200 EMA for macro trend filtering.
- Opening range for early-session strength.
- Relative volume and quality scoring for stricter A-setup filtering.

The framework compares:

- Baseline VWAP + EMA continuation signals.
- Elite A-setup signals with stricter quality filters.

## Important Files

- `PROJECT_MEMORY.md`: compact context transfer between Codex windows.
- `HANDOFF.md`: human-readable project handoff and next-step guide.
- `main.py`: main backtest command.
- `config/settings.py`: strategy and risk settings.
- `data/market_data.py`: current market data loader.
- `indicators/`: VWAP, EMA, session, opening range, and timeframe helpers.
- `strategies/`: baseline and elite signal logic.
- `backtesting/`: trade simulation and performance metrics.
- `reports/summary.py`: plain-English report generator.
- `logs/`: generated backtest outputs.

## Development Style

- Keep code beginner-readable.
- Prefer clear comments that explain why a rule exists.
- Keep modules small and focused.
- Avoid unnecessary abstractions.
- Preserve the research-first workflow.
- Use R-multiple thinking for risk and performance.

## Safety Rules

Never add:

- Martingale logic.
- Averaging down losers.
- Revenge-trade behavior.
- Overleverage.
- Stop-loss removal.
- Real-money execution without explicit user approval and prior paper testing.

## Recommended Next Tasks

The next useful development tasks are:

1. Add CSV import support so the backtester does not depend only on Yahoo data.
2. Add a multi-symbol runner for SPY, QQQ, NVDA, TSLA, AMD, AAPL, META, MSFT.
3. Add a more reliable data provider later, such as Webull OpenAPI, Alpaca, or Polygon.
4. Add live alert mode only after backtests are usable.
5. Add paper trading only after live alerts behave correctly.

## Data Source Note

Yahoo Finance through `yfinance` has been unreliable in this project because
requests have failed with DNS errors for `guce.yahoo.com`.

Prefer adding local CSV import next.

## How To Verify Context

At the start of a new Codex session, ask:

```text
Read AGENTS.md, PROJECT_MEMORY.md, and HANDOFF.md. Summarize the current project status, safety rules, blockers, and the next safest coding task.
```

The correct answer should mention:

- Research/backtesting only.
- VWAP + EMA strategy.
- 1H thesis, 30m entries, 5m exits.
- Baseline vs elite A-setup comparison.
- Yahoo data blocker.
- CSV import as the next recommended task.
