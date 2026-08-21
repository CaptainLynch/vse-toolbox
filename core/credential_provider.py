# -*- coding: utf-8 -*-
"""Short-lived credential lookup for unattended Windows tasks.

Only opaque ``credential_ref`` aliases cross persistence/API boundaries.  The
resolved value exists in process memory only for the duration of the context.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


class CredentialProviderError(RuntimeError):
    """Stable, credential-free provider failure."""


@dataclass
class ResolvedCredential:
    username: str = field(repr=False)
    password: str = field(repr=False)

    def clear(self) -> None:
        self.username = ""
        self.password = ""


class CredentialProvider(Protocol):
    @contextmanager
    def resolve(self, credential_ref: str) -> Iterator[ResolvedCredential]: ...

    def is_available(self, credential_ref: str) -> bool: ...


class WindowsCredentialManagerProvider:
    """Read generic credentials from the current Windows user's vault."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

    @staticmethod
    def _validate_ref(value: str) -> str:
        ref = str(value or "").strip()
        if not ref or len(ref) > 256 or any(ord(ch) < 32 for ch in ref):
            raise CredentialProviderError("credential reference is invalid")
        return ref

    def _api(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            import win32cred  # type: ignore[import-not-found]
        except (ImportError, OSError) as exc:
            raise CredentialProviderError(
                "Windows Credential Manager is unavailable"
            ) from exc
        return win32cred

    @contextmanager
    def resolve(self, credential_ref: str) -> Iterator[ResolvedCredential]:
        ref = self._validate_ref(credential_ref)
        api = self._api()
        try:
            raw = api.CredRead(ref, api.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            raise CredentialProviderError(
                "credential reference is unavailable for the current Windows user"
            ) from exc

        username = str(raw.get("UserName") or "").strip()
        blob = raw.get("CredentialBlob", b"")
        if isinstance(blob, bytes):
            try:
                looks_utf16 = blob.startswith((b"\xff\xfe", b"\xfe\xff")) or (
                    len(blob) >= 2 and len(blob) % 2 == 0 and b"\x00" in blob[1::2]
                )
                password = blob.decode("utf-16-le" if looks_utf16 else "utf-8")
            except UnicodeDecodeError as exc:
                raise CredentialProviderError(
                    "credential reference has an unsupported value encoding"
                ) from exc
        else:
            password = str(blob or "")
        if not username or not password:
            password = ""
            raise CredentialProviderError("credential reference is incomplete")

        value = ResolvedCredential(username=username, password=password)
        username = ""
        password = ""
        raw = None
        try:
            yield value
        finally:
            value.clear()

    def is_available(self, credential_ref: str) -> bool:
        try:
            with self.resolve(credential_ref):
                return True
        except CredentialProviderError:
            return False


class MemoryCredentialProvider:
    """Offline test double; never use as production persistence."""

    def __init__(self, values: dict[str, tuple[str, str]]) -> None:
        self._values = dict(values)

    @contextmanager
    def resolve(self, credential_ref: str) -> Iterator[ResolvedCredential]:
        try:
            username, password = self._values[credential_ref]
        except KeyError as exc:
            raise CredentialProviderError("credential reference is unavailable") from exc
        value = ResolvedCredential(username=username, password=password)
        try:
            yield value
        finally:
            value.clear()

    def is_available(self, credential_ref: str) -> bool:
        return credential_ref in self._values
