"""Read-only Git helpers for PR-00 preflight, metadata, and sync gates."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from errors import EnterpriseError

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FORK_IDENTITY_RE = re.compile(r"github\.com[:/]+smc-copilot/skyvern(?:\.git)?(?:/|$)", re.IGNORECASE)
UPSTREAM_IDENTITY_RE = re.compile(r"github\.com[:/]+Skyvern-AI/skyvern(?:\.git)?(?:/|$)", re.IGNORECASE)


def sanitize_remote_url(url: str) -> str:
    """Strip credentials from HTTPS remotes before identity matching."""
    return re.sub(r"https://[^@]+@", "https://", url)


def run_git(repo_root: Path, args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command in repo_root and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        text=True,
        capture_output=True,
    )


def repo_root_from_cwd() -> Path:
    """Return the Git toplevel for the current working directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise EnterpriseError("REPO_IDENTITY_MISMATCH", result.stderr.strip() or "not a git repository")
    return Path(result.stdout.strip()).resolve()


def source_commit(repo_root: Path) -> str:
    """Return the 40-character HEAD SHA."""
    sha = run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()
    if not SHA_RE.fullmatch(sha):
        raise EnterpriseError("BUILD_SOURCE_SHA_MISSING", f"HEAD is not a 40-char SHA: {sha!r}")
    return sha


def current_branch(repo_root: Path) -> str:
    """Return the current branch name, or HEAD if detached."""
    result = run_git(repo_root, ["branch", "--show-current"])
    return result.stdout.strip() or "HEAD"


def porcelain_status(repo_root: Path) -> str:
    """Return `git status --porcelain --untracked-files=all` output."""
    return run_git(repo_root, ["status", "--porcelain", "--untracked-files=all"]).stdout


def is_dirty(repo_root: Path) -> bool:
    """Return True when the worktree has staged, unstaged, or untracked files."""
    return bool(porcelain_status(repo_root).strip())


def remotes(repo_root: Path) -> dict[str, str]:
    """Return fetch URLs keyed by remote name."""
    output = run_git(repo_root, ["remote", "-v"]).stdout.splitlines()
    mapping: dict[str, str] = {}
    for line in output:
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "(fetch)":
            mapping[parts[0]] = parts[1]
    return mapping


def origin_matches_fork(repo_root: Path) -> bool:
    """Return True when origin points at smc-copilot/skyvern."""
    url = remotes(repo_root).get("origin", "")
    return bool(FORK_IDENTITY_RE.search(sanitize_remote_url(url)))


def remote_matches_upstream(url: str) -> bool:
    """Return True for HTTPS or SSH remotes that point at Skyvern-AI/skyvern."""
    return bool(UPSTREAM_IDENTITY_RE.search(sanitize_remote_url(url)))


def assert_fork_identity(repo_root: Path) -> None:
    """Raise REPO_IDENTITY_MISMATCH when origin is not smc-copilot/skyvern."""
    if not origin_matches_fork(repo_root):
        raise EnterpriseError(
            "REPO_IDENTITY_MISMATCH",
            "origin remote is not smc-copilot/skyvern",
        )


def assert_clean_worktree_for_sync(repo_root: Path) -> None:
    """Raise WORKTREE_DIRTY when sync/merge is not allowed."""
    status = porcelain_status(repo_root)
    if status.strip():
        raise EnterpriseError("WORKTREE_DIRTY", "refusing Git sync on a dirty worktree")


def short_sha(sha: str) -> str:
    """Return the 12-character source identity prefix used in build tags."""
    if not SHA_RE.fullmatch(sha):
        raise EnterpriseError("BUILD_SOURCE_SHA_MISSING", f"invalid SHA {sha!r}")
    return sha[:12]
