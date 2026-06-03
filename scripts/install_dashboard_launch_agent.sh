#!/usr/bin/env bash
set -euo pipefail

LABEL="com.project-gwala.dashboard"
PROJECT_DIR="/Users/roy/Documents/New project"
SOURCE_PLIST="$PROJECT_DIR/launchd/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs"

if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$UID" "$TARGET_PLIST" >/dev/null 2>&1 || true
fi

cp "$SOURCE_PLIST" "$TARGET_PLIST"
plutil -lint "$TARGET_PLIST"
launchctl bootstrap "gui/$UID" "$TARGET_PLIST"
launchctl enable "gui/$UID/$LABEL"

echo "Installed and loaded $LABEL"
echo "Open: http://127.0.0.1:8765"
echo "Status: launchctl print gui/$UID/$LABEL"
echo "Logs:"
echo "  $PROJECT_DIR/logs/dashboard.launchd.out.log"
echo "  $PROJECT_DIR/logs/dashboard.launchd.err.log"
