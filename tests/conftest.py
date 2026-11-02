# -*- coding: utf-8 -*-
"""
tests/conftest.py — 公共 pytest fixtures

提供:
    tmp_db  — 使用 tmp_path 隔离的 DatabaseManager，
              init_database() 已调用，预置若干测试行。
              不污染真实 data/vse_toolbox.db。
"""

import pytest
from core.db_manager import DatabaseManager


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


# ── DSH-V2-27b：测试默认不拉起真实 Excel Worker 子进程 ──────────────────────
# create_app() 默认 process 模式，提交 Excel 任务会经 ensure_running 真实 Popen
# 一个 Worker（约 500MB）；全量测试期间会累积大量子进程。这里只替换控制器模块
# 自己引用的 ``subprocess``（代理对象：除 Popen 外全部委托真实模块），不影响其他
# 测试的子进程。需要真实子进程的用例加 ``@pytest.mark.real_excel_worker``。
# 既有用例 monkeypatch "services.excel_worker_process_controller.subprocess.Popen"
# 会落在代理上，行为不变。


class _InertWorkerProcess:
    """不启动任何进程的 Worker 替身：存活直到 terminate/kill/wait。"""

    _next_pid = 900000

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.pid = _InertWorkerProcess._next_pid
        _InertWorkerProcess._next_pid += 1
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = -9


class _ControllerSubprocessProxy:
    def __init__(self, real):
        self._real = real
        self.Popen = _InertWorkerProcess

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture(autouse=True)
def inert_excel_worker_processes(request, monkeypatch):
    if request.node.get_closest_marker("real_excel_worker") is not None:
        return None
    import subprocess as _real_subprocess

    import services.excel_worker_process_controller as _controller_module

    monkeypatch.setattr(
        _controller_module, "subprocess", _ControllerSubprocessProxy(_real_subprocess)
    )
    return None


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_excel_worker: 允许 ExcelWorkerProcessController 真实拉起 Worker 子进程",
    )
