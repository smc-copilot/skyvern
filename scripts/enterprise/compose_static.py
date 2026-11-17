"""Static checks of Enterprise Compose files that do not require Docker."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from constants import (
    BACKEND_IMAGE_REPOSITORY,
    COMPOSE_PROJECT_NAME,
    ENTERPRISE_API_PORT_DEFAULT,
    ENTERPRISE_ARTIFACT_PORT_DEFAULT,
    ENTERPRISE_DATA_DIRNAME,
    ENTERPRISE_POSTGRES_DB_DEFAULT,
    ENTERPRISE_UI_PORT_DEFAULT,
    ENTERPRISE_VNC_PORT_DEFAULT,
    OFFICIAL_BACKEND_IMAGE,
    OFFICIAL_UI_IMAGE,
    PRODUCTION_VOLUME_MARKERS,
    UI_IMAGE_REPOSITORY,
)
from errors import EnterpriseError

ENTERPRISE_COMPOSE = "docker-compose.enterprise.yml"
BASE_COMPOSE = "docker-compose.yml"


def _read(repo_root: Path, relpath: str) -> str:
    path = repo_root / relpath
    if not path.is_file():
        raise EnterpriseError("DOCKERFILE_NOT_FOUND", f"{relpath} is not a file")
    return path.read_text(encoding="utf-8")


def assert_default_compose_unmodified_images(repo_root: Path) -> None:
    """Default compose must still reference official latest when used alone."""
    text = _read(repo_root, BASE_COMPOSE)
    if OFFICIAL_BACKEND_IMAGE not in text or OFFICIAL_UI_IMAGE not in text:
        raise EnterpriseError(
            "OFFICIAL_IMAGE_REFERENCE_FOUND",
            "default docker-compose.yml no longer has official latest image references",
        )
    if "${SKYVERN_BACKEND_ENV_FILE:-.env}" not in text:
        raise EnterpriseError("ENTERPRISE_ENV_MISSING", "backend env_file default variable missing")
    if "${SKYVERN_FRONTEND_ENV_FILE:-skyvern-frontend/.env}" not in text:
        raise EnterpriseError("ENTERPRISE_ENV_MISSING", "frontend env_file default variable missing")


def assert_enterprise_override(repo_root: Path) -> dict[str, Any]:
    """Check the override file for isolation and local image names."""
    text = _read(repo_root, ENTERPRISE_COMPOSE)
    findings: dict[str, Any] = {"file": ENTERPRISE_COMPOSE}
    if OFFICIAL_BACKEND_IMAGE in text or OFFICIAL_UI_IMAGE in text:
        raise EnterpriseError("OFFICIAL_IMAGE_REFERENCE_FOUND", "enterprise override still names official latest")
    if f"{BACKEND_IMAGE_REPOSITORY}:" not in text:
        raise EnterpriseError("BUILD_TAG_MISSING", "enterprise backend image repository missing")
    if f"{UI_IMAGE_REPOSITORY}:" not in text:
        raise EnterpriseError("BUILD_TAG_MISSING", "enterprise UI image repository missing")
    if "dockerfile: Dockerfile" not in text and 'dockerfile: "Dockerfile"' not in text:
        raise EnterpriseError("DOCKERFILE_NOT_FOUND", "enterprise backend dockerfile missing")
    if "Dockerfile.ui" not in text:
        raise EnterpriseError("DOCKERFILE_NOT_FOUND", "enterprise UI dockerfile missing")
    if COMPOSE_PROJECT_NAME not in text:
        raise EnterpriseError("SMOKE_STACK_START_FAILED", "compose project name missing from override")
    if ENTERPRISE_POSTGRES_DB_DEFAULT not in text:
        raise EnterpriseError("SMOKE_DATABASE_TARGET_INVALID", "skyvern_pr00 not present")
    if f"{ENTERPRISE_API_PORT_DEFAULT}:8000" not in text and str(ENTERPRISE_API_PORT_DEFAULT) not in text:
        raise EnterpriseError("PORT_CONFLICT", "enterprise API port missing")
    if str(ENTERPRISE_UI_PORT_DEFAULT) not in text:
        raise EnterpriseError("PORT_CONFLICT", "enterprise UI port missing")
    if str(ENTERPRISE_ARTIFACT_PORT_DEFAULT) not in text:
        raise EnterpriseError("PORT_CONFLICT", "enterprise artifact port missing")
    if str(ENTERPRISE_VNC_PORT_DEFAULT) not in text:
        raise EnterpriseError("PORT_CONFLICT", "enterprise VNC port missing")
    if text.count("ports: !override") < 2:
        raise EnterpriseError(
            "PORT_CONFLICT",
            "enterprise ports must use !override so default 8000/6080/8080/9090 are not appended",
        )
    if text.count("env_file: !override") < 2:
        raise EnterpriseError("ENTERPRISE_ENV_MISSING", "enterprise env_file must use !override")
    if text.count("volumes: !override") < 3:
        raise EnterpriseError("PRODUCTION_VOLUME_REFERENCE", "enterprise volumes must use !override")
    for host_map in ("8000:8000", "6080:6080", "8080:8080", "9090:9090"):
        if host_map in text:
            raise EnterpriseError("PORT_CONFLICT", f"default host port mapping {host_map} must not appear in override")
    for marker in PRODUCTION_VOLUME_MARKERS:
        # `./artifacts` etc. must not appear as host mount sources in the override.
        pattern = rf"-\s*{re.escape(marker)}:"
        if re.search(pattern, text):
            raise EnterpriseError("PRODUCTION_VOLUME_REFERENCE", f"override mounts production path {marker}")
    if f"./{ENTERPRISE_DATA_DIRNAME}/postgres:" not in text and f"./{ENTERPRISE_DATA_DIRNAME}/postgres" not in text:
        raise EnterpriseError("PRODUCTION_VOLUME_REFERENCE", "enterprise postgres data dir missing")
    if "5432:5432" in text:
        raise EnterpriseError("PRODUCTION_VOLUME_REFERENCE", "postgres host port mapping is not allowed")
    findings["official_latest_reference_count"] = 0
    findings["backend_image_repository"] = BACKEND_IMAGE_REPOSITORY
    findings["ui_image_repository"] = UI_IMAGE_REPOSITORY
    return findings


def inspect_ignore_files(repo_root: Path) -> dict[str, bool]:
    """Confirm git/docker ignore rules for enterprise secrets and data."""
    gitignore = _read(repo_root, ".gitignore")
    dockerignore = _read(repo_root, ".dockerignore")
    return {
        "gitignore_env_enterprise": ".env.enterprise" in gitignore,
        "gitignore_frontend_env_enterprise": "skyvern-frontend/.env.enterprise" in gitignore,
        "gitignore_enterprise_data": ".enterprise-data/" in gitignore,
        "dockerignore_enterprise_data": ".enterprise-data/" in dockerignore,
        "dockerignore_env_enterprise": ".env.enterprise" in dockerignore,
        "dockerignore_frontend_env_enterprise": "skyvern-frontend/.env.enterprise" in dockerignore
        or "skyvern-frontend/.env*" in dockerignore,
    }
