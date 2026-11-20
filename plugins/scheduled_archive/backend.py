# -*- coding: utf-8 -*-
"""Scheduled-archive plugin backend.

任务管理页面仍调用宿主的 ``/api/scheduled-archive/*`` 接口（宿主已做本机写保护）。

本插件只加一组接口：**iBOM 报表手工导入**（数模 TDC + iBOM 双源方案 §6 用途 A）。
上传的 iBOM「数模设计审核流程报表」暂存一份，并立即触发一次 ``tdc_data_model`` 归档；
那次运行用这份文件代替 iBOM 自动抓取，TDC 侧照常在线抓取并合并。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from flask import request

from services.data_model_dual_source import IBOM_DUAL_SOURCE_ENV, dual_source_enabled, tdc_side_retired
from services.ibom_manual_feed import MAX_FEED_BYTES, IBOMManualFeedStore, ManualFeedError, feed_dir_for

DATA_MODEL_JOB_KEY = "tdc_data_model"


def register(host):
    ctx = host.context
    bp = host.blueprint
    # 与归档运行器同一目录：数据库所在目录（create_production_archive_runner）。
    store = IBOMManualFeedStore(feed_dir_for(Path(ctx.data_dir)))

    @bp.get("/ibom-manual-feed")
    def ibom_manual_feed_status():
        return ctx.json_ok({
            "enabled": dual_source_enabled(),
            "switch": IBOM_DUAL_SOURCE_ENV,
            "tdcRetired": tdc_side_retired(),
            "pending": store.pending(),
            "maxBytes": MAX_FEED_BYTES,
        })

    @bp.post("/ibom-manual-feed")
    def ibom_manual_feed_upload():
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        if not dual_source_enabled():
            return ctx.json_error(
                409, "DualSourceDisabled",
                f"未开启 iBOM 双源（环境变量 {IBOM_DUAL_SOURCE_ENV}=1），手工导入不会被使用",
            )
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return ctx.json_error(400, "ValidationError", "请选择 iBOM 报表文件（.xlsx 或 Unicode 文本 .txt）")
        content = upload.read(MAX_FEED_BYTES + 1)
        try:
            data_date = date.fromisoformat(str(request.form.get("dataDate") or "").strip())
        except ValueError:
            return ctx.json_error(400, "ValidationError", "请填写数据日期（YYYY-MM-DD）")
        try:
            meta = store.put(content, file_name=upload.filename, data_date=data_date)
        except ManualFeedError as exc:
            return ctx.json_error(422, exc.code, str(exc))
        try:
            archive: Any = ctx.service("scheduled_archive_admin")
            result = archive.sync_now(DATA_MODEL_JOB_KEY)
        except KeyError:
            store.clear()
            return ctx.json_error(404, "NotFound", "未找到数模设计审核流程归档任务")
        except LookupError:
            store.clear()
            return ctx.json_error(503, "ServiceUnavailable", "归档服务不可用")
        return ctx.json_ok({"feed": meta, "sync": result, "pendingAfterSync": store.pending()})
