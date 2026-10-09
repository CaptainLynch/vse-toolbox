# TIR 数据简表插件（`tir-report`）架构方案 — 2026-10-09

> 状态：P1 方案 + 独立复核已采纳（§10）；Phase 1/2 离线实现与测试已完成；Phase 0 真实探针**未执行**（需 Windows、内网与凭据）
> 证据：`TIR.har`（65 条 entry，仅脚本按结构读取，未入库）、`TIR数据简表.xlsx`（12 行 × 50 列，未入库）
> 本文档不含任何账号、密码密文、token、sessionID、内网 IP 或水印内容。

## 1. 范围与形态决定

| 问题 | 本次决定 | 是否待用户确认 |
| --- | --- | --- |
| 交付形态 | **独立插件** `plugins/tir_report/` 产出 Excel + 脱敏 HAR 两份文件，不并入日报邮件 | 是（§6-1，默认按独立插件） |
| 默认参数 | 项目 `F610S`、部门 `车体工程`、发放日期 `2022-07-11` ~ 当天 | 是（§6-2） |
| 每日自动跑 | 不做（只提供页面手动触发）；后续可复用 `tools/install_*_task.ps1` 模式 | 是（§6-2） |
| 凭据 | 页面只保存 `credential_ref` 别名，值由 Windows 凭据管理器解析 | 是（§6-3，需用户提供条目名） |
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
   `<td col="N" row="M" …><div>文本</div></td>`；首行表头即 50 列。**watermark 含登录用户名**，HAR 记录时必须丢弃响应体。
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
- **R2 导出下载**（主路径是**假设**，HAR 未捕获下载请求）：主路径 `op=export&format=excel&extype=simple`，响应必须以 `PK` 开头才算成功；
  否则退回「解析 `read_w_content` 全部分页 → 自建 xlsx」。退路保真度：表头与单元格文本一致、
  数值单元格写成数字，**丢失**样式/列宽/合并单元格；产物元数据 `mode=rebuilt` 明确标注，页面可见。
- **R3 会话与并发**：任务经宿主 `crawl_task_runner` 提交，`source="tir-report"` 固定 → **仅本进程内**同源串行；
  不覆盖 `tools/tir_probe.py`、第二个应用实例或用户自己的浏览器（同账号仍可能互踢，失败按闭集错误码报告，重跑即可）。
  API 调用一律 `allow_redirects=False`；打开报表页按内容判别登录页。单任务内发现登录态失效时**重登一次**；
  传输错误重试 2 次（2s、4s 退避）。插件注册默认处理器 `register_handler("tir_report_export", …)`，宿主「重试」可用。
- **R4 参数与去重**：`protocol.py` 全部是纯函数（参数模板、cjkEncode、表单体、sessionID 解析、
  表格解析），有契约测试。幂等：同一「项目+部门+科室+起止日期」在同一导出日已有成功产物时直接复用
  （`force=true` 才重跑）；同键任务在排队/运行中时复用该任务（查重+提交在插件级锁内，避免双击竞态）。
- **R5 落盘与下载**：宿主无文件下载约定可复用（`crawl_task_runner.downloads_dir` 有 7 天轮换，
  不适合作为交付物）。最小新增：插件数据目录
  `ctx.plugin_data_dir("tir-report")/exports/<导出日>/` 下写 `<stem>.xlsx`、`<stem>.har`、`<stem>.json`
  （元数据）；`stem = tir_<项目ASCII>_<起>-<止>_<筛选键sha256前8位>`，不含用户输入的中文/路径字符。
  `GET files/<day>/<name>`：`day` 必须匹配 `^\d{4}-\d{2}-\d{2}$`，`name` 必须匹配
  `^[A-Za-z0-9_-]+\.(xlsx|har|json)$`（拒绝 `\`、盘符、`:` 流），再校验 `resolve()` 位于导出根目录内且是文件。

## 4. 模块边界

```
plugins/tir_report/
  plugin.json        id tir-report，module 页面 report.js
  protocol.py        纯函数：参数模板/编码、URL 与表单、sessionID/公钥解析、read_w_content 表格解析
  client.py          FineReportClient：login → open_report → set_parameters → read_page → export_excel
  har.py             HarRecorder：包装 session.get/post，白名单脱敏后写 HAR 1.2
  xlsx_writer.py     退路用的最小 xlsx 写出器（标准库 zipfile）
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
| GET | `state` | 配置（`credentialRef` 别名、默认参数）、可选部门/项目建议值、最近产物 |
| POST | `config` | 保存别名与默认参数（`local_guard`） |
| POST | `export` | 提交导出任务（`local_guard`）；体 `{project, department, section, startDate, endDate, force}` |
| GET | `export/<task_id>` | 任务进度与结果 |
| GET | `files` | 产物清单（按导出日倒序） |
| GET | `files/<day>/<name>` | 下载 xlsx/har/json |

错误码（闭集）：`credential_missing`（未配置别名）、`credential_unavailable`、`login_failed`、
`login_unsupported`、`session_not_found`、`export_failed`、`network_error`，各自带中文处理指引。

## 6. HAR 脱敏规则（白名单）

- URL 与 Referer：主机一律替换为 `report.invalid`（不落内网主机/IP）；查询参数只保留白名单键（`op, cmd, widgetname, format, extype, type,
  reportIndex, pn, __boxModel__, __webpage__, __fit__, browserWidth, _paperWidth, _paperHeight`），其余值换 `[redacted]`。
- 请求头：只保留 `Accept, Content-Type, X-Requested-With, Referer(去查询串)` 的值，其余（含 Cookie、
  Authorization、sessionID）值换 `[redacted]`。
- 请求体：表单只保留白名单键（`op, cmd, format, type, startIndex, limitIndex, reload`）；`__parameters__`
  解码后只保留 `XM/BM/KS/STARTTIME/ENDTIME`；JSON 体（登录）全部值换 `[redacted]`，只留键名。
- 响应：保留状态码、`Content-Type/Content-Length/Content-Disposition`、尺寸；正文只保留 ≤ 512 字节 JSON 中
  白名单键 `status/state/isExporting` 的标量值；其他（含登录、`read_w_content` 水印、xlsx 二进制）一律不记。
- `serverIPAddress`、`connection`、`cookies`、`redirectURL` 恒为空。
- 兜底自检：客户端把账号、口令、口令密文、token、sessionID 登记给记录器，写出前若任一字面值残留则**拒绝写 HAR**
  （元数据标 `harError=redaction_self_check_failed`）。测试另断言测试主机名不出现。

## 7. 测试策略

`tests/test_plugin_tir_report.py`（全离线，fake session 重放脱敏 fixture，不含真实凭据）：
cjkEncode 与 HAR 第 33 条形态一致（`问题` → `[95ee][9898]`、`[]` → `[5b][5d]`）；请求序列
`login → entry/access → parameters_d → read_w_content → check/font → export → export_polling`；
xlsx 以 `PK` 开头且首行 50 列表头；退路模式自建 xlsx 表头一致；HAR 无凭据/token/sessionID；
插件加载、写路由 `local_guard`、文件下载路径穿越被拒、幂等复用。

## 8. 分阶段与回滚

- Phase 0（待执行）：`python tools/tir_probe.py --credential-ref <别名>`（Windows，内网）→ `.runtime/tir_probe_report.json`。
- Phase 1/2（本次完成离线部分）：协议纯函数 + 客户端 + 页面 + 双产物。
- Phase 3（可选）：`python tools/build_plugin_pkg.py plugins/tir_report --key <签名密钥>`。
- 回滚：插件自包含，删除 `plugins/tir_report/` 与对应测试即可；不涉及数据库迁移；数据目录可留存。

## 9. 留待确认

1. §1 表中三项用户确认；2. Phase 0 探针结果决定 R1 路径与 R2 主路径是否成立；
3. 若导出主路径在真实环境不成立，是否接受 `mode=rebuilt` 退路（无样式）作为正式交付物。

## 10. 独立复核记录（2026-10-09，Opus 只读审查）

10 条意见全部采纳：状态措辞（1）；HAR 主机占位、HAR 1.2 其他字段置空（2）；响应正文改为白名单键（3）；
`__parameters__` 只留 5 键（4）；下载路由正则 + ASCII stem + resolve 校验（5）；R3 改为「仅进程内」、API 禁跟随重定向（6）；
插件级锁 + `register_handler`（7）；`export/<task_id>` 校验 `source`（8）；凭据别名执行时从配置读、不进任务参数（9，
宿主 `domain_credential_vault` 是 DPAPI 域账号库而非 `credential_ref` 解析器，按任务约束仍走 Windows 凭据管理器，
经 `backend.credential_provider_factory` 可替换）；R1/R2 标注为假设、退路验收列为待确认（10）。

## 11. 离线验证结论

- `__parameters__` 编码与 HAR 第 33 条**逐字节一致**（同参数 F610S / 车体工程 / 2022-07-11 ~ 2026-10-09）。
- `read_w_content` 解析（隐藏第 14 列、不闭合 `<td/>`、标题行）对 HAR 第 35 条响应重建的表格与样例 xlsx
  **12 行 × 50 列逐格一致**（数值列 `1.0` 与 `1` 的格式差异除外）——退路 `rebuilt` 的数据保真度已证实。
- 样例 xlsx 经 `header_check` 判定 50 列表头一致。
