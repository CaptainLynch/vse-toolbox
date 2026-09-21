"""Deterministic, AI-free snapshot statistics for deliverable form snapshots.

纯统计学模块：无 AI、无网络、无 SQL。输入为统一表单分析的规范化表单行
（services.deliverable_form_analysis 归一化/持久化后的行结构）与可选历史
快照，输出聚合统计与既有明面的单号/步骤字段——不引入新泄露面。

语义列映射（逐 form_key 对照 core/report_contracts 表头核对）：

- 记录标识列：EWO="EWO编号"、PAA="PAA编号"、NCR 两表="NCR编号"
  （优先 dimensions.ncrNumber）、数模="实例号"、SOR="流水单号"。
- 状态/步骤列：dimensions.status / dimensions.stage（持久化行均有）。
- 最后活动时间列：优先 stageStart（当前节点到达日，仅内存规范化行携带，
  数据库持久化行不含），回退 submittedDate（全部六个 form_key 的持久化行
  均有：TDC 两表即批准的审批滞留起点「申请日期」，ARAS 各表为「提交日期」）。
  时间列缺失或非法的行剔除出滞留统计并单独计数。

离散度排名（2.1 结论）：deliverable_form_snapshots 按 form_key 保留最近
365 份快照（_FORM_SNAPSHOT_RETENTION），历史趋势可行，故采用「记录级停滞
跨快照方差」而非 z-score；历史不足（同一记录少于 2 次观测）时排名为空。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from services.deliverable_form_analysis import (
    _distinct_ncr_rows,
    _metric_rows,
    _normalize_sor_status,
    _normalize_tdc_status,
    _normalize_stage,
    _positional_value,
    _report_type,
    form_definition,
)

__all__ = [
    "compute_form_statistics",
    "parse_activity_date",
    "statistics_history_entry",
]

#: 每个快照的记录级停滞观测在最近历史中的参与上限。
STATISTICS_HISTORY_SNAPSHOT_LIMIT = 30

_STAGNATION_TOP_LIMIT = 5

#: TDC 两表与 ARAS 各表的终态状态词（与 summarize_form_rows 口径一致）。
_TDC_DATA_MODEL_TERMINAL_STATUSES = frozenset({"已废弃"})
_NCR_CLOSE_STAGE = "CLOSE"

_FORM_STATISTICS_LAYOUTS: dict[str, dict[str, Any]] = {
    "VPI-T2-D3": {
        "reportType": "ewo",
        "identityLabel": "EWO编号",
        "identityDimension": None,
        "activityFields": ("stageStart", "submittedDate"),
        "activityLabel": "提交日期",
    },
    "aras_paa": {
        "reportType": "paa",
        "identityLabel": "PAA编号",
        "identityDimension": None,
        "activityFields": ("stageStart", "submittedDate"),
        "activityLabel": "提交日期",
    },
    "aras_ncr_progress": {
        "reportType": "ncr_progress",
        "identityLabel": "NCR编号",
        "identityDimension": "ncrNumber",
        "activityFields": ("stageStart", "submittedDate"),
        "activityLabel": "提交日期",
    },
    "aras_ncr_detail": {
        "reportType": "ncr_detail",
        "identityLabel": "NCR编号",
        "identityDimension": "ncrNumber",
        "activityFields": ("stageStart", "submittedDate"),
        "activityLabel": "提交日期",
    },
    "tdc_data_model": {
        "reportType": "tdc_data_model",
        "identityLabel": "实例号",
        "identityDimension": None,
        "activityFields": ("stageStart", "submittedDate"),
        "activityLabel": "申请日期",
    },
    "tdc_sor": {
        "reportType": "tdc_sor",
        "identityLabel": "流水单号",
        "identityDimension": None,
        "activityFields": ("stageStart", "submittedDate"),
        "activityLabel": "申请日期",
    },
}


def parse_activity_date(value: object) -> date | None:
    """Parse a persisted activity date (YYYY-MM-DD prefix) defensively.

    只接受日期粒度：缺失、空白或非法文本返回 None（行剔除并计数）。
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    head = text.replace("T", " ").split(" ")[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def _safe_text(value: object, limit: int = 200) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _row_dimensions(row: Mapping[str, Any]) -> Mapping[str, Any]:
    dimensions = row.get("dimensions")
    return dimensions if isinstance(dimensions, Mapping) else {}


def _row_identity(
    form_key: str,
    layout: Mapping[str, Any],
    row: Mapping[str, Any],
    fallback_index: int,
) -> str:
    """Extract the business record identity from a normalized row."""
    dimensions = _row_dimensions(row)
    dimension_key = layout.get("identityDimension")
    if isinstance(dimension_key, str):
        identity = _safe_text(dimensions.get(dimension_key))
        if identity:
            return identity
    definition = form_definition(form_key)
    values = row.get("values")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        identity = _safe_text(
            _positional_value(list(values), definition, str(layout["identityLabel"]))
        )
        if identity:
            return identity
    return f"row:{fallback_index}"


def _terminal_statuses(report: str) -> frozenset[str]:
    if report == "tdc_sor":
        return frozenset({"已终止", "已作废", "Terminated", "Cancelled"})
    if report == "tdc_data_model":
        return frozenset({"已废弃"})
    return frozenset()


def _normalize_status(report: str, status: object) -> str:
    if report == "tdc_sor":
        return _normalize_sor_status(status)
    if report == "tdc_data_model":
        return _normalize_tdc_status(status)
    return _safe_text(status)


def _metric_grain_rows(form_key: str, rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Metric grain：NCR 两表按 NCR 单号去重，其余按物理行；统一完成兼容。

    _metric_rows 首参语义是 report 类型（如 ncr_progress），不是 form_key
    （如 aras_ncr_progress）；TDC 两表因 form_key 与 report 名巧合相等才
    一直等价，其余 form_key 必须经 _report_type 转换后传入。
    """
    return list(
        _metric_rows(_report_type(form_key), _distinct_ncr_rows(form_key, list(rows)))
    )


def _row_stagnation(
    layout: Mapping[str, Any],
    row: Mapping[str, Any],
    reference_day: date,
) -> tuple[int | None, str | None]:
    """Return (stagnation_days, failure_reason) for one row.

    在途记录的最后活动日期按 layout.activityFields 顺序取第一个可用值；
    无可用日期（缺失/非法）返回 (None, "missing_activity_date")，日期晚于
    参照日（脏数据）返回 (None, "future_activity_date")。
    """
    for field in layout["activityFields"]:
        parsed = parse_activity_date(row.get(field))
        if parsed is None:
            continue
        days = (reference_day - parsed).days
        if days < 0:
            return None, "future_activity_date"
        return days, None
    return None, "missing_activity_date"


def _is_in_flight(report: str, row: Mapping[str, Any]) -> bool:
    """在途 = 非终态且未完成（与 summarize_form_rows 完成口径一致）。"""
    if bool(row.get("isCompleted")):
        return False
    status = _normalize_status(report, _row_dimensions(row).get("status"))
    if status in _terminal_statuses(report):
        return False
    if _normalize_stage(status) == _NCR_CLOSE_STAGE:
        return False
    return True


def _mean(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _std_dev(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5


def _variance(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _round2(value: float) -> float:
    return round(value + 0.0, 2)


def _grouped_stagnation_mean(
    observations: list[Mapping[str, Any]],
    key_field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[int]] = {}
    for item in observations:
        label = _safe_text(item.get(key_field)) or "未分配"
        days = item.get("stagnationDays")
        if isinstance(days, int):
            groups.setdefault(label, []).append(days)
    return [
        {
            "label": label,
            "count": len(days),
            "mean": _round2(_mean(days)),
        }
        for label, days in sorted(groups.items())
    ]


def compute_form_statistics(
    form_key: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_at: str,
    history: Sequence[Mapping[str, Any]] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Compute deterministic statistics from normalized form rows.

    - ``rows``：最新快照的规范化表单行（持久化行或内存规范化行均可）。
    - ``history``：可选历史快照列表，每项 ``{"snapshotAt": str, "rows": [...]}``；
      用于记录级停滞跨快照方差离散度排名。
    - ``today``：停滞天数参照日（默认 date.today()），保证测试确定性。
    """
    if form_key not in _FORM_STATISTICS_LAYOUTS:
        raise KeyError(form_key)
    layout: Mapping[str, Any] = _FORM_STATISTICS_LAYOUTS[form_key]
    report = _report_type(form_key)
    reference_day = today or date.today()

    metric_rows = _metric_grain_rows(form_key, rows)
    total_records = len(metric_rows)
    status_counts: dict[str, int] = {}
    for row in metric_rows:
        status = _normalize_status(report, _row_dimensions(row).get("status")) or "未知"
        status_counts[status] = status_counts.get(status, 0) + 1
    status_distribution = [
        {"status": status, "count": count}
        for status, count in sorted(
            status_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    in_flight_rows = [row for row in metric_rows if _is_in_flight(report, row)]
    observations: list[dict[str, Any]] = []
    missing_activity_date = 0
    future_activity_date = 0
    for index, row in enumerate(in_flight_rows):
        days, failure = _row_stagnation(layout, row, reference_day)
        if days is None:
            if failure == "future_activity_date":
                future_activity_date += 1
            else:
                missing_activity_date += 1
            continue
        dimensions = _row_dimensions(row)
        observations.append(
            {
                "identity": _row_identity(form_key, layout, row, index),
                "stage": _safe_text(dimensions.get("stage")) or "未分配",
                "status": _normalize_status(report, dimensions.get("status")) or "未知",
                "stagnationDays": days,
            }
        )

    stagnation_days = [item["stagnationDays"] for item in observations]
    stagnation_block: dict[str, Any] | None = None
    if stagnation_days:
        stagnation_block = {
            "sampleCount": len(stagnation_days),
            "mean": _round2(_mean(stagnation_days)),
            "median": _round2(_median(stagnation_days)),
            "stdDev": _round2(_std_dev(stagnation_days)),
            "max": max(stagnation_days),
        }
    stagnation_top = sorted(
        observations,
        key=lambda item: (-item["stagnationDays"], item["identity"]),
    )[:_STAGNATION_TOP_LIMIT]

    dispersion = _cross_snapshot_dispersion(form_key, layout, report, history, reference_day)

    return {
        "formKey": form_key,
        "reportType": report,
        "snapshotAt": str(snapshot_at or ""),
        "layout": {
            "identityLabel": str(layout["identityLabel"]),
            "activityLabel": str(layout["activityLabel"]),
            "activityFields": list(layout["activityFields"]),
            "stagnationSupported": bool(layout["activityFields"]),
            "dispersionMode": "cross_snapshot_variance",
        },
        "totalRecords": total_records,
        "inFlightCount": len(in_flight_rows),
        "invalidActivityDateCount": missing_activity_date + future_activity_date,
        "statusDistribution": status_distribution,
        "stagnation": stagnation_block,
        "stagnationTop": stagnation_top,
        "stagnationByStatus": _grouped_stagnation_mean(observations, "status"),
        "stagnationByStage": _grouped_stagnation_mean(observations, "stage"),
        "dispersion": dispersion,
        "historySnapshotCount": _count_usable_history(history),
    }


def _cross_snapshot_dispersion(
    form_key: str,
    layout: Mapping[str, Any],
    report: str,
    history: Sequence[Mapping[str, Any]] | None,
    reference_day: date,
) -> list[dict[str, Any]]:
    """记录级停滞跨快照方差排名（2.1 结论：历史保留多份，可行）。

    同一记录（按业务单号）在历史快照中的停滞天数（快照日 - 最后活动日，
    快照日粒度）少于 2 次观测不参与；方差降序，方差相同按单号稳定排序。
    """
    if not history:
        return []
    observations: dict[str, list[int]] = {}
    identity_stage: dict[str, str] = {}
    identity_latest: dict[str, int] = {}
    bounded = list(history)[-STATISTICS_HISTORY_SNAPSHOT_LIMIT:]
    for entry in bounded:
        if not isinstance(entry, Mapping):
            continue
        snapshot_day = parse_activity_date(entry.get("snapshotAt"))
        if snapshot_day is None:
            continue
        rows = entry.get("rows")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        metric_rows = _metric_grain_rows(form_key, list(rows))
        for index, row in enumerate(metric_rows):
            if not _is_in_flight(report, row):
                continue
            days, failure = _row_stagnation(layout, row, snapshot_day)
            if days is None:
                # 历史快照早于记录提交日 → 该记录当时尚不存在，跳过该次
                # 观测（当前快照路径才把未来日期计为脏数据）。
                continue
            identity = _row_identity(form_key, layout, row, index)
            observations.setdefault(identity, []).append(days)
            identity_stage[identity] = _safe_text(
                _row_dimensions(row).get("stage")
            ) or "未分配"
            identity_latest[identity] = max(identity_latest.get(identity, 0), days)
    result: list[dict[str, Any]] = []
    for identity, values in observations.items():
        if len(values) < 2:
            continue
        result.append(
            {
                "identity": identity,
                "stage": identity_stage.get(identity, "未分配"),
                "observations": len(values),
                "latestStagnationDays": identity_latest.get(identity, 0),
                "variance": _round2(_variance(values)),
            }
        )
    result.sort(key=lambda item: (-item["variance"], str(item["identity"])))
    return result


def _count_usable_history(history: Sequence[Mapping[str, Any]] | None) -> int:
    """历史快照中快照时间可解析为日期粒度的条目数（有界）。"""
    if not history:
        return 0
    bounded = list(history)[-STATISTICS_HISTORY_SNAPSHOT_LIMIT:]
    return sum(
        1
        for entry in bounded
        if isinstance(entry, Mapping)
        and parse_activity_date(entry.get("snapshotAt")) is not None
    )


def history_snapshot_day(value: object) -> date | None:
    """Expose snapshot-day parsing for callers assembling history entries."""
    return parse_activity_date(value)


def statistics_history_entry(
    snapshot_at: object,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Build one history entry for compute_form_statistics.

    快照时间无法解析为日期粒度时返回 None（调用方跳过该快照），
    保证日期粒度语义（timedelta 以天为单位）。
    """
    snapshot_day = parse_activity_date(snapshot_at)
    if snapshot_day is None:
        return None
    return {
        "snapshotAt": snapshot_day.isoformat(),
        "rows": [dict(row) for row in rows if isinstance(row, Mapping)],
    }
