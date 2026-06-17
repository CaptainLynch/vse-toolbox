# 📋 VSE TOOLBOX — 项目状态快照模板

> 本文件用于在多设备 / 多智能体协作场景下保持开发进度一致性。
> 每次提交前由 **role_reviewer** 或 **role_architect** 更新。

---

## 1. 项目基本信息

| 字段 | 值 |
|---|---|
| 项目名称 | VSE TOOLBOX (Dual-Interface Edition) |
| 架构 | 双轨界面（CLI + WEB）共享 service 层 + SQLite + Office COM 自动化 |
| 主要依赖 | rich, pywin32, imapclient, pytz, selenium, **flask** |
| 开发/审查工具 | pytest, flake8, mypy |
| Python 版本 | ≥ 3.9 |
| Office I/O 方式 | win32com.client (禁止 pandas/openpyxl/python-pptx，原因: DLP 透明加密) |
| Agent 模型策略 | 不指定 model（继承父模型 mimo-v2.5-pro），通过 prompt 层面推理约束控制深度 |

---

## 2. 命令树 / 目录结构（Sprint 2 目标态）

> 标注: `[新]` 本轮新建 · `[改]` 本轮修改 · 其余为存量保留。

```
VSE-TOOLBOX/
├── main.py                     # [改] CLI 适配层: 菜单 Callable 化 + Excel 子菜单 + 延期置灰
├── core/
│   ├── __init__.py
│   ├── config.py               # [新] 集中配置常量（路径/Flask/默认值，禁存明文密码）
│   └── db_manager.py           # [改] init_database 末尾插入「未归类」兜底项目
├── services/
│   ├── __init__.py
│   ├── excel_toolbox.py        # [新·P0] Excel 工具箱: 合并/比对/回滚 (win32com COM)
│   ├── vertical_forms.py       # [新·P0] EWO/NCR/DMU/Styling 四个空类占位
│   ├── office_toolbox.py       # Excel / PPT 生成 (win32com COM)
│   ├── intranet_scraper.py     # Selenium 内网爬虫（P1 暂缓·置灰）
│   └── feishu_imap.py          # IMAP 邮件解析 → SQLite（P4 暂缓·置灰）
├── web/                        # [新] WEB 适配层
│   ├── __init__.py             # [新]
│   ├── app.py                  # [新] Flask 应用 + GET /api/overview (P2 大屏)
│   ├── templates/
│   │   └── dashboard.html      # [新] P2 Demo 大屏骨架 + 导航（延期模块置灰）
│   └── static/
│       ├── style.css           # [新] 大屏样式
│       └── app.js              # [新] fetch /api/overview 渲染概览卡片
├── data/
│   ├── vse_toolbox.db          # SQLite 数据库文件（运行时生成）
│   ├── .backup/                # [新] Excel 改写前 .bak 备份（回滚用）
│   ├── templates/              # PPT / Excel 模板
│   └── output/                 # 生成的文件输出
├── tests/                      # [新]
│   ├── conftest.py             # [新] 临时 DatabaseManager(tmp_path) fixture
│   ├── test_db_manager.py      # [新] 兜底项目 + 建表幂等 + 回滚
│   └── test_excel_toolbox.py   # [新] mock COM，断言写入/备份/回滚/高亮/图例/Quit
├── docs/
│   └── agents/                 # 多智能体 Prompt & 流程文档
├── setup.cfg                   # flake8 / mypy 配置
├── requirements.txt            # [改] 新增 flask
└── README.md
```

---

## 3. 数据库表结构设计

### 3.1 `projects` — 项目主表

| 列名 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| name | TEXT NOT NULL | 项目名称 |
| manager | TEXT | 项目经理 |
| status | TEXT DEFAULT 'active' | active / archived |
| created_at | TEXT | ISO-8601 创建时间 |
| updated_at | TEXT | ISO-8601 更新时间 |

### 3.2 `deliverables` — 交付物明细表

| 列名 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| project_id | INTEGER FK → projects.id | 所属项目 |
| name | TEXT NOT NULL | 交付物名称 |
| owner | TEXT | 负责人 |
| due_date | TEXT | 截止日期 (YYYY-MM-DD) |
| status | TEXT DEFAULT 'pending' | pending / in_progress / done / blocked |
| remark | TEXT | 备注 |
| created_at | TEXT | ISO-8601 |
| updated_at | TEXT | ISO-8601 |

### 3.3 `feishu_tasks` — 飞书待办解析表

| 列名 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增主键 |
| title | TEXT | 任务标题 |
| assignee | TEXT | 指派人 |
| deadline | TEXT | 截止时间 |
| source_email_id | TEXT | 来源邮件 Message-ID |
| parsed_at | TEXT | 解析时间 |
| synced | INTEGER DEFAULT 0 | 是否已同步至 deliverables |

---

## 4. 模块开发进度

| 模块 | 状态 | 断点 / 备注 |
|---|---|---|
| main.py | 🟡 待 Worker 执行 | Sprint2: 菜单 Callable 化(A3) + Excel 子菜单(B8) + 延期置灰(D1) |
| core/config.py | 🟡 待 Worker 执行 | Sprint2 新增(A1): 集中配置常量，禁存明文密码 |
| core/db_manager.py | 🟡 待 Worker 执行 | Sprint2: init_database 末尾插入「未归类」兜底项目(A2) |
| services/excel_toolbox.py (P0) | 🟡 待 Worker 执行 | Sprint2 新增(B1-B6): 合并/比对/回滚/莫兰迪高亮，全 COM |
| services/vertical_forms.py (P0) | 🟡 待 Worker 执行 | Sprint2 新增(B7): 四个空类占位，仅 NotImplementedError |
| web/ (P2) | 🟡 待 Worker 执行 | Sprint2 新增(C1-C3): Flask + /api/overview + Demo 大屏骨架 |
| services/intranet_scraper.py (P1) | 🟡 暂缓·置灰 | 骨架完成，真实选择器移交 Backlog P1；本轮 CLI 置灰(D1) |
| services/feishu_imap.py (P4) | 🟡 暂缓·置灰 | 骨架完成，imapclient 迁移移交 Backlog F1-c；本轮 CLI 置灰(D1) |
| services/office_toolbox.py | 🟢 已完成 | COM 版 Excel/PPT 导出（excel_toolbox 复用其 COM 模式） |
| tests/ | 🟡 待 Worker 执行 | Sprint2 新增(E1-E3): conftest + db_manager + excel_toolbox(mock COM) |
| 多智能体文档 | 🟢 已完成 | 角色 Prompt + SOP 流程文档 |
| 流程控制文件 | 🟢 已完成 | task.md / implementation_plan.md（Sprint2 已更新） |
| 代码质量配置 | 🟢 已完成 | setup.cfg (flake8 + mypy) |

> 状态图例：⬜ 未开始 · 🟡 进行中 / 待 Worker 执行 · 🟢 已完成 · 🔴 阻塞

---

## 5. 当前断点 & 下一步

- **当前断点**: Sprint 2（双轨界面 + P0 Excel 工具箱）方案已获批并落地为架构文档，
  task.md 共 **17 项任务**（A1-A3 / B1-B8 / C1-C3 / D1 / E1-E3），等待 Worker 执行。
- **首批可立即开工（无前置，可并行 4 路）**: **A1**(config) · **A2**(db 兜底) · **A3**(菜单 Callable) · **B7**(vertical_forms 占位)。
- **解耦红线提醒**: `services/*` 与 `core/*` 禁止 import rich / flask；界面适配仅在 main.py 与 web/app.py。
- **下一步**:
  1. Worker 按「🔀 可并行分派矩阵」波次 W1→W5 推进；B 组(CLI/Excel) 与 C 组(WEB) 在 A1 后跨界面并行。
  2. P0 Excel 工具箱(B1-B8)全功能落地（合并/比对/回滚），仅 CLI 验收。
  3. P2 WEB 仅搭可运行 Demo 骨架(C1-C3) + 延期模块导航置灰。
  4. 补齐测试(E1-E3，mock COM)，`pytest + flake8 + mypy` 全绿后交 Reviewer。
  5. 真实 Windows + Office 环境运行 `python main.py` 与 `python -m web.app` 端到端验证。

---

## 6. Agent 模型策略变更记录

### 2026-06-15: reasoning_effort 实测结论

**测试结果**: 父模型 `mimo-v2.5-pro` 不支持任何显式 `reasoning_effort` 参数（low/medium/high/xhigh 全部返回 "not supported"）。`spawn_agent` 的 `model` 参数也无法覆盖为其他模型（gpt-5.4/5.5/5.3-codex/5.2 全部在运行时报错）。

**最终策略**: 不指定 model 和 reasoning_effort（继承父模型），改为在 `.codex.yaml` 的 system_prompt 中通过 `【推理约束】` 段落控制各角色的推理深度：

| 角色 | 推理深度 | prompt 约束方式 |
|---|---|---|
| Explorer | 低 | "简洁直接，禁止长篇分析，300 字内" |
| Architect | 高 | "每个决策列 2+ 备选方案，分析优缺点，给出理由" |
| Worker | 结构化 | "禁止发散，每次只做 task.md 一项，严格对齐签名" |
| Reviewer | 高 | "追踪每个 public 方法的全部异常路径，检查资源泄漏" |
