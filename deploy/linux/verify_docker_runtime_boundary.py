#!/usr/bin/env python3
"""Verify Docker source/runtime-data separation for Project Gwala.

This verifier is read-only. It fails if Docker Compose would bind-mount host
runtime data over Python source packages such as `/app/data` or `/app/config`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE = PROJECT_ROOT / "compose.yaml"
SOURCE_PROBE = Path("data/webull_data.py")
SOURCE_PACKAGE_TARGETS = {
    "/app/data": "data",
    "/app/config": "config",
}
APPROVED_RUNTIME_TARGETS = {
    "/app/runtime_data",
    "/app/logs",
    "/app/.webull_tokens",
    "/app/backups",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Project Gwala Docker runtime/source boundary.")
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--compose-json", type=Path, help="Pre-rendered docker compose config JSON for tests.")
    parser.add_argument("--runtime-check", action="store_true", help="Run a short docker compose container source check.")
    return parser.parse_args()


def run_command(command: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()


def load_compose_config(compose_file: Path, compose_json: Path | None = None) -> dict[str, Any]:
    if compose_json is not None:
        return json.loads(compose_json.read_text(encoding="utf-8"))
    code, text = run_command(["docker", "compose", "-f", str(compose_file), "config", "--format", "json"], 60)
    if code != 0:
        raise RuntimeError(f"docker compose config failed: {text[-500:]}")
    return json.loads(text)


def volume_target(volume: object) -> str:
    if isinstance(volume, dict):
        return str(volume.get("target", ""))
    text = str(volume)
    parts = text.split(":")
    return parts[1] if len(parts) >= 2 else ""


def validate_compose_boundary(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    services = payload.get("services", {}) if isinstance(payload, dict) else {}
    if not isinstance(services, dict) or "gwala" not in services:
        return ["Compose config must define a gwala service."]
    service = services["gwala"]
    if not isinstance(service, dict):
        return ["Compose gwala service is not inspectable."]
    targets = [volume_target(volume) for volume in service.get("volumes") or []]
    shadowed = [target for target in targets if target in SOURCE_PACKAGE_TARGETS]
    if shadowed:
        for target in shadowed:
            errors.append(f"{target} must not be a bind mount; it is the {SOURCE_PACKAGE_TARGETS[target]} Python source package.")
    if "/app/runtime_data" not in targets:
        errors.append("Host runtime data must mount to /app/runtime_data.")
    unexpected = [
        target
        for target in targets
        if target.startswith("/app/") and target not in APPROVED_RUNTIME_TARGETS and target not in SOURCE_PACKAGE_TARGETS
    ]
    if unexpected:
        errors.append("Unexpected /app bind mount target(s): " + ", ".join(sorted(unexpected)))
    environment = service.get("environment") or {}
    env_items = environment if isinstance(environment, dict) else {}
    if str(env_items.get("GWALA_DATA_DIR", "")) != "/app/runtime_data":
        errors.append("GWALA_DATA_DIR must be /app/runtime_data inside Docker.")
    return errors


def source_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_source_check(compose_file: Path) -> None:
    expected = source_checksum(PROJECT_ROOT / SOURCE_PROBE)
    code, text = run_command(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "gwala",
            "python",
            "-c",
            (
                "import hashlib, pathlib; "
                "from config.runtime_paths import runtime_data_root; "
                "import config.filter_policy, config.strategy_registry, config.symbol_playbook; "
                "from data.webull_data import disable_sdk_default_logging; "
                "print(hashlib.sha256(pathlib.Path('/app/data/webull_data.py').read_bytes()).hexdigest())"
            ),
        ],
        120,
    )
    if code != 0:
        raise RuntimeError(f"Compose runtime source import/checksum failed: {text[-800:]}")
    actual = text.splitlines()[-1].strip()
    if actual != expected:
        raise RuntimeError("Compose runtime source checksum does not match Git checkout; source may be shadowed.")


def main() -> None:
    args = parse_args()
    payload = load_compose_config(args.compose_file, args.compose_json)
    errors = validate_compose_boundary(payload)
    if errors:
        print("source_package_shadowing=FAIL", file=sys.stderr)
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        raise SystemExit(1)
    print("source_package_shadowing=PASS")
    if args.runtime_check:
        runtime_source_check(args.compose_file)
    print("Docker runtime boundary: PASS")


if __name__ == "__main__":
    main()
