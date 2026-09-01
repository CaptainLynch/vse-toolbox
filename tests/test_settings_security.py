# -*- coding: utf-8 -*-
"""Focused security tests for application settings, path validation, and DPAPI credential isolation."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import web.app as web_app
from core.credential_provider import CredentialProviderError
from core.db_manager import DatabaseManager
from core.domain_identity import (
    CredentialVaultError,
    DPAPICredentialProvider,
    DomainSessionRegistry,
    WindowsDPAPICredentialVault,
)
from core.settings_store import (
    DEFAULTS,
    SettingsStore,
    SettingsValidationError,
    validate_local_directory,
)


def _runtime_opaque() -> str:
    return f"opq-{uuid.uuid4().hex}"


# ── 1. Local Directory Path Security Validation ───────────────────────────────


def test_validate_local_directory_valid_paths(tmp_path: Path) -> None:
    """Valid absolute local directory paths resolve successfully."""
    existing_dir = tmp_path / "fictional_valid_dir"
    existing_dir.mkdir(parents=True, exist_ok=True)

    resolved = validate_local_directory(str(existing_dir))
    assert Path(resolved).resolve() == existing_dir.resolve()

    # Non-existing but valid absolute path
    non_existing_dir = tmp_path / "fictional_sub_folder"
    resolved_non_existing = validate_local_directory(str(non_existing_dir))
    assert Path(resolved_non_existing).resolve() == non_existing_dir.resolve()


def test_validate_local_directory_empty_or_whitespace() -> None:
    """Empty or whitespace-only paths return empty string."""
    assert validate_local_directory("") == ""
    assert validate_local_directory("   ") == ""
    assert validate_local_directory("\t\n") == ""


def test_validate_local_directory_non_string_types() -> None:
    """Non-string inputs raise ValueError."""
    for invalid in (123, None, ["/some/path"], {"dir": "path"}, False, True):
        with pytest.raises(ValueError, match="必须是路径字符串"):
            validate_local_directory(invalid)


def test_validate_local_directory_rejects_unc_and_device_paths() -> None:
    """UNC and Windows device paths are strictly rejected."""
    unc_paths = (
        r"\\server\share\folder",
        r"\\192.168.1.1\share",
        "//server/share/folder",
        r"\\?\C:\some\dir",
        r"\\.\C:\some\dir",
        r"\\?\Volume{12345678-1234-1234-1234-123456789012}\\",
    )
    for unc in unc_paths:
        with pytest.raises(ValueError, match="仅允许本机普通目录"):
            validate_local_directory(unc)


def test_validate_local_directory_rejects_relative_and_traversal_paths(tmp_path: Path) -> None:
    """Relative paths and paths containing '..' traversal segments are rejected."""
    traversal_paths = (
        "relative/sub/dir",
        "./current/dir",
        "../parent/dir",
        str(tmp_path) + "/../escaped",
        r"C:\safe\..\sensitive",
    )
    for path_str in traversal_paths:
        with pytest.raises(ValueError, match="必须是绝对本机目录"):
            validate_local_directory(path_str)


def test_validate_local_directory_rejects_file_path(tmp_path: Path) -> None:
    """Paths pointing to existing regular files are rejected."""
    file_path = tmp_path / "fictional_file.txt"
    file_path.write_text("sample content", encoding="utf-8")

    with pytest.raises(ValueError, match="路径必须指向目录"):
        validate_local_directory(str(file_path))


# ── 2. SettingsStore Numeric Bounds and Credential Separation ─────────────────


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(db_path=tmp_path / "settings_test.db")
    manager.init_database()
    return manager


@pytest.fixture()
def store(db: DatabaseManager) -> SettingsStore:
    return SettingsStore(db)


def test_settings_store_defaults(store: SettingsStore) -> None:
    """Store returns expected default dictionary containing all standard keys."""
    settings = store.get()
    assert set(settings.keys()) == set(DEFAULTS.keys())
    for key, value in DEFAULTS.items():
        assert settings[key] == value


def test_settings_store_valid_numeric_and_path_updates(store: SettingsStore, tmp_path: Path) -> None:
    """Store accepts values within allowed integer bounds and valid paths."""
    archive_dir = tmp_path / "fictional_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    update_payload = {
        "archiveDirectory": str(archive_dir),
        "defaultDownloadMinutes": 120,
        "retryCount": 5,
        "dueSoonDays": 14,
        "cacheSnapshotCount": 60,
        "retentionDays": 180,
    }
    updated = store.update(update_payload)

    for key, value in update_payload.items():
        if key == "archiveDirectory":
            assert Path(str(updated[key])).resolve() == archive_dir.resolve()
        else:
            assert updated[key] == value


@pytest.mark.parametrize(
    ("key", "invalid_value"),
    [
        ("defaultDownloadMinutes", 4),       # below min 5
        ("defaultDownloadMinutes", 10081),   # above max 10080
        ("defaultDownloadMinutes", "60"),    # string type
        ("defaultDownloadMinutes", True),    # boolean type
        ("retryCount", -1),                  # below min 0
        ("retryCount", 11),                  # above max 10
        ("retryCount", False),               # boolean type
        ("dueSoonDays", -1),                 # below min 0
        ("dueSoonDays", 366),                # above max 365
        ("cacheSnapshotCount", 0),           # below min 1
        ("cacheSnapshotCount", 366),         # above max 365
        ("retentionDays", 0),                # below min 1
        ("retentionDays", 3651),             # above max 3650
    ],
)
def test_settings_store_rejects_out_of_bounds_integers(store: SettingsStore, key: str, invalid_value: Any) -> None:
    """Integer settings outside defined bounds or of incorrect types are rejected."""
    with pytest.raises(SettingsValidationError) as exc_info:
        store.update({key: invalid_value})
    assert key in exc_info.value.fields


def test_settings_store_separation_from_credentials(store: SettingsStore) -> None:
    """Attempting to inject credential fields into ordinary settings is strictly rejected."""
    sensitive_keys = [
        "password",
        "username",
        "token",
        "secret",
        "credential",
        "authorization",
    ]
    for key in sensitive_keys:
        sensitive = {key: _runtime_opaque()}
        with pytest.raises(SettingsValidationError) as exc_info:
            store.update(sensitive)
        assert "request" in exc_info.value.fields
        assert "包含不支持的设置" in exc_info.value.fields["request"]

    # Verify settings store remains untainted
    current = store.get()
    for key in sensitive_keys:
        assert key not in current


# ── 3. Windows DPAPI Credential Vault Security & Mock Isolation ───────────────


class FakeDPAPIBackend:
    """Deterministic, mock Windows DPAPI backend for isolated test environments."""

    PREFIX = b"MOCK_DPAPI_PROTECTED_BLOB:"

    @classmethod
    def CryptProtectData(
        cls,
        data: bytes,
        description: str = "",
        optional_entropy: Any = None,
        reserved: Any = None,
        prompt_struct: Any = None,
        flags: int = 0,
    ) -> tuple[str, bytes]:
        # Encrypts deterministically by reversing and prefixing
        return ("", cls.PREFIX + data[::-1])

    @classmethod
    def CryptUnprotectData(
        cls,
        data: bytes,
        optional_entropy: Any = None,
        reserved: Any = None,
        prompt_struct: Any = None,
        flags: int = 0,
    ) -> tuple[str, bytes]:
        if not data.startswith(cls.PREFIX):
            raise RuntimeError("Invalid ciphertext")
        clear = data[len(cls.PREFIX):][::-1]
        return ("", clear)


class BytesReturningDPAPIBackend(FakeDPAPIBackend):
    """Mirror the pywin32 CryptProtectData return type used by production Windows."""

    @classmethod
    def CryptProtectData(
        cls,
        data: bytes,
        description: str = "",
        optional_entropy: Any = None,
        reserved: Any = None,
        prompt_struct: Any = None,
        flags: int = 0,
    ) -> bytes:
        return cls.PREFIX + data[::-1]

    @classmethod
    def CryptUnprotectData(
        cls,
        data: bytes,
        optional_entropy: Any = None,
        reserved: Any = None,
        prompt_struct: Any = None,
        flags: int = 0,
    ) -> bytes:
        if not data.startswith(cls.PREFIX):
            raise RuntimeError("Invalid ciphertext")
        return data[len(cls.PREFIX):][::-1]


def test_dpapi_vault_stores_encrypted_bytes_without_plaintext(tmp_path: Path) -> None:
    """DPAPI vault writes encrypted bytes to disk and plaintext credentials are never stored in clear."""
    vault_file = tmp_path / "credentials" / "vault.dat"
    vault = WindowsDPAPICredentialVault(path=vault_file, backend=FakeDPAPIBackend)

    assert not vault.is_configured()

    user = _runtime_opaque()
    secret = _runtime_opaque()

    vault.store(user, secret)

    assert vault.is_configured()
    assert vault_file.is_file()

    raw_bytes = vault_file.read_bytes()
    assert raw_bytes.startswith(FakeDPAPIBackend.PREFIX)

    # Prove plaintext username and password are completely absent from the raw file bytes
    assert user.encode("utf-8") not in raw_bytes
    assert secret.encode("utf-8") not in raw_bytes

    # Incomplete credentials raise error
    with pytest.raises(CredentialVaultError, match="domain credentials are incomplete"):
        vault.store("", _runtime_opaque())
    with pytest.raises(CredentialVaultError, match="domain credentials are incomplete"):
        vault.store(_runtime_opaque(), "")


def test_dpapi_vault_accepts_pywin32_bytes_return_type(tmp_path: Path) -> None:
    """The real pywin32 API returns the protected blob directly as bytes, not a tuple."""
    vault_file = tmp_path / "credentials" / "pywin32-vault.dat"
    vault = WindowsDPAPICredentialVault(path=vault_file, backend=BytesReturningDPAPIBackend)

    vault.store(_runtime_opaque(), _runtime_opaque())

    assert vault.is_configured()


def test_dpapi_vault_clear_removes_file(tmp_path: Path) -> None:
    """DPAPI vault clear method removes the vault file on disk."""
    vault_file = tmp_path / "credentials" / "vault.dat"
    vault = WindowsDPAPICredentialVault(path=vault_file, backend=FakeDPAPIBackend)

    vault.store(_runtime_opaque(), _runtime_opaque())
    assert vault.is_configured()
    assert vault_file.exists()

    vault.clear()
    assert not vault.is_configured()
    assert not vault_file.exists()

    # Idempotent call
    vault.clear()
    assert not vault.is_configured()


def test_dpapi_vault_resolve_and_provider_lifecycle(tmp_path: Path) -> None:
    """Decryption succeeds only for approved reference, fields cleared on exit, unsupported fails."""
    vault_file = tmp_path / "credentials" / "vault.dat"
    vault = WindowsDPAPICredentialVault(path=vault_file, backend=FakeDPAPIBackend)

    approved_ref = "domain"
    unsupported_ref = _runtime_opaque()

    user = _runtime_opaque()
    secret = _runtime_opaque()

    vault.store(user, secret)
    assert vault.is_configured()

    raw_bytes = vault_file.read_bytes()
    assert raw_bytes.startswith(FakeDPAPIBackend.PREFIX)
    assert user.encode("utf-8") not in raw_bytes
    assert secret.encode("utf-8") not in raw_bytes

    provider = DPAPICredentialProvider(vault=vault)
    assert provider.is_available(approved_ref)
    assert not provider.is_available(unsupported_ref)

    # 1. Decryption succeeds only for the approved reference
    with provider.resolve(approved_ref) as resolved:
        assert resolved.username == user
        assert resolved.password == secret
        assert user not in repr(resolved)
        assert secret not in repr(resolved)

    # 2. Resolved fields are cleared after context exit
    assert resolved.username == ""
    assert resolved.password == ""

    # 3. Direct vault resolve also verifies lifecycle
    with vault.resolve() as v_resolved:
        assert v_resolved.username == user
        assert v_resolved.password == secret
    assert v_resolved.username == ""
    assert v_resolved.password == ""

    # 4. Unsupported references fail
    with pytest.raises(CredentialProviderError, match="credential reference is unavailable"):
        with provider.resolve(unsupported_ref):
            pass

    # 5. Vault clear removes file and provider resolve fails
    vault.clear()
    assert not vault.is_configured()
    assert not vault_file.exists()
    with pytest.raises(CredentialProviderError, match="credential reference is unavailable"):
        with provider.resolve(approved_ref):
            pass
    assert not provider.is_available(approved_ref)


def test_dpapi_vault_preserves_consumer_exception_after_resolve(tmp_path: Path) -> None:
    """Connector failures raised inside the resolved-credential context stay distinguishable."""
    vault_file = tmp_path / "credentials" / "vault.dat"
    vault = WindowsDPAPICredentialVault(path=vault_file, backend=FakeDPAPIBackend)
    vault.store(_runtime_opaque(), _runtime_opaque())

    with pytest.raises(RuntimeError, match="connector failure"):
        with vault.resolve():
            raise RuntimeError("connector failure")


# ── 4. DomainSessionRegistry and Web API Secret Absence ────────────────────────


def test_domain_session_registry_payload_is_secret_free() -> None:
    """DomainSessionRegistry payload contains only status/timestamps, no secrets."""
    registry = DomainSessionRegistry()
    registry.mark_authenticated("aras", "tdc")

    payload = registry.payload()
    assert "aras" in payload
    assert "tdc" in payload

    for sys_key, data in payload.items():
        assert isinstance(data["authenticated"], bool)
        assert data["authenticated"] is True
        assert data["updatedAt"] is not None
        assert data["expiresAt"] is not None
        assert data["expired"] is False

        # Ensure no credential or token fields exist
        assert "password" not in data
        assert "username" not in data
        assert "token" not in data
        assert "cookie" not in data

    registry.clear("aras")
    after_clear_aras = registry.payload()
    assert after_clear_aras["aras"]["authenticated"] is False
    assert after_clear_aras["tdc"]["authenticated"] is True


def _loopback_headers() -> dict[str, str]:
    return {"Host": "localhost:5000", "Origin": "http://localhost:5000", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    db = DatabaseManager(db_path=tmp_path / "web_settings_test.db")
    db.init_database()
    vault_path = tmp_path / "vault.dat"
    fake_vault = WindowsDPAPICredentialVault(path=vault_path, backend=FakeDPAPIBackend)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr(
        web_app,
        "WindowsDPAPICredentialVault",
        lambda *args, **kwargs: fake_vault,
    )

    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_api_settings_get_payload_contains_no_secrets(client: Any) -> None:
    """GET /api/settings response payload exposes no passwords or secret tokens."""
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"

    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]

    # Verify presence of approved fields
    assert "settings" in data
    assert "sessions" in data
    assert "credentialVaultConfigured" in data

    # Verify absence of secrets across entire serialized response
    raw_json = json.dumps(body)
    assert "password" not in raw_json.lower()
    assert "token" not in raw_json.lower()
    assert "secret" not in raw_json.lower()


def test_api_settings_domain_login_and_clear_lifecycle(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST domain-login and DELETE sessions operate securely without echoing passwords."""
    # Mock authentication clients to succeed
    mock_aras = MagicMock()
    mock_aras.login.return_value = MagicMock(session="aras_session")
    mock_tdc = MagicMock()
    mock_tdc.login.return_value = MagicMock(session="tdc_session")

    monkeypatch.setattr(web_app, "ArasECMAuthClient", lambda: mock_aras)
    monkeypatch.setattr(web_app, "TDCPasswordAuthClient", lambda: mock_tdc)
    monkeypatch.setattr(
        web_app,
        "store_windows_generic_credential",
        lambda ref, username, password: None,
    )
    monkeypatch.setattr(
        web_app,
        "delete_windows_generic_credential",
        lambda ref: True,
    )

    user = _runtime_opaque()
    secret = _runtime_opaque()
    login_payload = {
        "username": user,
        "password": secret,
        "saveForScheduled": True,
    }

    resp = client.post(
        "/api/settings/domain-login",
        json=login_payload,
        headers=_loopback_headers(),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True

    # Assert response contains results and session status, never the password
    assert "results" in body["data"]
    assert "sessions" in body["data"]
    assert secret not in json.dumps(body)

    # Check settings get reflects vault configuration
    settings_resp = client.get("/api/settings")
    assert settings_resp.get_json()["data"]["credentialVaultConfigured"] is True

    # Clear sessions and vault
    clear_resp = client.delete(
        "/api/settings/sessions",
        json={"clearCredentialVault": True},
        headers=_loopback_headers(),
    )
    assert clear_resp.status_code == 200
    assert client.get("/api/settings").get_json()["data"]["credentialVaultConfigured"] is False


def test_domain_login_save_writes_and_clear_removes_windows_credential(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """统一域账号登录勾选保存时，必须同步写入交付物同步使用的 Windows 凭据库。"""
    mock_aras = MagicMock()
    mock_aras.login.return_value = MagicMock(session="aras_session")
    mock_tdc = MagicMock()
    mock_tdc.login.return_value = MagicMock(session="tdc_session")
    monkeypatch.setattr(web_app, "ArasECMAuthClient", lambda: mock_aras)
    monkeypatch.setattr(web_app, "TDCPasswordAuthClient", lambda: mock_tdc)

    stored: list[tuple[str, str, str]] = []
    deleted: list[str] = []
    monkeypatch.setattr(
        web_app,
        "store_windows_generic_credential",
        lambda ref, username, password: stored.append((ref, username, password)),
    )
    monkeypatch.setattr(
        web_app,
        "delete_windows_generic_credential",
        lambda ref: deleted.append(ref) or True,
    )

    user = _runtime_opaque()
    secret = _runtime_opaque()
    resp = client.post(
        "/api/settings/domain-login",
        json={"username": user, "password": secret, "saveForScheduled": True},
        headers=_loopback_headers(),
    )
    assert resp.status_code == 200
    assert stored == [(web_app.SYNC_CREDENTIAL_REF, user, secret)]

    clear_resp = client.delete(
        "/api/settings/sessions",
        json={"clearCredentialVault": True},
        headers=_loopback_headers(),
    )
    assert clear_resp.status_code == 200
    assert deleted == [web_app.SYNC_CREDENTIAL_REF]


def test_domain_login_windows_credential_failure_returns_503(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows 凭据库不可用时，统一登录必须显式失败而不是静默丢失同步凭据。"""
    mock_aras = MagicMock()
    mock_aras.login.return_value = MagicMock(session="aras_session")
    mock_tdc = MagicMock()
    mock_tdc.login.return_value = MagicMock(session="tdc_session")
    monkeypatch.setattr(web_app, "ArasECMAuthClient", lambda: mock_aras)
    monkeypatch.setattr(web_app, "TDCPasswordAuthClient", lambda: mock_tdc)

    def _fail(ref: str, username: str, password: str) -> None:
        raise CredentialProviderError("Windows Credential Manager is unavailable")

    monkeypatch.setattr(web_app, "store_windows_generic_credential", _fail)

    resp = client.post(
        "/api/settings/domain-login",
        json={
            "username": _runtime_opaque(),
            "password": _runtime_opaque(),
            "saveForScheduled": True,
        },
        headers=_loopback_headers(),
    )
    assert resp.status_code == 503
    assert resp.get_json()["error"]["type"] == "CredentialVaultUnavailable"


def test_domain_login_dpapi_failure_rolls_back_windows_credential(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DPAPI 落库失败时必须回滚 Windows 凭据，且 503 消息说明登录会话已建立。"""
    mock_aras = MagicMock()
    mock_aras.login.return_value = MagicMock(session="aras_session")
    mock_tdc = MagicMock()
    mock_tdc.login.return_value = MagicMock(session="tdc_session")
    monkeypatch.setattr(web_app, "ArasECMAuthClient", lambda: mock_aras)
    monkeypatch.setattr(web_app, "TDCPasswordAuthClient", lambda: mock_tdc)
    monkeypatch.setattr(web_app, "store_windows_generic_credential", lambda ref, u, p: None)
    deleted: list[str] = []
    monkeypatch.setattr(
        web_app,
        "delete_windows_generic_credential",
        lambda ref: deleted.append(ref) or True,
    )

    def _dpapi_down(self, username: str, password: str) -> None:
        raise CredentialVaultError("dpapi unavailable")

    monkeypatch.setattr(WindowsDPAPICredentialVault, "store", _dpapi_down)

    resp = client.post(
        "/api/settings/domain-login",
        json={
            "username": _runtime_opaque(),
            "password": _runtime_opaque(),
            "saveForScheduled": True,
        },
        headers=_loopback_headers(),
    )
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"]["type"] == "CredentialVaultUnavailable"
    assert "登录会话已建立" in body["error"]["message"]
    assert deleted == [web_app.SYNC_CREDENTIAL_REF]
