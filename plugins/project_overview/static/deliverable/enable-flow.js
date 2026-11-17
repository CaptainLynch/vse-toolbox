// 「开始配置并启用」的完整流程：取证（两次，含稳定性核验）→ 推导映射 → 保存并启用 → 首次同步。
// 交付物详情里的单个向导和「一键开启自动同步」共用这一份，保证两边走同一套后端校验。
import { apiRequest, enc } from "./api.js";
import { newWizardSessionId, postMappingDiscovery } from "./discovery.js";
import {
  buildWizardDiscovery,
  dropDepartment,
  stabilityGateFailureMessage,
  wizardMapping,
  wizardNotMatchedMessage,
  wizardPolicyPatch,
  wizardRetryWithoutDepartment,
} from "./policy-logic.js";

const policyPath = (id) => `/api/project-status/deliverables/${enc(id)}/update-policy`;

/**
 * 运行一次启用流程；失败时抛出 Error（文案即给用户看的原因）。
 * say(text)：进度提示；pickCandidate(candidates) → Promise<externalKey>：
 * 仅在指定单号且命中多条时调用（一键开启只做按车型汇总，不会走到这里）。
 * 返回首次同步的结果（sync-now 的 data）。
 */
export async function runEnableFlow({ item, capabilities, values, vaultConfigured, say, pickCandidate }) {
  const plan = buildWizardDiscovery(values, capabilities);
  // 同一次启用内的多次取证共享会话：服务端据此复用第 1 次的全量抓取并做第 2 次轻量核验。
  plan.payload.wizardSessionId = newWizardSessionId();
  // 统一域会话下该请求会转后台任务（202），postMappingDiscovery 内部轮询至完成；
  // 密码/Cookie 模式仍同步执行。两次取证独立契约不变。
  say("正在抓取映射证据（第 1/2 次，统一域会话下后台执行）...");
  let result = (await postMappingDiscovery(item.id, plan.payload)) || {};
  if (result.state === "ambiguous" && !plan.aggregate) {
    if (!pickCandidate) throw new Error("候选记录不唯一，请到交付物详情里逐个配置。");
    say("候选不唯一，请选择一次目标记录。");
    plan.payload.selectedExternalKey = await pickCandidate(result.candidates);
    result = (await postMappingDiscovery(item.id, plan.payload)) || {};
  }
  if (result.state !== "matched" && plan.kind.isTdc && plan.deptVal) {
    say("指定部门未匹配，正在尝试不限部门自动重试...");
    const retry = (await postMappingDiscovery(item.id, wizardRetryWithoutDepartment(plan.payload))) || {};
    if (retry && (retry.state === "matched" || (retry.state === "ambiguous" && !plan.aggregate))) {
      result = retry;
      dropDepartment(plan);
    }
  }
  if (result.state !== "matched") throw new Error(wizardNotMatchedMessage(result));
  let confirmed = Number(result.stability && result.stability.confirmed);
  if (!Number.isFinite(confirmed) || confirmed < 2) {
    say("正在验证映射稳定性（第 2/2 次）...");
    result = (await postMappingDiscovery(item.id, { ...plan.payload, stabilityCheck: true })) || {};
    confirmed = Number(result.stability && result.stability.confirmed);
    if (result.state !== "matched" || !Number.isFinite(confirmed) || confirmed < 2) {
      throw new Error(stabilityGateFailureMessage(result));
    }
  }
  const mappingResult = wizardMapping(plan, capabilities, result);
  say("正在保存配置并启用自动同步...");
  await apiRequest(policyPath(item.id), { method: "PATCH", body: wizardPolicyPatch(plan, values, result, mappingResult, vaultConfigured) });
  say("配置已启用，正在触发首次同步...");
  return apiRequest(`/api/project-status/deliverables/${enc(item.id)}/sync-now`, { method: "POST" });
}
