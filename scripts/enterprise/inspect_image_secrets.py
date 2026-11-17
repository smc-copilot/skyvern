#!/usr/bin/env python3
"""Fail if local Backend/UI images contain enterprise env files or smoke data.

This is a fail-stop filesystem check. It does not classify user production
patches or choose a baseline SHA.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from constants import BACKEND_IMAGE_REPOSITORY, UI_IMAGE_REPOSITORY
from errors import EnterpriseError
from git_state import repo_root_from_cwd

FIND_SCRIPT = "find / -xdev \\( -name .env.enterprise -o -name .enterprise-data \\) 2>/dev/null | head -50"


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise EnterpriseError("DOCKER_STATE_UNAVAILABLE", "docker CLI is not installed")


def list_forbidden_paths(image: str) -> list[str]:
    """Return forbidden paths found inside a local image filesystem."""
    _require_docker()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            FIND_SCRIPT,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise EnterpriseError(
            "BUILD_FAILED",
            f"could not inspect {image}: {result.stderr.strip() or result.stdout.strip()}",
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def inspect_built_images(repo_root: Path) -> dict[str, Any]:
    """Inspect Backend and UI images named in build-metadata.json."""
    meta_path = repo_root / ".enterprise-data" / "build-metadata.json"
    if not meta_path.is_file():
        raise EnterpriseError("BUILD_TAG_MISSING", "build-metadata.json is missing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    backend = meta.get("backend_image") or f"{BACKEND_IMAGE_REPOSITORY}:{meta.get('build_tag')}"
    ui = meta.get("ui_image") or f"{UI_IMAGE_REPOSITORY}:{meta.get('build_tag')}"
    if not meta.get("backend_image_digest") or not meta.get("ui_image_digest"):
        raise EnterpriseError("BUILD_FAILED", "refusing image inspect without digests")
    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend_image": backend,
        "ui_image": ui,
        "backend_forbidden_paths": list_forbidden_paths(backend),
        "ui_forbidden_paths": list_forbidden_paths(ui),
    }
    leaked = report["backend_forbidden_paths"] + report["ui_forbidden_paths"]
    if leaked:
        raise EnterpriseError("SECRET_IN_IMAGE", f"forbidden paths in image: {leaked}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        output_dir = args.output_dir if args.output_dir else repo_root / ".enterprise-data" / "evidence" / "pr-00"
        output_dir.mkdir(parents=True, exist_ok=True)
        report = inspect_built_images(repo_root)
        (output_dir / "image-secret-inspect.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
