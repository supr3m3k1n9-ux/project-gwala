# Codex Project Instructions

This project is a beginner-readable Python research and backtesting framework
for a VWAP + EMA opening trend continuation trading strategy.

## Current Phase

Stay in paper-collection mode for the next 10 market sessions.

The primary KPI is:

- Completed Official Paper Trades

Allowed work during this mode:

- Candidate capture.
- Candidate review.
- Contract review.
- Paper trade logging.
- Exit management.
- Safety-critical bug fixes.

Disallowed work during this mode:

- New strategies.
- New indicators.
- New dashboard features.
- New research systems.
- New routing logic.
- New filters.
- New data providers.
- New architecture projects.

Exception:

- Only make a disallowed-category change if it directly increases completed
  official paper trades or fixes a blocker preventing official paper trades.

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

1. Run candidate capture during each market session.
2. Review A/B paper candidates.
3. Complete contract review for valid candidates.
4. Log official paper trades that pass the current workflow.
5. Manage exits and record completed official paper-trade outcomes.

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
