# -*- coding: utf-8 -*-
"""Plugin host contract: plugin.json manifest, registry loading and /api/host/manifest."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import MappingProxyType

import pytest
from flask import Flask, jsonify

import web.app as web_app
from host import HostContext, PluginManifestError, PluginRegistry
from host.plugin import host_api_compatible, parse_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent

_BASE_MANIFEST = {
    "id": "demo",
    "name": "演示插件",
    "version": "0.1.0",
    "hostApi": ">=1,<2",
    "pages": [{"id": "main", "title": "演示页"}],
    "nav": [{"title": "演示", "page": "main", "order": 50}],
}

_DEMO_BACKEND = '''
from .helpers import greeting


def register(host):
    bp = host.blueprint

    @bp.get("/ping")
    def ping():
        return host.context.json_ok({"greeting": greeting(), "dataDir": host.data_dir.name})

    @bp.post("/echo")
    def echo():
        blocked = host.context.local_guard()
        if blocked is not None:
            return blocked
        return host.context.json_ok({"echo": True})
'''


def _write_plugin(root: Path, directory: str, manifest: dict, files: dict[str, str]) -> Path:
    plugin_dir = root / directory
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    for name, content in files.items():
        target = plugin_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return plugin_dir


def _demo_plugin(root: Path, directory: str = "demo", **overrides) -> Path:
    manifest = {**_BASE_MANIFEST, **overrides}
    return _write_plugin(
        root,
        directory,
        manifest,
        {"backend.py": _DEMO_BACKEND, "helpers.py": "def greeting():\n    return 'hello'\n"},
    )


def _context(tmp_path: Path) -> HostContext:
    def json_ok(data=None, status=200):
        return jsonify({"ok": True, "data": data}), status

    def json_error(status, error_type, message, *args, **kwargs):
        return jsonify({"ok": False, "error": {"type": error_type, "message": message}}), status

    return HostContext(
        db=None,
        data_dir=tmp_path / "data",
        json_ok=json_ok,
        json_error=json_error,
        local_guard=web_app._local_web_mutation_error,
        services=MappingProxyType({"answer": 42}),
    )


def _load(tmp_path: Path, plugins_root: Path, **kwargs) -> tuple[Flask, PluginRegistry]:
    app = Flask(__name__)
    registry = PluginRegistry([plugins_root], **kwargs)
    registry.load_all(app, _context(tmp_path))
    return app, registry


# ── manifest ─────────────────────────────────────────────────────────


def test_manifest_parses_minimal_valid_document() -> None:
    manifest = parse_manifest(_BASE_MANIFEST)
    assert manifest.id == "demo"
    assert manifest.entry == "backend"
    assert manifest.pages[0].kind == "schema"
    assert manifest.to_payload()["nav"] == [{"title": "演示", "page": "main", "order": 50}]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"id": "Demo"}, "id"),
        ({"version": "1.0"}, "version"),
        ({"hostApi": "~1"}, "hostApi"),
        ({"entry": "../evil"}, "entry"),
        ({"surprise": True}, "未知字段"),
        ({"nav": [{"title": "x", "page": "missing"}]}, "不存在的页面"),
        ({"pages": [{"id": "main", "title": "a"}, {"id": "main", "title": "b"}]}, "重复"),
        ({"pages": [{"id": "main", "title": "a", "kind": "module"}]}, "module"),
        ({"pages": [{"id": "main", "title": "a", "kind": "module", "module": "../x.js"}]}, "module"),
        ({"pages": [{"id": "main", "title": "a", "module": "x.js"}]}, "module"),
        ({"requires": "requests"}, "requires"),
    ],
)
def test_manifest_rejects_invalid_documents(override: dict, message: str) -> None:
    with pytest.raises(PluginManifestError, match=message):
        parse_manifest({**_BASE_MANIFEST, **override})


def test_host_api_constraints() -> None:
    assert host_api_compatible(">=1,<2", "1.0")
    assert host_api_compatible(">=1.0", "1.3")
    assert not host_api_compatible(">=1.4", "1.3")
    assert not host_api_compatible(">=2", "1.9")
    assert not host_api_compatible("<1", "1.0")
    assert host_api_compatible("==1.0", "1.0")


# ── registry ─────────────────────────────────────────────────────────


def test_registry_loads_plugin_routes_relative_imports_and_nav(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _demo_plugin(plugins_root)
    app, registry = _load(tmp_path, plugins_root)

    [record] = registry.records
    assert record.status == "loaded"
    resp = app.test_client().get("/api/p/demo/ping")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "data": {"greeting": "hello", "dataDir": "demo"}}
    assert (tmp_path / "data" / "plugins" / "demo").is_dir()

    payload = registry.manifest_payload()
    assert payload["hostApi"] == "1.0"
    assert payload["nav"] == [{"plugin": "demo", "title": "演示", "page": "main", "order": 50}]
    assert payload["plugins"][0]["status"] == "loaded"


def test_failing_plugin_is_isolated_and_error_is_redacted(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "a-broken",
        {**_BASE_MANIFEST, "id": "broken"},
        {
            "backend.py": (
                "def register(host):\n"
                "    @host.blueprint.get('/leak')\n"
                "    def leak():\n"
                "        return 'x'\n"
                "    raise RuntimeError('login failed token=abc123secret')\n"
            )
        },
    )
    _demo_plugin(plugins_root, "b-demo")
    app, registry = _load(tmp_path, plugins_root)

    statuses = {record.id: record.status for record in registry.records}
    assert statuses == {"broken": "failed", "demo": "loaded"}
    broken = next(record for record in registry.records if record.id == "broken")
    assert "abc123secret" not in (broken.error or "")
    client = app.test_client()
    assert client.get("/api/p/broken/leak").status_code == 404
    assert client.get("/api/p/demo/ping").status_code == 200


def test_incompatible_plugin_is_not_imported(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _write_plugin(
        plugins_root,
        "future",
        {**_BASE_MANIFEST, "id": "future", "hostApi": ">=2"},
        {"backend.py": "raise SystemExit('must not be imported')\n"},
    )
    _, registry = _load(tmp_path, plugins_root)
    assert [record.status for record in registry.records] == ["incompatible"]


def test_missing_dependency_and_duplicate_id_and_invalid_manifest(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _demo_plugin(plugins_root, "a-demo")
    _demo_plugin(plugins_root, "b-demo-copy")
    _demo_plugin(plugins_root, "c-needs", id="needs", requires=["vse_definitely_missing_module"])
    (plugins_root / "d-bad").mkdir()
    (plugins_root / "d-bad" / "plugin.json").write_text("{not json", encoding="utf-8")
    (plugins_root / "e-no-manifest").mkdir()

    _, registry = _load(tmp_path, plugins_root)
    summary = [(record.path.name, record.status) for record in registry.records]
    assert summary == [
        ("a-demo", "loaded"),
        ("b-demo-copy", "failed"),
        ("c-needs", "failed"),
        ("d-bad", "invalid"),
    ]
    assert "依赖" in (registry.records[2].error or "")


def test_only_filter_loads_selected_plugins(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _demo_plugin(plugins_root, "a-demo")
    _demo_plugin(plugins_root, "b-other", id="other")
    app, registry = _load(tmp_path, plugins_root, only=["other"])
    assert [record.id for record in registry.records] == ["other"]
    assert app.test_client().get("/api/p/demo/ping").status_code == 404


def test_plugin_static_files_are_served_under_plugins_prefix(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    plugin_dir = _demo_plugin(plugins_root)
    (plugin_dir / "static").mkdir()
    (plugin_dir / "static" / "ui.js").write_text("export default 1;\n", encoding="utf-8")
    app, _ = _load(tmp_path, plugins_root)
    resp = app.test_client().get("/plugins/demo/static/ui.js")
    assert resp.status_code == 200
    assert b"export default 1" in resp.data


def test_plugin_write_route_uses_host_local_guard(tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _demo_plugin(plugins_root)
    app, _ = _load(tmp_path, plugins_root)
    client = app.test_client()
    assert client.post("/api/p/demo/echo").status_code == 200
    blocked = client.post("/api/p/demo/echo", headers={"Sec-Fetch-Site": "cross-site"})
    assert blocked.status_code == 403


def test_host_context_service_lookup(tmp_path: Path) -> None:
    context = _context(tmp_path)
    assert context.service("answer") == 42
    with pytest.raises(LookupError):
        context.service("missing")
    with pytest.raises(ValueError):
        context.plugin_data_dir("../escape")


# ── create_app integration ───────────────────────────────────────────


@pytest.fixture()
def make_app(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "plugin-host.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)

    def _make(**kwargs):
        app = web_app.create_app(**kwargs)
        app.config.update(TESTING=True)
        return app

    return _make


def test_create_app_exposes_host_manifest_and_plugin_routes(make_app, tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _demo_plugin(plugins_root)
    client = make_app(plugin_dirs=[plugins_root]).test_client()

    manifest = client.get("/api/host/manifest")
    assert manifest.status_code == 200
    body = manifest.get_json()
    assert body["ok"] is True
    assert [plugin["id"] for plugin in body["data"]["plugins"]] == ["demo"]
    assert client.get("/api/p/demo/ping").get_json()["data"]["greeting"] == "hello"
    # 旧路由不受插件加载影响
    assert client.get("/api/version").status_code == 200


def test_create_app_without_plugins_dir_reports_empty_manifest(make_app, tmp_path: Path) -> None:
    client = make_app(plugin_dirs=[tmp_path / "missing"]).test_client()
    data = client.get("/api/host/manifest").get_json()["data"]
    assert data == {"hostApi": "1.0", "plugins": [], "nav": []}


def test_create_app_honours_plugin_only_env(make_app, monkeypatch, tmp_path: Path) -> None:
    plugins_root = tmp_path / "plugins"
    _demo_plugin(plugins_root, "a-demo")
    _demo_plugin(plugins_root, "b-other", id="other")
    monkeypatch.setenv("VSE_TOOLBOX_PLUGIN_ONLY", "other")
    data = make_app(plugin_dirs=[plugins_root]).test_client().get("/api/host/manifest").get_json()["data"]
    assert [plugin["id"] for plugin in data["plugins"]] == ["other"]


# ── boundary rules for real plugins ──────────────────────────────────


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def test_repository_plugins_respect_boundaries() -> None:
    """插件不得依赖 Web 适配层，也不得互相 import；只能经 HostContext 取用宿主能力。"""
    plugins_root = REPO_ROOT / "plugins"
    if not plugins_root.is_dir():
        pytest.skip("no plugins yet")
    violations = []
    for plugin_dir in sorted(p for p in plugins_root.iterdir() if (p / "plugin.json").is_file()):
        for source in plugin_dir.rglob("*.py"):
            for module in _imported_modules(source):
                if module == "web" or module.startswith("web.") or module.startswith("vse_plugins"):
                    violations.append(f"{source.relative_to(REPO_ROOT)} imports {module}")
    assert violations == []
