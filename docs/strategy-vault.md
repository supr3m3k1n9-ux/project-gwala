# Strategy Vault

Legacy note, added 2026-08-07:

The authoritative current strategy portfolio state is now the root-level
`STRATEGY_STATE.md`. This `docs/strategy-vault.md` file is retained as
historical context and dated project history. If it conflicts with the
root-level company-memory files, use the root-level files.

This document records Strategy Vault architecture, strategy lanes, roadmap, and
research backlog decisions. Preserve dated entries.

## Strategy Vault Principle

The vault keeps Gwala's strategic net broad while preventing unproven strategies
from becoming paper-ready too early.

The router can study multiple strategy families, but V1 launch discipline should
keep official paper-watch focused on strategies that have earned evidence.

## Current Strategy Families

- VWAP + EMA Trend Continuation.
- VWAP Mean Reversion.
- Gap Fill / Gap Fade.
- VWAP Reclaim / Reject.
- Opening Range Breakout.
- Trend Pullback Continuation.
- Opening Range Failure.

## V1 Launch Lane

Primary V1 lane:

- VWAP + EMA trend/momentum continuation.

Supporting V1 infrastructure:

- Market regime detection.
- Market regime router.
- Paper activation rules.
- Paper Gate v2.
- Options Contract Gate v1.
- Manual paper-validation ledger.
- Data-flow and dashboard preflight checks.

## Research Lanes

Research strategies can be backtested, shadow-sampled, forward-observed, and
routed for study. They should not count as paper-watch/live-readiness evidence
until activation gates explicitly approve them.

## Contract Selection Roadmap

V1:

- Manual Options Contract Gate using entered contract details.

Later:

- Automated option-chain fetching.
- Contract ranking by delta, spread, liquidity, DTE, expected move, and event
  risk.
- Options-flow confirmation only after V1 is stable.

## Dated Entries

### 2026-06-16 - Grace Lane Is Validation Workflow, Not Strategy Expansion

What changed:

- The one-M30-candle B-tier grace lane is classified as paper-validation
  workflow, not a new Strategy Vault strategy.

Why it changed:

- The user is trying to reach the paper gate faster without adding new
  strategies, indicators, providers, options-flow filters, or gamma models.

Assumptions:

- Strategy families remain unchanged.
- The grace lane can only rescue timing on an existing signal and must use a
  fresh plan, fresh sizing, fresh stop/target, and manual review.

Implementation impact:

- Strategy Vault scope is unchanged.
- Implemented on 2026-06-16 in Paper Gate / pre-entry workflow, not in strategy
  signal generation.
- The lane increases validation throughput without adding strategies,
  indicators, providers, options-flow filters, or gamma models.

### 2026-06-15 - Options Contract Gate Added To V1 Path

What changed:

- Strategy Vault launch path now includes Options Contract Gate v1 between chart
  candidate approval and official validation sample import.

Why it changed:

- Strategy expansion alone does not guarantee faster path to market. Good
  signals need clean execution vehicles to produce credible paper evidence.

Assumptions:

- The fastest credible path is not "trade every setup"; it is "route broadly,
  validate selectively, and avoid bad contracts."
- Contract-quality checks should be attached to paper validation now, while full
  chain automation can remain a later milestone.

Implementation impact:

- Official options validation samples require both a Paper Gate v2 pass and an
  Options Contract Gate pass.
- Missing or failed contract review blocks import into the validation sample
  ledger.

### 2026-06-15 - Living Strategy Documentation Adopted

What changed:

- Strategy roadmap decisions should be recorded here instead of creating new
  standalone handoff files by default.

Why it changed:

- The Strategy Vault has multiple moving parts. A central strategy document
  helps keep router logic, research backlog, and paper-validation rules aligned.

Assumptions:

- Future strategy additions are safer when they update this roadmap before
  implementation.

Implementation impact:

- Future strategy logic changes should update this document when they alter the
  roadmap or research backlog.
