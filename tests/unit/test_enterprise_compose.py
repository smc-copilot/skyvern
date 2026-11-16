"""REQ-COMPOSE-001/002 static Compose tests. Resolved `docker compose config` is separate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.unit.enterprise_pr00_loader import load_enterprise_module

compose_static = load_enterprise_module("compose_static")
constants = load_enterprise_module("constants")
git_state = load_enterprise_module("git_state")

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_enterprise_override_uses_local_images_and_isolated_paths() -> None:
    findings = compose_static.assert_enterprise_override(REPO_ROOT)
    assert findings["official_latest_reference_count"] == 0
    assert findings["backend_image_repository"] == "local/smc-copilot-skyvern-backend"
    assert findings["ui_image_repository"] == "local/smc-copilot-skyvern-ui"


def test_default_compose_keeps_official_images_and_env_defaults() -> None:
    compose_static.assert_default_compose_unmodified_images(REPO_ROOT)
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "public.ecr.aws/skyvern/skyvern:latest" in text
    assert "${SKYVERN_BACKEND_ENV_FILE:-.env}" in text
    assert "${SKYVERN_FRONTEND_ENV_FILE:-skyvern-frontend/.env}" in text


def test_enterprise_example_env_has_no_real_secret_and_empty_ui_key() -> None:
    backend = (REPO_ROOT / ".env.enterprise.example").read_text(encoding="utf-8")
    frontend = (REPO_ROOT / "skyvern-frontend" / ".env.enterprise.example").read_text(encoding="utf-8")
    assert "sk-" not in backend
    assert "postgresql+psycopg://skyvern:skyvern@" not in backend
    assert "YOUR_API_KEY" not in frontend
    assert "VITE_SKYVERN_API_KEY=" in frontend
    assert "localhost:18000" in frontend
    assert "localhost:19090" in frontend


def test_dirty_worktree_blocks_sync(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "pr00@example.test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "PR00"], cwd=repo, check=True, capture_output=True)
    (repo / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "dirty").write_text("nope\n", encoding="utf-8")
    with pytest.raises(Exception) as exc:
        git_state.assert_clean_worktree_for_sync(repo)
    assert getattr(exc.value, "code", None) == "WORKTREE_DIRTY"
