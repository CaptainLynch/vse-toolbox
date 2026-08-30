# 图表标签分组定义（值映射）实施计划

> **Spec:** `docs/superpowers/specs/2026-08-30-chart-label-group-mapping-design.md`（六项决策已确认）
> **流程:** Main 定契约 → 子智能体写失败测试 → Main 审核 diff 并实现 → 聚焦验证 → code-reviewer → 全量回归 → 单次 commit `feat: chart label group mapping`。

## Global Constraints

- 映射只作用于图表分组展示（`chart_groups`/`customCharts`）；明细、summary、筛选、缓存数据不动。
- 匹配：成员 strip+casefold 精确等值；组名隐式自归属；组名不得出现在其他组的成员里；成员跨组重叠拒绝（双计）。
- `unmatched ∈ {keep, other, hide}`，默认 keep；`other` 桶名固定"未分组"。
- 上限：每标签 groups ≤20、成员 strip 后 1–80 字符、单标签成员总数 ≤200（空成员静默丢弃、组内去重）。
- 旧配置（无 groups/unmatched）行为与统计键完全不变；序列化输出显式携带 `groups: []` / `unmatched: "keep"`。

### Task 1: 服务层校验与映射（含 API）

**Files:**
- Modify: `services/project_status_deliverable_analysis.py`（`_validate_chart_labels` 扩展、`chart_labels` 序列化、`chart_groups`/`_chart_groups_from` 增 `groups`/`unmatched` 参数、overview 接线）
- Modify: `web/app.py`（无结构改动，PUT 透传）
- Test: `tests/test_project_status_deliverable_analysis.py`（校验场景 + 映射统计场景；更新既有 roundtrip 断言为五键形状）
- Test: `tests/test_project_status_analysis_api.py`（GET/PUT 携带 groups 往返、非法 422、customCharts 映射分组键；更新既有 saved_labels 形状断言）

**Interfaces:**
- `chart_groups(deliverable_id, source_field, *, model=None, model_match="fuzzy", groups=None, unmatched="keep")`。
- `_chart_groups_from(items, source_field, *, model, model_match, groups=None, unmatched="keep")`：构建 `成员(casefold) → 组名` 查找表（含组名自归属），未命中按 unmatched 三态处理。
- `chart_labels()` 输出每项 `{label, sourceField, sortOrder, groups, unmatched}`。

### Task 2: 前端编辑器（Main 自写测试 + 实现）

**Files:**
- Modify: `web/static/app.js` / `web/static/style.css`
- Test: `tests/test_overview_web.py`

**Interfaces:**
- `buildChartLabelEditor` 每个标签升级为块：主行（标签名/字段/配置分组切换/移除）+ 可折叠分组定义区（`.chart-group-rule` 行：`.chart-group-name` + `.chart-group-members` 文本框，分隔符 `,，、;；`；`.chart-group-add-btn`；未匹配值 `.chart-label-unmatched` 三选）。
- 保存 payload 每标签携带 `groups`（成员经分隔解析、去空、去重）与 `unmatched`；预填已存规则；旧标签预填空规则 + keep。

### Task 3: 回归与提交

- 聚焦测试 + `node --check` + `compileall` + `git diff --check` + 全量 `pytest -q`（5 个 pre-existing 失败单独报告）。
- code-reviewer 审查后提交。
