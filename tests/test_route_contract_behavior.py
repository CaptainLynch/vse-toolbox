# -*- coding: utf-8 -*-
"""路由接线与实际响应契约测试（DSH-V2-07）。

与 ``tests/test_route_contract_snapshot.py`` 的分工：

* 快照测试证明「路由集合 + 视图源码属性」没变（golden 对照）；
* 本文件证明**接线**与**实际响应**没变——用 Flask test client 发真实请求，
  走完整的 ``create_app`` 装配链，不是检查源码文本。

覆盖契约（``docs/refactor-v2/CONTRACTS.md`` C8：路径、方法、状态码、``{ok,data,error}``
信封、错误类型码、Content-Type、下载响应头、写保护行为）：

1. **接线**：对 ``web/app.py`` 实际调用的每个 ``register_*``，断言其注册出的
   endpoint 集合、断言 ``app.view_functions[endpoint].__module__`` 属于对应
   ``*_boot`` 模块，并用 spy 包装证明 ``create_app`` 真的调用了该 register
   （记录调用前后的 ``url_map`` 增量，不是源码包含符号）；
2. **分领域行为**：读路由成功（``{ok,data}``）、失败路径（状态码 + 错误信封）、
   写路由在本机认证缺失/错误时被拒（``web/security.py`` 的实际行为：无会话
   ``401 SessionRequired``、有会话无 Origin ``403 OriginRequired``）、存在下载
   路由的领域检查 ``Content-Disposition`` / ``Content-Type``；
3. **sync-now**：project-status 的 ``sync-now`` 保持 HTTP 200 + ``ok`` 语义；
4. **golden 只读**：本文件不改写、不放宽既有 golden 断言；领域接线清单与
   ``tests/golden/routes.json`` 的 endpoint 集合做只读交叉校验。

所有外部依赖（Aras / TDC / Excel 任务库与 Worker / 诊断录制）都用假实现或
monkeypatch，测试不访问网络、不触碰真实数据库与凭据。
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask.testing import FlaskClient

import core.runtime_paths as runtime_paths
import web.app as web_app
import web.project_status_boot as ps_boot
from core import diagnostic_recording as dr
from core.db_manager import DatabaseManager
from core.excel_tasks import ExcelTaskFileRef
from services.project_status_records import compute_config_signature
from services.project_status_sync_runner import (
    ConnectorRegistry,
    ProjectStatusConnector,
    SyncBindingContext,
)
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "routes.json"

#: 显式启动票据：让 security-aware 测试客户端能真实走一次 boot-exchange。
BOOT_TOKEN = "dsh-v2-07-route-contract-boot-token"

#: 本机安全层（web/security.py）在写请求上的两个 fail-closed 出口。
SESSION_REQUIRED = "SessionRequired"
ORIGIN_REQUIRED = "OriginRequired"


# ── 领域接线清单（与 web/app.py 的 register_* 调用逐条对应，冻结契约） ────────


@dataclass(frozen=True)
class DomainWiring:
    """一个已迁出领域的注册入口：模块、register 函数、它拥有的 endpoint。"""

    module: str
    function: str
    endpoints: tuple[str, ...]


DOMAIN_WIRINGS: tuple[DomainWiring, ...] = (
    DomainWiring(
        "web.crawler_boot",
        "register_crawler_routes",
        (
            "api_aras_ewo_export",
            "api_aras_ewo_query",
            "api_aras_ncr_detail",
            "api_aras_ncr_detail_download",
            "api_aras_ncr_progress",
            "api_aras_ncr_progress_download",
            "api_aras_paa_crawl_all",
            "api_aras_paa_export",
            "api_aras_paa_query",
        ),
    ),
    DomainWiring(
        "web.crawler_boot",
        "register_tdc_routes",
        (
            "api_tdc_a_face_crawl_all",
            "api_tdc_a_face_export",
            "api_tdc_a_face_query",
            "api_tdc_data_model_crawl_all",
            "api_tdc_data_model_export",
            "api_tdc_data_model_export_merged",
            "api_tdc_data_model_query",
            "api_tdc_sor_car_type_projects",
            "api_tdc_sor_crawl_all",
            "api_tdc_sor_export",
            "api_tdc_sor_query",
        ),
    ),
    DomainWiring(
        "web.crawler_boot",
        "register_form_catalog_routes",
        (
            "api_deliverable_form_rows",
            "api_deliverable_form_statistics",
            "api_deliverable_form_view",
            "api_deliverables_catalog",
        ),
    ),
    DomainWiring(
        "web.excel_boot",
        "register_excel_routes",
        (
            "api_excel_artifact_detail",
            "api_excel_artifact_download",
            "api_excel_artifact_download_audit",
            "api_excel_artifacts_retention_plan",
            "api_excel_roots_list",
            "api_excel_task_artifacts",
            "api_excel_task_detail",
            "api_excel_task_runs",
            "api_excel_tasks_create",
            "api_excel_tasks_list",
            "api_excel_worker_start",
            "api_excel_worker_status",
            "api_excel_worker_stop",
        ),
    ),
    DomainWiring(
        "web.tasks_boot",
        "register_tasks_routes",
        (
            "api_tasks_cancel",
            "api_tasks_download",
            "api_tasks_get",
            "api_tasks_list",
            "api_tasks_result",
            "api_tasks_retry",
        ),
    ),
    DomainWiring(
        "web.host_boot",
        "register_host_service_routes",
        (
            "api_version",
            "api_settings_get",
            "api_settings_update",
            "api_settings_native_folder",
            "api_domain_login",
            "api_domain_sessions_clear",
        ),
    ),
    DomainWiring(
        "web.host_boot",
        "register_host_update_routes",
        (
            "api_host_updates_discard",
            "api_host_updates_import",
            "api_host_updates_rollback",
        ),
    ),
    DomainWiring(
        "web.archive_boot",
        "register_archive_routes",
        (
            "api_scheduled_archive_config_audit",
            "api_scheduled_archive_folders",
            "api_scheduled_archive_native_folder",
            "api_scheduled_archive_jobs",
            "api_scheduled_archive_job_create",
            "api_scheduled_archive_job_update",
            "api_scheduled_archive_job_archive",
            "api_scheduled_archive_sync_now",
            "api_scheduled_archive_runs",
            "api_scheduled_archive_artifacts",
        ),
    ),
    DomainWiring(
        "web.project_status_boot",
        "register_project_status_routes",
        (
            "api_project_status",
            "api_project_status_analytics",
            "api_project_status_deliverable_update",
            "api_project_status_deliverable_analysis",
            "api_project_status_deliverable_analysis_items",
            "api_project_status_candidate_preview",
            "api_project_status_chart_labels",
            "api_project_status_chart_labels_write",
            "api_project_status_debug_bundle",
            "api_project_status_mapping_discovery_history",
            "api_project_status_mapping_discovery",
            "api_project_status_mapping_discovery_cancel",
            "api_project_status_sync_by_car_type",
            "api_project_status_sync_now",
            "api_project_status_unified_status",
            "api_project_status_update_policy",
            "api_project_status_update_policy_write",
            "api_project_status_phase_update",
            "api_project_status_milestones_update",
            "api_project_status_runs",
            "api_project_status_run_artifacts",
            "api_project_status_scheduler_status",
            "api_project_status_scheduler_config",
            "api_project_status_scheduler_sync_all",
            "api_section_rollup_get",
            "api_section_rollup_put",
            "api_project_status_updates",
        ),
    ),
    DomainWiring(
        "web.ewo_enrichment",
        "register_ewo_enrichment",
        (
            "ewo_enrichment_prepare",
            "ewo_enrichment_restore",
            "ewo_enrichment_run",
            "ewo_enrichment_status",
        ),
    ),
    DomainWiring(
        "web.diagnostics",
        "install_diagnostics",
        (
            "diagnostic_status",
            "diagnostic_download",
            "diagnostic_events",
            "diagnostic_mark",
            "diagnostic_start",
            "diagnostic_stop",
        ),
    ),
)

#: 仍留在组合根 ``web/app.py`` 的宿主路由（迁移基线，不属于任何 ``*_boot``）。
HOST_APP_ENDPOINTS: frozenset[str] = frozenset(
    {
        "index",
        "favicon",
        "api_overview",
        "api_host_manifest",
        "api_host_updates",
    }
)

#: 本机安全层自己的端点（web/security.py 注册）。
SECURITY_ENDPOINTS: frozenset[str] = frozenset({
    "api_security_boot_exchange",
    # DSH-V2-03（DSH_LOCAL_SECURITY_CONTRACT §6.1）新增的 4 条本机安全路由。
    "api_security_capabilities",
    "api_security_window_grant",
    "api_security_boot_claim",
    "api_security_session_recover",
})


def _all_domain_endpoints() -> frozenset[str]:
    return frozenset(endpoint for wiring in DOMAIN_WIRINGS for endpoint in wiring.endpoints)


# ── Excel 假实现：真实 ExcelTaskAdminService 代码照常执行 ────────────────────


class FakeExcelRoots:
    """``ApprovedExcelRoots`` 的最小替身（只做白名单根内的路径解析）。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root_ids(self) -> tuple[str, ...]:
        return ("demo",)

    def get_root(self, root_id: str) -> Path:
        if root_id != "demo":
            raise KeyError(root_id)
        return self._root

    def resolve_ref(self, ref: ExcelTaskFileRef, *, check_role: bool = True) -> Path:
        return self._root / ref.relative_path


class FakeExcelRepository:
    """``ExcelTaskRepository`` 的最小替身：一条任务 + 一份产物，不碰真实文件库。"""

    def __init__(self, root: Path, artifact_bytes: bytes) -> None:
        self.roots = FakeExcelRoots(root)
        self.audit_calls: list[dict[str, Any]] = []
        self.task: dict[str, Any] = {
            "id": 1,
            "operation": "transform",
            "status": "queued",
            "options": {},
            "attempt_count": 0,
            "max_attempts": 1,
            "error_type": None,
            "error_message": None,
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
            "started_at": None,
            "finished_at": None,
            "files": [
                ExcelTaskFileRef(role="source", root_id="demo", relative_path="in/source.xlsx")
            ],
        }
        self.artifact: dict[str, Any] = {
            "id": 1,
            "task_id": 1,
            "run_id": 1,
            "artifact_type": "output",
            "root_id": "demo",
            "relative_path": "out/result.xlsx",
            "display_name": "结果.xlsx",
            "size_bytes": len(artifact_bytes),
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "created_at": "2026-01-01T00:00:00.000Z",
        }

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        return dict(self.task) if task_id == self.task["id"] else None

    def list_tasks(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(self.task)]

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return dict(self.artifact) if artifact_id == self.artifact["id"] else None

    def list_task_artifacts(self, task_id: int) -> list[dict[str, Any]]:
        return [dict(self.artifact)] if task_id == self.task["id"] else []

    def list_artifact_download_audits(self, artifact_id: int, limit: int | None = None) -> list:
        return []

    def record_artifact_download_audit(self, **kwargs: Any) -> None:
        self.audit_calls.append(kwargs)

    def list_retention_candidates(self, cutoff_iso: str, limit: int) -> tuple[list, bool]:
        return [], False


class FakeWorkerStatus:
    def __init__(self, running: bool) -> None:
        self._running = running

    def to_dict(self) -> dict[str, Any]:
        return {"running": self._running, "mode": "in_process"}


class FakeExcelWorkerController:
    """Excel Worker 控制器替身：绝不启动真实进程/COM。"""

    def __init__(self) -> None:
        self.running = False

    def status(self) -> FakeWorkerStatus:
        return FakeWorkerStatus(self.running)

    def start(self) -> FakeWorkerStatus:
        self.running = True
        return FakeWorkerStatus(True)

    def stop(self) -> FakeWorkerStatus:
        self.running = False
        return FakeWorkerStatus(False)


# ── 隔离应用夹具：临时数据目录 + 假 Excel 依赖 + 可插桩的 create_app ─────────


class ContractEnv:
    """一个隔离 app 实例 + 断言助手；``app`` 懒构建，便于在构建前插桩。"""

    def __init__(self, tmp_path: Path, db: DatabaseManager, repository: FakeExcelRepository) -> None:
        self.tmp_path = tmp_path
        self.db = db
        self.repository = repository
        self.register_calls: dict[str, list[set[str]]] = {}
        self._app: Flask | None = None
        self._client: Any = None

    # ── 应用构建 ──
    def build(self) -> Flask:
        if self._app is None:
            self._app = web_app.create_app(
                excel_repository=self.repository,
                excel_worker_controller=FakeExcelWorkerController(),
                boot_token=BOOT_TOKEN,
            )
            self._app.config.update(TESTING=True)
        return self._app

    @property
    def app(self) -> Flask:
        return self.build()

    @property
    def client(self):
        """security-aware 测试客户端（等价浏览器：写请求自带会话与 Origin）。"""
        if self._client is None:
            self._client = self.app.test_client()
        return self._client

    @contextlib.contextmanager
    def raw_client(self) -> Iterator[Any]:
        """原生 werkzeug 客户端：不自动补会话/Origin，用于 fail-closed 断言。"""
        original = self.app.test_client_class
        self.app.test_client_class = FlaskClient
        try:
            yield self.app.test_client()
        finally:
            self.app.test_client_class = original

    # ── 接线插桩 ──
    def install_register_spies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """包装每个 register 函数，记录它对 url_map 的真实贡献。"""
        for wiring in DOMAIN_WIRINGS:
            module = importlib.import_module(wiring.module)
            original = getattr(module, wiring.function)

            def spy(*args: Any, _original=original, _function=wiring.function, **kwargs: Any):
                target = args[0]
                before = {rule.endpoint for rule in target.url_map.iter_rules()}
                result = _original(*args, **kwargs)
                after = {rule.endpoint for rule in target.url_map.iter_rules()}
                self.register_calls.setdefault(_function, []).append(after - before)
                return result

            monkeypatch.setattr(module, wiring.function, spy)


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ContractEnv]:
    """隔离工作区：临时数据库/下载目录/Excel 白名单根，绝不触碰真实数据。"""
    db = DatabaseManager(db_path=tmp_path / "route_contract.db")
    db.init_database()
    for name in ("data", "downloads", "ewo-downloads", "diagnostics"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    excel_root = tmp_path / "excel-root"
    (excel_root / "in").mkdir(parents=True, exist_ok=True)
    (excel_root / "out").mkdir(parents=True, exist_ok=True)
    artifact_bytes = b"PK\x03\x04synthetic-route-contract-xlsx"
    (excel_root / "out" / "result.xlsx").write_bytes(artifact_bytes)

    repository = FakeExcelRepository(excel_root, artifact_bytes)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    monkeypatch.setattr(web_app, "app_root", lambda: tmp_path, raising=False)
    monkeypatch.setattr(runtime_paths, "app_root", lambda: tmp_path)
    # 诊断录制器是进程级单例：重置后 default_recorder() 会落在临时 app_root 下。
    monkeypatch.setattr(dr, "_default", None)
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    monkeypatch.delenv("VSE_ROUTE_SNAPSHOT_WRITE", raising=False)

    contract_env = ContractEnv(tmp_path, db, repository)
    try:
        yield contract_env
    finally:
        contract_env._app = None


# ── 断言助手 ────────────────────────────────────────────────────────────────


def assert_ok(
    response: Any, status: int = 200, *, no_store: bool | None = None
) -> dict[str, Any]:
    """成功响应：状态码 + ``{ok: true, data: ...}`` 信封。

    ``no_store`` 显式区分「该路由设了 ``Cache-Control: no-store``」与「历史上没设」，
    避免把既有差异写成统一断言（差异见 ``NO_STORE_GAP_PATHS``）。
    """
    text = response.get_data(as_text=True)
    assert response.status_code == status, text
    body = response.get_json()
    assert isinstance(body, dict), text
    assert body.get("ok") is True, text
    assert "data" in body, text
    assert "error" not in body, text
    if no_store is True:
        assert response.headers.get("Cache-Control") == "no-store", text
    elif no_store is False:
        assert response.headers.get("Cache-Control") is None, text
    return body["data"]


def assert_error(response: Any, status: int, error_type: str) -> dict[str, Any]:
    """失败响应：状态码 + ``{ok: false, error: {type, message}}`` 信封。"""
    text = response.get_data(as_text=True)
    assert response.status_code == status, text
    body = response.get_json()
    assert isinstance(body, dict), text
    assert body.get("ok") is False, text
    error = body.get("error")
    assert isinstance(error, dict), text
    assert error.get("type") == error_type, text
    assert isinstance(error.get("message"), str) and error["message"], text
    return error


def assert_attachment(response: Any, *, expected_mimetype: str, name_hint: str) -> None:
    """下载响应头契约：``Content-Disposition`` 必须是附件，且文件名可辨识。"""
    assert response.status_code == 200, response.get_data(as_text=True)
    disposition = response.headers.get("Content-Disposition", "")
    assert disposition.lower().startswith("attachment"), disposition
    assert name_hint.lower() in disposition.lower(), disposition
    assert response.headers.get("Content-Type", "").startswith(expected_mimetype), (
        response.headers.get("Content-Type")
    )
    assert response.data, "下载响应体不能为空"


def _security_error_type(response: Any) -> str | None:
    body = response.get_json(silent=True)
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    return error.get("type") if isinstance(error, dict) else None


# ── 1. 接线：handler 所属模块 + create_app 真的调用了新 register ─────────────


def test_every_migrated_domain_handler_lives_in_its_boot_module(env: ContractEnv) -> None:
    """每个 endpoint 的 ``__module__`` 必须是对应 ``*_boot`` 模块（不是 web.app）。"""
    app = env.app
    for wiring in DOMAIN_WIRINGS:
        for endpoint in wiring.endpoints:
            assert endpoint in app.view_functions, f"{wiring.function} 未注册 {endpoint}"
            module = app.view_functions[endpoint].__module__
            assert module == wiring.module, (
                f"{endpoint} 的 handler 属于 {module}，契约要求 {wiring.module}"
            )


def test_create_app_really_invokes_each_register_function(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spy 证明 create_app 真的调用了每个 register，且调用贡献 = 冻结的 endpoint 集合。"""
    env.install_register_spies(monkeypatch)
    app = env.app

    for wiring in DOMAIN_WIRINGS:
        calls = env.register_calls.get(wiring.function)
        assert calls, f"create_app 没有调用 {wiring.module}.{wiring.function}"
        assert len(calls) == 1, (
            f"{wiring.module}.{wiring.function} 被调用了 {len(calls)} 次，应恰好一次"
        )
        assert calls[0] == set(wiring.endpoints), (
            f"{wiring.function} 实际注册的 endpoint 与冻结清单不一致："
            f"多出 {sorted(calls[0] - set(wiring.endpoints))}，"
            f"缺少 {sorted(set(wiring.endpoints) - calls[0])}"
        )
        # 每条 endpoint 都必须是这次 register 调用当场创建的。
        for endpoint in wiring.endpoints:
            assert endpoint in app.view_functions

    # 全部非插件 endpoint 都有明确归属：没有未登记的迁移遗留。
    owned = {endpoint for calls in env.register_calls.values() for endpoint in calls[0]}
    non_plugin = {
        endpoint
        for endpoint in app.view_functions
        if endpoint != "static" and not endpoint.startswith("plugin_")
    }
    assert owned == _all_domain_endpoints()
    assert non_plugin == owned | set(HOST_APP_ENDPOINTS) | set(SECURITY_ENDPOINTS)

    for endpoint in HOST_APP_ENDPOINTS:
        assert app.view_functions[endpoint].__module__ == "web.app", endpoint
    for endpoint in SECURITY_ENDPOINTS:
        assert app.view_functions[endpoint].__module__ == "web.security", endpoint


def test_domain_route_class_inventory_matches_documented_coverage(env: ContractEnv) -> None:
    """把「哪些领域没有某类路由」写成断言，避免报告口径与实际接线脱节。"""
    app = env.app
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    rules_by_endpoint = {rule.endpoint: rule for rule in app.url_map.iter_rules()}

    def methods(endpoint: str) -> set[str]:
        return {method for method in (rules_by_endpoint[endpoint].methods or set())} - {
            "HEAD",
            "OPTIONS",
        }

    inventory = {
        wiring.function: {
            "read": {e for e in wiring.endpoints if methods(e) == {"GET"}},
            "write": {e for e in wiring.endpoints if methods(e) & write_methods},
        }
        for wiring in DOMAIN_WIRINGS
    }

    # 只有表单/目录领域没有写路由（纯只读目录），其余领域都至少一条写路由。
    assert inventory["register_form_catalog_routes"]["write"] == set()
    for function, classes in inventory.items():
        if function == "register_form_catalog_routes":
            continue
        assert classes["write"], f"{function} 没有任何写路由，写保护覆盖会失真"

    # aras / tdc / ewo 的「读」是 POST 查询（POST 语义查询），因此 GET 集合为空；
    # 这几条查询路由同时受写保护约束（见 test_write_routes_reject_missing_local_session）。
    for function in ("register_crawler_routes", "register_tdc_routes", "register_ewo_enrichment"):
        assert inventory[function]["read"] == set(), function
    assert inventory["register_form_catalog_routes"]["read"] == {
        "api_deliverable_form_rows",
        "api_deliverable_form_statistics",
        "api_deliverable_form_view",
        "api_deliverables_catalog",
    }


# ── 2a. 读路由成功：{ok,data} 信封 ──────────────────────────────────────────

#: 观察到的既有差异（不在本任务范围内修生产代码，只如实钉住现状并在报告里列出）：
#: 这三条 200/ok 的读路由**没有**设置 ``Cache-Control: no-store``，与同领域其他
#: 读路由不一致。它们不是本次迁移引入的兼容性变化（迁移只搬位置），因此这里按
#: 现状断言并单独点名，避免把差异伪装成统一契约。
NO_STORE_GAP_PATHS: frozenset[str] = frozenset(
    {
        "/api/deliverables/catalog",
        "/api/aras/ncr/detail",
        "/api/tdc/sor/query",
    }
)

READ_CASES: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/version", "host_boot"),
    ("GET", "/api/settings", "host_boot"),
    ("GET", "/api/scheduled-archive/jobs", "archive_boot"),
    ("GET", "/api/scheduled-archive/runs", "archive_boot"),
    ("GET", "/api/excel-roots", "excel_boot"),
    ("GET", "/api/excel-tasks", "excel_boot"),
    ("GET", "/api/excel-tasks/1", "excel_boot"),
    ("GET", "/api/excel-worker/status", "excel_boot"),
    ("GET", "/api/tasks", "tasks_boot"),
    ("GET", "/api/project-status", "project_status_boot"),
    ("GET", "/api/project-status/updates?deliverableId=VPI-T2-D5", "project_status_boot"),
    ("GET", "/api/deliverables/catalog", "crawler_boot/form_catalog"),
)


@pytest.mark.parametrize(
    ("method", "path", "domain"),
    READ_CASES,
    ids=[f"{method} {path}" for method, path, _ in READ_CASES],
)
def test_read_routes_return_ok_envelope(
    env: ContractEnv, method: str, path: str, domain: str
) -> None:
    """每个领域至少一条读路由：200 + ``{ok: true, data}`` 信封。"""
    response = env.client.open(path, method=method)
    data = assert_ok(
        response, no_store=False if path in NO_STORE_GAP_PATHS else True
    )
    assert data is not None, f"{domain} {path} 的 data 为空"


def test_read_routes_without_no_store_are_the_three_documented_gaps(
    env: ContractEnv,
) -> None:
    """把「哪些 200/ok 读路由缺 no-store」固化成三条，防止差异悄悄扩散或消失。"""
    rules = {rule.rule for rule in env.app.url_map.iter_rules()}
    assert NO_STORE_GAP_PATHS <= rules, sorted(NO_STORE_GAP_PATHS - rules)
    assert len(NO_STORE_GAP_PATHS) == 3


def test_aras_ncr_detail_query_returns_ok_envelope_with_fake_client(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """aras 领域的读（POST 查询）：用假 Aras client 走完真实 handler。"""
    import web.crawler_boot as crawler_boot

    fake_client = SimpleNamespace(
        extract_ncr_approval_detail=lambda filters: SimpleNamespace(file_name="NCR_明细.xlsx"),
    )
    monkeypatch.setattr(
        crawler_boot, "_build_aras_client_from_payload", lambda payload, hosts: fake_client
    )

    response = env.client.post(
        "/api/aras/ncr/detail",
        json={"base_url": "https://ecm.sgmw.com.cn", "filters": {}},
    )
    data = assert_ok(response, no_store=False)
    assert data["file_name"] == "NCR_明细.xlsx"
    assert data["count"] == 0
    assert data["previewAvailable"] is False


def test_tdc_sor_query_returns_ok_envelope_with_fake_client(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tdc 领域的读（POST 查询）：假 TDC client 返回一页结果，信封与分页字段不变。"""
    import web.crawler_boot as crawler_boot

    fake_result = SimpleNamespace(
        report_type="sor",
        rows=[{"serialNumber": "SOR-1", "title": "合成行"}],
        page=1,
        page_size=50,
        total=1,
        pages=1,
        fetched_pages=1,
        unique_count=1,
        duplicate_count=0,
        stop_reason=None,
        record_granularity="row",
    )
    fake_client = SimpleNamespace(
        query_sor_page=lambda filters, page, page_size: fake_result,
        session=None,
    )
    monkeypatch.setattr(
        crawler_boot, "_build_tdc_client_from_payload", lambda payload, hosts: fake_client
    )

    response = env.client.post(
        "/api/tdc/sor/query",
        json={"base_url": "https://tdc.sgmw.com.cn", "filters": {}},
    )
    data = assert_ok(response, no_store=False)
    assert data["report_type"] == "sor"
    assert data["data_source"] == "list_endpoint"
    assert data["total"] == 1
    assert data["page"] == 1


def test_ewo_enrichment_status_returns_ok_envelope_with_fake_service(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ewo 领域的读（POST status）：服务替身 + 已绑定域会话 → 200 + ok。"""
    from services.aras_auth import DEFAULT_ARAS_BASE_URL

    service = env.app.extensions["ewo_enrichment"]
    monkeypatch.setattr(
        service,
        "status",
        lambda job_id, scope: {"jobId": job_id, "state": "parsed", "scope": scope},
    )
    sessions = env.app.extensions["domain_sessions"]
    sessions.mark_authenticated(
        "aras", object(), principal="synthetic-user", source_root=DEFAULT_ARAS_BASE_URL
    )

    job_id = "0123456789abcdef0123456789abcdef"
    response = env.client.post(f"/api/aras/ewo/enrichment/jobs/{job_id}/status", json={})
    data = assert_ok(response)
    assert data["jobId"] == job_id
    assert data["state"] == "parsed"


def test_diagnostics_status_returns_json_without_ok_envelope(env: ContractEnv) -> None:
    """诊断状态沿用 recorder.status() 的裸 JSON（历史契约），只断言形状不伪装成信封。"""
    response = env.client.get("/api/diagnostics")
    assert response.status_code == 200
    body = response.get_json()
    assert isinstance(body, dict)
    assert {"active", "latest", "recordings"} <= set(body)
    assert body["active"] is False


# ── 2b. 失败路径：状态码 + 错误信封 ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "status", "error_type"),
    [
        (
            "POST",
            "/api/aras/ncr/detail",
            {"json": {"filters": {}}},
            400,
            "ValidationError",
        ),
        ("POST", "/api/tdc/a-face/query", {"json": {}}, 400, "ContractBlocker"),
        (
            "POST",
            "/api/tdc/sor/query",
            {"json": {"base_url": "https://tdc.sgmw.com.cn", "page": 0}},
            400,
            "ValidationError",
        ),
        ("GET", "/api/deliverable-forms/not-a-form/view", {}, 404, "NotFound"),
        ("GET", "/api/excel-tasks/999", {}, 404, "NotFound"),
        ("GET", "/api/excel-artifacts/999", {}, 404, "NotFound"),
        ("GET", "/api/tasks/does-not-exist", {}, 404, "NotFound"),
        ("GET", "/api/project-status?phase=NOT-A-PHASE", {}, 404, "NotFound"),
        ("GET", "/api/scheduled-archive/runs?limit=0", {}, 422, "ValidationError"),
        ("DELETE", "/api/settings/sessions", {"json": {"system": "bogus"}}, 422, "ValidationError"),
        (
            "POST",
            "/api/host/updates/not-installed/rollback",
            {},
            404,
            "NotFound",
        ),
        ("POST", "/api/host/updates/import", {}, 400, "ValidationError"),
        (
            "POST",
            "/api/scheduled-archive/jobs/unknown-job/sync-now",
            {},
            404,
            "NotFound",
        ),
        (
            "POST",
            "/api/aras/ewo/enrichment/jobs/0123456789abcdef0123456789abcdef/status",
            {"json": {}},
            401,
            "DomainLoginRequired",
        ),
    ],
)
def test_failure_paths_return_error_envelope(
    env: ContractEnv,
    method: str,
    path: str,
    kwargs: dict[str, Any],
    status: int,
    error_type: str,
) -> None:
    """每个领域至少一条失败路径：状态码 + ``{ok:false,error:{type,message}}``。"""
    response = env.client.open(path, method=method, **kwargs)
    assert_error(response, status, error_type)


def test_diagnostics_bundle_failure_uses_legacy_string_error(env: ContractEnv) -> None:
    """诊断下载沿用历史 ``{ok:false, error:'RecordingNotFound'}`` 形状（不是嵌套信封）。"""
    response = env.client.get(
        "/api/diagnostics/bundles/0123456789abcdef0123456789abcdef"
    )
    assert response.status_code == 404
    body = response.get_json()
    assert body == {"ok": False, "error": "RecordingNotFound"}


# ── 2c. 写保护：缺失/错误本机认证一律 fail-closed ───────────────────────────


WRITE_PROTECTION_CASES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("POST", "/api/aras/paa/query", {"json": {}}),
    ("POST", "/api/tdc/sor/query", {"json": {}}),
    ("POST", "/api/excel-tasks", {"json": {}}),
    ("POST", "/api/tasks/unknown-task/cancel", {}),
    ("POST", "/api/settings/domain-login", {"json": {}}),
    ("POST", "/api/host/updates/demo/discard", {}),
    ("POST", "/api/scheduled-archive/jobs", {"json": {}}),
    (
        "POST",
        "/api/project-status/deliverables/VPI-T2-D5/sync-now",
        {},
    ),
    ("POST", "/api/aras/ewo/enrichment/jobs", {"json": {}}),
    ("POST", "/api/diagnostics/mark", {"json": {}}),
)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    WRITE_PROTECTION_CASES,
    ids=[f"{method} {path}" for method, path, _ in WRITE_PROTECTION_CASES],
)
def test_write_routes_reject_missing_local_session(
    env: ContractEnv, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    """无会话 Cookie 的写请求必须被 web/security.py 拦成 401 SessionRequired。"""
    with env.raw_client() as client:
        response = client.open(path, method=method, **kwargs)
    assert response.status_code == 401, response.get_data(as_text=True)
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == SESSION_REQUIRED
    assert _security_error_type(response) == SESSION_REQUIRED


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    WRITE_PROTECTION_CASES,
    ids=[f"{method} {path}" for method, path, _ in WRITE_PROTECTION_CASES],
)
def test_write_routes_reach_the_view_once_local_session_is_valid(
    env: ContractEnv, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    """对照组：同一路径带会话+同源 Origin 时穿过安全层，证明 401 来自安全层而非路由。"""
    response = env.client.open(path, method=method, **kwargs)
    assert not (
        response.status_code == 401 and _security_error_type(response) == SESSION_REQUIRED
    ), f"{path} 带合法本机会话仍被 SessionRequired 拒绝"


def test_write_protection_requires_session_then_origin(env: ContractEnv) -> None:
    """同一写路由的两道闸：无会话 401 SessionRequired，有会话缺 Origin 403 OriginRequired。"""
    path = "/api/project-status/deliverables/VPI-T2-D5/sync-now"
    with env.raw_client() as client:
        no_session = client.post(path, json={}, headers={"Origin": "http://localhost"})
        assert no_session.status_code == 401
        assert _security_error_type(no_session) == SESSION_REQUIRED

        exchanged = client.post(
            "/api/security/boot-exchange",
            json={"token": BOOT_TOKEN},
            headers={"Origin": "http://localhost"},
        )
        assert exchanged.status_code == 200, exchanged.get_data(as_text=True)
        assert exchanged.get_json() == {"ok": True, "data": {"exchanged": True}}

        no_origin = client.post(path, json={})
        assert no_origin.status_code == 403
        assert _security_error_type(no_origin) == ORIGIN_REQUIRED


def test_write_protection_rejects_cross_site_origin(env: ContractEnv) -> None:
    """会话有效但 Origin 跨源：403 CrossSiteRequest（同机不同端口同属 localhost 源）。"""
    path = "/api/scheduled-archive/jobs"
    with env.raw_client() as client:
        exchanged = client.post(
            "/api/security/boot-exchange",
            json={"token": BOOT_TOKEN},
            headers={"Origin": "http://localhost"},
        )
        assert exchanged.status_code == 200, exchanged.get_data(as_text=True)

        response = client.post(
            path, json={}, headers={"Origin": "http://localhost:9999"}
        )
    assert response.status_code == 403
    assert _security_error_type(response) == "CrossSiteRequest"


# ── 2d. 下载头：Content-Disposition / Content-Type ──────────────────────────


def test_aras_ncr_detail_download_sets_attachment_headers(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """aras 领域下载：假 client 落一份 xlsx，响应必须是附件 + xlsx Content-Type。"""
    import web.crawler_boot as crawler_boot

    def fake_download(file_name: str, target_dir: Path) -> Path:
        target = Path(target_dir) / file_name
        target.write_bytes(b"PK\x03\x04synthetic-ncr-detail")
        return target

    fake_client = SimpleNamespace(
        extract_ncr_approval_detail=lambda filters: SimpleNamespace(file_name="NCR-001.xlsx"),
        download_ncr_detail_file=fake_download,
    )
    monkeypatch.setattr(
        crawler_boot, "_build_aras_client_from_payload", lambda payload, hosts: fake_client
    )

    response = env.client.post(
        "/api/aras/ncr/detail/download",
        json={"base_url": "https://ecm.sgmw.com.cn", "filters": {}},
    )
    assert_attachment(
        response,
        expected_mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name_hint="ncr-001.xlsx",
    )


def test_excel_artifact_download_sets_attachment_headers(env: ContractEnv) -> None:
    """excel 领域下载：真实 ExcelTaskAdminService 校验 sha256 后返回附件。"""
    response = env.client.get("/api/excel-artifacts/1/download")
    assert_attachment(
        response,
        expected_mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name_hint="xlsx",
    )
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert env.repository.audit_calls, "下载必须留下审计记录"


def test_excel_artifact_download_rejects_integrity_mismatch(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """产物被篡改（sha256 不符）：409 ArtifactUnavailable，绝不下发内容。"""
    env.repository.artifact["sha256"] = "0" * 64
    response = env.client.get("/api/excel-artifacts/1/download")
    assert_error(response, 409, "ArtifactUnavailable")


def test_tasks_download_sets_attachment_headers(env: ContractEnv) -> None:
    """tasks 领域下载：统一任务中心复用 Excel 产物下载，仍是附件 + nosniff。"""
    response = env.client.get("/api/tasks/excel_1/download")
    assert_attachment(
        response,
        expected_mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name_hint="xlsx",
    )
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_project_status_debug_bundle_zip_sets_attachment_headers(env: ContractEnv) -> None:
    """project-status 领域下载：调试包 zip 走 send_file，附件头与 zip 类型不变。"""
    response = env.client.get(
        "/api/project-status/deliverables/VPI-T2-D5/debug-bundle?format=zip"
    )
    assert_attachment(response, expected_mimetype="application/zip", name_hint="debug.zip")
    assert response.data[:2] == b"PK"


def test_diagnostics_bundle_download_sets_attachment_headers(env: ContractEnv) -> None:
    """diagnostics 领域下载：真实录制器（临时目录）导出 zip 附件。"""
    started = env.client.post("/api/diagnostics/start", json={})
    assert started.status_code == 200, started.get_data(as_text=True)
    status = env.client.get("/api/diagnostics").get_json()
    recording_id = (status.get("latest") or {}).get("id")
    assert isinstance(recording_id, str) and recording_id, status

    response = env.client.get(f"/api/diagnostics/bundles/{recording_id}")
    assert_attachment(response, expected_mimetype="application/zip", name_hint="vse-diagnostics-")

    stopped = env.client.post("/api/diagnostics/stop", json={})
    assert stopped.status_code == 200


# ── 3. sync-now 保持 HTTP 200 + ok 语义 ─────────────────────────────────────


class FakeConnector(ProjectStatusConnector):
    """离线假连接器：返回预置快照，绝不访问 TDC/Aras。"""

    def __init__(self, snapshot: ConnectorSnapshot) -> None:
        self._snapshot = snapshot
        self.collect_calls: list[SyncBindingContext] = []

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot:
        self.collect_calls.append(context)
        return self._snapshot


def _current_updated_at(db: DatabaseManager, deliverable_id: str) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
    assert row is not None
    return str(row["updated_at"])


def _record_two_observations_for_d5(
    db: DatabaseManager,
    *,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
    fields: list[str] | None = None,
    match_rule: dict[str, object] | None = None,
) -> None:
    """记录两次同键匹配观测（同步准入门控要求证据齐备）。"""
    field_list = fields if fields is not None else [
        "currentApprover", "approvalComment", "incident", "reportType",
    ]
    report = {
        "fields": field_list,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    if match_rule is None:
        match_rule = {"reportType": "data_model", "incident": external_key}
    config_signature = compute_config_signature(source_type, match_rule)
    for fingerprint in ("fp1", "fp2"):
        db.record_mapping_observation(
            deliverable_id=deliverable_id,
            source_type=source_type,
            result_state="matched",
            external_key=external_key,
            candidate_fingerprint=fingerprint,
            candidate_count=1,
            candidate_summary_json=json.dumps([{"externalKey": external_key, "fields": {}}]),
            field_report_json=json.dumps(report),
            config_signature=config_signature,
        )


def _configure_ready_d5_binding(
    db: DatabaseManager,
    *,
    external_key: str = "FM-1",
    credential_ref: str = "placeholder_cred_alias",
) -> None:
    """把 D5 配成「证据齐备 + 绑定可用」的同步就绪状态。"""
    _record_two_observations_for_d5(
        db,
        deliverable_id="VPI-T2-D5",
        source_type="tdc",
        external_key=external_key,
        fields=["currentApprover", "incident", "reportType"],
    )
    update_service = ProjectStatusUpdateService(db)
    update_service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": external_key,
            "credentialRef": credential_ref,
            "matchRule": {"reportType": "data_model", "incident": external_key},
            "mapping": {"owner": "currentApprover"},
            "fieldAuthority": {"owner": "automatic"},
        },
    )


def _matched_snapshot(
    db: DatabaseManager,
    *,
    deliverable_id: str = "VPI-T2-D5",
    external_key: str = "FM-1",
    external_version: str = "v-sync-001",
    **field_values: Any,
) -> ConnectorSnapshot:
    return ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key=external_key,
                external_version=external_version,
                field_values=field_values,
                fetched_at="2026-08-22T00:00:00.000Z",
            )
        ],
        external_version=external_version,
        fetched_at="2026-08-22T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, deliverable_id),
    )


def test_project_status_sync_now_keeps_http_200_and_ok_semantics(
    env: ContractEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sync-now 是写路由但**成功仍返回 HTTP 200 + ok:true**（不是 202/204）。"""
    _configure_ready_d5_binding(env.db)
    registry = ConnectorRegistry()
    registry.register(
        "tdc",
        FakeConnector(
            _matched_snapshot(
                env.db,
                owner="新项目经理（自动同步）",
                plannedDate="2026-09-01",
                note="未授权字段",
            )
        ),
    )
    factory = MagicMock(return_value=registry)
    monkeypatch.setattr(ps_boot, "create_production_registry", factory)

    response = env.client.post("/api/project-status/deliverables/VPI-T2-D5/sync-now")
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["exitCode"] == 2
    assert data["result"]["deliverableId"] == "VPI-T2-D5"
    assert data["result"]["finalState"] == "partial"
    assert data["result"]["appliedFields"] == ["owner"]
    assert "status" not in data and "progress" not in data
    factory.assert_called_once()


def test_project_status_sync_now_unknown_deliverable_stays_404(env: ContractEnv) -> None:
    """sync-now 的失败语义：未知交付物 404 NotFound（不是 409/422）。"""
    response = env.client.post("/api/project-status/deliverables/NOT-A-DELIVERABLE/sync-now")
    assert_error(response, 404, "NotFound")


# ── 4. golden 只读交叉校验 ──────────────────────────────────────────────────


def test_domain_wiring_lists_match_golden_snapshot_readonly(env: ContractEnv) -> None:
    """冻结清单必须与 golden 的 endpoint 集合一致；本文件绝不改写 golden。"""
    assert os.environ.get("VSE_ROUTE_SNAPSHOT_WRITE") != "1", (
        "行为契约测试不得以 VSE_ROUTE_SNAPSHOT_WRITE=1 运行，否则会改写 golden"
    )
    assert GOLDEN_PATH.is_file(), f"缺少 golden 快照：{GOLDEN_PATH}"
    routes = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(routes) >= 80
    golden_endpoints = {
        route["endpoint"]
        for route in routes
        if route["endpoint"] != "static" and not route["endpoint"].startswith("plugin_")
    }
    assert golden_endpoints == (
        _all_domain_endpoints() | set(HOST_APP_ENDPOINTS) | set(SECURITY_ENDPOINTS)
    )
    # 清单里的 endpoint 与本次 create_app 的实际接线一一对应（无遗漏、无多余）。
    assert golden_endpoints <= set(env.app.view_functions)
