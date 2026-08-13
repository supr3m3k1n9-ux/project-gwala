#!/usr/bin/env python3
"""Write host systemd health for Dockerized Project Gwala heartbeat checks.

Run this on the Ubuntu host, not inside the Gwala container. It only reads
systemd unit state and writes a JSON artifact for the container to consume.
It does not enable, disable, start, stop, or reload any units.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
from typing import Any
from zoneinfo import ZoneInfo


MARKET_TZ = ZoneInfo("America/New_York")
DEFAULT_UNITS = [
    "project-gwala-dashboard.service",
    "project-gwala-autonomous-paper.service",
    "project-gwala-autonomous-paper.timer",
    "project-gwala-market-async-lane.service",
    "project-gwala-market-async-lane.timer",
    "project-gwala-production-alert.service",
    "project-gwala-production-alert.timer",
    "project-gwala-opening-executive-report.service",
    "project-gwala-opening-executive-report.timer",
    "project-gwala-eod-executive-report.service",
    "project-gwala-eod-executive-report.timer",
]
ALWAYS_ON_SERVICES = {"project-gwala-dashboard.service"}
ONESHOT_SERVICES = {
    "project-gwala-autonomous-paper.service",
    "project-gwala-market-async-lane.service",
    "project-gwala-production-alert.service",
    "project-gwala-opening-executive-report.service",
    "project-gwala-eod-executive-report.service",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Project Gwala host systemd health JSON.")
    parser.add_argument("--output", type=Path, default=Path("/srv/projects/gwala/logs/host_systemd_health.json"))
    parser.add_argument("--units", nargs="+", default=DEFAULT_UNITS)
    parser.add_argument(
        "--fail-on-red",
        action="store_true",
        help="Exit nonzero when a host unit is unhealthy. Default exits 0 so Docker heartbeat can consume RED artifacts.",
    )
    return parser.parse_args()


def systemctl_show(unit: str) -> dict[str, str]:
    completed = subprocess.run(
        ["systemctl", "show", unit, "--no-page"],
        check=False,
        text=True,
        capture_output=True,
    )
    fields: dict[str, str] = {
        "unit": unit,
        "returncode": str(completed.returncode),
    }
    if completed.stderr.strip():
        fields["stderr"] = completed.stderr.strip()[-500:]
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return fields


def unit_health(fields: dict[str, str]) -> dict[str, Any]:
    unit = fields.get("unit", "")
    load_state = fields.get("LoadState", "")
    active_state = fields.get("ActiveState", "")
    result = fields.get("Result", "")
    exec_status = fields.get("ExecMainStatus", "")
    if unit.endswith(".timer"):
        unit_type = "timer"
    elif unit in ALWAYS_ON_SERVICES:
        unit_type = "always_on_service"
    elif unit in ONESHOT_SERVICES:
        unit_type = "oneshot_service"
    else:
        unit_type = "service"

    blockers: list[str] = []
    if fields.get("returncode") != "0":
        blockers.append(f"systemctl_returncode={fields.get('returncode')}")
    if load_state != "loaded":
        blockers.append(f"LoadState={load_state or 'missing'}")
    if unit_type == "timer" and active_state != "active":
        blockers.append(f"ActiveState={active_state or 'missing'}")
    if unit_type == "always_on_service" and active_state != "active":
        blockers.append(f"ActiveState={active_state or 'missing'}")
    if unit_type == "oneshot_service" and active_state not in {"active", "inactive", "activating"}:
        blockers.append(f"ActiveState={active_state or 'missing'}")
    if unit_type == "service" and active_state not in {"active", "inactive"}:
        blockers.append(f"ActiveState={active_state or 'missing'}")
    if result not in {"", "success"}:
        blockers.append(f"Result={result}")
    if exec_status not in {"", "0"}:
        blockers.append(f"ExecMainStatus={exec_status}")

    status = "GREEN" if not blockers else "RED"
    return {
        "unit": unit,
        "type": unit_type,
        "status": status,
        "healthy": status == "GREEN",
        "reason": "loaded and healthy" if status == "GREEN" else "; ".join(blockers),
        "load_state": load_state,
        "active_state": active_state,
        "result": result,
        "exec_main_status": exec_status,
    }


def build_payload(units: list[str]) -> dict[str, Any]:
    now = datetime.now(MARKET_TZ)
    rows = [unit_health(systemctl_show(unit)) for unit in units]
    failing = [row for row in rows if row["status"] == "RED"]
    status = "RED" if failing else "GREEN"
    return {
        "generated_at_et": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "status": status,
        "reason": "All Project Gwala host systemd units are healthy."
        if status == "GREEN"
        else "One or more Project Gwala host systemd units are unhealthy.",
        "red_component": failing[0]["unit"] if failing else "",
        "red_reason": failing[0]["reason"] if failing else "",
        "units": rows,
        "guardrail": "Host systemd health artifact only. No service or timer state was changed.",
    }


def main() -> None:
    args = parse_args()
    payload = build_payload(args.units)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote host systemd health: {args.output} ({payload['status']})")
    raise SystemExit(1 if args.fail_on_red and payload["status"] == "RED" else 0)


if __name__ == "__main__":
    main()
