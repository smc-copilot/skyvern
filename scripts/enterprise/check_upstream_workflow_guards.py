#!/usr/bin/env python3
"""Fail when required upstream side-effect jobs lack a Fork identity guard.

This check is stdlib-only so ci.yml can run it before uv sync.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from constants import REQUIRED_WORKFLOW_GUARDS, UPSTREAM_REPO_GUARD
from errors import EnterpriseError
from git_state import repo_root_from_cwd
from workflow_yaml import job_has_repository_guard, parse_workflow_jobs


def check_guards(repo_root: Path) -> dict[str, object]:
    """Return a machine-readable guard report. Raises on missing/changed jobs."""
    missing: list[dict[str, str]] = []
    checked: list[dict[str, object]] = []
    for relpath, job_ids in REQUIRED_WORKFLOW_GUARDS.items():
        path = repo_root / relpath
        if not path.is_file():
            raise EnterpriseError("WORKFLOW_GUARD_PARSE_FAILED", f"{relpath} is not a file")
        jobs = parse_workflow_jobs(path.read_text(encoding="utf-8"))
        for job_id in job_ids:
            if job_id not in jobs:
                raise EnterpriseError(
                    "UPSTREAM_WORKFLOW_JOB_CHANGED",
                    f"{relpath} is missing job {job_id}",
                )
            job = jobs[job_id]
            guarded = job_has_repository_guard(job, UPSTREAM_REPO_GUARD)
            checked.append(
                {
                    "workflow": relpath,
                    "job_id": job_id,
                    "guarded": guarded,
                    "if_text": job.if_text,
                }
            )
            if not guarded:
                missing.append({"workflow": relpath, "job_id": job_id})
    if missing:
        raise EnterpriseError(
            "UPSTREAM_WORKFLOW_GUARD_MISSING",
            json.dumps(missing),
        )
    extra_write_workflows = sorted(
        relpath.relative_to(repo_root).as_posix()
        for relpath in (repo_root / ".github" / "workflows").glob("*.yml")
        if relpath.relative_to(repo_root).as_posix() not in REQUIRED_WORKFLOW_GUARDS
        and relpath.name != "enterprise-build.yml"
    )
    return {
        "guard_repository": "Skyvern-AI/skyvern",
        "guarded_workflow_job_count": len(checked),
        "missing_guard_count": 0,
        "jobs": checked,
        "unguarded_write_capable_workflows_not_in_prd_list": extra_write_workflows,
        "note": ("SPEC_SEMANTIC_GAP: PRD lists exactly these jobs. Extra workflows are reported, not auto-guarded."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        report = check_guards(repo_root)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
