# 代码审计：ZCode 交付物同步修复（2026-09-22）

审计对象：工作区未提交改动（HEAD `ce0523c` + 22 文件改动 / +1015 −122），
即「PAA/NCR 快照同步 + TDC 数模/SOR 部门解耦与爬虫全量翻页修复」。

审计方式：逐行阅读改动与调用链 + 独立重跑门禁 + 独立复现脚本。**只读审计，未修改任何业务代码。**

---

## 一、结论

**有条件通过。** 修复方向正确、契约分层合理、测试全绿，但存在：

- **1 个 Blocker**：问题 1 的「立即同步快照」在默认（未启用归档任务）状态下**假成功**，
  且不满足用户选定的形态 A（不要求先启用定时任务）。
- **1 个 Major**：问题 2 的爬虫行身份修复依赖**未经证实**的上游字段（`id`/`recordId`/`rowNo` 等），
  若真实响应不含这些字段则修复为空转、生产 422 仍会复现。
- **5 个 Minor**（重复反查实现、静默取值替换、单记录模式无降级、卡片未透出启用状态、测试为字符串断言）。

---

## 二、门禁（本审计独立重跑，全部通过）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 聚焦测试 | `pytest tests/test_tdc_crawler.py tests/test_deliverable_sync_wizard_enhanced.py tests/test_project_status_{contracts,discovery,updates,scheduler,scheduler_api,api}.py tests/test_deliverable_registry.py tests/test_overview_web.py tests/test_db_manager.py -q` | **287 passed in 24.36s** |
| 向导/汇总/连接器 | `pytest tests/test_deliverable_sync_summary_ui.py tests/test_deliverable_form_ui.py tests/test_project_status_sync_runner.py tests/test_project_status_connectors.py -q` | **85 passed in 9.89s** |
| 全量回归 | `pytest -q -p no:cacheprovider` | **2317 passed, 3 skipped in 257.39s，EXIT 0**（上轮基线 2297，+20 用例） |
| Lint | `flake8 -j 1`（全部改动 Python 文件） | 零告警 |
| 前端语法 | `node --check web/static/*.js` | 全部通过 |
| 项目地图 | `python tools/generate_project_map.py --check` | verified |
| 空白检查 | `git diff --check` | EXIT 0 |

证据：`.runtime/audit_gates.log`、`.runtime/audit_full_pytest.log`。

---

## 三、通过项（已逐条核对代码，非仅看测试）

1. **问题 2 主因（TDC 部门命名空间）已真正修复，且双路径覆盖**
   - `web/static/app.js:1575-1582` 新增 `normalizeTdcDepartment`：`技术中心_车体工程` / `技术中心-车体工程`
     → `车体工程`；空值/`null`/`undefined` 原样返回 `""`（**留空即全量**，与提示文案一致，已核对 `:1576` 的 falsy 分支）。
   - 向导默认值按来源区分：`:1872-1873` `isTdc ? "车体工程" : "技术中心_车体工程"`（采纳我建议的 C 方案）。
   - 向导侧 `:259`（原 `:2059` 区域）`deptVal = isTdc ? normalizeTdcDepartment(rawDeptVal) : rawDeptVal`。
   - **「高级设置」路径同样覆盖**：`:2548-2553` 对 TDC match 键 `department`/`superDepartment` 归一化，
     而 `:2704-2715` 的取证 `filters` 正是从同一 `payload.matchRule` 派生 → 两条路径口径一致。✅
2. **聚合取证降级重试的签名链正确**（`:2085-2102`）
   - `not_found && aggregate && isTdc && deptVal` → 去掉部门重试；成功时**同时删除** `filters` 与 `matchRule` 的部门键，
     保证「持久化的绑定」与「已记录证据的 config_signature」一致（否则保存必 409）；`config_signature` 随规则变化，
     步骤②用同一份无部门 `payload` 再次取证，`confirmed` 可达 2 → 可保存。逻辑自洽 ✅
   - `payload.filters` 与 `filters` 是同一对象引用，删除生效（隐式别名，读起来脆弱但行为正确）。
   - 诊断信息已补：`命中行数：${cCount}，字段数：${fCount}` ✅
3. **问题 1 后端契约**：`find_job_key_by_deliverable_id` 纯函数（`core/project_status_contracts.py:94-104`）
   由 `DELIVERABLE_LINK_REGISTRY` 派生；`web/app.py:2117` 在 `sourceInfo` 下发 `archiveJobKey`；
   `tests/test_project_status_api.py:465-472` 对 D1-D8 全量断言 ✅；注册表闭合测试同步增强 ✅。
4. **问题 1 前端卡片**：`renderSnapshotSyncCard`（`:2865-2957`）
   - 仅对 `item.formSnapshotDriven === true` 渲染（`:3000-3003` 分支）→ D1/D4 不受影响 ✅
   - **Safe DOM**：全部 `overviewEl`/`textContent`，零 `innerHTML` ✅
   - 回退来源 `capabilities.archiveJobKey` → `associations[].jobKey`，而 `web/app.py:1806/1813` 确实下发
     `jobKey` 与 `lastSuccessAt` → 回退非死代码 ✅
   - 同步后自动刷新：`options.onFormReload` 在详情页已接线（`:7646-7650`），`loadArchiveJobs(keepSelection)` 签名匹配 ✅
   - **误导性死按钮已解决**：`if (syncSupported) { syncActionBar.appendChild(syncBtn); }`（`:3727-3729`）
     → 非 syncCapable 交付物不再渲染永久 disabled 的「运行后台同步」✅（记忆档该项声明成立）
5. **爬虫行身份改动的失效方向是 fail-closed**：`services/tdc_crawler.py:702-712` 中重复即
   `stop_reason="duplicate_records"`（`:778-783`）→ 结果被判 incomplete → 取证/同步拒绝。
   即身份**过粗只会报错、不会静默丢数据**，不构成数据完整性风险 ✅
6. 其余随本批带入的既有修复（`project_status_update_bindings` 表名、`source_type` 约束、`interval_minutes`、
   `trigger_type="sync_now"`、`register_global` 开关、`isinstance(interval, bool)` 兜底、record_set 映射收敛）
   均与上一轮结论一致、无回退 ✅

---

## 四、BLOCKER：默认状态下「立即同步快照」假成功，且不满足形态 A

### 证据链（已独立复现）

1. `services/scheduled_archive_runner.py:533`：`jobs = self._db.list_archive_jobs(enabled_only=True)`；
   `:534-548` 当 `job_key` 不在**已启用**集合内时，直接返回
   `outcome="not_ready"`、`error_type="missing_job"`、`error_message="enabled archive job was not found"`。
2. `services/scheduled_archive_admin.py:350-357` `sync_now` 原样包装该结果（不抛异常）。
3. `web/app.py:4081-4084`：`jsonify({"ok": True, "data": data})` → **HTTP 200 + `ok: true`**。
4. `web/static/app.js:2933`：`if (!resp.ok || !body || body.ok !== true) throw` → 不抛；
   `:2937/:2944` 于是输出「快照同步完成…」「**快照同步成功，已刷新最新明细与图表。**」

### 复现（`.runtime/repro_snapshot_sync.py` → `.runtime/repro_out.txt`，临时库，无副作用）

```
== seeded archive jobs on a FRESH database ==
  job_key=aras_paa enabled=False credential_configured=False
  ...（6 个任务全部 enabled=False）
== sync_now('aras_paa') ==
  {"dryRun": false, "exitCode": 2,
   "results": [{"outcome": "not_ready", "errorType": "missing_job",
                "errorMessage": "enabled archive job was not found"}]}
== 浏览器收到 ==  http_status=200  body.ok=True
=> renderSnapshotSyncCard 判定：成功（假成功）
```

### 影响

- 新建/默认库中 6 个内置归档任务均为 `enabled=0`（`core/db_manager.py` DDL `DEFAULT 0`；
  本地库实测同为 0、`scheduled_archive_runs` 0 行）→ **D6/D7/D8 用户点击后看到"成功"，
  但交付物依旧「暂无表单快照数据」**。这比原本"没有按钮"更糟：会误导用户以为已修复。
- **不满足用户已选形态 A**（「不要求先启用定时任务」）：后端 `run_once` 的 `enabled_only` 门控仍未放开。
- 该缺陷是**通用**的：即使任务已启用，任何非成功结果（`credential_unavailable`、重试耗尽等）
  同样只被包成 `ok: true`，卡片一律报成功。
- 未被测试覆盖：新增的卡片测试只断言源码字符串包含「立即同步快照」，未覆盖结果判定。

### 修复方向（需产品决策，二选一）

- **(A-1) 满足形态 A（推荐）**：为「用户显式点击」的同步放开 enabled 门控，
  例如 `run_once(..., job_keys=...)` 增加显式 `include_disabled` 通道（**仅 `trigger_type="sync_now"` 生效**，
  调度路径始终保持 `enabled_only=True`），并补端点级测试：停用任务 + 显式 sync-now → 真正执行。
- **(A-2) 维持后端门控**：卡片改为读 `associations[0].enabled`，未启用时按钮置灰并给出
  「去自动归档启用（需先保存统一域账号凭据）」引导 —— 但这等于回退到用户已否决的形态 B。
- **无论选哪个都必须修前端结果判定**：解析 `body.data.results[0].outcome/finalState/errorMessage`，
  `not_ready`/`failed` 一律按失败展示并脱敏，禁止假成功。

---

## 五、MAJOR：爬虫行身份修复依赖未经证实的上游字段

- `services/tdc_crawler.py:1529-1585` 的 `_row_identity("data_model", …)` 现在优先使用
  `id`/`recordId`/`rowId`/`detailId`/`partId`/`subId`，其次行号 `rowNo`/`rowNum`/`rowIndex`/`lineNo`/`seq`。
- **全仓库检索**：这些键名**只出现在新增的爬虫代码里**（`grep -n "recordId|rowId|detailId|subId|rowNo|rowIndex"` 命中 5 处，全在该函数内），
  没有任何已捕获的真实响应字段清单、契约文档或夹具佐证其存在。
- `tests/test_tdc_crawler.py:881-945` 的新用例**自行构造**了逐行唯一的 `id`（`REC-1…850`），
  因此**用例通过只证明"若有 id 则正确"，不证明线上有 id**。
- 失效后果：
  - 真实响应**无** id 类/行号字段 → 修复为空转，线上 `duplicate_records` → HTTP 422 仍复现；
  - 真实 `id` 若为**流程级**（每行相同）→ 第 2 行起全被判定重复，立刻 `duplicate_records` 失败
    （fail-closed，但仍不可用）。
- 需要的证据（一次即可定案）：真实 data_model 列表接口**一页的字段名清单**（脱敏），
  或生产机上一次全量抓取的 `rows/unique/dup/stop_reason`。
- 建议增强：在 `TDCHttpDiagnosticEvent`/`safe_diagnostic` 的允许列表内记录
  「本次抓取判定身份所用的键类别」（如 `identityKey=rowId` 枚举值，非取值本身），使生产证据可自证；
  并用捕获的字段名清单补一个回归夹具。

---

## 六、MINOR

1. **反查逻辑重复实现**：新 helper 之外，`web/app.py:1785-1792` `_deliverable_associations`
   仍自行 `next(candidate_key for candidate_key, candidate in DELIVERABLE_LINK_REGISTRY.items() if candidate is entry)`。
   应按项目单一来源规则改为调用 `find_job_key_by_deliverable_id`。
2. **静默取值替换**：`normalizeTdcDepartment("技术中心")` → `"车体工程"`（`app.js:1579` 的前缀剥离兜底，
   且 `tests/test_deliverable_sync_wizard_enhanced.py:123` 明确固化了该行为）。用户只填父级部门时会被静默改写为子部门，
   建议改为保留原值或在 UI 提示。
3. **单记录模式无降级**：`app.js:2085` 的自动降级仅在 `aggregate` 生效；
   单记录（填了流程编号）时若该单据不在所选部门内，仍是硬失败（现已带命中行数/字段数，可接受，但需产品确认口径）。
4. **卡片未透出启用状态**：`renderSnapshotSyncCard` 的 facts 只有「数据来源/驱动模式/最近成功」，
   而 `associations[0].enabled` 与 `credentialAvailable` 已在前端可得；用户点击前无从判断任务是否停用
   （与 Blocker 叠加放大误导）。
5. **测试强度不均**：`normalizeTdcDepartment` 部分是真 Node VM 行为测试（好）；
   快照卡部分仅做**源码子串断言**（`:177-184`），未覆盖渲染与结果判定 —— 正是该强度缺口放过了 Blocker。
   建议补行为级 VM 测试（含"停用任务必须报失败"用例）。
6. **新增测试文件未纳入版本控制**：`tests/test_deliverable_sync_wizard_enhanced.py` 仍为 `??` 未跟踪；
   本批若提交须一并 `git add`，否则覆盖丢失。
7. **记忆档与代码的表述落差**：`memory/CURRENT_STATE.md` 记录"code-reviewer 审计 PASS（0 Blocker）"，
   但第 4 节 Blocker 属验收级阻断；建议在复盘中修正结论口径。

---

## 七、建议的验证与收口顺序

1. 先定 Blocker 的产品口径（A-1 / A-2），再改前端结果判定 —— 两者必须同时落地。
2. 补三类测试：停用任务 sync-now 契约（端点级）、快照卡结果判定（VM 行为级）、
   爬虫身份（用真实字段清单夹具）。
3. 拿生产证据确认 Major：真实 data_model 响应字段名 / 一次全量抓取的 rows-unique-dup-stop_reason。
4. 复跑：全量 `pytest`、`flake8 -j 1`、`node --check`、`generate_project_map.py --check`。
5. 生产复测：D5 一键启用并首次同步成功（已可预期通过）；D6/D7/D8 点【立即同步快照】后
   **交付物真的出现表单快照数据**（当前不满足）。

---

## 八、审计证据文件（本地只读）

- `.runtime/audit_gates.log`、`.runtime/audit_pytest_focused.log`、`.runtime/audit_full_pytest.log`
- `.runtime/repro_snapshot_sync.py` → `.runtime/repro_out.txt`（Blocker 复现）
- `.runtime/appjs.diff`、`.runtime/inspect_db.py`、`.runtime/dumpr_rows.py`
