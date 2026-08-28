# -*- coding: utf-8 -*-
"""Focused offline tests for Excel Task Admin Web API routes and service."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.excel_tasks import (
    ApprovedExcelRoots,
    ExcelTaskArtifactMetadata,
    ExcelTaskFileRef,
    ExcelTaskRepository,
)
from services.excel_task_admin import (
    ExcelArtifactUnavailableError,
    ExcelTaskAdminService,
    ExcelTaskAdminValidationError,
)


@pytest.fixture()
def test_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary SQLite database for Excel web API tests."""
    db_file = tmp_path / "web_excel_test.db"
    db_instance = DatabaseManager(db_path=db_file)
    db_instance.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)
    return db_instance


@pytest.fixture()
def roots_fixture(tmp_path: Path) -> tuple[Path, Path, ApprovedExcelRoots]:
    """Provide isolated approved Excel roots with valid dummy .xlsx files."""
    default_root = tmp_path / "default_root"
    secondary_root = tmp_path / "secondary_root"
    default_root.mkdir(parents=True, exist_ok=True)
    secondary_root.mkdir(parents=True, exist_ok=True)

    (default_root / "source.xlsx").write_bytes(b"dummy source content")
    (default_root / "source2.xlsx").write_bytes(b"dummy source2 content")
    (default_root / "baseline.xlsx").write_bytes(b"dummy baseline content")
    (default_root / "target.xlsx").write_bytes(b"dummy target content")
    (secondary_root / "sec_source.xlsx").write_bytes(b"dummy secondary source")

    roots = ApprovedExcelRoots(
        {
            "default": default_root,
            "secondary": secondary_root,
        }
    )
    return default_root, secondary_root, roots


@pytest.fixture()
def repo(
    test_db: DatabaseManager,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> ExcelTaskRepository:
    """Provide an ExcelTaskRepository backed by the isolated DB and roots."""
    _, _, roots = roots_fixture
    return ExcelTaskRepository(test_db, roots)


@pytest.fixture()
def service(repo: ExcelTaskRepository) -> ExcelTaskAdminService:
    """Provide a direct ExcelTaskAdminService instance for unit tests."""
    return ExcelTaskAdminService(repo)


@pytest.fixture()
def client(test_db: DatabaseManager, repo: ExcelTaskRepository):
    """Provide a Flask test client configured with the test repo."""
    app = web_app.create_app(excel_repository=repo)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture()
def unconfigured_client(test_db: DatabaseManager):
    """Provide a Flask test client without Excel task roots configured."""
    app = web_app.create_app(excel_repository=None)
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


def _assert_privacy(
    value: Any,
    raw_keys: Sequence[str] = (),
    forbidden_paths: Sequence[str | Path] = (),
) -> None:
    """Recursively assert responses never leak sensitive keys or paths."""
    forbidden_substrings = [
        "lease_token",
        "leasetoken",
        "idempotency_key_hash",
        "idempotencykeyhash",
        "request_fingerprint",
        "requestfingerprint",
        *[str(k) for k in raw_keys if k],
    ]
    for p in forbidden_paths:
        p_str = str(p)
        if p_str:
            forbidden_substrings.append(p_str)
            forbidden_substrings.append(p_str.replace("\\", "/"))

    def _walk(item: Any) -> None:
        if isinstance(item, dict):
            for k, v in item.items():
                k_lower = str(k).lower()
                for f in forbidden_substrings:
                    assert f.lower() not in k_lower, (
                        f"Forbidden key substring {f!r} in key {k!r}"
                    )
                _walk(v)
        elif isinstance(item, (list, tuple)):
            for elem in item:
                _walk(elem)
        elif isinstance(item, str):
            for f in forbidden_substrings:
                assert f.lower() not in item.lower(), (
                    f"Forbidden substring {f!r} in value {item!r}"
                )

    _walk(value)


def _valid_post_payload(
    operation: str = "merge_append",
    idempotency_key: str = "idem-test-key-001",
    files: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Construct a valid task creation payload."""
    if files is None:
        files = [
            {
                "role": "source",
                "rootId": "default",
                "relativePath": "source.xlsx",
                "ordinal": 0,
            },
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "output.xlsx",
                "ordinal": 0,
            },
        ]
    payload: dict[str, Any] = {
        "operation": operation,
        "idempotencyKey": idempotency_key,
        "files": files,
        "maxAttempts": max_attempts,
    }
    if options is not None:
        payload["options"] = options
    return payload


def _complete_artifact(
    repo: ExcelTaskRepository,
    root: Path,
    key: str,
    *,
    output_name: str = "artifact.xlsx",
    data: bytes = b"verified artifact bytes",
) -> dict[str, Any]:
    output_ref = ExcelTaskFileRef("output", "default", output_name)
    task = repo.create_task(
        "merge_append",
        [
            ExcelTaskFileRef("source", "default", "source.xlsx"),
            output_ref,
        ],
        key,
    )
    lease = repo.lease_next(lease_seconds=300)
    assert lease is not None
    repo.start(lease["task_id"], lease["run_id"], lease["lease_token"])
    (root / output_name).write_bytes(data)
    return repo.finish_success_with_artifact(
        int(task["id"]),
        int(lease["run_id"]),
        str(lease["lease_token"]),
        ExcelTaskArtifactMetadata(
            output_ref=output_ref,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )


# ── 1. Security Guards (POST /api/excel-tasks) ──────────────────────────────


@pytest.mark.parametrize(
    ("remote_addr", "host", "origin"),
    [
        ("127.0.0.1", "localhost:5000", "http://localhost:5000"),
        ("127.0.0.1", "127.0.0.1:5000", "http://127.0.0.1:5000"),
        ("127.0.0.2", "127.0.0.2:8000", "http://127.0.0.2:8000"),
        ("::1", "localhost:5000", "http://localhost:5000"),
        ("::1", "[::1]:5000", "http://[::1]:5000"),
        ("::ffff:127.0.0.1", "127.0.0.1:5000", "http://127.0.0.1:5000"),
        ("::ffff:127.0.0.1", "localhost:5000", "http://localhost:5000"),
        ("127.0.0.1", "localhost:5000", None),
    ],
)
def test_post_mutation_accepts_valid_loopback_remote_and_host(
    client,
    remote_addr: str,
    host: str,
    origin: str | None,
) -> None:
    """POST /api/excel-tasks accepts loopback remote, host, and origin."""
    headers = _loopback_headers(host=host, origin=origin)
    environ = {"REMOTE_ADDR": remote_addr, "HTTP_HOST": host}
    payload = _valid_post_payload(idempotency_key="loopback-accept-key")

    resp = client.post(
        "/api/excel-tasks",
        json=payload,
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["status"] == "queued"


@pytest.mark.parametrize(
    "non_loopback_remote",
    ["192.168.1.100", "10.0.0.1", "8.8.8.8", "172.16.0.5", "2001:db8::1"],
)
def test_post_mutation_rejects_non_loopback_remote(
    client,
    test_db: DatabaseManager,
    non_loopback_remote: str,
) -> None:
    """POST /api/excel-tasks rejects non-loopback remote with 403."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": non_loopback_remote}
    payload = _valid_post_payload(idempotency_key="non-loopback-key")

    resp = client.post(
        "/api/excel-tasks",
        json=payload,
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "LocalAccessRequired",
            "message": "此操作仅允许从本机访问",
        },
    }
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    "bad_host",
    [
        "example.com",
        "evil.com:5000",
        "192.168.1.50:5000",
        "attacker.local",
        "bad:host:colon:5000",
    ],
)
def test_post_mutation_rejects_untrusted_host(
    client,
    test_db: DatabaseManager,
    bad_host: str,
) -> None:
    """POST /api/excel-tasks rejects non-loopback or malformed Host with 403."""
    headers = _loopback_headers(host=bad_host, origin=None)
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": bad_host}
    payload = _valid_post_payload(idempotency_key="bad-host-key")

    resp = client.post(
        "/api/excel-tasks",
        json=payload,
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "LocalAccessRequired",
            "message": "请求主机不受信任",
        },
    }
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_mutation_rejects_cross_site_fetch_site(
    client,
    test_db: DatabaseManager,
) -> None:
    """POST /api/excel-tasks rejects Sec-Fetch-Site: cross-site with 403."""
    headers = _loopback_headers(sec_fetch_site="cross-site")
    environ = {"REMOTE_ADDR": "127.0.0.1"}
    payload = _valid_post_payload(idempotency_key="cross-site-key")

    resp = client.post(
        "/api/excel-tasks",
        json=payload,
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "CrossSiteRequest",
            "message": "拒绝跨站写操作",
        },
    }
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    "bad_origin",
    [
        "http://evil.com:5000",
        "http://localhost:8080",
        "https://localhost:5000",
        "http://192.168.1.1:5000",
    ],
)
def test_post_mutation_rejects_mismatched_origin(
    client,
    test_db: DatabaseManager,
    bad_origin: str,
) -> None:
    """POST /api/excel-tasks rejects mismatched Origin with 403."""
    headers = _loopback_headers(host="localhost:5000", origin=bad_origin)
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": "localhost:5000"}
    payload = _valid_post_payload(idempotency_key="bad-origin-key")

    resp = client.post(
        "/api/excel-tasks",
        json=payload,
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 403
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "CrossSiteRequest",
            "message": "请求来源与本机服务不一致",
        },
    }
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_mutation_security_guard_runs_before_body_parsing(
    client,
    test_db: DatabaseManager,
) -> None:
    """Security guard rejects foreign requests before parsing JSON body."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "192.168.1.100"}

    resp = client.post(
        "/api/excel-tasks",
        data="not json at all",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["type"] == "LocalAccessRequired"
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


# ── 2. Task Creation (POST /api/excel-tasks) ────────────────────────────────


def test_post_create_task_valid_merge_append_success(
    client,
    test_db: DatabaseManager,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """POST valid merge_append task returns 200, creates DB records, and no-store."""
    default_root, secondary_root, _ = roots_fixture
    raw_key = "secret-idempotency-key-001"
    payload = _valid_post_payload(
        operation="merge_append",
        idempotency_key=raw_key,
        options={},
        max_attempts=1,
    )
    headers = _loopback_headers()

    resp = client.post("/api/excel-tasks", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"

    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert isinstance(data["id"], int) and data["id"] >= 1
    assert data["operation"] == "merge_append"
    assert data["status"] == "queued"
    assert data["options"] == {}
    assert data["attemptCount"] == 0
    assert data["maxAttempts"] == 1
    assert data["errorType"] is None
    assert data["errorMessage"] is None
    assert isinstance(data["createdAt"], str)
    assert isinstance(data["updatedAt"], str)
    assert data["startedAt"] is None
    assert data["finishedAt"] is None
    assert len(data["files"]) == 2

    # Verify files payload has both source and output
    roles = {f["role"]: f for f in data["files"]}
    assert "source" in roles
    assert roles["source"] == {
        "role": "source",
        "rootId": "default",
        "relativePath": "source.xlsx",
        "ordinal": 0,
    }
    assert "output" in roles
    assert roles["output"] == {
        "role": "output",
        "rootId": "default",
        "relativePath": "output.xlsx",
        "ordinal": 0,
    }

    _assert_privacy(
        body,
        raw_keys=[raw_key],
        forbidden_paths=[default_root, secondary_root],
    )

    with test_db.get_connection() as conn:
        task_rows = conn.execute("SELECT * FROM excel_tasks").fetchall()
        assert len(task_rows) == 1
        file_rows = conn.execute("SELECT * FROM excel_task_files").fetchall()
        assert len(file_rows) == 2


@pytest.mark.parametrize(
    ("operation", "files"),
    [
        (
            "merge_append",
            [
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source2.xlsx",
                    "ordinal": 1,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "appended.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
        (
            "merge_overlay",
            [
                {
                    "role": "source",
                    "rootId": "secondary",
                    "relativePath": "sec_source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "target",
                    "rootId": "default",
                    "relativePath": "target.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "overlay_out.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
        (
            "diff_against_baseline",
            [
                {
                    "role": "baseline",
                    "rootId": "default",
                    "relativePath": "baseline.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "target",
                    "rootId": "default",
                    "relativePath": "target.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "diff_out.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
    ],
)
def test_post_create_all_supported_operations(
    client,
    operation: str,
    files: list[dict[str, Any]],
) -> None:
    """POST supports all defined operations and root combinations."""
    payload = _valid_post_payload(
        operation=operation,
        idempotency_key=f"key-op-{operation}",
        files=files,
    )
    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["operation"] == operation
    assert body["data"]["status"] == "queued"
    assert len(body["data"]["files"]) == len(files)


def test_post_create_same_key_same_request_replay(
    client,
    test_db: DatabaseManager,
) -> None:
    """POST with same idempotency key and same request returns original task."""
    raw_key = "replay-idempotency-key-002"
    payload = _valid_post_payload(idempotency_key=raw_key)
    headers = _loopback_headers()

    resp1 = client.post("/api/excel-tasks", json=payload, headers=headers)
    assert resp1.status_code == 200
    task1 = resp1.get_json()["data"]

    resp2 = client.post("/api/excel-tasks", json=payload, headers=headers)
    assert resp2.status_code == 200
    task2 = resp2.get_json()["data"]

    assert task1["id"] == task2["id"]
    assert task1 == task2

    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 1


def test_post_create_same_key_different_request_conflict_409(
    client,
    test_db: DatabaseManager,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """POST same key with different fingerprint returns 409 Conflict."""
    default_root, secondary_root, _ = roots_fixture
    raw_key = "conflict-key-003"
    payload1 = _valid_post_payload(
        operation="merge_append",
        idempotency_key=raw_key,
    )
    headers = _loopback_headers()

    resp1 = client.post("/api/excel-tasks", json=payload1, headers=headers)
    assert resp1.status_code == 200

    # Different operation
    payload2 = _valid_post_payload(
        operation="merge_overlay",
        idempotency_key=raw_key,
        files=[
            {
                "role": "source",
                "rootId": "default",
                "relativePath": "source.xlsx",
                "ordinal": 0,
            },
            {
                "role": "target",
                "rootId": "default",
                "relativePath": "target.xlsx",
                "ordinal": 0,
            },
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "output.xlsx",
                "ordinal": 0,
            },
        ],
    )
    resp2 = client.post("/api/excel-tasks", json=payload2, headers=headers)
    assert resp2.status_code == 409
    assert resp2.headers.get("Cache-Control") == "no-store"
    body2 = resp2.get_json()
    assert body2 == {
        "ok": False,
        "error": {
            "type": "Conflict",
            "message": "Idempotency key was already used for a different request",
        },
    }

    _assert_privacy(
        body2,
        raw_keys=[raw_key],
        forbidden_paths=[default_root, secondary_root],
    )

    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 1


# ── 3. POST Validation Errors (400, 422, 503) ───────────────────────────────


@pytest.mark.parametrize(
    "invalid_json_body",
    [
        "not json text",
        "[1, 2, 3]",
        '"plain string"',
        "12345",
        "true",
        "null",
    ],
)
def test_post_create_malformed_or_non_object_json_400(
    client,
    test_db: DatabaseManager,
    invalid_json_body: str,
) -> None:
    """POST /api/excel-tasks returns 400 when body is not a JSON object."""
    headers = _loopback_headers()
    headers["Content-Type"] = "application/json"

    resp = client.post(
        "/api/excel-tasks",
        data=invalid_json_body,
        headers=headers,
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
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_create_unsupported_root_fields_422(
    client,
    test_db: DatabaseManager,
) -> None:
    """POST with unexpected top-level fields returns 422."""
    payload = _valid_post_payload(idempotency_key="unsupported-fields-key")
    payload["unknownField"] = "malicious_payload"

    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == "ValidationError"
    assert body["error"]["fields"]["request"] == "contains unsupported fields"
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    ("bad_op", "expected_field", "expected_error"),
    [
        (None, "operation", "must be a non-empty string"),
        ("", "operation", "must be a non-empty string"),
        ("   ", "operation", "must be a non-empty string"),
        (123, "operation", "must be a non-empty string"),
        ("invalid_op", "request", "unsupported operation: 'invalid_op'"),
    ],
)
def test_post_create_invalid_operation_422(
    client,
    test_db: DatabaseManager,
    bad_op: Any,
    expected_field: str,
    expected_error: str,
) -> None:
    """POST with invalid operation returns 422 with field message."""
    payload = _valid_post_payload(idempotency_key="bad-op-key")
    if bad_op is None:
        payload.pop("operation", None)
    else:
        payload["operation"] = bad_op

    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["error"]["fields"][expected_field] == expected_error
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    ("bad_key", "expected_error"),
    [
        (None, "must be a non-empty string"),
        ("", "must be a non-empty string"),
        ("   ", "must be a non-empty string"),
        (12345, "must be a non-empty string"),
        (True, "must be a non-empty string"),
    ],
)
def test_post_create_invalid_idempotency_key_422(
    client,
    test_db: DatabaseManager,
    bad_key: Any,
    expected_error: str,
) -> None:
    """POST with invalid idempotencyKey returns 422."""
    payload = _valid_post_payload()
    if bad_key is None:
        payload.pop("idempotencyKey", None)
    else:
        payload["idempotencyKey"] = bad_key

    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["error"]["fields"]["idempotencyKey"] == expected_error
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    ("bad_options", "expected_error"),
    [
        ("string_options", "must be an object"),
        ([1, 2, 3], "must be an object"),
        (123, "must be an object"),
        ({"sheet": "Summary"}, "must be empty in this phase"),
    ],
)
def test_post_create_invalid_options_422(
    client,
    test_db: DatabaseManager,
    bad_options: Any,
    expected_error: str,
) -> None:
    """POST with non-mapping or non-empty options returns 422."""
    payload = _valid_post_payload(idempotency_key="bad-opt-key")
    payload["options"] = bad_options

    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["error"]["fields"]["options"] == expected_error
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    "bad_max_attempts",
    [2, 0, -1, 5, 1.0, True, False, "1", [1]],
)
def test_post_create_invalid_max_attempts_422(
    client,
    test_db: DatabaseManager,
    bad_max_attempts: Any,
) -> None:
    """POST with maxAttempts != 1 returns 422."""
    payload = _valid_post_payload(
        idempotency_key="bad-attempts-key",
        max_attempts=bad_max_attempts,
    )

    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert (
        body["error"]["fields"]["maxAttempts"]
        == "must be 1 until Excel transformations are retry-safe"
    )
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    "bad_files",
    [None, [], "not_a_list", 123, {}],
)
def test_post_create_invalid_files_array_422(
    client,
    test_db: DatabaseManager,
    bad_files: Any,
) -> None:
    """POST with missing, empty, or non-list files returns 422."""
    payload = _valid_post_payload(idempotency_key="bad-files-arr-key")
    if bad_files is None:
        payload.pop("files", None)
    else:
        payload["files"] = bad_files

    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"]["fields"]["files"] == "must be a non-empty array"
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_create_invalid_file_element_type_and_unsupported_fields_422(
    client,
    test_db: DatabaseManager,
) -> None:
    """POST with non-object file element or extra fields in file returns 422."""
    payload1 = _valid_post_payload(
        idempotency_key="file-not-obj-key",
        files=[123, "file.xlsx"],
    )
    resp1 = client.post("/api/excel-tasks", json=payload1, headers=_loopback_headers())
    assert resp1.status_code == 422
    assert resp1.get_json()["error"]["fields"]["files[0]"] == "must be an object"

    payload2 = _valid_post_payload(
        idempotency_key="file-extra-field-key",
        files=[
            {
                "role": "source",
                "rootId": "default",
                "relativePath": "source.xlsx",
                "extraProperty": True,
            }
        ],
    )
    resp2 = client.post("/api/excel-tasks", json=payload2, headers=_loopback_headers())
    assert resp2.status_code == 422
    assert (
        resp2.get_json()["error"]["fields"]["files[0]"]
        == "contains unsupported fields"
    )
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    ("file_override", "expected_field_key"),
    [
        ({"role": "invalid_role"}, "files[0]"),
        ({"ordinal": -1}, "files[0]"),
        ({"ordinal": "one"}, "files[0]"),
        ({"relativePath": "../outside.xlsx"}, "files[0]"),
        ({"relativePath": "sub\\source.xlsx"}, "files[0]"),
        ({"relativePath": "C:/source.xlsx"}, "files[0]"),
        ({"relativePath": "CON.xlsx"}, "files[0]"),
        ({"relativePath": "source.xlsm"}, "files[0]"),
        ({"relativePath": "source.csv"}, "files[0]"),
        ({"relativePath": "source.xlsx "}, "files[0]"),
    ],
)
def test_post_create_invalid_file_attributes_and_path_safety_422(
    client,
    test_db: DatabaseManager,
    file_override: dict[str, Any],
    expected_field_key: str,
) -> None:
    """POST with path safety or role errors returns 422 tagged with files[i]."""
    base_file = {
        "role": "source",
        "rootId": "default",
        "relativePath": "source.xlsx",
        "ordinal": 0,
    }
    base_file.update(file_override)
    payload = _valid_post_payload(
        idempotency_key="bad-file-attr-key",
        files=[
            base_file,
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "output.xlsx",
                "ordinal": 0,
            },
        ],
    )
    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert expected_field_key in body["error"]["fields"]
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


@pytest.mark.parametrize(
    ("operation", "files"),
    [
        (
            "merge_append",
            [
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "output.xlsx",
                    "ordinal": 0,
                }
            ],
        ),
        (
            "merge_append",
            [
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                }
            ],
        ),
        (
            "merge_append",
            [
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "target",
                    "rootId": "default",
                    "relativePath": "target.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "output.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
        (
            "merge_overlay",
            [
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "output.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
        (
            "diff_against_baseline",
            [
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "baseline",
                    "rootId": "default",
                    "relativePath": "baseline.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "target",
                    "rootId": "default",
                    "relativePath": "target.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "output.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
        (
            "merge_append",
            [
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "source",
                    "rootId": "default",
                    "relativePath": "source.xlsx",
                    "ordinal": 0,
                },
                {
                    "role": "output",
                    "rootId": "default",
                    "relativePath": "output.xlsx",
                    "ordinal": 0,
                },
            ],
        ),
    ],
)
def test_post_create_cardinality_violations_422(
    client,
    test_db: DatabaseManager,
    operation: str,
    files: list[dict[str, Any]],
) -> None:
    """POST with role cardinality violations returns 422 in request field."""
    payload = _valid_post_payload(
        operation=operation,
        idempotency_key="cardinality-violation-key",
        files=files,
    )
    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    body = resp.get_json()
    assert "request" in body["error"]["fields"]
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_create_unknown_root_or_missing_input_file_422(
    client,
    test_db: DatabaseManager,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """POST with unknown rootId or missing input file returns 422."""
    default_root, secondary_root, _ = roots_fixture

    # 1. Unknown rootId
    payload1 = _valid_post_payload(
        idempotency_key="unknown-root-key",
        files=[
            {
                "role": "source",
                "rootId": "non_existent_root",
                "relativePath": "source.xlsx",
                "ordinal": 0,
            },
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "output.xlsx",
                "ordinal": 0,
            },
        ],
    )
    resp1 = client.post("/api/excel-tasks", json=payload1, headers=_loopback_headers())
    assert resp1.status_code == 422
    assert "request" in resp1.get_json()["error"]["fields"]

    # 2. Missing source file on disk
    payload2 = _valid_post_payload(
        idempotency_key="missing-file-key",
        files=[
            {
                "role": "source",
                "rootId": "default",
                "relativePath": "does_not_exist_file.xlsx",
                "ordinal": 0,
            },
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "output.xlsx",
                "ordinal": 0,
            },
        ],
    )
    resp2 = client.post("/api/excel-tasks", json=payload2, headers=_loopback_headers())
    assert resp2.status_code == 422
    body2 = resp2.get_json()
    assert "request" in body2["error"]["fields"]
    _assert_privacy(
        body2,
        raw_keys=["missing-file-key"],
        forbidden_paths=[default_root, secondary_root],
    )

    # 3. Missing output parent directory on disk
    payload3 = _valid_post_payload(
        idempotency_key="missing-out-parent-key",
        files=[
            {
                "role": "source",
                "rootId": "default",
                "relativePath": "source.xlsx",
                "ordinal": 0,
            },
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "non_existent_dir/output.xlsx",
                "ordinal": 0,
            },
        ],
    )
    resp3 = client.post("/api/excel-tasks", json=payload3, headers=_loopback_headers())
    assert resp3.status_code == 422
    assert "request" in resp3.get_json()["error"]["fields"]

    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_create_unconfigured_service_503(
    unconfigured_client,
    test_db: DatabaseManager,
) -> None:
    """POST returns 503 NotConfigured when excel repository is not configured."""
    payload = _valid_post_payload(idempotency_key="unconfigured-key")
    resp = unconfigured_client.post(
        "/api/excel-tasks",
        json=payload,
        headers=_loopback_headers(),
    )
    assert resp.status_code == 503
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "NotConfigured",
            "message": "Excel task roots are not configured",
        },
    }
    with test_db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM excel_tasks").fetchone()[0]
        assert count == 0


def test_post_create_internal_server_error_500(
    client,
    monkeypatch: pytest.MonkeyPatch,
    test_db: DatabaseManager,
) -> None:
    """POST returns 500 when create_task raises unexpected exception."""
    monkeypatch.setattr(
        ExcelTaskAdminService,
        "create_task",
        MagicMock(side_effect=RuntimeError("Unexpected DB explosion")),
    )
    payload = _valid_post_payload(idempotency_key="server-err-key")
    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 500
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "Excel task creation failed",
        },
    }


# ── 4. Task Reads (GET /api/excel-tasks, detail, runs) ──────────────────────


def test_get_tasks_list_empty_and_populated(
    client,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """GET /api/excel-tasks returns list of tasks ordered by ID DESC."""
    default_root, secondary_root, _ = roots_fixture

    resp = client.get("/api/excel-tasks")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {"ok": True, "data": []}

    client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key="list-k1"),
        headers=_loopback_headers(),
    )
    client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key="list-k2"),
        headers=_loopback_headers(),
    )
    client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key="list-k3"),
        headers=_loopback_headers(),
    )

    resp2 = client.get("/api/excel-tasks")
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert body2["ok"] is True
    tasks = body2["data"]
    assert len(tasks) == 3
    assert [t["id"] for t in tasks] == [3, 2, 1]

    _assert_privacy(
        body2,
        raw_keys=["list-k1", "list-k2", "list-k3"],
        forbidden_paths=[default_root, secondary_root],
    )


def test_get_tasks_list_status_filter_and_whitespace(
    client,
    repo: ExcelTaskRepository,
) -> None:
    """GET /api/excel-tasks filters by status and handles empty/whitespace status."""
    client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key="st-k1"),
        headers=_loopback_headers(),
    )
    client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key="st-k2"),
        headers=_loopback_headers(),
    )
    # lease_next leases the oldest queued task (task 1)
    leased = repo.lease_next()
    assert leased is not None
    assert leased["task_id"] == 1
    repo.start(leased["task_id"], leased["run_id"], leased["lease_token"])

    # Task 2 remains queued
    resp_q = client.get("/api/excel-tasks?status=queued")
    assert resp_q.status_code == 200
    assert len(resp_q.get_json()["data"]) == 1
    assert resp_q.get_json()["data"][0]["id"] == 2

    # Task 1 is running
    resp_r = client.get("/api/excel-tasks?status=running")
    assert resp_r.status_code == 200
    assert len(resp_r.get_json()["data"]) == 1
    assert resp_r.get_json()["data"][0]["id"] == 1

    # Whitespace status returns all
    resp_ws = client.get("/api/excel-tasks?status=   ")
    assert resp_ws.status_code == 200
    assert len(resp_ws.get_json()["data"]) == 2


def test_get_tasks_list_invalid_status_422(client) -> None:
    """GET /api/excel-tasks with unknown status returns 422."""
    resp = client.get("/api/excel-tasks?status=invalid_status")
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ValidationError",
            "message": "请修正标记的字段",
            "fields": {"status": "is not a valid task status"},
        },
    }


@pytest.mark.parametrize(
    ("limit_arg", "expected_count"),
    [
        ("1", 1),
        ("2", 2),
        ("10", 3),
        ("200", 3),
    ],
)
def test_get_tasks_list_valid_limits(
    client,
    limit_arg: str,
    expected_count: int,
) -> None:
    """GET /api/excel-tasks with valid limit parameter."""
    for i in range(3):
        client.post(
            "/api/excel-tasks",
            json=_valid_post_payload(idempotency_key=f"lim-k{i}"),
            headers=_loopback_headers(),
        )
    resp = client.get(f"/api/excel-tasks?limit={limit_arg}")
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == expected_count


@pytest.mark.parametrize(
    ("bad_limit", "expected_field_msg"),
    [
        ("abc", "must be an integer"),
        ("0", "must be between 1 and 200"),
        ("201", "must be between 1 and 200"),
        ("-5", "must be between 1 and 200"),
        ("1.5", "must be an integer"),
    ],
)
def test_get_tasks_list_invalid_limit_422(
    client,
    bad_limit: str,
    expected_field_msg: str,
) -> None:
    """GET /api/excel-tasks with invalid limit returns 422."""
    resp = client.get(f"/api/excel-tasks?limit={bad_limit}")
    assert resp.status_code == 422
    assert resp.headers.get("Cache-Control") == "no-store"
    assert (
        resp.get_json()["error"]["fields"]["limit"] == expected_field_msg
    )


def test_get_tasks_list_unconfigured_503(unconfigured_client) -> None:
    """GET /api/excel-tasks returns 503 when service is not configured."""
    resp = unconfigured_client.get("/api/excel-tasks")
    assert resp.status_code == 503
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json()["error"]["type"] == "NotConfigured"


def test_get_tasks_list_server_error_500(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/excel-tasks returns 500 when service raises unexpected exception."""
    monkeypatch.setattr(
        ExcelTaskAdminService,
        "list_tasks",
        MagicMock(side_effect=RuntimeError("Query exploded")),
    )
    resp = client.get("/api/excel-tasks")
    assert resp.status_code == 500
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "Excel task query failed",
        },
    }


def test_get_task_detail_success_and_404(
    client,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """GET /api/excel-tasks/<id> returns 200 for existing and 404 for missing."""
    default_root, secondary_root, _ = roots_fixture
    raw_key = "detail-test-key-001"
    resp_create = client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key=raw_key),
        headers=_loopback_headers(),
    )
    task_id = resp_create.get_json()["data"]["id"]

    resp_detail = client.get(f"/api/excel-tasks/{task_id}")
    assert resp_detail.status_code == 200
    assert resp_detail.headers.get("Cache-Control") == "no-store"
    body = resp_detail.get_json()
    assert body["ok"] is True
    assert body["data"]["id"] == task_id
    assert body["data"]["status"] == "queued"
    _assert_privacy(
        body,
        raw_keys=[raw_key],
        forbidden_paths=[default_root, secondary_root],
    )

    resp_404 = client.get("/api/excel-tasks/99999")
    assert resp_404.status_code == 404
    assert resp_404.headers.get("Cache-Control") == "no-store"
    assert resp_404.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "Excel task was not found",
        },
    }


def test_get_task_detail_unconfigured_503(unconfigured_client) -> None:
    """GET /api/excel-tasks/<id> returns 503 when service is unconfigured."""
    resp = unconfigured_client.get("/api/excel-tasks/1")
    assert resp.status_code == 503
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json()["error"]["type"] == "NotConfigured"


def test_get_task_detail_server_error_500(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/excel-tasks/<id> returns 500 on unexpected service exception."""
    monkeypatch.setattr(
        ExcelTaskAdminService,
        "get_task",
        MagicMock(side_effect=RuntimeError("Detail failed")),
    )
    resp = client.get("/api/excel-tasks/1")
    assert resp.status_code == 500
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "Excel task query failed",
        },
    }


def test_get_task_runs_lifecycle_and_history(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """GET /api/excel-tasks/<id>/runs returns run history and 404 for missing."""
    default_root, secondary_root, _ = roots_fixture
    raw_key = "runs-history-key-001"
    resp_create = client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key=raw_key),
        headers=_loopback_headers(),
    )
    task_id = resp_create.get_json()["data"]["id"]

    resp_runs0 = client.get(f"/api/excel-tasks/{task_id}/runs")
    assert resp_runs0.status_code == 200
    assert resp_runs0.headers.get("Cache-Control") == "no-store"
    assert resp_runs0.get_json() == {"ok": True, "data": []}

    leased = repo.lease_next(lease_seconds=300)
    assert leased is not None
    run_id = leased["run_id"]
    lease_token = leased["lease_token"]

    repo.start(task_id, run_id, lease_token)

    repo.finish(
        task_id,
        run_id,
        lease_token,
        "succeeded",
        error_type=None,
        error_message=None,
    )

    resp_runs = client.get(f"/api/excel-tasks/{task_id}/runs")
    assert resp_runs.status_code == 200
    assert resp_runs.headers.get("Cache-Control") == "no-store"
    body = resp_runs.get_json()
    assert body["ok"] is True
    runs = body["data"]
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == run_id
    assert run["taskId"] == task_id
    assert run["attempt"] == 1
    assert run["runState"] == "succeeded"
    assert run["errorType"] is None
    assert run["errorMessage"] is None
    assert isinstance(run["createdAt"], str)
    assert isinstance(run["startedAt"], str)
    assert isinstance(run["finishedAt"], str)

    _assert_privacy(
        body,
        raw_keys=[raw_key, lease_token],
        forbidden_paths=[default_root, secondary_root],
    )

    resp_404 = client.get("/api/excel-tasks/99999/runs")
    assert resp_404.status_code == 404
    assert resp_404.headers.get("Cache-Control") == "no-store"
    assert resp_404.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "Excel task was not found",
        },
    }


def test_get_task_runs_unconfigured_503(unconfigured_client) -> None:
    """GET /api/excel-tasks/<id>/runs returns 503 when unconfigured."""
    resp = unconfigured_client.get("/api/excel-tasks/1/runs")
    assert resp.status_code == 503
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json()["error"]["type"] == "NotConfigured"


def test_get_task_runs_server_error_500(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/excel-tasks/<id>/runs returns 500 on unexpected service error."""
    monkeypatch.setattr(
        ExcelTaskAdminService,
        "list_runs",
        MagicMock(side_effect=RuntimeError("Runs query failed")),
    )
    resp = client.get("/api/excel-tasks/1/runs")
    assert resp.status_code == 500
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "Excel task query failed",
        },
    }


# ── 5. Privacy, Redaction & Invariants ──────────────────────────────────────


def test_privacy_redacts_approved_roots_in_error_messages(
    client,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """Error messages redact approved-root filesystem paths into <approved-root:id>."""
    default_root, secondary_root, _ = roots_fixture
    raw_key = "privacy-redact-key-001"
    payload = _valid_post_payload(
        idempotency_key=raw_key,
        files=[
            {
                "role": "source",
                "rootId": "default",
                "relativePath": "missing_input_file.xlsx",
                "ordinal": 0,
            },
            {
                "role": "output",
                "rootId": "default",
                "relativePath": "output.xlsx",
                "ordinal": 0,
            },
        ],
    )
    resp = client.post("/api/excel-tasks", json=payload, headers=_loopback_headers())
    assert resp.status_code == 422
    body = resp.get_json()
    _assert_privacy(
        body,
        raw_keys=[raw_key],
        forbidden_paths=[default_root, secondary_root],
    )


def test_privacy_invariants_across_all_lifecycle_endpoints(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """Assert lease tokens, hashes, fingerprints, and paths never appear in any response."""
    default_root, secondary_root, _ = roots_fixture
    raw_key = "super-secret-idempotency-token-xyz"

    # 1. Create
    resp_create = client.post(
        "/api/excel-tasks",
        json=_valid_post_payload(idempotency_key=raw_key),
        headers=_loopback_headers(),
    )
    assert resp_create.status_code == 200
    task_id = resp_create.get_json()["data"]["id"]

    # 2. Lease & run with simulated error containing secret and root path
    leased = repo.lease_next()
    assert leased is not None
    token = leased["lease_token"]
    run_id = leased["run_id"]
    repo.start(task_id, run_id, token)
    repo.finish(
        task_id,
        run_id,
        token,
        "failed",
        error_type="ExecutionFailure",
        error_message=f"Failed processing {default_root}/source.xlsx with token={token}",
    )

    # 3. Check detail
    resp_detail = client.get(f"/api/excel-tasks/{task_id}")
    assert resp_detail.status_code == 200
    body_detail = resp_detail.get_json()
    _assert_privacy(
        body_detail,
        raw_keys=[raw_key, token],
        forbidden_paths=[default_root, secondary_root],
    )
    assert "<approved-root:default>" in body_detail["data"]["errorMessage"]

    # 4. Check runs
    resp_runs = client.get(f"/api/excel-tasks/{task_id}/runs")
    assert resp_runs.status_code == 200
    body_runs = resp_runs.get_json()
    _assert_privacy(
        body_runs,
        raw_keys=[raw_key, token],
        forbidden_paths=[default_root, secondary_root],
    )
    assert "<approved-root:default>" in body_runs["data"][0]["errorMessage"]

    # 5. Check list
    resp_list = client.get("/api/excel-tasks")
    assert resp_list.status_code == 200
    body_list = resp_list.get_json()
    _assert_privacy(
        body_list,
        raw_keys=[raw_key, token],
        forbidden_paths=[default_root, secondary_root],
    )


# ── 6. Direct ExcelTaskAdminService Unit Tests ──────────────────────────────


def test_service_create_task_direct_success(
    service: ExcelTaskAdminService,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """ExcelTaskAdminService.create_task returns properly formatted dict."""
    payload = _valid_post_payload(idempotency_key="service-direct-k1")
    result = service.create_task(payload)
    assert isinstance(result["id"], int)
    assert result["operation"] == "merge_append"
    assert result["status"] == "queued"
    assert result["attemptCount"] == 0
    assert result["maxAttempts"] == 1
    assert len(result["files"]) == 2


def test_service_create_task_validation_error(service: ExcelTaskAdminService) -> None:
    """ExcelTaskAdminService.create_task raises ExcelTaskAdminValidationError."""
    with pytest.raises(ExcelTaskAdminValidationError) as exc_info:
        service.create_task({"operation": "", "files": []})
    assert "operation" in exc_info.value.fields
    assert "files" in exc_info.value.fields


def test_service_list_tasks_and_limit_direct(
    service: ExcelTaskAdminService,
) -> None:
    """ExcelTaskAdminService.list_tasks validates limit and status."""
    service.create_task(_valid_post_payload(idempotency_key="srv-lim-k1"))
    service.create_task(_valid_post_payload(idempotency_key="srv-lim-k2"))

    assert len(service.list_tasks(None, None)) == 2
    assert len(service.list_tasks(None, "")) == 2
    assert len(service.list_tasks(None, 1)) == 1

    with pytest.raises(ExcelTaskAdminValidationError):
        service.list_tasks(None, "invalid")
    with pytest.raises(ExcelTaskAdminValidationError):
        service.list_tasks(None, 0)
    with pytest.raises(ExcelTaskAdminValidationError):
        service.list_tasks(None, 201)
    with pytest.raises(ExcelTaskAdminValidationError):
        service.list_tasks(None, True)

    with pytest.raises(ExcelTaskAdminValidationError):
        service.list_tasks("bogus_status", 50)


def test_service_get_task_and_list_runs_key_error(
    service: ExcelTaskAdminService,
) -> None:
    """ExcelTaskAdminService raises KeyError for missing task IDs."""
    with pytest.raises(KeyError):
        service.get_task(99999)
    with pytest.raises(KeyError):
        service.list_runs(99999)


def test_service_safe_message_redaction(
    service: ExcelTaskAdminService,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    """ExcelTaskAdminService._safe_message redacts sensitive info and root paths."""
    default_root, secondary_root, _ = roots_fixture
    raw_msg = (
        f"Error in {default_root}\\file.xlsx and {secondary_root}/sec.xlsx; "
        "password=SuperSecretPassword123! token=ghp_1234567890abcdefghijklmnopqrst"
    )
    safe = service._safe_message(raw_msg)
    assert "<approved-root:default>" in safe
    assert "<approved-root:secondary>" in safe
    assert str(default_root) not in safe
    assert str(secondary_root) not in safe
    assert "SuperSecretPassword123!" not in safe
    assert "ghp_1234567890abcdefghijklmnopqrst" not in safe


def test_excel_artifact_read_and_download_endpoints(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    content = b"phase-d-artifact-content"
    artifact = _complete_artifact(
        repo,
        default_root,
        "artifact-api-success",
        output_name="report.xlsx",
        data=content,
    )

    list_response = client.get(f"/api/excel-tasks/{artifact['task_id']}/artifacts")
    assert list_response.status_code == 200
    assert list_response.headers["Cache-Control"] == "no-store"
    list_payload = list_response.get_json()
    assert list_payload["data"] == [
        {
            "id": artifact["id"],
            "taskId": artifact["task_id"],
            "runId": artifact["run_id"],
            "artifactType": "output",
            "rootId": "default",
            "relativePath": "report.xlsx",
            "displayName": "report.xlsx",
            "sizeBytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "createdAt": artifact["created_at"],
        }
    ]
    _assert_privacy(list_payload, forbidden_paths=(default_root,))

    detail_response = client.get(f"/api/excel-artifacts/{artifact['id']}")
    assert detail_response.status_code == 200
    assert detail_response.headers["Cache-Control"] == "no-store"
    assert detail_response.get_json()["data"] == list_payload["data"][0]

    download_response = client.get(f"/api/excel-artifacts/{artifact['id']}/download")
    assert download_response.status_code == 200
    assert download_response.data == content
    assert download_response.headers["Cache-Control"] == "no-store"
    assert download_response.headers["X-Content-Type-Options"] == "nosniff"
    assert download_response.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in download_response.headers["Content-Disposition"]
    assert "report.xlsx" in download_response.headers["Content-Disposition"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/excel-tasks/999999/artifacts",
        "/api/excel-artifacts/999999",
        "/api/excel-artifacts/999999/download",
        "/api/excel-artifacts/999999/download-audit",
    ],
)
def test_excel_artifact_unknown_returns_404(client, endpoint: str) -> None:
    response = client.get(endpoint)
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["error"]["type"] == "NotFound"


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/excel-tasks/1/artifacts",
        "/api/excel-artifacts/1",
        "/api/excel-artifacts/1/download",
        "/api/excel-artifacts/1/download-audit",
    ],
)
def test_excel_artifact_unconfigured_returns_503(
    unconfigured_client,
    endpoint: str,
) -> None:
    response = unconfigured_client.get(endpoint)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["error"]["type"] == "NotConfigured"


def test_excel_artifact_download_fails_closed_for_tamper_and_missing_file(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    tampered = _complete_artifact(
        repo,
        default_root,
        "artifact-api-tampered",
        output_name="tampered.xlsx",
        data=b"original",
    )
    (default_root / "tampered.xlsx").write_bytes(b"changed")

    tampered_response = client.get(
        f"/api/excel-artifacts/{tampered['id']}/download"
    )
    assert tampered_response.status_code == 409
    assert tampered_response.get_json()["error"]["type"] == "ArtifactUnavailable"
    assert str(default_root) not in tampered_response.get_data(as_text=True)

    missing = _complete_artifact(
        repo,
        default_root,
        "artifact-api-missing",
        output_name="missing.xlsx",
        data=b"will disappear",
    )
    (default_root / "missing.xlsx").unlink()

    missing_response = client.get(f"/api/excel-artifacts/{missing['id']}/download")
    assert missing_response.status_code == 409
    assert missing_response.get_json()["error"]["type"] == "ArtifactUnavailable"
    assert str(default_root) not in missing_response.get_data(as_text=True)


@pytest.mark.parametrize("unsafe_path", ["../escape.xlsx", "report.txt"])
def test_excel_artifact_download_rejects_unsafe_stored_reference(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
    monkeypatch: pytest.MonkeyPatch,
    unsafe_path: str,
) -> None:
    default_root, _, _ = roots_fixture
    artifact = _complete_artifact(
        repo,
        default_root,
        f"unsafe-{unsafe_path}",
        output_name="safe.xlsx",
    )
    poisoned = dict(artifact)
    poisoned["relative_path"] = unsafe_path
    monkeypatch.setattr(repo, "get_artifact", lambda artifact_id: poisoned)

    response = client.get(f"/api/excel-artifacts/{artifact['id']}/download")
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "ArtifactUnavailable"
    assert str(default_root) not in response.get_data(as_text=True)


def test_excel_artifact_download_rejects_reparse_target(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_root, _, roots = roots_fixture
    artifact = _complete_artifact(
        repo,
        default_root,
        "artifact-reparse",
        output_name="reparse.xlsx",
    )
    monkeypatch.setattr(
        roots,
        "_is_reparse",
        lambda path: Path(path).name == "reparse.xlsx",
    )

    response = client.get(f"/api/excel-artifacts/{artifact['id']}/download")
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "ArtifactUnavailable"
    assert str(default_root) not in response.get_data(as_text=True)


def test_service_artifact_methods_and_integrity_error(
    service: ExcelTaskAdminService,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    artifact = _complete_artifact(
        repo,
        default_root,
        "artifact-service",
        output_name="service.xls",
        data=b"legacy-xls-bytes",
    )

    assert service.list_artifacts(artifact["task_id"])[0]["id"] == artifact["id"]
    assert service.get_artifact(artifact["id"])["relativePath"] == "service.xls"
    download = service.prepare_artifact_download(artifact["id"])
    assert download.data == b"legacy-xls-bytes"
    assert download.mimetype == "application/vnd.ms-excel"

    (default_root / "service.xls").write_bytes(b"tampered")
    with pytest.raises(ExcelArtifactUnavailableError):
        service.prepare_artifact_download(artifact["id"])


# ── Excel Artifact Download Audit API Tests ─────────────────────────
def test_excel_artifact_download_records_audit_trail_and_api_queries(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    content = b"audit-trail-test-content-12345"
    artifact = _complete_artifact(
        repo,
        default_root,
        "artifact-download-audit-trail",
        output_name="audit_test.xlsx",
        data=content,
    )
    artifact_id = int(artifact["id"])

    # Initial audit list should be empty
    audit_resp0 = client.get(f"/api/excel-artifacts/{artifact_id}/download-audit")
    assert audit_resp0.status_code == 200
    assert audit_resp0.headers["Cache-Control"] == "no-store"
    assert audit_resp0.get_json()["data"] == []

    # 1. Perform successful download
    dl_resp = client.get(f"/api/excel-artifacts/{artifact_id}/download")
    assert dl_resp.status_code == 200
    assert dl_resp.data == content

    # Check audit recorded succeeded
    audit_resp1 = client.get(f"/api/excel-artifacts/{artifact_id}/download-audit")
    assert audit_resp1.status_code == 200
    audits1 = audit_resp1.get_json()["data"]
    assert len(audits1) == 1
    assert audits1[0]["artifactId"] == artifact_id
    assert audits1[0]["taskId"] == int(artifact["task_id"])
    assert audits1[0]["result"] == "succeeded"
    assert audits1[0]["reasonCode"] == "verified"
    assert audits1[0]["servedSizeBytes"] == len(content)
    assert isinstance(audits1[0]["createdAt"], str)
    _assert_privacy(audit_resp1.get_json(), forbidden_paths=(default_root,))

    # 2. Tamper file and perform failed download
    (default_root / "audit_test.xlsx").write_bytes(b"corrupted-bytes")
    dl_tampered = client.get(f"/api/excel-artifacts/{artifact_id}/download")
    assert dl_tampered.status_code == 409

    # Check audit recorded rejected
    audit_resp2 = client.get(f"/api/excel-artifacts/{artifact_id}/download-audit")
    audits2 = audit_resp2.get_json()["data"]
    assert len(audits2) == 2
    # Newest first
    assert audits2[0]["result"] == "rejected"
    assert audits2[0]["reasonCode"] == "integrity_mismatch"
    assert audits2[0]["servedSizeBytes"] is None
    assert audits2[1]["result"] == "succeeded"
    assert audits2[1]["reasonCode"] == "verified"

    # 3. Missing file failed download
    (default_root / "audit_test.xlsx").unlink()
    dl_missing = client.get(f"/api/excel-artifacts/{artifact_id}/download")
    assert dl_missing.status_code == 409

    audit_resp3 = client.get(f"/api/excel-artifacts/{artifact_id}/download-audit")
    audits3 = audit_resp3.get_json()["data"]
    assert len(audits3) == 3
    assert audits3[0]["result"] == "rejected"
    assert audits3[0]["reasonCode"] == "file_missing"


def test_excel_artifact_download_audit_reparse_and_unsafe_path(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_root, _, roots = roots_fixture

    # 1. Reparse target
    artifact_reparse = _complete_artifact(
        repo,
        default_root,
        "artifact-reparse-audit",
        output_name="reparse_audit.xlsx",
    )
    monkeypatch.setattr(
        roots,
        "_is_reparse",
        lambda path: Path(path).name == "reparse_audit.xlsx",
    )
    resp_reparse = client.get(f"/api/excel-artifacts/{artifact_reparse['id']}/download")
    assert resp_reparse.status_code == 409

    audits = client.get(f"/api/excel-artifacts/{artifact_reparse['id']}/download-audit").get_json()["data"]
    assert len(audits) == 1
    assert audits[0]["result"] == "rejected"
    assert audits[0]["reasonCode"] == "reparse_point_detected"

    # 2. Unsafe path reference
    artifact_unsafe = _complete_artifact(
        repo,
        default_root,
        "artifact-unsafe-audit",
        output_name="unsafe_audit.xlsx",
    )
    poisoned = dict(artifact_unsafe)
    poisoned["relative_path"] = "../escape.xlsx"
    monkeypatch.setattr(repo, "get_artifact", lambda aid: poisoned if aid == artifact_unsafe["id"] else None)

    resp_unsafe = client.get(f"/api/excel-artifacts/{artifact_unsafe['id']}/download")
    assert resp_unsafe.status_code == 409

    audits_unsafe = client.get(f"/api/excel-artifacts/{artifact_unsafe['id']}/download-audit").get_json()["data"]
    assert len(audits_unsafe) == 1
    assert audits_unsafe[0]["result"] == "rejected"
    assert audits_unsafe[0]["reasonCode"] == "unsafe_path"


def test_excel_artifact_download_audit_limits_and_validation(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    artifact = _complete_artifact(
        repo,
        default_root,
        "artifact-audit-limits",
        output_name="limits.xlsx",
    )
    artifact_id = int(artifact["id"])

    # Generate 5 download events
    for _ in range(5):
        client.get(f"/api/excel-artifacts/{artifact_id}/download")

    # limit=2
    resp_l2 = client.get(f"/api/excel-artifacts/{artifact_id}/download-audit?limit=2")
    assert resp_l2.status_code == 200
    assert len(resp_l2.get_json()["data"]) == 2

    # Invalid limits: 422
    for bad_limit in ["0", "-1", "201", "abc", "true"]:
        resp_bad = client.get(f"/api/excel-artifacts/{artifact_id}/download-audit?limit={bad_limit}")
        assert resp_bad.status_code == 422
        assert resp_bad.get_json()["error"]["type"] == "ValidationError"


def test_excel_artifact_download_audit_best_effort_db_failure(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_root, _, _ = roots_fixture
    content = b"valid content"
    artifact = _complete_artifact(
        repo,
        default_root,
        "artifact-audit-db-fail",
        output_name="db_fail.xlsx",
        data=content,
    )
    artifact_id = int(artifact["id"])

    # Simulate DB failure during audit record
    def fail_record(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repo, "record_artifact_download_audit", fail_record)

    # 1. Successful download still succeeds despite audit failure
    resp_dl = client.get(f"/api/excel-artifacts/{artifact_id}/download")
    assert resp_dl.status_code == 200
    assert resp_dl.data == content

    # 2. Unavailable download still returns 409 despite audit failure
    (default_root / "db_fail.xlsx").unlink()
    resp_missing = client.get(f"/api/excel-artifacts/{artifact_id}/download")
    assert resp_missing.status_code == 409
    assert resp_missing.get_json()["error"]["type"] == "ArtifactUnavailable"


# ── GET /api/excel-roots Tests ────────────────────────────────


def test_get_excel_roots_configured(
    client,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, secondary_root, _ = roots_fixture
    resp = client.get("/api/excel-roots")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    data = resp.get_json()
    assert data["ok"] is True
    assert data["data"] == [
        {"rootId": "default"},
        {"rootId": "secondary"},
    ]
    # Verify no paths, environment, or credentials leak
    _assert_privacy(
        data,
        forbidden_paths=[default_root, secondary_root],
    )


def test_get_excel_roots_unconfigured(unconfigured_client) -> None:
    resp = unconfigured_client.get("/api/excel-roots")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"]["type"] == "NotConfigured"


def test_get_excel_roots_server_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = web_app.ExcelTaskAdminService
    monkeypatch.setattr(svc, "list_roots", MagicMock(side_effect=RuntimeError("internal boom")))
    resp = client.get("/api/excel-roots")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"]["type"] == "ServerError"


# ── GET /api/excel-artifacts/retention-plan Tests ─────────────


def test_get_retention_plan_configured_success(
    client,
    repo: ExcelTaskRepository,
    test_db: DatabaseManager,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, secondary_root, _ = roots_fixture
    # Create artifacts
    art1 = _complete_artifact(repo, default_root, "ret-plan-1", output_name="art1.xlsx")
    art2 = _complete_artifact(repo, default_root, "ret-plan-2", output_name="art2.xlsx")
    art3 = _complete_artifact(repo, default_root, "ret-plan-3", output_name="art3.xlsx")

    # Set timestamps: art1 (oldest), art2 (middle), art3 (future)
    with test_db.get_connection() as conn:
        conn.execute("UPDATE excel_task_artifacts SET created_at = '2026-01-01T00:00:00.000Z' WHERE id = ?", (art1["id"],))
        conn.execute("UPDATE excel_task_artifacts SET created_at = '2026-01-10T00:00:00.000Z' WHERE id = ?", (art2["id"],))
        conn.execute("UPDATE excel_task_artifacts SET created_at = '2026-02-01T00:00:00.000Z' WHERE id = ?", (art3["id"],))

    # Inject clock fixed at 2026-01-20T00:00:00Z
    # With retentionDays=5 -> cutoff is 2026-01-15 -> art1 and art2 qualify
    fixed_now = datetime(2026, 1, 20, 0, 0, 0, tzinfo=timezone.utc)
    app = web_app.create_app(excel_repository=repo, excel_clock=lambda: fixed_now)
    app.config.update(TESTING=True)
    custom_client = app.test_client()

    resp = custom_client.get("/api/excel-artifacts/retention-plan?retentionDays=5&limit=100")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    payload = resp.get_json()
    assert payload["ok"] is True
    data = payload["data"]
    assert data["cutoffAt"] == "2026-01-15T00:00:00.000Z"
    assert data["truncated"] is False
    assert len(data["artifacts"]) == 2
    # Oldest first ordering
    assert data["artifacts"][0]["id"] == art1["id"]
    assert data["artifacts"][0]["displayName"] == "art1.xlsx"
    assert data["artifacts"][1]["id"] == art2["id"]
    assert data["artifacts"][1]["displayName"] == "art2.xlsx"

    # CamelCase properties
    for item in data["artifacts"]:
        assert "id" in item
        assert "taskId" in item
        assert "runId" in item
        assert "artifactType" in item
        assert "rootId" in item
        assert "relativePath" in item
        assert "displayName" in item
        assert "sizeBytes" in item
        assert "sha256" in item
        assert "createdAt" in item

    # Privacy check
    _assert_privacy(payload, forbidden_paths=[default_root, secondary_root])


def test_get_retention_plan_truncation_and_tie_break(
    repo: ExcelTaskRepository,
    test_db: DatabaseManager,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    art1 = _complete_artifact(repo, default_root, "tie-1", output_name="t1.xlsx")
    art2 = _complete_artifact(repo, default_root, "tie-2", output_name="t2.xlsx")
    art3 = _complete_artifact(repo, default_root, "tie-3", output_name="t3.xlsx")

    # Identical timestamps -> tie-break by ID ascending
    with test_db.get_connection() as conn:
        conn.execute("UPDATE excel_task_artifacts SET created_at = '2026-01-01T12:00:00.000Z' WHERE id IN (?, ?, ?)", (art1["id"], art2["id"], art3["id"]))

    fixed_now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    app = web_app.create_app(excel_repository=repo, excel_clock=lambda: fixed_now)
    app.config.update(TESTING=True)
    custom_client = app.test_client()

    # Limit=2 should return first 2 with truncated=True
    resp = custom_client.get("/api/excel-artifacts/retention-plan?retentionDays=2&limit=2")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["truncated"] is True
    assert len(data["artifacts"]) == 2
    assert data["artifacts"][0]["id"] == min(art1["id"], art2["id"], art3["id"])


def test_get_retention_plan_unconfigured(unconfigured_client) -> None:
    resp = unconfigured_client.get("/api/excel-artifacts/retention-plan?retentionDays=30")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"]["type"] == "NotConfigured"


def test_get_retention_plan_validation_errors(client) -> None:
    # Missing retentionDays
    resp1 = client.get("/api/excel-artifacts/retention-plan")
    assert resp1.status_code == 422
    assert resp1.get_json()["error"]["type"] == "ValidationError"
    assert "retentionDays" in resp1.get_json()["error"]["fields"]

    # retentionDays out of range (1..3650)
    for bad_days in ["0", "-5", "3651", "10000", "abc", "true"]:
        resp = client.get(f"/api/excel-artifacts/retention-plan?retentionDays={bad_days}")
        assert resp.status_code == 422
        assert resp.get_json()["error"]["type"] == "ValidationError"
        assert "retentionDays" in resp.get_json()["error"]["fields"]

    # limit out of range (1..500)
    for bad_limit in ["0", "-1", "501", "1000", "xyz", "true"]:
        resp = client.get(f"/api/excel-artifacts/retention-plan?retentionDays=30&limit={bad_limit}")
        assert resp.status_code == 422
        assert resp.get_json()["error"]["type"] == "ValidationError"
        assert "limit" in resp.get_json()["error"]["fields"]


def test_get_retention_plan_read_only_invariant(
    client,
    repo: ExcelTaskRepository,
    roots_fixture: tuple[Path, Path, ApprovedExcelRoots],
) -> None:
    default_root, _, _ = roots_fixture
    artifact = _complete_artifact(repo, default_root, "ro-plan-check", output_name="ro.xlsx")
    art_id = int(artifact["id"])
    target_file = default_root / "ro.xlsx"
    assert target_file.is_file()

    # Record initial mtime and content
    initial_bytes = target_file.read_bytes()
    initial_mtime = target_file.stat().st_mtime

    # Call retention plan
    resp = client.get("/api/excel-artifacts/retention-plan?retentionDays=1")
    assert resp.status_code == 200

    # Ensure file on disk was NOT touched, opened, deleted, or modified
    assert target_file.is_file()
    assert target_file.read_bytes() == initial_bytes
    assert target_file.stat().st_mtime == initial_mtime

    # Ensure artifact still exists in DB unchanged
    db_art = repo.get_artifact(art_id)
    assert db_art is not None


def test_get_retention_plan_unknown_roots_tolerance(
    client,
    test_db: DatabaseManager,
) -> None:
    # Insert artifact record with root_id that does not exist in ApprovedExcelRoots
    valid_hash = "a" * 64
    valid_fp = "b" * 64
    with test_db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO excel_tasks (
                operation, status, idempotency_key_hash, request_fingerprint,
                options_json, attempt_count, max_attempts, created_at, updated_at
            ) VALUES ('merge_append', 'succeeded', ?, ?, '{}', 1, 1,
                     '2025-01-01T00:00:00.000Z', '2025-01-01T00:00:00.000Z')
            """,
            (valid_hash, valid_fp),
        )
        task_id = cursor.lastrowid
        run_cursor = conn.execute(
            """
            INSERT INTO excel_task_runs (task_id, attempt, run_state, created_at)
            VALUES (?, 1, 'succeeded', '2025-01-01T00:00:00.000Z')
            """,
            (task_id,),
        )
        run_id = run_cursor.lastrowid
        conn.execute(
            """
            INSERT INTO excel_task_artifacts (
                task_id, run_id, artifact_type, root_id, relative_path,
                display_name, size_bytes, sha256, created_at
            ) VALUES (?, ?, 'output', 'decommissioned_root', 'old.xlsx', 'old.xlsx', 100,
                      '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
                      '2025-01-01T00:00:00.000Z')
            """,
            (task_id, run_id),
        )

    resp = client.get("/api/excel-artifacts/retention-plan?retentionDays=1")
    assert resp.status_code == 200
    artifacts = resp.get_json()["data"]["artifacts"]
    matching = [a for a in artifacts if a["rootId"] == "decommissioned_root"]
    assert len(matching) == 1
    assert matching[0]["relativePath"] == "old.xlsx"


def test_no_retention_mutation_endpoints_exist(client) -> None:
    # Verify forbidden retention mutation endpoints return 404 or 405
    assert client.delete("/api/excel-artifacts/retention-plan").status_code in (404, 405)
    assert client.post("/api/excel-artifacts/retention-plan").status_code in (404, 405)
    assert client.delete("/api/excel-artifacts/1").status_code in (404, 405)
    assert client.post("/api/excel-artifacts/cleanup").status_code == 404
    assert client.delete("/api/excel-roots/default").status_code == 404
