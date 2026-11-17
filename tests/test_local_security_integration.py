# -*- coding: utf-8 -*-
"""C7 本机安全集成验证：真实 HTTP 调用链（W16-03 → DSH-V2-01 → DSH-V2-03）。

与 ``tests/test_local_security.py`` 的分工：那份在进程内用 werkzeug 原生 Client /
等价 test client 覆盖判定分支；本文件起**真实 HTTP 服务**（werkzeug ``make_server``
线程 + 回环随机端口），用 ``http.client`` 发原始请求，Cookie / Origin /
``Sec-Fetch-Site`` / 启动器密钥全部由用例显式给出。

因此本文件**不使用** ``install_security_aware_test_client``（生产代码为测试便利提供、
会自动补 Cookie/Origin 的客户端），也不调用 ``app.test_client()``：任何放行都只能
来自服务端真实判定。

票据来源（契约 §8.4）：**不再**从 ``?boot=`` 地址栏取票。新链路的票据由启动器用
启动器密钥 ``POST /api/security/window-grant`` 现签（``delivery="env"``），
浏览器窗口走 ``delivery="claim"`` 授权 + ``POST /api/security/boot-claim`` 领取。
``?boot=`` 只在场景 ⑧ 作为“旧启动器 + 新 app”的兼容路径出现。

覆盖契约 §9.2 的八个真实 HTTP 场景：

1. 首窗领取会话后写放行（授权 → 会话 Cookie → 写四件套）；
2. 无授权时 ``boot-claim`` 409，且写请求仍然 401（fail-closed）；
3. 授权 10 秒后领取 401 ``GrantExpired``（注入时钟，不真等）；
4. ``boot-claim`` 重放 409，且原会话不被连带作废；
5. 12 小时会话过期 → ``session-recover`` 成功 → 写放行；
6. 窗口标记失效 → ``session-recover`` 401 ``SessionRecoveryUnavailable``；
7. 两个 app 实例的票据/授权/会话/启动器密钥互不通用（绝不串味）；
8. 旧 ``?boot=`` 兼容路径在 ``legacyBootQuery=true`` 下仍可用。

时间推进用注入时钟替换 ``web.security.time``（票据/授权/会话/标记存储唯一的时间源），
不 sleep，也不改产品代码。
"""

from __future__ import annotations

import http.client
import itertools
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from werkzeug.serving import make_server

import web.app as web_app
import web.security as web_security
from web.security import (
    BOOT_CLAIM_PATH,
    BOOT_EXCHANGE_PATH,
    BOOT_TICKET_TTL_SECONDS,
    CAPABILITIES_PATH,
    GRANT_TTL_SECONDS,
    LAUNCHER_SECRET_HEADER,
    SESSION_COOKIE_NAME,
    SESSION_RECOVER_PATH,
    SESSION_TTL_SECONDS,
    WINDOW_COOKIE_NAME,
    WINDOW_GRANT_PATH,
    WINDOW_MARKER_TTL_SECONDS,
)

#: 需要会话 + 同源 Origin 才能到达视图的写路由（空载荷 → 视图层 422 业务校验）。
WRITE_PATH = "/api/project-status/section-rollup"

#: 合成启动器密钥前缀（仅测试用；不是任何真实环境的凭据）。
LAUNCHER_SECRET_PREFIX = "test-only-launcher-secret-"


# ── 注入时钟：web.security 票据/授权/会话/标记存储的唯一时间源 ───────────────


class FakeClock:
    """``web.security`` 里 ``time`` 的替身（单位秒，从 0 起）。"""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return 1_735_689_600.0 + self.now  # 2025-01-01T00:00:00Z（合成时间轴）

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """在 create_app 之前替换时间源，签发时间与到期时间都走它。"""
    fake = FakeClock()
    monkeypatch.setattr(web_security, "time", fake)
    return fake


# ── 原生 HTTP 客户端：Cookie 与 Origin 显式管理，绝不自动补 ─────────────────

_MISSING = object()


@dataclass(frozen=True)
class NativeResponse:
    status: int
    headers: dict[str, str]
    set_cookies: list[str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))

    def data(self) -> dict[str, Any]:
        return self.json()["data"]

    def error_type(self) -> str | None:
        try:
            return self.json()["error"]["type"]
        except (KeyError, TypeError, ValueError):
            return None

    def _set_cookie(self, name: str) -> str | None:
        for header in self.set_cookies:
            if header.partition("=")[0].strip() == name:
                return header
        return None

    def cookie(self, name: str = SESSION_COOKIE_NAME) -> str | None:
        header = self._set_cookie(name)
        if header is None:
            return None
        return header.partition("=")[2].split(";", 1)[0].strip()

    def set_cookie_header(self, name: str = SESSION_COOKIE_NAME) -> str | None:
        return self._set_cookie(name)

    def session_set_cookie(self) -> str | None:
        return self._set_cookie(SESSION_COOKIE_NAME)

    def session_cookie(self) -> str | None:
        return self.cookie(SESSION_COOKIE_NAME)

    def window_cookie(self) -> str | None:
        return self.cookie(WINDOW_COOKIE_NAME)


class NativeClient:
    """``http.client`` 直连：每个请求只带用例显式给出的 Cookie / Origin / 头。"""

    def __init__(self, base_url: str) -> None:
        parts = urlsplit(base_url)
        self.host = parts.hostname or "127.0.0.1"
        self.port = parts.port or 80
        self.origin = f"http://{self.host}:{self.port}"

    def send(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        origin: Any = _MISSING,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> NativeResponse:
        merged = {"Accept": "application/json", "Connection": "close"}
        merged.update(headers or {})
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            merged["Content-Type"] = "application/json"
        if origin is not _MISSING and origin is not None:
            merged["Origin"] = str(origin)
        if cookies:
            merged["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
        connection = http.client.HTTPConnection(self.host, self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=merged)
            raw = connection.getresponse()
            payload = raw.read()
            return NativeResponse(
                status=raw.status,
                headers={name.lower(): value for name, value in raw.getheaders()},
                set_cookies=list(raw.headers.get_all("Set-Cookie") or []),
                body=payload,
            )
        finally:
            connection.close()


# ── 真实服务夹具：回环随机端口 + 独立临时数据库 + 合成启动器密钥 ──────────────


def _legacy_ticket_from_launch_url(url: str) -> str:
    """旧启动器（2.3.x）把票据放进 ``?boot=``；仅场景 ⑧ 的兼容路径使用。"""
    values = parse_qs(urlsplit(url).query).get("boot") or []
    assert len(values) == 1 and values[0], f"旧启动器 URL 必须带唯一票据：{url}"
    return values[0]


class LiveServer:
    def __init__(self, app: Any, server: Any, security: Any, token: str, launcher_secret: str) -> None:
        self.app = app
        self.server = server
        self.security = security
        #: 旧链路的首张票据（app 启动时注册）；只服务 ``?boot=`` 兼容路径。
        self.token = token
        #: 合成启动器密钥：等价于“只存在于 app 子进程环境里的启动器密钥”。
        self.launcher_secret = launcher_secret
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    @property
    def legacy_launch_url(self) -> str:
        return f"{self.base_url}/?boot={self.token}"

    def client(self) -> NativeClient:
        return NativeClient(self.base_url)


class ServerFarm:
    """按需起多个真实 app 实例（各自独立数据库与启动器密钥），用于多实例隔离场景。"""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._tmp_path = tmp_path
        self._started: list[tuple[Any, threading.Thread]] = []
        self._counter = itertools.count(1)
        db_cls = web_app.DatabaseManager
        monkeypatch.setattr(
            web_app,
            "DatabaseManager",
            lambda: db_cls(self._tmp_path / f"local-security-{next(self._counter)}.db"),
        )
        monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)

    def start(self, *, accept_legacy_boot_query: bool = True) -> LiveServer:
        index = next(self._counter)
        launcher_secret = f"{LAUNCHER_SECRET_PREFIX}{index}"
        app = web_app.create_app(
            launcher_secret=launcher_secret,
            accept_legacy_boot_query=accept_legacy_boot_query,
        )
        app.config.update(TESTING=False)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(
            target=server.serve_forever, name="local-security-http", daemon=True
        )
        thread.start()
        self._started.append((server, thread))
        return LiveServer(
            app=app,
            server=server,
            security=app.extensions["local_web_security"],
            token=app.config["VSE_BOOT_TOKEN"],
            launcher_secret=launcher_secret,
        )

    def shutdown(self) -> None:
        for server, thread in reversed(self._started):
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture()
def farm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> Iterator[ServerFarm]:
    # 依赖 clock：时钟替换必须先于 create_app，签发时间才落在替身时间轴上。
    live_farm = ServerFarm(tmp_path, monkeypatch)
    try:
        yield live_farm
    finally:
        live_farm.shutdown()


@pytest.fixture()
def live(farm: ServerFarm) -> LiveServer:
    return farm.start()


# ── 请求助手：全部显式给出凭证，绝不自动补 ─────────────────────────────────


def _exchange(client: NativeClient, token: str, *, cookies: dict[str, str] | None = None):
    return client.send(
        "POST",
        BOOT_EXCHANGE_PATH,
        json_body={"token": token},
        origin=client.origin,
        cookies=cookies,
    )


def _grant(
    client: NativeClient,
    live_server: LiveServer,
    *,
    delivery: str,
    purpose: str = "open",
    secret: str | None = None,
    origin: Any = _MISSING,
):
    """启动器用启动器密钥预置一次性授权（``POST /api/security/window-grant``）。"""
    return client.send(
        "POST",
        WINDOW_GRANT_PATH,
        json_body={"purpose": purpose, "delivery": delivery},
        origin=client.origin if origin is _MISSING else origin,
        headers={LAUNCHER_SECRET_HEADER: live_server.launcher_secret if secret is None else secret},
    )


def _arm_ticket(client: NativeClient, live_server: LiveServer) -> str:
    """新链路的取票方式：启动器现签 ``delivery="env"`` 授权，响应里带票据。"""
    granted = _grant(client, live_server, delivery="env")
    assert granted.status == 200, granted.body
    ticket = granted.data().get("ticket")
    assert isinstance(ticket, str) and ticket, granted.body
    return ticket


def _claim(client: NativeClient, *, cookie: str | None = None, same_site: bool = True):
    headers = {"Sec-Fetch-Site": "same-origin"} if same_site else {}
    cookies = {SESSION_COOKIE_NAME: cookie} if cookie else None
    return client.send(
        "POST",
        BOOT_CLAIM_PATH,
        json_body={},
        origin=client.origin,
        cookies=cookies,
        headers=headers,
    )


def _recover(client: NativeClient, *, marker: str | None = None, same_site: bool = True):
    headers = {"Sec-Fetch-Site": "same-origin"} if same_site else {}
    cookies = {WINDOW_COOKIE_NAME: marker} if marker else None
    return client.send(
        "POST",
        SESSION_RECOVER_PATH,
        json_body={},
        origin=client.origin,
        cookies=cookies,
        headers=headers,
    )


def _write(client: NativeClient, *, cookie: str | None, origin: Any = _MISSING):
    cookies = {SESSION_COOKIE_NAME: cookie} if cookie else None
    return client.send("PUT", WRITE_PATH, json_body={}, origin=origin, cookies=cookies)


# ── 场景 ①：首窗领取会话后写放行 ───────────────────────────────────────────


def test_first_boot_claim_grants_session_and_unlocks_writes(live: LiveServer) -> None:
    client = live.client()

    # 页面首屏是无会话读请求，必须照旧可加载（否则用户连领取授权的 JS 都拿不到）。
    page = client.send("GET", "/")
    assert page.status == 200

    # 启动器预置 delivery="claim" 授权；响应**不含**票据（浏览器拿不到任何票据）。
    granted = _grant(client, live, delivery="claim")
    assert granted.status == 200, granted.body
    data = granted.data()
    assert "ticket" not in data
    assert data["delivery"] == "claim"
    assert data["ttlSeconds"] == GRANT_TTL_SECONDS
    assert data["epoch"] == live.security.epoch

    claimed = _claim(client)
    assert claimed.status == 200, claimed.body
    body = claimed.data()
    assert body["exchanged"] is True and body["sessionValid"] is True
    assert body["sessionTtlSeconds"] == SESSION_TTL_SECONDS

    cookie = claimed.session_cookie()
    assert cookie and len(cookie) >= 32
    set_cookie = claimed.session_set_cookie() or ""
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie
    assert "Path=/" in set_cookie
    assert f"Max-Age={SESSION_TTL_SECONDS}" in set_cookie
    # loopback http：C7 以实测为准，不设 Secure。
    assert "Secure" not in set_cookie
    # 同时下发 30 天的窗口标记（K5 的恢复凭据）。
    window_set_cookie = claimed.set_cookie_header(WINDOW_COOKIE_NAME) or ""
    assert window_set_cookie.startswith(f"{WINDOW_COOKIE_NAME}=")
    assert f"Max-Age={WINDOW_MARKER_TTL_SECONDS}" in window_set_cookie

    # 四件套齐备的写请求穿过安全层，到达视图的业务校验（422，不是 401/403）。
    allowed = _write(client, cookie=cookie, origin=client.origin)
    assert allowed.status == 422, allowed.body
    assert allowed.error_type() == "ValidationError"

    # 同一会话缺 Origin → 仍被拒（上面的 422 不是绕过 Origin 校验换来的）。
    no_origin = _write(client, cookie=cookie, origin=None)
    assert no_origin.status == 403
    assert no_origin.error_type() == "OriginRequired"

    # 无会话的写请求 fail-closed。
    no_session = _write(client, cookie=None, origin=client.origin)
    assert no_session.status == 401
    assert no_session.error_type() == "SessionRequired"

    # 读接口（supervisor 健康探测）不受会话影响。
    assert client.send("GET", "/api/version").status == 200


# ── 场景 ②：无授权时 claim 409 且写 401 ────────────────────────────────────


def test_claim_without_grant_is_409_and_writes_stay_fail_closed(live: LiveServer) -> None:
    client = live.client()

    # 用户直接双击书签/收藏：没有启动器预置的授权。
    claimed = _claim(client)
    assert claimed.status == 409, claimed.body
    assert claimed.error_type() == "NoPendingGrant"
    assert claimed.set_cookies == []

    # 页面照常加载，但写操作仍然 401（绝不退化为无认证访问）。
    assert client.send("GET", "/").status == 200
    denied = _write(client, cookie=None, origin=client.origin)
    assert denied.status == 401
    assert denied.error_type() == "SessionRequired"


# ── 场景 ③：授权 10 秒后 401 GrantExpired（注入时钟） ──────────────────────


def test_grant_expires_after_ten_seconds(live: LiveServer, clock: FakeClock) -> None:
    client = live.client()

    _grant(client, live, delivery="claim")
    clock.advance(GRANT_TTL_SECONDS - 0.1)
    still_valid = _claim(client)
    assert still_valid.status == 200, still_valid.body  # TTL 内仍可领取

    # 另一个窗口：重新预置授权后超过 10 秒才领取。
    _grant(client, live, delivery="claim")
    clock.advance(GRANT_TTL_SECONDS + 0.5)
    expired = _claim(client)
    assert expired.status == 401, expired.body
    assert expired.error_type() == "GrantExpired"
    assert expired.set_cookies == []
    # 过期项已被删除：再次领取回到 409。
    assert _claim(client).status == 409


# ── 场景 ④：claim 重放 409 且原会话不受影响 ────────────────────────────────


def test_claim_replay_is_409_and_keeps_original_session(live: LiveServer) -> None:
    client = live.client()
    _grant(client, live, delivery="claim")

    first = _claim(client)
    assert first.status == 200, first.body
    cookie = first.session_cookie()
    assert cookie

    # 重放（新窗口、无会话 Cookie）：授权已消费 → 409，且不发放第二个会话。
    replay = _claim(client)
    assert replay.status == 409, replay.body
    assert replay.error_type() == "NoPendingGrant"
    assert replay.set_cookies == []

    # 拒绝重放不得以作废正常会话为代价（否则重放就退化成 DoS）。
    assert _write(client, cookie=cookie, origin=client.origin).status == 422

    # 已有有效会话时的 claim 是幂等的 200（exchanged=false），不重设 Cookie。
    idempotent = _claim(client, cookie=cookie)
    assert idempotent.status == 200, idempotent.body
    assert idempotent.data()["exchanged"] is False
    assert idempotent.set_cookies == []


# ── 场景 ⑤：12 小时过期 → recover 成功 → 写放行 ───────────────────────────


def test_session_recovery_after_twelve_hours(live: LiveServer, clock: FakeClock) -> None:
    client = live.client()
    _grant(client, live, delivery="claim")
    claimed = _claim(client)
    assert claimed.status == 200, claimed.body
    cookie = claimed.session_cookie()
    marker = claimed.window_cookie()
    assert cookie and marker

    assert _write(client, cookie=cookie, origin=client.origin).status == 422

    # 12 小时 TTL 越过：同一会话 Cookie 的写请求 fail-closed。
    clock.advance(SESSION_TTL_SECONDS + 1)
    expired = _write(client, cookie=cookie, origin=client.origin)
    assert expired.status == 401
    assert expired.error_type() == "SessionRequired"

    # 窗口标记仍在 30 天有效期内 → 一键恢复成功。
    recovered = _recover(client, marker=marker)
    assert recovered.status == 200, recovered.body
    data = recovered.data()
    assert data["recovered"] is True
    assert data["sessionTtlSeconds"] == SESSION_TTL_SECONDS
    new_cookie = recovered.session_cookie()
    assert new_cookie and new_cookie != cookie
    # 恢复不重设、不延长窗口标记。
    assert recovered.set_cookie_header(WINDOW_COOKIE_NAME) is None

    # 新会话放行写操作。
    assert _write(client, cookie=new_cookie, origin=client.origin).status == 422
    # 旧会话不因恢复而复活。
    assert _write(client, cookie=cookie, origin=client.origin).status == 401


# ── 场景 ⑥：标记失效 → recover 401 ────────────────────────────────────────


def test_session_recovery_unavailable_when_marker_invalid(
    live: LiveServer, clock: FakeClock
) -> None:
    client = live.client()

    # 从未领取过会话的窗口（新 profile / 清过 Cookie）。
    missing = _recover(client)
    assert missing.status == 401
    assert missing.error_type() == "SessionRecoveryUnavailable"
    assert missing.set_cookies == []

    # 未知标记。
    unknown = _recover(client, marker="not-a-real-marker")
    assert unknown.status == 401
    assert unknown.error_type() == "SessionRecoveryUnavailable"

    # 超过 30 天绝对有效期。
    _grant(client, live, delivery="claim")
    marker = _claim(client).window_cookie()
    assert marker
    clock.advance(WINDOW_MARKER_TTL_SECONDS + 1)
    stale = _recover(client, marker=marker)
    assert stale.status == 401
    assert stale.error_type() == "SessionRecoveryUnavailable"

    # 跨源/缺 Sec-Fetch-Site 的恢复请求被拒，且没有把标记烧掉。
    fresh_marker = None
    _grant(client, live, delivery="claim")
    fresh_marker = _claim(client).window_cookie()
    cross = client.send(
        "POST",
        SESSION_RECOVER_PATH,
        json_body={},
        origin="http://evil.example",
        cookies={WINDOW_COOKIE_NAME: fresh_marker or ""},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert cross.status == 403
    assert cross.error_type() == "CrossSiteRequest"
    assert _recover(client, marker=fresh_marker).status == 200


# ── 场景 ⑦：两实例票据/授权/会话/密钥都不串味 ──────────────────────────────


def test_two_app_instances_do_not_share_tickets_grants_or_sessions(farm: ServerFarm) -> None:
    first = farm.start()
    second = farm.start()
    client_a = first.client()
    client_b = second.client()
    assert first.token != second.token
    assert first.launcher_secret != second.launcher_secret
    assert first.security.epoch != second.security.epoch

    # A 的启动器密钥在 B 上无效（B 的密钥不同 → 401，绝不“无密钥即放行”）。
    cross_grant = _grant(client_b, second, delivery="env", secret=first.launcher_secret)
    assert cross_grant.status == 401, cross_grant.body
    assert cross_grant.error_type() == "LauncherAuthRequired"

    # A 的票据在 B 上无效：B 的票据存储不认（per-app 状态）。
    ticket_a = _arm_ticket(client_a, first)
    cross_ticket = _exchange(client_b, ticket_a)
    assert cross_ticket.status == 401
    assert cross_ticket.error_type() == "BootTicketInvalid"

    # A 正常换票（B 的拒绝不消耗 A 的票据）。
    exchanged_a = _exchange(client_a, ticket_a)
    assert exchanged_a.status == 200, exchanged_a.body
    cookie_a = exchanged_a.session_cookie()
    assert cookie_a

    # 同机同 host 不同端口：Cookie 不按端口隔离，A 的会话会被浏览器带给 B。
    # B 的会话存储里没有它 → 必须 fail-closed。
    cross_session = _write(client_b, cookie=cookie_a, origin=client_b.origin)
    assert cross_session.status == 401
    assert cross_session.error_type() == "SessionRequired"

    # A 的待领取授权不能被 B 的页面领取。
    _grant(client_a, first, delivery="claim")
    assert _claim(client_b).status == 409
    claimed_a = _claim(client_a)
    assert claimed_a.status == 200, claimed_a.body

    # 反向：B 领取后，B 的会话在 A 上同样被拒。
    _grant(client_b, second, delivery="claim")
    claimed_b = _claim(client_b)
    assert claimed_b.status == 200, claimed_b.body
    cookie_b = claimed_b.session_cookie()
    assert cookie_b
    assert _write(client_a, cookie=cookie_b, origin=client_a.origin).status == 401

    # 各自的会话在各自实例上可用。
    assert _write(client_a, cookie=cookie_a, origin=client_a.origin).status == 422
    assert _write(client_b, cookie=cookie_b, origin=client_b.origin).status == 422

    # Origin 按监听端口判定：A 的会话配 B 的 Origin → 跨源拒绝。
    wrong_origin = _write(client_a, cookie=cookie_a, origin=client_b.origin)
    assert wrong_origin.status == 403
    assert wrong_origin.error_type() == "CrossSiteRequest"


# ── 场景 ⑧：旧 ?boot= 兼容路径（legacyBootQuery=true） ────────────────────


def test_legacy_boot_query_path_still_works(live: LiveServer) -> None:
    client = live.client()

    capabilities = client.send("GET", CAPABILITIES_PATH)
    assert capabilities.status == 200
    assert capabilities.data()["legacyBootQuery"] is True  # 主控裁决 5：03 保持 true

    # 旧启动器（2.3.x）把票据放进地址栏；前端据此走兼容分支。
    ticket = _legacy_ticket_from_launch_url(live.legacy_launch_url)
    assert ticket == live.token

    exchanged = _exchange(client, ticket)
    assert exchanged.status == 200, exchanged.body
    # 响应体逐字冻结（契约 §6.6）。
    assert exchanged.json() == {"ok": True, "data": {"exchanged": True}}
    cookie = exchanged.session_cookie()
    assert cookie
    assert exchanged.headers.get("cache-control") == "no-store"
    assert exchanged.headers.get("x-vse-epoch") == live.security.epoch
    assert _write(client, cookie=cookie, origin=client.origin).status == 422

    # 已消费的兼容票据重放一律 401（与过期不可区分）。
    replay = _exchange(client, ticket)
    assert replay.status == 401
    assert replay.error_type() == "BootTicketInvalid"


def test_legacy_boot_query_switch_off_is_reported(farm: ServerFarm) -> None:
    """启动器传 VSE_LEGACY_BOOT_QUERY=0 时 capabilities 必须如实报告 false。"""
    server = farm.start(accept_legacy_boot_query=False)
    capabilities = server.client().send("GET", CAPABILITIES_PATH)
    assert capabilities.status == 200
    assert capabilities.data()["legacyBootQuery"] is False
    # 关闭的只是前端兼容读取；服务端票据语义不因开关收窄（契约 §8.2-3）。
    assert _exchange(server.client(), server.token).status == 200


# ── 补充：新链路票据 TTL 与重放（原“10 秒后重开”断言的等价覆盖） ───────────


def test_injected_ticket_still_valid_just_before_ten_seconds(
    live: LiveServer, clock: FakeClock
) -> None:
    client = live.client()
    ticket = _arm_ticket(client, live)
    clock.advance(BOOT_TICKET_TTL_SECONDS - 0.1)
    response = _exchange(client, ticket)
    assert response.status == 200, response.body
    assert response.session_cookie()


def test_injected_ticket_replay_is_rejected(live: LiveServer) -> None:
    client = live.client()
    ticket = _arm_ticket(client, live)

    first = _exchange(client, ticket)
    assert first.status == 200, first.body
    cookie = first.session_cookie()
    assert cookie

    # 重放：带不带原会话都拒绝，且不发放第二个会话。
    for cookies in (None, {SESSION_COOKIE_NAME: cookie}):
        replay = _exchange(client, ticket, cookies=cookies)
        assert replay.status == 401, (cookies, replay.body)
        assert replay.error_type() == "BootTicketInvalid"
        assert replay.set_cookies == []

    # 拒绝重放不得以作废正常会话为代价。
    assert _write(client, cookie=cookie, origin=client.origin).status == 422
