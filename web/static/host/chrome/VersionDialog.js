// Version chip in the top bar and the version / runtime detail dialog.
import { html, useEffect, useRef } from "../vendor/preact-htm.js";
import { createStore } from "../session.js";
import { useStore } from "./SessionBadges.js";

export const DEFAULT_VERSION = "开发工作区";
const FALLBACK_DATA = { displayVersion: DEFAULT_VERSION, channel: "source", buildId: null, detail: "开发工作区 (源码运行)" };

export const versionStore = createStore({ data: null, open: false, initialText: DEFAULT_VERSION });

export async function loadAppVersion() {
  try {
    const resp = await fetch("/api/version", { cache: "no-store" });
    const body = await resp.json();
    if (resp.ok && body.ok && body.data) versionStore.set((prev) => ({ ...prev, data: body.data }));
  } catch (_) {
    // 无法获取版本时安全退化，保留默认展示
  }
}

export function openVersionDialog() {
  versionStore.set((prev) => ({ ...prev, open: true }));
}

function focusChip() {
  const chip = document.getElementById("hc-version-chip");
  if (chip) chip.focus();
}

export function closeVersionDialog() {
  if (!versionStore.get().open) return;
  versionStore.set((prev) => ({ ...prev, open: false }));
  focusChip();
}

export function VersionChip() {
  const { data, initialText } = useStore(versionStore);
  const text = data ? data.displayVersion || DEFAULT_VERSION : initialText;
  const title = data ? `应用版本: ${data.displayVersion} · 点击查看运行环境详情` : "点击查看版本与运行环境详情";
  const onKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openVersionDialog();
    }
  };
  return html`<span
    id="hc-version-chip"
    class="hc-version-chip"
    role="button"
    tabindex="0"
    title=${title}
    aria-label="应用版本信息"
    aria-haspopup="dialog"
    onClick=${openVersionDialog}
    onKeyDown=${onKeyDown}
  >${text}</span>`;
}

export function VersionDialog() {
  const { data, open } = useStore(versionStore);
  const closeRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    if (closeRef.current) closeRef.current.focus();
    const onKey = (event) => {
      if (event.key === "Escape") closeVersionDialog();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  const info = data || FALLBACK_DATA;
  return html`<div id="hc-version-dialog" class="hc-modal" role="dialog" aria-modal="true" aria-labelledby="hc-version-title">
    <div class="hc-modal-backdrop" onClick=${closeVersionDialog}></div>
    <div class="hc-modal-card hc-version-card" role="document">
      <div class="hc-modal-head">
        <div>
          <p class="hc-eyebrow">维护与诊断</p>
          <h3 id="hc-version-title">版本与运行环境</h3>
        </div>
        <button ref=${closeRef} class="hc-modal-close" type="button" aria-label="关闭" onClick=${closeVersionDialog}>×</button>
      </div>
      <div class="hc-version-body">
        <dl class="hc-version-dl">
          <dt>当前显示版本</dt><dd>${info.displayVersion || "-"}</dd>
          <dt>运行形态</dt><dd>${info.channel || "source"}</dd>
          <dt>构建标识</dt><dd>${info.buildId || "无独立构建标识"}</dd>
          <dt>运行环境详情</dt><dd>${info.detail || "-"}</dd>
        </dl>
        <p class="hc-field-note">维护提示：反馈问题时可复制上述版本标识并附带生成的诊断报告。</p>
      </div>
    </div>
  </div>`;
}
