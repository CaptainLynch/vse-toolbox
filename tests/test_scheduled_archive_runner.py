# -*- coding: utf-8 -*-
"""Offline unit and integration tests for ArchiveSyncRunner and ArchiveConnectorRegistry.

All tests run strictly offline with temporary SQLite databases, MemoryCredentialProvider,
injected clocks, injected sleepers, and mock connectors.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from core.archive_store import ArchiveArtifact
from core.credential_provider import (
    CredentialProviderError,
    MemoryCredentialProvider,
    ResolvedCredential,
)
from core.db_manager import ARCHIVE_JOB_CONTRACTS, DatabaseManager
from services.aras_auth import ArasAuthError
from services.aras_crawler import ArasAuthenticationError, ArasCrawlerError
from services.deliverable_form_analysis import form_definition
from services.scheduled_archive_runner import (
    DEFAULT_BUSINESS_DEPARTMENT,
    EXIT_ATTENTION,
    EXIT_FAILED,
    EXIT_OK,
    ArchiveCollection,
    ArchiveConnectorRegistry,
    ArchiveJobContext,
    ArchiveJobRunResult,
    ArchiveRunOnceResult,
    ArchiveSyncRunner,
)
from services.tdc_auth import TDCAuthError
from services.windows_http import WinHTTPError, WinHTTPTimeoutError


class FakeConnector:
    """Configurable fake connector for offline runner testing."""

    def __init__(
        self,
        *,
        record_count: int = 10,
        artifacts: tuple[ArchiveArtifact, ...] | None = None,
        exception: BaseException | None = None,
        exceptions: list[BaseException] | None = None,
    ) -> None:
        self.record_count = record_count
        self.artifacts = artifacts or (
            ArchiveArtifact(
                relative_path="aras/ewo/2026-08-22/1/records.csv",
                artifact_type="csv",
                display_name="records.csv",
                size_bytes=1024,
                sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            ),
        )
        self.exception = exception
        self.exceptions = list(exceptions) if exceptions is not None else None
        self.call_count = 0
        self.last_context: ArchiveJobContext | None = None
        self.last_credential: ResolvedCredential | None = None
        self.seen_credentials: list[tuple[str, str]] = []

    def collect(self, context: ArchiveJobContext, credential: ResolvedCredential) -> ArchiveCollection:
        self.call_count += 1
        self.last_context = context
        self.last_credential = credential
        self.seen_credentials.append((credential.username, credential.password))

        if self.exceptions:
            raise self.exceptions.pop(0)
        if self.exception is not None:
            raise self.exception

        return ArchiveCollection(record_count=self.record_count, artifacts=self.artifacts)


class SnapshotConnector(FakeConnector):
    """Fake scheduled connector returning one safe form row for publication."""

    def collect(self, context: ArchiveJobContext, credential: ResolvedCredential) -> ArchiveCollection:
        base = super().collect(context, credential)
        return ArchiveCollection(
            record_count=base.record_count,
            artifacts=base.artifacts,
            form_rows=(
                {
                    "_no": "PAA-SNAPSHOT-1",
                    "_department": "部门A",
                    "_pe_tdc_smt": "科室A",
                    "_vehicles": "F610S",
                    "state": "PROC",
                    "_submit_date": "2026-09-01",
                },
            ),
        )


class TdcSnapshotConnector(FakeConnector):
    """Fake TDC connector returning synthetic positional data-model rows."""

    def collect(self, context: ArchiveJobContext, credential: ResolvedCredential) -> ArchiveCollection:
        base = super().collect(context, credential)
        return ArchiveCollection(
            record_count=base.record_count,
            artifacts=base.artifacts,
            form_rows=(
                {
                    "values": _tdc_form_values("审批中", "2026-08-30 09:30:00"),
                    "sheetName": "Sheet1",
                },
                {
                    "values": _tdc_form_values("已完成", "2026-08-20 10:00:00"),
                    "sheetName": "Sheet1",
                },
            ),
        )


def _tdc_form_values(status: str, request_date: str) -> list[object | None]:
    """One synthetic 47-column TDC data-model row (all values fabricated)."""
    headers = form_definition("tdc_data_model")["headerRows"][0]
    values: list[object | None] = [None] * len(headers)
    for label, value in {
        "实例号": "90000101",
        "流水单号": "F999X-3D-0001",
        "发布属性": "T2发布",
        "部门": "内饰科",
        "申请日期": request_date,
        "项目/车型": "F999X",
        "零件号": "27000001",
        "状态": status,
    }.items():
        values[headers.index(label)] = value
    return values


class CountingCredentialProvider(MemoryCredentialProvider):
    """Credential provider tracking the number of resolve invocations."""

    def __init__(self, credentials: dict[str, tuple[str, str]] | None = None) -> None:
        super().__init__(credentials or {})
        self.resolve_call_count = 0

    def resolve(self, credential_ref: str):
        self.resolve_call_count += 1
        return super().resolve(credential_ref)


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(db_path=tmp_path / "runner_test.db")
    manager.init_database()
    return manager


@pytest.fixture()
def registry() -> ArchiveConnectorRegistry:
    return ArchiveConnectorRegistry()


def _enable_job(
    db: DatabaseManager,
    job_key: str = "aras_ewo",
    *,
    credential_ref: str = "alias_test",
    output_subdir: str = "",
    output_directory: str = "",
    interval_minutes: int = 60,
) -> int:
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduled_archive_jobs
            SET enabled = 1, credential_ref = ?, output_subdir = ?, output_directory = ?, interval_minutes = ?
            WHERE job_key = ?
            """,
            (credential_ref, output_subdir, output_directory, interval_minutes, job_key),
        )
        row = conn.execute("SELECT id FROM scheduled_archive_jobs WHERE job_key = ?", (job_key,)).fetchone()
    assert row is not None
    return int(row["id"])


def _get_run_row(db: DatabaseManager, run_id: int):
    with db.get_connection() as conn:
        return conn.execute("SELECT * FROM scheduled_archive_runs WHERE id = ?", (run_id,)).fetchone()


def _get_job_row(db: DatabaseManager, job_id: int):
    with db.get_connection() as conn:
        return conn.execute("SELECT * FROM scheduled_archive_jobs WHERE id = ?", (job_id,)).fetchone()


def _get_artifact_rows(db: DatabaseManager, run_id: int):
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT * FROM scheduled_archive_artifacts WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()


def _setup_runner(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
    credentials: dict[str, tuple[str, str]] | None = None,
    connectors: dict[str, FakeConnector] | None = None,
    **runner_kwargs,
) -> tuple[ArchiveSyncRunner, MemoryCredentialProvider]:
    provider = MemoryCredentialProvider(credentials or {})
    for k, v in (connectors or {}).items():
        registry.register(k, v)
    runner = ArchiveSyncRunner(db=db, credentials=provider, registry=registry, **runner_kwargs)
    return runner, provider


# ── 1. Registry ─────────────────────────────────────────────────────────────


def test_registry_registration_and_retrieval_for_approved_keys(registry: ArchiveConnectorRegistry) -> None:
    approved_keys = tuple(sorted(ARCHIVE_JOB_CONTRACTS.keys()))
    assert len(approved_keys) == 6
    connectors = {key: FakeConnector(record_count=5) for key in approved_keys}
    for key, conn in connectors.items():
        registry.register(key, conn)
    assert registry.registered_job_keys == approved_keys
    for key in approved_keys:
        assert registry.get(key) is connectors[key]


@pytest.mark.parametrize(
    "unapproved_key",
    ["unknown_job", "aras_a_face", "tdc_a_face", "tdc_aface", "aras_aface", "tdc_vdr_a_face", "", "custom_crawler"],
)
def test_registry_rejection_of_unknown_and_a_face_keys(
    registry: ArchiveConnectorRegistry,
    unapproved_key: str,
) -> None:
    with pytest.raises(ValueError, match="archive connector job key is not approved"):
        registry.register(unapproved_key, FakeConnector())
    assert registry.get(unapproved_key) is None


# ── 2. Success lifecycle & credentials & artifacts ──────────────────────────


def test_successful_run_job_lifecycle_and_cleared_credential(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_aras", output_subdir="custom_dir")
    user_val, pass_val = f"user_{secrets.token_hex(4)}", f"pass_{secrets.token_hex(8)}"
    art1 = ArchiveArtifact("custom_dir/aras/ewo/2026-08-22/1/table.csv", "normalized_csv", "table.csv", 2048, "abc111")
    art2 = ArchiveArtifact("custom_dir/aras/ewo/2026-08-22/1/meta.json", "summary_json", "meta.json", 512, "abc222")
    connector = FakeConnector(record_count=42, artifacts=(art1, art2))
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_aras": (user_val, pass_val)},
        connectors={"aras_ewo": connector},
    )
    result = runner.run_job(job_id)

    assert result == ArchiveJobRunResult(job_id, "aras_ewo", "completed", result.run_id, "success")
    assert result.run_id is not None
    assert connector.call_count == 1 and connector.seen_credentials == [(user_val, pass_val)]
    assert connector.last_credential is not None
    assert connector.last_credential.username == "" and connector.last_credential.password == ""
    assert connector.last_context is not None
    assert (
        connector.last_context.job_id == job_id
        and connector.last_context.job_key == "aras_ewo"
        and connector.last_context.source_type == "aras"
        and connector.last_context.report_type == "ewo"
        and connector.last_context.output_subdir == "custom_dir"
        and connector.last_context.run_id == result.run_id
    )

    run_row = _get_run_row(db, result.run_id)
    assert run_row["run_state"] == "success" and run_row["record_count"] == 42
    assert run_row["result_summary"] == "archived 42 records in 2 artifacts"
    assert run_row["started_at"] is not None and run_row["finished_at"] is not None

    artifact_rows = _get_artifact_rows(db, result.run_id)
    assert len(artifact_rows) == 2
    assert (
        artifact_rows[0]["relative_path"] == "custom_dir/aras/ewo/2026-08-22/1/table.csv"
        and artifact_rows[0]["artifact_type"] == "normalized_csv"
        and artifact_rows[0]["size_bytes"] == 2048
        and artifact_rows[0]["sha256"] == "abc111"
        and artifact_rows[1]["relative_path"] == "custom_dir/aras/ewo/2026-08-22/1/meta.json"
    )

    job_row = _get_job_row(db, job_id)
    assert job_row["sync_state"] == "success"
    assert job_row["last_success_at"] is not None and job_row["last_attempt_at"] is not None
    assert job_row["lease_token"] is None


@pytest.mark.parametrize(
    ("job_key", "department_filter_key"),
    [
        ("aras_ewo", "responsibleDepartment"),
        ("aras_paa", "department"),
    ],
)
def test_builtin_department_uses_each_connector_filter_contract(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
    job_key: str,
    department_filter_key: str,
) -> None:
    """The built-in department scope must use the connector's exact filter key."""
    job_id = _enable_job(db, job_key, credential_ref=f"alias_{job_key}")
    # Exercise the runner fallback independently of the persisted seed value.
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET filters_json = '{}' WHERE id = ?",
            (job_id,),
        )
    connector = FakeConnector()
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={f"alias_{job_key}": ("user", "password")},
        connectors={job_key: connector},
    )

    result = runner.run_job(job_id)

    assert result.outcome == "completed"
    assert connector.last_context is not None
    assert connector.last_context.filters == {
        department_filter_key: DEFAULT_BUSINESS_DEPARTMENT,
    }


def test_successful_form_collection_publishes_snapshot_without_persisting_credential(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_paa", credential_ref="alias_snapshot")
    connector = SnapshotConnector()
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={"alias_snapshot": ("snapshot-user", "snapshot-password")},
        connectors={"aras_paa": connector},
    )

    result = runner.run_job(job_id)

    assert result.outcome == "completed"
    snapshot = db.get_latest_deliverable_form_snapshot("aras_paa")
    assert snapshot is not None
    assert snapshot["source_run_id"] == result.run_id
    rows = db.list_deliverable_form_rows("aras_paa")
    assert rows["total"] == 1
    serialized = str(snapshot) + str(rows)
    assert "snapshot-password" not in serialized
    assert "snapshot-user" not in serialized


def test_form_projection_failure_marks_archive_run_needs_attention_and_keeps_artifacts(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_paa", credential_ref="alias_projection_failure")
    connector = SnapshotConnector()
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={"alias_projection_failure": ("projection-user", "projection-password")},
        connectors={"aras_paa": connector},
    )

    with patch.object(
        runner,
        "_publish_form_snapshot",
        side_effect=ValueError("malformed projection payload"),
    ):
        result = runner.run_job(job_id)

    assert result.outcome == "needs_attention"
    assert result.final_state == "needs_attention"
    assert result.error_type == "form_projection_failed"
    run_row = _get_run_row(db, result.run_id)
    assert run_row["run_state"] == "needs_attention"
    assert run_row["record_count"] == 10
    assert _get_artifact_rows(db, result.run_id)
    assert _get_job_row(db, job_id)["sync_state"] == "needs_attention"
    assert db.get_latest_deliverable_form_snapshot("aras_paa") is None


def test_successful_tdc_collection_publishes_data_model_snapshot(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    """tdc_data_model 任务的归档行必须发布为同名表单快照。"""
    job_id = _enable_job(db, "tdc_data_model", credential_ref="alias_tdc_model")
    connector = TdcSnapshotConnector(record_count=2)
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={"alias_tdc_model": ("tdc-user", "tdc-password")},
        connectors={"tdc_data_model": connector},
    )

    result = runner.run_job(job_id)

    assert result.outcome == "completed"
    snapshot = db.get_latest_deliverable_form_snapshot("tdc_data_model")
    assert snapshot is not None
    assert snapshot["form_key"] == "tdc_data_model"
    assert snapshot["report_type"] == "tdc_data_model"
    assert snapshot["row_count"] == 2
    assert snapshot["source_run_id"] == result.run_id
    rows = db.list_deliverable_form_rows("tdc_data_model")
    assert rows["total"] == 2
    serialized = str(snapshot) + str(rows)
    assert "tdc-password" not in serialized
    assert "tdc-user" not in serialized


def test_runner_passes_task_output_directory_to_connector(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
    tmp_path: Path,
) -> None:
    """The selected task directory is carried through the lease into connector context."""
    selected = tmp_path / "task-output"
    selected.mkdir()
    job_id = _enable_job(
        db,
        "aras_ewo",
        credential_ref="alias_task_output",
        output_directory=str(selected),
    )
    connector = FakeConnector()
    registry.register("aras_ewo", connector)
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={"alias_task_output": ("user", "password")},
    )

    result = runner.run_job(job_id)

    assert result.outcome == "completed"
    assert connector.last_context is not None
    assert Path(connector.last_context.output_directory).resolve() == selected.resolve()


# ── 3. Needs attention (missing connector or alias) ──────────────────────────


@pytest.mark.parametrize(
    ("job_key", "cred_ref", "creds", "register_conn", "expected_err"),
    [
        ("aras_paa", "alias_paa", {"alias_paa": ("user", "pass")}, False, "connector_unavailable"),
        ("tdc_sor", "unregistered_alias", {}, True, "credential_unavailable"),
    ],
)
def test_run_job_needs_attention_scenarios(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
    job_key: str,
    cred_ref: str,
    creds: dict[str, tuple[str, str]],
    register_conn: bool,
    expected_err: str,
) -> None:
    job_id = _enable_job(db, job_key, credential_ref=cred_ref)
    conn = FakeConnector() if register_conn else None
    runner, _ = _setup_runner(
        db, registry,
        credentials=creds,
        connectors={job_key: conn} if conn else None,
    )
    result = runner.run_job(job_id)

    assert result.outcome == "needs_attention" and result.final_state == "needs_attention"
    assert result.error_type == expected_err and result.run_id is not None
    if conn:
        assert conn.call_count == 0

    run_row = _get_run_row(db, result.run_id)
    assert run_row["run_state"] == "needs_attention" and run_row["error_type"] == expected_err

    job_row = _get_job_row(db, job_id)
    assert job_row["sync_state"] == "needs_attention" and job_row["lease_token"] is None


def test_scheduled_paa_missing_credential_creates_auditable_run(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_paa", credential_ref="")
    connector = FakeConnector()
    runner, _ = _setup_runner(
        db,
        registry,
        connectors={"aras_paa": connector},
    )

    result = runner.run_once(trigger_type="scheduled", job_key="aras_paa")

    assert result.results[0].run_id is not None
    assert result.results[0].outcome == "needs_attention"
    assert result.results[0].error_type == "credential_unavailable"
    assert connector.call_count == 0
    run = _get_run_row(db, result.results[0].run_id)
    assert run["run_state"] == "needs_attention"
    assert run["error_type"] == "credential_unavailable"
    assert _get_job_row(db, job_id)["lease_token"] is None


def test_manual_archive_missing_credential_keeps_prelease_not_ready(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_paa", credential_ref="")
    runner, _ = _setup_runner(db, registry, connectors={"aras_paa": FakeConnector()})

    result = runner.run_job(job_id, trigger_type="sync_now")

    assert result.outcome == "not_ready"
    assert result.error_type == "job_not_ready"
    with db.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM scheduled_archive_runs WHERE job_id=?",
            (job_id,),
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("failure", "error_type", "outcome"),
    [
        (
            CredentialProviderError("missing credential password=secret"),
            "credential_unavailable",
            "needs_attention",
        ),
        (ArasAuthError("rejected password=secret"), "credential_invalid", "needs_attention"),
        (TDCAuthError("rejected password=secret"), "credential_invalid", "needs_attention"),
        (
            ArasAuthenticationError("login page token=secret"),
            "authentication_error",
            "needs_attention",
        ),
        (WinHTTPError("transport Cookie=secret"), "service_unavailable", "failed"),
        (WinHTTPTimeoutError("timeout token=secret"), "timeout", "failed"),
        (ArasCrawlerError("invalid XML Authorization=secret"), "query_failed", "failed"),
    ],
)
def test_archive_connector_failure_is_audited_without_secret(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
    failure: BaseException,
    error_type: str,
    outcome: str,
) -> None:
    job_id = _enable_job(db, "aras_paa", credential_ref="alias_paa")
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={"alias_paa": ("user", "pass")},
        connectors={"aras_paa": FakeConnector(exception=failure)},
    )

    result = runner.run_job(job_id)

    assert result.outcome == outcome
    assert result.error_type == error_type
    assert result.run_id is not None
    assert "secret" not in str(result)
    run = _get_run_row(db, result.run_id)
    assert run["run_state"] == outcome
    assert run["error_type"] == error_type
    assert "secret" not in str(dict(run))


# ── 4. Retry behavior (transient vs non-transient) ──────────────────────────


def test_transient_error_retries_and_recovers_with_backoff(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_retry")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET retry_policy_json = ? WHERE id = ?",
            ('{"max_attempts":2,"backoff_seconds":2}', job_id),
        )
    connector = FakeConnector(exceptions=[TimeoutError("first attempt timed out")])
    slept: list[float] = []
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_retry": ("u", "p")},
        connectors={"aras_ewo": connector},
        max_attempts=2,
        backoff_seconds=2.0,
        sleeper=slept.append,
    )
    result = runner.run_job(job_id)

    assert result.outcome == "completed" and result.final_state == "success"
    assert connector.call_count == 2 and slept == [2.0]


def test_transient_error_exhausts_retries_and_fails(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_retry")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET retry_policy_json = ? WHERE id = ?",
            ('{"max_attempts":2,"backoff_seconds":1.5}', job_id),
        )
    connector = FakeConnector(exceptions=[ConnectionError("first failed"), ConnectionError("second failed")])
    slept: list[float] = []
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_retry": ("u", "p")},
        connectors={"aras_ewo": connector},
        max_attempts=2,
        backoff_seconds=1.5,
        sleeper=slept.append,
    )
    result = runner.run_job(job_id)

    assert result.outcome == "failed" and result.final_state == "failed"
    assert result.error_type == "connection_error"
    assert connector.call_count == 2 and slept == [1.5]

    run_row = _get_run_row(db, result.run_id)
    assert run_row["run_state"] == "failed" and run_row["error_type"] == "connection_error"


def test_job_retry_policy_can_disable_transient_retry(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    """A task configured for one total attempt must not inherit the runner's two-attempt default."""
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_no_retry")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET retry_policy_json = ? WHERE id = ?",
            ('{"max_attempts":1,"backoff_seconds":1}', job_id),
        )
    connector = FakeConnector(exception=TimeoutError("single attempt timeout"))
    slept: list[float] = []
    runner, _ = _setup_runner(
        db,
        registry,
        credentials={"alias_no_retry": ("u", "p")},
        connectors={"aras_ewo": connector},
        max_attempts=2,
        sleeper=slept.append,
    )

    result = runner.run_job(job_id)
    assert result.outcome == "failed"
    assert connector.call_count == 1
    assert slept == []


def test_non_transient_validation_error_fails_immediately_without_retry(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "tdc_data_model", credential_ref="alias_model")
    connector = FakeConnector(exception=ValueError("malformed records response"))
    slept: list[float] = []
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_model": ("u", "p")},
        connectors={"tdc_data_model": connector},
        max_attempts=2,
        backoff_seconds=1.0,
        sleeper=slept.append,
    )
    result = runner.run_job(job_id)

    assert result.outcome == "failed" and result.final_state == "failed"
    assert result.error_type == "invalid_data"
    assert connector.call_count == 1 and slept == []


# ── 5. Sensitive sentinel leakage protection ────────────────────────────────


def test_dynamically_generated_sentinel_never_leaks_in_result_or_db(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    sentinel = f"SENTINEL_{secrets.token_hex(16)}"
    job_id = _enable_job(db, "aras_ncr_progress", credential_ref="alias_ncr")
    connector = FakeConnector(exception=RuntimeError(f"Remote backend failed with auth token={sentinel}"))
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_ncr": ("u", "p")},
        connectors={"aras_ncr_progress": connector},
    )
    result = runner.run_job(job_id)

    assert result.outcome == "failed" and result.final_state == "failed"
    assert result.error_type == "connector_error"
    assert result.error_message == "archive connector failed"
    assert sentinel not in str(result) and sentinel not in repr(result) and sentinel not in (result.error_message or "")

    run_row = _get_run_row(db, result.run_id)
    assert run_row["run_state"] == "failed" and run_row["error_type"] == "connector_error"
    assert run_row["error_message"] == "archive connector failed"
    assert run_row["result_summary"] == "archive connector failed"
    assert sentinel not in str(run_row["error_message"] or "") and sentinel not in str(run_row["result_summary"] or "")

    job_row = _get_job_row(db, job_id)
    assert job_row["sync_state"] == "failed" and job_row["last_error_type"] == "connector_error"
    assert job_row["last_error_message"] == "archive connector failed"
    assert sentinel not in str(job_row["last_error_message"] or "")


# ── 6. Disabled job, lease conflict & last_success preservation ─────────────


def test_disabled_job_skipped_before_lease(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    with db.get_connection() as conn:
        row = conn.execute("SELECT id FROM scheduled_archive_jobs WHERE job_key = 'aras_ewo'").fetchone()
    job_id = int(row["id"])

    runner, _ = _setup_runner(db, registry)
    result = runner.run_job(job_id)

    assert result.outcome == "not_ready" and result.error_type == "job_not_ready"
    with db.get_connection() as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM scheduled_archive_runs WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert run_count == 0


def test_active_lease_conflict_returns_skipped(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_busy")
    connector = FakeConnector()
    db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=600)

    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_busy": ("u", "p")},
        connectors={"aras_ewo": connector},
    )
    result = runner.run_job(job_id)

    assert result.outcome == "skipped" and result.error_type == "lease_busy"
    assert connector.call_count == 0


def test_prior_last_success_preserved_on_failure(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_fail")
    connector = FakeConnector(exception=RuntimeError("something went wrong"))
    prior_success = "2026-08-01T12:00:00.000Z"
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET last_success_at = ?, sync_state = 'success' WHERE id = ?",
            (prior_success, job_id),
        )

    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_fail": ("u", "p")},
        connectors={"aras_ewo": connector},
    )
    result = runner.run_job(job_id)

    assert result.outcome == "failed"
    job_row = _get_job_row(db, job_id)
    assert job_row["last_success_at"] == prior_success and job_row["sync_state"] == "failed"
    assert job_row["last_attempt_at"] is not None and job_row["last_attempt_at"] != prior_success


# ── 7. run_once scheduling, selector, dry-run & exit codes ──────────────────


def test_run_once_due_selection_and_timestamp_handling(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_1 = _enable_job(db, "aras_ewo", credential_ref="alias_1", interval_minutes=60)
    job_2 = _enable_job(db, "tdc_sor", credential_ref="alias_2", interval_minutes=60)
    job_3 = _enable_job(db, "aras_paa", credential_ref="alias_3", interval_minutes=60)
    job_4 = _enable_job(db, "tdc_data_model", credential_ref="alias_4", interval_minutes=60)

    fixed_now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
    with db.get_connection() as conn:
        conn.execute("UPDATE scheduled_archive_jobs SET last_attempt_at = '2026-08-22T11:40:00.000Z' WHERE id = ?", (job_1,))
        conn.execute("UPDATE scheduled_archive_jobs SET last_attempt_at = '2026-08-22T10:30:00.000Z' WHERE id = ?", (job_2,))
        conn.execute("UPDATE scheduled_archive_jobs SET last_attempt_at = NULL WHERE id = ?", (job_3,))
        conn.execute("UPDATE scheduled_archive_jobs SET last_attempt_at = 'invalid-timestamp' WHERE id = ?", (job_4,))

    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_1": ("u", "p"), "alias_2": ("u", "p"), "alias_3": ("u", "p"), "alias_4": ("u", "p")},
        connectors={k: FakeConnector() for k in ["aras_ewo", "tdc_sor", "aras_paa", "tdc_data_model"]},
        clock=lambda: fixed_now,
    )
    result = runner.run_once(trigger_type="scheduled")

    by_key = {r.job_key: r for r in result.results}
    assert by_key["aras_ewo"].outcome == "not_due"
    assert by_key["tdc_sor"].outcome == "completed"
    assert by_key["aras_paa"].outcome == "completed"
    assert by_key["tdc_data_model"].outcome == "completed"


def test_run_once_job_key_exact_filtering(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    _enable_job(db, "aras_ewo", credential_ref="alias_ewo")
    _enable_job(db, "tdc_sor", credential_ref="alias_sor")
    conn_ewo, conn_sor = FakeConnector(), FakeConnector()
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_ewo": ("u", "p"), "alias_sor": ("u", "p")},
        connectors={"aras_ewo": conn_ewo, "tdc_sor": conn_sor},
    )

    res = runner.run_once(trigger_type="sync_now", job_key="aras_ewo")
    assert len(res.results) == 1
    assert res.results[0].job_key == "aras_ewo" and res.results[0].outcome == "completed"
    assert conn_ewo.call_count == 1 and conn_sor.call_count == 0

    res_unknown = runner.run_once(trigger_type="sync_now", job_key="unknown_job_key")
    assert len(res_unknown.results) == 1
    assert res_unknown.results[0].job_key == "unknown_job_key" and res_unknown.results[0].outcome == "not_ready"
    assert res_unknown.results[0].error_type == "missing_job" and res_unknown.exit_code == EXIT_ATTENTION


def test_run_once_dry_run_zero_side_effects(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    _enable_job(db, "aras_ewo", credential_ref="alias_ready")
    with db.get_connection() as conn:
        conn.execute("UPDATE scheduled_archive_jobs SET enabled = 1, credential_ref = '' WHERE job_key = 'tdc_sor'")

    connector = FakeConnector()
    registry.register("aras_ewo", connector)
    slept: list[float] = []
    provider = CountingCredentialProvider({"alias_ready": ("u", "p")})
    runner = ArchiveSyncRunner(db=db, credentials=provider, registry=registry, sleeper=slept.append)
    res = runner.run_once(trigger_type="sync_now", dry_run=True)

    assert res.dry_run is True
    by_key = {r.job_key: r for r in res.results}
    assert by_key["aras_ewo"].outcome == "ready" and by_key["aras_ewo"].error_type is None
    assert by_key["tdc_sor"].outcome == "not_ready" and by_key["tdc_sor"].error_type == "job_not_ready"

    assert connector.call_count == 0 and provider.resolve_call_count == 0 and len(slept) == 0

    with db.get_connection() as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM scheduled_archive_runs").fetchone()[0]
        assert run_count == 0
        jobs = conn.execute("SELECT lease_token, last_attempt_at FROM scheduled_archive_jobs").fetchall()
        for j in jobs:
            assert j["lease_token"] is None and j["last_attempt_at"] is None


def test_run_once_trigger_type_validation_and_exit_code_logic(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    runner, _ = _setup_runner(db, registry)
    with pytest.raises(ValueError, match="unsupported archive trigger_type"):
        runner.run_once(trigger_type="invalid_trigger")

    assert ArchiveRunOnceResult((ArchiveJobRunResult(1, "aras_ewo", "completed"),)).exit_code == EXIT_OK
    assert ArchiveRunOnceResult((ArchiveJobRunResult(1, "aras_ewo", "completed"), ArchiveJobRunResult(2, "tdc_sor", "failed"))).exit_code == EXIT_FAILED
    assert ArchiveRunOnceResult((ArchiveJobRunResult(1, "aras_ewo", "needs_attention"), ArchiveJobRunResult(2, "tdc_sor", "completed"))).exit_code == EXIT_ATTENTION
    assert ArchiveRunOnceResult((ArchiveJobRunResult(1, "aras_ewo", "not_ready"),)).exit_code == EXIT_ATTENTION


# ── 8. KeyboardInterrupt handling ───────────────────────────────────────────


def test_keyboard_interrupt_best_effort_finalization_and_reraise(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_interrupt")
    connector = FakeConnector(exception=KeyboardInterrupt("Simulated Ctrl-C"))
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_interrupt": ("u", "p")},
        connectors={"aras_ewo": connector},
    )

    with pytest.raises(KeyboardInterrupt):
        runner.run_job(job_id)

    with db.get_connection() as conn:
        run_row = conn.execute(
            "SELECT * FROM scheduled_archive_runs WHERE job_id = ? ORDER BY id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        assert run_row is not None
        assert run_row["run_state"] == "failed" and run_row["error_type"] == "interrupted"
        assert run_row["finished_at"] is not None

    job_row = _get_job_row(db, job_id)
    assert job_row["lease_token"] is None


def test_keyboard_interrupt_when_finalize_raises_still_reraises_keyboard_interrupt(
    db: DatabaseManager,
    registry: ArchiveConnectorRegistry,
) -> None:
    job_id = _enable_job(db, "aras_ewo", credential_ref="alias_interrupt_fail")
    connector = FakeConnector(exception=KeyboardInterrupt("Simulated Ctrl-C during collect"))
    runner, _ = _setup_runner(
        db, registry,
        credentials={"alias_interrupt_fail": ("u", "p")},
        connectors={"aras_ewo": connector},
    )

    with patch.object(db, "finalize_archive_run", side_effect=RuntimeError("DB finalize write crash")):
        with pytest.raises(KeyboardInterrupt):
            runner.run_job(job_id)
