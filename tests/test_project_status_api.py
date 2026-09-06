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
    assert data["phase"]["completedCount"] == 2
    assert len(data["milestones"]) == 11
    assert [item["name"] for item in data["milestones"]] == list(MILESTONE_TEMPLATE_NAMES)
    assert all(item["date"] is None for item in data["milestones"])
    assert all(item["status"] == "未开始" for item in data["milestones"])
    assert all(item["type"] == "planned" for item in data["milestones"])
    assert [item["sortOrder"] for item in data["milestones"]] == list(range(1, 12))
    assert len(data["deliverables"]) == 5
    assert data["deliverables"][0]["associations"] == []

    form_links = {item["id"]: item["formLink"] for item in data["deliverables"]}
    assert form_links["VPI-T2-D1"] is None
    assert form_links["VPI-T2-D4"] is None
    assert form_links["VPI-T2-D2"]["formKey"] == "tdc_sor"
    assert form_links["VPI-T2-D2"]["summary"] is None
    assert form_links["VPI-T2-D3"]["formKey"] == "VPI-T2-D3"
    assert form_links["VPI-T2-D3"]["summary"] is None
    assert form_links["VPI-T2-D3"]["snapshotAt"] is None
    assert form_links["VPI-T2-D5"]["formKey"] == "tdc_data_model"

    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert set(overview.get_json()) == {"projects", "deliverables", "feishu"}


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
        (lambda items: [], "milestones"),
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
