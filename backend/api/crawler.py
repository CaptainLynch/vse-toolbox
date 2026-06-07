import asyncio
import logging

from fastapi import APIRouter

from api.response import error_response, success_response
from models.schemas import CrawlerFetchRequest, CrawlerFetchResult, CrawlerTableRequest, CrawlerTableResult
from services.crawler_service import get_driver_manager

logger = logging.getLogger("VSE_TOOLBOX.api.crawler")

router = APIRouter()


@router.post("/crawler/fetch")
async def crawler_fetch(request: CrawlerFetchRequest):
    try:
        mgr = get_driver_manager()
        result = await asyncio.to_thread(mgr.fetch_page, request.url)
        return success_response(CrawlerFetchResult(**result).model_dump())
    except ValueError as e:
        logger.warning("Crawler fetch validation error: %s", e)
        return error_response(str(e))
    except RuntimeError as e:
        logger.error("Crawler fetch runtime error: %s", e)
        return error_response(str(e), status_code=500)
    except Exception as e:
        logger.exception("Crawler fetch failed for url")
        return error_response("页面抓取失败", status_code=500)


@router.post("/crawler/table")
async def crawler_table(request: CrawlerTableRequest):
    try:
        mgr = get_driver_manager()
        result = await asyncio.to_thread(mgr.extract_table, request.url, request.xpath)
        return success_response(CrawlerTableResult(**result).model_dump())
    except ValueError as e:
        logger.warning("Crawler table validation error: %s", e)
        return error_response(str(e))
    except RuntimeError as e:
        logger.error("Crawler table runtime error: %s", e)
        return error_response(str(e), status_code=500)
    except Exception as e:
        logger.exception("Crawler table failed for url")
        return error_response("表格提取失败", status_code=500)
