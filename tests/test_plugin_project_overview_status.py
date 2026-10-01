# -*- coding: utf-8 -*-
"""project-overview plugin: 项目状态 / 交付物明细 pages (status.js, details.js).

Pins the static contract (served modules, imports, legacy API paths) and the
pure display logic in shared/status-logic.js ported from the legacy overview.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "plugins" / "project_overview" / "static"
OWN_MODULES = sorted(
    [STATIC / "status.js", STATIC / "details.js"]
    + list((STATIC / "status").glob("*.js"))
    + list((STATIC / "details").glob("*.js"))
    + list((STATIC / "shared").glob("status-*.js"))
)
HOST_IMPORTS = {"/static/host/vendor/preact-htm.js", "/static/host/kit.js"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "overview-status.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["project-overview"])
    app.config.update(TESTING=True)
    return app.test_client()


def _rel(path: Path) -> str:
    return path.relative_to(STATIC).as_posix()


def test_plugin_loads_with_status_and_details_pages(client) -> None:
    data = client.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "project-overview")
    assert record["status"] == "loaded", record.get("error")
    pages = {page["id"]: page for page in record["pages"]}
    assert pages["status"]["module"] == "status.js" and pages["status"]["kind"] == "module"
    assert pages["details"]["module"] == "details.js" and pages["details"]["kind"] == "module"


@pytest.mark.parametrize("module", [_rel(p) for p in OWN_MODULES])
def test_modules_are_served_as_javascript(client, module: str) -> None:
    response = client.get(f"/plugins/project-overview/static/{module}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_stylesheet_is_served(client) -> None:
    response = client.get("/plugins/project-overview/static/overview.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_modules_import_only_shipped_files() -> None:
    for module in OWN_MODULES:
        source = module.read_text(encoding="utf-8")
        for spec in re.findall(r'from\s+"([^"]+)"', source):
            if spec.startswith("/"):
                assert spec in HOST_IMPORTS, (module.name, spec)
                assert (REPO_ROOT / "web" / spec.lstrip("/")).is_file(), spec
            else:
                assert spec.startswith("./") or spec.startswith("../"), (module.name, spec)
                target = (module.parent / spec).resolve()
                assert target.is_file() and STATIC.resolve() in target.parents, (module.name, spec)
    # The logic module stays import-free so Node can load it directly.
    assert "import " not in (STATIC / "shared" / "status-logic.js").read_text(encoding="utf-8")


def _normalize(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "<x>", path)
    return re.sub(r"<[^>]+>", "<x>", path).rstrip("/")


def test_every_api_path_exists_in_url_map(client) -> None:
    rules = {_normalize(rule.rule) for rule in client.application.url_map.iter_rules()}
    found = set()
    for module in OWN_MODULES:
        source = module.read_text(encoding="utf-8")
        for match in re.findall(r"""["'`](/api/[^"'`\s]*)""", source):
            found.add(_normalize(match))
    assert found, "expected legacy /api paths in the page sources"
    missing = sorted(path for path in found if path not in rules)
    assert not missing, missing
    assert {"/api/project-status", "/api/project-status/scheduler", "/api/deliverables/catalog"} <= found


def test_sources_avoid_inner_html_and_console_log() -> None:
    for module in OWN_MODULES:
        source = module.read_text(encoding="utf-8")
        assert "innerHTML" not in source and "dangerouslySetInnerHTML" not in source, module.name
        assert "console.log" not in source, module.name


def test_project_status_payload_has_fields_the_pages_read(client) -> None:
    data = client.get("/api/project-status?phase=VPI-T2").get_json()["data"]
    assert {"phase", "milestones", "deliverables", "months"} <= set(data)
    assert {"id", "displayName", "status", "startDate", "endDate", "today", "overallProgress"} <= set(data["phase"])
    for item in data["deliverables"]:
        assert {"id", "name", "status", "plannedDate", "note", "source", "syncDisplay", "manualEditable",
                "boardVisible", "updatedAt", "updatePolicy"} <= set(item)
    scheduler = client.get("/api/project-status/scheduler").get_json()["data"]
    assert {"paused", "intervalSeconds", "lastTickAt", "nextRunSeconds", "eligibleCount"} <= set(scheduler)


def test_node_check_all_modules() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    for module in OWN_MODULES:
        result = subprocess.run([node, "--check", str(module)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, (module.name, result.stderr)


# ---------------------------------------------------------------------------
# Node: pure logic


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


needs_node = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules")

_LOGIC_SCRIPT = r"""
const L = await import(process.argv[1] + "/shared/status-logic.js");
const phase = { id: "VPI-T2", startDate: "2026-04-01", endDate: "2026-08-29", today: "2026-06-15",
  status: "进行中", overallProgress: 64 };
const milestones = [
  { id: 3, name: "C", date: "", sortOrder: 3, status: "未开始", type: "planned" },
  { id: 1, name: "VDR 决策", date: "2026-04-01", sortOrder: 1, status: "已完成", type: "done" },
  { id: 2, name: "B", date: "2026-08-29", sortOrder: 2, status: "已超期", type: "planned" },
  { id: 4, name: "D", date: null, sortOrder: 4, status: "进行中", type: "current" },
];
const xs = L.calculateMilestoneTimelineX(milestones, phase).map((e) => [e.milestone.id, Math.round(e.x * 100) / 100]);
const xsNoDates = L.calculateMilestoneTimelineX([{ id: 1, sortOrder: 1 }, { id: 2, sortOrder: 2 }, { id: 3, sortOrder: 3 }], phase).map((e) => e.x);
const entries = L.buildTimelineEntries({ phase, milestones }, 2).map((e) => e.type === "today"
  ? ["today", e.label] : [e.id, e.nodeType, e.nodeStatus, e.dateText, e.active]);
const ctx = L.buildNodeContext({ phase, milestones, deliverables: [] });
const enabled = { enabled: true, mode: "automatic" };
const display = [
  L.deliverableFormDisplay({ updatePolicy: enabled, analysisLink: { snapshotAt: "A", summary: { total: 4, completed: 3, overdue: 1 } },
    formLink: { snapshotAt: "B", summary: { total: 2, completed: 2, overdue: 0 } } }),
  L.deliverableFormDisplay({ updatePolicy: enabled, formLink: { snapshotAt: "B", summary: { total: 4, completed: 1, overdue: 2 } } }),
  L.deliverableFormDisplay({ updatePolicy: enabled, formLink: { snapshotAt: "B", summary: { total: 0 } } }),
  L.deliverableFormDisplay({ updatePolicy: { enabled: false }, analysisLink: { summary: { total: 4, completed: 3 } } }),
  L.deliverableFormDisplay({ updatePolicy: { ...enabled, aggregate: true }, formLink: { summary: { total: 4, completed: 4 } } }),
  L.deliverableFormDisplay({ status: "已逾期", syncDisplay: { state: "snapshot", displayStatus: "已逾期", displayProgress: 74.6,
    displaySummary: { snapshotAt: "S" } } }),
];
const merged = L.deliverableDisplayItem({ updatePolicy: enabled, status: "进行中", progress: 60,
  analysisLink: { summary: { total: 4, completed: 4, overdue: 0 } } });
const pendingRing = L.progressRingModel({ id: "P", name: "P", status: "已完成", progress: 100, plannedDate: "2026-06-01",
  syncDisplay: { state: "pending_first_sync", label: "待首次同步" } }, { phase });
const doneRing = L.progressRingModel({ id: "D", name: "D", status: "已完成", progress: 100, actualDate: "2026-05-02",
  note: "无", syncDisplay: { state: "manual" } }, { phase });
const pctRing = L.ringDateLabel({ status: "已完成", progress: 100 });
const state = { phase, milestones, deliverables: [
  { id: "VPI-T2-D1", status: "已完成", syncDisplay: { state: "manual" } },
  { id: "VPI-T2-D4", status: "已完成", boardVisible: false, syncDisplay: { state: "manual" } },
  { id: "VPI-T2-D2", status: "已完成", syncDisplay: { state: "pending_first_sync" } },
  { id: "VPI-T2-D3", status: "进行中", syncDisplay: { state: "manual" } },
] };
const autoIds = L.visibleProgressRings(state, "auto").map((r) => r.id);
const allIds = L.visibleProgressRings(state, "all").map((r) => r.id);
const hint = L.autoHiddenHint(state.deliverables, "auto", state);
const tokenMatch = L.deliverableNodeReached(["VPI"], { phase, milestones: [{ name: "VPI-T2 Gate", date: "2026-04-01" }] });
const rows = L.detailRows({ deliverables: [
  { id: "A", name: "A", status: "已逾期", progress: 30, manualEditable: true, source: "内网", syncDisplay: { state: "snapshot" },
    updatePolicy: enabled, analysisLink: { summary: { total: 10, completed: 3, overdue: 2 } } },
  { id: "H", boardVisible: false },
  { id: "X", name: "X", status: "进行中", manualEditable: false, readOnlyReason: "", isExternalArchive: true, externalJobKey: "aras_ewo",
    syncDisplay: { state: "paused", label: "已暂停" } },
] });
const ext = L.externalReferenceRows([{ name: "E", links: { displayCode: "DEL-003", archiveJobKey: "aras_ewo" } }, { name: "N" },
  { name: "U", links: {} }]);
const sched = [
  L.schedulerView({ paused: false, intervalSeconds: 1800, eligibleCount: 3, lastTickAt: "2026-09-01T08:15:30" }, 125),
  L.schedulerView({ paused: true, eligibleCount: 0, lastTickAt: null }, null),
  L.schedulerView({}, null).meta,
];
const valid = {
  ok: L.validateDeliverableDraft({ status: "进行中", owner: "王", plannedDate: "2026-05-01", actualDate: "", progress: "40", note: "" }),
  missing: L.validateDeliverableDraft({ status: "", owner: " ", plannedDate: "", actualDate: "", progress: "", note: "" }),
  done: L.validateDeliverableDraft({ status: "已完成", owner: "王", plannedDate: "2026/05/01", actualDate: "", progress: "90", note: "" }),
  undoneActual: L.validateDeliverableDraft({ status: "进行中", owner: "王", plannedDate: "2026-05-01", actualDate: "2026-05-02", progress: "1.5", note: "" }),
};
const payload = L.deliverablePatchPayload({ status: " 进行中 ", owner: " 王 ", plannedDate: "2026-05-01", actualDate: "", progress: "40", note: " n " },
  { updatedAt: "U1" });
const notePayload = L.notePatchPayload({ status: "进行中", owner: "王", plannedDate: "P", actualDate: null, progress: 5, updatedAt: "U2" }, "新备注");
const errs = [
  L.overviewErrorText({ status: 403, message: "此操作仅允许从本机访问" }),
  L.overviewErrorText({ status: 409, message: "记录已被其他会话更新，请刷新后重试" }),
  L.overviewErrorText({ status: 500, message: "请求失败（HTTP 500）" }),
  L.overviewErrorText({ status: 0, message: "无法连接本地服务" }),
];
console.log(JSON.stringify({
  xs, xsNoDates, entries, node: ctx.node && ctx.node.id, days: ctx.days, timing: [L.nodeTimingText(null), L.nodeTimingText(-3),
    L.nodeTimingText(0), L.nodeTimingText(5)], title: L.nodeFocusTitle({ node: null }, []),
  display, merged: [merged.status, merged.progress, merged.progressOrDate, merged.tone], pendingRing, doneRing, pctRing,
  autoIds, allIds, hint, tokenMatch, rows, ext, sched, valid, payload, notePayload, errs,
  serverFields: L.mapServerFieldErrors({ planned_date: "x", actualDate: "y", bogus: "z" }),
  dirty: [L.draftDirty(L.draftValuesFromItem({ progress: 0 }), L.draftValuesFromItem({ progress: 0 })),
    L.draftDirty({ note: "a" }, { note: "b" })],
  interval: [L.schedulerConfigPayload("0"), L.schedulerConfigPayload("3600"), L.intervalChangedMessage("0"), L.intervalChangedMessage("1800")],
  syncAll: L.syncAllMessage({ results: [{ status: "success" }, { status: "error" }] }),
  empty: [L.overviewIsEmpty(null), L.overviewIsEmpty({ phase, milestones, deliverables: [] }), L.overviewIsEmpty(state)],
}));
"""


@pytest.fixture(scope="module")
def logic() -> dict:
    if _node_major() < 22:
        pytest.skip("needs Node 22+ to import ES modules")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _LOGIC_SCRIPT, STATIC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
def test_timeline_positions_and_entries(logic) -> None:
    # Dated nodes sit at their date; undated ones spread towards the 100% tail.
    assert logic["xs"] == [[1, 0], [2, 100], [3, 100], [4, 100]]
    assert logic["xsNoDates"] == [25, 50, 75]
    entries = logic["entries"]
    assert entries[0] == [1, "done", "已完成", "04-01", False]
    assert ["today", "今天 06-15"] in entries
    assert [3, "planned", "未开始", "待排期", False] in entries
    assert [4, "planned", "未开始", "待排期", False] in entries  # undated ignores its own type/status
    assert [2, "planned", "已超期", "08-29", True] in entries


@needs_node
def test_node_focus_context(logic) -> None:
    assert logic["node"] == 2  # first unfinished node, overdue not skipped
    assert logic["days"] == 75
    assert logic["timing"] == ["待排期", "已超期 3 天", "计划今天完成", "距离计划日期还有 5 天"]
    assert logic["title"] == "主计划待设置"


@needs_node
def test_snapshot_display_rules(logic) -> None:
    display = logic["display"]
    assert display[0] == {"progress": 75, "status": "已逾期", "snapshotAt": "A"}
    assert display[1] == {"progress": 25, "status": "已逾期", "snapshotAt": "B"}
    assert display[2] is None and display[3] is None and display[4] is None
    assert display[5] == {"progress": 75, "status": "已逾期", "snapshotAt": "S"}
    assert logic["merged"] == ["已完成", 100, "100%", None]


@needs_node
def test_progress_rings(logic) -> None:
    pending = logic["pendingRing"]
    assert pending["center"] == "待同步" and pending["progress"] == 0 and pending["color"] == "var(--muted)"
    assert pending["statusText"] == "待首次同步" and pending["tone"] == "primary"
    assert pending["dateLabel"] == "计划完成 06-01；已逾期 14 天（待同步）"
    assert pending["ariaLabel"] == "P，状态 待首次同步，查看明细"
    done = logic["doneRing"]
    assert done["center"] == "100%" and done["color"] == "var(--success)" and done["dateLabel"] == "实际完成 05-02"
    assert done["title"] == "D（已完成）：无"
    assert logic["pctRing"] == "完成度 100%"
    # D1 is done and VDR was reached -> hidden in auto mode; D4 is board-hidden; pending D2 always shown.
    assert logic["allIds"] == ["VPI-T2-D1", "VPI-T2-D2", "VPI-T2-D3"]
    assert logic["autoIds"] == ["VPI-T2-D2", "VPI-T2-D3"]
    assert logic["hint"] == "已隐藏 1 项已完成交付物"
    assert logic["tokenMatch"] is False


@needs_node
def test_detail_rows_and_external_reference(logic) -> None:
    first, second = logic["rows"]
    assert first["index"] == 0 and second["index"] == 2  # payload index kept across board filtering
    assert first["values"] == ["A", "已逾期", None, "30%", None, "内网"]
    assert first["riskNote"]["text"] == "2单超期" and first["statusTone"] == "error"
    assert first["target"] == {"page": "deliverable", "params": {"id": "A"}}
    assert second["values"][1] == "已暂停" and second["values"][3] == "已暂停" and second["statusTone"] == "primary"
    assert second["editable"] is False and second["readOnlyReason"] == "该交付物当前由系统同步维护，手工字段只读。"
    assert second["target"] == {"page": "archive-deliverable", "params": {"job": "aras_ewo"}}
    assert logic["ext"] == [{"name": "E", "code": "DEL-003", "jobKey": "aras_ewo"}, {"name": "U", "code": "未关联项目交付物", "jobKey": ""}]


@needs_node
def test_scheduler_bar_text(logic) -> None:
    running, paused, unknown = logic["sched"]
    assert running["meta"] == "下次自动同步：02:05（共3项已启用交付物）· 上次完成：08:15:30"
    assert running["intervalValue"] == "1800" and running["pauseLabel"] == "暂停调度"
    assert paused["meta"] == "已暂停自动轮询（0项交付物绑定）· 上次完成：暂无"
    assert paused["intervalValue"] == "0" and paused["pauseLabel"] == "恢复调度" and paused["indicatorClass"] == "is-paused"
    assert unknown == "下次自动同步：00:00（共0项已启用交付物）· 上次完成：无"
    assert logic["interval"] == [{"paused": True}, {"intervalSeconds": 3600, "paused": False}, "已暂停交付物自动同步调度。",
                                 "自动同步频率已调整为 每 30 分钟。"]
    assert logic["syncAll"] == "全量同步完成：成功同步 1/2 项交付物。"


@needs_node
def test_deliverable_edit_validation_and_payloads(logic) -> None:
    valid = logic["valid"]
    assert valid["ok"] == {}
    assert valid["missing"] == {"status": "请选择状态", "owner": "负责人为必填项", "plannedDate": "计划完成日期为必填项",
                                "progress": "当前进度为必填项"}
    assert valid["done"] == {"plannedDate": "日期格式应为 YYYY-MM-DD", "progress": "已完成交付物的进度必须为 100",
                             "actualDate": "已完成交付物必须填写实际完成日期"}
    assert valid["undoneActual"] == {"progress": "当前进度必须是 0 到 100 的整数", "actualDate": "未完成的交付物不应填写实际完成日期"}
    assert logic["payload"] == {"status": "进行中", "owner": "王", "plannedDate": "2026-05-01", "actualDate": "", "progress": 40,
                                "note": "n", "updatedAt": "U1"}
    assert logic["notePayload"] == {"status": "进行中", "owner": "王", "plannedDate": "P", "actualDate": None, "progress": 5,
                                    "note": "新备注", "updatedAt": "U2"}
    assert logic["serverFields"] == {"plannedDate": "x", "actualDate": "y"}
    assert logic["dirty"] == [False, True]
    assert logic["errs"] == ["该操作只允许在本机浏览器中执行", "记录已被其他会话更新，请刷新后重试（HTTP 409）", "请求失败（HTTP 500）",
                             "无法连接本地服务"]
    assert logic["empty"] == [True, True, False]
