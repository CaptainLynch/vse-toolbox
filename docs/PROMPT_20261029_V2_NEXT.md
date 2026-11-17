# 新对话提示词：v2 后续收尾（2026-10-29）

> 用法：把下面「提示词」整段粘贴到新对话。

---

## 提示词

你在 `E:\project\vse-toolbox`，分支 `refactor/ux-v2`（最新提交 `2b320da`）。先按 `AGENTS.md` 恢复状态：
读 `memory/CURRENT_STATE.md` 顶部两节、`PROJECT_MAP.md`，再看 `git status` / `git diff --stat`。

背景：VSE Toolbox v2 是给不会写代码的工程师用的「傻瓜式」版本。生产电脑**没有管理员权限、没有 Python**，
不允许改公司安全设置；飞书功能已取消；「子系统开发策略」（VPI-T2-D1）已取消（retired，数据保留）。
`dist/v2-test/keys` 里的签名密钥**只用于测试**，不得提交或外发。冗长输出写到 `.runtime/`。

按顺序做下面的事，每做完一项都更新任务清单；涉及界面改动要用浏览器预览截图自查。

### 1. 先把未提交的同步修复收进提交（最优先）

工作区里有约 900 行未提交改动（17 个已修改文件 + `plugins/project_overview/static/deliverable/simple-logic.js`
+ `tests/test_plugin_overview_simple_logic.py` + `tests/test_plugin_policy_digest_editor.py`），
内容见 `docs/PLAN_20261028_V2_SYNC_DISPLAY_FIX.md` §9：EWO 同步时间不前进、明细进度恒 0%、
数模审批流程一键开启永久失败。CURRENT_STATE 记录全量 3435 passed / 6 skipped，并已打出测试包
`dist/v2-test/updates/vse-app-2.3.3.vsepkg`。

- 重新跑 `python -m pytest tests -q > .runtime/pytest-full.log` 和 `python tools/generate_project_map.py --check`，确认通过。
- 只提交上述相关文件（含 `docs/PLAN_20261028_V2_SYNC_DISPLAY_FIX.md`、`memory/CURRENT_STATE.md`、`PROJECT_MAP.md`）。
  **不要**提交无关的未跟踪文件：`docs/ADVISOR_*`、`pelican-*.html`、`.dsh/`、`dsh-remote-bridge.mjs`、
  `VSE-WebUI-compact.spec`、`docs/dsh-remote-control/` 等。

### 2. 简洁视图的小问题

文件：`plugins/project_overview/static/deliverable/simple.js`。

- 表格列用 `key=${c.key}`，但 schema 列只确定有 `index` / `label`。确认是否有 `key`；没有就改用 `c.index`，避免重复 key 警告。
- 用样例数据重截 7 个交付物的简洁视图（headless Edge 写到 `.runtime/shots-2.3.3/`），确认以下几点：
  - 进度读的是派生值：SOR 原来显示「100% 已完成」却有 3 条逾期。
  - 阶段显示中文。
  - 逾期单独成一列。
  - 不再显示负责人。

### 3. 项目管理补全（多项目 C1 的缺口）

- 后端已有 `PATCH /api/p/workbench/projects/<id>`，但界面上没有改名、改车型、改科室的入口。在
  `plugins/workbench/static/projects.js` 的切换器菜单里加「编辑当前项目」。
- 一键开启页 `plugins/project_overview/static/auto-sync.js`：项目没有科室时，现在默认勾选全部 5 个科室。
  改为优先用当前项目保存的科室；用户在这里改了科室后，回写到项目（PATCH）。
- 暂不做删除项目（不可逆，需先问用户）。

### 4. 需要用户提供信息才能做的（先问，不要猜）

- **车型下拉**：48 个车型代码清单还没给。拿到后，新建项目和一键开启页的车型改成可搜索下拉。
- **后台同步多个项目**：现在只有当前项目会在后台同步。先问用户是否需要，再设计；这涉及启动器和调度器，属于架构决定。

### 5. 后续功能（问用户优先级后再做）

- **F1**：在报告页里一键生成报告（`docs/refactor-v2/REQUIREMENTS.md` 中 F1 仍是未完成）。
- **M1 第 3 片**：token cookie、开机自启开关、pywebview 窗口、L0 原生启动器。

### 6. 需要在真机上验证的（让用户在公司电脑上测，你准备好步骤清单）

- 安装 2.3.3（或之后重打的包）后：
  - EWO 连点两次「立即同步」：第二次应显示「已同步，上游无变化」，且「上次同步」时间前进；进度显示约 71%（241/340）。
  - 数模审批流程「一键开启自动同步」：应走到 2/2 并开启。
- 一键开启对真实 TDC / Aras 的取证从未在真机验证过。请给出逐项核对表，让用户回报每一行显示的结果或原因。

### 收尾

- 更新 `memory/CURRENT_STATE.md`（整节替换前沿）和 `docs/refactor-v2/REQUIREMENTS.md` 的进度行。
- 改了前端或后端就用 `tools/build_v2_test_install.py` 重打测试包。版本号递增，不要复用 2.3.3。
- 不要 push，不要合并到 main。
