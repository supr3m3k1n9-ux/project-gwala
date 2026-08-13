# Phase 3 Research Factory

Adopted 2026-08-12.

Phase 2 remains active at 29/30 completed official validation trades. Phase 3
and the Research Factory are prepared, not active.

Current protection:

- Official Validation: 29 / 30.
- Phase 2: ACTIVE.
- Phase 3: PREPARED - NOT ACTIVE.
- Research Factory: PREPARED - NOT ACTIVE.
- Automatic Strategy Switching: DISABLED.

This document does not authorize historical strategy mining, new strategy
activation, production strategy changes, signal changes, gate changes,
threshold changes, risk changes, regime routing changes, broker/live behavior,
paper evidence rule changes, validation eligibility changes, or research
allocation changes.

## Core Philosophy

Phase 3 must not merely optimize the small set of strategies Gwala already has.
It should become a continuous Strategy R&D system:

1. generate market hypotheses;
2. prioritize them;
3. test them;
4. challenge them;
5. refine promising ideas;
6. preserve version lineage;
7. validate survivors against increasingly independent evidence;
8. store validated playbooks in the Strategy Vault;
9. learn from failed and shelved strategies;
10. use production evidence to generate future hypotheses.

The intended flywheel:

`Research -> Strategy Vault -> Production -> Evidence -> Observation -> New Hypothesis -> Research`

## Hypothesis Sources

Prepared hypothesis sources:

- Existing strategy families: VWAP / EMA continuation, trend pullback, opening
  range breakout, opening range failure, gap fill / fade, failed breakout, mean
  reversion.
- Production observations: direction asymmetry, unusual MAE/MFE behavior,
  recurring entry failures, DTE implementation differences, regime-specific
  performance, recurring candidate behavior.
- Market structure ideas: momentum, breakouts, failed moves, volatility
  expansion or contraction, relative strength or weakness, opening behavior,
  closing behavior, gap behavior, VWAP behavior.
- Portfolio gaps: missing validated playbooks for important market conditions.
- Human research ideas: Roy or the research team may submit ideas, but every
  idea must enter the same governance process.
- Vault memory: prior failures and successes should affect whether a hypothesis
  deserves renewed research.

No hypothesis receives preferential validation because it was human-submitted or
because an early backtest looks exciting.

## Hypothesis Registry

The Hypothesis Registry should permanently track:

- hypothesis ID;
- human-readable name;
- strategy family;
- source;
- date proposed;
- rationale;
- hypothesized market behavior;
- intended instruments and directions;
- possible regime relationship;
- motivating evidence;
- parent strategy or version;
- research priority;
- current stage;
- decision and reason;
- linked experiments;
- linked strategy versions.

Hypotheses are never silently deleted.

## Research Queue

The Research Queue should prioritize work based on:

- strength of motivating evidence;
- portfolio need;
- novelty;
- expected information value;
- existing Strategy Vault knowledge;
- research cost;
- sample availability;
- Investment Committee allocation.

The queue must not prioritize merely because a backtest looks exciting.

Prepared queue groups:

- Now Researching.
- Up Next.
- Waiting for Evidence.
- On Hold.

During Phase 2 these groups may display placeholders only.

## Research Lifecycle

Standard lifecycle:

`HYPOTHESIS -> QUICK SCREEN -> DISCOVERY -> ROBUSTNESS -> REFINEMENT -> WALK-FORWARD -> HOLDOUT -> FORWARD PAPER -> VALIDATED EDGE -> STRATEGY VAULT`

Failure at any stage preserves the research record.

Quick Screen:

- Determines whether a hypothesis deserves meaningful research resources.
- It is not validation.
- Failure may become `ARCHIVED - INSUFFICIENT EVIDENCE`.

Discovery:

- Determines whether an economically interesting pattern appears to exist.
- Exploration is permitted.
- Discovery evidence is not independent validation evidence.
- The development dataset must be recorded.

Robustness:

- Attempts to break the result.
- Future checks may include neighboring parameters, different years, different
  regimes, symbol portability, direction, concentration, best-trade removal,
  drawdown, sensitivity, and sample sufficiency.
- A strategy that works only at one exact parameter value is fragile.

Refinement:

- Allowed only when evidence creates a defensible hypothesis.
- Parameter changes because profit factor improved are not enough.
- Every refinement creates a new version.

Walk-Forward:

- Earlier data is used for development.
- Later unseen periods are used for testing.
- Each window is preserved independently.

Holdout:

- Holdout data remains unavailable to development.
- Once locked, the holdout opens.
- A failed holdout requires a new research/version cycle.

Forward Paper:

- Rules locked.
- Hands off.
- Future markets create new evidence.
- Compare expected versus actual expectancy, profit factor, win rate, drawdown,
  MAE/MFE, execution, regime behavior, concentration, and drift.

## Strategy Vault Experience

The Strategy Vault should become a founder-usable playbook library. It should
organize strategies by families where supported by evidence, such as trend /
momentum, opening / breakout, mean reversion, failure / reversal, gap,
volatility, and other validated families.

Do not hard-code the taxonomy if an existing extensible family model is more
accurate.

Each future Vault card should eventually show:

- strategy name;
- family;
- version;
- lifecycle state;
- current eligibility;
- instruments;
- direction;
- validated environments;
- N;
- expectancy;
- profit factor;
- drawdown;
- forward evidence;
- auditor status;
- Investment Committee decision.

Strategy detail pages should eventually explain in plain English:

- what the strategy is;
- why it might work;
- what behavior it exploits;
- when it has worked;
- when it has failed;
- which symbols and markets apply;
- long, short, or both;
- entry and exit logic;
- biggest risks;
- what the evidence says;
- why it is in its current state;
- what would make it eligible;
- what would cause it to be shelved.

Use authoritative evidence. Do not fabricate explanations.

## Portfolio Gap Analysis

Future support should identify missing exposure. Example:

`RESEARCH GAP: Project Gwala has no validated playbook for low-volatility range-bound conditions.`

This is a research recommendation only. It must not automatically create or
activate a strategy.

## Future Inbox Event Types

Prepared event types:

- NEW HYPOTHESIS.
- RESEARCH PRIORITY CHANGE.
- STRATEGY VERSION CREATED.
- ROBUSTNESS PASS/FAIL.
- WALK-FORWARD PASS/FAIL.
- HOLDOUT PASS/FAIL.
- FORWARD CHECKPOINT.
- STRATEGY VALIDATED.
- STRATEGY SHELVED.
- STRATEGY ELIGIBLE.
- STRATEGY DRIFT WARNING.
- PORTFOLIO GAP IDENTIFIED.

Do not emit these events without real evidence.

## Activation Trigger

Research Factory activation requires all of:

1. 30 / 30 legitimate completed official paper trades;
2. Cohort 1 frozen according to approved evidence governance;
3. Phase 3 explicitly activated.

Until then:

`RESEARCH FACTORY: PREPARED - NOT ACTIVE`
