# -*- coding: utf-8 -*-
"""Static contract tests for the deliverable sync summary card and wizard (A)."""

from pathlib import Path


JS_PATH = Path("web/static/app.js")
CSS_PATH = Path("web/static/style.css")
HTML_PATH = Path("web/templates/dashboard.html")


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8-sig")


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


def test_sync_summary_card_renders_state_timestamps_and_redacted_error() -> None:
    """摘要卡：当前同步态、最近成功/尝试时间与脱敏最近错误（A1）。"""
    source = _source()
    card = _slice(source, "function buildSyncSummaryCard", "function renderSyncBindingEditor")

    for marker in (
        "policy-sync-summary",
        "数据同步",
        "deliverableSyncDisplay(item)",
        "最近尝试",
        "最近成功",
        "最近错误",
        "currentPolicy.lastAttemptAt",
        "currentPolicy.lastSuccessAt",
        "currentPolicy.lastErrorMessage",
        "redactSensitiveText",
    ):
        assert marker in card, marker


def test_summary_card_buttons_gate_on_capability_and_enabled_state() -> None:
    """开启自动同步按钮仅在 syncCapable 且未启用时显示；已启用显示立即同步。"""
    source = _source()
    card = _slice(source, "function buildSyncSummaryCard", "function renderSyncBindingEditor")

    assert "开启自动同步" in card
    assert "立即同步" in card
    assert "capabilities.syncCapable === true && currentPolicy.enabled !== true" in card
    assert "syncNowBtn.hidden = currentPolicy.enabled !== true" in card
    assert "requestProjectStatusSync(item)" in card
    # 高级设置折叠入口。
    assert "advancedDetails.open = !advancedDetails.open" in card
    assert "policy-sync-advanced-btn" in card


def test_wizard_collects_minimal_inputs_and_follows_endpoint_sequence() -> None:
    """向导：最小输入 → mapping-discovery → 稳定性 2/2 → update-policy
    PATCH → sync-now，端点调用序列符合 A2 契约。"""
    source = _source()
    wizard_inputs = _slice(source, "function buildSyncSummaryCard", "startBtn.addEventListener(\"click\"")
    wizard = _slice(source, "startBtn.addEventListener(\"click\"", "syncNowBtn.addEventListener")

    # 第一步最小输入：凭据引用（与绑定表单同一数据源）+ 外部编号。
    assert "统一域账号（domain）" in wizard_inputs
    assert "credentialSelect.value = \"domain\"" in wizard_inputs
    assert "wizardPrimaryMatchField" in _source()
    # 外部编号占位提示从能力注册表 matchFields 生成。
    primary = _slice(_source(), "function wizardPrimaryMatchField", "function wizardEvidenceDefaults")
    assert "capabilities.matchFields" in primary
    assert "placeholder: primary[3]" in primary

    # 调用序列：mapping-discovery（两次取证）→ update-policy PATCH → sync-now。
    assert "postMappingDiscovery(item.id, payload)" in wizard
    assert "映射稳定性" in wizard
    assert "stability.confirmed" in wizard
    assert "mode: \"automatic\"" in wizard
    assert "enabled: true" in wizard
    assert "matchRule," in wizard
    assert "mapping," in wizard
    assert "fieldAuthority," in wizard
    assert "credentialRef" in wizard
    assert "/update-policy" in wizard
    assert "requestProjectStatusSync(item)" in wizard

    # 失败可重试：错误脱敏后展示，按钮恢复可用。
    assert "startBtn.disabled = false" in wizard
    assert "redactSensitiveText(ewoPolicyErrorMessage(err))" in wizard


def test_wizard_candidate_selection_and_safe_dom_only() -> None:
    """候选唯一自动选中、多个列出让用户选一次；全程 Safe DOM 无 innerHTML。"""
    source = _source()
    wizard_block = _slice(source, "function buildSyncSummaryCard", "function renderSyncBindingEditor")

    assert "result.state === \"ambiguous\"" in wizard_block
    assert "pickCandidateOnce" in wizard_block
    assert "payload.selectedExternalKey = selected" in wizard_block
    assert "innerHTML" not in wizard_block
    assert "document.write" not in wizard_block


def test_wizard_mapping_derivation_is_capability_and_evidence_grounded() -> None:
    """映射推导只允许能力注册表 fieldSemantics「」提示命中最新脱敏
    字段报告中的真实字段；推导失败给出可重试错误，不伪造映射。"""
    source = _source()
    derivation = _slice(
        source,
        "function wizardQuotedHints",
        "async function postMappingDiscovery",
    )

    assert "capabilities.fieldSemantics" in derivation
    assert "「" in derivation  # 「…」引用的来源列名提示
    assert "fieldReport.fields" in derivation
    assert "return null" in derivation

    wizard_block = _slice(source, "function buildSyncSummaryCard", "function renderSyncBindingEditor")
    assert "无法从最新脱敏字段报告确定自动字段映射" in wizard_block


def test_advanced_settings_collapses_existing_binding_form() -> None:
    """A3：完整绑定表单迁入默认收起的 details 高级设置区，保存逻辑复用。"""
    source = _source()
    tail = _slice(source, "const advancedDetails = document.createElement(\"details\")", "function renderArchiveDeliverableDetailPage")

    for marker in (
        "policy-advanced-settings",
        "高级设置",
        "advancedDetails.append(advancedSummary, head, form)",
        "buildSyncSummaryCard(item, currentPolicy, capabilities, settingsData, advancedDetails)",
    ):
        assert marker in tail, marker


def test_pending_config_and_manual_hints_rendered_in_summary_card() -> None:
    """A4：pending_config 与 manual 态都有定位说明文案。"""
    source = _source()
    hints = _slice(source, "const POLICY_SYNC_HINTS", "const POLICY_WIZARD_TDC_DEFAULT_BASE_URL")

    assert "pending_config" in hints
    assert "绑定已就绪，开启自动同步后将映射外部状态；当前显示的是手工填写值。" in hints
    assert "manual" in hints
    assert "手工维护" in hints


def test_summary_card_styles_present() -> None:
    css = CSS_PATH.read_text(encoding="utf-8-sig")
    for marker in (
        ".policy-sync-summary",
        ".policy-sync-summary-hint",
        ".policy-sync-summary-actions",
        ".policy-sync-wizard",
        ".policy-advanced-settings",
        ".policy-advanced-summary",
    ):
        assert marker in css, marker


def test_wizard_note_mapping_uses_normalized_equality() -> None:
    """行为断言（node 执行推导函数）：note 来源列归一化全等命中；全等
    无命中时 note 来源为空（不写 note 键），绝不回退子串包含；owner
    唯一命中判定保持不变。"""
    import subprocess
    import tempfile

    source = _source()
    helpers = _slice(source, "function ewoPolicyString", "function ewoPolicyDiscoveryFields")
    derivation = _slice(source, "function wizardQuotedHints", "async function postMappingDiscovery")
    scenario = """
const assert = require("node:assert/strict");
const capabilities = {
  fieldSemantics: {
    owner: "负责人（「责任工程师」列）",
    note: "风险备注（「Approval_Status」+「审批状态」组合）",
  },
};
// ① 归一化全等命中：trim / 大小写折叠 / 下划线与连字符归一后完全相等。
const hit = wizardDeriveMappingFromFieldReport(capabilities, {
  fields: ["approval-status", " 审批状态 ", "无关列"],
});
assert(hit && Array.isArray(hit.note), "note 命中时应为列表来源");
assert.deepEqual(hit.note, ["approval-status", "审批状态"]);
// ② 子串包含不再命中：两个报告列都只含提示词子串 → note 来源为空。
const miss = wizardDeriveMappingFromFieldReport(capabilities, {
  fields: ["Approval_Status_History", "最新审批状态记录", "其它"],
});
assert(miss === null || !("note" in miss), "全等无命中时不得写 note 来源");
// ③ owner 仍按子串包含 + 唯一命中（matches.length === 1）判定，行为不变。
const ownerHit = wizardDeriveMappingFromFieldReport(
  { fieldSemantics: { owner: "负责人（「责任工程师」列）" } },
  { fields: ["责任工程师名称", "其它"] },
);
assert(ownerHit && ownerHit.owner === "责任工程师名称");
console.log("PASS");
"""
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "wizard_derivation_check.js"
        script_path.write_text(helpers + "\n" + derivation + "\n" + scenario, encoding="utf-8")
        result = subprocess.run(
            ["node", str(script_path)], capture_output=True, text=True,
            cwd=JS_PATH.resolve().parents[1],
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_wizard_failure_path_remounts_inputs_for_retry() -> None:
    """行为断言（静态契约）：候选全部缺外部键被拒绝或其它失败进入 catch
    后，除脱敏状态提示外必须重挂向导输入区（凭据引用 + 外部编号输入 +
    开始按钮），与成功歧义路径共用同一重挂实现，无需刷新页面即可重试。"""
    source = _source()
    wizard = _slice(
        source,
        "startBtn.addEventListener(\"click\"",
        "syncNowBtn.addEventListener",
    )

    # 重挂实现单一来源：helper 依次清空并重挂三个输入节点。
    helper = _slice(source, "const remountWizardInputs = () => {", "};")
    assert "wizardHost.textContent = \"\";" in helper
    assert "wizardHost.appendChild(credentialLabel);" in helper
    assert "wizardHost.appendChild(numberLabel);" in helper
    assert "wizardHost.appendChild(startBtn);" in helper

    # 成功歧义路径与流程起点均复用该 helper。
    assert "const selected = await pickCandidateOnce(result.candidates);\n        remountWizardInputs();" in wizard
    assert "startBtn.disabled = true;\n    remountWizardInputs();" in wizard

    # catch 分支：脱敏状态提示 + 重挂输入区 + 恢复按钮，可立即重试。
    catch_block = _slice(wizard, "} catch (err) {", "});\n")
    assert "redactSensitiveText(ewoPolicyErrorMessage(err))" in catch_block
    assert "remountWizardInputs();" in catch_block
    assert "startBtn.disabled = false;" in catch_block
    # 拒绝路径源头：候选全部缺外部键时 reject，进入上述 catch。
    reject_source = _slice(source, "if (!select.options.length) reject", ");")
    assert "候选记录缺少外部稳定键" in reject_source


def test_wizard_derivation_handles_real_aras_and_tdc_crawler_fields() -> None:
    """真实抓取返回的英文属性名（_rsp_name, applicant 等）能被正确命中。"""
    import subprocess
    import tempfile

    source = _source()
    helpers = _slice(source, "function ewoPolicyString", "function ewoPolicyDiscoveryFields")
    derivation = _slice(source, "function wizardQuotedHints", "async function postMappingDiscovery")
    scenario = """
const assert = require("node:assert/strict");
// Aras EWO 真实爬虫字段测试
const ewoCaps = {
  fieldSemantics: {
    owner: "负责人（「_rsp_name」「责任工程师名称」列）",
    plannedDate: "计划完成日期（「_required_date」「要求完成时间」列）",
    note: "风险备注（「_subject」「_change_description」「当前阶段未签署的角色&人员」列）",
  },
};
const ewoHit = wizardDeriveMappingFromFieldReport(ewoCaps, {
  fields: ["_no", "_rsp_name", "_required_date", "_subject", "_change_description", "state"],
});
assert(ewoHit, "EWO 应成功推导映射");
assert.equal(ewoHit.owner, "_rsp_name");
assert.equal(ewoHit.plannedDate, "_required_date");
assert.deepEqual(ewoHit.note, ["_subject", "_change_description"]);

// TDC SOR 真实爬虫字段测试
const sorCaps = {
  fieldSemantics: {
    owner: "负责人（报表「startUserName」「申请人」列）",
    note: "风险备注（「latestCompletedNode」「processInstanceStatus」「最新完成节点」+「审批状态」组合）",
  },
};
const sorHit = wizardDeriveMappingFromFieldReport(sorCaps, {
  fields: ["processNo", "startUserName", "latestCompletedNode", "processInstanceStatus", "carTypeProject"],
});
assert(sorHit, "SOR 应成功推导映射");
assert.equal(sorHit.owner, "startUserName");
assert.deepEqual(sorHit.note, ["latestCompletedNode", "processInstanceStatus"]);
console.log("PASS");
"""
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "crawler_derivation_check.js"
        script_path.write_text(helpers + "\n" + derivation + "\n" + scenario, encoding="utf-8")
        result = subprocess.run(
            ["node", str(script_path)], capture_output=True, text=True,
            cwd=JS_PATH.resolve().parents[1],
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_binding_editor_prefills_default_mapping() -> None:
    """高级设置表单预填默认映射，且来源映射支持从脱敏报告中下拉选择。"""
    source = _source()
    editor_block = _slice(source, "function renderSyncBindingEditor", "async function loadDeliverablePolicy")
    assert "mappingInput.placeholder = `推荐：" in editor_block
    assert "mappingInput.setAttribute(\"list\"" in editor_block
    assert "setDiscoveredFields(fields)" in editor_block
