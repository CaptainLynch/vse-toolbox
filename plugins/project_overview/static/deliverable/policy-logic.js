// Pure rules of the sync binding editor and the "开启自动同步" wizard
// (legacy renderSyncBindingEditor / buildSyncSummaryCard). The components
// keep the form values; these functions turn them into API payloads and
// readiness messages. Import-free apart from ./format.js; node-tested.
import { parseHeaders } from "./format.js";

export const EWO_POLICY_MODE_LABELS = { manual: "手动维护", automatic: "自动同步", hybrid: "混合模式" };
export const EWO_POLICY_RECOMMENDED_MODE = "automatic";
export const EWO_POLICY_DEFAULT_ARAS_BASE_URL = "http://ecm.sgmw.com.cn/innovatorserver";
export const POLICY_WIZARD_TDC_DEFAULT_BASE_URL = "https://tdc.sgmw.com.cn/";
export const EWO_POLICY_MATCH_FIELDS = [
  ["ewoNo", "EWO 编号", "ewo_no"],
  ["projectCode", "车型项目", "project_code"],
  ["subjectKeyword", "主题关键词", "subject_keyword"],
  ["modelInfo", "车型信息", "model_info"],
];
export const EWO_POLICY_AUTOMATIC_FIELDS = [
  ["owner", "负责人"],
  ["plannedDate", "计划完成日期"],
  ["note", "风险与备注"],
];
export const INTERVAL_OPTIONS = [
  ["15", "每 15 分钟（推荐）"],
  ["30", "每 30 分钟"],
  ["60", "每 1 小时"],
  ["360", "每 6 小时"],
  ["1440", "每天"],
];
export const POLICY_SYNC_HINTS = {
  pending_config: "绑定已就绪，开启自动同步后将映射外部状态；当前显示的是手工填写值。",
  manual: "该交付物当前为手工维护；可开启自动同步，或在高级设置中配置绑定。",
  paused: "自动同步已暂停；可开启自动同步恢复，或在高级设置中调整绑定。",
};
const EWO_RULE_KEYS = ["ewoNo", "projectCode", "subjectKeyword", "changeType", "changeSubType", "area", "state", "rspDepartment", "rspSmt", "submitStart", "submitEnd", "modelInfo"];
const EWO_FILTER_NAMES = {
  ewoNo: "ewo_no", projectCode: "project_code", subjectKeyword: "subject_keyword", changeType: "change_type",
  changeSubType: "change_sub_type", area: "area", state: "state", rspDepartment: "rsp_department", rspSmt: "rsp_smt",
  submitStart: "submit_start", submitEnd: "submit_end", modelInfo: "model_info",
};
const DEFAULT_MAPPINGS = {
  "VPI-T2-D2": { owner: "startUserName", note: ["latestCompletedNode", "processInstanceStatus"] },
  "VPI-T2-D3": { owner: "_rsp_name", plannedDate: "_required_date", note: ["_subject", "_change_description"] },
  "VPI-T2-D5": { owner: "applicant", note: ["latestApproveLog", "status"] },
};

export function ewoPolicyString(value) {
  return typeof value === "string" ? value.trim() : "";
}

export function normalizeTdcDepartment(dept) {
  if (!dept || typeof dept !== "string") return "";
  const trimmed = dept.trim();
  if (trimmed === "技术中心") return trimmed;
  if (/^技术中心[_-]?/.test(trimmed)) return trimmed.replace(/^技术中心[_-]?/, "").trim();
  return trimmed;
}

export function capabilitiesOf(item) {
  return item && item.sourceInfo && typeof item.sourceInfo === "object"
    ? item.sourceInfo
    : { sourceType: "aras", reportType: "ewo", displayName: "ARAS EWO" };
}

export function defaultMappingFor(item, capabilities) {
  return capabilities && capabilities.defaultMapping && Object.keys(capabilities.defaultMapping).length > 0
    ? capabilities.defaultMapping
    : (DEFAULT_MAPPINGS[item && item.id] || {});
}

export function mappingText(value, sep = "｜") {
  if (value === null || value === undefined) return "";
  return Array.isArray(value) ? value.join(sep) : String(value);
}

export function ewoPolicyDiscoveryFields(discovery) {
  const observations = discovery && Array.isArray(discovery.observations) ? discovery.observations : [];
  const latest = observations[0] || {};
  const report = latest.fieldReport && typeof latest.fieldReport === "object" ? latest.fieldReport : {};
  return Array.isArray(report.fields) ? report.fields.map((v) => ewoPolicyString(v)).filter(Boolean) : [];
}

export function ewoPolicyDiscoveryStateLabel(value) {
  const labels = { matched: "已匹配", not_found: "未找到", ambiguous: "候选不唯一", key_changed: "稳定键发生变化" };
  return labels[value] || "待确认";
}

export function ewoPolicyPaginationDiagnosticText(diagnostic) {
  if (!diagnostic || typeof diagnostic !== "object") return "";
  const parts = [];
  const stop = ewoPolicyString(diagnostic.stopReason);
  if (stop) parts.push(`停止原因：${stop}`);
  [
    ["rowCount", "返回行数"], ["uniqueCount", "去重后行数"], ["duplicateCount", "重复行数"],
    ["declaredTotal", "声明总数"], ["declaredPages", "声明页数"], ["fetchedPages", "已抓页数"],
  ].forEach(([key, label]) => {
    const value = diagnostic[key];
    if (typeof value === "number" && Number.isFinite(value)) parts.push(`${label}：${value}`);
  });
  return parts.length ? `（${parts.join("，")}）` : "";
}

export function ewoPolicyErrorMessage(error) {
  if (error && error.fields && typeof error.fields === "object") {
    const fields = Object.entries(error.fields).map(([field, message]) => `${field}：${message}`).join("；");
    if (fields) return fields;
  }
  let msg = error instanceof Error ? error.message : String(error || "");
  if (msg.includes("映射发现证据与当前配置规则不一致")) {
    return "配置规则已更新，系统已自动重置证据；请点击“保存同步绑定”或重新抓取证据";
  }
  if (msg.includes("外部稳定键")) msg = msg.replace(/外部稳定键/g, "目标单号");
  const facts = error && error.diagnostic ? ewoPolicyPaginationDiagnosticText(error.diagnostic) : "";
  return facts ? `${msg}${facts}` : msg;
}

/**
 * F10 稳定性核验失败的具体原因（后端 mismatch：只含原因枚举与计数，无单号）。
 */
export function stabilityGateFailureMessage(result) {
  const mismatch = result && typeof result === "object" ? result.mismatch : null;
  if (mismatch && typeof mismatch === "object") {
    const expected = Number(mismatch.expected);
    const actual = Number(mismatch.actual);
    if (mismatch.reason === "total_mismatch" && Number.isFinite(expected) && Number.isFinite(actual)) {
      return `映射稳定性核验未通过：上游记录数在两次核验间变化（${expected}→${actual}），请稍后重试。`;
    }
    if (mismatch.reason === "sample_not_in_baseline") {
      return "映射稳定性核验未通过：第 1 页样本与首次取证基线不一致（上游数据可能已变化），请稍后重试。";
    }
    if (mismatch.reason === "fields_mismatch") {
      return "映射稳定性核验未通过：字段结构在两次核验间变化，请稍后重试。";
    }
    if (mismatch.reason === "legacy_baseline") {
      return "映射稳定性核验未通过：历史证据格式不兼容，请重新开始配置以重新取证。";
    }
  }
  return "映射稳定性未就绪（需连续两次一致的脱敏证据），请稍后重试。";
}

export function stabilityText(stability) {
  return stability && Number.isFinite(Number(stability.confirmed))
    ? `${Math.min(Math.max(Number(stability.confirmed), 0), 2)}/2`
    : "0/2";
}

// ---- wizard -----------------------------------------------------------------

export function wizardPrimaryMatchField(capabilities) {
  const matchFields = Array.isArray(capabilities.matchFields) ? capabilities.matchFields : [];
  const primary = matchFields[0];
  if (!Array.isArray(primary) || !primary[0]) return null;
  return { key: primary[0], label: primary[1] || primary[0], filterName: primary[2] || primary[0], placeholder: primary[3] || "" };
}

export function wizardEvidenceDefaults(capabilities) {
  if (capabilities.sourceType === "aras") return { base_url: EWO_POLICY_DEFAULT_ARAS_BASE_URL };
  if (capabilities.sourceType === "tdc") return { base_url: POLICY_WIZARD_TDC_DEFAULT_BASE_URL, auth_mode: "browser" };
  return {};
}

export function wizardQuotedHints(text) {
  const hints = [];
  const pattern = /「([^」]+)」/g;
  let match;
  while ((match = pattern.exec(String(text || ""))) !== null) hints.push(match[1]);
  return hints;
}

export function wizardNormalizeColumnKey(value) {
  return ewoPolicyString(value).trim().toLowerCase().replace(/[_-]/g, "");
}

export function wizardDeriveMappingFromFieldReport(capabilities, fieldReport) {
  const fields = fieldReport && Array.isArray(fieldReport.fields)
    ? fieldReport.fields.map((v) => ewoPolicyString(v)).filter(Boolean)
    : [];
  if (fields.length === 0) return null;
  const semantics = capabilities.fieldSemantics && typeof capabilities.fieldSemantics === "object" ? capabilities.fieldSemantics : {};
  const mapping = {};
  ["owner", "plannedDate", "note"].forEach((key) => {
    const hints = wizardQuotedHints(semantics[key]);
    if (hints.length === 0) return;
    if (key === "note") {
      const normalizedHints = hints.map(wizardNormalizeColumnKey);
      const noteMatches = fields.filter((name) => {
        const normalized = wizardNormalizeColumnKey(name);
        return normalized !== "" && normalizedHints.includes(normalized);
      });
      if (noteMatches.length) mapping[key] = noteMatches;
      return;
    }
    const matches = fields.filter((name) => hints.some((hint) => name.indexOf(hint) !== -1));
    if (matches.length === 1) mapping[key] = matches[0];
  });
  return Object.keys(mapping).length > 0 ? mapping : null;
}

export function wizardKind(capabilities) {
  const reportType = capabilities.reportType;
  return {
    isEwo: reportType === "ewo",
    isSor: reportType === "sor",
    isDataModel: reportType === "data_model",
    isPaa: reportType === "paa",
    isNcr: reportType === "ncr_progress" || reportType === "ncr_detail",
    isTdc: reportType === "sor" || reportType === "data_model" || capabilities.sourceType === "tdc",
  };
}

/** Initial wizard input values from the stored policy. */
export function wizardInitialValues(policy, capabilities, vaultConfigured) {
  const rule = policy && policy.matchRule && typeof policy.matchRule === "object" ? policy.matchRule : {};
  const kind = wizardKind(capabilities);
  const declaredDept = ewoPolicyString(capabilities && capabilities.defaultDepartment);
  const defaultDept = kind.isTdc ? "车体工程" : (declaredDept || "技术中心_车体工程");
  let credential = "";
  if (vaultConfigured) credential = "domain";
  return {
    credential,
    model: ewoPolicyString(rule.projectCode || rule.modelInfo || rule.carTypeProject || rule.projectModel || ""),
    department: ewoPolicyString(rule.rspDepartment || rule.department || defaultDept),
    // 数模存 matchRule.status；SOR 存 matchRule.approvalStatus（TDC SOR 状态筛选）。
    status: ewoPolicyString(kind.isSor ? rule.approvalStatus : rule.status),
    // NCR 无部门维度：科室为归集口径预设多选，随绑定保存为 matchRule.sectionScope。
    sections: Array.isArray(rule.sectionScope) ? rule.sectionScope.map((value) => String(value)) : [],
    interval: String((policy && policy.intervalMinutes) || 15),
    number: ewoPolicyString(rule.ewoNo || rule.processNo || rule.incident || rule.paaNo || rule.ncrNo || ""),
    // 数模流水单号（documentNo）与实例号并存二选一：回填只按各自键取值，
    // 不做跨键转换（存量 incident 绑定打开后不填流水单号框，反之亦然）。
    documentNo: ewoPolicyString(rule.documentNo || ""),
    defaultDept,
  };
}

/** Wizard pre-checks; returns an error message or "". */
export function wizardPrecheck(values, policy, capabilities, vaultConfigured) {
  const modelVal = ewoPolicyString(values.model);
  const specificNo = ewoPolicyString(values.number);
  if (policy.credentialAvailable !== true && !(values.credential === "domain" && vaultConfigured) && !vaultConfigured) {
    return "系统设置未检测到凭据保护库，请先登录并保存统一域账号。";
  }
  if (!specificNo && !modelVal && wizardPrimaryMatchField(capabilities)) return "请填写车型项目或车型信息（例如 F610S）。";
  const documentNo = ewoPolicyString(values.documentNo);
  if (documentNo && specificNo) {
    return "流水单号与实例号二选一：请只填写其中一项（流水单号为 3D- 前缀，实例号为纯数字）。";
  }
  return "";
}

/** Step 1 of the wizard: match rule, discovery filters and the discovery payload. */
export function buildWizardDiscovery(values, capabilities) {
  const kind = wizardKind(capabilities);
  const primary = wizardPrimaryMatchField(capabilities);
  const modelVal = ewoPolicyString(values.model);
  const rawDept = ewoPolicyString(values.department);
  const deptVal = kind.isTdc ? normalizeTdcDepartment(rawDept) : rawDept;
  const specificNo = ewoPolicyString(values.number);
  // 聚合 = 未指定单号；数模流水单号也是"指定单号"（绑定到命中行的 incident 作为
  // externalKey），只填流水单号时同样按单记录取证。
  const documentNoVal = ewoPolicyString(values.documentNo);
  const aggregate = !specificNo && !(kind.isDataModel && documentNoVal);
  const filters = {};
  const matchRule = { reportType: capabilities.reportType || (kind.isEwo ? "ewo" : ""), aggregate };
  const set = (ruleKey, filterKey, value) => {
    if (!value) return;
    matchRule[ruleKey] = value;
    filters[filterKey] = value;
  };
  if (kind.isEwo) {
    matchRule.contractVersion = "2";
    matchRule.bindingMode = aggregate ? "record_set" : "single_record";
    set("projectCode", "project_code", modelVal);
    set("rspDepartment", "rsp_department", deptVal);
    set("ewoNo", "ewo_no", specificNo);
  } else if (kind.isSor) {
    set("carTypeProject", "car_type_project", modelVal);
    set("department", "department", deptVal);
    // SOR 状态筛选：approvalStatus 存绑定，approval_status 进取证请求
    // （后端 _MAPPING_DISCOVERY_RULE_FIELDS 映射回 approvalStatus）。
    set("approvalStatus", "approval_status", ewoPolicyString(values.status));
    set("processNo", "serial_number", specificNo);
  } else if (kind.isDataModel) {
    set("projectModel", "project_model", modelVal);
    set("department", "department", deptVal);
    set("status", "status", ewoPolicyString(values.status));
    // 流水单号（documentNo）与实例号（incident）并存二选一（wizardPrecheck 拦截
    // 同填）：流水单号走后端全量抓取+本地精确匹配（它不是 TDC 查询参数），实例号
    // 仍是线上参数 incident。互不覆写，存量绑定回填不跨键转换。
    set("documentNo", "document_no", ewoPolicyString(values.documentNo));
    set("incident", "serial_number", specificNo);
  } else if (kind.isPaa) {
    set("projectModel", "project_model", modelVal);
    set("department", "department", deptVal);
    set("paaNo", "serial_number", specificNo);
  } else if (kind.isNcr) {
    set("projectModel", "project_model", modelVal);
    // NCR 无部门维度：绑定部门不是查询键，科室只作为归集口径的范围声明保存
    // （不发送 seccode——科室名→导出代码映射契约未确立）。
    const sectionScope = Array.isArray(values.sections) ? values.sections.map((value) => String(value)).filter(Boolean) : [];
    if (sectionScope.length) matchRule.sectionScope = sectionScope;
    set("ncrNo", "serial_number", specificNo);
  } else if (primary) {
    filters[primary.filterName] = specificNo || modelVal;
    matchRule[primary.key] = specificNo || modelVal;
  }
  const payload = { filters, selectedExternalKey: specificNo || null, aggregate, ...wizardEvidenceDefaults(capabilities) };
  // 流水单号绑定：document_no 已在 filters 里（发现端 _mapping_discovery_query_identity
  // 按 mapping 键收口为 matchRule.documentNo），selectedExternalKey 由后端映射发现
  // 回填为命中行的实例号（incident），不在请求里预置。
  if (kind.isEwo) {
    payload.contractVersion = "2";
    payload.bindingMode = aggregate ? "record_set" : "single_record";
  }
  return { kind, aggregate, deptVal, specificNo, filters, matchRule, payload };
}

/** Department-less retry payload for TDC (filters copied, department removed). */
export function wizardRetryWithoutDepartment(payload) {
  const filters = { ...payload.filters };
  delete filters.department;
  delete filters.rsp_department;
  return { ...payload, filters };
}

export function dropDepartment(plan) {
  delete plan.filters.department;
  delete plan.filters.rsp_department;
  delete plan.matchRule.department;
  delete plan.matchRule.rspDepartment;
}

export function wizardNotMatchedMessage(result) {
  const cCount = Number.isFinite(result.candidateCount) ? result.candidateCount : 0;
  const fCount = result.fieldReport && Array.isArray(result.fieldReport.fields) ? result.fieldReport.fields.length : 0;
  return `映射发现未匹配（${ewoPolicyDiscoveryStateLabel(result.state)}，命中行数：${cCount}，字段数：${fCount}），请核对车型与筛选条件后重试。`;
}

/** Step 3: field mapping + authority. Throws Error with the legacy wording. */
export function wizardMapping(plan, capabilities, result) {
  const { kind, aggregate } = plan;
  let mapping = {};
  const fieldAuthority = {};
  if (aggregate) {
    let candidateNotes;
    if (kind.isEwo) {
      candidateNotes = ["_change_description", "_subject"];
      fieldAuthority.plannedDate = "manual";
    } else if (kind.isSor) {
      candidateNotes = ["latestCompletedNode", "processInstanceStatus"];
    } else if (kind.isDataModel) {
      candidateNotes = ["latestApproveLog", "status"];
    } else if (capabilities.defaultMapping && capabilities.defaultMapping.note) {
      candidateNotes = Array.isArray(capabilities.defaultMapping.note) ? capabilities.defaultMapping.note : [capabilities.defaultMapping.note];
    } else {
      candidateNotes = ["status"];
    }
    const reported = Array.isArray(result && result.fieldReport && result.fieldReport.fields) ? result.fieldReport.fields : [];
    let matchedNotes = candidateNotes.filter((f) => reported.includes(f));
    if (matchedNotes.length === 0 && result && result.fieldReport) {
      const statusOrApproval = Array.isArray(result.fieldReport.statusOrApprovalFields) ? result.fieldReport.statusOrApprovalFields : [];
      const cols = statusOrApproval
        .map((entry) => (typeof entry === "string" ? entry : entry && entry.field))
        .filter((col) => col && reported.includes(col));
      if (cols.length > 0) matchedNotes = cols;
    }
    if (matchedNotes.length === 0) {
      throw new Error("无法从最新脱敏字段报告确定有效的备注映射字段，请打开高级设置手工确认映射后保存。");
    }
    mapping = { note: matchedNotes };
    fieldAuthority.note = "automatic";
    fieldAuthority.owner = "manual";
  } else {
    mapping = wizardDeriveMappingFromFieldReport(capabilities, result.fieldReport);
    if (!mapping && capabilities && capabilities.defaultMapping && Object.keys(capabilities.defaultMapping).length > 0) {
      mapping = { ...capabilities.defaultMapping };
    }
    if (!mapping) throw new Error("无法从最新脱敏字段报告确定自动字段映射，请打开高级设置手工完成映射后保存。");
    Object.keys(mapping).forEach((key) => { fieldAuthority[key] = "automatic"; });
  }
  return { mapping, fieldAuthority };
}

/** Step 4: the update-policy PATCH the wizard sends. */
export function wizardPolicyPatch(plan, values, result, mappingResult, vaultConfigured) {
  const patch = {
    mode: "automatic",
    enabled: true,
    externalKey: plan.aggregate ? null : (ewoPolicyString(result && result.externalKey) || plan.payload.selectedExternalKey || null),
    matchRule: plan.matchRule,
    mapping: mappingResult.mapping,
    fieldAuthority: mappingResult.fieldAuthority,
    intervalMinutes: parseInt(values.interval, 10) || 15,
  };
  if (plan.kind.isEwo) patch.bindingContractVersion = "2";
  if (values.credential === "domain" || vaultConfigured) patch.credentialRef = "domain";
  return patch;
}

// ---- advanced binding editor ----------------------------------------------

/** Initial editor form values from the stored policy. */
export function bindingInitialValues(item, policy, capabilities) {
  const current = policy && typeof policy === "object" ? policy : {};
  const matchFields = Array.isArray(capabilities.matchFields) ? capabilities.matchFields : EWO_POLICY_MATCH_FIELDS;
  const evidenceFields = Array.isArray(capabilities.evidenceFields)
    ? capabilities.evidenceFields
    : [{ name: "base_url", label: "ECM 地址（仅用于抓取映射证据）", type: "url" }];
  const rule = current.matchRule && typeof current.matchRule === "object" ? current.matchRule : {};
  const defaultMap = defaultMappingFor(item, capabilities);
  const modes = Object.keys(EWO_POLICY_MODE_LABELS);
  const match = {};
  matchFields.forEach((def) => {
    const key = Array.isArray(def) ? def[0] : def;
    match[key] = ewoPolicyString(rule[key]);
  });
  const evidence = {};
  evidenceFields.forEach((def) => {
    let value = "";
    if (def.type === "select") value = def.options && def.options.length ? def.options[0] : "";
    else if (def.type !== "textarea" && def.name === "base_url" && capabilities.sourceType === "aras") value = EWO_POLICY_DEFAULT_ARAS_BASE_URL;
    evidence[def.name] = value;
  });
  const authority = {};
  const mapping = {};
  EWO_POLICY_AUTOMATIC_FIELDS.forEach(([key]) => {
    const existing = current.mapping && current.mapping[key];
    const initial = existing !== null && existing !== undefined
      ? (Array.isArray(existing) ? existing.join("｜") : ewoPolicyString(existing))
      : mappingText(defaultMap[key]);
    mapping[key] = initial;
    authority[key] = current.fieldAuthority ? current.fieldAuthority[key] === "automatic" : Boolean(initial);
  });
  const supportsRecordSet = capabilities.supportsRecordSet === true;
  const values = {
    mode: modes.includes(current.mode) ? current.mode : "manual",
    enabled: current.enabled === true,
    credential: "",
    externalKey: ewoPolicyString(current.externalKey),
    bindingMode: supportsRecordSet ? (rule.contractVersion === "2" ? rule.bindingMode : "legacy") : null,
    interval: String(current.intervalMinutes || 15),
    match,
    evidence,
    authority,
    mapping,
  };
  return supportsRecordSet ? applyBindingMode(values, rule, defaultMap, false) : values;
}

/** Legacy refreshEwoBindingMode: record_set forces manual owner/plannedDate and automatic note. */
export function applyBindingMode(values, storedRule, defaultMap, migrating) {
  if (!values.bindingMode) return values;
  const next = { ...values, authority: { ...values.authority }, mapping: { ...values.mapping } };
  if (next.bindingMode === "record_set") {
    next.authority.owner = false;
    next.authority.plannedDate = false;
    next.authority.note = true;
    if (!String(next.mapping.note || "").trim() && defaultMap.note) next.mapping.note = mappingText(defaultMap.note, " | ");
  }
  if (migrating) next.enabled = false;
  return next;
}

export function bindingModeView(values, storedRule) {
  const mode = values.bindingMode;
  if (!mode) return { externalKeyHidden: false, externalKeyLabel: "关联目标单号", externalKeyPlaceholder: "选填，输入需跟踪的目标单号（留空自动关联）", lockOwnerPlanned: false };
  const setMode = mode === "record_set";
  return {
    externalKeyHidden: setMode || (mode === "legacy" && storedRule.aggregate === true),
    externalKeyLabel: mode === "single_record" ? "固定版本记录 ID" : "关联目标单号",
    externalKeyPlaceholder: mode === "single_record" ? "32位内部记录ID；不自动跟随修订" : "选填，输入需跟踪的目标单号（留空自动关联）",
    lockOwnerPlanned: setMode,
  };
}

/** Legacy buildPolicyPayload. */
export function buildPolicyPayload(item, capabilities, storedPolicy, values) {
  const storedRule = (storedPolicy && storedPolicy.matchRule) || {};
  const defaultMap = defaultMappingFor(item, capabilities);
  const payload = {
    mode: values.mode || "manual",
    enabled: Boolean(values.enabled),
    externalKey: ewoPolicyString(values.externalKey) || null,
    matchRule: { reportType: capabilities.reportType || "ewo" },
    mapping: {},
    fieldAuthority: {},
  };
  payload.matchRule.aggregate = capabilities.aggregate === true;
  if (values.bindingMode === "legacy" && typeof storedRule.aggregate === "boolean") payload.matchRule.aggregate = storedRule.aggregate;
  if (values.bindingMode && values.bindingMode !== "legacy") {
    EWO_RULE_KEYS.forEach((key) => {
      if (typeof storedRule[key] === "string" && storedRule[key].trim()) payload.matchRule[key] = storedRule[key];
    });
    payload.bindingContractVersion = "2";
    payload.matchRule.contractVersion = "2";
    payload.matchRule.bindingMode = values.bindingMode;
    payload.matchRule.aggregate = values.bindingMode === "record_set";
    if (payload.matchRule.aggregate) payload.externalKey = null;
    else {
      payload.externalKey = (payload.externalKey || "").toUpperCase();
      payload.matchRule.sourceItemId = payload.externalKey;
    }
  }
  const isTdcMatch = capabilities.reportType === "sor" || capabilities.reportType === "data_model" || capabilities.sourceType === "tdc";
  Object.entries(values.match || {}).forEach(([key, raw]) => {
    let value = ewoPolicyString(raw);
    if (value && isTdcMatch && (key === "department" || key === "superDepartment")) value = normalizeTdcDepartment(value);
    if (value) payload.matchRule[key] = value;
    else delete payload.matchRule[key];
  });
  // NCR 科室范围声明由向导维护；高级设置保存时原样保留，避免静默丢失。
  if (capabilities.sectionScopePresets && Array.isArray(storedRule.sectionScope) && storedRule.sectionScope.length) {
    payload.matchRule.sectionScope = storedRule.sectionScope.map((value) => String(value));
  }
  if (!payload.externalKey && !payload.matchRule.aggregate && payload.matchRule.ewoNo) payload.externalKey = payload.matchRule.ewoNo;
  EWO_POLICY_AUTOMATIC_FIELDS.forEach(([key]) => {
    const automatic = Boolean(values.authority && values.authority[key]);
    payload.fieldAuthority[key] = automatic ? "automatic" : "manual";
    if (!automatic) return;
    let sourceField = ewoPolicyString(values.mapping && values.mapping[key]);
    if (!sourceField && defaultMap[key]) sourceField = mappingText(defaultMap[key]);
    if (!sourceField) return;
    if (key === "note" && (sourceField.includes("｜") || sourceField.includes("|") || sourceField.includes(","))) {
      payload.mapping[key] = sourceField.split(/[｜|,]/).map((s) => s.trim()).filter(Boolean);
    } else if (key === "note" && Array.isArray(defaultMap[key])
      && [defaultMap[key].join("｜"), defaultMap[key].join(" | "), defaultMap[key].join("|")].includes(sourceField)) {
      payload.mapping[key] = defaultMap[key];
    } else {
      payload.mapping[key] = sourceField;
    }
  });
  if (values.credential === "domain") payload.credentialRef = "domain";
  if (values.credential === "__clear__") payload.credentialRef = null;
  payload.intervalMinutes = parseInt(values.interval, 10) || 15;
  return payload;
}

/** Legacy refreshLocalReadiness -> {text, ready}. */
export function bindingReadiness(payload, ctx) {
  const { storedPolicy = {}, vaultConfigured = false, lastEvidenceExternalKey = "", discoveredFields = [], defaultMap = {}, stability } = ctx;
  const discovered = new Set(discoveredFields);
  const missing = [];
  if (!EWO_POLICY_MODE_LABELS[payload.mode] || !["automatic", "hybrid"].includes(payload.mode)) missing.push("请选择自动同步或混合模式");
  const credentialReady = storedPolicy.credentialAvailable === true || (payload.credentialRef === "domain" && vaultConfigured);
  if (!credentialReady) missing.push(vaultConfigured ? "尚未绑定统一域账号凭据" : "凭据保护库未配置");
  const aggregateMode = payload.matchRule.aggregate === true;
  if (!aggregateMode && !payload.externalKey) missing.push("目标单号未确认（可填写EWO单号或抓取证据自动识别）");
  if (payload.enabled && !aggregateMode && !lastEvidenceExternalKey) missing.push("请先抓取映射证据（连续两次一致）");
  if (payload.enabled && !aggregateMode && lastEvidenceExternalKey && payload.externalKey !== lastEvidenceExternalKey) {
    missing.push("外部稳定键与最近一次映射证据不一致，请点击“抓取映射证据”重新验证");
  }
  const matchKeys = Object.keys(payload.matchRule).filter((key) => !["reportType", "aggregate", "contractVersion", "bindingMode", "sourceItemId"].includes(key));
  if (matchKeys.length === 0) missing.push("至少填写一个匹配条件");
  const automaticFields = Object.keys(payload.fieldAuthority).filter((key) => payload.fieldAuthority[key] === "automatic");
  if (automaticFields.length === 0) missing.push("至少选择一个自动字段");
  if (automaticFields.some((key) => !payload.mapping[key])) missing.push("自动字段必须填写来源映射");
  const flat = [];
  Object.values(payload.mapping).forEach((v) => { if (Array.isArray(v)) flat.push(...v); else if (v) flat.push(v); });
  const defaults = [];
  Object.values(defaultMap).forEach((v) => { if (Array.isArray(v)) defaults.push(...v); else if (v) defaults.push(v); });
  if (flat.length > 0 && discovered.size > 0 && flat.some((f) => !discovered.has(f) && !defaults.includes(f))) {
    missing.push("来源映射必须来自最近的脱敏字段报告");
  }
  const confirmed = stability && Number(stability.confirmed);
  if (!Number.isFinite(confirmed) || confirmed < 2) {
    missing.push(`映射稳定性未就绪（${Number.isFinite(confirmed) ? `${Math.max(confirmed, 0)}/2` : "0/2"}）`);
  }
  if (payload.enabled && missing.length === 0) return { ready: true, text: "已满足启用条件：保存后同步按钮将可用，后端仍会执行最终校验。" };
  if (!payload.enabled && missing.length === 0) return { ready: false, text: "绑定配置已齐全：勾选“启用自动同步”并保存后才会启用同步。" };
  return { ready: false, text: `尚缺：${missing.join("，")}` };
}

/** Legacy discoverMappingEvidence payload; returns null when no filter/key is set. */
export function buildEvidencePayload(capabilities, values, payload) {
  const matchFields = Array.isArray(capabilities.matchFields) ? capabilities.matchFields : EWO_POLICY_MATCH_FIELDS;
  const filters = {};
  matchFields.forEach((def) => {
    const [key, , filterName] = Array.isArray(def) ? def : [def, def, def];
    const value = ewoPolicyString(values.match && values.match[key]);
    if ((filterName || key) && value) filters[filterName || key] = value;
  });
  if (Object.keys(filters).length === 0 && payload.externalKey) {
    const first = Array.isArray(matchFields[0]) ? matchFields[0] : null;
    if (first && first[2]) filters[first[2]] = payload.externalKey;
  }
  if (Object.keys(filters).length === 0 && !payload.externalKey) return null;
  const evidence = { filters, selectedExternalKey: payload.externalKey || null, aggregate: payload.matchRule.aggregate === true };
  if (payload.bindingContractVersion === "2") {
    evidence.contractVersion = "2";
    evidence.bindingMode = payload.matchRule.bindingMode;
    if (payload.matchRule.sourceItemId) evidence.sourceItemId = payload.matchRule.sourceItemId;
    Object.entries(EWO_FILTER_NAMES).forEach(([key, name]) => {
      if (payload.matchRule[key]) evidence.filters[name] = payload.matchRule[key];
    });
  }
  Object.entries(values.evidence || {}).forEach(([name, raw]) => {
    if (name === "headers") {
      const parsed = parseHeaders(raw || "");
      if (Object.keys(parsed).length > 0) evidence.headers = parsed;
      return;
    }
    const value = ewoPolicyString(raw);
    if (value) evidence[name] = value;
  });
  return evidence;
}

// ---- interactive ARAS query -------------------------------------------------

export const INTERACTIVE_MODES = {
  ewo: {
    endpoint: "/api/aras/ewo/query",
    filterNames: ["ewo_no", "project_code", "subject_keyword", "change_type", "change_sub_type", "area", "state", "rsp_department", "submit_start", "submit_end"],
    preferredColumns: ["_no", "_eplmwriteneplcode", "_subject", "_area", "_sort_type", "_rsp_department", "_submit_time", "state"],
    label: "EWO",
  },
  paa: {
    endpoint: "/api/aras/paa/query",
    filterNames: ["paa_no", "ewo_no", "state", "area", "base", "department", "vehicle_keyword", "submit_start", "submit_end", "mtl_rq_start", "mtl_rq_end"],
    preferredColumns: [],
    label: "PAA",
  },
};

export const INTERACTIVE_QUERY_ERROR_LABELS = {
  unauthenticated: { label: "未认证", detail: "请先在设置中完成统一域账号登录。", tone: "warning" },
  service_unavailable: { label: "服务不可用", detail: "ARAS 当前不可用，请检查网络或 VPN 后重试。", tone: "error" },
  query_failed: { label: "查询失败", detail: "ARAS 查询未完成，请稍后重试。", tone: "error" },
};

export function interactiveFilterValue(value) {
  if (typeof value !== "string" && typeof value !== "number") return "";
  const text = String(value).trim();
  return text ? text.slice(0, 1000) : "";
}

export function interactiveQueryErrorCode(error, fallbackStatus) {
  const explicit = error && typeof (error.code || error.errorCode) === "string" ? (error.code || error.errorCode) : "";
  if (INTERACTIVE_QUERY_ERROR_LABELS[explicit]) return explicit;
  const status = Number(error && error.status !== undefined ? error.status : fallbackStatus);
  if (status === 401 || status === 403) return "unauthenticated";
  if (status === 0 || !Number.isFinite(status) || status >= 500) return "service_unavailable";
  return "query_failed";
}

export function formatInteractiveArasError(error, fallbackStatus = 0) {
  const descriptor = INTERACTIVE_QUERY_ERROR_LABELS[interactiveQueryErrorCode(error, fallbackStatus)] || INTERACTIVE_QUERY_ERROR_LABELS.query_failed;
  return `${descriptor.label}：${descriptor.detail}`;
}

export function buildInteractiveArasPayload(mode, filters = {}) {
  const config = INTERACTIVE_MODES[mode];
  if (!config) throw new Error("unsupported interactive ARAS mode");
  const allowed = new Set(config.filterNames);
  const safeFilters = {};
  if (filters && typeof filters === "object" && !Array.isArray(filters)) {
    Object.entries(filters).forEach(([name, value]) => {
      if (!allowed.has(name)) return;
      const clean = interactiveFilterValue(value);
      if (clean) safeFilters[name] = clean;
    });
  }
  return { base_url: EWO_POLICY_DEFAULT_ARAS_BASE_URL, auth_mode: "browser", filters: safeFilters, page: 1, page_size: 50, max_records: 2000 };
}

export function buildEwoInteractiveQuerySpec(policy = {}, item = {}) {
  const matchRule = policy && policy.matchRule && typeof policy.matchRule === "object" ? policy.matchRule : {};
  const filters = {};
  Object.entries(EWO_FILTER_NAMES).forEach(([policyKey, filterKey]) => {
    const value = interactiveFilterValue(matchRule[policyKey]);
    if (value) filters[filterKey] = value;
  });
  if (!Object.keys(filters).length) {
    const externalKey = interactiveFilterValue(policy && policy.externalKey);
    if (/^EWO[-_]/i.test(externalKey)) filters.ewo_no = externalKey;
  }
  return { filters, targetKey: filters.ewo_no || "", fallbackLabel: String((item && item.name) || "") };
}

export function buildPaaInteractiveFilters(filters = {}) {
  const source = filters && typeof filters === "object" && !Array.isArray(filters) ? filters : {};
  const fieldMap = {
    paaNo: "paa_no", ewoNo: "ewo_no", state: "state", area: "area", base: "base", department: "department",
    vehicleKeyword: "vehicle_keyword", submitStart: "submit_start", submitEnd: "submit_end",
    materialRequestStart: "mtl_rq_start", materialRequestEnd: "mtl_rq_end",
  };
  const result = {};
  Object.entries(fieldMap).forEach(([sourceKey, filterKey]) => {
    const value = interactiveFilterValue(source[sourceKey] ?? source[filterKey]);
    if (value) result[filterKey] = value;
  });
  return result;
}

function interactiveRowIdentityValues(mode, data, row) {
  const identityFields = mode === "ewo"
    ? ["_no", "ewoNo", "ewo_no", "id", "formId"]
    : ["_no", "paaNo", "paa_no", "ewoNo", "ewo_no", "id", "formId"];
  if (Array.isArray(row)) {
    const columns = data && Array.isArray(data.columns) ? data.columns : [];
    const values = [];
    columns.forEach((column, fallbackIndex) => {
      const sourceFields = column && Array.isArray(column.sourceFields) ? column.sourceFields : [];
      if (!sourceFields.some((field) => identityFields.includes(field))) return;
      values.push(row[Number.isInteger(column.index) ? column.index : fallbackIndex]);
    });
    if (!values.length && row.length) values.push(row[0]);
    return values;
  }
  if (row && typeof row === "object") return identityFields.map((field) => row[field]);
  return [];
}

export function interactiveQueryResultState(mode, data, targetKey = "") {
  const rows = data && Array.isArray(data.rows) ? data.rows : [];
  if (!rows.length || (data && data.queryState === "empty")) return "empty";
  const target = interactiveFilterValue(targetKey);
  if (!target) return "matched";
  const found = rows.some((row) => interactiveRowIdentityValues(mode, data, row).some((v) => interactiveFilterValue(v) === target));
  return found ? "matched" : "no_match";
}

export function formatInteractiveArasResult(data, expectedExternalKey = "", mode = "") {
  const state = interactiveQueryResultState(mode, data, expectedExternalKey);
  const descriptors = {
    matched: { text: "已匹配", tone: "success" },
    empty: { text: "数据为空", tone: "warning" },
    no_match: { text: "未匹配", tone: "warning" },
  };
  return { state, ...(descriptors[state] || descriptors.empty) };
}

// ---- manual edit ------------------------------------------------------------

export const OVERVIEW_STATUS_OPTIONS = ["已完成", "进行中", "待审批", "已逾期"];

export function draftValuesFromItem(item) {
  return {
    status: item.status || "",
    owner: item.owner || "",
    plannedDate: item.plannedDate || "",
    actualDate: item.actualDate || "",
    progress: item.progress === null || item.progress === undefined ? "" : String(item.progress),
    note: item.note || "",
  };
}

export function draftDirty(saved, values) {
  return ["status", "owner", "plannedDate", "actualDate", "progress", "note"].some((key) => saved[key] !== values[key]);
}

export function validateDeliverableDraft(values) {
  const errors = {};
  const status = String(values.status || "").trim();
  const owner = String(values.owner || "").trim();
  const plannedDate = String(values.plannedDate || "").trim();
  const actualDate = String(values.actualDate || "").trim();
  const progressRaw = String(values.progress || "").trim();
  const datePattern = /^\d{4}-\d{2}-\d{2}$/;
  if (!status) errors.status = "请选择状态";
  if (!owner) errors.owner = "负责人为必填项";
  if (!plannedDate) errors.plannedDate = "计划完成日期为必填项";
  else if (!datePattern.test(plannedDate)) errors.plannedDate = "日期格式应为 YYYY-MM-DD";
  if (progressRaw === "") errors.progress = "当前进度为必填项";
  else {
    const progress = Number(progressRaw);
    if (!Number.isInteger(progress) || progress < 0 || progress > 100) errors.progress = "当前进度必须是 0 到 100 的整数";
  }
  if (status === "已完成") {
    const progress = Number(progressRaw);
    if (progressRaw !== "" && Number.isInteger(progress) && progress !== 100) errors.progress = "已完成交付物的进度必须为 100";
    if (!actualDate) errors.actualDate = "已完成交付物必须填写实际完成日期";
    else if (!datePattern.test(actualDate)) errors.actualDate = "日期格式应为 YYYY-MM-DD";
  } else if (actualDate) {
    errors.actualDate = "未完成的交付物不应填写实际完成日期";
  }
  return errors;
}

export function buildDeliverablePatch(values, item) {
  return {
    status: values.status.trim(),
    owner: values.owner.trim(),
    plannedDate: values.plannedDate,
    actualDate: values.actualDate,
    progress: Number(values.progress),
    note: values.note.trim(),
    updatedAt: item.updatedAt || "",
  };
}

export function buildNotePatch(item, note) {
  return {
    status: item.status,
    owner: item.owner,
    plannedDate: item.plannedDate,
    actualDate: item.actualDate,
    progress: item.progress,
    note,
    updatedAt: item.updatedAt || "",
  };
}

export const SERVER_FIELD_MAP = {
  status: "status", owner: "owner", plannedDate: "plannedDate", actualDate: "actualDate", progress: "progress",
  note: "note", planned_date: "plannedDate", actual_date: "actualDate",
};

export function serverFieldErrors(fields) {
  const result = {};
  Object.keys(fields || {}).forEach((key) => {
    const name = SERVER_FIELD_MAP[key];
    if (name) result[name] = String(fields[key]);
  });
  return result;
}

/** Map a legacy association href onto the plugin routes. */
export function associationHref(entry) {
  const href = String((entry && entry.href) || "");
  if (!href.startsWith("#")) return "";
  if (entry.type === "archive_job" && entry.jobKey) {
    return `#p/project-overview/archive-deliverable?job=${encodeURIComponent(String(entry.jobKey))}`;
  }
  const archive = /^#archive-deliverable\/([^/?#]+)/.exec(href);
  if (archive) return `#p/project-overview/archive-deliverable?job=${archive[1]}`;
  return href;
}
