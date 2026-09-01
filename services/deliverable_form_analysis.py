"""Unified, redacted form snapshots and analysis for external deliverables.

The module contains pure normalization and aggregation helpers.  It does not
resolve credentials, acquire leases, or call an external service.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from core.redaction import redact_sensitive_text
from core.report_contracts import report_contracts, table_payload

FORM_KEYS = frozenset(
    {"VPI-T2-D3", "aras_paa", "aras_ncr_progress", "aras_ncr_detail"}
)

_REPORT_BY_FORM_KEY = {
    "VPI-T2-D3": "ewo",
    "aras_paa": "paa",
    "aras_ncr_progress": "ncr_progress",
    "aras_ncr_detail": "ncr_detail",
}
_SOURCE_BY_FORM_KEY = {
    "VPI-T2-D3": "aras",
    "aras_paa": "aras",
    "aras_ncr_progress": "aras",
    "aras_ncr_detail": "aras",
}
_SHEET_NAMES_BY_FORM_KEY = {
    "VPI-T2-D3": ["Innovator"],
    "aras_paa": ["Innovator"],
    "aras_ncr_progress": ["Sheet1", "Sheet2"],
    "aras_ncr_detail": ["整车", "发动机"],
}
_STAGES_BY_REPORT = {
    "ewo": ("DRAFT1", "DRAFT2", "EDIT1", "EDIT2", "PROC", "IMPL", "CLOSE"),
    "paa": ("DRAFT1", "DRAFT2", "EDIT", "APPRL1", "APPRL2", "IMPL", "CLOSE"),
    "ncr_progress": (
        "PE提交",
        "NCR管理员",
        "PE科室经理",
        "价值工程师",
        "财务工程师",
        "部门总监",
        "CLOSE",
    ),
    "ncr_detail": (),
}
_TEXT_LIMIT = 600
_CONTACT_INDEXES = {"ewo": (13,), "paa": (5, 15)}
_NCR_COST_LABELS = {
    "investment": {
        "estimate": "测算工程工装费用(万元)",
        "approved": "批准工程工装费用（万元）",
        "actual": "实际工程工装费用(万元)",
    },
    "vehicleChange": {
        "estimate": "测算单件成本变化（元）",
        "approved": "批准单件成本变化（元）",
        "actual": "实际单件成本变化（元）",
    },
}


@dataclass(frozen=True)
class FormSnapshotInput:
    """Sanitized snapshot payload passed from a collector to persistence."""

    form_key: str
    report_type: str
    source_run_id: int | None
    snapshot_at: str
    schema: Mapping[str, Any]
    rows: Sequence[Mapping[str, Any]]
    summary: Mapping[str, Any]
    charts: Mapping[str, Any]
    artifacts: Sequence[Mapping[str, Any]] = ()
    source: str = ""

    def __post_init__(self) -> None:
        if self.form_key not in FORM_KEYS:
            raise ValueError("unsupported deliverable form key")
        if self.report_type != _REPORT_BY_FORM_KEY[self.form_key]:
            raise ValueError("form key and report type do not match")
        if not isinstance(self.snapshot_at, str) or not self.snapshot_at.strip():
            raise ValueError("snapshot_at is required")
        if not isinstance(self.rows, Sequence) or isinstance(self.rows, (str, bytes)):
            raise ValueError("snapshot rows must be a sequence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "formKey": self.form_key,
            "reportType": self.report_type,
            "sourceRunId": self.source_run_id,
            "snapshotAt": self.snapshot_at,
            "schema": dict(self.schema),
            "rows": [dict(row) for row in self.rows],
            "summary": dict(self.summary),
            "charts": dict(self.charts),
            "artifacts": [dict(item) for item in self.artifacts],
            "source": self.source,
        }


def _report_type(form_key: str) -> str:
    try:
        return _REPORT_BY_FORM_KEY[form_key]
    except KeyError as exc:
        raise KeyError(form_key) from exc


def _safe_text(value: object, limit: int = _TEXT_LIMIT) -> str:
    return redact_sensitive_text(value, limit=limit).strip()


def _mask_contact(value: object) -> str:
    text = _safe_text(value, 80)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 7:
        return f"{digits[:3]}****{digits[-4:]}"
    return "[contact masked]" if text else ""


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _date_text(value: object) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed_date = _parse_date(text)
        return (
            datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
            if parsed_date
            else None
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_value(value: object, *, contact: bool = False) -> object | None:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = _mask_contact(value) if contact else _safe_text(value, 1000)
    return text or None


def _source_value(
    row: Mapping[str, object],
    *keys: str,
) -> object | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _normalize_stage(value: object) -> str:
    text = re.sub(r"\s+", "", str(value or "")).upper()
    aliases = {
        "CLOZ": "CLOSE",
        "CLOSE": "CLOSE",
        "DRAFT1": "DRAFT1",
        "DRAFT2": "DRAFT2",
        "EDIT": "EDIT",
        "EDIT1": "EDIT1",
        "EDIT2": "EDIT2",
        "PROC": "PROC",
        "IMPL": "IMPL",
        "PE提交": "PE提交",
        "NCR管理员": "NCR管理员",
        "PE科室经理": "PE科室经理",
        "价值工程师": "价值工程师",
        "财务工程师": "财务工程师",
        "部门总监": "部门总监",
        "财务部总监": "部门总监",
    }
    return aliases.get(text, str(value or "").strip())


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _snapshot_date(snapshot_at: object) -> date | None:
    parsed = _parse_datetime(snapshot_at)
    return parsed.date() if parsed else _parse_date(snapshot_at)


def classify_overdue(
    form_key: str,
    row: Mapping[str, object],
    *,
    snapshot_at: object,
) -> str:
    """Return on_time, overdue, unknown, or not_applicable."""
    report = _report_type(form_key)
    if report == "ncr_detail":
        return "not_applicable"
    stage = _normalize_stage(row.get("stage"))
    if not stage or stage == "CLOSE":
        return "not_applicable"
    current = _snapshot_date(snapshot_at)
    if current is None:
        return "unknown"
    end_date = _parse_date(row.get("stageEnd")) or current
    start_date = _parse_date(row.get("stageStart"))
    planned_date = _parse_date(row.get("plannedDate"))
    if report == "ewo":
        if stage in {"DRAFT1", "DRAFT2", "EDIT1", "EDIT2"}:
            if start_date is None:
                return "unknown"
            return "overdue" if end_date > start_date + timedelta(days=7) else "on_time"
        if stage == "PROC":
            if start_date is None:
                return "unknown"
            return "overdue" if end_date > _add_months(start_date, 1) else "on_time"
        if stage == "IMPL":
            if planned_date is None:
                return "unknown"
            return "overdue" if current > planned_date else "on_time"
        return "unknown"
    if report == "paa":
        if stage in {"DRAFT1", "DRAFT2", "EDIT"}:
            if start_date is None:
                return "unknown"
            return "overdue" if end_date > start_date + timedelta(days=3) else "on_time"
        if stage == "PROC":
            if start_date is None:
                return "unknown"
            return "overdue" if end_date > start_date + timedelta(days=7) else "on_time"
        if stage == "IMPL":
            if planned_date is None:
                return "unknown"
            return "overdue" if current > planned_date else "on_time"
        return "unknown"
    if report == "ncr_progress":
        if start_date is None:
            return "unknown"
        days = 3 if stage in {"NCR管理员", "PE科室经理"} else 7
        return "overdue" if end_date > start_date + timedelta(days=days) else "on_time"
    return "unknown"


def form_definition(form_key: str) -> dict[str, Any]:
    """Return a copy of the allowlisted form schema for one form key."""
    report = _report_type(form_key)
    contract = report_contracts()[report]
    table = table_payload(report, [])
    columns = [dict(column) for column in table["columns"]]
    if report == "ncr_detail":
        # NCR 明细第 5 行是车型矩阵表头；基础字段和成本字段位于第 1 行。
        # 多级表头仍完整返回，列的稳定识别名使用第 1 行字段名。
        base_headers = contract["headerRows"][0]
        for column in columns:
            index = int(column["index"])
            base_label = str(base_headers[index] or "").strip()
            if base_label:
                column["label"] = base_label
                column["baseLabel"] = base_label
    for column in columns:
        column["filterable"] = bool(
            str(column.get("label") or "").strip()
        )
        column["chartable"] = bool(
            column.get("sourceFields") or str(column.get("label") or "").strip()
        )
    return {
        "formKey": form_key,
        "reportType": report,
        "sheetNames": list(_SHEET_NAMES_BY_FORM_KEY[form_key]),
        "headerRows": contract["headerRows"],
        "dataHeaderRow": int(contract.get("dataHeaderRow", 0)),
        "columns": columns,
        "defaultVisibleCount": int(contract["defaultVisibleCount"]),
        "filterFields": [
            "keyword",
            "status",
            "department",
            "section",
            "model",
            "stage",
            "dateStart",
            "dateEnd",
        ],
        "chartFields": list(_STAGES_BY_REPORT[report]),
    }


def _positional_value(
    values: Sequence[object],
    definition: Mapping[str, Any],
    label: str,
) -> object | None:
    for column in definition["columns"]:
        if str(column.get("label") or "").strip() == label:
            index = int(column["index"])
            return values[index] if index < len(values) else None
    return None


def _positional_value_any(
    values: Sequence[object],
    definition: Mapping[str, Any],
    labels: Sequence[str],
) -> object | None:
    for label in labels:
        value = _positional_value(values, definition, label)
        if value not in (None, ""):
            return value
    return None


def _stage_date_from_mapping(
    row: Mapping[str, object],
    stage: str,
) -> object | None:
    normalized_stage = stage.casefold().replace("_", "")
    for key, value in row.items():
        key_text = str(key).casefold().replace("_", "")
        if normalized_stage in key_text and any(
            marker in key_text for marker in ("date", "time", "日期", "时间", "到达")
        ):
            if "days" not in key_text and "duration" not in key_text:
                parsed = _date_text(value)
                if parsed:
                    return parsed
    return None


def _dimensions_from_mapping(
    report: str,
    row: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, object]]:
    if report == "ewo":
        department = _source_value(row, "_department", "_rsp_department")
        section = _source_value(row, "_rsp_smt", "_section")
        model = _source_value(row, "_modelinfo", "modelInfo")
        status = _source_value(row, "state", "current_state__name")
        stage = _normalize_stage(status)
        submitted = _source_value(row, "_submit_time", "submit_date")
        planned = _source_value(row, "_required_date", "required_date")
        contact = _source_value(row, "_rsp_phone", "phone")
    else:
        department = _source_value(row, "_department", "_pe_tdc_department")
        section = _source_value(row, "_pe_tdc_smt", "_requester_smt")
        model = _source_value(row, "_vehicles", "_modelinfo")
        status = _source_value(row, "state", "current_state__name")
        stage = _normalize_stage(status)
        submitted = _source_value(row, "_submit_date", "submit_date")
        planned = _source_value(row, "_est_cmpl_date", "estimated_complete_date")
        contact = _source_value(row, "_requester_phone", "_pe_tdc_phone")
    return (
        {
            "department": _safe_text(department, 160),
            "section": _safe_text(section, 160),
            "model": _safe_text(model, 160),
            "status": _safe_text(status, 120),
            "stage": stage,
        },
        {
            "submittedDate": _date_text(submitted),
            "plannedDate": _date_text(planned),
            "contact": _mask_contact(contact),
            "stageStart": _stage_date_from_mapping(row, "DRAFT1"),
        },
    )


def _dimensions_from_ncr(
    report: str,
    values: Sequence[object],
    definition: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, object]]:
    status = _positional_value(values, definition, "状态")
    section = _positional_value(values, definition, "区域")
    model = _positional_value(values, definition, "项目")
    current_node = _positional_value_any(
        values,
        definition,
        ("当前节点", "当前节点及通知时间"),
    )
    stage = _normalize_stage(current_node or status)
    submitted = _positional_value(values, definition, "提交日期")
    planned = (
        _positional_value(values, definition, "估计完成日期")
        if report == "ncr_detail"
        else None
    )
    completed = _safe_text(
        _positional_value(values, definition, "是否审批完成"),
        40,
    )
    is_completed = _normalize_stage(status) == "CLOSE" or completed == "是"
    return (
        {
            "department": "",
            "section": _safe_text(section, 160),
            "model": _safe_text(model, 160),
            "status": _safe_text(status, 120),
            "stage": stage,
        },
        {
            "submittedDate": _date_text(submitted),
            "plannedDate": _date_text(planned),
            "stageStart": None,
            "isCompleted": is_completed,
        },
    )


def _cost_from_values(
    values: Sequence[object],
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    cost: dict[str, Any] = {}
    for group, labels in _NCR_COST_LABELS.items():
        cost[group] = {
            name: _number(_positional_value(values, definition, label))
            for name, label in labels.items()
        }
    actual = cost["vehicleChange"]["actual"]
    if actual is None:
        direction = "unknown"
    elif actual > 0:
        direction = "increase"
    elif actual < 0:
        direction = "decrease"
    else:
        direction = "unchanged"
    cost["vehicleChangeDirection"] = direction
    return cost


def _safe_values(
    report: str,
    values: Sequence[object],
) -> list[object | None]:
    contact_indexes = set(_CONTACT_INDEXES.get(report, ()))
    return [
        _clean_value(value, contact=index in contact_indexes)
        for index, value in enumerate(values)
    ]


def normalize_form_rows(
    form_key: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_at: str,
    sheet_name: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize source dictionaries or positional workbook rows safely."""
    report = _report_type(form_key)
    definition = form_definition(form_key)
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rows, 1):
        if not isinstance(raw, Mapping):
            continue
        positional = raw.get("values")
        row_sheet = _safe_text(raw.get("sheetName") or raw.get("sheet_name") or sheet_name or "")
        if isinstance(positional, Sequence) and not isinstance(positional, (str, bytes)):
            values = _safe_values(report, list(positional))
            dimensions, dates = _dimensions_from_ncr(report, values, definition)
            cost = _cost_from_values(values, definition) if report == "ncr_detail" else {}
            identity = "|".join(str(value or "") for value in values[:10])
        else:
            source = {str(key): value for key, value in raw.items()}
            table = table_payload(report, [source])
            raw_values = table["rows"][0]
            values = _safe_values(report, raw_values)
            dimensions, dates = _dimensions_from_mapping(report, source)
            cost = {}
            identity = str(
                _source_value(source, "_no", "id", "keyed_name", "ncr_no")
                or "|".join(str(value or "") for value in values[:5])
            )
        stage = dimensions["stage"]
        status = dimensions["status"]
        is_completed = bool(
            dates.get("isCompleted")
            or stage == "CLOSE"
            or status.casefold() in {"close", "closed", "关闭", "已完成"}
        )
        row_for_due = {
            "stage": stage,
            "stageStart": dates.get("stageStart"),
            "stageEnd": dates.get("stageEnd"),
            "plannedDate": dates.get("plannedDate"),
            "isCompleted": is_completed,
        }
        overdue_state = classify_overdue(
            form_key,
            row_for_due,
            snapshot_at=snapshot_at,
        )
        row_key = hashlib.sha256(
            f"{form_key}|{row_sheet}|{index}|{identity}".encode("utf-8")
        ).hexdigest()
        search_text = _safe_text(
            " ".join(str(value or "") for value in values),
            2000,
        )
        normalized.append(
            {
                "rowKey": row_key,
                "rowNumber": index,
                "sheetName": row_sheet,
                "values": values,
                "dimensions": dimensions,
                "submittedDate": dates.get("submittedDate"),
                "plannedDate": dates.get("plannedDate"),
                "stageStart": dates.get("stageStart"),
                "stageEnd": dates.get("stageEnd"),
                "overdueState": overdue_state,
                "isCompleted": is_completed,
                "searchText": search_text,
                "cost": cost,
                "contact": dates.get("contact", ""),
            }
        )
    return normalized


def _status_bucket(row: Mapping[str, Any]) -> str:
    if row.get("overdueState") == "overdue":
        return "overdue"
    if row.get("overdueState") == "on_time":
        return "on_time"
    if row.get("isCompleted"):
        return "on_time"
    return "unknown"


def _stage_status_summary(
    report: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stage in _STAGES_BY_REPORT[report]:
        selected = [
            row for row in rows
            if str(row.get("dimensions", {}).get("stage") or "") == stage
        ]
        result.append(
            {
                "label": stage,
                "onTime": sum(_status_bucket(row) == "on_time" for row in selected),
                "overdue": sum(_status_bucket(row) == "overdue" for row in selected),
            }
        )
    return result


def _section_status_summary(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        section = str(row.get("dimensions", {}).get("section") or "未分配")
        counts = buckets.setdefault(
            section,
            {"onTime": 0, "overdue": 0, "unknown": 0},
        )
        bucket = _status_bucket(row)
        counts[{"on_time": "onTime", "overdue": "overdue", "unknown": "unknown"}[bucket]] += 1
    return [
        {
            "label": label,
            **counts,
            "total": sum(counts.values()),
        }
        for label, counts in sorted(buckets.items())
    ]


def _cost_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row.get("dimensions", {}).get(dimension) or "部门总计")
        target = groups.setdefault(
            label,
            {
                "dimension": dimension,
                "label": label,
                "investment": {"estimate": None, "approved": None, "actual": None},
                "vehicleChange": {"estimate": None, "approved": None, "actual": None},
            },
        )
        cost = row.get("cost")
        if not isinstance(cost, Mapping):
            continue
        for group in ("investment", "vehicleChange"):
            source = cost.get(group)
            if not isinstance(source, Mapping):
                continue
            for name in ("estimate", "approved", "actual"):
                value = _number(source.get(name))
                if value is not None:
                    target[group][name] = (target[group][name] or 0.0) + value
    return sorted(groups.values(), key=lambda item: str(item["label"]))


def summarize_form_rows(
    form_key: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_at: str,
) -> dict[str, Any]:
    report = _report_type(form_key)
    total = len(rows)
    completed = sum(bool(row.get("isCompleted")) for row in rows)
    overdue = sum(row.get("overdueState") == "overdue" for row in rows)
    unknown = sum(row.get("overdueState") == "unknown" for row in rows)
    result: dict[str, Any] = {
        "total": total,
        "completed": completed,
        "incomplete": total - completed,
        "overdue": overdue,
        "unknown": unknown,
        "snapshotAt": snapshot_at,
        "departmentStatus": {"stages": _stage_status_summary(report, rows)},
        "sectionStatus": _section_status_summary(rows),
    }
    if report == "ncr_detail":
        result["departmentCost"] = _cost_summary(rows, dimension="department")
        result["sectionCost"] = _cost_summary(rows, dimension="section")
    return result


def aggregate_daily_trend(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Select the latest snapshot for each natural day, oldest first."""
    latest: dict[str, tuple[datetime, Mapping[str, Any]]] = {}
    for snapshot in snapshots:
        parsed = _parse_datetime(snapshot.get("snapshotAt") or snapshot.get("snapshot_at"))
        if parsed is None:
            continue
        day = parsed.date().isoformat()
        current = latest.get(day)
        if current is None or parsed >= current[0]:
            latest[day] = (parsed, snapshot)
    selected = sorted(latest.items())[-max(1, min(int(limit), 365)):]
    result: list[dict[str, Any]] = []
    for day, (_, snapshot) in selected:
        summary = snapshot.get("summary", {})
        if not isinstance(summary, Mapping):
            summary = {}
        result.append(
            {
                "day": day,
                "snapshotAt": str(
                    snapshot.get("snapshotAt") or snapshot.get("snapshot_at") or ""
                ),
                "total": int(summary.get("total") or 0),
                "incomplete": int(summary.get("incomplete") or 0),
                "overdue": int(summary.get("overdue") or 0),
            }
        )
    return result


def build_form_snapshot(
    form_key: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_at: str,
    source_run_id: int | None,
    source: str,
    artifacts: Sequence[Mapping[str, Any]] = (),
    sheet_name: str | None = None,
) -> FormSnapshotInput:
    normalized = normalize_form_rows(
        form_key,
        rows,
        snapshot_at=snapshot_at,
        sheet_name=sheet_name,
    )
    summary = summarize_form_rows(
        form_key,
        normalized,
        snapshot_at=snapshot_at,
    )
    report = _report_type(form_key)
    charts = {
        "departmentStatus": summary["departmentStatus"],
        "sectionStatus": summary["sectionStatus"],
    }
    if report == "ncr_detail":
        charts["departmentCost"] = summary["departmentCost"]
        charts["sectionCost"] = summary["sectionCost"]
    return FormSnapshotInput(
        form_key=form_key,
        report_type=report,
        source_run_id=source_run_id,
        snapshot_at=snapshot_at,
        schema=form_definition(form_key),
        rows=tuple(normalized),
        summary=summary,
        charts=charts,
        artifacts=tuple(dict(item) for item in artifacts),
        source=source,
    )


_VIEW_FILTER_KEYS = frozenset(
    {
        "keyword",
        "status",
        "department",
        "section",
        "model",
        "stage",
        "dateStart",
        "dateEnd",
        "overdueState",
        "isCompleted",
    }
)
_VIEW_FILTER_TEXT_LIMIT = 200


def normalize_form_filters(
    filters: Mapping[str, object] | None,
) -> dict[str, object]:
    """Validate and normalize the public form-view filter contract."""
    values = dict(filters or {})
    unknown = set(values) - _VIEW_FILTER_KEYS
    if unknown:
        raise ValueError("unsupported form view filter")
    normalized: dict[str, object] = {}
    for key, value in values.items():
        if value in (None, ""):
            continue
        if key == "isCompleted" and isinstance(value, bool):
            normalized[key] = value
            continue
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"invalid form view filter: {key}")
        text = str(value).strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValueError(f"form view filter contains control characters: {key}")
        if len(text) > _VIEW_FILTER_TEXT_LIMIT:
            raise ValueError(f"form view filter is too long: {key}")
        if key in {"dateStart", "dateEnd"}:
            parsed = _parse_date(text)
            if parsed is None or parsed.isoformat() != text:
                raise ValueError(f"invalid form view date filter: {key}")
            text = parsed.isoformat()
        if key == "isCompleted":
            folded = text.casefold()
            if folded not in {"0", "1", "true", "false", "yes", "no", "completed", "incomplete"}:
                raise ValueError("invalid form view completion filter")
            normalized[key] = folded in {"1", "true", "yes", "completed"}
        else:
            normalized[key] = text
    if (
        normalized.get("dateStart")
        and normalized.get("dateEnd")
        and str(normalized["dateStart"]) > str(normalized["dateEnd"])
    ):
        raise ValueError("dateStart must not be later than dateEnd")
    return normalized


def _chart_payload(
    form_key: str,
    summary: Mapping[str, Any],
    trend: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    report = _report_type(form_key)
    charts: dict[str, Any] = {
        "departmentStatus": summary.get("departmentStatus", {"stages": []}),
        "sectionStatus": summary.get("sectionStatus", []),
        "quantityTrend": [dict(item) for item in trend],
    }
    if report == "ncr_detail":
        charts["departmentCost"] = list(summary.get("departmentCost", []))
        charts["sectionCost"] = list(summary.get("sectionCost", []))
    return charts


def _filter_options(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    options: dict[str, set[str]] = {
        "status": set(),
        "department": set(),
        "section": set(),
        "model": set(),
        "stage": set(),
        "overdueState": set(),
    }
    for row in rows:
        dimensions = row.get("dimensions")
        if isinstance(dimensions, Mapping):
            for key in ("status", "department", "section", "model", "stage"):
                value = str(dimensions.get(key) or "").strip()
                if value:
                    options[key].add(value)
        overdue = str(row.get("overdueState") or "").strip()
        if overdue:
            options["overdueState"].add(overdue)
    return {key: sorted(values)[:500] for key, values in options.items()}


class DeliverableFormAnalysisService:
    """Read and publish the unified form snapshot contract for the Web UI.

    The service only reads already-collected snapshots.  It never resolves
    credentials, reuses a browser session, acquires a sync lease, or calls an
    external connector.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    @staticmethod
    def _validate_key(form_key: str) -> str:
        if form_key not in FORM_KEYS:
            raise KeyError(form_key)
        return form_key

    def rows(
        self,
        form_key: str,
        filters: Mapping[str, object] | None = None,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        key = self._validate_key(form_key)
        normalized = normalize_form_filters(filters)
        return self.db.list_deliverable_form_rows(
            key,
            normalized,
            offset=offset,
            limit=limit,
        )

    def _sync_status(self, form_key: str) -> dict[str, Any]:
        job_key = "aras_ewo" if form_key == "VPI-T2-D3" else form_key
        jobs = self.db.list_archive_jobs()
        job = next(
            (item for item in jobs if str(item.get("job_key") or "") == job_key),
            None,
        )
        if job is None:
            return {
                "jobKey": job_key,
                "state": "idle",
                "enabled": False,
                "credentialConfigured": False,
                "lastAttemptAt": None,
                "lastSuccessAt": None,
                "lastErrorType": None,
                "lastErrorMessage": None,
            }
        return {
            "jobKey": job_key,
            "state": str(job.get("sync_state") or "idle"),
            "enabled": bool(job.get("enabled")),
            "credentialConfigured": bool(job.get("credential_configured")),
            "lastAttemptAt": job.get("last_attempt_at"),
            "lastSuccessAt": job.get("last_success_at"),
            "lastErrorType": job.get("last_error_type"),
            "lastErrorMessage": job.get("last_error_message"),
        }

    def view(
        self,
        form_key: str,
        *,
        filters: Mapping[str, object] | None = None,
        trend_limit: int = 30,
    ) -> dict[str, Any]:
        key = self._validate_key(form_key)
        normalized_filters = normalize_form_filters(filters)
        if isinstance(trend_limit, bool) or not 1 <= int(trend_limit) <= 365:
            raise ValueError("trendLimit must be between 1 and 365")
        trend_count = int(trend_limit)
        definition = form_definition(key)
        latest = self.db.get_latest_deliverable_form_snapshot(key)
        snapshots = self.db.list_deliverable_form_snapshots(key, limit=30)
        latest_rows: list[dict[str, Any]] = []
        if latest is not None:
            latest_rows = self.db.list_deliverable_form_snapshot_rows(
                int(latest["id"]),
                normalized_filters,
            )
            snapshot_at = str(latest.get("snapshot_at") or "")
            summary = summarize_form_rows(
                key,
                latest_rows,
                snapshot_at=snapshot_at,
            )
            schema = latest.get("schema") or definition
            artifacts = latest.get("artifacts") or []
            snapshot = {
                "id": int(latest["id"]),
                "snapshotKey": str(latest.get("snapshot_key") or ""),
                "snapshotAt": snapshot_at,
                "rowCount": int(latest.get("row_count") or 0),
                "sourceRunId": latest.get("source_run_id"),
            }
        else:
            snapshot_at = ""
            latest_rows = []
            summary = summarize_form_rows(key, [], snapshot_at=snapshot_at)
            schema = definition
            artifacts = []
            snapshot = None

        if normalized_filters:
            trend_inputs: list[dict[str, Any]] = []
            for item in snapshots:
                item_rows = self.db.list_deliverable_form_snapshot_rows(
                    int(item["id"]),
                    normalized_filters,
                )
                item_summary = summarize_form_rows(
                    key,
                    item_rows,
                    snapshot_at=str(item.get("snapshot_at") or ""),
                )
                trend_inputs.append(
                    {
                        "snapshotAt": item.get("snapshot_at"),
                        "summary": item_summary,
                    }
                )
        else:
            trend_inputs = snapshots
        trend = aggregate_daily_trend(trend_inputs, limit=trend_count)
        return {
            "formKey": key,
            "reportType": _report_type(key),
            "snapshot": snapshot,
            "snapshotAt": snapshot_at or None,
            "rowCount": int(latest.get("row_count") or 0) if latest else 0,
            "matchedRowCount": int(summary.get("total") or 0),
            "schema": schema,
            "summary": summary,
            "charts": _chart_payload(key, summary, trend),
            "trend": trend,
            "artifacts": artifacts,
            "sync": self._sync_status(key),
            "filters": {
                "fields": list(definition["filterFields"]) + [
                    "overdueState",
                    "isCompleted",
                ],
                "applied": normalized_filters,
                "options": _filter_options(latest_rows),
            },
        }


__all__ = [
    "FORM_KEYS",
    "DeliverableFormAnalysisService",
    "FormSnapshotInput",
    "aggregate_daily_trend",
    "build_form_snapshot",
    "classify_overdue",
    "form_definition",
    "normalize_form_filters",
    "normalize_form_rows",
    "summarize_form_rows",
]
