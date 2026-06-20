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

### B. P0 Excel 工具箱 — `services/excel_toolbox.py`（历史 win32com 基线，已由 H 段覆盖）

> **历史说明**: B/E 组记录的是 Sprint 2 已完成的 `win32com` 基线实现与测试。自 H 段起，
> ExcelToolbox 的后续 Worker 任务以 `xlwings` 迁移为准；不得再按本节旧 API 继续扩展。

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

### H. Phase 1–3 — ExcelToolbox 强制迁移 xlwings + PowerShell pytest 修复

> **目标**: 不再讨论是否采用 `xlwings`。先解决 PowerShell 下 `python` / `pytest` 无法寻址，再把
> `services/excel_toolbox.py` 和 `tests/test_excel_toolbox.py` 迁移到 `xlwings`，最后由 Architect
> 静态审查语法并抓取真实 pytest 动态报告。
>
> **时序铁律**: **H1 必须先于 H2**。没有可执行的绝对路径 pytest 命令，不允许声称 H2 验收完成。
> **生产铁律**: 继续静默、无感知、脱密安全；Excel 输出仍走原生 `SaveAs(FileFormat=51)`，不得引入
> `pandas` / `openpyxl` 文件直写。

- [x] **H0** Architect 迁移图纸 — win32com 语义映射到 xlwings
  - 目标文件: `docs/agents/implementation_plan.md`、`docs/agents/task.md`
  - 图纸范围: `_get_win32com`、`Excel.Application`、`Workbooks.Add/Open`、`Sheets`、`Cells`、
    `UsedRange`、`.Value`、`.Formula`、`Interior.Color`、`SaveAs(FileFormat=51)`、`Close`、`Quit`。
  - 裁定: `services/excel_toolbox.py` 必须移除 `win32com.client` / `_get_win32com` / `Dispatch("Excel.Application")`；
    改为 `_get_xlwings()` + `xw.App(visible=False, add_book=False)`。
  - 验收: implementation_plan.md §2.1.1 与 §3.5 已给出可执行 API 映射、生命周期骨架与 mock 迁移要求。

- [x] **H1-a** Worker 环境诊断 — 定位可用 Python 解释器
  - 目标文件: 不改 `.py`；允许修复工作区虚拟环境或依赖安装状态。
  - 操作要求: 在 PowerShell 中诊断 `python`、`py`、`.venv\Scripts\python.exe`、已安装 Python 绝对路径。
    可使用 `where.exe python`、`where.exe py`、`py -0p`、`Get-Command python -All` 等命令。
  - 约束: 不依赖裸 `pytest` 命令；后续测试统一使用 `"<absolute-python>" -m pytest ...`。
  - 验收: Worker 交付说明中写明最终选定的 Python 绝对路径，以及为何原 `python` / `pytest` 无法寻址。

- [x] **H1-b** Worker 环境修复 — 形成可执行 pytest 命令
  - 目标文件: 不改业务 `.py`；如依赖缺失，可最小化修复 `.venv` 或安装 `requirements.txt`。
  - 允许手段:
    - 使用已存在解释器的绝对路径运行 pytest；
    - 重建工作区 `.venv`；
    - 通过 `"<absolute-python>" -m pip install -r requirements.txt` 补齐依赖；
    - 如 `requirements.txt` 缺少 `xlwings`，在 H2 中做最小依赖补丁，禁止引入 `pandas` / `openpyxl` 作为 Excel I/O。
  - 必须形成的命令模板:
    ```powershell
    & "E:\project\vse-toolbox\.venv\Scripts\python.exe" -m pytest tests/test_excel_toolbox.py -q
    ```
    若实际解释器不在 `.venv`，必须替换为 Worker 诊断出的真实绝对路径。
  - 验收: `& "<absolute-python>" -m pytest --version` 可运行；`tests/test_excel_toolbox.py` 的真实测试命令可执行
    （迁移前可以失败，但失败原因不得再是找不到 python/pytest）。

- [x] **H1-final** Phase 3 最终验收项 — PowerShell pytest 寻址修复完成
  - 标记规则: 只有 Architect 在 Phase 3 复核到真实命令输出后，才可把本项改为 `[x]`。
  - 通过条件: pytest 由绝对 Python 路径启动，错误不再是 `python` / `pytest` 无法寻址或系统无法访问解释器。

- [x] **H2-a** Worker 实现迁移 — `_get_xlwings()` 与 `xlwings.App` 生命周期
  - 目标文件: `services/excel_toolbox.py`；如缺依赖，仅允许最小修改 `requirements.txt` 新增 `xlwings`。
  - 实现:
    - 移除 `import win32com.client` 路径与 `_get_win32com()`；
    - 新增 `_get_xlwings() -> Any`，延迟导入 `xlwings as xw`，保留 monkeypatch 能力；
    - 每个 merge/diff 方法使用 `xw.App(visible=False, add_book=False)`；
    - 初始化后设置 `app.api.DisplayAlerts = False`、`app.api.ScreenUpdating = False`、`app.api.EnableEvents = False`；
    - finally 中关闭本次打开/创建的 `Book` 并 `app.quit()`。
  - 约束: 不改变 `ExcelToolbox` 公共签名；不把 UI 提示写进 service；不输出单元格内容到日志。
  - 验收: 静态 grep 不再命中 `_get_win32com`、`Dispatch("Excel.Application")`、`excel.Workbooks`。

- [x] **H2-b** Worker 实现迁移 — Range / UsedRange / SaveAs 语义替换
  - 目标文件: `services/excel_toolbox.py`
  - 替换要求:
    - `Workbooks.Add/Open` → `app.books.add()` / `app.books.open(...)`；
    - `Sheets(1)` / `ActiveSheet` → `book.sheets[0]` / `book.sheets.active`；
    - `UsedRange.Rows/Columns.Count` → `sheet.api.UsedRange.Rows.Count` / `.Columns.Count`；
    - `Cells(r, c).Value` → `sheet.range((r, c)).value`；
    - `Cells(r, c).Formula` → `sheet.range((r, c)).formula`；
    - `Interior.Color` → `sheet.range((r, c)).api.Interior.Color`；
    - `SaveAs(..., FileFormat=51)` → `book.api.SaveAs(..., FileFormat=51)`。
  - 约束: 备份、回滚、文件锁预检、莫兰迪色、防撞色、图例 Sheet、baseline 差异语义必须保持。
  - 验收: 三个公开方法 `merge_append` / `merge_overlay` / `diff_against_baseline` 均使用 xlwings API 完成同等语义。

- [x] **H2-c** Worker 测试迁移 — `tests/test_excel_toolbox.py` 改为 mock xlwings
  - 目标文件: `tests/test_excel_toolbox.py`
  - 实现: monkeypatch `services.excel_toolbox._get_xlwings`，提供假 `xw.App`、`App.books`、`Book`、`Sheet`、
    `Range` 与 `.api` 对象。
  - 断言:
    - `App` 构造参数包含 `visible=False`、`add_book=False`；
    - `app.api.DisplayAlerts`、`ScreenUpdating`、`EnableEvents` 被置为 `False`；
    - `book.api.SaveAs(..., FileFormat=51)` 被调用；
    - `sheet.range((row, col)).value` / `.formula` / `.api.Interior.Color` 替代原 `Cells` 语义；
    - 异常路径仍 `_rollback` 并 `app.quit()`；
    - 无真实 Excel 进程启动。
  - 约束: 测试不得继续以 `wc.Dispatch("Excel.Application")` 作为主 mock。
  - 验收: `& "<absolute-python>" -m pytest tests/test_excel_toolbox.py -q` 可真实执行。

- [x] **H2-final** Phase 3 最终验收项 — ExcelToolbox xlwings 迁移完成
  - 标记规则: 只有 Architect 在 Phase 3 看到静态审查通过且真实 pytest 全绿后，才可把本项改为 `[x]`。
  - 通过条件: `tests/test_excel_toolbox.py` 全绿；`services/excel_toolbox.py` 无 `win32com` 物理入口；
    Excel 保存仍通过 `book.api.SaveAs(..., FileFormat=51)`。

- [x] **H3-a** Architect 静态审查门 — xlwings 语法与禁用路径
  - 检查范围: `services/excel_toolbox.py`、`tests/test_excel_toolbox.py`、`requirements.txt`。
  - 建议命令:
    ```powershell
    rg -n "win32com|_get_win32com|Dispatch\\(\"Excel\\.Application\"\\)|\\.Workbooks|\\.Cells\\(" services/excel_toolbox.py tests/test_excel_toolbox.py
    rg -n "xlwings|_get_xlwings|xw\\.App|app\\.books|\\.range\\(\\(|\\.api\\.SaveAs|\\.api\\.Interior\\.Color|\\.api\\.UsedRange" services/excel_toolbox.py tests/test_excel_toolbox.py requirements.txt
    rg -n "pandas|openpyxl|DataFrame\\.to_excel|Workbook\\.save" services/excel_toolbox.py tests/test_excel_toolbox.py requirements.txt
    ```
  - 判定:
    - 第一条命令不得命中 ExcelToolbox 的 win32com 物理入口；
    - 第二条命令必须显示 xlwings 主路径；
    - 第三条命令不得显示 Excel I/O 直写实现。
  - 失败处理: 任何一条不满足，Architect 打回 Worker，不得标记 H1/H2/H3 final。

- [x] **H3-b** Architect 动态审查门 — 抓取真实 pytest 报告
  - 前置: H1 已给出可执行绝对路径 pytest 命令。
  - 必跑命令:
    ```powershell
    & "<absolute-python>" -m pytest tests/test_excel_toolbox.py -q
    ```
  - 报告要求: Architect 在审查记录或交付说明中贴出命令、退出码、通过/失败数量、首个失败摘要。
  - 失败处理: pytest 未全绿、命令无法执行、或仍然是解释器/pytest 寻址问题，均打回 Worker。

- [x] **H3-final** Phase 3 最终验收项 — Architect 守门通过并回填状态
  - 标记规则: 只有 H3-a 静态审查通过，且 H3-b 真实 pytest 全绿，才可把 `H1-final`、`H2-final`、
    `H3-final` 三项同时改为 `[x]`。
  - 通过后状态: 本轮 Excel 物理基座迁移完成；若失败，保持未勾选并在 Worker 下一步中列明返工项。
  - Phase 3 Final Review 真实输出摘要（2026-06-20）:
    - smoke: `& "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -c "import services.excel_toolbox as m; xw=m._get_xlwings(); print(xw.__version__)"` -> `0.36.6`
    - pytest: `& "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pytest tests/test_excel_toolbox.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider` -> `17 passed in 0.60s`

---

### I. P1 内网爬虫 Worker 组 — Aras HAR 契约落地（EWO / NCR）

> **目标**: 按 `docs/agents/crawler_contract.md` 落地 P1 HTTP/AML 爬虫，不再依赖真实浏览器选择器作为核心数据通路。
> **硬约束**: Worker 不得访问真实内网或外网；测试必须 mock HTTP；不得硬编码 Cookie、Authorization、api_key、token 或样本真实下载令牌。
> **推荐文件边界**: 新增 `services/aras_crawler.py`、`tests/fixtures/crawler/*`、`tests/test_aras_crawler.py`；必要时最小更新 `requirements.txt`。不要修改 `docs/agents/*`。

- [x] **I1** Worker 源码骨架 — `services/aras_crawler.py::ArasCrawlerClient`
  - 目标文件: `services/aras_crawler.py`（建议新增；若复用 `services/intranet_scraper.py`，必须保持 Selenium 手动登录职责不被扩大）
  - 实现:
    - 定义 `ArasCrawlerClient.__init__(base_url, session=None, headers=None, cookies=None, timeout=30.0)`。
    - 定义 DTO/dataclass: `EWOReportFilters`、`NCRApprovalFilters`、`EWOReportPage`、`NCRExportResult`、`NCRDetailExportResult`。
    - 合并通用 SOAP headers 与调用方注入 headers/cookies；调用方 headers 优先。
  - 约束: service 层不得 import `rich` / `flask`；不得在模块内写真实 cookie/token/auth；不得自动下载 vault 文件。
  - 验收: `python -m pytest tests/test_aras_crawler.py -q` 中 mock session 可实例化并验证 headers/cookies 注入。

- [x] **I2** Worker XML builder — EWO 查询请求
  - 目标函数: `ArasCrawlerClient.query_ewo_report()` 或其私有 builder。
  - 实现:
    - 路由 `POST /innovatorserver/Server/InnovatorServer.aspx`，`SOAPAction=ApplyItem`。
    - 构造 `Item type="EWO_O" action="get" page="<page>" pagesize="<page_size>" maxRecords="<max_records>" returnMode="itemsOnly"`。
    - 默认 `select` 字段完全按 `docs/agents/crawler_contract.md`；根据 `EWOReportFilters` 追加 AML 子节点条件。
  - 验收: 测试断言 method、route、SOAPAction、分页属性、`select`、关键 filter 节点名，不做真实 HTTP。

- [x] **I3** Worker XML builder — NCR 进度与明细请求
  - 目标函数: `query_ncr_approval_progress()`、`extract_ncr_approval_detail()` 或共享私有 builder。
  - 实现:
    - 进度: `Method action="sgmw_downloadFileProgressC"`。
    - 明细: `Method action="sgmw_downloadFileDetail4C"`。
    - 共同筛选节点: `buystart`、`buyend`、`pestart`、`peend`、`ncrno`、`ncrname`、`seccode`、`changetype`、`othercondition`。
    - `project_names` 以逗号连接写入 `ncrname` CDATA；`othercondition` 默认 `"0"`。
  - 验收: 测试断言两个方法仅 action 不同，payload 节点与 CDATA 内容符合 HAR 契约。

- [x] **I4** Worker parser — HAR 响应 XML/JSON 解析
  - 目标函数: EWO/NCR 响应解析函数，可为私有函数或模块级 helper。
  - 实现:
    - EWO: 解析 `Envelope/Body/Result/Item type="EWO_O"` 为 rows，并保留 `id`、`page`、raw XML。
    - NCR 进度: 解析 `sgmw_outputFileRecord` 的 `_file` 文本为 `file_id`，`_file@keyed_name` 为 `file_name`。
    - NCR 明细: 解析 `Envelope/Body/Result` 文本为 `file_name`。
    - 下载 token: 解析 JSON `{"d":"<download_token>"}`，但不得记录真实 token。
  - 验收: parser 测试从 fixture 读取响应并断言结构化结果；空/异常响应抛领域异常。

- [x] **I5** Worker fixtures — 从 HAR response.content 萃取离线样本
  - 目标文件:
    - `tests/fixtures/crawler/ewo_query_response.xml`
    - `tests/fixtures/crawler/ncr_project_lookup_response.xml`
    - `tests/fixtures/crawler/ncr_progress_response.xml`
    - `tests/fixtures/crawler/ncr_detail_response.xml`
    - `tests/fixtures/crawler/download_token_response.json`
  - 实现: 前四个 fixture 可来自 HAR `response.content.text` 原样内容；token fixture 必须替换为 `<download_token>` 或假 token。
  - 约束: fixture 不得包含真实 Cookie、Authorization、Set-Cookie、session、CSRF、download token。
  - 验收: `rg -n "Cookie|Authorization|Set-Cookie|csrf|session|token=" tests/fixtures/crawler` 不得命中真实敏感值；允许命中 `<download_token>`。

- [x] **I6** Worker mock 测试 — 禁止真实 HTTP
  - 目标文件: `tests/test_aras_crawler.py`
  - 实现:
    - Fake `requests.Session`，记录 `post/head/get` 参数并返回 fixture 文本。
    - 覆盖 EWO 查询、NCR 进度、NCR 明细、下载 token JSON 解析。
    - 覆盖 caller-supplied `headers` / `cookies` 注入与覆盖策略。
    - monkeypatch `requests.sessions.Session.request` 或直接断言 fake session，确保测试不会落到真实网络。
  - 验收命令:
    ```powershell
    & "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pytest tests/test_aras_crawler.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider
    ```

- [x] **I7** Worker 安全静态检查 — 凭据与真实 HTTP 防线
  - 检查范围: `services/aras_crawler.py`、`tests/test_aras_crawler.py`、`tests/fixtures/crawler/*`。
  - 建议命令:
    ```powershell
    rg -n "ecm\\.sgmw\\.com\\.cn|requests\\.(get|post|head|request)\\(|Cookie|Authorization|Set-Cookie|csrf|session|token=" services/aras_crawler.py tests/test_aras_crawler.py tests/fixtures/crawler
    ```
  - 判定:
    - 允许契约测试断言路径字符串或 base_url 测试值；不得出现真实 token/cookie/auth 值。
    - `requests.Session` 只能通过注入或创建后由测试 fake；不得在单元测试中发真实请求。

- [x] **I8** Reviewer 验收项 — P1 契约一致性审查
  - 审查文件: `docs/agents/crawler_contract.md`、`services/aras_crawler.py`、`tests/test_aras_crawler.py`、`tests/fixtures/crawler/*`。
  - 验收:
    - 三条能力的 route、method、SOAPAction、payload 节点、响应解析与合同一致。
    - Cookie/auth/token 全部外部注入或运行时返回，未硬编码。
    - 离线 pytest 全绿，且无真实 HTTP。
    - 若 Worker 修改了 `services/intranet_scraper.py`，Reviewer 需确认未破坏现有 Selenium 手动登录流。

- [x] **I9-final** Phase 4 最终验收项 — Aras HAR 契约落地完成
  - 标记规则: 只有 Architect 在 Phase 4 复核到目标解释器 smoke、生产 session smoke、import/class smoke、专项 pytest 真实输出后，才可把本项改为 `[x]`。
  - 通过条件: `requests` 在目标解释器可 import；`ArasCrawlerClient` 默认生产 session 可实例化；三条能力与 HAR 契约一致；fixture 无真实 Cookie/token/auth；测试不发真实 HTTP。
  - Phase 4 Final Review 真实输出摘要（2026-06-20）:
    - requests smoke: `2.34.2`
    - production session smoke: `Session`
    - import/class smoke: `ArasCrawlerClient`
    - pytest: `7 passed in 0.57s`

---

### J. P1 双轨接入 Worker 组 — CLI 终端适配 + WEB 可视化适配

> **目标**: 在不修改 `services/aras_crawler.py` 的前提下，把已验收的 Aras service 接入 CLI 与 WEB 两条界面轨道。
> **权威设计**: `docs/agents/implementation_plan.md` §2.11、§3.8、§4.3。
> **允许修改**: `main.py`、`web/app.py`、`web/templates/dashboard.html`、`web/static/app.js`、
> `web/static/style.css`、新增 `tests/test_aras_cli_web.py` 或同等聚焦测试。
> **禁止修改**: `services/aras_crawler.py`；除非 Architect 另行打回并新增专门修复任务。
> **安全硬约束**: 不持久化 Cookie/token/Authorization/api_key/secret；不写日志、不进 URL、不进 localStorage/sessionStorage；
> Web API 不默认调用真实内网，必须由用户显式提交 `base_url` 与 Cookie/header；测试必须 mock。

- [x] **J1** Worker CLI 入口解锁 — `main.py::DEFERRED` / `show_menu()` / `handle_intranet_scrape()`
  - 目标文件: `main.py`
  - 实现:
    - 从 `DEFERRED` 中移除 P1 菜单键 `"4"`，保留 P3/P4 暂缓。
    - `show_menu()` 中 P1 显示为可选普通菜单，不再标注“暂缓”。
    - `handle_intranet_scrape(db)` 移除 P1 短路 return，改为进入 Aras 爬虫二级菜单。
    - 引入 `ArasCrawlerClient`、`EWOReportFilters`、`NCRApprovalFilters`、`ArasCrawlerError`，仅在 CLI 适配层使用。
  - 约束: 不删除旧 `IntranetScraper` import 和历史代码，除非 Worker 同时证明没有破坏旧调用；本任务不得写任何 service 业务逻辑。
  - 验收: `python main.py` 菜单中 P1 可进入二级菜单；P3/P4 仍 dim/暂缓。

- [x] **J2** Worker CLI 表单采集 helpers — `main.py` Aras 输入解析
  - 目标文件: `main.py`
  - 建议新增函数:
    - `_ask_aras_connection() -> tuple[str, dict[str, str], dict[str, str] | None]`
    - `_ask_ewo_filters() -> tuple[EWOReportFilters, int, int, int]`
    - `_ask_ncr_filters() -> NCRApprovalFilters`
    - `_parse_header_lines(raw: str) -> dict[str, str]`
  - 实现:
    - `base_url` 必填；为空时提示并返回二级菜单。
    - Cookie 用 `Prompt.ask(..., password=True)` 或等效隐藏输入采集；作为 `headers["Cookie"]` 透传或结构化 cookies 透传。
    - 额外 headers 支持 `Key: Value` 多行/逗号分隔；跳过空行；拒绝无冒号格式并给 rich 提示。
    - EWO/NCR 过滤项与 `implementation_plan.md` §2.11 完全对齐；空输入转换为 `None` 或默认值。
  - 约束: 不把输入值写入 logger；不把 Cookie/token 回显到终端。
  - 验收: helper 可由测试 monkeypatch `Prompt.ask` 覆盖；敏感字段不会出现在 captured stdout。

- [x] **J3** Worker CLI 执行与 rich 渲染 — `main.py::handle_intranet_scrape()`
  - 目标文件: `main.py`
  - 实现:
    - 二级菜单提供 `EWO 报表查询`、`NCR 审批进度导出`、`NCR 审批明细提取`、`返回`。
    - EWO 调用 `client.query_ewo_report(filters, page, page_size, max_records)`，用 `rich.table.Table` 渲染 rows；
      同时显示 `page`、`count`、`item_ids` 数量。
    - NCR 进度调用 `client.query_ncr_approval_progress(filters)`，渲染 `file_name`、`file_id`、`record_id`；
      不默认调用 `get_file_download_token()`。
    - NCR 明细调用 `client.extract_ncr_approval_detail(filters)`，渲染 `file_name`。
    - 捕获 `ArasCrawlerError`、HTTP 异常、通用异常，输出脱敏错误摘要。
  - 约束: 不打印 `raw_xml`、Cookie、Authorization、token、完整 headers；不访问真实下载 URL。
  - 验收: 通过 fake client 测试三类分支的调用参数和 rich 输出结构。

- [x] **J4** Worker Web API 基础 helpers — `web/app.py`
  - 目标文件: `web/app.py`
  - 建议新增函数:
    - `_json_error(error_type: str, message: str, status: int)`
    - `_redact_error_message(exc: Exception) -> str`
    - `_build_aras_client_from_payload(payload: dict[str, Any]) -> ArasCrawlerClient`
    - `_payload_headers(payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, str] | None]`
  - 实现:
    - 校验 JSON object；`base_url` 缺失返回 `400`。
    - `headers` 只接收字符串键值；`cookie` 字符串写入 `headers["Cookie"]`；`cookies` mapping 可选。
    - 每次请求即时构造 `ArasCrawlerClient`；不使用 Flask session/server cache 保存凭据。
    - 错误响应统一为 `{"ok": false, "error": {"type": "...", "message": "..."}}`。
  - 约束: logger 不记录 payload、headers、cookie；错误 message 必须脱敏。
  - 验收: Flask test client 覆盖无 `base_url`、非法 headers、cookie 透传、错误脱敏。

- [x] **J5** Worker Web API 路由 — `web/app.py`
  - 目标文件: `web/app.py`
  - 实现路由:
    - `POST /api/aras/ewo/query` → `ArasCrawlerClient.query_ewo_report()`，返回 `rows`、`page`、`item_ids`、`count`。
    - `POST /api/aras/ncr/progress` → `query_ncr_approval_progress()`，返回 `file_id`、`file_name`、`record_id`。
    - `POST /api/aras/ncr/detail` → `extract_ncr_approval_detail()`，返回 `file_name`。
  - 状态码:
    - 参数错误 `400`；
    - `ArasCrawlerError` 或 HTTP 上游错误 `502`；
    - 未预期异常 `500`。
  - 约束: 全部使用 `POST`；不得通过 query string 接收 Cookie/token；不得返回 `raw_xml`。
  - 验收: `tests/test_aras_cli_web.py` 使用 monkeypatch fake client，断言 JSON 契约和状态码。

- [x] **J6** Worker Dashboard HTML 面板解锁 — `web/templates/dashboard.html`
  - 目标文件: `web/templates/dashboard.html`
  - 实现:
    - 将“内网爬虫（暂缓）”导航改为可用 P1 面板入口；P3/P4 仍 disabled。
    - 新增 P1 Aras 面板：连接信息、隐藏 Cookie 输入、headers 输入、查询类型切换、EWO filters、
      NCR filters、执行按钮、loading/error 区、结果容器。
    - 不在 HTML 中放任何真实 `base_url`、Cookie、Authorization、token 默认值。
  - 约束: 表单文案只描述字段本身，不展示敏感示例值；不引入前端框架。
  - 验收: 页面可无 JS 错误加载；P1 面板 DOM id/class 与 J7 约定一致。

- [x] **J7** Worker Dashboard JS 异步渲染队列 — `web/static/app.js`
  - 目标文件: `web/static/app.js`
  - 实现:
    - 采集 P1 表单并组装 POST JSON；按查询类型调用 `/api/aras/ewo/query`、
      `/api/aras/ncr/progress`、`/api/aras/ncr/detail`。
    - 实现 request 序号或 running/queued 状态，避免慢响应覆盖新结果；请求中禁用执行按钮并显示 loading。
    - EWO rows 渲染为表格；NCR progress/detail 渲染为摘要行；错误渲染为脱敏提示。
    - 请求完成后清理内存中的敏感临时变量引用；不得写 localStorage/sessionStorage/URL/console。
  - 约束: 原 `/api/overview` 概览渲染保持可用；不引入构建链。
  - 验收: 前端单元可通过 DOM smoke 或人工浏览验证；代码 grep 不出现 `localStorage`/`sessionStorage` 保存凭据。

- [x] **J8** Worker Dashboard 样式 — `web/static/style.css`
  - 目标文件: `web/static/style.css`
  - 实现:
    - 为 P1 表单、tabs/segmented control、结果表格、loading/error、disabled/running 状态补齐样式。
    - EWO 大表支持横向滚动；移动端不溢出视口。
  - 约束: 不改变现有 P2 overview 的基本布局；不把页面改成单一营销页。
  - 验收: dashboard 首屏和 P1 面板在桌面宽度下无明显重叠，P2 概览仍正常显示。

- [x] **J9** Worker CLI/Web 测试 — 新增 `tests/test_aras_cli_web.py`
  - 目标文件: `tests/test_aras_cli_web.py`
  - 实现:
    - main.py helper 测试：headers 解析、空值过滤、Cookie 不回显、DTO 构造。
    - Flask API 测试：fake `ArasCrawlerClient` 覆盖 EWO/NCR 三条路由，断言请求/响应 JSON。
    - 错误路径测试：无 `base_url` 为 `400`；fake service 抛 `ArasCrawlerError` 为 `502`；异常信息脱敏。
  - 约束: 不访问真实内网/外网；不得要求真实 Cookie/token fixture。
  - 验收命令:
    ```powershell
    & "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pytest tests/test_aras_cli_web.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider
    ```

- [x] **J10** Worker 安全静态检查 — 凭据、防反向污染与真实 HTTP 防线
  - 检查范围: `main.py`、`web/app.py`、`web/templates/dashboard.html`、`web/static/app.js`、
    `web/static/style.css`、`tests/test_aras_cli_web.py`、`services/aras_crawler.py`。
  - 建议命令:
    ```powershell
    rg -n "localStorage|sessionStorage|console\\.log\\(|Cookie|Authorization|api_key|token|secret" main.py web tests/test_aras_cli_web.py
    rg -n "rich|flask|render_template|jsonify|document\\.|window\\." services/aras_crawler.py
    rg -n "requests\\.(get|post|head|request)\\(" tests/test_aras_cli_web.py
    ```
  - 判定:
    - 第一条允许字段名/占位名命中，但不得出现真实敏感值或持久化逻辑。
    - 第二条不得命中，确保 service 不被 CLI/Web 反向污染。
    - 第三条不得命中真实 HTTP 直接调用。
  - 验收: Worker 交付说明贴出命令、退出码和命中解释。

- [x] **J11** Reviewer 验收项 — P1 双轨接入契约审查
  - 审查文件: `implementation_plan.md` §2.11、`main.py`、`web/app.py`、`web/templates/dashboard.html`、
    `web/static/app.js`、`web/static/style.css`、`tests/test_aras_cli_web.py`、`services/aras_crawler.py`。
  - 验收:
    - CLI P1 已解锁，P3/P4 仍暂缓；CLI 只做 rich 表单和渲染，不写爬虫业务。
    - Web 三条 POST API 契约、状态码、脱敏错误响应与 §2.11 一致。
    - dashboard P1 面板可操作，overview 仍可用，前端不持久化凭据。
    - `services/aras_crawler.py` 未被修改或未引入 rich/flask/DOM/web 依赖。
    - 专项 pytest 与安全静态检查通过；无真实 HTTP。

- [x] **J-final** Phase 3 最终验收项 — P1 CLI/Web 双轨注入返工签批完成
  - 最终复核日期: 2026-06-20
  - 最终复核输出:
    - pytest: `12 passed in 0.59s`
    - py_compile: `main.py`、`web/app.py` 通过，无输出
  - 签批结论: P1 CLI/Web 双轨注入返工通过最终复审，允许进入签批状态。

---

### K. PAA 全量抓取 Worker 组 — SOAP/AML 分页直连

> **目标**: 基于 Phase 1 PAA HAR 快照，实现 `PAA_O` 表单全量抓取能力。必须直连
> `/innovatorserver/Server/InnovatorServer.aspx` SOAP/AML，不走前端全量导出、不模拟浏览器点击。
> **权威设计**: `docs/agents/implementation_plan.md` §2.12、§3.4.1；证据源为
> `docs/agents/paa_har_snapshot.md`、`crawl source/ecm.sgmw.com.cn-PAA.har`、`crawl source/ecm.sgmw.com.cn-PAA1.har`。
> **允许修改**: 优先扩展 `services/aras_crawler.py`；新增
> `tests/fixtures/crawler/paa_*.xml`、`tests/test_aras_paa_crawler.py`，或最小扩展现有
> `tests/test_aras_crawler.py`。
> **禁止修改**: `main.py`、`web/*`、数据库 schema、Excel/Feishu/Office 相关代码、`docs/agents/*`。
> **安全硬约束**: Worker 不得访问真实内网/外网；测试必须 mock HTTP；不得硬编码 Cookie、
> Authorization、api_key、token、session、csrf 或任何真实凭据。

- [x] **K1** Worker PAA 契约常量与 DTO — `services/aras_crawler.py`
  - 目标文件: `services/aras_crawler.py`
  - 实现:
    - 新增 `DEFAULT_PAA_SELECT_FIELDS`，字段顺序必须按 `implementation_plan.md` §2.12 的 HAR-proven select。
    - 新增 `PAAReportFilters`，默认全空；筛选项仅按 AML 惯例推断：`paa_no`、`ewo_no`、`state`、`area`、
      `base`、`vehicle_keyword`、`submit_start`、`submit_end`、`mtl_rq_start`、`mtl_rq_end`。
    - 新增 `PAAReportPage(rows, page, item_ids, raw_xml)`，形态与 `EWOReportPage` 对齐。
  - 约束: 不引入 `rich` / `flask` / CLI/Web 依赖；不写真实 host、Cookie、Authorization、token。
  - 验收: import smoke 可导入新 DTO/常量；静态 grep 不出现真实凭据。

- [x] **K2** Worker XML builder — `Item type="PAA_O" action="get"`
  - 目标函数: `query_paa_report()` 或私有 `_build_paa_payload()`。
  - 实现:
    - 路由复用 `SOAP_ROUTE`：`POST /innovatorserver/Server/InnovatorServer.aspx`。
    - `SOAPAction` 固定为 `ApplyItem`。
    - 构造 `Item type="PAA_O" action="get" page="<page>" pagesize="<page_size>" maxRecords="<max_records>" returnMode="itemsOnly"`。
    - 默认 `select` 使用 `DEFAULT_PAA_SELECT_FIELDS`；调用方可覆盖 `select_fields`。
    - 空 `PAAReportFilters` 必须生成无子节点的 `<Item ... />` 或等价空 body。
    - 非空 filter 按 §2.12 生成 AML 子节点，`area/base/vehicle_keyword` 使用 `condition="like"`，
      日期范围使用 `condition="ge"` / `condition="le"`。
  - 验收: 测试断言 method、route、SOAPAction、分页属性、returnMode、select、空 filter、推断 filter 节点。

- [x] **K3** Worker XML parser — PAA SOAP 响应解析
  - 目标函数: `parse_paa_report_response(xml_text: str) -> PAAReportPage`。
  - 实现:
    - 必须使用 `xml.etree.ElementTree` 或等效 XML parser 解析 `Envelope/Body/Result/Item type="PAA_O"`。
    - 输出 `rows: list[dict[str, str | None]]`；子节点 `is_null="1"` 转为 `None`。
    - 保留 `Item@id` 到 `item_ids`；优先从 `Item@page` 得到 `page`；保留 `raw_xml`。
    - 空 XML、非法 XML、无可用 Result 时抛 `ArasCrawlerError` 或既有领域异常。
  - 约束: 严禁把响应按 JSON dict 解析；严禁以字符串 split/正则作为主 parser。
  - 验收: fixture parser 测试覆盖正常页、空页、短页、非法 XML。

- [x] **K4** Worker 全量分页循环 — `crawl_paa_report_all()`
  - 目标函数: `ArasCrawlerClient.crawl_paa_report_all()`。
  - 实现:
    - 从 `page=1` 开始 while 循环，逐页调用 `query_paa_report()`。
    - 每轮动态递增 `page`，不得重复请求第一页。
    - 当前页 `rows` 为空时终止；`len(rows) < page_size` 时也安全终止。
    - 必须提供并执行 `max_pages`、`max_records` 熔断，防止死循环；达到 `max_records` 时截断或停止。
    - 可选按 `Item@id` / child `<id>` / `keyed_name` 去重，但去重不得替代熔断。
  - 验收: fake session 测试覆盖多页拼接、空页终止、短页终止、`max_pages` 熔断、`max_records` 熔断。

- [x] **K5** Worker PAA fixtures — 从 HAR response.content 萃取离线 XML
  - 目标文件:
    - `tests/fixtures/crawler/paa_query_response.xml`
    - `tests/fixtures/crawler/paa_empty_response.xml`
    - `tests/fixtures/crawler/paa_short_page_response.xml`
  - 实现:
    - 从 `ecm.sgmw.com.cn-PAA.har` 的 `response.content.text` 萃取 SOAP/Result/Item 结构与字段名。
    - 因 HAR 长文本存在潜在未转义 XML 片段风险，fixture 必须整理成可被 XML parser 解析的最小代表性样本。
    - 业务文本、人员、电话、真实 id 等可用 `<sample>` / `PAA000001` / `ID_PLACEHOLDER` 等假值替换。
  - 约束: fixture 不得包含真实 Cookie、Authorization、Set-Cookie、token、session、csrf。
  - 验收: `rg -n "Cookie|Authorization|Set-Cookie|csrf|session|token=" tests/fixtures/crawler/paa_*.xml`
    不得命中真实敏感值。

- [x] **K6** Worker PAA mock 测试 — 禁止真实 HTTP
  - 目标文件: `tests/test_aras_paa_crawler.py`，或最小扩展 `tests/test_aras_crawler.py`。
  - 实现:
    - Fake `requests.Session`，记录 `post` 参数并返回 PAA fixture 文本。
    - 覆盖 `query_paa_report()` builder + parser 端到端。
    - 覆盖 caller-supplied `headers` / `cookies` 注入与 `SOAPAction=ApplyItem` 覆盖策略。
    - monkeypatch 或 fake 掉真实 network path，确保测试不会落到真实 HTTP。
  - 验收命令:
    ```powershell
    & "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pytest tests/test_aras_paa_crawler.py -q --basetemp E:\project\vse-toolbox\.tmp_pytest -p no:cacheprovider
    ```

- [x] **K7** Worker 安全静态检查 — PAA 凭据与边界
  - 检查范围: `services/aras_crawler.py`、`tests/test_aras_paa_crawler.py`、`tests/fixtures/crawler/paa_*.xml`。
  - 建议命令:
    ```powershell
    rg -n "ecm\\.sgmw\\.com\\.cn|requests\\.(get|post|head|request)\\(|Cookie|Authorization|Set-Cookie|csrf|session|token=" services/aras_crawler.py tests/test_aras_paa_crawler.py tests/fixtures/crawler/paa_*.xml
    rg -n "rich|flask|render_template|jsonify|document\\.|window\\." services/aras_crawler.py
    ```
  - 判定:
    - 允许测试使用假 `base_url`、字段名和占位符；不得出现真实敏感值。
    - `services/aras_crawler.py` 不得出现 CLI/Web 反向依赖。
    - 单元测试不得发真实 HTTP。

- [x] **K8** Reviewer 验收项 — PAA 契约一致性审查
  - 审查文件: `docs/agents/implementation_plan.md` §2.12、`services/aras_crawler.py`、
    `tests/test_aras_paa_crawler.py` 或扩展后的 `tests/test_aras_crawler.py`、`tests/fixtures/crawler/paa_*.xml`。
  - 验收:
    - PAA route、method、SOAPAction、`Item type="PAA_O" action="get"`、分页属性、select 字段与 HAR 摘要一致。
    - parser 使用 XML parser，未按 JSON dict 解析 SOAP 响应。
    - 全量方法从 page 1 开始动态递增，空页/短页终止，`max_pages`/`max_records` 熔断可测。
    - Cookie/auth/token 全部外部注入，源码和 fixture 未硬编码真实值。
    - 未修改 CLI/Web；离线 pytest 全绿；无真实 HTTP。

- [x] **K-final** Phase 4 最终验收项 — PAA 表单全量抓取核心签批完成
  - 最终复核日期: 2026-06-21
  - 最终复核输出:
    - pytest: `16 passed in 0.55s`
    - py_compile: `services/aras_crawler.py` 通过，无输出
  - 签批结论: PAA 表单全量抓取核心落地通过最终复审，允许进入签批状态。

---

## 🗂️ 后续 Sprint / Backlog（本轮**不实现**，仅登记）

> Architect 决策: 以下为非阻塞存量缺陷 / 演进项，登记待后续 Sprint 排期。

- [ ] **P1** 内网爬虫真实页面选择器（`_scrape_data` / `_save_to_database`）。
- [ ] **P3** 周报 PPT：本轮仅在 CLI/WEB 代码层预留入口，真实模板接入后开发。
- [ ] **P4** 飞书助手：本轮仅代码层预留入口，待需求明确后开发。
- [ ] **P5** Office I/O 适配层调研：仅当出现“脱离本机 Office / 服务端批处理 / Linux 运行 /
  多引擎切换”明确目标时启动；Excel 第一实现以 H 段 `xlwings` 基座为准，并证明不破坏 DLP 原生保存路径。

---

## 历史迭代

### Sprint 1 — 基础设施（已完成）

- [x] `core/db_manager.py` 1.1–1.6（连接管理 / 建表 / WAL / 表工具）
- [x] `services/office_toolbox.py` 2.1–2.6（COM 版 Excel/PPT 导出）
- [~] `services/feishu_imap.py` 3.1–3.4（骨架完成，imapclient 迁移移交 Backlog F1-c）
- [~] `services/intranet_scraper.py` 4.1–4.2（骨架完成，真实选择器移交 Backlog P1）
