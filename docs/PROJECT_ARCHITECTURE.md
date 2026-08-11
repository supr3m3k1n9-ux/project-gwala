# Project Gwala Architecture

Last updated: 2026-06-16

This document explains how Project Gwala is wired today. It is intended to be
beginner-readable, but specific enough that future changes can be checked
against the real data flow.

## System Purpose

Project Gwala is a local research, backtesting, and manual paper-validation
platform for chart-first intraday options trading.

The system answers:

- Is there historical evidence for this setup?
- Is today's chart candidate valid enough to review?
- Is the selected options contract clean enough to count as an official
  paper-validation sample?
- Are the dashboard widgets reading synchronized data?
- Are we still safely blocked from live broker execution?

The system does not place live orders, place real-money trades, create broker
execution alerts, or connect to broker order endpoints.

## Architecture Principles

- Research first, paper validation second, live execution later only with
  explicit approval.
- Webull local CSVs are the active market-data path for the dashboard/scanner.
- The dashboard should trust saved JSON/CSV/Markdown outputs, not hidden app
  state.
- Every major workflow should rebuild reports in dependency order.
- Data freshness and sync status must be visible before candidates are trusted.
- Historical research rows, shadow samples, forward observations, validation
  samples, and official paper trades are separate evidence types.

## Top-Level Layers

```text
Market Data
  -> Candle Cache / CSV Files
  -> Indicators + Strategy Scanners
  -> Position Sizing + Router + Pre-Entry Review
  -> Paper Gate v2 (A/current + B/one-M30 grace)
  -> Options Contract Gate v1
  -> Validation Sample Import
  -> Paper Review / Progress
  -> System State + Dashboard Preflight + Data Flow Sentinel
  -> Local Dashboard
```

## Important Directories

| path | purpose |
| --- | --- |
| `app/` | Browser dashboard UI. Reads app-facing JSON and report endpoints. |
| `backtesting/` | Candle replay and trade simulation helpers. |
| `config/` | Settings, market calendar, symbol playbook, and strategy registry. |
| `data/` | Local ledgers and manually maintained inputs. |
| `docs/` | Living source-of-truth documentation. |
| `indicators/` | VWAP, EMA, session, opening-range, and timeframe helpers. |
| `logs/` | Generated reports, JSON snapshots, CSV outputs, and candle files. |
| `reports/` | Shared app-state and report-building helpers. |
| `risk_management/` | Risk and sizing support. |
| `strategies/` | Strategy signal logic and scanner adapters. |

## Active Data Provider Path

Current active provider:

```text
Webull market-data-only CSV refresh
```

Core behavior:

- `run_webull_watchlist.py` refreshes or reuses local candle CSVs.
- `run_current_candle_capture.py` is the fast market-hours command for catching
  A/current candidates and one-M30 B/grace candidates while they are still
  eligible for paper validation.
- `run_daily_workflow.py --refresh-data --data-provider webull` remains the
  broader full-report rebuild command.
- Provider output is saved in `logs/` and the provider-neutral candle cache.
- Webull is used for market data only. It is not used for broker execution.

Known provider guardrail:

- Webull can occasionally return stale M30 rows while M5 rows are current.
- `run_repair_m30_from_lower_timeframe.py` can rebuild M30 candles from lower
  timeframe data.
- `run_data_flow_sentinel.py` reports this as `watch` with `repair_applied`
  instead of silently treating it as perfect.

## Strategy Architecture

Current strategy families:

- VWAP + EMA Trend Continuation.
- VWAP Mean Reversion.
- Gap Fill / Gap Fade.
- VWAP Reclaim / Reject.
- Opening Range Breakout.
- Trend Pullback Continuation.
- Opening Range Failure.

The Strategy Vault keeps a broad research net, but paper-readiness is gated.
Research strategies can produce backtests, shadow samples, and forward
observations without becoming official paper evidence.

Key files:

| file | role |
| --- | --- |
| `config/symbol_playbook.py` | Approved/watch symbol and setup definitions. |
| `config/strategy_registry.py` | Strategy IDs, chart markers, router/report contracts. |
| `strategies/scanner_adapters.py` | Maps playbook entries to strategy-specific signal columns. |
| `run_strategy_vault.py` | Builds Strategy Vault status/report. |
| `run_market_regime_router.py` | Routes current scanner rows by market regime. |
| `run_paper_activation_rules.py` | Keeps research lanes separate from paper-ready lanes. |

## Current-Candle Capture Workflow

The market-hours fast path is:

```bash
python run_current_candle_capture.py
```

High-level order:

1. Refresh or reuse Webull candle files.
2. Record refresh/provider audit information.
3. Run daily scanner.
4. Run position sizing.
5. Rebuild Strategy Vault and paper activation context.
6. Run Market Regime Router.
7. Run Pre-Entry Review.
8. Build Paper Entry Packet.
9. Run Paper Gate v2.
10. Run Options Contract Gate v1.
11. Run Validation Sample Import preview.
12. Run DAILY_SHIP_REPORT.
13. Run Filter Rejection Report.
14. Run Historical Bucket Sync.
15. Rebuild System State.
16. Run Dashboard Data Preflight.
17. Run Data Flow Sentinel.
18. Rebuild final System State.

Purpose:

- Preserve strict freshness: A-tier is `current_candle`; B-tier is only the
  immediately prior M30 candle with a refreshed current-candle plan.
- Avoid using the slower full daily workflow as the market-hours scan loop.
- Create `logs/current_candle_capture.json` and
  `logs/current_candle_capture.md` so the first zero-count bottleneck is visible.
- Create `logs/DAILY_SHIP_REPORT.md` so stage-by-stage drop-offs are visible
  after every scan.

The intraday loop, autonomous paper workflow, and accelerated paper-validation
loop use this command for market-hours scans.

## Automation / LaunchAgent Architecture

The durable market-refresh scheduler is the macOS user LaunchAgent:

```text
launchd/com.project-gwala.autonomous-paper.plist
```

Installed location:

```text
~/Library/LaunchAgents/com.project-gwala.autonomous-paper.plist
```

The LaunchAgent runs:

```bash
.venv-webull/bin/python run_autonomous_paper_workflow.py --interval-minutes 5 --auto-confirm-paper-exits --once
```

Runtime contract:

- The LaunchAgent uses scheduled one-shot runs instead of one all-day shell
  loop.
- Pre-market verification runs before the open.
- Market-hours scheduled runs call the A/current + B/grace capture workflow.
- After-close recap runs after the regular session.
- `PYTHONUNBUFFERED=1` keeps launchd logs readable while a scan is in progress.
- This automation is local research/paper validation only. It does not place
  broker orders, create broker alerts, import new paper entries, or enable live
  execution.

Important operational note:

```text
launchctl list | grep com.project-gwala.autonomous-paper
```

A `0` last-exit code means the last scheduled run completed cleanly. A running
PID means launchd is currently executing a scheduled one-shot scan.

## Current Daily Workflow

The broader full rebuild workflow is:

```bash
python run_daily_workflow.py --refresh-data --data-provider webull
```

High-level order:

1. Optionally refresh market data.
2. Record refresh/provider audit information.
3. Run daily scanner.
4. Run near-miss, observations, integrity, and review reports.
5. Run position sizing.
6. Run pre-entry review and paper entry packet.
7. Run Paper Gate v2.
8. Run Options Contract Gate v1.
9. Run Validation Sample Import preview.
10. Run paper execution simulator and open paper monitor in local-only mode.
11. Rebuild research, Strategy Vault, router, setup health, and milestone
    reports.
12. Rebuild system state.
13. Run dashboard data preflight.
14. Run Data Flow Sentinel.
15. Rebuild final system state.

The final validation/sync chain must remain:

```text
Paper Gate v2 (A/current + manual B/grace)
  -> Options Contract Gate v1
  -> Validation Sample Import
  -> DAILY_SHIP_REPORT
  -> Filter Rejection Report
  -> Historical Bucket Sync
  -> System State
  -> Dashboard Data Preflight
  -> Data Flow Sentinel
  -> Final System State
```

## Dashboard Architecture

Main files:

| file | role |
| --- | --- |
| `run_app.py` | Local HTTP server and report endpoints. |
| `app/index.html` | Dashboard shell. |
| `app/app.js` | Dashboard state/rendering logic. |
| `app/styles.css` | Dashboard styling. |

The dashboard reads:

- `logs/system_state.json` for Home and core app state.
- `logs/*.md` and `logs/*.csv` through allowlisted report endpoints.
- Local candle CSVs for chart/workspace views.
- Historical simulation endpoints from generated backtest and Strategy Vault
  trade logs.

Important dashboard rule:

```text
The dashboard should display what the saved app-facing reports say. It should
not invent trading state that was not produced by the workflow.
```

## App-Facing State Contract

Primary app snapshot:

```text
logs/system_state.json
```

Generated by:

```bash
python run_system_state.py --output-dir logs
```

The snapshot summarizes:

- Market status.
- Refresh status.
- Data Flow Sentinel status.
- Strategy Vault status.
- Current candidates.
- Forward sample queue.
- Paper progress.
- Risk guard.
- Setup health.
- Historical backtest performance.
- Source file states.

The dashboard should treat `system_state.json` as the main source of truth for
Home-level status, while detailed reports remain available through report
endpoints.

## Sync Guardrails

### Dashboard Data Preflight

Command:

```bash
python run_dashboard_data_preflight.py --output-dir logs
```

Purpose:

- Verify strict browser-safe JSON.
- Check refresh status exists.
- Check provider/candle freshness during market hours.
- Catch JSON parse problems before the UI gets stuck loading.

### Data Flow Sentinel

Command:

```bash
python run_data_flow_sentinel.py --output-dir logs
```

Purpose:

- Verify scanner, sizing, router, pre-entry, and system state agree.
- Verify the dashboard preflight passed.
- Verify provider/session evidence is stable or clearly marked as repaired.
- Verify the validation gate sequence is internally consistent.
- Surface historical bucket sync as a `pass` or `warn` so stale research lanes
  do not masquerade as fully current historical evidence.

The validation gate sequence check compares:

- `logs/paper_gate_v2.json`
- `logs/options_contract_gate.json`
- `logs/paper_validation_sample_import.json`

It checks counts, statuses, missing reviews, blocked contracts, and file order.

## Paper Validation Architecture

There are multiple evidence levels. They must not be blended.

| evidence type | counts toward official 30 paper trades? | notes |
| --- | --- | --- |
| Historical backtests | no | Research context only. |
| Strategy Vault research rows | no | Useful for strategy study. |
| Shadow samples | no | Forward-observed, not official paper trades. |
| Forward observations | no | Shows what was observed, not necessarily taken. |
| Validation samples | not by themselves | Manual options-ready samples awaiting outcome. |
| Completed allowed paper trades | yes | Official progress toward 30/60 gates. |

## Current Candidate Gate Chain

```text
Scanner row
  -> Position sizing
  -> Market regime router
  -> Pre-entry review
  -> Paper entry packet
  -> Paper Gate v2
  -> Options Contract Gate v1
  -> Validation sample import preview/confirm
```

Important files:

| file | role |
| --- | --- |
| `run_current_candle_capture.py` | Fast market-hours capture pass for A/current and B/one-M30 grace paper-validation candidates. |
| `run_daily_scanner.py` | Builds scanner rows from the current symbol/playbook universe. |
| `run_position_sizer.py` | Adds local research/paper sizing context. |
| `run_pre_entry_review.py` | Reviews A/current, B/grace, and study-only earlier-today candidates. |
| `run_paper_entry_packet.py` | Creates local A/current entry packets; B/grace never receives an entry command here. |
| `run_paper_gate_v2.py` | Splits A/B/C validation sample readiness. |
| `run_options_contract_gate.py` | Blocks official samples until contract quality passes. |
| `run_paper_validation_sample_import.py` | Imports contract-passed samples only with confirmation. |
| `run_filter_rejection_report.py` | Counts which safety, quality, and experimental filters rejected candidates. |

## Filter Policy Architecture

Ship mode separates filters into three classes:

| class | behavior |
| --- | --- |
| Safety-critical | Strict. These protect capital, data freshness, sizing, duplicate prevention, and future broker integrity. |
| Trade-quality | Configurable. These include trend, regime, volume, spread, liquidity, and time-of-day thresholds. |
| Experimental | Disabled by default. These include weakness overlays, options-flow, gamma, and advanced confirmation stacking. |

Current policy source:

```text
config/filter_policy.py
```

Daily rejection report:

```text
logs/filter_rejection_report.md
logs/filter_rejection_audit.csv
logs/filter_rejection_summary.csv
logs/filter_policy_audit.csv
logs/filter_thresholds.csv
```

Important rule:

```text
If a filter can block paper validation, it should be visible in the rejection
report or documented as intentionally out of scope.
```

## Options Contract Gate v1

Input:

```text
data/options_contract_audit.csv
```

Output:

```text
logs/options_contract_gate.json
logs/options_contract_gate.csv
logs/options_contract_gate.md
logs/options_contract_gate_template.csv
```

V1 checks:

- Option type matches chart direction.
- Absolute delta between `0.40` and `0.70`.
- Bid/ask spread at or below `15%`.
- Volume at least `100`.
- Open interest at least `500`.
- DTE from `0` to `5`.
- Strike, premium, bid, and ask are valid.
- Earnings window is not active.

This gate is manual and local. It does not fetch option chains, create broker
alerts, place paper broker orders, or place real orders.

## Historical Simulation Architecture

Historical simulation is for research context only.

It can include:

- Approved Playbook rows.
- Promotion Review rows.
- Strategy Vault Research rows.

The dashboard keeps these labeled so they do not look like official paper
trades.

Historical bucket sync command:

```bash
python run_historical_bucket_sync.py --output-dir logs
```

Outputs:

```text
logs/historical_bucket_sync.json
logs/historical_bucket_sync.md
```

The sync guardrail compares each bucket's latest trade date to the latest
scanner session and reports:

- `synced`: every required bucket reaches the latest scanner session.
- `watch`: the unified simulator may be current, but one or more buckets are
  behind and should be treated as older research context.
- `blocked`: required historical simulator inputs are missing or unreadable.

The fast market-hours capture path runs this as an audit only. The broader
daily workflow runs it after research reports have been rebuilt.

Important distinction:

```text
Historical Simulation Account and Historical Simulated Trade History should
read from the same full row set.
```

This prevents the chart, account cards, monthly bars, and trade table from
showing different historical datasets.

## Local Paper Trade Architecture

Official paper progress currently comes from local manual review, not broker
execution.

Important files:

| file | role |
| --- | --- |
| `data/paper_trades.csv` | Local paper trade ledger. |
| `logs/paper_review_clean_trades.csv` | Reviewed clean paper trades. |
| `run_paper_execution_simulator.py` | Local preview/confirmed paper entry helper. |
| `run_open_paper_monitor.py` | Local open paper trade exit monitor. |
| `run_paper_review.py` | Reviews completed local paper trades. |
| `run_checkpoint_report.py` | Tracks 30/60-trade checkpoints. |

Safety boundary:

```text
Local paper helper scripts may write local CSV ledgers when explicitly
confirmed. They must not call broker order endpoints.
```

## Report Registry

`run_app.py` uses an allowlist called `ALLOWED_REPORTS`.

Only allowlisted reports should be served through the dashboard. This keeps the
local app from exposing arbitrary files.

When adding a new dashboard report:

1. Generate JSON/CSV/Markdown output under `logs/`.
2. Add the report to `ALLOWED_REPORTS` if the UI needs to open it.
3. Add source-file state to `reports/system_state.py` if Home or System needs
   to know whether it exists.
4. Add wiring checks to `run_feature_wiring_audit.py` or
   `run_data_flow_sentinel.py` when the report affects trust.
5. Add tests in `tests/test_workflow_safety.py`.

## Safety Boundaries

Never add these without explicit future approval after validation is complete:

- Live Webull execution.
- Broker order placement.
- Real-money trading.
- Automated trade execution.
- Broker alerts that imply execution.
- Martingale logic.
- Averaging down losers.
- Revenge-trade behavior.
- Overleverage.
- Stop-loss removal.

Approved automation for the current phase:

- Market-data refresh.
- Report rebuilds.
- Dashboard state refresh.
- Local-only paper ledger previews.
- Explicitly confirmed local CSV updates for paper validation.

## Adding New Features Safely

Use this checklist for future architecture changes:

1. Read the living docs first:
   - `docs/PROJECT_STATE.md`
   - `docs/gwala-doctrine.md`
   - `docs/trading-philosophy.md`
   - `docs/strategy-vault.md`
   - `docs/PROJECT_ARCHITECTURE.md`
2. Decide whether the change affects doctrine, philosophy, strategy, roadmap,
   architecture, risk, or backlog.
3. Update the relevant doc with a dated entry.
4. Keep the feature research/paper-only unless explicitly approved otherwise.
5. Add or update generated reports under `logs/`.
6. Wire report visibility through the app allowlist only when needed.
7. Add sync checks if the feature affects dashboard trust.
8. Add tests before relying on the new workflow.
9. Run dashboard preflight and Data Flow Sentinel after changing data flow.

## Current Refactor Guidance

Do not do a broad architecture rewrite just because the project has many files.

Prefer targeted refactors when they:

- Remove duplicated command ordering.
- Make data contracts easier to audit.
- Prevent stale report outputs.
- Keep dashboard widgets synchronized.
- Preserve the fast path to official paper validation.

Current highest-value future architecture improvement:

```text
Create a canonical dashboard_snapshot.json so Home, Paper Progress,
Historical Simulation, Candidates, and System can prove they came from the
same workflow snapshot.
```

## Dated Entries

### 2026-06-15 - Architecture Source Of Truth Added

What changed:

- Created this architecture document as the source map for Project Gwala's
  current implementation.
- Captured the active data path, dashboard state contract, validation gate
  sequence, sync guardrails, paper-validation boundary, and safety limits.

Why it changed:

- Recent changes added more moving parts around Strategy Vault, Paper Gate v2,
  Options Contract Gate v1, validation import, dashboard preflight, and Data
  Flow Sentinel. The project needs one readable architecture map to prevent
  future wiring drift.

Assumptions:

- The current architecture is workable and should be hardened, not rewritten.
- The fastest path to market is better sync visibility and safer paper
  validation, not new live-execution plumbing.

Implementation impact:

- This document does not change runtime behavior.
- Future architecture changes should update this document in the same work
  session.

### 2026-06-15 - Filter Rejection Architecture Added

What changed:

- Added `config/filter_policy.py` and `run_filter_rejection_report.py` to the
  architecture map.
- The daily workflow now reports safety-critical, trade-quality, and
  experimental filter rejections.

Why it changed:

- The paper gate can be blocked by many small filters. The project needs a
  normalized report showing which filters are starving candidates before
  thresholds are changed.

Assumptions:

- Safety filters stay strict.
- Quality filters should be tunable after seeing rejection counts.
- Experimental filters should be disabled by default in ship mode.

Implementation impact:

- Workflow runs should rebuild `logs/filter_rejection_report.md` after Paper
  Gate v2, Options Contract Gate, and validation sample preview.
