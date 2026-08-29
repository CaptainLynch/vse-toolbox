# EWO 科室与流程阶段筛选实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 限制 EWO 默认同步科室范围，统一阶段与逾期规则，并在 Web 交付明细中提供科室/阶段筛选。

**Architecture:** Aras 查询层使用 EWO `_rsp_smt` 字段的受控五科室并集过滤（`_rsp_department` 保留上级部门语义）；共享分析服务在显式 `source_type` 边界内将 EWO `state` 规范化为独立 `source_stage` 并按阶段计算统计；Flask API 暴露安全筛选参数，前端交付明细通过同一 API 分页筛选。CLI 不新增交互控件，但复用共享同步逻辑。

**Tech Stack:** Python 3.9+, Flask, SQLite, pytest, 原有 Aras SOAP/HTTP crawler, 原生 JavaScript/CSS。

**Spec:** `docs/superpowers/specs/2026-08-30-ewo-department-stage-filter-design.md`

## Global Constraints

- 默认科室仅为：车身科、车体科、外饰科、内饰科、车体架构集成科。
- EWO 阶段仅允许：`open`、`draft1`、`draft2`、`edit1`、`edit2`、`proc`、`impl`、`close`。
- `open` 默认不计入统计；`close` 为完成且不逾期；`draft1` 至 `impl` 按截止日期判定。
- 未知阶段不得猜测映射，返回 `stage: null`、`stageAttention: true`，且不计入 `total/incomplete/overdue`。
- 不改变 TDC 逻辑，不新增依赖，不写入凭据或敏感响应。
- `services`/`core` 不得导入 Flask 或 Rich；前端只通过现有 `{ok,data}` API 契约通信。

### Task 1: 定义 EWO 科室与阶段领域常量及规范化函数

**Files:**
- Modify: `services/project_status_deliverable_analysis.py`
- Modify: `services/project_status_connectors.py`
- Modify: `services/project_status_sync_runner.py` (source_type 发布边界)
- Test: `tests/test_project_status_deliverable_analysis.py` (若不存在则在现有相关测试文件中加入)
- Test: `tests/test_project_status_connectors.py`

**Interfaces:**
- Produces constants for default departments and canonical stages, plus a pure normalizer returning canonical stage or `None`.
- Analysis publish path accepts explicit `source_type` and applies EWO stage rules only to `aras/ewo`.

- [ ] **Step 1: Write failing tests** for all eight stages, case/whitespace normalization, unknown stage, and default department tuple.
- [ ] **Step 2: Run focused tests** with `pytest tests/test_project_status_deliverable_analysis.py tests/test_project_status_connectors.py -q` and confirm failure.
- [ ] **Step 3: Implement** constants and normalization without changing non-EWO generic status behavior.
- [ ] **Step 4: Re-run focused tests** and confirm pass.
- [ ] **Step 5: Commit** with message `feat: define EWO department and stage rules`.

### Task 2: Apply the five-department default to EWO synchronization

**Files:**
- Modify: `services/project_status_connectors.py`
- Modify: `services/project_status_updates.py` only if contract validation needs a bounded EWO key
- Test: `tests/test_project_status_connectors.py`
- Test: `tests/test_project_status_sync_runner.py`

**Interfaces:**
- `ArasProjectStatusConnector.collect(context)` must pass the fixed validated `rsp_smt` expression when building an EWO query; the final AML element must be `_rsp_smt`.

- [ ] **Step 1: Add failing tests** asserting model-info sync sends the fixed five-department `_rsp_smt` OR expression and legacy bindings never produce an unbounded query.
- [ ] **Step 2: Run the connector tests** and confirm failure.
- [ ] **Step 3: Implement** the default filter using the existing Aras multi-value search syntax; preserve CLI reuse and session cleanup.
- [ ] **Step 4: Run connector and sync-runner tests** and confirm pass.
- [ ] **Step 5: Commit** with message `feat: constrain EWO sync departments`.

### Task 3: Add `source_stage` to the analysis cache and migrate idempotently

**Files:**
- Modify: `core/db_manager.py`
- Modify: schema/bootstrap section used by `DatabaseManager.init_database()`
- Modify: `services/project_status_deliverable_analysis.py`
- Test: `tests/test_db_manager.py`
- Test: `tests/test_project_status_deliverable_analysis.py`

**Interfaces:**
- Normalized analysis item includes `source_stage: str | None`.
- Database list methods can filter by `stage: str | None` and return `source_stage`.

- [ ] **Step 1: Add failing migration/cache tests** for fresh database, existing database migration, idempotent second initialization, and EWO row persistence.
- [ ] **Step 2: Run focused tests** and confirm failure.
- [ ] **Step 3: Implement** nullable `source_stage`, migration detection, cache insert/update, and normalized EWO stage extraction from `state` aliases.
- [ ] **Step 4: Run database and analysis tests** and confirm pass.
- [ ] **Step 5: Commit** with message `feat: persist normalized EWO stages`.

### Task 4: Implement stage-aware statistics and analysis queries

**Files:**
- Modify: `services/project_status_deliverable_analysis.py`
- Modify: `core/db_manager.py`
- Test: `tests/test_project_status_deliverable_analysis.py`
- Test: `tests/test_deliverable_analysis_paging.py`

**Interfaces:**
- `summarize_analysis_items(..., department=None, stage=None, ...)` validates stage and applies the same filter to rows and totals.
- `_alert_type` excludes `open`, treats `close` as complete, and date-checks active stages.

- [ ] **Step 1: Add failing tests** for open exclusion, close completion/no alert, active-stage overdue/due-soon/missing-date, unknown stage attention/non-counting, source_type isolation, and combined department/stage pagination.
- [ ] **Step 2: Run focused tests** and confirm failure.
- [ ] **Step 3: Implement** stage-aware SQL filtering and summary derivation while preserving generic non-EWO behavior.
- [ ] **Step 4: Run analysis/paging tests** and confirm pass.
- [ ] **Step 5: Commit** with message `feat: apply EWO stage-aware overdue rules`.

### Task 5: Extend Flask API validation and response serialization

**Files:**
- Modify: `web/app.py`
- Test: `tests/test_project_status_analysis_api.py`
- Test: `tests/test_project_status_api.py`

**Interfaces:**
- `GET /api/project-status/deliverables/<deliverable_id>/analysis/items` accepts `department` and `stage`.
- Item payload includes `stage` while retaining `status`.

- [ ] **Step 1: Add failing API tests** for valid filters, invalid stage, unknown department returning 422, default open/unknown exclusion, stageAttention serialization, alert-branch filtering, and total/list consistency.
- [ ] **Step 2: Run focused API tests** and confirm failure.
- [ ] **Step 3: Implement** bounded query parsing, error responses via existing sanitized helpers, and stage serialization.
- [ ] **Step 4: Run API tests** and confirm pass.
- [ ] **Step 5: Commit** with message `feat: expose EWO department and stage filters`.

### Task 6: Add Web delivery-detail department/stage controls

**Files:**
- Modify: `web/static/app.js`
- Modify: `web/templates/dashboard.html` only if a stable toolbar mount is required
- Modify: `web/static/style.css`
- Test: `tests/test_deliverables_web.py`
- Test: `tests/test_overview_web.py`

**Interfaces:**
- The detail analysis toolbar renders department and stage selects.
- Filter changes reset pagination and request both query parameters.
- Rows render a stage column and distinguish open/close/active states.

- [ ] **Step 1: Add failing static/behavioral tests** for controls, labels, stage options, query parameters, page reset, and stage column.
- [ ] **Step 2: Run focused frontend-contract tests** and confirm failure.
- [ ] **Step 3: Implement** controls using existing DOM helpers and fetch/error patterns; default stage view excludes open.
- [ ] **Step 4: Run focused frontend tests** and confirm pass.
- [ ] **Step 5: Commit** with message `feat: add EWO detail filters`.

### Task 7: Regression, packaging, and final verification

**Files:**
- Modify only files required by failing regressions from Tasks 1–6.
- Test: all affected test files plus full `tests/` suite.

- [ ] **Step 1: Run focused backend, API, and frontend tests.**
- [ ] **Step 2: Run `flake8 core services web main.py` and `mypy core services web`.**
- [ ] **Step 3: Run full `python -m pytest -q`, recording long output under `.runtime/`.**
- [ ] **Step 4: Verify CLI project-status sync imports the same default rules without adding prompts or flags.**
- [ ] **Step 5: Inspect scoped diff, credential redaction boundaries, and `git status --short`; report any pre-existing failures separately.**

### Task 8: 修复第一轮浏览器反馈

**Files:**
- Modify: `services/project_status_deliverable_analysis.py`
- Modify: `core/db_manager.py`
- Modify: `web/app.py`
- Modify: `web/static/app.js`
- Modify: `web/static/style.css`
- Test: `tests/test_ewo_department_stage_feature.py`
- Test: `tests/test_project_status_analysis_api.py`

**Interfaces:**
- API 接受重复键 `departments`、`stages`，并兼容旧的 `department`、`stage`。
- 历史 ARAS EWO 缓存在读取时能按来源回退识别阶段；`close` 不返回逾期。
- 前端提供可搜索多选、应用/清除筛选和同步状态/立即同步/刷新入口。

- [ ] **Step 1: Write failing tests** for multi-value filters, manual tokens, historical close cache, summary recalculation, and sync refresh controls.
- [ ] **Step 2: Run focused tests to verify failure.**
- [ ] **Step 3: Implement the smallest root-cause fixes.**
- [ ] **Step 4: Run focused tests, JS syntax check, and relevant API tests.**
- [ ] **Step 5: Commit with message `fix: address EWO browser feedback`.**
