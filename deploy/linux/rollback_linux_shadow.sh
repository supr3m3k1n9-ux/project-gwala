#!/usr/bin/env bash
set -euo pipefail

UNITS=(
  project-gwala-dashboard.timer
  project-gwala-dashboard.service
  project-gwala-autonomous-paper.timer
  project-gwala-autonomous-paper.service
  project-gwala-market-async-lane.timer
  project-gwala-market-async-lane.service
  project-gwala-production-alert.timer
  project-gwala-production-alert.service
  project-gwala-opening-executive-report.timer
  project-gwala-opening-executive-report.service
  project-gwala-eod-executive-report.timer
  project-gwala-eod-executive-report.service
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run rollback with sudo on the VPS." >&2
  exit 1
fi

for unit in "${UNITS[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl reset-failed

echo "Removed Project Gwala Linux shadow systemd units."
echo "Preserved /etc/project-gwala/gwala.env, /opt/project-gwala, and /var/log/project-gwala for audit/recovery."
