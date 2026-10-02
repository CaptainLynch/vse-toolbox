"""Canonical system department and NCR section-code mapping for Aras reports.

Display names seen in Aras reports (e.g. 技术中心-车体工程) are mapped to the
canonical system department value used in filters. Unknown or blank names
fail closed (ValueError) instead of being forwarded to Aras.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Mapping, Sequence

#: NCR report section codes accepted by the approval progress/detail exports.
NCR_SECTION_CODES: tuple[str, ...] = ("BA", "BE", "BI", "EXT", "INT", "SES", "VE")

#: Display-name aliases -> canonical system department value.
SYSTEM_DEPARTMENT_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "技术中心-车体工程": "技术中心_车体工程",
        "技术中心_车体工程": "技术中心_车体工程",
    }
)

#: Versioned mapping (v1): canonical system department -> NCR section codes.
#: Only 技术中心_车体工程 is currently supported; future departments extend v1+.
NCR_SECTION_CODES_BY_DEPARTMENT_V1: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "技术中心_车体工程": NCR_SECTION_CODES,
    }
)


def normalize_departments(names: Sequence[str | None]) -> tuple[str, ...]:
    """Normalize display department names to canonical system departments.

    Raises ValueError (fail-closed) when a name is blank/None or has no known
    canonical form. Returns an immutable tuple of canonical system departments.
    """
    resolved: list[str] = []
    for name in names:
        if name is None or not str(name).strip():
            raise ValueError("department name must not be empty")
        key = str(name).strip()
        try:
            canonical = SYSTEM_DEPARTMENT_ALIASES[key]
        except KeyError:
            raise ValueError(f"unknown department: {key!r}") from None
        resolved.append(canonical)
    return tuple(resolved)


def resolve_ncr_section_codes(names: Sequence[str | None]) -> tuple[str, ...]:
    """Resolve display department names to the NCR section codes used by filters.

    Fail-closed like normalize_departments: blank/None or unknown names raise
    ValueError. Duplicate aliases of the same department are deduped and still
    yield exactly one copy of that department's section codes. Returns an
    immutable tuple of NCR section codes.
    """
    resolved: list[str] = []
    for canonical in normalize_departments(names):
        try:
            codes = NCR_SECTION_CODES_BY_DEPARTMENT_V1[canonical]
        except KeyError:
            raise ValueError(f"department has no NCR section codes: {canonical!r}") from None
        for code in codes:
            if code not in resolved:
                resolved.append(code)
    return tuple(resolved)


_NCR_CODE_ITEM_SEPARATOR = re.compile(r"[,，、;；\n]+")


def parse_ncr_section_codes_input(value: object) -> tuple[str, ...]:
    """Parse user-provided NCR section-code input into canonical codes (fail-closed).

    配置保存（mapping-discovery）、同步 collect 三个入口共用同一解析器，
    不得只在取证入口校验。契约（docs/PLAN_20260926_SOR_ROWS_RING_CLICK_NCR_
    SECTION_DATAMODEL_STATUS.md F3）：
    - 空输入 → ``()``（不限科室，向导提示写明）；
    - 接受合法代码（大小写不敏感），逗号/顿号/分号/换行分隔，去重保序；
    - 单项内部空白：整体是「合法代码 + 空白 + 名称后缀」（如 ``BE 结构工程科``）
      时按该代码接受，名称后缀**不参与校验**；空白分隔的全部 token 都是合法
      代码时逐个接受；其余一律 ``ValueError``（消息列出合法代码）——绝不静默
      丢弃或退化为全量查询。纯中文科室名不映射（对照契约未确立）。
    """
    if value is None:
        return ()
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("科室代码必须是字符串")
    text = value.strip()
    if not text:
        return ()
    canonical_by_fold = {code.casefold(): code for code in NCR_SECTION_CODES}
    resolved: list[str] = []
    for item in _NCR_CODE_ITEM_SEPARATOR.split(text):
        item = item.strip()
        if not item:
            continue
        parts = item.split()
        if len(parts) > 1:
            if all(part.casefold() in canonical_by_fold for part in parts):
                # 空白分隔的多个合法代码：逐个接受。
                for part in parts:
                    code = canonical_by_fold[part.casefold()]
                    if code not in resolved:
                        resolved.append(code)
                continue
            first = parts[0].casefold()
            if first in canonical_by_fold:
                # 「合法代码 + 空白 + 名称后缀」：后缀不校验，识别结果以代码为准。
                code = canonical_by_fold[first]
            else:
                raise ValueError(
                    f"无法识别的科室：{item}（合法代码：{'/'.join(NCR_SECTION_CODES)}）"
                )
        else:
            folded = item.casefold()
            if folded not in canonical_by_fold:
                raise ValueError(
                    f"无法识别的科室：{item}（合法代码：{'/'.join(NCR_SECTION_CODES)}）"
                )
            code = canonical_by_fold[folded]
        if code not in resolved:
            resolved.append(code)
    return tuple(resolved)
