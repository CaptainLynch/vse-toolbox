"""官方 EWO 工作簿 → 契约行（单一来源）。

为什么存在：EWO 导出契约 111 列中有 60 列在列表接口来源下恒为空——不是官方没有值，
而是列表接口（``EWO_O/get``）根本没有这些列（阶段日期、停留天数、待签角色、签批角色人、
基地汇总等）。官方导出工作簿是这些列的唯一来源。本模块把它按契约标签投影成行，并对
任何形状偏差 fail-closed：

- 表头必须逐字等于契约 111 标签（缺一列、换序、措辞差异都失败）；
- 契约外列只要**任一数据行非空**就失败（整列为空则放行，并记录列名）；
- 行数与内部 ID 集合、业务编号多重集对账不通过即失败；
- 绝不部分投影、绝不从相邻列借值（与 ``services.tdc_official_rows`` 同形态）。

读取沿用 ``services.ewo_workbook``（包装 ``services.xlsx_preview`` 的 zip+XML 读取器，
不违反公司 DLP 对 pandas/openpyxl 的禁令）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from core.report_contracts import report_contracts
from services.ewo_readonly import associate_export_rows
from services.ewo_workbook import read_ewo_workbook

_HEADER_MISMATCH = "E_HEADER_MISMATCH"
_EXTRA_COLUMN_DATA = "E_EXTRA_COLUMN_DATA"
_WORKBOOK_INVALID = "E_WORKBOOK_INVALID"
_RECONCILE_MISMATCH = "E_RECONCILE_MISMATCH"

__all__ = [
    "EwoExportGateError",
    "E_EXTRA_COLUMN_DATA",
    "E_HEADER_MISMATCH",
    "E_RECONCILE_MISMATCH",
    "E_WORKBOOK_INVALID",
    "contract_labels",
    "label_rows",
    "project_official_ewo_rows",
    "read_official_ewo_rows",
    "reconcile_official_rows",
]

E_HEADER_MISMATCH = _HEADER_MISMATCH
E_EXTRA_COLUMN_DATA = _EXTRA_COLUMN_DATA
E_WORKBOOK_INVALID = _WORKBOOK_INVALID
E_RECONCILE_MISMATCH = _RECONCILE_MISMATCH


class EwoExportGateError(ValueError):
    """官方工作簿不能安全投影为契约行；``code`` 供任务层映射错误码与重试决策。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def contract_labels() -> list[str]:
    """EWO 契约的数据表头（111 个标签，按契约列序）。"""
    contract = report_contracts()["ewo"]
    header_rows = contract["headerRows"]
    data_header_row = int(contract.get("dataHeaderRow", 0))
    return [str(value or "").strip() for value in header_rows[data_header_row]]


def _cell(row: Sequence[object], index: int) -> object:
    return row[index] if index < len(row) else None


def _has_value(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def label_rows(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> tuple[dict[str, object], ...]:
    """按表头把矩阵行转成「契约标签 → 值」的行元组。

    表头为空、重复或与契约标签不一致时抛 ``E_HEADER_MISMATCH``；契约外列只要
    任一数据行非空抛 ``E_EXTRA_COLUMN_DATA``（整列为空放行）。
    """
    labels = contract_labels()
    normalized = [str(value or "").strip() for value in headers]
    if normalized[: len(labels)] != labels:
        missing = [label for label, got in zip(labels, normalized) if label != got]
        raise EwoExportGateError(
            _HEADER_MISMATCH,
            "workbook header does not match the approved EWO contract "
            f"(first differing labels: {', '.join(missing[:5]) or 'none'})",
        )
    extra = normalized[len(labels):]
    if extra:
        for row_index, row in enumerate(rows):
            for offset, header in enumerate(extra):
                if _has_value(_cell(row, len(labels) + offset)):
                    raise EwoExportGateError(
                        _EXTRA_COLUMN_DATA,
                        f"extra column {header!r} has data at row {row_index + 1}",
                    )
    labeled: list[dict[str, object]] = []
    for row in rows:
        labeled.append({label: _cell(row, index) for index, label in enumerate(labels)})
    return tuple(labeled)


def read_official_ewo_rows(path: Path) -> tuple[dict[str, object], ...]:
    """把官方 EWO 工作簿投影为契约行。

    ``read_ewo_workbook`` 负责工作表名、必需表头、表头唯一、行宽与行数上限；
    这里的 ValueError 统一包装成 ``E_WORKBOOK_INVALID``，形状偏差用专用错误码。
    """
    try:
        workbook = read_ewo_workbook(Path(path))
    except ValueError as exc:
        raise EwoExportGateError(_WORKBOOK_INVALID, str(exc)) from exc
    return label_rows(workbook["headers"], workbook["rows"])


def project_official_ewo_rows(
    rows: Sequence[Mapping[str, object]],
    labels: Sequence[str] | None = None,
) -> list[list[object | None]]:
    """按给定列标签取出行矩阵（缺列补 None，绝不从相邻列取值）。"""
    target = list(labels) if labels is not None else contract_labels()
    return [[row.get(label) for label in target] for row in rows]


def reconcile_official_rows(
    base_rows: Sequence[Mapping[str, object]],
    export_rows: Sequence[Sequence[object]],
    labels: Sequence[str] | None = None,
) -> dict[str, object]:
    """对账：工作簿行数 = 选择集行数，且业务编号严格唯一匹配。

    ``base_rows`` 为 ``{"id": 32hex, "_no": 业务编号}`` 行；``export_rows`` 为矩阵。
    任一空编号、重复编号或未命中都视为对账失败（不允许静默少导或错配）。
    """
    target = list(labels) if labels is not None else contract_labels()
    base = list(base_rows)
    exports = [list(row) for row in export_rows]
    if len(exports) != len(base):
        raise EwoExportGateError(
            _RECONCILE_MISMATCH,
            f"workbook rows {len(exports)} != selection rows {len(base)}",
        )
    result = associate_export_rows(base, target, exports)
    if (
        result["blank_number_count"]
        or result["ambiguous_count"]
        or result["unmatched_count"]
    ):
        raise EwoExportGateError(
            _RECONCILE_MISMATCH,
            "business number reconciliation failed "
            f"(blank={result['blank_number_count']}, "
            f"ambiguous={result['ambiguous_count']}, "
            f"unmatched={result['unmatched_count']})",
        )
    return result
