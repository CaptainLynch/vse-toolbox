"""数模（D5）向导「科室（可多选）」字段的渲染接线（真实 policy.js + 桩）。

纯逻辑契约在 test_plugin_overview_data_model_sections.py（真实 policy-logic.js）。
本模块只钉接线：D5 向导渲染科室字段，NCR 走自己的声明式科室字段，其它交付物
不渲染——避免把「筛选式科室」误挂到 SOR/PAA/EWO 上。
"""

from __future__ import annotations

from tests.p1d_frontend_fixture import Scenario, load_policy_panel

D5_MATCH_FIELDS = [
    ["documentNo", "流水单号（选填）", "document_no", "例如 3D-00001018"],
    ["incident", "实例号(incident)（选填）", "serial_number", "纯数字实例号"],
]

DEFAULT_SECTIONS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"]


def _capabilities(*, report_type: str = "data_model", source_type: str = "tdc") -> dict:
    return {
        "syncCapable": True,
        "sourceType": source_type,
        "reportType": report_type,
        "displayName": "数模设计审核流程报表",
        "matchFields": D5_MATCH_FIELDS,
        "evidenceFields": [],
        "sectionPresets": DEFAULT_SECTIONS if report_type == "data_model" else None,
        "sectionScopePresets": (
            ["车身科", "内饰科"]
            if report_type in {"ncr_progress", "ncr_detail"}
            else None
        ),
    }


def _panel(*, report_type: str = "data_model", source_type: str = "tdc", **inputs) -> object:
    return load_policy_panel(Scenario(
        policy={"enabled": False, "credentialAvailable": True, "matchRule": {}},
        settings={"credentialVaultConfigured": True},
        discovery={},
        capabilities=_capabilities(report_type=report_type, source_type=source_type),
        inputs=dict(inputs),
    ))


def test_data_model_wizard_renders_section_filter_field() -> None:
    panel = _panel()
    panel.result.assert_ok()
    fields = panel.elements("sections")
    assert len(fields) == 1, fields
    assert fields[0]["tag"] == "label"


def test_sor_wizard_does_not_render_section_filter_field() -> None:
    panel = _panel(report_type="sor")
    panel.result.assert_ok()
    assert panel.elements("sections") == []


def test_ncr_wizard_keeps_its_own_declaration_field() -> None:
    """NCR 的科室是声明式范围（sectionScope），不得复用数模的 sections 字段。"""
    panel = _panel(report_type="ncr_detail", source_type="aras")
    panel.result.assert_ok()
    assert panel.elements("sections") == []
