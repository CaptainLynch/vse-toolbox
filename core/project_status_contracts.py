"""Pure project-status presentation rules."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence


MILESTONE_STATUSES = ("未开始", "进行中", "已完成", "已超期")


#: 交付物来源能力元数据（单一来源，无服务依赖）：
#: - syncCapable: 已注册同步契约（连接器 + 更新服务校验齐备），可配置自动同步；
#: - manualOnly: 产品口径固定手工（无来源连接器或来源契约未验证）；
#: - matchKeys: 绑定匹配规则允许的键（更新服务 PATCH 校验与前端编辑器共用，
#:   恒含 reportType；键集必须与连接器实际消费的过滤键保持一致）；
#: - matchFields: (matchKey, 显示名, discovery 过滤名, placeholder)，
#:   驱动绑定编辑器的匹配规则表单与映射证据抓取请求；
#: - evidenceFields: 映射证据抓取所需的来源连接输入
#:   （aras 用设置页已认证 ECM 会话；tdc 需地址与认证请求头）；
#: - syncNote: 静态「更新方式」区域的解释文案。
PROJECT_STATUS_SOURCE_CAPABILITIES: dict[str, dict[str, object]] = {
    "VPI-T2-D1": {
        "sourceType": None,
        "reportType": None,
        "displayName": "内网",
        "syncCapable": False,
        "manualOnly": True,
        "syncNote": "该交付物暂无来源连接器，仅支持手工维护。",
        "syncBlockType": "ManualOnly",
        "blockReason": "该交付物仅允许手工维护",
        "matchKeys": (),
        "matchFields": (),
        "evidenceFields": (),
    },
    "VPI-T2-D2": {
        "sourceType": "tdc",
        "reportType": "sor",
        "displayName": "TDC SOR",
        "syncCapable": True,
        "manualOnly": False,
        "aggregate": True,
        "plannedDateSupported": False,
        "fieldSemantics": {
            "owner": "负责人（报表「申请人」列）",
            "note": "风险备注（「最新完成节点」+「审批状态」组合）",
        },
        "syncNote": None,
        "matchKeys": (
            "processNo", "processType", "carTypeProject", "carTypeProjectId", "applicant", "title",
            "department", "section", "applicationStart", "applicationEnd",
            "partNumber", "partName", "version", "sorNumber", "latestCompletedNode",
            "approvalStatus", "aggregate", "reportType",
        ),
        "matchFields": (
            ("processNo", "SOR 流程编号", "serial_number", "建议优先填写 SOR 流程编号"),
            ("carTypeProject", "车型项目", "car_type_project", "可选，与车型项目 ID 二选一"),
            ("carTypeProjectId", "车型项目 ID", "car_type_project_id", "可选，与车型项目二选一"),
            ("applicant", "申请人", "applicant", "可选"),
            ("title", "标题关键词", "title", "可选"),
            ("partNumber", "零件号", "part_number", "可选"),
            ("sorNumber", "SOR 编号", "sor_number", "可选"),
            ("approvalStatus", "审批状态", "approval_status", "可选"),
        ),
        "evidenceFields": (
            {"name": "base_url", "label": "TDC 地址（仅用于抓取映射证据）", "type": "url", "placeholder": "https://tdc.example.com/"},
            {"name": "auth_mode", "label": "认证方式", "type": "select", "options": ("browser", "password")},
            {"name": "headers", "label": "认证请求头（如 Cookie；仅用于本次抓取，不保存）", "type": "textarea", "placeholder": "Cookie: sid=..."},
        ),
    },
    "VPI-T2-D3": {
        "sourceType": "aras",
        "reportType": "ewo",
        "displayName": "ARAS EWO",
        "syncCapable": True,
        "manualOnly": False,
        "aggregate": True,
        "plannedDateSupported": True,
        "fieldSemantics": {
            "owner": "负责人（「责任工程师名称」列）",
            "plannedDate": "计划完成日期（「要求完成时间」列）",
            "note": "风险备注（「当前阶段未签署的角色&人员」列）",
        },
        "syncNote": None,
        "matchKeys": (
            "ewoNo", "projectCode", "subjectKeyword", "changeType", "changeSubType",
            "area", "state", "rspDepartment", "rspSmt", "submitStart", "submitEnd",
            "modelInfo", "aggregate", "reportType", "contractVersion", "bindingMode", "sourceItemId",
        ),
        "matchFields": (
            ("ewoNo", "EWO 编号", "ewo_no", "建议优先填写 EWO 编号"),
            ("projectCode", "车型项目", "project_code", "可选"),
            ("subjectKeyword", "主题关键词", "subject_keyword", "可选"),
            ("modelInfo", "车型信息", "model_info", "可选"),
        ),
        "evidenceFields": (
            {"name": "base_url", "label": "ECM 地址（仅用于抓取映射证据）", "type": "url", "placeholder": "http://ecm.sgmw.com.cn/innovatorserver"},
        ),
    },
    "VPI-T2-D4": {
        "sourceType": "tdc",
        "reportType": None,
        "displayName": "TDC A 面",
        "syncCapable": False,
        "manualOnly": True,
        "syncNote": "TDC A 面契约验证后将开放自动同步，当前仅支持手工维护。",
        "syncBlockType": "ContractBlocked",
        "blockReason": None,
        "matchKeys": (),
        "matchFields": (),
        "evidenceFields": (),
    },
    "VPI-T2-D5": {
        "sourceType": "tdc",
        "reportType": "data_model",
        "displayName": "数模设计审核流程报表",
        "syncCapable": True,
        "manualOnly": False,
        "aggregate": True,
        "plannedDateSupported": False,
        "fieldSemantics": {
            "owner": "负责人（报表「申请人」列）",
            "note": "风险备注（「待审批人员」列）",
        },
        "syncNote": None,
        "matchKeys": (
            "incident", "applicant", "department", "section",
            "applicationStart", "applicationEnd", "projectModel",
            "partNumber", "modelNumber", "aggregate", "reportType",
        ),
        "matchFields": (
            ("incident", "流程编号", "serial_number", "建议优先填写流程编号"),
            ("applicant", "申请人", "applicant", "可选"),
            ("department", "部门", "department", "可选"),
            ("section", "科室", "section", "可选"),
            ("applicationStart", "申请开始日期", "application_start", "可选（YYYY-MM-DD）"),
            ("applicationEnd", "申请结束日期", "application_end", "可选（YYYY-MM-DD）"),
            ("projectModel", "项目车型", "project_model", "可选"),
            ("partNumber", "零件号", "part_number", "可选"),
            ("modelNumber", "模型编号", "model_number", "可选"),
        ),
        "evidenceFields": (
            {"name": "base_url", "label": "TDC 地址（仅用于抓取映射证据）", "type": "url", "placeholder": "https://tdc.example.com/"},
            {"name": "auth_mode", "label": "认证方式", "type": "select", "options": ("browser", "password")},
            {"name": "headers", "label": "认证请求头（如 Cookie；仅用于本次抓取，不保存）", "type": "textarea", "placeholder": "Cookie: sid=..."},
        ),
    },
}


def project_status_source_capabilities(deliverable_id: str) -> dict[str, object]:
    """返回交付物的来源能力元数据；未注册交付物返回空配置。"""
    return PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id, {
        "sourceType": None,
        "reportType": None,
        "displayName": None,
        "syncCapable": False,
        "manualOnly": True,
        "syncNote": None,
        "matchKeys": (),
        "matchFields": (),
        "evidenceFields": (),
    })


def project_status_default_policy_mode(deliverable_id: str) -> str:
    """新库策略默认模式：契约内交付物默认自动同步，其余手工。"""
    capabilities = project_status_source_capabilities(deliverable_id)
    return "automatic" if capabilities.get("syncCapable") else "manual"


def milestone_display_status(status: object, milestone_date: object, today: date) -> str:
    normalized = {
        "done": "已完成",
        "current": "进行中",
        "planned": "未开始",
        "已达成": "已完成",
        "当前目标节点": "进行中",
        "计划节点": "未开始",
    }.get(str(status), str(status))
    if normalized == "已完成":
        return normalized
    try:
        planned = date.fromisoformat(str(milestone_date))
    except ValueError:
        return normalized if normalized in MILESTONE_STATUSES else "未开始"
    return "已超期" if planned < today else normalized


def current_stage_label(
    milestones: Sequence[Mapping[str, object]],
    today: date,
) -> str:
    valid_milestones = []
    for item in milestones:
        raw_date = item.get("date")
        if raw_date in (None, ""):
            continue
        try:
            parsed = date.fromisoformat(str(raw_date))
            valid_milestones.append((parsed, str(item.get("name", ""))))
        except ValueError:
            continue
    if not valid_milestones:
        return "项目开始 → 项目结束"
    ordered = sorted(valid_milestones, key=lambda item: (item[0].isoformat(), item[1]))
    previous = [item for item in ordered if item[0] <= today]
    following = [item for item in ordered if item[0] > today]
    left = previous[-1][1] if previous else "项目开始"
    right = following[0][1] if following else "项目结束"
    return f"{left} → {right}"
