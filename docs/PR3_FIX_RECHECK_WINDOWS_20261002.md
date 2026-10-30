# PR #3 修复复核：969e501 / Windows

状态：R1/R2/B1/B3 验证通过，B2 的守卫拦截断言也通过；Windows 全量仍有一个重试阶段失败，暂不建议直接合并。

## 固定对象与验证环境

- PR：CaptainLynch/vse-toolbox#3，`claude/restore-plugin-parity` → `refactor/plugin-host`。
- 固定 head：`969e501b650f1d8917b886d21216ef81ebb754fa`，对照上一轮 `f5b0df0b25b29693bdaeec1baf9223f0741ad187`。
- 本轮全新 Windows 工作树：`C:/Users/Lynch/.codex/worktrees/pr3-windows-969e501/vse-toolbox`。定向业务回归先在复用的 `pr3-windows-review` 工作树、同一 head 上执行。
- Windows / Python 3.12.10 / 本机 Chrome + Playwright。专用 Python：`E:/project/vse-toolbox/.runtime/pr3-review-venv/Scripts/python.exe`。
- 本轮证据：`E:/project/vse-toolbox/.runtime/pr3-windows-recheck-969e501/`。没有修改 PR 产品代码，没有合并、推送、打包或部署。

## 五项修复复核

| 项目 | 复核证据 | 定向结果 |
| --- | --- | --- |
| R1 后台阶段总截止 | 状态/结果 fetch 共用 AbortController 与截止；新增两个浏览器挂起用例；独立 Node 探针覆盖状态请求、状态 body、结果请求、结果 body | 四种探针均在约 53–76ms 内退出（预算 50ms），均带 signal、返回 retryable 和任务中心提示；两个浏览器用例通过 |
| R2 过期令牌取消新任务 | 任务注册表保留初始与重新挂接令牌；取消只查所属任务；`test_stale_cancel_token_cannot_cancel_a_later_task` | API 断言通过；未知/过期令牌返回 `not_running`，不取消新任务 |
| B1 切页签失败后筛选丢条件 | 失败恢复最后成功页签；`test_filter_apply_after_failed_tab_switch_keeps_the_typed_condition` | 真浏览器断言通过，失败后输入的关键词出现在后续请求中 |
| B2 守卫安装时序 | 改用 `useLayoutEffect`；`test_view_timeout_unlocks_interaction_and_offers_retry` | 定向及全量中的守卫断言均通过；但全量在该用例的后续重试阶段失败，见下节 |
| B3 Windows 换行校验 | 地图指纹 CRLF → LF；`.gitattributes` 固定 vendor LF；全新工作树运行地图检查与 host/map 模块 | 地图检查 exit 0；17 项测试全部通过 |

### B3 已有工作树的迁移细节

复用旧审查工作树从 f5b0df0 切到 969e501 时，vendor 文件仍是旧 CRLF 字节；首次 host/map 检查为 16 passed / 1 failed（vendor checksum）。新的属性文件不会保证 Git 自动重写内容未变的旧工作文件。普通 `checkout-index --force` 在该工作树也未刷新字节。

全新检出 969e501 后 vendor 为 LF，17 项检查全部通过。另在确认复用工作树的 vendor 没有用户改动后，删除该单个工作文件并从 HEAD 恢复，vendor 校验单项通过；Git blob 与 HEAD 完全一致，最终工作树无产品差异。已有工作树更新后应重新检出 vendor 文件并核对字节；不要修改记录的校验值来接受 CRLF。

## 验证结果

- 定向串行 pytest：`test_plugin_overview_browser.py`、`test_plugin_overview_parity_logic.py`、`test_project_status_api.py`，**87 passed / 3 warnings**，177.23s，exit 0。其中真浏览器 **40 项全部通过**。
- 全新工作树 B3：`test_host_frontend.py` + `test_project_map.py`，**17 passed**，12.22s，exit 0；地图 `--check` exit 0。
- 独立 Node 四种截止探针通过，证据 `repro-deadlines.mjs` 与 `deadline-*.log`。
- 独立 R2 API 探针 **2 passed**，18.43s：初始令牌、重新挂接令牌分别能取消所属任务，未知令牌返回 `not_running`。证据 `test_cancel_reattach.py` / `reattach-isolated.log`。初版探针复用向导会话且模拟客户端忽略取消，第二场景未进入模拟抓取，首次为 1 passed / 1 failed；修正独立会话及模拟取消后通过，保留初次日志 `reattach.log`，不列为产品失败。
- 改动 Python 文件 flake8 exit 0；两个生产 JS 文件 `node --check` 通过。
- Windows 全量：**2731 passed / 1 failed / 3 skipped / 4 warnings**，2251.55s（37:31），exit 1，共2735项。浏览器模块40项：39 passed / 1 failed。最终 `full.log` / `full.xml` 已读取。
- 全量中 R1 两条挂起用例、R2 过期令牌、B1 筛选、B3 vendor checksum 均通过；历史 foreign params hash 用例也通过。
- 唯一失败用例单独复跑：**1 passed**，5.06s，证据 `b2-rerun.log` / `b2-rerun.xml`。
- 三项跳过仍为 Windows 不能创建符号链接的两个 archive_store、一个 zcode_worker 用例；没有提升权限，相关链接场景未动态验收。四项 warnings 为 Playwright 清理期间 `Connection.wrap_api_call` 协程未 await，详见 full.log。

## 尚需闭环：重试场景失败与数据库锁冲突

唯一失败：`tests/test_plugin_overview_browser.py::test_view_timeout_unlocks_interaction_and_offers_retry`，当前源码第422行。

该次运行已通过 `data-form-interaction-blocked-count >= 1`，也已通过超时提示、解锁、输入及回退到项目状态的断言。失败发生在后续真实后端重试：刷新后再次切到“数量趋势”，等待 `.form-trend-chart` 超过8秒。因此不能将它描述为原 B2 的“监听器还未安装”复发。

同时日志记录多次 `sqlite3.OperationalError: database is locked`：`core/repos/project_status.py:654` 调用 `_ensure_project_status_policy`，在第537行的 `INSERT OR IGNORE` 失败，`update-policy` 与 `unified-status` GET 返回500。这两处 repo/analytics 文件相对 d0dd01d 基线未变；本轮尚未确定锁的持有者、是否与历史 hash 用例同根，以及锁冲突与最终图表超时的完整因果链。不能直接标为纯测试问题，也不能声称数据库锁已修复。

另一个明确的测试边界：用例把表单请求截止改为600ms来模拟超时，随后真实后端重试仍沿用600ms（生产默认30000ms）；刷新后只等待已存在的旧“项目状态”标题，不能证明该次刷新已落定。这会使重试断言受机器负载与后端时延影响，单独重跑通过也不能证明全量稳定。

建议合并前补一轮：超时/守卫阶段继续保留600ms和原拦截断言；重试阶段恢复正常请求预算，等待本次响应及加载落定，再检查目标页签。同时独立定位只读GET触发 policy seed 写入的锁冲突，不应只增加8秒的DOM等待来掩盖500。修正后先复跑这两类场景，再跑Windows全量。本轮只审查与验证，没有直接修改产品或提交测试补丁。

主要命令（固定工作树，Python 使用上述专用 venv）：

```text
python -m pytest tests/test_plugin_overview_browser.py tests/test_plugin_overview_parity_logic.py tests/test_project_status_api.py -q -p no:cacheprovider --basetemp <evidence>/focused-temp --junitxml=<evidence>/focused.xml
python tools/generate_project_map.py --check
python -m pytest tests/test_host_frontend.py tests/test_project_map.py -q -p no:cacheprovider --basetemp <evidence>/fresh-b3-temp --junitxml=<evidence>/fresh-b3.xml
python -m pytest tests -q -n 4 -p no:cacheprovider --basetemp <evidence>/full-temp --junitxml=<evidence>/full.xml
```

## 验证边界与下一步

历史 `test_wizard_discards_background_result_with_foreign_params_hash` 本轮定向与全量均通过，但数据库锁冲突在另一个浏览器用例中再次出现，根因仍未定位。

上一轮 onedir / Excel Worker / 合成 COM / 升级冒烟对应 f5b0df0，不能视为本轮 969e501 包的验收。本轮未重新打包。公司内网真实 Aras/TDC、NCR 官方科室白名单、费用对账、真实取消时延以及实际用户数据/已安装插件覆盖版本的升级仍需现场验收。PR #3、PR #2 的合并以及数模新功能规划留待后续。结束前再次 ls-remote 核实 head 仍969e501、base仍d0dd01d；两个969审查工作树产品源码干净，原工作区无关改动保留。
