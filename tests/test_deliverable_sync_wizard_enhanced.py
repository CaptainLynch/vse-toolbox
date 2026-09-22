# -*- coding: utf-8 -*-
"""Enhanced contract tests for deliverable sync wizard (aggregate default, department, interval)."""

from pathlib import Path


JS_PATH = Path("web/static/app.js")


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8-sig")


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


def test_wizard_renders_model_department_and_interval_inputs() -> None:
    """验证向导包含车型、责任部门（默认车体工程）以及定时同步周期输入。"""
    source = _source()
    wizard = _slice(source, "function buildSyncSummaryCard", "startBtn.addEventListener(\"click\"")

    # 1. 车型项目 / 车型信息
    assert "车型项目 / 车型信息" in wizard
    assert "modelInput.placeholder" in wizard

    # 2. 责任部门，默认预填“技术中心_车体工程”
    assert "责任部门" in wizard
    assert "技术中心_车体工程" in wizard
    assert "initialDept" in wizard

    # 3. 定时同步周期选项
    assert "定时自动同步周期" in wizard
    assert "每 15 分钟（推荐）" in wizard
    assert "每 30 分钟" in wizard
    assert "每 1 小时" in wizard
    assert "每 6 小时" in wizard
    assert "每天" in wizard


def test_wizard_defaults_to_record_set_aggregate_and_single_click_enable() -> None:
    """验证向导默认以集合模式抓取，并一键提交 intervalMinutes 与 contractVersion='2'。"""
    source = _source()
    click_handler = _slice(source, "startBtn.addEventListener(\"click\"", "syncNowBtn.addEventListener")

    # 默认聚合与 EWO v2 记录集合
    assert "const aggregate = !specificNo" in click_handler
    assert "matchRule.contractVersion = \"2\"" in click_handler
    assert "matchRule.bindingMode = aggregate ? \"record_set\" : \"single_record\"" in click_handler

    # 部门过滤与车型过滤自动挂载
    assert "matchRule.rspDepartment = deptVal" in click_handler
    assert "filters.rsp_department = deptVal" in click_handler
    assert "matchRule.projectCode = modelVal" in click_handler
    assert "filters.project_code = modelVal" in click_handler

    # EWO 记录集合只映射 note，不映射标量 owner / plannedDate
    assert "mapping = { note: [\"_change_description\", \"_subject\"] }" in click_handler
    assert "fieldAuthority.note = \"automatic\"" in click_handler
    assert "fieldAuthority.owner = \"manual\"" in click_handler
    assert "fieldAuthority.plannedDate = \"manual\"" in click_handler

    # 提交 patch 包含 intervalMinutes 与 bindingContractVersion
    assert "intervalMinutes: intervalMins" in click_handler
    assert "patch.bindingContractVersion = \"2\"" in click_handler
    assert "enabled: true" in click_handler


def test_reconfig_button_and_advanced_editor_interval() -> None:
    """验证已启用时展示【修改同步配置】与事实摘要，且高级设置包含周期选择。"""
    source = _source()
    card = _slice(source, "function buildSyncSummaryCard", "function renderSyncBindingEditor")
    editor = _slice(source, "function renderSyncBindingEditor", "function renderDeliverableStatusChart")

    # 1. 摘要卡显示修改配置按钮
    assert "修改同步配置" in card
    assert "reconfigBtn" in card
    assert "同步周期" in card
    assert "责任部门" in card

    # 2. 高级设置支持定时同步周期
    assert "name = \"intervalMinutes\"" in editor
    assert "payload.intervalMinutes = parseInt(intervalInput.value, 10) || 15" in editor


def test_wizard_supports_tdc_sor_and_data_model_aggregate_strategy() -> None:
    """验证向导对 TDC SOR (D2) 与数模 (D5) 聚合模式同样支持部门、车型过滤与标准备注映射。"""
    source = _source()
    click_handler = _slice(source, "startBtn.addEventListener(\"click\"", "syncNowBtn.addEventListener")

    # SOR (D2) 映射分支
    assert "filters.car_type_project = modelVal" in click_handler
    assert "filters.department = deptVal" in click_handler
    assert 'mapping = { note: ["latestCompletedNode", "processInstanceStatus"] }' in click_handler

    # 数模 (D5) 映射分支
    assert "filters.project_model = modelVal" in click_handler
    assert 'mapping = { note: ["latestApproveLog", "status"] }' in click_handler

    # 聚合模式下通用规则：负责人设为 manual，不覆盖交付物总负责人
    assert "fieldAuthority.note = \"automatic\"" in click_handler
    assert "fieldAuthority.owner = \"manual\"" in click_handler


def test_normalize_tdc_department_pure_function_in_node_vm() -> None:
    """验证 normalizeTdcDepartment 纯函数在 Node VM 下的各边界输入转换行为。"""
    import subprocess

    node_script = """
    const fs = require('fs');
    const source = fs.readFileSync('web/static/app.js', 'utf8');
    const fnMatch = source.match(/function normalizeTdcDepartment\\([\\s\\S]*?\\n\\}/);
    if (!fnMatch) throw new Error('normalizeTdcDepartment not found');
    eval(fnMatch[0]);

    const asserts = [
        [normalizeTdcDepartment("技术中心_车体工程"), "车体工程"],
        [normalizeTdcDepartment("技术中心-车体工程"), "车体工程"],
        [normalizeTdcDepartment("技术中心车体工程"), "车体工程"],
        [normalizeTdcDepartment("技术中心_外饰科"), "外饰科"],
        [normalizeTdcDepartment("车体工程"), "车体工程"],
        [normalizeTdcDepartment("技术中心"), "技术中心"],
        [normalizeTdcDepartment(""), ""],
        [normalizeTdcDepartment(null), ""],
        [normalizeTdcDepartment(undefined), ""],
    ];
    for (const [actual, expected] of asserts) {
        if (actual !== expected) {
            console.error(`Expected '${expected}', got '${actual}'`);
            process.exit(1);
        }
    }
    console.log("PASS");
    """
    proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
    assert "PASS" in proc.stdout


def test_wizard_department_decoupling_and_discovery_auto_retry() -> None:
    """验证向导中责任部门可彻底清空（移除 || 默认值），且 TDC not_found 时自动不带部门重试（聚合与单记录皆生效）。"""
    source = _source()
    click_handler = _slice(source, "startBtn.addEventListener(\"click\"", "syncNowBtn.addEventListener")

    # 1. 不再使用 || "技术中心_车体工程" 强制保底，允许彻底留空
    assert '|| "技术中心_车体工程"' not in click_handler
    assert "const rawDeptVal = ewoPolicyString(departmentInput.value);" in click_handler
    assert "const deptVal = isTdc ? normalizeTdcDepartment(rawDeptVal) : rawDeptVal;" in click_handler

    # 2. not_found 自动重试（不带部门参数）
    assert "if (result.state !== \"matched\" && isTdc && deptVal)" in click_handler
    assert "delete retryFilters.department;" in click_handler
    assert "delete retryFilters.rsp_department;" in click_handler
    assert "postMappingDiscovery(item.id, retryPayload)" in click_handler


def test_snapshot_sync_card_and_archive_job_key_contract() -> None:
    """验证 D6-D8 详情页快照同步卡与后端 archiveJobKey 契约。"""
    from core.project_status_contracts import find_job_key_by_deliverable_id

    # 1. 后端注册表反查契约
    assert find_job_key_by_deliverable_id("VPI-T2-D6") == "aras_paa"
    assert find_job_key_by_deliverable_id("VPI-T2-D7") == "aras_ncr_progress"
    assert find_job_key_by_deliverable_id("VPI-T2-D8") == "aras_ncr_detail"
    assert find_job_key_by_deliverable_id("VPI-T2-D2") == "tdc_sor"
    assert find_job_key_by_deliverable_id("VPI-T2-D3") == "aras_ewo"
    assert find_job_key_by_deliverable_id("VPI-T2-D5") == "tdc_data_model"
    assert find_job_key_by_deliverable_id("VPI-T2-D1") is None
    assert find_job_key_by_deliverable_id("VPI-T2-D4") is None

    # 2. 前端 loadDeliverablePolicy 对 formSnapshotDriven 交付物渲染快照同步卡
    source = _source()
    policy_loader = _slice(source, "async function loadDeliverablePolicy", "const DELIVERABLE_FIXED_SOURCES")
    assert "if (item.formSnapshotDriven === true)" in policy_loader
    assert "renderSnapshotSyncCard(container, item, capabilities, options)" in policy_loader

    # 3. renderSnapshotSyncCard 结构与 Safe DOM 规范
    card_fn = _slice(source, "function renderSnapshotSyncCard", "async function loadDeliverablePolicy")
    assert "policy-snapshot-sync-card" in card_fn
    assert "数据同步（外部快照）" in card_fn
    assert "快照驱动" in card_fn
    assert "立即同步快照" in card_fn
    assert "查看同步任务" in card_fn
    assert "/api/scheduled-archive/jobs/" in card_fn
    assert "/sync-now" in card_fn
    assert "data.exitCode !== 0" in card_fn
    assert "firstRes.outcome !== \"completed\"" in card_fn
    assert "loadArchiveJobs(true)" in card_fn
    assert "options.onFormReload()" in card_fn
    assert "innerHTML" not in card_fn
    assert "document.write" not in card_fn

    # 4. loadDeliverableEvidence 移除永久 disabled 的死按钮
    evidence_fn = _slice(source, "async function loadDeliverableEvidence", "function debugBundleSensitiveKey")
    assert "if (syncSupported) {\n    syncActionBar.appendChild(syncBtn);\n  }" in evidence_fn


def test_snapshot_sync_card_click_behavior_in_node_vm() -> None:
    """验证快照同步卡在 Node VM 下的点击行为：严格根据 exitCode 与 outcome 判定成败，不发生假成功。"""
    import subprocess

    node_script = """
    const fs = require('fs');
    const vm = require('vm');
    const source = fs.readFileSync('web/static/app.js', 'utf8');

    const code = [
      'function overviewEl(tag, cls, text) {',
      '  const el = { tagName: tag, className: cls || "", textContent: text || "", children: [], attributes: {}, eventListeners: {} };',
      '  el.appendChild = (c) => el.children.push(c);',
      '  el.append = (...cs) => cs.forEach(c => el.children.push(c));',
      '  el.setAttribute = (k, v) => { el.attributes[k] = v; };',
      '  el.addEventListener = (evt, fn) => { el.eventListeners[evt] = fn; };',
      '  return el;',
      '}',
      'function safeDisplayValue(val) { return String(val || ""); }',
      'function redactSensitiveText(txt) { return String(txt || ""); }',
      'let loadArchiveJobsCalled = false; async function loadArchiveJobs() { loadArchiveJobsCalled = true; }',
      'let loadProjectOverviewCalled = false; async function loadProjectOverview() { loadProjectOverviewCalled = true; }',
    ].join('\\n');

    const start = source.indexOf('function renderSnapshotSyncCard');
    const end = source.indexOf('async function loadDeliverablePolicy', start);
    const cardCode = source.slice(start, end);

    const sandbox = { console };
    vm.createContext(sandbox);
    vm.runInContext(code + '\\n' + cardCode, sandbox);

    async function runTest() {
      const container = sandbox.overviewEl('div');
      const item = { id: 'VPI-T2-D6', name: 'PAA', formSnapshotDriven: true };
      const capabilities = { archiveJobKey: 'aras_paa' };

      // 1. 错误判定：exitCode != 0 且 outcome == 'not_ready' 时必须按失败处理，禁止假成功
      sandbox.fetch = async () => ({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            exitCode: 2,
            results: [{ outcome: 'not_ready', errorMessage: 'archive job configuration is not ready' }]
          }
        })
      });

      sandbox.renderSnapshotSyncCard(container, item, capabilities, {});
      const card = container.children[0];
      const actions = card.children[3];
      const btn = actions.children[0];
      const statusMsg = actions.children[2];

      await btn.eventListeners['click']();
      if (!statusMsg.textContent.includes('archive job configuration is not ready')) {
        throw new Error('Expected error message in statusMsg, got: ' + statusMsg.textContent);
      }
      if (!statusMsg.className.includes('is-error')) {
        throw new Error('Expected is-error class');
      }

      // 2. 成功判定：exitCode == 0 且 outcome == 'completed' 时触发刷新并展示成功
      let formReloaded = false;
      sandbox.fetch = async () => ({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            exitCode: 0,
            results: [{ outcome: 'completed', finalState: 'success' }]
          }
        })
      });

      const container2 = sandbox.overviewEl('div');
      sandbox.renderSnapshotSyncCard(container2, item, capabilities, { onFormReload: () => { formReloaded = true; } });
      const btn2 = container2.children[0].children[3].children[0];
      const statusMsg2 = container2.children[0].children[3].children[2];
      await btn2.eventListeners['click']();
      if (!statusMsg2.textContent.includes('快照同步成功')) {
        throw new Error('Expected success message in statusMsg2, got: ' + statusMsg2.textContent);
      }
      if (!formReloaded) {
        throw new Error('Expected onFormReload to be called');
      }
      console.log("PASS");
    }

    runTest();
    """
    proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
    assert "PASS" in proc.stdout
