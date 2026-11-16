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

# Compose interpolates the whole file before `down`. Load env when present, then
# fill required ${VAR:?} placeholders so teardown cannot get stuck.
set -a
if [[ -f .enterprise-data/build.env ]]; then
  # shellcheck disable=SC1091
  source .enterprise-data/build.env
fi
if [[ -f .env.enterprise ]]; then
  # shellcheck disable=SC1091
  source .env.enterprise
fi
set +a
export SKYVERN_BUILD_TAG="${SKYVERN_BUILD_TAG:-stop-placeholder}"
export ENTERPRISE_POSTGRES_PASSWORD="${ENTERPRISE_POSTGRES_PASSWORD:-stop-placeholder}"

compose_args=(docker compose -p skyvern-enterprise-pr00)
if [[ -f .env.enterprise ]]; then
  compose_args+=(--env-file .env.enterprise)
fi
if [[ -f .enterprise-data/build.env ]]; then
  compose_args+=(--env-file .enterprise-data/build.env)
fi
compose_args+=(-f docker-compose.yml -f docker-compose.enterprise.yml)

"${compose_args[@]}" down --remove-orphans

if [[ ! -d .enterprise-data ]]; then
  echo "SMOKE_STOP_FAILED" >&2
  echo ".enterprise-data is missing after stop" >&2
  exit 1
fi

echo "STOPPED data_retained=true"
