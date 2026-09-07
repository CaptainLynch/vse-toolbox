# Current State

Last checkpoint: 2026-09-07（审计修复轮：N4/N2/M8 完成待提交，M4 复核为无需
修复，剩 M1/M2；交接文档已生成，工作经 docs/GPT_MIGRATION_PROMPT_b63397f7.md
迁移至 GPT 继续）。

## Current objective

Branch `feature/scheduled-deliverables-overview-excel`（基线 `9de04a6`）落实
code-reviewer 联合审计的 6 项修复。状态：

- ✅ N4 `core/redaction.py`：`_XML_RE`（紧跟 `_PARAM_RE`）+
  `redact_sensitive_text()` 管线先 XML 后参数脱敏。
- ✅ N2 `core/archive_store.py` ~315-325：`os.link` 循环内 `except OSError:`
  降级 `os.replace` + `break`；`unlink(missing_ok=True)`。
- ✅ M8 `web/static/app.js` `renderFormFilterBar`：`stashPendingFilterInputs()`
  在多选（status/department/section/model/stage/overdueState）onChange 的
  `onReload()` 前暂存 keyword/relationEwo/dateStart/dateEnd 至
  `state.pendingFilterInputs`；四输入初始化优先取暂存（`!== undefined`）；
  apply/clear 后置 null。多选闭包引用其后声明的变量无 TDZ 问题（回调仅
  用户交互时触发）。
- ✔️ M4 无需修复：`generate_preview_data.py` 在仓库根目录（非 tools/），自
  `5e100b3` 起即有 `--db`/`--dry-run` 且缺省 `parser.error` 拒写主库；审计
  引用的 `tools/...:94 DatabaseManager()` 与实况不符，勿重复修复。
- ❌ M1：form_key 白名单 6 处分散（`services/deliverable_form_analysis.py:19`
  FORM_KEYS、`core/db_manager.py:158` _FORM_SNAPSHOT_KEYS、`core/db_manager.py:383`
  DDL CHECK、`services/scheduled_archive_runner.py:448` 内联 dict、
  `web/app.py:1529` DELIVERABLE_FORM_LINKS、`web/static/app.js:4424`
  DELIVERABLE_FORM_KEY_BY_ITEM）→ 约定修复：runner 常量提取 + 跨模块
  一致性测试（含解析 app.js 映射）。
- ❌ M2：app.js 阶段名硬编码**真实范围仅 5 处 fetch URL**（6057、6720、
  6884、7306、9486 行）；审计"25 处"是 grep 行数，其中 `"VPI-T2-D1"`~
  `"VPI-T2-D5"` 为交付物节点 ID（产品配置，**禁止批量替换**）；
  `tests/test_approved_business_ui.py:57/63` 锁 URL 字面量需同步改。方案：
  顶层 `PROJECT_PHASE_ID` 常量 + 模板串（备选 overviewSavedState.phase.id）。

## 已验证（2026-09-07 实测）

- `node --check web/static/app.js` 通过。
- `pytest tests/test_credential_safety.py tests/test_archive_store.py
  tests/test_archive_jobs.py -q` → 75 passed, 2 skipped。
- 全量基线 1698 passed, 2 skipped；flake8 沿用既有基线。
- `tests/test_redaction.py` 不存在，N4 由 test_credential_safety.py 覆盖。

## 工作区

- 未提交：`core/redaction.py`、`core/archive_store.py`、`web/static/app.js`。
- 勿提交：`PPT_Table_Title_Sync.bas`（会话前无关文件）。
- 交接文档：`docs/SESSION_COMPLETION_b63397f7.md`（完成情况）、
  `docs/SESSION_HANDOFF_b63397f7.md`（执行规格）、
  `docs/GPT_MIGRATION_PROMPT_b63397f7.md`（GPT 迁移提示词）。
- M3/N1/N3 已修复并被契约测试锁定，勿重复修复；N5/M5/M6/M7 在 backlog。

## Next action

按 `docs/GPT_MIGRATION_PROMPT_b63397f7.md` 执行：验证并提交已有修复（N4/N2/
M8 一条 fix）→ M1 → M2 → 全量回归（基线 1698 passed, 2 skipped）+ flake8 +
node --check → 分批提交 → memory 检查点。已踩坑见 `memory/RECOVERY_NOTES.md`
（教训：行号正则脚本曾两次大面积误删 web/app.py；heredoc 转义失败——改代码
一律 Edit 工具或 AST 元素 span，编辑 app.js 前先重新 Read）。

## 环图 auto 规则（产品可调，详见 DECISIONS.md 2026-09-06）

`DELIVERABLE_AUTO_HIDE_NODE_KEYWORDS`（app.js ~751）：D1→VDR、D2→VPI、
D3→T2、D4→VDR、D5→T2；仅 auto 模式、仅已完成（含快照换算）、节点已排期
且日期已过才隐藏；关键字空格分词精确匹配（防 "VPI-T2 Gate" 误判）。
