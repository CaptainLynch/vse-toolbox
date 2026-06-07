import logging

from fastapi import APIRouter, Query

from api.response import error_response, success_response
from models.schemas import IssueCreate, IssueOut, IssueUpdate, PaginatedData
from services.db import DBManager

logger = logging.getLogger("VSE_TOOLBOX.api.issues")

router = APIRouter()


@router.get("/issues")
async def list_issues(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    priority: str | None = Query(default=None),
    status: str | None = Query(default=None),
    department: str | None = Query(default=None),
):
    try:
        items, total = DBManager.list_issues(
            page=page,
            size=size,
            priority=priority,
            status=status,
            department=department,
        )
        result = PaginatedData(
            items=[IssueOut(**item) for item in items],
            total=total,
            page=page,
            size=size,
        )
        return success_response(result.model_dump())
    except Exception as e:
        logger.exception("List issues failed")
        return error_response("查询问题列表失败", status_code=500)


@router.post("/issues")
async def create_issue(body: IssueCreate):
    try:
        issue = DBManager.create_issue(body.model_dump())
        return success_response(IssueOut(**issue).model_dump())
    except Exception as e:
        logger.exception("Create issue failed")
        return error_response("创建问题失败", status_code=500)


@router.put("/issues/{issue_id}")
async def update_issue(issue_id: str, body: IssueUpdate):
    try:
        existing = DBManager.get_issue_by_id(issue_id)
        if not existing:
            return error_response(f"问题不存在: {issue_id}", status_code=404)

        updated = DBManager.update_issue(issue_id, body.model_dump(exclude_none=True))
        if not updated:
            return error_response(f"更新问题失败: {issue_id}", status_code=500)

        return success_response(IssueOut(**updated).model_dump())
    except Exception as e:
        logger.exception("Update issue failed for %s", issue_id)
        return error_response("更新问题失败", status_code=500)


@router.delete("/issues/{issue_id}")
async def delete_issue(issue_id: str):
    try:
        deleted = DBManager.delete_issue(issue_id)
        if not deleted:
            return error_response(f"问题不存在: {issue_id}", status_code=404)
        return success_response(None)
    except Exception as e:
        logger.exception("Delete issue failed for %s", issue_id)
        return error_response("删除问题失败", status_code=500)


@router.get("/issues/stats")
async def get_issue_stats():
    try:
        stats = DBManager.get_issue_stats()
        return success_response(stats)
    except Exception as e:
        logger.exception("Get issue stats failed")
        return error_response("获取统计失败", status_code=500)
