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
│ (P0·COM) │ │ (COM)        │ │ (Selenium)   │ │ (IMAP)   │ │              │
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

### 2.1 Office I/O: win32com COM 自动化

**决策**: 放弃 pandas/openpyxl/python-pptx，改用 `win32com.client` 驱动本地 Office 进程。

**理由**: 公司 DLP 透明加密对 Python 文件库直接写入的二进制流进行加密，导致文件打开乱码。通过 COM 调用 Office 原生进程写入，走 Office 的正常保存路径，不受 DLP 干扰。

**COM 生命周期约束**:
- `Excel.Application` / `PowerPoint.Application` 必须在 `try...finally` 中操作
- `finally` 块必须包含 `Workbook.Close()` / `Presentation.Close()` + `Application.Quit()`
- 释放 COM 对象引用（`del`）以避免引用计数残留

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
  在 COM 操作前调用 `_backup(target)`；COM 异常时在 `except` 中 `_rollback(target, backup)` 并**上抛**异常。
- **备份命名**: `data/.backup/<name>.<YYYYMMDD_HHMMSS>.bak`（带时间戳，避免互相覆盖）。
- **COM 生命周期**: `try` 内执行 COM；`except` 内 `_rollback` 后 `raise`；`finally` 内 `Close + Quit + del` 释放进程。
- **与 §2.1 一致**: 复用 office_toolbox 的 `Visible=False` / `DisplayAlerts=False` / `SaveAs(FileFormat=51)` / try-finally 释放模式。

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
```

### 3.4 IntranetScraper (services/intranet_scraper.py)

```python
class IntranetScraper:
    def __init__(self, db: DatabaseManager, intranet_url: str, timeout: int) -> None: ...
    def run(self) -> None: ...
```

### 3.5 ExcelToolbox (services/excel_toolbox.py) — P0 · 全部 win32com COM

> **本节为 Worker 实现 B1–B6 的权威签名契约**。严禁擅自增删公共方法或改动参数名 / 默认值。
> 复用 office_toolbox 已验证模式：`_get_win32com` 延迟导入、`_check_file_not_locked` 占用预检、
> `_to_absolute`、`Excel.Visible=False`、`DisplayAlerts=False`、`SaveAs(FileFormat=51)`。
> **无 DatabaseManager 依赖**（纯文件工具）。

```python
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
    # 写入 sheet.Cells(row, col).Interior.Color = <bgr>

    def _write_legend(self, workbook: Any, color_map: dict[str, int]) -> None: ...
    # 新增独立 Sheet「图例说明」，逐行写"来源标签 ↔ 色块"（行单元格 Interior.Color 设为对应色值）

    @staticmethod
    def _auto_output_name(src: Path, suffix: str = "-汇总") -> Path: ...
    # src.with_stem(src.stem + suffix) 风格，输出到 OUTPUT_DIR
```

**COM 生命周期 & 回滚骨架（Worker 每个 merge/diff 方法须遵循）**:

```
backup = None
if output/target 已存在:
    backup = self._backup(target)
excel = workbook = None
try:
    excel = wc.Dispatch("Excel.Application")
    excel.Visible = False; excel.DisplayAlerts = False
    ...  # 打开 source/baseline、写入、_highlight_cell、_write_legend
    workbook.SaveAs(self._to_absolute(output_path), FileFormat=51)
    return output_path
except Exception:
    if backup is not None:
        self._rollback(target, backup)
    raise
finally:
    if workbook is not None: workbook.Close(SaveChanges=0)
    if excel is not None: excel.Quit()
    del workbook; del excel
```

**莫兰迪色板规格**: 6–8 个低饱和 BGR 整数循环分配；`color_map`（来源标签 → 色值）贯穿一次操作并交 `_write_legend`。

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
```
> Flask 仅做路由 + 序列化；概览查询逻辑复用 service/core，不在路由内写死超出最小复用范围。

## 4. 数据流

```
[飞书邮件] → IMAP → FeishuImapParser → feishu_tasks 表
                                              │ (synced=1)
                                              ▼
[内网页面] → Selenium → IntranetScraper → deliverables 表
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
ExcelToolbox.merge_append / merge_overlay / diff_against_baseline   (win32com COM)
   │  改写前 _backup → data/.backup/*.bak
   │  baseline 非空 → _highlight_cell(莫兰迪色) + _write_legend(图例说明 Sheet)
   ▼
data/output/<name>-汇总.xlsx        ← 异常时 _rollback 还原，COM finally 释放
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

> 说明: `synced` 同步桥、明文密码→getpass、imaplib→imapclient 迁移本轮**不实现**，
> 已登记至 task.md「后续 Sprint / Backlog」（F1-a/b/c）。

