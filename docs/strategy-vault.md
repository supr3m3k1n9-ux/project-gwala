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

## Phase 3 Strategy Lifecycle Constitution

Adopted 2026-08-12. Activated 2026-08-15 after Phase 2 reached 30 completed official observations and Cohort 1 was frozen under approved evidence governance.

- Phase 3 status is `ACTIVE`.
- Phase 3 research is activated for edge discovery only.
- No production strategy behavior, signals, gates, thresholds, risk rules,
  regime routing, broker/live behavior, paper evidence rules, or research
  allocation changes are authorized by this constitution. Broker/live behavior remains disabled. Broker/live behavior remains disabled.

Core principle:

Strategies must not be classified simply as good, bad, or deleted. A strategy
may have edge only under specific instruments, directions, market regimes,
volatility environments, times of day, and execution conditions. Gwala should
preserve validated playbooks and learn when each playbook is eligible.

Phase 3 research lifecycle:

`DISCOVERY -> RESEARCH -> ROBUSTNESS -> WALK-FORWARD -> HOLDOUT -> FORWARD PAPER
-> VALIDATED -> STRATEGY VAULT`

Operational lifecycle states for validated or studied strategies:

| State | Meaning |
| --- | --- |
| ACTIVE | A validated strategy currently permitted by the approved strategy/regime framework. |
| ELIGIBLE | Current market conditions match validated eligibility conditions, but active allocation is not guaranteed. |
| SHELVED - REGIME | Validated edge exists, but current market conditions do not match the demonstrated edge environment. |
| SHELVED - DRIFT | Historical validation exists, but recent forward evidence has materially diverged from expected behavior. |
| SHELVED - EXECUTION | Signal edge may remain valid, but current execution or contract implementation is not acceptable. |
| RESEARCH HOLD | Evidence is insufficient or weak enough that additional research allocation is temporarily paused. |
| ARCHIVED - FAILED VALIDATION | The hypothesis failed to demonstrate sufficient robust edge. Evidence and failure reasons remain permanent memory. |

Phase 3 must evaluate edge across supported dimensions:

`Strategy x Instrument x Direction x Regime x Time x Execution`

This prevents broad conclusions such as "Trend Pullback is bad" when the actual
evidence may say "SPY Long is weak, QQQ Long is watch, and NVDA Long is strong."
The robustness and auditor framework must prevent over-slicing data to
manufacture edge. Dimensional conclusions require sample sufficiency.

## Strategy Vault Permanent Record

The Strategy Vault should preserve:

- strategy family;
- strategy version;
- hypothesis;
- tested instruments and directions;
- validated regimes and execution conditions;
- historical, robustness, walk-forward, holdout, and forward evidence;
- execution studies and auditor history;
- Investment Committee history;
- current lifecycle state and reason;
- prior state changes;
- versions, lineage, and failure reasons;
- reactivation criteria.

Nothing is silently deleted. Failed strategies are archived with evidence,
versions, failure reasons, and research history so Gwala does not repeatedly
rediscover the same failed hypothesis without new evidence.

## Strategy Lineage Rule

Refinement must create explicit versions. Do not overwrite one version's
evidence with another version's results.

Example:

`ORB v1 -> baseline entry -> ORB v2 -> pullback entry -> ORB v3 -> revised exit`

Every version must preserve:

- what changed;
- why it changed;
- what evidence earned the change;
- what data was used for development;
- what data remained unseen;
- whether the new version improved out-of-sample results.

The farther a strategy progresses through Phase 3, the less freedom Gwala has
to modify it:

- Discovery: exploration allowed.
- Research/refinement: hypotheses may be developed.
- Walk-forward: freedom restricted.
- Holdout: rules locked.
- Forward Paper: hands off.
- Validated: changes require a new version and new evidence cycle.

Never optimize a validated strategy in place using evidence it later claims as
independent validation.

## Future Eligibility Auditors

Phase 3 may later support:

- Market Regime Auditor: determines current market conditions using validated
  objective inputs.
- Strategy Eligibility Auditor: compares current conditions with each
  strategy's validated eligibility conditions.

These auditors are governance concepts only until explicit future approval.
They must not activate, deactivate, or switch production strategies during Phase
2, and they must not automate strategy switching until Phase 3 has produced
validated regime relationships and the Investment Committee approves automation.

Future example output:

| Strategy | Previous State | New State | Why |
| --- | --- | --- | --- |
| QQQ Short Continuation | SHELVED | ELIGIBLE | Current conditions match validated bearish-trend / elevated-volatility regime. |
| VWAP Mean Reversion | ACTIVE | SHELVED - REGIME | Current market no longer resembles the validated mean-reversion environment. |

## Reactivation Rule

A shelved strategy may become eligible again when validated regime conditions
return, drift review clears, execution issues are repaired and independently
revalidated, or new evidence justifies renewed research. Reactivation must be
evidence-based, not calendar-based.

## Pivot Philosophy

Failure of one strategy does not justify randomly activating another.

- `CUT` or `REDUCE` means current evidence no longer earns additional
  allocation.
- `PIVOT` means another hypothesis has independently earned greater research
  allocation.

These are separate decisions.

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
