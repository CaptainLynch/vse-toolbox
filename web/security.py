# -*- coding: utf-8 -*-
"""本机 Web 安全集中接入（C7 契约，W16-03；启动票据传递与受控重开 DSH-V2-03）。

三层防线全部集中在本模块，路由层不再各自维护安全判定：

1. 启动票据（ticket）：启动器向 app 申请一次性票据（32 字节 urlsafe，TTL ≤10 秒，
   单次消费），经**继承的环境变量**交给窗口子进程，再由 pywebview ``js_api`` 桥交给
   页面；票据从不进入 URL 查询串、argv、浏览器历史或日志。旧启动器（2.3.x）的
   ``?boot=`` 兼容读取由 ``capabilities.legacyBootQuery`` 控制，默认保持开启。
2. 窗口授权（grant）：无注入通道（Edge app / 默认浏览器）时，启动器用**只存在于 app
   子进程环境里的启动器密钥**预置一张一次性授权，页面在严格同源条件下领取会话。
3. 会话 Cookie + 窗口标记 Cookie：``vse_session`` 12 小时；``vse_window`` 30 天，
   仅用于 12 小时过期后的一键恢复（服务端内存态，app 重启即失效）。
4. 写操作防护四件套：会话有效 + Host 头 loopback + Origin 必须存在且严格同源
   （以 Origin 严格校验替代 CSRF token，C7 允许）+ Cookie 受 SameSite=Strict 保护。

fail-closed：任何一步拿不到（票据无效/过期/重放、授权缺失/过期/重放、会话缺失、
Origin 缺失/不匹配）都不放行写操作；读请求维持既有 loopback + Host +
Origin-when-present 防线（supervisor 健康探测与页面静态加载不受影响）。

会话/票据/授权/标记均为 per-app 实例状态（实例锁保护），不是模块级单例——多个 app
实例（测试）之间绝不串味；服务重启即全体失效，属预期 fail-closed 行为。

日志纪律：票据、``grantId``、``vse_session``/``vse_window`` 值、``VSE_LAUNCH_SECRET``
一律不写日志；``boot-exchange`` 失败只累计计数，不记录收到的值。
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

from web.crawler_boot import _loopback_hostname, _origin_tuple

SESSION_COOKIE_NAME = "vse_session"
WINDOW_COOKIE_NAME = "vse_window"
SESSION_TTL_SECONDS = 12 * 3600
#: 窗口标记：30 天，允许在 12 小时会话过期后单独换一张新会话（主控裁决 3）。
WINDOW_MARKER_TTL_SECONDS = 30 * 24 * 3600
BOOT_TICKET_TTL_SECONDS = 10
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BOOT_EXCHANGE_PATH = "/api/security/boot-exchange"
CAPABILITIES_PATH = "/api/security/capabilities"
WINDOW_GRANT_PATH = "/api/security/window-grant"
BOOT_CLAIM_PATH = "/api/security/boot-claim"
SESSION_RECOVER_PATH = "/api/security/session-recover"
LAUNCHER_SECRET_HEADER = "X-VSE-Launch-Secret"
EPOCH_HEADER = "X-VSE-Epoch"
SECURITY_CONTRACT_VERSION = 1

#: 票据存储上限（超出按最早签发淘汰，见契约 §7.1）。
MAX_PENDING_TICKETS = 8
#: 窗口授权 TTL 与取值域（契约 §6.3）。
GRANT_TTL_SECONDS = BOOT_TICKET_TTL_SECONDS
GRANT_PURPOSES = frozenset({"open", "reopen", "recover"})
GRANT_DELIVERIES = frozenset({"env", "claim"})

#: 速率限制（契约 §5.11）：滑动窗口 60 秒。
RATE_WINDOW_SECONDS = 60.0
BOOT_EXCHANGE_FAILURE_LIMIT = 10
GRANT_CALL_LIMIT = 6
CLAIM_CALL_LIMIT = 10
RECOVERY_CALL_LIMIT = 6

#: 不需要既有会话的端点：各自用票据 / 启动器密钥 / 预置授权 / 窗口标记认证。
SESSIONLESS_PATHS = frozenset(
    {BOOT_EXCHANGE_PATH, WINDOW_GRANT_PATH, BOOT_CLAIM_PATH, SESSION_RECOVER_PATH}
)


#: 统一错误信封（与既有 {ok,error:{type,message}} 一致；类型码属 C8 演进允许范围）。
def _security_error(status: int, error_type: str, message: str):
    response = jsonify({"ok": False, "error": {"type": error_type, "message": message}})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _no_store(response):
    """新端点一律不缓存（契约 §5.11 补充冻结）。"""
    response.headers["Cache-Control"] = "no-store"
    return response


class BootTicketStore:
    """一次性启动票据：多张并存（上限 8），每张 TTL 内可消费一次，过期/重放一律拒绝。

    消费以 ``secrets.compare_digest`` 值匹配为前提——不知道票据的请求无法「烧掉」任何
    票据（跨源请求不能把凭证消耗掉，见契约 §5.11 校验顺序）。
    """

    def __init__(self, token: str | None = None, ttl_seconds: int = BOOT_TICKET_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._tickets: dict[str, float] = {}
        self._lock = threading.Lock()
        if token:
            self.issue(token)

    def issue(self, token: str | None = None) -> str:
        """签发一张票据（``token`` 仅用于兼容既有调用点的确定性值）。"""
        value = token or secrets.token_urlsafe(32)
        with self._lock:
            now = time.monotonic()
            self._drop_expired(now)
            self._tickets[value] = now
            while len(self._tickets) > MAX_PENDING_TICKETS:
                oldest = min(self._tickets, key=lambda item: self._tickets[item])
                self._tickets.pop(oldest, None)
        return value

    def consume(self, candidate: str | None) -> bool:
        if not isinstance(candidate, str) or not candidate:
            return False
        probe = candidate.encode("utf-8", "surrogatepass")
        with self._lock:
            now = time.monotonic()
            matched: str | None = None
            for token in self._tickets:
                if secrets.compare_digest(token.encode("utf-8"), probe):
                    matched = token
                    break
            if matched is None:
                return False
            issued_at = self._tickets.pop(matched)  # 单次：命中即消费，过期也一并作废
            return now - issued_at <= self._ttl

    def _drop_expired(self, now: float) -> None:
        for token in [name for name, issued in self._tickets.items() if now - issued > self._ttl]:
            self._tickets.pop(token, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._tickets)


@dataclass(frozen=True)
class WindowGrant:
    """一张待领取的窗口授权；``ticket`` 只在 ``delivery="env"`` 时存在。"""

    grant_id: str
    delivery: str
    ticket: str | None
    issued_at: float


class WindowGrantStore:
    """最多 1 张待领取授权；新授权 supersede 旧授权；claimed/过期即失效（契约 §7.2）。

    ``grantId`` 从不回传给浏览器：页面只发 ``POST boot-claim``，由服务端把「唯一的
    待领取授权」兑换成会话。
    """

    def __init__(self, ttl_seconds: int = GRANT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._grant: WindowGrant | None = None
        self._lock = threading.Lock()

    def arm(self, delivery: str, ticket: str | None = None) -> WindowGrant:
        grant = WindowGrant(
            grant_id="grt_" + secrets.token_urlsafe(18),
            delivery=delivery,
            ticket=ticket,
            issued_at=time.monotonic(),
        )
        with self._lock:
            self._grant = grant
        return grant

    def claim(self) -> tuple[str, WindowGrant | None]:
        """返回 ``("ok"|"expired"|"missing", grant)``；``ok`` 时授权被消费。"""
        with self._lock:
            grant = self._grant
            if grant is None:
                return "missing", None
            if time.monotonic() - grant.issued_at > self._ttl:
                self._grant = None  # 过期项随即删除
                return "expired", None
            if grant.delivery != "claim":
                # delivery="env" 的授权只用于宿主注入票据，不可被页面 claim（409）。
                return "missing", None
            self._grant = None
            return "ok", grant


class LocalSessionStore:
    """本机会话：随机 Cookie 值 → 过期时间；内存态，重启即全体失效。"""

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        value = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[value] = time.monotonic() + self._ttl
        return value

    def validate(self, cookie_value: str | None) -> bool:
        if not cookie_value:
            return False
        with self._lock:
            expires = self._sessions.get(cookie_value)
            if expires is None:
                return False
            if time.monotonic() > expires:
                del self._sessions[cookie_value]
                return False
            return True


class WindowMarkerStore:
    """窗口标记（``vse_window``）：30 天绝对有效期，只用于一键恢复会话。

    恢复**不续期、不重设** Cookie（契约 §5.8/§7.4）；app 重启即全体失效。
    """

    def __init__(self, ttl_seconds: int = WINDOW_MARKER_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._markers: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        value = secrets.token_urlsafe(32)
        with self._lock:
            self._markers[value] = time.monotonic() + self._ttl
        return value

    def validate(self, cookie_value: str | None) -> bool:
        if not cookie_value:
            return False
        with self._lock:
            expires = self._markers.get(cookie_value)
            if expires is None:
                return False
            if time.monotonic() > expires:
                del self._markers[cookie_value]
                return False
            return True


class RateLimiter:
    """滑动窗口计数器：窗口内事件数达到上限即拒绝（契约 §5.11 速率列）。"""

    def __init__(self, limit: int, window_seconds: float = RATE_WINDOW_SECONDS) -> None:
        self._limit = limit
        self._window = window_seconds
        self._events: list[float] = []
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        self._events = [stamp for stamp in self._events if now - stamp < self._window]

    def exceeded(self) -> bool:
        with self._lock:
            self._prune(time.monotonic())
            return len(self._events) >= self._limit

    def record(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._events.append(now)

    def allow(self) -> bool:
        """记一次调用；返回 False 表示已超限（调用方应回 429，且本次不计数）。"""
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True


class LocalWebSecurity:
    """C7 三层防线的宿主；create_app 在注册既有 loopback 守卫之后调用 install()。"""

    def __init__(
        self,
        boot_token: str | None = None,
        *,
        launcher_secret: str | None = None,
        accept_legacy_boot_query: bool = True,
    ) -> None:
        #: 本次进程生命周期标识；会话/标记/授权/票据都绑定它（契约 §5.1）。
        self.epoch = secrets.token_hex(8)
        #: 启动器密钥：只经环境变量进入 app 子进程，不落盘、不进 argv、不进日志。
        self.launcher_secret = str(launcher_secret or "")
        #: 旧启动器（2.3.x）的 ``?boot=`` 兼容读取开关；默认 true（主控裁决 5）。
        self.accept_legacy_boot_query = bool(accept_legacy_boot_query)
        self.tickets = BootTicketStore()
        self.boot_token = self.tickets.issue(boot_token) if boot_token else self.tickets.issue()
        self.sessions = LocalSessionStore()
        self.markers = WindowMarkerStore()
        self.grants = WindowGrantStore()
        self.exchange_limiter = RateLimiter(BOOT_EXCHANGE_FAILURE_LIMIT)
        self.grant_limiter = RateLimiter(GRANT_CALL_LIMIT)
        self.claim_limiter = RateLimiter(CLAIM_CALL_LIMIT)
        self.recover_limiter = RateLimiter(RECOVERY_CALL_LIMIT)

    def install(self, app: Flask) -> None:
        app.config["VSE_BOOT_TOKEN"] = self.boot_token
        app.config["VSE_SECURITY_CONTRACT"] = SECURITY_CONTRACT_VERSION
        app.extensions["local_web_security"] = self

        @app.before_request
        def _enforce_local_session():  # pragma: no cover - 闭包注册，见下方函数体
            return self._enforce_session_and_origin()

        @app.post(BOOT_EXCHANGE_PATH)
        def api_security_boot_exchange():  # pragma: no cover - 闭包注册
            return self._boot_exchange()

        @app.get(CAPABILITIES_PATH)
        def api_security_capabilities():  # pragma: no cover - 闭包注册
            return self._capabilities()

        @app.post(WINDOW_GRANT_PATH)
        def api_security_window_grant():  # pragma: no cover - 闭包注册
            return self._window_grant()

        @app.post(BOOT_CLAIM_PATH)
        def api_security_boot_claim():  # pragma: no cover - 闭包注册
            return self._boot_claim()

        @app.post(SESSION_RECOVER_PATH)
        def api_security_session_recover():  # pragma: no cover - 闭包注册
            return self._session_recover()

    # ── boot-exchange（保留：响应体逐字冻结） ─────────────────────────
    def _boot_exchange(self):
        if self.exchange_limiter.exceeded():
            return _security_error(429, "BootExchangeRateLimited", "启动票据校验失败次数过多，请稍后再试")
        payload = request.get_json(silent=True) or {}
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not self.tickets.consume(token):
            # 无效/过期/重放统一同一错误，不给枚举线索；只记计数，不记收到的值。
            self.exchange_limiter.record()
            return _security_error(401, "BootTicketInvalid", "启动票据无效或已过期，请重新打开应用")
        response = jsonify({"ok": True, "data": {"exchanged": True}})
        self._set_session_cookie(response)
        self._set_window_cookie(response)
        response.headers[EPOCH_HEADER] = self.epoch
        return _no_store(response)

    # ── capabilities ─────────────────────────────────────────────────
    def _capabilities(self):
        data = {
            "contractVersion": SECURITY_CONTRACT_VERSION,
            "grantArm": True,
            "windowInjection": True,
            "legacyBootQuery": self.accept_legacy_boot_query,
            "handoffFile": False,
            "ticketTtlSeconds": BOOT_TICKET_TTL_SECONDS,
            "sessionTtlSeconds": SESSION_TTL_SECONDS,
            "epoch": self.epoch,
        }
        return _no_store(jsonify({"ok": True, "data": data}))

    # ── window-grant（启动器密钥认证） ────────────────────────────────
    def _window_grant(self):
        if not self._launcher_authenticated():
            # 未配置密钥（开发态未设置 / 旧 app）一律拒绝：不存在「无密钥即放行」分支。
            return _security_error(401, "LauncherAuthRequired", "缺少有效的启动器密钥")
        source = self._require_same_origin()
        if source is not None:
            return source
        if not self.grant_limiter.allow():
            return _security_error(429, "GrantRateLimited", "窗口授权预置过于频繁，请稍后再试")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _security_error(400, "ValidationError", "请求体必须是 JSON 对象")
        purpose = payload.get("purpose")
        delivery = payload.get("delivery")
        if purpose not in GRANT_PURPOSES or delivery not in GRANT_DELIVERIES:
            return _security_error(400, "ValidationError", "purpose 或 delivery 取值非法")
        ticket = self.tickets.issue() if delivery == "env" else None
        grant = self.grants.arm(delivery, ticket=ticket)
        data: dict[str, Any] = {
            "grantId": grant.grant_id,
            "delivery": grant.delivery,
            "expiresAt": int(time.time()) + GRANT_TTL_SECONDS,
            "ttlSeconds": GRANT_TTL_SECONDS,
            "epoch": self.epoch,
        }
        if ticket is not None:
            data["ticket"] = ticket  # delivery="claim" 时该键不存在（而非空串）
        return _no_store(jsonify({"ok": True, "data": data}))

    # ── boot-claim（预置授权 → 会话） ────────────────────────────────
    def _boot_claim(self):
        source = self._require_same_origin_and_same_site()
        if source is not None:
            return source
        if self.sessions.validate(request.cookies.get(SESSION_COOKIE_NAME)):
            # 已有有效会话：不消费授权、不重设 Cookie（刷新页面不能把授权烧掉）。
            return _no_store(
                jsonify({"ok": True, "data": {"exchanged": False, "sessionValid": True, "epoch": self.epoch}})
            )
        if not self.claim_limiter.allow():
            return _security_error(429, "ClaimRateLimited", "领取会话过于频繁，请稍后再试")
        outcome, _grant = self.grants.claim()
        if outcome == "expired":
            return _security_error(401, "GrantExpired", "窗口授权已过期，请重新打开应用")
        if outcome != "ok":
            return _security_error(409, "NoPendingGrant", "没有待领取的窗口授权")
        response = jsonify(
            {
                "ok": True,
                "data": {
                    "exchanged": True,
                    "sessionValid": True,
                    "epoch": self.epoch,
                    "sessionTtlSeconds": SESSION_TTL_SECONDS,
                },
            }
        )
        self._set_session_cookie(response)
        self._set_window_cookie(response)
        return _no_store(response)

    # ── session-recover（窗口标记 → 新会话） ─────────────────────────
    def _session_recover(self):
        source = self._require_same_origin_and_same_site()
        if source is not None:
            return source
        if not self.recover_limiter.allow():
            return _security_error(429, "RecoveryRateLimited", "恢复会话过于频繁，请稍后再试")
        if not self.markers.validate(request.cookies.get(WINDOW_COOKIE_NAME)):
            return _security_error(
                401, "SessionRecoveryUnavailable", "本窗口无法自动恢复会话，请从开始菜单重新打开 VSE Toolbox"
            )
        response = jsonify(
            {"ok": True, "data": {"recovered": True, "sessionTtlSeconds": SESSION_TTL_SECONDS, "epoch": self.epoch}}
        )
        self._set_session_cookie(response)  # 不重设 vse_window：恢复不延长标记有效期
        return _no_store(response)

    # ── 写操作四件套（在既有 loopback/Host 守卫之后执行） ─────────────
    def _enforce_session_and_origin(self):
        if request.method not in WRITE_METHODS:
            return None
        if request.path in SESSIONLESS_PATHS:
            # 这四个端点各自认证（票据 / 启动器密钥 / 预置授权 / 窗口标记），不要求已有会话。
            return None
        if not self.sessions.validate(request.cookies.get(SESSION_COOKIE_NAME)):
            return _security_error(401, "SessionRequired", "本地会话缺失或已失效，请重新打开应用")
        origin = request.headers.get("Origin")
        if not origin:
            # 同站不同端口的页面发跨源写请求必带 Origin；缺失即非浏览器伪造。
            return _security_error(403, "OriginRequired", "写操作缺少来源校验，请在应用窗口内操作")
        expected = self._expected_origin()
        if expected is None or _origin_tuple(origin.strip()) != expected:
            return _security_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
        return None

    # ── 来源 / 认证助手 ──────────────────────────────────────────────
    def _launcher_authenticated(self) -> bool:
        if not self.launcher_secret:
            return False
        header = request.headers.get(LAUNCHER_SECRET_HEADER, "")
        if not header:
            return False
        return secrets.compare_digest(
            header.encode("utf-8", "surrogatepass"),
            self.launcher_secret.encode("utf-8", "surrogatepass"),
        )

    def _require_same_origin(self):
        origin = request.headers.get("Origin")
        if not origin:
            return _security_error(403, "OriginRequired", "缺少来源校验，请在应用窗口内操作")
        expected = self._expected_origin()
        if expected is None or _origin_tuple(origin.strip()) != expected:
            return _security_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
        return None

    def _require_same_origin_and_same_site(self):
        """先完成来源校验再消费授权/标记：跨源请求不能把凭证烧掉（契约 §5.11）。"""
        source = self._require_same_origin()
        if source is not None:
            return source
        if request.headers.get("Sec-Fetch-Site", "").strip().lower() != "same-origin":
            return _security_error(403, "SameSiteRequired", "请求来源不是同源页面")
        return None

    def _expected_origin(self) -> tuple[str, str, int] | None:
        try:
            host_url = urlsplit(f"//{request.host}")
        except ValueError:
            return None
        host_name = (host_url.hostname or "").rstrip(".").lower()
        if not _loopback_hostname(host_name):
            return None
        port = host_url.port or (443 if request.scheme == "https" else 80)
        return request.scheme.lower(), host_name, port

    def _set_session_cookie(self, response) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            self.sessions.issue(),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="Strict",
            path="/",
        )

    def _set_window_cookie(self, response) -> None:
        response.set_cookie(
            WINDOW_COOKIE_NAME,
            self.markers.issue(),
            max_age=WINDOW_MARKER_TTL_SECONDS,
            httponly=True,
            samesite="Strict",
            path="/",
        )


def install_local_security(
    app: Any,
    *,
    boot_token: str | None = None,
    launcher_secret: str | None = None,
    accept_legacy_boot_query: bool = True,
) -> LocalWebSecurity:
    """create_app 装配点：在既有 `_enforce_local_web_access` 之后注册本模块防线。

    顺序保证：Flask before_request 按注册顺序执行——loopback/Host/Sec-Fetch-Site
    先跑（既有行为、读请求也过），本模块的会话/Origin 判定后跑（只影响写）。
    """
    security = LocalWebSecurity(
        boot_token,
        launcher_secret=launcher_secret,
        accept_legacy_boot_query=accept_legacy_boot_query,
    )
    security.install(app)
    install_security_aware_test_client(app)
    return security


# ── 测试基础设施：等价模拟真实浏览器，不旁路任何服务端判定 ──────────────
def install_security_aware_test_client(app: Any) -> None:
    """把 app.test_client() 替换为带浏览器等价行为的客户端。

    - 写请求自动补 `Origin: http://localhost:{FLASK_PORT}`（真实浏览器同源写必带）；
    - 首次写之前用 app.config 里的票据**真实调用** boot-exchange 端点拿会话。
    本类不旁路任何服务端判定；fail-closed 路径（无 Origin/无会话/坏票据）用
    原生 werkzeug Client 直接断言。仅影响测试路径（test_client 只在测试使用），
    生产 WSGI 入口不受影响。
    """
    from flask.testing import FlaskClient

    base = app.test_client_class if app.test_client_class else FlaskClient
    base_open = base.open

    class _SecurityAwareTestClient(base):  # type: ignore[valid-type,misc]
        _bootstrapped = False

        def open(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            method = str(
                kwargs.get("method") or (args[1] if len(args) > 1 else "GET")
            ).upper()
            if method in WRITE_METHODS:
                host = self._outer_host(kwargs)
                self._ensure_bootstrap(host)
                kwargs["headers"] = self._with_origin(kwargs.get("headers"), host)
            return base_open(self, *args, **kwargs)

        def _outer_host(self, kwargs: dict) -> str:
            """外层请求实际使用的 Host（cookie 按 host 隔离，交换须同 host）。"""
            environ = kwargs.get("environ_base") or {}
            if isinstance(environ, dict) and environ.get("HTTP_HOST"):
                return str(environ["HTTP_HOST"])
            headers = kwargs.get("headers") or {}
            if isinstance(headers, dict) and headers.get("Host"):
                return str(headers["Host"])
            return "localhost"

        def _with_origin(self, headers: Any, host: str) -> Any:
            origin = self._origin(host)
            if headers is None:
                return {"Origin": origin}
            if isinstance(headers, dict):
                merged = dict(headers)
                merged.setdefault("Origin", origin)
                return merged
            # （headers, environ）或 Header 对象等罕见形态：原样返回，交由用例自带。
            return headers

        def _origin(self, host: str = "localhost") -> str:
            # 真实浏览器对同源写请求必带 Origin 且端口与 Host 一致；
            # 测试客户端默认 Host 为 "localhost"（省略 80 端口）。
            if host.endswith(":80"):
                host = host[:-3]
            return f"http://{host}"

        def _ensure_bootstrap(self, host: str) -> None:
            if self._bootstrapped:
                return
            self._bootstrapped = True
            token = self.application.config.get("VSE_BOOT_TOKEN")
            if not token:
                return
            base_open(
                self,
                BOOT_EXCHANGE_PATH,
                method="POST",
                json={"token": token},
                headers={"Origin": self._origin(host), "Host": host},
            )

    app.test_client_class = _SecurityAwareTestClient
