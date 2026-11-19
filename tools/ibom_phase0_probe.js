/*
 * iBOM 阶段 0A 只读取证脚本（浏览器控制台运行）
 *
 * 用法：在已登录的 https://ibom.sgmw.com.cn 页面按 F12 → Console，粘贴本文件全部内容回车。
 *       （Chrome/Edge 首次粘贴会要求先输入 allow pasting。）
 * 产出：下载目录里两个文件
 *       ibom_phase0_<时间>.json        全部请求/响应（不含 usertoken）
 *       数模设计审核流程报表_<日期>.xlsx  DMM 报表原件（服务端给的文件名）
 *
 * 只调用查询类接口（find / query / count / export），不发起审批、不保存、不删除。
 * 猜测的接口名调不通时只会记一条失败，不影响其它步骤。
 */
(async () => {
  "use strict";

  const SCRIPT_VERSION = "2026-11-18.1";
  const MAX_RESP_CHARS = 400000;
  const PAGE_SIZE = 50;
  const MAX_LIST_ROWS = 5000;
  const SAMPLES_PER_STATUS = 2;
  const DELAY_MS = 150;

  if (typeof location !== "undefined" && !/(^|\.)ibom\.sgmw\.com\.cn$/.test(location.hostname)) {
    console.error("[ibom-probe] 请在 ibom.sgmw.com.cn 的页面里运行");
    return;
  }
  const BASE = typeof location !== "undefined" ? location.origin : "https://ibom.sgmw.com.cn";

  // ── MD5（x-content-md5 = 请求体原文 UTF-8 字节的 hex MD5）────────────────
  function md5(text) {
    const bytes = new TextEncoder().encode(text);
    const n = bytes.length;
    const words = new Array((((n + 8) >>> 6) + 1) * 16).fill(0);
    for (let i = 0; i < n; i++) words[i >> 2] |= bytes[i] << ((i % 4) * 8);
    words[n >> 2] |= 0x80 << ((n % 4) * 8);
    words[words.length - 2] = (n * 8) >>> 0;
    words[words.length - 1] = Math.floor((n * 8) / 0x100000000) >>> 0;
    const S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];
    const K = [];
    for (let i = 0; i < 64; i++) K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 0x100000000) >>> 0;
    let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
    for (let off = 0; off < words.length; off += 16) {
      let A = a0, B = b0, C = c0, D = d0;
      for (let i = 0; i < 64; i++) {
        let F, g;
        if (i < 16) { F = (B & C) | (~B & D); g = i; }
        else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) % 16; }
        else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) % 16; }
        else { F = C ^ (B | ~D); g = (7 * i) % 16; }
        const s = S[(i >> 4) * 4 + (i % 4)];
        const tmp = D; D = C; C = B;
        const sum = (A + F + K[i] + words[off + g]) >>> 0;
        B = (B + ((sum << s) | (sum >>> (32 - s)))) >>> 0;
        A = tmp;
      }
      a0 = (a0 + A) >>> 0; b0 = (b0 + B) >>> 0; c0 = (c0 + C) >>> 0; d0 = (d0 + D) >>> 0;
    }
    return [a0, b0, c0, d0].map(v => {
      let h = "";
      for (let j = 0; j < 4; j++) h += ((v >>> (j * 8)) & 0xff).toString(16).padStart(2, "0");
      return h;
    }).join("");
  }

  // ── 请求封装 ───────────────────────────────────────────────────────
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const traceId = () => Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
  const bundle = {
    scriptVersion: SCRIPT_VERSION,
    startedAt: new Date().toISOString(),
    page: typeof location !== "undefined" ? location.pathname : "",
    cookieNamesVisibleToJs: typeof document !== "undefined"
      ? document.cookie.split(";").map(c => c.split("=")[0].trim()).filter(Boolean) : [],
    auth: {},
    calls: [],
    summary: {},
  };
  let auth = null;

  async function call(path, body, { raw = false, step = "" } = {}) {
    const text = body === undefined ? "" : JSON.stringify(body);
    const headers = {
      accept: "application/json, text/plain, */*",
      needhtmlescape: "false",
      userlanguage: "zh_CN",
      "x-g-tenant-id": "",
      "x-g-trace-id": traceId(),
      "x-content-md5": md5(text),
    };
    if (text) headers["content-type"] = "application/json";
    if (auth) {
      headers.usertoken = auth.token;
      headers.userloginname = auth.login;
      headers.logintype = auth.loginType;
      headers.locale = "zh_CN";
    }
    const rec = { step, path, request: body === undefined ? null : body };
    try {
      const resp = await fetch(BASE + path, {
        method: "POST", headers, body: text || undefined, credentials: "include",
      });
      rec.status = resp.status;
      rec.processResult = resp.headers.get("x-g-process-result");
      rec.contentType = resp.headers.get("content-type");
      rec.contentDisposition = resp.headers.get("content-disposition");
      if (raw) {
        const blob = await resp.blob();
        rec.bytes = blob.size;
        bundle.calls.push(rec);
        await sleep(DELAY_MS);
        return { rec, blob };
      }
      const bodyText = await resp.text();
      let json = null;
      try { json = bodyText ? JSON.parse(bodyText) : null; } catch (_) { /* 非 JSON */ }
      rec.state = json && json.state;
      rec.ok = resp.ok && rec.processResult !== "error" && rec.state === "success";
      const kept = json === null ? bodyText : JSON.stringify(json);
      rec.response = kept.length > MAX_RESP_CHARS ? kept.slice(0, MAX_RESP_CHARS) : (json === null ? bodyText : json);
      rec.truncated = kept.length > MAX_RESP_CHARS;
      bundle.calls.push(rec);
      await sleep(DELAY_MS);
      return { rec, json, data: json ? json.data : undefined };
    } catch (err) {
      rec.error = String(err);
      bundle.calls.push(rec);
      return { rec, json: null, data: undefined };
    }
  }

  const hasData = d => Array.isArray(d) ? d.length > 0
    : d && typeof d === "object" ? (Array.isArray(d.content) ? d.content.length > 0 : Object.keys(d).length > 0)
    : d !== undefined && d !== null;

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  const log = (...args) => console.log("[ibom-probe]", ...args);

  // ── 1. 会话：checkToken 换 usertoken（前端也这么做，失败重试一次）───────
  let tok = await call("/fwSecurity/authentication/checkToken.api", undefined, { step: "auth" });
  if (!tok.rec.ok) { await sleep(3000); tok = await call("/fwSecurity/authentication/checkToken.api", undefined, { step: "auth-retry" }); }
  if (!tok.rec.ok || !tok.data || !tok.data.userToken) {
    console.error("[ibom-probe] checkToken 失败，请确认已登录 iBOM 后重试");
    return;
  }
  auth = { token: tok.data.userToken, login: tok.data.userLoginName, loginType: tok.data.loginType || "DEFAULT_SSO" };
  bundle.auth = { loginType: auth.loginType, delegateMode: tok.data.delegateMode, hasToken: true };
  for (const c of bundle.calls) if (c.response && c.response.data && c.response.data.userToken) c.response.data.userToken = "<redacted>";
  log("会话就绪，loginType =", auth.loginType);

  const agg = await call("/fwSecurity/security/findUserAggregateInfo.api", undefined, { step: "account" });
  if (agg.data) {
    bundle.summary.roles = (agg.data.roles || []).map(r => r.roleName);
    bundle.summary.dmmFunctions = (agg.data.functions || []).filter(f => /数模|发布管理|PAA|SOR/.test(f));
    // 权限全量 functions 已在原始响应里，摘要只留相关项
  }

  // ── 2. DMM 全量列表 + A 面计数 ────────────────────────────────────
  const dmmWhere = [{ fieldName: "DISCRIMINATOR", operator: "EMPTY", value: "DMM" }];
  const rows = [];
  let total = null;
  for (let begin = 0; begin < MAX_LIST_ROWS; begin += PAGE_SIZE) {
    const r = await call("/bommgmt/change/smartQuery.api",
      { whereList: dmmWhere, filterInfo: {}, pageInfo: { beginIndex: begin, pageSize: PAGE_SIZE } },
      { step: "dmm-list" });
    if (!r.data || !Array.isArray(r.data.content)) break;
    total = r.data.totalCount;
    rows.push(...r.data.content);
    if (r.data.content.length === 0 || rows.length >= total) break;
  }
  const statusCount = {};
  for (const row of rows) statusCount[row.changeStatus] = (statusCount[row.changeStatus] || 0) + 1;
  bundle.summary.dmm = {
    totalCount: total, fetched: rows.length, statusCount,
    changeTypes: [...new Set(rows.map(r => r.changeType))],
    projectNames: [...new Set(rows.map(r => r.projectName))].slice(0, 200),
    changeCodeRange: rows.length ? [rows.map(r => r.changeCode).sort()[0], rows.map(r => r.changeCode).sort().slice(-1)[0]] : null,
    allChangeCodes: rows.map(r => r.changeCode),
  };
  log("DMM 列表", total, "条，状态分布", statusCount);

  const asuf = await call("/bommgmt/change/smartQuery.api",
    { whereList: [{ fieldName: "DISCRIMINATOR", operator: "EMPTY", value: "ASUF" }], filterInfo: {}, pageInfo: { beginIndex: 0, pageSize: 5 } },
    { step: "asuf-count" });
  bundle.summary.asufTotal = asuf.data ? asuf.data.totalCount : null;

  // 按单号搜索（模糊）：验证能否用单号直接查，替代全量抓取
  if (rows.length) {
    const code = rows[0].changeCode;
    for (const fieldName of ["CHANGE_CODE", "changeCode"]) {
      const r = await call("/bommgmt/change/smartQuery.api",
        { whereList: [{ fieldName, operator: "LIKE", value: code }, ...dmmWhere], filterInfo: {}, pageInfo: { beginIndex: 0, pageSize: 5 } },
        { step: "search-by-code:" + fieldName });
      bundle.summary["searchByCode_" + fieldName] = r.data ? r.data.totalCount : null;
    }
  }

  // ── 3. DMM 的 recTypeId（工作流/附件/页签都要它）────────────────────
  const classCandidates = [
    "com.gantang.prd.chgmgmt.model.PartDigitalModelChange",
    "com.gantang.prd.chgmgmt.model.DigitalModelChange",
    "com.gantang.prd.chgmgmt.model.PartDigitalModel",
    "com.gantang.prd.chgmgmt.model.Dmm",
    "com.gantang.prd.chgmgmt.model.EngineerChangeOrder",
    "com.gantang.prd.chgmgmt.model.EngineerChangeRequest",
  ];
  const recTypes = {};
  for (const className of classCandidates) {
    const r = await call("/mstdata/recordType/getId.api", { className }, { step: "recordType" });
    if (r.data && r.data.recTypeId) recTypes[className] = r.data.recTypeId;
  }
  bundle.summary.recTypes = recTypes;
  const dmmRecTypeIds = [...new Set(Object.entries(recTypes)
    .filter(([k]) => !/EngineerChange/.test(k)).map(([, v]) => v))];
  const fallbackRecTypeIds = [...new Set(Object.values(recTypes))];
  log("recTypeId", recTypes);

  // ── 4. 每种状态取样，逐个探测详情/零件/签署栏/审批流 ─────────────────
  const samples = [];
  for (const st of ["APPROVAL", "PUBLISH", "RETURNED", "DRAFT", "CANCEL"]) {
    samples.push(...rows.filter(r => r.changeStatus === st).slice(0, SAMPLES_PER_STATUS));
  }
  const bizTypes = ["partDesign", "partDigitalModel", "digitalModel", "partModel",
    "signOff", "partDigitalModelSignOff", "signOffContent", "partAssembly"];
  const guessed = [
    ["/bommgmt/partDigitalModelChange/findById.api", s => ({ id: s.id })],
    ["/bommgmt/partDigitalModelChange/findPartList.api", s => ({ filterInfo: { changeId: s.id }, pageInfo: { beginIndex: 0, pageSize: 200 } })],
    ["/bommgmt/partDigitalModelChange/findModelList.api", s => ({ filterInfo: { changeId: s.id }, pageInfo: { beginIndex: 0, pageSize: 200 } })],
    ["/bommgmt/partDigitalModelChange/findSignOff.api", s => ({ changeId: s.id })],
    ["/bommgmt/partDigitalModelChange/findSignOffList.api", s => ({ filterInfo: { changeId: s.id }, pageInfo: { beginIndex: 0, pageSize: 200 } })],
    ["/bommgmt/partDigitalModelSignOff/findByChangeId.api", s => ({ id: s.id })],
    ["/bommgmt/partDigitalModel/findByChangeId.api", s => ({ id: s.id })],
  ];
  const sampleResults = [];
  for (const s of samples) {
    const res = { id: s.id, changeCode: s.changeCode, status: s.changeStatus, hits: {} };
    const mark = (k, r) => { res.hits[k] = r.rec.ok ? (hasData(r.data) ? "data" : "empty") : ("fail:" + (r.rec.status || r.rec.error)); };
    const tag = "sample:" + s.changeCode;

    mark("change/findById", await call("/bommgmt/change/findById.api", { id: s.id }, { step: tag }));
    mark("approvalNodes", await call("/bommgmt/changeNodeApproval/approvalNodes.api", { changeId: s.id }, { step: tag }));
    mark("findLogRecord", await call("/bommgmt/change/findLogRecord.api",
      { filterInfo: { bizNo: s.changeCode, dataSource: [], subTypes: [] }, pageInfo: { beginIndex: 0, pageSize: 100 }, sortInfo: { orderDirection: "DESC" } },
      { step: tag }));
    mark("isExistCount", await call("/bommgmt/changeOperation/isExistCount.api", { changeId: s.id, businessTypes: bizTypes }, { step: tag }));
    for (const bt of bizTypes) {
      mark("loadEntity:" + bt, await call("/bommgmt/changeOperation/loadEntity.api",
        { filterInfo: { changeId: s.id, businessType: bt }, pageInfo: { beginIndex: 0, pageSize: 200 } }, { step: tag }));
    }
    for (const [path, mk] of guessed) mark(path.replace("/bommgmt/", ""), await call(path, mk(s), { step: tag }));
    mark("changeNoticeEmployee", await call("/bommgmt/changeNoticeEmployee/find.api",
      { filterInfo: { formId: s.id, formType: "Change" }, pageInfo: { beginIndex: 0, pageSize: 50 } }, { step: tag }));

    for (const recTypeId of (dmmRecTypeIds.length ? dmmRecTypeIds : fallbackRecTypeIds)) {
      const p = await call("/fwWorkflow/workflowProcess/findProcessesByResourcesUri.api", { recId: s.id, recTypeId }, { step: tag });
      mark("findProcesses:" + recTypeId, p);
      const procs = Array.isArray(p.data) ? p.data : [];
      for (const proc of procs.slice(0, 2)) {
        mark("findAllTasks:" + recTypeId, await call("/fwWorkflow/workflowProcess/findAllTasks.api",
          { processId: proc.id, showFutureTasks: true }, { step: tag }));
      }
      mark("formActions:" + recTypeId, await call("/fwWorkflow/workflowProcess/findFormProcessActions.api", { recId: s.id, recTypeId }, { step: tag }));
      mark("fileFind:" + recTypeId, await call("/fwFile/file/find.api",
        { filterInfo: { recId: s.id, recTypeId }, pageInfo: { beginIndex: 0, pageSize: 50 } }, { step: tag }));
    }
    sampleResults.push(res);
    log("样本", s.changeCode, s.changeStatus, "完成");
  }
  bundle.summary.samples = sampleResults;

  // 详情页页签清单（contextCategory 通常等于 recTypeId）
  const ctx = {};
  for (const recTypeId of fallbackRecTypeIds) {
    const r = await call("/fwSecurity/security/getContextMenu.api", { contextCategory: String(recTypeId) }, { step: "contextMenu" });
    ctx[recTypeId] = r.rec.ok ? (Array.isArray(r.data) ? r.data.map(m => m.path || m.name) : "non-array") : "fail";
  }
  bundle.summary.contextMenus = ctx;

  // ── 5. DMM 报表导出（二进制直接存盘，不经文本通道）─────────────────────
  const exp = await call("/bommgmt/partDigitalModelChange/exportReport.api",
    { whereList: dmmWhere, filterInfo: {} }, { raw: true, step: "export" });
  let fname = "数模设计审核流程报表.xlsx";
  const cd = exp.rec.contentDisposition || "";
  const m = /filename\*?=(?:UTF-8'')?([^;]+)/i.exec(cd);
  if (m) { try { fname = decodeURIComponent(m[1].replace(/"/g, "").trim()); } catch (_) { /* 保留默认名 */ } }
  bundle.summary.export = { status: exp.rec.status, bytes: exp.rec.bytes, contentType: exp.rec.contentType, filename: fname };
  if (exp.blob && exp.rec.status === 200) saveBlob(exp.blob, fname);

  // ── 6. 汇总并下载 ──────────────────────────────────────────────────
  bundle.finishedAt = new Date().toISOString();
  bundle.summary.callCount = bundle.calls.length;
  bundle.summary.failedCalls = bundle.calls.filter(c => c.ok === false || c.error).length;
  const json = JSON.stringify(bundle, null, 1);
  if (auth && json.includes(auth.token)) {
    console.error("[ibom-probe] 结果里出现了 usertoken，已中止下载");
    return;
  }
  const stamp = bundle.startedAt.replace(/[-:T]/g, "").slice(0, 14);
  saveBlob(new Blob([json], { type: "application/json" }), `ibom_phase0_${stamp}.json`);
  console.table(sampleResults.map(r => ({ changeCode: r.changeCode, status: r.status, ...r.hits })));
  log("完成：", bundle.calls.length, "次调用，下载目录里有 JSON 与报表 xlsx");
  if (typeof window !== "undefined") window.__ibomPhase0 = bundle;
})();
