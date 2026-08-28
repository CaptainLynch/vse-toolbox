# -*- coding: utf-8 -*-
"""Focused offline tests for Scheduled Archive Admin Web API routes and security guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.scheduled_archive_admin import ScheduledArchiveAdminService
from services.scheduled_archive_runner import (
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
)


@pytest.fixture()
def test_db(monkeypatch, tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary SQLite database for web API tests."""
    db_file = tmp_path / "web_api_test.db"
    db_instance = DatabaseManager(db_path=db_file)
    db_instance.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)
    return db_instance


@pytest.fixture()
def fake_runner() -> MagicMock:
    """Provide a canned runner without creating background schedulers or external I/O."""
    runner = MagicMock(spec=ArchiveSyncRunner)
    runner.run_once.return_value = ArchiveRunOnceResult(
        results=(
            ArchiveJobRunResult(
                job_id=1,
                job_key="aras_ewo",
                outcome="completed",
                run_id=101,
                final_state="success",
            ),
        ),
        dry_run=False,
    )
    return runner


@pytest.fixture()
def service_spies(monkeypatch):
    """Spy on ScheduledArchiveAdminService mutation methods to verify guard isolation."""
    orig_update_job = ScheduledArchiveAdminService.update_job
    orig_sync_now = ScheduledArchiveAdminService.sync_now
    spy_update = MagicMock(side_effect=orig_update_job)
    spy_sync = MagicMock(side_effect=orig_sync_now)
    monkeypatch.setattr(ScheduledArchiveAdminService, "update_job", spy_update)
    monkeypatch.setattr(ScheduledArchiveAdminService, "sync_now", spy_sync)
    return {"update_job": spy_update, "sync_now": spy_sync}


@pytest.fixture()
def client(monkeypatch, test_db: DatabaseManager, fake_runner: MagicMock):
    """Provide a Flask test client configured with isolated DB and fake runner."""
    monkeypatch.setattr(
        web_app,
        "ScheduledArchiveAdminService",
        lambda db: ScheduledArchiveAdminService(db, runner_factory=lambda _db: fake_runner),
    )
    app = web_app.create_app()
    # Isolated API tests use fake opaque aliases; production availability is
    # covered separately with an injected provider.
    app.extensions["scheduled_archive_admin"].set_credential_provider(None)
    app.config.update(TESTING=True)
    return app.test_client()


def _loopback_headers(
    host: str = "localhost:5000",
    origin: str | None = "http://localhost:5000",
    sec_fetch_site: str | None = "same-origin",
) -> dict[str, str]:
    """Helper to build safe loopback request headers."""
    headers: dict[str, str] = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    if sec_fetch_site is not None:
        headers["Sec-Fetch-Site"] = sec_fetch_site
    return headers


# ── 1. GET /api/scheduled-archive/jobs ────────────────────────────────────────


def test_get_jobs_returns_200_and_no_store(client) -> None:
    """GET jobs returns 200, no-store header, and exactly six sanitized jobs."""
    resp = client.get("/api/scheduled-archive/jobs")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"

    body = resp.get_json()
    assert body["ok"] is True
    jobs = body["data"]
    assert len(jobs) == 6

    for job in jobs:
        assert isinstance(job["id"], int)
        assert isinstance(job["jobKey"], str)
        assert job["intervalMinutes"] == 60
        assert isinstance(job["enabled"], bool)
        assert isinstance(job["credentialConfigured"], bool)
        assert isinstance(job["allowedFilterNames"], list)
        assert "credential_ref" not in job
        assert "credentialRef" not in job
        assert "lease_token" not in job
        assert "leaseToken" not in job


def test_get_jobs_server_error_returns_500_no_store(client, monkeypatch) -> None:
    """GET jobs returns 500 with no-store and exact error shape when service raises unexpected error."""
    monkeypatch.setattr(
        ScheduledArchiveAdminService,
        "list_jobs",
        MagicMock(side_effect=RuntimeError("db query exploded")),
    )

    resp = client.get("/api/scheduled-archive/jobs")
    assert resp.status_code == 500
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "db query exploded",
        },
    }


# ── 2. Loopback, Host, Sec-Fetch-Site, and Origin Security Guards ─────────────


@pytest.mark.parametrize(
    ("remote_addr", "host", "origin"),
    [
        ("127.0.0.1", "localhost:5000", "http://localhost:5000"),
        ("127.0.0.1", "127.0.0.1:5000", "http://127.0.0.1:5000"),
        ("127.0.0.2", "127.0.0.2:8000", "http://127.0.0.2:8000"),
        ("::1", "localhost:5000", "http://localhost:5000"),
        ("::1", "[::1]:5000", "http://[::1]:5000"),
        ("::ffff:127.0.0.1", "127.0.0.1:5000", "http://127.0.0.1:5000"),
        ("::ffff:127.0.0.1", "[::ffff:127.0.0.1]:5000", "http://[::ffff:127.0.0.1]:5000"),
        ("::ffff:127.0.0.1", "localhost:5000", "http://localhost:5000"),
        ("127.0.0.1", "[::ffff:127.0.0.1]:5000", "http://[::ffff:127.0.0.1]:5000"),
        ("127.0.0.1", "localhost:5000", None),  # omitted Origin is valid for same-origin
    ],
)
def test_mutation_accepts_valid_loopback_remote_and_host(
    client,
    remote_addr: str,
    host: str,
    origin: str | None,
) -> None:
    """PATCH and sync-now accept loopback remote + matching loopback Host and Origin."""
    headers = _loopback_headers(host=host, origin=origin)
    environ = {"REMOTE_ADDR": remote_addr, "HTTP_HOST": host}

    # Test sync-now
    resp_sync = client.post(
        "/api/scheduled-archive/jobs/aras_ewo/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp_sync.status_code == 200
    assert resp_sync.headers.get("Cache-Control") == "no-store"

    # Test PATCH (with invalid body just to assert security gate passed to validation)
    resp_patch = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json="non_dict_body",
        headers=headers,
        environ_base=environ,
    )
    assert resp_patch.status_code == 400
    assert resp_patch.headers.get("Cache-Control") == "no-store"


@pytest.mark.parametrize(
    "mutation_route",
    [
        ("POST", "/api/scheduled-archive/jobs/aras_ewo/sync-now"),
        ("PATCH", "/api/scheduled-archive/jobs/aras_ewo"),
    ],
)
@pytest.mark.parametrize(
    "non_loopback_remote",
    ["192.168.1.100", "10.0.0.1", "8.8.8.8", "172.16.0.5", "2001:db8::1"],
)
def test_mutation_rejects_non_loopback_remote(
    client,
    service_spies: dict[str, MagicMock],
    mutation_route: tuple[str, str],
    non_loopback_remote: str,
) -> None:
    """Mutations reject non-loopback remote_addr before invoking service."""
    method, endpoint = mutation_route
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": non_loopback_remote}
    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if method == "PATCH":
        kwargs["json"] = {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"}

    resp = client.open(endpoint, method=method, **kwargs)
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "LocalAccessRequired",
            "message": "此操作仅允许从本机访问",
        },
    }
    service_spies["update_job"].assert_not_called()
    service_spies["sync_now"].assert_not_called()


@pytest.mark.parametrize(
    "mutation_route",
    [
        ("POST", "/api/scheduled-archive/jobs/aras_ewo/sync-now"),
        ("PATCH", "/api/scheduled-archive/jobs/aras_ewo"),
    ],
)
@pytest.mark.parametrize(
    "bad_host",
    ["example.com", "evil.com:5000", "192.168.1.50:5000", "attacker.local", "bad:host:colon:5000"],
)
def test_mutation_rejects_non_loopback_or_malformed_host(
    client,
    service_spies: dict[str, MagicMock],
    mutation_route: tuple[str, str],
    bad_host: str,
) -> None:
    """Mutations reject non-loopback or malformed Host before invoking service."""
    method, endpoint = mutation_route
    headers = _loopback_headers(host=bad_host, origin=None)
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": bad_host}
    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if method == "PATCH":
        kwargs["json"] = {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"}

    resp = client.open(endpoint, method=method, **kwargs)
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "LocalAccessRequired",
            "message": "请求主机不受信任",
        },
    }
    service_spies["update_job"].assert_not_called()
    service_spies["sync_now"].assert_not_called()


@pytest.mark.parametrize(
    "mutation_route",
    [
        ("POST", "/api/scheduled-archive/jobs/aras_ewo/sync-now"),
        ("PATCH", "/api/scheduled-archive/jobs/aras_ewo"),
    ],
)
def test_mutation_rejects_cross_site_sec_fetch_site(
    client,
    service_spies: dict[str, MagicMock],
    mutation_route: tuple[str, str],
) -> None:
    """Mutations reject Sec-Fetch-Site: cross-site before invoking service."""
    method, endpoint = mutation_route
    headers = _loopback_headers(sec_fetch_site="cross-site")
    environ = {"REMOTE_ADDR": "127.0.0.1"}
    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if method == "PATCH":
        kwargs["json"] = {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"}

    resp = client.open(endpoint, method=method, **kwargs)
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "CrossSiteRequest",
            "message": "拒绝跨站写操作",
        },
    }
    service_spies["update_job"].assert_not_called()
    service_spies["sync_now"].assert_not_called()


@pytest.mark.parametrize(
    "mutation_route",
    [
        ("POST", "/api/scheduled-archive/jobs/aras_ewo/sync-now"),
        ("PATCH", "/api/scheduled-archive/jobs/aras_ewo"),
    ],
)
@pytest.mark.parametrize(
    "invalid_origin",
    [
        "https://localhost:5000",  # scheme mismatch
        "http://attacker.com",  # host mismatch
        "http://localhost:9999",  # port mismatch
        "http://user:pass@localhost:5000",  # userinfo
        "http://localhost:5000/subpath",  # path
        "http://localhost:5000/?query=1",  # query
        "http://localhost:5000/#fragment",  # fragment
        "invalid-origin-uri",  # malformed
    ],
)
def test_mutation_rejects_invalid_or_mismatched_origin(
    client,
    service_spies: dict[str, MagicMock],
    mutation_route: tuple[str, str],
    invalid_origin: str,
) -> None:
    """Mutations reject invalid/mismatched Origin before invoking service."""
    method, endpoint = mutation_route
    headers = _loopback_headers(origin=invalid_origin)
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": "localhost:5000"}
    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if method == "PATCH":
        kwargs["json"] = {"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"}

    resp = client.open(endpoint, method=method, **kwargs)
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "CrossSiteRequest",
            "message": "请求来源与本机服务不一致",
        },
    }
    service_spies["update_job"].assert_not_called()
    service_spies["sync_now"].assert_not_called()


# ── 3. PATCH /api/scheduled-archive/jobs/<job_key> ────────────────────────────


def test_patch_job_non_json_body_returns_400(client) -> None:
    """PATCH with non-dict / non-JSON body returns 400 ValidationError with no-store."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        data="plain text body",
        content_type="text/plain",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 400
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ValidationError",
            "message": "JSON object body is required",
        },
    }


def test_patch_job_unknown_job_returns_404(client) -> None:
    """PATCH with unknown job key returns 404 NotFound with no-store."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.patch(
        "/api/scheduled-archive/jobs/non_existent_job",
        json={"enabled": False, "filters": {}, "outputSubdir": "", "updatedAt": "2026-08-22T00:00:00Z"},
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 404
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "未找到归档任务",
        },
    }


def test_patch_job_validation_errors_returns_422_with_fields(client) -> None:
    """PATCH with invalid fields returns 422 ValidationError with fields mapping."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": "not_a_bool",
            "filters": "not_a_dict",
            "outputSubdir": 123,
            "updatedAt": "",
        },
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ValidationError",
            "message": "请修正标记的字段",
            "fields": {
                "enabled": "must be a boolean",
                "filters": "must be an object",
                "outputSubdir": "must be a string",
                "updatedAt": "is required",
            },
        },
    }


def test_patch_job_conflicts_and_not_ready_returns_409(client, test_db: DatabaseManager) -> None:
    """PATCH returns 409 Conflict for stale lock / active lease and 409 NotReady for unconfigured alias."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    jobs_resp = client.get("/api/scheduled-archive/jobs")
    job = [j for j in jobs_resp.get_json()["data"] if j["jobKey"] == "aras_ewo"][0]

    # 1. Enabling unconfigured job without alias -> 409 NotReady
    resp_not_ready = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": True,
            "filters": {},
            "outputSubdir": "",
            "updatedAt": job["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert resp_not_ready.status_code == 409
    assert resp_not_ready.headers.get("Cache-Control") == "no-store"
    assert resp_not_ready.get_json() == {
        "ok": False,
        "error": {
            "type": "NotReady",
            "message": "启用任务前必须配置凭据引用",
        },
    }

    # 2. Stale updatedAt -> 409 Conflict
    resp_stale = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "updatedAt": "2020-01-01T00:00:00.000000Z",
        },
        headers=headers,
        environ_base=environ,
    )
    assert resp_stale.status_code == 409
    assert resp_stale.headers.get("Cache-Control") == "no-store"
    assert resp_stale.get_json() == {
        "ok": False,
        "error": {
            "type": "Conflict",
            "message": "任务正在运行或配置已更新，请刷新后重试",
        },
    }

    # 3. Active lease conflict -> 409 Conflict
    # Configure and enable job first so lease can be acquired
    enable_resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": True,
            "credentialRef": "mock_lease_alias",
            "filters": {},
            "outputSubdir": "",
            "updatedAt": job["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert enable_resp.status_code == 200
    enabled_job = enable_resp.get_json()["data"]

    test_db.acquire_archive_job_lease(int(enabled_job["id"]), "sync_now", lease_seconds=900)
    leased_job = [j for j in client.get("/api/scheduled-archive/jobs").get_json()["data"] if j["jobKey"] == "aras_ewo"][0]
    resp_leased = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "updatedAt": leased_job["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert resp_leased.status_code == 409
    assert resp_leased.headers.get("Cache-Control") == "no-store"
    assert resp_leased.get_json() == {
        "ok": False,
        "error": {
            "type": "Conflict",
            "message": "任务正在运行或配置已更新，请刷新后重试",
        },
    }


def test_patch_job_safety_error_returns_422(client) -> None:
    """PATCH with path traversal outputSubdir returns 422 ValidationError."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    jobs_resp = client.get("/api/scheduled-archive/jobs")
    job = [j for j in jobs_resp.get_json()["data"] if j["jobKey"] == "aras_ewo"][0]

    resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": False,
            "filters": {},
            "outputSubdir": "../unsafe_traversal",
            "updatedAt": job["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == "ValidationError"
    assert "fields" in body["error"]
    assert "request" in body["error"]["fields"]


def test_patch_job_success_and_never_reflects_credential_ref(client) -> None:
    """PATCH success returns 200 with no-store and NEVER reflects credentialRef value in response."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    jobs_resp = client.get("/api/scheduled-archive/jobs")
    job = [j for j in jobs_resp.get_json()["data"] if j["jobKey"] == "aras_ewo"][0]

    secret_alias = "vault_secret_alias_key_99999"
    resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": True,
            "credentialRef": secret_alias,
            "filters": {"changeType": "ECR"},
            "outputSubdir": "aras/ewo",
            "updatedAt": job["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"

    response_text = resp.get_data(as_text=True)
    assert secret_alias not in response_text

    data = resp.get_json()["data"]
    assert data["enabled"] is True
    assert data["credentialConfigured"] is True
    assert "credential_ref" not in data
    assert "credentialRef" not in data
    assert data["filters"] == {"changeType": "ECR"}


def test_patch_job_accepts_task_output_directory(client, tmp_path: Path) -> None:
    """The HTTP contract persists an absolute task directory and supports clearing it."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}
    selected = tmp_path / "task-output"
    selected.mkdir()

    job = next(
        item for item in client.get("/api/scheduled-archive/jobs").get_json()["data"]
        if item["jobKey"] == "aras_ewo"
    )
    response = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": False,
            "filters": {},
            "outputSubdir": "",
            "outputDirectory": str(selected),
            "updatedAt": job["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert Path(data["outputDirectory"]).resolve() == selected.resolve()
    assert data["outputSubdir"] == ""


def test_delete_builtin_task_soft_archives_and_removes_it_from_active_api(
    client,
    test_db: DatabaseManager,
) -> None:
    """Built-in task deletion follows the same history-preserving archive contract."""
    headers = _loopback_headers()
    jobs = client.get("/api/scheduled-archive/jobs").get_json()["data"]
    builtin = next(item for item in jobs if item["jobKey"] == "aras_ewo")

    response = client.delete(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={"updatedAt": builtin["updatedAt"]},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["archivedAt"] is not None
    active_keys = {
        item["jobKey"]
        for item in client.get("/api/scheduled-archive/jobs").get_json()["data"]
    }
    assert "aras_ewo" not in active_keys
    archived = next(
        item for item in test_db.list_archive_jobs(include_archived=True)
        if item["job_key"] == "aras_ewo"
    )
    assert archived["archived_at"] is not None


@pytest.mark.parametrize(
    "error_payload_builder",
    [
        # Validation error in filter
        lambda job: {"enabled": False, "credentialRef": "secret_007", "filters": {"unsupported": "bad"}, "outputSubdir": "", "updatedAt": job["updatedAt"]},
        # Validation error in scalar filter type
        lambda job: {"enabled": False, "credentialRef": "secret_007", "filters": {"changeType": 123}, "outputSubdir": "", "updatedAt": job["updatedAt"]},
        # Stale update conflict
        lambda job: {"enabled": False, "credentialRef": "secret_007", "filters": {}, "outputSubdir": "", "updatedAt": "2020-01-01T00:00:00Z"},
        # Safety error
        lambda job: {"enabled": False, "credentialRef": "secret_007", "filters": {}, "outputSubdir": "../escaped", "updatedAt": job["updatedAt"]},
    ],
)
def test_patch_job_errors_never_reflect_credential_ref(client, error_payload_builder) -> None:
    """PATCH error responses NEVER reflect credentialRef value in response text or JSON."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    jobs_resp = client.get("/api/scheduled-archive/jobs")
    job = [j for j in jobs_resp.get_json()["data"] if j["jobKey"] == "aras_ewo"][0]

    secret_alias = "secret_007"
    payload = error_payload_builder(job)
    resp = client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json=payload,
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code in {409, 422}
    assert resp.headers.get("Cache-Control") == "no-store"
    response_text = resp.get_data(as_text=True)
    assert secret_alias not in response_text
    body = resp.get_json()
    assert body["ok"] is False


# ── 4. GET /api/scheduled-archive/runs ─────────────────────────────────────────


def test_get_runs_and_filtering(client, test_db: DatabaseManager) -> None:
    """GET runs returns 200 with no-store, respects jobKey filter, and handles limits / 422 validation."""
    with test_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_archive_runs
                (job_id, job_key, trigger_type, run_state, attempt, record_count, created_at)
            VALUES (1, 'aras_ewo', 'scheduled', 'success', 1, 10, '2026-08-22T10:00:00Z'),
                   (2, 'tdc_sor', 'sync_now', 'success', 1, 20, '2026-08-22T10:05:00Z')
            """
        )

    # 1. All runs
    resp_all = client.get("/api/scheduled-archive/runs")
    assert resp_all.status_code == 200
    assert resp_all.headers.get("Cache-Control") == "no-store"
    assert len(resp_all.get_json()["data"]) >= 2

    # 2. Filtered by jobKey
    resp_filtered = client.get("/api/scheduled-archive/runs?jobKey=aras_ewo")
    assert resp_filtered.status_code == 200
    runs = resp_filtered.get_json()["data"]
    assert len(runs) >= 1
    assert all(r["jobKey"] == "aras_ewo" for r in runs)

    # 3. Unknown jobKey -> 404 NotFound
    resp_unknown = client.get("/api/scheduled-archive/runs?jobKey=unknown_job_key")
    assert resp_unknown.status_code == 404
    assert resp_unknown.headers.get("Cache-Control") == "no-store"
    assert resp_unknown.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "未找到归档任务",
        },
    }

    # 4. Limit parameter handling
    resp_limit = client.get("/api/scheduled-archive/runs?limit=1")
    assert resp_limit.status_code == 200
    assert len(resp_limit.get_json()["data"]) == 1

    # 5. Invalid limit error handling returning 422
    for invalid_limit in ["invalid_str", "0", "-5"]:
        resp_invalid = client.get(f"/api/scheduled-archive/runs?limit={invalid_limit}")
        assert resp_invalid.status_code == 422
        assert resp_invalid.headers.get("Cache-Control") == "no-store"
        assert resp_invalid.get_json() == {
            "ok": False,
            "error": {
                "type": "ValidationError",
                "message": "limit must be a positive integer",
            },
        }


# ── 5. GET /api/scheduled-archive/runs/<run_id>/artifacts ─────────────────────


def test_get_artifacts_endpoint(client, test_db: DatabaseManager) -> None:
    """GET artifacts returns 404 for unknown run and 200 with relative paths only for existing run."""
    # 1. Unknown run_id -> 404 NotFound
    resp_404 = client.get("/api/scheduled-archive/runs/999999/artifacts")
    assert resp_404.status_code == 404
    assert resp_404.headers.get("Cache-Control") == "no-store"
    assert resp_404.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "未找到归档运行",
        },
    }

    # 2. Existing run with artifact
    with test_db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_archive_runs
                (job_id, job_key, trigger_type, run_state, attempt, created_at)
            VALUES (1, 'aras_ewo', 'scheduled', 'success', 1, '2026-08-22T10:00:00Z')
            """
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO scheduled_archive_artifacts
                (run_id, artifact_type, relative_path, display_name, size_bytes, sha256, created_at)
            VALUES (?, 'normalized_csv', 'aras/ewo/20260822/ewo.csv', 'ewo.csv', 512, 'hash123',
                    '2026-08-22T10:00:05Z')
            """,
            (run_id,),
        )

    resp_ok = client.get(f"/api/scheduled-archive/runs/{run_id}/artifacts")
    assert resp_ok.status_code == 200
    assert resp_ok.headers.get("Cache-Control") == "no-store"
    data = resp_ok.get_json()["data"]
    assert data["runId"] == run_id
    assert len(data["artifacts"]) == 1
    artifact = data["artifacts"][0]
    assert artifact["relativePath"] == "aras/ewo/20260822/ewo.csv"
    assert "absolute_path" not in artifact
    assert "absolutePath" not in artifact


# ── 6. GET /api/scheduled-archive/config-audit ────────────────────────────────


def test_get_config_audit_endpoint(client, test_db: DatabaseManager) -> None:
    """GET config-audit returns 200 with no-store, handles jobKey filter, limits, and 422 validation."""
    # 1. Update a job to create an audit record
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}
    jobs = {j["jobKey"]: j for j in client.get("/api/scheduled-archive/jobs").get_json()["data"]}

    client.patch(
        "/api/scheduled-archive/jobs/aras_ewo",
        json={
            "enabled": False,
            "filters": {"state": "Released"},
            "outputSubdir": "",
            "updatedAt": jobs["aras_ewo"]["updatedAt"],
        },
        headers=headers,
        environ_base=environ,
    )

    # 2. Query all audit
    resp_all = client.get("/api/scheduled-archive/config-audit")
    assert resp_all.status_code == 200
    assert resp_all.headers.get("Cache-Control") == "no-store"
    assert len(resp_all.get_json()["data"]) >= 1

    # 3. Query filtered by jobKey
    resp_filtered = client.get("/api/scheduled-archive/config-audit?jobKey=aras_ewo")
    assert resp_filtered.status_code == 200
    assert len(resp_filtered.get_json()["data"]) >= 1

    # 4. Unknown jobKey -> 404 NotFound
    resp_unknown = client.get("/api/scheduled-archive/config-audit?jobKey=unknown_job_key")
    assert resp_unknown.status_code == 404
    assert resp_unknown.headers.get("Cache-Control") == "no-store"
    assert resp_unknown.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "未找到归档任务",
        },
    }

    # 5. Limit parameter handling
    resp_limit = client.get("/api/scheduled-archive/config-audit?limit=1")
    assert resp_limit.status_code == 200
    assert len(resp_limit.get_json()["data"]) == 1

    # 6. Invalid limit error handling returning 422
    for invalid_limit in ["invalid_str", "0", "-5"]:
        resp_invalid = client.get(f"/api/scheduled-archive/config-audit?limit={invalid_limit}")
        assert resp_invalid.status_code == 422
        assert resp_invalid.headers.get("Cache-Control") == "no-store"
        assert resp_invalid.get_json() == {
            "ok": False,
            "error": {
                "type": "ValidationError",
                "message": "limit must be a positive integer",
            },
        }


# ── 7. POST /api/scheduled-archive/jobs/<job_key>/sync-now ────────────────────


def test_post_sync_now_endpoint(client, fake_runner: MagicMock) -> None:
    """POST sync-now triggers runner, returns 200 with no-store, and 404 on unknown job."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    # 1. Unknown job_key -> 404 NotFound
    resp_404 = client.post(
        "/api/scheduled-archive/jobs/unknown_job_key/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp_404.status_code == 404
    assert resp_404.headers.get("Cache-Control") == "no-store"
    assert resp_404.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "未找到归档任务",
        },
    }

    # 2. Valid job_key -> 200 OK
    resp_200 = client.post(
        "/api/scheduled-archive/jobs/aras_ewo/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp_200.status_code == 200
    assert resp_200.headers.get("Cache-Control") == "no-store"

    fake_runner.run_once.assert_called_once_with(
        trigger_type="sync_now",
        job_key="aras_ewo",
    )
    body = resp_200.get_json()
    assert body["ok"] is True
    assert body["data"]["dryRun"] is False
    assert len(body["data"]["results"]) == 1


# ── 8. Public /api/overview and Error Response Contract Preserved ─────────────


def test_public_api_overview_contract_preserved(client) -> None:
    """Existing public /api/overview endpoint remains unchanged in JSON shape."""
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"projects", "deliverables", "feishu"}
    assert isinstance(body["projects"], dict)
    assert isinstance(body["deliverables"], dict)
    assert set(body["feishu"].keys()) == {"total", "synced"}
