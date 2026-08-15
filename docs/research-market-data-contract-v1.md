# Research Market Data Contract V1

Contract Version: `research-market-data-contract-v1`

Purpose: prevent Phase 3 research from treating mutable, stale, adjusted-mixed,
or look-ahead-contaminated candles as strategy truth.

## Approved Source

- Primary provider: Webull.
- Polygon may be used only after explicit compatibility verification.
- yfinance legacy downloads are not authoritative for Phase 3 strategy evidence.

## Session And Timezone

- US equities regular trading hours only unless a future experiment explicitly
  declares a different session policy.
- Store timestamps with timezone information where possible.
- Interpret strategy decisions on the America/New_York market clock.

## Timeframe Semantics

- M30: entry-decision candle; historical decisions may use only data available
  after the M30 candle has completed.
- M5: exit-management candle; historical exits may use only M5 candles after
  the entry timestamp.
- M60: higher-timeframe context; reconstructed M60 buckets are unavailable
  until the full 60-minute bucket has completed.
- D: completed daily context only; no intraday same-session daily-bar leakage.

## Adjustment Policy

Current status: unresolved.

Known mismatch:

- Polygon importer defaults to `adjusted=True`.
- yfinance loader uses `auto_adjust=False`.
- Webull adjustment semantics are not documented in-project.

Rule: do not mix adjusted and unadjusted providers in one Phase 3 experiment
until the provider behavior is documented and the experiment records the policy.

## Missing-Bar Policy

Fail closed for decision-critical M30/M5 data. Supporting/chart gaps must remain
visible and must not be silently filled.

## Resampling Policy

Resampling may use only complete lower-timeframe buckets. Higher-timeframe
context must be labeled by the timestamp when it becomes available, not merely
by the bucket start.

## Provenance Requirements

Every Phase 3 experiment must record:

- provider
- ingestion script
- source path
- creation timestamp
- contract version
- snapshot id
- file checksum
- coverage
- known gaps

## Look-Ahead Policy

No feature, context label, signal, regime label, or exit may use information
that was unavailable at the historical decision timestamp.

## Gate Policy

P3-E001 and P3-E002 remain waiting until source, external-validation,
corporate-action, and M5 coverage findings are reviewed or cleared.
