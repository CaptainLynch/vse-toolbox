# -*- coding: utf-8 -*-
"""scheduled-archive plugin: manifest/static contract and the page's data module.

The page reuses the legacy /api/scheduled-archive/* endpoints, so these tests
also pin the response fields and PATCH payload shape the module depends on.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import web.app as web_app
from services.scheduled_archive_connectors import archive_filter_names

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "scheduled_archive"
STATIC = PLUGIN_DIR / "static"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "archive-plugin.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"], plugin_only=["scheduled-archive"])
    app.config.update(TESTING=True)
    return app.test_client()


def test_plugin_loads_with_jobs_module_page(client) -> None:
    data = client.get("/api/host/manifest").get_json()["data"]
    record = next(p for p in data["plugins"] if p["id"] == "scheduled-archive")
    assert record["status"] == "loaded", record.get("error")
    assert record["pages"] == [{"id": "jobs", "title": "自动下载与留存", "kind": "module", "module": "jobs.js"}]
    nav = next(item for item in data["nav"] if item["plugin"] == "scheduled-archive")
    assert {"page": "jobs", "title": "自动归档（新）", "order": 50}.items() <= nav.items()


@pytest.mark.parametrize("name", ["jobs.js", "archive_data.js"])
def test_page_modules_are_served_as_javascript(client, name: str) -> None:
    response = client.get(f"/plugins/scheduled-archive/static/{name}")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"


def test_page_stylesheet_is_served(client) -> None:
    response = client.get("/plugins/scheduled-archive/static/jobs.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_page_imports_only_host_runtime_and_own_modules() -> None:
    source = (STATIC / "jobs.js").read_text(encoding="utf-8")
    specs = re.findall(r'from\s+"([^"]+)"', source)
    allowed = {"/static/host/vendor/preact-htm.js", "/static/host/api.js", "/static/host/kit.js", "./archive_data.js"}
    assert set(specs) <= allowed, specs
    # The data module must stay importable under Node (no browser-only imports).
    assert "import " not in (STATIC / "archive_data.js").read_text(encoding="utf-8")


def test_legacy_job_payload_has_fields_the_page_reads(client) -> None:
    jobs = client.get("/api/scheduled-archive/jobs").get_json()["data"]
    assert jobs, "fresh DB is expected to seed builtin archive jobs"
    needed = {
        "jobKey", "templateKey", "sourceType", "displayName", "builtin", "enabled", "credentialConfigured",
        "credentialAvailable", "intervalMinutes", "filters", "allowedFilterNames", "outputSubdir",
        "outputDirectory", "retryPolicy", "syncState", "freshness", "lastAttemptAt", "lastSuccessAt",
        "lastErrorType", "lastErrorMessage", "updatedAt", "deliverableId",
    }
    for job in jobs:
        assert needed <= set(job), needed - set(job)


# ---------------------------------------------------------------------------
# Node: pure data-module logic


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
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


_LOGIC_SCRIPT = r"""
const D = await import(process.argv[1] + "/archive_data.js");
const job = {
  jobKey: "tdc_sor", templateKey: "tdc_sor", enabled: false, credentialConfigured: false,
  intervalMinutes: 30, retryPolicy: {max_attempts: 1}, filters: {processType: "定点", extra: 1},
  outputSubdir: "legacy", outputDirectory: "", updatedAt: "2026-09-01T00:00:00Z",
};
const form = D.initialForm(job, true);
const ok = D.buildUpdatePayload(job, {...form, outputDirectory: ""});
const withDir = D.buildUpdatePayload(job, {...form, outputDirectory: "D:\\VSE"});
const fields = D.filterFieldsFor(job);
console.log(JSON.stringify({
  form,
  ok,
  withDirSubdir: withDir.payload.outputSubdir,
  enableNoCred: D.buildUpdatePayload(job, {...form, enabled: true, credentialRef: ""}).errors,
  enableClear: Object.keys(D.buildUpdatePayload(job, {...form, enabled: true, clearCredential: true}).errors),
  clearOnly: D.buildUpdatePayload({...job, credentialConfigured: true}, {...form, credentialRef: "", clearCredential: true}).payload.credentialRef,
  retryBad: D.buildUpdatePayload(job, {...form, retryMaxAttempts: "3"}).errors,
  intervalBad: Object.keys(D.buildUpdatePayload(job, {...form, intervalMinutes: "2"}).errors),
  jsonBad: D.buildUpdatePayload(job, {...form, filtersJson: "{"}).errors,
  jsonArray: D.buildUpdatePayload(job, {...form, filtersJson: "[]"}).errors,
  merged: D.mergeFieldFilters(fields, {processType: "", carTypeProject: "F999X"}, {processType: "定点", extra: 1}),
  lists: D.collectFilterValues({projectNames: "A, B\nC", ncrNo: "  "}),
  prefill: D.planNamePrefill(fields, {}, D.filterInputs(fields, {}), "F999X 主计划"),
  prefillExplicit: D.planNamePrefill(fields, {carTypeProject: ""}, D.filterInputs(fields, {}), "F999X"),
  hashJob: D.jobFromHash("#p/scheduled-archive/jobs?job=tdc%5Fsor&x=1"),
  hashNone: D.jobFromHash("#p/scheduled-archive/jobs"),
  hashBuilt: D.jobHash("custom job"),
  picked: D.pickSelectedJob([{jobKey: "a"}, {jobKey: "b"}], "b").jobKey,
  pickedMissing: D.pickSelectedJob([{jobKey: "a"}], "zzz").jobKey,
  syncOk: D.summarizeSyncResult({exitCode: 0, results: [{jobKey: "tdc_sor", outcome: "completed"}]}, "tdc_sor"),
  syncAuth: D.summarizeSyncResult({exitCode: 1, results: [{jobKey: "tdc_sor", outcome: "failed", errorType: "authentication_error", errorMessage: "登录失效", remedy: null}]}, "tdc_sor"),
  syncNotReady: D.summarizeSyncResult({exitCode: 2, results: [{jobKey: "tdc_sor", outcome: "not_ready", errorType: "job_not_ready", remedy: "bind_domain_credential"}]}, "tdc_sor"),
  authAuth: D.isAuthFailure({remedy: "refresh_domain_credential"}),
  authStatus: D.isAuthFailure({status: 401}),
  authOther: D.isAuthFailure({errorType: "timeout"}),
  create: D.buildCreatePayload({templateKey: "aras_ewo", displayName: "  每日 ", copyFromJobKey: ""}),
  createNoName: D.buildCreatePayload({templateKey: "aras_ewo", displayName: " "}),
  tdcTemplates: D.templatesForSource("tdc").map((t) => t.key),
  chips: [D.syncStateChip("failed"), D.runStateChip("partial"), D.freshnessChip(null)],
  canSync: [D.canSyncNow({enabled: true, credentialConfigured: true}), D.canSyncNow({enabled: true, credentialConfigured: true, credentialAvailable: false})],
  filterNames: Object.fromEntries(Object.entries(D.FILTER_FIELDS).map(([k, v]) => [k, v.map((f) => f.name)])),
  templateKeys: D.TEMPLATES.map((t) => t.key),
}));
"""


@needs_node
def test_data_module_validation_and_helpers() -> None:
    data = _run_node(_LOGIC_SCRIPT)
    assert data["form"]["credentialRef"] == "domain"  # 未绑定且凭据库可用 → 预选统一域账号
    assert data["form"]["retryMaxAttempts"] == "1"
    assert data["ok"]["payload"] == {
        "enabled": False,
        "intervalMinutes": 30,
        "filters": {"processType": "定点", "extra": 1},
        "outputSubdir": "legacy",
        "outputDirectory": "",
        "retryPolicy": {"max_attempts": 1},
        "updatedAt": "2026-09-01T00:00:00Z",
        "credentialRef": "domain",
    }
    assert data["withDirSubdir"] == ""
    assert "credentialRef" in data["enableNoCred"]
    assert data["enableClear"] == ["enabled", "clearAlias"]
    assert data["clearOnly"] is None
    assert "retryPolicy" in data["retryBad"]
    assert data["intervalBad"] == ["intervalMinutes"]
    assert data["jsonBad"] == {"filters": "JSON 格式解析失败，请检查输入语法"}
    assert data["jsonArray"] == {"filters": "高级下载条件必须是 JSON 对象"}
    assert data["merged"] == {"extra": 1, "carTypeProject": "F999X"}
    assert data["lists"] == {"projectNames": ["A", "B", "C"]}
    assert data["prefill"]["carTypeProject"] == "F999X 主计划"
    assert data["prefillExplicit"] is None  # 显式清空优先于主计划名称
    assert data["hashJob"] == "tdc_sor"
    assert data["hashNone"] == ""
    assert data["hashBuilt"] == "#p/scheduled-archive/jobs?job=custom%20job"
    assert data["picked"] == "b"
    assert data["pickedMissing"] == "a"
    assert data["syncOk"]["ok"] is True
    assert data["syncAuth"] == {"ok": False, "message": "登录失效", "remedy": "refresh_domain_credential", "errorType": "authentication_error"}
    assert data["syncNotReady"]["remedy"] == "bind_domain_credential"
    assert data["authAuth"] is True and data["authStatus"] is True and data["authOther"] is False
    assert data["create"] == {"payload": {"templateKey": "aras_ewo", "displayName": "每日"}}
    assert data["createNoName"] == {"error": "任务名称为必填项"}
    assert data["tdcTemplates"] == ["tdc_data_model", "tdc_sor"]
    assert [chip["tone"] for chip in data["chips"]] == ["is-error", "is-warning", "is-muted"]
    assert data["canSync"] == [True, False]


@needs_node
def test_filter_fields_stay_within_backend_contract() -> None:
    data = _run_node(_LOGIC_SCRIPT)
    assert sorted(data["templateKeys"]) == sorted(data["filterNames"])
    for template_key, names in data["filterNames"].items():
        allowed = set(archive_filter_names(template_key))
        assert set(names) <= allowed, (template_key, set(names) - allowed)


_PAYLOAD_SCRIPT = r"""
const D = await import(process.argv[1] + "/archive_data.js");
const job = JSON.parse(process.argv[2]);
const form = D.initialForm(job, false);
const fields = D.filterFieldsFor(job);
const firstText = fields.find((f) => f.type !== "date" && !f.list);
const inputs = {...form.filterInputs, [firstText.name]: "插件冒烟"};
const filters = D.mergeFieldFilters(fields, inputs, D.parseFiltersJson(form.filtersJson).filters);
const built = D.buildUpdatePayload(job, {...form, intervalMinutes: "45", retryMaxAttempts: "1", filtersJson: JSON.stringify(filters)});
console.log(JSON.stringify({field: firstText.name, ...built}));
"""


@needs_node
def test_built_payload_is_accepted_by_legacy_patch_endpoint(client) -> None:
    jobs = client.get("/api/scheduled-archive/jobs").get_json()["data"]
    job = next(item for item in jobs if item["templateKey"] == "tdc_sor")
    built = _run_node(_PAYLOAD_SCRIPT, json.dumps(job))
    assert "payload" in built, built
    response = client.patch(f"/api/scheduled-archive/jobs/{job['jobKey']}", json=built["payload"])
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()["data"]
    assert saved["intervalMinutes"] == 45
    assert saved["retryPolicy"]["max_attempts"] == 1
    assert saved["filters"][built["field"]] == "插件冒烟"
    again = next(item for item in client.get("/api/scheduled-archive/jobs").get_json()["data"] if item["jobKey"] == job["jobKey"])
    assert again["updatedAt"] == saved["updatedAt"]
