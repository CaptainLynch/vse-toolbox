# GPT 迁移提示词

> 状态：Historical / Session Artifact
> 读者：Developer、Agent（一次性迁移复盘）
> 权威来源：指定会话快照；当前代码、`AGENTS.md` 和 `memory/` 优先
> 默认读取：禁止默认读取；不得作为当前项目状态来源

> 用法：将下方分隔线之间的全部正文复制给 GPT（建议 Codex CLI 等可本机访问仓库的
> 环境）。若目标 GPT 无法访问本仓库，需先人工同步代码与本文档。

---

【提示词正文开始】

你在 Windows 仓库 `E:\project\vse-toolbox`（Python 3.12 + Flask + 原生 JS，Git Bash，
主分支 main，当前工作分支 `feature/scheduled-deliverables-overview-excel`）继续一项
进行中的缺陷修复工作。

## 第 0 步：先读后动

按顺序阅读，再开始任何修改：
1. `AGENTS.md`（协作与运行时规则，含 runtime 选择）
2. `memory/CURRENT_STATE.md`（当前执行前沿）
3. `docs/SESSION_COMPLETION_b63397f7.md` 与 `docs/SESSION_HANDOFF_b63397f7.md`
   （上一会话完成情况与执行规格，本提示词与其冲突时以工作区实况为准）
4. `memory/DECISIONS.md` 中 2026-09-06 各条（环图 auto 规则、SOR 注册配方等产品口径）

## 背景与当前状态

基线 commit `9de04a6`。code-reviewer 联合审计的 6 项修复进度：

- **已完成、已验证、在工作区未提交**：
  - N4 `core/redaction.py`：`_XML_RE` + `redact_sensitive_text()` 先 XML 后参数脱敏。
  - N2 `core/archive_store.py`（约 315-325 行）：`os.link` 循环内 `except OSError:`
    降级 `os.replace`，`unlink(missing_ok=True)`。
  - M8 `web/static/app.js` `renderFormFilterBar`：`stashPendingFilterInputs()` 在多选
    onChange 的 `onReload()` 前暂存 keyword/relationEwo/dateStart/dateEnd 至
    `state.pendingFilterInputs`；四输入初始化优先取暂存；apply/clear 后置 null。
- **经复核无需修复，勿动**：M4 —— `generate_preview_data.py`（仓库根目录，不在
  tools/）自 `5e100b3` 起已有 `--db`/`--dry-run` 且缺省 `parser.error` 拒写主库；
  审计引用的 `tools/` 路径与 `:94` 行代码不存在。
- **更早轮次已修复且被契约测试锁定，勿重复修复**：M3、N1、N3。
- **剩余待办**：M1、M2（规格见下）。
- **backlog 本轮不修**：N5、M5、M6、M7。

## 任务 1：验证并提交已有修复

```bash
node --check web/static/app.js
python -m pytest tests/test_credential_safety.py tests/test_archive_store.py tests/test_archive_jobs.py -q
# 期望：语法通过；75 passed, 2 skipped
```

通过后将 `core/redaction.py`、`core/archive_store.py`、`web/static/app.js` 作为一条
fix 提交（说明 N4/N2/M8）。**严禁提交 `PPT_Table_Title_Sync.bas`**（会话前已存在
的无关文件）；`docs/` 三个交接文档可单独 docs 提交或随收尾提交。

## 任务 2：M1 — form_key 白名单一致性（不改产品行为）

6 处分散注册点：`services/deliverable_form_analysis.py:19`（FORM_KEYS）、
`core/db_manager.py:158`（_FORM_SNAPSHOT_KEYS）、`core/db_manager.py:383`（DDL
CHECK，扩展走表重建迁移）、`services/scheduled_archive_runner.py:448`（方法体内联
dict）、`web/app.py:1529`（DELIVERABLE_FORM_LINKS）、`web/static/app.js:4424`
（DELIVERABLE_FORM_KEY_BY_ITEM）。

实施：① 把 runner 内联 dict 提取为模块级常量；② 新增跨模块一致性测试——Python
侧常量互相断言（FORM_KEYS ⊇ 各处值域，DELIVERABLE_FORM_LINKS 值 ⊆ FORM_KEYS），
并解析 `web/static/app.js` 的 `DELIVERABLE_FORM_KEY_BY_ITEM` 字面量断言值域 ⊆
FORM_KEYS；用 6 个现役 key（aras_ewo / aras_paa / aras_ncr_progress /
aras_ncr_detail / tdc_data_model / tdc_sor）做正反用例。注册配方参考
`memory/DECISIONS.md` 2026-09-06 SOR 条目。

## 任务 3：M2 — 阶段名硬编码收敛

**真实范围仅 5 处 fetch URL**（`web/static/app.js` 6057、6720、6884、7306、9486 行）；
审计的"25 处"是 `grep -c 'VPI-T2'` 行数，其中 `"VPI-T2-D1"`~`"VPI-T2-D5"` 是**交付物
节点 ID（产品配置，禁止批量替换）**，其余为注释。

实施：① app.js 顶层常量区（4424 行附近）新增 `const PROJECT_PHASE_ID = "VPI-T2";`，
5 处 URL 改为模板串引用（备选：从 `overviewSavedState.phase.id` 取；优先常量方案）；
② 同步更新 `tests/test_approved_business_ui.py:57/63`（现断言 JS 源码含 URL 字面量）；
③ `grep -rn "phase=VPI-T2\|phases/VPI-T2" web/ tests/` 复查无遗漏。

## 任务 4：收尾

1. `python -m pytest -q` 全量回归，**基线 1698 passed, 2 skipped**，不得低于基线；
   `python -m flake8 core services web tools`（沿用既有 lint 基线，不引入新告警）；
   `node --check web/static/app.js`。
2. 分批提交（M1、M2 各一条或合并一条 refactor）。
3. 检查点：整体替换 `memory/CURRENT_STATE.md`（执行前沿、验证结果、下一步）；
   新坑/新决策追加 `memory/RECOVERY_NOTES.md` 或 `memory/DECISIONS.md`。

## 已踩坑（强制遵守）

- **改代码只用 Edit 工具或 AST 元素 span（lineno/end_lineno）定位，禁止行号正则
  脚本**——曾两次大面积误删 `web/app.py` 靠 `git checkout --` 恢复。
- Python heredoc 改代码转义多次失败，弃用。
- `tests/test_redaction.py` 不存在；N4 由 `tests/test_credential_safety.py` 覆盖。
- Windows 下 LF→CRLF warning 正常，勿改 .gitattributes、勿重排全文件。
- 编辑 `web/static/app.js` 前必须重新 Read 目标区域（可能已被外部修改）。
- 新增路由后重跑 `tools/generate_api_endpoints.py` 更新 `docs/API_ENDPOINTS.md`。

完成后输出：各任务验证结果摘要、提交清单（commit hash + message）、以及
memory 检查点确认。

【提示词正文结束】
