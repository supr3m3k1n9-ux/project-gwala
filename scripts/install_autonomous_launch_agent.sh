#!/usr/bin/env bash
set -euo pipefail

LABEL="com.project-gwala.autonomous-paper"
PROJECT_DIR="/Users/roy/Documents/New project"
SOURCE_PLIST="$PROJECT_DIR/launchd/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/ProjectGwala"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$LAUNCHD_LOG_DIR"

if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$UID" "$TARGET_PLIST" >/dev/null 2>&1 || true
fi

cp "$SOURCE_PLIST" "$TARGET_PLIST"
plutil -lint "$TARGET_PLIST"
launchctl bootstrap "gui/$UID" "$TARGET_PLIST"
launchctl enable "gui/$UID/$LABEL"

echo "Installed and loaded $LABEL"
echo "Status: launchctl print gui/$UID/$LABEL"
echo "Logs:"
echo "  $LAUNCHD_LOG_DIR/autonomous_paper_workflow.launchd.out.log"
echo "  $LAUNCHD_LOG_DIR/autonomous_paper_workflow.launchd.err.log"
