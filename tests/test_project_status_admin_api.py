# -*- coding: utf-8 -*-
"""Focused offline tests for Project Status Candidate-Preview, Sync-Now, and Mutation APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.project_status_sync_runner import (
    ConnectorRegistry,
    ProjectStatusConnector,
    SyncBindingContext,
)
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)


class FakeConnector(ProjectStatusConnector):
    """Configurable offline fake connector returning canned snapshot or raising exceptions."""

    def __init__(
        self,
        snapshot: ConnectorSnapshot | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._exc = exc
        self.collect_calls: list[SyncBindingContext] = []

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        self.collect_calls.append(context)
        if self._exc is not None:
            raise self._exc
        assert self._snapshot is not None
        return self._snapshot


@pytest.fixture()
def test_db(monkeypatch, tmp_path: Path) -> DatabaseManager:
    """Provide an isolated temporary DatabaseManager for web API tests."""
    db_file = tmp_path / "project_status_admin_test.db"
    db_instance = DatabaseManager(db_path=db_file)
    db_instance.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_instance)
    return db_instance


@pytest.fixture()
def fake_registry() -> ConnectorRegistry:
    """Provide an isolated fake connector registry."""
    return ConnectorRegistry()


@pytest.fixture()
def registry_factory(monkeypatch, fake_registry: ConnectorRegistry) -> MagicMock:
    """Provide a spy/mock factory for create_production_registry returning fake_registry."""
    factory = MagicMock(return_value=fake_registry)
    monkeypatch.setattr(web_app, "create_production_registry", factory)
    return factory


@pytest.fixture()
def client(test_db: DatabaseManager, registry_factory: MagicMock):
    """Provide a Flask test client with isolated DB and fake ConnectorRegistry."""
    app = web_app.create_app()
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


def _current_updated_at(db: DatabaseManager, deliverable_id: str) -> str:
    """Retrieve current updated_at for a deliverable."""
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
    assert row is not None
    return str(row["updated_at"])


def test_debug_bundle_json_export_is_redacted_and_offline(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/debug-bundle?format=json",
        headers=_loopback_headers(),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["filtered"] is True
    assert payload["schemaVersion"] == "1"
    assert "credential_ref" not in str(payload).lower()


def test_debug_bundle_zip_export_is_downloadable(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/debug-bundle?format=zip",
        headers=_loopback_headers(),
    )
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert response.data[:2] == b"PK"


def _record_two_observations_for_d5(
    db: DatabaseManager,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
    fields: list[str] | None = None,
) -> None:
    """Record two matched tdc observations for the same external key."""
    field_list = fields if fields is not None else [
        "currentApprover", "approvalComment", "incident", "reportType",
    ]
    report = {
        "fields": field_list,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    db.record_mapping_observation(
        deliverable_id=deliverable_id,
        source_type=source_type,
        result_state="matched",
        external_key=external_key,
        candidate_fingerprint="fp1",
        candidate_count=1,
        candidate_summary_json=json.dumps([{"externalKey": external_key, "fields": {}}]),
        field_report_json=json.dumps(report),
    )
    db.record_mapping_observation(
        deliverable_id=deliverable_id,
        source_type=source_type,
        result_state="matched",
        external_key=external_key,
        candidate_fingerprint="fp2",
        candidate_count=1,
        candidate_summary_json=json.dumps([{"externalKey": external_key, "fields": {}}]),
        field_report_json=json.dumps(report),
    )


def _configure_ready_d5_binding(
    db: DatabaseManager,
    external_key: str = "FM-1",
    credential_ref: str = "placeholder_cred_alias",
) -> None:
    """Configure a fully ready D5 binding meeting all assertion contracts."""
    _record_two_observations_for_d5(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key=external_key,
        fields=["currentApprover", "incident", "reportType"],
    )
    update_service = ProjectStatusUpdateService(db)
    update_service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": external_key,
            "credentialRef": credential_ref,
            "matchRule": {"reportType": "data_model", "incident": external_key},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )


def _matched_snapshot(
    db: DatabaseManager,
    deliverable_id: str = "VPI-T2-D5",
    external_key: str = "FM-1",
    external_version: str = "v-20260822-001",
    **field_values: Any,
) -> ConnectorSnapshot:
    """Create a standardized matched ConnectorSnapshot."""
    return ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key=external_key,
                external_version=external_version,
                field_values=field_values,
                fetched_at="2026-08-22T00:00:00.000Z",
            )
        ],
        external_version=external_version,
        fetched_at="2026-08-22T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, deliverable_id),
    )


def _normalized_response_keys(value: Any) -> set[str]:
    """Collect response keys recursively using a case-insensitive form."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add("".join(char for char in str(key).lower() if char.isalnum()))
            keys.update(_normalized_response_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_normalized_response_keys(item))
    return keys


# ── 1. GET candidate-preview Contract ─────────────────────────────────────────


def test_candidate_preview_returns_no_store_and_saved_evidence_differences(
    client, test_db: DatabaseManager, registry_factory: MagicMock
) -> None:
    """GET candidate-preview returns no-store and saved-evidence ready/difference payload."""
    _configure_ready_d5_binding(test_db, external_key="FM-1")

    # Record candidate rows through mapping observation
    candidate_row = {
        "incident": "FM-1",
        "currentApprover": "李四（新负责人）",
        "reportType": "data_model",
    }
    discovery_service = web_app.MappingDiscoveryService(test_db)
    discovery_service.observe("VPI-T2-D5", "tdc", [candidate_row])
    discovery_service.observe("VPI-T2-D5", "tdc", [candidate_row])

    resp = client.get("/api/project-status/deliverables/VPI-T2-D5/candidate-preview")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    registry_factory.assert_not_called()

    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["deliverableId"] == "VPI-T2-D5"
    assert data["state"] == "matched"
    assert data["reason"] is None
    assert data["externalKey"] == "FM-1"
    assert data["stability"] == {"confirmed": 2, "required": 2, "ready": True}

    diffs = data["differences"]
    assert len(diffs) == 1
    owner_diff = diffs[0]
    assert owner_diff["targetField"] == "owner"
    assert owner_diff["sourceField"] == "currentApprover"
    assert owner_diff["currentValue"] == "赵岩"
    assert owner_diff["candidateValue"] == "李四（新负责人）"
    assert owner_diff["changed"] is True

    # Ensure no secrets, raw xml, credentials, or candidate fingerprints leak
    serialized = json.dumps(body)
    assert "credential_ref" not in serialized
    assert "lease_token" not in serialized
    assert "candidate_fingerprint" not in serialized


def test_candidate_preview_unknown_deliverable_returns_404_no_store(
    client, registry_factory: MagicMock
) -> None:
    """GET candidate-preview returns 404 with no-store when deliverable is unknown."""
    resp = client.get("/api/project-status/deliverables/UNKNOWN-DELIVERABLE/candidate-preview")
    assert resp.status_code == 404
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "NotFound",
            "message": "未找到交付物",
        },
    }
    registry_factory.assert_not_called()


def test_candidate_preview_does_not_invoke_external_factories(
    client, test_db: DatabaseManager, registry_factory: MagicMock, monkeypatch
) -> None:
    """Candidate-preview is strictly offline and never calls external connectors or factories."""
    _configure_ready_d5_binding(test_db, external_key="FM-1")

    mock_aras = MagicMock()
    mock_tdc = MagicMock()
    monkeypatch.setattr(web_app, "_build_aras_client_from_payload", mock_aras)
    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", mock_tdc)

    resp = client.get("/api/project-status/deliverables/VPI-T2-D5/candidate-preview")
    assert resp.status_code == 200
    mock_aras.assert_not_called()
    mock_tdc.assert_not_called()
    registry_factory.assert_not_called()


# ── 2. POST sync-now Contract Rejections Before Registry Creation ──────────────


def test_sync_now_rejects_d1_with_409_manual_only(
    client, registry_factory: MagicMock
) -> None:
    """POST sync-now returns 409 ManualOnly for D1 before registry creation."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.post(
        "/api/project-status/deliverables/VPI-T2-D1/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 409
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json() == {
        "ok": False,
        "error": {
            "type": "ManualOnly",
            "message": "该交付物仅允许手工维护",
        },
    }
    registry_factory.assert_not_called()


def test_sync_now_rejects_d4_with_409_contract_blocked(
    client, registry_factory: MagicMock
) -> None:
    """POST sync-now returns 409 ContractBlocked for D4 before registry creation."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.post(
        "/api/project-status/deliverables/VPI-T2-D4/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 409
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == "ContractBlocked"
    assert "HAR" in body["error"]["message"]
    registry_factory.assert_not_called()


@pytest.mark.parametrize("deliverable_id", ["VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D5"])
def test_sync_now_rejects_unconfigured_deliverables_with_409_sync_not_ready(
    client, registry_factory: MagicMock, deliverable_id: str
) -> None:
    """POST sync-now returns 409 SyncNotReady for unconfigured D2/D3/D5 before registry creation."""
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.post(
        f"/api/project-status/deliverables/{deliverable_id}/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 409
    assert resp.headers.get("Cache-Control") == "no-store"
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == "SyncNotReady"
    registry_factory.assert_not_called()


# ── 3. Ready D5 Sync-Now Success Contract and Secret Safety ────────────────────


def test_ready_d5_sync_now_applies_automatic_field_and_sanitizes_response(
    client,
    test_db: DatabaseManager,
    fake_registry: ConnectorRegistry,
    registry_factory: MagicMock,
) -> None:
    """A ready D5 sync-now applies only approved automatic field, persists trigger_type=sync_now, and sanitizes output."""
    _configure_ready_d5_binding(
        test_db,
        external_key="FM-1",
        credential_ref="placeholder_alias_ref",
    )

    fake_connector = FakeConnector(
        snapshot=_matched_snapshot(
            test_db,
            deliverable_id="VPI-T2-D5",
            external_key="FM-1",
            external_version="v-sync-001",
            owner="新项目经理（自动同步）",
            plannedDate="2026-09-01",
            note="未授权字段",
        )
    )
    fake_registry.register("tdc", fake_connector)

    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    registry_factory.assert_called_once()

    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]

    # Response shape assertions covering ok/data/exitCode/result/finalState/appliedFields/skippedFields/errorType/errorMessage
    assert data["exitCode"] == 2
    assert "status" not in data
    assert "progress" not in data

    res = data["result"]
    assert res["deliverableId"] == "VPI-T2-D5"
    assert res["sourceType"] == "tdc"
    assert res["outcome"] == "partial"
    assert isinstance(res["runId"], int)
    assert res["finalState"] == "partial"
    assert res["appliedFields"] == ["owner"]
    assert res["skippedFields"] == {
        "plannedDate": "field is manually locked",
        "note": "field is manually locked",
    }
    assert res["errorType"] is None
    assert res["errorMessage"] == "sync completed"

    # Assert secrets, credentials, lease tokens, raw candidate, cookies, auth headers are never returned
    raw_response_text = json.dumps(body)
    assert "placeholder_alias_ref" not in raw_response_text
    response_keys = _normalized_response_keys(body)
    assert not {
        key for key in response_keys
        if (
            "credential" in key
            or "token" in key
            or "password" in key
            or "secret" in key
            or "session" in key
            or key in {"cookie", "authorization", "rawcandidate"}
        )
    }

    # Verify deliverable business row updated only for approved automatic field
    with test_db.get_connection() as conn:
        row = conn.execute(
            "SELECT owner, planned_date, remark FROM project_status_deliverables WHERE id='VPI-T2-D5'"
        ).fetchone()
        assert row["owner"] == "新项目经理（自动同步）"
        assert row["planned_date"] == "2026-08-08"  # initial value unchanged
        assert row["remark"] == "逾期 5 天"  # initial value unchanged

        # Verify trigger_type=sync_now persisted in run and audit
        run_row = conn.execute(
            "SELECT id, trigger_type, run_state FROM project_status_sync_runs WHERE id=?",
            (res["runId"],),
        ).fetchone()
        assert run_row is not None
        assert run_row["trigger_type"] == "sync_now"
        assert run_row["run_state"] == "partial"

        audit_row = conn.execute(
            "SELECT trigger_type, result, applied_changes_json, skipped_fields_json "
            "FROM project_status_update_audit WHERE deliverable_id='VPI-T2-D5'"
        ).fetchone()
        assert audit_row is not None
        assert audit_row["trigger_type"] == "sync_now"
        assert audit_row["result"] == "applied"
        assert json.loads(audit_row["applied_changes_json"]) == {"owner": "新项目经理（自动同步）"}
        assert json.loads(audit_row["skipped_fields_json"]) == {
            "plannedDate": "field is manually locked",
            "note": "field is manually locked",
        }


# ── 4. Busy Lease and Concurrency Guard ────────────────────────────────────────


def test_already_leased_binding_returns_busy_result_without_second_connector_call_or_run(
    client, test_db: DatabaseManager, fake_registry: ConnectorRegistry
) -> None:
    """An already leased ready binding returns a busy result without a second connector call or second run."""
    _configure_ready_d5_binding(test_db, external_key="FM-1")

    # Acquire an active lease in advance
    binding = test_db.get_sync_binding_by_deliverable("VPI-T2-D5")
    assert binding is not None
    test_db.acquire_sync_lease(int(binding["id"]), "scheduled")

    fake_connector = FakeConnector(
        snapshot=_matched_snapshot(test_db, deliverable_id="VPI-T2-D5", external_key="FM-1")
    )
    fake_registry.register("tdc", fake_connector)

    with test_db.get_connection() as conn:
        runs_count_before = conn.execute("SELECT COUNT(1) AS c FROM project_status_sync_runs").fetchone()["c"]

    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"

    body = resp.get_json()
    assert body["ok"] is True
    res = body["data"]["result"]
    assert res["outcome"] == "busy"
    assert res["finalState"] == "busy"
    assert res["runId"] is None

    # No second connector call
    assert len(fake_connector.collect_calls) == 0

    # No second run created
    with test_db.get_connection() as conn:
        runs_count_after = conn.execute("SELECT COUNT(1) AS c FROM project_status_sync_runs").fetchone()["c"]
        assert runs_count_after == runs_count_before == 1


# ── 5. Sensitive Exception Redaction in HTTP Response and Run Evidence ─────────


def test_connector_exception_with_sensitive_info_is_redacted(
    client, test_db: DatabaseManager, fake_registry: ConnectorRegistry
) -> None:
    """A fake connector exception containing password/token text is redacted in HTTP response and run evidence."""
    _configure_ready_d5_binding(test_db, external_key="FM-1")

    leak_message = "RemoteError: password=secret_pw_12345 Bearer eyJhbGciOi token=tok_abc987 Cookie=sid_secret"
    fake_connector = FakeConnector(exc=RuntimeError(leak_message))
    fake_registry.register("tdc", fake_connector)

    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    resp = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"

    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["exitCode"] == 1

    res = data["result"]
    assert res["outcome"] == "failed"
    assert res["finalState"] == "failed"
    assert res["errorType"] == "connector_error"

    raw_response_text = json.dumps(body)
    assert "secret_pw_12345" not in raw_response_text
    assert "eyJhbGciOi" not in raw_response_text
    assert "tok_abc987" not in raw_response_text
    assert "sid_secret" not in raw_response_text
    assert "[redacted]" in raw_response_text
    assert "Bearer [redacted]" in raw_response_text

    # Verify run evidence in SQLite is also redacted
    with test_db.get_connection() as conn:
        run_row = conn.execute(
            "SELECT error_message, result_summary FROM project_status_sync_runs WHERE id=?",
            (res["runId"],),
        ).fetchone()
        assert run_row is not None
        db_text = json.dumps(dict(run_row))
        assert "secret_pw_12345" not in db_text
        assert "eyJhbGciOi" not in db_text
        assert "tok_abc987" not in db_text
        assert "sid_secret" not in db_text
        assert "[redacted]" in db_text


# ── 6. Local-Only Security Guard: REMOTE_ADDR, Sec-Fetch-Site, and Origin ───────


@pytest.mark.parametrize(
    ("remote_addr", "host", "origin"),
    [
        ("127.0.0.1", "localhost:5000", "http://localhost:5000"),
        ("127.0.0.1", "127.0.0.1:5000", "http://127.0.0.1:5000"),
        ("::1", "localhost:5000", "http://localhost:5000"),
        ("::1", "[::1]:5000", "http://[::1]:5000"),
        ("::ffff:127.0.0.1", "localhost:5000", "http://localhost:5000"),
        ("127.0.0.1", "localhost:5000", None),
    ],
)
def test_sync_now_accepts_valid_loopback_remote_and_host(
    client,
    test_db: DatabaseManager,
    fake_registry: ConnectorRegistry,
    remote_addr: str,
    host: str,
    origin: str | None,
) -> None:
    """Sync-now accepts valid loopback remote, host, and matching origin."""
    _configure_ready_d5_binding(test_db, external_key="FM-1")
    fake_registry.register(
        "tdc",
        FakeConnector(snapshot=_matched_snapshot(test_db, deliverable_id="VPI-T2-D5", external_key="FM-1")),
    )

    headers = _loopback_headers(host=host, origin=origin)
    environ = {"REMOTE_ADDR": remote_addr, "HTTP_HOST": host}

    resp = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/sync-now",
        headers=headers,
        environ_base=environ,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    assert resp.get_json()["ok"] is True


@pytest.mark.parametrize(
    "mutation_call",
    [
        ("POST", "/api/project-status/deliverables/VPI-T2-D5/sync-now", None),
        ("PATCH", "/api/project-status/deliverables/VPI-T2-D5", {"updatedAt": "2026-08-22 00:00:00.000"}),
        ("PATCH", "/api/project-status/deliverables/VPI-T2-D5/update-policy", {"mode": "manual"}),
        ("POST", "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", {}),
    ],
)
@pytest.mark.parametrize(
    "non_loopback_remote",
    ["192.168.1.100", "10.0.0.1", "8.8.8.8", "172.16.0.5", "2001:db8::1"],
)
def test_mutations_reject_non_loopback_remote(
    client,
    registry_factory: MagicMock,
    mutation_call: tuple[str, str, dict | None],
    non_loopback_remote: str,
) -> None:
    """All project-status mutation endpoints reject non-loopback REMOTE_ADDR before registry creation."""
    method, endpoint, payload = mutation_call
    headers = _loopback_headers()
    environ = {"REMOTE_ADDR": non_loopback_remote}

    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if payload is not None:
        kwargs["json"] = payload

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
    registry_factory.assert_not_called()


@pytest.mark.parametrize(
    "mutation_call",
    [
        ("POST", "/api/project-status/deliverables/VPI-T2-D5/sync-now", None),
        ("PATCH", "/api/project-status/deliverables/VPI-T2-D5", {"updatedAt": "2026-08-22 00:00:00.000"}),
        ("PATCH", "/api/project-status/deliverables/VPI-T2-D5/update-policy", {"mode": "manual"}),
        ("POST", "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", {}),
    ],
)
def test_mutations_reject_cross_site_sec_fetch_site(
    client,
    registry_factory: MagicMock,
    mutation_call: tuple[str, str, dict | None],
) -> None:
    """All project-status mutation endpoints reject Sec-Fetch-Site: cross-site."""
    method, endpoint, payload = mutation_call
    headers = _loopback_headers(sec_fetch_site="cross-site")
    environ = {"REMOTE_ADDR": "127.0.0.1"}

    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if payload is not None:
        kwargs["json"] = payload

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
    registry_factory.assert_not_called()


@pytest.mark.parametrize(
    "mutation_call",
    [
        ("POST", "/api/project-status/deliverables/VPI-T2-D5/sync-now", None),
        ("PATCH", "/api/project-status/deliverables/VPI-T2-D5", {"updatedAt": "2026-08-22 00:00:00.000"}),
        ("PATCH", "/api/project-status/deliverables/VPI-T2-D5/update-policy", {"mode": "manual"}),
        ("POST", "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", {}),
    ],
)
@pytest.mark.parametrize(
    "invalid_origin",
    [
        "https://localhost:5000",
        "http://attacker.com",
        "http://localhost:9999",
        "http://user:pass@localhost:5000",
        "http://localhost:5000/subpath",
        "http://localhost:5000/?query=1",
        "http://localhost:5000/#fragment",
        "invalid-origin-uri",
    ],
)
def test_mutations_reject_mismatched_origin(
    client,
    registry_factory: MagicMock,
    mutation_call: tuple[str, str, dict | None],
    invalid_origin: str,
) -> None:
    """All project-status mutation endpoints reject invalid/mismatched Origin."""
    method, endpoint, payload = mutation_call
    headers = _loopback_headers(origin=invalid_origin)
    environ = {"REMOTE_ADDR": "127.0.0.1", "HTTP_HOST": "localhost:5000"}

    kwargs: dict[str, Any] = {"headers": headers, "environ_base": environ}
    if payload is not None:
        kwargs["json"] = payload

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
    registry_factory.assert_not_called()
