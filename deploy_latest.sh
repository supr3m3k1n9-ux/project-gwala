#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="${GWALA_STACK_DIR:-/srv/projects/gwala}"
APP_DIR="${GWALA_APP_DIR:-$STACK_DIR/app}"
if [[ ! -d "$APP_DIR/.git" ]]; then
  APP_DIR="$STACK_DIR"
fi
COMPOSE_FILE="$STACK_DIR/compose.yaml"

mkdir -p "$STACK_DIR/data" "$STACK_DIR/logs" "$STACK_DIR/config/webull_tokens" "$STACK_DIR/backups"

cd "$APP_DIR"

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

if [[ "$APP_DIR/compose.yaml" != "$COMPOSE_FILE" ]]; then
  install -m 0644 "$APP_DIR/compose.yaml" "$COMPOSE_FILE"
fi
if [[ "$APP_DIR/run_in_docker.sh" != "$STACK_DIR/run_in_docker.sh" ]]; then
  install -m 0755 "$APP_DIR/run_in_docker.sh" "$STACK_DIR/run_in_docker.sh"
fi
if [[ "$APP_DIR/deploy_latest.sh" != "$STACK_DIR/deploy_latest.sh" ]]; then
  install -m 0755 "$APP_DIR/deploy_latest.sh" "$STACK_DIR/deploy_latest.sh"
fi

export GWALA_APP_DIR="$APP_DIR"
export GWALA_STACK_DIR="$STACK_DIR"

python3 "$APP_DIR/deploy/linux/verify_docker_runtime_boundary.py" --compose-file "$COMPOSE_FILE" --app-dir "$APP_DIR" --stack-dir "$STACK_DIR"
GWALA_APP_DIR="$APP_DIR" GWALA_STACK_DIR="$STACK_DIR" docker compose -f "$COMPOSE_FILE" build gwala
python3 "$APP_DIR/deploy/linux/verify_docker_runtime_boundary.py" --compose-file "$COMPOSE_FILE" --app-dir "$APP_DIR" --stack-dir "$STACK_DIR" --runtime-check

python3 "$APP_DIR/deploy/linux/write_host_systemd_health.py" --output "$STACK_DIR/logs/host_systemd_health.json"
python3 "$APP_DIR/deploy/linux/write_host_docker_health.py" --output "$STACK_DIR/logs/host_docker_health.json" --compose-file "$COMPOSE_FILE" --expected-image project-gwala:shadow
python3 "$APP_DIR/deploy/linux/write_host_security_health.py" --output "$STACK_DIR/logs/host_security_health.json"

"$STACK_DIR/run_in_docker.sh" python run_continuous_assurance.py --layer runtime
python3 "$APP_DIR/deploy/linux/verify_vps_production.py" --app-dir "$APP_DIR" --stack-dir "$STACK_DIR"

echo "Deployed Project Gwala commit: $(git rev-parse HEAD)"
