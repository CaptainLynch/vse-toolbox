# 🗺️ implementation_plan.md — 架构实施计划

> **用途**: Architect 输出的顶层设计文档，Worker 严格按此实现。
> **维护者**: 仅 Architect 可修改。Worker 只读参照。
> **关联**: 每个实施项对应 `task.md` 中的具体任务编号。

---

## 1. 整体架构图

```
┌─────────────┐
│   main.py   │  ← CLI 菜单路由（零业务逻辑）
└──────┬──────┘
       │ 调用
       ├──────────────────────┬──────────────────────┐
       ▼                      ▼                      ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ IntranetScraper│  │ FeishuImapParser │   │  OfficeToolbox   │
│ (Selenium)    │  │ (imapclient)     │   │ (win32com COM)   │
└──────┬───────┘   └────────┬─────────┘   └────────┬─────────┘
       │                    │                       │
       │  所有 service 统一依赖                      │
       └────────────────────┼───────────────────────┘
                            ▼
                   ┌─────────────────┐
                   │  DatabaseManager │
                   │  (SQLite WAL)   │
                   └─────────────────┘
```

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

## 5. 迁移策略

当表结构变更时：
1. Architect 在 task.md 中添加迁移任务
2. 输出 `ALTER TABLE` 语句到 implementation_plan.md 第 6 节
3. Worker 在 `db_manager.py` 中追加迁移逻辑
4. 更新 project_state.md 第 3 节

---

## 6. 迁移记录

> （暂无迁移）

