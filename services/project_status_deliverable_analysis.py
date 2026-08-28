# -*- coding: utf-8 -*-
"""Normalized cached analysis for one project-status deliverable.

车型锚点扩展设计（car_type 预留接口）：
当前每个交付物的分析缓存来自单一车型数据源；后续"按车型名称自动同步"落地时，
由定时同步服务按车型调用 TDC 抓取后调用 publish() 写缓存，车型→交付物的映射在目录层维护；
overview/items 的 car_type 参数为本通道预留，现阶段仅透传回显，不参与过滤。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "item_key": (
        "incident", "processNo", "formId", "processInstanceId", "id", "itemId",
        "itemNumber",
        "code", "number", "no", "documentNo", "partNo",
        "编号", "单号", "零件号", "记录编号", "实例号", "流水单号",
        "EWO编号", "PAA编号", "SOR号",
    ),
    "item_number": (
        "incident", "processNo", "itemNumber", "displayNumber", "formId",
        "processInstanceId", "documentNo", "number", "no",
        "编号", "单号", "记录编号", "实例号", "流水单号", "EWO编号", "PAA编号", "SOR号",
    ),
    "title": (
        "title", "name", "subject", "itemName", "documentName", "partName",
        "名称", "标题", "主题", "任务名称", "零件名称", "流程名", "报表名称",
        "processName", "projectName",
    ),
    "department": (
        "department", "responsibleDepartment", "responsibleDept", "ownerDepartment",
        "dept", "deptName", "sectionName", "section", "科室", "部门", "责任部门", "负责科室",
    ),
    "owner": (
        "owner", "responsiblePerson", "assignee", "handler", "负责人", "责任人", "处理人",
        "申请人", "申请者", "责任工程师名称", "applicant", "startUserName",
        "currentApprover", "currentApproverName", "rsp_name", "_rsp_name",
    ),
    "pending_signers": (
        "pendingSigners", "pendingApprovers", "待签署人员", "待审批人员", "当前待办人",
        "当前阶段未签署的角色&人员", "当前审批人", "currentTodoUser",
        "currentTodoName", "currentApprover", "currentApproverName",
    ),
    "status": (
        "status", "state", "workflowState", "approvalStatus", "状态", "审批状态", "流程状态",
    ),
    "planned_date": (
        "plannedDate", "dueDate", "deadline", "planFinishDate", "targetDate",
        "applicationDate", "applyDate", "计划完成", "计划完成日期", "到期日期", "截止日期", "申请日期",
    ),
    "actual_date": (
        "actualDate", "completedDate", "finishDate", "实际完成", "实际完成日期", "完成日期",
    ),
}

_COMPLETED_STATUSES = frozenset({
    "completed", "complete", "done", "closed", "approved", "released",
    "已完成", "完成", "已关闭", "已批准", "已审批", "已发布", "通过",
})


def _normalized_key(value: object) -> str:
    return re.sub(r"[^\w]+", "", str(value), flags=re.UNICODE).casefold()


def _safe_text(value: object, *, limit: int) -> str:
    return redact_sensitive_text(value, limit=limit, collapse_newlines=True).strip()


def _field_value(
    row: Mapping[str, Any],
    logical_name: str,
    mapping: Mapping[str, object],
) -> object | None:
    requested = mapping.get(logical_name)
    if isinstance(requested, str) and requested in row:
        return row.get(requested)
    normalized = {_normalized_key(key): key for key in row if isinstance(key, str)}
    for alias in _FIELD_ALIASES[logical_name]:
        actual = normalized.get(_normalized_key(alias))
        if actual is not None:
            return row.get(actual)
    return None


def _iso_date(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    if not text:
        return None
    match = re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(0)).isoformat()
    except ValueError:
        return None


def _snapshot_time(value: object) -> str:
    if isinstance(value, datetime):
        current = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        try:
            current = datetime.fromisoformat(text)
        except ValueError:
            current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _completed(status: str, actual_date: str | None) -> bool:
    normalized = status.strip().casefold()
    if normalized in _COMPLETED_STATUSES:
        return True
    return any(token in normalized for token in ("完成", "关闭", "批准", "发布")) or bool(actual_date)


def _alert_type(item: Mapping[str, Any], today: date, due_soon_days: int = 7) -> tuple[str | None, int | None]:
    if bool(item.get("is_completed")):
        return None, None
    planned = _iso_date(item.get("planned_date"))
    if planned is None:
        return "missing_due_date", None
    planned_date = date.fromisoformat(planned)
    delta = (planned_date - today).days
    if delta < 0:
        return "overdue", abs(delta)
    if delta <= due_soon_days:
        return "due_soon", delta
    return None, delta


def normalize_analysis_rows(
    rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, object] | None = None,
) -> list[dict[str, Any]]:
    """Extract only the bounded fields needed by the business analysis cache."""
    checked_mapping = mapping or {}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw_key = _field_value(row, "item_key", checked_mapping)
        display_number = _safe_text(
            _field_value(row, "item_number", checked_mapping) or raw_key or "",
            limit=200,
        )
        title = _safe_text(_field_value(row, "title", checked_mapping) or raw_key or "未命名任务", limit=240)
        department = _safe_text(_field_value(row, "department", checked_mapping) or "未归属", limit=120)
        owner = _safe_text(_field_value(row, "owner", checked_mapping) or "", limit=120)
        pending_signers = _safe_text(
            _field_value(row, "pending_signers", checked_mapping) or "",
            limit=500,
        )
        status = _safe_text(_field_value(row, "status", checked_mapping) or "", limit=120)
        planned_date = _iso_date(_field_value(row, "planned_date", checked_mapping))
        actual_date = _iso_date(_field_value(row, "actual_date", checked_mapping))
        fingerprint_source = "|".join(
            (str(raw_key or ""), title, department, owner, planned_date or "")
        )
        item_key = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        if item_key in seen:
            continue
        seen.add(item_key)
        normalized.append({
            "item_key": item_key,
            "display_number": display_number,
            "title": title,
            "department": department or "未归属",
            "owner": owner,
            "pending_signers": pending_signers,
            "source_status": status,
            "is_completed": _completed(status, actual_date),
            "planned_date": planned_date,
            "actual_date": actual_date,
        })
    return normalized


def summarize_analysis_items(
    items: Sequence[Mapping[str, Any]],
    *,
    snapshot_at: object,
    today: date | None = None,
) -> dict[str, Any]:
    current = today or date.today()
    department_counts: dict[str, dict[str, int]] = {}
    completed_count = overdue_count = due_soon_count = missing_count = 0
    for item in items:
        department = str(item.get("department") or "未归属")
        counts = department_counts.setdefault(
            department,
            {"total": 0, "completed": 0, "incomplete": 0},
        )
        counts["total"] += 1
        if bool(item.get("is_completed")):
            completed_count += 1
            counts["completed"] += 1
        else:
            counts["incomplete"] += 1
            alert_type, _ = _alert_type(item, current)
            if alert_type == "overdue":
                overdue_count += 1
            elif alert_type == "due_soon":
                due_soon_count += 1
            elif alert_type == "missing_due_date":
                missing_count += 1
    total_count = len(items)
    return {
        "total_count": total_count,
        "completed_count": completed_count,
        "incomplete_count": total_count - completed_count,
        "overdue_count": overdue_count,
        "due_soon_count": due_soon_count,
        "missing_due_date_count": missing_count,
        "department_counts": department_counts,
        "snapshot_at": _snapshot_time(snapshot_at),
    }


class ProjectStatusDeliverableAnalysisService:
    def __init__(self, db: DatabaseManager, *, clock: Any = None) -> None:
        self.db = db
        self._clock = clock or date.today

    def publish(
        self,
        deliverable_id: str,
        source_run_id: int,
        rows: Sequence[Mapping[str, Any]],
        *,
        snapshot_at: object,
        mapping: Mapping[str, object] | None = None,
    ) -> None:
        items = normalize_analysis_rows(rows, mapping)
        snapshot = summarize_analysis_items(items, snapshot_at=snapshot_at, today=self._clock())
        self.db.replace_project_status_analysis_cache(
            deliverable_id,
            source_run_id,
            snapshot,
            items,
        )

    def overview(
        self,
        deliverable_id: str,
        *,
        trend_limit: int = 8,
        car_type: str | None = None,
    ) -> dict[str, Any]:
        deliverable = self._deliverable(deliverable_id)
        rows = self.db.list_project_status_analysis_snapshots(deliverable_id, trend_limit)
        latest = rows[0] if rows else None
        trend = []
        for row in reversed(rows):
            trend.append({
                "snapshotAt": row["snapshot_at"],
                "total": int(row["total_count"]),
                "completed": int(row["completed_count"]),
                "incomplete": int(row["incomplete_count"]),
                "overdue": int(row["overdue_count"]),
                "dueSoon": int(row["due_soon_count"]),
            })
        department_counts: dict[str, Any] = {}
        if latest is not None:
            try:
                parsed = json.loads(str(latest["department_counts_json"]))
                if isinstance(parsed, dict):
                    department_counts = parsed
            except (TypeError, ValueError):
                department_counts = {}
        return {
            "deliverable": deliverable,
            "hasCache": latest is not None,
            "snapshotAt": latest["snapshot_at"] if latest else None,
            "summary": None if latest is None else {
                "total": int(latest["total_count"]),
                "completed": int(latest["completed_count"]),
                "incomplete": int(latest["incomplete_count"]),
                "overdue": int(latest["overdue_count"]),
                "dueSoon": int(latest["due_soon_count"]),
                "missingDueDate": int(latest["missing_due_date_count"]),
            },
            "departments": department_counts,
            "trend": trend,
            "carType": car_type,
        }

    def items(
        self,
        deliverable_id: str,
        *,
        alert: str | None = None,
        department: str | None = None,
        state: str | None = None,
        offset: int = 0,
        limit: int = 200,
        car_type: str | None = None,
    ) -> dict[str, Any]:
        self._deliverable(deliverable_id)
        if state not in {None, "completed", "incomplete"}:
            raise ValueError("unsupported state filter")
        if alert not in {None, "overdue", "due_soon", "missing_due_date"}:
            raise ValueError("unsupported alert filter")
        if alert is not None and (state is not None or int(offset) != 0):
            raise ValueError("alert filter cannot be combined with state/offset pagination")

        current = self._clock()
        if alert is not None:
            bounded_limit = max(1, min(int(limit), 500))
            rows = self.db.list_project_status_analysis_items(
                deliverable_id,
                department=department,
                limit=bounded_limit,
            )
            selected = []
            for row in rows:
                alert_type, days = _alert_type(row, current)
                if alert_type != alert:
                    continue
                selected.append({
                    "itemKey": row["item_key"],
                    "itemNumber": row.get("display_number") or row["item_key"],
                    "title": row["title"],
                    "department": row["department"],
                    "owner": row["owner"],
                    "pendingSigners": row.get("pending_signers") or "",
                    "status": row["source_status"],
                    "completed": bool(row["is_completed"]),
                    "plannedDate": row["planned_date"],
                    "actualDate": row["actual_date"],
                    "alertType": alert_type,
                    "days": days,
                    "updatedAt": row["updated_at"],
                })
            order = {"overdue": 0, "due_soon": 1, "missing_due_date": 2, None: 3}
            selected.sort(key=lambda item: (
                order[item["alertType"]],
                item["plannedDate"] or "9999-12-31",
                item["title"],
            ))
            total = len(selected)
        else:
            completed_filter = None if state is None else (state == "completed")
            rows = self.db.list_project_status_analysis_items(
                deliverable_id,
                department=department,
                completed=completed_filter,
                offset=offset,
                limit=limit,
            )
            total = self.db.count_project_status_analysis_items(
                deliverable_id,
                department=department,
                completed=completed_filter,
            )
            selected = []
            for row in rows:
                alert_type, days = _alert_type(row, current)
                selected.append({
                    "itemKey": row["item_key"],
                    "itemNumber": row.get("display_number") or row["item_key"],
                    "title": row["title"],
                    "department": row["department"],
                    "owner": row["owner"],
                    "pendingSigners": row.get("pending_signers") or "",
                    "status": row["source_status"],
                    "completed": bool(row["is_completed"]),
                    "plannedDate": row["planned_date"],
                    "actualDate": row["actual_date"],
                    "alertType": alert_type,
                    "days": days,
                    "updatedAt": row["updated_at"],
                })

        return {
            "deliverableId": deliverable_id,
            "items": selected,
            "total": total,
            "offset": int(offset),
            "limit": int(limit),
            "carType": car_type,
        }

    def _deliverable(self, deliverable_id: str) -> dict[str, Any]:
        _, _, rows = self.db.get_project_status("VPI-T2")
        for row in rows:
            if str(row["id"]) == deliverable_id:
                return {
                    "id": deliverable_id,
                    "name": str(row["name"]),
                    "status": str(row["status"]),
                    "owner": str(row["owner"]),
                    "source": str(row["source"]),
                }
        raise KeyError(deliverable_id)
