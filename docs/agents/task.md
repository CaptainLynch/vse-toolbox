# 📝 task.md — 任务拆解与进度追踪

> **用途**: Architect 将功能需求拆解为函数级别的具体任务，Worker 逐项执行并勾选。
> **维护者**: Architect 创建任务，Worker 标记完成状态，Reviewer 确认。
> **规则**: 每项任务的粒度必须精确到单个函数或方法，禁止一次性指派整个文件。
> **关联**: 架构契约见 `implementation_plan.md`；进度快照见 `project_state.md`。

---

## 任务状态图例

- `[ ]` 待执行
- `[~]` 进行中（Worker 已开始但未完成测试）
- `[x]` 已完成（已通过 pytest + flake8 验证）
- `[!]` 阻塞（需人工介入或其他任务前置）
- `🔀` 可与同组其他任务并行分派给不同 Worker

---

## 当前迭代: Sprint 2 — 双轨界面 (Dual-Interface) + P0 Excel 工具箱

> **目标**: 将单一 CLI 升级为「CLI 适配层 + WEB 适配层 共享 service 层」的双轨架构。
> 本轮全面落地 **P0 Excel 工具箱（CLI）**，搭建 **P2 项目可视化 WEB Demo 骨架**，
> 隔离 P1/P3/P4 延期模块，并补齐测试。
>
> **解耦铁律**（Worker 必须遵守）: `services/*`、`core/*` 不得 import `rich` / `flask` /
> 任何界面库；只接收参数、返回数据/`Path`、抛领域异常。界面适配仅存在于
> `main.py`（CLI）与 `web/app.py`（WEB）。详见 implementation_plan.md §2.5。
>
> **签名铁律**: Worker 严格对齐本文件给出的方法签名与 implementation_plan.md §3.5
> 的 ExcelToolbox 完整契约，不得擅自增删公共方法或改动参数名 / 默认值。

---

### A. 基础设施 — `core/` + `main.py`

> 并行组 **{A1, A2}** 可同时分派；**A3** 独立（仅依赖现有 main.py）。

- [x] 🔀 **A1** `core/config.py`（新建）— 集中配置常量模块
  - 目标文件: `core/config.py`
  - 内容: 顶层模块级常量，**无类、无业务逻辑**：
    ```python
    PROJECT_ROOT: Path        # Path(__file__).resolve().parent.parent
    DATA_DIR: Path            # PROJECT_ROOT / "data"
    OUTPUT_DIR: Path          # DATA_DIR / "output"
    TEMPLATE_DIR: Path        # DATA_DIR / "templates"
    BACKUP_DIR: Path          # DATA_DIR / ".backup"
    DB_PATH: Path             # DATA_DIR / "vse_toolbox.db"
    DEFAULT_INTRANET_URL: str # "https://intranet.example.com"
    DEFAULT_IMAP_HOST: str    # "imap.example.com"
    DEFAULT_IMAP_PORT: int    # 993
    FLASK_HOST: str           # "127.0.0.1"
    FLASK_PORT: int           # 5000
    ```
  - 约束: **严禁存放任何明文密码 / token / 凭据**；只放路径与无敏感默认值。不 import rich/flask。
  - 依赖: 无
  - 验收: `from core import config` 可导入；`mypy` 通过；常量类型标注完整。

- [x] 🔀 **A2** `core/db_manager.py::init_database()` — 末尾幂等插入「未归类」兜底项目
  - 目标文件: `core/db_manager.py`（仅在既有 `init_database()` 的 `commit()` 之前追加一条语句，**不改动其他方法**）
  - 修复缺陷: `deliverables.project_id` 外键孤儿 —— 提供 `id=1` 兜底项目，避免无项目时插入交付物违反外键。
  - 建议 SQL（追加到 `for ddl in TABLE_DEFINITIONS` 循环之后、`conn.commit()` 之前）:
    ```sql
    INSERT OR IGNORE INTO projects (id, name, manager, status)
    VALUES (1, '未归类', 'system', 'active');
    ```
  - 约束: 必须用 `INSERT OR IGNORE` 保证幂等；显式写死 `id=1`；不破坏既有 AUTOINCREMENT 数据。
  - 依赖: 无（与 A1 并行）
  - 验收: 全新库 `init_database()` 后 `projects` 含 `id=1 名称='未归类'`；重复调用行数不增（见 E2）。

- [x] **A3** `main.py` — `MENU_OPTIONS` 改为直接函数对象引用，消除 `globals()` 反射
  - 目标文件: `main.py`
  - 签名变更:
    ```python
    from typing import Callable
    MENU_OPTIONS: dict[str, tuple[str, Callable[[DatabaseManager], None]]] = {
        "1": ("更新交付物状态", handle_update_deliverables),
        # ...
    }
    ```
  - `main()` 循环: 由 `handler_name = ...; globals().get(handler_name)` 改为
    `label, handler = MENU_OPTIONS[choice]; handler(db)`（直接调用函数对象）。
  - 约束: 因 `MENU_OPTIONS` 引用函数对象，**定义位置须移到所有 `handle_*` 函数之后**；保持 `show_menu()` 的解包 `for key, (label, _) in ...` 兼容。
  - 依赖: 无（独立；但 B8/D1 都依赖本任务先完成）
  - 验收: `python main.py` 菜单路由正常；`mypy` 对 `Callable` 标注通过；无 `globals()` 调用残留。

---

### B. P0 Excel 工具箱 — `services/excel_toolbox.py`（全部 win32com COM）

> **契约权威**: 方法签名以 implementation_plan.md §3.5 为准，本节给出依赖与验收。
> 串行起点 **B1** 先行 → 并行组 **{B2, B3}** → 并行组 **{B4, B5, B6}**（依赖 B1/B2/B3）
> → **B8**（依赖 B4/B5/B6 + A3）。**B7** 全程独立可并行。

- [x] **B1** 模块骨架 + COM 复用辅助
  - 目标文件: `services/excel_toolbox.py`（新建）
  - 实现:
    - `def _get_win32com() -> Any` —— **复用** office_toolbox 的延迟导入模式（模块级 `_win32com` 缓存 + ImportError 友好提示）。
    - `class ExcelToolbox: def __init__(self) -> None` —— 无 db 依赖；`BACKUP_DIR.mkdir(parents=True, exist_ok=True)`（A1 常量）。
    - `def collect_sources(self, paths: list[Path] | None = None, directory: Path | None = None) -> list[Path]` —— 汇总显式 paths + 扫描 directory 下 `*.xlsx`/`*.xls`，去重排序返回。
    - `@staticmethod def _auto_output_name(src: Path, suffix: str = "-汇总") -> Path` —— `src.with_stem(src.stem + suffix)` 风格生成默认输出名（输出到 `OUTPUT_DIR`）。
    - 复用 office_toolbox 的 `_check_file_not_locked` / `_to_absolute` 模式（可在本类内重新实现同名静态方法，保持 DLP 安全模式一致）。
  - 约束: 不 import rich；异常用 `print` 之外的方式或直接抛出（界面提示交给 main.py）。Excel `Visible=False`、`DisplayAlerts=False`、`SaveAs FileFormat=51`。
  - 依赖: A1（BACKUP_DIR/OUTPUT_DIR 常量）
  - 验收: 模块可导入；`collect_sources` / `_auto_output_name` 单元可测（见 E3）。

- [x] 🔀 **B2** `_backup` / `_rollback` — 磁盘 `.bak` 回滚机制
  - 目标文件: `services/excel_toolbox.py`
  - 实现:
    - `def _backup(self, target: Path) -> Path` —— `target` 存在时 `shutil.copy2` 到
      `BACKUP_DIR / f"{target.name}.{timestamp}.bak"`，返回备份路径；`target` 不存在则返回某哨兵（约定返回 `None` 不可行，签名为 `-> Path`，故**约定: 不存在时不备份并抛 `FileNotFoundError` 由调用方判断是否需要**——见 implementation_plan §3.5 注释）。
    - `def _rollback(self, target: Path, backup: Path) -> None` —— `shutil.copy2(backup, target)` 复制回原位；备份不存在则记录并安静返回。
  - 约束: 时间戳格式 `%Y%m%d_%H%M%S`；仅磁盘临时备份，不入库。
  - 依赖: A1（BACKUP_DIR）
  - 验收: E3 断言「改写已存在文件前调用 `_backup`」「构造异常时 `_rollback` 被调用并上抛」。

- [x] 🔀 **B3** 莫兰迪色板 + `_highlight_cell` + `_write_legend`
  - 目标文件: `services/excel_toolbox.py`
  - 实现:
    - 模块级常量 `MORANDI_PALETTE: list[int]` —— **6–8 个**低饱和莫兰迪色 BGR 整数（COM `Interior.Color` 为 BGR 十进制）。
    - `def _highlight_cell(self, sheet: Any, row: int, col: int, source_tag: str) -> None` ——
      按 `source_tag` 在 `color_map` 中分配/复用颜色；**写入前读取单元格原 `Interior.Color`，若与待写色撞色则顺延取色板下一色**；写入 `sheet.Cells(row, col).Interior.Color = <bgr>`。
    - `def _write_legend(self, workbook: Any, color_map: dict[str, int]) -> None` ——
      新增独立 Sheet「图例说明」，逐行写「来源标签 ↔ 色块（该行单元格 Interior.Color 设为对应色值）」。
  - 约束: `color_map`（来源标签 → 色值）在一次合并/比对操作内**全程贯穿**，最终交给 `_write_legend`。撞色检测仅作用于目标单元格已有底色。
  - 依赖: 无（与 B2 并行，仅依赖 B1 骨架存在）
  - 验收: E3 断言「`_highlight_cell` 撞色顺延取下一色」「`_write_legend` 创建名为『图例说明』的 Sheet」。

- [x] 🔀 **B4** `merge_append` — 纵向追加合并
  - 目标文件: `services/excel_toolbox.py`
  - 签名: `def merge_append(self, sources: list[Path], output_path: Path | None = None, baseline: Path | None = None) -> Path`
  - 实现: COM 打开各 source，按行纵向追加到新工作簿；`output_path` 为 None 时用 `_auto_output_name`。**`baseline` 非空时**：对相对 baseline 新增/变更的行调用 `_highlight_cell` 并维护 `color_map`，结束前调用 `_write_legend`。改写已存在 `output_path` 前先 `_backup`；COM 异常 `except` 中 `_rollback` 并上抛；`finally` 释放 COM（Close+Quit+del）。
  - 依赖: **B1 + B2 + B3**
  - 验收: E3 断言 Cells 写入序列 + `SaveAs(FileFormat=51)` + 改写前 `_backup` + finally `Quit()`。

- [x] 🔀 **B5** `merge_overlay` — 坐标重合合并
  - 目标文件: `services/excel_toolbox.py`
  - 签名: `def merge_overlay(self, sources: list[Path], target: Path, output_path: Path | None = None, baseline: Path | None = None) -> Path`
  - 实现: 以 `target` 为底，将各 source **按相同单元格坐标**覆盖/合并写入；冲突单元格按来源 `_highlight_cell` 标色。`baseline` 非空时高亮变更并写图例。改写 `target`/`output_path` 前 `_backup`；异常 `_rollback` 上抛；`finally` 释放 COM。
  - 依赖: **B1 + B2 + B3**
  - 验收: E3 断言坐标写入序列 + `SaveAs(51)` + 改写前 `_backup` + finally `Quit()`。

- [x] 🔀 **B6** `diff_against_baseline` — 数据 + 公式差异比对
  - 目标文件: `services/excel_toolbox.py`
  - 签名: `def diff_against_baseline(self, target: Path, baseline: Path, output_path: Path | None = None) -> Path`
  - 实现: COM 打开 `target` 与 `baseline`，逐单元格比对**值与公式**（`.Value` 与 `.Formula` 均比对）；差异单元格经 `_highlight_cell` 标色，`color_map` 区分「新增/修改/删除」语义标签；输出标注后的副本，`_write_legend` 写图例。比对为只读 baseline，仅改写输出副本（改写前 `_backup`）。
  - 依赖: **B1 + B3**（比对生成新文件，不一定改写既有文件，但若 `output_path` 已存在仍须 `_backup`，故同时建议依赖 B2）
  - 验收: E3 断言差异定位与高亮调用；finally `Quit()`。

- [x] 🔀 **B7** `services/vertical_forms.py` — 四个垂类表单空类占位
  - 目标文件: `services/vertical_forms.py`（新建）
  - 实现: `EWOForm` / `NCRForm` / `DMUReviewForm` / `StylingReviewForm` 四个**空类**，每个公共方法体仅 `raise NotImplementedError("待真实模板接入")`。
  - 约束: **严禁预写任何业务逻辑 / COM 调用**；仅占位骨架与 docstring。
  - 依赖: 无（全程独立可并行）
  - 验收: 可导入；实例化方法调用即抛 `NotImplementedError`。

- [x] **B8** `main.py` — 接入 P0「Excel 工具箱」子菜单 handler（CLI 适配层）
  - 目标文件: `main.py`
  - 实现: 新增 `def handle_excel_toolbox(db: DatabaseManager) -> None` —— rich 二级菜单（合并-追加 / 合并-重合 / 差异比对），交互收集源文件/baseline/输出路径，实例化 `ExcelToolbox()` 调用对应方法，捕获 `PermissionError`/`FileNotFoundError`/通用异常并 rich 提示。注册进 `MENU_OPTIONS`（新键，如 `"6"`）。
  - 约束: 本任务是**唯一**允许 import rich 并调用 ExcelToolbox 的接入点；不得在此写 COM 逻辑。
  - 依赖: **B4 + B5 + B6 + A3**
  - 验收: `python main.py` 进入子菜单可触发三种操作；异常被分类提示。

---

### C. WEB 骨架 — P2 项目可视化大屏 Demo（`web/`）

> 串行起点 **C1** 先行 → 并行组 **{C2, C3}**（依赖 C1）。
> **C 整组与 B 组可跨界面并行**（不同 Worker 同时推进 CLI 与 WEB）。

- [x] **C1** `web/app.py` — Flask 应用 + `GET /api/overview`
  - 目标文件: `web/app.py`（新建）+ `web/__init__.py`（新建空文件）
  - 实现:
    - `def create_app() -> Flask` 工厂；`FLASK_HOST` / `FLASK_PORT` 取自 `core.config`。
    - 路由 `GET /` —— 渲染 `dashboard.html`。
    - 路由 `GET /api/overview` —— 实例化 `DatabaseManager()`，**复用** db 概览查询（projects/deliverables 按 status 计数 + feishu 总计/已同步），组装为 dict 并 `jsonify` 返回。
  - 约束: **WEB 适配层** —— 查询逻辑应调用 `core/services` 数据方法；Flask 仅做 JSON 序列化与路由，**不得把业务 SQL 写死在路由里超过最小复用范围**（概览查询若已存在可抽取复用）。`app.py` 是唯一 import flask 的文件。
  - 依赖: A1（FLASK_HOST/PORT）
  - 验收: `python -m web.app` 启动后 `curl /api/overview` 返回合法 JSON；service 层无 flask 依赖。

- [x] 🔀 **C2** `web/templates/dashboard.html` — P2 Demo 大屏骨架 + 模块导航
  - 目标文件: `web/templates/dashboard.html`（新建）
  - 实现: 极简大屏 HTML 骨架（标题 + 概览卡片占位容器 + 模块导航条）。导航列出 Excel 工具箱 / 内网爬虫 / 项目可视化 / 周报 PPT / 飞书助手；**未就绪模块（P1/P3/P4）标灰 `disabled` 占位**，仅「项目可视化」可点亮。
  - 约束: 引用 `static/` 下 CSS/JS（C3）；不内联大段脚本。
  - 依赖: C1
  - 验收: 浏览器打开渲染出大屏骨架 + 置灰导航。

- [x] 🔀 **C3** `web/static/` — 极简 CSS + JS
  - 目标文件: `web/static/style.css`（新建）+ `web/static/app.js`（新建）
  - 实现: `app.js` 用 `fetch('/api/overview')` 拉取概览并渲染卡片（项目数 / 交付物各状态 / 飞书待办）；`style.css` 提供大屏深色基调 + 卡片栅格 + 置灰态样式。
  - 约束: 原生 fetch + DOM，**不引入前端框架**（保持「仅引入 Flask」决策）。
  - 依赖: C1（API 契约）
  - 验收: 页面加载后概览卡片由真实 `/api/overview` 数据填充。

---

### D. 延期模块隔离 — `main.py` 置灰

> 依赖 **A3**（菜单结构改造后再接入置灰逻辑）。

- [x] **D1** `main.py` — P1/P3/P4 菜单项置灰 + 选中提示
  - 目标文件: `main.py`
  - 实现: P1 内网爬虫 / P3 周报 PPT / P4 飞书助手 对应菜单项在 `show_menu()` 中以暗色（如 `dim`）渲染并标注「（暂缓）」；其 handler 改为统一提示「该模块暂缓开放」并 return，**不调用未就绪逻辑**。可用 `MENU_OPTIONS` 值的第三元素或独立 `DEFERRED` 集合标记。
  - 约束: 不删除既有 handler 代码，仅短路；P0 Excel（B8）与 P2 WEB 不在置灰之列。
  - 依赖: A3
  - 验收: 选中 P1/P3/P4 仅提示暂缓，无异常、无副作用。

---

### E. 测试 — `tests/`（mock COM，依赖对应实现）

> **E1** 先行（fixture 基座）→ **E2**（依赖 A2）、**E3**（依赖 B1–B6）可并行。

- [x] **E1** `tests/conftest.py` — 临时数据库 fixture
  - 目标文件: `tests/conftest.py`（新建）
  - 实现: `@pytest.fixture def tmp_db(tmp_path) -> DatabaseManager` —— 用 `tmp_path` 构造隔离库，`init_database()`，预置若干 `projects` / `deliverables` 行供其他测试复用。
  - 依赖: 无（但 E2/E3 复用本 fixture）
  - 验收: fixture 可注入；隔离不污染真实 `data/vse_toolbox.db`。

- [x] 🔀 **E2** `tests/test_db_manager.py`
  - 目标文件: `tests/test_db_manager.py`（新建）
  - 断言: ①兜底项目存在（`id=1 名称='未归类'`，验证 A2）；②建表幂等（重复 `init_database()` 行数不变）；③`get_connection()` 在异常时回滚（构造写入异常断言无脏数据）。
  - 依赖: A2 + E1
  - 验收: `pytest tests/test_db_manager.py` 全绿。

- [x] 🔀 **E3** `tests/test_excel_toolbox.py` — mock `_get_win32com`
  - 目标文件: `tests/test_excel_toolbox.py`（新建）
  - 实现: monkeypatch `excel_toolbox._get_win32com` 注入**假 Excel.Application**（MagicMock 记录 `Cells(...).Value`、`Interior.Color`、`SaveAs`、`Quit` 调用）。
  - 断言:
    - `merge_append` / `merge_overlay` 的 Cells 写入序列正确，且调用 `SaveAs(..., FileFormat=51)`；
    - 改写已存在文件前调用 `_backup`；
    - 构造 COM 异常时调用 `_rollback` 并上抛（`pytest.raises`）；
    - `_highlight_cell` 撞色时顺延取下一色；
    - `_write_legend` 创建名为「图例说明」的 Sheet；
    - `finally` 中 `Quit()` 被调用（即便异常路径）；
    - 占用文件（mock `_check_file_not_locked` 返回 False）触发 `PermissionError`。
  - 依赖: B1 + B2 + B3 + B4 + B5 + B6 + E1
  - 验收: `pytest tests/test_excel_toolbox.py` 全绿；无真实 Excel 进程启动。

---

## 🔀 可并行分派矩阵（给调度中心）

| 波次 | 可同时分派的任务组 | 前置 | 跨界面并行 |
|---|---|---|---|
| W1 | **{A1, A2}** + **A3** + **B7** | 无 | — |
| W2 | **B1**（待 A1） · **C1**（待 A1） | A1 | B 组 ∥ C 组 |
| W3 | **{B2, B3}** · **{C2, C3}**（待 C1） | B1 / C1 | B 组 ∥ C 组 |
| W4 | **{B4, B5, B6}** · **E1** | B1+B2+B3 | — |
| W5 | **B8**（待 B4/B5/B6+A3） · **D1**（待 A3） · **{E2, E3}** | 见各项 | — |

> **跨界面并行总则**: 整个 **B 组（CLI/Excel）** 与 **C 组（WEB）** 仅在 A1 完成后即可由
> 两名 Worker 完全并行推进，互不阻塞（service 层解耦保证无共享可变状态）。

---

## ✅ 首批可立即开工任务（无任何前置）

> 调度中心可在 0 时刻同时分派给至多 4 名 Worker：

- **A1** `core/config.py`（基座，解锁 B1/C1）
- **A2** `db_manager` 兜底项目（解锁 E2）
- **A3** `main.py` 菜单 Callable 化（解锁 B8/D1）
- **B7** `vertical_forms.py` 占位（完全独立）

---

### F. F1 — 飞书待办闭环 + 凭据安全 + IMAPClient 迁移

> **目标**: 把 Backlog F1-a/b/c 提升为下一批 Worker 目标。F1 只允许 Worker 修改
> `services/feishu_imap.py`、`services/intranet_scraper.py`（如发现明文密码交互才改）以及对应 `tests/`；
> 不改表结构、不改 `core/config.py` 写入敏感字段、不改已完成 Sprint 2 文档任务状态。
>
> **架构依据**: implementation_plan.md §2.9 与 §3.3。service 层仍不得 import flask；
> `services/feishu_imap.py` 当前已有 rich 交互属于存量 CLI 型 service，F1 不扩大 rich 使用面。

- [x] **F1-a1** `services/feishu_imap.py::FeishuImapParser.sync_unsynced_tasks_to_deliverables()` — 新增飞书待办同步桥
  - 目标文件: `services/feishu_imap.py`
  - 签名: `def sync_unsynced_tasks_to_deliverables(self, project_id: int = 1) -> int`
  - 实现: 在单个 `self._db.get_connection()` 事务内读取 `feishu_tasks WHERE synced=0 ORDER BY id`；
    逐条插入 `deliverables`，并仅把成功插入的同批 `feishu_tasks.id` 更新为 `synced=1`。
  - 字段映射: `project_id` 默认 `1`；`name = title or "未命名飞书待办"`；
    `owner = assignee or ""`；`due_date = deadline or None`；`status = "pending"`；
    `remark = "飞书待办同步: <source_email_id>"`（无来源时用空字符串或任务 id）。
  - 约束: 不新增表/列；不吞数据库异常；异常由 `get_connection()` 回滚；返回本次同步条数。
  - 依赖: Sprint 2 A2（`projects.id=1` 兜底项目已完成）
  - 验收: F1-v1 覆盖正常同步、空标题 fallback、重复调用不重复插入。

- [x] **F1-a2** `services/feishu_imap.py::FeishuImapParser.scan_and_parse()` — 保存后触发同步桥
  - 目标文件: `services/feishu_imap.py`
  - 实现: `_save_tasks(tasks)` 成功后调用 `self.sync_unsynced_tasks_to_deliverables(project_id=1)`；
    控制台提示可包含同步条数，但 `scan_and_parse()` 返回值仍保持 `saved_count`（新入库 feishu_tasks 数量）。
  - 约束: 不改变连接失败返回 `0` 的行为；单封邮件解析异常继续跳过；同步桥异常不得被误报为解析成功。
  - 依赖: F1-a1
  - 验收: F1-v1 用 monkeypatch 断言 `_save_tasks` 后调用同步桥，且返回值仍为 saved_count。

- [x] **F1-b1** `services/feishu_imap.py::FeishuImapParser._get_credentials()` — 密码输入改为 `getpass.getpass`
  - 目标文件: `services/feishu_imap.py`
  - 实现: 新增 `import getpass`；用户名可继续使用 `Prompt.ask()`；密码 / 应用专用密码必须使用
    `getpass.getpass("请输入邮箱密码 / 应用专用密码: ")` 或等价提示。
  - 约束: 不使用 `Prompt.ask(..., password=True)` 作为替代；不把密码写入日志、异常文本、config 常量或实例属性。
  - 依赖: 无（可与 F1-a1/F1-c1 并行，但注意同文件合并）
  - 验收: F1-v2 monkeypatch `getpass.getpass`，断言 `_get_credentials()` 返回密码且未调用密码字段的 `Prompt.ask`。

- [x] **F1-b2** `services/intranet_scraper.py` — 明文密码交互安全审查与最小修正
  - 目标文件: `services/intranet_scraper.py`
  - 实现: 检查本文件是否存在终端密码输入（例如 `Prompt.ask`/`input` 获取 password/token/secret）。
    若存在，限定在对应函数内改为 `getpass.getpass()`；若不存在，保持浏览器内手动登录流程不变。
  - 约束: 不新增账号/密码参数；不把内网密码放入 `core/config.py`；不改变 `_wait_for_user_login()` 的人工登录确认语义。
  - 依赖: 无
  - 验收: F1-v2 grep 证明 intranet_scraper 无 plaintext password Prompt；如发生代码修正，补单元测试或静态断言。

- [x] **F1-c1** `services/feishu_imap.py::FeishuImapParser._connect()` — 从 `imaplib.IMAP4_SSL` 迁移到 `imapclient.IMAPClient`
  - 目标文件: `services/feishu_imap.py`
  - 实现: 移除 `import imaplib`；改为 `from imapclient import IMAPClient` 及必要异常类型；
    `_conn` 类型改为 IMAPClient 兼容类型；`_connect()` 使用 `IMAPClient(self._imap_host, port=self._imap_port, ssl=True)` 并调用 `login(username, password)`。
  - 约束: 登录/协议/网络异常统一转为 `ConnectionError`；日志不得包含密码；保留现有成功/失败用户提示语义。
  - 依赖: 无（与 F1-b1 同文件，建议同一 Worker 顺序执行）
  - 验收: F1-v3 mock IMAPClient，断言构造参数、login 调用与异常转换；grep 无 `imaplib`。

- [x] **F1-c2** `services/feishu_imap.py::FeishuImapParser.scan_and_parse()` — 适配 IMAPClient 的 select/search/fetch 返回结构
  - 目标文件: `services/feishu_imap.py`
  - 实现: 用 `self._conn.select_folder(DEFAULT_MAILBOX, readonly=False)` 替代 `select()`；
    用 `self._conn.search(["UNSEEN"])` 获取 message id 列表；用 `self._conn.fetch(ids, ["RFC822"])`
    取得原始邮件字节并继续交给 `email.message_from_bytes()`。
  - 约束: 空搜索结果返回 `0`；逐封解析失败继续记录并跳过；飞书识别与正文解析函数不重写。
  - 依赖: F1-c1
  - 验收: F1-v3 mock search/fetch 覆盖空列表、非飞书邮件跳过、飞书邮件入库路径。

- [x] **F1-c3** `services/feishu_imap.py::FeishuImapParser._disconnect()` — 适配 IMAPClient logout
  - 目标文件: `services/feishu_imap.py`
  - 实现: 保持 `if self._conn:` 防护，调用 IMAPClient 的 `logout()`；任何 logout 异常继续安静忽略，
    finally 中置 `self._conn = None`。
  - 约束: 不新增 close/shutdown 分支，除非 IMAPClient mock/文档明确需要；保持重复调用安全。
  - 依赖: F1-c1
  - 验收: F1-v3 覆盖正常 logout、logout 异常、重复 disconnect。

- [x] **F1-v1** `tests/test_feishu_sync.py` — F1-a 同步桥事务与幂等测试
  - 目标文件: `tests/test_feishu_sync.py`（新建或扩展现有同名文件）
  - 断言: ①`synced=0` 任务同步为 `deliverables(project_id=1)` 并标记 `synced=1`；
    ②空标题使用 `"未命名飞书待办"`；③第二次调用返回 0 且不重复插入；
    ④构造插入异常时不把任务误标记为 `synced=1`。
  - 依赖: F1-a1 + tests/conftest.py 的 `tmp_db`
  - 验收: `pytest tests/test_feishu_sync.py` 全绿。

- [x] **F1-v2** `tests/test_credential_safety.py` — 凭据输入与 config 安全验证
  - 目标文件: `tests/test_credential_safety.py`（新建）
  - 断言: ①`FeishuImapParser._get_credentials()` 调用 `getpass.getpass` 获取密码；
    ②`services/feishu_imap.py` 不存在密码字段的 `Prompt.ask` 明文输入；
    ③`services/intranet_scraper.py` 不存在 password/token/secret 的明文终端输入；
    ④`core/config.py` 不含 password/token/secret 常量。
  - 依赖: F1-b1 + F1-b2
  - 验收: `pytest tests/test_credential_safety.py` 全绿；静态 grep 规则通过。

- [x] **F1-v3** `tests/test_feishu_imapclient.py` — IMAPClient 迁移行为测试
  - 目标文件: `tests/test_feishu_imapclient.py`（新建或扩展现有 feishu 测试）
  - 实现: monkeypatch `services.feishu_imap.IMAPClient` 为假客户端，覆盖 `login`、`select_folder`、
    `search`、`fetch`、`logout`。
  - 断言: ①`_connect()` 使用 SSL + 端口并调用 login；②登录异常转 `ConnectionError`；
    ③`scan_and_parse()` 使用 `select_folder/search/fetch(["RFC822"])`；
    ④`_disconnect()` logout 后清空连接；⑤源码无 `imaplib`。
  - 依赖: F1-c1 + F1-c2 + F1-c3
  - 验收: `pytest tests/test_feishu_imapclient.py` 全绿；不需要真实 IMAP 网络。

- [x] **F1-r1** Reviewer 静态边界检查 — F1 代码写入范围与敏感信息检查
  - 检查范围: `services/feishu_imap.py`、`services/intranet_scraper.py`、`tests/`、`core/config.py`
  - 断言: `core/config.py` 未新增 password/token/secret；业务源码无硬编码真实凭据；
    `services/feishu_imap.py` 无 `imaplib`；除既有允许边界外未引入 flask；未改动 F1 范围外业务文件。
  - 依赖: F1-a/F1-b/F1-c 全部实现
  - 验收: Reviewer 将发现写入 `review_feedback.md`；无问题则标记本项完成。

- [x] **F1-r2** Worker 最终验证 — 聚合测试命令
  - 命令: `pytest tests/test_feishu_sync.py tests/test_credential_safety.py tests/test_feishu_imapclient.py`
  - 建议补充: `pytest` 全量、`flake8`、`mypy`（若项目当前环境可运行）。
  - 依赖: F1-v1 + F1-v2 + F1-v3
  - 验收: Worker 在交付说明中贴出执行命令与结果；如环境缺依赖，说明缺失依赖而非跳过。

---

## 🗂️ 后续 Sprint / Backlog（本轮**不实现**，仅登记）

> Architect 决策: 以下为非阻塞存量缺陷 / 演进项，登记待后续 Sprint 排期。

- [ ] **P1** 内网爬虫真实页面选择器（`_scrape_data` / `_save_to_database`）。
- [ ] **P3** 周报 PPT：本轮仅在 CLI/WEB 代码层预留入口，真实模板接入后开发。
- [ ] **P4** 飞书助手：本轮仅代码层预留入口，待需求明确后开发。

---

## 历史迭代

### Sprint 1 — 基础设施（已完成）

- [x] `core/db_manager.py` 1.1–1.6（连接管理 / 建表 / WAL / 表工具）
- [x] `services/office_toolbox.py` 2.1–2.6（COM 版 Excel/PPT 导出）
- [~] `services/feishu_imap.py` 3.1–3.4（骨架完成，imapclient 迁移移交 Backlog F1-c）
- [~] `services/intranet_scraper.py` 4.1–4.2（骨架完成，真实选择器移交 Backlog P1）
