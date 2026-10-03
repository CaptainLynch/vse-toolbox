// 数模设计审核流程报表：多值搜索与关注清单的纯逻辑（签署日报规格 §9 S2–S10）。
// Import-free; node-tested (tests/test_plugin_overview_watchlist_logic.py).

export const DATA_MODEL_FORM_KEY = "tdc_data_model";

/** S5：占位符和输入框下方的常驻说明是同一句（与 services/form_search.py PLACEHOLDER 一致）。 */
export const TERMS_PLACEHOLDER = "输入流水单号、零件名称、零件号或申请人；多个用空格、逗号或换行分隔，可直接粘贴 Excel 一列";

const SEPARATORS = /[\s,;、，；]+/u;

/** S2：与后端 parse_terms 同一口径（全角转半角、去重、最多 100 个）。 */
export function parseTerms(text) {
  const normalized = String(text || "").normalize("NFKC");
  const seen = new Set();
  const terms = [];
  for (const raw of normalized.split(SEPARATORS)) {
    const token = raw.trim().slice(0, 200);
    if (!token || seen.has(token.toLowerCase())) continue;
    seen.add(token.toLowerCase());
    terms.push(token);
    if (terms.length >= 100) break;
  }
  return terms;
}

/** S4：「匹配 n 份表单；k 个词没有匹配」。 */
export function termSummaryText(summary) {
  if (!summary) return "";
  const missed = Array.isArray(summary.unmatched) ? summary.unmatched.length : 0;
  return missed ? `匹配 ${summary.forms} 份表单；${missed} 个词没有匹配` : `匹配 ${summary.forms} 份表单`;
}

export function termsChipText(value) {
  const count = parseTerms(value).length;
  return `${count} 个词`;
}

export function scopeLabel(scope) {
  return scope === "watchlist" ? "仅关注清单" : "全部表单";
}

/** S10：关注清单模式下进度只按清单内表单计算，标注「关注 n 份」。 */
export function watchlistProgressSuffix(watchlist) {
  if (!watchlist || watchlist.scope !== "watchlist") return "";
  return `（关注 ${watchlist.count} 份）`;
}

/** 清单项状态文字（S8：查不到的标「未找到」并留在清单里）。 */
export function itemStateText(item) {
  if (item.found === true) return "";
  if (item.found === false) return "未找到";
  return "未同步";
}
