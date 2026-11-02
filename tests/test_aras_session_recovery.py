# -*- coding: utf-8 -*-
"""DSH-V2-16：Aras 会话恢复链接入（真实调用链：create_app + app.test_client()）。

验收覆盖（``docs/refactor-v2/DSH_IDENTITY_CONTRACT.md`` §10.2 冻结接线范围）：

* 真实业务调用 ``ArasProjectStatusConnector.collect`` 消费统一续期协调器
  （不是只新增未消费的 helper）；
* 过期 401 → 单次续期 → 只读操作**原位**重放一次并成功；
* 403（权限）不续期、不清凭据、不重放；
* 统一清除 ``DELETE /api/settings/sessions`` 经协调器 ``clear()``：代次 +1、
  取消在途续期，迟到的续期结果不回填；
* ``unsafe_side_effect``（Aras 官方 NCR 导出）续期后不重放 → ``generation_unknown``；
* 登录失败结果项增量附 §4.3 闭集 ``code``，既有键与状态码不变。

真实内网登录/续期：**待验证**。本文件只用假传输、假 DPAPI 后端与内存凭据，
不读真实 keys/DPAPI 库、不打真实网络；口令一律运行期唯一合成值。
"""

from __future__ import annotations

import hmac
import json
import threading
import uuid
from types import SimpleNamespace

import pytest

import web.app as web_app
import web.host_boot as web_host_boot
import services.aras_auth as aras_auth
from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from core.db_manager import DatabaseManager
from core.domain_identity import SESSION_STATE_CLEARED, WindowsDPAPICredentialVault
from services import project_status_connectors
from services.aras_auth import ArasAuthError
from services.aras_crawler import ArasAuthenticationError
from services.project_status_connectors import ArasProjectStatusConnector, RetryingConnector
from services.project_status_sync_runner import SyncBindingContext
from services.session_recovery import (
    Forbidden,
    GenerationUnknown,
    SessionCleared,
)
from tests.test_settings_security import FakeDPAPIBackend

#: 合成值（契约 §9.2-5）：占位账号与占位来源根，绝不使用真实用户名/内网地址。
PRINCIPAL = "user-a"
ARAS_ROOT = "http://ecm.example.test/innovatorserver"
LOOPBACK_HEADERS = {"Host": "localhost", "Origin": "http://localhost"}


def _runtime_opaque() -> str:
    """运行期唯一合成秘密（对齐 tests/test_settings_security.py 的口径）。"""
    return f"opq-{uuid.uuid4().hex}"


def _assert_secret_absent(secret: str, *values: object) -> None:
    rendered = "\n".join(
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=repr)
        for value in values
    )
    assert secret not in rendered


# ── 夹具：假会话 / 假登录客户端 / 假 Aras 传输 ───────────────────────────────


class FakeSession:
    """假会话对象：注册表只按引用保存，不解释内容。"""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def __repr__(self) -> str:  # pragma: no cover - 便于失败时阅读
        return f"<FakeSession {self.tag}>"


class FakeLoginClient:
    """假登录客户端：只计数与校验口令，绝不保存口令明文。"""

    def __init__(
        self,
        *,
        tag: str,
        error: BaseException | None = None,
        expected_password: str | None = None,
        started: threading.Event | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.tag = tag
        self.error = error
        self.expected_password = expected_password
        self.started = started
        self.gate = gate
        self.login_calls = 0
        self.usernames: list[str] = []
        self._lock = threading.Lock()

    def login(self, username: str, password: str):
        with self._lock:
            self.login_calls += 1
            self.usernames.append(str(username))
        if self.expected_password is not None:
            assert hmac.compare_digest(str(password), self.expected_password)
        if self.started is not None:
            self.started.set()
        if self.gate is not None:
            assert self.gate.wait(5), "renewal gate was never released"
        if self.error is not None:
            raise self.error
        return SimpleNamespace(session=FakeSession(self.tag), token_expires_in=None)


class NoLoginAuth:
    """共享会话可用时连接器不得再自行登录：被调用即失败。"""

    base_url = ARAS_ROOT

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def login(self, username: str, password: str):  # pragma: no cover - 触发即失败
        raise AssertionError("connector must reuse the shared domain session")


class FailingLogin:
    """统一登录路由用的失败客户端：直接抛注入的闭集异常。"""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def login(self, username: str, password: str):
        raise self.error


class FakeUpstreamRejection(RuntimeError):
    """假传输：带 HTTP 状态码的上游拒绝。

    Aras 抓取当前把 401/403 合并成 ``ArasAuthenticationError``（拆分属
    DSH-V2-15b），所以 403 用带状态码的合成异常驱动，验证的是协调器分类
    （403 → forbidden，永不续期）与连接器的接法。
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"upstream rejected with HTTP {status_code}")
        self.status_code = status_code


def _ewo_result():
    return SimpleNamespace(
        rows=[{"_no": "EWO-1", "_rsp_name": "负责人"}],
        complete=True,
        stop_reason="short_page",
    )


class CrawlerScript:
    """假 Aras 传输：按脚本队列返回结果或抛异常，并记录用到的会话。"""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self._index = 0
        self._lock = threading.Lock()
        self.calls: list[str] = []
        self.sessions: list[object] = []

    def _next(self):
        with self._lock:
            outcome = self._outcomes[self._index]
            self._index += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _record(self, name: str, session: object) -> None:
        with self._lock:
            self.calls.append(name)
            self.sessions.append(session)

    def factory(self, base_url, session=None, timeout=None, prewarm=False):
        script = self

        class _Crawler:
            def __init__(self) -> None:
                self.session = session

            def crawl_ewo_report_all(self, filters, max_records):
                script._record("ewo", session)
                return script._next()

            def crawl_paa_report_all(self, filters, max_records):
                script._record("paa", session)
                return script._next()

            def query_ncr_approval_progress(self, filters):
                script._record("ncr_progress", session)
                return script._next()

        return _Crawler()


def _ewo_context() -> SyncBindingContext:
    return SyncBindingContext(
        binding_id=16,
        deliverable_id="VPI-T2-D3",
        phase_id="VPI-T2",
        source_type="aras",
        external_key="EWO-1",
        match_rule={"reportType": "ewo", "ewoNo": "EWO-1"},
        mapping={"owner": "_rsp_name"},
        cursor={},
        expected_deliverable_updated_at="v1",
        run_id=16,
        credential_ref="domain",
    )


def _ncr_context() -> SyncBindingContext:
    return SyncBindingContext(
        binding_id=17,
        deliverable_id="VPI-T2-D7",          # NCR 进度：官方导出（unsafe_side_effect）
        phase_id="VPI-T2",
        source_type="aras",
        external_key="NCR-1",
        match_rule={},
        mapping={},
        cursor={},
        expected_deliverable_updated_at="v1",
        run_id=17,
        credential_ref="domain",
    )


# ── 组合根夹具：create_app + test_client，假 DPAPI 后端 + 假传输 ─────────────


@pytest.fixture()
def aras_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """真实 create_app 装配：协调器/注册表/凭据提供者都来自应用组合根。"""
    db = DatabaseManager(db_path=tmp_path / "aras_session_recovery.db")
    db.init_database()
    vault = WindowsDPAPICredentialVault(path=tmp_path / "vault.dat", backend=FakeDPAPIBackend)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr(web_app, "WindowsDPAPICredentialVault", lambda *args, **kwargs: vault)

    route_client = FakeLoginClient(tag="route")
    tdc_client = FakeLoginClient(tag="tdc")
    renewal_client = FakeLoginClient(tag="renewed")
    monkeypatch.setattr(web_host_boot, "ArasECMAuthClient", lambda: route_client)
    monkeypatch.setattr(web_host_boot, "TDCPasswordAuthClient", lambda: tdc_client)
    monkeypatch.setattr(
        web_host_boot, "store_windows_generic_credential", lambda ref, user, secret: None
    )
    monkeypatch.setattr(web_host_boot, "delete_windows_generic_credential", lambda ref: True)
    # 协调器的登录客户端工厂（组合根装配点）替换为假客户端：不触发真实登录。
    monkeypatch.setattr(
        web_app, "_session_renewal_clients", lambda: {"aras": lambda: renewal_client}
    )

    app = web_app.create_app()
    app.config.update(TESTING=True)
    env = SimpleNamespace(
        app=app,
        client=app.test_client(),
        registry=app.extensions["domain_sessions"],
        coordinator=app.extensions["session_renewal"],
        vault=vault,
        route_client=route_client,
        tdc_client=tdc_client,
        renewal_client=renewal_client,
        tmp_path=tmp_path,
    )
    try:
        yield env
    finally:
        # 绑定是进程级装配状态：测试结束必须清空，避免影响其他用例。
        project_status_connectors.bind_session_renewal(None, None)


def _login(env, *, username: str = PRINCIPAL, password: str | None = None):
    secret = password or _runtime_opaque()
    response = env.client.post(
        "/api/settings/domain-login",
        json={"username": username, "password": secret, "saveForScheduled": True},
        headers=LOOPBACK_HEADERS,
    )
    return response, secret


def _connector(env, secret: str, script: CrawlerScript) -> ArasProjectStatusConnector:
    return ArasProjectStatusConnector(
        MemoryCredentialProvider({"domain": (PRINCIPAL, secret)}),
        ArchiveStore({"default": env.tmp_path}, reserve_bytes=0),
        auth_factory=NoLoginAuth,
        crawler_factory=script.factory,
    )


# ── 1. 过期 401 → 单次续期 → 只读操作原位重放成功 ───────────────────────────


def test_expired_401_renews_once_and_replays_read_in_place(aras_env) -> None:
    env = aras_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    assert login_response.get_json()["data"]["results"]["aras"] == {"ok": True}
    env.renewal_client.expected_password = secret

    route_session = env.registry.session("aras")
    assert route_session is not None
    generation_before = env.registry.generation("aras")
    account_ref_before = env.registry.identity_binding("aras")[1]
    assert account_ref_before

    script = CrawlerScript(
        [ArasAuthenticationError("Aras HTTP 401 expired session"), _ewo_result()]
    )
    snapshot = _connector(env, secret, script).collect(_ewo_context())

    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {"owner": "负责人"}
    # 首次 401 + 重放一次，且重放拿到的是协调器写回的新会话（原位恢复）。
    assert script.calls == ["ewo", "ewo"]
    assert script.sessions[0] is route_session
    renewed_session = env.registry.session("aras")
    assert renewed_session is not None and renewed_session is not route_session
    assert script.sessions[1] is renewed_session
    # 单次续期：协调器只登录一次，连接器自己没有额外登录。
    assert env.renewal_client.login_calls == 1
    assert env.renewal_client.usernames == [PRINCIPAL]
    assert env.route_client.login_calls == 1
    # 续期不改代次，绑定与凭据保持。
    assert env.registry.generation("aras") == generation_before
    assert env.registry.identity_binding("aras")[1] == account_ref_before
    assert env.vault.is_configured() is True

    operation = env.coordinator.last_operation()
    assert operation == {
        "system": "aras",
        "kind": "idempotent_read",
        "attempt": 2,
        "replayed": True,
        "code": None,
    }
    _assert_secret_absent(secret, login_response.get_json(), env.registry.payload(), operation)


# ── 2. 403 不续期、不清凭据、不重放 ─────────────────────────────────────────


def test_forbidden_403_never_renews_or_clears_credentials(aras_env) -> None:
    env = aras_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    session_before = env.registry.session("aras")
    generation_before = env.registry.generation("aras")

    script = CrawlerScript([FakeUpstreamRejection(403)])
    with pytest.raises(Forbidden) as excinfo:
        _connector(env, secret, script).collect(_ewo_context())

    error = excinfo.value
    assert error.code == "forbidden"
    assert error.http_status == 403
    assert error.action == "none"
    assert error.retryable is False
    assert script.calls == ["ewo"]                      # 不重放
    assert env.renewal_client.login_calls == 0          # 不续期
    assert env.registry.session("aras") is session_before
    assert env.registry.generation("aras") == generation_before
    assert env.vault.is_configured() is True            # 不清凭据
    _assert_secret_absent(secret, str(error), error.to_error_payload())


# ── 3. 清除竞态：迟到的续期结果不回填 ───────────────────────────────────────


def test_clear_during_renewal_discards_late_renewal_result(aras_env) -> None:
    env = aras_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    env.renewal_client.expected_password = secret
    started = threading.Event()
    release = threading.Event()
    env.renewal_client.started = started
    env.renewal_client.gate = release

    script = CrawlerScript([ArasAuthenticationError("Aras HTTP 401 expired session")])
    connector = _connector(env, secret, script)
    outcome: dict[str, BaseException] = {}

    def _collect() -> None:
        try:
            connector.collect(_ewo_context())
        except BaseException as exc:  # noqa: BLE001 - 测试只关心闭集错误
            outcome["error"] = exc

    worker = threading.Thread(target=_collect, name="aras-session-recovery")
    worker.start()
    try:
        assert started.wait(5), "renewal did not start"
        generation_before = env.registry.generation("aras")
        clear_response = env.client.delete(
            "/api/settings/sessions", json={}, headers=LOOPBACK_HEADERS
        )
        assert clear_response.status_code == 200
        body = clear_response.get_json()
        # 既有键与 200 不变；增量 results 带 §4.3 闭集码。
        assert body["ok"] is True
        assert body["data"]["results"]["aras"] == {"ok": True, "code": "session_cleared"}
        assert body["data"]["sessions"]["aras"]["state"] == SESSION_STATE_CLEARED
    finally:
        release.set()
        worker.join(5)

    assert not worker.is_alive()
    error = outcome.get("error")
    assert isinstance(error, SessionCleared)
    assert error.code == "session_cleared"
    # 代次 +1 且在途续期被取消：迟到的续期结果绝不回填。
    assert env.registry.generation("aras") == generation_before + 1
    assert env.registry.session("aras") is None
    assert env.registry.state("aras") == SESSION_STATE_CLEARED
    assert script.calls == ["ewo"]                      # 没有重放
    _assert_secret_absent(secret, str(error), env.registry.payload())


# ── 4. unsafe_side_effect：续期后不重放 → generation_unknown ─────────────────


def test_unsafe_ncr_export_is_not_replayed_after_renewal(aras_env) -> None:
    env = aras_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    env.renewal_client.expected_password = secret

    script = CrawlerScript([ArasAuthenticationError("Aras HTTP 401 expired session")])
    with pytest.raises(GenerationUnknown) as excinfo:
        _connector(env, secret, script).collect(_ncr_context())

    error = excinfo.value
    assert error.code == "generation_unknown"
    assert error.http_status == 409
    assert error.action == "confirm"
    assert error.retryable is False
    # 官方导出可能已在上游产生产物：只尝试一次，绝不自动重放。
    assert script.calls == ["ncr_progress"]
    assert env.renewal_client.login_calls == 1          # 续期只为后续操作可用
    operation = env.coordinator.last_operation()
    assert operation["kind"] == "unsafe_side_effect"
    assert operation["attempt"] == 1
    assert operation["replayed"] is False
    assert operation["code"] == "generation_unknown"
    _assert_secret_absent(secret, str(error), error.to_error_payload(), operation)


# ── 5. 外层有界重试不得重发 generation_unknown ───────────────────────────────


def test_generation_unknown_is_not_retried_by_outer_retrying_connector(aras_env) -> None:
    env = aras_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200

    # 已发出但无响应（超时）：unsafe_side_effect 升级为 generation_unknown。
    script = CrawlerScript([TimeoutError("no response")])
    inner = _connector(env, secret, script)
    collect_calls: list[int] = []

    class _Collect:
        def collect(self, context):
            collect_calls.append(1)
            return inner.collect(context)

    with pytest.raises(GenerationUnknown) as excinfo:
        RetryingConnector(_Collect(), sleeper=lambda delay: None).collect(_ncr_context())

    assert excinfo.value.code == "generation_unknown"
    assert collect_calls == [1]                 # 外层有界重试不重发（契约 §6.4）
    assert script.calls == ["ncr_progress"]     # 上游只被调用一次
    assert env.renewal_client.login_calls == 0  # 没有 401，不触发续期


# ── 6. 统一登录失败：增量 code，既有键与状态码不变 ──────────────────────────


def test_domain_login_failure_items_carry_closed_set_code(aras_env, monkeypatch) -> None:
    env = aras_env
    # 生产形态（services/aras_auth.py::_reject）：stage 是传输阶段，
    # recovery_code 是按契约 §4.2 登记的闭集语义（口令被拒 → credential_invalid）。
    aras_error = ArasAuthError(
        "ECM username/password login failed or requires additional verification",
        stage="ecm-credentials",
        status_code=200,
        recovery_code="credential_invalid",
    )
    monkeypatch.setattr(
        web_host_boot, "ArasECMAuthClient", lambda: FailingLogin(aras_error)
    )
    monkeypatch.setattr(
        web_host_boot,
        "TDCPasswordAuthClient",
        lambda: FailingLogin(RuntimeError("tdc offline")),
    )
    secret = _runtime_opaque()
    response = env.client.post(
        "/api/settings/domain-login",
        json={"username": PRINCIPAL, "password": secret, "saveForScheduled": True},
        headers=LOOPBACK_HEADERS,
    )

    # 全失败仍是 401 + ok=false（既有语义不变）。
    assert response.status_code == 401
    body = response.get_json()
    assert body["ok"] is False
    results = body["data"]["results"]
    assert results["aras"]["ok"] is False
    assert "message" in results["aras"]                  # 既有键保留
    assert results["aras"]["code"] == "credential_invalid"
    assert results["tdc"]["ok"] is False
    assert results["tdc"]["code"] == "service_unavailable"
    assert "sessions" in body["data"]
    # 登录全失败：不得写凭据库（vaultEpoch 未 bump，凭据未配置）。
    assert env.vault.is_configured() is False
    assert env.registry.vault_epoch() == 0
    assert env.renewal_client.login_calls == 0            # 登录路由不触发续期
    _assert_secret_absent(secret, body)


# ── 7. 登录期 403（账号无 Aras 权限）→ forbidden，不清凭据、不续期 ───────────


def test_domain_login_403_is_forbidden_not_renewable(aras_env, monkeypatch) -> None:
    env = aras_env
    forbidden_error = ArasAuthError(
        "ECM Aras ValidateUser returned HTTP 403; the domain account lacks Aras access",
        stage="ecm-validate-user",
        status_code=403,
        recovery_code="forbidden",
    )
    monkeypatch.setattr(
        web_host_boot, "ArasECMAuthClient", lambda: FailingLogin(forbidden_error)
    )
    monkeypatch.setattr(
        web_host_boot, "TDCPasswordAuthClient", lambda: FailingLogin(RuntimeError("tdc offline"))
    )
    secret = _runtime_opaque()
    response = env.client.post(
        "/api/settings/domain-login",
        json={"username": PRINCIPAL, "password": secret, "saveForScheduled": True},
        headers=LOOPBACK_HEADERS,
    )

    assert response.status_code == 401                    # 既有信封语义不变
    results = response.get_json()["data"]["results"]
    assert results["aras"]["ok"] is False
    assert results["aras"]["code"] == "forbidden"          # 不是 unauthenticated
    assert env.renewal_client.login_calls == 0             # 403 永不续期
    # 登录路由的既有全清仍在（代次 +1 → cleared），失败不会把会话写回 valid。
    assert env.registry.state("aras") == SESSION_STATE_CLEARED
    assert env.registry.session("aras") is None
    assert env.vault.is_configured() is False              # 不清/不写凭据


# ── 8. 登录客户端自身声明闭集码（生产形态，不经路由）────────────────────────


def test_aras_reject_declares_closed_recovery_code(monkeypatch) -> None:
    """``_reject`` 保持传输 stage 语义，同时按 §4.2 附带闭集恢复码。"""
    client = aras_auth.ArasECMAuthClient(session=object())
    monkeypatch.setattr(aras_auth, "_event_from_trace", lambda *args, **kwargs: None)
    monkeypatch.setattr(client, "_emit", lambda event: None)
    trace = SimpleNamespace(
        response=SimpleNamespace(status_code=200),
        stage="ecm-credentials",
        request_id="req-16a1b2c3",
    )

    with pytest.raises(ArasAuthError) as excinfo:
        client._reject(
            trace,
            "credentials-rejected",
            "ECM username/password login failed or requires additional verification",
            recovery_code="credential_invalid",
        )
    error = excinfo.value
    assert error.stage == "ecm-credentials"      # 既有 stage 语义不变
    assert error.status_code == 200
    assert error.recovery_code == "credential_invalid"

    # 未登记的码必须立刻失败，绝不污染 §4.3 闭集。
    with pytest.raises(ValueError):
        ArasAuthError("rejected", stage="ecm-credentials", recovery_code="not-a-code")
