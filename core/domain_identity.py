"""Unified domain identity status and Windows DPAPI credential storage."""

from __future__ import annotations

from core.diagnostic_recording import observed

import json
import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from threading import RLock
from urllib.parse import urlsplit

from core.credential_provider import CredentialProviderError, ResolvedCredential


class CredentialVaultError(RuntimeError):
    pass


def _dpapi_blob(result: object) -> bytes:
    """Normalize pywin32's bytes result and tuple-shaped test backends."""
    value = result[1] if isinstance(result, tuple) and len(result) > 1 else result
    if not isinstance(value, (bytes, bytearray)):
        raise TypeError("DPAPI returned a non-binary blob")
    return bytes(value)


class WindowsDPAPICredentialVault:
    def __init__(self, path: Path, backend: Any | None = None) -> None:
        self._path = path
        self._backend = backend

    def _api(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            import win32crypt  # type: ignore[import-not-found]
        except (ImportError, OSError) as exc:
            raise CredentialVaultError("Windows DPAPI is unavailable") from exc
        return win32crypt

    @observed("identity.WindowsDPAPICredentialVault.store")
    def store(self, username: str, password: str) -> None:
        user = str(username or "").strip()
        secret = str(password or "")
        if not user or not secret:
            raise CredentialVaultError("domain credentials are incomplete")
        clear = json.dumps({"username": user, "password": secret}, ensure_ascii=False).encode("utf-8")
        try:
            protected = _dpapi_blob(
                self._api().CryptProtectData(
                    clear, "VSE Toolbox domain credential", None, None, None, 0
                )
            )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            temporary.write_bytes(protected)
            os.replace(temporary, self._path)
        except Exception as exc:
            raise CredentialVaultError("could not protect domain credentials") from exc
        finally:
            clear = b""
            secret = ""

    @observed("identity.WindowsDPAPICredentialVault.clear")
    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialVaultError("could not clear domain credentials") from exc

    def is_configured(self) -> bool:
        return self._path.is_file() and self._path.stat().st_size > 0

    @contextmanager
    def resolve(self) -> Any:
        if not self.is_configured():
            raise CredentialVaultError("domain credential vault is not configured")
        clear = b""
        password = ""
        try:
            try:
                protected = self._path.read_bytes()
                clear = _dpapi_blob(
                    self._api().CryptUnprotectData(protected, None, None, None, 0)
                )
                payload = json.loads(clear.decode("utf-8"))
                username = str(payload.get("username") or "").strip()
                password = str(payload.get("password") or "")
                if not username or not password:
                    raise CredentialVaultError("domain credential vault is incomplete")
                value = ResolvedCredential(username=username, password=password)
            except CredentialVaultError:
                raise
            except Exception as exc:
                raise CredentialVaultError("could not unprotect domain credentials") from exc
            try:
                yield value
            finally:
                value.clear()
        except CredentialVaultError:
            raise
        finally:
            clear = b""
            password = ""


class DPAPICredentialProvider:
    """CredentialProvider adapter backed by the single approved domain vault."""

    def __init__(self, vault: WindowsDPAPICredentialVault) -> None:
        self._vault = vault

    @contextmanager
    def resolve(self, credential_ref: str) -> Any:
        if str(credential_ref or "").strip() not in {"domain", "unified-domain"}:
            raise CredentialProviderError("credential reference is unavailable")
        try:
            with self._vault.resolve() as value:
                yield value
        except CredentialVaultError as exc:
            raise CredentialProviderError("credential reference is unavailable") from exc

    def is_available(self, credential_ref: str) -> bool:
        return str(credential_ref or "").strip() in {"domain", "unified-domain"} and self._vault.is_configured()


@dataclass
class _SessionRecord:
    updated_at: datetime
    expires_at: datetime
    source_root: str | None = None
    scope: str | None = None


def _identity_source_root(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Invalid identity source')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Invalid identity source')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return json.dumps([parsed.scheme, parsed.hostname.lower(), port, parsed.path.rstrip('/')])


class DomainSessionRegistry:
    def __init__(self, ttl: timedelta = timedelta(hours=8)) -> None:
        self._ttl = ttl
        self._records: dict[str, _SessionRecord] = {}
        self._sessions: dict[str, Any] = {}
        self._lock = RLock()

    @observed("identity.DomainSessionRegistry.mark_authenticated")
    def mark_authenticated(self, system: str, session: Any | None = None, *,
                           principal: str | None = None, source_root: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        source = scope = None
        if principal is not None or source_root is not None:
            if not isinstance(principal, str) or not principal.strip() or session is None:
                raise ValueError('Incomplete identity binding')
            source = _identity_source_root(source_root)
            # Conservative exact principal: aliases produce separate scopes, never guessed equivalence.
            scope = hashlib.sha256(json.dumps(
                [system, source, principal.strip()], ensure_ascii=True
            ).encode('utf-8')).hexdigest()
        with self._lock:
            self._records[system] = _SessionRecord(now, now + self._ttl, source, scope)
            self._sessions.pop(system, None)
            if isinstance(session, str) and session in {"aras", "tdc"}:
                self._records[session] = _SessionRecord(now, now + self._ttl)
                self._sessions.pop(session, None)
                return
            if session is not None:
                self._sessions[system] = session

    def bound_session(self, system: str, source_root: str) -> tuple[Any, str] | None:
        source = _identity_source_root(source_root)
        with self._lock:
            record = self._records.get(system)
            session = self.session(system)
            if session is None or record is None or not record.scope or record.source_root != source:
                return None
            return session, record.scope

    @observed("identity.DomainSessionRegistry.session")
    def session(self, system: str) -> Any | None:
        with self._lock:
            record = self._records.get(system)
            if record is None or record.expires_at <= datetime.now(timezone.utc):
                self._sessions.pop(system, None)
                return None
            return self._sessions.get(system)

    @observed("identity.DomainSessionRegistry.clear")
    def clear(self, system: str | None = None) -> None:
        with self._lock:
            if system is None:
                self._records.clear()
                self._sessions.clear()
            else:
                self._records.pop(system, None)
                self._sessions.pop(system, None)

    def payload(self) -> dict[str, dict[str, object]]:
        now = datetime.now(timezone.utc)
        result: dict[str, dict[str, object]] = {}
        for system in ("aras", "tdc"):
            record = self._records.get(system)
            expired = record is not None and record.expires_at <= now
            result[system] = {
                "authenticated": bool(record and not expired),
                "updatedAt": record.updated_at.isoformat().replace("+00:00", "Z") if record else None,
                "expiresAt": record.expires_at.isoformat().replace("+00:00", "Z") if record else None,
                "expired": bool(expired),
            }
        return result
