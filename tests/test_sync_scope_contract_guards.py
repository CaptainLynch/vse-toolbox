# -*- coding: utf-8 -*-
"""同步范围字段的守卫：科室两键互斥、归档拒绝收窄键、字段契约版本对齐。

这三项对应架构评审里的 R3 / R10 / R9：
- R3：单值 ``section``（上游过滤）与多选 ``sections``（本地收窄）同时存在时，
  连接器只能丢弃其一，用户会以为两层条件都生效（多算）。保存与运行前都要拦。
- R10：归档保存的是上游原始导出，没有本地收窄这一步；把 ``sections`` 静默忽略
  会让用户以为归档也按科室收窄。
- R9：前后端字段契约版本不一致时，界面会显示旧控件；必须显式提示。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app
from core.project_status_contracts import MATCH_FIELD_CONTRACT

POLICY = "/api/project-status/deliverables/{}/update-policy"
STATIC = Path(__file__).resolve().parent.parent / "plugins" / "project_overview" / "static"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "guards.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _patch(client, deliverable: str, rule: dict):  # type: ignore[no-untyped-def]
    return client.patch(POLICY.format(deliverable), json={
        "mode": "manual", "enabled": False, "externalKey": None, "matchRule": rule,
        "mapping": {}, "fieldAuthority": {}, "intervalMinutes": 15,
    })


def test_section_and_sections_together_are_rejected(client) -> None:  # type: ignore[no-untyped-def]
    response = _patch(client, "VPI-T2-D5", {
        "reportType": "data_model", "aggregate": True,
        "section": "车身科", "sections": ["车身科"],
    })
    assert response.status_code == 422, response.get_json()
    message = response.get_json()["error"]["fields"]["matchRule"]
    assert "二选一" in message


@pytest.mark.parametrize("rule", [
    {"reportType": "data_model", "aggregate": True, "sections": ["车身科"]},
    {"reportType": "data_model", "aggregate": True, "section": "车身科"},
])
def test_single_scope_key_still_saves(client, rule: dict) -> None:  # type: ignore[no-untyped-def]
    response = _patch(client, "VPI-T2-D5", rule)
    assert response.status_code == 200, response.get_json()


def test_conflict_guard_is_scoped_to_data_model() -> None:
    """SOR 的 department/section 是既有上游条件，不得被数模的互斥规则波及。"""
    from services.project_status_updates import _section_scope_conflict_error

    assert _section_scope_conflict_error({
        "reportType": "sor", "section": "车身科", "sections": ["车身科"],
    }) is None
    assert _section_scope_conflict_error({
        "reportType": "data_model", "section": "车身科", "sections": ["车身科"],
    }) is not None
    assert _section_scope_conflict_error({"reportType": "data_model", "section": " "}) is None


def test_source_info_exposes_match_field_contract(client) -> None:  # type: ignore[no-untyped-def]
    data = client.get("/api/project-status?phase=VPI-T2").get_json()["data"]
    for item in data["deliverables"]:
        assert item["sourceInfo"]["matchFieldContract"] == MATCH_FIELD_CONTRACT


def test_archive_rejects_local_narrow_keys() -> None:
    from services.scheduled_archive_connectors import TDCArchiveConnector

    with pytest.raises(ValueError) as excinfo:
        TDCArchiveConnector._data_model_filters({"sections": ["车身科"]})
    assert "科室范围" in str(excinfo.value)
    # 上游过滤键仍可用（存量归档任务不受影响）。
    filters = TDCArchiveConnector._data_model_filters({"section": "车身科"})
    assert filters.to_params()["department"] == "车身科"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark_node = pytest.mark.skipif(
    _node_major() < 22, reason="needs Node 22+ to import ES modules"
)


@pytestmark_node
def test_frontend_contract_constant_matches_backend() -> None:
    """前端常量必须与后端同名常量同值：漂移就是「版本不一致提示」的来源。"""
    script = "\n".join([
        "const base = process.argv[1];",
        "const P = await import(base + '/deliverable/policy-logic.js');",
        "console.log(JSON.stringify({contract: P.MATCH_FIELD_CONTRACT}));",
    ])
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, STATIC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["contract"] == MATCH_FIELD_CONTRACT


@pytestmark_node
def test_summary_labels_section_scope_in_chinese() -> None:
    script = "\n".join([
        "const base = process.argv[1];",
        "const S = await import(base + '/details/sync-settings-logic.js');",
        "console.log(JSON.stringify({text: S.filterSummary({filters: {sections: ['车身科', '内饰科']}})}));",
    ])
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, STATIC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["text"] == "科室范围：车身科、内饰科"
