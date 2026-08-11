"""Append manually confirmed A/B options-ready validation samples to a ledger.

This writes to `data/paper_validation_samples.csv`, not the stricter
`data/paper_trades.csv`. It is still local paper-validation only and never
touches broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_options_contract_gate import build_gate as build_options_contract_gate
from run_playbook import markdown_table


SAMPLE_COLUMNS = [
    "sample_date",
    "entry_time_et",
    "source_signal_et",
    "candidate_entry_et",
    "exit_time_et",
    "symbol",
    "setup",
    "direction",
    "sample_tier",
    "signal_freshness",
    "validation_lane",
    "sample_status",
    "counts_toward_30",
    "counts_toward_live_readiness",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "actual_entry",
    "actual_exit",
    "suggested_shares",
    "sample_risk_pct",
    "contract_symbol",
    "option_type",
    "expiration",
    "dte",
    "strike",
    "delta",
    "bid",
    "ask",
    "mid",
    "spread_pct",
    "volume",
    "open_interest",
    "implied_volatility",
    "premium",
    "contract_gate_status",
    "outcome_r",
    "followed_plan",
    "exit_reason",
    "notes",
    "invalid_for_validation",
    "invalid_reason",
    "invalidated_at_et",
    "original_creation_timestamp",
    "incident_id",
    "source_contract_gate_identity",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import confirmed Paper Gate v2 validation samples.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--samples-csv", type=Path, default=Path("data/paper_validation_samples.csv"))
    parser.add_argument("--contract-audit-csv", type=Path, default=Path("data/options_contract_audit.csv"))
    parser.add_argument("--paper-csv", type=Path, default=Path("data/paper_trades.csv"))
    parser.add_argument("--confirm-samples", action="store_true", help="Actually append ready A/B samples.")
    return parser.parse_args()


def read_existing(path: Path) -> pd.DataFrame:
    """Read the validation sample ledger."""

    if not path.exists():
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    try:
        existing = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    for column in SAMPLE_COLUMNS:
        if column not in existing.columns:
            existing[column] = ""
    return existing[SAMPLE_COLUMNS]


def sample_rows_from_gate(payload: dict) -> pd.DataFrame:
    """Convert contract-passed gate rows into ledger rows."""

    rows = []
    for row in payload.get("passed_samples", []):
        rows.append(
            {
                "sample_date": row.get("sample_date", row.get("scan_date", "")),
                "entry_time_et": row.get("entry_time_et", ""),
                "source_signal_et": row.get("source_signal_et", ""),
                "candidate_entry_et": row.get("candidate_entry_et", ""),
                "exit_time_et": "",
                "symbol": row.get("symbol", ""),
                "setup": row.get("setup", ""),
                "direction": row.get("direction", ""),
                "sample_tier": row.get("sample_tier", ""),
                "signal_freshness": row.get("signal_freshness", ""),
                "validation_lane": row.get("validation_lane", row.get("sample_tier", "")),
                "sample_status": "open",
                "counts_toward_30": bool(row.get("counts_toward_30", False)),
                "counts_toward_live_readiness": bool(row.get("counts_toward_live_readiness", False)),
                "planned_entry": row.get("planned_entry", ""),
                "planned_stop": row.get("planned_stop", ""),
                "planned_target": row.get("planned_target", ""),
                "actual_entry": "",
                "actual_exit": "",
                "suggested_shares": row.get("suggested_shares", ""),
                "sample_risk_pct": row.get("sample_risk_pct", ""),
                "contract_symbol": row.get("contract_symbol", ""),
                "option_type": row.get("option_type", ""),
                "expiration": row.get("expiration", ""),
                "dte": row.get("dte", ""),
                "strike": row.get("strike", ""),
                "delta": row.get("delta", ""),
                "bid": row.get("bid", ""),
                "ask": row.get("ask", ""),
                "mid": row.get("mid", ""),
                "spread_pct": row.get("spread_pct", ""),
                "volume": row.get("volume", ""),
                "open_interest": row.get("open_interest", ""),
                "implied_volatility": row.get("implied_volatility", ""),
                "premium": row.get("premium", ""),
                "contract_gate_status": row.get("contract_gate_status", ""),
                "outcome_r": "",
                "followed_plan": "",
                "exit_reason": "",
                "notes": row.get("contract_gate_reason", ""),
                "invalid_for_validation": "",
                "invalid_reason": "",
                "invalidated_at_et": "",
                "original_creation_timestamp": "",
                "incident_id": "",
                "source_contract_gate_identity": "",
            }
        )
    return pd.DataFrame(rows, columns=SAMPLE_COLUMNS)


def dedupe(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    """Return rows that are not already in the ledger."""

    if new_rows.empty:
        return new_rows
    key_columns = [
        "sample_date",
        "entry_time_et",
        "symbol",
        "setup",
        "direction",
        "sample_tier",
        "planned_entry",
        "planned_stop",
        "planned_target",
        "contract_symbol",
        "expiration",
        "strike",
    ]
    existing_keys = set(existing[key_columns].astype(str).agg("|".join, axis=1)) if not existing.empty else set()
    new_keys = new_rows[key_columns].astype(str).agg("|".join, axis=1)
    return new_rows[~new_keys.isin(existing_keys)].copy()


def clean_text(value: object) -> str:
    """Return a stable string for CSV matching."""

    if pd.isna(value):
        return ""
    return str(value).strip()


def normalized_time(value: object) -> str:
    """Normalize HH:MM-ish CSV values without changing stored ledger values."""

    text = clean_text(value)
    if len(text) >= 5 and text[2] == ":":
        return text[:5]
    return text


def normalized_identity(date: object, time_value: object, symbol: object, setup: object, direction: object) -> str:
    """Build the contract-gate identity used across paper accounting ledgers."""

    return "|".join(
        [
            clean_text(date),
            normalized_time(time_value),
            clean_text(symbol).upper(),
            clean_text(setup).lower(),
            clean_text(direction).lower(),
        ]
    )


def official_sample_mask(samples: pd.DataFrame) -> pd.Series:
    """Return rows that are allowed to count toward official Gate 1 progress."""

    if samples.empty:
        return pd.Series(dtype=bool)
    if "counts_toward_30" in samples.columns:
        official = samples["counts_toward_30"].astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})
    elif "sample_tier" in samples.columns:
        official = samples["sample_tier"].astype(str).str.upper().isin({"A", "B"})
    else:
        official = pd.Series([False] * len(samples), index=samples.index)
    if "invalid_for_validation" in samples.columns:
        invalid = samples["invalid_for_validation"].astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})
        official = official & ~invalid
    return official


def completed_paper_trades(path: Path) -> pd.DataFrame:
    """Read completed local paper trades that can reconcile official samples."""

    if not path.exists():
        return pd.DataFrame()
    try:
        trades = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if "outcome_r" not in trades.columns:
        return pd.DataFrame()
    completed = trades["outcome_r"].notna() & trades["outcome_r"].astype(str).str.strip().ne("")
    return trades[completed].copy()


def paper_trade_identity(row: pd.Series) -> str:
    """Return the best available stable identity for a paper trade row."""

    explicit = clean_text(row.get("source_contract_gate_identity", ""))
    if explicit:
        return explicit
    return normalized_identity(
        row.get("trade_date", ""),
        row.get("entry_time_et", ""),
        row.get("symbol", ""),
        row.get("setup", ""),
        row.get("direction", ""),
    )


def sample_identity(row: pd.Series) -> str:
    """Return the best available stable identity for a validation sample row."""

    explicit = clean_text(row.get("source_contract_gate_identity", ""))
    if explicit:
        return explicit
    return normalized_identity(
        row.get("sample_date", ""),
        row.get("entry_time_et", ""),
        row.get("symbol", ""),
        row.get("setup", ""),
        row.get("direction", ""),
    )


def sync_completed_outcomes(samples: pd.DataFrame, paper_csv: Path) -> tuple[pd.DataFrame, int]:
    """Promote completed paper-trade outcomes into the official sample ledger."""

    if samples.empty:
        return samples, 0
    trades = completed_paper_trades(paper_csv)
    if trades.empty:
        return samples, 0

    trade_by_identity: dict[str, pd.Series] = {}
    for _, trade in trades.iterrows():
        identity = paper_trade_identity(trade)
        if identity and identity not in trade_by_identity:
            trade_by_identity[identity] = trade

    synced = samples.copy().astype(object)
    for column in SAMPLE_COLUMNS:
        if column not in synced.columns:
            synced[column] = ""

    official = official_sample_mask(synced)
    changed_rows = 0
    outcome_columns = ["exit_time_et", "actual_entry", "actual_exit", "outcome_r", "followed_plan", "exit_reason"]
    for index, sample in synced.iterrows():
        if not bool(official.loc[index]):
            continue
        identity = sample_identity(sample)
        trade = trade_by_identity.get(identity)
        if trade is None:
            continue
        row_changed = False
        for column in outcome_columns:
            if column not in trade.index:
                continue
            value = clean_text(trade.get(column, ""))
            if not value:
                continue
            current = clean_text(synced.at[index, column])
            if current != value:
                synced.at[index, column] = value
                row_changed = True
        if clean_text(trade.get("source_contract_gate_identity", "")) and clean_text(synced.at[index, "source_contract_gate_identity"]) == "":
            synced.at[index, "source_contract_gate_identity"] = clean_text(trade.get("source_contract_gate_identity", ""))
            row_changed = True
        if clean_text(trade.get("outcome_r", "")) and clean_text(synced.at[index, "sample_status"]) != "completed":
            synced.at[index, "sample_status"] = "completed"
            row_changed = True
        if row_changed:
            changed_rows += 1

    return synced[SAMPLE_COLUMNS], changed_rows


def build_import(
    output_dir: Path = Path("logs"),
    samples_csv: Path = Path("data/paper_validation_samples.csv"),
    contract_audit_csv: Path = Path("data/options_contract_audit.csv"),
    confirm_samples: bool = False,
    paper_csv: Path = Path("data/paper_trades.csv"),
) -> dict:
    """Build or write a validation sample import."""

    gate = build_options_contract_gate(
        output_dir=output_dir,
        contract_audit_csv=contract_audit_csv,
        samples_csv=samples_csv,
    )
    existing = read_existing(samples_csv)
    candidates = sample_rows_from_gate(gate)
    new_rows = dedupe(existing, candidates)
    if confirm_samples and not new_rows.empty:
        samples_csv.parent.mkdir(parents=True, exist_ok=True)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = existing
    combined, synced_outcome_rows = sync_completed_outcomes(combined, paper_csv)
    if (confirm_samples and not new_rows.empty) or synced_outcome_rows:
        samples_csv.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(samples_csv, index=False)
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "mode": "confirmed" if confirm_samples else "preview",
        "ready_candidates": int(gate.get("ready_sample_count", 0) or 0),
        "contract_ready_candidates": int(len(candidates)),
        "contract_gate_status": gate.get("status", "missing"),
        "missing_contract_reviews": int(gate.get("missing_contract_reviews", 0) or 0),
        "blocked_contract_count": int(gate.get("blocked_contract_count", 0) or 0),
        "new_rows": int(len(new_rows)),
        "synced_outcome_rows": int(synced_outcome_rows),
        "ledger_rows_after": int(len(combined)),
        "samples_csv": str(samples_csv),
        "contract_audit_csv": str(contract_audit_csv),
        "paper_csv": str(paper_csv),
        "guardrail": (
            "This imports local paper-validation samples only after Options Contract Gate v1 passes. "
            "It also syncs completed local paper-trade outcomes into existing official samples. "
            "It does not write broker orders, does not touch real money, and does not change data in data/paper_trades.csv."
        ),
        "rows": new_rows.to_dict("records"),
    }


def write_outputs(output_dir: Path, payload: dict) -> None:
    """Write sample import report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame(payload["rows"], columns=SAMPLE_COLUMNS)
    (output_dir / "paper_validation_sample_import.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    rows.to_csv(output_dir / "paper_validation_sample_import.csv", index=False)
    (output_dir / "paper_validation_sample_import.md").write_text(
        f"""# Paper Validation Sample Import

Generated: {payload["generated_at_et"]}

Mode: `{payload["mode"]}`

## Summary

```text
Ready candidates: {payload["ready_candidates"]}
Contract-ready candidates: {payload["contract_ready_candidates"]}
Contract gate status: {payload["contract_gate_status"]}
Missing contract reviews: {payload["missing_contract_reviews"]}
Blocked contracts: {payload["blocked_contract_count"]}
New rows: {payload["new_rows"]}
Synced completed outcomes: {payload["synced_outcome_rows"]}
Ledger rows after confirmed import: {payload["ledger_rows_after"]}
Ledger: {payload["samples_csv"]}
Contract audit: {payload["contract_audit_csv"]}
Paper trades: {payload["paper_csv"]}
```

## Rows

{markdown_table(rows)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_import(
        args.output_dir,
        args.samples_csv,
        args.contract_audit_csv,
        args.confirm_samples,
        paper_csv=args.paper_csv,
    )
    write_outputs(args.output_dir, payload)
    print(f"Paper validation sample import: {payload['mode']}")
    print(f"New rows: {payload['new_rows']}")
    print(f"Synced completed outcomes: {payload['synced_outcome_rows']}")
    print(f"Saved {args.output_dir / 'paper_validation_sample_import.md'}")


if __name__ == "__main__":
    main()
