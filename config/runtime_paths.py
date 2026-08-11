"""Runtime path helpers for workstation and VPS deployments."""

from __future__ import annotations

import os
import platform
from pathlib import Path


MACOS_PROJECT_ROOT = Path("/Users/roy/Documents/New project")
LINUX_PROJECT_ROOT = Path("/opt/project-gwala")


def default_project_root() -> Path:
    """Return the platform default without changing the current macOS setup."""

    if platform.system() == "Linux":
        return LINUX_PROJECT_ROOT
    return MACOS_PROJECT_ROOT


def project_root() -> Path:
    """Return the configured Project Gwala root directory."""

    configured = os.environ.get("GWALA_PROJECT_ROOT", "").strip()
    return Path(configured).expanduser() if configured else default_project_root()


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
