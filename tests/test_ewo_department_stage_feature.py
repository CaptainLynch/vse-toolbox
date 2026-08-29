from __future__ import annotations

from datetime import date
from pathlib import Path

from core.archive_store import ArchiveStore
from core.db_manager import DatabaseManager
from services.project_status_deliverable_analysis import (
    EWO_ACTIVE_STAGES,
    EWO_DEFAULT_DEPARTMENTS,
    EWO_STAGES,
    ProjectStatusDeliverableAnalysisService,
    normalize_analysis_rows,
    normalize_ewo_stage,
)


def test_ewo_stage_normalizer_and_defaults() -> None:
    assert EWO_DEFAULT_DEPARTMENTS == (
        "车身科", "车体科", "外饰科", "内饰科", "车体架构集成科",
    )
    assert EWO_STAGES == (
        "open", "draft1", "draft2", "edit1", "edit2", "proc", "impl", "close",
    )
    assert EWO_ACTIVE_STAGES == ("draft1", "draft2", "edit1", "edit2", "proc", "impl")
    assert normalize_ewo_stage(" Draft 1 ") == "draft1"
    assert normalize_ewo_stage("CLOSE") == "close"
    assert normalize_ewo_stage("not-a-stage") is None


def test_ewo_normalization_is_explicit_and_close_is_complete() -> None:
    rows = normalize_analysis_rows(
        [
            {"_no": "EWO-1", "_subject": "开放", "_rsp_smt": "车身科", "state": "OPEN"},
            {"_no": "EWO-2", "_subject": "关闭", "_rsp_smt": "车体科", "state": " close "},
            {"_no": "EWO-3", "_subject": "未知", "_rsp_smt": "外饰科", "state": "future"},
        ],
        source_type="aras",
    )
    assert [(row["source_stage"], row["is_completed"]) for row in rows] == [
        ("open", False), ("close", True), (None, False),
    ]
    assert rows[2]["stage_attention"] is True

    generic = normalize_analysis_rows(
        [{"id": "T-1", "status": "close", "actualDate": None}], source_type="tdc"
    )
    assert generic[0]["source_stage"] is None
    assert generic[0]["stage_attention"] is False


def test_ewo_summary_excludes_open_and_unknown_but_checks_active_dates(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "ewo-analysis.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        1,
        [
            {"_no": "EWO-OPEN", "_rsp_smt": "车身科", "_rsp_department": "技术中心_车体工程", "state": "OPEN", "_required_date": "2026-08-01"},
            {"_no": "EWO-ACTIVE", "_rsp_smt": "车体科", "_rsp_department": "技术中心_车体工程", "state": "IMPL", "_required_date": "2026-08-01"},
            {"_no": "EWO-CLOSE", "_rsp_smt": "外饰科", "_rsp_department": "技术中心_外饰", "state": "CLOSE", "_required_date": "2026-08-01"},
            {"_no": "EWO-UNKNOWN", "_rsp_smt": "内饰科", "_rsp_department": "技术中心_内饰", "state": "FUTURE", "_required_date": "2026-08-01"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    overview = service.overview("VPI-T2-D3")
    assert overview["summary"] == {
        "total": 2,
        "completed": 1,
        "incomplete": 1,
        "overdue": 1,
        "dueSoon": 0,
        "missingDueDate": 0,
    }
    assert service.items("VPI-T2-D3")["total"] == 2
    assert service.items("VPI-T2-D3", stage="open")["total"] == 1
    assert service.items("VPI-T2-D3", stage="all")["total"] == 4
    assert service.items("VPI-T2-D3", stage="close")["items"][0]["alertType"] is None
    assert any(item["stageAttention"] is True for item in service.items("VPI-T2-D3", stage="all")["items"])


def test_ewo_items_support_multiple_departments_and_stages_and_unknown_department_is_empty(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "ewo-multi-filter.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        2,
        [
            {"_no": "EWO-BODY", "_rsp_smt": "车身科", "_rsp_department": "技术中心_车体工程", "state": "IMPL", "_required_date": "2026-09-01"},
            {"_no": "EWO-TRIM", "_rsp_smt": "内饰科", "_rsp_department": "技术中心_内饰", "state": "CLOSE", "_required_date": "2026-08-01"},
            {"_no": "EWO-OPEN", "_rsp_smt": "外饰科", "_rsp_department": "技术中心_外饰", "state": "OPEN", "_required_date": "2026-08-01"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )

    filtered = service.items(
        "VPI-T2-D3",
        departments=("车身科", "内饰科"),
        stages=("impl", "close"),
    )
    assert filtered["total"] == 2
    assert {item["department"] for item in filtered["items"]} == {"车身科", "内饰科"}
    assert {item["stage"] for item in filtered["items"]} == {"impl", "close"}
    assert service.items("VPI-T2-D3", departments=("手工输入的未知科室",))["total"] == 0


def test_historical_aras_ewo_cache_recalculates_close_without_mutating_snapshot(tmp_path: Path) -> None:
    db = DatabaseManager(tmp_path / "ewo-legacy-cache.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        3,
        [{"_no": "EWO-CLOSE", "_rsp_smt": "车体科", "_rsp_department": "技术中心_车体工程", "state": "CLOSE", "_required_date": "2026-08-01"}],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_analysis_items "
            "SET source_type = '', source_stage = NULL, is_completed = 0 "
            "WHERE deliverable_id = ?",
            ("VPI-T2-D3",),
        )

    overview = service.overview("VPI-T2-D3")
    assert overview["summary"] == {
        "total": 1,
        "completed": 1,
        "incomplete": 0,
        "overdue": 0,
        "dueSoon": 0,
        "missingDueDate": 0,
    }
    assert service.items("VPI-T2-D3")["items"][0]["stage"] == "close"
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT source_type, source_stage, is_completed "
            "FROM project_status_analysis_items WHERE deliverable_id = ?",
            ("VPI-T2-D3",),
        ).fetchone()
    assert row["source_type"] == ""
    assert row["source_stage"] is None
    assert row["is_completed"] == 0


def test_ewo_default_scope_matches_department_keywords(tmp_path: Path) -> None:
    """默认范围按部门关键词匹配：_rsp_smt 混杂不影响命中，缺部门或无关键词的行被排除。"""
    db = DatabaseManager(tmp_path / "ewo-keyword-scope.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        10,
        [
            {"_no": "EWO-BODY", "_rsp_smt": "车身科", "_rsp_department": "技术中心_车体工程", "state": "IMPL", "_required_date": "2026-09-01"},
            {"_no": "EWO-TRIM", "_rsp_smt": "合并后的新科室", "_rsp_department": "外饰科", "state": "IMPL", "_required_date": "2026-09-01"},
            {"_no": "EWO-PM", "_rsp_smt": "合并后的新科室", "_rsp_department": "项目管理部", "state": "IMPL", "_required_date": "2026-09-01"},
            {"_no": "EWO-NO-DEPT", "_rsp_smt": "内饰科", "state": "IMPL", "_required_date": "2026-09-01"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    assert service.items("VPI-T2-D3")["total"] == 2
    # 部门默认范围对 stage=all 同样生效。
    assert service.items("VPI-T2-D3", stage="all")["total"] == 2
    # 科室列保留 _rsp_smt 原值（混杂值原样展示，不被部门匹配改写）。
    assert {item["department"] for item in service.items("VPI-T2-D3")["items"]} == {
        "车身科",
        "合并后的新科室",
    }


def test_ewo_explicit_department_filter_overrides_default_scope(tmp_path: Path) -> None:
    """显式科室筛选优先于部门关键词默认范围。"""
    db = DatabaseManager(tmp_path / "ewo-explicit-department.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        11,
        [
            {"_no": "EWO-BODY", "_rsp_smt": "车身科", "_rsp_department": "技术中心_车体工程", "state": "IMPL", "_required_date": "2026-09-01"},
            {"_no": "EWO-MERGED", "_rsp_smt": "合并新科室", "_rsp_department": "项目管理部", "state": "IMPL", "_required_date": "2026-09-01"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    # 显式科室筛选覆盖部门默认范围：无关键词部门的行仍可被科室命中。
    merged = service.items("VPI-T2-D3", departments=("合并新科室",))
    assert merged["total"] == 1
    assert [item["department"] for item in merged["items"]] == ["合并新科室"]
    # 无显式筛选时，行 2 被部门默认范围排除。
    assert service.items("VPI-T2-D3")["total"] == 1
    assert service.items("VPI-T2-D3", departments=("车身科",))["total"] == 1


def test_ewo_historical_rows_without_department_excluded_and_not_mutated(tmp_path: Path) -> None:
    """历史缓存行 source_department 为空时不进默认统计，也不被读取路径静默改写。"""
    db = DatabaseManager(tmp_path / "ewo-legacy-department.db")
    db.init_database()
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        12,
        [{"_no": "EWO-BODY", "_rsp_smt": "车身科", "_rsp_department": "技术中心_车体工程", "state": "IMPL", "_required_date": "2026-09-01"}],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE project_status_analysis_items SET source_department = '' "
            "WHERE deliverable_id = ?",
            ("VPI-T2-D3",),
        )

    assert service.items("VPI-T2-D3")["total"] == 0
    assert service.overview("VPI-T2-D3")["summary"]["total"] == 0
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT source_department FROM project_status_analysis_items "
            "WHERE deliverable_id = ?",
            ("VPI-T2-D3",),
        ).fetchone()
    assert row["source_department"] == ""
