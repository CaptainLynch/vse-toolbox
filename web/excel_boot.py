# -*- coding: utf-8 -*-
"""Excel 领域路由（W13-04 迁自 web/app.py，路径/方法/信封/endpoint 名逐字保持）。

任务提交/查询/产物下载与 Worker 启停——Worker 的自动管理对用户不可见，
这里的启停路由是专家模式与内部运维入口（服务端仍强制本机写保护）。
状态ful服务经 ExcelRouteDeps 注入；闭包时代共享助手由别名还原。
"""

from __future__ import annotations

import io
import logging
from typing import Any, Callable

from flask import jsonify, request, send_file

from core.excel_tasks import ExcelIdempotencyConflictError
from services.excel_task_admin import ExcelArtifactUnavailableError, ExcelTaskAdminValidationError

logger = logging.getLogger(__name__)


def _worker_autostart(controller: Any | None) -> dict[str, Any]:
    """提交后自动拉起唯一 Worker 进程（契约 2）；失败只降级为状态值，不影响任务创建。

    控制器没有 `ensure_running`（如 in_process 模式）时视为 unavailable。
    """
    ensure = getattr(controller, "ensure_running", None) if controller is not None else None
    if not callable(ensure):
        return {"state": "unavailable"}
    try:
        result = ensure(reason="submit")
    except Exception:
        logger.exception("Excel worker auto start failed")
        return {"state": "failed", "error": "Excel 处理进程自动启动失败，请手动启动或稍后重试"}
    if isinstance(result, dict):
        return dict(result)
    return {"state": "unknown"}


class ExcelRouteDeps:
    """Excel 路由依赖包：create_app 显式注入。"""

    def __init__(
        self,
        *,
        excel_admin_service: Any | None,
        excel_worker_controller: Any | None,
        local_mutation_error: Callable[[], Any],
        json_error: Callable[..., Any],
        validation_error: Callable[[dict], Any],
        safe_attachment_basename: Callable[..., str],
    ) -> None:
        self.excel_admin_service = excel_admin_service
        self.excel_worker_controller = excel_worker_controller
        self.local_mutation_error = local_mutation_error
        self.json_error = json_error
        self.validation_error = validation_error
        self.safe_attachment_basename = safe_attachment_basename


def register_excel_routes(app: Any, deps: ExcelRouteDeps) -> None:
    # 闭包别名：被搬运的实现按 create_app 内原名引用这些对象。
    excel_admin_service = deps.excel_admin_service
    excel_worker_controller = deps.excel_worker_controller
    _local_web_mutation_error = deps.local_mutation_error
    _json_error = deps.json_error
    _project_status_validation_error = deps.validation_error
    _safe_attachment_basename = deps.safe_attachment_basename

    @app.get("/api/excel-roots")
    def api_excel_roots_list():
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_roots()
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            logger.exception("Excel roots list failed")
            return _json_error(500, "ServerError", "Excel roots query failed")

    @app.post("/api/excel-tasks")
    def api_excel_tasks_create():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = excel_admin_service.create_task(payload)
            # 任务已落库（queued）后才尝试自动启动：启动失败也保持 200/queued。
            try:
                data["workerAutoStart"] = _worker_autostart(excel_worker_controller)
            except Exception:
                logger.exception("Excel worker auto start hook failed")
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except ExcelIdempotencyConflictError:
            return _json_error(
                409,
                "Conflict",
                "Idempotency key was already used for a different request",
            )
        except Exception:
            logger.exception("Excel task creation failed")
            return _json_error(500, "ServerError", "Excel task creation failed")

    @app.get("/api/excel-tasks")
    def api_excel_tasks_list():
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_tasks(
                request.args.get("status"),
                request.args.get("limit"),
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except Exception:
            logger.exception("Excel task list failed")
            return _json_error(500, "ServerError", "Excel task query failed")

    @app.get("/api/excel-worker/status")
    def api_excel_worker_status():
        if excel_worker_controller is None:
            return _json_error(503, "NotConfigured", "Excel worker is not configured")
        response = jsonify({"ok": True, "data": excel_worker_controller.status().to_dict()})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/excel-worker/start")
    def api_excel_worker_start():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if excel_worker_controller is None:
            return _json_error(503, "NotConfigured", "Excel worker is not configured")
        try:
            status = excel_worker_controller.start()
            response = jsonify({"ok": True, "data": status.to_dict()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except RuntimeError:
            return _json_error(409, "Conflict", "Excel worker is already running")
        except Exception:
            logger.exception("Excel worker start failed")
            return _json_error(500, "ServerError", "Excel worker start failed")

    @app.post("/api/excel-worker/stop")
    def api_excel_worker_stop():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if excel_worker_controller is None:
            return _json_error(503, "NotConfigured", "Excel worker is not configured")
        try:
            status = excel_worker_controller.stop()
            response = jsonify({"ok": True, "data": status.to_dict()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception:
            logger.exception("Excel worker stop failed")
            return _json_error(500, "ServerError", "Excel worker stop failed")

    @app.get("/api/excel-tasks/<int:task_id>")
    def api_excel_task_detail(task_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.get_task(task_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel task was not found")
        except Exception:
            logger.exception("Excel task detail failed")
            return _json_error(500, "ServerError", "Excel task query failed")

    @app.get("/api/excel-tasks/<int:task_id>/runs")
    def api_excel_task_runs(task_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_runs(task_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel task was not found")
        except Exception:
            logger.exception("Excel task runs failed")
            return _json_error(500, "ServerError", "Excel task query failed")

    @app.get("/api/excel-tasks/<int:task_id>/artifacts")
    def api_excel_task_artifacts(task_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_artifacts(task_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel task was not found")
        except Exception:
            logger.exception("Excel task artifacts failed")
            return _json_error(500, "ServerError", "Excel artifact query failed")

    @app.get("/api/excel-artifacts/<int:artifact_id>")
    def api_excel_artifact_detail(artifact_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.get_artifact(artifact_id)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel artifact was not found")
        except Exception:
            logger.exception("Excel artifact detail failed")
            return _json_error(500, "ServerError", "Excel artifact query failed")

    @app.get("/api/excel-artifacts/<int:artifact_id>/download")
    def api_excel_artifact_download(artifact_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            artifact = excel_admin_service.prepare_artifact_download(artifact_id)
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
            return _json_error(404, "NotFound", "Excel artifact was not found")
        except ExcelArtifactUnavailableError:
            return _json_error(
                409,
                "ArtifactUnavailable",
                "Excel artifact is unavailable or failed integrity validation",
            )
        except Exception:
            logger.exception("Excel artifact download failed")
            return _json_error(500, "ServerError", "Excel artifact download failed")

    @app.get("/api/excel-artifacts/<int:artifact_id>/download-audit")
    def api_excel_artifact_download_audit(artifact_id: int):
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.list_artifact_download_audits(
                artifact_id,
                limit=request.args.get("limit"),
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "Excel artifact was not found")
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except Exception:
            logger.exception("Excel artifact download audit query failed")
            return _json_error(500, "ServerError", "Excel artifact download audit query failed")

    @app.get("/api/excel-artifacts/retention-plan")
    def api_excel_artifacts_retention_plan():
        if excel_admin_service is None:
            return _json_error(503, "NotConfigured", "Excel task roots are not configured")
        try:
            data = excel_admin_service.plan_retention(
                retention_days=request.args.get("retentionDays"),
                limit=request.args.get("limit"),
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ExcelTaskAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except Exception:
            logger.exception("Excel artifact retention plan query failed")
            return _json_error(500, "ServerError", "Excel artifact retention plan query failed")

