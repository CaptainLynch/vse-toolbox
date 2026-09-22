# -*- coding: utf-8 -*-
"""Focused contracts for the project status scheduler API."""

from __future__ import annotations

import pytest

import web.app as web_app
from services.project_status_scheduler import (
    ProjectStatusSyncScheduler,
    set_global_scheduler,
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "project-status.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_scheduler_status_endpoint_default(client):
    set_global_scheduler(None)
    res = client.get("/api/project-status/scheduler")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert "running" in data
    assert "paused" in data
    assert "intervalSeconds" in data
    assert "eligibleCount" in data


def test_scheduler_status_and_config_with_scheduler(client):
    class FakeRunner:
        def __init__(self):
            self.calls = []

        def run_once(self, **kwargs):
            self.calls.append(kwargs)
            return None

    class FakeDb:
        def list_eligible_sync_bindings(self, deliverable_id=None):
            return [{"deliverable_id": "VPI-T2-D3"}]

    runner = FakeRunner()
    scheduler = ProjectStatusSyncScheduler(FakeDb(), runner, interval=600)
    set_global_scheduler(scheduler)

    try:
        # GET status
        res = client.get("/api/project-status/scheduler")
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["running"] is True
        assert data["paused"] is False
        assert data["intervalSeconds"] == 600

        # POST config: update interval and pause
        res = client.post("/api/project-status/scheduler/config", json={"intervalSeconds": 300, "paused": True})
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["intervalSeconds"] == 300
        assert data["paused"] is True
        assert scheduler.interval == 300
        assert scheduler.is_paused is True

        # POST config: resume
        res = client.post("/api/project-status/scheduler/config", json={"paused": False})
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["paused"] is False
        assert scheduler.is_paused is False

        # POST config validation
        res = client.post("/api/project-status/scheduler/config", json={"intervalSeconds": -10})
        assert res.status_code == 400

        # POST sync-all
        res = client.post("/api/project-status/scheduler/sync-all")
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert "results" in data
        assert len(data["results"]) == 1
    finally:
        set_global_scheduler(None)
