# 生产测试问题分析：交付物数据同步（2026-09-22 变更）

范围：`ce0523c`（已提交）+ 工作区未提交的「交付物同步向导极简策略同构化」改动。
结论优先级：代码/测试 > 本地库实证 > 推断。

---

## 问题 1：PAA 交付物 / NCR 审批明细 / NCR 审批进度 没有「数据同步」按钮

### 现象（与截图一致）
- `#deliverable/VPI-T2-D6|D7|D8` 详情页只显示：
  - 「更新方式」+ 静态文案「该交付物由定时归档的表单快照驱动，状态自动映射，暂无独立状态同步。」
  - 折叠区「外部同步与技术证据（点击展开）」
  - 表单分析区显示「暂无表单快照数据」
- 没有任何「开启自动同步 / 立即同步 / 修改同步配置」入口。

### 根因（设计口径 + 未启用数据源，两者叠加）

1. **能力门控**：`core/project_status_contracts.py:583-627` 中 D6/D7/D8 为
   `syncCapable=False`、`formSnapshotDriven=True`、`countsTowardCompletion=False`。
2. **前端分支**：`web/static/app.js:2829` `if (capabilities && capabilities.syncCapable)`；
   非 syncCapable 走 `:2864-2871`，只渲染「更新方式」静态文案，
   **永不调用 `buildSyncSummaryCard`** → 数据同步卡（含三个按钮）不渲染。
3. **死按钮**：证据面板里的「运行后台同步」按钮 `app.js:3501`
   `syncBtn.disabled = !syncSupported || !syncReady`，D6-D8 恒为 `disabled`，
   且 title 为「不可同步：该交付物不支持外部同步」。这就是用户感知的「没有按钮」。
4. **真实数据源未运行**：这三个交付物的数据来自定时归档任务
   （`DELIVERABLE_LINK_REGISTRY`：`aras_paa→D6`、`aras_ncr_progress→D7`、`aras_ncr_detail→D8`，
   `core/project_status_contracts.py:37-54`）。本地库实测：
   - `scheduled_archive_jobs` 6 个内置任务 **全部 `enabled=0`、`credential_ref=NULL`**；
   - `scheduled_archive_runs` **0 行**；
   - `deliverable_form_snapshots` 仅 3 条（tdc_data_model / aras_ncr_progress / tdc_sor，来源 run 101-103）。
   → 因此 PAA / NCR 明细必然显示「暂无表单快照数据」。
5. **唯一可用的同步路径被前端禁用**：`#archive-deliverable/<job_key>` 页（`app.js:7509`）
   的「后台归档同步」按钮 `disabled = !job.enabled`（`app.js:7589`），任务未启用即不可点。
   注意后端 **并不要求 enabled**：`POST /api/scheduled-archive/jobs/<job_key>/sync-now`
   → `ScheduledArchiveAdminService.sync_now`（`services/scheduled_archive_admin.py:350`）
   只校验 job_key 存在，未校验 enabled；阻塞完全来自前端。

### 判定
不是回归，是 2026-09-20 定下的「D6-D8 外部快照驱动、只读、不进分母」设计在
「用户需要一个可点的同步入口」这一产品预期上未被满足；同时这批交付物的
归档任务在生产机上是否启用、是否从未跑过，需要确认。

---

## 问题 2：数模设计审核流程报表（D5）数据同步报错

### 现象（截图）
向导内红字：**「配置启用失败：映射发现未匹配（未找到），请核对车型与筛选条件后重试。」**
输入：车型项目 `F610S`、责任部门 `技术中心_车体工程`、周期 15 分钟、流程编号留空（聚合）。
该文案出自 `web/static/app.js:2068`，`state=not_found` → `ewoPolicyDiscoveryStateLabel` → 「未找到」（`app.js:1591`）。
即：**TDC 请求成功返回，但该筛选组合命中 0 行记录**。

### ✅ 生产三点对照实验（用户 2026-09-22 19:39~19:40 在「系统查询 → TDC 数模」面板实测）

| 组 | 筛选条件 | 返回结果（面板 preview 统计行） | 结论 |
| --- | --- | --- | --- |
| **A** | 部门：`技术中心_车体工程`；项目车型：`F610S` | `page=1/1 rows=0 unique=0 dup=0` + 「当前筛选条件下未返回任何交付物数据」 | **复现故障** |
| **B** | 项目车型：`F610S`（部门留空） | `page=1/22 rows=50 unique=50 dup=0` | 有数据，范围最宽 |
| **C** | 部门：`车体工程`；项目车型：`F610S` | `page=1/17 rows=50 unique=50 dup=0` | 有数据，且部门维度有效收窄 |

另：A 组为 0 行、B/C 组均有数据 → **项目车型维度正确，唯一错误维度是部门取值**；
C 组结果行 `department` 列实际显示为「车体 / 内饰」级名称，与 `tests/test_report_contracts.py:296`
的 `superDepartment="车体工程"` 一致。

**→ 主因判定已确认：向导预填的 Aras 域值 `技术中心_车体工程` 在 TDC 部门（`superDepartment`）维度上 0 命中。**

### 根因（命名空间错配，**已由上述生产实测确认**）

**主因**：最近一次（未提交）改动把 **Aras 命名空间的默认责任部门** 无条件套用到 **TDC** 查询。

1. 向导代码 `app.js:1972` `const deptVal = ewoPolicyString(departmentInput.value) || "技术中心_车体工程";`
   `app.js:2034-2037`（D5 分支）与 `:2021-2024`（D2 分支）**只要非空就写入 `filters.department`**；
   而 `:1863-1868` 的预填默认值就是 `技术中心_车体工程`。用户无法清空（读取时又 `|| 默认值`）。
2. 该值在 TDC 侧的落点：
   - D5：`filters.department` → `_MAPPING_DISCOVERY_RULE_FIELDS[("tdc","data_model")]` → 规则键 `department`
     → `TDCDataModelFilters.department` → HTTP 参数 **`superDepartment`**
     （`services/tdc_crawler.py:202`；`services/tdc_contract_probe.py:920` 同口径）。
   - D2：→ `TDCSORFilters.department` → HTTP 参数 **`deptName`**（`tdc_crawler.py:244` 附近）。
3. **TDC 域值 ≠ Aras 域值**（权威字段合同证据）：
   - `tests/test_report_contracts.py:288-311`（`table_payload("tdc_data_model", …)` 合同）：
     `"department": "外饰科"`（= 科室级，报表第 5 列）与 `"superDepartment": "车体工程"`（= 部门级）。
   - `tests/test_report_contracts.py:351`：TDC SOR 的 `deptName = "车体工程"`。
   - `services/aras_department_mapping.py:19-20`：把「技术中心-车体工程」归一为「**技术中心_车体工程**」——
     这是 **Aras** 的口径（`_rsp_department` / PAA `department` / EWO `responsibleDepartment`，
     见 `core/db_manager.py:1771-1783` 内置归档任务过滤器）。
   - 本地库真实快照行（`deliverable_form_rows`，`tdc_data_model` snapshot 1）：
     `department` 实际取值 `外饰科 / 内饰科 / 车身科 / 底盘科`；`projectModel` 取值 `F999X / F888Y`；
     SOR 快照 `deptName` 取值 `内饰开发部 / 底盘开发部 / 电子电器部 / 车身开发部`。
   → `superDepartment=技术中心_车体工程` 必然 0 命中。
4. **回归性质**：`ce0523c` 版本的向导只收集「凭据引用 + 外部编号」，D5 只发
   `filters.serial_number=<流程编号>`、无部门维度；未提交改动新增了
   车型/部门/周期三个输入并把 `aggregate` 默认置为 true（`git diff web/static/app.js`：
   `+ const aggregate = !specificNo;`、`+ if (deptVal) { matchRule.department = deptVal; filters.department = deptVal; }`），
   从此 D5/D2 的取证请求必然带上错误的部门维度 → 一键向导再也跑不通。
5. 次要放大因素：
   - 报错文案只说「核对车型与筛选条件」，未暴露 `candidateCount=0` 与
     `fieldReport.fields.length`，用户无法区分「0 行」与「有行但无单号」。
   - 若之前按旧口径（仅流程编号）成功过，则老证据的 `config_signature` 与新规则不同，
     会被判定为不一致并重置（`core/project_status_records.py:compute_config_signature`）。
   - `app.js:2060` 仅在 `!aggregate` 时才提供候选选择；聚合模式的 `ambiguous` 直接硬失败。

### 同源风险（需一并回归）
- **D2（TDC SOR）**：同样被塞入 `技术中心_车体工程`，落点为 `deptName`，
  与实测值域（开发部级 / `车体工程`）不符 → 预计同样 0 行失败。
- **D3（Aras EWO）**：`技术中心_车体工程` 是其正确命名空间，但改前缺省是
  LIKE 关键词表达式 `*车体工程*|*外饰*|*内饰*`（`services/project_status_deliverable_analysis.py:56-66`，
  `_mapping_discovery_query_identity` 仅在缺省时注入），改动后变成**精确值**，存在范围收窄/精确匹配失败的风险。

---

## 需要用户提供的输入

### 问题 2（决定性，按优先级）
> **P2（三点对照实验）已由用户完成并确认主因，见上文实测表。**
> **P1（取证记录）仍建议回传，用于确认「0 行」而非「有行但无业务单号」这一分支，并留档。**

1. **失败后立刻采集 D5 取证证据**：交付物详情页 →「外部同步与技术证据」展开 →
   或直接 `GET /api/project-status/deliverables/VPI-T2-D5/mapping-discovery`。
   需要：`state`、`candidateCount`、`fieldReport.fields`（字段名列表）、`createdAt`。
   - `fields` 为空 → 确认「0 行」（与实测表一致）；
   - `fields` 非空但 `candidateCount=0` → 是身份字段口径问题（改查 `project_status_records.IDENTITY_FIELDS` 与真实行键）。
2. ~~三点对照实验~~ **已完成（A 组 0 行 / B 组 22 页 / C 组 17 页）**，无需重做。
3. **脱敏调试包**：`GET /api/project-status/deliverables/VPI-T2-D5/debug-bundle?format=zip`
   （白名单 + 脱敏 + 20 条运行事件，`web/app.py:4807`），以及
   `GET /api/project-status/runs?deliverableId=VPI-T2-D5&limit=10`。
4. 生产机上 TDC 数据源的**可见范围**：该账号在 TDC 里按 `F610S` 能否查到数模单据；
   是否只有特定部门/科室（如车体工程/外饰科）可见。
5. 需要确认的**语义口径**：「责任部门 = 技术中心_车体工程」在 TDC 里应当映射到
   哪个层级？（我按现有合同判定为「部门级 `superDepartment`，值域形如 `车体工程`」，
   科室级 `department` 值域形如 `外饰科`。）

### 问题 1
6. 生产机 `GET /api/scheduled-archive/jobs`：6 个任务的 `enabled`、
   `credentialConfigured`、`credentialAvailable`、`lastSuccessAt`（重点 aras_paa /
   aras_ncr_progress / aras_ncr_detail），以及「自动归档」页当前显示。
7. **产品决策**（决定实现形态，三选一）：
   - A（推荐）D6-D8 详情页直接提供「立即同步快照」——触发对应归档任务 `sync-now`，
     **不要求先启用定时任务**（后端已支持，仅前端门控需放开）；
   - B 必须先到「自动归档」启用任务（需统一域账号凭据）后，详情页才可同步；
   - C 维持只读，仅把文案改成「请到自动归档启用/运行 X 任务」的明确指引。

---

## 方案

### 问题 2（主因修复，前端 + 契约）

> **立即缓解（不改代码即可用）**：D5 的数据现在就能拿到——
> 「系统查询 → TDC 数模设计审核流程报表」，筛选 `部门=车体工程` + `项目车型=F610S`
> （或部门留空），即可 `rows=50 page=1/17`（或 `1/22`），再走全量抓取 / 下载 XLSX。
> 仅「向导一键启用自动同步」这条路被错误的部门默认值挡住。

1. **按来源区分责任部门默认值**（`web/static/app.js` 向导）：
   - Aras/EWO：保留 `技术中心_车体工程`（并保持既有 LIKE 关键词口径）；
   - TDC/D2、D5：默认值候选二选一（**待用户确认**）：
     - **(C) `车体工程`** —— 与「只统计车体工程部门」的原始意图等价，实测 `page=1/17 rows=50`；
     - **(B) 留空** —— 范围最宽，实测 `page=1/22 rows=50`，但会把其他部门单据一并纳入聚合；
   - 无论取哪个，**读取时都不再 `|| 默认值`**，允许用户清空；placeholder 明确
     「TDC 部门（如 车体工程）；请勿填写 Aras 形式 技术中心_车体工程」。
2. **TDC 部门归一化**（新增纯函数，对标 `services/aras_department_mapping.py`）：
   把误填的 Aras 形式 `技术中心-车体工程` / `技术中心_车体工程` 归一为 TDC 域值 `车体工程`
   （同时覆盖「高级设置」里手填该值的同款陷阱），并在向导提示中明确两个系统命名空间不同。
3. **修正 D5 matchFields 语义与标签**（`core/project_status_contracts.py`）：
   区分「部门（HTTP `superDepartment`，值域 车体工程 级）」与「科室（HTTP `department`，值域 外饰科 级）」，
   同步刷新 `fieldSemantics`，避免 UI 把两者混同（当前 HTTP 参数名与报表列名互为倒置，是陷阱点）。
4. **失败可自愈 + 可诊断**（`app.js:2067-2069`）：
   - 聚合模式下若 `not_found` 且带了部门筛选，自动降级重试一次（**去掉部门维度**），
     仍失败才硬停；
   - 错误文案补充 `candidateCount` 与 `fieldReport.fields.length`，
     明确区分「返回 0 行」与「有行但无业务单号」。
5. **回归验证**：D2 同源修复；D3 精确部门 vs LIKE 范围对比；D5 端到端一键启用。
6. **测试**：更新 `tests/test_deliverable_sync_wizard_enhanced.py`（现断言向导恒含
   `技术中心_车体工程`，需改为按来源断言）；新增「TDC 向导留空部门时 payload 不含
   `filters.department`」、「D5 聚合取证 not_found 自动降级重试」契约测试。

### 问题 1（补一个真正可用的同步入口）
1. **后端下发关联任务键**（`web/app.py` `/api/project-status` 的 `sourceInfo`）：
   由单一关联注册表派生 `archiveJobKey`（需补一个「按 deliverable_id 反查含 job_key 的条目」
   的纯函数；`DELIVERABLE_LINK_REGISTRY` 已含 `catalog_id/display_code/form_key`）。
2. **前端新增快照驱动分支**（`app.js:2864` 非 syncCapable 分支内，按 `formSnapshotDriven` 细分）：
   渲染「数据同步（外部快照）」卡：快照来源任务、最近快照时间/行数、最近同步状态与错误，
   按钮【立即同步快照】（`POST /api/scheduled-archive/jobs/{jobKey}/sync-now`）、
   【查看同步任务】（`#archive-deliverable/{jobKey}`）；任务未启用时给出
   「去自动归档启用」的明确指引（而不是灰按钮）。
3. **清理误导性控件**：非 syncCapable 交付物不再渲染永久 disabled 的「运行后台同步」。
4. **测试**：后端断言 D6-D8 的 `sourceInfo.archiveJobKey`；前端 Node VM 契约测试断言
   三个交付物渲染出快照同步卡且按钮指向归档端点；`tests/test_overview_web.py`、
   `tests/test_deliverable_sync_summary_ui.py` 同步更新。

### 验收
- `python -m pytest tests/test_project_status_*.py tests/test_deliverable_*.py tests/test_overview_web.py -q`
- `python -m flake8`（须 `-j 1`）、`node --check web/static/*.js`
- `python tools/generate_project_map.py --check`
- 生产复测：D5 一键启用成功并首次同步；D6/D7/D8 详情页可点【立即同步快照】并生成快照。

---

## 附录：生产取证清单（待用户回传，可直接复制执行）

> 说明：以下端点均为本机 WebUI（默认 `http://127.0.0.1:<port>`），
> 返回值为脱敏/白名单内容；不需要提供任何口令、Cookie 或 Token。

**P1 — D5 取证证据（最关键，决定主因是否成立）**
1. 浏览器打开 `GET /api/project-status/deliverables/VPI-T2-D5/mapping-discovery`
   → 回传最新一条观测的 `state`、`candidateCount`、`fieldReport.fields`（整份 JSON 亦可）。
2. 或页面操作：交付物 → 数模设计审核流程报表 → 展开「外部同步与技术证据」→ 采集映射证据卡。
   - `state=not_found` 且 `fieldReport.fields` **为空** → 确认「TDC 返回 0 行」（主因成立）。
   - `state=not_found` 但 `fieldReport.fields` **非空** → 是业务单号身份口径问题（转查
     `services/project_status_records.py:IDENTITY_FIELDS` 与真实行键）。

**P2 — 三点对照实验（一次定案）**
在「系统查询 → TDC 数模设计审核流程报表」面板分别查询，记录**返回行数**与**首行原始字段**：
| 组 | 项目车型 | 部门 | 预期 |
| --- | --- | --- | --- |
| A | `F610S` | `技术中心_车体工程` | 0 行（复现故障） |
| B | `F610S` | 留空 | 有数据 → 部门值错配 |
| C | `F610S` | `车体工程` | 有数据 → 确认正确域值 |
另请附：任一命中行的 `incident`、`department`、`superDepartment`(若有)、`projectModel` 实际值。

**P3 — 脱敏调试包与运行记录**
3. `GET /api/project-status/deliverables/VPI-T2-D5/debug-bundle?format=zip`
4. `GET /api/project-status/runs?deliverableId=VPI-T2-D5&limit=10`
5. `GET /api/project-status/scheduler`

**P4 — 归档任务状态（问题 1 决策输入）**
6. `GET /api/scheduled-archive/jobs` → 重点回传 `aras_paa`、`aras_ncr_progress`、
   `aras_ncr_detail` 的 `enabled` / `credentialConfigured` / `credentialAvailable` / `lastSuccessAt`。
7. 若生产机上「自动归档」页显示这 3 个任务近期跑过，请附 `GET /api/scheduled-archive/runs?limit=20`
   与 `GET /api/scheduled-archive/jobs/aras_paa`（确认 `filters`）。

**P5 — 可见范围**
8. 用同一账号在 TDC 里按 `F610S` 能查到数模单据吗？（判断是否属账号可见范围问题）

取证完成后回传，即可按本文档「方案」章节进入实施。

---

## 本地取证文件（仅本地，只读证据）
- `.runtime/inspect_db.py` / `.runtime/dumpr_rows.py` 与其输出 `.runtime/rows_dump.txt`
- 截图 OCR：`.runtime/ocr.ps1` + `.runtime/shots/shot{1,2,3}.png`
