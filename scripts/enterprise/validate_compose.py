#!/usr/bin/env python3
"""Validate Enterprise Compose files. Uses docker compose config when Docker exists."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from compose_static import assert_default_compose_unmodified_images, assert_enterprise_override
from constants import (
    BACKEND_IMAGE_REPOSITORY,
    COMPOSE_PROJECT_NAME,
    ENTERPRISE_API_PORT_DEFAULT,
    ENTERPRISE_ARTIFACT_PORT_DEFAULT,
    ENTERPRISE_DATA_DIRNAME,
    ENTERPRISE_UI_PORT_DEFAULT,
    ENTERPRISE_VNC_PORT_DEFAULT,
    OFFICIAL_BACKEND_IMAGE,
    OFFICIAL_UI_IMAGE,
    PRODUCTION_VOLUME_MARKERS,
    UI_IMAGE_REPOSITORY,
)
from errors import EnterpriseError
from git_state import repo_root_from_cwd

FORBIDDEN_PUBLISHED_PORTS = frozenset({8000, 6080, 8080, 9090, 5432})
REQUIRED_PUBLISHED_PORTS = frozenset(
    {
        ENTERPRISE_API_PORT_DEFAULT,
        ENTERPRISE_VNC_PORT_DEFAULT,
        ENTERPRISE_UI_PORT_DEFAULT,
        ENTERPRISE_ARTIFACT_PORT_DEFAULT,
    }
)


def published_ports_from_resolved(resolved: str) -> set[int]:
    """Return host ports published in a `docker compose config` document."""
    ports: set[int] = set()
    for match in re.finditer(r"published:\s*[\"']?(\d+)[\"']?", resolved):
        ports.add(int(match.group(1)))
    return ports


def assert_resolved_isolation(resolved: str) -> dict[str, Any]:
    """Fail if the merged compose still publishes default ports or production mounts."""
    if OFFICIAL_BACKEND_IMAGE in resolved or OFFICIAL_UI_IMAGE in resolved:
        raise EnterpriseError("OFFICIAL_IMAGE_REFERENCE_FOUND", "resolved config still references official latest")
    if BACKEND_IMAGE_REPOSITORY not in resolved or UI_IMAGE_REPOSITORY not in resolved:
        raise EnterpriseError("BUILD_TAG_MISSING", "resolved config missing local image repositories")
    published = published_ports_from_resolved(resolved)
    forbidden = published & FORBIDDEN_PUBLISHED_PORTS
    if forbidden:
        raise EnterpriseError("PORT_CONFLICT", f"resolved compose still publishes {sorted(forbidden)}")
    missing = REQUIRED_PUBLISHED_PORTS - published
    if missing:
        raise EnterpriseError("PORT_CONFLICT", f"resolved compose missing isolated ports {sorted(missing)}")
    for marker in PRODUCTION_VOLUME_MARKERS:
        if f"{marker}:" in resolved and ENTERPRISE_DATA_DIRNAME not in marker:
            raise EnterpriseError("PRODUCTION_VOLUME_REFERENCE", f"resolved config mounts {marker}")
    return {"published_ports": sorted(published), "official_latest_reference_count": 0}


def redact(text: str) -> str:
    """Strip obvious secret assignments before evidence archival."""
    lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if ":" in line and any(
            token in lowered for token in ("password", "api_key", "token", "secret", "database_string")
        ):
            key, _value = line.split(":", 1)
            lines.append(f"{key}: <redacted>")
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def docker_compose_config(repo_root: Path) -> str:
    """Return resolved compose config or raise DOCKER_STATE_UNAVAILABLE."""
    if shutil.which("docker") is None:
        raise EnterpriseError("DOCKER_STATE_UNAVAILABLE", "docker CLI is not installed")
    env_file = repo_root / ".env.enterprise"
    command = [
        "docker",
        "compose",
        "-p",
        COMPOSE_PROJECT_NAME,
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.enterprise.yml",
    ]
    if env_file.is_file():
        command.extend(["--env-file", str(env_file)])
    build_env = repo_root / ".enterprise-data" / "build.env"
    if build_env.is_file():
        command.extend(["--env-file", str(build_env)])
    command.append("config")
    result = subprocess.run(command, cwd=repo_root, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        raise EnterpriseError("SMOKE_STACK_START_FAILED", result.stderr.strip() or "docker compose config failed")
    resolved = result.stdout
    assert_resolved_isolation(resolved)
    return resolved


def collect_report(repo_root: Path) -> dict[str, Any]:
    """Run static checks always; resolved config when Docker is present."""
    assert_default_compose_unmodified_images(repo_root)
    static = assert_enterprise_override(repo_root)
    report: dict[str, Any] = {"static": static, "docker_compose_config_available": False}
    try:
        resolved = docker_compose_config(repo_root)
        report["docker_compose_config_available"] = True
        report["resolved_redacted"] = redact(resolved)
    except EnterpriseError as exc:
        if exc.code == "DOCKER_STATE_UNAVAILABLE":
            report["docker_compose_config_available"] = False
            report["error_code"] = exc.code
        else:
            raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--require-resolved-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        report = collect_report(repo_root)
        output_dir = args.output_dir if args.output_dir else repo_root / ".enterprise-data" / "evidence" / "pr-00"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "compose-config.redacted.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.require_resolved_config and not report.get("docker_compose_config_available"):
            raise EnterpriseError("DOCKER_STATE_UNAVAILABLE", "docker compose config is required but unavailable")
        print(json.dumps({k: v for k, v in report.items() if k != "resolved_redacted"}, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
