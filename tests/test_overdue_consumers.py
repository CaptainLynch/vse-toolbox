# -*- coding: utf-8 -*-
"""DSH-V2-11：逾期单一口径接入项目展示真实调用链的跨消费方一致性测试。

契约 C5/C9 要求「逾期只由 ``core.time_rules`` 的单一内核计算，列表与详情
共用」。本文件不复测内核本身（见 ``tests/test_time_rules.py``），而是经**真实
生产函数**验证两条消费路径对同一输入给出相同的逾期状态与天数：

1. 列表路径：``ProjectStatusDeliverableAnalysisService.latest_link_summary()``
   （看板联动摘要）与 ``.overview()``（详情页概览）的汇总计数；
2. 详情路径：``.items()`` 的逐行 ``alertType`` / ``days``（分页与 alert 两个分支）。

覆盖：纯日期输入、EWO 阶段机来源语义、已完成行、缺计划日期行，以及北京时间
跨午夜边界（UTC 15:59 → 23:59 北京 vs UTC 16:00 → 次日 00:00 北京）。

另含两条守卫：
- ``test_production_paths_actually_call_time_rules_kernel``：用 monkeypatch 证明
  两个生产模块确实调用内核（不是各留一套日期比较）；
- ``test_manual_progress_and_effective_progress_semantics_preserved``：手工
  ``progress`` 与派生 ``effectiveProgress`` 的分离语义未被本次改动触碰
  （API 级锁定见 ``tests/test_project_status_policy_api.py``）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

import core.project_status_contracts as contracts
import services.project_status_deliverable_analysis as analysis
from core.db_manager import DatabaseManager
from core.project_status_contracts import derive_effective_progress
from core.time_rules import overdue_state, to_beijing
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
)

#: EWO 交付物（列表路径按当前日期重算）与非 EWO 交付物（列表路径读存储快照）。
EWO_DELIVERABLE_ID = "VPI-T2-D3"
TDC_DELIVERABLE_ID = "VPI-T2-D5"


def _ewo_row(
    number: str,
    stage: str,
    planned: str | None,
    *,
    actual: str | None = None,
) -> dict[str, Any]:
    """ARAS EWO 连接器产出的行结构（部门关键词 + 阶段码 + `_` 前缀字段）。"""
    row: dict[str, Any] = {
        "id": f"ROW-{number}",
        "_no": number,
        "_subject": f"任务 {number}",
        "_rsp_department": "技术中心_车体工程",
        "_rsp_smt": "车体科",
        "_rsp_name": "莫仕沾",
        "state": stage,
    }
    if planned is not None:
        row["_required_date"] = planned
    if actual is not None:
        row["completedDate"] = actual
    return row


def _tdc_row(
    number: str,
    status: str,
    planned: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"ROW-{number}",
        "documentNo": number,
        "title": f"任务 {number}",
        "department": "质量科",
        "applicant": "张三",
        "status": status,
    }
    if planned is not None:
        row["dueDate"] = planned
    return row


def _service(db: DatabaseManager, today: date) -> ProjectStatusDeliverableAnalysisService:
    return ProjectStatusDeliverableAnalysisService(db, clock=lambda: today)


def _detail_rows(
    service: ProjectStatusDeliverableAnalysisService,
    deliverable_id: str,
) -> dict[str, dict[str, Any]]:
    payload = service.items(deliverable_id)
    return {item["itemNumber"]: item for item in payload["items"]}


def _assert_rows_match_kernel(
    rows: dict[str, dict[str, Any]],
    today: date,
) -> None:
    """逐行断言：详情行的 (alertType, days) 就是内核对该行输入的结果。

    唯一的有意差异：已完成行沿用历史契约 ``(None, None)``（不展示天数计数），
    而内核的 completed 覆盖分支返回 days=0。
    """
    assert rows, "详情路径必须返回行"
    for number, item in rows.items():
        if item["completed"]:
            assert (item["alertType"], item["days"]) == (None, None), number
            continue
        state = overdue_state(item["plannedDate"], False, today=today)
        if state.unset:
            assert (item["alertType"], item["days"]) == ("missing_due_date", None), number
        elif state.state == "overdue":
            assert (item["alertType"], item["days"]) == ("overdue", state.days), number
        elif state.state == "due_soon":
            assert (item["alertType"], item["days"]) == ("due_soon", state.days), number
        else:
            assert item["alertType"] is None, number
            assert item["days"] == state.days, number


def _assert_list_matches_detail(
    service: ProjectStatusDeliverableAnalysisService,
    deliverable_id: str,
    rows: dict[str, dict[str, Any]],
    *,
    check_link_summary: bool,
) -> None:
    """列表汇总计数必须与详情逐行分类计数一致（同一输入、同一 today）。"""
    detail_overdue = service.items(deliverable_id, alert="overdue")
    detail_due_soon = service.items(deliverable_id, alert="due_soon")
    detail_missing = service.items(deliverable_id, alert="missing_due_date")

    overview = service.overview(deliverable_id)["summary"]
    assert overview["total"] == len(rows)
    assert overview["completed"] == sum(1 for item in rows.values() if item["completed"])
    assert overview["overdue"] == detail_overdue["total"]
    assert overview["dueSoon"] == detail_due_soon["total"]
    assert overview["missingDueDate"] == detail_missing["total"]

    # alert 过滤结果与逐行 alertType 分类严格同源。
    assert {item["itemNumber"] for item in detail_overdue["items"]} == {
        number for number, item in rows.items() if item["alertType"] == "overdue"
    }
    assert {item["itemNumber"] for item in detail_due_soon["items"]} == {
        number for number, item in rows.items() if item["alertType"] == "due_soon"
    }
    assert {item["itemNumber"] for item in detail_missing["items"]} == {
        number for number, item in rows.items() if item["alertType"] == "missing_due_date"
    }

    if check_link_summary:
        # 看板联动摘要（列表真实入口）与详情概览同口径。
        link = service.latest_link_summary(deliverable_id)
        assert link is not None
        assert link["summary"]["total"] == overview["total"]
        assert link["summary"]["completed"] == overview["completed"]
        assert link["summary"]["overdue"] == overview["overdue"]


# ── 1. 列表 vs 详情：EWO（列表路径按当前日期重算） ────────────────────────────


def test_ewo_list_and_detail_overdue_agree(tmp_db: DatabaseManager) -> None:
    """同一批 EWO 行：看板联动摘要/概览的逾期计数与详情逐行状态、天数一致。"""
    today = date(2026, 8, 24)
    rows = [
        _ewo_row("EWO-OVERDUE-5", "IMPL", "2026-08-19"),
        _ewo_row("EWO-DUE-TODAY", "EDIT2", "2026-08-24"),
        _ewo_row("EWO-DUE-SOON-3", "PROC", "2026-08-27"),
        _ewo_row("EWO-FUTURE-8", "DRAFT1", "2026-09-01"),
        _ewo_row("EWO-CLOSE-PAST", "CLOSE", "2026-08-10", actual="2026-08-09"),
        # OPEN 不在 EWO 展示范围（_item_is_in_scope），两条路径必须同时排除它。
        _ewo_row("EWO-OPEN-PAST", "OPEN", "2026-08-01"),
        _ewo_row("EWO-NO-DATE", "IMPL", None),
    ]
    service = _service(tmp_db, today)
    service.publish(
        EWO_DELIVERABLE_ID,
        501,
        rows,
        snapshot_at="2026-08-24T01:00:00Z",
        source_type="aras_ewo",
    )

    detail = _detail_rows(service, EWO_DELIVERABLE_ID)
    assert "EWO-OPEN-PAST" not in detail, "OPEN 阶段不得进入展示范围"
    assert set(detail) == {
        "EWO-OVERDUE-5",
        "EWO-DUE-TODAY",
        "EWO-DUE-SOON-3",
        "EWO-FUTURE-8",
        "EWO-CLOSE-PAST",
        "EWO-NO-DATE",
    }
    _assert_rows_match_kernel(detail, today)

    # 具体数字（纯日期口径，无时区参与）：
    assert (detail["EWO-OVERDUE-5"]["alertType"], detail["EWO-OVERDUE-5"]["days"]) == (
        "overdue",
        5,
    )
    assert (detail["EWO-DUE-TODAY"]["alertType"], detail["EWO-DUE-TODAY"]["days"]) == (
        "due_soon",
        0,
    )
    assert (detail["EWO-DUE-SOON-3"]["alertType"], detail["EWO-DUE-SOON-3"]["days"]) == (
        "due_soon",
        3,
    )
    assert (detail["EWO-FUTURE-8"]["alertType"], detail["EWO-FUTURE-8"]["days"]) == (None, 8)
    assert (detail["EWO-NO-DATE"]["alertType"], detail["EWO-NO-DATE"]["days"]) == (
        "missing_due_date",
        None,
    )

    _assert_list_matches_detail(
        service, EWO_DELIVERABLE_ID, detail, check_link_summary=True
    )


# ── 2. 列表 vs 详情：非 EWO（列表路径读存储快照） ────────────────────────────


def test_tdc_list_and_detail_overdue_agree(tmp_db: DatabaseManager) -> None:
    """非 EWO 交付物：存储快照摘要（列表）与详情逐行状态/天数同口径。"""
    today = date(2026, 8, 24)
    rows = [
        _tdc_row("TDC-OVERDUE-5", "进行中", "2026-08-19"),
        _tdc_row("TDC-DUE-TODAY", "审批中", "2026-08-24"),
        _tdc_row("TDC-FUTURE-12", "进行中", "2026-09-05"),
        _tdc_row("TDC-DONE", "已完成", "2026-08-01"),
        _tdc_row("TDC-NO-DATE", "进行中", None),
    ]
    service = _service(tmp_db, today)
    service.publish(
        TDC_DELIVERABLE_ID,
        502,
        rows,
        snapshot_at="2026-08-24T01:00:00Z",
        source_type="tdc_data_model",
    )

    detail = _detail_rows(service, TDC_DELIVERABLE_ID)
    assert set(detail) == {
        "TDC-OVERDUE-5",
        "TDC-DUE-TODAY",
        "TDC-FUTURE-12",
        "TDC-DONE",
        "TDC-NO-DATE",
    }
    _assert_rows_match_kernel(detail, today)

    # 已完成行即使计划日期早于今天也不得计为逾期（内核 completed 覆盖）。
    assert (detail["TDC-DONE"]["alertType"], detail["TDC-DONE"]["days"]) == (None, None)
    assert (detail["TDC-OVERDUE-5"]["days"]) == 5
    assert (detail["TDC-DUE-TODAY"]["alertType"], detail["TDC-DUE-TODAY"]["days"]) == (
        "due_soon",
        0,
    )

    _assert_list_matches_detail(
        service, TDC_DELIVERABLE_ID, detail, check_link_summary=True
    )


# ── 3. 北京时间跨午夜边界 ─────────────────────────────────────────────────────


def test_beijing_midnight_boundary_keeps_list_and_detail_in_sync(
    tmp_db: DatabaseManager,
) -> None:
    """UTC 16:00 = 北京次日 00:00：跨午夜后两条路径必须同步翻到「逾期 1 天」。"""
    before_midnight = datetime(2026, 8, 23, 15, 59, tzinfo=timezone.utc)
    at_midnight = datetime(2026, 8, 23, 16, 0, tzinfo=timezone.utc)

    # 纯日期不位移：同一 UTC 时刻按北京时间取日期，恰好跨天。
    today_before = to_beijing(before_midnight).date()
    today_after = to_beijing(at_midnight).date()
    assert today_before == date(2026, 8, 23)
    assert today_after == date(2026, 8, 24)

    rows = [
        _ewo_row("EWO-PLANNED-0823", "IMPL", "2026-08-23"),
        _ewo_row("EWO-PLANNED-0824", "IMPL", "2026-08-24"),
    ]
    publisher = _service(tmp_db, today_before)
    publisher.publish(
        EWO_DELIVERABLE_ID,
        503,
        rows,
        snapshot_at=before_midnight.isoformat().replace("+00:00", "Z"),
        source_type="aras_ewo",
    )

    # 午夜前：08-23 当天到期（due_soon 0）、08-24 剩 1 天，均未逾期。
    before = _service(tmp_db, today_before)
    before_rows = _detail_rows(before, EWO_DELIVERABLE_ID)
    _assert_rows_match_kernel(before_rows, today_before)
    assert (before_rows["EWO-PLANNED-0823"]["alertType"], before_rows["EWO-PLANNED-0823"]["days"]) == (
        "due_soon",
        0,
    )
    _assert_list_matches_detail(
        before, EWO_DELIVERABLE_ID, before_rows, check_link_summary=True
    )
    assert before.overview(EWO_DELIVERABLE_ID)["summary"]["overdue"] == 0

    # 午夜后（北京次日）：08-23 变成逾期 1 天、08-24 当天到期；列表与详情同步。
    after = _service(tmp_db, today_after)
    after_rows = _detail_rows(after, EWO_DELIVERABLE_ID)
    _assert_rows_match_kernel(after_rows, today_after)
    assert (after_rows["EWO-PLANNED-0823"]["alertType"], after_rows["EWO-PLANNED-0823"]["days"]) == (
        "overdue",
        1,
    )
    assert (after_rows["EWO-PLANNED-0824"]["alertType"], after_rows["EWO-PLANNED-0824"]["days"]) == (
        "due_soon",
        0,
    )
    _assert_list_matches_detail(
        after, EWO_DELIVERABLE_ID, after_rows, check_link_summary=True
    )
    assert after.overview(EWO_DELIVERABLE_ID)["summary"]["overdue"] == 1
    assert after.latest_link_summary(EWO_DELIVERABLE_ID)["summary"]["overdue"] == 1


# ── 4. 生产调用方证据：两个模块确实调用 core/time_rules.py ───────────────────


def test_production_paths_actually_call_time_rules_kernel(
    tmp_db: DatabaseManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """monkeypatch 探针：分析服务与展示契约都必须经过 core.time_rules.overdue_state。"""
    today = date(2026, 8, 24)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    real_analysis_kernel = analysis.overdue_state
    real_contracts_kernel = contracts.overdue_state

    def _spy(tag: str, real: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append((tag, args, kwargs))
            return real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(analysis, "overdue_state", _spy("analysis", real_analysis_kernel))
    monkeypatch.setattr(contracts, "overdue_state", _spy("contracts", real_contracts_kernel))

    service = _service(tmp_db, today)
    service.publish(
        EWO_DELIVERABLE_ID,
        504,
        [_ewo_row("EWO-OVERDUE-2", "IMPL", "2026-08-22")],
        snapshot_at="2026-08-24T01:00:00Z",
        source_type="aras_ewo",
    )
    calls.clear()

    # 列表路径（概览 + 看板联动摘要）与详情路径（分页 + alert）都要打到内核。
    service.overview(EWO_DELIVERABLE_ID)
    service.latest_link_summary(EWO_DELIVERABLE_ID)
    service.items(EWO_DELIVERABLE_ID)
    service.items(EWO_DELIVERABLE_ID, alert="overdue")

    analysis_calls = [call for call in calls if call[0] == "analysis"]
    assert analysis_calls, "分析服务必须调用 core.time_rules.overdue_state"
    assert any(
        args and args[0] == "2026-08-22" and kwargs.get("today") == today
        for _, args, kwargs in analysis_calls
    ), "逾期判定必须以计划日期与注入的今天调用内核"

    # 展示契约的节点状态（列表/详情共用）同样走内核。
    assert contracts.milestone_display_status("planned", "2026-05-01", today) == "已超期"
    assert contracts.milestone_display_status("planned", "2026-09-01", today) == "未开始"
    assert contracts.milestone_display_status("done", "2026-05-01", today) == "已完成"

    contracts_calls = [call for call in calls if call[0] == "contracts"]
    assert contracts_calls, "milestone_display_status 必须调用 core.time_rules.overdue_state"
    assert all(kwargs.get("today") == today for _, _, kwargs in contracts_calls)
    # 「已完成」在调用内核前就已返回（完成覆盖优先），故只有两个未完成节点进内核。
    assert len(contracts_calls) == 2
    # 解析失败/未设置日期的节点不得伪造逾期，也不得调用内核。
    assert contracts.milestone_display_status("planned", "bad-date", today) == "未开始"
    assert contracts.milestone_display_status("进行中", None, today) == "进行中"
    assert len(contracts_calls) == 2


# ── 5. 手工 progress 与 effectiveProgress 分离语义保持不变 ───────────────────


def test_manual_progress_and_effective_progress_semantics_preserved() -> None:
    """快照态派生、其余态保留手工值；total=0 不伪造 0%（本次改动零触碰）。"""
    # 手工态：progress 原样（含 None / 越界钳制），来源标 manual。
    assert derive_effective_progress("manual", {"total": 5, "completed": 3}, 42) == (42, "manual")
    assert derive_effective_progress("manual", None, None) == (None, "manual")
    assert derive_effective_progress("paused", {"total": 5, "completed": 3}, 130) == (100, "manual")
    assert derive_effective_progress("manual", None, -3) == (0, "manual")
    assert derive_effective_progress("manual", None, True) == (None, "manual")
    assert derive_effective_progress("manual", None, "not-a-number") == (None, "manual")

    # 快照态：按 completed/total 换算；total=0 返回 None（前端显示「—」）。
    assert derive_effective_progress("snapshot", {"total": 4, "completed": 3}, 7) == (75, "snapshot")
    assert derive_effective_progress("snapshot", {"total": 0, "completed": 0}, 7) == (
        None,
        "snapshot",
    )
