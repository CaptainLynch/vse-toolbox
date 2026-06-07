from fastapi import APIRouter
from api.response import success_response, error_response
from services.db import DBManager
from models.schemas import DeliverableCategoryCreate, DeliverableCategoryUpdate

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def get_overview():
    """Aggregate data for the analytics overview page.

    Returns milestone_progress with actual_date/actual_percentage,
    completion_pie for pie chart, department_bar for bar chart.
    """
    try:
        stats = DBManager.get_issue_stats()
        milestones = DBManager.list_milestones()
        categories = DBManager.list_deliverable_categories()
        deliverable_counts = {}

        # 交付物计数
        for cat in categories:
            if cat["id"] == "issues":
                deliverable_counts["issues"] = stats.get("total_open", 0)
            elif cat["id"] == "ewo":
                ewo_stats = DBManager.get_ewo_stats()
                deliverable_counts["ewo"] = ewo_stats.get("total", 0)
            elif cat["id"] == "tir":
                tir_stats = DBManager.get_tir_stats()
                deliverable_counts["tir"] = tir_stats.get("total", 0)

        # 计算各部门统计
        dept_stats_raw = stats.get("department_stats", [])
        department_bar = []
        for d in dept_stats_raw:
            total = d.get("total_issues", 0)
            closed_rate = d.get("closed_rate", 0)
            closed = round(total * closed_rate / 100) if total > 0 else 0
            department_bar.append({
                "department": d["department"],
                "total": total,
                "closed": closed,
            })

        # 计算完成率饼图
        total_all = sum(d["total_issues"] for d in dept_stats_raw)
        closed_all = sum(
            round(d["total_issues"] * d["closed_rate"] / 100) if d["total_issues"] > 0 else 0
            for d in dept_stats_raw
        )
        open_all = stats.get("total_open", 0)
        in_progress_all = total_all - closed_all - open_all
        if in_progress_all < 0:
            in_progress_all = 0

        completion_pie = [
            {"name": "已关闭", "value": closed_all, "color": "#4ade80"},
            {"name": "进行中", "value": in_progress_all, "color": "#d4af37"},
            {"name": "待处理", "value": open_all, "color": "#ff4d4d"},
        ]

        # 里程碑进度（含实际节点）
        milestone_progress = []
        for m in milestones:
            milestone_progress.append({
                "name": m["name"],
                "percentage": m.get("percentage", 0),
                "actual_percentage": m.get("actual_percentage", 0),
                "target_date": m.get("target_date"),
                "actual_date": m.get("actual_date"),
                "category": m["category"],
            })

        # 计算总体关闭率
        closed_rate = 0.0
        if total_all > 0:
            closed_rate = round(closed_all / total_all * 100, 1)

        data = {
            "total_issues": total_all,
            "open_issues": open_all,
            "closed_rate": closed_rate,
            "high_risk_count": stats.get("high_risk_count", 0),
            "new_this_week": stats.get("new_this_week", 0),
            "closed_this_week": stats.get("closed_this_week", 0),
            "milestone_progress": milestone_progress,
            "completion_pie": completion_pie,
            "department_bar": department_bar,
            "trend": stats.get("trend", []),
            "deliverable_counts": deliverable_counts,
        }

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
def update_category(cat_id: str, body: DeliverableCategoryUpdate):
    try:
        item = DBManager.update_deliverable_category(cat_id, body.model_dump(exclude_none=True))
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