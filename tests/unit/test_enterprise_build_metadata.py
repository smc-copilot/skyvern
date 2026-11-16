"""REQ-BUILD-001 / A-BUILD-001 / A-BUILD-002 tests for build identity metadata."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.unit.enterprise_pr00_loader import ENTERPRISE_SCRIPTS, load_enterprise_module

build_metadata = load_enterprise_module("build_metadata")
constants = load_enterprise_module("constants")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path, *, dirty: bool) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "pr00@example.test")
    _git(repo, "config", "user.name", "PR00")
    (repo / "pyproject.toml").write_text('[project]\nname = "skyvern"\nversion = "1.0.57"\n', encoding="utf-8")
    _git(repo, "add", "pyproject.toml")
    _git(repo, "commit", "-m", "init")
    if dirty:
        (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    return repo


def test_clean_metadata_schema_and_tag(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, dirty=False)
    output = tmp_path / "out"
    document = build_metadata.collect_metadata(repo)
    build_metadata.write_metadata(output, document)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert document["schema_version"] == "1.0"
    assert document["repository"] == "smc-copilot/skyvern"
    assert document["source_commit"] == sha
    assert document["source_version"] == "1.0.57"
    assert document["source_dirty"] is False
    assert document["build_tag"] == f"1.0.57-{sha[:12]}"
    assert not document["build_tag"].endswith("-dirty")
    assert document["ui_app_version"] == sha
    assert document["backend_image"] == f"local/smc-copilot-skyvern-backend:{document['build_tag']}"
    assert document["ui_image"] == f"local/smc-copilot-skyvern-ui:{document['build_tag']}"
    assert document["backend_image_digest"] is None
    assert document["ui_image_digest"] is None
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ENTERPRISE_SCRIPTS / "schemas" / "build-metadata.schema.json").read_text())
    jsonschema.validate(document, schema)
    env = (output / "build.env").read_text(encoding="utf-8")
    assert "PASSWORD" not in env.upper()
    assert "SECRET" not in env.upper()
    assert f"SKYVERN_BUILD_SHA={sha}" in env
    assert "SKYVERN_BUILD_DIRTY=false" in env


def test_dirty_metadata_is_not_release_eligible(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, dirty=True)
    document = build_metadata.collect_metadata(repo)
    assert document["source_dirty"] is True
    assert document["build_tag"].endswith("-dirty")
    release_eligible = not document["source_dirty"]
    assert release_eligible is False


def test_secret_like_field_rejected() -> None:
    document = build_metadata.metadata_dict(
        source_commit_sha="a" * 40,
        source_version="1.0.57",
        source_dirty=False,
        built_at_utc="2026-11-16T00:00:00Z",
    )
    document["api_key"] = "should-not-exist"
    with pytest.raises(Exception) as exc:
        build_metadata.validate_metadata(document)
    assert getattr(exc.value, "code", None) == "BUILD_PROVENANCE_MISMATCH"


def test_backfill_preserves_source_identity() -> None:
    document = build_metadata.metadata_dict(
        source_commit_sha="b" * 40,
        source_version="1.0.57",
        source_dirty=False,
        built_at_utc="2026-11-16T00:00:00Z",
    )
    updated = build_metadata.backfill_digests(document, "sha256:backend", "sha256:ui")
    assert updated["source_commit"] == "b" * 40
    assert updated["backend_image_digest"] == "sha256:backend"
    assert updated["ui_image_digest"] == "sha256:ui"
    assert updated["ui_app_version"] == updated["source_commit"]
