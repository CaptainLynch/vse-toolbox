from fastapi import APIRouter
from api.response import success_response, error_response
from services.db import DBManager
from models.schemas import EWOCreate, EWOUpdate

router = APIRouter(prefix="/ewo", tags=["ewo"])


@router.get("")
def list_ewos(page: int = 1, size: int = 20, status: str = None, severity: str = None):
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