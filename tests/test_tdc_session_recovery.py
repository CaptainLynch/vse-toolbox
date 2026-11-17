# -*- coding: utf-8 -*-
"""DSH-V2-17：TDC 会话恢复链接入与统一退出清除（真实调用链）。

验收覆盖（``docs/refactor-v2/DSH_IDENTITY_CONTRACT.md`` §3.2/§4/§6/§7/§10.2）：

* 真实业务调用 ``TDCProjectStatusConnector.collect`` 消费统一续期协调器
  （``run_with_renewal("tdc", …)``，不是只新增未消费的 helper）；
* 过期 401 → 单次续期 → 只读查询**原位**重放一次并成功（导出随后用新会话）；
* 403（权限）不续期、不清凭据、不重放；
* 统一清除 ``DELETE /api/settings/sessions`` 经协调器 ``clear()``：代次 +1、
  取消在途 TDC 续期，迟到的续期结果不回填；
* ``unsafe_side_effect``（TDC 官方工作簿导出会在上游生成文件）续期后不重放；
* 跨账号不复用共享会话；校验后绑定被切换时不改用新会话；
* 清除结果逐系统如实（失败项 ``ok:false`` + §4.3 闭集 ``code``），
  ``clearCredentialVault`` 失败保持既有 503；
* W3 顶栏三档徽章：用 Node 执行 ``SessionBadges.aggregateSessionStatus``，
  输入为真实路由 ``GET /api/settings`` 返回的 sessions payload；
* ``TDCAuthError.recovery_code``（401/403）与 feishukey 协议字段/``token_expires_in``
  的保留。

真实内网 TDC 登录/续期：**待验证**。本文件只用假传输、假 DPAPI 后端与内存凭据，
不读真实 keys/DPAPI 库、不打真实网络；口令一律运行期唯一合成值。
"""

from __future__ import annotations

import hmac
import json
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.tdc_auth as tdc_auth
import web.app as web_app
import web.host_boot as web_host_boot
from core.archive_store import ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from core.db_manager import DatabaseManager
from core.domain_identity import SESSION_STATE_CLEARED, WindowsDPAPICredentialVault
from services import project_status_connectors
from services.project_status_connectors import RetryingConnector, TDCProjectStatusConnector
from services.project_status_sync_runner import SyncBindingContext
from services.session_recovery import Forbidden, RenewalRejected, SessionCleared
from services.tdc_auth import TDCAuthError
from services.tdc_crawler import DEFAULT_TDC_BASE_URL, TDCCrawlerError
from tests.test_settings_security import FakeDPAPIBackend

#: 合成值（契约 §9.2-5）：占位账号，绝不使用真实用户名。
PRINCIPAL = "tdc-user-a"
LOOPBACK_HEADERS = {"Host": "localhost", "Origin": "http://localhost"}

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"


def _runtime_opaque() -> str:
    """运行期唯一合成秘密（对齐 tests/test_settings_security.py 的口径）。"""
    return f"opq-{uuid.uuid4().hex}"


def _assert_secret_absent(secret: str, *values: object) -> None:
    rendered = "\n".join(
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=repr)
        for value in values
    )
    assert secret not in rendered


# ── 夹具：假会话 / 假登录客户端 / 假 TDC 传输 ────────────────────────────────


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

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def login(self, username: str, password: str):  # pragma: no cover - 触发即失败
        raise AssertionError("connector must reuse the shared domain session")


class SelfLoginAuth:
    """旧自行登录路径用的假登录客户端：记录以哪个账号登录，返回独立会话。"""

    instances: list["SelfLoginAuth"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.usernames: list[str] = []
        SelfLoginAuth.instances.append(self)

    def login(self, username: str, password: str):
        self.usernames.append(str(username))
        return SimpleNamespace(session=FakeSession("self-login"), token_expires_in=None)


class FailingLogin:
    """统一登录路由用的失败客户端：直接抛注入的闭集异常。"""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def login(self, username: str, password: str):
        raise self.error


def _data_model_result(rows: list[dict[str, object]] | None = None):
    return SimpleNamespace(
        rows=rows if rows is not None else [{"incident": "FLOW-1", "currentApprover": "审批人"}],
        complete=True,
        stop_reason="reported_pages",
    )


def _official_export(output_dir: Path):
    path = Path(output_dir) / "official.xlsx"
    path.write_bytes(b"PK\x03\x04fake")
    return SimpleNamespace(path=path, file_name="official.xlsx", byte_count=8)


class TdcCrawlerScript:
    """假 TDC 传输：按脚本队列返回结果或抛异常，并记录每次调用用到的会话。

    ``crawl_outcomes`` 依次供 ``crawl_data_model_all`` / ``crawl_sor_all`` 消费；
    ``export_outcomes`` 为 None 时导出成功（在临时目录里写一个假工作簿），否则
    按队列返回结果或抛异常。
    """

    def __init__(
        self,
        crawl_outcomes: list[object],
        export_outcomes: list[object] | None = None,
    ) -> None:
        self._crawl_outcomes = list(crawl_outcomes)
        self._export_outcomes = None if export_outcomes is None else list(export_outcomes)
        self._lock = threading.Lock()
        self.crawl_calls: list[str] = []
        self.crawl_sessions: list[object] = []
        self.export_calls: list[str] = []
        self.export_sessions: list[object] = []

    def _next(self, queue: list[object], label: str) -> object:
        with self._lock:
            if not queue:
                raise AssertionError(f"unexpected extra {label} call")
            outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _record(self, name: str, session: object, *, export: bool) -> None:
        with self._lock:
            if export:
                self.export_calls.append(name)
                self.export_sessions.append(session)
            else:
                self.crawl_calls.append(name)
                self.crawl_sessions.append(session)

    def factory(self, session=None, timeout=None, output_dir=None):
        script = self

        class _Crawler:
            def __init__(self) -> None:
                self.session = session
                self.output_dir = output_dir

            def crawl_data_model_all(self, filters, max_records):
                script._record("data_model", session, export=False)
                return script._next(script._crawl_outcomes, "crawl")

            def crawl_sor_all(self, filters, max_records):
                script._record("sor", session, export=False)
                return script._next(script._crawl_outcomes, "crawl")

            def _export(self, name: str):
                script._record(name, session, export=True)
                if script._export_outcomes is None:
                    return _official_export(self.output_dir)
                outcome = script._next(script._export_outcomes, "export")
                if callable(outcome):
                    return outcome(self.output_dir)
                return outcome

            def export_data_model(self, filters):
                return self._export("data_model")

            def export_sor(self, filters):
                return self._export("sor")

        return _Crawler()


def _tdc_context(*, report: str = "data_model", external_key: str = "FLOW-1") -> SyncBindingContext:
    return SyncBindingContext(
        binding_id=31,
        deliverable_id="VPI-T2-D5",
        phase_id="VPI-T2",
        source_type="tdc",
        external_key=external_key,
        match_rule={"reportType": report},
        mapping={"owner": "currentApprover"},
        cursor={},
        expected_deliverable_updated_at="v1",
        run_id=31,
        credential_ref="domain",
    )


# ── 组合根夹具：create_app + test_client，假 DPAPI 后端 + 假传输 ─────────────


@pytest.fixture()
def tdc_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """真实 create_app 装配：协调器/注册表/凭据提供者都来自应用组合根。"""
    db = DatabaseManager(db_path=tmp_path / "tdc_session_recovery.db")
    db.init_database()
    vault = WindowsDPAPICredentialVault(path=tmp_path / "vault.dat", backend=FakeDPAPIBackend)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr(web_app, "WindowsDPAPICredentialVault", lambda *args, **kwargs: vault)

    route_aras = FakeLoginClient(tag="route-aras")
    route_tdc = FakeLoginClient(tag="route-tdc")
    renewal_aras = FakeLoginClient(tag="renewed-aras")
    renewal_tdc = FakeLoginClient(tag="renewed-tdc")
    monkeypatch.setattr(web_host_boot, "ArasECMAuthClient", lambda: route_aras)
    monkeypatch.setattr(web_host_boot, "TDCPasswordAuthClient", lambda: route_tdc)
    monkeypatch.setattr(
        web_host_boot, "store_windows_generic_credential", lambda ref, user, secret: None
    )
    monkeypatch.setattr(web_host_boot, "delete_windows_generic_credential", lambda ref: True)
    # 协调器的登录客户端工厂（组合根装配点）替换为假客户端：不触发真实登录。
    # 注意：生产 web/app.py 目前只登记了 aras（见报告"需要的范围例外"）。
    monkeypatch.setattr(
        web_app,
        "_session_renewal_clients",
        lambda: {"aras": lambda: renewal_aras, "tdc": lambda: renewal_tdc},
    )

    app = web_app.create_app()
    app.config.update(TESTING=True)
    env = SimpleNamespace(
        app=app,
        client=app.test_client(),
        registry=app.extensions["domain_sessions"],
        coordinator=app.extensions["session_renewal"],
        vault=vault,
        route_aras=route_aras,
        route_tdc=route_tdc,
        renewal_aras=renewal_aras,
        renewal_tdc=renewal_tdc,
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


def _connector(env, secret: str, script: TdcCrawlerScript, *, auth_factory=NoLoginAuth):
    return TDCProjectStatusConnector(
        MemoryCredentialProvider({"domain": (PRINCIPAL, secret)}),
        ArchiveStore({"default": env.tmp_path}, reserve_bytes=0),
        auth_factory=auth_factory,
        crawler_factory=script.factory,
    )


def _sessions_payload(env) -> dict:
    """真实路由 GET /api/settings 返回的 sessions payload（徽章输入）。"""
    response = env.client.get("/api/settings", headers=LOOPBACK_HEADERS)
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    return body["data"]["sessions"]


# ── 1. 过期 401 → 单次续期 → 只读查询原位重放成功 ────────────────────────────


def test_expired_401_renews_once_and_replays_tdc_read_in_place(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    assert login_response.get_json()["data"]["results"]["tdc"] == {"ok": True}
    env.renewal_tdc.expected_password = secret

    route_session = env.registry.session("tdc")
    assert route_session is not None
    # TDC 登录必须建立身份绑定，续期键（accountRef）才成立（契约 §5.1）。
    root, account_ref_before = env.registry.identity_binding("tdc")
    assert root == DEFAULT_TDC_BASE_URL
    assert account_ref_before
    generation_before = env.registry.generation("tdc")

    script = TdcCrawlerScript(
        [TDCCrawlerError("TDC HTTP 401 at /tpc/dataModel", stage="status-validation", status_code=401),
         _data_model_result()]
    )
    snapshot = _connector(env, secret, script).collect(_tdc_context())

    assert snapshot.match_state == "matched"
    assert snapshot.candidates[0].field_values == {"owner": "审批人"}
    # 首次 401 + 重放一次，且重放拿到的是协调器写回的新会话（原位恢复）。
    assert script.crawl_calls == ["data_model", "data_model"]
    assert script.crawl_sessions[0] is route_session
    renewed_session = env.registry.session("tdc")
    assert renewed_session is not None and renewed_session is not route_session
    assert script.crawl_sessions[1] is renewed_session
    # 后续官方导出（unsafe_side_effect）同样用续期后的会话。
    assert script.export_calls == ["data_model"]
    assert script.export_sessions[0] is renewed_session
    # 导出产物确实落库（假工作簿内容非法，只影响 official_status，不改变归档）。
    assert "xlsx" in {item["artifact_type"] for item in snapshot.artifacts}
    # 单次续期：协调器只登录一次，连接器自己没有额外登录。
    assert env.renewal_tdc.login_calls == 1
    assert env.renewal_tdc.usernames == [PRINCIPAL]
    assert env.route_tdc.login_calls == 1
    # 续期不改代次，绑定与凭据保持。
    assert env.registry.generation("tdc") == generation_before
    assert env.registry.identity_binding("tdc")[1] == account_ref_before
    assert env.vault.is_configured() is True

    operation = env.coordinator.last_operation()
    # 最后一次业务调用是官方导出（unsafe_side_effect，只尝试一次、未重放）；
    # 只读查询"续期后原位重放一次"由上面的两次 crawl 调用与新会话证明。
    assert operation == {
        "system": "tdc",
        "kind": "unsafe_side_effect",
        "attempt": 1,
        "replayed": False,
        "code": None,
    }
    _assert_secret_absent(secret, login_response.get_json(), env.registry.payload(), operation)


# ── 2. 403 不续期、不清凭据、不重放 ─────────────────────────────────────────


def test_forbidden_403_never_renews_or_clears_credentials(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    session_before = env.registry.session("tdc")
    generation_before = env.registry.generation("tdc")

    script = TdcCrawlerScript(
        [TDCCrawlerError("TDC HTTP 403 at /tpc/dataModel", stage="status-validation", status_code=403)]
    )
    with pytest.raises(Forbidden) as excinfo:
        _connector(env, secret, script).collect(_tdc_context())

    error = excinfo.value
    assert error.code == "forbidden"
    assert error.http_status == 403
    assert error.action == "none"
    assert error.retryable is False
    assert script.crawl_calls == ["data_model"]           # 不重放
    assert script.export_calls == []                      # 查询失败不进入导出
    assert env.renewal_tdc.login_calls == 0               # 不续期
    assert env.registry.session("tdc") is session_before
    assert env.registry.generation("tdc") == generation_before
    assert env.vault.is_configured() is True              # 不清凭据
    _assert_secret_absent(secret, str(error), error.to_error_payload())


def test_shared_session_is_not_reused_for_another_account(tdc_env) -> None:
    """契约 §3.2：注册表绑定账号 A，credential_ref 解析为账号 B → 不复用 A 的会话。"""
    env = tdc_env
    login_response, _ = _login(env)
    assert login_response.status_code == 200
    route_session = env.registry.session("tdc")
    assert route_session is not None

    SelfLoginAuth.instances.clear()
    script = TdcCrawlerScript([_data_model_result()])
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"domain": ("other.user", _runtime_opaque())}),
        ArchiveStore({"default": env.tmp_path}, reserve_bytes=0),
        auth_factory=SelfLoginAuth,
        crawler_factory=script.factory,
    )
    snapshot = connector.collect(_tdc_context())

    assert snapshot.match_state == "matched"
    # 走旧的自行登录路径：以 credential_ref 的账号 B 登录，爬虫拿到的不是 A 的会话。
    assert [auth.usernames for auth in SelfLoginAuth.instances] == [["other.user"]]
    assert script.crawl_sessions[0] is not route_session
    assert env.renewal_tdc.login_calls == 0


def test_binding_switch_after_check_does_not_hand_over_new_account_session(tdc_env) -> None:
    """校验通过后、业务调用前绑定被换成别的账号：不得改用新账号的会话。"""
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    captured_session = env.registry.session("tdc")
    root, bound = env.registry.identity_binding("tdc")

    class SwitchingRegistry:
        """第一次读绑定返回原账号，之后模拟另一账号已登录。"""

        def __init__(self, real) -> None:
            self.real = real
            self.binding_reads = 0
            self.other_session = FakeSession("other-account")

        def identity_binding(self, system):
            self.binding_reads += 1
            if self.binding_reads == 1:
                return root, bound
            return root, "other-account-ref"

        def session(self, system):
            return self.other_session if self.binding_reads > 1 else self.real.session(system)

    switching = SwitchingRegistry(env.registry)
    script = TdcCrawlerScript([_data_model_result()])
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"domain": (PRINCIPAL, secret)}),
        ArchiveStore({"default": env.tmp_path}, reserve_bytes=0),
        auth_factory=NoLoginAuth,
        crawler_factory=script.factory,
        session_registry=switching,
    )
    snapshot = connector.collect(_tdc_context())

    assert snapshot.match_state == "matched"
    assert script.crawl_sessions[0] is captured_session
    assert script.crawl_sessions[0] is not switching.other_session


# ── 3. 清除竞态：迟到的续期结果不回填 ───────────────────────────────────────


def test_clear_during_renewal_discards_late_tdc_renewal_result(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    env.renewal_tdc.expected_password = secret
    started = threading.Event()
    release = threading.Event()
    env.renewal_tdc.started = started
    env.renewal_tdc.gate = release

    script = TdcCrawlerScript(
        [TDCCrawlerError("TDC HTTP 401 at /tpc/dataModel", stage="status-validation", status_code=401)]
    )
    connector = _connector(env, secret, script)
    outcome: dict[str, BaseException] = {}

    def _collect() -> None:
        try:
            connector.collect(_tdc_context())
        except BaseException as exc:  # noqa: BLE001 - 测试只关心闭集错误
            outcome["error"] = exc

    worker = threading.Thread(target=_collect, name="tdc-session-recovery")
    worker.start()
    try:
        assert started.wait(5), "renewal did not start"
        generation_before = env.registry.generation("tdc")
        # 续期在途：真实路由的 payload 必须如实呈现 renewing。
        in_flight = _sessions_payload(env)
        assert in_flight["tdc"]["state"] == "renewing"
        clear_response = env.client.delete(
            "/api/settings/sessions", json={}, headers=LOOPBACK_HEADERS
        )
        assert clear_response.status_code == 200
        body = clear_response.get_json()
        assert body["ok"] is True
        assert body["data"]["results"]["tdc"] == {"ok": True, "code": "session_cleared"}
        assert body["data"]["sessions"]["tdc"]["state"] == SESSION_STATE_CLEARED
    finally:
        release.set()
        worker.join(5)

    assert not worker.is_alive()
    error = outcome.get("error")
    assert isinstance(error, SessionCleared)
    assert error.code == "session_cleared"
    # 代次 +1 且在途续期被取消：迟到的续期结果绝不回填。
    assert env.registry.generation("tdc") == generation_before + 1
    assert env.registry.session("tdc") is None
    assert env.registry.state("tdc") == SESSION_STATE_CLEARED
    assert script.crawl_calls == ["data_model"]            # 没有重放
    _assert_secret_absent(secret, str(error), env.registry.payload())


# ── 4. unsafe_side_effect：官方导出续期后不重放 ─────────────────────────────


def test_unsafe_official_export_is_not_replayed_after_renewal(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    env.renewal_tdc.expected_password = secret

    script = TdcCrawlerScript(
        [_data_model_result()],
        export_outcomes=[
            TDCCrawlerError("TDC HTTP 401 at /tpc/export", stage="status-validation", status_code=401)
        ],
    )
    snapshot = _connector(env, secret, script).collect(_tdc_context())

    # 官方导出可能已在上游产生产物：只尝试一次，绝不自动重放；同步本身不失败
    # （既有语义：官方列只作补齐，失败只降级 official_status）。
    assert script.crawl_calls == ["data_model"]
    assert script.export_calls == ["data_model"]
    assert env.renewal_tdc.login_calls == 1               # 续期只为后续操作可用
    assert snapshot.match_state == "matched"
    assert snapshot.official_status == "export_failed"
    operation = env.coordinator.last_operation()
    assert operation == {
        "system": "tdc",
        "kind": "unsafe_side_effect",
        "attempt": 1,
        "replayed": False,
        "code": "generation_unknown",
    }
    _assert_secret_absent(secret, json.dumps(operation), env.registry.payload())


def test_unsafe_generation_unknown_is_not_retried_by_outer_retrying_connector(tdc_env) -> None:
    """已发出但无响应的导出升级为 generation_unknown：外层有界重试不得重发。"""
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200

    script = TdcCrawlerScript([_data_model_result()], export_outcomes=[TimeoutError("no response")])
    inner = _connector(env, secret, script)
    collect_calls: list[int] = []

    class _Collect:
        def collect(self, context):
            collect_calls.append(1)
            return inner.collect(context)

    snapshot = RetryingConnector(_Collect(), sleeper=lambda delay: None).collect(_tdc_context())

    assert snapshot.official_status == "export_failed"
    assert collect_calls == [1]                 # 外层有界重试不重发（契约 §6.4）
    assert script.export_calls == ["data_model"]  # 上游导出只被调用一次
    assert env.renewal_tdc.login_calls == 0     # 没有 401，不触发续期


# ── 5. 统一清除：逐系统结果如实、失败不伪报成功 ────────────────────────────


def test_clear_results_report_failed_system_without_faking_success(tdc_env, monkeypatch) -> None:
    env = tdc_env
    login_response, _ = _login(env)
    assert login_response.status_code == 200
    assert env.registry.session("tdc") is not None

    real_clear = env.coordinator.clear

    def _flaky_clear(system=None):
        if system == "tdc":
            raise RuntimeError("coordinator clear failed")
        return real_clear(system)

    monkeypatch.setattr(env.coordinator, "clear", _flaky_clear)

    # 单个系统失败：该项 ok:false + 闭集 code，其余系统照常清除。
    aras_response = env.client.delete(
        "/api/settings/sessions", json={"system": "aras"}, headers=LOOPBACK_HEADERS
    )
    assert aras_response.status_code == 200
    aras_body = aras_response.get_json()
    assert aras_body["ok"] is True
    assert aras_body["data"]["results"]["aras"] == {"ok": True, "code": "session_cleared"}

    tdc_response = env.client.delete(
        "/api/settings/sessions", json={"system": "tdc"}, headers=LOOPBACK_HEADERS
    )
    assert tdc_response.status_code == 200                   # HTTP 既有语义不变
    tdc_body = tdc_response.get_json()
    assert tdc_body["ok"] is False                           # 失败不伪报成功
    assert tdc_body["data"]["results"]["tdc"] == {
        "ok": False,
        "code": "service_unavailable",
    }
    assert env.registry.session("tdc") is not None           # 未清除就是未清除

    # 全清：一项成功一项失败 → 顶层 ok=false，逐项结果各自如实。
    all_response = env.client.delete(
        "/api/settings/sessions", json={}, headers=LOOPBACK_HEADERS
    )
    assert all_response.status_code == 200
    all_body = all_response.get_json()
    assert all_body["ok"] is False
    assert all_body["data"]["results"]["aras"] == {"ok": True, "code": "session_cleared"}
    assert all_body["data"]["results"]["tdc"]["ok"] is False


def test_clear_credential_vault_failure_keeps_503(tdc_env, monkeypatch) -> None:
    env = tdc_env
    login_response, _ = _login(env)
    assert login_response.status_code == 200

    from core.credential_provider import CredentialProviderError

    def _fail(ref: str) -> None:
        raise CredentialProviderError("Windows Credential Manager is unavailable")

    monkeypatch.setattr(web_host_boot, "delete_windows_generic_credential", _fail)
    response = env.client.delete(
        "/api/settings/sessions",
        json={"clearCredentialVault": True},
        headers=LOOPBACK_HEADERS,
    )
    assert response.status_code == 503
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == "CredentialVaultUnavailable"
    # 会话已按既有顺序清除，但凭据删除失败必须如实返回 503，不伪报成功。
    assert env.vault.is_configured() is True


# ── 6. TDCAuthError 闭集恢复码 / feishukey 协议字段保留 ─────────────────────


def _reject_via_status_check(monkeypatch: pytest.MonkeyPatch, status: int):
    """走生产调用点 ``_require_status``（非 2xx → ``_reject``），保留传输 stage。"""
    client = tdc_auth.TDCPasswordAuthClient(session=object())
    monkeypatch.setattr(tdc_auth, "_event_from_trace", lambda *args, **kwargs: None)
    monkeypatch.setattr(client, "_emit", lambda event: None)
    trace = SimpleNamespace(
        response=SimpleNamespace(status_code=status),
        stage="auth-credentials",
        request_id="req-tdc17a1",
    )
    with pytest.raises(TDCAuthError) as excinfo:
        client._require_status(trace, {200})
    return excinfo.value


def test_tdc_reject_declares_closed_recovery_code(monkeypatch) -> None:
    """登录被拒按 §4.2 附带闭集恢复码；既有 stage 语义不变。"""
    invalid = _reject_via_status_check(monkeypatch, 401)
    assert invalid.stage == "auth-credentials"        # 既有 stage 语义不变
    assert invalid.status_code == 401
    assert invalid.recovery_code == "credential_invalid"

    forbidden = _reject_via_status_check(monkeypatch, 403)
    assert forbidden.recovery_code == "forbidden"      # 403 永不转成 401

    upstream_down = _reject_via_status_check(monkeypatch, 502)
    assert upstream_down.recovery_code is None         # 交 classify 归 network

    # 主控冻结口径：只有 401/403 在异常上标码；其余状态交 classify。
    assert tdc_auth._login_rejection_code(200) is None
    assert tdc_auth._login_rejection_code(400) is None
    assert tdc_auth._login_rejection_code(422) is None
    assert tdc_auth._login_rejection_code(429) is None
    assert tdc_auth._login_rejection_code(404) is None
    assert tdc_auth._login_rejection_code(0) is None

    # 未登记的码必须立刻失败，绝不污染 §4.3 闭集。
    with pytest.raises(ValueError):
        TDCAuthError("rejected", stage="auth-credentials", recovery_code="not-a-code")


def test_tdc_login_keeps_feishukey_protocol_field_and_expires_in() -> None:
    """登录链保留 feishukey 协议字段，并按上游正整数秒填 token_expires_in。"""
    from tests.test_tdc_auth import AUTH_URL, FakeResponse, FakeSession, make_auth_client

    login_html = """
    <html><body>
      <form method="post" action="https://account.sgmw.com.cn/auth/realms/common/login-actions/authenticate?session_code=fictional-session&amp;execution=fictional-execution&amp;client_id=fictional-client&amp;tab_id=fictional-tab">
        <input name="username" type="text">
        <input name="password" type="password">
        <input name="newokey" type="hidden" value="">
        <input name="feishukey" type="hidden" value="fictional-feishu-key">
        <input name="credentialId" type="hidden" value="">
      </form>
    </body></html>
    """
    responses = [
        FakeResponse(
            status_code=200,
            url=AUTH_URL,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=login_html,
        ),
        FakeResponse(
            status_code=302,
            headers={
                "Location": (
                    "https://tdc.sgmw.com.cn/tpc"
                    "#state=fictional-state-value&session_state=fictional-session-state&code=fictional-code"
                )
            },
        ),
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={
                "access_token": "fictional-identity-token",
                "token_type": "bearer",
                "expires_in": 300,
            },
        ),
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={
                "code": 0,
                "data": {"access_token": "fictional-tdc-token", "expires_in": 600},
            },
        ),
        FakeResponse(
            headers={"Content-Type": "application/json"},
            payload={"code": 0, "data": {"displayName": "Fictional User"}},
        ),
    ]
    session = FakeSession(responses)
    result = make_auth_client(session).login("fictional-user", "fictional-password-secret")

    assert session.calls[1]["data"]["feishukey"] == "fictional-feishu-key"
    assert result.token_expires_in == 600


def test_tdc_login_rejection_declares_recovery_code_on_real_flow() -> None:
    """真实登录链：401/403 在异常上标闭集码；200 重渲染不标、交 classify。"""
    from tests.test_tdc_auth import (
        AUTH_URL,
        LOGIN_HTML,
        FakeResponse,
        FakeSession,
        make_auth_client,
    )

    def _login_error(status: int) -> TDCAuthError:
        responses = [
            FakeResponse(
                status_code=200,
                url=AUTH_URL,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text=LOGIN_HTML,
            ),
            FakeResponse(
                status_code=status,
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html><body>rejected</body></html>",
            ),
        ]
        with pytest.raises(TDCAuthError) as excinfo:
            make_auth_client(FakeSession(responses)).login(
                "fictional-user", "fictional-password-secret"
            )
        return excinfo.value

    invalid = _login_error(401)
    assert invalid.stage == "auth-credentials"
    assert invalid.recovery_code == "credential_invalid"

    forbidden = _login_error(403)
    assert forbidden.stage == "auth-credentials"
    assert forbidden.recovery_code == "forbidden"       # 403 永不转成 401

    re_rendered = _login_error(200)
    assert re_rendered.stage == "auth-credentials"
    assert re_rendered.recovery_code is None             # 其他状态不标，交 classify


# ── 7. W3 顶栏三档徽章：Node 执行真实 payload 的映射 ────────────────────────


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


_NODE_BADGE_SCRIPT = r"""
const base = process.argv[1];
const payload = JSON.parse(process.argv[2]);
const badges = await import(base + "/chrome/SessionBadges.js");
const session = await import(base + "/session.js");

const state = badges.aggregateSessionStatus(payload);

// 红档点击 = 原位登录：SessionCapsule 缺省 onLogin → openInPlaceLogin → loginStore，
// LoginDialog（web/static/host/chrome/LoginDialog.js:17，chrome/index.js:26 挂载）订阅它。
let clicked = false;
if (state.tier === badges.STATUS_TIERS.LOGIN_REQUIRED) {
  session.closeInPlaceLogin();
  const capsule = badges.SessionCapsule({ sessions: payload });
  if (typeof capsule.props.onClick === "function") {
    capsule.props.onClick();
    clicked = true;
  }
}
const login = session.loginStore.get();
session.closeInPlaceLogin();

console.log(JSON.stringify({
  tier: state.tier,
  text: state.text,
  tone: state.tone,
  clicked,
  loginOpen: Boolean(login.open),
  notice: login.notice || "",
}));
"""


def _badge_state(payload: dict) -> dict:
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            _NODE_BADGE_SCRIPT,
            HOST_STATIC.as_uri(),
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败:\n{result.stderr}"
    lines = result.stdout.strip().splitlines()
    assert lines, "Node 执行未产生输出"
    return json.loads(lines[-1])


_node_required = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules")


@_node_required
def test_badge_maps_logged_in_sessions_to_connected(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200

    payload = _sessions_payload(env)
    assert payload["aras"]["state"] == "valid"
    assert payload["tdc"]["state"] == "valid"
    badge = _badge_state(payload)
    assert badge["tier"] == "connected"
    assert badge["text"] == "已连接 ✓"
    _assert_secret_absent(secret, payload, badge)


@_node_required
def test_badge_maps_expired_sessions_to_recovering(tdc_env, monkeypatch) -> None:
    """真实 payload 的黄档：TTL 到期（state='expired'）→ 正在恢复。"""
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200

    # 注册表构造参数 clock 是契约 D12 的可注入时钟（本用例把"现在"推到 TTL 之后）。
    monkeypatch.setattr(
        env.registry, "_clock", lambda: datetime.now(timezone.utc) + timedelta(hours=9)
    )
    payload = _sessions_payload(env)
    assert payload["tdc"]["state"] == "expired"
    assert payload["tdc"]["expired"] is True
    assert payload["tdc"]["authenticated"] is False

    badge = _badge_state(payload)
    assert badge["tier"] == "recovering"
    assert badge["text"] == "正在恢复"
    _assert_secret_absent(secret, payload, badge)


@_node_required
def test_badge_maps_cleared_sessions_to_login_required_and_opens_login_dialog(tdc_env) -> None:
    env = tdc_env
    login_response, _ = _login(env)
    assert login_response.status_code == 200

    clear_response = env.client.delete(
        "/api/settings/sessions", json={}, headers=LOOPBACK_HEADERS
    )
    assert clear_response.status_code == 200
    payload = clear_response.get_json()["data"]["sessions"]
    assert payload["tdc"]["state"] == SESSION_STATE_CLEARED

    badge = _badge_state(payload)
    assert badge["tier"] == "login_required"
    assert badge["text"] == "需要重新登录"
    # 红档点击原位登录：LoginDialog 的 loginStore 被打开（复用 LoginDialog）。
    assert badge["clicked"] is True
    assert badge["loginOpen"] is True
    assert badge["notice"] == "请输入企业域账号登录；成功后将更新当前会话状态。"


@_node_required
def test_badge_maps_in_flight_renewal_to_recovering(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    env.renewal_tdc.expected_password = secret
    started = threading.Event()
    release = threading.Event()
    env.renewal_tdc.started = started
    env.renewal_tdc.gate = release

    script = TdcCrawlerScript(
        [TDCCrawlerError("TDC HTTP 401 at /tpc/dataModel", stage="status-validation", status_code=401)]
    )
    connector = _connector(env, secret, script)
    outcome: dict[str, BaseException] = {}

    def _collect() -> None:
        try:
            connector.collect(_tdc_context())
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    worker = threading.Thread(target=_collect, name="tdc-badge-recovering")
    worker.start()
    try:
        assert started.wait(5), "renewal did not start"
        payload = _sessions_payload(env)
        assert payload["tdc"]["state"] == "renewing"      # 后端状态机如实
        badge = _badge_state(payload)
        assert badge["tier"] == "recovering"              # 期望：正在恢复
    finally:
        release.set()
        worker.join(5)


@_node_required
def test_badge_maps_failed_renewal_to_login_required(tdc_env) -> None:
    env = tdc_env
    login_response, secret = _login(env)
    assert login_response.status_code == 200
    env.renewal_tdc.expected_password = secret
    # 生产形态（契约 §4.2）：新会话未被上游接受 → renewal_rejected(credential_invalid)。
    env.renewal_tdc.error = TDCAuthError(
        "TDC session verification failed", stage="session-verification-failed",
        status_code=200,
    )

    script = TdcCrawlerScript(
        [TDCCrawlerError("TDC HTTP 401 at /tpc/dataModel", stage="status-validation", status_code=401)]
    )
    with pytest.raises(RenewalRejected):
        _connector(env, secret, script).collect(_tdc_context())

    payload = _sessions_payload(env)
    assert payload["tdc"]["state"] == "failed"
    badge = _badge_state(payload)
    assert badge["tier"] == "login_required"             # 期望：需要重新登录


def test_production_renewal_clients_include_tdc() -> None:
    """生产装配（不 monkeypatch）：协调器的 TDC 登录客户端工厂已注册。"""
    import web.app as production_app
    from services.tdc_auth import TDCPasswordAuthClient

    clients = production_app._session_renewal_clients()
    assert clients.get("tdc") is TDCPasswordAuthClient
    assert "aras" in clients
