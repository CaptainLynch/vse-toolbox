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
- 多值筛选使用 `Sequence[str]`；每类最多 20 个值、单值最多 120 字符、拒绝控制字符并去重；`departments` 优先于旧单值 `department`，`stages` 优先于旧单值 `stage`。
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

**Task 8 acceptance details:**

- Unknown manually entered departments produce an empty result, never SQL/AML string interpolation or a generic 422.
- Stage tokens are limited to canonical stages plus `all`; invalid tokens return the existing sanitized validation error.
- Historical fallback is limited to `ARAS EWO`/`VPI-T2-D3`; current summary is recalculated from current cached items without mutating historical snapshot rows.
- “立即同步” is POST and “刷新同步数据” is GET-only; both disable while busy and refresh the open detail view after completion.
- 当前状态图表新增独立 EWO 同步摘要区，展示分析 API 的 `total/completed/incomplete/overdue/snapshotAt`，不覆盖手工 `progress/status`。

### Task 9: 修复第二轮浏览器反馈

**Files:**
- Modify: `web/static/app.js`
- Modify: `web/static/style.css`
- Modify: `services/project_status_deliverable_analysis.py`
- Modify: `web/app.py` only if policy/serialization changes require it
- Test: `tests/test_project_status_deliverable_analysis.py`
- Test: `tests/test_project_status_analysis_api.py`
- Test: `tests/test_overview_web.py`

**Interfaces and acceptance:**

- Multi-select candidate panels are opaque and layered above the table; arbitrary department names entered manually are retained and submitted as parameterized filters.
- Stage values are rendered uppercase in filter tokens/options and table cells while request values remain canonical lowercase.
- The table `状态` column renders only `超期`/`未超期`; the `阶段` column renders the uppercase EWO stage. `CLOSE` is always `未超期`.
- Pending signers are normalized from supported EWO role/person source forms into one `ROLE:person` line per role, including PE/LEADER/MAJOR/SQE and unknown future roles; absent values render `无`.
- EWO “更新方式” visibly offers manual, automatic-sync, and hybrid modes, recommends automatic-sync, and does not claim unconfigured field mappings are active.
- Manual project progress is explicitly labeled and remains separate from the EWO snapshot summary; summary labels state that values come from the latest sync snapshot.

**Audit clarifications:**

- Use only a defined opaque theme variable such as `--surface-card` for both multi-select control and option panel, with `z-index` and shadow assertions.
- Normalize pending signer input from strings, newline/separator-delimited `ROLE:person` entries, mappings, and arrays; preserve unknown roles and render one line per role. Never fall back to the responsible person field.
- Render the EWO policy editor for `VPI-T2-D3` with exact labels “手动维护”“自动同步”“混合模式”, mark “推荐：自动同步”, and show mapping-disabled status unless a mapping is configured.
- Label the manual chart value “项目手工进度” and the sync section “来自最近一次 EWO 快照”, with tests proving the sync summary does not overwrite `item.progress`.
- Pending-signer normalization contract: read only dedicated pending-signer aliases in their existing priority order; accept newline/semicolon/Chinese-or-English-comma-delimited strings, `{role, person}` arrays, or role-to-person mappings; discard blank entries, dedupe identical pairs keeping first occurrence, retain multiple people for one role, and serialize one `ROLE:person` line per pair. The responsible-person field is never a fallback.
- Policy readiness contract: use existing policy API `enabled` and complete `mapping` validation as the sole readiness signal. Any disabled/incomplete policy renders “未启用” and must not claim synchronization; mode labels are presentation only until readiness is true.
- Filter contract inherits the existing repeated `departments`/`stages` keys, 20-value/120-character limits, control-character rejection, deduplication, parameterized SQL, and empty result for unknown departments.

- [ ] **Step 1: Add failing tests** for opaque dropdown contract, uppercase stage labels, two-state status, signer normalization, policy modes, and progress/snapshot labels.
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement the smallest UI/data normalization fixes.**
- [ ] **Step 4: Run focused tests, JS syntax check, and regression tests.**
- [ ] **Step 5: Commit** with message `fix: address second-round EWO UI feedback`.
