"""Pure project-status presentation rules."""

from __future__ import annotations

from datetime import date
import json
from typing import Mapping, Sequence, TypedDict


MILESTONE_STATUSES = ("未开始", "进行中", "已完成", "已超期")


class DeliverableLink(TypedDict, total=False):
    """单一关联注册表条目：归档任务 ↔ 目录条目 ↔ 项目状态交付物 ↔ 表单。"""

    catalog_id: str
    deliverable_id: str | None
    display_code: str | None
    form_key: str


#: 单一关联注册表（纯常量，不 import 任何上层模块）：job_key → 关联四元组。
#: - catalog_id：_DELIVERABLES_CATALOG 目录条目 id；
#: - deliverable_id：项目状态交付物 id；
#: - display_code：对外展示的 DEL 编码；
#: - form_key：统一表单分析 form_key。
#: ARCHIVE_JOB_CONTRACTS / JOB_FORM_KEYS / DELIVERABLE_FORM_LINKS 及
#: catalog/任务列表/associations 的关联字段均从本表派生，
#: 一致性由 tests/test_deliverable_registry.py 锁定。
DELIVERABLE_LINK_REGISTRY: dict[str, DeliverableLink] = {
    "aras_ewo": {
        "catalog_id": "aras-ewo",
        "deliverable_id": "VPI-T2-D3",
        "display_code": "DEL-003",
        "form_key": "VPI-T2-D3",
    },
    "aras_paa": {
        "catalog_id": "aras-paa",
        "deliverable_id": "VPI-T2-D6",
        "display_code": "DEL-006",
        "form_key": "aras_paa",
    },
    "aras_ncr_progress": {
        "catalog_id": "aras-ncr-progress",
        "deliverable_id": "VPI-T2-D7",
        "display_code": "DEL-007",
        "form_key": "aras_ncr_progress",
    },
    "aras_ncr_detail": {
        "catalog_id": "aras-ncr-detail",
        "deliverable_id": "VPI-T2-D8",
        "display_code": "DEL-008",
        "form_key": "aras_ncr_detail",
    },
    "tdc_data_model": {
        "catalog_id": "tdc-data-model",
        "deliverable_id": "VPI-T2-D5",
        "display_code": "DEL-005",
        "form_key": "tdc_data_model",
    },
    "tdc_sor": {
        "catalog_id": "tdc-sor",
        "deliverable_id": "VPI-T2-D2",
        "display_code": "DEL-002",
        "form_key": "tdc_sor",
    },
}


def find_registry_entry_by_job_key(job_key: str) -> DeliverableLink | None:
    """按归档任务 job_key 反查注册表；模板派生的自定义任务查不到返回 None。"""
    return DELIVERABLE_LINK_REGISTRY.get(str(job_key or ""))


def find_registry_entry_by_catalog_id(catalog_id: str) -> DeliverableLink | None:
    """按目录条目 catalog_id 反查注册表；无关联返回 None。"""
    for entry in DELIVERABLE_LINK_REGISTRY.values():
        if entry["catalog_id"] == str(catalog_id or ""):
            return entry
    return None


def find_registry_entry_by_deliverable_id(deliverable_id: str) -> DeliverableLink | None:
    """按项目状态交付物 id 反查注册表；未关联交付物（如 D1/D4）返回 None。"""
    target = str(deliverable_id or "")
    if not target:
        return None
    for entry in DELIVERABLE_LINK_REGISTRY.values():
        if entry["deliverable_id"] == target:
            return entry
    return None


def deliverable_display_state(
    binding_mode: str,
    binding_enabled: bool,
    binding_sync_state: str,
    last_success_at: object | None,
    analysis_summary: Mapping[str, object] | None,
    form_summary: Mapping[str, object] | None,
    aggregate: bool,
    status_baseline: str,
    *,
    form_snapshot_driven: bool = False,
) -> tuple[str, str, str]:
    """交付物展示状态机（纯函数）：四输入七态输出。

    输入：绑定 mode/enabled/last_success_at/sync_state、分析与表单快照
    摘要、aggregate 标志与持久化 status 基准值。输出 (state, label,
    effective_status) 三元组，web/app.py 与前端共用同一口径。

    - 数值仅在 manual/paused/snapshot 三态展示；其余状态显示状态标签，
      避免"默认自动但尚未同步"的交付物展示编造进度。
    - 有效快照选择：分析快照优先；表单快照兜底仅限非聚合绑定（聚合
      绑定只信任分析快照链路——GPT 终审 E：前后端换绑隔离一致）。
    - 暂停 = 曾成功同步过（deliverable 手工列持有可信同步值）；从未
      同步（无论是否残留独立快照或失败痕迹）一律待配置。
    - form_snapshot_driven（外部快照驱动的交付物，如 D6-D8）先于 mode
      判定：有最新有效表单快照（total>0）即快照态（沿用快照换算）；
      无快照或 total=0 为待同步（不展示编造数值）。
    """
    display_summary = analysis_summary or (None if aggregate else form_summary)
    total = int(display_summary.get("total") or 0) if display_summary else None

    if form_snapshot_driven:
        driven_total = int(display_summary.get("total") or 0) if display_summary else 0
        if driven_total > 0:
            state, label = "snapshot", "快照同步"
        else:
            state, label = "pending_first_sync", "待同步"
    elif str(binding_mode) not in ("automatic", "hybrid"):
        state, label = "manual", "手工维护"
    elif not binding_enabled:
        if last_success_at:
            state, label = "paused", "已暂停"
        else:
            state, label = "pending_config", "待配置"
    elif total is None:
        sync_state = str(binding_sync_state or "idle")
        if sync_state in ("failed", "needs_attention"):
            state, label = "sync_failed", "同步失败"
        elif sync_state == "running":
            state, label = "pending_first_sync", "同步中"
        else:
            state, label = "pending_first_sync", "待首次同步"
    elif total <= 0:
        state, label = "no_source_records", "无来源记录"
    else:
        state, label = "snapshot", "快照同步"

    # 快照态的有效状态换算（与前端 deliverableFormDisplay 同规则）。
    effective_status = str(status_baseline)
    if state == "snapshot" and display_summary:
        if total and int(display_summary.get("completed") or 0) >= total:
            effective_status = "已完成"
        elif int(display_summary.get("overdue") or 0) > 0:
            effective_status = "已逾期"
        else:
            effective_status = "进行中"
    return state, label, effective_status


# These are deliberately user-facing strings.  The API exposes the reason
# alongside ``manualEditable`` so clients can explain why a row is locked.
PROJECT_STATUS_MAPPED_READ_ONLY_REASON = "已配置外部来源映射，需通过同步结果维护"
PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON = "外部来源映射规则无效，已禁止手工编辑"
PROJECT_STATUS_FORM_SNAPSHOT_READ_ONLY_REASON = "外部快照驱动，状态由归档快照自动映射"

_PROJECT_STATUS_EWO_V2_KEYS = frozenset(
    {"contractVersion", "bindingMode", "sourceItemId"}
)
_PROJECT_STATUS_MAPPING_LIST_FIELDS = frozenset({"note"})

_TEXT_LIMITS = {
    "external_key": 200,
    "match_rule": 4000,
    "mapping": 4000,
}


def _has_control_chars(val: str) -> bool:
    for ch in val:
        if ord(ch) < 32 or (127 <= ord(ch) <= 159):
            return True
    return False


def _project_status_decode_object(raw: object) -> tuple[dict[str, object] | None, bool]:
    """Decode configured JSON while distinguishing empty defaults from errors."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}, False
    if isinstance(raw, str):
        if len(raw) > _TEXT_LIMITS["match_rule"] or _has_control_chars(raw):
            return None, True
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None, True
    if not isinstance(raw, Mapping):
        return None, True
    try:
        encoded = json.dumps(raw, ensure_ascii=False)
        if len(encoded) > _TEXT_LIMITS["match_rule"]:
            return None, True
    except (TypeError, ValueError):
        return None, True
    return dict(raw), False


def _project_status_editability(
    manual_editable: bool,
    reason: str | None = None,
) -> dict[str, object]:
    return {"manualEditable": manual_editable, "readOnlyReason": reason}


def project_status_manual_editability(
    binding: Mapping[str, object] | None,
    *,
    deliverable_id: str | None = None,
) -> dict[str, object]:
    """Classify a binding without treating mode/enabled as a record target.

    Empty/default configuration and valid filter-only rules remain editable.
    A target key, aggregate selector, or validated EWO v2 selection is mapped;
    malformed nonempty content fails closed.  外部快照驱动（formSnapshotDriven）
    的交付物（D6-D8）一律不可手工编辑——其状态由归档表单快照自动映射。
    """
    if binding is None:
        if str(deliverable_id or "").strip() in _form_snapshot_driven_ids():
            return _project_status_editability(
                False, PROJECT_STATUS_FORM_SNAPSHOT_READ_ONLY_REASON
            )
        return _project_status_editability(True)
    outer = dict(binding)
    nested = outer.get("binding")
    if isinstance(nested, Mapping):
        binding = dict(nested)
        binding.setdefault(
            "deliverable_id",
            outer.get("deliverable_id", outer.get("deliverableId")),
        )
    else:
        binding = outer

    resolved_deliverable_id = str(
        deliverable_id
        or binding.get("deliverable_id", binding.get("deliverableId"))
        or ""
    ).strip()
    if resolved_deliverable_id in _form_snapshot_driven_ids():
        return _project_status_editability(
            False, PROJECT_STATUS_FORM_SNAPSHOT_READ_ONLY_REASON
        )

    external_key = binding.get("external_key", binding.get("externalKey"))
    if external_key is not None and not isinstance(external_key, str):
        return _project_status_editability(
            False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
        )
    if isinstance(external_key, str):
        if len(external_key) > _TEXT_LIMITS["external_key"] or _has_control_chars(external_key):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )
    has_external_key = bool(isinstance(external_key, str) and external_key.strip())
    raw_rule = binding.get("match_rule_json", binding.get("matchRule"))
    raw_mapping = binding.get("mapping_json", binding.get("mapping"))
    rule, rule_invalid = _project_status_decode_object(raw_rule)
    mapping, mapping_invalid = _project_status_decode_object(raw_mapping)
    if rule_invalid or mapping_invalid or rule is None or mapping is None:
        return _project_status_editability(
            False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
        )
    if not rule and not mapping:
        return _project_status_editability(
            not has_external_key,
            None if not has_external_key else PROJECT_STATUS_MAPPED_READ_ONLY_REASON,
        )

    deliverable_id = binding.get("deliverable_id", binding.get("deliverableId"))
    if isinstance(deliverable_id, str) and deliverable_id.strip():
        capabilities = PROJECT_STATUS_SOURCE_CAPABILITIES.get(deliverable_id)
        raw_match_keys = (capabilities or {}).get("matchKeys", ())
        allowed_match_keys = frozenset(
            key for key in (raw_match_keys if isinstance(raw_match_keys, (tuple, list, set, frozenset)) else ())
            if isinstance(key, str)
        )
        expected_report_type = (capabilities or {}).get("reportType")
        if (
            "reportType" in rule
            and rule["reportType"] != expected_report_type
        ):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )
    else:
        all_keys: list[str] = []
        for capabilities in PROJECT_STATUS_SOURCE_CAPABILITIES.values():
            val = capabilities.get("matchKeys")
            if isinstance(val, (tuple, list, set, frozenset)):
                all_keys.extend(k for k in val if isinstance(k, str))
        allowed_match_keys = frozenset(all_keys)

        report_types = frozenset(
            capabilities["reportType"]
            for capabilities in PROJECT_STATUS_SOURCE_CAPABILITIES.values()
            if isinstance(capabilities.get("reportType"), str)
        )
        report_type = rule.get("reportType")
        if "reportType" in rule and (
            not isinstance(report_type, str) or report_type not in report_types
        ):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )
    if any(key not in allowed_match_keys for key in rule):
        return _project_status_editability(
            False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
        )

    all_semantic_fields: list[str] = []
    for capabilities in PROJECT_STATUS_SOURCE_CAPABILITIES.values():
        semantics = capabilities.get("fieldSemantics")
        if isinstance(semantics, Mapping):
            all_semantic_fields.extend(f for f in semantics if isinstance(f, str))
    allowed_mapping_fields = frozenset(all_semantic_fields)
    for field_name, source_field in mapping.items():
        valid_string = isinstance(source_field, str) and bool(source_field.strip())
        valid_note_list = (
            field_name in _PROJECT_STATUS_MAPPING_LIST_FIELDS
            and isinstance(source_field, list)
            and bool(source_field)
            and all(isinstance(item, str) and bool(item.strip()) for item in source_field)
        )
        if field_name not in allowed_mapping_fields or not (valid_string or valid_note_list):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )

    if any(
        (key == "aggregate" and type(value) is not bool)
        or (key != "aggregate" and (not isinstance(value, str) or not value.strip()))
        for key, value in rule.items()
    ):
        return _project_status_editability(
            False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
        )
    if any(
        isinstance(v, str) and _has_control_chars(v)
        for v in rule.values()
    ):
        return _project_status_editability(
            False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
        )
    for v in mapping.values():
        if isinstance(v, str) and _has_control_chars(v):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )
        if isinstance(v, list) and any(isinstance(item, str) and _has_control_chars(item) for item in v):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )
    versioned = bool(_PROJECT_STATUS_EWO_V2_KEYS.intersection(rule))
    if versioned:
        from core.ewo_binding_v2 import normalize_ewo_v2_rule

        try:
            normalize_ewo_v2_rule(rule)
        except (TypeError, ValueError):
            return _project_status_editability(
                False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON
            )
    if versioned or has_external_key or rule.get("aggregate") is True:
        return _project_status_editability(False, PROJECT_STATUS_MAPPED_READ_ONLY_REASON)
    return _project_status_editability(True)


#: 交付物来源能力元数据（单一来源，无服务依赖）：
#: - syncCapable: 已注册同步契约（连接器 + 更新服务校验齐备），可配置自动同步；
#: - manualOnly: 产品口径固定手工（无来源连接器或来源契约未验证）；
#: - matchKeys: 绑定匹配规则允许的键（更新服务 PATCH 校验与前端编辑器共用，
#:   恒含 reportType；键集必须与连接器实际消费的过滤键保持一致）；
#: - matchFields: (matchKey, 显示名, discovery 过滤名, placeholder)，
#:   驱动绑定编辑器的匹配规则表单与映射证据抓取请求；
#: - evidenceFields: 映射证据抓取所需的来源连接输入
#:   （aras 用设置页已认证 ECM 会话；tdc 需地址与认证请求头）；
#: - defaultMapping: 前端预填/向导默认标准字段映射（降低手动配置成本）；
#: - fieldAliases: 常见外部列名/字段别名元组（用于自动从脱敏报告推导映射）；
#: - formSnapshotDriven: 无状态同步连接器、由定时归档的表单快照驱动：
#:   展示状态机直接消费最新有效表单快照（先于 mode 判定），且禁止手工编辑；
#: - countsTowardCompletion: 是否计入阶段完成统计价值态汇总（分母）。
#:   外部快照驱动的交付物（D6-D8）仅展示参考，不进入节点分母。
#: - syncNote: 静态「更新方式」区域的解释文案。
DELIVERABLE_DEFAULT_MAPPINGS: dict[str, dict[str, object]] = {
    "VPI-T2-D2": {
        "owner": "startUserName",
        "note": ["latestCompletedNode", "processInstanceStatus"],
    },
    "VPI-T2-D3": {
        "owner": "_rsp_name",
        "plannedDate": "_required_date",
        "note": ["_subject", "_change_description"],
    },
    "VPI-T2-D5": {
        "owner": "applicant",
        "note": ["latestApproveLog", "status"],
    },
}

DELIVERABLE_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "VPI-T2-D2": {
        "owner": ("startUserName", "applicant", "申请人", "owner", "_owner"),
        "note": ("latestCompletedNode", "processInstanceStatus", "approvalStatus", "最新完成节点", "审批状态", "title", "标题"),
    },
    "VPI-T2-D3": {
        "owner": ("_rsp_name", "责任工程师名称", "_owner", "owner", "起草人", "engineer"),
        "plannedDate": ("_required_date", "要求完成时间", "req_completion_date", "planned_date"),
        "note": ("当前阶段未签署的角色&人员", "当前阶段未签署的角色", "_subject", "_change_description", "主题", "更改描述"),
    },
    "VPI-T2-D5": {
        "owner": ("applicant", "申请人", "owner", "_owner"),
        "note": ("latestApproveLog", "status", "待审批人员", "pendingApprover", "待审批人", "flowStatus", "流程状态"),
    },
}


def get_deliverable_default_mapping(deliverable_id: str) -> dict[str, object]:
    """返回交付物的内置标准映射（如 EWO/SOR/数模）；未配置返回空字典。"""
    mapping = DELIVERABLE_DEFAULT_MAPPINGS.get(str(deliverable_id or ""))
    return dict(mapping) if isinstance(mapping, dict) else {}


def get_deliverable_field_aliases(deliverable_id: str) -> dict[str, tuple[str, ...]]:
    """返回交付物各字段的已知别名元组字典。"""
    aliases = DELIVERABLE_FIELD_ALIASES.get(str(deliverable_id or ""))
    return dict(aliases) if isinstance(aliases, dict) else {}


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
        "defaultMapping": {},
        "fieldAliases": {},
    },
    "VPI-T2-D2": {
        "sourceType": "tdc",
        "reportType": "sor",
        "displayName": "TDC SOR",
        "syncCapable": True,
        "manualOnly": False,
        "aggregate": True,
        "plannedDateSupported": False,
        "defaultMapping": DELIVERABLE_DEFAULT_MAPPINGS["VPI-T2-D2"],
        "fieldAliases": DELIVERABLE_FIELD_ALIASES["VPI-T2-D2"],
        "fieldSemantics": {
            "owner": "负责人（报表「startUserName」「申请人」列）",
            "note": "风险备注（「latestCompletedNode」「processInstanceStatus」「最新完成节点」+「审批状态」组合）",
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
        "defaultMapping": DELIVERABLE_DEFAULT_MAPPINGS["VPI-T2-D3"],
        "fieldAliases": DELIVERABLE_FIELD_ALIASES["VPI-T2-D3"],
        "fieldSemantics": {
            "owner": "负责人（「_rsp_name」「责任工程师名称」列）",
            "plannedDate": "计划完成日期（「_required_date」「要求完成时间」列）",
            "note": "风险备注（「_subject」「_change_description」「当前阶段未签署的角色&人员」列）",
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
        "defaultMapping": {},
        "fieldAliases": {},
    },
    "VPI-T2-D5": {
        "sourceType": "tdc",
        "reportType": "data_model",
        "displayName": "数模设计审核流程报表",
        "syncCapable": True,
        "manualOnly": False,
        "aggregate": True,
        "plannedDateSupported": False,
        "defaultMapping": DELIVERABLE_DEFAULT_MAPPINGS["VPI-T2-D5"],
        "fieldAliases": DELIVERABLE_FIELD_ALIASES["VPI-T2-D5"],
        "fieldSemantics": {
            "owner": "负责人（报表「applicant」「申请人」列）",
            "note": "风险备注（「latestApproveLog」「status」「最新审批记录」「状态」组合）",
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
    # D6-D8：外部快照驱动（PAA 报告 / NCR 审批进度 / NCR 审批明细）。
    # 无状态同步连接器（syncCapable=False，不进同步调度），状态由定时归档
    # 写入的表单快照自动映射（formSnapshotDriven=True）；仅作展示参考，
    # 不计入阶段完成统计分母（countsTowardCompletion=False）。
    "VPI-T2-D6": {
        "sourceType": "aras",
        "reportType": "paa",
        "displayName": "PAA 报告",
        "syncCapable": False,
        "manualOnly": False,
        "formSnapshotDriven": True,
        "countsTowardCompletion": False,
        "syncNote": "该交付物由定时归档的表单快照驱动，状态自动映射，暂无独立状态同步。",
        "matchKeys": (),
        "matchFields": (),
        "evidenceFields": (),
        "defaultMapping": {},
        "fieldAliases": {},
    },
    "VPI-T2-D7": {
        "sourceType": "aras",
        "reportType": "ncr_progress",
        "displayName": "NCR 审批进度",
        "syncCapable": False,
        "manualOnly": False,
        "formSnapshotDriven": True,
        "countsTowardCompletion": False,
        "syncNote": "该交付物由定时归档的表单快照驱动，状态自动映射，暂无独立状态同步。",
        "matchKeys": (),
        "matchFields": (),
        "evidenceFields": (),
        "defaultMapping": {},
        "fieldAliases": {},
    },
    "VPI-T2-D8": {
        "sourceType": "aras",
        "reportType": "ncr_detail",
        "displayName": "NCR 审批明细",
        "syncCapable": False,
        "manualOnly": False,
        "formSnapshotDriven": True,
        "countsTowardCompletion": False,
        "syncNote": "该交付物由定时归档的表单快照驱动，状态自动映射，暂无独立状态同步。",
        "matchKeys": (),
        "matchFields": (),
        "evidenceFields": (),
        "defaultMapping": {},
        "fieldAliases": {},
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


def _form_snapshot_driven_ids() -> frozenset[str]:
    """外部快照驱动交付物 id 集合（formSnapshotDriven 能力标志）。"""
    return frozenset(
        deliverable_id
        for deliverable_id, capabilities in PROJECT_STATUS_SOURCE_CAPABILITIES.items()
        if capabilities.get("formSnapshotDriven") is True
    )


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
