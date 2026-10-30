# 一键签署日报文案调整 + TIR 数据简表新模块（Claude 提示词）

> 状态：Active / Ready to use
> 读者：Claude Code（Opus 5.5 + Sonnet 5.5 双档协作）
> 权威来源：`AGENTS.md`、`PROJECT_MAP.md`、当前代码与测试；本文档只描述任务与证据
> 证据文件（只读，禁止入库）：`C:\Users\Lynch\Desktop\test2\1|2|3`、`C:\Users\Lynch\Desktop\TIR数据简表.xlsx`、`C:\Users\Lynch\Desktop\TIR.har`

> 用法：把下方【提示词正文开始】到【提示词正文结束】之间的全部内容复制给 Claude Code
> （工作目录 `E:\project\vse-toolbox`）。证据文件不在仓库内，Claude 需要本机读权限。

---

【提示词正文开始】

你在 Windows 仓库 `E:\project\vse-toolbox`（Python 3.12 + Flask 插件化宿主 + 原生 JS/Preact-htm，分支 main）
执行一项两阶段任务：**A 阶段**调整「一键签署日报」插件的邮件正文文案与明细表列；**B 阶段**新增
「TIR 数据简表」插件（独立新插件），交付 Excel 与 HAR 两份产物。

## 0. 先读后动（强制，顺序不可颠倒）

1. `AGENTS.md` —— 协作规则、插件架构约束、默认拒读路径、运行选择。
2. `memory/CURRENT_STATE.md` —— 当前执行前沿；如涉及爬虫/凭据/Excel 再读 `memory/RECOVERY_NOTES.md`。
3. `PROJECT_MAP.md` 的 Task Router 中「3D单签署日报插件」一行（约第 64 行），按其给出
   的入口与测试开始，**不要全仓搜索**。
4. 再读目标实现本身（A 阶段：`plugins/sign_daily/`；B 阶段：`host/`、`plugins/deliverables/`、
   `services/windows_http.py`、`core/credential_provider.py`、`tools/new_plugin.py`）。
5. 只读证据（**不复制进仓库、不写进日志、不写进测试 fixture**）：
   - `C:\Users\Lynch\Desktop\test2\1`、`2`、`3` —— 三张无扩展名 PNG，是**改动前**的日报邮件正文
     与明细表截图（`1` 为正文全貌，`2` 为明细表放大，`3` 为 Outlook 中的邮件正文）。
   - `C:\Users\Lynch\Desktop\TIR数据简表.xlsx` —— 帆软导出样例（12 行 × 50 列，见 §4.3）。
   - `C:\Users\Lynch\Desktop\TIR.har` —— 5.9 MB 帆软会话 HAR。**禁止整文件读取**；§4.2 已把
     需要的端点与参数提取完毕，只有确需核对时才用脚本按索引取单条 entry。

## 1. 模型路由（强制，不得越级或降级）

| 阶段 | 工作内容 | 模型 |
| --- | --- | --- |
| P1 | 需求边界确认、**架构方案出具**、FineReport 协议逆向方案、风险裁决、公共契约变更决策 | **OPUS 5.5** |
| P2 | 机械代码修改（文案替换、表头增删、顺序调整、测试期望更新） | **Sonnet 5.5** |
| P3 | **代码审查**（逐文件 diff 审查）、验收判定、是否放行 | **OPUS 5.5** |
| P4 | 插件脚手架、页面 UI、文档、测试补齐、打包 | **Sonnet 5.5** |

- 架构方案、审查、跨模块契约、安全与凭据处理**只能由 OPUS 5.5 出具**；纯文案/表头/测试期望
  这类机械改动**不要占用 OPUS 5.5**。
- 切换方式：`/model` 选择 Opus 5.5 / Sonnet 5.5 档位。若当前会话没有可用的 Opus 5.5 档，
  **停下来报告**，不要静默用 Sonnet 出架构方案或做审查。
- 每个阶段结束必须输出：变更文件清单、验证命令与真实结果、剩余风险、下一步；不得只给结论。

## 2. 任务 A：一键签署日报（`plugins/sign_daily`）四处调整

改动前的正文（与截图 `1`/`3` 一致，来自 `plugins/sign_daily/service.py:380-406`）：

```
各位领导、同事：
F610S-车体区域-3D单流程共208份，涉及零件796个，其中长周期件流程共34份，涉及零件75个。
长周期：会签签单率98.2%，总签单率98.7%，3D单完成34/34份，LLP T2发布率100.0%，已锁定发布75/75；
总：会签签单率96.6%，总签单率97.4%，3D单完成206/208份，T2发布率98.9%，已锁定发布787/796。
首次生成，无日变化
图1 外区域会签欠账
图2 内部科室会签欠账
图3 审批欠账
在途流程签署明细（表头：序号/流水单号/零件名称/归属科室/申请人/当前阶段/当前待办人/会签签单率/总签单率/已申请天数/停滞原因）
```

改动后的目标（用户已确认：**汇总行与明细表列都去掉总签单率**）：

```
各位领导、同事：
F610S-车体区域-3D单流程共208份，涉及零件796个，其中长周期件流程共34份，涉及零件75个。
长周期：会签签单率98.2%，3D单完成34/34份，已锁定发布75/75，LLP T2发布率100.0%；
总：会签签单率96.6%，3D单完成206/208份，已锁定发布787/796，T2发布率98.9%。
图1 外区域会签未签单情况
图2 内部科室会签未签单情况
图3 审批未签单情况
在途流程签署明细（表头：序号/流水单号/零件名称/归属科室/申请人/当前阶段/当前待办人/会签签单率/已申请天数/停滞原因）
```

### A1 邮件正文只体现会签签单率，不体现总签单率

- `plugins/sign_daily/service.py:391-396` `_summary_lines.line()`：删除
  `总签单率{pct(values, d, 'totalRate')}，` 这一段（**保留** `会签签单率` 及其 `(+x%)` 变化括号）。
- `plugins/sign_daily/mail.py:43-46` `_TABLE_HEADERS`：删除 `"总签单率"`。
- `plugins/sign_daily/mail.py:132-144` `_table_html()`：删除第 9 个 `<td>`（`_ratio(row["total"])`）。
- `plugins/sign_daily/mail.py:205-209` `render_text()`：删除 `_ratio(row["total"])` 对应列。
- 表格由 11 列变 10 列：`<table width="1100">` 与 `<td>` 内联宽度按比例收敛（建议 1000 px），
  必须继续满足「只用 `<table>` + 行内样式 + 固定像素宽度、无 `class=`」的既有约束
  （`tests/test_sign_daily_mail.py:75` 会断言）。
- **口径约束**：`rules.py` / `service.py` 仍然照常计算并返回 `totalRate`、`total`（每行 `total` 元组）
  到 report payload，只是不再渲染。不要删指标计算、不要改 API 字段，避免破坏其他消费方与既有测试。

### A2 「欠账」字样改成「未签单情况」

仅替换**用户可见文案**，内部标识符（`owed_charts`、`OwedGroup`、`owed_names`、`needsEntry` 等）保持不变。
必须覆盖的已知位置：

- `plugins/sign_daily/mail.py:23-27` `CHARTS`：
  `图1 外区域会签欠账` → `图1 外区域会签未签单情况`；
  `图2 内部科室会签欠账` → `图2 内部科室会签未签单情况`；
  `图3 审批欠账` → `图3 审批未签单情况`。
- `plugins/sign_daily/static/report.js:11` `CHART_TITLES`：三处同步（前后端标题必须一致）。
- `plugins/sign_daily/static/report.js:126,129`：`自动加入有欠账的人` → `自动加入有未签单情况的人`；
  `有欠账但通讯录里没有邮箱` → `有未签单情况但通讯录里没有邮箱`。
- `plugins/sign_daily/static/settings-panel.js:265,283`：两处标签中的「欠账」同样替换。
- 完成后跑一次 `rg -n "欠账" plugins/sign_daily tests`，确认**剩余命中全部是注释/文档字符串/内部标识**；
  若还有用户可见文案，一并改掉。图表 PNG 内部只画组名与统计，不含该字样，无需改 `chart.js`。

### A3 去掉「首次生成，无日变化」

- `plugins/sign_daily/rules.py:1206-1214` `baseline_mode()`：`base_date is None` 或超出
  `max_gap_days` 分支的 `note` 由 `"首次生成，无日变化"` 改为 `""`（`show` 仍为 `False`）。
- **不要动** `(data_date - base_date).days > 1` 分支的 `"括号内为较 MM-DD 的变化"`，
  也不要动 `base_date >= data_date` 的旧数据分支。
- `service.py:497-498` 的 `if mode["note"]: lines.append(...)` 逻辑保持不变（空串自然不追加）。

### A4 「已锁定发布」放到发布率前面

`plugins/sign_daily/service.py:391-396` 的拼接顺序改为：

```
会签签单率…，3D单完成{count}/{flows}份，已锁定发布{count}/{parts}，{t2_label}{pct}
```

即 `已锁定发布` 紧跟在 `3D单完成` 之后、`T2发布率` 之前；两行的 `t2_label`
（`LLP T2发布率` / `T2发布率`）保持不变。`V.fmt_delta` / `fmt_count_delta` 的变化括号语义不得改变。

### A5 受影响的测试（必须同步更新期望，不得删除断言）

| 文件:行 | 现状 | 应改为 |
| --- | --- | --- |
| `tests/test_sign_daily_rules.py:444` | `baseline_mode(DATA_DATE, None) == {"show": False, "note": "首次生成，无日变化"}` | `note` 期望改为 `""` |
| `tests/test_plugin_sign_daily.py:111` | `report["summaryLines"][-1] == "首次生成，无日变化"` | 改为断言该字样**不出现**（如 `all("首次生成" not in line for line in summaryLines)`） |
| `tests/test_plugin_sign_daily.py:169` | `second["summaryLines"][-1] != "首次生成，无日变化"` | 保留意图，改为「无该字样」的断言 |
| `tests/test_sign_daily_mail.py:35` | 夹具含 `"首次生成，无日变化"` | 从夹具移除，并补「正文不含该字样」断言 |
| `tests/test_sign_daily_mail.py:63-64` | 断言 `图1 外区域会签欠账` / `图2 内部科室会签欠账` / `图3 审批欠账` | 改为新标题 |
| `tests/test_plugin_sign_daily.py:326` | 注释含「欠账」 | 文案与断言随 A2 调整 |

新增断言（建议加在 `tests/test_sign_daily_mail.py`）：
- `render_html(...)` 与 `render_text(...)` 的结果中**不出现** `总签单率`、`欠账`、`首次生成`；
- 表头与每行列数一致（10 列），`_TABLE_HEADERS` 中无 `总签单率`；
- 汇总行顺序为 `会签签单率… 3D单完成… 已锁定发布… T2发布率…`（可用 `index()` 比较）。

### A6 A 阶段验收

```powershell
python -m pytest tests/test_sign_daily_mail.py tests/test_sign_daily_rules.py `
  tests/test_sign_daily_settings.py tests/test_sign_daily_frontend_logic.py `
  tests/test_plugin_sign_daily.py -q 2>&1 | Tee-Object .runtime\taskA_pytest.txt
```

> 基线（改动前，2026-10-09 已核实）：`128 passed, 1 skipped in 6.47s`。改动后这 5 个文件必须仍全绿，
> 且新增的「不含 总签单率 / 欠账 / 首次生成」断言通过。

另外必须肉眼核对：用 `python webui.py --only sign-daily` 打开签署日报页，生成的正文预览与
「复制正文」「下载 .eml」三条路径的文本与截图 `1` 的差异**仅限上述四处**。

## 3. 任务 B：新增「TIR 数据简表」插件（`plugins/tir_report`）

### 3.1 目标与交付物

新建**独立插件**（用户已确认形态）：id `tir-report`，目录 `plugins/tir_report/`，用
`python tools/new_plugin.py tir-report --name "TIR数据简表" --page report --title "TIR数据简表" --kind module`
生成骨架，再按本任务扩展。功能：登录帆软报表平台 `report.sgmw.com.cn`，按「项目 / 部门 / 地区 /
发放日期区间」参数导出 `TIR数据简表`，并把结果落盘为交付物。

交付物（两件，缺一不可）：

1. **Excel**：与 `C:\Users\Lynch\Desktop\TIR数据简表.xlsx` 同构的 `.xlsx`（帆软 `type=excel` 导出原样保存，
   不做二次改写），落盘到插件数据目录（`ctx.plugin_data_dir("tir-report")` 之下按数据日期分目录）。
2. **HAR**：本次运行的 HTTP 会话取证文件，**必须脱敏**（见 §3.5）。桌面上的 `TIR.har` 是接口契约
   基线证据，不是要提交的产物；新模块自己产出的 HAR 才是交付物。

> 若「追加 TIR 交付物」在验收时被理解为「把 TIR Excel/HAR 附进日报邮件」，那是另一种形态，
> 需要回到用户确认后再做——**P1 阶段必须先确认这一点并写进方案，不要自行扩展日报邮件。**

### 3.2 已提取的协议事实（来自 `TIR.har`，65 条 entry，全部指向 `report.sgmw.com.cn`）

平台是**帆软 FineReport**（`/webroot/decision/...`）。目标报表：
`技术中心 / TIR / 新TIR / TIR数据简表` → `path = tdc/TIR/TIR数据简表.cpt`，
条目 id `3770a19c-4f81-4c1b-9a94-55dd63c6d58e`。
同目录另有旧报表 `tdc/TIR/旧TIR/整车-简表.cpt`（本任务不处理）。

| # | 方法 | 路径 | 关键参数 / 请求体 | 响应 |
| --- | --- | --- | --- | --- |
| 1 | POST | `/webroot/decision/login` | `{"username":…,"password":<客户端 RSA 密文>,"validity":-1,"sliderToken":"","origin":"","encrypted":true}` | JSON，建立会话 |
| 2 | POST | `/webroot/decision/token/refresh` | `{"oldToken":…,"tokenTimeOut":3600000}` | `{"data":{…,"accessToken":…}}` |
| 3 | GET | `/webroot/decision/v10/view/entry/tree?_=<ts>` | — | 报表树，含 `TIR数据简表` 的 id/path |
| 4 | POST | `/webroot/decision/view/report?op=fr_paramstpl&cmd=query_favorite_params` | — | 收藏参数模板（含 `XM/BM/STARTTIME/ENDTIME/WTZT/DJ/XMJD/GZGBLX` 等键与默认值） |
| 5 | POST | `/webroot/decision/view/report?op=widget&widgetname=xm` | `startIndex=0&limitIndex=0&dataFilter=F610S&reload=false` | 项目下拉候选（`F610S` 等） |
| 6 | POST | `/webroot/decision/view/report?op=widget&widgetname=bm` | `startIndex=0&limitIndex=500&reload=true` | 部门下拉（含 `车体工程`） |
| 7 | POST | `/webroot/decision/view/report?op=widget&widgetname=region_name` | 同 6 | 区域下拉（含 `车体工程`） |
| 8 | POST | `/webroot/decision/view/report?op=fr_dialog&cmd=parameters_d` | `__parameters__=<URL 编码的 JSON>` | `{"status":"success"}` |
| 9 | GET | `/webroot/decision/view/report?__boxModel__=true&op=fr_write&cmd=read_w_content&cid=…&reportIndex=0&browserWidth=918&__webpage__=true&_paperWidth=918&_paperHeight=378&__fit__=false` | — | `{"outputMode":"STREAM_JSON","html":"…"}`（213 KB / 370 KB，即渲染后的表格数据） |
| 10 | POST | `/webroot/decision/export/check/font` | `format=excel` | `{"state":1}` |
| 11 | POST | `/webroot/decision/view/report` | `op=export&cmd=export_polling&type=excel&data=<毫秒时间戳>` | `{"isExporting":false}` |

**参数编码（关键细节）**：`__parameters__` 的值是 JSON，其中中文以「`[` + 小写十六进制码点 + `]`」
表示（例：`问题` → `[95ee][9898]`，`故障报告编号` → `[6545][969c][62a5][544a][7f16][53f7]`），
再整体做 URL 编码。HAR 中已出现并需要支持的键：
`XM`(项目)、`BM`(部门)、`KS`(科室)、`REGION_NAME`(区域)、`STARTTIME`/`ENDTIME`(发放起止日期，
样例 `2022-07-11` / `2026-10-09`)、`WTZT`(问题状态)、`DJ`(等级)、`XMJD`(项目阶段)、`GZGBLX`(故障关闭类型)、
`TCR`(提出人)、`TCKS`(提出科室)、`LJMC`(零件名称)、`SYMC`(试验名称)、`GZZT`(故障主题)、`CLPZ`(车辆配置)、
`CLSBH`(VIN)、`FDJXH`(发动机型号)、`GZBGBH`(故障报告编号)、`ZRGCS`(责任工程师)，以及对应的 `LABEL*` 标签键。

### 3.3 必须在 P1 方案里解决的开放风险（先只读探针验证，**禁止在方案中假设**）

- **R1 登录加密**：HAR 中 `password` 是客户端加密后的密文（`encrypted:true`），HAR 里没有捕获公钥获取请求。
  需确定：复用 FineReport 登录页的加密实现（公钥来自哪里）、平台是否支持明文/令牌登录、
  或能否用 `accessToken` + `token/refresh` 长期续期。给出**至少两条候选路径与验证方法**。
- **R2 导出下载链路不完整**：HAR 只有 `check/font` + `export_polling`，没有捕获真正的二进制下载请求
  （样例 xlsx 是人工另存的）。需确定 `export_polling` 之后真实的下载 URL 与所需会话头；
  若走不通，退路是解析第 9 步 `read_w_content` 的 JSON 自行生成 xlsx（需评估保真度并说明取舍）。
- **R3 会话与并发**：`tokenTimeOut = 3600000 ms`；同一账号并发登录可能互踢。
  需定义会话复用、失效重登、退避重试与「同账号串行」约束。
- **R4 参数与去重**：把第 4~8 步的参数契约固化成带契约测试的纯函数（脱敏 fixture），
  并对同一「项目+部门+日期区间」的重复导出定义幂等/缓存策略。
- **R5 落盘与下载**：宿主既有的文件落盘/下载约定是什么（参考 `plugins/deliverables`、`plugins/excel_tasks`
  的现有做法）；若宿主没有可复用约定，方案里要给出**最小新增**，不要另起一套。

### 3.4 架构约束（不可协商）

- 新功能即新插件；**不得**把路由写进 `web/app.py`，**不得**改 `core/db_manager.py`。
- 插件只能通过 `host.context`（`ctx.db`、`ctx.data_dir`、`ctx.plugin_data_dir()`、`ctx.service(...)`、
  `ctx.json_ok/json_error`）访问共享能力；**不得** `import web.*` 或其他插件。
- 每个写路由第一行调用 `ctx.local_guard()`；后台抓取走宿主的 `crawl_task_runner` 服务
  （参考 `plugins/sign_daily/backend.py:558-584` 的 `submit_task`/`get_task` 用法）。
- HTTP 传输复用 `services/windows_http.py`（WinHTTP/Schannel），不要新引入 `requests` 依赖。
- 凭据只经 `core/credential_provider.py` 的 `credential_ref` 别名读取（Windows 凭据管理器），
  **不得**在插件里保存账号密码、不得写进插件配置文件或数据库。
- 日志与错误信息走 `ctx.redact` / `core/redaction.py`；错误码沿用宿主闭集指引码的风格
  （见 `plugins/sign_daily/backend.py:56-72`）。
- 需要新增共享服务时，先在方案里写明边界与测试策略，再落地。

### 3.5 安全红线（违反即回滚）

- `TIR.har` 内含**真实账号名、加密后的密码密文、`oldToken`/`accessToken`、内网 IP**。
  这些值**不得**出现在任何仓库文件、文档、日志、测试 fixture、prompt 或报告里。
  HAR/XLSX 原始样例属 `AGENTS.md` 默认拒读路径，本任务显式授权解析，但**不得入库**。
  已核实：当前 `.gitignore` **没有**忽略 `*.har`（`git check-ignore TIR.har` 返回 1），
  所以 B 阶段第一步就要补 `*.har` 与 `*.xlsx` 样例的忽略项，再开始落盘任何 HAR。
- 插件自己产出的 HAR 必须脱敏：默认只保留方法/路径/状态码/耗时/尺寸与**白名单**参数，
  请求头中的 `Cookie`/`Authorization`/`token`、请求体中的 `password`/`oldToken` 一律替换为占位符。
- 不要把凭据写入测试或探针脚本；探针读取凭据只能通过凭据管理器。

### 3.6 分阶段实施（每阶段结束停下来汇报）

- **Phase 0 只读探针**（可执行、可回滚）：写一个 `tools/` 下的探针（参考 `tdc_probe_main.py` /
  `services/tdc_contract_probe.py` 的「不写库、不落原始数据」约定），在**你确认已具备凭据的前提下**
  逐条验证 §3.2 的 11 步，产出脱敏的端点契约报告到 `.runtime/`。若拿不到凭据，**停下来向用户索要
  凭据引用名（credential_ref）**，不要伪造、不要绕开。
- **Phase 1 最小可用导出**：纯函数化的登录/参数编码/导出链路 + 契约测试（脱敏 fixture 重放，
  不发真实网络请求），产出 xlsx 到插件数据目录。
- **Phase 2 页面与交付物**：`#p/tir-report/report` 页面（参数选择、触发、进度、下载），
  Excel + HAR 双产物落盘与下载入口。
- **Phase 3 打包（可选，按用户决定）**：`python tools/build_plugin_pkg.py plugins/tir_report --key <签名密钥>`。

### 3.7 B 阶段验收

```powershell
python -m pytest tests/test_plugin_tir_report.py -q 2>&1 | Tee-Object .runtime\taskB_pytest.txt
python tools/generate_project_map.py --check
```

- 离线契约测试通过：9~11 步链路的请求序列、`__parameters__` 中文 `[hex]` 编码、xlsx 落盘
  （zip 魔数 `PK` + 首行 50 列表头）均有断言，且 fixture 中**无任何真实凭据**。
- 手工验收：`python webui.py --only tir-report` → 打开 `#p/tir-report/report` → 选
  项目 `F610S` / 部门 `车体工程` / 发放日期区间（样例 `2022-07-11` ~ `2026-10-09`）→ 导出 →
  得到与 `C:\Users\Lynch\Desktop\TIR数据简表.xlsx` **同构**的文件（首行 50 列表头一致）。
- 产出的 HAR 中不存在明文/密文凭据与 token（用 `rg` 自检一遍）。

### 3.8 交付物列头参考（`TIR数据简表.xlsx` 第 1 行，共 50 列）

```
申请单号 | 序号 | 故障报告编号 | 责任工程师 | 责任科室 | 当前节点 | 未操作者 | 提出人 | 提出科室 |
提出日期 | 发放日期 | 故障等级 | 问题状态 | 项目编号 | 项目阶段 | 试验名称 | 故障主题 | 零件名称 |
是否是架构项目 | 所属架构平台 | 是否是架构件 | 一级故障模式 | 三级故障模式 | 试验规范 | 试验地点 |
故障背景 | 车辆编号 | 车辆配置 | 车辆识别号（VIN） | 变速箱型号 | 发动机型号 | 发动机号 | 电池信息 |
故障关闭类型 | 车辆验证里程（km） | 零件试验里程（km） | 坏路（km） |
根本原因（2/6）-计划 | 根本原因（2/6）-实际 | 长期措施（3/6）-计划 | 长期措施（3/6）-实际 |
措施实施（4/6）-计划 | 措施实施（4/6）-实际 | 验证开始（5/6）-计划 | 验证开始（5/6）-实际 |
关闭（6/6）-计划 | 关闭（6/6）-实际 | 试验认证协调员 | 责任区域 | 责任区域VSE
```

## 4. 工作流与交付顺序

1. **P1（Opus 5.5）**：先确认 §3.1 的形态问题与 §3.3 的风险结论，产出架构方案
   （模块边界、数据流、接口契约、落盘路径、测试策略、分阶段计划、回滚方案），写进
   `docs/`（文件名含日期）。方案里必须明确：哪些是本次做、哪些留待确认。
2. **P1 复核（Opus 5.5）**：对方案做一次独立审查（可让另一个 Opus 5.5 会话扮演审查者），
   确认没有触碰 `AGENTS.md` 的默认拒读路径与插件架构红线。
3. **P2（Sonnet 5.5）**：执行任务 A 的全部机械改动与测试更新，先跑 A 阶段验收命令。
4. **P2（Sonnet 5.5）**：按方案执行 B 阶段 Phase 0/1/2。
5. **P3（Opus 5.5）**：审查完整 diff（`git diff` + 新增文件），逐条对照 §2/§3 的验收标准；
   发现不符就回退给 Sonnet 5.5 修，最多两轮同类返工，第三轮由 Opus 5.5 接手。
6. **收尾**：跑一次相关测试全绿，更新 `memory/CURRENT_STATE.md`（整篇替换）并在需要时更新
   `memory/RECOVERY_NOTES.md`（把 FineReport 协议结论沉淀为长期知识）。

## 5. 全局禁止事项

- 不读取、不索引 `AGENTS.md` 中列出的默认拒读路径（`crawl source/`、`爬虫源文件/`、`error data/`、
  `build/`、`dist/`、`.runtime/`、`artifacts/`、`tmp/`、`.tmp_*`、`.agents/runs|logs|worktrees`、
  `.zcode/`、`design-previews/`、`meeting_outputs/`）——本任务对 `TIR.har`/`TIR数据简表.xlsx` 的解析
  是唯一例外，且只读。
- 不使用仓库根目录的递归全仓扫描（`rg --files`、`Get-ChildItem -Recurse`、`find`）。
- 不提交任何凭据、token、HAR 原文、原始 xlsx 样例。
- 不为了让测试通过而删除断言或放宽验收标准；不修改与本次任务无关的文件。
- 不擅自把 TIR 产物并入日报邮件（需用户确认，见 §3.1）。

## 6. 需要向用户确认的开放问题（P1 阶段先问）

1. 「HAR 与 Excel 是追加的 TIR 交付物」是否确指**独立插件产出两份文件**（本次默认），
   还是要把它们作为附件并入一键签署日报的邮件？
2. TIR 导出默认参数是什么（项目固定 `F610S`？部门固定 `车体工程`？日期区间按「发放日期」当天/近 N 天？），
   是否需要每天自动跑（Windows 计划任务）？
3. 帆软平台的 `credential_ref`（Windows 凭据管理器条目名）由谁提供？没有它 Phase 0 探针无法验证。

【提示词正文结束】
