# D5 项目件/架构件归集 — 代码与架构评审记录（2026-10-23）

- **任务**：`TASK-REVIEW-D5-REPORT-20261023`
- **分支**：`feat/d5-arch-part-attribution`
- **base**：`fe12ed6f177536badea8d510339f24d760c7d319`
- **head**：`4f4dca3dae6f1bac4797a971008bceb9ba78bb5e`
- **评审范围**：仅本地这 2 个提交（`46d0f9e` feat、`4f4dca3` docs/memory），共 9 个文件、+1154/−10。
  **未 fetch**，**未审** `main..HEAD` 的其余提交，**未审**工作区既有未提交改动与未跟踪文件；
  本轮**不修改**生产代码与测试代码。
- **结论**：**建议暂不合并**。R1 是本次改动引入的新回归；R2 是交付范围/入口缺口；
  R3、R4 影响历史口径与辅助汇总，应按影响修复或明确限制后再对外使用统计数字。

> 本文只依据本地代码、聚焦测试与合成数据核实，不代表全量回归、真实内网、真实浏览器或打包验证。
> 合成数据均为虚构车型/单号，不含敏感或真实业务数据。

---

## 1. 变更与评审边界

| 项 | 事实 |
| --- | --- |
| 提交数 | 2（`46d0f9e`、`4f4dca3`） |
| 文件数 | 9 |
| 行数 | +1154 / −10 |
| 主要生产改动 | `services/data_model_attribution.py`（新增）、`services/deliverable_form_analysis.py`、`core/form_registry.py` |
| 文档/记忆 | `PROJECT_MAP.md`、`docs/DM_RELEASE_STATS_MERGE_PLAN_20261022.md`、`memory/CURRENT_STATE.md`、`memory/DECISIONS.md` |
| 测试 | `tests/test_data_model_attribution.py`（新增）、`tests/test_deliverable_form_analysis.py` |

评审边界：

- 只评这两个本地提交，不把 `main` 之后的其他改动、工作区 dirty 文件或未跟踪文件算进结论。
- 不声称“全量回归通过”“真实内网通过”“打包通过”。历史记忆里的 3244 passed 是既有记录，不是本轮执行结果。
- 本轮只写 `docs/CODE_REVIEW_D5_20261023.md` 与 `memory/CURRENT_STATE.md`，不修任何发现。

---

## 2. 发现清单（均未修复）

### R1 [P1] 新回归：D5 复合分组标签被当作 `stage` 筛选值，点击柱条后结果归零

**代码位置**

- `services/deliverable_form_analysis.py:1630`：`label = _attribution.group_label(dimensions)`
- `services/deliverable_form_analysis.py:1637`：阶段行载荷 `{"label": label, ...}`
- `plugins/project_overview/static/deliverable/form-analysis.js:218`：
  `appendFormFilter(state, filterKey, row.label)`
- `plugins/project_overview/static/deliverable/form-analysis.js:570`：D5「项目状态」走
  `StatusBars ... filterKey="stage"`
- `plugins/project_overview/static/deliverable/form-state.js:158-173`：把 label 原样写入
  `filters.stage`（多值数组）
- `core/db_common.py:366-378`：`stage` 过滤映射到 `r.stage_key IN (...)`；`stage_key` 存的是原始
  `stage`（如 `Ar-L`、`F620S`），不是复合标签

**触发输入（合成）**

- 项目件行：`项目/车型=F620S`、`流水单号=F620S-3D-0075`
- 架构件行：`项目/车型=Ar-L`、`EWO/SOR号=SGMW-F620S-SOR0001`、`流水单号=Ar-L-3D-0002`

**实际行为（本轮实跑）**

- 图表分组标签：`['F620S · 项目件', 'F620S · 架构件']`
- 用复合标签作为 `stage` 过滤：
  - `F620S · 架构件` → `total=0`
  - `F620S · 项目件` → `total=0`
- 用原始 `stage` 过滤：
  - `Ar-L` → `total=1`
  - `F620S` → `total=1`
- Node 侧确认 `appendFormFilter(state, "stage", "F620S · 架构件")` 后：
  `applied_filters={"stage":["F620S · 架构件"]}`。

**影响**

- 点击 D5「项目状态」任意柱条（项目件与架构件都受影响）会把明细表筛成 0 行。
- 图表显示“有数据”，点击后却“查不到”，属于用户可见的新回归；不是历史缺陷。
- 当前可确认的影响是 `project_overview` 交付物详情页的 D5 图表交互；不影响数据存储本身。

**修复方向（契约级建议，本轮不实现）**

- 把“展示标签”和“筛选值”分离：阶段行额外下发机器可读的 `vehicle`/`dataSource`/`archPlatform`
  或原始 `stage`，前端按明确字段筛选；或在 SQL 过滤层支持 `vehicle + dataSource` 组合。
- 在筛选语义落地前，对复合分组禁用点击，避免给出错误交互。
- 补回归测试：D5 柱条点击 → 过滤条件 → 读取行数必须与柱条 `total` 一致。

---

### R2 [P2] 独立表单插件页仍只展平旧维度、按 `_stage` 分组，D5 继续分开 F620S 与 Ar-L

**代码位置**

- `core/form_registry.py:168-170`：D5 仅登记 `dataSource`/`vehicle`/`attribution` 三个维度显示名
  （未登记 `archPlatform`）。
- `plugins/deliverable_forms/backend.py:36`：`DIMENSIONS = ("department", "section", "model", "stage")`
- `plugins/deliverable_forms/backend.py:60-61`：只展平上述四个维度为 `_department`/`_section`/
  `_model`/`_stage`
- `plugins/deliverable_forms/static/pages/tdc_data_model.json:18-21`：筛选项 `_stage`「项目 / 车型」
- `plugins/deliverable_forms/static/pages/tdc_data_model.json:49`：图表 `groupBy: "_stage"`
- `web/static/host/pages.js:37-47`：`groupName`/`summarizeDone` 直接按 `row[groupBy]` 分组

**触发输入（合成）**

- 同 R1 的两行数据，经 `normalize_form_rows` → `plugins.deliverable_forms.backend.flatten_rows`。

**实际行为（本轮实跑）**

- 展平输出维度键：`['_department', '_section', '_model', '_stage', '_submitted', '_status',
  '_completed', '_overdue']`
- `_stage` 值：`['Ar-L', 'F620S']`
- 不存在 `_dataSource` / `_vehicle` / `_attribution` / `_archPlatform` 字段。
- 页面 schema 分组键：`['_stage', '_section']`。
- 因此该页仍把 `F620S` 与 `Ar-L` 分成两组，看不到「F620S · 项目件 / F620S · 架构件」归集效果。

**影响**

- 实施文档 `docs/DM_RELEASE_STATS_MERGE_PLAN_20261022.md:14` 所称「当前分组标签已可在现有图表直接呈现」
  只对 `project_overview` 交付物详情页（服务端 `departmentStatus` 标签）成立；
  对独立 `deliverable_forms` 表单页这个生产入口**不成立**。
- 属于交付范围/入口口径缺口，不是数据损坏；但会让用户在不同入口看到不同分组。

**修复方向（契约级建议，本轮不实现）**

- 在 `flatten_rows` 中展平 D5 归集维度，并给页面 schema 增加 `groupBy`/筛选项（如
  `_vehicle + _dataSource`），或明确只在 `project_overview` 详情页提供归集视图。
- 若短期不做，应在实施文档与发布说明中限定“归集展示仅限交付物详情页”，不得声称独立表单页已合并。

---

### R3 [P2] 旧快照读取兜底只用 `stage`，不读保留的 `values` 中 SOR/流水证据

**代码位置**

- `services/data_model_attribution.py:176-177`：旧快照缺归集键时
  `fallback = dimension_fields(stage)`（只传 `stage`，不传 EWO/SOR 号与流水单号）
- `services/data_model_attribution.py:159-191`：`resolve_dimensions` 的兜底路径
- `services/deliverable_form_analysis.py:1525-1573`：`_metric_rows` 只做状态/完成度兼容，不重算归集
- `services/deliverable_form_analysis.py:2600-2627`：`view()` 直接读取已存行并汇总，读取路径不重新归一化

**触发输入（合成）**

- 模拟旧快照行：`dimensions={"stage":"Ar-L","status":"审批中",...}`，
  但 `values` 中仍保留 `EWO/SOR号=SGMW-F620S-SOR0001`、`流水单号=Ar-L-3D-0002`。

**实际行为（本轮实跑）**

- 新写入口径：`dimension_fields("Ar-L", "SGMW-F620S-SOR0001", "Ar-L-3D-0002")` →
  `{'dataSource': '架构件', 'vehicle': 'F620S', 'attribution': 'SOR号证据', 'archPlatform': 'Ar-L'}`
- 旧快照读取兜底：`resolve_dimensions({"stage":"Ar-L",...})` →
  `{'dataSource': '架构件', 'vehicle': '', 'attribution': '平台池', 'archPlatform': 'Ar-L'}`
- 旧行汇总标签：`['待归属 Ar-L · 架构件']`
- 同时确认旧行 `values` 中的 SOR 证据仍在（`SGMW-F620S-SOR0001`），只是读取侧没用它。

**影响**

- 本分支之前发布的 D5 快照，架构件行即使原始 `values` 里有 SOR/流水证据，也会被读成平台池。
- 新快照按新口径、旧快照按旧兜底，混读时同一份数据会出现口径不一致；只能等重新同步后消失。
- 不丢原始数据、不回写错误值，但历史统计与完成率会偏差。

**修复方向（契约级建议，本轮不实现）**

- 读取兜底时从保留的 `values` 按表单定义恢复 `EWO/SOR号` 与 `流水单号`，再走同一套
  `dimension_fields`；或对旧快照做一次显式重投影/重新同步，并在 UI 标注口径版本。
- 无论选哪条，都应保证新旧快照不会在同一图表里被当成同一口径。

---

### R4 [P2] 辅助 `summarize_instances` 分组键缺平台维度，平台池实例被合并

**代码位置**

- `services/data_model_attribution.py:325-326`：
  `resolved = resolve_instance_dimensions(...)`；`key = (resolved["vehicle"], resolved["dataSource"])`
- `services/data_model_attribution.py:361-368`：`group["label"] = group_label({...})`，平台池标签取
  首个非空 `archPlatform`

**触发输入（合成）**

- 实例 i1：`Ar-L` / `TBD` / `Ar-L-3D-0002` → 平台池
- 实例 i2：`Ar-L+` / `EWO-030090` / `Ar-L+-3D-0005` → 平台池

**实际行为（本轮实跑）**

- `summarize_instances` 输出 **1 组**：
  `{'label': '待归属 Ar-L · 架构件', 'vehicle': '', 'dataSource': '架构件',
  'archPlatform': 'Ar-L', 'total': 2}`
- `Ar-L+` 的平台信息被合并掉。
- 对照生产逐行分组（`_stage_status_summary`）：输出
  `[('待归属 Ar-L · 架构件', 1), ('待归属 Ar-L+ · 架构件', 1)]`，确认生产阶段图不受该合并影响。

**影响**

- 该函数目前是辅助汇总函数；生产 D5 阶段图走 `_data_model_group_status`（逐行
  `group_label`），平台池会分别输出「待归属 Ar-L · 架构件」与「待归属 Ar-L+ · 架构件」，
  **不受此合并影响**。
- 但若后续把实例级汇总当主指标（实施文档确实把它列为方向），平台池会少一个维度，
  无法按平台解释数量。

**修复方向（契约级建议，本轮不实现）**

- 平台池分组键加入 `archPlatform`（例如 `(vehicle, dataSource, archPlatform if pool else "")`），
  或在输出中提供按平台的拆分字段。
- 明确该函数的消费范围；在成为主指标前补平台维度回归测试。

---

## 3. 非回归架构观察（不是本次新回归）

- `summarize_instances` / `summarize_vehicles` 目前**没有生产调用点**：全仓检索只命中
  `services/data_model_attribution.py` 自身与 `tests/test_data_model_attribution.py`。
- 主 API、`view()`/`rows()` 与前端仍是**行级口径**；D5 阶段图由 `_data_model_group_status`
  逐行 `group_label` 聚合。
- 实施文档把实例级列为统计粒度方向，但 `docs/DM_RELEASE_STATS_MERGE_PLAN_20261022.md:14`
  仍把「前端三行渲染与数据来源筛选下拉」标为待做。**这是口径/交付范围缺口**，
  不应表述为“本次改动引入的新回归”，也不应据此宣称实例级主指标已交付。

---

## 4. 验证命令与结果（本轮实跑）

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `git rev-parse HEAD` | `4f4dca3dae6f1bac4797a971008bceb9ba78bb5e` |
| 2 | `git diff --stat fe12ed6..4f4dca3` | 9 files changed, 1154 insertions(+), 10 deletions(-) |
| 3 | `git log --oneline fe12ed6..4f4dca3` | `4f4dca3` docs(memory)、`46d0f9e` feat(d5) |
| 4 | `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_data_model_attribution.py tests/test_deliverable_form_analysis.py -p no:cacheprovider -q --no-header` | **105 passed / 0 failed / 0 skipped，0.95s，exit 0** |
| 5 | `git diff --check fe12ed6..4f4dca3` | exit 0 |
| 6 | `python tools/generate_project_map.py --check` | `Project map verified`，exit 0 |
| 7 | 系统临时目录合成 D5 数据 + SQLite（脚本在工作区外，运行后删除） | 复合 label 过滤 `total=0`；原始 `Ar-L`/`F620S` 各 `total=1`；flatten 仅旧维度；旧快照读为平台池；`summarize_instances` 两平台实例合并 `total=2`；exit 0 |
| 8 | Node 24.15.0 调用 `appendFormFilter(state,"stage","F620S · 架构件")` | `applied_filters={"stage":["F620S · 架构件"]}`，exit 0 |
| 9 | `git diff --check HEAD -- docs/CODE_REVIEW_D5_20261023.md memory/CURRENT_STATE.md`（临时 `GIT_INDEX_FILE`，不改真实 index） | exit 0（仅 Git 提示工作副本 LF 将在下次触碰时转 CRLF） |

补充说明：

- 第 4 项是**聚焦测试**，不是全量回归；历史 3244 passed 记录不作为本轮结果。
- 第 7 项使用系统临时目录中的 SQLite 文件（`DatabaseManager` 每次连接重新打开，
  `:memory:` 无法跨连接保留），临时库与脚本均已清理；未向工作区写入测试源码。
- 第 1 项之外的 `git status` 中，`.gitignore`、`tools/agents/README.md` 及若干未跟踪文件
  是本 workflow 开始前就存在的 dirty 状态，本轮未触碰。

---

## 5. 变更文件清单（本 workflow）

| 文件 | 动作 |
| --- | --- |
| `docs/CODE_REVIEW_D5_20261023.md` | 新增（本报告） |
| `memory/CURRENT_STATE.md` | 在文件顶部新增本轮评审检查点，原有内容完整保留 |

未修改：`core/**`、`services/**`、`plugins/**`、`host/**`、`web/**`、`tests/**`、`tools/**`、
`.gitignore`、`PROJECT_MAP.md`、`data/**`，以及 git 引用、任务板。

---

## 6. 未完成项与原因

1. **未运行全量 pytest**：任务明确禁止；本轮只跑两个聚焦测试文件，不能据此声称全量回归通过。
2. **未 fetch、未审 `main..HEAD` 其余提交、未审未提交改动**：评审范围限定为本地 2 个提交。
3. **未做真实内网/真实浏览器/打包验证**：无相应环境与授权；合成数据只验证代码路径。
4. **未修复 R1–R4**：本 workflow 的验收目标就是“记录真实缺陷”，修复安排等待主控/用户。
5. **未验证 `archPlatform` 在独立表单页的展示**：该维度当前未展平、未登记，属于 R2 的修复内容。

---

## 7. 结论

- **暂不合并**：R1 是本次改动引入的用户可见新回归，应优先修复并补柱条点击回归测试。
- R2 需要修正交付范围声明或补独立表单页；R3 影响历史快照口径，需修复或明确版本边界；
  R4 限于辅助汇总函数，可在实例级指标正式启用前修复。
- 本报告不把源码现存缺陷视为本 workflow 的待修项；本 workflow 的交付物是**真实、可复核的记录**。
