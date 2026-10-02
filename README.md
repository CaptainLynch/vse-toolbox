# VSE Toolbox

> 状态：Active
> 读者：User
> 权威来源：运行入口、代码和测试；本文件只承担用户向导，不承担 Agent 代码地图
> 默认读取：按用户任务读取

VSE Toolbox 是面向 Windows 的工业/企业项目管理工具箱，提供本地 Web 工作台、
Rich CLI、Aras/TDC 数据查询与导出、交付物状态管理、定时归档，以及隔离的 Excel
自动化 Worker。

## 运行形态

| 模式 | 启动入口 | 用途 |
|---|---|---|
| Web 工作台 | `python webui.py` | 推荐的本地 Flask 单页工作台 |
| Rich CLI | `python main.py` | 交互式命令行和一次性操作 |
| Excel Worker | `python tools/excel_worker_cli.py --help` | 独立执行 Excel/COM 任务 |
| TDC 契约探测 | `python tdc_probe_main.py --help` | 受控的 TDC 接口诊断 |

生产环境使用 PyInstaller 打包的 WebUI 与 `VSE-ExcelWorker.exe`。Worker 与主程序
保持独立进程边界，具体部署、哈希校验和排障步骤见
`docs/PRODUCTION_OPERATION_GUIDE.md` 与 `docs/USER_GUIDE_STANDALONE_EXE.md`。

## 能力概览

- Flask + 原生 JavaScript 本地 Web 工作台；
- Rich CLI；
- SQLite 本地状态、运行记录、审计和归档存储；
- Aras EWO/PAA/NCR 查询、解析与导出；
- TDC 数模、SOR、A 面流程查询、导出与契约探测；
- 交付物状态、分析、映射发现和定时归档；
- 通过 `pywin32`/`xlwings` 调用本机 Office 的 Excel/PPT 自动化；
- Windows Credential Manager/DPAPI 和统一脱敏边界。

外部系统查询需要企业网络和有效会话/凭据；离线测试使用本地合成数据，不应把
生产 Cookie、Token、密码或原始响应写入仓库。

## 快速开始

```powershell
# 安装依赖（Windows，Python 3.9+）
python -m pip install -r requirements.txt

# 首次使用 pywin32 时按本机环境完成 COM 注册
python Scripts/pywin32_postinstall.py -install

# 启动 Web 工作台
python webui.py

# 或启动 CLI
python main.py
```

默认 Web 地址为 `http://127.0.0.1:5000/`。写操作只接受本机回环访问；不要把
本地服务直接暴露到不受信任的网络。

## 代码与文档导航

- Agent 代码地图：`PROJECT_MAP.md`
- Agent 协作和检索规则：`AGENTS.md`
- 持久化记忆导航：`memory/CONTEXT_MANIFEST.md`
- Web API 端点：`docs/API_ENDPOINTS.md`（生成文档）
- 生产运行手册：`docs/PRODUCTION_OPERATION_GUIDE.md`
- 独立 EXE 用户手册：`docs/USER_GUIDE_STANDALONE_EXE.md`
- Excel Worker 契约：`docs/EXCEL_TASK_WORKER.md`
- 定时归档架构：`docs/SCHEDULED_ARCHIVE_RUNNER_ARCHITECTURE.md`
- 交付物控制台修复与审计：[实施口径、审查结论及验证结果](docs/DELIVERABLE_CONSOLE_AUDIT_20260916.md)
- 交付物控制台验收：[受影响 UI 与手工测试 TODO](docs/DELIVERABLE_CONSOLE_UI_TODO_20260916.md)

目录结构、任务路由、生产模块职责和默认拒绝路径以 `PROJECT_MAP.md` 为准；不要
通过扫描仓库根目录来替代地图导航。

## CLI 菜单概览

| 编号 | 功能 | 主要入口 |
|---|---|---|
| 1 | 更新交付物状态 | `main.py`、SQLite |
| 2 | 生成周报 PPT | `services/office_toolbox.py` |
| 3 | 扫描飞书待办 | `services/feishu_imap.py` |
| 4 | Aras Cockpit | `services/aras_auth.py`、`services/aras_crawler.py` |
| 5 | 查看项目概览 | `core/db_manager.py` |
| 6 | Excel 工具箱 | `services/excel_toolbox.py` |
| 7 | TDC 报表工具 | `services/tdc_auth.py`、`services/tdc_crawler.py` |

CLI 菜单不是 Web 工作台的完整功能清单；Web API 和页面能力请查看对应文档。

## 协作说明

多 Agent 协作、Worker 运行时和持久化记忆规则以 `AGENTS.md` 为准。历史计划、
会话交接稿和外部上下文快照仅用于特定任务，不是当前代码事实来源。
