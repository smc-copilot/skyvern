#!/usr/bin/env python3
"""Evidence path policy for PR-00 (GAP-EVIDENCE-PATH clarification).

本轮澄清决策:
- Unmanaged raw runtime evidence (gitignored): `.enterprise-data/evidence/pr-00/`
  is the unique authority for original logs, inspect dumps, and screenshots.
- Managed sanitized summary (tracked): `docs/enterprise/pr00-cloud-agent-evidence.json`
  cites a run; it is not the raw authority and cannot upgrade BLOCKED to PASS.
- Workspace-external collection is an import source only. Preflight may write
  there first; importing copies into the unmanaged authority. Import never
  git-adds secrets or raw dumps.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from constants import MANAGED_EVIDENCE_RELPATH, RAW_EVIDENCE_RELPATH
from errors import EnterpriseError
from git_state import repo_root_from_cwd

SECRET_SUBSTRINGS = ("password", "api_key", "token", "secret", "dsn", "cookie")
MANAGED_REQUIRED_TOP = ("schema_version", "evidence_policy", "history", "current")


def raw_authority(repo_root: Path) -> Path:
    """Return the unmanaged raw evidence directory."""
    return (repo_root / RAW_EVIDENCE_RELPATH).resolve()


def managed_summary_path(repo_root: Path) -> Path:
    """Return the tracked sanitized summary path."""
    return repo_root / MANAGED_EVIDENCE_RELPATH


def assert_raw_is_gitignored(repo_root: Path) -> None:
    """Fail when the raw authority path is not ignored."""
    result = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", f"{RAW_EVIDENCE_RELPATH}/dummy"],
        cwd=repo_root,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or ".enterprise-data" not in result.stdout:
        raise EnterpriseError(
            "EVIDENCE_AUTHORITY_CONFLICT",
            f"{RAW_EVIDENCE_RELPATH} must be gitignored unmanaged raw evidence",
        )


def _reject_secret_keys(node: Any, *, trail: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SECRET_SUBSTRINGS):
                raise EnterpriseError(
                    "EVIDENCE_SECRET_IN_MANAGED",
                    f"managed summary has secret-like field {trail}.{key}",
                )
            _reject_secret_keys(value, trail=f"{trail}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _reject_secret_keys(item, trail=f"{trail}[{index}]")


def validate_managed_summary(document: dict[str, Any]) -> None:
    """Validate the tracked summary layer without treating it as raw authority."""
    missing = [field for field in MANAGED_REQUIRED_TOP if field not in document]
    if missing:
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", f"managed summary missing {missing}")
    policy = document["evidence_policy"]
    if policy.get("raw_authority") != RAW_EVIDENCE_RELPATH:
        raise EnterpriseError(
            "EVIDENCE_AUTHORITY_CONFLICT",
            "raw_authority must be .enterprise-data/evidence/pr-00",
        )
    if policy.get("managed_summary") != MANAGED_EVIDENCE_RELPATH:
        raise EnterpriseError(
            "EVIDENCE_AUTHORITY_CONFLICT",
            "managed_summary path mismatch",
        )
    if policy.get("raw_not_git_tracked") is not True:
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", "raw evidence must not be git tracked")
    if not isinstance(document["history"], list) or not document["history"]:
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", "history must retain prior managed summaries")
    current = document["current"]
    if not isinstance(current, dict):
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", "current must be an object")
    if current.get("layer") != "managed_summary":
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", "current.layer must be managed_summary")
    if current.get("raw_authority") != RAW_EVIDENCE_RELPATH:
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", "current cannot claim a second raw authority")
    _reject_secret_keys(document, trail="$")


def import_external_evidence(repo_root: Path, external_dir: Path) -> dict[str, Any]:
    """Copy workspace-external files into the unmanaged authority. Never git-add."""
    if not external_dir.is_dir():
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", f"import source is not a directory: {external_dir}")
    dest = raw_authority(repo_root) / "imported"
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for src in sorted(external_dir.rglob("*")):
        if not src.is_file():
            continue
        relative = src.relative_to(external_dir)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(relative.as_posix())
    manifest = {
        "import_source": str(external_dir),
        "raw_authority": RAW_EVIDENCE_RELPATH,
        "copied_files": copied,
        "git_add_performed": False,
        "note": "External collection is staging only; authority remains the unmanaged directory.",
    }
    (dest / "import-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def check_repo(repo_root: Path) -> dict[str, Any]:
    """Validate ignore rules and the managed summary against this repository."""
    assert_raw_is_gitignored(repo_root)
    path = managed_summary_path(repo_root)
    if not path.is_file():
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", f"missing {MANAGED_EVIDENCE_RELPATH}")
    document = json.loads(path.read_text(encoding="utf-8"))
    validate_managed_summary(document)
    tracked = subprocess.run(
        ["git", "ls-files", RAW_EVIDENCE_RELPATH],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if tracked:
        raise EnterpriseError("EVIDENCE_AUTHORITY_CONFLICT", "raw evidence files are tracked in Git")
    return {
        "raw_authority": RAW_EVIDENCE_RELPATH,
        "managed_summary": MANAGED_EVIDENCE_RELPATH,
        "history_entries": len(document["history"]),
        "current_round": document["current"].get("round"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--import-from", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        report = check_repo(repo_root)
        if args.import_from is not None:
            report["import"] = import_external_evidence(repo_root, args.import_from.resolve())
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
