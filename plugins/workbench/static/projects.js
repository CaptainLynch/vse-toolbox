// 项目切换（需求 C1）：每个项目一个数据文件夹，切换 = 保存选择 + 程序重启（约 10 秒）。
// 直接从源码运行（没有启动器）时只有一个项目，不显示切换器。
// 编辑与归档复用 workbench 后端已有接口（plugins/workbench/backend.py）：
//   PATCH /api/p/workbench/projects/<id>        name / vehicle / departments + expectedRevision
//   POST  /api/p/workbench/projects/<id>/archive  标记 retired，不删除任何数据
import { useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { api, html } from "./common.js";

const BASE = "/api/p/workbench/projects";

/** 默认科室（M0 问卷 C2）；新建项目时预先勾选。 */
export const DEFAULT_DEPARTMENTS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"];

/** 修订冲突的固定说法（后端 409 + RevisionConflict）。 */
export const REVISION_CONFLICT_MESSAGE = "项目已被修改，请刷新后再试";

/** 后端把错误码放在 error.type（显式时也在 error.code），两处都认。 */
export function isRevisionConflict(error) {
  if (!error || Number(error.status) !== 409) return false;
  return error.type === "RevisionConflict" || error.code === "RevisionConflict";
}

/**
 * 归档门禁，与 vse_boot/projects.py 的 archive() 同一口径：
 * 返回不能归档的原因（空串 = 可以归档）。前端禁用按钮只为提前说明，后端仍是权威。
 */
export function archiveBlockedReason(project, projects) {
  const list = (projects || []).filter(Boolean);
  if (!project) return "没有可归档的项目";
  if (list.length <= 1) return "当前只有一个项目，不能归档";
  if (!project.active) return "";
  const activeOthers = list.filter((p) => p.id !== project.id && p.status !== "retired");
  if (activeOthers.length) return "当前项目正在使用中，请先切换到其他项目再归档";
  return "当前只有一个可用项目，不能归档";
}

function normalizeDepartments(value) {
  const list = Array.isArray(value) ? value : [];
  const result = [];
  list.forEach((item) => {
    const text = String(item === undefined || item === null ? "" : item).trim();
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}

/**
 * 只提交改动字段：未改动的字段一律省略（省略 = 不改，显式 null 才清空）。
 * 返回空对象表示没有任何改动，此时不应发请求。
 */
export function buildProjectPatch(draft, original) {
  const patch = {};
  const before = original || {};
  const after = draft || {};
  const name = String(after.name === undefined || after.name === null ? "" : after.name).trim();
  const vehicle = String(after.vehicle === undefined || after.vehicle === null ? "" : after.vehicle).trim();
  if (name !== String(before.name || "").trim()) patch.name = name;
  if (vehicle !== String(before.vehicle || "").trim()) patch.vehicle = vehicle;
  const departments = normalizeDepartments(after.departments);
  if (departments.join("\u0000") !== normalizeDepartments(before.departments).join("\u0000")) {
    patch.departments = departments;
  }
  return patch;
}

/** 科室候选：默认科室 + 该项目已保存的科室（不丢自定义值）。 */
export function departmentOptions(current) {
  const result = DEFAULT_DEPARTMENTS.slice();
  normalizeDepartments(current).forEach((dept) => { if (!result.includes(dept)) result.push(dept); });
  return result;
}

export function useProjects() {
  const [state, setState] = useState({ data: null, error: null, token: 0 });
  useEffect(() => {
    let alive = true;
    api(BASE)
      .then((data) => { if (alive) setState((prev) => ({ ...prev, data, error: null })); })
      .catch((error) => { if (alive) setState((prev) => ({ ...prev, data: null, error })); });
    return () => { alive = false; };
  }, [state.token]);
  const reload = () => setState((prev) => ({ ...prev, token: (prev.token || 0) + 1 }));
  return { data: state.data, error: state.error, reload };
}

/** 等程序以目标项目重新起来再刷新：切换期间接口会短暂不可用。 */
export async function waitForProject(targetId, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  let sawDown = false;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const response = await fetch(BASE, { cache: "no-store" });
      if (!response.ok) { sawDown = true; continue; }
      const body = await response.json().catch(() => null);
      const active = body && body.data && body.data.active;
      // 后端在重启前就已写好当前项目，所以还要求「见过一次服务中断」，避免刷到旧进程上。
      if (active === targetId && sawDown) {
        window.location.reload();
        return true;
      }
    } catch (_err) {
      sawDown = true;
    }
  }
  return false;
}

function Busy({ text }) {
  return html`<div class="wb-scrim" role="status"><div class="wb-modal" style="text-align:center">
    <div style="font-size:30px" aria-hidden="true">⏳</div><p style="margin:8px 0 0;color:var(--ink);font-weight:600">${text}</p>
    <p class="wb-sub">程序正在重新启动，大约 10 秒后自动刷新。</p></div></div>`;
}

export function NewProjectDialog({ onClose, onCreated }) {
  const [name, setName] = useState("");
  const [vehicle, setVehicle] = useState("");
  const [departments, setDepartments] = useState(DEFAULT_DEPARTMENTS);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const toggle = (dept) => setDepartments(departments.includes(dept) ? departments.filter((d) => d !== dept) : [...departments, dept]);
  const submit = async (event) => {
    event.preventDefault();
    if (!vehicle.trim()) { setError("请填写车型，例如 F610S"); return; }
    setBusy(true);
    setError("");
    try {
      const result = await api(BASE, { method: "POST", body: { name, vehicle, departments } });
      onCreated(result.project);
    } catch (err) {
      setError(err.message || "新建失败");
      setBusy(false);
    }
  };
  return html`<div class="wb-scrim"><form class="wb-modal" onSubmit=${submit} aria-label="新建项目">
    <h2 style="margin:0 0 4px">新建项目</h2>
    <p class="wb-sub">每个项目的交付物、主计划和同步记录分开保存；登录的公司账号所有项目共用。</p>
    <label class="wb-field" style="margin-top:14px"><span>车型</span>
      <input value=${vehicle} onInput=${(e) => setVehicle(e.currentTarget.value)} placeholder="例如 F610S" autofocus /></label>
    <label class="wb-field"><span>项目名称（选填，默认用车型）</span>
      <input value=${name} onInput=${(e) => setName(e.currentTarget.value)} /></label>
    <div class="wb-field"><span>负责的科室</span>
      <div class="wb-row">${DEFAULT_DEPARTMENTS.map((dept) => html`<button type="button" key=${dept}
        class=${`wb-chip${departments.includes(dept) ? " is-on" : ""}`} aria-pressed=${departments.includes(dept) ? "true" : "false"}
        onClick=${() => toggle(dept)}>${dept}</button>`)}</div></div>
    ${error && html`<p class="wb-error" role="alert">${error}</p>`}
    <div class="wb-row" style="margin-top:18px;justify-content:space-between">
      <button type="button" class="wb-link" onClick=${onClose} disabled=${busy}>取消</button>
      <button type="submit" class="wb-btn is-primary" disabled=${busy}>${busy ? "正在新建…" : "新建并切换过去"}</button>
    </div>
  </form></div>`;
}

/**
 * 编辑项目：只提交改动字段（省略 = 不改），带 expectedRevision 做修订检查。
 * 409 RevisionConflict 时提示「项目已被修改，请刷新后再试」，刷新按钮重新拉列表并载入最新值。
 */
export function EditProjectDialog({ project, onClose, onSaved }) {
  const [baseline, setBaseline] = useState(project);
  const [name, setName] = useState(project.name || "");
  const [vehicle, setVehicle] = useState(project.vehicle || "");
  const [departments, setDepartments] = useState(normalizeDepartments(project.departments));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const options = departmentOptions(departments);
  const toggle = (dept) => setDepartments(departments.includes(dept) ? departments.filter((d) => d !== dept) : [...departments, dept]);

  const applyServer = (fresh, text) => {
    setBaseline(fresh);
    setName(fresh.name || "");
    setVehicle(fresh.vehicle || "");
    setDepartments(normalizeDepartments(fresh.departments));
    setConflict(false);
    setNotice(text);
  };

  const refresh = async () => {
    setRefreshing(true);
    setError("");
    try {
      const data = await api(BASE);
      const fresh = ((data && data.projects) || []).find((p) => p.id === project.id);
      if (!fresh) {
        setConflict(false);
        setError("这个项目已经不在项目列表里，请刷新页面后再试");
      } else {
        applyServer(fresh, "已刷新到最新数据，请确认后再保存");
      }
    } catch (err) {
      setError(err.message || "刷新失败，请稍后重试");
    }
    setRefreshing(false);
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!String(name).trim()) { setError("项目名称不能为空"); return; }
    const patch = buildProjectPatch({ name, vehicle, departments }, baseline);
    if (!Object.keys(patch).length) { onClose(); return; }
    const body = { ...patch };
    if (Number.isInteger(baseline.revision)) body.expectedRevision = baseline.revision;
    setBusy(true);
    setError("");
    setConflict(false);
    setNotice("");
    try {
      const result = await api(`${BASE}/${encodeURIComponent(project.id)}`, { method: "PATCH", body });
      onSaved(result.project);
    } catch (err) {
      if (isRevisionConflict(err)) {
        setConflict(true);
        setError(REVISION_CONFLICT_MESSAGE);
      } else {
        setError(err.message || "保存失败");
      }
      setBusy(false);
    }
  };

  return html`<div class="wb-scrim"><form class="wb-modal" onSubmit=${submit} aria-label="编辑项目">
    <h2 style="margin:0 0 4px">编辑项目</h2>
    <p class="wb-sub">改名只改显示名称，项目编号和数据文件夹不变；只有填过的字段会提交。</p>
    <label class="wb-field" style="margin-top:14px"><span>项目名称</span>
      <input value=${name} onInput=${(e) => setName(e.currentTarget.value)} autofocus /></label>
    <label class="wb-field"><span>车型</span>
      <input value=${vehicle} onInput=${(e) => setVehicle(e.currentTarget.value)} placeholder="例如 F610S" /></label>
    <div class="wb-field"><span>负责的科室</span>
      <div class="wb-row">${options.map((dept) => html`<button type="button" key=${dept}
        class=${`wb-chip${departments.includes(dept) ? " is-on" : ""}`} aria-pressed=${departments.includes(dept) ? "true" : "false"}
        onClick=${() => toggle(dept)}>${dept}</button>`)}</div></div>
    ${notice && html`<p class="wb-sub" role="status">${notice}</p>`}
    ${error && html`<p class="wb-error" role="alert">${error}</p>`}
    ${conflict && html`<div class="wb-row" style="align-items:center">
      <button type="button" class="wb-btn" data-action="refresh-project" onClick=${refresh} disabled=${refreshing}>${refreshing ? "正在刷新…" : "刷新"}</button>
      <span class="wb-small wb-muted">刷新会载入别人刚保存的内容，确认后再保存一次。</span></div>`}
    <div class="wb-row" style="margin-top:18px;justify-content:space-between">
      <button type="button" class="wb-link" onClick=${onClose} disabled=${busy}>取消</button>
      <button type="submit" class="wb-btn is-primary" disabled=${busy}>${busy ? "正在保存…" : "保存"}</button>
    </div>
  </form></div>`;
}

/** 归档确认：只标记 retired，从不删除数据，所以要说清「数据保留」。 */
export function ArchiveProjectDialog({ project, onClose, onArchived }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api(`${BASE}/${encodeURIComponent(project.id)}/archive`, { method: "POST", body: {} });
      onArchived(result.project);
    } catch (err) {
      setError(err.message || "归档失败");
      setBusy(false);
    }
  };
  return html`<div class="wb-scrim"><div class="wb-modal" role="dialog" aria-label="归档项目">
    <h2 style="margin:0 0 4px">归档「${project.name || project.vehicle || "这个项目"}」</h2>
    <p class="wb-sub">归档只把项目从列表里隐藏，<b>不会删除任何数据</b>：数据文件夹、交付物和同步记录都留在原处。</p>
    ${error && html`<p class="wb-error" role="alert">${error}</p>`}
    <div class="wb-row" style="margin-top:18px;justify-content:space-between">
      <button type="button" class="wb-link" onClick=${onClose} disabled=${busy}>取消</button>
      <button type="button" class="wb-btn is-primary" data-action="confirm-archive" onClick=${confirm} disabled=${busy}>${busy ? "正在归档…" : "归档（保留数据）"}</button>
    </div></div></div>`;
}

/** 页面头部的项目切换器。只有一个项目时也显示，方便新建第二个。 */
export function ProjectSwitcher() {
  const { data, reload } = useProjects();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [archiving, setArchiving] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  if (!data || !data.managed) return null;
  const visibleProjects = (data.projects || []).filter((p) => p.status !== "retired");
  const active = visibleProjects.find((p) => p.active) || (data.projects || []).find((p) => p.active) || visibleProjects[0] || (data.projects || [])[0];
  if (!active) return null;

  const restartInto = async (project, text) => {
    setBusy(text);
    const ok = await waitForProject(project.id);
    if (!ok) { setBusy(""); setError("程序重启时间较长，请稍后手动刷新页面，或从右下角托盘重新打开"); }
  };
  const switchTo = async (project) => {
    setOpen(false);
    if (project.active) return;
    setError("");
    setNotice("");
    try {
      await api(`${BASE}/${encodeURIComponent(project.id)}/switch`, { method: "POST", body: {} });
      await restartInto(project, `正在切换到「${project.name}」…`);
    } catch (err) {
      setError(err.message || "切换失败");
    }
  };
  const savedProject = (project) => {
    setEditing(null);
    setError("");
    setNotice(`已保存「${(project && project.name) || "项目"}」`);
    reload();
  };
  const archivedProject = (project) => {
    setArchiving(null);
    setError("");
    setNotice(`已归档「${(project && project.name) || "项目"}」，数据仍保留在原来的数据文件夹里`);
    reload();
  };

  return html`<div class="wb-projects">
    <button type="button" class="wb-btn wb-project-btn" aria-haspopup="listbox" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}>
      <span class="wb-muted wb-small">项目</span> <b>${active.name}</b> ▾</button>
    ${open && html`<div class="wb-project-menu" role="listbox" aria-label="切换项目">
      ${visibleProjects.map((p) => {
        const blocked = archiveBlockedReason(p, data.projects || []);
        return html`<div class="wb-row" role="presentation" key=${p.id} style="align-items:center;gap:6px;flex-wrap:wrap">
          <button type="button" role="option" data-project=${p.id} aria-selected=${p.active ? "true" : "false"}
            class=${`wb-project-item${p.active ? " is-active" : ""}`} style="flex:1" onClick=${() => switchTo(p)}>
            <b>${p.name}</b>${p.vehicle && p.vehicle !== p.name ? html`<small>${p.vehicle}</small>` : null}${p.active ? html`<small>当前</small>` : null}</button>
          <button type="button" class="wb-link wb-small" data-action="edit-project" data-project=${p.id} aria-label=${`编辑「${p.name}」`}
            onClick=${() => { setOpen(false); setEditing(p); }}>编辑</button>
          <button type="button" class="wb-link wb-small" data-action="archive-project" data-project=${p.id} aria-label=${`归档「${p.name}」`} disabled=${Boolean(blocked)}
            title=${blocked || "归档后从列表隐藏，数据保留"}
            onClick=${() => { setOpen(false); setArchiving(p); }}>归档</button>
          ${blocked && html`<small class="wb-muted wb-small" style="flex-basis:100%">${blocked}</small>`}
        </div>`;
      })}
      <button type="button" class="wb-project-item is-new" onClick=${() => { setOpen(false); setCreating(true); }}>＋ 新建项目</button>
    </div>`}
    ${notice && html`<span class="wb-small wb-muted" role="status">${notice}</span>`}
    ${error && html`<span class="wb-error wb-small" role="alert">${error}</span>`}
    ${creating && html`<${NewProjectDialog} onClose=${() => setCreating(false)}
      onCreated=${(project) => { setCreating(false); restartInto(project, `已新建「${project.name}」，正在切换过去…`); }} />`}
    ${editing && html`<${EditProjectDialog} project=${editing} onClose=${() => setEditing(null)} onSaved=${savedProject} />`}
    ${archiving && html`<${ArchiveProjectDialog} project=${archiving} onClose=${() => setArchiving(null)} onArchived=${archivedProject} />`}
    ${busy && html`<${Busy} text=${busy} />`}
  </div>`;
}
