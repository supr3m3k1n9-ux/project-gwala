#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/roy/Documents/New project"
APP_NAME="Project Gwala Dashboard.app"
OUTPUT_APP="$PROJECT_DIR/$APP_NAME"
EXECUTABLE="$OUTPUT_APP/Contents/MacOS/Project Gwala Dashboard"

chmod +x "$EXECUTABLE"
plutil -lint "$OUTPUT_APP/Contents/Info.plist"

echo "Built $OUTPUT_APP"
echo "Open it with:"
echo "  open \"$OUTPUT_APP\""
