"""Shared status contracts for EWO, PAA, and NCR objects.

This module intentionally contains only the small, serializable status model.
Connector credentials and other sensitive connector state are not part of the
model or its serialized representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, cast

from core.redaction import redact_sensitive_text


class _StatusEnum(str, Enum):
    """String-valued enum base so values remain convenient at boundaries."""

    def __str__(self) -> str:
        return cast(str, self.value)


class AuthState(_StatusEnum):
    UNAUTHENTICATED = "unauthenticated"
    CREDENTIAL_MISSING = "credential_missing"
    CREDENTIAL_INVALID = "credential_invalid"
    AUTHENTICATED = "authenticated"
    UNKNOWN = "unknown"

    # Lowercase aliases make the enum pleasant to use alongside wire values.
    unauthenticated = UNAUTHENTICATED
    credential_missing = CREDENTIAL_MISSING
    credential_invalid = CREDENTIAL_INVALID
    authenticated = AUTHENTICATED
    unknown = UNKNOWN


class QueryState(_StatusEnum):
    IDLE = "idle"
    QUERYING = "querying"
    SERVICE_UNAVAILABLE = "service_unavailable"
    FAILED = "failed"
    NO_MATCH = "no_match"
    MATCHED = "matched"

    idle = IDLE
    querying = QUERYING
    service_unavailable = SERVICE_UNAVAILABLE
    failed = FAILED
    no_match = NO_MATCH
    matched = MATCHED


class SyncState(_StatusEnum):
    IDLE = "idle"
    MANUAL = "manual"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"

    manual = MANUAL
    ready = READY
    running = RUNNING
    success = SUCCESS
    partial_success = PARTIAL_SUCCESS
    needs_attention = NEEDS_ATTENTION
    failed = FAILED
    idle = IDLE


# Readable aliases for callers that use "status" terminology.
AuthStatus = AuthState
QueryStatus = QueryState
SyncStatus = SyncState

_VALID_KINDS = frozenset({"ewo", "paa", "ncr"})


def _coerce_status(value: object, enum_type: type[_StatusEnum], field_name: str) -> _StatusEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"invalid {field_name!s}: {value!r}; expected one of {allowed}") from exc


def _freeze_texts(value: Iterable[object] | None, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be an iterable of strings")
    try:
        frozen = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be an iterable of strings") from exc
    if not all(isinstance(item, str) for item in frozen):
        raise ValueError(f"{field_name} must contain only strings")
    return frozen  # type: ignore[return-value]


def _serialize_timestamp(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@dataclass(frozen=True)
class UnifiedObjectStatus:
    """Immutable status snapshot shared by all three external object kinds."""

    kind: str
    id: str
    source: str
    external_key: str
    auth_state: AuthState | str
    query_state: QueryState | str
    sync_state: SyncState | str
    stage: str | None
    matched_fields: tuple[str, ...]
    errors: tuple[str, ...]
    last_updated: object
    content: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _VALID_KINDS:
            raise ValueError(f"invalid kind: {self.kind!r}; expected one of ewo, paa, ncr")
        object.__setattr__(self, "auth_state", _coerce_status(self.auth_state, AuthState, "auth_state"))
        object.__setattr__(self, "query_state", _coerce_status(self.query_state, QueryState, "query_state"))
        object.__setattr__(self, "sync_state", _coerce_status(self.sync_state, SyncState, "sync_state"))
        object.__setattr__(self, "matched_fields", _freeze_texts(self.matched_fields, "matched_fields"))
        safe_errors = tuple(
            redact_sensitive_text(item, limit=300, collapse_newlines=True)
            for item in _freeze_texts(self.errors, "errors")
        )
        object.__setattr__(self, "errors", safe_errors)
        if not isinstance(self.content, dict):
            raise ValueError("content must be a mapping")
        object.__setattr__(self, "content", dict(self.content))

    def to_dict(self) -> dict[str, Any]:
        """Return only the public, snake_case status fields.

        The returned lists are fresh copies, so callers cannot mutate this
        immutable snapshot through the serialized value.
        """

        return {
            "kind": self.kind,
            "id": self.id,
            "source": self.source,
            "external_key": self.external_key,
            "auth_state": str(self.auth_state),
            "query_state": str(self.query_state),
            "sync_state": str(self.sync_state),
            "stage": self.stage,
            "matched_fields": list(self.matched_fields),
            "errors": list(self.errors),
            "last_updated": _serialize_timestamp(self.last_updated),
            "content": dict(self.content),
        }


def classify_sync_outcome(
    applied_fields: Iterable[object] | None,
    skipped_fields: Iterable[object] | None,
    error_type: str | None = None,
) -> str:
    """Classify field application into one of the terminal sync states."""

    if error_type is not None:
        return SyncState.FAILED.value
    has_applied = bool(applied_fields)
    has_skipped = bool(skipped_fields)
    if has_applied and has_skipped:
        return SyncState.PARTIAL_SUCCESS.value
    if has_skipped:
        return SyncState.NEEDS_ATTENTION.value
    return SyncState.SUCCESS.value


__all__ = [
    "AuthState",
    "AuthStatus",
    "QueryState",
    "QueryStatus",
    "SyncState",
    "SyncStatus",
    "UnifiedObjectStatus",
    "classify_sync_outcome",
]
