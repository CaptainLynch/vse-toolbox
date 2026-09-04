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
    {"VPI-T2-D3", "aras_paa", "aras_ncr_progress", "aras_ncr_detail", "tdc_data_model"}
)

_REPORT_BY_FORM_KEY = {
    "VPI-T2-D3": "ewo",
    "aras_paa": "paa",
    "aras_ncr_progress": "ncr_progress",
    "aras_ncr_detail": "ncr_detail",
    "tdc_data_model": "tdc_data_model",
}
_SOURCE_BY_FORM_KEY = {
    "VPI-T2-D3": "aras",
    "aras_paa": "aras",
    "aras_ncr_progress": "aras",
    "aras_ncr_detail": "aras",
    "tdc_data_model": "tdc",
}
_SHEET_NAMES_BY_FORM_KEY = {
    "VPI-T2-D3": ["Innovator"],
    "aras_paa": ["Innovator"],
    "aras_ncr_progress": ["Sheet1", "Sheet2"],
    "aras_ncr_detail": ["整车", "发动机"],
    "tdc_data_model": ["Sheet1"],
}
_STAGES_BY_REPORT = {
    "ewo": ("DRAFT1", "DRAFT2", "EDIT1", "EDIT2", "PROC", "IMPL", "CLOSE"),
    "paa": ("DRAFT1", "DRAFT2", "EDIT", "PROC", "IMPL", "CLOSE"),
    # 真实表单完整审批节点（用户 2026-09-02 确认）；非正式阶段由
    # _stage_status_summary 聚合为“其他状态”。
    "ncr_progress": (
        "PE提交",
        "NCR管理员",
        "PE科室经理",
        "价值工程师",
        "价值工程经理",
        "PE部门总监",
        "财务工程师",
        "平台项目管理专家",
        "海外项目总监",
        "平台首席",
        "动力平台首席",
        "财务部总监",
        "CLOSE",
    ),
    "ncr_detail": (),
    # 数模设计审核流程没有固定审批阶段列表；阶段图按观察到的
    # 项目/车型值聚合（见 _stage_status_summary）。
    "tdc_data_model": (),
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
_NCR_PROGRESS_STAGE_DATE_LABELS = {
    "PE提交": ("PE填写", "PE提交"),
    "NCR管理员": ("NCR管理员",),
    "PE科室经理": ("PE科室经理",),
    "价值工程师": ("价值工程师",),
    "价值工程经理": ("价值工程经理",),
    "PE部门总监": ("PE部门总监",),
    "财务工程师": ("财务工程师",),
    "平台项目管理专家": ("平台项目管理专家",),
    "海外项目总监": ("海外项目总监",),
    "平台首席": ("平台首席",),
    "动力平台首席": ("动力平台首席",),
    "财务部总监": ("财务部总监",),
}
# 逾期判定天数（设计文档批准口径，可被 view/rows 的阈值参数覆盖）：
# - EWO：起草/编辑类阶段 stageDays=7 天；PROC=1 个自然月（lateDays=30 时
#   保持日历月语义，其余值按天差比较）；IMPL 只比较要求完成时间。
# - PAA：起草/编辑类 3 天；PROC 7 天；IMPL 只比较估计完成日期。
# - NCR 审批进度：前两个节点（NCR管理员、PE科室经理）3 天，其余节点 7 天。
# - 数模设计审核流程：审批中且申请日期滞留超过 7 天记为逾期。
_TDC_OVERDUE_DWELL_DAYS = 7
_OVERDUE_RULES = {
    "ewo": {"stageDays": 7, "lateDays": 30},
    "paa": {"stageDays": 3, "lateDays": 7},
    "ncr_progress": {"stageDays": 3, "lateDays": 7},
    # 数模设计审核流程：审批中且申请日期滞留超过 7 天记为逾期。
    "tdc_data_model": {"stageDays": _TDC_OVERDUE_DWELL_DAYS, "lateDays": _TDC_OVERDUE_DWELL_DAYS},
}
_NCR_STAGE_FIRST_TWO = frozenset({"NCR管理员", "PE科室经理"})
_OVERDUE_THRESHOLD_MIN = 0
_OVERDUE_THRESHOLD_MAX = 999
# 明细表默认展示的关键中文字段（与当前图表相关）。按表头标签解析为列
# 索引，缺失的标签自动跳过；NCR 明细必须默认可见六个成本字段与 EWO号。
_KEY_COLUMN_LABELS = {
    "ewo": (
        "EWO编号", "状态", "部门", "责任工程师专业科室", "车型信息",
        "主题", "提交日期", "要求完成时间",
    ),
    "paa": (
        "PAA编号", "状态", "部门", "专业科室", "车型",
        "零件或总成名称", "提交日期", "估计完成日期", "EWO编号",
    ),
    "ncr_progress": (
        "NCR编号", "状态", "当前节点及通知时间", "区域", "项目",
        "提交日期", "是否审批完成", "当前审批人滞留天数", "EWO号",
    ),
    "ncr_detail": (
        "NCR编号", "状态", "区域", "项目", "零件名称", "零件号",
        "测算工程工装费用(万元)", "批准工程工装费用（万元）",
        "实际工程工装费用(万元)", "测算单件成本变化（元）",
        "批准单件成本变化（元）", "实际单件成本变化（元）", "EWO号",
    ),
    "tdc_data_model": (),
}
# 数模设计审核流程（TDC 47 列导出）的展示口径：
# - “重量（单件）”“零件合计”不在明细视图体现（列索引 12/13）；
# - 默认可见列以“EWO/SOR号”收尾；
# - 审批中滞留阈值见 _OVERDUE_RULES["tdc_data_model"]；
# - “已废弃”是终态，不计入未完成，也不参与逾期判定。
_TDC_HIDDEN_COLUMN_INDEXES = {"tdc_data_model": frozenset({12, 13})}
_TDC_DEFAULT_VISIBLE_COUNT = 15
_TDC_DEPRECATED_STATUS = "已废弃"


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
    if value is None:
        return ""
    return str(redact_sensitive_text(value, limit=limit)).strip()


def _mask_contact(value: object) -> str:
    text = _safe_text(value, 80)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
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
    if contact:
        masked = _mask_contact(value)
        return masked or None
    if isinstance(value, (int, float, bool)):
        return value
    text = _safe_text(value, 1000)
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
        "关闭": "CLOSE",
        "已关闭": "CLOSE",
        "已完成": "CLOSE",
        "完成": "CLOSE",
        "审批完成": "CLOSE",
        "DRAFT1": "DRAFT1",
        "DRAFT2": "DRAFT2",
        "EDIT": "EDIT",
        "EDIT1": "EDIT1",
        "EDIT2": "EDIT2",
        "APPRL1": "PROC",
        "APPRL2": "PROC",
        "PROC": "PROC",
        "IMPL": "IMPL",
        "PE提交": "PE提交",
        "NCR管理员": "NCR管理员",
        "NCR管理员审核": "NCR管理员",
        "PE科室经理": "PE科室经理",
        "PE科室经理审核": "PE科室经理",
        "价值工程师": "价值工程师",
        "价值工程师审核": "价值工程师",
        "价值工程经理": "价值工程经理",
        "价值工程经理审核": "价值工程经理",
        "PE部门总监": "PE部门总监",
        "PE部门总监审批": "PE部门总监",
        "PE部门总监审核": "PE部门总监",
        "财务工程师": "财务工程师",
        "财务工程师审核": "财务工程师",
        "平台项目管理专家": "平台项目管理专家",
        "平台项目管理专家审核": "平台项目管理专家",
        "海外项目总监": "海外项目总监",
        "海外项目总监批准": "海外项目总监",
        "平台首席": "平台首席",
        "平台首席批准": "平台首席",
        "动力平台首席": "动力平台首席",
        "动力平台首席批准": "动力平台首席",
        "财务部总监": "财务部总监",
        "财务总监批准": "财务部总监",
    }
    if text in aliases:
        return aliases[text]
    for alias, normalized in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and text.startswith(alias):
            return normalized
    return str(value or "").strip()


def _normalize_tdc_status(value: object) -> str:
    """Normalize TDC list/status codes before deriving completion metrics."""
    text = _safe_text(value, 120)
    return {"4": "已完成"}.get(text, text)


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
    stage_days: int | None = None,
    late_days: int | None = None,
) -> str:
    """Return on_time, overdue, unknown, or not_applicable.

    ``stage_days``/``late_days`` override the approved per-report defaults
    (see ``_OVERDUE_RULES``).  EWO PROC keeps the calendar-month rule when the
    effective late value is the default 30 days; any other value compares by
    plain day difference.
    """
    report = _report_type(form_key)
    rules = _OVERDUE_RULES.get(report) or {}
    effective_stage_days = (
        int(stage_days) if stage_days is not None else int(rules.get("stageDays", 7))
    )
    effective_late_days = (
        int(late_days) if late_days is not None else int(rules.get("lateDays", 7))
    )
    if report == "ncr_detail":
        return "not_applicable"
    if report == "tdc_data_model":
        # 数模的阶段维度是项目/车型，可能为空或与审批阶段词表冲突；
        # 逾期只取决于状态与申请日期滞留天数，不依赖项目/车型取值，
        # 因此必须在通用 stage 守卫之前判定。
        status = _normalize_tdc_status(row.get("status"))
        if (
            row.get("isCompleted")
            or status == _TDC_DEPRECATED_STATUS
            or _normalize_stage(status) == "CLOSE"
        ):
            return "not_applicable"
        current = _snapshot_date(snapshot_at)
        start_date = _parse_date(row.get("stageStart"))
        if current is None or start_date is None:
            return "unknown"
        return (
            "overdue"
            if current > start_date + timedelta(days=effective_stage_days)
            else "on_time"
        )
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
            return (
                "overdue"
                if end_date > start_date + timedelta(days=effective_stage_days)
                else "on_time"
            )
        if stage == "PROC":
            if start_date is None:
                return "unknown"
            if effective_late_days == _OVERDUE_RULES["ewo"]["lateDays"]:
                threshold = _add_months(start_date, 1)
            else:
                threshold = start_date + timedelta(days=effective_late_days)
            return "overdue" if end_date > threshold else "on_time"
        if stage == "IMPL":
            if planned_date is None:
                return "unknown"
            return "overdue" if current > planned_date else "on_time"
        return "unknown"
    if report == "paa":
        if stage in {"DRAFT1", "DRAFT2", "EDIT"}:
            if start_date is None:
                return "unknown"
            return (
                "overdue"
                if end_date > start_date + timedelta(days=effective_stage_days)
                else "on_time"
            )
        if stage == "PROC":
            if start_date is None:
                return "unknown"
            return (
                "overdue"
                if end_date > start_date + timedelta(days=effective_late_days)
                else "on_time"
            )
        if stage == "IMPL":
            if planned_date is None:
                return "unknown"
            return "overdue" if current > planned_date else "on_time"
        return "unknown"
    if report == "ncr_progress":
        if start_date is None:
            return "unknown"
        days = (
            effective_stage_days
            if stage in _NCR_STAGE_FIRST_TWO
            else effective_late_days
        )
        return "overdue" if end_date > start_date + timedelta(days=days) else "on_time"
    return "unknown"


def form_definition(form_key: str) -> dict[str, Any]:
    """Return a copy of the allowlisted form schema for one form key."""
    report = _report_type(form_key)
    contract = report_contracts()[report]
    table = table_payload(report, [])
    raw_columns = table["columns"]
    if not isinstance(raw_columns, Sequence) or isinstance(raw_columns, (str, bytes)):
        raise ValueError("form table columns are invalid")
    columns = [dict(column) for column in raw_columns if isinstance(column, Mapping)]
    hidden_indexes = _TDC_HIDDEN_COLUMN_INDEXES.get(report, frozenset())
    if hidden_indexes:
        columns = [
            column
            for column in columns
            if int(column.get("index", -1)) not in hidden_indexes
        ]
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
    key_labels = list(_KEY_COLUMN_LABELS.get(report, ()))
    label_to_index = {
        str(column.get("label") or "").strip(): int(column.get("index", -1))
        for column in columns
    }
    key_columns = [
        label_to_index[label]
        for label in key_labels
        if label in label_to_index and label_to_index[label] >= 0
    ]
    filter_fields = [
        "keyword",
        "status",
        "department",
        "section",
        "model",
        "stage",
        "dateStart",
        "dateEnd",
    ]
    if report in _RELATION_FIELD_BY_REPORT:
        filter_fields.append("relationEwo")
    rules = _OVERDUE_RULES.get(report)
    definition = {
        "formKey": form_key,
        "reportType": report,
        "sheetNames": list(_SHEET_NAMES_BY_FORM_KEY[form_key]),
        "headerRows": contract["headerRows"],
        "dataHeaderRow": int(contract.get("dataHeaderRow", 0)),
        "columns": columns,
        "defaultVisibleCount": (
            _TDC_DEFAULT_VISIBLE_COUNT
            if report in _TDC_HIDDEN_COLUMN_INDEXES
            else int(contract["defaultVisibleCount"])
        ),
        "keyColumns": key_columns,
        "filterFields": filter_fields,
        "chartFields": list(_STAGES_BY_REPORT[report]),
    }
    if rules:
        definition["overdueRules"] = {
            "stageDays": int(rules["stageDays"]),
            "lateDays": int(rules["lateDays"]),
            "stageLabel": (
                "起草/编辑阶段"
                if report in {"ewo", "paa"}
                else "前两个节点（NCR管理员 / PE科室经理）"
            ),
            "lateLabel": (
                "PROC 阶段"
                if report in {"ewo", "paa"}
                else "后续审批节点"
            ),
            "note": (
                "IMPL 只比较要求完成时间；CLOSE=完成；日期缺失=未判定"
                if report == "ewo"
                else (
                    "IMPL 只比较估计完成日期；CLOSE=完成；日期缺失=未判定"
                    if report == "paa"
                    else "财务总监批准=审批完成；节点日期缺失=未判定"
                )
            ),
        }
    return definition


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
    department: object | None
    section: object | None
    model: object | None
    status: object | None
    stage: str
    submitted: object | None
    planned: object | None
    contact: object | None
    stage_start: object | None
    ncr_number: object | None = None
    if report == "tdc_data_model":
        # TDC UWF 列表 JSON（键名见 core.report_contracts 源字段映射）。
        department = ""
        section = _source_value(row, "department")
        model = _source_value(row, "publishProperty", "publishingProperties")
        status = _normalize_tdc_status(_source_value(row, "status"))
        stage = _normalize_stage(_source_value(row, "projectModel"))
        submitted = _source_value(row, "requestDate")
        planned = None
        contact = None
        stage_start = _date_text(submitted)
    elif report == "ewo":
        department = _source_value(row, "_department", "_rsp_department")
        section = _source_value(row, "_rsp_smt", "_section")
        model = _source_value(row, "_modelinfo", "modelInfo")
        status = _source_value(row, "state", "current_state__name")
        stage = _normalize_stage(status)
        submitted = _source_value(row, "_submit_time", "submit_date")
        planned = _source_value(row, "_required_date", "required_date")
        contact = _source_value(row, "_rsp_phone", "phone")
        stage_start = _stage_date_from_mapping(row, "DRAFT1")
    else:
        department = _source_value(row, "_department", "_pe_tdc_department")
        section = _source_value(row, "_pe_tdc_smt", "_requester_smt")
        model = _source_value(row, "_vehicles", "_modelinfo")
        status = _source_value(row, "state", "current_state__name")
        stage = _normalize_stage(status)
        submitted = _source_value(row, "_submit_date", "submit_date")
        planned = _source_value(row, "_est_cmpl_date", "estimated_complete_date")
        contact = _source_value(row, "_requester_phone", "_pe_tdc_phone")
        stage_start = _stage_date_from_mapping(row, "DRAFT1")
        if report in {"ncr_progress", "ncr_detail"}:
            ncr_number = _source_value(
                row,
                "_ncr_no",
                "ncr_no",
                "ncrNumber",
                "NCR编号",
            )
    dimensions = {
        "department": _safe_text(department, 160),
        "section": _safe_text(section, 160),
        "model": _safe_text(model, 160),
        "status": _safe_text(status, 120),
        "stage": stage,
    }
    if report in {"ncr_progress", "ncr_detail"}:
        normalized_ncr_number = _safe_text(ncr_number, 200)
        if normalized_ncr_number:
            dimensions["ncrNumber"] = normalized_ncr_number
    return (
        dimensions,
        {
            "submittedDate": _date_text(submitted),
            "plannedDate": _date_text(planned),
            "contact": _mask_contact(contact),
            "stageStart": stage_start,
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
    if is_completed:
        # NCR 的财务部总监审批完成是流程完成标志；完成字段优先于
        # 当前节点文本，避免“已完成”记录落在未注册的自定义节点上。
        stage = "CLOSE"
    dimensions = {
        "department": "",
        "section": _safe_text(section, 160),
        "model": _safe_text(model, 160),
        "status": _safe_text(status, 120),
        "stage": stage,
    }
    ncr_number = _safe_text(
        _positional_value(values, definition, "NCR编号"),
        200,
    )
    if ncr_number:
        dimensions["ncrNumber"] = ncr_number
    return (
        dimensions,
        {
            "submittedDate": _date_text(submitted),
            "plannedDate": _date_text(planned),
            "stageStart": _date_text(
                _positional_value(values, definition, "PE填写")
            ) if report == "ncr_progress" else None,
            "isCompleted": is_completed,
        },
    )


def _dimensions_from_tdc(
    values: Sequence[object],
    definition: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, object]]:
    """数模设计审核流程 47 列位置行的维度提取。

    维度口径：项目状态页签 ← 项目/车型（stage），部门状态页签 ← 部门
    （section），发布属性仅作筛选（model）；申请日期同时作为提交日期
    与逾期判定起点。
    """
    submitted = _positional_value(values, definition, "申请日期")
    status = _normalize_tdc_status(_positional_value(values, definition, "状态"))
    return (
        {
            "department": "",
            "section": _safe_text(
                _positional_value(values, definition, "部门"), 160
            ),
            "model": _safe_text(
                _positional_value(values, definition, "发布属性"), 160
            ),
            "status": status,
            "stage": _normalize_stage(
                _positional_value(values, definition, "项目/车型")
            ),
        },
        {
            "submittedDate": _date_text(submitted),
            "plannedDate": None,
            "stageStart": _date_text(submitted),
        },
    )


def _workflow_dates_from_values(
    report: str,
    stage: str,
    values: Sequence[object],
    definition: Mapping[str, Any],
) -> dict[str, str | None]:
    """Resolve the current stage arrival and next-stage end dates."""
    if report == "ncr_detail" or not stage:
        return {"stageStart": None, "stageEnd": None}
    if report == "tdc_data_model":
        # 数模的阶段起点（申请日期）由维度提取给出；无后续阶段到达日。
        return {"stageStart": None, "stageEnd": None}
    if report == "ncr_progress":
        stage_index = (
            _STAGES_BY_REPORT[report].index(stage)
            if stage in _STAGES_BY_REPORT[report]
            else -1
        )

        def ncr_arrival(stage_name: str) -> str | None:
            labels = _NCR_PROGRESS_STAGE_DATE_LABELS.get(stage_name, ())
            return _date_text(_positional_value_any(values, definition, labels))

        stage_start = ncr_arrival(stage)
        next_stage = (
            _STAGES_BY_REPORT[report][stage_index + 1]
            if 0 <= stage_index < len(_STAGES_BY_REPORT[report]) - 1
            else ""
        )
        return {
            "stageStart": stage_start,
            "stageEnd": ncr_arrival(next_stage) if next_stage else None,
        }
    stages = _STAGES_BY_REPORT[report]
    source_stage_names = [stage]
    if report == "paa" and stage == "PROC":
        source_stage_names = ["PROC", "APPRL1", "APPRL2"]

    def arrival(names: Sequence[str]) -> str | None:
        labels = [f"到达{name}的日期" for name in names]
        if report == "ewo" and names == ["CLOSE"]:
            labels.append("CLOZ的日期")
        if report == "paa" and names == ["CLOSE"]:
            labels.append("CLOZ的日期")
        return _date_text(_positional_value_any(values, definition, labels))

    try:
        stage_index = stages.index(stage)
    except ValueError:
        stage_index = -1
    next_names = (
        [stages[stage_index + 1]]
        if 0 <= stage_index < len(stages) - 1
        else []
    )
    return {
        "stageStart": arrival(source_stage_names),
        "stageEnd": arrival(next_names) if next_names else None,
    }


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
    normalized = [
        _clean_value(value, contact=index in contact_indexes)
        for index, value in enumerate(values)
    ]
    if report == "tdc_data_model" and len(normalized) > 46:
        normalized[46] = _normalize_tdc_status(normalized[46])
    return normalized


def _tdc_header_mapping_values(
    row: Mapping[str, object],
    definition: Mapping[str, Any],
) -> list[object] | None:
    """Restore positional TDC values from an official Chinese-header row."""
    headers = definition.get("headerRows", [[]])[0]
    if not isinstance(headers, Sequence) or isinstance(headers, (str, bytes)):
        return None
    header_names = [str(header or "").strip() for header in headers]
    if not any(name and name in row for name in header_names):
        return None
    return [row.get(name) if name else None for name in header_names]


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
        source = {str(key): value for key, value in raw.items()}
        header_mapping_values = (
            _tdc_header_mapping_values(source, definition)
            if report == "tdc_data_model"
            else None
        )
        if isinstance(positional, Sequence) and not isinstance(positional, (str, bytes)):
            values = _safe_values(report, list(positional))
            if report == "tdc_data_model":
                dimensions, dates = _dimensions_from_tdc(values, definition)
            else:
                dimensions, dates = _dimensions_from_ncr(report, values, definition)
            cost = _cost_from_values(values, definition) if report == "ncr_detail" else {}
            identity = "|".join(str(value or "") for value in values[:10])
        elif header_mapping_values is not None:
            values = _safe_values(report, header_mapping_values)
            dimensions, dates = _dimensions_from_tdc(values, definition)
            cost = {}
            identity = str(
                _source_value(
                    source,
                    "实例号",
                    "流水单号",
                    "incident",
                    "formId",
                    "documentNo",
                )
                or "|".join(str(value or "") for value in values[:5])
            )
        else:
            table = table_payload(report, [source])
            raw_rows = table["rows"]
            if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
                raise ValueError("form table rows are invalid")
            raw_values = raw_rows[0] if raw_rows else []
            if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                raise ValueError("form table row values are invalid")
            values = _safe_values(report, raw_values)
            dimensions, dates = _dimensions_from_mapping(report, source)
            cost = {}
            identity_keys = (
                ("incident", "formId", "documentNo")
                if report == "tdc_data_model"
                else ("_no", "id", "keyed_name", "ncr_no")
            )
            identity = str(
                _source_value(source, *identity_keys)
                or "|".join(str(value or "") for value in values[:5])
            )
        stage = dimensions["stage"]
        status = dimensions["status"]
        workflow_dates = _workflow_dates_from_values(
            report,
            stage,
            values,
            definition,
        )
        if workflow_dates["stageStart"] is None:
            workflow_dates["stageStart"] = _date_text(dates.get("stageStart"))
        dates.update(workflow_dates)
        is_completed = bool(
            dates.get("isCompleted")
            or stage == "CLOSE"
            or _normalize_stage(status) == "CLOSE"
        )
        row_for_due = {
            "stage": stage,
            "status": status,
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


def _metric_rows(
    report: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Apply read-side completion compatibility to metric rows."""
    result: list[Mapping[str, Any]] = []
    for row in rows:
        updated = dict(row)
        raw_dimensions = row.get("dimensions")
        dimensions = (
            dict(raw_dimensions) if isinstance(raw_dimensions, Mapping) else {}
        )
        status = (
            _normalize_tdc_status(dimensions.get("status"))
            if report == "tdc_data_model"
            else dimensions.get("status")
        )
        completed = bool(row.get("isCompleted"))
        if report == "tdc_data_model" and status == _TDC_DEPRECATED_STATUS:
            completed = False
        elif completed or _normalize_stage(status) == "CLOSE":
            completed = True
        if report == "ncr_progress" and completed:
            dimensions["stage"] = "CLOSE"
        if report == "tdc_data_model":
            dimensions["status"] = str(status or "")
        updated["dimensions"] = dimensions
        updated["isCompleted"] = completed
        if completed or (
            report == "tdc_data_model" and status == _TDC_DEPRECATED_STATUS
        ):
            updated["overdueState"] = "not_applicable"
        result.append(updated)
    return result


def _distinct_ncr_rows(
    form_key: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return one stable representative row per NCR for status metrics.

    NCR progress may contain duplicate exported records and NCR detail has a
    deliberate one-to-many relationship with detail rows. Blank identifiers
    are kept as separate rows because collapsing unrelated unknown records
    would undercount them. The original physical rows remain available to
    detail paging and cost aggregation.
    """
    if _report_type(form_key) not in {"ncr_progress", "ncr_detail"}:
        return list(rows)
    definition = form_definition(form_key)
    representatives: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        dimensions = row.get("dimensions")
        ncr_number = ""
        if isinstance(dimensions, Mapping):
            ncr_number = _safe_text(dimensions.get("ncrNumber"), 200)
        # Snapshots written before NCR identity was added have no usable
        # dimension value. Recover the identifier from the preserved
        # positional row so historical trend metrics use entity grain too.
        if ncr_number.casefold() in {"none", "null"}:
            ncr_number = ""
        if not ncr_number:
            values = row.get("values")
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                ncr_number = _safe_text(
                    _positional_value(list(values), definition, "NCR编号"),
                    200,
                )
        if ncr_number.casefold() in {"none", "null"}:
            ncr_number = ""
        identity = f"ncr:{ncr_number}" if ncr_number else f"row:{index}"
        representatives.setdefault(identity, row)
    return list(representatives.values())


def _stage_status_summary(
    report: str,
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stages = _STAGES_BY_REPORT[report]
    if report == "tdc_data_model":
        observed: set[str] = set()
        for row in rows:
            dimensions = row.get("dimensions")
            if isinstance(dimensions, Mapping):
                value = str(dimensions.get("stage") or "").strip()
                if value:
                    observed.add(value)
        stages = tuple(sorted(observed))
    official = set(stages)
    for stage in stages:
        selected = [
            row for row in rows
            if str(row.get("dimensions", {}).get("stage") or "") == stage
        ]
        result.append(
            {
                "label": stage,
                "onTime": sum(_status_bucket(row) == "on_time" for row in selected),
                "overdue": sum(_status_bucket(row) == "overdue" for row in selected),
                "unknown": sum(_status_bucket(row) == "unknown" for row in selected),
            }
        )
    if report in {"ewo", "paa", "ncr_progress"}:
        # OPEN、CANCEL、起草、挂起以及未注册的自定义节点统一聚合为
        # “其他状态”单独展示，不并入按期/逾期阶段列（用户 2026-09-02 确认）。
        others = [
            row for row in rows
            if str(row.get("dimensions", {}).get("stage") or "")
            and str(row.get("dimensions", {}).get("stage") or "") not in official
        ]
        if others:
            result.append(
                {
                    "label": "其他状态",
                    "onTime": sum(_status_bucket(row) == "on_time" for row in others),
                    "overdue": sum(_status_bucket(row) == "overdue" for row in others),
                    "unknown": sum(_status_bucket(row) == "unknown" for row in others),
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
    metric_rows = _metric_rows(
        report,
        _distinct_ncr_rows(form_key, rows),
    )
    total = len(metric_rows)
    completed = sum(bool(row.get("isCompleted")) for row in metric_rows)
    if report == "tdc_data_model":
        incomplete = 0
        for row in metric_rows:
            if bool(row.get("isCompleted")):
                continue
            dimensions = row.get("dimensions")
            status = (
                str(dimensions.get("status") or "")
                if isinstance(dimensions, Mapping)
                else ""
            )
            if status != _TDC_DEPRECATED_STATUS:
                incomplete += 1
    else:
        incomplete = total - completed
    overdue = sum(row.get("overdueState") == "overdue" for row in metric_rows)
    unknown = sum(row.get("overdueState") == "unknown" for row in metric_rows)
    result: dict[str, Any] = {
        "total": total,
        "completed": completed,
        "incomplete": incomplete,
        "overdue": overdue,
        "unknown": unknown,
        "snapshotAt": snapshot_at,
        "departmentStatus": {"stages": _stage_status_summary(report, metric_rows)},
        "sectionStatus": _section_status_summary(metric_rows),
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
        "relationEwo",
    }
)
# 同一字段内多选为 OR；这些键接受标量（向后兼容）或字符串列表。
_MULTI_FILTER_KEYS = frozenset(
    {"status", "department", "section", "model", "stage", "overdueState"}
)
_MULTI_FILTER_MAX_VALUES = 20
_VIEW_FILTER_TEXT_LIMIT = 200
_RELATION_FIELD_BY_REPORT = {
    "paa": ("EWO编号",),
    "ncr_progress": ("EWO号",),
    "ncr_detail": ("EWO号",),
}


def normalize_overdue_thresholds(
    thresholds: Mapping[str, object] | None,
) -> dict[str, int] | None:
    """Validate optional overdue-day overrides for one read request."""
    if thresholds is None:
        return None
    if not isinstance(thresholds, Mapping):
        raise ValueError("overdue thresholds must be a mapping")
    unknown = set(thresholds) - {"overdueDaysStage", "overdueDaysLate"}
    if unknown:
        raise ValueError("unsupported overdue threshold")
    normalized: dict[str, int] = {}
    for key, value in thresholds.items():
        if value in (None, ""):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"invalid overdue threshold: {key}")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid overdue threshold: {key}") from exc
        if not _OVERDUE_THRESHOLD_MIN <= parsed <= _OVERDUE_THRESHOLD_MAX:
            raise ValueError(
                f"{key} must be between "
                f"{_OVERDUE_THRESHOLD_MIN} and {_OVERDUE_THRESHOLD_MAX}"
            )
        normalized[key] = parsed
    return normalized or None


def _normalize_filter_text(key: str, value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"invalid form view filter: {key}")
    text = str(value).strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"form view filter contains control characters: {key}")
    if len(text) > _VIEW_FILTER_TEXT_LIMIT:
        raise ValueError(f"form view filter is too long: {key}")
    return text


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
        if value in (None, "", ()):
            continue
        if key == "isCompleted" and isinstance(value, bool):
            normalized[key] = value
            continue
        if key in _MULTI_FILTER_KEYS:
            raw_items = value if isinstance(value, (list, tuple)) else [value]
            if not isinstance(raw_items, (list, tuple)):
                raise ValueError(f"invalid form view filter: {key}")
            cleaned: list[str] = []
            for item in raw_items[:_MULTI_FILTER_MAX_VALUES * 2]:
                text = _normalize_filter_text(key, item)
                if text and text not in cleaned:
                    cleaned.append(text)
            if len(cleaned) > _MULTI_FILTER_MAX_VALUES:
                raise ValueError(f"too many values for form view filter: {key}")
            if cleaned:
                normalized[key] = cleaned[0] if len(cleaned) == 1 else cleaned
            continue
        text = _normalize_filter_text(key, value)
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


def _recomputed_overdue_state(
    form_key: str,
    row: Mapping[str, Any],
    definition: Mapping[str, Any],
    *,
    snapshot_at: str,
    stage_days: int | None,
    late_days: int | None,
) -> str:
    """Re-derive one stored row's overdue state under custom thresholds."""
    report = _report_type(form_key)
    if report == "ncr_detail":
        return "not_applicable"
    values = row.get("values")
    values_list = (
        list(values)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes))
        else []
    )
    raw_dimensions = row.get("dimensions")
    dimensions: Mapping[str, Any] = (
        raw_dimensions if isinstance(raw_dimensions, Mapping) else {}
    )
    stage = str(dimensions.get("stage") or "")
    status = str(dimensions.get("status") or "")
    workflow = _workflow_dates_from_values(report, stage, values_list, definition)
    if report == "ncr_progress" and not workflow.get("stageStart"):
        # 与发布路径一致：流程起点回退到 PE填写 列（如“起草”等未注册节点）。
        workflow["stageStart"] = _date_text(
            _positional_value(values_list, definition, "PE填写")
        )
    stage_start = workflow.get("stageStart") or row.get("stageStart")
    if report == "tdc_data_model" and not stage_start:
        # 快照行将申请日期持久化为 submittedDate；TDC 没有审批阶段日期列，
        # 因此读取侧阈值重算必须复用该字段作为滞留起点。
        stage_start = row.get("submittedDate") or _date_text(
            _positional_value(values_list, definition, "申请日期")
        )
    row_for_due = {
        "stage": stage,
        "status": status,
        "stageStart": stage_start,
        "stageEnd": workflow.get("stageEnd"),
        "plannedDate": row.get("plannedDate"),
        "isCompleted": bool(row.get("isCompleted")),
    }
    return classify_overdue(
        form_key,
        row_for_due,
        snapshot_at=snapshot_at,
        stage_days=stage_days,
        late_days=late_days,
    )


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

    @staticmethod
    def _apply_overdue_thresholds(
        form_key: str,
        rows: list[dict[str, Any]],
        *,
        snapshot_at: str,
        thresholds: Mapping[str, int],
    ) -> list[dict[str, Any]]:
        definition = form_definition(form_key)
        stage_days = thresholds.get("overdueDaysStage")
        late_days = thresholds.get("overdueDaysLate")
        recomputed: list[dict[str, Any]] = []
        for row in rows:
            updated = dict(row)
            updated["overdueState"] = _recomputed_overdue_state(
                form_key,
                row,
                definition,
                snapshot_at=snapshot_at,
                stage_days=stage_days,
                late_days=late_days,
            )
            recomputed.append(updated)
        return recomputed

    @staticmethod
    def _filter_overdue_states(
        rows: list[dict[str, Any]],
        wanted: object,
    ) -> list[dict[str, Any]]:
        if not wanted:
            return rows
        values = wanted if isinstance(wanted, list) else [wanted]
        states = {str(item) for item in values}
        return [row for row in rows if str(row.get("overdueState")) in states]

    def rows(
        self,
        form_key: str,
        filters: Mapping[str, object] | None = None,
        *,
        offset: int = 0,
        limit: int = 200,
        overdue_thresholds: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        key = self._validate_key(form_key)
        normalized = normalize_form_filters(filters)
        thresholds = normalize_overdue_thresholds(overdue_thresholds)
        if thresholds is None:
            result = self.db.list_deliverable_form_rows(
                key,
                normalized,
                offset=offset,
                limit=limit,
            )
            return dict(result)
        latest = self.db.get_latest_deliverable_form_snapshot(key)
        bounded_offset = max(0, int(offset))
        bounded_limit = max(1, min(int(limit), 500))
        if latest is None:
            return {
                "items": [],
                "total": 0,
                "offset": bounded_offset,
                "limit": bounded_limit,
            }
        effective_filters = {
            name: value
            for name, value in normalized.items()
            if name != "overdueState"
        }
        snapshot_at = str(latest.get("snapshot_at") or "")
        all_rows = self.db.list_deliverable_form_snapshot_rows(
            int(latest["id"]),
            effective_filters,
        )
        all_rows = self._apply_overdue_thresholds(
            key,
            all_rows,
            snapshot_at=snapshot_at,
            thresholds=thresholds,
        )
        all_rows = self._filter_overdue_states(
            all_rows,
            normalized.get("overdueState"),
        )
        return {
            "items": all_rows[bounded_offset:bounded_offset + bounded_limit],
            "total": len(all_rows),
            "offset": bounded_offset,
            "limit": bounded_limit,
        }

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
        overdue_thresholds: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        key = self._validate_key(form_key)
        normalized_filters = normalize_form_filters(filters)
        thresholds = normalize_overdue_thresholds(overdue_thresholds)
        if isinstance(trend_limit, bool) or not 1 <= int(trend_limit) <= 365:
            raise ValueError("trendLimit must be between 1 and 365")
        trend_count = int(trend_limit)
        definition = form_definition(key)
        latest = self.db.get_latest_deliverable_form_snapshot(key)
        # A job may run more than once per day. Read the full bounded history
        # so the 30-natural-day aggregation can select the last snapshot per
        # day instead of the last 30 runs.
        snapshots = self.db.list_deliverable_form_snapshots(key, limit=365)
        latest_rows: list[dict[str, Any]] = []
        effective_filters = dict(normalized_filters)
        if thresholds:
            # 阈值覆盖时逾期状态在读取侧重算，SQL 层不再按存储口径过滤。
            effective_filters.pop("overdueState", None)
        if latest is not None:
            latest_rows = self.db.list_deliverable_form_snapshot_rows(
                int(latest["id"]),
                effective_filters,
            )
            snapshot_at = str(latest.get("snapshot_at") or "")
            if thresholds:
                latest_rows = self._apply_overdue_thresholds(
                    key,
                    latest_rows,
                    snapshot_at=snapshot_at,
                    thresholds=thresholds,
                )
                latest_rows = self._filter_overdue_states(
                    latest_rows,
                    normalized_filters.get("overdueState"),
                )
            summary = summarize_form_rows(
                key,
                latest_rows,
                snapshot_at=snapshot_at,
            )
            # Stored schema metadata is historical. The view endpoint must
            # expose the current allowlisted contract after additive schema
            # changes, even when the newest database snapshot predates them.
            schema = definition
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
            trend_inputs = []
            report = _report_type(key)
            for item in snapshots:
                stored_schema = item.get("schema")
                needs_compatibility_recompute = (
                    report in {"ncr_progress", "ncr_detail"}
                    and (
                        not isinstance(stored_schema, Mapping)
                        or "keyColumns" not in stored_schema
                    )
                )
                if needs_compatibility_recompute:
                    item_rows = self.db.list_deliverable_form_snapshot_rows(
                        int(item["id"]),
                    )
                    trend_inputs.append(
                        {
                            "snapshotAt": item.get("snapshot_at"),
                            "summary": summarize_form_rows(
                                key,
                                item_rows,
                                snapshot_at=str(item.get("snapshot_at") or ""),
                            ),
                        }
                    )
                else:
                    trend_inputs.append(item)
        trend = aggregate_daily_trend(trend_inputs, limit=trend_count)
        option_rows = latest_rows
        if latest is not None and normalized_filters:
            # Option discovery is independent from the active selection so a
            # user can add a second value without losing it from the menu.
            option_rows = self.db.list_deliverable_form_snapshot_rows(
                int(latest["id"]),
            )
            if thresholds:
                option_rows = self._apply_overdue_thresholds(
                    key,
                    option_rows,
                    snapshot_at=str(latest.get("snapshot_at") or ""),
                    thresholds=thresholds,
                )
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
            "overdueThresholds": thresholds,
            "sync": self._sync_status(key),
            "filters": {
                "fields": list(definition["filterFields"]) + [
                    "overdueState",
                    "isCompleted",
                ],
                "applied": normalized_filters,
                "options": _filter_options(option_rows),
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
