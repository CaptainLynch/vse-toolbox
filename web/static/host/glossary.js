// 术语与文案规范词表及扫描工具：
// 锁定用户可见界面文案的通俗中文表达，防止内部实现黑话与代码路径泄露给用户。

/** Windows 绝对盘符路径特征（C:\ 形态；只认反斜杠——URL 的 s:// 不算代码路径） */
export const DRIVE_PATH_PATTERN = /[a-zA-Z]:\\[^\s"'`<>]+/g;

/** Python 脚本代码文件后缀特征 */
export const PY_SUFFIX_PATTERN = /\b[a-zA-Z0-9_.-]+\.py\b/g;

/**
 * 禁用术语清单：面向最终用户展示时必须规避的技术词汇与底层文件特征。
 * 包含精确字面量与正则特征匹配器。
 */
export const BANNED = Object.freeze([
  "JSON",
  "Base URL",
  "Worker",
  "快照",
  "取证",
  DRIVE_PATH_PATTERN,
  PY_SUFFIX_PATTERN,
]);

/**
 * 扫描输入文本中是否存在禁用的技术术语或代码路径特征。
 * 返回所有命中的词项、位置与匹配文本切片。
 *
 * @param {string} text 要扫描的目标文本
 * @param {Array<string|RegExp>} [terms=BANNED] 扫描依据的词表规则，默认使用 BANNED
 * @returns {Array<{term: string, word: string, match: string, index: number, position: number}>} 命中文案的详情列表
 */
export function scanText(text, terms = BANNED) {
  if (typeof text !== "string" || !text) return [];

  const hits = [];
  const list = Array.isArray(terms) ? terms : BANNED;

  for (const item of list) {
    if (typeof item === "string") {
      let startIndex = 0;
      while (startIndex < text.length) {
        const found = text.indexOf(item, startIndex);
        if (found === -1) break;
        hits.push({
          term: item,
          word: item,
          match: item,
          index: found,
          position: found,
        });
        startIndex = found + item.length;
      }
    } else if (item instanceof RegExp) {
      // 创建独立的正则实例，防止不同调用间共享 lastIndex 产生并发或状态脏读
      const flags = item.flags.includes("g") ? item.flags : item.flags + "g";
      const regex = new RegExp(item.source, flags);
      let match;
      while ((match = regex.exec(text)) !== null) {
        const termName = item.source.includes("a-zA-Z]:") ? "盘符路径"
          : (item.source.includes("\\.py") ? ".py 后缀" : item.source);
        hits.push({
          term: termName,
          word: match[0],
          match: match[0],
          index: match.index,
          position: match.index,
        });
        if (regex.lastIndex === match.index) {
          regex.lastIndex++; // 避免零宽匹配死循环
        }
      }
    }
  }

  // 统一按在原文本中出现的位置升序排列
  return hits.sort((a, b) => a.index - b.index);
}
