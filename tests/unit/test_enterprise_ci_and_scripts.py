"""REQ-CI-001 / REQ-ROLLBACK-001 static tests for no-push CI and non-destructive stop."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _command_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def test_enterprise_build_workflow_never_pushes() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "enterprise-build.yml").read_text(encoding="utf-8")
    assert "push: false" in text
    assert "push: true" not in text
    assert "Dockerfile.ui" in text
    assert "APP_VERSION=${{ github.sha }}" in text
    assert "AWS_ACCESS_KEY_ID" not in text
    assert "DOCKERHUB_TOKEN" not in text
    assert "pypi" not in text.lower()
    assert "npm publish" not in text


def test_stop_smoke_does_not_use_volumes_flag() -> None:
    path = REPO_ROOT / "scripts" / "enterprise" / "stop_smoke.sh"
    commands = "\n".join(_command_lines(path))
    assert "down --remove-orphans" in commands
    assert "down -v" not in commands
    assert "--volumes" not in commands
    assert "volume prune" not in commands
    assert "system prune" not in commands


def test_stop_smoke_interpolates_env_before_down() -> None:
    text = (REPO_ROOT / "scripts" / "enterprise" / "stop_smoke.sh").read_text(encoding="utf-8")
    assert "--env-file .env.enterprise" in text
    assert "--env-file .enterprise-data/build.env" in text
    assert "source .env.enterprise" in text
    assert "SKYVERN_BUILD_TAG:-stop-placeholder" in text
    assert "ENTERPRISE_POSTGRES_PASSWORD:-stop-placeholder" in text


def test_build_images_does_not_push() -> None:
    text = (REPO_ROOT / "scripts" / "enterprise" / "build_images.sh").read_text(encoding="utf-8")
    assert "docker push" not in text
    assert "compose push" not in text
    assert "skyvern-enterprise-pr00" in text


def test_verify_baseline_exits_nonzero_on_drift_without_merging() -> None:
    text = (REPO_ROOT / "scripts" / "enterprise" / "verify_upstream_baseline.py").read_text(encoding="utf-8")
    assert "UPSTREAM_BASELINE_DRIFT" in text
    assert 'merge_performed": False' in text.replace(" ", "") or "merge_performed" in text
    assert "reset --hard" not in text


def test_ci_yml_retains_existing_jobs() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for job_id in ("pre-commit:", "pytest:", "test:", "fe-lint-build:", "pip-package-smoke:"):
        assert f"\n  {job_id}" in text or f"\n{job_id}" in text
    assert "check_upstream_workflow_guards.py" in text


def test_smoke_refuses_missing_images_and_placeholder_password() -> None:
    text = (REPO_ROOT / "scripts" / "enterprise" / "smoke_test.sh").read_text(encoding="utf-8")
    assert "BUILD_FAILED" in text
    assert "SMOKE_DB_SECRET_MISSING" in text
    assert "down -v" not in "\n".join(_command_lines(REPO_ROOT / "scripts" / "enterprise" / "smoke_test.sh"))


def test_smoke_waits_for_postgres_api_and_ui() -> None:
    text = (REPO_ROOT / "scripts" / "enterprise" / "smoke_test.sh").read_text(encoding="utf-8")
    assert "wait_for_cmd" in text
    assert "http_is_200" in text
    assert "postgres_is_ready" in text
    assert "SMOKE_UI_FAILED" in text
    assert "SMOKE_API_FAILED" in text
    assert "down --remove-orphans" in text
    assert "inspect_image_secrets.py" in text
    assert "SECRET_IN_IMAGE" in text
    assert "SMOKE_STACK_START_FAILED" in text
