"""Freeze Project Gwala Cohort 1 evidence.

This command is archive/reporting only. It writes a versioned Cohort 1 freeze
snapshot and refuses to overwrite an existing freeze. It does not edit the
authoritative validation ledger or activate Phase 3.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.runtime_paths import runtime_data_root
from reports.cohort_freeze import COHORT_VERSION
from reports.cohort_freeze import freeze_cohort_1
from reports.cohort_freeze import freeze_paths
from reports.cohort_freeze import verify_cohort_1_freeze


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze Project Gwala Cohort 1 evidence.")
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--data-dir", type=Path, default=runtime_data_root())
    parser.add_argument("--production-commit", required=True)
    parser.add_argument("--freeze-timestamp", default="")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.verify_only:
        result = verify_cohort_1_freeze(args.logs_dir, args.data_dir)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["status"] == "PASS" else 1)

    snapshot = freeze_cohort_1(
        logs_dir=args.logs_dir,
        data_dir=args.data_dir,
        production_commit=args.production_commit,
        freeze_timestamp=args.freeze_timestamp or None,
        cohort_version=COHORT_VERSION,
    )
    verification = verify_cohort_1_freeze(args.logs_dir, args.data_dir)
    paths = freeze_paths(args.logs_dir)
    print(f"COHORT 1: {snapshot['status']}")
    print(f"PHASE 2: {snapshot['phase_2']['status']}")
    print(f"PHASE 3: {snapshot['phase_3']['status']}")
    print(f"Snapshot: {paths.snapshot_json}")
    print(f"Report: {paths.report_md}")
    print(f"Checksums: {paths.checksums_sha256}")
    print(f"Verification: {verification['status']}")
    raise SystemExit(0 if verification["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
