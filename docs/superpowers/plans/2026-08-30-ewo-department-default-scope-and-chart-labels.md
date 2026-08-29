# EWO 部门默认范围、车型查找与自定义图表标签实施计划

> **Spec:** `docs/superpowers/specs/2026-08-30-ewo-department-default-scope-and-chart-labels-design.md`（六项决策已全部确认）
> **流程:** Main 定契约 → 子智能体撰写失败测试 → Main 审核 diff 并实现 → 聚焦验证 → code-reviewer → 全量回归 → 单次 commit `feat: EWO department scope, model search and chart labels`。

## Global Constraints

- 三个部门关键词 `EWO_DEPARTMENT_KEYWORDS = ("车体工程", "外饰", "内饰")` 为唯一口径来源，连接器 LIKE 表达式由其生成。
- `_rsp_department` 为空的行不进默认展示/统计，不静默推断；显式 `departments` 科室筛选优先于默认范围。
- 车型只匹配 `_modelinfo` 列（无标题兜底）；`carType` 保持回显锚点语义不参与过滤；`model` 筛选同时作用于 overview 统计与 items 明细。
- 标签上限 6 个/交付物；配置存 `app_settings`（键 `project_status_chart_labels:<id>`）；图表形式为"默认科室图 + 每标签一张图（tab 切换）"。
- `extra_fields_json` 捕获：≤60 键、键 ≤80 字符、值 `_safe_text` ≤200 字符、跳过敏感名称模式键与裸 GUID 键、保留 `__keyed_name`/`__name` 伴生键。
- 不改 TDC 逻辑、不新增依赖、不写凭据/敏感响应；`services`/`core` 不导入 Flask。

### Task 1: 数据层扩展（迁移、捕获、默认范围、连接器）

**Files:**
- Modify: `core/db_manager.py`（`source_department`、`model_info`、`extra_fields_json` 三列幂等迁移）
- Modify: `services/project_status_deliverable_analysis.py`（`EWO_DEPARTMENT_KEYWORDS`、三列捕获、`_item_is_in_scope` 部门默认范围）
- Modify: `services/project_status_connectors.py`（`rsp_department` LIKE 表达式替代 `rsp_smt`）
- Test: `tests/test_project_status_connectors.py`（反转两个既有断言）
- Test: `tests/test_ewo_department_stage_feature.py`（部门默认范围）
- Test: `tests/test_db_manager.py`（三列迁移幂等）
- Test: `tests/test_project_status_deliverable_analysis.py`（`source_department`/`model_info` 捕获与别名）

**Interfaces:**
- `normalize_analysis_rows` 行级新增 `source_department`（`_rsp_department` → "部门"等别名）、`model_info`（`_modelinfo`，strip ≤120）；`_item_is_in_scope`：`is_ewo and not department_values` 时要求 `source_department` 包含任一关键词（大小写不敏感子串）。
- 连接器两处 `EWOReportFilters(...)` 改为 `rsp_department="*车体工程*|*外饰*|*内饰*"`（由关键词常量生成），不再传 `rsp_smt`；`model_info` 查询条件不动。

### Task 2: 车型查找（服务层 + API）

**Files:**
- Modify: `services/project_status_deliverable_analysis.py`（`items`/`overview` 新增 `model`、`model_match` 参数与 `_model_matches`；非法 match 抛 `ValueError`）
- Modify: `web/app.py`（`model` ≤80、拒绝控制字符；`modelMatch∈{fuzzy,exact}`，非法 422）
- Test: `tests/test_project_status_analysis_api.py`
- Test: `tests/test_project_status_deliverable_analysis.py`

**Interfaces:**
- fuzzy：`query.casefold() in value.casefold()`；exact：`value.strip() == query.strip()`；`model_info` 为空的行不命中。
- `carType` 锚点回显行为回归不变。

### Task 3: extra_fields 捕获与自定义标签

**Files:**
- Modify: `core/db_manager.py`（`app_settings` 读写标签配置）
- Modify: `services/project_status_deliverable_analysis.py`（extra_fields 捕获、`EWO_FIELD_LABELS`、标签存取校验、`chart_groups`、`overview.customCharts`）
- Modify: `web/app.py`（`GET/PUT .../chart-labels`，本地写守卫）
- Test: `tests/test_project_status_deliverable_analysis.py`
- Test: `tests/test_project_status_analysis_api.py`

**Interfaces:**
- 服务层：`chart_labels(deliverable_id)`、`save_chart_labels(deliverable_id, labels)`（≤6 个、label 1-40 去空白拒绝控制字符、不重名；source_field 1-80 命中 `^[A-Za-z0-9_][A-Za-z0-9_\u4e00-\u9fff]*$` 且存在于最近缓存行字段集合，否则 `ValueError`）、`chart_field_candidates(deliverable_id)`（`[{key,label,count}]`，count 降序）、`chart_groups(deliverable_id, source_field, *, model=None, model_match="fuzzy")`（分组值 → `{total, completed, incomplete}`，范围口径同 items）。
- API：`GET chart-labels → {labels:[{label,sourceField,sortOrder}], fields:[{key,label,count}]}`；`PUT` 整体替换；`GET .../analysis` 响应新增 `customCharts: [{label, sourceField, groups}]`，未配置为 `[]`。

### Task 4: 前端（车型控件、标签管理、多图表）

**Files:**
- Modify: `web/static/app.js`、`web/static/style.css`、`web/templates/dashboard.html`（仅当需要挂载点）
- Test: `tests/test_overview_web.py`（Main 自写，与实现命名强耦合）

**Interfaces:**
- 明细工具栏新增车型输入（`analysis-model-input`）与模糊/精确切换（`analysis-model-match`，默认模糊，`aria-pressed`）；"应用筛选"提交 `model`/`modelMatch` 并重载分析面板与明细。
- 图表区 tab 切换（默认科室图 + 每标签一张图，`customCharts` 驱动）；"图表内容设置"弹层（`chart-labels-editor`）：标签名输入、字段下拉（候选来自 `fields`，显示中文名）、增删/保存（PUT）/取消。
- 未配置标签时行为与当前一致；候选框沿用第二轮不透明样式契约。

### Task 5: 回归与提交

- 聚焦测试 + `node --check` + `compileall` + `git diff --check` + 全量 `pytest -q`（输出落 `.runtime/`）。
- code-reviewer 审查（限流则 Main 等效自查并记录）。
- 已知 pre-existing 失败（4 个 overview-web 契约漂移 + 1 个 agent_supervisor）不在本任务范围，单独报告。
