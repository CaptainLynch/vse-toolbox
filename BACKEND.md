# VSE TOOLBOX - 后端开发主文档

> 本文档由 agent 读取并执行。每完成一个任务后，**必须**更新下方的「开发进度」表格状态，然后继续下一项。
>
> 状态约定：`TODO` -> `IN_PROGRESS` -> `DONE`

---

## 1. 项目概述

为汽车项目管理人员开发的桌面工具箱后端，使用 Python + FastAPI 提供本地 HTTP 服务（仅监听 127.0.0.1:8002），供前端 React 应用调用。

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

## 3. 数据库 Schema（8张表）

```sql
-- 问题追踪表
CREATE TABLE IF NOT EXISTS issues (...);

-- 里程碑进度表
CREATE TABLE IF NOT EXISTS milestones (...);

-- 飞书邮件缓存表
CREATE TABLE IF NOT EXISTS feishu_mails (...);

-- 待办任务表
CREATE TABLE IF NOT EXISTS todos (...);

-- 交付物分类表
CREATE TABLE IF NOT EXISTS deliverable_categories (...);

-- Dashboard卡片布局表
CREATE TABLE IF NOT EXISTS dashboard_layouts (...);

-- EWO/NCR记录表
CREATE TABLE IF NOT EXISTS ewo_ncr (...);

-- TIR记录表
CREATE TABLE IF NOT EXISTS tir (...);
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
| GET | /api/tir | TIR列表 |
| GET | /api/tir/stats | TIR统计 |
| POST | /api/tir | 创建TIR |
| PUT | /api/tir/{id} | 更新TIR |
| DELETE | /api/tir/{id} | 删除TIR |

---

## 5. 目录结构

```
backend/
├── main.py              # FastAPI入口（port 8002）
├── config.py            # 共享配置、目录常量、路径安全
├── api/
│   ├── issues.py        # 问题追踪 CRUD + 统计
│   ├── milestones.py    # 里程碑 CRUD
│   ├── excel.py         # Excel工具
│   ├── ppt.py           # PPT生成
│   ├── crawler.py       # 爬虫
│   ├── feishu.py        # 飞书
│   ├── dashboard.py     # Dashboard聚合+布局+分类
│   ├── ewo_ncr.py       # EWO/NCR CRUD
│   ├── tir.py           # TIR CRUD
│   └── response.py      # 统一响应封装
├── services/
│   ├── db.py            # SQLite（8张表+全部CRUD）
│   ├── excel_service.py
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

全部 Phase 1-7 完成。后端已实现全部 API 端点，包括前端重构新增的 dashboard/ewo/tir 端点。

---

## 7. 最后更新

- 创建时间：2026-05-27
- 最后更新：2026-06-07（新增 dashboard/ewo/tir 端点，端口改为 8002）