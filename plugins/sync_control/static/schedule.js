// 调度时刻与暂停设置（plugin module page，DSH-V2-21）。
//
// 只做「界面 + 真实 API 调用」，不复制任何调度语义：
// - 当前项目来自既有 GET /api/p/workbench/projects（读不到即「未配置」态）；
// - 读写 GET/PUT /api/p/sync-control/binding[/<projectId>]，时刻规范化以后端为准；
// - 「下次执行」与「今天的执行」的时间一律北京时间，复用宿主
//   /static/host/time-format.js（契约 C9），状态色复用宿主 ui-kit 的 TONE；
// - 保存失败时后端 message 在表单原位显示，绝不清空用户输入。
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { api } from "/static/host/api.js";
import { TONE } from "/static/host/ui-kit.js";
import { beijingParts, formatBeijing } from "/static/host/time-format.js";

export const PROJECTS_PATH = "/api/p/workbench/projects";
export const BINDING_PATH = "/api/p/sync-control/binding";

/** 槽状态 -> 中文术语（与 C4 契约的槽状态闭集一一对应）。 */
export const STATUS_LABELS = Object.freeze({
  pending: "待执行",
  leased: "执行中",
  succeeded: "已完成",
  failed: "失败",
  paused_skipped: "暂停跳过",
  expired: "已过期",
});

/** 槽状态 -> 宿主 TONE（ok 绿 / warn 黄 / bad 红 / off 灰）。 */
export const STATUS_TONES = Object.freeze({
  pending: TONE.warn,
  leased: TONE.warn,
  succeeded: TONE.ok,
  failed: TONE.bad,
  paused_skipped: TONE.off,
  expired: TONE.off,
});

const TIME_RE = /^(\d{1,2}):(\d{2})$/;

function pad2(value) {
  return String(value).padStart(2, "0");
}

function text(value) {
  return String(value === null || value === undefined ? "" : value).trim();
}

/**
 * 前端只做格式提示：`'9:00'` -> `'09:00'`；无法识别返回 null。
 * 真正的校验与规范化仍以后端 schedule_policy 为准（这里不替它兜底）。
 */
export function normalizeTimeText(value) {
  const raw = text(value);
  const match = TIME_RE.exec(raw);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return null;
  return `${pad2(hour)}:${pad2(minute)}`;
}

/** 非空且无法识别 -> 需要就地提示格式（空行表示「不填」）。 */
export function isInvalidTime(value) {
  return text(value) !== "" && normalizeTimeText(value) === null;
}

/**
 * 提交给后端的时刻：只去掉首尾空白与空行，**不替后端规范化**。
 * 去重、升序、`'9:00'` ≡ `'09:00'`、非法时刻的 400 判定一律以 schedule_policy 为准。
 */
export function payloadTimes(values) {
  return (Array.isArray(values) ? values : [])
    .map((value) => text(value))
    .filter((value) => value !== "");
}

/** 服务端数据 -> 表单草稿；没有时刻时留一个空行供输入。 */
export function bindingDraft(data) {
  const source = data || {};
  const times = Array.isArray(source.times) ? source.times.map((item) => String(item)) : [];
  return { times: times.length ? times : [""], paused: Boolean(source.paused) };
}

/** 「下次执行」文案：暂停 / 非 fixed 时明确说明不排下一槽。 */
export function nextRunText(data) {
  const source = data || {};
  if (source.mode !== "fixed") return "未开启固定时刻，当前按间隔同步";
  if (source.paused) return "已暂停，恢复后才排下一槽";
  if (!source.nextRunAt) return "暂无下一次执行时刻";
  try {
    return `${formatBeijing(source.nextRunAt)}（北京时间）`;
  } catch (_err) {
    return String(source.nextRunAt);
  }
}

/** 绑定模式文案（固定时刻时列出规范化后的时刻）。 */
export function modeText(data) {
  const source = data || {};
  const times = Array.isArray(source.times) ? source.times : [];
  if (source.mode === "fixed") {
    return `固定时刻 · 共 ${times.length} 个：${times.join("、")}`;
  }
  if (source.mode === "interval") return "间隔同步（未开启固定时刻）";
  return "未配置调度绑定";
}

/**
 * 当天槽摘要 -> 界面行（状态中文 + TONE + 补跑/重试说明）。
 * `nowMs` 只为测试/回放注入，缺省用浏览器当前时刻。
 */
export function todayRows(data, nowMs) {
  const source = data || {};
  const rows = Array.isArray(source.today) ? source.today : [];
  const now = beijingParts(nowMs === undefined || nowMs === null ? Date.now() : nowMs);
  const clock = `${pad2(now.hour)}:${pad2(now.minute)}`;
  return rows.map((row) => {
    const status = text(row && row.status);
    const scheduledTime = text(row && row.scheduledTime);
    const attempt = Number(row && row.attempt) || 0;
    // 已过点且仍在等待：当天补跑（只补当天，不补前几天）。
    const catchUp = status === "pending" && scheduledTime !== "" && scheduledTime < clock;
    const details = [];
    if (catchUp) details.push("已过点，等待补跑");
    if (attempt > 1) details.push(`第 ${attempt} 次尝试`);
    if (status === "failed" && text(row && row.lastErrorCode)) {
      details.push(`错误码 ${text(row.lastErrorCode)}`);
    }
    return {
      scheduledTime,
      status,
      statusText: STATUS_LABELS[status] || "未知状态",
      tone: STATUS_TONES[status] || TONE.off,
      catchUp,
      detail: details.join(" · "),
    };
  });
}

export default function SchedulePage({ plugin, nowMs }) {
  const pluginId = (plugin && plugin.id) || "sync-control";
  const [project, setProject] = useState({ loading: true, id: "", name: "", missing: false });
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({ times: [""], paused: false });
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    const current = ++seq.current;
    let alive = true;
    const run = async () => {
      setLoadError(null);
      let projects = null;
      try {
        projects = await api(PROJECTS_PATH);
      } catch (_err) {
        projects = null;
      }
      if (!alive || current !== seq.current) return;
      const active = text(projects && projects.active);
      if (!active) {
        setProject({ loading: false, id: "", name: "", missing: true });
        setData(null);
        return;
      }
      const matched = (projects.projects || []).find((item) => item && item.id === active);
      setProject({
        loading: false,
        id: active,
        name: text(matched && matched.name) || active,
        missing: false,
      });
      try {
        const binding = await api(`${BINDING_PATH}?projectId=${encodeURIComponent(active)}`);
        if (!alive || current !== seq.current) return;
        setData(binding);
        setDraft(bindingDraft(binding));
      } catch (err) {
        if (!alive || current !== seq.current) return;
        setLoadError(err);
      }
    };
    run();
    return () => {
      alive = false;
    };
  }, [reloadToken]);

  const updateTime = (index, value) => {
    setDraft((prev) => {
      const times = prev.times.slice();
      times[index] = value;
      return { ...prev, times };
    });
    setSaveError(null);
  };

  const addTime = () => setDraft((prev) => ({ ...prev, times: prev.times.concat([""]) }));

  const removeTime = (index) =>
    setDraft((prev) => ({ ...prev, times: prev.times.filter((_item, at) => at !== index) }));

  const togglePause = () => setDraft((prev) => ({ ...prev, paused: !prev.paused }));

  const reload = () => {
    setNotice("");
    setSaveError(null);
    setProject((prev) => ({ ...prev, loading: true }));
    setReloadToken((value) => value + 1);
  };

  const save = async () => {
    if (!project.id) return;
    setSaving(true);
    setSaveError(null);
    setNotice("");
    try {
      const next = await api(`${BINDING_PATH}/${encodeURIComponent(project.id)}`, {
        method: "PUT",
        body: { times: payloadTimes(draft.times), paused: Boolean(draft.paused) },
      });
      setData(next);
      setDraft(bindingDraft(next));
      setNotice(next && next.mode === "fixed" ? "已保存固定时刻" : "已关闭固定时刻，回到间隔同步");
    } catch (err) {
      // 后端 message 原位显示；草稿（用户输入）保持原样，不清空。
      setSaveError({ field: "times", message: text(err && err.message) || "保存失败，请稍后重试" });
    } finally {
      setSaving(false);
    }
  };

  const header = html`<header class="vk-page-header">
    <div>
      <h2>调度时刻</h2>
      ${!project.missing && !project.loading &&
      html`<p class="vk-muted" data-role="project">当前项目：${project.name || project.id}</p>`}
    </div>
  </header>`;

  if (project.missing) {
    return html`<div class="vk-page sched-page" data-plugin=${pluginId}>
      ${header}
      <p class="vk-state is-empty" data-state="unconfigured">
        未配置项目：读不到当前项目，暂时无法设置调度时刻。请先在工作台创建或切换项目。
      </p>
    </div>`;
  }

  if (project.loading || (!data && !loadError)) {
    return html`<div class="vk-page sched-page" data-plugin=${pluginId}>
      ${header}
      <p class="vk-state is-loading" aria-busy="true" data-state="loading">正在读取调度设置…</p>
    </div>`;
  }

  if (loadError) {
    return html`<div class="vk-page sched-page" data-plugin=${pluginId}>
      ${header}
      <div class="vk-state is-error" role="alert" data-state="error">
        <span>${text(loadError.message) || "读取调度设置失败"}</span>
        <button type="button" class="vk-btn" data-action="reload" onClick=${reload}>重新加载</button>
      </div>
    </div>`;
  }

  const rows = todayRows(data, nowMs);

  return html`<div class="vk-page sched-page" data-plugin=${pluginId}>
    <header class="vk-page-header">
      <div>
        <h2>调度时刻</h2>
        <p class="vk-muted" data-role="project">当前项目：${project.name || project.id}</p>
      </div>
      <div class="vk-page-actions">
        <span class="vk-muted" aria-live="polite" data-role="notice">${notice || (saving ? "正在保存…" : "")}</span>
        <button type="button" class="vk-btn" data-action="reload" disabled=${saving} onClick=${reload}>重新加载</button>
      </div>
    </header>

    <section class="sched-next" aria-label="下次执行">
      <h3>下次执行</h3>
      <p data-role="next-run">${nextRunText(data)}</p>
      <p class="vk-muted" data-role="mode">${modeText(data)}</p>
    </section>

    <section class="sched-form" aria-label="调度时刻设置">
      <h3>固定时刻</h3>
      <p class="vk-muted">
        北京时间，按 HH:MM 填写；保存后由后台调度器按这些时刻执行。
        0 个时刻保存后等于关闭固定时刻，回到间隔同步。
      </p>
      ${draft.times.map((value, index) => html`<div class="sched-row" key=${index}>
        <input
          type="text"
          class="vk-input"
          inputMode="numeric"
          maxLength="5"
          placeholder="HH:MM"
          aria-label=${`第 ${index + 1} 个调度时刻`}
          aria-invalid=${isInvalidTime(value) ? "true" : "false"}
          data-time-index=${index}
          value=${value}
          onInput=${(event) => updateTime(index, event.currentTarget.value)}
        />
        <button
          type="button"
          class="vk-btn"
          data-action="remove-time"
          data-time-index=${index}
          onClick=${() => removeTime(index)}
        >删除</button>
        ${isInvalidTime(value) && html`<span class="sched-hint" data-role="time-hint">格式应为 HH:MM</span>`}
      </div>`)}
      <div class="sched-actions">
        <button type="button" class="vk-btn" data-action="add-time" onClick=${addTime}>添加时刻</button>
        <label class="sched-pause">
          <input type="checkbox" data-action="toggle-pause" checked=${Boolean(draft.paused)} onChange=${togglePause} />
          <span>暂停固定时刻调度</span>
        </label>
        <button type="button" class="vk-btn is-primary" data-action="save" disabled=${saving} onClick=${save}>保存</button>
      </div>
      <p class="vk-muted">暂停期间到点的时刻标为「暂停跳过」，不补跑；恢复后从下一个时刻继续。</p>
      ${saveError && html`<p class="sched-error" role="alert" data-role="save-error" data-field=${saveError.field}>${saveError.message}</p>`}
    </section>

    <section class="sched-today" aria-label="今天的执行">
      <h3>今天的执行</h3>
      ${rows.length === 0
        ? html`<p class="vk-muted" data-role="today-empty">今天还没有到点的执行槽。</p>`
        : html`<ul class="sched-runs">
            ${rows.map((row) => html`<li
              class="sched-run"
              data-status=${row.status}
              data-tone=${row.tone}
              data-scheduled-time=${row.scheduledTime}
            >
              <span class="sched-run-time">${row.scheduledTime}</span>
              <span class=${`sched-run-status tone-${row.tone}`} data-tone=${row.tone}>${row.statusText}</span>
              ${row.detail && html`<span class="vk-muted sched-run-detail">${row.detail}</span>`}
            </li>`)}
          </ul>`}
    </section>
  </div>`;
}
