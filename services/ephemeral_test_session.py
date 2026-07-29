"""RAM-only, single-flight vault for an explicitly enabled local test run."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping


HARD_TTL_SECONDS = 15 * 60
IDLE_TTL_SECONDS = 5 * 60
MAX_OPERATIONS = 4
PLANNED_MODULES = frozenset({"ewo", "paa"})


class EphemeralTestSessionError(RuntimeError):
    """Stable vault error containing no user-provided values."""

    def __init__(self, code: str, *, http_status: int) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


class SecretBuffer:
    """Best-effort overwriteable password storage for the current process only."""

    def __init__(self, value: str) -> None:
        self._data = bytearray(value.encode("utf-8"))

    def reveal(self) -> str:
        return bytes(self._data).decode("utf-8")

    def clear(self) -> None:
        for index in range(len(self._data)):
            self._data[index] = 0
        self._data.clear()

    def __bool__(self) -> bool:
        return bool(self._data)


@dataclass
class _VaultRecord:
    sid_digest: bytes
    csrf_digest: bytes
    created_at: float
    hard_deadline: float
    idle_deadline: float
    seeded: bool = False
    base_url: str = ""
    username: str = ""
    allow_insecure_http: bool = False
    current_module: str = "ewo"
    filters_by_module: dict[str, dict[str, Any]] = field(default_factory=dict)
    password: SecretBuffer | None = field(default=None, repr=False)
    authenticated_session: Any | None = field(default=None, repr=False)
    validated_modules: set[str] = field(default_factory=set)
    completed_modules: set[str] = field(default_factory=set)
    operations_remaining: int = MAX_OPERATIONS
    running: bool = False
    cancel_requested: bool = False


@dataclass(frozen=True)
class EphemeralOperationLease:
    base_url: str
    username: str
    allow_insecure_http: bool
    module: str
    filters: Mapping[str, Any]
    authenticated_session: Any | None = field(default=None, repr=False)
    _record: _VaultRecord = field(default=None, repr=False)  # type: ignore[assignment]

    def reveal_password(self) -> str:
        password = self._record.password
        return password.reveal() if password is not None else ""

    @property
    def cancel_requested(self) -> bool:
        return self._record.cancel_requested


class EphemeralTestSessionVault:
    """Own exactly one local test session and destroy it on every terminal path."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._record: _VaultRecord | None = None
        self._closed = False
        self._stop = threading.Event()
        self._sweeper = threading.Thread(
            target=self._sweep,
            name="vse-ephemeral-session-sweeper",
            daemon=True,
        )
        self._sweeper.start()

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("ascii", errors="strict")).digest()

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)

    def _sweep(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                self._expire_locked(time.monotonic())

    def _expire_locked(self, now: float) -> None:
        record = self._record
        if record is not None and (
            now >= record.hard_deadline or now >= record.idle_deadline
        ):
            if record.running:
                self._request_cancel_locked(record)
            else:
                self._destroy_locked()

    @staticmethod
    def _request_cancel_locked(record: _VaultRecord) -> None:
        record.cancel_requested = True
        session = record.authenticated_session
        request_cancel = getattr(session, "request_cancel", None)
        if callable(request_cancel):
            try:
                request_cancel()
            except Exception:
                pass

    def _destroy_locked(self) -> None:
        record = self._record
        self._record = None
        if record is None:
            return
        if record.password is not None:
            record.password.clear()
            record.password = None
        session = record.authenticated_session
        record.authenticated_session = None
        if session is not None:
            try:
                session.headers.clear()
            except Exception:
                pass
            try:
                session.cookies.clear()
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass
        record.filters_by_module.clear()
        record.validated_modules.clear()
        record.completed_modules.clear()
        record.username = ""
        record.base_url = ""
        record.running = False
        record.cancel_requested = False

    def _require_locked(self, sid: str, csrf: str, *, touch: bool = True) -> _VaultRecord:
        now = time.monotonic()
        self._expire_locked(now)
        record = self._record
        if record is None:
            raise EphemeralTestSessionError("TEST_SESSION_NOT_FOUND", http_status=404)
        try:
            sid_digest = self._digest(sid)
            csrf_digest = self._digest(csrf)
        except (UnicodeError, ValueError):
            raise EphemeralTestSessionError("TEST_SESSION_NOT_FOUND", http_status=404) from None
        if not hmac.compare_digest(record.sid_digest, sid_digest) or not hmac.compare_digest(
            record.csrf_digest, csrf_digest
        ):
            raise EphemeralTestSessionError("TEST_SESSION_FORBIDDEN", http_status=403)
        if touch:
            record.idle_deadline = min(record.hard_deadline, now + IDLE_TTL_SECONDS)
        return record

    def bootstrap(self) -> tuple[str, str]:
        with self._lock:
            if self._closed:
                raise EphemeralTestSessionError("TEST_SESSION_DISABLED", http_status=404)
            self._destroy_locked()
            sid = self._new_token()
            csrf = self._new_token()
            now = time.monotonic()
            self._record = _VaultRecord(
                sid_digest=self._digest(sid),
                csrf_digest=self._digest(csrf),
                created_at=now,
                hard_deadline=now + IDLE_TTL_SECONDS,
                idle_deadline=now + IDLE_TTL_SECONDS,
            )
            return sid, csrf

    def seed(
        self,
        sid: str,
        csrf: str,
        *,
        base_url: str,
        username: str,
        password: str,
        allow_insecure_http: bool,
        module: str,
        filters: Mapping[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        with self._lock:
            record = self._require_locked(sid, csrf, touch=False)
            if record.seeded:
                raise EphemeralTestSessionError(
                    "TEST_SESSION_ALREADY_SEEDED", http_status=409
                )
            if module not in PLANNED_MODULES:
                raise EphemeralTestSessionError("TEST_SESSION_INVALID", http_status=400)
            new_sid = self._new_token()
            new_csrf = self._new_token()
            now = time.monotonic()
            record.sid_digest = self._digest(new_sid)
            record.csrf_digest = self._digest(new_csrf)
            record.created_at = now
            record.hard_deadline = now + HARD_TTL_SECONDS
            record.idle_deadline = now + IDLE_TTL_SECONDS
            record.seeded = True
            record.base_url = base_url
            record.username = username
            record.allow_insecure_http = allow_insecure_http
            record.current_module = module
            record.filters_by_module = {module: dict(filters)}
            record.password = SecretBuffer(password)
            record.operations_remaining = MAX_OPERATIONS
            record.cancel_requested = False
            return new_sid, new_csrf, self._status_locked(record, now)

    def _status_locked(self, record: _VaultRecord, now: float) -> dict[str, Any]:
        remaining = max(
            0.0,
            min(record.hard_deadline - now, record.idle_deadline - now),
        )
        ttl_bucket = min(HARD_TTL_SECONDS, int((remaining + 29) // 30) * 30)
        return {
            "seeded": record.seeded,
            "base_url": record.base_url if record.seeded else "",
            "username": record.username if record.seeded else "",
            "module": record.current_module if record.seeded else None,
            "filters": dict(record.filters_by_module.get(record.current_module, {})),
            "password_cached": bool(record.password),
            "authenticated": record.authenticated_session is not None,
            "running": record.running,
            "cancel_requested": record.cancel_requested,
            "operations_remaining": record.operations_remaining,
            "ttl_seconds": ttl_bucket,
            "completed_modules": sorted(record.completed_modules),
        }

    def status(self, sid: str, csrf: str) -> dict[str, Any]:
        with self._lock:
            record = self._require_locked(sid, csrf)
            return self._status_locked(record, time.monotonic())

    def begin_operation(
        self,
        sid: str,
        csrf: str,
        *,
        module: str,
        filters: Mapping[str, Any] | None,
    ) -> EphemeralOperationLease:
        with self._lock:
            record = self._require_locked(sid, csrf)
            if not record.seeded:
                raise EphemeralTestSessionError("TEST_SESSION_NOT_SEEDED", http_status=409)
            if module not in PLANNED_MODULES:
                raise EphemeralTestSessionError("TEST_SESSION_INVALID", http_status=400)
            if record.running:
                raise EphemeralTestSessionError("TEST_SESSION_BUSY", http_status=409)
            if record.operations_remaining <= 0:
                self._destroy_locked()
                raise EphemeralTestSessionError("TEST_SESSION_LIMIT_REACHED", http_status=410)
            if filters is not None:
                record.filters_by_module[module] = dict(filters)
            record.current_module = module
            record.running = True
            record.cancel_requested = False
            record.operations_remaining -= 1
            return EphemeralOperationLease(
                base_url=record.base_url,
                username=record.username,
                allow_insecure_http=record.allow_insecure_http,
                module=module,
                filters=dict(record.filters_by_module.get(module, {})),
                authenticated_session=record.authenticated_session,
                _record=record,
            )

    def promote_authenticated(
        self,
        lease: EphemeralOperationLease,
        session: Any,
        *,
        validated_module: str,
    ) -> None:
        with self._lock:
            if self._record is not lease._record or not lease._record.running:
                raise EphemeralTestSessionError("TEST_SESSION_EXPIRED", http_status=410)
            record = lease._record
            record.authenticated_session = session
            record.validated_modules.add(validated_module)
            if record.password is not None:
                record.password.clear()
                record.password = None

    def mark_validated(self, lease: EphemeralOperationLease, module: str) -> None:
        with self._lock:
            if self._record is not lease._record or not lease._record.running:
                raise EphemeralTestSessionError("TEST_SESSION_EXPIRED", http_status=410)
            lease._record.validated_modules.add(module)

    def module_is_validated(self, lease: EphemeralOperationLease, module: str) -> bool:
        with self._lock:
            return self._record is lease._record and module in lease._record.validated_modules

    def finish_success(self, lease: EphemeralOperationLease) -> bool:
        with self._lock:
            if self._record is not lease._record:
                return True
            record = lease._record
            record.running = False
            record.completed_modules.add(lease.module)
            record.idle_deadline = min(
                record.hard_deadline, time.monotonic() + IDLE_TTL_SECONDS
            )
            terminal = (
                record.cancel_requested
                or PLANNED_MODULES.issubset(record.completed_modules)
                or record.operations_remaining <= 0
            )
            if terminal:
                self._destroy_locked()
            return terminal

    def finish_failure(
        self,
        lease: EphemeralOperationLease,
        *,
        preserve_pre_touch_password: bool,
    ) -> bool:
        """Destroy on every Scheme-A failure.

        ``preserve_pre_touch_password`` remains in the signature only for old
        local callers; it is deliberately ignored and must never retain a
        credential for an automatic retry.
        """
        with self._lock:
            if self._record is not lease._record:
                return True
            self._destroy_locked()
            return True

    def clear(self, sid: str, csrf: str) -> None:
        with self._lock:
            record = self._require_locked(sid, csrf, touch=False)
            if record.running:
                self._request_cancel_locked(record)
                return
            self._destroy_locked()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._record is not None and self._record.running:
                self._request_cancel_locked(self._record)
            else:
                self._destroy_locked()
            self._stop.set()
        if self._sweeper is not threading.current_thread():
            self._sweeper.join(timeout=2.0)
