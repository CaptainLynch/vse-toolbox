# 📋 VSE TOOLBOX — 项目状态快照模板

> 本文件用于在多设备 / 多智能体协作场景下保持开发进度一致性。
> 每次提交前由 **role_reviewer** 或 **role_architect** 更新。

---

## 1. 项目基本信息

| 字段 | 值 |
|---|---|
| 项目名称 | VSE TOOLBOX (CLI Edition) |
| 架构 | 纯后端 CLI + SQLite + Office COM 自动化 |
| 主要依赖 | rich, pywin32, imapclient, pytz, selenium |
| 开发/审查工具 | pytest, flake8, mypy |
| Python 版本 | ≥ 3.9 |
| Office I/O 方式 | win32com.client (禁止 pandas/openpyxl/python-pptx，原因: DLP 透明加密) |
| Agent 模型策略 | 不指定 model（继承父模型 mimo-v2.5-pro），通过 prompt 层面推理约束控制深度 |

---

## 2. CLI 命令树（当前版本）

```
VSE-TOOLBOX/
├── main.py                     # CLI 主入口 & 菜单循环
├── core/
│   ├── __init__.py
│   └── db_manager.py           # SQLite 连接池 & ORM 建表
├── services/
│   ├── __init__.py
│   ├── intranet_scraper.py     # Selenium 内网爬虫
│   ├── feishu_imap.py          # IMAP 邮件解析 → SQLite
│   └── office_toolbox.py       # Excel / PPT 生成 (win32com COM)
├── data/
│   ├── vse_toolbox.db          # SQLite 数据库文件（运行时生成）
│   ├── templates/              # PPT / Excel 模板
│   └── output/                 # 生成的文件输出
├── docs/
│   └── agents/                 # 多智能体 Prompt & 流程文档
├── setup.cfg                   # flake8 / mypy 配置
├── requirements.txt
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
| main.py | 🟢 已完成 | CLI 菜单循环骨架，6 个数字选项路由 |
| core/db_manager.py | 🟢 已完成 | SQLite WAL 模式，contextmanager 连接管理，3 张表 DDL |
| services/intranet_scraper.py | 🟡 骨架完成 | Selenium WebDriver，待补充实际页面解析逻辑 (TODO) |
| services/feishu_imap.py | 🟡 骨架完成 | IMAP 连接 + 飞书邮件识别 + 正则解析，待改用 imapclient |
| services/office_toolbox.py | 🟢 已完成 | 已重写为 win32com COM 自动化（Excel.Application / PowerPoint.Application） |
| 多智能体文档 | 🟢 已完成 | 5 个角色 Prompt + 1 个 SOP 流程文档 |
| 流程控制文件 | 🟢 已完成 | task.md / implementation_plan.md / review_feedback.md / research_notes.md |
| 代码质量配置 | 🟢 已完成 | setup.cfg (flake8 + mypy) |

> 状态图例：⬜ 未开始 · 🟡 进行中 · 🟢 已完成 · 🔴 阻塞

---

## 5. 当前断点 & 下一步

- **当前断点**: 所有基础设施就绪，10 项待办任务等待 Worker 执行
- **下一步**:
  1. Worker 按 task.md 逐项执行：feishu_imap.py 改用 imapclient (任务 3.1-3.4)
  2. Worker 补充 intranet_scraper.py 实际选择器 (任务 4.1-4.2)
  3. Architect 设计测试用例，Worker 编写 tests/ (任务 5.1-5.4)
  4. 在真实 Windows + Office 环境中运行 `python main.py` 端到端测试

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
