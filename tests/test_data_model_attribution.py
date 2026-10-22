# -*- coding: utf-8 -*-
"""数模设计审核流程（D5）项目件/架构件归集规则的离线测试。

覆盖：脏值归一、来源判定、车型证据提取（SOR 号 > 流水单号 > 平台池）、
旧快照维度兜底、分组标签、实例级汇总口径，以及"只有 D5 改分组、
tdc_sor 等其余报表不变"的回归断言。

另含代码评审（docs/CODE_REVIEW_D5_20261023.md）四项发现的回归测试：
R1 复合分组标签不能当 stage 值查库；R2 独立表单页要展平归集维度；
R3 旧快照读取兜底要用保留的 values 重算；R4 平台池按平台分桶。
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


# ── 车型证据提取 ────────────────────────────────────────────────────────────


def test_extract_vehicle_evidence_prefers_sor_number() -> None:
    assert attribution.extract_vehicle_evidence(
        "SGMW-F710S-SOR0023", "Ar-L-3D-0002"
    ) == ("F710S", attribution.ATTRIBUTION_SOR)


def test_extract_vehicle_evidence_falls_back_to_document_prefix() -> None:
    assert attribution.extract_vehicle_evidence("TBD", "F620S-3D-0028") == (
        "F620S",
        attribution.ATTRIBUTION_DOCUMENT,
    )


def test_extract_vehicle_evidence_ignores_platform_sor_and_bare_documents() -> None:
    """``SGMW-Ar-L-SOR0027`` 与 ``3D-00001181`` 都不构成车型证据。"""
    assert attribution.extract_vehicle_evidence("SGMW-Ar-L-SOR0027", "Ar-L-3D-0079") is None
    assert attribution.extract_vehicle_evidence("EWO-034010", "3D-00001181") is None
    assert attribution.extract_vehicle_evidence("", "") is None


# ── 行级归集 ────────────────────────────────────────────────────────────────


def test_dimension_fields_for_project_part() -> None:
    fields = attribution.dimension_fields("F620S", "EWO-034010", "F620S-3D-0075")
    assert fields == {
        "dataSource": attribution.PROJECT_PART,
        "vehicle": "F620S",
        "attribution": attribution.ATTRIBUTION_SELF,
        "archPlatform": "",
    }


def test_dimension_fields_for_architecture_part_with_evidence() -> None:
    fields = attribution.dimension_fields("Ar-L", "SGMW-F710S-SOR0023", "Ar-L-3D-0002")
    assert fields["dataSource"] == attribution.ARCHITECTURE_PART
    assert fields["vehicle"] == "F710S"
    assert fields["attribution"] == attribution.ATTRIBUTION_SOR
    assert fields["archPlatform"] == "Ar-L"


def test_dimension_fields_for_architecture_part_without_evidence_goes_to_pool() -> None:
    fields = attribution.dimension_fields("Ar-L+", "EWO-030090", "Ar-L+-3D-0005")
    assert fields["vehicle"] == ""
    assert fields["attribution"] == attribution.ATTRIBUTION_POOL
    assert fields["archPlatform"] == "Ar-L+"


# ── 旧快照兜底与分组标签 ────────────────────────────────────────────────────


def test_resolve_dimensions_derives_from_legacy_stage_only_snapshot() -> None:
    """旧快照只有 stage 键，读取侧按同一套纯函数兜底，无需回填。"""
    legacy = {"stage": "Ar-L", "status": "已完成"}
    resolved = attribution.resolve_dimensions(legacy)
    assert resolved["dataSource"] == attribution.ARCHITECTURE_PART
    assert resolved["attribution"] == attribution.ATTRIBUTION_POOL
    assert resolved["archPlatform"] == "Ar-L"


def test_group_label_keeps_vehicle_and_source_together() -> None:
    project = attribution.group_label(
        attribution.dimension_fields("F620S", "", "F620S-3D-0075")
    )
    architecture = attribution.group_label(
        attribution.dimension_fields("Ar-L", "SGMW-F620S-SOR0064", "Ar-L-3D-0071")
    )
    pool = attribution.group_label(attribution.dimension_fields("Ar-L", "TBD", "Ar-L-3D-0002"))
    assert project == "F620S · 项目件"
    assert architecture == "F620S · 架构件"
    assert pool == "待归属 Ar-L · 架构件"


def test_group_sort_key_places_pool_last_and_pairs_same_vehicle() -> None:
    labels = ["待归属 Ar-L · 架构件", "F710S · 项目件", "F620S · 架构件", "F620S · 项目件"]
    assert sorted(labels, key=attribution.group_sort_key) == [
        "F620S · 项目件",
        "F620S · 架构件",
        "F710S · 项目件",
        "待归属 Ar-L · 架构件",
    ]


# ── 实例级汇总 ──────────────────────────────────────────────────────────────


def _row(stage: str, status: str, instance: str, ewo: str = "", document: str = "") -> dict:
    return {
        "instance": instance,
        "status": status,
        "dimensions": {
            **attribution.dimension_fields(stage, ewo, document),
            "stage": stage,
        },
    }


def test_summarize_instances_counts_instances_not_rows() -> None:
    rows = [
        _row("F620S", "已完成", "I1"),
        _row("F620S", "已完成", "I1"),  # 同一实例的第二行，不得重复计数
        _row("F620S", "审批中", "I2"),
        _row("Ar-L", "已完成", "I3", ewo="SGMW-F620S-SOR0064"),
    ]
    groups = attribution.summarize_instances(rows)
    by_label = {group["label"]: group for group in groups}
    assert by_label["F620S · 项目件"]["total"] == 2
    assert by_label["F620S · 项目件"]["completed"] == 1
    assert by_label["F620S · 项目件"]["active"] == 1
    assert by_label["F620S · 架构件"]["total"] == 1


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


def test_summarize_instances_lets_evidence_win_over_pool_within_instance() -> None:
    """同一实例多行 EWO 号时，有证据的行把该实例从平台池拉出来。"""
    rows = [
        _row("Ar-L", "已完成", "I1", ewo="TBD", document="Ar-L-3D-0045"),
        _row("Ar-L", "已完成", "I1", ewo="SGMW-F710S-SOR0023", document="Ar-L-3D-0045"),
    ]
    groups = attribution.summarize_instances(rows)
    assert len(groups) == 1
    assert groups[0]["vehicle"] == "F710S"
    assert groups[0]["attribution"] == attribution.ATTRIBUTION_SOR


def test_summarize_vehicles_keeps_platform_pool_out_of_vehicle_total() -> None:
    rows = [
        _row("F620S", "已完成", "I1"),
        _row("Ar-L", "已完成", "I2", ewo="SGMW-F620S-SOR0064"),
        _row("Ar-L", "已完成", "I3", ewo="TBD", document="Ar-L-3D-0002"),
    ]
    vehicles = attribution.summarize_vehicles(rows)
    assert [item["vehicle"] for item in vehicles] == ["F620S"]
    assert vehicles[0]["total"] == 2  # 项目件 + 证据归属的架构件
    assert {part["dataSource"] for part in vehicles[0]["parts"]} == {"项目件", "架构件"}


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


def test_dimensions_from_tdc_adds_attribution_fields_without_changing_stage() -> None:
    definition = form_definition("tdc_data_model")
    dimensions, dates = _dimensions_from_tdc(_tdc_values(), definition)

    # 原 stage 语义不变，旧筛选/历史对照继续可用。
    assert dimensions["stage"] == "F999X"
    assert dimensions["dataSource"] == attribution.PROJECT_PART
    assert dimensions["vehicle"] == "F999X"
    assert dimensions["attribution"] == attribution.ATTRIBUTION_SELF
    assert dates["isCompleted"] is False


def test_dimensions_from_tdc_attributes_architecture_row_via_sor() -> None:
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
    assert dimensions["vehicle"] == "F620S"
    assert dimensions["archPlatform"] == "Ar-L"


def _metric_row(project_model: str, status: str, ewo: str = "", document: str = "") -> dict:
    return {
        "overdueState": "on_time",
        "isCompleted": status == "已完成",
        "dimensions": {
            **attribution.dimension_fields(project_model, ewo, document),
            "stage": project_model,
            "status": status,
        },
    }


def test_data_model_summary_groups_project_and_architecture_under_one_vehicle() -> None:
    rows = [
        _metric_row("F620S", "已完成", document="F620S-3D-0075"),
        _metric_row("F620S", "审批中", document="F620S-3D-0076"),
        _metric_row("Ar-L", "已完成", ewo="SGMW-F620S-SOR0064"),
        _metric_row("Ar-L", "已完成", ewo="TBD", document="Ar-L-3D-0002"),
    ]
    summary = _stage_status_summary("tdc_data_model", rows)
    labels = [row["label"] for row in summary["stages"]]
    assert labels == ["F620S · 项目件", "F620S · 架构件", "待归属 Ar-L · 架构件"]
    assert summary["stages"][0]["total"] == 2
    assert summary["stages"][1]["total"] == 1
    assert summary["unrecognizedStageCount"] == 0


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


def test_registry_exposes_attribution_dimension_labels_for_d5_only() -> None:
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
        "tdc_data_model", {"stage": ["F620S · 架构件"]}
    )
    assert "stage" not in sql_filters
    assert labels == ("F620S · 架构件",)


def test_split_group_filters_leaves_other_reports_untouched() -> None:
    filters = {"stage": ["F620S · 项目件"]}
    sql_filters, labels = _split_data_model_group_filters("tdc_sor", filters)
    assert sql_filters == filters
    assert labels == ()


def test_filter_rows_by_group_label_matches_chart_buckets() -> None:
    rows = [
        {"dimensions": attribution.dimension_fields("F620S", "", "F620S-3D-0075")},
        {"dimensions": attribution.dimension_fields("Ar-L", "SGMW-F620S-SOR0001", "")},
        {"dimensions": attribution.dimension_fields("Ar-L", "TBD", "Ar-L-3D-0002")},
    ]
    kept = _filter_rows_by_group_label(rows, ["F620S · 项目件"])
    assert len(kept) == 1
    kept = _filter_rows_by_group_label(rows, ["F620S · 架构件"])
    assert len(kept) == 1
    kept = _filter_rows_by_group_label(rows, ["待归属 Ar-L · 架构件"])
    assert len(kept) == 1
    # 同一车型的两个来源一起选时是并集。
    assert len(_filter_rows_by_group_label(rows, ["F620S · 项目件", "F620S · 架构件"])) == 2


# ── R3 回归：旧快照读取兜底要用保留的 values 重算 ──────────────────────────


def test_enrich_data_model_dimensions_recovers_evidence_from_values() -> None:
    definition = form_definition("tdc_data_model")
    values = _tdc_values(
        **{
            "项目/车型": "Ar-L",
            "EWO/SOR号": "SGMW-F620S-SOR0001",
            "流水单号": "Ar-L-3D-0002",
        }
    )
    rows = [
        {
            "values": values,
            "dimensions": {"stage": "Ar-L", "status": "审批中"},
        }
    ]
    enriched = _enrich_data_model_dimensions("tdc_data_model", rows)
    assert enriched[0]["dimensions"]["vehicle"] == "F620S"
    assert enriched[0]["dimensions"]["attribution"] == attribution.ATTRIBUTION_SOR
    assert attribution.group_label(enriched[0]["dimensions"]) == "F620S · 架构件"


def test_enrich_data_model_dimensions_keeps_stored_values() -> None:
    """已有归集键的快照不被重算覆盖（避免新旧口径互相打架）。"""
    stored = {
        "stage": "Ar-L",
        "dataSource": attribution.ARCHITECTURE_PART,
        "vehicle": "F710S",
        "attribution": attribution.ATTRIBUTION_SOR,
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


# ── R4 回归：平台池按平台分桶 ──────────────────────────────────────────────


def test_summarize_instances_keeps_pool_platforms_separate() -> None:
    rows = [
        _row("Ar-L", "已完成", "i1", ewo="TBD", document="Ar-L-3D-0002"),
        _row("Ar-L+", "已完成", "i2", ewo="EWO-030090", document="Ar-L+-3D-0005"),
    ]
    groups = attribution.summarize_instances(rows)
    assert len(groups) == 2
    assert {group["archPlatform"] for group in groups} == {"Ar-L", "Ar-L+"}
    assert {group["label"] for group in groups} == {
        "待归属 Ar-L · 架构件",
        "待归属 Ar-L+ · 架构件",
    }
    # 平台池仍不并入任何车型合计。
    assert attribution.summarize_vehicles(rows) == []


# ── R2 回归：独立表单页展平归集维度 ────────────────────────────────────────


def test_flatten_rows_exposes_attribution_dimensions_for_d5() -> None:
    from plugins.deliverable_forms.backend import flatten_rows

    rows = [
        {
            "rowKey": "r1",
            "values": _tdc_values(),
            "dimensions": {
                **attribution.dimension_fields("Ar-L", "SGMW-F620S-SOR0001", "Ar-L-3D-0002"),
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
    assert item["_vehicle"] == "F620S"
    assert item["_attribution"] == attribution.ATTRIBUTION_SOR
    assert item["_archPlatform"] == "Ar-L"
    assert item["_group"] == "F620S · 架构件"


def test_flatten_rows_does_not_leak_attribution_fields_to_other_forms() -> None:
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
    assert {"_dataSource", "_vehicle"} <= filter_keys
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
    assert {bucket["label"]: bucket["total"] for bucket in buckets} == {
        "F620S · 项目件": 1,
        "F620S · 架构件": 1,
    }

    for bucket in buckets:
        filtered = service.view("tdc_data_model", filters={"stage": [bucket["label"]]})
        assert filtered["summary"]["total"] == bucket["total"], bucket["label"]

    # 原始项目/车型值仍可照旧筛选（旧深链不失效）。
    assert service.view("tdc_data_model", filters={"stage": ["Ar-L"]})["summary"]["total"] == 1
    assert service.view("tdc_data_model", filters={"stage": ["F620S"]})["summary"]["total"] == 1

