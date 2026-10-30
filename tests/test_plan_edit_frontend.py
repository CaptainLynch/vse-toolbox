# -*- coding: utf-8 -*-
"""主计划时间轴直接编辑 + 表格模式（REQUIREMENTS C3）前端与契约测试。

使用 Node 22+ VM 运行时测试 plugins/workbench/static/plan-edit.js：
1. 模块语法与导出完整性；
2. 日期校验逻辑（范围、格式、已完成节点未来日期校验）；
3. 构建 PATCH 请求载荷（更新目标节点、保留其他节点、乐观锁版本号、清空日期置未开始）；
4. 统一保存实现回调与载荷校验（PATCH /api/project-status/phases/<phase_id>/milestones）；
5. 409 冲突映射（主计划已被其他会话更新，请刷新后重试）；
6. 未排期节点的「去排期」行为保持（指向 #p/project-overview/plan）；
7. 已排期节点的编辑唤起入口；
8. 时间轴与表格模式共用保存实现；
9. 用户可见文案合规门禁（规避内部术语与代码路径）；
10. 配合既有后端 PATCH 接口的端到端集成往返。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import web.app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_EDIT_JS = REPO_ROOT / "plugins" / "workbench" / "static" / "plan-edit.js"
PROJECT_JS = REPO_ROOT / "plugins" / "workbench" / "static" / "project.js"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


needs_node = pytest.mark.skipif(_node_major() < 22, reason="需要 Node 22+ 支持 ES 模块 VM")


def _run_node_vm(scenario: dict[str, Any]) -> dict[str, Any]:
    """在 Node VM 环境中运行 plan-edit.js 测试场景并返回 JSON 结果。"""
    node = shutil.which("node")
    assert node is not None, "未找到 node 命令"

    runner_js = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const [, PLAN_EDIT_PATH, SCENARIO_JSON] = process.argv;
const scenario = JSON.parse(SCENARIO_JSON);

const recordedRequests = [];

const context = vm.createContext({
  console: { log() {}, warn() {}, error() {}, info() {} },
  setTimeout, clearTimeout,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Error,
  encodeURIComponent, decodeURIComponent,
  window: {},
});

const code = readFileSync(PLAN_EDIT_PATH, "utf8");
const mod = new vm.SourceTextModule(code, {
  context,
  initializeImportMeta(meta) {
    meta.url = pathToFileURL(PLAN_EDIT_PATH).href;
  },
});

function templateToString(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(templateToString).join("");
  if (node.__pill) return `[pill:${node.tone}]${templateToString(node.children)}[/pill]`;
  if (node.__template) {
    let res = "";
    for (let i = 0; i < node.strings.length; i++) {
      res += node.strings[i];
      if (i < node.values.length) {
        const v = node.values[i];
        if (typeof v === "function") {
          // 事件处理器桩：组件里合法使用 stopPropagation/preventDefault（真实 DOM 都有）。
          res += templateToString(v({
            stopPropagation() {},
            preventDefault() {},
            target: {},
            currentTarget: { value: "" },
          }));
        } else {
          res += templateToString(v);
        }
      }
    }
    return res;
  }
  return String(node);
}

await mod.link(async (specifier) => {
  if (specifier.includes("preact-htm")) {
    return new vm.SyntheticModule(
      ["html", "useState", "useEffect", "useCallback", "useRef"],
      function () {
        this.setExport("html", (strings, ...values) => ({ __template: true, strings: Array.from(strings), values }));
        this.setExport("useState", (init) => [typeof init === "function" ? init() : init, () => {}]);
        this.setExport("useEffect", () => {});
        this.setExport("useCallback", (fn) => fn);
        this.setExport("useRef", (init) => ({ current: init }));
      },
      { context }
    );
  }
  if (specifier.includes("common.js")) {
    return new vm.SyntheticModule(
      ["api", "html", "Pill", "TONE"],
      function () {
        this.setExport("api", async (url, opts) => {
          recordedRequests.push({ url, opts });
          if (scenario.mockApiError) {
            const err = new Error(scenario.mockApiError.message || "Request failed");
            if (scenario.mockApiError.status) err.status = scenario.mockApiError.status;
            throw err;
          }
          return scenario.mockApiResponse || { ok: true, data: { projectStatus: {} } };
        });
        this.setExport("html", (strings, ...values) => ({ __template: true, strings: Array.from(strings), values }));
        this.setExport("Pill", ({ tone, children }) => ({ __pill: true, tone, children }));
        this.setExport("TONE", { success: "ok", primary: "info", warning: "warn", error: "bad" });
      },
      { context }
    );
  }
  throw new Error("unexpected specifier: " + specifier);
});

await mod.evaluate();
const exports = mod.namespace;

const out = {
  exportsList: Object.keys(exports),
};

if (scenario.action === "validateDates") {
  const phase = scenario.phase;
  out.validation = {
    valid: exports.validateMilestoneDate(scenario.dates.valid, phase),
    empty: exports.validateMilestoneDate("", phase),
    nullVal: exports.validateMilestoneDate(null, phase),
    badFormat: exports.validateMilestoneDate(scenario.dates.badFormat, phase),
    invalidDay: exports.validateMilestoneDate(scenario.dates.invalidDay, phase),
    tooEarly: exports.validateMilestoneDate(scenario.dates.tooEarly, phase),
    tooLate: exports.validateMilestoneDate(scenario.dates.tooLate, phase),
    doneFuture: exports.validateMilestoneDate(scenario.dates.doneFuture, phase, "已完成"),
    donePast: exports.validateMilestoneDate(scenario.dates.donePast, phase, "已完成"),
  };
} else if (scenario.action === "buildPayload") {
  out.payloadUpdated = exports.buildMilestonesSavePayload(
    scenario.milestones,
    scenario.targetId,
    scenario.newDate,
    scenario.updatedAt
  );
  out.payloadCleared = exports.buildMilestonesSavePayload(
    scenario.milestones,
    scenario.targetId,
    "",
    scenario.updatedAt
  );
} else if (scenario.action === "testSave") {
  const customCalls = [];
  const customApi = async (url, opts) => {
    customCalls.push({ url, opts });
    if (scenario.mockError) {
      const err = new Error(scenario.mockError.message || "Fail");
      if (scenario.mockError.status) err.status = scenario.mockError.status;
      throw err;
    }
    return { ok: true, data: { projectStatus: { phase: scenario.phase } } };
  };

  out.saveSuccess = await exports.saveMilestoneDate({
    phaseId: scenario.phaseId,
    milestones: scenario.milestones,
    milestoneId: scenario.targetId,
    newDate: scenario.newDate,
    phase: scenario.phase,
    apiFn: customApi,
  });
  out.requestRecorded = customCalls[0] || null;

  // 校验拦截（日期超出阶段区间时不应发出网络请求）
  customCalls.length = 0;
  out.saveInvalidDate = await exports.saveMilestoneDate({
    phaseId: scenario.phaseId,
    milestones: scenario.milestones,
    milestoneId: scenario.targetId,
    newDate: "2026-09-30",
    phase: scenario.phase,
    apiFn: customApi,
  });
  out.requestOnInvalid = customCalls.length;

  // 409 冲突场景
  const conflictApi = async () => {
    const err = new Error("Conflict");
    err.status = 409;
    throw err;
  };
  out.saveConflict = await exports.saveMilestoneDate({
    phaseId: scenario.phaseId,
    milestones: scenario.milestones,
    milestoneId: scenario.targetId,
    newDate: scenario.newDate,
    phase: scenario.phase,
    apiFn: conflictApi,
  });
} else if (scenario.action === "renderComponents") {
  const phase = scenario.phase;
  const milestones = scenario.milestones;
  out.timelineHtml = templateToString(exports.PlanTimeline({
    milestones,
    today: phase.today,
    onEditMilestone: () => {},
  }));
  out.tableHtml = templateToString(exports.PlanTable({
    milestones,
    phase,
    onSaveRow: () => {},
    savingId: null,
    rowErrors: {},
  }));
  out.modalHtml = templateToString(exports.PlanDateModal({
    milestone: milestones[0],
    phase,
    onClose: () => {},
    onSave: () => {},
    saving: false,
    error: "",
  }));
  out.sectionHtml = templateToString(exports.PlanSection({
    milestones,
    phase,
    today: phase.today,
  }));
}

console.log(JSON.stringify(out));
"""

    result = subprocess.run(
        [node, "--experimental-vm-modules", "--input-type=module", "-e", runner_js, str(PLAN_EDIT_JS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node VM 退出码异常: {result.returncode}\nstderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"未捕获到 Node JSON 输出:\n{result.stdout}"
    return json.loads(lines[-1])


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "plan-edit-test.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[REPO_ROOT / "plugins"])
    app.config.update(TESTING=True)
    return app.test_client()


def test_files_exist_in_scope() -> None:
    """验证 scope 内的文件均正常存在。"""
    assert PLAN_EDIT_JS.is_file(), "plan-edit.js 必须存在"
    assert PROJECT_JS.is_file(), "project.js 必须存在"


@needs_node
def test_node_check_plan_sources() -> None:
    """使用 Node 原生 --check 语法检查。"""
    for src in [PLAN_EDIT_JS, PROJECT_JS]:
        res = subprocess.run(["node", "--check", str(src)], capture_output=True, text=True, check=False)
        assert res.returncode == 0, f"Node 语法检查失败: {src.name}\n{res.stderr}"


@needs_node
def test_plan_edit_module_exports() -> None:
    """断言 plan-edit.js 导出了必要的函数与组件。"""
    data = _run_node_vm({"action": "checkExports"})
    exports = set(data["exportsList"])
    required = {
      "validateMilestoneDate",
      "buildMilestonesSavePayload",
      "saveMilestoneDate",
      "PlanTimeline",
      "PlanDateModal",
      "PlanTable",
      "PlanSection",
      "MILESTONE_TONE",
    }
    assert required.issubset(exports), f"缺少必要导出: {required - exports}"


@needs_node
def test_date_validation_logic() -> None:
    """断言日期校验规则：周期范围、格式、已完成节点。"""
    phase = {
        "startDate": "2026-04-08",
        "endDate": "2026-08-30",
        "today": "2026-06-01",
    }
    dates = {
        "valid": "2026-05-15",
        "badFormat": "2026/05/15",
        "invalidDay": "2026-02-31",
        "tooEarly": "2026-04-01",
        "tooLate": "2026-09-01",
        "doneFuture": "2026-06-15",
        "donePast": "2026-05-20",
    }
    res = _run_node_vm({"action": "validateDates", "phase": phase, "dates": dates})["validation"]
    assert res["valid"] is None
    assert res["empty"] is None
    assert res["nullVal"] is None
    assert res["badFormat"] == "日期格式应为 YYYY-MM-DD"
    assert res["invalidDay"] == "日期格式应为 YYYY-MM-DD"
    assert "2026-04-08" in res["tooEarly"]
    assert "2026-08-30" in res["tooLate"]
    assert "不能晚于当前日期" in res["doneFuture"]
    assert res["donePast"] is None


@needs_node
def test_build_milestones_save_payload() -> None:
    """断言构建的 PATCH 载荷：目标节点更新、保留其他节点、清空日期置未开始。"""
    milestones = [
        {"id": 1, "name": "项目启动", "date": "2026-04-08", "status": "已完成", "type": "done", "sortOrder": 1},
        {"id": 2, "name": "VDR 决策", "date": "2026-06-15", "status": "进行中", "type": "current", "sortOrder": 2},
        {"id": 3, "name": "OTS", "date": None, "status": "未开始", "type": "planned", "sortOrder": 3},
    ]
    res = _run_node_vm({
        "action": "buildPayload",
        "milestones": milestones,
        "targetId": 2,
        "newDate": "2026-07-01",
        "updatedAt": "v100",
    })

    # 更新日期载荷
    payload = res["payloadUpdated"]
    assert payload["updatedAt"] == "v100"
    assert len(payload["milestones"]) == 3
    assert payload["milestones"][0]["date"] == "2026-04-08"
    assert payload["milestones"][1]["id"] == 2
    assert payload["milestones"][1]["date"] == "2026-07-01"
    assert payload["milestones"][1]["status"] == "进行中"

    # 清空日期载荷：状态自动置为未开始，避免触发后端校验异常
    cleared = res["payloadCleared"]
    assert cleared["milestones"][1]["date"] is None
    assert cleared["milestones"][1]["status"] == "未开始"
    assert cleared["milestones"][1]["type"] == "planned"


@needs_node
def test_save_milestone_date_request_and_conflict_mapping() -> None:
    """断言统一保存函数的请求路径、HTTP 方法、请求体与 409 冲突映射。"""
    phase = {
        "id": "VPI-T2",
        "startDate": "2026-04-08",
        "endDate": "2026-08-30",
        "today": "2026-06-01",
        "updatedAt": "v2026",
    }
    milestones = [
        {"id": 10, "name": "OTS 节点", "date": "2026-05-10", "status": "未开始", "type": "planned", "sortOrder": 1},
    ]
    res = _run_node_vm({
        "action": "testSave",
        "phaseId": "VPI-T2",
        "milestones": milestones,
        "targetId": 10,
        "newDate": "2026-05-25",
        "phase": phase,
    })

    assert res["saveSuccess"]["ok"] is True
    req = res["requestRecorded"]
    assert req["url"] == "/api/project-status/phases/VPI-T2/milestones"
    assert req["opts"]["method"] == "PATCH"
    body = req["opts"]["body"]
    assert body["updatedAt"] == "v2026"
    assert body["milestones"][0]["date"] == "2026-05-25"

    # 校验拦截：日期非法时不应发起网络请求
    assert res["saveInvalidDate"]["ok"] is False
    assert "节点日期需在阶段周期" in res["saveInvalidDate"]["error"]
    assert res["requestOnInvalid"] == 0

    # 409 冲突映射
    assert res["saveConflict"]["ok"] is False
    assert res["saveConflict"]["error"] == "主计划已被其他会话更新，请刷新后重试"


@needs_node
def test_unscheduled_node_entrance_maintained_and_edit_trigger() -> None:
    """断言未排期节点的「去排期」行为保持，已排期节点可点击修改。"""
    phase = {
        "id": "VPI-T2",
        "startDate": "2026-04-08",
        "endDate": "2026-08-30",
        "today": "2026-06-01",
        "updatedAt": "v1",
    }
    milestones = [
        {"id": 1, "name": "已排期节点", "date": "2026-05-20", "status": "进行中", "type": "current", "sortOrder": 1},
        {"id": 2, "name": "未排期节点", "date": None, "status": "未开始", "type": "planned", "sortOrder": 2},
    ]
    res = _run_node_vm({
        "action": "renderComponents",
        "phase": phase,
        "milestones": milestones,
    })

    timeline = res["timelineHtml"]
    table = res["tableHtml"]

    # 1. 未排期节点：必须保留「去排期」链接且指向既有主计划维护页 #p/project-overview/plan
    assert 'href="#p/project-overview/plan"' in timeline
    assert "去排期" in timeline
    assert 'href="#p/project-overview/plan"' in table
    assert "去排期" in table

    # 2. 已排期节点：展示截断月日，且带可点击触发编辑特征
    assert "05-20" in timeline
    assert "点击修改日期" in timeline

    # 3. 表格模式内联编辑与保存按钮
    assert "阶段节点" in table
    assert "里程碑日期" in table
    assert "保存" in table
    assert 'type="date"' in table

    # 4. 区块切换器
    section = res["sectionHtml"]
    assert "时间轴" in section
    assert "表格" in section


def test_user_visible_text_has_no_banned_terms() -> None:
    """门禁测试：用户可见文案禁止包含技术术语与代码文件特征。"""
    banned_literals = ["JSON", "Base URL", "Worker", "快照", "取证"]
    drive_pattern = re.compile(r"[a-zA-Z]:\\[^\s\"'`<>]+")
    py_pattern = re.compile(r"\b[a-zA-Z0-9_.-]+\.py\b")

    for file_path in [PLAN_EDIT_JS, PROJECT_JS]:
        content = file_path.read_text(encoding="utf-8")
        # 提取可见文案特征（过滤掉单行注释与引用）
        code_lines = [
            ln for ln in content.splitlines()
            if not ln.strip().startswith("//") and not ln.strip().startswith("/*") and not ln.strip().startswith("*")
        ]
        active_text = "\n".join(code_lines)

        for word in banned_literals:
            assert word not in active_text, f"{file_path.name} 存在禁用术语: {word}"

        assert not drive_pattern.search(active_text), f"{file_path.name} 存在盘符路径特征"


def test_backend_milestones_round_trip_with_plan_edit_payload(client) -> None:
    """端到端集成：使用实际主计划接口与 plan-edit.js 载荷格式进行往返验证。"""
    # 1. 查询当前阶段状态
    res = client.get("/api/project-status?phase=VPI-T2")
    assert res.status_code == 200
    initial = res.get_json()["data"]
    phase = initial["phase"]
    milestones = initial["milestones"]
    assert len(milestones) > 0

    first = milestones[0]
    updated_date = phase["startDate"]

    # 2. 模拟 plan-edit.js 生成的更新载荷
    list_payload = []
    for m in milestones:
        if m["id"] == first["id"]:
            list_payload.append({
                "id": m["id"],
                "name": m["name"],
                "date": updated_date,
                "status": "已完成",
                "type": "done",
                "sortOrder": m["sortOrder"],
            })
        else:
            list_payload.append({
                "id": m["id"],
                "name": m["name"],
                "date": m["date"],
                "status": m["status"],
                "type": m["type"],
                "sortOrder": m["sortOrder"],
            })

    patch_payload = {
        "milestones": list_payload,
        "updatedAt": phase["updatedAt"],
    }

    # 3. 调用既有 PATCH 接口
    patch_res = client.patch("/api/project-status/phases/VPI-T2/milestones", json=patch_payload)
    assert patch_res.status_code == 200, patch_res.get_json()
    result_data = patch_res.get_json()["data"]["projectStatus"]
    assert result_data["milestones"][0]["date"] == updated_date
    assert result_data["milestones"][0]["status"] == "已完成"

    # 4. 再次使用已过期的 updatedAt 提交，验证乐观锁 409 冲突
    stale_res = client.patch("/api/project-status/phases/VPI-T2/milestones", json=patch_payload)
    assert stale_res.status_code == 409
    assert stale_res.get_json()["error"]["message"] == "主计划已被其他会话更新，请刷新后重试"
