# 真实浏览器关键路径夹具（DSH-V2-08）

> 状态：已实现（W2，DSH-V2-08）。范围：`tests/browser/v2_fixtures.py`、
> `tests/browser/test_v2_user_paths.py`、本文件。生产代码零改动。
> 依赖口径：**不新增任何生产/测试依赖**，只用本机已有浏览器 + Node 内置能力。

## 1. 这份夹具解决什么

`tests/browser/test_browser_channel.py` 只证明「浏览器能起无头进程、能 dump DOM」。
它不能证明：

- 页面里的 ES Module 真的加载并执行（`shell.js → /api/host/manifest → 插件页面模块`）；
- 启动票据 `?boot=` 真的换到了会话 Cookie；
- 用户真实点击「下一步」后 DOM 步骤真的变化；
- 报告类插件页面真的把数据渲染成元素；
- 浏览器 console 没有 error 级日志。

本任务用 **Edge/Chrome 的 DevTools 协议（CDP）** 补齐这些路径：真实 DOM、
真实 ES Module、真实鼠标事件与文本输入，断言对象是渲染结果而不是源码文本。

## 2. 依赖与环境

| 依赖 | 要求 | 说明 |
|---|---|---|
| 浏览器 | 本机 Microsoft Edge 或 Google Chrome（Chromium ≥ 112，支持 `--headless=new`） | 复用 `tests/browser/test_browser_channel.py::find_browser_channel` 探测；不下载、不安装 |
| Node.js | ≥ v22 | 只用内置全局 `WebSocket` / `fetch`；不 `npm install`、不联网 |
| Python 侧 | 现有 `requirements.txt` | 不用 Playwright / Selenium / websocket-client |
| 外部系统 | 不访问 | Aras / TDC / 帆软 / 邮件全部不参与，数据只来自临时 SQLite |

显式指定路径（可选）：

```powershell
$env:VSE_BROWSER_PATH = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$env:VSE_NODE_PATH    = "C:\Program Files\nodejs\node.exe"
```

- `VSE_BROWSER_PATH` 指向**不存在**的文件时，夹具不会静默回落到自动探测，而是
  按「显式指定错了」如实跳过并写明路径；
- `VSE_NODE_PATH` 同理；
- 两者都不是生产环境变量，只影响测试进程。

## 3. 怎么跑

```powershell
python -B -m pytest -p no:cacheprovider tests/browser/test_v2_user_paths.py -q -rs
```

本机实测（Edge + Node v26.8.2）：`4 passed`，多次运行 5.9–7.2 秒，退出码 0，
整文件 < 3 分钟。无浏览器/无 Node 时输出 `4 skipped`，退出码仍为 0（pytest 语义），
**所以 release 门禁不能只看退出码**，见第 7 节。

## 4. 夹具 API（`tests/browser/v2_fixtures.py`）

| fixture | 作用 |
|---|---|
| `browser` | 启动测试专属浏览器（临时 profile + `--remote-debugging-port=0`）与 Node CDP 驱动；缺失时 `pytest.skip` 并写明缺什么 |
| `page` | 页面驱动 `BrowserPage`（下表） |
| `server` | 进程内真实 `create_app` + werkzeug `make_server` 的 127.0.0.1 随机端口服务 |

`server` 依赖 `browser` 是有意为之：启动票据 TTL 只有 10 秒（`web/security.py`），
浏览器必须先就绪，票据签发后才能立刻在用例里导航交换——**不放宽生产 TTL**。

`BrowserPage` 公共方法：

| 方法 | 说明 |
|---|---|
| `goto(url)` | `Page.navigate` 并等到 `document.readyState === 'complete'` |
| `eval(expression)` | `Runtime.evaluate`（`returnByValue`），返回可 JSON 序列化的值 |
| `wait_for_selector(selector)` | 轮询 `document.querySelector` |
| `wait_for_function(expression)` | 轮询任意页面条件（可返回真值） |
| `click(selector=None, text=None)` | 目标中心派发真实 `mousePressed/mouseReleased`；`text` 按可见文本匹配 |
| `type_text(selector, text)` | 真实点击聚焦 + `Input.insertText`（失败时逐字符回退） |
| `console_errors()` | 浏览器 error 级日志（`Runtime.consoleAPICalled` / `Runtime.exceptionThrown` / `Log.entryAdded` 三路合并） |
| `clear_console()` | 清空已收集日志 |
| `cookies(urls)` | `Network.getCookies`（能读到 HttpOnly 会话） |
| `snapshot()` / `diagnose(message)` | DOM 片段 + 页面文本 + console 日志；票据统一脱敏 |

断言辅助：`assert_no_console_errors(page, allow=(...))`。`allow` 只放行**已列明**
的已知项（子串或编译好的正则），不会把「有 4xx 就整体忽略」当成通过。

## 5. 覆盖的关键路径

| 用例 | 路径 | 关键断言 |
|---|---|---|
| `test_boot_ticket_establishes_session_and_loads_shell` | `/?boot=<票据>` → 外壳 ES Module → 导航 | `.wb-page` 渲染、`nav.hc-nav a[data-plugin-link]` 含「今天/报告」、`vse_session` Cookie 存在且 `HttpOnly` + `SameSite=Strict`、`document.cookie` 读不到、`location.search` 已清理、默认路由 `workbench` |
| `test_wizard_advances_through_real_clicks` | 首次使用向导 | 真实点击「开始 → 跳过登录 → 输入车型 → 下一步」；DOM 标题从「登录公司域账号」→「新建或配置项目」→「选择要跟踪的交付物」；步骤条 4 个点亮；`localStorage['vse.wizardState'].step === 3` |
| `test_project_overview_report_entry_renders` | `#p/project-overview/status` | 概览 tab（项目状态/交付物明细/主计划维护）、时间轴标题 `F610S`、主计划节点 ≥ 1、交付物进度环 ≥ 1、无加载失败区块 |
| `test_sign_daily_report_entry_renders` | `#p/sign-daily/report` | 标题「3D 单签署日报」、「一键生成」按钮、无错误态 |

向导用例里点「下一步」会真实提交 `POST /api/p/workbench/projects`。单项目环境
（非启动器托管）按产品契约返回 `409 NotManaged`，浏览器把它记为一条 network
error；这是**预期业务分支**，而且反证写请求穿过了会话 + Origin 防线（不是
401/403）。该条已在测试里用精确正则列明：

```
status of 409 (CONFLICT) (http://127.0.0.1:<port>/api/p/workbench/projects)
```

其它任何 4xx/5xx console error 仍然会让用例失败。

## 6. 离线与安全边界

- 服务只监听 `127.0.0.1`；浏览器加
  `--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1`，从浏览器层拒绝解析
  除回环外的任何主机——**不访问真实内网/外网**；
- 浏览器 profile 是 `tmp_path` 下的临时目录，teardown 删除；不碰用户真实配置；
- 启动票据由 `web.security` 真实签发（测试进程生成的合成值），不写入日志/文档：
  - `LiveServer.token` 设了 `repr=False`，pytest 失败报告不会打印；
  - werkzeug 访问日志在夹具内降到 `WARNING`，`GET /?boot=<票据>` 不进捕获日志；
  - 诊断里的 URL 一律 `boot=<redacted>`；
- teardown 只结束**本测试自己启动**的浏览器：先发 CDP `Browser.close` 让整棵进程树
  自行退出，仍在运行时才按**本进程 PID 的进程树**（`taskkill /PID <pid> /T /F`）结束；
  绝不按进程名匹配任何其他 Edge/Chrome；
- 不使用真实凭据、真实数据库、生产环境变量；测试数据全部来自 `tmp_path` 下的
  临时 SQLite。

## 7. release 门禁接线（必须由 DSH-V2-06 落地）

`tools/wave_gate.py` 的 **release 模式**由 DSH-V2-06 引入（本任务不改它）。
基线 1619141 的 `wave_gate.py` 只有 `--focus/--skip-full/--out`，浏览器通道缺失时
只打印 `已跳过 (原因)`，**不会让门禁失败**；`--focus` 模式还会隐含跳过全量回归。

release 模式必须把本文件纳入并满足：

1. 浏览器步骤**显式**运行本文件，产出 junit；
2. junit 里 `skipped > 0`、`failures > 0`、`errors > 0`、**或报告文件缺失** → 该步骤
   `FAIL`（release 下 SKIP 视为失败）；
3. `browser_channel.status != "verified"` → 门禁 `FAIL`；
4. 只有 `tests > 0` 且 `skipped=0, failures=0, errors=0` 才允许 `PASS`。

建议的浏览器步骤命令（junit 路径由 V2-06 决定，这里给一个可用示例）：

```powershell
python -B -m pytest -p no:cacheprovider tests/browser/test_v2_user_paths.py `
  -q -rs --junitxml=.runtime/wave-gate/browser-junit.xml
```

对应的 junit 判定要点（伪代码）：

```python
suite = junit_root.find(".//testsuite")
if suite is None:                       # 报告缺失
    step.status = "FAIL"
elif int(suite.get("skipped", 0)) > 0:  # 无浏览器/无 Node 的 SKIP
    step.status = "FAIL"
elif int(suite.get("failures", 0)) or int(suite.get("errors", 0)):
    step.status = "FAIL"
else:
    step.status = "PASS"
```

注意：**全 SKIP 时 pytest 退出码是 0**，只看退出码会把「没有浏览器」误判成通过。
这也是 release 模式必须解析 junit、并把 `browser_channel.status` 纳入判定的原因。

V2-06 落地时需要的后续接线（本任务未改 `tools/wave_gate.py`）：

- 在 `execute_wave_gate` 增加浏览器步骤（或在 release 模式下复用 `--focus`
  目标并强制读取 junit）；
- `probe_browser_status` 的 `skipped` 在 release 模式映射为 `FAIL`；
- 结构化报告里保留 `browser_channel.status/verified/executable/reason` 与
  junit 的 `tests/skipped/failures/errors` 计数；
- CI/发布机需要 Node ≥ v22；缺失时 release 按设计失败（安装 Node 或设置
  `VSE_NODE_PATH`），不得静默跳过。

## 8. 超时与失败定位

- 单步 CDP 命令 ≤ 30 秒（`DEFAULT_STEP_TIMEOUT_MS`）；
- 单条用例的浏览器操作总预算 120 秒（`PAGE_TIME_BUDGET_SECONDS`）；
- 浏览器启动 ≤ 30 秒；
- 整文件目标 < 3 分钟（本机实测约 7 秒）。

失败时断言消息里带：当前 URL（票据脱敏）、`#plugin-host` DOM 片段、页面文本、
以及浏览器 console error 日志。`pytest-timeout` 不在依赖里，因此没有
`pytest.mark.timeout`，超时由上述三层实现。

## 9. 已知限制

- 只跑无头 Chromium（Edge/Chrome）；不覆盖 pywebview 独立窗口、托盘、打包后的
  exe（那是 DSH-V2-35 等任务的范围）；
- 使用本机探测到的第一个浏览器通道，不做 Edge/Chrome 交叉矩阵；
- 不截图、不做像素对比；断言基于可访问性/DOM 语义（aria-label、角色、可见文本）；
- 不做真实网络与真实凭据验证；离线边界由 `--host-resolver-rules` 与回环服务保证；
- 本文件是**局部**证据，不能替代全量回归（基线：3582 passed / 7 skipped / 2 warnings）。
