// 交付物详情页：关注清单与历史原件组件（需求 D9/G2；契约 C5 单一权威）。
import { html, useEffect, useState } from "/static/host/vendor/preact-htm.js";
import { apiRequest, enc, plainErrorMessage } from "./api.js";
import { formatArtifactSize, safeDisplayValue } from "./format.js";
import { itemStateText, scopeLabel, TERMS_PLACEHOLDER } from "./watchlist-logic.js";

// 与报告页、表单分析页共享同源关注清单及原件接口（契约 C5 单一权威）。
export const WATCHLIST_PATH = "/api/p/project-overview/watchlist";
export const TERMS_PATH = "/api/p/project-overview/form-terms";
export const WATCHLIST_CSV_PATH = "/api/p/project-overview/watchlist.csv";
export const ARCHIVE_RUNS_PATH = "/api/scheduled-archive/runs";

// 接口能力边界与阻塞点声明：
// 1. 历史原件 runs 接口仅支持按任务标识（jobKey）过滤与 limit 限制，不支持交付物标识直接过滤；
// 2. 当前系统未提供独立的原件文件流下载路由（仅提供产物元数据只读接口）。
export const ARCHIVE_FILTER_BLOCKING_NOTE = "历史原件接口暂不支持按交付物标识直接过滤；仅支持按任务标识与数量限制过滤。";
export const ARCHIVE_DOWNLOAD_BLOCKING_NOTE = "历史原件暂未提供独立的文件流下载路由（仅提供元数据只读接口）。";

const SERIAL_SPLIT_REGEX = /[\s,;、，；]+/u;

/** 解析多单号输入：全角转半角规范化、去重、单条上限 200 字符、最多 1000 个。 */
export function parseSerialInput(text) {
  const normalized = String(text || "").normalize("NFKC");
  const seen = new Set();
  const serials = [];
  for (const raw of normalized.split(SERIAL_SPLIT_REGEX)) {
    const token = raw.trim().slice(0, 200);
    if (!token || seen.has(token.toUpperCase())) continue;
    seen.add(token.toUpperCase());
    serials.push(token);
    if (serials.length >= 1000) break;
  }
  return serials;
}

/** 关注清单只读获取。 */
export async function loadWatchlist() {
  return apiRequest(WATCHLIST_PATH);
}

/** 关注清单状态变更（新增、移除、清空、切换同步范围）。 */
export async function changeWatchlist(body) {
  return apiRequest(WATCHLIST_PATH, { method: "POST", body });
}

/** 快捷方法：添加单号到关注清单。 */
export async function addSerialsToWatchlist(serials) {
  return changeWatchlist({ action: "add", serials });
}

/** 快捷方法：从关注清单移除单号。 */
export async function removeSerialFromWatchlist(serial) {
  return changeWatchlist({ action: "remove", serials: [serial] });
}

/** 快捷方法：清空关注清单。 */
export async function clearWatchlist() {
  return changeWatchlist({ action: "clear" });
}

/** 快捷方法：更新同步范围。 */
export async function updateWatchlistScope(scope) {
  return changeWatchlist({ action: "scope", scope });
}

/** 历史原件：读取运行记录（只读）。 */
export async function loadArchiveRuns(jobKey, limit = 10) {
  const query = jobKey ? `?jobKey=${enc(jobKey)}&limit=${enc(limit)}` : `?limit=${enc(limit)}`;
  return apiRequest(`${ARCHIVE_RUNS_PATH}${query}`);
}

/** 历史原件：读取单次运行生成的产物元数据（只读）。 */
export async function loadArchiveArtifacts(runId) {
  return apiRequest(`${ARCHIVE_RUNS_PATH}/${enc(runId)}/artifacts`);
}

/**
 * 交付物详情页关注清单编辑块。
 * 读写同一份接口，支持添加流水单号、单项移除、一键清空、切换同步范围以及导出 CSV。
 */
export function DetailWatchlistPanel({ watchlist = null, onChanged = null }) {
  const [data, setData] = useState(watchlist);
  const [inputText, setInputText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    setData(watchlist);
  }, [watchlist]);

  useEffect(() => {
    let alive = true;
    if (!watchlist) {
      loadWatchlist()
        .then((result) => {
          if (alive) {
            setData(result);
            if (onChanged) onChanged(result);
          }
        })
        .catch((err) => {
          if (alive) {
            setError(plainErrorMessage(err, "关注清单加载失败"));
          }
        });
    }
    return () => {
      alive = false;
    };
  }, []);

  const executeAction = async (body, successHint = "") => {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const nextData = await changeWatchlist(body);
      setData(nextData);
      if (successHint) setFeedback(successHint);
      if (onChanged) onChanged(nextData);
    } catch (err) {
      setError(plainErrorMessage(err, "操作失败"));
    } finally {
      setBusy(false);
    }
  };

  const handleAddSerials = async () => {
    const serials = parseSerialInput(inputText);
    if (!serials.length) {
      setError("请输入至少一个流水单号");
      return;
    }
    await executeAction({ action: "add", serials }, `已加入 ${serials.length} 份单号`);
    setInputText("");
  };

  const handleClear = () => {
    if (window.confirm("确定清空关注清单吗？")) {
      executeAction({ action: "clear" }, "关注清单已清空");
    }
  };

  const currentScope = (data && data.scope) || "all";
  const count = data && typeof data.count === "number" ? data.count : 0;
  const items = (data && Array.isArray(data.items)) ? data.items : [];
  const missingList = (data && Array.isArray(data.missing)) ? data.missing : [];
  const configIssue = (data && data.configIssue) ? data.configIssue : "";

  // 嵌套模板遵循规则：所有子模板赋值给局部变量再组装，彻底避免反引号配对问题。
  const missingBadge = missingList.length > 0
    ? html`<span class="form-watchlist-missing"> · ${missingList.length} 份未找到</span>`
    : null;

  const issueBadge = configIssue
    ? html`<span class="form-watchlist-issue"> · ${configIssue}</span>`
    : null;

  const summaryHeader = html`<div class="form-watchlist-summary-line">
    <strong>关注清单</strong>
    <span class="form-watchlist-count">共 ${count} 份</span>
    <span class="form-watchlist-scope-tag">同步范围：${scopeLabel(currentScope)}</span>
    ${missingBadge}
    ${issueBadge}
  </div>`;

  const radioAll = html`<label class="form-watchlist-radio-label">
    <input
      type="radio"
      name="detail-watchlist-scope"
      checked=${currentScope === "all"}
      disabled=${busy}
      onChange=${() => executeAction({ action: "scope", scope: "all" }, "已切换为同步全部表单")}
    />
    <span>同步全部表单</span>
  </label>`;

  const radioWatchlist = html`<label class="form-watchlist-radio-label">
    <input
      type="radio"
      name="detail-watchlist-scope"
      checked=${currentScope === "watchlist"}
      disabled=${busy}
      onChange=${() => executeAction({ action: "scope", scope: "watchlist" }, "已切换为仅同步关注清单")}
    />
    <span>仅同步关注清单</span>
  </label>`;

  const exportBtn = html`<a class="btn is-secondary" href=${WATCHLIST_CSV_PATH} download="watchlist.csv">导出 CSV</a>`;

  const clearBtn = html`<button
    type="button"
    class="btn is-secondary"
    disabled=${busy || count === 0}
    onClick=${handleClear}
  >清空</button>`;

  const actionsBar = html`<div class="form-watchlist-actions">
    ${radioAll}
    ${radioWatchlist}
    ${exportBtn}
    ${clearBtn}
  </div>`;

  const inputRow = html`<div class="form-watchlist-input-row">
    <textarea
      class="form-filter-keyword form-terms-input form-watchlist-add-input"
      rows="2"
      maxlength="20000"
      aria-label="新增流水单号"
      placeholder=${TERMS_PLACEHOLDER}
      value=${inputText}
      disabled=${busy}
      onInput=${(e) => setInputText(e.target.value)}
    ></textarea>
    <button
      type="button"
      class="btn is-primary form-watchlist-add-btn"
      disabled=${busy || !inputText.trim()}
      onClick=${handleAddSerials}
    >加入关注清单</button>
  </div>`;

  const hintText = html`<p class="form-terms-hint">${TERMS_PLACEHOLDER}</p>`;

  const errorAlert = error
    ? html`<p class="form-watchlist-error" role="alert">${error}</p>`
    : null;

  const feedbackStatus = feedback
    ? html`<p class="form-watchlist-feedback" role="status">${feedback}</p>`
    : null;

  const emptyPlaceholder = html`<p class="form-watchlist-empty">清单为空。在上方输入流水单号后点击加入。</p>`;

  const listItems = items.map((item) => {
    const stateLabel = itemStateText(item);
    const stateClass = item.found === false ? "form-watchlist-state is-missing" : "form-watchlist-state";
    const stateChip = stateLabel ? html`<span class=${stateClass}>${stateLabel}</span>` : null;
    const removeBtn = html`<button
      type="button"
      class="form-filter-chip-remove"
      aria-label=${`移除 ${item.serial}`}
      disabled=${busy}
      onClick=${() => executeAction({ action: "remove", serials: [item.serial] })}
    >×</button>`;

    return html`<li key=${item.serial} class="form-watchlist-item-entry">
      <span class="form-watchlist-serial-text">${item.serial}</span>
      ${stateChip}
      ${removeBtn}
    </li>`;
  });

  const listContainer = items.length > 0
    ? html`<ul class="form-watchlist-items">${listItems}</ul>`
    : emptyPlaceholder;

  return html`<section class="detail-watchlist-panel" aria-label="关注清单维护">
    ${summaryHeader}
    ${actionsBar}
    ${inputRow}
    ${hintText}
    ${errorAlert}
    ${feedbackStatus}
    ${listContainer}
  </section>`;
}

/**
 * 交付物详情页历史原件与运行记录块。
 * 读写契约：只读查询运行历史及产物元数据，无写路由；
 * 阻塞点声明：接口不支持按交付物标识过滤，仅支持按任务过滤。
 */
export function DetailHistoricalArchivePanel({ item = null, jobKey = "" }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedRunId, setExpandedRunId] = useState(null);
  const [artifactsState, setArtifactsState] = useState({ loading: false, error: "", items: null });

  const resolvedJobKey = jobKey
    || (item && item.jobKey)
    || (item && Array.isArray(item.associations)
        ? (item.associations.find((a) => a && a.type === "archive_job") || {}).jobKey
        : "")
    || "";

  const fetchRuns = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await loadArchiveRuns(resolvedJobKey, 10);
      setRuns(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(plainErrorMessage(err, "历史原件记录加载失败"));
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, [resolvedJobKey]);

  const toggleArtifacts = async (runId) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
      setArtifactsState({ loading: false, error: "", items: null });
      return;
    }
    setExpandedRunId(runId);
    setArtifactsState({ loading: true, error: "", items: null });
    try {
      const data = await loadArchiveArtifacts(runId);
      const items = (data && Array.isArray(data.artifacts)) ? data.artifacts : [];
      setArtifactsState({ loading: false, error: "", items });
    } catch (err) {
      setArtifactsState({ loading: false, error: plainErrorMessage(err, "产物清单读取失败"), items: null });
    }
  };

  // 子模板均在局部变量构建，遵循规则 (4)
  const blockingNotice = html`<div class="archive-blocking-notice" role="note">
    <p class="archive-blocking-text">说明：${ARCHIVE_FILTER_BLOCKING_NOTE}</p>
  </div>`;

  const headerBlock = html`<div class="archive-header-row">
    <h5 class="archive-section-title">历史原件与运行记录</h5>
    <button type="button" class="btn is-secondary archive-refresh-btn" disabled=${loading} onClick=${fetchRuns}>刷新记录</button>
  </div>`;

  let contentBody = null;
  if (loading) {
    contentBody = html`<p class="loading" role="status">正在读取历史原件记录...</p>`;
  } else if (error) {
    contentBody = html`<div class="error-msg" role="alert">
      <span>${error}</span>
      <button type="button" class="btn is-secondary" onClick=${fetchRuns}>重试</button>
    </div>`;
  } else if (runs.length === 0) {
    contentBody = html`<p class="archive-empty-text">暂无历史原件记录</p>`;
  } else {
    const tableHeaders = ["运行时间", "状态", "记录数", "结果摘要", "原件明细"].map((title) => html`<th key=${title}>${title}</th>`);
    const tableRows = runs.map((run) => {
      const runId = run.id;
      const isExpanded = expandedRunId === runId;
      const stateLabel = run.runState === "success" ? "成功" : (run.runState === "failed" ? "失败" : "进行中");
      const stateTone = run.runState === "success" ? "is-success" : (run.runState === "failed" ? "is-error" : "is-warning");
      const timeStr = safeDisplayValue(run.finishedAt || run.startedAt || run.createdAt || "未知时间");
      const recordCount = typeof run.recordCount === "number" ? `${run.recordCount} 条` : "—";
      const summaryText = safeDisplayValue(run.errorMessage || run.resultSummary || "无");

      let artifactRowContent = null;
      if (isExpanded) {
        if (artifactsState.loading) {
          artifactRowContent = html`<p class="loading">正在读取产物元数据...</p>`;
        } else if (artifactsState.error) {
          artifactRowContent = html`<p class="error-msg">${artifactsState.error}</p>`;
        } else if (!artifactsState.items || artifactsState.items.length === 0) {
          artifactRowContent = html`<p class="archive-empty-text">本次运行未保存产物文件</p>`;
        } else {
          const artHeaders = ["产物名称", "类型", "大小", "相对路径", "下载"].map((h) => html`<th key=${h}>${h}</th>`);
          const artRows = artifactsState.items.map((art, index) => {
            const name = safeDisplayValue(art.displayName || art.relativePath || "未命名文件");
            const type = safeDisplayValue(art.artifactType || "—");
            const size = formatArtifactSize(art.sizeBytes);
            const path = safeDisplayValue(art.relativePath || "—");

            // 下载入口：若后端提供具体文件流链接则直接跳转，否则展示明确阻塞提示
            const downloadEntrance = art.downloadUrl
              ? html`<a class="btn is-secondary" href=${art.downloadUrl} download=${name}>下载</a>`
              : html`<span class="archive-no-download" title=${ARCHIVE_DOWNLOAD_BLOCKING_NOTE}>暂无下载接口</span>`;

            return html`<tr key=${index}>
              <td>${name}</td>
              <td>${type}</td>
              <td>${size}</td>
              <td>${path}</td>
              <td>${downloadEntrance}</td>
            </tr>`;
          });

          artifactRowContent = html`<table class="archive-artifacts-table">
            <thead><tr>${artHeaders}</tr></thead>
            <tbody>${artRows}</tbody>
          </table>`;
        }
      }

      const mainRow = html`<tr key=${`run-${runId}`}>
        <td>${timeStr}</td>
        <td><span class=${`status-text ${stateTone}`}>${stateLabel}</span></td>
        <td>${recordCount}</td>
        <td>${summaryText}</td>
        <td>
          <button
            type="button"
            class="btn is-secondary"
            onClick=${() => toggleArtifacts(runId)}
          >${isExpanded ? "收起原件" : "查看原件"}</button>
        </td>
      </tr>`;

      const detailRow = isExpanded
        ? html`<tr key=${`art-${runId}`} class="archive-artifact-detail-row">
            <td colspan="5">
              <div class="archive-artifact-container">
                <strong>已留存原件文件</strong>
                ${artifactRowContent}
              </div>
            </td>
          </tr>`
        : null;

      return html`${mainRow}${detailRow}`;
    });

    contentBody = html`<div class="archive-table-container">
      <table class="archive-runs-table">
        <thead><tr>${tableHeaders}</tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>`;
  }

  return html`<section class="detail-historical-archive-panel" aria-label="历史原件与运行记录">
    ${headerBlock}
    ${blockingNotice}
    ${contentBody}
  </section>`;
}

export const WatchlistBlock = DetailWatchlistPanel;
export const HistoricalArchiveBlock = DetailHistoricalArchivePanel;
export const DetailWatchlist = DetailWatchlistPanel;
