#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${GWALA_APP_DIR:-}"
if [[ -z "$APP_DIR" ]]; then
  if [[ -d "$STACK_DIR/app/.git" ]]; then
    APP_DIR="$STACK_DIR/app"
  else
    APP_DIR="$STACK_DIR"
  fi
fi

export GWALA_APP_DIR="$APP_DIR"
export GWALA_STACK_DIR="${GWALA_STACK_DIR:-$STACK_DIR}"

cd "$STACK_DIR"
exec docker compose -f "$STACK_DIR/compose.yaml" run --rm gwala "$@"
