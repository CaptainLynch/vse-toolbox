# -*- coding: utf-8 -*-
"""签署日报对 iBOM 单的适配（docs/PLAN_20261119_IBOM_DMM_DUAL_SOURCE.md §7）。

- iBOM 状态词：已发布 = 完成；取消 = 废弃（不进日报）；草稿/退回 = 在途且不报 unknownStatus。
- 阶段先看状态：草稿 → 待提交，退回 → 退回修改。
- iBOM 单的应签/已签/未签/签署率按角色列人次自算（决策 C5），不报计数不一致；TDC 单不变。
- 快照路径：dimensions.sourceSystem → 记录里的 ``_sourceSystem``。
"""

from __future__ import annotations

from tests.test_sign_daily_rules import R, _row

IBOM = {R.SOURCE_KEY: R.SOURCE_IBOM}


def build(*rows):
    return R.build_flows(list(rows))


def kinds(result, serial="S1"):
    return {item["kind"] for item in result.anomalies if item["serial"] == serial}


def test_ibom_status_words():
    result = build(
        _row("S1", 状态="已发布", **IBOM),
        _row("S2", 状态="取消", **IBOM),
        _row("S3", 状态="草稿", **IBOM),
        _row("S4", 状态="退回", **IBOM),
    )
    flows = {flow.serial: flow for flow in result.flows}
    assert set(flows) == {"S1", "S3", "S4"}  # 取消 = 废弃，不返回
    assert flows["S1"].is_done and not flows["S1"].in_flight
    assert flows["S3"].in_flight and flows["S4"].in_flight
    assert not any(item["kind"] == "unknownStatus" for item in result.anomalies)


def test_stage_follows_ibom_status_first():
    draft = build(_row("S1", 状态="草稿", 设计工程师="张三(未签)", 待审批人员="", **IBOM)).flows[0]
    assert draft.stage == R.STAGE_DRAFT
    returned = build(_row("S1", 状态="退回", 造型="李四(未签)", 待审批人员="王五", **IBOM)).flows[0]
    assert returned.stage == R.STAGE_RETURNED


def test_draft_without_pending_is_not_an_anomaly():
    result = build(_row("S1", 状态="草稿", 设计工程师="张三(未签)", 待审批人员="", **IBOM))
    assert "pendingEmpty" not in kinds(result)
    in_flight = build(_row("S1", 状态="审批中", 设计工程师="张三(未签)", 待审批人员="", **IBOM))
    assert "pendingEmpty" in kinds(in_flight)


def test_ibom_counts_use_role_column_occurrences():
    # 同一人出现在两列：TDC 口径按人次计 2；iBOM 报表按人去重给 1。
    row = _row(
        "S1", 状态="审批中", **IBOM,
        造型="甲(未签)", 总体工程="甲(未签)、乙", 设计工程师="丙",
        应签人数=3, 已签人数=2, 未签人数=1, 签署率="66.67%", 待审批人员="甲",
    )
    result = build(row)
    flow = result.flows[0]
    assert (flow.required, flow.signed, flow.unsigned_count) == (4, 2, 2)
    assert flow.rate == 50.0
    assert not {"requiredCountDiffer", "unsignedCountDiffer"} & kinds(result)


def test_tdc_counts_unchanged_and_still_checked():
    row = _row("S1", 状态="进行中", 造型="甲(未签)", 总体工程="甲(未签)、乙",
               应签人数=2, 已签人数=1, 未签人数=1, 签署率="50.00%")
    result = build(row)
    flow = result.flows[0]
    assert flow.source == R.SOURCE_TDC
    assert (flow.required, flow.signed, flow.unsigned_count, flow.rate) == (2, 1, 1, 50.0)
    assert {"requiredCountDiffer", "unsignedCountDiffer"} <= kinds(result)


def test_ibom_order_with_no_signers_has_no_rate():
    flow = build(_row("S1", 状态="草稿", 应签人数=0, **IBOM)).flows[0]
    assert flow.required == 0 and flow.rate is None


def test_load_source_carries_source_from_snapshot_dimensions(monkeypatch):
    from plugins.sign_daily import service as S

    headers = ["流水单号", "状态", "零件号"]
    snapshot = {"id": 3, "snapshot_at": "2026-11-20T01:00:00Z", "schema_json": "{}"}

    class DB:
        def get_latest_deliverable_form_snapshot(self, key):
            return snapshot

        def list_deliverable_form_snapshots(self, key, limit=60):
            return [snapshot]

        def list_deliverable_form_snapshot_rows(self, snapshot_id):
            return [
                {"values": ["3D-1", "审批中", "P1"], "dimensions": {"sourceSystem": "ibom"}},
                {"values": ["3D-2", "审批中", "P2"], "dimensions": {"dataSource": "项目件"}},
            ]

    monkeypatch.setattr(S.V, "check_columns", lambda headers: None)
    source = S.load_source(DB(), lambda snap: headers)
    assert source.records[0][R.SOURCE_KEY] == R.SOURCE_IBOM
    assert R.SOURCE_KEY not in source.records[1]


# ── 阶段 4：本地导入认 iBOM 报表表头 ───────────────────────────────────

from datetime import date  # noqa: E402

import pytest  # noqa: E402

from services.tdc_official_rows import official_contract_headers, variant_file_headers  # noqa: E402
from tests.test_data_model_dual_source import ibom_row, xlsx_bytes  # noqa: E402

LABELS = official_contract_headers("data_model")


def ibom_matrix(header=None):
    header = header or variant_file_headers("data_model", "ibom")
    row = ibom_row("3D-90", "P1")
    row.update({"造型": "甲(未签)", "总体工程": "甲(未签)、乙", "设计工程师": "丙", "应签人数": "3",
                "已签人数": "2", "未签人数": "1", "签署率": "66.67%", "待审批人员": "甲"})
    return [header, ["1"] + [row[label] for label in LABELS[1:]]]


def utf16_txt(matrix):
    return ("\r\n".join("\t".join(str(v) for v in row) for row in matrix) + "\r\n").encode("utf-16")


def importer():
    from plugins.sign_daily import importer as module
    return module


@pytest.mark.parametrize("name,payload", [
    ("ibom.xlsx", lambda: xlsx_bytes(ibom_matrix())),
    ("ibom.txt", lambda: utf16_txt(ibom_matrix())),
])
def test_manual_import_accepts_ibom_report_and_recounts(name, payload):
    module = importer()
    source = module.source_from_bytes(payload(), date(2026, 11, 20), name=name)
    assert all(record[R.SOURCE_KEY] == R.SOURCE_IBOM for record in source.records)
    flow = R.build_flows(source.records).flows[0]
    assert (flow.required, flow.signed, flow.unsigned_count) == (4, 2, 2)
    meta = module.import_meta(__import__("pathlib").Path(name), source, name=name, digest="0" * 64)
    assert meta["sourceVariant"] == "ibom"
    assert "iBOM" in meta["note"]


def test_manual_import_tdc_report_unchanged():
    module = importer()
    matrix = ibom_matrix(header=list(LABELS))
    matrix[1][0] = "54110920"
    source = module.source_from_bytes(xlsx_bytes(matrix), date(2026, 11, 20), name="tdc.xlsx")
    assert R.SOURCE_KEY not in source.records[0]
    meta = module.import_meta(__import__("pathlib").Path("tdc.xlsx"), source, name="tdc.xlsx", digest="0" * 64)
    assert meta["sourceVariant"] == "tdc"


def test_manual_import_rejects_ibom_header_with_other_differences():
    module = importer()
    header = variant_file_headers("data_model", "ibom")
    header[20] = header[20] + "X"
    with pytest.raises(module.ManualImportError) as info:
        module.source_from_bytes(xlsx_bytes(ibom_matrix(header)), date(2026, 11, 20), name="bad.xlsx")
    assert info.value.code == "E_HEADER_MISMATCH"
    other = list(LABELS)
    other[0] = "编号"
    with pytest.raises(module.ManualImportError) as info:
        module.source_from_bytes(xlsx_bytes(ibom_matrix(other)), date(2026, 11, 20), name="bad.xlsx")
    assert info.value.code == "E_HEADER_MISMATCH"


def test_directory_precheck_accepts_ibom_report(tmp_path):
    module = importer()
    path = tmp_path / "ibom.xlsx"
    path.write_bytes(xlsx_bytes(ibom_matrix()))
    assert module._header_ok(path) == (True, "")


def test_excel_proxy_keeps_ibom_numeric_columns_as_text():
    from plugins.sign_daily import excel_proxy

    header = variant_file_headers("data_model", "ibom")
    row = [None] * len(header)
    row[0], row[11], row[12] = 1.0, 2.0, 0.83139307
    out = excel_proxy.to_canonical([header, row], header,
                                   numeric_text_columns=excel_proxy.IBOM_NUMERIC_TEXT_COLUMNS)
    assert out[1][0] == "1" and out[1][11] == "2" and out[1][12] == "0.83139307"
    with pytest.raises(excel_proxy.CanonicalError):
        excel_proxy.to_canonical([header, row], header)


# ── 一键生成：快照里的 iBOM 单走人次口径并显示来源计数 ─────────────────

from tests.test_plugin_sign_daily import API, HEADERS, SCOPE, _ok, _rows, client  # noqa: E402,F401
from services.deliverable_form_analysis import build_form_snapshot  # noqa: E402


def test_generate_reports_source_counts_for_dual_source_snapshot(client):  # noqa: F811
    _, http, db, _today = client
    rows = _rows()
    positional = []
    for index, row in enumerate(rows):
        item = {"values": [row.get(h) for h in HEADERS], "sheetName": "Sheet1"}
        if index == 0:
            item["_sourceSystem"] = "ibom"
        positional.append(item)
    db.publish_deliverable_form_snapshot(build_form_snapshot(
        "tdc_data_model", positional, snapshot_at="2026-10-02T08:00:00Z", source_run_id=1, source="test"))
    report = _ok(http.post(f"{API}/generate", json=SCOPE))
    counts = report["sourceCounts"]
    assert counts["ibom"] == 1
    assert counts["tdc"] >= 1


def test_scan_dir_outside_roots_does_not_reveal_existence(tmp_path):
    module = importer()
    for outside in (tmp_path / "exists", tmp_path / "missing"):
        if outside.name == "exists":
            outside.mkdir()
        with pytest.raises(module.ManualImportError) as info:
            module.resolve_scan_dir(str(outside), default_dir=tmp_path / "allowed-root")
        assert info.value.code == "E_DIR_NOT_ALLOWED"
    allowed = tmp_path / "allowed-root"
    with pytest.raises(module.ManualImportError) as info:
        module.resolve_scan_dir(str(allowed / "nope"), default_dir=allowed)
    assert info.value.code == "E_DIR_MISSING"
