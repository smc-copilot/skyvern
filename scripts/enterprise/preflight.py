#!/usr/bin/env python3
"""Read-only PR-00 workspace preflight. Does not modify Git, files, or containers."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from constants import ENTERPRISE_REPOSITORY
from errors import EnterpriseError
from git_state import (
    assert_fork_identity,
    current_branch,
    origin_matches_fork,
    porcelain_status,
    remotes,
    repo_root_from_cwd,
    run_git,
    source_commit,
)


def _sanitize_remote_url(url: str) -> str:
    if "://" in url and "@" in url.split("://", 1)[1]:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{rest.split('@', 1)[1]}"
    return url


def docker_state() -> dict[str, Any]:
    """Return a read-only Docker snapshot, or an unavailable marker."""
    if shutil.which("docker") is None:
        return {"available": False, "error_code": "DOCKER_STATE_UNAVAILABLE"}
    commands = {
        "docker_ps": ["docker", "ps", "--no-trunc", "--format", "{{json .}}"],
        "docker_compose_version": ["docker", "compose", "version"],
    }
    snapshot: dict[str, Any] = {"available": True}
    for key, command in commands.items():
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        snapshot[key] = {
            "exit_code": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-1000:],
        }
        if result.returncode != 0 and key == "docker_ps":
            snapshot["available"] = False
            snapshot["error_code"] = "DOCKER_STATE_UNAVAILABLE"
    return snapshot


def collect_preflight(repo_root: Path) -> dict[str, Any]:
    """Assemble the Git + Docker preflight report."""
    assert_fork_identity(repo_root)
    status = porcelain_status(repo_root)
    report = {
        "repository": ENTERPRISE_REPOSITORY,
        "repo_root": str(repo_root),
        "branch": current_branch(repo_root),
        "source_commit": source_commit(repo_root),
        "remotes": {name: _sanitize_remote_url(url) for name, url in remotes(repo_root).items()},
        "origin_matches_fork": origin_matches_fork(repo_root),
        "git_status_porcelain": status,
        "worktree_dirty": bool(status.strip()),
        "recent_commits": run_git(repo_root, ["log", "--oneline", "-20"]).stdout.strip().splitlines(),
        "submodule_status": run_git(repo_root, ["submodule", "status"], check=False).stdout.strip(),
        "docker": docker_state(),
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_unique_commits_vs_origin_main": run_git(
            repo_root, ["log", "--oneline", "origin/main..HEAD"], check=False
        )
        .stdout.strip()
        .splitlines(),
        "codeblock_sample_search": "GOLDEN_CODEBLOCK_NOT_FOUND",
        "note": (
            "This cloud workspace is not the user's production host. Production "
            "container identity remains UNKNOWN. See SPEC_SEMANTIC_GAP GAP-PRODUCTION-IDENTITY."
        ),
    }
    return report


def write_preflight(report: dict[str, Any], output_dir: Path) -> Path:
    """Write preflight.json and git-status-before.txt."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "preflight.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "git-status-before.txt").write_text(report["git_status_porcelain"], encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        output_dir = args.output_dir if args.output_dir else repo_root / ".enterprise-data" / "evidence" / "pr-00"
        report = collect_preflight(repo_root)
        write_preflight(report, output_dir)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
