# -*- coding: utf-8 -*-
"""Project overview plugin backend. Routes are mounted at /api/p/project-overview/.

页面主要调用宿主已有的 /api/project-status*、/api/deliverable-forms/*、
/api/scheduled-archive/*、/api/tasks* 等接口（含本机写保护与租约逻辑）。
本插件只补数模设计审核流程报表的两组接口（3D单签署日报规格 §9）：

- GET  form-terms      多值搜索结果摘要：匹配几份表单、哪些词没有匹配（S2–S4）
- GET  watchlist       关注清单与同步范围；清单里在 TDC 查不到的单号标「未找到」（S8）
- POST watchlist       加入、移除、清空、改同步范围（S1、S6）；经归档任务服务写入，
                       沿用其校验、乐观锁和配置审计（S21）
- GET  watchlist.csv   导出关注清单（S6）
"""

from __future__ import annotations

import csv
import io
from typing import Any, Mapping

from flask import Response, request

from services import data_model_watchlist as W
from services import form_search

FORM_KEY = "tdc_data_model"
_ACTIONS = {"add", "remove", "clear", "scope"}


class _Invalid(ValueError):
    pass


def _job(admin: Any) -> Mapping[str, Any]:
    job = next((item for item in admin.list_jobs() if item.get("jobKey") == W.JOB_KEY), None)
    if job is None:
        raise LookupError("未找到数模设计审核流程报表的同步任务")
    return job


def _watchlist_view(db: Any, job: Mapping[str, Any]) -> dict[str, Any]:
    scope, serials = W.watchlist_settings(job.get("filters") or {})
    present = form_search.form_serials(db, FORM_KEY)
    latest = db.get_latest_deliverable_form_snapshot(FORM_KEY)
    coverage = W.snapshot_coverage(latest)
    reported_missing = set(coverage.get("missing") or ())
    synced = latest is not None
    items = [
        {"serial": serial, "found": (serial in present and serial not in reported_missing) if synced else None}
        for serial in serials
    ]
    return {
        "scope": scope,
        "items": items,
        "count": len(serials),
        "missing": [item["serial"] for item in items if item["found"] is False],
        "jobUpdatedAt": job.get("updatedAt"),
        "jobEnabled": bool(job.get("enabled")),
        "snapshotCoverage": coverage.get("kind"),
        "placeholder": form_search.PLACEHOLDER,
        "limit": W.MAX_WATCHLIST,
        "configIssue": "待配置：关注清单为空" if scope == W.SCOPE_WATCHLIST and not serials else None,
    }


def _apply(job: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    action = body.get("action")
    if action not in _ACTIONS:
        raise _Invalid("action 只能是 add、remove、clear、scope")
    filters = dict(job.get("filters") or {})
    scope, serials = W.watchlist_settings(filters)
    incoming = body.get("serials", [])
    if not isinstance(incoming, list) or len(incoming) > W.MAX_WATCHLIST:
        raise _Invalid(f"serials 必须是不超过 {W.MAX_WATCHLIST} 个流水单号的数组")
    try:
        cleaned = [W.normalize_serial(item) for item in incoming]
    except W.WatchlistError as exc:
        raise _Invalid(str(exc)) from None
    if action == "add":
        serials = tuple(dict.fromkeys([*serials, *cleaned]))
    elif action == "remove":
        drop = set(cleaned)
        serials = tuple(s for s in serials if s not in drop)
    elif action == "clear":
        serials = ()
    else:
        scope = body.get("scope")
        if scope not in (W.SCOPE_ALL, W.SCOPE_WATCHLIST):
            raise _Invalid("同步范围只能是 all 或 watchlist")
    filters.update({"syncScope": scope, "watchlist": list(serials)})
    try:
        W.watchlist_settings(filters)
    except W.WatchlistError as exc:
        raise _Invalid(str(exc)) from None
    return filters


def register(host):
    ctx = host.context
    bp = host.blueprint

    @bp.get("/form-terms")
    def form_terms():
        form_key = request.args.get("formKey") or FORM_KEY
        terms = form_search.parse_terms(request.args.get("terms"))
        try:
            data = form_search.term_summary(ctx.db, form_key, terms)
        except KeyError:
            return ctx.json_error(404, "NotFound", "未找到表单")
        return ctx.json_ok({**data, "placeholder": form_search.PLACEHOLDER})

    def admin():
        return ctx.service("scheduled_archive_admin")

    @bp.get("/watchlist")
    def watchlist():
        try:
            return ctx.json_ok(_watchlist_view(ctx.db, _job(admin())))
        except LookupError as exc:
            return ctx.json_error(404, "NotFound", str(exc))
        except W.WatchlistError as exc:
            return ctx.json_error(409, "WatchlistInvalid", str(exc))

    @bp.post("/watchlist")
    def watchlist_update():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return ctx.json_error(400, "ValidationError", "请求体必须是 JSON 对象")
        try:
            service = admin()
            job = _job(service)
            filters = _apply(job, body)
            updated = service.update_job(W.JOB_KEY, {
                "enabled": bool(job.get("enabled")),
                "filters": filters,
                "outputSubdir": str(job.get("outputSubdir") or ""),
                "updatedAt": str(job.get("updatedAt") or ""),
            })
        except _Invalid as exc:
            return ctx.json_error(400, "ValidationError", str(exc))
        except LookupError as exc:
            return ctx.json_error(404, "NotFound", str(exc))
        except W.WatchlistError as exc:
            return ctx.json_error(409, "WatchlistInvalid", str(exc))
        except Exception as exc:  # noqa: BLE001 - 归档任务服务的校验与并发冲突原样带回
            fields = getattr(exc, "fields", None) or getattr(exc, "errors", None)
            message = "；".join(f"{k}：{v}" for k, v in dict(fields).items()) if isinstance(fields, Mapping) else str(exc)
            return ctx.json_error(409, "WatchlistUpdateFailed", ctx.redact(message or "保存关注清单失败"))
        return ctx.json_ok(_watchlist_view(ctx.db, updated))

    @bp.get("/watchlist.csv")
    def watchlist_csv():
        try:
            view = _watchlist_view(ctx.db, _job(admin()))
        except (LookupError, W.WatchlistError) as exc:
            return ctx.json_error(404, "NotFound", str(exc))
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(["流水单号", "状态"])
        for item in view["items"]:
            writer.writerow([item["serial"], {True: "已找到", False: "未找到", None: "未同步"}[item["found"]]])
        response = Response("﻿" + buffer.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=\"watchlist.csv\""
        response.headers["Cache-Control"] = "no-store"
        return response
