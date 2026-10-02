// Mapping-discovery request channel (wizard + advanced editor).
//
// 映射取证是**全量**操作（TDC 全量抓取 / Aras 整本工作簿导出），实测数模一次
// 14.5s（17 页）、SOR 31.6s（9 页）、NCR 明细单次导出 65–67s。没有边界时前端会
// 无限等下去且无法取消，所以按通道给不同上限：TDC 列表 90s，Aras 导出 240s
// （与其服务端自身的收包超时一致），超时即取消并给出可重试的失败文案。
//
// 统一域会话下服务端把全量取证转成后台任务（202 + taskId/statusUrl/paramsHash）：
// 浏览器只等 202 握手，随后轮询任务状态并读取与同步响应同构的结果。握手超时
// 只覆盖 202 握手与同步回落路径，任务阶段由轮询上限兜底。密码/显式 Cookie
// 模式与引擎不可用时服务端回落同步响应，本模块对两种响应形态都兼容。
//
// `discoveryLimits` 是可变对象：测试把上限压到毫秒级来验证超时路径。
import { DeliverableApiError, enc, requestError } from "./api.js";

export const discoveryLimits = {
  tdcMs: 90000,
  arasMs: 240000,
  taskPollTimeoutMs: 15 * 60 * 1000,
  taskPollIntervalMs: 2000,
};

const TDC_DELIVERABLES = new Set(["VPI-T2-D2", "VPI-T2-D5"]);

export function mappingDiscoveryTimeoutMs(deliverableId) {
  return TDC_DELIVERABLES.has(String(deliverableId || "")) ? discoveryLimits.tdcMs : discoveryLimits.arasMs;
}

function randomToken(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 向导会话 ID：同一次「开始配置并启用」内共享服务端取证缓存与稳定性基线。 */
export function newWizardSessionId() {
  return randomToken("wiz");
}

function postQuietly(path, body) {
  // 前端 abort 只结束浏览器等待；必须同时通知服务端，否则整轮全量抓取照跑，
  // "可取消"就只是表面文章。取消失败不改变"前端已取消"这一事实，也不掩盖原始超时错误。
  try {
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {});
  } catch (_err) {
    // ignore
  }
}

export function requestMappingDiscoveryCancel(deliverableId, cancelToken) {
  postQuietly(`/api/project-status/deliverables/${enc(deliverableId)}/mapping-discovery/cancel`, { cancelToken });
}

export function requestMappingTaskCancel(taskId) {
  // 联动任务中心的协作式取消：TDC 分页边界即停；Aras 单次导出不可中断，
  // 任务会在当前导出结束后标记取消（最长约 240s）。
  postQuietly(`/api/tasks/${enc(taskId)}/cancel`, {});
}

export function isTaskAccepted(status, body) {
  return status === 202 && Boolean(body) && body.ok === true && Boolean(body.data && body.data.taskId);
}

function kickTaskCenter() {
  document.dispatchEvent(new CustomEvent("vse:task-center-kick"));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function readJson(response) {
  try {
    return await response.json();
  } catch (_err) {
    return null;
  }
}

async function waitForTask(taskId, deadline, signal) {
  while (Date.now() < deadline) {
    if (signal.aborted) return null;
    try {
      const response = await fetch(`/api/tasks/${enc(taskId)}`, { cache: "no-store", signal });
      if (response.ok) {
        const task = (await readJson(response) || {}).data;
        if (task && task.is_active === false) return task;
      }
    } catch (err) {
      if (signal.aborted) return null;
      // 瞬态网络错误继续轮询，由总截止兜底
    }
    await sleep(discoveryLimits.taskPollIntervalMs);
  }
  return null;
}

async function fetchTaskResult(taskId, signal) {
  const response = await fetch(`/api/tasks/${enc(taskId)}/result`, { cache: "no-store", signal });
  const body = await readJson(response);
  if (!response.ok || !body || body.ok !== true) throw requestError(body, response.status);
  return body.data;
}

function retryableError(message) {
  const error = new DeliverableApiError(message, { status: 0, type: "timeout", retryable: true });
  return error;
}

/**
 * POST mapping-discovery with the client deadline, cooperative cancel and the
 * 202 background-task contract. Resolves with the discovery result object
 * (same shape as the synchronous response). `options.timeoutMs` overrides the
 * per-channel deadline; `options.cancelToken` is for tests.
 */
export async function postMappingDiscovery(deliverableId, payload, options = {}) {
  const timeoutMs = Number(options.timeoutMs) > 0 ? Number(options.timeoutMs) : mappingDiscoveryTimeoutMs(deliverableId);
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const cancelToken = options.cancelToken || randomToken("disc");
  let timer = null;
  let timedOut = false;
  if (controller) {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  let activeTask = null;
  const expired = () => timedOut || (controller && controller.signal.aborted);
  try {
    const response = await fetch(`/api/project-status/deliverables/${enc(deliverableId)}/mapping-discovery`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ...payload, cancelToken }),
      signal: controller ? controller.signal : undefined,
    });
    const body = await readJson(response);
    if (isTaskAccepted(response.status, body)) {
      // 后台任务路径：202 只代表受理成功，解除握手超时，改由任务轮询上限兜底。
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      activeTask = body.data || {};
      kickTaskCenter();
      // 后台阶段的独立总截止：覆盖状态轮询、响应体与结果读取（任一次请求挂起都不能越过它）。
      const pollMs = discoveryLimits.taskPollTimeoutMs;
      const stage = new AbortController();
      const stageTimer = setTimeout(() => stage.abort(), pollMs);
      const stageExpired = () => retryableError(`映射取证后台任务超过 ${Math.max(1, Math.round(pollMs / 60000))} 分钟未完成，可在任务中心查看或取消后重试。`);
      try {
        const task = await waitForTask(activeTask.taskId, Date.now() + pollMs, stage.signal);
        if (!task) throw stageExpired();
        if (task.status === "cancelled") throw new Error("映射取证已取消；可重新点击「开始配置并启用」。");
        if (task.status !== "succeeded") {
          const detail = task.error_message ? String(task.error_message) : "原因未记录";
          throw new Error(`映射取证后台任务失败：${detail}`);
        }
        let resultBody;
        try {
          resultBody = await fetchTaskResult(activeTask.taskId, stage.signal);
        } catch (err) {
          if (stage.signal.aborted) throw stageExpired();
          throw err;
        }
        // 参数哈希绑定：结果必须属于本次提交的查询身份，否则显式丢弃。
        if (
          !resultBody || typeof resultBody !== "object" || !resultBody.result
          || (activeTask.paramsHash && resultBody.paramsHash !== activeTask.paramsHash)
        ) {
          throw new Error("映射取证结果与请求参数不一致，已丢弃；请重新点击「开始配置并启用」。");
        }
        return resultBody.result;
      } finally {
        clearTimeout(stageTimer);
      }
    }
    // 同步回落：密码/显式 Cookie 模式、引擎不可用或会话缓存命中，契约不变。
    if (!response.ok || !body || body.ok !== true) throw requestError(body, response.status);
    return body.data || {};
  } catch (err) {
    if (expired() && (!err || err.name === "AbortError" || timedOut)) {
      if (activeTask && activeTask.taskId) requestMappingTaskCancel(activeTask.taskId);
      else requestMappingDiscoveryCancel(deliverableId, cancelToken);
      throw retryableError(`映射取证超过 ${Math.round(timeoutMs / 1000)} 秒未完成，已取消；可稍后重试。`);
    }
    if (err && err.name === "AbortError") throw err;
    if (err instanceof TypeError) {
      throw new DeliverableApiError("无法连接本地服务，请确认 VSE Toolbox 仍在运行", { status: 0, type: "network" });
    }
    throw err;
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}
