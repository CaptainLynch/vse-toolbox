# -*- coding: utf-8 -*-
"""deliverables plugin: loads, serves its module page, keeps legacy workbench parity."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "deliverables"
STATIC_DIR = PLUGIN_DIR / "static"
HOST_STATIC = REPO_ROOT / "web" / "static"
MODULES = ["catalog.js", "lib.js", "grid.js"]


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "deliverables.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    flask_app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["deliverables"])
    flask_app.config.update(TESTING=True)
    return flask_app


def test_plugin_loads_with_module_page(app) -> None:
    data = app.test_client().get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "deliverables")
    assert record["status"] == "loaded", record.get("error")
    assert record["name"] == "交付物"
    assert record["pages"] == [{"id": "catalog", "title": "交付物工作台", "kind": "module", "module": "catalog.js"}]
    assert data["nav"] == [{"plugin": "deliverables", "title": "交付物", "page": "catalog", "order": 15}]


@pytest.mark.parametrize("name", MODULES)
def test_static_modules_are_served_as_javascript(app, name: str) -> None:
    response = app.test_client().get(f"/plugins/deliverables/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_stylesheet_is_served(app) -> None:
    response = app.test_client().get("/plugins/deliverables/static/catalog.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_imports_resolve_to_shipped_files() -> None:
    for path in STATIC_DIR.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        for spec in re.findall(r'from\s+"([^"]+)"', source):
            if spec.startswith("./"):
                assert (STATIC_DIR / spec[2:]).is_file(), f"{path.name} imports missing {spec}"
            else:
                assert spec.startswith("/static/host/"), f"{path.name} imports {spec}"
                assert (HOST_STATIC / spec[len("/static/"):]).is_file(), f"{path.name} imports missing {spec}"


def test_plugin_frontend_respects_boundaries() -> None:
    for path in STATIC_DIR.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        assert "console." not in source, path.name
        assert "innerHTML" not in source and "dangerouslySetInnerHTML" not in source, path.name
        assert "/plugins/system_query" not in source and "system-query/static" not in source, path.name
        # 请求头 / 凭据永不落盘：只有网格列偏好使用 localStorage。
        if "localStorage" in source or "sessionStorage" in source:
            assert path.name == "grid.js", path.name
            assert "sessionStorage" not in source
    backend = (PLUGIN_DIR / "backend.py").read_text(encoding="utf-8")
    assert "import web" not in backend and "from web" not in backend
    css = (STATIC_DIR / "catalog.css").read_text(encoding="utf-8")
    for selector in re.findall(r"(?m)^([^\s@/{}][^{]*)\{", css):
        for part in selector.split(","):
            part = part.strip()
            if part and not part[0].isdigit() and part not in ("from", "to"):
                assert part.startswith(".dlv-page"), f"unscoped selector: {part}"


# ── 接口路径与 Flask url_map 一致 ───────────────────────────────────────

_EXPECTED_METHODS = {
    "/api/deliverables/catalog": "GET",
    "/api/tdc/sor/car-type-projects": "POST",
    "/api/tdc/data-model/query": "POST",
    "/api/tdc/data-model/crawl-all": "POST",
    "/api/tdc/data-model/export": "POST",
    "/api/tdc/sor/query": "POST",
    "/api/tdc/sor/crawl-all": "POST",
    "/api/tdc/sor/export": "POST",
}

_TASK_ROUTES = {
    "/api/tasks/<task_id>": "GET",
    "/api/tasks/<task_id>/result": "GET",
    "/api/tasks/<task_id>/download": "GET",
    "/api/tasks/<task_id>/cancel": "POST",
}


def test_every_api_path_is_a_registered_route(app) -> None:
    rules: dict[str, set[str]] = {}
    for rule in app.url_map.iter_rules():
        rules.setdefault(rule.rule, set()).update(rule.methods or set())
    found: set[str] = set()
    for path in STATIC_DIR.glob("*.js"):
        found.update(re.findall(r'"(/api/[^"$`]+)"', path.read_text(encoding="utf-8")))
    assert found, "no /api paths found"
    for api_path in found:
        if api_path.startswith("/api/tasks/"):
            continue
        assert api_path in _EXPECTED_METHODS, f"unexpected endpoint {api_path}"
    assert set(_EXPECTED_METHODS) <= found
    for api_path, method in {**_EXPECTED_METHODS, **_TASK_ROUTES}.items():
        assert api_path in rules, api_path
        assert method in rules[api_path], (api_path, method)
    lib = (STATIC_DIR / "lib.js").read_text(encoding="utf-8")
    assert "`/api/tasks/${encodeURIComponent(taskId)}${suffix}`" in lib
    catalog = (STATIC_DIR / "catalog.js").read_text(encoding="utf-8")
    for suffix in ('"/result"', '"/download"', '"/cancel"'):
        assert f"taskUrl(task" in catalog and suffix in catalog


def test_catalog_items_match_executable_tdc_endpoints(app, node_data) -> None:
    body = app.test_client().get("/api/deliverables/catalog").get_json()
    assert body["ok"] is True
    items = {item["id"]: item for item in body["data"]["deliverables"]}
    for item_id in node_data["tdcIds"]:
        assert item_id in items and items[item_id]["availability"] == "available"
        assert items[item_id]["fields"], item_id
    aras = [item for item in items.values() if (item.get("target") or {}).get("panel") == "aras-panel"]
    assert aras and all(item["target"].get("mode") for item in aras)


def test_auth_error_without_session_is_401(app) -> None:
    response = app.test_client().post("/api/tdc/sor/query", json={"base_url": "https://tdc.sgmw.com.cn", "headers": {}, "filters": {}})
    assert response.status_code == 401
    assert response.get_json()["error"]["type"] == "DomainSessionRequired"


# ── 纯逻辑（node） ─────────────────────────────────────────────────────

_NODE_SCRIPT = r"""
const [staticUri] = process.argv.slice(1);
const lib = await import(staticUri + "/lib.js");

const sor = {
  id: "tdc-sor", name: "SOR", category: "tdc", availability: "available", implementation_status: "已完整实现",
  fields: [
    {name: "serial_number", label: "流水号", type: "text"},
    {name: "car_type_project", label: "车型项目", type: "text"},
    {name: "application_start", label: "申请开始", type: "date"},
  ],
};
const dm = {id: "tdc-data-model", name: "数模", category: "tdc", availability: "available", implementation_status: "部分实现", fields: []};
const ewo = {id: "aras-ewo", name: "EWO", category: "aras", availability: "available", implementation_status: "已完整实现",
  target: {panel: "aras-panel", mode: "ewo"}};
const off = {id: "x-off", name: "Off", category: "aras", availability: "disabled", implementation_status: "仅占位"};
const catalog = [off, ewo, sor, dm];

const base = lib.defaultFormValues(sor);
const values = {...base, serial_number: " S-1 ", car_type_project: "E262S", car_type_project_id: "p-9",
  headers: "Cookie: a=1\nX-Trace: 2", page: "2", max_records: "0", preview_source: "official_export"};

const rows = [{serial_number: "S-10", token: "t", title: "b"}, {serial_number: "S-2", token: "t", title: "a"}];
const grid = lib.buildGridColumns({rows}, rows, [], "tdc-sor");
const cols = lib.candidateColumns(grid);
const colMap = new Map(cols.map((c) => [c.index, c]));

let runs = [];
for (let i = 0; i < 10; i += 1) runs = lib.addRecentRun(runs, {id: "a", name: "N", operation: "query", status: "success", summary: i === 9 ? "token=abc" : `rows=${i}`, time: "t"});

console.log(JSON.stringify({
  tdcIds: Object.keys(lib.TDC_ENDPOINTS),
  defaults: base,
  query: lib.buildPayload(sor, values, "query"),
  crawl: lib.buildPayload(sor, values, "crawl_all"),
  exp: lib.buildPayload(sor, values, "export"),
  dmQuery: lib.buildPayload(dm, lib.defaultFormValues(dm), "query"),
  errQueryOk: lib.validateForm(sor, base, "query"),
  errBad: lib.validateForm(sor, {...base, base_url: "", page: "0", page_size: "1.5"}, "query"),
  errBadUrl: lib.validateForm(sor, {...base, base_url: "not a url"}, "crawl_all"),
  errCrawl: lib.validateForm(sor, {...base, page: "", max_pages: ""}, "crawl_all"),
  errExport: lib.validateForm(sor, {...base, page: "", file_name: " "}, "export"),
  summary: lib.formatFilterSummary(sor, {serial_number: "S-1", car_type_project_id: "p", other: "password=x"}),
  summaryEmpty: lib.formatFilterSummary(sor, {}),
  visibleTdc: lib.visibleDeliverables(catalog, "tdc", "").map((i) => i.id),
  visibleStatus: lib.visibleDeliverables(catalog, "", "仅占位").map((i) => i.id),
  statusOptions: lib.statusOptions(catalog).map((o) => o.id),
  categoryOptions: lib.categoryOptions([{id: "aras", name: "Aras 报告"}]).map((o) => o.name),
  meta: lib.itemMetaText(sor, [{id: "tdc", name: "TDC 报表"}]),
  pickDefault: lib.pickInitialItem(catalog, "", "").id,
  pickRequested: lib.pickInitialItem(catalog, "tdc-sor", "aras-ewo").id,
  pickCurrent: lib.pickInitialItem(catalog, "missing", "tdc-data-model").id,
  executable: catalog.map((i) => lib.isExecutableTdc(i)),
  sqHash: [lib.systemQueryHash(ewo), lib.systemQueryHash({target: {panel: "aras-panel"}})],
  itemHash: lib.itemHash("tdc sor"),
  param: [lib.parseItemParam("#p/deliverables/catalog?item=tdc-sor"), lib.parseItemParam("#p/other/x?item=y"), lib.parseItemParam("#p/deliverables/catalog")],
  runs: runs.map((r) => r.summary),
  auth: [
    lib.isAuthError(lib.toApiError({error: {type: "DomainSessionRequired", message: "尚未建立统一域账号会话"}}, 401)),
    lib.isAuthError(lib.toApiError({error: {type: "LocalAccessRequired", message: "x"}}, 403)),
    lib.isLocalGuardError(lib.toApiError({error: {type: "CrossSiteRequest", message: "x"}}, 403)),
    lib.isAuthError(lib.toApiError({error: {type: "ServiceError", message: "boom"}}, 502)),
    lib.isAuthError(lib.messageError("后台任务失败：session expired")),
  ],
  formatted: lib.formatApiErrorMessage(lib.toApiError({error: {type: "X", message: "token=abc", diagnosticPath: "d.md"}}, 500)),
  network: lib.toApiError(null, 0).message,
  accepted: [lib.isTaskAccepted(202, {ok: true, data: {taskId: "t1"}}), lib.isTaskAccepted(200, {ok: true, data: {taskId: "t1"}})],
  filename: lib.parseContentDispositionFilename("attachment; filename*=UTF-8''sor%20x.xlsx"),
  taskUrl: lib.taskUrl("a/b", "/result"),
  meta2: lib.resultMetaText({report_type: "sor", rows: [1, 2], page: 1, pages: 3}),
  unmapped: lib.unmappedWarning({mappingComplete: false, unmappedColumns: ["a", "b"]}),
  ctx: [lib.previewContextText({queryTime: "T", filterSummary: "F"}), lib.previewContextText({queryTime: "T", filterSummary: "F"}, "操作失败")],
  cols: cols.map((c) => c.key),
  sorted: lib.processRows(rows, cols, "", [{index: cols.findIndex((c) => c.key === "serial_number"), dir: "asc"}], colMap).map((r) => r.serial_number),
  filtered: lib.processRows(rows, cols, "S-2", [], colMap).map((r) => r.serial_number),
  sortCycle: [lib.nextSortSpec([], 1, false), lib.nextSortSpec([{index: 1, dir: "asc"}], 1, false), lib.nextSortSpec([{index: 1, dir: "desc"}], 1, false)],
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
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, STATIC_DIR.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("name", MODULES)
def test_node_check_passes(name: str) -> None:
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    subprocess.run(["node", "--check", str(STATIC_DIR / name)], check=True, capture_output=True)


def test_defaults_follow_legacy_form(node_data) -> None:
    d = node_data["defaults"]
    assert d["base_url"] == "https://tdc.sgmw.com.cn"
    assert (d["page"], d["page_size"], d["max_pages"], d["max_records"]) == ("1", "50", "100", "10000")
    assert d["file_name"] == "tdc_sor_part_details.xlsx"
    assert d["operation_mode"] == "query" and d["output_format"] == "XLSX" and d["preview_source"] == "list_endpoint"


def test_payloads_follow_legacy_collector(node_data) -> None:
    q = node_data["query"]
    assert q["base_url"] == "https://tdc.sgmw.com.cn"
    assert q["headers"] == {"Cookie": "a=1", "X-Trace": "2"}
    assert q["filters"] == {"serial_number": "S-1", "car_type_project": "E262S", "car_type_project_id": "p-9"}
    assert (q["page"], q["page_size"], q["preview_source"]) == (2, 50, "official_export")
    assert "max_pages" not in q and "file_name" not in q
    c = node_data["crawl"]
    assert (c["page_size"], c["max_pages"]) == (50, 100) and "max_records" not in c and "page" not in c
    assert c["preview_source"] == "official_export"
    e = node_data["exp"]
    assert e["file_name"] == "tdc_sor_part_details.xlsx"
    assert not {"page", "page_size", "preview_source"} & set(e)
    assert node_data["dmQuery"]["filters"] == {} and node_data["dmQuery"]["preview_source"] == "list_endpoint"


def test_validation_matches_native_constraints(node_data) -> None:
    assert node_data["errQueryOk"] == {}
    bad = node_data["errBad"]
    assert bad["base_url"] == "请填写 Base URL"
    assert bad["page"] == "请输入不小于 1 的整数" and bad["page_size"] == "请输入不小于 1 的整数"
    assert "base_url" in node_data["errBadUrl"]
    crawl = node_data["errCrawl"]
    assert set(crawl) == {"max_pages"} and crawl["max_pages"] == "请填写最大页数"
    assert node_data["errExport"] == {"file_name": "请填写 XLSX 文件名"}


def test_catalog_filters_and_selection(node_data) -> None:
    assert node_data["visibleTdc"] == ["tdc-sor", "tdc-data-model"]
    assert node_data["visibleStatus"] == ["x-off"]
    assert node_data["statusOptions"] == ["", "已完整实现", "部分实现", "仅占位"]
    assert node_data["categoryOptions"] == ["全部分类", "Aras 报告"]
    assert node_data["meta"] == "TDC 报表 · 可用 · 已完整实现"
    assert node_data["pickDefault"] == "aras-ewo"
    assert node_data["pickRequested"] == "tdc-sor"
    assert node_data["pickCurrent"] == "tdc-data-model"
    assert node_data["executable"] == [False, False, True, True]


def test_links_and_deep_links(node_data) -> None:
    assert node_data["sqHash"] == ["#p/system-query/query?mode=ewo&from=overview", "#p/system-query/query?from=overview"]
    assert node_data["itemHash"] == "#p/deliverables/catalog?item=tdc%20sor"
    assert node_data["param"] == ["tdc-sor", "", ""]


def test_recent_runs_are_bounded_and_redacted(node_data) -> None:
    runs = node_data["runs"]
    assert len(runs) == 8
    assert runs[0] == "token=[redacted]" and runs[-1] == "rows=2"


def test_error_classification_and_redaction(node_data) -> None:
    assert node_data["auth"] == [True, False, True, False, True]
    assert "abc" not in node_data["formatted"] and "诊断报告已保存：d.md" in node_data["formatted"]
    assert node_data["network"] == "无法连接本地服务，请确认 VSE Toolbox 仍在运行"
    assert node_data["accepted"] == [True, False]
    assert node_data["filename"] == "sor x.xlsx"
    assert node_data["taskUrl"] == "/api/tasks/a%2Fb/result"
    assert node_data["summary"] == "流水号: S-1；other: password=[redacted]"
    assert node_data["summaryEmpty"] == "无筛选条件"


def test_result_text_helpers(node_data) -> None:
    assert node_data["meta2"].startswith("report=sor source=- page=1/3 rows=2 ")
    assert node_data["unmapped"] == "列表接口尚未提供 2 个官方导出列，已保留为空值；请使用官方导出预览。"
    assert node_data["ctx"] == ["预览生成时间：T · 筛选条件：F", "保留上次查询预览（生成时间：T · 筛选条件：F）· 操作失败"]


def test_grid_drops_sensitive_columns_and_sorts(node_data) -> None:
    assert "token" not in node_data["cols"]
    assert node_data["sorted"] == ["S-2", "S-10"]
    assert node_data["filtered"] == ["S-2"]
    assert node_data["sortCycle"] == [[{"index": 1, "dir": "asc"}], [{"index": 1, "dir": "desc"}], []]
