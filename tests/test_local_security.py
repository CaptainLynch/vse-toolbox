# -*- coding: utf-8 -*-
"""C7 本机安全与启动契约验证（W16-03 → DSH-V2-03）。

覆盖契约验证清单（DSH_LOCAL_SECURITY_CONTRACT.md §9.2）：
1. 票据：多张签发、单次消费、≤10 秒 TTL、无效/缺失 401（boot-exchange 语义不回归）；
2. `capabilities` 字段集与 `legacyBootQuery` 开关（默认 true，主控裁决 5）；
3. `window-grant`：无密钥 401、密钥错 401、缺 Origin 403、跨源 403、限流 429、
   新授权 supersede 旧授权、`delivery="claim"` 响应不含 ticket 键；
4. `boot-claim`：无授权 409、过期 401、重放 409、`delivery="env"` 不可 claim、
   跨源 403、缺 `Sec-Fetch-Site` 403、已有会话 200 且不消费授权；
5. `session-recover`：无标记 401、有标记 200 且不重设标记、跨源 403、限流 429；
6. 写操作 Origin/会话拒绝（缺失 403 OriginRequired、不匹配 403 CrossSiteRequest）；
7. Cookie 属性断言（HttpOnly; SameSite=Strict; Path=/；loopback http 不设 Secure）；
8. fail-closed：会话缺失的写请求 401，绝不退化为无认证访问；读请求不受影响；
9. 启动链：票据/启动器密钥只经 `env=` 下发（启动器 `os.environ` 不含），
   `instance.json` 不含 `bootToken`、`url` 无查询串（新链路）；
10. 前端握手模块（Node 隔离执行）：接收器幂等与自删、legacyBootQuery 开关、
    `replaceState` 清理、`shell.js` 先注册接收器再渲染、401 横幅与恢复按钮。

fail-closed 路径用原生 werkzeug Client（模拟"不带浏览器等价行为的客户端"），
正常路径用 tests/security_client_fixture.py 显式安装的等价 test client（真实走
boot-exchange 端点）；本模块是 raw_security，不会被 conftest 默认安装替身。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

import web.app as web_app
import web.security as web_security
from web.security import (
    BOOT_CLAIM_PATH,
    BOOT_EXCHANGE_PATH,
    BOOT_EXCHANGE_FAILURE_LIMIT,
    BOOT_TICKET_TTL_SECONDS,
    CAPABILITIES_PATH,
    CLAIM_CALL_LIMIT,
    GRANT_CALL_LIMIT,
    LAUNCHER_SECRET_HEADER,
    RECOVERY_CALL_LIMIT,
    SECURITY_CONTRACT_VERSION,
    SESSION_COOKIE_NAME,
    SESSION_RECOVER_PATH,
    SESSION_TTL_SECONDS,
    WINDOW_COOKIE_NAME,
    WINDOW_GRANT_PATH,
    WINDOW_MARKER_TTL_SECONDS,
    BootTicketStore,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
#: 合成启动器密钥（仅测试用；不是任何真实环境的凭据）。
LAUNCHER_SECRET = "test-only-launcher-secret"


class FakeClock:
    """``web.security.time`` 的替身：monotonic 从 0 起，wall clock 从合成基准起。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.wall = 1_735_689_600.0  # 2025-01-01T00:00:00Z（合成时间轴）

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.wall + self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(web_security, "time", fake)
    return fake


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "security.db"))
    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)
    flask_app = web_app.create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def secured_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """带启动器密钥的 app：window-grant / boot-claim / session-recover 可被驱动。"""
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "secured.db"))
    monkeypatch.delenv("VSE_BOOT_TOKEN", raising=False)
    flask_app = web_app.create_app(launcher_secret=LAUNCHER_SECRET)
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def raw(app):
    """原生 werkzeug Client：不注入 Origin、不自动交换票据、不自动带 Cookie。

    ``use_cookies=False`` 是必要的：真实浏览器在「重放 / 无会话」场景里由用例
    显式给出 Cookie，客户端 Cookie 罐会把上一响应的 ``vse_session`` 自动带上，
    使重放看起来像「已有有效会话」（契约 §6.4 的合法分支），从而掩盖 409。
    """
    return Client(app, Response, use_cookies=False)


@pytest.fixture()
def secured_raw(secured_app):
    return Client(secured_app, Response, use_cookies=False)


def _loopback(raw_client: Client):
    return {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}}


def _origin_headers(origin: str = "http://localhost") -> dict:
    return {"Origin": origin}


def _same_site_headers(origin: str = "http://localhost") -> dict:
    return {"Origin": origin, "Sec-Fetch-Site": "same-origin"}


def _exchange(raw_client: Client, token, *, headers: dict | None = None):
    return raw_client.post(
        BOOT_EXCHANGE_PATH, json={"token": token}, **_loopback(raw_client), headers=headers
    )


def _grant(raw_client: Client, *, delivery: str = "claim", purpose: str = "open",
           headers: dict | None = None, body: dict | None = None):
    merged = dict(headers if headers is not None else {"Origin": "http://localhost"})
    payload = body if body is not None else {"purpose": purpose, "delivery": delivery}
    return raw_client.post(WINDOW_GRANT_PATH, json=payload, **_loopback(raw_client), headers=merged)


def _authed_grant(raw_client: Client, *, delivery: str = "claim", purpose: str = "open"):
    return _grant(
        raw_client,
        delivery=delivery,
        purpose=purpose,
        headers={"Origin": "http://localhost", LAUNCHER_SECRET_HEADER: LAUNCHER_SECRET},
    )


def _claim(raw_client: Client, *, headers: dict | None = None, cookie: str | None = None):
    merged = dict(headers if headers is not None else _same_site_headers())
    if cookie:
        merged["Cookie"] = f"{SESSION_COOKIE_NAME}={cookie}"
    return raw_client.post(BOOT_CLAIM_PATH, json={}, **_loopback(raw_client), headers=merged)


def _recover(raw_client: Client, *, marker: str | None = None, headers: dict | None = None):
    merged = dict(headers if headers is not None else _same_site_headers())
    if marker:
        merged["Cookie"] = f"{WINDOW_COOKIE_NAME}={marker}"
    return raw_client.post(SESSION_RECOVER_PATH, json={}, **_loopback(raw_client), headers=merged)


def _session_pair(response) -> str:
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith(f"{SESSION_COOKIE_NAME}="):
            return header.split(";")[0]
    raise AssertionError("响应没有下发 vse_session")


def _window_pair(response) -> str:
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith(f"{WINDOW_COOKIE_NAME}="):
            return header.split(";")[0]
    raise AssertionError("响应没有下发 vse_window")


def _cookie_value(pair: str) -> str:
    return pair.partition("=")[2]


# ── 1. 票据：无票据 401、单次、TTL、多张并存 ─────────────────────────────


def test_boot_exchange_without_ticket_is_401(app, raw):
    response = raw.post(BOOT_EXCHANGE_PATH, json={}, **_loopback(raw))
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "BootTicketInvalid"


def test_boot_exchange_with_wrong_ticket_is_401(app, raw):
    response = _exchange(raw, "not-the-real-ticket", headers=_origin_headers())
    assert response.status_code == 401


def test_boot_ticket_is_single_use(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = _exchange(raw, token, headers=_origin_headers())
    assert first.status_code == 200
    replay = _exchange(raw, token, headers=_origin_headers())
    assert replay.status_code == 401
    assert replay.get_json()["error"]["type"] == "BootTicketInvalid"


def test_boot_ticket_store_issues_many_consumes_once_and_expires(clock: FakeClock):
    """多张票据并存（上限 8）、单次消费、TTL 到点即失效（契约 §7.1）。"""
    store = BootTicketStore(ttl_seconds=BOOT_TICKET_TTL_SECONDS)
    tokens = [store.issue() for _ in range(3)]
    assert len(set(tokens)) == 3
    assert store.consume("wrong") is False  # 值不匹配不烧掉任何票据
    assert store.consume(tokens[1]) is True
    assert store.consume(tokens[1]) is False  # 单次
    assert store.consume(tokens[0]) is True  # 其余票据不受影响

    expiring = store.issue()
    clock.advance(BOOT_TICKET_TTL_SECONDS + 0.5)
    assert store.consume(expiring) is False
    assert store.consume(tokens[2]) is False  # 同一 TTL 一起过期
    assert BOOT_TICKET_TTL_SECONDS <= 10  # 冻结上限：不得放大 TTL 规避慢启动


def test_boot_ticket_store_caps_pending_tickets(clock: FakeClock):
    store = BootTicketStore(ttl_seconds=BOOT_TICKET_TTL_SECONDS)
    issued = [store.issue() for _ in range(web_security.MAX_PENDING_TICKETS + 2)]
    assert len(store) == web_security.MAX_PENDING_TICKETS
    # 最早的被淘汰，最新的仍在
    assert store.consume(issued[0]) is False
    assert store.consume(issued[-1]) is True


# ── 2. capabilities ──────────────────────────────────────────────────────


def test_capabilities_exposes_frozen_field_set(app, raw):
    response = raw.get(CAPABILITIES_PATH, **_loopback(raw))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.get_json()["data"]
    assert data == {
        "contractVersion": SECURITY_CONTRACT_VERSION,
        "grantArm": True,
        "windowInjection": True,
        "legacyBootQuery": True,  # 默认 true（主控裁决 5）
        "handoffFile": False,
        "ticketTtlSeconds": BOOT_TICKET_TTL_SECONDS,
        "sessionTtlSeconds": SESSION_TTL_SECONDS,
        "epoch": data["epoch"],
    }
    assert len(data["epoch"]) == 16


def test_capabilities_legacy_boot_query_switch(monkeypatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "legacy.db"))
    flask_app = web_app.create_app(accept_legacy_boot_query=False)
    flask_app.config.update(TESTING=True)
    client = Client(flask_app, Response)
    data = client.get(CAPABILITIES_PATH, **_loopback(client)).get_json()["data"]
    assert data["legacyBootQuery"] is False
    # 只有显式关闭才为 false：默认值不变（翻转为 false 需独立批准）
    assert web_app.create_app().extensions["local_web_security"].accept_legacy_boot_query is True


# ── 3. window-grant ──────────────────────────────────────────────────────


def test_window_grant_without_secret_is_401(app, raw):
    """未配置启动器密钥：一律 401，不存在“无密钥即放行”。"""
    response = _grant(raw, headers={"Origin": "http://localhost", LAUNCHER_SECRET_HEADER: "x"})
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "LauncherAuthRequired"
    assert response.headers.get("Set-Cookie") is None  # 不设置任何 Cookie


def test_window_grant_with_wrong_secret_is_401(secured_app, secured_raw):
    response = _grant(
        secured_raw,
        headers={"Origin": "http://localhost", LAUNCHER_SECRET_HEADER: "wrong-secret"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "LauncherAuthRequired"


def test_window_grant_requires_origin(secured_app, secured_raw):
    response = _grant(secured_raw, headers={LAUNCHER_SECRET_HEADER: LAUNCHER_SECRET})
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "OriginRequired"


def test_window_grant_rejects_cross_origin(secured_app, secured_raw):
    response = _grant(
        secured_raw,
        headers={"Origin": "http://evil.example", LAUNCHER_SECRET_HEADER: LAUNCHER_SECRET},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "CrossSiteRequest"


def test_window_grant_env_returns_ticket_and_claim_does_not(secured_app, secured_raw):
    env_response = _authed_grant(secured_raw, delivery="env")
    assert env_response.status_code == 200
    env_data = env_response.get_json()["data"]
    assert env_data["delivery"] == "env"
    assert env_data["grantId"].startswith("grt_")
    assert env_data["ttlSeconds"] == BOOT_TICKET_TTL_SECONDS
    assert env_data["epoch"] == secured_app.extensions["local_web_security"].epoch
    assert isinstance(env_data["ticket"], str) and len(env_data["ticket"]) >= 32
    assert env_response.headers.get("Set-Cookie") is None

    claim_response = _authed_grant(secured_raw, delivery="claim")
    assert claim_response.status_code == 200
    claim_data = claim_response.get_json()["data"]
    assert claim_data["delivery"] == "claim"
    assert "ticket" not in claim_data  # 键不存在，而非空串


def test_window_grant_supersedes_previous_grant(secured_app, secured_raw):
    assert _authed_grant(secured_raw, delivery="claim").status_code == 200
    assert _authed_grant(secured_raw, delivery="env").status_code == 200
    # 旧 claim 授权已被 supersede：页面拿不到待领取授权
    response = _claim(secured_raw)
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "NoPendingGrant"


def test_window_grant_validates_payload(secured_app, secured_raw):
    for body in ({"purpose": "open"}, {"purpose": "nope", "delivery": "claim"},
                 {"purpose": "open", "delivery": "nope"}):
        response = _grant(
            secured_raw,
            body=body,
            headers={"Origin": "http://localhost", LAUNCHER_SECRET_HEADER: LAUNCHER_SECRET},
        )
        assert response.status_code == 400, body
        assert response.get_json()["error"]["type"] == "ValidationError"


def test_window_grant_is_rate_limited(secured_app, secured_raw):
    for _ in range(GRANT_CALL_LIMIT):
        assert _authed_grant(secured_raw).status_code == 200
    limited = _authed_grant(secured_raw)
    assert limited.status_code == 429
    assert limited.get_json()["error"]["type"] == "GrantRateLimited"


def test_boot_exchange_failures_are_rate_limited(app, raw):
    for _ in range(BOOT_EXCHANGE_FAILURE_LIMIT):
        assert _exchange(raw, "wrong-ticket", headers=_origin_headers()).status_code == 401
    limited = _exchange(raw, "wrong-ticket", headers=_origin_headers())
    assert limited.status_code == 429
    assert limited.get_json()["error"]["type"] == "BootExchangeRateLimited"


# ── 4. boot-claim ────────────────────────────────────────────────────────


def test_boot_claim_without_grant_is_409(secured_app, secured_raw):
    response = _claim(secured_raw)
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "NoPendingGrant"


def test_boot_claim_requires_same_origin_and_same_site(secured_app, secured_raw):
    _authed_grant(secured_raw, delivery="claim")
    no_origin = _claim(secured_raw, headers={})
    assert no_origin.status_code == 403
    assert no_origin.get_json()["error"]["type"] == "OriginRequired"

    no_site = _claim(secured_raw, headers={"Origin": "http://localhost"})
    assert no_site.status_code == 403
    assert no_site.get_json()["error"]["type"] == "SameSiteRequired"

    cross = _claim(secured_raw, headers=_same_site_headers("http://evil.example"))
    assert cross.status_code == 403
    assert cross.get_json()["error"]["type"] == "CrossSiteRequest"

    # 三次跨源/缺头请求都没有把授权烧掉：正确的同源领取仍然成功。
    granted = _claim(secured_raw)
    assert granted.status_code == 200
    assert granted.get_json()["data"]["exchanged"] is True


def test_boot_claim_issues_session_and_window_cookies(secured_app, secured_raw):
    _authed_grant(secured_raw, delivery="claim")
    response = _claim(secured_raw)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["exchanged"] is True and data["sessionValid"] is True
    assert data["sessionTtlSeconds"] == SESSION_TTL_SECONDS
    assert data["epoch"] == secured_app.extensions["local_web_security"].epoch
    session_cookie = response.headers.getlist("Set-Cookie")
    session_header = next(h for h in session_cookie if h.startswith(f"{SESSION_COOKIE_NAME}="))
    window_header = next(h for h in session_cookie if h.startswith(f"{WINDOW_COOKIE_NAME}="))
    assert "HttpOnly" in session_header and "SameSite=Strict" in session_header
    assert f"Max-Age={SESSION_TTL_SECONDS}" in session_header
    assert "Secure" not in session_header
    assert f"Max-Age={WINDOW_MARKER_TTL_SECONDS}" in window_header
    assert response.headers["Cache-Control"] == "no-store"


def test_boot_claim_replay_is_409(secured_app, secured_raw):
    _authed_grant(secured_raw, delivery="claim")
    first = _claim(secured_raw)
    assert first.status_code == 200
    replay = _claim(secured_raw)
    assert replay.status_code == 409
    assert replay.get_json()["error"]["type"] == "NoPendingGrant"
    assert replay.headers.getlist("Set-Cookie") == []


def test_boot_claim_expired_grant_is_401(secured_app, secured_raw, clock: FakeClock):
    _authed_grant(secured_raw, delivery="claim")
    clock.advance(BOOT_TICKET_TTL_SECONDS + 0.5)
    response = _claim(secured_raw)
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "GrantExpired"
    # 过期项已被删除：再次领取回到 409
    assert _claim(secured_raw).status_code == 409


def test_boot_claim_ignores_env_delivery_grant(secured_app, secured_raw):
    _authed_grant(secured_raw, delivery="env")
    response = _claim(secured_raw)
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "NoPendingGrant"


def test_boot_claim_with_existing_session_does_not_consume_grant(secured_app, secured_raw):
    token = secured_app.config["VSE_BOOT_TOKEN"]
    exchanged = _exchange(secured_raw, token, headers=_origin_headers())
    assert exchanged.status_code == 200
    session = _cookie_value(_session_pair(exchanged))

    _authed_grant(secured_raw, delivery="claim")
    with_session = _claim(secured_raw, cookie=session)
    assert with_session.status_code == 200
    data = with_session.get_json()["data"]
    assert data["exchanged"] is False and data["sessionValid"] is True
    assert with_session.headers.getlist("Set-Cookie") == []  # 不重设 Cookie

    # 授权未被消费：没有会话的浏览器仍能领取
    fresh = _claim(secured_raw)
    assert fresh.status_code == 200
    assert fresh.get_json()["data"]["exchanged"] is True


def test_boot_claim_is_rate_limited(secured_app, secured_raw):
    _authed_grant(secured_raw, delivery="claim")
    assert _claim(secured_raw).status_code == 200  # 消费授权
    for _ in range(CLAIM_CALL_LIMIT - 1):
        assert _claim(secured_raw).status_code == 409
    limited = _claim(secured_raw)
    assert limited.status_code == 429
    assert limited.get_json()["error"]["type"] == "ClaimRateLimited"


# ── 5. session-recover ───────────────────────────────────────────────────


def test_session_recover_without_marker_is_401(secured_app, secured_raw):
    response = _recover(secured_raw)
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "SessionRecoveryUnavailable"
    unknown = _recover(secured_raw, marker="not-a-real-marker")
    assert unknown.status_code == 401


def test_session_recover_reissues_session_without_touching_marker(secured_app, secured_raw):
    token = secured_app.config["VSE_BOOT_TOKEN"]
    exchanged = _exchange(secured_raw, token, headers=_origin_headers())
    marker = _cookie_value(_window_pair(exchanged))

    response = _recover(secured_raw, marker=marker)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["recovered"] is True
    assert data["sessionTtlSeconds"] == SESSION_TTL_SECONDS
    new_session = _cookie_value(_session_pair(response))
    assert new_session
    set_cookies = response.headers.getlist("Set-Cookie")
    assert all(not header.startswith(f"{WINDOW_COOKIE_NAME}=") for header in set_cookies)
    # 恢复不延长标记有效期：同一标记仍可再次恢复（幂等换新会话）。
    assert _recover(secured_raw, marker=marker).status_code == 200


def test_session_recover_rejects_cross_origin(secured_app, secured_raw):
    token = secured_app.config["VSE_BOOT_TOKEN"]
    exchanged = _exchange(secured_raw, token, headers=_origin_headers())
    marker = _cookie_value(_window_pair(exchanged))
    cross = _recover(secured_raw, marker=marker, headers=_same_site_headers("http://evil.example"))
    assert cross.status_code == 403
    assert cross.get_json()["error"]["type"] == "CrossSiteRequest"
    no_site = _recover(secured_raw, marker=marker, headers={"Origin": "http://localhost"})
    assert no_site.status_code == 403
    assert no_site.get_json()["error"]["type"] == "SameSiteRequired"
    # 跨源请求没有把标记烧掉
    assert _recover(secured_raw, marker=marker).status_code == 200


def test_session_recover_is_rate_limited(secured_app, secured_raw):
    token = secured_app.config["VSE_BOOT_TOKEN"]
    marker = _cookie_value(_window_pair(_exchange(secured_raw, token, headers=_origin_headers())))
    for _ in range(RECOVERY_CALL_LIMIT):
        assert _recover(secured_raw, marker=marker).status_code == 200
    limited = _recover(secured_raw, marker=marker)
    assert limited.status_code == 429
    assert limited.get_json()["error"]["type"] == "RecoveryRateLimited"


# ── 7. Cookie 属性 ───────────────────────────────────────────────────────


def test_session_cookie_attributes(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    response = _exchange(raw, token, headers=_origin_headers())
    assert response.status_code == 200
    cookie = response.headers.get("Set-Cookie") or ""
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    # loopback http：浏览器把 127.0.0.1 视为安全上下文，不设 Secure（C7 以实测为准）
    assert "Secure" not in cookie
    assert f"Max-Age={SESSION_TTL_SECONDS}" in cookie
    # boot-exchange 同时下发 vse_window（K5 的恢复凭据），且响应体逐字冻结
    assert response.get_json() == {"ok": True, "data": {"exchanged": True}}
    window_cookie = next(
        header for header in response.headers.getlist("Set-Cookie")
        if header.startswith(f"{WINDOW_COOKIE_NAME}=")
    )
    assert "HttpOnly" in window_cookie and "SameSite=Strict" in window_cookie
    assert f"Max-Age={WINDOW_MARKER_TTL_SECONDS}" in window_cookie
    assert response.headers[web_security.EPOCH_HEADER] == app.extensions["local_web_security"].epoch


# ── 6. 写操作：会话 + Origin（Origin 严格校验替代 CSRF token） ──────────


def test_write_without_session_is_401_fail_closed(app, raw):
    response = raw.put(
        "/api/project-status/section-rollup", json={}, **_loopback(raw), headers=_origin_headers()
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "SessionRequired"


def test_write_with_session_but_missing_origin_is_403(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = _exchange(raw, token, headers=_origin_headers())
    session_pair = _session_pair(first)
    response = raw.put(
        "/api/project-status/section-rollup",
        json={},
        **_loopback(raw),
        headers={"Cookie": session_pair},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "OriginRequired"


def test_write_with_wrong_origin_is_403(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = _exchange(raw, token, headers=_origin_headers())
    session_pair = _session_pair(first)
    for origin in ("http://127.0.0.1:6666", "http://evil.example", "http://localhost:1"):
        response = raw.put(
            "/api/project-status/section-rollup",
            json={},
            **_loopback(raw),
            headers={"Cookie": session_pair, "Origin": origin},
        )
        assert response.status_code == 403, origin
        assert response.get_json()["error"]["type"] == "CrossSiteRequest"


def test_write_with_session_and_matching_origin_reaches_view(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    first = _exchange(raw, token, headers=_origin_headers())
    session_pair = _session_pair(first)
    response = raw.put(
        "/api/project-status/section-rollup",
        json={},
        **_loopback(raw),
        headers={"Cookie": session_pair, "Origin": "http://localhost"},
    )
    # 通过安全层后到达视图（422=业务校验，而不是 401/403 安全拒绝）
    assert response.status_code == 422


def test_read_endpoints_stay_open_for_supervisor_probe(app, raw):
    # supervisor 探测 /api/version 与 /api/host/manifest（父进程、无会话）。
    for path in ("/api/version", "/api/host/manifest"):
        response = raw.get(path, **_loopback(raw))
        assert response.status_code == 200, path


def test_non_loopback_exchange_stays_rejected(app, raw):
    token = app.config["VSE_BOOT_TOKEN"]
    response = raw.post(
        BOOT_EXCHANGE_PATH,
        json={"token": token},
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
        headers=_origin_headers(),
    )
    # 既有 loopback 守卫先于本模块生效（fail-closed 不回退）。
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "LocalAccessRequired"


# ── 8. 测试客户端边界（DSH-V2-05）：生产模块不再安装已认证替身 ─────────────


def test_production_module_has_no_test_client_substitute():
    # 回归哨兵：替身代码已移到 tests/security_client_fixture.py。
    assert not hasattr(web_security, "install_security_aware_test_client")
    assert not hasattr(web_security, "_SecurityAwareTestClient")


def test_native_test_client_write_without_session_is_401(app):
    # 本模块是 raw_security：app.test_client() 是原生客户端，未经替身补齐。
    client = app.test_client()
    response = client.put(
        "/api/project-status/section-rollup",
        json={},
        headers=_origin_headers(),
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 401


def test_native_test_client_write_without_origin_is_403(app, raw):
    # 先真实换到会话，再以该会话发不带 Origin 的写请求（原生 Client，不补 Origin）。
    exchanged = _exchange(raw, app.config["VSE_BOOT_TOKEN"], headers=_origin_headers())
    assert exchanged.status_code == 200
    response = raw.put(
        "/api/project-status/section-rollup",
        json={},
        headers={"Cookie": _session_pair(exchanged)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["type"] == "OriginRequired"


def test_authenticated_fixture_client_writes_pass_through_security(app):
    from tests.security_client_fixture import install_authenticated_test_client

    install_authenticated_test_client(app)
    client = app.test_client()
    response = client.put("/api/project-status/section-rollup", json={})
    # 到达视图的业务校验层（而不是被安全层拒绝）。
    assert response.status_code == 422


def test_each_app_instance_has_its_own_session_store(app):
    from tests.security_client_fixture import install_authenticated_test_client

    other = web_app.create_app()
    install_authenticated_test_client(app)
    install_authenticated_test_client(other)
    client = app.test_client()
    other_client = other.test_client()
    ok = client.put("/api/project-status/section-rollup", json={})
    ok_other = other_client.put("/api/project-status/section-rollup", json={})
    assert ok.status_code == 422 and ok_other.status_code == 422
    # per-app 状态，绝不串味。
    assert app.config["VSE_BOOT_TOKEN"] != other.config["VSE_BOOT_TOKEN"]
    assert app.extensions["local_web_security"].epoch != other.extensions["local_web_security"].epoch


# ── 9. 启动链 ────────────────────────────────────────────────────────────
# 票据/密钥只经 `env=` 下发、instance.json 字段集、capabilities 降级、K4/K6 等
# 启动器侧行为在 tests/test_vse_boot_supervisor.py 覆盖（那里有 Supervisor 夹具）。


# ── 10. 前端握手模块（Node 隔离执行，无 DOM） ─────────────────────────────

NODE_FIXTURE = r"""
const path = process.argv[1];
const mod = await import(path);

function makeFetch(handlers) {
  const calls = [];
  const fetchStub = async (url, init = {}) => {
    calls.push({ url, init });
    const handler = handlers[url] || handlers["*"];
    const payload = handler ? handler(init) : { ok: true, data: {} };
    return {
      ok: payload.ok !== false,
      status: payload.status || (payload.ok === false ? 409 : 200),
      json: async () => payload.body,
    };
  };
  return { fetchStub, calls };
}

function makeWindow(search = "", bridge = null) {
  const listeners = {};
  const window = {
    location: { search, pathname: "/", hash: "" },
    history: { replaced: null, replaceState(_state, _title, url) { this.replaced = url; } },
    addEventListener(name, handler) { (listeners[name] = listeners[name] || []).push(handler); },
    dispatchEvent(event) { (listeners[event.type] || []).forEach((fn) => fn(event)); return true; },
  };
  if (bridge) window.pywebview = { api: { take_boot_ticket: bridge } };
  return window;
}

const out = {};

// 1) 接收器：幂等 + 收到票据后自删 + 真实发 boot-exchange
{
  const { fetchStub, calls } = makeFetch({
    "/api/security/boot-exchange": () => ({ body: { ok: true, data: { exchanged: true } } }),
  });
  globalThis.fetch = fetchStub;
  const win = makeWindow();
  const first = mod.registerBootReceiver(win);
  const second = mod.registerBootReceiver(win);
  out.receiverIdempotent = first === second && typeof win.__vseBootReceiver === "function";
  out.receiverResult = win.__vseBootReceiver("tok_synthetic");
  out.receiverDeleted = !("__vseBootReceiver" in win);
  await new Promise((resolve) => setTimeout(resolve, 20));
  out.receiverExchange = calls.map((call) => [call.url, JSON.parse(call.init.body)]);
}

// 2) legacyBootQuery=false：不读地址栏
{
  const { fetchStub, calls } = makeFetch({
    "/api/security/capabilities": () => ({ body: { ok: true, data: { legacyBootQuery: false } } }),
    "/api/security/boot-claim": () => ({ ok: false, status: 409, body: { ok: false, error: { type: "NoPendingGrant" } } }),
  });
  globalThis.fetch = fetchStub;
  const win = makeWindow("?boot=tok_legacy&x=1");
  out.legacyOff = await mod.runBootHandshake(win);
  out.legacyOffCalls = calls.map((call) => call.url);
  out.legacyOffReplaced = win.history.replaced;
}

// 3) legacyBootQuery=true：取票 + 交换 + replaceState 清理
{
  const { fetchStub, calls } = makeFetch({
    "/api/security/capabilities": () => ({ body: { ok: true, data: { legacyBootQuery: true } } }),
    "/api/security/boot-claim": () => ({ ok: false, status: 409, body: { ok: false, error: { type: "NoPendingGrant" } } }),
    "/api/security/boot-exchange": () => ({ body: { ok: true, data: { exchanged: true } } }),
  });
  globalThis.fetch = fetchStub;
  const win = makeWindow("?boot=tok_legacy&x=1");
  out.legacyOn = await mod.runBootHandshake(win);
  out.legacyOnExchange = calls
    .filter((call) => call.url === "/api/security/boot-exchange")
    .map((call) => JSON.parse(call.init.body));
  out.legacyOnReplaced = win.history.replaced;
}

// 4) pywebview 桥：取票一次后交换，不再走 claim
{
  let taken = 0;
  const { fetchStub, calls } = makeFetch({
    "/api/security/boot-exchange": () => ({ body: { ok: true, data: { exchanged: true } } }),
  });
  globalThis.fetch = fetchStub;
  const win = makeWindow("", async () => {
    taken += 1;
    return taken === 1 ? "tok_bridge" : null;
  });
  out.bridge = await mod.runBootHandshake(win);
  out.bridgeExchange = calls.map((call) => [call.url, JSON.parse(call.init.body)]);
  out.bridgeTakeCalls = taken;
}

// 5) 无桥无授权：claim 409 静默，不抛错
{
  const { fetchStub, calls } = makeFetch({
    "/api/security/capabilities": () => ({ body: { ok: true, data: { legacyBootQuery: true } } }),
    "/api/security/boot-claim": () => ({ ok: false, status: 409, body: { ok: false, error: { type: "NoPendingGrant" } } }),
  });
  globalThis.fetch = fetchStub;
  const win = makeWindow("");
  out.claimSilent = await mod.runBootHandshake(win);
  out.claimCalls = calls.map((call) => call.url);
}

console.log(JSON.stringify(out));
"""


def _node_available() -> bool:
    return shutil.which("node") is not None


needs_node = pytest.mark.skipif(not _node_available(), reason="需要 Node.js")


def _run_node(script: str, module_path: Path) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, module_path.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
def test_boot_handshake_js_receiver_claim_and_legacy_branch() -> None:
    data = _run_node(NODE_FIXTURE, REPO_ROOT / "web" / "static" / "host" / "boot-exchange.js")
    # 接收器幂等、收到票据后自删并真实发起交换
    assert data["receiverIdempotent"] is True
    assert data["receiverResult"] is True
    assert data["receiverDeleted"] is True
    assert data["receiverExchange"] == [
        ["/api/security/boot-exchange", {"token": "tok_synthetic"}]
    ]
    # legacyBootQuery=false：不读地址栏、不交换、不动 history
    assert data["legacyOff"] is False
    assert "/api/security/boot-exchange" not in data["legacyOffCalls"]
    assert data["legacyOffReplaced"] is None
    # legacyBootQuery=true：取票 + 交换 + replaceState 清理
    assert data["legacyOn"] is True
    assert data["legacyOnExchange"] == [{"token": "tok_legacy"}]
    assert data["legacyOnReplaced"] == "/?x=1"
    # pywebview 桥：票据只交付一次，走 K2 而不是 claim
    assert data["bridge"] is True
    assert data["bridgeExchange"] == [["/api/security/boot-exchange", {"token": "tok_bridge"}]]
    assert data["bridgeTakeCalls"] == 1
    # 无桥无授权：claim 409 静默，不抛错
    assert data["claimSilent"] is False
    assert "/api/security/boot-claim" in data["claimCalls"]


@needs_node
def test_boot_exchange_js_extract_strip_and_cleanup_logic() -> None:
    script = r"""
const mod = await import(process.argv[1]);
const { extractBootTicket, stripBootTicket } = mod;
const out = {
  extract: extractBootTicket("?boot=abc&x=1"),
  none: extractBootTicket("?x=1"),
  keep: stripBootTicket("?boot=abc&x=1"),
  root: stripBootTicket("?boot=abc"),
  unchanged: stripBootTicket("?x=1"),
};
console.log(JSON.stringify(out));
"""
    data = _run_node(script, REPO_ROOT / "web" / "static" / "host" / "boot-exchange.js")
    assert data["extract"] == "abc"
    assert data["none"] is None
    assert data["keep"] == "?x=1"
    assert data["root"] == ""
    assert data["unchanged"] is None


SHELL_BANNER_FIXTURE = r"""
const mod = await import(process.argv[1]);

function makeDoc() {
  const created = [];
  const doc = {
    body: { children: [], appendChild(node) { this.children.push(node); node.parent = this; } },
    createElement(tag) {
      const node = {
        tag, id: "", hidden: false, textContent: "", style: {}, children: [], listeners: {},
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); },
        addEventListener(name, handler) { (this.listeners[name] = this.listeners[name] || []).push(handler); },
        click() { return Promise.all((this.listeners.click || []).map((fn) => fn())); },
      };
      created.push(node);
      return node;
    },
    getElementById(id) {
      const found = doc.body.children.find((node) => node.id === id);
      return found || null;
    },
    documentElement: null,
  };
  return doc;
}

function makeWin() {
  const listeners = {};
  return {
    addEventListener(name, handler) { (listeners[name] = listeners[name] || []).push(handler); },
    dispatchEvent(event) { (listeners[event.type] || []).forEach((fn) => fn(event)); return true; },
    listeners,
  };
}

const out = {};
const doc = makeDoc();
const win = makeWin();
const calls = [];
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url, method: init.method });
  return { ok: true, status: 200, json: async () => ({ ok: true, data: { recovered: true } }) };
};
const handle = mod.mountSessionRecoveryBanner(win, doc);
out.mounted = Boolean(handle && handle.banner && handle.text && handle.button);
out.hiddenInitially = handle.banner.hidden;
out.textInitially = handle.text.textContent;
out.buttonLabel = handle.button.textContent;
win.dispatchEvent({ type: "vse:session-expired" });
out.shownAfterEvent = handle.banner.hidden === false;
await handle.button.click();
out.hiddenAfterRecover = handle.banner.hidden;
out.calls = calls.map((call) => [call.url, call.method]);
out.duplicateMount = mod.mountSessionRecoveryBanner(win, doc);

// 恢复失败（标记失效）：文案切换为“请从开始菜单重新打开”
globalThis.fetch = async () => ({
  ok: false,
  status: 401,
  json: async () => ({ ok: false, error: { type: "SessionRecoveryUnavailable" } }),
});
win.dispatchEvent({ type: "vse:session-expired" });
await handle.button.click();
out.unrecoverableText = handle.text.textContent;
out.buttonHidden = handle.button.hidden;

console.log(JSON.stringify(out));
"""


@needs_node
def test_host_shell_registers_receiver_before_render_and_recovers_session() -> None:
    data = _run_node(SHELL_BANNER_FIXTURE, REPO_ROOT / "web" / "static" / "host" / "shell.js")
    assert data["mounted"] is True
    assert data["hiddenInitially"] is True
    assert data["textInitially"] == "本地会话已过期"
    assert data["buttonLabel"] == "恢复会话"
    assert data["shownAfterEvent"] is True
    assert data["hiddenAfterRecover"] is True
    assert data["calls"] == [["/api/security/session-recover", "POST"]]
    assert data["duplicateMount"] is None  # 幂等：同一文档只挂一个横幅
    assert data["unrecoverableText"] == "本窗口无法自动恢复，请从开始菜单重新打开 VSE Toolbox"
    assert data["buttonHidden"] is True


def test_host_shell_source_registers_receiver_before_start_shell() -> None:
    source = (REPO_ROOT / "web" / "static" / "host" / "shell.js").read_text(encoding="utf-8")
    register_at = source.index("registerBootReceiver(window);")
    handshake_at = source.index("runBootHandshake(window);")
    start_at = source.index("startShell();", handshake_at)
    assert register_at < handshake_at < start_at
    assert "runBootExchange().finally" not in source
    assert 'from "./boot-exchange.js"' in source


@needs_node
def test_api_js_dispatches_session_expired_only_for_session_required() -> None:
    script = r"""
const mod = await import(process.argv[1]);
const events = [];
globalThis.window = {
  dispatchEvent(event) { events.push(event.type); return true; },
};
const out = {};
globalThis.fetch = async () => ({
  ok: false, status: 401,
  json: async () => ({ ok: false, error: { type: "SessionRequired", message: "本地会话缺失或已失效" } }),
});
try { await mod.api("/api/p/workbench/today"); } catch (error) {
  out.sessionError = [error.status, error.type, error.message];
}
globalThis.fetch = async () => ({
  ok: false, status: 401,
  json: async () => ({ ok: false, error: { type: "BootTicketInvalid", message: "票据无效" } }),
});
try { await mod.api("/api/security/boot-exchange", { method: "POST", body: {} }); } catch (error) {
  out.ticketError = [error.status, error.type];
}
out.events = events;
console.log(JSON.stringify(out));
"""
    data = _run_node(script, REPO_ROOT / "web" / "static" / "host" / "api.js")
    assert data["sessionError"] == [401, "SessionRequired", "本地会话缺失或已失效"]
    assert data["ticketError"] == [401, "BootTicketInvalid"]
    # 只有 SessionRequired 触发恢复横幅事件
    assert data["events"] == ["vse:session-expired"]
