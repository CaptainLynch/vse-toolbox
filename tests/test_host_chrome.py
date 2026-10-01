# -*- coding: utf-8 -*-
"""Host chrome (top bar, global dialogs, task center): serving, API contract and pure logic."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"
LEGACY_APP_JS = REPO_ROOT / "web" / "static" / "app.js"
CHROME_MODULES = sorted(p.relative_to(HOST_STATIC).as_posix() for p in (HOST_STATIC / "chrome").glob("*.js"))
OWN_MODULES = ["session.js", "shell.js", *CHROME_MODULES]


@pytest.fixture()
def app(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "chrome.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    application = web_app.create_app(plugin_dirs=[tmp_path / "plugins"])
    application.config.update(TESTING=True)
    return application


def test_chrome_module_set_is_complete() -> None:
    names = {Path(name).stem for name in CHROME_MODULES}
    assert {"TopBar", "VersionDialog", "LoginDialog", "TaskCenter", "ThemeToggle", "SessionBadges", "index"} <= names


@pytest.mark.parametrize("name", OWN_MODULES)
def test_chrome_modules_are_served_as_javascript(app, name: str) -> None:
    response = app.test_client().get(f"/static/host/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_chrome_css_is_served_and_imported_by_host_css(app) -> None:
    response = app.test_client().get("/static/host/chrome.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"
    host_css = (HOST_STATIC / "host.css").read_text(encoding="utf-8")
    assert host_css.lstrip().startswith('@import url("chrome.css')


_IMPORT = re.compile(r'(?:from\s+|import\s*\(\s*)"([^"]+)"')


@pytest.mark.parametrize("name", OWN_MODULES)
def test_chrome_imports_resolve_inside_host_static(name: str) -> None:
    path = HOST_STATIC / name
    for spec in _IMPORT.findall(path.read_text(encoding="utf-8")):
        assert spec.startswith("./") or spec.startswith("../"), f"{name} imports {spec}"
        target = (path.parent / spec).resolve()
        assert target.is_file(), f"{name}: unresolved import {spec}"
        assert HOST_STATIC.resolve() in target.parents, f"{name}: import {spec} leaves web/static/host"


_API_PATH = re.compile(r'["`](/api/[^"`?\s]*)')


def _rule_patterns(application) -> list[re.Pattern[str]]:
    patterns = []
    for rule in application.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        regex = re.sub(r"<[^>]+>", "[^/]+", re.escape(rule.rule).replace(r"\<", "<").replace(r"\>", ">"))
        patterns.append(re.compile(regex))
    return patterns


def test_every_api_path_used_by_the_chrome_exists(app) -> None:
    patterns = _rule_patterns(app)
    used = set()
    for name in OWN_MODULES:
        source = (HOST_STATIC / name).read_text(encoding="utf-8")
        for raw in _API_PATH.findall(source):
            used.add(re.sub(r"\$\{[^}]*\}", "x", raw))
    expected = {"/api/settings", "/api/version", "/api/settings/domain-login", "/api/tasks",
                "/api/tasks/x/download", "/api/tasks/x/x", "/api/host/manifest"}
    assert expected <= used
    for path in used:
        if path == "/api/tasks/x/x":
            # `/api/tasks/${id}/${action}`: action is cancel or retry.
            candidates = ["/api/tasks/x/cancel", "/api/tasks/x/retry"]
        else:
            candidates = [path]
        for candidate in candidates:
            assert any(p.fullmatch(candidate) for p in patterns), f"no Flask route for {candidate}"


def test_chrome_sources_avoid_unsafe_patterns() -> None:
    for name in OWN_MODULES:
        source = (HOST_STATIC / name).read_text(encoding="utf-8")
        assert "console.log" not in source, name
        assert "innerHTML" not in source, name
        assert "dangerouslySetInnerHTML" not in source, name
    login = (HOST_STATIC / "session.js").read_text(encoding="utf-8")
    # The password travels only in the POST body.
    assert 'fetch("/api/settings/domain-login", {' in login
    assert "JSON.stringify({ username, password," in login
    assert "localStorage" not in login and "sessionStorage" not in login


def test_shell_declares_temporary_legacy_nav() -> None:
    source = (HOST_STATIC / "shell.js").read_text(encoding="utf-8")
    assert "export const LEGACY_NAV = [" in source
    assert "mountChrome({ legacyNav: LEGACY_NAV })" in source


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


needs_node = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules without a package.json")


@needs_node
@pytest.mark.parametrize("name", [*OWN_MODULES, "api.js", "kit.js", "pages.js"])
def test_node_check_passes(name: str) -> None:
    subprocess.run(["node", "--check", str(HOST_STATIC / name)], check=True, capture_output=True)


REDACTION_FIXTURES = [
    "Authorization: Bearer abc.def",
    "cookie: a=1; b=2",
    '{"password": "p@ss"}',
    "token=xyz&x=1",
    "Bearer qwerty",
    "sid: 12345, foo",
    "plain text",
    None,
    42,
    "set-cookie=JSESSIONID=abc; Path=/",
    "'secret':'v'",
    "url?api_key=K1&csrf=C2",
    "authorization=Basic Zm9v, token: t1 cookie: c=1",
    "ArasAuth: s3cr3t\nnext line",
    'headers {"Cookie": "a=b", "X": "y"}',
]

# Pinned outputs so the contract survives once legacy app.js is deleted.
REDACTION_GOLDEN = {
    "Authorization: Bearer abc.def": "Authorization: [redacted]",
    "cookie: a=1; b=2": "cookie: [redacted]",
    '{"password": "p@ss"}': '{"password":"[redacted]"}',
    "Bearer qwerty": "Bearer [redacted]",
    "sid: 12345, foo": "sid: [redacted], foo",
    "plain text": "plain text",
    "set-cookie=JSESSIONID=abc; Path=/": "set-cookie=[redacted]",
    "url?api_key=K1&csrf=C2": "url?api_key=[redacted]",
}

_NODE_SCRIPT = r"""
import fs from "node:fs";
const [base, legacyPath, fixturesJson] = process.argv.slice(1);
const fixtures = JSON.parse(fixturesJson);
const session = await import(base + "/session.js");
const tasks = await import(base + "/chrome/TaskCenter.js");
const topbar = await import(base + "/chrome/TopBar.js");
const theme = await import(base + "/chrome/ThemeToggle.js");
const shell = await import(base + "/shell.js");

let legacy = null;
if (legacyPath && fs.existsSync(legacyPath)) {
  const src = fs.readFileSync(legacyPath, "utf8");
  const a = src.indexOf("const SENSITIVE_VALUE_PATTERNS");
  const b = src.indexOf("];", a) + 2;
  const c = src.indexOf("function redactSensitiveText(");
  const d = src.indexOf("\n}\n", c) + 3;
  legacy = new Function(src.slice(a, b) + "\n" + src.slice(c, d) + "\nreturn redactSensitiveText;")();
}

const [aras, tdc] = session.SESSION_SYSTEMS;
const now = Date.parse("2026-10-01T00:10:00Z");
const pw = "Pa55word!";
console.log(JSON.stringify({
  host: fixtures.map((f) => session.redactSensitiveText(f)),
  legacy: legacy ? fixtures.map((f) => legacy(f)) : null,
  secret: session.redactWithSecret(`login ${pw} failed token=abc`, pw),
  badges: {
    initial: session.badgeState(aras, undefined),
    auth: session.badgeState(aras, {authenticated: true, expired: true}),
    expired: session.badgeState(tdc, {expired: true}),
    unknown: session.badgeState(tdc, {}),
    nullish: session.badgeState(tdc, null),
  },
  outcomes: {
    ok: session.loginOutcome(200, {ok: true, data: {results: {aras: {ok: true}, tdc: {ok: true}}, sessions: {aras: {}}}}, pw),
    partial: session.loginOutcome(200, {ok: true, data: {results: {aras: {ok: true}, tdc: {ok: false, message: `bad ${pw}`}}}}, pw),
    failed: session.loginOutcome(401, {ok: false, data: {results: {aras: {ok: false, message: `x ${pw}`}, tdc: {ok: false, message: "password=" + pw}}, sessions: {}}}, pw),
    vault: session.loginOutcome(503, {ok: false, error: {type: "CredentialVaultUnavailable", message: `vault ${pw}`}}, pw),
    other: session.loginOutcome(403, {ok: false, error: {type: "Forbidden", message: "only local"}}, pw),
    garbage: session.loginOutcome(500, null, pw),
  },
  tasks: {
    active: tasks.isActiveTask({status: "leased"}),
    flagged: tasks.isActiveTask({status: "failed", is_active: true}),
    filter: ["active", "history", "all"].map((f) => tasks.filterTasks([{status: "running"}, {status: "failed"}, {status: "queued"}], f).length),
    counts: tasks.taskCounts([{status: "running"}, {status: "succeeded"}, {status: "cancelled"}]),
    labels: ["queued", "parsed", "interrupted", "weird"].map(tasks.statusLabel),
    classes: ["downloading", "generated", "interrupted", "cancelled", "weird"].map(tasks.statusClass),
    ago: [tasks.formatTimeAgo("2026-10-01T00:09:30Z", now), tasks.formatTimeAgo("2026-10-01T00:00:00Z", now), tasks.formatTimeAgo("2026-09-30T21:00:00Z", now), tasks.formatTimeAgo("nope", now)],
    elapsed: [
      tasks.formatElapsed({status: "running", created_at: "2026-10-01T00:08:55Z"}, now),
      tasks.formatElapsed({status: "succeeded", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:02:00Z"}, now),
    ],
    poll: [
      tasks.nextPollDelay({open: true, activeCount: 0, closedPolls: 999}),
      tasks.nextPollDelay({open: false, activeCount: 2, closedPolls: 0}),
      tasks.nextPollDelay({open: false, activeCount: 2, closedPolls: tasks.MAX_CLOSED_POLLS}),
      tasks.nextPollDelay({open: false, activeCount: 0, closedPolls: 0}),
    ],
    url: tasks.taskDownloadUrl({id: "a/b c"}),
  },
  nav: {
    sorted: topbar.sortNav([{title: "b", order: 50}, {title: "a"}, {title: "c", order: 10}, {title: "d", order: 50}]).map((e) => e.title),
    keys: ["", "#overview", "#overview?tab=plan", "#overview-plan-panel", "#deliverables", "#deliverables/X1",
      "#archive-deliverable/k", "#p/settings/general", "#p/../etc", "#unknown"].map((h) => topbar.activeNavKey(h, shell.LEGACY_NAV)),
    emptied: topbar.activeNavKey("#overview", []),
  },
  theme: [theme.resolveTheme("dark", false), theme.resolveTheme(null, true), theme.resolveTheme("junk", false), theme.themeLabel("dark")],
}));
"""


@needs_node
def test_chrome_pure_logic_under_node() -> None:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SCRIPT, HOST_STATIC.as_uri(), str(LEGACY_APP_JS), json.dumps(REDACTION_FIXTURES)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])

    # Redaction: identical to legacy while app.js exists; pinned outputs always.
    if data["legacy"] is not None:
        assert data["host"] == data["legacy"]
    for fixture, expected in REDACTION_GOLDEN.items():
        assert data["host"][REDACTION_FIXTURES.index(fixture)] == expected
    assert "Pa55word!" not in data["secret"] and "abc" not in data["secret"]

    badges = data["badges"]
    assert badges["initial"] == {"tone": "is-unknown", "text": "未认证", "title": "Aras / ECM 流程会话状态"}
    assert badges["auth"] == {"tone": "is-authenticated", "text": "已认证", "title": "Aras ECM 会话：有效"}
    assert badges["expired"] == {"tone": "is-expired", "text": "已过期", "title": "TDC 研发流程会话：已过期（需重新登录）"}
    assert badges["unknown"]["tone"] == badges["nullish"]["tone"] == "is-unknown"
    assert badges["unknown"]["title"] == "TDC 研发流程会话：未认证"

    outcomes = data["outcomes"]
    assert outcomes["ok"]["kind"] == "success" and outcomes["ok"]["text"] == "登录成功，会话已建立"
    assert outcomes["ok"]["sessions"] == {"aras": {}}
    assert outcomes["partial"]["kind"] == "partial"
    assert outcomes["partial"]["text"] == "部分登录成功：Aras 成功；TDC 失败：bad [redacted]"
    assert outcomes["failed"]["kind"] == "error"
    assert outcomes["failed"]["text"] == "登录失败：Aras 失败：x [redacted]；TDC 失败：password=[redacted]"
    assert outcomes["failed"]["sessions"] == {}
    assert outcomes["vault"]["kind"] == "vault" and outcomes["vault"]["text"] == "vault [redacted]"
    assert outcomes["other"]["text"] == "登录失败：only local"
    assert outcomes["garbage"]["text"] == "登录失败：域认证登录失败"
    assert all("Pa55word!" not in o["text"] for o in outcomes.values())

    tasks = data["tasks"]
    assert tasks["active"] is True and tasks["flagged"] is True
    assert tasks["filter"] == [2, 1, 3]
    assert tasks["counts"] == {"active": 1, "history": 2}
    assert tasks["labels"] == ["排队中", "已完成", "已中断", "weird"]
    assert tasks["classes"] == ["is-running", "is-succeeded", "is-failed", "is-cancelled", "is-queued"]
    assert tasks["ago"] == ["30秒前", "10分钟前", "3小时前", ""]
    assert tasks["elapsed"] == ["已运行 1分5秒", "耗时 2分钟"]
    assert tasks["poll"] == [1500, 5000, None, None]
    assert tasks["url"] == "/api/tasks/a%2Fb%20c/download"

    nav = data["nav"]
    assert nav["sorted"] == ["c", "b", "d", "a"]
    assert nav["keys"] == [
        "overview", "overview", "overview", "overview", "deliverables", "overview",
        "overview", "p:settings/general", None, None,
    ]
    assert nav["emptied"] is None
    assert data["theme"] == ["dark", "dark", "light", "深色"]
