# -*- coding: utf-8 -*-
"""Deterministic deliverable snapshot statistics: pure functions, endpoint
contract and static frontend wiring (no AI, no network, no SQL in the
computation module)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from core.db_manager import DatabaseManager
from services.deliverable_form_analysis import (
    _distinct_ncr_rows,
    _metric_rows,
    build_form_snapshot,
)
from services.deliverable_statistics import (
    _metric_grain_rows,
    compute_form_statistics,
    parse_activity_date,
    statistics_history_entry,
)


def _ewo_row(
    identity: str,
    *,
    status: str = "进行中",
    stage: str = "PROC",
    submitted: object = "2026-09-01",
    is_completed: bool = False,
) -> dict[str, object]:
    return {
        "dimensions": {"status": status, "stage": stage, "department": "", "section": "", "model": ""},
        "values": [identity],
        "submittedDate": submitted,
        "plannedDate": None,
        "isCompleted": is_completed,
        "overdueState": "unknown",
    }


TODAY = date(2026, 9, 11)


# ── 纯函数单测（算术精确断言）───────────────────────────────────────


def test_parse_activity_date_accepts_day_granularity_and_rejects_garbage() -> None:
    assert parse_activity_date("2026-09-01") == date(2026, 9, 1)
    assert parse_activity_date("2026-09-01T08:30:00Z") == date(2026, 9, 1)
    assert parse_activity_date("2026-09-01 08:30:00") == date(2026, 9, 1)
    assert parse_activity_date("") is None
    assert parse_activity_date(None) is None
    assert parse_activity_date("not-a-date") is None
    assert parse_activity_date("2026-13-40") is None


def test_compute_form_statistics_exact_arithmetic() -> None:
    rows = [
        # 在途 10 天（2026-09-01 → 2026-09-11）
        _ewo_row("EWO-A", submitted="2026-09-01"),
        # 在途 5 天
        _ewo_row("EWO-B", submitted="2026-09-06"),
        # 在途 15 天
        _ewo_row("EWO-C", submitted="2026-08-27"),
        # 已完成：不参与停滞
        _ewo_row("EWO-D", status="已完成", is_completed=True),
        # 终态（stage CLOSE）：不参与停滞
        _ewo_row("EWO-F", status="已完成", submitted="2026-07-01"),
        # 非法时间列：剔除并计数
        _ewo_row("EWO-E", submitted="bad-date"),
    ]
    stats = compute_form_statistics(
        "VPI-T2-D3", rows, snapshot_at="2026-09-11T08:00:00", today=TODAY
    )

    assert stats["formKey"] == "VPI-T2-D3"
    assert stats["reportType"] == "ewo"
    assert stats["totalRecords"] == 6
    assert stats["inFlightCount"] == 4
    assert stats["invalidActivityDateCount"] == 1
    # 状态分布计数（计数稳定排序：多值按数量降序、同数按名称）。
    assert {"status": "进行中", "count": 4} in stats["statusDistribution"]
    assert {"status": "已完成", "count": 2} in stats["statusDistribution"]

    stagnation = stats["stagnation"]
    assert stagnation is not None
    assert stagnation["sampleCount"] == 3
    assert stagnation["mean"] == 10.0
    assert stagnation["median"] == 10.0
    assert stagnation["stdDev"] == round(((50 / 3) ** 0.5), 2)
    assert stagnation["max"] == 15

    # 停滞 Top：15 → 10 → 5。
    top = stats["stagnationTop"]
    assert [item["identity"] for item in top] == ["EWO-C", "EWO-A", "EWO-B"]
    assert top[0]["stagnationDays"] == 15
    assert top[0]["stage"] == "PROC"
    assert top[0]["status"] == "进行中"

    by_status = {item["label"]: item for item in stats["stagnationByStatus"]}
    assert by_status["进行中"]["mean"] == 10.0
    assert by_status["进行中"]["count"] == 3
    by_stage = {item["label"]: item for item in stats["stagnationByStage"]}
    assert by_stage["PROC"]["mean"] == 10.0

    # 无历史 → 离散度排名为空（2.1 结论：跨快照方差需要历史观测）。
    assert stats["dispersion"] == []
    assert stats["layout"]["identityLabel"] == "EWO编号"
    assert stats["layout"]["dispersionMode"] == "cross_snapshot_variance"


def test_compute_form_statistics_cross_snapshot_variance_ranking() -> None:
    rows = [
        _ewo_row("EWO-A", submitted="2026-09-01"),
        _ewo_row("EWO-B", submitted="2026-09-06"),
    ]
    # EWO-A：快照日 2026-09-09 → 8 天；2026-09-05 → 4 天；方差 = 4.0。
    history = [
        statistics_history_entry("2026-09-09", rows),
        statistics_history_entry("2026-09-05", rows),
        # 快照时间无法解析的条目被跳过。
        {"snapshotAt": "garbage", "rows": rows},
    ]
    stats = compute_form_statistics(
        "VPI-T2-D3",
        rows,
        snapshot_at="2026-09-11T08:00:00",
        history=history,
        today=TODAY,
    )
    assert stats["historySnapshotCount"] == 2
    dispersion = stats["dispersion"]
    assert [item["identity"] for item in dispersion] == ["EWO-A"]
    # values [8, 4]：mean 6，方差 = ((8-6)² + (4-6)²)/2 = 4.0。
    assert dispersion[0]["variance"] == 4.0
    assert dispersion[0]["observations"] == 2
    assert dispersion[0]["latestStagnationDays"] == 8


def test_compute_form_statistics_ncr_identity_and_sor_terminal_statuses() -> None:
    ncr_rows = [
        {
            "dimensions": {"status": "审批中", "stage": "NCR管理员", "ncrNumber": "NCR-1"},
            "values": [],
            "submittedDate": "2026-09-02",
            "isCompleted": False,
        },
        {
            "dimensions": {"status": "审批中", "stage": "NCR管理员", "ncrNumber": ""},
            "values": [],
            "submittedDate": "2026-09-04",
            "isCompleted": False,
        },
    ]
    stats = compute_form_statistics(
        "aras_ncr_progress", ncr_rows, snapshot_at="2026-09-11", today=TODAY
    )
    top = stats["stagnationTop"]
    assert top[0]["identity"] == "NCR-1"
    assert top[0]["stagnationDays"] == 9
    # 空单号退化为行号身份，仍是独立记录。
    assert top[1]["identity"].startswith("row:")

    sor_rows = [
        _ewo_row("SOR-1", status="审批中", submitted="2026-09-01"),
        _ewo_row("SOR-2", status="已终止", submitted="2026-08-01"),
        _ewo_row("SOR-3", status="已完成", submitted="2026-08-01", is_completed=True),
    ]
    sor_stats = compute_form_statistics(
        "tdc_sor", sor_rows, snapshot_at="2026-09-11", today=TODAY
    )
    assert sor_stats["inFlightCount"] == 1
    assert sor_stats["stagnation"]["max"] == 10
    assert sor_stats["layout"]["identityLabel"] == "流水单号"


def test_metric_grain_rows_passes_report_type_not_form_key() -> None:
    """_metric_rows 首参语义是 report 类型：aras form_key 必须先转换。

    回归锁定：此前 _metric_grain_rows 把 form_key 直接传给 _metric_rows，
    aras 各表落入非特化 else 分支——aras_ncr_progress 的 completed 行不再
    补 stage=CLOSE（与 report=ncr_progress 行为不一致）；TDC 两表因
    form_key 与 report 名巧合相等才未暴露。
    """
    rows = [
        {
            "dimensions": {"status": "审批中", "stage": "NCR管理员", "ncrNumber": "NCR-1"},
            "values": [],
            "submittedDate": "2026-09-02",
            "isCompleted": True,
        },
        {
            "dimensions": {"status": "审批中", "stage": "NCR管理员", "ncrNumber": ""},
            "values": [],
            "submittedDate": "2026-09-04",
            "isCompleted": False,
        },
    ]
    grain = _metric_grain_rows("aras_ncr_progress", rows)
    expected = _metric_rows(
        "ncr_progress", _distinct_ncr_rows("aras_ncr_progress", list(rows))
    )
    assert grain == expected
    # report=ncr_progress 的完成兼容语义：completed 行显式补 stage=CLOSE。
    assert grain[0]["dimensions"]["stage"] == "CLOSE"
    assert grain[0]["isCompleted"] is True

    # 非特化 report（paa，走 _metric_rows 的 else 分支）行内容保持原样，
    # 不注入 stage=CLOSE，与 report="paa" 直接调用结果一致。
    paa_rows = [
        {
            "dimensions": {"status": "审批中"},
            "values": [],
            "submittedDate": "2026-09-02",
            "isCompleted": True,
        }
    ]
    paa_grain = _metric_grain_rows("aras_paa", paa_rows)
    assert paa_grain == _metric_rows("paa", _distinct_ncr_rows("aras_paa", list(paa_rows)))
    assert paa_grain[0]["isCompleted"] is True
    assert paa_grain[0]["dimensions"]["status"] == "审批中"
    assert "stage" not in paa_grain[0]["dimensions"]


def test_compute_form_statistics_rejects_unregistered_form_key() -> None:
    with pytest.raises(KeyError):
        compute_form_statistics("unknown_key", [], snapshot_at="2026-09-11")


def test_statistics_history_entry_skips_unparseable_snapshot_time() -> None:
    assert statistics_history_entry("garbage", []) is None
    entry = statistics_history_entry("2026-09-09T18:00:00Z", [])
    assert entry is not None
    assert entry["snapshotAt"] == "2026-09-09"


# ── 端点契约测试 ────────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    import web.app as web_app

    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "stats-web.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client(), db_cls(tmp_path / "stats-web.db")


def test_statistics_endpoint_404_for_unregistered_form_key(client) -> None:  # type: ignore[no-untyped-def]
    flask_client, _ = client
    response = flask_client.get("/api/deliverable-forms/not_a_form_key/statistics")
    assert response.status_code == 404
    body = response.get_json()
    assert body["ok"] is False


def test_statistics_endpoint_empty_state_without_snapshot(client) -> None:  # type: ignore[no-untyped-def]
    flask_client, _ = client
    response = flask_client.get("/api/deliverable-forms/aras_paa/statistics")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert body["ok"] is True
    assert body["data"]["hasSnapshot"] is False
    assert body["data"]["statistics"] is None


def _publish_paa_snapshot(db: DatabaseManager, *, snapshot_at: str, run_id: int) -> None:
    snapshot = build_form_snapshot(
        "aras_paa",
        [
            {
                "_no": "PAA-STAT-1",
                "_department": "车身开发部",
                "_pe_tdc_smt": "车体工程",
                "_vehicles": "F610S",
                "state": "APPRL1",
                "_submit_date": "2026-09-01",
            },
            {
                "_no": "PAA-STAT-2",
                "_department": "动力总成部",
                "_pe_tdc_smt": "动力总成",
                "_vehicles": "F510S",
                "state": "CLOZ",
                "_submit_date": "2026-08-20",
            },
        ],
        snapshot_at=snapshot_at,
        source_run_id=run_id,
        source="test archive",
    )
    assert db.publish_deliverable_form_snapshot(snapshot) > 0


def test_statistics_endpoint_computes_from_latest_snapshot(client) -> None:  # type: ignore[no-untyped-def]
    flask_client, db = client
    _publish_paa_snapshot(db, snapshot_at="2026-09-10T08:00:00Z", run_id=1)
    _publish_paa_snapshot(db, snapshot_at="2026-09-11T08:00:00Z", run_id=2)

    response = flask_client.get("/api/deliverable-forms/aras_paa/statistics")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["hasSnapshot"] is True
    assert data["snapshotAt"] == "2026-09-11T08:00:00Z"
    stats = data["statistics"]
    assert stats["totalRecords"] == 2
    assert stats["inFlightCount"] == 1
    # 端点以真实今天为参照日：PAA-STAT-1 提交 2026-09-01。
    expected_days = (date.today() - date(2026, 9, 1)).days
    assert stats["stagnation"]["max"] == expected_days
    assert stats["stagnationTop"][0]["identity"] == "PAA-STAT-1"
    # JSON 可序列化（无 date/非标对象残留）。
    json.dumps(body)


def test_statistics_endpoint_history_row_cap_truncates(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """历史快照累计行数达到 _STATISTICS_MAX_HISTORY_ROWS 即停止装载。

    构造 4 份快照（最新 1 份 + 历史 3 份，每份 2 行）并把上限调小到 4：
    从新到旧装载 2 份历史（累计 4 行）后停止，historyTruncated=True，
    部分历史仍参与统计（historySnapshotCount=2）。
    """
    import web.app as web_app

    flask_client, db = client
    monkeypatch.setattr(web_app, "_STATISTICS_MAX_HISTORY_ROWS", 4)
    _publish_paa_snapshot(db, snapshot_at="2026-09-10T08:00:00Z", run_id=1)
    _publish_paa_snapshot(db, snapshot_at="2026-09-11T08:00:00Z", run_id=2)

    response = flask_client.get("/api/deliverable-forms/aras_paa/statistics")
    assert response.status_code == 200
    data = response.get_json()["data"]
    # 未超限：仅 1 份历史（2 行），累计上限内，历史完整。
    assert data["historyTruncated"] is False
    assert data["statistics"]["historySnapshotCount"] == 1

    _publish_paa_snapshot(db, snapshot_at="2026-09-08T08:00:00Z", run_id=3)
    _publish_paa_snapshot(db, snapshot_at="2026-09-09T08:00:00Z", run_id=4)

    response = flask_client.get("/api/deliverable-forms/aras_paa/statistics")
    data = response.get_json()["data"]
    # 3 份历史（各 2 行）：从新到旧装载 2 份（累计 4 行）后停止。
    assert data["historyTruncated"] is True
    stats = data["statistics"]
    # 部分历史仍可用：最新 2 份历史参与统计，其余被截断。
    assert stats["historySnapshotCount"] == 2
    assert stats["totalRecords"] == 2


# ── 前端静态契约（按 tests/test_deliverable_form_ui.py 先例）────────


def _read(name: str) -> str:
    return Path(name).read_text(encoding="utf-8-sig")


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


def test_statistics_ui_static_contract() -> None:
    js = _read("web/static/app.js")
    css = _read("web/static/style.css")

    statistics_source = _slice(
        js,
        "function statisticsNumberText",
        "function buildPaaInteractiveFilters",
    )
    # 端点接线与折叠区渲染。
    assert "/api/deliverable-forms/" in statistics_source
    assert "/statistics" in statistics_source
    assert "deliverable-statistics" in statistics_source
    assert "统计分析" in statistics_source
    # 指标卡 / 状态分布条 / Top5 表 / 离散度排名。
    assert "statistics-metric-grid" in statistics_source
    assert "statistics-status-distribution" in statistics_source
    assert "statistics-top-table" in statistics_source
    assert "statistics-dispersion-list" in statistics_source
    assert "跨快照方差" in statistics_source
    # 空/加载/错误态。
    assert "暂无快照数据" in statistics_source
    assert "正在读取快照统计" in statistics_source
    assert "statistics-load-error" in statistics_source
    # Safe DOM：统计分析代码段不允许 innerHTML。
    assert "innerHTML" not in statistics_source

    # 外部快照驱动徽标（环图卡与明细行）。
    assert "snapshot-driven-badge" in js
    assert "外部快照·参考" in js
    assert "formSnapshotDriven" in js

    for marker in (
        ".deliverable-statistics",
        ".snapshot-driven-badge",
        ".statistics-metric-grid",
        ".statistics-status-fill",
        ".statistics-top-table",
        ".statistics-dispersion-list",
    ):
        assert marker in css


def test_statistics_section_wired_into_form_view_renderer() -> None:
    js = _read("web/static/app.js")
    renderer_source = _slice(
        js,
        "function renderDeliverableFormAnalysis",
        "function buildPaaInteractiveFilters",
    )
    assert "renderDeliverableStatisticsSection(item)" in renderer_source
