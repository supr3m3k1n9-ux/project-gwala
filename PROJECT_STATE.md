# Project Gwala State

Last updated: 2026-08-07

This file is the authoritative current-state memory for Project Gwala. It
represents now, not the full history.

## Mission

Build a quantitative trading firm that reaches sustainable profitability as
quickly as reasonably possible.

## Current Phase

Phase 2: discover the firm's first commercially viable trading edge.

Current operating mode:

```text
EXECUTE
```

## Current Company State

- Commercial stage: Pre-Revenue.
- Active business: Equities Division, US equities/options research.
- Live capital: not deployed.
- Broker/live execution: disabled.
- Primary objective: collect decision-quality evidence for the first
  revenue-producing strategy.

## Active Funded Strategies

1. VWAP + EMA Trend Continuation
   - Role: primary official paper-validation lane.
   - Evidence target: 30 completed official paper trades for the current
     decision checkpoint.

2. Morning SPY/QQQ Long ORB before noon ET
   - Role: funded secondary Manual Paper-Watch lane.
   - Strategy identifier: `morning_index_orb_long`.
   - Evidence target: 20 completed ORB Manual Paper-Watch trades.
   - Broad ORB remains shadow/forward research only.

## Current Critical KPIs

- VWAP completed official paper trades: 17 / 30.
- VWAP open official paper trades: 9 currently shown in
  `data/paper_validation_samples.csv` as of 2026-08-07.
- ORB Manual Paper-Watch completed trades: 0 / 20.
- ORB Manual Paper-Watch ledger:
  `data/morning_index_orb_manual_paper_trades.csv`.
- Monthly operating cost assumption: approximately $200.
- Monthly trading profit: $0 realized live profit.

## Current Biggest Bottleneck

Decision-quality evidence velocity.

VWAP still needs completed official outcomes. Morning SPY/QQQ Long ORB now has
the minimum operational wiring to start Manual Paper-Watch evidence collection,
but the operator must review and contract-check candidates while they are still
actionable.

## Current Runway Status

Research runway is active and finite.

- VWAP: continue until the 30-completed-trade checkpoint forces a decision.
- Morning SPY/QQQ Long ORB: collect up to 20 completed Manual Paper-Watch trades
  before the next Investment Committee promotion/reduction/retirement decision.
- Default is not indefinite continuation. At runway checkpoints, the Investment
  Committee must choose PROMOTE, CONTINUE with written justification, REDUCE, or
  RETIRE.

## Current Highest-ROI Task

Execute Monday market-hours evidence collection:

1. Preserve VWAP official paper validation.
2. Run the promoted Morning SPY/QQQ Long ORB Manual Paper-Watch workflow.
3. Review fresh ORB candidates quickly enough to size, contract-review, and log
   paper-only entries while actionable.

## Current Biggest Risk

Operational timing risk: valid candidates may be detected but not reviewed,
sized, contract-checked, and entered into the correct paper-only ledger before
the market opportunity expires.

## Next Forced Decision

The next forced business decisions are:

1. VWAP at 30 completed official paper trades.
2. Morning SPY/QQQ Long ORB at 20 completed Manual Paper-Watch trades.
3. Any earlier trigger crossing for promotion, reduction, retirement,
   engineering, or capital reallocation.

## Active Guardrails

- No live capital.
- No broker orders.
- No automated real-money execution.
- No strategy-rule changes unless evidence earns them and the Investment
  Committee approves.
- Do not contaminate VWAP's 30-trade count with ORB evidence.
- Broad ORB remains shadow-only unless separately promoted.

