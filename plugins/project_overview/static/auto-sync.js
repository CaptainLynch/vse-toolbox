// #p/project-overview/auto-sync —「一键开启自动同步」（需求 D2/D3）。
// 按项目的车型和科室推导每个交付物的筛选条件，然后对每个还没开启的交付物依次跑一遍
// 交付物详情里同一个「开始配置并启用」流程（取证两次 → 保存 → 首次同步）。
// 不新增后端接口、不绕开任何校验：哪一项没核对上，就停在那一项并说清原因。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import {
  failRunningFirstSync,
  markFirstSyncNotApplicable,
  markFirstSyncRunning,
  readFirstSyncRequest,
  recoverInterruptedFirstSync,
  readOnboardingSelection,
  recordFirstSyncEntry,
  requestFirstSync,
  summarizeFirstSync,
} from "/static/host/onboarding-selection.js";
import { PROJECT_PHASE_ID } from "./shared/client.js";
import { apiRequest, enc } from "./deliverable/api.js";
import { runEnableFlow } from "./deliverable/enable-flow.js";
import { redactSensitiveText } from "./deliverable/format.js";
import { capabilitiesOf, ewoPolicyErrorMessage, wizardInitialValues, wizardKind, wizardPrecheck } from "./deliverable/policy-logic.js";

const DEFAULT_DEPARTMENTS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"];
const BACK_HASH = "#p/workbench/project";

/** 一键开启时每个交付物的向导输入：车型来自项目；数模 / NCR 用项目的科室。 */
export function autoSyncValues(policy, capabilities, vaultConfigured, { vehicle, departments }) {
  const values = wizardInitialValues(policy, capabilities, vaultConfigured);
  const kind = wizardKind(capabilities);
  values.model = vehicle;
  // 只做「按车型汇总」：不带任何单号，所以不会出现「候选不唯一要人选」的情况。
  values.number = "";
  values.documentNo = "";
  values.documentNos = "";
  if ((kind.isDataModel || kind.isNcr) && departments.length) values.sections = [...departments];
  return values;
}

/**
 * 向导选择的启用范围。null = 没有向导选择（沿用全部交付物）；
 * 空数组 = 用户明确一个都没勾选（本次不启用任何交付物）。
 */
export function autoSyncScope(selection) {
  if (!selection || !Array.isArray(selection.deliverables)) return null;
  return new Set(selection.deliverables.map((id) => String(id)));
}

/** 可以一键开启的交付物：在向导选择范围内、有连接器、且还没开启。 */
export function autoSyncTargets(deliverables, policies, selection) {
  const allowed = autoSyncScope(selection);
  return (deliverables || []).filter((d) => {
    if (allowed && !allowed.has(String(d.id))) return false;
    const caps = d.sourceInfo || {};
    if (!caps.syncCapable) return false;
    const policy = policies[d.id];
    return !(policy && policy.enabled === true);
  });
}

/**
 * 首次同步结果 → 逐项状态。只认真实任务回报：
 * 没有结果（未开始）、失败、需要处理都不算完成。
 */
export function firstSyncOutcome(data) {
  const envelope = data && typeof data === "object" ? data : {};
  const payload = envelope.data && typeof envelope.data === "object" ? envelope.data : envelope;
  const result = payload.result && typeof payload.result === "object" ? payload.result : {};
  const finalState = String(result.finalState || payload.finalState || "");
  const outcome = String(result.outcome || payload.outcome || finalState);
  if (finalState === "success" && outcome === "completed") return { state: "success", text: "首次同步成功" };
  if (finalState === "partial" || outcome === "partial") return { state: "partial", text: "首次同步部分成功" };
  if (finalState === "busy" || outcome === "busy") return { state: "running", text: "首次同步进行中" };
  const message = redactSensitiveText(result.errorMessage || payload.errorMessage || "");
  return { state: "failed", text: message ? `首次同步失败：${message}` : "首次同步失败" };
}

/** 逐项状态 → 行样式（成功 / 进行中 / 失败或部分成功）。 */
export function firstSyncTone(state) {
  if (state === "success") return "ok";
  if (state === "running") return "info";
  return "bad";
}

/**
 * 科室回写计划：只有用户显式勾选「同时把这些科室设为项目默认科室」且本次至少
 * 成功开启一项时才写回；返回 null 表示不发任何请求（默认行为）。
 * 带 expectedRevision 走 backend 现有的修订检查，失败由调用方如实展示。
 */
export function departmentWriteBackPlan({ writeBack, enabled, project, departments }) {
  if (!writeBack || !enabled) return null;
  const cleaned = [];
  (Array.isArray(departments) ? departments : []).forEach((item) => {
    const text = String(item === undefined || item === null ? "" : item).trim();
    if (text && !cleaned.includes(text)) cleaned.push(text);
  });
  if (!cleaned.length) return null;
  if (!project || !project.id) return { projectId: "", body: null, error: "没有找到当前项目" };
  const body = { departments: cleaned };
  if (Number.isInteger(project.revision)) body.expectedRevision = project.revision;
  return { projectId: String(project.id), body, error: "" };
}

/** 回写失败的统一说法：页面结果区原样显示，不降级成 console.warn。 */
export function departmentWriteBackFailure(reason) {
  const text = redactSensitiveText(reason === undefined || reason === null ? "" : reason).trim();
  return `科室没有写回项目默认值：${text || "未知原因"}`;
}

function rowState(item, policies, progress, selection, request) {
  if (progress[item.id]) return progress[item.id];
  // 刷新页面后仍按宿主模块里记录的真实结果展示，失败不会被「已开启」盖掉。
  const entry = request && Array.isArray(request.entries)
    ? request.entries.find((candidate) => candidate.id === item.id)
    : null;
  if (entry && entry.state === "success") return { tone: "ok", text: entry.text || "首次同步成功" };
  if (entry && entry.state === "partial") return { tone: "bad", text: entry.text || "首次同步部分成功" };
  if (entry && entry.state === "failed") return { tone: "bad", text: entry.text || "首次同步失败" };
  if (entry && entry.state === "running") return { tone: "info", text: entry.text || "首次同步进行中" };
  if (entry && entry.state === "not_applicable") return { tone: "off", text: entry.text || "不参与自动同步" };
  const caps = item.sourceInfo || {};
  if (!caps.syncCapable) return { tone: "off", text: caps.syncNote || "只能手工维护" };
  const policy = policies[item.id];
  if (policy && policy.enabled === true) return { tone: "ok", text: "已开启 ✓" };
  const allowed = autoSyncScope(selection);
  if (allowed && !allowed.has(String(item.id))) return { tone: "off", text: "不在向导选择范围" };
  if (allowed) return { tone: "off", text: "未开始（等待首次同步）" };
  return { tone: "off", text: "未开启" };
}

export default function AutoSyncPage({ plugin }) {
  useStylesheet(`/plugins/${(plugin && plugin.id) || "project-overview"}/static/auto-sync.css`);
  const [load, setLoad] = useState({ loading: true, error: "", status: null, settings: null, policies: {}, project: null });
  const [vehicle, setVehicle] = useState("");
  const [departments, setDepartments] = useState(DEFAULT_DEPARTMENTS);
  // 向导交接：勾选的交付物与首次同步请求（宿主模块负责存取，不跨插件 import）。
  const [handoff, setHandoff] = useState(() => ({
    selection: readOnboardingSelection(),
    // 首次同步只在本页面内执行：重新打开时遗留的「进行中」恢复为未开始。
    request: recoverInterruptedFirstSync(),
  }));
  const [progress, setProgress] = useState({});
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState(null);
  // 科室回写必须显式勾选（默认不勾）：不勾选时一键开启不会改动项目默认科室。
  const [writeBack, setWriteBack] = useState(false);
  const [writeBackResult, setWriteBackResult] = useState(null);

  const reload = async () => {
    try {
      const [status, settings, projects] = await Promise.all([
        apiRequest(`/api/project-status?phase=${enc(PROJECT_PHASE_ID)}`),
        apiRequest("/api/settings").catch(() => null),
        apiRequest("/api/p/workbench/projects").catch(() => null),
      ]);
      const deliverables = (status && status.deliverables) || [];
      const entries = await Promise.all(deliverables
        .filter((d) => d.sourceInfo && d.sourceInfo.syncCapable)
        .map(async (d) => [d.id, await apiRequest(`/api/project-status/deliverables/${enc(d.id)}/update-policy`).catch(() => null)]));
      const project = projects && Array.isArray(projects.projects) ? projects.projects.find((p) => p.active) : null;
      setLoad({ loading: false, error: "", status, settings, policies: Object.fromEntries(entries), project });
      return { status, project };
    } catch (err) {
      setLoad((prev) => ({ ...prev, loading: false, error: redactSensitiveText(ewoPolicyErrorMessage(err)) }));
      return null;
    }
  };

  useEffect(() => {
    const preferred = handoff.selection || {};
    reload().then((loaded) => {
      if (!loaded) return;
      const phaseName = loaded.status && loaded.status.phase ? loaded.status.phase.displayName : "";
      setVehicle(preferred.vehicle || (loaded.project && loaded.project.vehicle) || phaseName || "");
      const projectDepartments = loaded.project && loaded.project.departments;
      const wanted = preferred.departments && preferred.departments.length ? preferred.departments : projectDepartments;
      if (wanted && wanted.length) setDepartments(wanted);
    });
  }, []);

  if (load.loading) return html`<div class="vk-page"><p class="vk-muted">正在读取交付物…</p></div>`;
  if (load.error && !load.status) {
    return html`<div class="vk-page"><div class="vk-state is-error" role="alert"><span>读取失败：${load.error}</span>
      <button type="button" class="vk-btn" onClick=${reload}>重试</button></div></div>`;
  }

  const deliverables = ((load.status && load.status.deliverables) || []).filter((d) => !d.retired);
  const vaultConfigured = Boolean(load.settings) && load.settings.credentialVaultConfigured === true;
  // 有首次同步请求时以请求里的交付物为准，保证逐项结果与请求一一对应。
  const scope = handoff.request ? { deliverables: handoff.request.deliverables } : handoff.selection;
  const counts = summarizeFirstSync(handoff.request ? handoff.request.entries : []);
  const targets = autoSyncTargets(deliverables, load.policies, scope);
  const scopeEmpty = Boolean(scope && scope.deliverables && scope.deliverables.length === 0);
  const buttonLabel = running
    ? "正在开启…"
    : targets.length
      ? `全部开启（${targets.length} 项）`
      : scopeEmpty
        ? "没有可同步的交付物"
        : (handoff.request && !counts.allDone ? "已开启（首次同步未全部成功）" : "已全部开启");
  const toggle = (dept) => setDepartments(departments.includes(dept) ? departments.filter((d) => d !== dept) : [...departments, dept]);
  const mark = (id, next) => setProgress((prev) => ({ ...prev, [id]: next }));

  const start = async () => {
    const model = vehicle.trim();
    if (!model) { setSummary({ error: true, text: "请先填写车型，例如 F610S" }); return; }
    if (!vaultConfigured) { setSummary({ error: true, text: "还没有保存公司账号的密码：点右上角「登录 / 切换」，登录时勾选“保存至凭据保护库”，然后再回来。" }); return; }
    // 只有真实点击开始才登记/推进首次同步请求；仅打开页面不会改任何结果。
    if (scope && scope.deliverables && scope.deliverables.length) {
      if (!handoff.request) {
        requestFirstSync({
          deliverables: scope.deliverables,
          vehicle: model,
          departments,
          projectId: (load.project && load.project.id) || "",
        });
      }
      // 选中但不参与自动同步的项（只能手工维护、早已开启）标为不适用，不让它们永远「未开始」。
      const targetIds = new Set(targets.map((item) => String(item.id)));
      const byId = new Map(deliverables.map((d) => [String(d.id), d]));
      const notApplicable = scope.deliverables
        .filter((id) => !targetIds.has(String(id)))
        .map((id) => {
          const d = byId.get(String(id));
          const caps = (d && d.sourceInfo) || {};
          const reason = !d ? "不在当前项目的交付物中" : !caps.syncCapable ? (caps.syncNote || "只能手工维护，不参与自动同步") : "已开启自动同步";
          return { id, name: (d && d.name) || "", text: reason };
        });
      const updated = markFirstSyncNotApplicable(notApplicable);
      setHandoff((prev) => ({ ...prev, request: updated || readFirstSyncRequest() }));
    }
    if (!targets.length) { setSummary({ error: false, text: "没有需要首次同步的交付物。" }); return; }
    setRunning(true);
    setSummary(null);
    setWriteBackResult(null);
    window.__vseWizardBusy = true;
    if (scope && scope.deliverables && scope.deliverables.length) {
      markFirstSyncRunning(targets.map((item) => item.id));
    }
    let enabled = 0;
    const failed = [];
    const blocked = [];
    try {
      // 主计划名称就是交付物的车型锚点：先对齐，自动同步才会按这个车型统计。
      const phase = load.status.phase || {};
      if (phase.displayName !== model) {
        await apiRequest(`/api/project-status/phases/${enc(PROJECT_PHASE_ID)}`, {
          method: "PATCH",
          body: { displayName: model, status: phase.status, startDate: phase.startDate, endDate: phase.endDate, updatedAt: phase.updatedAt },
        });
      }
      for (const item of targets) {
        const capabilities = capabilitiesOf(item);
        const policy = load.policies[item.id] || {};
        const values = autoSyncValues(policy, capabilities, vaultConfigured, { vehicle: model, departments });
        const precheck = wizardPrecheck(values, policy, capabilities, vaultConfigured);
        if (precheck) {
          mark(item.id, { tone: "bad", text: precheck });
          recordFirstSyncEntry({ id: item.id, name: item.name, state: "failed", text: precheck });
          blocked.push(item.name);
          continue;
        }
        mark(item.id, { tone: "info", text: "正在核对…" });
        try {
          // 真实任务：启用流程内部调用现有 sync-now 接口，返回值就是首次同步结果。
          const syncData = await runEnableFlow({ item, capabilities, values, vaultConfigured, say: (text) => mark(item.id, { tone: "info", text }) });
          const outcome = firstSyncOutcome(syncData);
          mark(item.id, { tone: firstSyncTone(outcome.state), text: outcome.text });
          recordFirstSyncEntry({ id: item.id, name: item.name, state: outcome.state, text: outcome.text });
          enabled += 1;
          if (outcome.state !== "success") failed.push(item.name);
        } catch (err) {
          const text = redactSensitiveText(ewoPolicyErrorMessage(err));
          mark(item.id, { tone: "bad", text });
          recordFirstSyncEntry({ id: item.id, name: item.name, state: "failed", text });
          blocked.push(item.name);
        }
      }
      // 科室回写：只有用户显式勾选、且本次至少成功开启一项时才写回项目默认科室。
      // 失败（含 409 修订冲突）在结果区如实显示，不 console.warn、不吞掉，也不影响
      // 已开启项的结果展示；回写只改项目默认科室字段，不碰任何已验证的同步绑定。
      const plan = departmentWriteBackPlan({ writeBack, enabled, project: load.project, departments });
      if (plan) {
        if (plan.error) {
          setWriteBackResult({ error: true, text: departmentWriteBackFailure(plan.error) });
        } else {
          try {
            await apiRequest(`/api/p/workbench/projects/${enc(plan.projectId)}`, {
              method: "PATCH",
              body: plan.body,
            });
            setWriteBackResult({ error: false, text: `科室已写回项目默认值：${plan.body.departments.join("、")}` });
          } catch (writeErr) {
            setWriteBackResult({ error: true, text: departmentWriteBackFailure(ewoPolicyErrorMessage(writeErr)) });
          }
        }
      }
    } catch (err) {
      // 运行中途失败（如车型对齐 PATCH 失败）：仍标「进行中」的项改记失败，刷新后不会假装还在跑。
      failRunningFirstSync("首次同步没有开始：车型对齐失败，请重试");
      setHandoff((prev) => ({ ...prev, request: readFirstSyncRequest() }));
      setSummary({ error: true, text: `没有开始：${redactSensitiveText(ewoPolicyErrorMessage(err))}` });
      setRunning(false);
      window.__vseWizardBusy = false;
      return;
    }
    window.__vseWizardBusy = false;
    setRunning(false);
    failRunningFirstSync();
    const request = readFirstSyncRequest();
    setHandoff((prev) => ({ ...prev, request }));
    if (request) {
      const latest = summarizeFirstSync(request.entries);
      const progressText = `向导选择的 ${latest.total} 项：成功 ${latest.success} 项，未成功 ${latest.failed + latest.partial} 项，进行中 ${latest.running} 项，未开始 ${latest.notStarted} 项${latest.notApplicable ? `，不适用 ${latest.notApplicable} 项` : ""}。`;
      if (latest.allDone) {
        setSummary({ error: false, text: `${progressText}首次同步已全部完成。` });
      } else if (failed.length || blocked.length) {
        const parts = [];
        if (failed.length) parts.push(`${failed.length} 项首次同步没有成功（${failed.join("、")}）`);
        if (blocked.length) parts.push(`${blocked.length} 项没有开启（${blocked.join("、")}）`);
        setSummary({ error: true, text: `${progressText}本次已启用 ${enabled} 项；${parts.join("；")}。未开始或失败的项不会算作完成；未开启的项改好后可再点一次，已开启但同步失败的项可到交付物详情里重新同步。` });
      } else {
        setSummary({ error: true, text: `${progressText}仍有 ${latest.notStarted} 项未开始，未开始的项不会算作完成。` });
      }
    } else {
      const issues = failed.concat(blocked);
      setSummary(issues.length
        ? { error: true, text: `开启了 ${enabled} 项；${issues.length} 项没有完成（${issues.join("、")}）。原因写在对应行里，改好车型或科室后再点一次，只会处理没开启的那几项。` }
        : { error: false, text: enabled ? `全部开启了（${enabled} 项），之后每天会自动更新。` : "所有能自动同步的交付物都已经开启了。" });
    }
    await reload();
  };

  return html`<div class="vk-page as-page">
    <header class="vk-page-header"><div><h2>一键开启自动同步</h2>
      <p class="vk-muted" style="margin:4px 0 0">确认车型和科室 → 点「全部开启」。每一项都会先到系统里核对一遍数据，核对上了才开启。整个过程大约每项 1 分钟。</p></div>
      <div class="vk-page-actions"><a class="vk-btn" href=${BACK_HASH}>← 返回项目</a></div></header>

    ${scope && scope.deliverables.length === 0 && html`<p class="as-summary is-error" role="status">向导里没有勾选任何交付物：本次不会开启或同步任何交付物。</p>`}
    ${scope && scope.deliverables.length > 0 && !handoff.request && html`<p class="vk-muted" role="status">本次只处理向导里勾选的 ${scope.deliverables.length} 项交付物；未开始或失败的项不会算作完成。</p>`}
    ${handoff.request && html`<p class=${counts.allDone ? "as-summary" : "as-summary is-error"} role="status">首次同步进度：成功 ${counts.success} 项，未成功 ${counts.failed + counts.partial} 项，进行中 ${counts.running} 项，未开始 ${counts.notStarted} 项${counts.notApplicable ? `，不适用 ${counts.notApplicable} 项` : ""}。${counts.allDone ? "已全部完成。" : "未开始或失败的项不会算作完成。"}</p>`}

    <section class="as-form">
      <label class="as-field"><span>车型</span>
        <input value=${vehicle} onInput=${(e) => setVehicle(e.currentTarget.value)} placeholder="例如 F610S" disabled=${running} /></label>
      <div class="as-field"><span>科室（数模审核、NCR 按这些科室统计）</span>
        <div class="as-chips">${DEFAULT_DEPARTMENTS.map((dept) => html`<button type="button" key=${dept} disabled=${running}
          class=${`as-chip${departments.includes(dept) ? " is-on" : ""}`} aria-pressed=${departments.includes(dept) ? "true" : "false"}
          onClick=${() => toggle(dept)}>${dept}</button>`)}</div></div>
      <label class="as-field" style="display:flex;flex-direction:row;align-items:center;gap:8px">
        <input type="checkbox" data-field="write-back-departments" checked=${writeBack} disabled=${running}
          style="max-width:none;width:16px;height:16px;margin:0"
          onChange=${(e) => setWriteBack(e.currentTarget.checked)} />
        <span>同时把这些科室设为项目默认科室</span></label>
      <p class="vk-muted" style="margin:0">不勾选就不会改动项目默认科室；回写只改默认值，不会重写已经开启并验证过的同步绑定。</p>
      <div class="as-actions">
        <button type="button" class="vk-btn is-primary" disabled=${running || !targets.length} onClick=${start}>
          ${buttonLabel}</button>
        ${!vaultConfigured && html`<span class="vk-muted">需要先登录并保存公司账号的密码</span>`}
      </div>
      ${summary && html`<p class=${summary.error ? "as-summary is-error" : "as-summary"} role="status">${summary.text}</p>`}
      ${writeBackResult && html`<p class=${writeBackResult.error ? "as-summary is-error" : "as-summary"} role=${writeBackResult.error ? "alert" : "status"}>${writeBackResult.text}</p>`}
    </section>

    <section class="as-list" aria-label="交付物">
      ${deliverables.map((item) => {
        const state = rowState(item, load.policies, progress, scope, handoff.request);
        return html`<div class="as-row" key=${item.id}>
          <div><b>${item.name}</b><small>${(item.sourceInfo && item.sourceInfo.displayName) || ""}</small></div>
          <span class=${`as-state is-${state.tone}`}>${state.text}</span>
        </div>`;
      })}
    </section>
  </div>`;
}
