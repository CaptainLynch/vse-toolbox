# -*- coding: utf-8 -*-
"""Plugin shell frontend: integration points with the legacy page and UI Kit pure logic."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "shell.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[tmp_path / "plugins"])
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.mark.parametrize("name", ["shell.js", "api.js", "kit.js", "pages.js", "vendor/preact-htm.js"])
def test_shell_modules_are_served_as_javascript(client, name: str) -> None:
    # 浏览器只执行 JavaScript MIME 的 ES Module；Windows 注册表可能把 .js 映射成 text/plain。
    response = client.get(f"/static/host/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_dashboard_is_only_the_plugin_shell(client) -> None:
    html = client.get("/").get_data(as_text=True)
    assert '<div id="host-chrome" data-version=' in html
    assert '<section id="plugin-host" class="panel-section plugin-host"' in html
    assert html.index("/static/host/base.css") < html.index("/static/host/host.css")
    assert '<script type="module" src="/static/host/shell.js' in html
    for legacy in ("/static/app.js", "/static/style.css", "node-overview", 'class="top-bar"', "in-place-login-modal"):
        assert legacy not in html


def test_vendored_runtime_matches_recorded_checksum() -> None:
    readme = (HOST_STATIC / "vendor" / "README.md").read_text(encoding="utf-8")
    recorded = re.search(r"`([0-9a-f]{64})`", readme)
    assert recorded is not None
    lines = (HOST_STATIC / "vendor" / "preact-htm.js").read_bytes().split(b"\n", 1)
    assert lines[0].startswith(b"/*! htm 3.1.1")
    assert hashlib.sha256(lines[1]).hexdigest() == recorded.group(1)


def test_shell_imports_stay_inside_host_static() -> None:
    for path in HOST_STATIC.glob("*.js"):
        for spec in re.findall(r'from\s+"([^"]+)"', path.read_text(encoding="utf-8")):
            assert spec.startswith("./"), f"{path.name} imports {spec}"


_NODE_SCRIPT = r"""
const base = process.argv[1];
const pages = await import(base + "/pages.js");
const shell = await import(base + "/shell.js");
const rows = [
  {id: 1, code: "SOR-001", dept: "车身科", done: true, due: "2026-10-01"},
  {id: 2, code: "SOR-002", dept: "车身科", done: false, due: "2026-10-05"},
  {id: 3, code: "sor-003", dept: "", done: false, due: "2026-09-30"},
  {id: 4, code: "X-4", dept: "车身科", done: null, due: "2026-08-01"},
];
const fields = [
  {key: "code", type: "text"},
  {key: "dept", type: "select"},
  {key: "due", type: "date", match: "gte"},
];
console.log(JSON.stringify({
  contains: pages.applyClientFilters(rows, fields, {code: "sor-00"}).map(r => r.id),
  eq: pages.applyClientFilters(rows, fields, {dept: "车身科"}).map(r => r.id),
  gte: pages.applyClientFilters(rows, fields, {due: "2026-10-01"}).map(r => r.id),
  empty: pages.applyClientFilters(rows, fields, {code: "", dept: null}).length,
  done: pages.summarizeDone(rows, "dept", "done"),
  route: shell.parsePluginRoute("#p/deliverable_forms/sor?x=1"),
  legacy: shell.parsePluginRoute("#overview"),
  traversal: shell.parsePluginRoute("#p/../etc"),
}));
"""


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


@pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules without a package.json")
def test_ui_kit_pure_logic_under_node() -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, HOST_STATIC.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["contains"] == [1, 2, 3]
    assert data["eq"] == [1, 2, 4]
    assert data["gte"] == [1, 2]
    assert data["empty"] == 4
    # null 是终态：计入总数，不算完成也不算未完成
    assert data["done"]["summary"] == {"total": 4, "completed": 1, "incomplete": 2}
    assert data["done"]["groups"]["车身科"] == {"total": 3, "completed": 1, "incomplete": 1}
    assert data["done"]["groups"]["未填写"] == {"total": 1, "completed": 0, "incomplete": 1}
    assert data["route"] == {"pluginId": "deliverable_forms", "pageId": "sor"}
    assert data["legacy"] is None
    assert data["traversal"] is None


_LEGACY_SCRIPT = r"""
const { legacyRedirect } = await import(process.argv[1] + "/legacy-routes.js");
const hashes = ["", "#overview", "#overview?tab=plan", "#overview/deliverables/VPI-T2-D3",
  "#deliverable/A%20B", "#deliverable-detail/X", "#archive-deliverable/J1", "#deliverables",
  "#aras-panel?mode=ewo&from=overview", "#excel", "#archive", "#settings-panel", "#p/settings/general", "#nope"];
console.log(JSON.stringify(Object.fromEntries(hashes.map(h => [h, legacyRedirect(h)]))));
"""


@pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules without a package.json")
def test_legacy_hashes_redirect_to_plugin_routes() -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _LEGACY_SCRIPT, HOST_STATIC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data[""] == data["#overview"] == "#p/project-overview/status"
    assert data["#overview?tab=plan"] == "#p/project-overview/plan"
    assert data["#overview/deliverables/VPI-T2-D3"] == "#p/project-overview/deliverable?id=VPI-T2-D3"
    assert data["#deliverable/A%20B"] == "#p/project-overview/deliverable?id=A+B"
    assert data["#deliverable-detail/X"] == "#p/project-overview/deliverable?id=X"
    assert data["#archive-deliverable/J1"] == "#p/project-overview/archive-deliverable?job=J1"
    assert data["#deliverables"] == "#p/deliverables/catalog"
    assert data["#aras-panel?mode=ewo&from=overview"] == "#p/system-query/query?mode=ewo&from=overview"
    assert data["#excel"] == "#p/excel-tasks/workspace"
    assert data["#archive"] == "#p/scheduled-archive/jobs"
    assert data["#settings-panel"] == "#p/settings/general"
    assert data["#p/settings/general"] is None
    assert data["#nope"] is None
