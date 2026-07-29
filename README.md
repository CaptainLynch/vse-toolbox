# VSE TOOLBOX (CLI Edition)

汽车行业项目管理自动化工具箱 — 纯命令行架构。

## 特性

- **极简依赖**: `rich`, `pywin32`, `imapclient`, `selenium`，零 Web 框架
- **完全离线**: 数据存储在本地 SQLite，无需云端服务
- **DLP 兼容**: Office 操作通过 `win32com.client` COM 自动化，绕过公司透明加密
- **交互式 CLI**: 基于 `rich` 的彩色终端菜单，操作直观
- **模块化设计**: 各 service 独立可调，通过 main.py 路由
- **多智能体协作**: 内置 Agent 角色定义和 SOP 流程文档

## 快速开始

```bash
# 1. 安装依赖（Windows + Python 3.9+）
pip install -r requirements.txt

# 2. 安装 pywin32 的 COM 注册（如首次安装）
python Scripts/pywin32_postinstall.py -install

# 3. 启动 CLI
python main.py
```

## 目录结构

```
vse-toolbox/
├── main.py                          # CLI 主入口 & 菜单循环
├── core/
│   ├── __init__.py
│   └── db_manager.py                # SQLite 连接管理 & 表结构
├── services/
│   ├── __init__.py
│   ├── intranet_scraper.py           # Selenium 内网爬虫
│   ├── feishu_imap.py                # IMAP 邮件解析 → SQLite
│   └── office_toolbox.py             # Excel / PPT 生成 (win32com COM)
├── data/
│   ├── templates/                    # PPT / Excel 模板
│   └── output/                       # 生成的文件输出
├── docs/
│   └── agents/                       # 多智能体 Prompt & 流程文档
│       ├── project_state.md          # 项目状态快照
│       ├── implementation_plan.md    # 架构实施计划
│       ├── task.md                   # 任务拆解与进度
│       ├── review_feedback.md        # 审查反馈记录
│       ├── research_notes.md         # Explorer 探索笔记
│       ├── SOP_worker_coding.md      # Worker 标准作业程序
│       └── role_*.md                 # 角色定义文件
├── setup.cfg                         # flake8 / mypy 配置
├── requirements.txt
└── README.md
```

## 菜单选项

| 编号 | 功能 | 对应模块 |
|---|---|---|
| 1 | 更新交付物状态 | `main.py` → SQLite |
| 2 | 生成周报 PPT | `services/office_toolbox.py` (PowerPoint COM) |
| 3 | 扫描飞书待办 | `services/feishu_imap.py` (IMAP) |
| 4 | Aras Cockpit | `services/aras_crawler.py`（EWO、PAA、NCR） |
| 5 | 查看项目概览 | `core/db_manager.py` |
| 6 | Excel 工具箱 | `services/excel_toolbox.py` |
| 7 | TDC 报表爬虫 | `services/tdc_auth.py` + `services/tdc_crawler.py`（企业账号登录、查询与导出） |
| 0 | 退出系统 | — |

菜单 4 保持为 Aras Cockpit。菜单 7 提供数模设计审核流程、SOR 流程以及造型 A 面冻结发布单的独立 CLI。TDC 默认通过企业账号中心使用用户名和隐藏密码完成 OIDC 登录，浏览器 Header/Cookie 作为备用方式保留；密码、令牌和会话信息不写入配置、日志或诊断报告。

EWO/PAA 新建 XLSX 导出以 Excel COM 为首选。仅当本机明确没有可用的
`Excel.Application` COM 注册时，Aras 导出器使用 Python 标准库生成等价的
OOXML 新文件；该窄范围回退不读取或修改已有工作簿，也不适用于 Excel 工具箱、
PPT 或其他可能受 DLP 保护的 Office 文件。Excel 已启动后的保存、权限、DLP 或
磁盘错误始终失败关闭，不会绕过 COM。

## 多智能体协作

项目内置四角色 Agent 体系，详见 `docs/agents/` 目录：

| 角色 | 模型 | 职责 | 权限 |
|---|---|---|---|
| Explorer | 低深度推理 | 代码探索、上下文检索 | 只读 |
| Architect | 高深度推理 | 架构设计、任务拆解 | 可写文档 |
| Worker | 结构化推理 | 代码实现、单元测试 | 可写代码 |
| Reviewer | 高深度推理 | 静态检查、代码审查 | 只读 |
