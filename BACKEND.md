# VSE TOOLBOX - 后端开发主文档

> 本文档由 agent 读取并执行。每完成一个任务后，**必须**更新下方的「开发进度」表格状态，然后继续下一项。
>
> 状态约定：`TODO` -> `IN_PROGRESS` -> `DONE`

---

## 1. 项目概述

为汽车项目管理人员开发的桌面工具箱后端。
**当前开发策略（2026-06-13起）**：已暂停 FastAPI/React 的 Web 端开发，全面转向基于中文命令行的终端 (CLI) 模式，以最快速度落地核心业务（爬虫、Excel、PPT）。

**主要入口**：
1. `cli_main.py`（最新）：终端命令行交互入口。
2. `main.py`（冷藏中）：FastAPI 服务，仅监听 127.0.0.1:8002。

**运行环境**：公司电脑（无 Python、无 pip、无管理员权限）
**部署形态**：PyInstaller 打包为独立 exe，绿色便携

---

## 2. 技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| 运行时 | Python 3.14 | 主运行环境 |
| Web 框架 | FastAPI | API 服务 |
| 服务器 | Uvicorn | ASGI 服务器 |
| Excel 处理 | openpyxl + pandas | 读写 Excel |
| PPT 生成 | python-pptx + matplotlib | 生成 PowerPoint |
| 爬虫 | selenium | 浏览器自动化 |
| 数据验证 | Pydantic | 模型校验 |
| 打包 | PyInstaller | 打包为 exe |

---

## 3. 数据库 Schema（11张表）

```sql
-- 问题追踪表（已扩展：零件总成/子系统/原因分析/措施/断点/行动计划/source）
CREATE TABLE IF NOT EXISTS issues (...);

-- 里程碑进度表（已扩展：actual_date / actual_percentage）
CREATE TABLE IF NOT EXISTS milestones (...);

-- 飞书邮件缓存表
CREATE TABLE IF NOT EXISTS feishu_mails (...);

-- 待办任务表
CREATE TABLE IF NOT EXISTS todos (...);

-- 交付物分类表
CREATE TABLE IF NOT EXISTS deliverable_categories (...);

-- Dashboard卡片布局表
CREATE TABLE IF NOT EXISTS dashboard_layouts (...);

-- EWO/NCR记录表（已扩展：source / source_file）
CREATE TABLE IF NOT EXISTS ewo_ncr (...);

-- TIR记录表（已扩展：source / source_file）
CREATE TABLE IF NOT EXISTS tir (...);

-- 零件总成→子系统映射表
CREATE TABLE IF NOT EXISTS lookup_part_system (...);

-- 工程师→科室映射表
CREATE TABLE IF NOT EXISTS lookup_engineer (...);

-- 应用配置表
CREATE TABLE IF NOT EXISTS app_settings (...);
```

> 完整 Schema 见 backend/services/db.py 的 SCHEMA_SQL 常量。

---

## 4. API 端点清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/issues | 问题列表（支持分页筛选） |
| POST | /api/issues | 创建问题 |
| PUT | /api/issues/{id} | 更新问题 |
| DELETE | /api/issues/{id} | 删除问题 |
| GET | /api/issues/stats | 问题统计 |
| GET | /api/milestones | 里程碑列表 |
| POST | /api/milestones | 创建里程碑 |
| PUT | /api/milestones/{id} | 更新里程碑 |
| DELETE | /api/milestones/{id} | 删除里程碑 |
| POST | /api/excel/merge | Excel多文件合并 |
| POST | /api/excel/merge-same | 同结构拼接 |
| POST | /api/excel/rename | 批量改名 |
| GET | /api/ppt/templates | 模板列表 |
| POST | /api/ppt/weekly | 生成周报PPT |
| POST | /api/ppt/deliverable | 生成交付物PPT |
| POST | /api/crawler/fetch | 抓取页面 |
| POST | /api/crawler/table | 提取表格 |
| GET | /api/feishu/mails | 邮件列表 |
| POST | /api/feishu/sync | 同步邮件 |
| GET | /api/feishu/todos | 待办列表 |
| POST | /api/feishu/todo-toggle | 切换待办状态 |
| GET | /api/download | 文件下载 |
| GET | /api/dashboard/overview | 首页聚合数据 |
| GET | /api/dashboard/deliverable-categories | 交付物分类列表 |
| POST | /api/dashboard/deliverable-categories | 新增分类 |
| PUT | /api/dashboard/deliverable-categories/{id} | 更新分类 |
| DELETE | /api/dashboard/deliverable-categories/{id} | 删除分类 |
| GET | /api/dashboard/layouts | 获取卡片布局 |
| PUT | /api/dashboard/layouts | 保存卡片布局 |
| GET | /api/ewo | EWO/NCR列表 |
| GET | /api/ewo/stats | EWO/NCR统计 |
| POST | /api/ewo | 创建EWO/NCR |
| PUT | /api/ewo/{id} | 更新EWO/NCR |
| DELETE | /api/ewo/{id} | 删除EWO/NCR |
| POST | /api/ewo/import-excel | EWO Excel导入 |
| GET | /api/tir | TIR列表 |
| GET | /api/tir/stats | TIR统计 |
| POST | /api/tir | 创建TIR |
| PUT | /api/tir/{id} | 更新TIR |
| DELETE | /api/tir/{id} | 删除TIR |
| POST | /api/tir/import-excel | TIR Excel导入 |
| POST | /api/issues/import-excel | 造车问题 Excel导入 |
| GET | /api/lookup/part-system | 零件总成查询 |
| POST | /api/lookup/part-system | 新增零件总成映射 |
| GET | /api/lookup/engineer | 工程师查询 |
| POST | /api/lookup/engineer | 新增工程师映射 |
| GET | /api/settings | 获取全部设置 |
| PUT | /api/settings/{key} | 更新单个设置 |

---

## 5. 目录结构

```
backend/
├── main.py              # FastAPI入口（port 8002）
├── config.py            # 共享配置、目录常量、路径安全
├── api/
│   ├── issues.py        # 问题追踪 CRUD + 统计 + Excel导入
│   ├── milestones.py    # 里程碑 CRUD
│   ├── excel.py         # Excel工具
│   ├── ppt.py           # PPT生成
│   ├── crawler.py       # 爬虫
│   ├── feishu.py        # 飞书
│   ├── dashboard.py     # Dashboard聚合+布局+分类
│   ├── ewo_ncr.py       # EWO/NCR CRUD + Excel导入
│   ├── tir.py           # TIR CRUD + Excel导入
│   ├── lookup.py        # 零件总成/工程师自动关联
│   ├── settings.py      # 应用配置
│   └── response.py      # 统一响应封装
├── services/
│   ├── db.py            # SQLite（11张表+全部CRUD）
│   ├── excel_service.py
│   ├── excel_import_service.py  # 交付物Excel导入引擎
│   ├── ppt_service.py
│   ├── crawler_service.py
│   └── feishu_service.py
├── models/
│   └── schemas.py       # Pydantic模型
├── drivers/             # WebDriver
├── templates/           # PPT模板
└── dist/                # 前端build产物
```

---

## 6. 开发进度

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1-7 | DONE | 基础框架+问题追踪+Excel+PPT+爬虫+飞书+打包 |
| Phase 8 | DONE | 前端重构后端扩展（dashboard/ewo/tir） |
| Phase 9 | DONE | 交付物管理与Excel导入（B-24~B-38）+ 两轮代码审计（24项修复22项） |
| API集成测试 | DONE | 37项API测试全部通过（2026-06-07） |

---

## 7. 最后更新

- 创建时间：2026-05-27
- 最后更新：2026-06-07（后端代码审计修复完毕 + API集成测试 37项全部通过 + 前端 F-20~F-26 完成+两轮审计）