# Trading Philosophy

This document records Gwala's trading philosophy and reasoning. Preserve dated
entries and add to the history when the philosophy changes.

## Core Philosophy

Gwala is built around directional intraday chart edge first.

The system should identify when the underlying chart favors a directional trade,
then use options as the leverage vehicle only if the selected contract is
tradable, liquid, and aligned with expected hold time.

## V1 Philosophy

- Win by knowing when to trade and when to sit out.
- Prefer trend/momentum conditions for V1 paper-watch and launch work.
- Treat chop, mean reversion, volatility events, and options-flow ideas as
  research lanes until they earn promotion.
- Avoid trying to trade every market condition from day one.
- Do not confuse wider scope with faster progress; broader research is useful
  only when routing and gates keep it disciplined.

## Options Philosophy

Trading from the underlying chart is acceptable, but a chart signal alone is not
enough for an official options sample.

Contract quality matters because a correct chart read can still fail through:

- Bad delta.
- Wide bid/ask spread.
- Low volume.
- Low open interest.
- Wrong DTE for expected hold time.
- Excessively cheap/unstable premium.
- Event or earnings risk.

## Risk Philosophy

- Paper validation should measure disciplined execution, not forced activity.
- Reduced-risk samples may help reach evidence faster, but they must remain
  separated from live-readiness proof when appropriate.
- The system should explain why a candidate is blocked, not just hide it.
- Safety filters protect the account; quality filters shape expectancy;
  experimental filters are hypotheses. These should not be treated as the same
  kind of rule.

## Dated Entries

### 2026-06-16 - Grace Samples Are Timing Recovery, Not Rule Loosening

What changed:

- Added the principle that a one-candle B-tier grace sample can be valid only
  when it is a timing-recovery lane, not a lower-quality substitute for A-tier.

Why it changed:

- The current-candle requirement can be operationally too narrow for manual
  paper validation, especially when scanner output arrives after the signal
  candle has closed.
- Backtesting showed incremental B-tier windows improved throughput without
  worse average R or MAE in the current 90-day replay.

Assumptions:

- The source signal must come from the prior M30 candle.
- The reviewed candle must receive a new plan, new stop, new target, and new
  sizing.
- Manual chart review remains mandatory before any official validation sample.

Implementation impact:

- Implemented on 2026-06-16 as a manual B-tier Paper Gate path.
- B-tier can contribute official validation evidence only after refreshed
  sizing, manual review, Options Contract Gate pass, and explicit validation
  import.
- It does not justify automated stale entries, earlier-today official samples,
  live trading, or broker execution.

### 2026-06-15 - Chart First, Contract Quality Second

What changed:

- Reaffirmed that Gwala is not becoming a pure options-flow, volatility-arb, or
  market-making system for V1.
- Added explicit philosophy that options data should first be used for contract
  selection, risk control, and filtering.

Why it changed:

- The options-contract audit showed the chart/risk workflow was ahead of the
  actual contract-quality workflow.

Assumptions:

- Contract-quality validation can improve the credibility of paper samples
  without slowing V1 as much as a full option-chain integration would.
- Manual contract review is acceptable for V1 if it protects sample quality.

Implementation impact:

- Options Contract Gate v1 now sits before validation sample import.
- Future work can automate option-chain selection once a reliable provider path
  is chosen.

### 2026-06-15 - Paper Gate Filter Philosophy

What changed:

- Added the principle that paper validation should not over-stack experimental
  confirmation filters by default.
- Safety-critical filters remain strict, while trade-quality filters are
  threshold-based and should be reviewed through rejection counts.

Why it changed:

- The platform needs enough official paper trades to evaluate whether the edge
  works. Too many hidden quality filters can delay learning without actually
  improving safety.

Assumptions:

- More paper samples are useful only when sizing, data freshness, duplicate
  prevention, and manual review remain intact.
- Experimental overlays should prove themselves with forward evidence before
  they can become default blockers.

Implementation impact:

- `weakness_v1` is no longer the default paper scanner filter.
- Filter rejection counts should guide future threshold tuning.
