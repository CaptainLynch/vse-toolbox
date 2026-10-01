// Data loading shared by the status / details pages (legacy loadProjectOverview)
// plus the small state components every overview band uses.
import { html, useCallback, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { PROJECT_PHASE_ID, redactText, request } from "./client.js";
import { overviewErrorText, overviewIsEmpty } from "./status-logic.js";

export const PROJECT_STATUS_PATH = `/api/project-status?phase=${PROJECT_PHASE_ID}`;

/** GET /api/project-status with a request sequence so stale responses are dropped. */
export function useProjectStatus() {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const seq = useRef(0);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; seq.current += 1; }, []);

  /** quiet: keep the current data on screen while refetching (after a sync). */
  const reload = useCallback(async ({ quiet = false } = {}) => {
    const current = ++seq.current;
    if (!quiet) setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const data = await request(PROJECT_STATUS_PATH);
      if (!alive.current || current !== seq.current) return;
      setState({ data: data || null, loading: false, error: null });
    } catch (error) {
      if (!alive.current || current !== seq.current) return;
      setState({ data: null, loading: false, error: overviewErrorText(error) || "未知错误" });
    }
  }, []);

  /** Replace with the projectStatus a successful PATCH returned (no refetch). */
  const replace = useCallback((data) => {
    seq.current += 1;
    setState({ data, loading: false, error: null });
  }, []);

  useEffect(() => { reload(); }, [reload]);
  const retry = useCallback(() => reload(), [reload]);
  return { ...state, reload, retry, replace };
}

/** Legacy per-band state: 加载中 / 暂无数据 / 加载失败：… + 重试. Returns null when ready. */
export function BandState({ loading, error, data, onRetry }) {
  if (loading) return html`<p class="loading">加载中</p>`;
  if (error) {
    return html`<div class="overview-load-error">
      <p class="error-msg" role="alert">加载失败：${redactText(error)}</p>
      <button type="button" class="overview-retry-btn" onClick=${onRetry}>重试</button>
    </div>`;
  }
  if (!data || overviewIsEmpty(data)) return html`<p class="is-empty">暂无数据</p>`;
  return null;
}

/** Text with sensitive values redacted; blank becomes "-" (legacy safeDisplayValue). */
export function safeDisplayValue(value) {
  const text = redactText(value);
  return text.trim() ? text : "-";
}
