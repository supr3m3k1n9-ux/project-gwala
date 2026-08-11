# Market Session Readiness

Generated: 2026-06-17

Purpose: make the next regular market session operationally ready for Project
Gwala paper validation. This is research and manual paper-validation only. It
does not place broker orders, create broker alerts, enable live execution, or
move real money.

## 1. Before Market Open

Run this from the project root:

```bash
cd "/Users/roy/Documents/New project"
.venv-webull/bin/python run_premarket_verification.py --output-dir logs --probe-webull --webull-python .venv-webull/bin/python
```

Pass condition:

- `logs/premarket_verification.md` has no failed checks.
- Webull credentials are detected.
- Webull data-only probe passes or has a previous pass.
- Safety flags show live trading, broker execution, and real-money readiness
  are disabled.
- Paper import remains blocked until a fresh reviewed candidate exists.

## 2. During Market Hours

Run this at the open and then every 5 minutes during regular market hours if
the LaunchAgent is not already handling scheduled scans:

```bash
cd "/Users/roy/Documents/New project"
.venv-webull/bin/python run_current_candle_capture.py --output-dir logs --pause 5 --account-size 10000 --risk-per-trade-pct 0.005
```

This command refreshes Webull market data, scans the approved/watch universe,
builds A/current and B/grace candidates, runs sizing, router, pre-entry review,
Paper Gate v2, Options Contract Gate, validation import preview, ship report,
sync checks, and final system state.

If you want to check whether the scheduled runner is loaded:

```bash
launchctl list | grep com.project-gwala.autonomous-paper
```

## 3. Reports To Monitor

Primary reports:

| Report | What to watch |
| --- | --- |
| `logs/current_candle_capture.md` | Fastest session view. Look at scanner current-candle allowed, B-tier grace allowed, Paper Gate ready, and first bottleneck. |
| `logs/DAILY_SHIP_REPORT.md` | Ship-mode funnel. Shows scanner signals through completed official paper trades and remaining trades to 30. |
| `logs/paper_gate_v2.md` | A/B/C validation classification. This is where A-tier and B-tier ready samples appear. |
| `logs/options_contract_gate.md` | Contract review status. Must pass before validation import. |
| `logs/options_contract_gate_template.csv` | Template to fill into `data/options_contract_audit.csv` when a candidate needs contract review. |
| `logs/paper_validation_sample_import.md` | Preview/confirmed import summary for official validation samples. |
| `logs/system_state.md` | App-facing state after reports are rebuilt. |
| `logs/data_flow_sentinel.md` | Sync and wiring checks. Failed checks must be fixed before trusting the dashboard. |
| `logs/dashboard_data_preflight.md` | Dashboard data availability and freshness checks. |
| `logs/filter_rejection_summary.csv` | Rejection counts by filter. Useful if candidates disappear unexpectedly. |

Dashboard pages:

- Home: current command center, data freshness, current bottleneck.
- Paper Progress: official validation sample count, remaining to 30, outcomes.

## 4. How To Know An A-Tier Candidate Appears

An A-tier candidate exists when either of these is true:

- `logs/current_candle_capture.json` has `scanner_current_allowed > 0`.
- `logs/paper_gate_v2.json` has `a_tier_ready > 0`.

Confirm the row in `logs/paper_gate_v2.md`:

- `sample_tier` = `A`
- `signal_freshness` = `current_candle`
- `validation_lane` = `A`
- `sample_status` = `ready_for_validation_sample`
- `manual_review_required` = `True`

A-tier can receive a local A/current paper-entry packet, but it still does not
place broker orders.

## 5. How To Know A B-Tier Candidate Appears

A B-tier grace candidate exists when either of these is true:

- `logs/current_candle_capture.json` has `scanner_grace_allowed > 0`.
- `logs/paper_gate_v2.json` has `b_tier_ready > 0`.

Confirm the row in `logs/paper_gate_v2.md`:

- `sample_tier` = `B`
- `signal_freshness` = `grace_candle`
- `validation_lane` = `B`
- `sample_status` = `ready_for_validation_sample`
- `manual_review_required` = `True`
- `source_signal_et` is the prior M30 signal candle
- `candidate_entry_et` is the refreshed current candle
- `fresh_plan_source` = `latest_grace_candle`

B-tier must not receive auto-entry, broker orders, or local paper-entry packet
commands. It can only move forward through manual review, Options Contract Gate,
and validation sample import.

## 6. Turn A Candidate Into An Official Validation Sample

Use this sequence only after a Paper Gate v2 A/B candidate appears.

1. Manually review the chart.

   Confirm symbol, setup, direction, entry, stop, target, risk, current price,
   and sizing still make sense. For B-tier, confirm it is exactly one M30
   candle late and uses the refreshed current-candle plan.

2. Review the generated contract template.

   Open:

   ```text
   logs/options_contract_gate_template.csv
   ```

3. Enter the selected contract into:

   ```text
   data/options_contract_audit.csv
   ```

   Required contract fields include contract symbol, option type, expiration,
   DTE, strike, delta, bid, ask, mid, spread, volume, open interest, implied
   volatility, premium, earnings flag, and notes.

4. Rerun Options Contract Gate:

   ```bash
   cd "/Users/roy/Documents/New project"
   .venv-webull/bin/python run_options_contract_gate.py --output-dir logs --account-size 10000
   ```

5. If the contract passes, preview validation import:

   ```bash
   cd "/Users/roy/Documents/New project"
   .venv-webull/bin/python run_paper_validation_sample_import.py --output-dir logs
   ```

6. If the preview is correct, explicitly confirm the sample import:

   ```bash
   cd "/Users/roy/Documents/New project"
   .venv-webull/bin/python run_paper_validation_sample_import.py --output-dir logs --confirm-samples
   ```

7. Rebuild the ship/state reports:

   ```bash
   cd "/Users/roy/Documents/New project"
   .venv-webull/bin/python run_daily_ship_report.py --output-dir logs
   .venv-webull/bin/python run_system_state.py --output-dir logs
   ```

The row is an official validation sample after it is appended to:

```text
data/paper_validation_samples.csv
```

It becomes a completed official paper trade only after the outcome fields are
recorded, especially `outcome_r`, `followed_plan`, and `exit_reason`.

## 7. What Can Still Block An Official Paper Trade

Common blockers:

- No A/current or B/one-M30 grace candidate appears.
- Candidate is `earlier_today`; that remains study/shadow only.
- Market is closed or outside regular session.
- Webull candles are stale or data refresh fails.
- Data Flow Sentinel or dashboard preflight fails.
- Position sizing rejects the row because risk is too wide or risk guard is hit.
- Market Regime Router blocks the row or routes it to shadow-only.
- Pre-entry review blocks it.
- Paper Gate v2 classifies it as C/study-only.
- B-tier duplicates an A-window candidate and is downgraded.
- Contract review is missing.
- Contract fails Options Contract Gate because of delta, spread, volume, open
  interest, DTE, premium, or earnings/event risk.
- Validation import is only previewed, not confirmed.
- The sample is imported but outcome fields are never completed.

Safety blockers that must stay strict:

- No broker orders.
- No live execution.
- No real-money trading.
- No auto-entry for B-tier.
- No paper sample without manual review and contract gate pass.

## 8. End-Of-Day Metrics To Record

After the close, run:

```bash
cd "/Users/roy/Documents/New project"
.venv-webull/bin/python run_after_close_evidence_maturity.py --output-dir logs
.venv-webull/bin/python run_daily_recap.py --output-dir logs
.venv-webull/bin/python run_readiness_check.py --output-dir logs
.venv-webull/bin/python run_daily_ship_report.py --output-dir logs
.venv-webull/bin/python run_system_state.py --output-dir logs
```

Record these metrics:

| Metric | Source |
| --- | --- |
| Scanner rows | `logs/DAILY_SHIP_REPORT.md` |
| Allowed signals | `logs/DAILY_SHIP_REPORT.md` |
| A/B paper-validation allowed rows | `logs/DAILY_SHIP_REPORT.md` |
| A-tier ready count | `logs/paper_gate_v2.md` |
| B-tier ready count | `logs/paper_gate_v2.md` |
| Contract-passed rows | `logs/options_contract_gate.md` |
| Validation-imported rows | `logs/paper_validation_sample_import.md` |
| Official validation samples | `logs/DAILY_SHIP_REPORT.md` |
| Completed official paper trades | `logs/DAILY_SHIP_REPORT.md` |
| Remaining trades to 30 | `logs/DAILY_SHIP_REPORT.md` |
| Win rate and average R | `logs/system_state.md` or `data/paper_validation_samples.csv` |
| First bottleneck | `logs/current_candle_capture.md` and `logs/DAILY_SHIP_REPORT.md` |
| Worst drop | `logs/DAILY_SHIP_REPORT.md` |
| Top rejection filters | `logs/filter_rejection_summary.csv` |
| Data sync status | `logs/data_flow_sentinel.md` |
| Dashboard preflight status | `logs/dashboard_data_preflight.md` |
| Market regime | `logs/market_regime_router.md` |

End-of-day rule:

```text
If an official validation sample was opened, do not count it as completed until
outcome_r, followed_plan, and exit_reason are recorded.
```
