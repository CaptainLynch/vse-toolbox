# -*- coding: utf-8 -*-
"""DSH-V2-31：自检插件的连接器与调度覆盖（只读、三态、白名单导出）。

本文件验证主控冻结契约：

1. 在既有会话/Excel/更新/项目检查之外，自检聚合新增「同步连接器」「同步调度」两项；
2. 新两项用 ``not_run``（未执行）/ ``unable``（无法检查）/ ``fail``（失败）三态，
   任何异常都不得写成 ok；既有 4 项的取值与键集合保持兼容；
3. 每项只允许 ``name/state/detail/checkedAt/facts``，facts 只含扁平白名单字段，
   注入的 URL / 用户名 / 文件路径 / 错误原文绝不出现在响应 JSON 文本里；
4. 全程只读（GET 之外一律 405），测试走真实 create_app + 真实 SQLite + 真实
   路由调用链，不使用源码文本断言代替执行。

前端断言用 Node 执行真实 ES 模块：把 preact 导入替换为最小桩后动态 import，
调用 ``SelfCheckItem`` / ``StatusDot`` 检查新状态的中文标签与状态色。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import time
from pathlib import Path
from typing import Any

import pytest

from core.db_manager import DatabaseManager
from core.time_rules import now_utc, to_beijing
from services.schedule_policy import SYNC_JOB_ID, SlotKey
from services.schedule_slots import SYNC_CONTROL_TABLE_PREFIX, SlotStore

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "diagnostics"

#: 连接器 facts 的显式白名单（与后端一致，逐键断言）。
CONNECTOR_FACT_KEYS = {
    "bindingCount",
    "credentialConfiguredCount",
    "sourceTypeCount",
    "sourceTypes",
    "lastSuccessAt",
    "lastFailureState",
}

#: 调度 facts 的显式白名单。
SCHEDULER_FACT_KEYS = {
    "paused",
    "intervalSeconds",
    "fixedMode",
    "fixedBindings",
    "nextRunSeconds",
    "slotCheck",
    "slotPending",
    "slotLeased",
    "slotSucceeded",
    "slotFailed",
    "slotExpired",
    "slotPausedSkipped",
}

#: 新两项允许的取值闭集。
NEW_STATES = {"ok", "warn", "not_run", "unable", "fail"}
#: 既有 4 项保持兼容的取值闭集（need_check/unknown 不改名）。
LEGACY_STATES = {"ok", "warn", "need_check", "unknown"}


class _FakeScheduler:
    """只实现自检所需的 ``get_status()`` 只读协议。"""

    def __init__(self, status: dict[str, Any]) -> None:
        self._status = dict(status)

    def get_status(self) -> dict[str, Any]:
        return dict(self._status)


@pytest.fixture(autouse=True)
def restore_global_scheduler():
    """每个用例前后把全局调度器恢复原值（测试内注册假调度器，结束后恢复 None）。"""
    from services import project_status_scheduler as scheduler_module

    previous = scheduler_module.get_global_scheduler()
    scheduler_module.set_global_scheduler(None)
    try:
        yield
    finally:
        scheduler_module.set_global_scheduler(previous)


@pytest.fixture()
def app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """真实 ``create_app``（仅加载自检插件）+ 隔离到 tmp_path 的真实 SQLite。"""
    import web.app as web_app

    db = DatabaseManager(db_path=tmp_path / "diagnostics-coverage.db")
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    application = web_app.create_app(
        plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["diagnostics"]
    )
    application.config.update(TESTING=True)
    return application, db


@pytest.fixture()
def app(app_db):
    return app_db[0]


@pytest.fixture()
def db(app_db) -> DatabaseManager:
    return app_db[1]


@pytest.fixture()
def client(app):
    return app.test_client()


# ── 数据构造（合成数据，不触碰真实库） ────────────────────────────────────


def _insert_binding(
    db: DatabaseManager,
    *,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    enabled: int = 1,
    mode: str = "automatic",
    sync_state: str = "idle",
    last_success_at: str | None = None,
    credential_ref: str | None = None,
    external_key: str | None = None,
    match_rule_json: str = "{}",
    mapping_json: str = "{}",
    last_error_type: str | None = None,
    last_error_message: str | None = None,
) -> None:
    """写入一条合成同步绑定（覆盖种子行，字段形状与真实表一致）。"""
    with db.get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO project_status_update_bindings ("
            "deliverable_id, mode, source_type, external_key, match_rule_json, "
            "mapping_json, enabled, interval_minutes, cursor_json, credential_ref, "
            "sync_state, last_attempt_at, last_success_at, last_error_type, "
            "last_error_message, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                deliverable_id,
                mode,
                source_type,
                external_key,
                match_rule_json,
                mapping_json,
                enabled,
                15,
                "{}",
                credential_ref,
                sync_state,
                "2026-01-01T00:00:00.000Z",
                last_success_at,
                last_error_type,
                last_error_message,
                "2026-01-01T00:00:00.000Z",
                "2026-01-01T00:00:00.000Z",
            ),
        )


def _items(client) -> dict[str, dict[str, Any]]:
    """调用真实自检路由并按名称索引。"""
    resp = client.get("/api/p/diagnostics/self-check")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    return {item["name"]: item for item in body["data"]["items"]}


def _create_slot_tables(db: DatabaseManager) -> SlotStore:
    """按调度插件同一份迁移建立槽表（只读检查不会建表）。"""
    store = SlotStore(db, SYNC_CONTROL_TABLE_PREFIX, clock=now_utc)
    with db.get_connection() as conn:
        for _version, step in store.migrations():
            step(conn)
    return store


# ── 1. 载荷形状与取值闭集 ────────────────────────────────────────────────


def test_item_shape_and_state_vocabulary(client) -> None:
    """新增两项出现，既有 4 项键集合与取值保持兼容，新项只含白名单键。"""
    resp = client.get("/api/p/diagnostics/self-check")
    assert resp.status_code == 200
    items = resp.get_json()["data"]["items"]

    assert [item["name"] for item in items] == [
        "统一账号会话",
        "表格环境",
        "更新通道",
        "项目注册表",
        "同步连接器",
        "同步调度",
    ]

    for item in items[:4]:
        assert set(item.keys()) == {"name", "state", "detail", "checkedAt"}
        assert item["state"] in LEGACY_STATES

    for item in items[4:]:
        assert set(item.keys()) == {"name", "state", "detail", "checkedAt", "facts"}
        assert item["state"] in NEW_STATES
        assert isinstance(item["facts"], dict)
        assert isinstance(item["detail"], str)


def test_self_check_route_is_read_only(client) -> None:
    """自检仍只有 GET；写方法一律 405（不新增写路由）。"""
    assert client.get("/api/p/diagnostics/self-check").status_code == 200
    assert client.post("/api/p/diagnostics/self-check", json={}).status_code == 405
    assert client.put("/api/p/diagnostics/self-check", json={}).status_code == 405
    assert client.delete("/api/p/diagnostics/self-check").status_code == 405


def test_response_has_no_legacy_forbidden_tokens_or_private_ip(client) -> None:
    """新增两项不引入既有禁止清单（凭据字样）与内网地址。"""
    resp = client.get("/api/p/diagnostics/self-check")
    assert resp.status_code == 200
    raw = json.dumps(resp.get_json(), ensure_ascii=False).lower()

    for token in (
        "password",
        "token",
        "secret",
        "cookie",
        "sessionid",
        "authorization",
        "set-cookie",
        "api_key",
    ):
        assert token not in raw, f"自检响应中意外发现敏感字样: {token}"

    private_ip = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.\d+\.\d+\b")
    assert not private_ip.search(raw), "自检响应中意外发现内网 IP 地址"


# ── 2. 连接器：未执行 / 失败 / 正常 / 提示 ────────────────────────────────


def test_connector_read_exception_is_unable(client, db: DatabaseManager, monkeypatch) -> None:
    """读取绑定抛错 -> unable，只报异常类型，不导出异常原文。"""
    def _broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic db failure with C:\\Users\\alice\\secret")

    monkeypatch.setattr(db, "list_eligible_sync_bindings", _broken)
    connector = _items(client)["同步连接器"]

    assert connector["state"] == "unable"
    assert "RuntimeError" in connector["detail"]
    assert "synthetic db failure" not in connector["detail"]
    assert "alice" not in connector["detail"]


def test_connector_not_run_without_bindings(client) -> None:
    """无启用绑定 -> not_run（未执行），facts 为全零白名单形态。"""
    connector = _items(client)["同步连接器"]

    assert connector["state"] == "not_run"
    assert set(connector["facts"].keys()) <= CONNECTOR_FACT_KEYS
    assert connector["facts"]["bindingCount"] == 0
    assert connector["facts"]["credentialConfiguredCount"] == 0
    assert connector["facts"]["sourceTypeCount"] == 0
    assert connector["facts"]["sourceTypes"] == ""
    assert connector["facts"]["lastSuccessAt"] is None
    assert connector["facts"]["lastFailureState"] is None


def test_connector_fail_on_sync_failure(client, db: DatabaseManager) -> None:
    """有绑定且最近失败 -> fail；facts 只含计数/布尔/枚举/时间。"""
    _insert_binding(
        db,
        sync_state="failed",
        last_success_at="2026-01-01T00:00:00.000Z",
        credential_ref="synthetic-credential-alias",
    )
    connector = _items(client)["同步连接器"]

    assert connector["state"] == "fail"
    facts = connector["facts"]
    assert set(facts.keys()) <= CONNECTOR_FACT_KEYS
    assert facts["bindingCount"] == 1
    assert facts["credentialConfiguredCount"] == 1
    assert facts["sourceTypeCount"] == 1
    assert facts["sourceTypes"] == "tdc"
    assert facts["lastSuccessAt"] == "2026-01-01T00:00:00.000Z"
    assert facts["lastFailureState"] in {"failed", "needs_attention"}
    for value in facts.values():
        assert value is None or isinstance(value, (str, int, bool))


def test_connector_ok_and_warn_by_credential(client, db: DatabaseManager) -> None:
    """凭据已配置 -> ok；凭据缺失 -> warn（未配置不等于失败）。"""
    _insert_binding(
        db,
        sync_state="success",
        last_success_at="2026-01-02T03:04:05.000Z",
        credential_ref="synthetic-credential-alias",
    )
    assert _items(client)["同步连接器"]["state"] == "ok"

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_update_bindings SET credential_ref = NULL "
            "WHERE deliverable_id = 'VPI-T2-D5'"
        )
    connector = _items(client)["同步连接器"]
    assert connector["state"] == "warn"
    assert connector["facts"]["credentialConfiguredCount"] == 0
    assert connector["facts"]["lastSuccessAt"] == "2026-01-02T03:04:05.000Z"


def test_connector_not_run_when_never_succeeded(client, db: DatabaseManager) -> None:
    """有绑定但从未成功同步 -> not_run（不是 ok，也不是 fail）。"""
    _insert_binding(db, sync_state="idle", last_success_at=None, credential_ref="cred-1")
    connector = _items(client)["同步连接器"]

    assert connector["state"] == "not_run"
    assert connector["facts"]["lastSuccessAt"] is None


# ── 3. 调度：未注册 / 正常 / 无法检查 / 失败 ──────────────────────────────


def test_scheduler_not_run_when_unregistered(client) -> None:
    """全局调度器未注册 -> not_run，facts 明确 fixedMode off。"""
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "not_run"
    assert set(scheduler["facts"].keys()) <= SCHEDULER_FACT_KEYS
    assert scheduler["facts"]["fixedMode"] == "off"
    assert scheduler["facts"]["slotCheck"] == "off"


def test_scheduler_stopped_is_not_run(client) -> None:
    """调度器实例存在但已停止 -> not_run（未执行）。"""
    from services.project_status_scheduler import set_global_scheduler

    set_global_scheduler(
        _FakeScheduler(
            {
                "running": False,
                "paused": False,
                "intervalSeconds": 900,
                "fixedBindings": 0,
                "fixedMode": "off",
                "nextRunSeconds": None,
            }
        )
    )
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "not_run"


def test_scheduler_status_exception_is_unable(client) -> None:
    """get_status() 抛错 -> unable，只报异常类型，不导出异常原文。"""
    from services.project_status_scheduler import set_global_scheduler

    class _BrokenScheduler:
        def get_status(self) -> dict[str, Any]:
            raise RuntimeError("synthetic scheduler failure at 10.9.8.7")

    set_global_scheduler(_BrokenScheduler())
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "unable"
    assert "RuntimeError" in scheduler["detail"]
    assert "synthetic scheduler failure" not in scheduler["detail"]
    assert "10.9.8.7" not in scheduler["detail"]


def test_scheduler_ok_with_registered_scheduler(client) -> None:
    """注册假调度器 -> ok，并带 intervalSeconds / fixedMode / 下次执行秒数。"""
    from services.project_status_scheduler import set_global_scheduler

    set_global_scheduler(
        _FakeScheduler(
            {
                "running": True,
                "paused": False,
                "intervalSeconds": 900,
                "fixedBindings": 0,
                "fixedMode": "off",
                "nextRunSeconds": 42,
            }
        )
    )
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "ok"
    facts = scheduler["facts"]
    assert set(facts.keys()) <= SCHEDULER_FACT_KEYS
    assert facts["paused"] is False
    assert facts["intervalSeconds"] == 900
    assert facts["fixedMode"] == "off"
    assert facts["nextRunSeconds"] == 42


def test_scheduler_paused_is_warn(client) -> None:
    """调度器暂停 -> warn（运行中但需要关注）。"""
    from services.project_status_scheduler import set_global_scheduler

    set_global_scheduler(
        _FakeScheduler(
            {
                "running": True,
                "paused": True,
                "intervalSeconds": 900,
                "fixedBindings": 0,
                "fixedMode": "off",
                "nextRunSeconds": None,
            }
        )
    )
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "warn"
    assert scheduler["facts"]["paused"] is True
    assert scheduler["facts"]["nextRunSeconds"] is None


def test_scheduler_fixed_mode_missing_slot_table_is_unable(client) -> None:
    """fixedMode on 但槽表不存在 -> 调度子项 unable（绝不伪报 ok）。"""
    from services.project_status_scheduler import set_global_scheduler

    set_global_scheduler(
        _FakeScheduler(
            {
                "running": True,
                "paused": False,
                "intervalSeconds": 900,
                "fixedBindings": 2,
                "fixedMode": "on",
                "nextRunSeconds": 10,
            }
        )
    )
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "unable"
    assert scheduler["facts"]["slotCheck"] == "unable"
    assert scheduler["facts"]["fixedMode"] == "on"
    assert scheduler["facts"]["fixedBindings"] == 2


def test_scheduler_fixed_mode_counts_slots_and_reports_failure(
    client, db: DatabaseManager
) -> None:
    """槽表存在时统计今日槽状态；存在 failed 槽 -> fail 并带计数。"""
    from services.project_status_scheduler import set_global_scheduler

    store = _create_slot_tables(db)
    day = to_beijing(now_utc()).date()
    store.set_binding("synthetic-project", SYNC_JOB_ID, "fixed", times=("09:00", "10:00"))
    store.ensure_slots(
        [
            SlotKey("synthetic-project", SYNC_JOB_ID, day, time(9, 0)),
            SlotKey("synthetic-project", SYNC_JOB_ID, day, time(10, 0)),
        ]
    )

    first = store.lease_next("coverage-owner", lease_seconds=900, business_date=day)
    assert first is not None
    assert store.finish(first, str(first["leaseToken"]), ok=True) is True

    second = store.lease_next("coverage-owner", lease_seconds=900, business_date=day)
    assert second is not None
    assert (
        store.finish(
            second,
            str(second["leaseToken"]),
            ok=False,
            error_code="timeout",
        )
        is True
    )

    set_global_scheduler(
        _FakeScheduler(
            {
                "running": True,
                "paused": False,
                "intervalSeconds": 900,
                "fixedBindings": 1,
                "fixedMode": "on",
                "nextRunSeconds": 30,
            }
        )
    )
    scheduler = _items(client)["同步调度"]

    assert scheduler["state"] == "fail"
    facts = scheduler["facts"]
    assert facts["slotCheck"] == "checked"
    assert facts["slotSucceeded"] == 1
    assert facts["slotFailed"] == 1
    assert facts["slotPending"] == 0
    assert facts["slotLeased"] == 0
    assert facts["slotExpired"] == 0
    assert facts["slotPausedSkipped"] == 0


# ── 4. 白名单导出：不含业务原文 ──────────────────────────────────────────


def test_response_excludes_raw_binding_business_text(client, db: DatabaseManager) -> None:
    """注入 URL / 用户名 / 路径 / 错误原文，响应 JSON 全文不得出现。"""
    _insert_binding(
        db,
        sync_state="failed",
        last_success_at="2026-01-01T00:00:00.000Z",
        credential_ref="cred-alias-9f8e7d",
        external_key="https://svc-user@internal.example.local/reports/secret.xlsx",
        match_rule_json='{"username": "DOMAIN\\\\alice", "url": "https://svc:pass@10.9.8.7/private"}',
        mapping_json='{"path": "C:\\\\Users\\\\alice\\\\Desktop\\\\report.xlsx"}',
        last_error_type="TimeoutError",
        last_error_message="连接 https://svc:pass@10.9.8.7/private 失败：张三 的工作簿不可读",
    )
    resp = client.get("/api/p/diagnostics/self-check")
    assert resp.status_code == 200
    raw = json.dumps(resp.get_json(), ensure_ascii=False)

    for forbidden in (
        "svc-user",
        "internal.example.local",
        "secret.xlsx",
        "alice",
        "10.9.8.7",
        "cred-alias-9f8e7d",
        "张三",
        "TimeoutError",
        "svc:pass",
        "report.xlsx",
    ):
        assert forbidden not in raw, f"自检响应意外包含业务原文: {forbidden}"

    connector = _items(client)["同步连接器"]
    assert connector["state"] == "fail"
    assert set(connector["facts"].keys()) <= CONNECTOR_FACT_KEYS


# ── 5. 前端：新状态中文标签与状态色（Node 真实执行 ES 模块） ──────────────

_PREACT_STUB = """
const render = (value) => {
  if (Array.isArray(value)) return value.map(render).join("");
  if (value === null || value === undefined || value === false) return "";
  return String(value);
};
export const html = (strings, ...values) =>
  strings.reduce(
    (acc, part, index) => acc + part + (index < values.length ? render(values[index]) : ""),
    "",
  );
export const useCallback = (fn) => fn;
export const useEffect = () => {};
export const useState = (initial) => [typeof initial === "function" ? initial() : initial, () => {}];
"""

_NODE_RUNNER = """
import { STATE_CONFIG, SelfCheckItem, StatusDot } from "./self-check.mjs";

const states = ["ok", "warn", "need_check", "unknown", "error", "fail", "not_run", "unable"];
const labels = {};
const tones = {};
const colors = {};
for (const state of states) {
  const conf = STATE_CONFIG[state];
  labels[state] = conf ? conf.label : null;
  tones[state] = conf ? conf.tone : null;
  colors[state] = conf ? conf.color : null;
}
const rendered = {};
for (const state of ["fail", "not_run", "unable"]) {
  rendered[state] = {
    item: SelfCheckItem({
      item: { name: "同步连接器", state, detail: "只读摘要", checkedAt: "2026-01-01T00:00:00Z" },
    }),
    dot: StatusDot({ state }),
  };
}
console.log(JSON.stringify({ labels, tones, colors, rendered }));
"""


def _node_available() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_available(), reason="需要 Node 环境执行前端状态标签夹具")
def test_frontend_new_state_labels_and_tones(tmp_path: Path) -> None:
    """真实执行 self-check.js：新状态有中文标签，tone/状态色按宿主语义映射。"""
    js_file = PLUGIN_DIR / "static" / "self-check.js"
    source = js_file.read_text(encoding="utf-8")
    import_line = (
        'import { html, useCallback, useEffect, useState } '
        'from "/static/host/vendor/preact-htm.js";'
    )
    assert import_line in source, "self-check.js 的 preact 导入行已变化，需更新夹具"
    module_source = source.replace(
        import_line,
        'import { html, useCallback, useEffect, useState } from "./preact_stub.mjs";',
    )
    (tmp_path / "preact_stub.mjs").write_text(_PREACT_STUB, encoding="utf-8")
    (tmp_path / "self-check.mjs").write_text(module_source, encoding="utf-8")
    (tmp_path / "runner.mjs").write_text(_NODE_RUNNER, encoding="utf-8")

    proc = subprocess.run(
        ["node", str(tmp_path / "runner.mjs")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, f"Node 执行 self-check.js 失败: {proc.stderr}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])

    assert payload["labels"]["fail"] == "失败"
    assert payload["labels"]["not_run"] == "未执行"
    assert payload["labels"]["unable"] == "无法检查"

    # 复用宿主 TONE 语义：ok→ok，warn→warn，fail→bad，未执行/无法检查→中性 off。
    assert payload["tones"]["ok"] == "ok"
    assert payload["tones"]["warn"] == "warn"
    assert payload["tones"]["fail"] == "bad"
    assert payload["tones"]["not_run"] == "off"
    assert payload["tones"]["unable"] == "off"

    # 失败用红色；未执行与无法检查用宿主既有中性灰。
    assert payload["colors"]["fail"] == "#ef4444"
    assert payload["colors"]["not_run"] == "#9ca3af"
    assert payload["colors"]["unable"] == "#9ca3af"

    for state in ("fail", "not_run", "unable"):
        label = payload["labels"][state]
        rendered = payload["rendered"][state]
        assert label in rendered["item"], f"{state} 未渲染中文标签 {label}"
        assert label in rendered["dot"], f"{state} 状态点缺少标题 {label}"
        assert payload["colors"][state] in rendered["dot"], f"{state} 状态点缺少状态色"
