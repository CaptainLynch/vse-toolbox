/* Node membership rules are intentionally unset pending the business rule design.
 * buildContext accepts an explicit { milestoneId: [deliverableId] } rule result;
 * absence must never silently become the full project's deliverables.
 */
(function (root) {
  "use strict";
  const hasValue = item => !item.syncDisplay || ["manual", "snapshot"].includes(item.syncDisplay.state);
  const status = item => item.status || item.effectiveStatus;
  const hasDataIssue = item => !hasValue(item) || Boolean(item.syncDisplay && ["failed", "needs_attention"].includes(item.syncDisplay.syncState));
  const isRisk = item => hasValue(item) && status(item) !== "已完成" && (
    ["已逾期", "已超期", "受阻"].includes(status(item))
    || (item.scheduleState === "overdue" && (!item.syncDisplay || item.syncDisplay.state !== "snapshot"))
    || Boolean(item.note && !["无", "待同步", "—", "-"].includes(String(item.note).trim()))
  );

  function buildContext(data, rules = {}) {
    const milestones = [...(data.milestones || [])].sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
    const node = milestones.find(item => !["已完成", "已达成", "done"].includes(item.status)) || null;
    const all = data.deliverables || [];
    const ids = node && Object.prototype.hasOwnProperty.call(rules, String(node.id)) ? rules[String(node.id)] : null;
    const known = new Set(all.map(item => item.id));
    const ruleConfigured = Array.isArray(ids) && ids.every(id => typeof id === "string" && known.has(id));
    const items = ruleConfigured ? all.filter(item => ids.includes(item.id)) : [];
    const completed = ruleConfigured ? items.filter(item => hasValue(item) && status(item) === "已完成").length : null;
    const total = ruleConfigured ? items.length : null;
    const today = data.phase && data.phase.today;
    const delta = node && node.date && today ? (Date.parse(node.date) - Date.parse(today)) / 86400000 : NaN;
    return {
      node, ruleConfigured, items, total, completed,
      days: Number.isFinite(delta) ? Math.round(delta) : null,
      progress: total ? Math.round(completed / total * 100) : null,
      risks: items.filter(isRisk), dataIssues: items.filter(hasDataIssue),
      projectRisks: all.filter(isRisk), projectDataIssues: all.filter(hasDataIssue),
    };
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function detailLink(item) {
    const link = el("a", "node-detail-link", "查看明细 →");
    link.href = `#deliverable/${encodeURIComponent(item.id)}`;
    link.setAttribute("aria-label", `查看 ${item.name} 明细`);
    return link;
  }
  function renderRiskList(container, risks, dataIssues, configured = true) {
    if (!configured) {
      container.appendChild(el("p", "node-empty", "交付物规则待设置，暂不判断本节点风险。"));
      return;
    }
    if (!risks.length) container.appendChild(el("p", "node-empty", "现有可用数据中暂无风险或备注项。"));
    risks.forEach(item => {
      const row = el("div", "node-risk-row");
      const copy = el("div");
      const overdue = item.scheduleState === "overdue" && (!item.syncDisplay || item.syncDisplay.state !== "snapshot");
      const reason = overdue ? `计划已逾期${Number.isFinite(item.scheduleDays) ? ` ${item.scheduleDays} 天` : ""}` : status(item);
      const note = item.note && !["无", "待同步", "—", "-"].includes(String(item.note).trim()) ? ` · ${item.note}` : "";
      copy.append(el("strong", null, item.name), el("p", null, `${reason}${note}`));
      copy.appendChild(el("small", null, `负责人：${item.owner || "未填写"} · 计划：${item.plannedDate || "待排期"}`));
      row.append(copy, detailLink(item));
      container.appendChild(row);
    });
    if (dataIssues.length) {
      const warning = el("div", "node-data-warning");
      warning.appendChild(el("strong", null, `${dataIssues.length} 项数据待确认（同步异常或尚无有效数据）`));
      dataIssues.forEach(item => {
        const row = el("div", "node-risk-row");
        const label = hasValue(item) ? "更新异常 · 保留上次快照" : item.syncDisplay.label || item.syncDisplay.state;
        row.append(el("span", null, `${item.name} · ${label}`), detailLink(item));
        warning.appendChild(row);
      });
      container.appendChild(warning);
    }
  }
  function render(container, data, editPlan, rules = {}) {
    if (!container) return;
    container.textContent = "";
    const ctx = buildContext(data, rules);
    const head = el("div", "node-focus-head");
    const title = el("div");
    title.append(el("p", "eyebrow", "当前节点"), el("h3", "node-focus-title", ctx.node ? ctx.node.name : (data.milestones.length ? "主计划节点已全部完成" : "主计划待设置")));
    const edit = el("button", "timeline-edit-btn", "编辑主计划");
    edit.type = "button";
    edit.addEventListener("click", editPlan);
    head.append(title, edit);
    container.appendChild(head);
    if (!ctx.node) {
      container.appendChild(el("p", "node-empty", "可通过编辑主计划维护节点名称、日期、完成状态及顺序。"));
      return;
    }
    const timing = ctx.days === null ? "待排期" : ctx.days < 0 ? `已超期 ${-ctx.days} 天` : ctx.days === 0 ? "计划今天完成" : `距离计划日期还有 ${ctx.days} 天`;
    const bar = el("div", "node-focus-meta");
    bar.append(el("span", ctx.days < 0 ? "node-overdue" : "", `${ctx.node.status} · ${timing}`), el("span", null, `计划日期：${ctx.node.date || "未设置"}`));
    container.append(bar, el("p", "node-rule-note", "按主计划顺序定位第一个未完成节点；逾期不会自动跳过。"));
    const grid = el("div", "node-focus-grid");
    const deliveries = el("section", "node-focus-section");
    deliveries.appendChild(el("h4", null, "本节点交付物"));
    if (!ctx.ruleConfigured) {
      deliveries.append(el("strong", "node-rule-pending", "交付物规则待设置"), el("p", "node-empty", "后续按节点规则确定交付范围；下方全项目数据仅供参考，不计入本节点完成率。"));
    } else {
      deliveries.appendChild(el("p", "node-counts", ctx.total ? `已完成 ${ctx.completed} / ${ctx.total} 项 · ${ctx.progress}%` : "本节点规则未要求交付物"));
      ctx.items.forEach(item => {
        const row = el("div", "node-risk-row");
        row.append(el("span", null, `${item.name} · ${hasValue(item) ? status(item) : item.syncDisplay.label || item.syncDisplay.state}`), detailLink(item));
        deliveries.appendChild(row);
      });
    }
    const risks = el("section", "node-focus-section");
    risks.appendChild(el("h4", null, "本节点风险与备注"));
    renderRiskList(risks, ctx.risks, ctx.dataIssues, ctx.ruleConfigured);
    grid.append(deliveries, risks);
    container.appendChild(grid);
  }
  function renderProjectRisks(container, data) {
    if (!container) return;
    container.textContent = "";
    const context = buildContext(data);
    container.append(el("h4", null, "全项目风险与备注（参考）"), el("p", "node-rule-note", "此处展示全项目的逾期、受阻及人工备注，尚未按当前节点归属筛选。"));
    renderRiskList(container, context.projectRisks, context.projectDataIssues);
  }
  const api = { buildContext, render, renderProjectRisks };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VseNodeOverview = api;
})(typeof window === "undefined" ? globalThis : window);
