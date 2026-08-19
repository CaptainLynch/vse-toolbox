"""Canonical system department and NCR section-code mapping for Aras reports.

Display names seen in Aras reports (e.g. 技术中心-车体工程) are mapped to the
canonical system department value used in filters. Unknown or blank names
fail closed (ValueError) instead of being forwarded to Aras.
"""

from __future__ import annotations

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
