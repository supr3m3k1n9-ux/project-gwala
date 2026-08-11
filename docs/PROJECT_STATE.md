# Project Gwala State

Legacy note, added 2026-08-07:

The authoritative current company-state file is now the root-level
`PROJECT_STATE.md`. This `docs/PROJECT_STATE.md` file is retained as historical
context and dated project history. If it conflicts with the root-level
company-memory files, use the root-level files.

This document is historical project context for prior status, guardrails, and
dated decisions. Preserve historical entries, but use the root-level
company-memory files for current authority.

## Current Phase

Research, backtesting, and manual paper validation.

Live broker execution, real-money trading, automated order placement, and live
Webull execution remain disabled unless explicitly approved after backtesting
and paper-trading work are complete.

## Current Implementation State

- Chart-first intraday options research system.
- Webull local CSV data is the active market-data path for dashboard/scanner work.
- Ship mode is active: strategy expansion is frozen until the paper gate is
  moving reliably.
- Strategy Vault and Market Regime Router are wired for research/manual paper
  review, not automatic execution.
- Paper Gate v2 separates A/B/C validation samples.
- Options Contract Gate v1 exists as a manual quality gate before official
  options validation samples are imported.
- Validation sample import writes to `data/paper_validation_samples.csv`, not
  `data/paper_trades.csv`, and requires explicit confirmation.

## Active Safety Guardrails

- No live broker orders.
- No real-money execution.
- No broker alerts that imply execution.
- No new strategy, indicator, options-flow, gamma, or Strategy Vault expansion
  work during ship mode.
- No martingale, averaging down, revenge entries, overleverage, or stop removal.
- Official paper-validation samples must pass current-session/data freshness
  gates.
- Options validation samples must pass the Options Contract Gate before import.

## Dated Entries

### 2026-06-17 - Market Session Readiness Checklist Added

What changed:

- Added `docs/MARKET_SESSION_READINESS.md` as the operational checklist for
  the next regular market session.
- The checklist defines exact pre-market, market-hours, candidate review,
  Options Contract Gate, validation import, blocker, and end-of-day metric
  commands.

Why it changed:

- The A/current and B/one-M30 grace lanes are now implemented, so the next
  session needs a simple operating guide that turns workflow outputs into
  repeatable user actions.

Assumptions:

- This remains research and manual paper validation only.
- Live broker execution, real-money trading, broker order placement, and
  B-tier auto-entry remain disabled.

Implementation impact:

- No trading logic changed.
- Tomorrow's market session should use `run_premarket_verification.py` before
  the open and `run_current_candle_capture.py` during market hours, then follow
  the A/B candidate workflow in the readiness checklist.

### 2026-06-16 - One-Candle B-Tier Grace Lane Implemented

What changed:

- Implemented the researched one-M30-candle B-tier grace lane across scanner,
  position sizing, market regime router, pre-entry review, Paper Gate v2,
  Options Contract Gate, validation import, daily ship reporting, and app state.
- A-tier remains strict current M30 candle only.
- B-tier is exactly current + one prior M30 signal window only, requires manual
  paper review, uses a refreshed latest-candle plan, receives reduced sizing,
  removes duplicate A-window candidates, and must pass Options Contract Gate
  before validation import.
- B-tier grace rows are excluded from local paper-entry packets and broker/order
  paths.

Why it changed:

- The current-candle-only rule was safe but too narrow for manual validation
  throughput. The user approved the researched grace structure because the
  backtest showed a `64.3%` candidate-window increase without worse average R
  or MAE.

Assumptions:

- B-tier is a validation workflow lane, not a new strategy or indicator.
- Anything older than current + one M30 candle remains study/shadow only.
- B-tier can count toward the 30 official validation samples only after manual
  review and Options Contract Gate pass, but it does not count toward live
  readiness by itself.

Implementation impact:

- Full workflow safety tests passed: `202 / 202`.
- The latest capture run completed end-to-end and currently shows `0` A/current
  and `0` B/grace allowed rows; the current bottleneck is scanner freshness, not
  the downstream B-tier wiring.
- `docs/SHIP_READINESS_REPORT.md` now reflects the implemented B-tier lane and
  the expected `64.3%` throughput improvement from `logs/grace_lane_backtest.json`.

### 2026-06-16 - One-Candle Grace Lane Backtested

What changed:

- Added `run_grace_lane_backtest.py` to replay the proposed Paper Gate grace
  structure from local Webull CSV candles.
- The report writes `logs/grace_lane_backtest.md`,
  `logs/grace_lane_backtest.json`, and `logs/grace_lane_backtest.csv`.
- The 90-day approved-plus-watch replay compared current A-tier candidates
  against incremental one-M30-candle-late B-tier review windows.

Why it changed:

- The strict `current_candle` rule is protecting data freshness, but it can
  also cause valid manual-review opportunities to expire before the workflow
  reaches Paper Gate v2.
- The user asked whether a one-candle grace lane would materially increase
  throughput without degrading trade quality.

Assumptions:

- A-tier remains current M30 candle only.
- B-tier is manual review only and requires fresh sizing, fresh stop, fresh
  target, and a fresh one-candle-late plan.
- Earlier-today signals beyond one M30 candle remain research/shadow only.
- B windows that duplicate an A-tier opportunity at the same setup/time should
  not count as incremental throughput.

Implementation impact:

- Runtime Paper Gate behavior is unchanged by this audit.
- Research evidence supports a future manual B-tier grace implementation:
  current A-tier produced `308` candidates at `50.3%` win rate, `+0.1696R`
  average R, and `0.5596R` average MAE; incremental B-tier produced `198`
  candidates at `61.6%` win rate, `+0.3126R` average R, and `0.4826R`
  average MAE.
- The audited candidate-window increase was `64.3%` after removing `29`
  B windows that duplicated current A windows.
- Next implementation, if approved, should wire B-tier as a manual
  paper-validation lane only, with no auto-entry, no broker orders, and no
  live-readiness credit unless explicitly promoted later.

### 2026-06-16 - Autonomous Market Refresh LaunchAgent Repaired

What changed:

- Regenerated and reinstalled the macOS LaunchAgent for the autonomous paper
  workflow from `tools/build_autonomous_launchd_plist.py`.
- The installed LaunchAgent now uses `--once`, writes unbuffered logs, and has
  weekday schedule entries for pre-market verification, repeated market-hours
  current-candle scans, and after-close recap.
- A manual launchd kickstart completed successfully with exit code `0`.

Why it changed:

- The previous installed LaunchAgent was stale: it only had the old morning
  schedule and did not include the one-shot supervisor contract.
- Shell-detached loops were not durable enough for this environment, so macOS
  launchd is the correct always-on scheduling layer for current data refreshes.

Assumptions:

- This remains research and paper-validation only. The LaunchAgent does not
  place broker orders, create broker alerts, import new paper entries, or enable
  real-money execution.
- The Mac must be awake and the user LaunchAgent session must be available for
  scheduled refreshes to run.

Implementation impact:

- `launchd/com.project-gwala.autonomous-paper.plist` is now aligned with the
  generated LaunchAgent contract.
- `~/Library/LaunchAgents/com.project-gwala.autonomous-paper.plist` has been
  installed and loaded from the regenerated project plist.
- The proof run refreshed current-session Webull candles, rebuilt the current
  paper pipeline, passed dashboard preflight, and left launchd waiting for the
  next scheduled trigger.

### 2026-06-16 - Historical Bucket Sync Guardrail Added

What changed:

- Added a dedicated historical bucket sync guardrail for the historical
  simulation account.
- The guardrail audits Approved Playbook, Promotion Review, and Strategy Vault
  Research buckets against the latest scanner session.
- The report writes `logs/historical_bucket_sync.json` and
  `logs/historical_bucket_sync.md`, and the result is included in
  `logs/system_state.json`.

Why it changed:

- Historical simulator rows come from different source buckets that can refresh
  at different times.
- The dashboard should not imply that every historical lane is current just
  because the unified simulator has at least one current lane.

Assumptions:

- Bucket sync is observability only. It does not alter strategy logic, paper
  eligibility, position sizing, validation import, or live execution.
- The market-hours current-candle capture path should audit bucket sync without
  slowing down candidate capture with a full research rebuild.

Implementation impact:

- `run_historical_bucket_sync.py` is now part of the fast capture workflow, the
  full daily workflow, dashboard refresh state commands, System State, Data Flow
  Sentinel, and dashboard report registry.
- A `watch` bucket-sync status means current paper scanning can continue, but
  stale historical lanes must be treated as older research context.

### 2026-06-16 - Historical Source Freshness Made Explicit

What changed:

- The historical simulation account now exposes source-level freshness for
  Approved Playbook, Promotion Review, and Strategy Vault Research rows.
- The Paper Progress historical account card shows each lane's latest trade
  date, row count, and freshness status against the latest scanner session.
- The frontend re-checks the historical freshness card after central app state
  loads, so a load-order race cannot leave source lanes stuck in an
  ambiguous "loaded" status.

Why it changed:

- A single blended "last trade" date can make the historical section look stale
  even when one source lane is behind and another is current.
- The user repeatedly catches sync issues in the historical trade section, so
  the app should make stale lanes visible immediately instead of requiring CSV
  tracing.

Assumptions:

- Source freshness is observability only. It does not change trading rules,
  paper-gate eligibility, position sizing, validation import, or broker
  behavior.
- Historical backtests, shadow samples, and official paper samples remain
  separate evidence classes.

Implementation impact:

- `/api/backtest-portfolio` now returns `source_bucket_timelines`.
- The Paper Progress historical simulator card renders per-source freshness so
  Promotion Review can be behind while the unified simulator remains current
  through Strategy Vault rows.
- The Paper Progress sync badge and source-lane cards now rerender after app
  state refreshes, keeping the historical account view aligned with the latest
  scanner session.

### 2026-06-16 - Paper Trade Command Center Added

What changed:

- Added a launch-focused Paper Trade Command Center to the Home dashboard.
- The panel summarizes current candidates, the current funnel bottleneck,
  completed official paper trades, remaining trades to the 30-trade gate, win
  rate, average R, and the current market regime.
- `logs/system_state.json` now exposes a `paper_trade_command_center` object
  sourced from current candidates, the official validation ledger when present,
  `DAILY_SHIP_REPORT`, and the Market Regime Router.

Why it changed:

- Ship mode needs one screen that answers whether the project is moving toward
  launch without manually opening several reports.
- The user has repeatedly flagged data wiring and sync drift as a major risk,
  so the launch panel should read from the same central app state as the rest
  of the dashboard.

Assumptions:

- The panel is observability only and must not fetch data, import samples,
  place broker orders, create broker alerts, or change trading rules.
- Official progress should prefer `data/paper_validation_samples.csv` when it
  exists, with existing ship and paper-progress reports used as fallback
  context.

Implementation impact:

- Home now shows the launch-progress panel immediately after Mission Control.
- This does not loosen safety filters, add strategies, or enable live trading.

### 2026-06-15 - DAILY_SHIP_REPORT Funnel Added

What changed:

- Added `run_daily_ship_report.py` to produce `logs/DAILY_SHIP_REPORT.md`,
  `logs/DAILY_SHIP_REPORT.csv`, and `logs/DAILY_SHIP_REPORT.json`.
- The report shows scanner signals, allowed signals, size-ok signals,
  review-ready signals, Paper Gate A/B signals, contract-passed signals,
  validation-import rows, completed official paper trades, and percentage drop
  between comparable current-run stages.
- Wired the report into the current-candle capture workflow, full daily
  workflow, local paper-session cycle, and app report allow-list.

Why it changed:

- The paper gate cannot move quickly if bottlenecks are only visible after a
  manual trace. Each workflow run should immediately show where candidates
  disappear.

Assumptions:

- The report is observability only and should not loosen any safety or quality
  gate.
- Completed official paper trades are cumulative validation-ledger progress,
  while scanner-to-validation counts describe the latest workflow run.

Implementation impact:

- Workflow runs now refresh `DAILY_SHIP_REPORT` after the validation-import
  preview stage.
- Broker orders, broker alerts, automatic sample confirmation, live execution,
  and real-money execution remain disabled.

### 2026-06-15 - Current-Candle Capture Fast Path Added

What changed:

- Added `run_current_candle_capture.py` as the fast market-hours capture pass
  for official paper candidates.
- Updated intraday, autonomous, and accelerated market-hours scan loops to use
  the current-candle capture pass instead of the full daily workflow.
- The capture report now writes `logs/current_candle_capture.json` and
  `logs/current_candle_capture.md` with scanner, sizing, router, pre-entry,
  Paper Gate, Options Contract Gate, validation import, and first-bottleneck
  counts.

Why it changed:

- The Ship Readiness Report showed the narrowest bottleneck was timing:
  allowed candidates were being seen after they were already `earlier_today`
  instead of while still `current_candle`.
- The full daily workflow rebuilds too much research surface for a fast
  market-hours scan loop.

Assumptions:

- The strict `current_candle` safety rule should stay in place.
- The correct acceleration is to capture valid signals sooner, not to weaken
  data freshness or add new strategies.
- Validation import remains preview/manual unless explicitly confirmed later.

Implementation impact:

- Market-hours scan loops now call `run_current_candle_capture.py`.
- New paper entries are still not auto-confirmed.
- Broker orders, broker alerts, live execution, and real-money execution remain
  disabled.

### 2026-06-15 - Ship Readiness Report Added

What changed:

- Added `docs/SHIP_READINESS_REPORT.md` with current launch readiness,
  trade-funnel counts, rejection counts, paper-gate status, safety audit,
  scope-creep audit, and market-launch recommendation.
- Initial controlled-live launch readiness was scored at `26%`; the updated
  2026-06-16 report scores readiness at `30%` after B-tier implementation.
- Market launch recommendation is `B) Requires additional hardening before
  paper gate completion`.

Why it changed:

- The project needs hard evidence for ship-mode decisions instead of relying on
  recommendations alone.
- The latest reports show the architecture is mostly synchronized, but the
  official paper funnel is not yet producing countable candidates.

Assumptions:

- The latest evidence snapshot is from the 2026-06-15 local workflow reports.
- Webull remains the active market-data-only provider.
- Completed allowed paper trades, not historical or shadow samples, are the
  paper gate currency.

Implementation impact:

- No runtime behavior changed.
- Next implementation should harden the local paper write contract, keep
  strategy expansion frozen, and focus on converting valid current-candle
  candidates into completed official paper evidence.

### 2026-06-15 - Ship Mode Release Decision

What changed:

- Added `docs/SHIP_MODE_RELEASE_PLAN.md` as the active release plan for getting
  to the paper trading gate.
- Froze new strategy, indicator, options-flow, gamma, and Strategy Vault work
  until the paper workflow is reliable.
- Defined the near-term release target as 30 completed allowed paper trades,
  followed by a separate small-size live-readiness checklist.

Why it changed:

- The main path-to-market blocker is not a lack of research ideas. It is that
  the official paper workflow has not yet produced 30 completed allowed paper
  trades.
- Recent sync work improved visibility, but ship mode needs enforcement at the
  write points too.

Assumptions:

- Webull remains the active market-data-only path.
- Local paper validation is the fastest safe path; broker execution remains
  disabled.
- Strategy integrity should not be loosened just to force the paper count.

Implementation impact:

- Current runtime behavior is not changed by this documentation entry.
- Next implementation work should focus on paper-workflow enforcement:
  local kill switch, max trades per day at the paper writer, and hard alignment
  between pre-entry/Paper Gate/Options Contract Gate and countable paper rows.
- Live trading remains blocked until paper validation and live safety systems
  are complete.

### 2026-06-15 - Ship Mode Filter Audit

What changed:

- Added a ship-mode filter policy that separates safety-critical filters,
  trade-quality filters, and experimental filters.
- Paper scanning now defaults to no experimental `weakness_v1` overlay; that
  filter can still be requested explicitly for research comparisons.
- Added a filter rejection report so the workflow shows exactly which filters
  are blocking candidates and how often.

Why it changed:

- Gwala may have been over-filtered for the paper gate. The platform needs
  enough official paper samples to evaluate performance without disabling core
  safety.

Assumptions:

- Safety-critical controls stay strict.
- Trade-quality filters should be visible and configurable rather than hidden.
- Experimental confirmation stacking should not be enabled by default during
  ship-mode paper validation.

Implementation impact:

- `config/filter_policy.py` owns the current ship-mode filter classifications
  and paper-gate/contract-gate thresholds.
- `run_filter_rejection_report.py` writes rejection audit and summary files.
- Daily and paper-session workflows rebuild the rejection report with the rest
  of the paper gate.

### 2026-06-15 - Living Documentation Source Of Truth

Superseded note:

This 2026-06-15 decision is historical. As of 2026-08-07, the root-level
company-memory files are the authoritative current source of truth.

What changed:

- Created the `docs/` knowledge base as the preferred source of truth for
  Project Gwala decisions.
- Future trading concepts, strategy changes, market-regime insights, options
  contract rules, risk decisions, and architecture decisions should be written
  into these docs instead of scattered handoff files.
- Before code changes, the engineer should read these docs when they exist and
  update the relevant one when a decision changes doctrine, philosophy,
  strategy, roadmap, or backlog.

Why it changed:

- The project has accumulated many handoff-style notes. A living knowledge base
  reduces drift and keeps reasoning connected to implementation.

Assumptions:

- These docs are easier to maintain than disconnected handoffs.
- Preserving dated reasoning is more valuable than overwriting older context.
- Documentation should guide trading-logic changes, especially when the change
  affects risk, strategy selection, or path-to-market timing.

Implementation impact:

- Current implementation is not changed by this entry.
- Future implementation should use these docs as the planning checkpoint before
  modifying trading logic.

### 2026-06-15 - Options Contract Gate v1 Added

What changed:

- Added a manual Options Contract Gate between Paper Gate v2 and validation
  sample import.
- The gate checks selected contract quality using delta, DTE, bid/ask spread,
  volume, open interest, premium, option type, strike, and earnings-window
  status.

Why it changed:

- Gwala is chart-first, but official options paper samples should not count if
  the actual contract is structurally poor.
- This prevents a good chart signal from being validated through a bad options
  contract.

Assumptions:

- Manual contract audit is faster than wiring a new option-chain provider.
- Contract selection should support the path to market without turning V1 into
  an advanced options-flow or volatility system.

Implementation impact:

- `run_options_contract_gate.py` produces gate reports and a manual template.
- `run_paper_validation_sample_import.py` now imports only contract-passed rows.
- Dashboard/report wiring includes the Options Contract Gate.

### 2026-06-15 - Validation Pipeline Sync Hardening

What changed:

- Added a targeted hardening task for the expanded validation path instead of a
  broad refactor.
- The fragile dependency chain is now treated as:
  `Paper Gate v2 -> Options Contract Gate -> Validation Sample Import ->
  Dashboard Preflight -> Data Flow Sentinel -> System State`.
- The Data Flow Sentinel should verify that the saved gate reports agree with
  each other before the dashboard is treated as synchronized.

Why it changed:

- Adding the Options Contract Gate created more moving parts. The main risk is
  not strategy logic; it is stale or mismatched report outputs being shown as if
  they belong to the same workflow run.

Assumptions:

- The existing architecture is usable; a full rewrite would slow the path to
  market.
- Small, explicit sync checks are safer than centralizing every workflow command
  before the pipeline has stabilized.

Implementation impact:

- Add validation-gate consistency checks to the Data Flow Sentinel.
- Add generation metadata to validation sample import outputs so stale report
  issues are easier to diagnose.

### 2026-06-15 - Project Architecture Document Added

What changed:

- Added `docs/PROJECT_ARCHITECTURE.md` as the readable source map for the
  current implementation.
- The architecture document covers the active Webull market-data path, scanner
  pipeline, Strategy Vault, Paper Gate v2, Options Contract Gate v1, validation
  sample import, dashboard state contract, sync guardrails, and safety
  boundaries.

Why it changed:

- The project now has enough moving parts that future changes need one
  architecture reference before refactoring or adding new data paths.

Assumptions:

- Keeping the architecture documented will reduce wiring drift and repeated
  dashboard sync issues.
- The current implementation should be hardened with explicit contracts instead
  of rewritten broadly.

Implementation impact:

- Runtime behavior is unchanged.
- Future architecture or data-flow changes should update
  `docs/PROJECT_ARCHITECTURE.md` in the same work session.
