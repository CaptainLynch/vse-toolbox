# -*- coding: utf-8 -*-
"""Offline contract tests for the tir-report plugin (FineReport TIR数据简表 export).

假会话按方案 §2 的协议形态重放**合成**响应：fixture 里的账号、口令、token、sessionID 都是测试占位值，
不含任何来自真实 HAR 的数据；不发真实网络请求。
"""

from __future__ import annotations

import base64
import io
import json
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
from core.credential_provider import MemoryCredentialProvider
from plugins.tir_report import protocol as P
from plugins.tir_report import service as S
from plugins.tir_report.client import FineReportClient, TirError
from plugins.tir_report.har import HarRecorder
from plugins.tir_report.xlsx_writer import build_xlsx
from services.xlsx_preview import read_xlsx_preview

PLUGINS_ROOT = Path(__file__).resolve().parent.parent / "plugins"
TODAY = date(2026, 10, 9)
USER = "tester-account"
PASSWORD = "Pa55-word-for-tests"
TOKEN = "test-access-token-0123456789"
SESSION_ID = "11111111-2222-3333-4444-555555555555"
HOST = "https://report.example.test"
REF = "VSE/tir-test"


# ── 假会话 ──────────────────────────────────────────────────────────


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
        self.xlsx = build_xlsx([list(P.EXPECTED_HEADERS)] + DATA_ROWS)

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
                return FakeResponse(200, self.xlsx, "application/x-excel")
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
    ({"project": ""}, "项目"),
    ({"department": "x" * 300}, "无效"),
])
def test_normalize_filters_rejects_bad_input(raw, message):  # type: ignore[no-untyped-def]
    with pytest.raises(P.ProtocolError, match=message):
        P.normalize_filters(raw, today=TODAY)


def test_normalize_filters_defaults_end_to_today():
    filters = P.normalize_filters({}, today=TODAY)
    assert filters.as_payload() == {"project": "F610S", "department": "车体工程", "section": "",
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
    assert result.mode == "original" and result.content[:2] == b"PK" and result.rows == 3


def test_client_plaintext_login_when_page_has_no_public_key():
    fake = FakeFineReport()
    _client(fake).run(USER, PASSWORD, P.build_parameters(_filters()))
    login = json.loads(fake.calls[1]["data"])
    assert login["encrypted"] is False and login["password"] == PASSWORD


def test_client_falls_back_to_rebuilt_xlsx():
    fake = FakeFineReport(export_xlsx=False)
    result = _client(fake).run(USER, PASSWORD, P.build_parameters(_filters()))
    assert result.mode == "rebuilt" and result.content[:2] == b"PK"
    assert S.header_check(result.content) == {"ok": True, "columns": 50}


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


# ── 落盘、HAR 脱敏、幂等 ─────────────────────────────────────────────


def _run(tmp_path: Path, fake: FakeFineReport, **kwargs):  # type: ignore[no-untyped-def]
    return S.run_export(
        _filters(), data_dir=tmp_path, credential_ref=REF,
        credential_provider=MemoryCredentialProvider({REF: (USER, PASSWORD)}),
        session_factory=lambda: fake, today=TODAY, base_url=HOST, sleep=lambda s: None, **kwargs,
    )


def test_run_export_writes_xlsx_har_and_meta(tmp_path: Path):
    _, der = _rsa_pair()
    fake = FakeFineReport(public_key=der)
    meta = _run(tmp_path, fake)
    day_dir = tmp_path / "exports" / "2026-10-09"
    stem = meta["stem"]
    assert stem.isascii() and stem.startswith("tir_F610S_20220711-20261009_")
    xlsx = (day_dir / f"{stem}.xlsx").read_bytes()
    assert xlsx[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(xlsx))
    preview = read_xlsx_preview(day_dir / f"{stem}.xlsx", max_rows=5)
    assert tuple(str(v) for v in preview.rows[0][:50]) == P.EXPECTED_HEADERS
    assert meta["ok"] and meta["mode"] == "original" and meta["headerCheck"] == {"ok": True, "columns": 50}

    har_text = (day_dir / f"{stem}.har").read_text(encoding="utf-8")
    har = json.loads(har_text)
    assert har["log"]["version"] == "1.2" and len(har["log"]["entries"]) == len(EXPECTED_SEQUENCE)
    login_body = fake.calls[1]["data"].decode()
    encrypted_pw = json.loads(login_body)["password"]
    for secret in (USER, PASSWORD, encrypted_pw, TOKEN, SESSION_ID, "report.example.test", "fine_auth_token"):
        assert secret not in har_text, secret
    params = next(e for e in har["log"]["entries"] if "parameters_d" in e["request"]["url"])
    summary = json.loads(params["request"]["postData"]["params"][0]["value"])
    assert summary == {"XM": "F610S", "BM": "车体工程", "KS": "", "STARTTIME": "2022-07-11", "ENDTIME": "2026-10-09"}
    for entry in har["log"]["entries"]:
        assert urlsplit(entry["request"]["url"]).hostname == "report.invalid"
        assert entry["serverIPAddress"] == "" and entry["request"]["cookies"] == []
        assert "text" not in entry["response"]["content"] or len(entry["response"]["content"]["text"]) < 64
    meta_file = json.loads((day_dir / f"{stem}.json").read_text(encoding="utf-8"))
    assert meta_file["har"] is True and meta_file["steps"][-1] == "export_polling"


def test_run_export_reuses_same_day_result_unless_forced(tmp_path: Path):
    first = _run(tmp_path, FakeFineReport())
    fake = FakeFineReport()
    again = _run(tmp_path, fake)
    assert again["reused"] is True and fake.calls == [] and again["stem"] == first["stem"]
    forced = _run(tmp_path, fake, force=True)
    assert forced["reused"] is False and fake.calls


def test_run_export_failure_keeps_har_and_meta_without_xlsx(tmp_path: Path):
    with pytest.raises(TirError):
        _run(tmp_path, FakeFineReport(login_ok=False))
    files = sorted(p.suffix for p in (tmp_path / "exports" / "2026-10-09").iterdir())
    assert files == [".har", ".json"]
    meta = json.loads(next((tmp_path / "exports" / "2026-10-09").glob("*.json")).read_text(encoding="utf-8"))
    assert meta["ok"] is False and meta["errorCode"] == "login_failed"
    assert S.find_cached(tmp_path, "2026-10-09", _filters()) is None


def test_run_export_credential_errors(tmp_path: Path):
    with pytest.raises(TirError) as info:
        S.run_export(_filters(), data_dir=tmp_path, credential_ref="", credential_provider=None,
                     session_factory=FakeFineReport, today=TODAY)
    assert info.value.code == "credential_missing"
    with pytest.raises(TirError) as info:
        S.run_export(_filters(), data_dir=tmp_path, credential_ref="missing",
                     credential_provider=MemoryCredentialProvider({}), session_factory=FakeFineReport, today=TODAY)
    assert info.value.code == "credential_unavailable"


def test_har_recorder_refuses_to_write_when_secret_survives():
    from plugins.tir_report.har import HarLeakError

    class Echo(FakeFineReport):
        def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
            return FakeResponse(200, json.dumps({"status": TOKEN[:20]}), "application/json")

    recorder = HarRecorder(Echo())
    recorder.register_secret("abcd1234")
    recorder.get(HOST + "/webroot/decision/x?op=abcd1234")  # 白名单查询键原样保留 -> 自检必须拦截
    with pytest.raises(HarLeakError):
        recorder.dumps()


@pytest.mark.parametrize("day, name", [
    ("2026-10-09", "..\\..\\config.json"), ("2026-10-09", "../x.json"), ("..", "x.json"),
    ("2026-10-09", "C:x.xlsx"), ("2026-10-09", "x.exe"), ("2026-10-09", "missing.xlsx"),
])
def test_safe_file_path_rejects_traversal(tmp_path: Path, day: str, name: str):
    (tmp_path / "exports" / "2026-10-09").mkdir(parents=True)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert S.safe_file_path(tmp_path, day, name) is None


# ── 插件路由 ────────────────────────────────────────────────────────


@pytest.fixture()
def app_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[PLUGINS_ROOT], plugin_only=["tir-report"])
    app.config.update(TESTING=True)
    backend = sys.modules["vse_plugins.tir_report.backend"]
    fake = FakeFineReport()
    monkeypatch.setattr(backend, "_today", lambda: TODAY)
    monkeypatch.setattr(backend, "session_factory", lambda: fake)
    monkeypatch.setattr(backend, "credential_provider_factory",
                        lambda: MemoryCredentialProvider({REF: (USER, PASSWORD)}))
    return app, app.test_client(), fake, tmp_path


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
    _, http, fake, tmp_path = app_client
    manifest = http.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in manifest["plugins"] if p["id"] == "tir-report")
    assert record["status"] == "loaded", record.get("error")

    state = _ok(http.get("/api/p/tir-report/state"))
    assert state["config"]["credentialRef"] == "" and state["report"]["path"] == "tdc/TIR/TIR数据简表.cpt"
    missing = http.post("/api/p/tir-report/export", json={})
    assert missing.status_code == 409 and missing.get_json()["error"]["type"] == "credential_missing"

    _ok(http.post("/api/p/tir-report/config", json={"credentialRef": REF}))
    config_text = (tmp_path / "plugins" / "tir-report" / "config.json").read_text(encoding="utf-8")
    assert REF in config_text and PASSWORD not in config_text and USER not in config_text

    started = _ok(http.post("/api/p/tir-report/export", json={"project": "F610S", "department": "车体工程",
                                                              "startDate": "2022-07-11", "endDate": "2026-10-09"}))
    view = _wait(http, started["taskId"])
    assert view["status"] == "succeeded", view
    assert view["result"]["ok"] is True and view["result"]["headerCheck"]["columns"] == 50
    assert fake.step_paths() == EXPECTED_SEQUENCE

    files = _ok(http.get("/api/p/tir-report/files"))["exports"]
    assert files and sorted(name.rsplit(".", 1)[1] for name in files[0]["files"]) == ["har", "json", "xlsx"]
    xlsx_name = next(name for name in files[0]["files"] if name.endswith(".xlsx"))
    download = http.get(f"/api/p/tir-report/files/{files[0]['day']}/{xlsx_name}")
    assert download.status_code == 200 and download.data[:2] == b"PK"
    assert http.get("/api/p/tir-report/files/2026-10-09/..%5Cconfig.json").status_code == 404

    again = _ok(http.post("/api/p/tir-report/export", json={"project": "F610S", "department": "车体工程",
                                                            "startDate": "2022-07-11", "endDate": "2026-10-09"}))
    assert again["reused"] is True and again["taskId"] is None


def test_plugin_rejects_invalid_input_and_foreign_tasks(app_client):  # type: ignore[no-untyped-def]
    _, http, _, _ = app_client
    _ok(http.post("/api/p/tir-report/config", json={"credentialRef": REF}))
    bad = http.post("/api/p/tir-report/export", json={"startDate": "2026-12-01", "endDate": "2026-10-09"})
    assert bad.status_code == 400
    assert http.post("/api/p/tir-report/config", json={"credentialRef": 3}).status_code == 400
    assert http.get("/api/p/tir-report/export/not-a-task").status_code == 400
    assert http.get("/api/p/tir-report/export/crawl_0123456789ab").status_code == 404
