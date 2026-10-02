// 签署日报：一键抓取 TDC 数模设计审核流程并生成「3D单签署进展」日报邮件。
// 计算与渲染都在后端（report.py）；本页只负责选范围、触发、预览、复制和下载。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";

const ROLE_COLUMNS = [
  "造型", "总体工程", "CAE", "整车性能", "车身", "内外饰", "底盘", "动力", "空调电子",
  "尺寸工程", "冲压", "车身制造", "涂装", "总装", "新能源", "感知质量", "造型专家审核", "NVH",
  "设计工程师", "主任工程师", "专家/经理", "首席/总监",
];

export function formatTime(value) {
  if (!value) return "暂无";
  const text = String(value).replace("T", " ").replace(/\.\d+/, "").replace(/Z$/, " UTC");
  return text;
}

/** "张三=车身科" 每行一条 <-> {张三: 车身科} */
export function parsePairs(text) {
  const result = {};
  String(text || "").split(/\r?\n/).forEach((line) => {
    const match = line.match(/^\s*([^=＝:：]+?)\s*[=＝:：]\s*(.+?)\s*$/);
    if (match) result[match[1]] = match[2];
  });
  return result;
}

export function formatPairs(map) {
  return Object.entries(map || {}).map(([key, value]) => `${key}=${value}`).join("\n");
}

export function parseLines(text) {
  return [...new Set(String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
}

function toggle(list, value) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

async function copyRich(htmlText, plainText, fallbackNode) {
  if (navigator.clipboard && window.ClipboardItem) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([htmlText], { type: "text/html" }),
        "text/plain": new Blob([plainText], { type: "text/plain" }),
      })]);
      return;
    } catch (_) { /* 退回到选区复制 */ }
  }
  const range = document.createRange();
  range.selectNodeContents(fallbackNode);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  const ok = document.execCommand("copy");
  selection.removeAllRanges();
  if (!ok) throw new Error("浏览器不允许复制，请手动选中预览内容复制");
}

async function downloadEml(url, form) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "message/rfc822, application/json" },
    body: JSON.stringify(form),
  });
  if (!response.ok) {
    let message = `下载失败（HTTP ${response.status}）`;
    try { message = (await response.json()).error.message || message; } catch (_) { /* keep */ }
    throw new Error(message);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const name = match ? decodeURIComponent(match[1]) : "daily-report.eml";
  const href = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

function Chips({ options, value, onChange, emptyText }) {
  if (!options.length) return html`<span class="vk-muted">${emptyText}</span>`;
  return html`<div class="sd-chips">
    ${options.map((option) => html`<label key=${option} class=${`sd-chip ${value.includes(option) ? "is-on" : ""}`}>
      <input type="checkbox" checked=${value.includes(option)} onChange=${() => onChange(toggle(value, option))} />${option}
    </label>`)}
  </div>`;
}

function Settings({ config, onSave }) {
  const [roles, setRoles] = useState({ ...config.roleDepartments });
  const [people, setPeople] = useState(formatPairs(config.personDepartments));
  const [applicants, setApplicants] = useState(formatPairs(config.applicantDepartments));
  const [longNames, setLongNames] = useState((config.longCycleNames || []).join("\n"));
  const [book, setBook] = useState(config.addressBook || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      await onSave({
        roleDepartments: roles,
        personDepartments: parsePairs(people),
        applicantDepartments: parsePairs(applicants),
        longCycleNames: parseLines(longNames),
        addressBook: book,
      });
      setMessage("已保存");
    } catch (err) {
      setMessage(`保存失败：${err.message}`);
    } finally {
      setBusy(false);
    }
  };
  return html`<details class="sd-panel">
    <summary>设置（科室归属、长周期件清单、通讯录）</summary>
    <div class="sd-settings">
      <section>
        <h4>角色列 → 科室</h4>
        <p class="vk-muted">填「@部门」表示归到该 3D单的申请部门（审批人默认如此）。</p>
        <div class="sd-role-grid">
          ${ROLE_COLUMNS.map((column) => html`<label key=${column}>${column}
            <input value=${roles[column] || ""} onInput=${(e) => setRoles({ ...roles, [column]: e.target.value })} /></label>`)}
        </div>
      </section>
      <section>
        <h4>「@部门」的申请部门 → 科室</h4>
        <textarea rows="3" placeholder="每行一条，例如：ES科=运营管理部" value=${applicants} onInput=${(e) => setApplicants(e.target.value)}></textarea>
      </section>
      <section>
        <h4>人员 → 科室（优先于角色列）</h4>
        <textarea rows="6" placeholder="每行一条，例如：张三=车身科" value=${people} onInput=${(e) => setPeople(e.target.value)}></textarea>
      </section>
      <section>
        <h4>长周期件清单（零件名称，每行一个）</h4>
        <textarea rows="6" value=${longNames} onInput=${(e) => setLongNames(e.target.value)}></textarea>
      </section>
      <section>
        <h4>通讯录（用于把有未签单的人自动加进收件人）</h4>
        <textarea rows="6" placeholder='"张三"<zhangsan@example.com>; "李四"<lisi@example.com>' value=${book} onInput=${(e) => setBook(e.target.value)}></textarea>
      </section>
      <div class="sd-actions">
        <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${save}>保存设置</button>
        <span class="vk-muted">${message}</span>
      </div>
    </div>
  </details>`;
}

function LongCycleConfirm({ hits, onConfirm }) {
  const [picked, setPicked] = useState(() => Object.fromEntries(hits.map((h) => [`${h.project}\u0000${h.part}`, true])));
  if (!hits.length) return null;
  const submit = () => {
    const decisions = {};
    hits.forEach((h) => {
      decisions[h.project] = decisions[h.project] || {};
      decisions[h.project][h.part] = Boolean(picked[`${h.project}\u0000${h.part}`]);
    });
    onConfirm(decisions);
  };
  return html`<div class="sd-confirm">
    <p>以下零件名称命中长周期件清单，请勾选确认（未勾选的记为非长周期）：</p>
    <ul>${hits.map((h) => {
      const key = `${h.project}\u0000${h.part}`;
      return html`<li key=${key}><label><input type="checkbox" checked=${Boolean(picked[key])}
        onChange=${() => setPicked({ ...picked, [key]: !picked[key] })} />
        ${h.project} · ${h.part} <span class="vk-muted">（清单：${h.matched}）</span></label></li>`;
    })}</ul>
    <button type="button" class="vk-btn is-primary" onClick=${submit}>确认并重新生成</button>
  </div>`;
}

function Recipients({ result, onSave }) {
  const [to, setTo] = useState(result.recipientsText.to);
  const [cc, setCc] = useState(result.recipientsText.cc);
  const [busy, setBusy] = useState(false);
  const list = (items) => items.map((r) => r.name || r.address).join("、") || "（空）";
  const added = result.recipients.added || [];
  return html`<details class="sd-panel">
    <summary>收件人 ${result.recipients.to.length} 人，抄送 ${result.recipients.cc.length} 人${added.length ? `（自动加入未签人 ${added.length} 人）` : ""}</summary>
    <p><b>收件人：</b>${list(result.recipients.to)}</p>
    <p><b>抄送：</b>${list(result.recipients.cc)}</p>
    <label class="sd-field">收件人名单（本范围记住，粘贴 "姓名"&lt;邮箱&gt;）
      <textarea rows="3" value=${to} onInput=${(e) => setTo(e.target.value)}></textarea></label>
    <label class="sd-field">抄送名单
      <textarea rows="3" value=${cc} onInput=${(e) => setCc(e.target.value)}></textarea></label>
    <button type="button" class="vk-btn" disabled=${busy}
      onClick=${async () => { setBusy(true); try { await onSave({ to, cc }); } finally { setBusy(false); } }}>保存名单</button>
  </details>`;
}

export default function Page({ plugin, api }) {
  useStylesheet(`/plugins/${plugin.id}/static/report.css`);
  const [state, setState] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | refreshing | generating
  const [error, setError] = useState(null); // {message, canFallback}
  const [result, setResult] = useState(null);
  const [toast, setToast] = useState("");
  const previewRef = useRef(null);

  const load = async () => {
    setLoadError(null);
    try {
      const data = await api.get("state");
      setState(data);
      setForm((current) => current || { ...data.config.form });
      return data;
    } catch (err) {
      setLoadError(err);
      return null;
    }
  };
  useEffect(() => { load(); }, []);

  if (!state || !form) return html`<${StateBlock} loading=${!loadError} error=${loadError} onRetry=${load} />`;

  const busy = phase !== "idle";
  const saveConfig = async (patch) => {
    const data = await api.post("config", patch);
    setState((current) => ({ ...current, config: data.config }));
    return data.config;
  };

  const generate = async () => {
    setPhase("generating");
    try {
      const data = await api.post("generate", form);
      setResult(data);
      setError(null);
    } catch (err) {
      setError({ message: err.message, canFallback: false });
    } finally {
      setPhase("idle");
    }
  };

  const oneClick = async () => {
    setError(null);
    setPhase("refreshing");
    try {
      await api.post("refresh", {});
    } catch (err) {
      setPhase("idle");
      await load();
      setError({ message: err.message, canFallback: true });
      return;
    }
    await load();
    await generate();
  };

  const confirmLongCycle = async (decisions) => {
    const merged = { ...(state.config.longCycleConfirmed || {}) };
    Object.entries(decisions).forEach(([project, parts]) => { merged[project] = { ...(merged[project] || {}), ...parts }; });
    await saveConfig({ longCycleConfirmed: merged });
    await generate();
  };

  const saveRecipients = async (texts) => {
    await saveConfig({ recipients: { ...(state.config.recipients || {}), [result.scopeKey]: texts } });
    await generate();
  };

  const flash = (text) => { setToast(text); setTimeout(() => setToast(""), 3000); };
  const copy = async () => {
    try {
      await copyRich(result.html, result.text, previewRef.current);
      flash("正文已复制，可直接粘贴到邮件");
    } catch (err) {
      flash(err.message);
    }
  };
  const eml = async () => {
    try {
      await downloadEml(api.url("eml"), form);
    } catch (err) {
      flash(err.message);
    }
  };

  const set = (key) => (value) => setForm({ ...form, [key]: value });
  const dataTime = state.data ? formatTime(state.data.updatedAt) : "暂无";

  return html`<div class="vk-page sd-page">
    <header class="vk-page-header">
      <h2>3D单签署日报</h2>
      <div class="vk-page-actions"><span class="vk-muted">TDC 数据时间：${dataTime}</span></div>
    </header>

    <section class="sd-form">
      <div class="sd-field"><span>项目/车型</span>
        <${Chips} options=${state.options.projects} value=${form.projects} onChange=${set("projects")} emptyText="暂无数据，先点一键生成" /></div>
      <div class="sd-field"><span>部门</span>
        <${Chips} options=${state.options.departments} value=${form.departments} onChange=${set("departments")} emptyText="—" /></div>
      <label class="sd-field"><span>区域名</span>
        <input value=${form.region} onInput=${(e) => set("region")(e.target.value)} /></label>
      <label class="sd-field"><span>计划/超期说明</span>
        <textarea rows="2" placeholder="如：计划10-10发布，已超期x天" value=${form.planText} onInput=${(e) => set("planText")(e.target.value)}></textarea></label>
      <label class="sd-field"><span>飞书多维表格链接</span>
        <input value=${form.feishuLink} placeholder="问题反馈：https://..." onInput=${(e) => set("feishuLink")(e.target.value)} /></label>
      <div class="sd-actions">
        <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${oneClick}>一键生成</button>
        <button type="button" class="vk-btn" disabled=${busy || !state.data} onClick=${generate}>用现有数据生成</button>
        ${phase === "refreshing" && html`<span class="sd-progress">正在抓取 TDC 数模设计审核流程，数据多时需要几分钟…</span>`}
        ${phase === "generating" && html`<span class="sd-progress">正在生成…</span>`}
      </div>
      ${state.dataError && !state.data && html`<p class="vk-muted">${state.dataError}</p>`}
      ${error && html`<div class="vk-state is-error" role="alert">
        <span>${error.message}</span>
        ${error.canFallback && state.data && html`<button type="button" class="vk-btn" onClick=${generate}>用最近一次数据生成（${dataTime}）</button>`}
      </div>`}
    </section>

    <${Settings} key=${JSON.stringify(state.config.roleDepartments)} config=${state.config} onSave=${saveConfig} />

    ${result && html`<section class="sd-result">
      ${result.notices.map((n) => html`<div key=${n.kind} class="sd-notice">${n.text}</div>`)}
      <${LongCycleConfirm} key=${result.longCycleHits.map((h) => h.part).join("|")} hits=${result.longCycleHits} onConfirm=${confirmLongCycle} />
      <div class="sd-preview-bar">
        <div><b>主题：</b>${result.subject}<br /><span class="vk-muted">数据时间：${formatTime(result.data.updatedAt)}${result.previousDate ? `；日变化基线：${result.previousDate}` : "；无上次汇总，不显示日变化"}</span></div>
        <div class="sd-actions">
          <button type="button" class="vk-btn is-primary" onClick=${copy}>复制正文</button>
          <button type="button" class="vk-btn" onClick=${eml}>下载 .eml 草稿</button>
          ${toast && html`<span class="vk-muted">${toast}</span>`}
        </div>
      </div>
      <${Recipients} key=${result.scopeKey + result.recipientsText.to + result.recipientsText.cc} result=${result} onSave=${saveRecipients} />
      <div class="sd-preview" ref=${previewRef} dangerouslySetInnerHTML=${{ __html: result.html }}></div>
    </section>`}
  </div>`;
}
