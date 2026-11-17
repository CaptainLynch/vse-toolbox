# -*- coding: utf-8 -*-
"""DSH-V2-15：企业会话续期协调器与清除代次。

覆盖 ``docs/refactor-v2/DSH_IDENTITY_CONTRACT.md`` §9.3 T1–T13 与 §10.3 U1–U6，
全部用例名带编号。测试纪律（§9.2）：

* 只用假传输 + 内存凭据：不读 DPAPI 真库、不读现有 keys、不打真实网络；
* 合成值一律 ``user-a`` / ``user-b`` / ``example.test``，口令为运行期唯一秘密；
* 断言"只登录一次 / 只重放一次"用调用计数，不用真实等待（并发窗口由
  ``await_waiters`` 观测器稳定，不参与断言）。
"""

from __future__ import annotations

import hmac
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.credential_provider import MemoryCredentialProvider
from core.domain_identity import (
    RECOVERY_ERROR_CODES,
    SESSION_STATE_CLEARED,
    SESSION_STATE_EXPIRED,
    SESSION_STATE_FAILED,
    SESSION_STATE_NONE,
    SESSION_STATE_RENEWING,
    SESSION_STATE_VALID,
    DomainSessionRegistry,
)
from services.aras_auth import ArasAuthError
from services.aras_crawler import ArasAuthenticationError
from services.session_recovery import (
    IDEMPOTENT_READ,
    IDEMPOTENT_WRITE_WITH_KEY,
    UNSAFE_SIDE_EFFECT,
    CredentialUnavailable,
    Forbidden,
    GenerationUnknown,
    RenewalRejected,
    SessionCleared,
    SessionExpired,
    SessionRecoveryError,
    SessionRenewalCoordinator,
    UpstreamParseError,
    UpstreamUnavailable,
)
from services.tdc_crawler import CrawlCancelled, TDCCrawlerError

ARAS_ROOT = "https://example.test/innovatorserver"
TDC_ROOT = "https://example.test/uwf"
PRINCIPAL = "user-a"
OTHER_PRINCIPAL = "user-b"


def _runtime_opaque() -> str:
    """运行期唯一合成秘密（对齐 tests/test_settings_security.py:32-33）。"""
    return f"opq-{uuid.uuid4().hex}"


PASSWORD = _runtime_opaque()


# ── 夹具：假时钟 / 假响应 / 假传输 / 假登录客户端 ────────────────────────────


class FakeClock:
    """可步进时钟；禁止用 time.sleep 参与断言（§9.2-3）。"""

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)


class FakeResponse:
    def __init__(self, status_code: int = 200, *, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(payload or {"ok": status_code < 400})
        self._payload = payload or {"ok": status_code < 400}

    def json(self) -> dict:
        return dict(self._payload)


class FakeTransport:
    """假传输：按脚本返回 FakeResponse 或抛脚本化异常，并记录调用序列。"""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def _call(self, method: str, url: str, *, status: int, error: Exception | None,
              payload: dict | None) -> FakeResponse:
        with self._lock:
            self.calls.append({
                "method": method,
                "url": url,
                "status": status,
                "error": type(error).__name__ if error is not None else None,
            })
        if error is not None:
            raise error
        return FakeResponse(status, payload=payload)

    def get(self, url: str, *, status: int = 200, error: Exception | None = None,
            payload: dict | None = None, **_: object) -> FakeResponse:
        return self._call("GET", url, status=status, error=error, payload=payload)

    def post(self, url: str, *, status: int = 200, error: Exception | None = None,
             payload: dict | None = None, **_: object) -> FakeResponse:
        return self._call("POST", url, status=status, error=error, payload=payload)


class FakeSession:
    """假会话对象：注册表只按引用保存，不解释内容。"""

    def __init__(self, tag: str = "renewed") -> None:
        self.tag = tag

    def __repr__(self) -> str:  # pragma: no cover - 便于失败时阅读
        return f"<FakeSession {self.tag}>"


class FakeLoginClient:
    """假登录客户端：只计数，绝不保存口令；延迟用回调而不是真实等待。"""

    def __init__(self, *, token_expires_in: int | None = None,
                 error: Exception | None = None,
                 on_login=None,
                 expected_password: str | None = None) -> None:
        self.login_calls = 0
        self.usernames: list[str] = []
        self.password_matched: bool | None = None
        self.token_expires_in = token_expires_in
        self.error = error
        self.on_login = on_login
        self._expected_password = expected_password
        self._lock = threading.Lock()

    def login(self, username: str, password: str):
        with self._lock:
            self.login_calls += 1
            self.usernames.append(username)
            if self._expected_password is not None:
                self.password_matched = hmac.compare_digest(
                    str(password), str(self._expected_password)
                )
        if self.on_login is not None:
            self.on_login(self)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            session=FakeSession("renewed"),
            token_expires_in=self.token_expires_in,
            auth_mode="password",
        )


def _build(*, system: str = "aras", source_root: str = ARAS_ROOT,
           ttl: timedelta = timedelta(hours=8), clock: FakeClock | None = None,
           credentials: dict | None = None, client: FakeLoginClient | None = None,
           **options) -> SimpleNamespace:
    clock = clock or FakeClock()
    registry = DomainSessionRegistry(ttl=ttl, clock=clock)
    registry.mark_authenticated(system, FakeSession("initial"), principal=PRINCIPAL,
                                source_root=source_root)
    account_ref = registry.identity_binding(system)[1]
    values = {"domain": (PRINCIPAL, PASSWORD)} if credentials is None else credentials
    provider = MemoryCredentialProvider(values)
    clients = {system: (lambda: client)} if client is not None else {}
    coordinator = SessionRenewalCoordinator(registry, provider, clients, clock=clock, **options)
    return SimpleNamespace(
        registry=registry, provider=provider, client=client, coordinator=coordinator,
        clock=clock, account_ref=account_ref, source_root=source_root, system=system,
    )


def _operation(transport: FakeTransport, url: str, *, fail_first: int = 1,
               error_factory=None):
    """真实调用链的业务操作：假传输 → 401/异常 → 协调器分类。"""
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        expired = calls["n"] <= fail_first
        if expired and error_factory is not None:
            return transport.get(url, error=error_factory())
        response = transport.get(url, status=401 if expired else 200)
        if response.status_code == 401:
            raise ArasAuthenticationError("Aras login page returned")
        return response

    return operation, calls


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _run_threads(count: int, worker) -> None:
    barrier = threading.Barrier(count)
    threads = [threading.Thread(target=worker, args=(barrier,)) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20.0)
    assert not any(thread.is_alive() for thread in threads), "worker thread did not finish"


# ── §9.3 T1–T13 ─────────────────────────────────────────────────────────────


def test_t1_ten_concurrent_expired_requests_renew_once() -> None:
    """T1：10 个并发过期请求只登录一次，10 个调用方都拿到成功会话。"""
    client = FakeLoginClient(expected_password=PASSWORD)
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    assert env.registry.state("aras") == SESSION_STATE_EXPIRED
    transport = FakeTransport()
    results: list[FakeResponse] = []
    errors: list[BaseException] = []
    # 让 leader 的登录等到 9 个 follower 都进入同一次续期（单飞窗口，不参与断言）。
    def on_login(_client) -> None:
        assert env.coordinator.await_waiters("aras", env.account_ref, 9, 5.0) is True

    client.on_login = on_login

    def worker(barrier: threading.Barrier) -> None:
        operation, _calls = _operation(transport, f"{ARAS_ROOT}/EWO")
        barrier.wait(10.0)
        try:
            results.append(env.coordinator.run_with_renewal(
                "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
            ))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    _run_threads(10, worker)

    assert client.login_calls == 1
    assert client.password_matched is True
    assert errors == []
    assert len(results) == 10
    assert all(response.status_code == 200 for response in results)
    # 10 次首次 401 + 10 次重放 200
    assert len(transport.calls) == 20
    assert env.registry.state("aras") == SESSION_STATE_VALID
    assert env.registry.session("aras") is not None


def test_t2_single_flight_network_failure_shared_without_retry() -> None:
    """T2：leader 网络失败 → 登录 1 次、全部等待者同一闭集错误、状态 expired、不重试。"""
    client = FakeLoginClient(error=ConnectionError("simulated connection reset"))
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    errors: list[SessionRecoveryError] = []

    def on_login(_client) -> None:
        assert env.coordinator.await_waiters("aras", env.account_ref, 3, 5.0) is True

    client.on_login = on_login

    def worker(barrier: threading.Barrier) -> None:
        operation, _calls = _operation(transport, f"{ARAS_ROOT}/EWO")
        barrier.wait(10.0)
        try:
            env.coordinator.run_with_renewal(
                "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
            )
        except SessionRecoveryError as exc:
            errors.append(exc)

    _run_threads(4, worker)

    assert client.login_calls == 1
    assert len(errors) == 4
    assert {error.code for error in errors} == {"service_unavailable"}
    assert all(isinstance(error, UpstreamUnavailable) for error in errors)
    assert env.registry.state("aras") == SESSION_STATE_EXPIRED
    # 只有 4 次首次请求：失败后不自动重试、不重放。
    assert len(transport.calls) == 4
    assert env.coordinator.diagnostic_counts()["service_unavailable"] >= 1


def test_t3_renewal_success_replays_idempotent_read_once() -> None:
    """T3：续期成功后 idempotent_read 重放一次，诊断记录 replayed=true。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    operation, calls = _operation(transport, f"{ARAS_ROOT}/EWO")

    response = env.coordinator.run_with_renewal(
        "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
    )

    assert response.status_code == 200
    assert calls["n"] == 2
    assert client.login_calls == 1
    assert [call["status"] for call in transport.calls] == [401, 200]
    last = env.coordinator.last_operation()
    assert last["replayed"] is True
    assert last["attempt"] == 2
    assert last["code"] is None
    assert env.registry.state("aras") == SESSION_STATE_VALID


def test_t4_unsafe_side_effect_is_not_replayed_after_renewal() -> None:
    """T4：unsafe_side_effect 续期成功也不重放，返回 generation_unknown + confirm。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    operation, calls = _operation(transport, f"{ARAS_ROOT}/NCR/export")

    with pytest.raises(GenerationUnknown) as caught:
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=UNSAFE_SIDE_EFFECT
        )

    error = caught.value
    assert error.code == "generation_unknown"
    assert error.http_status == 409
    assert error.action == "confirm"
    assert error.retryable is False
    assert calls["n"] == 1
    assert len(transport.calls) == 1
    assert client.login_calls == 1          # 续期确实发生（为后续操作恢复会话）
    assert env.registry.state("aras") == SESSION_STATE_VALID


def test_t5_no_response_timeout_on_unsafe_side_effect_is_generation_unknown() -> None:
    """T5：已发出但无响应的 unsafe 操作 → generation_unknown，业务调用 1 次。"""
    client = FakeLoginClient()
    env = _build(client=client)
    transport = FakeTransport()
    operation, calls = _operation(
        transport, f"{ARAS_ROOT}/NCR/export",
        error_factory=lambda: TimeoutError("simulated transport timeout"),
    )

    with pytest.raises(GenerationUnknown) as caught:
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=UNSAFE_SIDE_EFFECT
        )

    assert caught.value.action == "confirm"
    assert calls["n"] == 1
    assert transport.calls[0]["error"] == "TimeoutError"
    assert client.login_calls == 0          # 网络类永不触发续期
    assert env.registry.state("aras") == SESSION_STATE_VALID


def test_t6_forbidden_does_not_renew_or_clear_credentials() -> None:
    """T6：403 不续期、不清凭据、code=forbidden、HTTP 403。"""
    client = FakeLoginClient()
    env = _build(system="tdc", source_root=TDC_ROOT, client=client)
    transport = FakeTransport()
    operation, calls = _operation(
        transport, f"{TDC_ROOT}/sor/export",
        error_factory=lambda: TDCCrawlerError(
            "upstream refused", stage="status-validation", status_code=403
        ),
    )

    with pytest.raises(Forbidden) as caught:
        env.coordinator.run_with_renewal(
            "tdc", env.account_ref, operation, kind=IDEMPOTENT_READ
        )

    error = caught.value
    assert error.code == "forbidden"
    assert error.http_status == 403
    assert error.action == "none"
    assert error.retryable is False
    assert calls["n"] == 1
    assert client.login_calls == 0
    assert env.provider.is_available("domain") is True
    payload = error.to_error_payload()
    assert payload["type"] == "Forbidden"
    assert payload["code"] == "forbidden"
    assert payload["diagnostic"]["upstreamHttpStatus"] == 403


def test_t7_parse_failure_does_not_renew_and_counts_diagnostic() -> None:
    """T7：解析失败不续期、code=upstream_parse_error、诊断计数 +1。"""
    client = FakeLoginClient()
    env = _build(system="tdc", source_root=TDC_ROOT, client=client)
    transport = FakeTransport()
    operation, calls = _operation(
        transport, f"{TDC_ROOT}/sor/list",
        error_factory=lambda: TDCCrawlerError("bad payload", stage="parse-json"),
    )

    with pytest.raises(UpstreamParseError) as caught:
        env.coordinator.run_with_renewal(
            "tdc", env.account_ref, operation, kind=IDEMPOTENT_READ
        )

    assert caught.value.code == "upstream_parse_error"
    assert caught.value.http_status == 502
    assert caught.value.action == "none"
    assert calls["n"] == 1
    assert client.login_calls == 0
    assert env.coordinator.diagnostic_counts()["upstream_parse_error"] == 1


def test_t8_clear_during_renewal_discards_result() -> None:
    """T8：续期在途时 clear() → 回写被拒、状态 cleared、session() 为 None。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    client.on_login = lambda _client: env.coordinator.clear("aras")
    transport = FakeTransport()
    operation, calls = _operation(transport, f"{ARAS_ROOT}/EWO")

    with pytest.raises(SessionCleared) as caught:
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
        )

    assert caught.value.code == "session_cleared"
    assert env.registry.generation("aras") == 1
    assert env.registry.state("aras") == SESSION_STATE_CLEARED
    assert env.registry.session("aras") is None
    assert calls["n"] == 1


def test_t9_vault_epoch_change_during_renewal_discards_result() -> None:
    """T9：续期在途时凭据 store() → vaultEpoch 变化 → 结果作废。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    client.on_login = lambda _client: env.registry.bump_vault_epoch()
    transport = FakeTransport()
    operation, _calls = _operation(transport, f"{ARAS_ROOT}/EWO")

    with pytest.raises(SessionCleared):
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
        )

    assert env.registry.vault_epoch() == 1
    assert env.registry.session("aras") is None
    assert env.registry.state("aras") == SESSION_STATE_CLEARED


def test_t10_account_lockout_cooldowns_and_manual_reset() -> None:
    """T10：连续失败进入冷却；第 3 次失败后 login_locked 且不再自动尝试。"""
    clock = FakeClock()
    client = FakeLoginClient(error=ArasAuthError("rejected", stage="credentials-rejected"))
    env = _build(client=client, clock=clock)

    with pytest.raises(RenewalRejected) as first:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert first.value.code == "credential_invalid"
    assert client.login_calls == 1

    # 冷却中：第 2 次自动登录前必须等待 cooldown_seconds[0]=60s
    with pytest.raises(RenewalRejected) as cooling:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert cooling.value.code == "login_locked"
    assert client.login_calls == 1

    clock.advance(61)
    with pytest.raises(RenewalRejected) as second:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert second.value.code == "credential_invalid"
    assert client.login_calls == 2

    with pytest.raises(RenewalRejected) as cooling2:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert cooling2.value.code == "login_locked"
    assert client.login_calls == 2

    clock.advance(301)
    with pytest.raises(RenewalRejected) as third:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert third.value.code == "credential_invalid"
    assert client.login_calls == 3

    # 第 3 次失败后：无论等多久都不再自动尝试
    clock.advance(3600)
    with pytest.raises(RenewalRejected) as locked:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert locked.value.code == "login_locked"
    assert client.login_calls == 3
    assert env.registry.state("aras") == SESSION_STATE_FAILED

    # 手动登录清零失败计数（§5.3-6），代次不回退
    env.registry.mark_authenticated("aras", FakeSession("manual"), principal=PRINCIPAL,
                                    source_root=ARAS_ROOT)
    clock.advance(1)
    with pytest.raises(RenewalRejected) as after_manual:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert after_manual.value.code == "credential_invalid"
    assert client.login_calls == 4


def test_t11_missing_credentials_never_calls_login() -> None:
    """T11：无凭据 → can_renew=false、code=credential_unavailable、登录 0 次。"""
    client = FakeLoginClient()
    env = _build(client=client, credentials={})
    env.clock.advance(9 * 3600)

    snapshot = env.coordinator.snapshot("aras")
    assert snapshot.can_renew is False
    assert snapshot.state == SESSION_STATE_EXPIRED

    with pytest.raises(CredentialUnavailable) as caught:
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)

    assert caught.value.code == "credential_unavailable"
    assert caught.value.action == "relogin"
    assert client.login_calls == 0
    assert env.registry.state("aras") == SESSION_STATE_FAILED


def test_t12_state_machine_transitions() -> None:
    """T12：逐条断言 §7.3 转移表；cleared 是吸收态，只能经登录回到 valid。"""
    clock = FakeClock()
    registry = DomainSessionRegistry(clock=clock)
    assert registry.state("aras") == SESSION_STATE_NONE

    registry.mark_authenticated("aras", FakeSession("initial"), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    assert registry.state("aras") == SESSION_STATE_VALID

    clock.advance(9 * 3600)
    assert registry.state("aras") == SESSION_STATE_EXPIRED

    generation, vault_epoch = registry.begin_renewal("aras")
    assert registry.state("aras") == SESSION_STATE_RENEWING
    assert (generation, vault_epoch) == (0, 0)

    assert registry.commit_renewal(
        "aras", FakeSession("renewed"), principal=PRINCIPAL, source_root=ARAS_ROOT,
        generation=generation, vault_epoch=vault_epoch,
    ) is True
    assert registry.state("aras") == SESSION_STATE_VALID
    assert registry.payload()["aras"]["lastRenewedAt"] is not None

    registry.mark_failed("aras", "credential_invalid")
    assert registry.state("aras") == SESSION_STATE_FAILED
    assert registry.payload()["aras"]["lastErrorCode"] == "credential_invalid"
    with pytest.raises(ValueError):
        registry.mark_failed("aras", "not-a-registered-code")

    registry.mark_authenticated("aras", FakeSession("manual"), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    assert registry.state("aras") == SESSION_STATE_VALID

    registry.clear("aras")
    assert registry.state("aras") == SESSION_STATE_CLEARED
    assert registry.generation("aras") == 1

    # cleared 是吸收态：自动路径不得复活
    registry.mark_renewing("aras")
    assert registry.state("aras") == SESSION_STATE_CLEARED
    assert registry.commit_renewal(
        "aras", FakeSession("stale"), principal=PRINCIPAL, source_root=ARAS_ROOT,
        generation=0, vault_epoch=0,
    ) is False
    assert registry.state("aras") == SESSION_STATE_CLEARED
    assert registry.session("aras") is None

    registry.mark_authenticated("aras", FakeSession("manual"), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    assert registry.state("aras") == SESSION_STATE_VALID
    assert registry.generation("aras") == 1        # 代次不回退


def test_t13_no_secret_leaks_in_payload_errors_or_diagnostics() -> None:
    """T13：T1–T12 路径跑完后，payload/异常/诊断序列化文本不含合成口令。"""
    client = FakeLoginClient(expected_password=PASSWORD)
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    operation, _calls = _operation(transport, f"{ARAS_ROOT}/EWO")
    env.coordinator.run_with_renewal(
        "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
    )
    with pytest.raises(SessionRecoveryError) as forbidden:
        env.coordinator.run_with_renewal(
            "aras", env.account_ref,
            _operation(transport, f"{ARAS_ROOT}/EWO",
                       error_factory=lambda: TDCCrawlerError(
                           "refused", stage="status-validation", status_code=403))[0],
            kind=IDEMPOTENT_READ,
        )

    texts = [
        json.dumps(env.registry.payload(), ensure_ascii=False),
        json.dumps(env.coordinator.snapshot("aras").to_payload(), ensure_ascii=False),
        json.dumps(env.coordinator.last_operation(), ensure_ascii=False),
        json.dumps(env.coordinator.diagnostic_counts(), ensure_ascii=False),
        json.dumps(forbidden.value.to_error_payload(), ensure_ascii=False),
        str(forbidden.value),
        repr(forbidden.value),
    ]
    blob = "\n".join(texts)
    assert PASSWORD not in blob
    assert PRINCIPAL not in blob            # principal 原文绝不外泄（C2）
    assert "innovatorserver" not in blob    # 内网/来源根 URL 不进 payload/异常


# ── §10.3 U1–U6（注册表与协调器的边界断言）─────────────────────────────────


def test_u1_registry_existing_behaviour_is_unchanged() -> None:
    """U1：既有行为零回归（过期 / 清除 / bound_session 严格匹配 / 非法 source_root）。"""
    registry = DomainSessionRegistry()
    first = object()
    registry.mark_authenticated("aras", first, principal=PRINCIPAL, source_root=ARAS_ROOT)
    session, scope = registry.bound_session("aras", ARAS_ROOT + "/")
    assert session is first
    registry.mark_authenticated("aras", object(), principal=PRINCIPAL, source_root=ARAS_ROOT)
    assert registry.bound_session("aras", ARAS_ROOT)[1] == scope
    registry.mark_authenticated("aras", object(), principal=OTHER_PRINCIPAL,
                                source_root=ARAS_ROOT)
    assert registry.bound_session("aras", ARAS_ROOT)[1] != scope
    assert registry.bound_session("aras", ARAS_ROOT.replace("https:", "http:")) is None
    assert registry.bound_session("aras", ARAS_ROOT + "/other") is None
    assert OTHER_PRINCIPAL not in str(registry.payload())

    # 历史分支：仅标记状态不得继承既有绑定
    legacy = DomainSessionRegistry()
    legacy.mark_authenticated("aras", object(), principal=PRINCIPAL, source_root=ARAS_ROOT)
    legacy.mark_authenticated("aras")
    assert legacy.bound_session("aras", ARAS_ROOT) is None
    assert legacy.session("aras") is None

    # 过期会话惰性失效，不抛错
    expired = DomainSessionRegistry(ttl=timedelta(seconds=-1))
    expired.mark_authenticated("aras", object(), principal=PRINCIPAL, source_root=ARAS_ROOT)
    assert expired.session("aras") is None
    assert expired.bound_session("aras", ARAS_ROOT) is None

    # 清除后不得恢复
    cleared = DomainSessionRegistry()
    cleared.mark_authenticated("aras", object(), principal=PRINCIPAL, source_root=ARAS_ROOT)
    cleared.clear("aras")
    assert cleared.bound_session("aras", ARAS_ROOT) is None

    for root in ("https://user:pass@example.test/app",
                 "https://example.test/app?token=secret", "relative"):
        with pytest.raises(ValueError):
            cleared.mark_authenticated("aras", object(), principal=PRINCIPAL, source_root=root)


def test_u2_payload_key_set_is_old_four_plus_new_six() -> None:
    """U2：payload 键集 = 旧 4 键 + 新 6 键，且不含 principal/scope/sourceRoot。"""
    registry = DomainSessionRegistry()
    registry.mark_authenticated("aras", FakeSession(), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    payload = registry.payload()

    assert set(payload) == {"aras", "tdc"}
    for system in ("aras", "tdc"):
        assert set(payload[system]) == {
            "authenticated", "updatedAt", "expiresAt", "expired",
            "state", "generation", "accountMasked", "lastErrorCode",
            "lastRenewedAt", "canRenew",
        }
    assert payload["aras"]["accountMasked"] == "u***"        # 无域后缀：首字符 + 固定掩码
    assert payload["tdc"]["accountMasked"] is None
    assert payload["aras"]["generation"] == 0
    assert payload["aras"]["canRenew"] is True
    assert payload["tdc"]["canRenew"] is False
    # 裁决 Q9：带域账号时保留域后缀，绝不复用 scope 哈希
    registry.mark_authenticated("aras", FakeSession(), principal="user-a@example.test",
                                source_root=ARAS_ROOT)
    assert registry.payload()["aras"]["accountMasked"] == "u***@example.test"
    text = json.dumps(registry.payload(), ensure_ascii=False)
    for forbidden in ("principal", "scope", "sourceRoot", ARAS_ROOT, PRINCIPAL,
                      "user-a@example.test"):
        assert forbidden not in text


def test_u3_clock_injection_makes_expiry_deterministic() -> None:
    """U3：clock 注入生效——步进后 session() 立即返回 None。"""
    clock = FakeClock()
    registry = DomainSessionRegistry(clock=clock)
    registry.mark_authenticated("aras", FakeSession(), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    assert registry.session("aras") is not None
    clock.advance(8 * 3600 + 1)
    assert registry.session("aras") is None
    assert registry.state("aras") == SESSION_STATE_EXPIRED


def test_u4_commit_renewal_rejects_changed_generation_and_vault_epoch() -> None:
    """U4：代次/凭据纪元变化时 commit_renewal 返回 False 且未写入会话。"""
    clock = FakeClock()
    registry = DomainSessionRegistry(clock=clock)
    registry.mark_authenticated("aras", FakeSession("initial"), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    generation, vault_epoch = registry.begin_renewal("aras")

    registry.clear("aras")
    assert registry.commit_renewal(
        "aras", FakeSession("stale"), principal=PRINCIPAL, source_root=ARAS_ROOT,
        generation=generation, vault_epoch=vault_epoch,
    ) is False
    assert registry.session("aras") is None
    assert registry.state("aras") == SESSION_STATE_CLEARED

    registry.mark_authenticated("aras", FakeSession("manual"), principal=PRINCIPAL,
                                source_root=ARAS_ROOT)
    generation, vault_epoch = registry.begin_renewal("aras")
    registry.bump_vault_epoch()
    assert registry.commit_renewal(
        "aras", FakeSession("stale"), principal=PRINCIPAL, source_root=ARAS_ROOT,
        generation=generation, vault_epoch=vault_epoch,
    ) is False
    assert registry.session("aras") is None
    assert registry.state("aras") == SESSION_STATE_CLEARED


def test_u5_coordinator_without_credentials_never_calls_login() -> None:
    """U5：无凭据时协调器不调用登录客户端（login_calls == 0）。"""
    client = FakeLoginClient()
    env = _build(client=client, credentials={})
    with pytest.raises(CredentialUnavailable):
        env.coordinator.renew("aras", account_ref=env.account_ref, generation=0)
    assert client.login_calls == 0
    assert env.coordinator.snapshot("aras").can_renew is False


def test_u6_unsafe_side_effect_never_replays_even_after_successful_renewal() -> None:
    """U6：unsafe_side_effect 即便续期成功也不重放（business_calls == 1）。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    operation, calls = _operation(transport, f"{ARAS_ROOT}/NCR/export")

    with pytest.raises(GenerationUnknown):
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=UNSAFE_SIDE_EFFECT
        )

    assert calls["n"] == 1
    assert client.login_calls == 1
    assert env.coordinator.last_operation()["replayed"] is False


# ── 契约表与边界（§4.3 / §5.3-7 / §6.3）────────────────────────────────────


@pytest.mark.parametrize("code,error_type,status,action,retryable", [
    ("unauthenticated", "AuthenticationError", 401, "renew", False),
    ("login_page", "AuthenticationError", 401, "renew", False),
    ("session_cleared", "DomainLoginRequired", 401, "relogin", False),
    ("forbidden", "Forbidden", 403, "none", False),
    ("service_unavailable", "ServiceUnavailable", 503, "wait", True),
    ("timeout", "ServiceUnavailable", 503, "wait", True),
    ("upstream_parse_error", "UpstreamContractError", 502, "none", False),
    ("credential_unavailable", "CredentialVaultUnavailable", 503, "relogin", False),
    ("credential_invalid", "DomainLoginRejected", 401, "relogin", False),
    ("login_challenge", "DomainLoginRejected", 401, "relogin", False),
    ("login_locked", "DomainLoginRejected", 401, "relogin", False),
    ("generation_unknown", "ConflictError", 409, "confirm", False),
])
def test_error_code_table_matches_contract(code, error_type, status, action, retryable) -> None:
    """§4.3 闭集：code → type / HTTP / action / retryable 唯一映射。"""
    from services import session_recovery

    assert code in RECOVERY_ERROR_CODES
    error = session_recovery._error_for(code, system="aras")
    assert error.code == code
    assert error.error_type == error_type
    assert error.http_status == status
    assert error.action == action
    assert error.retryable is retryable
    assert error.to_error_payload()["diagnostic"] == {"system": "aras"}
    assert str(error) == session_recovery._MESSAGES[code]


def test_renewal_ttl_uses_upstream_expires_in_with_safety_margin() -> None:
    """§5.3-7：TTL 取 min(8h, upstream_expires_in − 安全余量)。"""
    clock = FakeClock()
    client = FakeLoginClient(token_expires_in=120)
    env = _build(system="tdc", source_root=TDC_ROOT, client=client, clock=clock)
    clock.advance(9 * 3600)

    snapshot = env.coordinator.renew("tdc", account_ref=env.account_ref, generation=0)

    expires_at = _parse_iso(env.registry.payload()["tdc"]["expiresAt"])
    assert timedelta(seconds=50) <= expires_at - clock() <= timedelta(seconds=70)
    assert snapshot.state == SESSION_STATE_VALID
    assert env.registry.payload()["tdc"]["lastRenewedAt"] is not None


def test_renewal_success_exposes_cache_invalidation_signal() -> None:
    """§5.3-7 / 裁决 Q8：续期成功暴露可供 TDC 导出缓存失效的代次信号。

    本任务只提供信号（``payload().lastRenewedAt`` / ``updatedAt`` / ``expiresAt``
    变化，以及 ``SessionSnapshot.last_renewed_at``）；读取该信号并失效
    ``tdc_export_cache`` 的接线由 DSH-V2-16/17 承接（契约 §10.2）。
    """
    clock = FakeClock()
    client = FakeLoginClient()
    env = _build(system="tdc", source_root=TDC_ROOT, client=client, clock=clock)
    before = env.registry.payload()["tdc"]
    clock.advance(9 * 3600)

    snapshot = env.coordinator.renew("tdc", account_ref=env.account_ref, generation=0)

    after = env.registry.payload()["tdc"]
    assert snapshot.last_renewed_at is not None
    assert after["lastRenewedAt"] == snapshot.last_renewed_at
    assert after["updatedAt"] != before["updatedAt"]
    assert after["expiresAt"] != before["expiresAt"]
    assert after["state"] == SESSION_STATE_VALID


def test_snapshot_payload_is_whitelisted() -> None:
    """§8.2：SessionSnapshot.to_payload() 只输出白名单键，不含 principal/scope/URL。"""
    client = FakeLoginClient()
    env = _build(client=client)
    payload = env.coordinator.snapshot("aras").to_payload()
    assert set(payload) == {
        "system", "state", "generation", "accountMasked",
        "lastRenewedAt", "lastErrorCode", "canRenew",
    }
    text = json.dumps(payload, ensure_ascii=False)
    assert PRINCIPAL not in text
    assert ARAS_ROOT not in text


def test_replay_is_bounded_to_one_and_second_401_is_not_renewed_again() -> None:
    """§6.2 末行：同一操作第 2 次遇到 401 不再续期、不再重放。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    operation, calls = _operation(transport, f"{ARAS_ROOT}/EWO", fail_first=2)

    with pytest.raises(SessionExpired) as caught:
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
        )

    assert caught.value.replayed is True
    assert calls["n"] == 2
    assert client.login_calls == 1
    assert env.coordinator.last_operation()["attempt"] == 2


def test_idempotent_write_with_key_reuses_same_operation_closure() -> None:
    """§6.3：idempotent_write_with_key 必须带幂等键，重放复用同一闭包（同一 opId）。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    seen: list[str] = []
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        seen.append("op-1")            # 同一请求体 + 同一幂等键
        response = transport.post(f"{ARAS_ROOT}/report",
                                  status=401 if calls["n"] == 1 else 200)
        if response.status_code == 401:
            raise ArasAuthenticationError("Aras login page returned")
        return response

    env.coordinator.run_with_renewal(
        "aras", env.account_ref, operation,
        kind=IDEMPOTENT_WRITE_WITH_KEY, idempotency_key="op-1",
    )
    assert seen == ["op-1", "op-1"]
    assert calls["n"] == 2
    assert client.login_calls == 1

    with pytest.raises(ValueError):
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=IDEMPOTENT_WRITE_WITH_KEY
        )
    with pytest.raises(ValueError):
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind="unsafe_maybe"
        )


def test_cancellation_is_never_converted_to_a_retryable_code() -> None:
    """取消不是错误：原样上抛，不续期、不改写成可重试码。"""
    client = FakeLoginClient()
    env = _build(client=client)

    def operation():
        raise CrawlCancelled("cancelled at pagination boundary")

    with pytest.raises(CrawlCancelled):
        env.coordinator.run_with_renewal(
            "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
        )
    assert client.login_calls == 0


def test_clear_cancels_in_flight_renewal_for_followers() -> None:
    """§7.2-1：clear() 先作废代次再取消在途续期，follower 立即得到 session_cleared。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    leader_errors: list[SessionRecoveryError] = []
    follower_errors: list[SessionRecoveryError] = []
    leader_in_login = threading.Event()
    clear_done = threading.Event()

    def on_login(_client):
        leader_in_login.set()
        assert clear_done.wait(5.0), "clear() did not run while the renewal was in flight"

    client.on_login = on_login

    def run(errors: list[SessionRecoveryError]) -> None:
        operation, _calls = _operation(transport, f"{ARAS_ROOT}/EWO")
        try:
            env.coordinator.run_with_renewal(
                "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
            )
        except SessionRecoveryError as exc:
            errors.append(exc)

    leader = threading.Thread(target=run, args=(leader_errors,))
    leader.start()
    assert leader_in_login.wait(5.0), "leader never reached the login call"

    follower = threading.Thread(target=run, args=(follower_errors,))
    follower.start()
    assert env.coordinator.await_waiters("aras", env.account_ref, 1, 5.0) is True

    snapshots = env.coordinator.clear("aras")
    clear_done.set()
    leader.join(10.0)
    follower.join(10.0)
    assert not leader.is_alive() and not follower.is_alive()

    assert [error.code for error in follower_errors] == ["session_cleared"]
    assert [error.code for error in leader_errors] == ["session_cleared"]
    assert snapshots["aras"].state == SESSION_STATE_CLEARED
    assert env.registry.state("aras") == SESSION_STATE_CLEARED
    assert env.registry.session("aras") is None


# ── 主控补充：评审低级发现的回归 ───────────────────────────────────────────


def test_lead_401_after_peer_renewal_reuses_session_without_second_login() -> None:
    """操作开始后、其 401 返回前已有别的请求完成续期：复用新会话，不再登录。"""
    client = FakeLoginClient()
    env = _build(client=client)
    env.clock.advance(9 * 3600)
    transport = FakeTransport()
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        if calls["n"] == 1:
            # 旧会话请求在途期间，另一请求完成了续期（时间前进 1 秒）。
            env.clock.advance(1)
            env.coordinator.renew("aras", account_ref=env.account_ref,
                                  generation=env.registry.generation("aras"))
            transport.get(f"{ARAS_ROOT}/EWO", status=401)
            raise ArasAuthenticationError("Aras login page returned")
        return transport.get(f"{ARAS_ROOT}/EWO", status=200)

    response = env.coordinator.run_with_renewal(
        "aras", env.account_ref, operation, kind=IDEMPOTENT_READ
    )

    assert response.status_code == 200
    assert calls["n"] == 2
    assert client.login_calls == 1


def test_clear_removes_cancelled_flight_so_new_request_runs_own_checks() -> None:
    """clear() 取消在途续期后，同键新请求不再加入被取消的旧航班。"""
    env = _build(client=FakeLoginClient())
    key = ("aras", env.account_ref)
    with env.coordinator._lock:
        from services.session_recovery import _Flight  # 内部航班表的最小注入
        stale = _Flight(key)
        env.coordinator._flights[key] = stale

    env.coordinator.clear("aras")

    assert stale.done.is_set()
    assert not env.coordinator.in_flight("aras", env.account_ref)
