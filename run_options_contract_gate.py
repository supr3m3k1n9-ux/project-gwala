"""Gate paper-validation candidates by manual options contract quality.

This is the first options-specific quality layer for Project Gwala. It reads
Paper Gate v2 chart candidates and a manually maintained contract audit CSV,
then decides whether the selected option contract is clean enough for an
official local paper-validation sample.

It does not request option chains, place broker orders, create broker alerts, or
enable real-money trading.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

from config.filter_policy import OPTIONS_CONTRACT_THRESHOLDS
from config.market_calendar import MARKET_TZ
from config.runtime_paths import runtime_data_path
from run_paper_gate_v2 import build_payload as build_paper_gate_payload
from run_playbook import markdown_table


CONTRACT_AUDIT_CSV = runtime_data_path("options_contract_audit.csv")
CONTRACT_AUDIT_COLUMNS = [
    "sample_date",
    "entry_time_et",
    "symbol",
    "setup",
    "direction",
    "strategy_id",
    "sample_tier",
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
    "notes",
]
GATE_COLUMNS = [
    "sample_date",
    "entry_time_et",
    "source_signal_et",
    "candidate_entry_et",
    "symbol",
    "setup",
    "direction",
    "strategy_id",
    "variant",
    "exit_profile",
    "sample_tier",
    "signal_freshness",
    "validation_lane",
    "manual_review_required",
    "counts_toward_30",
    "counts_toward_live_readiness",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "suggested_shares",
    "sample_risk_pct",
    *CONTRACT_AUDIT_COLUMNS[7:],
    "contract_gate_status",
    "contract_gate_pass",
    "contract_gate_reason",
]
FILTERS = OPTIONS_CONTRACT_THRESHOLDS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Options Contract Gate v1 report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--contract-audit-csv", type=Path, default=CONTRACT_AUDIT_CSV)
    parser.add_argument("--samples-csv", type=Path, default=runtime_data_path("paper_validation_samples.csv"))
    parser.add_argument("--candidate-ledger-csv", type=Path, default=runtime_data_path("candidate_window_ledger.csv"))
    parser.add_argument("--account-size", type=float, default=10_000.0)
    parser.add_argument(
        "--skip-autonomous-lifecycle",
        action="store_true",
        help="Do not trigger the autonomous A-tier lifecycle after Contract Gate PASS rows.",
    )
    return parser.parse_args()


def read_csv_or_empty(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV or return an empty frame with the expected columns."""

    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    try:
        frame = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns or [])
    if columns:
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
        return frame[columns]
    return frame


def text(value: object) -> str:
    """Return stable text for CSV/JSON values."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def number(value: object) -> float | None:
    """Return a finite number or None."""

    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        parsed = float(str(value).strip().replace("%", ""))
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def ratio_value(value: object) -> float | None:
    """Read ratios entered either as 0.15 or 15."""

    parsed = number(value)
    if parsed is None:
        return None
    if parsed > 1:
        return parsed / 100
    return parsed


def yes_value(value: object) -> bool:
    """Return True for common yes/true values."""

    return text(value).lower() in {"1", "true", "yes", "y"}


def sample_entry_time(row: dict[str, Any]) -> str:
    """Return HH:MM from the active Paper Gate candidate time."""

    raw = text(row.get("candidate_entry_et")) or text(row.get("latest_signal_et"))
    parsed = pd.to_datetime(raw, errors="coerce")
    if not pd.isna(parsed):
        return parsed.strftime("%H:%M")
    return raw[11:16] if len(raw) >= 16 else raw


def contract_key(row: dict[str, Any] | pd.Series) -> tuple[str, str, str, str, str]:
    """Return the matching key between a gate sample and manual contract row."""

    return (
        text(row.get("sample_date")).lower(),
        text(row.get("entry_time_et")).lower(),
        text(row.get("symbol")).upper(),
        text(row.get("setup")).lower(),
        text(row.get("direction")).lower(),
    )


def sample_template_row(row: dict[str, Any]) -> dict[str, Any]:
    """Build the manual contract-audit template row for one ready sample."""

    return {
        "sample_date": text(row.get("scan_date")),
        "entry_time_et": sample_entry_time(row),
        "symbol": text(row.get("symbol")).upper(),
        "setup": text(row.get("setup")),
        "direction": text(row.get("direction")).lower(),
        "strategy_id": text(row.get("strategy_id")),
        "sample_tier": text(row.get("sample_tier")),
        "contract_symbol": "",
        "option_type": "CALL" if text(row.get("direction")).lower() == "long" else "PUT",
        "expiration": "",
        "dte": "",
        "strike": "",
        "delta": "",
        "bid": "",
        "ask": "",
        "mid": "",
        "spread_pct": "",
        "volume": "",
        "open_interest": "",
        "implied_volatility": "",
        "premium": "",
        "earnings_within_window": "",
        "notes": "",
    }


def latest_contract_lookup(audit: pd.DataFrame) -> dict[tuple[str, str, str, str, str], pd.Series]:
    """Return the last manual contract row per sample key."""

    lookup: dict[tuple[str, str, str, str, str], pd.Series] = {}
    for _, row in audit.iterrows():
        lookup[contract_key(row)] = row
    return lookup


def contract_mid(row: pd.Series) -> float | None:
    """Return contract mid from row mid or bid/ask."""

    mid = number(row.get("mid"))
    if mid and mid > 0:
        return mid
    bid = number(row.get("bid"))
    ask = number(row.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2


def contract_spread_pct(row: pd.Series) -> float | None:
    """Return bid/ask spread as a ratio."""

    explicit = ratio_value(row.get("spread_pct"))
    if explicit is not None:
        return explicit
    bid = number(row.get("bid"))
    ask = number(row.get("ask"))
    mid = contract_mid(row)
    if bid is None or ask is None or mid is None or mid <= 0:
        return None
    return (ask - bid) / mid


def required_option_type(direction: str) -> str:
    """Return the expected option side for the directional chart signal."""

    return "PUT" if direction.lower() == "short" else "CALL"


def review_contract(row: pd.Series, direction: str) -> tuple[str, bool, str, dict[str, Any]]:
    """Return status, pass flag, reason, and normalized contract fields."""

    blockers: list[str] = []
    option_type = text(row.get("option_type")).upper()
    expected_type = required_option_type(direction)
    if option_type != expected_type:
        blockers.append(f"option_type must be {expected_type}")

    delta = number(row.get("delta"))
    abs_delta = abs(delta) if delta is not None else None
    if abs_delta is None:
        blockers.append("missing delta")
    elif abs_delta < FILTERS["min_abs_delta"] or abs_delta > FILTERS["max_abs_delta"]:
        blockers.append(
            f"delta {delta:.2f} outside {FILTERS['min_abs_delta']:.2f}-{FILTERS['max_abs_delta']:.2f}"
        )

    bid = number(row.get("bid"))
    ask = number(row.get("ask"))
    mid = contract_mid(row)
    spread_pct = contract_spread_pct(row)
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        blockers.append("missing valid bid/ask")
    elif ask < bid:
        blockers.append("ask is below bid")
    if spread_pct is None:
        blockers.append("missing spread")
    elif spread_pct > FILTERS["max_bid_ask_spread_pct"]:
        blockers.append(f"spread {spread_pct:.1%} above {FILTERS['max_bid_ask_spread_pct']:.0%}")

    volume = number(row.get("volume"))
    if volume is None or volume < FILTERS["min_volume"]:
        blockers.append(f"volume below {FILTERS['min_volume']}")

    open_interest = number(row.get("open_interest"))
    if open_interest is None or open_interest < FILTERS["min_open_interest"]:
        blockers.append(f"open interest below {FILTERS['min_open_interest']}")

    dte = number(row.get("dte"))
    if dte is None:
        blockers.append("missing DTE")
    elif dte < FILTERS["min_dte"] or dte > FILTERS["max_dte"]:
        blockers.append(f"DTE outside {FILTERS['min_dte']}-{FILTERS['max_dte']}")

    strike = number(row.get("strike"))
    if strike is None or strike <= 0:
        blockers.append("missing valid strike")

    premium = number(row.get("premium"))
    if premium is None or premium <= 0:
        blockers.append("missing valid premium")

    if yes_value(row.get("earnings_within_window")):
        blockers.append("earnings within risk window")

    status = "contract_pass" if not blockers else "contract_blocked"
    normalized = {
        "contract_symbol": text(row.get("contract_symbol")),
        "option_type": option_type,
        "expiration": text(row.get("expiration")),
        "dte": dte if dte is not None else "",
        "strike": strike if strike is not None else "",
        "delta": delta if delta is not None else "",
        "bid": bid if bid is not None else "",
        "ask": ask if ask is not None else "",
        "mid": round(mid, 4) if mid is not None else "",
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else "",
        "volume": int(volume) if volume is not None else "",
        "open_interest": int(open_interest) if open_interest is not None else "",
        "implied_volatility": number(row.get("implied_volatility")) or "",
        "premium": premium if premium is not None else "",
        "earnings_within_window": yes_value(row.get("earnings_within_window")),
        "notes": text(row.get("notes")),
    }
    return status, not blockers, "pass" if not blockers else "; ".join(blockers), normalized


def gate_row(sample: dict[str, Any], contract: pd.Series | None) -> dict[str, Any]:
    """Build one options contract gate row."""

    template = sample_template_row(sample)
    base = {
        "sample_date": template["sample_date"],
        "entry_time_et": template["entry_time_et"],
        "source_signal_et": text(sample.get("source_signal_et")),
        "candidate_entry_et": text(sample.get("candidate_entry_et")) or text(sample.get("latest_signal_et")),
        "symbol": template["symbol"],
        "setup": template["setup"],
        "direction": template["direction"],
        "strategy_id": template["strategy_id"],
        "variant": text(sample.get("variant")),
        "exit_profile": text(sample.get("exit_profile")),
        "sample_tier": template["sample_tier"],
        "signal_freshness": text(sample.get("signal_freshness")),
        "validation_lane": text(sample.get("validation_lane")) or template["sample_tier"],
        "manual_review_required": bool(sample.get("manual_review_required", True)),
        "counts_toward_30": bool(sample.get("counts_toward_30", False)),
        "counts_toward_live_readiness": bool(sample.get("counts_toward_live_readiness", False)),
        "planned_entry": sample.get("planned_entry", ""),
        "planned_stop": sample.get("planned_stop", ""),
        "planned_target": sample.get("planned_target", ""),
        "suggested_shares": sample.get("suggested_shares", ""),
        "sample_risk_pct": sample.get("sample_risk_pct", ""),
    }
    if contract is None:
        return {
            **base,
            **{column: template[column] for column in CONTRACT_AUDIT_COLUMNS[7:]},
            "contract_gate_status": "missing_contract_review",
            "contract_gate_pass": False,
            "contract_gate_reason": "Add contract details to data/options_contract_audit.csv before confirming this sample.",
        }
    status, passed, reason, normalized = review_contract(contract, template["direction"])
    return {
        **base,
        **normalized,
        "contract_gate_status": status,
        "contract_gate_pass": passed,
        "contract_gate_reason": reason,
    }


def clean_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return JSON-safe records from a DataFrame."""

    if frame.empty:
        return []
    records = []
    for item in frame.to_dict("records"):
        clean = {}
        for key, value in item.items():
            if value is None or pd.isna(value):
                clean[key] = ""
            else:
                clean[key] = value
        records.append(clean)
    return records


def build_gate(
    output_dir: Path = Path("logs"),
    contract_audit_csv: Path | None = None,
    samples_csv: Path | None = None,
    candidate_ledger_csv: Path | None = None,
    account_size: float = 10_000.0,
) -> dict[str, Any]:
    """Build the Options Contract Gate v1 payload."""

    contract_audit_csv = contract_audit_csv or CONTRACT_AUDIT_CSV
    samples_csv = samples_csv or runtime_data_path("paper_validation_samples.csv")
    candidate_ledger_csv = candidate_ledger_csv or runtime_data_path("candidate_window_ledger.csv")
    paper_gate = build_paper_gate_payload(
        output_dir=output_dir,
        scanner_csv=output_dir / "daily_paper_signal_scanner.csv",
        samples_csv=samples_csv,
        account_size=account_size,
        promotion_source="candidate_ledger",
        candidate_ledger_csv=candidate_ledger_csv,
    )
    ready_samples = paper_gate.get("ready_samples", []) if isinstance(paper_gate.get("ready_samples", []), list) else []
    audit = read_csv_or_empty(contract_audit_csv, CONTRACT_AUDIT_COLUMNS)
    lookup = latest_contract_lookup(audit)
    template = pd.DataFrame([sample_template_row(row) for row in ready_samples], columns=CONTRACT_AUDIT_COLUMNS)
    rows = pd.DataFrame(
        [
            gate_row(row, lookup.get(contract_key(sample_template_row(row))))
            for row in ready_samples
        ],
        columns=GATE_COLUMNS,
    )
    passed = rows[rows["contract_gate_pass"].astype(bool)].copy() if not rows.empty else pd.DataFrame(columns=GATE_COLUMNS)
    missing = rows[rows["contract_gate_status"].eq("missing_contract_review")].copy() if not rows.empty else pd.DataFrame()
    blocked = rows[rows["contract_gate_status"].eq("contract_blocked")].copy() if not rows.empty else pd.DataFrame()

    if not ready_samples:
        status = "waiting_for_chart_candidate"
        next_action = "No Paper Gate v2 A/B candidate is ready. Keep scanning."
    elif not passed.empty:
        status = "ready"
        next_action = "Contract gate has pass rows. These can be previewed for official validation import."
    elif not missing.empty and blocked.empty:
        status = "waiting_for_contract_review"
        next_action = "Fill the template with selected contract details, then rerun this gate."
    else:
        status = "blocked"
        next_action = "Selected contracts did not pass V1 quality filters. Choose a cleaner contract or skip."

    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "ready_sample_count": int(len(ready_samples)),
        "passed_contract_count": int(len(passed)),
        "missing_contract_reviews": int(len(missing)),
        "blocked_contract_count": int(len(blocked)),
        "filters": FILTERS,
        "promotion_source": paper_gate.get("promotion_source", "scanner_snapshot"),
        "contract_audit_csv": str(contract_audit_csv),
        "template_csv": str(output_dir / "options_contract_gate_template.csv"),
        "next_action": next_action,
        "guardrail": (
            "Options Contract Gate v1 is manual paper-validation only. It does not request option chains, "
            "place broker orders, create broker alerts, or enable live/real-money trading."
        ),
        "rows": clean_records(rows),
        "passed_samples": clean_records(passed),
        "template_rows": clean_records(template),
    }


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write options contract gate outputs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame(payload["rows"], columns=GATE_COLUMNS)
    template = pd.DataFrame(payload["template_rows"], columns=CONTRACT_AUDIT_COLUMNS)
    (output_dir / "options_contract_gate.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    rows.to_csv(output_dir / "options_contract_gate.csv", index=False)
    template.to_csv(output_dir / "options_contract_gate_template.csv", index=False)
    filter_rows = pd.DataFrame([{"filter": key, "value": value} for key, value in FILTERS.items()])
    (output_dir / "options_contract_gate.md").write_text(
        f"""# Options Contract Gate v1

This report checks whether a manually selected options contract is clean enough
for an official local paper-validation sample.

Important: this does not request option chains, place broker orders, create
broker alerts, or enable live execution.

## Summary

```text
Status: {payload["status"]}
Paper Gate v2 ready samples: {payload["ready_sample_count"]}
Contract pass rows: {payload["passed_contract_count"]}
Missing contract reviews: {payload["missing_contract_reviews"]}
Blocked contracts: {payload["blocked_contract_count"]}
Next action: {payload["next_action"]}
```

## V1 Filters

{markdown_table(filter_rows)}

## Contract Gate Rows

{markdown_table(rows)}

## Manual Contract Template

Fill this template into `{payload["contract_audit_csv"]}`:

{markdown_table(template)}

## Guardrail

```text
{payload["guardrail"]}
```
""",
        encoding="utf-8",
    )


def autonomous_lifecycle_command(args: argparse.Namespace) -> list[str]:
    """Return the command that consumes fresh Contract Gate PASS rows."""

    return [
        sys.executable,
        "run_autonomous_a_tier_lifecycle.py",
        "--output-dir",
        str(args.output_dir),
        "--contract-audit-csv",
        str(args.contract_audit_csv),
        "--samples-csv",
        str(args.samples_csv),
        "--candidate-ledger-csv",
        str(args.candidate_ledger_csv),
        "--account-size",
        str(args.account_size),
    ]


def trigger_autonomous_lifecycle(args: argparse.Namespace, payload: dict[str, Any]) -> bool:
    """Trigger autonomous lifecycle exactly when Contract Gate has pass rows."""

    if args.skip_autonomous_lifecycle:
        return False
    if int(payload.get("passed_contract_count", 0) or 0) < 1:
        return False
    subprocess.run(
        autonomous_lifecycle_command(args),
        cwd=Path(__file__).resolve().parent,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return True


def main() -> None:
    args = parse_args()
    payload = build_gate(
        args.output_dir,
        args.contract_audit_csv,
        args.samples_csv,
        args.candidate_ledger_csv,
        args.account_size,
    )
    write_outputs(args.output_dir, payload)
    lifecycle_triggered = trigger_autonomous_lifecycle(args, payload)
    print(f"Options contract gate: {payload['status']}")
    print(f"Contract pass rows: {payload['passed_contract_count']}")
    print(f"Autonomous lifecycle triggered: {lifecycle_triggered}")
    print(f"Saved {args.output_dir / 'options_contract_gate.md'}")


if __name__ == "__main__":
    main()
