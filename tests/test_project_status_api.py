# -*- coding: utf-8 -*-
"""Focused contracts for the persisted VPI-T2 project status API."""

from __future__ import annotations

import pytest

import web.app as web_app


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
    assert len(data["milestones"]) == 6
    assert len(data["deliverables"]) == 5
    assert data["deliverables"][0]["associations"] == []

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
                "date": "2026-08-30",
                "status": "计划节点",
                "type": "planned",
                "sortOrder": 1,
            },
            *[
                {**item, "sortOrder": index}
                for index, item in enumerate(reversed(kept), start=2)
            ],
        ],
    }
    response = client.patch("/api/project-status/phases/VPI-T2/milestones", json=payload)
    assert response.status_code == 200
    data = response.get_json()["data"]["projectStatus"]
    assert data["milestones"][0]["name"] == "新增评审节点"
    assert "项目启动" not in {item["name"] for item in data["milestones"]}
    assert data["milestones"][0]["date"] == data["milestones"][1]["date"]

    persisted = _status(client)
    assert [item["name"] for item in persisted["milestones"]] == [
        item["name"] for item in data["milestones"]
    ]


@pytest.mark.parametrize(
    ("mutator", "field"),
    [
        (lambda items: [], "milestones"),
        (lambda items: [{**item, "name": items[0]["name"]} if index == 1 else item for index, item in enumerate(items)], "milestones.1.name"),
        (lambda items: [{**item, "date": "2026-09-01"} if index == 0 else item for index, item in enumerate(items)], "milestones.0.date"),
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
    assert len(_status(client)["milestones"]) == 6


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
