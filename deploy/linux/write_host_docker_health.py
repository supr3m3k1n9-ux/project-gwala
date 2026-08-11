"""Write host Docker health for containerized Project Gwala assurance.

This helper is read-only. It runs on the Ubuntu host before the application
container starts assurance, then the container consumes the JSON artifact. Do
not mount the host Docker socket into the application container for this check.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("logs/host_docker_health.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write read-only host Docker health for Project Gwala.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compose-file", type=Path, default=Path(os.environ.get("GWALA_COMPOSE_FILE", "compose.yaml")))
    parser.add_argument("--expected-image", default=os.environ.get("GWALA_EXPECTED_DOCKER_IMAGE", ""))
    parser.add_argument("--fail-on-red", action="store_true")
    return parser.parse_args()


def run_command(command: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    text = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, text[-800:]


def check_row(component: str, status: str, reason: str) -> dict[str, str]:
    return {"component": component, "status": status, "reason": reason}


def docker_health(compose_file: Path, expected_image: str) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    docker = shutil.which("docker")
    if not docker:
        checks.append(check_row("docker cli", "RED", "docker command is unavailable on the host."))
    else:
        checks.append(check_row("docker cli", "GREEN", "docker command is available on the host."))
        code, text = run_command([docker, "info", "--format", "{{json .ServerVersion}}"])
        checks.append(
            check_row(
                "docker daemon",
                "GREEN" if code == 0 else "RED",
                "docker daemon responded to docker info." if code == 0 else f"docker info failed: {text}",
            )
        )
        if expected_image:
            code, text = run_command([docker, "image", "inspect", expected_image])
            checks.append(
                check_row(
                    "expected image",
                    "GREEN" if code == 0 else "RED",
                    f"expected image is present: {expected_image}" if code == 0 else f"expected image missing: {expected_image}",
                )
            )

    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    if docker_host.startswith("tcp://"):
        checks.append(check_row("docker remote endpoint", "RED", "DOCKER_HOST points at a TCP Docker endpoint."))
    else:
        checks.append(check_row("docker remote endpoint", "GREEN", "No TCP Docker endpoint is configured in this process."))

    if compose_file.exists():
        if docker:
            compose_command = [docker, "compose", "-f", str(compose_file), "config", "--quiet"]
            code, text = run_command(compose_command, timeout=30)
            checks.append(
                check_row(
                    "compose config",
                    "GREEN" if code == 0 else "WATCH",
                    "compose config is valid." if code == 0 else f"compose config could not be verified: {text}",
                )
            )
        else:
            checks.append(check_row("compose config", "WATCH", "compose file exists but docker command is unavailable."))
    else:
        checks.append(check_row("compose config", "WATCH", f"compose file is not present at {compose_file}."))

    statuses = {check["status"] for check in checks}
    status = "RED" if "RED" in statuses else "WATCH" if "WATCH" in statuses else "GREEN"
    red = next((check for check in checks if check["status"] == "RED"), {})
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "generated_at_epoch": time.time(),
        "status": status,
        "red_component": red.get("component", ""),
        "red_reason": red.get("reason", ""),
        "checks": checks,
        "guardrail": "Read-only host Docker health artifact. Does not start, stop, enable, disable, or control containers.",
    }


def main() -> None:
    args = parse_args()
    payload = docker_health(args.compose_file, args.expected_image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Host Docker health: {payload['status']}")
    print(f"Saved host Docker health: {args.output}")
    if args.fail_on_red and payload["status"] == "RED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
