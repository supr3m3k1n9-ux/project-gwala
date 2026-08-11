# Project Gwala Handoff

Last refreshed: 2026-08-07

This handoff is a concise session-start guide generated from the authoritative
company-memory files. It is not the source of truth.

Authoritative files:

- `PROJECT_STATE.md`
- `DECISION_LOG.md`
- `ROADMAP.md`
- `OPERATING_DOCTRINE.md`
- `STRATEGY_STATE.md`

## Mission

Build a quantitative trading firm that reaches sustainable profitability as
quickly as reasonably possible.

## Current Phase

Phase 2: discover the firm's first commercially viable trading edge.

Default operating mode:

```text
EXECUTE
```

## Current Company State

- Commercial stage: Pre-Revenue.
- Active business: Equities Division, US equities/options.
- Live capital: not deployed.
- Broker/live execution: disabled.
- Primary objective: collect decision-quality evidence for the first
  revenue-producing strategy.

## Current Funded Strategies

1. VWAP + EMA Trend Continuation
   - Primary official paper-validation lane.
   - Current checkpoint: 17 / 30 completed official paper trades.
   - Open official trades currently shown by source ledger: 9.

2. Morning SPY/QQQ Long ORB before noon ET
   - Funded secondary Manual Paper-Watch lane.
   - Strategy ID: `morning_index_orb_long`.
   - Current checkpoint: 0 / 20 completed ORB Manual Paper-Watch trades.
   - Broad ORB remains shadow/forward research only.

## Current KPIs

- Completed official VWAP paper trades.
- Completed ORB Manual Paper-Watch trades.
- Evidence velocity.
- Average R.
- Profit factor.
- Max drawdown.
- Opportunity frequency.
- Operator-review misses.
- Contract-review failures.
- Evidence confidence.

## Current Bottleneck

Decision-quality evidence velocity.

The system must convert valid market-hours candidates into clean, separate
evidence while they are still actionable.

## Current Risks

- Valid candidates may expire before operator review, sizing, contract review,
  and paper-only entry.
- Strategy evidence may become contaminated if ledgers are mixed.
- Future sessions may follow stale historical docs unless the authoritative
  memory files are read first.

## Recent Major Decisions

- Doctrine is frozen; default mode is EXECUTE.
- Every Executive Report recommendation must be exactly one of CONTINUE,
  INVESTIGATE, BUILD, or REALLOCATE.
- Research Runway is required for every funded strategy.
- Morning SPY/QQQ Long ORB before noon ET is promoted to Manual Paper-Watch.
- Broad ORB remains shadow-only.
- Minimum ORB Manual Paper-Watch wiring was implemented.
- Phase 3.5 Command Center activates after Tiny Live approval and before
  scaling.
- Hyperliquid crypto perpetual futures are approved only as a future Phase 7
  expansion after Equities produces a commercially validated revenue engine.

## Next Forced Decision

- VWAP: at 30 completed official paper trades, or earlier if a trigger crosses.
- Morning SPY/QQQ Long ORB: at 20 completed Manual Paper-Watch trades, or
  earlier if a trigger crosses.

## Current Approved Engineering Task

No additional engineering task is approved after the ORB Manual Paper-Watch
minimum wiring.

Default next action:

```text
Execute Monday evidence collection.
```

## Do Not Change

- Do not change trading strategy logic.
- Do not change risk rules.
- Do not change scanner logic.
- Do not change Paper Gate eligibility.
- Do not change Contract Gate standards.
- Do not change validation/accounting behavior.
- Do not enable broker orders.
- Do not enable live capital.
- Do not mix ORB evidence into VWAP's 30-trade checkpoint.
- Do not activate broad ORB, late-day ORB, ORB shorts, or non-SPY/QQQ ORB.
- Do not start Command Center, crypto, or other future roadmap work until the
  activation conditions are met.

## Files To Read First

1. `PROJECT_STATE.md`
2. `OPERATING_DOCTRINE.md`
3. `STRATEGY_STATE.md`
4. `DECISION_LOG.md`
5. `ROADMAP.md`
6. `AGENTS.md`

## Handoff Maintenance Rule

Before a major chat/window migration or context reset, refresh this handoff from
the authoritative files above. Do not use this file to silently change doctrine.

