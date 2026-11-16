"""Stdlib parser for GitHub Actions job-level `if:` conditions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowJob:
    """One GitHub Actions job and its job-level if condition, if any."""

    job_id: str
    if_text: str | None
    start_line: int


def _indent(line: str) -> int:
    stripped = line.lstrip(" ")
    if stripped == line:
        return 0
    return len(line) - len(stripped)


def _is_job_key(line: str) -> str | None:
    if _indent(line) != 2:
        return None
    stripped = line.strip()
    if not stripped.endswith(":") or stripped.startswith("#"):
        return None
    key = stripped[:-1].strip()
    if not key or " " in key or key in {"defaults", "permissions", "env", "concurrency"}:
        return None
    if key.startswith(("&", "*")):
        return None
    return key


def parse_workflow_jobs(text: str) -> dict[str, WorkflowJob]:
    """Parse job ids and job-level `if` values from a workflow YAML document.

    This is intentionally a constrained parser: it only understands the job map
    under a top-level `jobs:` key in the workflows in this repository. It does
    not execute expressions.
    """
    lines = text.splitlines()
    in_jobs = False
    jobs: dict[str, WorkflowJob] = {}
    current_id: str | None = None
    current_start = 0
    current_if: str | None = None
    collecting_if = False
    if_lines: list[str] = []
    if_base_indent = 0

    def flush() -> None:
        nonlocal current_id, current_if, collecting_if, if_lines
        if current_id is None:
            return
        if collecting_if:
            current_if = "\n".join(if_lines).strip()
        jobs[current_id] = WorkflowJob(job_id=current_id, if_text=current_if, start_line=current_start)
        current_id = None
        current_if = None
        collecting_if = False
        if_lines = []

    for index, raw in enumerate(lines, start=1):
        if not in_jobs:
            if raw.strip() == "jobs:" and _indent(raw) == 0:
                in_jobs = True
            continue
        if raw.strip() and not raw.startswith(" ") and not raw.startswith("\t") and raw.strip() != "---":
            flush()
            break
        if collecting_if:
            if raw.strip() == "" or raw.lstrip().startswith("#"):
                if_lines.append(raw)
                continue
            if _indent(raw) > if_base_indent:
                if_lines.append(raw.strip())
                continue
            current_if = "\n".join(if_lines).strip()
            collecting_if = False
            if_lines = []
        job_id = _is_job_key(raw)
        if job_id is not None:
            flush()
            current_id = job_id
            current_start = index
            continue
        if current_id is None:
            continue
        stripped = raw.strip()
        if _indent(raw) == 4 and stripped.startswith("if:"):
            value = stripped[3:].strip()
            if value in {">", ">-", "|", "|-"} or value.endswith(">") or value in {">", "|"}:
                collecting_if = True
                if_base_indent = _indent(raw)
                if_lines = []
            elif value.startswith((">", "|")):
                collecting_if = True
                if_base_indent = _indent(raw)
                remainder = value.lstrip(">-|").strip()
                if_lines = [remainder] if remainder else []
            else:
                current_if = value.strip()
    flush()
    return jobs


def job_has_repository_guard(job: WorkflowJob, guard: str) -> bool:
    """Return True when the job-level if contains the exact repository guard."""
    if job.if_text is None:
        return False
    collapsed = " ".join(job.if_text.split())
    return guard in collapsed
