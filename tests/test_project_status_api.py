# -*- coding: utf-8 -*-
"""Focused contracts for the persisted VPI-T2 project status API."""

from __future__ import annotations

from types import SimpleNamespace

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
    # 看板可见性由能力注册表单一来源下发：D1/D4 不进两块看板，但仍在
    # deliverables 全量字段中出现（详情页/分析接口/审计/统计参与不变）。
    board_flags = {item["id"]: item["boardVisible"] for item in data["deliverables"]}
    assert board_flags["VPI-T2-D1"] is False
    assert board_flags["VPI-T2-D4"] is False
    assert all(
        board_flags[deliverable_id] is True
        for deliverable_id in (
            "VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D5",
            "VPI-T2-D6", "VPI-T2-D7", "VPI-T2-D8",
        )
    )
    # associations 由单一关联注册表反查填充：D3 关联 aras_ewo 任务与
    # aras-ewo 目录条目；D1/D4 未关联项目交付物为空数组。
    by_id = {item["id"]: item for item in data["deliverables"]}
    d3_associations = by_id["VPI-T2-D3"]["associations"]
    assert [entry["type"] for entry in d3_associations] == ["archive_job", "catalog_item"]
    assert d3_associations[0]["jobKey"] == "aras_ewo"
    assert d3_associations[0]["href"] == "#archive-deliverable/aras_ewo"
    assert d3_associations[0]["enabled"] is False
    assert d3_associations[0]["lastSuccessAt"] is None
    # 凭据引用是否已绑定必须随 associations 下发，卡片才能展示真实就绪状态，
    # 而不是声称「支持直接立即同步」却必然失败。
    assert d3_associations[0]["credentialConfigured"] is False
    assert by_id["VPI-T2-D6"]["associations"][0]["credentialConfigured"] is False
    assert by_id["VPI-T2-D7"]["associations"][0]["credentialConfigured"] is False
    assert by_id["VPI-T2-D8"]["associations"][0]["credentialConfigured"] is False
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
        # NCR 交付物下发官方科室代码表（单一来源 NCR_SECTION_CODES）；其它为 null。
        if item["id"] in {"VPI-T2-D7", "VPI-T2-D8"}:
            assert item["sourceInfo"]["ncrSectionCodes"] == [
                "BA", "BE", "BI", "EXT", "INT", "SES", "VE",
            ]
            # 科室预设与看板归集口径同源（默认五科室；用户可在归集规则编辑）。
            assert item["sourceInfo"]["sectionScopePresets"] == [
                "车身科", "车体科", "内饰科", "外饰科", "车体架构集成科",
            ]
        else:
            assert item["sourceInfo"]["ncrSectionCodes"] is None
            assert item["sourceInfo"]["sectionScopePresets"] is None

    assert items["VPI-T2-D2"]["sourceInfo"]["reportType"] == "sor"
    assert items["VPI-T2-D3"]["sourceInfo"]["reportType"] == "ewo"
    assert items["VPI-T2-D5"]["sourceInfo"]["reportType"] == "data_model"

    assert items["VPI-T2-D6"]["sourceInfo"]["archiveJobKey"] == "aras_paa"
    assert items["VPI-T2-D7"]["sourceInfo"]["archiveJobKey"] == "aras_ncr_progress"
    assert items["VPI-T2-D8"]["sourceInfo"]["archiveJobKey"] == "aras_ncr_detail"
    assert items["VPI-T2-D1"]["sourceInfo"]["archiveJobKey"] is None
    assert items["VPI-T2-D4"]["sourceInfo"]["archiveJobKey"] is None
    assert items["VPI-T2-D2"]["sourceInfo"]["archiveJobKey"] == "tdc_sor"
    assert items["VPI-T2-D3"]["sourceInfo"]["archiveJobKey"] == "aras_ewo"
    assert items["VPI-T2-D5"]["sourceInfo"]["archiveJobKey"] == "tdc_data_model"


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


def test_mapping_discovery_rule_fields_whitelists_paa_and_ncr() -> None:
    """PAA (D6), NCR progress (D7), and NCR detail (D8) support mapping discovery whitelist fields."""
    from web.app import _mapping_discovery_query_identity

    # PAA (D6)
    paa_payload = {
        "filters": {
            "department": "技术中心_车体工程",
            "project_model": "F610S",
            "paa_no": "PAA-2026-001",
            "section_code": "SEC-01",
            "ewo_no": "EWO-2026-001",
        },
        "aggregate": True,
    }
    paa_rule, paa_values = _mapping_discovery_query_identity(paa_payload, "VPI-T2-D6")
    assert paa_rule["department"] == "技术中心_车体工程"
    assert paa_rule["projectModel"] == "F610S"
    assert paa_rule["paaNo"] == "PAA-2026-001"
    assert paa_rule["sectionCode"] == "SEC-01"
    assert paa_rule["ewoNo"] == "EWO-2026-001"

    # PAA serial_number alias
    paa_alias_payload = {
        "filters": {
            "serial_number": "PAA-2026-002",
        },
        "aggregate": True,
    }
    paa_alias_rule, _ = _mapping_discovery_query_identity(paa_alias_payload, "VPI-T2-D6")
    assert paa_alias_rule["paaNo"] == "PAA-2026-002"

    # NCR progress (D7)：科室代码（白名单解析，F3 2026-09-26）
    ncr_progress_payload = {
        "filters": {
            "department": "技术中心_车体工程",
            "project_model": "F610S",
            "ncr_no": "NCR-2026-001",
            "section_code": "be, INT",
        },
        "aggregate": True,
    }
    ncr_rule, _ = _mapping_discovery_query_identity(ncr_progress_payload, "VPI-T2-D7")
    assert ncr_rule["department"] == "技术中心_车体工程"
    assert ncr_rule["projectModel"] == "F610S"
    assert ncr_rule["ncrNo"] == "NCR-2026-001"
    assert ncr_rule["sectionCode"] == "be, INT"

    # NCR 科室代码非法输入：fail-closed 422 语义（列合法代码）。
    from web.app import _ArasRequestError

    with pytest.raises(_ArasRequestError, match="合法代码"):
        _mapping_discovery_query_identity(
            {
                "filters": {
                    "project_model": "F610S",
                    "section_code": "结构工程科",
                },
                "aggregate": True,
            },
            "VPI-T2-D7",
        )

    # NCR detail (D8) with serial_number alias
    ncr_detail_payload = {
        "filters": {
            "department": "技术中心_车体工程",
            "project_model": "F610S",
            "serial_number": "NCR-2026-002",
        },
        "aggregate": True,
    }
    ncr_detail_rule, _ = _mapping_discovery_query_identity(ncr_detail_payload, "VPI-T2-D8")
    assert ncr_detail_rule["department"] == "技术中心_车体工程"
    assert ncr_detail_rule["projectModel"] == "F610S"
    assert ncr_detail_rule["ncrNo"] == "NCR-2026-002"


def test_tdc_data_model_mapping_discovery_supports_status_filter() -> None:
    """TDC 数模 (D5) 映射发现支持 status 筛选。"""
    from web.app import _mapping_discovery_query_identity

    payload = {
        "filters": {
            "project_model": "F610S",
            "department": "车体工程",
            "status": "审批中",
        },
        "aggregate": True,
    }
    rule, values = _mapping_discovery_query_identity(payload, "VPI-T2-D5")
    assert rule["projectModel"] == "F610S"
    assert rule["department"] == "车体工程"
    assert rule["status"] == "审批中"
    assert values["status"] == "审批中"


# ===== 映射取证的协作式取消（前端 abort 必须让服务端真的停下来） =====


def test_mapping_discovery_cancel_token_registry_is_bounded() -> None:
    assert web_app._register_discovery_cancel("bad token!") == (None, None)
    assert web_app._register_discovery_cancel(None) == (None, None)
    assert web_app._register_discovery_cancel("x" * 65) == (None, None)

    token, event = web_app._register_discovery_cancel("disc-abc_123-XYZ")
    assert token == "disc-abc_123-XYZ"
    assert event is not None and event.is_set() is False
    with web_app._DISCOVERY_CANCEL_LOCK:
        assert web_app._DISCOVERY_CANCEL_TOKENS[token] is event

    web_app._release_discovery_cancel(token, event)
    with web_app._DISCOVERY_CANCEL_LOCK:
        assert token not in web_app._DISCOVERY_CANCEL_TOKENS
        web_app._DISCOVERY_CANCEL_TOKENS.clear()
    # 登记有上限：异常路径不会无限增长。注意 _register_discovery_cancel 自己会取锁，
    # 不能在持有 _DISCOVERY_CANCEL_LOCK 时调用它，否则自死锁。
    for index in range(web_app._DISCOVERY_CANCEL_MAX_TOKENS + 5):
        web_app._register_discovery_cancel(f"disc-{index}")
    with web_app._DISCOVERY_CANCEL_LOCK:
        assert len(web_app._DISCOVERY_CANCEL_TOKENS) <= web_app._DISCOVERY_CANCEL_MAX_TOKENS
        web_app._DISCOVERY_CANCEL_TOKENS.clear()


def test_mapping_discovery_cancel_endpoint_sets_registered_event(client) -> None:  # type: ignore[no-untyped-def]
    token, event = web_app._register_discovery_cancel("disc-endpoint-1")
    try:
        response = client.post(
            "/api/project-status/deliverables/VPI-T2-D2/mapping-discovery/cancel",
            json={"base_url": "https://tdc.example", "cancelToken": token},
        )
        assert response.status_code == 200
        assert response.get_json()["data"]["cancelled"] is True
        assert event is not None and event.is_set() is True
    finally:
        web_app._release_discovery_cancel(token, event)


def test_mapping_discovery_cancel_endpoint_rejects_unknown_and_invalid(client) -> None:  # type: ignore[no-untyped-def]
    unknown = client.post(
        "/api/project-status/deliverables/VPI-T2-D2/mapping-discovery/cancel",
        json={"base_url": "https://tdc.example", "cancelToken": "disc-never-registered"},
    )
    assert unknown.status_code == 200
    assert unknown.get_json()["data"] == {"cancelled": False, "reason": "not_running"}

    invalid = client.post(
        "/api/project-status/deliverables/VPI-T2-D2/mapping-discovery/cancel",
        json={"base_url": "https://tdc.example", "cancelToken": "bad token!"},
    )
    assert invalid.status_code == 400


# ===== F9a / F10 向导取证去重与独立轻量签名核验 =====


def test_mapping_discovery_rejects_malformed_wizard_session_id(client) -> None:  # type: ignore[no-untyped-def]
    invalid = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={"base_url": "https://tdc.sgmw.com.cn", "wizardSessionId": "bad session id with spaces!"},
    )
    assert invalid.status_code == 422
    assert "wizardSessionId" in invalid.get_json()["error"]["fields"]


def test_mapping_discovery_f9a_session_cache_deduplicates(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    crawl_calls: list[object] = []

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            crawl_calls.append(("crawl", filters))
            return SimpleNamespace(
                rows=[
                    {"incident": "INC-001", "projectModel": "F610S", "department": "车体工程"},
                    {"incident": "INC-002", "projectModel": "F610S", "department": "车体工程"},
                ],
                complete=True,
                stop_reason="reported_pages",
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-test-01",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }

    # 1. 第一次发现：发起真实抓取并写入会话缓存
    resp1 = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1.status_code == 200
    assert len(crawl_calls) == 1

    # 2. 第二次发现（同一会话、相同基础查询）：命中缓存，不发起上游抓取
    resp2 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "selectedExternalKey": "INC-001"},
    )
    assert resp2.status_code == 200
    assert len(crawl_calls) == 1  # 依然是 1，证明未重复调用上游！

    # 3. 换一个会话 ID：缓存隔离，发起新的上游调用
    resp3 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "wizardSessionId": "wiz-sess-test-02"},
    )
    assert resp3.status_code == 200
    assert len(crawl_calls) == 2


def test_mapping_discovery_f10_stability_sampling_verification(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    actions: list[str] = []

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            actions.append("crawl_all")
            return SimpleNamespace(
                rows=[{"incident": "INC-001", "projectModel": "F610S", "department": "车体工程"}],
                complete=True,
                stop_reason="reported_pages",
            )

        def query_data_model_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
            actions.append("query_page")
            return SimpleNamespace(
                rows=[{"incident": "INC-001", "projectModel": "F610S", "department": "车体工程"}],
                total=1,
                page=1,
                page_size=50,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-stability-01",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }

    # 第 1 次：全量取证
    resp1 = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1.status_code == 200
    assert actions == ["crawl_all"]
    assert resp1.get_json()["data"]["stability"]["confirmed"] == 1

    # 第 2 次（F10 轻量签名采样）：只请求单页 query_page，不走全量抓取
    resp2 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "stabilityCheck": True},
    )
    assert resp2.status_code == 200
    assert actions == ["crawl_all", "query_page"]
    data2 = resp2.get_json()["data"]
    assert data2["state"] == "matched"
    assert data2["stability"]["confirmed"] == 2
    assert data2["stability"]["ready"] is True


def test_mapping_discovery_f10_stability_detects_total_mismatch(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                rows=[{"incident": "INC-001", "projectModel": "F610S", "department": "车体工程"}],
                complete=True,
                stop_reason="reported_pages",
            )

        def query_data_model_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
            # 上游在两次请求间总数发生变化（如从 1 变到 2），未保持一致
            return SimpleNamespace(
                rows=[{"incident": "INC-001", "projectModel": "F610S", "department": "车体工程"}],
                total=2,
                page=1,
                page_size=50,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-stability-mismatch",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }

    resp1 = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1.status_code == 200
    assert resp1.get_json()["data"]["stability"]["confirmed"] == 1

    resp2 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "stabilityCheck": True},
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()["data"]
    assert data2["state"] == "key_changed"
    assert data2["stability"]["confirmed"] == 0
    assert data2["stability"]["ready"] is False


def test_mapping_discovery_f10_stability_aggregate_over_one_page(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """回归主用例（TASK-20260929-F10-STABILITY-GATE）：>50 条聚合 + 上游倒序。

    r4 缺陷：第 1 次观测存的是全量按单号排序后的前 5 个单号，第 2 次采样是
    上游页序第 1 页 50 行，两集合不可能互为子集 → 聚合模式必然报"映射稳定性
    未就绪"。修复后基线为全量单号截断哈希集合，采样 ⊆ 基线即通过。
    """
    actions: list[str] = []
    ordered = [
        {"incident": f"INC-{i:04d}", "projectModel": "F610S", "department": "车体工程"}
        for i in range(60)
    ]
    upstream_rows = list(reversed(ordered))  # 上游按时间倒序：页 1 是单号最大的一批

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            actions.append("crawl_all")
            return SimpleNamespace(
                rows=list(upstream_rows),
                total=60,
                complete=True,
                stop_reason="reported_pages",
            )

        def query_data_model_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
            actions.append("query_page")
            return SimpleNamespace(
                rows=upstream_rows[:page_size],
                total=60,
                page=page,
                page_size=page_size,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-stability-60",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }

    resp1 = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1.status_code == 200
    assert resp1.get_json()["data"]["stability"]["confirmed"] == 1

    resp2 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "stabilityCheck": True},
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()["data"]
    assert data2["state"] == "matched"
    assert data2["stability"] == {"confirmed": 2, "required": 2, "ready": True}
    assert data2["mismatch"] is None
    assert actions == ["crawl_all", "query_page"]


def test_mapping_discovery_f10_stability_mismatch_structure_reported(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """采样不一致时响应必须带结构化 mismatch（原因枚举 + 计数），供前端给出具体文案。"""
    ordered = [
        {"incident": f"INC-{i:04d}", "projectModel": "F610S", "department": "车体工程"}
        for i in range(60)
    ]

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                rows=list(ordered),
                total=60,
                complete=True,
                stop_reason="reported_pages",
            )

        def query_data_model_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
            # 上游第 1 页混入一条新记录（把最后一条挤到第 2 页），声明总数不变。
            drifted = [{"incident": "INC-9000", "projectModel": "F610S"}] + ordered[:49]
            return SimpleNamespace(rows=drifted, total=60, page=page, page_size=page_size)

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-stability-drift",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }

    resp1 = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1.status_code == 200

    resp2 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "stabilityCheck": True},
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()["data"]
    assert data2["state"] == "key_changed"
    assert data2["mismatch"] == {
        "reason": "sample_not_in_baseline",
        "expected": 60,
        "actual": 50,
    }


def test_mapping_discovery_f10_stability_cache_hit_keeps_declared_total(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """顾问复核 F2：F9a 缓存命中路径再次落观测时必须沿用首次抓取的声明总数。

    上游存在跨页重复行时，去重后行数（60）< 声明总数（62）；若缓存命中的
    再观测用去重后行数充当 `_upstreamTotal`，采样端的声明总数就会与之假性
    失配，向导永远无法就绪。
    """
    actions: list[str] = []
    ordered = [
        {"incident": f"INC-{i:04d}", "projectModel": "F610S", "department": "车体工程"}
        for i in range(60)
    ]

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            actions.append("crawl_all")
            # 模拟爬虫跨页去重后剩 60 行，但上游声明总数是 62。
            return SimpleNamespace(
                rows=list(ordered), total=62, complete=True, stop_reason="reported_pages"
            )

        def query_data_model_page(self, filters, page=1, page_size=50):  # type: ignore[no-untyped-def]
            actions.append("query_page")
            return SimpleNamespace(
                rows=ordered[:page_size], total=62, page=page, page_size=page_size
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-stability-cache-total",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }

    resp1 = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1.status_code == 200
    assert resp1.get_json()["data"]["stability"]["confirmed"] == 1

    # 同会话同参数的再次取证（缓存命中路径）：不得重复抓取，且基线总数保持 62。
    resp1b = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload)
    assert resp1b.status_code == 200
    assert actions == ["crawl_all"]

    resp2 = client.post(
        "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
        json={**payload, "stabilityCheck": True},
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()["data"]
    assert data2["state"] == "matched"
    assert data2["stability"] == {"confirmed": 2, "required": 2, "ready": True}
    assert data2["mismatch"] is None
    assert actions == ["crawl_all", "query_page"]


# ===== G5 映射取证后台化：202 契约 / 参数哈希绑定 / 单在途 / 协作取消 =====


def _wait_unified_task(client, task_id: str, timeout_s: float = 5.0) -> dict:  # type: ignore[no-untyped-def]
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        if data.get("is_active") is False:
            return data
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not settle within {timeout_s}s")


def test_mapping_discovery_async_202_contract_and_isomorphic_result(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """统一域会话在位时全量取证转后台任务：202 受理 → 轮询 succeeded →
    结果与同步响应同构且携带同一参数哈希（G5 参数绑定）。"""
    crawl_calls: list[object] = []

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            crawl_calls.append(("crawl", filters))
            return SimpleNamespace(
                rows=[{"incident": "INC-001", "projectModel": "F610S", "department": "车体工程"}],
                complete=True,
                stop_reason="reported_pages",
                total=1,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-01",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp.status_code == 202
        data = resp.get_json()["data"]
        assert data["taskId"]
        assert data["status"] in {"queued", "running"}
        assert data["statusUrl"] == f"/api/tasks/{data['taskId']}"
        assert data["resultUrl"] == f"/api/tasks/{data['taskId']}/result"
        assert len(data["paramsHash"]) == 16

        task = _wait_unified_task(client, data["taskId"])
        assert task["status"] == "succeeded"
        assert len(crawl_calls) == 1

        result_resp = client.get(f"/api/tasks/{data['taskId']}/result")
        assert result_resp.status_code == 200
        result_data = result_resp.get_json()["data"]
        assert result_data["paramsHash"] == data["paramsHash"]
        assert isinstance(result_data["result"], dict)
    finally:
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_async_same_params_reattach_and_conflict(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """单在途契约：同参数重复提交返回原任务（重挂）；不同参数在途时 409 显式拒绝。"""
    import threading

    release = threading.Event()
    started = threading.Event()

    class BlockingTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            started.set()
            if not release.wait(timeout=5.0):
                raise AssertionError("test event not released")
            return SimpleNamespace(
                rows=[{"incident": "INC-001"}], complete=True,
                stop_reason="reported_pages", total=1,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: BlockingTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-02",
        "filters": {"project_model": "F610S", "department": "车体工程"},
        "aggregate": True,
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp1 = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp1.status_code == 202
        task_id = resp1.get_json()["data"]["taskId"]
        assert started.wait(2.0)

        resp2 = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp2.status_code == 202
        assert resp2.get_json()["data"]["taskId"] == task_id

        resp3 = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
            json={**payload, "aggregate": False},
        )
        assert resp3.status_code == 409
        assert resp3.get_json()["error"]["type"] == "DiscoveryInProgress"

        release.set()
        task = _wait_unified_task(client, task_id)
        assert task["status"] == "succeeded"
    finally:
        release.set()
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_async_cooperative_cancel(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """后台取证任务可经任务中心协作取消：TDC 分页边界停止，结果丢弃。"""
    import threading
    import time as _time

    from services.tdc_crawler import CrawlCancelled

    started = threading.Event()

    class SlowTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            started.set()
            for _ in range(500):
                if should_stop is not None and should_stop():
                    raise CrawlCancelled("cancelled at page boundary")
                _time.sleep(0.02)
            return SimpleNamespace(rows=[], complete=True, stop_reason="reported_pages", total=0)

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: SlowTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-03",
        "filters": {"project_model": "F610S"},
        "aggregate": True,
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp.status_code == 202
        task_id = resp.get_json()["data"]["taskId"]
        assert started.wait(2.0)

        cancel = client.post(f"/api/tasks/{task_id}/cancel", json={})
        assert cancel.status_code == 200

        task = _wait_unified_task(client, task_id)
        assert task["status"] == "cancelled"

        result_resp = client.get(f"/api/tasks/{task_id}/result")
        assert result_resp.status_code == 409
    finally:
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_password_mode_stays_sync(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """凭据红线：密码模式不进后台任务（凭据禁止入库），回落同步路径且行为不变。"""
    calls: list[object] = []

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            calls.append(("crawl", filters))
            return SimpleNamespace(
                rows=[{"incident": "INC-001"}], complete=True,
                stop_reason="reported_pages", total=1,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-04",
        "filters": {"project_model": "F610S"},
        "aggregate": True,
        "auth_mode": "password",
        "username": "u",
        "password": "p",
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert len(calls) == 1
        assert "VPI-T2-D5" not in web_app._MAPPING_DISCOVERY_TASKS
    finally:
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_cancel_endpoint_cancels_background_task(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """顾问复审 F1/F2：后台任务在途时，前端 abort 经 cancel 端点按交付物兜底
    协作取消；且 worker 退出前注册键不释放（换参提交仍 409，不产生双 worker）。"""
    import threading

    release = threading.Event()
    started = threading.Event()

    class BlockingTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            started.set()
            # 阻塞直到测试放行：cancel 后 worker 仍未退出（模拟不可中断导出）。
            if not release.wait(timeout=5.0):
                raise AssertionError("test event not released")
            return SimpleNamespace(
                rows=[{"incident": "INC-001"}], complete=True,
                stop_reason="reported_pages", total=1,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: BlockingTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-05",
        "filters": {"project_model": "F610S"},
        "aggregate": True,
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp.status_code == 202
        task_id = resp.get_json()["data"]["taskId"]
        assert started.wait(2.0)

        # 旧令牌已随 202 释放：取消走注册表兜底（F1）。
        cancel = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery/cancel",
            json={"base_url": "https://tdc.example", "cancelToken": "disc-legacy-unregistered"},
        )
        assert cancel.status_code == 200
        cancel_data = cancel.get_json()["data"]
        assert cancel_data["cancelled"] is True
        assert cancel_data["taskId"] == task_id

        # worker 仍在运行：注册键未释放，换参提交必须仍 409（F2）。
        conflict = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery",
            json={**payload, "aggregate": False},
        )
        assert conflict.status_code == 409

        release.set()
        task = _wait_unified_task(client, task_id)
        assert task["status"] == "cancelled"

        # worker 退出后注册键已释放：可重新提交。
        resp2 = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp2.status_code == 202
        _wait_unified_task(client, resp2.get_json()["data"]["taskId"])
    finally:
        release.set()
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_cookie_mode_stays_sync(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """G5（顾问复审 F1 配套）：显式 Cookie 模式不进后台任务，回落同步（凭据红线）。"""
    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                rows=[{"incident": "INC-001"}], complete=True,
                stop_reason="reported_pages", total=1,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-06",
        "filters": {"project_model": "F610S"},
        "aggregate": True,
        # 显式携带敏感字段提交：它们只允许留在请求闭包内，绝不落盘。
        "auth_mode": "browser",
        "cookie": "<COOKIE_PLACEHOLDER>",
        "headers": {"X-Demo": "<HEADER_PLACEHOLDER>"},
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        # cookie 属显式 Cookie 模式 → 不进后台任务，回落同步（200）。
        assert resp.status_code == 200
    finally:
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_async_artifact_redline_on_async_path(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """G5（顾问复审 F11）：统一域会话异步路径的落盘 artifact 只含 result 与 paramsHash。"""
    import json as _json

    class FakeTDCClient:
        def crawl_data_model_all(self, filters, max_records=5000, should_stop=None):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                rows=[{"incident": "INC-001"}], complete=True,
                stop_reason="reported_pages", total=1,
            )

    monkeypatch.setattr(web_app, "_build_tdc_client_from_payload", lambda p, hosts: FakeTDCClient())
    monkeypatch.setattr(web_app, "_shared_domain_session", lambda system: object())
    payload = {
        "base_url": "https://tdc.sgmw.com.cn",
        "wizardSessionId": "wiz-sess-async-07",
        "filters": {"project_model": "F610S"},
        "aggregate": True,
    }
    web_app._MAPPING_DISCOVERY_TASKS.clear()
    try:
        resp = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json=payload
        )
        assert resp.status_code == 202
        task_id = resp.get_json()["data"]["taskId"]
        task = _wait_unified_task(client, task_id)
        assert task["status"] == "succeeded"
        runner = client.application.extensions["crawl_task_runner"]
        artifact_file = runner.downloads_dir / f"{task_id}.result.json"
        artifact_payload = _json.loads(artifact_file.read_text(encoding="utf-8"))
        assert set(artifact_payload.keys()) == {"result", "paramsHash"}
        artifact_text = artifact_file.read_text(encoding="utf-8").lower()
        for forbidden in ("cookie", "authorization", "password", "set-token", "bearer"):
            assert forbidden not in artifact_text
    finally:
        web_app._MAPPING_DISCOVERY_TASKS.clear()


def test_mapping_discovery_cancel_endpoint_does_not_require_base_url(client) -> None:  # type: ignore[no-untyped-def]
    """The page's abort handler sends only the cancel token (nothing is queried upstream)."""
    token, event = web_app._register_discovery_cancel("disc-no-base-url")
    try:
        response = client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery/cancel",
            json={"cancelToken": token},
        )
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["data"]["cancelled"] is True
        assert event is not None and event.is_set() is True
        assert client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery/cancel", json={"cancelToken": "bad token!"},
        ).status_code == 400
        assert client.post(
            "/api/project-status/deliverables/VPI-T2-D5/mapping-discovery/cancel", data="not json",
        ).status_code == 400
    finally:
        web_app._release_discovery_cancel(token, event)
