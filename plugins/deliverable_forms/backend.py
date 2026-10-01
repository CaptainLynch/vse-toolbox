# -*- coding: utf-8 -*-
"""Deliverable forms plugin: read-only analysis rows from stored form snapshots.

Routes (mounted at /api/p/deliverable-forms/):
- GET forms                     表单清单，来自 core/form_registry.py
- GET forms/<form_key>/rows     最新快照的明细行，按表单关键列展平成 {列名: 值}

只读已采集的快照，不触发同步、不解析凭据。旧的 /api/deliverable-forms/* 保持不变。
"""

from __future__ import annotations

from core import form_registry
from services.deliverable_form_analysis import form_definition

# 与旧页面 overdueStateLabels 保持同一口径。
OVERDUE_LABELS = {
    "overdue": "逾期风险",
    "on_time": "按期推进",
    "unknown": "未判定",
    "not_applicable": "已完成 / 不适用",
}


def _cell(values, index):
    if index >= len(values):
        return None
    value = values[index]
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def flatten_rows(form_key, snapshot_rows):
    """Flatten stored rows to {key-column label: value} plus normalized fields."""
    definition = form_definition(form_key)
    terminal = form_registry.get_form(form_key).terminal_statuses
    labels = {int(column["index"]): str(column.get("label") or "") for column in definition["columns"]}
    key_indexes = [index for index in definition["keyColumns"] if labels.get(index)]
    flattened = []
    for position, row in enumerate(snapshot_rows):
        values = row.get("values") or []
        dimensions = row.get("dimensions") or {}
        item = {"id": row.get("rowKey") or f"row-{position}"}
        for index in key_indexes:
            item[labels[index]] = _cell(values, index)
        status = dimensions.get("status") or None
        item["_status"] = status
        # 三态：True 完成 / False 未完成 / None 终态（计入总数，不算完成也不算未完成），与旧汇总口径一致。
        item["_completed"] = None if status in terminal else bool(row.get("isCompleted"))
        item["_overdue"] = OVERDUE_LABELS.get(str(row.get("overdueState")), "未判定")
        flattened.append(item)
    return flattened


def register(host):
    ctx = host.context
    bp = host.blueprint

    @bp.get("/forms")
    def forms():
        return ctx.json_ok([
            {"formKey": spec.form_key, "title": spec.title, "source": spec.source, "report": spec.report}
            for spec in form_registry.FORMS
        ])

    @bp.get("/forms/<form_key>/rows")
    def form_rows(form_key):
        if form_key not in form_registry.FORM_KEYS:
            return ctx.json_error(404, "NotFound", "未找到交付物表单")
        latest = ctx.db.get_latest_deliverable_form_snapshot(form_key)
        if latest is None:
            return ctx.json_ok({"rows": [], "updatedAt": None})
        rows = ctx.db.list_deliverable_form_snapshot_rows(int(latest["id"]))
        return ctx.json_ok({
            "rows": flatten_rows(form_key, rows),
            "updatedAt": latest.get("snapshot_at"),
        })
