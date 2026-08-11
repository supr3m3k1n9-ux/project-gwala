# Project Gwala Ship Readiness Report

Generated: 2026-06-16

Evidence snapshot used:

- `logs/current_candle_capture.json` from the final 2026-06-16 workflow run
- `logs/DAILY_SHIP_REPORT.json` from the final 2026-06-16 workflow run
- `logs/grace_lane_backtest.json`
- `logs/paper_gate_v2.json`
- `logs/options_contract_gate.json`
- `logs/paper_validation_sample_import.json`
- `logs/filter_rejection_summary.csv`
- Full workflow safety tests: `202` tests passed

## 1. Executive Summary

Current controlled-live launch readiness: **30%**

The readiness score improved from the prior `26%` snapshot because the researched
B-tier grace lane is now implemented and tested. It did not move paper progress
yet because the latest cached scan still produced `0` A/current or B/grace
paper-validation rows.

Biggest blocker to launch:

**No current A-tier or one-M30 B-tier scanner candidate exists in the latest
workflow run.** The scanner produced `24` rows and `1` allowed signal, but that
allowed signal was `earlier_today`, which remains study/shadow only.

Estimated days to paper gate completion:

- Current observed rate: **not forecastable** because completed official paper
  trades remain `0 / 30`.
- Expected after candidates appear: the implemented B-tier grace lane should
  materially improve throughput. The 90-day replay showed `308` A-tier windows
  plus `198` incremental B-tier windows after removing `29` duplicate A-window
  candidates, a **64.3% candidate-window increase**.
- Operating estimate once market-hours scans produce candidates: `5-10` market
  days if we can review and complete `3-6` official samples per day.

Estimated days to controlled live deployment:

- **Not before the paper gate is complete.**
- After `30 / 30` completed official paper trades: estimate `5-10` additional
  development/verification days for live-only safety systems.

Top 5 actions that move Project Gwala fastest toward market:

1. Keep the automated market-hours refresh/capture workflow running.
2. Review A/current and B/grace candidates immediately when they appear.
3. Complete Options Contract Gate review same day for every Paper Gate A/B row.
4. Import only contract-passed validation samples and complete outcomes quickly.
5. Keep strategy/provider/dashboard expansion frozen until paper throughput is moving.

## 2. Trade Funnel Analysis

Most recent local workflow run:

| Funnel Stage | Count | Percent of Scanner Rows | Percent of Previous Stage | Evidence |
| --- | ---: | ---: | ---: | --- |
| Scanner Signals Generated | 24 | 100.0% | 100.0% | `logs/daily_paper_signal_scanner.csv` |
| Allowed Signals | 1 | 4.2% | 4.2% | `1` allowed, but outside A/B freshness |
| A/B Paper-Validation Allowed | 0 | 0.0% | 0.0% | `0` current A-tier, `0` B-tier grace |
| After Position Sizing | 0 | 0.0% | 0.0% | `0` `size_ok` |
| After Market Regime Router | 0 | 0.0% | 0.0% | `0` review-supported rows |
| After Pre-Entry Review | 0 | 0.0% | 0.0% | `0` ready for manual review |
| After Paper Gate v2 | 0 | 0.0% | 0.0% | `0` A/B ready samples |
| After Options Contract Gate | 0 | 0.0% | 0.0% | `0` passed contracts |
| After Validation Import | 0 | 0.0% | 0.0% | Import mode `preview`; `0` new rows |
| Final Official Paper Candidates | 0 | 0.0% | 0.0% | `0 / 30` completed official paper trades |

B-tier throughput evidence:

| Metric | Value |
| --- | ---: |
| Current A-tier replay windows | 308 |
| Raw B-tier grace windows | 227 |
| Duplicate B windows removed | 29 |
| Incremental B-tier windows | 198 |
| Expected candidate-window increase | 64.3% |
| Incremental B-tier win rate | 61.6% |
| Incremental B-tier average R | +0.3126R |

## 3. Rejection Analysis

Total latest rejection events: **414**

| Filter Name | Rejections | Percentage of Total Rejections | Safety Critical | Quality Filter | Experimental |
| --- | ---: | ---: | --- | --- | --- |
| `trend_strength` | 275 | 66.4% | No | Yes | No |
| `position_size_limit` | 47 | 11.4% | Yes | No | No |
| `data_freshness` | 30 | 7.2% | Yes | No | No |
| `time_of_day_rule` | 24 | 5.8% | No | Yes | No |
| `volume_confirmation` | 20 | 4.8% | No | Yes | No |
| `regime_confidence` | 18 | 4.3% | No | Yes | No |

Experimental filters rejected **0** candidates in the latest report.

## 4. Paper Trading Gate Status

Current gate target: **30 completed official paper trades**

Current progress: **0 / 30**

| Requirement | Status | Blocking Reason |
| --- | --- | --- |
| A-tier current M30 lane | Complete | Implemented and still strict current-candle only |
| B-tier one-M30 grace lane | Complete | Implemented; no B row appeared in latest run |
| B-tier manual review only | Complete | B rows do not receive local entry packets |
| B-tier fresh stop/target/sizing | Complete | Scanner refreshes plan from latest candle; sizing caps B at reduced risk |
| B-tier duplicate A-window removal | Complete | Paper Gate downgrades duplicate B windows to study-only |
| Options Contract Gate required | Complete | Validation import only reads contract-passed samples |
| Official validation sample import | In Progress | Works in preview/confirmed mode, but no contract-passed rows exist now |
| Completed official paper trades | Blocked | `0 / 30`; no official sample has completed outcome review |
| Live broker readiness | Not Started | Broker execution remains intentionally disabled |

## 5. Safety Systems Audit

| Safety System | Status | Evidence |
| --- | --- | --- |
| Kill switch | FAIL | Required before live/broker phase; not needed for current manual validation import |
| Max daily loss | PASS | Position sizing/risk guard covers local paper sizing |
| Position size limits | PASS | A uses configured paper risk; B is capped at reduced `0.10%` validation risk |
| Duplicate order prevention | PASS | Local paper execution keeps current-candle-only duplicate keys; B does not enter local order path |
| Broker disconnect handling | FAIL | No broker path exists yet |
| Logging | PASS | Scanner, sizing, router, pre-entry, Paper Gate, Contract Gate, import, ship report, and system state write reports |
| Emergency shutdown | FAIL | Required before live/broker phase |
| Error recovery | PARTIAL | Data Flow Sentinel, dashboard preflight, and router JSON cleanup catch workflow issues |
| Trade reconciliation | PARTIAL | Paper validation ledger exists; broker reconciliation is out of scope until live phase |

## 6. Scope Creep Audit

| Feature / Area | Required For Paper Gate? | Maintenance Burden | Complexity Burden | Defer? |
| --- | --- | --- | --- | --- |
| New strategies | No | High | High | Yes |
| New indicators | No | High | High | Yes |
| Options-flow/gamma systems | No | High | High | Yes |
| Provider switching | No | Medium | High | Yes |
| Dashboard polish/showpiece visuals | No | Medium | Medium | Yes |
| Automated broker execution | No | High | High | Yes |
| Automated option-chain selection | No for V1 | High | High | Yes |
| B-tier grace lane | Yes | Low | Medium | Implemented |

## 7. Market Launch Recommendation

**B) Requires additional hardening before paper gate completion**

Evidence:

- The B-tier grace lane is implemented and tested.
- Full workflow safety tests passed: `202 / 202`.
- The latest workflow still has `0` A/B paper-validation candidates and `0 / 30`
  completed official paper trades.
- Live-only safety systems are still missing, especially kill switch,
  emergency shutdown, broker disconnect handling, and broker order rejection
  handling.

## 8. Founder Summary

If I were CTO and the only goal was reaching market as fast as possible, I
would stop building new strategy/provider/dashboard scope immediately.

I would finish first:

- Market-hours capture reliability.
- Same-day manual review for A/current and B/grace rows.
- Same-day Options Contract Gate review.
- Same-day validation import and outcome completion.
- Live-only safety systems only after the paper gate has real completed evidence.

The shortest safe path is now narrower and clearer: **use the implemented
A/B paper-validation lanes to collect completed official samples, not more
strategy surface area.**
