#!/usr/bin/env python3
"""Dirty-worktree policy for PR-00 (GAP-DIRTY-BOUNDARY clarification).

本轮澄清决策: Dirty is classified by operation. Scripts never stash, reset,
or restore the worktree. Dirty metadata is never Release PASS.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from errors import EnterpriseError
from git_state import is_dirty, porcelain_status

FORBIDDEN_MUTATIONS = (
    "git stash",
    "git reset --hard",
    "git checkout --force",
    "git restore --source",
    "git clean -fd",
)


class DirtyOperation(StrEnum):
    """Allowed dirty-handling modes."""

    READ_ONLY_DIAGNOSTIC = "read_only_diagnostic"
    BASELINE_SYNC = "baseline_sync"
    ALLOW_DIRTY_DEV_BUILD = "allow_dirty_dev_build"
    RELEASE_GATE = "release_gate"


def evaluate_dirty(
    *,
    operation: DirtyOperation | str,
    dirty: bool,
    allow_dirty_flag: bool = False,
    build_tag: str | None = None,
    release_eligible: bool | None = None,
) -> dict[str, Any]:
    """Return a machine-readable dirty decision. Raises on forbidden combinations."""
    op = DirtyOperation(operation)
    report: dict[str, Any] = {
        "operation": op.value,
        "worktree_dirty": dirty,
        "allow_dirty_flag": allow_dirty_flag,
        "allowed": True,
        "release_eligible": False,
        "auto_stash_or_reset": False,
    }
    if op is DirtyOperation.READ_ONLY_DIAGNOSTIC:
        report["release_eligible"] = False
        return report
    if op is DirtyOperation.BASELINE_SYNC:
        if dirty:
            raise EnterpriseError("WORKTREE_DIRTY", "refusing Git sync on a dirty worktree")
        report["release_eligible"] = False
        return report
    if op is DirtyOperation.ALLOW_DIRTY_DEV_BUILD:
        if dirty and not allow_dirty_flag:
            raise EnterpriseError(
                "WORKTREE_DIRTY",
                "build requires a clean worktree unless --allow-dirty is set",
            )
        if dirty:
            if build_tag is not None and not build_tag.endswith("-dirty"):
                raise EnterpriseError("DIRTY_RELEASE_BUILD", "dirty build_tag must end with -dirty")
            report["release_eligible"] = False
            return report
        report["release_eligible"] = False
        return report
    if op is DirtyOperation.RELEASE_GATE:
        if dirty:
            raise EnterpriseError("DIRTY_RELEASE_BUILD", "dirty worktree is never Release PASS")
        if release_eligible is False:
            raise EnterpriseError("DIRTY_RELEASE_BUILD", "release_eligible is false")
        report["release_eligible"] = True
        return report
    raise EnterpriseError("BUILD_PROVENANCE_MISMATCH", f"unknown dirty operation {op}")


def assert_script_does_not_mutate_worktree(text: str, *, path: str) -> None:
    """Fail when a script would stash/reset the Git worktree."""
    lowered = text.lower()
    for needle in FORBIDDEN_MUTATIONS:
        if needle in lowered:
            raise EnterpriseError(
                "DESTRUCTIVE_CLEANUP_DETECTED",
                f"{path} contains forbidden worktree mutation {needle!r}",
            )


def snapshot_dirty(repo_root: Path) -> dict[str, Any]:
    """Read-only dirty snapshot for diagnostics."""
    status = porcelain_status(repo_root)
    return {
        "worktree_dirty": is_dirty(repo_root),
        "git_status_porcelain": status,
        "operation": DirtyOperation.READ_ONLY_DIAGNOSTIC.value,
    }
