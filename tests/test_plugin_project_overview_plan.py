# -*- coding: utf-8 -*-
"""project-overview plugin, 主计划维护 page: static contract, API round trip
with the payload the page builds, and the pure logic module under Node."""

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
PLAN_SOURCES = [STATIC / "plan.js", *sorted((STATIC / "plan").glob("*.js"))]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "plan-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["project-overview"])
    app.config.update(TESTING=True)
    return app.test_client()


def test_plugin_loads_with_plan_page(client) -> None:
    data = client.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "project-overview")
    assert record["status"] == "loaded", record.get("error")
    page = next(p for p in record["pages"] if p["id"] == "plan")
    assert page == {"id": "plan", "title": "主计划维护", "kind": "module", "module": "plan.js"}


@pytest.mark.parametrize("name", ["plan.js", "plan/logic.js", "plan/phase.js", "plan/milestones.js", "plan/guard.js"])
def test_plan_modules_are_served_as_javascript(client, name: str) -> None:
    response = client.get(f"/plugins/project-overview/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_plan_stylesheet_is_served(client) -> None:
    response = client.get("/plugins/project-overview/static/plan.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_plan_modules_import_only_shipped_files() -> None:
    host_allowed = {"/static/host/vendor/preact-htm.js", "/static/host/kit.js"}
    for source in PLAN_SOURCES:
        text = source.read_text(encoding="utf-8")
        for spec in re.findall(r'(?:from|import)\s+"([^"]+)"', text):
            if spec.startswith("/static/host/"):
                assert spec in host_allowed, (source.name, spec)
                assert (REPO_ROOT / "web" / spec.lstrip("/")).is_file(), spec
            else:
                assert spec.startswith("."), (source.name, spec)
                assert (source.parent / spec).resolve().is_file(), (source.name, spec)
    assert "import " not in (STATIC / "plan" / "logic.js").read_text(encoding="utf-8")


def test_plan_sources_have_no_unsafe_patterns() -> None:
    for source in PLAN_SOURCES:
        text = source.read_text(encoding="utf-8")
        assert "innerHTML" not in text and "dangerouslySetInnerHTML" not in text, source.name
        assert "console.log" not in text, source.name


def test_every_api_path_exists_in_url_map(client) -> None:
    rules = {rule.rule for rule in client.application.url_map.iter_rules()}
    found: set[str] = set()
    for source in PLAN_SOURCES:
        for raw in re.findall(r"[`\"'](/api/[^`\"'?]*)", source.read_text(encoding="utf-8")):
            found.add(re.sub(r"\$\{PROJECT_PHASE_ID\}", "<phase_id>", raw))
    assert found == {
        "/api/project-status",
        "/api/project-status/phases/<phase_id>",
        "/api/project-status/phases/<phase_id>/milestones",
    }
    assert found <= rules, found - rules


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


def _run_node(script: str, *args: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, (STATIC / "plan").as_uri(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
def test_node_check_all_plan_sources() -> None:
    for source in PLAN_SOURCES:
        subprocess.run(["node", "--check", str(source)], check=True, capture_output=True)


_BUILD_SCRIPT = r"""
const L = await import(process.argv[1] + "/logic.js");
const saved = JSON.parse(process.argv[2]);
let rows = L.milestoneRowsFrom(saved.milestones);
rows = rows.map((r, i) => i === 0 ? L.updateRow(L.updateRow(r, "name", " 冒烟节点 "), "date", process.argv[3]) : r);
rows = rows.map((r, i) => i === 0 ? L.updateRow(r, "type", "done") : r);
rows = [...rows, {...L.newMilestoneRow(1, rows.length), name: "新增节点A"}];
rows = L.moveRow(rows, "new-1", -1);
console.log(JSON.stringify({
  dirty: L.milestoneDraftDirty(saved.milestones, rows),
  clean: L.milestoneDraftDirty(saved.milestones, L.milestoneRowsFrom(saved.milestones)),
  errors: L.validateMilestoneRows(rows, saved.phase),
  payload: L.buildMilestonePayload(rows, saved.phase.updatedAt),
}));
"""


@needs_node
def test_milestone_round_trip_with_page_payload(client) -> None:
    status = client.get("/api/project-status?phase=VPI-T2").get_json()["data"]
    phase = status["phase"]
    data = _run_node(_BUILD_SCRIPT, json.dumps(status, ensure_ascii=False), phase["startDate"])
    assert data["dirty"] is True and data["clean"] is False
    assert data["errors"] == {}
    payload = data["payload"]
    count = len(status["milestones"])
    assert len(payload["milestones"]) == count + 1
    assert payload["milestones"][0] == {
        "id": status["milestones"][0]["id"], "name": "冒烟节点", "date": phase["startDate"],
        "status": "已完成", "type": "done", "sortOrder": 1,
    }
    assert payload["milestones"][count - 1]["name"] == "新增节点A"
    assert payload["milestones"][count - 1]["id"] is None

    response = client.patch("/api/project-status/phases/VPI-T2/milestones", json=payload)
    body = response.get_json()
    assert response.status_code == 200, body
    names = [m["name"] for m in body["data"]["projectStatus"]["milestones"]]
    assert names[0] == "冒烟节点" and names[count - 1] == "新增节点A" and len(names) == count + 1
    reloaded = client.get("/api/project-status?phase=VPI-T2").get_json()["data"]
    assert reloaded["milestones"][0]["status"] == "已完成"
    assert reloaded["milestones"][0]["date"] == phase["startDate"]

    # Saving again with the stale version is a 409 conflict.
    stale = client.patch("/api/project-status/phases/VPI-T2/milestones", json=payload)
    assert stale.status_code == 409
    assert stale.get_json()["error"]["message"] == "主计划已被其他会话更新，请刷新后重试"


def test_phase_patch_with_page_payload(client) -> None:
    phase = client.get("/api/project-status?phase=VPI-T2").get_json()["data"]["phase"]
    body = {"displayName": "F610S-新", "status": phase["status"], "startDate": phase["startDate"],
            "endDate": phase["endDate"], "updatedAt": phase["updatedAt"]}
    response = client.patch("/api/project-status/phases/VPI-T2", json=body)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["projectStatus"]["phase"]["displayName"] == "F610S-新"


_LOGIC_SCRIPT = r"""
const L = await import(process.argv[1] + "/logic.js");
const phase = {id: "VPI-T2", displayName: "F610S", status: "进行中", startDate: "2026-04-08", endDate: "2026-08-30", today: "2026-06-01", updatedAt: "v1"};
const row = (localId, extra) => ({localId, id: null, name: "N" + localId, date: "", status: "", type: "planned", sortOrder: 1, ...extra});
const rows = [row("a"), row("b"), row("c")];
console.log(JSON.stringify({
  required: L.validateMilestoneRows([row("a", {name: "  "})], phase),
  tooLong: L.validateMilestoneRows([row("a", {name: "x".repeat(101)})], phase),
  dup: L.validateMilestoneRows([row("a", {name: "X"}), row("b", {name: " X "})], phase),
  unscheduledOk: L.validateMilestoneRows([row("a")], phase),
  unscheduledBad: L.validateMilestoneRows([L.updateRow(row("a"), "type", "current")], phase),
  badFormat: L.validateMilestoneRows([row("a", {date: "2026/05/01"})], phase),
  outOfRange: L.validateMilestoneRows([row("a", {date: "2026-09-01"})], phase),
  doneFuture: L.validateMilestoneRows([L.updateRow(row("a", {date: "2026-07-01"}), "type", "done")], phase),
  plannedPast: L.validateMilestoneRows([row("a", {date: "2026-04-10"})], phase),
  overdueStatus: L.updateRow(row("a"), "type", "overdue").status,
  overduePayload: L.buildMilestonePayload([L.updateRow(row("a"), "type", "overdue")], "v1").milestones[0],
  typeFromStatus: L.milestoneRowsFrom([{id: 3, name: "M", date: null, status: "已完成", type: "planned"}])[0],
  up: L.moveRow(rows, "b", -1).map((r) => r.localId),
  topNoop: L.moveRow(rows, "a", -1) === rows,
  down: L.moveRow(rows, "b", 1).map((r) => r.localId),
  removeMid: L.removeRow(rows, "b").focus,
  removeLast: L.removeRow(rows, "c").focus,
  removeOnly: L.removeRow([row("a")], "a"),
  server: L.mapServerFieldErrors({"milestones.1.date": "节点日期必须位于阶段周期内", "milestones.0.name": "dup", "updatedAt": "缺少阶段版本"}, rows),
  phaseOk: L.buildPhasePayload(L.phaseDraftFrom(phase)),
  phaseName: L.buildPhasePayload({...L.phaseDraftFrom(phase), displayName: " "}),
  phaseStatus: L.buildPhasePayload({...L.phaseDraftFrom(phase), status: "x"}),
  phaseDate: L.buildPhasePayload({...L.phaseDraftFrom(phase), endDate: ""}),
  phaseOrder: L.buildPhasePayload({...L.phaseDraftFrom(phase), endDate: "2026-01-01"}),
  phaseDirty: [L.phaseDraftDirty(phase, L.phaseDraftFrom(phase)), L.phaseDraftDirty(phase, {...L.phaseDraftFrom(phase), endDate: "2026-08-31"})],
  rename: L.buildPhaseNamePayload(phase, " F610S-B "),
  renameSame: L.buildPhaseNamePayload(phase, "F610S"),
  renameEmpty: L.buildPhaseNamePayload(phase, "  "),
  err403: L.requestErrorText({status: 403, message: "此操作仅允许从本机访问"}),
  err409: L.requestErrorText({status: 409, message: "主计划已被其他会话更新，请刷新后重试"}),
  errNet: L.requestErrorText({status: 0, message: "无法连接本地服务"}),
  cleared: L.clearFieldError({"a.name": "x", "a.date": "y"}, "a", "name"),
  empty: [L.isEmptyStatus(null), L.isEmptyStatus({phase, milestones: [1], deliverables: []}), L.isEmptyStatus({phase, milestones: [1], deliverables: [1]})],
  display: [L.displayValue(""), L.displayValue(null), L.displayValue("x")],
}));
"""


@needs_node
def test_logic_validation_ordering_and_dates() -> None:
    d = _run_node(_LOGIC_SCRIPT)
    assert d["required"] == {"a.name": "节点名称为必填项"}
    assert d["tooLong"] == {"a.name": "节点名称不能超过 100 个字符"}
    assert d["dup"] == {"b.name": "节点名称不能重复"}
    assert d["unscheduledOk"] == {}
    assert d["unscheduledBad"] == {"a.date": "空日期节点状态必须为未开始"}
    assert d["badFormat"] == {"a.date": "日期格式应为 YYYY-MM-DD"}
    assert d["outOfRange"] == {"a.date": "节点日期需在阶段周期 2026-04-08 至 2026-08-30 内"}
    assert d["doneFuture"] == {"a.date": "已达成节点日期不能晚于当前日期 2026-06-01"}
    assert d["plannedPast"] == {}
    assert d["overdueStatus"] == "已超期"
    assert d["overduePayload"] == {"id": None, "name": "Na", "date": "", "status": "已超期", "type": "planned", "sortOrder": 1}
    assert d["typeFromStatus"]["type"] == "done" and d["typeFromStatus"]["date"] == ""
    assert d["up"] == ["b", "a", "c"] and d["topNoop"] is True and d["down"] == ["a", "c", "b"]
    assert d["removeMid"] == "c" and d["removeLast"] == "b"
    assert d["removeOnly"] == {"rows": [], "focus": None}
    assert d["server"] == {"b.date": "节点日期必须位于阶段周期内", "a.name": "dup", "draft": "缺少阶段版本"}
    assert d["phaseOk"] == {"payload": {"displayName": "F610S", "status": "进行中", "startDate": "2026-04-08", "endDate": "2026-08-30", "updatedAt": "v1"}}
    assert d["phaseName"] == {"error": "主计划名称不能为空"}
    assert d["phaseStatus"] == {"error": "阶段状态无效"}
    assert d["phaseDate"] == {"error": "日期格式应为 YYYY-MM-DD"}
    assert d["phaseOrder"] == {"error": "计划完成日期不能早于开始日期"}
    assert d["phaseDirty"] == [False, True]
    assert d["rename"] == {"displayName": "F610S-B", "status": "进行中", "startDate": "2026-04-08", "endDate": "2026-08-30", "updatedAt": "v1"}
    assert d["renameSame"] is None and d["renameEmpty"] is None
    assert d["err403"] == "该操作只允许在本机浏览器中执行"
    assert d["err409"] == "主计划已被其他会话更新，请刷新后重试（HTTP 409）"
    assert d["errNet"] == "无法连接本地服务"
    assert d["cleared"] == {"a.date": "y"}
    assert d["empty"] == [True, True, False]
    assert d["display"] == ["-", "-", "x"]
