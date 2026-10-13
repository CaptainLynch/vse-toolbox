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
from services.xlsx_preview import XLSXPreviewError, read_xlsx_preview


class OfficialWorkbookError(ValueError):
    """官方工作簿不可安全投影为契约行。"""


class OfficialWorkbookUnreadable(OfficialWorkbookError):
    """工作簿本身读不出来（非 XLSX、超出预览上限、缺少工作表）。"""


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


def read_official_tdc_rows(
    path: Path,
    report_type: str,
    *,
    max_rows: int,
) -> tuple[dict[str, object], ...]:
    """把官方工作簿投影为「契约列标签 → 值」的行元组。

    `max_rows` 含表头行；读到上限即抛 `OfficialWorkbookTruncated`，不做部分投影。
    """
    if max_rows <= 1:
        raise ValueError("max_rows must allow at least a header row")
    try:
        preview = read_xlsx_preview(path, max_rows=max_rows)
    except XLSXPreviewError as exc:
        raise OfficialWorkbookUnreadable(str(exc)) from exc
    if preview.truncated:
        raise OfficialWorkbookTruncated("official workbook preview truncated")
    if not preview.rows:
        return ()
    expected = official_contract_headers(report_type)
    raw_header = [str(value or "").strip() for value in preview.rows[0]]
    if raw_header[: len(expected)] != expected or any(raw_header[len(expected) :]):
        raise OfficialWorkbookContractError(
            f"official TDC {report_type} export header does not match the approved contract"
        )
    rows: list[dict[str, object]] = []
    for row in preview.rows[1:]:
        if not row or not any(value not in (None, "") for value in row):
            continue
        values = list(row) + [None] * max(0, len(expected) - len(row))
        rows.append({expected[index]: values[index] for index in range(len(expected))})
    return tuple(rows)


def project_official_rows(
    rows: Sequence[Mapping[str, object]],
    labels: Sequence[str],
) -> list[list[object | None]]:
    """按给定列标签取出行矩阵（缺列补 None，绝不从相邻列取值）。"""
    return [[row.get(label) for label in labels] for row in rows]
