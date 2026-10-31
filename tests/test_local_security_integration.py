# -*- coding: utf-8 -*-
"""C7 本机安全集成验证：真实 HTTP 调用链（W16-03 后续，DSH-V2-01）。

与 ``tests/test_local_security.py`` 的分工：那份在进程内用 werkzeug 原生 Client /
等价 test client 覆盖判定分支；本文件起**真实 HTTP 服务**（werkzeug ``make_server``
线程 + 回环随机端口），用 ``http.client`` 发原始请求，Cookie 与 Origin 全部由用例
显式给出。

因此本文件**不使用** ``install_security_aware_test_client``（生产代码为测试便利提供、
会自动补 Cookie/Origin 的客户端），也不调用 ``app.test_client()``：任何放行都只能
来自服务端真实判定。

覆盖契约 C7 的五个场景：

1. 首次启动：启动器给出的 ``?boot=`` 票据 → ``POST /api/security/boot-exchange``
   换会话 Cookie → 写请求四件套（会话 + Host + Origin）放行到视图；
2. 10 秒后重开：票据 TTL（≤10s）到期，同一 ``?boot=`` 重开被拒（注入时钟，不真等）；
3. 票据重放：已消费票据再次交换被拒，且拿不到新会话、原会话不被连带作废；
4. 会话过期：12 小时 TTL 越过之后同一 Cookie 的写请求 fail-closed（注入时钟）；
5. 多 app 隔离：两个实例的票据与会话互不通用（per-app 状态，绝不串味）。

时间推进用注入时钟替换 ``web.security.time``（票据/会话存储唯一的时间源），
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
    BOOT_EXCHANGE_PATH,
    BOOT_TICKET_TTL_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
)

#: 需要会话 + 同源 Origin 才能到达视图的写路由（空载荷 → 视图层 422 业务校验）。
WRITE_PATH = "/api/project-status/section-rollup"


# ── 注入时钟：web.security 票据/会话存储的唯一时间源 ────────────────────────


class FakeClock:
    """``web.security`` 里 ``time.monotonic`` 的替身（单位秒，从 0 起）。"""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """在 create_app 之前替换时间源，票据签发时间与会话到期时间都走它。"""
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

    def error_type(self) -> str | None:
        try:
            return self.json()["error"]["type"]
        except (KeyError, TypeError, ValueError):
            return None

    def session_set_cookie(self) -> str | None:
        for header in self.set_cookies:
            if header.partition("=")[0].strip() == SESSION_COOKIE_NAME:
                return header
        return None

    def session_cookie(self) -> str | None:
        header = self.session_set_cookie()
        if header is None:
            return None
        return header.partition("=")[2].split(";", 1)[0].strip()


class NativeClient:
    """``http.client`` 直连：每个请求只带用例显式给出的 Cookie / Origin。"""

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
    ) -> NativeResponse:
        headers = {"Accept": "application/json", "Connection": "close"}
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if origin is not _MISSING and origin is not None:
            headers["Origin"] = str(origin)
        if cookies:
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
        connection = http.client.HTTPConnection(self.host, self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers)
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


# ── 真实服务夹具：回环随机端口 + 独立临时数据库 ────────────────────────────


def _ticket_from_launch_url(url: str) -> str:
    """启动器把票据放进 ``?boot=``；浏览器 JS 从这里取票（不读任何内部状态）。"""
    values = parse_qs(urlsplit(url).query).get("boot") or []
    assert len(values) == 1 and values[0], f"启动 URL 必须带唯一票据：{url}"
    return values[0]


class LiveServer:
    def __init__(self, app: Any, server: Any, security: Any, token: str) -> None:
        self.app = app
        self.server = server
        self.security = security
        self.token = token
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    @property
    def launch_url(self) -> str:
        return f"{self.base_url}/?boot={self.token}"

    def client(self) -> NativeClient:
        return NativeClient(self.base_url)


class ServerFarm:
    """按需起多个真实 app 实例（各自独立数据库），用于多实例隔离场景。"""

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

    def start(self) -> LiveServer:
        app = web_app.create_app()
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
        )

    def shutdown(self) -> None:
        for server, thread in reversed(self._started):
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture()
def farm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> Iterator[ServerFarm]:
    # 依赖 clock：时钟替换必须先于 create_app，票据签发时间才落在替身时间轴上。
    live_farm = ServerFarm(tmp_path, monkeypatch)
    try:
        yield live_farm
    finally:
        live_farm.shutdown()


@pytest.fixture()
def live(farm: ServerFarm) -> LiveServer:
    return farm.start()


def _exchange(client: NativeClient, token: str, *, cookies: dict[str, str] | None = None):
    return client.send(
        "POST",
        BOOT_EXCHANGE_PATH,
        json_body={"token": token},
        origin=client.origin,
        cookies=cookies,
    )


def _write(client: NativeClient, *, cookie: str | None, origin: Any = _MISSING):
    cookies = {SESSION_COOKIE_NAME: cookie} if cookie else None
    return client.send("PUT", WRITE_PATH, json_body={}, origin=origin, cookies=cookies)


# ── 场景 1：首次启动（?boot= → 会话 Cookie → 写请求放行） ──────────────────


def test_first_boot_exchange_grants_session_and_unlocks_writes(live: LiveServer) -> None:
    client = live.client()
    assert len(live.token) >= 32

    # 页面首屏是无会话读请求，必须照旧可加载（否则用户连交换票据的 JS 都拿不到）。
    page = client.send("GET", "/")
    assert page.status == 200

    # 启动器 URL 里的票据 → 真实 HTTP 交换。
    ticket = _ticket_from_launch_url(live.launch_url)
    exchanged = _exchange(client, ticket)
    assert exchanged.status == 200, exchanged.body
    assert exchanged.json() == {"ok": True, "data": {"exchanged": True}}

    cookie = exchanged.session_cookie()
    assert cookie and len(cookie) >= 32
    set_cookie = exchanged.session_set_cookie() or ""
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie
    assert "Path=/" in set_cookie
    assert f"Max-Age={SESSION_TTL_SECONDS}" in set_cookie
    # loopback http：C7 以实测为准，不设 Secure。
    assert "Secure" not in set_cookie

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


# ── 场景 2：10 秒后重开（票据 TTL 到期，注入时钟不真等） ───────────────────


def test_boot_ticket_still_valid_just_before_ten_seconds(
    live: LiveServer, clock: FakeClock
) -> None:
    client = live.client()
    ticket = _ticket_from_launch_url(live.launch_url)
    assert ticket == live.token  # 提取正确，排除"用错票据也 401"的假阳性
    clock.advance(BOOT_TICKET_TTL_SECONDS - 0.1)
    response = _exchange(client, ticket)
    assert response.status == 200, response.body
    assert response.session_cookie()


def test_reopen_after_ten_seconds_is_rejected(live: LiveServer, clock: FakeClock) -> None:
    client = live.client()
    ticket = _ticket_from_launch_url(live.launch_url)
    assert ticket == live.token  # 提取正确，排除"用错票据也 401"的假阳性
    clock.advance(BOOT_TICKET_TTL_SECONDS + 0.5)  # 用户 10 秒后才重新打开启动 URL
    response = _exchange(client, ticket)
    assert response.status == 401
    assert response.error_type() == "BootTicketInvalid"
    # 过期票据绝不下发会话 Cookie。
    assert response.set_cookies == []

    # 因此随后的写请求仍然是 fail-closed。
    assert _write(client, cookie=None, origin=client.origin).status == 401


# ── 场景 3：票据重放 ──────────────────────────────────────────────────────


def test_consumed_ticket_replay_is_rejected(live: LiveServer) -> None:
    client = live.client()
    ticket = _ticket_from_launch_url(live.launch_url)

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

    # 拒绝重放不得以作废正常会话为代价（否则重放就退化成 DoS）。
    assert _write(client, cookie=cookie, origin=client.origin).status == 422


# ── 场景 4：会话过期（12 小时 TTL，注入时钟） ──────────────────────────────


def test_session_expiry_fails_closed_for_writes(live: LiveServer, clock: FakeClock) -> None:
    client = live.client()
    exchanged = _exchange(client, live.token)
    assert exchanged.status == 200, exchanged.body
    cookie = exchanged.session_cookie()
    assert cookie

    assert _write(client, cookie=cookie, origin=client.origin).status == 422

    # 到期前一秒仍然有效（TTL 是 12 小时，不是更短）。
    clock.advance(SESSION_TTL_SECONDS - 1)
    assert _write(client, cookie=cookie, origin=client.origin).status == 422

    # 越过 TTL：同一 Cookie 的写请求 fail-closed。
    clock.advance(2)
    expired = _write(client, cookie=cookie, origin=client.origin)
    assert expired.status == 401
    assert expired.error_type() == "SessionRequired"

    # 会话失效只影响写；读请求维持既有 loopback 防线。
    assert client.send("GET", "/api/version").status == 200


# ── 场景 5：多 app 隔离（票据与会话都不串味） ──────────────────────────────


def test_two_app_instances_do_not_share_tickets_or_sessions(farm: ServerFarm) -> None:
    first = farm.start()
    second = farm.start()
    client_a = first.client()
    client_b = second.client()
    assert first.token != second.token

    # A 的票据在 B 上无效：B 的票据存储不认（per-app 状态）。
    cross_ticket = _exchange(client_b, first.token)
    assert cross_ticket.status == 401
    assert cross_ticket.error_type() == "BootTicketInvalid"

    # A 正常换票（B 的拒绝不消耗 A 的票据）。
    exchanged_a = _exchange(client_a, first.token)
    assert exchanged_a.status == 200, exchanged_a.body
    cookie_a = exchanged_a.session_cookie()
    assert cookie_a

    # 同机同 host 不同端口：Cookie 不按端口隔离，A 的会话会被浏览器带给 B。
    # B 的会话存储里没有它 → 必须 fail-closed。
    cross_session = _write(client_b, cookie=cookie_a, origin=client_b.origin)
    assert cross_session.status == 401
    assert cross_session.error_type() == "SessionRequired"

    # 反向：B 换票后，B 的会话在 A 上同样被拒。
    exchanged_b = _exchange(client_b, second.token)
    assert exchanged_b.status == 200, exchanged_b.body
    cookie_b = exchanged_b.session_cookie()
    assert cookie_b
    assert _write(client_a, cookie=cookie_b, origin=client_a.origin).status == 401

    # 各自的会话在各自实例上可用。
    assert _write(client_a, cookie=cookie_a, origin=client_a.origin).status == 422
    assert _write(client_b, cookie=cookie_b, origin=client_b.origin).status == 422

    # Origin 按监听端口判定：A 的会话配 B 的 Origin → 跨源拒绝。
    wrong_origin = _write(client_a, cookie=cookie_a, origin=client_b.origin)
    assert wrong_origin.status == 403
    assert wrong_origin.error_type() == "CrossSiteRequest"
