"""Activate Project Gwala Phase 3 research state.

This command creates the approved Phase 3 opening research agenda from the
frozen Cohort 1 snapshot. It does not run research jobs, mutate Cohort 1,
activate broker execution, or change production trading behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reports.phase3_activation import activate_phase3
from reports.phase3_activation import load_phase3_activation
from reports.phase3_activation import phase3_activation_path
from reports.phase3_activation import phase3_opening_agenda_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Activate Project Gwala Phase 3 research governance.")
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--production-commit", required=True)
    parser.add_argument("--activated-at", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.status:
        payload = load_phase3_activation(args.logs_dir)
        print(json.dumps(payload, indent=2))
        raise SystemExit(0 if payload.get("phase_3") == "ACTIVE" else 1)
    payload = activate_phase3(
        logs_dir=args.logs_dir,
        production_commit=args.production_commit,
        activated_at=args.activated_at or None,
        force=args.force,
    )
    print(f"PHASE 2: {payload['phase_2']}")
    print(f"COHORT 1: {payload['cohort_1']['status']}")
    print(f"PHASE 3: {payload['phase_3']}")
    print(f"RESEARCH FACTORY: {payload['research_factory']}")
    print(f"EDGE DISCOVERY: {payload['edge_discovery']}")
    print(f"BROKER / REAL MONEY: {payload['broker_real_money']}")
    print(f"Activation: {phase3_activation_path(args.logs_dir)}")
    print(f"Agenda: {phase3_opening_agenda_path(args.logs_dir)}")


if __name__ == "__main__":
    main()
