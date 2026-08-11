"""Summarize provider stability after a market-data refresh.

This is a local data-quality audit for the research/paper workflow. It does
not fetch market data, place orders, import paper trades, create alerts, or
connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from config.symbol_playbook import playbook_symbols
from data.market_data_sources import read_sources
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit provider/session stability after refresh.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where workflow outputs live.")
    parser.add_argument("--audit-csv", type=Path, default=Path("data/market_refresh_audit.csv"))
    parser.add_argument("--provider", default="webull", help="Provider used by the refresh workflow.")
    parser.add_argument("--symbols", nargs="+", default=playbook_symbols("approved_plus_watch"))
    parser.add_argument("--refresh-started-at", default="", help="Refresh start timestamp in ET.")
    parser.add_argument("--refresh-ended-at", default="", help="Refresh end timestamp in ET.")
    return parser.parse_args()


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def latest_audit_run(audit: pd.DataFrame) -> pd.DataFrame:
    """Return rows from the latest market-refresh audit event."""

    if audit.empty or "refresh_run_at_et" not in audit.columns:
        return pd.DataFrame()
    latest_run = str(audit["refresh_run_at_et"].dropna().iloc[-1])
    return audit[audit["refresh_run_at_et"].astype(str) == latest_run].copy()


def repair_summary(output_dir: Path) -> dict[str, Any]:
    """Return the latest M30 repair summary."""

    repair = read_csv_or_empty(output_dir / "m30_repair_audit.csv")
    if repair.empty or "status" not in repair.columns:
        return {
            "status": "not_recorded",
            "repaired_symbols": [],
            "message": "No M30 repair audit was recorded for this refresh.",
        }
    repaired = repair[repair["status"].astype(str) == "repaired"]
    symbols = sorted(set(repaired["symbol"].astype(str).str.upper())) if "symbol" in repaired.columns else []
    if symbols:
        return {
            "status": "repair_applied",
            "repaired_symbols": symbols,
            "message": f"M30 repair applied for {', '.join(symbols)}.",
        }
    return {
        "status": "no_repair_needed",
        "repaired_symbols": [],
        "message": "No M30 repair was needed.",
    }


def source_summary(output_dir: Path, symbols: list[str]) -> dict[str, Any]:
    """Summarize latest source metadata for requested M5/M30 streams."""

    sources = read_sources(output_dir / "market_data_sources.csv")
    if sources.empty:
        return {
            "required_rows": len(symbols) * 2,
            "latest_rows": 0,
            "provider_counts": {},
            "status_counts": {},
            "latest_refreshed_at_et": "",
        }

    latest_rows: list[pd.Series] = []
    for symbol in [value.upper() for value in symbols]:
        for timeframe in ["M5", "M30"]:
            matches = sources[
                sources["symbol"].astype(str).str.upper().eq(symbol)
                & sources["timeframe"].astype(str).str.upper().eq(timeframe)
            ]
            if not matches.empty:
                latest_rows.append(matches.iloc[-1])

    latest = pd.DataFrame(latest_rows)
    if latest.empty:
        return {
            "required_rows": len(symbols) * 2,
            "latest_rows": 0,
            "provider_counts": {},
            "status_counts": {},
            "latest_refreshed_at_et": "",
        }

    provider_counts = latest.groupby("provider").size().to_dict() if "provider" in latest.columns else {}
    status_counts = latest.groupby("status").size().to_dict() if "status" in latest.columns else {}
    latest_refreshed = str(latest["refreshed_at_et"].dropna().iloc[-1]) if "refreshed_at_et" in latest.columns else ""
    return {
        "required_rows": len(symbols) * 2,
        "latest_rows": int(len(latest)),
        "provider_counts": {str(key): int(value) for key, value in provider_counts.items()},
        "status_counts": {str(key): int(value) for key, value in status_counts.items()},
        "latest_refreshed_at_et": latest_refreshed,
    }


def build_provider_stability_audit(
    *,
    output_dir: Path = Path("logs"),
    audit_csv: Path = Path("data/market_refresh_audit.csv"),
    provider: str = "webull",
    symbols: list[str] | None = None,
    refresh_started_at: str = "",
    refresh_ended_at: str = "",
) -> dict[str, Any]:
    """Build a compact stability payload from existing refresh evidence."""

    requested_symbols = [value.upper() for value in (symbols or playbook_symbols("approved_plus_watch"))]
    audit = latest_audit_run(read_csv_or_empty(audit_csv))
    repair = repair_summary(output_dir)
    sources = source_summary(output_dir, requested_symbols)

    if audit.empty:
        return {
            "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
            "status": "not_recorded",
            "provider": provider,
            "refresh_started_at_et": refresh_started_at,
            "refresh_ended_at_et": refresh_ended_at,
            "latest_refresh_run_at_et": "",
            "requested_symbols": requested_symbols,
            "evidence_counts": {},
            "mismatch_symbols": [],
            "failed_symbols": [],
            "repair": repair,
            "source_summary": sources,
            "network_note": "No public IP or VPN state is recorded; this audit verifies provider output consistency.",
            "next_action": "Run the market-data refresh workflow so provider/session evidence can be recorded.",
        }

    evidence_counts = (
        audit["refresh_evidence_status"].astype(str).value_counts().to_dict()
        if "refresh_evidence_status" in audit.columns
        else {}
    )
    mismatch = audit[
        audit.get("refresh_evidence_status", pd.Series(dtype=str)).astype(str) == "timeframe_session_mismatch"
    ]
    failed = audit[
        audit.get("refresh_evidence_status", pd.Series(dtype=str)).astype(str) == "failed_or_missing_file"
    ]
    mismatch_symbols = sorted(set(mismatch["symbol"].astype(str).str.upper())) if "symbol" in mismatch.columns else []
    failed_symbols = sorted(set(failed["symbol"].astype(str).str.upper())) if "symbol" in failed.columns else []
    repair_applied = repair.get("status") == "repair_applied"

    if failed_symbols:
        status = "blocked"
        next_action = "Provider refresh left failed or missing candle files. Refresh again before paper review."
    elif mismatch_symbols and repair_applied:
        status = "watch"
        next_action = "M5/M30 mismatch was repaired. Usable, but keep watching for repeated provider lag."
    elif mismatch_symbols:
        status = "blocked"
        next_action = "M5/M30 sessions disagree and were not repaired. Refresh again before paper review."
    else:
        status = "stable"
        next_action = "Provider/session evidence is stable for the latest refresh."

    latest_run = str(audit["refresh_run_at_et"].dropna().iloc[-1]) if "refresh_run_at_et" in audit.columns else ""
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "provider": provider,
        "refresh_started_at_et": refresh_started_at,
        "refresh_ended_at_et": refresh_ended_at,
        "latest_refresh_run_at_et": latest_run,
        "requested_symbols": requested_symbols,
        "evidence_counts": {str(key): int(value) for key, value in evidence_counts.items()},
        "mismatch_symbols": mismatch_symbols,
        "failed_symbols": failed_symbols,
        "repair": repair,
        "source_summary": sources,
        "network_note": "No public IP or VPN state is recorded; this audit verifies provider output consistency.",
        "next_action": next_action,
    }


def write_reports(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON and Markdown reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "provider_stability_audit.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    evidence = pd.DataFrame(
        [{"status": key, "symbol_checks": value} for key, value in payload.get("evidence_counts", {}).items()]
    )
    summary = pd.DataFrame(
        [
            {
                "status": payload.get("status", "unknown"),
                "provider": payload.get("provider", "unknown"),
                "started": payload.get("refresh_started_at_et", ""),
                "ended": payload.get("refresh_ended_at_et", ""),
                "latest_audit": payload.get("latest_refresh_run_at_et", ""),
                "mismatch_symbols": ", ".join(payload.get("mismatch_symbols", [])),
                "failed_symbols": ", ".join(payload.get("failed_symbols", [])),
                "repair_status": payload.get("repair", {}).get("status", "unknown"),
                "source_rows": payload.get("source_summary", {}).get("latest_rows", 0),
            }
        ]
    )
    (output_dir / "provider_stability_audit.md").write_text(
        f"""# Provider Stability Audit

This report summarizes the latest market-data refresh evidence. It is local
data-quality visibility only and does not fetch data, place orders, import
paper trades, create alerts, or connect to broker execution.

## Summary

{markdown_table(summary)}

## Evidence Counts

{markdown_table(evidence)}

## Network Note

```text
{payload.get("network_note", "")}
```

## Next Action

```text
{payload.get("next_action", "")}
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_provider_stability_audit(
        output_dir=args.output_dir,
        audit_csv=args.audit_csv,
        provider=args.provider,
        symbols=args.symbols,
        refresh_started_at=args.refresh_started_at,
        refresh_ended_at=args.refresh_ended_at,
    )
    write_reports(args.output_dir, payload)
    print(f"Provider stability audit: {payload['status']}")
    print(f"Saved provider stability audit: {args.output_dir / 'provider_stability_audit.md'}")


if __name__ == "__main__":
    main()
