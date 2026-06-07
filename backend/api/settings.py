"""应用配置 API。R-02: SQL 参数化。"""

import logging

from fastapi import APIRouter

from api.response import error_response, success_response
from models.schemas import SettingUpdate
from services.db import DBManager

logger = logging.getLogger("VSE_TOOLBOX.api.settings")

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings():
    """获取全部设置项。"""
    try:
        settings = DBManager.get_all_settings()
        return success_response(settings)
    except Exception as e:
        logger.exception("Get settings failed")
        return error_response("获取设置失败", status_code=500)


@router.put("/{key}")
def update_setting(key: str, body: SettingUpdate):
    """更新单个设置项。"""
    try:
        result = DBManager.set_setting(key, body.value)
        return success_response(result)
    except Exception as e:
        logger.exception("Update setting failed for %s", key)
        return error_response(f"更新设置失败: {str(e)}", status_code=500)
