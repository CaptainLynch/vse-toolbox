# 生产测试第二轮：两个问题仍未解决的根因分析与修改方案

对象：`23e1fcf feat: complete deliverable snapshot sync, TDC pagination repair, and audit closure`
（ZCode + Gemini 3 Flash 一轮修改，已提交；工作区当前干净）。

结论：**上一轮的两处修复各自只走了一半**——门控/文案改了但运维前提没解决（问题 A），
诊断信息被丢导致第二轮仍在猜（问题 B）。两个问题都不是"同一处代码没改对"，而是
**缺少决定性证据 + 缺少把证据暴露出来的那一步**。

---

## 一、截图判读（4 张）

| 图 | 页面 | 关键内容 |
| --- | --- | --- |
| a | D6 PAA 详情页 | 「数据同步（外部快照）」卡已渲染；`任务状态 未启用（支持直接立即同步）`；**同步失败：archive job configuration is not ready** |
| b | D7 NCR 进度 | 同上 |
| c | D8 NCR 明细 | 同上 |
| d | D5 数模向导 | 车型已填、**责任部门留空**（显示占位符）；**配置启用失败：mapping discovery query incomplete; narrow the filters or retry (HTTP 422)** |

上一轮**已生效**的部分（应确认保留）：
- 假成功已根除：卡片现在显示「同步失败：…」而不是"成功" ✅
- TDC 部门命名空间已修好：不再出现「映射发现未匹配（未找到）」✅
- 快照同步卡、任务状态、`archiveJobKey` 后端下发均已上线 ✅

---

## 二、问题 A：D6/D7/D8「立即同步快照」仍失败（**已本地复现，根因确定**）

### 复现（`.runtime/repro2_archive_ready.py` → `.runtime/repro2_out.txt`，临时库）

```
STEP 1  停用 + 未绑定凭据
  → outcome=not_ready, errorType=job_not_ready,
    errorMessage="archive job configuration is not ready"     ← 与截图完全一致

绑定 credential_ref='domain'（任务保持停用）
  → credentialConfigured=True, credentialAvailable=True
STEP 2  再次 sync_now（仍停用）
  → 通过门控，进入执行：outcome=needs_attention,
    errorType=credential_unavailable,
    errorMessage="credential reference is unavailable"        ← 证明 A-1 的停用放行是有效的
```

### 根因链

1. **A-1（停用放行）本身实现正确**：`scheduled_archive_runner.run_once` 改为
   `enabled_only = trigger_type == "scheduled"`；`db_manager.acquire_archive_job_lease`
   改为 `if trigger_type != "sync_now" and not job["enabled"]`。两部分都生效 ✅
2. **真正的阻塞是"任务未配置"**：`core/db_manager.py:4508-4511`
   ```python
   if validate_runtime_prerequisites and not str(job["credential_ref"] or "").strip():
       raise ArchiveJobNotReadyError("archive job credential reference is not configured")
   ```
   `run_once` 对 `sync_now` 传 `validate_runtime_prerequisites=True`，而新库 6 个内置任务
   `credential_ref` 全为 NULL → 必然 `job_not_ready`。
3. **错误信息在两层被抹平，用户无从下手**：
   - `db_manager` 抛的是具体原因（"credential reference is not configured"），
     但 `scheduled_archive_runner._safe_exception_message` 把 `error_type="job_not_ready"`
     统一映射为 `"archive job configuration is not ready"`（`:109`），
     **具体原因（缺凭据 / 停用 / filters 非法 / 契约不符）全部丢失**。
   - 前端只把该英文串原样展示，没有给出"缺什么、去哪里配"的指引。
4. **卡片文案误导**：`app.js:2895` 显示「未启用（支持直接立即同步）」，让用户以为
   不需要任何配置即可同步；实际仍需**绑定统一域账号凭据**（可用「保持停用」状态绑定）。

### 修改方案（问题 A）

- **A-1 后端：不再丢失原因**（`services/scheduled_archive_runner.py`）
  把 `job_not_ready` 细分为白名单枚举（不外泄异常原文）：
  `credential_not_configured` / `job_disabled` / `contract_mismatch` / `filters_invalid` /
  `retry_policy_invalid`，并在 `ArchiveJobRunResult` payload 追加 `remedy` 字段
  （如 `"bind_domain_credential"`），供前端直接映射指引文案。
- **A-2 后端：关联信息补齐**（`web/app.py:_deliverable_associations`）
  现在只下发 `enabled/lastSuccessAt`；`_job_payload` 里已有的
  `credentialConfigured` / `credentialAvailable` 也应随 associations 下发，
  让卡片能显示真实就绪状态。（同时顺手把 `:1785-1792` 的自研反查改用
  `find_job_key_by_deliverable_id`，消除重复实现。）
- **A-3 前端：状态与指引说人话**（`web/static/app.js` 快照卡）
  - 「任务状态」改为三态：`已启用` / `未启用（凭据已就绪，可直接同步）` /
    `未配置（缺统一域账号凭据，需先绑定）`；
  - 点击失败时按 `errorType/remedy` 映射：
    - 缺凭据 → 「该同步任务尚未绑定统一域账号。请到『自动归档』选择任务 → 登录信息选
      「统一域账号（domain）」→ 保存（可保持停用），再回来点【立即同步快照】。」
    - `credential_unavailable` → 「凭据保护库中没有可用的统一域账号：请到系统设置登录并勾选
      「保存至凭据保护库」。」
  - 增加【去配置该同步任务】按钮，跳 `#scheduled-archive` 并预选该任务
    （`selectedArchiveJobKey = jobKey`，归档页已支持）。
- **A-4 立即可用的运维操作（无需改码）**：对 `aras_paa` / `aras_ncr_progress` /
  `aras_ncr_detail` 三个任务，在「自动归档」里各绑定一次统一域账号并保存（保持停用），
  同时确认系统设置里已把统一域账号保存进凭据保护库。绑定后 `sync_now` 即可真正执行。

---

## 三、问题 B：D5 数模仍报 HTTP 422 incomplete（**根因未定，因为证据被丢弃**）

### 现状

`web/app.py:1243-1252`：
```python
stop_reason = str(getattr(result, "stop_reason", "unknown") or "unknown")
if getattr(result, "complete", None) is not True or stop_reason not in COMPLETE_RESULT_STOP_REASONS:
    raise error_type(
        "mapping discovery query was incomplete; narrow the filters or retry",
        "IncompleteDiscovery", 422,
    )
```
**`stop_reason` / `unique_count` / `duplicate_count` / `total` / `pages` / `fetched_pages`
全部被丢弃**，只回一句"不完整"。

而这些信息**在爬虫里已经产生**：`services/tdc_crawler.py:816-836` 每页都会 emit
`TDCHttpDiagnosticEvent(stage="pagination", stop_reason=…, duplicate_count=…, total=…, pages=…)`，
但它只进**诊断记录器**（需先 `/api/diagnostics/start` 或开诊断浮窗），
错误响应里没有 —— 所以两轮修改都只能靠猜，这就是问题 B 迟迟不闭环的原因。

### 两个首要嫌疑（决定 `stop_reason`，必须由证据二选一）

**嫌疑 1：`duplicate_records`（身份仍不够细）**
`tdc_crawler.py` 的分支顺序是
`page_mismatch → size_mismatch → metadata_inconsistent → duplicates → 结束条件`，
即**任意一页出现一行"身份碰撞"就整体判不完整**。
上一轮把 `_row_identity` 细化（`detailId/partId/subId/rowId/recordId/id`，
并排除与 workflow 原始 ID 相同的值，再加行号与 quantity/version/status 等特征），
方向正确，但**如果 TDC 列表接口根本不返回任何逐行唯一键**，
同一流程内真正重复出现的同名零件行仍会碰撞。
⚠️ 证据缺口：`detailId/partId/subId/rowId/recordId/rowNo/...` 这些键名**全仓库只出现在爬虫新代码里**，
没有任何真实响应字段清单佐证它们存在（我上一轮已列为 Major，至今未闭环）。

**嫌疑 2：`inconsistent_metadata`（实时报表 total 漂移）**
`tdc_crawler.py:714-718`：
```python
if (reported_total is not None and result.total != reported_total) or result.total < accumulated_count:
    metadata_inconsistent = True
```
**total 只要求完全相等**。数模报表是活数据：17~22 页、约 850~1100 行的抓取要跑几十秒，
期间只要有**一条**新数模记录被创建，`total` 就会 +1 → 整个抓取被判不完整。
这能很好解释：单页预览永远正常（`page=1/17`/`1/22`），全量抓取必失败。

**放大因素（截图已显示）**：用户把**责任部门留空了**（图中是占位符），
于是走的是最宽口径（车型-only ≈ 22 页 ≈ 1100 行），
比 `部门=车体工程`（17 页）**更容易**撞上碰撞或 total 漂移。

其余可能：`inconsistent_page` / `inconsistent_page_size`（服务端不按 `size` 返回）、
`max_pages`（22 < 100，基本排除）、`max_records`（1100 < 5000，排除）。

### 修改方案（问题 B）

**P0 —— 先让证据可见（小改动、立刻可定案）**
1. `web/app.py:_require_complete_mapping_result`：把完整性事实放进 422 响应，
   例如 `error.diagnostic = {"stopReason","uniqueCount","duplicateCount","total","pages","fetchedPages"}`
   （均为有界、非敏感的元数据，本就在 `TDCHttpDiagnosticEvent` 白名单内）。
2. 向导错误文案同步展示这些字段（`app.js` 已具备拼接「命中行数/字段数」的先例）。
3. 复现指引：先 `POST /api/diagnostics/start`（或开页面右下角诊断浮窗）→ 再点一次
   【开始配置并启用】→ 导出 `GET /api/diagnostics/bundles/<identity>` 的 zip，
   取 `stage=pagination` 的最后一页事件。

**P1 —— 按 `stop_reason` 分派修复（决策表）**

| stop_reason | 修复 |
| --- | --- |
| `duplicate_records` | 改完整性契约：**重复不再致命**，降级为诊断元数据；完成条件改为 `page >= reported_pages` 且 `len(unique) >= reported_total`（页元数据/页码/页大小不一致仍保持致命失败）。因为"身份过粗"会导致 `len(unique) < total`，仍会被拒绝，fail-closed 语义不丢。同时用真实字段清单补一个夹具测试。 |
| `inconsistent_metadata` | 容忍 **total 增长**：`result.total > reported_total` → 提升 `reported_total` 并继续；仅当 total 缩小/低于已累计数或 pages 倒退才判不完整。补"抓取中途 total +3"的测试。 |
| `inconsistent_page` / `inconsistent_page_size` | 放弃对请求 `size` 的强校验，改用服务端回传的 `size/pages` 继续分页；只在页号错乱时失败。 |
| `max_pages` / `max_records` | 提高上限；并把"部门默认 `车体工程`"作为首跑口径（17 页 < 22 页）。 |
| `empty_page` / `short_page` / `reported_*` | 已属完成态，无需处理。 |

**P1 —— 向导侧对称降级**（`web/static/app.js`）
当前自动降级只会"**放宽**"（`not_found` 时去掉部门重试）。本次报错恰恰相反：
部门留空导致**过宽**而不完整。应补一条对称策略：
`IncompleteDiscovery(422)` 且当前无部门筛选时，自动**收窄**为
`部门=车体工程` 重试一次（并提示"数据量过大，已按车体工程部门收窄重试"），
仍失败再硬停。这与后端文案 "narrow the filters or retry" 语义一致。

**P1 —— 补测试**：17 页含合法重复行必须 complete；抓取中途 total 增长必须 complete；
身份过粗导致 unique < total 必须仍判不完整。

---

## 四、需要你提供的输入（决定性，按优先级）

1. **P0-a（一条命令即可定案）**：按第三节 P0 指引，先开诊断记录，再复现一次 D5 报错，
   然后回传 `stage=pagination` 最后一条事件里的
   `stopReason / duplicate_count / unique_count / total / pages`。
   —— 没有这个，问题 B 只能继续猜。
2. **P0-b（10 秒可验证的旁证）**：把 D5 向导的**责任部门填成 `车体工程`**（不要留空）再跑一次。
   - 若**成功** → 强烈指向 total 漂移/碰撞随规模放大，按"收窄口径 + 容错"修；
   - 若**仍 422** → 说明与规模无关，优先查 `inconsistent_page_size`（服务端分页契约）。
3. **P0-c**：用「系统查询 → TDC 数模」做一次**全量抓取**（不是单页预览），看是否同样报 incomplete
   —— 用于隔离"交付物向导链路"与"爬虫本身"。
4. **P1**：真实 data_model 列表接口**一页的字段名清单**（脱敏），用于确认是否存在逐行唯一键。
5. **P1**：问题 A 的运维状态 —— `GET /api/scheduled-archive/jobs` 中
   `aras_paa`/`aras_ncr_progress`/`aras_ncr_detail` 的
   `enabled / credentialConfigured / credentialAvailable`；以及系统设置里统一域账号是否已保存。

---

## 五、验收标准

- 问题 A：三个任务绑定统一域账号后，点【立即同步快照】→ 卡片显示真实结果
  （成功即刷新明细；失败必须给出**具体缺什么 + 去哪里配**的中文指引，不再出现
  "archive job configuration is not ready" 这种无指向文案）。
- 问题 B：D5 一键启用成功并完成首次同步；且**任意规模**的 data_model 全量抓取在
  合法重复/实时 total 漂移下都能判定为完整，而"身份过粗导致丢记录"仍被判不完整。
- 门禁：全量 `pytest`、`flake8 -j 1`、`node --check`、`generate_project_map.py --check` 全绿。

---

## 六、开工前输入清单（按"是否阻塞"分类）

### ✅ 不需要你提供任何信息即可先做（不改语义、不依赖外部证据）
| 阶段 | 内容 |
| --- | --- |
| P0 | `_json_error` 扩展 `diagnostic` 唯一出口；422 下发完整性事实；向导展示 |
| P1-A | `job_not_ready` 闭集枚举化 + `remedy`；associations 补 `credentialConfigured`；前端三态与中文指引 |
| P2 | 抽 `evaluate_pagination_integrity` 共享纯函数（行为等价重构 + 等价性测试） |

### 🔴 阻塞项 1：D5 全量抓取的 `stop_reason`（**一次点击即可，无需开诊断**）
已核实这条路径会直接返回所需事实，且与 discovery 用**同一爬虫、同一 page_size=50、同一 max_pages=100**：
1. 「系统查询 → TDC 数模设计审核流程报表」→ 筛选与失败时**完全相同**（车型 `F610S`、**部门留空**）→ 每页条 `50` → 点**全量抓取**；
2. 任务完成后，从任务中心／浏览器 DevTools 的 `GET /api/tasks/<task_id>/result` 取结果 JSON
   （该 JSON 由 `_tdc_result_data()` 生成，`web/app.py:1456-1478` + `:2767`）；
3. 回传这 6 个字段：`stop_reason`、`unique_count`、`duplicate_count`、`total`、`pages`、`fetched_pages`。

**备选（若要抓交付物向导那条链路的现场）**：页面右下角诊断浮窗 → 开始记录 → 复现向导报错 → 导出诊断包；
或 `POST /api/diagnostics/start` → 复现 → `GET /api/diagnostics` 取 identity → `GET /api/diagnostics/bundles/<identity>`，
回传最后一条 `stage=pagination` 事件的同 6 个字段（`services/tdc_crawler.py:816-836`）。

### 🔴 阻塞项 2：三个决策
1. 是否接受 **completeness 语义放宽**（重复不再致命 → `unique ≥ total` 且页簿记一致）？
2. 向导"过宽时自动收窄为部门=车体工程"是否允许**静默**改口径，还是必须弹确认／仅提示？
3. mapping discovery 是否**本轮异步化**（复用 `CrawlTaskRunner`），还是单独立项？
4. （附带）是否允许在 `sync-now` 响应中新增**闭集** `error_type`/`remedy` 字段（公开契约的加法变更）？

### 🟡 不阻塞代码、但决定验收能否通过：问题 A 的运维状态
- 系统设置：统一域账号是否已勾选「保存至凭据保护库」；
- `GET /api/scheduled-archive/jobs`：`aras_paa` / `aras_ncr_progress` / `aras_ncr_detail` 的
  `enabled` / `credentialConfigured` / `credentialAvailable`；
- 说明：截图里的 `job_not_ready` **已经证明 `credential_ref` 为空**
  （若只是凭据库不可用会显示 `credential_unavailable`），所以 A 组代码改动**不需要**等这份数据；
  但"点一下就真的同步成功"的验收，必须先在自动管理页给这三个任务绑定统一域账号（可保持停用）。

### ⚪ 可选加速项（不做也能推进）
- 真实 data_model 列表接口一页的字段名清单 —— **若采纳 P3 就不再需要**：
  A2 的整个目的就是让爬虫不再依赖业务字段猜身份，从而永久消除"要字段清单"这件事。

### 🚫 明确不需要提供
数据库文件、Cookie／口令／Token、更多截图、TDC/Aras 账号信息、以及任何手工行数比对
（`unique_count` / `duplicate_count` 爬虫已自行统计）。

---

## 八、实施记录：P0 + P1-A + P2 已完成（2026-09-22）

按架构评估第六节的顺序，先落地**不依赖用户输入**的三块；P3/P4 未动。

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P2 | 新增 `services/pagination_integrity.py`（`stop_reason` 词表 + `is_complete()` + `PageBookkeeping` + `decide_page_outcome()`），TDC/Aras 双爬虫接入，`project_status_records` 降为别名再导出 | ✅ 行为等价（既有爬虫测试全绿） |
| P0 | `_json_error` 支持 `diagnostic` 成为唯一出口；422 下发 `stopReason/rowCount/uniqueCount/duplicateCount/declaredTotal/declaredPages/fetchedPages`；向导渲染为可读尾注 | ✅ |
| P1-A1 | `ArchiveJobNotReadyError.reason` 闭集化（6 值）+ `remedy_for()/remedy_for_error_type()` 映射 + `ArchiveJobRunResult.remedy` + 全部产出路径填充 | ✅ |
| P1-A2 | associations 增补 `credentialConfigured`（无 vault I/O） | ✅ |
| P1-A3 | 快照卡任务状态三态 + 常驻指引 + 【去配置该同步任务】（预选任务并跳转）+ 失败按闭集 remedy 给中文指引 | ✅ |
| P3 | completeness 语义放宽（重复降级为指标、容忍 total 增长） | ⏸ 等 stop_reason 证据与你的决策 |
| P4 | 向导对称收窄降级 | ⏸ 等产品口径决策 |

**门禁（本轮实测）**：全量 `pytest` **2346 passed, 3 skipped（EXIT 0，+29 新用例）**；
`flake8 -j 1` 零告警；`node --check` 通过；`generate_project_map.py --check` verified；
`git diff --check` EXIT 0。

**仍然存在的行为**（必须说清，避免误判已修好）：
- 问题 A：代码侧已能给出一句话的「去哪里配什么」；但**生产上仍未绑定统一域账号**，
  所以点击仍会失败（只是失败原因现在说得清）。
- 问题 B：**语义层未修复**，D5 仍可能 422；区别是现在**一次复现就能拿到 `stopReason`**，
  从而决定 P3 的分支。

---

## 九、证据文件（本地只读）

- `.runtime/repro2_archive_ready.py` → `.runtime/repro2_out.txt`（问题 A 复现）
- `.runtime/repro_snapshot_sync.py` → `.runtime/repro_out.txt`（上一轮假成功复现）
- `.runtime/shots3/{a,b,c,d}.png` + `.runtime/ocr.ps1`（本轮截图与 OCR）
