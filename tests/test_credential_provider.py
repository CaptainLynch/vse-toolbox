from __future__ import annotations

import pytest

from core.credential_provider import (
    CredentialProviderError,
    MemoryCredentialProvider,
    WindowsCredentialManagerProvider,
)


class FakeBackend:
    CRED_TYPE_GENERIC = 1

    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def CredRead(self, ref, credential_type, flags):
        if self.error:
            raise self.error
        return self.value


def test_resolve_decodes_and_clears_without_repr_disclosure():
    sentinel_user = "synthetic-user"
    sentinel_password = "synthetic-pass"
    backend = FakeBackend({"UserName": sentinel_user, "CredentialBlob": sentinel_password.encode("utf-16-le")})
    provider = WindowsCredentialManagerProvider(backend)
    with provider.resolve("vse/test") as value:
        assert value.username == sentinel_user
        assert value.password == sentinel_password
        assert sentinel_user not in repr(value)
        assert sentinel_password not in repr(value)
    assert value.username == ""
    assert value.password == ""


@pytest.mark.parametrize("ref", ["", "bad\x00ref", "x" * 257])
def test_invalid_reference_is_rejected(ref):
    with pytest.raises(CredentialProviderError):
        with WindowsCredentialManagerProvider(FakeBackend()).resolve(ref):
            pass


def test_backend_failures_and_incomplete_values_are_secret_free():
    secret = "synthetic-secret"
    provider = WindowsCredentialManagerProvider(FakeBackend(error=RuntimeError(secret)))
    with pytest.raises(CredentialProviderError) as caught:
        with provider.resolve("missing"):
            pass
    assert secret not in str(caught.value)
    incomplete = WindowsCredentialManagerProvider(FakeBackend({"UserName": "", "CredentialBlob": b""}))
    assert not incomplete.is_available("missing")


def test_utf8_blob_and_memory_test_double():
    backend = FakeBackend({"UserName": "user", "CredentialBlob": b"pass"})
    with WindowsCredentialManagerProvider(backend).resolve("ref") as value:
        assert value.password == "pass"
    memory = MemoryCredentialProvider({"ref": ("user", "pass")})
    assert memory.is_available("ref")
    with memory.resolve("ref") as value:
        assert value.username == "user"
    assert value.username == ""
    with pytest.raises(CredentialProviderError):
        with memory.resolve("missing"):
            pass
