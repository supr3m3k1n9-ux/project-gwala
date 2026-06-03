"""Build a compact timeline for the autonomous paper workflow.

This report makes the launchd automation diagnosable without reading the raw
log wall. It is status-only: it does not fetch market data, place orders,
create broker alerts, import paper trades, or change strategy rules.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_calendar import MARKET_TZ
from reports.system_state import file_state
from run_playbook import markdown_table


LOG_COMMAND_PREFIX = "=== "


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the daily automation timeline report.")
    parser.add_argument("--output-dir", type=Path, default=Path("logs"), help="Where reports are saved.")
    parser.add_argument("--tail-lines", type=int, default=220, help="How many raw log lines to inspect.")
    return parser.parse_args()


def now_et() -> datetime:
    """Return the current New York time."""

    return datetime.now(MARKET_TZ)


def read_json_or_empty(path: Path) -> dict[str, Any]:
    """Read a JSON object if it exists."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_tail(path: Path, limit: int) -> list[str]:
    """Read the last limit lines from a text file."""

    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def command_name(line: str) -> str:
    """Extract a command name from a launchd command block."""

    cleaned = line.strip().strip("=")
    parts = cleaned.split()
    for part in parts:
        if part.endswith(".py"):
            return Path(part).name
    return cleaned


def recent_commands(lines: list[str], count: int = 12) -> list[dict[str, str]]:
    """Return recent command blocks from the autonomous log tail."""

    commands: list[dict[str, str]] = []
    for line in lines:
        if line.startswith(LOG_COMMAND_PREFIX):
            commands.append({"command": command_name(line), "raw": line.strip()})
    return commands[-count:]


def recent_failures(out_lines: list[str], err_lines: list[str], count: int = 10) -> list[dict[str, str]]:
    """Return likely failure lines from stdout/stderr tails."""

    markers = ("error", "failed", "traceback", "exception", "no such file", "permission denied")
    rows: list[dict[str, str]] = []
    for source, lines in [("stdout", out_lines), ("stderr", err_lines)]:
        for line in lines:
            lower = line.lower()
            if any(marker in lower for marker in markers):
                rows.append({"source": source, "message": line.strip()})
    return rows[-count:]


def status_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Build high-signal status rows from structured reports."""

    autonomous = payload["autonomous_status"]
    watchdog = payload["morning_watchdog"]
    digest = payload["post_scan_digest"]
    return [
        {
            "area": "Autonomous status",
            "status": str(autonomous.get("decision") or autonomous.get("latest_action") or "missing"),
            "detail": str(autonomous.get("message") or autonomous.get("generated_at_et") or "No JSON status yet."),
        },
        {
            "area": "Morning watchdog",
            "status": str(watchdog.get("status", "missing")),
            "detail": str(watchdog.get("headline", "No watchdog status yet.")),
        },
        {
            "area": "Post-scan digest",
            "status": str(digest.get("action", "missing")),
            "detail": str(digest.get("headline", "No post-scan digest yet.")),
        },
        {
            "area": "Next action",
            "status": "guidance",
            "detail": str(digest.get("next_action") or watchdog.get("next_action") or "Run the scheduled workflow or refresh reports."),
        },
    ]


def timeline_verdict(payload: dict[str, Any], failures: list[dict[str, str]]) -> tuple[str, str]:
    """Return timeline status and headline."""

    watchdog_status = str(payload["morning_watchdog"].get("status", "missing"))
    digest_action = str(payload["post_scan_digest"].get("action", "missing"))
    if failures:
        return "warn", "Recent automation logs contain possible errors or failures."
    if watchdog_status == "pass" and digest_action == "review_candidate":
        return "action_needed", "Automation ran and a candidate needs manual review."
    if watchdog_status == "pass":
        return "pass", "Automation is confirmed for today."
    if watchdog_status == "pending":
        return "pending", "Automation is not due yet or the first scan has not finished."
    if watchdog_status == "warn":
        return "warn", "Automation needs attention today."
    return "unknown", "Automation has not written enough structured status yet."


def build_timeline(output_dir: Path, *, moment: datetime | None = None, tail_lines: int = 220) -> dict[str, Any]:
    """Build the automation timeline payload from structured and raw logs."""

    current_time = moment or now_et()
    autonomous_json = output_dir / "autonomous_paper_workflow_status.json"
    out_log = output_dir / "autonomous_paper_workflow.launchd.out.log"
    err_log = output_dir / "autonomous_paper_workflow.launchd.err.log"
    payload = {
        "generated_at_et": current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "timeline_date": str(current_time.date()),
        "autonomous_status": read_json_or_empty(autonomous_json),
        "morning_watchdog": read_json_or_empty(output_dir / "morning_run_watchdog.json"),
        "post_scan_digest": read_json_or_empty(output_dir / "post_scan_digest.json"),
        "files": {
            "autonomous_status_json": file_state(autonomous_json),
            "autonomous_status_md": file_state(output_dir / "autonomous_paper_workflow_status.md"),
            "launchd_stdout": file_state(out_log),
            "launchd_stderr": file_state(err_log),
            "morning_watchdog_json": file_state(output_dir / "morning_run_watchdog.json"),
            "post_scan_digest_json": file_state(output_dir / "post_scan_digest.json"),
            "daily_workflow_summary": file_state(output_dir / "daily_workflow_summary.md"),
        },
    }
    out_lines = read_tail(out_log, tail_lines)
    err_lines = read_tail(err_log, tail_lines)
    failures = recent_failures(out_lines, err_lines)
    status, headline = timeline_verdict(payload, failures)
    payload.update(
        {
            "status": status,
            "headline": headline,
            "recent_commands": recent_commands(out_lines),
            "recent_failures": failures,
            "guardrail": (
                "Automation timeline is status-only. It does not fetch data, place orders, "
                "create broker alerts, import paper trades, or change strategy rules."
            ),
        }
    )
    return payload


def write_report(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write the timeline JSON and Markdown report."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "daily_automation_timeline.json"
    md_path = output_dir / "daily_automation_timeline.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    status_frame = pd.DataFrame(status_rows(payload))
    command_frame = pd.DataFrame(payload["recent_commands"])
    failure_frame = pd.DataFrame(payload["recent_failures"])
    file_frame = pd.DataFrame(
        [
            {
                "file": name,
                "exists": state.get("exists", False),
                "modified_et": state.get("modified_et", ""),
                "size_bytes": state.get("size_bytes", 0),
            }
            for name, state in payload["files"].items()
        ]
    )

    md_path.write_text(
        f"""# Daily Automation Timeline

This report summarizes the autonomous paper workflow without requiring you to
read raw LaunchAgent logs.

Important: this is status-only. It does not fetch data, place orders, create
broker alerts, import paper trades, or change scanner rules.

## Verdict

```text
{payload["status"]}: {payload["headline"]}
```

## Structured Status

{markdown_table(status_frame)}

## Recent Commands

{markdown_table(command_frame)}

## Recent Possible Failures

{markdown_table(failure_frame)}

## File Health

{markdown_table(file_frame)}

## Guardrail

```text
{payload["guardrail"]}
```

## Files

```text
logs/daily_automation_timeline.json
logs/daily_automation_timeline.md
logs/autonomous_paper_workflow.launchd.out.log
logs/autonomous_paper_workflow.launchd.err.log
logs/autonomous_paper_workflow_status.json
logs/morning_run_watchdog.json
logs/post_scan_digest.json
```
""",
        encoding="utf-8",
    )
    return json_path, md_path


def main() -> None:
    args = parse_args()
    payload = build_timeline(args.output_dir, tail_lines=args.tail_lines)
    json_path, md_path = write_report(payload, args.output_dir)
    print(f"Saved automation timeline JSON: {json_path}")
    print(f"Saved automation timeline report: {md_path}")


if __name__ == "__main__":
    main()
