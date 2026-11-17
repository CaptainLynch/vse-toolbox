# -*- coding: utf-8 -*-
"""TIR数据简表「同日复用」条件：复用键隔离与产物完整性（走真实服务调用链）。

覆盖 DSH-V2-24 的验收：

1. 同一导出日、同一组筛选 → 命中复用，且不再访问报表平台；
2. 换项目、换车型（多项目环境各项目一个数据根）、换筛选、换导出日 → 一律不复用；
3. 产物被删除、被改写（同大小 / 大小不符）、记录缺校验字段 → 不返回 ``reused=True``，
   按正常路径重新导出，且不删除既有文件。

假会话只重放协议形态的**合成**响应（账号、口令、token、sessionID 都是测试占位值），不发真实网络请求，
不启动 Excel COM；落盘走真实 ``ArchiveStore``。
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from core.archive_store import ArchiveStore
from core.credential_provider import ResolvedCredential
from core.domain_identity import DPAPICredentialProvider
from plugins.tir_report import protocol as P
from plugins.tir_report import service as S

TODAY = date(2026, 10, 9)
NEXT_DAY = date(2026, 10, 10)
USER = "tester-account"
PASSWORD = "Pa55-word-for-tests"
TOKEN = "test-access-token-0123456789"
SESSION_ID = "11111111-2222-3333-4444-555555555555"
HOST = "https://report.example.test"
DOMAIN_USER = f"SGMW\\{USER}"


# ── 假数据源（FineReport 10 形态，纯合成） ────────────────────────────


def _sample_xlsx(rows: list[list[str]]) -> bytes:
    """A tiny valid workbook standing in for FineReport's own export (inline strings, one sheet)."""
    def cell(r: int, c: int, value: str) -> str:
        col = ""
        n = c + 1
        while n:
            n, rem = divmod(n - 1, 26)
            col = chr(65 + rem) + col
        return f'<c r="{col}{r}" t="inlineStr"><is><t>{value}</t></is></c>'

    sheet_rows = "".join(f'<row r="{r}">' + "".join(cell(r, c, v) for c, v in enumerate(row)) + "</row>"
                         for r, row in enumerate(rows, start=1))
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/></Types>')
        archive.writestr("_rels/.rels", f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
                         f'Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
                         '<sheet name="sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
                         f'Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml",
                         f'<worksheet xmlns="{main}"><sheetData>{sheet_rows}</sheetData></worksheet>')
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status: int, body: bytes | str, content_type: str = "text/html;charset=UTF-8") -> None:
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": content_type}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


def _content_html(rows: list[list[str]]) -> str:
    """Mimic ``read_w_content``: title row 0, then header + data rows by (row, col)."""
    trs = ['<tr><td col="0" row="0">车体工程</td></tr>']
    for r_index, row in enumerate(rows, start=1):
        tds = "".join(f'<td col="{c}" row="{r_index}"><div heavytd="light">{value}</div></td>'
                      for c, value in enumerate(row))
        trs.append(f"<tr>{tds}</tr>")
    return ('<table class="x-table">' + "".join(trs) + "</table>"
            "<script>FR._p.lgps[0].reportTotalPage=0;</script>")


DATA_ROWS = [[f"A{n}" if i == 0 else f"v{n}-{i}" for i in range(len(P.EXPECTED_HEADERS))] for n in range(1, 3)]


class FakeFineReport:
    """Records each call and answers like FineReport 10; never touches the network."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        self.calls: list[dict] = []
        self.xlsx = _sample_xlsx([list(P.EXPECTED_HEADERS)] + DATA_ROWS)

    def set_cookies(self, cookies, url):  # type: ignore[no-untyped-def]
        self.cookies.update(cookies)

    def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return self._handle("GET", url, kwargs)

    def post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return self._handle("POST", url, kwargs)

    def _handle(self, method, url, kwargs):  # type: ignore[no-untyped-def]
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        self.calls.append({"method": method, "path": parts.path, "query": query})
        path = parts.path.removeprefix(P.BASE_PATH)
        if path == "/login" and method == "GET":
            return FakeResponse(200, "<html><script>var Dec={encryptionKey:''}</script></html>")
        if path == "/login":
            return FakeResponse(200, json.dumps({"data": {"accessToken": TOKEN, "username": USER}}),
                                "application/json")
        if path.startswith("/v10/entry/access/"):
            return FakeResponse(200, f"<html><script>FR.SessionMgr.register('{SESSION_ID}', x);</script></html>")
        if path == "/view/report" and query.get("cmd") == "parameters_d":
            return FakeResponse(200, '{"status":"success"}')
        if path == "/view/report" and query.get("cmd") == "read_w_content":
            payload = {"outputMode": "STREAM_JSON",
                       "html": _content_html([list(P.EXPECTED_HEADERS)] + DATA_ROWS)}
            return FakeResponse(200, json.dumps(payload, ensure_ascii=False), "application/json;charset=UTF-8")
        if path == "/export/check/font":
            return FakeResponse(200, '{"state":1}')
        if path == "/view/report" and query.get("op") == "export":
            response = FakeResponse(200, self.xlsx, "application/x-excel")
            response.headers["Content-Disposition"] = (
                "attachment; filename*=UTF-8''TIR%E6%95%B0%E6%8D%AE%E7%AE%80%E8%A1%A8.xlsx")
            return response
        if path == "/view/report" and "export_polling" in str(kwargs.get("data")):
            return FakeResponse(200, '{"isExporting":false}\n')
        return FakeResponse(404, "not found")


class FakeVault:
    """Stands in for the host's DPAPI domain vault (WindowsDPAPICredentialVault)."""

    def is_configured(self) -> bool:
        return True

    @contextmanager
    def resolve(self):  # type: ignore[no-untyped-def]
        value = ResolvedCredential(username=DOMAIN_USER, password=PASSWORD)
        try:
            yield value
        finally:
            value.clear()


def _domain() -> DPAPICredentialProvider:
    return DPAPICredentialProvider(FakeVault())


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore({"default": tmp_path / "archive"})


def _filters(**overrides) -> P.ExportFilters:  # type: ignore[no-untyped-def]
    raw = {"project": "F610S", "department": "车体工程", "section": "", "startDate": "2022-07-11",
           "endDate": "2026-10-09", **overrides}
    return P.normalize_filters(raw, today=TODAY)


def _run(tmp_path: Path, fake: FakeFineReport, filters: P.ExportFilters | None = None, *,
         store: ArchiveStore | None = None, today: date = TODAY, force: bool = False) -> dict:
    return S.run_export(
        filters or _filters(), data_dir=tmp_path, store=store or _store(tmp_path),
        credential_provider=_domain(), session_factory=lambda: fake, today=today,
        base_url=HOST, sleep=lambda seconds: None, force=force,
    )


def _artifact(tmp_path: Path, meta: dict) -> Path:
    return tmp_path / "archive" / meta["relativePath"]


def _record_path(tmp_path: Path, meta: dict, day: str = "2026-10-09") -> Path:
    return tmp_path / "runs" / day / f"{meta['stem']}.json"


def _rewrite_record(path: Path, **changes) -> None:  # type: ignore[no-untyped-def]
    record = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            record.pop(key, None)
        else:
            record[key] = value
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


# ── 复用键组成 ──────────────────────────────────────────────────────


def test_cache_key_and_stem_cover_project_department_section_and_dates():
    base = _filters()
    variants = [_filters(project="F620S"), _filters(department="底盘工程"), _filters(section="车身科"),
                _filters(startDate="2022-07-12"), _filters(endDate="2026-10-08")]
    keys = [base.cache_key(), *(item.cache_key() for item in variants)]
    stems = [S.file_stem(base), *(S.file_stem(item) for item in variants)]
    assert len(set(keys)) == len(keys) == 6
    assert len(set(stems)) == len(stems) == 6
    assert base.cache_key() == "F610S|车体工程||2022-07-11|2026-10-09"
    assert stems[0].startswith("tir_F610S_20220711-20261009_")
    assert stems[1].startswith("tir_F620S_20220711-20261009_")


def test_run_record_carries_the_whole_reuse_key(tmp_path: Path):
    meta = _run(tmp_path, FakeFineReport())
    record = json.loads(_record_path(tmp_path, meta).read_text(encoding="utf-8"))
    artifact = _artifact(tmp_path, meta)
    assert record["day"] == "2026-10-09" and record["stem"] == S.file_stem(_filters())
    assert record["filters"] == _filters().as_payload() and record["filters"]["project"] == "F610S"
    assert record["bytes"] == artifact.stat().st_size > 0
    assert record["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert record["sha256"] == meta["sha256"]


# ── 命中复用 ────────────────────────────────────────────────────────


def test_same_day_same_filters_reuses_without_calling_the_platform(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    assert first["reused"] is False and first["day"] == "2026-10-09"

    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is True and fake.calls == []  # 不重新登录、不重新导出
    assert (again["stem"], again["relativePath"], again["sha256"], again["rows"]) == (
        first["stem"], first["relativePath"], first["sha256"], first["rows"])
    assert again["runId"] == first["runId"]
    assert len(list((tmp_path / "archive").rglob("*.xlsx"))) == 1  # 复用不产生第二份产物

    cached = S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters())
    assert cached is not None and cached["day"] == "2026-10-09" and cached["ok"] is True


def test_force_reexports_even_when_the_artifact_is_intact(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    fake = FakeFineReport()
    forced = _run(tmp_path, fake, force=True)
    assert forced["reused"] is False and fake.calls
    assert forced["runId"] == first["runId"] + 1
    assert len(list((tmp_path / "archive").rglob("*.xlsx"))) == 2


# ── 项目/车型/筛选/日期隔离 ──────────────────────────────────────────


@pytest.mark.parametrize("overrides", [
    {"project": "F620S"},
    {"department": "底盘工程"},
    {"section": "车身科"},
    {"startDate": "2022-07-12"},
    {"endDate": "2026-10-08"},
])
def test_other_filters_do_not_reuse(tmp_path: Path, overrides: dict):
    first = _run(tmp_path, FakeFineReport())
    fake = FakeFineReport()
    second = _run(tmp_path, fake, _filters(**overrides))
    assert second["reused"] is False and fake.calls
    assert second["stem"] != first["stem"]
    assert second["relativePath"] != first["relativePath"]
    assert len(list((tmp_path / "archive").rglob("*.xlsx"))) == 2  # 两份产物各自留存


def test_another_project_data_root_does_not_reuse_the_same_filters(tmp_path: Path):
    """换车型 = 换项目：车型是项目属性，多项目环境一个项目一个数据根，归档根可能被共用。

    同一组筛选在另一个项目的数据根里没有记录，必须重新导出，不能拿别的项目的产物当当天结果。
    """
    store = _store(tmp_path)
    project_a, project_b = tmp_path / "projects" / "p1", tmp_path / "projects" / "p2"
    first = _run(project_a, FakeFineReport(), store=store)
    fake = FakeFineReport()
    second = _run(project_b, fake, store=store)
    assert first["reused"] is False and second["reused"] is False and fake.calls
    assert S.find_cached(project_a, store, "2026-10-09", _filters()) is not None
    assert S.find_cached(project_b, store, "2026-10-09", _filters()) is not None
    assert len(list((tmp_path / "archive").rglob("*.xlsx"))) == 2


@pytest.mark.parametrize("field, value", [
    ("project", "F620S"),
    ("department", "底盘工程"),
    ("section", "车身科"),
    ("startDate", "2022-07-12"),
    ("endDate", "2026-10-08"),
])
def test_record_for_another_filter_set_is_not_reused(tmp_path: Path, field: str, value: str):
    """记录里的 filters 与本次请求不一致（旧记录/手改/复用键组成变化）时不得复用。"""
    meta = _run(tmp_path, FakeFineReport())
    record_path = _record_path(tmp_path, meta)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    _rewrite_record(record_path, filters={**record["filters"], field: value})

    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is False and fake.calls


def test_record_from_another_export_day_is_not_reused(tmp_path: Path):
    meta = _run(tmp_path, FakeFineReport())
    copied = _record_path(tmp_path, meta, day="2026-10-10")
    copied.parent.mkdir(parents=True)
    copied.write_text(_record_path(tmp_path, meta).read_text(encoding="utf-8"), encoding="utf-8")

    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-10", _filters()) is None
    fake = FakeFineReport()
    again = _run(tmp_path, fake, today=NEXT_DAY)
    assert again["reused"] is False and fake.calls and again["day"] == "2026-10-10"


def test_next_export_day_does_not_reuse_yesterday(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    fake = FakeFineReport()
    second = _run(tmp_path, fake, today=NEXT_DAY)
    assert second["reused"] is False and fake.calls
    assert second["stem"] == first["stem"] and second["day"] == "2026-10-10"


# ── 产物完整性：删除/篡改/大小不符/记录缺校验 ────────────────────────


def test_deleted_artifact_is_reexported_instead_of_reused(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    artifact = _artifact(tmp_path, first)
    artifact.unlink()

    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is False and fake.calls
    assert again["runId"] == first["runId"] + 1 and again["relativePath"] != first["relativePath"]
    assert _artifact(tmp_path, again).is_file()
    assert (tmp_path / "archive" / first["manifestPath"]).is_file()  # 别的文件不动


def test_tampered_artifact_with_the_same_size_is_not_reused(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    artifact = _artifact(tmp_path, first)
    flipped = bytearray(artifact.read_bytes())
    flipped[len(flipped) // 2] ^= 0xFF
    artifact.write_bytes(bytes(flipped))
    assert artifact.stat().st_size == first["bytes"]  # 大小没变，只有 sha256 变了

    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is False and fake.calls
    assert again["runId"] == first["runId"] + 1
    assert again["sha256"] == hashlib.sha256(fake.xlsx).hexdigest()  # 记录指向重新导出的产物
    assert _artifact(tmp_path, again).read_bytes() == fake.xlsx
    assert artifact.read_bytes() == bytes(flipped)  # 被篡改的旧产物不删、不改写


@pytest.mark.parametrize("mutation", ["append", "truncate", "empty"])
def test_artifact_with_a_different_size_is_not_reused(tmp_path: Path, mutation: str):
    first = _run(tmp_path, FakeFineReport())
    artifact = _artifact(tmp_path, first)
    content = artifact.read_bytes()
    artifact.write_bytes({"append": content + b"tampered-bytes",
                          "truncate": content[:-64],
                          "empty": b""}[mutation])

    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is False and fake.calls
    assert _artifact(tmp_path, again).read_bytes() == fake.xlsx


@pytest.mark.parametrize("changes", [
    {"sha256": None},
    {"bytes": None},
    {"sha256": "not-a-digest"},
    {"bytes": "1136"},
    {"bytes": 0},
    {"sha256": "0" * 64},
])
def test_record_without_usable_integrity_fields_is_not_reused(tmp_path: Path, changes: dict):
    meta = _run(tmp_path, FakeFineReport())
    _rewrite_record(_record_path(tmp_path, meta), **changes)

    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is False and fake.calls
    assert _artifact(tmp_path, again).is_file()


def test_artifact_outside_the_archive_root_is_not_reused(tmp_path: Path):
    meta = _run(tmp_path, FakeFineReport())
    _rewrite_record(_record_path(tmp_path, meta), relativePath="../runs/run-seq.json")
    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None


# ── 计划任务：产物被改写时当天重跑 ──────────────────────────────────


def test_scheduled_export_reruns_when_the_artifact_was_tampered(tmp_path: Path):
    config = S.default_config()
    config["auto"] = {"enabled": True, "hour": 8}
    S.save_config(tmp_path, config)
    store = _store(tmp_path)
    fake = FakeFineReport()
    first = S.run_auto(tmp_path, now=datetime(2026, 10, 9, 8, 5), store=store, credential_provider=_domain(),
                       session_factory=lambda: fake, base_url=HOST, sleep=lambda seconds: None)
    assert first["status"] == "ok"
    later = datetime(2026, 10, 9, 9, 5)
    assert S.auto_decision(config, S.load_auto_state(tmp_path), later, tmp_path, store) == "done"

    artifact = tmp_path / "archive" / first["relativePath"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    assert S.auto_decision(config, S.load_auto_state(tmp_path), later, tmp_path, store) == "run"

    rerun = S.run_auto(tmp_path, now=later, store=store, credential_provider=_domain(),
                       session_factory=FakeFineReport, base_url=HOST, sleep=lambda seconds: None)
    assert rerun["status"] == "ok" and rerun["attempts"] == 2
    assert artifact.read_bytes().endswith(b"tampered")  # 旧文件保留，新结果另存
    assert len(list((tmp_path / "archive").rglob("*.xlsx"))) == 2
