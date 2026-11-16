// 签署日报：选范围 → 一键生成（后台抓取 + 进度）→ 预览三图一表 → 长周期复核 → 复制正文 / 下载 .eml。
// 口径和正文都在后端（rules.py、mail.py）；本页画图（chart.js，Canvas 出 PNG）并负责交互。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { StateBlock, useStylesheet } from "/static/host/kit.js";
import { CHART_PRESETS, matchPreset, presetPalettes, renderChartPng, resolveAllPalettes, tooLight } from "./chart.js";
import {
  baselineOptions, compareResultText, comparePlan, conclusionsPayload, exportAllowed, fileDateHint, formatTime,
  initialPicks,
  inlineImages, migratePrefs, orphanProjects, sameColors, scopeKey, searchMisses, stageText, statusGateText, todayIso,
  toggle,
} from "./report-logic.js";
import { Chips } from "./chips.js";
import { SettingsPanel } from "./settings-panel.js";

const CHART_TITLES = { external: "图1 外区域会签未签单情况", sections: "图2 内部科室会签未签单情况", approval: "图3 审批未签单情况" };
const POLL_MS = 1500;
/** 配色面板：按「画的是什么」起名，不露 key。一个输入框可以同时管普通柱和特殊组柱。 */
const COLOR_FIELDS = [
  { id: "external", label: "图1 外区域柱子", chart: "external", slots: ["bar", "special"] },
  { id: "sectionsBar", label: "图2 普通科室", chart: "sections", slots: ["bar"] },
  { id: "sectionsSpecial", label: "图2 特殊组", chart: "sections", slots: ["special"] },
  { id: "approval", label: "图3 审批柱子", chart: "approval", slots: ["bar", "special"] },
];

/** 用当前配色把结果里的三张图画成 PNG：预览、复制正文、下载图片、.eml 用的都是这一份。 */
function renderImages(data, colors) {
  const next = {};
  (data.chartsWithData || []).forEach((chart) => {
    next[chart] = renderChartPng(data.charts[chart], chart, undefined, colors ? colors[chart] : undefined);
  });
  return next;
}

/** 图表配色：一键方案 + 折叠的「自定义」取色；改了马上重画右侧的图，保存是可选的。 */
function ChartColors({ colors, saved, onChange, onSave, onReset, busy }) {
  const dirty = !sameColors(colors, saved);
  const preset = matchPreset(colors);
  const set = (field, value) => {
    const next = { ...colors, [field.chart]: { ...colors[field.chart] } };
    field.slots.forEach((slot) => { next[field.chart][slot] = value; });
    onChange(next);
  };
  const light = COLOR_FIELDS.filter((field) => tooLight(colors[field.chart][field.slots[0]]));
  return html`<details class="sd-panel sd-colors">
    <summary>图表配色${dirty ? "（已修改，未保存）" : ""}</summary>
    <p class="vk-muted sd-hint">点一下换一套颜色，右边的图马上跟着变；复制正文、下载图片和 .eml 都用这里的颜色。</p>
    <div class="sd-actions" role="group" aria-label="配色方案">
      ${CHART_PRESETS.map((item) => html`<button type="button" key=${item.id} disabled=${busy}
        class=${`vk-btn${preset === item.id ? " is-primary" : ""}`} aria-pressed=${preset === item.id}
        onClick=${() => onChange(presetPalettes(item.id))}>${item.name}</button>`)}
    </div>
    <details class="sd-colors-custom"><summary>自定义</summary>
      <div class="sd-color-grid">${COLOR_FIELDS.map((field) => html`<label key=${field.id} class="sd-color-field">
        <input type="color" value=${colors[field.chart][field.slots[0]]} disabled=${busy}
          onInput=${(e) => set(field, e.target.value)} />
        <span>${field.label}</span></label>`)}</div>
      <p class="vk-muted sd-hint">点色块挑颜色，右边的图会马上变。</p>
    </details>
    ${light.length > 0 && html`<p class="sd-warn" role="status">颜色太浅，柱子可能看不清：${light.map((f) => f.label).join("、")}</p>`}
    ${dirty && html`<p class="sd-warn" role="status">配色已修改，未保存（这次复制、下载照样用新颜色）</p>`}
    <div class="sd-actions">
      <button type="button" class="vk-btn is-primary" disabled=${busy || !dirty} onClick=${onSave}>保存，以后都用这套</button>
      <button type="button" class="vk-btn" disabled=${busy} onClick=${onReset}>恢复默认</button>
    </div>
    <p class="vk-muted sd-hint">保存后，下次打开也是这套颜色；不保存只对这一次有效。</p>
  </details>`;
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
/** 扫描失败的原因码 → 用户能看懂的话（服务端只回稳定的 E_* 码）。 */
const SCAN_REASONS = {
  E_NO_FILE: "目录里没有 .xlsx 或 .txt",
  E_MTIME_TIE: "有两个文件修改时间完全相同，请手动选一份",
  E_FILE_WRITING: "最新那份还在写入（大小或时间在变），请稍后再扫描",
  E_NEWEST_HIDDEN: "最新的是隐藏文件，已跳过；请改成普通文件或手动选",
  E_HEADER_MISMATCH: "最新那份表头与官方 47 列不一致",
  E_ENCRYPTED_WORKBOOK: "最新那份受公司终端加密保护，本功能读不到内容",
  E_WORKBOOK_INVALID: "最新那份读不了（不是有效的 .xlsx）",
  E_TEXT_INVALID: "最新那份文本读不了（请在 Excel 中重新另存为「Unicode 文本」）",
  E_EMPTY_WORKBOOK: "最新那份没有数据行",
  E_REQUIRED_COLUMNS: "最新那份缺少日报必需的列",
  E_SCAN_EXPIRED: "扫描结果已失效，请重新扫描",
  E_SCAN_STALE: "文件在扫描后被改动过，请重新扫描",
  E_DIR_NOT_ALLOWED: "目录不在允许范围内",
  E_DIR_MISSING: "目录不存在",
  E_DIR_UNREADABLE: "目录读不了",
  E_DIR_TOO_MANY: "目录项太多，请先清理",
  E_FILE_GONE: "文件已不存在",
  E_FILE_TOO_LARGE: "文件超过大小上限",
  E_FILE_NOT_REGULAR: "不是普通文件",
};
const reasonText = (code) => SCAN_REASONS[code] || String(code || "");

/** error.diagnostic.reason → 错误框里**补充**的一句说明。
 *  只说正文没说的那部分（不复述提示语本身，避免同一句话显示两遍）；
 *  不显示十六进制、不建议换浏览器/换上传方式。 */
const REASON_NOTES = {
  encrypted_container: "这不是文件损坏，也不需要重新导出。",
  schema_mismatch: "常见原因是导出后删过列或改过列名。",
  text_malformed: "常见原因是导出后用记事本等工具改过内容。",
  // Excel 代读（已开启时）没有成功的原因：只说发生了什么，不显示任何表格内容。
  excel_unavailable: "已尝试让本机 Excel 代读，但这台电脑上启动不了 Excel。",
  excel_cannot_open: "已尝试让本机 Excel 代读，但 Excel 打不开这份文件。",
  timeout: "已尝试让本机 Excel 代读，但在限定时间内没有读完，已停止。若任务管理器里留有后台 EXCEL.EXE，可手动结束。",
  busy: "上一份代读还没结束，请稍后再试。",
  worker_protocol_error: "已尝试让本机 Excel 代读，但读取过程异常中断。",
  path_rejected: "这份文件的位置不允许代读（只接受扫描目录里的普通 .xlsx）。",
  has_formula: "Excel 读到了公式单元格：官方导出件不应含公式，请重新导出。",
  range_not_at_a1: "表格不是从 A1 开始的：请确认是官方原样导出件。",
  too_large: "表格的行数或列数超过上限。",
  cell_error: "表格里有错误值或不支持的单元格类型。",
  unexpected_numeric: "有不该是数字的列被 Excel 当成了数字，为避免编号失真已拒绝。",
};

/** multipart 上传：宿主 api.post 只发 JSON，这里直接 fetch 并解宿主信封。 */
async function postForm(url, formData) {
  let response;
  try {
    response = await fetch(url, { method: "POST", body: formData, headers: { Accept: "application/json" } });
  } catch (_) {
    throw new Error("无法连接本地服务，请确认 VSE Toolbox 仍在运行");
  }
  let payload = null;
  try { payload = await response.json(); } catch (_) { payload = null; }
  if (payload && payload.ok === true) return payload.data;
  const error = (payload && payload.error) || {};
  // 宿主信封里 code 可能在 error.code，也可能只落在 error.type（json_error 的 type 就是码）；
  // reason 只在 error.diagnostic.reason（闭集词）里，用于在错误框里补一句说明。
  const failure = new Error(error.message || `请求失败（HTTP ${response.status}）`);
  failure.code = error.code || error.type || "";
  failure.reason = (error.diagnostic && error.diagnostic.reason) || "";
  throw failure;
}

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
  const [manualFile, setManualFile] = useState(null);
  // 数据截至日期默认填今天（只是前端预填，用户看得见、可以改；后端从不拿导入时间代替）。
  const [manualDate, setManualDate] = useState(() => todayIso());
  const [colors, setColors] = useState(null); // 生效配色（可能还没保存）
  const [colorBusy, setColorBusy] = useState(false);
  const [baselines, setBaselines] = useState([]); // 已存的手工导入（可以「和哪一天比」）
  const [baselineChoice, setBaselineChoice] = useState(""); // "" = 上次导入（自动）
  const [keepBaseline, setKeepBaseline] = useState(true);
  const [baselineBusy, setBaselineBusy] = useState(false);
  const [scan, setScan] = useState(null);
  const fileRef = useRef(null);
  const previewRef = useRef(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = async () => {
    setLoadError(null);
    try {
      const data = await api.get("state");
      setState(data);
      setForm((current) => current || { ...data.form });
      setColors((current) => current || resolveAllPalettes(data.chartColors));
      return data;
    } catch (err) {
      setLoadError(err);
      return null;
    }
  };
  const loadBaselines = async () => {
    try {
      const data = await api.get("manual-baselines");
      setBaselines(data.items || []);
      return data.items || [];
    } catch (_) {
      return null; // 列表拿不到不影响导入：下拉只剩「自动」
    }
  };
  useEffect(() => { load(); loadBaselines(); }, []);
  // 换颜色时只在前端重画已经算好的图，不再请求后端。
  useEffect(() => { if (result && colors) setImages(renderImages(result, colors)); }, [colors]);

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
  // 飞书功能已取消（需求清单 K6）：不再发送飞书链接，已保存的旧值也不进正文。
  const requestBody = () => ({ ...form, ...texts, feishuLink: "" });

  const generate = async () => {
    if (result && result.mode === "manual") {
      flash("当前是手工导入的报告：请重新选文件/扫描目录，或换一份数据源");
      return;
    }
    setPhase("generating");
    try {
      const data = await api.post("generate", requestBody());
      // 结果和三张图一起落定：预览、复制、.eml 用同一张 PNG，预览里也不会出现未替换的 cid: 地址。
      setImages(renderImages(data, effectiveColors));
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

  // 本地报表导入（方案 B）：不碰一键生成的数据；默认和上次导入比每日进展，不提供 .eml。
  const importFromFile = async () => {
    const scanned = scan && scan.selected;
    if (!manualFile && !scanned) {
      flash("请选择要导入的报表文件，或先「扫描目录」挑出最新的一份");
      return;
    }
    if (!manualDate) { flash("请填写这份报表的数据截至日期（不会用导入时间代替）"); return; }
    setPhase("generating");
    setError(null);
    try {
      const body = new FormData();
      if (manualFile) {
        body.append("file", manualFile);
      } else {
        body.append("scanDirId", scan.dirId || "");
        body.append("scanName", scanned.name);
        body.append("scanToken", scanned.token);
      }
      body.append("dataDate", manualDate);
      body.append("projects", JSON.stringify(form.projects || []));
      body.append("departments", JSON.stringify(form.departments || []));
      body.append("region", form.region || "");
      body.append("greeting", texts.greeting || "");
      body.append("planText", texts.planText || "");
      body.append("keepBaseline", keepBaseline ? "1" : "0");
      if (baselineChoice) body.append("baselineDate", baselineChoice);
      const data = await postForm(api.url("import-form"), body);
      setImages(renderImages(data, effectiveColors));
      setResult(data);
      setProceed(false);
      const items = await loadBaselines();
      if (items && baselineChoice && !items.some((item) => item.date === baselineChoice)) setBaselineChoice("");
    } catch (err) {
      setError({ message: err.message, canFallback: false, reason: err.reason || "" });
    } finally {
      setPhase("idle");
    }
  };

  const savedColors = resolveAllPalettes(state.chartColors);
  const effectiveColors = colors || savedColors;
  const saveColors = async () => {
    setColorBusy(true);
    try {
      await api.post("config", { chartColors: effectiveColors });
      await load();
      flash("配色已保存，以后都用这套");
    } catch (err) {
      flash(err.message);
    } finally {
      setColorBusy(false);
    }
  };
  const resetColors = async () => {
    if (!window.confirm("恢复成默认配色并保存？之前保存或刚改的配色都会被替换。")) return;
    const defaults = presetPalettes("default");
    setColorBusy(true);
    try {
      await api.post("config", { chartColors: defaults });
      setColors(defaults);
      await load();
      flash("已恢复默认配色");
    } catch (err) {
      flash(err.message);
    } finally {
      setColorBusy(false);
    }
  };

  const baselineAction = async (path, payload, done) => {
    setBaselineBusy(true);
    try {
      const data = await api.post(`manual-baselines/${path}`, payload);
      setBaselines(data.items || []);
      flash(done);
      return true;
    } catch (err) {
      flash(err.message);
      return false;
    } finally {
      setBaselineBusy(false);
    }
  };
  const pinChoice = () => baselineAction("pin", { date: baselineChoice },
    `已固定：以后导入都和 ${baselineChoice} 比，直到取消固定`);
  const unpin = () => baselineAction("unpin", {}, "已取消固定：以后自动和上次导入比");
  const deleteChoice = async () => {
    const date = baselineChoice;
    if (!window.confirm(`删除 ${date} 的导入记录后，就不能再和这一天比了（你的报表文件不受影响）。确定删除？`)) return;
    if (await baselineAction("delete", { date }, `已删除 ${date} 的导入记录`)) setBaselineChoice("");
  };
  const pinnedItem = baselines.find((item) => item.pinned);
  // 日期是预填的今天：选中的文件不是同一天改的就提醒一句，免得把昨天的报表记成今天。
  const dateHint = fileDateHint(
    manualFile ? manualFile.lastModified : (scan && scan.selected ? scan.selected.mtime : null), manualDate);
  const plan = comparePlan(baselines, {
    dataDate: manualDate, choice: baselineChoice,
    maxGapDays: (state.thresholds && state.thresholds.baselineMaxGapDays) || 14,
  });

  const toggleExcelProxy = async (enabled) => {
    try {
      await api.post("config", { excelProxyEnabled: enabled });
      await load();
      setScan(null);
    } catch (err) {
      flash(err.message);
    }
  };

  const scanDir = async () => {
    try {
      const data = await postForm(api.url("import-scan"), new FormData());
      setScan(data);
      if (data.selected) {
        setManualFile(null);
        if (fileRef.current) fileRef.current.value = "";
      }
      if (data.selected) {
        // 文件的修改时间不会被当成数据日期：日期框里是什么就用什么，请用户自己确认。
        flash(`已挑出最新文件：${data.selected.name}（请确认数据截至日期 ${manualDate || "未填"} 是否正确）`);
      } else {
        flash(`没有可用候选：${reasonText(data.reason) || "目录里没有 .xlsx 或 .txt"}`);
      }
    } catch (err) {
      flash(err.message);
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
  const gate = result ? result.statusGate : null;
  const gateBlocked = Boolean(gate && gate.blocked);
  const gateText = result ? statusGateText(result) : "";
  const copy = async () => {
    try {
      flash(await copyRich(inlineImages(result.html, images), result.text, previewRef.current));
    } catch (err) {
      flash(err.message);
    }
  };
  const eml = async () => {
    if (result && result.mode === "manual") { flash("手工导入的报告不提供 .eml，请复制正文后手动发送"); return; }
    try {
      await downloadEml(api.url("eml"), { ...requestBody(), mode: result.mode || "", images, proceedWithSuggestion: proceed });
    } catch (err) {
      flash(err.message);
    }
  };

  const set = (field) => (value) => setForm({ ...form, [field]: value });
  // 取消孤儿项目（本次数据里没有的历史残留）时，沿用原范围的收件人与文案；
  // 只在新范围还没有记忆时复制，旧范围的记忆保留（TDC-20261029）。
  const migrateScope = async (oldKey, nextKey) => {
    const prefs = migratePrefs(state.preferences, oldKey, nextKey);
    if (!prefs) return;
    try {
      await api.post("config", { preferences: { [nextKey]: prefs } });
      await load();
      flash("已沿用原范围的收件人与文案");
    } catch (err) {
      flash(err.message);
    }
  };
  const setProjects = (next) => {
    const removed = orphanProjects(state.options.projects, form.projects).filter((item) => !next.includes(item));
    const nextKey = scopeKey(next, form.departments, form.watchlistOnly);
    setForm({ ...form, projects: next });
    if (removed.length) migrateScope(key, nextKey);
  };
  const setText = (field) => (e) => setTexts({ ...texts, [field]: e.target.value });
  const dataTime = state.data ? formatTime(state.data.snapshotAt) : "暂无";
  const watch = state.watchlist;

  return html`<div class="vk-page sd-page">
    <header class="vk-page-header">
      <div><h2>3D 单签署日报</h2>
        <p class="vk-muted" style="margin:4px 0 0">选好车型和科室 → 一键生成（会先自动刷新 TDC 数据）→ 复制正文或生成邮件草稿</p></div>
      <div class="vk-page-actions">
        ${toast && html`<span class="sd-toast" role="status">${toast}</span>`}
        <span class="vk-muted">数据时间：${dataTime}${state.data && state.data.coverage === "watchlist" ? "（仅关注清单）" : ""}</span>
      </div>
    </header>

    <div class="sd-layout">
    <div class="sd-side">
    <section class="sd-form">
      <div class="sd-field"><span>项目 / 车型</span>
        <${Chips} options=${state.options.projects} orphans=${state.data ? orphanProjects(state.options.projects, form.projects) : []}
          value=${form.projects} onChange=${setProjects} emptyText="还没有数据，先点「一键生成」" /></div>
      <div class="sd-field"><span>科室</span>
        <${Chips} options=${state.options.departments} value=${form.departments} onChange=${set("departments")} emptyText="—" /></div>
      <label class="sd-check"><input type="checkbox" checked=${form.watchlistOnly}
        onChange=${() => set("watchlistOnly")(!form.watchlistOnly)} />只统计关注清单（${watch.count} 份）</label>
      <div class="sd-actions">
        <button type="button" class="vk-btn is-primary sd-main-btn" disabled=${busy} onClick=${oneClick}>⚡ 一键生成</button>
        <button type="button" class="vk-btn" disabled=${busy || !state.data} onClick=${generate}>用现有数据生成</button>
      </div>
      ${phase === "refreshing" && html`<p class="sd-progress" role="status">${task && task.reused ? "已有抓取在运行，沿用它：" : ""}${stageText(task) || "正在提交抓取任务…"}</p>`}
      ${phase === "generating" && html`<p class="sd-progress" role="status">正在生成…</p>`}
      ${state.dataError && !state.data && html`<p class="vk-muted">${state.dataError}</p>`}
      ${error && html`<div class="vk-state is-error" role="alert">
        <span>${error.message}</span>
        ${error.reason && REASON_NOTES[error.reason]
          && !String(error.message || "").includes(REASON_NOTES[error.reason])
          && html`<span class="vk-muted">${REASON_NOTES[error.reason]}</span>`}
        ${error.canFallback && state.data && html`<button type="button" class="vk-btn" onClick=${generate}>用最近一次数据生成（${dataTime}）</button>`}
      </div>`}
      <details class="sd-import">
        <summary>用本地导出的报表生成（自动和上次导入比，看每日进展）</summary>
        <p class="vk-muted sd-import-hint">文件必须是 TDC「数模设计审核流程」原样导出的 .xlsx（47 列表头）。数据日期请自己确认——程序不会用导入时间、文件修改时间或「申请日期」推断。</p>
        <p class="vk-muted sd-import-hint">如果 .xlsx 提示受终端加密保护：用 Excel 打开它，「另存为」选「Unicode 文本(*.txt)」，再选这份 .txt 导入（不要手工改内容）。</p>
        ${state.excelProxy && html`<p class="vk-muted sd-import-hint">
          <label><input type="checkbox"
            checked=${!!state.excelProxy.enabled}
            disabled=${busy || !state.excelProxy.authorized}
            onChange=${(e) => toggleExcelProxy(e.target.checked)} />
            加密的 xlsx 由本机 Excel 代读（只对扫描目录里的文件生效）</label>
          　${state.excelProxy.text}</p>`}
        ${state.importDir && html`<p class="sd-import-hint">
          扫描目录（把报表放进这个文件夹，再点「扫描目录」）：<b class="sd-path">${state.importDir}</b>
          ${state.excelProxy && state.excelProxy.status === "ok" && html`<br />
            <b>加密的 xlsx 只能放进上面这个文件夹由 Excel 代读；用下面的「报表文件」上传不会代读。</b>`}</p>`}
        <label class="sd-field"><span>报表文件</span>
          <input type="file" accept=".xlsx,.txt"
            ref=${fileRef}
            onChange=${(e) => {
              setManualFile((e.target.files && e.target.files[0]) || null);
              setScan(null);
            }} /></label>
        <label class="sd-field"><span>数据截至日期</span>
          <input type="date" value=${manualDate} onInput=${(e) => setManualDate(e.target.value)} /></label>
        <p class="vk-muted sd-import-hint">已预填今天；如果这份报表不是今天导出的，请改成导出那天。</p>
        ${dateHint && html`<p class="sd-warn" role="status">${dateHint}</p>`}
        <label class="sd-check"><input type="checkbox" checked=${keepBaseline}
          onChange=${() => setKeepBaseline(!keepBaseline)} />留作下次对比</label>
        <p class="vk-muted sd-import-hint">勾上后，明天导入就能看到比今天进展了多少。</p>
        <details class="sd-compare">
          <summary>更多：指定和哪一天比</summary>
          <label class="sd-field"><span>和哪一天比</span>
            <select value=${baselineChoice} disabled=${busy || baselineBusy}
              onChange=${(e) => setBaselineChoice(e.target.value)}>
              ${baselineOptions(baselines).map((item) => html`<option key=${item.value} value=${item.value}>${item.label}</option>`)}
            </select></label>
          <p class="vk-muted sd-import-hint">选「上次导入（自动）」最省事；选了某一天，这次就只和那一天比。</p>
          <div class="sd-actions">
            <button type="button" class="vk-btn" disabled=${busy || baselineBusy || !baselineChoice} onClick=${pinChoice}>固定和这一天比</button>
            <button type="button" class="vk-btn" disabled=${busy || baselineBusy || !pinnedItem} onClick=${unpin}>取消固定</button>
            <button type="button" class="vk-btn" disabled=${busy || baselineBusy || !baselineChoice} onClick=${deleteChoice}>删除</button>
          </div>
          <p class="vk-muted sd-import-hint">
            ${pinnedItem ? `现在固定和 ${pinnedItem.date} 比；「取消固定」后改回自动。` : "「固定」后，以后每次导入都和这一天比，直到取消固定。"}
            「删除」只删程序里记下的那天的数据，不动你的文件。</p>
          <p class="vk-muted sd-import-hint">两天导出时 TDC 的筛选条件要一样，否则少掉的单会显示为「消失」。</p>
        </details>
        <p class=${`sd-plan-line is-${plan.tone}`} role="status">${plan.text}</p>
        <div class="sd-actions">
          <button type="button" class="vk-btn" disabled=${busy} onClick=${scanDir}>扫描目录</button>
          <button type="button" class="vk-btn is-primary" disabled=${busy} onClick=${importFromFile}>用这份报表生成</button>
        </div>
        ${scan && html`<div class="sd-scan">
          <p class="vk-muted">实际扫描的文件夹：<b class="sd-path">${scan.dirPath || scan.dir}</b>　${scan.hint}</p>
          ${scan.reason === "E_NO_FILE" && html`<p class="sd-scan-stop">
            这个文件夹里没有可用的报表。请确认文件放进的正是上面这个路径
            （注意文件夹名是 sign-daily，不是程序目录里的 sign_daily）。</p>`}
          ${scan.selected
            ? html`<p>已选中最新：<b>${scan.selected.name}</b>（修改时间 ${formatTime(scan.selected.mtime)}，内容摘要 ${scan.selected.sha256 || ""}）${scan.selected.viaExcel ? "　受终端加密，生成时由本机 Excel 代读" : ""}</p>`
            : html`<p class="sd-scan-stop">没有自动选中：${reasonText(scan.reason)}</p>`}
          <p class="vk-muted">将使用：${manualFile ? `手动选择的 ${manualFile.name}` : (scan.selected ? `扫描到的 ${scan.selected.name}` : "（还没有选定数据源）")}</p>
          <ul class="sd-scan-list" aria-label="候选文件">
            ${(scan.entries || []).slice(0, 8).map((entry) => html`<li key=${entry.name}>
              ${entry.ok ? "合格" : "不合格"} ${entry.name}　${entry.mtime ? formatTime(entry.mtime) : ""}　${reasonText(entry.reason)}
            </li>`)}
          </ul>
          ${(scan.entries || []).length > 8 && html`<p class="vk-muted">共 ${scan.entries.length} 项，只显示前 8 项。</p>`}
          ${!scan.selected && html`<p class="vk-muted">
            按口径不会自动退回更旧的文件：请修好最新那份，或直接用上面的「报表文件」手动选一份。</p>`}
        </div>`}
      </details>

      <details class="sd-mail-options">
        <summary>邮件内容（可选）：区域、称呼、计划说明</summary>
        <label class="sd-field"><span>区域名</span>
          <input value=${form.region} onInput=${(e) => set("region")(e.target.value)} /></label>
        <label class="sd-field"><span>称呼</span><input value=${texts.greeting} onInput=${setText("greeting")} /></label>
        <label class="sd-field"><span>计划/超期说明</span>
          <textarea rows="2" placeholder="如：计划10-10发布，已超期x天" value=${texts.planText} onInput=${setText("planText")}></textarea></label>
      </details>
    </section>
    <${ChartColors} colors=${effectiveColors} saved=${savedColors} busy=${colorBusy}
      onChange=${setColors} onSave=${saveColors} onReset=${resetColors} />
    <${SettingsPanel} api=${api} state=${state} onSaved=${load}
      onChanged=${() => { if (result && result.mode !== "manual") generate(); }} />
    </div>

    <div class="sd-main">
    ${!result && html`<section class="sd-empty"><div class="sd-empty-icon" aria-hidden="true">📊</div>
      <p>选好条件后点「一键生成」，这里会显示日报预览。</p></section>`}
    ${result && html`<section class="sd-result">
      ${result.mode === "manual" && html`<div class="sd-notice is-manual">
        手工导入｜${result.importMeta.sourceName}｜数据截至日期 ${result.importMeta.dataDate}（用户确认，未经系统核验）｜
        参与计算 ${result.importMeta.rowCount} 行｜${result.importMeta.baselineStatement || ""}
        <br /><b>${compareResultText(result.importMeta)}</b>
        ${result.importMeta.reportDigest && html`<br />正文指纹 ${result.importMeta.reportDigest}
          （同一份数据、同样的条件，换一种导入方式或有没有对比，指纹都应当相同）`}
      </div>`}
      ${result.stale && result.mode !== "manual" && html`<div class="sd-notice is-stale">用的是旧数据（数据时间 ${formatTime(result.snapshotAt)}），不写快照，不显示日变化。</div>`}
      ${result.notices.map((n) => html`<div key=${n.kind} class=${`sd-notice${n.blocking ? " is-blocking" : ""}`}>${n.text}</div>`)}
      ${gateText && html`<div class=${`sd-notice${gateBlocked ? " is-blocking" : ""}`}
        role=${gateBlocked ? "alert" : "status"}>${gateText}</div>`}
      ${result.mode === "manual"
        ? (result.longCycle.review.length > 0 && html`<div class="sd-notice is-manual">
            长周期初筛 ${result.longCycle.review.length} 项：手工导入模式不提供「确认并记住」（不写入记录），请人工判断；
            清单已写进正文，确认后可复制
            ${!proceed && html`<button type="button" class="vk-btn" onClick=${() => setProceed(true)}>
              本次按建议继续</button>`}
          </div>`)
        : html`<${LongCycleReview} key=${result.longCycle.review.map((i) => i.normalized).join("|")}
            longCycle=${result.longCycle} onConfirm=${confirmLongCycle}
            onProceed=${() => setProceed(true)} proceeding=${proceed} />`}
      <div class="sd-preview-bar">
        <div><b>主题：</b>${result.subject}<br /><span class="vk-muted">数据日期 ${result.dataDate}${result.baseDate ? `；日变化基线 ${result.baseDate}` : ""}</span></div>
        <div class="sd-actions">
          <button type="button" class="vk-btn is-primary" disabled=${!canExport} onClick=${copy}>复制正文</button>
          <button type="button" class="vk-btn" disabled=${!canExport || result.mode === "manual"} onClick=${eml}>下载 .eml 草稿</button>
          ${result.mode === "manual" && html`<span class="vk-muted">手工导入的报告不提供 .eml，请复制正文</span>`}
          ${!canExport && html`<span class="vk-muted">${gateBlocked ? "状态列是数字码，禁止发送" : "长周期初筛待确认，确认后才能复制和下载"}</span>`}
        </div>
      </div>
      <${Recipients} key=${result.scopeKey + result.recipientsText.to + result.recipientsText.cc} result=${result}
        onSave=${(names) => (result.mode === "manual" ? flash("手工导入模式不保存名单") : savePrefs(names))} />
      <${ChartTools} images=${images} onMessage=${flash} />
      <div class="sd-preview" ref=${previewRef}>
        ${gateBlocked && html`<div class="sd-preview-warning">状态列是数字码，本页数字不可直接引用；手工复制也会带上这条提示。</div>`}
        <div dangerouslySetInnerHTML=${{ __html: inlineImages(result.html, images) }}></div>
      </div>
    </section>`}
    </div>
    </div>
  </div>`;
}
