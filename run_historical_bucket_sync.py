"""Audit historical simulator bucket freshness.

This is a local research/data-sync guardrail. It checks whether the historical
simulator's source buckets are aligned with the latest scanner session and can
optionally rebuild the research snapshot that feeds Promotion Review.

It does not fetch market data, import paper trades, place orders, create
alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_app import SIMULATION_BUCKET_LABELS, build_backtest_portfolio_simulation
from run_playbook import markdown_table


REQUIRED_BUCKETS = ("Approved Playbook", "Promotion Review", "Strategy Vault Research")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit historical simulator bucket freshness.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where report files are saved.")
    parser.add_argument(
        "--rebuild-research-snapshot",
        action="store_true",
        help="Rebuild research confidence, promotion review, and strategy vault before auditing buckets.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when the historical bucket contract is blocked.",
    )
    return parser.parse_args()


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty dict."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    """Read a CSV or return an empty frame."""

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def latest_scanner_session(output_dir: Path) -> str:
    """Return the latest scanner session known to the app."""

    refresh = read_json_or_empty(output_dir / "refresh_status.json")
    refresh_scanner = refresh.get("scanner", {}) if isinstance(refresh.get("scanner"), dict) else {}
    if refresh_scanner.get("latest_scanner_session"):
        return str(refresh_scanner["latest_scanner_session"])

    system = read_json_or_empty(output_dir / "system_state.json")
    freshness = system.get("data_freshness", {}) if isinstance(system.get("data_freshness"), dict) else {}
    if freshness.get("latest_scanner_session"):
        return str(freshness["latest_scanner_session"])

    scanner = read_csv_or_empty(output_dir / "daily_paper_signal_scanner.csv")
    if not scanner.empty and "scan_date" in scanner.columns:
        values = sorted(str(value) for value in scanner["scan_date"].dropna().unique())
        if values:
            return values[-1]
    return "unknown"


def provider_label(output_dir: Path) -> str:
    """Return the latest provider recorded in refresh status."""

    refresh = read_json_or_empty(output_dir / "refresh_status.json")
    provider = refresh.get("provider_refresh", {}) if isinstance(refresh.get("provider_refresh"), dict) else {}
    return str(provider.get("provider", "unknown") or "unknown")


def bucket_status(last_entry: str, target_session: str) -> str:
    """Classify one historical source bucket against the scanner session."""

    if not last_entry:
        return "missing"
    if not target_session or target_session == "unknown":
        return "loaded"
    if last_entry < target_session:
        return "behind"
    return "current"


def rebuild_research_snapshot(output_dir: Path, python: str = sys.executable) -> list[dict[str, str]]:
    """Run the lightweight historical research snapshot rebuild commands."""

    research_dir = output_dir / "universe_expansion"
    commands = [
        [python, "run_research_confidence.py", "--output-dir", str(research_dir)],
        [python, "run_promotion_review.py", "--output-dir", str(output_dir), "--research-dir", str(research_dir)],
        [python, "run_strategy_vault.py", "--output-dir", str(output_dir)],
    ]
    results = []
    for command in commands:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = "\n".join(part.strip() for part in [completed.stdout, completed.stderr] if part.strip())
        results.append({"command": " ".join(command), "status": "ok", "output": output})
    return results


def build_historical_bucket_sync(
    output_dir: Path = Path("logs"),
    *,
    rebuild_research: bool = False,
) -> dict[str, Any]:
    """Build the historical simulator bucket-sync payload."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rebuild_results: list[dict[str, str]] = []
    if rebuild_research:
        rebuild_results = rebuild_research_snapshot(output_dir)

    target_session = latest_scanner_session(output_dir)
    provider = provider_label(output_dir)
    try:
        rows, account = build_backtest_portfolio_simulation(output_dir, risk_model="tiered")
        timelines = account.get("source_bucket_timelines", {})
        build_error = ""
    except Exception as error:  # pragma: no cover - exercised through status payload, not terminal trace
        rows = pd.DataFrame()
        account = {}
        timelines = {}
        build_error = str(error)

    bucket_rows: list[dict[str, Any]] = []
    for bucket in REQUIRED_BUCKETS:
        lane = timelines.get(bucket, {}) if isinstance(timelines, dict) else {}
        last_entry = str(lane.get("last_entry", "") or "")
        status = bucket_status(last_entry, target_session)
        bucket_rows.append(
            {
                "bucket": bucket,
                "status": status,
                "row_count": int(lane.get("row_count", 0) or 0),
                "first_entry": str(lane.get("first_entry", "") or ""),
                "last_entry": last_entry,
                "active_trade_dates": int(lane.get("active_trade_dates", 0) or 0),
                "active_months": int(lane.get("active_months", 0) or 0),
                "latest_symbol": str(lane.get("latest_symbol", "") or ""),
                "latest_setup": str(lane.get("latest_setup", "") or ""),
                "latest_candidate": str(lane.get("latest_candidate", "") or ""),
                "latest_trade_log": str(lane.get("latest_trade_log", "") or ""),
                "source_category": SIMULATION_BUCKET_LABELS[bucket]["source_category"],
            }
        )

    missing = [row["bucket"] for row in bucket_rows if row["status"] == "missing"]
    behind = [row["bucket"] for row in bucket_rows if row["status"] == "behind"]
    current = [row["bucket"] for row in bucket_rows if row["status"] == "current"]
    loaded = [row["bucket"] for row in bucket_rows if row["status"] == "loaded"]
    unified_last_entry = str(account.get("timeline", {}).get("last_entry", "") or "")
    unified_status = bucket_status(unified_last_entry, target_session)

    if build_error or missing:
        status = "blocked"
        next_action = (
            "Historical simulator inputs are missing. Rebuild the full daily research workflow, then rerun "
            "python run_historical_bucket_sync.py --output-dir logs."
        )
    elif behind:
        status = "watch"
        next_action = (
            "Historical simulator is usable with source-lane warnings. Rebuild the stale bucket producers after close "
            f"or treat {', '.join(behind)} as older research context."
        )
    elif loaded:
        status = "loaded"
        next_action = "Scanner session is unknown. Rebuild refresh status before judging historical freshness."
    else:
        status = "synced"
        next_action = "Historical simulator buckets are aligned with the latest scanner session."

    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "target_scanner_session": target_session,
        "provider": provider,
        "unified_last_entry": unified_last_entry,
        "unified_status": unified_status,
        "total_simulated_rows": int(len(rows)),
        "source_files": int(account.get("source_files", 0) or 0),
        "required_buckets": list(REQUIRED_BUCKETS),
        "current_buckets": current,
        "behind_buckets": behind,
        "missing_buckets": missing,
        "loaded_buckets": loaded,
        "bucket_rows": bucket_rows,
        "rebuild_ran": bool(rebuild_research),
        "rebuild_results": rebuild_results,
        "build_error": build_error,
        "next_action": next_action,
        "guardrail": "Historical bucket sync is observability only. It does not fetch broker data, place orders, or count paper trades.",
    }


def write_reports(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON and Markdown historical bucket sync reports."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "historical_bucket_sync.json"
    md_path = output_dir / "historical_bucket_sync.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    bucket_frame = pd.DataFrame(payload["bucket_rows"])
    md_path.write_text(
        f"""# Historical Bucket Sync

This report checks whether the buckets behind the historical simulation account
are aligned with the latest scanner session.

Important: this is observability only. It does not fetch broker data, import
paper trades, place orders, create alerts, or enable live execution.

## Summary

```text
Status: {payload["status"]}
Target scanner session: {payload["target_scanner_session"]}
Provider: {payload["provider"]}
Unified simulator through: {payload["unified_last_entry"] or "unknown"}
Simulated rows: {payload["total_simulated_rows"]}
Rebuild ran: {payload["rebuild_ran"]}
```

## Bucket Status

{markdown_table(bucket_frame)}

## Next Action

{payload["next_action"]}

## Files

```text
logs/historical_bucket_sync.json
logs/historical_bucket_sync.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    payload = build_historical_bucket_sync(args.output_dir, rebuild_research=args.rebuild_research_snapshot)
    write_reports(args.output_dir, payload)
    if args.strict and payload["status"] == "blocked":
        raise SystemExit(1)
    print(f"Saved historical bucket sync: {args.output_dir / 'historical_bucket_sync.md'}")


if __name__ == "__main__":
    main()
