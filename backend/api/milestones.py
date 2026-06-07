import logging

from fastapi import APIRouter

from api.response import error_response, success_response
from models.schemas import MilestoneCreate, MilestoneUpdate
from services.db import DBManager

logger = logging.getLogger("pm_toolbox.api.milestones")

router = APIRouter()


@router.get("/milestones")
async def list_milestones():
    try:
        items = DBManager.list_milestones()
        return success_response(items)
    except Exception as e:
        logger.exception("List milestones failed")
        return error_response("获取里程碑列表失败", status_code=500)


@router.post("/milestones")
async def create_milestone(body: MilestoneCreate):
    try:
        milestone = DBManager.create_milestone(body.model_dump())
        return success_response(milestone)
    except Exception as e:
        logger.exception("Create milestone failed")
        return error_response("创建里程碑失败", status_code=500)


@router.put("/milestones/{milestone_id}")
async def update_milestone(milestone_id: int, body: MilestoneUpdate):
    try:
        updated = DBManager.update_milestone(milestone_id, body.model_dump(exclude_none=True))
        if updated is None:
            return error_response(f"里程碑不存在: {milestone_id}", status_code=404)
        return success_response(updated)
    except Exception as e:
        logger.exception("Update milestone failed for %s", milestone_id)
        return error_response("更新里程碑失败", status_code=500)


@router.delete("/milestones/{milestone_id}")
async def delete_milestone(milestone_id: int):
    try:
        deleted = DBManager.delete_milestone(milestone_id)
        if not deleted:
            return error_response(f"里程碑不存在: {milestone_id}", status_code=404)
        return success_response(None)
    except Exception as e:
        logger.exception("Delete milestone failed for %s", milestone_id)
        return error_response("删除里程碑失败", status_code=500)
