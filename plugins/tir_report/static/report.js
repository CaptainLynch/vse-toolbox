// TIR数据简表：参数 → 后台导出 → 进度 → 下载帆软原样导出的 Excel。共享运行时与 UI Kit 来自宿主。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { DataTable, StateBlock } from "/static/host/kit.js";

const POLL_MS = 1500;
const STAGES = { login: "登录帆软", save: "保存文件", done: "完成" };

function Field({ label, children }) {
  return html`<label class="vk-field" style="display:flex;flex-direction:column;gap:4px;min-width:160px">
    <span>${label}</span>${children}</label>`;
}

function fileLink(api, item) {
  return html`<a href=${api.url(`files/${item.day}/${item.file}`)}>下载 Excel</a>`;
}

export default function Page({ api }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null);
  const [ref, setRef] = useState("");
  const [task, setTask] = useState(null);
  const [message, setMessage] = useState("");
  const timer = useRef(null);

  async function load() {
    try {
      const data = await api.get("state");
      setState(data);
      setRef(data.config.credentialRef || "");
      setForm((prev) => prev || { ...data.config.defaults, endDate: data.today, force: false });
      setError(null);
    } catch (err) {
      setError(err);
    }
  }
  useEffect(() => { load(); return () => clearTimeout(timer.current); }, []);

  async function poll(taskId) {
    try {
      const view = await api.get(`export/${taskId}`);
      setTask(view);
      if (view.status === "queued" || view.status === "running") {
        timer.current = setTimeout(() => poll(taskId), POLL_MS);
      } else {
        load();
      }
    } catch (err) {
      setMessage(err.message);
    }
  }

  async function saveRef() {
    try {
      await api.post("config", { credentialRef: ref, defaults: { project: form.project, department: form.department, section: form.section, startDate: form.startDate } });
      setMessage("已保存");
      load();
    } catch (err) {
      setMessage(err.message);
    }
  }

  async function start() {
    setMessage("");
    try {
      const started = await api.post("export", form);
      setTask(started);
      if (started.taskId && !started.result) poll(started.taskId);
      else load();
    } catch (err) {
      setMessage(err.message);
    }
  }

  if (!state || !form) return html`<${StateBlock} loading=${!error} error=${error} onRetry=${load} />`;
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const running = task && (task.status === "queued" || task.status === "running");
  const columns = [
    { key: "day", title: "导出日" },
    { key: "filters", title: "筛选", sortable: false, format: (_, row) => row.filters ? `${row.filters.project} / ${row.filters.department || "全部部门"} / ${row.filters.startDate} ~ ${row.filters.endDate}` : "" },
    { key: "rows", title: "行数" },
    { key: "headerCheck", title: "表头", sortable: false, format: (_, row) => row.headerCheck ? (row.headerCheck.ok ? "50 列一致" : `不一致（${row.headerCheck.columns} 列）`) : "" },
    { key: "file", title: "下载", sortable: false, format: (_, row) => fileLink(api, row) },
  ];

  return html`<div class="vk-page">
    <header class="vk-page-header"><h2>TIR数据简表</h2>
      <p class="vk-muted">从帆软报表平台导出「${state.report.path}」，交付帆软原样导出的 Excel。账号口令只从 Windows 凭据管理器读取。</p></header>
    <section class="vk-card" style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end">
      <${Field} label="凭据条目名（credential_ref）">
        <input value=${ref} placeholder="例如 VSE/report.sgmw" onInput=${(e) => setRef(e.target.value)} /></${Field}>
      <button class="vk-btn" onClick=${saveRef}>保存条目名与默认筛选</button>
    </section>
    <section class="vk-card" style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-top:12px">
      <${Field} label="项目"><input value=${form.project} onInput=${set("project")} /></${Field}>
      <${Field} label="部门"><input value=${form.department} onInput=${set("department")} /></${Field}>
      <${Field} label="科室（选填）"><input value=${form.section} onInput=${set("section")} /></${Field}>
      <${Field} label="发放开始日期"><input type="date" value=${form.startDate} onInput=${set("startDate")} /></${Field}>
      <${Field} label="发放结束日期"><input type="date" value=${form.endDate} onInput=${set("endDate")} /></${Field}>
      <label><input type="checkbox" checked=${form.force} onChange=${set("force")} /> 忽略当天已有结果重新导出</label>
      <button class="vk-btn vk-btn-primary" disabled=${running} onClick=${start}>${running ? "导出中…" : "导出"}</button>
    </section>
    ${task && html`<p class="vk-muted">${task.reused ? "复用：" : ""}${task.status === "failed" ? `失败：${task.error || ""}` :
      task.status === "succeeded" ? `完成${task.result && task.result.rows != null ? `（${task.result.rows} 行）` : ""}` :
      `${STAGES[task.stage] || "排队中"} ${task.percent ?? 0}%`}</p>`}
    ${message && html`<p class="vk-muted">${message}</p>`}
    <h3 style="margin-top:16px">产物</h3>
    <${DataTable} columns=${columns} rows=${state.exports.map((item) => ({ ...item, key: `${item.day}/${item.stem}` }))} rowKey="key" emptyText="还没有导出过" />
  </div>`;
}
