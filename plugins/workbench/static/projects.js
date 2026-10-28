// 项目切换（需求 C1）：每个项目一个数据文件夹，切换 = 保存选择 + 程序重启（约 10 秒）。
// 直接从源码运行（没有启动器）时只有一个项目，不显示切换器。
import { useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { api, html } from "./common.js";

const BASE = "/api/p/workbench/projects";

/** 默认科室（M0 问卷 C2）；新建项目时预先勾选。 */
export const DEFAULT_DEPARTMENTS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"];

export function useProjects() {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let alive = true;
    api(BASE)
      .then((data) => { if (alive) setState({ data, error: null }); })
      .catch((error) => { if (alive) setState({ data: null, error }); });
    return () => { alive = false; };
  }, []);
  return state;
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

/** 页面头部的项目切换器。只有一个项目时也显示，方便新建第二个。 */
export function ProjectSwitcher() {
  const { data } = useProjects();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  if (!data || !data.managed) return null;
  const active = data.projects.find((p) => p.active) || data.projects[0];

  const restartInto = async (project, text) => {
    setBusy(text);
    const ok = await waitForProject(project.id);
    if (!ok) { setBusy(""); setError("程序重启时间较长，请稍后手动刷新页面，或从右下角托盘重新打开"); }
  };
  const switchTo = async (project) => {
    setOpen(false);
    if (project.active) return;
    setError("");
    try {
      await api(`${BASE}/${encodeURIComponent(project.id)}/switch`, { method: "POST", body: {} });
      await restartInto(project, `正在切换到「${project.name}」…`);
    } catch (err) {
      setError(err.message || "切换失败");
    }
  };

  return html`<div class="wb-projects">
    <button type="button" class="wb-btn wb-project-btn" aria-haspopup="listbox" aria-expanded=${open ? "true" : "false"} onClick=${() => setOpen(!open)}>
      <span class="wb-muted wb-small">项目</span> <b>${active.name}</b> ▾</button>
    ${open && html`<div class="wb-project-menu" role="listbox" aria-label="切换项目">
      ${data.projects.map((p) => html`<button type="button" role="option" key=${p.id} aria-selected=${p.active ? "true" : "false"}
        class=${`wb-project-item${p.active ? " is-active" : ""}`} onClick=${() => switchTo(p)}>
        <b>${p.name}</b>${p.vehicle && p.vehicle !== p.name ? html`<small>${p.vehicle}</small>` : null}${p.active ? html`<small>当前</small>` : null}</button>`)}
      <button type="button" class="wb-project-item is-new" onClick=${() => { setOpen(false); setCreating(true); }}>＋ 新建项目</button>
    </div>`}
    ${error && html`<span class="wb-error wb-small" role="alert">${error}</span>`}
    ${creating && html`<${NewProjectDialog} onClose=${() => setCreating(false)}
      onCreated=${(project) => { setCreating(false); restartInto(project, `已新建「${project.name}」，正在切换过去…`); }} />`}
    ${busy && html`<${Busy} text=${busy} />`}
  </div>`;
}
