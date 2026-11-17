# 方案 v2：数模同步补齐官方 47 列（逐行取得状态 + 缺列标注）

- 日期：2026-10-22
- 触发：用户反馈「多单号可以同步，但内容不完整」——表单明细里 27 列显示 `-`
- 顾问评审：codex-readonly / gpt-6-astra / high，run `80614167430b4bfdb27e243233a310dd`
- 状态：**方案已按顾问意见修订，待用户批准实施**；尚未改代码

## 1. 根因（已核实）

- 同步的表单快照来自 `TDCProjectStatusConnector.collect` 的 `application_rows`，
  而它来自**列表接口**（`crawl_data_model_all`），只覆盖 47 列中的 **20 列**
  （`core/report_contracts.py:132` `_TDC_DATA_MODEL_SOURCE_FIELDS`）。
- 官方工作簿**每次同步都已下载**（`project_status_connectors.py:373-392`），但只归档、未解析。
- 表单快照由 `build_form_snapshot(form_key, snapshot.analysis_rows, ...)` 构建
  （`project_status_sync_runner.py:546-554`），缺键列被 `source_absent_indexes` 标记，
  但页面部分视图用 `format.js:30` 的 `-` 占位，用户无法区分「没取到」与「上游为空」。

### 缺失的 27 列（精确索引，已用脚本核对）

12:数量、13:重量（单件）、14:零件合计、16:对应IA号、19:造型、20:总体工程、21:CAE、22:整车性能、
23:车身、24:内外饰、25:底盘、26:动力、27:空调电子、28:尺寸工程、29:冲压、30:车身制造、31:涂装、
32:总装、33:新能源、34:感知质量、36:NVH、37:加签人员、42:应签人数、43:已签人数、44:未签人数、
45:签署率、46:待审批人员。

> 注意：`15:版本号` 与 `35:造型专家审核` **是已映射列**，不在缺失集合内（v1 方案误列，已纠正）。

## 2. 顾问评审结论（已采纳）

1. **合并键**：v1 的「唯一单号回退」证据不足且不安全（同单号不同零件号会被合并）。
   → 改为**只用非空 `(流水单号, 零件号)` 复合键**；单号回退**默认关闭**；incident 暂不参与对齐（跨源口径未证实）。
2. **标注**：快照级 status 不够，**必须逐行记录取得状态**；完整官方行的真实空值保持空值；
   未取得官方列的行才显示指定文案；`源端不提供` 只用于已确认的来源能力。
3. **失败策略**：四类失败可降级；但**契约不符（contract_mismatch）必须整批丢弃官方数据**，保留列表同步成功。
4. 顾问额外指出的两点已核实：
   - 缺失列数应为 27（v1 误写 29）——已用脚本核对并纠正；
   - 混合键优先级未证：实测 `_tdc_header_mapping_values`（`deliverable_form_analysis.py:1001-1012`）
     只要行里出现**任一**表头标签就走标签映射、忽略 API 键 → 合并策略必须保证「要么整行 47 个标签键齐全，要么不加标签键」。

## 3. 设计 v2

### 3.1 取数与失败分类（connector）

- 在现有 best-effort 官方导出处解析 `official.path`：
  `read_official_tdc_rows(path, "data_model", max_rows=_MAX_ROWS + 1)`。
- 失败分类（**不阻断同步**，只记录 status）：
  `unavailable` / `truncated` / `contract_mismatch`（整批丢弃）/ `export_failed` / `ok`。
- 结果通过 `ConnectorSnapshot` 新字段传给 runner：`official_rows`（只读）+ `official_status`。

### 3.2 合并（保守、可审计）

- 只对**列表侧已收窄的目标行**做 join（不扩行）。
- 键：`(流水单号, 零件号)`，**零件号为空不算有效键**；键在两侧都必须唯一，否则不合并。
- 不合并的行保留纯列表行（20 列），并记 `officialJoin="ambiguous"|"unmatched"`；
  合并成功的行产出**完整 47 标签键**的新 dict（官方行本身即 47 列），同时保留原列表键供分析/更新链路使用。
- 官方侧存在但列表侧没有的单号：不新增行，只计数进诊断（`unjoinedOfficialRows`）。

### 3.3 逐行状态与展示

- 快照 schema 新增：
  ```json
  "officialColumns": {
    "status": "ok|unavailable|truncated|contract_mismatch|export_failed|not_requested",
    "rowStatus": {"joined": 12, "ambiguous": 1, "unmatched": 3},
    "missingIndexes": [12, 13, ...]
  }
  ```
  逐行状态写入规范化行的 `officialJoin` 字段（持久化在快照行里，供读取侧判定）。
- UI：
  - 行内已合并 → 正常显示（官方真实空值仍显示空/`-`，不额外标注）；
  - 行内未合并（`ambiguous`/`unmatched`）→ 缺失的 27 列显示**「本次未取得官方列」**；
  - 快照级 `status != ok` → 表单明细顶部一条说明（不逐格刷屏）。
- 旧快照无 `officialColumns` → 视为 `not_requested`，沿用现状，不迁移。

### 3.4 预算

- 解析一次（zip+XML），行上限 `_MAX_ROWS`（5000）；超限 → `truncated`，本次不补齐，保留列表 20 列 + 顶部说明。
- 若实测频繁 truncated（宽筛选导致官方表很大），后续再评估「按目标单号流式筛选」；本期不做。

## 4. 测试

- 单元：4 类失败 → 4 个 status；合并器（复合键唯一/零件号空/歧义/官方多行/列表多行）；
  标签键齐全性（合并行 47 键，未合并行不得出现任何标签键）。
- 集成：connector → snapshot → form snapshot；官方可读时 27 列有值；不可读时 status + 同步 success + 逐行标注。
- 前端：未合并行显示新文案；旧快照行为不变。
- 门禁：全量 pytest、flake8、node --check、地图 `--check`、冻结包冒烟（新增 3 项：47 列有值 / 降级标注 / 旧快照兼容）。

## 5. 风险

- 官方表按筛选条件导出，可能包含范围外单号 → 只 join 不扩行。
- 同单号多零件行、零件号口径差异 → 不合并（保守），用户看到「本次未取得官方列」而非错误值。
- 宽筛选下官方表超 5000 行 → 本次不补齐；需在页面上明确说明原因。
- 快照 schema 新增键必须向后兼容。

## 6. 顾问要求的补充证据（本轮已处理）

| 顾问要求 | 处理 |
|---|---|
| 双源标识样本与重复分布 | **通过设计规避**：默认不做单号回退，只认非空复合键；无需样本即可安全上线 |
| 47 列索引/映射/混合键优先级 | 已核实：缺失 27 列（脚本核对）；标签映射优先于 API 键（`_tdc_header_mapping_values`） |
| 解析器缺列/空值/超限行为 | 已核实：`read_official_tdc_rows` 超限抛错不部分投影；本方案按 truncated 降级 |
