# -*- coding: utf-8 -*-
"""Offline API and persistence tests for unified deliverable form snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from services.deliverable_form_analysis import build_form_snapshot


def _paa_snapshot(*, snapshot_at: str, source_run_id: int) -> object:
    return build_form_snapshot(
        "aras_paa",
        [
            {
                "_no": "PAA-API-1",
                "_department": "车身开发部",
                "_pe_tdc_smt": "车体工程",
                "_vehicles": "F610S",
                "state": "CLOZ",
                "_requester_phone": "13800138000",
                "_submit_date": "2026-08-30",
            },
            {
                "_no": "PAA-API-2",
                "_department": "动力总成部",
                "_pe_tdc_smt": "动力总成",
                "_vehicles": "F510S",
                "state": "APPRL1",
                "_submit_date": "2026-08-31",
            },
        ],
        snapshot_at=snapshot_at,
        source_run_id=source_run_id,
        source="test archive",
        artifacts=(
            {
                "display_name": "paa.json",
                "relative_path": "aras/paa/paa.json",
                "artifact_type": "normalized_json",
            },
        ),
    )


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    database = DatabaseManager(tmp_path / "form-api.db")
    database.init_database()
    return database


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(
        web_app,
        "DatabaseManager",
        lambda: db_cls(tmp_path / "form-web.db"),
    )
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client(), db_cls(tmp_path / "form-web.db")


def test_database_persists_latest_snapshot_and_bounded_rows(db: DatabaseManager) -> None:
    snapshot = _paa_snapshot(
        snapshot_at="2026-09-01T18:00:00Z",
        source_run_id=2,
    )

    snapshot_id = db.publish_deliverable_form_snapshot(snapshot)
    latest = db.get_latest_deliverable_form_snapshot("aras_paa")
    page = db.list_deliverable_form_rows(
        "aras_paa",
        {"section": "车体工程"},
        offset=0,
        limit=1,
    )

    assert snapshot_id > 0
    assert latest is not None
    assert latest["form_key"] == "aras_paa"
    assert latest["row_count"] == 2
    assert page["total"] == 1
    assert len(page["items"]) == 1
    serialized = json.dumps(latest, ensure_ascii=False)
    assert "13800138000" not in serialized
    assert "form-api.db" not in serialized


def test_daily_trend_keeps_latest_snapshot_when_same_day_has_two_runs(
    db: DatabaseManager,
) -> None:
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T08:00:00Z", source_run_id=1)
    )
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    snapshots = db.list_deliverable_form_snapshots("aras_paa", limit=30)

    assert len(snapshots) == 2
    assert snapshots[0]["snapshot_at"] == "2026-09-01T18:00:00Z"


def test_form_view_endpoint_returns_schema_summary_charts_and_artifacts(
    client,
) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get("/api/deliverable-forms/aras_paa/view")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["formKey"] == "aras_paa"
    assert len(data["schema"]["columns"]) == 113
    assert data["summary"]["total"] == 2
    assert "departmentStatus" in data["charts"]
    assert data["sync"]["jobKey"] == "aras_paa"
    assert "credentialRef" not in json.dumps(data, ensure_ascii=False)
    assert data["artifacts"][0]["display_name"] == "paa.json"
    assert "form-api.db" not in json.dumps(data, ensure_ascii=False)


def test_form_rows_endpoint_accepts_only_allowlisted_filters(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={
            "department": "车身开发部",
            "section": "车体工程",
            "model": "F610S",
            "status": "CLOSE",
            "offset": "0",
            "limit": "1",
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["dimensions"]["model"] == "F610S"

    invalid = http.get(
        "/api/deliverable-forms/aras_paa/rows",
        query_string={"unsupported": "x"},
    )
    assert invalid.status_code == 422


def test_form_view_filters_charts_and_daily_trend_from_same_snapshot_rows(client) -> None:
    http, db = client
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-08-31T18:00:00Z", source_run_id=1)
    )
    db.publish_deliverable_form_snapshot(
        _paa_snapshot(snapshot_at="2026-09-01T18:00:00Z", source_run_id=2)
    )

    response = http.get(
        "/api/deliverable-forms/aras_paa/view",
        query_string={"section": "车体工程", "model": "F610S"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["total"] == 1
    assert data["summary"]["completed"] == 1
    assert data["charts"]["sectionStatus"][0]["label"] == "车体工程"
    assert all(point["total"] == 1 for point in data["charts"]["quantityTrend"])
    assert data["filters"]["applied"] == {
        "section": "车体工程",
        "model": "F610S",
    }


def test_form_view_keeps_thirty_calendar_days_when_runs_are_more_frequent(client) -> None:
    http, db = client
    for day in range(1, 32):
        db.publish_deliverable_form_snapshot(
            _paa_snapshot(
                snapshot_at=f"2026-08-{day:02d}T18:00:00Z",
                source_run_id=day,
            )
        )

    response = http.get("/api/deliverable-forms/aras_paa/view")

    assert response.status_code == 200
    trend = response.get_json()["data"]["charts"]["quantityTrend"]
    assert len(trend) == 30
    assert trend[0]["day"] == "2026-08-02"
    assert trend[-1]["day"] == "2026-08-31"


@pytest.mark.parametrize(
    "form_key",
    ["VPI-T2-D3", "aras_paa", "aras_ncr_progress", "aras_ncr_detail"],
)
def test_form_view_endpoint_accepts_each_allowlisted_key(
    client,
    form_key: str,
) -> None:
    http, _ = client

    response = http.get(f"/api/deliverable-forms/{form_key}/view")

    assert response.status_code == 200
    assert response.get_json()["data"]["formKey"] == form_key


def test_form_view_endpoint_rejects_unknown_key(client) -> None:
    http, _ = client

    response = http.get("/api/deliverable-forms/not-approved/view")

    assert response.status_code == 404
