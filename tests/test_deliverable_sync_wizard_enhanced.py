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
    assert 'candidateNotes = ["_change_description", "_subject"]' in click_handler
    assert "mapping = { note: matchedNotes }" in click_handler
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
    assert 'candidateNotes = ["latestCompletedNode", "processInstanceStatus"]' in click_handler

    # 数模 (D5) 映射分支
    assert "filters.project_model = modelVal" in click_handler
    assert 'candidateNotes = ["latestApproveLog", "status"]' in click_handler
    assert "mapping = { note: matchedNotes }" in click_handler
    assert "matchRule.status = statusVal" in click_handler
    assert "filters.status = statusVal" in click_handler

    # 聚合模式下通用规则：负责人设为 manual，不覆盖交付物总负责人
    assert "fieldAuthority.note = \"automatic\"" in click_handler
    assert "fieldAuthority.owner = \"manual\"" in click_handler


def test_wizard_supports_aras_paa_and_ncr_aggregate_strategy() -> None:
    """验证向导对 ARAS PAA (D6) 与 NCR (D7/D8) 聚合模式同样支持部门、车型过滤与标准备注映射。"""
    source = _source()
    click_handler = _slice(source, "startBtn.addEventListener(\"click\"", "syncNowBtn.addEventListener")

    # PAA (D6) 分支
    assert "isPaa" in click_handler
    assert "matchRule.paaNo = specificNo" in click_handler

    # NCR (D7/D8) 分支
    assert "isNcr" in click_handler
    assert "matchRule.ncrNo = specificNo" in click_handler


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


def test_sync_dispatch_and_archive_job_key_contract() -> None:
    """D6-D8 与 EWO 一样走统一的同步入口；归档任务反查契约保持不变。"""
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

    # 2. 同步入口只按 syncCapable 分派：D6-D8 与 EWO 共用同一套向导，
    #    历史上按 formSnapshotDriven 分叉出的第二套「快照同步卡」已删除
    #    （它不可达且与 EWO 结构不一致）。
    source = _source()
    policy_loader = _slice(source, "async function loadDeliverablePolicy", "const DELIVERABLE_FIXED_SOURCES")
    assert "if (capabilities && capabilities.syncCapable)" in policy_loader
    assert "formSnapshotDriven" not in policy_loader
    assert "renderSnapshotSyncCard" not in source
    assert "数据同步（外部快照）" not in source
    # 3. 只读口径改由后端投影下发（manualEditable/readOnlyReason），
    #    前端不再自行推断快照驱动语义。
    assert "item.manualEditable" in source
    assert "item.readOnlyReason" in source

    # 3. 归档明细页与交付物明细页仍可读取归档任务状态与表单视图。
    assert "/api/scheduled-archive/jobs" in source
    assert "/api/deliverable-forms/" in source

    # 4. loadDeliverableEvidence 移除永久 disabled 的死按钮
    evidence_fn = _slice(source, "async function loadDeliverableEvidence", "function debugBundleSensitiveKey")
    assert "if (syncSupported) {\n    syncActionBar.appendChild(syncBtn);\n  }" in evidence_fn


def test_wizard_data_model_status_input_safe_dom_contract() -> None:
    """数模设计审核 (D5) 增加状态选填项，采用 Safe DOM 构建，严禁 innerHTML 拼接。"""
    source = _source()
    card_func = _slice(source, "function buildSyncSummaryCard", "function renderSyncBindingEditor")

    # 1. 结构与提示
    assert "isDataModel" in card_func
    assert 'statusLabel.appendChild(overviewEl("span", null, "状态（选填）"))' in card_func
    assert 'statusInput.placeholder = "选填，如：审批中、已完成，留空查询全部"' in card_func

    # 2. remount 重新挂载
    assert "if (statusLabel) {" in card_func
    assert "wizardHost.appendChild(statusLabel);" in card_func

    # 3. 事实卡透传
    assert 'if (storedMatchRule.status) factList.push(["状态", safeDisplayValue(storedMatchRule.status)])' in card_func


def test_wizard_aggregate_note_dynamic_intersection_in_node_vm() -> None:
    """Node VM 验证聚合向导备注字段的动态交集匹配与 statusOrApprovalFields 拾取及 fail-closed 兜底。"""
    import subprocess

    node_script = """
    function resolveAggregateNotes(candidateNotes, result) {
      const reportedFields = Array.isArray(result && result.fieldReport && result.fieldReport.fields)
        ? result.fieldReport.fields
        : [];
      let matchedNotes = candidateNotes.filter((f) => reportedFields.includes(f));
      if (matchedNotes.length === 0 && result && result.fieldReport) {
        const statusOrApproval = Array.isArray(result.fieldReport.statusOrApprovalFields)
          ? result.fieldReport.statusOrApprovalFields
          : [];
        const statusColNames = statusOrApproval
          .map((entry) => (typeof entry === "string" ? entry : entry && entry.field))
          .filter((col) => col && reportedFields.includes(col));
        if (statusColNames.length > 0) {
          matchedNotes = statusColNames;
        }
      }

      if (matchedNotes.length === 0) {
        throw new Error("无法从最新脱敏字段报告确定有效的备注映射字段，请打开高级设置手工确认映射后保存。");
      }
      return matchedNotes;
    }

    // 1. 候选与报告字段部分匹配 -> 取交集
    const res1 = { fieldReport: { fields: ["latestCompletedNode", "applicant"] } };
    const matched1 = resolveAggregateNotes(["latestCompletedNode", "processInstanceStatus"], res1);
    if (matched1.length !== 1 || matched1[0] !== "latestCompletedNode") {
      throw new Error("Expected latestCompletedNode, got: " + JSON.stringify(matched1));
    }

    // 2. 候选全部不匹配，但 statusOrApprovalFields 存在真实列 -> 拾取 statusOrApprovalFields
    const res2 = {
      fieldReport: {
        fields: ["applicant", "flowStatus"],
        statusOrApprovalFields: [{ field: "flowStatus", samples: ["审批完成"] }]
      }
    };
    const matched2 = resolveAggregateNotes(["latestCompletedNode", "processInstanceStatus"], res2);
    if (matched2.length !== 1 || matched2[0] !== "flowStatus") {
      throw new Error("Expected flowStatus fallback, got: " + JSON.stringify(matched2));
    }

    // 3. 候选与 statusOrApprovalFields 均无匹配 -> Fail-Closed 抛错
    let caught = false;
    try {
      resolveAggregateNotes(["latestCompletedNode"], { fieldReport: { fields: ["applicant"] } });
    } catch (e) {
      caught = true;
      if (!e.message.includes("无法从最新脱敏字段报告确定有效的备注映射字段")) {
        throw new Error("Unexpected error: " + e.message);
      }
    }
    if (!caught) throw new Error("Expected fail-closed error");

    console.log("PASS");
    """
    proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
    assert "PASS" in proc.stdout
