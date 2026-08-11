# Local Option-Chain Imports

Put one CSV per symbol in this folder when a Paper Gate survivor needs automatic
paper-contract selection.

Expected path:

```text
data/options_chains/TSLA.csv
```

Template paths:

```text
data/options_chains/templates/TSLA_template.csv
data/options_chains/templates/MSFT_template.csv
data/options_chains/templates/SPY_template.csv
```

Required columns:

```text
contract_symbol,option_type,expiration,dte,strike,delta,bid,ask,volume,open_interest
```

Optional columns:

```text
mid,spread_pct,implied_volatility,premium,earnings_within_window
```

Notes:

- `option_type` should be `CALL` or `PUT`.
- `spread_pct` can be entered as `0.05` or `5` for five percent.
- If `mid`, `spread_pct`, or `premium` are blank, the review script derives
  them from bid/ask when possible.
- The script only selects contracts that already pass the current Options
  Contract Gate thresholds. It does not place orders or approve paper entries.

## Fastest Market-Hours Workflow

1. Copy the matching template into the active symbol path:

```text
cp data/options_chains/templates/TSLA_template.csv data/options_chains/TSLA.csv
```

2. Replace the sample rows with the contracts around the candidate strike from
   the option chain.
3. Save the file.
4. In the Paper Trade Command Center, click `Auto-select A-tier Contract`.

If the symbol file is missing, the Command Center shows the exact missing path,
for example:

```text
Missing TSLA option-chain CSV: data/options_chains/TSLA.csv
```
