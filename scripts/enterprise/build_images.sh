#!/usr/bin/env bash
# Build local Backend and UI images from the current Fork commit. Never push.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

ALLOW_DIRTY=0
if [[ "${1:-}" == "--allow-dirty" ]]; then
  ALLOW_DIRTY=1
  shift
fi

if [[ ! -f .env.enterprise ]]; then
  echo "ENTERPRISE_ENV_MISSING" >&2
  echo ".env.enterprise is required (copy .env.example, then merge .env.enterprise.example)" >&2
  exit 1
fi

STATUS="$(git status --porcelain --untracked-files=all)"
if [[ -n "$STATUS" && "$ALLOW_DIRTY" -ne 1 ]]; then
  echo "WORKTREE_DIRTY" >&2
  echo "build_images.sh requires a clean worktree unless --allow-dirty is set" >&2
  exit 1
fi

python3 scripts/enterprise/build_metadata.py --output-dir .enterprise-data

set -a
# shellcheck disable=SC1091
source .enterprise-data/build.env
set +a

if ! command -v docker >/dev/null 2>&1; then
  echo "DOCKER_STATE_UNAVAILABLE" >&2
  echo "docker CLI is required to build images; metadata was written with null digests" >&2
  exit 1
fi

export COMPOSE_PROJECT_NAME=skyvern-enterprise-pr00

docker compose \
  -p skyvern-enterprise-pr00 \
  --env-file .env.enterprise \
  --env-file .enterprise-data/build.env \
  -f docker-compose.yml \
  -f docker-compose.enterprise.yml \
  build skyvern skyvern-ui

backend_digest="$(docker image inspect "local/smc-copilot-skyvern-backend:${SKYVERN_BUILD_TAG}" --format '{{.Id}}')"
ui_digest="$(docker image inspect "local/smc-copilot-skyvern-ui:${SKYVERN_BUILD_TAG}" --format '{{.Id}}')"

python3 scripts/enterprise/build_metadata.py \
  --output-dir .enterprise-data \
  --backfill-digests \
  --backend-digest "$backend_digest" \
  --ui-digest "$ui_digest"

mkdir -p .enterprise-data/evidence/pr-00
docker image inspect "local/smc-copilot-skyvern-backend:${SKYVERN_BUILD_TAG}" \
  > .enterprise-data/evidence/pr-00/backend-image-inspect.json
docker image inspect "local/smc-copilot-skyvern-ui:${SKYVERN_BUILD_TAG}" \
  > .enterprise-data/evidence/pr-00/ui-image-inspect.json
cp .enterprise-data/build-metadata.json .enterprise-data/evidence/pr-00/build-metadata.json
