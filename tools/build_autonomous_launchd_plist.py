"""Generate the autonomous paper LaunchAgent plist.

The generated schedule keeps the laptop quieter:
- 06:15 PT pre-market check
- 06:30-13:00 PT market scans every 5 minutes
- 13:05 PT after-close recap

Each launch runs the supervisor with --once, so the process exits after its
scheduled action instead of staying alive all day.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from config.runtime_paths import project_log_dir, project_python, project_root

PROJECT_DIR = project_root()
LAUNCHD_LOG_DIR = project_log_dir()
LABEL = "com.project-gwala.autonomous-paper"
OUTPUT_PATH = PROJECT_DIR / "launchd" / f"{LABEL}.plist"


def calendar_entries() -> list[dict[str, int]]:
    """Return weekday local-time launch points for the paper supervisor."""

    entries: list[dict[str, int]] = []
    weekdays = range(1, 6)
    for weekday in weekdays:
        entries.append({"Weekday": weekday, "Hour": 6, "Minute": 15})
        for total_minutes in range((6 * 60) + 30, (13 * 60) + 1, 5):
            entries.append(
                {
                    "Weekday": weekday,
                    "Hour": total_minutes // 60,
                    "Minute": total_minutes % 60,
                }
            )
        entries.append({"Weekday": weekday, "Hour": 13, "Minute": 5})
    return entries


def build_plist() -> dict:
    """Build the LaunchAgent plist payload."""

    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(project_python()),
            str(PROJECT_DIR / "run_autonomous_paper_workflow.py"),
            "--interval-minutes",
            "5",
            "--auto-confirm-paper-exits",
            "--once",
        ],
        "WorkingDirectory": str(PROJECT_DIR),
        "StartCalendarInterval": calendar_entries(),
        "StandardOutPath": str(LAUNCHD_LOG_DIR / "autonomous_paper_workflow.launchd.out.log"),
        "StandardErrorPath": str(LAUNCHD_LOG_DIR / "autonomous_paper_workflow.launchd.err.log"),
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
