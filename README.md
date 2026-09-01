# VSE TOOLBOX (CLI Edition)

> VSE Toolbox development utilities.

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
│   ├── agents/                       # 爬虫研究参考（research_notes / crawler_contract /
│   │                                 #   crawl_source_index / paa_har_snapshot）
│   └── superpowers/                  # 按日期的 feature 设计 spec 与执行计划
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

Aras/EWO 使用浏览器中已登录会话的 Cookie/Authorization，不在本地持久化凭据。CLI 会识别失效会话返回的登录页并给出重新获取浏览器凭据的提示；EWO 查询后可按 `max_records` 上限分页抓取，并导出为 UTF-8 CSV（Excel 可直接打开）。使用 HTTP 地址时 CLI 会提示凭据明文传输风险。

## 多智能体协作

多 Agent 协作规则、运行时选择与持久记忆协议见 `AGENTS.md`；本地双 Agent
harness（Codex 主导 + AGY CLI worker）见 `tools/agents/README.md` 与
`.agents/config.json`。2026-06 的四角色体系（`.codex.yaml` +
`docs/agents/role_*.md` 等）已于 2026-09-02 退役删除，如需查阅请走 Git 历史。
