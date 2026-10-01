// Update-method panel (legacy loadDeliverablePolicy / buildSyncSummaryCard /
// renderSyncBindingEditor / loadDeliverableUpdateHistory): data-sync summary
// card with the one-click wizard and "立即同步", plus the advanced binding
// editor (mode, credential ref, binding contract, interval, match rule,
// evidence connection, field authority + mapping, mapping discovery,
// readiness, save, update history).
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc } from "./api.js";
import { deliverableSyncDisplay, syncResultText } from "./display.js";
import { redactSensitiveText, safeDisplayValue } from "./format.js";
import {
  EWO_POLICY_AUTOMATIC_FIELDS,
  EWO_POLICY_MATCH_FIELDS,
  EWO_POLICY_MODE_LABELS,
  EWO_POLICY_RECOMMENDED_MODE,
  INTERVAL_OPTIONS,
  POLICY_SYNC_HINTS,
  applyBindingMode,
  bindingInitialValues,
  bindingModeView,
  bindingReadiness,
  buildEvidencePayload,
  buildPolicyPayload,
  buildWizardDiscovery,
  capabilitiesOf,
  defaultMappingFor,
  dropDepartment,
  ewoPolicyDiscoveryFields,
  ewoPolicyDiscoveryStateLabel,
  ewoPolicyErrorMessage,
  ewoPolicyString,
  mappingText,
  stabilityText,
  wizardInitialValues,
  wizardKind,
  wizardMapping,
  wizardNotMatchedMessage,
  wizardPolicyPatch,
  wizardPrecheck,
  wizardPrimaryMatchField,
  wizardRetryWithoutDepartment,
} from "./policy-logic.js";

const policyPath = (id) => `/api/project-status/deliverables/${enc(id)}/update-policy`;
const discoveryPath = (id) => `/api/project-status/deliverables/${enc(id)}/mapping-discovery`;

function IntervalSelect({ value, onChange, name }) {
  return html`<select name=${name} value=${value} onChange=${(e) => onChange(e.currentTarget.value)}>
    ${INTERVAL_OPTIONS.map(([val, label]) => html`<option key=${val} value=${val}>${label}</option>`)}
  </select>`;
}

// ---- summary card + wizard ------------------------------------------------------

function SyncSummaryCard({ item, policy, capabilities, settings, advancedOpen, onToggleAdvanced, onSyncNow, onReloadOverview, status, setStatus }) {
  const current = policy && typeof policy === "object" ? policy : {};
  const vaultConfigured = Boolean(settings) && settings.credentialVaultConfigured === true;
  const syncDisplay = deliverableSyncDisplay(item);
  const rule = current.matchRule && typeof current.matchRule === "object" ? current.matchRule : {};
  const kind = wizardKind(capabilities);
  const primary = wizardPrimaryMatchField(capabilities);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [values, setValues] = useState(() => wizardInitialValues(current, capabilities, vaultConfigured));
  const [running, setRunning] = useState(false);
  const [candidates, setCandidates] = useState(null);
  const candidateResolver = useRef(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const set = (key) => (event) => {
    const value = event.currentTarget.value;
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const say = (text, error = false) => setStatus({ text, error });

  const facts = [
    ["最近尝试", safeDisplayValue(current.lastAttemptAt || "无")],
    ["最近成功", safeDisplayValue(current.lastSuccessAt || "无")],
  ];
  if (current.enabled === true) {
    const model = rule.projectCode || rule.modelInfo || rule.carTypeProject || rule.projectModel;
    const dept = rule.rspDepartment || rule.department;
    if (model) facts.push(["车型项目", safeDisplayValue(model)]);
    if (dept) facts.push(["责任部门", safeDisplayValue(dept)]);
    if (rule.status) facts.push(["状态", safeDisplayValue(rule.status)]);
    facts.push(["同步周期", `每 ${current.intervalMinutes || 15} 分钟`]);
  }
  facts.push(["最近错误", current.lastErrorMessage ? redactSensitiveText(String(current.lastErrorMessage)) : "无"]);

  const pickCandidate = (list) => new Promise((resolve, reject) => {
    const keys = (list || []).map((c) => ewoPolicyString(c && c.externalKey)).filter(Boolean);
    if (!keys.length) {
      reject(new Error("候选记录缺少外部稳定键，请使用高级设置完成绑定。"));
      return;
    }
    candidateResolver.current = resolve;
    setCandidates({ keys, selected: keys[0] });
  });

  const start = async () => {
    const precheck = wizardPrecheck(values, current, capabilities, vaultConfigured);
    if (precheck) {
      say(precheck, true);
      return;
    }
    setRunning(true);
    try {
      const plan = buildWizardDiscovery(values, capabilities);
      say("正在抓取映射证据（第 1/2 次）...");
      let result = (await apiRequest(discoveryPath(item.id), { method: "POST", body: plan.payload })) || {};
      if (result.state === "ambiguous" && !plan.aggregate) {
        say("候选不唯一，请选择一次目标记录。");
        const selected = await pickCandidate(result.candidates);
        setCandidates(null);
        plan.payload.selectedExternalKey = selected;
        result = (await apiRequest(discoveryPath(item.id), { method: "POST", body: plan.payload })) || {};
      }
      if (result.state !== "matched" && plan.kind.isTdc && plan.deptVal) {
        say("指定部门未匹配，正在尝试不限部门自动重试...");
        const retry = (await apiRequest(discoveryPath(item.id), { method: "POST", body: wizardRetryWithoutDepartment(plan.payload) })) || {};
        if (retry && (retry.state === "matched" || (retry.state === "ambiguous" && !plan.aggregate))) {
          result = retry;
          dropDepartment(plan);
        }
      }
      if (result.state !== "matched") throw new Error(wizardNotMatchedMessage(result));
      let confirmed = Number(result.stability && result.stability.confirmed);
      if (!Number.isFinite(confirmed) || confirmed < 2) {
        say("正在验证映射稳定性（第 2/2 次）...");
        result = (await apiRequest(discoveryPath(item.id), { method: "POST", body: plan.payload })) || {};
        confirmed = Number(result.stability && result.stability.confirmed);
        if (result.state !== "matched" || !Number.isFinite(confirmed) || confirmed < 2) {
          throw new Error("映射稳定性未就绪（需连续两次一致的脱敏证据），请稍后重试。");
        }
      }
      const mappingResult = wizardMapping(plan, capabilities, result);
      say("正在保存配置并启用自动同步...");
      await apiRequest(policyPath(item.id), { method: "PATCH", body: wizardPolicyPatch(plan, values, result, mappingResult, vaultConfigured) });
      say("配置已启用，正在触发首次同步...");
      const syncData = await apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" });
      say(`配置并启用成功！${syncResultText(syncData)}`);
      setRunning(false);
      await onReloadOverview();
    } catch (err) {
      setCandidates(null);
      say(`配置启用失败：${redactSensitiveText(ewoPolicyErrorMessage(err))}`, true);
      setRunning(false);
    }
  };

  const syncNow = async () => {
    setSyncBusy(true);
    say("正在同步...");
    try {
      const data = await onSyncNow();
      say(syncResultText(data));
      await onReloadOverview();
    } catch (err) {
      say(`同步失败：${redactSensitiveText(ewoPolicyErrorMessage(err))}`, true);
    } finally {
      setSyncBusy(false);
    }
  };

  const declaredHint = POLICY_SYNC_HINTS[syncDisplay.state];
  const numberText = kind.isEwo ? "EWO 编号（选填，留空则整车聚合）"
    : kind.isPaa ? "PAA 编号（选填，留空则整车聚合）"
      : kind.isNcr ? "NCR 编号（选填，留空则整车聚合）"
        : (primary ? `${primary.label}（选填）` : "外部编号（选填）");

  return html`<section class="policy-sync-summary" aria-label=${`${item.name} 数据同步`}>
    <div class="policy-sync-summary-head">
      <strong class="policy-sync-summary-title">数据同步</strong>
      <span class="policy-sync-summary-state">${syncDisplay.label}</span>
    </div>
    ${declaredHint && html`<p class="policy-sync-summary-hint">${declaredHint}</p>`}
    ${capabilities && capabilities.completenessPolicy === "workbook_admission" && html`<p class="policy-sync-summary-hint">来源为官方工作簿导出：仅当表头契约成立且逐行归类核对无剩余时才写入快照；该类来源没有声明总数，因此不构成源端零丢失的证明。</p>`}
    <ul class="policy-sync-summary-facts">
      ${facts.map(([label, value]) => html`<li class="policy-sync-summary-fact" key=${label}>
        <span class="policy-sync-fact-label">${label}</span><span class="policy-sync-fact-value">${value}</span>
      </li>`)}
    </ul>
    <div class="policy-sync-summary-actions">
      ${current.enabled === true && html`<button type="button" class="policy-sync-now-btn" disabled=${syncBusy} onClick=${syncNow}>立即同步</button>`}
      ${capabilities.syncCapable === true && current.enabled === true && html`<button type="button" class="policy-sync-reconfig-btn" onClick=${() => setWizardOpen(!wizardOpen)}>修改同步配置</button>`}
      ${capabilities.syncCapable === true && current.enabled !== true && html`<button type="button" class="policy-sync-enable-btn" onClick=${() => setWizardOpen(!wizardOpen)}>开启自动同步</button>`}
      <button type="button" class="policy-sync-advanced-btn" aria-expanded=${advancedOpen ? "true" : "false"} onClick=${onToggleAdvanced}>高级设置</button>
    </div>
    <p class=${`policy-sync-wizard-status${status.error ? " is-error" : ""}`} role="status" aria-live="polite">${status.text}</p>
    <div class="policy-sync-wizard" hidden=${!wizardOpen}>
      ${candidates
        ? html`<div class="policy-wizard-candidates">
          <p class="policy-field-note">候选记录不唯一，请选择一次目标记录：</p>
          <select value=${candidates.selected} onChange=${(e) => { const v = e.currentTarget.value; setCandidates((prev) => ({ ...prev, selected: v })); }}>
            ${candidates.keys.map((key) => html`<option key=${key} value=${key}>${key}</option>`)}
          </select>
          <button type="button" class="policy-wizard-candidate-btn" onClick=${() => {
            if (candidateResolver.current) candidateResolver.current(ewoPolicyString(candidates.selected));
            candidateResolver.current = null;
          }}>确认所选候选</button>
        </div>`
        : html`
          <label class="policy-ewo-field policy-wizard-field">
            <span>同步凭据引用</span>
            <select value=${values.credential} onChange=${set("credential")}>
              <option value="">${current.credentialAvailable === true ? "保持当前已绑定凭据（不修改）" : "暂不绑定"}</option>
              <option value="domain">统一域账号（domain）</option>
            </select>
            <small class="policy-field-note">${current.credentialAvailable === true || vaultConfigured
              ? "使用已保存的统一域账号自动登录内网抓取数据。"
              : "请先到系统设置登录并勾选“保存至凭据保护库”。"}</small>
          </label>
          <label class="policy-ewo-field policy-wizard-field">
            <span>车型项目 / 车型信息</span>
            <input type="text" maxlength="200" placeholder="例如 F610S 或 N300（整车项目聚合）" value=${values.model} onInput=${set("model")} />
          </label>
          <label class="policy-ewo-field policy-wizard-field">
            <span>责任部门</span>
            <input type="text" maxlength="200" value=${values.department} onInput=${set("department")}
              placeholder=${kind.isTdc ? "TDC 部门（如 车体工程，支持留空）" : `默认：${values.defaultDept}`} />
            <small class="policy-field-note">${kind.isTdc
              ? "TDC 部门（如“车体工程”），支持留空查询全量数据。请勿填写 Aras 形式“技术中心_车体工程”。"
              : `默认筛选“${values.defaultDept}”，支持按需修改。`}</small>
          </label>
          ${kind.isDataModel && html`<label class="policy-ewo-field policy-wizard-field">
            <span>状态（选填）</span>
            <input type="text" maxlength="200" placeholder="选填，如：审批中、已完成，留空查询全部" value=${values.status} onInput=${set("status")} />
          </label>`}
          <label class="policy-ewo-field policy-wizard-field">
            <span>定时自动同步周期</span>
            <${IntervalSelect} value=${values.interval} onChange=${(v) => setValues((prev) => ({ ...prev, interval: v }))} />
          </label>
          <label class="policy-ewo-field policy-wizard-field">
            <span>${numberText}</span>
            <input type="text" maxlength="200" placeholder="选填，留空将对整车项目全部单据进行聚合统计" value=${values.number} onInput=${set("number")} />
          </label>
          <button type="button" class="policy-wizard-start-btn" disabled=${running} onClick=${start}>${current.enabled === true ? "保存配置并同步" : "开始配置并启用"}</button>`}
    </div>
  </section>`;
}

// ---- advanced binding editor ----------------------------------------------------

function UpdateHistory({ itemId, trigger }) {
  const [state, setState] = useState(null);
  useEffect(() => {
    if (!trigger) return;
    let alive = true;
    setState({ loading: true });
    apiRequest(`/api/project-status/updates?deliverableId=${enc(itemId)}`)
      .then((data) => {
        if (!alive) return;
        setState({ updates: data && Array.isArray(data.updates) ? data.updates.slice(0, 5) : [] });
      })
      .catch((err) => { if (alive) setState({ error: err instanceof Error ? err.message : String(err) }); });
    return () => { alive = false; };
  }, [trigger]);
  if (!state) return html`<div class="policy-history"></div>`;
  if (state.loading) return html`<div class="policy-history">正在读取更新记录...</div>`;
  if (state.error) return html`<div class="policy-history is-error">${state.error}</div>`;
  if (!state.updates.length) return html`<div class="policy-history"><p class="policy-history-empty">暂无更新记录</p></div>`;
  return html`<div class="policy-history"><ol class="policy-history-list">
    ${state.updates.map((entry, index) => html`<li key=${index}>${`${safeDisplayValue(entry.createdAt)} · ${entry.triggerType === "manual" ? "手动更新" : "自动同步"} · ${entry.result === "applied" ? "已应用" : safeDisplayValue(entry.result)}`}</li>`)}
  </ol></div>`;
}

function BindingEditor({ item, policy, capabilities, settings, discovery: initialDiscovery, onEvidenceRefresh, onSaved, savedMessage }) {
  const current = policy && typeof policy === "object" ? policy : {};
  const storedRule = current.matchRule || {};
  const vaultConfigured = Boolean(settings) && settings.credentialVaultConfigured === true;
  const matchFields = Array.isArray(capabilities.matchFields) ? capabilities.matchFields : EWO_POLICY_MATCH_FIELDS;
  const evidenceFields = Array.isArray(capabilities.evidenceFields)
    ? capabilities.evidenceFields
    : [{ name: "base_url", label: "ECM 地址（仅用于抓取映射证据）", type: "url" }];
  const defaultMap = defaultMappingFor(item, capabilities);
  const itemToken = String(item.id || "ewo").replace(/[^A-Za-z0-9_-]/g, "-");
  const [values, setValues] = useState(() => bindingInitialValues(item, current, capabilities));
  const [discovery, setDiscovery] = useState(() => (initialDiscovery && typeof initialDiscovery === "object" ? initialDiscovery : {}));
  const [discoveredFields, setDiscoveredFields] = useState(() => ewoPolicyDiscoveryFields(initialDiscovery || {}));
  const [lastEvidenceKey, setLastEvidenceKey] = useState(() => {
    const obs = initialDiscovery && Array.isArray(initialDiscovery.observations) && initialDiscovery.observations.length ? initialDiscovery.observations[0] : null;
    return ewoPolicyString(obs && obs.externalKey);
  });
  const [discoveryStatus, setDiscoveryStatus] = useState({
    text: `连续稳定证据：${stabilityText(initialDiscovery && initialDiscovery.stability)}（需点击两次并保持目标一致）`,
    tone: "",
  });
  const [discovering, setDiscovering] = useState(false);
  const [status, setStatus] = useState(() => (savedMessage ? { text: savedMessage, error: false } : { text: "", error: false }));
  useEffect(() => {
    if (savedMessage) setStatus({ text: savedMessage, error: false });
  }, [savedMessage]);
  const [saving, setSaving] = useState(false);
  const [historyTrigger, setHistoryTrigger] = useState(0);

  const update = (patch) => setValues((prev) => ({ ...prev, ...patch }));
  const setMatch = (key, value) => setValues((prev) => {
    const next = { ...prev, match: { ...prev.match, [key]: value } };
    if ((key === "ewoNo" || key === "sourceItemId") && !String(prev.externalKey || "").trim()) next.externalKey = value.trim();
    return next;
  });
  const payload = buildPolicyPayload(item, capabilities, current, values);
  const readiness = bindingReadiness(payload, {
    storedPolicy: current,
    vaultConfigured,
    lastEvidenceExternalKey: lastEvidenceKey,
    discoveredFields,
    defaultMap,
    stability: discovery.stability,
  });
  const modeView = bindingModeView(values, storedRule);

  const discover = async () => {
    const evidencePayload = buildEvidencePayload(capabilities, values, payload);
    if (!evidencePayload) {
      setDiscoveryStatus({ text: "请先填写外部稳定键或至少一个匹配条件。", tone: "error" });
      return;
    }
    setDiscovering(true);
    setDiscoveryStatus({ text: "正在抓取脱敏映射证据...", tone: "busy" });
    try {
      const result = (await apiRequest(discoveryPath(item.id), { method: "POST", body: evidencePayload })) || {};
      setDiscovery((prev) => ({
        ...prev,
        stability: result.stability || prev.stability,
        observations: [
          { state: result.state, externalKey: result.externalKey, candidateCount: result.candidateCount, fieldReport: result.fieldReport || {} },
          ...(Array.isArray(prev.observations) ? prev.observations : []),
        ],
      }));
      const discoveredKey = ewoPolicyString(result.externalKey);
      const fields = result.fieldReport && Array.isArray(result.fieldReport.fields) ? result.fieldReport.fields : [];
      setDiscoveredFields(fields.map((v) => ewoPolicyString(v)).filter(Boolean));
      setValues((prev) => (!String(prev.externalKey || "").trim() && discoveredKey ? { ...prev, externalKey: discoveredKey } : prev));
      if (discoveredKey) setLastEvidenceKey(discoveredKey);
      setDiscoveryStatus({
        text: `本次${ewoPolicyDiscoveryStateLabel(result.state)}：候选 ${Number(result.candidateCount) || 0} 条；连续稳定证据 ${stabilityText(result.stability)}。`,
        tone: result.state === "matched" ? "success" : "warning",
      });
      if (onEvidenceRefresh) onEvidenceRefresh();
    } catch (err) {
      setDiscoveryStatus({ text: `抓取失败：${redactSensitiveText(ewoPolicyErrorMessage(err))}`, tone: "error" });
    } finally {
      setDiscovering(false);
    }
  };

  const save = async (event) => {
    event.preventDefault();
    if (payload.enabled && !vaultConfigured && current.credentialAvailable !== true) {
      setStatus({ text: "系统设置未检测到凭据保护库，请先登录并保存统一域账号。", error: true });
      return;
    }
    setSaving(true);
    setStatus({ text: "正在保存...", error: false });
    try {
      await apiRequest(policyPath(item.id), { method: "PATCH", body: payload });
      const failure = await onSaved();
      if (failure) {
        setStatus({ text: failure, error: false });
        setSaving(false);
      }
    } catch (err) {
      setStatus({ text: redactSensitiveText(ewoPolicyErrorMessage(err)), error: true });
      setSaving(false);
    }
  };

  const supportsRecordSet = capabilities.supportsRecordSet === true;
  const reportType = capabilities.reportType || "ewo";
  const lockOwnerPlanned = modeView.lockOwnerPlanned;
  const credentialNote = current.credentialAvailable === true
    ? "本交付物已有凭据引用；此处不显示用户名或密码。"
    : (vaultConfigured
      ? "全局凭据库已配置，但尚未绑定到本交付物；请选择统一域账号。"
      : "请先到系统设置登录并勾选“保存至凭据保护库”，再在此选择统一域账号。");
  const listId = `policy-discovered-fields-${itemToken}`;

  return html`
    <div class="policy-editor-head">
      <strong class="policy-editor-title">更新方式</strong>
      <span class="policy-source">数据来源 · ${capabilities.displayName || item.source || "外部来源"}</span>
    </div>
    <form class="policy-editor-form" onSubmit=${save}>
      <fieldset class="policy-mode-group">
        <legend>更新模式</legend>
        <div class="policy-segmented">
          ${Object.entries(EWO_POLICY_MODE_LABELS).map(([value, label]) => html`
            <input type="radio" key=${`i${value}`} name=${`policy-mode-${item.id}`} id=${`policy-mode-${item.id}-${value}`} value=${value}
              checked=${values.mode === value} onChange=${() => update({ mode: value })} />
            <label key=${`l${value}`} for=${`policy-mode-${item.id}-${value}`}>${label}${value === EWO_POLICY_RECOMMENDED_MODE && html`<span class="policy-ewo-mode-badge">推荐：自动同步</span>`}</label>`)}
        </div>
      </fieldset>
      <fieldset class="policy-ewo-binding">
        <legend>绑定同步配置</legend>
        <div class="policy-ewo-binding-grid">
          <label class="policy-ewo-field">
            <span>同步凭据引用</span>
            <select id=${`policy-credential-ref-${itemToken}`} name="credentialRef" value=${values.credential}
              onChange=${(e) => update({ credential: e.currentTarget.value })}>
              <option value="">${current.credentialAvailable === true ? "保持当前已绑定凭据（不修改）" : "暂不绑定（选择统一域账号）"}</option>
              <option value="domain">统一域账号（domain）</option>
            </select>
            <small class="policy-field-note">${credentialNote}</small>
          </label>
          <label class="policy-ewo-field" hidden=${modeView.externalKeyHidden}>
            <span>${modeView.externalKeyLabel}</span>
            <input type="text" name="externalKey" id=${`policy-external-key-${itemToken}`} maxlength="200"
              placeholder=${modeView.externalKeyPlaceholder} value=${values.externalKey}
              onInput=${(e) => update({ externalKey: e.currentTarget.value })} />
            <small class="policy-field-note">需跟踪的外部单号；如留空，将在保存或抓取时根据匹配条件自动关联。</small>
          </label>
          ${supportsRecordSet && html`<label class="policy-ewo-field">
            <span>EWO绑定合同</span>
            <select name="ewoBindingMode" value=${values.bindingMode}
              onChange=${(e) => {
                const bindingMode = e.currentTarget.value;
                setValues((prev) => applyBindingMode({ ...prev, bindingMode }, storedRule, defaultMap, true));
              }}>
              ${storedRule.contractVersion !== "2" && html`<option value="legacy">保留旧版规则</option>`}
              <option value="record_set">新版：记录集合</option>
              <option value="single_record">新版：固定单条记录</option>
            </select>
            <small class="policy-field-note">旧版保持原有单条/多条写入规则。迁移到新版须先停用保存，再重新取证；集合负责人和计划日期始终手工。</small>
          </label>`}
          <label class="policy-ewo-field">
            <span>定时同步周期</span>
            <${IntervalSelect} name="intervalMinutes" value=${values.interval} onChange=${(v) => update({ interval: v })} />
            <small class="policy-field-note">设置常驻后台调度器自动同步该交付物状态的执行频率。</small>
          </label>
          <fieldset class="policy-ewo-match">
            <legend>匹配规则（报表类型固定为 ${reportType}）</legend>
            <span class="policy-ewo-fixed-value">reportType = ${reportType}</span>
            ${matchFields.map((def) => {
              const [key, label, filterName, placeholder] = Array.isArray(def) ? def : [def, def, def, "可选"];
              return html`<label class="policy-ewo-field" key=${key}>
                <span>${label}</span>
                <input type="text" data-match-key=${key} data-filter-name=${filterName || key} placeholder=${placeholder || "可选"}
                  value=${values.match[key] || ""} onInput=${(e) => setMatch(key, e.currentTarget.value)} />
              </label>`;
            })}
            <small class="policy-field-note">至少填写一个筛选条件；保存启用时后端会再次校验来源契约。</small>
          </fieldset>
          <fieldset class="policy-ewo-evidence-source">
            <legend>映射证据来源连接</legend>
            ${evidenceFields.map((def) => {
              const value = values.evidence[def.name] || "";
              const onInput = (e) => { const v = e.currentTarget.value; setValues((prev) => ({ ...prev, evidence: { ...prev.evidence, [def.name]: v } })); };
              let control;
              if (def.type === "select") {
                control = html`<select data-evidence-field=${def.name} value=${value} onChange=${onInput}>
                  ${(def.options || []).map((option) => html`<option key=${option} value=${option}>${option}</option>`)}
                </select>`;
              } else if (def.type === "textarea") {
                control = html`<textarea rows="2" data-evidence-field=${def.name} placeholder=${def.placeholder || null} value=${value} onInput=${onInput}></textarea>`;
              } else {
                control = html`<input type=${def.type || "text"} data-evidence-field=${def.name} placeholder=${def.placeholder || null} value=${value} onInput=${onInput} />`;
              }
              return html`<label class="policy-ewo-field" key=${def.name}><span>${def.label || def.name}</span>${control}</label>`;
            })}
          </fieldset>
        </div>
        <fieldset class="policy-ewo-authority">
          <legend>自动字段与来源映射</legend>
          ${EWO_POLICY_AUTOMATIC_FIELDS.map(([key, label]) => {
            const locked = lockOwnerPlanned && (key === "owner" || key === "plannedDate");
            const checked = Boolean(values.authority[key]);
            const placeholderVal = Array.isArray(defaultMap[key]) ? defaultMap[key].join("｜") : (defaultMap[key] || "_owner");
            return html`<div class="policy-ewo-mapping-row" key=${key}>
              <label class="policy-field-check">
                <input type="checkbox" name=${`fieldAuthority-${key}`} data-authority-field=${key} checked=${checked} disabled=${locked}
                  onChange=${(e) => {
                    const on = e.currentTarget.checked;
                    setValues((prev) => {
                      const next = { ...prev, authority: { ...prev.authority, [key]: on }, mapping: { ...prev.mapping } };
                      if (on && !next.mapping[key] && defaultMap[key]) next.mapping[key] = mappingText(defaultMap[key]);
                      return next;
                    });
                  }} />
                <span>${label}自动更新</span>
              </label>
              <label class="policy-ewo-field policy-ewo-mapping-field">
                <span>${label}来源字段</span>
                <input type="text" name=${`mapping-${key}`} data-mapping-field=${key} list=${listId}
                  placeholder=${`推荐：${placeholderVal}`} value=${values.mapping[key] || ""} disabled=${locked || !checked}
                  onInput=${(e) => { const v = e.currentTarget.value; setValues((prev) => ({ ...prev, mapping: { ...prev.mapping, [key]: v } })); }} />
              </label>
            </div>`;
          })}
          <datalist id=${listId}>${discoveredFields.map((name) => html`<option key=${name} value=${name}>${name}</option>`)}</datalist>
        </fieldset>
      </fieldset>
      <div class="policy-ewo-discovery">
        <button type="button" class="policy-discovery-btn" disabled=${discovering} onClick=${discover}>抓取映射证据</button>
        <span class=${`policy-discovery-status${discoveryStatus.tone ? ` is-${discoveryStatus.tone}` : ""}`} role="status" aria-live="polite">${discoveryStatus.text}</span>
        <small class="policy-field-note">每次点击只抓取并保存脱敏字段报告，不会自动修改映射或业务数据。</small>
        <label class="policy-ewo-enable">
          <input type="checkbox" name="enabled" id=${`policy-enabled-${itemToken}`} checked=${values.enabled}
            onChange=${(e) => update({ enabled: e.currentTarget.checked })} />
          <span>启用自动同步</span>
        </label>
      </div>
      <p class=${`policy-ewo-readiness ${readiness.ready ? "is-ready" : "is-disabled"}`} role="status">${readiness.text}</p>
      <p class="policy-ewo-note">已认证会话和全局凭据库不会自动绑定到本交付物；本表单只保存凭据别名和同步策略，不保存密码。</p>
      <div class="policy-editor-actions">
        <button type="submit" class="policy-save-btn" disabled=${saving}>保存同步绑定</button>
        <button type="button" class="policy-history-btn" onClick=${() => setHistoryTrigger((v) => v + 1)}>更新记录</button>
      </div>
      <p class=${`policy-request-status${status.error ? " is-error" : ""}`} role="status">${status.text}</p>
      <${UpdateHistory} itemId=${item.id} trigger=${historyTrigger} />
    </form>`;
}

/**
 * Policy panel. Reloads policy + settings + discovery when `version` changes.
 * `onPolicyLoaded(policy)` feeds the EWO interactive query.
 */
export function PolicyPanel({ item, version, onPolicyLoaded, onEvidenceRefresh, onReloadOverview }) {
  const capabilities = item.sourceInfo && typeof item.sourceInfo === "object" ? item.sourceInfo : null;
  const [state, setState] = useState({ loading: true, policy: null, settings: null, discovery: null, error: "", seq: 0 });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [wizardStatus, setWizardStatus] = useState({ text: "", error: false });
  const [notice, setNotice] = useState(null);
  const seq = useRef(0);

  useEffect(() => {
    if (!capabilities || !capabilities.syncCapable) return undefined;
    let alive = true;
    const current = ++seq.current;
    setState((prev) => ({ ...prev, loading: true }));
    (async () => {
      const id = enc(item.id);
      try {
        const [policy, settings, discovery] = await Promise.all([
          apiRequest(policyPath(item.id)),
          apiRequest("/api/settings").catch(() => null),
          apiRequest(`/api/project-status/deliverables/${id}/mapping-discovery`).catch(() => null),
        ]);
        if (!alive || current !== seq.current) return;
        if (onPolicyLoaded) onPolicyLoaded(policy || {});
        setState({ loading: false, policy: policy || {}, settings, discovery, error: "", seq: current });
      } catch (err) {
        if (!alive || current !== seq.current) return;
        // 无绑定或读取失败时按未启用展示，并保留脱敏后的错误信息。
        setState({ loading: false, policy: null, settings: null, discovery: null, error: redactSensitiveText(ewoPolicyErrorMessage(err)), seq: current });
      }
    })();
    return () => { alive = false; };
  }, [item.id, version]);

  if (!capabilities || !capabilities.syncCapable) {
    return html`<strong class="policy-editor-title">更新方式</strong>
      <p class="policy-static-mode">${capabilities && capabilities.syncNote ? capabilities.syncNote : "手动维护"}</p>`;
  }
  if (state.loading && !state.seq) return html`<p class="policy-loading">正在读取更新策略...</p>`;

  const effectiveCaps = capabilitiesOf(item);
  // 保存成功后概览刷新会触发策略重新读取并重建编辑器；提示在新编辑器上显示。
  const savedMessage = notice && state.seq >= notice.seq ? notice.text : null;
  const onSaved = async () => {
    const target = seq.current + 1;
    const ok = await onReloadOverview();
    if (ok === false) return "已保存，但概览数据刷新失败，请刷新页面查看最新状态";
    setNotice({ text: "更新方式已保存", seq: target });
    return "";
  };

  return html`
    <${SyncSummaryCard}
      key=${`summary-${state.seq}`}
      item=${item}
      policy=${state.policy}
      capabilities=${effectiveCaps}
      settings=${state.settings}
      advancedOpen=${advancedOpen}
      onToggleAdvanced=${() => setAdvancedOpen(!advancedOpen)}
      onSyncNow=${() => apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" })}
      onReloadOverview=${onReloadOverview}
      status=${wizardStatus}
      setStatus=${setWizardStatus}
    />
    <details class="policy-advanced-settings" open=${advancedOpen} ontoggle=${(e) => setAdvancedOpen(e.currentTarget.open)}>
      <summary class="policy-advanced-summary">
        <span class="policy-advanced-title">高级设置</span>
        <span class="policy-advanced-summary-hint">完整绑定表单：更新模式、匹配规则、映射证据与字段映射</span>
      </summary>
      <${BindingEditor}
        key=${`editor-${state.seq}`}
        item=${item}
        policy=${state.policy}
        capabilities=${effectiveCaps}
        settings=${state.settings}
        discovery=${state.discovery}
        onEvidenceRefresh=${onEvidenceRefresh}
        onSaved=${onSaved}
        savedMessage=${savedMessage}
      />
    </details>
    ${state.error && html`<p class="policy-request-status is-error">${state.error}</p>`}`;
}
