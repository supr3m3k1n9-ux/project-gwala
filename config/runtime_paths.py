"""Runtime path helpers for workstation and VPS deployments."""

from __future__ import annotations

import os
import platform
from pathlib import Path


MACOS_PROJECT_ROOT = Path("/Users/roy/Documents/New project")
LINUX_PROJECT_ROOT = Path("/opt/project-gwala")
DOCKER_PROJECT_ROOT = Path("/app")
DOCKER_RUNTIME_DATA_ROOT = Path("/app/runtime_data")


def default_project_root() -> Path:
    """Return the platform default without changing the current macOS setup."""

    if running_in_docker():
        return DOCKER_PROJECT_ROOT
    if platform.system() == "Linux":
        return LINUX_PROJECT_ROOT
    return MACOS_PROJECT_ROOT


def running_in_docker() -> bool:
    """Return True when running inside a Docker/container runtime."""

    if Path("/.dockerenv").exists():
        return True
    cgroup = Path("/proc/1/cgroup")
    if not cgroup.exists():
        return False
    try:
        text = cgroup.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return any(marker in text for marker in ("docker", "containerd", "kubepods"))


def project_root() -> Path:
    """Return the configured Project Gwala root directory."""

    configured = os.environ.get("GWALA_PROJECT_ROOT", "").strip()
    return Path(configured).expanduser() if configured else default_project_root()


def runtime_data_root() -> Path:
    """Return the durable runtime-data directory, distinct from the `data` package."""

    configured = os.environ.get("GWALA_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if running_in_docker():
        return DOCKER_RUNTIME_DATA_ROOT
    return project_root() / "data"


def runtime_data_path(*parts: str) -> Path:
    """Return a path below the durable runtime-data directory."""

    return runtime_data_root().joinpath(*parts)


def project_python() -> Path:
    """Return the configured Python interpreter for operational commands."""

    configured = os.environ.get("GWALA_PYTHON", "").strip()
    return Path(configured).expanduser() if configured else project_root() / ".venv-webull" / "bin" / "python"


def project_log_dir() -> Path:
    """Return the external service log directory."""

    configured = os.environ.get("GWALA_SERVICE_LOG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if platform.system() == "Linux":
        return Path("/var/log/project-gwala")
    return Path("/Users/roy/Library/Logs/ProjectGwala")
