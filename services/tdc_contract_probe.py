# -*- coding: utf-8 -*-
"""
services/tdc_contract_probe.py — TDC 数模同步契约只读证据探测器。

安全约束：
- 不 import Flask，不 import DatabaseManager，不写 project-status 数据库。
- 不负责认证，不发起网络请求。
- 只接收 TDCPagedResult 或标准化 rows，在内存中聚合证据后立即丢弃原始 rows。
- 默认不输出任何原始字段值；分类值需用户显式批准且经脱敏。
- candidate key（formId/incident/documentNo）只输出统计，不输出实际值或 hash。
- 报告禁止包含 base URL、username、password、Cookie、Authorization、token、
  session、header、filter 值、原始行、原始 JSON、traceback。

本模块为纯函数 + 冻结 dataclass，可直接用 fake rows 测试，不访问真实系统。
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.redaction import redact_sensitive_text

# ── 常量 ────────────────────────────────────────────────────────

#: candidate key 字段名（与 tdc_crawler._row_identity data_model 优先级一致）。
CANDIDATE_KEY_FIELDS: tuple[str, ...] = ("formId", "incident", "documentNo")

#: 禁止加入分类值 allowlist 的字段名片段（大小写不敏感）。
#: 含身份标识词干（formid/incident/documentno/applicant/startuser/userid/tel），
#: 防止通过变体名（applicantTel、incidentNo、formIdDesc）绕过精确匹配。
_FORBIDDEN_VALUE_FIELD_FRAGMENTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "cookie",
    "authorization",
    "session",
    "credential",
    "phone",
    "mobile",
    "email",
    "address",
    "idcard",
    "身份证",
    "formid",
    "incident",
    "documentno",
    "applicant",
    "startuser",
    "userid",
    "applicanttel",
    "tel",
)

#: 禁止加入分类值 allowlist 的标识/人员字段名（精确匹配，大小写不敏感）。
_FORBIDDEN_VALUE_FIELD_EXACT: frozenset[str] = frozenset(
    {
        "formid",
        "incident",
        "documentno",
        "applicant",
        "startuser",
        "applicantid",
        "userid",
        "createuser",
        "updateuser",
    }
)

#: external_version 候选字段名模式（仅名称匹配，不决定最终策略）。
_VERSION_FIELD_PATTERNS: tuple[str, ...] = (
    "updatedat",
    "updatetime",
    "modifiedat",
    "modifytime",
    "completedat",
    "completetime",
    "finishdate",
    "requestdate",
    "version",
    "revision",
    "lastmodified",
)

#: 分类值输出上限。
MAX_CATEGORICAL_FIELDS = 5
MAX_CATEGORICAL_VALUES_PER_FIELD = 30
_CATEGORICAL_VALUE_LIMIT = 200

#: 查询上限。
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 2
MAX_MAX_PAGES = 5
DEFAULT_MAX_RECORDS = 200
ABSOLUTE_MAX_RECORDS = 500

#: 报告 schema 版本。
REPORT_SCHEMA_VERSION = 1

#: 报告写入目录（相对于 .runtime）。
REPORT_DIR_NAME = "tdc_contract_probe"

#: 报告中禁止出现的敏感片段模式（写入前全文检查）。
_REPORT_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+", re.IGNORECASE),
    re.compile(r"cookie\s*[:=]", re.IGNORECASE),
    re.compile(r"set-cookie", re.IGNORECASE),
    re.compile(r"secret\s*[:=]", re.IGNORECASE),
    re.compile(r"token\s*[:=]", re.IGNORECASE),
)

#: 报告中禁止出现的具体信息标记（非正则，精确子串检查）。
_REPORT_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "tdc.sgmw.com.cn",
    "account.sgmw.com.cn",
    "username",
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass(frozen=True)
class TDCContractProbeOptions:
    """探测选项。"""

    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = DEFAULT_MAX_PAGES
    max_records: int = DEFAULT_MAX_RECORDS
    stability_check: bool = False
    categorical_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldProfile:
    """单个字段的统计画像。不含任何原始值。"""

    field_name: str
    present_count: int
    non_empty_count: int
    null_count: int
    observed_types: tuple[str, ...]
    distinct_count: int
    duplicate_count: int


@dataclass(frozen=True)
class CandidateKeyProfile:
    """candidate key 字段的统计画像。不含实际值或 hash。"""

    field_name: str
    field_exists: bool
    non_empty_count: int
    distinct_count: int
    duplicate_count: int
    one_per_workflow: bool
    stable_across_reads: bool | None = None


@dataclass(frozen=True)
class StabilityProfile:
    """连续两次读取的稳定性比较。只含计数，不含 key 或差异内容。"""

    stable_count: int = 0
    added_count: int = 0
    removed_count: int = 0
    duplicate_count: int = 0
    conclusion: str = "not_checked"  # stable / unstable / inconclusive / not_checked
    row_count_match: bool = False


@dataclass(frozen=True)
class CategoricalValueSummary:
    """用户批准的分类字段值摘要。每个值经脱敏和限长。"""

    field_name: str
    values: tuple[str, ...]
    truncated: bool = False
    user_approved: bool = True


@dataclass(frozen=True)
class VersionFieldCandidate:
    """external_version 候选字段。只含字段名，不含值。"""

    field_name: str
    category: str  # directly_observed / name_only_candidate / rejected
    reason: str = ""


@dataclass(frozen=True)
class TDCContractProbeResult:
    """完整探测结果。"""

    schema_version: int = REPORT_SCHEMA_VERSION
    generated_at: str = ""
    sampled: bool = True
    report_type: str = "data_model"
    page_count: int = 0
    record_count: int = 0
    truncated: bool = False
    stop_reason: str = ""
    filter_fields_used: tuple[str, ...] = ()
    field_profiles: tuple[FieldProfile, ...] = ()
    candidate_key_profiles: tuple[CandidateKeyProfile, ...] = ()
    stability: StabilityProfile = field(default_factory=StabilityProfile)
    categorical_values: tuple[CategoricalValueSummary, ...] = ()
    version_candidates: tuple[VersionFieldCandidate, ...] = ()
    external_version_strategy: str = "unresolved"
    warnings: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()


# ── 校验 ────────────────────────────────────────────────────────


def validate_options(options: TDCContractProbeOptions) -> None:
    """校验探测选项的安全范围。"""
    if not (1 <= options.page_size <= MAX_PAGE_SIZE):
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if not (1 <= options.max_pages <= MAX_MAX_PAGES):
        raise ValueError(f"max_pages must be between 1 and {MAX_MAX_PAGES}")
    if not (1 <= options.max_records <= ABSOLUTE_MAX_RECORDS):
        raise ValueError(f"max_records must be between 1 and {ABSOLUTE_MAX_RECORDS}")
    if len(options.categorical_fields) > MAX_CATEGORICAL_FIELDS:
        raise ValueError(
            f"at most {MAX_CATEGORICAL_FIELDS} categorical fields allowed"
        )


def _filter_value_non_empty(value: Any) -> bool:
    """判断过滤值是否非空（None 或纯空白视为空）。"""
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return bool(value)


def validate_filters_non_empty(filters: TDCDataModelFiltersLike) -> None:
    """拒绝空过滤条件，防止全量探测。"""
    if filters is None:
        raise ValueError("filters are required; empty filters are not allowed")
    non_empty = [
        name
        for name in _FILTER_FIELD_NAMES
        if _filter_value_non_empty(getattr(filters, name, None))
    ]
    if not non_empty:
        raise ValueError(
            "at least one non-empty filter condition is required; "
            "empty filters would trigger a full scan"
        )


def validate_categorical_fields(
    requested: Sequence[str],
    available_fields: Sequence[str],
) -> tuple[str, ...]:
    """
    校验用户请求的分类字段，返回安全通过的字段名元组。

    - 必须从本次结果实际存在的字段中选择。
    - 最多 MAX_CATEGORICAL_FIELDS 个。
    - 拒绝名称含敏感片段或精确匹配标识/人员字段的字段。
    """
    available = {str(f) for f in available_fields}
    approved: list[str] = []
    for name in requested:
        if name not in available:
            raise ValueError(
                f"categorical field '{name}' is not present in the sample"
            )
        if _is_forbidden_value_field(name):
            raise ValueError(
                f"categorical field '{name}' is not allowed: "
                "contains sensitive, identity, or personnel keywords"
            )
        approved.append(name)
        if len(approved) > MAX_CATEGORICAL_FIELDS:
            raise ValueError(
                f"at most {MAX_CATEGORICAL_FIELDS} categorical fields allowed"
            )
    return tuple(approved)


def _is_forbidden_value_field(field_name: str) -> bool:
    lowered = field_name.lower()
    if lowered in _FORBIDDEN_VALUE_FIELD_EXACT:
        return True
    return any(frag in lowered for frag in _FORBIDDEN_VALUE_FIELD_FRAGMENTS)


# ── profiler 核心 ───────────────────────────────────────────────


def profile_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, FieldProfile], dict[str, set[Any]], dict[str, list[Any]]]:
    """
    对 rows 做字段级统计，返回 (profiles, distinct_values, value_lists)。

    distinct_values 和 value_lists 仅在内存中短暂存在，用于后续分类值提取；
    不写入报告，调用结束后由 GC 回收。
    """
    if not rows:
        return {}, {}, {}

    all_fields: set[str] = set()
    for row in rows:
        all_fields.update(row.keys())

    profiles: dict[str, FieldProfile] = {}
    distinct_values: dict[str, set[Any]] = {}
    value_lists: dict[str, list[Any]] = {}

    for field_name in sorted(all_fields):
        present = 0
        non_empty = 0
        null_count = 0
        types: set[str] = set()
        seen: set[Any] = set()
        duplicates = 0

        for row in rows:
            if field_name in row:
                present += 1
                value = row[field_name]
                if value is None or (isinstance(value, str) and not value.strip()):
                    null_count += 1
                else:
                    non_empty += 1
                    types.add(type(value).__name__)
                    value_key = str(value)
                    if value_key in seen:
                        duplicates += 1
                    else:
                        seen.add(value_key)

        profiles[field_name] = FieldProfile(
            field_name=field_name,
            present_count=present,
            non_empty_count=non_empty,
            null_count=null_count,
            observed_types=tuple(sorted(types)),
            distinct_count=len(seen),
            duplicate_count=duplicates,
        )
        distinct_values[field_name] = seen
        value_lists[field_name] = [
            row.get(field_name) for row in rows if field_name in row
        ]

    return profiles, distinct_values, value_lists


def profile_candidate_keys(
    rows: Sequence[Mapping[str, Any]],
    field_profiles: dict[str, FieldProfile],
) -> tuple[CandidateKeyProfile, ...]:
    """对 formId/incident/documentNo 做 candidate key 统计。"""
    results: list[CandidateKeyProfile] = []
    for key_field in CANDIDATE_KEY_FIELDS:
        if key_field not in field_profiles:
            results.append(
                CandidateKeyProfile(
                    field_name=key_field,
                    field_exists=False,
                    non_empty_count=0,
                    distinct_count=0,
                    duplicate_count=0,
                    one_per_workflow=False,
                )
            )
            continue
        profile = field_profiles[key_field]
        # one_per_workflow: non_empty == distinct（每条记录一个唯一值）。
        one_per = (
            profile.non_empty_count > 0
            and profile.duplicate_count == 0
            and profile.non_empty_count == profile.distinct_count
        )
        results.append(
            CandidateKeyProfile(
                field_name=key_field,
                field_exists=True,
                non_empty_count=profile.non_empty_count,
                distinct_count=profile.distinct_count,
                duplicate_count=profile.duplicate_count,
                one_per_workflow=one_per,
            )
        )
    return tuple(results)


def extract_categorical_values(
    rows: Sequence[Mapping[str, Any]],
    approved_fields: Sequence[str],
) -> tuple[CategoricalValueSummary, ...]:
    """提取用户批准的分类字段值，每个值经脱敏和限长。"""
    summaries: list[CategoricalValueSummary] = []
    for field_name in approved_fields:
        seen: dict[str, str] = {}
        truncated = False
        for row in rows:
            value = row.get(field_name)
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            sanitized = redact_sensitive_text(text, limit=_CATEGORICAL_VALUE_LIMIT)
            if sanitized not in seen:
                if len(seen) >= MAX_CATEGORICAL_VALUES_PER_FIELD:
                    truncated = True
                    break
                seen[sanitized] = sanitized
        summaries.append(
            CategoricalValueSummary(
                field_name=field_name,
                values=tuple(seen.keys()),
                truncated=truncated,
                user_approved=True,
            )
        )
    return tuple(summaries)


def identify_version_candidates(
    field_profiles: dict[str, FieldProfile],
) -> tuple[VersionFieldCandidate, ...]:
    """识别可能的 external_version 字段，分为 directly_observed / name_only_candidate / rejected。"""
    candidates: list[VersionFieldCandidate] = []
    observed_names = {name.lower() for name in field_profiles}
    matched: set[str] = set()

    for field_name, profile in sorted(field_profiles.items()):
        lowered = field_name.lower()
        is_version_name = any(
            pattern in lowered for pattern in _VERSION_FIELD_PATTERNS
        )
        if not is_version_name:
            continue
        matched.add(lowered)

        # rejected: 全空或类型不适用（bool/int 且不含时间含义）。
        if profile.non_empty_count == 0:
            candidates.append(
                VersionFieldCandidate(
                    field_name=field_name,
                    category="rejected",
                    reason="all values null or empty",
                )
            )
        elif profile.observed_types and all(
            t in ("bool",) for t in profile.observed_types
        ):
            candidates.append(
                VersionFieldCandidate(
                    field_name=field_name,
                    category="rejected",
                    reason="type boolean not suitable for version",
                )
            )
        else:
            candidates.append(
                VersionFieldCandidate(
                    field_name=field_name,
                    category="directly_observed",
                    reason="field present with non-empty values",
                )
            )

    # name_only_candidate: 模式匹配但未在样本中观察到。
    for pattern in _VERSION_FIELD_PATTERNS:
        if pattern not in observed_names and pattern not in matched:
            candidates.append(
                VersionFieldCandidate(
                    field_name=pattern,
                    category="name_only_candidate",
                    reason="name matches version pattern but field not observed in sample",
                )
            )

    return tuple(candidates)


def compare_stability(
    first_rows: Sequence[Mapping[str, Any]],
    second_rows: Sequence[Mapping[str, Any]],
    first_truncated: bool,
    second_truncated: bool,
) -> StabilityProfile:
    """
    比较两次读取的稳定性。只输出计数，不输出 key 或差异内容。

    如果任一次读取被分页截断，结论为 inconclusive。
    """
    if first_truncated or second_truncated:
        return StabilityProfile(
            conclusion="inconclusive",
            row_count_match=len(first_rows) == len(second_rows),
        )

    def _key_set(rows: Sequence[Mapping[str, Any]]) -> set[str]:
        keys: set[str] = set()
        for row in rows:
            for kf in CANDIDATE_KEY_FIELDS:
                val = row.get(kf)
                if val is not None and str(val).strip():
                    keys.add(f"{kf}:{val}")
                    break
        return keys

    first_keys = _key_set(first_rows)
    second_keys = _key_set(second_rows)

    stable = first_keys & second_keys
    added = second_keys - first_keys
    removed = first_keys - second_keys

    # duplicate_count: second 中 key 重复的计数。
    second_key_list = []
    for row in second_rows:
        for kf in CANDIDATE_KEY_FIELDS:
            val = row.get(kf)
            if val is not None and str(val).strip():
                second_key_list.append(f"{kf}:{val}")
                break
    dup_count = len(second_key_list) - len(set(second_key_list))

    if not first_keys and not second_keys:
        conclusion = "inconclusive"
    elif added or removed:
        conclusion = "unstable"
    else:
        conclusion = "stable"

    return StabilityProfile(
        stable_count=len(stable),
        added_count=len(added),
        removed_count=len(removed),
        duplicate_count=dup_count,
        conclusion=conclusion,
        row_count_match=len(first_rows) == len(second_rows),
    )


# ── 报告生成与脱敏 ──────────────────────────────────────────────


def build_report(
    rows: Sequence[Mapping[str, Any]],
    options: TDCContractProbeOptions,
    filter_fields_used: Sequence[str],
    paged_result_meta: Mapping[str, Any] | None = None,
    stability_rows: Sequence[Mapping[str, Any]] | None = None,
    stability_truncated: bool = False,
) -> TDCContractProbeResult:
    """
    从 rows 构建完整探测报告。原始 rows 在构建后由调用方丢弃。

    Args:
        rows: 第一次读取的行。
        options: 探测选项。
        filter_fields_used: 使用的过滤字段名（不含值）。
        paged_result_meta: 来自 TDCPagedResult 的元信息（page_count, stop_reason 等）。
        stability_rows: 第二次读取的行（可选）。
        stability_truncated: 第二次读取是否被截断。
    """
    validate_options(options)

    field_profiles, _, _ = profile_rows(rows)
    candidate_keys = profile_candidate_keys(rows, field_profiles)

    # 分类值提取。
    categorical_values: tuple[CategoricalValueSummary, ...] = ()
    if options.categorical_fields:
        approved = validate_categorical_fields(
            options.categorical_fields, list(field_profiles.keys())
        )
        categorical_values = extract_categorical_values(rows, approved)

    # external_version 候选。
    version_candidates = identify_version_candidates(field_profiles)
    has_directly_observed = any(
        c.category == "directly_observed" for c in version_candidates
    )
    strategy = "candidate_identified" if has_directly_observed else "unresolved"

    # 稳定性。
    stability = StabilityProfile()
    if options.stability_check and stability_rows is not None:
        first_truncated = paged_result_meta is not None and bool(
            paged_result_meta.get("truncated", False)
        )
        stability = compare_stability(
            rows, stability_rows, first_truncated, stability_truncated
        )

    # 元信息。
    page_count = 0
    record_count = len(rows)
    truncated = False
    stop_reason = ""
    if paged_result_meta:
        page_count = int(paged_result_meta.get("fetched_pages", 0))
        truncated = bool(paged_result_meta.get("truncated", False))
        stop_reason = str(paged_result_meta.get("stop_reason", ""))

    warnings: list[str] = []
    if truncated:
        warnings.append("sample was truncated by pagination limits")
    if not any(ck.field_exists and ck.non_empty_count > 0 for ck in candidate_keys):
        warnings.append("no candidate key field has non-empty values in the sample")

    return TDCContractProbeResult(
        schema_version=REPORT_SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sampled=True,
        report_type="data_model",
        page_count=page_count,
        record_count=record_count,
        truncated=truncated,
        stop_reason=stop_reason,
        filter_fields_used=tuple(sorted(filter_fields_used)),
        field_profiles=tuple(sorted(field_profiles.values(), key=lambda p: p.field_name)),
        candidate_key_profiles=candidate_keys,
        stability=stability,
        categorical_values=categorical_values,
        version_candidates=version_candidates,
        external_version_strategy=strategy,
        warnings=tuple(warnings),
        unresolved_questions=_build_unresolved_questions(
            candidate_keys, version_candidates, stability
        ),
    )


def _build_unresolved_questions(
    candidate_keys: tuple[CandidateKeyProfile, ...],
    version_candidates: tuple[VersionFieldCandidate, ...],
    stability: StabilityProfile,
) -> tuple[str, ...]:
    questions: list[str] = []
    ready_keys = [ck for ck in candidate_keys if ck.field_exists and ck.one_per_workflow]
    if len(ready_keys) != 1:
        questions.append(
            "which candidate key (formId/incident/documentNo) is the authoritative external key?"
        )
    if not any(c.category == "directly_observed" for c in version_candidates):
        questions.append(
            "no reliable version field observed; what field should serve as external_version?"
        )
    if stability.conclusion in ("unstable", "inconclusive"):
        questions.append(
            "stability check was not conclusive; repeat with larger sample or narrower filters"
        )
    return tuple(questions)


# ── 报告序列化与安全检查 ────────────────────────────────────────


def serialize_report_json(result: TDCContractProbeResult) -> str:
    """将报告序列化为 JSON 字符串。"""
    return json.dumps(_result_to_dict(result), ensure_ascii=False, sort_keys=True, indent=2)


def serialize_report_markdown(result: TDCContractProbeResult) -> str:
    """将报告序列化为 Markdown 字符串。"""
    lines: list[str] = []
    lines.append(f"# TDC 数模同步契约探测报告")
    lines.append("")
    lines.append(f"- schema_version: {result.schema_version}")
    lines.append(f"- generated_at: {result.generated_at}")
    lines.append(f"- sampled: {result.sampled}")
    lines.append(f"- report_type: {result.report_type}")
    lines.append(f"- page_count: {result.page_count}")
    lines.append(f"- record_count: {result.record_count}")
    lines.append(f"- truncated: {result.truncated}")
    lines.append(f"- stop_reason: {result.stop_reason}")
    lines.append(f"- filter_fields_used: {', '.join(result.filter_fields_used) or '(none)'}")
    lines.append(f"- external_version_strategy: {result.external_version_strategy}")
    lines.append("")

    lines.append("## 字段画像")
    lines.append("")
    lines.append("| field | present | non_empty | null | distinct | duplicate | types |")
    lines.append("|---|---|---|---|---|---|---|")
    for p in result.field_profiles:
        lines.append(
            f"| {p.field_name} | {p.present_count} | {p.non_empty_count} | "
            f"{p.null_count} | {p.distinct_count} | {p.duplicate_count} | "
            f"{', '.join(p.observed_types)} |"
        )
    lines.append("")

    lines.append("## Candidate Key 统计")
    lines.append("")
    lines.append("| field | exists | non_empty | distinct | duplicate | one_per_workflow | stable |")
    lines.append("|---|---|---|---|---|---|---|")
    for ck in result.candidate_key_profiles:
        stable = "-" if ck.stable_across_reads is None else str(ck.stable_across_reads)
        lines.append(
            f"| {ck.field_name} | {ck.field_exists} | {ck.non_empty_count} | "
            f"{ck.distinct_count} | {ck.duplicate_count} | {ck.one_per_workflow} | {stable} |"
        )
    lines.append("")

    lines.append("## 稳定性")
    lines.append("")
    s = result.stability
    lines.append(f"- conclusion: {s.conclusion}")
    lines.append(f"- stable_count: {s.stable_count}")
    lines.append(f"- added_count: {s.added_count}")
    lines.append(f"- removed_count: {s.removed_count}")
    lines.append(f"- duplicate_count: {s.duplicate_count}")
    lines.append(f"- row_count_match: {s.row_count_match}")
    lines.append("")

    if result.categorical_values:
        lines.append("## 用户批准的分类字段值")
        lines.append("")
        lines.append("> 这些值是 user-approved categorical evidence，不是最终业务映射。")
        lines.append("")
        for cv in result.categorical_values:
            lines.append(f"### {cv.field_name}")
            lines.append(f"- truncated: {cv.truncated}")
            for v in cv.values:
                lines.append(f"  - {v}")
            lines.append("")
    else:
        lines.append("## 分类字段值")
        lines.append("")
        lines.append("（未选择分类字段）")
        lines.append("")

    lines.append("## external_version 候选")
    lines.append("")
    lines.append("| field | category | reason |")
    lines.append("|---|---|---|")
    for vc in result.version_candidates:
        lines.append(f"| {vc.field_name} | {vc.category} | {vc.reason} |")
    lines.append("")

    if result.warnings:
        lines.append("## 警告")
        lines.append("")
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")

    if result.unresolved_questions:
        lines.append("## 待确认问题")
        lines.append("")
        for q in result.unresolved_questions:
            lines.append(f"- {q}")
        lines.append("")

    return "\n".join(lines)


def check_report_safety(text: str) -> tuple[bool, str | None]:
    """
    对序列化后的报告文本做敏感模式检查。

    Returns:
        (safe, reason) — safe=False 时 reason 描述命中的禁止片段。
    """
    for pattern in _REPORT_FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match:
            return False, f"forbidden pattern matched: {pattern.pattern!r} at offset {match.start()}"
    for substr in _REPORT_FORBIDDEN_SUBSTRINGS:
        if substr in text.lower():
            return False, f"forbidden substring found: {substr!r}"
    return True, None


def save_report(
    result: TDCContractProbeResult,
    output_dir: Path,
) -> tuple[Path, Path] | None:
    """
    将报告保存为 JSON + Markdown。

    写入前对全文做敏感模式检查；发现禁止内容时拒绝保存并记录原因。
    文件名只含 UTC 时间和随机非敏感短标识。

    Returns:
        (json_path, md_path) 或 None（安全检查失败时，safety_reason 含脱敏原因）。
    """
    json_text = serialize_report_json(result)
    md_text = serialize_report_markdown(result)

    safe, reason = check_report_safety(json_text)
    if not safe:
        save_report.safety_reason = reason  # type: ignore[attr-defined]
        return None
    safe, reason = check_report_safety(md_text)
    if not safe:
        save_report.safety_reason = reason  # type: ignore[attr-defined]
        return None
    save_report.safety_reason = None  # type: ignore[attr-defined]

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_id = secrets.token_hex(4)
    stem = f"probe_{timestamp}_{short_id}"

    json_path = output_dir / f"{stem}.json"
    md_path = output_dir / f"{stem}.md"
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    return json_path, md_path


# ── 内部辅助 ────────────────────────────────────────────────────


def _result_to_dict(result: TDCContractProbeResult) -> dict[str, Any]:
    """将冻结 dataclass 转为可 JSON 序列化的 dict。"""
    return {
        "schema_version": result.schema_version,
        "generated_at": result.generated_at,
        "sampled": result.sampled,
        "report_type": result.report_type,
        "page_count": result.page_count,
        "record_count": result.record_count,
        "truncated": result.truncated,
        "stop_reason": result.stop_reason,
        "filter_fields_used": list(result.filter_fields_used),
        "field_profiles": [
            {
                "field_name": p.field_name,
                "present_count": p.present_count,
                "non_empty_count": p.non_empty_count,
                "null_count": p.null_count,
                "observed_types": list(p.observed_types),
                "distinct_count": p.distinct_count,
                "duplicate_count": p.duplicate_count,
            }
            for p in result.field_profiles
        ],
        "candidate_key_profiles": [
            {
                "field_name": ck.field_name,
                "field_exists": ck.field_exists,
                "non_empty_count": ck.non_empty_count,
                "distinct_count": ck.distinct_count,
                "duplicate_count": ck.duplicate_count,
                "one_per_workflow": ck.one_per_workflow,
                "stable_across_reads": ck.stable_across_reads,
            }
            for ck in result.candidate_key_profiles
        ],
        "stability": {
            "stable_count": result.stability.stable_count,
            "added_count": result.stability.added_count,
            "removed_count": result.stability.removed_count,
            "duplicate_count": result.stability.duplicate_count,
            "conclusion": result.stability.conclusion,
            "row_count_match": result.stability.row_count_match,
        },
        "categorical_values": [
            {
                "field_name": cv.field_name,
                "values": list(cv.values),
                "truncated": cv.truncated,
                "user_approved": cv.user_approved,
            }
            for cv in result.categorical_values
        ],
        "version_candidates": [
            {
                "field_name": vc.field_name,
                "category": vc.category,
                "reason": vc.reason,
            }
            for vc in result.version_candidates
        ],
        "external_version_strategy": result.external_version_strategy,
        "warnings": list(result.warnings),
        "unresolved_questions": list(result.unresolved_questions),
    }


# ── 类型别名 ────────────────────────────────────────────────────

#: TDCDataModelFilters 的鸭子类型，避免 import tdc_crawler。
TDCDataModelFiltersLike = Any

#: TDCDataModelFilters 字段名列表（与 services/tdc_crawler.py TDCDataModelFilters 一致）。
_FILTER_FIELD_NAMES: tuple[str, ...] = (
    "serial_number",
    "applicant",
    "department",
    "section",
    "application_start",
    "application_end",
    "project_model",
    "part_number",
    "model_number",
)

#: TDCDataModelFilters 字段名 → 显示标签（用于报告 filter_fields_used）。
FILTER_FIELD_LABELS: dict[str, str] = {
    "serial_number": "incident",
    "applicant": "applicant",
    "department": "superDepartment",
    "section": "department",
    "application_start": "requestDateStart",
    "application_end": "requestDateEnd",
    "project_model": "projectModel",
    "part_number": "partNumber",
    "model_number": "modelNumber",
}


def get_filter_field_labels(filters: TDCDataModelFiltersLike) -> tuple[str, ...]:
    """返回非空过滤字段的 HTTP 参数名（不含值）。"""
    if filters is None:
        return ()
    labels: list[str] = []
    for name in _FILTER_FIELD_NAMES:
        if _filter_value_non_empty(getattr(filters, name, None)):
            labels.append(FILTER_FIELD_LABELS.get(name, name))
    return tuple(sorted(labels))
