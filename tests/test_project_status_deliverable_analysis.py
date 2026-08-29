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


def test_normalize_maps_aras_ewo_underscore_fields() -> None:
    """ARAS EWO 行使用 `_` 前缀字段（`_no`/`_subject`/`_rsp_smt`），必须正确映射。

    `_normalized_key` 的 `\\w` 保留前导下划线，裸键别名（no/subject）匹配不到
    `_no`/`_subject`；别名表必须显式收录，否则编号/名称退化为内部 id（GUID）。
    科室取 `_rsp_smt`（车体科/外饰科/内饰科/车身科/车体架构集成科等）；
    `_rsp_department` 是部门名，不得冒充科室。
    """
    items = normalize_analysis_rows(
        [
            {
                "id": "AAAABBBBCCCCDDDDEEEEFFFF00001111",
                "_no": "EWO-049039",
                "_subject": "F610S 蒙皮总成更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_rsp_name": "莫仕沾(m22400106)",
                "state": "EDIT2",
                "_required_date": "2026-09-30T00:00:00",
            },
            {
                "id": "BBBBCCCCDDDDEEEEFFFF000011112222",
                "_no": "EWO-049040",
                "_subject": "F610S 内饰件更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_name": "李四",
                "state": "EDIT2",
            },
        ]
    )
    first = items[0]
    # 业务单号必须优先于内部 id（GUID）。
    assert first["display_number"] == "EWO-049039"
    assert first["title"] == "F610S 蒙皮总成更改"
    assert first["department"] == "车体科"
    assert first["owner"] == "莫仕沾(m22400106)"
    assert first["source_status"] == "EDIT2"
    assert first["planned_date"] == "2026-09-30"
    # 只有部门没有科室的行归入「未归属」，不得把部门名当科室显示。
    assert items[1]["department"] == "未归属"


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
