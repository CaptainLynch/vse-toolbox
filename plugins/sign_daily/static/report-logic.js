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

/** 数据时间统一显示北京时间（后端快照时间是 UTC，带 Z 或时区偏移）。 */
export function formatTime(value) {
  if (!value) return "暂无";
  const text = String(value);
  if (/(Z|[+-]\d{2}:?\d{2})$/.test(text)) {
    const date = new Date(text);
    if (!Number.isNaN(date.getTime())) {
      const parts = new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false,
      }).formatToParts(date).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
    }
  }
  return text.replace("T", " ").replace(/\.\d+/, "").slice(0, 16);
}

/** 预览/复制用：把正文里的 cid:sd-<图> 换成同一张 PNG 的 data URI；没有图的位置不动。 */
export function inlineImages(html, images) {
  return String(html || "").replace(/src="cid:sd-([a-z]+)"/g, (match, key) => (images && images[key] ? `src="${images[key]}"` : match));
}

/** 有待复核项时禁止复制和下载，除非选了「本次按建议继续」（§7 时序 4、7）。
 *  状态门禁（数字码）不提供「继续」选项：份数与签单率不可信时一律不许发送。 */
export function exportAllowed(result, proceed) {
  if (!result) return false;
  if (result.statusGate && result.statusGate.blocked) return false;
  return !result.exportBlocked || proceed === true;
}

/** 已保存但本次数据里没有的项目（历史残留）：可见、可取消，绝不自动删除。 */
export function orphanProjects(options, selected) {
  const known = new Set(options || []);
  const seen = new Set();
  return (selected || []).filter((item) => {
    if (!item || known.has(item) || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}

/** 发送门禁提示（后端 statusGate）；未拦截时为空串。 */
export function statusGateText(result) {
  const gate = result && result.statusGate;
  const codes = (gate && gate.codes) || [];
  if (gate && gate.blocked) return String(gate.text || "状态列是数字码，已禁止发送");
  if (!codes.length) return "";
  // 门禁被关掉但码值仍在：不拦，但必须披露，否则就是静默错数
  const listed = codes.map((item) => `${item.code}：${item.flows} 份`).join("、");
  return `门禁已关闭，状态列仍是数字码（${listed}）：数字仅供参考，发出去就是错数`;
}

/** 取消孤儿项目时沿用原范围的收件人与文案：只在新范围还没有记忆、旧范围有记忆时返回旧记忆。 */
export function migratePrefs(preferences, oldKey, newKey) {
  const prefs = preferences || {};
  if (!oldKey || !newKey || oldKey === newKey) return null;
  if (prefs[newKey]) return null;
  const previous = prefs[oldKey];
  if (!previous || typeof previous !== "object") return null;
  return { ...previous };
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

export function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

export function stageText(task) {
  if (!task) return "";
  const percent = Number.isFinite(task.percent) ? `（${task.percent}%）` : "";
  return `${task.stage || "排队中"}${percent}`;
}

// ── 本地导入的「和哪一天比」（2026-11-16）：页面只说人话，不说「基线」 ──────────

const mmdd = (iso) => String(iso || "").slice(5, 10);
const daysBetween = (later, earlier) => Math.round((Date.parse(later) - Date.parse(earlier)) / 86400000);

/** 本地日期 YYYY-MM-DD（数据日期输入框的默认值；只是前端预填，用户看得见、可以改）。 */
export function todayIso(now = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** 「和哪一天比」下拉框：第一项是自动，其余每个已存的导入一项，固定的那项标出来。 */
export function baselineOptions(items) {
  return [
    { value: "", label: "上次导入（自动）" },
    ...(items || []).map((item) => ({
      value: item.date,
      label: `${item.date} · ${item.sourceName || "（未记录文件名）"}${item.pinned ? "（固定）" : ""}`,
    })),
  ];
}

/**
 * 生成按钮上方的一句话：这次会和哪一天比（与后端同一顺序：本次指定 > 固定 > 自动）。
 * 返回 {text, tone}，tone 是 ok（会显示每日进展）/ info（这次不比，正常）/ warn（需要用户改选择）。
 * 只是预告：项目范围等细节以生成结果为准。
 */
export function comparePlan(items, { dataDate = "", choice = "", maxGapDays = 14 } = {}) {
  const list = items || [];
  if (!dataDate) return { text: "先填数据截至日期，就能看到这次会和哪一天比", tone: "info" };
  const later = list.filter((item) => item.date > dataDate).map((item) => item.date).sort();
  if (later.length) {
    return { text: `已有更晚日期（${mmdd(later[later.length - 1])}）的导入，本次按旧数据处理，不显示每日进展`, tone: "warn" };
  }
  const describe = (item) => `${mmdd(item.date)} 的导入（${item.sourceName || "未记录文件名"}）`;
  const pinned = list.find((item) => item.pinned);
  const chosen = choice ? list.find((item) => item.date === choice) : null;
  if (choice) {
    if (!chosen || choice >= dataDate) {
      return { text: "选的对比日期要早于本次数据日期，请改选或改回自动", tone: "warn" };
    }
    return { text: `将与 ${describe(chosen)}对比（你指定的）`, tone: "ok" };
  }
  if (pinned) {
    if (pinned.date >= dataDate) {
      return { text: `已固定与 ${mmdd(pinned.date)} 对比，但它不早于本次数据日期：请在「更多」里改选或取消固定`, tone: "warn" };
    }
    return { text: `已固定与 ${describe(pinned)}对比`, tone: "ok" };
  }
  if (!list.length) return { text: "这是第一次导入，明天起才能看到每日进展", tone: "info" };
  const earlier = list.filter((item) => item.date < dataDate).sort((a, b) => (a.date < b.date ? 1 : -1));
  if (!earlier.length) return { text: "今天先导入一次，明天再导入就能看到进展", tone: "info" };
  const last = earlier[0];
  if (daysBetween(dataDate, last.date) > maxGapDays) {
    return { text: `上次导入是 ${mmdd(last.date)}，隔了超过 ${maxGapDays} 天，这次不自动比；需要的话在「更多」里指定这一天`, tone: "info" };
  }
  return { text: `将与 ${describe(last)}对比`, tone: "ok" };
}

/** 生成之后，结果区再说一遍「这次实际和哪一天比了」（以后端返回为准）。 */
export function compareResultText(importMeta) {
  const meta = importMeta || {};
  const saved = meta.baselineSaved ? "本次已留作下次对比。" : "本次没有留作下次对比。";
  const base = meta.baseline;
  if (base) {
    const how = { explicit: "你指定的", pinned: "已固定的", auto: "自动选的上次导入" }[base.mode] || "自动选的上次导入";
    return `已与 ${mmdd(base.date)} 的导入（${base.sourceName || "未记录文件名"}，${how}）对比。${saved}`;
  }
  if (String(meta.baselineStatement || "").startsWith("已有更晚日期")) {
    return `已有更晚日期的导入，本次按旧数据处理，没有显示每日进展。${saved}`;
  }
  if (meta.baselineReason) return `选的对比日期要早于本次数据日期，且要包含所选项目，请改选或改回自动。${saved}`;
  return `没有可比的更早导入：今天先导入一次，明天再导入就能看到进展。${saved}`;
}

/** 两套配色是否相同（判断「配色已修改，未保存」）。 */
export function sameColors(a, b) {
  const keys = ["external", "sections", "approval"];
  return keys.every((key) => ["bar", "special"].every(
    (slot) => String(((a || {})[key] || {})[slot] || "").toLowerCase() === String(((b || {})[key] || {})[slot] || "").toLowerCase(),
  ));
}
