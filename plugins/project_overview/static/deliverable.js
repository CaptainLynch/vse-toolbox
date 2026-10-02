// #p/project-overview/deliverable?id=<id> — one deliverable's detail page
// (legacy renderDeliverableDetailPage). Loads the VPI-T2 project status and
// hands the matching deliverable to DeliverableDetail; panels reload when
// `version` changes (the legacy page re-rendered wholesale after a reload).
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { useStylesheet } from "/static/host/kit.js";
import { PROJECT_PHASE_ID, hashParams } from "./shared/client.js";
import { apiRequest, enc } from "./deliverable/api.js";
import { DeliverableDetail } from "./deliverable/detail.js";
import { errorText, safeDisplayValue } from "./deliverable/format.js";

const LIST_HASH = "#p/project-overview/details";

function currentId() {
  return String(hashParams().get("id") || "");
}

export default function DeliverablePage({ plugin }) {
  useStylesheet(`/plugins/${(plugin && plugin.id) || "project-overview"}/static/deliverable.css`);
  const [id, setId] = useState(currentId);
  const [state, setState] = useState({ status: "loading", data: null, error: "" });
  const [version, setVersion] = useState(0);
  const alive = useRef(true);
  const seq = useRef(0);

  useEffect(() => {
    alive.current = true;
    const onHash = () => {
      const next = currentId();
      setId((prev) => (prev === next ? prev : next));
    };
    window.addEventListener("hashchange", onHash);
    return () => {
      alive.current = false;
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  // Resolves true when a fresh overview replaced the current one.
  const reloadOverview = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const data = await apiRequest(`/api/project-status?phase=${enc(PROJECT_PHASE_ID)}`);
      if (!alive.current || mine !== seq.current) return false;
      setState({ status: "ready", data: data || {}, error: "" });
      setVersion((value) => value + 1);
      return true;
    } catch (err) {
      if (!alive.current || mine !== seq.current) return false;
      // Keep the last good overview on a failed background reload.
      setState((prev) => (prev.data ? prev : { status: "error", data: null, error: errorText(err) }));
      return false;
    }
  }, []);

  const replaceOverview = useCallback((projectStatus) => {
    if (!alive.current || !projectStatus) return;
    seq.current += 1;
    setState({ status: "ready", data: projectStatus, error: "" });
    setVersion((value) => value + 1);
  }, []);

  useEffect(() => { reloadOverview(); }, []);
  useEffect(() => { if (typeof window.scrollTo === "function") window.scrollTo(0, 0); }, [id]);

  if (!state.data && state.status === "loading") {
    return html`<div class="overview-deliverable-detail-view"><p class="loading">加载交付物明细与分析...</p></div>`;
  }
  if (!state.data) {
    return html`<div class="overview-deliverable-detail-view deliverable-detail-not-found">
      <p class="error-msg">项目概览加载失败：${state.error}</p>
      <div class="deliverable-detail-not-found-actions">
        <button type="button" class="btn is-secondary" onClick=${() => { setState({ status: "loading", data: null, error: "" }); reloadOverview(); }}>重试</button>
        <a class="segment back-to-list-btn" href=${LIST_HASH}>返回交付物列表</a>
      </div>
    </div>`;
  }
  const deliverables = Array.isArray(state.data.deliverables) ? state.data.deliverables : [];
  const item = deliverables.find((candidate) => candidate && candidate.id === id) || null;
  if (!item) {
    return html`<div class="overview-deliverable-detail-view deliverable-detail-not-found">
      <p class="error-msg">未找到编号为 "${safeDisplayValue(id)}" 的交付物</p>
      <a class="segment back-to-list-btn" href=${LIST_HASH}>返回交付物列表</a>
    </div>`;
  }
  return html`<div class="overview-deliverable-detail-view">
    <${DeliverableDetail}
      key=${item.id}
      item=${item}
      overview=${state.data}
      version=${version}
      reloadOverview=${reloadOverview}
      replaceOverview=${replaceOverview}
    />
  </div>`;
}
