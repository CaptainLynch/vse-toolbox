# -*- coding: utf-8 -*-
"""Offline contract tests for the tir-report plugin (FineReport TIR数据简表 export).

假会话按方案 §2 的协议形态重放**合成**响应：fixture 里的账号、口令、token、sessionID 都是测试占位值，
不含任何来自真实 HAR 的数据；不发真实网络请求。交付物只有帆软原样导出的 xlsx（不产出 HAR、不自建表格）。
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import time
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import web.app as web_app
from contextlib import contextmanager
from datetime import datetime

from core.archive_store import ArchiveStore
from core.credential_provider import ResolvedCredential
from core.domain_identity import CredentialVaultError, DPAPICredentialProvider
from plugins.tir_report import protocol as P
from plugins.tir_report import service as S
from plugins.tir_report.client import FineReportClient, TirError
from services.xlsx_preview import read_xlsx_preview

PLUGINS_ROOT = Path(__file__).resolve().parent.parent / "plugins"
TODAY = date(2026, 10, 9)
USER = "tester-account"
PASSWORD = "Pa55-word-for-tests"
TOKEN = "test-access-token-0123456789"
SESSION_ID = "11111111-2222-3333-4444-555555555555"
HOST = "https://report.example.test"
DOMAIN_USER = f"SGMW\\{USER}"  # 域账号库里可能带域前缀；帆软用不带前缀的工号


# ── 假会话 ──────────────────────────────────────────────────────────


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
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main}"><sheetData>{sheet_rows}</sheetData></worksheet>')
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status: int, body: bytes | str, content_type: str = "text/html;charset=UTF-8") -> None:
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": content_type}

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


def _content_html(rows: list[list[str]], *, hidden_col: int = 14) -> str:
    """Mimic read_w_content: title row 0, header row 1, a hidden empty column, an unclosed <td/>, frozen dupes."""
    trs = ['<tr><td col="0" row="0">车体工程</td></tr>']
    for r_index, row in enumerate(rows, start=1):
        cells = list(row[:hidden_col]) + [""] + list(row[hidden_col:])
        tds = []
        for c_index, value in enumerate(cells):
            if c_index == hidden_col:
                tds.append(f'<td col="{c_index}" row="{r_index}" class="x"/>')  # 不闭合
                continue
            tds.append(f'<td col="{c_index}" row="{r_index}" cv="x"><div heavytd="light">{value}</div></td>')
        trs.append("<tr>" + "".join(tds) + "</tr>")
    frozen = f'<table class="frozen-table"><tr><td col="0" row="1"></td></tr></table>'
    script = "<script>FR._p.lgps[0].reportTotalPage=0;</script>"
    return frozen + '<table class="x-table">' + "".join(trs) + "</table>" + script


DATA_ROWS = [
    [f"A{n}" if i == 0 else ("1" if i == 1 else f"v{n}-{i}") for i in range(len(P.EXPECTED_HEADERS))]
    for n in range(1, 4)
]


class FakeFineReport:
    """Records each call and answers like FineReport 10."""

    def __init__(self, *, public_key: bytes | None = None, export_xlsx: bool = True,
                 login_ok: bool = True, expire_session_once: bool = False) -> None:
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        self.calls: list[dict] = []
        self.public_key = public_key
        self.export_xlsx = export_xlsx
        self.login_ok = login_ok
        self.expire_session_once = expire_session_once
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
        headers = {**self.headers, **(kwargs.get("headers") or {})}
        data = kwargs.get("data")
        self.calls.append({"method": method, "path": parts.path, "query": query, "headers": headers, "data": data})
        path = parts.path.removeprefix(P.BASE_PATH)
        if path == "/login" and method == "GET":
            key = self.public_key.decode() if self.public_key else ""
            return FakeResponse(200, f"<html><script>var Dec={{encryptionKey:'{key}'}}</script></html>")
        if path == "/login":
            if not self.login_ok:
                return FakeResponse(200, json.dumps({"errorCode": "21300007", "errorMsg": f"{USER} 密码错误"}),
                                    "application/json")
            return FakeResponse(200, json.dumps({"data": {"accessToken": TOKEN, "username": USER}}), "application/json")
        if path.startswith("/v10/entry/access/"):
            if self.expire_session_once:
                self.expire_session_once = False
                return FakeResponse(200, '<html><a href="/webroot/decision/login">login</a></html>')
            assert headers.get("Authorization") == f"Bearer {TOKEN}"
            return FakeResponse(200, f"<html><script>FR.SessionMgr.register('{SESSION_ID}', x);</script></html>")
        if path == "/view/report" and query.get("cmd") == "parameters_d":
            return FakeResponse(200, '{"status":"success"}')
        if path == "/view/report" and query.get("cmd") == "read_w_content":
            payload = {"outputMode": "STREAM_JSON", "html": _content_html([list(P.EXPECTED_HEADERS)] + DATA_ROWS),
                       "watermark": {"text": f"{USER}2026-10-09 20:18:34"}}
            return FakeResponse(200, json.dumps(payload, ensure_ascii=False), "application/json;charset=UTF-8")
        if path == "/export/check/font":
            return FakeResponse(200, '{"state":1}')
        if path == "/view/report" and query.get("op") == "export":
            if self.export_xlsx:
                response = FakeResponse(200, self.xlsx, "application/x-excel")
                response.headers["Content-Disposition"] = (
                    "attachment; filename*=UTF-8''TIR%E6%95%B0%E6%8D%AE%E7%AE%80%E8%A1%A8.xlsx")
                return response
            return FakeResponse(200, "<html>export disabled</html>")
        if path == "/view/report" and "export_polling" in str(data):
            return FakeResponse(200, '{"isExporting":false}\n')
        return FakeResponse(404, "not found")

    def step_paths(self) -> list[str]:
        out = []
        for call in self.calls:
            label = call["path"].removeprefix(P.BASE_PATH)
            if call["query"].get("cmd"):
                label += f"?{call['query']['cmd']}"
            elif call["query"].get("op"):
                label += f"?{call['query']['op']}"
            elif call["data"] and "export_polling" in str(call["data"]):
                label += "?export_polling"
            out.append(f"{call['method']} {label}")
        return out


def _rsa_pair():  # type: ignore[no-untyped-def]
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, base64.b64encode(der)


def _filters() -> P.ExportFilters:
    return P.normalize_filters({"project": "F610S", "department": "车体工程", "startDate": "2022-07-11",
                                "endDate": "2026-10-09"}, today=TODAY)


# ── 协议纯函数 ──────────────────────────────────────────────────────


def test_cjk_encode_matches_finereport_form():
    assert P.cjk_encode("问题") == "[95ee][9898]"
    assert P.cjk_encode("故障报告编号") == "[6545][969c][62a5][544a][7f16][53f7]"
    assert P.cjk_encode('{"SFSJGXM":[]}') == '{"SFSJGXM":[5b][5d]}'
    assert P.cjk_decode(P.cjk_encode("车体工程 F610S [x]")) == "车体工程 F610S [x]"


def test_parameters_contract_key_order_and_encoding():
    params = P.build_parameters(_filters())
    keys = list(params)
    assert keys[:4] == ["LABELWTZT", "LABELGB6/6SJ", "ZRGCS", "LABELZRGCS"] and keys[-1] == "SSJGPT"
    assert len(keys) == 44 and sum(k.startswith("LABEL") for k in keys) == 22
    assert (params["XM"], params["BM"], params["KS"]) == ("F610S", "车体工程", "")
    assert (params["STARTTIME"], params["ENDTIME"]) == ("2022-07-11", "2026-10-09")
    assert params["SFSJGXM"] == [] and params["LABELBM"] == "部门"
    encoded = P.encode_parameters(params)
    assert all(ord(ch) < 0x80 for ch in encoded)
    assert '"BM":"[8f66][4f53][5de5][7a0b]"' in encoded and '"SFSJGXM":[5b][5d]' in encoded
    body = P.parameters_form(params, 1791548303795)
    field, _, value = body.partition("&")[0].partition("=")
    assert field == "__parameters__"
    assert value.startswith("%7B%22LABELWTZT%22%3A%22%5B95ee%5D%5B9898%5D")  # 与浏览器同形
    assert P.decode_parameters(unquote(value)) == params


def test_multi_value_and_extra_filters():
    params = P.build_parameters(_filters(), {"status": ["已关闭", "处理中"], "grade": "A"})
    assert params["WTZT"] == "已关闭','处理中" and params["DJ"] == "A"
    with pytest.raises(P.ProtocolError):
        P.build_parameters(_filters(), {"unknown": "x"})


@pytest.mark.parametrize("raw, message", [
    ({"startDate": "2026/10/01"}, "YYYY-MM-DD"),
    ({"startDate": "2026-02-30"}, "有效日期"),
    ({"startDate": "2026-10-10", "endDate": "2026-10-09"}, "不能晚于"),
    ({"department": "x" * 300}, "无效"),
])
def test_normalize_filters_rejects_bad_input(raw, message):  # type: ignore[no-untyped-def]
    with pytest.raises(P.ProtocolError, match=message):
        P.normalize_filters(raw, today=TODAY)


def test_normalize_filters_defaults_end_to_today():
    filters = P.normalize_filters({}, today=TODAY)
    assert filters.as_payload() == {"project": "", "department": "车体工程", "section": "",
                                    "startDate": "2022-07-11", "endDate": "2026-10-09"}


def test_parse_content_page_handles_hidden_column_unclosed_td_and_title_row():
    rows, total = P.parse_content_page({"html": _content_html([list(P.EXPECTED_HEADERS)] + DATA_ROWS)})
    assert total == 0
    table = P.table_from_pages([rows])
    assert tuple(table[0]) == P.EXPECTED_HEADERS and len(table) == 4
    assert table[1][0] == "A1" and all(len(row) == 50 for row in table)
    with pytest.raises(P.ProtocolError):
        P.table_from_pages([[["无关"]]])


def test_session_id_and_public_key_parsing():
    assert P.parse_session_id(f"FR.SessionMgr.register('{SESSION_ID}')") == SESSION_ID
    assert P.parse_session_id(f'var currentSessionID = "{SESSION_ID}";') == SESSION_ID
    with pytest.raises(P.ProtocolError):
        P.parse_session_id("<html></html>")
    _, der = _rsa_pair()
    assert P.find_public_key(f"x='{der.decode()}'").startswith(b"-----BEGIN PUBLIC KEY-----")
    assert P.find_public_key("<html>no key</html>") is None


# ── 客户端链路 ──────────────────────────────────────────────────────


EXPECTED_SEQUENCE = [
    "GET /login", "POST /login", f"GET /v10/entry/access/{P.ENTRY_ID}", "POST /view/report?parameters_d",
    "GET /view/report?read_w_content", "POST /export/check/font", "GET /view/report?export",
    "POST /view/report?export_polling",
]


def _client(fake: FakeFineReport) -> FineReportClient:
    return FineReportClient(fake, base_url=HOST, sleep=lambda s: None, clock_ms=lambda: 1791548303795)


def test_client_request_sequence_rsa_login_and_original_export():
    private, der = _rsa_pair()
    fake = FakeFineReport(public_key=der)
    result = _client(fake).run(USER, PASSWORD, P.build_parameters(_filters()))

    assert fake.step_paths() == EXPECTED_SEQUENCE
    login = json.loads(fake.calls[1]["data"])
    assert login["encrypted"] is True and login["username"] == USER and login["validity"] == -1
    assert private.decrypt(base64.b64decode(login["password"]), padding.PKCS1v15()).decode() == PASSWORD
    assert fake.cookies == {"fine_auth_token": TOKEN}
    for call in fake.calls[3:]:
        if call["path"].endswith("/view/report"):
            assert call["headers"]["sessionID"] == SESSION_ID
    export_query = fake.calls[6]["query"]
    assert export_query == {"op": "export", "format": "excel", "extype": "simple", "sessionID": SESSION_ID}
    assert result.content == fake.xlsx and result.rows == 3  # 帆软原样导出，不做二次改写


def test_client_plaintext_login_when_page_has_no_public_key():
    fake = FakeFineReport()
    _client(fake).run(USER, PASSWORD, P.build_parameters(_filters()))
    login = json.loads(fake.calls[1]["data"])
    assert login["encrypted"] is False and login["password"] == PASSWORD


def test_client_fails_when_platform_returns_no_xlsx():
    """不接受自建表格：导出端点没给 xlsx 就失败。"""
    fake = FakeFineReport(export_xlsx=False)
    with pytest.raises(TirError) as info:
        _client(fake).run(USER, PASSWORD, P.build_parameters(_filters()))
    assert info.value.code == "export_failed"
    assert fake.step_paths() == EXPECTED_SEQUENCE


def test_client_relogs_in_once_when_session_expired():
    fake = FakeFineReport(expire_session_once=True)
    _client(fake).run(USER, PASSWORD, P.build_parameters(_filters()))
    paths = fake.step_paths()
    assert paths.count("POST /login") == 2 and paths[-1] == "POST /view/report?export_polling"


def test_client_login_failure_is_closed_set_and_does_not_echo_server_message():
    with pytest.raises(TirError) as info:
        _client(FakeFineReport(login_ok=False)).run(USER, PASSWORD, {})
    assert info.value.code == "login_failed" and USER not in str(info.value)


def test_client_retries_transport_errors_then_reports_network_error():
    class Broken(FakeFineReport):
        def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("boom 10.0.0.1")

    sleeps: list[float] = []
    client = FineReportClient(Broken(), base_url=HOST, sleep=sleeps.append)
    with pytest.raises(TirError) as info:
        client.login(USER, PASSWORD)
    assert info.value.code == "network_error" and sleeps == [2.0, 4.0] and "10.0.0.1" not in str(info.value)


# ── 落盘、域账号、幂等、互斥 ──────────────────────────────────────────


class FakeVault:
    """Stands in for the host's DPAPI domain vault (WindowsDPAPICredentialVault)."""

    def __init__(self, configured: bool = True, broken: bool = False) -> None:
        self.configured = configured
        self.broken = broken

    def is_configured(self) -> bool:
        return self.configured

    @contextmanager
    def resolve(self):  # type: ignore[no-untyped-def]
        if self.broken:
            raise CredentialVaultError("could not unprotect domain credentials")
        value = ResolvedCredential(username=DOMAIN_USER, password=PASSWORD)
        try:
            yield value
        finally:
            value.clear()


def _domain(**kwargs) -> DPAPICredentialProvider:  # type: ignore[no-untyped-def]
    return DPAPICredentialProvider(FakeVault(**kwargs))


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore({"default": tmp_path / "archive"})


def _run(tmp_path: Path, fake: FakeFineReport, filters: P.ExportFilters | None = None, **kwargs):  # type: ignore[no-untyped-def]
    return S.run_export(
        filters or _filters(), data_dir=tmp_path, store=_store(tmp_path), credential_provider=_domain(),
        session_factory=lambda: fake, today=TODAY, base_url=HOST, sleep=lambda s: None, **kwargs,
    )


def test_run_export_archives_the_original_xlsx_like_other_deliverables(tmp_path: Path):
    """与自动归档的官方工作簿同一 ArchiveStore、同一路径格式：<根>/<来源>/<报表>/<日期>/<运行号>/<平台文件名>。"""
    _, der = _rsa_pair()
    fake = FakeFineReport(public_key=der)
    meta = _run(tmp_path, fake)
    archive = tmp_path / "archive"
    files = sorted((p for p in archive.rglob("*") if p.is_file()), key=lambda p: p.suffix != ".xlsx")
    assert [p.name for p in files] == ["TIR数据简表.xlsx", "tir_brief-manifest.json"]  # 与自动归档一样：工作簿 + manifest
    assert files[0].parent == files[1].parent
    manifest_text = files[1].read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert {"jobKey", "recordCount", "normalization", "bookkeeping", "stopReason", "projectionError"} <= set(manifest)
    assert manifest["recordCount"] == 3 and manifest["workbook"] == "TIR数据简表.xlsx"
    assert manifest["bookkeeping"]["headerColumns"] == 50 and manifest["bookkeeping"]["headerMatchesContract"] is True
    for secret in (USER, PASSWORD, TOKEN, SESSION_ID):
        assert secret not in manifest_text
    assert meta["manifestPath"] == files[1].relative_to(archive).as_posix()
    relative = files[0].relative_to(archive).as_posix()
    source, report, day, run_id, name = relative.split("/")
    assert (source, report, run_id, name) == ("finereport", "tir_brief", "1", "TIR数据简表.xlsx")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
    assert meta["relativePath"] == relative and meta["fileName"] == "TIR数据简表.xlsx" and meta["runId"] == 1
    assert files[0].read_bytes() == fake.xlsx and zipfile.is_zipfile(io.BytesIO(fake.xlsx))
    preview = read_xlsx_preview(files[0], max_rows=5)
    assert tuple(str(v) for v in preview.rows[0][:50]) == P.EXPECTED_HEADERS
    assert meta["ok"] and meta["rows"] == 3 and meta["headerCheck"] == {"ok": True, "columns": 50}
    assert not list(tmp_path.rglob("*.har"))
    record_text = (tmp_path / "runs" / "2026-10-09" / f"{meta['stem']}.json").read_text(encoding="utf-8")
    for secret in (USER, PASSWORD, TOKEN, SESSION_ID):
        assert secret not in record_text
    assert json.loads(record_text)["steps"][-1] == "export_polling"
    assert not (tmp_path / "runs" / ".lock").exists()

    forced = _run(tmp_path, FakeFineReport(), force=True)  # 第二次运行：运行号递增，目录与命名规则不变
    assert forced["runId"] == 2 and forced["relativePath"].split("/")[3] == "2"


def test_run_export_logs_in_with_domain_account_without_domain_prefix(tmp_path: Path):
    fake = FakeFineReport()
    _run(tmp_path, fake)
    assert json.loads(fake.calls[1]["data"])["username"] == USER


def test_run_export_with_empty_project_means_all_projects(tmp_path: Path):
    filters = P.normalize_filters({"project": "", "endDate": "2026-10-09"}, today=TODAY)
    fake = FakeFineReport()
    meta = _run(tmp_path, fake, filters)
    assert meta["stem"].startswith("tir_all_20220711-20261009_") and meta["fileName"] == "TIR数据简表.xlsx"
    sent = P.decode_parameters(unquote(fake.calls[3]["data"].split("&")[0].split("=", 1)[1]))
    assert sent["XM"] == "" and sent["BM"] == "车体工程"


def test_run_export_reuses_same_day_result_unless_forced(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is True and fake.calls == [] and again["stem"] == first["stem"]
    forced = _run(tmp_path, fake, force=True)
    assert forced["reused"] is False and fake.calls


@pytest.mark.parametrize("fake", [FakeFineReport(login_ok=False), FakeFineReport(export_xlsx=False)])
def test_run_export_failure_writes_nothing(tmp_path: Path, fake: FakeFineReport):
    with pytest.raises(TirError):
        _run(tmp_path, fake)
    assert not [p for p in (tmp_path / "archive").rglob("*") if p.is_file()]
    assert not list((tmp_path / "runs").rglob("*.json"))
    assert S.find_cached(tmp_path, _store(tmp_path), "2026-10-09", _filters()) is None


def test_run_export_credential_errors(tmp_path: Path):
    for provider in (None, _domain(configured=False)):
        with pytest.raises(TirError) as info:
            S.run_export(_filters(), data_dir=tmp_path, store=_store(tmp_path), credential_provider=provider,
                         session_factory=FakeFineReport, today=TODAY)
        assert info.value.code == "credential_missing"
    with pytest.raises(TirError) as info:
        S.run_export(_filters(), data_dir=tmp_path, store=_store(tmp_path), credential_provider=_domain(broken=True),
                     session_factory=FakeFineReport, today=TODAY)
    assert info.value.code == "credential_unavailable"


def test_run_lock_blocks_a_second_export_and_clears_stale_locks(tmp_path: Path):
    with S.run_lock(tmp_path):
        with pytest.raises(TirError) as info:
            _run(tmp_path, FakeFineReport())
        assert info.value.code == "busy"
    lock = tmp_path / "runs" / ".lock"
    lock.write_text("123", encoding="ascii")
    with S.run_lock(tmp_path, now=lambda: time.time() + 3600):  # 超过 30 分钟视为残留锁
        pass
    assert not lock.exists()


# ── 自动导出 ────────────────────────────────────────────────────────


def _enable_auto(tmp_path: Path, hour: int = 8) -> None:
    config = S.default_config()
    config["auto"] = {"enabled": True, "hour": hour}
    S.save_config(tmp_path, config)


def _auto(tmp_path: Path, fake: FakeFineReport, at: datetime, **kwargs):  # type: ignore[no-untyped-def]
    return S.run_auto(tmp_path, now=at, store=_store(tmp_path), credential_provider=_domain(**kwargs),
                      session_factory=lambda: fake,
                      base_url=HOST, sleep=lambda s: None)


def test_auto_export_runs_once_per_day_after_the_configured_hour(tmp_path: Path):
    fake = FakeFineReport()
    assert _auto(tmp_path, fake, datetime(2026, 10, 9, 9)) == {"decision": "disabled"}
    _enable_auto(tmp_path, hour=8)
    assert _auto(tmp_path, fake, datetime(2026, 10, 9, 7, 30)) == {"decision": "not_yet"}
    first = _auto(tmp_path, fake, datetime(2026, 10, 9, 8, 5))
    assert first["status"] == "ok" and first["attempts"] == 1
    sent = P.decode_parameters(unquote(fake.calls[3]["data"].split("&")[0].split("=", 1)[1]))
    assert (sent["XM"], sent["ENDTIME"]) == ("", "2026-10-09")  # 默认项目留空，结束日期取当天
    assert _auto(tmp_path, FakeFineReport(), datetime(2026, 10, 9, 9, 5)) == {"decision": "done"}
    assert S.load_auto_state(tmp_path)["relativePath"].startswith("finereport/tir_brief/")
    assert S.load_auto_state(tmp_path)["status"] == "ok"


def test_auto_export_stops_for_the_day_after_a_login_failure(tmp_path: Path):
    _enable_auto(tmp_path)
    failed = _auto(tmp_path, FakeFineReport(login_ok=False), datetime(2026, 10, 9, 8, 5))
    assert failed["status"] == "failed" and failed["errorCode"] == "login_failed"
    fake = FakeFineReport()
    assert _auto(tmp_path, fake, datetime(2026, 10, 9, 9, 5)) == {"decision": "stopped_today"}
    assert fake.calls == []  # 不再尝试登录，避免锁定域账号
    assert _auto(tmp_path, fake, datetime(2026, 10, 10, 8, 5))["status"] == "ok"  # 第二天恢复


def test_auto_export_gives_up_after_three_transient_failures(tmp_path: Path):
    _enable_auto(tmp_path)
    for hour in (8, 9, 10):
        assert _auto(tmp_path, FakeFineReport(export_xlsx=False), datetime(2026, 10, 9, hour, 5))["status"] == "failed"
    assert _auto(tmp_path, FakeFineReport(), datetime(2026, 10, 9, 11, 5)) == {"decision": "attempts_exhausted"}


def test_auto_export_cli_uses_plugin_data_dir_and_domain_vault(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import tools.tir_export_cli as cli

    data_dir = tmp_path / "plugins" / "tir-report"
    data_dir.mkdir(parents=True)
    _enable_auto(data_dir, hour=0)
    monkeypatch.setattr(cli, "plugin_data_dir", lambda: data_dir)
    monkeypatch.setattr(cli, "domain_provider", lambda: _domain())
    fake = FakeFineReport()
    monkeypatch.setattr(cli, "session_factory", lambda: fake)
    monkeypatch.setattr(cli, "archive_store", lambda: _store(tmp_path))
    assert cli.main(["--once"]) == 0
    assert [p.name for p in (tmp_path / "archive").rglob("*.xlsx")] == ["TIR数据简表.xlsx"]
    assert [p.name for p in (tmp_path / "archive").rglob("*.json")] == ["tir_brief-manifest.json"]
    with pytest.raises(SystemExit):
        cli.main([])  # 与 scheduled-archive 一样必须显式 --once


@pytest.mark.parametrize("day, stem", [
    ("2026-10-09", "..\\..\\config"), ("2026-10-09", "../x"), ("..", "tir_all_20220711-20261009_0123abcd"),
    ("2026-10-09", "C:x"), ("2026-10-09", "tir_all_20220711-20261009_0123abcd"),
])
def test_download_path_rejects_traversal_and_unknown_records(tmp_path: Path, day: str, stem: str):
    assert S.download_path(tmp_path, _store(tmp_path), day, stem) is None


def test_download_path_ignores_records_pointing_outside_the_archive(tmp_path: Path):
    meta = _run(tmp_path, FakeFineReport())
    record_path = tmp_path / "runs" / "2026-10-09" / f"{meta['stem']}.json"
    assert S.download_path(tmp_path, _store(tmp_path), "2026-10-09", meta["stem"])[1] == "TIR数据简表.xlsx"
    for evil in ("../runs/run-seq.json", "/etc/passwd", "finereport/../../x"):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["relativePath"] = evil
        record_path.write_text(json.dumps(record), encoding="utf-8")
        assert S.download_path(tmp_path, _store(tmp_path), "2026-10-09", meta["stem"]) is None


# ── 插件路由 ────────────────────────────────────────────────────────


@pytest.fixture()
def app_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[PLUGINS_ROOT], plugin_only=["tir-report"])
    app.config.update(TESTING=True)
    web_db = db_cls(tmp_path / "plugin.db")
    web_db.update_app_settings({"archiveDirectory": str(tmp_path / "archive")})  # 不写进仓库的 data/output
    vault = FakeVault(configured=False)
    app.extensions["domain_credential_vault"] = vault  # 插件经 ctx.service 读取，HostContext 是活视图
    backend = sys.modules["vse_plugins.tir_report.backend"]
    fake = FakeFineReport()
    monkeypatch.setattr(backend, "_today", lambda: TODAY)
    monkeypatch.setattr(backend, "session_factory", lambda: fake)
    return app, app.test_client(), fake, tmp_path, vault


def _ok(response):  # type: ignore[no-untyped-def]
    payload = response.get_json()
    assert payload["ok"] is True, payload
    return payload["data"]


def _wait(http, task_id: str) -> dict:  # type: ignore[no-untyped-def]
    for _ in range(200):
        view = _ok(http.get(f"/api/p/tir-report/export/{task_id}"))
        if view["status"] not in ("queued", "running"):
            return view
        time.sleep(0.02)
    raise AssertionError("export task did not finish")


def test_plugin_loads_and_exports_end_to_end(app_client):  # type: ignore[no-untyped-def]
    _, http, fake, tmp_path, vault = app_client
    manifest = http.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in manifest["plugins"] if p["id"] == "tir-report")
    assert record["status"] == "loaded", record.get("error")

    state = _ok(http.get("/api/p/tir-report/state"))
    assert state["domainCredentialReady"] is False and state["report"]["path"] == "tdc/TIR/TIR数据简表.cpt"
    assert state["config"]["defaults"]["project"] == "" and state["config"]["auto"] == {"enabled": False, "hour": 8}
    missing = http.post("/api/p/tir-report/export", json={})
    assert missing.status_code == 409 and missing.get_json()["error"]["type"] == "credential_missing"

    vault.configured = True
    assert _ok(http.get("/api/p/tir-report/state"))["domainCredentialReady"] is True
    started = _ok(http.post("/api/p/tir-report/export", json={"project": "F610S", "department": "车体工程",
                                                              "startDate": "2022-07-11", "endDate": "2026-10-09"}))
    view = _wait(http, started["taskId"])
    assert view["status"] == "succeeded", view
    assert view["result"]["ok"] is True and view["result"]["headerCheck"]["columns"] == 50
    assert fake.step_paths() == EXPECTED_SEQUENCE
    assert json.loads(fake.calls[1]["data"])["username"] == USER

    files = _ok(http.get("/api/p/tir-report/files"))["exports"]
    assert len(files) == 1 and files[0]["relativePath"].startswith("finereport/tir_brief/") and files[0]["rows"] == 3
    assert (tmp_path / "archive" / files[0]["relativePath"]).is_file()
    download = http.get(f"/api/p/tir-report/files/{files[0]['day']}/{files[0]['stem']}")
    assert download.status_code == 200 and download.data == fake.xlsx
    assert "TIR" in download.headers["Content-Disposition"]
    assert http.get("/api/p/tir-report/files/2026-10-09/..%5Cconfig").status_code == 404

    again = _ok(http.post("/api/p/tir-report/export", json={"project": "F610S", "department": "车体工程",
                                                            "startDate": "2022-07-11", "endDate": "2026-10-09"}))
    assert again["reused"] is True and again["taskId"] is None


def test_plugin_saves_auto_export_settings_without_credentials(app_client):  # type: ignore[no-untyped-def]
    _, http, _, tmp_path, _ = app_client
    saved = _ok(http.post("/api/p/tir-report/config", json={
        "auto": {"enabled": True, "hour": 7}, "defaults": {"project": "", "department": "车体工程"}}))
    assert saved["config"]["auto"] == {"enabled": True, "hour": 7} and saved["config"]["defaults"]["project"] == ""
    config_text = (tmp_path / "plugins" / "tir-report" / "config.json").read_text(encoding="utf-8")
    assert USER not in config_text and PASSWORD not in config_text
    assert _ok(http.get("/api/p/tir-report/state"))["config"]["auto"]["hour"] == 7
    for bad in ({"enabled": "yes", "hour": 7}, {"enabled": True, "hour": 24}, "on"):
        assert http.post("/api/p/tir-report/config", json={"auto": bad}).status_code == 400


def test_plugin_rejects_invalid_input_and_foreign_tasks(app_client):  # type: ignore[no-untyped-def]
    _, http, _, _, vault = app_client
    vault.configured = True
    bad = http.post("/api/p/tir-report/export", json={"startDate": "2026-12-01", "endDate": "2026-10-09"})
    assert bad.status_code == 400
    assert http.get("/api/p/tir-report/export/not-a-task").status_code == 400
    assert http.get("/api/p/tir-report/export/crawl_0123456789ab").status_code == 404
