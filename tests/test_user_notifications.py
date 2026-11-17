# -*- coding: utf-8 -*-
"""DSH-V2-28 托盘通知：文件收件箱发布端、托盘轮询消费端与三类真实事件。

覆盖主控冻结的进程间契约：

1. ``services.user_notifications.publish`` 写 ``state/notifications/<id>.json``，
   同 ``(event, project_id, key)`` 全局幂等；未托管静默返回 False；异常不外抛；
   标题/正文脱敏、去链接与路径并限长；事件闭集外 ``ValueError``。
2. ``vse_boot.tray.TrayNotificationPoller`` 消费消息 → ``notify`` → ``sent`` 账本
   → 删除文件；坏文件进 ``bad/``；``notify`` 抛错最多重试 3 次；重启不重复弹。
3. ``update_found`` 由托盘轮询 ``available_updates`` 产生，同一版本只一次。
4. 真实调用链：``ProjectStatusSyncRunner`` 失败运行与 sign_daily 定时生成成功
   各产生恰好一条消息；成功同步不产生消息；收件箱不可写不影响业务结果。

全部使用 ``tmp_path`` 下真实 ``InstallLayout`` / 真实 SQLite；pystray 一律用假
托盘替身，不触发真实系统通知。
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import sys

import pytest

from core.db_manager import DatabaseManager
from plugins.sign_daily import scheduled
from services import user_notifications
from services.project_status_records import compute_config_signature
from services.project_status_sync_runner import ConnectorRegistry, ProjectStatusSyncRunner
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)
from services.schedule_policy import DAILY_REPORT_JOB_ID
from vse_boot.api import (
    notification_id,
    notifications_dir,
    record_sent_notification,
    sent_notifications,
)
from vse_boot.layout import InstallLayout
from vse_boot.tray import TrayNotificationPoller

DAILY_PROJECT = "sign-daily"
REPORTS_TABLE = "p_sign_daily_scheduled_reports"
SLOT_ROW = {
    "projectId": DAILY_PROJECT,
    "jobId": DAILY_REPORT_JOB_ID,
    "businessDate": "2024-05-06",
    "scheduledTime": "08:30",
}
SLOT_KEY = "sign-daily/daily_report/2024-05-06/08:30"


# ── 公共替身与工具 ────────────────────────────────────────────────


class FakeTray:
    """托盘替身：记录气泡文本；可让前 N 次 ``notify`` 抛错。"""

    def __init__(self, failures: int = 0) -> None:
        self.texts: list[str] = []
        self.calls = 0
        self._failures = failures

    def notify(self, text: str) -> None:
        self.calls += 1
        if self.calls <= self._failures:
            raise RuntimeError("balloon unavailable")
        self.texts.append(text)


def _managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> InstallLayout:
    """托管安装：``VSE_INSTALL_ROOT`` 指向 tmp_path，应用侧才会发布。"""
    layout = InstallLayout(tmp_path)
    monkeypatch.setenv("VSE_INSTALL_ROOT", str(tmp_path))
    return layout


def _message_files(layout: InstallLayout) -> list[Path]:
    directory = notifications_dir(layout)
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.json") if path.name != "sent.json")


def _payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _poller(layout: InstallLayout, handle: FakeTray, **kwargs: Any) -> TrayNotificationPoller:
    kwargs.setdefault("available_updates_fn", lambda _layout: [])
    return TrayNotificationPoller(layout, handle, interval=0.01, **kwargs)


def _publish_daily(layout: InstallLayout, key: str = "slot-1") -> bool:
    return user_notifications.publish(
        "daily_ready",
        project_id=DAILY_PROJECT,
        key=key,
        title="日报已生成",
        body="数据日期 2024-05-06，请到报告中心查看并发送",
        layout=layout,
    )


# ── 1. 发布端：写文件、去重、未托管、异常、脱敏、闭集 ──────────────


def test_publish_writes_message_file_and_dedupes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)

    assert _publish_daily(layout) is True
    [path] = _message_files(layout)
    payload = _payload(path)
    assert path.name == f"{notification_id('daily_ready', DAILY_PROJECT, 'slot-1')}.json"
    assert payload["event"] == "daily_ready"
    assert payload["projectId"] == DAILY_PROJECT
    assert payload["title"] == "日报已生成"
    assert payload["body"] == "数据日期 2024-05-06，请到报告中心查看并发送"
    assert payload["createdAt"].endswith("Z")
    assert not list(notifications_dir(layout).glob("*.tmp"))

    # 同键第二次：文件已在 → 视为已发布。
    assert _publish_daily(layout) is False
    assert len(_message_files(layout)) == 1

    # 换成已送达账本判定：文件被消费后同键仍不再发布。
    record_sent_notification(layout, payload["id"])
    path.unlink()
    assert _publish_daily(layout) is False
    assert _message_files(layout) == []


def test_publish_without_supervisor_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VSE_INSTALL_ROOT", raising=False)
    layout = InstallLayout(tmp_path)

    assert (
        user_notifications.publish(
            "daily_ready",
            project_id=DAILY_PROJECT,
            key="slot-1",
            title="日报已生成",
            body="数据日期 2024-05-06，请到报告中心查看并发送",
        )
        is False
    )
    assert not notifications_dir(layout).exists()


def test_publish_never_raises_when_inbox_is_not_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    notifications_dir(layout).write_text("blocked", encoding="utf-8")

    assert _publish_daily(layout) is False


def test_publish_redacts_and_truncates_title_and_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)

    assert user_notifications.publish(
        "sync_failed",
        project_id="P1",
        key="run-1",
        title="同步失败 token=topsecret",
        body="C:\\Users\\alice\\secret.txt 见 https://example.com/run/1 " + "错" * 300,
        layout=layout,
    )
    [path] = _message_files(layout)
    payload = _payload(path)
    assert "topsecret" not in payload["title"]
    assert "[redacted]" in payload["title"]
    assert len(payload["title"]) <= user_notifications.TITLE_LIMIT
    assert "https://" not in payload["body"]
    assert "C:\\Users" not in payload["body"]
    assert len(payload["body"]) == user_notifications.BODY_LIMIT


def test_publish_rejects_event_outside_closed_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        user_notifications.publish(
            "unknown_event", project_id="P1", key="k", title="t", body="b", layout=layout
        )
    assert _message_files(layout) == []


def test_sent_ledger_keeps_latest_500_ids(tmp_path: Path) -> None:
    layout = InstallLayout(tmp_path)
    for index in range(505):
        record_sent_notification(layout, f"id{index}")

    ids = sent_notifications(layout)
    assert len(ids) == 500
    assert ids[0] == "id5"
    assert ids[-1] == "id504"


# ── 2. 消费端：通知、账本、删除、坏文件、重试、重启 ────────────────


def test_poller_consumes_message_into_tray_and_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    assert _publish_daily(layout) is True
    [path] = _message_files(layout)
    message_id = _payload(path)["id"]
    handle = FakeTray()

    assert _poller(layout, handle).scan_once() == 1
    assert handle.texts == ["日报已生成：数据日期 2024-05-06，请到报告中心查看并发送"]
    assert _message_files(layout) == []
    assert sent_notifications(layout) == [message_id]


def test_restarted_poller_does_not_repeat_a_sent_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    assert _publish_daily(layout) is True
    [path] = _message_files(layout)
    payload = _payload(path)
    assert _poller(layout, FakeTray()).scan_once() == 1

    # 模拟「账本已写、文件未删」后重启：新轮询实例不得重复弹。
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    handle = FakeTray()
    assert _poller(layout, handle).scan_once() == 0
    assert handle.texts == []
    assert _message_files(layout) == []


def test_bad_files_are_quarantined_without_notifying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    directory = notifications_dir(layout)
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    (directory / "unknown-event.json").write_text(
        json.dumps(
            {
                "id": "a" * 32,
                "event": "boom",
                "projectId": "P1",
                "title": "t",
                "body": "b",
                "createdAt": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (directory / "missing-fields.json").write_text(
        json.dumps({"id": "b" * 32, "event": "sync_failed", "projectId": "P1"}),
        encoding="utf-8",
    )
    handle = FakeTray()

    assert _poller(layout, handle).scan_once() == 0
    assert handle.texts == []
    assert _message_files(layout) == []
    assert sorted(path.name for path in (directory / "bad").iterdir()) == [
        "broken.json",
        "missing-fields.json",
        "unknown-event.json",
    ]


def test_notify_failure_is_retried_then_dropped_after_three_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    assert _publish_daily(layout) is True
    [path] = _message_files(layout)
    message_id = _payload(path)["id"]
    handle = FakeTray(failures=99)
    poller = _poller(layout, handle)

    for _ in range(2):
        assert poller.scan_once() == 0
        assert len(_message_files(layout)) == 1

    assert poller.scan_once() == 0
    assert handle.calls == 3
    assert _message_files(layout) == []
    assert sent_notifications(layout) == [message_id]

    # 丢弃后不再重试。
    assert poller.scan_once() == 0
    assert handle.calls == 3


def test_poller_thread_exits_on_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    handle = FakeTray()
    poller = _poller(layout, handle)
    poller.start()
    try:
        assert _publish_daily(layout) is True
        deadline = time.monotonic() + 3.0
        while not handle.texts and time.monotonic() < deadline:
            time.sleep(0.01)
        assert handle.texts
    finally:
        poller.stop()

    assert poller._thread is not None
    assert not poller._thread.is_alive()
    assert poller._stop.is_set()


# ── 3. 更新发现：同一版本只一次 ────────────────────────────────────


def test_update_found_notifies_once_per_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    candidates = [
        SimpleNamespace(version="1.2.3"),
        SimpleNamespace(version="9.9.9"),
        SimpleNamespace(version="not-a-version"),
    ]
    handle = FakeTray()
    poller = _poller(layout, handle, available_updates_fn=lambda _layout: candidates)

    assert poller.check_updates() == 2
    payloads = [_payload(path) for path in _message_files(layout)]
    assert {item["event"] for item in payloads} == {"update_found"}
    assert {item["projectId"] for item in payloads} == {"app"}
    assert poller.check_updates() == 0  # 消息文件已存在

    assert poller.scan_once() == 2
    assert sorted(handle.texts) == [
        "发现新版本：1.2.3 已就绪，可在托盘菜单检查更新",
        "发现新版本：9.9.9 已就绪，可在托盘菜单检查更新",
    ]

    # 新轮询实例同目录：账本已记录，同一版本只一次。
    restarted = _poller(layout, FakeTray(), available_updates_fn=lambda _layout: candidates)
    assert restarted.check_updates() == 0
    assert restarted.scan_once() == 0


def test_update_scan_honours_injected_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    now = [0.0]
    calls: list[int] = []

    def fake_updates(_layout: InstallLayout) -> list[Any]:
        calls.append(1)
        return []

    poller = _poller(
        layout,
        FakeTray(),
        update_interval=600.0,
        clock=lambda: now[0],
        available_updates_fn=fake_updates,
    )
    poller.poll_once()
    poller.poll_once()
    assert len(calls) == 1

    now[0] = 601.0
    poller.poll_once()
    assert len(calls) == 2


# ── 4. 真实调用链：同步失败 / 日报成功 / 成功同步不发布 ─────────────


def _record_two_observations(
    db: DatabaseManager,
    deliverable_id: str = "VPI-T2-D5",
    source_type: str = "tdc",
    external_key: str = "FM-1",
) -> None:
    fields = [
        "currentApprover",
        "approvalComment",
        "incident",
        "reportType",
        "ewoNo",
        "projectCode",
        "subjectKeyword",
    ]
    report = {
        "fields": fields,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
    match_rule = {"reportType": "data_model", "incident": external_key}
    signature = compute_config_signature(source_type, match_rule)
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
            config_signature=signature,
        )


def _enable_pilot(service: ProjectStatusUpdateService) -> None:
    _record_two_observations(service._db)
    service.update_update_policy(
        "VPI-T2-D5",
        {
            "mode": "hybrid",
            "enabled": True,
            "externalKey": "FM-1",
            "matchRule": {"reportType": "data_model", "incident": "FM-1"},
            "mapping": {"owner": "currentApprover", "note": "approvalComment"},
            "fieldAuthority": {"owner": "automatic", "note": "automatic"},
            "credentialRef": "test-credential-ref",
        },
    )


def _current_updated_at(db: DatabaseManager, deliverable_id: str) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (deliverable_id,),
        ).fetchone()
    assert row is not None
    return str(row["updated_at"])


def _matched_snapshot(db: DatabaseManager) -> ConnectorSnapshot:
    return ConnectorSnapshot(
        match_state="matched",
        candidates=[
            ConnectorCandidate(
                external_key="FM-1",
                external_version="v-ok",
                field_values={"owner": "ok", "note": "ok"},
                fetched_at="2026-08-20T00:00:00.000Z",
            )
        ],
        external_version="v-ok",
        fetched_at="2026-08-20T00:00:00.000Z",
        expected_deliverable_updated_at=_current_updated_at(db, "VPI-T2-D5"),
    )


class FailingConnector:
    def collect(self, context: Any) -> ConnectorSnapshot:
        raise RuntimeError("boom password=secret")


class FixedConnector:
    def __init__(self, snapshot: ConnectorSnapshot) -> None:
        self._snapshot = snapshot

    def collect(self, context: Any) -> ConnectorSnapshot:
        return self._snapshot


@pytest.fixture()
def sync_env(tmp_path: Path) -> SimpleNamespace:
    db = DatabaseManager(db_path=tmp_path / "runner.db")
    db.init_database()
    service = ProjectStatusUpdateService(db)
    registry = ConnectorRegistry()
    return SimpleNamespace(
        db=db,
        service=service,
        registry=registry,
        runner=ProjectStatusSyncRunner(db, service, registry),
    )


def test_sync_failure_publishes_exactly_one_message(
    sync_env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    _enable_pilot(sync_env.service)
    sync_env.registry.register("tdc", FailingConnector())

    result = sync_env.runner.run_once(validate_runtime_prerequisites=False)

    item = result.results[0]
    assert item.final_state == "failed" and item.run_id is not None
    [path] = _message_files(layout)
    payload = _payload(path)
    assert payload["event"] == "sync_failed"
    assert payload["projectId"] == "VPI-T2-D5"
    assert payload["id"] == notification_id(
        "sync_failed", "VPI-T2-D5", f"VPI-T2-D5:{item.run_id}"
    )
    assert "secret" not in payload["body"]
    assert "connector failure" in payload["body"]

    # 真实事件到达托盘：轮询消费后气泡文本与业务结果一致。
    handle = FakeTray()
    assert _poller(layout, handle).scan_once() == 1
    assert handle.texts == ["项目状态同步失败：同步未完成：connector failure"]
    assert _message_files(layout) == []


def test_sync_success_publishes_nothing(
    sync_env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    _enable_pilot(sync_env.service)
    sync_env.registry.register("tdc", FixedConnector(_matched_snapshot(sync_env.db)))

    result = sync_env.runner.run_once()

    assert result.exit_code == 0
    assert _message_files(layout) == []


def test_sync_result_survives_unwritable_inbox(
    sync_env: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _managed(tmp_path, monkeypatch)
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    notifications_dir(layout).write_text("blocked", encoding="utf-8")
    _enable_pilot(sync_env.service)
    sync_env.registry.register("tdc", FailingConnector())

    result = sync_env.runner.run_once(validate_runtime_prerequisites=False)

    assert result.exit_code == 1
    assert result.results[0].error_type == "connector_error"


# ── 5. 真实调用链：日报定时生成成功 ────────────────────────────────


class _DailyDb:
    """日报作业所需的最小数据库面：真实 SQLite 连接 + 快照/归档读取。"""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row

    @contextmanager
    def get_connection(self) -> Any:
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def list_deliverable_form_snapshots(self, form_key: str, limit: int = 60) -> list[dict[str, Any]]:
        return [{"snapshot_at": "2024-05-06T00:10:00Z"}]

    def list_archive_jobs(self) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        self._conn.close()


class _DailyStore:
    def config(self) -> dict[str, Any]:
        return {
            "form": {
                "projects": ["F610M"],
                "departments": [],
                "watchlistOnly": False,
                "region": "车体区域",
            },
            "thresholds": {},
        }


def _fake_build_report(**_kwargs: Any) -> dict[str, Any]:
    return {
        "subject": "F610M项目3D单签署进展-车体区域-20240506",
        "dataDate": "2024-05-06",
        "html": "<p>report</p>",
        "text": "report",
        "statusGate": {"blocked": False},
        "exportBlocked": False,
    }


@pytest.fixture()
def daily_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    layout = _managed(tmp_path, monkeypatch)
    db = _DailyDb(tmp_path / "daily.db")
    reports = scheduled.ScheduledReportStore(db, "p_sign_daily_")
    _version, migrate = reports.migration()
    with db.get_connection() as conn:
        migrate(conn)
    monkeypatch.setattr(scheduled, "build_report", _fake_build_report)
    monkeypatch.setattr(
        scheduled, "start_refresh", lambda **kwargs: ({"taskId": "task-1"}, False)
    )
    monkeypatch.setattr(
        scheduled, "wait_refresh", lambda *args, **kwargs: {"status": "succeeded"}
    )
    job = scheduled.DailyReportJob(
        db=db,
        store=_DailyStore(),
        snapshots=object(),
        reports=reports,
        effective=lambda config: None,
        runner_factory=lambda: object(),
        archive_factory=lambda: object(),
        data_tz=lambda: timezone.utc,
        clock=lambda: datetime(2024, 5, 6, 0, 30, tzinfo=timezone.utc),
    )
    try:
        yield SimpleNamespace(layout=layout, db=db, reports=reports, job=job)
    finally:
        db.close()


def _report_count(db: _DailyDb) -> int:
    with db.get_connection() as conn:
        return int(
            conn.execute(f"SELECT COUNT(*) AS c FROM {REPORTS_TABLE}").fetchone()["c"]
        )


def test_daily_generation_publishes_exactly_one_message(daily_env: Any) -> None:
    outcome = daily_env.job.handle(SLOT_ROW)

    assert outcome.ok is True
    assert _report_count(daily_env.db) == 1
    [path] = _message_files(daily_env.layout)
    payload = _payload(path)
    assert payload["event"] == "daily_ready"
    assert payload["projectId"] == DAILY_PROJECT
    assert payload["title"] == "日报已生成"
    assert "2024-05-06" in payload["body"]
    assert "请到报告中心查看并发送" in payload["body"]
    assert payload["id"] == notification_id("daily_ready", DAILY_PROJECT, SLOT_KEY)

    # 真实事件到达托盘：消费后气泡含数据日期与查看指引。
    handle = FakeTray()
    assert _poller(daily_env.layout, handle).scan_once() == 1
    assert handle.texts == ["日报已生成：数据日期 2024-05-06，请到报告中心查看并发送"]
    assert _message_files(daily_env.layout) == []

    # 同槽重复执行仍成功；账本已记录，不再产生消息。
    assert daily_env.job.handle(SLOT_ROW).ok is True
    assert _message_files(daily_env.layout) == []


def test_daily_generation_survives_unwritable_inbox(daily_env: Any) -> None:
    daily_env.layout.state_dir.mkdir(parents=True, exist_ok=True)
    notifications_dir(daily_env.layout).write_text("blocked", encoding="utf-8")

    outcome = daily_env.job.handle(SLOT_ROW)

    assert outcome.ok is True
    assert _report_count(daily_env.db) == 1
    assert _message_files(daily_env.layout) == []


def test_app_imports_under_old_launcher_without_notification_api(monkeypatch) -> None:
    """旧版启动器（vse_boot.api 没有通知收件箱接口）上运行新应用包：不得导入失败。

    回归：2.4.0 应用包装进 2.3.0 启动器时，顶层 ``from vse_boot.api import ...`` 抛
    ImportError，应用启动即退出（用户反馈“加载测试包后闪退”）。
    """
    import importlib
    import types

    import services.user_notifications as module

    old_api = types.ModuleType("vse_boot.api")
    old_api.managed_layout = lambda: None  # 旧启动器只有这些既有接口
    monkeypatch.setitem(sys.modules, "vse_boot.api", old_api)
    try:
        reloaded = importlib.reload(module)
        assert reloaded.LAUNCHER_SUPPORTS_NOTIFICATIONS is False
        assert reloaded.publish(
            "sync_failed", project_id="p", key="k", title="t", body="b"
        ) is False
        with pytest.raises(ValueError):
            reloaded.publish("bogus", project_id="p", key="k", title="t", body="b")
    finally:
        monkeypatch.undo()
        importlib.reload(module)
    assert module.LAUNCHER_SUPPORTS_NOTIFICATIONS is True
