#!/usr/bin/env python3
"""Enumerate and detect add/remove of protected CI jobs (GAP-CI-EXISTING-JOBS).

本轮澄清决策: Compare workflow+job_id against the committed inventory.
Do not require GitHub check-run count 16. expected_skip_on_fork_pr skipped
runs are not failures. path_filter_may_omit missing runs are not failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from constants import UPSTREAM_REPO_GUARD
from errors import EnterpriseError
from git_state import repo_root_from_cwd
from workflow_yaml import parse_workflow_jobs

INVENTORY_PATH = Path(__file__).resolve().parent / "schemas" / "protected-ci-jobs.json"


def load_inventory() -> dict[str, Any]:
    """Load the committed protected job inventory."""
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def classify_run(
    job: dict[str, Any],
    *,
    run_present: bool,
    conclusion: str | None,
) -> str:
    """Classify a GitHub run conclusion against inventory skip semantics."""
    if not run_present:
        if job.get("path_filter_may_omit"):
            return "ABSENT_OK"
        if job.get("expected_skip_on_fork_pr"):
            return "MISSING_RUN"
        return "MISSING_RUN"
    if conclusion == "success":
        return "OK"
    if conclusion == "skipped" and job.get("expected_skip_on_fork_pr"):
        return "EXPECTED_SKIP_OK"
    if conclusion == "skipped":
        return "UNEXPECTED_SKIP"
    if conclusion in {"failure", "timed_out", "cancelled"}:
        return "FAILED"
    return "UNKNOWN"


def check_inventory(repo_root: Path) -> dict[str, Any]:
    """Compare committed workflows to the inventory. Fail on add/remove."""
    inventory = load_inventory()
    jobs = inventory["jobs"]
    removed: list[dict[str, str]] = []
    added: list[dict[str, str]] = []
    checked: list[dict[str, Any]] = []
    workflows = sorted({job["workflow"] for job in jobs})
    parsed: dict[str, dict[str, Any]] = {}
    for relpath in workflows:
        path = repo_root / relpath
        if not path.is_file():
            raise EnterpriseError("CI_JOB_REMOVED", f"{relpath} is missing")
        parsed[relpath] = parse_workflow_jobs(path.read_text(encoding="utf-8"))
    inventory_ids = {(job["workflow"], job["job_id"]) for job in jobs}
    for job in jobs:
        relpath = job["workflow"]
        job_id = job["job_id"]
        if job_id not in parsed[relpath]:
            removed.append({"workflow": relpath, "job_id": job_id})
            continue
        parsed_job = parsed[relpath][job_id]
        skip_guarded = False
        if parsed_job.if_text:
            skip_guarded = UPSTREAM_REPO_GUARD in " ".join(parsed_job.if_text.split())
        if job.get("expected_skip_on_fork_pr") and not skip_guarded:
            raise EnterpriseError(
                "CI_SKIP_SEMANTICS_MISMATCH",
                f"{relpath} job {job_id} is inventory-expected-skip but has no upstream repo guard",
            )
        checked.append(
            {
                "workflow": relpath,
                "job_id": job_id,
                "class": job["class"],
                "expected_skip_on_fork_pr": job.get("expected_skip_on_fork_pr", False),
                "path_filter_may_omit": job.get("path_filter_may_omit", False),
                "if_text": parsed_job.if_text,
            }
        )
    for relpath, job_map in parsed.items():
        for job_id in job_map:
            if (relpath, job_id) not in inventory_ids:
                added.append({"workflow": relpath, "job_id": job_id})
    if removed:
        raise EnterpriseError("CI_JOB_REMOVED", json.dumps(removed))
    if added:
        raise EnterpriseError("CI_JOB_ADDED", json.dumps(added))
    existing = [job for job in jobs if job["class"] == "existing_protected"]
    return {
        "inventory_job_count": len(jobs),
        "existing_protected_job_ids": [job["job_id"] for job in existing],
        "checked": checked,
        "check_run_count_not_required": True,
        "previous_sha_check_count_16_not_binding": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        repo_root = args.repo_root.resolve() if args.repo_root else repo_root_from_cwd()
        report = check_inventory(repo_root)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
