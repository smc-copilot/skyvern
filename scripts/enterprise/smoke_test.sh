#!/usr/bin/env bash
# Start the isolated PR-00 Compose project and check Postgres / API / UI.
# Never connects to production volumes. Never runs docker compose down -v.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
EVIDENCE=".enterprise-data/evidence/pr-00"
mkdir -p "$EVIDENCE" .enterprise-data/{postgres,artifacts,videos,har,log,downloads,browser_sessions,credential_vault,.skyvern}

if [[ ! -f .env.enterprise || ! -f skyvern-frontend/.env.enterprise ]]; then
  echo "ENTERPRISE_ENV_MISSING" >&2
  exit 1
fi

if grep -Eq '^ENTERPRISE_POSTGRES_PASSWORD=(replace-with-a-random-alphanumeric-value)?[[:space:]]*$' .env.enterprise; then
  echo "SMOKE_DB_SECRET_MISSING" >&2
  echo "Set ENTERPRISE_POSTGRES_PASSWORD in .env.enterprise to a random alphanumeric value" >&2
  exit 1
fi

if [[ ! -f .enterprise-data/build.env || ! -f .enterprise-data/build-metadata.json ]]; then
  echo "BUILD_TAG_MISSING" >&2
  echo "Run scripts/enterprise/build_images.sh first" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .enterprise-data/build.env
# shellcheck disable=SC1091
source .env.enterprise
set +a

python3 scripts/enterprise/validate_compose.py --require-resolved-config --output-dir "$EVIDENCE"

if ! python3 - <<'PY'
import json
import sys
from pathlib import Path

def fail(code: str, message: str) -> None:
    print(code, file=sys.stderr)
    print(message, file=sys.stderr)
    raise SystemExit(1)

meta = json.loads(Path(".enterprise-data/build-metadata.json").read_text())
if meta.get("metadata_state") != "acceptance":
    fail("BUILD_METADATA_STATE_INVALID", "Smoke requires acceptance metadata, not draft")
if not meta.get("backend_image_digest") or not meta.get("ui_image_digest"):
    fail("BUILD_FAILED", "Refusing to start Smoke Stack without image digests")
if meta.get("source_dirty") and meta.get("release_eligible"):
    fail("DIRTY_RELEASE_BUILD", "dirty metadata cannot be release_eligible")
PY
then
  exit 1
fi

check_port() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    print(f"PORT_CONFLICT port {port} is already bound", file=sys.stderr)
    sys.exit(1)
finally:
    sock.close()
PY
}

check_port "${ENTERPRISE_API_PORT:-18000}"
check_port "${ENTERPRISE_VNC_PORT:-16080}"
check_port "${ENTERPRISE_UI_PORT:-18080}"
check_port "${ENTERPRISE_ARTIFACT_PORT:-19090}"

if ! command -v docker >/dev/null 2>&1; then
  echo "DOCKER_STATE_UNAVAILABLE" >&2
  exit 1
fi

enterprise_compose() {
  docker compose \
    -p skyvern-enterprise-pr00 \
    --env-file .env.enterprise \
    --env-file .enterprise-data/build.env \
    -f docker-compose.yml \
    -f docker-compose.enterprise.yml \
    "$@"
}

wait_for_cmd() {
  local timeout_s="$1"
  shift
  local start now
  start="$(date +%s)"
  while true; do
    if "$@"; then
      return 0
    fi
    now="$(date +%s)"
    if (( now - start >= timeout_s )); then
      return 1
    fi
    sleep 2
  done
}

http_is_200() {
  local url="$1"
  local dest="$2"
  local code
  code="$(curl -sS -D "${dest}.hdr" -o "${dest}.body" -w '%{http_code}' "$url" || true)"
  {
    cat "${dest}.hdr" 2>/dev/null || true
    echo
    cat "${dest}.body" 2>/dev/null || true
    printf '\nhttp_status=%s\n' "${code:-000}"
  } > "$dest"
  [[ "$code" == "200" ]]
}

postgres_is_ready() {
  docker compose -p skyvern-enterprise-pr00 exec -T postgres \
    pg_isready -U "${ENTERPRISE_POSTGRES_USER:-skyvern_pr00}" -d "${ENTERPRISE_POSTGRES_DB:-skyvern_pr00}"
}

cleanup_on_fail() {
  local code="$1"
  echo "$code" >&2
  mkdir -p "$EVIDENCE/smoke-logs"
  enterprise_compose logs > "$EVIDENCE/smoke-logs/compose.log" 2>&1 || true
  enterprise_compose down --remove-orphans >/dev/null 2>&1 || true
}

if ! enterprise_compose up -d; then
  cleanup_on_fail "SMOKE_STACK_START_FAILED"
  exit 1
fi

mkdir -p "$EVIDENCE/smoke-logs"

if ! wait_for_cmd 90 postgres_is_ready; then
  cleanup_on_fail "SMOKE_DB_NOT_READY"
  exit 1
fi
postgres_is_ready > "$EVIDENCE/postgres-health.txt"

alembic_out="$(docker compose -p skyvern-enterprise-pr00 exec -T postgres \
  psql -U "${ENTERPRISE_POSTGRES_USER:-skyvern_pr00}" -d "${ENTERPRISE_POSTGRES_DB:-skyvern_pr00}" -tAc \
  "SELECT version_num FROM alembic_version;" || true)"
printf '%s\n' "$alembic_out" > "$EVIDENCE/alembic-version.txt"
if [[ -z "${alembic_out// }" ]]; then
  cleanup_on_fail "SMOKE_MIGRATION_FAILED"
  exit 1
fi

if ! wait_for_cmd 240 http_is_200 \
  "http://127.0.0.1:${ENTERPRISE_API_PORT:-18000}/api/v1/heartbeat" \
  "$EVIDENCE/api-heartbeat.txt"; then
  cleanup_on_fail "SMOKE_API_FAILED"
  exit 1
fi

if ! wait_for_cmd 180 http_is_200 \
  "http://127.0.0.1:${ENTERPRISE_UI_PORT:-18080}/" \
  "$EVIDENCE/dashboard-http.txt"; then
  cleanup_on_fail "SMOKE_UI_FAILED"
  exit 1
fi

if ! python3 scripts/enterprise/inspect_image_secrets.py --output-dir "$EVIDENCE"; then
  cleanup_on_fail "SECRET_IN_IMAGE"
  exit 1
fi

# VNC oracle is independent of Dashboard GET /. HTTP 200 on :18080 is not VNC PASS.
if ! wait_for_cmd 90 python3 scripts/enterprise/vnc_oracle.py \
  --host 127.0.0.1 \
  --port "${ENTERPRISE_VNC_PORT:-16080}" \
  --output "$EVIDENCE/vnc-oracle.json"; then
  cleanup_on_fail "SMOKE_VNC_FAILED"
  exit 1
fi

echo "SMOKE_OK"
