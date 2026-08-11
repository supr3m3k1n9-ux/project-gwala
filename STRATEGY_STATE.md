# Project Gwala Strategy State

Last updated: 2026-08-07

This file is the authoritative current strategy portfolio state.

## Portfolio Summary

Current funded lanes:

1. VWAP + EMA Trend Continuation
2. Morning SPY/QQQ Long ORB before noon ET

Broad ORB and other Strategy Vault ideas remain research/shadow unless
separately promoted by evidence.

## VWAP + EMA Trend Continuation

- Market/business: Equities Division, US equities/options.
- Lifecycle stage: official paper validation.
- Allocation/research priority: primary lane.
- Evidence summary: official paper collection active.
- Completed official paper trades: 17 / 30.
- Open official paper trades: 9 currently shown in
  `data/paper_validation_samples.csv` as of 2026-08-07.
- Average R: latest known completed official sample average approximately
  negative/slightly below breakeven; use current report artifacts for exact
  value before a decision.
- Profit factor: use current report artifacts before decision.
- Drawdown: use current report artifacts before decision.
- Research runway: 30 completed official paper trades for the current
  checkpoint.
- Promotion distance: 13 more completed official trades needed from the 17/30
  source count.
- Reduction/retirement status: no final trigger crossed yet.
- Next required evidence: completed official outcomes from open trades and new
  valid paper entries.
- Next forced decision: at 30 completed official paper trades or earlier if a
  promotion, reduction, retirement, or engineering trigger crosses.

## Morning SPY/QQQ Long ORB Before Noon ET

- Strategy identifier: `morning_index_orb_long`.
- Market/business: Equities Division, US equities/options.
- Lifecycle stage: Manual Paper-Watch.
- Allocation/research priority: funded secondary lane.
- Evidence summary: narrow ORB subset earned promotion from shadow evidence;
  broad ORB did not.
- Completed Manual Paper-Watch trades: 0 / 20.
- Open Manual Paper-Watch trades: 0.
- Average R: 0.0 for Manual Paper-Watch ledger because no completed manual
  trades exist yet.
- Profit factor: 0.0 for Manual Paper-Watch ledger until completed evidence
  exists.
- Drawdown: 0.0 for Manual Paper-Watch ledger until completed evidence exists.
- Research runway: 20 completed Morning SPY/QQQ Long ORB Manual Paper-Watch
  trades.
- Promotion distance: 20 completed manual trades remaining.
- Reduction/retirement status: no Manual Paper-Watch trigger crossed yet.
- Next required evidence: fresh Monday market-hours candidate review, paper-only
  sizing, contract review, entries, lifecycle outcomes, and separate ORB ledger
  completions.
- Next forced decision: at 20 completed ORB Manual Paper-Watch trades or earlier
  if a trigger crosses.

Approved checkpoint criteria:

- 20 completed trades.
- Positive average R.
- Target average R at least +0.20R.
- Profit factor greater than 1.30.
- Max drawdown no worse than -4R.
- SPY and QQQ tracked separately.
- No single symbol responsible for more than 50% of positive R unless separated
  into its own strategy.
- Clean operational timing and audit trail.
- Market-regime coverage tracked.

## Broad Opening Range Breakout

- Market/business: Equities Division, US equities/options.
- Lifecycle stage: shadow/forward research only.
- Allocation/research priority: not the promoted business.
- Evidence summary: aggregate broad ORB evidence is less commercially precise
  than the Morning SPY/QQQ Long subset.
- Completed official trades: 0.
- Research runway: no active Manual Paper-Watch runway.
- Promotion distance: requires separate evidence and Investment Committee
  approval.
- Reduction/retirement status: unchanged shadow-only.
- Next required evidence: continue broad shadow/forward collection only.
- Next forced decision: none unless evidence earns a new review.

## Other Strategy Vault Lanes

The following remain research backlog or shadow-only unless evidence earns a
new allocation decision:

- VWAP Mean Reversion.
- Gap Fill / Gap Fade.
- VWAP Reclaim / Reject.
- Trend Pullback Continuation.
- Opening Range Failure.

No engineering or strategy activation is authorized for these lanes right now.

