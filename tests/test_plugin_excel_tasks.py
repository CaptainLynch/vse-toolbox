# -*- coding: utf-8 -*-
"""excel-tasks plugin: manifest/nav, static module page, legacy endpoint contract it relies on."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
STATIC = PLUGINS_ROOT / "excel_tasks" / "static"
MODULES = ("workspace.js", "shared.js", "logic.js", "examples.js")


def _make_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "excel-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[PLUGINS_ROOT], plugin_only=["excel-tasks"], **kwargs)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    return _make_app(monkeypatch, tmp_path)


def test_plugin_loads_with_workspace_module_page(client) -> None:
    data = client.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "excel-tasks")
    assert record["status"] == "loaded", record.get("error")
    assert record["pages"] == [
        {"id": "workspace", "title": "Excel 文件处理", "kind": "module", "module": "workspace.js"}
    ]
    nav = [entry for entry in data["nav"] if entry["plugin"] == "excel-tasks"]
    assert len(nav) == 1
    assert {"title": "Excel", "page": "workspace", "order": 40}.items() <= nav[0].items()


@pytest.mark.parametrize("name", MODULES)
def test_static_modules_are_served_as_javascript(client, name: str) -> None:
    response = client.get(f"/plugins/excel-tasks/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_stylesheet_is_served(client) -> None:
    response = client.get("/plugins/excel-tasks/static/excel-tasks.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_static_imports_stay_on_host_runtime_or_plugin_dir() -> None:
    pattern = re.compile(r"""^\s*(?:import|export)\b[^;]*?from\s+["']([^"']+)["']""", re.MULTILINE)
    for name in MODULES:
        for spec in pattern.findall((STATIC / name).read_text(encoding="utf-8")):
            assert spec.startswith("/static/host/") or spec.startswith("./"), (name, spec)


def test_plugin_adds_no_backend_routes(client) -> None:
    assert client.get("/api/p/excel-tasks/rows").status_code == 404


def test_legacy_excel_endpoints_used_by_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    root.mkdir()
    (root / "a.xlsx").write_bytes(b"PK\x03\x04 placeholder")
    http = _make_app(monkeypatch, tmp_path, excel_roots={"inbox": root})

    rules = {rule.rule for rule in http.application.url_map.iter_rules()}
    for rule in (
        "/api/excel-roots",
        "/api/excel-worker/status",
        "/api/excel-worker/start",
        "/api/excel-worker/stop",
        "/api/excel-tasks",
        "/api/excel-tasks/<int:task_id>",
        "/api/excel-tasks/<int:task_id>/runs",
        "/api/excel-tasks/<int:task_id>/artifacts",
        "/api/excel-artifacts/<int:artifact_id>/download",
        "/api/excel-artifacts/<int:artifact_id>/download-audit",
        "/api/excel-artifacts/retention-plan",
        "/api/tasks/<task_id>/cancel",
    ):
        assert rule in rules, rule

    # 页面源码里出现的每个 /api/ 前缀都必须落在现有路由上（防止旧接口改名后静默失效）。
    source = "\n".join((STATIC / name).read_text(encoding="utf-8") for name in MODULES)
    used = set(re.findall(r"[`\"'](/api/[a-z\-/]+)", source))
    assert {"/api/excel-roots", "/api/excel-worker/status", "/api/excel-tasks"} <= used
    for prefix in used:
        # 模板字符串里的 `/api/tasks/excel_${id}` 截出 /api/tasks/excel，按上一级 + 动态段匹配。
        parent = prefix.rstrip("/").rsplit("/", 1)[0] + "/<"
        assert any(rule.startswith(prefix.rstrip("/")) or rule.startswith(parent) for rule in rules), prefix

    assert http.get("/api/excel-roots").get_json() == {"ok": True, "data": [{"rootId": "inbox"}]}
    assert http.get("/api/excel-tasks?limit=200").get_json() == {"ok": True, "data": []}

    created = http.post(
        "/api/excel-tasks",
        json={
            "operation": "merge_append",
            "files": [
                {"role": "source", "rootId": "inbox", "relativePath": "a.xlsx", "ordinal": 0},
                {"role": "output", "rootId": "inbox", "relativePath": "result.xlsx", "ordinal": 0},
            ],
            "idempotencyKey": "excel-test-1",
            "maxAttempts": 1,
        },
    )
    assert created.status_code == 200, created.get_json()
    task = created.get_json()["data"]
    assert task["status"] == "queued"
    assert {"id", "operation", "status", "attemptCount", "maxAttempts", "updatedAt", "files"} <= set(task)

    for suffix, expected in (("", dict), ("/runs", list), ("/artifacts", list)):
        body = http.get(f"/api/excel-tasks/{task['id']}{suffix}").get_json()
        assert body["ok"] is True and isinstance(body["data"], expected)

    # 页面的“取消任务”走统一任务中心入口 excel_<id>。
    cancelled = http.post(f"/api/tasks/excel_{task['id']}/cancel").get_json()
    assert cancelled["ok"] is True
    assert http.get(f"/api/excel-tasks/{task['id']}").get_json()["data"]["status"] == "cancelled"

    # 422 时 fields 明细供错误卡片展示。
    invalid = http.post("/api/excel-tasks", json={"operation": "", "files": []})
    assert invalid.status_code == 422
    assert invalid.get_json()["error"]["fields"]

    plan = http.get("/api/excel-artifacts/retention-plan?retentionDays=90&limit=500").get_json()
    assert plan["ok"] is True and isinstance(plan["data"]["artifacts"], list)


def test_unconfigured_excel_endpoints_report_not_configured(client) -> None:
    for path in ("/api/excel-roots", "/api/excel-tasks", "/api/excel-worker/status"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.get_json()["error"]["type"] == "NotConfigured"


_NODE_SCRIPT = r"""
const base = process.argv[1];
const m = await import(new URL("logic.js", base));
const roots = ["inbox", "out"];
const form = {
  operation: "merge_overlay", sourceRoot: "inbox", sourcePaths: "a.xlsx\n\n b.xls ",
  targetRoot: "inbox", targetPath: "t.xlsx", baselineRoot: "inbox", baselinePath: "",
  outputRoot: "out", outputPath: "r/out.xlsx", idempotencyKey: "k1",
};
const payload = m.buildTaskPayload(form, roots);
const errors = [];
for (const bad of ["/abs.xlsx", "a\\b.xlsx", "c:x.xlsx", "a/../b.xlsx", "a.csv", ""]) {
  try { m.validateRelativePath(bad, "F"); errors.push(null); } catch (e) { errors.push(e.message); }
}
let diffError = null;
try { m.buildTaskPayload({ ...form, operation: "diff_against_baseline" }, roots); } catch (e) { diffError = e.message; }
let rootError = null;
try { m.buildTaskPayload({ ...form, outputRoot: "nope" }, roots); } catch (e) { rootError = e.message; }
const back = m.formFromTask({ operation: payload.operation, files: payload.files }, "inbox");
console.log(JSON.stringify({
  payload, errors, diffError, rootError,
  back: { ...back, idempotencyKey: back.idempotencyKey.startsWith("excel-") },
  tone: [m.statusTone("succeeded"), m.statusTone("running"), m.statusTone("failed"), m.statusTone("x")],
  size: [m.formatSize(512), m.formatSize(2048), m.formatSize(null)],
  redacted: m.redact("token=abc123 ok"),
}));
"""


def _node_major() -> int:
    node = shutil.which("node")
    if not node:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


@pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules without a package.json")
def test_form_logic_under_node() -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, STATIC.as_uri() + "/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["payload"] == {
        "operation": "merge_overlay",
        "files": [
            {"role": "source", "rootId": "inbox", "relativePath": "a.xlsx", "ordinal": 0},
            {"role": "source", "rootId": "inbox", "relativePath": "b.xls", "ordinal": 1},
            {"role": "target", "rootId": "inbox", "relativePath": "t.xlsx", "ordinal": 0},
            {"role": "output", "rootId": "out", "relativePath": "r/out.xlsx", "ordinal": 0},
        ],
        "idempotencyKey": "k1",
        "maxAttempts": 1,
    }
    assert all(data["errors"]), data["errors"]
    assert data["diffError"] == "对比基准为必填项"
    assert data["rootError"] == "请选择有效的文件所在位置"
    back = data["back"]
    assert back["sourcePaths"] == "a.xlsx\nb.xls"
    assert (back["targetPath"], back["outputRoot"], back["outputPath"]) == ("t.xlsx", "out", "r/out.xlsx")
    assert back["idempotencyKey"] is True
    assert data["tone"] == ["is-success", "is-running", "is-failed", "is-unknown"]
    assert data["size"] == ["512 B", "2.0 KB", "-"]
    assert "abc123" not in data["redacted"]
