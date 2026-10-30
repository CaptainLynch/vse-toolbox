# -*- coding: utf-8 -*-
"""任务中心统一路由（W13-03 迁自 web/app.py，路径/方法/信封/endpoint 名逐字保持）。

统一视图聚合三类后台任务（抓取 crawl / Excel / EWO 导表）；三类任务的生命周期
取消/重试语义各自独立（EWO 的 generation_unknown 红线在此冻结：仅人工核查，
禁止自动重发）。状态ful服务经 TasksRouteDeps 注入；闭包时代的共享助手
（_safe_attachment_basename / logger / _TASK_RESULT_MAX_BYTES）由别名还原。
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from flask import jsonify, request, send_file

logger = logging.getLogger(__name__)

_TASK_RESULT_MAX_BYTES = 64 * 1024 * 1024

#: 抓取任务类型的中文标题（随 W13-03 从 create_app 局部常量迁入）。
_CRAWL_TASK_TYPE_LABELS = {
    "paa_crawl": "Aras PAA 全量抓取",
    "paa_export": "Aras PAA 导出",
    "ewo_export": "Aras EWO 导出",
    "tdc_data_model_crawl": "TDC 数模审核全量抓取",
    "tdc_data_model_export": "TDC 数模审核导出",
    "tdc_sor_crawl": "TDC SOR 全量抓取",
    "tdc_sor_export": "TDC SOR 导出",
}


class TasksRouteDeps:
    """任务路由依赖包：create_app 显式注入。"""

    def __init__(
        self,
        *,
        db: Any,
        crawl_task_runner: Any | None,
        excel_admin_service: Any | None,
        excel_repository: Any | None,
        local_mutation_error: Callable[[], Any],
        json_error: Callable[..., Any],
        safe_attachment_basename: Callable[..., str],
    ) -> None:
        self.db = db
        self.crawl_task_runner = crawl_task_runner
        self.excel_admin_service = excel_admin_service
        self.excel_repository = excel_repository
        self.local_mutation_error = local_mutation_error
        self.json_error = json_error
        self.safe_attachment_basename = safe_attachment_basename


def register_tasks_routes(app: Any, deps: TasksRouteDeps) -> None:
    # 闭包别名：被搬运的实现按 create_app 内原名引用这些对象。
    crawl_task_runner = deps.crawl_task_runner
    excel_admin_service = deps.excel_admin_service
    db = deps.db
    excel_repository = deps.excel_repository
    _local_web_mutation_error = deps.local_mutation_error
    _json_error = deps.json_error
    _safe_attachment_basename = deps.safe_attachment_basename

    def _crawl_task_title(task_type: str | None, source: str | None) -> str:
        t = (task_type or "").lower()
        if t in _CRAWL_TASK_TYPE_LABELS:
            return _CRAWL_TASK_TYPE_LABELS[t]
        s = (source or "aras").upper()
        if "ewo" in t:
            return f"{s} EWO 数据查询与抓取"
        elif "paa" in t:
            return f"{s} PAA 报表查询"
        elif "ncr" in t:
            return f"{s} NCR 报表抓取"
        elif "sor" in t:
            return f"{s} SOR 导出任务"
        elif "model" in t or "data_model" in t:
            return f"{s} 数模审核报表抓取"
        elif "export" in t:
            return f"{s} 数据导出任务"
        return f"{s} {task_type or '后台任务'}"

    def _crawl_task_entry(ct: dict[str, Any]) -> dict[str, Any]:
        st = ct["status"]
        is_active = st in ("queued", "leased", "running")
        prog = {}
        if ct.get("progress_json"):
            try:
                prog = json.loads(ct["progress_json"])
            except Exception:
                pass
        art_path = ct.get("artifact_path")
        has_art = False
        if art_path:
            try:
                target_f = (crawl_task_runner.downloads_dir / art_path).resolve()
                has_art = (
                    target_f.is_file()
                    and target_f.is_relative_to(crawl_task_runner.downloads_dir.resolve())
                )
            except Exception:
                pass

        tid = ct["task_id"]
        # 仅注册了默认 handler 的任务类型可安全重试；抓取/导出任务的工作函数
        # 与请求上下文（会话、筛选）绑定，过期后须从面板重新提交。
        retryable = st in ("failed", "interrupted", "cancelled") and (
            crawl_task_runner is not None
            and crawl_task_runner.has_handler(ct.get("task_type") or "")
        )
        return {
            "id": tid if tid.startswith("crawl_") else f"crawl_{tid}",
            "raw_id": tid,
            "category": "crawl",
            "source": ct.get("source", "aras"),
            "task_type": ct.get("task_type", "query"),
            "title": _crawl_task_title(ct.get("task_type"), ct.get("source")),
            "status": st,
            "is_active": is_active,
            "progress": prog,
            "artifact_path": art_path if has_art else None,
            "has_artifact": has_art,
            "error_message": ct.get("error_message"),
            "created_at": ct.get("created_at"),
            "updated_at": ct.get("updated_at"),
            "can_cancel": is_active,
            "can_download": has_art and st == "succeeded",
            "can_retry": retryable,
            "manual_check_required": False,
        }

    def _excel_task_entry(et: dict[str, Any]) -> dict[str, Any]:
        st = et["status"]
        is_active = st in ("queued", "leased", "running")
        has_art = False
        try:
            arts = excel_admin_service.list_artifacts(et["id"])
            has_art = bool(arts)
        except Exception:
            pass
        return {
            "id": f"excel_{et['id']}",
            "raw_id": str(et["id"]),
            "category": "excel",
            "source": "excel",
            "task_type": et.get("operation", "transform"),
            "title": f"Excel {et.get('operation', '处理')}",
            "status": st,
            "is_active": is_active,
            "progress": {},
            "artifact_path": None,
            "has_artifact": has_art,
            "error_message": et.get("errorMessage"),
            "created_at": et.get("createdAt"),
            "updated_at": et.get("updatedAt"),
            "can_cancel": is_active,
            "can_download": has_art and st == "succeeded",
            "can_retry": False,
            "manual_check_required": False,
        }

    def _ewo_task_entry(ej: dict[str, Any]) -> dict[str, Any]:
        raw_st = ej["state"]
        is_active = raw_st in ("queued", "generating", "downloading")
        if raw_st == "queued":
            norm_st = "queued"
        elif raw_st in ("generating", "downloading"):
            norm_st = "running"
        elif raw_st in ("parsed", "generated"):
            norm_st = "succeeded"
        elif raw_st in ("generation_unknown",):
            norm_st = "failed"
        else:
            norm_st = raw_st

        has_art = bool(ej.get("file_id") or ej.get("snapshot_ref"))
        ewo_dl_dir = (Path(db.db_path).parent / "ewo-downloads").resolve()
        cand = []
        if ewo_dl_dir.exists():
            for f in ewo_dl_dir.iterdir():
                if f.is_file() and ej["id"] in f.name:
                    cand.append(f)
                    break
        if cand and cand[0].is_file():
            has_art = True

        c_ts = (
            datetime.fromtimestamp(ej["created"], tz=timezone.utc).isoformat()
            if ej.get("created")
            else ""
        )
        u_ts = (
            datetime.fromtimestamp(ej["updated"], tz=timezone.utc).isoformat()
            if ej.get("updated")
            else ""
        )

        # W3-3 冻结重试语义：generation_unknown 仅允许人工核查，禁止自动重发。
        manual_check = raw_st == "generation_unknown"
        return {
            "id": f"ewo_{ej['id']}",
            "raw_id": ej["id"],
            "category": "ewo",
            "source": "aras",
            "task_type": "ewo_export",
            "title": f"Aras EWO 增强导表 ({ej.get('scope', 'default')})",
            "status": norm_st,
            "raw_status": raw_st,
            "is_active": is_active,
            "progress": {},
            "artifact_path": cand[0].name if cand else None,
            "has_artifact": has_art,
            "error_message": None,
            "created_at": c_ts,
            "updated_at": u_ts,
            "can_cancel": is_active,
            "can_download": has_art and norm_st == "succeeded",
            "can_retry": raw_st in ("interrupted", "failed"),
            "manual_check_required": manual_check,
        }

    def _find_unified_task_entry(task_id: str) -> dict[str, Any] | None:
        tid = task_id.strip()
        if crawl_task_runner is not None:
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(tid.removeprefix("crawl_"))
            if ct is not None:
                return _crawl_task_entry(ct)
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            try:
                et = excel_admin_service.get_task(int(raw_ex_id))
                return _excel_task_entry(et)
            except KeyError:
                pass
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ej = EWOExportJobs(db.db_path).get_job(raw_ewo_id)
                if ej is not None:
                    return _ewo_task_entry(ej)
            except Exception:
                pass
        return None

    @app.get("/api/tasks")
    def api_tasks_list():
        category = request.args.get("category", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        raw_limit = request.args.get("limit")
        try:
            limit = max(1, min(int(raw_limit), 200)) if raw_limit else 50
        except (ValueError, TypeError):
            limit = 50

        aggregated: list[dict[str, Any]] = []

        # 1. crawl_tasks
        if crawl_task_runner is not None and (not category or category == "crawl"):
            try:
                for ct in crawl_task_runner.list_tasks(limit=limit * 2):
                    aggregated.append(_crawl_task_entry(ct))
            except Exception:
                logger.exception("Failed to query crawl_tasks for unified task list")

        # 2. excel_tasks
        if excel_admin_service is not None and (not category or category == "excel"):
            try:
                for et in excel_admin_service.list_tasks(limit=limit * 2):
                    aggregated.append(_excel_task_entry(et))
            except Exception:
                logger.exception("Failed to query excel_tasks for unified task list")

        # 3. ewo_export_jobs（EWO 增强导表任务）
        if (not category or category == "ewo"):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ewo_jobs = EWOExportJobs(db.db_path).list_jobs(limit=limit * 2)
                for ej in ewo_jobs:
                    aggregated.append(_ewo_task_entry(ej))
            except Exception:
                logger.exception("Failed to query ewo_export_jobs for unified task list")

        # Compute accurate total active count from database indices
        active_crawl = db.count_active_crawl_tasks() if hasattr(db, "count_active_crawl_tasks") else 0
        active_excel = 0
        if excel_repository is not None:
            try:
                with db.get_connection() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM excel_tasks WHERE status IN ('queued', 'leased', 'running')"
                    ).fetchone()
                    active_excel = int(row[0]) if row else 0
            except Exception:
                pass
        active_ewo = 0
        try:
            from core.ewo_export_jobs import EWOExportJobs
            active_ewo = EWOExportJobs(db.db_path).count_active_jobs()
        except Exception:
            pass
        active_count = active_crawl + active_excel + active_ewo

        if status_filter == "active":
            aggregated = [t for t in aggregated if t["is_active"]]
        elif status_filter in ("history", "finished"):
            aggregated = [t for t in aggregated if not t["is_active"]]
        elif status_filter:
            aggregated = [t for t in aggregated if t["status"] == status_filter]

        aggregated.sort(key=lambda t: t.get("created_at") or "", reverse=True)
        paged = aggregated[:limit]

        response = jsonify({
            "ok": True,
            "data": {
                "tasks": paged,
                "active_count": active_count,
                "total_count": len(aggregated),
            }
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/tasks/<task_id>/cancel")
    def api_tasks_cancel(task_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error

        tid = task_id.strip()

        # 1. Try crawl task
        if crawl_task_runner is not None:
            raw_tid = tid.removeprefix("crawl_")
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(raw_tid)
            if ct is not None:
                if ct["status"] not in ("queued", "leased", "running"):
                    return _json_error(409, "Conflict", f"Task is already {ct['status']}")
                crawl_task_runner.cancel_task(ct["task_id"])
                return jsonify({"ok": True, "data": {"taskId": task_id, "status": "cancelled"}})

        # 2. Try excel task
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            ex_id = int(raw_ex_id)
            try:
                et = excel_admin_service.get_task(ex_id)
                if et["status"] not in ("queued", "leased", "running"):
                    return _json_error(409, "Conflict", f"Task is already {et['status']}")
                excel_admin_service.cancel_task(ex_id)
                return jsonify({"ok": True, "data": {"taskId": task_id, "status": "cancelled"}})
            except KeyError:
                pass

        # 3. Try EWO export job
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ewo_jobs = EWOExportJobs(db.db_path)
                ej = ewo_jobs.get_job(raw_ewo_id)
                if ej is not None:
                    if ej["state"] not in ("queued", "generating", "downloading"):
                        return _json_error(409, "Conflict", f"Task is already {ej['state']}")
                    ewo_jobs.cancel(raw_ewo_id)
                    return jsonify({"ok": True, "data": {"taskId": task_id, "status": "cancelled"}})
            except Exception:
                pass

        return _json_error(404, "NotFound", f"Task '{task_id}' was not found")

    @app.post("/api/tasks/<task_id>/retry")
    def api_tasks_retry(task_id: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error

        tid = task_id.strip()

        # 1. Try crawl task retry
        if crawl_task_runner is not None:
            raw_tid = tid.removeprefix("crawl_")
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(raw_tid)
            if ct is not None:
                if ct["status"] not in ("failed", "cancelled", "interrupted"):
                    return _json_error(409, "Conflict", f"Task cannot be retried (current status: {ct['status']})")
                try:
                    new_id = crawl_task_runner.retry_task(ct["task_id"])
                    return jsonify({"ok": True, "data": {"taskId": ct["task_id"], "newTaskId": new_id, "status": "queued"}})
                except (RuntimeError, ValueError) as exc:
                    return _json_error(400, "CannotRetry", str(exc))

        # 2. Try excel task retry (Excel transformations are not retry-safe per policy)
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            ex_id = int(raw_ex_id)
            try:
                excel_admin_service.get_task(ex_id)
                return _json_error(400, "CannotRetry", "Excel batch tasks must be re-submitted from Excel Toolbox")
            except KeyError:
                pass

        # 3. Try EWO export job retry
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ewo_jobs = EWOExportJobs(db.db_path)
                ej = ewo_jobs.get_job(raw_ewo_id)
                if ej is not None:
                    # 业务红线：generation_unknown 表示外部生成结果未知，
                    # 严禁自动重发，仅允许人工核查后再处理。
                    if ej["state"] == "generation_unknown":
                        return _json_error(
                            409,
                            "ManualCheckRequired",
                            "EWO 生成结果未知，禁止自动重发；请先人工核查该任务的生成状态",
                        )
                    if ej["state"] not in ("interrupted", "failed"):
                        return _json_error(409, "Conflict", f"EWO job cannot be retried (current state: {ej['state']})")
                    try:
                        targets = json.loads(ej["item_ids"]) if ej.get("item_ids") else []
                    except (TypeError, ValueError):
                        return _json_error(500, "ServerError", "EWO job selection data is corrupted")
                    if not targets:
                        return _json_error(409, "Conflict", "EWO job has no selection to retry")
                    try:
                        new_job = ewo_jobs.create(ej["scope"], targets)
                    except ValueError as exc:
                        return _json_error(400, "CannotRetry", str(exc))
                    return jsonify({"ok": True, "data": {"taskId": task_id, "newTaskId": f"ewo_{new_job['id']}", "status": "queued"}})
            except Exception:
                logger.exception("EWO export job retry failed")
                return _json_error(500, "ServerError", "EWO export job retry failed")

        return _json_error(404, "NotFound", f"Task '{task_id}' was not found")

    @app.get("/api/tasks/<task_id>/download")
    def api_tasks_download(task_id: str):
        tid = task_id.strip()

        # 1. Try crawl task artifact
        if crawl_task_runner is not None:
            raw_tid = tid.removeprefix("crawl_")
            ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(raw_tid)
            if ct is not None:
                art_rel = ct.get("artifact_path")
                if not art_rel:
                    return _json_error(404, "NotFound", "Task has no artifact")
                downloads_dir = crawl_task_runner.downloads_dir.resolve()
                try:
                    target_file = (downloads_dir / art_rel).resolve()
                    if not target_file.is_relative_to(downloads_dir):
                        return _json_error(403, "Forbidden", "Unsafe artifact path")
                except (ValueError, RuntimeError):
                    return _json_error(403, "Forbidden", "Unsafe artifact path")
                if not target_file.is_file():
                    return _json_error(404, "NotFound", "Artifact file not found")
                safe_name = _safe_attachment_basename(target_file.name, fallback="artifact.xlsx")
                response = send_file(
                    target_file,
                    as_attachment=True,
                    download_name=safe_name,
                )
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response

        # 2. Try excel task artifact
        raw_ex_id = tid.removeprefix("excel_")
        if raw_ex_id.isdigit() and excel_admin_service is not None:
            ex_id = int(raw_ex_id)
            try:
                excel_admin_service.get_task(ex_id)
                arts = excel_admin_service.list_artifacts(ex_id)
                if not arts:
                    return _json_error(404, "NotFound", "Task has no artifact")
                artifact = excel_admin_service.prepare_artifact_download(arts[0]["id"])
                response = send_file(
                    io.BytesIO(artifact.data),
                    mimetype=artifact.mimetype,
                    as_attachment=True,
                    download_name=_safe_attachment_basename(
                        artifact.display_name,
                        fallback="excel-artifact.xlsx",
                    ),
                )
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response
            except KeyError:
                pass
            except Exception:
                pass

        # 3. Try EWO export artifact
        raw_ewo_id = tid.removeprefix("ewo_").strip()
        if raw_ewo_id and re.fullmatch(r"[0-9a-fA-F-]{8,64}", raw_ewo_id):
            try:
                from core.ewo_export_jobs import EWOExportJobs
                ej = EWOExportJobs(db.db_path).get_job(raw_ewo_id)
                if ej is not None:
                    ewo_dl_dir = (Path(db.db_path).parent / "ewo-downloads").resolve()
                    if ewo_dl_dir.exists():
                        for f in ewo_dl_dir.iterdir():
                            if f.is_file() and raw_ewo_id in f.name:
                                target_file = f.resolve()
                                try:
                                    if not target_file.is_relative_to(ewo_dl_dir):
                                        continue
                                except (ValueError, RuntimeError):
                                    continue
                                safe_name = _safe_attachment_basename(target_file.name, fallback="ewo-export.xlsx")
                                response = send_file(
                                    target_file,
                                    as_attachment=True,
                                    download_name=safe_name,
                                )
                                response.headers["Cache-Control"] = "no-store"
                                response.headers["X-Content-Type-Options"] = "nosniff"
                                return response
                    return _json_error(404, "NotFound", "Task has no artifact")
            except Exception:
                pass

        return _json_error(404, "NotFound", f"Artifact for task '{task_id}' was not found")

    @app.get("/api/tasks/<task_id>")
    def api_tasks_get(task_id: str):
        entry = _find_unified_task_entry(task_id.strip())
        if entry is None:
            return _json_error(404, "NotFound", f"Task '{task_id}' was not found")
        response = jsonify({"ok": True, "data": entry})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/tasks/<task_id>/result")
    def api_tasks_result(task_id: str):
        """读取成功后台抓取任务的结果 JSON（与原同步响应 data 同构）。"""
        if crawl_task_runner is None:
            return _json_error(503, "TaskEngineUnavailable", "后台任务引擎未初始化")
        tid = task_id.strip()
        ct = crawl_task_runner.get_task(tid) or crawl_task_runner.get_task(tid.removeprefix("crawl_"))
        if ct is None:
            return _json_error(404, "NotFound", f"Task '{task_id}' was not found")
        if ct["status"] != "succeeded":
            return _json_error(
                409,
                "Conflict",
                f"Task result is only available after success (current: {ct['status']})",
            )
        art_rel = ct.get("artifact_path")
        if not art_rel or not art_rel.lower().endswith(".json"):
            return _json_error(404, "NotFound", "Task has no JSON result artifact")
        downloads_dir = crawl_task_runner.downloads_dir.resolve()
        try:
            target_file = (downloads_dir / art_rel).resolve()
            if not target_file.is_relative_to(downloads_dir):
                return _json_error(403, "Forbidden", "Unsafe artifact path")
        except (ValueError, RuntimeError):
            return _json_error(403, "Forbidden", "Unsafe artifact path")
        if not target_file.is_file():
            return _json_error(404, "NotFound", "Result artifact file not found")
        if target_file.stat().st_size > _TASK_RESULT_MAX_BYTES:
            return _json_error(413, "PayloadTooLarge", "Task result artifact exceeds size limit")
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _json_error(500, "ServerError", "Task result artifact is unreadable")
        response = jsonify({"ok": True, "data": data})
        response.headers["Cache-Control"] = "no-store"
        return response

