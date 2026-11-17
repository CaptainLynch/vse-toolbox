"""Frontend VM fixture for the P1D deliverable policy panel.

Runs the REAL ``policy.js`` and the REAL ``api.js`` inside one Node VM context.
Every other import of ``policy.js`` is linked as a ``SyntheticModule`` at its
exact specifier; ``policy-logic.js`` is never read from disk, only represented
by configured stubs. ``preact-htm.js`` is likewise a synthetic template/hooks
implementation, so no real Preact or DOM chain is loaded.

``./policy-digest-logic.js`` is different: it is import-free real source, so the
linker reads the actual file when (and only when) ``policy.js`` imports it.
The fixture never composes a request body on the code's behalf; a test sees
exactly what the panel sent.

Design contract (A89):

* pytest -> ``node --experimental-vm-modules --input-type=module`` subprocess.
* Same Node flags, process and context for preflight and every scenario.
* Missing node, rejected flag, missing ``SourceTextModule``/``SyntheticModule``,
  link failure, timeout, non-zero exit or a malformed result protocol all FAIL
  the test. Nothing is skipped.
* Only repository files are read. The fixture writes nothing, opens no socket,
  and reads no path outside the repository.
* The child process is ``shutil.which("node")`` with a fixed argument list;
  no shell, no interpolation of caller input into the command line. The module
  paths travel through ``argv``.

Exported API
------------
``node_major()``
    Installed Node major version, or 0 when Node is absent.
``require_node()``
    Hard-fail (never skip) when Node is missing or older than 22.
``Scenario(...)``
    Build a scenario description consumed by :func:`run_scenario`.
``run_scenario(scenario, *, timeout=60)``
    Execute one scenario in a fresh VM context and return its ``ScenarioResult``.
``load_policy_panel(scenario=None, *, timeout=60)``
    Convenience wrapper: run a scenario and return a :class:`Panel` handle.
``ScenarioResult`` / ``Panel``
    Result objects exposing the request log, render history and save trigger.
    ``Panel.patches[-1].body`` is the exact JSON body the panel sent.
    ``Panel.elements("documentNos")`` returns the rendered elements tagged
    ``data-wizard-field="documentNos"`` with their scalar attribute values
    (``disabled`` / ``value`` / ``data-*``), so a test can assert control state
    without a DOM.

Typical use in an EDITOR/WIZARD test::

    panel = load_policy_panel(Scenario(
        policy={"configDigest": "cfgd1:...", "enabled": True, "credentialAvailable": True},
        settings={"credentialVaultConfigured": True},
        inputs={"mode": "auto", "intervalMinutes": 47},
    ))
    assert len(panel.patches) == 1
    assert panel.patches[-1].body["expectedConfigDigest"] == "cfgd1:..."

See ``tests/test_p1d_frontend_fixture_selfcheck.py`` for executable examples.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DELIVERABLE_DIR = REPO_ROOT / "plugins/project_overview/static/deliverable"
POLICY_JS = DELIVERABLE_DIR / "policy.js"
API_JS = DELIVERABLE_DIR / "api.js"

#: Minimum Node major that ships ``vm.SourceTextModule`` behind the flag.
MIN_NODE_MAJOR = 22

#: Every named import ``policy.js`` takes from ``./policy-logic.js``.
POLICY_LOGIC_EXPORTS = (
    "EWO_POLICY_AUTOMATIC_FIELDS",
    "EWO_POLICY_MATCH_FIELDS",
    "EWO_POLICY_MODE_LABELS",
    "EWO_POLICY_RECOMMENDED_MODE",
    "INTERVAL_OPTIONS",
    "MATCH_FIELD_CONTRACT",
    "POLICY_SYNC_HINTS",
    "SERIAL_SET_TEXT_MAX",
    "applyBindingMode",
    "bindingInitialValues",
    "bindingModeView",
    "bindingReadiness",
    "buildEvidencePayload",
    "buildPolicyPayload",
    "buildWizardDiscovery",
    "capabilitiesOf",
    "defaultMappingFor",
    "dropDepartment",
    "ewoPolicyDiscoveryFields",
    "ewoPolicyDiscoveryStateLabel",
    "ewoPolicyErrorMessage",
    "ewoPolicyString",
    "mappingText",
    "parseSerialSet",
    "stabilityGateFailureMessage",
    "stabilityText",
    "wizardInitialValues",
    "wizardKind",
    "wizardMapping",
    "wizardMultiSerialError",
    "wizardMultiSerialHint",
    "wizardNotMatchedMessage",
    "wizardPolicyPatch",
    "wizardPrecheck",
    "wizardPrimaryMatchField",
    "wizardRetryWithoutDepartment",
)

#: Specifiers loaded as REAL source (the rest are synthetic).
REAL_MODULES = ("./api.js",)

#: Extra import-free helpers a scenario may ask the VM to load as real source.
DIGEST_JS = DELIVERABLE_DIR / "policy-digest-logic.js"


class FixtureError(RuntimeError):
    """Raised when the Node child could not run the scenario at all."""


def _node_binary() -> str:
    node = shutil.which("node")
    if node is None:
        raise FixtureError("node executable not found on PATH; the frontend VM fixture requires Node >= 22")
    return node


def node_major() -> int:
    """Return the installed Node major version, or 0 when Node is absent."""
    node = shutil.which("node")
    if node is None:
        return 0
    result = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    text = (result.stdout or "").strip()
    if not text.startswith("v"):
        return 0
    try:
        return int(text[1:].split(".", 1)[0])
    except ValueError:
        return 0


def require_node() -> None:
    """Fail (never skip) unless Node satisfies :data:`MIN_NODE_MAJOR`."""
    major = node_major()
    if major == 0:
        raise FixtureError("node executable not found on PATH; the frontend VM fixture requires Node >= 22")
    if major < MIN_NODE_MAJOR:
        raise FixtureError(
            f"node {major} is too old; the frontend VM fixture requires Node >= {MIN_NODE_MAJOR} "
            "(--experimental-vm-modules with vm.SourceTextModule)"
        )


@dataclass
class Scenario:
    """One VM scenario: what the real modules see when they run.

    Attributes
    ----------
    policy:
        Value returned by ``GET /api/project-status/deliverables/<id>/update-policy``.
    settings:
        Value returned by ``GET /api/settings`` (``None`` answers 404).
    discovery:
        Value returned by the mapping-discovery route (``None`` answers 404).
    responses:
        Ordered queue of scripted HTTP answers. Each entry is a mapping with
        ``method``, ``path`` (substring or exact), ``status``, ``body`` and
        optionally ``delayMs``. Unmatched requests fall back to the defaults
        above, then to a 404 envelope.
    item:
        The ``item`` prop handed to ``PolicyPanel``.
    capabilities:
        ``item.sourceInfo``; controls whether the panel is sync-capable.
    logic:
        Overrides for the ``./policy-logic.js`` synthetic module. Missing
        names keep their scenario defaults; ``buildPolicyPayload`` and
        ``wizardPolicyPatch`` must not add ``expectedConfigDigest`` themselves.
    version:
        The ``version`` prop; changing it re-runs the load effect.
    """

    policy: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] | None = None
    discovery: dict[str, Any] | None = None
    responses: list[dict[str, Any]] = field(default_factory=list)
    item: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    logic: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    deliverable_id: str = "VPI-T2-D5"
    inputs: dict[str, Any] = field(default_factory=dict)
    extra_modules: list[str] = field(default_factory=list)
    #: When set, this JS source is loaded as the entry module instead of
    #: ``policy.js``. It exists so a test can prove the linker maps
    #: ``./policy-digest-logic.js`` to the real file without editing the repo.
    entry_source: str | None = None

    def to_payload(self) -> dict[str, Any]:
        item = dict(self.item) or {"id": self.deliverable_id, "name": "示例交付物", "source": "ewo"}
        item.setdefault("id", self.deliverable_id)
        caps = dict(self.capabilities) or {
            "syncCapable": True,
            "reportType": "ewo",
            "displayName": "示例来源",
            "matchFields": [],
            "evidenceFields": [],
        }
        item.setdefault("sourceInfo", caps)
        return {
            "policy": self.policy,
            "settings": self.settings,
            "discovery": self.discovery,
            "responses": self.responses,
            "item": item,
            "capabilities": caps,
            "logic": self.logic,
            "version": self.version,
            "deliverableId": self.deliverable_id,
            "inputs": self.inputs,
            "extraModules": self.extra_modules,
            "entrySource": self.entry_source,
        }


@dataclass
class RequestRecord:
    """One HTTP call observed inside the VM."""

    method: str
    path: str
    body: Any = None
    status: int = 0
    ok: bool = False
    seq: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "body": self.body,
            "status": self.status,
            "ok": self.ok,
            "seq": self.seq,
        }


@dataclass
class ScenarioResult:
    """Everything a test may assert about one scenario run."""

    requests: list[RequestRecord] = field(default_factory=list)
    renders: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    preflight: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def requests_of(self, method: str) -> list[RequestRecord]:
        return [r for r in self.requests if r.method.upper() == method.upper()]

    @property
    def last_request(self) -> RequestRecord | None:
        return self.requests[-1] if self.requests else None

    def assert_ok(self) -> "ScenarioResult":
        """Fail loudly when the child reported an in-VM error."""
        if self.errors:
            raise AssertionError("scenario reported errors: " + "; ".join(self.errors))
        return self


def run_scenario(scenario: Scenario, *, timeout: int = 60) -> ScenarioResult:
    """Run one scenario in a fresh VM context.

    Raises :class:`FixtureError` when the child could not start or violated the
    result protocol, and :class:`AssertionError` is left to the caller for
    scenario-level assertions.
    """
    require_node()
    payload = scenario.to_payload()
    args = [
        _node_binary(),
        "--experimental-vm-modules",
        "--input-type=module",
        "-e",
        _BOOTSTRAP_JS,
        "--",
        str(POLICY_JS),
        str(API_JS),
        json.dumps(payload),
        str(DIGEST_JS),
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise FixtureError(
            "node VM child failed with exit {code}\n--- stdout ---\n{out}\n--- stderr ---\n{err}".format(
                code=result.returncode,
                out=(result.stdout or "")[-4000:],
                err=(result.stderr or "")[-4000:],
            )
        )
    line = _last_json_line(result.stdout or "")
    if line is None:
        raise FixtureError(
            "node VM child produced no JSON result line\n--- stdout ---\n{out}\n--- stderr ---\n{err}".format(
                out=(result.stdout or "")[-4000:],
                err=(result.stderr or "")[-4000:],
            )
        )
    return _to_result(line)


def _last_json_line(text: str) -> dict[str, Any] | None:
    for raw in reversed(text.strip().splitlines()):
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("fixture") == "p1d":
            return parsed
    return None


def _to_result(payload: dict[str, Any]) -> ScenarioResult:
    if payload.get("protocol") != 1:
        raise FixtureError(f"unexpected result protocol: {payload.get('protocol')!r}")
    if not payload.get("preflight", {}).get("ok"):
        raise FixtureError(f"VM preflight failed: {payload.get('preflight')!r}")
    requests = [
        RequestRecord(
            method=str(entry.get("method", "")),
            path=str(entry.get("path", "")),
            body=entry.get("body"),
            status=int(entry.get("status", 0)),
            ok=bool(entry.get("ok")),
            seq=int(entry.get("seq", 0)),
        )
        for entry in payload.get("requests", [])
    ]
    return ScenarioResult(
        requests=requests,
        renders=list(payload.get("renders", [])),
        statuses=list(payload.get("statuses", [])),
        errors=list(payload.get("errors", [])),
        exports=list(payload.get("exports", [])),
        preflight=dict(payload.get("preflight", {})),
        raw=payload,
    )


@dataclass
class Panel:
    """Handle over one loaded ``PolicyPanel`` inside a finished scenario run."""

    result: ScenarioResult
    item: dict[str, Any]
    version: int

    @property
    def requests(self) -> list[RequestRecord]:
        return self.result.requests

    @property
    def renders(self) -> list[dict[str, Any]]:
        return self.result.renders

    @property
    def statuses(self) -> list[dict[str, Any]]:
        return self.result.statuses

    def renders_of(self, component: str) -> list[dict[str, Any]]:
        return [r for r in self.result.renders if r.get("component") == component]

    def last_render(self, component: str = "BindingEditor") -> dict[str, Any]:
        rows = self.renders_of(component)
        if not rows:
            raise AssertionError(f"component {component!r} never rendered")
        return rows[-1]

    def save_handlers(self) -> list[dict[str, Any]]:
        """Every ``onSubmit`` callback captured from the rendered form."""
        return [r for r in self.result.renders if r.get("kind") == "form-submit"]

    @property
    def patches(self) -> list[RequestRecord]:
        return self.result.requests_of("PATCH")

    def trigger_save(self) -> dict[str, Any]:
        """Fire the form ``onSubmit`` captured from the last render."""
        events = self.result.raw.get("saveEvents") or []
        if not events:
            raise AssertionError("no form onSubmit was captured; the panel did not render a save form")
        return events[-1]

    def inputs(self) -> list[dict[str, Any]]:
        return [r for r in self.result.renders if r.get("kind") == "input"]

    def elements(self, wizard_field: str | None = None) -> list[dict[str, Any]]:
        """Rendered elements that carry ``data-*`` attributes.

        ``elements("documentNos")`` returns the elements tagged
        ``data-wizard-field="documentNos"``; ``elements()`` returns them all.
        """
        rows = [r for r in self.result.renders if r.get("kind") == "element"]
        if wizard_field is None:
            return rows
        return [r for r in rows if r["attrs"].get("data-wizard-field") == wizard_field]


def load_policy_panel(scenario: Scenario | None = None, *, timeout: int = 60) -> Panel:
    """Load ``PolicyPanel`` with the scenario's props and return a handle."""
    scenario = scenario or Scenario()
    result = run_scenario(scenario, timeout=timeout)
    return Panel(result=result, item=scenario.to_payload()["item"], version=scenario.version)


# ---------------------------------------------------------------------------
# Node bootstrap. Everything below runs inside the child process.
# ---------------------------------------------------------------------------
_BOOTSTRAP_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, POLICY_PATH, API_PATH, PAYLOAD_JSON, DIGEST_PATH] = process.argv;
const scenario = JSON.parse(PAYLOAD_JSON);

const requests = [];
const renders = [];
function fail(message) { errors.push(String(message)); }
const statuses = [];
const errors = [];
const saveEvents = [];
const saveHandlers = [];
let seq = 0;

function record(status, ok) {
  const last = requests[requests.length - 1];
  if (last) { last.status = status; last.ok = ok; }
}

function bodyOf(response) {
  return response && response.body !== undefined ? response.body : null;
}

function envelope(status, data) {
  if (status >= 200 && status < 300) return { ok: true, data };
  return { ok: false, error: data };
}

function pickResponse(method, path) {
  for (let index = 0; index < scenario.responses.length; index += 1) {
    const entry = scenario.responses[index];
    if (!entry) continue;
    if (entry.method && entry.method.toUpperCase() !== method.toUpperCase()) continue;
    if (entry.path && !path.includes(entry.path)) continue;
    scenario.responses.splice(index, 1);
    return entry;
  }
  if (method === "GET" && path.includes("/update-policy")) {
    return { status: 200, body: envelope(200, scenario.policy) };
  }
  if (method === "GET" && path.includes("/api/settings")) {
    if (scenario.settings === null) return { status: 404, body: { ok: false, error: { message: "not found" } } };
    return { status: 200, body: envelope(200, scenario.settings) };
  }
  if (method === "GET" && path.includes("/mapping-discovery")) {
    // The panel tolerates a 404 here and falls back to {}, which is what the
    // real route does for a deliverable with no discovery yet.
    if (scenario.discovery === null) return { status: 404, body: { ok: false, error: { message: "not found" } } };
    return { status: 200, body: envelope(200, scenario.discovery || {}) };
  }
  if (method === "GET" && path.includes("/api/project-status/updates")) {
    return { status: 200, body: envelope(200, { updates: [] }) };
  }
  return { status: 404, body: { ok: false, error: { message: "no scripted response" } } };
}

function makeFetch() {
  return async function fetch(path, init = {}) {
    const method = String(init.method || "GET").toUpperCase();
    let body = null;
    if (typeof init.body === "string") { try { body = JSON.parse(init.body); } catch { body = init.body; } }
    const entry = { method, path: String(path), body, status: 0, ok: false, seq: seq++ };
    requests.push(entry);
    const scripted = pickResponse(method, String(path));
    if (scripted && scripted.delayMs) {
      await new Promise((resolve) => setTimeout(resolve, scripted.delayMs));
    }
    const status = Number(scripted && scripted.status ? scripted.status : 200);
    const payload = scripted && scripted.body !== undefined ? scripted.body : envelope(status, null);
    entry.status = status;
    entry.ok = status >= 200 && status < 300;
    return {
      ok: entry.ok,
      status,
      async json() { return payload; },
    };
  };
}

// ---- hooks stub: one slot list per component, cursor aligned to call order
const hookState = new Map();
let hookOwner = null;
let hookCursor = 0;

function slotStore(owner) {
  let store = hookState.get(owner);
  if (!store) { store = { slots: [], effectSlots: [] }; hookState.set(owner, store); }
  return store;
}

function nextSlot(init) {
  const store = slotStore(hookOwner);
  const index = hookCursor++;
  if (index >= store.slots.length) {
    // React-style lazy initializer: a function is called once, a value is used as-is.
    store.slots.push({ value: typeof init === "function" ? init() : init, kind: "state" });
  }
  return store.slots[index];
}

function useState(init) {
  const slot = nextSlot(init);
  const set = (next) => {
    slot.value = typeof next === "function" ? next(slot.value) : next;
    scheduleRender();
  };
  return [slot.value, set];
}

function useRef(init) {
  const store = slotStore(hookOwner);
  const index = hookCursor++;
  if (index >= store.slots.length) store.slots.push({ value: { current: init }, kind: "ref" });
  const slot = store.slots[index];
  if (slot.value === undefined || typeof slot.value !== "object" || slot.value === null || !("current" in slot.value)) {
    slot.value = { current: init };
  }
  return slot.value;
}

function useEffect(fn, deps) {
  // Effects occupy a slot too, so the cursor stays aligned with call order.
  const store = slotStore(hookOwner);
  const index = hookCursor++;
  if (index >= store.slots.length) store.slots.push({ value: undefined, kind: "effect" });
  store.slots[index].effect = { fn, deps };
  store.effectSlots[index] = store.slots[index];
}

function resetCursor(owner) {
  hookOwner = owner;
  hookCursor = 0;
}

let pendingRender = null;
function scheduleRender() {
  if (pendingRender) return;
  pendingRender = Promise.resolve().then(() => {
    pendingRender = null;
    if (typeof currentRender === "function") currentRender();
  });
}
let currentRender = null;

function html(strings, ...values) {
  return { __template: true, strings: Array.from(strings), values };
}

function isTemplate(node) { return Boolean(node && node.__template === true); }

function collect(node, out) {
  if (node === null || node === undefined || node === false) return;
  if (Array.isArray(node)) { for (const child of node) collect(child, out); return; }
  if (isTemplate(node)) {
    out.push(node);
    for (const value of node.values) collect(value, out);
    return;
  }
  if (typeof node === "function") { out.push(node); return; }
  out.push(node);
}

// A tagged template yields strings.length === values.length + 1, so the text
// preceding values[i] is strings[i].
function walkProps(template, visit) {
  for (let index = 0; index < template.values.length; index += 1) {
    const before = String(template.strings[index] || "");
    const match = /([A-Za-z_][A-Za-z0-9_-]*)=\s*$/.exec(before);
    if (!match) continue;
    visit(match[1], template.values[index], index);
  }
}

// Rendered-control state without a DOM: flatten one template to text (scalar
// interpolations inlined, handlers/nested templates replaced by a marker), then
// record every element carrying at least one data-* attribute. Tests assert on
// data-wizard-field / disabled / value this way instead of re-parsing templates.
const DYNAMIC_MARK = "\u0001";
const VALUE_MARK = "\u0002";
const ELEMENT_RE = /<([A-Za-z][A-Za-z0-9-]*)((?:[^<>"]|"[^"]*")*?)\/?>/g;
const ATTRIBUTE_RE = /([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?:"([^"]*)"|\u0002([^\u0002]*)\u0002|\u0001)/g;

function flattenTemplate(template) {
  let out = "";
  for (let index = 0; index < template.strings.length; index += 1) {
    out += String(template.strings[index] || "");
    if (index >= template.values.length) break;
    const value = template.values[index];
    const scalar = typeof value !== "function" && (value === null || typeof value !== "object");
    out += scalar ? VALUE_MARK + String(value) + VALUE_MARK : DYNAMIC_MARK;
  }
  return out;
}

// Boolean interpolations arrive as the strings "true"/"false"; they are restored
// to booleans so a test can assert `disabled is True`.
function attributeValue(text) {
  if (text === "true") return true;
  if (text === "false") return false;
  return text;
}

function recordElement(template, depth) {
  const flat = flattenTemplate(template);
  if (flat.indexOf("data-") === -1) return;
  ELEMENT_RE.lastIndex = 0;
  let element;
  while ((element = ELEMENT_RE.exec(flat)) !== null) {
    const body = element[2];
    const attrs = {};
    let hasData = false;
    ATTRIBUTE_RE.lastIndex = 0;
    let attribute;
    while ((attribute = ATTRIBUTE_RE.exec(body)) !== null) {
      const name = attribute[1];
      const value = attribute[2] !== undefined ? attribute[2]
        : (attribute[3] !== undefined ? attributeValue(attribute[3]) : "<dynamic>");
      attrs[name] = value;
      if (name.indexOf("data-") === 0) hasData = true;
    }
    if (hasData) renders.push({ kind: "element", tag: element[1].toLowerCase(), attrs, depth });
  }
}

// ---- synthetic module factories
function syntheticModule(name, exportsMap) {
  const names = Object.keys(exportsMap);
  return new vm.SyntheticModule(names, function () {
    for (const key of names) this.setExport(key, exportsMap[key]);
  }, { context: sharedContext, identifier: name });
}

function logicStub() {
  const overrides = scenario.logic || {};
  const base = {
    // [key, label] tuples: the panel destructures each entry.
    EWO_POLICY_AUTOMATIC_FIELDS: [["owner", "负责人"], ["plannedDate", "计划日期"]],
    EWO_POLICY_MATCH_FIELDS: [{ name: "ewoNo", label: "EWO 单号" }],
    EWO_POLICY_MODE_LABELS: { manual: "手动", auto: "自动同步" },
    EWO_POLICY_RECOMMENDED_MODE: "auto",
    INTERVAL_OPTIONS: [5, 15, 30, 60],
    // 字段契约版本：面板会与 sourceInfo.matchFieldContract 比较，不一致时提示
    // 「重启+强刷」。桩给同值，避免测试里出现无关提示。
    MATCH_FIELD_CONTRACT: "2026-10-27.1",
    POLICY_SYNC_HINTS: { manual: "手动维护", auto: "按间隔自动同步" },
    // 多单号文本框的字符上限（与后端 500 × 64 + 分隔符同口径）。
    SERIAL_SET_TEXT_MAX: 500 * 64 + 499,
    applyBindingMode: (values) => values,
    bindingInitialValues: () => ({
      mode: "manual", credential: "", externalKey: "", bindingMode: "",
      intervalMinutes: 30, match: {}, evidence: {}, mapping: {}, authority: {},
    }),
    bindingModeView: () => ({ externalKeyHidden: false, externalKeyLabel: "外部单号",
                              externalKeyPlaceholder: "例如 EWO-0001", lockOwnerPlanned: false }),
    bindingReadiness: () => ({ ready: true, blockers: [], notes: [] }),
    buildEvidencePayload: () => ({ externalKey: "EWO-0001" }),
    // The stub must not merge a digest; that is the panel's own concern.
    buildPolicyPayload: (_item, _caps, _current, values) => ({
      enabled: values.mode !== "manual",
      mode: values.mode,
      intervalMinutes: values.intervalMinutes,
      credentialRef: values.credential || "",
      externalKey: values.externalKey || "",
      matchRule: values.match || {},
    }),
    buildWizardDiscovery: () => ({}),
    capabilitiesOf: (item) => (item && item.sourceInfo) || {},
    defaultMappingFor: () => ({}),
    dropDepartment: (values) => values,
    ewoPolicyDiscoveryFields: () => [],
    ewoPolicyDiscoveryStateLabel: () => "已匹配",
    ewoPolicyErrorMessage: (error) => String((error && error.message) || error || ""),
    ewoPolicyString: (value) => (value === null || value === undefined ? "" : String(value)),
    mappingText: () => "",
    parseSerialSet: (value) => (typeof value === "string" && value.trim() ? value.split(",").map((v) => v.trim()).filter(Boolean) : []),
    stabilityGateFailureMessage: () => "",
    stabilityText: () => "0/2",
    wizardInitialValues: () => ({
      credential: "", model: "", department: "", status: "", sections: [],
      interval: "15", number: "", documentNo: "", documentNos: "", defaultDept: "",
    }),
    // The real module returns the kind OBJECT and a nullable primary field; the
    // stub mirrors those shapes so the wizard branches render as they do in the
    // browser (a string would silently disable every kind-specific field).
    wizardKind: (caps) => {
      const reportType = (caps && caps.reportType) || "";
      return {
        isEwo: reportType === "ewo",
        isSor: reportType === "sor",
        isDataModel: reportType === "data_model",
        isPaa: reportType === "paa",
        isNcr: reportType === "ncr_progress" || reportType === "ncr_detail",
        isTdc: reportType === "sor" || reportType === "data_model" || (caps && caps.sourceType) === "tdc",
      };
    },
    wizardMapping: () => ({}),
    wizardMultiSerialError: () => "",
    wizardMultiSerialHint: (values) => {
      const parsed = typeof values.documentNos === "string" && values.documentNos.trim()
        ? values.documentNos.split(",").map((v) => v.trim()).filter(Boolean)
        : [];
      return parsed.length ? "识别到 " + parsed.length + " 个单号（合并统计）" : "";
    },
    wizardNotMatchedMessage: () => "",
    wizardPolicyPatch: (_plan, _values, _result, _mapping, _vault) => ({}),
    // 真实实现返回**字符串**（"" = 通过，否则是可直接展示的中文拦截文案）；
    // 桩返回对象会掩盖「precheck 永远为真」这类缺陷。
    wizardPrecheck: () => "",
    wizardPrimaryMatchField: () => null,
    wizardRetryWithoutDepartment: () => ({}),
  };
  const merged = Object.assign({}, base);
  for (const [key, value] of Object.entries(overrides)) merged[key] = value;
  const missing = Object.keys(base).filter((key) => typeof merged[key] === "undefined");
  if (missing.length) fail("logic stub missing: " + missing.join(","));
  return merged;
}

const sharedContext = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  queueMicrotask, Promise, JSON, Math, Date, Object, Array, String, Number, Boolean,
  Error, TypeError, RangeError, Map, Set, WeakMap, WeakSet, Symbol, Reflect, RegExp,
  encodeURIComponent, decodeURIComponent, isNaN, parseInt, parseFloat, undefined,
  fetch: makeFetch(),
  window: {},
});

function syntheticSpecifiers() {
  const logic = logicStub();
  const registry = new Map();
  registry.set("/static/host/vendor/preact-htm.js", {
    html, useState, useRef, useEffect,
  });
  registry.set("./discovery.js", {
    newWizardSessionId: () => "wizard-session-1",
    postMappingDiscovery: async () => ({ stability: { matched: 2 }, fields: [] }),
  });
  registry.set("./multi-select.js", {
    SearchMultiSelect: function SearchMultiSelect() { return html`<div class="multi-select"></div>`; },
  });
  registry.set("./display.js", {
    deliverableSyncDisplay: () => ({ state: "ok", text: "" }),
    syncResultText: () => "",
  });
  registry.set("./format.js", {
    redactSensitiveText: (value) => String(value === undefined || value === null ? "" : value),
    safeDisplayValue: (value) => String(value === undefined || value === null ? "" : value),
  });
  registry.set("./policy-logic.js", logic);
  return registry;
}

const report = { ok: false, node: process.version, sourceTextModule: typeof vm.SourceTextModule,
                 syntheticModule: typeof vm.SyntheticModule, minimal: null };

if (typeof vm.SourceTextModule !== "function" || typeof vm.SyntheticModule !== "function") {
  console.log(JSON.stringify({ fixture: "p1d", protocol: 1, preflight: report, errors: ["vm API missing"] }));
  process.exit(1);
}

const probeSynth = new vm.SyntheticModule(["flag"], function () { this.setExport("flag", "ok"); },
                                          { context: sharedContext, identifier: "probe" });
probeSynth.link(() => { throw new Error("synthetic must not link"); });
await probeSynth.evaluate();
const probeSource = new vm.SourceTextModule("export const value = 42;", { context: sharedContext, identifier: "probe2" });
await probeSource.link(() => { throw new Error("source must not link"); });
await probeSource.evaluate();
report.minimal = { synthetic: probeSynth.namespace.flag, source: probeSource.namespace.value };
report.ok = probeSynth.namespace.flag === "ok" && probeSource.namespace.value === 42;

if (!report.ok) {
  console.log(JSON.stringify({ fixture: "p1d", protocol: 1, preflight: report, errors: ["preflight assertion"] }));
  process.exit(1);
}

const registry = syntheticSpecifiers();
const entrySource = typeof scenario.entrySource === "string" ? scenario.entrySource : readFileSync(POLICY_PATH, "utf8");
const policyModule = new vm.SourceTextModule(entrySource, {
  context: sharedContext, identifier: pathToFileURL(POLICY_PATH).href,
});
const apiModule = new vm.SourceTextModule(readFileSync(API_PATH, "utf8"), {
  context: sharedContext, identifier: pathToFileURL(API_PATH).href,
});

try {
  await policyModule.link(async (specifier) => {
    // Real source, never a synthetic stand-in: the fixture must not speak for
    // code that policy.js actually imports.
    if (specifier === "./api.js") return apiModule;
    if (specifier === "./policy-digest-logic.js") {
      if (!DIGEST_PATH) throw new Error("digest helper path not supplied");
      // The VM links and evaluates returned modules itself; linking here would
      // double-link it.
      return new vm.SourceTextModule(readFileSync(DIGEST_PATH, "utf8"), {
        context: sharedContext, identifier: pathToFileURL(DIGEST_PATH).href,
      });
    }
    if (specifier === "./enable-flow.js") {
      // 启用流程是 policy.js 抽出来的真实代码（与「一键开启」共用），按真源码加载；
      // 它自己的依赖（api / discovery / policy-logic）仍走同一个链接器。
      const flowPath = POLICY_PATH.replace(/policy\.js$/, "enable-flow.js");
      return new vm.SourceTextModule(readFileSync(flowPath, "utf8"), {
        context: sharedContext, identifier: pathToFileURL(flowPath).href,
      });
    }
    if (specifier === "./api.js") return apiModule;
    const exportsMap = registry.get(specifier);
    if (!exportsMap) throw new Error("unknown specifier " + specifier);
    return syntheticModule(specifier, exportsMap);
  });
  // A module returned from the link callback is linked and evaluated by the VM,
  // so only the entry module is evaluated here.
  await policyModule.evaluate();
} catch (error) {
  console.log(JSON.stringify({ fixture: "p1d", protocol: 1, preflight: report,
    errors: ["link/evaluate failed: " + String(error && error.message)], requests, renders, statuses, saveEvents }));
  process.exit(0);
}

const PolicyPanel = policyModule.namespace.PolicyPanel;
const exportsList = Object.keys(policyModule.namespace);
if (typeof PolicyPanel !== "function") {
  console.log(JSON.stringify({ fixture: "p1d", protocol: 1, preflight: report,
    errors: ["PolicyPanel export missing"], requests, renders, statuses, saveEvents }));
  process.exit(0);
}

const props = {
  item: scenario.item,
  version: scenario.version,
  onPolicyLoaded: (policy) => statuses.push({ kind: "policy-loaded", policy }),
  onEvidenceRefresh: () => statuses.push({ kind: "evidence-refresh" }),
  onReloadOverview: async () => { statuses.push({ kind: "reload-overview" }); return true; },
};

// Commit any effects registered during the last render, comparing deps the way
// React does (undefined deps = run every time, [] = run once).
async function commitEffects(owner) {
  const store = slotStore(owner);
  const pending = store.slots.filter((slot) => slot.kind === "effect" && slot.effect);
  for (const slot of pending) {
    const { fn, deps } = slot.effect;
    const previous = slot.committedDeps;
    const same = previous !== undefined && deps !== undefined
      && previous.length === deps.length
      && previous.every((value, index) => Object.is(value, deps[index]));
    if (same) continue;
    if (typeof slot.cleanup === "function") { try { slot.cleanup(); } catch (_) {} }
    slot.committedDeps = deps;
    const cleanup = fn();
    slot.cleanup = typeof cleanup === "function" ? cleanup : undefined;
  }
}

async function renderOnce() {
  resetCursor(PolicyPanel);
  const tree = PolicyPanel(props);
  await commitEffects(PolicyPanel);
  // Let the load effect's promises settle, then re-render with the new state.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  resetCursor(PolicyPanel);
  const settled = PolicyPanel(props);
  await commitEffects(PolicyPanel);
  return settled;
}

let tree = await renderOnce();

// Scenario inputs override the component's own initial state, so a test can put
// the form in a specific shape before the save handler runs.
// Inputs are applied after the components have been invoked once, so their own
// state slots exist. Applied to every component, keyed by the shape of its
// state object (a key the object already owns is overwritten).
function applyInputs(owner) {
  const store = hookState.get(owner);
  if (!store) return false;
  let touched = false;
  for (const slot of store.slots) {
    if (slot.kind !== "state") continue;
    const value = slot.value;
    if (value === null || typeof value !== "object" || Array.isArray(value)) continue;
    for (const [key, next] of Object.entries(scenario.inputs)) {
      if (Object.prototype.hasOwnProperty.call(value, key)) { value[key] = next; touched = true; }
    }
  }
  return touched;
}

// Walk the rendered tree and record every component invocation plus the
// callbacks the template actually wired.
const seen = new Set();
const components = [];
function inspect(node, depth) {
  if (node === null || node === undefined || node === false) return;
  if (Array.isArray(node)) { for (const child of node) inspect(child, depth); return; }
  if (isTemplate(node)) {
    recordElement(node, depth);
    walkProps(node, (name, value) => {
      if (name === "onSubmit" && typeof value === "function") {
        renders.push({ kind: "form-submit", depth });
        saveEvents.push({ index: saveEvents.length });
      }
      if (name === "onInput" && typeof value === "function") {
        renders.push({ kind: "input", depth });
      }
    });
    for (const value of node.values) inspect(value, depth + 1);
    return;
  }
  if (typeof node === "function") {
    // Only Capitalized functions are components. Their real props live in the
    // enclosing template's interpolations, so record the reference here and let
    // invokeComponent() run them with the props the template actually passed.
    const label = node.name || "";
    if (!/^[A-Z]/.test(label)) return;
    if (seen.has(node)) return;
    seen.add(node);
    renders.push({ kind: "component", component: label });
    components.push({ fn: node, name: label });
  }
}

inspect(tree, 0);

// Run each discovered component with the props the template passed to it.
// A template may interpolate several components, so collect every candidate
// and pick the one whose attribute run actually starts right after THIS
// function's interpolation.
function propsFor(fn) {
  const candidates = [];
  function scan(node) {
    if (node === null || node === undefined) return;
    if (Array.isArray(node)) { for (const child of node) scan(child); return; }
    if (!isTemplate(node)) return;
    const at = node.values.indexOf(fn);
    if (at >= 0 && node.values.filter((v) => v === fn).length === 1) {
      const props = {};
      let count = 0;
      for (let k = at + 1; k < node.values.length; k += 1) {
        const match = /([A-Za-z_][A-Za-z0-9_-]*)=\s*$/.exec(String(node.strings[k] || ""));
        // A non-attribute interpolation ends this component's prop run; stop
        // rather than borrowing the next component's props.
        if (!match) break;
        props[match[1]] = node.values[k];
        count += 1;
      }
      candidates.push({ props, count });
    }
    for (const value of node.values) scan(value);
  }
  scan(tree);
  if (!candidates.length) return null;
  // Prefer the run that attached the most attributes: a bare interpolation of
  // the same function elsewhere in the tree yields fewer or none.
  candidates.sort((a, b) => b.count - a.count);
  return candidates[0].props;
}

for (const entry of components) {
  const props = propsFor(entry.fn);
  if (!props) continue;
  resetCursor(entry.fn);
  let out;
  try { out = entry.fn(props); } catch (error) { fail("component " + entry.name + " threw: " + String(error && error.message)); continue; }
  await commitEffects(entry.fn);
  renders.push({ kind: "component-props", component: entry.name, props: Object.keys(props).sort() });
  inspect(out, 1);
  walkProps(out, (propName, propValue) => {
    if (propName === "onSubmit" && typeof propValue === "function") {
      renders.push({ kind: "form-submit", component: entry.name, index: saveEvents.length });
      saveHandlers.push({ component: entry.name, fn: propValue });
      saveEvents.push({ component: entry.name, index: saveEvents.length });
    }
  });
}

if (scenario.inputs && Object.keys(scenario.inputs).length) {
  for (const entry of components) applyInputs(entry.fn);
  // Re-render so the save closure captures the updated payload.
  saveHandlers.length = 0;
  renders.length = 0;
  components.length = 0;
  seen.clear();
  resetCursor(PolicyPanel);
  tree = PolicyPanel(props);
  await commitEffects(PolicyPanel);
  inspect(tree, 0);
  // Snapshot: inspect() appends the components it discovers, and this loop must
  // visit each component of THIS render exactly once.
  for (const entry of components.slice()) {
    const entryProps = propsFor(entry.fn);
    if (!entryProps) continue;
    resetCursor(entry.fn);
    let out2;
    try { out2 = entry.fn(entryProps); } catch (error) { fail("component " + entry.name + " threw: " + String(error && error.message)); continue; }
    await commitEffects(entry.fn);
    // Same inspection as the pre-inputs pass, so data-* element records describe
    // the state the save closures actually see.
    inspect(out2, 1);
    walkProps(out2, (propName, propValue) => {
      if (propName === "onSubmit" && typeof propValue === "function") {
        renders.push({ kind: "form-submit", component: entry.name, index: saveHandlers.length });
        saveHandlers.push({ component: entry.name, fn: propValue });
      }
    });
  }
}

// Fire every captured save handler once, in capture order, so the caller can
// assert on the resulting request log.
for (const handler of saveHandlers) {
  const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  try {
    await handler.fn(event);
    saveEvents.push({ component: handler.component, fired: true, prevented: event.defaultPrevented });
  } catch (error) {
    fail("save handler threw: " + String(error && error.message));
    saveEvents.push({ component: handler.component, fired: false, error: String(error && error.message) });
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function describeTree(node, depth) {
  if (depth > 3) return "<max>";
  if (node === null || node === undefined) return String(node);
  if (Array.isArray(node)) return node.map((child) => describeTree(child, depth + 1));
  if (isTemplate(node)) return { template: true, text: node.strings.join("|").slice(0, 120) };
  if (typeof node === "function") return "<fn " + (node.name || "anonymous") + ">";
  return typeof node;
}

console.log(JSON.stringify({
  fixture: "p1d",
  protocol: 1,
  preflight: report,
  tree: describeTree(tree, 0),
  exports: exportsList,
  requests,
  renders,
  statuses,
  saveEvents,
  errors,
  entry: (() => {
    // Only meaningful for a custom entry module: expose what it exported so a
    // test can assert the linker resolved a real dependency.
    if (typeof scenario.entrySource !== "string") return null;
    const out = {};
    for (const key of Object.keys(policyModule.namespace)) {
      const value = policyModule.namespace[key];
      out[key] = typeof value === "function" ? value() : value;
    }
    return out;
  })(),
}));
"""
