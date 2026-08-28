"""Unified domain identity status and Windows DPAPI credential storage."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
            try:
                yield value
            finally:
                value.clear()
        except CredentialVaultError:
            raise
        except Exception as exc:
            raise CredentialVaultError("could not unprotect domain credentials") from exc
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


class DomainSessionRegistry:
    def __init__(self, ttl: timedelta = timedelta(hours=8)) -> None:
        self._ttl = ttl
        self._records: dict[str, _SessionRecord] = {}
        self._sessions: dict[str, Any] = {}

    def mark_authenticated(self, system: str, session: Any | None = None) -> None:
        now = datetime.now(timezone.utc)
        self._records[system] = _SessionRecord(now, now + self._ttl)
        if isinstance(session, str) and session in {"aras", "tdc"}:
            self._records[session] = _SessionRecord(now, now + self._ttl)
            return
        if session is not None:
            self._sessions[system] = session

    def session(self, system: str) -> Any | None:
        record = self._records.get(system)
        if record is None or record.expires_at <= datetime.now(timezone.utc):
            self._sessions.pop(system, None)
            return None
        return self._sessions.get(system)

    def clear(self, system: str | None = None) -> None:
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
