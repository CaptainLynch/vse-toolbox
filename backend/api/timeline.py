"""Timeline CRUD routes."""

from fastapi import APIRouter
from api.response import success_response, error_response
from models.schemas import TimelineNodeCreate, TimelineNodeUpdate, TimelineReorderRequest
from services.db import DBManager

router = APIRouter(tags=["timeline"])


@router.get("/timeline")
def list_timeline_nodes():
    nodes = DBManager.list_timeline_nodes()
    return success_response(nodes)


@router.post("/timeline")
def create_timeline_node(data: TimelineNodeCreate):
    try:
        node = DBManager.create_timeline_node(data.model_dump())
        return success_response(node)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.put("/timeline/reorder")
def reorder_timeline_nodes(body: TimelineReorderRequest):
    items = [item.model_dump() for item in body.items]
    if not items:
        return error_response("items cannot be empty", status_code=400)
    count = DBManager.reorder_timeline_nodes(items)
    return success_response({"updated": count})


@router.get("/timeline/{node_id}")
def get_timeline_node(node_id: int):
    node = DBManager.get_timeline_node(node_id)
    if not node:
        return error_response("node not found", status_code=404)
    return success_response(node)


@router.put("/timeline/{node_id}")
def update_timeline_node(node_id: int, data: TimelineNodeUpdate):
    node = DBManager.update_timeline_node(node_id, data.model_dump(exclude_unset=True))
    if not node:
        return error_response("node not found", status_code=404)
    return success_response(node)


@router.delete("/timeline/{node_id}")
def delete_timeline_node(node_id: int):
    ok = DBManager.delete_timeline_node(node_id)
    if not ok:
        return error_response("node not found", status_code=404)
    return success_response({"deleted": True})