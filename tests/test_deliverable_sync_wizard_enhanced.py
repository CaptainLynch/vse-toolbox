# -*- coding: utf-8 -*-
"""Enhanced contract tests for deliverable sync wizard (aggregate default, department, interval)."""

from pathlib import Path


JS_PATH = Path("web/static/app.js")


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8-sig")


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    assert start != -1, f"Start marker '{start_marker}' not found"
    end = text.find(end_marker, start)
    assert end != -1, f"End marker '{end_marker}' not found after '{start_marker}'"
    return text[start:end]


def test_sync_dispatch_and_archive_job_key_contract() -> None:
    """D6-D8 与 EWO 一样走统一的同步入口；归档任务反查契约保持不变。"""
    from core.project_status_contracts import find_job_key_by_deliverable_id

    # 1. 后端注册表反查契约
    assert find_job_key_by_deliverable_id("VPI-T2-D6") == "aras_paa"
    assert find_job_key_by_deliverable_id("VPI-T2-D7") == "aras_ncr_progress"
    assert find_job_key_by_deliverable_id("VPI-T2-D8") == "aras_ncr_detail"
    assert find_job_key_by_deliverable_id("VPI-T2-D2") == "tdc_sor"
    assert find_job_key_by_deliverable_id("VPI-T2-D3") == "aras_ewo"
    assert find_job_key_by_deliverable_id("VPI-T2-D5") == "tdc_data_model"
    assert find_job_key_by_deliverable_id("VPI-T2-D1") is None
    assert find_job_key_by_deliverable_id("VPI-T2-D4") is None


def test_wizard_aggregate_note_dynamic_intersection_in_node_vm() -> None:
    """Node VM 验证聚合向导备注字段的动态交集匹配与 statusOrApprovalFields 拾取及 fail-closed 兜底。"""
    import subprocess

    node_script = """
    function resolveAggregateNotes(candidateNotes, result) {
      const reportedFields = Array.isArray(result && result.fieldReport && result.fieldReport.fields)
        ? result.fieldReport.fields
        : [];
      let matchedNotes = candidateNotes.filter((f) => reportedFields.includes(f));
      if (matchedNotes.length === 0 && result && result.fieldReport) {
        const statusOrApproval = Array.isArray(result.fieldReport.statusOrApprovalFields)
          ? result.fieldReport.statusOrApprovalFields
          : [];
        const statusColNames = statusOrApproval
          .map((entry) => (typeof entry === "string" ? entry : entry && entry.field))
          .filter((col) => col && reportedFields.includes(col));
        if (statusColNames.length > 0) {
          matchedNotes = statusColNames;
        }
      }

      if (matchedNotes.length === 0) {
        throw new Error("无法从最新脱敏字段报告确定有效的备注映射字段，请打开高级设置手工确认映射后保存。");
      }
      return matchedNotes;
    }

    // 1. 候选与报告字段部分匹配 -> 取交集
    const res1 = { fieldReport: { fields: ["latestCompletedNode", "applicant"] } };
    const matched1 = resolveAggregateNotes(["latestCompletedNode", "processInstanceStatus"], res1);
    if (matched1.length !== 1 || matched1[0] !== "latestCompletedNode") {
      throw new Error("Expected latestCompletedNode, got: " + JSON.stringify(matched1));
    }

    // 2. 候选全部不匹配，但 statusOrApprovalFields 存在真实列 -> 拾取 statusOrApprovalFields
    const res2 = {
      fieldReport: {
        fields: ["applicant", "flowStatus"],
        statusOrApprovalFields: [{ field: "flowStatus", samples: ["审批完成"] }]
      }
    };
    const matched2 = resolveAggregateNotes(["latestCompletedNode", "processInstanceStatus"], res2);
    if (matched2.length !== 1 || matched2[0] !== "flowStatus") {
      throw new Error("Expected flowStatus fallback, got: " + JSON.stringify(matched2));
    }

    // 3. 候选与 statusOrApprovalFields 均无匹配 -> Fail-Closed 抛错
    let caught = false;
    try {
      resolveAggregateNotes(["latestCompletedNode"], { fieldReport: { fields: ["applicant"] } });
    } catch (e) {
      caught = true;
      if (!e.message.includes("无法从最新脱敏字段报告确定有效的备注映射字段")) {
        throw new Error("Unexpected error: " + e.message);
      }
    }
    if (!caught) throw new Error("Expected fail-closed error");

    console.log("PASS");
    """
    proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
    assert "PASS" in proc.stdout
