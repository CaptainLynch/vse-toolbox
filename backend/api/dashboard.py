from fastapi import APIRouter
from api.response import success_response, error_response
from services.db import DBManager
from models.schemas import DeliverableCategoryCreate

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def get_overview():
    """Aggregate data for the analytics overview page."""
    try:
        stats = DBManager.get_issue_stats()
        milestones = DBManager.list_milestones()
        categories = DBManager.list_deliverable_categories()
        deliverable_counts = {}
        for cat in categories:
            if cat["id"] == "issues":
                deliverable_counts["issues"] = stats.get("total_open", 0)
            elif cat["id"] == "ewo":
                ewo_stats = DBManager.get_ewo_stats()
                deliverable_counts["ewo"] = ewo_stats.get("total", 0)
            elif cat["id"] == "tir":
                tir_stats = DBManager.get_tir_stats()
                deliverable_counts["tir"] = tir_stats.get("total", 0)

        data = {
            "total_issues": sum(c["total_issues"] for c in stats.get("department_stats", [])) or stats.get("total_open", 0),
            "open_issues": stats.get("total_open", 0),
            "closed_rate": 0,
            "high_risk_count": stats.get("high_risk_count", 0),
            "new_this_week": stats.get("new_this_week", 0),
            "closed_this_week": stats.get("closed_this_week", 0),
            "milestone_progress": [
                {"name": m["name"], "percentage": m["percentage"], "category": m["category"]}
                for m in milestones
            ],
            "department_stats": [
                {"department": d["department"], "totalIssues": d["total_issues"], "closedRate": d["closed_rate"]}
                for d in stats.get("department_stats", [])
            ],
            "trend": stats.get("trend", []),
            "deliverable_counts": deliverable_counts,
        }
        # Compute overall closed rate
        total_all = sum(d["totalIssues"] for d in data["department_stats"])
        if total_all > 0:
            closed_all = sum(d["closedRate"] * d["totalIssues"] / 100 for d in data["department_stats"])
            data["closed_rate"] = round(closed_all / total_all * 100, 1)

        return success_response(data)
    except Exception as e:
        return error_response(str(e), status_code=500)


# ---------------------------------------------------------------------------
# Deliverable categories CRUD
# ---------------------------------------------------------------------------

@router.get("/deliverable-categories")
def list_categories():
    try:
        items = DBManager.list_deliverable_categories()
        return success_response(items)
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.post("/deliverable-categories")
def create_category(body: DeliverableCategoryCreate):
    try:
        item = DBManager.create_deliverable_category(body.model_dump())
        return success_response(item)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.put("/deliverable-categories/{cat_id}")
def update_category(cat_id: str, body: dict):
    try:
        item = DBManager.update_deliverable_category(cat_id, body)
        if not item:
            return error_response("Category not found", status_code=404)
        return success_response(item)
    except Exception as e:
        return error_response(str(e), status_code=400)


@router.delete("/deliverable-categories/{cat_id}")
def delete_category(cat_id: str):
    try:
        ok = DBManager.delete_deliverable_category(cat_id)
        if not ok:
            return error_response("Category not found", status_code=404)
        return success_response({"deleted": True})
    except Exception as e:
        return error_response(str(e), status_code=400)


# ---------------------------------------------------------------------------
# Dashboard layouts CRUD
# ---------------------------------------------------------------------------

@router.get("/layouts")
def get_layouts(page_key: str):
    try:
        items = DBManager.get_layouts(page_key)
        return success_response(items)
    except Exception as e:
        return error_response(str(e), status_code=500)


@router.put("/layouts")
def save_layouts(body: dict):
    try:
        page_key = body.get("page_key")
        layouts = body.get("layouts", [])
        if not page_key:
            return error_response("page_key is required", status_code=400)
        count = DBManager.save_layouts(page_key, layouts)
        return success_response({"saved": count})
    except Exception as e:
        return error_response(str(e), status_code=400)