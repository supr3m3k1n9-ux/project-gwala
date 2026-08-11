# Project Gwala Decision Log

Last updated: 2026-08-07

This file is the permanent record of material Project Gwala company decisions.
Do not silently overwrite prior decisions. Add a new dated entry when evidence
earns a change.

## 2026-08-07 - Build Morning SPY/QQQ Long ORB Manual Paper-Watch

- Decision: implement the minimum operational wiring for Morning SPY/QQQ Long
  ORB before noon ET as a Manual Paper-Watch lane.
- Evidence/reason: weekly evidence supported promotion of the narrow Morning
  SPY/QQQ Long ORB business, but the system could not yet route it through
  manual review, sizing, contract review, paper-only entry, lifecycle tracking,
  and a separate ORB ledger.
- Investment Committee recommendation: BUILD.
- What changed: added a promoted ORB manual paper-watch lane with source-aware
  filtering, review template, contract gate/template, separate paper-only
  ledger, and reporting summary.
- What did not change: VWAP strategy logic, VWAP Paper Gate, Contract Gate
  standards, risk rules, scanner logic, validation import behavior, broker
  connectivity, live execution, and broad ORB shadow/forward collection.
- Rejected alternatives: promoting broad ORB, enabling automatic approval,
  routing ORB through VWAP's official 30-trade ledger, adding dashboard or
  architecture expansion.
- Reversal condition: if Manual Paper-Watch evidence fails the approved ORB
  runway criteria or shows operational unreliability, reduce or retire the lane.

## 2026-08-07 - Promote Narrow ORB Business, Not Broad ORB

- Decision: promote Morning SPY/QQQ Long ORB before noon ET from Shadow Research
  to Manual Paper-Watch. Broad ORB remains shadow-only.
- Evidence/reason: ORB positive expectancy was concentrated in the Morning
  SPY/QQQ Long subset rather than broad ORB.
- Investment Committee recommendation: REALLOCATE research attention toward the
  narrow promoted ORB business while preserving VWAP official validation.
- What changed: ORB became a funded secondary research lane at the narrow
  business level.
- What did not change: non-SPY/QQQ ORB, shorts, late-day ORB, and broad ORB did
  not become official paper-watch strategies.
- Rejected alternatives: promote broad ORB; delay ORB activation until after
  VWAP's 30-trade checkpoint.
- Reversal condition: if the narrow ORB lane fails runway or evidence-quality
  criteria, reduce or retire it.

## 2026-08-07 - Add Research Runway Doctrine

- Decision: every funded strategy must have success criteria, failure criteria,
  and Research Runway.
- Evidence/reason: the firm must prevent indefinite research and increase
  decision velocity.
- Investment Committee recommendation: CONTINUE under finite runway rules.
- What changed: funded strategies require promotion, continue, reduction,
  retirement criteria, and a forced decision at runway exhaustion.
- What did not change: strategy logic, risk rules, or evidence thresholds
  already approved for individual lanes.
- Rejected alternatives: keep collecting evidence indefinitely.
- Reversal condition: none without a new Investment Committee doctrine decision.

## 2026-08-07 - Adopt Company Success & Failure Scorecard

- Decision: maintain a Company Success & Failure Scorecard as a weekly
  Executive Report section.
- Evidence/reason: the company needs predefined success and failure conditions
  so it does not drift.
- Investment Committee recommendation: CONTINUE execution with explicit
  trigger actions.
- What changed: company categories now track Current Status, Success Criteria,
  Failure Criteria, and Trigger Action.
- What did not change: trading behavior or research allocation by itself.
- Rejected alternatives: subjective weekly health interpretation without
  predefined failure responses.
- Reversal condition: future evidence proves the scorecard is slowing
  commercially important decisions.

## 2026-08-07 - Freeze Doctrine and Enter EXECUTE Mode

- Decision: strategic planning phase is complete; default operating mode is
  EXECUTE.
- Evidence/reason: the firm had accumulated enough doctrine and now needed to
  focus on evidence collection.
- Investment Committee recommendation: CONTINUE.
- What changed: no further philosophical, architectural, governance, or
  operating-doctrine expansion is approved unless future evidence earns it.
- What did not change: mission remains sustainable profitability as quickly as
  reasonably possible.
- Rejected alternatives: continue expanding doctrine or architecture.
- Reversal condition: only evidence showing that doctrine itself is blocking
  profitability.

## 2026-08-07 - Add Future Phase 7 Crypto Division

- Decision: approve Hyperliquid crypto perpetual futures as a future expansion
  target only.
- Evidence/reason: multi-asset expansion may eventually improve firm-level
  opportunity set.
- Investment Committee recommendation: CONTINUE equities execution now.
- What changed: Phase 7 is recorded as a future roadmap item.
- What did not change: no crypto engineering, research, implementation, or
  capital allocation is authorized until the Equities Division produces the
  first commercially validated revenue engine.
- Rejected alternatives: start crypto work now.
- Reversal condition: Equities Division reaches the approved activation
  condition for future market expansion.

## 2026-08-07 - Command Center Activation Refined

- Decision: Project Gwala Command Center activates after the first strategy is
  approved for Tiny Live and before capital scaling begins.
- Evidence/reason: the command center should manage the transition from
  research to live capital, not help discover the first edge.
- Investment Committee recommendation: CONTINUE execution now.
- What changed: Command Center is Phase 3.5, not immediate work and not delayed
  until after scaling.
- What did not change: no command-center implementation is authorized now.
- Rejected alternatives: build command center before edge discovery; wait until
  after scaling begins.
- Reversal condition: a strategy reaches Tiny Live approval.

## 2026-08-07 - Capital Deployment Philosophy Approved

- Decision: once a strategy earns capital, deploy through Paper -> Tiny Live ->
  Small Live -> Medium Live -> Full Production with strict drawdown, loss-limit,
  kill-switch, scale-up, and scale-down rules.
- Evidence/reason: the firm needs to monetize quickly once edge is validated
  while protecting capital first.
- Investment Committee recommendation: CONTINUE research until capital is
  earned.
- What changed: commercialization roadmap exists.
- What did not change: no live trading is approved today.
- Rejected alternatives: jump directly from paper to full production.
- Reversal condition: future live evidence shows stage criteria are too loose
  or too restrictive.

## 2026-08-07 - Validation Source Integrity Fix Approved

- Decision: update reporting health logic so validation-sequence comparisons
  compare only same-source candidate populations.
- Evidence/reason: scanner-snapshot Paper Gate and candidate-ledger Paper Gate
  are different populations and should not be treated as a failed sequence.
- Investment Committee recommendation: BUILD.
- What changed: Data Flow Sentinel/reporting health distinguishes
  Scanner-Snapshot Paper Gate from Candidate-Ledger Paper Gate.
- What did not change: Paper Gate eligibility, Contract Gate rules, validation
  import behavior, candidate ledger behavior, strategy logic, risk rules, or
  trading execution.
- Rejected alternatives: treat scanner-snapshot 0 vs candidate-ledger >0 as
  automatically DEGRADED.
- Reversal condition: same-source sequence mismatches recur or evidence shows
  the source distinction hides a real pipeline defect.

