# Decision Log

Durable decisions that constrain future work. Append-only: supersede, never
delete. Per-plan rulings stay in their SDD ledger (`.superpowers/sdd/…`, local)
and get promoted here once they prove durable. Newest first. Keep entries
short: decision, why, cost if violated, source pointer.

## 2026-10-01 — 插件化重构立项：宿主 + 功能插件 + Schema 视图 + onedir 签名插件包

1. **方向**：保留 `services/` 能力层，把 Web 层、数据归属和打包分发重建为 CTFd 式 Flask 插件目录（`register(host)`）+ `plugin.json` 声明式清单 + calibre 式签名 `.vsepkg` 导入；前端为无构建的 Preact + htm（用户确认）。
2. **迁移纪律**：绞杀者方式分 4 个 Sprint；重构期间新需求一律写成插件，不再往 `app.js`、`web/app.py`、`core/db_manager.py` 加代码；插件不得互相 import 或直接写公共表。
3. **基线**：重构前代码点为分支 `checkpoint/pre-plugin-refactor-20261001`（d15d0f2）；重构分支 `refactor/plugin-host`。
4. **表单定义单一来源暂放 `core/form_registry.py`**：onedir 包里插件以源码放在 exe 旁、不进 PYZ，旧 services/core 在冻结运行时无法 import 插件目录；旧调用方迁完后再移入插件。
5. **S1 门槛演练（Claude 执行，2026-10-01）**：用 `tools/new_plugin.py` 新建只读“归档任务看板”插件，只改了插件自己的 `backend.py`（约 30 行）和 `static/pages/jobs.json`，宿主与旧文件改动为 0；浏览器验证通过后删除（只是演练，不上线）。演练暴露的 UI Kit 缺口（图例文字写死）已补上 `labels`。容器时钟不能当真实耗时，“新增展示页 ≤45 分钟”仍需开发者本人实测一次。
6. **签名插件包（S2）**：`.vsepkg` 用 Ed25519 签名（`cryptography`），私钥只在打包机，用 `tools/plugin_keys.py init` 生成并把公钥写入 `host/trusted_keys.json`；导入只暂存，重启时生效，新版本加载失败自动回滚到上一版或随包内置版本。用户在“设置 → 插件更新”页操作，不会强制更新。
7. **表单 form_key 不再用 SQL CHECK（S2）**：合法性由写入前按 `core/form_registry.py` 校验；旧库检测到 CHECK 时整表重建一次。`CURRENT_SCHEMA_VERSION` 保持 14，这样回退旧版 exe 仍能打开数据库。
8. **数据库按域拆分（S3）**：`DatabaseManager` 变成门面，方法按领域放在 `core/repos/`（项目状态、表单快照、自动同步、定时归档、crawl 任务、插件迁移），共用常量和辅助函数在 `core/db_common.py`；对外接口不变。插件自己的表用 `p_<id>_` 前缀，由 `host.migrate([(版本, fn)])` 做只加不减的迁移，版本记在 `plugin_schema_versions`，数据库版本高于插件时跳过不报错（保证插件包可回滚）。
Cost if violated: 新功能继续散落到共享巨型文件，增量发布无法实现。
Source: `docs/PLUGIN_REFACTOR_PROPOSAL_20261001.md`、`docs/PLUGIN_REFACTOR_PLAN_20261001.md`。

## 2026-09-25 — NCR 命名行：位置视图是权威值来源，标签字典只是有损投影

1. **`NcrWorkbookRow.named_row()` 必须携带契约顺序的 `values`**。官方 NCR 进度数据表头有 11 个
   角色标签各出现两次（列 37..47 办理时间 / 列 52..62 执行人），标签字典按「后写覆盖先写」构建，
   是**有损**投影：按标签重建位置视图必然丢掉一个同名列。因此位置数组是权威值来源，
   读取侧位置优先，标签键只供按标签取值的消费者使用。
   代价：命名行多一个数组键；任何对快照行做 exact-equality 的断言都必须同步更新。
   违反代价：11 个办理时间日期被静默覆盖 → 所有节点被误判逾期（2026-09-25 审计 Major）。
   来源：`docs/PLAN_20260925_BOARD_TRIM_AND_ARAS_UNIFY.md`（审计修复轮）+ Codex `sol-high` 咨询裁决。
2. **不采用「父表头消歧」改标签键**。那会改变命名行形状、破坏与 Aras 命名行一致的约定，
   并要求所有按角色标签取值的代码同步改；收益小于风险。
3. **行身份语义不得因行形状改变而变**：`_ncr_row_identity()` 优先 `NCR编号` 标签、否则前 10 列拼接，
   使同一行带不带位置视图得到相同 `rowKey`（修复不产生新身份键）。
4. **历史有损快照不回填、也不假装已修**：只带标签键的行保持原读取边界，并 emit
   `forms.ambiguous_header_labels`（有界、非敏感）+ `remedy=reproject_from_archived_workbook`；
   补救路径是重新同步（归档路径保留官方 XLSX 原件）。禁止把历史行当作修复后的正确数据。
5. **重复表头标签是契约事实，必须由守护测试钉住**（重复标签集合、索引、父表头语义、
   阶段日期命中第一组）。上游表头一变即失败提醒重评读取口径；**禁止改契约文件规避**重复标签。
6. **EWO 分析缓存来源标签写作 `aras_ewo`**：所有 Aras 报表写入侧都用限定标签，
   裸 `"aras"` 仅保留为历史缓存读兼容（`is_ewo_source_type` 对两者皆真，读取语义不变）。
7. **披露事件的载荷必须落在录制白名单内**：`core/diagnostic_recording.safe_metadata` 只转发
   `_NUMBER_FIELDS` 数字键与 `_TEXT_FIELDS` + 闭集 `_VALUES` 的文本键，其余键在落盘时被整体丢弃
   （事件名仍留存，`data` 变 `{}`）。产品新增诊断必须用白名单内的键名，或按既有做法把词条加入 `_VALUES`；
   新增披露必须配一个"经 `Recorder` 录制导出后 `data` 可读"的回归测试。
   违反代价：告警看起来存在，运维实际读不到任何数字（2026-09-25 两处 NCR 披露同时踩坑）。
8. **历史快照不回填、读时不诊断**：`normalize_form_rows` 的生产唯一调用点是发布路径
   `build_form_snapshot`；快照读取路径不重新归一化。因此纠正历史错误数据的唯一路径是重新同步
   （归档保留官方 XLSX）。**禁止**把库里历史行的 `values` 当权威去"重投影"——那是被覆盖值还原出的污染数据。
9. **同名表头标签的列一律不还原**：`_ncr_header_mapping_values()` 对重复标签（NCR 进度 11 组）不填任何位置，
   宁可"未判定"也不让执行人姓名落进办理时间列；带位置视图的行不走该分支。

## 2026-09-25 — PAA/NCR 与 EWO 同构：单一解析口径、工作簿准入门、来源标签限定、元数据取代硬编码

1. **NCR 官方工作簿只有一个解析口径**：`services/aras_ncr_workbook.parse_ncr_workbook()`。
   同步路径（`project_status_connectors`）与归档路径（`scheduled_archive_connectors`）都必须
   消费它，行形状统一为「按已批准表头标签命名的字典 + `sheetName`」。禁止任一路径再自建解析
   或发布位置行——读取按 `snapshot_at DESC` 取最新，双形状会让同一交付物的明细/图表口径
   随"最后写入者"翻转。
2. **完备性词表仍由 `services/pagination_integrity.py` 单点拥有**：官方工作簿准入新增
   `WorkbookBookkeeping` + `decide_workbook_outcome()`，`COMPLETE_STOP_REASONS` 增加
   `workbook_rows`。判定只消费簿记事实（读取/解析/空行/表头/未归类行、表头契约、截断），
   不消费业务字段语义。**`complete` 只表示"满足准入策略"，不等于"证明源端零丢失"**；
   官方工作簿没有声明总数，不得宣称与分页报表同等的源端全量保证。
3. **NCR 准入 fail-closed 的分支优先级即契约**：不可读 → 表头不符 → 截断 → 行被拒 →
   簿记不平 → 存在未归类行 → 空表 → 通过。同步路径 `require_complete_workbook()` 抛错；
   归档路径保留官方产物，以 `projection_error` + manifest 簿记事实披露并转 attention。
4. **EWO 阶段机只适用于 EWO**：分析缓存写入侧必须用 `analysis_source_type()` 产出的限定标签
   （`aras_ewo` / `aras_paa` / `aras_ncr`）。裸 `"aras"` 仅保留为历史缓存读兼容，
   禁止在新写入路径使用（否则 PAA/NCR 会被按 EWO 语义归一化与评分）。
5. **能力注册表是同步契约的唯一来源**：`supportsRecordSet` / `completenessPolicy` /
   `defaultDepartment` / `filterKeys` / `boardVisible` 一律从
   `core/project_status_contracts.py` 派生。禁止在连接器、路由、前端再写
   `deliverable_id == "VPI-T2-D3"` 之类的行为分支，也禁止把默认责任部门硬编码在连接器里。
   `filterKeys` 必须与连接器实际消费的查询键一致（由测试守护），`matchKeys` 必须包含
   `filterKeys`（PATCH 校验与连接器同源）。
6. **看板可见性与统计参与解耦**：`boardVisible=False`（当前 D1/D4）只影响首页卡片区与
   交付物明细表的渲染，不改变交付物存在性、详情页、分析接口、审计与完成度统计分母。
   `countsTowardCompletion` 仍单独控制分母参与。
Cost if violated: 同一交付物两种快照形状导致明细/图表忽多忽少；NCR 少行被当完整写入（静默丢数）；
PAA/NCR 被 EWO 语义误判逾期；新增交付物仍需改多处 id 分支（结构继续漂移）。
Source: 2026-09-25 用户批准 `docs/PLAN_20260925_BOARD_TRIM_AND_ARAS_UNIFY.md`（外部顾问 `sol-xhigh`
第二意见已采纳：P1/P2/语义隔离同次上线、服务端看板投影、工作簿准入 (a)、双写者同形、不断言源端全量）。

## 2026-09-25 — 分页完整性容忍度契约修订（方案 1-A 的 95% 阈值不得定案，方向改为有界放行 + 显式披露）

1. **方案 1-A 的 95% 相对覆盖率阈值不得作为长期安全阈值**：该阈值只约束 `declared_total − unique_count`，不约束实际折叠条数（809 行可少 40 条、10 万行可少 5,000 条仍判 complete）。在拿到生产身份/抓取证据前，任何非零容忍度不得定案。
2. **长期方向（外部顾问裁决，lead 采纳）**：终局放行采用有界容忍 + 显式披露——容忍度为调用方显式传入的策略参数（默认严格；TDC data_model/sor 显式选有界容忍，Aras 保持严格，完整性模块不识别来源业务语义）；放行终局须携带独立 stop_reason（`reported_pages_with_duplicates`，待消费方审计后纳入 `COMPLETE_STOP_REASONS`）与折叠数/声明总数/去重数诊断；`complete=True` 语义为"满足准入策略"，不得表述为"证明零丢失"。
3. **临时护栏（Phase 1）**：`allowance = 0（declared_total < 20）；否则 min(1, floor(0.01 × declared_total))`；折叠数与 `max(0, final_total − unique_count)` 均不得超过 allowance；簿记一致性核对（原始读取数 = 去重数 + 折叠数）须对 `overflowed` 豁免。上限如需提高（例如至 3 条）必须用 `min` 形态并以生产证据校准。
4. **禁止**：仅凭相对比例放行；在 `services/pagination_integrity.py` 内识别 TDC/Aras 业务来源或字段语义（容忍度只经调用方参数进入）。
Cost if violated: 行键缺陷或上游重发造成的成规模误折叠被判 complete → 静默数据丢失并污染聚合统计与完成度分母；或回退到第 1 页 1 条业务重复即熔断的 HTTP 422 产线阻断。
Source: 2026-09-25 外部专家顾问裁决（脱敏咨询包：分页完整性方案 1-A 安全边界定案）；关键主张已由 lead 在当前代码上核验（`services/pagination_integrity.py:67-76,120-131`、`services/tdc_crawler.py` 去重循环与溢出豁免、词表消费方清单）。

## 2026-09-23 — SOR 聚合字段映射容错、数模状态全链路闭环与 PAA/NCR 白名单补齐

1. **聚合向导 note 字段映射容错与清洗**：
   - 前端向导在聚合模式下，禁止硬编码 note 映射列，必须与最新脱敏字段报告（`fieldReport.fields`）做动态交集；
   - 后端在 `_mapping_evidence_error` 校验中，对列表型 `note` 字段只要候选列与 `observed_fields` 交集非空即可放行，并将清洗后的交集列表写入数据库，严格保证存库 `mapping ⊆ observed_fields`。
2. **数模状态筛选（8 点契约闭环）与严格全等完成态**：
   - `TDCDataModelFilters` 及相关 8 处注册表完整闭环支持 `status` 字段；
   - 完成态枚举扩充支持 `{"4", "已完成", "完成", "审批完成", "审批通过", "已归档", "归档", "已发布", "流程结束", "已生效"}`，禁止使用子串匹配以防“审核不通过”误判；
   - 严禁将快照完成时间反写进数据库业务表的 `actual_date`，维持 Field Authority 人工隔离。
3. **PAA / NCR 映射发现白名单覆盖**：
   - `web/app.py` 的 `_MAPPING_DISCOVERY_RULE_FIELDS` 必须完整注册 `("aras", "paa")`, `("aras", "ncr_progress")`, `("aras", "ncr_detail")`，且必须包含 `department` 字段与单号别名（`serial_number` 与 `ncr_no` / `paa_no`）。
Cost if violated: SOR 向导因局部字段缺失抛 HTTP 422 阻断启用；数模状态无法按需筛选且完成度始终为 0%；PAA/NCR 映射发现抛 HTTP 400 filters contains unsupported fields。
Source: 2026-09-23 生产实测与子智能体 code-reviewer 架构审计。

## 2026-09-23 — 分页完整性翻页熔断放宽 (方案 1-A) 与 PAA/NCR 交付物同步向导全量同构化 (方案 2-A)

1. **分页翻页熔断放宽（方案 1-A）**：
   - 爬虫翻页中途（`page < reported_pages`），单页出现轻微重复时不提前熔断，爬虫必须继续翻页抓取后续页（返回 `continue`）；
   - 在翻满声明页数（`page >= reported_pages`）且总记录数较多（>= 20）时，允许极轻微业务重复（去重行数覆盖率 >= 95% 时判定为 `"reported_pages"` 完整）；
   - 少量记录样本（< 20）或去重行数严重不足（< 95%）时，依然 fail-closed 判为 `duplicate_records`（防大批量漏数据）。
2. **PAA/NCR 交付物同步向导全面同构化解耦（方案 2-A）**：
   - 彻底废除 D6-D8（PAA、NCR 进度、NCR 明细）必须跳页面至「自动归档」配置的割裂链路；
   - 将 D6-D8 全面升级为 `syncCapable=True`，注册各自的标准字段映射（`defaultMapping`）与字段别名推导词表（`fieldAliases`）；
   - 前端详情页统一呈现【数据同步向导】（凭据默认统一域账号、车型项目输入、责任部门预填 `技术中心_车体工程`、定时周期下拉），点一次即可一键配置并首次同步，常驻【立即同步】与【修改同步配置】；
   - 后端连接器与运行器在同步执行后全自动构造并持久化表单快照（`publish_deliverable_form_snapshot`），无缝保持表单视图与统计图表的实时更新。
Cost if violated: TDC 多页抓取在第 1 页因 1 条业务重复即中断失败（HTTP 422）；PAA/NCR 交付物同步体验与 EWO 割裂，必须跳出页面去配置归档。
Source: 2026-09-23 用户生产测试确认方案 1-A 与方案 2-A。

## 2026-09-22 — TDC 数模爬虫零件级粒度标识与责任部门解耦规范

1. **TDC 数模 (D5) 零件级（part_detail）行唯一性标识规范**：
   - TDC UWF 数模设计审核流程报表粒度为 `part_detail`（同一流程客观存在多行同零件号、同模号、同名称记录，如左/右侧第二排锁扣组件等）；
   - `_row_identity` **必须优先使用行记录级主键/实例键**（`id`, `recordId`, `rowId`, `detailId`, `partId`, `subId`）；
   - **禁止**将流程级标识（`processInstanceId`, `instanceId`）作为行级主键使用（它们代表流程/审批单，会导致同流程全部零件被误折叠为 1 行并误杀为 `duplicate_records`）；
   - 流程级标识必须归入 `workflow_key`（与 `incident`, `documentNo`, `formId` 等同属流程级）。
2. **向导责任部门多系统命名空间解耦与容错**：
   - 向导禁止硬编码单一系统部门默认值；读取时禁止使用 `|| 默认值` 剥夺用户清空部门参数的权利；
   - Aras 默认 `技术中心_车体工程`，TDC 默认 `车体工程`（提示可留空）；
   - 提供 `normalizeTdcDepartment` 自动剥离 `技术中心_` / `技术中心-` 前缀；聚合取证若遇 `not_found` 支持自动尝试不带部门参数重试一次。
Cost if violated: TDC 数模多页抓取时同名合法零件被误杀致第 1 页自杀式中断（HTTP 422）；或将 Aras 部门误注入 TDC 导致 0 命中。
Source: 2026-09-22 生产实测取证与 code-reviewer 架构交叉审计结论。

## 2026-09-22 — 分页完整性契约单一拥有者 + 错误出口统一 + 失败指引闭集化

1. **`complete/stop_reason` 判定只有一个拥有者**：`services/pagination_integrity.py`
   （叶子模块，无第三方依赖、不 import 上层、**不消费业务字段语义**）拥有 `stop_reason` 词表
   （`COMPLETE_STOP_REASONS` / `is_complete()`）与元数据驱动的终局判定
   （`decide_page_outcome()`，分支顺序即契约）。TDC 与 Aras 两个生产者都必须经它派生 `complete`；
   **禁止**任一爬虫再立字面集合（`tests/test_pagination_integrity.py` 有反向守护）。
   `services/project_status_records.COMPLETE_RESULT_STOP_REASONS` 仅为兼容别名（同一对象）。
   Why：此前同一语义在两个爬虫各自实现，改一处必漏另一处（D3/EWO 迟早同类失败）。
2. **分页完整性只管簿记，不管业务身份**：`complete` 只由页号/大小/声明总数与页数/去重计数决定；
   业务身份永远只属 `services/project_status_records`。
3. **错误出口唯一**：`web/app.py:_json_error` 是唯一错误出口，`diagnostic` 只承载**有界、非敏感**的
   枚举与计数（如 `stopReason/uniqueCount/duplicateCount/declaredTotal/declaredPages/fetchedPages`）；
   禁止放入上游原文、凭据或业务行内容。抓取类失败**必须**携带完整性事实，否则线上无法定案。
4. **失败指引闭集化**：`ArchiveJobNotReadyError.reason`（credential_not_configured / job_disabled /
   contract_mismatch / filters_invalid / retry_policy_invalid / unknown）与
   `remedy` 指引码（bind_domain_credential / save_domain_credential / …）均为闭集；
   前端只匹配闭集码，**严禁**匹配英文原文文案。
5. **热路径禁止 vault I/O**：`/api/project-status` 只能透出 `credentialConfigured`（既有布尔列）；
   「凭据是否真的可用」留给点击时的 `sync-now` 结果。
Cost if violated: 语义再次分裂并第三次返工；错误响应缺失事实导致又一轮盲猜；
前端匹配英文串在文案变化时静默失效；热路径凭据探测拖慢项目状态接口。
Source: `docs/ARCH_REVIEW_20260922_SYNC_FIX_FEASIBILITY.md`（架构评估）+
本轮实施与门禁证据（全量 2346 passed）。

## 2026-09-22 — 归档同步的「用户显式触发」与「调度」门控必须分离，且前端禁止假成功

1. **门控分离**：`ArchiveSyncRunner.run_once` 的 `enabled_only=True` 是**调度**语义的正确门控，
   但**用户显式点击的同步**（交付物详情页【立即同步快照】→ `POST /api/scheduled-archive/jobs/<key>/sync-now`）
   在默认（新库 6 个内置归档任务全 `enabled=0`）状态下会得到
   `outcome=not_ready / errorType=missing_job`，而端点仍返回 HTTP 200 + `ok:true`。
   若产品口径要求「用户无需先启用定时任务也能同步一次」（形态 A，用户已选），
   必须新增**仅对 `trigger_type="sync_now"` 生效**的显式通道，**调度路径始终保持 `enabled_only=True`**。
2. **前端禁止假成功**：任何 `sync-now` 类调用必须解析
   `results[0].outcome/finalState/errorType/errorMessage`；`not_ready`/`failed`/非零 `exitCode`
   一律按失败展示（脱敏）并给出可操作指引（去自动归档启用 / 保存统一域账号凭据）。
   仅校验 HTTP 状态与 `body.ok` 即为缺陷。
Cost if violated: 用户看到"同步成功"但交付物依旧无数据，比"没有按钮"更具误导性；
调度门控被误放开又会让未启用的任务在后台自动运行。
Source: 2026-09-22 主 Agent 独立代码审计（`docs/CODE_AUDIT_20260922_DELIVERABLE_SYNC_ZCODE.md`）
+ 复现证据 `.runtime/repro_out.txt`。

## 2026-09-22 — 外部快照驱动交付物（D6-D8）同步入口形态：直接可点「立即同步快照」

1. **D6/D7/D8（PAA / NCR 审批进度 / NCR 审批明细）** 虽为 `syncCapable=False`
   的外部快照驱动交付物（`formSnapshotDriven=True`、`countsTowardCompletion=False`），
   但**必须在交付物详情页提供可点的同步入口**，且 **不要求用户先到「自动归档」启用定时任务**：
   入口直接调用对应归档任务的 `POST /api/scheduled-archive/jobs/<jobKey>/sync-now`
   （后端 `ScheduledArchiveAdminService.sync_now` 本就不校验 `enabled`），
   另附「查看同步任务」跳转 `#archive-deliverable/<jobKey>`；任务未启用时给
   「去自动归档启用」的明确指引，**禁止**再渲染永久 `disabled` 的死按钮。
2. **关联键单一来源**：归档任务键必须由 `DELIVERABLE_LINK_REGISTRY` 派生并随
   `/api/project-status` 的 `sourceInfo` 下发（`archiveJobKey`），前端禁止硬编码映射。
3. **TDC 与 Aras 部门命名空间严格分离**：`技术中心_车体工程` 是 **Aras** 口径
   （`_rsp_department` / PAA `department` / EWO `responsibleDepartment`），
   **禁止**作为 TDC（SOR `deptName`、数模 `superDepartment`）筛选默认值；
   TDC 域值形如 `车体工程`（部门级）/ `外饰科`（科室级）。
4. **实施与验证状态**：已完整落地实施并通过自动化测试、Node VM 契约核验与 code-reviewer 严格交叉代码审计（PASS）。
Cost if violated: 用户面对不可用的灰按钮或「没有同步按钮」；再次把 Aras 部门默认值
灌入 TDC 查询导致 D2/D5 一键同步必然失败（回归重演）；关联键硬编码使注册表漂移。
Source: 2026-09-22 生产测试反馈 3 张截图 + 代码/契约/本地库取证实证 +
`docs/PROD_TEST_20260922_DELIVERABLE_SYNC_ISSUES.md`。

## 2026-09-19 — HCI 与系统架构审计决策：统一任务模型、冻结重试语义与桌面/导航重构架构约束

1. **统一任务模型与 Schema 纪律**：复用 `core/excel_tasks.py` 经审计的持久化范式（状态机、租约管理、不存凭据与 Token、幂等性），提供全局统一的任务抽屉 UI 与 `/api/tasks` 外观（facade），严格维持 Schema v14 兼容基线，`crawl_tasks` 采用增量式 DDL，禁止新建平行分裂的任务子系统。
2. **冻结重试语义与 EWO 防重**：端点按外部副作用严格分类——纯读类查询与普通导出（EWO/PAA/NCR query/crawl-all、TDC query/crawl-all）允许重试；带外部写/生成副作用的 EWO 流程增强任务（`/api/aras/ewo/enrichment/jobs`）严禁盲目自动重试，`generation_unknown` 态仅允许通过状态复核（state check）探查，复用既有 durable ownership 模型。
3. **工件统一生命周期**：产物统一落盘至 `data/downloads/`，执行 7 天自动归档清理淘汰策略（7-day pruning），避免单机环境磁盘膨胀。
4. **进程内线程池与同源互斥**：采用进程内 `ThreadPoolExecutor(max_workers=2)`，明确否决 Celery/Redis 等外部重型依赖；针对同一数据源施加并发互斥锁（per-source mutual exclusion），避免共享 Cookie/Session 互踩；抓取支持在分页边界进行协作式取消（cooperative cancellation，<= 2s 响应延迟）。
5. **Fail-closed 启动清理机制**：桌面 EXE 进程退出将终止运行中 daemon 线程；服务启动或重启时执行自检（startup sweep），将孤儿 `running` / `leased` 状态的抓取任务标记为 `interrupted`，彻底杜绝僵尸运行态与虚假进度。
6. **桌面启动与就绪探测**：`webui.py` 新增端口连通性 readiness probe，仅在 HTTP 服务真正监听就绪后通过标准库 `webbrowser` 打开 `http://127.0.0.1:<port>`；提供 `--no-browser` 命令行标志以适配批处理与无头测试环境。
7. **分期推进与测试解耦纪律**：Phase 1 优先落地 Hash 深链路由与测试套件解耦，明确约束「抽屉先行、未建任务抽屉前禁止移除 Excel 顶栏入口」——在统一任务抽屉与 `/api/tasks` 真正落地上线前，严格保留顶栏 6 大导航入口（包括交付物与 Excel 任务），禁止过早收拢或隐藏；专项重构测试套件中脆弱的字符串切片与位置断言（`tests/test_overview_web.py` 等），提升为语义化断言；全流程确保既有测试全绿且地图无漂移。
Cost if violated: 任务语义分裂与重复建设；EWO 盲目重发引发服务端重复记录污染；磁盘空间泄露；僵尸任务混淆用户；UI 结构调整引发大规模陈旧测试假红。
Source: `docs/HCI_BLUEPRINT_ARCHITECTURE_AUDIT_20260919.md` 架构审计与统一决策评审。

## 2026-09-16 — WebUI 第一阶段易用性：原位登录现场保护、显式继续查询与设置分层

1. **版本探测与环境退化**：建立 `core/version.py` 与 `GET /api/version`，优先读取注入环境变量与版本元数据文件，开发环境安全退化为「开发工作区」，冻结环境在无元数据时退化为「独立运行包」，严禁每次请求调用外部 Git 进程或泄漏物理路径。
2. **顶栏独立指示与原位登录**：顶栏独立分别展示 Aras 与 TDC 会话状态；查询未认证或过期时提供原位登录模态浮层，登录取消或失败不刷新页面、不清空表单输入；登录成功后关闭浮层并提供显式【继续查询】按钮，禁止自动重放有副作用或未确认草稿的业务请求。
3. **共享结构化错误与防重**：前端统一封装 `renderStructuredErrorCard`，包含业务影响说明、下一步明确动作与折叠技术详情；保存成功但刷新失败场景下明确告知「已保存」，仅提供刷新显示按钮，禁止诱导重复保存；EWO 未知生成状态严格禁止重发。
4. **设置分层与兼容性保护**：日常业务目录默认展开，低频临时/诊断目录与重试、保留参数收纳在高级维护折叠区；标签清除底层代码字段名，保持 input id/name/类型完全兼容，确保折叠时保存不重置未编辑字段；明确重试次数仅控制实时在线抓取，不越界覆盖定时任务。
Cost if violated: 页面跳转导致工程师填写的条件丢失；错误诱导重复提交业务写操作；设置保存误清空高级参数。
Source: ZCode 会话 2026-09-16 WebUI 第一阶段易用性优化实施合同。

## 2026-09-06 — 环图"按节点状态自动显示"规则口径

auto 模式下，交付物若已完成（完成态取快照换算口径，回退手工值）且主计划中
存在"名称分词后包含其关联节点关键字、且日期已过"的节点，则不再展示；隐藏
数量在 band-head 提示。映射常量 DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS
（app.js）：D1→VDR、D2→VPI、D3→T2、D4→VDR、D5→T2，属产品口径可调整。
节点匹配必须用分词精确匹配且连字符不分词——子串或按连字符分词会把
「VPI-T2 Gate」误判为 VPI 节点。空日期（待排期）节点永不触发隐藏。
Cost if violated: 关键交付物在总览被误隐藏或该隐藏的不隐藏。
Source: ZCode 会话 2026-09-06 用户示例（到了 VDR 阶段隐藏已完成的子系统
开发策略）+ code-reviewer 审计轮。

## 2026-09-06 — SOR 定点流程 (tdc_sor) 注册为第 6 个统一表单

`tdc_sor`（TDC SOR 定点流程，官方 15 列导出，headers 见
report_contracts()['tdc_sor']）按 tdc_data_model 同款机制注册：DDL CHECK
白名单 + 检测式重建迁移（迁移检测条件为存储 DDL 缺任一新 form_key）；
维度口径 stage←车型项目 / section←科室 / department←部门（入库不上图）/
model←类型（仅筛选）；审批状态 API 中英文混合，`_normalize_sor_status`
归一（Completed→已完成）；已完成/Completed 计为完成；已终止/已作废/
Terminated/Cancelled 为终态（不计完成、不计未完成、不判逾期）；逾期沿用
审批中滞留 7 天口径（申请日期起）；“当前待办人”列（索引 14）加入
_CONTACT_INDEXES 脱敏；deliverable VPI-T2-D2 经
DELIVERABLE_FORM_LINKS/DELIVERABLE_FORM_KEY_BY_ITEM 双侧映射到 tdc_sor。
后续新增 TDC 表单照此配方：DDL 白名单+重建检测 → 分析服务四映射+维度/
逾期/状态归一 → runner job→form map → DELIVERABLE_FORM_LINKS → app.js
（键/tabs/筛选标签/图表标题）→ 四层测试。Cost if violated: 位置行错位、
联系人泄漏或状态口径不一致。Source: ZCode 会话 2026-09-06，SOR 官方 15 列
合同与 report_contracts 源字段映射为既定事实。

## 2026-09-06 — 主计划默认里程碑模板与空日期语义

默认里程碑模板为 11 个空日期节点（VPI → 内饰模型评审 → 外饰模型评审 →
LLP VDR → 100% VDR → LLP T2 → 100% T2 → OTS → 验证阀 → 内部体验阀 → 用户
体验阀），milestone_date=NULL 表示"待排期"（schema v13 里程碑列可空）。空
日期仅允许"未开始"节点；种子修复采用**全字段元组比对**：与旧 6 节点种子
完全一致才替换为模板，任何差异（哪怕只调换顺序或改一天日期）都视为用户
数据保留。current_stage_label 必须跳过空日期节点，否则 /api/project-status
500。未来新增"创建项目"接口时必须挂同一模板。Cost if violated: 用户手工
排期数据被静默覆盖，或空日期导致总览接口崩溃。Source: ZCode 会话
2026-09-06（用户确认方案 A + 架构审核修正版）。

## 2026-09-06 — 交付物状态图表读侧联动表单快照，不写库

除 VPI-T2-D1（子系统开发策略，纯手动）外，交付物"当前状态图表"与总览环图
在渲染时从 DELIVERABLE_FORM_LINKS（web/app.py 后端单源）指向的最新表单快照
换算：progress=round(completed/total*100)，状态三态（全部完成→已完成/
overdue>0→已逾期/否则→进行中）；无快照回退手工值；手工进度保留为详细明细
参考值。不向 project_status_deliverables 写回任何字段，字段权威规则不受影
响。快照→交付物映射只允许在后端维护（formLink payload 下发），前端
DELIVERABLE_FORM_KEY_BY_ITEM 仅作归档详情页回退。D2(SOR) 需业务口径确认后
注册表单；D4(造型VDR) 等 A 面契约解锁。Cost if violated: 双源映射漂移、或
自动写库与手工锁定字段冲突。Source: ZCode 会话 2026-09-06 用户确认。

## 2026-09-02 — 数模设计审核流程 (tdc_data_model) unified detail view contract

`tdc_data_model` (数模设计审核流程, TDC UWF `procuwfpe3ddigitalmodeldesignreview`,
47-column export) is now the 5th unified deliverable form. Approved口径:
chart tabs = 项目状态 (stage ← 项目/车型, observed values not fixed list) /
部门状态 (section ← 部门) / 数量趋势; 发布属性 only a filter (model dimension);
department dimension unused (empty select is hidden in UI). Overdue = 审批中
dwell > 7 days from 申请日期 (`_OVERDUE_RULES["tdc_data_model"]`); 已完成 and
已废弃 are not_applicable. Summary incomplete excludes 已废弃 (but in charts
已废弃 falls into the blue "unknown" bucket by design). Detail table hides
columns 12/13 (重量（单件）, 零件合计) everywhere in the view via
`_TDC_HIDDEN_COLUMN_INDEXES`, default visible 15 ending at EWO/SOR号; raw
values stay in stored rows. form_key is `tdc_data_model` (job-key aligned,
auto-links archive cards); project-status deliverable VPI-T2-D5 maps to it in
`DELIVERABLE_FORM_KEY_BY_ITEM`. Why: matches production test product (808 rows,
headers identical to the contract) and user-confirmed preview. Cost if
violated: the detail view diverges from the approved preview and EWO/PAA/NCR
structure. Source: this session's preview confirmation + implementation.

## 2026-09-02 — SQLite form_key CHECK 白名单扩展必须走表重建迁移

SQLite cannot alter a CHECK constraint; `_migrate_schema` rebuilds
`deliverable_form_snapshots` when its stored DDL lacks a newly allowed
form_key (foreign_keys=OFF outside any transaction → rebuild → commit →
foreign_keys=ON; leftover rebuild tables are dropped on next init). Adding a
future form key requires: DDL template + detection-based rebuild + the four
analysis-service maps + runner job→form map + connector form_rows + app.js
maps. Source: tdc_data_model registration, schema v11→v12.

## 2026-09-02 — Accept existing lint/type baseline for this migration

Treat the full pytest result (`1629 passed, 2 skipped`) and scoped flake8 over
the hardening files as the migration gates. Accept the repository-wide flake8
scan-boundary diagnostics and 69 existing mypy errors as out of scope; fixing
them requires a separate quality task. Source: verification after commits
`82827f5`, `86238b9`, and `785c650`.

## 2026-09-02 — Retired the 2026-06 four-role agent subsystem

Deleted `.codex.yaml` (explorer/architect/worker/reviewer role prompts; no
code consumer left) and the related historical docs (`docs/agents/`:
`project_state`, `task`, `review_feedback`, `role_*`, `SOP_worker_coding`,
`implementation_plan`) plus the consumed sprint plans (`PROJECT_OVERVIEW_*`,
`FRONTEND_REDESIGN_EXECUTION_PLAN`). Current collaboration rules: `AGENTS.md`
+ the supervisor harness (`tools/agents/`, `.agents/config.json`) +
`memory/`. Kept on purpose: `docs/PHASE0/PHASE1_*` (refactor rationale),
`DELIVERABLE_UPDATE_MODES_*` (implemented architecture), and
`GPT_WEB_PROJECT_CONTEXT.md` (external-LLM context). Recover via Git history.

## Established ≤ 2026-08-20 — Web/scheduling architecture constraints (promoted from GPT_WEB_PROJECT_CONTEXT.md §6)

- No permanent scheduler thread inside Flask: scheduled work runs as a
  standalone `run_once` runner invoked by Windows Task Scheduler
  (`services/scheduled_archive_runner.py`, `services/project_status_sync_runner.py`).
- External connectors return normalized candidate updates; they never write
  project-status tables directly — the shared update service owns validation,
  field authority, audit, and writes.
- Manual values win by default; scheduled sync respects field authority and
  never silently overwrites manually locked fields.
- A failed run keeps the last successful data and records a sanitized
  failure; it must not clear the dashboard or claim success.
- Preserve the existing `/api/overview` contract; add dedicated APIs rather
  than changing unrelated public endpoints.
- Unattended authentication requires a separately approved credential-reference
  design; plaintext credentials are never persisted to make scheduling work.
Source: `GPT_WEB_PROJECT_CONTEXT.md` §6 (capability claims elsewhere in that
file are partially stale — see CONTEXT_MANIFEST).

## 2026-09-02 — `memory/` is the shared Codex+ZCode memory layer

Four git-tracked agent-neutral files (`CONTEXT_MANIFEST`, `CURRENT_STATE`,
`DECISIONS`, `RECOVERY_NOTES`); protocol in `AGENTS.md`. Chosen because the
only durable cross-agent state was git history plus design docs: SDD ledgers
and `.agents/runs/` are local-only. Cost if violated: state loss on
clone/machine change/session switch, repeated investigation.

## 2026-09-01 — Headless AGY permission denial is a blocked result, never a reason to weaken the sandbox

Reaffirmed after 6 lost AGY runs (see RECOVERY_NOTES). The fix belongs in
detection/classification (`tools/agents/agy_cli.py`), not in disabling
`--sandbox` or granting blanket permissions. Source: `AGENTS.md` → Local AGY
CLI Delegation.

## 2026-09-01 — Form snapshot service stays additive to the existing EWO analysis cache

Existing EWO endpoints and legacy chart-label behavior must remain
compatible. Cost if violated: duplicate EWO storage and an extra migration
surface. Source: SDD ledger ruling 2026-09-01.

## 2026-09-01 — EWO PROC period uses one natural calendar-month boundary, not a fixed 30-day approximation

Requirement says "one month" and month boundaries are user-visible. Cost if
violated: one-day classification differences around short/long months.
Source: SDD ledger ruling 2026-09-01.

## Long-standing — Credential boundaries

- TDC: OIDC login via enterprise account center; passwords, tokens, and
  session data are never written to config, logs, or diagnostics.
- Aras/EWO: reuse the browser session Cookie/Authorization; no local
  credential persistence; expired sessions prompt re-capture, not storage.
- Secrets live only in the Windows DPAPI vault
  (`core/credential_provider.py`, `data/domain-credential.dpapi`, gitignored).
- Redaction (`core/redaction.py`) scrubs tokens/cookies/authorization
  headers from logs, exports, and diagnostics.
Source: README, `docs/PROD_DATA_MODEL_SOR_CAPTURE_GUIDE.md`, code.

## Long-standing — Excel automation is out-of-process for DLP compatibility

Office COM work runs in a dedicated worker process
(`tools/excel_worker_cli.py` / `core/excel_worker.py`), not in-process,
because enterprise DLP transparent encryption breaks in-process COM file
access. Source: `docs/EXCEL_TASK_WORKER.md`.

## 2026-09-02 — NCR/EWO relationship and detail aggregation

- Treat the cross-form relationship as `EWO 1:N NCR`; every NCR must map to
  exactly one EWO, while one EWO may map to multiple NCRs. NCR detail rows
  remain a separate `NCR 1:N detail-row` grain.
- Count NCR progress and NCR detail status/trend metrics by distinct NCR
  number. Sum NCR detail cost values at detail-row grain, aggregate the
  department as the all-region total, and use `区域` as the section
  dimension. Source: user confirmation on 2026-09-02 and the supplied
  workbook cardinality audit.

## 2026-09-02 — Scheduled EWO/PAA default department uses connector-specific keys

The built-in EWO archive filter stores and sends
`responsibleDepartment=技术中心_车体工程`; PAA stores and sends
`department=技术中心_车体工程`. The runner keeps a runtime fallback and the
schema seed repairs the exact early EWO typo without overwriting other user
filters. Why: the two ARAS connector contracts use different field names;
using `department` for EWO causes connector validation failure.

## 2026-09-02 — NCR form status metrics are entity-grain, costs are row-grain

`ncr_progress` and `ncr_detail` summary/status/overdue metrics collapse rows by
the sanitized `NCR编号`, using a stable representative for each NCR. NCR
detail cost charts and detail-table pagination continue to use every physical
detail row. Why: one NCR can have many detail rows; mixing grains inflates
status counts or loses cost values.

## 2026-09-02 — TDC official exports normalize by approved Chinese headers

TDC official XLSX rows are returned by the connector as header-keyed mappings,
but the form analysis layer recognizes approved Chinese headers and restores
the positional 47-column contract before extracting dimensions and dates. Why:
the API dictionary keys and official workbook labels are different contracts;
mapping the latter as API keys silently produces empty snapshot rows.

## 2026-09-02 — Legacy form snapshots use read-side compatibility

Existing installations are not rewritten just to add current schema metadata or
change NCR metric grain. The view service serves the current allowlisted schema
and re-summarizes legacy NCR history from preserved positional rows when the
stored schema lacks the entity-grain marker; status completion is normalized in
the read-side metric projection. Why: this preserves historical rows and keeps
the migration additive while removing mixed-grain dashboard results.

## 2026-09-02 — Form projection completeness is part of archive run acceptance

An archive run with an unreadable/invalid/truncated official form or a failed
form snapshot projection cannot finalize as `success`. The connector returns a
stable projection error code; the runner stores collected artifacts and marks
the same run `needs_attention`, preserving the last good snapshot. Why: a
successful source archive without a trustworthy form projection is not an
auditable successful sync.

## 2026-09-02 — NCR progress export records are identified by Result/_file

The NCR progress parser must not require one server-side `Item type` spelling.
It accepts only a non-empty `_file` child under an `Item` within the top-level
`Result` subtree, retaining the outer record ID and `_file` keyed name. It does
not use `Message` nodes as a fallback. Why: live ARAS returned a valid export
record with a different type value; the scoped relation is the stable contract
while arbitrary XML fallback would risk accepting error metadata.

## 2026-09-02 — Production WebUI package uses an explicit slim build profile

The WebUI PyInstaller spec excludes CLI-only integrations and development
helpers that are not reachable from the WebUI runtime (Selenium, IMAP, Rich,
xlwings, PythonWin browsers, and Flask test/debug modules). It retains the
explicit WinHTTP/pywin32 hidden imports required by the packaging contract.
The size-compliant delivery build uses Python 3.11, PyInstaller 6.22.2, and
UPX 5.2.1, then creates a standard Deflate ZIP containing only
`VSE-WebUI.exe`. Why: the default Python 3.14 build remains above the strict
15,000,000-byte mail limit; dropping Tk or the required COM hidden imports
would trade away WebUI functionality or violate the existing contract.


## 2026-09-08 — Primary local delegation runtime

Supersedes earlier default AGY-only Codex delegation for this project. User explicitly chose Codex lead + local ZCode Gemini bounded worker; optional free-GLM periods use one interactive ZCode GLM lead. Gemini is subscription/fixed quota, so optimize Codex allowance and acceptance success rather than minimizing Gemini reasoning at the expense of retries. Keep Flash High initially.

Reuse supervisor contracts/worktrees/checks, select zcode-app-server explicitly, and return high-risk/unclassified work to the current lead without another Codex planner call. Do not silently fallback to paid providers. Keep AGY/DeepSeek as explicit opt-in only. Native-tool guard, process-tree cleanup, model preflight and final diff/check review are required. New worker branches use codex/ prefix.


## 2026-09-09 — SOR identity and failure contract

- Resolve SOR project number/name to a unique internal ID with exact trimmed matching; reject missing/ambiguous/stale/mismatched identities. Do not reuse display text as carTypeProjectAll[0]. Blank filters remain unfiltered without a project-list request; cache only within one client.
- Retain query_failed compatibility while preserving allowlisted diagnostic stage/status/code/request identifier in archival messages. Arbitrary upstream prose stays out of persisted history. Do not mark workflow-list fallback as successful official XLSX export.

## 2026-09-10 — Gemini dual-tier and 272K worker policy

- Codex is the sole control-plane authority: use `gpt-5.6-luna` with `max` reasoning for architecture, security, public contracts, task decomposition and final integration; preserve its native context window.
- All non-Codex workers use an effective 272,000-token context ceiling. Gemini total usage is not cost-capped; output, waterline, wall-clock and loop limits exist for protocol stability, side-effect safety and context overflow prevention.
- Use Flash for bounded exploration, mechanical implementation, tests and ordinary UI work. Use Pro for complex implementation, root-cause analysis and deep read-only review. High-risk tasks remain Codex-controlled with Pro as an advisory reviewer only.
- The default worker path is ZCode app-server with explicit model slots and no automatic GLM/provider fallback. GLM is an explicit optional probe whose failure skips the side path.
- Worker-to-lead communication uses bounded `handoff.v1.json`; raw tool output, screenshots, credentials and provider diagnostics remain local evidence. The runtime must preflight model identity, protocol fields, scope policy and transport before a formal worker run.

## 2026-09-10 — Generated project map and Markdown lifecycle policy

`PROJECT_MAP.md` is the default Agent-facing code-navigation entrypoint. Its
volatile file, symbol, route and source-fingerprint sections are generated by
`tools/generate_project_map.py` from an explicit production allowlist; raw
crawler evidence, build artifacts, runtime state, historical root scripts and
session documents remain default-deny. `AGENTS.md` requires map-first,
scope-limited searches and `memory/CONTEXT_MANIFEST.md` remains the memory
navigation layer rather than duplicating the code map.

Markdown is classified as Active, Generated, Historical, Reference/Evidence or
Scratch. Active documents point to code/tests/decisions, generated documents
are refreshed by their named generator, and historical or scratch material is
not default Agent input. Why: the repository contains a large tracked crawler
sample pool and many dated planning artifacts; a manually maintained directory
tree or README cannot reliably distinguish production code from evidence.

## 2026-09-11 — safe diagnostic capture scope

User approved the complete observable WebUI/Aras/TDC/sync/archive/storage chain, excluding Office/Excel Worker/API. Use local cross-process recording with structural metadata and stable per-recording fingerprints, not raw payload capture or external telemetry. The operator guide states capacity, retention and evidence limitations. A matching CLI shares the application data root; existing Windows Task Scheduler definitions are not modified automatically.

## 2026-09-12 — main context governance and weekend worker profile

- Keep Codex on its native context window, but enforce orchestration watermarks of 150K (bounded-read monitoring), 180K (phase Handoff) and 200K (new micro-session). Trigger Handoff early for a phase boundary above 150K, a 20K uncached increment, an 8K tool return, or browser image payload.
- Keep the normal ZCode Gemini Flash/Pro route unchanged. Use the explicit project profile `weekend-5.3flash` only when the weekend allowance is selected; it maps to the configured `GLM-5.3-Flash` Provider and retains the 272K non-Codex worker cap.
- ZCode runtime accepts only explicit provider kinds and formats: `openai-compatible`/`openai-chat-completions` and `anthropic`/`anthropic-messages`. Provider/model/allowlist/preflight failures stop the route; no silent fallback.
- Parent Handoffs remain bounded to changed files, diff summary, verification, risks and next action. Full logs, diffs and screenshots remain local evidence.
- Treat `weekend-5.3flash` as an interactive-only ZCode gifted-card profile: static `anthropic-messages` setup passes, but the headless path must stop before preflight because the card requires interactive runtime headers/CAPTCHA. Do not route it through the bounded headless Worker or silently fall back.

## 2026-09-13 — Gemini Worker 1M context override

- The user explicitly overrides the previous non-Codex 272K Worker cap. Keep the Astra main-controller policy independent, but allow the configured Gemini Flash/Pro Worker to use up to 1,000,000 context tokens when the provider advertises that capacity.
- Preserve the 32,768 output allowance and 16,384 safety reserve, yielding a 950,848-token per-request input budget. Derive Worker waterlines from that budget at 80%/95%/100% instead of retaining the old 272K absolute thresholds.
- The repository config, installed runtime, handoff schema, installer defaults and operator docs must agree on 1,000,000. Provider/model preflight remains authoritative; no model/provider fallback is introduced.

## 2026-09-13 — Astra main-controller effective context 272K

- The user explicitly chooses a 272,000-token effective context window for the Astra Codex client, while keeping the Gemini Flash/Pro Worker at 1,000,000.
- Set `C:\Users\Lynch\.codex\config.toml:model_context_window` to `272000`; preserve `model_max_output_tokens=128000`, model selection and reasoning settings. This is a local client limit; it does not change Astra's provider-side native context capability.
- New Codex sessions must be used to observe the updated UI context total. The existing 150K/180K/200K orchestration watermarks remain inside this client window and are not replaced by the config edit.

## 2026-09-13 — 交付物同步聚合模式与映射模板（用户确认）

- 按车型模糊搜索默认**聚合全部匹配记录**（F610S 会命中低规出口/右舵/出口巴西等多个变体，
  全部计入同一交付物的完成度），不再要求唯一稳定键；单记录匹配保留为聚合的特例。
- 字段回写规则（用户确认的映射模板 + 聚合规则）：
  - EWO 流程：负责人←「责任工程师名称」；计划完成日期←「要求完成时间」；
    风险备注←「当前阶段未签署的角色&人员」。
  - SOR 定点流程：负责人←「申请人」；计划完成日期**取消自动更新**（报表无对应列，保持手工）；
    风险备注←「最新完成节点」+「审批状态」组合。
  - 数模设计审核流程报表：负责人←「申请人」；计划完成日期**取消自动更新**；风险备注←「待审批人员」。
  - 聚合多条记录时：负责人/计划完成日期**不自动写**（多记录写单值必然出错）；
    风险备注聚合写入（逐条"标识：卡点信息"，未完成优先、超长截断）。
    同步从不写 status/progress（既有口径不变）。
- 映射模板按"来源/报表版本"显式维护并需业务确认；来源字段名以真实证据抓取的
  字段报告为准（mapping ⊆ 最新报告校验兜底），TDC 行键为英文字段名（如
  incident/currentApprover），部分列名需生产证据确认。
- NCR **纳入同步范围**：排在聚合引擎之后接入（新增交付物行 + Aras 连接器 NCR
  报表支持 + 能力注册表契约 + NCR 列映射确认）。接入前维持归档留存 + 外部同步行展示。
- 交互形态（design-previews/sync-quick-config-demo.html 已确认方向）：
  车型关键词搜索 → 聚合记录预览 → 确认启用；服务端凭据抓取证据（复用统一域账号
  账密）；专家表单折叠为逃生门。TDC password 模式要求 HTTPS（生产地址待确认）；
  browser 模式无 Cookie 时已自动复用统一域会话（app.py _shared_domain_session）。
- 前置未决：单记录 vs 聚合的业务语义已由本决策定为**聚合**；若后续需要
  "单条流程精确定位"，专家表单的匹配键仍可收窄到单条。

## 2026-09-15 EWO v2持久兼容边界

EWO新版合同使用字符串contractVersion=2和显式single_record/record_set；旧规则不自动迁移。内部sourceItemId只固定当前记录版本，不能跟随同号新修订。集合负责人/计划日期永远手工。迁移先停用保存，新签名两次取证后启用；旧HTTP客户端缺版本确认拒绝修改，并在事务内比较配置修订号。数据库schema14同时阻止旧EXE打开新版库，回退必须恢复旧库备份。

官方导出为独立只读增强，不进入自动字段映射。账号+来源+筛选签名控制恢复；unknown生成结果禁止重发；基础与增强分别记时间；空号不按位置猜测关联。用户可以在prepare后查看真实基础内部ID，prepare无生成副作用。

## 2026-09-16 交付物控制台首期范围（用户授权实施）

- 已配置外部目标、集合或 EWO v2 映射时，整项禁止新的手工保存；默认 automatic 但无目标仍可编辑，异常配置拒绝。人工字段归属只约束同步写入，不绕过整项编辑限制。此规则覆盖旧文档的映射后人工覆盖入口。
- PAA/NCR 首期使用两张快照参考进度卡；2026-09-13 的正式 NCR 交付物接入为后续规划，本期不登记、不计入节点分母；NCR 明细不重复统计。
- 无节点隶属规则时隐藏交付物/风险占位，保留节点时间与主计划维护，不推断隶属关系。官方 EWO 增强仍只读。
- 本次仅后端自动测试；UI 由用户按 docs/DELIVERABLE_CONSOLE_UI_TODO_20260916.md 手工验收，工程审计完成不代表 UI 已验收。

## 2026-09-25 Expert Advisor 自主路由阈值

DSH 与 ZCode 的交互主代理可在用户未指定场景时自行决定是否咨询 Codex：先本地取证，仅当高影响决策有真实方案取舍，或高影响故障两轮聚焦排查后证据仍冲突时触发；用户明确要求第二意见也触发。普通实现、测试、文档和已定案问题跳过。每个决策最多咨询一次，重要新证据出现才可重新评估；顾问只提供意见，主代理保留最终裁决和验证责任，worker 不得调用。统一入口继续执行脱敏、隔离、额度和失败即停止的现有门禁。
## 2026-09-25 Expert Advisor 顾问模型与自主触发（取代同日旧高影响双方案阈值）

DSH DeepSeek Harness + v4.1 Flash 主代理和 ZCode Gemini 3.8 Flash 交互主代理，在非琐碎的架构设计与实施方案定案前自主寻求 Codex 第二意见，不要求用户点名或先有两个候选方案；普通执行和已定案事项跳过。选档：sol-high 为一般方案，sol-xhigh 为复杂多模块公共契约/并发/回滚，astra-medium 为边界较清楚的难回退安全、静默丢数、破坏性迁移决策，astra-high 为同类决策且有证据冲突或多处耦合。Codex 只提供意见，主代理独立裁决和负责实施；worker 不得调用。

四档经受控只读官方 CLI 的固定白名单传递，所有档位共用 provider 账本、额度、隔离与失败即停守卫。新增滚动 5 小时 2 次、7 日 8 次，Astra 另限日 1/7 日 2；从 2026-09-25 16:22 +08:00 前向生效，旧启动仍计入原自然日和每任务额度。旧受控只读模式的请求前零工具不可达缺口仍在，用户此前已接受该剩余风险。

## 2026-09-25 Expert Advisor 本地额度重置与验证

用户明确允许重置本机 Expert Advisor 配额。采用策略中的 local_quota_reset_at 前向计数，而非删除或改写账本；重置前的启动和结果继续留存，重置后的所有 Sol/Astra 档位仍共享原本地上限。此操作不触碰 ChatGPT Plus 的服务端用量或信用额度。用户授权后，DSH sol-high 与 ZCode astra-medium 各一次纯合成 live 已通过；验证后再次设置本地计数起点，为真实项目保留额度。项目中的自动路由规则与角色责任不变。

## 2026-09-25 Expert Advisor 共享 7 日额度改为 30（取代先前 8 次）

用户明确要求把前一轮讨论的本地滚动 7 日上限直接设为 30 次。codex-readonly 的 Sol/high、Sol/xhigh、Astra/medium、Astra/high 四档继续共用一个 provider 账本，weekly_cap=30。其他护栏保持：滚动 5 小时 2 次、自然日 10 次、每任务 2 次；Astra 另限自然日 1 次、滚动 7 日 2 次。此变更不重置 ChatGPT Plus 服务端额度或历史账本，也不自动扩大顾问触发场景。

## 2026-10-02 恢复策略：移植而非合并，行为测试取代源码文本测试

- 决定：旧业务分支遗漏行为**按条目移植**到插件架构（后端取参考顶端文件、前端按插件重写），不整条 merge/cherry-pick，
  不恢复 `web/static/app.js` 与旧全局样式；旧 `app.js` 源码文本断言一律不恢复，业务断言迁为 API / Node 纯逻辑 / 真浏览器行为测试。
- 决定：映射取证请求通道集中在 `deliverable/discovery.js`（向导与高级设置共用），可变 `discoveryLimits` 供测试压缩时限；
  终态文案用按交付物限定的待显示槽（面板卸载后写、重新挂载时取走）。
- 决定：候选预览与执行共用同一报表类型（预览必须逐字节等于执行写入）；NCR 科室范围只是绑定上的声明（`sectionScope`），不是查询键，
  不发送 `seccode`；取消端点不要求 `base_url`。
- 决定：不保留“表单明细用户列偏好”概念（现有表单明细表无该存储；系统查询网格的列偏好键不变）。

