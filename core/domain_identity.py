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
from typing import Any, Callable
from threading import RLock
from urllib.parse import urlsplit

from core.credential_provider import CredentialProviderError, ResolvedCredential


# ── 内部会话状态机（docs/refactor-v2/DSH_IDENTITY_CONTRACT.md §7.3）──────────
# 只出现在 payload()["state"] 与后端代码；CONTRACTS C2 的公开词汇不变（裁决 Q1）。
SESSION_STATE_NONE = "none"
SESSION_STATE_VALID = "valid"
SESSION_STATE_RENEWING = "renewing"
SESSION_STATE_EXPIRED = "expired"
SESSION_STATE_CLEARED = "cleared"
SESSION_STATE_FAILED = "failed"
SESSION_STATES = frozenset({
    SESSION_STATE_NONE,
    SESSION_STATE_VALID,
    SESSION_STATE_RENEWING,
    SESSION_STATE_EXPIRED,
    SESSION_STATE_CLEARED,
    SESSION_STATE_FAILED,
})

# 契约 §4.3 闭集错误码。未登记的码不得进入 payload()["lastErrorCode"]。
RECOVERY_ERROR_CODES = frozenset({
    "unauthenticated",
    "login_page",
    "session_cleared",
    "forbidden",
    "service_unavailable",
    "timeout",
    "upstream_parse_error",
    "credential_unavailable",
    "credential_invalid",
    "login_challenge",
    "login_locked",
    "generation_unknown",
})

# payload() 只暴露契约 C2 已冻结的两个系统。
_PAYLOAD_SYSTEMS = ("aras", "tdc")


class CredentialVaultError(RuntimeError):
    pass


def _mask_account(principal: str) -> str:
    """脱敏账号（裁决 Q9）：首字符 + 固定掩码 + 域后缀，绝不复用 scope 哈希。"""
    text = str(principal or "").strip()
    if not text:
        return ""
    local, separator, domain = text.partition("@")
    head = (local or text)[:1]
    return f"{head}***@{domain}" if separator and domain else f"{head}***"


def _account_ref(system: str, source: str, principal: str) -> str:
    """既有 ``scope`` 派生：保守精确 principal，别名的等价性永不猜测。"""
    return hashlib.sha256(json.dumps(
        [system, source, principal.strip()], ensure_ascii=True
    ).encode('utf-8')).hexdigest()


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
    #: 原始来源根（未归一化），只给续期回写复用；不进入 payload。
    source: str | None = None


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
    def __init__(self, ttl: timedelta = timedelta(hours=8), *,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._ttl = ttl
        # 契约 D12：时钟可注入，过期/续期竞态可确定性构造。
        self._clock = clock
        self._records: dict[str, _SessionRecord] = {}
        self._sessions: dict[str, Any] = {}
        self._lock = RLock()
        self._generations: dict[str, int] = {}
        self._vault_epoch = 0
        self._states: dict[str, str] = {}
        self._last_error: dict[str, str | None] = {}
        self._last_renewed: dict[str, datetime | None] = {}
        self._accounts: dict[str, str] = {}

    def _now(self) -> datetime:
        value = self._clock() if self._clock is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def account_ref(system: str, principal: str, source_root: str) -> str:
        """公开的 ``accountRef`` 派生（续期键的一半），与 ``mark_authenticated`` 同源。"""
        return _account_ref(system, _identity_source_root(source_root), principal)

    @observed("identity.DomainSessionRegistry.mark_authenticated")
    def mark_authenticated(self, system: str, session: Any | None = None, *,
                           principal: str | None = None, source_root: str | None = None) -> None:
        now = self._now()
        source = scope = None
        if principal is not None or source_root is not None:
            if not isinstance(principal, str) or not principal.strip() or session is None:
                raise ValueError('Incomplete identity binding')
            source = _identity_source_root(source_root)
            # Conservative exact principal: aliases produce separate scopes, never guessed equivalence.
            scope = _account_ref(system, source, principal)
        with self._lock:
            self._records[system] = _SessionRecord(
                now, now + self._ttl, source, scope,
                source_root if source is not None else None,
            )
            self._sessions.pop(system, None)
            # 用户显式登录：cleared/failed 只能经此回到 valid（契约 §7.3），失败计数由
            # 协调器按 record.updated_at 感知并清零。
            self._states.pop(system, None)
            self._last_error[system] = None
            if principal is None:
                self._accounts.pop(system, None)
            else:
                self._accounts[system] = _mask_account(principal)
            if isinstance(session, str) and session in {"aras", "tdc"}:
                self._records[session] = _SessionRecord(now, now + self._ttl)
                self._sessions.pop(session, None)
                self._states.pop(session, None)
                self._last_error[session] = None
                self._accounts.pop(session, None)
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
            if record is None or record.expires_at <= self._now():
                self._sessions.pop(system, None)
                return None
            return self._sessions.get(system)

    @observed("identity.DomainSessionRegistry.clear")
    def clear(self, system: str | None = None) -> None:
        with self._lock:
            # 契约 §7.2-1：先作废（代次 +1），再移除会话；在途续期由协调器取消。
            for name in self._clear_targets(system):
                self._generations[name] = self._generations.get(name, 0) + 1
                self._states[name] = SESSION_STATE_CLEARED
                self._last_error[name] = None
                self._accounts.pop(name, None)
            if system is None:
                self._records.clear()
                self._sessions.clear()
            else:
                self._records.pop(system, None)
                self._sessions.pop(system, None)

    def _clear_targets(self, system: str | None) -> tuple[str, ...]:
        if system is not None:
            return (system,)
        names = set(_PAYLOAD_SYSTEMS)
        names.update(self._generations)
        names.update(self._states)
        return tuple(sorted(names))

    # ── 新增：清除代次与状态机（契约 §7 / §8.1；只增不改）─────────────────

    def generation(self, system: str) -> int:
        with self._lock:
            return self._generations.get(system, 0)

    def vault_epoch(self) -> int:
        with self._lock:
            return self._vault_epoch

    def bump_vault_epoch(self) -> int:
        with self._lock:
            self._vault_epoch += 1
            return self._vault_epoch

    def state(self, system: str) -> str:
        with self._lock:
            explicit = self._states.get(system)
            if explicit in {SESSION_STATE_CLEARED, SESSION_STATE_FAILED, SESSION_STATE_RENEWING}:
                return explicit
            record = self._records.get(system)
            if record is None:
                return SESSION_STATE_NONE
            if record.expires_at <= self._now():
                return SESSION_STATE_EXPIRED
            return SESSION_STATE_VALID

    def begin_renewal(self, system: str) -> tuple[int, int]:
        """leader 开始续期：转 renewing 并捕获 (generation, vaultEpoch)。"""
        with self._lock:
            self.mark_renewing(system)
            return self._generations.get(system, 0), self._vault_epoch

    def mark_renewing(self, system: str) -> None:
        with self._lock:
            # cleared 是吸收态：自动路径不得把会话从 cleared 拉回 renewing/valid。
            if self._states.get(system) == SESSION_STATE_CLEARED:
                return
            self._states[system] = SESSION_STATE_RENEWING

    def end_renewal(self, system: str, *, error_code: str | None = None) -> str:
        """网络类失败：退出 renewing 但保留会话可重试（§7.3 renewing→expired）。"""
        with self._lock:
            if self._states.get(system) == SESSION_STATE_RENEWING:
                self._states.pop(system, None)
            if error_code is not None:
                self._last_error[system] = self._valid_code(error_code)
            return self.state(system)

    def commit_renewal(self, system: str, session: Any, *, principal: str,
                       source_root: str, generation: int, vault_epoch: int,
                       ttl: timedelta | None = None) -> bool:
        """续期成功回写；代次/凭据纪元已变则结果作废并返回 False（§7.2-2）。"""
        if session is None:
            raise ValueError('Renewed session is missing')
        if not isinstance(principal, str) or not principal.strip():
            raise ValueError('Incomplete identity binding')
        if ttl is not None and ttl <= timedelta(0):
            raise ValueError('Invalid renewal TTL')
        source = _identity_source_root(source_root)
        scope = _account_ref(system, source, principal)
        with self._lock:
            if self._generations.get(system, 0) != generation or self._vault_epoch != vault_epoch:
                # 结果作废：丢弃新会话对象，不更新 TTL/updatedAt（禁止复活）。
                self._records.pop(system, None)
                self._sessions.pop(system, None)
                self._accounts.pop(system, None)
                self._states[system] = SESSION_STATE_CLEARED
                return False
            now = self._now()
            self._records[system] = _SessionRecord(
                now, now + (ttl if ttl is not None else self._ttl), source, scope, source_root
            )
            self._sessions[system] = session
            self._states.pop(system, None)
            self._last_error[system] = None
            self._last_renewed[system] = now
            self._accounts[system] = _mask_account(principal)
            return True

    def mark_failed(self, system: str, code: str) -> None:
        """登录被拒/挑战/连续失败/解析失败：转 failed，只有手动登录可恢复。"""
        with self._lock:
            self._last_error[system] = self._valid_code(code)
            self._states[system] = SESSION_STATE_FAILED

    @staticmethod
    def _valid_code(code: str) -> str:
        text = str(code or "").strip()
        if text not in RECOVERY_ERROR_CODES:
            raise ValueError('Unsupported recovery error code')
        return text

    def identity_binding(self, system: str) -> tuple[str | None, str | None]:
        """``(原始 source_root, account_ref)``；只给协调器做续期键校验，永不进 payload。"""
        with self._lock:
            record = self._records.get(system)
            if record is None:
                return None, None
            return record.source, record.scope

    def record_updated_at(self, system: str) -> datetime | None:
        with self._lock:
            record = self._records.get(system)
            return record.updated_at if record is not None else None

    def payload(self) -> dict[str, dict[str, object]]:
        now = self._now()
        result: dict[str, dict[str, object]] = {}
        with self._lock:
            for system in _PAYLOAD_SYSTEMS:
                record = self._records.get(system)
                expired = record is not None and record.expires_at <= now
                state = self.state(system)
                renewed = self._last_renewed.get(system)
                result[system] = {
                    "authenticated": bool(record and not expired),
                    "updatedAt": record.updated_at.isoformat().replace("+00:00", "Z") if record else None,
                    "expiresAt": record.expires_at.isoformat().replace("+00:00", "Z") if record else None,
                    "expired": bool(expired),
                    "state": state,
                    "generation": self._generations.get(system, 0),
                    "accountMasked": self._accounts.get(system),
                    "lastErrorCode": self._last_error.get(system),
                    "lastRenewedAt": renewed.isoformat().replace("+00:00", "Z") if renewed else None,
                    "canRenew": bool(
                        record is not None
                        and record.scope
                        and state not in {SESSION_STATE_CLEARED, SESSION_STATE_FAILED}
                    ),
                }
        return result
