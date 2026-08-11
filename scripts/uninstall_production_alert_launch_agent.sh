#!/usr/bin/env bash
set -euo pipefail

LABEL="com.project-gwala.production-alert"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -f "$TARGET_PLIST" ]; then
  launchctl bootout "gui/$UID" "$TARGET_PLIST" >/dev/null 2>&1 || true
  rm "$TARGET_PLIST"
  echo "Unloaded and removed $LABEL"
else
  echo "$LABEL was not installed."
fi
