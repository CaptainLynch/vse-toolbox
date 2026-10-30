# PR #3 独立审查与 Windows 回归

状态：独立代码审查与本机 Windows 回归完成；当前不建议直接合并。两处继承的取证缺陷须补修，Windows 校验与新增守卫断言须稳定通过。

## 对象与边界

- PR：CaptainLynch/vse-toolbox#3，`claude/restore-plugin-parity` → `refactor/plugin-host`。
- 固定 head：`f5b0df0b25b29693bdaeec1baf9223f0741ad187`；固定基线：`d0dd01d0b6da4f8f3f60587adfb8d434f8876113`。
- 审查工作树：`C:/Users/Lynch/.codex/worktrees/pr3-windows-review/vse-toolbox`。
- 基线工作树：`C:/Users/Lynch/.codex/worktrees/pr3-windows-baseline/vse-toolbox`。
- 环境：Windows、Python 3.12.10、Chrome/Playwright；专用 venv 使用系统已有依赖，另装 pytest-xdist 与 Playwright。
- 直接审查恢复的取证/取消/缓存/签名、范围剔除、完成口径、费用解析、归集规则、插件前端状态与筛选。测试使用隔离数据库与合成上游；未请求真实公司上游。
- 未修改 PR 产品源码、未合并/推送/发布，也未对外提交审查评论。

## 应在合并前修复的发现

### R1 / P2：后台取证的轮询和结果读取没有真正的截止时间

位置：`plugins/project_overview/static/deliverable/discovery.js:81,100,149`。

202 握手成功后会清除原 AbortController 定时器，调用 `waitForTask` 又不传 signal。轮询的 deadline 只在两次请求之间检查；某一次 `/api/tasks/<id>` 的 fetch 或 JSON body 一直不返回时，不能走到下一次 deadline 检查。任务成功后的 `/result` 同样没有截止时间。

表现：向导一直停在抓取状态，开始按钮与诊断轮询让路标志不能恢复；界面宣称的 15 分钟总上限失效。短时限复现把任务上限设为 50ms，状态请求、结果请求分别挂住，300ms 后两者仍未结束，且相应 fetch 都没有 signal。

建议：为完整后台阶段建立独立 deadline/AbortController，覆盖状态 fetch、响应 body、结果 fetch；到时统一退出并恢复向导状态，按明确策略协作取消任务。补“状态请求挂住”和“结果请求挂住”行为断言，不能只测服务器持续返回 running 的情况。

证据：`.runtime/pr3-windows-review/repro-discovery-hang.mjs`、`repro-discovery-status.log`、`repro-discovery-result.log`。这是 PR 恢复请求通道中的问题。进一步核对旧顶端 e2c58a3 的 app.js：waitForTaskCompletion 及 fetchTaskResult 也采用无截止的单次 fetch；缺陷从旧实现继承，不应归咎于此次前端重写新造的回归。

### R2 / P2：过期取消令牌可能取消后来启动的任务

位置：`web/app.py:5173-5197`，关联 `5056` 注册表及 `5153` 令牌释放。

令牌查不到时，取消端点仅按 deliverable_id 找当前后台任务，不验证它与该令牌是否属于同一请求。旧请求 A 的 202 响应若延迟/丢失，A 已完成，另一个页面已启动新任务 B，随后 A 的截止处理发来旧令牌，会把 B 取消。

表现：用户新发起的取证莫名显示取消；参数哈希不同也不能阻止这一情况。合成 API 复现：仅登记 NEW-TASK-B/NEW-QUERY-B，发送未登记的 old-request-A，返回 200/cancelled=true/taskId=NEW-TASK-B，runner 实际收到了取消 B 的调用。

建议：后台受理时保存 token 与 taskId/查询身份的关联，持续到 worker 实际退出；只取消该令牌所属任务，未知/过期令牌返回 not_running。保留“未收到握手时能取消原任务”的覆盖，并新增“旧令牌不能取消新任务”的断言。

证据：`.runtime/pr3-windows-review/test_cancel_identity_repro.py`、`cancel-repro.log`。进一步核对旧顶端 e2c58a3 的 web/app.py：同样采用按交付物回落并 runner.cancel_task(entry[task_id]) 的逻辑；这是本次恢复继承的旧缺陷，不应归咎于 Claude 新造的回归。

## 已确认的基线问题与验证缺口

### B1 / P2：页签切换失败后应用筛选丢失条件（基线已存在）

位置：`plugins/project_overview/static/deliverable/form-analysis.js:811,851,872,934`。

切换失败时，activeTab 已是新页签，界面继续展示并编辑旧 view.tab 的 shown 状态；点击“应用筛选”却由 reload/load 读取新 activeTab 的条件。

实浏览器复现：数模“项目状态”切到“数量趋势”时模拟 view=500；解锁后输入 REVIEW-KEYWORD 并应用，请求为 `/view?trendLimit=30`，不含 keyword。PR 和基线均复现同一行为，因此不计为 PR 新引入回归。建议恢复到最后成功页签或把显示页签和请求的状态绑定一致，并补失败后真正应用条件的断言。

证据：`test_review_repro.py::test_filter_after_failed_tab_switch`、`repro-browser.log`；`test_baseline_repro.py`、`baseline-repro.log`。

### B2：新增浏览器测试的交互守卫断言存在时序依赖

`test_view_timeout_unlocks_interaction_and_offers_retry` 在 Windows 定向测试及单独复跑都在 blocked-count 断言失败。加长截止时间至 5000ms 仍可见 locked=true 而首次点击计数为空，排除了 600ms 太短这一单独解释；守卫用 useEffect 安装，与 DOM 锁定属性的出现并非同一时刻。两种截止时间下再等 200ms 点击，locked 仍为 true，blocked-count 都变为 2。确认是属性已更新、监听器尚未安装的窗口；守卫本身在基线中已用 useEffect，但新增断言只等待 DOM 属性，未等待监听器就绪，不能把该失败解释成云端已有的四项 Windows 专属失败。建议让锁定 UI 与守卫安装同时生效，并为断言建立明确就绪条件。

定向测试另外一次 `test_wizard_discards_background_result_with_foreign_params_hash` 在等待政策面板时超时，日志出现 database is locked；该用例单独重跑及最终全量都通过。初次结果与复跑结果分别保留，不能通过重跑抹掉初次失败。这一初次不稳定性仍需留意，当前没有证据认定为哈希校验业务失败。

### B3：Windows 地图检查失败来自 CRLF/LF 指纹差异

未修改的 PR checkout 上 `python tools/generate_project_map.py --check` 失败。生成器按 read_bytes 哈希，197 个源文件在 Windows checkout 为 CRLF。

- PR 地图指纹 / 对源文件按 LF 归一后计算：`be5afc3a10c12c481cc2a1f13c95bb6ce38d64c952017b5220b9ddec276bff8d`。
- Windows 原始字节指纹：`1214f586112c255f129bab86cb72b72c8927d820898117f3e702b6170155f67d`。
- 仅替换 fingerprint 计算后的整个生成地图与提交中的地图完全相等。

这是既有生成器的跨平台确定性问题，不是源文件内容漏更新。应让指纹采用统一换行或用 .gitattributes 明确检查范围的 LF；本轮没有重写 PR 地图隐藏这个失败。

基线额外 305 项对比已结束：304 passed / 1 failed，失败为 `test_host_frontend.py::test_vendored_runtime_matches_recorded_checksum`。vendor JS 也受 CRLF 影响；LF 归一后的 SHA256 为记录的 `72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7`，原字节为 `93a87d787a1a0b4f4c0d719a1016b5b334497abc5ebb821b69fe943a22a05fa6`。vendor 文件与测试都未被 PR 修改，因此属于基线的 Windows checkout 问题，适合通过该路径的 LF 属性解决。

## 验证记录

- 恢复点定向 pytest：330 passed / 2 failed / 2 warnings，267.07s；含后台 API、范围、费用、归集、逻辑及真浏览器检查。初次两个失败见 B2。
- PR 全量 Windows pytest：**2726 passed / 2 failed / 3 skipped / 3 warnings**，2534.14s（42:14），exit 1，共2731项。失败仅为 B2 守卫断言及 B3 vendor checksum；浏览器模块37项中36通过、1失败、0跳过。`full.xml` 保存逐项结果，`full.log` 保存输出。
- 三项跳过均因 Windows 当前进程无创建符号链接权限：archive_store 的两个链接越界测试、zcode_worker 的一个链接越界测试。相应链接场景未在本机动态验证；没有为此提升权限或改安全配置。
- 三项 warnings 含 Playwright 挂起路由清理相关的未 await 协程告警，详见 full.log；不当成应用业务错误，也不声称零告警。
- 基线 Windows 打包/Worker/插件宿主/更新聚焦：59 passed，73.97s。
- 基线针对 PR 全量中出现失败的相邻模块比对：304 passed / 1 failed，765.48s；vendor 校验失败见 B3。
- 改动生产 Python 文件及三项新增测试 flake8：exit 0；改动的 12 个 JS 模块 node --check：全部通过。
- 官方 `tools/build_excel_bundle.ps1`：成功生成 VSE-WebUI onedir、VSE-ExcelWorker.exe、SHA256SUMS.txt 与 ZIP（仅本地验收产物）。
- ZIP：63800207字节，SHA256 `a9c2e96ad1c34242f60b1f495b44a93004f466f0b13a17a547266fc18ea15edd`。产物无正式版本标识，仅用于本次验收。
- 冻结 WebUI 启动：/api/version isFrozen=true；7 个插件 status=loaded；项目概览 API 与新 discovery.js 静态资源 200。
- 冻结页面走查：两种宽度 1400/420 共 44 次页面组合，0 pageerror、0 横向溢出。
- 真实 Excel COM：通过冻结 Worker 执行合成 merge_append，输出工作簿两行的值与预期一致，exit 0；结束后无 EXCEL 进程残留。未借用用户打开的工作簿。
- 合成库升级：从基线生成数据库，放入新 onedir 启动；旧默认 PAA 报告变为 PAA流程，自定义 EWO 名称/负责人保留；升级数据库的副本可被基线代码重新初始化并保留自定义字段。
- Gemini 只读复核：路由 dry-run 为 gemini-3.8-flash-high；live 启动前 preflight-blocked，`Unrecognized key: runtimeModel`，未产生模型审查结果。遵守项目约定停止该路由，没有切换其他供应商。直接代码审查由 Codex 完成，独立于 Claude 原修复会话。

证据根目录：`E:/project/vse-toolbox/.runtime/pr3-windows-review/`；产物仅用于本次验证，尚未发布。

主要命令（在固定PR工作树，使用专用venv Python；VSE_TEST_CHROMIUM 指向本机Chrome）：

```text
python -m pytest tests -q -n 4 -p no:cacheprovider --basetemp <evidence>/full-temp --junitxml=<evidence>/full.xml
python -m flake8 <改动生产Python文件及三项新增测试> -j 1
node --check <12个改动JS文件，逐个执行>
python tools/generate_project_map.py --check
tools/build_excel_bundle.ps1 -OutputDir <evidence>/bundle -WorkDir <evidence>/bundle-build -PythonExecutable <venv-python> -NoCleanup
```

基线失败比对：在d0dd01d工作树执行Windows打包/插件相关59项，以及Excel API/Worker、host、overview相关305项；后者 vendor 校验同样失败，其他304项通过。页签失败复现也在两份代码分别执行。没有把局部基线比对称为基线全量。

## 后续执行前沿

先处理 R1/R2 并稳定 Windows 新增浏览器断言及换行校验，再复跑相关行为与全量回归。R1/R2来自旧e2c58a3实现，B1已在d0dd01d基线中存在；这三项不能描述成Claude此次新造的业务回归。B1应修复或明确登记。公司内网真实 Aras/TDC、NCR 科室白名单的官方行为、真实 NCR 费用对账、实际用户数据/已激活插件覆盖版本的升级与取消最长时间仍需现场验收；COM只验证了合成merge_append，没有以真实文件验证另外两类操作。数模新增功能继续保持后续规划状态；PR #3、PR #2 尚未合并。结束前再次ls-remote核实head/base仍与上述固定SHA一致；两个审查工作树产品源码保持干净。
