from __future__ import annotations

import sys
import uuid

import pytest

from core.credential_provider import (
    CredentialProviderError,
    MemoryCredentialProvider,
    WindowsCredentialManagerProvider,
    delete_windows_generic_credential,
    store_windows_generic_credential,
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


class _FakeWin32Cred:
    """win32cred 替身：覆盖 CredWrite/CredDelete/CredRead 的最小行为面。

    CredWrite 按真实 pywin32 语义把 str CredentialBlob 编码为 UTF-16LE（无 BOM）。
    """

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self):
        self.written = []
        self.deleted = []
        self.errors: dict[str, Exception] = {}

    def CredWrite(self, credential, flags):
        blob = credential["CredentialBlob"]
        if isinstance(blob, str):
            blob = blob.encode("utf-16-le")
        self.written.append(dict(credential, CredentialBlob=blob, _flags=flags))

    def CredDelete(self, ref, credential_type, flags):
        error = self.errors.get(ref)
        if error is not None:
            raise error
        self.deleted.append(ref)

    def CredRead(self, ref, credential_type, flags):
        for credential in self.written:
            if credential["TargetName"] == ref:
                return {
                    "UserName": credential["UserName"],
                    "CredentialBlob": credential["CredentialBlob"],
                }
        raise RuntimeError("credential not found")


@pytest.fixture()
def fake_win32cred(monkeypatch: pytest.MonkeyPatch) -> _FakeWin32Cred:
    fake = _FakeWin32Cred()
    monkeypatch.setitem(sys.modules, "win32cred", fake)
    return fake


def test_store_windows_generic_credential_writes_utf16_blob(fake_win32cred):
    store_windows_generic_credential("domain", "user", "能-量@密码")
    (credential,) = fake_win32cred.written
    assert credential["TargetName"] == "domain"
    assert credential["UserName"] == "user"
    assert credential["Persist"] == fake_win32cred.CRED_PERSIST_LOCAL_MACHINE
    assert credential["_flags"] == 0
    blob = credential["CredentialBlob"]
    assert isinstance(blob, bytes)
    # pywin32 语义：str 由其内部编码为 UTF-16LE，不带 BOM。
    assert blob == "能-量@密码".encode("utf-16-le")


def test_store_then_provider_resolve_round_trip_with_non_ascii_password(fake_win32cred):
    """纯 CJK 密码（UTF-16LE 无 BOM、无 NUL）经读取端 utf-16-le 兜底分支还原。"""
    store_windows_generic_credential("domain", "user", "能量密码")
    provider = WindowsCredentialManagerProvider(fake_win32cred)
    with provider.resolve("domain") as value:
        assert value.username == "user"
        assert value.password == "能量密码"


def test_delete_windows_generic_credential_handles_not_found(fake_win32cred):
    missing = Exception("not found")
    missing.winerror = 1168
    fake_win32cred.errors["domain"] = missing
    assert delete_windows_generic_credential("domain") is False
    fake_win32cred.errors.clear()
    store_windows_generic_credential("domain", "user", "pwd")
    assert delete_windows_generic_credential("domain") is True
    assert fake_win32cred.deleted == ["domain"]


def test_delete_windows_generic_credential_wraps_other_errors(fake_win32cred):
    denied = Exception("access denied")
    denied.winerror = 5
    fake_win32cred.errors["domain"] = denied
    with pytest.raises(CredentialProviderError):
        delete_windows_generic_credential("domain")


@pytest.mark.parametrize("ref", ["", "bad\x00ref", "x" * 257])
def test_store_delete_reject_invalid_reference(fake_win32cred, ref):
    with pytest.raises(CredentialProviderError):
        store_windows_generic_credential(ref, "user", "pwd")
    with pytest.raises(CredentialProviderError):
        delete_windows_generic_credential(ref)


def test_store_and_resolve_round_trip_against_real_windows_vault():
    """真机回归：pywin32 的 CredWrite 拒绝 bytes blob，必须走 str 路径；密码用纯 CJK 覆盖兜底分支。"""
    win32cred = pytest.importorskip("win32cred")
    ref = "vse-toolbox-selftest-" + uuid.uuid4().hex[:8]
    try:
        store_windows_generic_credential(ref, "user", "能量密码")
        with WindowsCredentialManagerProvider().resolve(ref) as value:
            assert value.username == "user"
            assert value.password == "能量密码"
    finally:
        try:
            win32cred.CredDelete(ref, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception:
            pass
