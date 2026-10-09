// 签署日报：选范围 → 一键生成（后台抓取 + 进度）→ 预览三图一表 → 长周期复核 → 复制正文 / 下载 .eml。
// 口径和正文都在后端（rules.py、mail.py）；本页画图（chart.js，Canvas 出 PNG）并负责交互。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";
import { renderChartPng } from "./chart.js";
import {
  conclusionsPayload, exportAllowed, formatTime, initialPicks, inlineImages, scopeKey, searchMisses, stageText, toggle,
} from "./report-logic.js";
import { SettingsPanel } from "./settings-panel.js";

const CHART_TITLES = { external: "图1 外区域会签未签单情况", sections: "图2 内部科室会签未签单情况", approval: "图3 审批未签单情况" };
const POLL_MS = 1500;

function Chips({ options, value, onChange, emptyText }) {
  if (!options.length) return html`<span class="vk-muted">${emptyText}</span>`;
  return html`<div class="sd-chips">
    ${options.map((option) => html`<label key=${option} class=${`sd-chip ${value.includes(option) ? "is-on" : ""}`}>
      <input type="checkbox" checked=${value.includes(option)} onChange=${() => onChange(toggle(value, option))} />${option}
    </label>`)}
  </div>`;
}

/** 富文本复制：clipboard.write 同时写 text/html 和 text/plain；非安全上下文时退回选中预览区复制（§10）。 */
async function copyRich(htmlText, plainText, fallbackNode) {
  if (window.isSecureContext && navigator.clipboard && window.ClipboardItem) {
    await navigator.clipboard.write([new ClipboardItem({
      "text/html": new Blob([htmlText], { type: "text/html" }),
      "text/plain": new Blob([plainText], { type: "text/plain" }),
    })]);
    return "正文已复制，可直接粘贴到邮件";
  }
  const range = document.createRange();
  range.selectNodeContents(fallbackNode);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  const ok = document.execCommand("copy");
  selection.removeAllRanges();
  if (!ok) throw new Error("浏览器不允许复制，请手动选中预览内容复制");
  return "当前不是 https 或 localhost，已改用选中复制；如粘贴后丢图，请逐张「复制图片」";
}

async function copyImage(dataUri) {
  if (!(window.isSecureContext && navigator.clipboard && window.ClipboardItem)) {
    throw new Error("当前地址不支持复制图片，请用「下载图片」");
  }
  const blob = await (await fetch(dataUri)).blob();
  await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}

function download(href, name) {
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function downloadEml(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "message/rfc822, application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let message = `下载失败（HTTP ${response.status}）`;
    try { message = (await response.json()).error.message || message; } catch (_) { /* keep */ }
    throw new Error(message);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const href = URL.createObjectURL(await response.blob());
  download(href, match ? decodeURIComponent(match[1]) : "daily-report.eml");
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** §7 复核时序 5–7：确定命中默认勾选、疑似不勾选；排除项在折叠区可强制纳入；未命中可搜索后手工纳入。 */
function LongCycleReview({ longCycle, onConfirm, onProceed, proceeding }) {
  const [picks, setPicks] = useState(() => initialPicks(longCycle));
  const [forced, setForced] = useState({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  if (!longCycle.review.length) return null;
  const id = (item) => `${item.project}\u0000${item.normalized}`;
  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm(conclusionsPayload(longCycle, picks, forced));
    } finally {
      setBusy(false);
    }
  };
  return html`<section class="sd-review" aria-label="长周期初筛复核">
    <h4>${longCycle.review.length} 项长周期初筛待确认</h4>
    <table class="sd-table"><thead><tr><th>纳入</th><th>项目</th><th>零件名称</th><th>命中规则</th><th>结果</th><th>涉及 3D单</th></tr></thead><tbody>
      ${longCycle.review.map((item) => html`<tr key=${id(item)}>
        <td><input type="checkbox" checked=${Boolean(picks[id(item)])} onChange=${() => setPicks({ ...picks, [id(item)]: !picks[id(item)] })} /></td>
        <td>${item.project}</td><td>${item.names.join("、")}</td><td>${item.rule}</td>
        <td>${item.result}${item.reason ? `（${item.reason}）` : ""}</td><td>${item.flows}</td></tr>`)}
    </tbody></table>
    ${longCycle.excluded.length > 0 && html`<details><summary>排除 ${longCycle.excluded.length} 项（可按项目强制纳入）</summary>
      <ul class="sd-plain-list">${longCycle.excluded.map((item) => html`<li key=${id(item)}><label>
        <input type="checkbox" checked=${Boolean(forced[id(item)])} onChange=${() => setForced({ ...forced, [id(item)]: !forced[id(item)] })} />
        ${item.project} · ${item.names.join("、")}（${item.reason}，${item.flows} 份）</label></li>`)}</ul></details>`}
    <details><summary>搜索未命中零件手工纳入</summary>
      <input placeholder="输入零件名称的一部分" value=${query} onInput=${(e) => setQuery(e.target.value)} />
      <ul class="sd-plain-list">${searchMisses(longCycle.misses, query).map((item) => html`<li key=${id(item)}><label>
        <input type="checkbox" checked=${Boolean(forced[id(item)])} onChange=${() => setForced({ ...forced, [id(item)]: !forced[id(item)] })} />
        ${item.project} · ${item.normalized}（${item.flows} 份）</label></li>`)}</ul></details>
    <div class="sd-actions">
      <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${confirm}>确认并记住</button>
      <button type="button" class="vk-btn" disabled=${busy || proceeding} onClick=${onProceed}>本次按建议继续</button>
      <span class="vk-muted">「本次按建议继续」不写入记忆，下次仍会提示。</span>
    </div>
  </section>`;
}

function Recipients({ result, onSave }) {
  const [to, setTo] = useState(result.recipientsText.to);
  const [cc, setCc] = useState(result.recipientsText.cc);
  const [busy, setBusy] = useState(false);
  const list = (items) => items.map((r) => r.name || r.address).join("、") || "（空）";
  const { added, missing, ambiguous } = result.recipients;
  return html`<details class="sd-panel" open=${missing.length > 0 || ambiguous.length > 0}>
    <summary>收件人 ${result.recipients.to.length} 人，抄送 ${result.recipients.cc.length} 人${added.length ? `（自动加入有未签单情况的人 ${added.length} 位）` : ""}</summary>
    <p><b>收件人：</b>${list(result.recipients.to)}</p>
    <p><b>抄送：</b>${list(result.recipients.cc)}</p>
    ${missing.length > 0 && html`<p class="sd-warn">有未签单情况但通讯录里没有邮箱：${missing.join("、")}</p>`}
    ${ambiguous.length > 0 && html`<p class="sd-warn">通讯录里同名对应多个邮箱，没有自动加入，请手工选择：${ambiguous.map((a) => `${a.name}（${a.addresses.join(" / ")}）`).join("；")}</p>`}
    <label class="sd-field">收件人名单（本范围记住，粘贴 "姓名"&lt;邮箱&gt;）
      <textarea rows="3" value=${to} onInput=${(e) => setTo(e.target.value)}></textarea></label>
    <label class="sd-field">抄送名单
      <textarea rows="3" value=${cc} onInput=${(e) => setCc(e.target.value)}></textarea></label>
    <button type="button" class="vk-btn" disabled=${busy}
      onClick=${async () => { setBusy(true); try { await onSave({ to, cc }); } finally { setBusy(false); } }}>保存名单</button>
  </details>`;
}

function ChartTools({ images, onMessage }) {
  const keys = Object.keys(images);
  if (!keys.length) return null;
  return html`<div class="sd-chart-tools">${keys.map((key) => html`<span key=${key} class="sd-actions">
    <b>${CHART_TITLES[key]}</b>
    <button type="button" class="vk-btn" onClick=${async () => {
      try { await copyImage(images[key]); onMessage(`${CHART_TITLES[key]} 已复制`); } catch (err) { onMessage(err.message); }
    }}>复制图片</button>
    <button type="button" class="vk-btn" onClick=${() => download(images[key], `${CHART_TITLES[key]}.png`)}>下载图片</button>
  </span>`)}</div>`;
}

export default function Page({ plugin, api }) {
  useStylesheet(`/plugins/${plugin.id}/static/report.css`);
  const [state, setState] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState(null);
  const [texts, setTexts] = useState({ greeting: "各位领导、同事：", planText: "", feishuLink: "" });
  const [phase, setPhase] = useState("idle"); // idle | refreshing | generating
  const [task, setTask] = useState(null);
  const [error, setError] = useState(null); // {message, canFallback}
  const [result, setResult] = useState(null);
  const [images, setImages] = useState({});
  const [proceed, setProceed] = useState(false);
  const [toast, setToast] = useState("");
  const previewRef = useRef(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = async () => {
    setLoadError(null);
    try {
      const data = await api.get("state");
      setState(data);
      setForm((current) => current || { ...data.form });
      return data;
    } catch (err) {
      setLoadError(err);
      return null;
    }
  };
  useEffect(() => { load(); }, []);

  // 范围变了就带出该范围记住的文案（§7 日报偏好按范围记住）。
  const key = form ? scopeKey(form.projects, form.departments, form.watchlistOnly) : "";
  useEffect(() => {
    if (!state || !form) return;
    const prefs = state.preferences[key];
    if (prefs) {
      setForm((f) => ({ ...f, region: prefs.region || f.region }));
      setTexts({ greeting: prefs.greeting || "各位领导、同事：", planText: prefs.planText || "", feishuLink: prefs.feishuLink || "" });
    }
  }, [key, state]);

  if (!state || !form) return html`<${StateBlock} loading=${!loadError} error=${loadError} onRetry=${load} />`;

  const busy = phase !== "idle";
  const flash = (text) => { setToast(text); setTimeout(() => { if (alive.current) setToast(""); }, 4000); };
  const requestBody = () => ({ ...form, ...texts });

  const generate = async () => {
    setPhase("generating");
    try {
      const data = await api.post("generate", requestBody());
      // 结果和三张图一起落定：预览、复制、.eml 用同一张 PNG，预览里也不会出现未替换的 cid: 地址。
      const next = {};
      data.chartsWithData.forEach((chart) => { next[chart] = renderChartPng(data.charts[chart], chart); });
      setImages(next);
      setResult(data);
      setProceed(false);
      setError(null);
      load();
    } catch (err) {
      setError({ message: err.message, canFallback: false });
    } finally {
      setPhase("idle");
    }
  };

  const poll = async (taskId) => {
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      if (!alive.current) return null;
      const view = await api.get(`refresh/${taskId}`);
      setTask(view);
      if (view.status !== "queued" && view.status !== "running") return view;
    }
  };

  const oneClick = async () => {
    setError(null);
    setPhase("refreshing");
    try {
      const started = await api.post("refresh", { watchlistOnly: form.watchlistOnly });
      setTask(started);
      const finished = started.status === "succeeded" ? started : await poll(started.taskId);
      if (!finished) return;
      if (finished.status !== "succeeded") throw new Error(finished.error || "TDC 抓取未完成");
    } catch (err) {
      setPhase("idle");
      await load();
      setError({ message: err.message, canFallback: true });
      return;
    }
    await load();
    await generate();
  };

  const confirmLongCycle = async (batches) => {
    for (const batch of batches) await api.post("long-cycle", batch);
    await generate();
  };

  const savePrefs = async (patch) => {
    await api.post("config", { preferences: { [result.scopeKey]: { ...texts, region: form.region, ...result.recipientsText, ...patch } } });
    await load();
    await generate();
  };

  const canExport = exportAllowed(result, proceed);
  const copy = async () => {
    try {
      flash(await copyRich(inlineImages(result.html, images), result.text, previewRef.current));
    } catch (err) {
      flash(err.message);
    }
  };
  const eml = async () => {
    try {
      await downloadEml(api.url("eml"), { ...requestBody(), images, proceedWithSuggestion: proceed });
    } catch (err) {
      flash(err.message);
    }
  };

  const set = (field) => (value) => setForm({ ...form, [field]: value });
  const setText = (field) => (e) => setTexts({ ...texts, [field]: e.target.value });
  const dataTime = state.data ? formatTime(state.data.snapshotAt) : "暂无";
  const watch = state.watchlist;

  return html`<div class="vk-page sd-page">
    <header class="vk-page-header">
      <h2>3D单签署日报</h2>
      <div class="vk-page-actions"><span class="vk-muted">TDC 数据时间：${dataTime}${state.data && state.data.coverage === "watchlist" ? "（仅关注清单）" : ""}</span></div>
    </header>

    <section class="sd-form">
      <div class="sd-field"><span>项目/车型</span>
        <${Chips} options=${state.options.projects} value=${form.projects} onChange=${set("projects")} emptyText="暂无数据，先点一键生成" /></div>
      <div class="sd-field"><span>归属科室（按申请人的花名册科室）</span>
        <${Chips} options=${state.options.departments} value=${form.departments} onChange=${set("departments")} emptyText="—" /></div>
      <label class="sd-check"><input type="checkbox" checked=${form.watchlistOnly}
        onChange=${() => set("watchlistOnly")(!form.watchlistOnly)} />只统计关注清单
        <span class="vk-muted">（关注清单 ${watch.count} 份，在交付物明细的数模设计审核流程报表里维护）</span></label>
      <label class="sd-field"><span>区域名</span>
        <input value=${form.region} onInput=${(e) => set("region")(e.target.value)} /></label>
      <label class="sd-field"><span>称呼</span><input value=${texts.greeting} onInput=${setText("greeting")} /></label>
      <label class="sd-field"><span>计划/超期说明</span>
        <textarea rows="2" placeholder="如：计划10-10发布，已超期x天" value=${texts.planText} onInput=${setText("planText")}></textarea></label>
      <label class="sd-field"><span>飞书多维表格链接</span>
        <input value=${texts.feishuLink} placeholder="问题反馈：https://..." onInput=${setText("feishuLink")} /></label>
      <div class="sd-actions">
        <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${oneClick}>一键生成</button>
        <button type="button" class="vk-btn" disabled=${busy || !state.data} onClick=${generate}>用现有数据生成</button>
        ${phase === "refreshing" && html`<span class="sd-progress" role="status">${task && task.reused ? "已有抓取在运行，沿用它：" : ""}${stageText(task) || "正在提交抓取任务…"}</span>`}
        ${phase === "generating" && html`<span class="sd-progress" role="status">正在生成…</span>`}
      </div>
      ${state.dataError && !state.data && html`<p class="vk-muted">${state.dataError}</p>`}
      ${error && html`<div class="vk-state is-error" role="alert">
        <span>${error.message}</span>
        ${error.canFallback && state.data && html`<button type="button" class="vk-btn" onClick=${generate}>用最近一次数据生成（${dataTime}）</button>`}
      </div>`}
    </section>

    <${SettingsPanel} api=${api} state=${state} onSaved=${load} onChanged=${() => { if (result) generate(); }} />

    ${result && html`<section class="sd-result">
      ${result.stale && html`<div class="sd-notice is-stale">用的是旧数据（数据时间 ${formatTime(result.snapshotAt)}），不写快照，不显示日变化。</div>`}
      ${result.notices.map((n) => html`<div key=${n.kind} class=${`sd-notice${n.blocking ? " is-blocking" : ""}`}>${n.text}</div>`)}
      <${LongCycleReview} key=${result.longCycle.review.map((i) => i.normalized).join("|")} longCycle=${result.longCycle}
        onConfirm=${confirmLongCycle} onProceed=${() => setProceed(true)} proceeding=${proceed} />
      <div class="sd-preview-bar">
        <div><b>主题：</b>${result.subject}<br /><span class="vk-muted">数据日期 ${result.dataDate}${result.baseDate ? `；日变化基线 ${result.baseDate}` : ""}</span></div>
        <div class="sd-actions">
          <button type="button" class="vk-btn is-primary" disabled=${!canExport} onClick=${copy}>复制正文</button>
          <button type="button" class="vk-btn" disabled=${!canExport} onClick=${eml}>下载 .eml 草稿</button>
          ${!canExport && html`<span class="vk-muted">长周期初筛待确认，确认后才能复制和下载</span>`}
          ${toast && html`<span class="vk-muted" role="status">${toast}</span>`}
        </div>
      </div>
      <${Recipients} key=${result.scopeKey + result.recipientsText.to + result.recipientsText.cc} result=${result}
        onSave=${(names) => savePrefs(names)} />
      <${ChartTools} images=${images} onMessage=${flash} />
      <div class="sd-preview" ref=${previewRef} dangerouslySetInnerHTML=${{ __html: inlineImages(result.html, images) }}></div>
    </section>`}
  </div>`;
}
