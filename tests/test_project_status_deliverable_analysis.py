from __future__ import annotations

from datetime import date

import pytest

from core.db_manager import DatabaseManager
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
    analysis_source_type,
    normalize_analysis_rows,
    normalize_pending_signers,
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


def test_aras_paa_close_status_counts_completed_like_form_caliber(
    tmp_db: DatabaseManager,
) -> None:
    """生产缺陷闭环（2026-09-26）：分析口径必须识别 aras_paa 的 CLOSE 终态。

    同一批行的表单口径按 ``_normalize_stage(status)=="CLOSE"`` 判完成；分析侧
    ``_completed`` 词表只有 ``closed`` 没有 ``close``，曾把 PAA 53 行全判未完成
    （顶部「当前状态」卡 0% 而统一表单分析卡 31/53）。
    """
    rows = [
        {"id": "P-1", "name": "A面确认", "status": "CLOSE", "dueDate": "2026-08-20"},
        {"id": "P-2", "name": "B面确认", "status": "APPR L1", "dueDate": "2026-08-25"},
        {"id": "P-3", "name": "C面确认", "status": "EDIT"},
    ]
    items = normalize_analysis_rows(rows, source_type="aras_paa")
    assert [item["is_completed"] for item in items] == [True, False, False]

    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D6",
        301,
        rows,
        snapshot_at="2026-08-23T07:00:00Z",
        source_type="aras_paa",
    )
    summary = service.latest_link_summary("VPI-T2-D6")
    assert summary is not None
    assert summary["summary"]["total"] == 3
    assert summary["summary"]["completed"] == 1
    # CLOSE 行视为完成后不得再进入逾期/缺日期分母（P-2 临期、P-3 缺计划日期）。
    overview = service.overview("VPI-T2-D6")
    assert overview["summary"]["overdue"] == 0
    assert overview["summary"]["dueSoon"] == 1
    assert overview["summary"]["missingDueDate"] == 1


def test_aras_ncr_close_completes_but_tdc_sources_stay_unchanged() -> None:
    """CLOSE 终态识别按来源限定：aras_ncr 受益；TDC 完成语义不外溢。"""
    ncr_items = normalize_analysis_rows(
        [{"id": "N-1", "name": "NCR 流程", "status": "CLOSE"}],
        source_type="aras_ncr",
    )
    assert ncr_items[0]["is_completed"] is True

    tdc_items = normalize_analysis_rows(
        [{"id": "T-1", "name": "SOR 流程", "status": "close"}],
        source_type="tdc_sor",
    )
    assert tdc_items[0]["is_completed"] is False


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


def test_latest_link_summary_matches_detail_recalc_for_ewo(tmp_db: DatabaseManager) -> None:
    """概览联动摘要与明细页同口径：EWO 交付物按当前日期重算逾期数。

    EWO 行必须满足明细页重算的数据契约（部门默认范围关键词 + EWO 阶段码），
    与 ARAS EWO 连接器产出的行结构一致。
    """
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 20),
    )
    service.publish(
        "VPI-T2-D3",
        201,
        [
            {
                "id": "E-1",
                "name": "门板缺件",
                "responsibleDepartment": "车身设计科",
                "_rsp_department": "技术中心_车体工程",
                "owner": "陈璇",
                "status": "IMPL",
                "dueDate": "2026-08-25",
            },
            {
                "id": "E-2",
                "name": "尾门卡滞",
                "responsibleDepartment": "车身设计科",
                "_rsp_department": "技术中心_车体工程",
                "owner": "李珊",
                "status": "CLOSE",
                "dueDate": "2026-08-10",
                "completedDate": "2026-08-09",
            },
        ],
        snapshot_at="2026-08-20T07:00:00Z",
    )

    # 发布日（2026-08-20）口径：dueDate 未到 → 逾期 0、完成 1（CLOSE 终态）。
    stored = service.latest_link_summary("VPI-T2-D3")
    assert stored == {
        "snapshotAt": "2026-08-20T07:00:00.000Z",
        "summary": {"total": 2, "completed": 1, "incomplete": 1, "overdue": 0},
    }

    # 查询日推进到 2026-08-26：明细页重算 overdue=1，联动摘要必须一致。
    today_service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 26),
    )
    link = today_service.latest_link_summary("VPI-T2-D3")
    assert link["summary"] == {"total": 2, "completed": 1, "incomplete": 1, "overdue": 1}
    detail = today_service.overview("VPI-T2-D3")
    assert detail["summary"]["overdue"] == 1

    # 非 EWO 交付物直接读存储摘要（发布时 overdue=0 保持不变）。
    service.publish(
        "VPI-T2-D5",
        202,
        [
            {
                "id": "N-1",
                "name": "数模任务",
                "responsibleDepartment": "车身设计科",
                "owner": "赵岩",
                "status": "进行中",
                "dueDate": "2026-08-25",
            },
        ],
        snapshot_at="2026-08-20T07:00:00Z",
    )
    d5 = today_service.latest_link_summary("VPI-T2-D5")
    assert d5["summary"] == {"total": 1, "completed": 0, "incomplete": 1, "overdue": 0}


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


def test_normalize_pending_signers_supports_all_source_forms() -> None:
    """字符串/映射/数组与历史折叠行都规范为每条一行 ROLE:person。"""
    # 空值
    assert normalize_pending_signers(None) == ""
    assert normalize_pending_signers("") == ""
    assert normalize_pending_signers("   ") == ""
    # 分号/换行/中英文逗号/中文分号分隔
    assert normalize_pending_signers("PE:张三;LEADER:李四") == "PE:张三\nLEADER:李四"
    assert normalize_pending_signers(
        "PE:张三\nLEADER:李四，MAJOR:王五,SQE:赵六；QA7:小张"
    ) == "PE:张三\nLEADER:李四\nMAJOR:王五\nSQE:赵六\nQA7:小张"
    # 中文冒号归一为英文冒号
    assert normalize_pending_signers("PE：张三") == "PE:张三"
    # 完全相同的 role/person 只保留首次
    assert normalize_pending_signers("PE:张三;LEADER:李四;PE:张三") == "PE:张三\nLEADER:李四"
    # 空白条目丢弃（含只有角色没有人名的 PE:）
    assert normalize_pending_signers("PE:张三;;  ,,LEADER:李四;PE:") == "PE:张三\nLEADER:李四"
    # 同角色多人保留多行
    assert normalize_pending_signers("PE:张三,PE:李四") == "PE:张三\nPE:李四"
    # 未知未来角色原样保留
    assert normalize_pending_signers("QA7:小张") == "QA7:小张"
    # 无角色条目原样保留（、不是分隔符）
    assert normalize_pending_signers("李四、王五") == "李四、王五"
    assert normalize_pending_signers("钱七") == "钱七"
    # 历史折叠行：空格在 ROLE: 前缀处切分，人名内部空格保留
    assert normalize_pending_signers("PE:张三 LEADER:李四") == "PE:张三\nLEADER:李四"
    assert normalize_pending_signers("PE:张三 San LEADER:李四") == "PE:张三 San\nLEADER:李四"
    # 映射形式
    assert normalize_pending_signers({"PE": "张三", "LEADER": "李四"}) == "PE:张三\nLEADER:李四"
    assert normalize_pending_signers({"PE": "张三,李四"}) == "PE:张三\nPE:李四"
    assert normalize_pending_signers({"PE": ["张三", "李四"]}) == "PE:张三\nPE:李四"
    # 数组形式（键名大小写不敏感、字符串元素）
    assert normalize_pending_signers([
        {"role": "PE", "person": "张三"},
        {"Role": "SQE", "Person": "赵六"},
    ]) == "PE:张三\nSQE:赵六"
    assert normalize_pending_signers(["PE:张三", "LEADER:李四"]) == "PE:张三\nLEADER:李四"
    # JSON 字符串形式
    assert normalize_pending_signers('{"PE": "张三"}') == "PE:张三"
    assert normalize_pending_signers('[{"role": "PE", "person": "张三"}]') == "PE:张三"
    # 幂等
    once = normalize_pending_signers("PE:张三;LEADER:李四，SQE:赵六")
    assert normalize_pending_signers(once) == once


def test_pending_signers_never_fall_back_to_owner() -> None:
    """只有负责人字段时不得把负责人当待签署人员。"""
    rows = normalize_analysis_rows(
        [{"id": "T-1", "负责人": "张三", "状态": "进行中"}],
        source_type="tdc",
    )
    assert rows[0]["owner"] == "张三"
    assert rows[0]["pending_signers"] == ""


def test_analysis_rows_store_canonical_signer_lines() -> None:
    """发布路径把数组/映射等待签署输入规范化为多行文本存储。"""
    rows = normalize_analysis_rows(
        [
            {"id": "E-1", "pendingSigners": [{"role": "PE", "person": "张三"}, {"role": "LEADER", "person": "李四"}]},
            {"id": "E-2", "pendingSigners": {"SQE": "赵六"}},
            {"id": "E-3", "待审批人员": "钱七"},
        ],
        source_type="aras",
    )
    stored = {row["display_number"]: row["pending_signers"] for row in rows}
    assert stored["E-1"] == "PE:张三\nLEADER:李四"
    assert stored["E-2"] == "SQE:赵六"
    assert stored["E-3"] == "钱七"


def test_service_items_serializes_pending_signers_per_role_line(tmp_db: DatabaseManager) -> None:
    """存量逗号折叠值在读取时也按 ROLE:person 行规范输出。"""
    service = ProjectStatusDeliverableAnalysisService(tmp_db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D5",
        104,
        [
            {
                "流水单号": "WF-2026-003",
                "流程名": "流程三",
                "申请人": "张三",
                "部门": "质量科",
                "当前待办人": "PE:李四;LEADER:王五，SQE:赵六",
                "状态": "审批中",
            }
        ],
        snapshot_at="2026-08-23T07:00:00Z",
    )
    item = service.items("VPI-T2-D5")["items"][0]
    assert item["pendingSigners"] == "PE:李四\nLEADER:王五\nSQE:赵六"


def test_normalize_rows_capture_department_model_and_extra_fields() -> None:
    """行级新增 source_department / model_info / extra_fields 的捕获契约。

    - 部门别名 `_rsp_department` 优先于 `部门`（不得被科室别名冒充）；
    - `_modelinfo` 去空白归一为 model_info，缺失为 ""，超长截断到 120；
    - extra_fields 按行键插入顺序捕获非标准字段：跳过敏感键名与裸 GUID 值键，
      保留 `__keyed_name` 伴生显示键，最多 60 键（先到先得），空结果为 `{}`。
    """
    items = normalize_analysis_rows(
        [
            {
                "id": "E-1",
                "_rsp_department": "技术中心_车体工程",
                "部门": "技术中心_车体工程",
                "_modelinfo": " F610S ",
                "created_by_id": "AAAABBBBCCCCDDDDEEEEFFFF00001111",
                "created_by_id__keyed_name": "张三",
                "authorization": "Bearer x",
                "password": "x",
            },
        ]
    )
    first = items[0]
    extra = first["extra_fields"]
    assert first["source_department"] == "技术中心_车体工程"
    assert first["model_info"] == "F610S"
    # 裸 GUID 值键跳过，伴生显示键保留（起草人显示名不受排除影响）。
    assert "created_by_id" not in extra
    assert extra["created_by_id__keyed_name"] == "张三"
    # 敏感键名一律不入 extra_fields。
    assert "authorization" not in extra
    assert "password" not in extra

    # 最多捕获 60 个键（先到先得）。
    many = normalize_analysis_rows(
        [{"id": "E-2", **{f"f{i:02d}": "v" for i in range(65)}}]
    )
    assert len(many[0]["extra_fields"]) == 60

    # 无额外键的行 extra_fields 为空 dict；model_info 缺失为空字符串。
    plain = normalize_analysis_rows(
        [{"id": "E-3", "name": "无额外字段任务", "status": "进行中"}]
    )
    assert plain[0]["extra_fields"] == {}
    assert plain[0]["model_info"] == ""

    # 车型超长（130 字符）截断到 120。
    long_model = normalize_analysis_rows(
        [{"id": "E-4", "_modelinfo": "M" * 130}]
    )
    assert long_model[0]["model_info"] == "M" * 120


def test_chart_groups_standard_extra_and_model_filter(tmp_db: DatabaseManager) -> None:
    """分组统计支持标准列与 extra_fields 键，并与明细/摘要用同一车型过滤口径。"""
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        201,
        [
            {
                "id": "T-1",
                "name": "任务一",
                "department": "质量科",
                "owner": "张三",
                "_rsp_name": "张三",
                "status": "进行中",
                "dueDate": "2026-08-20",
            },
            {
                "id": "T-2",
                "name": "任务二",
                "department": "质量科",
                "owner": "张三",
                "_rsp_name": "张三",
                "status": "已完成",
                "dueDate": "2026-08-21",
            },
            {
                "id": "T-3",
                "name": "任务三",
                "department": "车身设计科",
                "owner": "李四",
                "_rsp_name": "李四",
                "status": "进行中",
                "dueDate": "2026-08-22",
            },
        ],
        snapshot_at="2026-08-23T00:00:00Z",
    )

    expected = {
        "张三": {"total": 2, "completed": 1, "incomplete": 1},
        "李四": {"total": 1, "completed": 0, "incomplete": 1},
    }
    # 标准列字段与 extra_fields 伴生键（负责人 `_rsp_name`）分组一致。
    assert service.chart_groups("VPI-T2-D5", "owner") == expected
    assert service.chart_groups("VPI-T2-D5", "_rsp_name") == expected

    with pytest.raises(ValueError):
        service.chart_groups("VPI-T2-D5", "no_such_field")

    service.publish(
        "VPI-T2-D3",
        202,
        [
            {
                "_no": "EWO-MA",
                "_subject": "F610S 蒙皮更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_modelinfo": "F610S-A",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
            {
                "_no": "EWO-MB",
                "_subject": "F610S 内饰更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_modelinfo": "F610S-B",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
            {
                "_no": "EWO-GM",
                "_subject": "G610M 顶盖更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_modelinfo": "G610M",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
        ],
        source_type="aras",
        snapshot_at="2026-08-23T01:00:00Z",
    )

    groups = service.chart_groups("VPI-T2-D3", "model_info")
    assert set(groups) == {"F610S-A", "F610S-B", "G610M"}
    assert groups["F610S-A"] == {"total": 1, "completed": 0, "incomplete": 1}

    # fuzzy（默认）：大小写不敏感子串包含。
    fuzzy = service.chart_groups("VPI-T2-D3", "model_info", model="F610S")
    assert set(fuzzy) == {"F610S-A", "F610S-B"}

    # exact：去空白后全等，无命中时分组为空。
    exact = service.chart_groups(
        "VPI-T2-D3",
        "model_info",
        model="F610S",
        model_match="exact",
    )
    assert exact == {}

    with pytest.raises(ValueError):
        service.items("VPI-T2-D3", model="F610S", model_match="bogus")


def test_chart_label_validation_and_roundtrip(tmp_db: DatabaseManager) -> None:
    """图表标签存取：整体替换、sortOrder 从 1 编号、逐项校验失败抛 ValueError。"""
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        301,
        [
            {
                "id": "L-1",
                "name": "标签轮换任务",
                "department": "质量科",
                "owner": "张三",
                "status": "进行中",
                "dueDate": "2026-08-20",
            },
        ],
        snapshot_at="2026-08-23T00:00:00Z",
    )

    service.save_chart_labels(
        "VPI-T2-D5",
        [
            {"label": "内容A", "sourceField": "department"},
            {"label": "内容B", "sourceField": "owner"},
        ],
    )
    expected_labels = [
        {
            "label": "内容A",
            "sourceField": "department",
            "sortOrder": 1,
            "groups": [],
            "unmatched": "keep",
        },
        {
            "label": "内容B",
            "sourceField": "owner",
            "sortOrder": 2,
            "groups": [],
            "unmatched": "keep",
        },
    ]
    assert service.chart_labels("VPI-T2-D5") == expected_labels

    def _expect_error(labels: list[dict[str, str]]) -> None:
        with pytest.raises(ValueError):
            service.save_chart_labels("VPI-T2-D5", labels)

    # 超过 6 个标签。
    _expect_error(
        [{"label": f"标签{i}", "sourceField": "department"} for i in range(7)]
    )
    # label 空白。
    _expect_error([{"label": "   ", "sourceField": "department"}])
    # label 41 字符。
    _expect_error([{"label": "甲" * 41, "sourceField": "department"}])
    # label 含控制字符（换行必须位于中部，strip 后仍保留）。
    _expect_error([{"label": "内容\nA", "sourceField": "department"}])
    # label 去空白后重复。
    _expect_error(
        [
            {"label": "重复", "sourceField": "department"},
            {"label": " 重复 ", "sourceField": "owner"},
        ]
    )
    # sourceField 81 字符。
    _expect_error([{"label": "内容C", "sourceField": "a" * 81}])
    # sourceField 含空格（不满足字符集正则）。
    _expect_error([{"label": "内容C", "sourceField": "bad field"}])
    # sourceField 不在最近缓存行字段集合。
    _expect_error([{"label": "内容C", "sourceField": "no_such_field"}])
    # sourceField 为空。
    _expect_error([{"label": "内容C", "sourceField": ""}])

    # 校验失败不落库，原配置保持不变。
    assert service.chart_labels("VPI-T2-D5") == expected_labels

    # 整体替换：先存 3 个再存 2 个，只剩 2 个且 sortOrder 重新从 1 编号。
    service.save_chart_labels(
        "VPI-T2-D5",
        [
            {"label": "甲", "sourceField": "department"},
            {"label": "乙", "sourceField": "owner"},
            {"label": "丙", "sourceField": "department"},
        ],
    )
    assert len(service.chart_labels("VPI-T2-D5")) == 3
    service.save_chart_labels(
        "VPI-T2-D5",
        [
            {"label": "内容A", "sourceField": "department"},
            {"label": "内容B", "sourceField": "owner"},
        ],
    )
    assert service.chart_labels("VPI-T2-D5") == expected_labels


def test_chart_label_group_rules_validation(tmp_db: DatabaseManager) -> None:
    """分组定义校验：上限/组名/成员/跨组重叠/unmatched，失败不落库。"""
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        401,
        [
            {
                "id": "L-1",
                "name": "分组校验任务",
                "department": "质量科",
                "owner": "张三",
                "status": "进行中",
                "dueDate": "2026-08-20",
            },
        ],
        snapshot_at="2026-08-23T00:00:00Z",
    )

    def _rules(
        groups: list[dict[str, object]],
        unmatched: str = "keep",
    ) -> list[dict[str, object]]:
        return [
            {
                "label": "科室",
                "sourceField": "department",
                "groups": groups,
                "unmatched": unmatched,
            }
        ]

    def _expect_error(labels: object) -> None:
        with pytest.raises(ValueError):
            service.save_chart_labels("VPI-T2-D5", labels)

    valid = _rules(
        [
            {"name": "内饰科", "members": ["内饰科", "内饰工程科", "内饰设计科"]},
            {"name": "外饰科", "members": ["外饰科", "外饰工程科"]},
        ]
    )
    service.save_chart_labels("VPI-T2-D5", valid)
    assert service.chart_labels("VPI-T2-D5") == [
        {
            "label": "科室",
            "sourceField": "department",
            "sortOrder": 1,
            "groups": [
                {"name": "内饰科", "members": ["内饰科", "内饰工程科", "内饰设计科"]},
                {"name": "外饰科", "members": ["外饰科", "外饰工程科"]},
            ],
            "unmatched": "keep",
        },
    ]

    # 组数量超过 20。
    _expect_error(_rules([{"name": f"组{i}", "members": ["质量科"]} for i in range(21)]))
    # 组名空白。
    _expect_error(_rules([{"name": "", "members": ["质量科"]}]))
    # 组名 41 字符。
    _expect_error(_rules([{"name": "甲" * 41, "members": ["质量科"]}]))
    # 组名含控制字符。
    _expect_error(_rules([{"name": "组\n名", "members": ["质量科"]}]))
    # 组名去空白后重复。
    _expect_error(
        _rules([{"name": "内饰科", "members": []}, {"name": " 内饰科 ", "members": []}])
    )
    # 组名出现在其他组的成员里。
    _expect_error(_rules([{"name": "A", "members": ["B"]}, {"name": "B", "members": []}]))
    # 同一成员跨组重叠。
    _expect_error(_rules([{"name": "A", "members": ["x"]}, {"name": "B", "members": ["x"]}]))
    # 成员 81 字符。
    _expect_error(_rules([{"name": "A", "members": ["m" * 81]}]))
    # 单标签成员总数超过 200。
    _expect_error(_rules([{"name": "A", "members": [f"m{i:03d}" for i in range(201)]}]))
    # unmatched 非法。
    _expect_error(_rules([{"name": "A", "members": ["质量科"]}], unmatched="bogus"))

    # 空成员静默丢弃 + 组内成员去重。
    service.save_chart_labels(
        "VPI-T2-D5",
        _rules([{"name": "内饰科", "members": ["", "  ", "内饰工程科", "内饰工程科"]}]),
    )
    assert service.chart_labels("VPI-T2-D5")[0]["groups"] == [
        {"name": "内饰科", "members": ["内饰工程科"]}
    ]

    # 校验失败不落库，原分组配置保持不变。
    with pytest.raises(ValueError):
        service.save_chart_labels(
            "VPI-T2-D5",
            _rules([{"name": "A", "members": ["x"]}, {"name": "B", "members": ["x"]}]),
        )
    assert service.chart_labels("VPI-T2-D5")[0]["groups"] == [
        {"name": "内饰科", "members": ["内饰工程科"]}
    ]


def test_chart_groups_apply_member_mapping(tmp_db: DatabaseManager) -> None:
    """分组映射：多对一归并、组名隐式自归属、unmatched 三态、空规则向后兼容。"""
    service = ProjectStatusDeliverableAnalysisService(
        tmp_db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        402,
        [
            {
                "id": "M-1",
                "name": "任务一",
                "department": "内饰科",
                "owner": "甲",
                "status": "进行中",
                "dueDate": "2026-08-20",
            },
            {
                "id": "M-2",
                "name": "任务二",
                "department": "内饰科",
                "owner": "乙",
                "status": "已完成",
                "dueDate": "2026-08-20",
            },
            {
                "id": "M-3",
                "name": "任务三",
                "department": "内饰工程科",
                "owner": "丙",
                "status": "进行中",
                "dueDate": "2026-09-30",
            },
            {
                "id": "M-4",
                "name": "任务四",
                "department": "内饰工程科",
                "owner": "丁",
                "status": "已完成",
                "dueDate": "2026-08-19",
            },
            {
                "id": "M-5",
                "name": "任务五",
                "department": "内饰设计科",
                "owner": "戊",
                "status": "进行中",
                "dueDate": "2026-09-01",
            },
            {
                "id": "M-6",
                "name": "任务六",
                "department": "结构工程科",
                "owner": "己",
                "status": "进行中",
                "dueDate": "2026-09-15",
            },
            {
                "id": "M-7",
                "name": "任务七",
                "department": "结构工程科",
                "owner": "庚",
                "status": "已完成",
                "dueDate": "2026-08-21",
            },
            {
                "id": "M-8",
                "name": "任务八",
                "department": "外饰科",
                "owner": "辛",
                "status": "进行中",
                "dueDate": "2026-09-15",
            },
        ],
        snapshot_at="2026-08-23T00:00:00Z",
    )

    # 组名"内饰科"不在 members 里，依赖组名隐式自归属。
    rules = [{"name": "内饰科", "members": ["内饰工程科", "内饰设计科"]}]

    # keep：归并组 + 未映射值独立成键，总数守恒（8 = 5+2+1）。
    keep = service.chart_groups("VPI-T2-D5", "department", groups=rules, unmatched="keep")
    assert keep == {
        "内饰科": {"total": 5, "completed": 2, "incomplete": 3},
        "结构工程科": {"total": 2, "completed": 1, "incomplete": 1},
        "外饰科": {"total": 1, "completed": 0, "incomplete": 1},
    }

    # other：未命中并入"未分组"。
    other = service.chart_groups("VPI-T2-D5", "department", groups=rules, unmatched="other")
    assert other == {
        "内饰科": {"total": 5, "completed": 2, "incomplete": 3},
        "未分组": {"total": 3, "completed": 1, "incomplete": 2},
    }

    # hide：未命中从图表排除。
    hide = service.chart_groups("VPI-T2-D5", "department", groups=rules, unmatched="hide")
    assert hide == {"内饰科": {"total": 5, "completed": 2, "incomplete": 3}}

    # 成员 strip 后匹配：规则只含 内饰工程科，归并组 = 组名自归属(2) + 成员(2)；
    # 内饰设计科 未映射，keep 模式独立成键。
    spaced = service.chart_groups(
        "VPI-T2-D5",
        "department",
        groups=[{"name": "内饰科", "members": ["  内饰工程科  "]}],
        unmatched="keep",
    )
    assert spaced["内饰科"]["total"] == 4
    assert spaced["内饰设计科"]["total"] == 1

    # 空/缺省 groups：行为与现状完全一致（原始值直接作为键）。
    raw = service.chart_groups("VPI-T2-D5", "department")
    assert raw == {
        "内饰科": {"total": 2, "completed": 1, "incomplete": 1},
        "内饰工程科": {"total": 2, "completed": 1, "incomplete": 1},
        "内饰设计科": {"total": 1, "completed": 0, "incomplete": 1},
        "结构工程科": {"total": 2, "completed": 1, "incomplete": 1},
        "外饰科": {"total": 1, "completed": 0, "incomplete": 1},
    }

    with pytest.raises(ValueError):
        service.chart_groups("VPI-T2-D5", "department", groups=rules, unmatched="bogus")


def test_analysis_status_alias_covers_sor_process_instance_status() -> None:
    """分析口径的 status 别名必须覆盖 TDC SOR 的 processInstanceStatus（生产缺陷 2026-09-26）。

    应用行已扁平化为纯文本 → 直接命中完成词表；历史/异构行仍是嵌套对象时只取
    name，不用数值形态推断完成。
    """
    items = normalize_analysis_rows(
        [
            {"id": "S-1", "name": "A", "processInstanceStatus": "已完成"},
            {"id": "S-2", "name": "B", "processInstanceStatus": "审批中"},
            {"id": "S-3", "name": "C", "processInstanceStatus": {"value": 4, "valueStr": "4"}},
        ],
        source_type="tdc_sor",
    )
    assert [item["is_completed"] for item in items] == [True, False, False]
    assert items[2]["source_status"] in ("", None)


def test_tdc_data_model_numeric_status_completion_alignment() -> None:
    """分析口径对齐表单侧：数模数字状态码 "4"=已完成、"2"/未知码=未完成（2026-09-29 生产缺陷）。

    现场症状：分析快照 completed=0/717 而表单明细正常——``_completed`` 的子串
    词表识别不了数字码且数模行无实际完成日期。修复后仅 tdc_data_model 标签
    生效，已废弃/审批中不在完成集内自然为 False。
    """
    items = normalize_analysis_rows(
        [
            {"id": "D-1", "name": "A", "status": "4"},
            {"id": "D-2", "name": "B", "status": "2"},
            {"id": "D-3", "name": "C", "status": "9"},
            {"id": "D-4", "name": "D", "status": "已完成"},
        ],
        source_type="tdc_data_model",
    )
    assert [item["is_completed"] for item in items] == [True, False, False, True]


def test_tdc_sor_rows_keep_text_completion_semantics() -> None:
    """SOR 行完成判定不受数模数字码对齐影响（来源限定，不外溢）。"""
    items = normalize_analysis_rows(
        [
            {"id": "S-1", "name": "A", "status": "已完成"},
            {"id": "S-2", "name": "B", "status": "审批中"},
            {"id": "S-3", "name": "C", "status": "已撤回"},
        ],
        source_type="tdc_sor",
    )
    assert [item["is_completed"] for item in items] == [True, False, False]


def test_analysis_source_type_tags_tdc_reports() -> None:
    """TDC 写入侧使用限定来源标签（与 Aras 同一先例）；其他来源不变。"""
    assert analysis_source_type("tdc", "data_model") == "tdc_data_model"
    assert analysis_source_type("tdc", "sor") == "tdc_sor"
    assert analysis_source_type("tdc", "unknown_report") == "tdc"
    assert analysis_source_type("aras", "ewo") == "aras_ewo"
