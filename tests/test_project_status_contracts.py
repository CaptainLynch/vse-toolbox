# -*- coding: utf-8 -*-
"""Focused tests for project status presentation contracts and database migrations."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from core.db_manager import CURRENT_SCHEMA_VERSION, DatabaseManager
from core.project_status_contracts import (
    DELIVERABLE_DEFAULT_MAPPINGS,
    DELIVERABLE_FIELD_ALIASES,
    PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
    PROJECT_STATUS_MAPPED_READ_ONLY_REASON,
    current_stage_label,
    get_deliverable_default_mapping,
    get_deliverable_field_aliases,
    milestone_display_status,
    project_status_default_policy_mode,
    project_status_manual_editability,
    project_status_source_capabilities,
)


# ── 1. Milestone Display Status Contracts ──────────────────────────────────────


def test_milestone_display_status_completed_override() -> None:
    """'已完成' / 'done' / '已达成' status always overrides date checks and never marks overdue."""
    today = date(2026, 8, 23)
    past_date = "2026-05-01"
    future_date = "2026-12-01"

    # Done in the past -> must remain '已完成', not '已超期'
    assert milestone_display_status("done", past_date, today) == "已完成"
    assert milestone_display_status("已达成", past_date, today) == "已完成"
    assert milestone_display_status("已完成", past_date, today) == "已完成"

    # Done in the future -> '已完成'
    assert milestone_display_status("done", future_date, today) == "已完成"
    assert milestone_display_status("已达成", future_date, today) == "已完成"
    assert milestone_display_status("已完成", future_date, today) == "已完成"

    # Invalid date with done status -> '已完成'
    assert milestone_display_status("done", "invalid-date", today) == "已完成"
    assert milestone_display_status("已达成", "not-iso", today) == "已完成"


def test_milestone_display_status_automatic_overdue() -> None:
    """Non-completed milestones with planned date earlier than today are marked '已超期'."""
    today = date(2026, 8, 23)
    past_date = "2026-08-01"

    assert milestone_display_status("planned", past_date, today) == "已超期"
    assert milestone_display_status("current", past_date, today) == "已超期"
    assert milestone_display_status("计划节点", past_date, today) == "已超期"
    assert milestone_display_status("当前目标节点", past_date, today) == "已超期"
    assert milestone_display_status("未开始", past_date, today) == "已超期"
    assert milestone_display_status("进行中", past_date, today) == "已超期"


def test_milestone_display_status_future_and_today() -> None:
    """Non-completed milestones on or after today preserve their normalized status."""
    today = date(2026, 8, 23)
    future_date = "2026-09-01"
    same_day = "2026-08-23"

    # Future dates
    assert milestone_display_status("planned", future_date, today) == "未开始"
    assert milestone_display_status("current", future_date, today) == "进行中"
    assert milestone_display_status("计划节点", future_date, today) == "未开始"
    assert milestone_display_status("当前目标节点", future_date, today) == "进行中"
    assert milestone_display_status("未开始", future_date, today) == "未开始"
    assert milestone_display_status("进行中", future_date, today) == "进行中"

    # Same day (milestone_date == today) is NOT overdue
    assert milestone_display_status("planned", same_day, today) == "未开始"
    assert milestone_display_status("current", same_day, today) == "进行中"


def test_milestone_display_status_invalid_date_fallback() -> None:
    """Invalid dates fall back safely to recognized status or '未开始'."""
    today = date(2026, 8, 23)

    assert milestone_display_status("planned", "invalid-date", today) == "未开始"
    assert milestone_display_status("current", "bad-date", today) == "进行中"
    assert milestone_display_status("进行中", None, today) == "进行中"
    assert milestone_display_status("custom_unrecognized", "bad-date", today) == "未开始"


# ── 2. Current Stage Label Contract ───────────────────────────────────────────


@pytest.fixture()
def sample_milestones() -> list[dict[str, object]]:
    return [
        {"name": "节点A-立项", "date": "2026-05-01"},
        {"name": "节点B-设计冻结", "date": "2026-06-15"},
        {"name": "节点C-样件试制", "date": "2026-07-20"},
        {"name": "节点D-量产交付", "date": "2026-09-30"},
    ]


def test_current_stage_label_empty() -> None:
    """Empty milestones return default '项目开始 → 项目结束'."""
    assert current_stage_label([], date(2026, 6, 1)) == "项目开始 → 项目结束"


def test_current_stage_label_skips_undated_nodes() -> None:
    """空日期（待排期）节点不参与阶段推算，也不得导致异常。"""
    milestones = [
        {"name": "VPI", "date": None},
        {"name": "节点A-立项", "date": "2026-05-01"},
        {"name": "内饰模型评审", "date": None},
        {"name": "节点B-设计冻结", "date": "2026-06-01"},
        {"name": "用户体验阀", "date": ""},
    ]
    assert current_stage_label(milestones, date(2026, 5, 20)) == "节点A-立项 → 节点B-设计冻结"
    assert current_stage_label(milestones, date(2026, 6, 15)) == "节点B-设计冻结 → 项目结束"


def test_current_stage_label_all_undated() -> None:
    """全部节点无日期时回退默认文案。"""
    milestones = [{"name": f"节点{i}", "date": None} for i in range(3)]
    assert current_stage_label(milestones, date(2026, 6, 1)) == "项目开始 → 项目结束"


def test_milestone_display_status_undated_is_not_overdue() -> None:
    """空日期节点不做逾期判定，按状态显示。"""
    today = date(2026, 9, 6)
    assert milestone_display_status("未开始", None, today) == "未开始"
    assert milestone_display_status("未开始", "", today) == "未开始"


def test_current_stage_label_before_first_node(sample_milestones: list[dict[str, object]]) -> None:
    """When today is before the earliest milestone, left side is '项目开始'."""
    today = date(2026, 4, 15)  # before 2026-05-01
    assert current_stage_label(sample_milestones, today) == "项目开始 → 节点A-立项"


def test_current_stage_label_exact_first_node(sample_milestones: list[dict[str, object]]) -> None:
    """When today matches the first milestone date exactly, left is first and right is second."""
    today = date(2026, 5, 1)  # exact date of 节点A-立项
    assert current_stage_label(sample_milestones, today) == "节点A-立项 → 节点B-设计冻结"


def test_current_stage_label_between_nodes(sample_milestones: list[dict[str, object]]) -> None:
    """When today is strictly between two milestones, returns current and next milestone names."""
    # Between node A and B
    today_ab = date(2026, 5, 20)
    assert current_stage_label(sample_milestones, today_ab) == "节点A-立项 → 节点B-设计冻结"

    # Between node B and C
    today_bc = date(2026, 7, 1)
    assert current_stage_label(sample_milestones, today_bc) == "节点B-设计冻结 → 节点C-样件试制"

    # Between node C and D
    today_cd = date(2026, 8, 15)
    assert current_stage_label(sample_milestones, today_cd) == "节点C-样件试制 → 节点D-量产交付"


def test_current_stage_label_exact_intermediate_node(sample_milestones: list[dict[str, object]]) -> None:
    """When today matches an intermediate milestone, left is that node and right is subsequent."""
    today = date(2026, 6, 15)  # exact date of 节点B-设计冻结
    assert current_stage_label(sample_milestones, today) == "节点B-设计冻结 → 节点C-样件试制"


def test_current_stage_label_exact_last_node(sample_milestones: list[dict[str, object]]) -> None:
    """When today matches the last milestone date, left is last node and right is '项目结束'."""
    today = date(2026, 9, 30)  # exact date of 节点D-量产交付
    assert current_stage_label(sample_milestones, today) == "节点D-量产交付 → 项目结束"


def test_current_stage_label_after_last_node(sample_milestones: list[dict[str, object]]) -> None:
    """When today is after the last milestone, left is last node and right is '项目结束'."""
    today = date(2026, 10, 15)  # after 2026-09-30
    assert current_stage_label(sample_milestones, today) == "节点D-量产交付 → 项目结束"


def test_current_stage_label_sorts_unordered_milestones() -> None:
    """Milestones provided out of order are sorted deterministically by (date, name)."""
    unordered = [
        {"name": "节点D-量产交付", "date": "2026-09-30"},
        {"name": "节点A-立项", "date": "2026-05-01"},
        {"name": "节点C-样件试制", "date": "2026-07-20"},
        {"name": "节点B-设计冻结", "date": "2026-06-15"},
    ]
    today = date(2026, 7, 20)
    assert current_stage_label(unordered, today) == "节点C-样件试制 → 节点D-量产交付"


# ── 3. Database Migration Contracts ────────────────────────────────────────────


def test_database_migration_node_status_and_display_codes(tmp_path: Path) -> None:
    """Database migration converts legacy node statuses and assigns deterministic DEL-001 display codes without changing internal IDs."""
    db_path = tmp_path / "migration_test.db"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA user_version = 2;")

    # Seed legacy VPI-T2 phase
    conn.execute(
        """
        CREATE TABLE project_status_phases (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            simulated_today TEXT NOT NULL,
            overall_progress INTEGER NOT NULL,
            planned_progress INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO project_status_phases
        VALUES ('VPI-T2', '进行中', '2026-04-08', '2026-08-30', '2026-08-13', 64, 80, '2026-08-13 09:42:00.000')
        """
    )

    # Legacy milestones with legacy statuses
    conn.execute(
        """
        CREATE TABLE project_status_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phase_id TEXT NOT NULL,
            name TEXT NOT NULL,
            milestone_date TEXT NOT NULL,
            status TEXT NOT NULL,
            type TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            UNIQUE (phase_id, name)
        );
        """
    )
    legacy_milestones = [
        ("VPI-T2", "项目启动", "2026-04-08", "done", "done", 1),
        ("VPI-T2", "策略冻结", "2026-05-12", "已达成", "done", 2),
        ("VPI-T2", "定点流程发布", "2026-06-18", "current", "current", 3),
        ("VPI-T2", "设计冻结", "2026-07-15", "当前目标节点", "current", 4),
        ("VPI-T2", "VDR 决策", "2026-08-15", "planned", "planned", 5),
        ("VPI-T2", "VPI-T2 Gate", "2026-08-30", "计划节点", "planned", 6),
    ]
    conn.executemany(
        "INSERT INTO project_status_milestones (phase_id, name, milestone_date, status, type, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
        legacy_milestones,
    )

    # Legacy deliverables WITHOUT display_code column
    conn.execute(
        """
        CREATE TABLE project_status_deliverables (
            id TEXT PRIMARY KEY,
            phase_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            owner TEXT NOT NULL,
            planned_date TEXT NOT NULL,
            actual_date TEXT,
            progress INTEGER NOT NULL,
            remark TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    # Deliverables with original VPI-T2 IDs plus custom IDs
    legacy_deliverables = [
        ("VPI-T2-D1", "VPI-T2", "交付物1", "已完成", "负责人1", "2026-05-12", "2026-05-10", 100, "无", "内网", 1, "2026-08-13 09:42:00.000"),
        ("VPI-T2-D2", "VPI-T2", "交付物2", "已完成", "负责人2", "2026-06-18", "2026-06-17", 100, "无", "TDC SOR", 2, "2026-08-13 09:42:00.000"),
        ("VPI-T2-D3", "VPI-T2", "交付物3", "进行中", "负责人3", "2026-08-22", None, 72, "按计划推进", "ARAS EWO", 3, "2026-08-13 09:42:00.000"),
        ("VPI-T2-D4", "VPI-T2", "交付物4", "待审批", "负责人4", "2026-08-15", None, 90, "等待审批", "TDC", 4, "2026-08-13 09:42:00.000"),
        ("VPI-T2-D5", "VPI-T2", "交付物5", "已逾期", "负责人5", "2026-08-08", None, 82, "逾期", "TDC 数模", 5, "2026-08-13 09:42:00.000"),
        ("CUSTOM-DEL-6", "VPI-T2", "扩展交付物6", "进行中", "负责人6", "2026-08-30", None, 50, "扩展", "自定义", 6, "2026-08-13 09:42:00.000"),
    ]
    conn.executemany(
        "INSERT INTO project_status_deliverables (id, phase_id, name, status, owner, planned_date, actual_date, progress, remark, source, sort_order, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        legacy_deliverables,
    )

    conn.execute(
        """
        CREATE TABLE project_status_update_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deliverable_id TEXT NOT NULL UNIQUE,
            mode TEXT NOT NULL DEFAULT 'manual',
            source_type TEXT NOT NULL DEFAULT 'tdc',
            external_key TEXT,
            match_rule_json TEXT NOT NULL DEFAULT '{}',
            mapping_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 0,
            interval_minutes INTEGER,
            last_attempt_at TEXT,
            last_success_at TEXT,
            sync_state TEXT NOT NULL DEFAULT 'idle',
            last_error_type TEXT,
            last_error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        """
    )

    conn.commit()
    conn.close()

    manager = DatabaseManager(db_path=db_path)
    manager.init_database()

    with manager.get_connection() as c:
        version = c.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION

        ms_rows = c.execute(
            "SELECT name, status FROM project_status_milestones WHERE phase_id = 'VPI-T2' ORDER BY sort_order"
        ).fetchall()
        statuses = [row["status"] for row in ms_rows]
        assert statuses == ["已完成", "已完成", "进行中", "进行中", "未开始", "未开始"]

        deliv_rows = c.execute(
            "SELECT id, display_code, sort_order FROM project_status_deliverables WHERE phase_id = 'VPI-T2' ORDER BY sort_order"
        ).fetchall()

        # 存量库 6 行（含自定义交付物）保留原 id 与确定性编码；D6-D8 种子
        # 行按合同编码优先、被占用时顺延补齐（DEL-006 已被 CUSTOM-DEL-6
        # 占用，D6-D8 顺延为 DEL-007/008/009）。
        assert len(deliv_rows) == 9
        expected_codes = [
            "DEL-001", "DEL-002", "DEL-003", "DEL-004", "DEL-005", "DEL-006",
            "DEL-007", "DEL-008", "DEL-009",
        ]
        expected_ids = [
            "VPI-T2-D1", "VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D4", "VPI-T2-D5",
            "CUSTOM-DEL-6", "VPI-T2-D6", "VPI-T2-D7", "VPI-T2-D8",
        ]

        for idx, row in enumerate(deliv_rows):
            assert row["id"] == expected_ids[idx]
            assert row["display_code"] == expected_codes[idx]

        index_exists = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_ps_deliverables_display_code'"
        ).fetchone()
        assert index_exists is not None


def test_source_capabilities_registry_contract() -> None:
    """能力注册表单一来源：契约内交付物可自动同步，键集与连接器消费键一致。"""
    from services.project_status_updates import PROJECT_STATUS_SYNC_CONTRACTS

    sync_ids = {"VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D5"}
    assert set(PROJECT_STATUS_SYNC_CONTRACTS) == sync_ids
    for deliverable_id in sync_ids:
        capabilities = project_status_source_capabilities(deliverable_id)
        assert capabilities["syncCapable"] is True
        assert capabilities["manualOnly"] is False
        contract = PROJECT_STATUS_SYNC_CONTRACTS[deliverable_id]
        assert contract["sourceType"] == capabilities["sourceType"]
        assert contract["reportType"] == capabilities["reportType"]
        # 编辑器 matchFields 的键必须都在 matchKeys 白名单内（防 SOR 键漂移复发）。
        field_keys = {field[0] for field in capabilities["matchFields"]}
        assert field_keys <= set(contract["matchKeys"])
        assert "reportType" in contract["matchKeys"]
        assert capabilities["evidenceFields"], "证据采集必须声明来源连接输入"

    for deliverable_id in ("VPI-T2-D1", "VPI-T2-D4"):
        capabilities = project_status_source_capabilities(deliverable_id)
        assert capabilities["syncCapable"] is False
        assert capabilities["manualOnly"] is True
        assert capabilities["syncNote"]
        assert project_status_default_policy_mode(deliverable_id) == "manual"

    for deliverable_id in sync_ids:
        assert project_status_default_policy_mode(deliverable_id) == "automatic"
    # 未注册交付物兜底为手工。
    assert project_status_default_policy_mode("VPI-T2-D9") == "manual"


@pytest.mark.parametrize(
    ("binding", "manual_editable", "reason"),
    [
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": "{}",
                "mapping_json": "{}",
            },
            True,
            None,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 1,
                "external_key": None,
                "match_rule_json": "{}",
                "mapping_json": "{}",
            },
            True,
            None,
        ),
        # A filter-only rule does not identify a configured record target.
        (
            {
                "mode": "hybrid",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": "{}",
            },
            True,
            None,
        ),
        (
            {
                "mode": "hybrid",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": '{"note":["currentApprover","approvalComment"]}',
            },
            True,
            None,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": "FM-1",
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": "{}",
                "sync_state": "failed",
            },
            False,
            PROJECT_STATUS_MAPPED_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","aggregate":true,"incident":"FM-1"}',
                "mapping_json": "{}",
                "sync_state": "failed",
            },
            False,
            PROJECT_STATUS_MAPPED_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": '{"contractVersion":"2","reportType":"ewo","bindingMode":"record_set","aggregate":true,"modelInfo":"F610S"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_MAPPED_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": '{"contractVersion":"2","reportType":"ewo","bindingMode":"single_record","aggregate":false,"sourceItemId":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","modelInfo":"F610S"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_MAPPED_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": "{broken",
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": '{"aggregate":"true","incident":"FM-1"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": '{"owner":42}',
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"bogus":"x"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"ewo","incident":"FM-1"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": '{"owner":["currentApprover"]}',
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "externalKey": None,
                "matchRule": {"reportType": []},
                "mapping": {},
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "externalKey": None,
                "matchRule": {"reportType": {}},
                "mapping": {},
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "binding": {
                    "externalKey": None,
                    "matchRule": {"reportType": []},
                    "mapping": {},
                },
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        (
            {
                "binding": {
                    "externalKey": None,
                    "matchRule": {"reportType": {}},
                    "mapping": {},
                },
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        # Control character in match rule
        (
            {
                "mode": "hybrid",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1\\u0000"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        # Control character in mapping
        (
            {
                "mode": "hybrid",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": '{"note":["currentApprover\\u0000"]}',
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        # Control character in external_key
        (
            {
                "mode": "automatic",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": "FM-1\x00",
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        # Oversized match rule (> 4000 chars)
        (
            {
                "mode": "hybrid",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"' + ('A' * 4005) + '"}',
                "mapping_json": "{}",
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
        # Oversized mapping (> 4000 chars)
        (
            {
                "mode": "hybrid",
                "enabled": 0,
                "deliverable_id": "VPI-T2-D5",
                "external_key": None,
                "match_rule_json": '{"reportType":"data_model","incident":"FM-1"}',
                "mapping_json": '{"note":["' + ('B' * 4005) + '"]}',
            },
            False,
            PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON,
        ),
    ],
)
def test_project_status_manual_editability_contract(
    binding: dict[str, object],
    manual_editable: bool,
    reason: str | None,
) -> None:
    result = project_status_manual_editability(binding)
    assert result == {"manualEditable": manual_editable, "readOnlyReason": reason}


# ── 展示状态机 formSnapshotDriven 分支（D6-D8 外部快照驱动）────────────


def _driven_state(**overrides: object) -> tuple[str, str, str]:
    from core.project_status_contracts import deliverable_display_state

    kwargs: dict[str, object] = {
        "binding_mode": "manual",
        "binding_enabled": False,
        "binding_sync_state": "idle",
        "last_success_at": None,
        "analysis_summary": None,
        "form_summary": None,
        "aggregate": False,
        "status_baseline": "进行中",
        "form_snapshot_driven": True,
    }
    kwargs.update(overrides)
    return deliverable_display_state(**kwargs)  # type: ignore[arg-type]


def test_display_state_form_snapshot_driven_snapshot_state() -> None:
    """有最新有效表单快照（total>0）→ snapshot 态，沿用快照换算。"""
    state, label, effective = _driven_state(
        form_summary={"total": 4, "completed": 1, "incomplete": 3, "overdue": 1},
    )
    assert (state, label) == ("snapshot", "快照同步")
    assert effective == "已逾期"

    state, label, effective = _driven_state(
        form_summary={"total": 2, "completed": 2, "incomplete": 0, "overdue": 0},
    )
    assert (state, label) == ("snapshot", "快照同步")
    assert effective == "已完成"


def test_display_state_form_snapshot_driven_pending_first_sync() -> None:
    """无快照或 total=0 → pending_first_sync（待同步），不展示数值。"""
    assert _driven_state(form_summary=None)[:2] == ("pending_first_sync", "待同步")
    assert _driven_state(
        form_summary={"total": 0, "completed": 0, "incomplete": 0, "overdue": 0},
    )[:2] == ("pending_first_sync", "待同步")


def test_display_state_form_snapshot_driven_precedes_mode_decision() -> None:
    """formSnapshotDriven 分支先于 mode 判定：manual 绑定也走快照态。"""
    state, _, _ = _driven_state(
        binding_mode="manual",
        binding_enabled=False,
        form_summary={"total": 3, "completed": 0, "incomplete": 3, "overdue": 0},
    )
    assert state == "snapshot"
    # manual 绑定但无快照 → 待同步（而非手工维护）。
    assert _driven_state(binding_mode="manual", form_summary=None)[:2] == (
        "pending_first_sync",
        "待同步",
    )


def test_display_state_form_snapshot_driven_aggregate_gate_kept() -> None:
    """现有 aggregate 门控保留：聚合绑定时表单快照不作为有效摘要。"""
    assert _driven_state(
        aggregate=True,
        form_summary={"total": 3, "completed": 0, "incomplete": 3, "overdue": 0},
    )[:2] == ("pending_first_sync", "待同步")


def test_display_state_non_driven_defaults_unchanged() -> None:
    """未传 form_snapshot_driven（默认 False）时七态输出与既有口径一致。"""
    from core.project_status_contracts import deliverable_display_state

    assert deliverable_display_state(
        "manual", False, "idle", None, None, None, False, "进行中",
    ) == ("manual", "手工维护", "进行中")
    assert deliverable_display_state(
        "automatic", False, "idle", None, None, None, False, "进行中",
    ) == ("pending_config", "待配置", "进行中")


def test_manual_editability_form_snapshot_driven_deliverables() -> None:
    """D6-D8 一律不可手工编辑，固定 readOnlyReason；D5 pristine 不受影响。"""
    from core.project_status_contracts import (
        PROJECT_STATUS_FORM_SNAPSHOT_READ_ONLY_REASON,
    )

    for deliverable_id in ("VPI-T2-D6", "VPI-T2-D7", "VPI-T2-D8"):
        # 无绑定（binding None）也拒绝。
        denied = project_status_manual_editability(None, deliverable_id=deliverable_id)
        assert denied == {
            "manualEditable": False,
            "readOnlyReason": PROJECT_STATUS_FORM_SNAPSHOT_READ_ONLY_REASON,
        }
        # pristine manual 绑定同样拒绝。
        denied = project_status_manual_editability(
            {
                "mode": "manual",
                "enabled": 0,
                "external_key": None,
                "match_rule_json": "{}",
                "mapping_json": "{}",
            },
            deliverable_id=deliverable_id,
        )
        assert denied["manualEditable"] is False
        assert denied["readOnlyReason"] == PROJECT_STATUS_FORM_SNAPSHOT_READ_ONLY_REASON

    # D5（pristine、未配置映射）仍可手工编辑。
    editable = project_status_manual_editability(
        {
            "mode": "manual",
            "enabled": 0,
            "external_key": None,
            "match_rule_json": "{}",
            "mapping_json": "{}",
        },
        deliverable_id="VPI-T2-D5",
    )
    assert editable == {"manualEditable": True, "readOnlyReason": None}


def test_source_capabilities_form_snapshot_driven_flags() -> None:
    """D6-D8 能力标志：syncCapable=False、formSnapshotDriven=True、
    countsTowardCompletion=False；默认策略仍为 manual（不进同步调度）。"""
    for deliverable_id, report_type in (
        ("VPI-T2-D6", "paa"),
        ("VPI-T2-D7", "ncr_progress"),
        ("VPI-T2-D8", "ncr_detail"),
    ):
        capabilities = project_status_source_capabilities(deliverable_id)
        assert capabilities["sourceType"] == "aras"
        assert capabilities["reportType"] == report_type
        assert capabilities["syncCapable"] is False
        assert capabilities["manualOnly"] is False
        assert capabilities["formSnapshotDriven"] is True
        assert capabilities["countsTowardCompletion"] is False
        assert capabilities["syncNote"]
        assert project_status_default_policy_mode(deliverable_id) == "manual"
    # D1-D5 未声明新标志（payload 按缺省 True 处理计数分母）。
    for deliverable_id in ("VPI-T2-D1", "VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D4", "VPI-T2-D5"):
        capabilities = project_status_source_capabilities(deliverable_id)
        assert "formSnapshotDriven" not in capabilities
        assert "countsTowardCompletion" not in capabilities


def test_default_mappings_and_field_aliases_contracts() -> None:
    """核心交付物（D2/D3/D5）内置标准映射与别名字典：确保开箱即用、防空映射。"""
    assert "VPI-T2-D2" in DELIVERABLE_DEFAULT_MAPPINGS
    assert "VPI-T2-D3" in DELIVERABLE_DEFAULT_MAPPINGS
    assert "VPI-T2-D5" in DELIVERABLE_DEFAULT_MAPPINGS
    assert "VPI-T2-D3" in DELIVERABLE_FIELD_ALIASES

    d2_map = get_deliverable_default_mapping("VPI-T2-D2")
    assert d2_map["owner"] == "startUserName"
    assert "latestCompletedNode" in d2_map["note"]
    assert "processInstanceStatus" in d2_map["note"]

    d3_map = get_deliverable_default_mapping("VPI-T2-D3")
    assert d3_map["owner"] == "_rsp_name"
    assert d3_map["plannedDate"] == "_required_date"
    assert "_subject" in d3_map["note"]

    d5_map = get_deliverable_default_mapping("VPI-T2-D5")
    assert d5_map["owner"] == "applicant"
    assert "latestApproveLog" in d5_map["note"]
    assert "status" in d5_map["note"]

    assert get_deliverable_default_mapping("VPI-T2-D1") == {}
    assert get_deliverable_default_mapping("UNKNOWN") == {}

    d3_aliases = get_deliverable_field_aliases("VPI-T2-D3")
    assert "_rsp_name" in d3_aliases["owner"]
    assert "责任工程师名称" in d3_aliases["owner"]
    assert "_required_date" in d3_aliases["plannedDate"]
    assert "要求完成时间" in d3_aliases["plannedDate"]

    # 交叉核验：默认映射的所有字段名必须属于 core/report_contracts 中已核实的源字段集合
    from core.report_contracts import (
        _EWO_SOURCE_FIELDS,
        _TDC_SOR_SOURCE_FIELDS,
        _TDC_DATA_MODEL_SOURCE_FIELDS,
    )
    sor_fields = {f for tup in _TDC_SOR_SOURCE_FIELDS.values() for f in tup}
    ewo_fields = {f for tup in _EWO_SOURCE_FIELDS.values() for f in tup}
    dm_fields = {f for tup in _TDC_DATA_MODEL_SOURCE_FIELDS.values() for f in tup}

    assert d2_map["owner"] in sor_fields
    assert all(f in sor_fields for f in d2_map["note"])

    assert d3_map["owner"] in ewo_fields
    assert d3_map["plannedDate"] in ewo_fields
    assert all(f in ewo_fields for f in d3_map["note"])

    assert d5_map["owner"] in dm_fields
    assert all(f in dm_fields for f in d5_map["note"])

    # 能力注册表中下发 defaultMapping 与 fieldAliases
    d3_caps = project_status_source_capabilities("VPI-T2-D3")
    assert d3_caps["defaultMapping"] == d3_map
    assert d3_caps["fieldAliases"] == d3_aliases
