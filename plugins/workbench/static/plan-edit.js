// 主计划时间轴直接编辑 + 表格模式（需求 C3）。
// 沿用主计划维护的既有保存接口（/api/project-status/phases/<phase_id>/milestones），
// 统一时间轴节点点击弹窗与表格行内编辑两种交互的保存实现与修订语义。
import { useState } from "/static/host/vendor/preact-htm.js";
import { Pill, api, html } from "./common.js";

/** 里程碑节点状态对应的统一样式色调 */
export const MILESTONE_TONE = Object.freeze({
  已完成: "ok",
  进行中: "info",
  未开始: "off",
  已超期: "bad",
});

/**
 * 校验里程碑节点日期合法性：
 * 1. 允许空日期（表示待排期/未排期）；
 * 2. 格式必须为标准的 YYYY-MM-DD；
 * 3. 必须位于阶段周期的开始与结束日期之内；
 * 4. 已达成节点日期不得晚于当前今天日期。
 *
 * @param {string|null|undefined} dateStr 待校验日期
 * @param {object} phase 阶段对象，包含 startDate, endDate, today
 * @param {string} [currentStatus] 当前状态
 * @returns {string|null} 校验失败时返回通俗中文提示，通过返回 null
 */
export function validateMilestoneDate(dateStr, phase = {}, currentStatus = "") {
  if (dateStr === null || dateStr === undefined || String(dateStr).trim() === "") {
    return null;
  }
  const clean = String(dateStr).trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(clean)) {
    return "日期格式应为 YYYY-MM-DD";
  }
  const parts = clean.split("-").map(Number);
  const parsed = new Date(parts[0], parts[1] - 1, parts[2]);
  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.getFullYear() !== parts[0] ||
    parsed.getMonth() !== parts[1] - 1 ||
    parsed.getDate() !== parts[2]
  ) {
    return "日期格式应为 YYYY-MM-DD";
  }
  if (phase.startDate && clean < phase.startDate) {
    return `节点日期需在阶段周期 ${phase.startDate} 至 ${phase.endDate || ""} 内`;
  }
  if (phase.endDate && clean > phase.endDate) {
    return `节点日期需在阶段周期 ${phase.startDate || ""} 至 ${phase.endDate} 内`;
  }
  if (currentStatus === "已完成" && phase.today && clean > phase.today) {
    return `已达成节点日期不能晚于当前日期 ${phase.today}`;
  }
  return null;
}

/**
 * 构建更新节点列表的请求载荷：
 * 保持后端同一全量节点替换语义，更新目标节点日期；若清空日期，
 * 按照后端规则将节点状态同步置为「未开始」（类型 planned），避免 422 报错。
 *
 * @param {Array} milestones 当前节点列表
 * @param {number|string} targetId 要更新的节点 ID
 * @param {string|null} newDate 新日期
 * @param {string} updatedAt 乐观锁版本号
 * @returns {object} { milestones: [...], updatedAt }
 */
export function buildMilestonesSavePayload(milestones, targetId, newDate, updatedAt) {
  const cleanDate = newDate && String(newDate).trim() ? String(newDate).trim() : null;
  const list = (milestones || []).map((m) => {
    if (m.id === targetId) {
      let nextStatus = m.status;
      let nextType = m.type;
      if (!cleanDate) {
        nextStatus = "未开始";
        nextType = "planned";
      }
      return {
        id: m.id,
        name: m.name,
        date: cleanDate,
        status: nextStatus,
        type: nextType,
        sortOrder: m.sortOrder,
      };
    }
    return {
      id: m.id,
      name: m.name,
      date: m.date || null,
      status: m.status,
      type: m.type,
      sortOrder: m.sortOrder,
    };
  });
  return {
    milestones: list,
    updatedAt: updatedAt || "",
  };
}

/**
 * 统一的主计划节点保存实现：
 * 时间轴弹窗与表格行内编辑共用同一网络请求与错误处理逻辑。
 */
export async function saveMilestoneDate({
  phaseId = "VPI-T2",
  milestones = [],
  milestoneId,
  newDate,
  phase = {},
  apiFn = api,
}) {
  const target = milestones.find((m) => m.id === milestoneId);
  const status = target ? target.status : "";
  const valError = validateMilestoneDate(newDate, phase, status);
  if (valError) {
    return { ok: false, error: valError };
  }
  const payload = buildMilestonesSavePayload(milestones, milestoneId, newDate, phase.updatedAt);
  try {
    const res = await apiFn(`/api/project-status/phases/${encodeURIComponent(phaseId)}/milestones`, {
      method: "PATCH",
      body: payload,
    });
    return { ok: true, data: res && res.data ? res.data : res };
  } catch (err) {
    const statusVal = err && (err.status || err.statusCode);
    const msg = String((err && err.message) || "");
    if (statusVal === 409 || msg.includes("409") || msg.includes("已被其他会话更新")) {
      return { ok: false, error: "主计划已被其他会话更新，请刷新后重试" };
    }
    return { ok: false, error: msg || "保存失败，请稍后重试" };
  }
}

/**
 * 时间轴渲染：未排期节点保持「去排期」跳转入口；已排期节点支持点击唤起日期编辑。
 */
export function PlanTimeline({ milestones, today, onEditMilestone }) {
  const list = milestones || [];
  const current = list.find((m) => m.status !== "已完成");
  return html`<div class="wb-timeline" role="list">
    ${list.map((m) => {
      const done = m.status === "已完成";
      const late = !done && m.date && m.date < today;
      const isCurrent = m === current;
      const cls = ["wb-node", done ? "is-done" : "", isCurrent ? "is-current" : "", late ? "is-late" : ""].join(" ");
      return html`<div
        class=${cls}
        role="listitem"
        key=${m.id}
        onClick=${m.date ? () => onEditMilestone && onEditMilestone(m) : undefined}
        style=${m.date ? "cursor:pointer" : ""}
      >
        <i class="dot"></i><b>${m.name}</b>
        <span>
          ${m.date
            ? html`<button
                type="button"
                class="wb-link"
                style="font-weight:600"
                onClick=${(e) => {
                  e.stopPropagation();
                  if (onEditMilestone) onEditMilestone(m);
                }}
                title="点击修改日期"
              >${m.date.slice(5)}</button>`
            : html`<a class="wb-link" href="#p/project-overview/plan">去排期</a>`}
        </span>
      </div>`;
    })}
  </div>`;
}

/**
 * 已排期节点的日期编辑弹窗
 */
export function PlanDateModal({ milestone, phase, onClose, onSave, saving, error }) {
  const [date, setDate] = useState(milestone ? milestone.date || "" : "");
  const [localError, setLocalError] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    const err = validateMilestoneDate(date, phase, milestone?.status);
    if (err) {
      setLocalError(err);
      return;
    }
    setLocalError("");
    onSave(milestone.id, date);
  };

  return html`
    <div class="wb-scrim" onClick=${(e) => { if (e.target === e.currentTarget && !saving) onClose(); }}>
      <form class="wb-modal" onSubmit=${handleSubmit} aria-label="修改节点日期">
        <h3 style="margin:0 0 8px">修改节点日期</h3>
        <p class="wb-sub" style="margin-bottom:16px">节点：<b>${milestone.name}</b></p>
        <label class="wb-field">
          <span>计划完成日期</span>
          <input
            type="date"
            value=${date}
            min=${phase.startDate || ""}
            max=${phase.endDate || ""}
            onInput=${(e) => { setDate(e.currentTarget.value); setLocalError(""); }}
            autofocus
          />
        </label>
        ${(localError || error) && html`<p class="wb-error" role="alert">${localError || error}</p>`}
        <div class="wb-row" style="margin-top:20px;justify-content:flex-end">
          <button type="button" class="wb-btn" onClick=${onClose} disabled=${saving}>取消</button>
          <button type="submit" class="wb-btn is-primary" disabled=${saving}>${saving ? "正在保存…" : "保存"}</button>
        </div>
      </form>
    </div>
  `;
}

/**
 * 表格批量编辑模式：阶段列表 + 里程碑日期列内联编辑，逐行保存
 */
export function PlanTable({ milestones, phase, onSaveRow, savingId, rowErrors = {} }) {
  const [drafts, setDrafts] = useState({});
  const list = milestones || [];

  const handleDateChange = (id, value) => {
    setDrafts((prev) => ({ ...prev, [id]: value }));
  };

  const handleSave = (m) => {
    const raw = drafts[m.id] !== undefined ? drafts[m.id] : m.date || "";
    onSaveRow(m.id, raw);
  };

  return html`<div class="wb-table-wrap">
    <table class="wb-table">
      <thead>
        <tr>
          <th>阶段节点</th>
          <th>状态</th>
          <th>里程碑日期</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${list.map((m) => {
          const currentVal = drafts[m.id] !== undefined ? drafts[m.id] : m.date || "";
          const isDirty = drafts[m.id] !== undefined && drafts[m.id] !== (m.date || "");
          const isSaving = savingId === m.id;
          const err = rowErrors[m.id];
          const tone = MILESTONE_TONE[m.status] || "off";
          return html`<tr key=${m.id}>
            <td><b>${m.name}</b></td>
            <td><${Pill} tone=${tone}>${m.status}<//></td>
            <td>
              <div class="wb-row" style="gap:10px">
                <input
                  type="date"
                  style="border:1px solid var(--hairline-strong);border-radius:8px;padding:5px 8px;font:inherit;background:var(--canvas);color:var(--ink)"
                  value=${currentVal}
                  min=${phase.startDate || ""}
                  max=${phase.endDate || ""}
                  onInput=${(e) => handleDateChange(m.id, e.currentTarget.value)}
                />
                ${!m.date && !currentVal && html`<a class="wb-link" href="#p/project-overview/plan">去排期</a>`}
              </div>
              ${err && html`<div class="wb-error wb-small" style="margin-top:4px">${err}</div>`}
            </td>
            <td>
              <button
                type="button"
                class="wb-btn"
                onClick=${() => handleSave(m)}
                disabled=${isSaving || !isDirty}
              >
                ${isSaving ? "保存中…" : "保存"}
              </button>
            </td>
          </tr>`;
        })}
      </tbody>
    </table>
  </div>`;
}

/**
 * 主计划区块：整合时间轴模式与表格模式，支持视图切换、节点弹窗与逐行保存
 */
export function PlanSection({ milestones = [], phase = {}, onReload, today }) {
  const [viewMode, setViewMode] = useState("timeline");
  const [editingMilestone, setEditingMilestone] = useState(null);
  const [modalSaving, setModalSaving] = useState(false);
  const [modalError, setModalError] = useState("");
  const [savingId, setSavingId] = useState(null);
  const [rowErrors, setRowErrors] = useState({});

  const phaseId = phase.id || "VPI-T2";
  const todayStr = today || phase.today || "";

  // 统一保存入口
  const handleSave = async (milestoneId, newDate) => {
    return await saveMilestoneDate({
      phaseId,
      milestones,
      milestoneId,
      newDate,
      phase,
      apiFn: api,
    });
  };

  // 时间轴弹窗保存回调
  const handleModalSave = async (milestoneId, newDate) => {
    setModalSaving(true);
    setModalError("");
    const res = await handleSave(milestoneId, newDate);
    setModalSaving(false);
    if (!res.ok) {
      setModalError(res.error);
      return;
    }
    setEditingMilestone(null);
    if (onReload) onReload();
  };

  // 表格模式逐行保存回调
  const handleTableRowSave = async (milestoneId, newDate) => {
    setSavingId(milestoneId);
    setRowErrors((prev) => ({ ...prev, [milestoneId]: "" }));
    const res = await handleSave(milestoneId, newDate);
    setSavingId(null);
    if (!res.ok) {
      setRowErrors((prev) => ({ ...prev, [milestoneId]: res.error }));
      return false;
    }
    if (onReload) onReload();
    return true;
  };

  return html`
    <section class="wb-card">
      <div class="wb-card-head">
        <div class="wb-row" style="gap:12px">
          <h3>主计划</h3>
          <div class="wb-row" style="gap:6px">
            <button
              type="button"
              class=${`wb-chip${viewMode === "timeline" ? " is-on" : ""}`}
              onClick=${() => setViewMode("timeline")}
            >时间轴</button>
            <button
              type="button"
              class=${`wb-chip${viewMode === "table" ? " is-on" : ""}`}
              onClick=${() => setViewMode("table")}
            >表格</button>
          </div>
        </div>
        <span class="wb-small wb-muted">今天 ${todayStr}</span>
      </div>

      ${viewMode === "timeline"
        ? html`<${PlanTimeline}
            milestones=${milestones}
            today=${todayStr}
            onEditMilestone=${(m) => { setEditingMilestone(m); setModalError(""); }}
          />`
        : html`<${PlanTable}
            milestones=${milestones}
            phase=${phase}
            onSaveRow=${handleTableRowSave}
            savingId=${savingId}
            rowErrors=${rowErrors}
          />`
      }

      ${editingMilestone && html`<${PlanDateModal}
        milestone=${editingMilestone}
        phase=${phase}
        onClose=${() => { if (!modalSaving) setEditingMilestone(null); }}
        onSave=${handleModalSave}
        saving=${modalSaving}
        error=${modalError}
      />`}
    </section>
  `;
}
