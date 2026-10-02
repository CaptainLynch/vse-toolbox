# 会话交接文档（Session Handoff — 技术执行规格）

> 状态：Historical / Session Artifact
> 读者：Developer、Agent（会话交接复盘）
> 权威来源：2026-09-07 会话交接；当前代码、`AGENTS.md` 和 `memory/` 优先
> 默认读取：禁止默认读取，仅在追溯该会话时读取

**会话 ID**: `sess_b63397f7-509f-497c-934b-f363e2c49e52`
**分支**: `feature/scheduled-deliverables-overview-excel`｜**基线**: `9de04a6`
**生成日期**: 2026-09-07（复核更新版）

> 完成状态总览见 [SESSION_COMPLETION_b63397f7.md](SESSION_COMPLETION_b63397f7.md)，
> 本文聚焦剩余工作的执行规格与避坑信息。所有行号均以 2026-09-07 工作区
> 实测为准（含未提交的 M8 改动），动手前请重新 Read 目标区域。

---

## 1. 待办任务执行规格

### 任务 A：提交已有修复（N4 + N2 + M8）

三个文件的改动已完成并通过聚焦验证（75 passed, 2 skipped；`node --check` 通过），
尚在工作区未提交。提交前复跑验证命令（见 §3），通过后作为一条 fix 提交。

**严禁提交** `PPT_Table_Title_Sync.bas`（会话前已存在的无关文件）。

### 任务 B：M1 — form_key 白名单一致性

**目标**：消除 6 处分散注册点的漏改风险（不改产品行为）。

**精确位置**（已逐一复核）：

| # | 位置 | 内容 |
|:--|:-----|:-----|
| 1 | `services/deliverable_form_analysis.py:19` | `FORM_KEYS`（frozenset） |
| 2 | `core/db_manager.py:158` | `_FORM_SNAPSHOT_KEYS`（frozenset） |
| 3 | `core/db_manager.py:383` | DDL `CHECK(form_key IN (...))`（扩展走检测式表重建迁移） |
| 4 | `services/scheduled_archive_runner.py:448` | job_key→form_key **内联 dict**，位于发布快照方法体内 |
| 5 | `web/app.py:1529` | `DELIVERABLE_FORM_LINKS` |
| 6 | `web/static/app.js:4424` | `DELIVERABLE_FORM_KEY_BY_ITEM` |

**实施要点**：
1. 将第 4 处内联 dict 提取为模块级常量（如 `JOB_KEY_TO_FORM_KEY`），方法体引用常量。
2. 新增跨模块一致性测试（建议 `tests/test_form_key_consistency.py` 或并入既有测试文件）：
   - Python 侧：断言 `FORM_KEYS` ⊇ `_FORM_SNAPSHOT_KEYS` ⊇ runner 常量值域；
     `DELIVERABLE_FORM_LINKS` 的值都在 `FORM_KEYS` 内。
   - 前端侧：读取 `web/static/app.js` 源码解析 `DELIVERABLE_FORM_KEY_BY_ITEM`
     字面量（正则或 `node -e` 均可），断言其值域 ⊆ `FORM_KEYS`。
   - 用 6 个现役 form_key（aras_ewo / aras_paa / aras_ncr_progress / aras_ncr_detail /
     tdc_data_model / tdc_sor）做正反用例。
3. 注册配方参考：`memory/DECISIONS.md` 2026-09-06「SOR 注册为第 6 个统一表单」条目。

**验收**：新测试通过；`python -m pytest -q` 不低于基线 `1698 passed, 2 skipped`。

### 任务 C：M2 — 阶段名硬编码收敛

**真实范围（纠正审计的"25 处"口径，重要）**：

- 25 是 `grep -c 'VPI-T2'` 的行数。其中**真硬编码仅 5 处 fetch URL**：
  `web/static/app.js` 6057、6720、6884、7306、9486 行
  （`/api/project-status?phase=VPI-T2`、`/api/project-status/phases/VPI-T2`、
  `/api/project-status/phases/VPI-T2/milestones`）。
- `"VPI-T2-D1"`~`"VPI-T2-D5"` 是**交付物节点 ID**（产品配置命名空间：auto 隐藏
  关键字映射、源标签、form_key 映射等），**禁止批量替换**，见
  `memory/DECISIONS.md` 2026-09-06「环图 auto 规则」条目。
- 其余命中为注释（765 行）。

**实施要点**：
1. 在 app.js 顶层常量区（如 4424 行 `DELIVERABLE_FORM_KEY_BY_ITEM` 附近）新增
   `const PROJECT_PHASE_ID = "VPI-T2";`，5 处 URL 改为模板串引用。
   （备选：从 `overviewSavedState.phase.id` 取值；主审优先常量方案，改动小且契约测试友好。）
2. 同步更新 `tests/test_approved_business_ui.py:57/63` —— 这两处直接断言 JS 源码
   含 URL 字面量，需改为断言常量拼接结果或放宽为模板串形态。
3. 全仓 `grep -rn "phase=VPI-T2\|phases/VPI-T2" web/ tests/` 复查无遗漏。

**验收**：`node --check web/static/app.js` 通过；相关契约测试通过；全量回归不低于基线。

### 任务 D：收尾

1. `python -m pytest -q` 全量回归（基线 1698 passed, 2 skipped）；
   `python -m flake8 core services web tools`（沿用既有 lint 基线，不引入新告警，
   见 DECISIONS.md 2026-09-02 条目）；`node --check web/static/app.js`。
2. 分批提交（M1、M2 各一条或合并一条 refactor），永远不提交
   `PPT_Table_Title_Sync.bas`；docs/ 三个交接文档可一并提交。
3. 检查点：整体替换 `memory/CURRENT_STATE.md`；新坑/新决策追加
   `memory/RECOVERY_NOTES.md` / `memory/DECISIONS.md`。

---

## 2. M8 实现备忘（供 review，已落地于工作区）

`renderFormFilterBar`（app.js ~4710 起）：

- `stashPendingFilterInputs()` 定义于 keyword 输入创建之后，捕获
  `keyword` / `relationInput` / `dateStart` / `dateEnd` 的当前值写入
  `state.pendingFilterInputs`（`relationInput` 不存在时存 `""`）。
- 每个多选 onChange：更新 `state.filterStateByTab` → 重置页码 →
  **`stashPendingFilterInputs()`** → `onReload()`。
- 四个输入初始化：`pendingInputs.<key> !== undefined ? pendingInputs.<key> : String(filters.<key> || "")`。
- 「应用筛选」（写入 filters 后）与「清除」（`clearCurrentFilters` 后）均置
  `state.pendingFilterInputs = null`。
- 注意：多选 onChange 闭包引用了源码顺序上其后声明的 `relationInput`/`dateStart`/
  `dateEnd`，因回调仅在用户交互时触发（渲染同步完成），无 TDZ 问题。

---

## 3. 常用命令

```bash
# 语法/静态检查
node --check web/static/app.js
python -m flake8 core services web tools

# 聚焦测试（本轮改动）
python -m pytest tests/test_credential_safety.py tests/test_archive_store.py tests/test_archive_jobs.py -q

# 前端契约测试（M2 涉及）
python -m pytest tests/test_approved_business_ui.py tests/test_overview_web.py -q

# 全量回归（基线 1698 passed, 2 skipped）
python -m pytest -q

# WebUI 冒烟（曾后台运行）
python webui.py --host 127.0.0.1 --port 5000
```

---

## 4. 已踩坑（勿重复）

1. **禁止行号正则脚本改代码**：曾两次大面积误删 `web/app.py`，靠 `git checkout --` 恢复。
   Python 侧用 AST 元素 `lineno/end_lineno`，JS 侧用 Edit 工具直接编辑。
2. **Python heredoc 改代码多次转义失败**，已定策弃用，一律 Edit 工具。
3. `tests/test_redaction.py` **不存在**；N4 由 `tests/test_credential_safety.py` 覆盖。
4. 审计发现需先对磁盘实况复核再动手：本轮 M4 即审计引用过期路径/代码行的案例。
5. Windows 下 LF→CRLF warning 正常，勿据此改 .gitattributes 或重排全文件。
6. 编辑 `web/static/app.js` 前必须重新 Read 目标区域（本会话曾因文件已被外部
   修改报 "File has been modified since read"）。
7. 新增路由后需重跑 `tools/generate_api_endpoints.py` 更新 `docs/API_ENDPOINTS.md`。

---

## 5. 关键架构约束

见 [SESSION_COMPLETION_b63397f7.md §8](SESSION_COMPLETION_b63397f7.md)，以及
`memory/DECISIONS.md` 的「Web/scheduling architecture constraints」「Credential
boundaries」「Excel out-of-process」等长期条目。
