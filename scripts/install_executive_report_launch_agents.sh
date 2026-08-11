#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/roy/Documents/New project"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/ProjectGwala"
LABELS=(
  "com.project-gwala.opening-executive-report"
  "com.project-gwala.eod-executive-report"
)

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs/executive_reports"
mkdir -p "$LAUNCHD_LOG_DIR"

"$PROJECT_DIR/.venv-webull/bin/python" "$PROJECT_DIR/tools/build_executive_report_launchd_plists.py"

for LABEL in "${LABELS[@]}"; do
  SOURCE_PLIST="$PROJECT_DIR/launchd/$LABEL.plist"
  TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

  if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID" "$TARGET_PLIST" >/dev/null 2>&1 || true
  fi

  cp "$SOURCE_PLIST" "$TARGET_PLIST"
  plutil -lint "$TARGET_PLIST"
  launchctl bootstrap "gui/$UID" "$TARGET_PLIST"
  launchctl enable "gui/$UID/$LABEL"
  echo "Installed and loaded $LABEL"
done

echo "Status checks:"
for LABEL in "${LABELS[@]}"; do
  echo "  launchctl print gui/$UID/$LABEL"
done
echo "Logs:"
echo "  $LAUNCHD_LOG_DIR/com.project-gwala.opening-executive-report.out.log"
echo "  $LAUNCHD_LOG_DIR/com.project-gwala.opening-executive-report.err.log"
echo "  $LAUNCHD_LOG_DIR/com.project-gwala.eod-executive-report.out.log"
echo "  $LAUNCHD_LOG_DIR/com.project-gwala.eod-executive-report.err.log"
