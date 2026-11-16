#!/usr/bin/env python3
"""Generate PR-00 build identity JSON and a secret-free build.env file.

Order (REQ-BUILD-001 / schema 9.1): write metadata with null digests, then
build images, then backfill digests. This script does not build images.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from constants import (
    BACKEND_IMAGE_REPOSITORY,
    BUILD_METADATA_SCHEMA_VERSION,
    ENTERPRISE_REPOSITORY,
    UI_IMAGE_REPOSITORY,
)
from errors import EnterpriseError
from git_state import is_dirty, repo_root_from_cwd, short_sha, source_commit
from project_version import read_project_version

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "build-metadata.schema.json"
SECRET_SUBSTRINGS = ("password", "api_key", "token", "secret", "dsn", "cookie")


def build_tag(version: str, sha: str, dirty: bool) -> str:
    """Return the Build Tag contract from version, SHA, and dirty state."""
    tag = f"{version}-{short_sha(sha)}"
    if dirty:
        return f"{tag}-dirty"
    return tag


def metadata_dict(
    *,
    source_commit_sha: str,
    source_version: str,
    source_dirty: bool,
    built_at_utc: str,
    backend_image_digest: str | None = None,
    ui_image_digest: str | None = None,
) -> dict[str, Any]:
    """Return a schema-shaped metadata document."""
    tag = build_tag(source_version, source_commit_sha, source_dirty)
    return {
        "schema_version": BUILD_METADATA_SCHEMA_VERSION,
        "repository": ENTERPRISE_REPOSITORY,
        "source_commit": source_commit_sha,
        "source_version": source_version,
        "source_dirty": source_dirty,
        "build_tag": tag,
        "ui_app_version": source_commit_sha,
        "built_at_utc": built_at_utc,
        "backend_image": f"{BACKEND_IMAGE_REPOSITORY}:{tag}",
        "ui_image": f"{UI_IMAGE_REPOSITORY}:{tag}",
        "backend_image_digest": backend_image_digest,
        "ui_image_digest": ui_image_digest,
    }


def load_schema() -> dict[str, Any]:
    """Load the committed JSON Schema document."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_metadata(document: dict[str, Any]) -> None:
    """Validate required fields without adding undeclared properties."""
    schema = load_schema()
    required = schema["required"]
    missing = [field for field in required if field not in document]
    if missing:
        raise EnterpriseError("BUILD_VERSION_MISSING", f"metadata missing fields: {missing}")
    extra = [field for field in document if field not in schema["properties"]]
    if extra:
        raise EnterpriseError("BUILD_PROVENANCE_MISMATCH", f"additionalProperties not allowed: {extra}")
    if document["schema_version"] != BUILD_METADATA_SCHEMA_VERSION:
        raise EnterpriseError("BUILD_PROVENANCE_MISMATCH", "schema_version must be 1.0")
    if document["repository"] != ENTERPRISE_REPOSITORY:
        raise EnterpriseError("REPO_IDENTITY_MISMATCH", f"repository must be {ENTERPRISE_REPOSITORY}")
    from git_state import SHA_RE

    if not SHA_RE.fullmatch(str(document["source_commit"])):
        raise EnterpriseError("BUILD_SOURCE_SHA_MISSING", "source_commit is not a 40-char SHA")
    if document["ui_app_version"] != document["source_commit"]:
        raise EnterpriseError("BUILD_PROVENANCE_MISMATCH", "ui_app_version must equal source_commit")
    dirty = bool(document["source_dirty"])
    tag = str(document["build_tag"])
    if dirty and not tag.endswith("-dirty"):
        raise EnterpriseError("DIRTY_RELEASE_BUILD", "dirty metadata must use a -dirty build_tag")
    if not dirty and tag.endswith("-dirty"):
        raise EnterpriseError("BUILD_PROVENANCE_MISMATCH", "clean metadata must not use a -dirty build_tag")
    for key in document:
        lowered = key.lower()
        if any(part in lowered for part in SECRET_SUBSTRINGS):
            raise EnterpriseError("BUILD_PROVENANCE_MISMATCH", f"secret-like field {key} is not allowed")


def write_build_env(path: Path, document: dict[str, Any]) -> None:
    """Write compose-safe identity variables. No secrets."""
    dirty = "true" if document["source_dirty"] else "false"
    path.write_text(
        (
            f"SKYVERN_BUILD_TAG={document['build_tag']}\n"
            f"SKYVERN_BUILD_SHA={document['source_commit']}\n"
            f"SKYVERN_SOURCE_VERSION={document['source_version']}\n"
            f"SKYVERN_BUILD_DIRTY={dirty}\n"
        ),
        encoding="utf-8",
    )


def collect_metadata(repo_root: Path) -> dict[str, Any]:
    """Read Git / pyproject state and return pre-build metadata."""
    return metadata_dict(
        source_commit_sha=source_commit(repo_root),
        source_version=read_project_version(repo_root),
        source_dirty=is_dirty(repo_root),
        built_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def write_metadata(output_dir: Path, document: dict[str, Any]) -> Path:
    """Validate and write build-metadata.json plus build.env."""
    validate_metadata(document)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "build-metadata.json"
    json_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_build_env(output_dir / "build.env", document)
    return json_path


def backfill_digests(document: dict[str, Any], backend_digest: str | None, ui_digest: str | None) -> dict[str, Any]:
    """Return a copy with image digests filled after a successful build."""
    updated = dict(document)
    updated["backend_image_digest"] = backend_digest
    updated["ui_image_digest"] = ui_digest
    validate_metadata(updated)
    return updated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--backfill-digests",
        action="store_true",
        help="Read existing JSON and fill digest fields from --backend-digest/--ui-digest.",
    )
    parser.add_argument("--backend-digest", default=None)
    parser.add_argument("--ui-digest", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        output_dir = args.output_dir if args.output_dir else repo_root / ".enterprise-data"
        if args.backfill_digests:
            json_path = output_dir / "build-metadata.json"
            document = json.loads(json_path.read_text(encoding="utf-8"))
            document = backfill_digests(document, args.backend_digest, args.ui_digest)
        else:
            document = collect_metadata(repo_root)
        write_metadata(output_dir, document)
        print(json.dumps(document, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
