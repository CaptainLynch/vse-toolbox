# -*- coding: utf-8 -*-
"""TIR数据简表 plugin backend. Routes are mounted at /api/p/tir-report/.

从帆软报表平台导出 ``tdc/TIR/TIR数据简表.cpt``，交付帆软原样导出的 xlsx（方案见
``docs/TIR_REPORT_PLUGIN_DESIGN_20261009.md``）。所有写路由先过 ``ctx.local_guard()``。

- GET  state                 默认筛选、自动导出设置与上次自动导出结果、域账号是否已保存、最近产物
- POST config                保存默认筛选与自动导出设置（不接收账号口令）

账号用统一域账号（宿主 ``domain_credential_vault``，DPAPI）；自动导出由 Windows 计划任务调用
``tools/tir_export_cli.py --once``（安装：``tools/install_tir_export_task.ps1``），页面只负责开关与时间。
- POST export                提交导出任务；同组筛选在排队/运行中复用该任务，当日已有成功产物直接复用
- GET  export/<task_id>      任务进度与结果
- GET  files                 产物清单
- GET  files/<day>/<name>    下载 xlsx
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any, Mapping

from flask import request, send_file

from core.domain_identity import DPAPICredentialProvider

from . import protocol as P
from . import service as S
from .client import TirError

def session_factory() -> Any:
    from services.windows_http import WinHTTPSession

    return WinHTTPSession(timeout=60)


def _today() -> date:
    return date.today()


def register(host):
    ctx = host.context
    bp = host.blueprint
    data_dir = host.data_dir
    submit_lock = threading.Lock()

    def body() -> Mapping[str, Any]:
        value = request.get_json(silent=True)
        return value if isinstance(value, Mapping) else {}

    def guarded(handler):
        def wrapper(*args, **kwargs):
            guard = ctx.local_guard()
            if guard is not None:
                return guard
            try:
                return handler(*args, **kwargs)
            except P.ProtocolError as exc:
                return ctx.json_error(400, "ValidationError", str(exc))
        wrapper.__name__ = handler.__name__
        return wrapper

    def runner() -> Any:
        return ctx.service("crawl_task_runner")

    def credential_provider() -> Any:
        try:
            return DPAPICredentialProvider(ctx.service("domain_credential_vault"))
        except LookupError:
            return None

    def domain_ready() -> bool:
        provider = credential_provider()
        return provider is not None and provider.is_available(S.DOMAIN_REF)

    def worker(task_ctx: Any) -> None:
        params = task_ctx.params if isinstance(task_ctx.params, Mapping) else {}
        filters = P.normalize_filters(params.get("filters") or {}, today=_today())
        meta = S.run_export(
            filters,
            data_dir=data_dir,
            credential_provider=credential_provider(),
            session_factory=session_factory,
            today=_today(),
            force=bool(params.get("force")),
            progress=lambda stage, percent: task_ctx.update_progress(stage=stage, percent=percent),
            cancelled=lambda: task_ctx.is_cancelled,
        )
        task_ctx.update_progress({"result": _result_view(meta)}, stage="done", percent=100)

    try:
        runner().register_handler(S.TASK_TYPE, worker)  # 有默认处理器，宿主「重试」才可用
    except LookupError:
        pass

    def _result_view(meta: Mapping[str, Any]) -> dict[str, Any]:
        keys = ("ok", "rows", "headerCheck", "stem", "day", "reused", "filters")
        return {key: meta.get(key) for key in keys if key in meta}

    @bp.get("/state")
    def state():
        config = S.load_config(data_dir)
        return ctx.json_ok({
            "config": config,
            "domainCredentialReady": domain_ready(),
            "autoState": S.load_auto_state(data_dir),
            "report": {"name": P.REPORT_NAME, "path": P.REPORT_PATH},
            "today": _today().isoformat(),
            "exports": S.list_exports(data_dir, limit=20),
        })

    @bp.post("/config")
    @guarded
    def save_config():
        value = body()
        config = S.load_config(data_dir)
        if "auto" in value:
            config["auto"] = S.validate_auto(value.get("auto"))
        defaults = value.get("defaults")
        if isinstance(defaults, Mapping):
            merged = {**config["defaults"], **{k: v for k, v in defaults.items() if k in config["defaults"]}}
            checked = P.normalize_filters({**merged, "endDate": _today().isoformat()}, today=_today())
            config["defaults"] = {"project": checked.project, "department": checked.department,
                                  "section": checked.section, "startDate": checked.start_date}
        S.save_config(data_dir, config)
        return ctx.json_ok({"config": config})

    @bp.post("/export")
    @guarded
    def export():
        value = body()
        force = value.get("force", False)
        if not isinstance(force, bool):
            raise P.ProtocolError("force 必须是布尔值")
        filters = P.normalize_filters(value, today=_today())
        if not domain_ready():
            return ctx.json_error(409, "credential_missing", TirError("credential_missing").args[0])
        if not force:
            cached = S.find_cached(data_dir, _today().isoformat(), filters)
            if cached is not None:
                return ctx.json_ok({"taskId": None, "status": "succeeded", "reused": True,
                                    "result": _result_view({**cached, "day": _today().isoformat(), "reused": True})})
        try:
            task_runner = runner()
        except LookupError as exc:
            return ctx.json_error(409, "SyncNotReady", str(exc))
        with submit_lock:  # 查重与提交原子化，避免两次点击各起一个任务
            for task in task_runner.list_tasks(source=S.TASK_SOURCE, limit=20):
                if task.get("status") in ("queued", "running"):
                    view = S.task_view(task)
                    if view["filters"] == filters.as_payload():
                        return ctx.json_ok({**view, "reused": True})
            task_id = task_runner.submit_task(S.TASK_TYPE, S.TASK_SOURCE, S.task_params(filters, force))
        task = task_runner.get_task(task_id) or {"task_id": task_id, "status": "queued"}
        return ctx.json_ok({**S.task_view(task), "reused": False})

    @bp.get("/export/<task_id>")
    def export_status(task_id: str):
        if not S.valid_task_id(task_id):
            return ctx.json_error(400, "ValidationError", "无效的任务编号")
        try:
            task = runner().get_task(task_id)
        except LookupError as exc:
            return ctx.json_error(409, "SyncNotReady", str(exc))
        if task is None or task.get("source") != S.TASK_SOURCE:
            return ctx.json_error(404, "NotFound", "没有这个导出任务")
        view = S.task_view(task)
        if view["error"]:
            view["error"] = ctx.redact(str(view["error"]))
        return ctx.json_ok(view)

    @bp.get("/files")
    def files():
        return ctx.json_ok({"exports": S.list_exports(data_dir, limit=100)})

    @bp.get("/files/<day>/<name>")
    def download(day: str, name: str):
        target = S.safe_file_path(data_dir, day, name)
        if target is None:
            return ctx.json_error(404, "NotFound", "没有这个文件")
        return send_file(target, mimetype=S.XLSX_MIME, as_attachment=True, download_name=f"{P.REPORT_NAME}_{name}")
