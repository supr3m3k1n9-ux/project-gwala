"""Validate dashboard data before trusting the app.

This is a local research/paper guardrail. It checks that the app-facing JSON is
strict browser-safe, that refresh reports exist, and that market-hours candles
are not silently stale. It does not fetch data, place orders, import paper
trades, create broker alerts, or connect to broker execution.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from run_playbook import markdown_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dashboard data preflight checks.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    return parser.parse_args()


def reject_json_constant(value: str) -> None:
    """Reject NaN/Infinity values that browsers cannot parse."""

    raise ValueError(f"Non-standard JSON constant is not allowed: {value}")


def read_strict_json(path: Path) -> tuple[dict[str, Any], str]:
    """Read JSON exactly the way the dashboard needs it: strict and finite."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_json_constant)
    except FileNotFoundError:
        return {}, f"{path} does not exist."
    except (json.JSONDecodeError, ValueError) as error:
        return {}, str(error)
    if not isinstance(payload, dict):
        return {}, f"{path} did not contain a JSON object."
    problem = first_non_finite_path(payload)
    if problem:
        return {}, f"{path} contains a non-finite number at {problem}."
    return payload, ""


def first_non_finite_path(value: Any, path: str = "$") -> str:
    """Return the first NaN/Infinity path inside nested data, if any."""

    if isinstance(value, dict):
        for key, item in value.items():
            problem = first_non_finite_path(item, f"{path}.{key}")
            if problem:
                return problem
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problem = first_non_finite_path(item, f"{path}[{index}]")
            if problem:
                return problem
    elif isinstance(value, float) and not math.isfinite(value):
        return path
    return ""


def check_row(area: str, status: str, detail: str, action: str = "") -> dict[str, str]:
    """Build one report row."""

    return {"area": area, "status": status, "detail": detail, "action": action}


def build_checks(output_dir: Path) -> dict[str, Any]:
    """Build dashboard/data preflight checks from saved workflow outputs."""

    system_state, system_error = read_strict_json(output_dir / "system_state.json")
    refresh_status, refresh_error = read_strict_json(output_dir / "refresh_status.json")
    rows: list[dict[str, str]] = []

    if system_error:
        rows.append(
            check_row(
                "System state JSON",
                "fail",
                system_error,
                "Run python run_system_state.py. If it still fails, inspect non-finite metrics.",
            )
        )
    else:
        generated_at = system_state.get("app_health", {}).get("generated_at_et", "unknown")
        rows.append(check_row("System state JSON", "pass", f"Strict JSON is valid. Generated {generated_at}."))

    if refresh_error:
        rows.append(
            check_row(
                "Refresh status JSON",
                "fail",
                refresh_error,
                "Run python run_refresh_status.py, then rebuild system state.",
            )
        )
    else:
        status = str(refresh_status.get("status", "unknown"))
        rows.append(check_row("Refresh status JSON", "pass", f"Strict JSON is valid. Status: {status}."))

    market = refresh_status.get("market", {}) if refresh_status else {}
    market_open = bool(market.get("market_is_open"))
    provider = refresh_status.get("provider_refresh", {}) if refresh_status else {}
    freshness = refresh_status.get("candle_freshness", {}) if refresh_status else {}
    scanner = refresh_status.get("scanner", {}) if refresh_status else {}

    if refresh_status:
        provider_status = str(provider.get("status", "unknown"))
        if market_open and provider_status != "current_session_bars":
            rows.append(
                check_row(
                    "Provider refresh",
                    "fail",
                    f"Market is open but provider status is {provider_status}.",
                    "Run python run_daily_workflow.py --refresh-data --data-provider webull.",
                )
            )
        else:
            rows.append(
                check_row(
                    "Provider refresh",
                    "pass",
                    f"Provider {provider.get('provider', 'unknown')} status: {provider_status}.",
                )
            )

        stale_m5 = freshness.get("stale_m5_symbols", []) or []
        stale_m30 = freshness.get("stale_m30_symbols", []) or []
        unknown = freshness.get("unknown_symbols", []) or []
        if market_open and (stale_m5 or stale_m30 or unknown):
            rows.append(
                check_row(
                    "Candle freshness",
                    "fail",
                    f"Stale M5: {stale_m5}; stale M30: {stale_m30}; unknown: {unknown}.",
                    "Refresh Webull data before reviewing candidates.",
                )
            )
        else:
            rows.append(
                check_row(
                    "Candle freshness",
                    "pass",
                    f"Status: {freshness.get('status', 'unknown')}; stale symbols: none blocking.",
                )
            )

        if market_open and int(scanner.get("current_candidate_count", 0) or 0) < int(
            scanner.get("allowed_current_candidate_count", 0) or 0
        ):
            rows.append(
                check_row(
                    "Candidate sync",
                    "warn",
                    "Allowed current-candle count is higher than total current-candidate count.",
                    "Rebuild scanner, sizing, refresh status, and system state.",
                )
            )
        else:
            rows.append(
                check_row(
                    "Candidate sync",
                    "pass",
                    (
                        f"Scanner session {scanner.get('latest_scanner_session', 'unknown')}; "
                        f"current candidates {scanner.get('current_candidate_count', 0)}."
                    ),
                )
            )

    fail_count = sum(1 for row in rows if row["status"] == "fail")
    warn_count = sum(1 for row in rows if row["status"] == "warn")
    status = "fail" if fail_count else "warn" if warn_count else "pass"
    return {
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "checks": rows,
        "guardrail": "Local dashboard/data preflight only. No broker actions or paper imports.",
    }


def write_reports(output_dir: Path, payload: dict[str, Any]) -> None:
    """Write JSON and Markdown preflight reports."""

    json_path = output_dir / "dashboard_data_preflight.json"
    md_path = output_dir / "dashboard_data_preflight.md"
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    checks = pd.DataFrame(payload["checks"])
    md_path.write_text(
        f"""# Dashboard Data Preflight

This validates whether the dashboard can trust the app-facing data contract.

Important: this is research/paper workflow only. It does not fetch data, place
orders, import paper trades, create broker alerts, or connect to broker
execution.

## Status

```text
{payload["status"]}
```

## Checks

{markdown_table(checks)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
logs/dashboard_data_preflight.json
logs/dashboard_data_preflight.md
```
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_checks(args.output_dir)
    write_reports(args.output_dir, payload)
    print(f"Dashboard data preflight: {payload['status']}")
    print("Saved dashboard data preflight report: " f"{args.output_dir / 'dashboard_data_preflight.md'}")
    if payload["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
