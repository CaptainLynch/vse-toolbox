"""Wizard「流水单号（多个，合并统计）」input (Task 11) through the real policy.js.

The parser/validator contracts live in ``test_plugin_overview_parity_logic.py``,
which runs the real ``policy-logic.js``. This module links ``./policy-logic.js``
as the fixture's stub, so it pins the panel *wiring* instead: which control is
rendered, what it is seeded with, how the two serial inputs disable each other,
and the ``multiSerialSyncEnabled`` capability gate (feature flag default off).

The stub never speaks for the parser: ``parseSerialSet`` here only splits on
commas, so these cases assert counts and disabled states, not normalisation.
"""

from __future__ import annotations

from tests.p1d_frontend_fixture import Scenario, load_policy_panel

D5_MATCH_FIELDS = [
    ["documentNo", "流水单号（选填）", "document_no", "例如 3D-00001018"],
    ["documentNos", "流水单号（多个，合并统计）", "document_nos", "空格或逗号分隔"],
    ["incident", "实例号(incident)（选填）", "serial_number", "纯数字实例号"],
]


def _capabilities(*, multi_enabled: bool = True, report_type: str = "data_model") -> dict:
    return {
        "syncCapable": True,
        "sourceType": "tdc",
        "reportType": report_type,
        "displayName": "数模设计审核流程报表",
        "matchFields": D5_MATCH_FIELDS,
        "evidenceFields": [],
        # 功能开关（VSE_TDC_MULTI_SERIAL_SYNC）由后端能力下发；缺省关闭。
        "multiSerialSyncEnabled": multi_enabled,
    }


def _panel(*, multi_enabled: bool = True, report_type: str = "data_model", **inputs) -> object:
    return load_policy_panel(Scenario(
        policy={"enabled": False, "credentialAvailable": True, "matchRule": {}},
        settings={"credentialVaultConfigured": True},
        discovery={},
        capabilities=_capabilities(multi_enabled=multi_enabled, report_type=report_type),
        inputs=dict(inputs),
    ))


def test_wizard_renders_multi_serial_input_when_flag_on() -> None:
    """开关开启时向导多一个独立多值输入，单值框保持原样。"""
    panel = _panel()
    panel.result.assert_ok()
    multi = panel.elements("documentNos")
    assert len(multi) == 1, multi
    assert multi[0]["tag"] == "input"
    assert multi[0]["attrs"]["data-wizard-hint"] == ""
    assert multi[0]["attrs"]["disabled"] is False
    assert len(panel.elements("documentNo")) == 1
    assert len(panel.elements("number")) == 1


def test_wizard_multi_serial_hint_counts_parsed_serials() -> None:
    """识别到 N 个单号（合并统计）随输入实时更新，并禁用单值框（三选一）。"""
    panel = _panel(documentNos="3D-1, 3D-2")
    panel.result.assert_ok()
    multi = panel.elements("documentNos")
    assert len(multi) == 1
    assert multi[0]["attrs"]["value"] == "3D-1, 3D-2"
    assert multi[0]["attrs"]["data-wizard-hint"] == "识别到 2 个单号（合并统计）"
    # 多值优先：单值框禁用，避免同一张表单填出「三选二」。
    assert panel.elements("documentNo")[0]["attrs"]["disabled"] is True


def test_wizard_multi_serial_disables_the_incident_input() -> None:
    """多值框有内容时实例号（number）同样必须禁用：三选一是双向互斥。"""
    panel = _panel(documentNos="3D-1, 3D-2")
    panel.result.assert_ok()
    assert panel.elements("documentNos")[0]["attrs"]["disabled"] is False
    assert panel.elements("number")[0]["attrs"]["disabled"] is True


def test_wizard_multi_serial_input_cap_matches_the_backend_limit() -> None:
    """maxlength 与后端 500 × 64 同口径：合法粘贴不会被静默截断（旧值 4000 会）。"""
    panel = _panel()
    panel.result.assert_ok()
    assert panel.elements("documentNos")[0]["attrs"]["maxlength"] == str(500 * 64 + 499)


def test_wizard_multi_serial_input_hidden_when_flag_off() -> None:
    """开关关闭时不得引导用户使用多单号（后端会 fail-closed）。"""
    panel = _panel(multi_enabled=False)
    panel.result.assert_ok()
    assert panel.elements("documentNos") == []
    assert panel.elements("documentNo")[0]["attrs"]["disabled"] is False


def test_wizard_multi_serial_input_only_for_the_data_model_wizard() -> None:
    """多单号只属于数模交付物：其它报表类型的向导不渲染该输入。"""
    panel = _panel(report_type="ewo")
    panel.result.assert_ok()
    assert panel.elements("documentNos") == []


def test_wizard_multi_serial_input_disabled_when_single_value_filled() -> None:
    """单值流水单号或实例号已填时，多值框禁用（三选一的双向约束）。"""
    for inputs in ({"documentNo": "3D-00001018"}, {"number": "51553863"}):
        panel = _panel(**inputs)
        panel.result.assert_ok()
        multi = panel.elements("documentNos")
        assert len(multi) == 1, inputs
        assert multi[0]["attrs"]["disabled"] is True, inputs
        assert multi[0]["attrs"]["data-wizard-hint"] == "", inputs
