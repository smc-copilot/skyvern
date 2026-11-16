#!/usr/bin/env bash
# Stop the isolated PR-00 Compose project without deleting data.
# Forbidden: compose down with the volumes flag.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "DOCKER_STATE_UNAVAILABLE" >&2
  exit 1
fi

docker compose \
  -p skyvern-enterprise-pr00 \
  -f docker-compose.yml \
  -f docker-compose.enterprise.yml \
  down --remove-orphans

if [[ ! -d .enterprise-data ]]; then
  echo "SMOKE_STOP_FAILED" >&2
  echo ".enterprise-data is missing after stop" >&2
  exit 1
fi

echo "STOPPED data_retained=true"
