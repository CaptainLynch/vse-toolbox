# -*- coding: utf-8 -*-
"""官方 TDC 工作簿 → 契约行（单一来源）。

官方导出工作簿是**唯一**能提供全部官方列的数据源：列表接口只覆盖契约 47 列中的
20 列（EWO 111 列中 51 列、PAA 113 列中 45 列），其余列在列表来源下恒为空——
用户会把空列读成"无人待签/数量为 0"（2026-10-13 生产反馈）。归档连接器与
「导出合并结果」都必须用同一套读取语义，避免两处各自解析后漂移。

读取沿用 `services.xlsx_preview`（zip + XML，无第三方依赖，符合公司 DLP 禁令：
禁止用 pandas/openpyxl 读写 Office 文件）。语义边界：

- 工作簿不可读（非 XLSX / 超限）→ `OfficialWorkbookUnreadable`，调用方决定回退；
- 表头与已批准契约不一致、或行数超过读取上限 → 对应异常，**绝不**降级成
  "少几行但看起来正常"的结果（fail-closed）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from core.report_contracts import report_contracts
from services.tdc_text_rows import TextTableError, read_text_table
from services.xlsx_preview import (
    REASON_SCHEMA_MISMATCH,
    XLSXPreviewError,
    read_xlsx_preview,
    read_xlsx_preview_bytes,
)


class OfficialWorkbookError(ValueError):
    """官方工作簿不可安全投影为契约行。

    reason 与 services.xlsx_preview.REASONS 同一套闭集词；col_index 只在表头
    不符时给出（首个不符列的 0 基下标）。调用方只按 reason 映射用户文案。
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        col_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.col_index = col_index


class OfficialWorkbookUnreadable(OfficialWorkbookError):
    """工作簿本身读不出来（非 XLSX、终端加密容器、超出预览上限、缺少工作表）。"""


class OfficialWorkbookTruncated(OfficialWorkbookError):
    """行数达到读取上限：无法证明取全，必须由调用方显式处理。"""


class OfficialWorkbookContractError(OfficialWorkbookError):
    """表头与已批准契约不一致。"""


_SUPPORTED_REPORTS = ("data_model", "sor")


def official_contract_headers(report_type: str) -> list[str]:
    """官方工作簿的数据表头（= 契约列标签，按列序）。"""
    if report_type not in _SUPPORTED_REPORTS:
        raise OfficialWorkbookContractError(f"unsupported TDC report type: {report_type}")
    contract = report_contracts()[f"tdc_{report_type}"]
    header_rows = contract["headerRows"]
    data_header_row = int(contract.get("dataHeaderRow", 0))
    return [str(value or "").strip() for value in header_rows[data_header_row]]


def _first_header_mismatch(raw_header: Sequence[str], expected: Sequence[str]) -> int | None:
    """首个不符列的 0 基下标；整行一致时返回 None。

    不 strip、不做 Unicode 归一：官方契约要求逐字一致，调用方只把这个下标
    当诊断（列号不是敏感信息），绝不把列值带出去。
    """
    for index in range(min(len(raw_header), len(expected))):
        if raw_header[index] != expected[index]:
            return index
    if len(raw_header) != len(expected):
        # 少列 → 首个缺失列下标；多列 → 首个多余列下标（都是同一处"断点"）。
        return min(len(raw_header), len(expected))
    return None


def _is_blank(value: object) -> bool:
    return value is None or value == ""


def check_official_header(
    header_row: Sequence[object],
    report_type: str,
    *,
    strict: bool = False,
) -> list[str]:
    """校验表头行并返回契约列标签；不一致抛 `OfficialWorkbookContractError`。

    - `strict=False`（既有调用方的行为，保持不变）：每格 strip 后比对，契约列之后
      只要没有非空表头就放行。
    - `strict=True`（签署日报的 xlsx 与 TXT 共用）：**逐字、逐序**比对——不 strip、
      不做 Unicode 归一，值必须是字符串；缺列、多列、错位都拒绝。只有「行尾的空格子」
      （xlsx 里带格式的空单元格 / TXT 行尾多出的空字段）不算一列，因为它不带任何内容。
    """
    expected = official_contract_headers(report_type)
    raw_header: list[object]
    if strict:
        raw_header = list(header_row)
        while raw_header and _is_blank(raw_header[-1]):
            raw_header.pop()
        matches = len(raw_header) == len(expected) and all(
            isinstance(value, str) and value == expected[index]
            for index, value in enumerate(raw_header)
        )
    else:
        raw_header = [str(value or "").strip() for value in header_row]
        matches = raw_header[: len(expected)] == expected and not any(raw_header[len(expected) :])
    if not matches:
        raise OfficialWorkbookContractError(
            f"official TDC {report_type} export header does not match the approved contract",
            reason=REASON_SCHEMA_MISMATCH,
            col_index=_first_header_mismatch(raw_header, expected),  # type: ignore[arg-type]
        )
    return expected


def official_rows_from_matrix(
    matrix: Sequence[Sequence[object]],
    report_type: str,
    *,
    strict: bool = False,
) -> tuple[dict[str, object], ...]:
    """行矩阵（第一行是表头）→「契约列标签 → 值」的行元组。

    全空行跳过；短行按空值补齐（Excel 的文本导出会省掉行尾空字段）。`strict=True`
    时，契约列之外出现任何非空值都拒绝——那说明列错位或被人加了列，不能悄悄丢掉。
    """
    if not matrix:
        return ()
    expected = check_official_header(matrix[0], report_type, strict=strict)
    width = len(expected)
    rows: list[dict[str, object]] = []
    for row in matrix[1:]:
        if not row or not any(not _is_blank(value) for value in row):
            continue
        if strict:
            for index in range(width, len(row)):
                if not _is_blank(row[index]):
                    raise OfficialWorkbookContractError(
                        f"official TDC {report_type} export has values beyond the approved columns",
                        reason=REASON_SCHEMA_MISMATCH,
                        col_index=index,
                    )
        values = list(row) + [None] * max(0, width - len(row))
        rows.append({expected[index]: values[index] for index in range(width)})
    return tuple(rows)


def read_official_tdc_rows(
    path: Path,
    report_type: str,
    *,
    max_rows: int,
    strict: bool = False,
) -> tuple[dict[str, object], ...]:
    """把官方工作簿投影为「契约列标签 → 值」的行元组。

    `max_rows` 含表头行；读到上限即抛 `OfficialWorkbookTruncated`，不做部分投影。
    `strict` 见 `check_official_header`（默认保持既有的宽松表头比对）。
    """
    if max_rows <= 1:
        raise ValueError("max_rows must allow at least a header row")
    try:
        preview = read_xlsx_preview(path, max_rows=max_rows)
    except XLSXPreviewError as exc:
        raise OfficialWorkbookUnreadable(
            str(exc), reason=str(getattr(exc, "reason", "") or "")
        ) from exc
    if preview.truncated:
        raise OfficialWorkbookTruncated("official workbook preview truncated")
    return official_rows_from_matrix(preview.rows, report_type, strict=strict)


def read_official_tdc_matrix_from_bytes(
    data: bytes,
    *,
    max_rows: int,
    text: bool,
    max_columns: int | None = None,
) -> tuple[list[list[object | None]], bool]:
    """内存字节 → (行矩阵, 是否截断)；`text=True` 按 Excel 导出的 TAB 文本读，否则按 xlsx。

    全程不落临时文件。读不出来统一抛 `OfficialWorkbookUnreadable`（带闭集 reason）。
    """
    limits = {} if max_columns is None else {"max_columns": max_columns}
    try:
        if text:
            table = read_text_table(data, max_rows=max_rows, **limits)
            return [list(row) for row in table.rows], table.truncated
        preview = read_xlsx_preview_bytes(data, max_rows=max_rows, **limits)
        return preview.rows, preview.truncated
    except (XLSXPreviewError, TextTableError) as exc:
        raise OfficialWorkbookUnreadable(
            str(exc), reason=str(getattr(exc, "reason", "") or "")
        ) from None


def read_official_tdc_rows_from_bytes(
    data: bytes,
    report_type: str,
    *,
    max_rows: int,
    text: bool = False,
    strict: bool = True,
) -> tuple[dict[str, object], ...]:
    """同 `read_official_tdc_rows`，但读**内存里的字节**，并支持 Excel 导出的 TAB 文本。

    新入口默认 `strict=True`（表头逐字比对）；调用方目前只有签署日报的本地导入。
    """
    if max_rows <= 1:
        raise ValueError("max_rows must allow at least a header row")
    matrix, truncated = read_official_tdc_matrix_from_bytes(data, max_rows=max_rows, text=text)
    if truncated:
        raise OfficialWorkbookTruncated("official export truncated at the row limit")
    return official_rows_from_matrix(matrix, report_type, strict=strict)


def project_official_rows(
    rows: Sequence[Mapping[str, object]],
    labels: Sequence[str],
) -> list[list[object | None]]:
    """按给定列标签取出行矩阵（缺列补 None，绝不从相邻列取值）。"""
    return [[row.get(label) for label in labels] for row in rows]
