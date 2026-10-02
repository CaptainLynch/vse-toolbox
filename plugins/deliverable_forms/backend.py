# -*- coding: utf-8 -*-
"""Deliverable forms plugin: read-only analysis rows from stored form snapshots.

Routes (mounted at /api/p/deliverable-forms/):
- GET forms                     表单清单，来自 core/form_registry.py
- GET forms/<form_key>/rows     最新快照的明细行，按表单页面列展平成 {列名: 值}
- GET registry                  表单注册表（含维度显示名、页面列），供页面与旧前端共用

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


# 归一化维度展平为 _<维度> 字段，页面按维度筛选/分组，不依赖各表单列名。
DIMENSIONS = ("department", "section", "model", "stage")


def _column_indexes(form_key, definition):
    by_label = {}
    for column in definition["columns"]:
        label = str(column.get("label") or "").strip()
        if label and label not in by_label:
            by_label[label] = int(column["index"])
    return [(label, by_label[label]) for label in form_registry.get_form(form_key).page_columns if label in by_label]


def flatten_rows(form_key, snapshot_rows):
    """Flatten stored rows to {page-column label: value} plus normalized fields."""
    definition = form_definition(form_key)
    terminal = form_registry.get_form(form_key).terminal_statuses
    columns = _column_indexes(form_key, definition)
    flattened = []
    for position, row in enumerate(snapshot_rows):
        values = row.get("values") or []
        dimensions = row.get("dimensions") or {}
        item = {"id": row.get("rowKey") or f"row-{position}"}
        for label, index in columns:
            item[label] = _cell(values, index)
        for dimension in DIMENSIONS:
            item["_" + dimension] = dimensions.get(dimension) or None
        item["_submitted"] = row.get("submittedDate") or None
        status = dimensions.get("status") or None
        item["_status"] = status
        # 三态：True 完成 / False 未完成 / None 终态（计入总数，不算完成也不算未完成），与旧汇总口径一致。
        item["_completed"] = None if status in terminal else bool(row.get("isCompleted"))
        item["_overdue"] = OVERDUE_LABELS.get(str(row.get("overdueState")), "未判定")
        flattened.append(item)
    return flattened


def registry_entry(spec):
    return {
        "formKey": spec.form_key,
        "title": spec.title,
        "source": spec.source,
        "report": spec.report,
        "dimensionLabels": {key: spec.dimension_label(key) for key in ("status",) + DIMENSIONS},
        "pageColumns": list(spec.page_columns),
        "terminalStatuses": sorted(spec.terminal_statuses),
    }


def register(host):
    ctx = host.context
    bp = host.blueprint

    @bp.get("/forms")
    def forms():
        items = []
        for spec in form_registry.FORMS:
            latest = ctx.db.get_latest_deliverable_form_snapshot(spec.form_key)
            items.append({
                "formKey": spec.form_key,
                "title": spec.title,
                "source": spec.source,
                "report": spec.report,
                # 页面 id 用报表名（plugin.json 的页面 id 只允许小写）。
                "page": spec.report,
                "updatedAt": latest.get("snapshot_at") if latest else None,
                "rowCount": int(latest.get("row_count") or 0) if latest else 0,
            })
        return ctx.json_ok(items)

    @bp.get("/registry")
    def registry():
        return ctx.json_ok([registry_entry(spec) for spec in form_registry.FORMS])

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
