# -*- coding: utf-8 -*-
"""ARAS NCR 官方工作簿的共享解析与归类（唯一解析口径）。

**为什么存在**：同一交付物（D7 NCR 审批进度 / D8 NCR 审批明细）原先有两条
互不相干的解析实现——同步路径在 `services.project_status_connectors` 里把
位置行按表头拼成命名行，归档路径在 `services.scheduled_archive_connectors`
里发布位置行。两者写入同一个表单快照存储，而读取按 `snapshot_at` 取最新，
于是"快照形状取决于最后写入者"，明细/图表口径随之漂移。

本模块是两条路径**唯一**的工作簿解析入口，保证：
1. 行形状唯一：按已批准表头标签命名的字典（与 Aras 行查询路径的命名行同形），
   额外携带 `sheetName` 与契约顺序的位置视图 `values`——表头存在同名标签时
   （NCR 进度有 11 组），位置视图是唯一无损的值来源，标签字典只作按标签取值用。
2. 归类可核对：每个被读取的行都归入「记录 / 空行 / 表头或摘要行 / 未归类」之一，
   并向上层暴露读写事实，供准入判定使用。

设计边界：
- 本模块只解析与归类，**不判定 completeness**：准入判定由
  `services.pagination_integrity.decide_workbook_outcome` 单点拥有；
- 不在本模块访问 SQLite、凭据或网络；
- 不扩张已批准契约：超出契约宽度的额外单元格不进入投影，只计数披露
  （`unmapped_cells`），因为 `ncr_detail` 的整车/发动机两种工作表本就存在
  动态列块，超出部分是契约外内容而非丢失的已批准列。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.report_contracts import report_contracts
from services.pagination_integrity import (
    WorkbookBookkeeping,
    decide_workbook_outcome,
    is_complete,
)
from services.xlsx_preview import XLSXPreviewError, read_xlsx_workbook_preview

#: 与 `services.scheduled_archive_connectors` 既有披露词表保持一致的投影错误码。
PROJECTION_ERROR_UNREADABLE = "official_workbook_unreadable"
PROJECTION_ERROR_TRUNCATED = "official_workbook_truncated"
PROJECTION_ERROR_CONTRACT = "official_workbook_contract_invalid"

SUPPORTED_NCR_REPORTS: frozenset[str] = frozenset({"ncr_progress", "ncr_detail"})

#: 工作簿预览上限（与既有实现一致：20001 行 × 200 列）。
_MAX_PREVIEW_ROWS = 20001
_MAX_PREVIEW_COLUMNS = 200


class NcrWorkbookError(ValueError):
    """工作簿无法作为已批准的 NCR 报表使用。"""


@dataclass(frozen=True)
class NcrWorkbookRow:
    """一行已归类的业务记录（位置视图 + 标签命名视图同源）。"""

    values: tuple[Any, ...]
    labels: dict[str, Any] = field(default_factory=dict)
    sheet_name: str = ""

    def named_row(self) -> dict[str, Any]:
        """返回按已批准表头标签命名的行（自动携带 `sheetName` 与位置视图）。

        **位置视图是权威值来源。** 已批准的 NCR 进度表头里有 11 个角色标签各出现
        两次（列 37..47 是各角色「办理时间」日期，列 52..62 是同名角色的「执行人」
        姓名）。标签字典无法无损表达这种行——同名键只能保留后写入的那一个，于是
        办理时间会被执行人覆盖。因此这里同时携带契约顺序的 `values`，读取侧据此
        还原位置视图（11 个办理时间不再被静默覆盖）；标签键继续保留，供按标签取值
        的消费者使用，命名行约定不被破坏。
        """
        row = dict(self.labels)
        row["values"] = list(self.values)
        row["sheetName"] = self.sheet_name
        return row


@dataclass(frozen=True)
class NcrWorkbookOutcome:
    """解析结果：命名行 + 簿记事实 + 投影错误码 + 准入停机原因。"""

    report_type: str
    rows: tuple[NcrWorkbookRow, ...]
    bookkeeping: WorkbookBookkeeping
    projection_error: str | None
    stop_reason: str
    unmapped_cells: int = 0

    @property
    def complete(self) -> bool:
        return is_complete(self.stop_reason)

    def named_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(row.named_row() for row in self.rows)

    def bookkeeping_facts(self) -> dict[str, int]:
        book = self.bookkeeping
        return {
            "rowsRead": book.read_rows,
            "rowsParsed": book.parsed_rows,
            "rowsBlank": book.blank_rows,
            "rowsHeader": book.header_rows,
            "rowsUnclassified": book.unclassified_rows,
            "cellsOutsideContract": self.unmapped_cells,
        }


def _contract(report_type: str) -> Mapping[str, Any]:
    if report_type not in SUPPORTED_NCR_REPORTS:
        raise NcrWorkbookError(f"unsupported ARAS form workbook report: {report_type}")
    try:
        return report_contracts()[report_type]
    except KeyError as exc:  # pragma: no cover - 由契约文件保证
        raise NcrWorkbookError(f"missing report contract: {report_type}") from exc


def _header_index(report_type: str) -> int:
    # NCR 进度的第一行是过滤摘要，真正的表头在第二行。
    return 1 if report_type == "ncr_progress" else 0


def _expected_labels(contract: Mapping[str, Any], report_type: str) -> list[str]:
    header_rows = contract["headerRows"]
    return [str(value or "").strip() for value in header_rows[_header_index(report_type)]]


def _is_blank_row(row: Sequence[Any]) -> bool:
    return not any(value not in (None, "") for value in row)


def parse_ncr_workbook(path: Path, report_type: str) -> NcrWorkbookOutcome:
    """解析官方 NCR 工作簿；任何结构性怀疑都以 fail-closed 停机原因返回。

    调用方（同步路径）必须检查 `complete`；归档路径只记录 `projection_error`
    与簿记事实（它还要保留官方产物，不因投影失败丢弃原件）。
    """
    contract = _contract(report_type)
    expected = _expected_labels(contract, report_type)
    expected_indexes = {
        label: index for index, label in enumerate(expected) if label
    }
    minimum_data_row = len(contract["headerRows"])

    try:
        previews = read_xlsx_workbook_preview(
            path, max_rows=_MAX_PREVIEW_ROWS, max_columns=_MAX_PREVIEW_COLUMNS
        )
    except XLSXPreviewError:
        return _outcome(
            report_type,
            rows=(),
            bookkeeping=WorkbookBookkeeping(
                read_rows=0, parsed_rows=0, unreadable=True
            ),
            projection_error=PROJECTION_ERROR_UNREADABLE,
        )

    rows: list[NcrWorkbookRow] = []
    read_rows = 0
    blank_rows = 0
    header_rows = 0
    unclassified_rows = 0
    header_contract_ok = True
    truncated = False
    row_rejected = False
    unmapped_cells = 0

    for sheet_index, preview in enumerate(previews):
        sheet_rows = preview.rows
        sheet_name = preview.sheet_name
        # NCR 进度的后续工作表是过滤摘要，不是报表表体（已批准契约）。
        if report_type == "ncr_progress" and sheet_index > 0:
            header_rows += len(sheet_rows)
            read_rows += len(sheet_rows)
            continue
        if preview.truncated:
            truncated = True
        read_rows += len(sheet_rows)
        if len(sheet_rows) <= _header_index(report_type):
            header_rows += len(sheet_rows)
            continue
        actual = [
            str(value or "").strip() for value in sheet_rows[_header_index(report_type)]
        ]
        actual = actual[: len(expected)] + [""] * max(0, len(expected) - len(actual))
        if report_type == "ncr_progress" and actual != expected:
            header_contract_ok = False
        if report_type == "ncr_detail":
            # 整车工作表带动态车型矩阵块，发动机工作表没有该块：
            # 按稳定的已批准列名对齐，两侧得到同一套命名列。
            actual_nonempty = {label for label in actual if label}
            required = set(expected[:17]) - {""}
            if not required.issubset(actual_nonempty):
                header_contract_ok = False

        data_start = minimum_data_row
        label_aligned = report_type == "ncr_detail" and actual != expected
        if label_aligned:
            # 发动机工作表只有一行表头且没有车型矩阵块。
            data_start = _header_index(report_type) + 1
        header_rows += min(len(sheet_rows), data_start)

        for raw_row in sheet_rows[data_start:]:
            if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
                row_rejected = True
                # 该行已被读取却无法归类：计入 unclassified 使账目等式仍成立，
                # 避免"读了但哪里都没算"的缺口（停机原因仍由 row_rejected 优先给出）。
                unclassified_rows += 1
                continue
            if _is_blank_row(raw_row):
                blank_rows += 1
                continue
            values: list[Any] = [None] * len(expected)
            if label_aligned:
                for source_index, label in enumerate(actual):
                    target_index = expected_indexes.get(label)
                    if target_index is not None and source_index < len(raw_row):
                        values[target_index] = raw_row[source_index]
                unmapped_cells += sum(
                    1
                    for source_index, label in enumerate(actual)
                    if label and label not in expected_indexes
                    and source_index < len(raw_row)
                    and raw_row[source_index] not in (None, "")
                )
            else:
                values = list(raw_row[: len(expected)])
                values.extend([None] * max(0, len(expected) - len(values)))
                unmapped_cells += sum(
                    1
                    for value in raw_row[len(expected):]
                    if value not in (None, "")
                )
            if not any(value not in (None, "") for value in values):
                # 非空行，但在已批准契约的列内没有任何值 —— 无法归类，不放行。
                unclassified_rows += 1
                continue
            labels = {
                label: values[index]
                for index, label in enumerate(expected)
                if label
            }
            rows.append(
                NcrWorkbookRow(
                    values=tuple(values), labels=labels, sheet_name=sheet_name
                )
            )

    bookkeeping = WorkbookBookkeeping(
        read_rows=read_rows,
        parsed_rows=len(rows),
        blank_rows=blank_rows,
        header_rows=header_rows,
        unclassified_rows=unclassified_rows,
        header_contract_ok=header_contract_ok,
        truncated=truncated,
        row_rejected=row_rejected,
    )
    projection_error = None
    if not header_contract_ok:
        projection_error = PROJECTION_ERROR_CONTRACT
    elif truncated:
        projection_error = PROJECTION_ERROR_TRUNCATED
    return _outcome(
        report_type,
        rows=tuple(rows),
        bookkeeping=bookkeeping,
        projection_error=projection_error,
        unmapped_cells=unmapped_cells,
    )


def _outcome(
    report_type: str,
    *,
    rows: tuple[NcrWorkbookRow, ...],
    bookkeeping: WorkbookBookkeeping,
    projection_error: str | None,
    unmapped_cells: int = 0,
) -> NcrWorkbookOutcome:
    return NcrWorkbookOutcome(
        report_type=report_type,
        rows=rows,
        bookkeeping=bookkeeping,
        projection_error=projection_error,
        stop_reason=decide_workbook_outcome(bookkeeping),
        unmapped_cells=unmapped_cells,
    )


def require_complete_workbook(outcome: NcrWorkbookOutcome) -> None:
    """同步路径的 fail-closed 门：未通过准入即抛错（与分页门同形）。"""
    if outcome.complete:
        return
    raise NcrWorkbookError(
        f"external query is incomplete ({outcome.stop_reason})"
    )
