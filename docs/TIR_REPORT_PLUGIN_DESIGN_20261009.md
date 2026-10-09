# TIR 数据简表插件（`tir-report`）架构方案 — 2026-10-09

> 状态：P1 方案 + 独立复核已采纳（§10）；Phase 1/2 离线实现与测试已完成；Phase 0 真实探针**未执行**（需 Windows、内网与凭据）
> 证据：`TIR.har`（65 条 entry，仅脚本按结构读取，未入库）、`TIR数据简表.xlsx`（12 行 × 50 列，未入库）
> 本文档不含任何账号、密码密文、token、sessionID、内网 IP 或水印内容。

## 1. 范围与形态决定

| 问题 | 本次决定 | 是否待用户确认 |
| --- | --- | --- |
| 交付形态 | **独立插件** `plugins/tir_report/` 只产出帆软原样导出的 Excel，不产出 HAR，不并入日报邮件 | 已确认（2026-10-09） |
| 默认参数 | 项目**留空（全部项目）**、部门 `车体工程`、发放日期 `2022-07-11` ~ 当天；页面可改并保存 | 已确认（项目留空） |
| 每日自动跑 | 参照「自动归档」：计划任务每小时跑 `tools/tir_export_cli.py --once`，页面开关 + 时间决定是否导出 | 已确认 |
| 凭据 | 帆软账号 = 统一域账号：经宿主 `domain_credential_vault`（DPAPI）读取，插件不保存任何账号信息 | 已确认 |
| 「地区」参数 | **TIR数据简表.cpt 没有地区参数**：HAR 第 33 条 `parameters_d` 只含 `XM/BM/KS/STARTTIME/ENDTIME/…`；`REGION_NAME` 属于旧报表 `旧TIR/整车-简表.cpt`（第 56/57 条）。本次只支持新报表真实存在的参数 | 告知用户 |

## 2. 协议结论（HAR 结构分析）

平台：帆软 FineReport 10（`/webroot/decision/...`）。目标条目 `3770a19c-4f81-4c1b-9a94-55dd63c6d58e`，
`path = tdc/TIR/TIR数据简表.cpt`。

1. **登录** `POST /webroot/decision/login`，JSON `{username,password,validity:-1,sliderToken:"",origin:"",encrypted}`；
   响应 `{data:{accessToken,…}}`。HAR 是 Chrome 的「脱敏 HAR」：所有请求都**没有** Cookie/Authorization 头，
   说明鉴权头被导出时剥离，而不是不存在。FineReport 前端把 `accessToken` 写进 `fine_auth_token` cookie，
   XHR 同时带 `Authorization: Bearer <token>`。实现两者都设置。
2. **报表会话**：所有 `view/report` 请求带同一个 `sessionID` 头（UUID 形态），Referer 是
   `/webroot/decision/v10/entry/access/<entryId>`。该页面 HTML 本身未被 HAR 捕获；sessionID 从该页 HTML
   中解析（候选模式：`FR.SessionMgr.register('…')`、`sessionID: '…'`、`currentSessionID = '…'`）。
3. **参数提交** `POST view/report?op=fr_dialog&cmd=parameters_d`，表单字段 `__parameters__`：
   `JSON.stringify(参数对象)` → `FR.cjkEncode`（码点 ≥ 0x80 **以及 `[`、`]`** 编码成 `[小写hex]`）
   → `encodeURIComponent`。多选值以 `','` 连接成一个字符串（旧报表 `REGION_NAME` 证据）；空多选是 `[]`。
   浏览器会把**全部**参数键（含 `LABEL*` 标签键与空值）一起提交，实现照抄同样的键集与顺序。
4. **取数** `GET view/report?op=fr_write&cmd=read_w_content&reportIndex=0&pn=<页>&__webpage__=true…`
   → `{"outputMode":"STREAM_JSON","html":…,"sheets":…,"watermark":…}`。html 中单元格是
   `<td col="N" row="M" …><div>文本</div></td>`；首行表头即 50 列。**watermark 含登录用户名**，该响应不得记录或落盘。
5. **导出**：HAR 只有 `export/check/font (format=excel)`、`fr_write save_w_content` 与
   `op=export&cmd=export_polling&type=excel`；真正的下载是浏览器导航（隐藏 iframe/表单），未进 XHR 记录。
   FineReport 10 的标准下载端点是 `GET view/report?op=export&format=excel&extype=simple&sessionID=<sid>`。

## 3. 开放风险结论（R1–R5）

- **R1 登录加密**：候选路径（按顺序尝试，Phase 0 探针逐条报告哪条成立）：
  以下三条均为**待 Phase 0 证实的假设**（HAR 未捕获公钥来源）：
  1. 从登录页 HTML 解析 RSA 公钥（`-----BEGIN PUBLIC KEY-----` 或 `MIIB…` Base64 DER），
     用 `cryptography`（已是依赖）做 PKCS#1 v1.5 加密 → `encrypted:true`。
  2. 页面未开启传输加密（找不到公钥）→ 明文 + `encrypted:false`。
  3. 两者都失败：平台可能是 SM4 传输加密或滑块验证，探针输出 `login_unsupported` 指引码并停止，不猜测。
  长期 `token/refresh` 续期**不做**：每次任务重新登录，不持久化任何 token。
- **R2 导出下载**（主路径是**假设**，HAR 未捕获下载请求）：`op=export&format=excel&extype=simple`，响应必须是
  HTTP 200 且以 `PK` 开头才算成功，否则任务以 `export_failed` 失败、不落任何文件。**不做自建 xlsx 退路**
  （用户 2026-10-09 确认不接受重建产物）。`read_w_content` 仍按浏览器顺序调用一次（报表据此计算），只用于统计行数。
- **R3 会话与并发**：任务经宿主 `crawl_task_runner` 提交，`source="tir-report"` 固定 → **仅本进程内**同源串行；
  页面任务与计划任务（`tools/tir_export_cli.py`）另有跨进程文件锁 `runs/.lock` 互斥（§12-4）；不覆盖
  `tools/tir_probe.py` 与用户自己的浏览器（同账号仍可能互踢，失败按闭集错误码报告，重跑即可）。
  API 调用一律 `allow_redirects=False`；打开报表页按内容判别登录页。单任务内发现登录态失效时**重登一次**；
  传输错误重试 2 次（2s、4s 退避）。插件注册默认处理器 `register_handler("tir_report_export", …)`，宿主「重试」可用。
- **R4 参数与去重**：`protocol.py` 全部是纯函数（参数模板、cjkEncode、表单体、sessionID 解析、
  表格解析），有契约测试。幂等：同一「项目+部门+科室+起止日期」在同一导出日已有成功产物时直接复用
  （`force=true` 才重跑）；同键任务在排队/运行中时复用该任务（查重+提交在插件级锁内，避免双击竞态）。
- **R5 落盘与下载**：宿主无文件下载约定可复用（`crawl_task_runner.downloads_dir` 有 7 天轮换，
  不适合作为交付物）。最小新增：交付物只有 `ctx.plugin_data_dir("tir-report")/exports/<导出日>/<stem>.xlsx`；
  复用判断与产物列表用的运行记录放在插件内部 `runs/<导出日>/<stem>.json`（不进导出目录、不提供下载）；失败不写文件。
  `stem = tir_<项目ASCII>_<起>-<止>_<筛选键sha256前8位>`，不含用户输入的中文/路径字符。
  `GET files/<day>/<name>`：`day` 必须匹配 `^\d{4}-\d{2}-\d{2}$`，`name` 必须匹配 `^[A-Za-z0-9_-]+\.xlsx$`
  （拒绝 `\`、盘符、`:` 流），再校验 `resolve()` 位于导出根目录内且是文件。

## 4. 模块边界

```
plugins/tir_report/
  plugin.json        id tir-report，module 页面 report.js
  protocol.py        纯函数：参数模板/编码、URL 与表单、sessionID/公钥解析、read_w_content 表格解析
  client.py          FineReportClient：login → open_report → set_parameters → read_page → export_excel
  service.py         run_export()：组装客户端、落盘三件套、幂等判断、任务视图
  backend.py         路由（写路由首行 local_guard）
  static/report.js   页面：参数、凭据别名、触发、进度、产物列表与下载
tools/tir_probe.py   Phase 0 只读探针：逐步验证并把脱敏契约报告写到 .runtime/
```

依赖：`services.windows_http.WinHTTPSession`（传输）、`core.credential_provider.WindowsCredentialManagerProvider`
（凭据）、`core.redaction`（错误文本）、`services.xlsx_preview`（表头校验）、宿主服务 `crawl_task_runner`。
不 import `web.*`、不 import 其他插件、不改 `web/app.py` / `core/db_manager.py`、不建表。

## 5. 路由契约（`/api/p/tir-report/`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `state` | 默认筛选、自动导出设置、上次自动导出结果、域账号是否已保存、最近产物 |
| POST | `config` | 保存默认筛选与自动导出开关/时间（`local_guard`） |
| POST | `export` | 提交导出任务（`local_guard`）；体 `{project, department, section, startDate, endDate, force}` |
| GET | `export/<task_id>` | 任务进度与结果 |
| GET | `files` | 产物清单（按导出日倒序） |
| GET | `files/<day>/<name>` | 下载 xlsx |

错误码（闭集）：`credential_missing`（未配置别名）、`credential_unavailable`、`login_failed`、
`login_unsupported`、`session_not_found`、`export_failed`、`network_error`，各自带中文处理指引。

## 6. 敏感信息约束

插件不产出 HAR（用户 2026-10-09 确认交付物只有 Excel）。账号口令只在凭据上下文内使用；token、sessionID
只存在客户端对象内存，不写盘、不进任务参数与运行记录；错误信息只用闭集指引码，不回显服务器原文
（登录失败消息可能回显账号）。`tools/tir_probe.py` 的报告只含步骤名、布尔值、计数与错误码。

## 7. 测试策略

`tests/test_plugin_tir_report.py`（全离线，fake session 重放脱敏 fixture，不含真实凭据）：
cjkEncode 与 HAR 第 33 条形态一致（`问题` → `[95ee][9898]`、`[]` → `[5b][5d]`）；请求序列
`login → entry/access → parameters_d → read_w_content → check/font → export → export_polling`；
落盘 xlsx 与平台返回字节一致且首行 50 列表头；平台不给 xlsx 时失败且不落文件；运行记录无凭据/token/sessionID；
插件加载、写路由 `local_guard`、文件下载路径穿越被拒、幂等复用。

## 8. 分阶段与回滚

- Phase 0（待执行）：`python tools/tir_probe.py`（Windows，内网，已在 VSE 保存统一域账号）→ `.runtime/tir_probe_report.json`。
- Phase 1/2（本次完成离线部分）：协议纯函数 + 客户端 + 页面 + 双产物。
- Phase 3（可选）：`python tools/build_plugin_pkg.py plugins/tir_report --key <签名密钥>`。
- 回滚：插件自包含，删除 `plugins/tir_report/` 与对应测试即可；不涉及数据库迁移；数据目录可留存。

## 9. 留待确认

1. §1 表中三项用户确认；2. Phase 0 探针结果决定 R1 路径与 R2 主路径是否成立；
3. ~~是否接受重建 xlsx~~：已确认**不接受**；导出端点若在真实环境不成立，需按探针结果修正端点。

## 10. 独立复核记录（2026-10-09，Opus 只读审查）

10 条意见全部采纳：状态措辞（1）；HAR 主机占位、HAR 1.2 其他字段置空（2）；响应正文改为白名单键（3）；
`__parameters__` 只留 5 键（4）；下载路由正则 + ASCII stem + resolve 校验（5）；R3 改为「仅进程内」、API 禁跟随重定向（6）；
插件级锁 + `register_handler`（7）；`export/<task_id>` 校验 `source`（8）；凭据别名执行时从配置读、不进任务参数（9，
宿主 `domain_credential_vault` 是 DPAPI 域账号库而非 `credential_ref` 解析器，按任务约束仍走 Windows 凭据管理器，
经 `backend.credential_provider_factory` 可替换）；R1/R2 标注为假设、退路验收列为待确认（10）。

## 11. 离线验证结论

- `__parameters__` 编码与 HAR 第 33 条**逐字节一致**（同参数 F610S / 车体工程 / 2022-07-11 ~ 2026-10-09）。
- `read_w_content` 解析（隐藏第 14 列、不闭合 `<td/>`、标题行）对 HAR 第 35 条响应重建的表格与样例 xlsx
  **12 行 × 50 列逐格一致**（数值列 `1.0` 与 `1` 的格式差异除外）。重建退路已按用户决定移除，此结论仅用于行数统计。
- 样例 xlsx 经 `header_check` 判定 50 列表头一致。

## 12. 用户决定（2026-10-09）

1. TIR 只产出 Excel：移除 HAR 产物（`har.py`）及相关路由/页面链接；§6、§10 中 HAR 脱敏条目随之失效。
2. 不接受重建 xlsx：移除 `xlsx_writer.py` 与 `rebuilt` 模式；拿不到帆软原样导出即失败。
3. 默认项目留空（= 全部项目，`XM` 提交空串）。文件名项目段为 `all`。
4. 自动导出参照「自动归档」：`tools/install_tir_export_task.ps1` 注册每小时一次的计划任务（当前用户、
   IgnoreNew、StartWhenAvailable），调用 `tools/tir_export_cli.py --once`；`service.auto_decision` 决定：
   开关关 → disabled；未到设定小时 → not_yet；当天已有默认筛选的结果 → done；当天登录类失败
   （credential_missing/credential_unavailable/login_failed/login_unsupported）→ stopped_today（避免锁定域账号）；
   当天已失败 3 次 → attempts_exhausted。结果写 `runs/auto-state.json`，页面展示。
   页面任务与计划任务跨进程互斥：`runs/.lock`（O_EXCL，30 分钟视为残留），冲突返回 `busy`。
5. 帆软账号 = 统一域账号：`DPAPICredentialProvider(domain_credential_vault).resolve("domain")`，用户名去掉
   `域\` 前缀后登录（待 Phase 0 复核帆软是否接受）。未保存时提示「登录 TDC 并勾选保存至凭据保护库」。
   §10 第 9 条「仍走 Windows 凭据管理器」据此作废。
