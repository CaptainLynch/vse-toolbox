"""Contract tests for the unified EWO/PAA/NCR object status model."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from core.unified_status import (
    AuthState,
    QueryState,
    SyncState,
    UnifiedObjectStatus,
    classify_sync_outcome,
)


@pytest.mark.parametrize("kind", ["ewo", "paa", "ncr"])
def test_unified_object_status_supports_each_object_kind(kind: str) -> None:
    status = UnifiedObjectStatus(
        kind=kind,
        id="internal-1",
        source="connector",
        external_key="external-1",
        auth_state=AuthState.AUTHENTICATED,
        query_state=QueryState.MATCHED,
        sync_state=SyncState.SUCCESS,
        stage="detail",
        matched_fields=("name", "owner"),
        errors=(),
        last_updated=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    assert status.kind == kind
    assert status.auth_state is AuthState.AUTHENTICATED
    assert status.query_state is QueryState.MATCHED
    assert status.sync_state is SyncState.SUCCESS


def test_status_rejects_invalid_kind_and_state_values() -> None:
    fields = dict(
        id="internal-1",
        source="connector",
        external_key="external-1",
        auth_state="authenticated",
        query_state="matched",
        sync_state="success",
        stage="detail",
        matched_fields=(),
        errors=(),
        last_updated="2026-08-31T00:00:00+00:00",
    )

    with pytest.raises(ValueError):
        UnifiedObjectStatus(kind="other", **fields)
    with pytest.raises(ValueError):
        UnifiedObjectStatus(kind="ewo", **{**fields, "auth_state": "authorized"})
    with pytest.raises(ValueError):
        UnifiedObjectStatus(kind="paa", **{**fields, "query_state": "unknown_query"})
    with pytest.raises(ValueError):
        UnifiedObjectStatus(kind="ncr", **{**fields, "sync_state": "unknown_sync"})


def test_status_is_immutable() -> None:
    status = UnifiedObjectStatus(
        kind="ewo",
        id="internal-1",
        source="connector",
        external_key="external-1",
        auth_state="authenticated",
        query_state="matched",
        sync_state="success",
        stage="detail",
        matched_fields=["name"],
        errors=[],
        last_updated="2026-08-31T00:00:00+00:00",
    )

    with pytest.raises(FrozenInstanceError):
        status.sync_state = SyncState.FAILED  # type: ignore[misc]

    assert isinstance(status.matched_fields, tuple)
    assert isinstance(status.errors, tuple)


def test_to_dict_serializes_contract_fields_without_secret_fields() -> None:
    status = UnifiedObjectStatus(
        kind="ncr",
        id="internal-1",
        source="connector",
        external_key="external-1",
        auth_state=AuthState.CREDENTIAL_MISSING,
        query_state=QueryState.SERVICE_UNAVAILABLE,
        sync_state=SyncState.NEEDS_ATTENTION,
        stage="lookup",
        matched_fields=("name",),
        errors=("credential required",),
        last_updated=datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc),
    )

    serialized = status.to_dict()

    assert serialized == {
        "kind": "ncr",
        "id": "internal-1",
        "source": "connector",
        "external_key": "external-1",
        "auth_state": "credential_missing",
        "query_state": "service_unavailable",
        "sync_state": "needs_attention",
        "stage": "lookup",
        "matched_fields": ["name"],
        "errors": ["credential required"],
        "last_updated": "2026-08-31T12:30:00+00:00",
        "content": {},
    }
    assert not any("secret" in key.lower() or "token" in key.lower() for key in serialized)


def test_errors_are_redacted_at_unified_status_boundary() -> None:
    status = UnifiedObjectStatus(
        kind="ewo", id="x", source="aras", external_key="",
        auth_state="credential_invalid", query_state="failed", sync_state="failed",
        stage=None, matched_fields=(),
        errors=("credential_ref=VAULT_ALIAS", "-----BEGIN PRIVATE KEY-----ABC-----END PRIVATE KEY-----"),
        last_updated=None,
    )
    errors = status.to_dict()["errors"]
    assert "VAULT_ALIAS" not in errors[0]
    assert "PRIVATE KEY-----ABC" not in errors[1]


@pytest.mark.parametrize(
    ("applied", "skipped", "error_type", "expected"),
    [
        ([], [], None, "success"),
        (["name"], [], None, "success"),
        (["name"], ["owner"], None, "partial_success"),
        ([], ["owner"], None, "needs_attention"),
        ([], [], "connector_error", "failed"),
        (["name"], ["owner"], "connector_error", "failed"),
    ],
)
def test_classify_sync_outcome_boundaries(
    applied: list[str],
    skipped: list[str],
    error_type: str | None,
    expected: str,
) -> None:
    assert classify_sync_outcome(applied, skipped, error_type) == expected
