# M1 实施计划：新底座（分层安装 + app 级增量更新）

> 依据：[ARCHITECTURE.md](ARCHITECTURE.md) §3–§5、[M0_FINDINGS_20261028.md](M0_FINDINGS_20261028.md) · 分支 `refactor/ux-v2`

## 关键决策（实现期）

1. **更新内核 `vse_boot` 放在 L1 运行时层，不放在 app 包里。** 负责校验、安装、试用、回滚的代码自身必须稳定：如果它随 app 一起更新，一个坏的 app 包就可能把更新链路也弄坏。`vse_boot` 只依赖标准库和 `cryptography`，**不 import 任何 app 代码**（`core/`、`host/`、`web/`…）。它只随 runtime 包更新，一年 1–2 次。架构 §4.3 中"由 L2 引导脚本完成"据此修正为"由 L1 的 `vse_boot` 完成"。
2. **监督进程 + app 子进程。** `python -m vse_boot` 是监督进程，app（现有 Flask 应用）作为子进程运行。试用版启动失败或健康检查不过时，监督进程结束子进程，切回上一版本再启动一次。这样不需要原生 L0 也能做到崩溃安全；L0 启动器（Spike S2）以后只需要执行 `pythonw -m vse_boot`。
3. **M1 只做 app 级版本化。** 插件级更新继续沿用现有的 `host/updates.py`（format 1 `.vsepkg`，进程内失败回滚已有测试）。v2 包格式（format 2）先只实现 `kind: "app"`，`pack`/`bundle` 在 M4 拆包时再加。
4. **数据目录由监督进程显式指定。** 环境变量 `VSE_DATA_ROOT` 优先于 `core/runtime_paths.app_root()` 的推断，这样 app 代码搬进 `app/<版本>/` 后数据仍在 `<安装根>/data`。
5. **窗口**：M1 先用 Edge `--app`（零新依赖，M0 已确认有 Edge 144），使用独立的用户数据目录；pywebview、托盘和一次性令牌放在 M1 的第 2 片。

## 接口

```
<安装根>/
  runtime/            L1（含 vse_boot）
  app/<版本>/          L2：core/ services/ host/ web/ plugins/ webui.py tools/excel_worker_cli.py app.json
  state/boot.json      试用/生效/上一版本 + 事件
  state/staging/       已校验、待安装的包
  state/db-snapshots/  迁移前快照（保留 3 份）
  state/instance.json  运行中实例的端口（第二次启动时用它唤起已有窗口）
  data/                与现在的 data/ 相同
```

| 模块 | 职责 |
|---|---|
| `vse_boot/layout.py` | 安装根下各目录的定位 |
| `vse_boot/state.py` | `boot.json` 原子读写；`install_staged → select_for_boot → commit / abandon`；手动 `rollback`；只保留当前版本和上一版本两个目录 |
| `vse_boot/packages.py` | format 2 构建、校验（签名 → 清单 → 逐文件 sha256 → 路径安全 → 体积上限 → Python 版本）、暂存 |
| `vse_boot/dbsnap.py` | SQLite 在线备份快照与恢复 |
| `vse_boot/discover.py` | 扫描文件夹中的 `.vsepkg`，返回比当前版本新、且签名有效的包（只看后缀和签名） |
| `vse_boot/supervisor.py` | 启动序列：单实例 → 安装暂存包 → 选版本 → 快照 → 启动子进程 → 健康检查 → 生效 / 回滚重试 → 打开窗口 |
| `vse_boot/app_main.py` | 子进程入口：把 app 目录插到 `sys.path` 最前，调用 `webui.main` |
| `tools/release.py` | 从仓库构建签名的 app 包，检查 8 MB 体积上限 |

## 验收（本片）

- 聚焦测试：`tests/test_vse_boot_*.py`、`tests/test_release_tool.py`、`tests/test_runtime_paths.py`。
- 端到端（开发机）：用 `tools/release.py` 构建 2.0.0 和 2.0.1 两个包 → 暂存安装 → `python -m vse_boot run` 启动并通过健康检查 → 再装一个故意启动失败的 2.0.2 → 自动回到 2.0.1。
- 回归：`tests/test_plugin_updates.py`、`tests/test_plugin_host.py` 不受影响。

## 进度（2026-10-28）

**第 1 片已完成**：`vse_boot/`、`tools/release.py`、`VSE-Launcher.spec`、`tools/build_v2_test_install.py`、`tools/e2e_v2_test_install.py`。

- 单元测试 36 项通过；全量回归 3382 passed / 6 skipped；端到端（真实 exe + 真实 app）14/14。
- 代码评审（high）发现 10 项问题，已全部修复并补了测试：试用崩溃后未恢复快照、启动器被结束后 app 成为孤儿进程、在「下载」里运行会把「下载」当成安装根、快照依赖手动声明迁移、`boot.json` 损坏后无法启动、日志覆盖、运行时标签取自打包机、坏的暂存包阻塞启动、构建慢、扫描时重复校验。端到端测试又发现 1 项：损坏的包会弹出阻塞的错误框（已修复）。
- 产物：`dist/v2-test/`（启动器加运行时 95 MB；app 包约 1 MB/个）。签名密钥是**测试专用**的。

**第 2 片已完成**：
- 托盘（`vse_boot/tray.py`，pystray）：打开 / 检查更新 / 重新启动 / 退出；更新生效或回滚时弹出托盘提示。
- 监督进程改为可重启循环：设置页按钮和托盘「重新启动」走同一条重启请求；重启时沿用端口，已打开的窗口刷新即可；app 意外退出时最多自动重启 2 次；`quit` 请求正常退出。
- 双击 `.vsepkg`（`vse_boot/association.py`，只写 HKCU）：校验 → 提示框 →（运行中）重启完成更新 /（未运行）启动。
- 设置 →「程序与插件更新」新增「程序更新」卡片（`plugins/settings/static/app-updates.js` + 插件路由 `/api/p/settings/app-updates*`）：显示当前/上一版本，列出「下载」里发现的新版本（签名有效），「安装并重启」，「回到上一版本」，安装/生效/回滚记录；重启后页面自动刷新。
- 验证：单测 + 路由测试 52 项；全量回归 3398 passed；端到端 17/17；真实界面点击「安装并重启」「回到上一版本」均实测通过。实测还发现 1 个问题并修复：回滚后无法再次升级到上一版本。

**第 3 片（下一步）**：一次性令牌 → HttpOnly cookie（三种窗口退路通用）、开机自启开关、pywebview 原生窗口（Edge `--app` 作为退路）、L0 原生启动器选型（Spike S2）。
