"""Review an options chain against the existing Contract Gate rules.

This is a paper-workflow helper only. It reads Paper Gate v2 ready samples and
an option-chain CSV/export, chooses the cleanest contract that already satisfies
the existing Options Contract Gate thresholds, and can write that contract into
data/options_contract_audit.csv for the normal gate to judge.

It does not request broker orders, place trades, create alerts, or enable live
execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from config.filter_policy import OPTIONS_CONTRACT_THRESHOLDS
from config.market_calendar import MARKET_TZ
from run_options_contract_gate import (
    CONTRACT_AUDIT_COLUMNS,
    CONTRACT_AUDIT_CSV,
    contract_key,
    read_csv_or_empty,
    sample_entry_time,
    sample_template_row,
)
from run_paper_gate_v2 import build_payload as build_paper_gate_payload
from run_playbook import markdown_table


CHAIN_COLUMNS = [
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
    "earnings_within_window",
    "selection_status",
    "selection_reason",
    "selection_score",
]

COLUMN_ALIASES = {
    "contract_symbol": ["contract_symbol", "option_symbol", "ticker", "symbol", "contract"],
    "option_type": ["option_type", "option side", "side", "type", "put/call"],
    "expiration": ["expiration", "expiry", "exp", "expire_date", "expiration_date"],
    "dte": ["dte", "days_to_expiration", "days to expiration"],
    "strike": ["strike", "strike_price"],
    "delta": ["delta"],
    "bid": ["bid"],
    "ask": ["ask"],
    "mid": ["mid", "mark", "mark_price"],
    "last": ["last", "last_price"],
    "spread_pct": ["spread_pct", "spread %", "spread_percent", "bid_ask_spread_pct"],
    "volume": ["volume", "vol"],
    "open_interest": ["open_interest", "open int", "open_int", "oi"],
    "implied_volatility": ["implied_volatility", "impl vol", "impl_vol", "iv", "implied vol"],
    "premium": ["premium"],
    "earnings_within_window": ["earnings_within_window", "earnings", "earnings_warning"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review option-chain contracts for ready Paper Gate samples.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument(
        "--chain-csv",
        type=Path,
        help=(
            "Option-chain CSV/export. If omitted, uses data/options_chains/SYMBOL.csv "
            "for each ready sample."
        ),
    )
    parser.add_argument("--chain-dir", type=Path, default=Path("data/options_chains/active"))
    parser.add_argument("--symbol", help="Only review ready samples for this symbol.")
    parser.add_argument(
        "--tier",
        action="append",
        choices=["A", "B"],
        help="Only review ready samples from this Paper Gate tier. May be passed more than once.",
    )
    parser.add_argument("--max-dte", type=float, default=OPTIONS_CONTRACT_THRESHOLDS["max_dte"])
    parser.add_argument("--contract-audit-csv", type=Path, default=CONTRACT_AUDIT_CSV)
    parser.add_argument("--samples-csv", type=Path, default=Path("data/paper_validation_samples.csv"))
    parser.add_argument("--candidate-ledger-csv", type=Path, default=Path("data/candidate_window_ledger.csv"))
    parser.add_argument("--account-size", type=float, default=10_000.0)
    parser.add_argument("--max-chain-age-minutes", type=float, default=20.0)
    parser.add_argument(
        "--write-audit",
        action="store_true",
        help="Append the selected contract row to data/options_contract_audit.csv.",
    )
    parser.add_argument(
        "--allow-missing-option-type",
        action="store_true",
        help="Assume PUT for short samples and CALL for long samples when the chain has no option_type column.",
    )
    return parser.parse_args()


def clean_name(value: object) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    raw = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def yes_value(value: object) -> bool:
    return text(value).lower() in {"1", "true", "yes", "y"}


def chain_path_for_sample(sample: dict[str, Any], explicit: Path | None, chain_dir: Path = Path("data/options_chains")) -> Path:
    if explicit:
        return explicit
    return chain_dir / f"{text(sample.get('symbol')).upper()}.csv"


def read_chain(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def metadata_path_for(chain_path: Path) -> Path:
    return chain_path.with_suffix(".metadata.json")


def parse_et_timestamp(value: object) -> pd.Timestamp | None:
    raw = text(value)
    if not raw:
        return None
    parsed = pd.to_datetime(raw, errors="coerce")
    if pd.isna(parsed) and raw.endswith((" EDT", " EST")):
        parsed = pd.to_datetime(raw.rsplit(" ", 1)[0], errors="coerce")
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(MARKET_TZ)
    return parsed.tz_convert(MARKET_TZ)


def read_metadata(path: Path) -> dict[str, Any]:
    metadata_path = metadata_path_for(path)
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def validate_chain_provenance(
    *,
    chain_path: Path,
    chain: pd.DataFrame,
    sample: dict[str, Any],
    max_age_minutes: float,
    now: datetime | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Fail closed unless the active chain has current-session provenance."""

    metadata = read_metadata(chain_path)
    if not metadata:
        return False, "blocked_incomplete_provenance: missing option-chain metadata", {}
    symbol = text(sample.get("symbol")).upper()
    sample_date = text(sample.get("scan_date"))
    if text(metadata.get("import_status")) != "success":
        return False, "blocked_incomplete_provenance: provider import did not complete successfully", metadata
    if text(metadata.get("symbol")).upper() != symbol:
        return False, "blocked_incomplete_provenance: metadata symbol mismatch", metadata
    try:
        if chain_path.resolve() != Path(text(metadata.get("chain_file"))).resolve():
            return False, "blocked_incomplete_provenance: metadata chain file mismatch", metadata
    except OSError:
        return False, "blocked_incomplete_provenance: metadata chain file mismatch", metadata
    if text(metadata.get("trading_session_date")) != sample_date:
        return False, "blocked_stale_option_chain: metadata session date does not match candidate", metadata
    chain_ts = parse_et_timestamp(metadata.get("chain_retrieval_timestamp"))
    underlying_ts = parse_et_timestamp(metadata.get("underlying_price_timestamp"))
    if chain_ts is None:
        return False, "blocked_incomplete_provenance: missing chain retrieval timestamp", metadata
    if underlying_ts is None:
        return False, "blocked_incomplete_provenance: missing underlying price timestamp", metadata
    current = pd.Timestamp(now or datetime.now(MARKET_TZ)).tz_convert(MARKET_TZ)
    max_age = pd.Timedelta(minutes=max_age_minutes)
    if current - chain_ts > max_age:
        return False, "blocked_stale_option_chain: chain retrieval timestamp is over age tolerance", metadata
    if current - underlying_ts > max_age:
        return False, "blocked_stale_option_chain: underlying price timestamp is over age tolerance", metadata
    required_metadata = [
        "provider",
        "source_file_generation_timestamp",
        "underlying_price_used",
        "delta_source",
        "delta_model_name",
        "risk_free_rate_used",
        "implied_volatility_source",
        "underlying_price_used_for_delta",
        "calculation_timestamp",
    ]
    missing = [key for key in required_metadata if text(metadata.get(key)) == ""]
    if missing:
        return False, "blocked_incomplete_provenance: missing " + ", ".join(missing), metadata
    required_columns = [
        "provider",
        "trading_session_date",
        "chain_retrieval_timestamp",
        "quote_timestamp",
        "underlying_price",
        "underlying_price_timestamp",
        "delta_source",
        "delta_model_name",
        "risk_free_rate",
        "implied_volatility_source",
        "underlying_price_for_delta",
        "calculation_timestamp",
    ]
    if chain.empty or any(column not in chain.columns for column in required_columns):
        return False, "blocked_incomplete_provenance: missing row-level provenance columns", metadata
    if not chain["trading_session_date"].astype(str).eq(sample_date).all():
        return False, "blocked_stale_option_chain: row session date does not match candidate", metadata
    if not chain["provider"].astype(str).eq(text(metadata.get("provider"))).all():
        return False, "blocked_incomplete_provenance: row provider mismatch", metadata
    if not chain["delta_source"].astype(str).eq("modeled_black_scholes").all():
        return False, "blocked_incomplete_provenance: unsupported or missing delta source", metadata
    if chain[["delta", "implied_volatility", "underlying_price_for_delta", "risk_free_rate"]].isna().any().any():
        return False, "blocked_incomplete_provenance: modeled delta inputs missing", metadata
    return True, "pass", metadata


def alias_map(columns: list[str]) -> dict[str, str]:
    by_clean = {clean_name(column): column for column in columns}
    found = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if clean_name(alias) in by_clean:
                found[canonical] = by_clean[clean_name(alias)]
                break
    return found


def expected_option_type(direction: str) -> str:
    return "PUT" if direction.lower() == "short" else "CALL"


def normalize_chain_row(
    raw: pd.Series,
    aliases: dict[str, str],
    template: dict[str, Any],
    allow_missing_option_type: bool,
) -> dict[str, Any]:
    direction = text(template.get("direction")).lower()
    expected_type = expected_option_type(direction)

    def value(name: str) -> object:
        column = aliases.get(name)
        return raw.get(column, "") if column else ""

    option_type = text(value("option_type")).upper()
    if not option_type and allow_missing_option_type:
        option_type = expected_type

    bid = number(value("bid"))
    ask = number(value("ask"))
    mid = number(value("mid"))
    if mid is None and bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2

    premium = number(value("premium"))
    if premium is None:
        premium = mid or number(value("last"))

    spread_pct = number(value("spread_pct"))
    if spread_pct is not None and spread_pct > 1:
        spread_pct = spread_pct / 100
    if spread_pct is None and bid is not None and ask is not None and mid is not None and mid > 0:
        spread_pct = (ask - bid) / mid

    return {
        "sample_date": template["sample_date"],
        "entry_time_et": template["entry_time_et"],
        "symbol": template["symbol"],
        "setup": template["setup"],
        "direction": template["direction"],
        "strategy_id": template["strategy_id"],
        "sample_tier": template["sample_tier"],
        "contract_symbol": text(value("contract_symbol")),
        "option_type": option_type,
        "expiration": text(value("expiration")),
        "dte": number(value("dte")),
        "strike": number(value("strike")),
        "delta": number(value("delta")),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_pct": spread_pct,
        "volume": number(value("volume")),
        "open_interest": number(value("open_interest")),
        "implied_volatility": number(value("implied_volatility")),
        "premium": premium,
        "earnings_within_window": yes_value(value("earnings_within_window")),
        "notes": "selected_from_option_chain_review",
    }


def review_candidate(row: dict[str, Any], max_dte: float) -> tuple[bool, str]:
    blockers: list[str] = []
    filters = OPTIONS_CONTRACT_THRESHOLDS

    if row["option_type"] != expected_option_type(row["direction"]):
        blockers.append(f"option_type must be {expected_option_type(row['direction'])}")

    delta = row["delta"]
    abs_delta = abs(delta) if delta is not None else None
    if abs_delta is None:
        blockers.append("missing delta")
    elif abs_delta < filters["min_abs_delta"] or abs_delta > filters["max_abs_delta"]:
        blockers.append(f"delta {delta:.2f} outside {filters['min_abs_delta']:.2f}-{filters['max_abs_delta']:.2f}")

    bid = row["bid"]
    ask = row["ask"]
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        blockers.append("missing valid bid/ask")
    elif ask < bid:
        blockers.append("ask is below bid")

    spread_pct = row["spread_pct"]
    if spread_pct is None:
        blockers.append("missing spread")
    elif spread_pct > filters["max_bid_ask_spread_pct"]:
        blockers.append(f"spread {spread_pct:.1%} above {filters['max_bid_ask_spread_pct']:.0%}")

    volume = row["volume"]
    if volume is None or volume < filters["min_volume"]:
        blockers.append(f"volume below {filters['min_volume']}")

    open_interest = row["open_interest"]
    if open_interest is None or open_interest < filters["min_open_interest"]:
        blockers.append(f"open interest below {filters['min_open_interest']}")

    dte = row["dte"]
    if dte is None:
        blockers.append("missing DTE")
    elif dte < filters["min_dte"] or dte > max_dte:
        blockers.append(f"DTE outside {filters['min_dte']}-{max_dte}")

    strike = row["strike"]
    if strike is None or strike <= 0:
        blockers.append("missing valid strike")

    premium = row["premium"]
    if premium is None or premium <= 0:
        blockers.append("missing valid premium")

    if row["earnings_within_window"]:
        blockers.append("earnings within risk window")

    return not blockers, "pass" if not blockers else "; ".join(blockers)


def selection_score(row: dict[str, Any]) -> float:
    """Rank only gate-passing contracts with conservative tie-breakers."""

    abs_delta = abs(float(row["delta"]))
    spread_pct = float(row["spread_pct"])
    volume = float(row["volume"])
    open_interest = float(row["open_interest"])
    premium = float(row["premium"])
    return (
        abs(abs_delta - 0.50) * 100
        + spread_pct * 100
        - min(volume, 5000) / 5000
        - min(open_interest, 10000) / 10000
        + min(premium, 20) / 100
    )


def json_safe(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def format_audit_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def write_audit_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_csv_or_empty(path, CONTRACT_AUDIT_COLUMNS)
    existing_keys = (
        {(contract_key(row), text(row.get("contract_symbol")).upper()) for _, row in existing.iterrows()}
        if not existing.empty
        else set()
    )
    new_rows = []
    for row in rows:
        row_key = (contract_key(row), text(row.get("contract_symbol")).upper())
        if row_key in existing_keys:
            continue
        new_rows.append({column: format_audit_value(row.get(column, "")) for column in CONTRACT_AUDIT_COLUMNS})
    if not new_rows:
        return
    pd.concat([existing, pd.DataFrame(new_rows, columns=CONTRACT_AUDIT_COLUMNS)], ignore_index=True).to_csv(
        path,
        index=False,
    )


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    paper_gate = build_paper_gate_payload(
        output_dir=args.output_dir,
        scanner_csv=args.output_dir / "daily_paper_signal_scanner.csv",
        samples_csv=args.samples_csv,
        account_size=args.account_size,
        promotion_source="candidate_ledger",
        candidate_ledger_csv=args.candidate_ledger_csv,
    )
    ready_samples = paper_gate.get("ready_samples", []) if isinstance(paper_gate.get("ready_samples", []), list) else []
    if args.symbol:
        ready_samples = [row for row in ready_samples if text(row.get("symbol")).upper() == args.symbol.upper()]
    if args.tier:
        allowed_tiers = {tier.upper() for tier in args.tier}
        ready_samples = [row for row in ready_samples if text(row.get("sample_tier")).upper() in allowed_tiers]

    rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    chain_files: list[str] = []

    for sample in ready_samples:
        template = sample_template_row(sample)
        template["entry_time_et"] = sample_entry_time(sample)
        chain_path = chain_path_for_sample(sample, args.chain_csv, args.chain_dir)
        chain_files.append(str(chain_path))
        chain = read_chain(chain_path)
        if chain.empty:
            rows.append(
                {
                    **{column: template.get(column, "") for column in CONTRACT_AUDIT_COLUMNS},
                    "selection_status": "missing_chain",
                    "selection_reason": f"Option-chain CSV not found or empty: {chain_path}",
                    "selection_score": "",
                }
            )
            continue
        provenance_ok, provenance_reason, provenance = validate_chain_provenance(
            chain_path=chain_path,
            chain=chain,
            sample=sample,
            max_age_minutes=args.max_chain_age_minutes,
        )
        if not provenance_ok:
            rows.append(
                {
                    **{column: template.get(column, "") for column in CONTRACT_AUDIT_COLUMNS},
                    "selection_status": provenance_reason.split(":", 1)[0],
                    "selection_reason": provenance_reason,
                    "selection_score": "",
                }
            )
            continue

        aliases = alias_map(list(chain.columns))
        reviewed = []
        for _, raw in chain.iterrows():
            normalized = normalize_chain_row(raw, aliases, template, args.allow_missing_option_type)
            passed, reason = review_candidate(normalized, args.max_dte)
            normalized["selection_status"] = "eligible" if passed else "blocked"
            normalized["selection_reason"] = reason
            normalized["selection_score"] = selection_score(normalized) if passed else ""
            reviewed.append(normalized)

        eligible = [row for row in reviewed if row["selection_status"] == "eligible"]
        if eligible:
            eligible.sort(key=lambda row: float(row["selection_score"]))
            selected = {**eligible[0], "selection_status": "selected"}
            selected_rows.append(selected)
            for row in reviewed:
                if row is eligible[0]:
                    rows.append(selected)
                else:
                    rows.append(row)
        else:
            rows.extend(reviewed)

    audit_rows = [{column: row.get(column, "") for column in CONTRACT_AUDIT_COLUMNS} for row in selected_rows]
    if args.write_audit:
        write_audit_rows(args.contract_audit_csv, audit_rows)

    status = "ready" if selected_rows else "waiting_for_eligible_contract"
    if not ready_samples:
        status = "waiting_for_paper_gate_sample"

    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "ready_sample_count": len(ready_samples),
        "selected_contract_count": len(selected_rows),
        "write_audit": bool(args.write_audit),
        "contract_audit_csv": str(args.contract_audit_csv),
        "promotion_source": paper_gate.get("promotion_source", "scanner_snapshot"),
        "chain_files": sorted(set(chain_files)),
        "filters": {**OPTIONS_CONTRACT_THRESHOLDS, "max_dte": args.max_dte},
        "max_chain_age_minutes": args.max_chain_age_minutes,
        "guardrail": (
            "Option-chain review is paper-contract selection only. It writes no orders, "
            "creates no alerts, and leaves final approval to Options Contract Gate v1."
        ),
        "selected_contracts": [{key: json_safe(value) for key, value in row.items()} for row in selected_rows],
        "rows": [{key: json_safe(value) for key, value in row.items()} for row in rows],
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame(payload["rows"], columns=CHAIN_COLUMNS)
    selected = pd.DataFrame(payload["selected_contracts"], columns=CONTRACT_AUDIT_COLUMNS + ["selection_score"])
    rows.to_csv(output_dir / "options_chain_review.csv", index=False)
    selected.to_csv(output_dir / "options_chain_selected_contracts.csv", index=False)
    (output_dir / "options_chain_review.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")

    filter_rows = pd.DataFrame([{"filter": key, "value": value} for key, value in payload["filters"].items()])
    (output_dir / "options_chain_review.md").write_text(
        f"""# Options Chain Review

This report selects paper-contract candidates from an option-chain CSV/export
using the existing Options Contract Gate thresholds.

## Summary

```text
Status: {payload["status"]}
Ready Paper Gate samples: {payload["ready_sample_count"]}
Selected contracts: {payload["selected_contract_count"]}
Wrote audit CSV: {payload["write_audit"]}
Contract audit CSV: {payload["contract_audit_csv"]}
```

## Filters

{markdown_table(filter_rows)}

## Selected Contracts

{markdown_table(selected)}

## Reviewed Chain Rows

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
    payload = build_payload(args)
    write_outputs(args.output_dir, payload)
    print(f"Options chain review: {payload['status']}")
    print(f"Selected contracts: {payload['selected_contract_count']}")
    if args.write_audit:
        print(f"Wrote selected rows to {args.contract_audit_csv}")
    print(f"Saved {args.output_dir / 'options_chain_review.md'}")


if __name__ == "__main__":
    main()
