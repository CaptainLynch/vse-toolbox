# ARCHITECTURE

> **当前系统架构的最终结论。只放What，不放Why（Why在ADR.md）。**

---

## 1. 运行时架构

```
+---------------------------------------------------------------+
|  用户操作层                                                     |
|  浏览器 http://127.0.0.1:8002                                  |
|                                                               |
|  +--------------+    +--------------+    +--------------+     |
|  | Analytics    |    | Toolbox      |    | FeishuMail   |     |
|  | (数据分析看板)|    | (Excel/PPT/  |    | (邮件/待办)   |     |
|  | + 子页面体系  |    |  爬虫)       |    |              |     |
|  +------+-------+    +------+-------+    +------+-------+     |
|         |                   |                   |              |
|  +------+-------------------+-------------------+--------+    |
|  |                  React 19 (HashRouter)                |    |
|  |           fetch('/api/xxx') -> 统一api.ts封装         |    |
|  +---------------------------+---------------------------+    |
|                              |                                |
+------------------------------+--------------------------------+
|                              |  127.0.0.1:8002               |
|  +---------------------------+---------------------------+    |
|  |              FastAPI + Uvicorn (ASGI)                  |    |
|  |  /api/issues  /api/excel  /api/ppt  /api/crawler      |    |
|  |  /api/feishu  /api/download  /api/milestones           |    |
|  |  /api/dashboard  /api/ewo  /api/tir                    |    |
|  |  /api/lookup  /api/settings  /api/*/import-excel       |    |
|  +---------------------------+---------------------------+    |
|                              |                                |
|  +---------------------------+---------------------------+    |
|  |              业务服务层                                 |    |
|  |                                                       |    |
|  |  +-----------+  +-----------+  +-------------------+  |    |
|  |  | db.py     |  | excel_    |  | ppt_service.py    |  |    |
|  |  | (SQLite)  |  | service.  |  | TemplateEngine    |  |    |
|  |  |           |  | py        |  | DataAdapter       |  |    |
|  |  |           |  | (openpyxl |  | ChartGenerator    |  |    |
|  |  |           |  | +pandas)  |  |                   |  |    |
|  |  +-----------+  +-----------+  +-------------------+  |    |
|  |                                                       |    |
|  |  +---------------+  +-----------------------------+   |    |
|  |  | crawler_      |  | feishu_service.py           |   |    |
|  |  | service.py    |  | sync_mails()                |   |    |
|  |  | DriverManager |  | extract_todos()             |   |    |
|  |  | (Chrome+Edge) |  |                             |   |    |
|  |  +---------------+  +-----------------------------+   |    |
|  +-------------------------------------------------------+    |
|                                                               |
|  +-------------------------------------------------------+    |
|  |              外部依赖层                                 |    |
|  |                                                       |    |
|  |  +----------+  +----------+  +----------------------+ |    |
|  |  | drivers/ |  | templates|  | Chrome / Edge        | |    |
|  |  | chromedri|  | /master/ |  | (白名单控制)         | |    |
|  |  | ver.exe  |  | .pptx    |  |                      | |    |
|  |  | msedge dr|  |          |  |                      | |    |
|  |  | iver.exe |  |          |  |                      | |    |
|  |  +----------+  +----------+  +----------------------+ |    |
|  +-------------------------------------------------------+    |
|                                                               |
|  +-------------------------------------------------------+    |
|  |              公司安全层（透明）                         |    |
|  |  文件自动加密  |  网络防火墙  |  白名单控制  |  GAC    |    |
|  +-------------------------------------------------------+    |
+---------------------------------------------------------------+
```

---

## 2. 数据流

### 2.1 问题追踪
```
前端 DeliverableIssues --GET/POST/PUT/DELETE /api/issues--> api/issues.py --> db.py --> SQLite
                                                         |
                                                  GET /api/issues/stats
                                                         |
                                              聚合查询返回KPI+图表数据
```

### 2.2 Excel处理
```
前端 Toolbox --multipart/form-data--> api/excel.py --> excel_service.py --> openpyxl/pandas
                                                              |
                                                        生成文件到temp/
                                                              |
                                                        GET /api/download
                                                              |
                                                        前端自动下载
```

### 2.3 PPT生成
```
前端 Toolbox --JSON--> api/ppt.py --> ppt_service.py
                                         |--- DataAdapter --> db.py
                                         |--- ChartGenerator --> matplotlib -> PNG
                                         +--- TemplateEngine --> python-pptx
                                                          |
                                                    填充母版模板
                                                          |
                                                    输出到templates/output/
                                                          |
                                                    GET /api/download
```

### 2.4 爬虫
```
前端 Toolbox --JSON{url}--> api/crawler.py --> crawler_service.py
                                                     |--- auto_select(url)
                                                     |     |--- feishu.cn -> Edge WebDriver
                                                     |     +--- 其他 -> Chrome WebDriver
                                                     |--- fetch_page()
                                                     +--- extract_table()
```

### 2.5 飞书
```
前端 FeishuMail --POST /api/feishu/sync--> feishu_service.py --> Edge WebDriver --> 飞书网页
     |                                                                            |
  GET /api/feishu/mails <-------------------------------------------- 抓取邮件写入SQLite
     |
  GET /api/feishu/todos <-- feishu_service.extract_todos() --> 关键词匹配生成待办
```

### 2.6 Dashboard 聚合
```
前端 AnalyticsOverview --GET /api/dashboard/overview--> api/dashboard.py
                                                            |--- issues stats
                                                            |--- milestones
                                                            |--- deliverable_categories
                                                            +--- ewo/tir counts
```

### 2.7 EWO/NCR & TIR
```
前端 DeliverableEWO --GET/POST/PUT/DELETE /api/ewo--> api/ewo_ncr.py --> db.py --> SQLite
前端 DeliverableTIR --GET/POST/PUT/DELETE /api/tir--> api/tir.py --> db.py --> SQLite
```

---

## 3. 数据库结构

### 3.1 ERD

```
+--------------+       +--------------+       +--------------+       +--------------+
|   issues     |       |  milestones  |       | feishu_mails |       |    todos     |
+--------------+       +--------------+       +--------------+       +--------------+
| id PK TEXT   |       | id PK INT    |       | id PK TEXT   |       | id PK TEXT   |
| priority TEXT|       | name TEXT    |       | sender TEXT  |       | content TEXT |
| component TEXT|      | category TEXT|       | subject TEXT |       | source TEXT  |
| description TEXT     | percentage INT       | preview TEXT |       | deadline TEXT|
| department TEXT|     | target_date TEXT     | content TEXT |       | completed INT|
| status TEXT  |       | actual_date TEXT     | category TEXT|       | created_at TEXT
| assignee TEXT|       | actual_pct INT       | is_read INT  |       +--------------+
| part_system  |       +--------------+       | is_starred INT
| sub_system   |                              | has_attachment INT
| root_cause   |                              | received_at TEXT
| short_term   |                              +--------------+
| long_term    |
| cutoff_point |
| action_plan  |
| source       |
| source_file  |
| created_at   |
| updated_at   |
+--------------+

+---------------------+       +---------------------+       +--------------+
| deliverable_        |       | dashboard_          |       |  ewo_ncr     |
| categories          |       | layouts             |       +--------------+
+---------------------+       +---------------------+       | id PK TEXT   |
| id PK TEXT          |       | id PK INT           |       | type TEXT    |
| name TEXT           |       | user_id TEXT        |       | title TEXT   |
| icon TEXT           |       | page_key TEXT       |       | description  |
| sort_order INT      |       | card_id TEXT        |       | severity TEXT|
| is_visible INT      |       | card_type TEXT      |       | status TEXT  |
| created_at TEXT     |       | x INT, y INT        |       | department   |
+---------------------+       | w INT, h INT        |       | assignee     |
                              | config TEXT         |       | raised_date  |
                              | created_at TEXT     |       | target_date  |
                              | updated_at TEXT     |       | source       |
                              +---------------------+       | source_file  |
                                                            | created_at   |
                                                            | updated_at   |
                                                            +--------------+

+--------------+       +--------------------+       +--------------------+
|    tir       |       | lookup_part_system |       | lookup_engineer    |
+--------------+       +--------------------+       +--------------------+
| id PK TEXT   |       | id PK INT          |       | id PK INT          |
| title TEXT   |       | part_system TEXT   |       | name TEXT          |
| description  |       | sub_system TEXT    |       | department TEXT    |
| category TEXT|       | created_at TEXT    |       | created_at TEXT    |
| status TEXT  |       +--------------------+       +--------------------+
| department   |
| assignee     |       +--------------------+
| test_date    |       | app_settings       |
| result TEXT  |       +--------------------+
| source       |       | key PK TEXT        |
| source_file  |       | value TEXT         |
| created_at   |       | updated_at TEXT    |
| updated_at   |       +--------------------+
+--------------+
```

### 3.2 表定义

**issues**
```sql
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,                           -- ISS-YYYY-MMDDHHMMSS-xxxxxx
    priority TEXT CHECK(priority IN ('P0','P1','P2','P3')),
    component TEXT NOT NULL,                       -- 零部件名称
    description TEXT NOT NULL,
    department TEXT NOT NULL,                      -- 责任科室
    status TEXT CHECK(status IN ('open','in_progress','resolved','closed')),
    assignee TEXT,                                 -- 责任工程师
    part_system TEXT,                              -- 零件总成
    sub_system TEXT,                               -- 子系统
    root_cause TEXT,                               -- 问题原因分析
    short_term_action TEXT,                        -- 短期措施
    long_term_action TEXT,                         -- 长期措施
    cutoff_point TEXT,                             -- 断点时间
    action_plan TEXT,                              -- 行动计划
    source TEXT DEFAULT 'manual',                  -- manual / excel_import
    source_file TEXT,                              -- 来源Excel文件名
    created_at TEXT,                               -- ISO-8601
    updated_at TEXT
);
```

**milestones**
```sql
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    percentage INTEGER DEFAULT 0 CHECK(percentage BETWEEN 0 AND 100),
    target_date TEXT,                              -- 计划完成日期
    actual_date TEXT,                              -- 实际完成日期
    actual_percentage INTEGER DEFAULT 0 CHECK(actual_percentage BETWEEN 0 AND 100)
);
```

**feishu_mails**
```sql
CREATE TABLE IF NOT EXISTS feishu_mails (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    preview TEXT,
    content TEXT,
    category TEXT,
    is_read INTEGER DEFAULT 0,
    is_starred INTEGER DEFAULT 0,
    has_attachment INTEGER DEFAULT 0,
    received_at TEXT
);
```

**todos**
```sql
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT,
    deadline TEXT,
    completed INTEGER DEFAULT 0,
    created_at TEXT
);
```

**deliverable_categories**
```sql
CREATE TABLE IF NOT EXISTS deliverable_categories (
    id TEXT PRIMARY KEY,            -- 'issues', 'ewo', 'tir'
    name TEXT NOT NULL,             -- '造车问题', 'EWO/NCR', 'TIR'
    icon TEXT,                      -- lucide icon name
    sort_order INTEGER DEFAULT 0,
    is_visible INTEGER DEFAULT 1,
    created_at TEXT
);
-- Seed: issues(1), ewo(2), tir(3)
```

**dashboard_layouts**
```sql
CREATE TABLE IF NOT EXISTS dashboard_layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    page_key TEXT NOT NULL,             -- 'overview', 'issues', 'ewo', 'tir'
    card_id TEXT NOT NULL,
    card_type TEXT NOT NULL,
    x INTEGER NOT NULL DEFAULT 0,
    y INTEGER NOT NULL DEFAULT 0,
    w INTEGER NOT NULL DEFAULT 1,
    h INTEGER NOT NULL DEFAULT 1,
    config TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, page_key, card_id)
);
```

**ewo_ncr**
```sql
CREATE TABLE IF NOT EXISTS ewo_ncr (
    id TEXT PRIMARY KEY,                -- EWO-YYYY-MMDD-xxxx / NCR-YYYY-MMDD-xxxx
    type TEXT CHECK(type IN ('EWO','NCR')),
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT CHECK(severity IN ('critical','major','minor')),
    status TEXT CHECK(status IN ('open','investigating','resolved','closed')),
    department TEXT,
    assignee TEXT,
    raised_date TEXT,
    target_date TEXT,
    source TEXT DEFAULT 'manual',
    source_file TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

**tir**
```sql
CREATE TABLE IF NOT EXISTS tir (
    id TEXT PRIMARY KEY,                -- TIR-YYYY-MMDD-xxxx
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    status TEXT CHECK(status IN ('draft','submitted','approved','rejected')),
    department TEXT,
    assignee TEXT,
    test_date TEXT,
    result TEXT,
    source TEXT DEFAULT 'manual',
    source_file TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

**lookup_part_system**（零件总成→子系统映射）
```sql
CREATE TABLE IF NOT EXISTS lookup_part_system (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_system TEXT NOT NULL UNIQUE,
    sub_system TEXT NOT NULL,
    created_at TEXT
);
```

**lookup_engineer**（工程师→科室映射）
```sql
CREATE TABLE IF NOT EXISTS lookup_engineer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    created_at TEXT
);
```

**app_settings**（应用配置持久化）
```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT
);
```

---

## 4. API端点清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/issues | 列表（page,size,priority,status,department） |
| POST | /api/issues | 创建 |
| PUT | /api/issues/{id} | 更新 |
| DELETE | /api/issues/{id} | 删除 |
| GET | /api/issues/stats | 统计 |
| GET | /api/milestones | 里程碑列表 |
| POST | /api/milestones | 创建里程碑 |
| PUT | /api/milestones/{id} | 更新里程碑 |
| DELETE | /api/milestones/{id} | 删除里程碑 |
| POST | /api/excel/merge | 多文件合并（multipart） |
| POST | /api/excel/merge-same | 同结构拼接（multipart） |
| POST | /api/excel/rename | 批量改名（JSON） |
| GET | /api/ppt/templates | 模板列表 |
| POST | /api/ppt/weekly | 生成周报 |
| POST | /api/ppt/deliverable | 生成交付物报告 |
| POST | /api/crawler/fetch | 抓取页面 |
| POST | /api/crawler/table | 提取表格 |
| GET | /api/feishu/mails | 邮件列表 |
| POST | /api/feishu/sync | 同步邮件 |
| GET | /api/feishu/todos | 待办列表 |
| POST | /api/feishu/todo-toggle | 切换待办状态 |
| GET | /api/download | 文件下载（?path=） |
| GET | /api/dashboard/overview | 首页聚合数据 |
| GET | /api/dashboard/deliverable-categories | 交付物分类列表 |
| POST | /api/dashboard/deliverable-categories | 新增分类 |
| PUT | /api/dashboard/deliverable-categories/{id} | 更新分类 |
| DELETE | /api/dashboard/deliverable-categories/{id} | 删除分类 |
| GET | /api/dashboard/layouts?page_key=xxx | 获取页面卡片布局 |
| PUT | /api/dashboard/layouts | 批量保存卡片布局 |
| GET | /api/ewo | EWO/NCR列表（page,size,status,severity） |
| GET | /api/ewo/stats | EWO/NCR统计 |
| POST | /api/ewo | 创建EWO/NCR |
| PUT | /api/ewo/{id} | 更新EWO/NCR |
| DELETE | /api/ewo/{id} | 删除EWO/NCR |
| POST | /api/ewo/import-excel | EWO Excel导入（multipart） |
| GET | /api/tir | TIR列表（page,size,status,category） |
| GET | /api/tir/stats | TIR统计 |
| POST | /api/tir | 创建TIR |
| PUT | /api/tir/{id} | 更新TIR |
| DELETE | /api/tir/{id} | 删除TIR |
| POST | /api/tir/import-excel | TIR Excel导入（multipart） |
| POST | /api/issues/import-excel | 造车问题 Excel导入（multipart） |
| GET | /api/lookup/part-system?q=xxx | 零件总成模糊查询 |
| POST | /api/lookup/part-system | 新增零件总成映射 |
| GET | /api/lookup/engineer?q=xxx | 工程师模糊查询 |
| POST | /api/lookup/engineer | 新增工程师映射 |
| GET | /api/settings | 获取全部设置项 |
| PUT | /api/settings/{key} | 更新单个设置项 |

---

## 5. 目录结构

```
VSE_TOOLBOX/
├── PROJECT.md              # 入口
├── TODO.md                 # 全局任务
├── ADR.md                  # 决策记录
├── ARCHITECTURE.md         # 本文件
├── CODING_RULES.md         # 编码规则
├── ROLES.md                # 模型分工
├── DESIGN_FRONTEND_REDESIGN.md  # 前端重构设计
├── backend/
│   ├── main.py             # FastAPI入口（port 8002）
│   ├── config.py           # 共享配置、目录常量、路径安全
│   ├── api/
│   │   ├── issues.py       # 问题追踪 + Excel导入
│   │   ├── milestones.py   # 里程碑
│   │   ├── excel.py        # Excel工具
│   │   ├── ppt.py          # PPT生成
│   │   ├── crawler.py      # 爬虫
│   │   ├── feishu.py       # 飞书
│   │   ├── dashboard.py    # Dashboard聚合+布局+分类
│   │   ├── ewo_ncr.py      # EWO/NCR CRUD + Excel导入
│   │   ├── tir.py          # TIR CRUD + Excel导入
│   │   ├── lookup.py       # 零件总成/工程师自动关联
│   │   ├── settings.py     # 应用配置
│   │   └── response.py     # 统一响应封装
│   ├── services/
│   │   ├── db.py           # SQLite（11张表）
│   │   ├── excel_service.py
│   │   ├── excel_import_service.py  # 交付物Excel导入引擎
│   │   ├── ppt_service.py  # TemplateEngine+DataAdapter+ChartGenerator
│   │   ├── crawler_service.py  # DriverManager+PageExtractor
│   │   └── feishu_service.py
│   ├── models/
│   │   └── schemas.py      # Pydantic（含EWO/TIR/Dashboard模型）
│   ├── drivers/            # WebDriver
│   │   ├── chromedriver.exe
│   │   └── msedgedriver.exe
│   ├── templates/
│   │   ├── master/         # .pptx母版
│   │   ├── config/         # .json映射
│   │   └── output/         # PPT输出
│   └── dist/               # 前端build产物
├── app/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ui/         # shadcn/ui组件库
│   │   │   ├── Sidebar.tsx
│   │   │   ├── TopBar.tsx
│   │   │   ├── LoadingScreen.tsx
│   │   │   ├── OfflineBanner.tsx
│   │   │   ├── SubPageNav.tsx      # 子页面底部导航
│   │   │   ├── DraggableGrid.tsx   # 磁吸卡片网格
│   │   │   └── DraggableCard.tsx   # 可拖拽卡片
│   │   ├── pages/
│   │   │   ├── AnalyticsLayout.tsx  # 数据分析看板容器
│   │   │   ├── AnalyticsOverview.tsx # 项目总览首页
│   │   │   ├── DeliverableIssues.tsx # 造车问题子页面
│   │   │   ├── DeliverableEWO.tsx    # EWO/NCR子页面
│   │   │   ├── DeliverableTIR.tsx    # TIR子页面
│   │   │   ├── Analytics.tsx         # 旧版分析页（保留）
│   │   │   ├── Dashboard.tsx         # 旧版问题页（保留）
│   │   │   ├── ExcelToolbox.tsx      # Excel工具箱（保留）
│   │   │   ├── Toolbox.tsx           # 工具矩阵
│   │   │   ├── FeishuMail.tsx        # 飞书邮件助手
│   │   │   └── Settings.tsx          # 设置
│   │   ├── config/
│   │   │   └── defaultLayouts.ts     # 默认卡片布局
│   │   ├── services/
│   │   │   ├── api.ts               # API封装
│   │   │   └── converters.ts        # snake_case->camelCase
│   │   ├── stores/
│   │   │   └── appStore.ts          # Zustand全局状态
│   │   ├── types/
│   │   │   └── index.ts             # TypeScript类型定义
│   │   ├── hooks/
│   │   │   └── use-mobile.ts
│   │   ├── lib/
│   │   │   └── utils.ts
│   │   ├── App.tsx
│   │   ├── main.tsx                 # HashRouter入口
│   │   ├── index.css                # 全局样式+react-grid-layout
│   │   └── App.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── postcss.config.js
├── data/
│   └── VSE_TOOLBOX.db
├── temp/
├── logs/
├── requirements.txt
└── build.py                # PyInstaller打包
```

---

## 6. 关键常量

### 配色
```
primary:        #d4af37 (琥珀金)
background:     #0a0a0c (主背景)
surface:        #141416 (卡片)
text_primary:   #ffffff
text_secondary: #8a8f98
border:         #2a2a2e
danger:         #ff4d4d
warning:        #ff9f4d
success:        #4ade80
```

### 端口与地址
```
后端监听: 127.0.0.1:8002
前端访问: http://127.0.0.1:8002 (dist/) 或 http://localhost:5173 (dev)
CORS: 127.0.0.1:8000, 127.0.0.1:8002, localhost:5173
API前缀: /api
静态文件: /
```

### 浏览器分流规则
```
URL含feishu.cn或larksuite.com -> msedgedriver.exe (Edge)
其他URL -> chromedriver.exe (Chrome)
```

---

最后更新：2026-06-07（追加 Phase 5：交付物管理与 Excel 导入 — 数据库扩展至11张表 + lookup/settings/import-excel API + 前端Settings/Overview/Issues重写）