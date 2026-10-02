# VSE Toolbox 架构诊断与核心重构方案

> 状态：Active
> 读者：User、Developer、Agent
> 权威来源：2026-10-01 对 `feature/scheduled-deliverables-overview-excel`（d15d0f2）的只读分析；执行以 `docs/PLUGIN_REFACTOR_PLAN_20261001.md` 为准；在线版（含图表）https://claude.ai/code/artifact/2f174f60-fe2f-4b83-b100-6461dd5ca642
> 默认读取：插件化重构的背景与论证，按需读取

## 结论速览

**建议动核心，但只动"壳"**：把 Web 层、数据归属和打包分发重建为"Python 宿主 + 特性插件 + Schema 驱动视图 + onedir 分层分发"，`services/` 下已经稳定、有测试的 Aras/TDC/Excel/认证集成原样保留，作为插件调用的能力层。用绞杀者方式分期推进，旧页面全程可用。

核心判断：改一个页面要 2~3 小时，主因不是"框架选错"，而是**系统里不存在"特性/页面"这个一等公民**。每个功能都散落在 5 个巨型共享文件里，所以每次改动都要穿透全栈。这一点靠局部封装无法根治，增量更新也无从谈起。

### 从代码推断出的上下文

| 项目 | 推断结果 | 依据 |
| --- | --- | --- |
| 分析基线 | `feature/scheduled-deliverables-overview-excel` 分支（2026-09-26，139 次提交） | `main` 仍停在 6 月 |
| 应用形态 | Windows 本地工具：`webui.py` 启动 Flask（127.0.0.1:5000）并打开系统浏览器；另有 Rich CLI、Excel Worker、TDC Probe | `README.md`、`PROJECT_MAP.md` |
| 技术栈 | Python 3.9+ / Flask 3 / SQLite / 原生 JS（无构建、无框架）/ pywin32 + xlwings / PyInstaller 单文件 | `requirements.txt`、`VSE-WebUI.spec`（只有 `EXE`，无 `COLLECT`） |
| 最痛文件 | `web/static/app.js`（15,932 行，33 次改动）、`core/db_manager.py`（5,246 行，30 次）、`web/app.py`（5,737 行，28 次）、`web/static/style.css`（8,382 行，26 次）、`web/templates/dashboard.html`（916 行，13 次） | `git log` 文件改动频次前五 |
| 已有约束 | 同事拿到的是 exe；公司电脑不能直接下 GitHub Release；接受 onedir；更新包外部构建、飞书分发、必须签名、只提示不强制 | 项目早期记录 |

历史教训：6 月 16 日已经推倒过一次（React 19 + FastAPI → CLI → 现在的 Flask + 原生 JS），之后 100 天内 `app.js` 从 87 行长到 15,932 行（平均每天约 158 行）。换框架而不建立模块边界，同样的问题会第三次出现。

## 1. 架构死结诊断与根本病因

改一个展示页要 2~3 小时，是因为一个页面在代码里没有自己的位置：它被拆成 7 片，分别嵌进 5 个所有功能共享的巨型文件，而且这些文件还在加速变大（2026-06-18 → 09-26：`app.js` 87 → 15,932 行，`app.py` 74 → 5,737 行，`db_manager.py` 237 → 5,246 行）。

### 新增一个展示页，今天要动哪些地方

1. `dashboard.html`：在顶栏加 `data-panel-link`，再手写一个 `<section>` 骨架。
2. `app.js`：加模块级状态变量（现有 54 个全局 `let`）；在 `handleHashChange` 的 3 条五层三元表达式链里各加一个分支，再加一条 `if (isXxx) loadXxx()`。
3. `app.js`：手写加载函数，重新实现请求序号防竞态、loading/error 状态、`ok !== true` 判断。全文件已有 48 处序号字段、82 处 ok 判断、40 处 `cache: "no-store"`。
4. `style.css`：8,382 行的全局样式，新类名容易和旧规则互相影响。
5. `web/app.py`：在 `create_app()` 里加路由。这个函数从第 2947 行一直写到文件末尾（约 2,800 行），86 个路由全是闭包。
6. `core/db_manager.py`：在一个 5,246 行的 `DatabaseManager` 类里加表、加方法、加迁移。全库只有一个 schema 版本；`form_key` 写在 SQL `CHECK` 白名单里，每加一个表单都要做一次**重建表迁移**（DECISIONS 2026-09-02）。
7. 测试：21 个测试文件里有约 330 条 `assert "某字符串" in js_text` 式的源码文本断言（`test_overview_web.py` 就有 133 条）。改个函数名或文案就会假红。

再加上 Vibe Coding 的特有成本：Agent 无法一次读完 1.6 万行的 `app.js`，只能 grep 后局部打补丁，漏掉的隐式依赖变成回归。

### 散弹式修改的实证：一个表单被写了 10 遍

`tdc_sor` 出现在 10 个生产文件里。`services/deliverable_form_analysis.py` 有至少 8 个以 form_key 为键的平行字典（`FORM_KEYS`、`_REPORT_BY_FORM_KEY`、`_SOURCE_BY_FORM_KEY`、`_SHEET_NAMES_BY_FORM_KEY`…），`app.js` 又有至少 6 个（`DELIVERABLE_FORM_TABS`、`DELIVERABLE_FORM_FILTER_LABELS`、`DELIVERABLE_FORM_CHART_TITLES` 等），再加一条 SQL `CHECK`。提交 `c6286d5` 新增这个表单时改了 7 个生产文件，+1,417 / −269 行。6 个交付物表单页其实是同一种页面，**Schema 已经隐式存在，只是被拆成了 10 份**。

### 哪些能局部修，哪些是先天缺陷

| 痛点 | 根因 | 分类 | 处理方式 |
| --- | --- | --- | --- |
| 一个表单要改 10 处 | 领域知识没有单一所有者 | 局部可修 | 合并为一份 Python FormRegistry，经 API 下发前端 |
| 改文案就假红 | 测试绑定源码文本而非行为 | 局部可修 | 改写为 API 契约测试 + DOM 行为测试 |
| 每页重写请求/竞态/错误样板 | 没有公共数据访问层 | 局部可缓解 | 抽 `apiClient` + `useResource` |
| `app.py` 路由堆积 | 86 个闭包共享 `create_app` 内的依赖 | 半局部 | 拆 Blueprint 前必须先引入显式服务容器 |
| 新页面必须改中心文件 | 前端没有模块边界 | **先天缺陷** | 宿主 Shell + 页面注册契约 |
| 特性无法拥有自己的数据 | 一个类拥有全部表和单一 schema 版本 | **先天缺陷** | 按插件划分表与迁移版本 |
| 任何改动都要全量发布 | 分发单元 = 整个 onefile exe | **先天缺陷** | onedir + 签名插件包 |
| 新功能注册散落各处 | 宿主与特性之间没有生命周期契约 | **先天缺陷** | `register(host)` 单入口 |

## 2. 核心重构立项论证

### ① 必要性

- **外包一层**：新页面依然要注册进 `handleHashChange` 和 `dashboard.html`，依然读写全局状态，数据依然进 `DatabaseManager`，发布依然跟整个 exe 走。耦合点一个没少。
- **局部封装**：没有宿主-插件契约，拆出来的只是多个共享全局作用域的 `<script>`，隐式依赖变成加载顺序依赖，更难排错。
- **三条致命缺陷**：运行时没有"特性"实体；数据所有权集中；分发粒度是整个应用。增量更新要求改第三条，而第三条依赖前两条先改。

### ② 收益量化（估算，S1 实测验证）

| 场景 | 现在 | 重构后（估算） |
| --- | --- | --- |
| 新增纯展示页 | 2~3 小时 | 20~40 分钟 |
| 新增有自定义交互的页面 | 2~3 小时以上 | 60~90 分钟 |
| 给已有表单加字段、改标签 | 约 1 小时 | 5~15 分钟 |
| 新增一个外部表单数据源 | 7 个文件、约 1.4k 行、一次重建表迁移 | 1 个插件目录，无重建表 |
| 发给同事 | 重新打整个 exe、全量回归 | 一个 KB~MB 级签名插件包，只回归该插件 |
| Agent 每次任务要读的代码 | `app.js` 1.6 万行 + `app.py` 5.7k 行 | 一个插件目录（目标 ≤ 1,500 行）+ 宿主 SDK 说明 |

ROI 粗算：按每周 3~4 次页面级改动、每次省 1.5~2 小时计，每周省 5~8 小时；前两期投入 60~80 小时，约 10~14 周回本。

### ③ 技术选型

| 层 | 选择 | 不选其他的理由 |
| --- | --- | --- |
| 前端 | 无构建：随包内置 Preact + htm，每个插件交付一个 ES Module（2026-10-01 用户确认） | React + Vite 需要插件各自构建或 Module Federation，且 6 月已回退过一次；原生 JS 没有组件与状态模型 |
| 视图 | Schema 驱动 + 自定义组件兜底 | 纯手写会产生 6 份相似代码；纯低代码不够灵活 |
| 协议 | 固化现有 `{ok, data, error}` 信封；插件路由在 `/api/p/<id>/` | GraphQL / WebSocket 对本地单用户工具无收益 |
| 后端 | 每个插件一个 Flask Blueprint，依赖由 `HostContext` 注入 | 换 FastAPI 收益小、成本高 |
| 数据 | 插件拥有自己的表与迁移版本；公共表只经宿主服务访问 | ORM 不解决归属问题 |
| 分发 | onedir + `plugins/` 目录；插件为签名 zip | onefile 无法局部替换 |

### ④ 代价与破坏半径

| 既有资产 | 处置 | 风险 |
| --- | --- | --- |
| `services/` 41 个文件 | 原样保留 | 低 |
| `core/` 凭据、脱敏、Excel Worker、归档、诊断 | 升级为宿主服务 | 低 |
| `web/app.py` 86 个路由 | 按组迁入 Blueprint，旧路径保留别名 | 中 |
| `core/db_manager.py` | 按领域拆 repository，表名不变、不搬数据 | 中高 |
| `app.js` + `style.css` + `dashboard.html` | 按页面绞杀，最后删除 | 高 |
| 约 330 条源码文本断言 | 随页面迁移改写 | 中 |
| `*.spec` 与 CI | onefile 改 onedir，增加插件打包与签名 | 中 |

主要技术风险：冻结环境下插件只能用宿主已打包的库；签名密钥管理；过渡期双前端并存；整体投入约 4 个双周 Sprint。

## 3. 目标架构蓝图

- **宿主（Host，稳定、少改）**：生命周期、`PluginRegistry`、`HostContext`（数据库、凭据、任务运行器、归档存储、调度、脱敏、诊断）、HTTP 内核（信封、错误映射、只允许本机写入）、前端 Shell（导航、hash 路由、主题、会话指示、原位登录、任务抽屉）、UI Kit 与 Schema 渲染器。
- **插件（Plugin，高频改）**：自己的路由、查询、表与迁移、视图 Schema、可选自定义组件、测试。
- **能力层（现有 `services/`）**：保持不变，插件按需调用。
- **硬规则**：插件之间不互相引用，不直接写公共表；CI 用边界测试保证。

```text
plugins/deliverable_forms/
  plugin.json        # id、version、host_api、导航入口、依赖声明
  backend.py         # def register(host): 挂 Blueprint、调度任务、归档连接器
  registry.py        # 6 个表单的唯一定义
  queries.py         # 只负责取数
  views.py           # 视图 Schema
  migrations/001_init.sql
  ui.js              # 可选：自定义单元格或整页组件
  tests/
```

页面开发分三档：L1 纯 Schema（查询函数 + 视图描述）；L2 Schema + 插件自注册的小组件；L3 自定义 Preact 页面，仍使用宿主的 `useResource` 与 UI Kit。

增量发布（onedir）：

```text
VSE-Toolbox/
  VSE-WebUI.exe
  _internal/                 # 宿主运行时
  plugins/
    deliverable_forms/1.4.0/
    deliverable_forms/1.3.2/ # 上一版，用于回滚
    active.json
  updates/staging/
```

外部构建机打 `.vsepkg`（manifest + 文件 + sha256）并用 Ed25519 签名 → 飞书分发 → "设置 → 更新"导入、验签、检查 `host_api` → 提示重启生效 → 重启时切换 `active.json`，自检失败自动回滚。宿主包低频，需要独立的小更新器替换 exe。

## 4. 绞杀者迁移与兼容策略

旧 `app.js` 作为 legacy 整体挂在新 Shell 下，逐页迁出。

- 路由：Shell 先匹配已迁移路由，其余交给旧 `handleHashChange`；现有深链保持不变。
- API：新路径在 `/api/p/<id>/`，旧路径保留别名到 legacy 删除。
- 数据：表名不改、数据不搬；schema v14 冻结为基线，之后走插件迁移版本。
- 回退：每个迁移页面在设置里保留"使用旧版页面"开关一个版本周期。
- 样式：旧样式放进 `@layer legacy`，新样式分层加前缀。
- 测试：只在页面迁移时改写该页的文本断言。

## 5. 参考范例

| 项目 | 对应哪一块 |
| --- | --- |
| [CTFd](https://github.com/CTFd/CTFd) | Flask 宿主 + 插件目录（`load(app)`），本方案主参考 |
| [calibre 插件机制](https://manual.calibre-ebook.com/creating_plugins.html) | 冻结桌面程序导入 zip 插件、重启生效，本方案主参考 |
| [VS Code Contribution Points](https://code.visualstudio.com/api/references/contribution-points) | 声明式注册导航与视图，本方案主参考 |
| [Datasette](https://github.com/simonw/datasette) + [pluggy](https://github.com/pytest-dev/pluggy) | 宿主与插件的 hook 契约（只借鉴思路） |
| [Home Assistant integrations](https://developers.home-assistant.io/docs/creating_integration_manifest) | 每个功能一个目录 + manifest |
| [Grafana 插件签名](https://grafana.com/docs/grafana/latest/administration/plugin-management/plugin-sign/) | 签名与兼容性检查 |
| [amis](https://github.com/baidu/amis) | Schema 配置词汇（不直接引入） |
| [htm](https://github.com/developit/htm) + [Preact](https://preactjs.com/) | 无构建前端 |
| [tufup](https://github.com/dennisvang/tufup) | 宿主包更新（推迟） |
| [minisign](https://jedisct1.github.io/minisign/) | Ed25519 签名 |
| [Strangler Fig Application](https://martinfowler.com/bliki/StranglerFigApplication.html) | 绞杀者迁移 |
