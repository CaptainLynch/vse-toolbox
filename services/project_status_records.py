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
from services.pagination_integrity import COMPLETE_STOP_REASONS as COMPLETE_RESULT_STOP_REASONS  # noqa: F401
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


def build_aggregate_candidate_values(
    identified: Sequence[tuple[str, Mapping[str, Any]]],
    mapping: Mapping[str, Any],
) -> dict[str, str | None]:
    """统一根据规范化记录集与映射生成拟写入字段值（connector 与 preview 唯一来源）。"""
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
