# -*- coding: utf-8 -*-
"""DSH-V2-30：同步运行 ↔ 历史原件的追踪、同次性与清理边界（真实调用链）。

全部用例都走真实实现，不 mock 文件系统、SQLite 或浏览器：

1. 成功同步：假连接器经**真实** ``ArchiveStore`` 写出的原件清单，随
   ``finalize_sync_success`` 落到 ``project_status_sync_artifacts``（run_id 关联），
   并同时进入 ``deliverable_form_snapshots.artifacts_json``（runner L566 一路）。
2. 第二次运行不覆盖第一次原件：两个 run_id 目录与两份清单并存。
3. 原件写入失败：运行如实 failed，清单为空，失败文件不冒充已留存，
   上一次成功运行的原件与清单原样保留。
4. 7 天临时清理只删 ``downloads`` 目录；``ArchiveStore`` 根下的历史原件不动。
5. 同步路径从不隐式执行 ArchiveStore retention；只有显式调用才删除。
6. 定时归档运行同样只登记本次 run_id 目录里的原件（同次性，无二次抓取回填）。
7. 前端 ``archive-deliverable.js`` 的「历史原件」：真实浏览器 + 真实 HTTP +
   真实 SQLite，按运行列出（北京时间 / run_id / 类型 / 大小）；运行目录不存在
   时显示「原件缺失」；没有清单的旧运行显示「该次运行未记录原件清单」。

运行::

    python -B -m pytest -p no:cacheprovider tests/test_sync_originals_integration.py -q
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from core.archive_store import ArchiveCapacityError, ArchiveStore
from core.credential_provider import MemoryCredentialProvider
from core.db_manager import DatabaseManager
from services.crawl_task_runner import CrawlTaskRunner
from services.project_status_records import compute_config_signature
from services.project_status_sync_runner import (
    EXIT_OK,
    ConnectorRegistry,
    ProjectStatusSyncRunner,
)
from services.project_status_updates import (
    ConnectorCandidate,
    ConnectorSnapshot,
    ProjectStatusUpdateService,
)
from services.scheduled_archive_runner import (
    ArchiveCollection,
    ArchiveConnectorRegistry,
    ArchiveSyncRunner,
)
from tests.browser.v2_fixtures import (  # noqa: F401 - pytest fixture 注入
    BrowserPage,
    LiveServer,
    assert_no_console_errors,
    browser,
    page,
    server,
)

DAY = 86400.0
SYNC_DELIVERABLE = "VPI-T2-D5"
SYNC_FORM_KEY = "tdc_data_model"
ARCHIVE_JOB_KEY = "aras_ewo"

#: 外壳启动握手先 POST boot-claim，无预置授权时 409 是正常路径（既有用例同口径）。
BOOT_CLAIM_PROBE = re.compile(r"status of 409 \(CONFLICT\).*/api/security/boot-claim")
#: 「原件缺失」用例会主动查询已删除的运行目录：浏览器把这次 404 记为网络错误。
ARCHIVE_FOLDER_404 = re.compile(r"status of 404 .*/api/scheduled-archive/folders")
ARCHIVE_ROUTE = "#p/project-overview/archive-deliverable?job=aras_ewo"


# ── 同步侧 fixture 与假连接器（真实 ArchiveStore 写原件） ────────────────────


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(db_path=tmp_path / "sync_originals.db")
    manager.init_database()
    return manager


@pytest.fixture()
def archive(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore({"default": tmp_path / "archive-root"})


@pytest.fixture()
def service(db: DatabaseManager) -> ProjectStatusUpdateService:
    return ProjectStatusUpdateService(db)


@pytest.fixture()
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


@pytest.fixture()
def runner(
    db: DatabaseManager,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
) -> ProjectStatusSyncRunner:
    return ProjectStatusSyncRunner(db, service, registry)


def _record_two_observations(
    db: DatabaseManager,
    deliverable_id: str = SYNC_DELIVERABLE,
    source_type: str = "tdc",
    external_key: str = "FM-1",
) -> None:
    field_list = ["currentApprover", "approvalComment", "incident", "reportType"]
    report = {
        "fields": field_list,
        "statusOrApprovalFields": [],
        "suggestedStatusMapping": [],
        "suggestedAutomaticFields": [],
        "requiresConfirmation": True,
    }
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
            candidate_summary_json=json.dumps(
                [{"externalKey": external_key, "fields": {}}]
            ),
            field_report_json=json.dumps(report),
            config_signature=config_signature,
        )


def _enable_pilot(service: ProjectStatusUpdateService) -> int:
    """启用 VPI-T2-D5（tdc）绑定；返回 binding_id。"""
    _record_two_observations(service._db)
    service.update_update_policy(
        SYNC_DELIVERABLE,
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
    with service._db.get_connection() as conn:
        return int(
            conn.execute(
                "SELECT id FROM project_status_update_bindings "
                "WHERE deliverable_id=?",
                (SYNC_DELIVERABLE,),
            ).fetchone()["id"]
        )


def _current_updated_at(db: DatabaseManager) -> str:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT updated_at FROM project_status_deliverables WHERE id = ?",
            (SYNC_DELIVERABLE,),
        ).fetchone()
    assert row is not None
    return str(row["updated_at"])


class OriginalWritingConnector:
    """假连接器：经真实 ``ArchiveStore`` 写原件，再返回带清单的快照。

    ``fail_at`` 指定第几个文件写入时抛 ``ArchiveCapacityError``（0 基）：
    之前的文件已经真实落盘（只增不删），用于验证「失败不冒充已留存」。
    """

    def __init__(
        self,
        archive: ArchiveStore,
        updated_at: Callable[[], str],
        *,
        fail_at: int | None = None,
    ) -> None:
        self._archive = archive
        self._updated_at = updated_at
        self._fail_at = fail_at
        self.contexts: list[Any] = []

    def collect(self, context: Any) -> ConnectorSnapshot:
        self.contexts.append(context)
        artifacts: list[dict[str, Any]] = []
        for index, (file_name, artifact_type) in enumerate(
            (("records.csv", "csv"), ("records.json", "json"))
        ):
            if self._fail_at is not None and index >= self._fail_at:
                raise ArchiveCapacityError("simulated archive capacity failure")
            item = self._archive.write_bytes(
                f"row-{index}".encode("utf-8"),
                source="tdc",
                report="data_model",
                run_id=context.run_id,
                file_name=file_name,
                artifact_type=artifact_type,
            )
            artifacts.append(item.as_metadata())
        external_version = f"v-{context.run_id}"
        return ConnectorSnapshot(
            match_state="matched",
            candidates=(
                ConnectorCandidate(
                    external_key="FM-1",
                    external_version=external_version,
                    field_values={"owner": "负责人", "note": "ok"},
                    fetched_at="2026-08-20T00:00:00.000Z",
                ),
            ),
            external_version=external_version,
            fetched_at="2026-08-20T00:00:00.000Z",
            expected_deliverable_updated_at=self._updated_at(),
            artifacts=tuple(artifacts),
            analysis_rows=(
                {
                    "incident": "90000101",
                    "documentNo": "3D-00001018",
                    "partNumber": "27000001",
                    "projectModel": "F999X",
                    "status": "2",
                },
            ),
        )


def _run_paths(archive: ArchiveStore, rows: list[Mapping[str, Any]]) -> list[Path]:
    return [archive.root() / str(row["relative_path"]) for row in rows]


# ── 1. 成功运行：run_id ↔ 原件清单持久化，文件在 run_id 目录 ────────────────


def test_successful_run_persists_run_id_artifact_tracking(
    db: DatabaseManager,
    archive: ArchiveStore,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
    runner: ProjectStatusSyncRunner,
) -> None:
    _enable_pilot(service)
    connector = OriginalWritingConnector(archive, lambda: _current_updated_at(db))
    registry.register("tdc", connector)

    result = runner.run_once()

    assert result.exit_code == EXIT_OK
    item = result.results[0]
    assert item.final_state == "success"
    assert item.run_id is not None
    # 同次性：一次同步只调用一次连接器，清单里的文件全部写在该 run_id 目录。
    assert len(connector.contexts) == 1
    assert connector.contexts[0].run_id == item.run_id

    rows = db.list_sync_artifacts(item.run_id)
    assert [row["artifact_type"] for row in rows] == ["csv", "json"]
    assert {row["run_id"] for row in rows} == {item.run_id}
    for row in rows:
        path = archive.root() / str(row["relative_path"])
        assert path.is_file(), f"清单记录的原件必须真实存在：{row['relative_path']}"
        assert path.stat().st_size == row["size_bytes"]
        assert row["sha256"]
        assert f"/{item.run_id}/" in f"/{row['relative_path']}"

    # runner L566 一路：表单快照同时保存同一份清单与 source_run_id。
    stored = db.get_latest_deliverable_form_snapshot(SYNC_FORM_KEY)
    assert stored is not None
    assert stored["source_run_id"] == item.run_id
    assert [artifact["relative_path"] for artifact in stored["artifacts"]] == [
        row["relative_path"] for row in rows
    ]


# ── 2. 第二次运行不覆盖第一次原件 ──────────────────────────────────────────


def test_second_run_never_overwrites_first_run_originals(
    db: DatabaseManager,
    archive: ArchiveStore,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
    runner: ProjectStatusSyncRunner,
) -> None:
    _enable_pilot(service)
    registry.register("tdc", OriginalWritingConnector(archive, lambda: _current_updated_at(db)))

    first = runner.run_once().results[0]
    second = runner.run_once().results[0]

    assert first.final_state == second.final_state == "success"
    assert first.run_id != second.run_id
    first_rows = db.list_sync_artifacts(first.run_id)
    second_rows = db.list_sync_artifacts(second.run_id)
    assert len(first_rows) == len(second_rows) == 2

    first_paths = {str(row["relative_path"]) for row in first_rows}
    second_paths = {str(row["relative_path"]) for row in second_rows}
    assert first_paths.isdisjoint(second_paths)
    for path in _run_paths(archive, first_rows + second_rows):
        assert path.is_file(), f"两次运行的原件都必须保留：{path}"

    # 第一次运行的清单仍然按自己的 run_id 可查（只增不删）。
    assert {row["run_id"] for row in db.list_sync_artifacts(first.run_id)} == {first.run_id}
    assert {row["run_id"] for row in db.list_sync_artifacts(second.run_id)} == {second.run_id}


# ── 3. 原件写入失败：不报已留存，清单不含失败文件，上次原件仍在 ─────────────


def test_archive_write_failure_is_failed_and_never_claims_retention(
    db: DatabaseManager,
    archive: ArchiveStore,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
    runner: ProjectStatusSyncRunner,
) -> None:
    _enable_pilot(service)
    registry.register("tdc", OriginalWritingConnector(archive, lambda: _current_updated_at(db)))
    ok_run = runner.run_once().results[0]
    ok_rows = db.list_sync_artifacts(ok_run.run_id)
    ok_paths = _run_paths(archive, ok_rows)
    assert all(path.is_file() for path in ok_paths)

    # 第二次运行：第一个文件写出后，第二个文件写入抛 ArchiveCapacityError。
    registry.register(
        "tdc",
        OriginalWritingConnector(
            archive,
            lambda: _current_updated_at(db),
            fail_at=1,
        ),
    )
    failed = runner.run_once().results[0]

    assert failed.outcome == "failed"
    assert failed.final_state == "failed"
    assert failed.run_id is not None and failed.run_id != ok_run.run_id
    assert "留存" not in str(failed.error_message or "")
    run_row = db.get_sync_run(failed.run_id)
    assert run_row is not None and run_row["run_state"] == "failed"

    # 失败运行不写清单：未写成功的文件绝不冒充「已留存」。
    assert db.list_sync_artifacts(failed.run_id) == []

    # 失败尝试已落盘的文件保留（只增不删），但不在任何清单里。
    failed_files = [
        path
        for path in archive.root().rglob("*")
        if path.is_file() and f"/{failed.run_id}/" in path.as_posix()
    ]
    assert failed_files, "失败尝试已写出的文件不得被删除（只增不删）"
    listed_paths = {str(row["relative_path"]) for row in db.list_sync_artifacts(ok_run.run_id)}
    for path in failed_files:
        assert path.relative_to(archive.root()).as_posix() not in listed_paths

    # 上一次成功运行的原件与清单原样保留；表单快照仍指向成功运行。
    assert all(path.is_file() for path in ok_paths)
    assert [row["id"] for row in db.list_sync_artifacts(ok_run.run_id)] == [
        row["id"] for row in ok_rows
    ]
    stored = db.get_latest_deliverable_form_snapshot(SYNC_FORM_KEY)
    assert stored is not None and stored["source_run_id"] == ok_run.run_id


# ── 4. 7 天临时清理与历史原件目录边界 ──────────────────────────────────────


def test_seven_day_cleanup_never_touches_archive_originals(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "cleanup_boundary.db")
    db.init_database()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    archive = ArchiveStore({"default": tmp_path / "archive-root"})
    original = archive.write_bytes(
        b"historical original",
        source="tdc",
        report="data_model",
        run_id=7,
        file_name="records.csv",
        artifact_type="csv",
    )
    original_path = archive.root() / original.relative_path
    aged = time.time() - 30 * DAY
    os.utime(original_path, (aged, aged))

    task_id = "crawl_old0000000001"
    db.create_crawl_task(task_id, "paa_export", "aras")
    db.update_crawl_task_status(task_id, "succeeded", artifact_path=f"{task_id}.csv")
    expired = downloads / f"{task_id}.csv"
    expired.write_bytes(b"temporary artifact")
    os.utime(expired, (aged, aged))

    cleanup_runner = CrawlTaskRunner(
        db=db,
        downloads_dir=downloads,
        max_workers=1,
        clock=time.time,
    )
    try:
        report = cleanup_runner.cleanup_expired_artifacts(now=time.time())
    finally:
        cleanup_runner.shutdown(wait=True)

    assert report.ok, report
    assert Path(report.directory).resolve() == downloads.resolve()
    assert expired.name in report.removed
    assert not expired.exists(), "过期临时产物必须被 7 天清理删除"
    assert original_path.is_file(), "7 天清理不得触碰 ArchiveStore 根下的历史原件"


# ── 5. 同步路径不隐式执行 retention；只有显式调用才删除 ────────────────────


def test_sync_never_runs_archive_retention_implicitly(
    db: DatabaseManager,
    archive: ArchiveStore,
    service: ProjectStatusUpdateService,
    registry: ConnectorRegistry,
    runner: ProjectStatusSyncRunner,
) -> None:
    _enable_pilot(service)
    registry.register("tdc", OriginalWritingConnector(archive, lambda: _current_updated_at(db)))

    first = runner.run_once().results[0]
    first_rows = db.list_sync_artifacts(first.run_id)
    aged = time.time() - 200 * DAY
    for path in _run_paths(archive, first_rows):
        os.utime(path, (aged, aged))

    second = runner.run_once().results[0]
    assert second.run_id != first.run_id

    # 同步路径（含第二次运行）不会隐式执行 ArchiveStore retention。
    for path in _run_paths(archive, first_rows):
        assert path.is_file(), f"同步不得删除旧原件：{path}"
    assert len(db.list_sync_artifacts(first.run_id)) == len(first_rows)

    # 只有显式调用 plan/execute_retention 才会删除历史原件。
    plan = archive.plan_retention(retention_days=90)
    planned = {item.relative_path for item in plan}
    assert {str(row["relative_path"]) for row in first_rows} <= planned
    removed = archive.execute_retention(plan)
    assert {str(row["relative_path"]) for row in first_rows} <= set(removed)
    for path in _run_paths(archive, first_rows):
        assert not path.exists()


# ── 6. 前端「历史原件」：真实浏览器 / 真实 HTTP / 真实 SQLite ───────────────


class ArchiveJobWritingConnector:
    """归档任务假连接器：经真实 ``ArchiveStore`` 写原件并返回集合。"""

    def __init__(self, archive: ArchiveStore, *, fail: bool = False) -> None:
        self._archive = archive
        self._fail = fail

    def collect(self, context: Any, credential: Any) -> ArchiveCollection:
        if self._fail:
            raise ValueError("synthetic archive failure")
        item = self._archive.write_bytes(
            b"archived records",
            source=context.source_type,
            report=context.report_type,
            run_id=context.run_id,
            output_subdir=context.output_subdir,
            file_name="records.csv",
            artifact_type="normalized_csv",
        )
        return ArchiveCollection(record_count=1, artifacts=(item,))


def _enable_archive_job(db: DatabaseManager, job_key: str = ARCHIVE_JOB_KEY) -> int:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET enabled=1, credential_ref=? "
            "WHERE job_key=?",
            ("alias_test", job_key),
        )
        row = conn.execute(
            "SELECT id FROM scheduled_archive_jobs WHERE job_key=?", (job_key,)
        ).fetchone()
    assert row is not None
    return int(row["id"])


def _seed_archive_run(
    db: DatabaseManager,
    archive: ArchiveStore,
    *,
    fail: bool = False,
) -> int:
    job_id = _enable_archive_job(db)
    registry = ArchiveConnectorRegistry()
    registry.register(
        ARCHIVE_JOB_KEY, ArchiveJobWritingConnector(archive, fail=fail)
    )
    runner = ArchiveSyncRunner(
        db,
        MemoryCredentialProvider({"alias_test": ("synthetic-user", "synthetic-secret")}),
        registry,
    )
    result = runner.run_job(
        job_id,
        job_key=ARCHIVE_JOB_KEY,
        trigger_type="sync_now",
        validate_runtime_prerequisites=False,
    )
    assert result.run_id is not None
    if fail:
        assert result.outcome == "failed", result
    else:
        assert result.outcome == "completed", result
    return int(result.run_id)


def test_scheduled_archive_run_records_only_same_run_originals(tmp_path: Path) -> None:
    """归档运行只登记本次 run_id 目录里的原件（同次性，无二次抓取回填）。"""
    db = DatabaseManager(db_path=tmp_path / "archive_same_run.db")
    db.init_database()
    archive = ArchiveStore({"default": tmp_path / "archive-same-run"})

    run_id = _seed_archive_run(db, archive)

    rows = db.list_archive_artifacts(run_id)
    assert rows, "成功的归档运行必须登记原件清单"
    for row in rows:
        assert f"/{run_id}/" in f"/{row['relative_path']}", row
        assert (archive.root() / str(row["relative_path"])).is_file(), row
    assert {row["run_id"] for row in rows} == {run_id}


def _beijing_text(value: str) -> str:
    """UTC ISO 时间 → 北京时间 'YYYY-MM-DD HH:mm'（与宿主 time-format 同口径）。"""
    from datetime import datetime, timedelta, timezone

    text = str(value).strip()
    parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    shifted = parsed.astimezone(timezone(timedelta(hours=8)))
    return shifted.strftime("%Y-%m-%d %H:%M")


def _text_js(selector: str) -> str:
    return (
        "(() => { const el = document.querySelector(%s);"
        " return el ? el.innerText.trim() : ''; })()" % json.dumps(selector)
    )


def _text_of(page_obj: BrowserPage, selector: str) -> str:
    return str(page_obj.eval(_text_js(selector)))


def test_archive_deliverable_lists_originals_per_run(
    server: LiveServer,
    page: BrowserPage,  # noqa: F811 - 参数名就是 fixture 名
    tmp_path: Path,
) -> None:
    """按运行列出原件（北京时间/run_id/类型/大小）、缺失与旧运行无清单文案。"""
    db = server.app.extensions["scheduled_archive_admin"]._db
    archive = ArchiveStore({"default": tmp_path / "browser-archive"})
    db.update_app_settings({"archiveDirectory": str(archive.root())})

    present_run = _seed_archive_run(db, archive)
    missing_run = _seed_archive_run(db, archive)
    empty_run = _seed_archive_run(db, archive, fail=True)

    # 让 missing_run 的运行目录整体消失：清单还在，但文件已不存在。
    missing_rows = db.list_archive_artifacts(missing_run)
    assert missing_rows
    missing_dir = (archive.root() / missing_rows[0]["relative_path"]).parent
    shutil.rmtree(missing_dir)
    assert not missing_dir.exists()

    page.goto(server.route_url(ARCHIVE_ROUTE))
    page.wait_for_selector(".archive-originals-run")

    runs = page.eval(
        "Array.from(document.querySelectorAll('.archive-originals-run'))"
        ".map((row) => row.getAttribute('data-run-id'))"
    )
    assert [int(value) for value in runs] == [empty_run, missing_run, present_run], page.diagnose(
        f"历史原件未按运行列出：{runs}"
    )

    with db.get_connection() as conn:
        finished = {
            int(row["id"]): row["finished_at"]
            for row in conn.execute(
                "SELECT id, finished_at FROM scheduled_archive_runs WHERE id IN (?,?,?)",
                (present_run, missing_run, empty_run),
            )
        }
    for run_id in (present_run, missing_run, empty_run):
        row_text = _text_of(page, f".archive-originals-run[data-run-id='{run_id}']")
        assert f"#{run_id}" in row_text, page.diagnose(f"运行 {run_id} 未显示 run_id：{row_text}")
        assert _beijing_text(finished[run_id]) in row_text, page.diagnose(
            f"运行 {run_id} 未按北京时间显示：{row_text}"
        )

    # 正常运行的清单：类型 + 大小 + 记录状态。
    page.click(selector=f".archive-originals-run[data-run-id='{present_run}'] .archive-originals-toggle")
    page.wait_for_selector(
        f".archive-originals-detail[data-run-id='{present_run}'] .archive-original-artifact"
    )
    present_text = _text_of(page, f".archive-originals-detail[data-run-id='{present_run}']")
    assert "records.csv" in present_text, page.diagnose(f"原件名称未渲染：{present_text}")
    assert "normalized_csv" in present_text, page.diagnose(f"原件类型未渲染：{present_text}")
    assert "16 B" in present_text, page.diagnose(f"原件大小未渲染：{present_text}")
    assert "原件缺失" not in present_text, page.diagnose("文件存在却显示原件缺失")
    assert (
        page.eval(
            "document.querySelectorAll("
            f"\".archive-originals-detail[data-run-id='{present_run}'] .archive-original-artifact\""
            ").length"
        )
        == 1
    )

    # 运行目录被删除：显示「原件缺失」而不是可下载。
    page.click(selector=f".archive-originals-run[data-run-id='{missing_run}'] .archive-originals-toggle")
    page.wait_for_selector(
        f".archive-originals-detail[data-run-id='{missing_run}'] .archive-original-state.is-missing"
    )
    missing_text = _text_of(page, f".archive-originals-detail[data-run-id='{missing_run}']")
    assert "原件缺失" in missing_text, page.diagnose(f"缺失原件未标注：{missing_text}")
    assert page.eval(
        "document.querySelectorAll("
        f"\".archive-originals-detail[data-run-id='{missing_run}'] a[download]\").length"
    ) == 0, page.diagnose("原件缺失时不得提供下载入口")

    # 没有清单的旧运行：明确文案，不伪装成「已留存」。
    page.click(selector=f".archive-originals-run[data-run-id='{empty_run}'] .archive-originals-toggle")
    page.wait_for_selector(
        f".archive-originals-detail[data-run-id='{empty_run}'] .archive-originals-empty"
    )
    empty_text = _text_of(page, f".archive-originals-detail[data-run-id='{empty_run}']")
    assert "该次运行未记录原件清单" in empty_text, page.diagnose(
        f"旧运行缺少无清单文案：{empty_text}"
    )

    assert_no_console_errors(page, allow=(BOOT_CLAIM_PROBE, ARCHIVE_FOLDER_404))
