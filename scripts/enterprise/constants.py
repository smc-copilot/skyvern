"""PR-00 identity constants for the smc-copilot/skyvern fork.

User override (2026-11-16): repository identity, image names, and Fork guards
follow smc-copilot/skyvern rather than the PRD's original loudon84/skyvern
labels. Upstream workflow side-effect jobs remain limited to Skyvern-AI/skyvern.
"""

from __future__ import annotations

ENTERPRISE_REPOSITORY = "smc-copilot/skyvern"
ENTERPRISE_SOURCE_URL = "https://github.com/smc-copilot/skyvern"
UPSTREAM_REPOSITORY = "Skyvern-AI/skyvern"
UPSTREAM_REMOTE_URL = "https://github.com/Skyvern-AI/skyvern.git"
PINNED_UPSTREAM_SHA = "d04ca9c7fd9925216b3dcdc687203e9ee79de351"
PINNED_UPSTREAM_VERSION = "1.0.57"

BACKEND_IMAGE_REPOSITORY = "local/smc-copilot-skyvern-backend"
UI_IMAGE_REPOSITORY = "local/smc-copilot-skyvern-ui"
SOURCE_DIRTY_LABEL = "io.smc-copilot.skyvern.source-dirty"

COMPOSE_PROJECT_NAME = "skyvern-enterprise-pr00"
ENTERPRISE_POSTGRES_USER_DEFAULT = "skyvern_pr00"
ENTERPRISE_POSTGRES_DB_DEFAULT = "skyvern_pr00"

ENTERPRISE_API_PORT_DEFAULT = 18000
ENTERPRISE_VNC_PORT_DEFAULT = 16080
ENTERPRISE_UI_PORT_DEFAULT = 18080
ENTERPRISE_ARTIFACT_PORT_DEFAULT = 19090

OFFICIAL_BACKEND_IMAGE = "public.ecr.aws/skyvern/skyvern:latest"
OFFICIAL_UI_IMAGE = "public.ecr.aws/skyvern/skyvern-ui:latest"

PRODUCTION_VOLUME_MARKERS = (
    "./postgres-data",
    "postgres-data",
    "./artifacts",
    "./videos",
    "./har",
    "./log",
    "./downloads",
    "./browser_sessions",
    "./credential_vault",
    "./.skyvern",
)

ENTERPRISE_DATA_DIRNAME = ".enterprise-data"
RAW_EVIDENCE_RELPATH = ".enterprise-data/evidence/pr-00"
MANAGED_EVIDENCE_RELPATH = "docs/enterprise/pr00-cloud-agent-evidence.json"
BUILD_METADATA_SCHEMA_ID = "ewdac://skyvern/build-metadata/1.1"
BUILD_METADATA_SCHEMA_VERSION = "1.1"
VNC_ORACLE_TIMEOUT_SECONDS = 5
VNC_RFB_PREFIX = b"RFB "
PROTECTED_CI_JOBS_SCHEMA = "protected-ci-jobs.json"

UPSTREAM_REPO_GUARD = "github.repository == 'Skyvern-AI/skyvern'"

REQUIRED_WORKFLOW_GUARDS: dict[str, tuple[str, ...]] = {
    ".github/workflows/auto-merge-sync.yml": ("auto-merge",),
    ".github/workflows/build-docker-image.yml": ("build-docker-image",),
    ".github/workflows/auto-release.yml": ("create-release",),
    ".github/workflows/sync-skyvern-cloud.yml": ("sync",),
    ".github/workflows/sdk-release.yml": ("build-sdk", "publish-sdk"),
    ".github/workflows/ts-sdk-release.yml": ("build-and-publish-sdk",),
}
