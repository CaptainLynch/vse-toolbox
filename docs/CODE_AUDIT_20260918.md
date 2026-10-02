# VSE Toolbox 严格代码审计报告（2026-09-18）

- **审计对象**：当前工作区 `feature/scheduled-deliverables-overview-excel` 分支，含 27 个已修改文件与 10 个未跟踪文件（约 +3650/-421 行未提交改动）。
- **审计方式**：静态通读 + 定向验证。覆盖 `core/`、`services/`、`web/`（含 80 条 Flask 路由）、`web/static/*.js`（13146 行 app.js 抽样审查）、`tests/`、`*.spec` 与 `.github/workflows/`。已执行一次全量测试套件作为基线。
- **审计者**：主控模型直接执行（见「环境与工具」一节的子智能体路由故障）。
- **证据目录**：`.runtime/audit-20260918/`（全量测试日志）。
- **本报告不代表已完成真实内网、Office COM、浏览器 UI 或真实数据库的验收**，理由见文末「未验证边界」。

---

## 一、基线事实

| 项目 | 结果 |
| --- | --- |
| `python -m pytest -q tests/` | **9 failed, 2157 passed, 3 skipped**（281s，退出码 1） |
| 收集用例总数 | 2169 |
| `python tools/generate_project_map.py --check` | 通过（地图无漂移） |
| 失败用例 | `test_approved_business_ui.py::test_css_design_tokens_and_radii_constraints`、`test_deliverable_form_ui.py::test_stage_b_filters_reach_both_form_queries_and_keep_multi_select_state`、`test_overview_external_deliverables_ui.py`（2 条）、`test_overview_web.py`（4 条）、`test_scheduled_archive_admin_ui.py::test_dashboard_html_cache_buster_updated` |

`memory/CURRENT_STATE.md` 与本轮 checkpoint 文档将「`15 passed` + `156 passed`」描述为「全套回归测试」通过。该子集约 171 条，占实际 2169 条的 7.9%，**不能代表全套回归**。

---

## 二、已确认缺陷

### A1 [高] 工作区测试套件为红，记录却声称全绿

- **证据**：`.runtime/audit-20260918/pytest-full.log`，9 条失败，退出码 1。
- **根因**：未提交的交付物控制台 UI 改造中，源码内部结构发生了下列变化，而钉住这些内部结构的测试未同步更新：

| 变化 | 证据 | 影响用例 |
| --- | --- | --- |
| `renderRiskSummary` 被删除（HEAD 有定义、无调用点，属死代码） | `git show HEAD:web/static/app.js` 第 1025 行；工作区 grep 计数 0 | 2 条（作为源码切片哨兵被 `.index()` 使用 → `ValueError`） |
| `renderExternalSyncSummary` 改名/重构为 `renderOverviewBusinessSnapshots` | HEAD 第 1162 行定义、6258 行调用；工作区仅存 `renderOverviewBusinessSnapshots`（app.js:1155） | 2 条 |
| `#overview-risk-summary` 占位 div 被移除 | HEAD `dashboard.html:72`；工作区 grep 计数 0 | 1 条 |
| static 资源 cache-buster 版本号变更 | dashboard.html 现为 `?v=deliverable-console-20260916` | 1 条 |
| `renderFormFilterBar` 内部实现改变 | `current[key] = values` 字面量消失 | 1 条 |
| 新增 CSS `border-radius: 10px`（`style.css:2590`，本次 diff 新增） | 见 A3 | 1 条 |

- **性质判定**：这 9 条中，8 条属**测试陈旧（钉住源码字符串）而非功能回归**——`renderExternalSyncSummary` 的功能已由 `renderOverviewBusinessSnapshots` 承接（渲染「PAA / NCR 外部源进度（参考）」快照卡），`riskBody` 在 HEAD 上虽被 `getElementById` 取出却从未被 `renderRiskSummary` 填充，占位始终停在「加载中」。第 9 条（border-radius）**是被测代码真实违反仓库自身设计约束**，见 A3。
- **为什么仍是高优先级**：无论单条归因如何，「改动未让测试同步、且记录宣称全绿」使基线失去可信度；后续任何回归都会被这 9 条噪音掩盖，也无法用「测试通过」作为合并门槛。
- **修复方向**（待用户决定）：同步更新这 6 类断言（切片哨兵改用稳定锚点或函数边界扫描），或把测试从「源码字符串匹配」改为行为/契约断言。

### A2 [高] 读接口缺少本机来源校验，DNS 重绑定可读取内部业务数据

- **证据**：
  - `web/app.py:384-445` 定义 `_loopback_hostname` / `_origin_tuple` / `_local_web_mutation_error`，其中 `web/app.py:432` 的 `_loopback_hostname(host_name)`（Host 头校验）是抵御 DNS 重绑定的关键一步。
  - 该函数被调用于 19 处路由体内，另经 `_request_payload()`（`web/app.py:569-579`）间接覆盖 11 处，再经 `_tdc_report_query/crawl/export` 间接覆盖 9 处——**38 条变更型路由全部受保护**（此项已逐条追踪确认，非缺陷）。
  - 但 `web/app.py` 中不存在 `before_request`/`after_request` 全局钩子（`rg -n "before_request" web/app.py` 无结果）；`web/diagnostics.py:48-56` 的 `before_request` 只对 `/api/diagnostics*` 生效。
  - 因此 **所有 GET 路由没有任何 Host 校验**，包括 `/api/project-status`、`/api/overview`、`/api/settings`、`/api/excel-tasks`、`/api/excel-artifacts/<id>/download`（返回文件字节，`web/app.py:2865-2893`）、`/api/project-status/deliverables/<id>/debug-bundle`。
  - `core/config.py` 中 `FLASK_HOST = "127.0.0.1"`，故 `request.remote_addr` 恒为本机，`_local_web_mutation_error` 里的 `remote_addr` 检查实际为恒真；真正生效的只有 Host/Sec-Fetch-Site/Origin 三项。
- **可复现攻击路径**：用户浏览器访问攻击者页面（该页面在 `evil.com:5000` 提供服务，DNS TTL 置 0 后把 `evil.com` 指向 `127.0.0.1`）→ 浏览器同源请求 `http://evil.com:5000/api/...` → Flask 不校验 Host 直接响应 → 脚本读取项目状态、交付物、Excel 任务与制品文件。
- **未受影响**：38 条变更型路由（含 Aras/TDC 查询与导出，其 `base_url` 另受 `_validate_allowed_base_url` 白名单约束，仅允许 `ecm.sgmw.com.cn` / `tdc.sgmw.com.cn`），以及 `/api/diagnostics*`。
- **修复方向**：把 Host/Sec-Fetch-Site 校验提升为全局 `before_request`（或至少覆盖全部 `/api/*`），使读写路由一致；并补一条针对非 loopback Host 的 GET 拒绝测试（当前测试套件无此覆盖）。

### A3 [中] 新增 CSS 违反仓库自身强制执行的视觉约束

- **证据**：`web/static/style.css:2590` 新增 `border-radius: 10px`（本次 diff 引入，见 `git diff -- web/static/style.css` 第 137 处新增行）；`tests/test_approved_business_ui.py:371-379` 明确约束除 brand-mark(12px) 与 pill(999px) 外必须 ≤ 8px。
- **影响**：该圆角在 `.deliverable-console` 类弹层上生效，与全站 ≤8px 的组件圆角口径不一致；同时它正是 A1 中第 9 条失败的来源。
- **修复方向**：改为 8px，或若 10px 是刻意的产品口径，则同步放宽测试约束并在 `memory/DECISIONS.md` 记录理由。

### A4 [中] Excel Worker 在「停止中」窗口内可被再次启动，导致进程失去跟踪且状态错误

- **证据**：`services/excel_worker_process_controller.py`
  - `stop()` 第 115-122 行在持锁状态下把 `self._status` 置为 `"stopping"` 并写停止文件，随后**在 `try:` 处释放锁**（第 123-124 行 `process.wait(timeout=...)`，最长等待 10s 才 terminate）。
  - `start()` 第 66-69 行仅拒绝 `state == "running"`，故 `"stopping"` 会被放行；第 109 行 `self._process = process` 直接覆盖旧引用，旧 worker 进程从此不可达。
  - `stop()` 结尾第 132-135 行再次持锁把状态写回 `"stopped"`，会覆盖新 worker 的 `"running"` 状态。
- **触发序列**：`POST /api/excel-worker/stop` → 在 worker 优雅退出的最长 10 秒窗口内 `POST /api/excel-worker/start` → 产生两个同时运行的 worker（任务级租约可容忍并发，但第二个进程不再受控制器管理），且 UI/API 状态与实际不符。
- **修复方向**：`start()` 同时拒绝 `"stopping"`，或让 `stop()` 在整个等待期间持锁；停止后若发现 `self._process` 已被替换则不得回写状态。

### A5 [低-中] XML 解析加固不一致：导出通道有防注入，爬虫/认证通道没有

- **证据**：
  - 有防护：`services/ewo_export_transport.py:34` 在解析前拒绝 `<!DOCTYPE` / `<!ENTITY`，并有 4MB 上限。
  - 无防护：`services/aras_crawler.py:1199` `_parse_xml()` 与 `services/aras_auth.py:895` `_validate_user_response_has_id()` 直接 `ET.fromstring()`，既无 DOCTYPE/ENTITY 检查也无大小上限；`services/xlsx_preview.py:62/98/99/125` 同理（成员大小有 64MB 上限，但实体膨胀不受该上限约束）。
- **风险**：响应体来自内网 Aras（`ecm.sgmw.com.cn`），属受信边界内的服务器；若该服务器被入侵或返回畸形 XML，内部实体膨胀可造成内存/CPU 拒绝服务。Python 3.12 捆绑的 expat 自带 billion-laughs 放大保护，实际可利用性有限。
- **为什么仍记为缺陷**：同一代码库已在 `ewo_export_transport` 中承认并处理了这一威胁模型，其余通道未对齐，属一致性与纵深防御缺口。
- **修复方向**：抽出共用的 `_parse_xml_safely(text, max_bytes)`，统一做 DOCTYPE/ENTITY 与长度预检。

### A6 [低] Flask 未设置 `MAX_CONTENT_LENGTH`，请求体无上限

- **证据**：`rg -n "MAX_CONTENT_LENGTH" web core services` 无结果；`web/app.py:573` 直接 `request.get_json(silent=True)`。
- **对照**：`web/diagnostics.py:54-55` 对 `/api/diagnostics*` 单独做了 4096 字节上限——说明作者已知此风险，只是未全局化。
- **影响**：本机进程或 A2 场景下的浏览器脚本可提交超大 JSON 造成内存耗尽。
- **修复方向**：`app.config["MAX_CONTENT_LENGTH"]` 设为明确的少量 MB 级上限。

### A7 [低] `get_connection()` 仅在 `sqlite3.Error` 时回滚

- **证据**：`core/db_manager.py:4655-4659`
  ```python
  except sqlite3.Error:
      if conn:
          conn.rollback()
      logger.exception("数据库事务回滚")
      raise
  finally:
      if conn:
          conn.close()
  ```
- **分析**：非 `sqlite3.Error` 异常（`MappedDeliverableReadOnlyError`、`KeyError`、`ProjectStatusConcurrentUpdateError`、`ValueError`）走 `finally` 直接 `close()`。CPython 的 `Connection.close()` 会使 SQLite 回滚未提交事务，**数据安全性无实际损失**；但回滚是隐式的、且不会留下「数据库事务回滚」日志，事务未提交原因在日志中完全不可见。
- **修复方向**：改为在 `except BaseException` 中显式 rollback（保留对 `sqlite3.Error` 的日志级别区分）。

### A8 [低] `ArchiveStore._write_chunks` 的降级分支可能覆盖同名文件

- **证据**：`core/archive_store.py:314-325`
  ```python
  try:
      os.link(temp_name, destination); break
  except FileExistsError:
      continue
  except OSError:
      os.replace(temp_name, destination); break
  ```
- **分析**：`os.link` 因“目标已存在”失败会被 `FileExistsError` 分支正确处理并重试；但任何**其他** `OSError`（如权限、介质不支持硬链接）会落入 `os.replace`，而 `os.replace` 是**覆盖语义**。若此时目标名恰好已被另一进程创建（`_destination()` 的检查与建立之间的 TOCTOU），对方文件会被静默覆盖。目标名含微秒时间戳与计数器，实际碰撞概率极低。
- **修复方向**：降级分支改用 `open(destination, "xb")` 或先复查 `destination.exists()`，保留「不覆盖」语义。

### A9 [低] `core/debug_bundle.py` 的脱敏是「字段名」制，键名异常时明文外泄

- **证据**：`core/debug_bundle.py:42-67`，`_is_sensitive_text()` 只匹配 `_SENSITIVE_TERMS` 中 12 个词；`redact_debug_payload({"hdr": "Bearer eyJhbGci..."})` 中键 `hdr` 与值都不含敏感词 → **原样输出**。
- **对照（正面证据）**：另一条诊断通道 `core/diagnostic_recording.py` 采用**投影式**允许清单（`safe_metadata`/`_shape`，`_SECRET` 键过滤 + HMAC 指纹化），其模块文档「never stores raw payloads」经核验成立；`emit()` 第 253-254 行对异常也只取 `vars(exception)` 后投影。
- **影响**：`GET /api/project-status/deliverables/<id>/debug-bundle`（`web/app.py:3969`）导出的包在遇到非标准键名的凭据时会包含明文。
- **修复方向**：对 `debug_bundle` 也改用投影/指纹化，或对值做熵与 `Bearer`/JWT 形态检测（`Bearer\s+\S+`、`eyJ`-前缀 base64）。

### A10 [低] 乐观锁版本号分辨率仅 1 毫秒

- **证据**：`core/db_manager.py:104` `_LOCAL_NOW_SQL = "strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')"`，`update_project_status_deliverable` 与 `apply_project_status_manual_update` 均以该值作为 CAS 版本（`core/db_manager.py:2423-2430`）。
- **分析**：同一交付物在同一毫秒内的两次写入产生相同 `updated_at`，乐观锁无法区分，第二次写入不会触发 `ProjectStatusConcurrentUpdateError`。经 UI 触发的实际概率极低，但契约上「以更新时间作乐观锁」的强度只到毫秒。
- **修复方向**：改用单调递增的整数修订号（如现有 `sync_config_revision` 的模式）或加入行级 `revision` 列。

---

## 三、架构与可维护性观察（非缺陷）

### B1 映射有效性判定的双实现

- `core/project_status_contracts.py::project_status_manual_editability`（本次新增）与 `services/project_status_updates.py::_valid_mapping_source` / `_valid_match_rule_values` / `_validate_binding`（`services/project_status_updates.py:41-60, 409-452`）各自独立实现「映射是否有效/是否已映射」的判断。
- 我已逐条比对主要分支（空配置、`aggregate=True`、EWO v2 版本化键、列表仅限 `note` 字段、`matchKeys` 白名单、控制字符），**未发现两者产生相反结论的具体输入**；失败方向也是 fail-closed（判为只读），不构成越权可编辑。
- 但两个实现无共享来源、也无「两者一致」的断言测试；`services/project_status_updates.py:68` 的 `set(mapping) - {'note'}` 与 contracts 中的 `_PROJECT_STATUS_MAPPING_LIST_FIELDS = {"note"}` 已经是一份被复制的事实。
- 建议：抽出单一严格规范化器，由只读判定与策略层共同调用（`memory/RECOVERY_NOTES.md` 2026-09-16 条目本身也提出了这一方向）。

### B2 UI 契约测试以「源码字符串」为断言基准

- 16 个测试文件读取 `app.js` / `dashboard.html` / `style.css` 的正文字符串做断言；其中至少 2 处把函数名当作源码切片哨兵（`js_text.index("function renderRiskSummary")`）。
- 后果：任何重命名、删除死代码或调整内部实现都会让测试变红，而这些失败**不携带任何行为信息**；反过来，真正的行为回归也可能因为哨兵仍存在而被漏掉。A1 的 9 条失败全部属于此类。
- 建议：行为断言优先，UI 结构断言改用稳定的 `data-*` 契约锚点（如 `data-deliverable-run`、`data-overview-tab`）而非函数名。

### B3 前端并发控制以布尔重入锁实现

- 全仓 `web/static/*.js` 无 `AbortController`（`rg -c "AbortController"` 无结果），app.js 有 70 处 `fetch`。
- 现有的重入锁：`overviewLoading`(250)、`arasRunning`(91)、`deliverableRunning`(171)、`excelWorkspaceLoading`(9957)、`archiveJobsLoading`(10691)、`archiveRunsLoading`(10692)。模式是在入口拦截重入、`finally` 复位，对单用户本机工具足够。
- 残留风险：当**不同代码路径**（例如总览刷新与页签切换）同时请求同一视图时，布尔锁互不感知，慢响应仍可能覆盖新渲染。目前未发现具体可复现路径，故列为观察项。

---

## 四、经核验的正面结论（负向证据）

以下为本次审计**实际验证通过**的高风险面，可作为后续改动不要破坏的基线：

1. **变更型路由防护完整**：38 条 POST/PUT/PATCH/DELETE 路由全部经由 `_local_web_mutation_error()`（直接调用 19 处 + `_request_payload()` 11 处 + `_tdc_report_*` 9 处）获得 Host/Sec-Fetch-Site/Origin 校验。`web/ewo_enrichment.py:21` 的 4 条增强导表路由亦调用 `local_guard()`，并在工作完成后复查会话绑定（第 56-58 行）以拒绝中途登录切换。
2. **诊断录制采用投影而非正则擦除**：`core/diagnostic_recording.py::safe_metadata`/`_shape` 为允许清单式投影，数值直存、字符串指纹化、`_SECRET` 键直接丢弃；异常只取类型、errno/winerror/hresult 与文件/函数/行号（第 253-271 行）。`export()` 的 manifest 明确列出证据边界。
3. **凭据边界干净**：仅不透明 `credential_ref` 跨持久化/API 边界；`ResolvedCredential` 字段 `repr=False`，`resolve()` 在 `finally` 中 `clear()`（`core/credential_provider.py:19-27, 104-111`）；写入路径使用 Windows 凭据管理器 + `CRED_PERSIST_LOCAL_MACHINE`，未见明文回退分支；`delete_windows_generic_credential` 对 ERROR_NOT_FOUND 单独处理。
4. **传输层无降级开关**：全仓无 `verify=False`、无 `InsecureRequest`、无禁用证书校验的开关（`rg` 无结果）；`services/windows_http.py` 通过 WinHTTP/Schannel，`_decompress_bounded` 有 64MB 解压上限与截断检测，超时参数被 `_validate_timeout` 限制在 (0, 600] 秒。
5. **EWO 官方导出通道加固到位**：`allow_redirects=False`（生成、下载、取 token 三处）、vault URL 同源 + 路径后缀校验（`services/ewo_export_transport.py` 的 `origin()` 比对）、DOOCTYPE/ENTITY 拒绝、响应与解压大小上限、ZIP 炸弹上限（成员总和解压后 ≤96MB）、失败一律返回「结果未知需人工核查」而非自动重试。
6. **路径封闭性可靠**：`core/archive_store.py` 对根组件做 NFKC 归一 + 保留设备名 + 非法字符拒绝，全程拒绝 reparse point，落盘用 `mkstemp` + `os.link` 原子化并 `fsync`，`retention` 与 `list_subdirectories` 均做 `is_relative_to` 复核；`core/excel_tasks.py::resolve_ref` 逐层 reparse 检查 + 封闭性校验 + 角色存在性校验。`GET /api/scheduled-archive/folders?path=` 因此被限制在批准归档根内，**不构成任意目录枚举**。Excel 制品下载还会复核 SHA-256（`services/excel_task_admin.py:253`）。
7. **租约实现正确**：同步租约（`core/db_manager.py:2844-2926`）与归档租约均在 `BEGIN IMMEDIATE` 内以「条件 UPDATE 的 `rowcount == 1`」充当互斥锁，失败抛 `SyncLeaseBusyError`；长时间工作后的落库写入前会经 `_assert_lease_holder` 复核 `lease_token`，被抢占的持租方在写前失败（`SyncLeaseLostError`），不会静默写入。
8. **动态 SQL 已受控**：生产范围内 f-string SQL 共 5 处（第一轮漏计 `core/db_manager.py:4721`，由附录更正 2 补入，归入 N1）。`_utc_offset_sql` 的插值由 `_validate_lease_duration` 先做 int + 区间校验；`core/db_manager.py` 的 `PRAGMA table_info({revision_table})` 与 `core/ewo_export_jobs.py:161` 的 `{field}` 均由固定内部常量喂入（后者已在原地注释说明来源）。
9. **无危险执行面**：生产范围内无 `shell=True`、`os.system`、`os.popen`、`eval`、`exec`、`pickle.loads`、`yaml.load`；唯一 `subprocess.Popen`（`services/excel_worker_process_controller.py:101`）使用 argv 列表、`sys.executable` 或同目录 `VSE-ExcelWorker.exe` 并校验 `is_file()`。
10. **DOM 输出以 `textContent` 为主**：app.js 共 25 处 `innerHTML` 出现，其中 4 处为模板赋值（9141/9163/9267/9298），其余 21 处为 `innerHTML = ""` 清空。唯一动态插值点已转义：`web/static/app.js:9278` 的 `escapeHtml(config.defaultExportName)`（`escapeHtml` 定义于 8885，第一轮误把定义行当作插值点，见附录更正 1）；9298 的插值为常量标签。无 `insertAdjacentHTML`/`outerHTML`/`document.write`。所有 `anchor.href` 赋值均来自 `URL.createObjectURL`，无 `javascript:` 注入面。
11. **人工可编辑性契约已端到端贯通**：服务端在 `apply_project_status_manual_update` 与 `update_project_status_deliverable` **事务内**复核绑定（`core/db_manager.py:2349, 2506, 2513`），且检查先于 `_ensure_project_status_policy`，因此拒绝时不产生授权行/审计记录副作用；API 层 `web/app.py:3652` 将其映射为 409 `MappedDeliverableReadOnly`，且该 except 位于 `RuntimeError` 之前（顺序正确）；前端消费 `manualEditable`/`readOnlyReason`（`web/static/app.js:356-357, 6611`）。新增测试断言了字段归属、审计计数与阶段时间戳均无变化，非空壳测试。
12. **测试数据库隔离已修复且经实测**：`tests/test_version_and_usability.py:248-259` 通过 `monkeypatch.setattr(web_app, "DatabaseManager", ...)` 注入 `tmp_path` 库。本次全量套件运行后 `data/vse_toolbox.db` 的 mtime 仍为 `2026-09-16 21:52`，**未被本次审计运行触碰**（此前 `memory/RECOVERY_NOTES.md` 记录的 `archiveDirectory` 被真实库写入事件未复发）。

---

## 五、环境与工具

- **子智能体路由故障（需用户处理）**：本次尝试按 `AGENTS.md` 分派 `code-reviewer`（差异审查）与 3 个 `Explore`（Web API / 持久化并发 / 凭据与传输）子智能体，四个调用全部失败：
  ```
  Cannot start subagent: No reasoning level selected / 未选择思考档位
  [reason=reasoning-level-missing; selection=.../gemini-3.8-flash-high]
  ```
  即使改用 `general-purpose` 类型，同一错误复现，说明是子智能体模型的思考档位配置缺失，而非角色定义问题。按 `AGENTS.md`「模型/配额/权限失败必须报告，不得静默切换付费回退」，本次未改派其他 provider，改由主控直接完成全部审计工作。**因此本次审计的广度受单一上下文预算限制**，第三节的架构观察项与 A5/A9 的严重度评估可能未穷尽。
- `pytest-timeout` 未安装，`--timeout` 不可用（首次基线命令因此以 `EXIT=4` 失败，已去掉该参数重跑）。
- 本次审计未执行 `git commit` / `git push`，未修改任何生产代码或测试；唯一新增文件为本报告。

---

## 六、未验证边界

以下内容**没有**在本次审计中被验证，任何基于本报告的结论都不得外推到这里：

- 真实内网 Aras（`ecm.sgmw.com.cn`）/ TDC 的响应、契约与错误路径。
- Windows 凭据管理器与 DPAPI 的实际加解密、用户隔离与凭据迁移行为（仅审阅调用方式）。
- 真实 Office COM 批处理、`VSE-ExcelWorker.exe` 跨进程运行。
- 浏览器中的实际 UI 渲染与交互（未做浏览器人工验收，`docs/WEBUI_PHASE2_MANUAL_CHECKLIST_20260916.md` 的各用例仍为 `[待验]`）。
- 真实 `data/vse_toolbox.db` 的 `archiveDirectory` 原值（本轮未读取该值，也未回写；该历史遗留问题仍待用户确认）。
- `dist/`、`production*/` 下既有构建产物与 ZIP 的内部一致性（未重新校验哈希）。
- PyInstaller 在当前环境下的重新构建（仅审阅 `VSE-WebUI.spec` 与 CI workflow 的静态逻辑）。

---

## 七、建议处理顺序

1. **A1**（先恢复绿基线，再谈其他）：同步更新 6 类陈旧断言，或改造为行为断言；同时纠正 `memory/CURRENT_STATE.md` 中「全套回归测试」的表述。
2. **A2**：把 Host/Sec-Fetch-Site 校验提升为全局钩子，并补一条 GET 拒绝测试。
3. **A3**：改 8px 或记录放宽理由。
4. **A4**：`start()` 拒绝 `stopping`，修 `stop()` 的状态回写。
5. **A5 / A6 / A9**：三项低成本加固，建议合并为一次提交。
6. **A7 / A8 / A10**：按需处理。
7. **B1 / B2**：纳入后续重构，B2 的改造同时是 A1 的根治手段。

---

# 附录：第二轮独立复核（2026-09-18，主控）

本附录由主控在同一工作区、同一未提交状态下独立复核第一轮结论并补充缺口。
方法：重跑全量套件与 `compileall`、机械扫描全部路由装饰器、逐条重读被断言的源码、
核对 `git show HEAD:` 与工作区差异。**未修改任何生产代码或测试。**

## 复核结论

| 结论 | 复核结果 |
| --- | --- |
| 基线 `9 failed, 2157 passed, 3 skipped` | 复现一致（本次 279.20s，EXIT 1） |
| `compileall` / `project map --check` | 均通过 |
| A1 九条失败的符号级归因 | 逐条核实成立（`git show HEAD:web/static/app.js` 对照） |
| A2 变更型路由全受保护、GET 无 Host 校验 | 成立；`web/app.py:570` 确为集中式守卫入口 |
| A3 `style.css:2590` 圆角越界 | 成立（`border-radius: 10px`，弹层样式） |
| A4 Excel Worker 「停止中」竞态 | 成立，并补充后果见 N6 |
| A5 XML 加固不一致 | 成立（`aras_crawler.py:1195-1201`、`aras_auth.py:895` 无 DOCTYPE/ENTITY 与长度预检） |
| A6 `MAX_CONTENT_LENGTH` 未设置 | 成立（全生产范围无设置） |
| A7 仅 `sqlite3.Error` 回滚 | 成立 |
| A8 归档降级分支覆盖语义 | 成立 |
| A9 debug_bundle 按词表过滤 | 成立；`_SENSITIVE_TERMS` 确不含 `bearer`/`jwt`，`{"hdr": "Bearer eyJ…"}` 会原样保留 |
| A10 毫秒级 CAS 版本 | 成立（`_LOCAL_NOW_SQL`） |

## 引用更正（不影响结论，但影响可追溯性）

1. A1/正面结论 10 引用的 `web/static/app.js:8885` 是 `function escapeHtml` 的**定义行**；
   实际插值点是 `app.js:9278`（`escapeHtml(config.defaultExportName)`）。
   全文件 `innerHTML` 共 25 处，其中 4 处为模板赋值（9141/9163/9267/9298），
   其余 21 处均为 `innerHTML = ""` 清空；插值点有 2 个（9278 转义、9298 为常量标签），
   故「唯一插值点」宜表述为「唯一动态插值点已转义」。
2. 正面结论 8「全仓 f-string SQL 仅 4 处」未点名 `core/db_manager.py:4721`
   `f"SELECT COUNT(*) FROM {table_name}"`；该处见 N1。
3. A1 表格中 `renderExternalSyncSummary` → `renderOverviewBusinessSnapshots`
   的承接关系已核实（`app.js:1155` 定义、`6744` 调用）。

## 第一轮未覆盖的补充发现

### N1 [低] `get_table_row_count` 以 f-string 拼接表名

`core/db_manager.py:4704-4721`。入口先经 `table_exists()`（参数化查询）确认表存在，
因此可注入面被限制为「库中已存在的表名」，且生产范围内**唯一调用方是测试**
（`tests/test_db_manager.py:95`），当前不可利用。属需要清理的潜在面：
建议删除该方法，或改为白名单常量集合。

### N2 [中] 归档运行「记录失败」失败时被静默吞掉

`services/scheduled_archive_runner.py:740-750`：把运行标记为 `failed` 的
`finalize_archive_run` 被 `except Exception: pass` 包裹。若该回写本身失败，
运行行可能停留在非终态并继续持有租约直至过期，且不产生任何诊断记录
（租约过期是兜底，但现场不可复现）。至少应转发到 `core/diagnostic_recording`。

### N3 [低] 显示版本可被 EXE 同级文件覆盖，且无单一事实源

`core/version.py:48-67` 在冻结运行时把 **EXE 同级目录排在 `sys._MEIPASS` 之前**。
任何人放置一个 `version.json` 在 EXE 旁，即可让界面显示任意「版本/渠道」
（例如伪装 production）。这不是权限边界，但会破坏支持与诊断的可信度。
同时版本号无单一事实源：CI 默认 `0.1.0`/`production-validation`
（`.github/workflows/build-windows-exe.yml:93-96`），`VSE-WebUI.spec:24` 仅在
env 注入时才打包 `version.json`（否则冻结包退化为「独立运行包」），
而 `memory/CURRENT_STATE.md` 记录的人工构建为 `0.2.0`。

### N4 [低] 根目录 `version.json` 未被忽略，且 CI 会写入检出目录

`.gitignore` 覆盖 `dist/`、`build/`，但未忽略根 `version.json`；
CI 步骤 `build-windows-exe.yml:102` 会将其写入检出目录。
本地执行该步骤既污染工作区，又因 N3 的搜索路径 #1 改变源码模式的版本显示。

### N5 [低] 死代码

`core/db_manager.py:134` 的 `MappedDeliverableReadOnly = MappedDeliverableReadOnlyError`
别名无任何引用（API 侧使用字符串字面量 `"MappedDeliverableReadOnly"`）。

### N6 [中，A4 补充] 竞态的第二重后果：新 worker 失去停止文件

`services/excel_worker_process_controller.py` 中 `stop()` 在等待结束后调用
`_cleanup_stop_file()`，而该方法读取的是**实例属性** `self._stop_file`。
若等待窗口内 `start()` 已把它替换为新 worker 的停止文件路径，
则 `stop()` 会删除**新 worker** 的停止文件（旧 worker 正常终止不受影响）。
即 A4 的竞态不仅造成状态错乱与进程失管，还会让新 worker 的停止通道失效，
须由下一次 `stop()` 重新写入。修复 A4 时应以局部变量快照 `stop_file`
并在回写前校验 `self._process is process`。

## 本轮额外核实为无缺陷的面（可与第一轮正面结论并列）

- 写口守卫**顺序**正确：机械核对全部 20 个处理器体内 + `_request_payload()`
  的集中式守卫，**没有任何处理器在校验前先执行写库/调服务**。
  （提醒后续审计者：`_request_payload()` 内含守卫，仅扫描处理器正文会误判为缺失。）
- `BEGIN IMMEDIATE` 与本仓库连接工厂相容：`core/db_manager.py:4644-4649` 使用默认
  `isolation_level`、`timeout=10`，新增的两处（:2349、:2506）在各自方法中均为首条语句，
  不会触发「事务中再开事务」；非 `sqlite3.Error` 异常经 `close()` 隐式回滚，
  数据安全性无损失（可读性见 A7）。
- 手工写拒绝路径**无副作用**：`_assert_project_status_manual_editable` 先于
  `_ensure_project_status_policy`，被拒的映射写不会插入授权行或审计记录。
- 归档保留删除的封闭性：`execute_retention` 校验相对路径、`..`、reparse point
  与父目录收敛后才 `unlink`，且 CLI 默认 dry-run（`main.py:1593-1610`）。
  **补充提示**：`plan_retention` 以「根目录下所有超期文件」为候选，不按命名约定过滤，
  若归档根被指向共享目录，`--execute` 会连带删除无关旧文件——操作前须确认根目录专用。
- Excel 路径封闭性、URL allowlist（scheme/userinfo/端口归一/精确主机名）、
  WinHTTP 默认证书校验、`shell`-free 子进程、PEM/Bearer/参数级脱敏：
  均按第一轮正面结论独立复现，未见新问题。

---

# 第三轮：修复验证（2026-09-18 08:20 起）

修复轮（02:30–08:27）落地后在同一未提交工作区重新审计：验证修复是否真实、是否被测试掩盖、是否引入新缺陷。
方法：重跑全量套件、逐条对照 `git show HEAD:` 与工作区、对脱敏与 XML 守卫做**可执行反例**验证、机械扫描路由与解析点。
**本轮未修改任何生产代码或测试。**

## 3.1 基线

| 项目 | 修复前（第一轮） | 修复后（本轮实测） |
| --- | --- | --- |
| `python -m pytest -q tests/` | 9 failed, 2157 passed, 3 skipped | **2182 passed, 3 skipped, 0 failed**（229.33s，EXIT 0） |
| 收集用例 | 2169 | 2185 |
| 9 个历史失败用例 | 全部失败 | 定向重跑 **13 passed** |
| `flake8`（12 个修改模块） | 未测 | EXIT 0（独立复现） |
| `git diff --check` | EXIT 0 | EXIT 0（独立复现） |
| 地图 `--check` | 通过 | 通过 |

## 3.2 已修复并独立验证

- **A1**：9 个历史失败用例全部恢复通过（定向重跑 13 个用例）。归因确认：1 个改源码（CSS），8 个改测试；未新增 skip/xfail、未删除 `pytest.raises`、未放宽数值边界。
- **A2**：新增全局 `before_request(_enforce_local_web_access)`，Host 回环校验覆盖**所有方法与所有路径**（含此前完全裸奔的 GET 下载路由），比第一轮建议更彻底。附 6 个新测试（4 个非法 Host 参数化 + 跨站 GET + 16MB+1KB 413）。
- **A3**：重算全表圆角，除白名单 12px/999px 外无 >8px 取值。
- **A4 + N6**：`start()` 拒绝 `stopping`；`status()` 不再把 `stopping` 覆盖为 `running`；`stop()` 快照本地 `stop_file`、以 `self._process is process` 守卫状态回写、竞态分支下只清理自己的停止文件，并为 `kill()` 后的 `wait()` 补 `TimeoutExpired` 兜底。
- **A5**：独立全范围扫描确认生产范围内 4 个 XML 解析点**全部**具备 DOCTYPE/ENTITY 拒绝 + 体积上限，无遗漏的裸 `ET.fromstring`。
- **A6**：`MAX_CONTENT_LENGTH = 16MB` + 413 处理器。
- **A7（更正第一轮结论）**：`get_connection()` 现已增加 `except BaseException as exc:` 分支，显式回滚并记录应用层异常类型。第一轮判定「未修复」是**我的误读**——当时用 `head -20` 截断了 grep，未看到该分支。
- **A8**：降级分支改为先以 `open(destination, "xb")` 独占占位、`FileExistsError` 时重试，`os.replace` 不再具备静默覆盖语义。
- **A9（部分）**：`debug_bundle` 增加值形态规则（`Bearer`/`eyJ…` 正则）。第一轮 PoC `{"hdr": "Bearer …"}` 现已 `[FILTERED]`。
- **N1（更正第一轮结论）**：`get_table_row_count` 增加 `isascii() and isidentifier()` 前置校验。同样属我第一轮截断读取导致的误判。
- **N2**：归档终态回写失败改为 `logger.exception`，不再静默。
- **N3**：`core/version.py` 检索顺序改为 `sys._MEIPASS` → EXE 同级 → 应用根，旁置文件无法再覆盖内嵌元数据。
- **N4**：`.gitignore` 增加 `/version.json`。
- **第一轮未提出、本轮确认的额外正确修复**：归档租约三处补 `BEGIN IMMEDIATE`（关闭了「持有者断言→写入」之间的 TOCTOU，此前同步租约已有而归档路径没有）；`_safe_filename` 改为对 stem 截断，修复了旧实现可能截掉 `.xlsx` 后缀的缺陷；`xlsx_preview` 在 `<c>` 缺 `r` 属性时按列自增推导坐标（旧实现会对合法文件抛 `XLSXPreviewError`）。

## 3.3 仍未修复（修复记录亦未声明已修）

- **A10**：`_LOCAL_NOW_SQL` 仍为毫秒精度，乐观锁版本号分辨率不变。
- **N5**：`core/db_manager.py:134` 的 `MappedDeliverableReadOnly` 别名仍无引用。

## 3.4 修复轮**新引入**的缺陷

### C1 [中] `core/redaction.py` 键名匹配为**全等匹配**，复合键名凭据明文外泄

`_JSON_RE` 要求引号内的键名**整体**等于敏感词表之一，因此 `user_password`、`dbPassword`、`old_token`、`api_secret_key`、`access_token` 等一律不脱敏。实测（值取中性串以排除值形态规则干扰）：

| 键名 | `core/redaction.py` | `core/debug_bundle.py` |
| --- | --- | --- |
| `password` / `apiKey` | 脱敏 | 脱敏 |
| `user_password` / `dbPassword` / `old_token` / `api_secret_key` / `access_token` | **未脱敏** | 脱敏 |
| `密码` / `口令` | **未脱敏** | **未脱敏** |

`access_token` 是 OIDC 标准字段名，本仓库确有 OIDC 流程（`/auth/oauth/token`、refresh token），因此这不是构造出来的耦合。
**缓解**：新增的 `_JWT_RE` 会按**值形态**命中 `eyJ…` 开头的 JWT，与键名无关；故 JWT 形态的 access token 仍被拦截，**不透明 token** 才会真正外泄。
**加重因素**：两条脱敏路径现已不一致，且能力**较弱的那条**（`redaction.py`）才是接入错误信息（`_sanitize_error_message`）、API 行（`_safe_rows`）、诊断与同步记录落库的路径。

### C2 [低] `core/debug_bundle.py` 改用子串匹配后**过度脱敏**

`_is_sensitive_text` 对短词做子串匹配，新增的 `sid` 会命中 `outside`/`residual`/`consider`/`president`，整串被替换为 `[FILTERED]`。实测 `redact_debug_payload({"note": "residual risk on outside wall"})` → `"[FILTERED]"`。方向是 fail-safe（不泄漏），但会静默销毁诊断包里的正常业务文本——而诊断包正是排障用的产物。

### C3 [低] 中文敏感键在**两条**脱敏路径中均未覆盖

`rg` 在 `core/redaction.py` 与 `core/debug_bundle.py` 中均找不到 `密码`/`口令`/`凭证`/`秘钥`/`私钥`，实测 `{"密码": "…"}` 与 `口令=…` 均原样透出。本仓库业务语言为中文，后续任何中文字段承载凭据都会静默绕过脱敏。

### C4 [低] `services/xlsx_preview.py` 新增的 DOCTYPE/ENTITY 守卫对 UTF-16 成员失效

`_parse_member_xml` 在**原始字节**上做 `b"<!DOCTYPE" in raw.upper()`；UTF-16 成员的字节为 `<\x00!\x00D\x00…`，ASCII 子串匹配失败，而 `ET.fromstring` 仍能按 BOM 解码并展开实体。可执行反例（本轮实测）：

| 输入 | 守卫是否拦截 | `ET.fromstring` 结果 |
| --- | --- | --- |
| UTF-8 + DOCTYPE/ENTITY | 拦截 | — |
| **UTF-16 / UTF-16-LE + DOCTYPE/ENTITY** | **未拦截** | 成功，实体被展开 |
| UTF-16，732 字节、6 层嵌套实体 | 未拦截 | **展开为 1,000,000 字符，无异常** |
| UTF-16，842 字节、7 层嵌套实体 | 未拦截 | `ParseError: limit on input amplification factor (from DTD and entities) breached` |

**定级依据**：真正的上限来自 CPython 3.12 内置 expat 自身的放大因子保护（约 10⁶ 字符即触发），而非这道守卫；因此这不是内存炸弹，而是**纵深防御缺口**——修复轮声明的「严格拦截实体扩展」在这一输入类别上完全不成立。修法很轻：先解码成员再检查，或同时匹配 UTF-16LE/BE 字节形态。

## 3.5 测试质量回归（A1 的代价）

- **正当**：cache-buster 值更新（本就是变更探测测试）；`current[key] = values` → `draft[key] = values.slice()`（断言反而更强，现在校验了防御性拷贝）；`renderRiskSummary` → `renderOverviewBusinessSnapshots` / `overviewBusinessSnapshotCondition` 改名跟进；移除 `#overview-risk-summary` 与 `risk-summary` 标记断言——第一轮已核实该 div 在 HEAD 上从未被填充（`renderRiskSummary` 有定义无调用），是永久停在「加载中」的坏占位，删除断言属正确清理。
- **被放宽**：
  1. `tests/test_overview_external_deliverables_ui.py`：`assert "progressOrDate: job.lastSuccessAt" in source` → `assert "job.lastSuccessAt" in source`。该测试名为 `test_external_rows_preserve_success_time_and_selected_archive_job`，但新断言在 13000 行文件中只要出现 `job.lastSuccessAt` 即通过（现存于 1904/2462/6424/6508/11356 等多处无关函数），**已不再验证它声称验证的行为**。
  2. 同文件：`assert "selectedArchiveJobKey = item.externalJobKey" in source` → `… or "selectedArchiveJobKey = definition.archiveJobKey" …`。两种形态在 `app.js` 中确实都存在（1222/6653/6662），但两个字面量的 `or` 无法有意义地失败。
  3. `tests/test_overview_web.py`：`assert "loadOverview" not in js_text` → `assert "loadOverview(" not in js_text`。属意图保留型适配（新增 `loadOverviewBusinessSnapshots` 所致），但裸引用或函数定义现在可放行。
- **未改变的结构债**：切片哨兵仍是「函数名」`js_text.index("function overviewBusinessSnapshotCondition")`，下次改名会再次同时打断多个用例（第一轮 B2）。

## 3.6 修复记录（`memory/CURRENT_STATE.md`）的准确性核验

| 记录声称 | 核验结果 |
| --- | --- |
| `pytest` 全绿 | **成立** |
| `get_connection()` 扩充捕获 `BaseException` | **成立** |
| `get_table_row_count()` 增加纯 ASCII 标识符校验 | **成立** |
| `flake8` EXIT 0、`git diff --check` EXIT 0 | **成立**（独立复现） |
| 「2,177 passed, 3 skipped」 | **与树不符**：当前实测 2182 passed（收集 2185），记录不是由最终状态产出 |
| 「扩展中文敏感凭证关键词（密码、口令、凭证、秘钥、私钥）」 | **不成立**：两个文件中均不存在这些词，实测中文键确实漏出（见 C3） |
| 「强制 100MB 成员体积上限」 | **不成立**：实际为 64MB（`_MAX_MEMBER_BYTES`），另 96MB 成员总和、64MB 归档上限 |

存在不实声称这一点本身即需关注：它使「已修复」无法仅凭记录采信，必须逐条复核——本轮正是因此才发现 C1/C3。

## 3.7 修复轮附带的无关联改动（已逐条比对，非缺陷）

- **SQL 下沉**：把 `feishu_tasks` / `deliverables` 的写入从 `services/` 移入 `core/db_manager.py`，新增 5 个公开方法（`save_feishu_tasks`、`sync_unsynced_feishu_tasks_to_deliverables`、`persist_scraped_deliverables`、`get_deliverables_for_export`、`get_feishu_tasks_summary`）。与 HEAD 的内联 SQL 逐一对照：列名、默认值、`synced_ids` 后置 `UPDATE` 的两段式、`ORDER BY d.due_date ASC` 均一致，并额外加了 `BEGIN IMMEDIATE`；调用方保留 try/except + 日志 + 重新抛出。唯一损失是重复跳过路径上的 `logger.debug("邮件 %s 已解析过，跳过")`。该改动方向与「`core/` 拥有 SQLite」的既定边界一致，但**未写入 `memory/DECISIONS.md`**。
- **COM 生命周期**：`services/office_toolbox.py` 新增两处 `pythoncom.CoInitialize()`/`CoUninitialize()`，以 `co_init` 标志确保只在初始化成功后才反初始化（与 `services/windows_http.py` 同一防御写法），配平正确，无过度反初始化风险。
- **COM 批量改写**：`excel_toolbox`/`office_toolbox` 由逐格 `sheet.range((r,c)).value` 改为二维矩阵整体读写。契约（签名、返回类型、异常）未变，但你机器上无 Office，**本轮无法验证真实 COM 行为**。
- `setup.cfg` / `.gitignore` 去 BOM 与中英注释调整：格式性，无行为影响。

## 3.8 本轮未验证边界

- 真实 Office/WPS 宿主上的 COM 矩阵读写与 CoInitialize 变更（无 Office 环境）。
- 归档/同步租约新增的 `BEGIN IMMEDIATE`：由代码审读 + 测试覆盖确认，未做真实双进程竞争复现。
- 真实内网 Aras/TDC、DPAPI、浏览器 UI 人工验收（与第一轮相同，未被本轮修复改变）。

## 3.9 环境

- **子智能体路由已恢复**：本轮成功并行 4 个 Explore 分工（测试削弱复核、XML 加固全范围扫描、无关服务改动核查），其中 1 个报告因空 result 丢失后重新索取成功。较第一轮「全部 spawn 失败」是实质改善。
- **本轮我自身的两次误判已更正**：A7 与 N1 第一轮判「未修复」，实为使用 `head -20` 截断 grep 所致，本节 3.2 已更正。这与第一轮报告中的两处引用错误同源——**结论必须回到完整上下文再下**。
