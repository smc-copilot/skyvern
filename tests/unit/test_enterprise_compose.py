"""REQ-COMPOSE-001/002 static Compose tests. Resolved `docker compose config` is separate."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.enterprise_pr00_loader import load_enterprise_module

compose_static = load_enterprise_module("compose_static")
constants = load_enterprise_module("constants")
git_state = load_enterprise_module("git_state")
validate_compose = load_enterprise_module("validate_compose")

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_enterprise_override_uses_local_images_and_isolated_paths() -> None:
    findings = compose_static.assert_enterprise_override(REPO_ROOT)
    assert findings["official_latest_reference_count"] == 0
    assert findings["backend_image_repository"] == "local/smc-copilot-skyvern-backend"
    assert findings["ui_image_repository"] == "local/smc-copilot-skyvern-ui"


def test_enterprise_compose_overrides_default_host_ports_and_mounts() -> None:
    text = (REPO_ROOT / "docker-compose.enterprise.yml").read_text(encoding="utf-8")
    assert text.count("ports: !override") >= 2
    assert text.count("env_file: !override") >= 2
    assert text.count("volumes: !override") >= 3
    assert "8000:8000" not in text
    assert "6080:6080" not in text
    assert "8080:8080" not in text
    assert "9090:9090" not in text


def test_upstream_remote_accepts_ssh_and_https() -> None:
    assert git_state.remote_matches_upstream("https://github.com/Skyvern-AI/skyvern.git")
    assert git_state.remote_matches_upstream("https://github.com/Skyvern-AI/skyvern")
    assert git_state.remote_matches_upstream("git@github.com:Skyvern-AI/skyvern.git")
    assert git_state.remote_matches_upstream("ssh://git@github.com/Skyvern-AI/skyvern.git")
    assert not git_state.remote_matches_upstream("git@github.com:other/skyvern.git")
    assert not git_state.remote_matches_upstream("https://github.com/smc-copilot/skyvern.git")


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


def test_resolved_isolation_rejects_default_published_ports() -> None:
    resolved = """
services:
  skyvern:
    image: local/smc-copilot-skyvern-backend:tag
    ports:
      - published: "8000"
        target: 8000
      - published: "18000"
        target: 8000
  skyvern-ui:
    image: local/smc-copilot-skyvern-ui:tag
    ports:
      - published: "18080"
        target: 8080
      - published: "19090"
        target: 9090
"""
    with pytest.raises(Exception) as exc:
        validate_compose.assert_resolved_isolation(resolved)
    assert getattr(exc.value, "code", None) == "PORT_CONFLICT"


def test_resolved_isolation_accepts_enterprise_ports_only() -> None:
    resolved = """
services:
  skyvern:
    image: local/smc-copilot-skyvern-backend:tag
    ports:
      - published: "18000"
        target: 8000
      - published: "16080"
        target: 6080
  skyvern-ui:
    image: local/smc-copilot-skyvern-ui:tag
    ports:
      - published: "18080"
        target: 8080
      - published: "19090"
        target: 9090
"""
    findings = validate_compose.assert_resolved_isolation(resolved)
    assert findings["published_ports"] == [16080, 18000, 18080, 19090]


def _docker_daemon_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(["docker", "info"], check=False, capture_output=True, text=True)
    return result.returncode == 0


@pytest.mark.skipif(not _docker_daemon_available(), reason="docker daemon unavailable")
def test_live_docker_compose_config_uses_isolated_ports(tmp_path: Path) -> None:
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "ENTERPRISE_POSTGRES_PASSWORD=ciisolatedplaceholder\n"
        "SKYVERN_BUILD_TAG=ci-isolated-placeholder\n"
        "SKYVERN_BUILD_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "SKYVERN_SOURCE_VERSION=0.0.0-test\n"
        "SKYVERN_BUILD_DIRTY=true\n"
        "SKYVERN_BACKEND_ENV_FILE=.env.enterprise.example\n"
        "SKYVERN_FRONTEND_ENV_FILE=skyvern-frontend/.env.enterprise.example\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "ENTERPRISE_POSTGRES_PASSWORD": "ciisolatedplaceholder",
            "SKYVERN_BUILD_TAG": "ci-isolated-placeholder",
            "SKYVERN_BUILD_SHA": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "SKYVERN_SOURCE_VERSION": "0.0.0-test",
            "SKYVERN_BUILD_DIRTY": "true",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "skyvern-enterprise-pr00-configtest",
            "--env-file",
            str(env_file),
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.enterprise.yml",
            "config",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    findings = validate_compose.assert_resolved_isolation(result.stdout)
    assert 8000 not in findings["published_ports"]
    assert 8080 not in findings["published_ports"]
    assert findings["published_ports"] == [16080, 18000, 18080, 19090]


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
