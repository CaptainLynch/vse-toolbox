# -*- coding: utf-8 -*-
"""system-query plugin: loads, serves its module page, and keeps legacy mode parity."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "system_query"
STATIC_DIR = PLUGIN_DIR / "static"
MODULES = ["query.js", "modes.js", "lib.js", "grid.js"]


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "system-query.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    flask_app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["system-query"])
    flask_app.config.update(TESTING=True)
    return flask_app


def test_plugin_loads_with_module_page(app) -> None:
    data = app.test_client().get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "system-query")
    assert record["status"] == "loaded", record.get("error")
    assert record["pages"] == [{"id": "query", "title": "系统查询", "kind": "module", "module": "query.js"}]
    assert data["nav"] == [{"plugin": "system-query", "title": "系统查询", "page": "query", "order": 20}]


@pytest.mark.parametrize("name", MODULES)
def test_static_modules_are_served_as_javascript(app, name: str) -> None:
    response = app.test_client().get(f"/plugins/system-query/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_stylesheet_is_served(app) -> None:
    response = app.test_client().get("/plugins/system-query/static/query.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_plugin_frontend_respects_boundaries() -> None:
    for path in STATIC_DIR.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        for spec in re.findall(r'from\s+"([^"]+)"', source):
            assert spec.startswith("./") or spec.startswith("/static/host/"), f"{path.name} imports {spec}"
        # 页面不得记录或持久化凭据：不打 console 日志，请求头不进 localStorage。
        assert "console." not in source, path.name
    backend = (PLUGIN_DIR / "backend.py").read_text(encoding="utf-8")
    assert "import web" not in backend and "from web" not in backend


# ── modes.js 与旧页面 / 服务端契约的一致性（node）─────────────────────

_NODE_SCRIPT = r"""
const [staticUri, appJsPath] = process.argv.slice(1);
const fs = await import("node:fs");
const modes = await import(staticUri + "/modes.js");
const lib = await import(staticUri + "/lib.js");

const source = fs.readFileSync(appJsPath, "utf-8");
const start = source.indexOf("const ARAS_MODES = {");
const end = source.indexOf("\n};\n", start);
const legacy = Function("return (" + source.slice(start + "const ARAS_MODES = ".length, end + 2) + ")")();

const values = {
  ewo: {ewo_no: " EWO-1 ", page: "2", page_size: "", max_records: "100", submit_start: "2026-02-01", submit_end: "2026-01-01"},
  ncr: {project_names: "F610S, F610S DG,", othercondition: "0"},
  sor: {serial_number: "S-1", car_type_project: "E262S", car_type_project_id: "p-9", page: "1", page_size: "50",
        max_pages: "3", max_records: "0", preview_source: "official_export", file_name: "a.xlsx"},
};
const aras = {base_url: "http://ecm.sgmw.com.cn/innovatorserver", headers: "X-Trace: 1"};
const tdc = {base_url: "https://tdc.sgmw.com.cn", headers: ""};

const ncrData = {
  headerRows: [["组", "组", "组"], ["NCR号", "项目", "token"]],
  rows: [["N-2", "B", "t"], ["N-10", "A", "t"]],
};
const objData = {rows: [{_no: "E-2", cookie: "c=1", state: "Open"}, {_no: "E-10", cookie: "c=2", state: "Closed"}]};
const objGrid = lib.buildGridColumns(objData, objData.rows, ["_no"], "ewo");
const objCols = lib.candidateColumns(objGrid);
const colMap = new Map(objCols.map((c) => [c.index, c]));

console.log(JSON.stringify({
  legacy,
  aras: modes.ARAS_MODES,
  tdc: modes.TDC_MODES,
  groups: Object.fromEntries(Object.entries(modes.FIELD_GROUPS).map(([k, g]) => [k, g.fields.map((f) => [f.name, f.label, f.type])])),
  payloadEwo: lib.buildPayload("ewo", values.ewo, aras, {includeXml: true}),
  payloadEwoExport: lib.buildPayload("ewo", values.ewo, aras, {operation: "export", includeXml: true}),
  payloadNcr: lib.buildPayload("ncr-detail", values.ncr, aras),
  payloadSorQuery: lib.buildPayload("tdc-sor", values.sor, tdc),
  payloadSorCrawl: lib.buildPayload("tdc-sor", values.sor, tdc, {operation: "crawl_all"}),
  payloadSorExport: lib.buildPayload("tdc-sor", values.sor, tdc, {operation: "export"}),
  errorsEwo: lib.validateForm("ewo", {...values.ewo, page: "0"}, {base_url: "ftp://x"}),
  errorsOk: lib.validateForm("ewo", {page: "1", page_size: "50", max_records: "2000"}, aras),
  errorsTdcExport: lib.validateForm("tdc-sor", {...values.sor, file_name: "../x.csv"}, tdc, "export"),
  link: lib.parseDeepLink("#p/system-query/query?mode=paa&from=overview&no=PAA-7"),
  linkAlias: lib.parseDeepLink("#p/system-query/query?mode=sor&serial_number=S-9"),
  linkNcr: lib.parseDeepLink("#p/system-query/query?mode=ncr-detail&ncrNo=N-1"),
  linkBad: lib.parseDeepLink("#p/system-query/query?mode=nope"),
  auth: [
    lib.isAuthError({status: 401, type: "DomainSessionRequired"}),
    lib.isAuthError({status: 403, type: "LocalAccessRequired", message: "此操作仅允许从本机访问"}),
    lib.isAuthError({status: 503, code: "service_unavailable", message: "ARAS 服务当前不可用"}),
    lib.isAuthError({status: 400, type: "X", message: "尚未建立统一域账号会话：请先登录"}),
  ],
  redacted: lib.redactSensitiveText("Cookie: ARASAUTH=abc123; token=xyz Authorization: Bearer qqq"),
  formatted: lib.formatApiErrorMessage(lib.toQueryError({error: {type: "AuthenticationError", message: "token=abc", diagnosticPath: "d.md"}}, 401)),
  ncrGrid: lib.buildGridColumns(ncrData, ncrData.rows, [], "ncr-detail").kind,
  ncrProgressLabels: lib.buildGridColumns(ncrData, ncrData.rows, [], "ncr-progress").labels.map((l) => l.label),
  ncrCandidates: lib.candidateColumns(lib.buildGridColumns(ncrData, ncrData.rows, [], "ncr-progress")).map((c) => c.label),
  objCols: objCols.map((c) => c.key),
  sorted: lib.processRows(objData.rows, objCols, "", [{index: 0, dir: "desc"}], colMap).map((r) => r._no),
  filtered: lib.processRows(objData.rows, objCols, "clos", [], colMap).map((r) => r._no),
  sortCycle: [lib.nextSortSpec([], 1, false), lib.nextSortSpec([{index: 1, dir: "asc"}], 1, false),
              lib.nextSortSpec([{index: 1, dir: "desc"}], 1, false), lib.nextSortSpec([{index: 1, dir: "asc"}], 2, true)],
  segments: lib.highlightSegments("EWO-171-ewo", "ewo"),
  copyable: [lib.isCopyableColumn("EWO编号", null), lib.isCopyableColumn("主题", "column_6"), lib.isCopyableColumn("x", "serial_number")],
  accepted: [lib.isTaskAccepted(202, {ok: true, data: {taskId: "t1"}}), lib.isTaskAccepted(200, {ok: true, data: {taskId: "t1"}})],
  filename: lib.parseContentDispositionFilename("attachment; filename*=UTF-8''ncr%20detail.xlsx"),
  traversal: lib.parseContentDispositionFilename('attachment; filename="a/../b\\c.csv"'),
}));
"""


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


@pytest.fixture(scope="module")
def node_data() -> dict:
    if _node_major() < 22:
        pytest.skip("needs Node 22+ to import ES modules without a package.json")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, STATIC_DIR.as_uri(), str(REPO_ROOT / "web" / "static" / "app.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_every_legacy_aras_mode_is_data_with_same_contract(node_data) -> None:
    legacy, ported = node_data["legacy"], node_data["aras"]
    assert set(legacy) == set(ported) == {"ewo", "paa", "ncr-progress", "ncr-detail"}
    for mode_id, legacy_mode in legacy.items():
        for key, value in legacy_mode.items():
            assert ported[mode_id].get(key) == value, (mode_id, key)
        assert ported[mode_id]["system"] == "aras"


def test_field_groups_cover_every_filter_and_number(node_data) -> None:
    groups = node_data["groups"]
    for mode in [*node_data["aras"].values(), *node_data["tdc"].values()]:
        names = {name for name, _, _ in groups[mode["fieldGroup"]]}
        expected = set(mode["filterNames"])
        if mode["system"] == "aras":
            expected |= set(mode["numberNames"])
        assert expected <= names, mode["fieldGroup"]


def test_tdc_modes_match_server_filter_contract(node_data) -> None:
    tdc, groups = node_data["tdc"], node_data["groups"]
    assert tuple(tdc["tdc-data-model"]["filterNames"]) == web_app._TDC_DATA_MODEL_FILTER_NAMES
    assert tuple(tdc["tdc-sor"]["filterNames"]) + ("car_type_project_id",) == web_app._TDC_SOR_FILTER_NAMES
    for group, server_fields in (("tdc-data-model", web_app._TDC_DATA_MODEL_FIELDS), ("tdc-sor", web_app._TDC_SOR_FIELDS)):
        assert groups[group] == [[f["name"], f["label"], f["type"]] for f in server_fields]


def test_every_mode_endpoint_is_a_registered_post_route(app, node_data) -> None:
    rules = {rule.rule for rule in app.url_map.iter_rules() if "POST" in (rule.methods or set())}
    keys = ("endpoint", "crawlAllEndpoint", "exportEndpoint", "downloadEndpoint", "carTypeProjectsEndpoint")
    for mode in [*node_data["aras"].values(), *node_data["tdc"].values()]:
        for key in keys:
            if key in mode:
                assert mode[key] in rules, (key, mode[key])


def test_payloads_follow_legacy_collectors(node_data) -> None:
    ewo = node_data["payloadEwo"]
    assert ewo["base_url"] == "http://ecm.sgmw.com.cn/innovatorserver"
    assert ewo["headers"] == {"X-Trace": "1"}
    assert ewo["filters"]["ewo_no"] == "EWO-1"
    assert ewo["filters"]["project_code"] == ""  # 旧页面把所有筛选字段都发出
    assert (ewo["page"], ewo["page_size"], ewo["max_records"]) == (2, 0, 100)
    assert ewo["include_xml"] is True
    export = node_data["payloadEwoExport"]
    assert (export["max_records"], export["max_pages"]) == (100, 0) and "page" not in export
    assert "include_xml" not in export
    ncr = node_data["payloadNcr"]
    assert ncr["filters"]["project_names"] == ["F610S", "F610S DG"]
    assert ncr["preview"] is True
    query = node_data["payloadSorQuery"]
    assert query["filters"] == {"serial_number": "S-1", "car_type_project": "E262S", "car_type_project_id": "p-9"}
    assert (query["page"], query["page_size"], query["preview_source"]) == (1, 50, "official_export")
    crawl = node_data["payloadSorCrawl"]
    assert (crawl["page_size"], crawl["max_pages"]) == (50, 3) and "max_records" not in crawl and "page" not in crawl
    export = node_data["payloadSorExport"]
    assert export["file_name"] == "a.xlsx" and "preview_source" not in export and "page" not in export


def test_validation(node_data) -> None:
    assert set(node_data["errorsEwo"]) == {"base_url", "page", "submit_end"}
    assert node_data["errorsOk"] == {}
    assert set(node_data["errorsTdcExport"]) == {"file_name"}


def test_deep_links(node_data) -> None:
    assert node_data["link"] == {
        "mode": "paa", "requestedMode": "paa", "from": "overview", "identifier": "PAA-7", "identifierField": "paa_no",
    }
    assert node_data["linkAlias"]["mode"] == "tdc-sor"
    assert node_data["linkAlias"]["identifierField"] == "serial_number"
    assert node_data["linkNcr"]["identifier"] == "N-1"
    assert node_data["linkBad"]["mode"] is None


def test_errors_auth_and_redaction(node_data) -> None:
    assert node_data["auth"] == [True, False, False, True]
    redacted = node_data["redacted"]
    assert "abc123" not in redacted and "xyz" not in redacted and "qqq" not in redacted
    assert "abc" not in node_data["formatted"].split("诊断")[0].replace("AuthenticationError", "")
    assert node_data["formatted"].endswith("诊断报告已保存：d.md")


def test_grid_logic(node_data) -> None:
    assert node_data["ncrGrid"] == "grouped"
    assert node_data["ncrProgressLabels"] == ["NCR号", "项目", "token"]
    assert node_data["ncrCandidates"] == ["NCR号", "项目"]  # 敏感列从源头剔除
    assert node_data["objCols"] == ["_no", "state"]
    assert node_data["sorted"] == ["E-10", "E-2"]  # 数字感知排序
    assert node_data["filtered"] == ["E-10"]
    assert node_data["sortCycle"] == [
        [{"index": 1, "dir": "asc"}],
        [{"index": 1, "dir": "desc"}],
        [],
        [{"index": 1, "dir": "asc"}, {"index": 2, "dir": "asc"}],
    ]
    assert [s["hit"] for s in node_data["segments"]] == [True, False, True]
    assert node_data["copyable"] == [True, False, True]
    assert node_data["accepted"] == [True, False]
    assert node_data["filename"] == "ncr detail.xlsx"
    assert "/" not in node_data["traversal"] and "\\" not in node_data["traversal"]
