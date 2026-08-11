# Gwala Doctrine

Legacy note, added 2026-08-07:

The authoritative company operating doctrine is now the root-level
`OPERATING_DOCTRINE.md`. This `docs/gwala-doctrine.md` file is retained as
historical context and dated project history. If it conflicts with the
root-level company-memory files, use the root-level files.

This document defines durable principles for Project Gwala. Preserve dated
entries and do not rewrite history when doctrine changes.

## Core Doctrine

Gwala is a chart-first intraday options research and paper-validation system.

The chart determines direction and timing. Options are the execution vehicle and
must be filtered for contract quality before a sample is treated as official.

## Non-Negotiables

- Research and paper validation come before live trading.
- No live execution until backtesting and paper validation are complete.
- No broker order placement without explicit future approval.
- No martingale logic.
- No averaging down losers.
- No revenge-trade behavior.
- No overleverage.
- No stop-loss removal.
- No loosening rules merely to force paper-trade count.

## Operating Doctrine

- Keep V1 simple enough to reach paper/live-readiness without turning the bot
  into a hedge-fund platform from day one.
- In ship mode, reliability beats breadth. Finish the paper workflow before
  expanding the research universe again.
- Use regime routing to decide when a strategy deserves attention.
- Use gates to prevent research ideas from quietly becoming paper-ready.
- Treat official paper samples as evidence, not decoration.
- Prefer manual validation where automation would slow the near-term path to
  market or introduce unreliable data.

## Documentation Doctrine

- The root-level company-memory files are the source of truth for current
  company reasoning; this `docs/` file is historical context.
- Do not create new handoff files by default.
- Update the appropriate living doc when discussion changes doctrine,
  philosophy, strategy, roadmap, or backlog.
- Add dated entries that explain what changed, why, assumptions, and whether
  implementation is affected.
- When uncertain, propose the documentation update before changing trading
  logic.

## Dated Entries

### 2026-06-16 - Manual Grace Lane Doctrine

What changed:

- Gwala may use a one-M30-candle B-tier grace lane for manual paper-validation
  review if the lane is explicitly wired and tested.
- The grace lane is not an automated entry permission and does not weaken
  safety-critical gates.

Why it changed:

- A 90-day replay showed the one-candle-late lane can materially increase
  paper-review throughput while maintaining quality when fresh sizing,
  stop/target recalculation, and manual review are required.

Assumptions:

- Current-candle A-tier remains the cleanest validation path.
- B-tier grace must remove duplicate windows where the same setup/time is
  already A-tier.
- Earlier-today signals outside the one-candle window stay research/shadow.

Implementation impact:

- Implemented on 2026-06-16 across scanner, sizing, router, pre-entry review,
  Paper Gate v2, Options Contract Gate, validation import, reporting, and app
  state.
- B-tier preserves data freshness, duplicate prevention, manual review, reduced
  risk, and local-only paper validation.
- Local paper-entry packets and broker/order paths remain A/current only.
- Future B-tier expansion beyond one M30 candle requires new research evidence
  and another doctrine update.

### 2026-06-15 - Ship Funnel Visibility Required

What changed:

- Ship-mode workflows should produce a daily funnel report that makes candidate
  drop-off visible from scanner output through validation import and completed
  official paper-trade progress.

Why it changed:

- Reliability issues are easier to fix when the system shows the first
  bottleneck immediately instead of requiring manual CSV tracing.

Assumptions:

- Observability can accelerate paper-gate completion without weakening the
  trading rules.
- Completed official paper trades remain evidence-based and separate from
  historical backtests, shadow samples, or unconfirmed import previews.

Implementation impact:

- `DAILY_SHIP_REPORT` is part of the ship-mode workflow contract.
- This does not authorize live broker execution, automatic sample import, or
  rule loosening.

### 2026-06-15 - Ship Mode Doctrine Adopted

What changed:

- Project Gwala is now operating in ship mode.
- New strategies, indicators, options-flow systems, gamma models, and Strategy
  Vault expansion are deferred.
- The paper gate remains evidence-based: 30 completed allowed paper trades are
  required before the project can consider controlled small-size live trading.

Why it changed:

- The user goal is to reach market faster, but the safest acceleration is to
  reduce workflow friction and enforce the existing gates, not add more
  unfinished strategy surface area.

Assumptions:

- A simple, reliable paper workflow is more valuable than a broader but
  harder-to-trust research system.
- Official samples should be countable only when data freshness, review gates,
  risk sizing, and contract quality agree.
- Live trading requires a separate safety checklist after the paper gate.

Implementation impact:

- Near-term code work should focus on local paper reliability and safety
  enforcement.
- Any future live path must include a kill switch, emergency shutdown, daily
  loss cap, max trades per day, duplicate-order protection, broker rejection
  handling, broker disconnect handling, and durable logging.

### 2026-06-15 - Filter Discipline For Paper Gate

What changed:

- Gwala now treats filters as three classes: safety-critical, trade-quality,
  and experimental.
- Safety-critical filters remain strict.
- Trade-quality filters should be configurable and reported.
- Experimental filters should be disabled by default during ship mode unless
  explicitly requested.

Why it changed:

- The paper gate needs enough trades to evaluate performance. Over-stacking
  confirmation filters can make the platform look safe while actually starving
  the validation process.

Assumptions:

- More paper trades are acceptable only if risk limits, data freshness,
  duplicate prevention, sizing controls, and manual review remain intact.
- Trade-quality thresholds can be tuned after seeing rejection counts.

Implementation impact:

- Paper validation should use filter rejection counts before adding or removing
  rules.
- New filters must declare whether they are safety-critical, trade-quality, or
  experimental before they can block paper samples.

### 2026-06-15 - Living Knowledge Base Adopted

What changed:

- Project Gwala now uses `docs/PROJECT_STATE.md`, `docs/gwala-doctrine.md`,
  `docs/trading-philosophy.md`, `docs/strategy-vault.md`, and
  `docs/PROJECT_ARCHITECTURE.md` as the living knowledge base.

Why it changed:

- The project needs one coherent record of decisions instead of disconnected
  handoff files.

Assumptions:

- Decisions are safer when the reasoning is preserved near the implementation.
- Dated entries reduce confusion when priorities shift.

Implementation impact:

- Future code changes should be preceded by reading these docs when they exist.
- Trading-logic changes should update the relevant doc in the same work session.

### 2026-06-15 - Architecture Documentation Added

What changed:

- Added `docs/PROJECT_ARCHITECTURE.md` to the living knowledge base.

Why it changed:

- Project Gwala needs a stable architecture map so future work can preserve
  data sync, report ordering, and safety boundaries.

Assumptions:

- Architecture drift is one of the main risks as the platform grows.
- A living architecture doc is more useful than disconnected handoff notes.

Implementation impact:

- Future architecture changes should update `docs/PROJECT_ARCHITECTURE.md`
  before or alongside code changes.
