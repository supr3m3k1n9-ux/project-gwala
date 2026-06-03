# Project Gwala App Manual

This manual explains how to open and navigate the Project Gwala dashboard.

The app is for research, backtesting, and paper validation only. It does not
place orders, create broker alerts, import paper entries automatically, or
connect to broker execution. Local paper exits can be auto-recorded when saved
5m candles hit the paper stop, target, or end-of-day rule.

## Quick Start

The dashboard server is already set up to run in the background with macOS
LaunchAgent:

```text
com.project-gwala.dashboard
```

Open the dashboard one of two ways:

```text
Double-click Project Gwala Dashboard.app
```

or open this URL:

```text
http://127.0.0.1:8765
```

The desktop app is just a convenient launcher. The actual dashboard server runs
in the background.

## Start, Stop, And Status

Check whether the dashboard background service is running:

```bash
launchctl print gui/$UID/com.project-gwala.dashboard
```

Start or reinstall the dashboard auto-start:

```bash
bash scripts/install_dashboard_launch_agent.sh
```

Stop and remove the dashboard auto-start:

```bash
bash scripts/uninstall_dashboard_launch_agent.sh
```

Dashboard logs:

```text
logs/dashboard.launchd.out.log
logs/dashboard.launchd.err.log
```

## Important Daily Context

The dashboard reads saved files from `logs/` and `data/`. It is not a live
broker terminal.

Use `Home` in the side menu to return to the main dashboard overview. Each
side-menu item opens as its own page so the app does not jump down one long
mixed dashboard.

During market hours, the autonomous paper workflow updates scanner data,
position sizing, reports, and system state. The dashboard shows the latest
saved results. The LaunchAgent starts the supervisor before the regular
session; the supervisor then loops every 5 minutes while the market is open and
exits after the close.

Current local schedule:

```text
6:15 AM PT = start supervisor and run pre-market check
6:30 AM-1:00 PM PT = market scan every 5 minutes
After 1:00 PM PT = after-close recap, then supervisor exits
```

Existing local paper trades are also checked for paper exit conditions during
market scans.

The morning watchdog tells you whether the scheduled run actually happened
today. After the first 6:30 AM PT market scan has had a few minutes to finish,
check the Home automation card or Reports -> Daily Workflow -> Morning
Watchdog. It should answer:

```text
Did the autonomous workflow write status today?
Did the market scan run today?
Was today's Webull refresh confirmed?
Is the scanner using today's session?
How many current/reviewable candidates exist?
What is the next action?
```

If it says `pending`, the first scan is not due yet. If it says `warn` after
6:35 AM PT on a regular session, keep the laptop awake and use Refresh Webull
Data from the dashboard.

The Home page now has a `Candle Age` warning. During market hours, use it as a
freshness brake before reviewing paper candidates:

```text
5m candles older than 10 minutes = refresh before exit/paper review
30m candles older than 40 minutes = refresh before entry/paper review
```

The workflow auto-start service is:

```text
com.project-gwala.autonomous-paper
```

Check it with:

```bash
launchctl print gui/$UID/com.project-gwala.autonomous-paper
```

Key status files:

```text
logs/autonomous_paper_workflow_status.md
logs/autonomous_paper_workflow_status.json
logs/morning_run_watchdog.md
logs/morning_run_watchdog.json
logs/daily_automation_timeline.md
logs/daily_automation_timeline.json
```

The Mac must be awake and your user account must be logged in for user
LaunchAgents to run.

## Top Bar

### Refresh

The `Refresh` button reloads the latest saved dashboard state from:

```text
logs/system_state.json
```

Use this after the background workflow finishes a scan. It does not fetch new
market data by itself.

## Sidebar Navigation

The left sidebar opens each dashboard page:

```text
Trading Workspace
Near-Miss Analytics
Investment Narrative
Research
System
Sample Queue
Candidates
Trade Logger
Paper Progress
Setup Health
Practice Replay
Reports
```

## Strategy Vault

The Strategy Vault is the research router. It compares the current broad-market
backdrop with the strategy families in the vault and recommends where attention
belongs:

```text
active = existing paper-watch strategy is favored by the current regime
watch = strategy is usable only if the normal scanner/sizing gates are perfect
caution = strategy is not favored; stand aside unless the setup is unusually clean
research_priority = build or test this strategy next
research_backlog = keep it in the vault, but do not prioritize it today
```

Open the full report from:

```text
Reports -> Research -> Strategy Vault
```

The evidence accumulation status is available from:

```text
Reports -> Research -> Strategy Evidence Accumulator
```

Use this report to confirm whether the market-hours workflow is collecting
generic forward observations, generic shadow samples, and strategy-specific
mean-reversion evidence. It also marks research strategies that do not yet have
their own forward evidence lane.

The research-to-paper-watch activation contract is available from:

```text
Reports -> Research -> Paper Activation Rules
```

Use this report to see the exact requirements before any research strategy can
graduate into manual paper-watch review: strategy-specific gate, tightened
backtest pass, walk-forward pass, shadow evidence, and forward observation
evidence. Passing still means manual paper validation only, not live trading.

The vault does not approve trades, import paper entries, place orders, create
broker alerts, or bypass the paper gate. It only helps decide which strategy
family deserves research or manual paper-review attention.

### Opening Range Breakout

Opening Range Breakout is the vault's first pure momentum-open strategy. It
tests whether price can expand through the opening range while aligned with
VWAP and the 9/21 EMA structure.

```text
Reports -> Research -> Opening Range Breakout
logs/opening_range_breakout.md
```

The research pass tests long breaks above the opening-range high and short
breaks below the opening-range low. It uses 30m candles for entries, 5m candles
for exits, a fixed R target, and a stop around the signal candle or opening
range extreme. This is research only; it does not create paper trades, broker
orders, or live alerts.

### Trend Pullback Continuation

Trend Pullback Continuation is the vault's second-chance trend strategy. It
studies entries after a move is already underway, when price pulls back into
the 9/21 EMA area and then closes back in the direction of VWAP and the larger
trend.

```text
Reports -> Research -> Trend Pullback Continuation
logs/trend_pullback_continuation.md
```

The research pass tests long pullbacks above VWAP and EMA 200, plus short
pullbacks below VWAP and EMA 200. It uses 30m candles for entries, 5m candles
for exits, a fixed R target, and a stop around the signal candle or EMA 21.
This is research only; it does not create paper trades, broker orders, or live
alerts.

### Strategy Selector

The Strategy Vault page now includes a Strategy Selector at the top of the
page. It separates:

```text
Paper-Watch Strategy = the only strategy family allowed to reach manual paper review
Research Focus = the strategy family worth building or studying next
Selector Rule = what the app allows today
Blocked Research = research-only strategies that cannot be paper-traded yet
```

If a research strategy fits the current regime better than the active strategy,
the selector may prioritize it for research. That still does not make it
paper-watch eligible. A strategy needs its own evidence and promotion gate
before it can move from research-only into paper-watch review.

### VWAP Mean Reversion

VWAP Mean Reversion is the first complementary vault strategy. It studies
range/chop sessions where price stretches away from VWAP and rejects the
extreme back toward the mean.

Open the report from:

```text
Reports -> Research -> VWAP Mean Reversion
```

The next evidence layer is the walk-forward report:

```text
Reports -> Research -> VWAP Mean Reversion Walk-Forward
```

Walk-forward splits each promising row into older trades and newer trades. A
`holding_up` decision means the newer half still meets the early durability
floor. It is a good sign, but it is still not paper-watch approval by itself.

The forward-style shadow lane is available from:

```text
Reports -> Research -> VWAP Mean Reversion Shadow Samples
```

This report collects recent-window mean-reversion samples when the saved data
passes the strategy-specific filters. These samples stay separate from the
generic near-miss shadow lane and from official paper trades.

The collector scans a recent M30 candle window during each market-hours
workflow run, not only the single latest candle. This reduces missed samples
when a qualifying mean-reversion setup appeared earlier in the current session.
Rows append only when the saved candles are fresh for the open market session.

The strategy-specific forward observation lane is available from:

```text
Reports -> Research -> VWAP Mean Reversion Forward Observations
```

This report preserves qualifying recent-window mean-reversion signals as
forward observations. These observations are closer to paper-watch evidence
than historical backtests, but they still do not count as official paper trades.

Like the shadow lane, the forward-observation lane now scans a recent M30
window and dedupes by symbol, direction, signal, and entry time.

The paper-watch gate is available from:

```text
Reports -> Research -> VWAP Mean Reversion Paper-Watch Gate
```

This report says whether the strategy is ready for manual paper-watch review.
It checks tightened backtests, walk-forward stability, strategy-specific shadow
samples, and strategy-specific forward observations. A passing gate still does
not place orders or enable live trading.

The Strategy Vault page also shows the gate as dashboard cards:

```text
Strategy Vault -> Strategy Promotion Gate
```

Use those cards for the quick answer: gate decision, next blocker, shadow
evidence, and forward observation evidence.

This strategy is backtest/research only until it has enough evidence,
walk-forward stability, shadow samples, and forward paper-validation results.

### Opening Range Failure

Opening Range Failure is the first failed-breakout vault strategy. It studies
sessions where price breaks the opening range, fails to hold that breakout, and
reverses back toward VWAP or the opening-range midpoint.

Open the report from:

```text
Reports -> Research -> Opening Range Failure
```

This report is research-only. It helps decide whether failed opening-range
breakouts deserve deeper testing, walk-forward checks, shadow samples, or
forward observations. It does not approve paper trades or broker execution.

## Home Backtest Account View

The Home page includes a Backtest Performance Snapshot. Click `View trades` on
a backtest row to open its historical simulated trade log.

The simulated account controls let you test a paper-account model such as:

```text
Starting account: 5000
Risk per trade %: 0.5
```

The app compounds risk from the simulated account balance after each historical
trade. It shows ending account value, total P/L, return, drawdown, win rate,
average R, best/worst trade, loss streak, and exit pattern context. This is
historical simulation only; it is not a broker account and does not approve live
or real-money trading.

The Paper Progress page separates two accounts:

```text
Forward Paper Account = actual logged paper trades only
Historical Simulation Account = promoted historical backtest trades only
```

Both use the same starting-account and risk-percent model so you can compare
forward paper progress against the historical simulation without mixing them.
Both accounts show date context when trades are available. The historical
simulation shows first trade date, last trade date, active trade dates, active
months, and monthly P/L bars.

The Historical Simulation Account can use either fixed risk or tiered setup
risk. Tiered risk is based on objective promotion evidence:

```text
Standard = base risk
Strong = 1.5x base risk, capped at 1.5%
Best-tier = 2x base risk, capped at 2%
```

The tiered model requires stronger readiness score, expectancy, win rate, and
drawdown conditions. It is research sizing only, not permission to raise real
money risk.

Forward paper risk is guarded separately from historical simulation risk. Until
the Forward Paper Account reaches the first validation gate, the app caps
forward paper scale guidance at normal risk:

```text
0-29 allowed completed paper trades = max 0.5% forward paper risk
30-59 allowed completed paper trades = max 0.75% forward paper risk
60+ allowed completed paper trades = max 1.0% forward paper risk
```

This keeps strong-looking setups from encouraging premature scale-up before the
system has enough live forward paper evidence.

## Notification Layer

The Home page has a local notification panel for paper workflow alerts.

Use `Enable alerts` after opening the dashboard. Browsers usually block sound
until you click something, so alerts must be enabled once per browser session.

The notification layer watches for:

```text
Entry alert = a new current-candle candidate becomes ready for manual review
Exit alert = an open local paper row is closed after a local paper outcome is logged
```

It does not place orders, close orders, or connect to a broker.

Sound files live here:

```text
app/assets/entry-alert.wav
app/assets/exit-alert.wav
```

Upload your preferred entry and exit sounds as `.mp3`, `.wav`, or `.ogg`. If
the filenames or format are different, update the matching audio path in
`app/index.html`.

## System State Panel

The `State` panel lives under the System side-menu page. It is the dashboard's
top-level verdict.

It shows:

```text
project phase
readiness verdict
safety status
warning badges
```

Good things to look for:

```text
Research and paper validation phase
Fresh data for today during market hours
Live trading disabled
Broker order execution disabled
Real money ready = false
```

If the dashboard says data is stale or outside market hours, do not treat any
candidate as actionable.

## Research

The Research side-menu page combines broad research confidence, promotion
review, and forward evidence.

### Research Confidence

This panel summarizes broad-universe backtests from:

```text
logs/universe_expansion/research_confidence.csv
logs/universe_expansion/research_confidence.md
```

Use it to find symbols and setups worth deeper review. `Research ready` means
review and forward paper validation next. It does not mean real-money ready.

To rebuild the broader research pass:

```text
python run_research_expansion.py --universe liquid_options --reuse-csv
```

Leave the approved scanner/playbook separate until a setup has enough backtest
and forward paper evidence.

For deeper provider history that was exported to CSV, import each timeframe
into the local candle cache first:

```text
python run_import_candles_csv.py --symbol SPY --timeframe M30 --source-csv data/SPY_30m.csv --output-dir logs/external_history
python run_import_candles_csv.py --symbol SPY --timeframe M5 --source-csv data/SPY_5m.csv --output-dir logs/external_history
python run_webull_watchlist.py --symbols SPY --reuse-csv --output-dir logs/external_history --candidate-preset best_plus_market
```

The importer accepts common vendor headers such as `Date`, `Open`, `High`,
`Low`, `Close`, and `Vol`, then saves the normalized files where the existing
backtest runner expects them.

### Promotion Review

This panel is the checkpoint between broad research and active paper watch.

It reads:

```text
logs/promotion_review.csv
logs/promotion_review.md
```

Focused deeper-history candidate checks live here and are available from the
Reports tab as Deep Research and Deep Promotion:

```text
logs/deeper_research/research_confidence.md
logs/deeper_research/promotion_review.md
```

The controlled and walk-forward tests are available in the Reports tab too:

```text
logs/controlled_variant_review.md
logs/walk_forward_review.md
logs/vwap_mean_reversion_walk_forward.md
logs/vwap_mean_reversion_shadow_samples.md
logs/vwap_mean_reversion_forward_observations.md
logs/vwap_mean_reversion_paper_watch_gate.md
logs/opening_range_breakout.md
logs/trend_pullback_continuation.md
logs/opening_range_failure.md
logs/strategy_evidence_accumulator.md
logs/paper_activation_rules.md
logs/regime_review.md
logs/deeper_research/controlled_variant_review.md
logs/deeper_research/walk_forward_review.md
logs/deeper_research/regime_review.md
```

Use Controlled Variants to see whether a filter improved its matching baseline.
Use Walk Forward to see whether the newer half of the trade log is still
working. Use Regime Review to see whether a setup works best when SPY is
bullish, bearish, choppy, high-volatility, or low-volatility.

Use it to avoid adding noisy setups to the scanner. A `Paper watch candidate`
means the setup is eligible for manual forward paper validation only. It does
not mean live trading, broker execution, or real-money readiness.

To rebuild it:

```text
python run_promotion_review.py
```

## Key Metrics

The metric tiles summarize the current operating state.

### Market

Shows whether the market is open, closed, before open, or after close.

### Data

Shows whether scanner data is fresh for today's session.

### Paper Gate

Shows progress toward the paper-validation checkpoints:

```text
30 allowed completed paper trades = first useful checkpoint
60 allowed completed paper trades = stronger checkpoint
```

### Setup Health

Shows how many approved setups need attention based on backtest/playbook
health.

### Pre-Market Gate

Shows whether pre-market checks passed and whether the previous Webull
data-only probe is still recognized.

## Trading Workspace

The Trading Workspace is a read-only review panel built from saved Webull
market-data candles.

It includes:

```text
Approved universe watchlist
5m / 30m chart toggle
VWAP overlay
EMA 9, EMA 21, EMA 200 overlays
Opening range lines
Signal markers from the stored scanner session
Paper ticket summary
Setup readiness radar
```

### Watchlist

Click a symbol in the approved universe list to change the chart.

Only symbols in the approved paper-validation universe are shown.

### 5m / 30m Buttons

Use `5m` for exit-management style review.

Use `30m` for entry-signal structure.

The Trading Workspace shows a candle freshness banner under the chart. If it
says the selected chart is stale, refresh Webull data before paper review.

### Paper Ticket

The ticket is review-only.

It fills in when the latest scanner has a current candidate for the selected
symbol. It may show:

```text
entry
stop
target
shares
status
setup coverage
```

The order button is disabled on purpose.

### Setup Readiness Radar

This explains which setup rules are passing or missing for the selected
symbol.

It is explanation only. It does not create a signal, approve a trade, or change
position sizing.

## Near-Miss Analytics

Near-Miss Analytics explains what blocked setups that were close but not ready.

It shows:

```text
most frequent blockers
latest closest setups
number of blocker rows
evidence basis
```

Use this after a scan when there are no valid paper candidates. It helps answer
questions like:

```text
What condition keeps blocking trades?
Which symbols were closest?
Are we missing VWAP, opening range, relative volume, or thesis alignment?
```

Near-miss rows are not trades and not signals.

The Missed Opportunity Tracker on this page follows almost-ready rows. It does
not invent a trade result for a blocked setup. Instead, it checks whether that
same symbol/setup/direction later became an allowed forward observation. If the
later allowed observation matures, the tracker shows its hypothetical R result.

## Investment Narrative

This panel shows long-term research context for the selected chart symbol.

It may include:

```text
symbol summary
long-term thesis focus
monitoring themes
future source connection slots
review questions
```

It is deliberately separate from the VWAP/EMA trading system.

Do not use narrative context to override scanner rules, stops, sizing, or paper
eligibility.

## App Health Panel

The App Health panel lives under the System side-menu page. It shows freshness
timestamps for important source files and reports.

Use it to check whether key files are present and recently updated.

Examples:

```text
system_state.json
dashboard report
scanner report
position sizing
setup replay
near-miss analytics
```

If a file says missing or stale, run the appropriate workflow before relying on
that section.

## System

The System side-menu page combines state diagnostics, app health timestamps,
signal workflow controls, and app scaffold file links.

The workflow panel summarizes scanner and data workflow status. It also has
local workflow buttons.

### Update Refresh Status

This rebuilds local readiness/status reports only.

It does not:

```text
fetch Webull data
import paper trades
place orders
enable live trading
```

Use it when you want the dashboard to recalculate whether the current saved
data is fresh or stale.

### Run Local Pre-Market Check

This rebuilds local pre-market readiness reports.

It checks things like:

```text
candle integrity
refresh status
readiness
safety flags
system state
```

It does not run a Webull market-data probe. The Webull probe remains a separate
terminal command.

## Guardrails

The Guardrails panel confirms safety controls.

The expected safe state is:

```text
live trading disabled
broker order execution disabled
real money ready false
paper import blocked unless a manually reviewed current-candle candidate exists
```

If these do not look safe, stop and investigate before using the workflow.

## Current-Candle Candidates

This section shows paper-review candidates from the latest scanner state.

A row is only potentially actionable for paper review when:

```text
market is open
data is fresh for today
signal freshness is current_candle
scanner status is allowed
position sizing says size_ok
checklist passes
```

Watch-only and not-ready rows are not paper entries.

If the section is empty, the correct action is usually to wait, observe, and
study near-misses or replay cards.

### Forward Evidence

Forward Evidence summarizes observed hypothetical scanner results.

These are preserved observations, not paper trades.

It tracks:

```text
fresh signal observations
matured hypothetical outcomes
allowed average R
watch/blocked average R
data integrity warnings
```

Use this to learn from the scanner during live sessions even when no paper
trade was taken.

## Paper Progress Visualization

This section tracks reviewed paper trades and the local paper outcomes recorded
against them.

It shows:

```text
Forward Paper Account for actual logged paper P/L
Historical Simulation Account for promoted backtest P/L
progress to 30-trade checkpoint
progress to 60-trade checkpoint
cumulative R
allowed vs watch-only breakdown
plan adherence breakdown
```

If there are no completed paper trades yet, it will correctly show zero
progress.

The Home `Session Readiness` panel also shows the active Risk Guard. If it says
`0.50% max`, scale-up is still locked until enough completed forward paper
trades are logged.

## Paper Trade Logging Workflow

All logged paper trades are local records. They do not place broker orders, do
not close broker orders, and do not import real brokerage activity.

Entries still require review. Use this workflow when you want Codex or the
dashboard to handle local entry logging:

```text
1. Open Home.
2. Check Today's Command Center for the next safe action.
3. If data is stale, use Refresh Webull Data.
4. Open Candidates or Trading Workspace.
5. Review any current-candle candidate manually.
6. Open System.
7. Run paper preview.
8. If the preview is correct, run Confirm local paper entry.
9. Check Paper Progress.
```

Exit discipline is automated for the local paper account while the autonomous
workflow is active. Every market-hours scan checks open local paper trades
against saved Webull 5m candles. If price hits the paper stop, paper target, or
end-of-day exit rule, the app records the local paper exit outcome for you.

That exit automation only updates `data/paper_trades.csv`. It does not close a
Webull trade, submit an order, or connect to broker execution.

You can still use Trade Logger when you want to add notes, fix a manually
observed paper outcome, or review why an exit was recorded.

You can also ask Codex directly:

```text
Run the paper preview.
Confirm eligible local paper entries.
Show me open paper trades.
Log this paper trade exit.
Refresh Paper Progress.
```

The dashboard should only log a trade when the scanner, session gate, and
position-sizing checks already produced an eligible local paper row. Do not
manually force rows into the paper log just to create activity.

Use the Sample Queue page before Candidates when you want the cleanest next
paper-validation action. It separates:

```text
Ready = current-candle candidate eligible for manual checklist review
Blocked Current = current signal exists but a gate blocked paper entry
Almost Ready = close setup to watch on the next scan, not a paper entry
Waiting = no useful action
```

The Sample Queue is read-only. It does not create paper trades, place broker
orders, or change position sizing.

Click `Review 30m chart` on a Sample Queue row to open the Trading Workspace
for that symbol with entry-timeframe chart context. Use `Expanded chart` when
you want the larger chart in a separate browser tab.

The Trading Workspace includes a Pre-entry Checklist beside the paper ticket.
It keeps local paper preview disabled until the saved data, candle age, scanner
status, sizing, paper gate, plan fields, shares, and risk guard are all ready.
After those pass, manually tick the review checkbox to enable `Run local paper
preview`.

The Backtest Research Account on Paper Progress is different. It uses promoted
historical backtest trades to show simulated P/L progress from the `$5,000`
research account model. It is useful for visualizing research, but it is not a
completed paper-trade record.

## Feature Placement Guide

New dashboard features should be placed by job:

```text
Home = daily overview and highest-priority next action
Trading Workspace = chart, ticket, setup readiness, paper review context
Sample Queue = ready, blocked, and almost-ready forward paper candidates
Candidates = current-candle review candidates
Trade Logger = entering or updating local paper-trade outcomes
Paper Progress = actual paper progress plus backtest research account visuals
Research = backtests, promotion review, forward evidence, validation context
System = health, workflow controls, state diagnostics, file links
Reports = long Markdown reports
Practice Replay = historical practice mode
Setup Health = approved-playbook warnings
```

## Setup Health

Setup Health is a side-menu page that flags approved playbook setups that need
attention.

It may show:

```text
symbol
setup name
direction
health status
health score
trade count
expectancy
profit factor
flags
```

Common statuses:

```text
watch_more = promising but still too small a sample
watch = acceptable but still monitor
caution = needs attention
```

Setup Health is research context. It does not approve individual paper trades.

## Setup Replay

Practice Replay is a side-menu page for historical setup review.

It is designed to train process quality without revealing the outcome too soon.

### Replay Filters And Presets

You can filter replay cards by:

```text
symbol
setup
grade
reviewed result
reviewed exit reason
```

Presets:

```text
All Cards
Unreviewed Only
A-Grade Setups
Setup B Shorts
Reviewed Losses
Reviewed Stop-Losses
Reviewed VWAP Exits
```

Important: result and exit-reason filters only use cards you already compared.
Hidden outcomes are not used to build the queue.

### Replay Journal

Before revealing an outcome, choose one:

```text
Take
Skip
Watch
```

You can also write notes.

Replay journal data is saved in your browser's local storage. It is not written
to the paper trade log.

### Replay Scoring Dashboard

Scoring appears after you compare replay outcomes.

It shows:

```text
reviewed count
Take average outcome
losses avoided by Skip/Watch
practice exit delta versus saved strategy exit
decision outcome breakdown
setup/grade outcome breakdown
practice exit comparisons
```

This is training feedback only. It is not forward-validation evidence.

### Replay Card

Each replay card shows:

```text
symbol
setup
direction
entry
stop
target
chart
setup details
practice prompts
decision buttons
journal notes
management controls
```

Before comparison, the outcome is hidden.

### Candle-By-Candle Management

After selecting Take, Skip, or Watch, use:

```text
Start management
Hold / Next candle
Exit here
Stop followed
Compare with historical outcome
```

The chart reveals only the allowed next candle while you practice management.

Use `Exit here` if you would manually exit at the visible candle.

Use `Stop followed` only when the visible candle has reached the stop.

Use `Compare with historical outcome` after your practice decision is complete.

## Reports

Reports is a side-menu page for read-only Markdown reports inside the app. Use
the report dropdown to switch between daily workflow, paper review, research,
deep research, and system reports.

Common report choices:

```text
Dashboard
Scanner
Observations
Near Misses
Observation Review
Reconciliation
Integrity
Refresh Audit
Setup Health
Paper Session
Paper Execution
Candidate Alerts
Forward Sample Queue
Post-Scan Digest
Forward Evidence
Candidate Aging
No-Trade Analysis
Shadow Samples
Open Paper Monitor
Exit Audit
Readiness
Checkpoint
Refresh Status
Morning Watchdog
Automation Timeline
Premarket
Setup Replay
Research Confidence
Promotion Review
Controlled Variants
Walk Forward
Regime Review
Strategy Audit
Opening Range Test
Deep Research
Deep Promotion
Deep Controlled
Deep Walk Forward
Deep Regime
System State
```

Use this section when you want the detailed report behind a dashboard tile.

`Morning Watchdog` confirms whether today's scheduled autonomous market scan
has run, whether today's Webull refresh is confirmed, whether the scanner is
using today's session, and how many current/reviewable candidates exist.

`Automation Timeline` summarizes the autonomous workflow without reading raw
LaunchAgent logs. It shows structured status, recent commands, possible
failures, file health, and the latest guidance from the watchdog/digest.

`Post-Scan Digest` is the quickest answer after a scan. It converts the latest
scanner, sample queue, no-trade analysis, refresh status, and watchdog state
into one action:

```text
review_candidate = manual checklist needed
watch_almost_ready = close setup, wait for next scan
study_blocker = no trade, but blocker pattern is worth reviewing
wait = nothing to do
data_issue = refresh/staleness problem first
```

`Strategy Audit` compares the current VWAP/EMA codebase against the strategy
upgrade handoff. It marks each framework item as existing, partial, or missing
and recommends the safest implementation order.

`Opening Range Test` compares the current opening-range requirement against a
no-opening-range research variant. Use it to decide whether a relaxation should
be shadow-tested, rejected, or studied further.

`Paper Session` shows the one-command local paper cycle. It updates candidate
alerts, local paper execution preview, open paper monitoring, paper review,
refresh status, and system state.

`Pre-Entry Review` is the hardened checklist before any local paper entry is
logged. It joins scanner status, sizing, data freshness, paper import
availability, Strategy Selector mode, and the Risk Guard into one
ready-or-blocked table.

Open it from:

```text
Reports -> Paper Review -> Pre-Entry Review
```

If this report says `blocked`, do not log the paper entry.

The Signal Workflow section has matching buttons: `Run paper preview`,
`Confirm local paper entry`, and `Confirm local paper exits`. The entry confirm
button is still manual. The exit confirm action is also run automatically during
market-hours autonomous scans. Both only write local paper logs; they do not
submit Webull paper orders or broker orders.

`Paper Execution` shows the local paper order preview generated from eligible
position-sizing rows. It is still local simulation only; it does not submit
Webull paper orders or any broker order.

`Candidate Alerts` shows whether any current-candle setup is ready for manual
paper review. It only shows ready when the scanner is allowed, the signal is
current-candle, the market/session gate passes, and sizing is `size_ok`.

`Forward Sample Queue` ranks the latest scanner rows by review priority. Use it
to see ready candidates, blocked current signals, almost-ready setups, and how
many allowed completed paper trades remain before the 30-trade checkpoint.

`Forward Evidence` combines official paper progress, forward observations,
shadow samples, and the current sample queue into one progress report. Use it
as the main proof-trail page before deciding whether the system is ready for a
next phase.

`Candidate Aging` checks whether candidates are appearing early enough in the
session to have room to work. It groups scanner, observation, shadow, and paper
rows by opening-hour, midday, afternoon, and late-day buckets.

`No-Trade Analysis` explains why Gwala is not producing paper candidates. It
shows top blockers, closest setups, and which single-rule relaxation would have
created more scanner passes. It does not loosen rules or create trades.

`Shadow Samples` records near-miss setups in a separate research lane. These
are would-have trades that missed one or two rules. They are scored later from
saved 5m candles but do not count toward official paper-trade validation.

`Open Paper Monitor` previews stop, target, or end-of-day updates for open
local paper trades using saved Webull 5m candles. It only writes outcomes when
the monitor runs with `--confirm-updates`. The autonomous workflow now uses
that exit-confirm mode for local paper exits only.

`Exit Audit` checks recorded local paper exits against the same saved Webull
5m candle rules. It helps catch cases where a recorded exit does not match the
paper stop, target, or end-of-day rule that the monitor would have used.

Common exit audit statuses:

```text
matched = recorded exit matches the saved 5m candle rule
mismatch = recorded exit differs from the saved 5m candle rule
open_or_incomplete = paper row is not closed yet
blocked = required candle data is missing or invalid
needs_review = saved candles did not produce a clear expected exit
```

Exit Audit is local paper validation only. It does not place, close, or modify
broker orders.

### App Scaffold

The App Scaffold panel on the System page links to important generated files.

It helps you find the underlying Markdown, CSV, and JSON outputs that power the
dashboard without keeping those file links in the main dashboard scroll.

## Normal Market-Day Routine

Before the open:

```text
Open Project Gwala Dashboard.app
Check System, Pre-Market Gate, and Reports
Use Run local pre-market check if needed
```

At and after the open:

```text
Let the autonomous workflow scan in the background
Click Refresh after scans complete
Review Current-Candle Candidates
Use Trading Workspace for chart context
Use the checklist before any manual paper trade
Let local paper exits auto-record from saved 5m candles
```

If no candidate appears:

```text
Review Near-Miss Analytics
Practice Setup Replay
Do not force paper trades
```

After the close:

```text
Review Daily Recap through Reports
Check Paper Progress
Practice replay cards
Review Setup Health if there are caution flags
```

## Safety Rules For Interpreting The App

Only a current-candle allowed candidate with eligible size can move to manual
paper review.

The app never gives permission for real-money trading.

The dashboard is not a broker.

The disabled order button is intentional.

Narrative, near-miss, replay, and setup-health panels are learning tools. They
do not override the scanner, checklist, stop, or sizing rules.

## Troubleshooting

If the app does not open:

```bash
launchctl print gui/$UID/com.project-gwala.dashboard
bash scripts/install_dashboard_launch_agent.sh
open "Project Gwala Dashboard.app"
```

If the app opens but data looks stale:

```text
Wait for the autonomous workflow to finish its current scan.
Click Refresh.
Check System -> App Health timestamps.
Check Reports -> Refresh Status.
```

If the dashboard server log has errors:

```text
logs/dashboard.launchd.err.log
```

If the autonomous workflow has errors:

```text
logs/autonomous_paper_workflow.launchd.err.log
logs/autonomous_paper_workflow.launchd.out.log
```

If the Mac was asleep or logged out:

```text
Wake/log in first. User LaunchAgents cannot run while the Mac is unavailable.
```
