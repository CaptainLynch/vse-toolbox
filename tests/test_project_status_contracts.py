# -*- coding: utf-8 -*-
"""Focused tests for project status presentation contracts and database migrations."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from core.db_manager import CURRENT_SCHEMA_VERSION, DatabaseManager
from core.project_status_contracts import (
    current_stage_label,
    milestone_display_status,
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

        assert len(deliv_rows) == 6
        expected_codes = ["DEL-001", "DEL-002", "DEL-003", "DEL-004", "DEL-005", "DEL-006"]
        expected_ids = ["VPI-T2-D1", "VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D4", "VPI-T2-D5", "CUSTOM-DEL-6"]

        for idx, row in enumerate(deliv_rows):
            assert row["id"] == expected_ids[idx]
            assert row["display_code"] == expected_codes[idx]

        index_exists = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_ps_deliverables_display_code'"
        ).fetchone()
        assert index_exists is not None
