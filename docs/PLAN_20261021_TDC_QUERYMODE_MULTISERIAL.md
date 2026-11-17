# TDC 数模「查询模式切换后预览失败」与「多流水单号合并同步」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 先止血「填了流水单号 + 官方 Excel 预览 → 查询预览 400」，再让数模审批同步支持「多个流水单号合并统计」的聚合绑定。

**Architecture:** 第 1 批只改交互与错误语义（后端结构化错误码 + 两个插件同源守卫 + 诚实文案），不碰绑定契约；第 2 批在绑定契约新增 `matchRule.documentNos`（多值，聚合绑定），复用既有 `match_serials` 本地匹配与聚合证据门禁（`observation_is_aggregate` + config signature），存量单值绑定**不升级、不改写**。

**Tech Stack:** Python 3.12 + Flask（`web/app.py`）、SQLite、Preact/htm 插件前端（`plugins/*/static/*.js`）、pytest + node 静态/VM 测试、PyInstaller onedir 单 exe。

**Spec:** 本文件即方案正文（含顾问意见 run `89d0f5f1-9908-42aa-a98e-86873a782f10` 的裁决结果）。

## Global Constraints

- 流水单号绝不作为上游查询参数发送（`values.pop("document_no"/"document_nos")`）。
- 导出链路保持「全部单号命中才成功」（`SerialNotFound` 422），不得放宽。
- 单值输入框（`matchRule.documentNo`）继续 fail-closed，绝不接受多值整串。
- 存量绑定不自动升级、不重写 `match_rule_json`；签名/摘要口径对存量必须逐字节不变。
- 两个插件（`plugins/deliverables`、`plugins/system_query`）行为与文案必须一致，由 parity 测试钉住。
- 运行期遇到契约外 matchRule 键已 fail-closed（`assert_sync_ready` 的 `issubset(contract["matchKeys"])`），不得回退成"忽略未知键"。
- 所有用户可见文案用中文；测试与代码注释沿用仓库现有中文风格。
- 门禁命令统一用 `.runtime/pr3-review-venv/Scripts/python.exe -m pytest`；flake8 改动文件 0 告警；`tools/generate_project_map.py --check` 必须 verified。

---

# 第 1 批（止血，纯交互 + 错误语义，无契约变更）

### Task 1: 后端把「单号 + 官方预览」的拒绝改成可执行引导

**Files:**
- Modify: `web/app.py:3150-3158`
- Test: `tests/test_deliverables_web.py:799-805`（改写既有用例）、新增两个用例

**Interfaces:**
- Produces: 错误体 `{"error": {"type": "SerialRequiresListSource", "message": <可执行引导>}}`，HTTP 400 不变。

- [ ] **Step 1: 改写失败用例**

```python
# tests/test_deliverables_web.py:799
def test_tdc_data_model_query_document_no_rejects_official_export_source(client) -> None:
    """官方导出预览是另一种数据源：不能静默忽略 document_no 后把全量行当结果。"""
    resp = _document_no_query(client, "F610S-3D-0001", preview_source="official_export")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"]["type"] == "SerialRequiresListSource"
    assert "快速查询" in body["error"]["message"]
    assert "导出合并结果" in body["error"]["message"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_deliverables_web.py::test_tdc_data_model_query_document_no_rejects_official_export_source -v`
Expected: FAIL（`ValidationError` != `SerialRequiresListSource`）

- [ ] **Step 3: 新增「空单号不触发守卫」用例**

```python
def test_tdc_data_model_official_preview_without_serial_skips_guard(client, monkeypatch) -> None:
    """缺省/空白单号不是本地匹配请求：官方预览必须照常可用。"""
    seen = []

    def fake_preview(payload, filters, allowed_hosts, **kwargs):
        seen.append(kwargs["operation"])
        return {"report_type": "data_model", "data_source": "official_export", "rows": []}

    monkeypatch.setattr(web_app, "_tdc_official_data_model_preview", fake_preview)
    for extra in ({}, {"document_no": ""}, {"document_no": "   "}):
        payload = {
            "base_url": "https://tdc.example", "auth_mode": "password",
            "username": "fictional-user", "password": "fictional-password-secret",
            "filters": {"project_model": "F610S"}, "preview_source": "official_export",
            **extra,
        }
        resp = client.post("/api/tdc/data-model/query", json=payload)
        assert resp.status_code == 200
    assert seen == ["query", "query", "query"]
```

- [ ] **Step 4: 改实现**

```python
# web/app.py:3151-3158
if document_nos is not None:
    # 流水单号必须走全量翻页 + 本地精确匹配；官方导出预览是另一种数据源，
    # 静默忽略 document_no 会让用户拿到"全部行"当成匹配结果。
    if preview_source != "list_endpoint":
        raise _TDCRequestError(
            "填了流水单号时，查询预览只能用「快速查询（list 接口）」：请把查询模式切回快速查询；"
            "需要官方 47 列全量请到交付物工作台使用「导出合并结果」，或清空流水单号后再用官方 Excel 预览。",
            "SerialRequiresListSource",
            400,
        )
    return _tdc_data_model_serial_query(payload, filters, allowed_hosts, document_nos)
```

- [ ] **Step 5: 补「全量抓取忽略单号」的显式用例（Astra 排查新增）**

`/api/tdc/data-model/crawl-all` 在 `preview_source=official_export` 时**不读** `document_no`
（`web/app.py:3230-3255`，全仓只有 `_tdc_report_query` 与 `_tdc_report_export_merged` 读单号）：
它是「全量抓取」语义，忽略单号是设计而不是缺陷，但必须显式钉住，避免以后被当成漏改。

```python
def test_crawl_all_ignores_document_no_and_reports_full_scope(client, monkeypatch) -> None:
    """全量抓取按定义忽略流水单号（两种数据源都是），返回的是条件范围内的全部行。"""
    rows = [{"incident": "900001", "documentNo": "F610S-3D-0001"}]
    _stub_data_model_crawl(monkeypatch, rows, complete=True)
    payload = {
        "base_url": "https://tdc.example", "auth_mode": "password",
        "username": "fictional-user", "password": "fictional-password-secret",
        "filters": {"project_model": "F610S"}, "document_no": "F610S-3D-0002",
    }
    resp = client.post("/api/tdc/data-model/crawl-all", json=payload)
    assert resp.status_code == 200
    assert "serialMatch" not in resp.get_json()["data"]
```

- [ ] **Step 6: 跑通**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_deliverables_web.py -q -k "document_no or official_preview or crawl_all_ignores"`
Expected: PASS（含既有 official preview 用例）

- [ ] **Step 6: 提交**

```bash
git add web/app.py tests/test_deliverables_web.py
git commit -m "fix(tdc): 单号+官方预览返回可执行引导错误码 SerialRequiresListSource"
```

### Task 2: system_query 插件加同源守卫

**Files:**
- Modify: `plugins/system_query/static/lib.js`（新增常量与判定函数，约 74 行附近与文件末尾）
- Modify: `plugins/system_query/static/query.js:690-790`
- Test: `tests/test_plugin_system_query.py`

**Interfaces:**
- Produces: `export const SERIAL_REQUIRES_LIST_NOTICE: string`；`export function serialSourceConflict(values, mode): boolean`（两个插件同名同语义，Task 3 复用）。

- [ ] **Step 1: 写失败用例（node 静态/VM 断言）**

```python
# tests/test_plugin_system_query.py 追加
def test_serial_source_conflict_predicate_and_notice(node_lib) -> None:
    script = """
const lib = await import(LIB);
const mode = { previewSource: true };
out.officialWithSerial = lib.serialSourceConflict({document_no: " 3D-1 ", preview_source: "official_export"}, mode);
out.officialEmpty = lib.serialSourceConflict({document_no: "", preview_source: "official_export"}, mode);
out.listWithSerial = lib.serialSourceConflict({document_no: "3D-1", preview_source: "list_endpoint"}, mode);
out.noMode = lib.serialSourceConflict({document_no: "3D-1", preview_source: "official_export"}, null);
out.notice = lib.SERIAL_REQUIRES_LIST_NOTICE;
"""
    data = run_node(node_lib, script)  # 复用本文件既有 node harness
    assert data["officialWithSerial"] is True
    assert data["officialEmpty"] is False
    assert data["listWithSerial"] is False
    assert data["noMode"] is False
    assert "快速查询" in data["notice"] and "导出合并结果" in data["notice"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_plugin_system_query.py -q -k serial_source_conflict -v`
Expected: FAIL（`serialSourceConflict is not a function`）

- [ ] **Step 3: 在 lib.js 实现**

```javascript
// plugins/system_query/static/lib.js（PREVIEW_SOURCES 定义之后）
export const SERIAL_REQUIRES_LIST_NOTICE =
  "填了流水单号时，查询预览只能用「快速查询（list 接口）」：请把查询模式切回快速查询；"
  + "需要官方 47 列全量请到交付物工作台使用「导出合并结果」。";

export function serialSourceConflict(values, mode) {
  if (!mode || !mode.previewSource) return false;
  const hasSerial = Boolean(String((values && values.document_no) || "").trim());
  if (!hasSerial) return false;
  return String((values && values.preview_source) || "list_endpoint") === "official_export";
}
```

- [ ] **Step 4: query.js 接线（禁用按钮 + 主区域提示 + 执行前短路）**

```javascript
// plugins/system_query/static/query.js：mergedExportNotice 之后
const serialSourceBlocked = serialSourceConflict(values, mode);
// 查询按钮（既有「查询预览」按钮）
<button class="primary-btn" type="button" data-action="query"
  disabled=${busy || serialSourceBlocked} onClick=${() => run("query")}>查询预览</button>
${serialSourceBlocked && html`<div class="error-msg sq-warning" role="status">${SERIAL_REQUIRES_LIST_NOTICE}</div>`}
```

`run("query")` 入口加同源短路：

```javascript
if (action === "query" && serialSourceConflict(values, mode)) {
  setStatus({ text: SERIAL_REQUIRES_LIST_NOTICE, error: true });
  return;
}
```

- [ ] **Step 5: 跑通并做语法检查**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_plugin_system_query.py -q`；`node --check plugins/system_query/static/lib.js`；`node --check plugins/system_query/static/query.js`
Expected: PASS / 无输出

- [ ] **Step 6: 提交**

```bash
git add plugins/system_query/static/lib.js plugins/system_query/static/query.js tests/test_plugin_system_query.py
git commit -m "feat(system_query): 单号+官方预览禁用查询预览并给出可执行引导"
```

### Task 3: deliverables 插件同源实现 + parity 钉住

**Files:**
- Modify: `plugins/deliverables/static/lib.js`、`plugins/deliverables/static/catalog.js:680-700`
- Test: `tests/test_deliverables_system_query_parity.py`

**Interfaces:**
- Consumes: Task 2 的 `SERIAL_REQUIRES_LIST_NOTICE` / `serialSourceConflict`（同名同签名，独立实现，不跨插件 import）。

- [ ] **Step 1: parity 用例（先失败）**

```python
# tests/test_deliverables_system_query_parity.py：扩展既有 node harness 的收集脚本
const dlvConflict = dlvLib.serialSourceConflict({document_no: "3D-1", preview_source: "official_export"}, {previewSource: true});
const sqConflict = sqLib.serialSourceConflict({document_no: "3D-1", preview_source: "official_export"}, {previewSource: true});
out.dlvNotice = dlvLib.SERIAL_REQUIRES_LIST_NOTICE;
out.sqNotice = sqLib.SERIAL_REQUIRES_LIST_NOTICE;
out.dlvConflict = dlvConflict;
out.sqConflict = sqConflict;

def test_serial_source_guard_is_identical(parity: dict) -> None:
    assert parity["dlvNotice"] == parity["sqNotice"]
    assert parity["dlvConflict"] is True and parity["sqConflict"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_deliverables_system_query_parity.py -q -k serial_source_guard -v`
Expected: FAIL

- [ ] **Step 3: 在 deliverables/lib.js 复制 Task 2 的两段实现（文案逐字一致），catalog.js 按同一模式禁用「查询预览」并显示提示**

```javascript
// plugins/deliverables/static/catalog.js：与 system_query 完全相同的三个接入点
const serialSourceBlocked = serialSourceConflict(values, mode);
disabled=${busy || serialSourceBlocked}
${serialSourceBlocked && html`<div class="error-msg sq-warning" role="status">${SERIAL_REQUIRES_LIST_NOTICE}</div>`}
```

- [ ] **Step 4: 跑通**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_deliverables_system_query_parity.py tests/test_plugin_deliverables.py tests/test_plugin_system_query.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add plugins/deliverables/static/lib.js plugins/deliverables/static/catalog.js tests/test_deliverables_system_query_parity.py
git commit -m "feat(deliverables): 与 system_query 同源的单号/官方预览守卫 + parity 断言"
```

### Task 4: 多单号同步的诚实文案（第 1 批不变更能力）

**Files:**
- Modify: `services/data_model_watchlist.py:66-69`
- Modify: `plugins/project_overview/static/deliverable/policy-logic.js:76`
- Test: `tests/test_data_model_identity_contract.py:152-156`、`tests/test_plugin_overview_parity_logic.py`

**Interfaces:**
- Produces: 后端与前端同一句文案（逐字一致，parity 断言）。

- [ ] **Step 1: 写文案一致性用例（先失败）**

```python
def test_multi_serial_message_is_actionable() -> None:
    from services.data_model_watchlist import WatchlistError, normalize_single_serial
    with pytest.raises(WatchlistError) as excinfo:
        normalize_single_serial("3D-00001020 3D-00001018")
    text = str(excinfo.value)
    assert "合并统计同步暂不支持" in text
    assert "导出合并结果" in text
```

- [ ] **Step 2: 运行确认失败**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_data_model_identity_contract.py -q -k multi_serial_message -v`
Expected: FAIL（现文案是"一次只能填一个"）

- [ ] **Step 3: 改文案（后端 + 前端逐字一致）**

> Astra 复核修正：用户口径是「合并统计」，因此**不得**把「逐张单据各建一个交付物」写成答案，
> 文案只说明现状与可用替代，不提拆交付物。

```python
# services/data_model_watchlist.py:66-69
raise WatchlistError(
    "多单号合并统计同步暂不支持（开发中）；当前可用「导出合并结果」按多个单号取数"
)
```

```javascript
// plugins/project_overview/static/deliverable/policy-logic.js:76
return "多单号合并统计同步暂不支持（开发中）；当前可用「导出合并结果」按多个单号取数。";
```

- [ ] **Step 4: 跑通（含既有断言迁移）**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_data_model_identity_contract.py tests/test_plugin_overview_parity_logic.py tests/test_project_status_admin_api.py -q`
Expected: PASS（若既有用例断言旧文案，同步改断言）

- [ ] **Step 5: 第 1 批整体门禁 + 提交**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_deliverables_web.py tests/test_plugin_system_query.py tests/test_plugin_deliverables.py tests/test_deliverables_system_query_parity.py tests/test_data_model_identity_contract.py tests/test_project_status_policy_api.py -q`；`python tools/generate_project_map.py --check`
Expected: 全绿 + verified

```bash
git add services/data_model_watchlist.py plugins/project_overview/static/deliverable/policy-logic.js tests/
git commit -m "chore(tdc): 多单号同步改为诚实文案（能力见第 2 批）"
```

---

# 第 2 批（D：多单号合并统计绑定，默认功能开关关闭）

### Task 5: 共享多值规范化 `normalize_serial_set`

**Files:**
- Modify: `services/data_model_watchlist.py`（新增函数，紧邻 `normalize_single_serial`）
- Test: `tests/test_data_model_watchlist.py`

**Interfaces:**
- Produces: `normalize_serial_set(value: str | Sequence[str]) -> list[str]`（逐项走 `normalize_single_serial`，去重 + 排序；上限 `MAX_WATCHLIST` = 500；空/超限抛 `WatchlistError`）。

- [ ] **Step 1: 失败用例**

```python
def test_normalize_serial_set_dedupes_and_sorts() -> None:
    from services.data_model_watchlist import normalize_serial_set
    assert normalize_serial_set("3D-2, 3D-1 3D-2") == ["3D-1", "3D-2"]
    assert normalize_serial_set(["3D-2", "3D-1"]) == ["3D-1", "3D-2"]

def test_normalize_serial_set_rejects_bad_members() -> None:
    from services.data_model_watchlist import WatchlistError, normalize_serial_set
    for bad in ([], "", ["3D-1", "3D-1 3D-2"], ["3D-1", "  "]):
        with pytest.raises(WatchlistError):
            normalize_serial_set(bad)
```

- [ ] **Step 2: 运行确认失败**（函数不存在）

- [ ] **Step 3: 实现**

```python
def normalize_serial_set(value: Any) -> list[str]:
    """多值流水单号（合并统计绑定）：逐项走单值校验，去重后排序保证签名稳定。"""
    if isinstance(value, str):
        terms = parse_terms(value)
    elif isinstance(value, (list, tuple)):
        terms = [str(item) for item in value]
    else:
        raise WatchlistError("流水单号必须是字符串或字符串数组")
    if not terms:
        raise WatchlistError("流水单号不能为空")
    if len(terms) > MAX_WATCHLIST:
        raise WatchlistError(f"流水单号一次最多 {MAX_WATCHLIST} 个，请分批处理")
    return sorted({normalize_single_serial(term) for term in terms})
```

- [ ] **Step 4: 跑通 + 提交**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_data_model_watchlist.py -q`

```bash
git add services/data_model_watchlist.py tests/test_data_model_watchlist.py
git commit -m "feat(tdc): 新增 normalize_serial_set 多值流水单号规范化"
```

### Task 6: 绑定契约新增 `documentNos`（仅 D5）

**Files:**
- Modify: `core/project_status_contracts.py`（`PROJECT_STATUS_SOURCE_CAPABILITIES["VPI-T2-D5"]` 的 `matchKeys` / `matchFields`）
- Modify: `web/app.py:1240-1254`（`_MAPPING_DISCOVERY_RULE_FIELDS[("tdc","data_model")]` 增 `document_nos`）
- Test: `tests/test_project_status_policy_api.py`、`tests/test_deliverables_system_query_parity.py:173-183`

**Interfaces:**
- Produces: 契约键 `documentNos`（list[str]，与 `documentNo` 互斥）；discovery 过滤名 `document_nos`。

- [ ] **Step 1: 失败用例（契约可见性）**

```python
def test_d5_contract_exposes_multi_serial_key() -> None:
    from core.project_status_contracts import PROJECT_STATUS_SOURCE_CAPABILITIES
    caps = PROJECT_STATUS_SOURCE_CAPABILITIES["VPI-T2-D5"]
    assert "documentNos" in caps["matchKeys"]
    names = [item[2] for item in caps["matchFields"]]
    assert "document_nos" in names
    # 其它交付物不得出现该键
    assert all("documentNos" not in PROJECT_STATUS_SOURCE_CAPABILITIES[key]["matchKeys"]
               for key in ("VPI-T2-D2", "VPI-T2-D3"))
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 改契约**

```python
# core/project_status_contracts.py：D5 matchKeys 增 "documentNos"（紧随 "documentNo"）
"matchKeys": (
    "incident", "documentNo", "documentNos", "applicant", "department", "section",
    "applicationStart", "applicationEnd", "projectModel",
    "partNumber", "modelNumber", "status", "aggregate", "reportType",
),
# matchFields 增一行（放在 documentNo 之后）
("documentNos", "流水单号（多个，合并统计）", "document_nos",
 "多个单号用空格/逗号分隔；填多个时按集合合并统计，与实例号二选一"),
```

```python
# web/app.py:1252 附近
"document_no": "documentNo",
"document_nos": "documentNos",
```

- [ ] **Step 4: 跑通（含 parity 字段集断言迁移）**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_project_status_policy_api.py tests/test_deliverables_system_query_parity.py tests/test_plugin_system_query.py -q`
Expected: PASS；`_TDC_DATA_MODEL_FILTER_NAMES` 与目录字段集的既有断言需按新字段更新（catalog 是单源，`document_nos` 同样不是服务端 filter）

- [ ] **Step 5: 提交**

```bash
git add core/project_status_contracts.py web/app.py tests/
git commit -m "feat(tdc): D5 绑定契约新增多单号键 documentNos"
```

### Task 7: 签名/摘要对多值键的规范化（存量逐字节不变）

**Files:**
- Modify: `services/project_status_records.py:80-90`（`_QUERY_RULE_KEYS_BY_SOURCE["tdc"]` 增 `documentNos`）、`:259-275`（列表规范化分支）
- Test: `tests/test_bprime_config_digest_spec.py`、新增 golden 用例

**Interfaces:**
- Consumes: Task 5 `normalize_serial_set`（或在签名内联等价的 sorted-join，避免新增依赖）。
- Produces: `compute_config_signature("tdc", {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-2","3D-1"]})` 与 `documentNos: ["3D-1","3D-2"]` 结果相同；不含 `documentNos` 的规则签名**逐字不变**。

- [ ] **Step 1: 失败用例**

```python
def test_signature_canonicalizes_document_nos() -> None:
    from services.project_status_records import compute_config_signature
    base = {"reportType": "data_model", "aggregate": True}
    a = compute_config_signature("tdc", {**base, "documentNos": ["3D-2", "3D-1"]})
    b = compute_config_signature("tdc", {**base, "documentNos": [" 3D-1 ", "3D-2", "3D-1"]})
    c = compute_config_signature("tdc", {**base, "documentNos": "3D-1 3D-2"})
    assert a == b == c

def test_signature_of_legacy_single_serial_rule_is_unchanged() -> None:
    """golden：契约新增键不得改变存量规则的签名。"""
    from services.project_status_records import compute_config_signature
    sig = compute_config_signature("tdc", {"reportType": "data_model", "aggregate": False, "documentNo": "3D-00001018"})
    assert sig == "sig:28bf6d069facde729ee1fe06bf56"
    agg = compute_config_signature("tdc", {"reportType": "data_model", "aggregate": True, "projectModel": "F610S"})
    assert agg == "sig:5da94c0257977e70332cc3eaf9eb"
```

> 两个 golden 值已于 2026-10-21 在本机实测记录（与 memory 里 20261010 的 `sig:28bf6d06…` 一致）；改动后复跑必须逐字节相同。

- [ ] **Step 2: 运行确认失败**（`documentNos` 被当作非字符串拒绝 → ValueError）

- [ ] **Step 3: 实现**

```python
# services/project_status_records.py:83 增 "documentNos"
# :259-275 循环内，在 "aggregate" 分支之后插入
        if key_str == "documentNos":
            if isinstance(v, str):
                items = sorted({item.strip() for item in re.split(r"[\s,;、\r\n]+", v) if item.strip()})
            elif isinstance(v, (list, tuple)):
                items = sorted({str(item).strip() for item in v if str(item).strip()})
            else:
                raise ValueError("match_rule documentNos must be a string or a list of strings")
            if not items:
                raise ValueError("match_rule documentNos must not be empty")
            cleaned[key_str] = " ".join(items)
            continue
```

- [ ] **Step 4: 跑通（签名/摘要/审计相关套件）**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_bprime_config_digest_spec.py tests/test_bprime_config_concurrency_digest.py tests/test_project_status_policy_api.py tests/test_project_status_records.py -q`
Expected: PASS，且 golden 用例证明存量签名/摘要不变

- [ ] **Step 5: 提交**

```bash
git add services/project_status_records.py tests/
git commit -m "feat(tdc): 配置签名支持 documentNos 规范化（存量签名不变）"
```

### Task 8: 保存与运行前校验（互斥、聚合、全命中门禁）

**Files:**
- Modify: `services/project_status_updates.py:89-101`（`_valid_match_rule_values`）、`:470-500`（`assert_sync_ready`）、`:1034-1062`（PATCH 校验）
- Modify: `web/app.py:1411-1426`（`_mapping_discovery_query_identity` 互斥与聚合推导）
- Test: `tests/test_project_status_policy_api.py`、`tests/test_project_status_admin_api.py`

**Interfaces:**
- Consumes: Task 5/6/7。
- Produces: 规则不变量——`documentNos` 存在 ⇒ `aggregate is True` 且 `external_key` 为空；`documentNos` 与 `documentNo`/`incident`/`syncScope=watchlist` 三者任一互斥。

- [ ] **Step 1: 失败用例（互斥与聚合）**

```python
@pytest.mark.parametrize(("rule", "field"), [
    ({"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"], "documentNo": "3D-2"}, "matchRule"),
    ({"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"], "incident": "900001"}, "matchRule"),
    ({"reportType": "data_model", "aggregate": False, "documentNos": ["3D-1"]}, "matchRule"),
])
def test_multi_serial_rule_rejects_invalid_combinations(client, rule, field) -> None:
    response = client.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json={"matchRule": rule})
    assert response.status_code == 422
    assert field in response.get_json()["error"]["fields"]
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现校验（三处同源，抽一个私有函数）**

```python
# services/project_status_updates.py
def _multi_serial_rule_error(match_rule: Mapping[str, Any], *, external_key: str | None, aggregate: bool) -> str | None:
    serials = match_rule.get("documentNos")
    if not serials:
        return None
    try:
        normalize_serial_set(serials)
    except WatchlistError as exc:
        return str(exc)
    if match_rule.get("documentNo") or match_rule.get("incident"):
        return "多单号与单个流水单号/实例号三选一：请只保留一种匹配方式"
    if not aggregate:
        return "多单号绑定必须是聚合绑定（aggregate=true）"
    if external_key:
        return "多单号绑定不接受单记录外部键"
    return None
```

在 `assert_sync_ready`（:470 之后）与 PATCH 校验（:1040 之后）各调用一次；`_valid_match_rule_values` 增加列表分支：

```python
        else (isinstance(value, (list, tuple)) and bool(value)
              and all(isinstance(item, str) and item.strip() for item in value))
        if key == "documentNos"
```

`web/app.py` 的 discovery identity 同样处理：`document_nos` → `rule["documentNos"] = normalize_serial_set(...)`，`rule["aggregate"] = True`，`values.pop("document_nos", None)`。

- [ ] **Step 4: 跑通 + 提交**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_project_status_policy_api.py tests/test_project_status_admin_api.py tests/test_project_status_updates.py -q`

```bash
git add services/project_status_updates.py web/app.py tests/
git commit -m "feat(tdc): 多单号绑定校验（互斥、聚合、拒绝单记录键）"
```

### Task 9: 映射发现支持多单号（聚合观测 + 部分命中）

**Files:**
- Modify: `web/app.py:5306-5456`（`run_observation` 的 document_no 分支）
- Test: `tests/test_project_status_api.py`（新增多单号发现用例）

**Interfaces:**
- Consumes: Task 5/8。
- Produces: 多单号发现返回 `serialMatch = {requested: [...], found: [...], missing: [...], scanned, matched, complete}`；全部命中 → `state="matched"`、`aggregate=True` 观测、`selected=None`；部分/全部缺失 → `state="not_found"`、`reason="serial_set_partial"`（可存草稿，不可启用）。

- [ ] **Step 1: 失败用例**

```python
def test_multi_serial_discovery_matches_union_as_aggregate(client, monkeypatch) -> None:
    rows = [
        {"incident": "FLOW-A", "documentNo": "3D-1", "partNumber": "P-1"},
        {"incident": "FLOW-B", "documentNo": "3D-2", "partNumber": "P-1"},
        {"incident": "FLOW-C", "documentNo": "3D-3", "partNumber": "P-1"},
    ]
    _stub(monkeypatch, rows, complete=True)
    response = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json={
        "filters": {"document_nos": ["3D-1", "3D-2"]},
        "aggregate": True,
    })
    body = response.get_json()["data"]
    assert response.status_code == 200
    assert body["serialMatch"]["found"] == ["3D-1", "3D-2"]
    assert body["serialMatch"]["missing"] == []
    assert body["observation"]["state"] == "matched"

def test_multi_serial_discovery_partial_match_is_not_found(client, monkeypatch) -> None:
    rows = [{"incident": "FLOW-A", "documentNo": "3D-1", "partNumber": "P-1"}]
    _stub(monkeypatch, rows, complete=True)
    response = client.post("/api/project-status/deliverables/VPI-T2-D5/mapping-discovery", json={
        "filters": {"document_nos": ["3D-1", "3D-9"]}, "aggregate": True,
    })
    body = response.get_json()["data"]
    assert body["serialMatch"]["missing"] == ["3D-9"]
    assert body["observation"]["state"] == "not_found"
    assert body["observation"]["reason"] == "serial_set_partial"
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现（多单号走 `match_serials`，跳过单记录唯一性检查）**

```python
# web/app.py:5381 分支改为
document_nos = match_rule.get("documentNos") or None
if document_nos:
    if not _mapping_result_is_complete(crawl_result):   # 与单值同一条 fail-closed
        raise _TDCRequestError("抓取不完整，无法判定流水单号集合，请重试", "IncompleteDiscovery", 422)
    matched, bookkeeping = match_serials(rows, document_nos)
    serial_match = {
        "requested": list(document_nos), "found": bookkeeping["found"],
        "missing": bookkeeping["missing"], "scanned": bookkeeping["scanned"],
        "matched": bookkeeping["matched"], "complete": True,
    }
    rows = matched
    effective_selected = None          # 聚合绑定无单记录键
elif document_no:
    ... 既有单值分支保持不变 ...
```

缺失时（`serial_match["missing"]`）在 observation 上写 `state="not_found"`、`reason="serial_set_partial"`，并在返回体带 `serialMatch`（不得静默按已命中子集建绑定）。

- [ ] **Step 4: 证据指纹改用「配置单号成员身份」（Astra 排查新增，必做）**

背景（已核实）：`aggregate_fingerprint`（`services/project_status_records.py:213-222`）只哈希
**行身份集合**（数模=incident）。多单号场景下上游行集会随新增零件行/新增实例变化，导致连续两次
观测指纹永不一致，`_mapping_evidence_error` 的「两次指纹一致」门禁实际上不可达 ⇒ 绑定永远无法启用。
因此多单号绑定的证据基线改为**配置单号集合 ∩ 已命中单号**（成员身份），行内容与行数不参与。

```python
# services/project_status_discovery.py:82-92 增加可选参数
    def observe(
        self, deliverable_id, source_type, rows, selected_external_key=None, *,
        aggregate: bool = False, match_rule=None, upstream_total=None,
        fingerprint_identities: Sequence[str] | None = None,
    ):
        ...
        # 聚合指纹：默认沿用行身份（存量行为逐字不变）；多单号绑定传成员身份
        identities = (
            list(fingerprint_identities) if fingerprint_identities is not None
            else [key for key, _ in keyed]
        )
        aggregate_key = aggregate_fingerprint([(item, {}) for item in identities])
```

```python
# web/app.py 多单号分支调用
observation = discovery_service.observe(
    deliverable_id, "tdc", rows, None,
    aggregate=True, match_rule=match_rule, upstream_total=upstream_declared_total,
    fingerprint_identities=serial_match["found"],
)
```

- [ ] **Step 5: 成员身份稳定性用例（先失败）**

```python
def test_multi_serial_evidence_survives_new_part_rows(client, monkeypatch) -> None:
    """同一批单号，上游多出一行零件行，证据指纹必须不变（否则永远无法启用）。"""
    first = [{"incident": "FLOW-A", "documentNo": "3D-1", "partNumber": "P-1"}]
    second = [
        {"incident": "FLOW-A", "documentNo": "3D-1", "partNumber": "P-1"},
        {"incident": "FLOW-A2", "documentNo": "3D-1", "partNumber": "P-2"},
    ]
    payload = {"filters": {"document_nos": ["3D-1"]}, "aggregate": True}
    _stub(monkeypatch, first, complete=True)
    assert client.post(url, json=payload).get_json()["data"]["observation"]["state"] == "matched"
    _stub(monkeypatch, second, complete=True)
    assert client.post(url, json=payload).get_json()["data"]["observation"]["state"] == "matched"
    # 两次观测指纹一致 ⇒ 允许启用
    response = client.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy", json={
        "matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"]},
        "enabled": True, "credentialRef": "alias",
        "mapping": {"owner": "applicant"}, "fieldAuthority": {"owner": "automatic"},
    })
    assert response.status_code == 200
```

- [ ] **Step 6: 跑通 + 提交**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_project_status_api.py tests/test_project_status_admin_api.py tests/test_project_status_discovery.py -q`

```bash
git add web/app.py services/project_status_discovery.py tests/
git commit -m "feat(tdc): 映射发现支持多单号（聚合观测、成员身份证据、部分命中归因）"
```

### Task 10: 运行期连接器多单号收窄与完整性归因

**Files:**
- Modify: `services/project_status_connectors.py:374-490`
- Test: `tests/test_project_status_connectors.py`、`tests/test_project_status_sync_runner.py`

**Interfaces:**
- Consumes: `normalize_serial_set`、`match_serials`。
- Produces: 多单号绑定运行期行为——抓取不完整 → `ValueError("抓取不完整…")`（runner 记 needs_attention，保留上次快照）；全部缺失 → `tdc_document_nos_zero_match`；部分缺失 → `tdc_document_nos_partial_missing` + `ValueError`（不写部分结果）；行缺单号列 → 既有 `tdc_document_no_structure_drift`；原始归档行不收窄。

- [ ] **Step 1: 失败用例（部分缺失必须停跑，不得少算）**

```python
def test_multi_serial_partial_missing_raises_and_emits_diagnostic(monkeypatch) -> None:
    rows = [{"incident": "FLOW-A", "documentNo": "3D-1"}, {"incident": "FLOW-B", "documentNo": "3D-3"}]
    events = []
    monkeypatch.setattr(connectors, "emit", lambda name, payload, **kw: events.append(name))
    with pytest.raises(ValueError) as excinfo:
        connectors.TDCProjectStatusConnector._narrow_by_document_no(
            rows, {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1", "3D-2"]})
    assert "3D-2" in str(excinfo.value)
    assert "tdc_document_nos_partial_missing" in events
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# services/project_status_connectors.py：_narrow_by_document_no 开头
        serials = rule.get("documentNos")
        if serials:
            normalized = data_model_watchlist.normalize_serial_set(serials)
            matched, bookkeeping = data_model_watchlist.match_serials(rows, normalized)
            if not matched:
                emit("tdc_document_nos_zero_match",
                     {"report_type": "data_model", "scanned": bookkeeping["scanned"],
                      "requested": len(normalized)},
                     name="sync_connector.TDCProjectStatusConnector.collect")
                return []
            missing = [str(item) for item in bookkeeping.get("missing", [])]
            if missing:
                emit("tdc_document_nos_partial_missing",
                     {"report_type": "data_model", "missing": len(missing),
                      "requested": len(normalized)},
                     name="sync_connector.TDCProjectStatusConnector.collect")
                raise ValueError(
                    "部分流水单号未命中：" + "、".join(missing[:5]) +
                    "；本次不写入部分结果，请核对单号或补充车型/日期后重试"
                )
            return list(matched)
        document_no = str(rule.get("documentNo") or "").strip()   # 既有单值分支保持不变
```

- [ ] **Step 4: 跑通**

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_project_status_connectors.py tests/test_project_status_sync_runner.py tests/test_project_status_updates.py -q`

- [ ] **Step 5: 自愈回归（Astra 排查新增）**

已核实：失败只把 run 置 `needs_attention`，不改绑定 `enabled`；`list_eligible_sync_bindings`
（`core/repos/sync_runs.py:923-941`）只取 `enabled=1`，调度器仅按 `last_success_at` 新鲜度跳过
（`project_status_scheduler.py:8-12`，默认 900 s）⇒ 缺失单号补齐后下一次 tick 会自愈。
用一条用例把该行为钉住，防止以后有人「失败即停用绑定」：

```python
def test_partial_missing_keeps_binding_enabled_and_recovers_next_run(tmp_path, monkeypatch) -> None:
    # 第一次：3D-2 不存在 -> needs_attention，绑定仍 enabled
    runner.run_once(deliverable_id="VPI-T2-D5", trigger_type="scheduled")
    assert db.get_sync_binding_by_deliverable("VPI-T2-D5")["enabled"] == 1
    # 第二次：上游出现 3D-2 -> 同一绑定恢复 success，快照被替换
    runner.run_once(deliverable_id="VPI-T2-D5", trigger_type="scheduled")
    assert db.get_sync_binding_by_deliverable("VPI-T2-D5")["sync_state"] == "success"
```

- [ ] **Step 6: 提交**

```bash
git add services/project_status_connectors.py tests/
git commit -m "feat(tdc): 运行期多单号收窄与部分缺失 fail-closed"
```

### Task 11: 前端向导多值输入 + 功能开关 + 冒烟

**Files:**
- Modify: `plugins/project_overview/static/deliverable/policy-logic.js`（新增 `parseSerialSet` / `wizardMultiSerialError` / `buildWizardDiscovery` 多值分支）
- Modify: `plugins/project_overview/static/deliverable/policy.js`（向导新增「流水单号（多个）」输入 + 解析结果提示）
- Modify: `web/app.py`（`_mapping_discovery_query_identity` 与 PATCH 入口的开关判定）
- Test: `tests/p1d_frontend_fixture.py` 复用夹具新增用例、`tests/test_plugin_overview_parity_logic.py`
- Modify: `.runtime/smoke_exe_20261021.ps1` → 新建 `.runtime/smoke_exe_<新包>.ps1`

**Interfaces:**
- Consumes: Task 5–10。
- Produces: 功能开关 `VSE_TDC_MULTI_SERIAL_SYNC=1`（缺省关闭：关闭时 `documentNos` 一律 422 `MultiSerialSyncDisabled`）。

- [ ] **Step 1: 失败用例（前端解析 + 开关）**

```python
def test_wizard_parses_multi_serial_set() -> None:
    panel = load_policy_panel(Scenario(inputs={"documentNos": "3D-2, 3D-1 3D-2"}, ...))
    panel.result.assert_ok()
    assert panel.requests[-1].body["filters"]["document_nos"] == ["3D-1", "3D-2"]
    assert panel.requests[-1].body["aggregate"] is True

def test_multi_serial_disabled_by_default(client, monkeypatch) -> None:
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC", raising=False)
    response = client.patch("/api/project-status/deliverables/VPI-T2-D5/update-policy",
                            json={"matchRule": {"reportType": "data_model", "aggregate": True, "documentNos": ["3D-1"]}})
    assert response.status_code == 422
    assert response.get_json()["error"]["type"] == "MultiSerialSyncDisabled"
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现前端解析与输入**

```javascript
// plugins/project_overview/static/deliverable/policy-logic.js
export function parseSerialSet(text) {
  const raw = ewoPolicyString(text);
  if (!raw) return [];
  const terms = raw.normalize("NFKC").split(DOCUMENT_NO_SEPARATORS).map((item) => item.trim()).filter(Boolean);
  return Array.from(new Set(terms)).sort();
}

export function wizardMultiSerialError(values) {
  const serials = parseSerialSet(values.documentNos);
  if (!serials.length) return "";
  if (serials.length > 500) return "流水单号一次最多 500 个，请分批处理。";
  if (ewoPolicyString(values.documentNo) || ewoPolicyString(values.number)) {
    return "多单号与单个流水单号/实例号三选一：请只保留一种匹配方式。";
  }
  return "";
}
```

向导渲染在「流水单号」下方新增：`识别到 ${serials.length} 个单号（合并统计）`，并禁用单值框。

- [ ] **Step 4: 实现开关（后端）+ 关闭时的存量绑定语义（Astra 排查新增）**

开关关闭不仅要拦住**新建**多单号绑定，还必须定义**已存在**的多单号绑定在关闭/回退后的行为：
按「停跑但不算错」处理——`assert_sync_ready` 拒绝并给出可执行原因（绑定保持 enabled，
每次 tick 会重复报同一条 needs_attention，人工修规则或重新开启开关后自愈）。

```python
# web/app.py：PATCH 与 mapping-discovery 入口
def _multi_serial_enabled() -> bool:
    return str(os.environ.get("VSE_TDC_MULTI_SERIAL_SYNC") or "").strip() in {"1", "true", "yes"}

# 命中 documentNos 且开关关闭时
raise _TDCRequestError(
    "多单号同步尚未启用：请联系维护人员开启后重试", "MultiSerialSyncDisabled", 422)
```

```python
# services/project_status_updates.py：_multi_serial_rule_error 内追加（运行期同样生效）
    if match_rule.get("documentNos") and not multi_serial_enabled():
        return "多单号同步已被功能开关关闭：请改为单值绑定或联系维护人员开启"
```

配套用例：

```python
def test_disabled_flag_stops_existing_multi_binding_without_disabling_it(client, monkeypatch) -> None:
    monkeypatch.setenv("VSE_TDC_MULTI_SERIAL_SYNC", "1")
    _save_multi_binding(client)                      # 先合法建立
    monkeypatch.delenv("VSE_TDC_MULTI_SERIAL_SYNC")  # 模拟回退/关闭
    resp = client.post("/api/project-status/deliverables/VPI-T2-D5/sync-now", json={})
    assert resp.status_code == 409
    assert "功能开关关闭" in resp.get_json()["error"]["message"]
    binding = web_app.DatabaseManager().get_sync_binding_by_deliverable("VPI-T2-D5")
    assert binding["enabled"] == 1                   # 停跑但不停用
```

- [ ] **Step 5: 跑通 + 冒烟脚本扩展**

新增冒烟检查（沿用 20261021 脚本，端口 5176）：
- `documentNos` 在开关关闭时 422 `MultiSerialSyncDisabled`；开关打开（`$env:VSE_TDC_MULTI_SERIAL_SYNC=1`）时保存多单号草稿 200、`configDigest` 轮换；
- 包内 `policy-logic.js` 含 `parseSerialSet` 与「合并统计」文案；
- 既有 50 项全部保留。

Run: `.runtime/pr3-review-venv/Scripts/python.exe -m pytest tests/test_plugin_overview_parity_logic.py tests/test_project_status_policy_api.py tests/test_project_status_api.py -q`

- [ ] **Step 6: 提交**

```bash
git add plugins/project_overview/static/deliverable/ web/app.py tests/ .runtime/smoke_exe_*.ps1
git commit -m "feat(tdc): 向导多单号输入 + 功能开关 + 冒烟扩展"
```

---

## 自检（Self-Review）

- **Spec 覆盖**：反馈 1 → Task 1–3；反馈 2 文案 → Task 4；反馈 2 能力（D）→ Task 5–11；顾问要求的「存量不升级 / 全命中才可启用 / 完整性优先 / 与关注清单互斥 / 功能开关」→ Task 7（golden）、8（互斥+聚合）、9（全命中）、10（完整性）、11（开关）。
- **顾问两条条件项已闭合**：空值不触发 400（Task 1 Step 3 用例钉住）；存量签名/摘要不变（Task 7 golden）。故顾问建议的「运行期未知键 fail-closed 前置补丁」不需要新增（既有 `assert_sync_ready` 已实现），第 2 批可直接排期。
- **第二轮（codex-readonly / gpt-6-astra / high）排查的三项修正已并入**：
  1. 相邻未防护路径：`/api/tdc/data-model/crawl-all` 在官方模式下也不读单号（语义上是「全量抓取」，故不拒绝，改为用例显式钉住）→ Task 1 Step 5。
  2. 聚合证据可达性：`aggregate_fingerprint` 只哈希行身份，多单号场景会因上游行集变化导致「两次指纹一致」永不可达 → 多单号改用**配置单号成员身份**做证据基线 → Task 9 Step 4–5。
  3. 回退语义与自愈：开关关闭时已有多单号绑定「停跑不停用」；失败不清 `enabled`、调度器每 tick 重试（默认 900 s）→ Task 10 Step 5、Task 11 Step 4。
- **第二轮提出的另两项已用证据消解**：签名编码包含键名（`{"source_type","rule"}` + sort_keys），且 `normalize_single_serial` 禁止单号内含分隔符 ⇒ 空格连接无歧义、不跨键撞车（Task 7 用例仍需保留 round-trip 断言）。
- **类型一致性**：`normalize_serial_set`（Task 5）在 Task 8/10 复用；`serialSourceConflict` / `SERIAL_REQUIRES_LIST_NOTICE`（Task 2）在 Task 3 复用同名同签名；`documentNos` 一律 list[str]，`document_nos` 一律 discovery 过滤名；`fingerprint_identities` 只在多单号路径传值。
- **回滚**：第 1 批纯交互/文案，可直接 revert；第 2 批靠 `VSE_TDC_MULTI_SERIAL_SYNC` 关闭能力，且存量绑定不改写，回滚后含 `documentNos` 的绑定会被 `assert_sync_ready` 判为 not ready（停跑而非算错）。

## 执行交接

计划已保存到 `docs/PLAN_20261021_TDC_QUERYMODE_MULTISERIAL.md`。两种执行方式：
1. **Subagent-Driven（推荐）**：每个 Task 派一个全新 subagent，我在任务之间复核。
2. **Inline Execution**：在本会话按 executing-plans 分批执行并设检查点。
