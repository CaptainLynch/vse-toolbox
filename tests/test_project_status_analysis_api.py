from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
)


@pytest.fixture()
def client_and_db(monkeypatch, tmp_path: Path):
    db = DatabaseManager(tmp_path / "analysis-api.db")
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(project_status_clock=lambda: date(2026, 8, 23))
    app.config.update(TESTING=True)
    return app.test_client(), db


def test_phase_metadata_update_and_dynamic_today(client_and_db) -> None:
    client, _ = client_and_db
    before = client.get("/api/project-status").get_json()["data"]
    assert before["phase"]["today"] == "2026-08-23"
    # 主计划名称即车型锚点，种子默认 F610S。
    assert before["phase"]["displayName"] == "F610S"
    assert before["phase"]["riskCount"] == 3
    assert before["summary"]["risk"] == "EWO 流程已逾期 1 天"

    response = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "VPI-T2 整车交付主计划",
            "status": "进行中",
            "startDate": "2026-04-08",
            "endDate": "2026-09-05",
            "updatedAt": before["phase"]["updatedAt"],
        },
    )
    assert response.status_code == 200
    phase = response.get_json()["data"]["projectStatus"]["phase"]
    assert phase["displayName"] == "VPI-T2 整车交付主计划"
    assert phase["endDate"] == "2026-09-05"

    stale = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "stale",
            "status": "进行中",
            "startDate": "2026-04-08",
            "endDate": "2026-09-05",
            "updatedAt": before["phase"]["updatedAt"],
        },
    )
    assert stale.status_code == 409


def test_analysis_car_type_anchor_falls_back_to_phase_display_name(client_and_db) -> None:
    """未显式传 carType 时，分析接口回显主计划名称作为车型锚点，且跟随手动修改。"""
    client, _ = client_and_db
    analysis = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis")
    assert analysis.status_code == 200
    assert analysis.get_json()["data"]["carType"] == "F610S"

    items = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis/items")
    assert items.status_code == 200
    assert items.get_json()["data"]["carType"] == "F610S"

    before = client.get("/api/project-status").get_json()["data"]
    renamed = client.patch(
        "/api/project-status/phases/VPI-T2",
        json={
            "displayName": "G610M",
            "status": "进行中",
            "startDate": "2026-04-08",
            "endDate": "2026-09-05",
            "updatedAt": before["phase"]["updatedAt"],
        },
    )
    assert renamed.status_code == 200

    renamed_analysis = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis")
    assert renamed_analysis.get_json()["data"]["carType"] == "G610M"

    explicit = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis?carType=F710S"
    )
    # 显式参数仍优先于锚点回退。
    assert explicit.get_json()["data"]["carType"] == "F710S"


def test_analysis_api_returns_cache_departments_trend_and_warnings(client_and_db) -> None:
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(
        db,
        clock=lambda: date(2026, 8, 23),
    )
    service.publish(
        "VPI-T2-D5",
        77,
        [
            {
                "id": "task-1",
                "name": "冻结发布单确认",
                "department": "质量科",
                "owner": "赵岩",
                "status": "进行中",
                "dueDate": "2026-08-18",
            },
            {
                "id": "task-2",
                "name": "A 面数据确认",
                "department": "车身设计科",
                "owner": "陈璇",
                "status": "进行中",
                "dueDate": "2026-08-25",
            },
            {
                "id": "task-3",
                "name": "审批关闭",
                "department": "项目管理科",
                "status": "已完成",
                "dueDate": "2026-08-20",
            },
        ],
        snapshot_at="2026-08-23T06:00:00Z",
    )

    analysis = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/analysis"
    )
    assert analysis.status_code == 200
    data = analysis.get_json()["data"]
    assert data["summary"]["total"] == 3
    assert data["summary"]["completed"] == 1
    assert data["departments"]["质量科"]["incomplete"] == 1
    assert len(data["trend"]) == 1

    overdue = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/analysis/items?alert=overdue"
    )
    assert overdue.status_code == 200
    assert overdue.get_json()["data"]["items"][0]["days"] == 5

    invalid = client.get(
        "/api/project-status/deliverables/VPI-T2-D5/analysis/items?alert=unknown"
    )
    assert invalid.status_code == 422


def test_analysis_api_accepts_repeated_department_and_stage_filters(client_and_db) -> None:
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        88,
        [
            {"_no": "EWO-1", "_rsp_smt": "车身科", "state": "IMPL", "_required_date": "2026-08-20"},
            {"_no": "EWO-2", "_rsp_smt": "内饰科", "state": "CLOSE", "_required_date": "2026-08-20"},
            {"_no": "EWO-3", "_rsp_smt": "外饰科", "state": "OPEN", "_required_date": "2026-08-20"},
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )

    response = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis/items"
        "?departments=%E8%BD%A6%E8%BA%AB%E7%A7%91&departments=%E5%86%85%E9%A5%B0%E7%A7%91"
        "&stages=impl&stages=close"
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 2
    assert {row["stage"] for row in data["items"]} == {"impl", "close"}

    unknown = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis/items?departments=%E6%9C%AA%E7%9F%A5%E7%A7%91%E5%AE%A4"
    )
    assert unknown.status_code == 200
    assert unknown.get_json()["data"]["total"] == 0

    invalid_stage = client.get(
        "/api/project-status/deliverables/VPI-T2-D3/analysis/items?stages=not-a-stage"
    )
    assert invalid_stage.status_code == 422


def test_analysis_api_serializes_pending_signer_lines_and_close_alert(client_and_db) -> None:
    """API 输出每条一行 ROLE:person；CLOSE 永远无逾期提醒；stage 保持小写规范值。"""
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        91,
        [
            {
                "_no": "EWO-SIGN",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车身科",
                "state": "IMPL",
                "_required_date": "2026-08-20",
                "当前阶段未签署的角色&人员": "PE:张三;LEADER:李四，SQE:赵六",
            },
            {
                "_no": "EWO-CLOSE",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "state": "CLOSE",
                "_required_date": "2026-08-01",
            },
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )

    response = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis/items?stage=all")
    assert response.status_code == 200
    data = response.get_json()["data"]
    by_number = {row["itemNumber"]: row for row in data["items"]}
    assert by_number["EWO-SIGN"]["pendingSigners"] == "PE:张三\nLEADER:李四\nSQE:赵六"
    # CLOSE 是流程终点：无提醒（前端据此显示 未超期），阶段值保持小写
    assert by_number["EWO-CLOSE"]["alertType"] is None
    assert by_number["EWO-CLOSE"]["stage"] == "close"


def test_analysis_items_model_filter_and_match_types(client_and_db) -> None:
    """model 查询参数同时过滤明细与 overview 摘要；modelMatch 仅允许 fuzzy|exact。"""
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D3",
        92,
        [
            {
                "_no": "EWO-MA",
                "_subject": "F610S 蒙皮更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_modelinfo": "F610S-A",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
            {
                "_no": "EWO-MB",
                "_subject": "F610S 内饰更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_modelinfo": "F610S-B",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
            {
                "_no": "EWO-GM",
                "_subject": "G610M 顶盖更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "_modelinfo": "G610M",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
            {
                "_no": "EWO-NM",
                "_subject": "无车型信息更改",
                "_rsp_department": "技术中心_车体工程",
                "_rsp_smt": "车体科",
                "state": "IMPL",
                "_required_date": "2026-09-30T00:00:00",
            },
        ],
        source_type="aras",
        snapshot_at="2026-08-23T00:00:00Z",
    )
    items_url = "/api/project-status/deliverables/VPI-T2-D3/analysis/items"

    # 默认 fuzzy：大小写不敏感子串包含；model_info 为空的行不命中。
    fuzzy = client.get(f"{items_url}?model=F610S")
    assert fuzzy.status_code == 200
    fuzzy_data = fuzzy.get_json()["data"]
    assert fuzzy_data["total"] == 2
    assert {row["itemNumber"] for row in fuzzy_data["items"]} == {"EWO-MA", "EWO-MB"}

    exact_one = client.get(f"{items_url}?model=F610S-A&modelMatch=exact")
    assert exact_one.status_code == 200
    assert exact_one.get_json()["data"]["total"] == 1

    exact_zero = client.get(f"{items_url}?model=G610&modelMatch=exact")
    assert exact_zero.status_code == 200
    assert exact_zero.get_json()["data"]["total"] == 0

    # 空 model = 不按车型过滤（不受 modelMatch 影响）。
    empty_model = client.get(f"{items_url}?model=&modelMatch=exact")
    assert empty_model.status_code == 200
    assert empty_model.get_json()["data"]["total"] == 4

    bad_match = client.get(f"{items_url}?model=x&modelMatch=bogus")
    assert bad_match.status_code == 422

    too_long_model = "x" * 81
    too_long = client.get(f"{items_url}?model={too_long_model}")
    assert too_long.status_code == 422

    # 控制字符（换行）拒绝。
    control = client.get(f"{items_url}?model=F610%0A")
    assert control.status_code == 422

    overview = client.get("/api/project-status/deliverables/VPI-T2-D3/analysis?model=F610S")
    assert overview.status_code == 200
    overview_data = overview.get_json()["data"]
    assert overview_data["summary"]["total"] == 2
    # carType 维持回显锚点语义（主计划名 F610S），不参与过滤。
    assert overview_data["carType"] == "F610S"


def test_chart_labels_api_contract(client_and_db) -> None:
    """图表标签 API：候选字段、标签 CRUD 校验、customCharts 分组统计与本地写守卫。"""
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D5",
        93,
        [
            {
                "id": "C-1",
                "name": "冻结发布单确认",
                "department": "质量科",
                "owner": "张三",
                "_rsp_name": "张三",
                "status": "进行中",
                "dueDate": "2026-08-18",
            },
            {
                "id": "C-2",
                "name": "A 面数据确认",
                "department": "质量科",
                "owner": "陈璇",
                "_rsp_name": "陈璇",
                "status": "已完成",
                "dueDate": "2026-08-19",
            },
            {
                "id": "C-3",
                "name": "审批意见关闭",
                "department": "车身设计科",
                "owner": "周敏",
                "_rsp_name": "周敏",
                "status": "进行中",
                "dueDate": "2026-08-20",
            },
        ],
        snapshot_at="2026-08-23T00:00:00Z",
    )

    # 未配置标签时 customCharts 为空数组，前端回退现有科室图。
    before = client.get("/api/project-status/deliverables/VPI-T2-D5/analysis")
    assert before.status_code == 200
    assert before.get_json()["data"]["customCharts"] == []

    chart_labels_url = "/api/project-status/deliverables/VPI-T2-D5/chart-labels"
    fields_response = client.get(chart_labels_url)
    assert fields_response.status_code == 200
    fields_data = fields_response.get_json()["data"]
    assert fields_data["labels"] == []
    fields = fields_data["fields"]
    assert isinstance(fields, list)
    by_key = {field["key"]: field for field in fields}
    assert by_key["department"]["label"] == "科室"
    assert by_key["department"]["count"] >= 1
    assert by_key["_rsp_name"]["label"] == "负责人"
    assert by_key["_rsp_name"]["count"] >= 1
    # 候选字段按 count 降序、同数按 key 升序。
    for left, right in zip(fields, fields[1:]):
        assert left["count"] > right["count"] or (
            left["count"] == right["count"] and left["key"] <= right["key"]
        )

    saved = client.put(
        chart_labels_url,
        json={
            "labels": [
                {"label": "内容A", "sourceField": "department"},
                {"label": "内容B", "sourceField": "owner"},
            ]
        },
    )
    assert saved.status_code == 200
    saved_labels = saved.get_json()["data"]["labels"]
    assert saved_labels == [
        {
            "label": "内容A",
            "sourceField": "department",
            "sortOrder": 1,
            "groups": [],
            "unmatched": "keep",
        },
        {
            "label": "内容B",
            "sourceField": "owner",
            "sortOrder": 2,
            "groups": [],
            "unmatched": "keep",
        },
    ]
    reread = client.get(chart_labels_url)
    assert reread.status_code == 200
    assert reread.get_json()["data"]["labels"] == saved_labels

    # 校验失败 422，且不落库。
    too_many = client.put(
        chart_labels_url,
        json={"labels": [{"label": f"标签{i}", "sourceField": "department"} for i in range(7)]},
    )
    assert too_many.status_code == 422
    long_label = client.put(
        chart_labels_url,
        json={"labels": [{"label": "甲" * 41, "sourceField": "department"}]},
    )
    assert long_label.status_code == 422
    unknown_field = client.put(
        chart_labels_url,
        json={"labels": [{"label": "内容C", "sourceField": "no_such_field"}]},
    )
    assert unknown_field.status_code == 422
    # body 非 dict → 400。
    non_object = client.put(chart_labels_url, json=["not-a-dict"])
    assert non_object.status_code == 400

    after = client.get("/api/project-status/deliverables/VPI-T2-D5/analysis")
    assert after.status_code == 200
    charts = after.get_json()["data"]["customCharts"]
    assert len(charts) == 2
    assert charts[0] == {
        "label": "内容A",
        "sourceField": "department",
        "groups": {
            "质量科": {"total": 2, "completed": 1, "incomplete": 1},
            "车身设计科": {"total": 1, "completed": 0, "incomplete": 1},
        },
    }
    assert charts[1]["label"] == "内容B"
    assert charts[1]["sourceField"] == "owner"
    for counts in charts[1]["groups"].values():
        assert set(counts) == {"total", "completed", "incomplete"}

    # 未知交付物 404。
    missing = client.put(
        "/api/project-status/deliverables/VPI-T2-NOPE/chart-labels",
        json={"labels": [{"label": "内容A", "sourceField": "department"}]},
    )
    assert missing.status_code == 404


def test_chart_labels_group_mapping_api(client_and_db) -> None:
    """PUT 携带分组规则往返；非法规则 422；customCharts 分组键为映射后名称。"""
    client, db = client_and_db
    service = ProjectStatusDeliverableAnalysisService(db, clock=lambda: date(2026, 8, 23))
    service.publish(
        "VPI-T2-D5",
        94,
        [
            {
                "id": "G-1",
                "name": "任务一",
                "department": "内饰科",
                "owner": "甲",
                "status": "进行中",
                "dueDate": "2026-08-20",
            },
            {
                "id": "G-2",
                "name": "任务二",
                "department": "内饰工程科",
                "owner": "乙",
                "status": "已完成",
                "dueDate": "2026-08-19",
            },
            {
                "id": "G-3",
                "name": "任务三",
                "department": "结构工程科",
                "owner": "丙",
                "status": "进行中",
                "dueDate": "2026-09-15",
            },
        ],
        snapshot_at="2026-08-23T00:00:00Z",
    )
    url = "/api/project-status/deliverables/VPI-T2-D5/chart-labels"

    saved = client.put(
        url,
        json={
            "labels": [
                {
                    "label": "科室",
                    "sourceField": "department",
                    "groups": [{"name": "内饰科", "members": ["内饰科", "内饰工程科"]}],
                    "unmatched": "keep",
                },
            ]
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()["data"]["labels"] == [
        {
            "label": "科室",
            "sourceField": "department",
            "sortOrder": 1,
            "groups": [{"name": "内饰科", "members": ["内饰科", "内饰工程科"]}],
            "unmatched": "keep",
        },
    ]
    reread = client.get(url)
    assert reread.get_json()["data"]["labels"] == saved.get_json()["data"]["labels"]

    # 跨组成员重叠 → 校验失败 422。
    overlap = client.put(
        url,
        json={
            "labels": [
                {
                    "label": "科室",
                    "sourceField": "department",
                    "groups": [{"name": "A", "members": ["x"]}, {"name": "B", "members": ["x"]}],
                },
            ]
        },
    )
    assert overlap.status_code == 422

    # customCharts 分组键为映射后的显示组名。
    analysis = client.get("/api/project-status/deliverables/VPI-T2-D5/analysis")
    assert analysis.status_code == 200
    charts = analysis.get_json()["data"]["customCharts"]
    assert charts == [
        {
            "label": "科室",
            "sourceField": "department",
            "groups": {
                "内饰科": {"total": 2, "completed": 1, "incomplete": 1},
                "结构工程科": {"total": 1, "completed": 0, "incomplete": 1},
            },
        },
    ]

    # unmatched=other：未命中值并入"未分组"桶。
    other = client.put(
        url,
        json={
            "labels": [
                {
                    "label": "科室",
                    "sourceField": "department",
                    "groups": [{"name": "内饰科", "members": ["内饰科", "内饰工程科"]}],
                    "unmatched": "other",
                },
            ]
        },
    )
    assert other.status_code == 200
    analysis2 = client.get("/api/project-status/deliverables/VPI-T2-D5/analysis")
    charts2 = analysis2.get_json()["data"]["customCharts"]
    assert set(charts2[0]["groups"]) == {"内饰科", "未分组"}
