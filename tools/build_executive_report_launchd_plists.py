"""Generate local LaunchAgent plists for executive reports."""

from __future__ import annotations

import plistlib
from pathlib import Path

from config.runtime_paths import project_log_dir, project_python, project_root

PROJECT_DIR = project_root()
LAUNCHD_LOG_DIR = project_log_dir()
PYTHON = project_python()
LAUNCHD_DIR = PROJECT_DIR / "launchd"


def opening_calendar_entries() -> list[dict[str, int]]:
    """Run before the 06:30 PT regular-session open."""

    return [{"Weekday": weekday, "Hour": 6, "Minute": 20} for weekday in range(1, 6)]


def eod_calendar_entries() -> list[dict[str, int]]:
    """Retry after close so final M5 data can settle before final reporting."""

    entries: list[dict[str, int]] = []
    for weekday in range(1, 6):
        for hour, minute in [(13, 5), (13, 10), (13, 15), (13, 20), (13, 30)]:
            entries.append({"Weekday": weekday, "Hour": hour, "Minute": minute})
    return entries


def build_plist(label: str, report_type: str, entries: list[dict[str, int]]) -> dict:
    """Build one executive report LaunchAgent payload."""

    return {
        "Label": label,
        "ProgramArguments": [
            str(PYTHON),
            str(PROJECT_DIR / "run_executive_report.py"),
            "--report-type",
            report_type,
            "--output-dir",
            "logs",
            "--data-dir",
            "data",
            "--reports-dir",
            "logs/executive_reports",
            "--deliver",
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "StartCalendarInterval": entries,
        "StandardOutPath": str(LAUNCHD_LOG_DIR / f"{label}.out.log"),
        "StandardErrorPath": str(LAUNCHD_LOG_DIR / f"{label}.err.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def build_opening_plist() -> dict:
    return build_plist(
        "com.project-gwala.opening-executive-report",
        "opening",
        opening_calendar_entries(),
    )


def build_eod_plist() -> dict:
    return build_plist(
        "com.project-gwala.eod-executive-report",
        "eod",
        eod_calendar_entries(),
    )


def main() -> None:
    LAUNCHD_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        LAUNCHD_DIR / "com.project-gwala.opening-executive-report.plist": build_opening_plist(),
        LAUNCHD_DIR / "com.project-gwala.eod-executive-report.plist": build_eod_plist(),
    }
    for path, payload in outputs.items():
        with path.open("wb") as file:
            plistlib.dump(payload, file, sort_keys=False)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
