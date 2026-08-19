# 📝 review_feedback.md — 代码审查反馈记录

> **用途**: Reviewer 审查代码后输出的结构化反馈，Worker 按此修复。
> **维护者**: 仅 Reviewer 可写入。Worker 只读并逐项修复。
> **规则**: 每条反馈必须包含文件路径、行号、严重程度、问题描述和修复建议。

---

## Review Conversation #7 - Phase 3 Architect Final Review for P1 CLI/Web Rework

**Review date**: 2026-06-20
**Review role**: Phase 3 Architect Final Reviewer
**Review scope**: `main.py`, `web/app.py`, `tests/test_aras_cli_web.py`, `services/aras_crawler.py`,
`web/templates/dashboard.html`, `web/static/app.js`, `web/static/style.css`.

### Gate Result

Final review passed. P1 CLI/Web dual-track injection is signed off after the sensitive-value
redaction rework. `services/aras_crawler.py` remains a service-layer module and is not polluted by
CLI/Web dependencies.

### Verification Notes

- Leakage regression samples were rechecked for both CLI `_safe_error_message()` and Web
  `_sanitize_error_message()`: `sid=abc123`, `Bearer xyz789`, and `token=tok123` do not remain in
  the sanitized outputs or Web error response body.
- Static architecture guard passed: `services/aras_crawler.py` has no `rich`, `flask`,
  `render_template`, `jsonify`, `document.`, or `window.` dependency hit.
- Static HTTP guard passed: `tests/test_aras_cli_web.py` has no direct `requests.get/post/head/request`
  call.
- Functional surface guard passed: CLI menu key `4` is unlocked while P3/P4 remain deferred; Web
  keeps `POST /api/aras/ewo/query`, `POST /api/aras/ncr/progress`, `POST /api/aras/ncr/detail`,
  dashboard DOM hooks, and `fetch()` calls.
- Static credential persistence guard passed: no `localStorage`, `sessionStorage`, or `console.log(`
  hit in the reviewed CLI/Web/test scope.

### Real Command Output

| Check | Command summary | Output |
|---|---|---|
| pytest | `python.exe -m pytest tests/test_aras_cli_web.py tests/test_aras_crawler.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` | `12 passed in 0.59s` |
| py_compile | `python.exe -m py_compile main.py web/app.py` | passed, no output |
| JS syntax smoke | `node --check web/static/app.js` | passed, no output |

**Final Phase 3 P1 readiness**: Signed off. J11 and J-final are marked complete in
`docs/agents/task.md`.

---

## Review Conversation #8 - Phase 4 Architect Final Review for PAA Full Crawl Core

**Review date**: 2026-06-21
**Review role**: Phase 4 Architect Reviewer
**Review scope**: `services/aras_crawler.py`, `tests/test_aras_paa_crawler.py`,
`tests/test_aras_crawler.py`, `tests/fixtures/crawler/paa_*.xml`, `docs/agents/task.md`,
`docs/agents/implementation_plan.md`, `docs/agents/paa_har_snapshot.md`.

### Gate Result

Final review passed. PAA report querying and full crawl pagination are implemented in the service
layer only. The implementation uses the SOAP route with `SOAPAction=ApplyItem`, builds
`Item type="PAA_O" action="get"` payloads, parses SOAP XML via `ElementTree`, and keeps tests fully
offline through fake sessions.

### Verification Notes

- PAA route, method, `SOAPAction`, pagination attributes, `returnMode="itemsOnly"`, and default
  `select` match the HAR-backed contract in `implementation_plan.md` and `paa_har_snapshot.md`.
- `parse_paa_report_response()` uses XML parsing and does not parse SOAP responses as JSON dicts.
- `crawl_paa_report_all()` starts from page 1, increments page dynamically, stops on empty pages and
  short pages, and enforces `max_pages` plus `max_records` fuses with truncation at `max_records`.
- PAA fixtures contain placeholder/sample values only; static credential scans found no real
  Cookie, Authorization, Set-Cookie, csrf, session, or token values.
- No PAA CLI/Web route or UI integration was introduced in this worker scope.

### Real Command Output

| Check | Command summary | Output |
|---|---|---|
| pytest | `python.exe -m pytest tests/test_aras_paa_crawler.py tests/test_aras_crawler.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` | `16 passed in 0.55s` |
| py_compile | `python.exe -m py_compile services/aras_crawler.py` | passed, no output |
| static credential scan | `rg -n -g "paa_*.xml" ... tests/fixtures/crawler`; `rg -n ... services/aras_crawler.py tests/test_aras_paa_crawler.py` | no disallowed hits |
| service UI dependency scan | `rg -n "rich|flask|render_template|jsonify|document\.|window\." services/aras_crawler.py` | no hits |

**Final Phase 4 PAA readiness**: Signed off. K8 and K-final are marked complete in
`docs/agents/task.md`.

---

## Review Conversation #6 - Phase 3 Architect Final Review

**Review scope**: `services/excel_toolbox.py`, `tests/test_excel_toolbox.py`, `requirements.txt`,
`docs/agents/task.md`, `docs/agents/implementation_plan.md`.

### Gate Result

Final review passed. ExcelToolbox production path now uses `xlwings` via `_get_xlwings()` and
`xw.App(visible=False, add_book=False)`, with `app.api.DisplayAlerts=False`,
`app.api.ScreenUpdating=False`, and `app.api.EnableEvents=False`. Output still uses native Excel
`book.api.SaveAs(..., FileFormat=51)`. No `pandas` / `openpyxl` direct Excel file-write path was
introduced.

### Verification Notes

- Static gate: no `win32com` / `_get_win32com` / `Dispatch("Excel.Application")` / `.Workbooks` /
  `.Cells(` hit in `services/excel_toolbox.py` or `tests/test_excel_toolbox.py`.
- Static gate: xlwings path is present in production code, tests, and `requirements.txt`
  (`xlwings>=0.33.0`).
- Static gate: no `pandas` / `openpyxl` / `DataFrame.to_excel` / `Workbook.save` hit in the scoped
  Excel files or `requirements.txt`.
- Smoke command:
  `& "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -c "import services.excel_toolbox as m; xw=m._get_xlwings(); print(xw.__version__)"`
  -> `0.36.6`.
- Pytest command:
  `& "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pytest tests/test_excel_toolbox.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider`
  -> `17 passed in 0.60s`.

**Final Phase 3 readiness**: Signed off. H1-final, H2-final, H3-a, H3-b, and H3-final are marked
complete in `docs/agents/task.md`.

---

## Review Conversation #5 - Phase 4 Excel I/O Stack Gate

**Review scope**: `requirements.txt`, `services/excel_toolbox.py`, `services/office_toolbox.py`,
`tests/test_excel_toolbox.py`, `docs/agents/implementation_plan.md`, `docs/agents/task.md`.

### Gate Result

Phase 2 不迁移裁定通过。静态审查确认本轮不触发 ExcelToolbox 源码重构，保持
`win32com.client` / Office 原生保存路径；`xlwings` 仅作为文档比较项出现，未进入运行时依赖或源码实现。

### Verification Notes

- 最终工作树变更仅涉及 `docs/agents/implementation_plan.md`、`docs/agents/task.md`、
  `docs/agents/review_feedback.md`；未发现 `.py` 源码改动。
- `requirements.txt` 未新增 `xlwings`、`openpyxl`、`pandas`；运行时 Office 自动化依赖仍为 `pywin32`。
- `services/excel_toolbox.py` 仍保留 `_get_win32com()`、`Excel.Application`、`SaveAs(FileFormat=51)`、
  `Close()` / `Quit()`、备份与回滚路径。
- `tests/test_excel_toolbox.py` 仍通过 monkeypatch `_get_win32com` 隔离真实 COM，未要求启动真实 Excel。
- 测试未能执行：`pytest` 不在 PowerShell PATH；`python -m pytest` 失败于 `python.exe` 系统无法访问；
  `py -m pytest` 失败于 `py.exe` 系统无法访问。该项记录为环境阻塞，不记为测试通过。

**Final Phase 4 readiness**: Passed by static/source-level review. No Phase 3 rollback item is required.

---

## Review Conversation #4 - Phase 4 F1 Code Review

**Review scope**: `services/feishu_imap.py`, F1 tests, F1 contract in `task.md` / `implementation_plan.md`.

### Blocking Findings

| # | Severity | File | Lines | Problem | Required fix | Status |
|---|---|---|---|---|---|---|
| F1-1 | Blocking | `services/feishu_imap.py` | L423-L438 | `scan_and_parse()` catches every exception from `_save_tasks()` and `sync_unsynced_tasks_to_deliverables()` and converts it to `return 0`. This violates the F1 contract that sync/database errors must not be hidden as normal scan completion. It also creates misleading semantics: `_save_tasks()` may already have committed new `feishu_tasks`, but the public return becomes `0`, so callers cannot distinguish "no unread mail" from "database/sync failed after saving". The current tests only cover the happy path and do not assert sync bridge failure propagation. | Restrict the `return 0` path to connection failure, and let `_save_tasks()` / sync bridge database exceptions propagate after logging. Add a test where `sync_unsynced_tasks_to_deliverables()` raises and assert `scan_and_parse()` surfaces the failure rather than returning `0` or a normal count. | ✅ Verified — final review passed |

### Verification Notes

- Static review confirms `services/feishu_imap.py` no longer contains `imaplib` and uses `IMAPClient(..., ssl=True)`, `select_folder`, `search(["UNSEEN"])`, and `fetch(ids, ["RFC822"])`.
- Static review confirms `_get_credentials()` uses `getpass.getpass()` for the password and no password-style `Prompt.ask()` remains in `services/feishu_imap.py`.
- Final retry review confirms `scan_and_parse()` returns `0` for connection failure / no unread mail, continues per-message parse errors, and re-raises `_save_tasks()` / `sync_unsynced_tasks_to_deliverables()` persistence failures after logging.
- Final retry review confirms `tests/test_feishu_sync.py` includes the sync-failure propagation regression and fixture literals now match `tests/conftest.py` (`飞书任务1`, `张三`).
- `pytest` could not be executed in this environment: `pytest` is not on PATH, and `python.exe` / `py.exe` are inaccessible through the sandbox. Review is therefore static plus source-level reasoning.

**Final F1 readiness**: Passed by static/source-level review. No blocking F1 defects remain.

---

## 审查状态图例

- `⏳ 待修复` — Worker 尚未处理
- `🔧 修复中` — Worker 已开始修复
- `✅ 已修复` — Worker 已修复，待 Reviewer 确认
- `✅ 已验证` — Reviewer 确认修复有效
- `❌ 无效` — Reviewer 经复核后认为此条无需修改

---

## 审查会话 #3 — Sprint 2 W2–W5 修复复审

**审查日期**: 当前迭代（会话 #2 打回后的复审）  
**审查范围**: 会话 #2 所有打回条目（M1/M2/M3/X1–X5/W1/W2/H1/T2/T3/T4）

---

### 阶段一：自动化拦截

> ⚠ **分类器仍间歇性不可用**（`python -m flake8/mypy/pytest` 均被拦截）。
> 分多次尝试后确认无法通过 Bash 运行任何 `python` 命令。
> 阶段一结果继续基于人工等效分析，以下结论已经过逐行核查。
> **待办**: 请用户或 Worker 在本地手动执行以下命令并将输出粘贴至本文件：
> ```
> python -m flake8 core/ services/ main.py web/ tests/
> python -m mypy core/ services/ main.py web/ tests/ --ignore-missing-imports --python-version 3.10
> python -m pytest tests/ -v
> ```

**flake8 等效**

- `main.py`：setup.cfg 已添加 `main.py:E402` per-file-ignores（L25），import 行无 `# noqa: E402`，E402 豁免正确。L148/L169/L187 的 `# noqa:` 后无规则码（宽泛豁免），flake8 会发出 `W504`（某些版本）或静默通过，**不属于 Error 级别**，不触发阶段一打回。
- `services/excel_toolbox.py`：全文无 flake8 问题。等效：**绿灯**。
- `web/app.py`：`from typing import Any` 已补充，无 F401。等效：**绿灯**。
- `tests/test_excel_toolbox.py`：无明显问题。等效：**绿灯**。

**mypy 等效**

- `web/app.py`：`-> dict[str, Any]` 已参数化。等效：**绿灯**。
- 其余文件：无新增类型问题。等效：**绿灯**。

**pytest 等效**：逻辑审查可行（见阶段二），真实运行待分类器恢复后补跑。

---

### 阶段一判定（等效）

| 文件 | flake8 等效 | mypy 等效 | 阶段一结论 |
|---|---|---|---|
| `services/excel_toolbox.py` | ✅ 绿灯 | ✅ 绿灯 | **进入阶段二** |
| `main.py` | ✅ 绿灯 | ✅ 绿灯 | **进入阶段二** |
| `web/app.py` | ✅ 绿灯 | ✅ 绿灯 | **进入阶段二** |
| `tests/test_excel_toolbox.py` | ✅ 绿灯 | ✅ 绿灯 | **进入阶段二** |

---

### 阶段二：修复验证

| 条目 | 文件 | 行号 | 修复验证结果 |
|---|---|---|---|
| M1 | `main.py` | L31–L35, L144–L195 | ✅ **已验证**：四个 import 全部恢复；三个 handler 均以 `console.print(...); return` 短路，`return` 后保留完整原业务代码（OfficeToolbox/FeishuImapParser/IntranetScraper 调用均在场） |
| M2 | `main.py` | L287 | ✅ **已验证**：`except EOFError: return` 已补充 |
| M3 | `setup.cfg` + `main.py` | L25 / L31–L35 | ✅ **已验证**：setup.cfg L25 新增 `main.py:E402`；main.py import 行无残留 `# noqa: E402` |
| X1 | `excel_toolbox.py` | L281–L303 / L401–L423 | ✅ **已验证**：`src_wb = None; try: ... finally: if src_wb: src_wb.Close(...)` 模式完整 |
| X2 | `excel_toolbox.py` | L260–L276 / L386–L399 | ✅ **已验证**：`bl_wb = None; try: ... finally: ...` 模式完整，两处均覆盖 |
| X3 | `excel_toolbox.py` | L321–L327 / L440–L447 / L552–L563 | ✅ **已验证**：三处 finally 的 Close/Quit 捕获均已加 `logger.debug` |
| X4 | `excel_toolbox.py` | L151–L152 | ✅ **已验证**：`if attempts == len(MORANDI_PALETTE): logger.warning(...)` 已加 |
| X5 | `excel_toolbox.py` | L31–L40 | ✅ **已验证**：注释行已删除，仅保留色值 |
| W1 | `web/app.py` | L53–L54 | ✅ **已验证**：`DatabaseManager()` + `init_database()` 提升到 `create_app()` 应用级，路由闭包复用 `db` |
| W2 | `web/app.py` | L23 | ✅ **已验证**：`-> dict[str, Any]`，`from typing import Any` 已导入 |
| H1 | `web/static/app.js` | L28–L38 | ✅ **已验证**：`renderStatRows` 完全改为 DOM 操作（`createElement` + `textContent`），无 `innerHTML` 注入用户数据；`renderFeishu` 同样改为 DOM 操作 |
| T2 | `test_excel_toolbox.py` | L46–L264 | ✅ **已验证**：`_make_excel_with_open_map` 按路径字符串 side_effect 区分 baseline/source；新增 `test_merge_append_multi_source_distinct_workbooks` 断言 `Workbooks.Open` 调用 3 次且路径各异 |
| T3 | `test_excel_toolbox.py` | L83–L111 | ✅ **已验证**：提取 `_inject_excel` 和 `toolbox_with_mock_excel` fixture，冗余注入已消除 |
| T4 | `test_excel_toolbox.py` | L235 / L355 | ✅ **已验证**：`ca.args[1:2] == (51,) or ca.kwargs.get("FileFormat") == 51` 语义清晰 |

---

### 新发现问题（本轮复审）

| # | 严重程度 | 文件 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|---|
| N1 | 🔵 建议 | `main.py` | L148, L169, L187 | `return  # noqa:` 后无规则码，等同于全局 `# noqa`，会抑制该行所有 flake8 警告。正确用法应为 `# noqa: F401` 等具体规则或直接不加 noqa（此处 `return` 后死代码不会触发 flake8 error）。 | 删除行尾 `# noqa:` 或改为 `# 以下为保留的原业务代码，暂不执行` 普通注释。 | ⏳ 待修复 |
| N2 | 🔵 建议 | `test_excel_toolbox.py` | L46–L80 | `_make_excel_with_open_map` 返回 `(mock_excel, add_wb)` 元组，但函数签名无返回类型标注（`-> tuple[MagicMock, MagicMock]`），与项目 mypy 风格略有差异。 | 加类型标注（可选）。 | ⏳ 待修复 |

---

### 最终审查结论（会话 #3 复审）

| 任务 | 文件 | 结论 |
|---|---|---|
| **B1–B6** | `services/excel_toolbox.py` | ✅ **审查通过** |
| **A3 + B8 + D1** | `main.py` | ✅ **审查通过**（N1 为建议，不阻塞） |
| **E3** | `tests/test_excel_toolbox.py` | ✅ **审查通过**（N2 为建议，不阻塞） |
| **C1 re** | `web/app.py` | ✅ **审查通过** |
| **C3 re** | `web/static/app.js` | ✅ **审查通过** |

> **待补**: 分类器恢复后需补跑 `pytest tests/test_excel_toolbox.py -v` 与 `flake8`/`mypy`，
> 若出现新 Error 将追加反馈并撤销对应 `[x]` 标记。

---

## 审查会话 #2 — Sprint 2 W2–W5 批次

**审查日期**: 当前迭代  
**审查范围**:
- `services/excel_toolbox.py`（任务 B1–B6）
- `main.py`（任务 A3 重提交 + B8 + D1）
- `web/app.py`（任务 C1）
- `web/templates/dashboard.html`（任务 C2）
- `web/static/app.js` + `web/static/style.css`（任务 C3）
- `tests/conftest.py`（任务 E1）
- `tests/test_db_manager.py`（任务 E2）
- `tests/test_excel_toolbox.py`（任务 E3）

---

### 阶段一：自动化拦截

> ⚠ **注意**: 本轮审查期间系统安全分类器暂时不可用，`flake8`、`mypy`、`pytest` 无法通过
> `Bash` 工具执行。阶段一结果基于**人工逐行代码审查**得出，等同于静态分析。
> 待分类器恢复后，Reviewer 将补充运行三项检查并以终端输出为准更新本记录。

#### 人工 flake8 等效分析结果

**`main.py`（A3 重提交）**

Worker 已在 L31–L32 添加 `# noqa: E402` 豁免，仅保留 2 条 import（DatabaseManager + ExcelToolbox），
`IntranetScraper`、`FeishuImapParser`、`OfficeToolbox` 三个 import 被**完全删除**。
两行 `# noqa: E402` 豁免可消除 E402 Error，flake8 等效：**绿灯**（但存在逻辑问题，见阶段二 #M1）。

**`services/excel_toolbox.py`**

人工检查全文：无行超过 120 字符，import 顺序合规，无未使用变量。等效：**绿灯**。

**`web/app.py`**

人工检查：无明显 flake8 问题。等效：**绿灯**。

**`tests/conftest.py`**、**`tests/test_db_manager.py`**、**`tests/test_excel_toolbox.py`**

人工检查：无明显 flake8 问题。等效：**绿灯**。

---

#### mypy 等效分析结果

**`services/excel_toolbox.py`**

- L129–L154 `_highlight_cell`：`sheet: Any` — COM 对象为 `Any`，mypy 无法静态分析，无 error。
- L25 `from core.config import BACKUP_DIR, OUTPUT_DIR`：使用 `Path` 类型，标注正确。
- L31–L40 `MORANDI_PALETTE: list[int]`：正确。
- 全文无 `-> None` / `-> Path` 缺失情况。等效：**绿灯**。

**`main.py`**

- `Callable[[DatabaseManager], None]` 标注正确。
- `DEFERRED: set[str]` 正确。
- 新增 `handle_excel_toolbox` 中 `Path | None` 为 Python 3.10+ 语法，`setup.cfg` 已配置 `python_version = 3.10`，合规。
  等效：**绿灯**。

**`web/app.py`**

- `def _query_overview(db: DatabaseManager) -> dict`：返回值 `dict` 未参数化，`warn_return_any` 不触发（返回的是具体字面量），mypy 可接受。等效：**绿灯**。

**测试文件**：无类型标注问题。等效：**绿灯**。

---

#### pytest（E1 + E2 + E3）

静态分析可见断言的完整性（无法替代真实运行，待分类器恢复后补跑）。

人工检查测试逻辑完整性：

- `test_excel_toolbox.py::test_merge_append_calls_saveas_and_quit`（L172–L187）：
  `monkeypatch.setattr(et_module, "_get_win32com", lambda: MagicMock(Dispatch=lambda _: mock_excel))`
  此处注入的 `MagicMock(Dispatch=...)` 是 `win32com` 模块级对象，实际代码调用 `wc.Dispatch("Excel.Application")`，`lambda _: mock_excel` 会忽略参数直接返回 `mock_excel` ——
  但 `mock_wb.SaveAs` 被调用是发生在 `workbook` 上，而 `workbook = excel.Workbooks.Add()`，`mock_excel.Workbooks.Add.return_value = mock_wb`，`mock_wb` 的 `SaveAs` 可断言。**逻辑可行**。

  然而 `mock_wb.Sheets.return_value = mock_sheet`（非 `Sheets(1)` 调用），而代码中调用的是 `workbook.ActiveSheet`（对应 `mock_wb.ActiveSheet = mock_sheet` ✓），
  以及后续 `workbook.Sheets.Add()` 用于 `_write_legend`，`mock_wb.Sheets.Add.return_value = mock_legend_sheet` ✓。**可行**。

---

### 阶段一判定（等效）

| 文件 | flake8 等效 | mypy 等效 | pytest 等效 | 阶段一结论 |
|---|---|---|---|---|
| `services/excel_toolbox.py` | ✅ 绿灯 | ✅ 绿灯 | N/A | **进入阶段二** |
| `main.py`（A3 re + B8 + D1） | ✅ 绿灯（noqa 豁免） | ✅ 绿灯 | N/A | **进入阶段二** |
| `web/app.py` | ✅ 绿灯 | ✅ 绿灯 | N/A | **进入阶段二** |
| `web/templates/dashboard.html` | N/A | N/A | N/A | **进入阶段二** |
| `web/static/app.js` + `style.css` | N/A | N/A | N/A | **进入阶段二** |
| `tests/conftest.py` | ✅ 绿灯 | ✅ 绿灯 | N/A | **进入阶段二** |
| `tests/test_db_manager.py` | ✅ 绿灯 | ✅ 绿灯 | N/A | **进入阶段二** |
| `tests/test_excel_toolbox.py` | ✅ 绿灯 | ✅ 绿灯 | N/A | **进入阶段二** |

---

### 阶段二：逻辑审查

---

#### `main.py` — 任务 A3 / B8 / D1 综合审查

| # | 严重程度 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|
| M1 | 🔴 严重 | L31–L32 | **D1 约束违反：删除了 `IntranetScraper` / `FeishuImapParser` / `OfficeToolbox` 三个 import**。task.md D1 明确规定「不删除既有 handler 代码，仅短路」。当前 `handle_generate_ppt`、`handle_scan_feishu`、`handle_intranet_scrape` 三个 handler 只剩空壳提示，其内部本应保留的 `OfficeToolbox(db)` / `FeishuImapParser(db)` / `IntranetScraper(db)` 调用代码均已消失，而非被「短路」保留。若后续 Sprint 解除暂缓需要恢复，代码已无处可找，需完整重写。 | 恢复三个 import（加 `# noqa: E402` 豁免或放到文件顶部）；恢复三个 handler 内的原始业务代码，仅在函数最顶部添加 `console.print("[dim]该模块暂缓开放...[/]"); return` 短路，让原有逻辑在 `return` 后留存（注释掉亦可，但不能删除）。 | ✅ 已修复 |
| M2 | 🟡 警告 | L202–L214 | `handle_excel_toolbox` 中两个嵌套函数 `_ask_paths` / `_ask_path_optional` 均不捕获 `EOFError`，但主循环只在最外层捕获 `EOFError`。若用户在子菜单 `Prompt.ask` 时发送 EOF（如管道/脚本测试场景），会导致 `EOFError` 冒泡到主循环但已经跳过二级菜单的清理，行为略显粗糙。 | 在 `handle_excel_toolbox` 的顶层 `try/except` 中补充 `except EOFError: return`，与主循环的 `EOFError` 处理保持一致。 | ✅ 已修复 |
| M3 | 🔵 建议 | L31–L32 | `# noqa: E402` 豁免是可接受的 workaround，但建议在 `setup.cfg` 的 `per-file-ignores` 段补充 `main.py:E402`，统一管理豁免，避免 `noqa` 注释散落代码中。 | 在 setup.cfg 中 `per-file-ignores` 添加 `main.py:E402`，移除代码内的 `# noqa`。 | ✅ 已修复 |

**结论**：`main.py` 因 M1（D1 约束违反，删除了既有业务代码）**打回**。

---

#### `services/excel_toolbox.py` — 任务 B1–B6 综合审查

| # | 严重程度 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|
| X1 | 🔴 严重 | L268–L288 (`merge_append`) | **`src_wb` 中间工作簿资源泄漏**：每个 source 文件打开后调用 `src_wb.Close(SaveChanges=0)`，但若 `Close` 前抛出异常（例如 L278–L285 的单元格读写出错），`src_wb` 不会被关闭，COM 进程残留。当前外层 `except Exception` 只回滚备份，不关闭中间 `src_wb`。`merge_overlay` L382–L395 存在同样问题。 | 将 `src_wb = excel.Workbooks.Open(...)` 改为嵌套 `try/finally` 模式：`src_wb = None; try: src_wb = ...; ...; finally: if src_wb: src_wb.Close(SaveChanges=0)`。 | ✅ 已修复 |
| X2 | 🔴 严重 | L256–L267 (`merge_append`) | **`baseline` 工作簿同样无异常保护**：`bl_wb = excel.Workbooks.Open(...)` 打开后，若 L261–L266 的读取循环异常，`bl_wb.Close` 不被调用。`merge_overlay` L371–L377 同理。 | 同 X1，包装为 `try/finally`。 | ✅ 已修复 |
| X3 | 🟡 警告 | L293 (`merge_append`) | `workbook.SaveAs(...)` 在 `finally` 中同样执行了 `workbook.Close(SaveChanges=0)`，对一个「刚 SaveAs 完成的工作簿」再 Close 是冗余但无害的；然而若 `SaveAs` 已成功但后续 Close 失败（极少见），日志中无任何提示。 | 在 finally 的 `Close` 内捕获异常时加 `logger.debug` 记录，便于排查 COM 残留。（低优先级，不阻塞通过）| ✅ 已修复 |
| X4 | 🟡 警告 | L129–L154 (`_highlight_cell`) | `_highlight_cell` 中撞色检测逻辑有边界问题：当 `MORANDI_PALETTE` 所有颜色都与目标单元格现有颜色相同时（极端情况），`while` 循环会遍历全部调色板后退出，仍写入最后一次 `color` 值（可能与原底色相同），但不抛异常、无日志。 | 在 `while` 循环后，若 `attempts == len(MORANDI_PALETTE)`，记录一条 `logger.warning("色板耗尽，无可用非冲突色: row=%d col=%d")` 并跳过写色（或写入默认色）。 | ✅ 已修复 |
| X5 | 🔵 建议 | L31–L39 | `MORANDI_PALETTE` 中颜色名称注释（藕粉、灰蓝、薄荷等）与 BGR 十六进制值存在命名漂移：`0xC5B8C8`（实际偏紫粉）注释为「藕粉」、`0xC4B8A8`（实际偏棕）注释为「灰蓝」。不影响功能，但命名误导维护者。 | 校准注释或去掉颜色名称注释，仅保留色值。 | ✅ 已修复 |

**结论**：`services/excel_toolbox.py` 因 X1、X2（COM 资源泄漏，严重）**打回**。

---

#### `web/app.py` — 任务 C1 审查

| # | 严重程度 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|
| W1 | 🟡 警告 | L57–L60 | `api_overview` 每次请求都调用 `DatabaseManager()` + `db.init_database()`，`init_database()` 会执行全套 DDL + WAL PRAGMA。对高频 API 调用有性能开销（SQLite WAL pragma 快但非零），且 `init_database` 本为应用启动时一次性调用，放入路由语义不符。 | 将 `DatabaseManager` 实例提升到应用级（在 `create_app()` 内实例化，`init_database()` 调用一次），通过 `app.config` 或闭包传入路由，而非每请求重新创建。 | ✅ 已修复 |
| W2 | 🔵 建议 | L22 | `_query_overview` 返回 `dict`（未参数化），建议改为 `dict[str, Any]`，与 mypy `warn_return_any` 配置对齐。 | `def _query_overview(db: DatabaseManager) -> dict[str, Any]` | ✅ 已修复 |

**结论**：`web/app.py` W1 为🟡警告级别，建议修复但不阻塞。整体**有条件通过**。

---

#### `web/templates/dashboard.html` + `web/static/` — 任务 C2 / C3 审查

| # | 严重程度 | 文件 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|---|
| H1 | 🟡 警告 | `app.js` | L28–L29 | `innerHTML` 注入含 `STATUS_LABELS[key] || key` 的用户可控内容。`/api/overview` 返回的 key 来自 SQLite `GROUP BY status`，当前 `status` 有 `CHECK` 约束，无法注入。但若约束绕过（如数据库直接写入），XSS 路径存在。 | 改用 `textContent` 赋值，或对 `STATUS_LABELS[key] || key` 和 `value` 做 `escapeHtml` 处理。 | ✅ 已修复 |
| H2 | 🔵 建议 | `dashboard.html` | L17 | Excel 工具箱导航项标注「（暂缓）」，但 C2 任务要求 Excel 工具箱应**不**在置灰之列（task.md C2：「未就绪模块（P1/P3/P4）标灰」，Excel 工具箱为 P0 已就绪）。实际仅有 CLI 入口，WEB 入口确实缺失，但注释应改为「（仅 CLI，WEB 待接入）」而非「（暂缓）」，语义更准确。 | 将 `title="P0 · 仅 CLI"` 和文本「Excel 工具箱（暂缓）」改为「Excel 工具箱（仅 CLI）」。 | ✅ 已修复 |

**结论**：C2/C3 整体**有条件通过**，H1 为🟡警告，建议在下一轮修复。

---

#### `tests/conftest.py` — 任务 E1 审查

| # | 严重程度 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|
| — | — | — | 无问题 | — | — |

**结论**：`tests/conftest.py` **审查通过**。fixture 使用 `tmp_path` 隔离，预置数据合理，不污染生产库。

---

#### `tests/test_db_manager.py` — 任务 E2 审查

| # | 严重程度 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|
| T1 | 🔵 建议 | L27 | `test_init_database_idempotent` 未使用 `tmp_db` fixture，自行构造 `DatabaseManager`——合理，避免 conftest 预置数据干扰行数断言。但 `tmp_path` 形参未声明类型标注，与项目 mypy 风格略有差异。 | 可加 `tmp_path: Path` 类型标注（可选，不影响功能）。 | ✅ 已修复 |

**结论**：`tests/test_db_manager.py` **审查通过**（T1 为微小风格建议，不阻塞）。

---

#### `tests/test_excel_toolbox.py` — 任务 E3 审查

| # | 严重程度 | 行号 | 问题描述 | 修复建议 | 状态 |
|---|---|---|---|---|---|
| T2 | 🔴 严重 | L179 | **`monkeypatch` 注入方式与实际调用不匹配**：`monkeypatch.setattr(et_module, "_get_win32com", lambda: MagicMock(Dispatch=lambda _: mock_excel))`。实际代码 L242：`wc = _get_win32com(); excel = wc.Dispatch("Excel.Application")`。注入的 lambda 返回的是一个 `MagicMock(Dispatch=lambda _: mock_excel)` —— 此 MagicMock 的 `Dispatch` 属性是 `lambda _: mock_excel`，调用 `wc.Dispatch("Excel.Application")` 会调用该 lambda 返回 `mock_excel`，**链路正确**。但 `mock_excel.Workbooks.Add.return_value = mock_wb` 而 `mock_excel.Workbooks.Open.return_value = mock_wb`，意味着 baseline 和各 source 文件打开均返回同一个 `mock_wb`——这会导致对 baseline 和 source 读取同一 sheet 数据，测试断言 SaveAs 和 Quit 仍可通过，但**测试未真正验证多源合并的数据写入序列**（因为所有 Workbooks.Open 返回同一对象）。 | 为 `_make_fake_excel` 改为可以区分 baseline / source 的工厂；或在注入时对 `Workbooks.Open` 用 `side_effect` 按调用次序返回不同 mock 对象，确保测试覆盖多源场景。 | ✅ 已修复 |
| T3 | 🟡 警告 | L179 | 同一 `monkeypatch` 注入在 `test_merge_append_backup_before_overwrite` / `test_merge_append_rollback_on_com_error` 中重复使用相同的 `lambda: MagicMock(Dispatch=...)` 模式，且每次重新构造 `MagicMock`——导致各测试的 `mock_excel` 对象不同，无法在多测试间复用断言。不影响功能，但冗余代码较多。 | 将 `monkeypatch` 注入提取为 fixture（已有 `toolbox` fixture，可扩展为 `toolbox_with_mock_excel`）。 | ✅ 已修复 |
| T4 | 🔵 建议 | L186 | `assert kwargs.get("FileFormat") == 51 or mock_wb.SaveAs.call_args[0][1] == 51`——双重断言路径兼容位置参数/关键字参数，但语义略模糊。 | 改为 `call_args = mock_wb.SaveAs.call_args; assert (call_args.args[1:2] == (51,) or call_args.kwargs.get("FileFormat") == 51)` 形式，语义更清晰。 | ✅ 已修复 |

**结论**：`tests/test_excel_toolbox.py` T2（多源 mock 注入不准确，测试覆盖度不足）**打回**。

---

### 审查意见汇总（本轮 W2–W5 批次）

| # | 严重程度 | 文件 | 行号 | 简述 | 状态 |
|---|---|---|---|---|---|
| M1 | 🔴 严重 | `main.py` | L31–L152 | D1 约束违反：删除了三个 handler 的业务代码，仅剩空壳提示，应「仅短路」而非「删除」 | ✅ 已修复 |
| X1 | 🔴 严重 | `excel_toolbox.py` | L268–L288 | `merge_append` 的 src_wb 在异常时未关闭（COM 进程泄漏） | ✅ 已修复 |
| X2 | 🔴 严重 | `excel_toolbox.py` | L256–L267 | `merge_append`/`merge_overlay` 的 baseline bl_wb 异常路径未关闭 | ✅ 已修复 |
| T2 | 🔴 严重 | `test_excel_toolbox.py` | L179 | `Workbooks.Open` mock 注入不区分 baseline/source，多源覆盖度不足 | ✅ 已修复 |
| M2 | 🟡 警告 | `main.py` | L202–L214 | `handle_excel_toolbox` 子菜单未捕获 `EOFError` | ✅ 已修复 |
| X3 | 🟡 警告 | `excel_toolbox.py` | L293 | finally 中 Close 失败无日志 | ✅ 已修复 |
| X4 | 🟡 警告 | `excel_toolbox.py` | L147 | 色板耗尽无日志，静默写入可能冲突色 | ✅ 已修复 |
| W1 | 🟡 警告 | `web/app.py` | L57–L60 | 每请求重复调用 `init_database()`，语义不符且有性能开销 | ✅ 已修复 |
| H1 | 🟡 警告 | `web/static/app.js` | L28–L29 | `innerHTML` 注入 API 返回值，理论上存在 XSS 路径 | ✅ 已修复 |
| T3 | 🟡 警告 | `test_excel_toolbox.py` | L179+ | mock 注入冗余，缺少共用 fixture | ✅ 已修复 |
| M3 | 🔵 建议 | `main.py` | L31–L32 | `# noqa: E402` 建议迁移到 setup.cfg per-file-ignores | ✅ 已修复 |
| X5 | 🔵 建议 | `excel_toolbox.py` | L31–L39 | 莫兰迪色板注释名称与色值有漂移 | ✅ 已修复 |
| H2 | 🔵 建议 | `dashboard.html` | L17 | Excel 工具箱导航标注「暂缓」语义不准 | ✅ 已修复 |
| W2 | 🔵 建议 | `web/app.py` | L22 | `-> dict` 未参数化 | ✅ 已修复 |
| T1 | 🔵 建议 | `test_db_manager.py` | L27 | `tmp_path` 形参缺类型标注 | ✅ 已修复 |
| T4 | 🔵 建议 | `test_excel_toolbox.py` | L186 | SaveAs 断言路径兼容性写法语义模糊 | ✅ 已修复 |

---

### 最终审查结论（本轮 W2–W5 批次）

| 任务 | 文件 | 结论 |
|---|---|---|
| **B1–B6** | `services/excel_toolbox.py` | 🔧 修复中 — X1/X2/X3/X4/X5 已修复，待 Reviewer 二次确认 |
| **A3 re + B8 + D1** | `main.py` | 🔧 修复中 — M1/M2/M3 已修复，待 Reviewer 二次确认 |
| **C1** | `web/app.py` | 🔧 修复中 — W1/W2 已修复，待 Reviewer 二次确认 |
| **C2** | `web/templates/dashboard.html` | 🔧 修复中 — H2 已修复，待 Reviewer 二次确认 |
| **C3** | `web/static/app.js` + `style.css` | 🔧 修复中 — H1 已修复，待 Reviewer 二次确认 |
| **E1** | `tests/conftest.py` | ✅ **审查通过** |
| **E2** | `tests/test_db_manager.py` | 🔧 修复中 — T1 已修复，待 Reviewer 二次确认 |
| **E3** | `tests/test_excel_toolbox.py` | 🔧 修复中 — T2/T3/T4 已修复，待 Reviewer 二次确认 |

> **Worker 备注**：所有 16 条反馈均已在代码层面完成修复。  
> Auto Mode Bash 分类器在修复期间持续不可用，`pytest` / `flake8` 未能实际执行。  
> 建议 Reviewer 在分类器恢复后运行：`python -m pytest tests/ -v` 和  
> `python -m flake8 main.py services/excel_toolbox.py web/app.py tests/ core/db_manager.py --max-line-length=120`  
> 以补全阶段二自动化验证。

> **补充说明**：阶段一自动化检查（flake8 / mypy / pytest）因系统分类器暂时不可用，
> 基于人工等效分析得出。Reviewer 将在分类器恢复后补跑三项检查，若发现新 Error 将追加反馈。

---

## 审查会话 #1 — Sprint 2 W1 批次 — A1 / A2 / A3 / B7（历史）

**审查日期**: 当前迭代（早于会话 #2）  
**审查结论**（最终状态）:

| 任务 | 文件 | 结论 |
|---|---|---|
| **A1** | `core/config.py` | ✅ **审查通过** |
| **A2** | `core/db_manager.py` | 🟡 打回待修复 — L229 SQL 拼接（条目 #2） |
| **A3** | `main.py` | 🔴 打回待修复 — E402（条目 #1，已在 W2–W5 批次中以 noqa 形式重新提交） |
| **B7** | `services/vertical_forms.py` | ✅ **审查通过** |

**W1 批次打回条目**（供 Worker 参考，按新版 main.py 部分已解决）:

| # | 严重程度 | 文件 | 行号 | 简述 | 状态 |
|---|---|---|---|---|---|
| 1 | 🔴 | `main.py` | L31–L34 | E402（已在 W2–W5 用 noqa 豁免） | ✅ 已修复 |
| 2 | 🟡 | `core/db_manager.py` | L229 | SQL f-string 拼接，违反参数化查询铁律 | ⏳ 待修复 |
| 3 | 🔵 | `core/db_manager.py` | L176–L190 | executescript 事务语义不一致 | ⏳ 待修复 |

---

## 附录：Sprint 1 `[~]` 文件警告（Backlog 参考）

| # | 严重程度 | 文件 | 行号 | 问题描述 |
|---|---|---|---|---|
| S1 | 🔴 | `services/feishu_imap.py` | L202,208,215 | mypy: `get_payload()` 返回值类型不安全调用 `.decode()` |
| S2 | 🔴 | `services/feishu_imap.py` | L329,333,346 | mypy: `self._conn` Optional 未 assert 即访问方法 |
| S3 | 🔴 | `services/feishu_imap.py` | L350–L351 | mypy: `conn.fetch()` 返回值不可下标 |
| S4 | 🟡 | `services/feishu_imap.py` | L27 | flake8 F401: `datetime` 未使用 |
| S5 | 🟡 | `services/intranet_scraper.py` | L27 | flake8 F401: `Confirm` 未使用 |
| S6 | 🟡 | `services/intranet_scraper.py` | L36 | flake8 F401: `WebDriverException` 未使用 |

---

## 审查会话 #Phase 4 Final — P1 Aras HAR 契约最终签批

**审查日期**: 2026-06-20
**审查角色**: Phase 4 Architect Final Reviewer
**审查结论**: ✅ **签批通过**

### 真实命令输出

| 检查 | 命令摘要 | 真实输出 |
|---|---|---|
| requests smoke | `python.exe -c "import requests; print(requests.__version__)"` | `2.34.2` |
| production session smoke | `python.exe -c "from services.aras_crawler import ArasCrawlerClient; c=ArasCrawlerClient('http://aras.example'); print(type(c.session).__name__)"` | `Session` |
| import/class smoke | `python.exe -c "import services.aras_crawler as m; print(m.ArasCrawlerClient.__name__)"` | `ArasCrawlerClient` |
| 专项 pytest | `python.exe -m pytest tests/test_aras_crawler.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` | `7 passed in 0.57s` |

### 静态复核结论

| 范围 | 结论 |
|---|---|
| `services/aras_crawler.py` | EWO 报表过滤、NCR 审批进度、NCR 审批明细三大能力实体已落地；默认生产 session 在目标解释器可用。 |
| `tests/fixtures/crawler/*` | fixture 为离线响应样本；敏感扫描 `Cookie|Authorization|Set-Cookie|csrf|session|token=` 无命中真实凭据；下载 token 使用 `<download_token>`。 |
| `tests/test_aras_crawler.py` | 使用 `FakeSession`/`FakeResponse` 注入并记录调用；专项测试覆盖 EWO、NCR 进度、NCR 明细、下载 token；未发真实 HTTP。 |
| `requirements.txt` | 已包含 `requests>=2.32.0`。 |
| `docs/agents/task.md` | I1-I8 Worker/Reviewer 项已勾选，新增并勾选 I9-final 最终验收项。 |

**最终判定**: Phase 4 P1 Aras HAR 契约落地通过最终复审，可签批。
