import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from api.response import error_response, success_response
from config import TEMP_DIR, safe_path
from models.schemas import ExcelMergeResult, ExcelMergeSameResult, ExcelRenameRequest, ExcelRenameResult
from services.excel_service import batch_rename, merge_excel, merge_same_structure

logger = logging.getLogger("VSE_TOOLBOX.api.excel")

router = APIRouter()


@router.post("/excel/merge")
async def excel_merge(files: list[UploadFile] = File(...)):
    if not files:
        return error_response("未上传文件")

    saved_paths: list[Path] = []
    try:
        for upload in files:
            if not upload.filename:
                continue
            safe_name = Path(upload.filename).name
            dest = TEMP_DIR / safe_name
            with open(dest, "wb") as f:
                shutil.copyfileobj(upload.file, f)
            saved_paths.append(dest)

        if not saved_paths:
            return error_response("没有有效的文件")

        result = merge_excel(saved_paths, TEMP_DIR)
        return success_response(ExcelMergeResult(**result).model_dump())
    except ValueError as e:
        logger.warning("Excel merge validation error: %s", e)
        return error_response(str(e))
    except RuntimeError as e:
        logger.error("Excel merge runtime error: %s", e)
        return error_response(str(e), status_code=500)
    except Exception as e:
        logger.exception("Excel merge failed")
        return error_response("合并失败", status_code=500)
    finally:
        for upload in files:
            upload.file.close()
        for p in saved_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/excel/merge-same")
async def excel_merge_same(
    files: list[UploadFile] = File(...),
    header_row: int = Form(default=0),
):
    if not files:
        return error_response("未上传文件")

    saved_paths: list[Path] = []
    try:
        for upload in files:
            if not upload.filename:
                continue
            safe_name = Path(upload.filename).name
            dest = TEMP_DIR / safe_name
            with open(dest, "wb") as f:
                shutil.copyfileobj(upload.file, f)
            saved_paths.append(dest)

        if not saved_paths:
            return error_response("没有有效的文件")

        result = merge_same_structure(saved_paths, TEMP_DIR, header_row=header_row)
        return success_response(ExcelMergeSameResult(**result).model_dump())
    except ValueError as e:
        logger.warning("Excel merge-same validation error: %s", e)
        return error_response(str(e))
    except RuntimeError as e:
        logger.error("Excel merge-same runtime error: %s", e)
        return error_response(str(e), status_code=500)
    except Exception as e:
        logger.exception("Excel merge-same failed")
        return error_response("拼接失败", status_code=500)
    finally:
        for upload in files:
            upload.file.close()
        for p in saved_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/excel/rename")
async def excel_rename(request: ExcelRenameRequest):
    try:
        folder = Path(request.folder).resolve()
        if not folder.exists() or not folder.is_dir():
            return error_response(f"目录不存在: {request.folder}")
        result = batch_rename(folder, request.pattern, request.replacement)
        return success_response(ExcelRenameResult(**result).model_dump())
    except ValueError as e:
        logger.warning("Excel rename validation error: %s", e)
        return error_response(str(e))
    except Exception as e:
        logger.exception("Excel rename failed")
        return error_response("改名失败", status_code=500)
