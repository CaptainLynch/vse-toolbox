# -*- coding: utf-8 -*-
"""project-overview plugin: deliverable / archive-deliverable detail pages.

The pages call the legacy /api endpoints unchanged, so these tests pin the
endpoint paths the modules reference, the import graph, and round trips of
payloads built by the pure modules (under Node) through the real Flask API.
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
PAGE_MODULES = ["deliverable.js", "archive-deliverable.js"]
OWN_MODULES = sorted(p.relative_to(STATIC).as_posix() for p in (STATIC / "deliverable").glob("*.js"))
ALL_SOURCES = PAGE_MODULES + OWN_MODULES
PURE_MODULES = ["deliverable/format.js", "deliverable/api.js", "deliverable/display.js", "deliverable/policy-logic.js",
                "deliverable/form-state.js", "deliverable/chart-math.js"]
PHASE = "VPI-T2"


@pytest.fixture()
def app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "deliverable-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    application = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"])
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):  # type: ignore[no-untyped-def]
    return app.test_client()


def _overview(client) -> dict:  # type: ignore[no-untyped-def]
    body = client.get(f"/api/project-status?phase={PHASE}").get_json()
    assert body["ok"] is True, body
    return body["data"]


def _item(client, deliverable_id: str) -> dict:  # type: ignore[no-untyped-def]
    return next(d for d in _overview(client)["deliverables"] if d["id"] == deliverable_id)


# ---------------------------------------------------------------------------
# manifest / static contract


def test_plugin_loads_with_detail_pages(client) -> None:
    data = client.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "project-overview")
    assert record["status"] == "loaded", record.get("error")
    pages = {page["id"]: page for page in record["pages"]}
    assert pages["deliverable"]["module"] == "deliverable.js"
    assert pages["archive-deliverable"]["module"] == "archive-deliverable.js"


@pytest.mark.parametrize("name", ALL_SOURCES)
def test_modules_are_served_as_javascript(client, name: str) -> None:
    response = client.get(f"/plugins/project-overview/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_stylesheet_is_served_and_scoped(client) -> None:
    response = client.get("/plugins/project-overview/static/deliverable.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"
    css = (STATIC / "deliverable.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    for selector_list in re.findall(r"([^{}@]+)\{[^{}]*\}", css):
        for selector in selector_list.split(","):
            assert ".overview-deliverable-detail-view" in selector, selector


def _imports(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    return re.findall(r'(?:from|import)\s*\(?\s*"([^"]+)"', source)


def test_modules_import_only_shipped_files() -> None:
    host_allowed = {"/static/host/vendor/preact-htm.js", "/static/host/kit.js"}
    dynamic_allowed = {"/plugins/system-query/static/grid.js"}
    for rel in ALL_SOURCES:
        path = STATIC / rel
        for spec in _imports(path):
            if spec in host_allowed:
                assert (REPO_ROOT / "web" / spec.lstrip("/")).is_file(), spec
            elif spec in dynamic_allowed:
                assert (REPO_ROOT / "plugins" / "system_query" / "static" / "grid.js").is_file()
            else:
                assert spec.startswith("./"), (rel, spec)
                assert (path.parent / spec).resolve().is_file(), (rel, spec)


def test_pure_modules_have_no_browser_imports() -> None:
    for rel in PURE_MODULES:
        for spec in _imports(STATIC / rel):
            assert spec.startswith("./") and (STATIC / "deliverable" / spec).resolve().relative_to(STATIC), (rel, spec)
            assert f"deliverable/{spec[2:]}" in PURE_MODULES, (rel, spec)


def test_sources_avoid_unsafe_sinks() -> None:
    for rel in ALL_SOURCES:
        source = (STATIC / rel).read_text(encoding="utf-8")
        assert "innerHTML" not in source, rel
        assert "dangerouslySetInnerHTML" not in source, rel
        assert "console.log" not in source, rel
        assert "web/static/app.js" not in source, rel


def _api_paths() -> set[str]:
    """Every /api path literal in the sources, `${...}` replaced by a placeholder, query stripped."""
    paths: set[str] = set()
    for rel in ALL_SOURCES:
        source = (STATIC / rel).read_text(encoding="utf-8")
        for match in re.finditer(r"/api/", source):
            i, out = match.start(), []
            while i < len(source):
                ch = source[i]
                if source.startswith("${", i):
                    depth, j = 1, i + 2
                    while j < len(source) and depth:
                        depth += {"{": 1, "}": -1}.get(source[j], 0)
                        j += 1
                    inner = source[i + 2 : j - 1]
                    if "`" in inner:
                        break
                    out.append("X1")
                    i = j
                    continue
                if ch in "`\"'?\n ":
                    break
                out.append(ch)
                i += 1
            paths.add("".join(out))
    return paths


def test_every_api_path_exists_in_url_map(app) -> None:
    from werkzeug.exceptions import MethodNotAllowed, NotFound

    adapter = app.url_map.bind("localhost")
    paths = _api_paths()
    expected = {
        "/api/project-status", "/api/project-status/deliverables/X1", "/api/project-status/deliverables/X1/update-policy",
        "/api/project-status/deliverables/X1/sync-now", "/api/scheduled-archive/jobs/X1/sync-now", "/api/scheduled-archive/runs",
        "/api/deliverable-forms/X1/view", "/api/deliverable-forms/X1/rows", "/api/project-status/section-rollup",
    }
    assert expected <= paths, expected - paths
    missing = []
    for path in sorted(paths):
        # Placeholders stand in for ids; run ids are integer-typed routes.
        candidates = (path, path.replace("X1", "1"))
        for candidate in candidates:
            try:
                adapter.match(candidate, method="GET")
                break
            except MethodNotAllowed:
                break
            except NotFound:
                continue
        else:
            missing.append(path)
    assert not missing, missing


def test_archive_jobs_payload_has_fields_the_page_reads(client) -> None:
    jobs = client.get("/api/scheduled-archive/jobs").get_json()["data"]
    assert jobs
    needed = {"jobKey", "enabled", "syncState", "freshness", "lastSuccessAt", "lastAttemptAt", "lastErrorMessage",
              "credentialAvailable", "filters", "formKey"}
    for job in jobs:
        assert needed <= set(job), needed - set(job)
    assert {"aras_paa", "tdc_sor", "tdc_data_model"} <= {job["jobKey"] for job in jobs}


def test_runs_endpoint_answers_archive_history_query(client) -> None:
    body = client.get("/api/scheduled-archive/runs?jobKey=tdc_sor&limit=12").get_json()
    assert body["ok"] is True and isinstance(body["data"], list)


# ---------------------------------------------------------------------------
# Node: pure logic + payload round trips


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
        ["node", "--input-type=module", "-e", script, STATIC.as_uri(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@needs_node
@pytest.mark.parametrize("rel", ALL_SOURCES)
def test_node_check_passes(rel: str) -> None:
    result = subprocess.run(["node", "--check", str(STATIC / rel)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


_LOGIC_SCRIPT = r"""
const base = process.argv[1];
const F = await import(base + "/deliverable/format.js");
const A = await import(base + "/deliverable/api.js");
const P = await import(base + "/deliverable/policy-logic.js");
const S = await import(base + "/deliverable/form-state.js");
const C = await import(base + "/deliverable/chart-math.js");
const local = A.requestError({ok: false, error: {type: "LocalAccessRequired", message: "local only"}}, 403);
const conflict = A.requestError({ok: false, error: {type: "Conflict", message: "记录已被其他会话更新，请刷新后重试", fields: {note: "x"}}}, 409);
const fieldOptions = [["dept", "部门"], ["state", "状态"]];
const blocks = C.chartLabelBlocks([{label: "按部门", sourceField: "missing", groups: [{name: "A", members: ["x", "y"]}]}], fieldOptions);
const labelsPayload = C.buildChartLabelsPayload(blocks);
console.log(JSON.stringify({
  redacted: F.redactSensitiveText("password=hunter2 token: abc Bearer xyz"),
  local: local.message, localOnly: A.isLocalOnlyError(local), localPlain: A.plainErrorMessage(local, "fb"),
  conflict: conflict.message, conflictFields: conflict.fields, conflictLocal: A.isLocalOnlyError(conflict),
  statNull: F.statisticsNumberText(null),
  errorsEmpty: P.validateDeliverableDraft({status: "", owner: "", plannedDate: "", actualDate: "", progress: "", note: ""}),
  errorsDone: P.validateDeliverableDraft({status: "已完成", owner: "a", plannedDate: "2026-09-01", actualDate: "", progress: "80", note: ""}),
  errorsOk: P.validateDeliverableDraft({status: "进行中", owner: "a", plannedDate: "2026-09-01", actualDate: "", progress: "40", note: ""}),
  serverErrors: P.serverFieldErrors({planned_date: "bad", other: "ignored"}),
  paa: P.buildPaaInteractiveFilters({paaNo: " PAA-1 ", ewoNo: "", vehicleKeyword: "K", unknown: "u"}),
  paaPayload: P.buildInteractiveArasPayload("paa", {paa_no: "PAA-1", bogus: "x"}),
  stateEmpty: P.interactiveQueryResultState("paa", {rows: []}, "PAA-1"),
  stateMatch: P.interactiveQueryResultState("paa", {rows: [{paaNo: "PAA-1"}]}, "PAA-1"),
  stateMiss: P.interactiveQueryResultState("paa", {rows: [{paaNo: "PAA-2"}]}, "PAA-1"),
  err401: P.formatInteractiveArasError({status: 401}),
  archiveHref: P.associationHref({type: "archive_job", jobKey: "tdc_sor", href: "#archive-deliverable/tdc_sor"}),
  rollup: S.buildRollupPayload([{target: " 车身部 ", aliases: [" 车身 ", "", "白车身"]}]),
  blockSource: blocks.length ? blocks[0].sourceField : null,
  blockMembers: blocks.length ? blocks[0].groups[0].members : null,
  labelsPayload,
}));
"""


@needs_node
def test_pure_logic_helpers() -> None:
    data = _run_node(_LOGIC_SCRIPT)
    assert "hunter2" not in data["redacted"] and "abc" not in data["redacted"] and "xyz" not in data["redacted"]
    assert data["local"] == "该操作只允许在本机浏览器中执行（HTTP 403）"
    assert data["localOnly"] is True and data["localPlain"] == "该操作只允许在本机浏览器中执行"
    assert data["conflict"] == "记录已被其他会话更新，请刷新后重试（HTTP 409）"
    assert data["conflictFields"] == {"note": "x"} and data["conflictLocal"] is False
    assert data["statNull"] == "0"
    assert set(data["errorsEmpty"]) == {"status", "owner", "plannedDate", "progress"}
    assert set(data["errorsDone"]) == {"progress", "actualDate"}
    assert data["errorsOk"] == {}
    assert data["serverErrors"] == {"plannedDate": "bad"}
    assert data["paa"] == {"paa_no": "PAA-1", "vehicle_keyword": "K"}
    assert data["paaPayload"]["filters"] == {"paa_no": "PAA-1"}
    assert data["paaPayload"]["auth_mode"] == "browser"
    assert (data["stateEmpty"], data["stateMatch"], data["stateMiss"]) == ("empty", "matched", "no_match")
    assert data["err401"].startswith("未认证")
    assert data["archiveHref"] == "#p/project-overview/archive-deliverable?job=tdc_sor"
    assert data["rollup"] == {"targets": [{"target": "车身部", "aliases": ["车身", "白车身"]}]}
    assert data["blockSource"] == "dept"
    assert data["blockMembers"] == "x、y"
    assert data["labelsPayload"]["labels"][0]["sourceField"] == "dept"


_EDIT_SCRIPT = r"""
const P = await import(process.argv[1] + "/deliverable/policy-logic.js");
const item = JSON.parse(process.argv[2]);
const values = {...P.draftValuesFromItem(item), status: "进行中", owner: "插件冒烟", progress: "45", note: "插件详情页保存", actualDate: "",
                plannedDate: item.plannedDate || "2026-12-31"};
const errors = P.validateDeliverableDraft(values);
const notePatch = P.buildNotePatch({...item, owner: "插件冒烟", status: "进行中", progress: 45, actualDate: ""}, "行内备注");
console.log(JSON.stringify({errors, patch: P.buildDeliverablePatch(values, item), notePatch}));
"""


@needs_node
def test_manual_edit_patch_round_trip(client) -> None:
    item = _item(client, f"{PHASE}-D1")
    assert item["manualEditable"] is True
    built = _run_node(_EDIT_SCRIPT, json.dumps(item))
    assert built["errors"] == {}
    response = client.patch(f"/api/project-status/deliverables/{item['id']}", json=built["patch"])
    assert response.status_code == 200, response.get_json()
    saved = next(d for d in response.get_json()["data"]["projectStatus"]["deliverables"] if d["id"] == item["id"])
    assert (saved["owner"], saved["progress"], saved["note"]) == ("插件冒烟", 45, "插件详情页保存")

    # The stale record version is rejected with the legacy conflict.
    stale = client.patch(f"/api/project-status/deliverables/{item['id']}", json=built["patch"])
    assert stale.status_code == 409

    # Inline note edit built from the fresh record succeeds.
    fresh = _item(client, item["id"])
    note = _run_node(_EDIT_SCRIPT, json.dumps(fresh))["notePatch"]
    response = client.patch(f"/api/project-status/deliverables/{item['id']}", json=note)
    assert response.status_code == 200, response.get_json()
    assert _item(client, item["id"])["note"] == "行内备注"


@needs_node
def test_mapped_deliverable_patch_is_read_only(client) -> None:
    item = next(d for d in _overview(client)["deliverables"] if d["manualEditable"] is False)
    built = _run_node(_EDIT_SCRIPT, json.dumps(item))
    response = client.patch(f"/api/project-status/deliverables/{item['id']}", json=built["patch"])
    assert response.status_code == 409
    assert response.get_json()["error"]["type"] == "MappedDeliverableReadOnly"


_POLICY_SCRIPT = r"""
const P = await import(process.argv[1] + "/deliverable/policy-logic.js");
const [item, policy, matchValue] = JSON.parse(process.argv[2]);
const caps = P.capabilitiesOf(item);
let v = P.bindingInitialValues(item, policy, caps);
const firstKey = Object.keys(v.match)[0];
v = {...v, mode: "hybrid", interval: "30", match: {...v.match, [firstKey]: matchValue},
     authority: {...v.authority, note: true}};
const payload = P.buildPolicyPayload(item, caps, policy, v);
const evidence = P.buildEvidencePayload(caps, v, payload);
const readiness = P.bindingReadiness(payload, {storedPolicy: policy, vaultConfigured: false, defaultMap: P.defaultMappingFor(item, caps)});
console.log(JSON.stringify({firstKey, payload, evidence, readiness}));
"""


@needs_node
@pytest.mark.parametrize("deliverable_id,match_value", [
    (f"{PHASE}-D3", "EWO-2026-0001"),
    (f"{PHASE}-D5", "INC-1"),
    (f"{PHASE}-D2", "PROC-1"),
])
def test_binding_editor_policy_round_trip(client, deliverable_id: str, match_value: str) -> None:
    item = _item(client, deliverable_id)
    policy = client.get(f"/api/project-status/deliverables/{deliverable_id}/update-policy").get_json()["data"]
    built = _run_node(_POLICY_SCRIPT, json.dumps([item, policy, match_value]))
    payload = built["payload"]
    assert payload["matchRule"][built["firstKey"]] == match_value
    assert built["evidence"] is not None and match_value in built["evidence"]["filters"].values()
    assert built["readiness"]["ready"] is False
    response = client.patch(f"/api/project-status/deliverables/{deliverable_id}/update-policy", json=payload)
    assert response.status_code == 200, response.get_json()
    saved = client.get(f"/api/project-status/deliverables/{deliverable_id}/update-policy").get_json()["data"]
    assert saved["mode"] == "hybrid"
    assert saved["intervalMinutes"] == 30
    assert saved["matchRule"][built["firstKey"]] == match_value
    assert saved["fieldAuthority"]["note"] == ("automatic" if payload["mapping"].get("note") else "manual")


_ROLLUP_SCRIPT = r"""
const S = await import(process.argv[1] + "/deliverable/form-state.js");
const draft = S.cloneRollupTargets([{target: "车身部", aliases: ["车身", " 白车身 "]}]);
console.log(JSON.stringify(S.buildRollupPayload(draft)));
"""


@needs_node
def test_rollup_payload_round_trip(client) -> None:
    payload = _run_node(_ROLLUP_SCRIPT)
    response = client.put("/api/project-status/section-rollup", json=payload)
    assert response.status_code == 200, response.get_json()
