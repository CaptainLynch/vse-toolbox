"""EWO 111 列 CSV 导出编排的离线契约（假列表/假 transport + 合成工作簿）。"""
import hashlib
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest

from core.ewo_export_jobs import EWOExportJobs
from services.ewo_csv_export import EwoCsvExportError, EwoExportDeps, run_official_export
from services.ewo_official_rows import contract_labels

HEADER = contract_labels()
ID_A = "A" * 32
ID_B = "B" * 32


def _column_letters(index: int) -> str:
    letters = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def write_workbook(path: Path, headers, rows) -> Path:
    strings: list[str] = []
    lookup: dict[str, int] = {}

    def sid(text: str) -> int:
        if text not in lookup:
            lookup[text] = len(strings)
            strings.append(text)
        return lookup[text]

    sheet_rows = []
    for row_index, values in enumerate([list(headers)] + [list(row) for row in rows], start=1):
        cells = []
        for column, value in enumerate(values):
            if value is None or str(value) == "":
                continue
            reference = f"{_column_letters(column)}{row_index}"
            cells.append(f'<c r="{reference}" t="s"><v>{sid(str(value))}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Innovator" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">'
        + "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
        + "</sst>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


class FakeCrawler:
    def __init__(self, rows, ids, *, complete=True, truncated=False):
        self.rows = rows
        self.ids = ids
        self.complete = complete
        self.truncated = truncated
        self.calls = 0

    def crawl_ewo_report_all(self, filters=None, **kwargs):
        self.calls += 1
        return SimpleNamespace(rows=self.rows, item_ids=self.ids,
                               complete=self.complete, truncated=self.truncated)


class FakeTransport:
    def __init__(self, workbook_factory, *, download_error=None):
        self.workbook_factory = workbook_factory
        self.download_error = download_error
        self.generate_calls = 0
        self.download_calls = 0
        self.on_generate = None

    def generate(self, ids):
        self.generate_calls += 1
        if self.on_generate is not None:
            self.on_generate(ids)
        return ID_B

    def download(self, file_id, destination):
        self.download_calls += 1
        if self.download_error is not None:
            raise self.download_error
        return self.workbook_factory(Path(destination))


def build(tmp_path, *, download_error=None):
    jobs = EWOExportJobs(tmp_path / "jobs.db")
    crawler = FakeCrawler([{"id": ID_A, "_no": "E-1"}], [ID_A])
    transport = FakeTransport(lambda folder: write_workbook(
        folder / "official.xlsx", HEADER,
        [["E-1"] + [f"{label}|E-1" for label in HEADER[1:]]],
    ), download_error=download_error)
    deps = EwoExportDeps(jobs=jobs, crawler=crawler, transport=transport,
                         downloads_dir=tmp_path / "ewo-downloads")
    job = jobs.create("scope-a", [ID_A], purpose="csv_export")
    return deps, job, crawler, transport


def test_official_export_writes_all_111_columns(tmp_path):
    deps, job, crawler, transport = build(tmp_path)
    state = run_official_export(job["id"], "scope-a", deps)
    assert state["state"] == "exported"
    assert state["row_count"] == 1
    target = deps.downloads_dir / state["artifact_path"]
    assert target.is_file()
    content = target.read_bytes()
    assert content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    assert hashlib.sha256(content).hexdigest() == state["artifact_sha256"]
    header_line = content.decode("utf-8-sig").splitlines()[0]
    assert header_line.split(",") == HEADER
    data_line = content.decode("utf-8-sig").splitlines()[1].split(",")
    assert data_line[0] == "E-1"
    # 第 58 列起必须来自官方工作簿，不能是空值
    assert data_line[57] == f"{HEADER[57]}|E-1"
    assert data_line[-1] == f"{HEADER[-1]}|E-1"
    assert crawler.calls == 1
    assert transport.generate_calls == 1
    assert transport.download_calls == 1


def test_generation_state_is_committed_before_calling_transport(tmp_path):
    """P0-1：调用服务端生成之前，库中必须已经是 generating（否则崩溃后会被判可重试）。"""
    deps, job, _, transport = build(tmp_path)
    seen = {}

    def probe(_ids):
        with sqlite3.connect(deps.jobs.path) as conn:
            seen["state"] = conn.execute(
                "SELECT state FROM ewo_export_jobs WHERE id=?", (job["id"],)
            ).fetchone()[0]

    transport.on_generate = probe
    run_official_export(job["id"], "scope-a", deps)
    assert seen["state"] == "generating"


def test_incomplete_listing_never_calls_generation(tmp_path):
    deps, job, crawler, transport = build(tmp_path)
    crawler.complete = False
    with pytest.raises(EwoCsvExportError):
        run_official_export(job["id"], "scope-a", deps)
    assert transport.generate_calls == 0
    row = deps.jobs.get(job["id"], "scope-a")
    assert row["state"] == "export_failed"
    assert row["error_code"] == "E_LIST_INCOMPLETE"
    assert deps.jobs.decide_retry(job["id"]) == "new_job"


def test_header_gate_failure_marks_export_failed_without_file(tmp_path):
    deps, job, _, _ = build(tmp_path)
    # 必需表头齐全（能通过读取器），但第 58 列与契约不符 → 契约门禁失败。
    drifted = list(HEADER)
    drifted[57] = "错误的基地汇总"
    deps.transport.workbook_factory = lambda folder: write_workbook(
        folder / "bad.xlsx", drifted, [["E-1"] * 111],
    )
    with pytest.raises(Exception):
        run_official_export(job["id"], "scope-a", deps)
    row = deps.jobs.get(job["id"], "scope-a")
    assert row["state"] == "export_failed"
    assert row["error_code"] == "E_HEADER_MISMATCH"
    assert not (deps.downloads_dir / f"ewo_export_{job['id']}.csv").exists()
    assert deps.jobs.decide_retry(job["id"]) == "forbidden"


def test_download_failure_returns_to_generated_and_resumes_without_regenerating(tmp_path):
    deps, job, _, transport = build(tmp_path, download_error=OSError("network down"))
    with pytest.raises(OSError):
        run_official_export(job["id"], "scope-a", deps)
    row = deps.jobs.get(job["id"], "scope-a")
    assert row["state"] == "generated"
    assert transport.generate_calls == 1
    # 恢复网络后重跑：只续下载，不重新生成
    transport.download_error = None
    state = run_official_export(job["id"], "scope-a", deps)
    assert state["state"] == "exported"
    assert transport.generate_calls == 1
    assert transport.download_calls == 2


def test_cancel_during_generation_lands_cancelled_not_retryable(tmp_path):
    deps, job, _, transport = build(tmp_path)

    def cancel(_ids):
        deps.jobs.cancel(job["id"], "scope-a")

    transport.on_generate = cancel
    state = run_official_export(job["id"], "scope-a", deps)
    assert state["state"] == "cancelled"
    assert transport.generate_calls == 1
    assert deps.jobs.decide_retry(job["id"]) == "forbidden"


def test_reconcile_mismatch_marks_export_failed(tmp_path):
    deps, job, _, _ = build(tmp_path)
    deps.transport.workbook_factory = lambda folder: write_workbook(
        folder / "other.xlsx", HEADER,
        [["E-999"] + [f"{label}|E-999" for label in HEADER[1:]]],
    )
    with pytest.raises(Exception):
        run_official_export(job["id"], "scope-a", deps)
    row = deps.jobs.get(job["id"], "scope-a")
    assert row["state"] == "export_failed"
    assert row["error_code"] == "E_RECONCILE_MISMATCH"
