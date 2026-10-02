# -*- coding: utf-8 -*-
"""TASK-20260930-R7-G2：同步范围剔除共享实现与定时归档路径接线测试。

覆盖 services.scope_exclusion 的候选键序语义；定时归档路径（tdc_sor /
tdc_data_model / aras_paa）的 form_snapshot 行集剔除。同步路径的 collect
级测试见 tests/test_project_status_connectors.py。
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence
from xml.sax.saxutils import escape
from zipfile import ZipFile

from core.archive_store import ArchiveStore
from core.credential_provider import ResolvedCredential
from core.report_contracts import report_contracts
from services.scheduled_archive_connectors import (
    ArasArchiveConnector,
    TDCArchiveConnector,
)
from services.scheduled_archive_runner import ArchiveJobContext
from services.scope_exclusion import (
    exclude_paa_cancel_rows,
    exclude_tdc_scope_rows,
)


# ── 共享实现：候选键序语义 ──────────────────────────────────────────────────


def test_exclude_tdc_scope_rows_sor_key_sequence() -> None:
    """sor 候选键序：processInstanceStatus → approvalStatus → 审批状态，
    首个非空值命中；嵌套对象归一只取 name（不复制第二套归一口径）。"""
    rows = [
        {"processInstanceStatus": "已撤回"},  # 首选键
        {"approvalStatus": "已撤回"},  # 次选键回退
        {"审批状态": "已废弃"},  # 归档官方工作簿中文表头
        {"processInstanceStatus": None, "审批状态": "已废弃"},  # 首选键为空时回退
        {"processInstanceStatus": "已完成"},  # 保留
        {"processInstanceStatus": {"value": 3, "name": "已废弃"}},  # 嵌套对象防御
    ]
    kept, dropped = exclude_tdc_scope_rows("sor", rows)
    assert dropped == 5
    assert [row["processInstanceStatus"] for row in kept] == ["已完成"]


def test_exclude_tdc_scope_rows_data_model_text_column() -> None:
    """data_model 候选键序：status（数字码）→ 状态（归档文本列）；
    数字码与文本列共用同一剔除集，文本列 "已废弃" 剔除、"6" 透传不剔。"""
    rows = [{"status": "2"}, {"status": "4"}, {"状态": "已废弃"}, {"状态": "6"}]
    kept, dropped = exclude_tdc_scope_rows("data_model", rows)
    assert dropped == 1
    assert len(kept) == 3


def test_exclude_tdc_scope_rows_non_tdc_report_noop() -> None:
    """非 TDC 报表原样返回（丢弃数为 0），不读不剔。"""
    rows = [{"state": "已废弃"}]
    kept, dropped = exclude_tdc_scope_rows("ewo", rows)
    assert dropped == 0
    assert kept == rows


def test_exclude_paa_cancel_rows_variants() -> None:
    """PAA：CANCEL 大小写/空白变体一律命中，state 与 current_state__name
    任一命中即剔；其余状态值与无状态键行保留。"""
    rows = [
        {"state": "CANCEL"},
        {"state": "cancel"},
        {"state": " Cancel "},
        {"current_state__name": "cancel"},
        {"state": None, "current_state__name": "CANCEL"},
        {"state": "DRAFT1"},
        {"state": "CLOSE"},
        {"other": "CANCEL"},  # 无状态键 → 保留
    ]
    kept, dropped = exclude_paa_cancel_rows(rows)
    assert dropped == 5
    assert [row.get("state") for row in kept] == ["DRAFT1", "CLOSE", None]
    assert kept[2]["other"] == "CANCEL"


# ── 定时归档路径接线 ────────────────────────────────────────────────────────


class _FakeArchiveAuth:
    base_url = "https://fixed.example"

    def __init__(self, **kwargs: Any) -> None:
        pass

    def login(self, username: str, password: str) -> Any:
        return SimpleNamespace(session=object())


def _credential() -> ResolvedCredential:
    return ResolvedCredential(username=f"user_{secrets.token_hex(4)}", password="pass")


def _make_context(job_key: str, report_type: str) -> ArchiveJobContext:
    return ArchiveJobContext(
        job_id=1, job_key=job_key,
        source_type="tdc" if job_key.startswith("tdc") else "aras",
        report_type=report_type, filters={},
        output_subdir="scope", output_directory="", run_id=7,
    )


def _capture_emit(monkeypatch: Any) -> list[tuple[str, dict[str, Any], str]]:
    events: list[tuple[str, dict[str, Any], str]] = []
    monkeypatch.setattr(
        "services.scheduled_archive_connectors.emit",
        lambda kind, data=None, *, name="", exception=None: events.append(
            (kind, dict(data or {}), name)
        ),
    )
    return events


def _cell_ref(column: int, row: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return f"{result}{row}"


def _write_official_tdc_xlsx(
    path: Path,
    contract_key: str,
    value_rows: Sequence[Sequence[object]],
) -> None:
    """按 TDC 合同表头写一本可读的官方导出工作簿（通用 helper）。"""
    headers = report_contracts()[contract_key]["headerRows"][0]

    def row_xml(row_number: int, values: Sequence[object]) -> str:
        cells = "".join(
            f'<c r="{_cell_ref(index, row_number)}" t="inlineStr">'
            f"<is><t>{escape(str(value))}</t></is></c>"
            for index, value in enumerate(values, 1)
        )
        return f'<row r="{row_number}">{cells}</row>'

    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + row_xml(1, headers)
        + "".join(row_xml(number, values) for number, values in enumerate(value_rows, 2))
        + "</sheetData></worksheet>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class WorkbookExportTDC:
    """官方导出产出可读合同工作簿的 TDC 测试替身（按 contract_key 注入行）。"""

    def __init__(
        self,
        *,
        export_rows_by_contract: dict[str, list[list[object]]],
        session: Any = None,
        timeout: float | None = None,
        output_dir: Path | None = None,
        **kwargs: Any,
    ) -> None:
        self.output_dir = output_dir
        self._rows = export_rows_by_contract

    def _export(self, contract_key: str) -> Any:
        assert self.output_dir is not None
        path = self.output_dir / f"{contract_key}.xlsx"
        _write_official_tdc_xlsx(path, contract_key, self._rows[contract_key])
        return SimpleNamespace(
            path=path, file_name=path.name, byte_count=path.stat().st_size
        )

    def export_data_model(self, filters: Any) -> Any:
        return self._export("tdc_data_model")

    def export_sor(self, filters: Any) -> Any:
        return self._export("tdc_sor")


def _tdc_labeled_row(
    contract_key: str, labeled: dict[str, str]
) -> list[object]:
    headers = report_contracts()[contract_key]["headerRows"][0]
    return [labeled.get(str(header), "") for header in headers]


def test_archive_tdc_sor_form_rows_exclude_withdrawn(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """归档 tdc_sor：官方工作簿"审批状态"列 已撤回 剔除、已完成 保留；
    record_count 与 normalized 归档保持全量（原始取证=官方工作簿本体）。"""
    rows = [
        _tdc_labeled_row("tdc_sor", {"流水单号": "DOC-1", "审批状态": "已完成"}),
        _tdc_labeled_row("tdc_sor", {"流水单号": "DOC-2", "审批状态": "已撤回"}),
    ]
    connector = TDCArchiveConnector(
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=_FakeArchiveAuth,
        crawler_factory=lambda **kw: WorkbookExportTDC(
            export_rows_by_contract={"tdc_sor": rows}, **kw
        ),
    )
    events = _capture_emit(monkeypatch)

    collection = connector.collect(_make_context("tdc_sor", "sor"), _credential())

    assert collection.form_projection_error is None
    assert collection.record_count == 2  # 归档簿记保持全量
    assert [row["流水单号"] for row in collection.form_rows] == ["DOC-1"]
    assert collection.form_rows[0]["审批状态"] == "已完成"
    assert [(kind, data) for kind, data, _ in events] == [
        ("tdc_scope_exclusion", {"report_type": "sor", "kept_count": 1, "dropped_count": 1}),
    ]


def test_archive_tdc_data_model_form_rows_exclude_discarded(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """归档 data_model：官方工作簿"状态"文本列 已废弃 剔除、审批中/数字码
    文本保留（数字码映射语义保持现状，B 案另批）。"""
    rows = [
        _tdc_labeled_row("tdc_data_model", {"流水单号": "DOC-1", "状态": "已废弃"}),
        _tdc_labeled_row("tdc_data_model", {"流水单号": "DOC-2", "状态": "审批中"}),
        _tdc_labeled_row("tdc_data_model", {"流水单号": "DOC-3", "状态": "6"}),
    ]
    connector = TDCArchiveConnector(
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=_FakeArchiveAuth,
        crawler_factory=lambda **kw: WorkbookExportTDC(
            export_rows_by_contract={"tdc_data_model": rows}, **kw
        ),
    )
    events = _capture_emit(monkeypatch)

    collection = connector.collect(
        _make_context("tdc_data_model", "data_model"), _credential()
    )

    assert collection.form_projection_error is None
    assert collection.record_count == 3
    assert [row["流水单号"] for row in collection.form_rows] == ["DOC-2", "DOC-3"]
    assert [(kind, data) for kind, data, _ in events] == [
        ("tdc_scope_exclusion", {"report_type": "data_model", "kept_count": 2, "dropped_count": 1}),
    ]


def test_archive_aras_paa_form_rows_exclude_cancel(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """归档 aras_paa：CANCEL 变体行不进 form_rows；normalized 归档保持全量
    （PAA 归档没有官方工作簿，normalized 产物即原始取证）。"""
    crawl_rows = (
        {"_no": "PAA-DROP-1", "state": "CANCEL"},
        {"_no": "PAA-DROP-2", "state": "cancel "},
        {"_no": "PAA-DROP-3", "current_state__name": " Cancel "},
        {"_no": "PAA-KEEP-1", "state": "DRAFT1"},
        {"_no": "PAA-KEEP-2", "state": "CLOSE"},
    )

    class PaaAras:
        def __init__(self, base_url: str, session: Any = None, timeout: float | None = None, prewarm: bool = False) -> None:
            pass

        def crawl_paa_report_all(self, filters: Any, max_records: int) -> Any:
            return SimpleNamespace(rows=crawl_rows)

    connector = ArasArchiveConnector(
        ArchiveStore({"default": tmp_path}, reserve_bytes=0),
        auth_factory=_FakeArchiveAuth,
        crawler_factory=PaaAras,
    )
    events = _capture_emit(monkeypatch)

    collection = connector.collect(_make_context("aras_paa", "paa"), _credential())

    assert collection.record_count == 5  # 归档簿记与 normalized 产物保持全量
    assert [row["_no"] for row in collection.form_rows] == ["PAA-KEEP-1", "PAA-KEEP-2"]
    assert [(kind, data) for kind, data, _ in events] == [
        ("aras_scope_exclusion", {"report_type": "paa", "kept_count": 2, "dropped_count": 3}),
    ]
    json_artifacts = [
        artifact
        for artifact in collection.artifacts
        if artifact.artifact_type == "normalized_json"
    ]
    payload = json.loads(
        (tmp_path / json_artifacts[0].relative_path).read_text(encoding="utf-8")
    )
    assert sorted(row["_no"] for row in payload) == [
        "PAA-DROP-1", "PAA-DROP-2", "PAA-DROP-3", "PAA-KEEP-1", "PAA-KEEP-2",
    ]
