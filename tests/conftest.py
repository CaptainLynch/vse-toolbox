# -*- coding: utf-8 -*-
"""
tests/conftest.py — 公共 pytest fixtures

提供:
    tmp_db  — 使用 tmp_path 隔离的 DatabaseManager，
              init_database() 已调用，预置若干测试行。
              不污染真实 data/vse_toolbox.db。
    authenticated_test_client_default
            — DSH-V2-05：为普通业务测试安装「已认证测试客户端」
              （tests/security_client_fixture.py，原 web/security.py 里的替身）。
              生产安全模块不再安装任何 test_client 替身。

DSH-V2-05 安全边界（主控冻结契约）：
    - 默认替身只在本文件显式声明，且经 monkeypatch 包装 ``web.security.install_local_security``
      安装，生产代码零改动；
    - ``@pytest.mark.raw_security`` 标记的测试、以及 ``RAW_SECURITY_MODULES`` 列出的安全
      测试模块**不安装**替身，一律使用原生客户端——负向断言（401/403）必须来自服务端真实判定；
    - 不对全部安全测试请求做全局自动补齐。
"""

import pytest
from core.db_manager import DatabaseManager

from pathlib import Path

#: DSH-V2-05：已认证测试客户端替身已移出产品安全模块（``web/security.py``）。
#: 以下安全测试模块使用原生客户端，永不安装替身（模块名豁免，避免批量改写）。
RAW_SECURITY_MODULES = frozenset(
    {
        "test_local_security",
        "test_local_security_integration",
        "test_boot_ticket_transport",
    }
)


def pytest_configure(config: pytest.Config) -> None:
    """注册 ``raw_security`` marker（DSH-V2-05 契约 3）。"""
    config.addinivalue_line(
        "markers",
        "raw_security: 使用原生 test_client，不安装 tests.security_client_fixture 的已认证替身",
    )


def _uses_raw_security_client(request: pytest.FixtureRequest) -> bool:
    """该测试是否豁免默认的已认证测试客户端（marker 或安全测试模块名）。"""
    node = request.node
    if node.get_closest_marker("raw_security") is not None:
        return True
    path = getattr(node, "path", None)
    if path is None:
        fspath = getattr(node, "fspath", None)
        path = fspath if fspath is not None else ""
    return Path(str(path)).stem in RAW_SECURITY_MODULES


@pytest.fixture(autouse=True)
def authenticated_test_client_default(request, monkeypatch):
    """普通业务测试默认安装已认证测试客户端（DSH-V2-05 主控裁决 5）。

    生产模块不再安装替身；这里在 ``create_app`` 装配本机安全之后安装
    ``tests/security_client_fixture`` 的等价客户端（真实补同源 Origin、真实走
    boot-exchange，不旁路任何服务端判定）。豁免路径保持原生客户端。
    """
    if _uses_raw_security_client(request):
        return None
    import web.security as web_security
    from tests.security_client_fixture import install_authenticated_test_client

    original = web_security.install_local_security

    def install_local_security_with_test_client(app, **kwargs):
        security = original(app, **kwargs)
        install_authenticated_test_client(app)
        return security

    monkeypatch.setattr(
        web_security, "install_local_security", install_local_security_with_test_client
    )
    return None


#: 显式选择已认证测试客户端：``def test_x(app, authed_client)``。
#: 实现与默认安装逻辑同在 tests/security_client_fixture.py，这里再导出供 pytest 发现。
from tests.security_client_fixture import authed_client  # noqa: E402,F401


@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    """返回已初始化的隔离数据库，预置 projects + deliverables 测试数据。"""
    db = DatabaseManager(db_path=tmp_path / "test.db")
    db.init_database()

    with db.get_connection() as conn:
        # 追加一个真实项目（id=1 兜底项目已由 init_database 插入）
        conn.execute(
            "INSERT INTO projects (id, name, manager, status) VALUES (2, '测试项目', '测试员', 'active')"
        )
        conn.execute(
            "INSERT INTO deliverables (project_id, name, owner, due_date, status) "
            "VALUES (2, '交付物A', '负责人A', '2026-12-31', 'pending')"
        )
        conn.execute(
            "INSERT INTO deliverables (project_id, name, owner, due_date, status) "
            "VALUES (2, '交付物B', '负责人B', '2026-11-30', 'done')"
        )
        conn.execute(
            "INSERT INTO feishu_tasks (title, assignee, deadline, synced) "
            "VALUES ('飞书任务1', '张三', '2026-12-01', 0)"
        )
        conn.execute(
            "INSERT INTO feishu_tasks (title, assignee, deadline, synced) "
            "VALUES ('飞书任务2', '李四', '2026-12-15', 1)"
        )
        conn.commit()

    return db


BPRIME_DELIVERABLE_ID = "VPI-T2-D5"
BPRIME_REVISION = 7
BPRIME_FIXED_AT = "2026-01-05 09:00:00"

_BPRIME_SEED_SQL = """
INSERT INTO project_status_update_bindings (
    deliverable_id, mode, source_type, external_key, match_rule_json, mapping_json,
    enabled, sync_state, cursor_json, sync_config_revision, updated_at
) VALUES ('VPI-T2-D5', 'hybrid', 'tdc', 'BPRIME-EXT-7', '{"reportType": "bprime"}',
          '{"owner": "currentApprover"}', 0, 'failed', '{"cursor": "BPRIME-7"}', 7,
          '2026-01-05 09:00:00')
ON CONFLICT(deliverable_id) DO UPDATE SET
    mode = 'hybrid', source_type = 'tdc', external_key = excluded.external_key,
    match_rule_json = excluded.match_rule_json, mapping_json = excluded.mapping_json,
    enabled = 0, sync_state = 'failed', cursor_json = excluded.cursor_json,
    sync_config_revision = excluded.sync_config_revision, updated_at = excluded.updated_at;

INSERT OR REPLACE INTO project_status_field_authority (deliverable_id, field_name,
    authority, source_type, locked_at, updated_at) VALUES ('VPI-T2-D5', 'progress',
    'manual', 'tdc', '2026-01-05 09:00:00', '2026-01-05 09:00:00');

INSERT OR REPLACE INTO project_status_field_authority (deliverable_id, field_name,
    authority, source_type, locked_at, updated_at) VALUES ('VPI-T2-D5', 'owner',
    'manual', 'tdc', '2026-01-05 09:00:00', '2026-01-05 09:00:00');

INSERT INTO project_status_analysis_snapshots (deliverable_id, source_run_id, total_count,
    completed_count, incomplete_count, overdue_count, due_soon_count,
    missing_due_date_count, snapshot_at)
VALUES ('VPI-T2-D5', NULL, 2, 1, 1, 0, 0, 0, '2026-01-05 09:00:00');

INSERT OR REPLACE INTO project_status_analysis_items
    (deliverable_id, item_key, title, is_completed, updated_at)
VALUES ('VPI-T2-D5', 'BPRIME-ITEM-1', '夹具任务', 1, '2026-01-05 09:00:00');

INSERT INTO project_status_update_audit (deliverable_id, trigger_type, result, created_at)
VALUES ('VPI-T2-D5', 'sync_now', 'skipped', '2026-01-05 09:00:00');
"""


@pytest.fixture
def bprime_audit_case(tmp_db) -> dict:
    """bprime 审计夹具：停用 hybrid 绑定、分析快照/明细与只读快照能力。"""
    from services.project_status_updates import ProjectStatusUpdateService

    def _rows(conn, sql, params=()):
        cursor = conn.execute(sql, params)
        return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

    def _read(conn, sql, params=()):
        if conn is None:
            with tmp_db.get_connection() as own:
                return _rows(own, sql, params)
        return _rows(conn, sql, params)

    with tmp_db.get_connection() as conn:
        conn.executescript(_BPRIME_SEED_SQL)
        conn.commit()

    def snapshot(conn=None) -> dict:
        base = (BPRIME_DELIVERABLE_ID,)
        return {
            "binding": _read(conn, "SELECT * FROM project_status_update_bindings WHERE deliverable_id = ? ORDER BY deliverable_id", base),
            "authorities": _read(conn, "SELECT * FROM project_status_field_authority WHERE deliverable_id = ? ORDER BY field_name", base),
            "analysis_snapshots": _read(conn, "SELECT * FROM project_status_analysis_snapshots WHERE deliverable_id = ? ORDER BY snapshot_at, id", base),
            "analysis_items": _read(conn, "SELECT * FROM project_status_analysis_items WHERE deliverable_id = ? ORDER BY item_key", base),
            "dedicated_audit": _read(conn, "SELECT * FROM project_status_binding_config_audit WHERE deliverable_id = ? ORDER BY id", base),
            "business_audit": _read(conn, "SELECT * FROM project_status_update_audit WHERE deliverable_id = ? ORDER BY id", base),
            "archive_config_audit": _read(conn, "SELECT a.* FROM scheduled_archive_config_audit AS a JOIN scheduled_archive_jobs AS j ON j.id = a.job_id WHERE j.project_status_deliverable_id = ? ORDER BY a.job_id, a.id", base),
            "archive_jobs": _read(conn, "SELECT * FROM scheduled_archive_jobs WHERE project_status_deliverable_id = ? ORDER BY job_key, id", base),
        }

    def audit_rows(conn=None) -> list:
        return _read(conn, "SELECT * FROM project_status_binding_config_audit WHERE deliverable_id = ? ORDER BY id", (BPRIME_DELIVERABLE_ID,))

    return {"db": tmp_db, "service": ProjectStatusUpdateService(tmp_db),
            "deliverable_id": BPRIME_DELIVERABLE_ID, "revision": BPRIME_REVISION,
            "snapshot": snapshot, "audit_rows": audit_rows}


from contextlib import contextmanager as _bprime_contextmanager


@_bprime_contextmanager
def trace(db, label="save"):
    import sys
    from threading import RLock

    name = "record_deliverable_config_audit"
    missing = object()
    get_slot = db.__dict__.get("get_connection", missing)
    rec_slot = db.__dict__.get(name, missing)
    original_get = db.get_connection
    original_rec = getattr(db, name, missing)
    if getattr(original_get, "_bprime_trace", False):
        raise RuntimeError("nested trace on the same database")
    lock = RLock()
    log = {"label": label, "connections": [], "recorder_calls": [],
           "events": [], "recorder_present": original_rec is not missing,
           "recorder_wrapped": callable(original_rec)}

    def emit(kind, **data):
        with lock:
            event = {"seq": len(log["events"]), "kind": kind, **data}
            log["events"].append(event)
            return event

    def restore(attribute, value):
        if value is missing:
            db.__dict__.pop(attribute, None)
        else:
            setattr(db, attribute, value)

    @_bprime_contextmanager
    def get_connection(*args, **kwargs):
        record = None
        try:
            with original_get(*args, **kwargs) as conn:
                record = {"conn": conn, "sql": [], "closed": False,
                          "total_changes_before": conn.total_changes,
                          "total_changes_after": None,
                          "in_transaction_before": conn.in_transaction}
                with lock:
                    log["connections"].append(record)
                record["open_seq"] = emit("connection_open", conn=conn)["seq"]

                def capture(sql):
                    event = emit("sql", conn=conn, sql=sql,
                                 in_transaction=conn.in_transaction)
                    record["sql"].append(event)

                conn.set_trace_callback(capture)
                try:
                    yield conn
                finally:
                    record["total_changes_after"] = conn.total_changes
                    record["in_transaction_after_body"] = conn.in_transaction
        finally:
            if record is not None:
                record["closed"] = True
                record["exit_seq"] = emit("connection_exit", conn=record["conn"])["seq"]

    def recorder(*args, **kwargs):
        conn = kwargs.get("conn")
        call = {"args": args, "kwargs": dict(kwargs), "conn": conn,
                "in_transaction": None if conn is None else conn.in_transaction}
        call["start_seq"] = emit("recorder_enter", conn=conn)["seq"]
        with lock:
            log["recorder_calls"].append(call)
        try:
            result = original_rec(*args, **kwargs)
            call["result"] = result
            return result
        except BaseException as exc:
            call["exception"] = exc
            raise
        finally:
            call["end_seq"] = emit("recorder_exit", conn=conn)["seq"]

    get_connection._bprime_trace = True
    try:
        db.get_connection = get_connection
        if callable(original_rec):
            setattr(db, name, recorder)
        yield log
    finally:
        propagating = sys.exc_info()[0] is not None
        live = [item for item in log["connections"] if not item["closed"]]
        try:
            for item in live:
                item["conn"].set_trace_callback(None)
        finally:
            restore("get_connection", get_slot)
            if callable(original_rec):
                restore(name, rec_slot)
        if live and not propagating:
            raise RuntimeError("trace exited with live connections")
