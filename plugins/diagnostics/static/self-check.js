// 专家模式系统自检页面：只读列表与诊断包导出
import { html, useCallback, useEffect, useState } from "/static/host/vendor/preact-htm.js";

export const STATE_CONFIG = {
  ok: { label: "正常", color: "#10b981", tone: "ok" },
  warn: { label: "提示", color: "#f59e0b", tone: "warn" },
  need_check: { label: "需要检查", color: "#f59e0b", tone: "need_check" },
  unknown: { label: "未知", color: "#9ca3af", tone: "unknown" },
  error: { label: "异常", color: "#ef4444", tone: "error" },
};

export async function triggerDiagnosticExport() {
  let resp = await fetch("/api/diagnostics", { cache: "no-store" });
  let status = await resp.json();
  let id = null;

  if (status && status.active) {
    const stopResp = await fetch("/api/diagnostics/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const stopData = await stopResp.json();
    id = stopData && stopData.latest && stopData.latest.id;
  } else if (status && status.latest && status.latest.id) {
    id = status.latest.id;
  } else {
    await fetch("/api/diagnostics/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const stopResp = await fetch("/api/diagnostics/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const stopData = await stopResp.json();
    id = stopData && stopData.latest && stopData.latest.id;
  }

  if (!id) {
    const recheck = await (await fetch("/api/diagnostics", { cache: "no-store" })).json();
    id = recheck && recheck.latest && recheck.latest.id;
  }

  if (!id) {
    throw new Error("未能生成诊断包");
  }

  if (typeof document !== "undefined" && document.createElement) {
    const link = document.createElement("a");
    link.href = `/api/diagnostics/bundles/${encodeURIComponent(id)}`;
    link.download = `vse-diagnostics-${id}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }
  return id;
}

export function StatusDot({ state }) {
  const conf = STATE_CONFIG[state] || STATE_CONFIG.unknown;
  return html`<span
    class="diag-dot"
    title=${conf.label}
    style=${`display:inline-block;width:10px;height:10px;border-radius:50%;background-color:${conf.color};flex-shrink:0;margin-top:5px;`}
  ></span>`;
}

export function SelfCheckItem({ item }) {
  const conf = STATE_CONFIG[item.state] || STATE_CONFIG.unknown;
  return html`<li class="diag-item" style="display:flex;align-items:flex-start;gap:12px;padding:12px;border-bottom:1px solid rgba(0,0,0,0.08);">
    <${StatusDot} state=${item.state} />
    <div style="flex:1;min-width:0;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
        <strong style="font-size:14px;color:#111827;">${item.name}</strong>
        <span style="font-size:12px;padding:2px 8px;border-radius:9999px;background-color:${conf.color}20;color:${conf.color};font-weight:500;">
          ${conf.label}
        </span>
      </div>
      <div style="font-size:13px;color:#4b5563;line-height:1.5;">${item.detail || "无详情说明"}</div>
      ${item.checkedAt && html`<div style="font-size:11px;color:#9ca3af;margin-top:4px;">检查时间：${item.checkedAt}</div>`}
    </div>
  </li>`;
}

export default function SelfCheckPage({ api }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportNotice, setExportNotice] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let data = null;
      if (api && typeof api.get === "function") {
        data = await api.get("self-check");
      } else {
        const resp = await fetch("/api/p/diagnostics/self-check", { headers: { Accept: "application/json" } });
        const json = await resp.json();
        data = json && json.ok ? json.data : null;
      }
      const list = Array.isArray(data) ? data : (data && data.items ? data.items : []);
      setItems(list);
    } catch (err) {
      setError(err.message || "读取自检状态失败");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    setExportNotice("正在生成并导出诊断包…");
    try {
      await triggerDiagnosticExport();
      setExportNotice("诊断包已成功导出");
    } catch (err) {
      setExportNotice("导出诊断包失败，请稍后重试");
    } finally {
      setExporting(false);
    }
  };

  return html`<div class="diag-page" style="max-width:800px;margin:24px auto;padding:0 16px;">
    <header style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
      <div>
        <h2 style="margin:0 0 4px;font-size:20px;font-weight:600;color:#111827;">系统自检</h2>
        <p style="margin:0;font-size:13px;color:#6b7280;">聚合本机运行环境、各服务会话与更新通道的只读状态</p>
      </div>
      <div style="display:flex;gap:8px;">
        <button
          type="button"
          class="vk-btn"
          style="padding:6px 14px;font-size:13px;border-radius:6px;border:1px solid #d1d5db;background:#fff;cursor:pointer;"
          onClick=${loadData}
          disabled=${loading}
        >
          ${loading ? "检查中…" : "刷新"}
        </button>
        <button
          type="button"
          class="vk-btn vk-btn-primary"
          style="padding:6px 14px;font-size:13px;border-radius:6px;border:none;background:#2563eb;color:#fff;cursor:pointer;"
          onClick=${handleExport}
          disabled=${exporting}
        >
          ${exporting ? "导出中…" : "导出诊断包"}
        </button>
      </div>
    </header>

    ${exportNotice && html`<div style="margin-bottom:16px;padding:8px 12px;background:#f3f4f6;border-radius:6px;font-size:13px;color:#374151;">${exportNotice}</div>`}

    ${error && html`<div style="margin-bottom:16px;padding:12px;background:#fef2f2;border:1px solid #fee2e2;border-radius:6px;color:#b91c1c;font-size:13px;">${error}</div>`}

    <section style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.05);overflow:hidden;">
      ${loading && items.length === 0
        ? html`<div style="padding:32px;text-align:center;color:#6b7280;font-size:14px;">正在自检关键服务状态…</div>`
        : html`<ul style="list-style:none;margin:0;padding:0;">
            ${items.map((item, idx) => html`<${SelfCheckItem} key=${item.name || idx} item=${item} />`)}
          </ul>`}
    </section>
  </div>`;
}
