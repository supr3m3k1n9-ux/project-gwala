#!/usr/bin/env bash
set -euo pipefail

LABELS=(
  "com.project-gwala.opening-executive-report"
  "com.project-gwala.eod-executive-report"
)

for LABEL in "${LABELS[@]}"; do
  TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  if [ -f "$TARGET_PLIST" ]; then
    launchctl bootout "gui/$UID" "$TARGET_PLIST" >/dev/null 2>&1 || true
    rm "$TARGET_PLIST"
    echo "Unloaded and removed $LABEL"
  else
    echo "$LABEL was not installed."
  fi
done
