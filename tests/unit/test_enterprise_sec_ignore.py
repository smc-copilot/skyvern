"""REQ-SEC-001 / A-SEC-001 ignore-rule tests. Image filesystem checks need Docker."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.unit.enterprise_pr00_loader import load_enterprise_module

compose_static = load_enterprise_module("compose_static")

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_and_dockerignore_cover_enterprise_paths() -> None:
    flags = compose_static.inspect_ignore_files(REPO_ROOT)
    assert flags["gitignore_env_enterprise"] is True
    assert flags["gitignore_frontend_env_enterprise"] is True
    assert flags["gitignore_enterprise_data"] is True
    assert flags["dockerignore_enterprise_data"] is True


def test_git_check_ignore_matches_secret_files() -> None:
    env_match = subprocess.check_output(
        ["git", "check-ignore", "-v", "--no-index", ".env.enterprise"],
        cwd=REPO_ROOT,
        text=True,
    )
    ui_match = subprocess.check_output(
        ["git", "check-ignore", "-v", "--no-index", "skyvern-frontend/.env.enterprise"],
        cwd=REPO_ROOT,
        text=True,
    )
    data_match = subprocess.check_output(
        ["git", "check-ignore", "-v", "--no-index", ".enterprise-data/postgres/dummy"],
        cwd=REPO_ROOT,
        text=True,
    )
    assert ".env.enterprise" in env_match
    assert "skyvern-frontend/.env.enterprise" in ui_match
    assert ".enterprise-data" in data_match
    tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True).splitlines()
    assert ".env.enterprise" not in tracked
    assert "skyvern-frontend/.env.enterprise" not in tracked
    assert not any(path.startswith(".enterprise-data/") for path in tracked)


def test_example_files_are_present_and_not_secret() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    others = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO_ROOT, text=True)
    visible = tracked + "\n" + others
    assert (REPO_ROOT / ".env.enterprise.example").is_file()
    assert (REPO_ROOT / "skyvern-frontend" / ".env.enterprise.example").is_file()
    assert "YOUR_API_KEY" not in (REPO_ROOT / "skyvern-frontend" / ".env.enterprise.example").read_text()
    assert ".env.enterprise.example" in visible
