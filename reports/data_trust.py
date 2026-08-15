"""Phase 3 research market-data trust artifacts.

This module creates read-only research-data governance artifacts. It does not
fetch market data, run strategies, alter Cohort 1, or mutate production ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from config.market_calendar import MARKET_TZ
from data.candle_cache import preferred_candle_path


CONTRACT_VERSION = "research-market-data-contract-v1"
SNAPSHOT_SCHEMA_VERSION = "phase3-research-data-snapshot-v1"
DEFAULT_SNAPSHOT_ID = "phase3_research_snapshot_v1"
PHASE3_SYMBOLS = ["SPY", "QQQ", "AAPL", "AMD", "META", "MSFT", "NVDA", "TSLA"]
PHASE3_TIMEFRAMES = ["M1", "M5", "M15", "M30", "M60", "D"]


@dataclass(frozen=True)
class SnapshotPaths:
    root: Path
    manifest_json: Path
    checksums_sha256: Path
    contract_json: Path
    contract_md: Path


def phase3_data_trust_dir(logs_dir: Path) -> Path:
    """Return the Phase 3 data-trust artifact directory."""

    return logs_dir / "phase_3" / "data_trust"


def snapshot_paths(logs_dir: Path, snapshot_id: str = DEFAULT_SNAPSHOT_ID) -> SnapshotPaths:
    """Return paths for a versioned immutable research snapshot."""

    base = phase3_data_trust_dir(logs_dir)
    root = base / "research_snapshots" / snapshot_id
    return SnapshotPaths(
        root=root,
        manifest_json=root / "manifest.json",
        checksums_sha256=root / "checksums.sha256",
        contract_json=base / f"{CONTRACT_VERSION}.json",
        contract_md=base / f"{CONTRACT_VERSION}.md",
    )


def sha256_file(path: Path) -> str:
    """Return a SHA-256 digest for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv_summary(path: Path) -> dict[str, Any]:
    """Return lightweight structural coverage metadata for a candle CSV."""

    if not path.exists():
        return {"exists": False, "rows": 0, "first_datetime": "", "latest_datetime": "", "columns": []}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    datetimes = [str(row.get("datetime", "")).strip() for row in rows if str(row.get("datetime", "")).strip()]
    return {
        "exists": True,
        "rows": len(rows),
        "first_datetime": min(datetimes) if datetimes else "",
        "latest_datetime": max(datetimes) if datetimes else "",
        "columns": columns,
    }


def research_market_data_contract() -> dict[str, Any]:
    """Return the formal Phase 3 market-data contract."""

    return {
        "schema_version": "research-market-data-contract-schema-v1",
        "contract_version": CONTRACT_VERSION,
        "status": "ACTIVE_FOR_DATA_TRUST",
        "approved_provider": {
            "primary": "webull",
            "secondary": "polygon may be used only after explicit compatibility verification",
            "not_authoritative": ["yfinance legacy downloads", "mutable live cache without snapshot hash"],
        },
        "session_policy": "Regular trading hours only for equities research unless a future experiment explicitly declares otherwise.",
        "timezone_policy": "Store timestamps with timezone; interpret decisions in America/New_York.",
        "timeframe_semantics": {
            "M30": "Entry-decision candle. Historical decisions may use only data available after the M30 candle has completed.",
            "M5": "Exit/management candle. Historical exits may use only M5 candles after the entry timestamp.",
            "M60": "Higher-timeframe context. A reconstructed M60 bucket is unavailable until the full 60-minute bucket has completed.",
            "D": "Completed daily context. Intraday decisions must not consume same-session daily bars before session close.",
        },
        "adjustment_policy": {
            "research_default": "unresolved",
            "rule": "Do not mix adjusted and unadjusted sources in one experiment until provider adjustment behavior is documented.",
            "current_known_mismatch": {
                "polygon_import": "adjusted=True by default",
                "yfinance_loader": "auto_adjust=False",
                "webull": "adjustment semantics not documented in-project",
            },
        },
        "missing_bar_policy": "Fail closed for decision-critical M30/M5 data. Supporting/chart gaps remain visible and cannot be silently filled.",
        "resampling_policy": "Resampling may use only complete lower-timeframe buckets and must label context by availability timestamp, not bucket start.",
        "provenance_requirements": [
            "provider",
            "ingestion script",
            "source path",
            "creation timestamp",
            "contract version",
            "snapshot id",
            "file checksum",
            "coverage",
            "known gaps",
        ],
        "checksum_requirements": "Every research experiment must record the snapshot id and manifest checksum it used.",
        "lookahead_policy": "No feature, context label, signal, regime label, or exit may use information unavailable at the historical decision timestamp.",
        "phase3_gate_policy": "P3-E001/P3-E002 remain waiting until source/external/corporate-action/M5 coverage findings are reviewed or cleared.",
    }


def write_contract(logs_dir: Path) -> tuple[Path, Path]:
    """Persist the Phase 3 research market-data contract."""

    paths = snapshot_paths(logs_dir)
    paths.contract_json.parent.mkdir(parents=True, exist_ok=True)
    contract = research_market_data_contract()
    paths.contract_json.write_text(json.dumps(contract, indent=2, allow_nan=False), encoding="utf-8")
    paths.contract_md.write_text(contract_markdown(contract), encoding="utf-8")
    return paths.contract_json, paths.contract_md


def contract_markdown(contract: dict[str, Any]) -> str:
    """Return founder-readable contract markdown."""

    return f"""# Research Market Data Contract V1

Contract Version: {contract["contract_version"]}

Purpose: prevent Phase 3 research from treating mutable, stale, adjusted-mixed,
or look-ahead-contaminated candles as strategy truth.

## Approved Source

- Primary provider: Webull
- Polygon: allowed only after explicit compatibility verification
- yfinance: legacy/non-authoritative for Phase 3 strategy evidence

## Decision Semantics

- M30: entry-decision candle; no use before candle completion
- M5: exit-management candle; no use before candle completion
- M60: context only after the full higher-timeframe bucket is complete
- D: completed daily context only; no intraday same-session daily leakage

## Adjustment Policy

Current status: unresolved. Do not mix Webull, Polygon, and yfinance candles as
equivalent research truth until adjusted/unadjusted behavior is verified.

## Experiment Requirement

Every Phase 3 experiment must record this contract version and the immutable
research snapshot id/hash used.
"""


def create_research_snapshot(
    *,
    logs_dir: Path,
    source_candle_dir: Path,
    snapshot_id: str = DEFAULT_SNAPSHOT_ID,
    production_commit: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create an immutable copy/manifest of Phase 3 research candle data."""

    paths = snapshot_paths(logs_dir, snapshot_id)
    if paths.manifest_json.exists():
        raise FileExistsError(f"Research data snapshot already exists: {paths.manifest_json}")
    write_contract(logs_dir)
    created = created_at or datetime.now(MARKET_TZ).isoformat()
    files = []
    paths.root.mkdir(parents=True, exist_ok=False)
    for symbol in PHASE3_SYMBOLS:
        for timeframe in PHASE3_TIMEFRAMES:
            source = preferred_candle_path(source_candle_dir, symbol, timeframe)
            summary = read_csv_summary(source)
            destination = paths.root / "candles" / symbol / f"{timeframe}.csv"
            record: dict[str, Any] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "source_path": str(source),
                "snapshot_path": str(destination),
                "provider": "webull",
                "ingestion_source": "saved canonical candle cache",
                "contract_version": CONTRACT_VERSION,
                **summary,
            }
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                record["sha256"] = sha256_file(destination)
            else:
                record["sha256"] = ""
            files.append(record)

    known_gaps = [
        "M1 is a bounded chart/display window, not full-session archival history.",
        "M5 trusted current-cache coverage starts around 2026-07-24 for the approved universe.",
        "External independent cross-check is not complete in the current environment.",
        "Webull corporate-action adjustment semantics are not documented in-project.",
    ]
    manifest = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": created,
        "production_commit": production_commit,
        "contract_version": CONTRACT_VERSION,
        "symbols": PHASE3_SYMBOLS,
        "timeframes": PHASE3_TIMEFRAMES,
        "source_candle_dir": str(source_candle_dir),
        "snapshot_root": str(paths.root),
        "status": "CREATED_WITH_OPEN_FINDINGS",
        "phase3_research_data_ready": "NO",
        "files": files,
        "known_gaps": known_gaps,
        "guardrail": "Snapshot creation is read-only against production inputs and does not run research or mutate Cohort 1.",
    }
    paths.manifest_json.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    checksums = [f"{item['sha256']}  {item['snapshot_path']}" for item in files if item.get("sha256")]
    checksums.append(f"{sha256_file(paths.manifest_json)}  {paths.manifest_json}")
    paths.checksums_sha256.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    manifest["manifest_sha256"] = sha256_file(paths.manifest_json)
    paths.manifest_json.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return manifest


def verify_research_snapshot(logs_dir: Path, snapshot_id: str = DEFAULT_SNAPSHOT_ID) -> dict[str, Any]:
    """Verify that snapshot files still match their manifest checksums."""

    paths = snapshot_paths(logs_dir, snapshot_id)
    if not paths.manifest_json.exists():
        return {"status": "FAIL", "reason": f"Missing snapshot manifest: {paths.manifest_json}"}
    manifest = json.loads(paths.manifest_json.read_text(encoding="utf-8"))
    failures = []
    for item in manifest.get("files", []):
        checksum = item.get("sha256", "")
        path = Path(item.get("snapshot_path", ""))
        if not checksum:
            failures.append({"path": str(path), "reason": "missing source file at snapshot creation"})
            continue
        if not path.exists():
            failures.append({"path": str(path), "reason": "snapshot file missing"})
            continue
        actual = sha256_file(path)
        if actual != checksum:
            failures.append({"path": str(path), "reason": "checksum mismatch"})
    return {
        "status": "FAIL" if failures else "PASS",
        "snapshot_id": snapshot_id,
        "contract_version": manifest.get("contract_version", ""),
        "files_checked": len(manifest.get("files", [])),
        "failures": failures,
        "phase3_research_data_ready": manifest.get("phase3_research_data_ready", "NO"),
    }
