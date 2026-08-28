from __future__ import annotations

from datetime import date

from core.db_manager import DatabaseManager
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
    normalize_analysis_rows,
    summarize_analysis_items,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "id": "A-1",
            "name": "冻结发布单确认",
            "responsibleDepartment": "质量科",
            "owner": "赵岩",
            "status": "进行中",
            "dueDate": "2026-08-18",
        },
        {
            "id": "A-2",
            "name": "A 面数据确认",
            "responsibleDepartment": "车身设计科",
            "owner": "陈璇",
            "status": "进行中",
            "dueDate": "2026-08-25",
        },
        {
            "id": "A-3",
            "name": "审批意见关闭",
            "responsibleDepartment": "项目管理科",
            "owner": "周敏",
            "status": "已完成",
            "dueDate": "2026-08-20",
            "completedDate": "2026-08-19",
        },
        {
            "id": "A-4",
            "name": "缺少日期任务",
            "responsibleDepartment": "",
            "status": "待处理",
        },
    ]


def test_normalize_and_summarize_analysis_rows() -> None:
    items = normalize_analysis_rows(_rows())
    assert len(items) == 4
    assert items[3]["department"] == "未归属"
    assert all(len(str(item["item_key"])) == 64 for item in items)

    summary = summarize_analysis_items(
        items,
        snapshot_at="2026-08-23T07:00:00Z",
        today=date(2026, 8, 23),
    )
    assert summary["total_count"] == 4
    assert summary["completed_count"] == 1
    assert summary["incomplete_count"] == 3
    assert summary["overdue_count"] == 1
    assert summary["due_soon_count"] == 1
    assert summary["missing_due_date_count"] == 1
    assert summary["department_counts"]["质量科"] == {
        "total": 1,
        "completed": 0,
        "incomplete": 1,
    }


def test_normalize_preserves_business_number_and_pending_signers() -> None:
    """Chinese TDC report headers map to the fields required by the detail table."""
    items = normalize_analysis_rows(
        [
            {
                "流水单号": "WF-2026-001",
                "流程名": "数模审核流程",
                "申请人": "张三",
                "部门": "技术中心_车体工程",
                "待审批人员": "李四、王五",
                "状态": "审批中",
            }
        ]
    )

    assert items[0]["display_number"] == "WF-2026-001"
    assert items[0]["title"] == "数模审核流程"
    assert items[0]["owner"] == "张三"
    assert items[0]["pending_signers"] == "李四、王五"

    english_items = normalize_analysis_rows(
        [
            {
                "formId": "FORM-001",
                "incident": "INC-001",
                "currentApprover": "审批人",
                "department": "车体工程",
                "applicant": "申请人",
                "approvalStatus": "审批中",
            }
        ]
    )
    assert english_items[0]["display_number"] == "INC-001"
    assert english_items[0]["pending_signers"] == "审批人"


def test_service_publishes_cache_trend_and_alert_items(tmp_db: DatabaseManager) -> None:
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        101,
        _rows(),
        snapshot_at="2026-08-20T07:00:00Z",
    )
    service.publish(
        "VPI-T2-D5",
        102,
        [*_rows(), {"id": "A-5", "name": "新增完成任务", "status": "完成"}],
        snapshot_at="2026-08-23T07:00:00Z",
    )

    overview = service.overview("VPI-T2-D5")
    assert overview["hasCache"] is True
    assert overview["summary"] == {
        "total": 5,
        "completed": 2,
        "incomplete": 3,
        "overdue": 1,
        "dueSoon": 1,
        "missingDueDate": 1,
    }
    assert [point["completed"] for point in overview["trend"]] == [1, 2]
    assert overview["departments"]["未归属"]["total"] == 2

    overdue = service.items("VPI-T2-D5", alert="overdue")
    assert overdue["total"] == 1
    assert overdue["items"][0]["title"] == "冻结发布单确认"
    assert overdue["items"][0]["days"] == 5

    due_soon = service.items("VPI-T2-D5", alert="due_soon")
    assert due_soon["total"] == 1
    assert due_soon["items"][0]["days"] == 2


def test_service_returns_truthful_empty_cache(tmp_db: DatabaseManager) -> None:
    service = ProjectStatusDeliverableAnalysisService(tmp_db)
    result = service.overview("VPI-T2-D3")
    assert result["hasCache"] is False
    assert result["summary"] is None
    assert result["departments"] == {}
    assert result["trend"] == []


def test_service_items_exposes_business_number_and_pending_signers(tmp_db: DatabaseManager) -> None:
    """The API-facing analysis item includes a display number and pending signers."""
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        103,
        [
            {
                "流水单号": "WF-2026-002",
                "流程名": "流程二",
                "申请人": "赵六",
                "部门": "质量科",
                "待审批人员": "钱七",
                "状态": "审批中",
            }
        ],
        snapshot_at="2026-08-23T07:00:00Z",
    )

    item = service.items("VPI-T2-D5")["items"][0]

    assert item["itemNumber"] == "WF-2026-002"
    assert item["pendingSigners"] == "钱七"
