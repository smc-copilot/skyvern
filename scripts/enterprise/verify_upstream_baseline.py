#!/usr/bin/env python3
"""Verify the pinned upstream SHA and refuse sync when main has drifted.

This script never merge/rebase/reset. A non-zero exit with
UPSTREAM_BASELINE_DRIFT is the required gate, not a license to retarget SHA.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from constants import (
    PINNED_UPSTREAM_SHA,
    PINNED_UPSTREAM_VERSION,
    UPSTREAM_REMOTE_URL,
    UPSTREAM_REPOSITORY,
)
from errors import EnterpriseError
from git_state import (
    SHA_RE,
    assert_clean_worktree_for_sync,
    assert_fork_identity,
    porcelain_status,
    remotes,
    repo_root_from_cwd,
    run_git,
    source_commit,
)
from project_version import read_project_version


def ls_remote_main(url: str) -> str:
    """Return the current SHA of refs/heads/main at url."""
    result = subprocess.run(
        ["git", "ls-remote", url, "refs/heads/main"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise EnterpriseError("UPSTREAM_FETCH_FAILED", result.stderr.strip() or "git ls-remote failed")
    line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    sha = line.split()[0] if line else ""
    if not SHA_RE.fullmatch(sha):
        raise EnterpriseError("UPSTREAM_SHA_NOT_FOUND", f"could not parse ls-remote output: {line!r}")
    return sha


def merge_base_with_pin(repo_root: Path) -> str | None:
    """Return merge-base with the pinned SHA when the object is present locally."""
    result = run_git(repo_root, ["cat-file", "-t", PINNED_UPSTREAM_SHA], check=False)
    if result.returncode != 0:
        return None
    base = run_git(repo_root, ["merge-base", "HEAD", PINNED_UPSTREAM_SHA], check=False)
    if base.returncode != 0:
        return None
    return base.stdout.strip()


def collect_baseline(repo_root: Path, *, require_clean_for_sync: bool) -> dict[str, Any]:
    """Verify pin identity and report drift. Never mutates Git."""
    assert_fork_identity(repo_root)
    if require_clean_for_sync:
        assert_clean_worktree_for_sync(repo_root)
    upstream_urls = {name: url for name, url in remotes(repo_root).items() if "Skyvern-AI/skyvern" in url}
    if "upstream" in remotes(repo_root) and remotes(repo_root)["upstream"] not in {
        UPSTREAM_REMOTE_URL,
        UPSTREAM_REMOTE_URL.removesuffix(".git"),
    }:
        raise EnterpriseError("UPSTREAM_REMOTE_INVALID", remotes(repo_root)["upstream"])
    upstream_head = ls_remote_main(UPSTREAM_REMOTE_URL)
    drifted = upstream_head != PINNED_UPSTREAM_SHA
    pin_is_ancestor = merge_base_with_pin(repo_root) == PINNED_UPSTREAM_SHA
    report = {
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_remote_url": UPSTREAM_REMOTE_URL,
        "pinned_upstream_sha": PINNED_UPSTREAM_SHA,
        "pinned_upstream_version": PINNED_UPSTREAM_VERSION,
        "upstream_main_sha": upstream_head,
        "fork_head": source_commit(repo_root),
        "fork_pyproject_version": read_project_version(repo_root),
        "pin_is_ancestor_of_head": pin_is_ancestor,
        "upstream_baseline_drift": drifted,
        "worktree_dirty": bool(porcelain_status(repo_root).strip()),
        "existing_upstream_remotes": sorted(upstream_urls),
        "sync_performed": False,
        "merge_performed": False,
        "rebase_performed": False,
        "reset_hard_count": 0,
        "force_push_count": 0,
    }
    if drifted:
        report["error_code"] = "UPSTREAM_BASELINE_DRIFT"
        report["message"] = (
            f"upstream main is {upstream_head}, pinned SHA is {PINNED_UPSTREAM_SHA}. "
            "Refusing merge/rebase/SHA substitution."
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--require-clean-for-sync",
        action="store_true",
        help="Treat a dirty worktree as WORKTREE_DIRTY (sync/merge entry). Default is inspect-only.",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
    output_dir = args.output_dir if args.output_dir else repo_root / ".enterprise-data" / "evidence" / "pr-00"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        report = collect_baseline(repo_root, require_clean_for_sync=args.require_clean_for_sync)
        (output_dir / "upstream-baseline.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        if report.get("error_code") == "UPSTREAM_BASELINE_DRIFT":
            print("UPSTREAM_BASELINE_DRIFT", file=sys.stderr)
            print(report.get("message", ""), file=sys.stderr)
            return 1
        return 0
    except EnterpriseError as exc:
        payload = {
            "error_code": exc.code,
            "message": exc.message,
            "pinned_upstream_sha": PINNED_UPSTREAM_SHA,
            "sync_performed": False,
        }
        (output_dir / "upstream-baseline.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
