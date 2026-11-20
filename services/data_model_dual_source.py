"""数模设计审核流程 TDC + iBOM 双源：iBOM 报表读入、本地筛选、按流水单号合并。

方案：docs/PLAN_20261119_IBOM_DMM_DUAL_SOURCE.md（§2–§5）。要点：

- iBOM「数模设计审核流程报表」与 47 列契约只差第 0 列（``序号``），按 ``ibom`` 表头变体读入，
  ``实例号`` 置空。报表里不重复的流水单号数必须等于 iBOM 的 DMM ``totalCount``，否则不完整。
- TDC 的筛选在 TDC 服务器端生效；iBOM 报表是全量，只能按同样含义在本地再筛一遍。只实现取证过
  语义的键，其余键有值时 **fail-closed**（判 iBOM 侧不完整），绝不静默多算。
- 合并以**单据**为单位：同一流水单号只取一侧的全部行，绝不跨源拼行；每行带保留键
  ``_sourceSystem``（tdc/ibom）。
- 任一侧不完整一律抛 :class:`DualSourceIncomplete`，调用方不发布快照。

本模块是纯函数（除读取报表字节外不做 I/O），不发网络请求。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from services.deliverable_form_analysis import DATA_MODEL_SYNC_EXCLUDED_STATUSES, _normalize_tdc_status
from services.deliverable_form_analysis._impl import SOURCE_SYSTEM_KEY
from services.tdc_official_rows import (
    VARIANT_IBOM,
    OfficialWorkbookError,
    read_official_tdc_rows_from_bytes,
)

IBOM_DUAL_SOURCE_ENV = "VSE_IBOM_DUAL_SOURCE"
#: 退出 TDC（方案 §9）：数模只取 iBOM。只在 iBOM 双源已开启时生效。
TDC_RETIRED_ENV = "VSE_TDC_DATA_MODEL_RETIRED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

SOURCE_TDC = "tdc"
SOURCE_IBOM = "ibom"

#: 终态废弃（合并取舍用）：与数模范围剔除同一集合（TDC 已废弃/已撤回 + iBOM 取消）。
DISCARDED_STATUSES = frozenset(DATA_MODEL_SYNC_EXCLUDED_STATUSES)

_SERIAL_KEYS = ("流水单号", "documentNo")
_STATUS_KEYS = ("状态", "status")
_PART_KEYS = ("零件号", "partNumber")
_APPLICANT_KEYS = ("申请人", "applicant")
_REPORT_LIST_LIMIT = 200

#: 不完整原因闭集（进诊断与运行摘要，不含任何业务值）。
REASON_IBOM_DISABLED = "ibom_disabled"
REASON_IBOM_AUTH = "ibom_auth_failed"
REASON_IBOM_REQUEST = "ibom_request_failed"
REASON_IBOM_REPORT = "ibom_report_invalid"
REASON_IBOM_COUNT = "ibom_count_mismatch"
REASON_IBOM_FILTER = "ibom_filter_unsupported"
REASON_TDC_LOGIN_FIRST = "tdc_login_not_confirmed"
REASONS = frozenset({
    REASON_IBOM_DISABLED, REASON_IBOM_AUTH, REASON_IBOM_REQUEST, REASON_IBOM_REPORT,
    REASON_IBOM_COUNT, REASON_IBOM_FILTER, REASON_TDC_LOGIN_FIRST,
})

#: 归档筛选键在 iBOM 侧的处理（方案 §3.4，2026-11-20 按生产取证修订）。
_IGNORED_FILTER_KEYS = frozenset({"syncScope", "watchlist", "documentNo"})  # 由关注清单/下游处理，与 TDC 侧一致
_FAIL_CLOSED_FILTER_KEYS = frozenset({"applicant", "department", "partNumber", "modelNumber", "status"})
_ARCH_PREFIXES = ("TRA", "AR")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DualSourceIncomplete(ValueError):
    """某一侧不完整：调用方不得发布快照。``reason`` 属于 :data:`REASONS`。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in REASONS:
            raise ValueError("unsupported dual-source reason")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def dual_source_enabled(env: Mapping[str, str] | None = None) -> bool:
    """是否启用 iBOM 侧（``VSE_IBOM_DUAL_SOURCE`` = 1/true/yes/on）。缺省关闭：行为与纯 TDC 相同。"""
    source: Mapping[str, str] = os.environ if env is None else env
    return str(source.get(IBOM_DUAL_SOURCE_ENV) or "").strip().lower() in _TRUTHY


def _value(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        if key in row and row[key] is not None:
            text = str(row[key]).strip()
            if text:
                return text
    return ""


def _status(row: Mapping[str, Any]) -> str:
    return str(_normalize_tdc_status(_value(row, _STATUS_KEYS)) or "").strip()


def tdc_side_retired(env: Mapping[str, str] | None = None) -> bool:
    """数模是否已退出 TDC：``VSE_TDC_DATA_MODEL_RETIRED`` 为真**且** iBOM 双源已开启。

    退出条件（方案 §9）：TDC 不再接收新单，且 TDC 侧在途单全部到达已完成或已废弃。
    """
    source: Mapping[str, str] = os.environ if env is None else env
    retired = str(source.get(TDC_RETIRED_ENV) or "").strip().lower() in _TRUTHY
    return retired and dual_source_enabled(source)


# ── iBOM 报表 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IBOMReport:
    rows: tuple[dict[str, object], ...]
    documents: int


def read_ibom_report(content: bytes, *, total_count: int, max_rows: int) -> IBOMReport:
    """iBOM 报表字节 → 契约行；单据数必须等于 ``total_count``。"""
    try:
        rows = read_official_tdc_rows_from_bytes(
            content, "data_model", max_rows=max_rows, text=False, strict=True, variant=VARIANT_IBOM
        )
    except OfficialWorkbookError as exc:
        reason = str(getattr(exc, "reason", "") or type(exc).__name__)
        raise DualSourceIncomplete(REASON_IBOM_REPORT, reason) from None
    serials = {_value(row, _SERIAL_KEYS) for row in rows}
    serials.discard("")
    if any(not _value(row, _SERIAL_KEYS) for row in rows):
        raise DualSourceIncomplete(REASON_IBOM_REPORT, "row_without_serial")
    if len(serials) != total_count:
        raise DualSourceIncomplete(REASON_IBOM_COUNT, f"report={len(serials)} total={total_count}")
    return IBOMReport(tuple(rows), len(serials))


# ── 本地筛选 ──────────────────────────────────────────────────────────


def _filter_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "" if not value else "<list>"
    return str(value).strip()


def apply_ibom_filters(
    rows: Sequence[Mapping[str, Any]],
    filters: Mapping[str, object],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按归档筛选在 iBOM 行上本地套用 TDC 同含义的筛选；返回 (行, 报告)。"""
    active = {key: value for key, value in filters.items() if _filter_text(value)}
    blocked = sorted(key for key in active if key in _FAIL_CLOSED_FILTER_KEYS)
    unknown = sorted(
        key for key in active
        if key not in _FAIL_CLOSED_FILTER_KEYS and key not in _IGNORED_FILTER_KEYS
        and key not in {"incident", "section", "projectModel", "applicationStart", "applicationEnd"}
    )
    if blocked or unknown:
        raise DualSourceIncomplete(REASON_IBOM_FILTER, ",".join(blocked + unknown))
    kept = [dict(row) for row in rows]
    steps: list[dict[str, Any]] = [{"step": "all", "rows": len(kept)}]
    excluded_arch: dict[str, int] = {}

    if "incident" in active:
        kept = []  # 实例号只存在于 TDC
        steps.append({"step": "incident", "rows": 0})
    if "section" in active:
        target = _filter_text(active["section"])
        kept = [row for row in kept if _value(row, ("部门",)) == target]
        steps.append({"step": "section", "rows": len(kept)})
    if "projectModel" in active:
        target = _filter_text(active["projectModel"]).casefold()
        matched = []
        for row in kept:
            name = _value(row, ("项目/车型",))
            if name.casefold() == target:
                matched.append(row)
            elif name.upper().startswith(_ARCH_PREFIXES):
                excluded_arch[name] = excluded_arch.get(name, 0) + 1
        kept = matched
        steps.append({"step": "projectModel", "rows": len(kept)})
    start = _filter_text(active.get("applicationStart"))[:10]
    end = _filter_text(active.get("applicationEnd"))[:10]
    if start or end:
        for bound in (start, end):
            if bound and not _ISO_DAY.match(bound):
                raise DualSourceIncomplete(REASON_IBOM_FILTER, "applicationDate")
        days = []
        for row in kept:
            day = _value(row, ("申请日期",))[:10]
            if not _ISO_DAY.match(day):
                # 日期认不出（斜杠格式、Excel 序列号、空值）：无法证明它在不在范围内，判不完整而不是丢行。
                raise DualSourceIncomplete(REASON_IBOM_REPORT, "unparsable_application_date")
            days.append((row, day))
        kept = [row for row, day in days if (not start or day >= start) and (not end or day <= end)]
        steps.append({"step": "applicationDate", "rows": len(kept)})
    report = {"steps": steps, "excludedArchitectureProjects": dict(sorted(excluded_arch.items()))}
    return kept, report


# ── 合并 ──────────────────────────────────────────────────────────────


def _group(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_value(row, _SERIAL_KEYS), []).append(dict(row))
    return groups


def _document_status(rows: Sequence[Mapping[str, Any]]) -> str:
    return _status(rows[0]) if rows else ""


def _signature(rows: Sequence[Mapping[str, Any]]) -> tuple[frozenset[str], str]:
    parts = frozenset(_value(row, _PART_KEYS) for row in rows)
    return parts, _value(rows[0], _APPLICANT_KEYS) if rows else ""


def _tag(rows: Iterable[Mapping[str, Any]], source: str) -> list[dict[str, Any]]:
    return [{**row, SOURCE_SYSTEM_KEY: source} for row in rows]


def merge_sources(
    tdc_rows: Sequence[Mapping[str, Any]],
    ibom_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按流水单号合并两侧的行；返回 (行, 合并报告)。

    - 单号只在一侧：采用该侧全部行。
    - 两侧都有：一侧终态废弃而另一侧不是 → 取不是废弃的那一侧；否则取 iBOM，记「双系统单」；
      零件号集合或申请人不同另记「冲突」。
    - TDC 侧缺流水单号的行（列表接口兜底的异常行）原样保留为 TDC 行，不参与合并。
    """
    tdc_groups = _group(tdc_rows)
    ibom_groups = _group(ibom_rows)
    unkeyed_tdc = tdc_groups.pop("", [])
    if "" in ibom_groups:
        # iBOM 报表读入与手工导入都会先拒收无流水单号的行；走到这里说明调用方漏检，宁可停也不发布。
        raise DualSourceIncomplete(REASON_IBOM_REPORT, "row_without_serial")
    dual: list[str] = []
    conflicts: list[str] = []
    take_tdc: set[str] = set(tdc_groups)
    take_ibom: set[str] = set(ibom_groups)
    for serial in sorted(set(tdc_groups) & set(ibom_groups)):
        tdc_group, ibom_group = tdc_groups[serial], ibom_groups[serial]
        tdc_discarded = _document_status(tdc_group) in DISCARDED_STATUSES
        ibom_discarded = _document_status(ibom_group) in DISCARDED_STATUSES
        if tdc_discarded and not ibom_discarded:
            take_tdc.discard(serial)
        elif ibom_discarded and not tdc_discarded:
            take_ibom.discard(serial)
        else:
            take_tdc.discard(serial)
            dual.append(serial)
        if _signature(tdc_group) != _signature(ibom_group):
            conflicts.append(serial)
    merged: list[dict[str, Any]] = []
    tdc_kept = 0
    for serial, group in tdc_groups.items():
        if serial in take_tdc:
            merged.extend(_tag(group, SOURCE_TDC))
            tdc_kept += 1
    merged.extend(_tag(unkeyed_tdc, SOURCE_TDC))
    ibom_kept = 0
    for serial, group in ibom_groups.items():
        if serial in take_ibom:
            merged.extend(_tag(group, SOURCE_IBOM))
            ibom_kept += 1
    report = {
        "tdc": {"documents": len(tdc_groups), "rows": len(tdc_rows), "kept": tdc_kept,
                "rowsWithoutSerial": len(unkeyed_tdc)},
        "ibom": {"documents": len(ibom_groups), "rows": len(ibom_rows), "kept": ibom_kept},
        "dualSystem": dual[:_REPORT_LIST_LIMIT],
        "dualSystemCount": len(dual),
        "conflicts": conflicts[:_REPORT_LIST_LIMIT],
        "conflictCount": len(conflicts),
    }
    return merged, report
