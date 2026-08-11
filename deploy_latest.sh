#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/srv/projects/gwala"
cd "$PROJECT_ROOT"

if [[ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]]; then
  echo "Refusing deploy: VPS checkout is not on main." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing deploy: VPS worktree is not clean." >&2
  exit 1
fi

git fetch origin main
git merge --ff-only origin/main

python3 deploy/linux/verify_docker_runtime_boundary.py --compose-file compose.yaml
docker compose -f compose.yaml build gwala
python3 deploy/linux/verify_docker_runtime_boundary.py --compose-file compose.yaml --runtime-check

python3 deploy/linux/write_host_systemd_health.py --output logs/host_systemd_health.json
python3 deploy/linux/write_host_docker_health.py --output logs/host_docker_health.json --compose-file compose.yaml --expected-image project-gwala:shadow
python3 deploy/linux/write_host_security_health.py --output logs/host_security_health.json

./run_in_docker.sh python run_continuous_assurance.py --layer runtime

echo "Deployed Project Gwala commit: $(git rev-parse HEAD)"
