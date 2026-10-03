// 签署日报页面的纯逻辑（node 可测，tests/test_sign_daily_frontend_logic.py）。

/** 与 backend.scope_key 相同的范围 key（Python json.dumps 默认分隔符，中文不转义）。 */
export function scopeKey(projects, departments, watchlistOnly) {
  const list = (items) => `[${[...items].sort().map((item) => JSON.stringify(item)).join(", ")}]`;
  let key = `{"projects": ${list(projects || [])}, "departments": ${list(departments || [])}`;
  if (watchlistOnly) key += ", \"watchlistOnly\": true";
  return `${key}}`;
}

export function toggle(list, value) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

export function formatTime(value) {
  if (!value) return "暂无";
  return String(value).replace("T", " ").replace(/\.\d+/, "").replace(/Z$/, " UTC");
}

/** 预览/复制用：把正文里的 cid:sd-<图> 换成同一张 PNG 的 data URI；没有图的位置不动。 */
export function inlineImages(html, images) {
  return String(html || "").replace(/src="cid:sd-([a-z]+)"/g, (match, key) => (images && images[key] ? `src="${images[key]}"` : match));
}

/** 有待复核项时禁止复制和下载，除非选了「本次按建议继续」（§7 时序 4、7）。 */
export function exportAllowed(result, proceed) {
  return Boolean(result) && (!result.exportBlocked || proceed === true);
}

/** 复核面板的默认勾选：确定命中勾选、疑似不勾选；排除项默认不纳入。 */
export function initialPicks(longCycle) {
  const picks = {};
  (longCycle.review || []).forEach((item) => { picks[`${item.project}\u0000${item.normalized}`] = item.checked === true; });
  return picks;
}

/** 「确认并记住」：面板里列出的每一行都写入结论；勾选的记纳入、未勾选的记不纳入；强制纳入的排除项和手工纳入的未命中件记纳入。 */
export function conclusionsPayload(longCycle, picks, forced) {
  const byProject = {};
  const add = (project, key, include) => {
    if (!byProject[project]) byProject[project] = [];
    byProject[project].push({ key, include });
  };
  (longCycle.review || []).forEach((item) => add(item.project, item.normalized, Boolean(picks[`${item.project}\u0000${item.normalized}`])));
  Object.entries(forced || {}).forEach(([id, on]) => {
    if (!on) return;
    const [project, key] = id.split("\u0000");
    add(project, key, true);
  });
  return Object.entries(byProject).map(([project, items]) => ({ project, items }));
}

export function searchMisses(misses, text) {
  const q = String(text || "").trim().toUpperCase();
  if (!q) return [];
  return (misses || []).filter((item) => item.normalized.toUpperCase().includes(q)).slice(0, 50);
}

/** 「姓名=区域」每行一条 <-> 对象（未在册人员指定区域）。 */
export function parsePairs(text) {
  const result = {};
  String(text || "").split(/\r?\n/).forEach((line) => {
    const match = line.match(/^\s*([^=＝]+?)\s*[=＝]\s*(.+?)\s*$/);
    if (match) result[match[1]] = match[2];
  });
  return result;
}

export function formatPairs(map) {
  return Object.entries(map || {}).map(([key, value]) => `${key}=${value}`).join("\n");
}

/** 同义词表「规范词=别名1、别名2」每行一条 <-> 对象。 */
export function parseSynonyms(text) {
  const result = {};
  String(text || "").split(/\r?\n/).forEach((line) => {
    const match = line.match(/^\s*([^=＝]+?)\s*[=＝]\s*(.*?)\s*$/);
    if (match) result[match[1]] = match[2].split(/[、,，;；]+/).map((item) => item.trim()).filter(Boolean);
  });
  return result;
}

export function formatSynonyms(map) {
  return Object.entries(map || {}).map(([key, list]) => `${key}=${(list || []).join("、")}`).join("\n");
}

export function lines(text) {
  return [...new Set(String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
}

/** 导入文件编码自动识别：UTF-8 优先，失败按 GBK（§7 导入校验）。 */
export function decodeCsv(buffer, TextDecoderImpl = globalThis.TextDecoder) {
  try {
    return new TextDecoderImpl("utf-8", { fatal: true }).decode(buffer).replace(/^﻿/, "");
  } catch (_) {
    return new TextDecoderImpl("gbk").decode(buffer);
  }
}

export function stageText(task) {
  if (!task) return "";
  const percent = Number.isFinite(task.percent) ? `（${task.percent}%）` : "";
  return `${task.stage || "排队中"}${percent}`;
}
