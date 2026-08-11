"""Generate the local production alert LaunchAgent plist."""

from __future__ import annotations

import plistlib
from pathlib import Path

from config.runtime_paths import project_log_dir, project_python, project_root

PROJECT_DIR = project_root()
LAUNCHD_LOG_DIR = project_log_dir()
LABEL = "com.project-gwala.production-alert"
OUTPUT_PATH = PROJECT_DIR / "launchd" / f"{LABEL}.plist"
ALERT_OFFSET_MINUTES_AFTER_SCAN = 2


def calendar_entries() -> list[dict[str, int]]:
    """Return weekday alert checks offset from the market scan write window."""

    entries: list[dict[str, int]] = []
    for weekday in range(1, 6):
        start = (6 * 60) + 45 + ALERT_OFFSET_MINUTES_AFTER_SCAN
        stop = (13 * 60) + 6 + ALERT_OFFSET_MINUTES_AFTER_SCAN
        for total_minutes in range(start, stop, 5):
            entries.append(
                {
                    "Weekday": weekday,
                    "Hour": total_minutes // 60,
                    "Minute": total_minutes % 60,
                }
            )
    return entries


def build_plist() -> dict:
    """Build the LaunchAgent plist payload."""

    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(project_python()),
            str(PROJECT_DIR / "run_production_alert.py"),
            "--output-dir",
            "logs",
            "--data-dir",
            "data",
            "--interval-minutes",
            "5",
            "--cooldown-minutes",
            "30",
            "--recheck-seconds",
            "25",
            "--outage-threshold-minutes",
            "5",
            "--down-confirmation-failures",
            "2",
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "StartCalendarInterval": calendar_entries(),
        "StandardOutPath": str(LAUNCHD_LOG_DIR / "production_alert.launchd.out.log"),
        "StandardErrorPath": str(LAUNCHD_LOG_DIR / "production_alert.launchd.err.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def main() -> None:
    """Write the generated plist."""

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("wb") as file:
        plistlib.dump(build_plist(), file, sort_keys=False)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Calendar entries: {len(calendar_entries())}")


if __name__ == "__main__":
    main()
