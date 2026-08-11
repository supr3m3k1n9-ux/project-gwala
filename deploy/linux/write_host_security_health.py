#!/usr/bin/env python3
"""Write read-only host security health for Project Gwala.

Run this on the Ubuntu host, not inside the application container. The helper
only inspects host state and writes an artifact for continuous assurance to
consume; it does not change firewall, SSH, Docker, permissions, services, or
application state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo


MARKET_TZ = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(os.environ.get("GWALA_PROJECT_ROOT", "/srv/projects/gwala"))
DEFAULT_OUTPUT = PROJECT_ROOT / "logs" / "host_security_health.json"
SECRET_NAMES = [
    "WEBULL_APP_KEY",
    "WEBULL_APP_SECRET",
    "WEBULL_ACCESS_TOKEN",
    "WEBULL_REFRESH_TOKEN",
    "POLYGON_API_KEY",
    "GWALA_SMTP_PASSWORD",
    "SMTP_PASSWORD",
    "EMAIL_PASSWORD",
]
KEY_DIRECTORIES = ["app", "data", "logs", "config", "backups"]


CommandRunner = Callable[[list[str], int], tuple[int, str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Project Gwala host security health JSON.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--fail-on-red", action="store_true")
    return parser.parse_args()


def run_command(command: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()[-5000:]


def run_command_full(command: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a command without truncating stdout for structured JSON parsing."""

    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()[-5000:]
    return completed.returncode, completed.stdout.strip()


def check_row(component: str, status: str, reason: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {"component": component, "status": status, "reason": reason}
    row.update(extra)
    return row


def red_row(component: str, reason: str, next_action: str, **extra: object) -> dict[str, object]:
    return check_row(
        component,
        "RED",
        reason,
        business_impact="Material host security boundary violation.",
        operator_action_required="YES",
        engineering_trigger="INVESTIGATE",
        recommended_next_action=next_action,
        **extra,
    )


def parse_sshd_effective_config(text: str) -> dict[str, str]:
    config: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            config[parts[0].lower()] = parts[1].strip().lower()
    return config


def ssh_hardening_check(text: str | None = None, runner: CommandRunner = run_command) -> dict[str, object]:
    if text is None:
        code, text = runner(["sshd", "-T"], 20)
        if code != 0:
            return check_row("SSH hardening", "WATCH", "Could not inspect effective sshd configuration.")
    config = parse_sshd_effective_config(text)
    blockers = []
    expected = {
        "permitrootlogin": "no",
        "passwordauthentication": "no",
        "pubkeyauthentication": "yes",
    }
    for key, value in expected.items():
        actual = config.get(key, "")
        if actual != value:
            blockers.append(f"{key}={actual or 'missing'}")
    if blockers:
        return red_row(
            "SSH hardening",
            "; ".join(blockers),
            "Set PermitRootLogin no, PasswordAuthentication no, and PubkeyAuthentication yes after reviewed SSH change control.",
            details={"permit_root_login": config.get("permitrootlogin", ""), "password_authentication": config.get("passwordauthentication", ""), "pubkey_authentication": config.get("pubkeyauthentication", "")},
        )
    return check_row("SSH hardening", "GREEN", "Effective sshd config matches approved posture.")


def ufw_check(text: str | None = None, runner: CommandRunner = run_command) -> dict[str, object]:
    if text is None:
        code, text = runner(["ufw", "status", "verbose"], 20)
        if code != 0:
            return check_row("UFW", "WATCH", "Could not inspect UFW status.")
    lower = text.lower()
    if "status: inactive" in lower:
        return red_row("UFW", "UFW is inactive.", "Review and enable the approved host firewall policy.")
    if "status: active" not in lower:
        return check_row("UFW", "WATCH", "UFW status could not be determined.")
    default_ok = "default: deny (incoming)" in lower or "deny (incoming)" in lower
    ssh_ok = any(("22/tcp" in line or "openssh" in line.lower() or "ssh" in line.lower()) and "allow" in line.lower() for line in text.splitlines())
    unexpected = unexpected_ufw_allows(text)
    if not default_ok:
        return red_row("UFW", "Default incoming policy is not deny.", "Review UFW default incoming policy.")
    if not ssh_ok:
        return red_row("UFW", "No allowed SSH rule was found.", "Add the approved SSH allow rule before relying on host firewall health.")
    if unexpected:
        return check_row("UFW", "WATCH", "Unexpected allowed inbound rule(s) found.", unexpected_allowed=unexpected)
    return check_row("UFW", "GREEN", "UFW is active with deny incoming default and SSH allowed.")


def unexpected_ufw_allows(text: str) -> list[str]:
    allowed = []
    for line in text.splitlines():
        lower = line.lower()
        if "allow" not in lower:
            continue
        if "22/tcp" in lower or "openssh" in lower or re.search(r"\bssh\b", lower):
            continue
        if line.strip().startswith(("To", "--", "Status:", "Default:")):
            continue
        allowed.append(line.strip())
    return allowed


def parse_listener_lines(text: str) -> list[dict[str, object]]:
    listeners: list[dict[str, object]] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith(("Netid", "State")):
            continue
        parts = raw.split()
        if len(parts) < 5:
            continue
        protocol = parts[0].lower()
        local = parts[4]
        process = " ".join(parts[6:]) if len(parts) > 6 else ""
        host, port = split_host_port(local)
        listeners.append({"protocol": protocol, "host": host, "port": port, "process": process, "raw": raw})
    return listeners


def split_host_port(value: str) -> tuple[str, str]:
    if value.startswith("[") and "]:" in value:
        host, port = value.rsplit("]:", 1)
        return host.lstrip("["), port
    if ":" in value:
        host, port = value.rsplit(":", 1)
        return host, port
    return value, ""


def is_public_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"0.0.0.0", "::", "*", "[::]"} or normalized.startswith("[::]")


def is_localhost(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    return normalized in {"127.0.0.1", "::1", "localhost"}


def listening_ports_check(text: str | None = None, runner: CommandRunner = run_command) -> tuple[dict[str, object], dict[str, object]]:
    if text is None:
        code, text = runner(["ss", "-tulpen"], 20)
        if code != 0:
            return check_row("Listening network ports", "WATCH", "Could not inspect host listeners."), {
                "public_ports": [],
                "localhost_only_ports": [],
                "unexpected_listeners": [],
                "docker_tcp_exposed": False,
                "dashboard_public": False,
            }
    listeners = parse_listener_lines(text)
    public_ports = [listener for listener in listeners if is_public_host(str(listener["host"]))]
    localhost_ports = [listener for listener in listeners if is_localhost(str(listener["host"]))]
    dashboard_public = any(str(row["port"]) in {"5000", "8000", "8501"} and is_public_host(str(row["host"])) for row in listeners)
    docker_tcp_exposed = any(str(row["port"]) in {"2375", "2376"} and is_public_host(str(row["host"])) for row in listeners)
    unexpected = [
        row
        for row in public_ports
        if str(row["port"]) not in {"22"} and not (str(row["port"]) in {"2375", "2376"} and "docker" in str(row["process"]).lower())
    ]
    summary = {
        "public_ports": public_ports,
        "localhost_only_ports": localhost_ports,
        "unexpected_listeners": unexpected,
        "docker_tcp_exposed": docker_tcp_exposed,
        "dashboard_public": dashboard_public,
    }
    if dashboard_public:
        return red_row("Dashboard exposure", "Gwala dashboard appears publicly bound.", "Bind dashboard to localhost only."), summary
    if docker_tcp_exposed:
        return red_row("Docker TCP exposure", "Docker daemon TCP listener is publicly exposed.", "Disable public Docker TCP exposure."), summary
    if unexpected:
        return check_row("Listening network ports", "WATCH", "Unexpected public listener(s) found.", unexpected_listeners=unexpected), summary
    return check_row("Listening network ports", "GREEN", "Only expected public listeners found."), summary


def docker_inspect_check(
    inspect_payload: list[dict[str, Any]] | None = None,
    docker_host: str | None = None,
    runner: CommandRunner = run_command,
    compose_file: Path | None = None,
) -> dict[str, object]:
    if inspect_payload is None:
        code, ids = runner(["docker", "ps", "--filter", "name=gwala", "--quiet"], 20)
        if code != 0:
            return check_row("Docker security", "WATCH", "Could not inspect Docker containers.")
        container_ids = [line.strip() for line in ids.splitlines() if line.strip()]
        if not container_ids:
            return compose_security_fallback(compose_file or PROJECT_ROOT / "compose.yaml", runner)
        code, text = run_command_full(["docker", "inspect", *container_ids], 30)
        if code != 0:
            return check_row("Docker security", "WATCH", "docker inspect failed.")
        try:
            inspect_payload = json.loads(text)
        except json.JSONDecodeError:
            return check_row("Docker security", "WATCH", "docker inspect returned invalid JSON.")
    docker_host = docker_host if docker_host is not None else os.environ.get("DOCKER_HOST", "")
    blockers: list[str] = []
    warnings: list[str] = []
    if str(docker_host).startswith("tcp://"):
        blockers.append("DOCKER_HOST uses TCP endpoint")
    for container in inspect_payload:
        host_config = container.get("HostConfig", {}) or {}
        config = container.get("Config", {}) or {}
        name = str(container.get("Name", "")).lstrip("/")
        blockers.extend(container_security_blockers(name, host_config, config, container))
        warnings.extend(container_security_warnings(name, host_config))
    if blockers:
        return red_row("Docker security", "; ".join(blockers), "Review Docker Compose/runtime security posture before trusting host.")
    if warnings:
        return check_row("Docker security", "WATCH", "; ".join(warnings))
    return check_row("Docker security", "GREEN", "Gwala container posture matches approved Docker boundary.")


def container_security_blockers(
    name: str,
    host_config: dict[str, Any],
    config: dict[str, Any],
    container: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if host_config.get("Privileged"):
        blockers.append(f"{name}: privileged=true")
    if host_config.get("NetworkMode") == "host":
        blockers.append(f"{name}: host network")
    if host_config.get("PidMode") == "host":
        blockers.append(f"{name}: host PID namespace")
    if host_config.get("IpcMode") == "host":
        blockers.append(f"{name}: host IPC namespace")
    if host_config.get("Devices"):
        blockers.append(f"{name}: unexpected devices")
    user = str(config.get("User", ""))
    if user not in {"1000:1000", "1000", "app:app"}:
        blockers.append(f"{name}: unexpected user={user or 'root'}")
    for mount in host_config.get("Binds") or []:
        if str(mount).split(":", 2)[0] == "/var/run/docker.sock":
            blockers.append(f"{name}: Docker socket mounted")
    for mount in container.get("Mounts") or []:
        if mount.get("Source") == "/var/run/docker.sock" or mount.get("Destination") == "/var/run/docker.sock":
            blockers.append(f"{name}: Docker socket mounted")
    return blockers


def container_security_warnings(name: str, host_config: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    security_opt = [str(item) for item in host_config.get("SecurityOpt") or []]
    is_transient_compose_run = "-run-" in name
    if not any("no-new-privileges" in item for item in security_opt) and not is_transient_compose_run:
        warnings.append(f"{name}: no-new-privileges not declared")
    caps = host_config.get("CapAdd") or []
    if caps:
        warnings.append(f"{name}: added capabilities={caps}")
    return warnings


def compose_security_fallback(compose_file: Path, runner: CommandRunner = run_command) -> dict[str, object]:
    if not compose_file.exists():
        return check_row("Docker security", "WATCH", "No running Gwala container found to inspect; compose file not found.")
    code, text = run_command_full(["docker", "compose", "-f", str(compose_file), "config", "--format", "json"], 30)
    if code != 0:
        return check_row("Docker security", "WATCH", "No running Gwala container found; compose security config could not be inspected.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return check_row("Docker security", "WATCH", "No running Gwala container found; compose config returned invalid JSON.")
    blockers: list[str] = []
    warnings: list[str] = []
    services = payload.get("services", {}) if isinstance(payload, dict) else {}
    if not isinstance(services, dict) or not services:
        return check_row("Docker security", "WATCH", "No running Gwala container found; compose config has no inspectable services.")
    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        name = str(service_name)
        if service.get("privileged"):
            blockers.append(f"{name}: privileged=true")
        if service.get("network_mode") == "host":
            blockers.append(f"{name}: host network")
        if service.get("pid") == "host":
            blockers.append(f"{name}: host PID namespace")
        if service.get("ipc") == "host":
            blockers.append(f"{name}: host IPC namespace")
        if service.get("devices"):
            blockers.append(f"{name}: unexpected devices")
        user = str(service.get("user", ""))
        if user and user not in {"1000:1000", "1000", "app:app"}:
            blockers.append(f"{name}: unexpected user={user}")
        if not user:
            warnings.append(f"{name}: compose user not declared")
        security_opt = [str(item) for item in service.get("security_opt") or []]
        if not any("no-new-privileges" in item for item in security_opt):
            warnings.append(f"{name}: no-new-privileges not declared")
        if service.get("cap_add"):
            warnings.append(f"{name}: added capabilities={service.get('cap_add')}")
        for volume in service.get("volumes") or []:
            source = str(volume.get("source", "") if isinstance(volume, dict) else str(volume).split(":", 1)[0])
            target = str(volume.get("target", "") if isinstance(volume, dict) else "")
            if source == "/var/run/docker.sock" or target == "/var/run/docker.sock":
                blockers.append(f"{name}: Docker socket mounted")
    if blockers:
        return red_row("Docker security", "; ".join(blockers), "Review Docker Compose security posture before trusting host.")
    reason = "No running Gwala container found; compose config has no RED Docker security blockers. Runtime-only fields remain unverified."
    if warnings:
        reason += " " + "; ".join(warnings)
    return check_row("Docker security", "WATCH", reason)


def mode_string(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def owner_only(path: Path) -> bool:
    mode = stat.S_IMODE(path.stat().st_mode)
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def secret_file_permissions_check(project_root: Path) -> dict[str, object]:
    paths = {
        "config": project_root / "config",
        "gwala.env": project_root / "config" / "gwala.env",
        "webull_tokens": project_root / "config" / "webull_tokens",
    }
    blockers: list[str] = []
    details: dict[str, str] = {}
    for label, path in paths.items():
        if not path.exists():
            blockers.append(f"{label} missing")
            continue
        details[label] = mode_string(path)
        if not owner_only(path):
            blockers.append(f"{label} permissions {mode_string(path)}")
    token_dir = paths["webull_tokens"]
    if token_dir.exists() and token_dir.is_dir():
        for token_file in token_dir.iterdir():
            if token_file.is_file():
                details[f"webull_tokens/{token_file.name}"] = mode_string(token_file)
                if stat.S_IMODE(token_file.stat().st_mode) & (stat.S_IRWXG | stat.S_IRWXO):
                    blockers.append(f"token file {token_file.name} permissions {mode_string(token_file)}")
    if blockers:
        return red_row("Secret file permissions", "; ".join(blockers), "Restrict host secret files/directories to owner-only permissions.", details=details)
    return check_row("Secret file permissions", "GREEN", "Host secret files/directories are owner-only.", details=details)


def writable_by_group_or_other(path: Path) -> bool:
    mode = stat.S_IMODE(path.stat().st_mode)
    return bool(mode & (stat.S_IWGRP | stat.S_IWOTH))


def root_wrapper_permissions_check(project_root: Path, systemd_dir: Path = Path("/etc/systemd/system")) -> dict[str, object]:
    targets = [project_root / "run_in_docker.sh", project_root / "deploy_latest.sh"]
    targets.extend(sorted(systemd_dir.glob("project-gwala-*")))
    blockers = []
    details = {}
    for path in targets:
        if not path.exists():
            continue
        st = path.stat()
        details[str(path)] = {"uid": st.st_uid, "mode": mode_string(path)}
        if writable_by_group_or_other(path):
            blockers.append(f"{path} writable by group/other ({mode_string(path)})")
    if blockers:
        return red_row("Root/privileged wrappers", "; ".join(blockers), "Restrict root-executed scripts and systemd units so ordinary users cannot modify them.", details=details)
    return check_row("Root/privileged wrappers", "GREEN", "Root-executed wrappers and Project Gwala units are not group/world writable.", details=details)


def filesystem_permissions_check(project_root: Path) -> dict[str, object]:
    paths = [project_root] + [project_root / name for name in KEY_DIRECTORIES]
    findings = []
    details = {}
    for path in paths:
        if not path.exists():
            continue
        details[str(path)] = mode_string(path)
        if stat.S_IMODE(path.stat().st_mode) & stat.S_IWOTH:
            findings.append(f"{path} world-writable ({mode_string(path)})")
        elif writable_by_group_or_other(path) and path.name in {"config", "backups"}:
            findings.append(f"{path} unexpectedly group-writable ({mode_string(path)})")
    if findings:
        return red_row("Filesystem permissions", "; ".join(findings), "Review and restrict broad write permissions on key Gwala directories.", details=details)
    return check_row("Filesystem permissions", "GREEN", "No world-writable key Gwala paths found.", details=details)


def secret_values_from_env(env: dict[str, str] | None = None) -> dict[str, str]:
    values = env if env is not None else os.environ
    secrets = {}
    for name in SECRET_NAMES:
        value = values.get(name, "").strip()
        if value and not value.startswith(("your_", "paste_", "test-", "dummy", "placeholder")):
            secrets[name] = value
    return secrets


def credential_leak_check(project_root: Path, env: dict[str, str] | None = None) -> dict[str, object]:
    secrets = secret_values_from_env(env)
    search_roots = [project_root / "logs", project_root / "data", project_root / "backups"]
    tracked_files = tracked_repository_files(project_root)
    findings: list[dict[str, str]] = []
    for path in iter_search_files(search_roots, tracked_files):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, value in secrets.items():
            if value and value in text:
                findings.append({"secret": name, "path": str(path), "severity": "RED"})
    sdk_log = project_root / "webull_data_sdk.log"
    if sdk_log.exists():
        findings.append({"secret": "webull_data_sdk.log", "path": str(sdk_log), "severity": "RED"})
    if findings:
        return red_row("Credential leak traces", f"{len(findings)} credential trace(s) found; values redacted.", "Remove leaked credential traces and rotate affected secrets.", findings=findings)
    return check_row("Credential leak traces", "GREEN", "No known secret value matches found in checked paths.")


def tracked_repository_files(project_root: Path) -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    return [project_root / line.strip() for line in completed.stdout.splitlines() if line.strip()]


def iter_search_files(search_roots: Iterable[Path], tracked_files: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in search_roots:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    yield path
    for path in tracked_files:
        if path.exists() and path.is_file() and path not in seen:
            seen.add(path)
            yield path


def build_payload(project_root: Path, runner: CommandRunner = run_command) -> dict[str, Any]:
    checks: list[dict[str, object]] = []
    ssh = ssh_hardening_check(runner=runner)
    checks.append(ssh)
    checks.append(ufw_check(runner=runner))
    listener_check, listener_summary = listening_ports_check(runner=runner)
    checks.append(listener_check)
    docker_check = docker_inspect_check(runner=runner)
    checks.append(docker_check)
    checks.append(secret_file_permissions_check(project_root))
    checks.append(root_wrapper_permissions_check(project_root))
    checks.append(filesystem_permissions_check(project_root))
    checks.append(credential_leak_check(project_root))

    statuses = {str(check["status"]) for check in checks}
    status = "RED" if "RED" in statuses else "WATCH" if "WATCH" in statuses else "GREEN"
    red = next((check for check in checks if check["status"] == "RED"), {})
    attack_surface_summary = {
        **listener_summary,
        "docker_socket_exposed_to_container": "Docker socket mounted" in str(docker_check.get("reason", "")),
        "docker_tcp_exposed": bool(listener_summary.get("docker_tcp_exposed")) or "DOCKER_HOST uses TCP endpoint" in str(docker_check.get("reason", "")),
        "dashboard_public": bool(listener_summary.get("dashboard_public")),
        "ssh_hardened": ssh.get("status") == "GREEN",
    }
    return {
        "generated_at": datetime.now(MARKET_TZ).isoformat(),
        "generated_at_et": datetime.now(MARKET_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "generated_at_epoch": time.time(),
        "status": status,
        "checks": checks,
        "attack_surface_summary": attack_surface_summary,
        "red_component": red.get("component", ""),
        "red_reason": red.get("reason", ""),
        "business_impact": red.get("business_impact", ""),
        "operator_action_required": red.get("operator_action_required", "NO" if status != "RED" else "YES"),
        "engineering_trigger": red.get("engineering_trigger", "WAIT" if status == "GREEN" else "INVESTIGATE"),
        "recommended_next_action": red.get("recommended_next_action", "Continue monitoring." if status == "GREEN" else "Review WATCH findings outside market hours."),
        "guardrail": "Read-only host security health artifact. No firewall, SSH, Docker, permission, service, user, strategy, broker, or trading state was changed.",
    }


def main() -> None:
    args = parse_args()
    payload = build_payload(args.project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Host security health: {payload['status']}")
    print(f"Saved host security health: {args.output}")
    raise SystemExit(1 if args.fail_on_red and payload["status"] == "RED" else 0)


if __name__ == "__main__":
    main()
