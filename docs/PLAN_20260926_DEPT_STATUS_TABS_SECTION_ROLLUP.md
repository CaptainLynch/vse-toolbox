# 方案：部门总状态双分页看板与科室归集（D3/D6/D7/D8）

- 日期：2026-09-26
- 状态：**已实施完成**（用户批准后按第 8 节顺序落地；全量门禁 2425 passed / 3 skipped，
  flake8 零告警，`node --check` 通过，项目地图 verified，冒烟 22/22，见第 10 节）
- 设计确认依据：用户 2026-09-25/26 口径澄清 + 预览图
  （`.runtime/preview-dept-status-tabs-v2/preview-*.png`，含归集规则编辑形态）

## 1. 背景与已确认的设计

用户要求把交付物详情页的「部门总状态」看板拆成两个分页，并澄清「状态」的口径：

| 表单 | 「状态」轴 | 看板形态 |
| --- | --- | --- |
| D3 EWO（`VPI-T2-D3`）/ D6 PAA（`aras_paa`） | 业务状态 `DRAFT1/DRAFT2/EDIT1/EDIT2/PROC/IMPL/CLOSE`（PAA 无 EDIT1/EDIT2，为 `EDIT`） | 双分页 |
| D7 NCR审批进度（`aras_ncr_progress`） | 审批节点 `PE提交/NCR管理员/…/CLOSE`（`_STAGES_BY_REPORT` 官方 13 节点） | 双分页 |
| D8 NCR审批明细（`aras_ncr_detail`） | 无状态维度 | 仅「按科室」单页 |

- 分页1「按科室」：每行一个归集后科室，柱内色段 = 各状态的数量占比；点击行追加科室筛选。
- 分页2「按状态」：每行一个状态（官方枚举全量按流程顺序展示，含零行，与现状一致），柱内色段 = 各归集后科室的数量占比；点击行追加状态筛选。
- 「按期推进/逾期风险/未判定」不再作为该看板的分色维度（明细筛选与预警保留）。
- 科室归集（二次筛选集合）：历史科室五花八门（如车身科前身结构工程科、车门附件科），先归集到现行五个科室（车身科、车体科、内饰科、外饰科、车体架构集成科）再统计；图表与「科室/区域」筛选都按归集口径；未登记值进「未归集」固定兜底，不静默丢弃；规则须可在 WebUI 自行编辑，保存后立即生效。

## 2. 范围与非目标

**范围**：D3/D6/D7 双分页看板；D8 单页科室统计板；科室归集规则（存储 + 校验 + API + WebUI 编辑器）；section 筛选按归集口径展开。

**非目标**：
- D2 SOR、D5 数模看板保持现状（其 section/stage 语义不同：科室=车型项目、部门等），本轮不动，后续可复用同一机制扩展。
- 不改写任何原始同步数据、不迁移历史快照（归集是读时统计口径）。
- 不做规则版本历史/审计日志、不做多套规则方案切换。
- 统计（`deliverable_statistics`）、归档、同步链路不受影响。

## 3. 现状关键事实（代码证据）

1. 图表读取时现算：`DeliverableFormAnalysisService.view()`（`services/deliverable_form_analysis.py:1951`）对**筛选后的最新快照行**重新调用 `summarize_form_rows`（:1993）→ `_chart_payload`（:1711）。因此读取层新增归集参数即可让规则变更即时生效，无需重建快照。
2. 快照发布路径 `build_form_snapshot`（:1547）预计算 summary/charts 存储，但新看板不消费存储值；趋势聚合只用 `total/incomplete/overdue`（与归集无关）。
3. 筛选在 DB 层按原始值匹配：`db.list_deliverable_form_snapshot_rows(id, effective_filters)`；`section` 属于多选键（`_MULTI_FILTER_KEYS`，同一字段 OR，上限 `_MULTI_FILTER_MAX_VALUES=20`，经 `normalize_form_filters` :1660 校验）。
4. 筛选下拉来自 `_filter_options`（:1728），按行原始 `dimensions.section` 去重排序（截断 500）。
5. 设置存储：`app_settings` 为自由键值表（`core/db_manager.py:822,1886,1896`，`setting_key`+`value_json` upsert），任意新键无需迁移；`core/settings_store.py` 是其白名单消费者。
6. 前端：`DELIVERABLE_FORM_TABS`（`web/static/app.js:5718`）、`renderFormChartTabs`（:6643）、`renderFormStatusBars`（:6359，固定按期/逾期/未判定三段）、`DELIVERABLE_FORM_CHART_TITLES`（:5782）、筛选 chips `appendFormFilter`；逾期判定控制条 `buildFormOverdueControl` 仅在 ewo/paa/ncr_progress 的两个状态页签显示。
7. 状态枚举：`_STAGES_BY_REPORT`（`services/deliverable_form_analysis.py:60`）；`ncr_detail: ()`。

## 4. 设计

### 4.1 归集规则存储与校验（新增 `core/section_rollup.py`）

- `DEFAULT_ROLLUP_RULES`：五个现行科室目标，各带空/最小别名集（首次运行的内置默认；完整历史对照由用户在 WebUI 补录）。
- 规则形状（存 `app_settings`，键 `sectionRollup`）：

```json
{
  "version": 1,
  "updatedAt": "2026-09-26T10:00:00Z",
  "targets": [
    {"target": "车身科", "aliases": ["结构工程科", "车门附件科"]},
    {"target": "车体科", "aliases": []},
    {"target": "内饰科", "aliases": []},
    {"target": "外饰科", "aliases": []},
    {"target": "车体架构集成科", "aliases": []}
  ]
}
```

- 语义：目标名自身恒匹配自身；alias 按去除首尾空白后的**精确相等**匹配；两个规则都未命中的原始值归入隐式「未归集」桶；`targets` 顺序即看板行序，「未归集」恒最后。
- 校验（`validate_section_rollup` → 规范化 + `SectionRollupError(ValueError)`）：target 非空、去重、数量 ≤ 24；alias 非空、trim、目标内与跨目标均唯一、不得等于任何 target 名、每目标 ≤ 40、总 alias ≤ 200；整体 JSON ≤ 64 KiB。
- 统一归集原语 `resolve_section(value, rollup) -> str | None`：trim 后精确匹配目标名或别名 → 返回目标名；未命中 → `None`（即「未归集」）。筛选谓词与矩阵聚合共用这一个函数，保证两处口径永远一致（顾问意见的核心落地）。
- `SectionRollupStore(db)`：`get()`（缺省返回默认规则）/`save(payload)`（校验后 upsert `app_settings`）；复用 `db_manager.get_app_settings/update_app_settings`，**不进入** `SettingsStore` 白名单（通用设置 PATCH 不受理该键）。写入为单条 upsert（原子），并发语义 = 本地单用户 last-write-wins，`updatedAt` 记录最近修改。

### 4.2 分析服务聚合（`services/deliverable_form_analysis.py`）

- `summarize_form_rows(..., *, section_rollup: Mapping[str, str] | None = None)`（alias→target 的扁平映射；`None` = 不归集）：
  - `report in {"ewo","paa","ncr_progress"}` 且传入了 rollup 时，追加产出：
    `sectionStageMatrix = {"sections": [{"label","total"}], "stages": [{"label","total"}], "cells": [{"section","stage","count"}]}`。
    - 行序：规则目标顺序 + 「未归集」；列序：官方 stage 全量按 `_STAGES_BY_REPORT` 顺序（含零计数行），「其他状态」（现状聚合口径）最后。
    - 仅当传入 rollup 才产出该键（趋势重算路径不传，避免无谓开销）。
  - `report == "ncr_detail"` 且传入 rollup 时追加 `sectionCounts = [{"label","total"}]`。
  - 现有 `departmentStatus`/`sectionStatus` 保持**原始值口径**不动（tdc 表单与旧载荷兼容）。
- `_chart_payload`（:1711）透传 `sectionStageMatrix`/`sectionCounts`（缺省空结构）。
- 发布路径 `build_form_snapshot` 不传 rollup（存储保持原始口径，无需回填历史快照）。

### 4.3 读取路径：行级归集 + Python 层科室筛选（顾问意见采纳）

**放弃**「把目标值展开为原始值列表（含未归集负桶显式化）」的方案：未登记原始值的种类数没有可靠上界，按列表展开+截断会引入静默漏数路径（顾问指出的核心缺陷）。改为**行级归集后筛选**：

- `view()` / `rows()` 增加仅关键字参数 `section_rollup`（web 层从 `SectionRollupStore` 读取传入）。
- **筛选语义**：section 筛选不再下推 SQL，改为读取行后逐行经 `resolve_section(row.section, rollup)` 判定归属，再按所选目标（或「未归集」= 判定为 `None`）在 Python 层过滤。「未归集」因此是真正的逐行分类，不存在任何列表展开、上限或截断——结构性消除漏数路径。
- **`view()`**：从 SQL 过滤参数中剥离 `section`（其余键仍走 SQL），行读入后先做阈值重算（既有逻辑），再做归集筛选，然后 `summarize_form_rows`（传 rollup）与 `matchedRowCount`。`view()` 本就为选项发现整读快照行（≤20000 既有读界），无新增量级成本。
- **`rows()`**：携带 section 筛选时改走整读路径（复用既有 thresholds 路径模式：`list_deliverable_form_snapshot_rows` → 阈值重算 → 归集筛选 → Python 内 `offset/limit` 切片，`total = len(筛选后)`）；无 section 筛选时保持既有 SQL `COUNT+LIMIT/OFFSET` 快路径不变。分页因此必然发生在筛选之后（顾问要求）。
- 每行附带派生字段 `sectionRollupTarget`（目标名或 `"未归集"`；未配置规则时不下发），供明细侧未来展示与调试，不改 `values[]` 位置语义。
- `_filter_options`：`section` 选项 = 出现行经 `resolve_section` 映射后的目标名（按规则顺序）+「未归集」（仅当存在未命中行）；其余键不变。选项为有限集合（≤ 目标数+1），无需 500 截断。
- 直接传历史原始值的旧筛选链接不再匹配（原值已被归集）——如需兼容可在规则里把该历史值登记为别名；这是归集语义的自然结果，写入用户手册。
- 与阈值重算的组合顺序固定：SQL 过滤（非 section 键）→ 阈值重算 → 归集筛选 → 汇总/分页。

### 4.4 Web API（`web/app.py`）

- `GET /api/project-status/section-rollup` → `{ok, data:{version, updatedAt, targets}}`。
- `PUT /api/project-status/section-rollup`：`_local_web_mutation_error()` 守卫；校验失败 → 422 `{ok:false, error:{message, fields:{...}}}`（沿用 `_json_error`）；成功返回保存后的规范化规则。
- `view`/`rows` 调用处读取 `SectionRollupStore.get()` 并传参；读路径无缓存，保存即生效。

### 4.5 前端（`web/static/app.js` + `style.css`，全 Safe DOM）

- `DELIVERABLE_FORM_TABS`：
  - `VPI-T2-D3` / `aras_paa` / `aras_ncr_progress` → `[["departmentStatus","部门状态"],["quantityTrend","数量趋势"]]`（移除三者的 `sectionStatus` 顶层页签，其科室维度由新分页1覆盖）。
  - `aras_ncr_detail` → `[["sectionCounts","按科室"],["departmentCost","部门成本"],["sectionCost","科室成本"]]`。
  - `tdc_data_model` / `tdc_sor` 不变。
- 新看板组件 `renderDepartmentStatusBoard(data, state, onReload)`（departmentStatus 顶层页签内容）：
  - 看板标题「部门总状态」+ 内部页签「按科室 / 按状态」（`state.boardTab` 记忆，切换触发 `onReload()`，复用既有 interaction guard/缓存机制）。
  - 分页描述按页签区分（沿用预览文案）；图例按当前页签维度（科室色 / 状态色）。
  - 新通用渲染 `renderFormMatrixBars(rows, {filterKey, state, onReload})`：行=标签，段=`{label,color,count}`；段宽=计数/最大行合计；段内白字计数（宽 ≥8%）；`title` 悬停显示「行 · 段：n 条（占 x%）」；行点击 `appendFormFilter`（按科室行→`section`，按状态行→`stage`；「其他状态」行与现状一致不可点击）。`renderFormStatusBars` 保留给 tdc 表单。
  - 配色：状态按流程顺序从固定暖色板取色，语义覆盖 `CLOSE→var(--success)`、`其他状态→灰`；科室按规则顺序固定色板，`未归集→灰`（与预览一致）。
  - 「科室归集规则」面板置于看板下方：常显只读规则表（归集到 ↔ 历史值 + 生效说明）；【编辑规则】进入编辑态（chips 增删、「+ 添加历史值」、「+ 新增目标科室」、校验提示、【保存规则】/【取消】）；保存成功后 `onReload()`。仅在 D3/D6/D7/D8 渲染。
  - `aras_ncr_detail` 的 sectionCounts 板：单段横条（主色）+ 同一归集面板。
- 逾期判定天数控制条保持现状与位置（其口径仍驱动明细/预警/趋势）。
- 防御：`charts.sectionStageMatrix`/`sectionCounts` 缺失或形状非法时按「暂无可分析的表单数据」空态处理。

### 4.6 交互与文案

- 「未归集」行可点击筛选（展开为显式未登记值列表）；「未归集」图例/行名固定最后。
- 编辑器校验错误逐字段展示（沿用 422 `fields` 形状）。
- 面板说明固定文案：「规则保存在本地数据库，保存后立即生效——只调整统计口径，不改写原始数据，无需重新同步。」

## 5. 兼容性

- 无数据库迁移（`app_settings` 自由 KV）；无历史快照回填（读时现算）。
- 旧载荷键 `departmentStatus`/`sectionStatus` 全部保留：tdc 表单继续消费；in-scope 表单不再渲染旧板但载荷仍在（成本最低、回滚容易）；后续如需瘦身另行决策。
- 明细表（rows/表单明细）继续显示原始科室值（保真）；仅筛选与图表按归集口径；行载荷附带 `sectionRollupTarget` 派生字段（不渲染进既有 `values[]` 位置语义），后续如需「归集后科室」辅助列可直接消费。
- 直接传历史原始值的旧筛选链接：该值若未登记为别名则不再命中（归集语义自然结果）；用户手册写明「历史值请在归集规则中登记」。

## 6. 测试计划

1. `core/section_rollup.py`：校验矩阵（跨目标重复 alias、alias=目标名、空值、超限、顺序保持、trim）、`resolve_section`（命中目标名/别名/未命中 `None`、空白与 Unicode 值）、默认规则、存取往返、KV 键独立于 SettingsStore 白名单。
2. `services/deliverable_form_analysis.py`：矩阵聚合正确性（归并、未归集逐行判定、零节点行显式保留、顺序稳定）、`ncr_detail` 计数、`section_rollup=None` 不产出新键、旧 summary 键形状不变、**规则变更后读取旧快照立即按新口径出数**（保存即生效钉住）。
3. 服务层：`view`/`rows` 的归集筛选（目标命中别名行、「未归集」= 判定 `None` 的全部行、未配置规则时 section 仍走原路径）、`rows` 带 section 筛选时分页与 total 正确（筛选后切片）、section+阈值组合路径、`_filter_options` 归集与「未归集」选项、`sectionRollupTarget` 派生字段。
4. `web/app.py`：GET/PUT 契约、422 字段错误形状、mutation 守卫、**保存规则后 view/rows 立即反映新口径**（端到端用例）。
5. Node VM（`tests/test_deliverable_sync_wizard_enhanced.py` 模式）：看板内页签切换渲染两种透视、行点击追加正确筛选键、「其他状态」行不可点击、编辑器增删/保存流程、零 `innerHTML`。
6. 回归：tdc 表单旧板、`test_deliverable_form_analysis.py`/`test_deliverables_web.py`/`test_overview_web.py` 全绿。
7. 门禁：全量 `pytest -q`、`flake8 -j 1`（改动文件零告警）、`node --check`、`tools/generate_project_map.py --check`、Flask test client 冒烟（含 PUT 规则后刷新看板）。
8. 实施核对项（顾问缺失证据清单的落实）：确认调试/备份导出（`core/debug_bundle.py`）覆盖 `app_settings` 的 `sectionRollup` 键，若未覆盖则补入。

## 7. 开放问题的裁决（已结合顾问意见定案）

1. **归集应用层** → 读时归集（方案 A）。存储 summary 保持原始口径、读时矩阵为归集口径的双口径**接受**：读路径本就现算图表，旧键仅供 tdc 表单与回滚兜底，本地 UI 无外部消费者；文档明确旧键口径为「原始值」。
2. **section 筛选实现** → 行级归集 + Python 层过滤（放弃值列表展开）：未归集是逐行分类，结构性消除漏数路径；分页保证在筛选之后（`rows()` 携带 section 时走整读切片路径）。
3. **规则存储** → `app_settings` 独立键 `sectionRollup`（自由 KV，无迁移；单条 upsert 原子；last-write-wins）；实施核对调试/备份导出覆盖该键。
4. **旧载荷保留** → 保留（tdc 表单消费 + 回滚兜底），前端 in-scope 表单不再渲染。
5. **明细口径** → 显示原始值；载荷附带 `sectionRollupTarget` 派生字段；「归集后科室」辅助列作为可选项待用户拍板（本轮不渲染）。
6. **别名匹配** → trim 后精确相等（不做前缀/包含，避免误归集）。
7. **矩阵载荷形状** → 实施定稿为嵌套对齐结构：`sections[]` 与 `stages[]` 各自带 `total` 和 `cells`（cells 与对侧维度数组顺序严格对齐、显式零计数、固定顺序）；信息与平铺 cells 等价，双透视无需重排。

## 8. 实施顺序

1. `core/section_rollup.py` + 测试 → 2. 分析服务矩阵聚合 + 测试 → 3. 服务层归集筛选（view/rows）+ 测试 → 4. Web API + 测试 → 5. 前端看板/编辑器 + VM 测试 → 6. 全量门禁 + 冒烟 → 7. 用户手册（`docs/USER_GUIDE_STANDALONE_EXE.md`）补节。

## 9. Codex 顾问审计记录

- 咨询：2026-09-26，`codex-readonly --profile sol-high --caller zcode`，任务 `TASK-20260926-DEPT-STATUS-TABS-ROLLUP`，包 `.runtime/consult-20260926-dept-status-rollup.md`（6,889 B，SHA-256 `054ab5c3…557e95`），live 一次成功（exit 0；12,359 input / 978 output tokens；1 个非致命 error item，按契约仅计数）。意见归档：`~/.dsh/expert-advisor/runs/codex-readonly-20260926-003019-c8968d80.advice.md`。
- **顾问核心意见**：方案 A（读时归集）可行；但「未归集」按原始值列表展开（500 截断）会静默漏数——应在读路径用同一归集函数统一归集后再筛选；分页必须在筛选之后；保留旧载荷键并明确读时口径；明细建议加「归集后科室」辅助列；测试补充空白/Unicode、重复别名、超量未归集值、分页总数、规则变更后旧快照、并发保存。
- **主代理裁决（逐条）**：
  1. 「未归集」展开方案的缺陷**成立**——已核实 `_filter_options` 的 500 截断与 `view()` 整读行为后，改采**行级归集 + Python 过滤**（4.3 节重写），结构性消除截断漏数；性能上 `view()` 本就整读快照行（≤20000 既有读界），`rows()` 携带 section 时复用既有 thresholds 整读路径模式，无新量级成本。
  2. 分页在筛选之后——已核实 `rows()` 常规路径为 SQL `COUNT+LIMIT/OFFSET`（`db_manager.py:2481`）、thresholds 路径为 Python 过滤；section 筛选时统一走后者，切片与 total 在筛选后计算。
  3. 存储/API/旧载荷保留/明细口径/测试补充——按顾问意见采纳并落入 4.1/4.4/5/6 节；「归集后科室」辅助列降级为可选待用户拍板（本轮仅下发派生字段，不动 `values[]` 位置语义）。
  4. 「大快照下服务层筛选性能」风险——接受：读界 20000 为既有契约，典型快照 10²~10³ 行；若未来快照量级显著增长，再评估与归集函数语义一致的 DB 层筛选（注意 SQLite trim ≠ Python strip），本轮不做。
  5. 并发保存——本地单用户 + 单条 upsert 原子性足够，不做锁测试（顾问建议中的保守项，记录为已知取舍）。
- 置信度（顾问自评：中）经本地证据补齐后，主代理对方案定案的置信度：**高**。

## 10. 实施记录（2026-09-26）

- **改动文件**：新增 `core/section_rollup.py`、`tests/test_section_rollup.py`、
  `tests/test_deliverable_status_board_ui.py`；修改 `services/deliverable_form_analysis.py`
  （矩阵/计数聚合 + view/rows 行级归集筛选 + `_filter_options` 归集化）、
  `web/app.py`（GET/PUT `/api/project-status/section-rollup` + view/rows 接线 + view 下发
  `sectionRollup` 规则）、`web/static/app.js`（双分页看板、矩阵条形、归集面板/编辑器、
  页签配置调整）、`web/static/style.css`（看板与编辑器样式）、
  `tests/test_deliverable_form_analysis.py`（+3）、`tests/test_deliverable_form_api.py`
  （+4，2 处既有用例按归集口径更新）、`tests/test_deliverable_form_ui.py` 无需改动
  （tdc 页签契约保留）、`docs/USER_GUIDE_STANDALONE_EXE.md`（新增 6.16）、`PROJECT_MAP.md`（刷新）。
- **实施中发现并修复**：view() 无快照分支漏传 `section_rollup`（冒烟 21/22 时发现），
  修复后空快照也产出零矩阵。
- **门禁（最终轮实测）**：全量 `pytest -q -p no:cacheprovider` → **2425 passed, 3 skipped
  （exit 0，219.98s；基线 2403 → +22）**（`.runtime/pytest-full-rollup2.log`）；
  flake8 对全部改动文件零告警；`node --check web/static/app.js` 通过；
  `tools/generate_project_map.py --write && --check` → verified；
  冒烟 `.runtime/smoke_section_rollup.py`（临时库 + test client）**22/22 PASS**。
- **待用户（生产侧）**：提供完整「历史科室 → 现行科室」对照清单，在 WebUI 归集面板录入；
  生产构建（PyInstaller 打包）按需另行执行。

## 11. 代码审计与处置（2026-09-26）

- **审计**：用户要求实施完成后启动代码审计。code-reviewer（只读）按 A-F 清单（归集语义/分页正确性/
  兼容性/契约与安全/前端状态/测试缺口）完成审计：**1 Major + 2 Minor + 1 Nit，有条件合入**。
- **逐条核实与处置（全部成立，全部修复）**：
  1. [Major] 校验单趟遍历漏两类碰撞（alias==自身 target；前序 alias 撞后序 target）——后序目标会在
     `build_rollup_index` 中被别名抢占自绑定，导致看板丢行且归属错乱。→ **修复**：`validate_section_rollup`
     改两趟校验（第一趟收集全部目标名，第二趟别名对全部目标名 + 其他别名全量查重），并恢复同目标内
     重复别名拦截。
  2. [Minor] 未禁止系统保留名「未归集」作 target/alias（会造成矩阵重复行）。→ **修复**：target 与
     alias 均拦截保留名。
  3. [Minor] 手册 6.16 缺「携带历史科室值的旧深链需登记别名后才命中」说明。→ **修复**：已补。
  4. [Nit] 调试包 context 未含 sectionRollup（方案第 6 节核对项）。→ **修复**：注入
     `sectionRollupStore.get()`（经既有 redact 通道）。
  5. 测试缺口：补 4 项校验回归（自身同名/后序同名/保留名×2）+ 1 项 rows() 组合路径端到端
     （section 筛选 + overdueDaysStage 阈值重算 + 归集筛选 + 切片）。
- **审计后门禁（实测）**：聚焦 100 passed；全量 `pytest -q` → **2429 passed, 3 skipped（基线 2425 → +4）**
  （`.runtime/pytest-full-auditfix.log`）；flake8 改动文件零告警。
- **顾问复审状态**：用户要求将审计结果送 Codex 顾问复审。复审包
  `.runtime/consult-20260926-audit-review.md`（6,408 B）已制备并 dry-run 通过
  （sol-high / TASK-20260926-AUDIT-REVIEW）；live 调用因本地 5 小时滚动额度满（2/2，最早在窗启动
  2026-09-25 22:26:10，03:26:10 退出窗口）暂被阻塞，按契约不换档不绕过，窗口释放后即可发起。

## 12. 审计结果的 Codex 顾问复审（2026-09-26）

- **复审调用**：`codex-readonly --profile sol-high --caller zcode`，任务 `TASK-20260926-AUDIT-REVIEW`，
  包 `.runtime/consult-20260926-audit-review.md`（6,683 B，SHA-256 `ec8112f3…0a6330ec`），
  live 一次成功（exit 0；12,194 input / 683 output tokens；1 个非致命 error item，按契约仅计数）。
  等待本地 5 小时滚动额度于 03:26 释放后发起（22:26 的在窗启动退出窗口）。意见归档：
  `~/.dsh/expert-advisor/runs/codex-readonly-20260926-032757-51f90048.advice.md`。
- **顾问结论**：四项发现与定级均成立/可接受；两趟校验与保留名拦截方向正确；不建议引入 Unicode
  等价合并（保持现有 trim+精确匹配口径）。
- **主代理对顾问三项「修改/核实」要求的落实**：
  1. `all_targets` 只收合法目标：已核实代码——`all_targets.add` 仅在目标通过非空/长度/保留名/重复
     全部检查后的 `else` 分支执行，无效目标的别名不可能引发合法别名的误拒；
  2. 「备份导出」独立路径：已核实全项目不存在独立备份导出功能（方案原文措辞不严），唯一诊断导出
     路径即 debug bundle，已覆盖；
  3. 组织名称披露：调试包仅限本机操作者按需生成，包内既有 analytics/policy/mapping 已含更细的
     项目数据，科室名/别名不构成新披露类别，接受。
- **最终状态**：审计 4 项发现全部修复并经顾问复审认可；全量 2429 passed / 3 skipped、flake8 零告警、
  `node --check` 通过、项目地图 verified、冒烟 22/22（修复后复跑）。**本任务闭环。**
