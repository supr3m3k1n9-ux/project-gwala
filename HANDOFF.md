# Trading Bot Project Handoff

This file explains the project in plain English so you can open it in VS Code
and quickly understand what is going on.

## Context Transfer Between Codex Windows

For persistent project memory, use:

```text
PROJECT_MEMORY.md
```

At the start of a new Codex window, ask:

```text
Read AGENTS.md, PROJECT_MEMORY.md, and HANDOFF.md. Summarize the current
project status, safety rules, blockers, and the next safest coding task.
```

At the end of a work session, ask:

```text
Update PROJECT_MEMORY.md and HANDOFF.md with what changed, what was verified,
what is still blocked, and the next recommended task.
```

## Project Location

The project is saved here:

```text
/Users/roy/Documents/New project
```

Open this folder in VS Code:

```text
File -> Open Folder -> /Users/roy/Documents/New project
```

## What This Project Is

This is a research and backtesting framework for a trading strategy.

It uses Webull market data only for research CSVs and paper-validation inputs.
It does not place real trades.
It does not use AI to guess future prices.

The goal is to test whether your strategy has measurable edge before any live
trading automation is added.

## Current Strategy Idea

Strategy family:

```text
VWAP + EMA opening trend continuation
```

The strategy uses:

```text
1H timeframe = higher-timeframe thesis
30m timeframe = entry signal
5m timeframe = exit management
VWAP = intraday control
9 EMA = short-term momentum
21 EMA = trend structure
200 EMA = macro trend filter
opening range = early session strength filter
relative volume = participation filter
```

## Current Bot Behavior

When the backtest runs, it:

1. Downloads historical candles.
2. Calculates VWAP, 9 EMA, 21 EMA, and 200 EMA.
3. Calculates opening range high/low.
4. Calculates higher-timeframe bullish bias.
5. Creates baseline trade signals.
6. Creates stricter elite A-setup signals.
7. Enters trades from 30m candles.
8. Exits trades using 5m candles.
9. Saves reports, charts, and trade logs.

## Baseline Vs Elite Strategy

The project compares two versions:

### Baseline

This uses the basic VWAP/EMA continuation rules.

### Elite A-Setup

This is stricter. It requires:

```text
higher-timeframe alignment
price above VWAP
price above opening range high
9 EMA above 21 EMA
clean bull trend structure
strong relative volume
room before resistance
trend-day behavior
```

The purpose is to test whether fewer, higher-quality trades outperform the
basic version.

## Important Files

Main command file:

```text
main.py
```

Strategy settings:

```text
config/settings.py
```

Data download:

```text
data/market_data.py
```

Indicators:

```text
indicators/trend.py
indicators/multitimeframe.py
indicators/session.py
```

Strategy logic:

```text
strategies/opening_trend_continuation.py
strategies/quality_filters.py
```

Backtesting engine:

```text
backtesting/engine.py
```

Performance metrics:

```text
backtesting/metrics.py
```

Report generator:

```text
reports/summary.py
```

Charts:

```text
visualization/charts.py
```

Saved results:

```text
logs/
```

## How To Run The Project

Open a terminal in VS Code:

```text
Terminal -> New Terminal
```

Then run:

```bash
cd "/Users/roy/Documents/New project"
source .venv/bin/activate
python main.py --symbol SPY --period 60d
```

If Yahoo/yfinance is unavailable, run from local CSV files instead:

```bash
python main.py \
  --symbol SPY \
  --entry-csv logs/webull_SPY_M30_candles.csv \
  --exit-csv logs/webull_SPY_M5_candles.csv
```

To run the improved Webull watchlist backtest:

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

Combined reports:

```text
logs/webull_watchlist_backtest_summary.csv
logs/webull_watchlist_backtest_summary.md
```

To compare strategy variants without fetching new Webull data:

```bash
python run_webull_watchlist.py \
  --symbols QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --variants current quality_entry
```

To fetch deeper paged history:

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

You can test other symbols:

```bash
python main.py --symbol QQQ --period 60d
python main.py --symbol NVDA --period 60d
python main.py --symbol TSLA --period 60d
python main.py --symbol AMD --period 60d
python main.py --symbol AAPL --period 60d
```

## Where Results Show Up

After a successful run, open the `logs/` folder.

The most important file is the summary report:

```text
logs/SYMBOL_60d_30m_entry_5m_exit_summary.md
```

Example:

```text
logs/SPY_60d_30m_entry_5m_exit_summary.md
```

The summary report explains:

```text
baseline results
elite A-setup results
win rate
expectancy
profit factor
drawdown
grade breakdown
which files to review next
```

Other files:

```text
baseline_trades.csv = simulated trades from baseline strategy
elite_trades.csv = simulated trades from stricter A-setup strategy
baseline_by_grade.csv = A/B/C performance comparison
baseline_chart.png = chart with baseline entries/exits
elite_chart.png = chart with elite entries/exits
```

## Current Operational Priority

CSV import and Webull market-data-only collection are implemented. The
priority now is reliable forward paper validation.

The Tuesday, May 26, 2026 regular session has been captured through the close
with a market-data-only Webull refresh. No current-candle paper candidate was
available during monitored scans, so no paper trade or forward observation
was recorded. The next regular session is Wednesday, May 27, 2026. Until
same-session Webull data produces a manually reviewed current-candle candidate,
keep paper import and position sizing blocked.

Before Wednesday:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_premarket_verification.py
```

During regular market hours on Wednesday:

```bash
source .venv-webull/bin/activate
python run_daily_workflow.py --refresh-data
```

The first forward paper-validation checkpoint is 30 allowed completed trades;
the stronger checkpoint is 60. Live trading and broker order execution remain
off.

## Historical Data Blocker

The current data source is Yahoo Finance through `yfinance`.

Recently, the data request failed with:

```text
Could not resolve host: guce.yahoo.com
```

That means the strategy code can run, but the data provider was unreachable.

This is why CSV import and Webull market-data CSV collection were added.

Webull OpenAPI access has been approved, and the local `.env` file now stores
the user's Webull app key and app secret. Do not print or expose those values.

A data-only Webull connection probe has been added:

```text
tools/check_webull_data.py
```

The current main project virtual environment uses Python 3.14.4. The Webull
OpenAPI Python SDK does not fit Python 3.14 cleanly, so Webull testing uses a
separate Python 3.11 virtual environment:

```text
.venv-webull
```

Python 3.11.9 was installed, `.venv-webull` was created, and the Webull SDK was
installed successfully.

The Webull data-only probe reached Webull successfully and completed token
verification. The first market-data request then failed with:

```text
401 Unauthorized - Insufficient permission, please subscribe to stock quotes.
```

The user claimed the free Nasdaq Basic - Non Display subscription. After that,
the Webull probe succeeded for SPY M5 candles.

To rerun the current Webull data-only probe:

```bash
source .venv-webull/bin/activate
python tools/check_webull_data.py --symbol SPY --timespan M5 --count 20
```

Successful output files:

```text
logs/webull_probe_SPY_M5.json
logs/webull_probe_SPY_M5_candles.csv
```

## Recommended Next Development Tasks

Ask the AI coding assistant to do these in order:

### 0. Test Webull Market Data

Goal:

```text
Use Webull OpenAPI for market-data-only candle retrieval.
```

Keep this data-only. Do not add order placement or live execution.

### 1. Add CSV Import

Status:

```text
Done. main.py now supports --entry-csv and --exit-csv.
Done. run_import_candles_csv.py normalizes provider exports into the local
webull_SYMBOL_TIMEFRAME_candles.csv reuse-cache format.
```

Goal:

```text
Allow the bot to backtest from local CSV files instead of only Yahoo.
```

Example future command:

```bash
python main.py --entry-csv data/SPY_30m.csv --exit-csv data/SPY_5m.csv
```

Expected CSV columns:

```text
datetime,open,high,low,close,volume
```

Verified with:

```bash
python main.py --symbol SPY --entry-csv logs/webull_SPY_M30_candles.csv --exit-csv logs/webull_SPY_M5_candles.csv
```

Provider-export import example:

```bash
python run_import_candles_csv.py --symbol SPY --timeframe M30 --source-csv data/SPY_30m.csv --output-dir logs/external_history
python run_import_candles_csv.py --symbol SPY --timeframe M5 --source-csv data/SPY_5m.csv --output-dir logs/external_history
python run_webull_watchlist.py --symbols SPY --reuse-csv --output-dir logs/external_history --candidate-preset best_plus_market
```

The command completed and saved reports under `logs/`. The limited sample
produced zero trades, which means no qualifying signal occurred in that small
data window.

### 2. Add Multi-Symbol Runner

Status:

```text
Initial Webull watchlist runner added.
```

Goal:

```text
Run SPY, QQQ, NVDA, TSLA, AMD, AAPL, META, MSFT together.
```

Example future command:

```bash
python scan.py --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT --period 60d
```

Output should be one combined summary table.

Current runner:

```text
run_webull_watchlist.py
```

Latest 1200-candle Webull run:

```text
SPY baseline: 9 trades, -0.1040R expectancy; elite: 0 trades
QQQ baseline: 12 trades, -0.1557R expectancy; elite: 0 trades
NVDA baseline: 4 trades, -0.1934R expectancy; elite: 0 trades
TSLA baseline: 4 trades, 0.7858R expectancy; elite: 0 trades
AMD baseline: 5 trades, 0.0890R expectancy; elite: 1 trade, -0.7749R expectancy
AAPL baseline: 10 trades, -0.3682R expectancy; elite: 0 trades
META baseline: 0 trades; elite: 0 trades
MSFT baseline: 2 trades, 0.2299R expectancy; elite: 0 trades
```

Interpretation: the baseline is mixed and still sample-limited. Elite filters
are probably too strict or need more history before they can be judged.

Diagnostics and variants were added:

```text
reports/diagnostics.py
run_webull_watchlist.py --variants ...
```

Important diagnostic finding:

```text
The opening range filter is restrictive, but removing it generally increased
trades while making expectancy worse. That suggests it is helping.
```

New research variant:

```text
quality_entry
```

This tests whether high-quality conditions should trigger directly instead of
also requiring the baseline pullback/reclaim entry. Early sample results were
mixed but more interesting than the original elite signal:

```text
QQQ quality_entry: 1 elite trade, -1.0000R
NVDA quality_entry: 1 elite trade, +0.3465R
TSLA quality_entry: 1 elite trade, +0.2895R
AMD quality_entry: 2 elite trades, -0.4146R average
AAPL quality_entry: 2 elite trades, +0.8923R average
META/MSFT quality_entry: 0 elite trades
```

First deeper-history paging result:

```text
TSLA with 2400 M30 candles and 7200 M5 candles:
current baseline: 7 trades, 71.43% win rate, +0.4977R expectancy, 5.8198 profit factor
quality_entry elite: 2 trades, 50.00% win rate, -0.0920R expectancy, 0.6114 profit factor
```

Latest full paged watchlist run:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --entry-count 1200 \
  --exit-count 1200 \
  --entry-pages 2 \
  --exit-pages 6 \
  --pause 8 \
  --variants current quality_entry
```

This produced 2400 M30 candles and 7200 M5 candles per symbol.

Key results:

```text
SPY current baseline: 32 trades, +0.0260R expectancy, 1.1372 profit factor
QQQ current baseline: 28 trades, +0.0164R expectancy, 1.1035 profit factor
QQQ quality_entry: 4 elite trades, +0.5196R expectancy, 2.9542 profit factor
NVDA current baseline: 21 trades, -0.0461R expectancy
NVDA quality_entry: 7 elite trades, -0.0133R expectancy
TSLA current baseline: 7 trades, +0.4977R expectancy, 5.8198 profit factor
AMD quality_entry: 7 elite trades, +0.0219R expectancy, 1.0671 profit factor
AAPL quality_entry: 2 elite trades, +0.8923R expectancy, 9.2851 profit factor
META current baseline: 10 trades, -0.2645R expectancy
MSFT current baseline: 9 trades, +0.0622R expectancy, 1.4453 profit factor
```

Research read: current baseline is slightly positive on SPY/QQQ/MSFT and strong
but low-count on TSLA. `quality_entry` looks most interesting on QQQ, but still
has too few trades to trust.

Exit profile testing was added:

```text
current
target_1_5r
no_vwap_exit
breakeven_after_1r
```

Command used:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --variants current quality_entry \
  --exit-profiles current target_1_5r no_vwap_exit breakeven_after_1r
```

Best current-baseline exits:

```text
TSLA no_vwap_exit: 7 trades, +0.5254R expectancy, 7.0988 profit factor
MSFT target_1_5r: 9 trades, +0.1697R expectancy, 2.2146 profit factor
QQQ no_vwap_exit: 21 trades, +0.0711R expectancy, 1.4387 profit factor
AMD no_vwap_exit: 23 trades, +0.0595R expectancy, 1.2463 profit factor
SPY no_vwap_exit: 26 trades, +0.0371R expectancy, 1.1510 profit factor
```

Best quality-entry exits:

```text
AAPL no_vwap_exit: 2 trades, +1.7001R expectancy
QQQ no_vwap_exit: 4 trades, +0.6317R expectancy, 3.5268 profit factor
NVDA no_vwap_exit: 7 trades, +0.2372R expectancy, 2.0146 profit factor
AMD no_vwap_exit: 7 trades, +0.1923R expectancy, 1.6500 profit factor
```

Research read: `no_vwap_exit` improved most symbols. The VWAP-loss exit may be
cutting trades too early.

Exit-reason breakdown was added to reports:

```text
logs/SYMBOL_VARIANT_EXIT_webull_30m_entry_5m_exit_baseline_by_exit_reason.csv
logs/SYMBOL_VARIANT_EXIT_webull_30m_entry_5m_exit_elite_by_exit_reason.csv
```

Key confirmation:

```text
QQQ current/current:
lost_vwap_5m had 14 trades, 0% win rate, -0.2886R expectancy.
end_of_day_exit had 14 trades, 78.57% win rate, +0.3213R expectancy.

AMD current/current:
lost_vwap_5m had 12 trades, 0% win rate, -0.4095R expectancy.
end_of_day_exit had 9 trades, 44.44% win rate, +0.1789R expectancy.
```

Research read: the 5m VWAP-loss exit appears to be cutting trades too early in
this sample.

Softer exit profiles were tested:

```text
two_vwap_closes
bearish_vwap_loss
ema9_exit
```

Average expectancy across symbols:

```text
current baseline:
no_vwap_exit: +0.0544R average
two_vwap_closes: +0.0344R average
bearish_vwap_loss: +0.0057R average
current: -0.0080R average
ema9_exit: -0.0477R average

quality_entry elite:
no_vwap_exit: +0.3076R average
two_vwap_closes: +0.1737R average
bearish_vwap_loss: +0.1471R average
current: +0.1225R average
ema9_exit: -0.0762R average
```

Conclusion: the softer exits help versus current, but `no_vwap_exit` is still
the best research candidate on this sample.

Best-candidate preset was added:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best
```

This compares:

```text
current + no_vwap_exit = more active baseline candidate
quality_entry + no_vwap_exit = more selective quality candidate
```

Focused report:

```text
logs/best_candidate_summary.md
```

Candidate selection report:

```text
logs/candidate_selection_report.md
```

Pass rule:

```text
expectancy_r > 0
profit_factor > 1
```

Current selected long candidates:

```text
SPY: current + no_vwap_exit
QQQ: quality_entry + no_vwap_exit
NVDA: quality_entry + no_vwap_exit
TSLA: current + no_vwap_exit
AMD: quality_entry + no_vwap_exit
AAPL: quality_entry + no_vwap_exit
MSFT: current + no_vwap_exit
META: reject for long strategy for now
```

Important: AAPL has only 2 selected trades, so treat it as promising but
low-confidence.

Current best entry/exit candidate:

```text
Entry: quality_entry
Exit: no_vwap_exit
```

Current broader candidate:

```text
Entry: current baseline
Exit: no_vwap_exit
```

### 3. Add Better Data Provider

Possible sources:

```text
Webull OpenAPI
Alpaca
Polygon.io
local CSV
```

Webull is likely the long-term fit if API access is approved.

### 4. Add Live Alert Mode

Only after backtesting works:

```text
alert only
no real trades
show A-setup candidates
show stop, target, R, and reason
```

### 5. Add Paper Trading

Only after live alerts behave correctly:

```text
simulated orders
fake fills
journal
daily report
no real money
```

### 6. Optional Webull Execution

Only after the system is proven:

```text
manual approval first
hard stops required
max trades per day
max daily loss
kill switch
no martingale
no averaging down
```

## How We Know The Strategy Is Getting Better

Focus on the elite A-setup report.

Promising signs:

```text
expectancy_r > 0
profit_factor > 1.3
drawdown controlled
enough trades to matter
elite better than baseline
```

Not ready:

```text
expectancy_r below 0
profit_factor below 1
drawdown too large
too few trades
elite does not improve baseline
```

## Important Safety Principle

Do not connect this to real Webull execution yet.

Current phase:

```text
research and backtesting
```

Correct order:

```text
1. Backtest
2. Improve rules
3. Test many symbols
4. Build live alerts
5. Paper trade
6. Consider real execution only after proof
```

## Latest Confidence Filter

Added a sample-size confidence filter to the best-candidate runner.

Command:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best \
  --min-approved-trades 10
```

Default rule:

```text
approved = expectancy_r > 0, profit_factor > 1, and trades >= 10
watch_more = expectancy_r > 0 and profit_factor > 1, but trades < 10
reject = fails expectancy/profit-factor math rule
```

Latest status from `logs/candidate_selection_report.md`:

```text
SPY: approved, current + no_vwap_exit, 26 trades, +0.0371R expectancy, 1.151 PF
AAPL: watch_more, quality_entry + no_vwap_exit, 2 trades, +1.7001R expectancy, infinite PF
QQQ: watch_more, quality_entry + no_vwap_exit, 4 trades, +0.6317R expectancy, 3.5268 PF
TSLA: watch_more, current + no_vwap_exit, 7 trades, +0.5254R expectancy, 7.0988 PF
NVDA: watch_more, quality_entry + no_vwap_exit, 7 trades, +0.2372R expectancy, 2.0146 PF
AMD: watch_more, quality_entry + no_vwap_exit, 7 trades, +0.1923R expectancy, 1.65 PF
MSFT: watch_more, current + no_vwap_exit, 9 trades, +0.0772R expectancy, 1.5893 PF
META: reject, current + no_vwap_exit, 11 trades, -0.0909R expectancy, 0.5018 PF
```

Current interpretation:

```text
Only SPY is approved under the 10-trade confidence rule.
QQQ, NVDA, TSLA, AMD, AAPL, and MSFT are promising but need more historical trades.
META remains rejected for this long strategy.
```

## Latest Deeper Watchlist Result

After pulling deeper Webull history and rerunning the best-candidate preset,
the current approval universe is:

```text
QQQ: approved, quality_entry + no_vwap_exit, 10 trades, +0.3754R expectancy, 2.2513 PF
TSLA: approved, current + no_vwap_exit, 25 trades, +0.0426R expectancy, 1.1323 PF
SPY: approved, current + no_vwap_exit, 26 trades, +0.0371R expectancy, 1.151 PF
AMD: watch_more, quality_entry + no_vwap_exit, 9 trades, +0.3831R expectancy, 2.6644 PF
MSFT: reject, current + no_vwap_exit, 44 trades, -0.0026R expectancy, 0.987 PF
AAPL: reject, current + no_vwap_exit, 62 trades, -0.0350R expectancy, 0.8831 PF
NVDA: reject, quality_entry + no_vwap_exit, 16 trades, -0.0822R expectancy, 0.806 PF
META: reject, current + no_vwap_exit, 11 trades, -0.0909R expectancy, 0.5018 PF
```

Current interpretation:

```text
Approved: SPY, QQQ, TSLA
Almost approved: AMD, but it has only 9 qualifying trades
Rejected for this long strategy: AAPL, NVDA, MSFT, META
```

Important research note:

```text
More data made the system stricter. AAPL, NVDA, and MSFT looked promising in
small samples but failed after deeper history, so they should not be trusted
for the current long strategy.
```

## Latest Market-Regime Filter Result

Added SPY-confirmed market-regime variants:

```text
market_confirmed
quality_entry_market_confirmed
```

Market confirmation rule:

```text
SPY close > SPY VWAP
SPY close > SPY 21 EMA
SPY 9 EMA > SPY 21 EMA
```

Command:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best_plus_market \
  --market-regime-symbol SPY \
  --min-approved-trades 10
```

Latest approved/watch/reject universe:

```text
QQQ: approved, quality_entry + no_vwap_exit, 10 trades, +0.3754R expectancy, 2.2513 PF
TSLA: approved, market_confirmed + no_vwap_exit, 17 trades, +0.2151R expectancy, 2.1985 PF
AAPL: approved, market_confirmed + no_vwap_exit, 33 trades, +0.1545R expectancy, 1.7618 PF
SPY: approved, current + no_vwap_exit, 118 trades, +0.0375R expectancy, 1.1415 PF
AMD: watch_more, quality_entry + no_vwap_exit, 9 trades, +0.3831R expectancy, 2.6644 PF
MSFT: reject, current + no_vwap_exit, 44 trades, -0.0026R expectancy, 0.987 PF
META: reject, quality_entry_market_confirmed + no_vwap_exit, 2 trades, -0.0640R expectancy, 0.0 PF
NVDA: reject, quality_entry + no_vwap_exit, 16 trades, -0.0822R expectancy, 0.806 PF
```

Interpretation:

```text
The SPY market-regime filter helped TSLA and AAPL.
QQQ still prefers the non-market quality_entry candidate.
SPY still prefers the original current candidate.
AMD is still promising but one qualifying trade short.
NVDA, MSFT, and META remain rejected for this long strategy.
```

## Setup B Started

Setup A remains unchanged and preserved as the approved long-side setup family.

Setup B has been added as bearish VWAP + EMA trend continuation research.
It is short-side backtesting only, not live trading.

New implementation pieces:

```text
strategies/opening_trend_continuation_short.py
backtesting.engine.run_short_backtest()
backtesting.engine.find_short_exit()
risk_management.rules.build_short_risk()
```

New runner variants:

```text
setup_b_short
setup_b_quality_short
```

New runner preset:

```text
setup_b
```

Command:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset setup_b \
  --min-approved-trades 10
```

Setup B latest result:

```text
TSLA: approved, setup_b_short + no_vwap_exit, 23 trades, +0.1547R expectancy, 1.6527 PF
AMD: approved, setup_b_short + no_vwap_exit, 47 trades, +0.1268R expectancy, 1.575 PF
QQQ: approved, setup_b_short + no_vwap_exit, 26 trades, +0.0608R expectancy, 1.2714 PF
AAPL: approved, setup_b_short + no_vwap_exit, 41 trades, +0.0379R expectancy, 1.1557 PF
META: watch_more, setup_b_quality_short + no_vwap_exit, 4 trades, +0.5944R expectancy, 22.0967 PF
MSFT: watch_more, setup_b_quality_short + no_vwap_exit, 5 trades, +0.3538R expectancy, 2.6144 PF
NVDA: watch_more, setup_b_quality_short + no_vwap_exit, 9 trades, +0.1141R expectancy, 1.2166 PF
SPY: watch_more, setup_b_quality_short + no_vwap_exit, 7 trades, +0.0154R expectancy, 1.046 PF
```

Important interpretation:

```text
Setup B is promising, especially on TSLA and AMD.
NVDA is closest to approval among the old rejected Setup A names, but it needs one more qualifying quality-short trade.
META and MSFT have attractive quality-short stats, but too few trades to trust yet.
```

Labeled reports:

```text
logs/setup_a_candidate_selection_report.md
logs/setup_a_candidate_summary.md
logs/setup_a_watchlist_backtest_summary.csv
logs/setup_a_watchlist_backtest_summary.md

logs/setup_b_candidate_selection_report.md
logs/setup_b_candidate_summary.md
logs/setup_b_watchlist_backtest_summary.csv
logs/setup_b_watchlist_backtest_summary.md
```

## Latest Setup B Deeper Test

Pulled deeper Webull history for NVDA, MSFT, and META, then reran Setup B
across the full watchlist.

Command used for deeper data:

```bash
python run_webull_watchlist.py \
  --symbols NVDA MSFT META \
  --entry-count 1200 \
  --exit-count 1200 \
  --entry-pages 12 \
  --exit-pages 36 \
  --pause 6 \
  --candidate-preset setup_b \
  --min-approved-trades 10
```

Latest Setup B status:

```text
TSLA: approved, setup_b_short + no_vwap_exit, 23 trades, +0.1547R expectancy, 1.6527 PF
AMD: approved, setup_b_short + no_vwap_exit, 47 trades, +0.1268R expectancy, 1.575 PF
QQQ: approved, setup_b_short + no_vwap_exit, 26 trades, +0.0608R expectancy, 1.2714 PF
NVDA: approved, setup_b_short + no_vwap_exit, 66 trades, +0.0494R expectancy, 1.1593 PF
AAPL: approved, setup_b_short + no_vwap_exit, 41 trades, +0.0379R expectancy, 1.1557 PF
META: watch_more, setup_b_quality_short + no_vwap_exit, 9 trades, +0.4659R expectancy, 2.9847 PF
MSFT: watch_more, setup_b_quality_short + no_vwap_exit, 6 trades, +0.2693R expectancy, 2.2941 PF
SPY: watch_more, setup_b_quality_short + no_vwap_exit, 7 trades, +0.0154R expectancy, 1.046 PF
```

Interpretation:

```text
NVDA is now approved under Setup B.
META is one quality-short trade short of approval.
MSFT remains promising but under-sampled.
```

## Approved Playbook Runner

Added the approved playbook config and runner:

```text
config/symbol_playbook.py
run_playbook.py
```

Command:

```bash
python run_playbook.py --mode approved
```

Approved playbook entries:

```text
SPY: Setup A Long, current + no_vwap_exit
QQQ: Setup A Long, quality_entry + no_vwap_exit
TSLA: Setup A Long, market_confirmed + no_vwap_exit
AAPL: Setup A Long, market_confirmed + no_vwap_exit
TSLA: Setup B Short, setup_b_short + no_vwap_exit
AMD: Setup B Short, setup_b_short + no_vwap_exit
QQQ: Setup B Short, setup_b_short + no_vwap_exit
NVDA: Setup B Short, setup_b_short + no_vwap_exit
AAPL: Setup B Short, setup_b_short + no_vwap_exit
```

Latest approved playbook result:

```text
Trades: 381
Win rate: 0.5118
Expectancy R: +0.0862
Profit factor: 1.3417
Max drawdown R: -10.0424
```

By setup:

```text
Setup A Long: 178 trades, +0.0952R expectancy, 1.3845 PF
Setup B Short: 203 trades, +0.0784R expectancy, 1.3055 PF
```

Generated files:

```text
logs/playbook_approved_trades.csv
logs/playbook_approved_summary.csv
logs/playbook_approved_summary.md
```

Important limitation:

```text
This is not yet a true portfolio simulator. It combines R results trade-by-trade but does not yet enforce cross-symbol capital allocation, overlapping-position limits, or portfolio-level daily risk caps.
```

## Portfolio Simulator Added

Added portfolio-level simulation on top of the approved playbook:

```text
run_portfolio.py
```

Default command:

```bash
python run_portfolio.py --name approved
```

Default rules:

```text
max open positions = 3
max open positions per symbol = 1
max trades per day = 5
max daily realized loss = -3R
```

Default portfolio result:

```text
Accepted trades: 373
Skipped trades: 8
Win rate: 0.5121
Expectancy R: +0.0876
Profit factor: 1.3473
Max drawdown R: -10.0424
```

Default files:

```text
logs/portfolio_approved_accepted_trades.csv
logs/portfolio_approved_skipped_trades.csv
logs/portfolio_approved_daily_summary.csv
logs/portfolio_approved_summary.md
```

Strict test command:

```bash
python run_portfolio.py \
  --name approved_strict \
  --max-open-positions 2 \
  --max-open-per-symbol 1 \
  --max-trades-per-day 4 \
  --max-daily-loss-r -2
```

Strict portfolio result:

```text
Accepted trades: 347
Skipped trades: 34
Win rate: 0.5101
Expectancy R: +0.0829
Profit factor: 1.3228
Max drawdown R: -9.6751
```

Interpretation:

```text
The strict profile reduces drawdown slightly but skips many more trades and lowers expectancy/profit factor.
The default profile is the better current balance.
```

## Portfolio Robustness Reports

Extended `run_portfolio.py` to generate:

```text
logs/portfolio_approved_equity_curve.csv
logs/portfolio_approved_monthly_summary.csv
logs/portfolio_approved_drawdown_stretches.csv
```

Default portfolio after regeneration:

```text
Accepted trades: 373
Skipped trades: 8
Win rate: 0.5121
Expectancy R: +0.0876
Profit factor: 1.3473
Final cumulative R: +32.6832
Max drawdown R: -10.0424
```

Worst months:

```text
2025-05: 16 trades, -6.4482R total, -0.4030R expectancy, 0.1555 PF
2026-01: 28 trades, -5.1208R total, -0.1829R expectancy, 0.4806 PF
2025-10: 19 trades, -3.7504R total, -0.1974R expectancy, 0.4019 PF
```

Worst drawdown stretch:

```text
Started trade 100 on 2025-04-16
Trough at trade 131 on 2025-06-10
Recovered at trade 251 on 2025-12-18
Max drawdown: -9.3604R
Duration: 152 trades
```

Next recommended task:

```text
Promote the monthly -3R portfolio loss stop as the current preferred research profile, then continue improving entries/exits inside that safer portfolio shell.
```

## Current Best Portfolio Profile

Added a named portfolio preset:

```bash
python run_portfolio.py --profile monthly_stop_3r
```

This preset applies:

```text
Max open positions: 3
Max open positions per symbol: 1
Max trades per day: 5
Max daily realized loss: -3R
Max monthly realized loss: -3R
```

Latest result:

```text
Accepted trades: 340
Skipped trades: 44
Win rate: 0.5172
Expectancy R: +0.1135
Profit factor: 1.4677
Final cumulative R: +38.5937
Max drawdown R: -6.5803
```

Why this matters:

```text
The previous default portfolio had +0.0876R expectancy, 1.3473 profit factor, +32.6832R final cumulative R, and -10.0424R max drawdown.

The monthly -3R stop improved expectancy, profit factor, total R, and drawdown at the same time.
This is the strongest current risk-control upgrade.
```

## Exit Optimizer Upgrade

Added:

```text
run_exit_optimizer.py
```

The optimizer keeps the approved playbook fixed, changes one exit profile at a
time, and scores the result through the `monthly_stop_3r` portfolio profile.

Best individual changes:

```text
AAPL Setup B Short: no_vwap_exit -> two_vwap_closes
TSLA Setup A Long: no_vwap_exit -> two_vwap_closes
```

Testing both together improved the current best portfolio:

```text
Previous monthly_stop_3r:
348 accepted trades, +0.1069R expectancy, 1.4303 PF, -6.9918R max drawdown, +37.2058R final cumulative R

Updated approved playbook:
340 accepted trades, +0.1135R expectancy, 1.4677 PF, -6.5803R max drawdown, +38.5937R final cumulative R
```

The approved playbook now uses:

```text
TSLA Setup A Long: market_confirmed + two_vwap_closes
AAPL Setup B Short: setup_b_short + two_vwap_closes
```

Next recommended task:

```text
Use the exit optimizer report to decide whether to test entry-filter upgrades next, especially on SPY and NVDA, which still have the weakest expectancy inside the approved portfolio.
```

## Entry Optimizer Pass

Added:

```text
run_entry_optimizer.py
```

First targeted pass:

```bash
python run_entry_optimizer.py --symbols SPY NVDA
```

Result:

```text
No promotable SPY or NVDA entry upgrade.
NVDA setup_b_quality_short improved drawdown slightly, but lowered expectancy and final R.
SPY quality/market-confirmed variants lowered expectancy and final R.
```

Then ran a broader approved-symbol pass:

```bash
python run_entry_optimizer.py --symbols SPY QQQ TSLA AAPL AMD NVDA
```

Best one-change result:

```text
QQQ Setup B Short: setup_b_short -> setup_b_quality_short
Expectancy: +0.1150R versus +0.1135R baseline
Profit factor: 1.4678 versus 1.4677 baseline
Final cumulative R: +37.6103R versus +38.5937R baseline
```

Interpretation:

```text
Do not promote the QQQ short quality-entry change. The expectancy improvement is tiny, and it gives up nearly 1R of final cumulative return.
No entry-filter upgrade is approved from this pass.
The current approved playbook remains unchanged after the entry optimizer.
```

Next recommended task:

```text
Move from broad entry/exit swaps to targeted weakness analysis: inspect SPY long and NVDA short losing trades by month, time of day, quality score, and exit reason to find a more specific filter.
```

## Weakness Analyzer And Filter V1

Added:

```text
run_weakness_analyzer.py
```

Ran:

```bash
python run_weakness_analyzer.py --focus-symbols SPY NVDA
```

Key weak spots found:

```text
NVDA Setup B Short, 11-12 ET: 7 trades, -0.3155R expectancy, -2.2083R total
NVDA Setup B Short, relative volume 1.25-1.5: 6 trades, -0.7126R expectancy, -4.2757R total
NVDA Setup B Short, relative volume 0.75-1.0: 12 trades, -0.2462R expectancy, -2.9540R total
SPY Setup A Long, room-to-target 0.75R-1.0R: 6 trades, -0.2339R expectancy, -1.4031R total
```

Added optional portfolio trade filter:

```bash
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
```

`weakness_v1` blocks:

```text
NVDA Setup B Short: 11am ET entries
NVDA Setup B Short: relative volume 0.75-1.0 and 1.25-1.5
SPY Setup A Long: room-to-target 0.75R-1.0R
```

Result:

```text
Accepted trades: 325
Skipped trades: 31
Raw trades blocked by filter: 28
Win rate: 0.5354
Expectancy R: +0.1446
Profit factor: 1.6707
Final cumulative R: +46.9839
Max drawdown R: -6.5803
```

Comparison to prior best:

```text
Previous monthly_stop_3r:
340 accepted trades, +0.1135R expectancy, 1.4677 PF, -6.5803R max drawdown, +38.5937R final cumulative R

weakness_v1:
325 accepted trades, +0.1446R expectancy, 1.6707 PF, -6.5803R max drawdown, +46.9839R final cumulative R
```

Interpretation:

```text
weakness_v1 is the current best research profile, but it may be sample-fit because it was built from weakness analysis on the existing trade set.
Do not treat it as a live-trading rule until validated on fresh data or a holdout period.
```

Next recommended task:

```text
Add a holdout/validation runner to compare base monthly_stop_3r versus weakness_v1 on earlier vs later date ranges.
```

## Holdout Validation

Added:

```text
run_holdout_validation.py
```

Ran:

```bash
python run_holdout_validation.py
```

This compares base `monthly_stop_3r` versus `monthly_stop_3r --trade-filter weakness_v1`
across full sample, first half, second half, and calendar years.

Validation result:

```text
full_sample:
base +0.1135R expectancy, 1.4677 PF, +38.5937R final
weakness_v1 +0.1446R expectancy, 1.6707 PF, +46.9839R final

first_half:
base +0.0837R expectancy, 1.3598 PF, +14.5677R final
weakness_v1 +0.1283R expectancy, 1.6232 PF, +20.3957R final

second_half:
base +0.1447R expectancy, 1.5717 PF, +24.0260R final
weakness_v1 +0.1602R expectancy, 1.7125 PF, +26.5882R final

2024:
base +0.0663R expectancy, 1.2813 PF, +2.9846R final
weakness_v1 +0.1825R expectancy, 2.1357 PF, +6.2038R final

2025:
base +0.0742R expectancy, 1.2927 PF, +14.0212R final
weakness_v1 +0.0980R expectancy, 1.4357 PF, +18.7242R final

2026:
base +0.2037R expectancy, 1.8993 PF, +21.5879R final
weakness_v1 +0.2206R expectancy, 2.0204 PF, +22.0559R final
```

Interpretation:

```text
weakness_v1 improved expectancy and profit factor in every internal validation window.
It also improved final cumulative R in every window.
This makes weakness_v1 the strongest current research profile.
However, because it was discovered from the same broad historical sample, it still needs fresh-data validation before live/paper-trade confidence.
```

Next recommended task:

```text
Pull or append fresh Webull candle data later and rerun:
python run_playbook.py --mode approved
python run_portfolio.py --profile monthly_stop_3r
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
python run_holdout_validation.py
```

## Paper Workflow Artifacts

Added:

```text
PLAYBOOK_CHEATSHEET.md
run_signal_journal.py
```

The cheat sheet describes:

```text
Trade style
Approved setup list
weakness_v1 blocks
Portfolio risk rules
Entry checklist
Paper signal fields
Safety rules
Fresh-data validation commands
```

Generated paper signal journal:

```bash
python run_signal_journal.py --trade-filter weakness_v1 --latest 30
```

Outputs:

```text
logs/paper_signal_journal.csv
logs/paper_signal_journal.md
```

Added journal insight report:

```text
run_journal_insights.py
logs/journal_insights.md
```

Ran:

```bash
python run_journal_insights.py
```

Key journal implications:

```text
weakness_v1 is focused, not broad. It blocks only 28 historical signals.
Blocked signals came only from NVDA and SPY.
Allowed signals: 356 signals, +0.1202R average, +42.8060R total.
Blocked signals: 28 signals, -0.3469R average, -9.7125R total.
Strongest allowed symbol after filtering: NVDA, +0.2560R average.
Weakest allowed symbol after filtering: SPY, +0.0530R average.
```

Paper-trading watch points:

```text
Track every allowed signal.
Track every blocked signal as watch-only.
Compare fresh allowed average R against +0.1202R.
Compare fresh blocked average R against -0.3469R.
If blocked signals start outperforming allowed signals on fresh data, review weakness_v1.
```

Latest journal summary:

```text
Allowed historical signals: 356
Blocked historical signals: 28
Allowed average historical R: +0.1202
Blocked average historical R: -0.3469
Blocked total historical R: -9.7125
```

Blocked signal reasons:

```text
blocked_nvda_short_relvol_1_25_to_1_5: 6 signals, -4.2757R total
blocked_nvda_short_11am_et: 7 signals, -2.2083R total
blocked_nvda_short_relvol_0_75_to_1_0: 8 signals, -1.7789R total
blocked_spy_long_room_0_75_to_1_0: 7 signals, -1.4496R total
```

Next recommended task:

```text
When fresh Webull data is available, run the fresh-data validation sequence. Until then, use PLAYBOOK_CHEATSHEET.md and logs/paper_signal_journal.md as the paper workflow reference.
```

## Research Pipeline Runner

Added:

```text
run_research_pipeline.py
```

Ran:

```bash
python run_research_pipeline.py
```

The pipeline regenerates:

```text
Approved playbook
Base monthly_stop_3r portfolio
monthly_stop_3r + weakness_v1 portfolio
Holdout validation
Paper signal journal
Journal insights
Master pipeline summary
```

Master output:

```text
logs/research_pipeline_summary.md
```

Latest pipeline summary:

```text
Base monthly_stop_3r:
340 accepted trades, +0.1135R expectancy, 1.4677 PF, -6.5803R max drawdown, +38.5937R final cumulative R

weakness_v1:
325 accepted trades, +0.1446R expectancy, 1.6707 PF, -6.5803R max drawdown, +46.9839R final cumulative R

Paper journal:
356 allowed signals, +0.1202R average, +42.8060R total
28 blocked signals, -0.3469R average, -9.7125R total
```

Use this as the default command after fresh data is added:

```bash
python run_research_pipeline.py
```

## 2026-05-23 Fresh Webull Validation

Pulled fresh Webull data with:

```bash
python run_webull_watchlist.py --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT --entry-count 1200 --exit-count 1200 --entry-pages 2 --exit-pages 6 --pause 5 --candidate-preset best_plus_market

python run_webull_watchlist.py --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT --entry-count 1200 --exit-count 1200 --entry-pages 2 --exit-pages 6 --pause 5 --candidate-preset setup_b
```

Then reran:

```bash
python run_research_pipeline.py
```

Fresh approved playbook:

```text
113 trades
+0.1842R expectancy before portfolio rules
```

Fresh portfolio comparison:

```text
Base monthly_stop_3r:
104 accepted trades
9 skipped trades
0 raw trades blocked
0.5481 win rate
+0.1987R expectancy
1.8761 profit factor
-4.9038R max drawdown
+20.6687R final cumulative R

weakness_v1:
94 accepted trades
12 skipped trades
7 raw trades blocked
0.5638 win rate
+0.2223R expectancy
1.9859 profit factor
-4.2148R max drawdown
+20.8980R final cumulative R
```

Fresh holdout result:

```text
full_sample: weakness_v1 improved expectancy by +0.0236R and final R by +0.2293R
first_half: weakness_v1 improved expectancy by +0.0311R and final R by +1.1127R
second_half: weakness_v1 improved expectancy by +0.0031R but final R was -0.8834R lower
```

Fresh journal insight:

```text
Allowed signals: 106, +0.1965R average, +20.8288R total
Blocked signals: 7, -0.0023R average, -0.0159R total
Strongest allowed symbol: NVDA, +0.4578R average
Weakest allowed symbol: SPY, +0.0257R average
```

Interpretation:

```text
Fresh validation is positive overall. weakness_v1 still beat the base portfolio on expectancy, profit factor, drawdown, and final cumulative R.

The improvement is smaller than the original historical result.

The blocked group was nearly flat on fresh data, not strongly negative. This means weakness_v1 should remain in research/paper validation and should be monitored closely rather than treated as fully proven.
```

Current confidence:

```text
Research confidence improved.
Paper-trading readiness is closer, but still needs forward journal tracking.
Real-money readiness remains no.
```

## Forward Paper Review Tool

Built a manual paper-trade review workflow:

```text
data/paper_trades.csv
run_paper_review.py
logs/paper_review_summary.md
```

Use `data/paper_trades.csv` to log paper trades and watch-only blocked signals.
Then run:

```bash
python run_paper_review.py
```

The review compares fresh paper results against the latest allowed-signal
baseline of `+0.1965R` and blocked-signal baseline of `-0.0023R`.

Confidence checkpoints:

```text
30 allowed paper trades = first useful checkpoint
60 allowed paper trades = stronger checkpoint
```

## Daily Paper Signal Scanner

Built the daily scanner:

```text
run_daily_scanner.py
logs/daily_paper_signal_scanner.csv
logs/daily_paper_signal_scanner.md
logs/daily_paper_trade_import_template.csv
```

Command:

```bash
python run_daily_scanner.py
```

The scanner reads local `logs/webull_SYMBOL_M30_candles.csv` and
`logs/webull_SYMBOL_M5_candles.csv`, applies the approved playbook, and labels
each setup as:

```text
allowed
blocked_watch_only
not_ready
data_error
```

Latest local scan found:

```text
3 allowed signals
6 not_ready setups
```

All three allowed signals were from earlier in the latest local session, so
they are review/logging examples rather than fresh current-candle entries.

## Daily Workflow Cleanup

Added a one-command daily workflow and scanner import helper:

```text
run_daily_workflow.py
run_paper_import.py
logs/daily_workflow_summary.md
```

Normal daily run without network refresh:

```bash
python run_daily_workflow.py
```

Daily run with explicit Webull CSV refresh:

```bash
python run_daily_workflow.py --refresh-data
```

Safe paper-log import preview after reviewing a current-session candidate:

```bash
python run_paper_import.py --dry-run
```

Real paper-log import is now guarded at the file-write boundary:

```text
only current_candle allowed signals can be written; watch-only rows stay observations
scanner rows must be from today's session
the regular market session must currently be open
historical/earlier-today rows may be previewed but are not real paper imports
run_daily_workflow.py --append-current-signals is disabled pending human review
```

## Paper Position Sizer

Added:

```text
run_position_sizer.py
logs/position_sizing.csv
logs/position_sizing.md
```

Command:

```bash
python run_position_sizer.py
```

Default sizing assumptions:

```text
Account size: $10,000
Risk per trade: 0.50%
Risk budget: $50
Freshness filter: current_candle
```

The latest sizing run correctly produced no eligible paper sizes because all
allowed signals were `earlier_today`, not `current_candle`.

## Trade Management Lab

Added:

```text
run_trade_management_lab.py
logs/trade_management_lab.md
logs/trade_management_overall.csv
logs/trade_management_by_symbol.csv
logs/trade_management_by_setup.csv
```

Command:

```bash
python run_trade_management_lab.py
```

Latest result:

```text
Current playbook expectancy: +0.1842R
Best tested profile: tied with current management
Partial-at-1R profiles reduced expectancy
```

Interpretation:

```text
Do not switch to partial-at-1R yet. The current exits are still the research
leader on this sample.
```

## Project Dashboard

Added:

```text
run_dashboard.py
logs/project_gwala_dashboard.md
```

Command:

```bash
python run_dashboard.py
```

The dashboard combines scanner status, current-candle candidates, position
sizing, paper progress, portfolio health, holdout health, and trade-management
health into one report. The current dashboard says:

```text
No current-candle paper candidates.
No eligible current-candle position sizes.
Paper sample is still too small: 0 completed allowed trades.
Keep running the daily workflow until the 30-trade checkpoint.
```

## Intraday Paper Loop

Added:

```text
run_intraday_loop.py
logs/intraday_loop_status.md
```

Commands:

```bash
python run_intraday_loop.py
python run_intraday_loop.py --once
```

The loop runs the daily workflow with Webull refresh every 30 minutes during
regular market hours. It skips weekends and closed hours by default. Use
`--force` only for testing outside market hours.

This remains paper-only. It does not place orders or create broker alerts.

## Market Calendar

Added:

```text
config/market_calendar.py
run_market_calendar.py
```

The intraday loop now uses the calendar instead of a simple weekday check.
It recognizes regular NYSE holidays, observed fixed-date holidays, Good Friday,
and common 1pm ET early closes.

Verified examples:

```text
2026-05-24 = Weekend closed
2026-05-25 = Memorial Day closed
2026-05-26 = Regular session
2026-11-27 = Day after Thanksgiving early close, 09:30-13:00 ET
```

## Paper Outcome Updater

Added:

```text
run_update_paper_trade.py
```

List open rows:

```bash
python run_update_paper_trade.py --list-open
```

Update a paper-trade row:

```bash
python run_update_paper_trade.py --row 1 --actual-entry 100 --actual-exit 102 --exit-time 11:30 --followed-plan yes --exit-reason profit_target
```

It calculates `outcome_r` from actual entry, actual exit, planned stop, and
direction.

## Paper Validation Checkpoint

Added:

```text
run_checkpoint_report.py
logs/paper_validation_checkpoint.md
```

Command:

```bash
python run_checkpoint_report.py
```

Current expected state:

```text
0 allowed completed paper trades
30 trades remaining to first checkpoint
60 trades remaining to stronger checkpoint
```

## Paper Workflow Drill

Added:

```text
run_paper_drill.py
logs/paper_drill/paper_drill_summary.md
```

Command:

```bash
python run_paper_drill.py
```

Purpose:

```text
Rehearse the scanner -> completed paper trade -> paper review -> checkpoint
workflow in a sandbox folder.
```

Verified behavior:

```text
Creates logs/paper_drill/paper_drill_trades.csv
Creates logs/paper_drill/paper_review_summary.md
Creates logs/paper_drill/paper_validation_checkpoint.md
Leaves data/paper_trades.csv untouched
```

The drill now defaults to a full fake outcome set:

```text
planned win
planned loss
breakeven
plan break
```

For one custom fake outcome:

```bash
python run_paper_drill.py --scenario single --outcome-r 1.5
```

## Offline Paper Support Reports

Added:

```text
run_premarket_plan.py
run_trade_checklist.py
run_mistake_tracker.py
run_daily_recap.py
data/paper_mistakes.csv
logs/daily_trade_plan.md
logs/trade_entry_checklist.md
logs/paper_mistake_tracker.md
logs/daily_recap.md
```

Commands:

```bash
python run_premarket_plan.py
python run_trade_checklist.py
python run_mistake_tracker.py
python run_daily_recap.py
```

The normal daily workflow now runs these after scanner, sizing, review,
checkpoint, and dashboard:

```bash
python run_daily_workflow.py
```

Purpose:

```text
daily_trade_plan.md = before-market operating plan
trade_entry_checklist.md = required checks before any paper trade
paper_mistake_tracker.md = process mistakes and estimated R cost
daily_recap.md = end-of-day scanner/progress recap
```

## Market-Open Readiness Check

Added:

```text
run_readiness_check.py
logs/readiness_check.md
```

Command:

```bash
python run_readiness_check.py
```

It checks:

```text
market calendar
Webull key names in .env without printing values
local Webull M30/M5 CSV coverage for approved symbols
scanner freshness
eligible position sizes
paper-log schema and open outcome rows
support report files
paper progress toward the 30-trade gate
```

The normal daily workflow now updates readiness too:

```bash
python run_daily_workflow.py
```

Current Sunday/off-market verdict:

```text
During market hours, run python run_daily_workflow.py --refresh-data and wait
for current-candle candidates.
```

## Setup B Runner Cleanup

On 2026-05-24, the Setup B watchlist runner was cleaned up.

Fixed in:

```text
run_webull_watchlist.py
```

What changed:

```text
setup_b_short now uses elite_short_signal for its stricter comparison leg.
Preset runs now automatically save labeled archive reports.
```

When using a preset such as:

```bash
python run_webull_watchlist.py --reuse-csv --candidate-preset setup_b
```

The runner now saves:

```text
logs/setup_b_watchlist_backtest_summary.csv
logs/setup_b_watchlist_backtest_summary.md
logs/setup_b_candidate_summary.md
logs/setup_b_candidate_selection_report.md
```

Verification:

```bash
.venv/bin/python -m py_compile run_webull_watchlist.py
```

Note:

```text
A quick Setup B reuse test was run against the currently cached 1200-candle
local CSV files. Treat that as a wiring check, not as a replacement for the
archived deeper Setup B research reports.
```

## Off-Market Safety Improvements

Added stale-data warnings and a more decision-focused dashboard.

Changed:

```text
run_dashboard.py
run_daily_scanner.py
```

The dashboard now shows:

```text
Today's Action
Warnings
Data Freshness
Current-Candle Candidates
Eligible Position Sizes
Paper Progress
Portfolio/Holdout/Management health
```

If scanner data is stale, the dashboard says prep only, names the next market
session, and hides actionable candidate/sizing rows.

The scanner report now includes a Data Freshness table. If the rows come from
an older local session, the candidate section is labeled:

```text
Historical Candidates And Watch-Only Signals
```

with a warning not to import, size, or paper trade those rows until Webull data
is refreshed during the next open session.

Verified:

```bash
.venv/bin/python -m py_compile run_dashboard.py run_daily_scanner.py run_readiness_check.py
.venv/bin/python run_daily_scanner.py
.venv/bin/python run_dashboard.py
.venv/bin/python run_readiness_check.py
```

Current off-market action:

```text
On 2026-05-26, run python run_daily_workflow.py --refresh-data before
importing or sizing any paper trade.
```

## Setup Health Report

Added:

```text
run_setup_health.py
logs/setup_health.csv
logs/setup_health.md
```

Purpose:

```text
Score each approved playbook setup so we can see which setups are healthy,
which need more paper evidence, and which should be treated cautiously.
```

Inputs:

```text
logs/playbook_approved_trades.csv
```

Health uses:

```text
trade count
expectancy R
profit factor
max drawdown R
recent expectancy
recent profit factor
```

Status meanings:

```text
healthy = at least 30 trades and strong enough to keep paper-tracking
watch = positive but still needs monitoring
watch_more = promising but under-sampled below 10 trades
caution = weak math or recent weakness
```

The dashboard now includes a Setup Health section and warns when approved
setups need watch/caution review.

The daily workflow now runs setup health automatically before the dashboard:

```bash
python run_setup_health.py
```

Latest health read:

```text
watch: AAPL Setup A Long, QQQ Setup B Short, NVDA Setup B Short, TSLA Setup B Short, SPY Setup A Long
watch_more: QQQ Setup A Long, TSLA Setup A Long, AMD Setup B Short
caution: AAPL Setup B Short
```

Verified:

```bash
.venv/bin/python -m py_compile run_setup_health.py run_dashboard.py run_daily_workflow.py
.venv/bin/python run_setup_health.py
.venv/bin/python run_dashboard.py
```

## App-Ready System State

Added:

```text
reports/system_state.py
run_system_state.py
logs/system_state.json
logs/system_state.md
```

Purpose:

```text
Create one structured source of truth for future app/dashboard work.
```

The system-state JSON contains:

```text
schema_version
project_phase
safety flags
market status
data freshness
scanner status
position sizing status
paper progress
setup health
readiness verdict
source files
```

The daily workflow now runs:

```bash
python run_system_state.py
```

after setup health and before the dashboard.

Current system-state verdict:

```text
Prep only. On 2026-05-26, run python run_daily_workflow.py --refresh-data
before importing or sizing any paper trade.
```

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_daily_workflow.py
.venv/bin/python run_system_state.py
```

Recommendation checklist:

```text
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Collect only valid current-candle paper trades until the 30-trade checkpoint.
[ ] Review setup health before trusting any approved setup.
[ ] Keep AAPL Setup B Short under caution until its math improves.
[ ] Preserve app-ready JSON/CSV outputs as the source for any future UI.
```

## System State Integration

The existing dashboard and readiness reports now consume the app-ready system
state layer.

Changed:

```text
run_dashboard.py
run_readiness_check.py
```

Dashboard uses:

```text
reports.system_state.build_system_state()
```

for its main verdict, data freshness, and paper progress.

Readiness check now includes an `App System State` section and uses the
system-state verdict unless a hard readiness blocker exists.

Readiness support checks now include:

```text
logs/system_state.json
logs/system_state.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_readiness_check.py run_dashboard.py reports/system_state.py run_system_state.py
.venv/bin/python run_readiness_check.py
```

Recommendation checklist:

```text
[ ] Continue moving duplicated report logic into reports/system_state.py where it makes sense.
[ ] Add a lightweight local app shell that reads logs/system_state.json.
[ ] Keep logs/system_state.json as the future UI/API source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## Local App Shell

Added:

```text
app/index.html
app/styles.css
app/app.js
run_app.py
```

The app is a local read-only dashboard shell for future app work. It reads
`logs/system_state.json` through:

```text
http://127.0.0.1:8765/api/system-state
```

Run:

```bash
python run_system_state.py
python run_app.py
```

Open:

```text
http://127.0.0.1:8765
```

The app shows:

```text
readiness verdict
market/data freshness
paper validation progress
scanner and sizing counts
setup health attention list
safety guardrails
links to key generated reports
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s -I http://127.0.0.1:8765/
```

Visual verification note:

```text
The in-app Browser tool was not exposed in this session, and Playwright was not
installed, so visual verification was limited to server/API checks.
```

Recommendation checklist:

```text
[ ] Add a small app health panel for recent refresh times.
[ ] Add report detail views inside the app instead of opening raw Markdown.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## App Health Panel

Added app health timestamps to the system state and local app.

Changed:

```text
reports/system_state.py
run_system_state.py
app/index.html
app/styles.css
app/app.js
```

The app now has an App Health section showing modified/generated times for key
outputs:

```text
system_state.json
dashboard report
scanner CSV
position sizing CSV
setup health CSV
paper log
```

The system state now includes:

```text
generated_at_et
app_health.generated_at_et
app_health.source_file_states
```

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s http://127.0.0.1:8765/app.js
```

Recommendation checklist:

```text
[ ] Add report detail views inside the app instead of opening raw Markdown.
[ ] Add a manual refresh/run-status workflow for Tuesday's Webull refresh.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## App Report Detail Views

Added read-only report detail views inside the local app.

Changed:

```text
run_app.py
app/index.html
app/styles.css
app/app.js
README.md
```

New API:

```text
GET /api/report?name=dashboard
```

Allowed report names:

```text
dashboard
scanner
setup_health
readiness
checkpoint
system_state
```

The app now includes a Report Detail section with tabs and a small built-in
Markdown renderer. Reports are served only from an explicit allowlist.

Verified:

```bash
.venv/bin/python -m py_compile run_app.py
curl -s "http://127.0.0.1:8765/api/report?name=dashboard"
curl -s "http://127.0.0.1:8765/api/report?name=setup_health"
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8765/api/report?name=not_allowed"
```

The disallowed report check returned:

```text
404
```

Recommendation checklist:

```text
[ ] Add a manual refresh/run-status workflow for Tuesday's Webull refresh.
[ ] Add app-side persistent warning badges for stale data, market closed, and paper gate progress.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## Refresh Status And App Warning Badges

Added:

```text
reports/refresh_status.py
run_refresh_status.py
logs/refresh_status.json
logs/refresh_status.md
```

Changed:

```text
reports/system_state.py
run_system_state.py
run_daily_workflow.py
run_app.py
app/index.html
app/styles.css
app/app.js
README.md
```

Refresh status checks:

```text
market open/closed status
next market session
latest scanner session
current-candle candidate count
approved-symbol Webull CSV presence and modified times
whether paper import is blocked
exact refresh command to run
```

Current refresh status:

```text
status = prep_only
reason = Market is not open: Weekend.
next_action = On 2026-05-26 during market hours, run python run_daily_workflow.py --refresh-data.
paper_import_blocked = True
```

The local app now shows persistent warning badges for:

```text
data freshness
market status
paper gate progress
setup health attention count
paper import blocked/review state
```

The daily workflow now runs:

```bash
python run_refresh_status.py
```

before rebuilding system state.

Verified:

```bash
.venv/bin/python -m py_compile reports/refresh_status.py run_refresh_status.py reports/system_state.py run_system_state.py run_app.py run_daily_workflow.py
.venv/bin/python run_refresh_status.py
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s "http://127.0.0.1:8765/api/report?name=refresh_status"
curl -s http://127.0.0.1:8765/app.js
```

Recommendation checklist:

```text
[ ] Run python run_refresh_status.py before Tuesday's market open.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
[ ] Only import paper trades after current-candle candidates exist.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## Setup Replay Practice Mode

Added historical setup replay practice mode for non-market-hours training.

New files:

```text
run_setup_replay.py
logs/setup_replay.json
logs/setup_replay.md
```

Changed:

```text
reports/system_state.py
run_system_state.py
run_daily_workflow.py
run_app.py
app/index.html
app/styles.css
app/app.js
README.md
```

Run:

```bash
python run_setup_replay.py
python run_system_state.py
```

Replay mode uses historical trades from:

```text
logs/playbook_approved_trades.csv
```

The local app now displays replay cards with:

```text
symbol and setup
direction
entry / stop / target
exit result and exit reason
quality information
practice prompts
previous/next controls
```

It also adds a `setup_replay` report detail tab. Replay mode is for practice
only; it does not create signals or permit live/paper entry.

Latest generated replay set:

```text
20 historical approved-playbook cards
```

Verified:

```bash
.venv/bin/python -m py_compile run_setup_replay.py reports/system_state.py run_system_state.py run_app.py run_daily_workflow.py
.venv/bin/python run_setup_replay.py
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s "http://127.0.0.1:8765/api/report?name=setup_replay"
curl -s http://127.0.0.1:8765/app.js
```

Recommendation checklist:

```text
[ ] Use replay mode to review at least one win and one loss before Tuesday's open.
[ ] Add a reveal-outcome mode so entry/stop/target can be reviewed before seeing result.
[ ] Run python run_refresh_status.py before Tuesday's market open.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## Setup Replay Reveal-Outcome Mode

Added concealed-outcome practice behavior to the local app replay cards.

Changed:

```text
run_setup_replay.py
app/index.html
app/styles.css
app/app.js
README.md
logs/setup_replay.json
logs/setup_replay.md
logs/system_state.json
logs/system_state.md
```

The replay app now shows entry, stop, target, quality, and planning prompts
first. Its historical `R` result and exit details stay hidden until the user
chooses `Reveal outcome`. Moving to the previous or next card returns to the
concealed practice state.

The Markdown replay report remains a complete audit record, so it still lists
historical outcomes.

Verified:

```bash
.venv/bin/python -m py_compile run_setup_replay.py reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_setup_replay.py
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s http://127.0.0.1:8765/
curl -s http://127.0.0.1:8765/app.js
```

The local app API returned HTTP 200 and served the updated HTML/JavaScript. A
scripted UI behavior check confirmed that a card starts hidden, reveals on
request, and hides again when navigating to the next card. This session did
not have an attached in-app browser available for a full visual click-through.

Recommendation checklist:

```text
[ ] Use concealed replay cards to review at least one win and one loss before Tuesday's open.
[ ] Run python run_refresh_status.py before Tuesday's market open.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
[ ] Only import paper trades after current-candle candidates exist.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## Dashboard Status-Only Action

Added one controlled dashboard action for rebuilding local refresh readiness.

Changed:

```text
run_app.py
app/index.html
app/styles.css
app/app.js
README.md
logs/refresh_status.json
logs/refresh_status.md
logs/system_state.json
logs/system_state.md
```

New local API action:

```text
POST /api/actions/refresh-status
```

The app's `Update refresh status` button runs only the local report builders:

```text
python run_refresh_status.py
python run_system_state.py
```

It does not fetch Webull data, import paper trades, place orders, or enable
live trading. Market-data refresh remains a terminal workflow for deliberate
use during market hours.

Verified:

```bash
.venv/bin/python -m py_compile run_app.py run_refresh_status.py reports/refresh_status.py run_system_state.py
.venv/bin/python run_app.py --port 8766
curl -s -X POST http://127.0.0.1:8766/api/actions/refresh-status
curl -s 'http://127.0.0.1:8766/api/report?name=refresh_status'
curl -s -X POST http://127.0.0.1:8766/api/actions/refresh-data
```

The permitted status action returned HTTP 200 and the unimplemented
market-data action returned HTTP 404. A scripted app-state check confirmed the
button posts to the endpoint and shows its no-fetch/no-import success message.
File timestamps confirmed that `data/paper_trades.csv` and representative
Webull candle CSVs were not changed by the action.

Recommendation checklist:

```text
[ ] Use the dashboard status button before Tuesday's market open to confirm the session plan.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data from the terminal.
[ ] Keep actual data refresh and paper import outside app buttons until the workflow is validated.
[ ] Only import paper trades after current-candle candidates exist.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## App Current-Candidate Panel

Added a read-only current-candle candidate panel to the local app.

Changed:

```text
reports/system_state.py
run_system_state.py
app/index.html
app/styles.css
app/app.js
README.md
logs/system_state.json
logs/system_state.md
```

The app state now joins existing scanner and position-sizing outputs for
display. For each current-candle candidate, the panel can show:

```text
symbol / setup / direction
planned entry / stop / target
suggested shares and estimated paper risk
scanner / sizing / quality context
readiness checklist flags and blocker messages
```

Safety boundary:

```text
no new signal generation
no paper-log import
no order placement
no live execution
```

Current generated state has zero candidate cards because the saved scanner
data is stale/off-market prep data until the next market-session refresh.

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_system_state.py
```

An in-memory state test confirmed a fresh allowed candidate joins to eligible
position sizing, is JSON serializable, and becomes ready for review. A
scripted UI check confirmed both the empty-state message and the rendered
candidate card path with plan values, estimated risk, and checklist flags.

Recommendation checklist:

```text
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data from the terminal.
[ ] Inspect the candidate panel only after the scanner status is fresh for today.
[ ] Only import paper trades after current-candle candidates pass review.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## App Paper Progress Visualization

Added a display-only forward-paper progress visualization to the local app.

Changed:

```text
reports/system_state.py
run_system_state.py
app/index.html
app/styles.css
app/app.js
README.md
logs/system_state.json
logs/system_state.md
```

The visualization reads completed results already written to:

```text
logs/paper_review_clean_trades.csv
```

It displays:

```text
30-trade and 60-trade gate progress bars
cumulative forward paper R chart
allowed versus blocked/watch-only comparisons
plan-adherence comparisons
```

This is not a second journal and does not calculate from historical backtest
results. It only makes the existing forward paper-validation data easier to
see. The current empty paper log correctly produces an empty-state display.

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_system_state.py
```

An in-memory completed-trade sample confirmed cumulative R and gate-progress
calculations, group summaries, and JSON serialization. A scripted dashboard
check confirmed both zero-trade and populated visual states.

Recommendation checklist:

```text
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data from the terminal.
[ ] Log only reviewed current-candle paper candidates and their completed outcomes.
[ ] Use the visualization after forward paper results begin accumulating.
[ ] Continue paper validation toward the 30-trade checkpoint before promoting strategy changes.
```

## Good Prompt To Give An AI Coding Assistant

```text
Read AGENTS.md, PROJECT_MEMORY.md, and HANDOFF.md. This project already has
CSV/Webull market-data support and is now preparing for forward paper
validation. Check logs/premarket_verification.md and the automated safety
tests. Keep live trading and broker order execution disabled.
```

## Daily Workflow State-Sync Fix

The current project is past CSV import and is in paper-validation preparation.
A small workflow reliability fix was added:

```text
run_daily_workflow.py now rebuilds logs/system_state.json after the dashboard,
recap, readiness check, and daily summary are complete.
```

This keeps the local app health timestamps aligned with the completed daily
run. The daily workflow and position-sizer CLI help strings were also fixed so
their `0.5%` text no longer causes an `argparse` startup error.

Verified:

```bash
.venv/bin/python -m py_compile run_daily_workflow.py run_position_sizer.py reports/system_state.py run_system_state.py run_dashboard.py run_readiness_check.py
.venv/bin/python run_daily_workflow.py --help
.venv/bin/python run_position_sizer.py --help
.venv/bin/python run_daily_workflow.py
```

The safe no-refresh run completed on Sunday, 2026-05-24. Current action:

```text
Prep only. During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data before importing or sizing any paper trade.
```

## Pre-Market Reliability Pass

Added one command for pre-market preparation:

```bash
.venv/bin/python run_premarket_verification.py
```

It rebuilds and summarizes local candle integrity, refresh status, system
state, readiness, safety flags, and the paper-import gate. It is local-only by
default.

Optional data-only Webull access verification:

```bash
.venv/bin/python run_premarket_verification.py --probe-webull
```

Probe outputs now use their own filenames under `logs/premarket_probe/` when
run from the pre-market command, so a small access check cannot replace full
workflow candles.

Added `tests/test_workflow_safety.py` for the paper-validation guardrails.
Verified with:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_premarket_verification.py
```

Latest result:

```text
12 automated tests passed
12 local candle files checked with 0 integrity warnings
Webull data-only probe passed and saved isolated premarket probe files
paper import is blocked until fresh reviewed candidates exist
no paper trades or forward observations were appended during verification
```

## Dashboard Pre-Market Gate Upgrade

The local app now surfaces pre-market readiness directly on its mission-control
view:

```text
Pre-Market Gate metric tile and status badge
Run local pre-market check button
Pre-Market Verification report tab
latest probe/integrity/paper-import gate summary in system_state.json
```

The new button is intentionally local-only. It rebuilds derived safety and
readiness reports but does not request Webull data or import paper trades. The
explicit data-only probe remains:

```bash
.venv/bin/python run_premarket_verification.py --probe-webull
```

The app now escapes state-derived text before rendering it into HTML, including
setup-health flags and replay details.

Verified:

```text
15 automated tests passed
local pre-market endpoint returned HTTP 200
dashboard state retained the earlier successful Webull probe as previous_pass
data/paper_trades.csv, data/forward_signal_observations.csv, and
data/market_refresh_audit.csv did not change
```

## Forward Signal Observation Journal

Added append-only forward evidence collection for paper validation:

```text
run_forward_observations.py
data/forward_signal_observations.csv
logs/forward_signal_observations.md
```

The daily workflow now records fresh `current_candle` signals from the
scanner when the regular market is open. It captures both `allowed` and
`blocked_watch_only` rows so `weakness_v1` can be evaluated without losing
signals between refreshes.

Safety behavior:

```text
observations are not paper trades
no broker orders, live alerts, or execution are created
stale/off-market scanner rows are not appended
repeat scans deduplicate by signal_time_et + symbol + setup + direction
```

The local app exposes an `Observations` report tab and shows accumulated
allowed/watch-only observation counts from `logs/system_state.json`.

Verified:

```bash
.venv/bin/python -m py_compile run_forward_observations.py run_daily_workflow.py run_position_sizer.py reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_daily_workflow.py
.venv/bin/python run_forward_observations.py --output-dir logs
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s 'http://127.0.0.1:8765/api/report?name=observations'
```

An in-memory fresh scanner sample confirmed allowed and watch-only conversion
plus duplicate suppression. The off-market run on Sunday, 2026-05-24 created
the empty report but did not change the append-only CSV contents or timestamp.

## Offline Monthly Stability Validation

Added a stricter offline read on the existing `weakness_v1` research filter:

```text
run_holdout_validation.py now scores calendar-month windows
run_research_pipeline.py now shows the monthly stability verdict and refreshes app state at the end
tests/test_workflow_safety.py covers monthly boundaries and summary counting
```

This does not fetch Webull data, enable live behavior, or append forward
evidence. It is meant to expose whether a historically designed filter works
consistently across time before forward paper results exist.

Latest cached-data result:

```text
Aggregate weakness_v1 expectancy: +0.2223R versus +0.1987R base
Aggregate final-R improvement: +0.2293R
Months where weakness_v1 blocked trades: January and March 2026
Monthly expectancy improved: 1 of 2 affected months
Monthly final R declined: 1 of 2 affected months
```

Research read:

```text
weakness_v1 is still worth monitoring in paper validation, but the monthly
evidence is mixed. Do not describe it as durable or proven from historical
data alone.
```

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile run_holdout_validation.py run_research_pipeline.py tests/test_workflow_safety.py
.venv/bin/python run_research_pipeline.py --skip-playbook
```

Result:

```text
17 tests passed
logs/holdout_validation_report.md and logs/research_pipeline_summary.md regenerated
no paper trade, forward observation, or refresh-audit rows were appended
```

## Paper Action-Boundary Guardrails

Closed several gaps before the first market-hours forward-validation run:

```text
run_paper_import.py now rejects real writes unless an allowed scanner row is
from the current open market session, freshness is current_candle, and the
symbol has current-session Webull refresh-audit evidence.

run_daily_workflow.py no longer permits automatic --append-current-signals
imports; a candidate must be reviewed before running run_paper_import.py.

run_position_sizer.py no longer exposes actionable sizes for stale,
outside-session, earlier-today, unaudited-refresh, or blocked/watch-only candidates.

run_position_sizer.py now derives daily and monthly realized R automatically
from completed allowed rows in data/paper_trades.csv before enforcing loss stops.

run_daily_scanner.py now generates an import template only for open-session
current-candle candidates; pre-open/stale templates are header-only.

run_data_integrity.py and run_refresh_audit.py now treat the current day's
partial M5 file during regular hours as in_progress rather than as a false
incomplete-session warning.

reports/refresh_status.py now keeps paper import blocked for watch-only-only
signals and for allowed signals without matching current-session refresh audit.
```

Verified offline on Tuesday, 2026-05-26 before regular market hours:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile run_paper_import.py run_position_sizer.py run_daily_scanner.py run_daily_workflow.py run_intraday_loop.py tests/test_workflow_safety.py
.venv/bin/python run_daily_workflow.py
```

Result:

```text
24 automated tests passed
the pre-open no-refresh workflow completed safely
logs/daily_paper_trade_import_template.csv contained headers only
no paper trade, forward observation, or refresh-audit rows were appended
```

## Post-Close Preparation For Wednesday, May 27

After Tuesday's regular session, the data-only workflow was refreshed through
the close and the offline paper-validation guardrails were tightened.

Changed:

```text
reports/system_state.py
run_intraday_loop.py
run_premarket_verification.py
run_setup_replay.py
run_premarket_plan.py
run_trade_checklist.py
run_daily_workflow.py
tests/test_workflow_safety.py
README.md
HANDOFF.md
PROJECT_MEMORY.md
```

New guardrails:

```text
The dashboard/system-state freshness label changes to outside_market_hours
after the close, even when today's candle files exist.
The continuous intraday loop terminates after the regular session ends.
Tomorrow's plan and checklist cannot display a prior-session row as a current
paper candidate or eligible paper size.
Pre-market verification wording no longer assumes a particular weekday.
Each daily refresh cycle fetches Webull candles once, then evaluates Setup B
from the just-saved CSVs rather than downloading the same data again.
```

Tuesday end-of-day result:

```text
Webull market-data-only refresh completed after the close.
All approved-symbol M5 files cover the final 15:55 ET regular-session bar.
Candle integrity warnings: 0.
No current-candle paper candidate existed.
No paper trade or forward observation was appended.
Paper evidence remains 0 / 30 allowed completed trades.
```

Prepared for Wednesday:

```text
logs/premarket_verification.md = safeguards pass; previous Webull probe passed
logs/daily_trade_plan.md = Wednesday, 2026-05-27 plan
logs/readiness_check.md = Wednesday session ready for fresh-data scan, with no candidate yet
logs/system_state.md = after-close / outside_market_hours / paper import blocked
```

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile reports/system_state.py run_intraday_loop.py run_premarket_verification.py run_setup_replay.py run_premarket_plan.py run_trade_checklist.py run_daily_workflow.py tests/test_workflow_safety.py
.venv-webull/bin/python run_daily_workflow.py --refresh-data
.venv/bin/python run_premarket_verification.py
.venv/bin/python run_premarket_plan.py --date 2026-05-27
.venv/bin/python run_readiness_check.py --date 2026-05-27
```

Result:

```text
31 automated tests passed, including verification that the second setup-family
evaluation reuses freshly downloaded CSVs.
Tomorrow still requires a new market-hours Webull refresh before any candidate
may be considered for a paper trade.
Live trading and broker order execution remain disabled.
```

## Exploratory Universe Expansion On May 26

Broader ticker research resumed in a separate workspace so it does not alter
the approved paper-validation workflow:

```text
logs/universe_expansion/
```

Screened:

```text
IWM DIA AMZN GOOGL AVGO NFLX COIN PLTR
```

`SPY` was included only as the market-confirmation reference. New symbols that
showed early interest were retested with two M30 history pages and six M5
history pages.

Long-side expansion candidates:

```text
AMZN market_confirmed + no_vwap_exit: 11 trades, +0.1937R expectancy, 2.3218 PF
COIN current + no_vwap_exit: 12 trades, +0.0212R expectancy, 1.0888 PF
NFLX remains watch_more with only 2 market-confirmed long trades.
IWM and DIA did not survive deeper Setup A testing.
```

Short-side expansion candidates:

```text
NFLX setup_b_short + no_vwap_exit: 14 trades, +0.6258R expectancy, 10.6169 PF
DIA setup_b_short + no_vwap_exit: 16 trades, +0.1682R expectancy, 1.7211 PF
IWM setup_b_short + no_vwap_exit: 12 trades, +0.0723R expectancy, 1.3858 PF
AMZN and COIN did not pass deeper Setup B testing.
```

Relevant reports:

```text
logs/universe_expansion/best_plus_market_candidate_selection_report.md
logs/universe_expansion/setup_b_candidate_selection_report.md
```

No exploratory ticker was added to `config/symbol_playbook.py`, the scanner,
or the paper-validation refresh list. They need portfolio-impact and stability
review before any promotion.

During this run, candidate selection was corrected so a passing candidate with
the required minimum number of trades is not displaced by a higher-expectancy
but under-sampled candidate. This matters for `COIN`, whose 12-trade long
candidate now correctly remains selected over its 8-trade alternative.

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
32 automated tests passed
```

## Main-Page Trading Workspace On May 26

Added the requested trading-style interface directly to the dashboard main
page. It is a native Project Gwala panel backed by saved Webull market-data
candles, not an embedded broker order-entry page.

Main-page workstation contents:

```text
approved-playbook watchlist
5-minute / 30-minute timeframe switches
candlestick chart
VWAP, EMA 9, EMA 21, EMA 200, and opening-range overlays
selected-symbol last stored price and prior-session change
paper-review ticket showing entry, stop, target, and shares when a current
scanner candidate exists
prominent no-order-execution safety label and disabled order button
```

Implementation:

```text
run_app.py now serves /api/trading-workspace?symbol=SPY&timeframe=M5
app/index.html defines the Trading Workspace main-page panel
app/app.js draws chart SVGs and connects chart selection to paper candidate state
app/styles.css provides terminal/watchlist/chart/ticket styling
tests/test_workflow_safety.py verifies approved-symbol chart payloads and blocks
unapproved exploratory symbols from the operational workspace
```

Decision boundary:

```text
No Webull trading UI or order execution API was embedded.
No live-trading controls were added.
The chart uses the same Webull CSV data already used by the scanner.
Research expansion names remain outside the operational interface until
deliberately promoted to the approved playbook.
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
34 automated tests passed
```

## Investment Narrative Panel On May 26

Added a main-page `Investment Narrative` panel beneath the Trading Workspace.
It follows the selected approved ticker and is intentionally separate from the
intraday paper-validation strategy.

Panel contents:

```text
selected symbol and asset type
long-term thesis focus
three durable monitoring themes
two review questions
future connection slots for market news and X public-post trends
visible guardrail that narrative context cannot influence trade decisions
```

Implementation boundary:

```text
The initial panel does not claim to retrieve or summarize live news.
It displays Sources Not Connected until an approved provider is added.
/api/investment-narrative returns research-only content for approved symbols.
Unapproved symbols are rejected.
No broker, order, signal-scoring, or position-sizing logic changed.
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py config/investment_narratives.py tests/test_workflow_safety.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
36 automated tests passed
```

## Setup Readiness Radar And Chart Markers On May 26

Added a trading-workspace explanation upgrade for paper validation:

```text
The chart now marks stored-session scanner signals for the selected ticker.
The Setup Readiness Radar lists passed and missing scanner conditions.
It also displays quality grade/score, relative volume, room-to-target R, and
whether the approved setup triggered earlier in the saved session.
```

For the current saved `SPY` session, the dashboard visibly shows the earlier
Setup A Long signal at `10:00 ET` and explains that the latest saved candle
passes `7 / 9` requirements, while it is no longer a current paper candidate.

Safety boundary:

```text
The radar reads existing scanner output only.
It does not create signals, unblock paper importing, alter sizing, or expose
order execution.
```

Verification:

```bash
.venv/bin/python -m py_compile run_app.py run_daily_scanner.py config/investment_narratives.py tests/test_workflow_safety.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
38 automated tests passed
```

## Near-Miss Analytics On May 26

Added a main-page `Near-Miss Analytics` panel to learn from non-ready approved
setups without loosening any rules.

What it shows:

```text
frequent missing scanner conditions
the approved setups closest to readiness on the latest saved candle
whether the evidence is an accumulated open-session journal or only a latest
saved scanner snapshot
an explicit guardrail that analytics cannot change signal eligibility
```

Collection behavior:

```text
run_near_miss_analytics.py is now called immediately after run_daily_scanner.py
inside the daily workflow.
It appends data/near_miss_observations.csv only when scanner output belongs to
the current open market session.
It deduplicates the same setup, candle, and missing condition.
After-close or stale runs generate a display/report snapshot only.
```

Current snapshot result:

```text
37 blocker occurrences from the latest saved scanner snapshot.
inside entry window is currently most frequent with 7 occurrences.
QQQ Setup A Long is closest at 9/13 conditions passed.
TSLA Setup A Long follows at 8/10 conditions passed.
0 accumulated open-session rows were appended because this verification was
outside an active fresh paper session.
```

Verified:

```bash
.venv/bin/python -m py_compile run_near_miss_analytics.py run_daily_workflow.py run_daily_scanner.py run_app.py reports/system_state.py tests/test_workflow_safety.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_near_miss_analytics.py --output-dir logs
```

Result:

```text
40 automated tests passed
```

## Chart Outcome Replay Upgrade On May 26

The Setup Replay panel now includes a historical saved-candle chart for
process practice.

What it shows:

```text
Entry, stop, and target plan lines.
VWAP, 9 EMA, and 21 EMA context.
An entry marker before the historical result is revealed.
The exit path and exit marker only after Reveal outcome is selected.
```

Concealment behavior:

```text
The new /api/replay-chart endpoint reads saved replay cards and local Webull
CSV candles only.
The pre-reveal response ends at the 30-minute entry candle, which is the
existing engine's entry-on-signal-close point.
After reveal, stored 5-minute bars are used for exit-management review when
they cover the trade session; older cards use a 30-minute fallback.
```

Current replay coverage:

```text
20 saved historical replay cards build correctly.
15 revealed cards have stored M5 outcome coverage.
5 older revealed cards use the M30 fallback.
```

Safety boundary:

```text
This is historical read-only practice data.
It does not generate current signals, place orders, enable execution, import
paper trades, or change strategy eligibility.
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py run_setup_replay.py reports/system_state.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
42 automated tests passed.
A live local endpoint smoke test confirmed concealed and revealed chart
responses for an actual SPY replay card.
The in-app browser surface was unavailable in this session, so the rendered
click-through still needs a visual check when that surface is available.
```

## Replay Decision Journal On May 26

Added the next practice-focused replay layer in the local app.

What changed:

```text
Every replay card now asks for Take, Skip, or Watch before Reveal outcome is
enabled.
Once the historical result has been viewed, the recorded decision is locked.
Optional per-card notes can be saved for checklist reflection.
The Replay heading includes local counts for decisions and reviewed outcomes.
```

Persistence and boundaries:

```text
This journal is browser-local only and remains available when the same local
browser revisits the dashboard.
It is deliberately separate from logs/setup_replay.json, data/paper_trades.csv,
forward observations, scanner decisions, sizing, and all execution behavior.
Reviewed cards reopen with outcomes hidden so replay still begins as a
practice decision.
```

Changed:

```text
app/index.html
app/app.js
app/styles.css
README.md
PROJECT_MEMORY.md
HANDOFF.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py run_setup_replay.py reports/system_state.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
42 automated tests passed.
The in-app browser surface was unavailable in this session, so the new
interactive journal should receive a visual click-through at the next
available dashboard browser session.
```

## Candle-By-Candle Replay Management On May 27

Added a sequential management trainer to historical Setup Replay.

Workflow:

```text
1. Review the entry chart and record Take, Skip, or Watch.
2. Select Start management.
3. Use Hold / Next candle to expose one stored management candle at a time.
4. Review marked price and unrealized R without seeing the recorded ending.
5. Record Exit here, use Stop followed when the visible candle reaches the
   planned stop, or continue until the historical exit candle is reached.
6. Select Compare with historical outcome to see the strategy result.
```

Concealment and safety:

```text
The `/api/replay-chart` endpoint accepts bounded candle steps and returns only
bars currently permitted in the replay.
Before completion it does not expose how many future management candles remain.
Historical result details and the exit marker are still withheld until
comparison.
Practice actions live in browser-local storage only; they are not paper trades
and cannot affect scanner eligibility, sizing, strategy logic, or execution.
```

Changed:

```text
run_app.py
app/index.html
app/app.js
app/styles.css
tests/test_workflow_safety.py
README.md
PROJECT_MEMORY.md
HANDOFF.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py run_setup_replay.py reports/system_state.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
43 automated tests passed.
JavaScript syntax parsing succeeded.
Real saved SPY replay payloads confirmed stepwise M5 candle exposure and
duration concealment until the final stored management candle.
A live local endpoint smoke test confirmed that only comparison adds the
historical exit marker.
```

## Replay Scoring Dashboard On May 27

Added a training-only scoreboard above the Setup Replay cards.

What it shows:

```text
Reviewed replay comparisons out of the current saved-card set.
Average historical outcome for reviewed Take decisions.
Losing historical setups avoided by reviewed Skip or Watch decisions.
Average practice-exit R difference versus the saved historical strategy exit.
Decision-outcome breakdown for Take, Skip, and Watch.
Setup-and-grade outcome breakdown for reviewed cards.
Latest practice-exit comparisons.
```

Important scoring rule:

```text
Only cards already compared with their historical outcome are included.
Unrevealed cards never contribute outcomes or summary metrics, so the
dashboard does not leak future replay information.
```

Boundary:

```text
Scoring reads browser-local practice decisions and reviewed historical replay
cards only. It is not forward-validation evidence and cannot affect signals,
paper-trade eligibility, sizing, strategy logic, or order execution.
```

Changed:

```text
app/index.html
app/app.js
app/styles.css
README.md
PROJECT_MEMORY.md
HANDOFF.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py run_setup_replay.py reports/system_state.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
43 automated tests passed.
JavaScript syntax parsing succeeded.
The sequential replay endpoint still conceals the exit marker before
comparison and exposes it after comparison.
The in-app browser surface was unavailable for a rendered scoreboard
click-through in this session.
```

## Replay Filters And Session Presets On May 27

Added a practice-session builder above Setup Replay.

Available controls:

```text
Filter by symbol, setup, and quality grade without requiring outcome review.
Filter by result or exit reason only among previously compared cards.
Quick presets: All Cards, Unreviewed Only, A-Grade Setups, Setup B Shorts,
Reviewed Losses, Reviewed Stop-Losses, and Reviewed VWAP Exits.
```

Queue and scoring behavior:

```text
Previous and Next move only through cards in the active practice session.
If a card is compared while using Unreviewed Only, it leaves that queue on the
next navigation action while remaining visible long enough to review.
Scoring and journal totals continue to cover the entire saved card set rather
than shrinking to the current session filter.
```

Boundary:

```text
Historical outcome and exit-reason sessions are reviewed-only. An unrevealed
card cannot be selected because of its future result or exit reason.
This is browser-local historical practice tooling only; it cannot affect
forward validation, paper eligibility, sizing, or execution.
```

Changed:

```text
app/index.html
app/app.js
app/styles.css
README.md
PROJECT_MEMORY.md
HANDOFF.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py run_setup_replay.py reports/system_state.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
43 automated tests passed.
JavaScript syntax parsing succeeded.
The in-app browser surface was unavailable for a rendered filter and preset
click-through in this session.
```

## Autonomous Paper Supervisor Foundation On May 27

Added the first safe foundation for eventual always-on operation:

```text
run_autonomous_paper_workflow.py
```

It decides what to do from the local market calendar:

```text
wait until the pre-market window
run pre-market verification
run market-hours refresh/scanner/sizing/dashboard workflow
run after-close recap/readiness/system-state reports
```

Status output:

```text
logs/autonomous_paper_workflow_status.md
```

Safe preview:

```bash
.venv/bin/python run_autonomous_paper_workflow.py --once --dry-run
```

Market-hours loop:

```bash
source .venv-webull/bin/activate
python run_autonomous_paper_workflow.py --interval-minutes 5
```

Safety boundary:

```text
This is research and paper-validation only.
It does not place orders.
It does not create broker alerts.
It does not auto-import reviewed paper trades.
It does not pass --append-current-signals to the daily workflow.
```

Changed:

```text
run_autonomous_paper_workflow.py
tests/test_workflow_safety.py
README.md
PROJECT_MEMORY.md
HANDOFF.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_autonomous_paper_workflow.py tests/test_workflow_safety.py
.venv/bin/python run_autonomous_paper_workflow.py --once --dry-run
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
Dry-run correctly selected market_scan during the open session.
47 workflow safety tests passed.
```

Next recommended task:

```text
Run the supervisor manually during market hours first. After it behaves well
for a few sessions, add a macOS launchd plist or another OS-level scheduler so
it starts automatically at login before the open.
```

## macOS Auto-Start Installed On May 27

Installed and loaded the macOS LaunchAgent for the autonomous paper workflow.

Files:

```text
launchd/com.project-gwala.autonomous-paper.plist
scripts/install_autonomous_launch_agent.sh
scripts/uninstall_autonomous_launch_agent.sh
/Users/roy/Library/LaunchAgents/com.project-gwala.autonomous-paper.plist
```

Schedule:

```text
RunAtLoad = true
Weekdays at 6:15 AM local time
Supervisor interval = 5 minutes during market hours
```

Commands:

```bash
bash scripts/install_autonomous_launch_agent.sh
launchctl print gui/$UID/com.project-gwala.autonomous-paper
bash scripts/uninstall_autonomous_launch_agent.sh
```

Logs:

```text
logs/autonomous_paper_workflow.launchd.out.log
logs/autonomous_paper_workflow.launchd.err.log
logs/autonomous_paper_workflow_status.md
```

Observed result:

```text
launchctl reported state = running.
RunAtLoad started a live market_scan during the open session.
The supervisor status showed Dry Run = False.
The launchd error log was empty at install-time check.
```

Safety boundary:

```text
Still research and paper-validation only.
No broker execution.
No broker alerts.
No automatic paper import.
```

Mac limitation:

```text
This is a user LaunchAgent. It requires the Mac to be powered on and the user
account logged in. It cannot run while the Mac is asleep, powered off, or fully
logged out.
```

## Dashboard Auto-Start Installed On May 27

Installed and loaded a separate macOS LaunchAgent for the local dashboard.

Files:

```text
launchd/com.project-gwala.dashboard.plist
scripts/install_dashboard_launch_agent.sh
scripts/uninstall_dashboard_launch_agent.sh
/Users/roy/Library/LaunchAgents/com.project-gwala.dashboard.plist
```

Behavior:

```text
RunAtLoad = true
KeepAlive = true
Serves http://127.0.0.1:8765
Uses run_app.py and .venv/bin/python
```

Commands:

```bash
bash scripts/install_dashboard_launch_agent.sh
launchctl print gui/$UID/com.project-gwala.dashboard
bash scripts/uninstall_dashboard_launch_agent.sh
open http://127.0.0.1:8765
```

Logs:

```text
logs/dashboard.launchd.out.log
logs/dashboard.launchd.err.log
```

Observed result:

```text
launchctl reported state = running.
The dashboard URL was opened in the user's regular macOS browser.
The in-app browser surface was unavailable in this session.
```

## Dashboard Desktop App Wrapper On May 27

Added a local macOS app wrapper:

```text
Project Gwala Dashboard.app
Project Gwala Dashboard.app/Contents/Info.plist
Project Gwala Dashboard.app/Contents/MacOS/Project Gwala Dashboard
scripts/build_dashboard_app.sh
```

Behavior:

```text
Double-clicking the app opens http://127.0.0.1:8765.
The dashboard server still comes from the dashboard LaunchAgent.
```

Verified:

```bash
plutil -lint "Project Gwala Dashboard.app/Contents/Info.plist"
bash scripts/build_dashboard_app.sh
open "Project Gwala Dashboard.app"
```

Result:

```text
The app bundle validates and opens the local dashboard URL.
```

## Local Paper Execution Simulator On May 27

Added a local-only paper execution simulator.

Files:

```text
execution/paper_trader.py
run_paper_execution_simulator.py
logs/local_paper_execution_simulator.md
data/paper_orders.csv
data/paper_trades.csv
```

Behavior:

```text
Reads logs/position_sizing.csv.
Uses only size_ok + allowed + current_candle rows.
Builds local paper order tickets.
Can append open rows to data/paper_trades.csv when explicitly confirmed.
```

Safety boundary:

```text
Default mode is preview only.
Writing requires --confirm-local-paper.
No Webull order endpoints are called.
No Webull paper orders are placed.
No broker alerts.
No live execution.
```

Commands:

```bash
.venv/bin/python run_paper_execution_simulator.py
.venv/bin/python run_paper_execution_simulator.py --confirm-local-paper
```

Current run:

```text
Eligible local paper rows: 0
New local paper orders: 0
Preview only; no rows written.
```

Verified:

```bash
.venv/bin/python -m py_compile execution/paper_trader.py run_paper_execution_simulator.py tests/test_workflow_safety.py
.venv/bin/python run_paper_execution_simulator.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
48 workflow safety tests passed.
```
*** End of File

## END OF LATEST SESSION - 2026-05-27 AFTER CLOSE

Saved session state:

```text
Phase: research and paper validation only
Dashboard: running at http://127.0.0.1:8765
Autonomous workflow: installed
Dashboard paper buttons: installed
Safety tests: 52 passed
Paper progress: 0 / 30 first checkpoint, 0 / 60 strong checkpoint
Ready candidates: 0
Open paper trades: 0
Next market session: 2026-05-28
```

Next safest move:

```text
During the next market session, refresh data and use Run paper preview.
Only use Confirm local paper entry if a current-candle allowed size_ok candidate appears.
Keep all broker/Webull order execution disabled.
```

## Latest Session Snapshot - 2026-05-27 After Close

Saved after the dashboard paper-cycle work.

Current phase:

```text
Research and paper validation only.
No live trading.
No broker order execution.
No Webull paper order placement.
No real-money readiness.
```

Current operating status:

```text
Dashboard LaunchAgent is installed and running at http://127.0.0.1:8765.
Autonomous paper workflow LaunchAgent is installed.
Paper session dashboard buttons are installed.
Paper preview cycle runs successfully.
Safety test suite is passing with 52 tests.
```

Current progress bar:

```text
Raw paper rows: 0
Completed paper trades: 0
Allowed completed trades: 0
First paper checkpoint: 0 / 30
Strong paper checkpoint: 0 / 60
Ready candidates: 0
Eligible local paper rows: 0
Open paper trades: 0
Exit updates ready: 0
```

Latest state:

```text
Market status: after_close
Next market session: 2026-05-28
Latest scanner session: 2026-05-27
Data status: outside_market_hours
Readiness verdict: today's scanner data is no longer actionable; refresh data during the next market session.
```

Main controls now available in the dashboard Signal Workflow section:

```text
Run paper preview
Confirm local paper entry
Confirm local paper exits
```

Important files changed/added in this session:

```text
run_paper_session_cycle.py
run_open_paper_monitor.py
run_app.py
app/index.html
app/app.js
app/styles.css
APP_MANUAL.md
README.md
tests/test_workflow_safety.py
logs/paper_session_cycle.md
logs/open_paper_trade_monitor.md
logs/paper_candidate_alerts.md
logs/local_paper_execution_simulator.md
```

Next safest task:

```text
On 2026-05-28 during market hours, run or use the dashboard preview action after fresh data is collected.
Watch for paper_review_ready candidates.
Only confirm local paper entry if the dashboard/report shows a current-candle allowed size_ok candidate.
Keep broker/Webull order execution disabled.
```

Useful commands:

```bash
open "Project Gwala Dashboard.app"
.venv/bin/python run_daily_workflow.py --refresh-data
.venv/bin/python run_paper_session_cycle.py
.venv/bin/python run_paper_session_cycle.py --confirm-local-paper
.venv/bin/python run_paper_session_cycle.py --confirm-exits
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

## Paper Session Cycle Added On May 27

Added one safe operator command for the current local paper-validation loop.

Files:

```text
run_paper_session_cycle.py
logs/paper_session_cycle.md
```

Integrated:

```text
run_app.py exposes the paper_session report endpoint.
app/app.js shows a Paper Session report tab.
README.md and APP_MANUAL.md document the command and report.
```

Behavior:

```text
Default mode is preview-only.
Runs candidate alerts, local paper execution preview, open paper monitor, paper review, refresh status, and system state.
Writes local paper entries only with --confirm-local-paper.
Writes local paper exits only with --confirm-exits.
Does not place Webull paper orders, real orders, broker alerts, or broker execution calls.
```

Current preview:

```text
Paper candidates ready for review: 0
Eligible local paper rows: 0
Exit updates ready: 0
Still open: 0
```

Useful commands:

```bash
.venv/bin/python run_paper_session_cycle.py
.venv/bin/python run_paper_session_cycle.py --confirm-local-paper
.venv/bin/python run_paper_session_cycle.py --confirm-exits
```

Verified:

```bash
.venv/bin/python -m py_compile run_paper_session_cycle.py run_app.py tests/test_workflow_safety.py
.venv/bin/python run_paper_session_cycle.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
51 workflow safety tests passed.
```

## Paper Session Dashboard Buttons Added On May 27

Added dashboard controls for the safe local paper cycle.

Files changed:

```text
run_app.py
app/index.html
app/app.js
app/styles.css
README.md
APP_MANUAL.md
tests/test_workflow_safety.py
```

Buttons in the Signal Workflow section:

```text
Run paper preview
Confirm local paper entry
Confirm local paper exits
```

Backend routes:

```text
POST /api/actions/paper-session-preview
POST /api/actions/paper-session-confirm-entry
POST /api/actions/paper-session-confirm-exits
```

Safety behavior:

```text
Preview runs run_paper_session_cycle.py with no confirm flags.
Confirm entry only adds --confirm-local-paper.
Confirm exits only adds --confirm-exits.
All actions end by refreshing system_state.json.
No broker orders, Webull paper orders, real trades, broker alerts, or Webull order endpoint calls.
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
.venv/bin/python run_paper_session_cycle.py
bash scripts/install_dashboard_launch_agent.sh
```

Result:

```text
52 workflow safety tests passed.
Dashboard LaunchAgent reloaded and running.
Paper preview cycle ran with 0 ready candidates and no writes.
```

## Open Paper Trade Monitor Added On May 27

Added a local paper-trade exit monitor.

Files:

```text
run_open_paper_monitor.py
logs/open_paper_trade_monitor.csv
logs/open_paper_trade_monitor.md
```

Integrated:

```text
run_daily_workflow.py runs run_open_paper_monitor.py after candidate alerts.
run_app.py exposes the open_paper_monitor report endpoint.
app/app.js shows an Open Paper Monitor report tab.
README.md and APP_MANUAL.md document the report.
```

Behavior:

```text
Reads open rows from data/paper_trades.csv.
Uses saved logs/webull_SYMBOL_M5_candles.csv files.
Previews stop, target, or end-of-day exit updates by default.
Only writes completed local paper exits with --confirm-updates.
Does not place orders, create broker alerts, call Webull order endpoints, or connect to broker execution.
```

Current preview:

```text
Exit updates ready: 0
Still open: 0
```

Useful commands:

```bash
.venv/bin/python run_open_paper_monitor.py
.venv/bin/python run_open_paper_monitor.py --confirm-updates
```

Verified:

```bash
.venv/bin/python run_open_paper_monitor.py
.venv/bin/python -m py_compile run_open_paper_monitor.py run_daily_workflow.py run_app.py tests/test_workflow_safety.py
Node syntax parse for app/app.js
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
50 workflow safety tests passed.
```

## Candidate Alerts Added On May 27

Added a candidate alert/readiness layer.

Files:

```text
run_candidate_alerts.py
logs/paper_candidate_alerts.csv
logs/paper_candidate_alerts.md
```

Integrated:

```text
run_daily_workflow.py runs candidate alerts after local paper execution preview.
run_app.py exposes the candidate_alerts report endpoint.
app/app.js shows a Candidate Alerts report tab.
README.md and APP_MANUAL.md document the report.
```

Ready condition:

```text
market is open
scanner row is from today's session
scanner_status = allowed
signal_freshness = current_candle
sizing_status = size_ok
```

Current run:

```text
Paper candidates ready for review: 0
```

Verified:

```bash
.venv/bin/python run_candidate_alerts.py
.venv/bin/python -m py_compile run_candidate_alerts.py run_daily_workflow.py run_app.py tests/test_workflow_safety.py
Node syntax parse for app/app.js
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
49 workflow safety tests passed.
```

## Paper Execution Preview Integrated On May 27

Integrated the local paper execution simulator into the normal workflow.

Changed:

```text
run_daily_workflow.py
run_app.py
app/app.js
APP_MANUAL.md
README.md
PROJECT_MEMORY.md
HANDOFF.md
```

Behavior:

```text
run_daily_workflow.py runs run_paper_execution_simulator.py after position sizing.
Future autonomous market scans automatically create logs/local_paper_execution_simulator.md.
The dashboard Reports section includes Paper Execution.
This remains preview-only during the automated workflow.
```

Current preview:

```text
Eligible local paper rows: 0
New local paper orders: 0
Preview only; no rows written.
```

Verified:

```bash
.venv/bin/python -m py_compile run_daily_workflow.py run_app.py run_paper_execution_simulator.py execution/paper_trader.py tests/test_workflow_safety.py
.venv/bin/python run_paper_execution_simulator.py
Node syntax parse for app/app.js
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
48 workflow safety tests passed.
```

## FINAL SAVED SESSION POINTER - 2026-05-27 AFTER CLOSE

The latest saved state is the dashboard paper-validation operating stage:

```text
Dashboard running: http://127.0.0.1:8765
Dashboard paper buttons installed: Run paper preview, Confirm local paper entry, Confirm local paper exits
Safety tests passing: 52
Paper progress: 0 / 30 first checkpoint, 0 / 60 strong checkpoint
Ready candidates: 0
Eligible local paper rows: 0
Open paper trades: 0
Broker/Webull order execution: disabled
Next safest action: refresh market data during the 2026-05-28 session and run paper preview.
```

## 2026-05-30 Strategy Overlap Audit Added

Digested `/Users/roy/Downloads/project_gwala_strategy_upgrade_handoff.md` and
created a generated audit comparing the current codebase against the
professional trend-following framework.

Files:

```text
run_strategy_overlap_audit.py
logs/strategy_overlap_audit.md
logs/strategy_overlap_audit.csv
```

Dashboard:

```text
Reports -> Research -> Strategy Audit
```

Audit result:

```text
Exists: 10
Partial: 5
Missing: 1
Highest-value next move: formalize shared market regime + explicit reward-to-risk status before adding more entry rules.
```

Recommended implementation order:

```text
1. Promote market regime labeling into a shared reusable module and daily report.
2. Add explicit reward_to_risk_status to scanner/sizing outputs.
3. Add candle-based liquidity/dollar-volume filter.
4. Build filter impact matrix for regime, relative volume, liquidity, and R:R.
5. Add controlled partial+runner exit simulation after measurement is stable.
6. Keep collecting local paper trades; do not add broker execution yet.
```

Verified:

```bash
.venv/bin/python run_strategy_overlap_audit.py
.venv/bin/python -m py_compile run_strategy_overlap_audit.py run_app.py tests/test_workflow_safety.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
bash scripts/install_dashboard_launch_agent.sh
```

Result:

```text
81 workflow safety tests passed.
Dashboard LaunchAgent reloaded.

## 2026-05-31 Battery-Friendly Autonomous Schedule

The autonomous paper workflow has been changed from a persistent all-day
supervisor into short scheduled LaunchAgent runs. This is meant to reduce heat,
battery drain, and unnecessary background activity while the laptop is still the
host machine.

Added:

```text
tools/build_autonomous_launchd_plist.py
```

This script regenerates:

```text
launchd/com.project-gwala.autonomous-paper.plist
```

Current local Pacific-time schedule:

```text
Weekdays 6:15 AM = pre-market check
Weekdays 6:30 AM through 1:00 PM = run every 5 minutes
Weekdays 1:05 PM = after-close recap
```

Important behavior:

```text
The LaunchAgent calls run_autonomous_paper_workflow.py with --once.
RunAtLoad is disabled.
Each scheduled run starts, performs one workflow pass, then exits.
```

Installed user LaunchAgent:

```text
/Users/roy/Library/LaunchAgents/com.project-gwala.autonomous-paper.plist
```

Verified:

```bash
.venv/bin/python tools/build_autonomous_launchd_plist.py
plutil -lint launchd/com.project-gwala.autonomous-paper.plist
.venv/bin/python -m py_compile tools/build_autonomous_launchd_plist.py run_autonomous_paper_workflow.py tests/test_workflow_safety.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
bash scripts/install_autonomous_launch_agent.sh
launchctl print gui/501/com.project-gwala.autonomous-paper
```

Result:

```text
405 calendar schedule entries generated.
Plist is valid.
87 workflow safety tests passed.
LaunchAgent is installed and loaded.
launchctl shows the service configured with --once and waiting for scheduled triggers.
```

Operational note:

```text
The laptop still needs to be awake and signed in during the market window.
This does not place broker orders and does not add real-money execution.
The workflow remains local paper validation / forward evidence collection.
```

## 2026-05-31 Morning Run Watchdog Added

Added a status-only watchdog report so the dashboard can confirm whether the
scheduled morning workflow ran after the 6:30 AM PT market scan.

Files:

```text
run_morning_watchdog.py
logs/morning_run_watchdog.json
logs/morning_run_watchdog.md
```

Integrated:

```text
run_autonomous_paper_workflow.py writes logs/autonomous_paper_workflow_status.json.
run_daily_workflow.py runs run_morning_watchdog.py near the end of each daily workflow.
reports/system_state.py exposes morning_watchdog in logs/system_state.json.
run_app.py serves Reports -> Daily Workflow -> Morning Watchdog.
app/app.js uses the watchdog on the Home automation card.
README.md and APP_MANUAL.md document the report.
```

The watchdog checks:

```text
Autonomous status wrote today
Market scan due
Market scan ran today
Webull refresh confirmed today
Scanner session is today
Current candidate count
Reviewable candidate count
Allowed candidate count
Next action
```

Current report before the first scheduled scan:

```text
pending: Morning scheduled workflow is not due yet.
Next action: Keep the laptop awake for the first 6:30 AM PT scheduled run.
```

Verified:

```bash
.venv/bin/python -m py_compile run_morning_watchdog.py run_autonomous_paper_workflow.py run_daily_workflow.py run_app.py reports/system_state.py tests/test_workflow_safety.py
.venv/bin/python run_morning_watchdog.py
.venv/bin/python run_system_state.py
.venv/bin/python -m unittest tests.test_workflow_safety.MarketCalendarTests -v
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
89 workflow safety tests passed.
No broker orders, Webull paper orders, broker alerts, or automatic paper imports were added.
```

## 2026-05-31 Post-Scan Candidate Digest Added

Added a compact status-only report that converts the latest scanner/sample
state into one paper-action decision.

Files:

```text
run_post_scan_digest.py
logs/post_scan_digest.json
logs/post_scan_digest.md
```

Integrated:

```text
run_daily_workflow.py runs the digest after forward_sample_queue and no_trade_analysis.
reports/system_state.py exposes post_scan_digest.
run_app.py serves Reports -> Paper Review -> Post-Scan Digest.
app/app.js adds the report and uses the digest on the Home candidate/action card.
README.md and APP_MANUAL.md document it.
```

Digest actions:

```text
review_candidate = manual checklist needed
watch_almost_ready = close setup, wait for next scan
study_blocker = no trade, but blocker pattern is worth reviewing
wait = nothing to do
data_issue = refresh/staleness problem first
```

Current saved digest:

```text
study_blocker: No candidate is ready, but 1 setup(s) are one rule away.
Closest setup: SPY Setup A Long, missing above opening range high.
Next action: Study the blocker pattern and keep collecting shadow evidence; do not loosen rules live.
```

Verified:

```bash
.venv/bin/python -m py_compile run_post_scan_digest.py run_daily_workflow.py run_app.py reports/system_state.py tests/test_workflow_safety.py
.venv/bin/python run_post_scan_digest.py
.venv/bin/python run_system_state.py
.venv/bin/python -m unittest tests.test_workflow_safety.MarketCalendarTests.test_post_scan_digest_prioritizes_ready_candidate tests.test_workflow_safety.MarketCalendarTests.test_post_scan_digest_surfaces_one_rule_blocker -v
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
91 workflow safety tests passed.
No broker orders, Webull paper orders, broker alerts, automatic paper imports, or strategy-rule changes were added.
```

## 2026-05-31 Daily Automation Timeline Added

Added a status-only automation timeline so tomorrow's scheduled workflow can be
debugged from one readable report instead of raw LaunchAgent logs.

Files:

```text
run_daily_automation_timeline.py
logs/daily_automation_timeline.json
logs/daily_automation_timeline.md
```

Integrated:

```text
run_autonomous_paper_workflow.py runs the timeline after scheduled actions.
run_daily_workflow.py runs the timeline near the end of the daily workflow.
reports/system_state.py exposes automation_timeline.
run_app.py serves Reports -> Daily Workflow -> Automation Timeline.
app/app.js adds Automation Timeline to Reports, Workflow, and App Health.
README.md and APP_MANUAL.md document it.
```

The timeline summarizes:

```text
autonomous status
morning watchdog
post-scan digest
recent LaunchAgent command blocks
recent possible failures from stdout/stderr logs
file health for key automation artifacts
```

Current saved report:

```text
pending: Automation is not due yet or the first scan has not finished.
Recent possible failures: none.
autonomous_status_json is missing only because the latest status Markdown was written before the JSON upgrade.
```

Verified:

```bash
.venv/bin/python -m py_compile run_daily_automation_timeline.py run_autonomous_paper_workflow.py run_daily_workflow.py run_app.py reports/system_state.py tests/test_workflow_safety.py
.venv/bin/python run_daily_automation_timeline.py
.venv/bin/python run_system_state.py
.venv/bin/python -m unittest tests.test_workflow_safety.MarketCalendarTests.test_automation_timeline_tolerates_missing_autonomous_json tests.test_workflow_safety.MarketCalendarTests.test_automation_timeline_flags_recent_log_failures -v
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
93 workflow safety tests passed.
No data fetch, broker order, Webull paper order, broker alert, automatic paper import, or strategy-rule change was added.
```
```

## 2026-05-30 Opening Range Relaxation Review Added

Backtested the existing `no_opening_range` variant against `current` using
saved Webull CSV data for SPY, QQQ, TSLA, and AAPL with `no_vwap_exit`.

Files:

```text
run_opening_range_relaxation_review.py
logs/opening_range_relaxation_review.md
logs/opening_range_relaxation_review.csv
```

Dashboard:

```text
Reports -> Research -> Opening Range Test
```

Latest result:

```text
Opening-range relaxation added 26 historical trades across this run.
SPY: shadow_test_only, +4 trades, expectancy stayed positive but weaker: 0.0502R -> 0.0412R.
QQQ: reject_relaxation, expectancy fell from 0.1958R to -0.1238R.
TSLA: reject_relaxation, expectancy worsened.
AAPL: less_bad_but_not_tradeable, still negative.
```

Decision:

```text
Do not remove the opening-range rule globally.
If no-trade analysis keeps showing one-rule opening-range misses, collect those as shadow/watch evidence first.
Only promote a relaxed opening-range rule if it improves expectancy or paper-watch outcomes for a specific symbol/setup.
```

Verified:

```bash
.venv/bin/python run_webull_watchlist.py --reuse-csv --symbols SPY QQQ TSLA AAPL --variants current no_opening_range --exit-profiles no_vwap_exit --output-dir logs --pause 0
.venv/bin/python run_opening_range_relaxation_review.py
.venv/bin/python -m py_compile run_opening_range_relaxation_review.py run_app.py tests/test_workflow_safety.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
bash scripts/install_dashboard_launch_agent.sh
```

Result:

```text
83 workflow safety tests passed.
Dashboard LaunchAgent reloaded.
```

## 2026-05-30 Shadow Sample Collection Added

Added a research-only shadow sample lane for near-miss setups. This lets the
project collect evidence on blocked trades without treating them as official
paper trades.

Files:

```text
run_shadow_samples.py
data/shadow_samples.csv
logs/shadow_sample_outcomes.csv
logs/shadow_samples.md
```

Dashboard:

```text
Reports -> Paper Review -> Shadow Samples
```

How to run manually:

```bash
.venv/bin/python run_shadow_samples.py
```

To backfill the latest saved scanner snapshot, even outside market freshness:

```bash
.venv/bin/python run_shadow_samples.py --record-latest-snapshot
```

Latest result:

```text
2 new shadow samples appended.
SPY Setup A Long was one rule away from passing.
TSLA Setup B Short was a close-watch shadow setup.
0 matured outcomes yet because complete regular-session 5m candles were not available.
```

Important guardrail:

```text
Shadow samples are not trades.
They do not count toward the 30/60 official paper-trade gates.
They do not place broker orders.
Use them only to decide whether a blocked rule deserves more backtesting/paper review.
```

Verified:

```bash
.venv/bin/python -m py_compile run_shadow_samples.py run_daily_workflow.py run_paper_session_cycle.py run_app.py tests/test_workflow_safety.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
84 workflow safety tests passed.
Dashboard LaunchAgent reloaded.
Dashboard API serves /api/report?name=shadow_samples.
```

## 2026-05-30 Forward Evidence Dashboard Added

Added one report that shows the whole forward proof trail in one place:
official paper trades, forward observations, shadow samples, and the current
sample queue.

Files:

```text
run_forward_evidence.py
logs/forward_evidence.md
```

Dashboard:

```text
Reports -> Paper Review -> Forward Evidence
```

How to run manually:

```bash
.venv/bin/python run_forward_evidence.py
```

Latest result:

```text
Official paper gate: 0 / 30
Forward observations: 7
Matured forward observation outcomes: 7
Allowed observation average: -0.1844R
Shadow samples: 2
Matured shadow outcomes: 0
Current ready queue: 0
Total learning rows: 9
```

Important read:

```text
The app now has forward evidence, but not official paper-trade proof yet.
The existing observation outcomes are negative on average, so do not rush into
execution. Keep collecting current-candle official paper trades and shadow
samples until the evidence gate is meaningful.
```

Verified:

```bash
.venv/bin/python -m py_compile run_forward_evidence.py run_daily_workflow.py run_paper_session_cycle.py run_app.py tests/test_workflow_safety.py
.venv/bin/python run_forward_evidence.py
.venv/bin/python run_paper_session_cycle.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
bash scripts/install_dashboard_launch_agent.sh
curl -s "http://127.0.0.1:8765/api/report?name=forward_evidence"
```

Result:

```text
85 workflow safety tests passed.
Dashboard LaunchAgent reloaded.
Dashboard API serves /api/report?name=forward_evidence.
```

## 2026-05-31 M5 Provider Final-Bar Handling Added

Fixed the M5 completeness issue. Webull sometimes returns 15:50 ET as the
latest available 5m bar for a regular 16:00 ET session. The app now keeps this
visible as `provider_final_bar` instead of treating it as a broken partial
session.

Changed:

```text
run_data_integrity.py classifies M5 coverage as complete, provider_final_bar,
in_progress, or partial_session.

run_forward_observation_review.py accepts complete and provider_final_bar for
closed-session outcome grading.

reports/system_state.py and run_premarket_verification.py no longer count
provider_final_bar as an integrity issue.

run_refresh_audit.py records files_present_provider_final_bar.
```

Latest result:

```text
Candle integrity warnings: 0
System state integrity_issue_count: 0
Shadow samples matured: 2 / 2
SPY Setup A Long shadow: -0.1228R
TSLA Setup B Short shadow: -1.0R
Forward evidence shadow average: -0.5614R
```

Important read:

```text
The data gap is fixed, but the first shadow outcomes are negative. Do not
promote opening-range relaxation from this evidence. Keep collecting live
market-session official paper trades and shadow samples.
```

Verified:

```bash
.venv/bin/python -m py_compile run_data_integrity.py run_forward_observation_review.py run_shadow_samples.py run_refresh_audit.py run_premarket_verification.py run_system_state.py reports/system_state.py tests/test_workflow_safety.py
.venv/bin/python run_data_integrity.py
.venv/bin/python run_shadow_samples.py --record-latest-snapshot
.venv/bin/python run_forward_observation_review.py
.venv/bin/python run_forward_evidence.py
.venv/bin/python run_refresh_status.py
.venv/bin/python run_system_state.py
.venv/bin/python run_refresh_audit.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
```

Result:

```text
85 workflow safety tests passed.
```

## 2026-05-31 Candidate Aging Review Added

Added candidate aging to measure whether scanner rows, forward observations,
shadow samples, and paper trades are appearing early enough in the session.

Files:

```text
run_candidate_aging.py
logs/candidate_aging.csv
logs/candidate_aging.md
```

Dashboard:

```text
Reports -> Paper Review -> Candidate Aging
```

How to run manually:

```bash
.venv/bin/python run_candidate_aging.py
```

Latest result:

```text
Candidate aging rows: 18
Aged outcome rows: 9
Late-day rows: 13
Late-day outcomes: 4
Late-day average: -0.4189R
Late-day win rate: 0%
Verdict: Late-day candidates are negative so far. Treat late signals as caution-only until more evidence improves.
```

Important read:

```text
Late-day signals are currently a weak pocket. Do not loosen rules for late-day
setups. Keep collecting Monday live-session evidence, especially earlier
signals, before changing entry timing rules.
```

Verified:

```bash
.venv/bin/python -m py_compile run_candidate_aging.py run_forward_evidence.py run_daily_workflow.py run_paper_session_cycle.py run_app.py tests/test_workflow_safety.py
.venv/bin/python run_candidate_aging.py
.venv/bin/python run_forward_evidence.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
bash scripts/install_dashboard_launch_agent.sh
curl -s "http://127.0.0.1:8765/api/report?name=candidate_aging"
```

Result:

```text
86 workflow safety tests passed.
Dashboard LaunchAgent reloaded.
Dashboard API serves /api/report?name=candidate_aging.
```

## 2026-05-30 No-Trade Blocker Analysis Added

Added a research-only report to explain why Gwala is not producing paper
candidates and whether the current rules are too tight for sample collection.

Files:

```text
run_no_trade_analysis.py
logs/no_trade_blocker_analysis.md
logs/no_trade_blocker_analysis.csv
```

Integrated:

```text
run_daily_workflow.py runs run_no_trade_analysis.py after the forward sample queue.
run_paper_session_cycle.py includes No-trade analysis in preview/confirm cycles.
run_app.py exposes no_trade_analysis.
app/app.js shows Reports -> Paper Review -> No-Trade Analysis.
README.md and APP_MANUAL.md document the report.
```

Latest report read:

```text
No trades are allowed, but 1 row is one rule away from passing.
Latest snapshot: 9 rows, 0 allowed, 1 one-rule miss, 2 rows at 75%+ check score.
Single-rule relaxation candidate: above opening range high.
Closest setup: SPY Setup A Long, 8/9 checks passed, missing only above opening range high.
```

Interpretation:

```text
The bot may be too tight for fast sample collection.
Do not loosen multiple rules at once.
Next best research task is to backtest opening range relaxation/variant against baseline.
```

Verified:

```bash
.venv/bin/python run_no_trade_analysis.py
.venv/bin/python run_paper_session_cycle.py
.venv/bin/python -m py_compile run_no_trade_analysis.py run_paper_session_cycle.py run_daily_workflow.py run_app.py tests/test_workflow_safety.py
.venv/bin/python -m unittest tests.test_workflow_safety -v
bash scripts/install_dashboard_launch_agent.sh
```

Result:

```text
82 workflow safety tests passed.
Dashboard LaunchAgent reloaded.
```
