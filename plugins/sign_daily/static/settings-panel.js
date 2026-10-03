// 签署日报「设置」：花名册、长周期规则与词表、长周期结论、未在册人员区域、区域显示名、通讯录与阈值（规格 §7、§8）。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import {
  decodeCsv, formatPairs, formatSynonyms, lines, parsePairs, parseSynonyms,
} from "./report-logic.js";

const TABS = [
  ["roster", "花名册"], ["rules", "长周期规则"], ["vocabulary", "长周期词表"], ["conclusions", "长周期结论"],
  ["people", "未在册人员与区域名"], ["mail", "通讯录与阈值"],
];

function useAsync() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const run = async (fn, done) => {
    setBusy(true);
    setMessage("");
    try {
      const value = await fn();
      if (done) setMessage(typeof done === "function" ? done(value) : done);
      return value;
    } catch (err) {
      setMessage(err.message || "操作失败");
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { busy, message, run, setMessage };
}

/** 导入（选文件、校验、差异预览、确认、单事务提交并备份）、导出、备份恢复、恢复内置种子（M5–M7）。 */
function ImportExport({ api, dataset, view, onView, onChanged }) {
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState("");
  const [replace, setReplace] = useState(false);
  const [skip, setSkip] = useState(false);
  const [plan, setPlan] = useState(null);
  const op = useAsync();
  const pick = async (event) => {
    const file = event.currentTarget.files && event.currentTarget.files[0];
    if (!file) return;
    if (!/\.csv$/i.test(file.name)) {
      op.setMessage("请选择 CSV 文件；xlsx 请先另存为 CSV（UTF-8 或 GBK 都可以）");
      return;
    }
    setFileName(file.name);
    setCsv(decodeCsv(await file.arrayBuffer()));
    setPlan(null);
  };
  const preview = () => op.run(async () => {
    const data = await api.post(`settings/${dataset}/import`, { csv, replace, commit: false });
    setPlan(data.plan);
  });
  const commit = () => op.run(async () => {
    const data = await api.post(`settings/${dataset}/import`, { csv, replace, commit: true, skipErrors: skip });
    setPlan(null);
    setCsv("");
    setFileName("");
    onView(data.view);
    onChanged();
  }, "已导入，旧数据已自动备份");
  const restore = (id) => op.run(async () => { onView(await api.post(`settings/${dataset}/restore`, { backupId: id })); onChanged(); }, "已恢复");
  const reset = () => {
    if (!window.confirm("恢复内置种子会清空本地改动（会先自动备份），确定吗？")) return;
    op.run(async () => { onView(await api.post(`settings/${dataset}/reset`, {})); onChanged(); }, "已恢复内置种子");
  };
  const list = (items, render) => html`<details><summary>${items.length} 条</summary><ul class="sd-plain-list">${items.map(render)}</ul></details>`;
  return html`<section class="sd-import">
    <h5>导入、导出与备份</h5>
    <div class="sd-actions">
      <label class="vk-btn">选择 CSV<input type="file" accept=".csv,text/csv" hidden onChange=${pick} /></label>
      <span class="vk-muted">${fileName}</span>
      <label><input type="radio" checked=${!replace} onChange=${() => setReplace(false)} />合并更新</label>
      <label><input type="radio" checked=${replace} onChange=${() => setReplace(true)} />整体覆盖（种子层停用）</label>
      <button type="button" class="vk-btn" disabled=${op.busy || !csv} onClick=${preview}>校验并预览差异</button>
      <a class="vk-btn" href=${api.url(`settings/${dataset}.csv`)} download=${`${dataset}.csv`}>导出 CSV</a>
      <button type="button" class="vk-btn" disabled=${op.busy} onClick=${reset}>恢复内置种子</button>
    </div>
    ${plan && html`<div class="sd-plan">
      <p>新增 ${plan.counts.added}、变更 ${plan.counts.changed}、删除 ${plan.counts.removed}、冲突 ${plan.counts.conflicts}、错误 ${plan.counts.errors}${plan.merged ? `；同名同科室合并 ${plan.merged} 人` : ""}</p>
      ${plan.added.length > 0 && html`<div>新增 ${list(plan.added, (i) => html`<li key=${i.name || i.id}>${i.name}${i.department ? ` · ${i.department}` : ""}</li>`)}</div>`}
      ${plan.changed.length > 0 && html`<div>变更 ${list(plan.changed, (i) => html`<li key=${i.name || i.id}>${i.name || i.id}：${JSON.stringify(i.from)} → ${JSON.stringify(i.to)}</li>`)}</div>`}
      ${plan.removed.length > 0 && html`<div>删除 ${list(plan.removed, (i) => html`<li key=${i.name || i.id}>${i.name}</li>`)}</div>`}
      ${plan.conflicts.length > 0 && html`<div>冲突（同名不同科室，默认不导入）${list(plan.conflicts, (i) => html`<li key=${i.name}>${i.name}：${i.departments.join("、")}</li>`)}</div>`}
      ${plan.errors.length > 0 && html`<div>错误行 ${list(plan.errors, (i) => html`<li key=${i.line}>第 ${i.line} 行：${i.text}</li>`)}
        <label><input type="checkbox" checked=${skip} onChange=${() => setSkip(!skip)} />跳过错误行导入</label></div>`}
      <div class="sd-actions">
        <button type="button" class="vk-btn is-primary" disabled=${op.busy || (plan.errors.length > 0 && !skip)} onClick=${commit}>确认导入</button>
        <button type="button" class="vk-btn" onClick=${() => setPlan(null)}>全部取消</button>
      </div>
    </div>`}
    ${view.backups && view.backups.length > 0 && html`<details><summary>最近 ${view.backups.length} 份备份</summary>
      <ul class="sd-plain-list">${view.backups.map((b) => html`<li key=${b.id}>#${b.id} ${b.createdAt} ${b.reason}
        <button type="button" class="vk-btn" disabled=${op.busy} onClick=${() => restore(b.id)}>恢复</button></li>`)}</ul></details>`}
    ${op.message && html`<p class="vk-muted" role="status">${op.message}</p>`}
  </section>`;
}

function RosterTab({ api, onChanged }) {
  const [view, setView] = useState(null);
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState({ name: "", department: "车身科" });
  const op = useAsync();
  useEffect(() => { api.get("settings/roster").then(setView).catch((err) => op.setMessage(err.message)); }, []);
  if (!view) return html`<p class="vk-muted">${op.message || "加载中…"}</p>`;
  const save = (payload, done) => op.run(async () => { setView(await api.post("settings/roster/person", payload)); onChanged(); }, done);
  const revert = (name) => op.run(async () => { setView(await api.post("settings/roster/revert", { name })); onChanged(); }, "已撤销本地改动");
  const shown = view.rows.filter((row) => !filter || row.name.includes(filter) || row.department.includes(filter)).slice(0, 200);
  return html`<div class="sd-settings-tab">
    <p class="vk-muted">共 ${view.rows.length} 人${view.mode === "replace" ? "（整体覆盖模式：内置种子已停用）" : ""}。只存姓名和科室；匹配只用姓名。</p>
    ${view.conflicts.length > 0 && html`<p class="sd-warn">种子升级后和本地都改过（本地优先）：${view.conflicts.map((c) => `${c.key}（种子 ${c.seed || "无"}，本地 ${c.local || "删除"}）`).join("、")}</p>`}
    <div class="sd-actions">
      <input placeholder="搜索姓名或科室" value=${filter} onInput=${(e) => setFilter(e.target.value)} />
      <input placeholder="新增姓名" value=${draft.name} onInput=${(e) => setDraft({ ...draft, name: e.target.value })} />
      <select value=${draft.department} onChange=${(e) => setDraft({ ...draft, department: e.target.value })}>
        ${view.departments.map((d) => html`<option key=${d} value=${d}>${d}</option>`)}
      </select>
      <button type="button" class="vk-btn" disabled=${op.busy || !draft.name.trim()}
        onClick=${() => save({ name: draft.name, department: draft.department }, "已保存")}>新增 / 修改</button>
    </div>
    <table class="sd-table"><thead><tr><th>姓名</th><th>科室</th><th>来源</th><th></th></tr></thead><tbody>
      ${shown.map((row) => html`<tr key=${row.name} class=${row.source === "已删除" ? "is-deleted" : ""}>
        <td>${row.name}</td>
        <td><select value=${row.department} disabled=${op.busy || row.source === "已删除"}
          onChange=${(e) => save({ name: row.name, department: e.target.value }, "已保存")}>
          ${view.departments.map((d) => html`<option key=${d} value=${d}>${d}</option>`)}</select></td>
        <td><span class="sd-tag">${row.source}</span></td>
        <td>${row.source === "已删除" || row.source === "已修改"
          ? html`<button type="button" class="vk-btn" disabled=${op.busy} onClick=${() => revert(row.name)}>撤销</button>`
          : html`<button type="button" class="vk-btn" disabled=${op.busy} onClick=${() => save({ name: row.name, department: null }, "已删除")}>删除</button>`}</td>
      </tr>`)}
    </tbody></table>
    ${view.rows.length > shown.length && html`<p class="vk-muted">只显示前 ${shown.length} 条，请用搜索缩小范围。</p>`}
    ${op.message && html`<p class="vk-muted" role="status">${op.message}</p>`}
    <${ImportExport} api=${api} dataset="roster" view=${view} onView=${setView} onChanged=${onChanged} />
  </div>`;
}

function RulesTab({ api, onChanged }) {
  const [view, setView] = useState(null);
  const [draft, setDraft] = useState({ id: "", name: "", remark: "", aliases: "", enabled: true });
  const op = useAsync();
  useEffect(() => { api.get("settings/rules").then(setView).catch((err) => op.setMessage(err.message)); }, []);
  if (!view) return html`<p class="vk-muted">${op.message || "加载中…"}</p>`;
  const save = (payload, done) => op.run(async () => { setView(await api.post("settings/rules/rule", payload)); onChanged(); }, done);
  const revert = (id) => op.run(async () => { setView(await api.post("settings/rules/revert", { id })); onChanged(); }, "已撤销本地改动");
  return html`<div class="sd-settings-tab">
    <p class="vk-muted">一行对应清单一项；名称用「/」写并列叫法，备注写「非A、B」作为排除词，别名用顿号分隔。改动后已有的人工结论不变，新命中且没结论的零件会重新进入复核。</p>
    ${view.conflicts.length > 0 && html`<p class="sd-warn">种子升级后和本地都改过（本地优先）：${view.conflicts.map((c) => c.key).join("、")}</p>`}
    <div class="sd-actions">
      <input placeholder="规则编号（新增可留空）" value=${draft.id} onInput=${(e) => setDraft({ ...draft, id: e.target.value })} />
      <input placeholder="零件名称" value=${draft.name} onInput=${(e) => setDraft({ ...draft, name: e.target.value })} />
      <input placeholder="备注，如 非加强板、横梁" value=${draft.remark} onInput=${(e) => setDraft({ ...draft, remark: e.target.value })} />
      <input placeholder="别名" value=${draft.aliases} onInput=${(e) => setDraft({ ...draft, aliases: e.target.value })} />
      <button type="button" class="vk-btn" disabled=${op.busy || !draft.name.trim()}
        onClick=${() => save(draft, "已保存")}>新增 / 修改</button>
    </div>
    <table class="sd-table"><thead><tr><th>编号</th><th>零件名称</th><th>备注</th><th>别名</th><th>启用</th><th>来源</th><th></th></tr></thead><tbody>
      ${view.rows.map((row) => html`<tr key=${row.id} class=${row.source === "已删除" ? "is-deleted" : ""}>
        <td>${row.id}</td><td>${row.name}</td><td>${row.remark}</td><td>${row.aliases}</td>
        <td><input type="checkbox" checked=${row.enabled} disabled=${op.busy || row.source === "已删除"}
          onChange=${() => save({ id: row.id, name: row.name, remark: row.remark, aliases: row.aliases, enabled: !row.enabled }, "已保存")} /></td>
        <td><span class="sd-tag">${row.source}</span></td>
        <td>
          <button type="button" class="vk-btn" onClick=${() => setDraft({ id: row.id, name: row.name, remark: row.remark, aliases: row.aliases, enabled: row.enabled })}>编辑</button>
          ${row.source === "已删除" || row.source === "已修改"
            ? html`<button type="button" class="vk-btn" disabled=${op.busy} onClick=${() => revert(row.id)}>撤销</button>`
            : html`<button type="button" class="vk-btn" disabled=${op.busy} onClick=${() => save({ id: row.id, delete: true }, "已删除")}>删除</button>`}
        </td>
      </tr>`)}
    </tbody></table>
    ${op.message && html`<p class="vk-muted" role="status">${op.message}</p>`}
    <${ImportExport} api=${api} dataset="rules" view=${view} onView=${setView} onChanged=${onChanged} />
  </div>`;
}

function VocabularyTab({ api, onChanged }) {
  const [view, setView] = useState(null);
  const [text, setText] = useState(null);
  const op = useAsync();
  const fill = (data) => {
    setView(data);
    setText({
      globalExcludes: data.vocabulary.globalExcludes.join("\n"),
      synonyms: formatSynonyms(data.vocabulary.synonyms),
      orientation: data.vocabulary.orientation,
      suffixes: data.vocabulary.suffixes.join("\n"),
    });
  };
  useEffect(() => { api.get("settings/vocabulary").then(fill).catch((err) => op.setMessage(err.message)); }, []);
  if (!view || !text) return html`<p class="vk-muted">${op.message || "加载中…"}</p>`;
  const save = () => op.run(async () => {
    fill(await api.post("settings/vocabulary", { vocabulary: {
      globalExcludes: lines(text.globalExcludes), synonyms: parseSynonyms(text.synonyms),
      orientation: text.orientation, suffixes: lines(text.suffixes),
    } }));
    onChanged();
  }, "已保存（旧词表已自动备份）");
  const reset = () => op.run(async () => { fill(await api.post("settings/vocabulary/reset", {})); onChanged(); }, "已恢复默认词表");
  const field = (key, label, rows) => html`<label class="sd-field">${label}
    <textarea rows=${rows} value=${text[key]} onInput=${(e) => setText({ ...text, [key]: e.target.value })}></textarea></label>`;
  return html`<div class="sd-settings-tab sd-grid-2">
    ${field("globalExcludes", "全局排除词（每行一个）", 8)}
    ${field("synonyms", "同义词（每行「规范词=别名、别名」）", 8)}
    <label class="sd-field">方位字<input value=${text.orientation} onInput=${(e) => setText({ ...text, orientation: e.target.value })} /></label>
    ${field("suffixes", "后缀白名单（每行一个）", 8)}
    <div class="sd-actions">
      <button type="button" class="vk-btn is-primary" disabled=${op.busy} onClick=${save}>保存词表</button>
      <button type="button" class="vk-btn" disabled=${op.busy} onClick=${reset}>恢复默认</button>
      ${op.message && html`<span class="vk-muted" role="status">${op.message}</span>`}
    </div>
  </div>`;
}

function ConclusionsTab({ api, projects, onChanged }) {
  const [known, setKnown] = useState([]);
  const [project, setProject] = useState("");
  const [items, setItems] = useState([]);
  const op = useAsync();
  useEffect(() => { api.get("long-cycle").then((data) => setKnown(data.projects || [])).catch(() => {}); }, []);
  const choices = [...new Set([...known, ...projects])].sort();
  const load = (value) => {
    setProject(value);
    if (value) op.run(async () => setItems((await api.get("long-cycle", { query: { project: value } })).items));
  };
  const flip = (item) => op.run(async () => {
    await api.post("long-cycle", { project, items: [{ key: item.key, include: !item.include }] });
    setItems((await api.get("long-cycle", { query: { project } })).items);
    onChanged();
  }, "已改判");
  const clear = () => {
    if (!window.confirm(`清空「${project}」的长周期结论？清空后下次生成会重新提示复核。`)) return;
    op.run(async () => { await api.post("long-cycle/clear", { project }); setItems([]); onChanged(); }, "已清空");
  };
  return html`<div class="sd-settings-tab">
    <div class="sd-actions">
      <select value=${project} onChange=${(e) => load(e.target.value)}>
        <option value="">选择项目</option>${choices.map((p) => html`<option key=${p} value=${p}>${p}</option>`)}
      </select>
      <button type="button" class="vk-btn" disabled=${!project || op.busy} onClick=${clear}>清空该项目的记忆</button>
      ${op.message && html`<span class="vk-muted" role="status">${op.message}</span>`}
    </div>
    ${project && html`<table class="sd-table"><thead><tr><th>零件（规范化名称）</th><th>结论</th><th>当时的自动结果</th><th>规则</th><th>确认时间</th><th></th></tr></thead><tbody>
      ${items.map((item) => html`<tr key=${item.key}><td>${item.key}</td><td>${item.include ? "纳入" : "不纳入"}</td>
        <td>${item.autoResult}</td><td>${item.rule}</td><td>${item.decidedAt}</td>
        <td><button type="button" class="vk-btn" disabled=${op.busy} onClick=${() => flip(item)}>改判</button></td></tr>`)}
    </tbody></table>`}
  </div>`;
}

function PeopleTab({ api, state, onSaved }) {
  const [areas, setAreas] = useState(formatPairs(state.personAreas));
  const [names, setNames] = useState({ ...state.areaNames });
  const op = useAsync();
  const save = () => op.run(async () => {
    await api.post("config", { personAreas: parsePairs(areas), areaNames: names });
    await onSaved();
  }, "已保存");
  return html`<div class="sd-settings-tab sd-grid-2">
    <label class="sd-field">未在册人员指定区域（A11，每行「姓名=区域」；指定后他在所有会签列的欠账都归到这个区域）
      <textarea rows="8" value=${areas} onInput=${(e) => setAreas(e.target.value)}></textarea></label>
    <div class="sd-field"><span>外部会签列的区域显示名（角色列配置）</span>
      <div class="sd-role-grid">${state.externalColumns.map((column) => html`<label key=${column}>${column}
        <input value=${names[column] || ""} placeholder=${column} onInput=${(e) => setNames({ ...names, [column]: e.target.value })} /></label>`)}</div>
    </div>
    <div class="sd-actions"><button type="button" class="vk-btn is-primary" disabled=${op.busy} onClick=${save}>保存</button>
      ${op.message && html`<span class="vk-muted" role="status">${op.message}</span>`}</div>
  </div>`;
}

function MailTab({ api, state, onSaved }) {
  const [book, setBook] = useState(state.addressBook || "");
  const [thresholds, setThresholds] = useState({ ...state.thresholds });
  const op = useAsync();
  const num = (key) => (e) => setThresholds({ ...thresholds, [key]: parseInt(e.target.value, 10) || 0 });
  const save = () => op.run(async () => { await api.post("config", { addressBook: book, thresholds }); await onSaved(); }, "已保存");
  return html`<div class="sd-settings-tab">
    <label class="sd-field">通讯录（当天有欠账且在通讯录里的人自动加进收件人；同名多个邮箱时不自动加入）
      <textarea rows="6" placeholder='"张三"<zhangsan@example.com>; "李四"<lisi@example.com>' value=${book} onInput=${(e) => setBook(e.target.value)}></textarea></label>
    <div class="sd-actions">
      <label>预警天数 <input type="number" min="1" value=${thresholds.warnDays} onInput=${num("warnDays")} /></label>
      <label>超期天数 <input type="number" min="1" value=${thresholds.overdueDays} onInput=${num("overdueDays")} /></label>
      <label>基线最长间隔天数 <input type="number" min="1" value=${thresholds.baselineMaxGapDays} onInput=${num("baselineMaxGapDays")} /></label>
      <button type="button" class="vk-btn is-primary" disabled=${op.busy} onClick=${save}>保存</button>
      ${op.message && html`<span class="vk-muted" role="status">${op.message}</span>`}
    </div>
  </div>`;
}

export function SettingsPanel({ api, state, onSaved, onChanged }) {
  const [tab, setTab] = useState("roster");
  return html`<details class="sd-panel">
    <summary>设置（花名册、长周期规则与词表、长周期结论、区域、通讯录与阈值）· 种子版本 ${state.seedVersion || "—"}</summary>
    <div class="sd-tabs" role="tablist">${TABS.map(([key, label]) => html`<button key=${key} type="button" role="tab"
      aria-selected=${tab === key ? "true" : "false"} class=${`sd-tab${tab === key ? " is-active" : ""}`} onClick=${() => setTab(key)}>${label}</button>`)}</div>
    ${tab === "roster" && html`<${RosterTab} api=${api} onChanged=${onChanged} />`}
    ${tab === "rules" && html`<${RulesTab} api=${api} onChanged=${onChanged} />`}
    ${tab === "vocabulary" && html`<${VocabularyTab} api=${api} onChanged=${onChanged} />`}
    ${tab === "conclusions" && html`<${ConclusionsTab} api=${api} projects=${state.options.projects} onChanged=${onChanged} />`}
    ${tab === "people" && html`<${PeopleTab} api=${api} state=${state} onSaved=${onSaved} />`}
    ${tab === "mail" && html`<${MailTab} api=${api} state=${state} onSaved=${onSaved} />`}
  </details>`;
}
