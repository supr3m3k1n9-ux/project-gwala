"""Build one pre-market verification report for the paper workflow.

This command rebuilds local safety/readiness reports and can optionally make
one Webull market-data-only probe request. It never imports paper trades,
creates alerts, or connects to order execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd

from run_data_integrity import coverage_is_issue
from run_playbook import markdown_table
from run_readiness_check import env_has_webull_keys


LOCAL_REPORT_COMMANDS = [
    "run_data_integrity.py",
    "run_refresh_status.py",
    "run_system_state.py",
    "run_readiness_check.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Project Gwala pre-market verification report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Local Webull environment file.")
    parser.add_argument(
        "--probe-webull",
        action="store_true",
        help="Run one data-only SPY M5 Webull access probe and save separate probe files.",
    )
    parser.add_argument(
        "--webull-python",
        type=Path,
        default=Path(".venv-webull/bin/python"),
        help="Python interpreter that has the Webull SDK installed.",
    )
    parser.add_argument("--probe-symbol", default="SPY", help="Symbol for the optional Webull probe.")
    parser.add_argument("--probe-count", type=int, default=5, help="Small candle count for the optional probe.")
    return parser.parse_args()


def run_local_reports(output_dir: Path) -> None:
    """Refresh derived reports needed by the verification summary."""

    for script in LOCAL_REPORT_COMMANDS:
        subprocess.run(
            [sys.executable, script, "--output-dir", str(output_dir)],
            check=True,
        )


def run_webull_probe(args: argparse.Namespace, previous_verification: dict[str, Any] | None = None) -> dict[str, str]:
    """Run an explicitly requested market-data-only probe."""

    if not args.probe_webull:
        previous_probe = (previous_verification or {}).get("probe", {})
        if previous_probe.get("status") in {"pass", "previous_pass"}:
            return {
                "status": "previous_pass",
                "detail": "Most recent recorded data-only Webull probe passed; no new request was made.",
            }
        return {
            "status": "not_requested",
            "detail": "Optional data-only Webull probe was not requested.",
        }
    if not args.webull_python.exists():
        return {
            "status": "fail",
            "detail": f"Webull Python interpreter not found: {args.webull_python}.",
        }

    probe_dir = args.output_dir / "premarket_probe"
    command = [
        str(args.webull_python),
        "tools/check_webull_data.py",
        "--symbol",
        args.probe_symbol.upper(),
        "--timespan",
        "M5",
        "--count",
        str(args.probe_count),
        "--output-dir",
        str(probe_dir),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        return {
            "status": "fail",
            "detail": "Data-only Webull probe failed. Review terminal-safe probe output and quote permissions.",
        }
    if "HTTP status: 200" not in completed.stdout:
        return {
            "status": "fail",
            "detail": "Data-only Webull probe did not report HTTP 200.",
        }
    return {
        "status": "pass",
        "detail": f"Data-only Webull probe succeeded for {args.probe_symbol.upper()} M5; outputs saved under {probe_dir}.",
    }


def read_json(path: Path) -> dict[str, Any]:
    """Read a generated JSON report."""

    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    """Read a generated CSV report when available."""

    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_checks(args: argparse.Namespace, probe: dict[str, str]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Gather the local pre-market gate checks."""

    refresh = read_json(args.output_dir / "refresh_status.json")
    state = read_json(args.output_dir / "system_state.json")
    integrity = read_csv(args.output_dir / "candle_data_integrity.csv")
    integrity_issues = 0
    if not integrity.empty:
        issues = integrity.apply(lambda row: coverage_is_issue(row["status"], row["session_coverage"]), axis=1)
        integrity_issues = int(issues.sum())

    safety = state.get("safety", {})
    safety_ok = (
        safety.get("live_trading_enabled") is False
        and safety.get("broker_order_execution_enabled") is False
        and safety.get("real_money_ready") is False
    )
    paper_blocked = refresh.get("paper_import_blocked") is True
    credentials_ok = env_has_webull_keys(args.env_file)

    checks = [
        {
            "area": "Webull credentials",
            "status": "pass" if credentials_ok else "fail",
            "detail": "Credential names and non-empty values detected; values not printed."
            if credentials_ok
            else "WEBULL_APP_KEY and WEBULL_APP_SECRET were not detected.",
        },
        {
            "area": "Webull data-only access",
            "status": probe["status"],
            "detail": probe["detail"],
        },
        {
            "area": "Candle integrity",
            "status": "pass" if integrity_issues == 0 else "fail",
            "detail": f"{integrity_issues} local candle integrity warning(s) found.",
        },
        {
            "area": "Safety flags",
            "status": "pass" if safety_ok else "fail",
            "detail": "Live trading, broker execution, and real-money readiness remain disabled."
            if safety_ok
            else "Safety flags are not in the expected disabled state.",
        },
        {
            "area": "Paper import gate",
            "status": "pass" if paper_blocked else "review",
            "detail": "Paper import is blocked pending fresh reviewed candidates."
            if paper_blocked
            else "Current candidates may exist; manually review before any paper import.",
        },
        {
            "area": "Next action",
            "status": refresh.get("status", "missing"),
            "detail": str(refresh.get("next_action", "Refresh status output is missing.")),
        },
    ]
    summary = {
        "refresh_status": refresh,
        "system_state": state,
        "integrity_issues": integrity_issues,
        "probe": probe,
    }
    return checks, summary


def write_report(path: Path, checks: list[dict[str, str]], summary: dict[str, Any]) -> None:
    """Write the single pre-market pass/fail report."""

    hard_failures = [check for check in checks if check["status"] == "fail"]
    refresh = summary["refresh_status"]
    state = summary["system_state"]
    if hard_failures:
        verdict = "Not ready for the next paper workflow session. Fix failed checks first."
    elif summary["probe"]["status"] == "not_requested":
        verdict = "Local safeguards pass. Run the optional data-only Webull probe before the next session workflow."
    elif summary["probe"]["status"] == "previous_pass":
        verdict = "Local safeguards pass. The most recent recorded Webull data-only probe previously passed."
    else:
        verdict = "Pre-market verification passes. Keep paper import blocked until fresh reviewed candidates exist."

    path.write_text(
        f"""# Pre-Market Verification

This is a single readiness summary for the Project Gwala research and paper
workflow. It does not place orders, import paper trades, create alerts, or
connect to broker execution.

## Verdict

```text
{verdict}
```

## Checks

{markdown_table(pd.DataFrame(checks))}

## Session State

{markdown_table(pd.DataFrame([
    {"field": "project_phase", "value": state.get("project_phase", "missing")},
    {"field": "data_status", "value": state.get("data_freshness", {}).get("data_status", "missing")},
    {"field": "latest_scanner_session", "value": state.get("data_freshness", {}).get("latest_scanner_session", "missing")},
    {"field": "current_candidate_count", "value": state.get("scanner", {}).get("current_candidate_count", 0)},
    {"field": "paper_import_blocked", "value": refresh.get("paper_import_blocked", "missing")},
    {"field": "next_market_session", "value": refresh.get("market", {}).get("next_market_session", "missing")},
]))}

## Next-Session Operating Rule

```text
Use fresh current-session data and manually review a qualifying candidate
before importing any paper trade. Live trading and broker execution stay off.
```

## Commands

Local-only check:

```bash
.venv/bin/python run_premarket_verification.py
```

Optional Webull data-only access check:

```bash
.venv/bin/python run_premarket_verification.py --probe-webull
```

During the next regular market session:

```bash
source .venv-webull/bin/activate
python run_daily_workflow.py --refresh-data
```
""",
        encoding="utf-8",
    )


def has_failed_checks(checks: list[dict[str, str]]) -> bool:
    """Return whether any required pre-market check failed."""

    return any(check["status"] == "fail" for check in checks)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    previous_verification = read_json(args.output_dir / "premarket_verification.json")
    run_local_reports(args.output_dir)
    probe = run_webull_probe(args, previous_verification)
    checks, summary = build_checks(args, probe)
    json_path = args.output_dir / "premarket_verification.json"
    report_path = args.output_dir / "premarket_verification.md"
    json_path.write_text(json.dumps({"checks": checks, **summary}, indent=2), encoding="utf-8")
    write_report(report_path, checks, summary)
    # Keep the app-ready state synchronized with the verification result just written.
    subprocess.run([sys.executable, "run_system_state.py", "--output-dir", str(args.output_dir)], check=True)
    for check in checks:
        print(f"{check['area']}: {check['status']}")
    print(f"Saved pre-market verification JSON: {json_path}")
    print(f"Saved pre-market verification report: {report_path}")
    if has_failed_checks(checks):
        raise SystemExit("Pre-market verification has failed checks. Review the report before the next session.")


if __name__ == "__main__":
    main()
