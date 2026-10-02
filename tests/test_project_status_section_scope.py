# -*- coding: utf-8 -*-
"""NCR wizard 'sectionScope' declaration: accepted by binding validation, never a query key."""

from __future__ import annotations

from pathlib import Path

import pytest

import web.app as web_app
from core.project_status_contracts import project_status_sync_contract

POLICY = "/api/project-status/deliverables/{}/update-policy"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "scope.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _patch(client, deliverable: str, rule: dict):  # type: ignore[no-untyped-def]
    return client.patch(POLICY.format(deliverable), json={
        "mode": "manual", "enabled": False, "externalKey": None, "matchRule": rule,
        "mapping": {}, "fieldAuthority": {}, "intervalMinutes": 15,
    })


@pytest.mark.parametrize("deliverable", ["VPI-T2-D7", "VPI-T2-D8"])
def test_ncr_binding_accepts_and_round_trips_section_scope(client, deliverable: str) -> None:
    rule = {"reportType": "ncr_progress" if deliverable.endswith("7") else "ncr_detail", "aggregate": True,
            "projectModel": "F610S", "sectionScope": ["车身科", "内饰科"]}
    response = _patch(client, deliverable, rule)
    assert response.status_code == 200, response.get_json()
    stored = client.get(POLICY.format(deliverable)).get_json()["data"]["matchRule"]
    assert stored["sectionScope"] == ["车身科", "内饰科"]


@pytest.mark.parametrize("bad", [[], ["车身科", "车身科"], "车身科", [1], [" "], ["x" * 101], [f"科{i}" for i in range(21)]])
def test_section_scope_must_be_a_bounded_list_of_distinct_nonblank_strings(client, bad) -> None:
    response = _patch(client, "VPI-T2-D7", {"reportType": "ncr_progress", "sectionScope": bad})
    assert response.status_code == 422
    assert "matchRule" in response.get_json()["error"]["fields"]


@pytest.mark.parametrize("deliverable", ["VPI-T2-D2", "VPI-T2-D5", "VPI-T2-D6"])
def test_other_reports_do_not_accept_section_scope(client, deliverable: str) -> None:
    response = _patch(client, deliverable, {"sectionScope": ["车身科"]})
    assert response.status_code == 422


@pytest.mark.parametrize("deliverable", ["VPI-T2-D7", "VPI-T2-D8"])
def test_section_scope_is_not_an_upstream_query_key(deliverable: str) -> None:
    keys = project_status_sync_contract(deliverable)["filterKeys"]
    assert "sectionScope" not in keys and "department" not in keys and "rspDepartment" not in keys
