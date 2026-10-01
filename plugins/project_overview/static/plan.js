// 主计划维护 (project-overview plugin page). Parity port of the legacy
// #overview-plan-panel / #milestone-maintenance in web/static/app.js: phase
// metadata (form + inline rename) and the milestone editor, saved through the
// existing /api/project-status endpoints with optimistic `updatedAt` checks.
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { PROJECT_PHASE_ID, hashParams, pageHash, redactText, request } from "./shared/client.js";
import { OverviewTabs } from "./shared/tabs.js";
import { useLeaveGuard } from "./plan/guard.js";
import {
  DISCARD_CONFIRM,
  SWITCH_TO_MILESTONES_CONFIRM,
  buildMilestonePayload,
  buildPhaseNamePayload,
  buildPhasePayload,
  clearFieldError,
  isEmptyStatus,
  mapServerFieldErrors,
  milestoneDraftDirty,
  milestoneRowsFrom,
  moveRow,
  newMilestoneRow,
  phaseDraftDirty,
  phaseDraftFrom,
  removeRow,
  requestErrorText,
  updateRow,
  validateMilestoneRows,
} from "./plan/logic.js";
import { MilestoneEditForm, MilestoneReadonlyList } from "./plan/milestones.js";
import { PhaseEditForm, PhaseReadonlyCard } from "./plan/phase.js";

const STATUS_PATH = `/api/project-status?phase=${PROJECT_PHASE_ID}`;
const PHASE_PATH = `/api/project-status/phases/${PROJECT_PHASE_ID}`;
const MILESTONES_PATH = `/api/project-status/phases/${PROJECT_PHASE_ID}/milestones`;

function failureText(err) {
  const base = requestErrorText(err);
  if (!err || err.status !== 422 || !err.fields) return base;
  const fields = Object.values(err.fields).map((value) => String(value)).filter(Boolean);
  return fields.length ? `${base}：${fields.join("；")}` : base;
}

export default function PlanPage({ plugin }) {
  useStylesheet(`/plugins/${(plugin && plugin.id) || "project-overview"}/static/plan.css`);
  const rootRef = useRef(null);
  const seq = useRef(0);
  const localSeq = useRef(0);
  const savingRef = useRef(false);
  const [saved, setSaved] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [phaseMessage, setPhaseMessage] = useState("");
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState(null);
  const [focus, setFocus] = useState(null);
  const [restoreNotice, setRestoreNotice] = useState(false);
  const [editRequest, setEditRequest] = useState(() => hashParams().get("edit") || "");

  const savedRef = useRef(saved);
  savedRef.current = saved;
  const draftRef = useRef(draft);
  draftRef.current = draft;

  const isDirty = useCallback(() => {
    const current = draftRef.current;
    const state = savedRef.current;
    if (!current || !state) return false;
    if (current.kind === "phase") return phaseDraftDirty(state.phase, current);
    return milestoneDraftDirty(state.milestones, current.rows);
  }, []);

  const resetEditors = useCallback(() => {
    setDraft(null);
    setErrors({});
    setMessage(null);
    setPhaseMessage("");
  }, []);

  useLeaveGuard(isDirty, resetEditors, rootRef);

  const load = useCallback(async () => {
    const current = ++seq.current;
    setLoading(true);
    setLoadError("");
    try {
      const data = await request(STATUS_PATH);
      if (current !== seq.current) return;
      setSaved(data || null);
    } catch (err) {
      if (current !== seq.current) return;
      setSaved(null);
      setLoadError(requestErrorText(err));
    } finally {
      if (current === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    return () => { seq.current += 1; };
  }, [load]);

  // `#p/project-overview/plan?edit=milestones|phase` opens an editor directly
  // (replaces the legacy status tab's openMilestoneEditor shortcut).
  useEffect(() => {
    const onHash = () => setEditRequest(hashParams().get("edit") || "");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const startMilestoneEdit = useCallback(() => {
    const state = savedRef.current;
    if (!state || savingRef.current) return;
    if (draftRef.current && isDirty() && !window.confirm(SWITCH_TO_MILESTONES_CONFIRM)) return;
    setPhaseMessage("");
    setErrors({});
    setMessage(null);
    setRestoreNotice(false);
    setDraft({
      kind: "milestones",
      updatedAt: state.phase ? state.phase.updatedAt : "",
      rows: milestoneRowsFrom(state.milestones),
    });
    setFocus({ first: true });
  }, [isDirty]);

  const startPhaseEdit = useCallback(() => {
    const state = savedRef.current;
    if (!state || savingRef.current) return;
    if (isDirty() && !window.confirm(DISCARD_CONFIRM)) return;
    setErrors({});
    setMessage(null);
    setPhaseMessage("");
    setRestoreNotice(false);
    setDraft(phaseDraftFrom(state.phase));
  }, [isDirty]);

  useEffect(() => {
    if (!editRequest || !saved || isEmptyStatus(saved)) return;
    setEditRequest("");
    try {
      window.history.replaceState(null, "", pageHash("plan"));
    } catch (_err) {
      // replaceState may be unavailable in sandboxed frames; the editor still opens.
    }
    if (editRequest === "milestones") startMilestoneEdit();
    else if (editRequest === "phase") startPhaseEdit();
  }, [editRequest, saved, startMilestoneEdit, startPhaseEdit]);

  const setSavingState = (value) => {
    savingRef.current = value;
    setSaving(value);
  };

  // ------------------------------------------------------------ phase

  const savePhase = async () => {
    if (!draft || draft.kind !== "phase" || savingRef.current) return;
    setPhaseMessage("");
    const built = buildPhasePayload(draft);
    if (built.error) {
      setPhaseMessage(built.error);
      return;
    }
    setSavingState(true);
    try {
      const data = await request(PHASE_PATH, { method: "PATCH", body: built.payload });
      if (!data || !data.projectStatus || isEmptyStatus(data.projectStatus)) {
        throw new Error("保存响应缺少完整的项目状态，请重试");
      }
      setSaved(data.projectStatus);
      setDraft(null);
    } catch (err) {
      setPhaseMessage(redactText(failureText(err)));
    } finally {
      setSavingState(false);
    }
  };

  /** Inline rename; resolves to "" on success/no-op or the error text to show. */
  const renamePhase = async (value) => {
    const state = savedRef.current;
    if (!state || savingRef.current) return "";
    if (draftRef.current && draftRef.current.kind === "phase") return "";
    const body = buildPhaseNamePayload(state.phase, value);
    if (!body) return "";
    try {
      const data = await request(PHASE_PATH, { method: "PATCH", body });
      if (!data || !data.projectStatus || isEmptyStatus(data.projectStatus)) {
        throw new Error("数据已保存，但刷新最新状态未完成；请刷新当前视图更新显示，无需重新保存");
      }
      setSaved(data.projectStatus);
      return "";
    } catch (err) {
      return redactText(failureText(err));
    }
  };

  // ------------------------------------------------------- milestones

  const editRows = (update) => {
    setDraft((current) => (current && current.kind === "milestones" ? { ...current, rows: update(current.rows) } : current));
  };

  const onField = (localId, field, value) => {
    if (savingRef.current) return;
    editRows((rows) => rows.map((row) => (row.localId === localId ? updateRow(row, field, value) : row)));
    setErrors((current) => clearFieldError(current, localId, field));
  };

  const onMove = (localId, delta) => {
    if (savingRef.current) return;
    editRows((rows) => moveRow(rows, localId, delta));
    setFocus({ localId });
  };

  const onDelete = (localId) => {
    if (savingRef.current || !draft || draft.kind !== "milestones") return;
    const result = removeRow(draft.rows, localId);
    if (result.focus === undefined) return;
    editRows(() => result.rows);
    setFocus(result.focus ? { localId: result.focus } : { add: true });
  };

  const onAdd = () => {
    if (savingRef.current || !draft || draft.kind !== "milestones") return;
    localSeq.current += 1;
    const row = newMilestoneRow(localSeq.current, draft.rows.length);
    editRows((rows) => [...rows, row]);
    setFocus({ localId: row.localId });
  };

  const saveMilestones = async () => {
    if (!draft || draft.kind !== "milestones" || savingRef.current) return;
    setMessage(null);
    const found = validateMilestoneRows(draft.rows, saved && saved.phase);
    if (Object.keys(found).length) {
      setErrors(found);
      setFocus({ invalid: true });
      return;
    }
    setErrors({});
    // 删除全部节点后保存 → 服务端自动恢复默认节点模板（不再 422）。
    const hadNoRows = !draft.rows.length;
    const payload = buildMilestonePayload(draft.rows, draft.updatedAt);
    setSavingState(true);
    try {
      const data = await request(MILESTONES_PATH, { method: "PATCH", body: payload });
      if (!data || !data.projectStatus || isEmptyStatus(data.projectStatus)) {
        throw new Error("保存响应缺少完整的项目状态，请重试");
      }
      setSaved(data.projectStatus);
      setDraft(null);
      setRestoreNotice(hadNoRows);
    } catch (err) {
      const mapped = err && err.fields ? mapServerFieldErrors(err.fields, draft.rows) : {};
      const { draft: draftError, ...rowErrors } = mapped;
      setMessage({ tone: "error", text: redactText(draftError || requestErrorText(err)) });
      setErrors(rowErrors);
      if (Object.keys(rowErrors).length) setFocus({ invalid: true });
    } finally {
      setSavingState(false);
    }
  };

  const cancelMilestones = () => {
    if (savingRef.current) return;
    resetEditors();
  };

  const cancelPhase = () => {
    if (savingRef.current) return;
    setDraft(null);
    setPhaseMessage("");
  };

  // ------------------------------------------------------------ render

  let body;
  if (loading) {
    body = html`<p class="loading">加载中</p>`;
  } else if (loadError) {
    body = html`<div class="overview-load-error">
      <p class="error-msg">加载失败：${redactText(loadError)}</p>
      <button type="button" class="overview-retry-btn" onClick=${load}>重试</button>
    </div>`;
  } else if (!saved || isEmptyStatus(saved)) {
    body = html`<p class="is-empty">暂无数据</p>`;
  } else {
    const milestones = Array.isArray(saved.milestones) ? saved.milestones : [];
    body = html`
      <div class="phase-meta-section">
        ${draft && draft.kind === "phase"
          ? html`<${PhaseEditForm}
              draft=${draft}
              saving=${saving}
              message=${phaseMessage}
              onChange=${setDraft}
              onSave=${savePhase}
              onCancel=${cancelPhase}
            />`
          : html`<${PhaseReadonlyCard}
              key=${saved.phase.updatedAt || "phase"}
              phase=${saved.phase}
              saving=${saving}
              onEdit=${startPhaseEdit}
              onRename=${renamePhase}
            />`}
      </div>
      <div class="milestone-nodes-section">
        ${draft && draft.kind === "milestones"
          ? html`<${MilestoneEditForm}
              rows=${draft.rows}
              errors=${errors}
              message=${message}
              saving=${saving}
              focus=${focus}
              onField=${onField}
              onMove=${onMove}
              onDelete=${onDelete}
              onAdd=${onAdd}
              onSave=${saveMilestones}
              onCancel=${cancelMilestones}
            />`
          : html`<${MilestoneReadonlyList}
              milestones=${milestones}
              saving=${saving}
              restoreNotice=${restoreNotice}
              onEdit=${startMilestoneEdit}
            />`}
      </div>`;
  }

  return html`<div class="vk-page project-overview po-plan" ref=${rootRef}>
    <${OverviewTabs} current="plan" />
    <section class="overview-band milestone-maintenance-band" aria-label="主计划维护">
      <div class="band-head">
        <div>
          <p class="eyebrow">主计划</p>
          <h4>主计划维护</h4>
        </div>
      </div>
      <div class="milestone-maintenance" aria-busy=${loading ? "true" : "false"}>${body}</div>
    </section>
  </div>`;
}
