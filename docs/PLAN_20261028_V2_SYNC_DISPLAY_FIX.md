# 2026-10-28 v2 同步三问题修复方案（Claude 顾问已评审 · 2026-10-29 已实施）

> 状态：**三批全部落地**，全量回归 3429 passed / 6 skipped（基线 3418/6），
> `generate_project_map.py --check` 通过。实施记录见文末 §9。
> 分支：`refactor/ux-v2` @ `2b320da`（只读核查，未运行生产）
> 顾问：run `34b15811-3337-4841-a4d0-4396246e9f1d`（claude-opus-5-5 / effort xhigh / `--risk data-loss`）
> 裁决：决定 1 = adopted，决定 2 = adopted，决定 3 = partial

## 0. 一句话结论

三个问题都不是"同步没跑"，而是**跑完之后没反映到用户看到的地方**，外加**一处稳定性核验口径错误**：

| # | 现象 | 根因 |
| --- | --- | --- |
| P1 | EWO 同步后时间不变；负责人要去掉；状态应写阶段；逾期要独立成列 | 幂等 skipped 不刷新 `last_success_at`（F1）+ 接口永远 200/"同步完成"（F2）+ 展示层把手工字段和原始状态码直接渲染（F4/F6） |
| P2 | 交付物明细同步后仍是 0% | 后端已算好 `syncDisplay.displayProgress`，前端读的是手工字段 `item.progress`（F5） |
| P3 | 数模设计审核流程报表同步失败 | 稳定性采样没有做科室收窄，与"收窄后的全量基线"必然对不上（F7）；失败还会毒化基线（F8） |

## 1. 已核实证据（代码坐标）

- **F1** `core/repos/sync_runs.py:501-528`：`already_processed` 幂等分支只写 audit + `_finalize_run_and_release`，**没有**执行 `:582-597` 的 `UPDATE ... last_success_at`。聚合绑定去重键是 `cursor.aggregate_last_content_version`（`:486-499`），上游内容不变 ⇒ 每次"立即同步"都 skipped ⇒ UI"上次同步"停在首次成功时刻。
- **F2** `web/app.py:6294-6296`：sync-now 无论 run 结果如何都返回 HTTP 200 + `ok:true`；`plugins/project_overview/static/deliverable/simple.js:124-126` 只看 HTTP 成功就写"同步完成"。
- **F3** `services/project_status_updates.py:48`：自动写入字段白名单 = `{owner, plannedDate, note}`；`core/repos/sync_runs.py:455-459` 同白名单；`services/project_status_connectors.py:272` 注释"同步从不写 status/progress"。
- **F4** `services/ewo_binding_records.py:15-16`：EWO 记录集绑定**禁止**映射 owner/plannedDate；发现侧把 mapping 收敛为仅 note（`services/project_status_discovery.py:191-192`）。⇒ "计划完成 2026-08-22"永远是手工值，同步不会改它。
- **F5** `web/app.py:2442-2460`：`display_state=="snapshot"` 时已派生 `displayProgress=round(completed/total*100)`、`displaySummary`；但同一响应的 `progress` 仍是手工 `row["progress"]`（`:2483`）。`simple.js:118,142` 读的是后者 ⇒ 恒 0%（EWO 实际 241/340 = 71%）。
- **F6** `services/deliverable_form_analysis.py:1423-1442`：行级已有 `dimensions.stage`、`overdueState`、`isCompleted`；EWO 的 `stage = normalize(state)`（`:720-729`），阶段码 `{DRAFT1,DRAFT2,EDIT1,EDIT2,PROC,IMPL,CLOSE}`（`core/form_registry.py:78`），**无中文标签**。`simple.js:101` 用 `dimensions.status` 原码，且逾期时用"逾期"覆盖状态。
- **F7** 基线 = "全量抓取 + 科室多选本地收窄"后的行身份集合（`web/app.py:5511-5537`；`services/project_status_discovery.py:265-270`）；采样走 `query_data_model_page(page=1,page_size=50)` **未收窄**（`web/app.py:5887-5891`）⇒ 子集判定失败 ⇒ `sample_not_in_baseline`（`project_status_discovery.py:407-424`；文案 `policy-logic.js:241-243`）。
- **F8** 失败会落一条 `key_changed` 观测（`project_status_discovery.py:468-495`），此后 `previous[0].result_state != matched` ⇒ 直接 `stability_baseline_missing`（`:336-348`），**单独重试永远不就绪**，必须重做第 1 次取证。
- **F9（已被顾问推翻，作废）** "第 1 页排序漂移导致子集失败"：排序漂移不改变样本是否属于全集；真正风险是**基线分页抓取漏行/重行**，应改为基线自检（见 3.4）。

## 2. 批 1（只读侧，可整体回滚）：P1 展示口径 + P2 进度

### 2.1 进度派生单源（P2）
- `core/project_status_contracts.py` 新增纯函数 `derive_effective_progress(display_state, summary, manual) -> {value, source}`：
  - snapshot 且 total>0 → `round(completed/total*100)`，source=`snapshot`；
  - total==0 → `value=None`（前端显示"—"，不显示 0%）；
  - 其它状态 → 手工值，source=`manual`。
- `web/app.py:2456-2468` 改为调用它；响应**新增** `effectiveProgress` / `progressSource`，**`progress` 键语义不变**。
  - 这条护栏必须保留：编辑表单用 `item.progress` 预填（`deliverable/edit.js`、`shared/status-edit.js`），一旦把派生值写回 `progress`，用户点一次保存就把派生值固化成手工值 —— 等于无审计的数据写入。
- `simple.js:118,142` 改读 `item.effectiveProgress`（null → "—"）；source=snapshot 时标"由明细派生"。

### 2.2 状态列 → 阶段列
- `core/form_registry.py` 的 `FormSpec` 增 `stage_labels`，由 `form_definition()`（`:473/:541`）下发到 schema（`deliverable_form_analysis.view()` 的 `schema.stageLabels`）。
- 初始文案（待用户确认，改一个字典即可）：DRAFT1 起草 / DRAFT2 起草（二轮）/ EDIT1、EDIT 编辑 / EDIT2 编辑（二轮）/ PROC 审批中 / IMPL 实施 / CLOSE 关闭；缺失回退原码。
- `simple.js:94-102`：表头"状态"→"阶段"，取 `row.dimensions.stage` 经 `schema.stageLabels` 翻译；**删除"逾期覆盖状态"逻辑**。

### 2.3 逾期独立成列
- 新列"逾期"：`row.overdueState === "overdue" && !row.isCompleted` → "是"，否则"—"。
- 天数暂不前端自算：等契约能给出同一参考日期/时区下的 `overdueDays` 再下发（顾问条件）。
- KPI 行（总数/已完成/未完成/逾期）保持不变。

### 2.4 负责人
- `simple.js:139` 去掉 `负责人 xxx ·`；`plugins/workbench/static/project.js:110` 列表副标题同样去掉 owner。
- **不动映射、不动 DB**：EWO 记录集绑定本来就不能映射 owner（F4），"清空映射"没有对象可清；清 DB 值不可逆且会影响单记录绑定与其它页面。

### 2.5 计划完成时间
- 加"手工"标识（如 `计划完成 2026-08-22（手工）`）。记录集绑定不写 plannedDate 是设计约束，不是缺陷。

### 2.6 "同步完成"文案（P1 的体感来源）
- `simple.js:121-130` 按 `data.result.outcome/finalState` 三态：
  - `completed` + 有 appliedFields → "同步完成，更新 N 项"；
  - `completed` + 无 appliedFields（幂等 skipped）→ "已同步，上游无变化"；
  - 其它 → 错误态并显示 `errorType/errorMessage`。
- **不改** HTTP 200 / `ok` 语义（可能存在未知调用方，兼容性取舍）。

## 3. 批 2（数据层一行）：上次同步时间

- `core/repos/sync_runs.py:501-528` 的 `already_processed` 分支，在 `_finalize_run_and_release` 之前、同一事务内补 `:582-597` 的 `UPDATE ... last_success_at / sync_state / updated_at`；audit 仍记 `skipped`。
- 语义定为：**skipped = 已抓取上游且内容无变化 = 一次成功同步**。
  - 已核实前提：`aggregate_last_content_version` 来自本次上游抓取（`services/project_status_connectors.py:288` 用本次 records 计算 `external_version`），进入该分支前必然已完成 collect。
  - 连带效果：调度器 `_is_fresh`（`services/project_status_scheduler.py:337-346`）按 `last_success_at` 节流，现状"永远不新鲜"⇒ 每轮都跑；修后按 interval 正常复用。
- **反例门槛**：若将来出现"不抓上游就能进入 already_processed"的路径（例如只比对本地缓存版本），必须改回"新增 `last_checked_at` 列"方案，否则就是虚报新鲜度、掩盖上游故障。

## 4. 批 3（数模稳定性）：同源采样 + 不毒化基线

1. **抽公共收窄函数**：把 `web/app.py:5511-5537` 的 sections 收窄封成 `narrow_data_model_rows(db, rows, match_rule)`，发现 / 采样 / 同步三处共用（同步侧已有 `TDCProjectStatusConnector._narrow_by_sections`，只做接线，不复制逻辑）。
2. **采样同源**：`web/app.py:5887-5891` 的第 1 页行先收窄再比对；total 口径 raw 对 raw（基线 `_upstreamTotal` 与 page `total` 都是上游声明总数），身份集用收窄后。
3. **空样本 = inconclusive**：收窄后 0 行 → 不 ready、不写 `key_changed`，提示"第 1 页样本落在所选科室之外，请扩大科室范围或稍后重试"。禁止空集子集判定（会空真通过，假 ready）。
4. **基线自检**：去重身份数 ≠ raw total 或存在重复身份 → 判"基线无效"，要求重新取证，不进入采样（替代被推翻的 F9 排序假设）。
5. **不毒化基线**：`observe_stability_sample` 的基线改为"最近一条 `matched` 且 `config_signature` 相符"的观测（`list_mapping_observations` 已有 20 条窗口，扫描即可），而不是 `previous[0]`。mismatch 仍落 `key_changed` 保留审计，但不再顶掉基线。
6. **失败分类不改枚举**：`project_status_mapping_observations.result_state` 有 CHECK 约束（`core/db_common.py:757`），加枚举值要重建表、违反 additive；把 `kind`（`sample_not_in_baseline` / `inconclusive` / `baseline_invalid`）写进已有的 `aggregated_candidate_json`。
7. **文案**：`policy-logic.js:233-252` 增加 inconclusive / 基线无效两类，避免"上游可能已变化"误导。
8. **存量恢复**：已毒化绑定不需要迁移；改后重新点"开启自动同步"即可（会重新取证 + 采样）。

## 5. 改动清单

| 批次 | 文件 | 位置 | 改动 |
| --- | --- | --- | --- |
| 1 | `core/project_status_contracts.py` | 新增函数 | `derive_effective_progress` |
| 1 | `web/app.py` | 2442-2470 | 调契约函数，下发 `effectiveProgress/progressSource` |
| 1 | `core/form_registry.py` + `services/deliverable_form_analysis.py` | FormSpec / `form_definition` | `stage_labels` → `schema.stageLabels` |
| 1 | `plugins/project_overview/static/deliverable/simple.js` | 94-102、118、139-142、121-130 | 阶段列、逾期列、进度字段、负责人、同步文案 |
| 1 | `plugins/workbench/static/project.js` | 110 | 列表副标题去 owner |
| 2 | `core/repos/sync_runs.py` | 501-528 | skipped 分支刷新 `last_success_at` |
| 3 | `web/app.py` | 5511-5537、5887-5891 | 抽 `narrow_data_model_rows` 并在采样复用 |
| 3 | `services/project_status_discovery.py` | 336-348、407-424、468-495 | 基线取最近 matched；空样本 inconclusive；kind 落 JSON |
| 3 | `plugins/project_overview/static/deliverable/policy-logic.js` | 233-252 | 失败分类文案 |

## 6. 验证

- 单测：`derive_effective_progress` 金样例（snapshot/manual/total=0）；`stageLabels` 契约；simple 视图渲染断言（阶段列、逾期列、进度 71%、无 owner、skipped 文案）。
- `sync_runs`：同版本连跑两次 → 第二次 skipped 且 `last_success_at` 前进；版本变化 → applied。
- 数模：第 1 页含其它科室行 → 通过；收窄后空页 → inconclusive；基线漏行 → baseline_invalid；已毒化历史 → 重新取证后可 ready；真实键变更 → 仍 `key_changed`。
- 全量 `python -m pytest tests -q` + `python tools/generate_project_map.py --check`。
- 真机：EWO 连点两次"立即同步"看时间前进、进度 71%、阶段中文、逾期独立列；数模"一键开启自动同步"成功。

## 7. 明确不做

- 不把 `progress/status` 纳入 automatic authority（方案 B 被硬约束排除）。
- 不清理 EWO 的 owner 映射/DB 值（无对象可清，且不可逆）。
- 不改 sync-now 的 HTTP 200 语义。
- 不在本次处理"天数"口径与"导出/报表读 progress"的改造（顾问反例项，留待确认）。

## 8. 实施顺序

批 1（只读，可回滚）→ 批 2（一行 SQL，需上面的反例门槛复核）→ 批 3（数模阻塞业务时可与批 1 并行）。

## 9. 实施记录（2026-10-29）

### 9.1 已落地

| 批次 | 文件 | 实际改动 |
| --- | --- | --- |
| 1 | `core/project_status_contracts.py` | 新增纯函数 `derive_effective_progress`（snapshot 换算 / 其它态回退手工 / total=0 → None） |
| 1 | `web/app.py` | 调契约函数；响应新增 `effectiveProgress` / `progressSource`，`progress` 与 `displayProgress` 语义不变 |
| 1 | `core/form_registry.py` | `FormSpec.stage_labels` + `stage_label()`；EWO/PAA 七/六阶段中文标签 |
| 1 | `services/deliverable_form_analysis.py` | `form_definition` 下发 `stageLabels`（单一来源） |
| 1 | `plugins/project_overview/static/deliverable/simple-logic.js`（新） | 纯逻辑：`stageLabel` / `overdueLabel` / `progressDisplay` / `syncResultText` |
| 1 | `plugins/project_overview/static/deliverable/simple.js` | 阶段列 + 逾期列；去负责人；计划完成标「（手工）」；进度读派生值；同步文案三态 |
| 1 | `plugins/workbench/static/project.js` | 列表进度读 `effectiveProgress`；副标题去负责人 |
| 2 | `core/repos/sync_runs.py` | 幂等 skipped 分支刷新 `last_success_at / sync_state / updated_at` |
| 3 | `web/app.py` | 抽 `_narrow_discovery_rows_by_sections`；采样三条路径（第 1 页 / 单号 / 多单号）统一收窄；空样本 → `sample_empty_reason`；基线总数改用收窄前行数 |
| 3 | `services/project_status_discovery.py` | 基线取「最近一条 matched」（50 条回看窗口）；`sample_empty_reason` → inconclusive 且不落观测 |
| 3 | `plugins/project_overview/static/deliverable/policy-logic.js` | 新增 inconclusive 文案 |

### 9.2 与方案的三处偏离（均已验证）

1. **§3.4 基线自检未实施**：`_upstreamTotal` 与行身份数是否同口径取决于上游 total 是「行数」还是「实例数」（D5 是零件行粒度），未取证前加这个校验会误杀合法绑定。改为在采样侧保持「收窄对收窄、total 对 total」的显式口径（已在代码注释写明）。
2. **纯逻辑抽成 `simple-logic.js`**：原计划改 `simple.js`，但 `simple.js` 依赖 preact 运行时无法在 Node 门禁里直接断言；抽出无 preact 依赖的纯逻辑后新增 `tests/test_plugin_overview_simple_logic.py`（真实 Node 执行）。
3. **多单号「全部单号消失」按 inconclusive**：原来会落 `serial_set_changed`，现在样本为空时先判不确定（无法区分「移出科室范围」与「真删除」）。部分缺失（仍有命中）仍是 `serial_set_changed`，原测试未变。

### 9.3 新增/更新的门禁

- `tests/test_project_status_contracts.py`：派生进度 4 例（snapshot/manual/total=0/越界与脏值）。
- `tests/test_project_status_policy_api.py`：payload 级 `effectiveProgress/progressSource` 断言（75% + 手工 0 并存）。
- `tests/test_project_status_aggregate_sync.py`：幂等 skipped 后 `last_success_at` 必须前进。
- `tests/test_project_status_discovery.py`：失败采样不毒化基线（重试可 matched，计数 1/2）；空样本 inconclusive 且不写观测。
- `tests/test_project_status_api.py`：数模采样同源（含其它科室行仍 matched）；空样本 inconclusive。
- `tests/test_deliverable_form_analysis.py`：`stageLabels` 契约。
- `tests/test_plugin_overview_simple_logic.py`（新）：阶段/逾期/进度/同步文案纯逻辑。

### 9.4 待真机确认

- EWO 连点两次「立即同步」：第二次应显示「已同步，上游无变化」且「上次同步」时间前进；进度应显示 71%（241/340）。
- 数模「一键开启自动同步」：应一次走到 2/2 并启用；若第 1 页落在所选科室之外，提示「采样页在所选科室里没有命中记录」而不是「上游可能已变化」。

## 10. 实施后顾问复核（2026-10-29）

顾问：run `e6210966-371f-4be7-8d1d-35e1bbb4c4b6`（claude-opus-5-5 / xhigh / `--risk data-loss`，
task `TASK-20261029-V2-SYNC-IMPL-REVIEW-01`）。裁决：1=partial，2=adopted，3=partial。
总体判断「需修再发布」，逐项裁决如下（**否决项均给出代码证据，未按意见改**）。

| 顾问项 | 级别 | 裁决 | 依据 / 处置 |
| --- | --- | --- | --- |
| A skipped 自锁（"没抓上游也刷新新鲜度"） | S1 | **否决** | 新鲜度分支直接跳过、不调用 runner（`services/project_status_scheduler.py:234,314`），已有断言 `test_fresh_bindings_are_skipped_without_network`；connector 失败走 `finalize_sync_failure`，已有断言 last_success_at 不变（`tests/test_project_status_sync_runner.py:663-684`）；connector 无"回退快照"路径 |
| A skipped 写 binding.updated_at 放大乐观锁冲突 | S3 | **否决** | 绑定编辑用 `sync_config_revision` + 配置摘要；交付物编辑用 `deliverable.updated_at`；`project_status_update_bindings.updated_at` 不参与任何乐观锁 |
| B 回退到旧配置的 matched 基线 | S1 | **采纳** | 优先取同签名（或旧版无签名）的 matched；只剩旧配置基线时改为**只做否定性比对**：即使样本落在旧基线内也强制 `baseline_signature_mismatch`，本次绝不返回 matched。新增 `test_f10_stability_baseline_requires_matching_config_signature`（改规则 → 不一致；同规则 → 两条一致证据后 2/2） |
| B 跨 key_changed 回看会持续 key_changed | — | 保留设计 | 这正是修复目的（失败不毒化基线）；真实键变化由重新取证恢复，enable 流程每次先 `observe`。已补"失败后可重建"断言 |
| C 缺列 ValueError 去向丢失（疑 500 / 被吞） | S1 | **否决** | helper 内 `except ValueError -> _TDCRequestError(..., "SectionColumnMissing", 422)`；新增 `test_mapping_discovery_f10_stability_missing_section_column_is_422` |
| C total 口径语义变化 | S2 | 部分采纳 | 仅影响「上游未声明 total」分支（声明 total 时行为不变；无 sections 时两口径相等）。旧观测首轮 mismatch 一次即重新取证自愈，已记录 |
| D snapshot 丢 0..100 夹紧 | S2 | **否决** | 实现为 `min(100, max(0, round(...)))`；新增 oracle 测试逐例比对改动前的内联实现（含 completed>total） |
| D manual 夹紧/类型处理 | S2 | 采纳（有意差异） | 越界夹紧、非数字判 None（旧实现会原样透出 150 或在非数字上抛错）；已在等价测试里列为"有意差异" |
| D 其它态回落手工值（列表跳 0%） | S2 | 保留 | 有快照时 state 恒为 snapshot，不会跳变；paused 的手工列存的是上次同步值 |
| E ES module 缓存导致白屏 | S2 | 部分采纳 | `simple-logic.js` 是新增文件，`/plugins/` 已 no-cache；打包清单需确认（真机清单第 1 项） |
| E 其它 progress 读者 | S3 | **采纳** | `progressOrDate`（概览表"实际完成或当前进度"）改用派生值；其余读取点本地检索无命中 |
| Q2 门禁不足以证明 | — | **采纳** | 新增 4 条门禁（换规则基线 / 采样缺列 422 / 旧实现 oracle / progressOrDate）；A 的失败与节流路径确认已有断言 |

复核后回归：全量 `python -m pytest tests -q` → **3432 passed / 6 skipped**（复核前 3429/6，新增 3 条门禁）。

### 10.1 复核后的实施补丁

1. **B**：`observe_stability_sample` 基线选择改为「同签名优先 + 旧配置只做否定性比对」；新增 mismatch 原因
   `baseline_signature_mismatch`（前端 `policy-logic.js` 同步文案）。
   过程中与既有契约 `tests/test_data_model_identity_contract.py::test_legacy_form_id_baseline_reports_mismatch_instead_of_matching`
   冲突一次：该契约要求旧基线必须报「不一致」而不是被忽略——因此保留否定性比对，而不是直接 `baseline_missing`。
2. **E**：`progressOrDate`（概览表"实际完成或当前进度"）改用派生进度，避免概览表与工作台两套数字。
3. **门禁新增 4 条**：换规则基线（含恢复路径 1/2 → 2/2）、采样缺列 422、旧实现 oracle 等价、`progressOrDate`。
4. **确认既有断言已覆盖顾问的 A 项**：`test_fresh_bindings_are_skipped_without_network`（节流零网络）、
   `tests/test_project_status_sync_runner.py:663-684`（失败不动 last_success_at）。
