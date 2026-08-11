# Project Memory

Use this file to transfer context between Codex windows.

At the start of a new session, ask Codex:

```text
Read AGENTS.md, PROJECT_MEMORY.md, and HANDOFF.md. Summarize the current
project status, safety rules, blockers, and the next safest coding task.
```

At the end of a work session, ask Codex:

```text
Update PROJECT_MEMORY.md and HANDOFF.md with what changed, what was verified,
what is still blocked, and the next recommended task.
```

## Current Project Status

This project is a beginner-readable Python research, backtesting, and forward
paper-validation framework for a VWAP + EMA opening trend continuation trading
strategy.

Current phase:

```text
research, backtesting, and paper validation only
```

The system may record observations and manually reviewed paper results. It
must not place real trades, connect to live broker execution, or automate
order placement in this phase.

## Strategy Context

The strategy uses:

```text
1H timeframe = higher-timeframe thesis
30m timeframe = entry signal
5m timeframe = exit management
VWAP = intraday control
9 EMA = short-term momentum
21 EMA = trend structure
200 EMA = macro trend filter
opening range = early-session strength filter
relative volume = participation filter
quality scoring = stricter A-setup filtering
```

The framework compares:

```text
baseline VWAP + EMA continuation signals
elite A-setup signals with stricter quality filters
```

## Safety Rules

Do not add:

```text
real-money execution
broker order placement
automated live trading
martingale logic
averaging down losers
revenge-trade behavior
overleverage
stop-loss removal
```

Live alerts may come later, after backtests are usable.
Paper trading may come after live alerts behave correctly.
Real execution should only be considered after backtesting, alerts, and paper
trading are proven.

## Current Priority

CSV import and Webull market-data-only collection are implemented. The current
priority is reliable forward paper validation, not adding another data-loader
feature.

The Tuesday, 2026-05-26 regular session has been captured through the close
with a market-data-only Webull refresh. No current-candle paper candidate was
available during the monitored scans, so no paper trade or forward observation
was recorded. The next regular session is Wednesday, 2026-05-27. Until
same-session Webull data produces a manually reviewed current-candle candidate,
paper import and paper position sizing remain blocked.

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

The forward evidence gates are 30 allowed completed paper trades for the first
useful checkpoint and 60 for a stronger checkpoint.

## Historical Data Blocker

Yahoo Finance through `yfinance` has been unreliable because requests failed
with DNS errors for:

```text
guce.yahoo.com
```

Because of that, local CSV import and Webull market-data CSV collection were
added.

Webull API access has been approved and local `.env` placeholders were created.
The user saved their app key and app secret locally in `.env`. Do not print,
inspect, or expose those values.

The main Python environment is Python 3.14.4. The Webull OpenAPI Python SDK
does not fit Python 3.14 cleanly, so Webull testing uses a separate Python
3.11 virtual environment named `.venv-webull`.

Python 3.11.9 was installed from the official python.org macOS installer
because Python 3.11.15 is source-only. `.venv-webull` was created and both
project requirements and `webull-openapi-python-sdk==2.0.7` were installed.

The Webull data-only probe reached Webull successfully and token verification
completed. The first historical bar request failed with:

```text
401 Unauthorized - Insufficient permission, please subscribe to stock quotes.
```

The user then claimed the free Nasdaq Basic - Non Display subscription. After
that, the Webull probe succeeded for SPY M5 candles with HTTP 200.

The probe now saves separate probe-only files:

```text
logs/webull_probe_SPY_M5.json = raw Webull response
logs/webull_probe_SPY_M5_candles.csv = normalized probe candles
```

This avoids replacing full workflow candle files during a small access check.

## Completed Data Work

CSV import support is now added. `main.py` accepts `--entry-csv` and
`--exit-csv`, and `data/market_data.py` has `load_candles_from_csv()`.

Added `data/webull_data.py` and `run_webull_watchlist.py`.

`run_webull_watchlist.py` fetches Webull M30 and M5 candles, pauses between
requests, runs baseline/elite backtests, and saves combined reports.

Latest full watchlist command:

```bash
source .venv-webull/bin/activate
python run_webull_watchlist.py --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT --entry-count 1200 --exit-count 1200 --entry-pages 1 --exit-pages 1 --pause 10
```

Latest combined reports:

```text
logs/webull_watchlist_backtest_summary.csv
logs/webull_watchlist_backtest_summary.md
```

Added diagnostics and variant comparison:

```text
reports/diagnostics.py
run_webull_watchlist.py --variants ...
```

Variants:

```text
current
elite_score_6
relvol_1_0
room_0_75
no_opening_range
balanced_relaxed
quality_entry
```

`quality_entry` uses high-quality trend conditions directly as the entry signal
instead of requiring them to overlap with the baseline pullback/reclaim signal.

Target command shape:

```bash
python main.py --entry-csv data/SPY_30m.csv --exit-csv data/SPY_5m.csv
```

Expected CSV columns:

```text
datetime,open,high,low,close,volume
```

Keep the implementation beginner-readable, modular, and research-first.

Webull data-only test command:

```bash
source .venv-webull/bin/activate
python tools/check_webull_data.py --symbol SPY --timespan M5 --count 20
```

CSV backtest command:

```bash
python main.py --symbol SPY --entry-csv logs/webull_SPY_M30_candles.csv --exit-csv logs/webull_SPY_M5_candles.csv
```

Webull watchlist command:

```bash
source .venv-webull/bin/activate
python run_webull_watchlist.py --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT --entry-count 1200 --exit-count 1200 --pause 10
```

Variant comparison command:

```bash
source .venv-webull/bin/activate
python run_webull_watchlist.py --symbols QQQ NVDA TSLA AMD AAPL META MSFT --reuse-csv --variants current quality_entry
```

Paged deeper-history command:

```bash
source .venv-webull/bin/activate
python run_webull_watchlist.py --symbols TSLA --entry-count 1200 --exit-count 1200 --entry-pages 2 --exit-pages 6 --pause 5 --variants current quality_entry
```

## Important Files

```text
AGENTS.md = standing Codex instructions and safety rules
HANDOFF.md = human-readable overview and next-step guide
PROJECT_MEMORY.md = compact context transfer between Codex windows
main.py = main backtest command
config/settings.py = strategy and risk settings
data/market_data.py = current market data loader
indicators/ = VWAP, EMA, session, opening range, timeframe helpers
strategies/ = baseline and elite signal logic
backtesting/ = trade simulation and performance metrics
reports/summary.py = plain-English report generator
logs/ = generated backtest outputs
tools/check_webull_data.py = data-only Webull market-data connection probe
requirements-webull.txt = Webull SDK dependency for Python 3.11 env
```

## Session Update Checklist

When ending a session, update this file with:

```text
what changed
files edited
commands/tests run
what passed
what failed or was not verified
new blockers
next recommended task
```

## Last Session Notes

Created this repo-local memory protocol so future Codex windows can recover
project context by reading `AGENTS.md`, `PROJECT_MEMORY.md`, and `HANDOFF.md`.

Started Webull market-data setup:

```text
Created .env and .env.example.
Confirmed .env has Webull key fields without printing secret values.
Created tools/check_webull_data.py for data-only candle testing.
Created requirements-webull.txt.
Updated README.md with Webull setup instructions.
Confirmed current Python is 3.14.4, so a Python 3.11 env is needed for SDK testing.
Installed Python 3.11.9, created .venv-webull, installed Webull SDK 2.0.7.
Ran Webull probe. Token verification succeeded, but market-data request failed because OpenAPI stock quotes are not enabled/subscribed.
Updated tools/check_webull_data.py to suppress SDK logs and avoid printing signed headers/tokens on failures.
User claimed Nasdaq Basic - Non Display. Reran probe successfully for SPY M5 candles.
Updated tools/check_webull_data.py to save normalized CSV output.
Added CSV import support in data/market_data.py and main.py.
Verified CSV backtest command completed using Webull M30 entry candles and M5 exit candles.
The limited Webull sample produced zero trades, meaning no qualifying setup triggered in that small window.
Ran Webull CSV backtests for SPY, QQQ, NVDA, TSLA, AMD, AAPL, META, and MSFT using 300 M30 candles and 300 M5 candles per symbol.
Initial rapid Webull fetch hit 429 TOO_MANY_REQUESTS; retrying the remaining symbols more slowly worked.
Saved aggregate metrics to logs/watchlist_csv_backtest_summary.csv.
Results from this limited sample:
- SPY, QQQ, NVDA, TSLA, AMD, META: 0 baseline trades and 0 elite trades.
- AAPL baseline: 2 trades, 0.0 win rate, -0.8673 expectancy R. AAPL elite: 0 trades.
- MSFT baseline: 2 trades, 1.0 win rate, 0.2299 expectancy R. MSFT elite: 0 trades.
Added reusable Webull data helper module and watchlist runner.
Ran full watchlist with 1200 M30 candles and 1200 M5 candles per symbol.
Results:
- SPY baseline: 9 trades, -0.1040R expectancy; elite: 0 trades.
- QQQ baseline: 12 trades, -0.1557R expectancy; elite: 0 trades.
- NVDA baseline: 4 trades, -0.1934R expectancy; elite: 0 trades.
- TSLA baseline: 4 trades, 0.7858R expectancy; elite: 0 trades.
- AMD baseline: 5 trades, 0.0890R expectancy; elite: 1 trade, -0.7749R expectancy.
- AAPL baseline: 10 trades, -0.3682R expectancy; elite: 0 trades.
- META baseline: 0 trades; elite: 0 trades.
- MSFT baseline: 2 trades, 0.2299R expectancy; elite: 0 trades.
Added signal diagnostics reports per symbol/variant.
Ran variant comparison. Removing opening range increased trade count but generally worsened expectancy, so the opening range filter appears useful.
Ran quality_entry variant:
- QQQ: 1 elite trade, -1.0000R.
- NVDA: 1 elite trade, +0.3465R.
- TSLA: 1 elite trade, +0.2895R.
- AMD: 2 elite trades, -0.4146R average.
- AAPL: 2 elite trades, +0.8923R average.
- META/MSFT: 0 elite trades.
Added Webull paging support:
- `data.webull_data.fetch_history_bars()` now supports `end_time`.
- `data.webull_data.fetch_history_bars_paged()` pages older candles by ending before the oldest candle in the previous page.
- `run_webull_watchlist.py` now supports `--entry-pages` and `--exit-pages`.
Smoke-tested paging with TSLA.
Ran deeper TSLA test with 2400 M30 candles and 7200 M5 candles:
- current baseline: 7 trades, 71.43% win rate, +0.4977R expectancy, 5.8198 profit factor.
- quality_entry elite: 2 trades, 50.00% win rate, -0.0920R expectancy, 0.6114 profit factor.
Ran full paged watchlist with 2400 M30 candles and 7200 M5 candles per symbol:
- SPY current baseline: 32 trades, +0.0260R expectancy, 1.1372 profit factor. quality_entry: 0 trades.
- QQQ current baseline: 28 trades, +0.0164R expectancy, 1.1035 profit factor. quality_entry: 4 trades, +0.5196R expectancy, 2.9542 profit factor.
- NVDA current baseline: 21 trades, -0.0461R expectancy. quality_entry: 7 trades, -0.0133R expectancy.
- TSLA current baseline: 7 trades, +0.4977R expectancy, 5.8198 profit factor. quality_entry: 2 trades, -0.0920R expectancy.
- AMD current baseline: 24 trades, -0.1377R expectancy. quality_entry: 7 trades, +0.0219R expectancy, 1.0671 profit factor.
- AAPL current baseline: 20 trades, -0.2177R expectancy. quality_entry: 2 trades, +0.8923R expectancy, 9.2851 profit factor.
- META current baseline: 10 trades, -0.2645R expectancy. quality_entry: 0 trades.
- MSFT current baseline: 9 trades, +0.0622R expectancy, 1.4453 profit factor. quality_entry: 1 trade, -0.3489R.
Added exit profile testing:
- `current`
- `target_1_5r`
- `no_vwap_exit`
- `breakeven_after_1r`
Ran offline exit-profile comparison on the paged Webull CSVs.
Best current-baseline exits:
- TSLA no_vwap_exit: 7 trades, +0.5254R expectancy, 7.0988 profit factor.
- MSFT target_1_5r: 9 trades, +0.1697R expectancy, 2.2146 profit factor.
- QQQ no_vwap_exit: 21 trades, +0.0711R expectancy, 1.4387 profit factor.
- AMD no_vwap_exit: 23 trades, +0.0595R expectancy, 1.2463 profit factor.
- SPY no_vwap_exit: 26 trades, +0.0371R expectancy, 1.1510 profit factor.
Best quality-entry exits:
- AAPL no_vwap_exit: 2 trades, +1.7001R expectancy.
- QQQ no_vwap_exit: 4 trades, +0.6317R expectancy, 3.5268 profit factor.
- NVDA no_vwap_exit: 7 trades, +0.2372R expectancy, 2.0146 profit factor.
- AMD no_vwap_exit: 7 trades, +0.1923R expectancy, 1.6500 profit factor.
Main research finding: `no_vwap_exit` improved most symbols; the VWAP-loss exit may be cutting winners too early.
Added exit-reason breakdowns to reports and reran current vs no_vwap_exit.
Key confirmation:
- QQQ current/current lost_vwap_5m: 14 trades, 0% win rate, -0.2886R expectancy.
- QQQ current/current end_of_day_exit: 14 trades, 78.57% win rate, +0.3213R expectancy.
- AMD current/current lost_vwap_5m: 12 trades, 0% win rate, -0.4095R expectancy.
- AMD current/current end_of_day_exit: 9 trades, 44.44% win rate, +0.1789R expectancy.
Conclusion: 5m VWAP-loss exit is probably too aggressive in this sample.
Added softer exit profiles:
- `two_vwap_closes`
- `bearish_vwap_loss`
- `ema9_exit`
Reran current and quality_entry across all symbols with current/no_vwap_exit/two_vwap_closes/bearish_vwap_loss/ema9_exit.
Average expectancy across symbols:
- current baseline no_vwap_exit: +0.0544R.
- current baseline two_vwap_closes: +0.0344R.
- current baseline bearish_vwap_loss: +0.0057R.
- current baseline current: -0.0080R.
- current baseline ema9_exit: -0.0477R.
- quality_entry elite no_vwap_exit: +0.3076R.
- quality_entry elite two_vwap_closes: +0.1737R.
- quality_entry elite bearish_vwap_loss: +0.1471R.
- quality_entry elite current: +0.1225R.
- quality_entry elite ema9_exit: -0.0762R.
Conclusion: softer exits help, but no_vwap_exit remains the best research candidate in this sample.
Added `--candidate-preset best` to `run_webull_watchlist.py`.
The preset compares:
- `current + no_vwap_exit`
- `quality_entry + no_vwap_exit`
Generated focused report:
- `logs/best_candidate_summary.md`
Generated selection report:
- `logs/candidate_selection_report.md`
Current best entry/exit candidate:
- Entry: `quality_entry`
- Exit: `no_vwap_exit`
Current broader candidate:
- Entry: `current`
- Exit: `no_vwap_exit`
Selected per-symbol long candidates:
- SPY: current + no_vwap_exit, 26 trades, +0.0371R expectancy, 1.151 PF.
- QQQ: quality_entry + no_vwap_exit, 4 trades, +0.6317R expectancy, 3.5268 PF.
- NVDA: quality_entry + no_vwap_exit, 7 trades, +0.2372R expectancy, 2.0146 PF.
- TSLA: current + no_vwap_exit, 7 trades, +0.5254R expectancy, 7.0988 PF.
- AMD: quality_entry + no_vwap_exit, 7 trades, +0.1923R expectancy, 1.65 PF.
- AAPL: quality_entry + no_vwap_exit, 2 trades, +1.7001R expectancy, infinite PF; low confidence due to only 2 trades.
- MSFT: current + no_vwap_exit, 9 trades, +0.0772R expectancy, 1.5893 PF.
- META: reject for long strategy for now; deeper test still negative.
```

Files changed:

```text
PROJECT_MEMORY.md
HANDOFF.md
.env
.env.example
.gitignore
README.md
requirements-webull.txt
tools/check_webull_data.py
```

Next recommended task:

```text
Use candidate_selection_report.md as the approval/watch/reject universe. Next likely improvement is gathering deeper history for watch_more symbols or testing short-side logic for rejected symbols like META.
```

## 2026-05-22 Confidence Filter Added

Added a minimum-trade confidence filter to `run_webull_watchlist.py`.

New CLI option:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best \
  --min-approved-trades 10
```

Default threshold:

```text
min-approved-trades = 10
```

Candidate status meanings:

```text
approved = expectancy_r > 0, profit_factor > 1, and trades >= 10
watch_more = expectancy_r > 0 and profit_factor > 1, but trades < 10
reject = fails expectancy/profit-factor math rule
```

Latest rerun with saved Webull CSVs:

```text
SPY: approved, current + no_vwap_exit, 26 trades, +0.0371R expectancy, 1.151 PF.
AAPL: watch_more, quality_entry + no_vwap_exit, 2 trades, +1.7001R expectancy, infinite PF.
QQQ: watch_more, quality_entry + no_vwap_exit, 4 trades, +0.6317R expectancy, 3.5268 PF.
TSLA: watch_more, current + no_vwap_exit, 7 trades, +0.5254R expectancy, 7.0988 PF.
NVDA: watch_more, quality_entry + no_vwap_exit, 7 trades, +0.2372R expectancy, 2.0146 PF.
AMD: watch_more, quality_entry + no_vwap_exit, 7 trades, +0.1923R expectancy, 1.65 PF.
MSFT: watch_more, current + no_vwap_exit, 9 trades, +0.0772R expectancy, 1.5893 PF.
META: reject, current + no_vwap_exit, 11 trades, -0.0909R expectancy, 0.5018 PF.
```

Current interpretation:

```text
Only SPY is approved under the 10-trade confidence rule.
QQQ, NVDA, TSLA, AMD, AAPL, and MSFT are promising but need more historical trades.
META remains rejected for this long strategy.
```

## 2026-05-22 Deeper Watchlist Fetch

Pulled deeper Webull history for the symbols that still needed confirmation.

Commands used:

```bash
python run_webull_watchlist.py \
  --symbols QQQ NVDA TSLA AMD AAPL MSFT \
  --entry-count 1200 \
  --exit-count 1200 \
  --entry-pages 4 \
  --exit-pages 12 \
  --pause 6 \
  --candidate-preset best \
  --min-approved-trades 10

python run_webull_watchlist.py \
  --symbols NVDA AMD AAPL MSFT \
  --entry-count 1200 \
  --exit-count 1200 \
  --entry-pages 8 \
  --exit-pages 24 \
  --pause 6 \
  --candidate-preset best \
  --min-approved-trades 10

python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset best \
  --min-approved-trades 10
```

Final status from `logs/candidate_selection_report.md`:

```text
QQQ: approved, quality_entry + no_vwap_exit, 10 trades, +0.3754R expectancy, 2.2513 PF.
TSLA: approved, current + no_vwap_exit, 25 trades, +0.0426R expectancy, 1.1323 PF.
SPY: approved, current + no_vwap_exit, 26 trades, +0.0371R expectancy, 1.151 PF.
AMD: watch_more, quality_entry + no_vwap_exit, 9 trades, +0.3831R expectancy, 2.6644 PF.
MSFT: reject, current + no_vwap_exit, 44 trades, -0.0026R expectancy, 0.987 PF.
AAPL: reject, current + no_vwap_exit, 62 trades, -0.0350R expectancy, 0.8831 PF.
NVDA: reject, quality_entry + no_vwap_exit, 16 trades, -0.0822R expectancy, 0.806 PF.
META: reject, current + no_vwap_exit, 11 trades, -0.0909R expectancy, 0.5018 PF.
```

Current interpretation:

```text
Approved for this long strategy: SPY, QQQ, TSLA.
Nearly approved but needs one more qualifying trade: AMD.
Rejected by larger sample: AAPL, NVDA, MSFT, META.
```

Important lesson:

```text
More history made the report stricter, not looser. AAPL, NVDA, and MSFT looked promising on smaller samples but failed after deeper data. That is a good research outcome because it prevents trusting weak candidates too early.
```

## 2026-05-22 SPY Market-Regime Filter

Added market-regime research variants to `run_webull_watchlist.py`.

New variants:

```text
market_confirmed
quality_entry_market_confirmed
```

New candidate presets:

```text
market
best_plus_market
```

Market confirmation rule:

```text
Use SPY 30m candles as the broad-market filter.
Only allow long entries when SPY close > SPY VWAP, SPY close > SPY 21 EMA, and SPY 9 EMA > SPY 21 EMA.
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

Latest status from `logs/candidate_selection_report.md`:

```text
QQQ: approved, quality_entry + no_vwap_exit, 10 trades, +0.3754R expectancy, 2.2513 PF.
TSLA: approved, market_confirmed + no_vwap_exit, 17 trades, +0.2151R expectancy, 2.1985 PF.
AAPL: approved, market_confirmed + no_vwap_exit, 33 trades, +0.1545R expectancy, 1.7618 PF.
SPY: approved, current + no_vwap_exit, 118 trades, +0.0375R expectancy, 1.1415 PF.
AMD: watch_more, quality_entry + no_vwap_exit, 9 trades, +0.3831R expectancy, 2.6644 PF.
MSFT: reject, current + no_vwap_exit, 44 trades, -0.0026R expectancy, 0.987 PF.
META: reject, quality_entry_market_confirmed + no_vwap_exit, 2 trades, -0.0640R expectancy, 0.0 PF.
NVDA: reject, quality_entry + no_vwap_exit, 16 trades, -0.0822R expectancy, 0.806 PF.
```

Interpretation:

```text
The SPY market-regime filter helped TSLA strongly and rescued AAPL from reject to approved.
It did not rescue NVDA, MSFT, or META.
AMD remains one qualifying trade short of approval; the non-market quality_entry version is still best for AMD.
```

## 2026-05-22 Setup B Started

Setup A is preserved as the approved long-side setup family.

Started Setup B as a separate bearish VWAP + EMA continuation research path.
This is still research/backtesting only.

New files/code paths:

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

Setup B command:

```bash
python run_webull_watchlist.py \
  --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT \
  --reuse-csv \
  --candidate-preset setup_b \
  --min-approved-trades 10
```

Setup B latest status:

```text
TSLA: approved, setup_b_short + no_vwap_exit, 23 trades, +0.1547R expectancy, 1.6527 PF.
AMD: approved, setup_b_short + no_vwap_exit, 47 trades, +0.1268R expectancy, 1.575 PF.
QQQ: approved, setup_b_short + no_vwap_exit, 26 trades, +0.0608R expectancy, 1.2714 PF.
AAPL: approved, setup_b_short + no_vwap_exit, 41 trades, +0.0379R expectancy, 1.1557 PF.
META: watch_more, setup_b_quality_short + no_vwap_exit, 4 trades, +0.5944R expectancy, 22.0967 PF.
MSFT: watch_more, setup_b_quality_short + no_vwap_exit, 5 trades, +0.3538R expectancy, 2.6144 PF.
NVDA: watch_more, setup_b_quality_short + no_vwap_exit, 9 trades, +0.1141R expectancy, 1.2166 PF.
SPY: watch_more, setup_b_quality_short + no_vwap_exit, 7 trades, +0.0154R expectancy, 1.046 PF.
```

Important interpretation:

```text
Setup B immediately shows promise as a broad bearish-continuation setup, especially TSLA and AMD.
For the rejected Setup A names, NVDA is closest to approval on Setup B with 9 quality-short trades.
MSFT and META look promising on quality shorts, but their samples are still very small.
```

Labeled reports were saved so Setup A and Setup B do not overwrite each other:

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

## 2026-05-22 Setup B Deeper Watch-More Test

Pulled deeper Webull history for the Setup B watch-more names:

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

Then reran Setup B across the full watchlist and refreshed:

```text
logs/setup_b_candidate_selection_report.md
logs/setup_b_candidate_summary.md
logs/setup_b_watchlist_backtest_summary.csv
logs/setup_b_watchlist_backtest_summary.md
```

Latest Setup B status:

```text
TSLA: approved, setup_b_short + no_vwap_exit, 23 trades, +0.1547R expectancy, 1.6527 PF.
AMD: approved, setup_b_short + no_vwap_exit, 47 trades, +0.1268R expectancy, 1.575 PF.
QQQ: approved, setup_b_short + no_vwap_exit, 26 trades, +0.0608R expectancy, 1.2714 PF.
NVDA: approved, setup_b_short + no_vwap_exit, 66 trades, +0.0494R expectancy, 1.1593 PF.
AAPL: approved, setup_b_short + no_vwap_exit, 41 trades, +0.0379R expectancy, 1.1557 PF.
META: watch_more, setup_b_quality_short + no_vwap_exit, 9 trades, +0.4659R expectancy, 2.9847 PF.
MSFT: watch_more, setup_b_quality_short + no_vwap_exit, 6 trades, +0.2693R expectancy, 2.2941 PF.
SPY: watch_more, setup_b_quality_short + no_vwap_exit, 7 trades, +0.0154R expectancy, 1.046 PF.
```

Important interpretation:

```text
NVDA is now approved under Setup B using the broader baseline short candidate.
META is one quality-short trade short of approval and still has strong stats.
MSFT remains promising but under-sampled.
```

## 2026-05-22 Approved Playbook Runner

Added the approved playbook config and runner.

New files:

```text
config/symbol_playbook.py
run_playbook.py
```

Command:

```bash
python run_playbook.py --mode approved
```

The approved playbook combines only the approved setup/symbol pairs:

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
Setup A Long: 178 trades, +0.0952R expectancy, 1.3845 PF.
Setup B Short: 203 trades, +0.0784R expectancy, 1.3055 PF.
```

By symbol:

```text
TSLA: 40 trades, +0.1804R expectancy, 1.8486 PF.
QQQ: 36 trades, +0.1482R expectancy, 1.6044 PF.
AMD: 47 trades, +0.1268R expectancy, 1.575 PF.
AAPL: 74 trades, +0.0899R expectancy, 1.3991 PF.
NVDA: 66 trades, +0.0494R expectancy, 1.1593 PF.
SPY: 118 trades, +0.0375R expectancy, 1.1415 PF.
```

Generated files:

```text
logs/playbook_approved_trades.csv
logs/playbook_approved_summary.csv
logs/playbook_approved_summary.md
```

Important limitation:

```text
The playbook report combines R results trade-by-trade. It is not yet a true portfolio simulator with capital allocation, overlapping-position limits, or daily risk caps across all symbols.
```

## 2026-05-22 Portfolio Simulator Added

Added portfolio-level simulation on top of the approved playbook.

New file:

```text
run_portfolio.py
```

Default command:

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

Default portfolio result:

```text
Accepted trades: 373
Skipped trades: 8
Win rate: 0.5121
Expectancy R: +0.0876
Profit factor: 1.3473
Max drawdown R: -10.0424
```

By setup:

```text
Setup A Long: 178 trades, +0.0952R expectancy, 1.3845 PF.
Setup B Short: 195 trades, +0.0807R expectancy, 1.3145 PF.
```

Default portfolio files:

```text
logs/portfolio_approved_accepted_trades.csv
logs/portfolio_approved_skipped_trades.csv
logs/portfolio_approved_daily_summary.csv
logs/portfolio_approved_summary.md
```

Also tested a stricter version:

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

## 2026-05-22 Portfolio Robustness Reports

Extended `run_portfolio.py` to generate:

```text
logs/portfolio_approved_equity_curve.csv
logs/portfolio_approved_monthly_summary.csv
logs/portfolio_approved_drawdown_stretches.csv
```

Default portfolio result after regeneration:

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
2025-05: 16 trades, -6.4482R total, -0.4030R expectancy, 0.1555 PF.
2026-01: 28 trades, -5.1208R total, -0.1829R expectancy, 0.4806 PF.
2025-10: 19 trades, -3.7504R total, -0.1974R expectancy, 0.4019 PF.
```

Worst drawdown stretch:

```text
Started trade 100 on 2025-04-16.
Trough at trade 131 on 2025-06-10.
Recovered at trade 251 on 2025-12-18.
Max drawdown: -9.3604R.
Duration: 152 trades.
```

Current interpretation:

```text
The playbook is positive overall, but it has a major regime weakness around spring/summer 2025 and another weak pocket in January 2026. The next improvement should target regime detection or risk reduction during those drawdown periods.
```

## 2026-05-22 Portfolio Monthly Loss Stop

Added a named preset to `run_portfolio.py`:

```bash
python run_portfolio.py --profile monthly_stop_3r
```

This uses the approved playbook with:

```text
Max open positions: 3
Max open positions per symbol: 1
Max trades per day: 5
Max daily realized loss: -3R
Max monthly realized loss: -3R
```

Monthly -3R stop result:

```text
Accepted trades: 340
Skipped trades: 44
Win rate: 0.5172
Expectancy R: +0.1135
Profit factor: 1.4677
Final cumulative R: +38.5937
Max drawdown R: -6.5803
```

Comparison to the previous default portfolio:

```text
Default expectancy: +0.0876R
Monthly stop expectancy: +0.1135R

Default profit factor: 1.3473
Monthly stop profit factor: 1.4677

Default max drawdown: -10.0424R
Monthly stop max drawdown: -6.5803R

Default final cumulative R: +32.6832R
Monthly stop final cumulative R: +38.5937R
```

Interpretation:

```text
The monthly -3R stop is the best current portfolio risk upgrade.
Prior-month SPY regime filters did not help, but the portfolio-level monthly loss stop improved expectancy, profit factor, drawdown, and total R.
Promote `--profile monthly_stop_3r` as the current preferred research profile.
```

## 2026-05-22 Exit Optimizer Upgrade

Added:

```text
run_exit_optimizer.py
```

Purpose:

```text
Keep the approved playbook fixed.
Change one exit profile at a time.
Score each test through the monthly_stop_3r portfolio profile.
Only promote changes that improve the whole portfolio.
```

Best individual changes:

```text
AAPL Setup B Short: no_vwap_exit -> two_vwap_closes
TSLA Setup A Long: no_vwap_exit -> two_vwap_closes
```

The two changes were tested together and promoted into `config/symbol_playbook.py`.

Updated approved playbook result with monthly_stop_3r:

```text
Accepted trades: 340
Skipped trades: 44
Win rate: 0.5176
Expectancy R: +0.1135
Profit factor: 1.4677
Final cumulative R: +38.5937
Max drawdown R: -6.5803
```

Approved exit upgrades:

```text
TSLA Setup A Long: market_confirmed + two_vwap_closes
AAPL Setup B Short: setup_b_short + two_vwap_closes
```

Current weakest approved symbols inside the updated monthly-stop portfolio:

```text
SPY: +0.0613R expectancy, 1.2345 PF
NVDA: +0.0822R expectancy, 1.2849 PF
```

Next recommended research:

```text
Test entry-filter upgrades for SPY and NVDA rather than changing the whole system.
```

## 2026-05-22 Entry Optimizer Pass

Added:

```text
run_entry_optimizer.py
```

Purpose:

```text
Keep the approved playbook fixed.
Change one entry variant at a time.
Score each test through the monthly_stop_3r portfolio profile.
Only promote changes that improve the whole portfolio.
```

Targeted pass:

```bash
python run_entry_optimizer.py --symbols SPY NVDA
```

Targeted result:

```text
No promotable SPY or NVDA entry upgrade.
NVDA setup_b_quality_short reduced drawdown slightly but lowered expectancy and final cumulative R.
SPY quality/market-confirmed variants lowered expectancy and final cumulative R.
```

Broad pass:

```bash
python run_entry_optimizer.py --symbols SPY QQQ TSLA AAPL AMD NVDA
```

Best one-change result:

```text
QQQ Setup B Short: setup_b_short -> setup_b_quality_short
Accepted trades: 327
Skipped trades: 36
Win rate: 0.5107
Expectancy R: +0.1150
Profit factor: 1.4678
Max drawdown R: -6.5803
Final cumulative R: +37.6103
```

Baseline for comparison:

```text
Accepted trades: 340
Skipped trades: 44
Win rate: 0.5176
Expectancy R: +0.1135
Profit factor: 1.4677
Max drawdown R: -6.5803
Final cumulative R: +38.5937
```

Decision:

```text
Do not promote any entry-filter upgrade from this pass.
The QQQ short quality-entry improvement is too small and gives up almost 1R of final cumulative return.
Current approved playbook remains unchanged after entry optimizer.
```

Next recommended research:

```text
Do targeted weakness analysis on SPY long and NVDA short losing trades by month, time of day, quality score, and exit reason.
Look for a narrow filter instead of broad variant swaps.
```

## 2026-05-22 Weakness Analyzer And Filter V1

Added:

```text
run_weakness_analyzer.py
```

Ran:

```bash
python run_weakness_analyzer.py --focus-symbols SPY NVDA
```

Important weak pockets:

```text
NVDA Setup B Short, 11-12 ET: 7 trades, -0.3155R expectancy, -2.2083R total
NVDA Setup B Short, relative volume 1.25-1.5: 6 trades, -0.7126R expectancy, -4.2757R total
NVDA Setup B Short, relative volume 0.75-1.0: 12 trades, -0.2462R expectancy, -2.9540R total
SPY Setup A Long, room-to-target 0.75R-1.0R: 6 trades, -0.2339R expectancy, -1.4031R total
```

Added optional trade filter to `run_portfolio.py`:

```bash
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
```

weakness_v1 blocks:

```text
NVDA Setup B Short: 11am ET entries
NVDA Setup B Short: relative volume 0.75-1.0 and 1.25-1.5
SPY Setup A Long: room-to-target 0.75R-1.0R
```

weakness_v1 result:

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

Previous best monthly_stop_3r result:

```text
Accepted trades: 340
Skipped trades: 44
Win rate: 0.5176
Expectancy R: +0.1135
Profit factor: 1.4677
Final cumulative R: +38.5937
Max drawdown R: -6.5803
```

Interpretation:

```text
weakness_v1 is the current best research profile.
It improves expectancy, win rate, profit factor, skipped trades, and final cumulative R without worsening max drawdown.
Because it was created from the existing weakness analysis, it may be sample-fit.
Validate it on a holdout/fresh-data split before treating it as durable.
```

Next recommended research:

```text
Add a holdout validation runner.
Compare base monthly_stop_3r versus monthly_stop_3r + weakness_v1 by date range.
The goal is to see whether weakness_v1 survives outside the exact sample used to discover it.
```

## 2026-05-22 Holdout Validation

Added:

```text
run_holdout_validation.py
```

Ran:

```bash
python run_holdout_validation.py
```

The runner compares base `monthly_stop_3r` versus `monthly_stop_3r --trade-filter weakness_v1`
across:

```text
full_sample
first_half
second_half
2024
2025
2026
```

Results:

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
weakness_v1 improved expectancy, profit factor, and final cumulative R in every internal validation window.
It also improved second-half drawdown from -6.3979R to -5.7953R, 2024 drawdown from -3.2782R to -1.5607R, and 2026 drawdown from -4.0211R to -3.8573R.
It did not improve max drawdown in full_sample, first_half, or 2025, but it did not worsen them.
This is a strong internal validation result.
```

Important caution:

```text
This is still not true fresh out-of-sample validation because weakness_v1 was discovered from the broad historical sample.
Before live alerts or paper-trading confidence, pull new Webull data later and rerun the playbook, portfolio, weakness_v1, and holdout validation.
```

Current best research profile:

```bash
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
```

## 2026-05-22 Paper Workflow Artifacts

Added:

```text
PLAYBOOK_CHEATSHEET.md
run_signal_journal.py
```

Purpose:

```text
Freeze the current best rules in human language.
Generate a paper-trade-style signal journal from approved playbook signals.
Label each signal as allowed or blocked by weakness_v1.
Record planned entry, stop, target, risk per share, exit profile, quality score, relative volume, and room to target.
```

Ran:

```bash
python run_signal_journal.py --trade-filter weakness_v1 --latest 30
```

Outputs:

```text
logs/paper_signal_journal.csv
logs/paper_signal_journal.md
```

Added:

```text
run_journal_insights.py
logs/journal_insights.md
```

Ran:

```bash
python run_journal_insights.py
```

Journal insights:

```text
weakness_v1 is focused, not broad. It blocks 28 historical signals.
Blocked signals came only from NVDA and SPY.
Allowed signals: 356 signals, +0.1202R average, +42.8060R total.
Blocked signals: 28 signals, -0.3469R average, -9.7125R total.
Strongest allowed symbol after filtering: NVDA, +0.2560R average.
Weakest allowed symbol after filtering: SPY, +0.0530R average.
Allowed Setup B Short signals: 184 signals, +0.1322R average, +24.3256R total.
Allowed Setup A Long signals: 172 signals, +0.1074R average, +18.4804R total.
```

Paper-trading implications:

```text
Track every allowed signal as a paper-trade candidate.
Track every blocked signal as watch-only.
Compare fresh allowed average R against +0.1202R.
Compare fresh blocked average R against -0.3469R.
If blocked signals start outperforming allowed signals, weakness_v1 may be regime-dependent or overfit.
SPY remains the weakest allowed symbol and should be watched closely during paper validation.
```

Latest journal summary:

```text
Allowed historical signals: 356
Blocked historical signals: 28
Allowed average historical R: +0.1202
Allowed total historical R: +42.8060
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

Interpretation:

```text
The paper workflow layer is now in place.
The project has a readable playbook and a repeatable signal journal.
No live execution or broker order placement has been added.
```

Next recommended task:

```text
When new Webull candles are available, rerun the fresh-data validation sequence:
python run_playbook.py --mode approved
python run_portfolio.py --profile monthly_stop_3r
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
python run_holdout_validation.py
python run_signal_journal.py
```

## 2026-05-22 Research Pipeline Runner

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

Holdout:
weakness_v1 improved expectancy and final R in full_sample, first_half, second_half, 2024, 2025, and 2026 windows.

Paper journal:
356 allowed signals, +0.1202R average, +42.8060R total
28 blocked signals, -0.3469R average, -9.7125R total
```

Current default command after adding fresh data:

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

Fresh holdout:

```text
full_sample:
weakness_v1 improved expectancy by +0.0236R and final R by +0.2293R

first_half:
weakness_v1 improved expectancy by +0.0311R and final R by +1.1127R

second_half:
weakness_v1 improved expectancy by +0.0031R but final R was -0.8834R lower
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
Fresh validation is positive overall. weakness_v1 still beat the base profile on expectancy, profit factor, max drawdown, and final cumulative R.
The edge improvement is smaller than the original historical test.
The blocked group was nearly flat rather than clearly bad, so weakness_v1 is not fully proven.
This is enough to move closer to structured paper validation, but not enough for real money.
```

Current confidence:

```text
Strategy idea: promising.
Backtest/research tooling: strong.
weakness_v1: fresh-data positive but still monitor.
Paper trading readiness: close, if journal discipline is followed.
Real-money readiness: no.
```

## Forward Paper Review Tool

Manual paper validation now has a dedicated tracker:

```text
data/paper_trades.csv
run_paper_review.py
logs/paper_review_summary.md
```

The script reviews allowed paper trades, blocked/watch-only signals, symbol
performance, setup performance, plan discipline, and exit reasons. It compares
fresh paper results against the latest fresh-data baselines:

```text
Allowed baseline: +0.1965R
Blocked baseline: -0.0023R
```

Next confidence gates:

```text
30 allowed paper trades
60 allowed paper trades
```

## Daily Paper Signal Scanner

Daily paper scanning is now available:

```text
run_daily_scanner.py
logs/daily_paper_signal_scanner.csv
logs/daily_paper_signal_scanner.md
logs/daily_paper_trade_import_template.csv
```

The scanner uses local Webull CSV candles and approved playbook entries. It
does not fetch data, send alerts, or place trades. It labels setups as:

```text
allowed
blocked_watch_only
not_ready
data_error
```

The generated import template can be copied into `data/paper_trades.csv` after
paper-trade results are known.

## Daily Workflow Cleanup

Daily workflow tools now exist:

```text
run_daily_workflow.py
run_paper_import.py
logs/daily_workflow_summary.md
```

Use:

```bash
python run_daily_workflow.py
```

This runs the scanner and paper review without refreshing data. To refresh
Webull CSV candles first, use:

```bash
python run_daily_workflow.py --refresh-data
```

The paper importer is conservative by default:

```bash
python run_paper_import.py --dry-run
```

It now writes only reviewed `current_candle` allowed signals from the current
open market session. Historical or earlier-today rows are preview/research
only, and automatic workflow import is disabled.

## Paper Position Sizer

Position sizing is now available:

```text
run_position_sizer.py
logs/position_sizing.csv
logs/position_sizing.md
```

The sizer reads `logs/daily_paper_signal_scanner.csv` and produces suggested
paper share sizes based on account size, risk per trade, planned entry, and
planned stop. It defaults to current-candle signals only.

Default risk assumptions:

```text
Account size: $10,000
Risk per trade: 0.50%
Risk budget: $50
```

## Trade Management Lab

Trade-management research now exists:

```text
run_trade_management_lab.py
logs/trade_management_lab.md
logs/trade_management_overall.csv
logs/trade_management_by_symbol.csv
logs/trade_management_by_setup.csv
```

The lab compares current exits, full targets at 1R/1.5R/2R, partial-at-1R
profiles, and breakeven-after-profit profiles using 5m candle path MFE/MAE.

Latest finding:

```text
Current management remains tied for best at +0.1842R expectancy.
Partial-at-1R reduced expectancy.
Do not change approved exits based on this sample.
```

## Project Dashboard

Mission-control dashboard now exists:

```text
run_dashboard.py
logs/project_gwala_dashboard.md
```

It reads the scanner, sizing, paper review, portfolio, holdout, and
trade-management outputs and gives one current action plus warnings.

Current dashboard state:

```text
No current-candle paper candidates.
No eligible current-candle position sizes.
0 completed allowed paper trades.
Next action: keep running the daily workflow and log valid current-candle paper trades until 30 allowed completed trades.
```

## Intraday Paper Loop

Intraday loop mode now exists:

```text
run_intraday_loop.py
logs/intraday_loop_status.md
```

Default behavior:

```text
Runs only during regular market hours.
Refreshes Webull data and reruns the daily workflow every 30 minutes.
Writes current-candle candidate and eligible sizing status.
Skips weekends and closed hours unless --force is used.
```

It is paper-only and does not place orders.

## Market Calendar

Market calendar guard now exists:

```text
config/market_calendar.py
run_market_calendar.py
```

`run_intraday_loop.py` uses it to skip weekends, NYSE holidays, observed
fixed-date holidays, Good Friday, and common early closes. Verified Memorial
Day 2026 and Black Friday 2026 behavior.

## Paper Outcome Updater

Paper-trade outcome updates now have a helper:

```text
run_update_paper_trade.py
```

Use:

```bash
python run_update_paper_trade.py --list-open
python run_update_paper_trade.py --row 1 --actual-entry ... --actual-exit ... --exit-time ... --followed-plan yes --exit-reason ...
```

It calculates `outcome_r` automatically from actual prices, planned stop, and
direction.

## Paper Validation Checkpoint

Checkpoint reporting now exists:

```text
run_checkpoint_report.py
logs/paper_validation_checkpoint.md
```

It tracks raw paper rows, completed trades, allowed completed trades, blocked
completed trades, average R versus baseline, and progress toward 30/60-trade
confidence gates.

## Paper Workflow Drill

Sandbox paper workflow rehearsal now exists:

```text
run_paper_drill.py
logs/paper_drill/paper_drill_summary.md
logs/paper_drill/paper_drill_trades.csv
logs/paper_drill/paper_review_summary.md
logs/paper_drill/paper_validation_checkpoint.md
```

Use:

```bash
python run_paper_drill.py
```

The drill uses the latest scanner output, creates one fake completed trade,
runs the paper review, and runs the checkpoint report inside `logs/paper_drill`.
It is sandbox-only and leaves `data/paper_trades.csv` untouched.

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

The project now has a fuller non-market-hours support layer:

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

The normal daily workflow now runs these support reports automatically after
scanner, sizing, review, checkpoint, and dashboard.

```bash
python run_daily_workflow.py
```

Report purpose:

```text
daily_trade_plan.md = market calendar, risk box, approved playbook, current candidates, permission rules
trade_entry_checklist.md = required checks before any paper trade
paper_mistake_tracker.md = structured process mistake log and summary
daily_recap.md = end-of-day scanner/progress recap
```

## Market-Open Readiness Check

The project now has a readiness command:

```text
run_readiness_check.py
logs/readiness_check.md
```

Use:

```bash
python run_readiness_check.py
```

It checks market calendar status, Webull key names in `.env` without printing
values, approved-symbol Webull M30/M5 CSV coverage, scanner freshness, eligible
position sizes, paper-log schema, open paper rows needing outcomes, support
files, and paper progress toward the 30-trade gate.

The normal daily workflow now updates readiness too:

```bash
python run_daily_workflow.py
```

Current off-market verdict:

```text
During market hours, run python run_daily_workflow.py --refresh-data and wait
for current-candle candidates.
```

## 2026-05-24 Setup B Runner Cleanup

Continued from the prior session by checking the Setup B watchlist path.

Fixed a report-routing bug in `run_webull_watchlist.py`:

```text
setup_b_short now uses elite_short_signal for its stricter comparison leg.
Previously that comparison leg accidentally pointed at elite_long_signal.
```

Also added automatic preset-labeled report outputs. When the runner is called
with a candidate preset, it now saves both the generic latest-run reports and
the preset archive reports:

```text
logs/{preset}_watchlist_backtest_summary.csv
logs/{preset}_watchlist_backtest_summary.md
logs/{preset}_candidate_summary.md
logs/{preset}_candidate_selection_report.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_webull_watchlist.py
```

Also reran a quick Setup B reuse test against the currently cached local CSVs:

```bash
.venv/bin/python run_webull_watchlist.py --symbols SPY QQQ NVDA TSLA AMD AAPL META MSFT --reuse-csv --candidate-preset setup_b --exit-profiles no_vwap_exit
```

Important note:

```text
That quick reuse test used the current local webull_SYMBOL_M30/M5 CSV files,
which only contained 1200 entry and 1200 exit candles at the time. It is not
comparable to the archived deeper Setup B reports.
```

Next recommended task:

```text
Run the normal daily workflow during market hours with --refresh-data, then use
the scanner, position sizing, checklist, and paper log to collect forward paper
trades. Keep real-money execution disabled.
```

## 2026-05-24 Off-Market Safety Improvements

Because the market is closed for the weekend and Memorial Day on 2026-05-25,
the system was improved for off-market prep.

Changed:

```text
run_dashboard.py
run_daily_scanner.py
logs/project_gwala_dashboard.md
logs/daily_paper_signal_scanner.md
logs/readiness_check.md
```

Dashboard improvement:

```text
Added a Data Freshness gate using the local NYSE calendar.
If scanner data is stale, the dashboard says prep only.
It names the next market session and the exact refresh command.
It hides actionable current-candle candidates and eligible sizing rows unless
data is fresh for today.
```

Scanner improvement:

```text
Added a Data Freshness table to the scanner report.
When data is stale/off-market, candidate rows are labeled historical/prep-only
with a clear warning not to import, size, or paper trade them.
```

Verified:

```bash
.venv/bin/python -m py_compile run_dashboard.py run_daily_scanner.py run_readiness_check.py
.venv/bin/python run_daily_scanner.py
.venv/bin/python run_dashboard.py
.venv/bin/python run_readiness_check.py
```

Current dashboard action:

```text
Prep only. On 2026-05-26, run python run_daily_workflow.py --refresh-data
before importing or sizing any paper trade.
```

## 2026-05-24 Setup Health Report

Added a setup health scoring report:

```text
run_setup_health.py
logs/setup_health.csv
logs/setup_health.md
```

The report scores each approved playbook setup by:

```text
trade count
expectancy R
profit factor
max drawdown R
recent expectancy / recent profit factor
```

Status meanings:

```text
healthy = at least 30 trades and strong enough to keep paper-tracking
watch = positive but still needs monitoring
watch_more = promising but under-sampled below 10 trades
caution = weak math or recent weakness
```

Important current finding:

```text
No setup is labeled healthy yet because none has 30 trades in the latest fresh
playbook sample. Several are positive but still watch/watch_more.
AAPL Setup B Short is caution because expectancy is slightly negative and
profit factor is below 1.
SPY Setup A Long remains watch, but recent trades are weak.
```

The dashboard now reads `logs/setup_health.csv` and shows the setup health rows
that need the most attention.

The daily workflow now runs:

```bash
python run_setup_health.py
```

before rebuilding the dashboard.

Verified:

```bash
.venv/bin/python -m py_compile run_setup_health.py run_dashboard.py run_daily_workflow.py
.venv/bin/python run_setup_health.py
.venv/bin/python run_dashboard.py
```

## 2026-05-24 App-Ready System State

Added a structured system-state layer for future app/dashboard work:

```text
reports/system_state.py
run_system_state.py
logs/system_state.json
logs/system_state.md
```

Purpose:

```text
Give the project one app-ready source of truth for market status, stale-data
state, scanner status, position sizing, paper progress, setup health, safety
flags, and next action.
```

The JSON includes:

```text
schema_version
project_phase
safety flags
market
data_freshness
scanner
position_sizing
paper_progress
setup_health
readiness_verdict
source_files
```

Important current verdict:

```text
Prep only. On 2026-05-26, run python run_daily_workflow.py --refresh-data
before importing or sizing any paper trade.
```

The daily workflow now runs:

```bash
python run_system_state.py
```

after setup health and before the dashboard.

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_daily_workflow.py
.venv/bin/python run_system_state.py
```

Standing recommendation checklist after this upgrade:

```text
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Collect only valid current-candle paper trades until the 30-trade checkpoint.
[ ] Review setup health before trusting any approved setup.
[ ] Keep AAPL Setup B Short under caution until its math improves.
[ ] Preserve app-ready JSON/CSV outputs as the source for any future UI.
```

## 2026-05-24 System State Integration

Integrated the app-ready system state into the existing reports.

Changed:

```text
run_dashboard.py
run_readiness_check.py
logs/project_gwala_dashboard.md
logs/readiness_check.md
```

Dashboard now uses `reports.system_state.build_system_state()` for:

```text
readiness verdict
data freshness
paper progress
```

Readiness check now uses system state for the main verdict when there are no
blocked readiness items, and includes an `App System State` snapshot:

```text
project_phase
data_status
latest_scanner_session
current_candidate_count
eligible_size_count
allowed_completed_trades
setup_health_attention_count
live_trading_enabled
real_money_ready
```

Readiness support-file checks now include:

```text
logs/system_state.json
logs/system_state.md
```

Verified:

```bash
.venv/bin/python -m py_compile run_readiness_check.py run_dashboard.py reports/system_state.py run_system_state.py
.venv/bin/python run_readiness_check.py
```

Recommendation checklist after this upgrade:

```text
[ ] Continue moving duplicated report logic into reports/system_state.py where it makes sense.
[ ] Add a lightweight local app shell that reads logs/system_state.json.
[ ] Keep logs/system_state.json as the future UI/API source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 Local App Shell

Added a lightweight dependency-free local app shell.

New files:

```text
app/index.html
app/styles.css
app/app.js
run_app.py
```

Purpose:

```text
Read logs/system_state.json through a local API and show a compact dashboard
for mission-control status, stale-data state, paper progress, setup health,
guardrails, and key report links.
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

API:

```text
http://127.0.0.1:8765/api/system-state
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s -I http://127.0.0.1:8765/
```

Browser/Playwright note:

```text
The in-app Browser tool was not exposed in this session, and Playwright was not
installed, so visual verification was limited to server/API checks.
```

Recommendation checklist after this upgrade:

```text
[ ] Add a small app health panel for recent refresh times.
[ ] Add report detail views inside the app instead of opening raw Markdown.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 App Health Panel

Added app health/freshness timestamps to the app scaffold.

Changed:

```text
reports/system_state.py
run_system_state.py
app/index.html
app/styles.css
app/app.js
logs/system_state.json
logs/system_state.md
```

`logs/system_state.json` now includes:

```text
generated_at_et
app_health.generated_at_et
app_health.source_file_states
```

The local app now has an App Health section showing refresh/modified times for:

```text
system_state.json
dashboard report
scanner CSV
position sizing CSV
setup health CSV
paper log
```

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s http://127.0.0.1:8765/app.js
```

Recommendation checklist after this upgrade:

```text
[ ] Add report detail views inside the app instead of opening raw Markdown.
[ ] Add a manual refresh/run-status workflow for Tuesday's Webull refresh.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 App Report Detail Views

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

The app now has a Report Detail section with tabs for the allowed reports and a
small built-in Markdown renderer. It is read-only and only serves an explicit
allowlist of local reports.

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

Recommendation checklist after this upgrade:

```text
[ ] Add a manual refresh/run-status workflow for Tuesday's Webull refresh.
[ ] Add app-side persistent warning badges for stale data, market closed, and paper gate progress.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Refresh Webull data during the next open market session before acting on scanner rows.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 Refresh Status And App Warning Badges

Added refresh readiness workflow and persistent app warning badges.

New files:

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

The app now has persistent warning badges for:

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

Recommendation checklist after this upgrade:

```text
[ ] Run python run_refresh_status.py before Tuesday's market open.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
[ ] Only import paper trades after current-candle candidates exist.
[ ] Continue keeping logs/system_state.json as the UI source of truth.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 Setup Replay Practice Mode

Added historical setup replay practice mode for off-market training.

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

Replay mode reads:

```text
logs/playbook_approved_trades.csv
```

and generates historical cards with:

```text
symbol and setup
direction
entry / stop / target
exit price and exit reason
R result
quality score
relative volume
practice prompts
```

The local app now includes a Setup Replay section with previous/next controls,
plus a `setup_replay` report tab. Replay mode is strictly process practice and
does not create live or paper signals.

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

Recommendation checklist after this upgrade:

```text
[ ] Use replay mode to review at least one win and one loss before Tuesday's open.
[ ] Add a reveal-outcome mode so entry/stop/target can be reviewed before seeing result.
[ ] Run python run_refresh_status.py before Tuesday's market open.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 Setup Replay Reveal-Outcome Mode

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

Replay cards now start with:

```text
entry / stop / target visible
quality and relative-volume context visible
historical R result and exit details hidden
planning prompts visible before outcome
```

The `Reveal outcome` button displays the historical result, exit details, and
post-outcome review prompts. Moving to another replay card hides the outcome
again. `logs/setup_replay.md` intentionally remains a full historical audit
table and shows outcomes.

Verified:

```bash
.venv/bin/python -m py_compile run_setup_replay.py reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_setup_replay.py
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s http://127.0.0.1:8765/
curl -s http://127.0.0.1:8765/app.js
```

The live local API returned HTTP 200 and served the new replay control and
conceal/reveal logic. A scripted UI behavior check confirmed that a card
starts hidden, reveals on request, and returns to hidden state when moving to
the next card. A visual browser click-through could not be completed because
no in-app browser was attached in this session.

Recommendation checklist after this upgrade:

```text
[ ] Use concealed replay cards to practice at least one win and one loss before Tuesday's open.
[ ] Run python run_refresh_status.py before Tuesday's market open.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
[ ] Only import paper trades after current-candle candidates exist.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 Dashboard Status-Only Action

Added a controlled dashboard button for updating local refresh readiness.

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

The `Update refresh status` button runs only:

```text
python run_refresh_status.py
python run_system_state.py
```

Safety boundary:

```text
does not fetch Webull data
does not import paper trades
does not place orders
does not enable live trading
rejects unimplemented action paths such as /api/actions/refresh-data
```

The app updates its state display and opens the refreshed status report after
the action completes. The server prevents overlapping status-action runs and
gives a clear message if its JSON state file needs regeneration.

Verified:

```bash
.venv/bin/python -m py_compile run_app.py run_refresh_status.py reports/refresh_status.py run_system_state.py
.venv/bin/python run_app.py --port 8766
curl -s -X POST http://127.0.0.1:8766/api/actions/refresh-status
curl -s 'http://127.0.0.1:8766/api/report?name=refresh_status'
curl -s -X POST http://127.0.0.1:8766/api/actions/refresh-data
```

The approved status action returned HTTP 200. The unimplemented data-refresh
action returned HTTP 404. A scripted front-end check confirmed that the button
uses POST and displays the successful no-fetch/no-import message. File
timestamps confirmed `data/paper_trades.csv` and representative Webull candle
CSVs remained unchanged while `logs/refresh_status.json` and
`logs/system_state.json` were rebuilt.

Recommendation checklist after this upgrade:

```text
[ ] Use the dashboard status button before Tuesday's market open to confirm the session plan.
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data from the terminal.
[ ] Keep actual data refresh and paper import outside app buttons until the workflow is validated.
[ ] Only import paper trades after current-candle candidates exist.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 App Current-Candidate Panel

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

The panel reuses existing outputs:

```text
logs/daily_paper_signal_scanner.csv
logs/position_sizing.csv
logs/refresh_status.json
```

It displays current-candle candidates with:

```text
symbol / setup / direction
entry / stop / target
suggested shares and estimated paper risk
scanner and sizing status
quality score
readiness checklist flags and blockers
```

The panel creates no signals, imports no paper rows, and offers no execution
controls. It only displays candidates already present in existing scanner and
sizing outputs.

Current real state:

```text
0 current-candle candidates
0 ready-for-review candidates
```

That is expected because the current saved scanner session is stale/off-market
prep data and a fresh market-hours refresh has not been performed yet.

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_system_state.py
```

An in-memory candidate-state test confirmed that a fresh allowed candidate
joins to `size_ok` position sizing, serializes to JSON, and is marked ready
for review. A scripted front-end check confirmed both the empty current-state
message and a rendered positive-path card with plan prices, estimated risk,
and checklist flags.

Recommendation checklist after this upgrade:

```text
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data from the terminal.
[ ] Inspect the candidate panel only after the scanner status is fresh for today.
[ ] Only import paper trades after current-candle candidates pass review.
[ ] Continue paper validation toward the 30-trade checkpoint.
```

## 2026-05-24 App Paper Progress Visualization

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

Data source:

```text
logs/paper_review_clean_trades.csv
```

The panel shows:

```text
allowed completed trades toward the 30-trade first checkpoint
allowed completed trades toward the 60-trade stronger checkpoint
cumulative forward paper R line chart
allowed versus blocked/watch-only average R summaries
plan-followed versus plan-broken outcome summaries
```

The panel is intentionally based only on completed forward paper results. It
does not blend historical backtest results into the forward-validation view.
With the current empty paper log, the dashboard accurately shows zero gate
progress and an empty cumulative-R chart.

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_system_state.py
```

An in-memory three-trade state check confirmed calculation of cumulative R,
30/60 gate percentages, allowed/watch-only summaries, plan-adherence
summaries, and JSON serialization. A scripted front-end check confirmed both
the empty-state visualization and a populated line chart/summary rendering.

Recommendation checklist after this upgrade:

```text
[ ] During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data from the terminal.
[ ] Log only reviewed current-candle paper candidates and their completed outcomes.
[ ] Use this visualization after completed paper results begin accumulating.
[ ] Continue paper validation toward the 30-trade checkpoint before promoting any strategy changes.
```

## Daily Workflow State-Sync Fix

Fixed the daily paper workflow so its app-ready state snapshot is rebuilt
after all support reports are generated.

Changed:

```text
run_daily_workflow.py
run_position_sizer.py
README.md
```

`run_daily_workflow.py` previously generated `logs/system_state.json` before
the dashboard, recap, and readiness outputs. As a result, the app health panel
could immediately show old report timestamps after a successful workflow run.
The workflow now runs `run_system_state.py` again at the end, after writing
the daily summary.

Also fixed an existing `argparse` startup error in the risk-per-trade help
text in both the daily workflow and position sizer. A literal percent sign in
an argparse help string must be written as `%%`.

Verified:

```bash
.venv/bin/python -m py_compile run_daily_workflow.py run_position_sizer.py reports/system_state.py run_system_state.py run_dashboard.py run_readiness_check.py
.venv/bin/python run_daily_workflow.py --help
.venv/bin/python run_position_sizer.py --help
.venv/bin/python run_daily_workflow.py
```

Latest local state remains prep-only because Sunday, 2026-05-24 is a weekend.
The next session action remains:

```text
During market hours on 2026-05-26, run python run_daily_workflow.py --refresh-data.
```

## Forward Signal Observation Journal

Added append-only evidence tracking for fresh scanner sightings:

```text
run_forward_observations.py
data/forward_signal_observations.csv
logs/forward_signal_observations.md
```

The daily workflow now appends fresh `current_candle` `allowed` and
`blocked_watch_only` observations only while the market is open. It does not
create paper trades or execution actions. Duplicate refreshes are prevented
with:

```text
signal_time_et + symbol + setup + direction
```

The app-ready state and local dashboard report tabs now include forward
observation counts/report access. This is intended to preserve forward
evidence for evaluating `weakness_v1` during paper validation.

Verified:

```bash
.venv/bin/python -m py_compile run_forward_observations.py run_daily_workflow.py run_position_sizer.py reports/system_state.py run_system_state.py run_app.py
.venv/bin/python run_daily_workflow.py
.venv/bin/python run_forward_observations.py --output-dir logs
.venv/bin/python run_system_state.py
curl -s http://127.0.0.1:8765/api/system-state
curl -s 'http://127.0.0.1:8765/api/report?name=observations'
```

An in-memory fresh scanner sample confirmed that allowed and blocked/watch-only
rows map into the new observation schema and that a repeat scan appends no
duplicates. The Sunday, 2026-05-24 offline workflow confirmed stale/off-market
rows append nothing and leave the observation CSV timestamp unchanged.

## 2026-05-24 Pre-Market Reliability Pass

Added the preparation work needed before Tuesday's next regular market
session:

```text
run_premarket_verification.py
tests/test_workflow_safety.py
tests/__init__.py
```

`run_premarket_verification.py` rebuilds local integrity, refresh-status,
system-state, and readiness outputs into one pre-market summary. By default it
does not fetch Webull data. With `--probe-webull`, it performs one explicitly
requested data-only access check.

Fixed `tools/check_webull_data.py` so probe output is saved as:

```text
logs/webull_probe_SYMBOL_TIMEFRAME_candles.csv
```

This prevents a small connection probe from replacing full workflow candle
caches such as `logs/webull_SPY_M5_candles.csv`.

Added automated guardrail tests for:

```text
Memorial Day and next-session calendar behavior
candle integrity complete versus partial sessions
stale signal sizing blocks
forward observation deduplication and reconciliation
disabled execution safety flags
stale-data paper-import blocking
dashboard status-only action commands
pre-market verification calculation and report rendering
```

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q -f run_premarket_verification.py tools/check_webull_data.py run_app.py tests/test_workflow_safety.py
.venv/bin/python run_premarket_verification.py
```

Result:

```text
12 tests passed
12 local candle files checked with 0 integrity warnings
paper import remains blocked pending fresh reviewed current-session candidates
no paper trade, forward observation, or refresh-audit journal rows were added
optional Webull data-only probe passed and saved isolated premarket probe files
```

## 2026-05-25 Dashboard Pre-Market Gate Upgrade

Added the remaining safe app improvements before Tuesday use:

```text
dashboard Pre-Market Gate tile and status badge
local-only Run local pre-market check button
pre-market status summary in logs/system_state.json
pre-market report access in the dashboard
HTML escaping and safe CSS status class handling for dynamic app content
```

The app button runs local derived-report verification only. It does not make a
new Webull request, import paper trades, or alter execution behavior. A prior
successful explicitly requested data-only probe is retained as
`previous_pass`, so running the local check does not erase known probe status.

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q -f reports/system_state.py run_system_state.py run_premarket_verification.py run_app.py tests/test_workflow_safety.py
.venv/bin/python run_premarket_verification.py
POST http://127.0.0.1:8765/api/actions/premarket-check
```

Result:

```text
15 automated tests passed
pre-market dashboard state reports passed / previous_pass
local action returned HTTP 200
no paper trade, forward observation, or refresh-audit journal rows changed
```

## 2026-05-25 Offline Monthly Stability Validation

Strengthened the cached-data research validation without fetching market data
or changing the paper-trade gate.

Changed:

```text
run_holdout_validation.py
run_research_pipeline.py
tests/test_workflow_safety.py
```

`run_holdout_validation.py` now adds calendar-month windows and a monthly
stability summary for each filter. It also explicitly labels the result as an
internal historical stability check, not untouched out-of-sample evidence.
`run_research_pipeline.py` surfaces that caution in the master summary and
rebuilds `logs/system_state.json` after its generated dashboard/report outputs
so the local app snapshot is not stale after an offline pipeline run.

Latest `weakness_v1` monthly stability result from cached approved-playbook
trades:

```text
months with blocked trades: 2
months with improved expectancy: 1
months with lower final R: 1
net final-R delta across affected months: +0.2293R
```

Interpretation:

```text
weakness_v1 still improves the aggregate saved sample, but its improvement is
sparse and mixed month-to-month. Keep it in research/paper validation and
require forward results before trusting it more broadly.
```

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile run_holdout_validation.py run_research_pipeline.py tests/test_workflow_safety.py
.venv/bin/python run_research_pipeline.py --skip-playbook
```

Result:

```text
17 automated tests passed
offline research pipeline completed on cached playbook trades
data/paper_trades.csv, data/forward_signal_observations.csv, and
data/market_refresh_audit.csv remained unchanged
```

## 2026-05-26 Paper Action-Boundary Guardrails

Before regular market hours, closed gaps around declaring or sizing paper
trades from stale or unreviewed scanner rows.

Changed:

```text
run_paper_import.py
run_position_sizer.py
run_daily_scanner.py
run_daily_workflow.py
run_intraday_loop.py
tests/test_workflow_safety.py
README.md
HANDOFF.md
```

Behavior:

```text
Real paper import requires allowed current_candle rows from today's open regular session.
Blocked/watch-only rows remain in the forward observation journal, not the real paper log.
Actionable import and sizing also require current-session Webull refresh-audit evidence.
The daily workflow cannot automatically import a newly discovered candidate.
Position sizing exposes size_ok only for current open-session allowed rows.
Watch-only sizing remains study-only and cannot appear action-eligible.
Daily/monthly paper loss stops now use completed allowed paper outcomes automatically.
The scanner import template is header-only when current-session manual review is unavailable.
Current-session partial M5 data is marked in_progress during regular hours
rather than being falsely reported as an incomplete-session integrity problem.
Refresh status cannot unblock paper import for watch-only-only rows or
unaudited allowed candidates.
```

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile run_paper_import.py run_position_sizer.py run_daily_scanner.py run_daily_workflow.py run_intraday_loop.py tests/test_workflow_safety.py
.venv/bin/python run_daily_workflow.py
```

Result:

```text
24 tests passed
safe pre-open workflow completed with no actionable import template rows
data/paper_trades.csv, data/forward_signal_observations.csv, and
data/market_refresh_audit.csv remained unchanged
```

## 2026-05-26 Post-Close Preparation For May 27

Completed the first market-hours data refresh day and tightened offline
operational guardrails before the next regular session.

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

Behavior:

```text
System state now distinguishes today's completed scanner data from actionable
open-session data and reports outside_market_hours after the close.
The intraday loop exits after the regular session completes instead of waiting
overnight for another scan.
Pre-market verification and replay wording is session-neutral rather than
hard-coded to Tuesday.
The pre-market plan and paper checklist hide candidate and sizing rows unless
they belong to the active open session.
The daily refresh fetches Webull candles once, then reuses those newly saved
CSVs for Setup B evaluation instead of requesting identical data a second time.
```

After-hours Webull market-data refresh result:

```text
May 26 full regular session captured for all approved-symbol M30/M5 CSV pairs
latest M5 regular-session bar: 15:55 ET
candle integrity warnings: 0
current-candle paper candidates: 0
paper trades appended: 0
forward observations appended: 0
paper progress: 0 / 30 allowed completed trades
```

Verified:

```bash
.venv/bin/python -m py_compile reports/system_state.py run_intraday_loop.py run_premarket_verification.py run_setup_replay.py run_premarket_plan.py run_trade_checklist.py run_daily_workflow.py tests/test_workflow_safety.py
.venv/bin/python -m unittest discover -s tests -v
.venv-webull/bin/python run_daily_workflow.py --refresh-data
.venv/bin/python run_premarket_verification.py
.venv/bin/python run_premarket_plan.py --date 2026-05-27
.venv/bin/python run_readiness_check.py --date 2026-05-27
```

Result:

```text
31 automated tests passed, including the single-fetch/reuse workflow guard
pre-market verification passed with prior Webull probe retained
logs/daily_trade_plan.md is dated 2026-05-27
paper import remains blocked until a reviewed May 27 current-candle candidate exists
live trading and broker execution remain disabled
```

## 2026-05-26 Exploratory Universe Expansion

Resumed broad-symbol research without changing the approved paper-validation
universe. New ticker data and reports were isolated under:

```text
logs/universe_expansion/
```

First-pass symbols:

```text
IWM DIA AMZN GOOGL AVGO NFLX COIN PLTR
```

`SPY` was fetched in the isolated folder only as the reference for
market-confirmed long variants. First-pass leads were then expanded to two
M30 pages and six M5 pages for deeper testing.

Deeper long-side results:

```text
AMZN: research-qualified, market_confirmed + no_vwap_exit, 11 trades, +0.1937R expectancy, 2.3218 PF
COIN: research-qualified but weak, current + no_vwap_exit, 12 trades, +0.0212R expectancy, 1.0888 PF
NFLX: watch_more, market_confirmed + no_vwap_exit, 2 trades, +0.6996R expectancy
DIA: reject for Setup A long
IWM: reject for Setup A long
```

Deeper short-side results:

```text
NFLX: research-qualified, setup_b_short + no_vwap_exit, 14 trades, +0.6258R expectancy, 10.6169 PF
DIA: research-qualified, setup_b_short + no_vwap_exit, 16 trades, +0.1682R expectancy, 1.7211 PF
IWM: research-qualified, setup_b_short + no_vwap_exit, 12 trades, +0.0723R expectancy, 1.3858 PF
COIN: reject for Setup B short
AMZN: reject for Setup B short
```

Important boundary:

```text
These are exploratory research candidates only.
They were not added to config/symbol_playbook.py or the daily paper workflow.
Validate their portfolio impact and stability before any playbook promotion.
```

Fixed a candidate-selection defect in `run_webull_watchlist.py`: a passing
candidate with at least the minimum trade count is now preferred over a
higher-expectancy passing candidate that is still under-sampled. `COIN`
demonstrated this case. Added a regression test.

Verified:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
32 automated tests passed
```

## 2026-05-26 Main-Page Trading Workspace

Added a prominent read-only trading interface directly to the dashboard main
page rather than embedding a broker trading webpage.

Changed:

```text
run_app.py
app/index.html
app/styles.css
app/app.js
tests/test_workflow_safety.py
README.md
HANDOFF.md
PROJECT_MEMORY.md
```

Behavior:

```text
The main page now has a Trading Workspace panel.
It shows an approved-playbook watchlist, 5m/30m candlestick chart, VWAP,
EMA 9, EMA 21, EMA 200, opening-range overlays, and a paper-review ticket.
The chart API reads the saved Webull candle CSVs already used by the scanner.
The ticket is filled only from current scanner candidate state.
Exploratory research symbols are excluded until promoted into the playbook.
Orders remain disabled and no Webull trading API calls were added.
```

Reason for implementation choice:

```text
Webull OpenAPI documents market-data and trading endpoints, but no official
embeddable Webull trading-interface widget was identified. A native
read-only chart keeps signal review aligned with the same candle data used by
the strategy while preserving the paper-validation boundary.
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

## 2026-05-26 Investment Narrative Dashboard Panel

Added a read-only long-term research panel directly below the Trading
Workspace. It follows the selected approved chart symbol and presents
ticker-specific thesis focus, monitoring themes, and review questions.

Current source behavior:

```text
No live news or X source is connected yet.
The panel states that clearly instead of presenting prompts as live summaries.
Future headline and X public-post summaries have a dedicated UI/API boundary.
Narrative context is excluded from strategy scoring, entries, exits,
position sizing, and paper-trade eligibility.
```

Implementation:

```text
config/investment_narratives.py contains long-horizon review prompts.
run_app.py serves /api/investment-narrative?symbol=SPY.
app/index.html and app/app.js add the selected-symbol narrative panel.
app/styles.css includes the Fragment blue/white/black theme and matching panel.
tests/test_workflow_safety.py checks the narrative safety boundary.
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

## 2026-05-26 Setup Readiness Radar And Signal Markers

Added an explanation layer inside the main-page Trading Workspace to make
paper-session review more useful without adding trade decisions.

Behavior:

```text
The chart now displays markers for stored-session scanner signals.
The Setup Readiness Radar follows the selected approved chart symbol.
Each approved setup shows passed conditions, missing conditions, quality,
relative volume, room-to-target R, and whether a signal triggered earlier.
The radar is explanation only and does not generate signals, approve paper
trades, change position sizing, or alter any strategy rule.
```

Implementation:

```text
run_daily_scanner.py now writes structured passed/missing condition fields.
run_app.py serves /api/setup-readiness?symbol=SPY from saved scanner output.
app/index.html, app/app.js, and app/styles.css add radar cards and SVG markers.
logs/daily_paper_signal_scanner.csv was regenerated from existing saved candle
data only so the dashboard can display structured checks immediately.
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py run_daily_scanner.py config/investment_narratives.py tests/test_workflow_safety.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
38 automated tests passed
```

## 2026-05-26 Near-Miss Analytics

Added a research-only panel and workflow collector for setups that are close
to ready but still missing scanner requirements.

Behavior:

```text
The main page now shows Near-Miss Analytics below the Trading Workspace.
It displays frequent missing conditions and ranks the closest latest setups.
During future fresh open-market workflow scans, missing-condition rows append
to data/near_miss_observations.csv with deduplication by candle/setup/blocker.
Outside a fresh open-market scan, no observation rows are appended; the panel
clearly labels its data as Latest Saved Scanner Snapshot.
Near-miss data cannot change signal eligibility or paper decisions.
```

Current saved-session snapshot:

```text
37 latest-snapshot blocker occurrences.
Most frequent blocker: inside entry window (7 occurrences).
Closest non-ready setups: QQQ Setup A Long (9/13) and TSLA Setup A Long (8/10).
0 open-session near-miss observation rows were appended after close.
```

Implementation:

```text
run_near_miss_analytics.py collects and summarizes missing scanner conditions.
run_daily_workflow.py runs the collector after the scanner on future cycles.
run_app.py serves /api/near-miss-analytics and the report endpoint.
app/index.html, app/app.js, and app/styles.css render the analytics panel.
reports/system_state.py exposes the report/journal file health.
logs/near_miss_analytics.md contains the current snapshot report.
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
No after-close near-miss evidence was appended.
```

## 2026-05-26 Chart Outcome Replay Upgrade

Added a saved-candle chart to Setup Replay without changing signal, sizing, or
execution behavior.

Behavior:

```text
Before reveal, each replay shows its planned entry, stop, target, indicators,
and entry marker on a 30-minute chart ending at the historical entry candle.
Future historical price bars are excluded from the concealed API response.
After Reveal outcome, the chart shows the exit path and an exit marker.
Revealed cards prefer 5-minute exit-management candles when stored coverage
exists; earlier cards fall back to 30-minute historical context.
```

Implementation:

```text
run_app.py serves /api/replay-chart from the saved setup_replay.json cards and
local Webull candle CSV files only.
app/index.html, app/app.js, and app/styles.css render the replay chart,
indicator legend, plan-level lines, and entry/exit markers.
tests/test_workflow_safety.py checks that concealed bars stop at entry and that
revealed charts use the 30-minute fallback if the 5-minute session is absent.
```

Verified:

```bash
.venv/bin/python -m py_compile run_app.py tests/test_workflow_safety.py run_setup_replay.py reports/system_state.py
.venv/bin/python -m unittest discover -s tests -v
```

Result:

```text
42 automated tests passed.
All 20 saved replay cards build chart payloads successfully.
15 recent revealed cards use M5 outcome charts; 5 older cards use M30 fallback.
A live local API smoke test confirmed hidden bars stop at entry and revealed
bars include the exit marker.
The in-app browser surface was unavailable in this session, so visual
click-through remains to be performed when a browser surface is attached.
```

## 2026-05-26 Replay Decision Journal

Added process-decision recording to the chart replay workflow.

Behavior:

```text
Each replay now requires a Take, Skip, or Watch decision before its historical
outcome can be revealed in the local app.
After reveal, the selected decision is locked so the result cannot influence a
rewritten pre-outcome choice.
Each card supports optional practice notes.
The Replay section shows counts for decided, take, skip, watch, and reviewed
historical cards.
```

Storage and safety:

```text
Practice decisions and notes use browser-local storage only.
They do not write to paper-trade logs, scanner output, forward evidence,
strategy rules, position sizing, or execution paths.
Refreshing or revisiting the app preserves the journal in the same browser.
Reopening a reviewed card still starts with the historical outcome concealed.
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
The in-app browser surface was unavailable in this session, so a rendered
take/skip/watch, reveal, and note-persistence click-through remains to verify.
```

## 2026-05-27 Candle-By-Candle Replay Management

Added sequential management practice after the replay decision journal.

Behavior:

```text
After a Take, Skip, or Watch decision, Start management opens the stored
exit-management chart without disclosing the historical result.
Hold / Next candle exposes exactly one additional stored management candle.
The current displayed bar supplies marked price and unrealized R for practice.
Exit here records the visible marked-price practice exit.
Stop followed is enabled only when the visible candle reaches the planned stop.
Compare with historical outcome stays disabled until a practice exit is
recorded or the historical exit candle has actually been reached.
```

Concealment:

```text
The replay API now accepts a bounded step parameter.
It releases only candles through that step.
It does not return the total hidden management-candle count until the final
candle is reached, avoiding a hidden trade-duration clue.
The historical exit marker and recorded R remain absent until comparison.
```

Storage and safety:

```text
Management actions and practice exits remain browser-local journal data only.
They cannot change strategy rules, current signals, paper evidence, sizing, or
broker execution.
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
JavaScript syntax parsing succeeded in the available restricted runtime.
An actual SPY replay payload confirmed entry-only view, incremental M5 release,
and no disclosed step total until its final saved management candle.
A live local endpoint smoke test confirmed the historical exit marker is
returned only by the final comparison response.
```

## 2026-05-27 Replay Scoring Dashboard

Added training feedback summaries for the browser-local replay journal.

Behavior:

```text
The Replay Scoring Dashboard includes historical cards only after the user has
selected Compare with historical outcome.
It shows reviewed completion, average historical outcome behind Take choices,
the number of losing historical setups avoided by Skip or Watch decisions, and
average practice-exit R difference versus the saved strategy exit.
It provides reviewed breakdowns by Take / Skip / Watch and by setup / quality
grade, plus the latest practice-exit comparisons.
```

Concealment and safety:

```text
Uncompared historical outcomes are excluded from all scoreboard calculations.
The score dashboard reads browser-local replay journal entries and already
revealed historical cards only.
It is training feedback, not forward-validation evidence, and cannot change
scanner eligibility, paper evidence, sizing, strategy logic, or execution.
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
JavaScript syntax parsing succeeded in the available restricted runtime.
A replay endpoint smoke check confirmed entry/step responses still conceal the
historical exit marker while comparison returns it.
The in-app browser surface was unavailable, so visual scoreboard interaction
remains to be checked when the dashboard browser is attached.
```

## 2026-05-27 Replay Filters And Session Presets

Added focused practice-session controls above the replay journal and scoring
dashboard.

Behavior:

```text
Safe pre-comparison filters organize saved cards by symbol, setup, and quality
grade.
Unreviewed Only builds a queue from browser-local comparison status.
Reviewed Losses, Reviewed Stop-Losses, and Reviewed VWAP Exits create targeted
review queues from compared historical cards only.
All Cards, A-Grade Setups, and Setup B Shorts are provided as quick presets.
Previous and Next now navigate the active filtered practice queue.
Journal and scoring totals continue to summarize the complete saved replay set.
```

Concealment and safety:

```text
Result and exit-reason filters do not evaluate or list uncompared card
outcomes. Available exit-reason choices are derived only from compared cards,
apart from named reviewed-only preset labels.
Filtered replay practice remains browser-local training only and cannot affect
forward evidence, paper trades, strategy rules, sizing, or execution.
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
JavaScript syntax parsing succeeded in the available restricted runtime.
The in-app browser surface was unavailable for rendered filter interaction
testing in this session.
```

## 2026-05-27 Autonomous Paper Supervisor Foundation

Added a safe local supervisor for the future always-on research workflow:

```text
run_autonomous_paper_workflow.py
logs/autonomous_paper_workflow_status.md
```

Purpose:

```text
Choose the next paper-validation action from the local NYSE calendar.
Run pre-market verification before the open.
Run market-hours Webull refresh, scanner, sizing, dashboard, and support reports.
Run after-close recap, readiness, and system-state reports.
Wait when no action is due.
```

Safety boundary:

```text
The supervisor is research and paper-validation only.
It does not place orders, create broker alerts, import reviewed paper trades,
or connect to broker execution.
The market-hours command intentionally does not pass --append-current-signals.
```

Main commands:

```bash
.venv/bin/python run_autonomous_paper_workflow.py --once --dry-run
source .venv-webull/bin/activate
python run_autonomous_paper_workflow.py --interval-minutes 5
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
Dry-run selected market_scan during the open session.
47 workflow safety tests passed.
```

## 2026-05-27 macOS Auto-Start Installed

Installed the local macOS LaunchAgent for the autonomous paper supervisor:

```text
launchd/com.project-gwala.autonomous-paper.plist
/Users/roy/Library/LaunchAgents/com.project-gwala.autonomous-paper.plist
scripts/install_autonomous_launch_agent.sh
scripts/uninstall_autonomous_launch_agent.sh
```

Schedule:

```text
RunAtLoad = true
Weekdays at 6:15 AM local time
Supervisor interval = 5 minutes during regular market hours
```

Install/load command used:

```bash
bash scripts/install_autonomous_launch_agent.sh
```

Status check:

```bash
launchctl print gui/$UID/com.project-gwala.autonomous-paper
```

Uninstall command:

```bash
bash scripts/uninstall_autonomous_launch_agent.sh
```

Launch logs:

```text
logs/autonomous_paper_workflow.launchd.out.log
logs/autonomous_paper_workflow.launchd.err.log
```

Result:

```text
LaunchAgent installed and loaded.
launchctl reported state = running.
RunAtLoad started a live market_scan during the open session.
The supervisor status showed Dry Run = False.
The error log was empty at install-time check.
```

Important limitation:

```text
A user LaunchAgent runs only while the Mac is powered on and the user account
is logged in. If the Mac is asleep, powered off, or logged out, macOS cannot
run this user-level workflow until the machine wakes and allows user agents.
```

## 2026-05-27 Dashboard Auto-Start Installed

Installed and loaded a separate macOS LaunchAgent for the local dashboard:

```text
launchd/com.project-gwala.dashboard.plist
/Users/roy/Library/LaunchAgents/com.project-gwala.dashboard.plist
scripts/install_dashboard_launch_agent.sh
scripts/uninstall_dashboard_launch_agent.sh
```

Behavior:

```text
RunAtLoad = true
KeepAlive = true
Serves http://127.0.0.1:8765 with run_app.py
Uses .venv/bin/python
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

Result:

```text
LaunchAgent installed and loaded.
launchctl reported state = running.
The dashboard was opened in the regular macOS browser.
The in-app browser surface was unavailable in this session.
```

## 2026-05-27 Dashboard Desktop App Wrapper

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
The actual dashboard server still runs through the dashboard LaunchAgent.
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

## 2026-05-27 Local Paper Execution Simulator

Added the first runnable paper-execution script, deliberately local-only:

```text
execution/paper_trader.py
run_paper_execution_simulator.py
logs/local_paper_execution_simulator.md
data/paper_orders.csv
data/paper_trades.csv
```

Purpose:

```text
Convert eligible `logs/position_sizing.csv` rows into local paper order tickets.
Append open rows to `data/paper_trades.csv` only when explicitly confirmed.
Keep order lifecycle practice separate from Webull broker order endpoints.
```

Safety:

```text
Default mode is preview only.
Writing requires --confirm-local-paper.
Only sizing_status=size_ok, scanner_status=allowed, signal_freshness=current_candle rows are eligible.
No Webull order endpoints are called.
No Webull paper orders are placed.
No broker alerts or live execution are created.
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

## 2026-05-27 Paper Session Cycle Added

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

## 2026-05-27 Paper Session Dashboard Buttons Added

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

## 2026-05-27 Open Paper Trade Monitor Added

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

## 2026-05-27 Candidate Alerts Added

Added a candidate alert/readiness layer:

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

## 2026-05-27 Paper Execution Preview Integrated

Integrated the local paper execution simulator into the regular daily workflow:

```text
run_daily_workflow.py now runs run_paper_execution_simulator.py after position sizing.
run_app.py allows the paper_execution report endpoint.
app/app.js shows a Paper Execution report tab.
APP_MANUAL.md and README.md document the new report.
```

Behavior:

```text
Every future daily/autonomous market scan builds logs/local_paper_execution_simulator.md.
The workflow remains preview-only and does not write local paper orders unless run manually with --confirm-local-paper.
The dashboard can show the Paper Execution report.
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

Added research-only shadow sample collection so near-miss setups can be tracked
without counting as official paper trades.

Files:

```text
run_shadow_samples.py
data/shadow_samples.csv
logs/shadow_sample_outcomes.csv
logs/shadow_samples.md
```

Integrated:

```text
run_daily_workflow.py runs shadow samples after no-trade analysis.
run_paper_session_cycle.py includes Shadow samples in preview/confirm cycles.
run_app.py exposes shadow_samples.
app/app.js shows Reports -> Paper Review -> Shadow Samples.
README.md and APP_MANUAL.md document the feature.
```

Rules:

```text
official_candidate rows are excluded from shadow samples
one_rule_miss = one missing scanner rule and at least 80% checks passed
close_watch_shadow = one or two missing scanner rules and at least 75% checks passed
shadow samples do not count toward the 30/60 official paper-trade gates
shadow samples do not place orders
```

Latest run:

```bash
.venv/bin/python run_shadow_samples.py --record-latest-snapshot
```

Latest result:

```text
Append status: appended_new_shadow_samples
Latest shadow candidates: 2
New shadow samples appended: 2
Matured shadow outcomes: 0
SPY Setup A Long: one_rule_miss, missing above opening range high, 8/9 checks passed.
TSLA Setup B Short: close_watch_shadow, missing price below 200 EMA and 1H bearish thesis, 7/9 checks passed.
Outcome grading is awaiting complete regular-session 5m candle data.
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

Added a single proof-trail report that combines official paper progress,
forward observations, shadow samples, and the current sample queue.

Files:

```text
run_forward_evidence.py
logs/forward_evidence.md
```

Integrated:

```text
run_daily_workflow.py runs run_forward_evidence.py after checkpoint reporting.
run_paper_session_cycle.py includes Forward evidence after Shadow samples.
run_app.py exposes forward_evidence.
app/app.js shows Reports -> Paper Review -> Forward Evidence.
README.md and APP_MANUAL.md document the report.
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
Next action: keep collecting official paper trades and shadow samples until evidence reaches the first gate.
```

Guardrail:

```text
Shadow samples do not count toward official paper gates.
Only completed allowed paper trades count toward the 30/60 gates.
No broker orders, Webull paper orders, or live execution are created.
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

Fixed the candle completeness gap where Webull M5 files ending at 15:50 ET
were treated as incomplete even when that was the provider's final returned
bar for a regular 16:00 ET close.

Changed:

```text
run_data_integrity.py now distinguishes:
- complete = full configured 15:55 ET force-exit bar exists
- provider_final_bar = provider returned 15:50 ET as final available M5 bar
- partial_session = truly too early/incomplete

run_forward_observation_review.py accepts complete and provider_final_bar for
closed-session outcome grading.

run_shadow_samples.py now benefits through the shared observation review
coverage check.

reports/system_state.py and run_premarket_verification.py no longer count
provider_final_bar as an integrity issue.

run_refresh_audit.py records files_present_provider_final_bar when appropriate.
```

Latest result:

```text
Candle integrity warnings: 0
M5 files for 2026-05-29 show provider_final_bar at 15:50 ET.
Shadow samples matured: 2 / 2
SPY Setup A Long shadow outcome: -0.1228R, last_available_exit at 15:50 ET.
TSLA Setup B Short shadow outcome: -1.0R, stop_loss_5m.
Forward evidence shadow average: -0.5614R.
System state integrity_issue_count: 0.
```

Interpretation:

```text
The final-bar gap is fixed/clarified.
The first two shadow samples are evidence against instantly relaxing those
rules, especially TSLA Setup B Short.
Continue collecting official paper trades and shadow samples during live
market sessions; do not promote opening-range relaxation yet.
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

Added candidate aging so Gwala can see whether signals are appearing too late
in the session to have room to work.

Files:

```text
run_candidate_aging.py
logs/candidate_aging.csv
logs/candidate_aging.md
```

Integrated:

```text
run_daily_workflow.py runs run_candidate_aging.py before forward evidence.
run_paper_session_cycle.py includes Candidate aging before Forward evidence.
run_forward_evidence.py includes a compact Candidate Aging section.
run_app.py exposes candidate_aging.
app/app.js shows Reports -> Paper Review -> Candidate Aging.
README.md and APP_MANUAL.md document the report.
```

Buckets:

```text
opening_hour = 09:30 to 10:29 ET
midday = 10:30 to 12:29 ET
afternoon = 12:30 to 14:29 ET
late_day = 14:30 ET or later
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
Forward Evidence aging status: late_day_caution.
```

Interpretation:

```text
Do not loosen rules for late-day candidates yet.
Watch Monday live scans for earlier-session candidates.
If most valid candidates continue to arrive after 14:30 ET, consider a late-day
filter/caution gate after more evidence is collected.
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

## 2026-05-28 Deep Research Expansion And CSV Import Lane

Completed a deeper research pass while staying in research/backtesting mode:

```text
Broad universe: 40 liquid optionable symbols.
Broad data depth: 4 pages of 30m entry candles and 12 pages of 5m exit candles.
Focused data depth: selected candidates with 6 pages of 30m candles and 18 pages of 5m candles.
Reports: logs/universe_expansion and logs/deeper_research.
```

Key focused-pass read:

```text
WMT market-confirmed long remained constructive over 33 trades.
TSLA and AAPL were positive only in market-confirmed baseline form.
NFLX and UNH looked promising but still need more sample.
CRM Setup B short held up better than many earlier leads.
AMD, DIS, QQQ, NVDA, DIA, and AMZN weakened or stayed noisy after deeper history.
```

Added:

```text
run_import_candles_csv.py
```

This imports provider-exported candle CSVs into the same
`webull_SYMBOL_TIMEFRAME_candles.csv` cache format used by
`run_webull_watchlist.py --reuse-csv`.

## 2026-05-29 Controlled Variants And Walk-Forward Review

Added research-only comparison reports:

```text
run_controlled_variant_review.py
run_walk_forward_review.py
```

Also corrected `run_research_confidence.py` and `run_promotion_review.py` so
quality variants use their intended elite/quality trade metrics and logs
instead of baseline metrics.

Current deep-report read:

```text
Controlled variants: market confirmation improves AAPL, TSLA, and NFLX in the focused deeper folder.
Quality filters are often too selective or weaker; do not assume stricter means better.
Walk-forward: DIA Setup B Short, TSLA market-confirmed long, AMD Setup B Short, WMT current long, UNH current long, CRM Setup B Short, and NFLX market-confirmed long were holding up in newer halves.
Some rows are still needs_more_sample; keep them in research/paper-watch review, not live trading.
```

## 2026-05-29 Regime Review

Added:

```text
run_regime_review.py
```

This labels candidate trade logs by SPY M30 market regime at entry:

```text
bullish
bearish
choppy
high_volatility
normal_volatility
low_volatility
```

It writes:

```text
logs/regime_review.md
logs/deeper_research/regime_review.md
```

The app Reports tab now includes Regime Review and Deep Regime.

## 2026-05-31 Battery-Friendly Autonomous Schedule

Changed the autonomous paper workflow from an all-day supervisor into short
scheduled macOS LaunchAgent runs so the laptop does less background work.

Added:

```text
tools/build_autonomous_launchd_plist.py
```

This regenerates:

```text
launchd/com.project-gwala.autonomous-paper.plist
```

Current schedule, using local Pacific time:

```text
Weekdays 6:15 AM = pre-market check
Weekdays 6:30 AM through 1:00 PM = one short workflow run every 5 minutes
Weekdays 1:05 PM = after-close recap
```

Important behavior:

```text
The LaunchAgent now passes --once to run_autonomous_paper_workflow.py.
RunAtLoad is disabled.
Each scheduled invocation starts, checks market/workflow state, acts if needed,
then exits instead of staying alive all day.
```

Installed and loaded:

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
405 calendar entries generated.
Plist lint passed.
87 workflow safety tests passed.
LaunchAgent installed, loaded, and configured with --once.
```

Laptop note:

```text
The Mac still must be awake and the user account available during the market
window. It no longer needs to keep a long-running paper workflow open overnight
or all day outside market hours.
```

## 2026-05-31 Morning Run Watchdog Added

Added a status-only watchdog so the dashboard can clearly answer whether the
scheduled morning workflow actually ran.

Added:

```text
run_morning_watchdog.py
logs/morning_run_watchdog.json
logs/morning_run_watchdog.md
```

Updated:

```text
run_autonomous_paper_workflow.py now writes autonomous_paper_workflow_status.json.
run_daily_workflow.py runs the morning watchdog near the end of the workflow.
reports/system_state.py includes morning_watchdog in system_state.json.
run_app.py allows the Morning Watchdog report.
app/app.js shows Morning Watchdog in Reports and uses it on the Home automation card.
README.md and APP_MANUAL.md document the watchdog.
```

The watchdog reports:

```text
autonomous status wrote today
market scan due
market scan ran today
Webull refresh confirmed today
scanner session is today
current/reviewable/allowed candidate counts
next action
```

Current generated state before the first scheduled scan:

```text
Morning watchdog status: pending
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
Watchdog is status-only and does not place orders, create broker alerts, or import paper trades.
```

## 2026-05-31 Post-Scan Candidate Digest Added

Added a compact post-scan digest that turns the latest scanner/sample evidence
into one plain-English action.

Added:

```text
run_post_scan_digest.py
logs/post_scan_digest.json
logs/post_scan_digest.md
```

Integrated:

```text
run_daily_workflow.py runs run_post_scan_digest.py after forward_sample_queue and no_trade_analysis.
reports/system_state.py exposes post_scan_digest in system_state.json.
run_app.py serves Reports -> Paper Review -> Post-Scan Digest.
app/app.js adds Post-Scan Digest to Reports and uses it on the Home candidate/action card.
README.md and APP_MANUAL.md document the digest.
```

Possible actions:

```text
review_candidate = manual checklist needed
watch_almost_ready = close setup, wait for next scan
study_blocker = no trade, but blocker pattern is worth reviewing
wait = nothing to do
data_issue = refresh/staleness problem first
```

Current saved digest from stale 2026-05-29 scanner:

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
Digest is status-only. It does not import paper trades, place broker orders, create broker alerts, or change scanner rules.
```

## 2026-05-31 Daily Automation Timeline Added

Added a compact timeline report so the autonomous workflow is diagnosable
without reading raw LaunchAgent logs.

Added:

```text
run_daily_automation_timeline.py
logs/daily_automation_timeline.json
logs/daily_automation_timeline.md
```

Integrated:

```text
run_autonomous_paper_workflow.py runs timeline after scheduled actions.
run_daily_workflow.py runs timeline near the end of the daily workflow.
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

Current saved timeline:

```text
pending: Automation is not due yet or the first scan has not finished.
No recent possible failures.
autonomous_status_json is missing because the last status Markdown was written before the JSON status upgrade; future scheduled runs will write it.
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
Timeline is status-only. It does not fetch data, place orders, create broker alerts, import paper trades, or change scanner rules.
```

## 2026-06-17 Gwala Paper Collection Mode

Effective immediately, the project is in Paper Collection Mode for the next 10
market sessions.

Primary KPI:

```text
Completed Official Paper Trades
```

Allowed work:

```text
Candidate capture
Candidate review
Contract review
Paper trade logging
Exit management
Safety-critical bug fixes
```

Disallowed work:

```text
New strategies
New indicators
New dashboard features
New research systems
New routing logic
New filters
New data providers
New architecture projects
```

Exception:

```text
Only allow a disallowed-category change if it directly increases completed
official paper trades or fixes a blocker preventing official paper trades.
```

Next safest action:

```text
Run the current paper workflow during each market session, review valid A/B
candidates, complete contract review, log official paper trades, and manage
exits. Do not expand the system unless a direct official-paper-trade blocker is
found.
```
