# -*- coding: utf-8 -*-
"""同步记录身份与聚合指纹的共享规范化（纯函数，无 IO）。

连接器（同步执行侧）与映射发现（证据侧）共用同一套身份提取、记录
规范化与指纹算法（GPT 终审任务 3：避免两侧单号排除、截断和指纹口径不一致）。

- 无业务单号的行在两侧一致排除；
- 集合指纹仅使用排序后的单号列表做确定性 JSON 序列化后哈希（记录集合范围稳定性）；
- 内容版本与集合指纹职责分离（同单号内容变化由 aggregate_content_version 捕获，不被幂等误判）；
- 统一生成聚合候选字段拟写入值（与连接器 _aggregate_snapshot 完全同源）；
- 统一计算观测配置签名（config_signature），确保证据与查询目标强绑定。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from core.redaction import redact_sensitive_text
from core.ewo_binding_v2 import normalize_ewo_v2_rule
from core.report_cost_values import cost_note_segments
from services.pagination_integrity import COMPLETE_STOP_REASONS as COMPLETE_RESULT_STOP_REASONS  # noqa: F401
from services.deliverable_form_analysis import normalize_tdc_report_status
from services.project_status_deliverable_analysis import (
    EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION,
)

IDENTITY_FIELDS: tuple[str, ...] = (
    "_no", "formId", "incident", "documentNo", "processInstanceId",
    "processNo", "id", "ewo_no", "item_number", "itemNumber",
    "NCR编号", "ncrNo", "ncr_no",
)

_AGGREGATE_FINGERPRINT_PREFIX = "agg:"
_IDENTITY_MAX_LEN = 1000
MAX_AGGREGATE_RECORDS = 5000
# Only these crawler stop reasons carry an explicit end-of-data proof.
# 权威定义在 services/pagination_integrity（与两个爬虫的生产者同源），此处只做
# 名称保持以兼容既有消费者（连接器 / web 门控）；不要在本文件另立字面集合。

# 查询规则的固定身份合同。这里列的是实际 crawler filter 的 camelCase
# 名称，而不是“看起来像敏感词就丢弃”的模糊规则。凭据、Cookie 等永远
# 不属于规则身份；未知键也不会悄悄改变已批准查询的身份。
_QUERY_RULE_KEYS_BY_SOURCE: dict[str, frozenset[str]] = {
    "tdc": frozenset(
        {
            "reportType", "aggregate", "incident", "applicant", "department",
            "section", "applicationStart", "applicationEnd", "projectModel",
            "partNumber", "modelNumber", "processNo", "processType",
            "carTypeProject", "carTypeProjectId", "title", "partName", "version",
            "sorNumber", "latestCompletedNode", "approvalStatus", "status",
        }
    ),
    "aras": frozenset(
        {
            "reportType", "aggregate", "ewoNo", "projectCode", "subjectKeyword",
            "changeType", "changeSubType", "area", "state", "rspDepartment",
            "rspSmt", "submitStart", "submitEnd", "modelInfo",
            "paaNo", "ncrNo", "projectModel", "projectNames", "department", "sectionCode",
        }
    ),
}


def _canonical_query_value(value: Any) -> Any:
    """Canonicalize only query values, without inspecting names heuristically."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    # Public query builders accept strings. For defensive direct callers, keep
    # a deterministic scalar representation instead of raising during history.
    return str(value).strip() or None


def clean_identity(value: Any) -> str:
    """提取规范化单号字符串（保留完整性，防敏感泄露，不执行 200 字符截断）。"""
    if value is None or isinstance(value, (dict, list, tuple, set, bytes, bytearray)):
        return ""
    text = redact_sensitive_text(value, limit=_IDENTITY_MAX_LEN, collapse_newlines=True).strip()
    return text


def record_identity(row: Mapping[str, Any]) -> str:
    """提取行业务单号（无单号返回空串）。"""
    for field in IDENTITY_FIELDS:
        value = row.get(field)
        if value:
            cleaned = clean_identity(value)
            if cleaned:
                return cleaned
    return ""


_IDENTITY_DIGEST_LEN = 16


def identity_digest(value: str) -> str:
    """单号截断哈希：稳定性基线只落不可逆摘要，不存原始单号明文。

    映射发现两侧（全量取证与轻量采样）必须共用本函数，保证同一单号
    在基线集合与采样集合之间可判定子集关系。
    """
    text = str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_IDENTITY_DIGEST_LEN]


def identified_records(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """按单号识别记录：无单号行一致排除；按单号排序保证重排不变。

    重复单号不静默丢弃（保留全部内容，指纹与风险备注均可见）。
    超限（>MAX_AGGREGATE_RECORDS）时 fail-closed 抛出 ValueError。
    """
    if len(rows) > MAX_AGGREGATE_RECORDS:
        raise ValueError(
            f"record count {len(rows)} exceeds maximum {MAX_AGGREGATE_RECORDS}"
        )
    identified = [(record_identity(row), dict(row)) for row in rows]
    identified = [(key, row) for key, row in identified if key]
    return sorted(identified, key=lambda item: item[0])


def _content_json(row: Mapping[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def aggregate_fingerprint(
    records: Sequence[tuple[str, Mapping[str, Any]]],
) -> str:
    """记录集合指纹：排序后的单号列表确定性哈希（仅对单号集合敏感，行内容无关）。"""
    identities = sorted(identity for identity, _ in records if identity)
    payload = json.dumps(identities, ensure_ascii=False, separators=(",", ":"))
    return _AGGREGATE_FINGERPRINT_PREFIX + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:32]


def aggregate_content_version(
    records: Sequence[tuple[str, Mapping[str, Any]]],
) -> str:
    """聚合内容版本：与指纹同基线并覆盖行内容（用于幂等去重）。"""
    normalized = sorted(
        (identity, _content_json(row)) for identity, row in records
    )
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return _AGGREGATE_FINGERPRINT_PREFIX + "v" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:32]


def observation_is_aggregate(observation: Mapping[str, Any]) -> bool:
    """判定一条观测记录是否为聚合模式（写入侧使用固定前缀，非猜测）。"""
    key = observation.get("external_key")
    fingerprint = str(observation.get("candidate_fingerprint") or "")
    return not key and fingerprint.startswith(_AGGREGATE_FINGERPRINT_PREFIX)


def compute_config_signature(source_type: str, match_rule: Mapping[str, Any] | None) -> str:
    """计算固定查询合同的规范化签名（不包含凭据或未知配置键）。"""
    if match_rule is not None and not isinstance(match_rule, Mapping):
        raise ValueError("match_rule must be an object")
    rule = match_rule or {}
    source = str(source_type).strip().lower()
    allowed = _QUERY_RULE_KEYS_BY_SOURCE.get(source, frozenset())
    if any(key in rule for key in ('contractVersion', 'bindingMode', 'sourceItemId')):
        if source != 'aras':
            raise ValueError('Versioned EWO rule requires Aras source')
        rule = normalize_ewo_v2_rule(dict(rule))
        allowed = allowed | {'contractVersion', 'bindingMode', 'sourceItemId'}
    cleaned: dict[str, Any] = {}
    for k, v in rule.items():
        key_str = str(k)
        if key_str not in allowed:
            continue
        if key_str == "aggregate":
            if not isinstance(v, bool):
                raise ValueError("match_rule aggregate must be a boolean")
        elif v is not None and not isinstance(v, str):
            # Query builders and persisted bindings use strings for every
            # source-side filter.  Do not stringify lists/dicts/numbers here:
            # that would let malformed rules acquire a misleading signature
            # and could collapse distinct invalid requests onto one identity.
            raise ValueError(f"match_rule field {key_str} must be a string")
        canonical = _canonical_query_value(v)
        if canonical is not None:
            cleaned[key_str] = canonical
    if source == "aras" and cleaned.get("reportType") == "ewo" and cleaned.get("modelInfo"):
        # Model-anchor EWO execution deliberately resolves ewoNo inside the
        # model result set; it is not an effective source-side filter there.
        cleaned.pop("ewoNo", None)
    if (
        source == "aras"
        and cleaned.get("reportType") == "ewo"
        and not str(cleaned.get("rspDepartment") or "").strip()
    ):
        # Aras project-status execution applies this fixed source-side scope
        # when no explicit department filter is configured.  Canonicalize the
        # implicit condition so saved bindings and request-local discovery
        # evidence share one query identity.
        cleaned["rspDepartment"] = EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION
    payload = json.dumps(
        {"source_type": source, "rule": cleaned},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sig:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:28]


def compute_mapping_signature(mapping: Mapping[str, Any] | None) -> str:
    """Return a stable identity for an approved field mapping."""
    payload = json.dumps(
        dict(mapping or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "map:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:28]


def normalize_candidate_value(api_field: str, value: Any) -> str | None:
    """Normalize one candidate with the same scalar/date rules as execution."""
    cleaned = clean_identity(value) or None
    if cleaned is None:
        return None
    if api_field == "plannedDate":
        try:
            return datetime.fromisoformat(cleaned).date().isoformat()
        except ValueError:
            pass
    return cleaned


# 多记录摘要用的状态候选键（按序取首个非空值；G34 备注摘要化）。
# 键序即现场证据优先级：列表接口字段在前，工作簿中文名兜底。
_STATUS_KEYS_BY_REPORT: dict[str, tuple[str, ...]] = {
    "sor": ("processInstanceStatus", "approvalStatus", "审批状态"),
    "data_model": ("status", "状态"),
    "paa": ("state", "current_state__name"),
    "ncr_progress": ("状态", "status"),
    "ncr_detail": ("状态", "status"),
    "ewo": ("state", "current_state__name", "current_state__keyed_name"),
}

_UNFILLED_STATUS_LABEL = "未填写"
# 数模已映射状态码（与 normalize_tdc_report_status 同一映射，仅用于识别
# 「未映射码」以便展示 其他(码N)；文本归一本身仍走同一函数，禁止第二套口径）。
_DATA_MODEL_MAPPED_CODES = frozenset({"2", "4"})

_AGGREGATE_NOTE_LIMIT = 1000


def _aggregate_status_label(report: str, row: Mapping[str, Any]) -> str:
    """按报表候选键取首个非空状态并归一为摘要展示文本（空计为「未填写」）。"""
    raw = ""
    for key in _STATUS_KEYS_BY_REPORT.get(report, ()):
        text = clean_identity(row.get(key)).strip()
        if text:
            raw = text
            break
    if not raw:
        return _UNFILLED_STATUS_LABEL
    if report == "data_model":
        # 数字码归一走与连接器/分析同一函数；未映射码诚实披露为 其他(码N)。
        if raw in _DATA_MODEL_MAPPED_CODES:
            return normalize_tdc_report_status("data_model", raw)
        return f"其他(码{raw})"
    return raw


def _aggregate_note_summary(
    identified: Sequence[tuple[str, Mapping[str, Any]]],
    report: str,
) -> dict[str, str | None]:
    """多记录风险备注摘要：状态计数优先完整，费用段按顺序在预算内追加。

    格式：``共 N 条；<状态> X、<状态> Y…``（计数降序、同数按状态名升序）；
    ncr_detail 追加四指标费用合计段。超过 1000 字时先保「共 N 条」与全部
    状态计数完整，再按顺序截费用段（宁可费用段缺失也不截断状态计数；
    状态段本身极长时保持完整，不做字符截断）。
    """
    counts: dict[str, int] = {}
    for _identity, row in identified:
        label = _aggregate_status_label(report, row)
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    head = f"共 {len(identified)} 条；" + "、".join(
        f"{status} {count}" for status, count in ordered
    )
    if report != "ncr_detail":
        return {"note": head}
    summary = head
    segments = cost_note_segments(
        (row for _identity, row in identified),
        total_count=len(identified),
    )
    for segment in segments:
        candidate = f"{summary}；{segment}"
        if len(candidate) > _AGGREGATE_NOTE_LIMIT:
            break
        summary = candidate
    return {"note": summary}


def build_aggregate_candidate_values(
    identified: Sequence[tuple[str, Mapping[str, Any]]],
    mapping: Mapping[str, Any],
    *,
    report: str | None = None,
) -> dict[str, str | None]:
    """统一根据规范化记录集与映射生成拟写入字段值（connector 与 preview 唯一来源）。

    ``report``（G34 备注摘要化，过渡语义）：``None`` 时多记录分支保持旧
    明细行为（逐条「单号：卡点信息」以「；」连接、1000 字截断）——历史调用
    方（discovery / ewo_v2）不传即不变；连接器聚合路径接线后总会传报表类型，
    此时多记录分支返回确定性摘要（见 :func:`_aggregate_note_summary`）。
    单记录分支两种取值下行为完全一致。
    """
    if not identified:
        return {}
    if len(identified) == 1:
        row = identified[0][1]
        values: dict[str, str | None] = {}
        for api_field, source_field in mapping.items():
            if api_field == "note" and isinstance(source_field, list):
                chunks = [
                    clean_identity(row.get(str(src)))
                    for src in source_field
                    if isinstance(src, str)
                ]
                joined = "｜".join(chunk for chunk in chunks if chunk)
                values[api_field] = joined[:_IDENTITY_MAX_LEN] or None
                continue
            if not isinstance(source_field, str):
                continue
            values[api_field] = normalize_candidate_value(api_field, row.get(source_field))
        return values

    # 多记录聚合模式：不写 owner/plannedDate，仅聚合 note
    if report is not None:
        return _aggregate_note_summary(identified, report)
    note_sources = mapping.get("note")
    note_sources = [note_sources] if isinstance(note_sources, str) else list(note_sources or [])
    parts: list[str] = []
    for identity, row in identified:
        chunks = [
            clean_identity(row.get(str(src)))
            for src in note_sources
            if isinstance(src, str)
        ]
        chunks = [chunk for chunk in chunks if chunk]
        if chunks:
            parts.append(f"{identity}：{'｜'.join(chunks)}")
    return {"note": "；".join(parts)[:1000]} if parts else {}
