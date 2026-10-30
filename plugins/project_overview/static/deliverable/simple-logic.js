// 简洁视图的纯逻辑（不 import preact，Node 测试可直接 import）：阶段文案、逾期列、
// 派生进度、同步结果文案。为什么单独成文件：这些口径必须能被门禁直接断言，
// 而不是只能靠浏览器里看。
import { redactSensitiveText } from "./format.js";

/** 阶段展示名的唯一来源是后端 schema.stageLabels（core.form_registry 的 stage_labels）。
 *  前端不另写阶段文案表；未登记的阶段回退原码，空阶段回退源表状态。 */
export function stageLabel(schema, row) {
  const labels = (schema && schema.stageLabels) || {};
  const dims = (row && row.dimensions) || {};
  const stage = String(dims.stage || "").trim();
  if (stage) return labels[stage] || stage;
  return String(dims.status || "").trim();
}

/** 逾期独立成列：已完成行不判逾期；未知/不适用显示「—」，不猜测。 */
export function overdueLabel(row) {
  if (!row || row.isCompleted) return "—";
  if (row.overdueState === "overdue") return "是";
  if (row.overdueState === "on_time") return "否";
  return "—";
}

/** 派生进度：快照态按明细 completed/total 换算，其余状态回退手工值。
 *  value=null 表示没有可信数值 —— 界面显示「—」，不编造 0%。 */
export function progressDisplay(item) {
  const raw = item && item.effectiveProgress !== undefined ? item.effectiveProgress : (item ? item.progress : null);
  if (raw === null || raw === undefined || raw === "") return { value: null, text: "—", derived: false };
  const value = Number(raw);
  if (!Number.isFinite(value)) return { value: null, text: "—", derived: false };
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return { value: clamped, text: `${clamped}%`, derived: Boolean(item && item.progressSource === "snapshot") };
}

/** 同步结果文案：只有真的应用了字段才叫「更新」；内容未变的幂等跳过叫「无变化」；
 *  失败必须显式报错——接口对 failed 也返回 HTTP 200，只看 HTTP 成功会把失败说成完成。 */
export function syncResultText(data) {
  const result = (data && data.result) || {};
  const state = String(result.finalState || "");
  const outcome = String(result.outcome || "");
  const applied = Array.isArray(result.appliedFields) ? result.appliedFields.length : 0;
  if (state === "failed" || outcome === "failed") {
    const reason = redactSensitiveText(String(result.errorMessage || result.errorType || "请查看同步记录"));
    return `同步失败：${reason}`;
  }
  if (state === "needs_attention" || outcome === "needs_attention") {
    const reason = redactSensitiveText(String(result.errorMessage || result.errorType || "请查看同步记录"));
    return `同步需要处理：${reason}`;
  }
  if (applied > 0) return `同步完成，更新 ${applied} 项`;
  return "已同步，上游无变化";
}
