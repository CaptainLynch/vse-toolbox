# -*- coding: utf-8 -*-
"""本机 Web 安全集中接入（C7 契约，W16-03）。

三层防线全部集中在本模块，路由层不再各自维护安全判定：

1. 启动交换票据：启动器生成短时（≤10 秒）单次 token，经环境变量传给服务进程、
   经 `?boot=` 查询串传给页面；页面 JS 用它换会话 Cookie 后清除地址栏。
2. 会话 Cookie：`HttpOnly; SameSite=Strict; Path=/`；loopback http 下不设
   `Secure`（浏览器把 127.0.0.1 视为安全上下文，C7 以实测为准）。
3. 写操作防护四件套：会话有效 + Host 头 loopback + Origin 必须存在且严格同源
   （以 Origin 严格校验替代 CSRF token，C7 允许）+ Cookie 受 SameSite=Strict 保护。
   不只检查 remote_addr——同机其他端口的本地页面同属 localhost 源。

fail-closed：任何一步拿不到（票据无效/过期/重放、会话缺失、Origin 缺失/不匹配）
都不放行写操作；读请求维持既有 loopback + Host + Origin-when-present 防线
（supervisor 健康探测与页面静态加载不受影响）。

会话与票据均为 per-app 实例状态（实例锁保护），不是模块级单例——多个 app
实例（测试）之间绝不串味；服务重启即全体失效，属预期 fail-closed 行为。
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

from web.crawler_boot import _loopback_hostname, _origin_tuple

SESSION_COOKIE_NAME = "vse_session"
SESSION_TTL_SECONDS = 12 * 3600
BOOT_TICKET_TTL_SECONDS = 10
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BOOT_EXCHANGE_PATH = "/api/security/boot-exchange"

#: 统一错误信封（与既有 {ok,error:{type,message}} 一致；类型码属 C8 演进允许范围）。
def _security_error(status: int, error_type: str, message: str):
    response = jsonify({"ok": False, "error": {"type": error_type, "message": message}})
    response.status_code = status
    return response


class BootTicketStore:
    """一次性启动票据：签发后 TTL 内可消费一次，过期/重放一律拒绝。"""

    def __init__(self, token: str, ttl_seconds: int = BOOT_TICKET_TTL_SECONDS) -> None:
        self._token = token
        self._ttl = ttl_seconds
        self._issued_at = time.monotonic()
        self._consumed = False
        self._lock = threading.Lock()

    def consume(self, candidate: str) -> bool:
        with self._lock:
            if self._consumed:
                return False
            if time.monotonic() - self._issued_at > self._ttl:
                self._consumed = True  # 过期即作废，不再给第二次机会
                return False
            if not secrets.compare_digest(str(candidate or ""), self._token):
                return False
            self._consumed = True
            return True


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


class LocalWebSecurity:
    """C7 三层防线的宿主；create_app 在注册既有 loopback 守卫之后调用 install()。"""

    def __init__(self, boot_token: str | None = None) -> None:
        self.boot_token = boot_token or secrets.token_urlsafe(32)
        self.tickets = BootTicketStore(self.boot_token)
        self.sessions = LocalSessionStore()

    def install(self, app: Flask) -> None:
        app.config["VSE_BOOT_TOKEN"] = self.boot_token
        app.extensions["local_web_security"] = self

        @app.before_request
        def _enforce_local_session():  # pragma: no cover - 闭包注册，见下方函数体
            return self._enforce_session_and_origin()

        @app.post(BOOT_EXCHANGE_PATH)
        def api_security_boot_exchange():  # pragma: no cover - 闭包注册
            return self._boot_exchange()

    # ── boot-exchange ────────────────────────────────────────────────
    def _boot_exchange(self):
        payload = request.get_json(silent=True) or {}
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not self.tickets.consume(token):
            # 无效/过期/重放统一同一错误，不给枚举线索。
            return _security_error(401, "BootTicketInvalid", "启动票据无效或已过期，请重新打开应用")
        response = jsonify({"ok": True, "data": {"exchanged": True}})
        response.set_cookie(
            SESSION_COOKIE_NAME,
            self.sessions.issue(),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="Strict",
            path="/",
        )
        return response

    # ── 写操作四件套（在既有 loopback/Host 守卫之后执行） ─────────────
    def _enforce_session_and_origin(self):
        if request.method not in WRITE_METHODS:
            return None
        if request.path == BOOT_EXCHANGE_PATH:
            return None  # 交换端点自身靠单次票据防护，不要求已有会话
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


def install_local_security(app: Any, *, boot_token: str | None = None) -> LocalWebSecurity:
    """create_app 装配点：在既有 `_enforce_local_web_access` 之后注册本模块防线。

    顺序保证：Flask before_request 按注册顺序执行——loopback/Host/Sec-Fetch-Site
    先跑（既有行为、读请求也过），本模块的会话/Origin 判定后跑（只影响写）。
    """
    security = LocalWebSecurity(boot_token)
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
