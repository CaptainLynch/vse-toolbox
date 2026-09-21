# -*- coding: utf-8 -*-
"""Focused contracts for the persisted VPI-T2 project status API."""

from __future__ import annotations

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager

MILESTONE_TEMPLATE_NAMES = (
    "VPI",
    "内饰模型评审",
    "外饰模型评审",
    "LLP VDR",
    "100% VDR",
    "LLP T2",
    "100% T2",
    "OTS",
    "验证阀",
    "内部体验阀",
    "用户体验阀",
)

LEGACY_SEED_ROWS = (
    ("项目启动", "2026-04-08", "已完成", "done", 1),
    ("策略冻结", "2026-05-12", "已完成", "done", 2),
    ("定点流程发布", "2026-06-18", "已完成", "done", 3),
    ("设计冻结", "2026-07-15", "已完成", "done", 4),
    ("VDR 决策", "2026-08-15", "进行中", "current", 5),
    ("VPI-T2 Gate", "2026-08-30", "未开始", "planned", 6),
)


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "project-status.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _status(client):  # type: ignore[no-untyped-def]
    response = client.get("/api/project-status?phase=VPI-T2")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    return body["data"]


def test_project_status_read_contract_and_overview_compatibility(client) -> None:  # type: ignore[no-untyped-def]
    data = _status(client)
    assert data["phase"]["id"] == "VPI-T2"
    assert data["phase"]["overallProgress"] == 64
    # 契约内交付物（D2/D3/D5）新库默认自动同步但未同步 → 待同步；
    # D1（手工演示值）计入完成数，D4（手工模式，占位值）计入数值态。
    assert data["phase"]["completedCount"] == 1
    # 外部快照驱动交付物（D6-D8，countsTowardCompletion=False）不进入
    # 价值态汇总：pendingCount 分母仍为 D1-D5 的待同步/待配置 3 项。
    assert data["phase"]["pendingCount"] == 3
    assert data["phase"]["totalCount"] == 8
    assert len(data["milestones"]) == 11
    assert [item["name"] for item in data["milestones"]] == list(MILESTONE_TEMPLATE_NAMES)
    assert all(item["date"] is None for item in data["milestones"])
    assert all(item["status"] == "未开始" for item in data["milestones"])
    assert all(item["type"] == "planned" for item in data["milestones"])
    assert [item["sortOrder"] for item in data["milestones"]] == list(range(1, 12))
    assert len(data["deliverables"]) == 8
    # associations 由单一关联注册表反查填充：D3 关联 aras_ewo 任务与
    # aras-ewo 目录条目；D1/D4 未关联项目交付物为空数组。
    by_id = {item["id"]: item for item in data["deliverables"]}
    d3_associations = by_id["VPI-T2-D3"]["associations"]
    assert [entry["type"] for entry in d3_associations] == ["archive_job", "catalog_item"]
    assert d3_associations[0]["jobKey"] == "aras_ewo"
    assert d3_associations[0]["href"] == "#archive-deliverable/aras_ewo"
    assert d3_associations[0]["enabled"] is False
    assert d3_associations[0]["lastSuccessAt"] is None
    assert d3_associations[1]["catalogId"] == "aras-ewo"
    assert d3_associations[1]["href"] == "#deliverables"
    assert by_id["VPI-T2-D1"]["associations"] == []
    assert by_id["VPI-T2-D4"]["associations"] == []
    # D2/D5 关联各自的 TDC 归档任务。
    assert by_id["VPI-T2-D2"]["associations"][0]["jobKey"] == "tdc_sor"
    assert by_id["VPI-T2-D5"]["associations"][0]["jobKey"] == "tdc_data_model"

    form_links = {item["id"]: item["formLink"] for item in data["deliverables"]}
    assert form_links["VPI-T2-D1"] is None
    assert form_links["VPI-T2-D4"] is None
    assert form_links["VPI-T2-D2"]["formKey"] == "tdc_sor"
    assert form_links["VPI-T2-D2"]["summary"] is None
    assert form_links["VPI-T2-D3"]["formKey"] == "VPI-T2-D3"
    assert form_links["VPI-T2-D3"]["summary"] is None
    assert form_links["VPI-T2-D3"]["snapshotAt"] is None
    assert form_links["VPI-T2-D5"]["formKey"] == "tdc_data_model"
    # D6-D8（外部快照驱动）：formLink 经注册表派生存在，无快照时 summary 为 None。
    assert form_links["VPI-T2-D6"]["formKey"] == "aras_paa"
    assert form_links["VPI-T2-D6"]["summary"] is None
    assert form_links["VPI-T2-D7"]["formKey"] == "aras_ncr_progress"
    assert form_links["VPI-T2-D8"]["formKey"] == "aras_ncr_detail"

    # D6-D8：planned_date NULL → plannedDate/scheduleState/scheduleDays 均为
    # null；payload 下发 formSnapshotDriven/countsTowardCompletion 标志；
    # 手工编辑被拒并给出固定 readOnlyReason；展示状态机输出待同步。
    for deliverable_id, expected_job in (
        ("VPI-T2-D6", "aras_paa"),
        ("VPI-T2-D7", "aras_ncr_progress"),
        ("VPI-T2-D8", "aras_ncr_detail"),
    ):
        item = by_id[deliverable_id]
        assert item["plannedDate"] is None
        assert item["scheduleState"] is None
        assert item["scheduleDays"] is None
        assert item["formSnapshotDriven"] is True
        assert item["countsTowardCompletion"] is False
        assert item["manualEditable"] is False
        assert item["readOnlyReason"] == "外部快照驱动，状态由归档快照自动映射"
        assert item["syncDisplay"]["state"] == "pending_first_sync"
        assert item["syncDisplay"]["label"] == "待同步"
        assert item["syncDisplay"]["displayStatus"] is None
        assert item["syncDisplay"]["displayProgress"] is None
        assert item["syncDisplay"]["displaySummary"] is None
        associations = item["associations"]
        assert associations[0]["type"] == "archive_job"
        assert associations[0]["jobKey"] == expected_job
        assert associations[1]["type"] == "catalog_item"

    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert set(overview.get_json()) == {"projects", "deliverables", "feishu"}


def test_project_status_payload_includes_latest_analysis_link(client) -> None:
    """概览 payload 为每个交付物附带最新明细分析快照摘要（analysisLink）；
    无快照时为 None，发布快照后与明细页分析摘要同源。"""
    data = _status(client)
    links = {item["id"]: item["analysisLink"] for item in data["deliverables"]}
    assert links["VPI-T2-D1"] is None
    assert links["VPI-T2-D3"] is None

    db = client.application.extensions["deliverable_analysis"].db
    snapshot = {
        "total_count": 4,
        "completed_count": 3,
        "incomplete_count": 1,
        "overdue_count": 1,
        "due_soon_count": 0,
        "missing_due_date_count": 0,
        "department_counts": {"车身科": {"total": 4, "completed": 3, "incomplete": 1}},
        "snapshot_at": "2026-09-12T08:00:00.000Z",
    }
    db.replace_project_status_analysis_cache("VPI-T2-D2", 21, snapshot, [])

    reloaded = _status(client)
    link = next(
        item["analysisLink"]
        for item in reloaded["deliverables"]
        if item["id"] == "VPI-T2-D2"
    )
    assert link == {
        "snapshotAt": "2026-09-12T08:00:00.000Z",
        "summary": {
            "total": 4,
            "completed": 3,
            "incomplete": 1,
            "overdue": 1,
        },
    }
    # 未发布快照的交付物保持 None。
    assert next(
        item["analysisLink"]
        for item in reloaded["deliverables"]
        if item["id"] == "VPI-T2-D1"
    ) is None


def test_project_status_update_persists_and_returns_shared_saved_state(client) -> None:  # type: ignore[no-untyped-def]
    before = _status(client)
    item = before["deliverables"][2]
    response = client.patch(
        f'/api/project-status/deliverables/{item["id"]}',
        json={
            "status": "进行中",
            "owner": "李珊（项目）",
            "plannedDate": "2026-08-23",
            "actualDate": None,
            "progress": 75,
            "note": "按更新后的计划推进",
            "updatedAt": item["updatedAt"],
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["data"]["deliverable"]["progress"] == 75
    assert body["data"]["projectStatus"]["deliverables"][2]["owner"] == "李珊（项目）"

    reloaded = _status(client)
    saved = next(row for row in reloaded["deliverables"] if row["id"] == item["id"])
    assert saved["plannedDate"] == "2026-08-23"
    assert saved["note"] == "按更新后的计划推进"


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"owner": ""}, "owner"),
        ({"progress": 101}, "progress"),
        ({"plannedDate": "not-a-date"}, "plannedDate"),
        ({"status": "已完成", "progress": 90, "actualDate": None}, "progress"),
        ({"status": "进行中", "actualDate": "2026-08-13"}, "actualDate"),
    ],
)
def test_project_status_update_rejects_invalid_fields(client, changes, field) -> None:  # type: ignore[no-untyped-def]
    item = _status(client)["deliverables"][2]
    payload = {
        "status": item["status"],
        "owner": item["owner"],
        "plannedDate": item["plannedDate"],
        "actualDate": item["actualDate"],
        "progress": item["progress"],
        "note": item["note"],
        "updatedAt": item["updatedAt"],
    }
    payload.update(changes)
    response = client.patch(f'/api/project-status/deliverables/{item["id"]}', json=payload)
    assert response.status_code == 422
    assert field in response.get_json()["error"]["fields"]


def test_project_status_update_detects_stale_record(client) -> None:  # type: ignore[no-untyped-def]
    item = _status(client)["deliverables"][2]
    payload = {
        "status": item["status"],
        "owner": item["owner"],
        "plannedDate": item["plannedDate"],
        "actualDate": item["actualDate"],
        "progress": 74,
        "note": item["note"],
        "updatedAt": item["updatedAt"],
    }
    first = client.patch(f'/api/project-status/deliverables/{item["id"]}', json=payload)
    assert first.status_code == 200
    stale = client.patch(f'/api/project-status/deliverables/{item["id"]}', json=payload)
    assert stale.status_code == 409
    assert stale.get_json()["error"]["type"] == "Conflict"


def test_unknown_project_status_phase_and_record_are_not_found(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/project-status?phase=OTS-S").status_code == 404
    response = client.patch(
        "/api/project-status/deliverables/missing",
        json={"updatedAt": "2026-08-13 09:42:00.000"},
    )
    assert response.status_code == 404


def test_milestone_update_adds_reorders_and_deletes_baseline_nodes(client) -> None:  # type: ignore[no-untyped-def]
    before = _status(client)
    kept = before["milestones"][1:]
    payload = {
        "updatedAt": before["phase"]["updatedAt"],
        "milestones": [
            {
                "id": None,
                "name": "新增评审节点",
                "date": "2026-08-05",
                "status": "计划节点",
                "type": "planned",
                "sortOrder": 1,
            },
            *[
                {**item, "sortOrder": index}
                for index, item in enumerate(kept, start=2)
            ],
        ],
    }
    response = client.patch("/api/project-status/phases/VPI-T2/milestones", json=payload)
    assert response.status_code == 200
    data = response.get_json()["data"]["projectStatus"]
    assert data["milestones"][0]["name"] == "新增评审节点"
    assert data["milestones"][0]["date"] == "2026-08-05"
    assert len(data["milestones"]) == 11

    persisted = _status(client)
    assert [item["name"] for item in persisted["milestones"]] == [
        item["name"] for item in data["milestones"]
    ]

    # 删除尾节点并确认持久化。
    before_delete = _status(client)
    remaining = before_delete["milestones"][:-1]
    delete_payload = {
        "updatedAt": before_delete["phase"]["updatedAt"],
        "milestones": [
            {**item, "sortOrder": index}
            for index, item in enumerate(remaining, start=1)
        ],
    }
    delete_response = client.patch(
        "/api/project-status/phases/VPI-T2/milestones", json=delete_payload
    )
    assert delete_response.status_code == 200
    after = _status(client)
    assert "用户体验阀" not in {item["name"] for item in after["milestones"]}
    assert len(after["milestones"]) == 10


@pytest.mark.parametrize(
    ("mutator", "field"),
    [
        (lambda items: [{**item, "name": items[0]["name"]} if index == 1 else item for index, item in enumerate(items)], "milestones.1.name"),
        (lambda items: [{**item, "date": "2026-09-01"} if index == 0 else item for index, item in enumerate(items)], "milestones.0.date"),
        (
            lambda items: [
                {**item, "status": "进行中", "date": ""} if index == 0 else item
                for index, item in enumerate(items)
            ],
            "milestones.0.date",
        ),
    ],
)
def test_milestone_update_rejects_invalid_plan(client, mutator, field) -> None:  # type: ignore[no-untyped-def]
    before = _status(client)
    response = client.patch(
        "/api/project-status/phases/VPI-T2/milestones",
        json={
            "updatedAt": before["phase"]["updatedAt"],
            "milestones": mutator(before["milestones"]),
        },
    )
    assert response.status_code == 422
    assert field in response.get_json()["error"]["fields"]
    assert len(_status(client)["milestones"]) == 11


def test_milestone_update_accepts_undated_planned_node(client) -> None:  # type: ignore[no-untyped-def]
    """空日期=待排期：未开始节点允许不带日期保存。"""
    before = _status(client)
    items = [{**item, "date": ""} for item in before["milestones"]]
    response = client.patch(
        "/api/project-status/phases/VPI-T2/milestones",
        json={
            "updatedAt": before["phase"]["updatedAt"],
            "milestones": items,
        },
    )
    assert response.status_code == 200
    data = response.get_json()["data"]["projectStatus"]
    assert all(item["date"] is None for item in data["milestones"])
    assert len(_status(client)["milestones"]) == 11


def test_seed_repairs_untouched_legacy_milestones(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """与旧 6 节点种子逐字段一致的项目在再次初始化时替换为默认模板。"""
    db = DatabaseManager(tmp_path / "legacy-repair.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM project_status_milestones WHERE phase_id = 'VPI-T2'")
        conn.executemany(
            """
            INSERT INTO project_status_milestones
                (phase_id, name, milestone_date, status, type, sort_order)
            VALUES ('VPI-T2', ?, ?, ?, ?, ?)
            """,
            [(*row,) for row in LEGACY_SEED_ROWS],
        )
    db.init_database()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT name, milestone_date FROM project_status_milestones "
            "WHERE phase_id = 'VPI-T2' ORDER BY sort_order, id"
        ).fetchall()
    assert [row["name"] for row in rows] == list(MILESTONE_TEMPLATE_NAMES)
    assert all(row["milestone_date"] is None for row in rows)


def test_seed_preserves_user_edited_milestones(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """用户编辑过的里程碑（即使节点名与旧种子相同）不会被模板覆盖。"""
    db = DatabaseManager(tmp_path / "edited-keep.db")
    db.init_database()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM project_status_milestones WHERE phase_id = 'VPI-T2'")
        conn.executemany(
            """
            INSERT INTO project_status_milestones
                (phase_id, name, milestone_date, status, type, sort_order)
            VALUES ('VPI-T2', ?, ?, ?, ?, ?)
            """,
            [
                (name, "2026-05-13" if name == "策略冻结" else legacy_date, status, kind, order)
                for name, legacy_date, status, kind, order in LEGACY_SEED_ROWS
            ],
        )
    db.init_database()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT name, milestone_date FROM project_status_milestones "
            "WHERE phase_id = 'VPI-T2' ORDER BY sort_order, id"
        ).fetchall()
    assert [row["name"] for row in rows] == [row[0] for row in LEGACY_SEED_ROWS]
    kept = next(row for row in rows if row["name"] == "策略冻结")
    assert kept["milestone_date"] == "2026-05-13"


def test_milestone_update_detects_stale_phase_version(client) -> None:  # type: ignore[no-untyped-def]
    before = _status(client)
    payload = {
        "updatedAt": before["phase"]["updatedAt"],
        "milestones": before["milestones"],
    }
    first = client.patch("/api/project-status/phases/VPI-T2/milestones", json=payload)
    assert first.status_code == 200
    stale = client.patch("/api/project-status/phases/VPI-T2/milestones", json=payload)
    assert stale.status_code == 409
    assert stale.get_json()["error"]["type"] == "Conflict"


def test_milestone_update_empty_list_restores_default_template(client) -> None:
    """删除全部节点后保存：自动恢复 11 节点默认模板而非 422。"""
    before = _status(client)
    response = client.patch(
        "/api/project-status/phases/VPI-T2/milestones",
        json={
            "updatedAt": before["phase"]["updatedAt"],
            "milestones": [],
        },
    )
    assert response.status_code == 200
    data = response.get_json()["data"]["projectStatus"]
    assert [item["name"] for item in data["milestones"]] == list(MILESTONE_TEMPLATE_NAMES)
    assert all(item["date"] is None for item in data["milestones"])
    assert all(item["status"] == "未开始" for item in data["milestones"])
    assert [item["sortOrder"] for item in data["milestones"]] == list(range(1, 12))

    persisted = _status(client)
    assert [item["name"] for item in persisted["milestones"]] == list(MILESTONE_TEMPLATE_NAMES)


def test_project_status_payload_exposes_sync_display_and_capabilities(client) -> None:
    """新库种子：契约内交付物默认 automatic（待配置），payload 下发展示
    状态与来源能力；updateMethod 为 binding.mode 的兼容投影。"""
    data = _status(client)
    items = {item["id"]: item for item in data["deliverables"]}

    for deliverable_id in ("VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D5"):
        item = items[deliverable_id]
        assert item["syncDisplay"]["state"] == "pending_config"
        assert item["updateMethod"] == "automatic"
        assert item["sourceInfo"]["syncCapable"] is True
        assert item["sourceInfo"]["matchFields"]
        assert item["sourceInfo"]["evidenceFields"]

    for deliverable_id in ("VPI-T2-D1", "VPI-T2-D4"):
        item = items[deliverable_id]
        assert item["syncDisplay"]["state"] == "manual"
        assert item["updateMethod"] == "manual"
        assert item["sourceInfo"]["syncCapable"] is False
        assert item["sourceInfo"]["syncNote"]

    assert items["VPI-T2-D2"]["sourceInfo"]["reportType"] == "sor"
    assert items["VPI-T2-D3"]["sourceInfo"]["reportType"] == "ewo"
    assert items["VPI-T2-D5"]["sourceInfo"]["reportType"] == "data_model"


def test_form_snapshot_driven_deliverables_excluded_from_completion_counts(client) -> None:  # type: ignore[no-untyped-def]
    """D6（外部快照驱动）即使快照全部完成也不进入完成统计分母：
    completedCount 仍为 1，环图展示为快照态。"""
    from services.deliverable_form_analysis import build_form_snapshot

    data = _status(client)
    assert data["phase"]["completedCount"] == 1
    assert data["phase"]["pendingCount"] == 3

    db = client.application.extensions["deliverable_analysis"].db
    snapshot = build_form_snapshot(
        "aras_paa",
        [
            {"_no": "PAA-CNT-1", "state": "CLOZ", "_submit_date": "2026-08-01"},
            {"_no": "PAA-CNT-2", "state": "CLOZ", "_submit_date": "2026-08-02"},
        ],
        snapshot_at="2026-09-01T08:00:00Z",
        source_run_id=1,
        source="test archive",
    )
    assert db.publish_deliverable_form_snapshot(snapshot) > 0

    data = _status(client)
    d6 = next(item for item in data["deliverables"] if item["id"] == "VPI-T2-D6")
    # 展示状态机进入快照态并展示数值。
    assert d6["syncDisplay"]["state"] == "snapshot"
    assert d6["syncDisplay"]["displayStatus"] == "已完成"
    assert d6["syncDisplay"]["displayProgress"] == 100
    # 但价值态汇总分母排除：完成数不增加、待同步数不减少。
    assert data["phase"]["completedCount"] == 1
    assert data["phase"]["pendingCount"] == 3
    assert data["phase"]["totalCount"] == 8


def test_project_status_manual_update_rejected_for_form_snapshot_driven(client) -> None:  # type: ignore[no-untyped-def]
    """D6-D8 手工 PATCH 被写入门控拒绝（MappedDeliverableReadOnly）。"""
    data = _status(client)
    d6 = next(item for item in data["deliverables"] if item["id"] == "VPI-T2-D6")
    response = client.patch(
        "/api/project-status/deliverables/VPI-T2-D6",
        json={
            "status": "已完成",
            "progress": 100,
            "note": "x",
            "owner": "y",
            "plannedDate": "2026-09-30",
            "actualDate": "2026-09-29",
            "updatedAt": d6["updatedAt"],
        },
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"]["type"] == "MappedDeliverableReadOnly"
    assert "外部快照驱动" in body["error"]["message"]
