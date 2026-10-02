# -*- coding: utf-8 -*-
"""Shared sync-scope row exclusion for TDC SOR/data_model and Aras PAA rows.

TASK-20260930-R7-G2：项目状态同步与定时归档两条写入路径共用同一剔除实现
（单一来源，禁止复制出第二套口径）。剔除语义：

- TDC SOR：按报表候选键序取首个非空状态值，经
  ``normalize_tdc_report_status`` 归一后属于 ``TDC_SYNC_EXCLUDED_STATUSES``
  （已废弃/已撤回）即剔除。归一复用 services.deliverable_form_analysis
  （嵌套对象只取 name、英文别名映射、未映射文本透传），不在此复制。
- TDC data_model：数字码 "2"/"4" 归一为 审批中/已完成（不在剔除集）、未映射
  码（"3"/"6"）原样透传不剔除——码映射升级属 B 案，另行裁决；归档官方
  工作簿文本列（"状态"）按同一剔除集生效。
- Aras PAA：state / current_state__name 任一 trim+upper 后等于 "CANCEL"
  即剔除（空白/大小写变体一律命中）。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from services.deliverable_form_analysis import (
    TDC_SYNC_EXCLUDED_STATUSES,
    normalize_tdc_report_status,
)

#: 各报表形态的候选状态键（按优先级取首个非空值）：
#: - sor：同步行经 flatten_sor_rows 后 processInstanceStatus 为扁平文本；
#:   原始爬取行保留嵌套对象（归一只取 name）；归档官方工作簿行为中文表头
#:   "审批状态"（core.report_contracts 契约列）。
#: - data_model：同步行为数字码列 "status"；归档官方工作簿行为文本列 "状态"。
TDC_STATUS_KEYS_BY_REPORT: dict[str, tuple[str, ...]] = {
    "sor": ("processInstanceStatus", "approvalStatus", "审批状态"),
    "data_model": ("status", "状态"),
}

#: PAA 行状态候选键（任一命中 CANCEL 即剔除；core/report_contracts 命名行）。
PAA_STATUS_KEYS: tuple[str, ...] = ("state", "current_state__name")


def _first_status_value(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    if not isinstance(row, Mapping):
        return None
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        return value
    return None


def exclude_tdc_scope_rows(
    report: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """剔除 TDC 同步范围外（已废弃/已撤回）的行；返回 (保留行, 丢弃数)。

    候选键序内首个非空状态值经 ``normalize_tdc_report_status`` 归一后与
    ``TDC_SYNC_EXCLUDED_STATUSES`` 判等；调用方须披露丢弃数（诊断渠道），
    不得静默少行。非 TDC 报表原样返回（丢弃数为 0）。
    """
    keys = TDC_STATUS_KEYS_BY_REPORT.get(report)
    if keys is None:
        return list(rows), 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        status_text = normalize_tdc_report_status(
            report, _first_status_value(row, keys)
        )
        if status_text in TDC_SYNC_EXCLUDED_STATUSES:
            dropped += 1
            continue
        kept.append(dict(row))
    return kept, dropped


def exclude_paa_cancel_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """剔除状态为 CANCEL 的 PAA 行；返回 (保留行, 丢弃数)。

    state 与 current_state__name 按候选键序读取（trim+upper 判等，任一命中
    即剔）；"cancel "、" Cancel " 等空白/大小写变体一律命中；其余状态值
    （DRAFT1/CLOSE 等）保留。调用方须披露丢弃数，不得静默少行。
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        value = _first_status_value(row, PAA_STATUS_KEYS)
        if value is not None and str(value).strip().upper() == "CANCEL":
            dropped += 1
            continue
        kept.append(dict(row))
    return kept, dropped
