import logging
import os

from fastapi import APIRouter

from api.response import error_response, success_response
from models.schemas import DeliverablePPTRequest, TemplateInfo, WeeklyPPTRequest
from services.ppt_service import generate_deliverable_ppt, generate_weekly_ppt, OUTPUT_DIR, MASTER_DIR

logger = logging.getLogger("VSE_TOOLBOX.api.ppt")

router = APIRouter()

# 模板定义
TEMPLATES = [
    {
        "id": "weekly_report",
        "name": "项目周报",
        "description": "周度问题统计与进度汇报",
        "file": "weekly_report_master.pptx",
    },
    {
        "id": "deliverable",
        "name": "交付物报告",
        "description": "单个交付物状态跟踪",
        "file": "deliverable_master.pptx",
    },
]


def _count_slides(template_file: str) -> int:
    """统计模板幻灯片数量。"""
    from pptx import Presentation

    path = MASTER_DIR / template_file
    if not path.exists():
        return 0
    try:
        prs = Presentation(str(path))
        return len(prs.slides)
    except Exception:
        logger.warning("Failed to count slides for %s", template_file, exc_info=True)
        return 0


@router.get("/ppt/templates")
async def list_templates():
    try:
        items = []
        for t in TEMPLATES:
            items.append(
                TemplateInfo(
                    id=t["id"],
                    name=t["name"],
                    description=t["description"],
                    slides=_count_slides(t["file"]),
                ).model_dump()
            )
        return success_response(items)
    except Exception as e:
        logger.exception("List templates failed")
        return error_response("获取模板列表失败", status_code=500)


@router.post("/ppt/weekly")
async def create_weekly_ppt(request: WeeklyPPTRequest):
    try:
        result = generate_weekly_ppt(
            week_start=request.week_start,
            project_name=request.project_name,
            author=request.author,
        )
        return success_response(result)
    except FileNotFoundError as e:
        logger.warning("Template not found: %s", e)
        return error_response("母版模板不存在")
    except Exception as e:
        logger.exception("Generate weekly PPT failed")
        return error_response("生成周报 PPT 失败", status_code=500)


@router.post("/ppt/deliverable")
async def create_deliverable_ppt(request: DeliverablePPTRequest):
    try:
        result = generate_deliverable_ppt(
            deliverable_name=request.deliverable_name,
            responsible=request.responsible,
        )
        return success_response(result)
    except FileNotFoundError as e:
        logger.warning("Template not found: %s", e)
        return error_response("母版模板不存在")
    except Exception as e:
        logger.exception("Generate deliverable PPT failed")
        return error_response("生成交付物 PPT 失败", status_code=500)
