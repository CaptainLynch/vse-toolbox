# -*- coding: utf-8 -*-
"""
tests/test_archive_jobs.py — 归档任务种子与离线关系约束测试

覆盖验收标准:
1. 断言 schema 版本为 2，且存在三张 scheduled_archive 表结构
2. 断言 6 个固定 job_key，默认 disabled (enabled=0)，interval_minutes=60，max_attempts=2
3. 断言 D2/D3/D5 仅关联 SOR/EWO/data-model，PAA/NCR 关联为空，且不存在 A 面任务
4. 断言重复调用 init_database() 保留已修改的 enabled / interval 等配置
5. 断言离线 run / artifact 外键约束（RESTRICT / CASCADE）与 duplicate relative_path 唯一约束校验
"""

from __future__ import annotations

import concurrent.futures
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from core.db_manager import (
    CURRENT_SCHEMA_VERSION,
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    ArchiveLeaseLostError,
    DatabaseManager,
)

EXPECTED_SEEDS: dict[str, dict[str, str | None]] = {
    "aras_ewo": {
        "source_type": "aras",
        "report_type": "ewo",
        "project_status_deliverable_id": "VPI-T2-D3",
    },
    "aras_paa": {
        "source_type": "aras",
        "report_type": "paa",
        "project_status_deliverable_id": None,
    },
    "aras_ncr_progress": {
        "source_type": "aras",
        "report_type": "ncr_progress",
        "project_status_deliverable_id": None,
    },
    "aras_ncr_detail": {
        "source_type": "aras",
        "report_type": "ncr_detail",
        "project_status_deliverable_id": None,
    },
    "tdc_data_model": {
        "source_type": "tdc",
        "report_type": "data_model",
        "project_status_deliverable_id": "VPI-T2-D5",
    },
    "tdc_sor": {
        "source_type": "tdc",
        "report_type": "sor",
        "project_status_deliverable_id": "VPI-T2-D2",
    },
}


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    """返回已初始化的隔离 SQLite DatabaseManager。"""
    manager = DatabaseManager(db_path=tmp_path / "archive_test.db")
    manager.init_database()
    return manager


def _enable_archive_job(
    db: DatabaseManager,
    job_key: str = "aras_ewo",
    credential_ref: str = "fake_cred_alias",
) -> int:
    """启用指定归档任务并绑定假凭据别名，返回 job_id。"""
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET enabled = 1, credential_ref = ? WHERE job_key = ?",
            (credential_ref, job_key),
        )
        row = conn.execute(
            "SELECT id FROM scheduled_archive_jobs WHERE job_key = ?",
            (job_key,),
        ).fetchone()
    assert row is not None
    return int(row["id"])


def test_archive_schema_version_and_tables(db: DatabaseManager) -> None:
    """断言版本为 2 且三张 scheduled_archive 表与索引已建立。"""
    assert CURRENT_SCHEMA_VERSION == 2

    with db.get_connection() as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 2, f"PRAGMA user_version 应为 2，实际为 {user_version}"

    expected_tables = {
        "scheduled_archive_jobs",
        "scheduled_archive_runs",
        "scheduled_archive_artifacts",
    }
    for table_name in expected_tables:
        assert db.table_exists(table_name), f"表 {table_name} 不存在"

    with db.get_connection() as conn:
        job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(scheduled_archive_jobs)")}
        assert {
            "id",
            "job_key",
            "source_type",
            "report_type",
            "project_status_deliverable_id",
            "enabled",
            "credential_ref",
            "interval_minutes",
            "filters_json",
            "output_subdir",
            "retry_policy_json",
            "sync_state",
            "last_attempt_at",
            "last_success_at",
            "last_error_type",
            "last_error_message",
            "lease_token",
            "lease_acquired_at",
            "lease_expires_at",
            "created_at",
            "updated_at",
        }.issubset(job_cols)

        run_cols = {row["name"] for row in conn.execute("PRAGMA table_info(scheduled_archive_runs)")}
        assert {
            "id",
            "job_id",
            "job_key",
            "trigger_type",
            "run_state",
            "attempt",
            "record_count",
            "result_summary",
            "error_type",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
        }.issubset(run_cols)

        artifact_cols = {row["name"] for row in conn.execute("PRAGMA table_info(scheduled_archive_artifacts)")}
        assert {
            "id",
            "run_id",
            "artifact_type",
            "relative_path",
            "display_name",
            "size_bytes",
            "sha256",
            "created_at",
        }.issubset(artifact_cols)


def test_fixed_six_archive_jobs_seeded(db: DatabaseManager) -> None:
    """断言初始化后存在且仅存在 6 个固定 key，默认禁用、60 分钟间隔、max_attempts=2。"""
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, job_key, source_type, report_type, "
            "       project_status_deliverable_id, enabled, interval_minutes, "
            "       retry_policy_json, sync_state, output_subdir, filters_json "
            "FROM scheduled_archive_jobs ORDER BY id"
        ).fetchall()

    assert len(rows) == 6, f"应存在且仅存在 6 个预置归档任务种子，实际存在 {len(rows)} 个"

    keys_found = [row["job_key"] for row in rows]
    assert set(keys_found) == set(EXPECTED_SEEDS.keys()), f"种子 key 集合不匹配: {keys_found}"
    assert len(keys_found) == len(set(keys_found)), "种子 key 存在重复"

    for row in rows:
        key = str(row["job_key"])
        expected = EXPECTED_SEEDS[key]

        assert row["source_type"] == expected["source_type"]
        assert row["report_type"] == expected["report_type"]
        assert row["project_status_deliverable_id"] == expected["project_status_deliverable_id"]
        assert row["enabled"] == 0, f"种子 {key} enabled 默认值应为 0 (禁用)"
        assert row["interval_minutes"] == 60, f"种子 {key} interval_minutes 默认值应为 60"
        assert row["sync_state"] == "idle", f"种子 {key} sync_state 初始值应为 idle"
        assert row["output_subdir"] == "", f"种子 {key} output_subdir 默认值应为空字符串"
        assert row["filters_json"] == "{}", f"种子 {key} filters_json 默认值应为 {{}}"

        policy = json.loads(row["retry_policy_json"])
        assert policy.get("max_attempts") == 2, f"种子 {key} retry_policy max_attempts 应为 2"


def test_deliverable_links_and_no_a_face_seed(db: DatabaseManager) -> None:
    """断言 D2/D3/D5 仅绑定 SOR/EWO/data-model，PAA/NCR 链接为 null，且绝不包含 A 面任务。"""
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT job_key, source_type, report_type, project_status_deliverable_id "
            "FROM scheduled_archive_jobs"
        ).fetchall()

    mapping = {row["job_key"]: row["project_status_deliverable_id"] for row in rows}

    assert mapping["aras_ewo"] == "VPI-T2-D3", "aras_ewo 必须关联 VPI-T2-D3"
    assert mapping["tdc_sor"] == "VPI-T2-D2", "tdc_sor 必须关联 VPI-T2-D2"
    assert mapping["tdc_data_model"] == "VPI-T2-D5", "tdc_data_model 必须关联 VPI-T2-D5"

    assert mapping["aras_paa"] is None, "aras_paa 关联必须为 None"
    assert mapping["aras_ncr_progress"] is None, "aras_ncr_progress 关联必须为 None"
    assert mapping["aras_ncr_detail"] is None, "aras_ncr_detail 关联必须为 None"

    all_keys = [str(r["job_key"]).lower() for r in rows]
    all_reports = [str(r["report_type"]).lower() for r in rows]
    all_deliverables = [r["project_status_deliverable_id"] for r in rows]

    for key in all_keys:
        assert "a_face" not in key and "a-face" not in key and "aface" not in key, (
            f"严禁预置 TDC A 面任务: {key}"
        )
    for rep in all_reports:
        assert "a_face" not in rep and "a-face" not in rep, (
            f"严禁预置 A 面 report_type: {rep}"
        )
    assert "VPI-T2-D4" not in all_deliverables, "严禁预置关联 VPI-T2-D4 (造型 VDR 审批 / A 面)"


def test_repeated_initialization_preserves_custom_settings(tmp_path: Path) -> None:
    """断言多次调用 init_database() 保持已修改的 enabled/interval_minutes/filters 等配置不被覆盖。"""
    db_file = tmp_path / "preserve.db"
    db = DatabaseManager(db_path=db_file)
    db.init_database()

    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE scheduled_archive_jobs
            SET enabled = 1,
                interval_minutes = 30,
                filters_json = '{"project":"EP35"}',
                output_subdir = 'custom_ewo_dir',
                sync_state = 'success',
                last_success_at = '2026-08-20T12:00:00.000Z'
            WHERE job_key = 'aras_ewo'
            """
        )
        conn.execute(
            """
            UPDATE scheduled_archive_jobs
            SET enabled = 1,
                interval_minutes = 15
            WHERE job_key = 'tdc_sor'
            """
        )

    # 模拟应用重启或第二次 init_database 调用
    db.init_database()

    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM scheduled_archive_jobs").fetchone()[0]
        assert count == 6, f"重复初始化后 job 总数应依然为 6，实际为 {count}"

        ewo = conn.execute(
            "SELECT enabled, interval_minutes, filters_json, output_subdir, sync_state, last_success_at "
            "FROM scheduled_archive_jobs WHERE job_key = 'aras_ewo'"
        ).fetchone()
        assert ewo["enabled"] == 1
        assert ewo["interval_minutes"] == 30
        assert ewo["filters_json"] == '{"project":"EP35"}'
        assert ewo["output_subdir"] == "custom_ewo_dir"
        assert ewo["sync_state"] == "success"
        assert ewo["last_success_at"] == "2026-08-20T12:00:00.000Z"

        sor = conn.execute(
            "SELECT enabled, interval_minutes FROM scheduled_archive_jobs WHERE job_key = 'tdc_sor'"
        ).fetchone()
        assert sor["enabled"] == 1
        assert sor["interval_minutes"] == 15

        # 未修改的 job 保持默认
        paa = conn.execute(
            "SELECT enabled, interval_minutes FROM scheduled_archive_jobs WHERE job_key = 'aras_paa'"
        ).fetchone()
        assert paa["enabled"] == 0
        assert paa["interval_minutes"] == 60


def test_offline_runs_foreign_key_and_delete_restriction(db: DatabaseManager) -> None:
    """断言 scheduled_archive_runs 对 scheduled_archive_jobs 的外键约束及 ON DELETE RESTRICT。"""
    with db.get_connection() as conn:
        job_row = conn.execute(
            "SELECT id, job_key FROM scheduled_archive_jobs WHERE job_key = 'aras_ewo'"
        ).fetchone()
        assert job_row is not None
        job_id = int(job_row["id"])
        job_key = str(job_row["job_key"])

        # 1. 尝试插入指向不存在 job_id 的 run -> 违反外键约束
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
                VALUES (999999, 'non_existent_key', 'scheduled', 'leased', 1)
                """
            )

        # 2. 插入合法的 run
        cursor = conn.execute(
            """
            INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
            VALUES (?, ?, 'sync_now', 'leased', 1)
            """,
            (job_id, job_key),
        )
        run_id = cursor.lastrowid
        assert run_id is not None

        # 3. 尝试删除有 run 关联的 job -> ON DELETE RESTRICT 抛出 IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM scheduled_archive_jobs WHERE id = ?", (job_id,))


def test_offline_artifacts_foreign_key_and_cascade_delete(db: DatabaseManager) -> None:
    """断言 scheduled_archive_artifacts 对 scheduled_archive_runs 的外键约束及 ON DELETE CASCADE。"""
    with db.get_connection() as conn:
        job = conn.execute(
            "SELECT id, job_key FROM scheduled_archive_jobs WHERE job_key = 'aras_ewo'"
        ).fetchone()
        job_id = int(job["id"])
        job_key = str(job["job_key"])

        # 1. 尝试插入指向不存在 run_id 的 artifact -> 违反外键约束
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_artifacts
                    (run_id, artifact_type, relative_path, display_name, size_bytes, sha256)
                VALUES (888888, 'normalized_csv', 'aras/ewo/20260822_000000.csv', 'EWO Dump', 1024, 'abc')
                """
            )

        # 2. 插入合法 run 与 artifact
        cursor = conn.execute(
            """
            INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
            VALUES (?, ?, 'scheduled', 'success', 1)
            """,
            (job_id, job_key),
        )
        run_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO scheduled_archive_artifacts
                (run_id, artifact_type, relative_path, display_name, size_bytes, sha256)
            VALUES (?, 'normalized_csv', 'aras/ewo/20260822_000000.csv', 'EWO Dump', 1024, 'abc')
            """,
            (run_id,),
        )
        conn.execute(
            """
            INSERT INTO scheduled_archive_artifacts
                (run_id, artifact_type, relative_path, display_name, size_bytes, sha256)
            VALUES (?, 'normalized_json', 'aras/ewo/20260822_000000.json', 'EWO Meta', 512, 'def')
            """,
            (run_id,),
        )

        artifact_count = conn.execute(
            "SELECT COUNT(*) FROM scheduled_archive_artifacts WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        assert artifact_count == 2

        # 3. 删除 run -> 级联删除其 artifacts (ON DELETE CASCADE)
        conn.execute("DELETE FROM scheduled_archive_runs WHERE id = ?", (run_id,))

        remaining_artifacts = conn.execute(
            "SELECT COUNT(*) FROM scheduled_archive_artifacts WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        assert remaining_artifacts == 0, "run 删除后其 artifacts 应该被级联删除"


def test_duplicate_run_relative_path_rejected(db: DatabaseManager) -> None:
    """断言同一 run_id 下重复 relative_path 触发 UNIQUE (run_id, relative_path) 约束冲突。"""
    with db.get_connection() as conn:
        job = conn.execute(
            "SELECT id, job_key FROM scheduled_archive_jobs WHERE job_key = 'tdc_sor'"
        ).fetchone()
        job_id = int(job["id"])
        job_key = str(job["job_key"])

        cursor = conn.execute(
            """
            INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
            VALUES (?, ?, 'sync_now', 'running', 1)
            """,
            (job_id, job_key),
        )
        run_id = cursor.lastrowid

        rel_path = "tdc/sor/20260822_010000_sor.xlsx"
        conn.execute(
            """
            INSERT INTO scheduled_archive_artifacts
                (run_id, artifact_type, relative_path, display_name, size_bytes, sha256)
            VALUES (?, 'official_xlsx', ?, 'SOR Excel', 2048, 'hash1')
            """,
            (run_id, rel_path),
        )

        # 插入相同 (run_id, relative_path) 应被拒绝
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_artifacts
                    (run_id, artifact_type, relative_path, display_name, size_bytes, sha256)
                VALUES (?, 'official_xlsx', ?, 'Duplicate SOR Excel', 4096, 'hash2')
                """,
                (run_id, rel_path),
            )

        # 不同的 run_id 可以使用相同的 relative_path
        cursor2 = conn.execute(
            """
            INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
            VALUES (?, ?, 'scheduled', 'running', 1)
            """,
            (job_id, job_key),
        )
        run_id2 = cursor2.lastrowid
        conn.execute(
            """
            INSERT INTO scheduled_archive_artifacts
                (run_id, artifact_type, relative_path, display_name, size_bytes, sha256)
            VALUES (?, 'official_xlsx', ?, 'SOR Excel Run2', 2048, 'hash1')
            """,
            (run_id2, rel_path),
        )


def test_archive_jobs_unique_and_check_constraints(db: DatabaseManager) -> None:
    """断言 scheduled_archive_jobs 的唯一约束 (job_key, (source_type, report_type)) 与 CHECK 约束。"""
    with db.get_connection() as conn:
        # 1. 唯一约束: 重复 job_key
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_jobs
                    (job_key, source_type, report_type, enabled, interval_minutes)
                VALUES ('aras_ewo', 'aras', 'custom_ewo', 0, 60)
                """
            )

        # 2. 唯一约束: 重复 (source_type, report_type)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_jobs
                    (job_key, source_type, report_type, enabled, interval_minutes)
                VALUES ('new_ewo_key', 'aras', 'ewo', 0, 60)
                """
            )

        # 3. CHECK 约束: source_type IN ('aras', 'tdc')
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_jobs
                    (job_key, source_type, report_type, enabled, interval_minutes)
                VALUES ('invalid_source', 'feishu', 'doc', 0, 60)
                """
            )

        # 4. CHECK 约束: enabled IN (0, 1)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_jobs
                    (job_key, source_type, report_type, enabled, interval_minutes)
                VALUES ('invalid_enabled', 'aras', 'other', 2, 60)
                """
            )

        # 5. CHECK 约束: interval_minutes > 0
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_jobs
                    (job_key, source_type, report_type, enabled, interval_minutes)
                VALUES ('invalid_interval', 'aras', 'other', 0, 0)
                """
            )

        # 6. CHECK 约束: sync_state
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_jobs
                    (job_key, source_type, report_type, sync_state)
                VALUES ('invalid_state', 'aras', 'other', 'unknown_state')
                """
            )


def test_archive_runs_check_constraints(db: DatabaseManager) -> None:
    """断言 scheduled_archive_runs 的 CHECK 约束 (trigger_type, run_state, attempt)。"""
    with db.get_connection() as conn:
        job = conn.execute(
            "SELECT id, job_key FROM scheduled_archive_jobs LIMIT 1"
        ).fetchone()
        job_id = int(job["id"])
        job_key = str(job["job_key"])

        # trigger_type 校验
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
                VALUES (?, ?, 'manual_trigger', 'running', 1)
                """,
                (job_id, job_key),
            )

        # run_state 校验
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
                VALUES (?, ?, 'sync_now', 'invalid_state', 1)
                """,
                (job_id, job_key),
            )

        # attempt 校验 (BETWEEN 1 AND 2)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
                VALUES (?, ?, 'sync_now', 'running', 0)
                """,
                (job_id, job_key),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_archive_runs (job_id, job_key, trigger_type, run_state, attempt)
                VALUES (?, ?, 'sync_now', 'running', 3)
                """,
                (job_id, job_key),
            )


# ── 归档任务租约生命周期与负向边界测试 ──────────────────────────────────────


def test_list_archive_jobs_booleans_and_omits_secrets(db: DatabaseManager) -> None:
    """断言 list_archive_jobs 返回布尔类型 enabled / credential_configured，且绝不暴露 credential_ref 或 lease_token。"""
    # 1. 默认初始状态 (全部 disabled, 无 credential_ref)
    all_jobs = db.list_archive_jobs(enabled_only=False)
    assert len(all_jobs) == 6

    for job in all_jobs:
        assert isinstance(job["enabled"], bool)
        assert isinstance(job["credential_configured"], bool)
        assert job["enabled"] is False
        assert job["credential_configured"] is False
        assert "credential_ref" not in job, "list_archive_jobs 严禁泄露 credential_ref"
        assert "lease_token" not in job, "list_archive_jobs 严禁泄露 lease_token"

    # 2. 仅启用特定任务并配置假凭据
    _enable_archive_job(db, "aras_ewo", credential_ref="alias_ewo_fake")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET enabled = 1, credential_ref = '' WHERE job_key = 'tdc_sor'"
        )

    # 3. enabled_only=True 过滤验证
    enabled_jobs = db.list_archive_jobs(enabled_only=True)
    assert len(enabled_jobs) == 2
    by_key = {job["job_key"]: job for job in enabled_jobs}

    assert by_key["aras_ewo"]["enabled"] is True
    assert by_key["aras_ewo"]["credential_configured"] is True
    assert "credential_ref" not in by_key["aras_ewo"]
    assert "lease_token" not in by_key["aras_ewo"]

    assert by_key["tdc_sor"]["enabled"] is True
    assert by_key["tdc_sor"]["credential_configured"] is False
    assert "credential_ref" not in by_key["tdc_sor"]
    assert "lease_token" not in by_key["tdc_sor"]


def test_acquire_rejects_disabled_and_missing_alias_before_mutations(db: DatabaseManager) -> None:
    """断言未启用、缺失凭据别名或不存在 job 时在前置检查阶段拒绝，不产生 lease/run/last_attempt 变更。"""
    with db.get_connection() as conn:
        job = conn.execute("SELECT id FROM scheduled_archive_jobs WHERE job_key = 'aras_ewo'").fetchone()
    assert job is not None
    job_id = int(job["id"])

    # 1. 禁用状态 (enabled=0, credential_ref=NULL)
    with pytest.raises(ArchiveJobNotReadyError, match="not enabled"):
        db.acquire_archive_job_lease(job_id, "sync_now")

    with pytest.raises(ArchiveJobNotReadyError, match="not configured"):
        db.get_archive_job_credential_ref(job_id)

    # 验证未发生任何变更
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT lease_token, lease_acquired_at, lease_expires_at, last_attempt_at, sync_state "
            "FROM scheduled_archive_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row["lease_token"] is None
        assert row["lease_acquired_at"] is None
        assert row["lease_expires_at"] is None
        assert row["last_attempt_at"] is None
        assert row["sync_state"] == "idle"

        run_count = conn.execute("SELECT COUNT(*) FROM scheduled_archive_runs WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert run_count == 0

    # 2. 启用状态但缺失凭据 (enabled=1, credential_ref='')
    with db.get_connection() as conn:
        conn.execute("UPDATE scheduled_archive_jobs SET enabled = 1, credential_ref = '' WHERE id = ?", (job_id,))

    with pytest.raises(ArchiveJobNotReadyError, match="not configured"):
        db.acquire_archive_job_lease(job_id, "scheduled")

    with pytest.raises(ArchiveJobNotReadyError, match="not configured"):
        db.get_archive_job_credential_ref(job_id)

    # 再次验证未发生状态或 run 突变
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT lease_token, lease_acquired_at, lease_expires_at, last_attempt_at, sync_state "
            "FROM scheduled_archive_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row["lease_token"] is None
        assert row["lease_acquired_at"] is None
        assert row["lease_expires_at"] is None
        assert row["last_attempt_at"] is None
        assert row["sync_state"] == "idle"

        run_count = conn.execute("SELECT COUNT(*) FROM scheduled_archive_runs WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert run_count == 0

    # 3. 不存在的 job_id
    with pytest.raises(KeyError):
        db.acquire_archive_job_lease(999999, "sync_now")
    with pytest.raises(KeyError):
        db.get_archive_job_credential_ref(999999)

    # 4. 非法入参拒绝 (trigger_type, lease_seconds)
    _enable_archive_job(db, "aras_ewo", credential_ref="fake_alias")
    with pytest.raises(ValueError, match="unsupported trigger_type"):
        db.acquire_archive_job_lease(job_id, "invalid_trigger")
    with pytest.raises(ValueError, match="lease_seconds must be between"):
        db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=10)
    with pytest.raises(TypeError, match="lease_seconds must be an int"):
        db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds="900")  # type: ignore[arg-type]


def test_concurrent_lease_acquire_only_one_winner_and_no_second_run(db: DatabaseManager) -> None:
    """断言并发或连续获取租约时仅有一方成功，未获取方报错且绝不产生第二个 run。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="alias_concurrent")

    # 1. 顺序重入拒绝
    lease1 = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=600)
    assert lease1["job_id"] == job_id
    assert lease1["run_id"] > 0
    assert lease1["lease_token"]

    with pytest.raises(ArchiveLeaseBusyError, match="already has an unexpired lease"):
        db.acquire_archive_job_lease(job_id, "scheduled", lease_seconds=600)

    with db.get_connection() as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM scheduled_archive_runs WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert run_count == 1

    # 2. 多线程并发竞争同一 job
    job_id_2 = _enable_archive_job(db, "tdc_sor", credential_ref="alias_sor_concurrent")

    results: list[dict[str, Any]] = []
    errors: list[Exception] = []

    def _try_acquire() -> None:
        try:
            res = db.acquire_archive_job_lease(job_id_2, "scheduled", lease_seconds=300)
            results.append(res)
        except Exception as exc:
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_try_acquire) for _ in range(8)]
        concurrent.futures.wait(futures)

    assert len(results) == 1, f"并发获取租约必须仅有 1 个胜出者，实际为 {len(results)}"
    assert len(errors) == 7
    for err in errors:
        assert isinstance(err, ArchiveLeaseBusyError)

    with db.get_connection() as conn:
        run_count_2 = conn.execute(
            "SELECT COUNT(*) FROM scheduled_archive_runs WHERE job_id = ?",
            (job_id_2,),
        ).fetchone()[0]
        assert run_count_2 == 1, "并发竞争失败方不得插入 run 记录"


def test_start_and_finalize_token_mismatch_and_expired_lease_rejection(db: DatabaseManager) -> None:
    """断言 start/finalize 阶段的 token 不匹配、run 不匹配及过期租约均被拒绝，且过期租约可被安全抢占。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="alias_mismatch")
    lease = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=300)
    run_id = lease["run_id"]
    valid_token = lease["lease_token"]

    artifact = {
        "artifact_type": "normalized_csv",
        "relative_path": "aras/ewo/20260822_001.csv",
        "display_name": "EWO Export CSV",
        "size_bytes": 1024,
        "sha256": "abcdef123456",
    }

    # 1. start_archive_run token / run 校验
    with pytest.raises(ArchiveLeaseLostError):
        db.start_archive_run(job_id, run_id, "invalid_fake_token")
    with pytest.raises(ArchiveLeaseLostError):
        db.start_archive_run(job_id, 999999, valid_token)

    # 2. finalize_archive_run token / run 校验
    with pytest.raises(ArchiveLeaseLostError):
        db.finalize_archive_run(
            job_id, run_id, "invalid_fake_token", "success", artifacts=[artifact]
        )
    with pytest.raises(ArchiveLeaseLostError):
        db.finalize_archive_run(
            job_id, 999999, valid_token, "success", artifacts=[artifact]
        )

    # 3. 模拟租约过期
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET lease_expires_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
            (job_id,),
        )

    # 过期后无法 start 或 finalize
    with pytest.raises(ArchiveLeaseLostError):
        db.start_archive_run(job_id, run_id, valid_token)
    with pytest.raises(ArchiveLeaseLostError):
        db.finalize_archive_run(
            job_id, run_id, valid_token, "success", artifacts=[artifact]
        )

    # 4. 过期租约抢占 (Preemption)
    new_lease = db.acquire_archive_job_lease(job_id, "scheduled", lease_seconds=600)
    assert new_lease["run_id"] != run_id
    assert new_lease["lease_token"] != valid_token

    # 验证旧 run 已被标记为 expired
    with db.get_connection() as conn:
        old_run = conn.execute(
            "SELECT run_state, finished_at FROM scheduled_archive_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert old_run["run_state"] == "expired"
        assert old_run["finished_at"] is not None


def test_finalize_success_inserts_artifacts_clears_lease_and_sets_last_success(db: DatabaseManager) -> None:
    """断言 success 终态正常插入 artifacts、清理租约字段并更新 last_success_at。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="alias_success")
    lease = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=300)
    run_id = lease["run_id"]
    token = lease["lease_token"]

    db.start_archive_run(job_id, run_id, token)

    artifacts = [
        {
            "artifact_type": "normalized_csv",
            "relative_path": "aras/ewo/20260822_success.csv",
            "display_name": "EWO CSV",
            "size_bytes": 2048,
            "sha256": "sha256_csv_hash",
        },
        {
            "artifact_type": "summary_json",
            "relative_path": "aras/ewo/20260822_success.json",
            "display_name": "EWO Metadata JSON",
            "size_bytes": 512,
            "sha256": "sha256_json_hash",
        },
    ]

    db.finalize_archive_run(
        job_id,
        run_id,
        token,
        "success",
        record_count=100,
        artifacts=artifacts,
        result_summary="100 EWO records exported",
    )

    # 验证 job 表状态
    with db.get_connection() as conn:
        job = conn.execute(
            "SELECT sync_state, lease_token, lease_acquired_at, lease_expires_at, "
            "       last_success_at, last_error_type, last_error_message "
            "FROM scheduled_archive_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert job["sync_state"] == "success"
        assert job["lease_token"] is None
        assert job["lease_acquired_at"] is None
        assert job["lease_expires_at"] is None
        assert job["last_success_at"] is not None
        assert job["last_error_type"] is None
        assert job["last_error_message"] is None

        # 验证 run 表状态
        run = conn.execute(
            "SELECT run_state, record_count, result_summary, finished_at "
            "FROM scheduled_archive_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["run_state"] == "success"
        assert run["record_count"] == 100
        assert run["result_summary"] == "100 EWO records exported"
        assert run["finished_at"] is not None

        # 验证 artifacts 插入
        rows = conn.execute(
            "SELECT artifact_type, relative_path, display_name, size_bytes, sha256 "
            "FROM scheduled_archive_artifacts WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["relative_path"] == "aras/ewo/20260822_success.csv"
        assert rows[0]["size_bytes"] == 2048
        assert rows[1]["relative_path"] == "aras/ewo/20260822_success.json"
        assert rows[1]["size_bytes"] == 512


def test_finalize_failure_and_needs_attention_preserves_last_success_and_redacts(db: DatabaseManager) -> None:
    """断言 failed 与 needs_attention 终态保留原有 last_success_at，清空租约，并脱敏截断错误信息。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="alias_fail")
    old_success_time = "2026-08-18T10:00:00.000Z"

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET last_success_at = ? WHERE id = ?",
            (old_success_time, job_id),
        )

    # 1. 测试 failed
    lease1 = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=300)
    run_id1 = lease1["run_id"]
    token1 = lease1["lease_token"]

    db.start_archive_run(job_id, run_id1, token1)

    sensitive_error = "Connect failed: password=supersecretpass token Bearer sensitive_bearer_1234567890"
    db.finalize_archive_run(
        job_id,
        run_id1,
        token1,
        "failed",
        error_type="AuthenticationError",
        error_message=sensitive_error,
        result_summary="Auth failed with password=supersecretpass",
    )

    with db.get_connection() as conn:
        job = conn.execute(
            "SELECT sync_state, lease_token, lease_expires_at, last_success_at, "
            "       last_error_type, last_error_message "
            "FROM scheduled_archive_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert job["sync_state"] == "failed"
        assert job["lease_token"] is None
        assert job["lease_expires_at"] is None
        assert job["last_success_at"] == old_success_time, "failed 终态必须保留历史 last_success_at"
        assert "supersecretpass" not in str(job["last_error_message"])
        assert "sensitive_bearer_1234567890" not in str(job["last_error_message"])

        run = conn.execute(
            "SELECT run_state, error_type, error_message, result_summary "
            "FROM scheduled_archive_runs WHERE id = ?",
            (run_id1,),
        ).fetchone()
        assert run["run_state"] == "failed"
        assert "supersecretpass" not in str(run["error_message"])
        assert "supersecretpass" not in str(run["result_summary"])

    # 2. 测试 needs_attention
    lease2 = db.acquire_archive_job_lease(job_id, "scheduled", lease_seconds=300)
    run_id2 = lease2["run_id"]
    token2 = lease2["lease_token"]

    db.finalize_archive_run(
        job_id,
        run_id2,
        token2,
        "needs_attention",
        error_type="SchemaMismatch",
        error_message="Missing required field token=abc1234567",
    )

    with db.get_connection() as conn:
        job2 = conn.execute(
            "SELECT sync_state, lease_token, last_success_at, last_error_type "
            "FROM scheduled_archive_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert job2["sync_state"] == "needs_attention"
        assert job2["lease_token"] is None
        assert job2["last_success_at"] == old_success_time, "needs_attention 终态必须保留历史 last_success_at"


def test_finalize_partial_maps_job_sync_state_to_needs_attention(db: DatabaseManager) -> None:
    """断言 partial 终态在 run 表记录 partial，但将 job 的 sync_state 映射为 needs_attention。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="alias_partial")
    old_success = "2026-08-15T00:00:00.000Z"
    with db.get_connection() as conn:
        conn.execute("UPDATE scheduled_archive_jobs SET last_success_at = ? WHERE id = ?", (old_success, job_id))

    lease = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=300)
    run_id = lease["run_id"]
    token = lease["lease_token"]

    db.start_archive_run(job_id, run_id, token)

    artifact = {
        "artifact_type": "partial_csv",
        "relative_path": "aras/ewo/20260822_partial.csv",
        "display_name": "EWO Partial CSV",
        "size_bytes": 100,
        "sha256": "partial_sha256",
    }

    db.finalize_archive_run(
        job_id,
        run_id,
        token,
        "partial",
        record_count=50,
        artifacts=[artifact],
        result_summary="Partial export 50/100 rows",
    )

    with db.get_connection() as conn:
        job = conn.execute(
            "SELECT sync_state, lease_token, last_success_at "
            "FROM scheduled_archive_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        # 验收要求: partial 终态映射 job sync_state 为 needs_attention
        assert job["sync_state"] == "needs_attention"
        assert job["lease_token"] is None
        assert job["last_success_at"] == old_success, "partial 不更新 last_success_at"

        run = conn.execute(
            "SELECT run_state, record_count, result_summary "
            "FROM scheduled_archive_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["run_state"] == "partial"
        assert run["record_count"] == 50


def test_artifact_safety_rejections_and_success_without_artifacts(db: DatabaseManager) -> None:
    """断言目录穿越、绝对路径、空段、Windows 设备名、尾随点空格、重复路径及无 artifact 成功均被拒绝。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="alias_safety")
    lease = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=300)
    run_id = lease["run_id"]
    token = lease["lease_token"]

    # 1. 成功必须附带 artifacts
    with pytest.raises(ValueError, match="successful archive run requires artifacts"):
        db.finalize_archive_run(job_id, run_id, token, "success", artifacts=[])

    # 2. 非法 final_state
    with pytest.raises(ValueError, match="invalid archive final state"):
        db.finalize_archive_run(job_id, run_id, token, "unknown_state")

    # 3. 非法 record_count
    with pytest.raises(ValueError, match="record_count must be a non-negative int"):
        db.finalize_archive_run(job_id, run_id, token, "failed", record_count=-5)
    with pytest.raises(ValueError, match="record_count must be a non-negative int"):
        db.finalize_archive_run(job_id, run_id, token, "failed", record_count=True)  # type: ignore[arg-type]

    # 4. artifact 路径安全性检验
    invalid_cases = [
        # (artifact_dict, 预期匹配关键词)
        ({"artifact_type": "csv", "display_name": "x"}, "relative_path is required"),
        ({"relative_path": "", "artifact_type": "csv", "display_name": "x"}, "relative_path is required"),
        ({"relative_path": "../escape.csv", "artifact_type": "csv", "display_name": "x"}, "parent directories"),
        ({"relative_path": "foo/../../escape.csv", "artifact_type": "csv", "display_name": "x"}, "parent directories"),
        ({"relative_path": "/root/escape.csv", "artifact_type": "csv", "display_name": "x"}, "relative path"),
        ({"relative_path": "C:/Windows/calc.exe", "artifact_type": "csv", "display_name": "x"}, "relative path"),
        ({"relative_path": "D:\\data\\file.csv", "artifact_type": "csv", "display_name": "x"}, "relative path"),
        ({"relative_path": "foo//bar.csv", "artifact_type": "csv", "display_name": "x"}, "parent directories"),
        ({"relative_path": "foo/./bar.csv", "artifact_type": "csv", "display_name": "x"}, "parent directories"),
        ({"relative_path": "CON", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/PRN.txt", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/aux.csv", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/NUL", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "COM1.dat", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/LPT9.log", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/file.csv.", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder /file.csv", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/file.csv ", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "folder/file:name.csv", "artifact_type": "csv", "display_name": "x"}, "unsafe segment"),
        ({"relative_path": "valid.csv", "artifact_type": "", "display_name": "x"}, "artifact_type is required"),
        ({"relative_path": "valid.csv", "artifact_type": "csv", "display_name": "   "}, "display_name is required"),
        ({"relative_path": "valid.csv", "artifact_type": "csv", "display_name": "x", "size_bytes": -1}, "size_bytes must be a non-negative int"),
        ({"relative_path": "valid.csv", "artifact_type": "csv", "display_name": "x", "size_bytes": True}, "size_bytes must be a non-negative int"),
        ({"relative_path": "valid.csv", "artifact_type": "csv", "display_name": "x", "sha256": "  "}, "sha256 must be a non-empty string"),
    ]

    for art, match_str in invalid_cases:
        with pytest.raises(ValueError, match=match_str):
            db.finalize_archive_run(job_id, run_id, token, "failed", artifacts=[art])

    # 5. 单次调用中包含相同 relative_path 的重复 artifact 导致 DB 唯一约束失败
    duplicate_artifacts = [
        {
            "artifact_type": "csv",
            "relative_path": "aras/ewo/dup.csv",
            "display_name": "EWO 1",
            "size_bytes": 100,
            "sha256": "hash1",
        },
        {
            "artifact_type": "csv",
            "relative_path": "aras/ewo/dup.csv",
            "display_name": "EWO 2",
            "size_bytes": 200,
            "sha256": "hash2",
        },
    ]
    with pytest.raises(sqlite3.IntegrityError):
        db.finalize_archive_run(
            job_id, run_id, token, "failed", artifacts=duplicate_artifacts
        )


def test_run_and_artifact_list_methods_omit_secrets_and_absolute_paths(db: DatabaseManager) -> None:
    """断言 list_archive_runs 与 list_archive_artifacts 严格省略凭据、token 与绝对路径数据。"""
    job_id = _enable_archive_job(db, "aras_ewo", credential_ref="secret_credential_alias_123")
    lease = db.acquire_archive_job_lease(job_id, "sync_now", lease_seconds=300)
    run_id = lease["run_id"]
    token = lease["lease_token"]

    db.start_archive_run(job_id, run_id, token)

    artifact = {
        "artifact_type": "normalized_csv",
        "relative_path": "aras/ewo/20260822_clean.csv",
        "display_name": "Clean EWO",
        "size_bytes": 1024,
        "sha256": "clean_sha256",
    }
    db.finalize_archive_run(
        job_id, run_id, token, "success", record_count=10, artifacts=[artifact], result_summary="Done"
    )

    # 1. list_archive_runs
    runs = db.list_archive_runs(job_key="aras_ewo", limit=10)
    assert len(runs) >= 1
    for r in runs:
        assert "lease_token" not in r
        assert "credential_ref" not in r
        assert "absolute_path" not in r
        assert "full_path" not in r
        assert set(r.keys()) == {
            "id",
            "job_id",
            "job_key",
            "trigger_type",
            "run_state",
            "attempt",
            "record_count",
            "result_summary",
            "error_type",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
        }

    # 2. list_archive_runs limit 边界测试
    bounded_runs = db.list_archive_runs(limit=0)
    assert len(bounded_runs) == 1

    # 3. list_archive_artifacts
    artifacts = db.list_archive_artifacts(run_id)
    assert len(artifacts) == 1
    art_item = artifacts[0]
    assert set(art_item.keys()) == {
        "id",
        "run_id",
        "artifact_type",
        "relative_path",
        "display_name",
        "size_bytes",
        "sha256",
        "created_at",
    }
    assert art_item["relative_path"] == "aras/ewo/20260822_clean.csv"
    assert not art_item["relative_path"].startswith("/")
    assert ":" not in art_item["relative_path"]
    assert "lease_token" not in art_item
    assert "credential_ref" not in art_item
    assert "absolute_path" not in art_item
    assert "full_path" not in art_item
