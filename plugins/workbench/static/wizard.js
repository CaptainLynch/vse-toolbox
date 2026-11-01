// 首次使用向导（需求 U1；契约 C3 向导条款）：
// 步骤推进：欢迎 → 统一登录 → 新建项目 → 选择交付物 → 开机自启 → 完成。
// 契约保证：
// 1. 跨重启恢复非敏感状态（步进、车型、科室、交付物选择存 localStorage）；
// 2. 密码绝不持久化到向导状态（密码只进 DPAPI，经 identity 服务）；
// 3. 区分「稍后设置」（标记 status: skipped）与「已完成」（标记 status: completed）；
// 4. 每步可返回，开机自启询问默认关闭，现有向导调用方零修改。

import { html, useState, useEffect, useRef } from "/static/host/vendor/preact-htm.js";
import { submitDomainLogin, updateSessionBadges } from "/static/host/session.js";
import { api, go, activeDeliverables } from "./common.js";

export const DISMISS_KEY = "vse.wizardDone";
export const STATE_KEY = "vse.wizardState";

/**
 * 单项目环境（源码直接运行，没有启动器管理多项目）的唯一合法错误码。
 * 后端 POST /api/p/workbench/projects 只在该情形返回 409 + 这个错误码，
 * 见 plugins/workbench/backend.py 的 mutation()：ctx.json_error(409, "NotManaged", ...)。
 */
export const NOT_MANAGED_CODE = "NotManaged";

/**
 * 开机自启的确认状态。只有后端明确回报后才允许显示「已开启 / 未开启」，
 * 失败或读不到状态时绝不猜测（避免勾选/未勾选被伪报成已生效）。
 */
export const AUTOSTART_CONFIRMED = ["on", "off", "failed", "unknown"];

export const STEP_NAMES = ["欢迎", "统一登录", "新建项目", "选择交付物", "开机自启", "完成"];

/** 默认科室（M0 问卷 C2）；新建项目时预先勾选。 */
export const DEFAULT_DEPARTMENTS = ["车体科", "车身科", "内饰科", "外饰科", "车体架构集成科"];

/** 允许持久化到本地存储的非敏感键白名单，严禁任何密码、口令或敏感凭据写入 */
export const ALLOWED_STATE_KEYS = [
  "step",
  "status",
  "vehicle",
  "name",
  "departments",
  "selectedDeliverables",
  "autostart",
  "username",
  // 注：偏好类标记（如「记住登录」勾选）不进本清单——凭据本身走凭据保护库，勾选态每次会话默认勾上
  "updatedAt",
  "skippedStep",
  // 项目恢复：已建项目 ID 与创建签名（车型+名称+科室），用于刷新/重启后复用，不再重复建项目
  "projectId",
  "projectCreated",
  "projectSignature",
  // 开机自启确认态（on/off/failed/unknown），只记录后端回报的结果，不记录任何凭据
  "autostartConfirmed",
];

/**
 * 过滤并清洗向导状态，绝不允许密码/凭据进入持久化存储。
 */
export function sanitizeWizardState(input) {
  if (!input || typeof input !== "object") return {};
  const clean = {};
  for (const key of ALLOWED_STATE_KEYS) {
    if (Object.prototype.hasOwnProperty.call(input, key)) {
      clean[key] = input[key];
    }
  }

  // 严格约束各字段类型与边界
  if (typeof clean.step !== "number" || clean.step < 0 || clean.step > 5) {
    clean.step = 0;
  }
  if (!["in_progress", "skipped", "completed"].includes(clean.status)) {
    clean.status = "in_progress";
  }
  if (typeof clean.vehicle !== "string") clean.vehicle = "";
  if (typeof clean.name !== "string") clean.name = "";
  if (!Array.isArray(clean.departments)) {
    clean.departments = [...DEFAULT_DEPARTMENTS];
  }
  if (!Array.isArray(clean.selectedDeliverables)) {
    clean.selectedDeliverables = [];
  }
  // 开机自启询问默认关
  clean.autostart = Boolean(clean.autostart);
  if (typeof clean.username !== "string") clean.username = "";
  // 项目恢复：ID 与签名只接受字符串，未创建过就是空
  if (typeof clean.projectId !== "string") clean.projectId = "";
  if (typeof clean.projectSignature !== "string") clean.projectSignature = "";
  clean.projectCreated = Boolean(clean.projectCreated);
  // 开机自启确认态：只接受枚举值，未知一律 unknown（不猜测已生效）
  if (!AUTOSTART_CONFIRMED.includes(clean.autostartConfirmed)) clean.autostartConfirmed = "unknown";
  delete clean.saveCredentials;  // 偏好不持久化（见 ALLOWED_STATE_KEYS 注释）
  return clean;
}

/**
 * 从 localStorage 读取向导状态。
 */
export function loadWizardState() {
  try {
    const raw = window.localStorage.getItem(STATE_KEY);
    if (!raw) return null;
    return sanitizeWizardState(JSON.parse(raw));
  } catch (_err) {
    return null;
  }
}

/**
 * 保存向导状态到 localStorage，自动过滤敏感字段并写入更新时间。
 */
export function saveWizardState(partial) {
  try {
    const current = loadWizardState() || {};
    const safePartial = {};
    if (partial && typeof partial === "object") {
      for (const key of ALLOWED_STATE_KEYS) {
        if (Object.prototype.hasOwnProperty.call(partial, key)) {
          safePartial[key] = partial[key];
        }
      }
    }
    const merged = {
      ...current,
      ...safePartial,
      updatedAt: new Date().toISOString(),
    };
    const clean = sanitizeWizardState(merged);
    window.localStorage.setItem(STATE_KEY, JSON.stringify(clean));
    return clean;
  } catch (_err) {
    return null;
  }
}

/**
 * 标记为「稍后设置」并持久化（跳过该步并记录 skipped，向导可随时从设置页重进）。
 */
export function markWizardSkipped(currentStep = 0, extra = {}) {
  const stepNum = typeof currentStep === "number" ? currentStep : 0;
  const clean = saveWizardState({
    ...extra,
    step: stepNum,
    skippedStep: stepNum,
    status: "skipped",
  });
  try {
    window.localStorage.setItem(DISMISS_KEY, "1");
  } catch (_err) {}
  return clean;
}

/**
 * 标记为「已完成」并持久化。
 */
export function markWizardCompleted(extra = {}) {
  const clean = saveWizardState({
    ...extra,
    step: 5,
    status: "completed",
  });
  try {
    window.localStorage.setItem(DISMISS_KEY, "1");
  } catch (_err) {}
  return clean;
}

/**
 * 判断向导是否已被跳过（稍后设置）。
 */
export function isWizardSkipped() {
  const state = loadWizardState();
  return Boolean(state && state.status === "skipped");
}

/**
 * 判断向导是否已全部完成。
 */
export function isWizardCompleted() {
  const state = loadWizardState();
  return Boolean(state && state.status === "completed");
}

/**
 * 向导是否已关闭（稍后设置或已完成均视为已关闭，避免在今天页自动反复弹窗）。
 * 保持对既有调用方兼容。
 */
export function wizardDismissed() {
  try {
    const state = loadWizardState();
    if (state && (state.status === "completed" || state.status === "skipped")) {
      return true;
    }
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  } catch (_err) {
    return false;
  }
}

/**
 * 重置向导状态（用于从设置页重新进入向导时）。
 */
export function resetWizardState() {
  try {
    window.localStorage.removeItem(STATE_KEY);
    window.localStorage.removeItem(DISMISS_KEY);
  } catch (_err) {}
}

/**
 * 项目创建签名：车型 + 项目名称 + 科室。
 * 用来判断「已建项目是否就是这次要建的项目」，从而在重复点击或刷新恢复后复用，
 * 不再发第二次创建请求。
 */
export function projectSignature({ vehicle, name, departments } = {}) {
  const v = String(vehicle == null ? "" : vehicle).trim();
  const n = String(name == null ? "" : name).trim();
  const depts = Array.isArray(departments) ? departments.map((d) => String(d)) : [];
  return JSON.stringify([v, n, depts]);
}

/**
 * 只有「HTTP 409 且错误码为 NotManaged」才是已批准的单项目环境分支。
 * 其它 409（RevisionConflict / CurrentProjectArchived 等）与其它错误码一律按失败处理。
 * 注：host 的 json_error(409, "NotManaged", ...) 把错误码放在 error.type，
 * 显式传 code 时才放在 error.code，两者都要认。
 */
export function isSingleProjectEnvironment(err) {
  if (!err || Number(err.status) !== 409) return false;
  const code = err.code == null || err.code === "" ? err.type : err.code;
  return String(code == null ? "" : code) === NOT_MANAGED_CODE;
}

/**
 * 创建项目失败时给用户看的中文说明。按状态码归类，不回显后端内部细节
 * （异常类型、路径、堆栈、英文原文）。
 */
export function projectCreateErrorMessage(err) {
  const status = err && Number(err.status);
  if (status === 401) return "登录状态已失效，请重新登录后再继续";
  if (status === 403) return "当前操作只允许在本机浏览器中执行";
  if (status === 409) return "项目创建失败，请刷新后重试";
  if (status === 422) return "项目信息格式有误，请检查车型与科室后重试";
  if (status >= 500) return "本地服务暂时不可用，请稍后重试";
  if (!status) return "无法连接本地服务，请确认 VSE Toolbox 仍在运行";
  if (status >= 400) return "项目创建失败，请稍后重试";
  // 2xx 但没有可用的成功响应（例如非 JSON 响应体）
  return "本地服务返回异常，请重试";
}

/** 开机自启设置失败时的中文说明，同样不回显内部细节。 */
export function autostartErrorMessage(err) {
  const status = err && Number(err.status);
  if (status === 401) return "登录状态已失效，请重新登录后再继续";
  if (status === 403) return "开机自启只允许在本机浏览器中设置";
  if (status === 501) return "当前运行环境不支持开机自启设置";
  if (status >= 500) return "本地服务暂时不可用，开机自启未生效";
  if (!status) return "无法连接本地服务，开机自启未生效";
  if (status >= 400) return "开机自启设置失败，请稍后在设置里重试";
  return "开机自启未生效，请稍后在设置里重试";
}

/**
 * 创建项目或复用已建项目（向导第 2 步的唯一决策点，供组件与测试共用）。
 *
 * - 已建过项目且签名一致（重复点击、刷新/重启恢复）→ 直接复用，不再发创建请求；
 * - 409 + NotManaged → 单项目环境的已批准分支，视为可继续；
 * - 其它任何错误（401/403/500/网络/非 JSON/其它 409）→ 失败：不推进步骤、不标记已建项目。
 *
 * 返回 { ok, step, projectId, signature, reused, singleProject, message }。
 */
export async function createOrReuseProject({ create, vehicle, name, departments, saved } = {}) {
  const v = String(vehicle == null ? "" : vehicle).trim();
  const projectNameStr = String(name == null ? "" : name).trim() || v;
  const depts = Array.isArray(departments) ? departments.map((d) => String(d)) : [];
  const signature = projectSignature({ vehicle: v, name: projectNameStr, departments: depts });
  const previous = saved && typeof saved === "object" ? saved : {};

  if (previous.projectCreated === true && previous.projectSignature === signature) {
    return {
      ok: true,
      step: 3,
      reused: true,
      singleProject: false,
      projectId: typeof previous.projectId === "string" ? previous.projectId : "",
      signature,
    };
  }

  let data;
  try {
    data = await create({ name: projectNameStr, vehicle: v, departments: depts });
  } catch (err) {
    if (isSingleProjectEnvironment(err)) {
      // 单项目环境：没有多项目能力，但没有真的失败；记下 main（后端单项目 id）避免反复 409
      return { ok: true, step: 3, reused: false, singleProject: true, projectId: "main", signature };
    }
    return {
      ok: false,
      step: 2,
      reused: false,
      singleProject: false,
      projectId: "",
      signature,
      message: projectCreateErrorMessage(err),
    };
  }

  const createdId = data && data.project && data.project.id ? String(data.project.id) : "";
  return { ok: true, step: 3, reused: false, singleProject: false, projectId: createdId, signature };
}

/**
 * 开机自启询问的决策点（向导第 4 步）。
 *
 * - 未勾选：绝不调用开启；只读回真实状态，读不到就不下结论（confirmed: unknown）；
 * - 勾选：调用 POST {enabled: true}，只有后端明确返回 enabled === true 才算已开启；
 * - 失败：如实返回失败（confirmed: failed），组件停在当前步显示原因。
 */
export async function submitAutostartChoice({ request, autostart } = {}) {
  if (!autostart) {
    try {
      const data = await request("/api/p/settings/autostart", { method: "GET" });
      const enabled = Boolean(data && data.enabled === true);
      return { ok: true, step: 5, called: false, enabled, confirmed: enabled ? "on" : "off" };
    } catch (_err) {
      return { ok: true, step: 5, called: false, enabled: false, confirmed: "unknown" };
    }
  }

  let data;
  try {
    data = await request("/api/p/settings/autostart", { method: "POST", body: { enabled: true } });
  } catch (err) {
    return { ok: false, step: 4, called: true, enabled: false, confirmed: "failed", message: autostartErrorMessage(err) };
  }
  if (!data || data.enabled !== true) {
    return {
      ok: false,
      step: 4,
      called: true,
      enabled: false,
      confirmed: "failed",
      message: "开机自启没有生效，请稍后在设置里重新开启",
    };
  }
  return { ok: true, step: 5, called: true, enabled: true, confirmed: "on" };
}

export function Wizard({ projectName, onClose, initialStep }) {
  const saved = loadWizardState() || {};

  // 跨重启恢复步进：若未显式指定 initialStep，从保存状态恢复
  const [step, setStep] = useState(
    typeof initialStep === "number"
      ? initialStep
      : (typeof saved.step === "number" ? saved.step : 0)
  );

  // 状态字段（仅域账号持久化，密码绝不进 localStorage）
  const [username, setUsername] = useState(saved.username || "");
  const [password, setPassword] = useState("");
  const [save, setSave] = useState(saved.saveCredentials !== false);

  // 项目字段（车型/项目名称/科室）
  const [vehicle, setVehicle] = useState(saved.vehicle || projectName || "");
  const [name, setName] = useState(saved.name || "");
  const [departments, setDepartments] = useState(
    Array.isArray(saved.departments) && saved.departments.length
      ? saved.departments
      : [...DEFAULT_DEPARTMENTS]
  );

  // 交付物字段
  const [deliverables, setDeliverables] = useState([]);
  const [deliverablesLoaded, setDeliverablesLoaded] = useState(false);
  const [selectedDeliverables, setSelectedDeliverables] = useState(
    Array.isArray(saved.selectedDeliverables) ? saved.selectedDeliverables : []
  );

  // 开机自启设置（默认关）
  const [autostart, setAutostart] = useState(Boolean(saved.autostart));
  // 开机自启确认态：只有后端回报后才显示已开启/未开启
  const [autostartConfirmed, setAutostartConfirmed] = useState(
    AUTOSTART_CONFIRMED.includes(saved.autostartConfirmed) ? saved.autostartConfirmed : "unknown"
  );

  // 交互反馈与加载状态
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState("");
  // 防重复点击：创建项目的请求在飞时不发第二次
  const projectSubmitting = useRef(false);

  const persistCurrent = (nextStep, extra = {}) => {
    saveWizardState({
      step: nextStep,
      status: "in_progress",
      username,
      vehicle,
      name,
      departments,
      selectedDeliverables,
      autostart,
      saveCredentials: save,
      ...extra,
    });
  };

  const goToStep = (nextStep) => {
    setMessage(null);
    setError("");
    setStep(nextStep);
    persistCurrent(nextStep);
  };

  const skipWizard = () => {
    markWizardSkipped(step, {
      username,
      vehicle,
      name,
      departments,
      selectedDeliverables,
      autostart,
    });
    if (typeof onClose === "function") onClose(false);
  };

  const finishWizard = () => {
    markWizardCompleted({
      username,
      vehicle,
      name,
      departments,
      selectedDeliverables,
      autostart,
    });
    if (typeof onClose === "function") onClose(true);
  };

  const finishAndOpenAutoSync = () => {
    markWizardCompleted({
      username,
      vehicle,
      name,
      departments,
      selectedDeliverables,
      autostart,
    });
    go("#p/project-overview/auto-sync");
    if (typeof onClose === "function") onClose(true);
  };

  const login = async (event) => {
    if (event) event.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    setMessage(null);
    setError("");
    try {
      const outcome = await submitDomainLogin({ username, password, saveForScheduled: save });
      setPassword(""); // 内存即时清空，绝不留存
      setBusy(false);
      if (outcome && outcome.sessions) updateSessionBadges(outcome.sessions);
      if (outcome && outcome.kind === "error") {
        setMessage({ tone: "bad", text: outcome.text || "登录失败，请核对域账号与密码" });
        return;
      }
      setMessage(outcome && outcome.kind === "success" ? null : { tone: "warn", text: outcome.text });
      goToStep(2);
    } catch (err) {
      setPassword("");
      setBusy(false);
      setMessage({ tone: "bad", text: err.message || "登录请求异常" });
    }
  };

  const toggleDept = (dept) => {
    const next = departments.includes(dept)
      ? departments.filter((d) => d !== dept)
      : [...departments, dept];
    setDepartments(next);
    saveWizardState({ departments: next });
  };

  const submitProject = async (event) => {
    if (event) event.preventDefault();
    if (projectSubmitting.current) return;  // 双击只发一次创建请求
    const v = vehicle.trim();
    if (!v) {
      setError("请填写车型，例如 F610S");
      return;
    }
    projectSubmitting.current = true;
    setBusy(true);
    setError("");
    const projectNameStr = name.trim() || v;
    saveWizardState({ vehicle: v, name: projectNameStr, departments });
    let outcome;
    try {
      outcome = await createOrReuseProject({
        create: (body) => api("/api/p/workbench/projects", { method: "POST", body }),
        vehicle: v,
        name: projectNameStr,
        departments,
        saved: loadWizardState() || {},
      });
    } catch (_err) {
      // 任何未预期的异常同样按失败处理，不得静默推进
      outcome = null;
    } finally {
      projectSubmitting.current = false;
    }
    setBusy(false);
    if (!outcome || !outcome.ok) {
      // 失败一律停在当前步，显示真实原因，不标记已建项目
      setError((outcome && outcome.message) || "项目创建失败，请稍后重试");
      return;
    }
    // 创建成功：把项目 ID 与创建签名一起持久化，刷新/重启后复用，不再重复建项目
    saveWizardState({
      projectCreated: true,
      projectId: outcome.projectId || "",
      projectSignature: outcome.signature,
      vehicle: v,
      name: projectNameStr,
      departments,
    });
    goToStep(3);
  };

  useEffect(() => {
    if (step === 3 && !deliverablesLoaded) {
      let alive = true;
      api("/api/project-status")
        .then((data) => {
          if (!alive) return;
          const list = (data && data.deliverables) || [];
          const active = typeof activeDeliverables === "function" ? activeDeliverables(list) : list.filter((d) => !d.retired);
          setDeliverables(active);
          setDeliverablesLoaded(true);
          // 首次加载时：默认全选计入完成统计项（若没有则全选当前交付物）
          if (!selectedDeliverables || !selectedDeliverables.length) {
            const counting = active.filter((d) => d.countsTowardCompletion !== false).map((d) => d.id);
            const initial = counting.length ? counting : active.map((d) => d.id);
            setSelectedDeliverables(initial);
            saveWizardState({ selectedDeliverables: initial });
          }
        })
        .catch(() => {
          if (alive) setDeliverablesLoaded(true);
        });
      return () => { alive = false; };
    }
  }, [step, deliverablesLoaded]);

  const toggleDeliverable = (id) => {
    const next = selectedDeliverables.includes(id)
      ? selectedDeliverables.filter((item) => item !== id)
      : [...selectedDeliverables, id];
    setSelectedDeliverables(next);
    saveWizardState({ selectedDeliverables: next });
  };

  const selectAllDeliverables = () => {
    const all = deliverables.map((d) => d.id);
    setSelectedDeliverables(all);
    saveWizardState({ selectedDeliverables: all });
  };

  const clearAllDeliverables = () => {
    setSelectedDeliverables([]);
    saveWizardState({ selectedDeliverables: [] });
  };

  const submitAutostart = async () => {
    setBusy(true);
    setError("");
    saveWizardState({ autostart });
    const outcome = await submitAutostartChoice({
      request: (url, options) => api(url, options),
      autostart,
    });
    setBusy(false);
    setAutostartConfirmed(outcome.confirmed);
    saveWizardState({ autostartConfirmed: outcome.confirmed });
    if (!outcome.ok) {
      // 如实显示失败，停在自启步；用户可重试，也可显式跳过
      setError(outcome.message || "开机自启设置失败，请稍后在设置里重试");
      return;
    }
    goToStep(5);
  };

  /** 自启设置失败后显式跳过：不把失败伪报成已开启，完成页如实说明未生效。 */
  const skipAutostartStep = () => {
    setError("");
    setAutostartConfirmed("failed");
    saveWizardState({ autostartConfirmed: "failed" });
    goToStep(5);
  };

  const stepsBar = html`<div class="wb-steps" aria-label="向导进度">
    ${[0, 1, 2, 3, 4, 5].map((i) => html`<i class=${i <= step ? "on" : ""} key=${i} title=${STEP_NAMES[i]}></i>`)}
  </div>`;

  let body;
  if (step === 0) {
    body = html`<div>
      <div style="text-align:center">
        <div class="hc-brand-mark" style="margin:0 auto 12px;width:56px;height:56px;font-size:28px">V</div>
        <h1>欢迎使用 VSE Toolbox</h1>
        <p class="wb-sub">只需要几步简单配置，即可连通公司系统、建立项目并开启交付物自动同步，日报一键生成。</p>
      </div>
      <div class="wb-row" style="margin-top:24px;justify-content:space-between">
        <button type="button" class="wb-link" onClick=${skipWizard}>稍后设置</button>
        <button type="button" class="wb-btn is-primary" onClick=${() => goToStep(1)}>开始</button>
      </div>
    </div>`;
  } else if (step === 1) {
    body = html`<form onSubmit=${login}>
      <h2>登录公司域账号</h2>
      <p class="wb-sub">一次登录同时连通 Aras 和 TDC。</p>
      <label class="wb-field" style="margin-top:14px"><span>域账号</span>
        <input type="text" autocomplete="username" value=${username} onInput=${(e) => setUsername(e.currentTarget.value)} disabled=${busy} autofocus />
      </label>
      <label class="wb-field"><span>密码</span>
        <input type="password" autocomplete="current-password" value=${password} onInput=${(e) => setPassword(e.currentTarget.value)} disabled=${busy} />
      </label>
      <label class="wb-check"><input type="checkbox" checked=${save} onChange=${(e) => setSave(e.currentTarget.checked)} />
        <span>记住密码，用于自动同步（加密保存在本机，只有你的 Windows 账号能读取）</span></label>
      ${message && html`<p class=${message.tone === "bad" ? "wb-error" : "wb-sub"}>${message.text}</p>`}
      <div class="wb-row" style="margin-top:20px;justify-content:space-between">
        <div class="wb-row">
          <button type="button" class="wb-link" onClick=${() => goToStep(0)}>上一步</button>
          <span style="color:var(--hairline-strong)">|</span>
          <button type="button" class="wb-link" onClick=${skipWizard}>稍后设置</button>
        </div>
        <div class="wb-row">
          <button type="button" class="wb-btn" onClick=${() => goToStep(2)} disabled=${busy}>跳过登录</button>
          <button type="submit" class="wb-btn is-primary" disabled=${busy || !username || !password}>${busy ? "正在验证…" : "登录"}</button>
        </div>
      </div>
    </form>`;
  } else if (step === 2) {
    body = html`<form onSubmit=${submitProject}>
      <h2>新建或配置项目</h2>
      <p class="wb-sub">每个项目的交付物、主计划和同步记录分开保存；登录的公司账号所有项目共用。</p>
      <label class="wb-field" style="margin-top:14px"><span>车型</span>
        <input value=${vehicle} onInput=${(e) => setVehicle(e.currentTarget.value)} placeholder="例如 F610S" autofocus />
      </label>
      <label class="wb-field"><span>项目名称（选填，默认用车型）</span>
        <input value=${name} onInput=${(e) => setName(e.currentTarget.value)} placeholder=${vehicle || "项目名称"} />
      </label>
      <div class="wb-field"><span>负责的科室</span>
        <div class="wb-row">${DEFAULT_DEPARTMENTS.map((dept) => html`<button type="button" key=${dept}
          class=${`wb-chip${departments.includes(dept) ? " is-on" : ""}`} aria-pressed=${departments.includes(dept) ? "true" : "false"}
          onClick=${() => toggleDept(dept)}>${dept}</button>`)}
        </div>
      </div>
      ${error && html`<p class="wb-error" role="alert">${error}</p>`}
      <div class="wb-row" style="margin-top:20px;justify-content:space-between">
        <div class="wb-row">
          <button type="button" class="wb-link" onClick=${() => goToStep(1)}>上一步</button>
          <span style="color:var(--hairline-strong)">|</span>
          <button type="button" class="wb-link" onClick=${skipWizard}>稍后设置</button>
        </div>
        <div class="wb-row">
          <button type="button" class="wb-btn" onClick=${() => goToStep(3)} disabled=${busy}>跳过此步</button>
          <button type="submit" class="wb-btn is-primary" disabled=${busy}>${busy ? "正在保存…" : "下一步"}</button>
        </div>
      </div>
    </form>`;
  } else if (step === 3) {
    body = html`<div>
      <h2>选择要跟踪的交付物</h2>
      <p class="wb-sub">选中的交付物将纳入完成统计并支持自动同步，默认全选计入统计的交付物。</p>
      <div class="wb-row" style="margin:10px 0;justify-content:space-between">
        <span class="wb-small wb-muted">已选 ${selectedDeliverables.length} 项</span>
        <div class="wb-row">
          <button type="button" class="wb-link wb-small" onClick=${selectAllDeliverables}>全选</button>
          <span style="color:var(--hairline-strong)">|</span>
          <button type="button" class="wb-link wb-small" onClick=${clearAllDeliverables}>清空</button>
        </div>
      </div>
      <div style="max-height:220px;overflow-y:auto;border:1px solid var(--hairline);border-radius:10px;padding:8px 12px;display:grid;gap:8px">
        ${deliverables.length === 0 && html`<p class="wb-sub" style="margin:8px 0">${deliverablesLoaded ? "当前项目暂无可跟踪的交付物，后续可在项目页随时添加" : "正在加载交付物列表…"}</p>`}
        ${deliverables.map((d) => html`<label key=${d.id} class="wb-check" style="cursor:pointer">
          <input type="checkbox" checked=${selectedDeliverables.includes(d.id)} onChange=${() => toggleDeliverable(d.id)} />
          <span><b>${d.name}</b>${d.countsTowardCompletion ? html`<small class="wb-muted">（计入统计项）</small>` : ""}</span>
        </label>`)}
      </div>
      <div class="wb-row" style="margin-top:20px;justify-content:space-between">
        <div class="wb-row">
          <button type="button" class="wb-link" onClick=${() => goToStep(2)}>上一步</button>
          <span style="color:var(--hairline-strong)">|</span>
          <button type="button" class="wb-link" onClick=${skipWizard}>稍后设置</button>
        </div>
        <button type="button" class="wb-btn is-primary" onClick=${() => goToStep(4)}>下一步</button>
      </div>
    </div>`;
  } else if (step === 4) {
    body = html`<div>
      <h2>开机自启设置</h2>
      <p class="wb-sub">开机自动在后台运行工具箱，按时自动同步交付物数据，无需每天手动打开。</p>
      <div style="margin:20px 0;padding:16px;border:1px solid var(--hairline);border-radius:12px;background:var(--surface-soft)">
        <label class="wb-check" style="cursor:pointer;display:flex;align-items:flex-start;gap:10px">
          <input type="checkbox" checked=${autostart} onChange=${(e) => setAutostart(e.currentTarget.checked)} />
          <div>
            <strong style="color:var(--ink);font-size:14px">开机自动启动 VSE 工具箱</strong>
            <p class="wb-sub" style="margin:4px 0 0">电脑开机登录后自动在托盘运行，默认不打扰；可随时在设置中修改。</p>
          </div>
        </label>
      </div>
      ${error && html`<p class="wb-error" role="alert">${error}</p>`}
      <div class="wb-row" style="margin-top:20px;justify-content:space-between">
        <div class="wb-row">
          <button type="button" class="wb-link" onClick=${() => goToStep(3)}>上一步</button>
          <span style="color:var(--hairline-strong)">|</span>
          <button type="button" class="wb-link" onClick=${skipWizard}>稍后设置</button>
          ${error && html`<span style="color:var(--hairline-strong)">|</span><button type="button" class="wb-link" onClick=${skipAutostartStep}>先跳过自启</button>`}
        </div>
        <button type="button" class="wb-btn is-primary" onClick=${submitAutostart} disabled=${busy}>${busy ? "正在保存…" : "下一步"}</button>
      </div>
    </div>`;
  } else {
    const displayProject = name || vehicle || projectName || "默认项目";
    // 开机自启只按后端回报的确认态展示：未确认或失败绝不写成已开启
    const autostartText =
      autostartConfirmed === "on"
        ? "已开启"
        : autostartConfirmed === "off"
          ? "未开启（默认关闭，可随时在设置开启）"
          : autostartConfirmed === "failed"
            ? "未能开启（可稍后在设置里开启）"
            : "未确认（可稍后在设置里查看）";
    body = html`<div>
      <h2>配置完成</h2>
      <p class="wb-sub">首次使用向导配置已就绪，你可以开始使用了。</p>
      <ul class="wb-sub" style="padding-left:18px;margin:14px 0 0;line-height:1.8">
        <li>账号：${username ? `${username}（${save ? "已记住密码，可自动同步" : "未记住密码"}）` : "未配置（可稍后登录）"}</li>
        <li>项目：${displayProject}（${departments.length} 个科室）</li>
        <li>跟踪交付物：已选 ${selectedDeliverables.length} 项纳入自动跟踪</li>
        <li>开机自启：${autostartText}</li>
      </ul>
      <p class="wb-sub" style="margin-top:12px">接下来可以在项目页一键开启交付物自动同步，或进入今天页查看待办与最新进度。</p>
      <div class="wb-row" style="margin-top:20px;justify-content:space-between">
        <button type="button" class="wb-link" onClick=${() => goToStep(4)}>上一步</button>
        <div class="wb-row">
          <button type="button" class="wb-btn" onClick=${finishAndOpenAutoSync}>开启自动同步</button>
          <button type="button" class="wb-btn is-primary" onClick=${finishWizard}>开始使用</button>
        </div>
      </div>
    </div>`;
  }

  return html`<div class="wb-scrim" role="dialog" aria-modal="true" aria-label="首次使用向导">
    <div class="wb-modal">${stepsBar}${body}</div>
  </div>`;
}
