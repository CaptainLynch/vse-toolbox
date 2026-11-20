"""数模设计审核流程 TDC + iBOM 双源（docs/PLAN_20261119_IBOM_DMM_DUAL_SOURCE.md §2–§5）。

全部用合成数据：不含真实单号、人名或项目信息。
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from core.report_contracts import report_contracts
from services.data_model_dual_source import (
    REASON_IBOM_AUTH,
    REASON_IBOM_COUNT,
    REASON_IBOM_FILTER,
    REASON_IBOM_REPORT,
    REASON_IBOM_REQUEST,
    DualSourceIncomplete,
    apply_ibom_filters,
    dual_source_enabled,
    merge_sources,
    read_ibom_report,
)
from services.deliverable_form_analysis import build_form_snapshot
from services.ibom_auth import IBOMAuthError
from services.ibom_client import IBOMClientError
from services.tdc_official_rows import (
    OfficialWorkbookContractError,
    official_rows_from_matrix,
    variant_file_headers,
)
from services.scheduled_archive_connectors import FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE, TDCArchiveConnector
from tests.test_scheduled_archive_connectors import (
    FakeAuthClient,
    OfficialExportTDCCrawler,
    _tdc_export_values,
    make_context,
    make_store,
    random_credential,
)

LABELS = [str(h) for h in report_contracts()["tdc_data_model"]["headerRows"][0]]


def contract_row(**values: str) -> dict[str, Any]:
    return {label: values.get(label, "") for label in LABELS}


def ibom_row(serial: str, part: str, *, status: str = "审批中", project: str = "Ar-C",
             section: str = "车体科", applied: str = "2026-11-18 10:00:00", applicant: str = "甲") -> dict[str, Any]:
    return contract_row(**{"流水单号": serial, "零件号": part, "状态": status, "项目/车型": project,
                           "部门": section, "申请日期": applied, "申请人": applicant})


def _cell_ref(column: int, row: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return f"{result}{row}"


def xlsx_bytes(rows: list[list[object]]) -> bytes:
    def row_xml(values: list[object], number: int) -> str:
        cells = "".join(
            f'<c r="{_cell_ref(i, number)}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
            for i, v in enumerate(values, 1) if v not in (None, "")
        )
        return f'<row r="{number}">{cells}</row>'

    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'))
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>'))
        archive.writestr("xl/worksheets/sheet1.xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(row_xml(values, i) for i, values in enumerate(rows, 1))
            + "</sheetData></worksheet>"))
    return buffer.getvalue()


def ibom_report_bytes(rows: list[dict[str, Any]]) -> bytes:
    header = variant_file_headers("data_model", "ibom")
    matrix = [header] + [[str(index)] + [row[label] for label in LABELS[1:]] for index, row in enumerate(rows, 1)]
    return xlsx_bytes(matrix)


# ── 表头变体 ───────────────────────────────────────────────────────────


def test_ibom_variant_accepts_row_number_header_and_blanks_instance_no():
    header = variant_file_headers("data_model", "ibom")
    assert header[0] == "序号" and header[1:] == LABELS[1:]
    rows = official_rows_from_matrix([header, ["7", "主题", "3D-1"]], "data_model", strict=True, variant="ibom")
    assert rows[0]["实例号"] is None
    assert rows[0]["流水单号"] == "3D-1"
    assert list(rows[0]) == LABELS


def test_variants_do_not_accept_each_other():
    with pytest.raises(OfficialWorkbookContractError):
        official_rows_from_matrix([LABELS, ["1"]], "data_model", strict=True, variant="ibom")
    with pytest.raises(OfficialWorkbookContractError):
        official_rows_from_matrix([variant_file_headers("data_model", "ibom"), ["1"]], "data_model", strict=True)
    altered = variant_file_headers("data_model", "ibom")
    altered[30] = altered[30] + " "
    with pytest.raises(OfficialWorkbookContractError):
        official_rows_from_matrix([altered, ["1"]], "data_model", strict=True, variant="ibom")
    with pytest.raises(OfficialWorkbookContractError):
        variant_file_headers("sor", "ibom")


# ── 报表读入与完整性 ───────────────────────────────────────────────────


def test_read_ibom_report_counts_documents_not_rows():
    rows = [ibom_row("3D-1", "P1"), ibom_row("3D-1", "P2"), ibom_row("3D-2", "P3")]
    report = read_ibom_report(ibom_report_bytes(rows), total_count=2, max_rows=100)
    assert report.documents == 2 and len(report.rows) == 3
    assert all(row["实例号"] is None for row in report.rows)


def test_read_ibom_report_count_mismatch_and_bad_file_are_incomplete():
    data = ibom_report_bytes([ibom_row("3D-1", "P1")])
    with pytest.raises(DualSourceIncomplete) as info:
        read_ibom_report(data, total_count=2, max_rows=100)
    assert info.value.reason == REASON_IBOM_COUNT
    with pytest.raises(DualSourceIncomplete) as info:
        read_ibom_report(xlsx_bytes([LABELS, ["1"]]), total_count=1, max_rows=100)
    assert info.value.reason == REASON_IBOM_REPORT
    with pytest.raises(DualSourceIncomplete) as info:
        read_ibom_report(ibom_report_bytes([ibom_row("3D-1", "P1"), ibom_row("3D-2", "P2")]),
                         total_count=2, max_rows=2)
    assert info.value.reason == REASON_IBOM_REPORT


# ── 本地筛选 ──────────────────────────────────────────────────────────


def test_filters_match_production_semantics():
    rows = [
        ibom_row("3D-1", "P1", project="Ar-C", section="车体科"),
        ibom_row("3D-2", "P2", project="AR-C ", section="车身科"),
        ibom_row("3D-3", "P3", project="TRA_2.0", section="车体科"),
        ibom_row("3D-4", "P4", project="CF810P", section="车体科"),
    ]
    kept, report = apply_ibom_filters(rows, {"projectModel": "AR-C", "section": "车体科", "syncScope": "all"})
    assert [row["流水单号"] for row in kept] == ["3D-1"]
    assert report["excludedArchitectureProjects"] == {"TRA_2.0": 1}
    assert [step["step"] for step in report["steps"]] == ["all", "section", "projectModel"]


def test_filters_incident_dates_and_ignored_keys():
    rows = [ibom_row("3D-1", "P1", applied="2026-11-01 09:00:00"), ibom_row("3D-2", "P2", applied="2026-11-20 09:00:00")]
    assert apply_ibom_filters(rows, {"incident": "12345"})[0] == []
    kept, _ = apply_ibom_filters(rows, {"applicationStart": "2026-11-10", "applicationEnd": "2026-11-30"})
    assert [row["流水单号"] for row in kept] == ["3D-2"]
    kept, _ = apply_ibom_filters(rows, {"documentNo": "3D-9", "watchlist": ["3D-1"], "projectModel": ""})
    assert len(kept) == 2


@pytest.mark.parametrize("key", ["applicant", "department", "partNumber", "modelNumber", "status", "somethingNew"])
def test_unverified_filter_keys_fail_closed(key):
    with pytest.raises(DualSourceIncomplete) as info:
        apply_ibom_filters([ibom_row("3D-1", "P1")], {key: "x"})
    assert info.value.reason == REASON_IBOM_FILTER
    assert key in info.value.detail


# ── 合并 ──────────────────────────────────────────────────────────────


def tdc_row(serial: str, part: str, status: str = "审批中", applicant: str = "甲") -> dict[str, Any]:
    row = ibom_row(serial, part, status=status, applicant=applicant)
    row["实例号"] = "900" + serial[-1]
    return row


def serials(rows, source):
    return sorted({row["流水单号"] for row in rows if row["_sourceSystem"] == source})


def test_merge_takes_each_document_from_one_side_only():
    tdc = [tdc_row("3D-1", "P1"), tdc_row("3D-1", "P2"), tdc_row("3D-2", "P3")]
    ibom = [ibom_row("3D-2", "P3"), ibom_row("3D-3", "P4")]
    merged, report = merge_sources(tdc, ibom)
    assert serials(merged, "tdc") == ["3D-1"]
    assert serials(merged, "ibom") == ["3D-2", "3D-3"]
    assert len(merged) == 4
    assert report["dualSystem"] == ["3D-2"] and report["conflicts"] == []
    assert report["tdc"]["kept"] == 1 and report["ibom"]["kept"] == 2


@pytest.mark.parametrize("tdc_status,ibom_status,winner", [
    ("已废弃", "审批中", "ibom"),
    ("审批中", "取消", "tdc"),
    ("已撤回", "已发布", "ibom"),
    ("已废弃", "取消", "ibom"),
    ("已完成", "审批中", "ibom"),
])
def test_merge_discarded_side_loses(tdc_status, ibom_status, winner):
    merged, _ = merge_sources([tdc_row("3D-1", "P1", tdc_status)], [ibom_row("3D-1", "P1", status=ibom_status)])
    assert {row["_sourceSystem"] for row in merged} == {winner}


def test_merge_reports_conflicts_without_mixing_rows():
    merged, report = merge_sources([tdc_row("3D-1", "P1"), tdc_row("3D-1", "P2")],
                                   [ibom_row("3D-1", "P1", applicant="乙")])
    assert report["conflicts"] == ["3D-1"]
    assert [row["零件号"] for row in merged] == ["P1"]
    assert {row["_sourceSystem"] for row in merged} == {"ibom"}


def test_merge_keeps_tdc_api_rows_and_rows_without_serial():
    api_row = {"incident": "1", "documentNo": "3D-8", "status": "2", "partNumber": "P8"}
    orphan = {"incident": "2", "status": "4"}
    merged, report = merge_sources([api_row, orphan], [ibom_row("3D-9", "P9")])
    assert [row.get("documentNo") or row.get("流水单号") for row in merged] == ["3D-8", None, "3D-9"]
    assert report["tdc"]["rowsWithoutSerial"] == 1


def test_source_marker_reaches_snapshot_dimensions_only_when_present():
    merged, _ = merge_sources([tdc_row("3D-1", "P1")], [ibom_row("3D-2", "P2")])
    snapshot = build_form_snapshot("tdc_data_model", tuple(merged), snapshot_at="2026-11-20T01:00:00Z",
                                   source_run_id=1, source="scheduled_archive")
    assert sorted(row["dimensions"]["sourceSystem"] for row in snapshot.rows) == ["ibom", "tdc"]
    assert all("_sourceSystem" not in str(row["values"]) for row in snapshot.rows)
    plain = build_form_snapshot("tdc_data_model", (tdc_row("3D-1", "P1"),), snapshot_at="2026-11-20T01:00:00Z",
                                source_run_id=2, source="scheduled_archive")
    assert "sourceSystem" not in plain.rows[0]["dimensions"]


def test_dual_source_switch_defaults_off():
    assert dual_source_enabled({}) is False
    assert dual_source_enabled({"VSE_IBOM_DUAL_SOURCE": "1"}) is True
    assert dual_source_enabled({"VSE_IBOM_DUAL_SOURCE": "no"}) is False


# ── 定时归档连接器接入 ─────────────────────────────────────────────────


class FakeIBOMAuth:
    calls: list[tuple[str, str]] = []
    login_exc: Exception | None = None

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def login(self, username: str, password: str) -> Any:
        FakeIBOMAuth.calls.append((username, password))
        if FakeIBOMAuth.login_exc:
            raise FakeIBOMAuth.login_exc
        return SimpleNamespace(session=SimpleNamespace(close=lambda: None), user_token="t",
                               user_login_name="u", login_type="DEFAULT_SSO")


class FakeIBOMClient:
    report_rows: list[dict[str, Any]] = []
    total: int | None = None
    exc: Exception | None = None

    def __init__(self, session: Any, token: Any, timeout: float = 60.0) -> None:
        pass

    def dmm_total_count(self) -> int:
        if FakeIBOMClient.exc:
            raise FakeIBOMClient.exc
        return FakeIBOMClient.total if FakeIBOMClient.total is not None else len(
            {row["流水单号"] for row in FakeIBOMClient.report_rows})

    def export_dmm_report(self) -> Any:
        content = ibom_report_bytes(FakeIBOMClient.report_rows)
        return SimpleNamespace(content=content, file_name="数模设计审核流程报表_20261120.xlsx", byte_count=len(content))


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeIBOMAuth.calls, FakeIBOMAuth.login_exc = [], None
    FakeIBOMClient.report_rows, FakeIBOMClient.total, FakeIBOMClient.exc = [], None, None
    yield


def make_connector(tmp_path, *, enabled=True, tdc_login_exc=None):
    def crawler_factory(**kw):
        return OfficialExportTDCCrawler(**kw, export_values=_tdc_export_values())

    def tdc_auth(**kw):
        return FakeAuthClient(login_exc=tdc_login_exc, **kw)

    return TDCArchiveConnector(make_store(tmp_path), auth_factory=tdc_auth, crawler_factory=crawler_factory,
                               ibom_auth_factory=FakeIBOMAuth, ibom_client_factory=FakeIBOMClient,
                               dual_source_flag=lambda: enabled)


def context(filters=None):
    return make_context("tdc_data_model", source_type="tdc", report_type="data_model",
                        filters=filters or {}, output_subdir="dual", run_id=77)


def test_connector_disabled_keeps_tdc_only_behaviour(tmp_path):
    collection = make_connector(tmp_path, enabled=False).collect(context(), random_credential()[0])
    assert collection.form_projection_error is None
    assert len(collection.form_rows) == 1 and "_sourceSystem" not in collection.form_rows[0]
    assert FakeIBOMAuth.calls == []
    assert len(collection.artifacts) == 3


def test_connector_merges_ibom_rows_and_archives_report(tmp_path):
    FakeIBOMClient.report_rows = [ibom_row("3D-50", "P1"), ibom_row("3D-50", "P2"), ibom_row("3D-51", "P3")]
    credential, user, password = random_credential()
    collection = make_connector(tmp_path).collect(context(), credential)
    assert collection.form_projection_error is None
    sources = [row["_sourceSystem"] for row in collection.form_rows]
    assert sources.count("tdc") == 1 and sources.count("ibom") == 3
    assert FakeIBOMAuth.calls == [(user, password)]
    assert len(collection.artifacts) == 4
    assert any("ibom" in str(item.as_metadata()) for item in collection.artifacts)
    sources_report = collection.form_coverage["sources"]
    assert sources_report["ibomExport"]["documents"] == 2
    assert collection.form_coverage["kind"] == "all"


def test_connector_applies_job_filters_on_ibom_side(tmp_path):
    FakeIBOMClient.report_rows = [ibom_row("3D-60", "P1", project="Ar-C", section="车体科"),
                                  ibom_row("3D-61", "P2", project="CF810P", section="车体科")]
    job = context({"projectModel": "AR-C", "section": "车体科"})
    collection = make_connector(tmp_path).collect(job, random_credential()[0])
    ibom = [row for row in collection.form_rows if row["_sourceSystem"] == "ibom"]
    assert [row["流水单号"] for row in ibom] == ["3D-60"]


@pytest.mark.parametrize("setup,reason", [
    (lambda: setattr(FakeIBOMAuth, "login_exc", IBOMAuthError("x", stage="auth-credentials", credentials_sent=True)),
     REASON_IBOM_AUTH),
    (lambda: setattr(FakeIBOMClient, "exc", IBOMClientError("x", stage="dmm-count")), REASON_IBOM_REQUEST),
    (lambda: setattr(FakeIBOMClient, "total", 5), REASON_IBOM_COUNT),
])
def test_connector_incomplete_ibom_side_blocks_snapshot(tmp_path, setup, reason, monkeypatch):
    FakeIBOMClient.report_rows = [ibom_row("3D-70", "P1")]
    setup()
    events = []
    import services.scheduled_archive_connectors as module
    monkeypatch.setattr(module, "emit", lambda kind, data=None, **kw: events.append((kind, data)))
    collection = make_connector(tmp_path).collect(context(), random_credential()[0])
    assert collection.form_projection_error == FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE
    assert collection.form_rows is None
    assert ("data_model_dual_source_incomplete", {"report_type": "data_model", "reason": reason}) in events
    assert len(FakeIBOMAuth.calls) == 1


def test_connector_fail_closed_filter_blocks_snapshot(tmp_path):
    FakeIBOMClient.report_rows = [ibom_row("3D-80", "P1")]
    collection = make_connector(tmp_path).collect(context({"applicant": "某人"}), random_credential()[0])
    assert collection.form_projection_error == FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE


def test_connector_never_contacts_ibom_when_tdc_login_fails(tmp_path):
    with pytest.raises(RuntimeError):
        make_connector(tmp_path, tdc_login_exc=RuntimeError("tdc down")).collect(context(), random_credential()[0])
    assert FakeIBOMAuth.calls == []
    assert REASON_IBOM_FILTER  # 保持导入被使用


# ── 退出 TDC（方案 §9）────────────────────────────────────────────────


def test_tdc_retired_switch_requires_dual_source():
    from services.data_model_dual_source import tdc_side_retired

    assert tdc_side_retired({"VSE_TDC_DATA_MODEL_RETIRED": "1"}) is False
    assert tdc_side_retired({"VSE_TDC_DATA_MODEL_RETIRED": "1", "VSE_IBOM_DUAL_SOURCE": "1"}) is True
    assert tdc_side_retired({"VSE_IBOM_DUAL_SOURCE": "1"}) is False


def retired_connector(tmp_path, *, retired=True, dual=True):
    def tdc_auth(**kw):
        return FakeAuthClient(login_exc=AssertionError("TDC must not be contacted"), **kw)

    def crawler_factory(**kw):
        raise AssertionError("TDC crawler must not be built")

    return TDCArchiveConnector(make_store(tmp_path), auth_factory=tdc_auth, crawler_factory=crawler_factory,
                               ibom_auth_factory=FakeIBOMAuth, ibom_client_factory=FakeIBOMClient,
                               dual_source_flag=lambda: dual, tdc_retired_flag=lambda: retired)


def test_retired_tdc_collects_ibom_only(tmp_path):
    FakeIBOMClient.report_rows = [ibom_row("3D-90", "P1"), ibom_row("3D-91", "P2", status="取消")]
    credential, user, password = random_credential()
    collection = retired_connector(tmp_path).collect(context(), credential)
    assert collection.form_projection_error is None
    assert [row["流水单号"] for row in collection.form_rows] == ["3D-90"]  # 取消被范围剔除
    assert {row["_sourceSystem"] for row in collection.form_rows} == {"ibom"}
    assert collection.form_coverage["sources"]["tdcRetired"] is True
    assert FakeIBOMAuth.calls == [(user, password)]
    assert collection.record_count == 2


def test_retired_tdc_rejected_password_is_a_credential_error(tmp_path):
    from services.scheduled_archive_runner import _error_type

    FakeIBOMAuth.login_exc = IBOMAuthError("x", stage="auth-credentials", status_code=200,
                                           credentials_sent=True, rejected=True)
    with pytest.raises(IBOMAuthError) as info:
        retired_connector(tmp_path).collect(context(), random_credential()[0])
    assert _error_type(info.value) == "credential_invalid"
    assert len(FakeIBOMAuth.calls) == 1


@pytest.mark.parametrize("status", [503, 500, None])
def test_retired_tdc_transient_identity_failure_is_not_a_credential_error(tmp_path, status):
    FakeIBOMAuth.login_exc = IBOMAuthError("x", stage="auth-credentials", status_code=status,
                                           credentials_sent=True, rejected=False)
    collection = retired_connector(tmp_path).collect(context(), random_credential()[0])
    assert collection.form_projection_error == FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE


def test_dual_mode_ibom_password_rejection_stays_incomplete(tmp_path):
    FakeIBOMAuth.login_exc = IBOMAuthError("x", stage="auth-credentials", credentials_sent=True)
    collection = make_connector(tmp_path).collect(context(), random_credential()[0])
    assert collection.form_projection_error == FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE


def test_retired_tdc_ibom_failure_blocks_snapshot(tmp_path):
    FakeIBOMAuth.login_exc = IBOMAuthError("x", stage="sso-entry")
    collection = retired_connector(tmp_path).collect(context(), random_credential()[0])
    assert collection.form_projection_error == FORM_PROJECTION_DUAL_SOURCE_INCOMPLETE
    assert collection.form_rows is None
    assert len(collection.artifacts) == 2  # 只剩规范化 CSV/JSON


def test_retired_tdc_still_validates_filters_and_watchlist(tmp_path):
    FakeIBOMClient.report_rows = [ibom_row("3D-90", "P1"), ibom_row("3D-91", "P2")]
    with pytest.raises(ValueError):
        retired_connector(tmp_path).collect(context({"unknownKey": "x"}), random_credential()[0])
    collection = retired_connector(tmp_path).collect(
        context({"syncScope": "watchlist", "watchlist": ["3D-91"]}), random_credential()[0])
    assert [row["流水单号"] for row in collection.form_rows] == ["3D-91"]
    assert collection.form_coverage["kind"] == "watchlist"


@pytest.mark.parametrize("applied", ["2026/11/18 10:00", "46344.42", ""])
def test_date_filter_fails_closed_on_unparsable_dates(applied):
    rows = [ibom_row("3D-1", "P1"), ibom_row("3D-2", "P2", applied=applied)]
    with pytest.raises(DualSourceIncomplete) as info:
        apply_ibom_filters(rows, {"applicationStart": "2026-11-01"})
    assert info.value.reason == REASON_IBOM_REPORT


def test_merge_refuses_ibom_rows_without_serial():
    with pytest.raises(DualSourceIncomplete):
        merge_sources([], [ibom_row("", "P1")])


def test_cancelled_is_excluded_for_data_model_only():
    from services.scope_exclusion import exclude_tdc_scope_rows

    assert exclude_tdc_scope_rows("data_model", [{"状态": "取消"}])[1] == 1
    assert exclude_tdc_scope_rows("sor", [{"审批状态": "取消"}])[1] == 0
