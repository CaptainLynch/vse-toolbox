# -*- coding: utf-8 -*-
"""Deliverable form registry: the single source of each form's definition.

为什么存在：同一张表单（如 ``tdc_sor``）原先在分析服务、数据库白名单和前端
多处各写一份字典，新增或调整表单要同时改 10 处左右。这里把每张表单的
静态定义集中成一条 ``FormSpec``，``services/deliverable_form_analysis.py`` 与
``core/db_manager.py`` 的旧字典改为从这里推导（变量名保持不变）。

为什么放在 ``core/`` 而不是 ``plugins/deliverable_forms/``：onedir 包里插件以
源码形式放在 exe 旁边、不进 PYZ，旧的 services/core 代码无法在冻结运行时
import 插件目录。等旧调用方全部迁入插件（Sprint 2/3）后再把本模块移进插件。

本模块只放纯数据，不 import 项目内任何模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class FormSpec:
    """Static definition of one deliverable form.

    ``report`` 是报表契约名（``core/report_headers.json`` 的键）。
    ``contact_indexes`` / ``overdue_rule`` 为 ``None`` 表示该表单不适用。
    ``dwell_overdue`` 为真时走 TDC“审批中滞留”逾期口径，不依赖阶段词表。
    ``terminal_statuses`` 是终态：计入总数，但既不算完成也不算未完成，不参与逾期判定。
    ``dimension_labels`` 是归一化维度（status/department/section/model/stage）在该表单
    下的显示名，未列出的用 ``DEFAULT_DIMENSION_LABELS``。
    ``page_column_labels`` 是插件页明细表的列；为空时用 ``key_column_labels``。
    """

    form_key: str
    report: str
    source: str
    title: str
    sheet_names: tuple[str, ...]
    stages: tuple[str, ...] = ()
    contact_indexes: tuple[int, ...] | None = None
    overdue_rule: Mapping[str, int] | None = None
    dwell_overdue: bool = False
    key_column_labels: tuple[str, ...] = ()
    terminal_statuses: frozenset[str] = frozenset()
    dimension_labels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    page_column_labels: tuple[str, ...] = ()

    def dimension_label(self, dimension: str) -> str:
        return self.dimension_labels.get(dimension) or DEFAULT_DIMENSION_LABELS.get(dimension, dimension)

    @property
    def page_columns(self) -> tuple[str, ...]:
        return self.page_column_labels or self.key_column_labels


#: 与旧页面 FORM_FILTER_LABELS 同口径。
DEFAULT_DIMENSION_LABELS: Mapping[str, str] = MappingProxyType({
    "status": "状态",
    "department": "部门",
    "section": "科室 / 区域",
    "model": "车型 / 项目",
    "stage": "阶段 / 节点",
})


# 数模设计审核流程与 SOR 定点流程：审批中且申请日期滞留超过 7 天记为逾期。
TDC_OVERDUE_DWELL_DAYS = 7

FORMS: tuple[FormSpec, ...] = (
    FormSpec(
        form_key="VPI-T2-D3",
        report="ewo",
        source="aras",
        title="EWO 进度",
        sheet_names=("Innovator",),
        stages=("DRAFT1", "DRAFT2", "EDIT1", "EDIT2", "PROC", "IMPL", "CLOSE"),
        contact_indexes=(13,),
        overdue_rule=MappingProxyType({"stageDays": 7, "lateDays": 30}),
        key_column_labels=(
            "EWO编号", "状态", "部门", "责任工程师专业科室", "车型信息",
            "主题", "提交日期", "要求完成时间",
        ),
        dimension_labels=MappingProxyType({"section": "责任科室", "model": "车型", "stage": "审批阶段"}),
    ),
    FormSpec(
        form_key="aras_paa",
        report="paa",
        source="aras",
        title="PAA 进度",
        sheet_names=("Innovator",),
        stages=("DRAFT1", "DRAFT2", "EDIT", "PROC", "IMPL", "CLOSE"),
        contact_indexes=(5, 15),
        overdue_rule=MappingProxyType({"stageDays": 3, "lateDays": 7}),
        key_column_labels=(
            "PAA编号", "状态", "部门", "专业科室", "车型",
            "零件或总成名称", "提交日期", "估计完成日期", "EWO编号",
        ),
        dimension_labels=MappingProxyType({"section": "专业科室", "model": "车型", "stage": "审批阶段"}),
    ),
    FormSpec(
        form_key="aras_ncr_progress",
        report="ncr_progress",
        source="aras",
        title="NCR 审批进度",
        sheet_names=("Sheet1", "Sheet2"),
        # 真实表单完整审批节点（用户 2026-09-02 确认）；非正式阶段由
        # _stage_status_summary 聚合为“其他状态”。
        stages=(
            "PE提交",
            "NCR管理员",
            "PE科室经理",
            "价值工程师",
            "价值工程经理",
            "PE部门总监",
            "财务工程师",
            "平台项目管理专家",
            "海外项目总监",
            "平台首席",
            "动力平台首席",
            "财务部总监",
            "CLOSE",
        ),
        overdue_rule=MappingProxyType({"stageDays": 3, "lateDays": 7}),
        key_column_labels=(
            "NCR编号", "状态", "当前节点及通知时间", "区域", "项目",
            "提交日期", "是否审批完成", "当前审批人滞留天数", "EWO号",
        ),
        dimension_labels=MappingProxyType({"section": "区域", "model": "项目", "stage": "当前节点"}),
    ),
    FormSpec(
        form_key="aras_ncr_detail",
        report="ncr_detail",
        source="aras",
        title="NCR 审批明细",
        sheet_names=("整车", "发动机"),
        key_column_labels=(
            "NCR编号", "状态", "区域", "项目", "零件名称", "零件号",
            "测算工程工装费用(万元)", "批准工程工装费用（万元）",
            "实际工程工装费用(万元)", "测算单件成本变化（元）",
            "批准单件成本变化（元）", "实际单件成本变化（元）", "EWO号",
        ),
        dimension_labels=MappingProxyType({"section": "区域", "model": "项目", "stage": "当前节点"}),
    ),
    FormSpec(
        form_key="tdc_data_model",
        report="tdc_data_model",
        source="tdc",
        title="数模设计审核流程",
        sheet_names=("Sheet1",),
        # 没有固定审批阶段列表；阶段图按观察到的项目/车型值聚合。
        overdue_rule=MappingProxyType(
            {"stageDays": TDC_OVERDUE_DWELL_DAYS, "lateDays": TDC_OVERDUE_DWELL_DAYS}
        ),
        dwell_overdue=True,
        # 旧页面数模表默认显示全部列；插件页只展平这些列（旧页面不受影响）。
        page_column_labels=(
            "流水单号", "状态", "项目/车型", "发布属性", "部门", "申请人", "零件号",
            "零件名称", "申请日期", "最新审批记录", "签署率", "待审批人员",
        ),
        dimension_labels=MappingProxyType({"section": "部门", "model": "发布属性", "stage": "项目 / 车型"}),
    ),
    FormSpec(
        form_key="tdc_sor",
        report="tdc_sor",
        source="tdc",
        title="SOR 定点流程",
        sheet_names=("Sheet1",),
        # 阶段图按观察到的车型项目值聚合。
        contact_indexes=(14,),
        overdue_rule=MappingProxyType(
            {"stageDays": TDC_OVERDUE_DWELL_DAYS, "lateDays": TDC_OVERDUE_DWELL_DAYS}
        ),
        dwell_overdue=True,
        # API 返回中英文混合状态，两种写法都列出。
        terminal_statuses=frozenset({"已终止", "已作废", "Terminated", "Cancelled"}),
        key_column_labels=(
            "流水单号", "审批状态", "车型项目", "类型", "科室", "部门",
            "零件号", "零件名称", "申请日期", "最新完成节点", "SOR号",
        ),
        dimension_labels=MappingProxyType({"section": "科室", "model": "类型", "stage": "车型项目"}),
    ),
)

FORMS_BY_KEY: Mapping[str, FormSpec] = MappingProxyType({spec.form_key: spec for spec in FORMS})
FORM_KEYS = frozenset(FORMS_BY_KEY)


def get_form(form_key: str) -> FormSpec:
    """Return the spec for ``form_key``; raises ``KeyError`` for unknown keys."""
    return FORMS_BY_KEY[form_key]
