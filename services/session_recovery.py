# -*- coding: utf-8 -*-
"""企业会话续期协调器与清除代次（DSH-V2-15）。

实现依据：``docs/refactor-v2/DSH_IDENTITY_CONTRACT.md`` §4–§9、§10.1/§10.3 与
§11「主控裁决记录（2026-11-01）」。本模块只负责进程内的单飞续期、错误分类、
一次重放与代次复核；路由/前端/爬虫接线由 DSH-V2-16 与 15b 承接（§10.2）。

硬约束（逐条对应契约）：

* 只有 ``session_expired`` 触发自动续期；``forbidden`` / 网络 / 解析永不触发；
* 同 ``(system, accountRef)`` 并发过期请求共享同一次续期（单飞），follower
  不自行发起登录；
* 每个业务操作最多重放一次；``unsafe_side_effect`` 与「已发出但无响应」不重放；
* 续期回写前复核 ``(generation, vaultEpoch)``，任一变化即作废；
* 失败不静默重试、不换供应商、不切换账号；
* 口令/令牌/Cookie 只存在于凭据 ``resolve()`` 上下文内，绝不进入异常文本、
  快照或诊断事件。

实现说明（两处契约留白，按最保守语义落地）：

1. §6.2 中「网络超时/连接重置（无响应）+ 任意类 → 不重放」约束的是**重放**；
   错误码仍按 §4.1-6 处理：``unsafe_side_effect`` 的无响应失败升级为
   ``generation_unknown``（409/confirm），幂等读仍返回 ``timeout`` /
   ``service_unavailable``（可稍后重试），且两者都不自动重放。
2. 续期总预算 ``renewal_timeout`` 用注入时钟度量（登录调用返回后复核）；
   follower 另以 ``Event.wait(timeout)`` 兜底，超时得到 ``timeout`` 且不重试。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from core.credential_provider import CredentialProviderError
from core.diagnostic_recording import emit
from core.domain_identity import DomainSessionRegistry

SYSTEMS = ("aras", "tdc")            # 帆软/TIR 不在续期范围（§1.5 契约边界）

IDEMPOTENT_READ = "idempotent_read"
IDEMPOTENT_WRITE_WITH_KEY = "idempotent_write_with_key"
UNSAFE_SIDE_EFFECT = "unsafe_side_effect"
OPERATION_KINDS = frozenset({IDEMPOTENT_READ, IDEMPOTENT_WRITE_WITH_KEY, UNSAFE_SIDE_EFFECT})

DEFAULT_CREDENTIAL_REF = "domain"
DEFAULT_RENEWAL_TIMEOUT = 120.0      # 裁决 Q10
_TTL_SAFETY_SECONDS = 60.0
_MAX_TTL = timedelta(hours=8)

# ── 契约 §4.3 闭集：code → type / HTTP / action / 中文文案 ────────────────────
_ERROR_TYPES = {
    "unauthenticated": "AuthenticationError",
    "login_page": "AuthenticationError",
    "session_cleared": "DomainLoginRequired",
    "forbidden": "Forbidden",
    "service_unavailable": "ServiceUnavailable",
    "timeout": "ServiceUnavailable",
    "upstream_parse_error": "UpstreamContractError",
    "credential_unavailable": "CredentialVaultUnavailable",
    "credential_invalid": "DomainLoginRejected",
    "login_challenge": "DomainLoginRejected",
    "login_locked": "DomainLoginRejected",
    "generation_unknown": "ConflictError",
}
_HTTP_STATUS = {
    "unauthenticated": 401,
    "login_page": 401,
    "session_cleared": 401,
    "forbidden": 403,
    "service_unavailable": 503,
    "timeout": 503,
    "upstream_parse_error": 502,
    "credential_unavailable": 503,
    "credential_invalid": 401,
    "login_challenge": 401,
    "login_locked": 401,
    "generation_unknown": 409,
}
_ACTIONS = {
    "unauthenticated": "renew",
    "login_page": "renew",
    "session_cleared": "relogin",
    "forbidden": "none",
    "service_unavailable": "wait",
    "timeout": "wait",
    "upstream_parse_error": "none",
    "credential_unavailable": "relogin",
    "credential_invalid": "relogin",
    "login_challenge": "relogin",
    "login_locked": "relogin",
    "generation_unknown": "confirm",
}
_MESSAGES = {
    "unauthenticated": "登录已过期，正在尝试恢复…",
    "login_page": "上游返回了登录页，登录状态已失效",
    "session_cleared": "登录已被清除，请重新登录",
    "forbidden": "当前域账号没有该操作权限，请联系系统管理员；不需要重新登录",
    "service_unavailable": "企业系统暂时不可用，请检查网络或 VPN 后重试",
    "timeout": "企业系统响应超时，请稍后重试",
    "upstream_parse_error": "上游返回的数据格式与预期不符；已生成诊断，请回传诊断文件",
    "credential_unavailable": "未保存域账号凭据或凭据无法读取，请重新登录并勾选保存",
    "credential_invalid": "域账号口令被拒绝；请确认口令未变更后手动重新登录",
    "login_challenge": "登录需要验证码/多因素验证，请手动登录",
    "login_locked": "连续登录失败，可能触发账号锁定；请稍后手动登录",
    "generation_unknown": "操作可能已在上游执行但结果未知，请先在系统中确认，再决定是否重试",
}
_RETRYABLE = frozenset({"service_unavailable", "timeout"})

# §8.3：diagnostic 只允许这些键（不含业务行内容、URL、令牌）。
_DIAGNOSTIC_KEYS = frozenset({"system", "stage", "upstreamHttpStatus", "apiCode", "requestId", "generation"})
_KNOWN_STAGES = frozenset({
    "request", "export", "status-validation", "content-validation", "parse-json",
    "api-validation", "export-validation", "contract-validation", "pagination",
    "auth-verify", "ecm-credentials", "credentials-redirect", "oidc-token",
    "userinfo", "advalidate", "innovator-token", "validate-user", "login-form",
    "tdc-session-init", "tdc-token",
})
# 契约 §4.2 的逐阶段归类。值为 None 表示"交给 HTTP 状态码分支判定"。
_STAGE_CODES = {
    "credentials-rejected": "credential_invalid",
    "challenge-required": "login_challenge",
    "validate-user-no-user": "forbidden",
    "validate-user-rejected": "credential_invalid",
    "validate-user-login-page": "credential_invalid",
    "session-verification-failed": "credential_invalid",
    "rejected-content-type": "upstream_parse_error",
    "invalid-json": "upstream_parse_error",
    "json-not-object": "upstream_parse_error",
    "content-validation": "upstream_parse_error",
    "parse-json": "upstream_parse_error",
    "api-validation": "forbidden",
    "status-validation": None,
}

_TRANSPORT_NAMES = frozenset({
    "ConnectionError", "ConnectionResetError", "ConnectionAbortedError", "RemoteDisconnected",
    "IncompleteRead", "SSLError", "ProxyError", "ChunkedEncodingError", "ProtocolError",
    "NewConnectionError", "MaxRetryError", "TransportError",
})
_TIMEOUT_NAMES = frozenset({"Timeout", "ConnectTimeout", "ReadTimeout"})
_CANCEL_NAMES = frozenset({"CrawlCancelled", "CancelledError", "TaskCancelled"})


def _names(exc: BaseException) -> frozenset[str]:
    return frozenset(cls.__name__ for cls in type(exc).__mro__)


def _is_cancellation(exc: BaseException) -> bool:
    """调用方取消不是错误，原样上抛，绝不改写成可重试码。"""
    return bool(_names(exc) & _CANCEL_NAMES)


def _status_code_of(exc: BaseException) -> int | None:
    """已收到 HTTP 状态码 ⇒ 不是 generation_unknown（§4.1 判定顺序）。"""
    for holder in (exc, getattr(exc, "response", None)):
        value = getattr(holder, "status_code", None)
        if type(value) is int and 100 <= value <= 599:
            return value
    return None


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or bool(_names(exc) & _TIMEOUT_NAMES)


def _is_transport(exc: BaseException) -> bool:
    return isinstance(exc, OSError) or bool(_names(exc) & _TRANSPORT_NAMES)


def _closed_detail(detail: Mapping[str, Any] | None) -> dict[str, Any]:
    """§8.3 闭集诊断元数据：未知键静默丢弃，值只允许短标量。"""
    result: dict[str, Any] = {}
    if not isinstance(detail, Mapping):
        return result
    for key, value in detail.items():
        if key not in _DIAGNOSTIC_KEYS:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result[key] = value
        elif isinstance(value, str) and 0 < len(value) <= 64:
            result[key] = value
    return result


def _detail_of(exc: BaseException | None) -> dict[str, Any]:
    if exc is None:
        return {}
    detail: dict[str, Any] = {}
    stage = getattr(exc, "stage", None)
    if isinstance(stage, str) and stage in _KNOWN_STAGES:
        detail["stage"] = stage
    status = _status_code_of(exc)
    if status is not None:
        detail["upstreamHttpStatus"] = status
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and 8 <= len(request_id) <= 32 and request_id.isalnum():
        detail["requestId"] = request_id
    api_code = getattr(exc, "api_code", None)
    if type(api_code) is int or (isinstance(api_code, str) and 0 < len(api_code) <= 16):
        detail["apiCode"] = api_code
    return detail


class SessionRecoveryError(Exception):
    """闭集会话恢复错误：``str()`` 即可安全展示与入库。"""

    CODES: frozenset[str] = frozenset()
    DEFAULT_CODE: str = ""

    def __init__(self, code: str | None = None, *, system: str = "",
                 detail: Mapping[str, Any] | None = None, replayed: bool = False) -> None:
        resolved = str(code or self.DEFAULT_CODE)
        if resolved not in self.CODES:
            raise ValueError("unsupported recovery error code")
        self.code = resolved
        self.system = str(system or "")
        self.detail = _closed_detail(detail)
        #: 该错误是否发生在"重放"那一次尝试上（契约 §6.3 诊断要求）。
        self.replayed = bool(replayed)
        super().__init__(_MESSAGES[resolved])

    @property
    def error_type(self) -> str:
        return _ERROR_TYPES[self.code]

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS[self.code]

    @property
    def action(self) -> str:
        return _ACTIONS[self.code]

    @property
    def retryable(self) -> bool:
        return self.code in _RETRYABLE

    def to_error_payload(self) -> dict[str, Any]:
        """§8.3 前端错误信封的 ``error`` 部分（闭集，无上游原文/URL/令牌）。"""
        diagnostic = dict(self.detail)
        if self.system:
            diagnostic["system"] = self.system
        return {
            "type": self.error_type,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "action": self.action,
            "diagnostic": diagnostic,
        }


class SessionExpired(SessionRecoveryError):
    CODES = frozenset({"unauthenticated", "login_page"})
    DEFAULT_CODE = "unauthenticated"


class SessionCleared(SessionRecoveryError):
    CODES = frozenset({"session_cleared"})
    DEFAULT_CODE = "session_cleared"


class Forbidden(SessionRecoveryError):
    CODES = frozenset({"forbidden"})
    DEFAULT_CODE = "forbidden"


class UpstreamUnavailable(SessionRecoveryError):
    CODES = frozenset({"service_unavailable", "timeout"})
    DEFAULT_CODE = "service_unavailable"


class UpstreamParseError(SessionRecoveryError):
    CODES = frozenset({"upstream_parse_error"})
    DEFAULT_CODE = "upstream_parse_error"


class CredentialUnavailable(SessionRecoveryError):
    CODES = frozenset({"credential_unavailable"})
    DEFAULT_CODE = "credential_unavailable"


class RenewalRejected(SessionRecoveryError):
    CODES = frozenset({"credential_invalid", "login_challenge", "login_locked"})
    DEFAULT_CODE = "credential_invalid"


class GenerationUnknown(SessionRecoveryError):
    CODES = frozenset({"generation_unknown"})
    DEFAULT_CODE = "generation_unknown"


_ERROR_CLASSES = {
    "unauthenticated": SessionExpired,
    "login_page": SessionExpired,
    "session_cleared": SessionCleared,
    "forbidden": Forbidden,
    "service_unavailable": UpstreamUnavailable,
    "timeout": UpstreamUnavailable,
    "upstream_parse_error": UpstreamParseError,
    "credential_unavailable": CredentialUnavailable,
    "credential_invalid": RenewalRejected,
    "login_challenge": RenewalRejected,
    "login_locked": RenewalRejected,
    "generation_unknown": GenerationUnknown,
}


def _error_for(code: str, *, system: str, exc: BaseException | None = None,
               replayed: bool = False) -> SessionRecoveryError:
    return _ERROR_CLASSES[code](
        code, system=system, detail=_detail_of(exc), replayed=replayed
    )


@dataclass(frozen=True)
class SessionSnapshot:
    """续期结果的只读视图；只输出 §8.1 白名单键，绝不含 principal/scope/令牌。"""

    system: str
    state: str
    generation: int
    account_masked: str | None
    last_renewed_at: str | None
    last_error_code: str | None
    can_renew: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "system": self.system,
            "state": self.state,
            "generation": self.generation,
            "accountMasked": self.account_masked,
            "lastRenewedAt": self.last_renewed_at,
            "lastErrorCode": self.last_error_code,
            "canRenew": self.can_renew,
        }


class _Flight:
    """单飞续期的一次在途结果；follower 只等待，不登录。"""

    __slots__ = ("key", "done", "snapshot", "error", "joiners")

    def __init__(self, key: tuple[str, str]) -> None:
        self.key = key
        self.done = threading.Event()
        self.snapshot: SessionSnapshot | None = None
        self.error: SessionRecoveryError | None = None
        self.joiners = 0


class SessionRenewalCoordinator:
    """同 ``(system, accountRef)`` 单飞续期 + 清除代次复核 + 一次重放。"""

    def __init__(
        self,
        registry: DomainSessionRegistry,
        credential_provider: Any,
        clients: Mapping[str, Callable[[], Any]],
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        renewal_timeout: float = DEFAULT_RENEWAL_TIMEOUT,
        max_auto_attempts: int = 3,
        cooldown_seconds: tuple[float, ...] = (60.0, 300.0),
        attempt_window_seconds: float = 900.0,
        credential_ref: str = DEFAULT_CREDENTIAL_REF,
    ) -> None:
        if not isinstance(registry, DomainSessionRegistry):
            raise TypeError("registry must be a DomainSessionRegistry")
        if float(renewal_timeout) <= 0:
            raise ValueError("renewal_timeout must be positive")
        if int(max_auto_attempts) < 1:
            raise ValueError("max_auto_attempts must be at least 1")
        self._registry = registry
        self._provider = credential_provider
        self._clients = dict(clients or {})
        self._clock = clock
        self._sleep = sleep  # 保留契约签名；本实现不阻塞等待冷却，直接返回 login_locked
        self._renewal_timeout = float(renewal_timeout)
        self._max_auto_attempts = int(max_auto_attempts)
        self._cooldown_seconds = tuple(float(value) for value in cooldown_seconds) or (60.0, 300.0)
        self._attempt_window = timedelta(seconds=float(attempt_window_seconds))
        self._credential_ref = str(credential_ref or DEFAULT_CREDENTIAL_REF)
        self._lock = threading.RLock()
        self._waiter_cv = threading.Condition(self._lock)
        self._flights: dict[tuple[str, str], _Flight] = {}
        self._failures: dict[tuple[str, str], int] = {}
        self._last_failure_at: dict[tuple[str, str], datetime] = {}
        self._attempts: dict[tuple[str, str], list[datetime]] = {}
        self._diagnostics: dict[str, int] = {}
        self._last_operation: dict[str, Any] | None = None

    # ── 时钟与只读诊断 ────────────────────────────────────────────────────

    def _now(self) -> datetime:
        value = self._clock() if self._clock is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def diagnostic_counts(self) -> dict[str, int]:
        """进程内诊断计数（闭集 code → 次数）；不落盘、不含秘密。"""
        with self._lock:
            return dict(self._diagnostics)

    def last_operation(self) -> dict[str, Any] | None:
        """最近一次 ``run_with_renewal`` 的闭集元数据（含 ``replayed``）。"""
        with self._lock:
            return dict(self._last_operation) if self._last_operation else None

    def in_flight(self, system: str, account_ref: str) -> bool:
        with self._lock:
            return (system, str(account_ref or "").strip()) in self._flights

    def await_waiters(self, system: str, account_ref: str, count: int,
                      timeout: float = 5.0) -> bool:
        """等待至少 ``count`` 个 follower 加入在途续期（单飞可观测性）。

        只做观察，不触发任何登录；供运维/测试确认"10 个并发只续期一次"的窗口。
        """
        key = (system, str(account_ref or "").strip())

        def ready() -> bool:
            flight = self._flights.get(key)
            return flight is None or flight.joiners >= count or flight.done.is_set()

        with self._waiter_cv:
            self._waiter_cv.wait_for(ready, max(0.0, float(timeout)))
            flight = self._flights.get(key)
            return flight is not None and flight.joiners >= count

    # ── 快照 ─────────────────────────────────────────────────────────────

    def snapshot(self, system: str) -> SessionSnapshot:
        self._require_system(system)
        payload = self._registry.payload()[system]
        return SessionSnapshot(
            system=system,
            state=str(payload["state"]),
            generation=int(payload["generation"]),
            account_masked=payload["accountMasked"],
            last_renewed_at=payload["lastRenewedAt"],
            last_error_code=payload["lastErrorCode"],
            can_renew=bool(payload["canRenew"])
            and self._credentials_available()
            and self._client_factory(system) is not None,
        )

    # ── 单飞续期 ─────────────────────────────────────────────────────────

    def renew(self, system: str, *, account_ref: str, generation: int,
              since: datetime | None = None) -> SessionSnapshot:
        """续期一次；同键并发调用共享 leader 的结果（包括失败）。

        ``since`` 为触发续期的业务操作开始时刻：若会话在其之后已被续期/重登且仍有效，
        直接复用，不再登录（单飞只覆盖时间重叠的请求，此处补齐“刚续期完”的窗口，
        避免多余登录累计到账号锁定）。
        """
        self._require_system(system)
        reference = str(account_ref or "").strip()
        if not reference:
            # §7.3：无可续期条件（无 accountRef）→ failed(credential_unavailable)
            error = CredentialUnavailable(system=system)
            self._registry.mark_failed(system, error.code)
            self._note(error)
            raise error
        key = (system, reference)
        with self._lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = _Flight(key)
                self._flights[key] = flight
        if not leader:
            return self._follow(flight, system)
        return self._lead(flight, system, reference, generation, self._now(), since)

    def _follow(self, flight: _Flight, system: str) -> SessionSnapshot:
        with self._lock:
            flight.joiners += 1
            self._waiter_cv.notify_all()
        if not flight.done.wait(self._renewal_timeout):
            error = UpstreamUnavailable("timeout", system=system)
            self._note(error)
            raise error
        if flight.error is not None:
            raise self._copy_error(flight.error)
        return flight.snapshot

    @staticmethod
    def _copy_error(error: SessionRecoveryError) -> SessionRecoveryError:
        return type(error)(
            error.code, system=error.system, detail=error.detail, replayed=error.replayed
        )

    def _lead(self, flight: _Flight, system: str, account_ref: str,
              generation: int, started: datetime,
              since: datetime | None = None) -> SessionSnapshot:
        try:
            snapshot = self._run_leader(system, account_ref, generation, started, since)
        except Exception as exc:  # noqa: BLE001 - 闭集化后重抛，绝不泄漏原文
            error = self._renewal_failure(exc, system=system, key=flight.key)
            flight.error = error
            raise error from None
        else:
            flight.snapshot = snapshot
            return snapshot
        finally:
            # follower 只有在结果（成功或闭集错误）就绪后才被唤醒。
            with self._lock:
                if self._flights.get(flight.key) is flight:
                    self._flights.pop(flight.key, None)
                flight.done.set()
                self._waiter_cv.notify_all()

    def _run_leader(self, system: str, account_ref: str, generation: int,
                    started: datetime, since: datetime | None = None) -> SessionSnapshot:
        registry = self._registry
        if registry.generation(system) != generation:
            raise SessionCleared(system=system)
        if since is not None:
            updated = registry.record_updated_at(system)
            if (updated is not None and updated > since
                    and registry.session(system) is not None
                    and registry.identity_binding(system)[1] == account_ref):
                return self.snapshot(system)
        self._reset_if_manual_login(system, account_ref)
        self._guard_auto_attempt(system, account_ref)
        if not self._credentials_available():
            raise CredentialUnavailable(system=system)
        factory = self._client_factory(system)
        if factory is None:
            raise CredentialUnavailable(system=system)
        source_root, recorded_ref = registry.identity_binding(system)
        if not source_root or not recorded_ref:
            raise CredentialUnavailable(system=system)
        if recorded_ref != account_ref:
            # 绑定已换账号：本键的会话不存在，禁止把别的账号会话写回。
            raise SessionCleared(system=system)
        captured_generation, captured_epoch = registry.begin_renewal(system)
        self._record_attempt(system, account_ref)
        client = factory()
        username = ""
        result: Any = None
        try:
            with self._provider.resolve(self._credential_ref) as credential:
                username = str(getattr(credential, "username", "") or "")
                password = str(getattr(credential, "password", "") or "")
                if not username or not password:
                    raise CredentialUnavailable(system=system)
                if DomainSessionRegistry.account_ref(system, username, source_root) != account_ref:
                    # 凭据库里的账号已不是绑定的账号：拒绝自动续期，要求手动重登。
                    raise RenewalRejected("credential_invalid", system=system)
                try:
                    result = client.login(username, password)
                finally:
                    password = ""
        except CredentialProviderError:
            raise CredentialUnavailable(system=system) from None
        if self._now() - started > timedelta(seconds=self._renewal_timeout):
            raise UpstreamUnavailable("timeout", system=system)
        session = getattr(result, "session", None)
        if session is None:
            raise UpstreamParseError(system=system)
        ttl = self._renewal_ttl(result)
        if not registry.commit_renewal(
            system, session, principal=username, source_root=source_root,
            generation=captured_generation, vault_epoch=captured_epoch, ttl=ttl,
        ):
            raise SessionCleared(system=system)
        self._reset_attempts(system, account_ref)
        return self.snapshot(system)

    # ── 业务操作 + 一次重放 ──────────────────────────────────────────────

    def run_with_renewal(self, system: str, account_ref: str, operation: Callable[[], Any],
                         *, kind: str, idempotency_key: str | None = None) -> Any:
        """执行一次业务操作；仅在分类为 ``session_expired`` 时续期并按 §6 重放一次。"""
        self._require_system(system)
        if kind not in OPERATION_KINDS:
            raise ValueError("unsupported operation kind")
        key = str(idempotency_key or "").strip()
        if kind == IDEMPOTENT_WRITE_WITH_KEY and not key:
            raise ValueError("idempotent_write_with_key requires an idempotency key")
        reference = str(account_ref or "").strip()
        generation = self._registry.generation(system)
        started = self._now()
        try:
            value = operation()
        except Exception as exc:  # noqa: BLE001
            if _is_cancellation(exc):
                raise
            classified = self.classify(exc, system=system)
            if not isinstance(classified, SessionExpired):
                error = self._business_error(classified, kind=kind, exc=exc)
                self._note(error)
                self._record_operation(system, kind, 1, False, error.code, started)
                raise error from None
            return self._recover_and_replay(
                system, reference, operation, kind=kind, generation=generation,
                started=started,
            )
        self._record_operation(system, kind, 1, False, "", started)
        return value

    def _recover_and_replay(self, system: str, account_ref: str, operation: Callable[[], Any],
                            *, kind: str, generation: int, started: datetime) -> Any:
        try:
            self.renew(system, account_ref=account_ref, generation=generation, since=started)
        except SessionRecoveryError as error:
            self._record_operation(system, kind, 1, False, error.code, started)
            raise
        if kind == UNSAFE_SIDE_EFFECT:
            # 裁决 Q3：默认不重放；续期只为让后续操作可用，本操作交由用户确认。
            error = GenerationUnknown(system=system)
            self._note(error)
            self._record_operation(system, kind, 1, False, error.code, started)
            raise error
        if self._registry.generation(system) != generation:
            error = SessionCleared(system=system)
            self._note(error)
            self._record_operation(system, kind, 1, False, error.code, started)
            raise error
        try:
            value = operation()
        except Exception as exc:  # noqa: BLE001
            if _is_cancellation(exc):
                raise
            classified = self.classify(exc, system=system)
            if isinstance(classified, SessionExpired):
                # §6.2 末行：同一业务操作第 2 次遇到 401，不再续期、不再重放。
                classified.replayed = True
                self._note(classified)
                self._record_operation(system, kind, 2, True, classified.code, started)
                raise classified from None
            error = self._business_error(classified, kind=kind, exc=exc)
            error.replayed = True
            self._note(error)
            self._record_operation(system, kind, 2, True, error.code, started)
            raise error from None
        self._record_operation(system, kind, 2, True, "", started)
        return value

    def _business_error(self, error: SessionRecoveryError, *, kind: str,
                        exc: BaseException) -> SessionRecoveryError:
        """无响应的副作用操作升级为 ``generation_unknown``（§4.1-6 / §6.4）。"""
        if kind == UNSAFE_SIDE_EFFECT and isinstance(error, UpstreamUnavailable) \
                and _status_code_of(exc) is None:
            return GenerationUnknown(system=error.system, replayed=error.replayed)
        return error

    # ── 错误分类（§4.1 判定顺序，命中即停）────────────────────────────────

    def classify(self, exc: BaseException, *, system: str) -> SessionRecoveryError:
        if isinstance(exc, SessionRecoveryError):
            return exc
        stage = getattr(exc, "stage", None)
        stage_code = _STAGE_CODES.get(stage) if isinstance(stage, str) else None
        if stage_code:
            return _error_for(stage_code, system=system, exc=exc)
        status = _status_code_of(exc)
        if status == 401:
            return SessionExpired("unauthenticated", system=system, detail=_detail_of(exc))
        if status == 403:
            return Forbidden(system=system, detail=_detail_of(exc))
        if status == 429 or (status is not None and 500 <= status <= 599):
            return UpstreamUnavailable("service_unavailable", system=system, detail=_detail_of(exc))
        if status is not None:
            # 已收到响应但契约不符（其它 4xx/未预期状态）→ parse（§4.1-5）。
            return UpstreamParseError(system=system, detail=_detail_of(exc))
        cause = exc.__cause__
        if cause is not None and _is_transport(cause) and _status_code_of(cause) is None:
            code = "timeout" if _is_timeout(cause) or _is_timeout(exc) else "service_unavailable"
            return _error_for(code, system=system, exc=exc)
        names = _names(exc)
        if "ArasAuthenticationError" in names:
            return SessionExpired("unauthenticated", system=system, detail=_detail_of(exc))
        if names & {"ArasAuthError", "TDCAuthError"}:
            # 登录链失败且无阶段/状态信息 → renewal_rejected（禁止自动再试）。
            return RenewalRejected("credential_invalid", system=system, detail=_detail_of(exc))
        if _is_timeout(exc):
            return UpstreamUnavailable("timeout", system=system, detail=_detail_of(exc))
        if _is_transport(exc):
            return UpstreamUnavailable("service_unavailable", system=system, detail=_detail_of(exc))
        if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
            return UpstreamParseError(system=system, detail=_detail_of(exc))
        # 未知异常不伪装成"已确认无副作用"：按 network 类返回，且协调器永不因此重放。
        return UpstreamUnavailable("service_unavailable", system=system)

    # ── 清除 ─────────────────────────────────────────────────────────────

    def clear(self, system: str | None = None) -> dict[str, SessionSnapshot]:
        """清除会话：代次 +1 → 取消在途续期 → 移除会话（§7.2-1）。"""
        if system is not None:
            self._require_system(system)
        targets = SYSTEMS if system is None else (system,)
        self._registry.clear(system)
        with self._lock:
            for name in targets:
                for key, flight in list(self._flights.items()):
                    if key[0] != name or flight.done.is_set():
                        continue
                    flight.error = SessionCleared(system=name)
                    flight.done.set()
                    # 已取消的续期移出单飞表：此后同键新请求走自己的检查，不加入旧航班。
                    self._flights.pop(key, None)
                for key in [k for k in self._failures if k[0] == name]:
                    self._failures.pop(key, None)
                    self._last_failure_at.pop(key, None)
                    self._attempts.pop(key, None)
        return {name: self.snapshot(name) for name in targets}

    # ── 内部：账号锁定防护（§5.3-6 / D9）──────────────────────────────────

    def _guard_auto_attempt(self, system: str, account_ref: str) -> None:
        key = (system, account_ref)
        now = self._now()
        with self._lock:
            failures = self._failures.get(key, 0)
            last = self._last_failure_at.get(key)
            attempts = [value for value in self._attempts.get(key, [])
                        if now - value < self._attempt_window]
            self._attempts[key] = attempts
        if failures >= self._max_auto_attempts:
            raise RenewalRejected("login_locked", system=system)
        if failures and last is not None:
            index = min(failures, len(self._cooldown_seconds)) - 1
            if now - last < timedelta(seconds=self._cooldown_seconds[index]):
                raise RenewalRejected("login_locked", system=system)
        if len(attempts) >= self._max_auto_attempts:
            raise RenewalRejected("login_locked", system=system)

    def _record_attempt(self, system: str, account_ref: str) -> None:
        with self._lock:
            self._attempts.setdefault((system, account_ref), []).append(self._now())

    def _count_failure(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._failures[key] = self._failures.get(key, 0) + 1
            self._last_failure_at[key] = self._now()

    def _reset_attempts(self, system: str, account_ref: str) -> None:
        key = (system, account_ref)
        with self._lock:
            self._failures.pop(key, None)
            self._last_failure_at.pop(key, None)
            self._attempts.pop(key, None)

    def _reset_if_manual_login(self, system: str, account_ref: str) -> None:
        """手动登录成功即清零失败计数（§5.3-6）：以记录 updatedAt 晚于最后失败为准。"""
        updated = self._registry.record_updated_at(system)
        if updated is None:
            return
        key = (system, account_ref)
        with self._lock:
            last = self._last_failure_at.get(key)
            if last is None or updated <= last:
                return
        self._reset_attempts(system, account_ref)

    # ── 内部：失败收尾、诊断与工具 ────────────────────────────────────────

    def _renewal_failure(self, exc: BaseException, *, system: str,
                         key: tuple[str, str]) -> SessionRecoveryError:
        error = self.classify(exc, system=system)
        if isinstance(error, (CredentialUnavailable, RenewalRejected, UpstreamParseError)):
            self._registry.mark_failed(system, error.code)
        elif isinstance(error, SessionCleared):
            pass  # clear() 已置 cleared，绝不回退
        else:
            self._registry.end_renewal(system, error_code=error.code)
        if isinstance(error, (RenewalRejected, UpstreamParseError)) \
                and error.code != "login_locked":
            # login_locked 是本地冷却闸门合成的，不构成新的登录尝试。
            self._count_failure(key)
        self._note(error)
        return error

    def _note(self, error: SessionRecoveryError) -> None:
        with self._lock:
            self._diagnostics[error.code] = self._diagnostics.get(error.code, 0) + 1
        # 闭集元数据：只报 outcome 与 code（code 经 safe_metadata 白名单外会被指纹化，
        # 因此可读计数保存在 diagnostic_counts()，事件本身只作时间线标记）。
        emit("result", {"outcome": "failed"}, name="session_recovery.error")

    def _record_operation(self, system: str, kind: str, attempt: int, replayed: bool,
                          code: str, started: datetime) -> None:
        elapsed_ms = max(0.0, (self._now() - started).total_seconds() * 1000.0)
        with self._lock:
            self._last_operation = {
                "system": system,
                "kind": kind,
                "attempt": attempt,
                "replayed": bool(replayed),
                "code": code or None,
            }
        emit(
            "result",
            {
                # safe_metadata 白名单外键会被投影丢弃：用闭集 outcome=retry + attempt=2
                # 作为"发生了重放"的可读信号；replayed 布尔保存在 last_operation()。
                "outcome": "retry" if replayed else ("success" if not code else "failed"),
                "attempt": attempt,
                "elapsed_ms": elapsed_ms,
            },
            name="session_recovery.operation",
        )

    def _credentials_available(self) -> bool:
        try:
            return bool(self._provider.is_available(self._credential_ref))
        except Exception:  # noqa: BLE001 - 凭据库异常等同"不可用"，不改变业务结果
            return False

    def _client_factory(self, system: str) -> Callable[[], Any] | None:
        factory = self._clients.get(system)
        return factory if callable(factory) else None

    @staticmethod
    def _require_system(system: str) -> None:
        if system not in SYSTEMS:
            raise ValueError("unsupported enterprise system")

    @staticmethod
    def _renewal_ttl(result: Any) -> timedelta | None:
        expires_in = getattr(result, "token_expires_in", None)
        if type(expires_in) is not int or expires_in <= 0:
            return None  # Aras 未提供 expires_in：沿用注册表 8h TTL
        seconds = max(1.0, float(expires_in) - _TTL_SAFETY_SECONDS)
        return min(_MAX_TTL, timedelta(seconds=seconds))
