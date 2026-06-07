import asyncio
import logging

from fastapi import APIRouter, Query

from api.response import error_response, success_response
from models.schemas import FeishuSyncResult, TodoToggleRequest, TodoToggleResult
from services.db import DBManager
from services.feishu_service import FeishuService

logger = logging.getLogger("VSE_TOOLBOX.api.feishu")

router = APIRouter()


@router.get("/feishu/mails")
async def list_mails(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None),
    is_read: int | None = Query(default=None),
):
    try:
        items, total = DBManager.list_mails(
            page=page, size=size, category=category, is_read=is_read
        )
        return success_response({"items": items, "total": total})
    except Exception as e:
        logger.exception("List mails failed")
        return error_response("获取邮件列表失败", status_code=500)


@router.post("/feishu/sync")
async def sync_mails():
    try:
        result = await asyncio.to_thread(FeishuService.sync_mails)
        return success_response(
            FeishuSyncResult(
                synced_count=result["synced_count"],
                new_count=result["new_count"],
                demo=result.get("demo", False),
            ).model_dump()
        )
    except Exception as e:
        logger.exception("Sync mails failed")
        return error_response("同步邮件失败", status_code=500)


@router.get("/feishu/todos")
async def list_todos():
    try:
        todos = DBManager.list_todos()
        return success_response(todos)
    except Exception as e:
        logger.exception("List todos failed")
        return error_response("获取待办列表失败", status_code=500)


@router.post("/feishu/todo-toggle")
async def toggle_todo(request: TodoToggleRequest):
    try:
        result = DBManager.toggle_todo(request.id)
        if result is None:
            return error_response(f"待办不存在: {request.id}", status_code=404)
        return success_response(
            TodoToggleResult(id=result["id"], completed=result["completed"]).model_dump()
        )
    except Exception as e:
        logger.exception("Toggle todo failed")
        return error_response("切换待办状态失败", status_code=500)
