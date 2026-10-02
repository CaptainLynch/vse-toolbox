# EWO 部门默认范围、车型查找与自定义图表标签设计

> 状态：**已确认**（2026-08-30，六项待确认决策全部按文档建议通过）
> 前序：`2026-08-30-ewo-department-stage-filter-design.md`（第一、二轮已完成）

## 背景与目标

科室经历过合并后，部门下发的 EWO 中 `_rsp_smt`（科室）字段混杂了大量科室值，第一轮固定的五科室白名单（车身科、车体科、外饰科、内饰科、车体架构集成科）已无法覆盖真实数据。本轮需求：

1. **默认范围改按部门匹配**：EWO 交付物的默认展示与统计不再以科室列（`_rsp_smt`）白名单为准，改为部门列（`_rsp_department`）包含"车体工程"、"外饰"、"内饰"字样的内容；同时为车型增加查找能力，支持"模糊查找（默认）"与"精确查找"两种匹配类型。
2. **自定义图表标签**：交付物明细支持用户自定义标签（如"内容A"、"内容B"、"内容C"），每个标签绑定 EWO 导出列表中的任意一个参数（如"XX科室"、"工程师"、"起草人"），图表按标签所绑定的字段分组展示统计内容。

不改变 TDC 逻辑、不新增第三方依赖、不写入凭据或敏感上游响应；阶段规则（open 排除、close 完成、八阶段规范化、大写显示/小写传参）与第二轮全部修复保持不变。

## 选定方案

### A. 部门默认范围（同步、统计、明细全链路）

**领域常量（唯一口径来源）**

```text
EWO_DEPARTMENT_KEYWORDS = ("车体工程", "外饰", "内饰")
```

- **同步层**：`ArasProjectStatusConnector` 不再把五科室并集填入 `rsp_smt`，改为把 `EWO_DEPARTMENT_KEYWORDS` 生成的包含匹配表达式填入 `EWOReportFilters.rsp_department`：

  ```text
  *车体工程*|*外饰*|*内饰*
  ```

  `services/aras_crawler.py` **无需改动**：现有 `_search_elements` 已支持 `|` 多值 OR 并集、值中含 `*` 自动使用 `condition="like"`、XML 转义、表达式长度 500 与备选数 10 的上限校验；`_rsp_department` 也已在 EWO 查询列（`DEFAULT_EWO_SELECT_FIELDS`）中，行数据会带回该列。查询层过滤避免拉全量后本地丢弃（延续第一轮设计原则）。
- **分析层**：`normalize_analysis_rows` 新增提取部门字段 `source_department`（别名优先级：`_rsp_department` → "部门"、"责任部门" 等既有部门别名；科室别名组中冒充部门的字样移除），与 `source_stage` 平行存储。`_item_is_in_scope` 对 EWO 来源的默认范围（未显式传阶段/科室筛选时）从"科室在五科室白名单内"改为"`source_department` 包含任一关键词"（大小写不敏感子串，输入先做去空白归一）。
- **显式筛选保留**：`departments` 科室多选筛选（重复键、20 项/120 字符/控制字符/去重/参数化）语义不变，仍然作用于 `_rsp_smt` 值；用户显式筛选时优先于默认范围。
- **历史缓存**：旧行 `source_department` 为空时不参与默认展示与统计，不做静默推断，下一次 EWO 同步重填（与 `source_stage` 回退原则一致）；VPI-T2-D3 的历史回退识别逻辑同样按新口径重算。
- **常量降级**：`EWO_DEFAULT_DEPARTMENTS`（五科室）不再作为同步/统计默认范围，仅保留为前端科室筛选候选列表的种子（合并后实际科室以缓存中出现的值为准合并展示）。

### B. 车型查找与匹配类型

- **匹配字段**：EWO 导出列表中的车型列 `_modelinfo`（同步连接器本就按 `model_info` 查询、行数据带回该列）。
- **匹配模式**：
  - `fuzzy`（默认）：查询词大小写不敏感的子串包含；
  - `exact`：查询词去空白后与字段值精确相等。
- **API**：`analysis/items` 与 `analysis` 新增 `model`（≤80 字符、去空白、拒绝控制字符，校验路径与现有 `carType` 一致）与 `modelMatch=fuzzy|exact`（默认 `fuzzy`，非法值返回现有 422 脱敏错误）。启用车型筛选时，`_modelinfo` 为空的行不命中。
- **与现有 `carType` 锚点的关系**：`carType` 维持"回显锚点"语义（显式传入优先，否则回退主计划名），**不参与过滤**；过滤只由显式传入的 `model` 触发。这样避免"不传车型时被锚点值意外过滤"的回归。
- **统计一致性**：`model` 参数同时作用于 `overview` 的摘要/图表重算与 `items` 明细列表（延续第二轮"列表、总数、统计同口径"原则）；不传则不过滤。
- **前端**：明细工具栏新增"车型"输入框与"模糊/精确"切换控件（segmented，默认模糊，带 `aria-pressed`），经"应用筛选"提交、"清除筛选"还原；空查询词 = 不按车型过滤。

### C. 自定义图表标签

**数据捕获**

- `project_status_analysis_items` 新增 `extra_fields_json TEXT`（幂等迁移，默认 `''`）。发布时从完整上游行（同步 Runner 已透传 crawler 的原始行）捕获字段快照：
  - 最多 60 个键；键名 ≤80 字符，值经 `_safe_text`（脱敏 + 截断 ≤200 字符）；
  - 跳过命中敏感名称模式（复用 `core/redaction.py` 的 `_SENSITIVE_NAMES` 规则）的键与 `created_by_id`、`modified_by_id` 等裸 GUID 键，保留 `__keyed_name`、`__name` 伴生显示键（如 `created_by_id__keyed_name` 即"起草人"显示名）；
  - 不存凭据、Cookie、原始响应体；任何键命中敏感模式即不入库。
- 标准字段（编号/标题/科室/部门/负责人/状态/日期）继续走既有列，`extra_fields_json` 只承载其余参数。

**配置存储**

- 复用既有 `app_settings(setting_key, value_json, updated_at)` KV 表，键 `project_status_chart_labels:<deliverable_id>`，值 JSON；**不新建表、无迁移**。
- 校验（服务层强制）：每交付物最多 6 个标签；`label` 1–40 字符（去空白、拒绝控制字符、同交付物内不重名）；`source_field` 1–80 字符且必须命中 `^[A-Za-z0-9_][A-Za-z0-9_\u4e00-\u9fff]*$` **并存在于该交付物最近缓存行的字段集合**（含标准字段与 `extra_fields_json` 键），否则返回 422 脱敏校验错误。

**API**

```text
GET /api/project-status/deliverables/<id>/chart-labels
    → {ok, data: {labels: [{label, sourceField, sortOrder}],
                  fields: [{key, label, count}]}}
      # fields = 最近缓存行中出现的候选字段（标准字段 + extra_fields 键），
      # label 为内置中文显示名映射（_rsp_smt→科室、_rsp_department→部门、
      # _rsp_name→负责人、created_by_id__keyed_name→起草人、_modelinfo→车型等），
      # 未映射的键原样显示，count 为该字段在缓存中的非空出现次数（便于挑选）

PUT /api/project-status/deliverables/<id>/chart-labels
    body: {labels: [{label, sourceField}]}   # 整体替换、参数化 SQL、沿用本地写守卫
    → {ok, data: {labels: [...]}}            # 校验失败 422，逐字段错误信息

GET /api/project-status/deliverables/<id>/analysis
    → data.customCharts: [{label, sourceField, groups: {分组值: {total, completed, incomplete}}}]
      # 每个标签按绑定字段分组统计，分组口径与摘要一致（同一默认范围 + 显式筛选）；
      # 分组值经脱敏截断；未配置时 customCharts 为空数组，前端回退现有科室图
```

**前端交互**

- 图表区在现有"各科室完成情况"图之后，为每个自定义标签渲染一张同构分组条形图（tab 切换或纵向排列，默认显示科室图）；分组统计的条形/颜色/点击行为复用现有组件。
- 图表区新增"图表内容设置"入口（齿轮/编辑按钮）→ 弹层管理：标签名称输入、绑定字段下拉（候选来自 `fields`，显示中文名 + 原始键兜底）、添加/删除、保存（调用 PUT）与取消；保存成功后重载分析面板。
- 未配置任何标签时，页面行为与当前完全一致。

## 模块职责

| 模块 | 改动 |
| --- | --- |
| `services/aras_crawler.py` | 无需改动（复用 `_search_elements` 的 like/OR/转义/上限） |
| `services/project_status_connectors.py` | 默认过滤表达式改为 `_rsp_department` 关键词 LIKE 并集，传 `rsp_department` |
| `services/project_status_deliverable_analysis.py` | `EWO_DEPARTMENT_KEYWORDS` 常量、`source_department`/`extra_fields_json` 捕获、默认范围包含匹配、`model`/`modelMatch` 过滤、自定义分组统计与标签校验 |
| `core/db_manager.py` | `source_department`、`extra_fields_json` 两列幂等迁移；`app_settings` 读写标签配置 |
| `services/project_status_sync_runner.py` | 无需改动（发布链路已透传完整行） |
| `web/app.py` | `model`/`modelMatch` 解析校验、`chart-labels` GET/PUT（本地写守卫）、`customCharts` 序列化 |
| `web/static/app.js` / `style.css` / `templates/dashboard.html` | 车型输入与模糊/精确切换、标签管理弹层、多图表渲染、候选框样式沿用第二轮不透明契约 |

## 测试与验收（TDD，先失败后实现）

- 同步层：AML 断言从 `_rsp_smt` 五科室**反转为** `_rsp_department` 三关键词 LIKE 并集；关键词常量单一来源；XML 转义与上限校验仍生效；`model_info` 查询条件不受影响。
- 范围与统计：`source_department` 捕获与别名优先级；默认范围包含匹配（含大小写/空白归一）；显式 `departments` 筛选仍生效且优先；历史空 `source_department` 行不进默认统计且不被静默改写；阶段规则与第二轮行为全部不变。
- 车型：fuzzy/exact 命中与不命中、`_modelinfo` 为空行行为、`modelMatch` 非法值 422、`carType` 锚点回显回归不变、model 筛选下 summary/items 同口径。
- 自定义标签：`extra_fields_json` 捕获上限、敏感键跳过、伴生键保留；标签 CRUD 校验（数量/长度/字符集/字段存在性/重名）；PUT 参数化与本地写守卫；`customCharts` 分组统计与范围筛选一致性；未配置时行为不变。
- 前端契约：车型控件与匹配类型切换、标签管理弹层、多图表渲染、候选框不透明样式回归断言（沿用第二轮 CSS 断言模式）。
- 回归：TDC/CLI 不受影响、无新增依赖、`pytest` 全量、`node --check`、`compileall`、`git diff --check`。

## 待确认决策

1. **部门关键词**：默认范围关键词就是"车体工程"、"外饰"、"内饰"三个字样，无其他？关键词区分大小写无意义（中文），但"外饰"也会命中"外饰科"等子串——包含式匹配是否符合预期？
2. **空部门行**：`_rsp_department` 为空的 EWO 行将不进入默认展示与统计（刷新同步后恢复），是否接受？
3. **车型匹配字段**：建议匹配 EWO `_modelinfo` 列；模糊模式是否需要兜底匹配标题 `_subject`（如"F610S 蒙皮总成更改"）？建议：仅 `_modelinfo`，保持语义干净。
4. **车型筛选作用范围**：建议同时作用于统计摘要/图表与明细（口径一致），还是仅明细列表？建议前者。
5. **自定义标签上限**：建议每交付物 6 个；图表展示形式建议"默认科室图 + 每标签一张图（tab 切换）"，是否认可？
6. **科室多选筛选**：保留现状（作用于 `_rsp_smt`），仅默认口径变更——确认？

## 实施流程（确认后启动）

Main 编写实施计划（`docs/superpowers/plans/`，按 TDD 任务拆分）→ 分派子智能体执行有界任务（测试撰写 / 机械实现）→ Main 逐任务审核 diff、运行聚焦验证 → code-reviewer 审查 → 全量回归 → 单次清晰 commit。
