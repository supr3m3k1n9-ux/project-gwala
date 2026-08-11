# Project Gwala Ship Mode Release Plan

Last updated: 2026-06-15

This plan freezes new strategy expansion and focuses on the shortest safe path
to the paper trading gate, then controlled small-size live trading later.

## Release Decision

Project Gwala is in ship mode.

Ship mode means:

- Do not add new strategies, indicators, options-flow systems, gamma models, or
  Strategy Vault features.
- Do not loosen hard safety gates just to force the trade count.
- Prioritize reliable paper workflow execution, data freshness, reviewability,
  duplicate prevention, and clean progress tracking.
- Live broker execution remains out of scope until the paper gate is satisfied
  and the live safety checklist is implemented.

## Current Gate Status

As of the latest local reports on 2026-06-15:

| area | status |
| --- | --- |
| Active data provider | Webull market-data-only CSV path |
| Refresh status | `prep_only` because the market is closed |
| Provider refresh evidence | Current-session Webull M5/M30 bars were recorded |
| Data Flow Sentinel | `watch`, with no failed sync checks |
| Paper Gate v2 | `waiting` |
| A/B ready validation samples | `0` |
| Options Contract Gate | `waiting_for_chart_candidate` |
| Completed allowed paper trades | `0 / 30` |
| Risk guard | Conservative-only, max forward risk `0.50%` |

The current blocker is not a new strategy shortage. The current blocker is that
the official paper workflow has not produced and completed 30 allowed paper
trades yet.

## 1. What Blocks The Paper Trading Gate Right Now

Hard blockers:

- `0 / 30` completed allowed paper trades are logged in the official paper
  progress path.
- The latest Paper Gate v2 report has `0` A/B ready validation samples.
- The Options Contract Gate has no current chart candidate to review.
- The current market state is `prep_only` after the close, so paper import is
  blocked until the next open-market refresh creates current-candle candidates.
- The scanner has no `current_candle` candidate currently eligible for local
  paper sizing.

Ship-mode safety gaps:

- The local paper entry writer requires `size_ok`, but it currently annotates
  pre-entry review instead of enforcing pre-entry readiness as a hard write
  condition.
- The local paper entry writer does not yet enforce a daily max-trades cap at
  write time.
- There is no global local kill switch that blocks paper ledger writes.
- The Options Contract Gate is part of the validation-sample path, but the
  local paper entry writer should not allow official options-like samples to
  bypass that review when the trade is meant to count.

## 2. Required Blockers For Safe Launch

Required before counting new official paper trades:

- Current-session Webull refresh passes during market hours.
- Dashboard Data Preflight passes.
- Data Flow Sentinel has no failed sync checks.
- Scanner row is from today's session.
- Signal freshness is `current_candle`.
- Position sizing status is `size_ok`.
- Pre-entry review is ready.
- Paper Gate v2 classifies the row as A or B.
- Options Contract Gate passes when the sample is treated as an official
  options paper-validation sample.
- Local paper entry confirmation is explicit.
- Duplicate order prevention remains active.
- Daily loss guard remains active.
- Daily max-trades guard is enforced.
- Every entered local paper trade can be monitored to a completed outcome.

Required before any small-size live trading:

- 30 completed allowed paper trades are logged.
- Paper review shows positive expectancy or a clear no-go decision.
- No unresolved data-sync failures remain.
- Global kill switch exists and is tested.
- Max daily loss exists and is tested against broker/order flow.
- Max trades per day exists and is tested against broker/order flow.
- Position sizing limits are enforced before order creation.
- Order rejection handling is implemented and tested.
- Broker disconnect handling is implemented and tested.
- Duplicate order prevention uses idempotent order keys.
- Emergency shutdown is implemented and tested.
- Full broker/event logging exists.
- User gives explicit future approval to move from paper to live.

## 3. Nice-To-Have Items To Defer

Defer these until the paper gate is moving cleanly:

- New strategy families.
- New indicators.
- Options-flow or gamma models.
- Advanced option-chain automation.
- Strategy Vault expansion.
- Additional visual showpieces.
- Large dashboard redesigns.
- Broker execution abstraction beyond what is needed for a later controlled
  live pilot.
- Perfect historical simulation cosmetics unless they affect trust or sync.

## 4. Smallest Testable Paper Version

The smallest shippable paper-mode version is:

```text
run_current_candle_capture.py during market hours
  -> Dashboard Data Preflight
  -> Data Flow Sentinel
  -> Daily Scanner
  -> Position Sizer
  -> Pre-Entry Review
  -> Paper Gate v2
  -> Options Contract Gate
  -> Paper Entry Packet
  -> Explicit local paper confirmation
  -> Open Paper Monitor
  -> Paper Review
  -> Checkpoint Report
```

It is acceptable for this version to be local-only. It must not place broker
orders. It must produce clean, completed paper rows that the dashboard and
checkpoint report can count without ambiguity.

The official paper gate is:

```text
30 completed allowed paper trades in logs/paper_review_clean_trades.csv
```

Before 30 completed allowed paper trades:

- Max forward risk stays at `0.50%`.
- No scale-up is allowed.
- B-tier samples can support forward evidence, but A-tier samples are stronger
  live-readiness proof.

## 5. Graduation Checklist: Paper To Small-Size Live

Paper gate checklist:

- At least 30 completed allowed paper trades.
- Paper review rows are clean and reconciled.
- No duplicate official paper trades.
- No unresolved open paper trades from the validation window.
- Average R is positive, or the recommendation is no-go.
- Drawdown is acceptable relative to the rule set.
- Plan adherence is high enough to trust the workflow.
- Data Flow Sentinel has no failed sync checks across the validation window.
- Dashboard and checkpoint report agree on paper count.

Controlled live readiness checklist:

- Global kill switch tested.
- Emergency shutdown tested.
- Max daily loss tested.
- Max trades per day tested.
- Position sizing cap tested.
- Duplicate order prevention tested.
- Broker rejection handling tested.
- Broker disconnect handling tested.
- Order/event logging tested.
- Paper broker or dry-run broker path tested before real money.
- Live mode requires explicit user approval in a future session.

Controlled live first version:

- Smallest practical size only.
- 1 to 2 trades per day maximum.
- Conservative risk cap below or equal to the paper-mode risk cap.
- Stop immediately after any data, broker, or logging exception.
- No strategy expansion during the first live pilot.

## 6. Safety System Audit

| safety system | current status | ship-mode decision |
| --- | --- | --- |
| Kill switch | Missing as a global paper/live block | Required before live; add local kill switch before relying on automated paper writes |
| Max daily loss | Implemented in position sizing for local paper R stops | Keep; test before each release |
| Max trades per day | Partially present in backtest/settings context, not enforced at local paper write time | Required for ship-mode paper writer |
| Position sizing limits | Implemented through `size_ok`, session gates, risk budget, and conservative risk guard | Keep; make it part of the enforced paper write contract |
| Order rejection handling | Missing because no broker orders exist | Required before live broker integration |
| Broker disconnect handling | Missing because no broker connection exists | Required before live broker integration |
| Duplicate order prevention | Implemented for local paper orders/trades with row keys | Keep and test |
| Logging | Broad local report and CSV logging exists | Keep; add broker event logging only when broker work begins |
| Emergency shutdown | Missing as a live execution shutdown system | Required before live |

## 7. Seven-Day Execution Plan

Day 1 - Freeze and enforce the paper contract:

- Keep strategy scope frozen.
- Add or verify a local kill switch for paper ledger writes.
- Add or verify max trades per day at the local paper write point.
- Make official local paper writes require the same readiness contract the
  dashboard displays.

Day 2 - Run market-hours refresh and sync checks:

- Run `python run_current_candle_capture.py` during market hours.
- Confirm scanner, sizing, router, pre-entry review, Paper Gate v2, Options
  Contract Gate, validation import preview, Dashboard Data Preflight, and Data
  Flow Sentinel all come from the same capture pass.
- Enter only candidates that pass the official contract.

Day 3 - Complete and reconcile:

- Monitor open paper trades to completed exits.
- Run paper review and checkpoint report.
- Confirm dashboard, paper review, and checkpoint counts match.

Day 4 - Repeat the paper session:

- Keep the same rules.
- Do not add new strategies to increase count.
- Record every no-trade reason so the blocker is visible.

Day 5 - Midpoint go/no-go:

- If the count is moving, continue.
- If the count is not moving, inspect gate blockers and only adjust workflow
  reliability, not strategy integrity.

Day 6 - End-of-week audit:

- Reconcile completed paper trades.
- Confirm no sync failures or duplicate rows.
- Update the checkpoint report.

Day 7 - Gate decision:

- If 30 completed allowed paper trades exist and review quality is acceptable,
  start the live-readiness safety build.
- If fewer than 30 completed allowed paper trades exist, continue paper mode and
  do not force live.

## Backlog After Ship Mode

- Canonical `dashboard_snapshot.json` for cross-widget run identity.
- Broker paper adapter only after local paper workflow is reliable.
- Live broker adapter only after the paper gate and live safety checklist.
- Strategy expansion after the release path is no longer blocked by workflow
  reliability.
