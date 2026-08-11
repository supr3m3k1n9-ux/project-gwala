#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GWALA_PROJECT_ROOT:-/opt/project-gwala}"
ENV_DIR="/etc/project-gwala"
ENV_FILE="$ENV_DIR/gwala.env"
UNIT_SOURCE_DIR="$PROJECT_ROOT/deploy/linux/systemd"
UNIT_TARGET_DIR="/etc/systemd/system"
LOG_DIR="${GWALA_SERVICE_LOG_DIR:-/var/log/project-gwala}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo on the VPS." >&2
  exit 1
fi

mkdir -p "$ENV_DIR" "$LOG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$PROJECT_ROOT/deploy/linux/gwala.env.template" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE. Fill in secrets before enabling timers."
else
  echo "$ENV_FILE already exists; leaving it unchanged."
fi

install -m 0644 "$UNIT_SOURCE_DIR"/*.service "$UNIT_TARGET_DIR"/
install -m 0644 "$UNIT_SOURCE_DIR"/*.timer "$UNIT_TARGET_DIR"/
systemctl daemon-reload

echo "Installed Project Gwala systemd unit files."
echo "Next:"
echo "  1. Edit $ENV_FILE"
echo "  2. Run: $PROJECT_ROOT/.venv-webull/bin/python $PROJECT_ROOT/deploy/linux/preflight.py"
echo "  3. Enable timers only after preflight passes."
