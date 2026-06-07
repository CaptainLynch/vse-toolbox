from fastapi import APIRouter
from api.response import success_response, error_response
from services.db import DBManager
from models.schemas import TIRCreate, TIRUpdate

router = APIRouter(prefix="/tir", tags=["tir"])


@router.get("")
def list_tirs(page: int = 1, size: int = 20, status: str = None, category: str = None):
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