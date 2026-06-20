# 🗺️ implementation_plan.md — 架构实施计划

> **用途**: Architect 输出的顶层设计文档，Worker 严格按此实现。
> **维护者**: 仅 Architect 可修改。Worker 只读参照。
> **关联**: 每个实施项对应 `task.md` 中的具体任务编号。

---

## 1. 整体架构图

> **Sprint 2 起：单一 CLI → 双轨界面（Dual-Interface）**。
> CLI 与 WEB 是两层平行的「界面适配层」，**共享同一 service 层**。
> 解耦边界落在 service 层：`services/*`、`core/*` 不依赖任何界面库。

```
        界面适配层 (Interface Adapters)
┌────────────────────────┐      ┌────────────────────────┐
│   main.py  (CLI 入口)   │      │  web/app.py (WEB 入口)  │
│  handle_* + rich 渲染   │      │  Flask 路由 + jsonify   │
│  · Excel 工具箱 (P0)    │      │  · 项目可视化大屏 (P2)  │
│  · 内网爬虫 (P1, 置灰)  │      │  GET / , GET /api/...   │
└───────────┬────────────┘      └───────────┬────────────┘
            │  调用（仅传参 / 收数据）         │
            └───────────────┬─────────────────┘
                            ▼
              共享 service 层（界面无关 · 不 import rich/flask）
   ┌───────────────┬───────────────┬───────────────┬──────────────┐
   ▼               ▼               ▼               ▼              ▼
┌──────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ Excel    │ │ Office       │ │ Intranet     │ │ Feishu   │ │ vertical_    │
│ Toolbox  │ │ Toolbox      │ │ Scraper      │ │ ImapPars │ │ forms (占位) │
│(P0·xlwings)││ (COM)        │ │ (Selenium)   │ │ (IMAP)   │ │              │
└────┬─────┘ └──────┬───────┘ └──────┬───────┘ └────┬─────┘ └──────────────┘
     │              │                │              │
     └──────────────┴───────┬────────┴──────────────┘
                            ▼
                   ┌─────────────────┐      ┌─────────────────┐
                   │  DatabaseManager │◀────│  core/config.py  │
                   │  (SQLite WAL)   │      │ (集中常量·无密码)│
                   └─────────────────┘      └─────────────────┘
```

> 关键约束：**箭头单向向下**。service 接收参数 → 返回数据 / `Path` → 抛领域异常；
> 绝不反向 import 界面层，也不在 service 内做 rich 打印或 HTTP 响应。

## 2. 关键设计决策

### 2.1 Office I/O: Office 原生进程保存

**决策**: ExcelToolbox 的物理基座从 `win32com.client` 强制迁移到 `xlwings`；PowerPoint / OfficeToolbox
暂不纳入本次 Excel 迁移，仍按既有 Office 原生自动化路径维护。

**理由**: 公司 DLP 透明加密对 Python 文件库直接写入的二进制流进行加密，导致文件打开乱码。Excel 迁移到
`xlwings` 后仍必须驱动本机 Excel 进程，并继续通过 Excel 原生 `SaveAs(FileFormat=51)` 保存；不得改用
`pandas` / `openpyxl` 等文件直写路径。

**Office 生命周期约束**:
- `xlwings.App` 必须在 `try...finally` 或 context manager 中创建和释放。
- `xlwings.App(visible=False, add_book=False)` 是 ExcelToolbox 的最低构造参数；不得让 Excel 弹窗或创建无用空白簿。
- 静默策略通过 `app.api` 控制：至少设置 `DisplayAlerts=False`、`ScreenUpdating=False`，可按需设置
  `EnableEvents=False`；退出前必须关闭所有本次打开/创建的 `Book` 并 `app.quit()`。
- 输出仍使用 Excel 原生保存语义：`book.api.SaveAs(<abs_path>, FileFormat=51)`；禁止 `DataFrame.to_excel()`、
  `openpyxl.Workbook.save()` 或任何 OOXML 文件流直写。

### 2.1.1 Phase 1 裁定: 强制从 win32com 迁移至 xlwings

**裁定日期**: 2026-06-20

**裁定**: `services/excel_toolbox.py` 不再保留 `win32com.client` / `Excel.Application` / `_get_win32com`
作为 Excel 物理基座。Worker 必须以 `xlwings` 作为唯一 Excel 入口，并更新 `tests/test_excel_toolbox.py`
的 mock 形状。若 `requirements.txt` 尚未声明 `xlwings`，Worker 可做最小依赖补丁：新增 `xlwings`，
但不得新增 `pandas` / `openpyxl` 作为 Excel I/O 实现。

**关键 API 映射**:

| 现存 win32com 语义 | xlwings 替换方案 | 约束 |
|---|---|---|
| `_get_win32com()` | `_get_xlwings()` 延迟导入 `xlwings as xw` | 保留 monkeypatch seam，便于测试替换；ImportError 文案提示安装 `xlwings` |
| `wc.Dispatch("Excel.Application")` | `xw.App(visible=False, add_book=False)` | 必须显式传入 `visible=False`、`add_book=False` |
| `excel.Visible = False` | `App(visible=False, ...)` | 不再运行期切 visible；构造即隐藏 |
| `excel.DisplayAlerts = False` | `app.api.DisplayAlerts = False` | 同一静默初始化块内设置 |
| `ScreenUpdating / EnableEvents` | `app.api.ScreenUpdating = False`; `app.api.EnableEvents = False` | 降低可见闪烁和事件副作用 |
| `excel.Workbooks.Add()` | `app.books.add()` | 新建输出簿后用 `book.sheets[0]` 取首个 Sheet |
| `excel.Workbooks.Open(abs_path)` | `app.books.open(abs_path, update_links=False, read_only=<bool>)` | baseline/source 尽量只读；输出副本可写 |
| `workbook.ActiveSheet` | `book.sheets.active` 或 `book.sheets[0]` | 优先 `book.sheets[0]` 保持确定性 |
| `workbook.Sheets(1)` | `book.sheets[0]` | xlwings 为 0-based list 风格 |
| `workbook.Sheets.Add()` | `book.sheets.add(name="图例说明", after=book.sheets[-1])` | 图例 Sheet 名称保持不变 |
| `sheet.UsedRange.Rows.Count` | `sheet.api.UsedRange.Rows.Count` | 用 `.api` 访问 Excel 原生 UsedRange |
| `sheet.UsedRange.Columns.Count` | `sheet.api.UsedRange.Columns.Count` | 同上 |
| `sheet.Cells(r, c).Value` | `sheet.range((r, c)).value` | 行列坐标保持 1-based |
| `sheet.Cells(r, c).Formula` | `sheet.range((r, c)).formula` | 差异比对必须同时比对值和公式 |
| `sheet.Cells(r, c).Interior.Color` | `sheet.range((r, c)).api.Interior.Color` | 高亮仍使用 Excel BGR 整数 |
| `workbook.SaveAs(path, FileFormat=51)` | `book.api.SaveAs(path, FileFormat=51)` | 必须保留 Excel 原生 xlsx 保存语义 |
| `workbook.Close(SaveChanges=0)` | `book.close()` 或 `book.api.Close(SaveChanges=False)` | finally 中关闭所有本次打开的 Book |
| `excel.Quit()` | `app.quit()` | finally 中必须执行，避免残留 Excel 进程 |

**迁移骨架**:

```python
xw = _get_xlwings()
app = None
books: list[Any] = []
try:
    app = xw.App(visible=False, add_book=False)
    app.api.DisplayAlerts = False
    app.api.ScreenUpdating = False
    app.api.EnableEvents = False

    out_book = app.books.add()
    books.append(out_book)
    out_sheet = out_book.sheets[0]
    # source_book = app.books.open(path, update_links=False, read_only=True)
    # cell = out_sheet.range((row, col)); cell.value = value
    out_book.api.SaveAs(self._to_absolute(output_path), FileFormat=51)
    return output_path
except Exception:
    if backup is not None:
        self._rollback(output_path, backup)
    raise
finally:
    for book in reversed(books):
        try:
            book.close()
        except Exception:
            pass
    if app is not None:
        app.quit()
```

**生产约束**:

- 保留现有 `_check_file_not_locked`、`_to_absolute`、`_backup`、`_rollback`、莫兰迪色板、图例 Sheet、
  `merge_append` / `merge_overlay` / `diff_against_baseline` 公共签名和 CLI 契约。
- 日志不得输出单元格内容、公式正文、脱密前文件内容或凭据；可记录操作类型、文件名级别的非敏感信息和异常类型。
- 迁移只改变 Excel 物理自动化 API，不改变业务语义：追加合并、坐标覆盖、baseline 差异、高亮、防撞色、备份回滚均保持。
- `tests/test_excel_toolbox.py` 必须改为 mock `xlwings.App` / `Book` / `Sheet` / `Range` / `.api`，
  不得继续以 `wc.Dispatch("Excel.Application")` 作为主验证对象。

### 2.2 数据库: SQLite WAL 模式

**决策**: 启用 `PRAGMA journal_mode=WAL`，所有连接统一通过 `DatabaseManager.get_connection()` 上下文管理器。

**理由**: WAL 模式支持并发读写，适合 CLI 场景下爬虫写入 + 用户查询的并行需求。

### 2.3 IMAP 邮件: imapclient 替代标准库

**决策**: 使用 `imapclient` 替代 `imaplib`。

**理由**: imapclient 接口更友好，支持 IDLE 推送、更好的编码处理，减少邮件解析中的编码异常。

### 2.4 多智能体协作: 角色权限隔离

| 角色 | 模型 | 可修改文件 | 不可修改 |
|---|---|---|---|
| Explorer | 低深度推理 | 无（只读） | 所有 |
| Architect | 高深度推理 | project_state.md, task.md, implementation_plan.md | .py 源码 |
| Worker | 结构化推理 | .py 源码, tests/ | project_state.md 之外的文档 |
| Reviewer | 高深度推理 | review_feedback.md | 所有（只读审查） |

### 2.5 双轨界面（Dual-Interface）与解耦边界

#### 推导过程（≥2 备选 + ≥1 次推翻）

- **备选 A（被推翻）**: 保持纯 CLI，把可视化也塞进 rich 终端表格。
  优点：零新依赖、单一入口。缺点：项目「数据大屏」诉求本质是**多人浏览的可视化看板**，
  rich 终端无法满足非终端用户（管理层）远程查看，且大屏交互（卡片、刷新）在 TUI 中表达力极弱。**推翻**。
- **备选 B（被推翻）**: CLI 与 WEB 各自独立实现一套数据访问逻辑。
  优点：上手快。缺点：同一份概览查询会在 `main.py` 和 Flask 路由里**双写**，
  P0 Excel 若将来上 WEB 还要再抄一遍，违反 DRY，且两套逻辑必然漂移。**推翻**。
- **备选 C（采纳）**: 双轨界面 + 共享 service 层，**解耦边界画在 service 层**。
  CLI（`main.py` 的 `handle_*`）与 WEB（`web/app.py` 路由）都是**薄适配层**，
  调用同一组 `services/*` / `core/*` 方法；service 只认参数与返回值，不认界面。

#### 最终方案

- **解耦铁律**: `services/*`、`core/*` **禁止** `import rich` / `import flask` / 任何界面库；
  方法只接收原始参数（`Path` / `list` / `str` …），返回**数据结构 / `Path`**，
  失败时抛**领域异常**（`PermissionError` / `FileNotFoundError` / 自定义），由适配层翻译为界面反馈。
- **CLI 适配层** = `main.py`：负责 rich 渲染、`Prompt` 交互、异常分类提示。
- **WEB 适配层** = `web/app.py`：负责 Flask 路由、`jsonify` 序列化、HTTP 状态码。
- **本轮界面落地范围**:
  - **P0 Excel 工具箱 仅 CLI 落地**（合并/比对/回滚全功能）。
  - **WEB 仅搭可运行的 P2 Demo 骨架**（项目可视化大屏）+ 其余模块导航**置灰占位**。
- **校验手段**: Reviewer 对 `services/`、`core/` grep `rich` / `flask`，命中即判不合格。

### 2.6 WEB 技术栈：仅引入 Flask

#### 推导过程（≥2 备选 + ≥1 次推翻）

- **备选 A（被推翻）**: FastAPI + 前端框架（Vue/React）。
  优点：异步、自带 OpenAPI。缺点：本项目是**内网单机自用工具**，QPS 极低、无异步必要；
  引入构建链（node/打包）与额外重依赖，违背「轻量 CLI 工具」定位，也加重 DLP 环境部署负担。**推翻**。
- **备选 B（被推翻）**: Django。
  优点：全家桶。缺点：ORM/Admin/中间件对一个只读概览大屏严重过重。**推翻**。
- **备选 C（采纳）**: **仅引入 Flask**，动态读 SQLite 返回 JSON，前端用原生 fetch + 极简 HTML/CSS/JS。

#### 最终方案

- **决策**: `requirements.txt` **仅新增 `flask`**（不引入任何前端框架 / ORM / 异步栈）。
- **理由**: 内网自用、低并发、只读概览；Flask 足够轻、与现有 `pathlib`/`sqlite3` 风格一致；
  前端零构建（静态文件直出），DLP 环境部署成本最低。
- **数据通路**: 浏览器 `fetch('/api/overview')` → Flask 路由 → 复用 `DatabaseManager` 概览查询 → `jsonify`。
- **边界**: Flask 仅存在于 `web/app.py`；service 层对 Flask 无感知。

### 2.7 回滚机制：磁盘临时 `.bak` 备份

#### 推导过程（≥2 备选 + ≥1 次推翻）

- **备选 A（被推翻）**: 数据库事务式回滚（把 Excel 内容也纳入 DB 快照）。
  缺点：Excel 是二进制文件，DLP 加密下无法可靠序列化进 DB；且 COM 写文件不在 SQLite 事务边界内。**推翻**。
- **备选 B（被推翻）**: 内存缓存原文件字节，失败时写回。
  缺点：大文件占内存；进程崩溃则缓存丢失，无落盘恢复点。**推翻**。
- **备选 C（采纳）**: **改写前 `shutil.copy2` 落盘备份到 `data/.backup/`，失败时复制回原位**。

#### 最终方案

- **决策**: 任何**改写已存在文件**的操作（merge_overlay 覆盖 target、merge_append/diff 改写已存在的 output）
  在 Excel 自动化写入前调用 `_backup(target)`；异常时在 `except` 中 `_rollback(target, backup)` 并**上抛**异常。
- **备份命名**: `data/.backup/<name>.<YYYYMMDD_HHMMSS>.bak`（带时间戳，避免互相覆盖）。
- **Excel 生命周期**: `try` 内执行 `xlwings` 自动化；`except` 内 `_rollback` 后 `raise`；`finally` 内关闭 `Book` 并 `app.quit()`。
- **与 §2.1 一致**: 使用 `visible=False` / `add_book=False` / `app.api.DisplayAlerts=False` /
  `app.api.ScreenUpdating=False` / `SaveAs(FileFormat=51)` / try-finally 释放模式。

### 2.8 莫兰迪色高亮与防撞色

#### 推导过程（≥2 备选 + ≥1 次推翻）

- **备选 A（被推翻）**: 固定单色高亮所有变更。
  缺点：多来源合并时无法区分「这格来自哪个文件」，丢失溯源信息。**推翻**。
- **备选 B（被推翻）**: 随机生成 RGB。
  缺点：可能与单元格原有底色或彼此撞色，且观感杂乱、不可复现。**推翻**。
- **备选 C（采纳）**: **预置 6–8 个低饱和莫兰迪色板循环分配**，写入前**读原底色防撞色**。

#### 最终方案

- **色板**: 模块级常量 `MORANDI_PALETTE`（6–8 个低饱和 BGR 整数，COM `Interior.Color` 用 **BGR 十进制**）。
- **分配**: 按**来源标签**循环取色，记入 `color_map: dict[str, int]`（来源标签 → 色值），**一次操作内全程贯穿**。
- **防撞色**: `_highlight_cell` 写入前先读目标单元格原 `Interior.Color`；若与待写色撞色，**顺延取色板下一色**。
- **图例**: 操作结束前把 `color_map` 交给 `_write_legend`，在独立 Sheet「图例说明」逐行输出「来源 ↔ 色块」。

### 2.9 F1 飞书闭环、凭据安全与 IMAPClient 迁移

#### 推导过程（≥2 备选 + ≥1 次推翻）

- **备选 A（被推翻）**: 在 CLI handler 内直接读取 `feishu_tasks` 并写入 `deliverables`。
  优点：改动快。缺点：同步规则会被锁死在界面层，WEB 或定时任务将来无法复用；同时违反
  「界面适配层只做交互」的边界。**推翻**。
- **备选 B（被推翻）**: 新建独立同步表记录 `feishu_task_id → deliverable_id`。
  优点：可追踪映射。缺点：当前数据库已有 `feishu_tasks.synced` 状态位，F1 目标只是修复
  「写后无读」断链；新增表会扩大迁移面，且没有明确的反向追踪需求。**推翻**。
- **备选 C（采纳）**: 在 `FeishuImapParser` service 内新增一个事务级同步方法，
  把 `synced=0` 的飞书待办落入 `deliverables`，再把同一批任务标记为 `synced=1`。

#### 最终方案

- **同步桥归属**: `services/feishu_imap.py::FeishuImapParser` 新增
  `sync_unsynced_tasks_to_deliverables(project_id: int = 1) -> int`。该方法属于 service 层，
  不 import rich/flask，不做界面输出；只返回本次同步条数，异常上抛给适配层。
- **事务边界**: 一次同步必须在单个 `DatabaseManager.get_connection()` 事务内完成：
  先查询 `feishu_tasks WHERE synced=0`，逐条插入 `deliverables`，再仅标记这些已插入的
  `feishu_tasks.id` 为 `synced=1`。任一插入失败时整体回滚，避免「已标记但未落地」。
- **字段映射**:
  - `deliverables.project_id = project_id`，默认 `1`，依赖 Sprint 2 的「未归类」兜底项目。
  - `deliverables.name = feishu_tasks.title`；标题为空时使用 `"未命名飞书待办"`。
  - `deliverables.owner = feishu_tasks.assignee`；`deliverables.due_date = feishu_tasks.deadline`。
  - `deliverables.status = "pending"`。
  - `deliverables.remark` 写入轻量来源说明（如 `飞书待办同步: <source_email_id>`），避免新增列。
- **接入点**: `scan_and_parse()` 在 `_save_tasks(tasks)` 成功后调用同步桥，确保本次新增任务与历史
  `synced=0` 任务都会被补同步；`scan_and_parse()` 的公开返回值仍保持「新入库 feishu_tasks 数量」，
  避免破坏既有调用方语义。
- **凭据安全**:
  - `core/config.py` 继续只放路径、端口、默认 host 等非敏感常量，严禁密码、token、授权码。
  - `FeishuImapParser._get_credentials()` 的密码输入必须使用 `getpass.getpass()`；用户名可继续用
    `Prompt.ask()`。
  - `IntranetScraper` 当前是浏览器内手动登录，不在终端接收密码；Worker 不得新增明文密码 Prompt。
    若后续加入终端式账号密码输入，密码字段必须封装为 `getpass.getpass()`。
- **IMAPClient 迁移**: `services/feishu_imap.py` 必须移除 `imaplib` 依赖，改用 requirements 已声明的
  `imapclient.IMAPClient`。连接用 SSL，`select_folder()` 选择收件箱，`search(["UNSEEN"])` 获取未读邮件，
  `fetch(ids, ["RFC822"])` 取得原始邮件字节；解析逻辑继续复用既有 `email` 标准库函数。
- **异常归一**: IMAPClient 登录/协议/网络异常在 `_connect()` 内转换为 `ConnectionError`；
  `scan_and_parse()` 保持现有容错策略：连接失败返回 0，单封邮件解析失败记录后继续处理下一封。
- **校验手段**:
  - Reviewer grep `services/feishu_imap.py` 不得出现 `import imaplib` / `imaplib.`。
  - Reviewer grep `core/config.py` 不得出现 password/token/secret 等敏感常量。
  - Reviewer grep `services/feishu_imap.py` / `services/intranet_scraper.py` 不得出现密码字段的
    `Prompt.ask(...)` 明文交互。

### 2.10 P1 内网爬虫接口契约：HAR 逆向与离线优先

**裁定日期**: 2026-06-20

**证据源**: `docs/agents/crawl_source_index.md` 与 `docs/agents/crawler_contract.md`。本轮只基于
`crawl source` 离线 HAR/HTML/XLSX 样本设计契约，不允许 Worker 在开发或测试中访问真实内网或外网。

**三条能力线**:
- EWO 报表按需过滤查询：`POST /innovatorserver/Server/InnovatorServer.aspx`，`SOAPAction=ApplyItem`，
  AML 为 `Item type="EWO_O" action="get"`，分页属性为 `page` / `pagesize` / `maxRecords`，
  默认 `select` 字段来自 `ecm.sgmw.com.cn-EWO明细.har` 第一条 entry。
- NCR 审批进度查询：同一 SOAP 路由，`SOAPAction=ApplyMethod`，AML 为
  `Method action="sgmw_downloadFileProgressC"`，筛选字段为 `buystart`、`buyend`、`pestart`、`peend`、
  `ncrno`、`ncrname`、`seccode`、`changetype`、`othercondition`；响应为
  `sgmw_outputFileRecord`，其中 `_file` 提供 `<file_id>` 与 xlsx 文件名。
- NCR 审批明细提取：同一 SOAP 路由，`SOAPAction=ApplyMethod`，AML 为
  `Method action="sgmw_downloadFileDetail4C"`，筛选字段与进度查询一致；响应 `Result` 文本为明细 xlsx 文件名。

**Session / header / cookie 策略**:
- P1 Worker 必须使用 `requests.Session`，但 session、headers、cookies 均由外部调用方显式注入或传入；
  service 不得硬编码样本中的真实会话、用户、token、cookie、Authorization 或 api_key。
- 基础 headers 只可包含非敏感通用项：`Accept`、`Content-Type`、`SOAPAction`、`TIMEZONE_NAME`、
  `Origin`、`Referer`、`User-Agent`、`LOCALE`。`Cookie`、`Authorization`、`api_key` 只能来自调用方。
- NCR 文件下载 token 响应结构为 `{"d":"<download_token>"}`；真实 token 不得写入文档、源码、测试或日志。

**离线测试策略**:
- Worker 从 HAR `response.content.text` 萃取 XML/JSON fixture；包含 token 的 fixture 必须先脱敏为
  `<download_token>` 或生成假 token。
- 单元测试必须 mock `requests.Session.post/head/get`，断言 route、method、headers、payload、解析结果；
  严禁真实 HTTP 请求。
- 详细接口、字段映射、响应结构和 fixture 命名以 `docs/agents/crawler_contract.md` 为准。

### 2.11 P1 双轨接入拓扑：CLI 终端适配层 + WEB 可视化适配层

**裁定日期**: 2026-06-20

**阶段定位**: `services/aras_crawler.py` 已作为底层 HTTP/AML service 通过审查。本节只定义 P1 在
`main.py` 与 `web/*` 的接入拓扑、请求/响应契约、Worker 文件边界与安全红线；不得要求 Worker 修改
`services/aras_crawler.py`。

#### CLI 适配层（main.py）

**入口解锁**:
- `DEFERRED` 仅移除 P1 对应菜单键 `"4"`；P3/P4 继续暂缓。
- `show_menu()` 渲染时 P1 不再 dim/暂缓；`handle_intranet_scrape(db)` 不再短路 return，而是进入
  P1 Aras 爬虫二级菜单。
- 原 `IntranetScraper` Selenium 旧代码可保留为不可达历史分支或后续迁移对象，但本次 P1 菜单应调用
  `ArasCrawlerClient`，不扩大 Selenium 职责。

**rich 表单采集**:
- 必填连接项: `base_url`。必须由用户显式输入；不得从配置默认指向真实内网。
- 敏感项: Cookie/token/Authorization 等只通过当前会话输入。Cookie 推荐用 `Prompt.ask(..., password=True)`
  采集为原始 `Cookie` header 字符串；额外 headers 以 `Key: Value` 多行或逗号分隔输入，并在 CLI 层解析为
  `dict[str, str]`。
- 查询类型: 二级菜单提供 `EWO 报表查询`、`NCR 审批进度导出`、`NCR 审批明细提取`、`返回`。
- EWO 过滤项映射到 `EWOReportFilters`: `ewo_no`、`project_code`、`subject_keyword`、`change_type`、
  `change_sub_type`、`area`、`state`、`rsp_department`、`submit_start`、`submit_end`；分页项映射到
  `page`、`page_size`、`max_records`。
- NCR 过滤项映射到 `NCRApprovalFilters`: `buy_start`、`buy_end`、`pe_start`、`pe_end`、`ncr_no`、
  `project_names`、`section_code`、`change_type`、`othercondition`。
- CLI 层可把 Cookie 字符串透传为 `headers["Cookie"]`，或在用户输入结构化 cookies 时传入
  `cookies: Mapping[str, str]`；不得持久化到 `core/config.py`、数据库、日志或本地文件。

**service 调用与 rich 渲染**:
- CLI 仅实例化 `ArasCrawlerClient(base_url, headers=headers, cookies=cookies, timeout=...)` 并调用公开方法：
  `query_ewo_report()`、`query_ncr_approval_progress()`、`extract_ncr_approval_detail()`。
- EWO 返回 `EWOReportPage` 后用 `rich.table.Table` 渲染 `rows`；列名以返回 row keys 为准，可限制为首屏关键列
  或提供“显示全部列”选项；同时展示 `page`、`len(rows)`、`len(item_ids)`。
- NCR 进度返回 `NCRExportResult` 后渲染 `file_name`、`file_id`、`record_id`，并提示“下载 token 需用户显式二次确认”，
  不得默认调用真实下载。
- NCR 明细返回 `NCRDetailExportResult` 后渲染 `file_name`。`raw_xml` 只可在用户显式调试开关下脱敏展示，默认不打印。
- 捕获 `ArasCrawlerError`、HTTP 层异常和通用异常时，rich 只显示脱敏错误类型与摘要；logger 不记录 Cookie、
  Authorization、token、完整 headers 或完整请求体。

#### WEB 适配层（web/app.py + dashboard HTML/JS）

**Flask API 路由设计**:
- 所有 P1 API 使用 `POST`，避免凭据出现在 URL/query string。
- `POST /api/aras/ewo/query`
  - 请求 JSON:
    ```json
    {
      "base_url": "https://<aras-host>/",
      "headers": {"User-Agent": "...", "Authorization": "<optional>"},
      "cookie": "<Cookie header string>",
      "cookies": {"name": "value"},
      "filters": {
        "ewo_no": "", "project_code": "", "subject_keyword": "",
        "change_type": "", "change_sub_type": "", "area": "", "state": "",
        "rsp_department": "", "submit_start": "", "submit_end": ""
      },
      "page": 1,
      "page_size": 50,
      "max_records": 2000
    }
    ```
  - 成功响应 JSON:
    ```json
    {
      "ok": true,
      "data": {
        "rows": [{"_no": "..."}],
        "page": 1,
        "item_ids": ["..."],
        "count": 1
      }
    }
    ```
- `POST /api/aras/ncr/progress`
  - 请求 JSON: `base_url` / `headers` / `cookie` / `cookies` 同上，`filters` 使用
    `buy_start`、`buy_end`、`pe_start`、`pe_end`、`ncr_no`、`project_names`、`section_code`、
    `change_type`、`othercondition`。
  - 成功响应 JSON:
    ```json
    {"ok": true, "data": {"file_id": "...", "file_name": "...", "record_id": "..."}}
    ```
- `POST /api/aras/ncr/detail`
  - 请求 JSON: 同 NCR progress。
  - 成功响应 JSON:
    ```json
    {"ok": true, "data": {"file_name": "..."}}
    ```
- 失败响应 JSON 统一为:
  ```json
  {"ok": false, "error": {"type": "ArasCrawlerError", "message": "脱敏摘要"}}
  ```
  参数校验失败用 `400`；上游 Aras/HTTP 失败用 `502`；未预期异常用 `500`。

**headers/cookie 透传策略**:
- Web API 每次请求即时构造 `ArasCrawlerClient`；不使用服务器端 session 存储 Cookie/token。
- `cookie` 字符串优先转为 `headers["Cookie"]`，以保留浏览器复制出来的 Cookie header 语义；
  `cookies` mapping 仅在用户显式提交结构化键值时传给 client。
- `headers` 允许透传非空字符串键值，但 Web 层必须在日志、错误响应、测试快照中屏蔽 `Cookie`、
  `Authorization`、`token`、`api_key`、`secret` 等敏感字段。
- Web API 不默认调用真实内网；`base_url` 缺失时直接 `400`，不得从 `DEFAULT_INTRANET_URL` 自动补齐。

**dashboard HTML/JS 面板解锁**:
- `dashboard.html` 将 P1 导航从 disabled 改为可进入的“内网爬虫”面板；P3/P4 仍 disabled。
- 新增 P1 面板包含连接表单、查询类型 tabs/segmented control、EWO/NCR 过滤表单、执行按钮、结果表格、
  错误提示区与 loading 状态。
- `app.js` 使用原生 `fetch` 调用上述 POST API；实现轻量异步渲染队列：
  同一时间只允许一个 Aras 查询处于 running，后续点击进入 queued 或直接禁用按钮并显示等待状态；
  响应回来后按请求序号渲染，避免慢响应覆盖新结果。
- EWO rows 渲染为可横向滚动表格；NCR progress/detail 渲染为结果摘要。前端不得把 Cookie/token 写入
  `localStorage`、`sessionStorage`、URL、DOM 可见结果区或 console。

#### 隔离红线

- `services/aras_crawler.py` 不得 import `rich`、`flask`、DOM、浏览器 API、`web/*` 或 `main.py`。
- CLI/Web 只依赖 service 公开 DTO 与方法；service 不反向依赖 CLI/Web，也不输出终端样式或 HTTP response。
- Worker 本组允许改 `main.py`、`web/app.py`、`web/templates/dashboard.html`、`web/static/app.js`、
  `web/static/style.css`、新增 `tests/test_aras_cli_web.py` 或同等聚焦测试。
- Worker 本组禁止修改 `services/aras_crawler.py`；除非 Architect 另行打回并新增专门任务。

#### 安全红线

- 不持久化 Cookie/token/Authorization/api_key/secret；不写入配置、数据库、日志、测试 fixture、HTML 默认值。
- 不把鉴权信息写入异常、日志、前端 console、URL 或响应 JSON。
- Web API 不默认调用真实内网，必须由用户显式提交 `base_url` 与 Cookie/header。
- 单元测试必须 mock `ArasCrawlerClient` 或其 session；不得访问真实内网/外网。

## 3. 模块接口定义

### 3.1 DatabaseManager (core/db_manager.py)

```python
class DatabaseManager:
    def __init__(self, db_path: Path | str | None = None) -> None: ...
    def init_database(self) -> None: ...
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]: ...
    def execute_script(self, script: str) -> None: ...
    def table_exists(self, table_name: str) -> bool: ...
    def get_table_row_count(self, table_name: str) -> int: ...
```

### 3.2 OfficeToolbox (services/office_toolbox.py) — COM 版

```python
class OfficeToolbox:
    def __init__(self, db: DatabaseManager) -> None: ...
    def export_deliverables_excel(self, output_path: Path | None = None) -> Path: ...
    def refresh_weekly_ppt(self, template_path: Path | None = None, output_path: Path | None = None) -> Path: ...
```

### 3.3 FeishuImapParser (services/feishu_imap.py)

```python
class FeishuImapParser:
    def __init__(self, db: DatabaseManager, imap_host: str, imap_port: int) -> None: ...
    def scan_and_parse(self) -> int: ...  # 返回入库任务数
    def sync_unsynced_tasks_to_deliverables(self, project_id: int = 1) -> int: ...
```

> F1 起：底层 IMAP 客户端为 `imapclient.IMAPClient`，不得再使用 `imaplib`。
> `_get_credentials()` 中密码必须通过 `getpass.getpass()` 获取；`scan_and_parse()` 成功保存待办后调用
> `sync_unsynced_tasks_to_deliverables()`，但返回值仍表示「新入库 feishu_tasks 数量」。

### 3.4 IntranetScraper (services/intranet_scraper.py)

```python
class IntranetScraper:
    def __init__(self, db: DatabaseManager, intranet_url: str, timeout: int) -> None: ...
    def run(self) -> None: ...
```

> 当前登录模式为浏览器内手动登录，service 不接收、不保存密码。
> 若后续新增终端凭据输入，密码字段必须使用 `getpass.getpass()`，且不得写入 `core/config.py`。

### 3.4.1 ArasCrawlerClient (P1, services/aras_crawler.py 建议新增)

> P1 Worker 的新 HTTP/AML 爬虫实现建议独立放入 `services/aras_crawler.py`，避免继续扩大
> Selenium 版 `IntranetScraper` 的职责。若 Worker 选择复用现有文件，必须保持公共签名和契约等价。
> 详见 `docs/agents/crawler_contract.md`。

```python
class ArasCrawlerClient:
    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None: ...

    def query_ewo_report(
        self,
        filters: EWOReportFilters,
        page: int = 1,
        page_size: int = 50,
        max_records: int = 2000,
        select_fields: Sequence[str] | None = None,
    ) -> EWOReportPage: ...

    def query_ncr_approval_progress(self, filters: NCRApprovalFilters) -> NCRExportResult: ...
    def extract_ncr_approval_detail(self, filters: NCRApprovalFilters) -> NCRDetailExportResult: ...
    def get_file_download_token(self, file_id: str) -> str: ...
```

**实现边界**:
- `EWOReportFilters`、`NCRApprovalFilters` 与返回 DTO 可放在同一模块或轻量子模块中；不得引入界面库。
- 生产下载文件必须做显式 opt-in，不得在查询方法里自动访问 vault 下载 URL。
- tests 只能使用 HAR fixture 和 mock session；不得触达真实内网。

### 3.5 ExcelToolbox (services/excel_toolbox.py) — P0 · xlwings

> **本节为 Worker 实现 B1–B6 的权威签名契约**。严禁擅自增删公共方法或改动参数名 / 默认值。
> 复用既有文件安全模式：`_check_file_not_locked` 占用预检、`_to_absolute`、`.bak` 备份与回滚。
> Excel 物理层必须改为 `xlwings.App(visible=False, add_book=False)`，并通过 `app.api` 设置
> `DisplayAlerts=False`、`ScreenUpdating=False`、`EnableEvents=False`。保存必须走
> `book.api.SaveAs(..., FileFormat=51)`。
> **无 DatabaseManager 依赖**（纯文件工具）。

```python
def _get_xlwings() -> Any: ...
# 延迟导入 xlwings as xw；供 tests monkeypatch，不再暴露 _get_win32com。

class ExcelToolbox:
    def __init__(self) -> None: ...

    def collect_sources(
        self,
        paths: list[Path] | None = None,
        directory: Path | None = None,
    ) -> list[Path]: ...
    # 汇总显式 paths + 扫描 directory 下 *.xlsx/*.xls，去重排序返回

    def _backup(self, target: Path) -> Path: ...
    # shutil.copy2 → data/.backup/<name>.<YYYYMMDD_HHMMSS>.bak，返回备份路径
    # 约定: target 不存在时抛 FileNotFoundError（调用方在"已存在才备份"分支内调用）

    def _rollback(self, target: Path, backup: Path) -> None: ...
    # shutil.copy2(backup, target) 复制回原位；backup 缺失则记录并安静返回

    def merge_append(
        self,
        sources: list[Path],
        output_path: Path | None = None,
        baseline: Path | None = None,
    ) -> Path: ...
    # 纵向追加：各 source 行尾接式合并到新工作簿。
    # baseline 非空 → 对相对 baseline 的新增/变更行 _highlight_cell + _write_legend。
    # output_path 为 None → _auto_output_name。改写已存在 output 前 _backup。

    def merge_overlay(
        self,
        sources: list[Path],
        target: Path,
        output_path: Path | None = None,
        baseline: Path | None = None,
    ) -> Path: ...
    # 坐标重合：以 target 为底，各 source 按相同单元格坐标覆盖/合并。
    # 冲突格按来源 _highlight_cell 标色；baseline 非空时高亮变更 + _write_legend。
    # 改写 target / 已存在 output 前 _backup。

    def diff_against_baseline(
        self,
        target: Path,
        baseline: Path,
        output_path: Path | None = None,
    ) -> Path: ...
    # 逐单元格比对 .Value 与 .Formula；差异格 _highlight_cell（color_map 区分新增/修改/删除）。
    # 只读 baseline，输出标注副本（改写已存在 output 前 _backup）+ _write_legend。

    def _highlight_cell(self, sheet: Any, row: int, col: int, source_tag: str) -> None: ...
    # 按 source_tag 在 color_map 分配/复用莫兰迪色；写入前读原 Interior.Color，撞色则顺延取下一色；
    # 写入 sheet.range((row, col)).api.Interior.Color = <bgr>

    def _write_legend(self, workbook: Any, color_map: dict[str, int]) -> None: ...
    # 新增独立 Sheet「图例说明」，逐行写"来源标签 ↔ 色块"（行单元格 api.Interior.Color 设为对应色值）

    @staticmethod
    def _auto_output_name(src: Path, suffix: str = "-汇总") -> Path: ...
    # src.with_stem(src.stem + suffix) 风格，输出到 OUTPUT_DIR
```

**xlwings 生命周期 & 回滚骨架（Worker 每个 merge/diff 方法须遵循）**:

```
backup = None
if output/target 已存在:
    backup = self._backup(target)
app = None
books = []
try:
    xw = _get_xlwings()
    app = xw.App(visible=False, add_book=False)
    app.api.DisplayAlerts = False
    app.api.ScreenUpdating = False
    app.api.EnableEvents = False
    ...  # app.books.open/add、sheet.range((r, c)).value、_highlight_cell、_write_legend
    out_book.api.SaveAs(self._to_absolute(output_path), FileFormat=51)
    return output_path
except Exception:
    if backup is not None:
        self._rollback(target, backup)
    raise
finally:
    for book in reversed(books):
        try: book.close()
        except Exception: pass
    if app is not None: app.quit()
```

**莫兰迪色板规格**: 6–8 个低饱和 BGR 整数循环分配；`color_map`（来源标签 → 色值）贯穿一次操作并交 `_write_legend`。
底色读写必须通过 `Range.api.Interior.Color` 完成。

### 3.6 VerticalForms (services/vertical_forms.py) — 占位

```python
class EWOForm:           # 工程变更单
    ...                  # 所有方法体: raise NotImplementedError("待真实模板接入")
class NCRForm: ...       # 不合格报告
class DMUReviewForm: ... # DMU 评审
class StylingReviewForm: ...  # 造型评审
```
> **严禁预写业务逻辑 / COM 调用**，仅空类骨架。

### 3.7 配置 (core/config.py) — 集中常量

```python
PROJECT_ROOT: Path; DATA_DIR: Path; OUTPUT_DIR: Path; TEMPLATE_DIR: Path
BACKUP_DIR: Path          # DATA_DIR / ".backup"
DB_PATH: Path
DEFAULT_INTRANET_URL: str; DEFAULT_IMAP_HOST: str; DEFAULT_IMAP_PORT: int
FLASK_HOST: str; FLASK_PORT: int
```
> **禁存明文密码 / token**；无类、无业务逻辑、不 import 界面库。

### 3.8 WEB 适配层 (web/app.py) — Flask

```python
def create_app() -> Flask: ...
# GET /            → render dashboard.html
# GET /api/overview → 复用 DatabaseManager 概览查询，jsonify 返回:
#   { "projects": {status: count}, "deliverables": {status: count},
#     "feishu": {"total": int, "synced": int} }
# POST /api/aras/ewo/query    → 调用 ArasCrawlerClient.query_ewo_report，返回 rows/page/item_ids/count
# POST /api/aras/ncr/progress → 调用 ArasCrawlerClient.query_ncr_approval_progress，返回 file_id/file_name/record_id
# POST /api/aras/ncr/detail   → 调用 ArasCrawlerClient.extract_ncr_approval_detail，返回 file_name
```
> Flask 仅做路由 + 序列化；概览查询逻辑复用 service/core，不在路由内写死超出最小复用范围。
> P1 Aras API 必须 POST JSON，`base_url` 与鉴权 headers/cookie 每次由用户显式提交；不得服务器端持久化。

## 4. 数据流

```
[飞书邮件] → IMAPClient → FeishuImapParser → feishu_tasks 表 (synced=0)
                                                   │
                                                   │ sync_unsynced_tasks_to_deliverables(project_id=1)
                                                   ▼
[内网页面] → Selenium → IntranetScraper ───▶ deliverables 表
                                              │
                                              ▼
                                    OfficeToolbox.refresh_weekly_ppt()
                                              │
                                              ▼
                                    data/output/周报_YYYYMMDD.pptx
```

### 4.1 P0 Excel 工具箱数据流（CLI 适配）

```
[本地 .xlsx 散表]
   │ collect_sources(paths|directory)
   ▼
ExcelToolbox.merge_append / merge_overlay / diff_against_baseline   (xlwings.App)
   │  改写前 _backup → data/.backup/*.bak
   │  baseline 非空 → _highlight_cell(莫兰迪色) + _write_legend(图例说明 Sheet)
   ▼
data/output/<name>-汇总.xlsx        ← 异常时 _rollback 还原，finally 关闭 Book + app.quit()
   ▲
   │ handle_excel_toolbox(db)  ← main.py CLI 适配层（rich 子菜单 + 异常分类提示）
```

### 4.2 P2 项目可视化数据流（WEB 适配）

```
[浏览器] ──GET /──▶ Flask render dashboard.html
[浏览器] ──fetch('/api/overview')──▶ web/app.py 路由
                                        │ 复用 DatabaseManager 概览查询
                                        ▼
                                  SQLite (projects / deliverables / feishu_tasks)
                                        │ jsonify
   概览卡片 ◀──JSON──────────────────────┘   (static/app.js 渲染)
```

### 4.3 P1 Aras 内网爬虫双轨数据流

```
CLI:
[用户输入 base_url + Cookie/header + filters]
       │ rich Prompt / Confirm
       ▼
main.py::handle_intranet_scrape()
       │ ArasCrawlerClient(base_url, headers, cookies)
       ▼
services/aras_crawler.py
       │ EWOReportPage / NCRExportResult / NCRDetailExportResult / ArasCrawlerError
       ▼
rich Table / 脱敏错误提示

WEB:
[dashboard P1 表单]
       │ fetch POST /api/aras/...
       ▼
web/app.py Flask route
       │ 每次请求即时构造 ArasCrawlerClient；不存 Cookie/token
       ▼
services/aras_crawler.py
       │ DTO
       ▼
jsonify({ok, data}) ──▶ app.js 异步队列渲染表格/摘要
```

> 两条轨道共享同一 service；差异只在输入采集与输出渲染。任何鉴权信息只在本次调用内存中存在。

## 5. 迁移策略

当表结构变更时：
1. Architect 在 task.md 中添加迁移任务
2. 输出 `ALTER TABLE` 语句到 implementation_plan.md 第 6 节
3. Worker 在 `db_manager.py` 中追加迁移逻辑
4. 更新 project_state.md 第 3 节

---

## 6. 迁移记录

### 2026-06-17: Sprint 2 — `projects` 兜底项目幂等插入（task A2）

**背景**: `deliverables.project_id` 为 `NOT NULL` 且外键 `REFERENCES projects(id)`，
启用 `PRAGMA foreign_keys=ON` 后，空库直接插入交付物会因无父项目而违反外键约束（孤儿）。
飞书同步桥（Backlog F1-a）也需要一个默认归属项目。

**变更**: 在 `init_database()` 的建表循环之后、`conn.commit()` 之前追加一条幂等插入：

```sql
INSERT OR IGNORE INTO projects (id, name, manager, status)
VALUES (1, '未归类', 'system', 'active');
```

**性质**: 幂等（`INSERT OR IGNORE` + 固定 `id=1`），重复 `init_database()` 不增行、不覆盖既有数据。
本轮**不涉及** `ALTER TABLE` / 表结构变更，仅数据兜底。

**关联任务**: task A2；验收见 task E2（兜底项目存在性 + 建表幂等）。

> 说明: `synced` 同步桥、明文密码→getpass、imaplib→imapclient 已提升为 F1 目标；
> Worker 写入范围与验收拆解见 task.md「F. F1」。
