# -*- coding: utf-8 -*-
"""数模设计审核流程（D5）项目件/架构件分组规则的离线测试。

口径（用户 2026-10-23 确认，方案 a+c）：

* 项目件按**车型**统计；
* 架构件按**架构平台**单列，不归属单一车型、不并入车型合计；
* 车型归属的唯一权威来源是外部项目派单台账（``ledger_vehicle``）；
* ``EWO/SOR号`` 与流水单号前缀**都不是**归属证据，必须保持被忽略。

另含代码评审（docs/CODE_REVIEW_D5_20261023.md）四项发现的回归测试：
R1 复合分组标签不能当 stage 值查库；R2 独立表单页要展平分组维度；
R3 旧快照读取兜底要用保留的 values 重算；R4 平台分组不能互相合并。
"""

from __future__ import annotations

from core import form_registry
from services import data_model_attribution as attribution
from services.deliverable_form_analysis import (
    _dimensions_from_tdc,
    _enrich_data_model_dimensions,
    _filter_rows_by_group_label,
    _split_data_model_group_filters,
    _stage_status_summary,
    form_definition,
)


# ── 脏值归一 ────────────────────────────────────────────────────────────────


def test_normalize_vehicle_accepts_clean_codes() -> None:
    assert attribution.normalize_vehicle("F620S") == ("F620S", False)
    assert attribution.normalize_vehicle(" f710s ") == ("F710S", False)


def test_normalize_vehicle_repairs_observed_dirty_values() -> None:
    """实测导出里的两类脏值：带描述后缀、漏字母前缀。"""
    assert attribution.normalize_vehicle("F620S产品项目") == ("F620S", True)
    assert attribution.normalize_vehicle("620S") == ("F620S", True)


def test_normalize_vehicle_rejects_non_vehicle_text() -> None:
    for value in ("", None, "Ar-L", "Ar-L+", "F999X产品项目"):
        vehicle, repaired = attribution.normalize_vehicle(value)
        assert vehicle == ""
        assert repaired is False


# ── 来源判定 ────────────────────────────────────────────────────────────────


def test_classify_source_separates_platform_from_vehicle() -> None:
    for value in ("Ar-L", "Ar-L+", "ar-l", "AR_L"):
        assert attribution.classify_source(value) == attribution.ARCHITECTURE_PART
    for value in ("F620S", "620S", "F620S产品项目", ""):
        assert attribution.classify_source(value) == attribution.PROJECT_PART


# ── 行级分组 ────────────────────────────────────────────────────────────────


def test_dimension_fields_for_project_part() -> None:
    fields = attribution.dimension_fields("F620S")
    assert fields == {
        "dataSource": attribution.PROJECT_PART,
        "vehicle": "F620S",
        "attribution": attribution.ATTRIBUTION_SELF,
        "archPlatform": "",
    }


def test_dimension_fields_for_architecture_part_goes_to_platform_not_vehicle() -> None:
    fields = attribution.dimension_fields("Ar-L")
    assert fields["dataSource"] == attribution.ARCHITECTURE_PART
    assert fields["vehicle"] == ""
    assert fields["attribution"] == attribution.ATTRIBUTION_PLATFORM
    assert fields["archPlatform"] == "Ar-L"


def test_dimension_fields_uses_ledger_vehicle_when_provided() -> None:
    """台账是唯一权威车型来源：给出即归属，并标注「台账归属」。"""
    fields = attribution.dimension_fields("Ar-L", ledger_vehicle="f620s")
    assert fields["vehicle"] == "F620S"
    assert fields["attribution"] == attribution.ATTRIBUTION_LEDGER
    assert fields["archPlatform"] == "Ar-L"


# ── 反面回归：SOR 号 / 流水单号前缀不得参与归属 ────────────────────────────


def test_sor_number_is_not_evidence_for_attribution() -> None:
    """SOR 是零件定点文档编号，与数模审批单无关（用户 2026-10-23 确认）。

    早期版本把 ``SGMW-F710S-SOR0023`` 当成"该单服务 F710S"的证据，导致
    架构件 94 单里 34 单被错误归到车型。``dimension_fields`` 已无该入参，
    这里锁死行为：架构件无论 SOR 写什么，都按平台单列。
    """
    assert "ewo" not in attribution.dimension_fields.__code__.co_varnames
    assert "document" not in attribution.dimension_fields.__code__.co_varnames
    fields = attribution.dimension_fields("Ar-L")
    assert fields["vehicle"] == ""
    assert attribution.group_label(fields) == "Ar-L · 架构件"


def test_project_part_ignores_sor_that_points_to_another_vehicle() -> None:
    """实测反证：F620S 发布单里存在 SOR 指向 F710S 的行，发布车型仍应为 F620S。"""
    fields = attribution.dimension_fields("F620S")
    assert fields["vehicle"] == "F620S"
    assert attribution.group_label(fields) == "F620S · 项目件"


# ── 旧快照兜底与分组标签 ────────────────────────────────────────────────────


def test_resolve_dimensions_derives_from_legacy_stage_only_snapshot() -> None:
    """旧快照只有 stage 键，读取侧按同一套纯函数兜底，无需回填。"""
    resolved = attribution.resolve_dimensions({"stage": "Ar-L", "status": "已完成"})
    assert resolved["dataSource"] == attribution.ARCHITECTURE_PART
    assert resolved["attribution"] == attribution.ATTRIBUTION_PLATFORM
    assert resolved["archPlatform"] == "Ar-L"


def test_resolve_dimensions_recomputes_legacy_sor_based_attribution() -> None:
    """早期版本写进快照的 SOR 归属必须按新口径重算，不能沿用。"""
    legacy = {
        "stage": "Ar-L",
        "dataSource": attribution.ARCHITECTURE_PART,
        "vehicle": "F710S",
        "attribution": "SOR号证据",
        "archPlatform": "Ar-L",
    }
    resolved = attribution.resolve_dimensions(legacy)
    assert resolved["attribution"] == attribution.ATTRIBUTION_PLATFORM
    assert resolved["vehicle"] == ""


def test_group_label_shapes() -> None:
    assert attribution.group_label(attribution.dimension_fields("F620S")) == "F620S · 项目件"
    assert attribution.group_label(attribution.dimension_fields("Ar-L")) == "Ar-L · 架构件"
    assert (
        attribution.group_label(attribution.dimension_fields("Ar-L", ledger_vehicle="F620S"))
        == "F620S · 架构件（台账）"
    )


def test_group_sort_key_places_vehicle_groups_before_platform_groups() -> None:
    labels = ["Ar-L · 架构件", "F710S · 项目件", "Ar-L+ · 架构件", "F620S · 项目件"]
    assert sorted(labels, key=attribution.group_sort_key) == [
        "F620S · 项目件",
        "F710S · 项目件",
        "Ar-L · 架构件",
        "Ar-L+ · 架构件",
    ]


# ── 实例级汇总 ──────────────────────────────────────────────────────────────


def _row(stage: str, status: str, instance: str, ledger: str | None = None) -> dict:
    return {
        "instance": instance,
        "status": status,
        "dimensions": {
            **attribution.dimension_fields(stage, ledger_vehicle=ledger),
            "stage": stage,
        },
    }


def test_summarize_instances_counts_instances_not_rows() -> None:
    rows = [
        _row("F620S", "已完成", "I1"),
        _row("F620S", "已完成", "I1"),  # 同一实例的第二行，不得重复计数
        _row("F620S", "审批中", "I2"),
    ]
    group = attribution.summarize_instances(rows)[0]
    assert group["label"] == "F620S · 项目件"
    assert group["total"] == 2
    assert group["completed"] == 1
    assert group["active"] == 1


def test_summarize_instances_excludes_discarded_from_completion_rate() -> None:
    rows = [
        _row("F620S", "已完成", "I1"),
        _row("F620S", "审批中", "I2"),
        _row("F620S", "已废弃", "I3"),
    ]
    group = attribution.summarize_instances(rows)[0]
    assert group["total"] == 3
    assert group["discarded"] == 1
    # 已完成 / (已完成 + 审批中)，已废弃不进分母。
    assert group["completionRate"] == 50.0


def test_summarize_instances_keeps_platforms_separate() -> None:
    rows = [_row("Ar-L", "已完成", "i1"), _row("Ar-L+", "已完成", "i2")]
    groups = attribution.summarize_instances(rows)
    assert [group["label"] for group in groups] == ["Ar-L · 架构件", "Ar-L+ · 架构件"]
    assert [group["total"] for group in groups] == [1, 1]


def test_summarize_vehicles_excludes_architecture_parts() -> None:
    """架构件不并入任何车型合计——这是方案 (c) 的核心断言。"""
    rows = [
        _row("F620S", "已完成", "I1"),
        _row("Ar-L", "已完成", "I2"),
        _row("Ar-L+", "已完成", "I3"),
    ]
    vehicles = attribution.summarize_vehicles(rows)
    assert [item["vehicle"] for item in vehicles] == ["F620S"]
    assert vehicles[0]["total"] == 1
    assert [part["dataSource"] for part in vehicles[0]["parts"]] == [attribution.PROJECT_PART]


def test_summarize_platforms_reports_architecture_only() -> None:
    rows = [
        _row("F620S", "已完成", "I1"),
        _row("Ar-L", "已完成", "I2"),
        _row("Ar-L", "审批中", "I3"),
        _row("Ar-L+", "已废弃", "I4"),
    ]
    platforms = attribution.summarize_platforms(rows)
    by_name = {item["archPlatform"]: item for item in platforms}
    assert set(by_name) == {"Ar-L", "Ar-L+"}
    assert by_name["Ar-L"]["total"] == 2
    assert by_name["Ar-L"]["completed"] == 1
    assert by_name["Ar-L+"]["discarded"] == 1


# ── 与表单解析/汇总的集成 ──────────────────────────────────────────────────


def _tdc_values(**overrides: object) -> list[object | None]:
    headers = form_definition("tdc_data_model")["headerRows"][0]
    values: list[object | None] = [None] * len(headers)
    labeled: dict[str, object] = {
        "实例号": "90000101",
        "流程名": "T2发布-组件A",
        "流水单号": "F999X-3D-0001",
        "发布属性": "T2发布",
        "申请人": "测试员甲",
        "部门": "内饰科",
        "申请日期": "2026-08-20 10:00:00",
        "项目/车型": "F999X",
        "零件号": "27000001",
        "数模号": "27000001",
        "零件名称": "组件A",
        "对应IA号": "IA000001",
        "EWO/SOR号": "EWO-000001",
        "状态": "审批中",
    }
    labeled.update(overrides)
    for label, value in labeled.items():
        values[headers.index(label)] = value
    return values


def test_dimensions_from_tdc_adds_grouping_fields_without_changing_stage() -> None:
    definition = form_definition("tdc_data_model")
    dimensions, dates = _dimensions_from_tdc(_tdc_values(), definition)

    # 原 stage 语义不变，旧筛选/历史对照继续可用。
    assert dimensions["stage"] == "F999X"
    assert dimensions["dataSource"] == attribution.PROJECT_PART
    assert dimensions["vehicle"] == "F999X"
    assert dimensions["attribution"] == attribution.ATTRIBUTION_SELF
    assert dates["isCompleted"] is False


def test_dimensions_from_tdc_keeps_architecture_row_on_its_platform() -> None:
    """架构件行即使带 SOR 号，也不得被归到 SOR 里的车型。"""
    definition = form_definition("tdc_data_model")
    dimensions, _ = _dimensions_from_tdc(
        _tdc_values(
            **{
                "项目/车型": "Ar-L",
                "EWO/SOR号": "SGMW-F620S-SOR0064",
                "流水单号": "Ar-L-3D-0071",
            }
        ),
        definition,
    )
    assert dimensions["stage"] == "Ar-L"
    assert dimensions["dataSource"] == attribution.ARCHITECTURE_PART
    assert dimensions["vehicle"] == ""
    assert dimensions["archPlatform"] == "Ar-L"


def _metric_row(project_model: str, status: str) -> dict:
    return {
        "overdueState": "on_time",
        "isCompleted": status == "已完成",
        "dimensions": {
            **attribution.dimension_fields(project_model),
            "stage": project_model,
            "status": status,
        },
    }


def test_data_model_summary_groups_vehicles_and_platforms_side_by_side() -> None:
    rows = [
        _metric_row("F620S", "已完成"),
        _metric_row("F620S", "审批中"),
        _metric_row("Ar-L", "已完成"),
        _metric_row("Ar-L+", "已完成"),
    ]
    summary = _stage_status_summary("tdc_data_model", rows)
    labels = [row["label"] for row in summary["stages"]]
    assert labels == ["F620S · 项目件", "Ar-L · 架构件", "Ar-L+ · 架构件"]
    assert [row["total"] for row in summary["stages"]] == [2, 1, 1]


def test_tdc_sor_stage_summary_is_unchanged() -> None:
    """回归：D5 专属分组不得波及 tdc_sor 的既有观测值分组。"""
    rows = [
        {"overdueState": "on_time", "isCompleted": False,
         "dimensions": {"stage": "F999X", "status": "审批中"}},
        {"overdueState": "overdue", "isCompleted": False,
         "dimensions": {"stage": "F888Y", "status": "审批中"}},
    ]
    summary = _stage_status_summary("tdc_sor", rows)
    assert [row["label"] for row in summary["stages"]] == ["F888Y", "F999X"]


def test_registry_exposes_grouping_dimension_labels_for_d5_only() -> None:
    spec = form_registry.get_form("tdc_data_model")
    assert spec.dimension_label("dataSource") == "数据来源"
    assert spec.dimension_label("vehicle") == "归集车型"
    assert spec.dimension_label("attribution") == "归属方式"
    assert spec.dimension_label("archPlatform") == "架构平台"

    # 其他交付物没有这几个维度，兜底仍是原样回显维度名。
    for form_key in ("tdc_sor", "aras_paa", "aras_ncr_progress", "aras_ncr_detail"):
        other = form_registry.get_form(form_key)
        assert other.dimension_label("dataSource") == "dataSource"


# ── R1 回归：复合分组标签不能当 stage 值查库 ───────────────────────────────


def test_split_group_filters_moves_composite_labels_out_of_stage() -> None:
    sql_filters, labels = _split_data_model_group_filters(
        "tdc_data_model", {"stage": ["F620S · 项目件", "Ar-L"]}
    )
    # 原始 stage 值继续下推 SQL；复合标签留到读取侧。
    assert sql_filters == {"stage": ["Ar-L"]}
    assert labels == ("F620S · 项目件",)


def test_split_group_filters_drops_stage_key_when_only_labels_selected() -> None:
    sql_filters, labels = _split_data_model_group_filters(
        "tdc_data_model", {"stage": ["F620S · 项目件"]}
    )
    assert "stage" not in sql_filters
    assert labels == ("F620S · 项目件",)


def test_split_group_filters_leaves_other_reports_untouched() -> None:
    filters = {"stage": ["F620S · 项目件"]}
    sql_filters, labels = _split_data_model_group_filters("tdc_sor", filters)
    assert sql_filters == filters
    assert labels == ()


def test_filter_rows_by_group_label_matches_chart_buckets() -> None:
    rows = [
        {"dimensions": attribution.dimension_fields("F620S")},
        {"dimensions": attribution.dimension_fields("Ar-L")},
        {"dimensions": attribution.dimension_fields("Ar-L+")},
    ]
    assert len(_filter_rows_by_group_label(rows, ["F620S · 项目件"])) == 1
    assert len(_filter_rows_by_group_label(rows, ["Ar-L · 架构件"])) == 1
    assert len(_filter_rows_by_group_label(rows, ["Ar-L · 架构件", "Ar-L+ · 架构件"])) == 2


# ── R3 回归：旧快照读取兜底要用保留的 values 重算 ──────────────────────────


def test_enrich_data_model_dimensions_recovers_grouping_from_values() -> None:
    values = _tdc_values(**{"项目/车型": "Ar-L"})
    rows = [{"values": values, "dimensions": {"stage": "Ar-L", "status": "审批中"}}]
    enriched = _enrich_data_model_dimensions("tdc_data_model", rows)
    assert enriched[0]["dimensions"]["dataSource"] == attribution.ARCHITECTURE_PART
    assert attribution.group_label(enriched[0]["dimensions"]) == "Ar-L · 架构件"


def test_enrich_data_model_dimensions_overwrites_legacy_sor_attribution() -> None:
    """早期版本写过 SOR 归属的旧快照，读取时按新口径改写。"""
    values = _tdc_values(**{"项目/车型": "Ar-L"})
    rows = [
        {
            "values": values,
            "dimensions": {
                "stage": "Ar-L",
                "dataSource": attribution.ARCHITECTURE_PART,
                "vehicle": "F710S",
                "attribution": "SOR号证据",
                "archPlatform": "Ar-L",
            },
        }
    ]
    enriched = _enrich_data_model_dimensions("tdc_data_model", rows)
    assert enriched[0]["dimensions"]["vehicle"] == ""
    assert enriched[0]["dimensions"]["attribution"] == attribution.ATTRIBUTION_PLATFORM


def test_enrich_data_model_dimensions_keeps_current_grouping() -> None:
    stored = {
        "stage": "Ar-L",
        "dataSource": attribution.ARCHITECTURE_PART,
        "vehicle": "F620S",
        "attribution": attribution.ATTRIBUTION_LEDGER,
        "archPlatform": "Ar-L",
    }
    rows = [{"values": [], "dimensions": dict(stored)}]
    enriched = _enrich_data_model_dimensions("tdc_data_model", rows)
    assert enriched[0]["dimensions"] == stored


def test_enrich_data_model_dimensions_is_noop_for_other_reports() -> None:
    rows = [{"values": [], "dimensions": {"stage": "F999X"}}]
    assert _enrich_data_model_dimensions("tdc_sor", rows)[0]["dimensions"] == {
        "stage": "F999X"
    }


# ── R2 回归：独立表单页展平分组维度 ────────────────────────────────────────


def test_flatten_rows_exposes_grouping_dimensions_for_d5() -> None:
    from plugins.deliverable_forms.backend import flatten_rows

    rows = [
        {
            "rowKey": "r1",
            "values": _tdc_values(),
            "dimensions": {
                **attribution.dimension_fields("Ar-L"),
                "stage": "Ar-L",
                "status": "审批中",
            },
            "submittedDate": "2026-08-20",
            "isCompleted": False,
            "overdueState": "on_time",
        }
    ]
    item = flatten_rows("tdc_data_model", rows)[0]
    assert item["_dataSource"] == "架构件"
    assert item["_archPlatform"] == "Ar-L"
    assert item["_group"] == "Ar-L · 架构件"


def test_flatten_rows_does_not_leak_grouping_fields_to_other_forms() -> None:
    from plugins.deliverable_forms.backend import flatten_rows

    rows = [
        {
            "rowKey": "r1",
            "values": [],
            "dimensions": {"stage": "F999X", "status": "审批中", "dataSource": "项目件"},
            "submittedDate": None,
            "isCompleted": False,
            "overdueState": "unknown",
        }
    ]
    item = flatten_rows("tdc_sor", rows)[0]
    assert "_dataSource" not in item
    assert "_vehicle" not in item
    assert "_group" not in item


def test_d5_page_schema_exposes_group_chart_and_filters() -> None:
    import json
    from pathlib import Path

    page = json.loads(
        (
            Path("plugins") / "deliverable_forms" / "static" / "pages" / "tdc_data_model.json"
        ).read_text(encoding="utf-8")
    )
    filter_keys = {item["key"] for item in page["filters"]}
    assert {"_dataSource", "_archPlatform"} <= filter_keys
    chart_groups = {item["groupBy"] for item in page["charts"]}
    assert "_group" in chart_groups
    # 原有按原始项目/车型的图表保留，旧习惯不丢。
    assert "_stage" in chart_groups


# ── R1 端到端：柱条点击后的行数必须等于柱条 total ──────────────────────────


def test_clicking_a_d5_group_bar_returns_matching_rows(tmp_path) -> None:
    """回归（评审 R1）：把复合标签当 stage 值查库会把明细筛成 0 行。"""
    from core.db_manager import DatabaseManager
    from services.deliverable_form_analysis import (
        DeliverableFormAnalysisService,
        build_form_snapshot,
    )

    db = DatabaseManager(tmp_path / "d5.db")
    db.init_database()
    service = DeliverableFormAnalysisService(db)
    sources = [
        {
            "values": _tdc_values(
                **{"实例号": "90000101", "流水单号": "F620S-3D-0075", "项目/车型": "F620S"}
            ),
            "sheetName": "Sheet1",
        },
        {
            "values": _tdc_values(
                **{
                    "实例号": "90000102",
                    "流水单号": "Ar-L-3D-0002",
                    "项目/车型": "Ar-L",
                    "EWO/SOR号": "SGMW-F620S-SOR0001",
                    "状态": "已完成",
                }
            ),
            "sheetName": "Sheet1",
        },
    ]
    db.publish_deliverable_form_snapshot(
        build_form_snapshot(
            "tdc_data_model",
            sources,
            snapshot_at="2026-10-23T00:00:00Z",
            source_run_id=1,
            source="test",
        )
    )

    payload = service.view("tdc_data_model")
    buckets = payload["charts"]["departmentStatus"]["stages"]
    # 架构件带 F620S 的 SOR 号也仍然是平台分组——这是 SOR 不作为证据的端到端断言。
    assert {bucket["label"]: bucket["total"] for bucket in buckets} == {
        "F620S · 项目件": 1,
        "Ar-L · 架构件": 1,
    }

    for bucket in buckets:
        filtered = service.view("tdc_data_model", filters={"stage": [bucket["label"]]})
        assert filtered["summary"]["total"] == bucket["total"], bucket["label"]

    # 原始项目/车型值仍可照旧筛选（旧深链不失效）。
    assert service.view("tdc_data_model", filters={"stage": ["Ar-L"]})["summary"]["total"] == 1
    assert service.view("tdc_data_model", filters={"stage": ["F620S"]})["summary"]["total"] == 1
