# Project Gwala Trading Playbook

This is a research and paper-trading playbook for the current best backtested
profile. It is not a live-trading or broker-execution plan.

## Trade Style

Rules-based intraday VWAP and EMA trend continuation.

The strategy looks for strong opening-session direction, then trades continuation
in the direction of the trend using:

```text
1H chart: higher-timeframe bias
30m chart: entry signal
5m chart: exit management
VWAP: intraday control line
9 EMA: short-term momentum
21 EMA: trend structure
200 EMA: macro trend filter
Opening range: early-session strength
R-multiple: risk and performance measurement
```

## Current Best Research Profile

```bash
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
```

Latest internal research result:

```text
Accepted trades: 325
Skipped trades: 31
Raw trades blocked: 28
Win rate: 0.5354
Expectancy: +0.1446R
Profit factor: 1.6707
Max drawdown: -6.5803R
Final cumulative R: +46.9839R
```

Internal holdout checks improved expectancy and profit factor in every tested
window. Fresh data validation is still required before treating the filter as
durable.

## Approved Setups

| Symbol | Setup | Variant | Exit Profile | Notes |
| --- | --- | --- | --- | --- |
| SPY | Setup A Long | current | no_vwap_exit | Broadest long setup. |
| QQQ | Setup A Long | quality_entry | no_vwap_exit | Selective long setup. |
| TSLA | Setup A Long | market_confirmed | two_vwap_closes | Requires SPY confirmation; exits on two 5m VWAP losses. |
| AAPL | Setup A Long | market_confirmed | no_vwap_exit | Requires SPY confirmation. |
| TSLA | Setup B Short | setup_b_short | no_vwap_exit | Bearish continuation setup. |
| AMD | Setup B Short | setup_b_short | no_vwap_exit | Bearish continuation setup. |
| QQQ | Setup B Short | setup_b_short | no_vwap_exit | Bearish continuation setup. |
| NVDA | Setup B Short | setup_b_short | no_vwap_exit | Bearish continuation setup. |
| AAPL | Setup B Short | setup_b_short | two_vwap_closes | Exits on two 5m VWAP reclaims. |

## Trade Blocks

The `weakness_v1` filter blocks these entry-known conditions:

```text
NVDA Setup B Short:
- Block 11am ET entries
- Block relative volume from 0.75 to 1.0
- Block relative volume from 1.25 to 1.5

SPY Setup A Long:
- Block room-to-target from 0.75R to 1.0R
```

## Portfolio Risk Rules

```text
Max open positions: 3
Max open positions per symbol: 1
Max trades per day: 5
Max daily realized loss: -3R
Max monthly realized loss: -3R
```

## Entry Checklist

Before a paper trade is considered valid:

```text
1. Symbol/setup is in the approved playbook.
2. Direction matches the approved setup.
3. 1H bias supports the trade direction.
4. 30m signal triggers.
5. VWAP/EMA structure matches the setup rules.
6. Opening range behavior supports continuation.
7. Trade is not blocked by weakness_v1.
8. Portfolio risk limits allow a new trade.
```

## Planned Trade Fields

Every paper signal should record:

```text
symbol
setup
direction
entry time
entry price
stop price
target price
risk per share
exit profile
quality score
relative volume
room to target
allowed or blocked
block reason
```

## Safety Rules

Never add:

```text
martingale
averaging down
revenge trades
overleverage
stop-loss removal
real-money execution before separate paper-trading validation
```

## Next Validation Step

Pull fresh Webull candles later and rerun:

```bash
python run_playbook.py --mode approved
python run_portfolio.py --profile monthly_stop_3r
python run_portfolio.py --profile monthly_stop_3r --trade-filter weakness_v1
python run_holdout_validation.py
python run_signal_journal.py
```
