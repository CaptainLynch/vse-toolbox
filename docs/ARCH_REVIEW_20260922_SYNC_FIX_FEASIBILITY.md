# 架构可行性评估：交付物同步两问题的修改方案

评估对象：`docs/PROD_TEST_20260922_ROUND2_REMAINING_ISSUES.md` 提出的方案（问题 A 根因修复 + 问题 B 诊断先行/按 stop_reason 分派）。
方式：沿调用链核实模块边界、契约拥有者与共享消费者。**只读评估，未改动代码。**

---

## 一、总体结论

**方案整体可行，但当前形态不宜直接开工**：方案里有 3 项会跨模块改语义，
而现有架构对这 3 处**没有单一拥有者**（契约重复实现、身份语义有两套、诊断契约有手搓分支）。
若照现状逐条打补丁，第三次返工几乎必然。正确顺序是：**先收敛契约归属，再改语义，最后加表现层。**

一个决定性发现：**同一问题在本仓库已有正确先例，TDC 侧背离了它。**

`services/aras_crawler.py:417-450`（EWO）按 **Item ID** 去重，并留有明确注释：

> `# Use Item IDs, not business numbers: different items may have the same business number and still be legitimate records.`

且对无 ID 的历史响应走内容哈希 + `unidentified_content` fail-closed。
而 `services/tdc_crawler.py:1529-1588` 的 `_row_identity` **正是从业务/内容字段反推身份**
（`incident/documentNo/formId` + `partNumber/modelNumber/partName`，再加**零证据**的
`detailId/partId/subId/rowId/recordId/rowNo`）。Aras 侧明确禁止的做法，TDC 侧成了主路径——
这就是两轮修改都不闭环的结构性原因。

---

## 二、需要先决定的三个架构问题

### A1. `complete/stop_reason` 契约**没有单一拥有者**（生产者两个，语义判断散落）

| 角色 | 位置 |
| --- | --- |
| 生产者 1（TDC） | `services/tdc_crawler.py:674-855`（元数据驱动：pages/total/size/duplicates） |
| 生产者 2（Aras） | `services/aras_crawler.py:388-475`（页循环 + 显式 `complete` 标志 + Item-ID 去重） |
| 共享词表 | `services/project_status_records.py:36 COMPLETE_RESULT_STOP_REASONS`（唯一） |
| 消费者 | `services/project_status_connectors.py:65/253/361`、`web/app.py:1232/4606/4619`、`services/scheduled_archive_connectors.py:451/477`（**按 `== "max_records"` 特判**）、`services/ewo_enrichment.py:39`、`tdc_probe_cli.py:274/346`、`main.py:737/823`、`core/diagnostics.py:146`、`web/app.py:1476/1697`（预览接口已下发 `stop_reason`） |

结论：词表统一，但**判定逻辑在两处各自实现**。
→ 修 completeness 语义必须**同时**改 TDC 与 Aras，并同步两套测试
（`tests/test_tdc_crawler.py:195-217`、`tests/test_crawler_pagination_integrity.py:137` 都显式断言
`duplicate_records → complete=False`）。
**架构动作（P1，前置）**：抽出 `evaluate_pagination_integrity(page_meta, counts) -> (stop_reason, complete)`
纯函数（放 `services/` 共享层，不依赖 IO），两个爬虫都改为调用它，用等价性测试锁定行为后再改语义。

### A2. 行身份有**两套语义**，且爬虫那套在猜字段名

- 爬虫级（分页去重）：`services/tdc_crawler.py:_row_identity` —— 影响 `unique/duplicate/complete`。
- 同步级（业务身份）：`services/project_status_records.record_identity` + `IDENTITY_FIELDS`
  —— 影响聚合指纹、映射发现、落库归属。

两者**目的不同**（前者是簿记，后者是业务），但当前"簿记"依赖"业务字段唯一性"，
于是每次线上数据一变就要新增猜测字段名。这是本问题的**根因架构缺陷**，不是缺字段清单。

**架构正解**：分页完整性只由**簿记性质**决定（页号连续、size 一致、total/pages 单调一致、
unique ≥ total），`duplicate` 降级为**诊断指标**；业务身份**只**留在 `project_status_records` 层。
这样上一轮我列的 Major（身份键零证据）**自然消失**，不必再补字段清单。

### A3. 诊断/错误契约有手搓分支，且 `_json_error` 不承载诊断

- `web/app.py:376-391 _json_error(status, type, message, diagnostic_path, code=…)` —— 无 `diagnostic` 映射。
- `web/app.py:2608-2609` 为 Aras 错误**手搓**了 `{"message": …, "diagnostic": exc.safe_diagnostic()}`。
- 但 `web/app.py:1476/1697` 的**预览接口早已把 `stop_reason` 下发给前端**。

→ 问题 B 的 P0（把 `stopReason/duplicateCount/total/pages` 放进 422）**不是新概念**，
而是把预览接口已有的契约补齐到错误通道。
**架构动作（P0）**：扩展 `_json_error(..., diagnostic: Mapping | None)` 为唯一出口，
顺手把 `:2608` 手搓分支收敛进来；`core/diagnostic_recording._TEXT_FIELDS` 已含 `stop_reason`，
白名单校验无需扩张（`type/format` 只用有界数值与闭集枚举）。

---

## 三、逐项可行性

| # | 方案项 | 可行性 | 架构边界与代价 |
| --- | --- | --- | --- |
| A-1 | `job_not_ready` 细分 + payload 增 `remedy` | ✅ 可行（additive） | **约束**：`core/db_manager.py:4493-4519` 的 `ArchiveJobNotReadyError` 必须携带**闭集机器码**；`services/scheduled_archive_runner.py:_error_type/_safe_exception_message` 改为"码→(error_type, remedy)"映射，**绝不反射异常原文**（这是既有红线）。`ArchiveJobRunResult` 加字段是 additive，但 `tests/test_scheduled_archive_cli.py:191-200` 的文本行断言需同步。 |
| A-2 | associations 增补 `credentialConfigured` | ✅ 可行且**零新耦合** | `core/db_manager.list_archive_jobs` 已返回 `credential_configured`（`:4341`），而 `web/app.py:1945-1948` 手里的 `archive_jobs_by_key` 就是这些 raw row。**建议不要**在此处补 `credentialAvailable`：那是 `ScheduledArchiveAdminService._job_payload` 用凭据提供者做的 **DPAPI 探测**，放进 `/api/project-status` 会变成"每请求 × 6 任务的 vault I/O"，且要给 `_project_status_payload(db, …)` 注入凭据提供者，污染 adapter 边界。可用性留给点击时的 `sync-now` 结果（已能区分 `credential_unavailable`）。 |
| A-3 | 前端三态 + 中文指引 + 跳转预选 | ✅ 可行（纯前端） | 文案必须与后端**枚举同源**，不要在 JS 里再写一份英文串→文案映射（否则就是第三处契约副本）。【去配置该同步任务】跳 `#scheduled-archive` 并置 `selectedArchiveJobKey` 是既有能力，无需新路由。 |
| B-P0 | 422 携带 `stopReason` 等完整性事实 | ✅ 可行、低风险 | 见 A3：补齐既有契约，不动语义。 |
| B-P1a | `duplicate_records` 降级为指标 | ⚠️ **需要架构决策**（本方案唯一的高风险项） | 安全含义：把"重复即失败"换成"`page ≥ reported_pages` 且 `len(unique) ≥ reported_total` 且页簿记一致"。**保留了**"身份过粗→`unique < total`→仍失败"的 fail-closed 语义（不静默丢数据）。残余缝：服务端 `total` 本身偏小会漏判——但这条与今天**已被接受**的 `reported_pages` 路径同标准，非新增漏洞。影响面：TDC + Aras 两个生产者 + 两套测试 + `DECISIONS.md` 记录安全意图变更。 |
| B-P1b | 容忍 `total` 增长 | ⚠️ 需与 a 同批 | 区分"增长"（活报表新增行，可接受）与"页码/pages 倒退"（继续失败）。Aras 侧无 total 驱动路径，改动集中在 TDC，但**判定函数若已抽出则一处生效**。 |
| B-P1c | 向导"过宽时自动收窄为部门=车体工程"重试 | ⚠️ 可行但有**产品语义代价** | ① 改变 `matchRule` → 改变 `services/project_status_records.compute_config_signature` → 必须像"放宽"路径那样**同时**改写 `filters` 与 `matchRule` 再持久化，否则证据签名与绑定不一致 → 保存 409；② 用户本意"不限部门"会被**静默**改成"仅车体工程"，聚合口径变化。建议：只作一次性降级 + UI 明示，或改为**弹确认**。 |
| B-P1d | 严格化的 `inconsistent_page_size` 回退 | ✅ 低风险 | 改为采用服务端回传的 `size/pages` 继续分页；只在页号错乱时失败。 |
| B-可选 | mapping discovery 异步化 | ✅ 架构已支持 | `services/crawl_task_runner.py` 是**通用 task_type 注册器**（`register_handler` / `submit_task`，`:262-330`），Phase-3 已有 `202 + /api/tasks` 模式。把 discovery 的抓取挂进去不需要新基础设施。**注意**：它消除的是长同步请求/超时，**不消除**活数据漂移窗口，属独立改进项。 |

---

## 四、架构上更优的收敛方向（推荐）

**不要把问题 A/B 当成两个独立 bug 修，而是收敛成三件事：**

1. **契约归属收敛**：`complete/stop_reason` 的**判定**抽成共享纯函数（TDC/Aras 共用），
   `_json_error` 成为**唯一**错误出口（含 `diagnostic`）。
2. **职责回归**：分页完整性 = 簿记（页号/size/total/pages/unique 计数）；
   **业务身份只留在同步层**。爬虫不再持有业务字段语义，也不再需要猜"逐行唯一键"。
3. **可观测性前置**：所有完整性事实（stop_reason / unique / dup / total / pages）默认进错误响应与诊断包，
   从此线上失败一轮可定案。

**另一个值得评估的架构选项（比继续修列表接口更彻底）**：
D5 的 `tdc_data_model` **同时**存在两条取数路径——live 同步（`syncCapable=True`）与归档任务快照
（`tdc_data_model` job，D6-D8 用的就是这条）。官方导出路径本身带显式行号列
（TDC 表单契约里有「工作表行号」，`web/app.py` 的 `preview_source=official_export` 已支持，
归档快照也正是走官方导出生成的）。若把 D5 的取证/同步改为**消费归档快照或一次归档运行结果**，
则：身份有稳定行号、复用语凭据/租约/重试机制、交互路径不再依赖 17~22 页的实时抓取，
并且 D2/D5 与 D6-D8 的模型统一。**代价**：改变 D2/D5 的取数架构，属较大立项，建议单独立项评估，不塞进本轮。

---

## 五、红线（改动过程中不可触碰）

1. 不得为修 B 削弱"身份过粗导致丢行"的 fail-closed —— 否则聚合快照会**静默少数据**。
2. `/api/project-status` 热路径**不得**引入 vault I/O。
3. 爬虫层**不得**反射上游异常原文；`error_type` / `remedy` 必须闭集。
4. 向导降级改写的 rule 必须与**落库内容、证据签名**三者一致。
5. completeness 语义变更必须**同时**落 TDC + Aras + 两套测试，并在 `DECISIONS.md` 记录安全意图变更。
6. 解析/落盘的旧证据（`config_signature`）不得被语义变更反向污染。

---

## 六、实施顺序与风险分级

| 阶段 | 内容 | 风险 | 依赖 |
| --- | --- | --- | --- |
| P0 | 错误契约扩展（`_json_error.diagnostic`）+ 422 下发完整性事实 + 向导展示 | 低 | 无（可立即做） |
| P1 | A-1 枚举化 + A-2 associations 字段 + A-3 前端三态与指引 | 低 | P0 的契约风格 |
| P2 | 抽 `evaluate_pagination_integrity` 共享纯函数（等价重构，不改语义） | 中（纯重构） | P0 |
| P3 | completeness 语义放宽（重复降级为指标 + total 容忍增长） | **中高（安全语义）** | P2 + 你的确认 |
| P4 | 向导对称收窄降级（含产品口径确认） | 中 | P1 |
| P5（可选） | discovery 异步化 / D2-D5 改走归档快照取数 | 中高 | 单独立项 |

**建议：P0+P1 现在就能做**（一个可定案、一个根因已复现确定）；
**P2 可与 P0 并行**（纯重构、行为等价）；
**P3 必须等你回传 `stop_reason` 并确认语义放宽**；
P4 需要你确认"自动收窄是否允许静默改口径"。

---

## 七、需要你决策的三件事

1. **是否接受 completeness 语义放宽**（重复不再致命，改为"unique ≥ total 且页簿记一致"）？
   —— 这是修 B 的关键，且它把上一轮的 Major 一并消掉。
2. **向导"自动收窄"是否允许静默改变聚合口径**，还是必须弹确认/仅提示？
3. **是否把 discovery 异步化**（复用既有 `CrawlTaskRunner`）——本轮做还是单独立项？

---

## 八、核实依据（本仓库实际代码位置）

- 去重身份：`services/tdc_crawler.py:1529-1588`、`services/aras_crawler.py:417-450`
- 完整性判定：`services/tdc_crawler.py:674-855`、`services/aras_crawler.py:388-475`
- 共享词表：`services/project_status_records.py:36`
- 消费者：`services/project_status_connectors.py:65/253/361`、`web/app.py:1232/4606/4619`、
  `services/scheduled_archive_connectors.py:451/477`、`services/ewo_enrichment.py:39`
- 错误出口：`web/app.py:376-391`、`:2608-2609`；预览已下发 stop_reason：`:1476/1697`
- 归档就绪门控：`core/db_manager.py:4493-4519`、`services/scheduled_archive_runner.py:70-119/313-361`
- 任务基础设施：`services/crawl_task_runner.py:262-330`
- 证据：`.runtime/repro2_out.txt`、`.runtime/repro_out.txt`、`.runtime/shots3/*`
