# 方案：交付物看板精简 + ARAS PAA/NCR 按 EWO 结构统一（**待确认，未动任何代码**）

- 日期：2026-09-25
- 输入：用户 4 张截图 + 4 条诉求；只读代码取证；本地库只读核查；外部顾问（Codex `sol-xhigh`）一次第二意见
- 状态：问题分析与架构方案已完成，**等用户逐项确认后才动工**
- 本轮唯一写入物：本文件；过程证据在 `.runtime/shots/plan-20260925/`（截图、OCR、像素定位）与 `.runtime/db_state.txt`（只读库核查）

---

## 实施状态（2026-09-25 实施轮，用户已批准全部决策）

用户答复「全部同意实施」，5 项决策全部按建议执行：P0 与 P1+P2+P3 均已落地（P1/P2/P3 合并为一次改动，符合顾问"不得留下中间态"的裁决）。

### 已实施范围

| 项 | 内容 | 关键落点 |
| --- | --- | --- |
| P0-a | 能力注册表新增 `boardVisible`（D1/D4 为 False）+ `project_status_board_visible()`；payload 新增 `boardVisible`（**不改动** `deliverables` 全量字段） | `core/project_status_contracts.py`、`web/app.py` |
| P0-b | 两块看板按后端投影过滤：`deliverableBoardVisible()` + 卡片/明细行过滤 + 自动隐藏计数排除 | `web/static/app.js` |
| P0-c | 删除首页「外部业务快照 / PAA·NCR 外部源进度（参考）」面板（渲染函数、状态判定、定义/缓存、加载器、调用点、CSS 全块） | `web/static/app.js`、`web/static/style.css` |
| P0-d | 删除「外部快照·参考」徽标（函数、卡片用法、明细行用法、CSS） | 同上 |
| P1 | 能力注册表新增 `supportsRecordSet`/`completenessPolicy`/`defaultDepartment`/`filterKeys` + 四个查询 helper；**移除 5 处 `VPI-T2-D3` 硬编码**（连接器、sync_runner form_key 回退、discovery、updates×2、web 路由与规则构建、前端绑定模式选择、分析 `_is_ewo_deliverable`） | `core/project_status_contracts.py`、`services/project_status_connectors.py`、`services/project_status_sync_runner.py`、`services/project_status_discovery.py`、`services/project_status_updates.py`、`services/project_status_deliverable_analysis.py`、`web/app.py`、`web/static/app.js` |
| P2-a | 新增共享解析模块 `services/aras_ncr_workbook.py`（唯一解析口径，消除连接器对归档模块私有函数的跨模块调用） | 新模块 |
| P2-b | 归档路径由「位置行」改为与同步路径同形的「按已批准表头标签命名」的行；`_SOURCE_FIELDS_BY_REPORT` 为 NCR 派生标签键映射；NCR 命名行复用同一套 NCR 维度/成本口径 | `services/scheduled_archive_connectors.py`、`core/report_contracts.py`、`services/deliverable_form_analysis.py` |
| P2-c | NCR 准入 fail-closed：`WorkbookBookkeeping` + `decide_workbook_outcome()` 进入完备性词表唯一拥有者；同步路径 `require_complete_workbook()`；归档路径以 `form_projection_error` + manifest 簿记事实披露 | `services/pagination_integrity.py`、`services/aras_ncr_workbook.py`、两个 collector |
| P3-a | 分析来源标签限定：`analysis_source_type()` → `aras_ewo` / `aras_paa` / `aras_ncr`，EWO 阶段机不再外溢到 PAA/NCR（裸 `"aras"` 仅保留为历史缓存兼容） | `services/project_status_deliverable_analysis.py`、`services/project_status_sync_runner.py` |
| P3-b | 删除不可达的第二套「快照同步卡」（`renderSnapshotSyncCard`/remedy 词表/加载分支/CSS）——同步入口只按 `syncCapable` 判定 | `web/static/app.js`、`web/static/style.css` |

### 实施中发现并修复的两个既有缺陷（P2 的必要前置）

1. **`ncr_detail` 列标签行错位**：`core/report_headers.json` 的 `dataHeaderRow=4` 指向车型矩阵带（TBD/车型号），使列标签全部落空、按标签取值（状态/区域/项目/NCR编号）必然失败；官方工作簿解析一直用 `headerRows[0]`（稳定 17 命名列 + 矩阵列）。已改为 `dataHeaderRow=0`，与解析口径对齐（`tests/test_report_contracts.py` 相应断言已更新，并新增 17 列非空与关键标签校验）。
2. **`matchKeys` 与连接器实际消费漂移**：新增的 `filterKeys` 一致性测试（按"单个声明键必须改变过滤器 + 未声明探针键不得改变过滤器"判定）发现 D6 声明了连接器从不消费的 `sectionCode`，而 D6 缺 `rspDepartment`、D7/D8 缺 `sectionCode`/`section_code`/`rspDepartment`/`changeType`。已按连接器实际消费修正注册表（D6 移除未消费的 `sectionCode`）。

### 与方案的偏差（已记录，均更保守）

- **未实现"与上次快照行数对比的报警"**：EWO/PAA 亦无该能力，为避免为诊断引入跨层依赖，本轮保持与 EWO 结构一致；行数事实已随 manifest 与快照披露，可直接用于生产证据校准。
- **未按身份（业务单号）拒绝 NCR 行**：NCR 明细可能存在合并单元格等形状，无生产样例前不做身份级拒绝（否则可能把 NCR 明细判成永不完整）。准入只做结构性判定：表头契约、逐行归类核对、未截断、契约列内非空。
- **准入语义如实声明**：`workbook_rows` 只表示"满足准入策略"，**不表示证明源端零丢失**（NCR 工作簿没有声明总数）。
- **未新增数据库迁移**：契约版本与簿记事实写入既有 JSON 字段（manifest / schema_json）。

### 验收证据

- 新增/更新聚焦测试：`tests/test_aras_ncr_workbook.py`（9 例）、`tests/test_pagination_integrity.py`（工作簿准入矩阵）、`tests/test_project_status_contracts.py`（元数据 + filterKeys 一致性）、`tests/test_ewo_department_stage_feature.py`（EWO 语义不外溢）、`tests/test_overview_web.py`（看板可见性 + 移除契约）、`tests/test_deliverable_form_analysis.py`（命名行与位置行归一化等价）、`tests/test_scheduled_archive_connectors.py`（准入失败分支不落库部分投影）。
- 全量门禁与静态检查结果见 `memory/CURRENT_STATE.md` 本轮条目。

### 独立复核（对抗式 code review）结论与处置

独立只读复核（另一个 agent，未跑测试）结论：**0 Blocker**，1 Major + 2 Minor + 1 Nit，其余逐项核实通过（看板投影一致性、payload 下标、注册表取代硬编码、工作簿簿记等式、两写者形状与读取兼容、`dataHeaderRow` 改动无其他消费者、来源标签限定与发布修订守卫）。处置如下：

| 级别 | 发现 | 处置 |
| --- | --- | --- |
| Major | NCR 同步路径在内存按部门再收窄（归档路径不做），两条写入路径的**行集合**仍可能不同；且 `区域/采购科室` 为空的行被静默丢弃（该过滤在准入门之后，准入簿记覆盖不到） | **部分修复 + 显式延后**：抽出 `_filter_ncr_rows_by_department()` 纯函数并返回丢弃行数；丢弃数经 `core.diagnostic_recording.emit("ncr_department_filter", {kept, dropped, departmentScoped})` 进入诊断渠道（不再静默），并加测试核对 `kept/dropped`。**行集合口径统一（归档 vs 绑定）仍按原计划延后**：归档侧用 `sectionCode/sectionCodes` 上游查询、绑定侧用 `department` 再收窄，语义不同；未拿到生产样本前删除内存收窄会静默放宽范围，属不可接受的静默行为变更。已列入执行前沿第 ④ 项。**（本载荷键已在下方「对抗式复核缺口闭环」中修正为 `kept_count`/`dropped_count`——原键不在录制白名单内，实测被投影成 `{}`，等于没有披露。）** |
| Minor | `web/static/app.js` 仍用 `["VPI-T2-D1","VPI-T2-D4"].includes(item.id)` 兜底同步能力 | 已改为 `capabilities.syncCapable === true`（能力缺失即不支持，fail-closed），两处（分析动作条与证据同步条）均已改。 |
| Minor | `sourceInfo.defaultDepartment` / `completenessPolicy` 下发但前端未消费 | 已补两个真实消费者：向导「责任部门」预填/占位/说明改用 `sourceInfo.defaultDepartment`（非 TDC 且注册表未声明时保留历史预填值，**不改变 EWO 既有查询范围**）；同步摘要卡在 `completenessPolicy === "workbook_admission"` 时展示准入语义说明（"complete 只表示满足准入策略，不构成源端零丢失的证明"）。 |
| Nit | 连接器内 `_PAA_DELIVERABLE_ID = "VPI-T2-D6"` 仍是一个 id 字面量 | 保留：它是注册表查询的键而非行为分支，且注释已说明来源。 |

---

## 审计修复轮（2026-09-25 晚，ZCode 代码审计报告处置）

外部审计（ZCode 只读审查，5 域分域审阅 + 逐项复核）结论：**有条件通过**（49 文件 / +3492−970），1 Major + 4 Minor + 3 Nit；另报的"分页 95% 阈值 Blocker"经核实属 2026-09-23 轮既有待授权项，非本轮回归。本轮的 Major 我在代码上逐环独立复现后修复，Minor/Nit 一并收口。

### Major：NCR 进度 11 组重复表头标签使「办理时间」被「执行人」静默覆盖

**复现（独立于审计报告）**：

1. `core/report_headers.json` 的 `ncr_progress.headerRows[1]`（dataHeaderRow=1）共 64 个标签，其中 11 个角色标签各出现 **两次**：`37..47` 与 `52..62`；父表头 `[36]="办理时间"`（合并块 36..51）、`[52]="执行人"`（合并块 52..63）。`ncr_detail`/`ewo`/`paa`/`tdc_*` 的 dataHeaderRow 均无重复标签。
2. 解析器用 `{label: values[index]}` 后写覆盖先写 → 字典里这 11 个键保留的都是执行人姓名；`named_row()` 只发布这个字典，位置视图不落盘（`services/aras_ncr_workbook.py`）。两条写入路径（同步 `project_status_connectors._collect_ncr_rows`、归档 `scheduled_archive_connectors._collect_ncr`）都发布该形状。
3. 读取侧按标签还原位置视图（重复标签两列取到同一个值）→ 阶段日期按标签命中列 37 → 已被人名覆盖。
4. 声称守护等价性的 `test_label_named_ncr_rows_normalize_identically_to_positional_rows`（**本轮已删除**）夹具只有单组日期、无执行人列 → **空过**（审计结论成立）。现由两条非空测试替代：
   `test_duplicate_label_ncr_rows_restore_all_stage_dates_via_positional_view`（真实契约两组夹具，11 个日期全还原 + 与位置行逐字段一致 + rowKey 不变）与
   `test_legacy_label_only_ncr_rows_disclose_ambiguous_columns`（历史行降级行为 + 有界诊断钉住）。

**实测影响（比审计描述更严重）**：修复前不是"日期解析失败/未判定"，而是**所有节点被系统性误判为逾期**。对同一份数据逐个节点对比：

| 当前节点 | 修复前 start/end/state | 修复后 start/end/state |
| --- | --- | --- |
| NCR管理员 | 2026-08-20 / None / **overdue** | 2026-08-21 / 2026-08-22 / on_time |
| PE科室经理 | 2026-08-20 / None / **overdue** | 2026-08-22 / 2026-08-23 / on_time |
| 价值工程师 | 2026-08-20 / None / **overdue** | 2026-08-23 / 2026-08-24 / on_time |
| 财务部总监 | 2026-08-20 / None / **overdue** | 2026-08-31 / None / on_time |

（`stageStart` 全部退回 PE填写 日期、`stageEnd` 全部丢失 → 前两个节点 3 天/其余 7 天的逾期窗口全部越界。）复算脚本：`.runtime/compare_ncr_legacy_vs_fixed.py`。

**顾问裁决（Codex `sol-high`，一次咨询）**：采纳方案 A，附三条约束——①先确认命名行约定允许增量键；②身份计算保持修复前语义；③历史无位置视图的行保留原读取边界并有界披露、不得标为已修复；④把"契约存在重复标签"做成守护测试。四条已全部落地。

**修复**：

| 层 | 改动 |
| --- | --- |
| 解析器 | `NcrWorkbookRow.named_row()` 额外携带契约顺序的位置视图 `values`（标签字典继续保留，供按标签取值的消费者使用）；模块 docstring 声明"同名标签时位置视图是唯一无损来源" |
| 读取侧 | 位置数组存在即走原有的位置优先分支（不新增第二套归一化）；NCR 行身份统一为 `_ncr_row_identity()`（优先 `NCR编号` 标签、否则前 10 列拼接）→ **带不带位置视图的同一行 rowKey 不变**，修复不改变行身份语义 |
| 诊断 | 只带标签键的历史行命中 `_duplicate_data_header_labels()` 时，单次归一化 `emit("forms.ambiguous_header_labels", {reportType, formKey, rows, ambiguousLabels(≤32), remedy:"reproject_from_archived_workbook"})`（有界、非敏感）。**载荷键随后修正为 `{report_type, row_count, remedy}`**（原键不在录制白名单内会被整体丢弃，见下方缺口表） |
| 守护测试 | 契约层锁定 11 组同名标签的索引与父表头语义；解析层锁定位置视图权威；读取层用真实契约夹具（日期组 + 执行人组）锁定 11 个日期还原，并锁定历史行的降级行为与诊断 |

**遗留（已声明，未修）**：历史快照里那 11 列**已不可逆**合并，本修复不回填。注意两条读/写边界：
- **读取旧快照不会重新归一化，因而不会产生任何诊断**（`normalize_form_rows` 的生产唯一调用点是发布路径
  `build_form_snapshot`，快照读取路径直接用已存行的字段）；旧快照只会原样返回旧的错误 `stageStart/stageEnd/overdueState`。
- 补救只能**重新同步**（归档保留官方 XLSX 原件）。诊断只在"某个不带权威位置视图的行被归一化时"触发，
  即发布/重投影路径，属于"以后别再写出这种行"的护栏，不是历史数据的读时提醒。
- 未来若新增"从归档重投影"路径，**不得把库里历史行的 `values` 当权威**——那正是被覆盖值还原出来的污染数据，
  必须从归档的官方工作簿重新解析。

### 对抗式复核（针对本轮修复）发现并已闭环的两处缺口

| 级别 | 发现 | 处置 |
| --- | --- | --- |
| Major | 披露事件的载荷被录制层整体丢弃：`core/diagnostic_recording.safe_metadata` 只白名单转发固定键与闭集文本值，`emit` 的 `{reportType, formKey, rows, ambiguousLabels, remedy}` 实测投影成 `{}`；上一轮的 `ncr_department_filter` 的 `{kept, dropped, departmentScoped}` 同样为 `{}` → "记录了"不等于"可运维读取" | 已修：`safe_metadata` 白名单新增 `kept_count`/`dropped_count`（数字）、`report_type`/`remedy`（文本）与闭集词条 `reproject_from_archived_workbook`；两处 emit 改用可转发键。新增端到端回归测试：经 `Recorder` 录制并导出后，两个事件的 `data` 必须可读 |
| Major（表述） | 文档声称"读旧快照会记录诊断"，与实际不符（读取路径不触发归一化） | 已修：方案文档、`memory/CURRENT_STATE.md`、r2/r3 说明文件统一改为"旧快照不回填、读时不诊断、必须重新同步" |
| Minor | 标签还原分支对重复标签取**最后一次出现**（执行人），而阶段日期按标签解析命中**第一列**（办理时间）→ 历史行会把执行人姓名写进办理时间列（列渲染按位置取值，用户可见） | 已修：`_ncr_header_mapping_values()` 新增 `ambiguous_labels` 形参，同名列一律不还原（留空）→ 宁可"未判定"也不产生错误日期；测试锁定 11 组两列全为空且 `searchText` 不含执行人 |
| Nit | 复核认为 `ncr_detail` 的行身份语义发生变化 | **经 diff 核实为误判**：`_no/id/keyed_name` 那一组是未被触碰的第三个（映射）分支；NCR 标签分支在修复前本来就是 `NCR编号` 优先，`_ncr_row_identity()` 与其逐字等价，位置分支仅在"行同时带标签键"（即新命名行）时生效，而那正是修复前走标签分支的同一批行 → 无身份变化 |

### Minor / Nit 处置

| 级别 | 发现 | 处置 |
| --- | --- | --- |
| Minor | EWO 写入侧仍用裸 `"aras"`，与 `is_ewo_source_type` 文档声明的"新写入必须用限定标签"相悖 | 已修：`_ARAS_REPORT_SOURCE_TAGS` 增加 `"ewo": "aras_ewo"`，写入侧 EWO 亦为限定标签；裸 `"aras"` 仅保留为历史缓存读取兼容（`is_ewo_source_type` 两值皆真，读取语义不变） |
| Minor | `decide_workbook_outcome` 负数守卫只覆盖 `read_rows/parsed_rows`，其余计数为负可让账目等式"假平衡" | 已修：五个计数整组纳入守卫；新增"负值刚好配平也必须 fail-closed"的参数化测试 |
| Minor | `overviewDetailsRow` 兜底按 DOM 位置回退，可能展开被看板隐藏的 D1/D4 | 已修：渲染行一律带 `data-deliverable-index`，命中不到即返回 `null`（仅在完全无下标标记时才保留位置回退） |
| Minor | `VSE-WebUI-compact.spec` 未纳入版本控制却与 tracked 的 `VSE-WebUI.spec` 输出同名 `VSE-WebUI` | **未改动（用户资产待决）**：该文件是 2026-09-23 就存在的工作区未跟踪文件，属"与本轮无关的既有改动"，按协作约定不擅自改删。生产构建实际使用 tracked 的 `VSE-WebUI.spec`，本轮交付物 SHA-256 已可溯源。建议用户二选一：纳入 git + 改独立输出名，或删除。 |
| Nit | `aras_ncr_workbook.py` 的 `blank_rows += 0` 是无操作 | 已修：改为 `unclassified_rows += 1`——被读取却无法归类的行计入账目，等式仍成立（停机原因仍由 `row_rejected` 优先给出），并在 `WorkbookBookkeeping` 文档中写明该口径 |
| Nit | `test_project_status_contracts.py` 测试 docstring 与断言体不符 | 已修（`syncCapable=True` / `automatic`） |
| Nit | 连接器内 `VPI-T2-D6/D7/D8` 字面量 | 保留（注册表查询键，非行为分支） |

### 本轮验收证据

- 全量：**2403 passed, 3 skipped（exit 0）**（日志 `.runtime/full-suite-audit-fix-r3.txt`，
  基线 2398 → +5）；flake8 对本轮改动文件零告警（`tests/test_diagnostic_recording.py` 的 5 处
  E128/E306 是该文件既有告警）；`node --check web/static/app.js` 通过；项目地图 verified。
- 聚焦新增：契约守护（重复标签索引与父表头语义）、解析层位置视图权威性、读取层 11 个日期全还原
  （原空夹具测试已改为非空）、历史行降级与"同名列不还原"、披露载荷经 Recorder 录制导出后 `data` 可读、
  负数假平衡、写入侧两条路径均携带位置视图。
- 交付包：`dist/hci-20260925-r3/`（EXE 21,427,466 B，SHA-256 `95c36af7…92df`；
  ZIP 21,089,326 B，SHA-256 `5ca5e6f3…c0ea`），出厂冒烟 30/30 通过；
  `dist/hci-20260925/` 与 `dist/hci-20260925-r2/` 已标记作废。

---

## 0. 结论摘要



1. **第 1、2、3 项是"展示层收口"**，与第 4 项没有代码耦合，可以独立成一次小改动（P0），单独验收、独立回退。
2. **第 4 项不是 UI 问题，而是链路结构问题**。D6-D8 在注册表里已经被标成"可同步"，但底层仍然是**三套**查询/身份/快照形状；其中 NCR 这条链路存在三个硬缺陷：
   - NCR **完全没有完备性门**（EWO/PAA 走 `_require_complete_result`，NCR 不走）；
   - 同一交付物的快照有**两条写入路径且形状不同**（同步路径写"命名行"、归档路径写"位置行"），而读取按 `snapshot_at DESC` 取最新 → **谁最后写，快照形状就翻转**；
   - `_SOURCE_FIELDS_BY_REPORT` **没有 NCR 条目**，命名行归一化会退化成全 None。
   再加上 `_EWO_SOURCE_TYPES` 里的裸 `"aras"` 让 PAA/NCR 被按 EWO 语义评分、版本化契约在 5 处硬编码 `VPI-T2-D3`、`syncCapable` 分支把 `formSnapshotDriven` 分支变成死代码——这就是"EWO 两种模式都 OK，NCR/PAA 结构差异很大"的机制性原因。
3. **外部顾问第二意见**（`codex-readonly` / `sol-xhigh`，package SHA-256 `762d7180…3e23ae`）：方案方向可行，但 **P1/P2/EWO 语义隔离必须同次上线**（P0 可独立）；NCR 完备性应取"工作簿准入 + 逐行校验 + 读取/解析/拒绝数核对"，**不得据工作簿宣称源端全量**；D1/D4 必须用**服务端看板投影**而不是过滤原接口字段；必须显式处理**双写者竞争覆盖**。我已逐条独立复核并裁决（见第 5 节）。
4. 需要用户拍板的事项收敛为 **5 条决策**（见第 6 节）。

---

## 1. 取证方法与截图解读（可复现）

截图本身无法直接机读，我用了三步取证，结论与用户的补充确认一致：

1. **OCR**（Windows.Media.Ocr，`zh-Hans-CN`）取文本与坐标：`.runtime/shots/plan-20260925/box-img*.txt`。
2. **手绘标注像素定位**（红色连通域 + 端点密度判定箭头头部）：`.runtime/red_components.ps1`、`.runtime/arrow_head.ps1`。结果：
   - 图1（1329×1052，首页「状态总览」）：红线主要簇位于 (244,522)–(350,599) 与 (811,579)–(950,674)，后者与 5 列卡片网格第 4 列（D4 造型 VDR 审批流程，环形 90%）重合；用户随后明确：**要取消的是 D1 + D4 两张卡片**。
   - 图2（1130×318）：无箭头，就是首页底部「外部业务快照 / PAA · NCR 外部源进度（参考）」面板特写。
   - 图3（1185×611，「交付物明细」表）：两个手绘箭头，箭头端分别落在第 1 行（D1 子系统开发策略，y≈103）与第 4 行（D4 造型 VDR 审批流程，y≈291）的"交付物"列内；**用户确认：删除这两行**。
   - 图4（1188×593）：同一张明细表，红框 (30,398)–(478,571) 圈住 D6/D7/D8 三行 → 即第 4 项重构的对象。
3. **只读代码/库取证**：关键行号见下；本地库（`data/vse_toolbox.db`）只读核查结果：

```text
project_status_update_bindings : D1..D8 全部 enabled=0 / credential_ref=NULL / match_rule={} / mapping={}
project_status_sync_runs       : 0 行
project_status_mapping_observations : 0 行
scheduled_archive_jobs         : 6 个全部 enabled=0 / credential_ref=NULL
scheduled_archive_runs         : 0 行
deliverable_form_snapshots     : 仅 3 条（tdc_data_model / aras_ncr_progress / tdc_sor，来源均为归档任务，非同步路径）
```

> 含义：**本地库从未跑通任何一条交付物绑定同步**；用户所说"EWO 立即同步/自动同步都 OK"来自生产环境。因此 P2 的验收不能只看本地库，需要生产复测（见 4.6）。

交付物编号对照（务必对齐，后面全部用 D 编号）：

| 编号 | 名称 | 来源 | 本次动作 |
| --- | --- | --- | --- |
| D1 | 子系统开发策略 | 内网（手工，100%） | 看板不展示 |
| D2 | SOR 定点流程 | TDC SOR | 不变 |
| D3 | EWO 流程 | ARAS EWO | **重构模板** |
| D4 | 造型 VDR 审批流程 | TDC A 面（契约待验证，90%） | 看板不展示 |
| D5 | 数模审批流程 | TDC 数模 | 不变 |
| D6 | PAA 报告 | ARAS PAA | 按 EWO 结构重构 |
| D7 | NCR 审批进度 | ARAS NCR | 按 EWO 结构重构 |
| D8 | NCR 审批明细 | ARAS NCR | 按 EWO 结构重构 |

---

## 2. 第 1 / 3 项：D1、D4 从两张看板收口

两项同源（同一份 payload、同一批交付物对象），合并为实现单元。

### 2.1 现状与落点

- 数据来源：`GET /api/project-status?phase=VPI-T2`（`web/static/app.js:8443`）→ `web/app.py:4163` → `_project_status_payload`（`web/app.py:2004`）。**不是** `/api/overview`（该路由只返回旧口径计数，前端被测试禁止调用，`tests/test_overview_web.py:125,201`）。
- 首页卡片：`renderDeliverableProgress`（`app.js:1032-1129`）→ `#overview-progress-grid`（`web/templates/dashboard.html:94`）。
- 明细表行：`renderDeliverableDetails`（`app.js:8222-8307`）→ `#overview-details-body`（`dashboard.html:125`）。
- 行序固定为 D1→D8（`core/db_manager.py` 种子 `1614-1623`，读取 `ORDER BY sort_order, id`），与截图行序一致。

### 2.2 方案（采纳顾问意见：服务端看板投影，不改原接口语义）

1. **单一来源**：在能力注册表 `core/project_status_contracts.py`（`PROJECT_STATUS_SOURCE_CAPABILITIES`，`489-720`；D1 在 `490-504`、D4 在 `575-589`，两条都已注册、均为 `syncCapable=False`）为每个交付物增加看板可见性元数据（如 `boardVisible: False` 仅 D1/D4），并从该字段派生看板投影，避免在前端按 id 硬编码。
2. **服务端投影**：`_project_status_payload` 在**不删除、不改写** 原 `deliverables` 字段的前提下，新增看板投影字段（例如 `board: { deliverables: [...] }`，或每项附 `boardVisible` 且由后端按注册表派生）。
3. **前端**：两处看板渲染器只消费投影；D1/D4 的详情页、分析接口、审计记录、`/api/project-status` 全量语义**全部保持不变**。
4. **明确不动统计口径**：首页卡片区标题下没有汇总数字；明细页摘要（`app.js:1459-1476`）只有"当前阶段/阶段状态/总体进度/阶段周期" + 同步控制条，**不按交付物计数**。因此 D1/D4 是否仍参与"完成度/价值态"统计需要用户明确——**我建议保持不变**（本次只改"看不看得见"）。

### 2.3 影响与测试

- 需要同步更新的断言：`tests/test_overview_web.py`（卡片/表结构、CSS 选择器 pin）、`tests/test_project_status_api.py`（payload 形状）、`tests/test_deliverable_registry.py`（五方一致闭包）、`tests/test_deliverable_statistics.py`（若引用了卡片徽标契约）。
- 不新增 HTTP 契约破坏：新字段是**追加**。

---

## 3. 第 2 项：删除「外部业务快照」面板与「外部快照·参考」徽标

### 3.1 待删集合（已核对到行）

| 对象 | 位置 |
| --- | --- |
| 面板渲染 | `app.js:1207-1283`（`renderOverviewBusinessSnapshots`） |
| 状态判定 | `app.js:1131-1205`（`overviewBusinessSnapshotCondition`） |
| 定义与缓存 | `app.js:258-282`（`OVERVIEW_BUSINESS_SNAPSHOT_DEFINITIONS` 等） |
| 加载器 | `app.js:8309-8340` + 调用点 `app.js:8381`、`8461` |
| 样式 | `style.css:7499-7623`（含 7636-7639 媒体查询） |
| 徽标函数 | `app.js:1016-1021`（`deliverableSnapshotBadge`），使用点 `app.js:1121`（卡片）、`8272-8275`（明细行） |
| 徽标样式 | `style.css:8289-8302`（`.snapshot-driven-badge`） |
| 测试 | `tests/test_overview_external_deliverables_ui.py:10`；`tests/test_deliverable_statistics.py:404-410`（徽标文案 pin） |

### 3.2 必须保留的部分（避免误删共享依赖）

- `overviewArchiveJobs`（来自 `GET /api/scheduled-archive/jobs`）仍被归档明细页使用（`app.js:7879`、刷新 `13415`）→ 只删面板，**不删**该状态。
- `GET /api/deliverable-forms/{formKey}/view` 仍被交付物明细页使用（`app.js:6408`）→ 保留。
- `item.formSnapshotDriven` 能力标志本身保留（它仍驱动展示状态机与"不计入分母"），只是**不再渲染徽标**。

> 注意口径：用户选择的是"删徽标 + 删面板"，**不是**改变"外部快照仅参考、不计入分母"的语义（`countsTowardCompletion=False` 保持，见第 6 节决策 4）。

---

## 4. 第 4 项：PAA / NCR 按 EWO 结构重构

### 4.1 "EWO 的整体结构"是什么（这条流水线才是模板）

```text
①凭据绑定(统一域账号) → ②映射取证/确认(2/2) → ③保存并启用策略
→ ④立即同步(run_once) / ⑤定时同步(scheduler tick)
→ ⑥取命名行 + 完备性门 → ⑦构建并发布表单快照 → ⑧归一化 → ⑨明细/图表/看板
```

| 层 | EWO 实现 | 文件锚点 |
| --- | --- | --- |
| 能力契约 | `reportType=ewo`、`aggregate`、`plannedDateSupported`、matchKeys/matchFields/defaultMapping/fieldAliases，且支持**版本化绑定**（`contractVersion`/`bindingMode`/`sourceItemId`） | `core/project_status_contracts.py:543-574` |
| 查询 | `build_project_status_ewo_filters()` → `crawl_ewo_report_all()`（分页行） | `services/project_status_connectors.py:313,371`；`services/aras_crawler.py:224-239` |
| 完备性门 | `_require_complete_result()`：`complete is True` 且 `stop_reason ∈ COMPLETE_RESULT_STOP_REASONS`，否则 raise | `services/project_status_connectors.py:69-83` |
| 身份/聚合 | 共享身份构造（`services/project_status_records.py`），默认部门表达式在共享身份侧 | `services/project_status_records.py:28-32`；`web/app.py:1225-1234` |
| 快照 | `contractVersion` → `_ewo_v2_snapshot`（记录集合/固定单条）；否则 aggregate | `services/project_status_connectors.py:107-152` |
| 发布 | 同步路径与归档路径都发布**同一 form_key**（`VPI-T2-D3`） | `services/project_status_sync_runner.py:508-532`；`services/scheduled_archive_runner.py:500-526` |
| 归一化 | `_SOURCE_FIELDS_BY_REPORT["ewo"]` 全字段契约 + 变换表 | `core/report_contracts.py:173-178` |
| UI | 同一套绑定编辑器（含版本化绑定模式选择）| `app.js:2330`、`2420-2437` |

### 4.2 差距表（D3 vs D6/D7/D8）

| 维度 | EWO (D3) | PAA (D6) | NCR (D7/D8) | 差距性质 |
| --- | --- | --- | --- | --- |
| 注册表能力 | syncCapable + aggregate + 版本化契约 | syncCapable + aggregate + `formSnapshotDriven` | 同 D6 | 显示分叉 + 无版本化契约 |
| 查询路径 | 分页行查询 | 分页行查询（`crawl_paa_report_all`） | **无行查询**：官方 XLSX 导出 → 下载 → 解析 | **结构性** |
| 完备性门 | 有 | 有 | **无** | **正确性缺口** |
| 过滤器来源 | 共享 builder（discovery 与执行同源） | 连接器内 `_paa_filters`，**默认部门硬编码** `技术中心_车体工程`（`:403`） | 连接器内 `_ncr_filters`，`sectionCode`/`projectNames` 语义与 matchKeys 声明不符 | 三套口径 |
| 行形状 | 命名行 | 命名行 | 同步路径**命名行**（`:445-454`）／归档路径**位置行**（`scheduled_archive_connectors.py:310-380`） | **同交付物双形状** |
| NCR 解析归属 | — | — | 连接器跨模块调用归档模块的私有 `_official_form_rows`（`:430`） | 模块边界破损 |
| 归一化 | 有契约 | 有契约 | `_SOURCE_FIELDS_BY_REPORT` **无 NCR 条目** | **数据空洞** |
| 分析语义 | EWO 阶段/逾期 | 被 `_EWO_SOURCE_TYPES` 裸 `"aras"` 误当 EWO | 同 D6 | **语义污染** |
| 绑定口径 vs 归档口径 | 一致 | 一致 | 归档键集远宽于绑定 matchKeys；归档无默认部门（`scheduled_archive_runner.py:295-298`） | 人群不一致 |
| UI 决策分支 | `syncCapable` | `syncCapable` 先返回 → `formSnapshotDriven` 分支死代码（`app.js:3176` vs `3211`） | 同 D6 | 死代码 + 不可扩展 |

### 4.3 为什么"立即同步/自动同步"在 NCR/PAA 上不可靠（机制合成）

1. **NCR 缺完备性门**：EWO/PAA 在 `_require_complete_result` 上 fail-closed；NCR 直接采信工作簿解析结果 → 上游导出少行、表头漂移、截断都可能被当成"完整"写进快照（`services/project_status_connectors.py:428-488`）。
2. **快照形状随最后写入者翻转**：读取按 `ORDER BY snapshot_at DESC, id DESC LIMIT 1`（`core/db_manager.py:2502,2518`），写入是 append（`:2235-2298`）。同步路径写命名行、归档路径写位置行 → 同一 D7 的分析结果取决于谁最后跑。
3. **命名行归一化空洞**：`_SOURCE_FIELDS_BY_REPORT` 只有 `ewo/paa/tdc_*`（`core/report_contracts.py:173-178`）；`services/deliverable_form_analysis.py:1030-1082` 里位置行走 `_dimensions_from_ncr()`（可用），命名行落到 `table_payload()` 分支 → 全 None。
4. **EWO 语义污染**：`services/project_status_deliverable_analysis.py:50` 的 `_EWO_SOURCE_TYPES` 含裸 `"aras"`，而 D6-D8 的 `sourceType` 正是 `"aras"` → PAA/NCR 分析项按 EWO 阶段/逾期语义评分。
5. **结构不可扩展**：版本化契约在 ≥5 处硬编码 D3（`app.js:2420-2437`、`web/app.py:1207-1210`、`project_status_connectors.py:135`、`project_status_updates.py:906,1068`、`project_status_discovery.py:98-116`）；`app.js:3176` 的提前 return 让 `renderSnapshotSyncCard`（`2988-3130`）成为死代码，也说明"注册表已升级、链路没升级"。

> 一句话：**D6-D8 只升级了"注册表与入口"，没升级"取数与归一化"**；EWO 之所以两种模式都好用，是因为它只有一条形状固定的通路。

### 4.4 方案 A（推荐）：元数据驱动的统一链路

**P0（独立交付，展示层）**：第 1/2/3 项看板收口。与重构无耦合，先落地先验收。

**P1（契约层统一，行为等价重构）**

- 能力注册表升级为"每交付物同步契约"单一来源：`rowContract`（命名行来源：API 行 / 官方工作簿列映射）、`identityKeys`、`completenessPolicy`、`defaultDepartment`、`filterKeys`（**由连接器过滤器 dataclass 派生**，消灭 matchKeys 与实现的漂移）、`boardVisible`、`supportsRecordSet`。
- 删除 5 处 `VPI-T2-D3` 硬编码：版本化分支改为 `supportsRecordSet` 元数据；`project_status_sync_runner.py:508-511` 的 EWO 回退改为纯注册表查表。
- 连接器统一为一条流水线：**取命名行 → 完备性门 → `_snapshot`**；`_paa_filters`/`_ncr_filters` 与 discovery 侧共用同一 builder。

**P2（NCR 行契约与完备性，同次上线）**

- 新建共享的 NCR 工作簿解析模块（把 `_official_form_rows` 从归档模块抽出），**同步路径与归档路径调用同一函数、产出同一命名行形状**（消除模块边界破损与双形状）。
- 补 `_SOURCE_FIELDS_BY_REPORT` 的 `ncr_progress`/`ncr_detail` 字段契约与必要变换。
- **NCR 完备性门**：见 4.5。
- 快照加"行契约版本"标记（建议放进 `schema_json`，避免数据库迁移），读取侧对旧形状显式降级而不是静默产出空分析。

**P3（语义隔离与清理，同次上线）**

- `_EWO_SOURCE_TYPES` 去掉裸 `"aras"`、改为按 `report`/交付物判定。
- 删除死分支 `renderSnapshotSyncCard` 与其源码字符串断言测试；统一"同步入口只按 `syncCapable`、`formSnapshotDriven` 只管展示状态机"。
- 补齐聚焦测试与文档（`docs/USER_GUIDE_STANDALONE_EXE.md` 相关小节、`memory/`）。

**为什么 P1+P2+P3 必须同次上线**（采纳顾问意见）：只做 P1 会形成"契约已统一、NCR 仍写位置行且无完备性门"的中间态，而该中间态**比现状更危险**（统一向导会让用户以为 NCR 与 EWO 等价）。

### 4.5 NCR 完备性设计（顾问三选一，我的裁决）

前置事实：NCR 是"官方工作簿导出"，**表格里没有声明总数/页数**（EWO/PAA 有分页元数据）；工作簿有固定表头契约（`core/report_headers.json`；`ncr_progress` 用 `headerRows[1]`，`ncr_detail` 用 `headerRows[0]`），`_official_form_rows` 目前对 progress 做**全表头全等**校验、对 detail 做前 17 列必需子集校验。

- 候选 (a)：表头契约 + 逐行校验 + **读取/解析/拒绝数核对**；不明丢行即 fail-closed；与上次快照行数对比只做诊断不阻断。
- 候选 (b)：若工作簿含汇总 sheet 则作声明值，缺失即判非完整。
- 候选 (c)：以"块/sheet"为簿记单位沿用 TDC 口径。

**裁决：取 (a)，并在出现可信汇总值时再演进到 (b)；(c) 不足以证明行完整（不采纳）。** 理由：

1. (c) 的簿记只能证明"sheet 数一致"，无法排除 sheet 内丢行，属于"假完整性"。
2. (b) 依赖上游是否存在汇总 sheet（当前未见证据），现在采用会立刻把 NCR 判成"永不完整"。
3. (a) 的严格版本能给出**可核对的等式**：`读取行数 = 解析成功行数 + 空行跳过数 + 拒绝行数`，任一不明差额 → 不可信 → fail-closed；同时提供"本次/上次行数"诊断。这与既有语义一致——`complete` 只表示"满足准入策略"，不表示"证明源端零丢失"（与 `services/pagination_integrity.py` 的既有契约一致）。
4. **单一 owner 约束**：完备性判定与 `stop_reason` 词表仍归 `services/pagination_integrity.py`（该模块文档已声明它是唯一拥有者）。NCR 的新准入结果必须通过同一词表/判定函数表达，**不得**在连接器里另起一套"complete"语义。

**验收口径（如实声明）**：本次目标是"工作簿满足准入策略"，**不承诺与 EWO 同等的源端全量保证**（顾问意见，我采纳）。若上游导出自身少行，本地无法证明——这条会写进文档与 UI 文案，不静默掩饰。

### 4.6 双写者与幂等（顾问指出的风险，我采纳并具体化）

- 根因：快照是 append + "按 `snapshot_at` 取最新"（`core/db_manager.py:2502,2518`），两条写者（同步/归档）谁最后写谁生效。
- 措施：① P2 让两条路径产出**同一行形状**（首要）；② 快照内记录行契约版本，读取侧对旧契约显式告警/降级；③ 明确"归档任务与交付物绑定是两条独立入口"的语义，不允许归档路径用不同过滤器人群覆盖绑定路径的视图——归档键集与绑定 matchKeys 的差异需要在契约里显式声明并（建议）收窄到同一口径。
- 回归重点：连续"归档同步 → 立即同步 → 定时同步"后，明细/图表/统计三者一致，且不出现"行数忽多忽少"。

### 4.7 验收测试与命令（实施后执行）

- 聚焦：`pytest tests/test_project_status_*.py tests/test_deliverable_*.py tests/test_scheduled_archive_*.py tests/test_overview_web.py tests/test_aras_*.py -q`
- 全量基线：`pytest -q -p no:cacheprovider`（当前基线 2,360 passed, 3 skipped）
- 静态：`flake8 -j 1`（改动文件）、`node --check web/static/app.js`
- 地图：`python tools/generate_project_map.py --check`
- 冒烟：独立端口启动 WebUI，验证 `/`、`/api/version`、`/api/project-status`、`/api/deliverable-forms/{key}/view`、`/api/scheduled-archive/jobs`
- **生产复测（必需，本地库无法替代）**：D6/D7/D8 各做一次"配置 → 立即同步 → 看明细/图表"，并观察一次定时同步；回传每次的 `run_state/error_type/行数/stop_reason`。

### 4.8 方案 B（最小修补，不推荐，但若只想"尽快能用"是备选）

只补 4 个点：NCR 完备性门、命名行归一化契约、`_EWO_SOURCE_TYPES` 去裸 `"aras"`、D6-D8 默认部门。改动与回归范围小得多，但三套 filter/identity 与双形状保留，结构仍会继续漂移；与用户"参考 EWO 重构"的诉求不符。

---

## 5. 外部顾问第二意见与我（主代理）的裁决

- 调用：`codex-readonly` / `sol-xhigh` / caller `dsh` / task `vse-aras-formed-20260925`，一次 live 成功（exit 0，input 13,736 tok / output 1,898 tok），意见归档：`C:\Users\Lynch\.dsh\expert-advisor\runs\codex-readonly-20260925-170043-39e4d887.advice.md`。
- 顾问要点 → 我的裁决：

| 顾问意见 | 我的裁决 | 理由 |
| --- | --- | --- |
| 方案 A 可行；P1+P2+EWO 语义隔离同次上线，P0 独立 | **采纳** | 中间态"契约统一但 NCR 无门/仍双形状"比现状更危险 |
| 隐藏 D1/D4 应新增服务端看板投影，不能过滤原接口字段 | **采纳** | 原 `deliverables` 字段被详情页/分析/审计/多处测试消费 |
| NCR 取 (a)：表头 + 逐行校验 + 读取/解析/拒绝核对，不明丢行即失败；历史行数仅报警 | **采纳** | 给出可核对等式，且不制造假完整性 |
| 可信汇总值出现后再采用 (b)；(c) 不足以证明行完整 | **采纳** | (c) 只能证明块数一致 |
| 归档与同步竞争写入可能覆盖较新快照 → 需版本/时间戳 + 幂等规则 | **采纳并具体化** | 见 4.6；首要措施是统一行形状 |
| 不能承诺与 EWO 同等的源端全量保证 | **采纳并写入验收口径** | NCR 无声明总数，这是事实边界 |
| 缺失证据：NCR 导出是否有可信成功标志、稳定行键 | **部分已解决 / 部分转用户** | 表头契约已有（`report_contracts`/`report_headers.json`）；**稳定行键与导出成功标志仍需生产样本确认** → 列入第 6 节决策 3 的证据要求 |

- 我保留的独立判断（与顾问意见一致但不依赖它）：完备性词表必须继续由 `services/pagination_integrity.py` 单点拥有；P0 与 P1-P3 解耦上线。

---

## 6. 待用户确认的 5 项决策

1. **交付节奏**：建议 P0（三项看板精简）先独立落地验收，P1+P2+P3（统一重构）作为第二次改动一次上线。是否同意？还是希望 4 项一起改、一次交付？
2. **D1/D4 的边界**：确认"仅从两张看板移除"，**保留**其详情页、分析接口、审计与统计数据参与（即阶段/完成度统计不变）。若你希望它们也退出统计分母，请明确——那会改变口径，需要单独确认。
3. **NCR 完备性口径**：接受 4.5 的 (a)（表头契约 + 逐行校验 + `读取 = 解析 + 空行 + 拒绝` 等式，不明丢行 fail-closed，历史行数只做诊断）？另外**需要你提供 1 份生产 NCR 导出样例**（或脱敏行键清单）来确认稳定行键与是否存在导出成功标志。
4. **PAA/NCR 统计口径**：确认保持"不计入完成分母"（`countsTowardCompletion=False`）不变，仅删除参考徽标。若你其实希望 PAA/NCR 同步成功后**像 EWO 一样计入完成统计**，请明说，这会扩大改动范围。
5. **自动同步验收**：定时同步的端到端验收需要生产环境凭据（统一域账号）。是否按"本地/测试用合成数据 + 生产由你复测一次"的方式验收？

---

## 7. 预计变更文件清单（确认后才动工）

- P0：`web/static/app.js`、`web/static/style.css`、`web/templates/dashboard.html`（若需容器调整）、`core/project_status_contracts.py`（看板可见性元数据）、`web/app.py`（看板投影字段）、相关测试。
- P1-P3：`core/project_status_contracts.py`、`core/report_contracts.py`、`services/project_status_connectors.py`、`services/scheduled_archive_connectors.py`、新增 `services/aras_ncr_workbook.py`（共享解析）、`services/pagination_integrity.py`、`services/deliverable_form_analysis.py`、`services/project_status_deliverable_analysis.py`、`services/project_status_sync_runner.py`、`services/project_status_discovery.py`、`services/project_status_updates.py`、`services/aras_crawler.py`、`web/app.py`、`web/static/app.js`、测试与文档。
- 不变量：不启用任何同步/归档任务；不写入或修改凭据；不删除 D1/D4 数据；不改动 `countsTowardCompletion` 口径；不新增数据库迁移（优先用现有 JSON 字段承载契约版本）。

---

## 8. 风险登记

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| NCR 上游导出本身少行，本地无法证明 | 中 | 验收口径如实声明；行数诊断 + fail-closed 准入；生产复测 |
| 双写者覆盖导致明细/图表口径漂移 | 中 | P2 统一行形状 + 契约版本标记 + 连续三入口回归 |
| 统一重构触及 2,360 例测试中的大量字符串断言 | 中 | 分期、先补/改断言再改实现；全量门禁 |
| 删徽标/面板被误解为"取消外部快照能力" | 低 | 文档与本次方案明确：只删展示，能力与快照链路保留 |
| 生产环境 D6-D8 绑定凭据仍未配置 | 中 | 交付物页向导一次性配置；不预置任何凭据 |

---

**下一步**：请在上述 5 项决策上给出结论（尤其是决策 1 的交付节奏与决策 3 的 NCR 完备性口径）。确认后我按分期实施，并在每期完成后给出聚焦测试 + 全量门禁 + 生产复测清单。
