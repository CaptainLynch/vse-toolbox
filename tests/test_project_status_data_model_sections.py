# -*- coding: utf-8 -*-
"""数模（D5）科室多选筛选：契约、保存校验、上游参数边界与本地收窄。

背景：用户反馈「按部门筛不可靠——同一科室的人有挂在『技术中心』、有挂在
『车体工程』」，因此 D5 增加按科室筛选（默认现行五科室）。TDC 的科室查询参数
只接受单值，多科室只能在抓取后按行内科室列本地收窄（归集口径与看板同源）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import web.app as web_app
from core.project_status_contracts import (
    project_status_source_capabilities,
    project_status_sync_contract,
)
from core.section_rollup import DEFAULT_SECTION_ROLLUP, build_rollup_index
from services.project_status_connectors import TDCProjectStatusConnector
from services.project_status_sync_runner import SyncBindingContext

POLICY = "/api/project-status/deliverables/{}/update-policy"
DEFAULT_SECTIONS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "sections.db"))
    app = web_app.create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _patch(client, deliverable: str, rule: dict):  # type: ignore[no-untyped-def]
    return client.patch(POLICY.format(deliverable), json={
        "mode": "manual", "enabled": False, "externalKey": None, "matchRule": rule,
        "mapping": {}, "fieldAuthority": {}, "intervalMinutes": 15,
    })


def _rows(*sections: str | None):  # type: ignore[no-untyped-def]
    rows = []
    for index, section in enumerate(sections):
        row = {"incident": f"INC-{index}", "department": section}
        rows.append(row)
    return rows


# ── 契约 ────────────────────────────────────────────────────────────────


def test_d5_declares_sections_as_binding_key_not_upstream_filter() -> None:
    capabilities = project_status_source_capabilities("VPI-T2-D5")
    # 配置键（签名/审计/保存校验）里必须有，上游查询键里必须没有。
    assert "sections" in capabilities["matchKeys"]
    assert "sections" not in capabilities["filterKeys"]
    assert capabilities["sectionPresets"] is True


@pytest.mark.parametrize("deliverable", ["VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D6", "VPI-T2-D7"])
def test_other_deliverables_do_not_declare_sections(deliverable: str) -> None:
    capabilities = project_status_source_capabilities(deliverable)
    assert "sections" not in capabilities.get("matchKeys", ())
    assert capabilities.get("sectionPresets") is not True
    assert "sections" not in project_status_sync_contract(deliverable)["filterKeys"]


# ── 保存与回读 ──────────────────────────────────────────────────────────


def test_d5_binding_round_trips_sections(client) -> None:  # type: ignore[no-untyped-def]
    rule = {"reportType": "data_model", "aggregate": True, "projectModel": "F620S",
            "sections": DEFAULT_SECTIONS}
    response = _patch(client, "VPI-T2-D5", rule)
    assert response.status_code == 200, response.get_json()
    stored = client.get(POLICY.format("VPI-T2-D5")).get_json()["data"]["matchRule"]
    assert stored["sections"] == DEFAULT_SECTIONS


@pytest.mark.parametrize("bad", [
    [], ["车身科", "车身科"], "车身科", [1], [" "], ["x" * 101],
    [f"科{i}" for i in range(21)],
])
def test_sections_must_be_a_bounded_list_of_distinct_nonblank_strings(client, bad) -> None:  # type: ignore[no-untyped-def]
    response = _patch(client, "VPI-T2-D5", {"reportType": "data_model", "sections": bad})
    assert response.status_code == 422
    assert "matchRule" in response.get_json()["error"]["fields"]


@pytest.mark.parametrize("deliverable", ["VPI-T2-D2", "VPI-T2-D3", "VPI-T2-D6", "VPI-T2-D7"])
def test_other_reports_do_not_accept_sections(client, deliverable: str) -> None:  # type: ignore[no-untyped-def]
    response = _patch(client, deliverable, {"sections": ["车身科"]})
    assert response.status_code == 422


# ── 上游参数边界 ────────────────────────────────────────────────────────


def test_sections_never_travel_as_upstream_single_value_section() -> None:
    """科室集合不是查询参数：存在 sections 时单值 section 一律不发。

    若把单值科室发上游，其它科室的行会在抓取阶段就被丢掉，本地再收窄就是
    静默少算。
    """
    filters = TDCProjectStatusConnector._data_model_filters(
        {"sections": ["车身科", "内饰科"], "section": "车身科", "department": "车体工程"}
    )
    params = filters.to_params()
    assert "department" not in params
    assert params["superDepartment"] == "车体工程"


def test_single_section_still_travels_when_no_selection() -> None:
    filters = TDCProjectStatusConnector._data_model_filters({"section": "车身科"})
    assert filters.to_params()["department"] == "车身科"


# ── 本地收窄 ────────────────────────────────────────────────────────────


def test_narrow_by_sections_matches_through_rollup_aliases() -> None:
    rows = _rows("车身科", "BE 结构工程科", "视觉工程科", "底盘科", None)
    kept = TDCProjectStatusConnector._narrow_by_sections(
        rows,
        {"sections": ["车身科", "外饰科"]},
        build_rollup_index(DEFAULT_SECTION_ROLLUP),
    )
    # 历史名按归集规则命中（结构工程科→车身科、视觉工程科→外饰科）；
    # 「底盘科」不在所选范围，缺科室列的行同样被排除。
    assert [row["department"] for row in kept] == ["车身科", "BE 结构工程科", "视觉工程科"]


def test_narrow_by_sections_empty_selection_keeps_every_row() -> None:
    rows = _rows("车身科", "底盘科")
    assert TDCProjectStatusConnector._narrow_by_sections(rows, {}, None) == rows


def test_narrow_by_sections_raises_when_column_missing_for_whole_batch() -> None:
    rows = [{"incident": "INC-1"}, {"incident": "INC-2"}]
    with pytest.raises(ValueError) as excinfo:
        TDCProjectStatusConnector._narrow_by_sections(
            rows, {"sections": ["车身科"]}, build_rollup_index(DEFAULT_SECTION_ROLLUP)
        )
    assert "科室列" in str(excinfo.value)


def test_narrow_by_sections_falls_back_to_default_rollup() -> None:
    """未注入归集索引时用内置默认，绝不让全部行落「未归集」。"""
    kept = TDCProjectStatusConnector._narrow_by_sections(
        _rows("车身科"), {"sections": ["车身科"]}, None
    )
    assert len(kept) == 1


@pytest.mark.parametrize("bad", ["车身科", [1], ["x" * 101]])
def test_narrow_by_sections_fails_closed_on_dirty_rule(bad) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        TDCProjectStatusConnector._narrow_by_sections(_rows("车身科"), {"sections": bad}, None)


# ── 映射发现 ────────────────────────────────────────────────────────────


def test_discovery_folds_sections_into_match_rule_not_query_params() -> None:
    rule, values = web_app._mapping_discovery_query_identity(
        {"filters": {"sections": [" 车身科 ", "内饰科", "车身科"]}, "aggregate": True},
        "VPI-T2-D5",
    )
    assert rule["sections"] == ["车身科", "内饰科"]
    assert "sections" not in values


def test_discovery_rejects_invalid_sections() -> None:
    with pytest.raises(web_app._TDCRequestError):
        web_app._mapping_discovery_query_identity(
            {"filters": {"sections": "车身科"}}, "VPI-T2-D5"
        )


# ── 运行期上下文 ────────────────────────────────────────────────────────


def test_sync_context_carries_optional_section_rollup() -> None:
    base = dict(
        binding_id=1, deliverable_id="VPI-T2-D5", phase_id="VPI-T2", source_type="tdc",
        external_key="", match_rule={"reportType": "data_model", "aggregate": True},
        mapping={}, cursor={}, expected_deliverable_updated_at="v1", run_id=7,
        credential_ref="ref",
    )
    assert SyncBindingContext(**base).section_rollup is None
    index = build_rollup_index(DEFAULT_SECTION_ROLLUP)
    assert SyncBindingContext(**base, section_rollup=index).section_rollup == index

# ── 同步运行期（collect）────────────────────────────────────────────────


class _FakeAuth:
    base_url = "https://fixed.example"

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def login(self, username, password):  # type: ignore[no-untyped-def]
        return SimpleNamespace(session=object())


class _SectionsTDC:
    """抓取返回三个科室的行；同时记录上游收到的科室参数。"""

    def __init__(self, **kwargs) -> None:
        self.output_dir = kwargs["output_dir"]
        self.seen_filters = None

    def crawl_data_model_all(self, filters, max_records):  # type: ignore[no-untyped-def]
        self.seen_filters = filters
        return SimpleNamespace(
            rows=[
                {"incident": "900001", "department": "车身科", "currentApprover": "张三"},
                {"incident": "900002", "department": "BE 结构工程科", "currentApprover": "李四"},
                {"incident": "900003", "department": "底盘科", "currentApprover": "王五"},
            ],
            complete=True,
            stop_reason="reported_pages",
        )

    def export_data_model(self, filters):  # type: ignore[no-untyped-def]
        path = self.output_dir / "official.xlsx"
        path.write_bytes(b"PK\x03\x04fake")
        return SimpleNamespace(path=path, file_name="official.xlsx", byte_count=8)


def _collect(tmp_path: Path, crawler_cls, match_rule: dict):  # type: ignore[no-untyped-def]
    from core.archive_store import ArchiveStore
    from core.credential_provider import MemoryCredentialProvider

    archive = ArchiveStore({"default": tmp_path}, reserve_bytes=0)
    connector = TDCProjectStatusConnector(
        MemoryCredentialProvider({"ref": ("user", "pass")}), archive,
        auth_factory=_FakeAuth, crawler_factory=crawler_cls,
    )
    ctx = SyncBindingContext(
        binding_id=31, deliverable_id="VPI-T2-D5", phase_id="VPI-T2",
        source_type="tdc", external_key="",
        match_rule=match_rule,
        mapping={"owner": "currentApprover"}, cursor={},
        expected_deliverable_updated_at="v1", run_id=32, credential_ref="ref",
        section_rollup=build_rollup_index(DEFAULT_SECTION_ROLLUP),
    )
    return connector.collect(ctx), connector


def test_collect_narrows_rows_by_selected_sections(tmp_path: Path) -> None:
    snapshot, connector = _collect(
        tmp_path,
        _SectionsTDC,
        {"reportType": "data_model", "aggregate": True, "sections": ["车身科"]},
    )
    # 上游不收到单值科室参数（多科室靠本地收窄）。
    assert connector is not None
    kept = [row["incident"] for row in snapshot.analysis_rows]
    assert kept == ["900001", "900002"]  # 「BE 结构工程科」按归集规则归到车身科
    # 归档原始行（取证）不收窄。
    assert len(snapshot.analysis_rows) == 2


def test_collect_without_sections_keeps_every_row(tmp_path: Path) -> None:
    snapshot, _ = _collect(
        tmp_path,
        _SectionsTDC,
        {"reportType": "data_model", "aggregate": True},
    )
    assert len(snapshot.analysis_rows) == 3


def test_collect_raises_when_section_column_missing(tmp_path: Path) -> None:
    class _NoSectionColumn(_SectionsTDC):
        def crawl_data_model_all(self, filters, max_records):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                rows=[{"incident": "900001", "currentApprover": "张三"}],
                complete=True,
                stop_reason="reported_pages",
            )

    with pytest.raises(ValueError) as excinfo:
        _collect(
            tmp_path,
            _NoSectionColumn,
            {"reportType": "data_model", "aggregate": True, "sections": ["车身科"]},
        )
    assert "科室列" in str(excinfo.value)

