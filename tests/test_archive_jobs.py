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

import json
import sqlite3
from pathlib import Path

import pytest

from core.db_manager import CURRENT_SCHEMA_VERSION, DatabaseManager

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
