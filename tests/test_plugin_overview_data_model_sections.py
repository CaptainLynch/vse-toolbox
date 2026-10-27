# -*- coding: utf-8 -*-
"""数模（D5）向导科室多选的纯逻辑契约（Node 下执行 policy-logic.js）。

锁三件事：
1. 默认勾选 = 后端下发的科室预设（默认现行五科室）；
2. 科室集合进 matchRule.sections 与发现请求的 filters.sections（本地收窄），
   绝不作为上游单值 department 参数；
3. 高级设置保存不得静默丢掉已存科室筛选。
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


_SCRIPT = r"""
const base = process.argv[1];
const P = await import(base + "/deliverable/policy-logic.js");
const PRESETS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"];
const dmCaps = {reportType: "data_model", sourceType: "tdc", sectionPresets: PRESETS,
  matchFields: [], evidenceFields: []};
const dmCapsNoPresets = {reportType: "data_model", sourceType: "tdc", matchFields: [], evidenceFields: []};
const ncrCaps = {reportType: "ncr_detail", sourceType: "aras", sectionScopePresets: ["车身科"],
  matchFields: [], evidenceFields: []};

const initDefault = P.wizardInitialValues({matchRule: {}}, dmCaps, true);
const initStored = P.wizardInitialValues({matchRule: {sections: ["车身科"], department: "车体工程"}}, dmCaps, true);
const initLegacyDeptOnly = P.wizardInitialValues({matchRule: {department: "车体工程"}}, dmCaps, true);
const initNoPresets = P.wizardInitialValues({matchRule: {}}, dmCapsNoPresets, true);
const initNcr = P.wizardInitialValues({matchRule: {sectionScope: ["车身科"]}}, ncrCaps, true);

const values = (sections, department = "") => ({credential: "domain", model: "F620S", number: "",
  documentNo: "", status: "", sections, interval: "15", defaultDept: "车体工程", department});
const dmWithSections = P.buildWizardDiscovery(values(PRESETS), dmCaps);
const dmNoSections = P.buildWizardDiscovery(values([], "车体工程"), dmCaps);
const dmBlankSections = P.buildWizardDiscovery(values(["  ", "车身科", ""]), dmCaps);

const stored = {matchRule: {reportType: "data_model", aggregate: true, sections: ["车身科", "内饰科"]}};
const editorKeep = P.buildPolicyPayload({id: "VPI-T2-D5"}, dmCaps, stored,
  {mode: "automatic", enabled: false, match: {}, authority: {}, mapping: {}, interval: "15", externalKey: ""});
const editorDrop = P.buildPolicyPayload({id: "VPI-T2-D5"}, dmCapsNoPresets,
  {matchRule: {reportType: "data_model", aggregate: true, sections: ["车身科"]}},
  {mode: "automatic", enabled: false, match: {}, authority: {}, mapping: {}, interval: "15", externalKey: ""});

console.log(JSON.stringify({
  initDefault: {sections: initDefault.sections, department: initDefault.department},
  initStored: {sections: initStored.sections, department: initStored.department},
  initLegacyDeptOnly: {sections: initLegacyDeptOnly.sections, department: initLegacyDeptOnly.department},
  initNoPresets: {sections: initNoPresets.sections, department: initNoPresets.department},
  initNcr: initNcr.sections,
  dmWithSections: {filters: dmWithSections.filters, rule: dmWithSections.matchRule},
  dmNoSections: {filters: dmNoSections.filters, rule: dmNoSections.matchRule},
  dmBlankSections: {filters: dmBlankSections.filters, rule: dmBlankSections.matchRule},
  editorKeep: editorKeep.matchRule,
  editorDrop: editorDrop.matchRule,
}));
"""


def test_wizard_defaults_to_section_presets_and_blank_department() -> None:
    data = _run(_SCRIPT)
    assert data["initDefault"]["sections"] == ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"]
    # 部门口径不稳定：新配置默认留空，不再预填「车体工程」。
    assert data["initDefault"]["department"] == ""
    assert data["initStored"] == {"sections": ["车身科"], "department": "车体工程"}
    # 存量只存了部门：科室仍按预设默认勾选，部门回填供用户自行清空。
    assert data["initLegacyDeptOnly"]["sections"] == data["initDefault"]["sections"]
    assert data["initLegacyDeptOnly"]["department"] == "车体工程"
    # 后端未下发预设（老库/其它来源）时不得凭空造值。
    assert data["initNoPresets"]["sections"] == []
    # NCR 的声明式范围回填不受影响。
    assert data["initNcr"] == ["车身科"]


def test_wizard_discovery_carries_sections_locally_not_as_department() -> None:
    data = _run(_SCRIPT)
    sections = data["dmWithSections"]
    assert sections["filters"]["sections"] == [
        "车体科", "车身科", "内饰科", "外饰科", "车体架构集成科",
    ]
    assert sections["rule"]["sections"] == sections["filters"]["sections"]
    assert "department" not in sections["filters"]
    # 清空科室 = 不限科室；部门只在显式填写时才作为上游条件。
    assert "sections" not in data["dmNoSections"]["filters"]
    assert data["dmNoSections"]["filters"]["department"] == "车体工程"
    # 空白项被剔除，不产生幽灵科室。
    assert data["dmBlankSections"]["filters"]["sections"] == ["车身科"]


def test_advanced_editor_keeps_sections_but_never_invents_them() -> None:
    data = _run(_SCRIPT)
    assert data["editorKeep"]["sections"] == ["车身科", "内饰科"]
    assert "sections" not in data["editorDrop"]
