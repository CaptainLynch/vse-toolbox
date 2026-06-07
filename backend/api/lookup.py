"""零件总成/工程师自动关联 API。R-02: SQL 参数化。"""

import logging

from fastapi import APIRouter, Query

from api.response import error_response, success_response
from models.schemas import PartSystemCreate, PartSystemOut, EngineerCreate, EngineerOut
from services.db import DBManager

logger = logging.getLogger("VSE_TOOLBOX.api.lookup")

router = APIRouter(prefix="/lookup", tags=["lookup"])


# ---------------------------------------------------------------------------
# 零件总成
# ---------------------------------------------------------------------------

@router.get("/part-system")
def search_part_system(q: str = Query(default="", max_length=200)):
    """模糊搜索零件总成→子系统映射。"""
    try:
        items = DBManager.search_part_system(q)
        return success_response([PartSystemOut(**item).model_dump() for item in items])
    except Exception as e:
        logger.exception("Search part system failed")
        return error_response("查询零件总成失败", status_code=500)


@router.post("/part-system")
def create_part_system(body: PartSystemCreate):
    """新增零件总成→子系统映射。"""
    try:
        item = DBManager.create_part_system(body.model_dump())
        return success_response(PartSystemOut(**item).model_dump())
    except Exception as e:
        logger.exception("Create part system failed")
        return error_response(f"创建映射失败: {str(e)}", status_code=400)


# ---------------------------------------------------------------------------
# 工程师
# ---------------------------------------------------------------------------

@router.get("/engineer")
def search_engineer(q: str = Query(default="", max_length=200)):
    """模糊搜索工程师→科室映射。"""
    try:
        items = DBManager.search_engineer(q)
        return success_response([EngineerOut(**item).model_dump() for item in items])
    except Exception as e:
        logger.exception("Search engineer failed")
        return error_response("查询工程师失败", status_code=500)


@router.post("/engineer")
def create_engineer(body: EngineerCreate):
    """新增工程师→科室映射。"""
    try:
        item = DBManager.create_engineer(body.model_dump())
        return success_response(EngineerOut(**item).model_dump())
    except Exception as e:
        logger.exception("Create engineer failed")
        return error_response(f"创建映射失败: {str(e)}", status_code=400)
