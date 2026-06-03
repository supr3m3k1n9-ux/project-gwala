# Trading Research Bot

This project is a research-first trading framework for testing VWAP + EMA trend
continuation ideas before any live execution is considered.

The system is designed to answer:

- Did this setup have measurable edge historically?
- What was the win rate, expectancy, drawdown, and profit factor?
- Which trades worked, which failed, and why?

It is not a prediction engine and it does not place live trades.

## Current Strategy

The first strategy is an opening trend continuation model:

- 1H candles define the broader thesis.
- 30m candles define execution entries.
- 5m candles manage exits after a trade is opened.
- VWAP represents intraday control.
- 9 EMA and 21 EMA represent short-term trend structure.
- 200 EMA represents the larger trend regime.
- The first 30 minutes define the opening range.
- Entries are limited to the regular session after the opening range has formed.

The framework also compares two versions:

- Baseline: your original VWAP + EMA continuation rules.
- Elite A-setup: baseline rules plus stricter quality filters for volume, clean
  trend structure, trend-day behavior, higher-timeframe alignment, opening range
  strength, and room before resistance.

Generate the strategy overlap audit after reviewing an upgrade handoff:

```bash
python run_strategy_overlap_audit.py
```

Output:

```text
logs/strategy_overlap_audit.md
logs/strategy_overlap_audit.csv
```

Run the opening-range relaxation review after comparing `current` against
`no_opening_range`:

```bash
python run_opening_range_relaxation_review.py
```

Output:

```text
logs/opening_range_relaxation_review.md
logs/opening_range_relaxation_review.csv
```

## Project Structure

```text
app/             Local research dashboard shell
config/           Strategy and risk settings
data/             Market data loading and storage
indicators/       VWAP, EMA, and other calculations
strategies/       Signal logic
backtesting/      Candle replay and trade simulation
risk_management/  Position sizing and safety rules
execution/        Future broker/paper-trading layer
visualization/    Trade charts
reports/          Shared report and app-state helpers
logs/             Backtest outputs and trade journals
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run A Backtest

```bash
python main.py --symbol SPY --period 60d
```

The script will:

1. Download historical 30m entry candles and 5m exit candles.
2. Calculate VWAP, 9 EMA, 21 EMA, and 200 EMA.
3. Calculate 1H higher-timeframe bias from the entry candles.
4. Calculate opening range high/low from the 5m candles.
5. Score each signal as A, B, or C quality.
6. Generate baseline and elite A-setup long signals.
7. Simulate entries on 30m candles and exits on 5m candles.
8. Print side-by-side performance statistics.
9. Save a plain-English summary report, candle files, trade logs, and charts in `logs/`.

Start with the summary report first. It explains the key statistics and links
the detailed files created by the run.

## Run From Local CSV Files

Use this when Yahoo/yfinance is unavailable or when candles were pulled from
Webull first.

Expected CSV columns:

```text
datetime,open,high,low,close,volume
```

Example using Webull-generated files:

```bash
python main.py \
  --symbol SPY \
  --entry-csv logs/webull_SPY_M30_candles.csv \
  --exit-csv logs/webull_SPY_M5_candles.csv
```

The entry CSV should usually be 30m candles. The exit CSV should usually be 5m
candles.

For provider exports that use headers like `Date`, `Open`, `High`, `Low`,
`Close`, and `Vol`, import them into the local reuse-cache format first:

```bash
python run_import_candles_csv.py \
  --symbol SPY \
  --timeframe M30 \
  --source-csv data/SPY_30m.csv \
  --output-dir logs/external_history

python run_import_candles_csv.py \
  --symbol SPY \
  --timeframe M5 \
  --source-csv data/SPY_5m.csv \
  --output-dir logs/external_history

python run_webull_watchlist.py \
  --symbols SPY \
  --reuse-csv \
  --output-dir logs/external_history \
  --candidate-preset best_plus_market
```

The importer normalizes the file names to
`webull_SYMBOL_TIMEFRAME_candles.csv` so the existing multi-symbol runner can
reuse the same backtest path.

## Compare Controlled Variants

After a watchlist run, compare each filter to its matching baseline:

```bash
python run_controlled_variant_review.py \
  --research-dir logs/deeper_research \
  --output-dir logs/deeper_research
```

Then check whether candidates still work in the newer half of their trade logs:

```bash
python run_walk_forward_review.py \
  --research-dir logs/deeper_research \
  --output-dir logs/deeper_research
```

Then check which broad-market regimes help or hurt each setup:

```bash
python run_regime_review.py \
  --research-dir logs/deeper_research \
  --output-dir logs/deeper_research
```

These are research reports only. They do not change the scanner, paper log,
alerts, broker settings, or live execution.

## Run The Local App Shell

The local app is a research and paper-validation dashboard. It reads
`logs/system_state.json` and supports local-only report rebuild actions; it
does not fetch data, import paper trades, place trades, create alerts, or
connect to broker execution.

Refresh system state first:

```bash
python run_system_state.py
```

Then start the app:

```bash
python run_app.py
```

Open:

```text
http://127.0.0.1:8765
```

Or open the local desktop app wrapper:

```text
Project Gwala Dashboard.app
```

That app simply opens the local dashboard URL. The dashboard server still comes
from the macOS LaunchAgent described below.

Full dashboard manual and navigation guide:

```text
APP_MANUAL.md
```

To start the dashboard automatically at login/load:

```bash
bash scripts/install_dashboard_launch_agent.sh
```

To stop and remove the dashboard auto-start:

```bash
bash scripts/uninstall_dashboard_launch_agent.sh
```

Check dashboard service status:

```bash
launchctl print gui/$UID/com.project-gwala.dashboard
```

Dashboard launch logs:

```text
logs/dashboard.launchd.out.log
logs/dashboard.launchd.err.log
```

The app API endpoint is:

```text
http://127.0.0.1:8765/api/system-state
```

Report detail endpoint:

```text
http://127.0.0.1:8765/api/report?name=dashboard
```

Allowed report names:

```text
dashboard
scanner
observations
setup_health
paper_session
paper_execution
candidate_alerts
open_paper_monitor
readiness
checkpoint
refresh_status
premarket
setup_replay
system_state
```

The dashboard includes two local status-only actions:

```text
POST http://127.0.0.1:8765/api/actions/refresh-status
POST http://127.0.0.1:8765/api/actions/premarket-check
```

The `Update refresh status` button runs this action. It rebuilds only local
refresh-readiness and system-state reports. It does not refresh Webull data,
import paper trades, place orders, or enable live trading.

The `Run local pre-market check` button rebuilds candle integrity, refresh
status, readiness, pre-market verification, and system-state outputs. It does
not run the Webull probe; an earlier successful explicit probe is shown as a
previous pass until intentionally rerun from the terminal.

The main dashboard includes a `Pre-Market Gate` tile and badge that show the
latest verification status and most recently recorded data-only probe result.

The main page also includes a read-only `Trading Workspace`:

```text
approved-symbol watchlist
5m and 30m candlestick chart from saved Webull market-data bars
VWAP, EMA 9, EMA 21, EMA 200, and opening-range overlays
paper-review ticket populated when a current scanner candidate exists
```

The workstation is native to this app rather than an embedded broker page.
It uses the same Webull candle files as the scanner so chart review and
strategy calculations have one data source. It does not expose order-entry
controls or call Webull trading endpoints.

The Trading Workspace also includes a read-only `Setup Readiness Radar`. It
uses the saved scanner output to show which existing setup conditions are
passing or missing on the latest scanner candle, plus markers for approved
signals previously found in the stored session. It explains the strategy
state; it does not generate signals, unblock paper importing, or change paper
position sizing.

The dashboard includes `Near-Miss Analytics` for learning from setups that
were not ready. During fresh open-market workflow scans,
`run_near_miss_analytics.py` appends missing-condition observations to
`data/near_miss_observations.csv`. Outside an open session the panel displays
the latest saved scanner snapshot only and does not add evidence. This feature
is explanatory and cannot change scanner eligibility or paper-trade decisions.

The main page also includes a read-only `Investment Narrative` panel linked to
the selected Trading Workspace symbol. Its initial version displays
long-horizon monitoring themes and review questions for the approved universe,
plus an honest disconnected state for future headline and X public-post
sources. Any future source-linked summaries remain research context only and
are excluded from signal scoring, entries, exits, sizing, and paper-trade
eligibility.

The app also includes a read-only `Current-Candle Candidates` panel. It joins
existing scanner and position-sizing outputs to show entry, stop, target,
suggested paper size, and readiness/checklist flags when a fresh candidate
exists. It does not create signals, import rows, or submit orders.

The read-only `Paper Progress Visualization` panel uses completed forward
paper results from `logs/paper_review_clean_trades.csv`. It shows progress
toward the 30/60-trade gates, cumulative paper `R`, allowed versus watch-only
results, and plan-adherence summaries. Until completed paper trades exist, it
shows an explicit empty state rather than historical backtest performance.

## Check Refresh Status

Use this before the market opens or before refreshing Webull data:

```bash
python run_refresh_status.py
```

It writes:

```text
logs/refresh_status.json
logs/refresh_status.md
```

The report tells you whether refresh is ready, whether paper import is blocked,
and the exact command to run during market hours.

## Pre-Market Verification

Use one local-only command before the next open market session to rebuild and
summarize candle integrity, refresh status, system state, readiness, and safety
flags:

```bash
.venv/bin/python run_premarket_verification.py
```

To also confirm Webull market-data access with a small data-only request:

```bash
.venv/bin/python run_premarket_verification.py --probe-webull
```

The optional probe saves separate files under `logs/premarket_probe/`. It does
not replace full workflow candle files, import paper trades, or connect to
order execution.

Generated files:

```text
logs/premarket_verification.json
logs/premarket_verification.md
```

Run automated workflow guardrail tests with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Run Setup Replay Practice

Use historical approved playbook trades for non-market-hours practice:

```bash
python run_setup_replay.py
python run_system_state.py
```

It writes:

```text
logs/setup_replay.json
logs/setup_replay.md
```

The local app then shows replay cards with an entry-time chart, plan levels,
and checklist prompts first. Record a `Take`, `Skip`, or `Watch` practice
decision, then use candle-by-candle management to advance one stored exit bar
at a time. You can record `Hold`, `Exit here`, or `Stop followed` before
comparing against the historical strategy outcome. Future candle count, exit
path, and result remain hidden until reached in the replay or compared after a
practice exit. Practice decisions and optional notes are saved only in the
local browser journal and cannot change scanner or paper-trade eligibility.
The Markdown replay report remains a full audit record and shows results.
Replay mode is for process practice only; it is not a live signal or
prediction tool.

After historical comparisons are completed, the app's Replay Scoring
Dashboard summarizes only those reviewed cards. It reports outcome patterns
behind `Take`, `Skip`, and `Watch` decisions; reviewed setup/grade groups; and
practice-exit R compared with the saved strategy exit. Unrevealed cards are
excluded from scoring, and the dashboard remains training feedback rather than
forward-validation evidence.

Use Replay Filters and Presets to build focused practice sessions by symbol,
setup, or quality grade. Presets such as `Unreviewed Only` and `A-Grade
Setups` are safe before comparison. Sessions based on results or exit reasons,
including `Reviewed Losses`, `Reviewed Stop-Losses`, and `Reviewed VWAP
Exits`, include compared cards only so hidden historical outcomes are not used
to choose the next practice card.

## Run A Webull Watchlist Backtest

After activating the Python 3.11 Webull environment, run the main watchlist with
larger Webull candle samples and built-in pauses:

```bash
source .venv-webull/bin/activate
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --entry-count 1200 \
  --exit-count 1200 \
  --entry-pages 1 \
  --exit-pages 1 \
  --pause 10
```

This fetches Webull M30 entry candles and M5 exit candles, runs the backtests,
and saves combined reports:

```text
logs/webull_watchlist_backtest_summary.csv
logs/webull_watchlist_backtest_summary.md
```

You can also compare research variants without fetching new data:

```bash
python run_webull_watchlist.py \
  --symbols QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --variants current quality_entry
```

Available variants include:

```text
current
elite_score_6
relvol_1_0
room_0_75
no_opening_range
balanced_relaxed
quality_entry
```

Per-symbol diagnostics show which filters block trades:

```text
logs/SYMBOL_VARIANT_webull_30m_entry_5m_exit_diagnostics.md
```

To run only the current best research candidates:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best
```

By default, the candidate selection report requires at least 10 trades before
a mathematically passing symbol is marked `approved`. Passing symbols with
fewer than 10 trades are marked `watch_more`.

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best \
  --min-approved-trades 10
```

This compares:

```text
current + no_vwap_exit = more active baseline candidate
quality_entry + no_vwap_exit = more selective quality candidate
```

Focused reports:

```text
logs/best_candidate_summary.md
logs/candidate_selection_report.md
```

To compare the current best candidates against SPY-confirmed market-regime
variants:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best_plus_market \
  --market-regime-symbol SPY \
  --min-approved-trades 10
```

The market-confirmed variants only allow entries when SPY is above VWAP, above
the 21 EMA, and has the 9 EMA above the 21 EMA on the 30m timeframe.

Setup A labeled reports:

```text
logs/setup_a_candidate_selection_report.md
logs/setup_a_candidate_summary.md
logs/setup_a_watchlist_backtest_summary.csv
logs/setup_a_watchlist_backtest_summary.md
```

To start Setup B bearish-continuation research:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset setup_b \
  --min-approved-trades 10
```

Setup B is a short-side research setup. It mirrors the VWAP + EMA continuation
idea, but only in bearish structure. It is still backtesting-only research.

Setup B labeled reports:

```text
logs/setup_b_candidate_selection_report.md
logs/setup_b_candidate_summary.md
logs/setup_b_watchlist_backtest_summary.csv
logs/setup_b_watchlist_backtest_summary.md
```

To run the combined approved playbook:

```bash
python run_playbook.py --mode approved
```

The playbook runner combines only the currently approved setup/symbol pairs.
It is still a research report, not live trading or paper trading.

Playbook outputs:

```text
logs/playbook_approved_trades.csv
logs/playbook_approved_summary.csv
logs/playbook_approved_summary.md
```

To apply portfolio-level rules to the approved playbook:

```bash
python run_portfolio.py --name approved
```

Default portfolio rules:

```text
max open positions = 3
max open positions per symbol = 1
max trades per day = 5
max daily realized loss = -3R
```

The current best research profile adds a monthly loss stop. This stops taking
new trades after the portfolio is down -3R realized in a calendar month:

```bash
python run_portfolio.py --profile monthly_stop_3r
```

Latest monthly-stop result:

```text
accepted trades = 340
skipped trades = 44
win rate = 0.5176
expectancy = +0.1135R
profit factor = 1.4677
max drawdown = -6.5803R
final cumulative R = +38.5937R
```

For comparison, the default profile had +0.0876R expectancy, 1.3473 profit
factor, -10.0424R max drawdown, and +32.6832R final cumulative R.

The current approved playbook also includes two exit upgrades found by the exit
optimizer:

```text
TSLA Setup A Long: two_vwap_closes
AAPL Setup B Short: two_vwap_closes
```

To rerun the exit optimizer:

```bash
python run_exit_optimizer.py
```

To rerun the entry optimizer for the current weaker symbols:

```bash
python run_entry_optimizer.py --symbols SPY NVDA
```

The latest broad entry-optimizer scan did not find a promotable entry upgrade.
The current approved entry variants should stay as-is for now.

To run the current best weakness-filter research profile:

```bash
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
```

Latest `weakness_v1` result:

```text
accepted trades = 325
skipped trades = 31
blocked raw trades = 28
win rate = 0.5354
expectancy = +0.1446R
profit factor = 1.6707
max drawdown = -6.5803R
final cumulative R = +46.9839R
```

This filter blocks three entry-known weak pockets found by the weakness
analyzer:

```text
NVDA Setup B Short: skip 11am ET entries
NVDA Setup B Short: skip relative volume 0.75-1.0 and 1.25-1.5
SPY Setup A Long: skip room-to-target 0.75R-1.0R
```

Treat `weakness_v1` as the current best research profile, not a live-trading
rule. It needs validation on fresh data.

To run the internal holdout validation:

```bash
python run_holdout_validation.py
```

Latest holdout check:

```text
full sample: +0.0311R expectancy improvement, +8.3902R final R
first half: +0.0446R expectancy improvement, +5.8280R final R
second half: +0.0155R expectancy improvement, +2.5622R final R
2024: +0.1162R expectancy improvement, +3.2192R final R
2025: +0.0238R expectancy improvement, +4.7030R final R
2026: +0.0169R expectancy improvement, +0.4680R final R
```

This supports `weakness_v1` as the strongest current research profile, but
fresh data is still needed before treating it as durable.

## Paper Workflow

To rerun the full current research and paper workflow:

```bash
python run_research_pipeline.py
```

Master output:

```text
logs/research_pipeline_summary.md
```

The current human-readable playbook is:

```text
PLAYBOOK_CHEATSHEET.md
```

To generate the paper-trade-style signal journal:

```bash
python run_signal_journal.py --trade-filter weakness_v1 --latest 30
```

Journal outputs:

```text
logs/paper_signal_journal.csv
logs/paper_signal_journal.md
```

To generate plain-English journal interpretation:

```bash
python run_journal_insights.py
```

Insights output:

```text
logs/journal_insights.md
```

Latest journal summary:

```text
allowed historical signals = 356
blocked historical signals = 28
allowed average historical R = +0.1202
blocked average historical R = -0.3469
```

## Latest Fresh-Data Validation

Fresh Webull candles were pulled on 2026-05-23 and the research pipeline was
rerun.

```bash
python run_research_pipeline.py
```

Fresh pipeline result:

```text
Base monthly_stop_3r:
accepted trades = 104
expectancy = +0.1987R
profit factor = 1.8761
max drawdown = -4.9038R
final cumulative R = +20.6687R

weakness_v1:
accepted trades = 94
expectancy = +0.2223R
profit factor = 1.9859
max drawdown = -4.2148R
final cumulative R = +20.8980R
```

Interpretation:

```text
weakness_v1 still beat the base profile on the refreshed data.
The improvement was smaller than the original historical test, but still positive.
The blocked journal group was nearly flat this time, so the filter should still be watched during paper validation.
```

## Forward Paper Review

Use this template for actual paper-trade tracking:

```text
data/paper_trades.csv
```

After adding paper trades, run:

```bash
python run_paper_review.py
```

The report is saved here:

```text
logs/paper_review_summary.md
```

Review gates:

```text
30 allowed paper trades = first useful checkpoint
60 allowed paper trades = stronger confidence checkpoint
```

## Daily Paper Signal Scanner

Use the scanner to turn the approved playbook into a daily paper-trading
checklist from the latest local Webull CSV candles:

```bash
python run_daily_scanner.py
```

Outputs:

```text
logs/daily_paper_signal_scanner.csv
logs/daily_paper_signal_scanner.md
logs/daily_paper_trade_import_template.csv
```

Scanner labels:

```text
allowed = paper candidate under the current research filter
blocked_watch_only = signal exists, but weakness_v1 says watch only
not_ready = setup is not currently qualified
data_error = required local candles are missing or invalid
```

## Forward Signal Observation Journal

The daily workflow automatically preserves fresh current-candle scanner
sightings in an append-only observation journal:

```text
data/forward_signal_observations.csv
logs/forward_signal_observations.md
```

This log records both `allowed` and `blocked_watch_only` observations during
an open market session. It is evidence collection only: an observation does
not become a paper trade and does not create any order or alert.

Repeated refreshes are deduplicated using:

```text
signal_time_et + symbol + setup + direction
```

You can rebuild its report from the current scanner output directly:

```bash
python run_forward_observations.py
```

## Daily Workflow Command

Use this for the normal daily paper routine when local CSVs are already fresh:

```bash
python run_daily_workflow.py
```

Use this when you want the workflow to refresh Webull market-data CSVs first:

```bash
python run_daily_workflow.py --refresh-data
```

The workflow fetches each symbol's fresh candle files once per cycle, then
reuses those files while evaluating the long and short approved setup families.

Generate fresh candidates first during market hours:

```bash
python run_daily_workflow.py --refresh-data
```

After manually reviewing a fresh current-candle candidate and its checklist,
preview and then import that paper row separately:

```bash
python run_paper_import.py --dry-run
python run_paper_import.py
```

The importer writes allowed candidates to `data/paper_trades.csv` only while
regular market hours are open, the scanner rows are from today's session, and
the workflow recorded current-session Webull refresh evidence for the symbol.
Blocked/watch-only rows remain in the observation journal. Automatic import from
`run_daily_workflow.py --append-current-signals` is disabled so a candidate
cannot be logged as a reviewed paper trade before human review.

Position sizing also requires an open-session current-candle candidate and
automatically reads completed allowed outcomes in `data/paper_trades.csv` for
the daily and monthly R-loss stops.

To preview imports without writing:

```bash
python run_paper_import.py --dry-run
```

Daily workflow output:

```text
logs/daily_workflow_summary.md
logs/forward_signal_observations.md
data/forward_signal_observations.csv
```

The workflow rebuilds `logs/system_state.json` after its reports finish so the
local app health panel reflects the completed daily run.

## Paper Position Sizing

Use this to turn scanner candidates into paper-trade share sizes:

```bash
python run_position_sizer.py
```

Defaults:

```text
Account size = $10,000
Risk per trade = 0.50%
Risk budget = $50
Freshness filter = current_candle
```

Outputs:

```text
logs/position_sizing.csv
logs/position_sizing.md
```

The daily workflow runs the sizer automatically.

## Trade Management Lab

Use this to compare take-profit and stop-management overlays on the approved
playbook:

```bash
python run_trade_management_lab.py
```

Outputs:

```text
logs/trade_management_lab.md
logs/trade_management_overall.csv
logs/trade_management_by_symbol.csv
logs/trade_management_by_setup.csv
```

Current finding from the latest local sample:

```text
The existing approved management remains tied for best.
Partial-at-1R profiles reduced expectancy on this sample.
```

## Project Dashboard

Use this to create one mission-control report from scanner, sizing, paper
review, portfolio, holdout, and trade-management outputs:

```bash
python run_dashboard.py
```

Output:

```text
logs/project_gwala_dashboard.md
```

The daily workflow and research pipeline both update this dashboard.

## Intraday Paper Loop

Use this to run the daily workflow on a market-hours loop:

```bash
python run_intraday_loop.py
```

Safe one-pass check:

```bash
python run_intraday_loop.py --once
```

The loop only runs during regular market hours by default and exits once that
day's regular session has closed. It writes:

```text
logs/intraday_loop_status.md
```

It remains paper-only: no orders, no broker alerts, no live execution.

## Autonomous Paper Supervisor

Use this when you want one local command to decide what the paper workflow
should do based on the market calendar:

```bash
python run_autonomous_paper_workflow.py
```

Safe one-pass preview:

```bash
python run_autonomous_paper_workflow.py --once --dry-run
```

The supervisor can:

```text
wait until the pre-market check window
run pre-market verification before the open
run market-hours refresh/scanner/sizing/dashboard cycles
run after-close recap/readiness/system-state reports
```

It writes:

```text
logs/autonomous_paper_workflow_status.md
logs/autonomous_paper_workflow_status.json
logs/morning_run_watchdog.md
logs/morning_run_watchdog.json
```

The morning watchdog is the first place to check after the 6:30 AM PT scan has
had a few minutes to finish. It reports whether the scheduled workflow wrote
status today, whether the market scan ran, whether today's Webull refresh was
confirmed, whether the scanner is on today's session, candidate counts, and the
next action.

It remains research and paper-validation only. It does not place orders, create
broker alerts, import reviewed paper trades, or connect to broker execution.

### Start Automatically On macOS

The project includes a macOS `launchd` agent for starting the autonomous paper
supervisor automatically:

```text
launchd/com.project-gwala.autonomous-paper.plist
```

Install and load it:

```bash
bash scripts/install_autonomous_launch_agent.sh
```

Check status:

```bash
launchctl print gui/$UID/com.project-gwala.autonomous-paper
```

Unload and remove it:

```bash
bash scripts/uninstall_autonomous_launch_agent.sh
```

Schedule:

```text
Weekdays at 6:15 AM PT = pre-market check
Weekdays 6:30 AM-1:00 PM PT = one-shot market scan every 5 minutes
Weekdays at 1:05 PM PT = after-close recap
```

Each scheduled run uses `--once`, so the process exits after the due action
instead of staying alive all day. This keeps the laptop quieter while still
refreshing during regular market hours.

The supervisor itself uses the market calendar, so holidays, weekends, market
hours, and after-close behavior are still gated by the project safety logic.

Launch logs:

```text
logs/autonomous_paper_workflow.launchd.out.log
logs/autonomous_paper_workflow.launchd.err.log
```

Important Mac note: a user LaunchAgent can run only while the Mac is powered
on and the user account is logged in. If the Mac is asleep, powered off, or
logged out, the workflow cannot run until macOS wakes and allows user agents.

## Market Calendar

Use this to preview the local NYSE market calendar guard:

```bash
python run_market_calendar.py --start 2026-05-24 --days 5
```

The calendar handles weekends, regular NYSE holidays, Good Friday, observed
fixed-date holidays, and common 1pm ET early closes.

## Paper Trade Outcome Updater

List open paper-trade rows:

```bash
python run_update_paper_trade.py --list-open
```

Update one completed paper trade:

```bash
python run_update_paper_trade.py \
  --row 1 \
  --actual-entry 748.75 \
  --actual-exit 754.05 \
  --exit-time 11:30 \
  --followed-plan yes \
  --exit-reason profit_target
```

The updater calculates `outcome_r` from actual entry, actual exit, planned
stop, and direction.

## Paper Validation Checkpoint

Use this to track progress toward the 30-trade and 60-trade paper validation
gates:

```bash
python run_checkpoint_report.py
```

Output:

```text
logs/paper_validation_checkpoint.md
```

## Paper Workflow Drill

Use this to rehearse the scanner-to-paper-review workflow without changing the
real paper journal:

```bash
python run_paper_drill.py
```

Output:

```text
logs/paper_drill/paper_drill_trades.csv
logs/paper_drill/paper_review_summary.md
logs/paper_drill/paper_validation_checkpoint.md
logs/paper_drill/paper_drill_summary.md
```

The drill creates one fake completed trade from the latest scanner output,
reviews it, and checks the paper-validation gate logic. It does not modify
`data/paper_trades.csv`.

By default, the drill now rehearses a full set of fake outcomes:

```text
planned win
planned loss
breakeven
plan break
```

Use `--scenario single --outcome-r 1.5` to rehearse one custom outcome.

## Pre-Market Plan

Use this before the market opens:

```bash
python run_premarket_plan.py
```

Output:

```text
logs/daily_trade_plan.md
```

The plan summarizes the market calendar, risk box, approved playbook, watch
list, current candidates, eligible sizes, and trade permission rules.

## Paper Trade Checklist

Use this before taking any paper trade:

```bash
python run_trade_checklist.py
```

Output:

```text
logs/trade_entry_checklist.md
```

## Paper Mistake Tracker

Use this to create and summarize the process-mistake log:

```bash
python run_mistake_tracker.py
```

Output:

```text
data/paper_mistakes.csv
logs/paper_mistake_tracker.md
```

Only add a mistake row when the process was actually broken.

## Daily Paper Recap

Use this after the session or after running the daily workflow:

```bash
python run_daily_recap.py
```

Output:

```text
logs/daily_recap.md
```

The normal `python run_daily_workflow.py` command now also updates the
pre-market plan, entry checklist, mistake tracker report, and daily recap.

## Paper Session Cycle

Use this as the simple operator command during market hours. By default it is
preview-only:

```bash
python run_paper_session_cycle.py
```

It updates candidate alerts, local paper execution preview, open paper monitor,
paper review, refresh status, and system state.

The dashboard Signal Workflow section also has buttons for the same cycle:

```text
Run paper preview
Confirm local paper entry
Confirm local paper exits
```

Only write local paper entries after review:

```bash
python run_paper_session_cycle.py --confirm-local-paper
```

Only write completed local paper exits after review:

```bash
python run_paper_session_cycle.py --confirm-exits
```

You can combine both flags after reviewing the previews:

```bash
python run_paper_session_cycle.py --confirm-local-paper --confirm-exits
```

Output:

```text
logs/paper_session_cycle.md
```

Important: this remains local paper simulation only. It does not place Webull
paper orders, call Webull order endpoints, create broker alerts, or connect to
broker execution.

## Local Paper Execution Simulator

Use this to preview local paper order tickets from rows that are already
eligible in `logs/position_sizing.csv`:

```bash
python run_paper_execution_simulator.py
```

Write local paper orders and open rows in `data/paper_trades.csv` only after
reviewing the preview:

```bash
python run_paper_execution_simulator.py --confirm-local-paper
```

Outputs:

```text
logs/local_paper_execution_simulator.md
data/paper_orders.csv
data/paper_trades.csv
```

Important: this is local simulation only. It does not place Webull paper
orders, call Webull order endpoints, create broker alerts, or connect to
broker execution.

## Paper Candidate Alerts

Use this to generate the review alert report from current scanner and sizing
outputs:

```bash
python run_candidate_alerts.py
```

Outputs:

```text
logs/paper_candidate_alerts.csv
logs/paper_candidate_alerts.md
```

The daily workflow runs this automatically after the local paper execution
preview. The dashboard Reports section shows it as `Candidate Alerts`.

## No-Trade Blocker Analysis

Use this when the bot is too quiet and you need to see which filters are
preventing paper candidates:

```bash
python run_no_trade_analysis.py
```

Outputs:

```text
logs/no_trade_blocker_analysis.csv
logs/no_trade_blocker_analysis.md
```

The report shows top blockers, closest setups, and which single-rule
relaxations would have created more scanner passes. It is research-only and
does not loosen rules by itself.

## Shadow Sample Collection

Use this to record near-miss setups separately from official paper trades:

```bash
python run_shadow_samples.py
```

Outputs:

```text
data/shadow_samples.csv
logs/shadow_sample_outcomes.csv
logs/shadow_samples.md
```

Shadow samples are would-have trades. They do not count toward the official
30/60 paper validation gates and do not create broker orders.

## Forward Evidence Dashboard

Use this to combine the official paper gate, forward observations, shadow
samples, and current sample queue into one proof-trail report:

```bash
python run_forward_evidence.py
```

Outputs:

```text
logs/forward_evidence.md
```

This report is read-only. It does not import trades, place orders, or promote
shadow samples into official paper evidence.

## Candidate Aging Review

Use this to see whether candidates are appearing too late in the day:

```bash
python run_candidate_aging.py
```

Outputs:

```text
logs/candidate_aging.csv
logs/candidate_aging.md
```

The report groups scanner rows, forward observations, shadow samples, and
paper trades into opening-hour, midday, afternoon, and late-day buckets. It is
research-only and does not change scanner rules.

## Morning Run Watchdog

Use this to confirm the scheduled morning workflow actually ran:

```bash
python run_morning_watchdog.py
```

Outputs:

```text
logs/morning_run_watchdog.json
logs/morning_run_watchdog.md
```

After 6:35 AM PT on a regular market day, the report should show whether the
autonomous workflow ran, whether Webull data refreshed for today's session,
whether scanner output is current, and how many candidates are ready for manual
paper review. It is status-only and never places orders or imports paper
trades.

## Post-Scan Candidate Digest

Use this to summarize the latest scanner pass into one paper-action decision:

```bash
python run_post_scan_digest.py
```

Outputs:

```text
logs/post_scan_digest.json
logs/post_scan_digest.md
```

The digest reads the forward sample queue, no-trade blocker analysis, refresh
status, and morning watchdog. It reports one of: `review_candidate`,
`watch_almost_ready`, `study_blocker`, `wait`, or `data_issue`. It is
status-only and never places orders, imports paper trades, or changes scanner
rules.

## Daily Automation Timeline

Use this to summarize the scheduled workflow without reading raw LaunchAgent
logs:

```bash
python run_daily_automation_timeline.py
```

Outputs:

```text
logs/daily_automation_timeline.json
logs/daily_automation_timeline.md
```

The timeline combines autonomous status, morning watchdog, post-scan digest,
recent LaunchAgent command blocks, possible errors, and file health. It is
status-only and never fetches data, places orders, creates broker alerts,
imports paper trades, or changes scanner rules.

## Open Paper Trade Monitor

Use this to preview exits for open local paper trades from saved Webull 5m
candles:

```bash
python run_open_paper_monitor.py
```

Write completed paper-trade exit updates only after reviewing the preview:

```bash
python run_open_paper_monitor.py --confirm-updates
```

Outputs:

```text
logs/open_paper_trade_monitor.csv
logs/open_paper_trade_monitor.md
```

The daily workflow runs this automatically in preview mode. The dashboard
Reports section shows it as `Open Paper Monitor`.

## Market-Open Readiness Check

Use this before the next session to see whether the paper workflow is ready:

```bash
python run_readiness_check.py
```

Output:

```text
logs/readiness_check.md
```

It checks the market calendar, Webull key names, local Webull CSV coverage,
scanner freshness, position sizing, paper-log health, open paper rows, and
support-report files. It does not fetch data or place trades.

The normal `python run_daily_workflow.py` command also updates this report.

Portfolio outputs:

```text
logs/portfolio_approved_accepted_trades.csv
logs/portfolio_approved_skipped_trades.csv
logs/portfolio_approved_daily_summary.csv
logs/portfolio_approved_equity_curve.csv
logs/portfolio_approved_monthly_summary.csv
logs/portfolio_approved_drawdown_stretches.csv
logs/portfolio_approved_summary.md
```

For deeper history, increase the page counts. Webull returns up to 1200 candles
per request, so this example pulls 2400 M30 candles and 7200 M5 candles for
TSLA:

```bash
python run_webull_watchlist.py \
  --symbols TSLA \
  --entry-count 1200 \
  --exit-count 1200 \
  --entry-pages 2 \
  --exit-pages 6 \
  --pause 5 \
  --variants current quality_entry
```

## Webull Market Data Setup

Webull integration should be used for market data first. Do not connect order
placement or live trading while this project is still in research/backtesting
mode.

Create a local `.env` file from `.env.example` and fill in:

```text
WEBULL_APP_KEY=your_app_key_here
WEBULL_APP_SECRET=your_app_secret_here
WEBULL_REGION_ID=us
WEBULL_API_ENDPOINT=
```

The Webull SDK does not currently fit this project's Python 3.14 virtual
environment cleanly. Use a Python 3.11 environment for Webull testing.

After Python 3.11 is installed, create a separate Webull test environment:

```bash
python3.11 -m venv .venv-webull
source .venv-webull/bin/activate
pip install -r requirements.txt
pip install -r requirements-webull.txt
```

Then test market-data access only:

```bash
python tools/check_webull_data.py --symbol SPY --timespan M5 --count 20
```

If the request succeeds, the raw response and a backtester-ready CSV are saved
in `logs/` for review.

Example output files:

```text
logs/webull_probe_SPY_M5.json
logs/webull_probe_SPY_M5_candles.csv
```

## Expand The Research Universe Safely

Use a separate output folder when screening new tickers. This keeps discovery
data and candidate reports separate from the currently approved paper workflow.

First-pass screen:

```bash
source .venv-webull/bin/activate
python run_webull_watchlist.py \
  --symbols SPY IWM DIA AMZN GOOGL AVGO NFLX COIN PLTR \
  --entry-count 1200 --exit-count 1200 \
  --entry-pages 1 --exit-pages 1 --pause 5 \
  --output-dir logs/universe_expansion \
  --candidate-preset best_plus_market
python run_webull_watchlist.py \
  --symbols IWM DIA AMZN GOOGL AVGO NFLX COIN PLTR \
  --reuse-csv --output-dir logs/universe_expansion \
  --candidate-preset setup_b
```

Only fetch deeper history for first-pass leads. Exploratory candidates do not
enter the approved playbook or daily paper scan just because a research report
marks them `approved`.

## Safety Notes

Before live execution, the strategy should be tested across many symbols,
market regimes, and dates. Paper trading comes before real orders.
