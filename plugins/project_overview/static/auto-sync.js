// #p/project-overview/auto-sync —「一键开启自动同步」（需求 D2/D3）。
// 按项目的车型和科室推导每个交付物的筛选条件，然后对每个还没开启的交付物依次跑一遍
// 交付物详情里同一个「开始配置并启用」流程（取证两次 → 保存 → 首次同步）。
// 不新增后端接口、不绕开任何校验：哪一项没核对上，就停在那一项并说清原因。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
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

/** 可以一键开启的交付物：有连接器、且还没开启。 */
export function autoSyncTargets(deliverables, policies) {
  return (deliverables || []).filter((d) => {
    const caps = d.sourceInfo || {};
    if (!caps.syncCapable) return false;
    const policy = policies[d.id];
    return !(policy && policy.enabled === true);
  });
}

function rowState(item, policies, progress) {
  const caps = item.sourceInfo || {};
  if (!caps.syncCapable) return { tone: "off", text: caps.syncNote || "只能手工维护" };
  if (progress[item.id]) return progress[item.id];
  const policy = policies[item.id];
  if (policy && policy.enabled === true) return { tone: "ok", text: "已开启 ✓" };
  return { tone: "off", text: "未开启" };
}

export default function AutoSyncPage({ plugin }) {
  useStylesheet(`/plugins/${(plugin && plugin.id) || "project-overview"}/static/auto-sync.css`);
  const [load, setLoad] = useState({ loading: true, error: "", status: null, settings: null, policies: {}, project: null });
  const [vehicle, setVehicle] = useState("");
  const [departments, setDepartments] = useState(DEFAULT_DEPARTMENTS);
  const [progress, setProgress] = useState({});
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState(null);

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
    reload().then((loaded) => {
      if (!loaded) return;
      const phaseName = loaded.status && loaded.status.phase ? loaded.status.phase.displayName : "";
      setVehicle((loaded.project && loaded.project.vehicle) || phaseName || "");
      if (loaded.project && loaded.project.departments && loaded.project.departments.length) setDepartments(loaded.project.departments);
    });
  }, []);

  if (load.loading) return html`<div class="vk-page"><p class="vk-muted">正在读取交付物…</p></div>`;
  if (load.error && !load.status) {
    return html`<div class="vk-page"><div class="vk-state is-error" role="alert"><span>读取失败：${load.error}</span>
      <button type="button" class="vk-btn" onClick=${reload}>重试</button></div></div>`;
  }

  const deliverables = ((load.status && load.status.deliverables) || []).filter((d) => !d.retired);
  const vaultConfigured = Boolean(load.settings) && load.settings.credentialVaultConfigured === true;
  const targets = autoSyncTargets(deliverables, load.policies);
  const toggle = (dept) => setDepartments(departments.includes(dept) ? departments.filter((d) => d !== dept) : [...departments, dept]);
  const mark = (id, next) => setProgress((prev) => ({ ...prev, [id]: next }));

  const start = async () => {
    const model = vehicle.trim();
    if (!model) { setSummary({ error: true, text: "请先填写车型，例如 F610S" }); return; }
    if (!vaultConfigured) { setSummary({ error: true, text: "还没有保存公司账号的密码：点右上角「登录 / 切换」，登录时勾选“保存至凭据保护库”，然后再回来。" }); return; }
    setRunning(true);
    setSummary(null);
    window.__vseWizardBusy = true;
    let ok = 0;
    const failed = [];
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
          failed.push(item.name);
          continue;
        }
        mark(item.id, { tone: "info", text: "正在核对…" });
        try {
          await runEnableFlow({ item, capabilities, values, vaultConfigured, say: (text) => mark(item.id, { tone: "info", text }) });
          mark(item.id, { tone: "ok", text: "已核对 ✓ 已开启" });
          ok += 1;
        } catch (err) {
          mark(item.id, { tone: "bad", text: redactSensitiveText(ewoPolicyErrorMessage(err)) });
          failed.push(item.name);
        }
      }
      // 科室回写：用户确认的科室集合在启用流程成功后写回项目默认科室（只在界面有明确科室选择时，失败不阻断流程）
      const currentProjectId = load.project && load.project.id;
      if (ok > 0 && currentProjectId && Array.isArray(departments) && departments.length > 0) {
        try {
          await apiRequest(`/api/p/workbench/projects/${enc(currentProjectId)}`, {
            method: "PATCH",
            body: { departments },
          });
        } catch (writeErr) {
          console.warn("回写项目默认科室失败：", writeErr);
        }
      }
    } catch (err) {
      setSummary({ error: true, text: `没有开始：${redactSensitiveText(ewoPolicyErrorMessage(err))}` });
      setRunning(false);
      window.__vseWizardBusy = false;
      return;
    }
    window.__vseWizardBusy = false;
    setRunning(false);
    setSummary(failed.length
      ? { error: true, text: `开启了 ${ok} 项；${failed.length} 项没核对上（${failed.join("、")}）。原因写在对应行里，改好车型或科室后再点一次，只会处理没开启的那几项。` }
      : { error: false, text: ok ? `全部开启了（${ok} 项），之后每天会自动更新。` : "所有能自动同步的交付物都已经开启了。" });
    await reload();
  };

  return html`<div class="vk-page as-page">
    <header class="vk-page-header"><div><h2>一键开启自动同步</h2>
      <p class="vk-muted" style="margin:4px 0 0">确认车型和科室 → 点「全部开启」。每一项都会先到系统里核对一遍数据，核对上了才开启。整个过程大约每项 1 分钟。</p></div>
      <div class="vk-page-actions"><a class="vk-btn" href=${BACK_HASH}>← 返回项目</a></div></header>

    <section class="as-form">
      <label class="as-field"><span>车型</span>
        <input value=${vehicle} onInput=${(e) => setVehicle(e.currentTarget.value)} placeholder="例如 F610S" disabled=${running} /></label>
      <div class="as-field"><span>科室（数模审核、NCR 按这些科室统计）</span>
        <div class="as-chips">${DEFAULT_DEPARTMENTS.map((dept) => html`<button type="button" key=${dept} disabled=${running}
          class=${`as-chip${departments.includes(dept) ? " is-on" : ""}`} aria-pressed=${departments.includes(dept) ? "true" : "false"}
          onClick=${() => toggle(dept)}>${dept}</button>`)}</div></div>
      <div class="as-actions">
        <button type="button" class="vk-btn is-primary" disabled=${running || !targets.length} onClick=${start}>
          ${running ? "正在开启…" : targets.length ? `全部开启（${targets.length} 项）` : "已全部开启"}</button>
        ${!vaultConfigured && html`<span class="vk-muted">需要先登录并保存公司账号的密码</span>`}
      </div>
      ${summary && html`<p class=${summary.error ? "as-summary is-error" : "as-summary"} role="status">${summary.text}</p>`}
    </section>

    <section class="as-list" aria-label="交付物">
      ${deliverables.map((item) => {
        const state = rowState(item, load.policies, progress);
        return html`<div class="as-row" key=${item.id}>
          <div><b>${item.name}</b><small>${(item.sourceInfo && item.sourceInfo.displayName) || ""}</small></div>
          <span class=${`as-state is-${state.tone}`}>${state.text}</span>
        </div>`;
      })}
    </section>
  </div>`;
}
