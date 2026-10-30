# -*- coding: utf-8 -*-
"""原件留存（原自动归档）领域路由（W13-05 迁自 web/app.py，路径/方法/信封/endpoint 逐字保持）。

目录与配置审计、任务增删改查、运行记录与产物、手动立即同步。原文件中这些路由
与其他注册交错，本模块把它们聚合为单一注册入口。
状态ful服务经 ArchiveRouteDeps 注入；共享助手 _archive_history_limit 随迁。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from flask import jsonify, request

from core.archive_store import ArchiveSafetyError
from core.db_common import ArchiveJobNotReadyError, ArchiveLeaseBusyError
from services.scheduled_archive_admin import ArchiveAdminValidationError
from core.settings_store import validate_local_directory
from core.native_folder_picker import NativeFolderPickerError, choose_native_folder

logger = logging.getLogger(__name__)


def _archive_history_limit(value: Any, default: int = 100) -> int:
    """Parse archive history limits strictly; invalid input is never defaulted."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("limit must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("limit must be a positive integer") from exc
    if parsed < 1:
        raise ValueError("limit must be a positive integer")
    return parsed


class ArchiveRouteDeps:
    """原件留存路由依赖包：create_app 显式注入。"""

    def __init__(
        self,
        *,
        db: Any,
        archive_admin_service: Any | None,
        excel_admin_service: Any | None,
        sanitize_error_message: Callable[[Exception], str],
        local_mutation_error: Callable[[], Any],
        json_ok: Callable[..., Any],
        json_error: Callable[..., Any],
        validation_error: Callable[[dict], Any],
    ) -> None:
        self.db = db
        self.archive_admin_service = archive_admin_service
        self.excel_admin_service = excel_admin_service
        self.sanitize_error_message = sanitize_error_message
        self.local_mutation_error = local_mutation_error
        self.json_ok = json_ok
        self.json_error = json_error
        self.validation_error = validation_error


def register_archive_routes(app: Any, deps: ArchiveRouteDeps) -> None:
    # 闭包别名：被搬运的实现按 create_app 内原名引用这些对象。
    db = deps.db
    archive_admin_service = deps.archive_admin_service
    excel_admin_service = deps.excel_admin_service
    _sanitize_error_message = deps.sanitize_error_message
    _local_web_mutation_error = deps.local_mutation_error
    _json_ok = deps.json_ok
    _json_error = deps.json_error
    _project_status_validation_error = deps.validation_error

    @app.get("/api/scheduled-archive/folders")
    def api_scheduled_archive_folders():
        try:
            data = archive_admin_service.list_folders(request.args.get("path", ""))
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except FileNotFoundError:
            return _json_error(404, "NotFound", "未找到归档目录")
        except ArchiveSafetyError as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except OSError:
            logger.exception("scheduled archive folder query failed")
            return _json_error(500, "ServerError", "无法读取归档目录")

    @app.post("/api/scheduled-archive/folders/native")
    def api_scheduled_archive_native_folder():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        if app.config.get("TESTING"):
            return _json_error(503, "NativeFolderPickerUnavailable", "测试环境不打开本机文件夹选择器")
        payload = request.get_json(silent=True) or {}
        initial_directory = payload.get("path", "") if isinstance(payload, dict) else ""
        if not isinstance(initial_directory, str):
            return _project_status_validation_error({"path": "必须是本机目录字符串"})
        try:
            data = archive_admin_service.pick_native_folder(initial_directory)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except NativeFolderPickerError as exc:
            return _json_error(503, "NativeFolderPickerUnavailable", _sanitize_error_message(exc))
        except FileNotFoundError:
            return _json_error(404, "NotFound", "未找到归档目录")
        except ArchiveSafetyError as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except OSError:
            logger.exception("scheduled archive native folder picker failed")
            return _json_error(500, "ServerError", "无法选择归档目录")

    @app.get("/api/scheduled-archive/jobs")
    def api_scheduled_archive_jobs():
        try:
            response = jsonify({"ok": True, "data": archive_admin_service.list_jobs()})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("scheduled archive jobs query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/scheduled-archive/jobs")
    def api_scheduled_archive_job_create():
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = archive_admin_service.create_job(payload)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response, 201
        except ArchiveAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except (KeyError, ValueError) as exc:
            return _project_status_validation_error({"request": _sanitize_error_message(exc)})

    @app.patch("/api/scheduled-archive/jobs/<job_key>")
    def api_scheduled_archive_job_update(job_key: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(400, "ValidationError", "JSON object body is required")
        try:
            data = archive_admin_service.update_job(job_key, payload)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ArchiveAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except (ArchiveLeaseBusyError, RuntimeError):
            return _json_error(409, "Conflict", "任务正在运行或配置已更新，请刷新后重试")
        except ArchiveJobNotReadyError:
            return _json_error(409, "NotReady", "启用任务前必须配置凭据引用")
        except (ArchiveSafetyError, TypeError, ValueError) as exc:
            return _project_status_validation_error(
                {"request": _sanitize_error_message(exc)}
            )
        except Exception as exc:
            logger.exception("scheduled archive job update failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.delete("/api/scheduled-archive/jobs/<job_key>")
    def api_scheduled_archive_job_archive(job_key: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        payload = request.get_json(silent=True) or {}
        try:
            data = archive_admin_service.archive_job(
                job_key,
                payload.get("updatedAt") if isinstance(payload, dict) else None,
            )
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except ArchiveAdminValidationError as exc:
            return _project_status_validation_error(exc.fields)
        except KeyError:
            return _json_error(404, "NotFound", "未找到定时任务")
        except RuntimeError:
            return _json_error(409, "Conflict", "任务配置已更新，请刷新后重试")
        except ValueError as exc:
            return _project_status_validation_error({"request": _sanitize_error_message(exc)})

    @app.get("/api/scheduled-archive/runs")
    def api_scheduled_archive_runs():
        job_key = request.args.get("jobKey") or None
        try:
            limit = _archive_history_limit(request.args.get("limit"))
            data = archive_admin_service.list_runs(job_key, limit)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("scheduled archive runs query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/scheduled-archive/runs/<int:run_id>/artifacts")
    def api_scheduled_archive_artifacts(run_id: int):
        try:
            if db.get_archive_run(run_id) is None:
                return _json_error(404, "NotFound", "未找到归档运行")
            data = {
                "runId": run_id,
                "artifacts": archive_admin_service.list_artifacts(run_id),
            }
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as exc:
            logger.exception("scheduled archive artifacts query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.get("/api/scheduled-archive/config-audit")
    def api_scheduled_archive_config_audit():
        job_key = request.args.get("jobKey") or None
        try:
            limit = _archive_history_limit(request.args.get("limit"))
            data = archive_admin_service.list_audit(job_key, limit)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except (TypeError, ValueError) as exc:
            return _json_error(422, "ValidationError", _sanitize_error_message(exc))
        except Exception as exc:
            logger.exception("scheduled archive audit query failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

    @app.post("/api/scheduled-archive/jobs/<job_key>/sync-now")
    def api_scheduled_archive_sync_now(job_key: str):
        local_error = _local_web_mutation_error()
        if local_error is not None:
            return local_error
        try:
            data = archive_admin_service.sync_now(job_key)
            response = jsonify({"ok": True, "data": data})
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return _json_error(404, "NotFound", "未找到归档任务")
        except Exception as exc:
            logger.exception("scheduled archive sync-now failed")
            return _json_error(500, "ServerError", _sanitize_error_message(exc))

