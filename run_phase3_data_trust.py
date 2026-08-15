"""Create or verify Phase 3 research market-data trust artifacts.

This runner is governance/provenance only. It never fetches market data, runs a
strategy experiment, alters Cohort 1, imports validation rows, or touches broker
state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from reports.data_trust import (
    DEFAULT_SNAPSHOT_ID,
    create_research_snapshot,
    snapshot_paths,
    verify_research_snapshot,
    write_contract,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Phase 3 data-trust artifacts.")
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--source-candle-dir", type=Path, default=Path("logs"))
    parser.add_argument("--snapshot-id", default=DEFAULT_SNAPSHOT_ID)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--production-commit", default="")
    return parser.parse_args()


def current_commit() -> str:
    """Return the current git commit if available."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def main() -> None:
    args = parse_args()
    contract_json, contract_md = write_contract(args.logs_dir)
    paths = snapshot_paths(args.logs_dir, args.snapshot_id)

    if args.verify_only:
        verification = verify_research_snapshot(args.logs_dir, args.snapshot_id)
        print(f"CONTRACT: {contract_json}")
        print(f"CONTRACT_MD: {contract_md}")
        print(f"SNAPSHOT: {paths.manifest_json}")
        print(f"SNAPSHOT_STATUS: {verification['status']}")
        print(json.dumps(verification, indent=2, allow_nan=False))
        if verification["status"] != "PASS":
            raise SystemExit(1)
        return

    commit = args.production_commit or current_commit()
    manifest = create_research_snapshot(
        logs_dir=args.logs_dir,
        source_candle_dir=args.source_candle_dir,
        snapshot_id=args.snapshot_id,
        production_commit=commit,
    )
    verification = verify_research_snapshot(args.logs_dir, args.snapshot_id)
    print(f"CONTRACT: {contract_json}")
    print(f"CONTRACT_MD: {contract_md}")
    print(f"SNAPSHOT: {paths.manifest_json}")
    print(f"CHECKSUMS: {paths.checksums_sha256}")
    print(f"SNAPSHOT_STATUS: {verification['status']}")
    print(f"PHASE3_RESEARCH_DATA_READY: {manifest['phase3_research_data_ready']}")
    if verification["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
