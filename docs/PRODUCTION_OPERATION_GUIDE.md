# VSE Toolbox 生产环境独立可执行文件操作与测试指南

本文档指导在**无需安装 Python 及第三方依赖**的 Windows 生产/预发环境中，部署、运行与测试 VSE Toolbox 的独立可执行文件（`.exe`）。

---

## 1. 交付工件清单与哈希校验

生产构建输出位于 `dist/` 目录：

| 文件名 | 架构 / 角色 | 说明 |
|---|---|---|
| `VSE-WebUI.exe` | Web 工作台主进程 (Flask + WebUI) | 提供 HTTP/REST API、仪表盘单页应用与任务管理调度（排除 COM 依赖，高稳定性） |
| `VSE-ExcelWorker.exe` | 独立 Excel 自动化工作进程 (CLI Worker) | 承载 Office COM / `xlwings` 真实任务执行，与 Web 进程强物理隔离 |
| `VSE-Toolbox.exe` | 统一终端交互控制台 (Rich CLI) | 面向运维/开发人员的终端全功能菜单（包含 Aras/TDC 查询、Excel 工具箱等） |
| `SHA256SUMS.txt` | 安全校验签名文件 | 包含所有可执行文件的 SHA-256 哈希指纹 |

### 签名校验方法 (PowerShell)

在目标机器上校验工件完整性：

```powershell
# 进入部署目录并计算 SHA256
Get-FileHash -Algorithm SHA256 dist\*.exe
```

---

## 2. 生产运行架构说明

```
┌────────────────────────────────────────────────────────┐
│                   浏览器 / 客户端                       │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP (http://127.0.0.1:5000)
┌──────────────────────────▼─────────────────────────────┐
│                    VSE-WebUI.exe                       │
│  - 仪表盘 / Aras Cockpit / TDC 控制台                  │
│  - SQLite 数据库状态机 (CAS 租约 & 乐观锁)             │
│  - ExcelWorker 进程控制器 (Loopback 同源保护)          │
└─────────────┬────────────────────────────┬─────────────┘
              │ 启动/监控子进程             │ 读写任务元数据
┌─────────────▼────────────┐ ┌─────────────▼─────────────┐
│   VSE-ExcelWorker.exe    │ │     vse_toolbox.db        │
│  - 独立运行 / 轮询队列   │ │  (阶段/里程碑/任务/审计)  │
│  - 真实 Office COM / xlwings  └─────────────────────────┘
│  - 白名单目录原子写操作  │
└─────────────┬────────────┘
              │ Headless 操作
┌─────────────▼────────────┐
│ Microsoft Excel (COM)    │
└──────────────────────────┘
```

**关键设计优势**：
- **COM 隔离**：Excel 崩溃或内存泄漏不会导致 WebUI 服务宕机。
- **零依赖运行**：内嵌 Python 3.12 运行时与所有依赖库，目标机无需配置 Python、pip 或环境变量。

---

## 3. 生产测试环境要求

1. **操作系统**：Windows 10 / Windows 11 / Windows Server 2016+ (x64)
2. **Office 环境**：Microsoft Office 2016 / 2019 / 2021 / Office 365（需已激活并可正常启动 Excel）
3. **网络要求**：
   - 本地 Loopback（`127.0.0.1`）访问权限
   - 若测试 Aras 爬虫：需连通企业 Aras ECM 网段
   - 若测试 TDC 爬虫：需连通企业 TDC 认证中心及系统网段
4. **权限要求**：普通用户权限即可（建议具备合规业务工作区目录的读写权限）。

---

## 4. 快速开始与操作流程

### 模式一：Web 桌面工作台模式（推荐）

1. **部署文件**：将 `VSE-WebUI.exe` 与 `VSE-ExcelWorker.exe` 放置在**同一目录**下（例如 `D:\VSE-Toolbox\`）。
2. **启动服务**：
   双击运行 `VSE-WebUI.exe`（或在终端执行）：
   ```cmd
   VSE-WebUI.exe
   ```
3. **访问界面**：
   打开浏览器访问：`http://127.0.0.1:5000`
4. **后台 Worker 联动**：
   在 Web 界面中通过 Excel 任务模块一键启动/停止 Worker，`VSE-WebUI.exe` 会自动调起同目录下的 `VSE-ExcelWorker.exe`。

---

### 模式二：终端交互 CLI 模式

适用于控制台交互与自动化脚本场景：

1. 打开 Windows Terminal / CMD，进入部署目录。
2. 运行终端工具箱：
   ```cmd
   VSE-Toolbox.exe
   ```
3. 按照数字菜单选项进行操作：
   - `[1] Deliverables`：项目交付物状态维护
   - `[4] Aras Cockpit`：EWO / PAA / NCR 报表抓取与导出
   - `[6] Excel Toolbox`：多工作簿合并、叠加与差异比对
   - `[7] TDC Reports`：数模审核与 SOR 流程报表导出

---

### 模式三：独立 Worker 命令行运行

适用于批处理作业或 Windows 计划任务：

1. **单次处理模式（run-once）**：
   ```cmd
   VSE-ExcelWorker.exe run-once --db data\vse_toolbox.db --root business=D:\ApprovedExcel
   ```
2. **常驻轮询模式（run）**：
   ```cmd
   VSE-ExcelWorker.exe run --db data\vse_toolbox.db --root business=D:\ApprovedExcel --interval 5.0
   ```
3. **优雅停机**：在轮询目录下创建 `--stop-file` 指定的文件，或按下 `Ctrl+C`。

---

## 5. 生产环境测试验收清单

请参照以下 10 项核心测试用例进行测试验收：

| 序号 | 测试场景 | 测试步骤与预期结果 | 状态 |
|---|---|---|---|
| **TC-01** | **独立启动验证** | 在未安装 Python 的干净虚拟机/机器上双击 `VSE-WebUI.exe`，控制台打印端口监听日志，`127.0.0.1:5000` 正常加载 Warm Cream 风格控制台。 | 待测 |
| **TC-02** | **安全目录白名单约束** | 提交源路径位于白名单外的任务，系统应直接拒绝，抛出安全越权异常（防止路径遍历与恶意重解析点攻击）。 | 待测 |
| **TC-03** | **同源双进程通信** | Web 界面点击“启动 Excel Worker”，检查任务管理器中成功拉起 `VSE-ExcelWorker.exe`，状态卡片由 `stopped` 切换为 `running`。 | 待测 |
| **TC-04** | **Excel 任务 CAS 租约并发** | 同时向 SQLite 插入 3 个任务，Worker 应按顺序原子竞争 `lease_token` 并依序成功执行，无脏写或重复执行。 | 待测 |
| **TC-05** | **工件下载与哈希校验** | 任务执行完成后，在 Web 界面下载生成的 `.xlsx` 文件，对比下载审计日志中的 SHA-256 与文件实际哈希一致。 | 待测 |
| **TC-06** | **超时租约自动回收** | 人工通过 `taskkill /F /IM VSE-ExcelWorker.exe` 模拟 Worker 进程崩溃，等待租约超时后再次启动 Worker，检查遗留任务被标记为 `stale` 并按重试策略恢复。 | 待测 |
| **TC-07** | **Aras ECM 数据查询** | 在 WebUI 或 CLI 中输入 Aras 凭据，执行 EWO / PAA 查询，确认表格正确脱敏并可导出 CSV/XLSX。 | 待测 |
| **TC-08** | **TDC 报表抓取与导出** | 执行 TDC 账号登录，拉取“数模设计审核”或“SOR 报表”，验证官方 XLSX 文件完整落盘在数据目录。 | 待测 |
| **TC-09** | **敏感凭据脱敏与 DPAPI** | 检查生成的日志文件、前端网络响应及数据库表，验证密码、Token、Session 等均被脱敏（`[REDACTED]`），凭据存入 Windows DPAPI 保险库。 | 待测 |
| **TC-10** | **优雅停机与资源释放** | 发送优雅停机信号（`POST /api/excel-worker/stop`），检查 Worker 在完成当前 Workbook 处理后正常释放 COM 对象并退出，无残留 `EXCEL.EXE` 僵尸进程。 | 待测 |

---

## 6. 常见问题排查 (FAQ)

### Q1: 运行 `VSE-WebUI.exe` 提示端口被占用？
- **原因**：默认 `5000` 端口被其他本地服务占用。
- **解决**：启动时使用环境变量指定端口，或使用命令行参数调整。

### Q2: Excel Worker 执行任务时提示 COM 错误或未响应？
- **原因**：Excel 弹出了授权激活对话框、正在编辑模式中或有模态对话框阻塞。
- **解决**：
  1. 手动打开一次 Excel 软件，确保许可已激活并关闭所有“首次运行配置”提示；
  2. 检查任务管理器中是否有卡死的 `EXCEL.EXE`，使用 `taskkill /F /IM EXCEL.EXE` 进行清理。

### Q3: 提示 `Approved root directory not found`？
- **原因**：安全白名单机制要求任务文件必须位于预先批准的根目录映射下。
- **解决**：启动 Worker 时通过 `--root ID=PATH` 传入正确的目录映射，且确保路径在物理磁盘上真实存在。
