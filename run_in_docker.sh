#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec docker compose -f compose.yaml run --rm gwala "$@"
