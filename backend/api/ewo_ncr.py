import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from api.response import success_response, error_response
from services.db import DBManager
from models.schemas import EWOCreate, EWOUpdate, ExcelImportResult

logger = logging.getLogger("VSE_TOOLBOX.api.ewo")

router = APIRouter(prefix="/ewo", tags=["ewo"])


@router.get("")
def list_ewos(page: int = 1, size: int = 20, status: str | None = None, severity: str | None = None):
    try:
        items, total = DBManager.list_ewos(page, size, status, severity)
        return success_response({"items": items, "total": total, "page": page, "size": size})
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.get("/stats")
def get_ewo_stats():
    try:
        return success_response(DBManager.get_ewo_stats())
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.post("")
def create_ewo(body: EWOCreate):
    try:
        item = DBManager.create_ewo(body.model_dump())
        return success_response(item)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.put("/{ewo_id}")
def update_ewo(ewo_id: str, body: EWOUpdate):
    try:
        item = DBManager.update_ewo(ewo_id, body.model_dump(exclude_unset=True))
        if not item:
            return error_response("EWO/NCR not found", status_code=404)
        return success_response(item)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.delete("/{ewo_id}")
def delete_ewo(ewo_id: str):
    try:
        ok = DBManager.delete_ewo(ewo_id)
        if not ok:
            return error_response("EWO/NCR not found", status_code=404)
        return success_response({"deleted": True})
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.post("/import-excel")
async def import_ewo_excel(files: UploadFile = File(...)):
    """从 Excel 导入 EWO/NCR。R-03: 使用 with 语句管理文件。"""
    from services.excel_import_service import import_ewo_from_excel

    tmp_path = None
    try:
        suffix = Path(files.filename).suffix if files.filename else ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await files.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        result = import_ewo_from_excel(tmp_path, source_file=files.filename)
        return success_response(ExcelImportResult(**result).model_dump())
    except Exception as e:
        logger.exception("Import EWO Excel failed")
        return error_response("导入失败，请检查文件格式", status_code=500)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass