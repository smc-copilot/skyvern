"""REQ-CI-002 / A-WF-001 tests for upstream side-effect workflow guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.enterprise_pr00_loader import load_enterprise_module

check_guards_mod = load_enterprise_module("check_upstream_workflow_guards")
constants = load_enterprise_module("constants")
workflow_yaml = load_enterprise_module("workflow_yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_required_jobs_are_guarded_in_this_repository() -> None:
    report = check_guards_mod.check_guards(REPO_ROOT)
    assert report["missing_guard_count"] == 0
    assert report["guard_repository"] == "Skyvern-AI/skyvern"
    assert report["guarded_workflow_job_count"] >= 7
    job_ids = {job["job_id"] for job in report["jobs"]}
    assert job_ids == {
        "auto-merge",
        "build-docker-image",
        "create-release",
        "sync",
        "build-sdk",
        "publish-sdk",
        "build-and-publish-sdk",
    }


def test_missing_guard_is_reported(tmp_path: Path) -> None:
    for relpath, job_ids in constants.REQUIRED_WORKFLOW_GUARDS.items():
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        body = ["name: x", "jobs:"]
        for job_id in job_ids:
            body.append(f"  {job_id}:")
            if relpath.endswith("auto-merge-sync.yml") and job_id == "auto-merge":
                body.append("    runs-on: ubuntu-latest")
            else:
                body.append("    if: github.repository == 'Skyvern-AI/skyvern'")
                body.append("    runs-on: ubuntu-latest")
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
    with pytest.raises(Exception) as exc:
        check_guards_mod.check_guards(tmp_path)
    assert getattr(exc.value, "code", None) == "UPSTREAM_WORKFLOW_GUARD_MISSING"


def test_changed_job_id_is_reported(tmp_path: Path) -> None:
    for relpath, job_ids in constants.REQUIRED_WORKFLOW_GUARDS.items():
        path = tmp_path / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        body = ["name: x", "jobs:"]
        for job_id in job_ids:
            renamed = "not-the-job" if relpath.endswith("auto-merge-sync.yml") else job_id
            body.extend(
                [
                    f"  {renamed}:",
                    "    if: github.repository == 'Skyvern-AI/skyvern'",
                    "    runs-on: ubuntu-latest",
                ]
            )
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
    with pytest.raises(Exception) as exc:
        check_guards_mod.check_guards(tmp_path)
    assert getattr(exc.value, "code", None) == "UPSTREAM_WORKFLOW_JOB_CHANGED"


def test_if_block_parser_reads_folded_scalar() -> None:
    text = (
        "jobs:\n"
        "  auto-merge:\n"
        "    if: >\n"
        "      github.repository == 'Skyvern-AI/skyvern' &&\n"
        "      contains(join(github.event.pull_request.labels.*.name, ','), 'sync')\n"
        "    runs-on: ubuntu-latest\n"
    )
    jobs = workflow_yaml.parse_workflow_jobs(text)
    assert workflow_yaml.job_has_repository_guard(jobs["auto-merge"], constants.UPSTREAM_REPO_GUARD)
