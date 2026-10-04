# -*- coding: utf-8 -*-
"""数模设计审核流程报表的「关注清单」同步范围（3D单签署日报 v2.0 规格 §9 S1、S8、S9、S11）。

关注清单是一组流水单号，和同步范围一起存进 ``tdc_data_model`` 归档任务的
``filters_json``（``syncScope``、``watchlist`` 两个键，不加表）。同一份清单同时约束
两条会发布数模表单快照的路径：

- 自动归档（``ArchiveSyncRunner`` + ``TDCArchiveConnector``）；
- 交付物自动同步（``ProjectStatusSyncRunner`` + ``TDCProjectStatusConnector``）。

TDC 查询参数里没有流水单号：``incident`` 对应的是第 0 列「实例号」（core/report_contracts.py），
所以两条路径都仍抓全量，只在落库前按清单保留（规格 §9「不能」分支：速度不变，结果正确）。
每份快照在 ``schema["coverage"]`` 里记录覆盖范围（S11）。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

from services.form_search import snapshot_schema

JOB_KEY = "tdc_data_model"
SCOPE_ALL = "all"
SCOPE_WATCHLIST = "watchlist"
#: filters_json 整体上限 16 KB（core/repos/archive_jobs.py），清单另给 12 KB 预算。
MAX_WATCHLIST = 500
MAX_WATCHLIST_BYTES = 12 * 1024
MAX_SERIAL_LENGTH = 64
FILTER_KEYS = frozenset({"syncScope", "watchlist"})
#: 官方导出行的表头是「流水单号」；接口行里流水单号是 documentNo（incident 是实例号，不是流水单号）。
_SERIAL_KEYS = ("流水单号", "documentNo")


class WatchlistError(ValueError):
    pass


def normalize_serial(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > MAX_SERIAL_LENGTH or any(ord(ch) < 32 for ch in text):
        raise WatchlistError("流水单号必须是 1–64 个可见字符")
    return text


def watchlist_settings(filters: Mapping[str, Any] | None) -> tuple[str, tuple[str, ...]]:
    """filters_json -> (同步范围, 关注清单)；校验并去重，保持顺序。"""
    filters = filters or {}
    scope = filters.get("syncScope", SCOPE_ALL)
    if scope not in (SCOPE_ALL, SCOPE_WATCHLIST):
        raise WatchlistError("同步范围只能是 all 或 watchlist")
    raw = filters.get("watchlist", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > MAX_WATCHLIST:
        raise WatchlistError(f"关注清单必须是不超过 {MAX_WATCHLIST} 个流水单号的数组")
    serials = tuple(dict.fromkeys(normalize_serial(item) for item in raw))
    if len(json.dumps(list(serials), ensure_ascii=False).encode("utf-8")) > MAX_WATCHLIST_BYTES:
        raise WatchlistError("关注清单过长，请分批关注或改用全部表单")
    return scope, serials


def normalized_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    """校验后把规范化的同步范围和清单写回；没设置过的键不加。"""
    scope, serials = watchlist_settings(filters)
    result = dict(filters)
    if "syncScope" in filters:
        result["syncScope"] = scope
    if "watchlist" in filters:
        result["watchlist"] = list(serials)
    return result


def tdc_query_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    """去掉清单相关的键，剩下的才是发给 TDC 的查询条件。"""
    return {key: value for key, value in filters.items() if key not in FILTER_KEYS}


def row_serial(row: Mapping[str, Any]) -> str:
    """官方导出行用表头「流水单号」，接口行用 ``documentNo``（见 core/report_contracts.py 第 2 列）。"""
    for key in _SERIAL_KEYS:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def apply_watchlist(
    rows: Iterable[Mapping[str, Any]],
    scope: str,
    serials: Sequence[str],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """-> (保留的行, 覆盖范围)。全部范围原样返回；关注清单范围只留清单里的单号（S1），
    清单里在 TDC 查不到的单号记在 ``missing``，不从清单删除（S8）。"""
    rows = list(rows)
    if scope != SCOPE_WATCHLIST:
        return rows, {"kind": SCOPE_ALL}
    wanted = set(serials)
    kept = [row for row in rows if row_serial(row) in wanted]
    found = {row_serial(row) for row in kept}
    return kept, {
        "kind": SCOPE_WATCHLIST,
        "serials": list(serials),
        "missing": [serial for serial in serials if serial not in found],
    }


def load_watchlist(db: Any) -> tuple[str, tuple[str, ...]]:
    """从 tdc_data_model 归档任务读同步范围和清单；任务缺失或配置非法时按全部处理。"""
    try:
        jobs = db.list_archive_jobs()
    except Exception:  # noqa: BLE001 - 读不到配置时不改变既有同步行为
        return SCOPE_ALL, ()
    job = next((item for item in jobs if item.get("job_key") == JOB_KEY), None)
    if job is None:
        return SCOPE_ALL, ()
    try:
        filters = json.loads(job.get("filters_json") or "{}")
        return watchlist_settings(filters if isinstance(filters, Mapping) else {})
    except (ValueError, WatchlistError):
        return SCOPE_ALL, ()


def snapshot_coverage(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """表单快照的覆盖范围；没记录的旧快照都是全量（S11）。"""
    schema = snapshot_schema(snapshot)
    coverage = schema.get("coverage") if schema else None
    if isinstance(coverage, Mapping) and coverage.get("kind") == SCOPE_WATCHLIST:
        return dict(coverage)
    return {"kind": SCOPE_ALL}


def latest_full_snapshot(db: Any, form_key: str = JOB_KEY, limit: int = 60) -> dict[str, Any] | None:
    """最近一次覆盖范围为全部的表单快照（S11）。"""
    for snapshot in db.list_deliverable_form_snapshots(form_key, limit=limit):
        if snapshot_coverage(snapshot)["kind"] == SCOPE_ALL:
            return snapshot
    return None
