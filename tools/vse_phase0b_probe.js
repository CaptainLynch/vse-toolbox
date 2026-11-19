/*
 * VSE Toolbox 阶段 0B 只读取证（在 VSE Toolbox 自己的页面里运行，生产机不需要 Python）
 *
 * 用法：打开 VSE Toolbox 网页（http://127.0.0.1:端口/），点书签「VSE 取证」，
 *       或 F12 → Console 粘贴本文件全文回车。
 * 产出：下载目录里的 vse_phase0b_<时间>.json，交回即可。
 *
 * 只调用 GET 接口（归档任务列表、D5/D2 更新策略、数模表单视图与行），不改任何配置、不触发同步。
 */
(async () => {
  "use strict";

  const SCRIPT_VERSION = "2026-11-19.1";
  const PAGE_LIMIT = 500;
  const MAX_ROWS = 20000;

  if (typeof location !== "undefined" && !/^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname)) {
    console.error("[vse-probe] 请在 VSE Toolbox 网页（127.0.0.1）里运行");
    return;
  }
  const BASE = typeof location !== "undefined" ? location.origin : "http://127.0.0.1:5000";
  const log = (...a) => console.log("[vse-probe]", ...a);
  const bundle = { scriptVersion: SCRIPT_VERSION, startedAt: new Date().toISOString(), calls: [] };

  async function get(path) {
    const rec = { path };
    try {
      const resp = await fetch(BASE + path, { credentials: "same-origin", headers: { accept: "application/json" } });
      rec.status = resp.status;
      const text = await resp.text();
      try { rec.body = JSON.parse(text); } catch (_) { rec.body = text.slice(0, 2000); }
    } catch (err) {
      rec.error = String(err);
    }
    bundle.calls.push(rec);
    return rec;
  }

  // 1. 归档任务（含筛选条件）
  await get("/api/scheduled-archive/jobs");
  // 2. 数模 / SOR 交付物的更新策略（含绑定的 matchRule）
  for (const id of ["VPI-T2-D5", "VPI-T2-D2"]) {
    await get(`/api/project-status/deliverables/${encodeURIComponent(id)}/update-policy`);
  }
  // 3. 数模表单视图（快照时间、覆盖范围、表头）
  await get("/api/deliverable-forms/tdc_data_model/view");
  // 4. 最新快照的全部行（只保留值与维度，丢掉其它字段以控制体积）
  const rows = [];
  let total = null;
  for (let offset = 0; offset < MAX_ROWS; offset += PAGE_LIMIT) {
    const rec = await get(`/api/deliverable-forms/tdc_data_model/rows?offset=${offset}&limit=${PAGE_LIMIT}`);
    const data = rec.body && rec.body.data;
    if (!data || !Array.isArray(data.items)) break;
    total = data.total;
    for (const item of data.items) rows.push({ values: item.values, dimensions: item.dimensions });
    rec.body = { ok: rec.body.ok, data: { total: data.total, offset: data.offset, limit: data.limit, itemCount: data.items.length } };
    if (data.items.length === 0 || rows.length >= total) break;
  }
  bundle.tdcRows = { total, fetched: rows.length, rows };
  bundle.finishedAt = new Date().toISOString();
  log("完成：", bundle.calls.length, "次请求，数模行", rows.length, "/", total);

  const json = JSON.stringify(bundle);
  if (typeof document !== "undefined") {
    const stamp = bundle.startedAt.replace(/[-:T]/g, "").slice(0, 14);
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url; a.download = `vse_phase0b_${stamp}.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  if (typeof window !== "undefined") window.__vsePhase0b = bundle;
})();
