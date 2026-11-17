# VSE Toolbox v2 发布兼容矩阵（冻结稿 2026-10-31）

> 状态：**冻结**（W0-02）。发布决策以此矩阵为准；修订需 lead 同意并记录。
> 已核验事实基于 `tools/release.py`（102 行）与 `vse_boot/packages.py`。

## 1. 已核验的打包能力（2026-10-31）

| 事实 | 证据 |
|---|---|
| `tools/release.py` 构建签名 app 包 `vse-app-<version>.vsepkg` | release.py docstring + `build_app_package` |
| app 包内容 = `core/ services/ host/ web/ plugins/ webui.py tools/excel_worker_cli.py` **全量**，非插件差分 | release.py L7-8 |
| 包 manifest `format=2, kind=app`，带 `requires.runtime` 运行时标签 | vse_boot/packages.py L12, L143 |
| 运行时标签不匹配 → 安装拒绝并提示先装新运行环境 | packages.py L236-237 |
| 验签入口 `verify_app_package(data, keys, runtime_tag=...)` | packages.py L191 |
| 插件包 `.vsepkg`（kind=plugin）与 app 包是两种格式 | `tools/build_plugin_pkg.py` vs `kind=app` |
| v2 启动器（`vse_boot`）支持双击安装、托盘、增量应用、失败回滚 | CURRENT_STATE 2026-10-28 条目 |
| 签名密钥为 TEST-ONLY（`dist/v2-test/keys`，不入库不外发） | AGENTS.md / 硬约束 |

## 2. 发布物 → 触发条件（冻结规则）

| 变更内容 | 发布物 | 命名 | 备注 |
|---|---|---|---|
| `core/ services/ web/ plugins/ webui.py host/` 任一变化（已验证与现有运行时兼容） | app 包 | `vse-app-<semver>.vsepkg` | 本阶段常规通道；每波集成后打一个唯一版本 |
| `vse_boot/`、启动器 exe、Python 运行时、PyInstaller spec、新增顶层进程、`RUNTIME_TAG` 变化 | **整包 onedir zip** | `VSE-Toolbox-v<semver>-test.zip` | 走 W17-02 真机验证后再发 |
| 单插件功能 | 仍可用插件包 `.vsepkg`（kind=plugin） | `vse-plugin-<id>-<version>.vsepkg` | 仅当该插件与宿主接口无变化 |
| 纯文档 / 测试 | 不发布 | — | 随下次发布携带 |

**硬规则**：

1. 宿主接口（`host.context` 字段、服务集、`table_prefix`/`migrate` 语义）或运行时变化 → 一律整包，
   禁止用 app 包携带宿主层破坏性变化。
2. 不假定 bundle、文件级差分更新等草案能力已实现（REQUIREMENTS A6 的 bundle 部分本阶段不做）。
3. 正式代码签名与信任链落实前，所有包标注「内部测试包」，签名用 TEST-ONLY 密钥。
4. 每个发布物记录：版本、buildId（`<date>-<short-sha>-<slug>`）、sha256、验证命令输出。
5. `dist/v2-test/updates/` 为 app 包唯一暂存目录；dist/ 不入库。

## 3. 生产操作指南差异（待 W19-02 修订）

`docs/PRODUCTION_OPERATION_GUIDE.md` §7 现存三条旧规则与 v2 现状不符：

1. §7.2「发布插件包」未覆盖 app 包流程（`tools/release.py` + 双击安装）；
2. §7.3「宿主升级（手工替换 onedir）」——v2 启动器已支持双击安装整包与自动回滚，手工替换降级为兜底；
3. §1 交付物清单未列 app 包与验签命令（`verify_app_package`）。

处理：本阶段发布一律按本矩阵执行；W19-02 统一修订指南（含中文截图手册同批）。
在此之前，任何人按旧指南操作产生的差异以本矩阵为准。

## 4. 版本与渠道基线（2026-10-31）

- 分支 `refactor/ux-v2`；app 包链 2.3.0 → 2.3.4（TEST-ONLY 签名，sha256 记录见 memory）。
- 2.3.3 / 2.3.4 均**未真机验证**（如实标记，待 W17-02/W1-03）。
- 本计划首个基线包：W0 集成提交后重新对账（包 ↔ 提交哈希映射记入 memory）。
