# -*- coding: utf-8 -*-
"""Normalized cached analysis for one project-status deliverable.

车型锚点扩展设计（car_type 预留接口）：
当前每个交付物的分析缓存来自单一车型数据源；后续"按车型名称自动同步"落地时，
由定时同步服务按车型调用 TDC 抓取后调用 publish() 写缓存，车型→交付物的映射在目录层维护；
overview/items 的 car_type 参数为本通道预留，现阶段仅透传回显，不参与过滤。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text

# EWO 的业务范围由来源系统的 `_rsp_smt` 字段决定。这里的常量同时供
# Aras 连接器和交付物分析使用，避免查询范围与展示范围出现两套口径。
EWO_DEFAULT_DEPARTMENTS: tuple[str, ...] = (
    "车身科",
    "车体科",
    "外饰科",
    "内饰科",
    "车体架构集成科",
)
EWO_STAGES: tuple[str, ...] = (
    "open",
    "draft1",
    "draft2",
    "edit1",
    "edit2",
    "proc",
    "impl",
    "close",
)
EWO_ACTIVE_STAGES: tuple[str, ...] = (
    "draft1",
    "draft2",
    "edit1",
    "edit2",
    "proc",
    "impl",
)
EWO_TERMINAL_STAGE = "close"
EWO_IGNORED_STAGE = "open"
_EWO_SOURCE_TYPES = frozenset({"aras", "ewo", "aras_ewo", "aras/ewo"})
_EWO_STAGE_FILTERS = frozenset((*EWO_STAGES, "all"))

# 科室合并后 `_rsp_smt` 混杂多变，默认范围改按上级部门字段（`_rsp_department`）
# 的包含式关键词匹配；该常量同时供 Aras 连接器生成 LIKE 查询与本地范围判定，
# 是唯一口径来源。
EWO_DEPARTMENT_KEYWORDS: tuple[str, ...] = (
    "车体工程",
    "外饰",
    "内饰",
)

# 图表自定义标签的候选字段中文显示名；未映射的键原样展示。
EWO_FIELD_LABELS: dict[str, str] = {
    "department": "科室",
    "_rsp_smt": "科室",
    "source_department": "部门",
    "_rsp_department": "部门",
    "owner": "负责人",
    "_rsp_name": "负责人",
    "created_by_id__keyed_name": "起草人",
    "model_info": "车型",
    "_modelinfo": "车型",
    "title": "标题",
    "_subject": "标题",
    "source_status": "源状态",
    "state": "状态",
    "source_stage": "阶段",
    "planned_date": "计划完成",
    "_required_date": "要求日期",
}

# extra_fields 快照的安全边界：敏感键名一律不入库，裸 GUID 值无分组价值。
_EXTRA_FIELD_LIMIT = 60
_EXTRA_VALUE_LIMIT = 200
_SENSITIVE_KEY_NAMES = frozenset({
    "authorization", "cookie", "token", "apikey", "sid", "sessionid",
    "arasauth", "jsessionid", "csrf", "secret", "password",
    "credential", "credentialref",
})
_BARE_GUID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_MODEL_MATCH_MODES = frozenset({"fuzzy", "exact"})

# 图表标签分组定义（值映射）边界：多对一归并、未命中三态、数量上限。
_CHART_GROUP_RULES_LIMIT = 20
_CHART_GROUP_MEMBERS_LIMIT = 200
_CHART_UNMATCHED_MODES = frozenset({"keep", "other", "hide"})
_CHART_UNGROUPED_BUCKET = "未分组"

# 自定义图表标签允许绑定的标准缓存列；extra_fields 键在其之上动态并入。
_CHART_STANDARD_FIELDS: tuple[str, ...] = (
    "department",
    "owner",
    "title",
    "source_department",
    "model_info",
    "source_status",
    "source_stage",
    "planned_date",
    "actual_date",
)

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "item_key": (
        "incident", "processNo", "formId", "processInstanceId", "_no", "id",
        "itemId", "itemNumber",
        "code", "number", "no", "documentNo", "partNo",
        "编号", "单号", "零件号", "记录编号", "实例号", "流水单号",
        "EWO编号", "PAA编号", "SOR号",
    ),
    "item_number": (
        "incident", "processNo", "_no", "itemNumber", "displayNumber", "formId",
        "processInstanceId", "documentNo", "number", "no",
        "编号", "单号", "记录编号", "实例号", "流水单号", "EWO编号", "PAA编号", "SOR号",
    ),
    "title": (
        "title", "name", "subject", "_subject", "itemName", "documentName", "partName",
        "名称", "标题", "主题", "任务名称", "零件名称", "流程名", "报表名称",
        "processName", "projectName",
    ),
    "department": (
        "department", "responsibleDepartment", "responsibleDept", "ownerDepartment",
        "dept", "deptName", "sectionName", "section", "_rsp_smt",
        "科室", "部门", "责任部门", "负责科室",
    ),
    "owner": (
        "owner", "responsiblePerson", "assignee", "handler", "负责人", "责任人", "处理人",
        "申请人", "申请者", "责任工程师名称", "applicant", "startUserName",
        "currentApprover", "currentApproverName", "rsp_name", "_rsp_name",
    ),
    "pending_signers": (
        "pendingSigners", "pendingApprovers", "待签署人员", "待审批人员", "当前待办人",
        "当前阶段未签署的角色&人员", "当前审批人", "currentTodoUser",
        "currentTodoName", "currentApprover", "currentApproverName",
    ),
    "status": (
        "status", "state", "workflowState", "approvalStatus", "状态", "审批状态", "流程状态",
    ),
    "source_department": (
        "_rsp_department", "部门", "责任部门", "所属部门",
    ),
    "model_info": (
        "_modelinfo", "modelInfo", "model_info", "车型",
    ),
    "planned_date": (
        "plannedDate", "dueDate", "deadline", "planFinishDate", "targetDate",
        "_required_date", "applicationDate", "applyDate",
        "计划完成", "计划完成日期", "到期日期", "截止日期", "申请日期",
    ),
    "actual_date": (
        "actualDate", "completedDate", "finishDate", "实际完成", "实际完成日期", "完成日期",
    ),
}

_COMPLETED_STATUSES = frozenset({
    "completed", "complete", "done", "closed", "approved", "released",
    "已完成", "完成", "已关闭", "已批准", "已审批", "已发布", "通过",
})


def is_ewo_source_type(source_type: object) -> bool:
    """Return whether an explicit source type is an EWO analysis source."""
    normalized = str(source_type or "").strip().casefold()
    return normalized in _EWO_SOURCE_TYPES


def normalize_ewo_stage(value: object) -> str | None:
    """Normalize one EWO lifecycle state to the eight canonical stage names.

    Aras currently returns uppercase state values. Whitespace, underscores and
    hyphens are tolerated for imported/legacy values, but unknown states are
    deliberately left unmapped so they cannot affect overdue statistics.
    """
    if value in (None, ""):
        return None
    normalized = re.sub(r"[\s_-]+", "", str(value).strip()).casefold()
    aliases = {stage.replace("_", "").casefold(): stage for stage in EWO_STAGES}
    return aliases.get(normalized)


# 待签署人员的条目分隔符：换行、分号、中英文逗号。空格只在下一段以新的
# “ROLE:”前缀开头时才视为分隔，保证历史折叠行与人名内部空格都能正确处理。
_SIGNER_SPLIT_RE = re.compile(r"[\r\n;；,，]+")
_SIGNER_ROLE_RE = re.compile(r"^([^\s:；，,]{1,32})[:：](.*)$", re.DOTALL)
_SIGNER_TOKEN_ROLE_RE = re.compile(r"^[^\s:；，,]{1,32}[:：]")


def _signer_role_person(entry: str) -> tuple[str, str] | None:
    """Split one signer entry into (role, person); empty role means no role."""
    match = _SIGNER_ROLE_RE.match(entry)
    if match is None:
        return ("", entry)
    role = match.group(1).strip()
    person = match.group(2).strip()
    if not person:
        return None
    return (role, person)


def _signer_entries_from_text(text: str) -> list[str]:
    """Split signer text into entries, tolerating legacy whitespace-collapsed lines."""
    entries: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            entries.append(current)
            current = ""

    for chunk in _SIGNER_SPLIT_RE.split(text):
        flush()
        for token in chunk.split():
            if current and not _SIGNER_TOKEN_ROLE_RE.match(token):
                current = f"{current} {token}"
            else:
                flush()
                current = token
    flush()
    return entries


def _signer_pairs(value: object) -> list[tuple[str, str]]:
    """Collect (role, person) pairs from strings, mappings, arrays and JSON text."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        pairs: list[tuple[str, str]] = []
        for key, item in value.items():
            role = str(key).strip()
            if not role:
                continue
            for entry_role, person in _signer_pairs(item):
                pairs.append((entry_role or role, person))
        return pairs
    if isinstance(value, (list, tuple)):
        pairs = []
        for item in value:
            if isinstance(item, Mapping):
                fields = {
                    str(key).strip().casefold(): nested
                    for key, nested in item.items()
                    if isinstance(key, str)
                }
                role = str(fields.get("role") or "").strip()
                for entry_role, person in _signer_pairs(fields.get("person")):
                    pairs.append((entry_role or role, person))
            else:
                pairs.extend(_signer_pairs(str(item)))
        return pairs
    pairs = []
    for entry in _signer_entries_from_text(str(value)):
        pair = _signer_role_person(entry)
        if pair is not None:
            pairs.append(pair)
    return pairs


def normalize_pending_signers(value: object) -> str:
    """Normalize pending signer inputs into one `ROLE:person` line per signer.

    Accepts delimiter-separated strings (newline/semicolon/Chinese-or-English
    comma), `[{role, person}]` arrays, `{role: person}` mappings and their JSON
    string encodings. Blank entries are dropped, identical role/person pairs
    keep their first occurrence, unknown roles are preserved verbatim, and
    entries without any role are kept as-is. The dedicated pending-signer
    aliases are the only input source; the responsible-person field is never a
    fallback.
    """
    if value in (None, ""):
        return ""
    raw: object = value
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        text = raw.strip()
        if text[:1] in ("{", "["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, (Mapping, list)):
                raw = parsed
    normalized: list[str] = []
    seen: set[tuple[str, str]] = set()
    for role, person in _signer_pairs(raw):
        if (role, person) in seen:
            continue
        seen.add((role, person))
        normalized.append(f"{role}:{person}" if role else person)
    return "\n".join(normalized)


def _stage_filter(value: object) -> str | None:
    """Validate/canonicalize a service or API stage filter."""
    if value in (None, ""):
        return None
    text = str(value).strip().casefold()
    if text == "all":
        return "all"
    stage = normalize_ewo_stage(text)
    if stage is None or stage not in _EWO_STAGE_FILTERS:
        raise ValueError("unsupported stage filter")
    return stage


def _filter_values(values: object, *, kind: str) -> tuple[str, ...]:
    """Normalize a bounded multi-value filter without ever building SQL text."""
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values = [values]
    else:
        try:
            raw_values = list(values)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(f"{kind} filter must be a sequence") from exc
    if len(raw_values) > 20:
        raise ValueError(f"{kind} filter accepts at most 20 values")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        value = str(raw).strip()
        if not value:
            continue
        if len(value) > 120:
            raise ValueError(f"{kind} filter value is too long")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"{kind} filter contains control characters")
        if kind == "stage":
            value = _stage_filter(value) or ""
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if kind == "stage" and "all" in seen:
        return ("all",)
    return tuple(normalized)


def _department_filters(
    department: str | None = None,
    departments: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Prefer the new multi-value contract while retaining the old argument."""
    values: object = departments if departments is not None else department
    return _filter_values(values, kind="department")


def _stage_filters(
    stage: str | None = None,
    stages: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Prefer the new multi-value contract while retaining the old argument."""
    values: object = stages if stages is not None else stage
    return _filter_values(values, kind="stage")


def _item_source_type(item: Mapping[str, Any], source_type: object = None) -> object:
    stored = item.get("source_type")
    return stored if stored not in (None, "") else source_type


def _item_stage(item: Mapping[str, Any], source_type: object = None) -> str | None:
    if not is_ewo_source_type(_item_source_type(item, source_type)):
        return None
    stored = item.get("source_stage")
    if stored not in (None, ""):
        return normalize_ewo_stage(stored)
    return normalize_ewo_stage(item.get("source_status"))


def _parse_extra_fields(raw: object) -> dict[str, str]:
    """把缓存中的 extra_fields_json 解析回字典；损坏内容按空快照处理。"""
    if isinstance(raw, Mapping):
        return {str(k): str(v) for k, v in raw.items() if str(v or "").strip()}
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if isinstance(key, str) and str(value or "").strip()
    }


def _department_in_default_scope(value: object) -> bool:
    """默认范围：部门字段包含任一关键词（大小写不敏感子串）即命中。"""
    text = str(value or "").strip().casefold()
    if not text:
        return False
    return any(keyword.casefold() in text for keyword in EWO_DEPARTMENT_KEYWORDS)


def _model_matches(value: object, model: str, model_match: str) -> bool:
    """车型查找：fuzzy 为大小写不敏感子串包含，exact 为去空白全等。"""
    if model_match not in _MODEL_MATCH_MODES:
        raise ValueError("unsupported model match")
    query = str(model or "").strip()
    if not query:
        return True
    stored = str(value or "").strip()
    if not stored:
        return False
    if model_match == "exact":
        return stored == query
    return query.casefold() in stored.casefold()


def _item_is_in_scope(
    item: Mapping[str, Any],
    *,
    source_type: object = None,
    department: str | None = None,
    departments: Sequence[str] | None = None,
    stage: str | None = None,
    stages: Sequence[str] | None = None,
    model: str | None = None,
    model_match: str = "fuzzy",
) -> bool:
    department_values = _department_filters(department, departments)
    if department_values and str(item.get("department") or "未归属") not in department_values:
        return False
    is_ewo = is_ewo_source_type(_item_source_type(item, source_type))
    # 显式科室筛选优先于部门默认范围；未显式筛选时 EWO 按部门关键词圈定，
    # 且对所有 stage 取值（含 all）生效。
    if is_ewo and not department_values and not _department_in_default_scope(
        item.get("source_department")
    ):
        return False
    # 车型过滤先于阶段分支：EWO 默认阶段分支会直接 return，不能吞掉该条件。
    if model is not None and not _model_matches(item.get("model_info"), model, model_match):
        return False
    stage_values = _stage_filters(stage, stages)
    if stage_values and stage_values != ("all",):
        return is_ewo and _item_stage(item, source_type) in stage_values
    if is_ewo and not stage_values:
        current_stage = _item_stage(item, source_type)
        return current_stage in (*EWO_ACTIVE_STAGES, EWO_TERMINAL_STAGE)
    return True


def _normalized_key(value: object) -> str:
    return re.sub(r"[^\w]+", "", str(value), flags=re.UNICODE).casefold()


def _safe_text(value: object, *, limit: int) -> str:
    return redact_sensitive_text(value, limit=limit, collapse_newlines=True).strip()


def _field_value_with_key(
    row: Mapping[str, Any],
    logical_name: str,
    mapping: Mapping[str, object],
) -> tuple[object | None, str | None]:
    """返回字段值及其真正命中的原始行键（用于 extra_fields 排除已消费键）。"""
    requested = mapping.get(logical_name)
    if isinstance(requested, str) and requested in row:
        return row.get(requested), requested
    normalized = {_normalized_key(key): key for key in row if isinstance(key, str)}
    for alias in _FIELD_ALIASES[logical_name]:
        actual = normalized.get(_normalized_key(alias))
        if actual is not None:
            return row.get(actual), actual
    return None, None


def _field_value(
    row: Mapping[str, Any],
    logical_name: str,
    mapping: Mapping[str, object],
) -> object | None:
    return _field_value_with_key(row, logical_name, mapping)[0]


def _extra_fields_snapshot(
    row: Mapping[str, Any],
    consumed_keys: set[str],
) -> dict[str, str]:
    """捕获标准字段之外的原始行参数快照（图表自定义标签的数据来源）。

    安全边界：键数上限 60（按行键插入顺序先到先得）；键名命中敏感集合或
    值为裸 GUID 的键跳过；值统一脱敏并截断；空值不入快照。
    """
    extra: dict[str, str] = {}
    for key, value in row.items():
        if len(extra) >= _EXTRA_FIELD_LIMIT:
            break
        if not isinstance(key, str) or key in consumed_keys:
            continue
        if re.sub(r"[^a-z0-9]", "", key.casefold()) in _SENSITIVE_KEY_NAMES:
            continue
        text = _safe_text(value, limit=_EXTRA_VALUE_LIMIT)
        if not text or _BARE_GUID_RE.fullmatch(text):
            continue
        extra[key] = text
    return extra


def _iso_date(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    if not text:
        return None
    match = re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(0)).isoformat()
    except ValueError:
        return None


def _snapshot_time(value: object) -> str:
    if isinstance(value, datetime):
        current = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        try:
            current = datetime.fromisoformat(text)
        except ValueError:
            current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _completed(status: str, actual_date: str | None) -> bool:
    normalized = status.strip().casefold()
    if normalized in _COMPLETED_STATUSES:
        return True
    return any(token in normalized for token in ("完成", "关闭", "批准", "发布")) or bool(actual_date)


def _alert_type(
    item: Mapping[str, Any],
    today: date,
    due_soon_days: int = 7,
    *,
    source_type: object = None,
) -> tuple[str | None, int | None]:
    if is_ewo_source_type(_item_source_type(item, source_type)):
        # EWO 的状态机决定完成与否；不得用通用状态文本或日期把 open、
        # close、未知阶段误报为逾期。
        stage = _item_stage(item, source_type)
        if stage not in EWO_ACTIVE_STAGES:
            return None, None
    elif bool(item.get("is_completed")):
        return None, None
    planned = _iso_date(item.get("planned_date"))
    if planned is None:
        return "missing_due_date", None
    planned_date = date.fromisoformat(planned)
    delta = (planned_date - today).days
    if delta < 0:
        return "overdue", abs(delta)
    if delta <= due_soon_days:
        return "due_soon", delta
    return None, delta


def normalize_analysis_rows(
    rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, object] | None = None,
    *,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Extract only the bounded fields needed by the business analysis cache."""
    checked_mapping = mapping or {}
    normalized_source_type = str(source_type or "").strip().casefold()
    ewo_source = is_ewo_source_type(normalized_source_type)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        consumed_keys: set[str] = set()
        raw_key, key_consumed = _field_value_with_key(row, "item_key", checked_mapping)
        if key_consumed:
            consumed_keys.add(key_consumed)
        number_value, number_consumed = _field_value_with_key(
            row, "item_number", checked_mapping
        )
        if number_consumed:
            consumed_keys.add(number_consumed)
        title_value, title_consumed = _field_value_with_key(row, "title", checked_mapping)
        if title_consumed:
            consumed_keys.add(title_consumed)
        department_value, department_consumed = _field_value_with_key(
            row, "department", checked_mapping
        )
        if department_consumed:
            consumed_keys.add(department_consumed)
        owner_value, owner_consumed = _field_value_with_key(row, "owner", checked_mapping)
        if owner_consumed:
            consumed_keys.add(owner_consumed)
        signers_value, signers_consumed = _field_value_with_key(
            row, "pending_signers", checked_mapping
        )
        if signers_consumed:
            consumed_keys.add(signers_consumed)
        status_value, status_consumed = _field_value_with_key(row, "status", checked_mapping)
        if status_consumed:
            consumed_keys.add(status_consumed)
        planned_value, planned_consumed = _field_value_with_key(
            row, "planned_date", checked_mapping
        )
        if planned_consumed:
            consumed_keys.add(planned_consumed)
        actual_value, actual_consumed = _field_value_with_key(
            row, "actual_date", checked_mapping
        )
        if actual_consumed:
            consumed_keys.add(actual_consumed)
        source_department_value, source_department_consumed = _field_value_with_key(
            row, "source_department", checked_mapping
        )
        if source_department_consumed:
            consumed_keys.add(source_department_consumed)
        model_value, model_consumed = _field_value_with_key(row, "model_info", checked_mapping)
        if model_consumed:
            consumed_keys.add(model_consumed)

        display_number = _safe_text(number_value or raw_key or "", limit=200)
        title = _safe_text(title_value or raw_key or "未命名任务", limit=240)
        department = _safe_text(department_value or "未归属", limit=120)
        owner = _safe_text(owner_value or "", limit=120)
        # 待签署人员只来自专用字段；先规范化为 ROLE:person 行再做脱敏，
        # 且不折叠换行，保证“每条一行”的输出契约在缓存中保留。
        pending_signers = redact_sensitive_text(
            normalize_pending_signers(signers_value),
            limit=500,
        ).strip()
        status = _safe_text(status_value or "", limit=120)
        source_stage = normalize_ewo_stage(status) if ewo_source else None
        stage_attention = ewo_source and source_stage is None
        planned_date = _iso_date(planned_value)
        actual_date = _iso_date(actual_value)
        # 部门与车型为 EWO 默认范围与车型查找的原始依据；extra_fields 只保留
        # 标准字段未消费的参数，供自定义图表标签按任意上游字段分组。
        source_department = _safe_text(source_department_value or "", limit=120)
        model_info = _safe_text(model_value or "", limit=120)
        extra_fields = _extra_fields_snapshot(row, consumed_keys)
        fingerprint_source = "|".join(
            (str(raw_key or ""), title, department, owner, planned_date or "")
        )
        item_key = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        if item_key in seen:
            continue
        seen.add(item_key)
        normalized.append({
            "item_key": item_key,
            "display_number": display_number,
            "title": title,
            "department": department or "未归属",
            "owner": owner,
            "pending_signers": pending_signers,
            "source_department": source_department,
            "model_info": model_info,
            "extra_fields": extra_fields,
            "source_status": status,
            "source_stage": source_stage,
            "stage_attention": stage_attention,
            "source_type": normalized_source_type,
            "is_completed": (
                source_stage == EWO_TERMINAL_STAGE
                if ewo_source
                else _completed(status, actual_date)
            ),
            "planned_date": planned_date,
            "actual_date": actual_date,
        })
    return normalized


def summarize_analysis_items(
    items: Sequence[Mapping[str, Any]],
    *,
    snapshot_at: object,
    today: date | None = None,
    source_type: str | None = None,
    department: str | None = None,
    departments: Sequence[str] | None = None,
    stage: str | None = None,
    stages: Sequence[str] | None = None,
    model: str | None = None,
    model_match: str = "fuzzy",
) -> dict[str, Any]:
    department_values = _department_filters(department, departments)
    stage_values = _stage_filters(stage, stages)
    current = today or date.today()
    department_counts: dict[str, dict[str, int]] = {}
    completed_count = overdue_count = due_soon_count = missing_count = 0
    selected_items = [
        item for item in items
        if _item_is_in_scope(
            item,
            source_type=source_type,
            departments=department_values,
            stages=stage_values,
            model=model,
            model_match=model_match,
        )
    ]
    for item in selected_items:
        item_department = str(item.get("department") or "未归属")
        counts = department_counts.setdefault(
            item_department,
            {"total": 0, "completed": 0, "incomplete": 0},
        )
        counts["total"] += 1
        if bool(item.get("is_completed")):
            completed_count += 1
            counts["completed"] += 1
        else:
            counts["incomplete"] += 1
            alert_type, _ = _alert_type(item, current, source_type=source_type)
            if alert_type == "overdue":
                overdue_count += 1
            elif alert_type == "due_soon":
                due_soon_count += 1
            elif alert_type == "missing_due_date":
                missing_count += 1
    total_count = len(selected_items)
    return {
        "total_count": total_count,
        "completed_count": completed_count,
        "incomplete_count": total_count - completed_count,
        "overdue_count": overdue_count,
        "due_soon_count": due_soon_count,
        "missing_due_date_count": missing_count,
        "department_counts": department_counts,
        "snapshot_at": _snapshot_time(snapshot_at),
    }


class ProjectStatusDeliverableAnalysisService:
    def __init__(self, db: DatabaseManager, *, clock: Any = None) -> None:
        self.db = db
        self._clock = clock or date.today

    def publish(
        self,
        deliverable_id: str,
        source_run_id: int,
        rows: Sequence[Mapping[str, Any]],
        *,
        snapshot_at: object,
        mapping: Mapping[str, object] | None = None,
        source_type: str | None = None,
    ) -> None:
        items = normalize_analysis_rows(rows, mapping, source_type=source_type)
        snapshot = summarize_analysis_items(
            items,
            snapshot_at=snapshot_at,
            today=self._clock(),
            source_type=source_type,
        )
        self.db.replace_project_status_analysis_cache(
            deliverable_id,
            source_run_id,
            snapshot,
            items,
        )

    def overview(
        self,
        deliverable_id: str,
        *,
        trend_limit: int = 8,
        car_type: str | None = None,
        model: str | None = None,
        model_match: str = "fuzzy",
    ) -> dict[str, Any]:
        if model_match not in _MODEL_MATCH_MODES:
            raise ValueError("unsupported model match")
        deliverable = self._deliverable(deliverable_id)
        rows = self.db.list_project_status_analysis_snapshots(deliverable_id, trend_limit)
        latest = rows[0] if rows else None
        trend = []
        for row in reversed(rows):
            trend.append({
                "snapshotAt": row["snapshot_at"],
                "total": int(row["total_count"]),
                "completed": int(row["completed_count"]),
                "incomplete": int(row["incomplete_count"]),
                "overdue": int(row["overdue_count"]),
                "dueSoon": int(row["due_soon_count"]),
            })
        department_counts: dict[str, Any] = {}
        recalculated: dict[str, Any] | None = None
        cache_items = self._cached_items(deliverable_id, deliverable=deliverable)
        if latest is not None and self._is_ewo_deliverable(deliverable_id, deliverable):
            recalculated = summarize_analysis_items(
                cache_items,
                snapshot_at=latest["snapshot_at"],
                today=self._clock(),
                model=model,
                model_match=model_match,
            )
        if latest is not None:
            try:
                parsed = (
                    recalculated["department_counts"]
                    if recalculated is not None
                    else json.loads(str(latest["department_counts_json"]))
                )
                if isinstance(parsed, dict):
                    department_counts = parsed
            except (TypeError, ValueError):
                department_counts = {}
        summary = None if latest is None else {
            "total": int(latest["total_count"]),
            "completed": int(latest["completed_count"]),
            "incomplete": int(latest["incomplete_count"]),
            "overdue": int(latest["overdue_count"]),
            "dueSoon": int(latest["due_soon_count"]),
            "missingDueDate": int(latest["missing_due_date_count"]),
        }
        if recalculated is not None:
            summary = {
                "total": int(recalculated["total_count"]),
                "completed": int(recalculated["completed_count"]),
                "incomplete": int(recalculated["incomplete_count"]),
                "overdue": int(recalculated["overdue_count"]),
                "dueSoon": int(recalculated["due_soon_count"]),
                "missingDueDate": int(recalculated["missing_due_date_count"]),
            }
        custom_charts = [
            {
                "label": chart_label["label"],
                "sourceField": chart_label["sourceField"],
                "groups": self._chart_groups_from(
                    cache_items,
                    chart_label["sourceField"],
                    model=model,
                    model_match=model_match,
                    groups=chart_label.get("groups"),
                    unmatched=chart_label.get("unmatched") or "keep",
                ),
            }
            for chart_label in self.chart_labels(deliverable_id)
        ]
        return {
            "deliverable": deliverable,
            "hasCache": latest is not None,
            "snapshotAt": latest["snapshot_at"] if latest else None,
            "summary": summary,
            "departments": department_counts,
            "trend": trend,
            "carType": car_type,
            "customCharts": custom_charts,
        }

    def items(
        self,
        deliverable_id: str,
        *,
        alert: str | None = None,
        department: str | None = None,
        departments: Sequence[str] | None = None,
        stage: str | None = None,
        stages: Sequence[str] | None = None,
        state: str | None = None,
        offset: int = 0,
        limit: int = 200,
        car_type: str | None = None,
        model: str | None = None,
        model_match: str = "fuzzy",
    ) -> dict[str, Any]:
        deliverable = self._deliverable(deliverable_id)
        department_values = _department_filters(department, departments)
        stage_values = _stage_filters(stage, stages)
        if state not in {None, "completed", "incomplete"}:
            raise ValueError("unsupported state filter")
        if alert not in {None, "overdue", "due_soon", "missing_due_date"}:
            raise ValueError("unsupported alert filter")
        if model_match not in _MODEL_MATCH_MODES:
            raise ValueError("unsupported model match")
        if alert is not None and (state is not None or int(offset) != 0):
            raise ValueError("alert filter cannot be combined with state/offset pagination")

        current = self._clock()
        rows = [
            row for row in self._cached_items(deliverable_id, deliverable=deliverable)
            if _item_is_in_scope(
                row,
                departments=department_values,
                stages=stage_values,
                model=model,
                model_match=model_match,
            )
        ]
        if state is not None:
            want_completed = state == "completed"
            rows = [row for row in rows if bool(row.get("is_completed")) is want_completed]

        if alert is not None:
            alert_rows: list[tuple[Mapping[str, Any], str, int | None]] = []
            for row in rows:
                alert_type, days = _alert_type(row, current)
                if alert_type == alert:
                    alert_rows.append((row, alert_type, days))
            alert_rows.sort(key=lambda entry: (
                {"overdue": 0, "due_soon": 1, "missing_due_date": 2}[entry[1]],
                entry[0].get("planned_date") or "9999-12-31",
                entry[0].get("title") or "",
            ))
            total = len(alert_rows)
            bounded_limit = max(1, min(int(limit), 500))
            selected = [
                self._serialize_item(row, alert_type, days)
                for row, alert_type, days in alert_rows[:bounded_limit]
            ]
        else:
            rows.sort(key=lambda row: (
                int(bool(row.get("is_completed"))),
                row.get("planned_date") is not None,
                row.get("planned_date") or "",
                row.get("title") or "",
            ))
            total = len(rows)
            bounded_offset = max(0, int(offset))
            bounded_limit = max(1, min(int(limit), 1000))
            selected = []
            for row in rows[bounded_offset:bounded_offset + bounded_limit]:
                alert_type, days = _alert_type(row, current)
                selected.append(self._serialize_item(row, alert_type, days))

        return {
            "deliverableId": deliverable_id,
            "items": selected,
            "total": total,
            "offset": int(offset),
            "limit": int(limit),
            "carType": car_type,
        }

    def chart_field_candidates(self, deliverable_id: str) -> list[dict[str, Any]]:
        """图表标签可绑定的候选字段：标准列 + extra_fields 键及其非空出现次数。"""
        deliverable = self._deliverable(deliverable_id)
        items = self._cached_items(deliverable_id, deliverable=deliverable)
        counts: dict[str, int] = {}
        for row in items:
            for key in _CHART_STANDARD_FIELDS:
                if str(row.get(key) or "").strip():
                    counts[key] = counts.get(key, 0) + 1
            extra = row.get("extra_fields")
            if isinstance(extra, Mapping):
                for key, value in extra.items():
                    if str(value or "").strip():
                        counts[key] = counts.get(key, 0) + 1
        fields = [
            {"key": key, "label": EWO_FIELD_LABELS.get(key, key), "count": count}
            for key, count in counts.items()
        ]
        fields.sort(key=lambda field: (-field["count"], field["key"]))
        return fields

    def chart_labels(self, deliverable_id: str) -> list[dict[str, Any]]:
        """读取自定义图表标签配置；损坏或缺失的配置按空处理。"""
        raw = self.db.get_app_settings().get(
            f"project_status_chart_labels:{deliverable_id}"
        )
        if not isinstance(raw, list):
            return []
        labels: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            normalized = self._normalize_stored_chart_label(entry, len(labels) + 1)
            if normalized is not None:
                labels.append(normalized)
        return labels

    @staticmethod
    def _normalize_stored_chart_label(
        entry: Mapping[str, Any],
        sort_order: int,
    ) -> dict[str, Any] | None:
        label = str(entry.get("label") or "").strip()
        source_field = str(entry.get("sourceField") or "").strip()
        if not label or not source_field:
            return None
        groups: list[dict[str, Any]] = []
        groups_raw = entry.get("groups")
        if isinstance(groups_raw, (list, tuple)):
            for rule in groups_raw:
                if not isinstance(rule, Mapping):
                    continue
                name = str(rule.get("name") or "").strip()
                if not name:
                    continue
                members_raw = rule.get("members")
                members = [
                    str(member).strip()
                    for member in (members_raw if isinstance(members_raw, (list, tuple)) else ())
                    if str(member or "").strip()
                ]
                groups.append({"name": name, "members": members})
        unmatched = str(entry.get("unmatched") or "keep").strip().casefold()
        if unmatched not in _CHART_UNMATCHED_MODES:
            unmatched = "keep"
        return {
            "label": label,
            "sourceField": source_field,
            "sortOrder": sort_order,
            "groups": groups,
            "unmatched": unmatched,
        }

    def save_chart_labels(
        self,
        deliverable_id: str,
        labels: object,
    ) -> list[dict[str, Any]]:
        """整体替换自定义图表标签；校验失败抛 ValueError 且不落库。"""
        self._deliverable(deliverable_id)
        cleaned = self._validate_chart_labels(deliverable_id, labels)
        self.db.update_app_settings({
            f"project_status_chart_labels:{deliverable_id}": cleaned,
        })
        return self.chart_labels(deliverable_id)

    def chart_groups(
        self,
        deliverable_id: str,
        source_field: str,
        *,
        model: str | None = None,
        model_match: str = "fuzzy",
        groups: object = None,
        unmatched: str = "keep",
    ) -> dict[str, dict[str, int]]:
        """按指定字段分组统计，范围口径与 items() 一致；groups 为值映射规则。"""
        if model_match not in _MODEL_MATCH_MODES:
            raise ValueError("unsupported model match")
        if unmatched not in _CHART_UNMATCHED_MODES:
            raise ValueError("unsupported unmatched mode")
        deliverable = self._deliverable(deliverable_id)
        items = self._cached_items(deliverable_id, deliverable=deliverable)
        if source_field not in self._known_fields(items):
            raise ValueError("unknown chart source field")
        return self._chart_groups_from(
            items,
            source_field,
            model=model,
            model_match=model_match,
            groups=groups,
            unmatched=unmatched,
        )

    def _chart_groups_from(
        self,
        items: Sequence[Mapping[str, Any]],
        source_field: str,
        *,
        model: str | None = None,
        model_match: str = "fuzzy",
        groups: object = None,
        unmatched: str = "keep",
    ) -> dict[str, dict[str, int]]:
        if unmatched not in _CHART_UNMATCHED_MODES:
            raise ValueError("unsupported unmatched mode")
        # 成员查找表：组名隐式自归属（原始值等于组名即归入该组）。
        lookup: dict[str, str] = {}
        for rule in groups or ():
            if not isinstance(rule, Mapping):
                continue
            name = str(rule.get("name") or "").strip()
            if not name:
                continue
            lookup.setdefault(name.casefold(), name)
            members = rule.get("members")
            if isinstance(members, (list, tuple)):
                for member in members:
                    text = str(member or "").strip()
                    if text:
                        lookup.setdefault(text.casefold(), name)
        results: dict[str, dict[str, int]] = {}
        for row in items:
            if not _item_is_in_scope(
                row,
                model=model,
                model_match=model_match,
            ):
                continue
            value = self._row_field_value(row, source_field)
            if not value:
                continue
            key = lookup.get(value.casefold()) if lookup else None
            if key is None:
                if unmatched == "hide":
                    continue
                key = _CHART_UNGROUPED_BUCKET if unmatched == "other" else value
            counts = results.setdefault(
                key,
                {"total": 0, "completed": 0, "incomplete": 0},
            )
            counts["total"] += 1
            if bool(row.get("is_completed")):
                counts["completed"] += 1
            else:
                counts["incomplete"] += 1
        return results

    def _validate_chart_labels(
        self,
        deliverable_id: str,
        labels: object,
    ) -> list[dict[str, str]]:
        if not isinstance(labels, (list, tuple)):
            raise ValueError("labels must be a sequence")
        if len(labels) > 6:
            raise ValueError("at most 6 chart labels")
        deliverable = self._deliverable(deliverable_id)
        known = self._known_fields(self._cached_items(deliverable_id, deliverable=deliverable))
        seen: set[str] = set()
        cleaned: list[dict[str, str]] = []
        for entry in labels:
            if not isinstance(entry, Mapping):
                raise ValueError("chart label must be an object")
            label = str(entry.get("label") or "").strip()
            if not label or len(label) > 40:
                raise ValueError("chart label length must be 1-40")
            if any(ord(char) < 32 or ord(char) == 127 for char in label):
                raise ValueError("chart label contains control characters")
            if label in seen:
                raise ValueError("chart label is duplicated")
            seen.add(label)
            source_field = str(entry.get("sourceField") or "").strip()
            if not source_field or len(source_field) > 80:
                raise ValueError("chart source field length must be 1-80")
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9\u4e00-\u9fff_]*", source_field):
                raise ValueError("chart source field has unsupported characters")
            if source_field not in known:
                raise ValueError("chart source field is not in the cached field set")
            groups = self._validate_chart_groups(entry.get("groups"))
            unmatched = str(entry.get("unmatched") or "keep").strip().casefold() or "keep"
            if unmatched not in _CHART_UNMATCHED_MODES:
                raise ValueError("chart unmatched mode must be keep, other or hide")
            cleaned.append({
                "label": label,
                "sourceField": source_field,
                "groups": groups,
                "unmatched": unmatched,
            })
        return cleaned

    @staticmethod
    def _validate_chart_groups(groups: object) -> list[dict[str, Any]]:
        """校验分组定义：数量/组名/成员边界与跨组一致性，失败抛 ValueError。"""
        if groups in (None, ""):
            return []
        if not isinstance(groups, (list, tuple)):
            raise ValueError("chart groups must be a sequence")
        if len(groups) > _CHART_GROUP_RULES_LIMIT:
            raise ValueError("at most 20 chart group rules per label")
        names: set[str] = set()
        member_owner: dict[str, str] = {}
        total_members = 0
        cleaned: list[dict[str, Any]] = []
        for rule in groups:
            if not isinstance(rule, Mapping):
                raise ValueError("chart group rule must be an object")
            name = str(rule.get("name") or "").strip()
            if not name or len(name) > 40:
                raise ValueError("chart group name length must be 1-40")
            if any(ord(char) < 32 or ord(char) == 127 for char in name):
                raise ValueError("chart group name contains control characters")
            if name.casefold() in names:
                raise ValueError("chart group name is duplicated")
            names.add(name.casefold())
            members_raw = rule.get("members")
            if members_raw is None:
                members_raw = []
            if not isinstance(members_raw, (list, tuple)):
                raise ValueError("chart group members must be a sequence")
            members: list[str] = []
            member_keys: set[str] = set()
            for member in members_raw:
                text = str(member or "").strip()
                if not text:
                    continue
                if len(text) > 80:
                    raise ValueError("chart group member length must be 1-80")
                if any(ord(char) < 32 or ord(char) == 127 for char in text):
                    raise ValueError("chart group member contains control characters")
                if text.casefold() in member_keys:
                    continue
                member_keys.add(text.casefold())
                members.append(text)
            total_members += len(members)
            if total_members > _CHART_GROUP_MEMBERS_LIMIT:
                raise ValueError("at most 200 chart group members per label")
            for member in members:
                owner = member_owner.get(member.casefold())
                if owner is not None and owner != name:
                    raise ValueError("chart group members must not overlap between groups")
                member_owner[member.casefold()] = name
            cleaned.append({"name": name, "members": members})
        for group in cleaned:
            self_key = group["name"].casefold()
            for member in group["members"]:
                if member.casefold() != self_key and member.casefold() in names:
                    raise ValueError("chart group name must not be a member of another group")
        return cleaned

    @staticmethod
    def _known_fields(items: Sequence[Mapping[str, Any]]) -> set[str]:
        known = set(_CHART_STANDARD_FIELDS)
        for row in items:
            extra = row.get("extra_fields")
            if isinstance(extra, Mapping):
                known.update(str(key) for key in extra.keys() if isinstance(key, str))
        return known

    @staticmethod
    def _row_field_value(row: Mapping[str, Any], source_field: str) -> str:
        if source_field in _CHART_STANDARD_FIELDS:
            return str(row.get(source_field) or "").strip()
        extra = row.get("extra_fields")
        if isinstance(extra, Mapping):
            return str(extra.get(source_field) or "").strip()
        return ""

    @staticmethod
    def _is_ewo_deliverable(deliverable_id: str, deliverable: Mapping[str, Any]) -> bool:
        if deliverable_id != "VPI-T2-D3":
            return False
        source = re.sub(r"[\s_-]+", "", str(deliverable.get("source") or "")).casefold()
        return source == "arasewo"

    def _cached_items(
        self,
        deliverable_id: str,
        *,
        deliverable: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Read current items and apply the narrow legacy ARAS EWO fallback in memory."""
        if deliverable is None:
            deliverable = self._deliverable(deliverable_id)
        historical_ewo = self._is_ewo_deliverable(deliverable_id, deliverable)
        rows = self.db.list_project_status_analysis_items(
            deliverable_id,
            stage="all",
            limit=1000,
        )
        normalized: list[dict[str, Any]] = []
        for row in rows:
            current = dict(row)
            current["extra_fields"] = _parse_extra_fields(
                current.get("extra_fields_json")
            )
            stored_source_type = str(current.get("source_type") or "").strip()
            if historical_ewo and (
                not stored_source_type or is_ewo_source_type(stored_source_type)
            ):
                stage = normalize_ewo_stage(
                    current.get("source_stage") or current.get("source_status")
                )
                if not stored_source_type:
                    current["source_type"] = "aras"
                current["source_stage"] = stage
                current["is_completed"] = stage == EWO_TERMINAL_STAGE
            normalized.append(current)
        return normalized

    @staticmethod
    def _serialize_item(
        row: Mapping[str, Any],
        alert_type: str | None,
        days: int | None,
    ) -> dict[str, Any]:
        stage = _item_stage(row)
        is_ewo = is_ewo_source_type(_item_source_type(row))
        return {
            "itemKey": row["item_key"],
            "itemNumber": row.get("display_number") or row["item_key"],
            "title": row["title"],
            "department": row["department"],
            "owner": row["owner"],
            # 存量行可能是历史折叠值，读取时再规范化一次（幂等）。
            "pendingSigners": normalize_pending_signers(row.get("pending_signers")),
            "status": row["source_status"],
            "stage": stage,
            "stageAttention": bool(is_ewo and stage is None),
            "completed": bool(row["is_completed"]),
            "plannedDate": row["planned_date"],
            "actualDate": row["actual_date"],
            "alertType": alert_type,
            "days": days,
            "updatedAt": row["updated_at"],
        }

    def _deliverable(self, deliverable_id: str) -> dict[str, Any]:
        _, _, rows = self.db.get_project_status("VPI-T2")
        for row in rows:
            if str(row["id"]) == deliverable_id:
                return {
                    "id": deliverable_id,
                    "name": str(row["name"]),
                    "status": str(row["status"]),
                    "owner": str(row["owner"]),
                    "source": str(row["source"]),
                }
        raise KeyError(deliverable_id)
