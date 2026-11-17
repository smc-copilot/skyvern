"""Positive/negative tests for the 2026-11-17 PR-00 semantic clarifications."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.unit.enterprise_pr00_loader import ENTERPRISE_SCRIPTS, load_enterprise_module

dirty_policy = load_enterprise_module("dirty_policy")
evidence_policy = load_enterprise_module("evidence_policy")
check_ci = load_enterprise_module("check_protected_ci_jobs")
vnc_oracle = load_enterprise_module("vnc_oracle")
constants = load_enterprise_module("constants")

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dirty_read_only_allows_dirty() -> None:
    report = dirty_policy.evaluate_dirty(
        operation=dirty_policy.DirtyOperation.READ_ONLY_DIAGNOSTIC,
        dirty=True,
    )
    assert report["allowed"] is True
    assert report["release_eligible"] is False
    assert report["auto_stash_or_reset"] is False


def test_dirty_sync_is_blocked() -> None:
    with pytest.raises(Exception) as exc:
        dirty_policy.evaluate_dirty(operation="baseline_sync", dirty=True)
    assert getattr(exc.value, "code", None) == "WORKTREE_DIRTY"


def test_dirty_build_requires_explicit_flag_and_never_releases() -> None:
    with pytest.raises(Exception) as exc:
        dirty_policy.evaluate_dirty(operation="allow_dirty_dev_build", dirty=True, allow_dirty_flag=False)
    assert getattr(exc.value, "code", None) == "WORKTREE_DIRTY"
    report = dirty_policy.evaluate_dirty(
        operation="allow_dirty_dev_build",
        dirty=True,
        allow_dirty_flag=True,
        build_tag="1.0.57-aaaaaaaaaaaa-dirty",
    )
    assert report["release_eligible"] is False
    with pytest.raises(Exception) as exc2:
        dirty_policy.evaluate_dirty(
            operation="allow_dirty_dev_build",
            dirty=True,
            allow_dirty_flag=True,
            build_tag="1.0.57-aaaaaaaaaaaa",
        )
    assert getattr(exc2.value, "code", None) == "DIRTY_RELEASE_BUILD"


def test_dirty_release_gate_never_passes() -> None:
    with pytest.raises(Exception) as exc:
        dirty_policy.evaluate_dirty(operation="release_gate", dirty=True, release_eligible=True)
    assert getattr(exc.value, "code", None) == "DIRTY_RELEASE_BUILD"


def test_enterprise_scripts_do_not_stash_or_reset() -> None:
    for relpath in (
        "scripts/enterprise/build_images.sh",
        "scripts/enterprise/verify_upstream_baseline.py",
        "scripts/enterprise/preflight.py",
        "scripts/enterprise/git_state.py",
    ):
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        dirty_policy.assert_script_does_not_mutate_worktree(text, path=relpath)


def test_evidence_policy_accepts_this_repository() -> None:
    report = evidence_policy.check_repo(REPO_ROOT)
    assert report["raw_authority"] == constants.RAW_EVIDENCE_RELPATH
    assert report["managed_summary"] == constants.MANAGED_EVIDENCE_RELPATH
    assert report["history_entries"] >= 1


def test_evidence_policy_rejects_secret_and_wrong_authority() -> None:
    document = json.loads((REPO_ROOT / constants.MANAGED_EVIDENCE_RELPATH).read_text(encoding="utf-8"))
    bad = dict(document)
    bad["current"] = dict(document["current"], api_token="leak")
    with pytest.raises(Exception) as exc:
        evidence_policy.validate_managed_summary(bad)
    assert getattr(exc.value, "code", None) == "EVIDENCE_SECRET_IN_MANAGED"
    wrong = dict(document)
    policy = dict(document["evidence_policy"], raw_authority="docs/enterprise")
    wrong["evidence_policy"] = policy
    with pytest.raises(Exception) as exc2:
        evidence_policy.validate_managed_summary(wrong)
    assert getattr(exc2.value, "code", None) == "EVIDENCE_AUTHORITY_CONFLICT"


def test_evidence_import_copies_into_unmanaged_authority(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    raw = repo / ".enterprise-data" / "evidence" / "pr-00"
    raw.mkdir(parents=True)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "preflight.json").write_text("{}\n", encoding="utf-8")
    manifest = evidence_policy.import_external_evidence(repo, external)
    assert manifest["git_add_performed"] is False
    assert (raw / "imported" / "preflight.json").is_file()
    assert (raw / "imported" / "import-manifest.json").is_file()


def test_protected_ci_inventory_matches_repository() -> None:
    report = check_ci.check_inventory(REPO_ROOT)
    assert report["existing_protected_job_ids"] == [
        "pre-commit",
        "pytest",
        "test",
        "fe-lint-build",
        "pip-package-smoke",
    ]
    assert report["check_run_count_not_required"] is True
    assert report["previous_sha_check_count_16_not_binding"] is True


def test_protected_ci_detects_removed_and_added_jobs(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  pre-commit:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (workflows / "enterprise-build.yml").write_text(
        "jobs:\n  backend-build:\n    runs-on: ubuntu-latest\n  ui-build:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (workflows / "auto-merge-sync.yml").write_text(
        "jobs:\n  auto-merge:\n    if: github.repository == 'Skyvern-AI/skyvern'\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (workflows / "zizmor.yml").write_text(
        "jobs:\n  zizmor:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception) as exc:
        check_ci.check_inventory(tmp_path)
    assert getattr(exc.value, "code", None) == "CI_JOB_REMOVED"

    extra = tmp_path / "with-extra"
    extra.mkdir()
    # Copy real workflows and add a job.
    dest = extra / ".github" / "workflows"
    dest.mkdir(parents=True)
    for name in ("ci.yml", "enterprise-build.yml", "auto-merge-sync.yml", "zizmor.yml"):
        (dest / name).write_text((REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    ci_text = (dest / "ci.yml").read_text(encoding="utf-8")
    (dest / "ci.yml").write_text(ci_text + "\n  brand-new-job:\n    runs-on: ubuntu-latest\n", encoding="utf-8")
    with pytest.raises(Exception) as exc2:
        check_ci.check_inventory(extra)
    assert getattr(exc2.value, "code", None) == "CI_JOB_ADDED"


def test_expected_skip_is_not_failure() -> None:
    job = {"expected_skip_on_fork_pr": True, "path_filter_may_omit": False}
    assert check_ci.classify_run(job, run_present=True, conclusion="skipped") == "EXPECTED_SKIP_OK"
    omit = {"expected_skip_on_fork_pr": False, "path_filter_may_omit": True}
    assert check_ci.classify_run(omit, run_present=False, conclusion=None) == "ABSENT_OK"
    required = {"expected_skip_on_fork_pr": False, "path_filter_may_omit": False}
    assert check_ci.classify_run(required, run_present=False, conclusion=None) == "MISSING_RUN"
    assert check_ci.classify_run(required, run_present=True, conclusion="skipped") == "UNEXPECTED_SKIP"


def _ws_frame(payload: bytes) -> bytes:
    header = bytearray([0x82, len(payload)])
    return bytes(header) + payload


def test_vnc_oracle_accepts_websocket_rfb_and_rejects_http_200() -> None:
    ready = threading.Event()
    port_holder: dict[str, int] = {}

    def serve_rfb() -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port_holder["port"] = server.getsockname()[1]
        server.listen(1)
        server.settimeout(2)
        ready.set()
        try:
            conn, _addr = server.accept()
        except TimeoutError:
            server.close()
            return
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            conn.sendall(_ws_frame(b"RFB 003.008\n"))
            time.sleep(0.2)
        server.close()

    thread = threading.Thread(target=serve_rfb, daemon=True)
    thread.start()
    assert ready.wait(2)
    report = vnc_oracle.probe_vnc("127.0.0.1", port_holder["port"], timeout_s=2)
    assert report["ok"] is True
    assert report["http_upgrade"] == 101
    assert report["rfb_banner_present"] is True
    thread.join(2)

    class HtmlHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>not vnc</html>")

        def log_message(self, format: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), HtmlHandler)
    http_thread = threading.Thread(target=httpd.handle_request, daemon=True)
    http_thread.start()
    html_port = httpd.server_address[1]
    with pytest.raises(Exception) as exc:
        vnc_oracle.probe_vnc("127.0.0.1", html_port, timeout_s=2)
    assert getattr(exc.value, "code", None) == "VNC_HTTP_NOT_WEBSOCKET"
    http_thread.join(2)
    httpd.server_close()


def test_vnc_oracle_closed_port_fails() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(Exception) as exc:
        vnc_oracle.probe_vnc("127.0.0.1", port, timeout_s=1)
    assert getattr(exc.value, "code", None) == "VNC_PORT_CLOSED"


def test_vnc_oracle_101_without_rfb_fails() -> None:
    ready = threading.Event()
    port_holder: dict[str, int] = {}

    def serve() -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port_holder["port"] = server.getsockname()[1]
        server.listen(1)
        server.settimeout(2)
        ready.set()
        try:
            conn, _addr = server.accept()
        except TimeoutError:
            server.close()
            return
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            conn.sendall(_ws_frame(b"hello-not-rfb"))
            time.sleep(0.2)
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(2)
    with pytest.raises(Exception) as exc:
        vnc_oracle.probe_vnc("127.0.0.1", port_holder["port"], timeout_s=2)
    assert getattr(exc.value, "code", None) == "VNC_RFB_MISSING"
    thread.join(2)


def test_inventory_schema_file_exists() -> None:
    path = ENTERPRISE_SCRIPTS / "schemas" / "protected-ci-jobs.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["jobs"]
    ids = [job["job_id"] for job in data["jobs"] if job["class"] == "existing_protected"]
    assert ids == ["pre-commit", "pytest", "test", "fe-lint-build", "pip-package-smoke"]
