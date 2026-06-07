import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from api.response import success_response, error_response
from services.db import DBManager
from models.schemas import TIRCreate, TIRUpdate, ExcelImportResult

logger = logging.getLogger("VSE_TOOLBOX.api.tir")

router = APIRouter(prefix="/tir", tags=["tir"])


@router.get("")
def list_tirs(page: int = 1, size: int = 20, status: str | None = None, category: str | None = None):
    try:
        items, total = DBManager.list_tirs(page, size, status, category)
        return success_response({"items": items, "total": total, "page": page, "size": size})
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.get("/stats")
def get_tir_stats():
    try:
        return success_response(DBManager.get_tir_stats())
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.post("")
def create_tir(body: TIRCreate):
    try:
        item = DBManager.create_tir(body.model_dump())
        return success_response(item)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.put("/{tir_id}")
def update_tir(tir_id: str, body: TIRUpdate):
    try:
        item = DBManager.update_tir(tir_id, body.model_dump(exclude_unset=True))
        if not item:
            return error_response("TIR not found", status_code=404)
        return success_response(item)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.delete("/{tir_id}")
def delete_tir(tir_id: str):
    try:
        ok = DBManager.delete_tir(tir_id)
        if not ok:
            return error_response("TIR not found", status_code=404)
        return success_response({"deleted": True})
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.post("/import-excel")
async def import_tir_excel(files: UploadFile = File(...)):
    """从 Excel 导入 TIR。R-03: 使用 with 语句管理文件。"""
    from services.excel_import_service import import_tir_from_excel

    tmp_path = None
    try:
        suffix = Path(files.filename).suffix if files.filename else ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await files.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        result = import_tir_from_excel(tmp_path, source_file=files.filename)
        return success_response(ExcelImportResult(**result).model_dump())
    except Exception as e:
        logger.exception("Import TIR Excel failed")
        return error_response("导入失败，请检查文件格式", status_code=500)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass