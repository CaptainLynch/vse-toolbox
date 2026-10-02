# -*- coding: utf-8 -*-
"""Pure-logic checks (under Node) for the restored project-overview behaviours.

Browser behaviour lives in test_plugin_overview_browser.py; these pin the
payload / render-model contracts of the pure modules.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "plugins" / "project_overview" / "static"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules")


def _run(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, STATIC.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


_WIZARD = r"""
const base = process.argv[1];
const P = await import(base + "/deliverable/policy-logic.js");
const caps = (reportType, sourceType = "aras") => ({reportType, sourceType, matchFields: [], evidenceFields: []});
const ncr = P.buildWizardDiscovery({model: "F610S", department: "技术中心_车体工程", number: "", status: "", sections: ["车身科", "内饰科"]}, caps("ncr_detail"));
const ncrNoScope = P.buildWizardDiscovery({model: "F610S", department: "x", number: "N-1", sections: []}, caps("ncr_progress"));
const sor = P.buildWizardDiscovery({model: "F610S", department: "车体工程", number: "", status: "审批中"}, caps("sor", "tdc"));
const dm = P.buildWizardDiscovery({model: "F610S", department: "车体工程", number: "", status: "已完成"}, caps("data_model", "tdc"));
const paa = P.buildWizardDiscovery({model: "F610S", department: "技术中心_车体工程", number: "", status: "ignored"}, caps("paa"));
const initSor = P.wizardInitialValues({matchRule: {approvalStatus: "审批中", status: "WRONG"}}, caps("sor", "tdc"), true);
const initDm = P.wizardInitialValues({matchRule: {status: "已完成"}}, caps("data_model", "tdc"), true);
const initNcr = P.wizardInitialValues({matchRule: {sectionScope: ["车身科", 7]}}, caps("ncr_detail"), true);
console.log(JSON.stringify({
  ncr: {filters: ncr.filters, rule: ncr.matchRule},
  ncrNoScope: {filters: ncrNoScope.filters, rule: ncrNoScope.matchRule},
  sor: {filters: sor.filters, rule: sor.matchRule},
  dm: {filters: dm.filters, rule: dm.matchRule},
  paa: {filters: paa.filters, rule: paa.matchRule},
  initSor: initSor.status, initDm: initDm.status, initNcr: initNcr.sections,
  gate: [
    P.stabilityGateFailureMessage({mismatch: {reason: "total_mismatch", expected: 100, actual: 101}}),
    P.stabilityGateFailureMessage({mismatch: {reason: "sample_not_in_baseline"}}),
    P.stabilityGateFailureMessage({mismatch: {reason: "fields_mismatch"}}),
    P.stabilityGateFailureMessage({mismatch: {reason: "legacy_baseline"}}),
    P.stabilityGateFailureMessage({mismatch: {reason: "total_mismatch", expected: "x", actual: 1}}),
    P.stabilityGateFailureMessage({}),
    P.stabilityGateFailureMessage(null),
  ],
}));
"""


def test_wizard_payloads_per_report_kind() -> None:
    data = _run(_WIZARD)
    # NCR: department is never a query key; the section scope is only a declaration on the binding
    assert data["ncr"]["filters"] == {"project_model": "F610S"}
    assert data["ncr"]["rule"]["sectionScope"] == ["车身科", "内饰科"]
    assert "department" not in data["ncr"]["rule"] and "sectionCode" not in data["ncr"]["rule"]
    assert data["ncrNoScope"]["filters"] == {"project_model": "F610S", "serial_number": "N-1"}
    assert "sectionScope" not in data["ncrNoScope"]["rule"]
    # SOR: status filter travels as approval_status / approvalStatus
    assert data["sor"]["filters"] == {"car_type_project": "F610S", "department": "车体工程", "approval_status": "审批中"}
    assert data["sor"]["rule"]["approvalStatus"] == "审批中" and "status" not in data["sor"]["rule"]
    # data model keeps status
    assert data["dm"]["filters"]["status"] == "已完成" and "approval_status" not in data["dm"]["filters"]
    # PAA ignores the status field entirely
    assert "status" not in data["paa"]["filters"] and "approval_status" not in data["paa"]["filters"]
    assert data["initSor"] == "审批中" and data["initDm"] == "已完成" and data["initNcr"] == ["车身科", "7"]


def test_stability_gate_messages_never_leak_identifiers() -> None:
    gate = _run(_WIZARD)["gate"]
    assert "（100→101）" in gate[0]
    assert "第 1 页样本" in gate[1]
    assert "字段结构" in gate[2]
    assert "历史证据格式不兼容" in gate[3]
    assert gate[4] == gate[5] == gate[6] == "映射稳定性未就绪（需连续两次一致的脱敏证据），请稍后重试。"


_FORM = r"""
const base = process.argv[1];
const S = await import(base + "/deliverable/form-state.js");
const C = await import(base + "/deliverable/chart-math.js");
const D = await import(base + "/deliverable/discovery.js");
const A = await import(base + "/deliverable/api.js");
const cols = [{index: 0, label: "流程名"}, {index: 6, label: "部门"}, {index: 3, label: "零件名称"}];
const dm = S.formDisplayColumns({formKey: "tdc_data_model"}, cols);
const sor = S.formDisplayColumns({formKey: "tdc_sor"}, cols);
const absent = S.formAbsentSourceIndexes({sourceAbsentIndexes: [2, "7", "x", null]});
const row = {values: ["a", "b", "c", "d"], dimensions: {status: "审批中"}};
const timeoutErr = S.formViewLoadTimeoutError(30000);
const retryable = A.requestError({ok: false, error: {message: "TDC 网关暂时不可用", diagnostic: {retryable: true}}}, 503);
const plain = A.requestError({ok: false, error: {message: "bad"}}, 400);
const costs = C.sectionCostRows([
  {label: "车身科", total: 3, costs: {investmentEstimate: {sum: 1234.5, count: 2}, investmentApproved: {sum: 0, count: 1}, vehicleChangeEstimate: {sum: -50, count: 1}, vehicleChangeApproved: {sum: 0, count: 0}}},
  {label: "内饰科", total: 1, costs: {}},
]);
console.log(JSON.stringify({
  tabs: S.DELIVERABLE_FORM_TABS.tdc_data_model.map((t) => t[0]),
  sorTabs: S.DELIVERABLE_FORM_TABS.tdc_sor.map((t) => t[0]),
  dmLabels: dm.map((c) => c.label), dmDerived: dm.map((c) => Boolean(c.derivedStatus)), sorLabels: sor.map((c) => c.label),
  absent: [...absent].sort(),
  cellDerived: S.formRowCell({derivedStatus: true}, row, absent).text,
  cellAbsent: S.formRowCell({index: 2, label: "x"}, row, absent),
  cellNormal: S.formRowCell({index: 3, label: "y"}, row, absent).text,
  truncated: ["流程名", "零件名称", "零件或总成名称", "标题", "主题", "最新审批记录"].every((l) => S.FORM_TRUNCATED_COLUMN_LABELS.has(l)),
  notTruncated: S.FORM_TRUNCATED_COLUMN_LABELS.has("部门"),
  timeoutMsg: S.formViewErrorMessage(timeoutErr), timeoutRetryable: timeoutErr.retryable === true,
  httpMsg: S.formViewErrorMessage({status: 503}), limit: S.FORM_VIEW_LIMITS.timeoutMs,
  costs: costs.map((r) => ({label: r.label, total: r.total, cells: r.cells.map((c) => c.empty ? "empty" : [c.text, c.negative, Math.round(c.widthPct), c.count])})),
  fmt: [C.formatCostSum(-1234567.891), C.formatCostSum(0), C.formatCostSum(0.005), C.formatCostSum(12)],
  unrec: [C.unrecognizedStageCount({unrecognizedStageCount: 3}), C.unrecognizedStageCount({}), C.unrecognizedStageCount({unrecognizedStageCount: -1}), C.unrecognizedStageCount({unrecognizedStageCount: "x"}), C.unrecognizedStageCount([])],
  countLabel: [C.sectionCountBars([{label: "车身科", total: 2}], "数模")[0].segments[0].title.includes("数模"), C.sectionCountBars([{label: "车身科", total: 2}])[0].segments[0].title.includes("NCR明细")],
  channel: [D.mappingDiscoveryTimeoutMs("VPI-T2-D2"), D.mappingDiscoveryTimeoutMs("VPI-T2-D5"), D.mappingDiscoveryTimeoutMs("VPI-T2-D6"), D.mappingDiscoveryTimeoutMs("VPI-T2-D7"), D.mappingDiscoveryTimeoutMs("VPI-T2-D3")],
  accepted: [D.isTaskAccepted(202, {ok: true, data: {taskId: "t"}}), D.isTaskAccepted(200, {ok: true, data: {taskId: "t"}}), D.isTaskAccepted(202, {ok: true, data: {}}), D.isTaskAccepted(202, null)],
  retryable: [retryable.retryable, plain.retryable],
}));
"""


def test_form_state_chart_math_and_discovery_contracts() -> None:
    data = _run(_FORM)
    assert data["tabs"] == ["departmentStatus", "sectionStatus", "sectionCounts", "quantityTrend"]
    assert data["sorTabs"] == ["departmentStatus", "sectionStatus", "quantityTrend"]     # SOR stays out of the rollup
    # derived 状态 column only for the data model, right after 部门
    assert data["dmLabels"] == ["流程名", "部门", "状态", "零件名称"] and data["dmDerived"] == [False, False, True, False]
    assert data["sorLabels"] == ["流程名", "部门", "零件名称"]
    assert data["absent"] == [2, 7]                      # null/garbage entries never turn column 0 "absent"
    assert data["cellDerived"] == "审批中" and data["cellNormal"] == "d"
    assert data["cellAbsent"]["text"] == "源端不提供" and data["cellAbsent"]["absent"] is True
    assert data["truncated"] is True and data["notTruncated"] is False
    assert "未完成，已取消；可稍后重试" in data["timeoutMsg"] and data["timeoutRetryable"] is True
    assert data["httpMsg"] == "表单数据服务暂不可用，请稍后重试。" and data["limit"] == 30000
    body, empty = data["costs"]
    # empty (no valid value) is not zero; zero with count 1 is a real zero; negative stays negative
    assert body["cells"][0] == ["1,234.5", False, 100, 2]
    assert body["cells"][1] == ["0", False, 0, 1]
    assert body["cells"][2] == ["-50", True, 100, 1]          # normalised within its own column
    assert body["cells"][3] == "empty" and empty["cells"] == ["empty"] * 4
    assert data["fmt"] == ["-1,234,567.89", "0", "0.01", "12"]
    assert data["unrec"] == [3, 0, 0, 0, 0]
    assert data["countLabel"] == [True, True]
    assert data["channel"] == [90000, 90000, 240000, 240000, 240000]
    assert data["accepted"] == [True, False, False, False]
    assert data["retryable"] == [True, False]
