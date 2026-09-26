# Recovery Notes

## 2026-09-25 — 诊断披露：`emit` 事件名留存不等于载荷可读

- **症状**：`emit("ncr_department_filter", {"kept": 2, "dropped": 4, ...})` 调用成功、事件名在
  `events.jsonl` 里也在，但事件 `data` 是 `{}` —— 运维读不到任何数字，等同于没有披露。
- **根因**：`core/diagnostic_recording.safe_metadata()` 只做**白名单投影**：
  - 数字键必须在 `_NUMBER_FIELDS`；
  - 文本键必须在 `_TEXT_FIELDS` **且**取值在闭集 `_VALUES` 内（否则退化成 `ref:<hash>` 指纹，不可读）；
  - 布尔只允许 `ok/hit/reasonAvailable/cancelled`；其余键一律丢弃。
  验证一行：`python -c "from core.diagnostic_recording import safe_metadata as s; print(s({'kept':2},'x'))"` → `{}`。
- **正确做法**：新增诊断时先用 `safe_metadata(payload, 'salt')` 自测非空；键用白名单名
  （数字：`kept_count`/`dropped_count`/`row_count`/`record_count`…；文本：`report_type`/`remedy`…），
  文本值若是产品词条，按既有做法加入 `_VALUES`。并配一个经 `Recorder` 录制 → 导出 → 读 `events.jsonl`
  的端到端测试（`tests/test_diagnostic_recording.py::test_product_disclosure_payloads_survive_recording`）。
- **另一条同轮教训**：**"读旧数据时告警"不可用**——`normalize_form_rows` 只在发布路径被调用，
  快照读取路径不重新归一化。凡是想靠"读时诊断"提示历史数据问题的设计都要先确认那条读取链真的会重新归一化。

## 2026-09-25 — 审计修复轮：行形状变更的连带面与记忆文件读取

- **给快照行加键会打破 exact-equality 断言**：本轮 `named_row()` 增带 `values` 后，命中两处硬断言
  （`tests/test_scheduled_archive_connectors.py` 的 `collection.form_rows == (...)`、
  `tests/test_project_status_connectors.py` 用合成 `NcrWorkbookRow(values=())` 构造的夹具）。
  下次改行形状前先 `rg -n "form_rows ==|named_row\(\)" tests services`，并注意合成夹具的
  `values` 长度不等于契约宽度（不能断言 `len(row["values"]) == 64`）。
- **用 `Get-Content` 看 `memory/*.md` 会显示乱码**：本机 PS 5.1 默认按 ANSI 读 UTF-8 无 BOM 文件，
  中文全成 `鈥?` 之类。判读记忆文档必须用文件读取工具；`Get-Content -Encoding UTF8` 或
  `-Raw -Encoding UTF8` 也可，但不要据此判断文件是否损坏。
- **重建单文件包用新目录**：`--workpath .runtime/pyinstaller-webui-<新标签>` +
  `--distpath dist/<新标签>`，避免覆盖上一个已交付工件；版本靠 `VSE_TOOLBOX_VERSION/CHANNEL/BUILD_ID`
  环境变量注入 spec，冒烟脚本里的 `rawVersion`/`buildId` 断言必须同步改（否则误报失败）。
- **中文 smoke 脚本**：写完后用 `python -c "...write(b'\xef\xbb\xbf'+...)"` 补 BOM，
  否则 PS 5.1 解析中文 here-string/字符串会崩（同 2026-09-25 首轮记录）。

## 2026-09-25 — 单文件 EXE 构建与出厂冒烟：三个 Windows 侧坑

- **本机 PowerShell 是 5.1（不是 pwsh 7）**：`.ps1` 脚本含中文且**无 BOM** 时按 ANSI 解码，
  会出现莫名其妙的语法错（本轮报 `The Try statement is missing its Catch or Finally block`）。
  写含中文的脚本后必须转成 UTF-8 **with BOM**：
  `[IO.File]::WriteAllText($p, (Get-Content $p -Raw), (New-Object Text.UTF8Encoding $true))`
  或 `Path.write_text(text, encoding='utf-8-sig')`。
- **PyInstaller onefile 会派生真正的子进程**：`$proc.Kill()` 只杀引导进程，应用子进程继续占用端口，
  并且因为子进程仍持有 stdout 管道，`StandardOutput.ReadToEnd()` 会**永久阻塞**（本轮工具调用因此超时）。
  正确做法：用 `taskkill /F /T /PID <pid>` 杀整棵树，再轮询 `Get-NetTCPConnection -LocalPort <p> -State Listen`
  确认释放；冒烟脚本不要重定向 stdout（继承控制台即可）。
- **`Start-Process` 在本机会直接抛异常**：环境里同时存在 `no_proxy` 与 `NO_PROXY`，
  5.1 重建环境块时大小写不敏感字典冲突（`Item has already been added. Key in dictionary: 'no_proxy'`）。
  改用 `System.Diagnostics.ProcessStartInfo`（`UseShellExecute=$false`）启动。
- **`/api/version` 的字段名是 `rawVersion` / `displayVersion`**，没有 `version` 键；
  冒烟断言写成 `data.version` 会得到空串并误判为"版本丢失"（本轮踩过，EXE 本身没问题）。

## 2026-09-25 — 看板过滤不能改变「payload 下标」语义（本轮已修，勿再退化）

- **症状**：把交付物明细表改成 `rows.filter(deliverableBoardVisible)` 后，
  `renderDeliverableDetails` 的 `forEach((rawRow, index))` 收到的是**过滤后下标**，
  而 `toggleDeliverableDetail` / `expandOverviewDetail` / `startDeliverableEdit`
  全都用 `overviewSavedState.deliverables[index]` 回查交付物 →
  点「查看明细」会打开**错误的交付物**（D1/D4 被隐藏后整体错位一格）。
- **正确做法**：过滤只跳过渲染，**下标必须保持 payload 下标**：
  `rows.forEach((rawRow, index) => { if (!deliverableBoardVisible(rawRow)) return; ... })`，
  同时把下标写进 DOM（`row.dataset.deliverableIndex = String(index)`），
  `overviewDetailsRow(index)` 优先按该属性定位（`querySelectorAll("tr")[index]` 在过滤后不再等价）。
- **回归护栏**：`tests/test_overview_web.py::test_board_visibility_contract_hides_d1_d4_and_removes_snapshot_panel`
  已 pin 上述四点；改动看板渲染时先跑它。
- **同类风险**：任何"为了隐藏某些项"而 `.filter()` 数组后仍用位置下标的地方
  （卡片区用 `deliverables.forEach` + `shouldShowDeliverable` 早退，因此天然安全）。

## 2026-09-25 — NCR/ARAS 结构统一轮：四个已踩过的坑

- **`core/report_headers.json` 的 `ncr_detail.dataHeaderRow` 曾是 4（错位）**：`headerRows[0]`
  才是稳定的 17 个命名列（状态/提交日期/项目/区域/NCR编号/当前节点…）+ 车型矩阵列；
  `headerRows[4]` 是矩阵带（TBD/车型号）。`_column_specs` 用 `dataHeaderRow` 取标签，
  于是按标签取值（`_positional_value` / `dimension` 归一化）全部落空。官方工作簿解析
  （`_official_form_rows` → 现 `parse_ncr_workbook`）一直用 `headerRows[0]`。
  **改动前先确认 `dataHeaderRow` 与解析用的表头行是同一行**；`ncr_progress` 是 1，`ncr_detail` 现为 0。
- **`_WorkbookPreviewTruncatedError` 不是 NCR 专属**：TDC 官方工作簿投影
  （`_official_workbook_rows`）与 TDC collector 仍在用它。删 NCR 旧解析时若连类一起删，
  会得到 `F821 undefined name`。NCR 已迁移到「簿记事实 + 准入停机原因」，TDC 保留原类。
- **`_official_form_rows` 曾被同步路径跨模块调用**（`project_status_connectors` → `scheduled_archive_connectors`）。
  重构时必须新建共享模块（`services/aras_ncr_workbook.py`）而不是在其中一侧保留私有函数，
  否则又出现两套解析。`parse_ncr_workbook` 在同步路径是**函数内 import**，
  因此测试打桩要 patch `services.aras_ncr_workbook.parse_ncr_workbook`，
  归档路径是模块级 import，打桩要 patch `services.scheduled_archive_connectors.parse_ncr_workbook`。
- **大块 JS 删除会让行号整体漂移**：本轮 `web/static/app.js` 删了首页快照面板与死快照卡共约 340 行，
  所有用行号/切片标记的测试（`_js_slice(js)`）会一起失效。删除顺序建议：先用 python 按
  「起始函数签名 + 下一个函数签名」定位整块删除，再全域 grep 残留符号，最后修
  `tests/**` 中以被删函数为切片端点的用例（本轮改了 `test_overview_web.py`、
  `test_deliverable_statistics.py`、`test_overview_external_deliverables_ui.py`、
  `test_deliverable_sync_wizard_enhanced.py`）。

## 2026-09-25 — 声明式契约要通过"单键探针"测试才能算一致

- 只断言「filterKeys ⊆ matchKeys」不足以发现漂移。本轮有效的判定法是：
  ① 每个声明键**单独**出现时必须让过滤器结果发生变化（证明真的进入查询）；
  ② 未声明的探针键不得改变过滤器（证明连接器不偷读未声明键）。
  该测试当场暴露了 D6 声明了从不消费的 `sectionCode`、D7/D8 缺 4 个实际消费的键。
- 同理，命名行归一化要断言「按已批准表头标签取值」而不是「字典位置」：
  `table_payload('ncr_progress'|'ncr_detail', [命名行])` 现在通过
  `_LABEL_KEYED_REPORTS` + `_label_source_fields()` 派生 index→标签 映射，
  新增报表只需加进 `_LABEL_KEYED_REPORTS`（如仍按列序号维护字段表，就留在
  `_SOURCE_FIELDS_BY_REPORT` 显式声明）。

## 2026-09-22 — 「不完整」类失败必须自带完整性事实（本轮已修，勿再退化）

- **症状**：D5 数模一键启用报 HTTP 422 `mapping discovery query was incomplete`，
  但原因（`stop_reason`、去重后条数、重复数、声明总数/页数）**在错误响应里被丢弃**，
  两轮修复都只能靠猜（ZCode 归因 `duplicate_records`、我归因待证）。
- **修法**：`web/app.py:_require_complete_mapping_result` 失败时下发
  `error.diagnostic = {stopReason,rowCount,uniqueCount,duplicateCount,declaredTotal,declaredPages,fetchedPages}`；
  `_json_error` 是唯一错误出口；前端 `ewoPolicyPaginationDiagnosticText()` 渲染为可读尾注。
- **更省事的取证路径（无需开诊断记录器）**：`POST /api/tdc/data-model/crawl-all` 是异步任务，
  其结果工件由 `_tdc_result_data()` 生成（`web/app.py:1456-1478` + `:2767`），
  **本身就含 `stop_reason/unique_count/duplicate_count/total/pages/fetched_pages`**，
  经 `GET /api/tasks/<task_id>/result` 可取；与 mapping discovery 同爬虫、同
  `page_size=50`、同 `max_pages=100`，因此 stop_reason 等价。
- **另一个坑**：`GET /api/diagnostics/bundles/<identity>` 的诊断包只有先
  `POST /api/diagnostics/start`（或开页面右下角诊断浮窗）才会记录；
  `TDCHttpDiagnosticEvent(stage="pagination")` 里有同样的字段。

## 2026-09-22 — Node VM 行为测试按「源码切片 + 固定子节点索引」断言，改动布局即假红

- `tests/test_deliverable_sync_wizard_enhanced.py` 从 `function renderSnapshotSyncCard`
  切到 `async function loadDeliverablePolicy` 求值，并按
  `card.children[3]`（actions）、`actions.children[0|2]`（同步按钮/状态文本）取值。
- **因此**：① 与卡片配套的新函数/常量必须放在这两个函数**之间**，否则沙箱里 undefined；
  ② actions 内前三位的顺序是契约，新增控件只能 `append` 到末尾；
  ③ 沙箱里要用 `globalThis.xxx` 暴露状态，`let/const` 声明的变量从外部不可见（`sandbox.xxx` 为 undefined）。

## 2026-09-22 — 归档 sync-now 的「假成功」链路（已验证根因，勿再踩）

- **现象**：交付物详情页点【立即同步快照】提示「快照同步成功，已刷新最新明细与图表。」，
  但交付物依旧「暂无表单快照数据」。
- **链路**：`ArchiveSyncRunner.run_once` 使用 `list_archive_jobs(enabled_only=True)`
  （`services/scheduled_archive_runner.py:533`）→ 任务停用时返回
  `outcome="not_ready" / errorType="missing_job" / errorMessage="enabled archive job was not found"`
  → `ScheduledArchiveAdminService.sync_now` 原样包装、不抛异常 → `web/app.py:4081` 返回
  **HTTP 200 + `ok:true`** → 前端只校验 `resp.ok/body.ok`（`web/static/app.js:2933`）→ 判定成功。
- **默认状态必现**：新库 6 个内置归档任务全部 `enabled=0`、`credential_configured=False`
  （`core/db_manager.py` DDL `enabled INTEGER NOT NULL DEFAULT 0`）。
- **复现脚本**：`.runtime/repro_snapshot_sync.py`（临时库、无副作用）→ 输出 `.runtime/repro_out.txt`。
- **排查提示 1**：`tags`/`exitCode` 非零（本次 `exitCode=2`）也是失败信号，前端不得忽略。
- **排查提示 2**：本机 `scheduled_archive_runs` 为空**不等于**归档任务从未跑过——
  `deliverable_form_snapshots` 中可能存在 `source_run_id` 指向已轮换/清理的 run（如 101-103）。
- **排查提示 3**：PowerShell 控制台 `Get-Content` 会把 UTF-8 中文显示成乱码（GBK 控制台），
  判断文件是否损坏必须用 read 工具而非控制台输出；据此误判会导致无谓的"修复"。

## 2026-09-22 — ProjectStatusSyncScheduler 全量同步 trigger_type 契约违背与 Mock 假绿排查

- **Mock 对象掩盖契约违背陷阱**：在 `ProjectStatusSyncScheduler.trigger_sync_all` 与 `web/app.py` 中，曾传入 `trigger_type="manual_all"`。底层 `ProjectStatusSyncRunner.run_once` 与数据库表约束（`CHECK (trigger_type IN ('sync_now', 'scheduled'))`）会 100% 拒绝该类型并抛出 `ValueError`。但由于单元测试 `tests/test_project_status_scheduler.py` 使用了无校验的 `FakeRunner` Mock，且在测试中断言了 `c["trigger_type"] == "manual_all"`，导致测试不仅全部绿灯，甚至将非法契约反向固定。**防范规则**：对于跨层传递的枚举/状态值，必须至少编写一个接入严格契约校验桩（如 `ContractEnforcingRunner`）或真实底层 Runner 的用例，确保 mock 测试不脱离底层真实契约。
- **Safe DOM 违规检测**：新增 UI 特性时严禁使用动态字符串插值 `innerHTML = \`...\``。即便需要渲染带格式（如 `<strong>`、emoji）的提示条，也应通过 `overviewEl` 与 `document.createTextNode` 组合构建安全树，确保全项目 Safe DOM 零动态 `innerHTML` 的红线不被突破。

## 2026-09-16 — 非 UI 严格审计修复与 PyInstaller 版本元数据打包边界

- **测试数据库隔离陷阱**：`DatabaseManager` 默认使用 `core.config.DB_PATH`，不读取 `VSE_TOOLBOX_DATABASE_PATH` 环境变量。在编写涉及 Web API / settings 的测试时，必须通过 `monkeypatch.setattr(web_app, "DatabaseManager", lambda *a, **kw: db_instance)` 显式传入基于 `tmp_path` 构造的实例；仅设置环境变量会导致测试悄悄修改真实 `data/vse_toolbox.db`。
- **PowerShell UTF-8 BOM 与 Python json 解析**：`.NET` / PowerShell 的 `[System.Text.Encoding]::UTF8` 默认输出带有 `0xEF 0xBB 0xBF` 的 UTF-8 BOM。Python 标准 `encoding="utf-8"` 在 `json.loads` 时会抛出 `JSONDecodeError: Unexpected UTF-8 BOM`。修复策略为双向加固：写侧使用 `New-Object System.Text.UTF8Encoding $false` 强制无 BOM，读侧（`core/version.py`）统一采用 `encoding="utf-8-sig"`，保证对无 BOM 及历史带 BOM 格式皆能安全兼容。
- **PyInstaller spec 动态 datas 陷阱**：若 spec 的 `datas` 列表中硬编码了当前不存在的文件（如 `('version.json', '.')`），PyInstaller 在无环境变量且无对应文件时会直接退出（exit 1）。正确方式是仅在确定存在有效元数据时动态将临时文件加入 datas（`*version_datas`），且临时文件生成在独立系统临时目录并在退出时通过 `atexit` 清理，严禁在仓库根目录留下脏文件，亦不可把工作区残留的历史旧 `version.json` 意外打包。
- **映射编辑权限的控制字符与超长防绕过**：规则字符串、映射字段与外部稳定键必须使用 `_has_control_chars()`（检测 ASCII < 32 及 127-159 范围）与 `_TEXT_LIMITS` 检查。如 `{"incident": "FM-1\u0000"}` 这类包含控制字符或超长 JSON 必须 fail-closed 判定为 `manualEditable=False, PROJECT_STATUS_INVALID_MAPPING_READ_ONLY_REASON`；且在 `apply_project_status_manual_update` 与 `update_project_status_deliverable` 事务开启后立即检查，拒绝时不得对业务行、阶段、字段归属或审计记录产生任何写副作用。

## 2026-09-14 — 生产测试双 EXE 已构建并完成离线冒烟

- 使用 canonical `tools/build_excel_bundle.ps1` 生成 `dist/VSE-Production-Test-20260914/`，包含 `VSE-WebUI.exe`、`VSE-ExcelWorker.exe` 与 `SHA256SUMS.txt`；清单哈希已用独立 `Get-FileHash` 重新核对。
- 依赖隔离验证从 `.runtime/production_exe_smoke_20260914` 工作目录完成：Worker `--help` 返回 0；WebUI 本机 `/` 和 `/api/overview` 返回 200。one-file WebUI 启动链曾留下实际监听进程，已按端口核对其精确可执行路径后终止，端口复核已释放。
- 全量回归为 **1997 passed, 3 skipped / 183.89s**，项目地图检查通过。构建日志中的 `xlwings.pro` LicenseError 仅影响可选 pro 子模块收集，不影响标准 Worker 打包；后续目标机仍需真实 Excel/Office 验收。

## 2026-09-14 — 第四轮分页缺陷已修复并全量验证
## 2026-09-14 — 第四轮分页缺陷已修复并全量验证

- `services/tdc_crawler.py` 增加严格分页整数解析，size 与请求不一致时不合并且不授权；显式无效页号不会再被默认值掩盖。缺失字段与 nullable total/pages 按旧兼容处理；零总数/零页数的空结果合法。
- `services/aras_crawler.py` 校验 Result 和全部 EWO Item 页号；错页、重复 Item ID 在合并前拒绝。只比较整页内容无法拦截缺 ID 的局部重叠，因此采用行内容哈希并跟踪有/无 ID 切换；有明确不同 Item ID 的相同业务内容仍允许。
- 两处旧测试需按新合同处理：数模 max_records 夹具应明确 size=3，不能靠默认 size=2；EWO page=unknown 的旧容忍测试应改为拒绝。最终持久分页用例 62 项，爬虫相关 154 passed，全量 1997 passed / 3 skipped。
- 原审计复现脚本断言漏洞存在，修复后不应继续以其 exit 0 为验收目标；使用 `tests/test_crawler_pagination_integrity.py` 与文档中的最终验证记录。

## 2026-09-14 — 第四轮审计新增未修复分页边界

- 已用真实 JSON/SOAP 解析加合成 HTTP session 证明：TDC 请求 size=100 而响应 size=2、无 total/pages 时，两条满页被当 short_page；current=0/invalid 在解析器中变成请求页号；Aras EWO 请求第二页返回 page=1 的短页，或连续重复 Item ID 后空页，仍返回 complete=true。两侧完整性门禁均接受。
- 防止误判：仅检查 `_crawl_all` 的 result.page 不足以证明协议校验可靠，必须检查解析器是否已把显式错误默认成请求值；尾页判断必须考虑有效分页大小；Aras 不能假定 TDC 的修复自动覆盖自身路径。
- 本轮未修产品代码。完整复现输入、影响、方案与验收合同在 `docs/AGGREGATE_SYNC_AUDIT_20260914_ROUND4.md`；403 项既有相关测试通过不代表上述新增边界通过。

## 2026-09-14 — TDC 分页完整性再次审计与修复

- 根因：`_crawl_all` 使用未去重的 `accumulated_count` 作为 `total_end` 证明，且没有验证 `TDCPagedResult.page` 是否等于请求页；因此重复页或矛盾的 `total/pages` 元数据可以被完整性门禁接受。
- 修复：请求页号错配时不合并该响应并返回 `inconsistent_page`；达到 total 但声明仍有后续页时返回 `inconsistent_metadata`；去重后的结果不足声明 total 或出现重复身份时不返回完整态，并以 `duplicate_records` 拒绝。
- 回归：`tests/test_tdc_crawler.py` 新增三项红绿测试；原审计合成脚本验证连接器与映射发现两侧均拒绝修复后的结果。相关套件 **270 passed**，全量 **1935 passed, 3 skipped**；地图、编译、Node 契约与差异检查均通过。

## 2026-09-14 — 聚合同步第二轮审计修复闭环

- 请求级 discovery 证据必须由请求开始时冻结的规范化规则签名；不能在外部请求返回后从当前 binding 回读规则。合法的未保存筛选仍可先形成证据，之后再保存/启用；请求身份不含凭据。
- 完整性不是 `rows` 非空或 `len(rows) == limit` 的推测。TDC 只有 `reported_pages`、`reported_total`、无矛盾的 `empty_page`/`short_page` 等明确停止证据才能 complete；页间 total/pages 矛盾要以 `inconsistent_metadata` fail-closed。Aras/TDC discovery 与同步执行共享完成态白名单。
- 历史计数需要从当前 binding 推导签名，并在有有效规则时归一化比较当前稳定键；聚合绑定的稳定键是 NULL。请求局部签名不能强行受旧 binding 稳定键限制，否则会破坏“先发现、后保存”的流程。
- 完整候选缓存是有界脱敏行集合，不是展示样本；展示可以截断到 200，候选写入口径仍可到 1000。mapping signature 用于记录缓存身份，mapping 改变时必须从完整缓存重算，不能继续读取旧聚合字符串。
- 旧测试夹具缺失 `config_signature` 时应迁移夹具生成合法当前签名，不能放宽生产校验。最终全量回归固定为 1932 passed / 3 skipped；证据日志位于 `.runtime/review2_repro_final.log` 和 `.runtime/review2_full_final3.log`。事务回归的并发侧应直接尝试换绑，才能验证产品写事务保护而不只是验证任意 SQLite 锁。

Environment pitfalls, failed attempts (do-not-retry), and verified root
causes. Rewritable wholesale at checkpoints — but never delete *why* a failed
attempt failed; prune only entries that no longer apply. Root causes that are
locked by regression tests are noted here for orientation; the tests in the
repo are the authoritative record.

## 2026-09-02 — 数模 tdc_data_model track (ZCode session 2)

- **No openpyxl/pandas on this host's Pythons** (venv 3.11 and system Python
  both lack them; the product ships xlsx via Win32 COM instead). Do-not-retry:
  `pip install` into the user env. Read-only xlsx structure inspection works
  with stdlib only (`zipfile` + `xml.etree`, sharedStrings + sheet XML) —
  kept at `.runtime/sm-review-inspect-xlsx-stdlib.py`.
- **`python -c` with multi-line/multi-arg quoting swallows output** in this
  cmd-compatible shell (exit 0, no stdout). Write a script file under
  `.runtime/` and run it instead.
- **summarize dead-code trap**: when adding a per-report `incomplete`
  computation above the result dict, the dict still returned the old
  `total - completed` expression — caught because the test-first contract
  asserted the contracted value (general-purpose agent reported it as a
  production-bug stop instead of patching). Lesson: per-report summary
  branches must be paired with a same-commit assertion on the summary key.
- **classify_overdue guard ordering**: the generic
  `if not stage or stage == CLOSE: not_applicable` runs before per-report
  branches; any report whose `stage` dimension is NOT an approval stage
  (数模 stage = 项目/车型) must be classified BEFORE that guard or empty/
  conflicting values silently bypass its overdue rule. Locked by
  `test_tdc_overdue_does_not_depend_on_project_value`.
- **SQLite CHECK whitelist extension** requires table rebuild; recipe and
  recovery (leftover `*_rebuild` table is dropped on next init) locked by
  `test_form_snapshot_check_constraint_rebuild_allows_tdc_data_model`.
  `PRAGMA foreign_keys=OFF` is a silent no-op inside a transaction — the
  rebuild must run before any DML opens the implicit transaction in
  `init_database`, then commit and re-enable FK inside `_migrate_schema`.

## Environment & tooling pitfalls

- Host is Windows with **no bash and no WSL**. SDD/workspace scripts that
  require bash fail; create the equivalent files manually (observed
  2026-09-01). Shell is cmd-compatible; `head`/`tail` etc. do not exist.
- **AGY CLI headless permission denials.** The local AGY worker
  (gemini-3.7-flash, sandboxed) cannot prompt for tool permissions in
  headless mode. Symptom: exit code 0 with stderr
  `jetski: no output produced — a tool required the "command" permission that
  headless mode cannot prompt for, so it was auto-denied.`
  FAILED ATTEMPT (do not repeat): delegating UI implementation to AGY on this
  host lost 6 runs on 2026-09-01 (TASK-20260901-DELIVERABLE-UI R1–R5, each
  ending `codex-takeover-required`, zero diffs produced). Until the
  permission flow is resolved, the lead/Main session implements UI and
  command-heavy work directly and reserves AGY for tasks whose required
  commands are pre-authorized in the sandbox. Fix in progress: `agy_cli.py`
  now classifies zero-exit denials as `blocked` (committed in `785c650`).
- `.agents/runs/`, `.runtime/`, `.superpowers/sdd/` are gitignored and
  local-only. Never treat their contents as recoverable state.
- Git CRLF warnings on this working tree are benign (autocrlf conversion
  notices), not corruption.
- The repository-wide `python -m flake8` command recursively scans
  `.agents/worktrees` and `.venv` because they are not in `setup.cfg`'s
  exclusions; it therefore returns baseline diagnostics unrelated to the
  migration. Scoped flake8 over the eight hardening Python files passes.
- UTF-8 mypy under both the system Python 3.14 and repository `.venv` Python
  3.11 reports the same 69 existing errors in 13 files. Do not attribute
  those errors to the hardening batch without a new, line-specific diff.
- Full validation of Aras/TDC endpoints requires domain authentication or
  local mock fixtures; production-network acceptance is only claimed when
  production credentials are actually used (so far: never — offline synthetic
  verification is the norm).

## Verified root causes (locked by tests — repo is truth)

- XLSX WebUI preview rejected official workbooks whose single sheet XML
  exceeded the old 32 MB member cap → caps rebalanced to 64 MB per member /
  96 MB total (committed in `785c650`; `tests/test_xlsx_preview.py`).
- NCR progress/vault-download timed out under the default receive timeout →
  240 s receive timeout on those paths (committed in `785c650`;
  `tests/test_aras_crawler.py`).
- DPAPI vault `resolve()` context swallowed consumer exceptions (e.g.
  connector failures raised inside the context) as `CredentialVaultError` →
  consumer exceptions now propagate untouched (committed in `785c650`;
  `tests/test_settings_security.py`).
- AGY `blocked` classification missed headless denials that exit 0 →
  stderr/stdout denial markers now checked before exit-code logic
  (committed in `785c650`; `tests/test_agy_cli.py`).

## Stale-doc warnings

- `README.md`: claims CLI-only/"zero web framework", contains a stray
  `ACCEPTANCE_TEST` line, and its directory table predates `web/`, `tools/`,
  and the scheduler services. The real interfaces are the Flask WebUI
  (`webui.py`) plus the CLI (`main.py`).
- The 2026-06 four-role agent subsystem was retired and deleted on
  2026-09-02: `.codex.yaml` plus `docs/agents/project_state.md`, `task.md`,
  `review_feedback.md`, `role_*.md`, `SOP_worker_coding.md`,
  `implementation_plan.md`, and the consumed sprint plans
  (`PROJECT_OVERVIEW_*`, `FRONTEND_REDESIGN_EXECUTION_PLAN`). Recover from
  Git history if ever needed. Current rules: `AGENTS.md`,
  `tools/agents/README.md`, `.agents/config.json`.

## Hypotheses (clearly labeled; promote only after verification)

- (2026-09-02, unconfirmed) The uncommitted hardening batch is post-release
  fallout from SDD Task 6 verification. Confirm with commit history or the
  user before treating as fact.

## 2026-09-02 — deliverable UI redesign checkpoint

- The UI redesign is paused at the preview gate. Architecture and the NCR
  aggregation grain are confirmed by the user; no production code was changed
  for this redesign.
- Read-only analysis of the supplied workbooks verified the relationship
  `EWO 1:N NCR 1:N NCR detail rows`: 387 unique NCRs, each with one EWO; the
  NCR detail workbook has 3768 rows and 366 NCRs with multiple detail rows.
  Use `.runtime/ncr-ewo-cardinality-20260902.json` only as local evidence;
  it contains field-level counts and no business identifiers.
- Confirmed aggregation: NCR progress status/trend counts distinct
  `NCR编号`; NCR detail status/trend also counts distinct `NCR编号`; NCR
  detail cost charts sum detail rows; department is the all-region total and
  section is `区域`.
- The prior preview regeneration was interrupted after the old ignored
  `.runtime/deliverable-forms-preview.html` was removed. Recreate it before
  any production-code edit; this is not source-code loss.
- Do not include workbook rows, credentials, cookies, tokens, or passwords in
  the preview, memory, ZCode handoff, logs, or tests. Use real headers and
  synthetic/redacted rows only.

## 2026-09-02 — Codex takeover repairs after ZCode quota exhaustion

- **EWO default filter key mismatch.** Stage B initially persisted and injected
  `department` for both EWO and PAA. `ArasArchiveConnector._ewo_filters()`
  accepts only `responsibleDepartment`; fake runner connectors did not expose
  the error. Fixed the seed migration and runtime fallback, including cleanup
  for the exact early incorrect built-in value. Locked by archive seed/admin
  and runner contract tests.
- **NCR entity/row grain mix-up.** Form summaries counted every physical row,
  inflating NCR progress duplicates and NCR detail status metrics. Added the
  sanitized `ncrNumber` dimension and a stable representative-row projection
  for status metrics only. Costs and table rows remain physical-row grain.
  Locked by duplicate progress/detail tests.
- **TDC official export mapping gap.** Official TDC XLSX rows use Chinese
  contract headers while the list API uses English keys. The old dictionary
  path therefore produced empty dimensions and values in snapshots. Added a
  header-detection path that restores positional values before normalizing.
  Locked by synthetic official-header regression coverage.
- **Frontend filter transport gap.** Stage B rendered overdue/relation-EWO
  controls but omitted both keys from the query builder, and multi-select
  reloads discarded newly selected values. Both are fixed and covered by UI
  static contract tests.
- Final offline validation after these repairs: `1658 passed, 2 skipped`,
  compileall/Node check/build passed; mypy remains the known 69-error baseline
  and scoped flake8 retains only the known `core/db_manager.py:37 E305`.

## 2026-09-02 — Codex read-only audit findings

- **NCR missing-identity collapse:** `_safe_text(None)` returns the literal
  `"None"`; the new NCR representative projection consequently treats blank
  `ncrNumber` values as one shared NCR. A synthetic two-row case returns
  `summary.total == 1`. The untouched local database reproduces the same
  symptom: NCR progress has 17,055 stored rows but the current view matches 1,
  and NCR detail has 74 stored rows but the current view matches 1.
- **Legacy snapshot incompatibility:** the local database is still schema v11
  and its existing form snapshots have no `keyColumns` or `overdueRules`.
  Startup migration upgrades the table constraint but does not rewrite the
  stored schema, dimensions, or historical summaries. `view()` serves the
  stored schema and unfiltered trend summaries, so an existing installation
  can show a current summary and historical trend at different grains.
- **NCR source aliases:** the existing snapshot contains a `完成` status which
  the current aliases do not classify as `CLOSE`; `LEADER审核` and
  `财务高级总监批准` are also not in the current node aliases. Their exact
  mapping to approved nodes needs business confirmation before production
  acceptance.
- **Sync observability/completeness:** an unreadable NCR workbook returns
  `form_rows=None` and record count zero, while the archive runner finalizes
  the source run as success. Form projection exceptions are likewise logged
  and hidden behind a successful run. TDC/NCR workbook parser truncation flags
  are not propagated, so bounded partial form snapshots can also look like
  complete successful syncs.
- Focused form/runner/connector tests: `162 passed`; full suite:
  `1658 passed, 2 skipped`. These tests do not cover the above legacy, blank
  identity, source-code status, parser-truncation, or projection-failure cases.

## 2026-09-02 — Codex repair and bounded ZCode cross-audit

- Added regression coverage and fixes for blank NCR identity handling, legacy
  schema/trend/status compatibility, NCR `完成`, TDC status code `4`, numeric
  and short contact masking, independent filter-option discovery, and archive
  form-projection/truncation observability.
- Archive projection is now checked before source-run success is finalized. A
  projection or verified-completeness failure finalizes the same run as
  `needs_attention` with the collected artifacts, preserving the last good
  form snapshot.
- Verification completed with `1671 passed, 2 skipped`, clean repair-scope
  flake8, clean target-service mypy under UTF-8/import-skip mode, and a passing
  isolated dual PyInstaller build. Full mypy remains the documented 69-error
  repository baseline.
- The configured local AGY worker was invoked in an isolated worktree for the
  requested cross-audit. A corrected bounded retry still hit the same
  headless `escalate_admin` denial and produced no findings or edits. Never
  weaken sandbox permissions or use `--dangerously-skip-permissions` to retry;
  treat this as an environment-blocked cross-audit and rely on Codex evidence
  until the exact project-level permission is approved.

## 2026-09-02 — NCR progress live response compatibility

- The built WebUI reached ARAS successfully, but the initial parser rejected an
  HTTP 200 response because the `<Result>/<Item>` type value was not the fixed
  `sgmw_outputFileRecord` spelling. A sanitized live-shape probe confirmed a
  valid `<Result>` item with a non-empty `_file` relation.
- `ArasCrawlerClient.parse_ncr_progress_response()` now scopes discovery to the
  `Result` subtree and accepts an `Item` only when it has a non-empty direct
  `_file` child. It still rejects empty/malformed results and never falls back
  to `Message` content.
- Regression and real validation passed: parser/Web routes `126 passed`, full
  suite `1673 passed, 2 skipped`, fresh dual build passed, and the fresh EXE
  returned 500 NCR progress rows with no browser console errors. No raw XML or
  credential value was persisted.

## 2026-09-02 — ZCode audit and Antigravity repair boundary

- ZCode was verified independently before the AGY repair attempt. Session
  `sess_8471cad2-b3f8-49d9-a956-7f9f22546a1c` used the configured
  `gemini-3.7-flash-high` provider, completed the requested read-only audit,
  ran the exact focused pytest command (`151 passed in 6.43s`), and ran
  `python -m compileall -q services core web` successfully. The model report
  found the requested deliverable-form and scheduled-archive behavior
  compliant, with custom NCR node aliases still awaiting domain confirmation.
- AGY 1.1.23 and the auto-updated 1.1.24 both execute model-only headless
  prompts, but a read-only `git status --short --branch` prompt is soft-denied
  in headless mode: the `Bash`/`RunCommand` tool requests `escalate_admin`,
  which headless mode cannot prompt for. A precise `command(git status
  --short --branch)` allow rule did not change the result. The TUI launches but
  stops at first-run terms/sign-in onboarding, which was not accepted
  automatically. A custom-agent experiment was removed because it did not
  demonstrate Bash execution and its real agent path returned a location
  precondition error.
- This is an external Windows permission/onboarding boundary, not a proven
  repository adapter defect. Keep the existing blocked-result classification
  and tests. Do not broaden global command permissions, enable
  `always-proceed`, or use `--dangerously-skip-permissions` without an explicit
  security decision.

## 2026-09-02 — Production WebUI package size and mail delivery boundary

- The original WebUI one-file build exceeded the mail limit because
  `VSE-WebUI.spec` collected CLI-only Selenium/IMAP/Rich trees and optional
  PythonWin helpers. The production spec now excludes those unused WebUI
  paths and development-only Flask/debug modules while retaining the explicit
  WinHTTP/pywin32 imports required by the packaging test.
- A size-compliant package was built in an isolated Python 3.11 environment
  with PyInstaller 6.22.2 and UPX 5.2.1. The final Deflate9 ZIP is
  14,942,697 bytes and contains only `VSE-WebUI.exe`; `ZipFile.testzip()`
  passed. Rebuilding with the default Python 3.14 environment is known to
  exceed the strict 15,000,000-byte target and must be rechecked.
- The local AGY packaging audit returned `Agent execution terminated due to
  error` after one read-only turn and made no changes. The result is not
  evidence against the packaging decision; the decision was independently
  verified by the build, smoke test, and full pytest.
- Classic Outlook COM activation is unavailable on this host. The user later
  reported Gmail connected and the workspace app list discovered Gmail, but
  the current task still exposes no Gmail send/attachment action. Do not claim
  delivery without a callable mail tool or a verified local mail-client send
  result. No credentials or mail secrets were stored.


## 2026-09-08 — ZCode worker runtime verified boundaries

- CLI 0.16.5 help lists --settings/--max-turns but the parser rejects them. Use the validated app-server adapter; do not retry those headless flags.
- `state.updated` reason `prompt_completed` is a dispatch milestone, emitted before actual model work. Wait for matching `session/event` turn.completed/turn.failed. Initial projection can be stale; verify settings.model.current and settings.permission.mode before sending.
- `mcpServers: []` does not disable global MCP loading; ZCODE_STORAGE_DIR changes storage, not the user config discovery path. Native tool allowlist removes MCP tools; the old AGY MCP was separately disabled in user config.
- Build mode allows native Edit without permission broker callbacks. Do not rely on permission_decision alone: the installed conditional PreToolUse scope guard was tested with an actual ZCode + local fake model that attempted an out-of-scope Write; result blocked and target absent.
- Worker deliberately has no Bash; supervisor runs user/lead-supplied verification commands. A worker statement that tests passed is not evidence. Single-round task IDs/run directories are not reusable; repair is a new bounded contract/task after lead review.
- Credentials are passed only in runtimeModel over stdio. Raw request/stderr logs are prohibited; summaries mask the configured key and endpoint URLs. Backups of existing user config remain under the user directory because those config files can contain secrets.


## 2026-09-09 — SOR export production evidence and Gemini review

- Loopback HAR cannot reveal upstream TDC request/response. Local 502 wraps crawler API validation; generic JSON-instead-of-XLSX text is local fallback, not a specific upstream cause. Do not equate archive query_failed with a proven failing upstream operation.
- Current manual-only SOR UI is intentional in tests since 623d4f2; historical project-selector completion claims do not describe current behavior. Archive ID omission reproduced synthetically.
- Gemini review needs primary verification: this run incorrectly claimed carTypeProjectId was accepted and absent test_tdc_web.py meant no Web tests; existing test_deliverables_web.py is the correct test home. Generic 12-column fallback does not apply to observed 15-column headerRows response.
- Installed launcher worked with current gemini-3.8-flash-high. Single verification command must remain an array of argument arrays; PowerShell can flatten nested arrays, so validate JSON shape before dispatch. This audit used a read-only task instruction, but runtime tool allowlist included writes; actual guard audit/diff confirmed no writes. Do not claim enforced readonly mode from context.read_only alone.
- Full evidence and next tasks: docs/SOR_EXPORT_ANALYSIS_20260909.md. Original production files and DPAPI remain untouched.


## 2026-09-09 — SOR repair implementation and verification

- Both ZCode implementation runs ended as permission-classified blocked after leaving partial edits. Their result changed_files=[] did NOT mean worktree was clean. Inspect actual git diff before takeover. No broadened permission or model retry was used.
- Gemini UI tests initially used CommonJS globals to override lexical functions and incomplete DOM stubs. Parent changed tests to VM context with bounded DOM control parsing; no production module.exports/test bootstrap was kept.
- Browser verification caught selector overflow invisible to contract assertions; flex wrapping and bounded select width fixed it. Manual edits clear hidden ID; reload clears selection; stale lookup cannot unlock a newer request. ID-only choices submit ID without copying it into display-name filter.
- New safe diagnostic stores allowlisted metadata only; raw upstream prose is intentionally not persisted in archive history. Numeric business code and upstream HTTP status are separate from local Web status. Nested messages are bounded to known keys and redacted for interactive display.
- Current WebUI entrypoint supports VSE_TOOLBOX_PORT (historical fixed-port note is superseded). Final packaged smoke used 5066; temporary DB kept separate from production. Output ZIP contains EXE only.
- Validation: full 1751 passed / 3 skipped; final targeted 15 passed after one ID-only test added; production TDC export not exercised. Durable release/retest guide: docs/SOR_EXPORT_REPAIR_20260909.md.

## 2026-09-10 — ZCode worker permission audit root cause

- `tools/agents/zcode_worker.py:27` currently allows permission requests only when the tool is in `WRITE_TOOLS`; an in-scope `Read` permission request is therefore denied. The two SOR implementation run audits each contain one `Read` record with `allowed: false`, and the worker result maps that denial to `failure_code=permission`.
- Preserve the write/scope safety boundary when repairing this predicate. Add a focused preflight and regression test for in-scope `Read`, `Grep`, and `Glob` before retrying implementation workers. Do not broaden global permissions or silently switch providers.

## 2026-09-10 — Gemini dual-tier runtime implementation

- The app-server rejects unknown fields inside `runtimeModel.provider.models[*]`. Internal `contextBudget` and `thinkingLevel` metadata must be removed before protocol submission; retain them only in local summaries and handoffs. Real Flash and Pro no-tool probes passed after this filter was added.
- The old installation manifest intentionally refused to overwrite a changed user runtime. Use the explicit installer mode with a new installation ID to back up the current target before synchronization; the verified Pro-agent installation is `vse-worker-20260910-pro-agent-verified`. Do not weaken the default hash guard.
- CliproxyAPI exposes `gemini-pro-agent` as `Gemini 3.1 Pro (High)` and also exposes `gemini-3.1-pro-low`; the project Pro slot must use `gemini-pro-agent`. Do not treat either local alias as an official model ID; capability and network preflight remain the source of truth.
- `Read` permission failures were caused by a Worker RPC predicate that only admitted `WRITE_TOOLS`; the shared `tool_decision` implementation now covers Read/Grep/Glob separately and preserves write scope/readonly checks.

## 2026-09-10 — dual-tier short/medium/long smoke

- The first long Pro-agent smoke was blocked after three tool requests because app-server native tool input used `filePath`, while the guard only read `file_path`/`path`. Additions to shared `tool_path` fixed this without broadening scope; rerun completed short Flash read, medium Flash write and long Pro-agent high read-only review.
- Smoke evidence: short `gemini-3.8-flash-high` completed with one Read; medium Flash completed with two calls and only `medium.txt` changed; long `gemini-pro-agent` completed with two Reads and no changes. All three used the 272,000-token effective context cap.

## 2026-09-11 — diagnostic recording recovery facts

- Short-lived SQLite connections caused repeated last-connection WAL checkpoints and intermittent event loss in a four-thread recorder test. Retain one connection during recording and serialize same-process writers; retain the short cross-process lock timeout so diagnostic contention never replaces the business error. Drop evidence is best-effort and explicitly described in the manifest.
- UI history initially preserved the old selected recording after starting a new one. Node regression now requires start to select the returned latest ID; manual history selection remains stable thereafter. Browser EXE smoke verified the fix.
- Expired recordings with no subsequent writes must have their effective expired state projected during export, not only during status reads. Every event includes process build identity so a recording spanning process restarts cannot silently imply one build version.
- Exception messages/locals/source lines remain excluded; preserve errno/winerror/HRESULT and each exception type in a bounded cause chain for native/network root-cause triage.
- Scheduled EXE requires core/report_headers.json in its PyInstaller datas. Added focused packaging test and supplied matching CLI/WebUI; two-process dry-run export verified offline. Do not claim full production execution from a no-enabled-jobs dry-run.

## 2026-09-12 — context policy and GLM-5.3-Flash profile verification

- Main-controller policy is orchestration-only: `150000` means bounded-read monitoring, `180000` requests Handoff and `200000` starts a new micro-session. It does not alter the native Codex context window. `tools/audit_token_trajectory.py` consumes the policy without reading raw prompts into the report.
- The first `weekend-5.3flash` no-inference probe failed because `zcode_worker.load_runtime` accepted only `openai-compatible`, while the configured `GLM-5.3-Flash` Provider is `anthropic`. The verified fix maps `anthropic` to `anthropic-messages` and preserves rejection of unsupported kinds/formats.
- The project profile is opt-in and maps both Flash/Pro slots to `GLM-5.3-Flash`; the default model remains Gemini. Launcher dry-run, provider load, local permission preflight and the installation manifest all pass. No external model inference was performed during this change.
- Global runtime changes use installation ID `vse-worker-20260912-interactive-card`; use its manifest-aware check/rollback rather than overwriting changed targets.

## 2026-09-12 — GLM-5.3-Flash real smoke blocker

- A temporary isolated short task with `-WorkerProfile weekend-5.3flash` reached the supervisor and passed static preflight: model `GLM-5.3-Flash`, Provider `builtin:zai-start-plan`, format `anthropic-messages`, effective context `272000`, Read/Grep/Glob allowed. Network preflight then returned a non-retryable runtime `unknown_error` during `prepare`; the task stayed `preflight-blocked`, with no worktree or Worker round.
- A separate explicit comparison using configured `builtin:zai` reached the provider but returned non-retryable HTTP 429/provider code `1309`. This is evidence of an entitlement/provider-side blocker, not permission scope failure. Medium and long real smokes were intentionally skipped; do not add a silent fallback or claim the weekend route operational until a short smoke reaches Worker execution.
- The initial failed short attempt was caused by PowerShell flattening nested `verification_commands`; rebuilding the contract with explicit nested lists produced the valid contract and exposed the actual provider preflight failure.
- The first preflight failure (`runtime prepare` / `Preflight tools are disabled`) was caused by the worker rejecting normal ZCode host callbacks `session/requestRuntimePreferences` and `interaction/requestProviderRuntimeHeaders`. The worker now answers safe runtime preferences and refuses to claim provider headers were applied when no interactive host is present. The next real probe reached the provider and exposed the true non-retryable 400/3007 CAPTCHA failure. Do not turn this into a header/CAPTCHA bypass.
- CliproxyAPI at the configured local `/v1/models` endpoint returned Gemini models but no `GLM-5.3-Flash`; there is no configured local OpenAI-compatible 5.3 Flash route to use as a transparent fallback.
- User clarified that `GLM-5.3-Flash` is a ZCode gifted trial card. Interpret provider code 3007 as the expected interactive-entitlement boundary; use interactive ZCode for the card and keep the headless supervisor profile fail-closed with `interactive-required`.

## 2026-09-13 — Gemini Worker 1M context verification

- The provider config advertises 1,000,000 context for `gemini-3.8-flash-high`, `gemini-pro-agent` and the GLM trial entry. The Worker itself, not CliproxyAPI, had been clamping all providers to 272,000; the clamp, handoff schema constant, installer default and runtime config were updated to 1,000,000.
- Flash static preflight and network preflight passed with a 1,000,000 context budget. A real read-only smoke reached Gemini and returned a completed result, but the supervisor recorded `permission` blocked because the model tried Glob/Grep with an omitted path and one repository-root Read outside the isolated worktree; the scope audit is intentionally fail-closed. Treat this as a test-contract/scope issue, not a context or provider failure.
- Pro `gemini-pro-agent` no-tool network preflight passed with the same 1,000,000/950,848 budget. Do not use the GLM interactive-only profile for this normal Gemini route.

## 2026-09-13 — direct `zcode` TUI entrypoint boundary

- `C:/Users/Lynch/.local/bin/zcode.cmd` and `C:/Users/Lynch/bin/zcode.cmd` both invoke `D:/zcode/resources/glm/zcode.cjs` without arguments. That bundle contains the `app-server` path used by the Worker, but the installed `glm` resource has no `@zcode/tui` package or `node_modules`, so bare `zcode` fails while importing the interactive TUI.
- Keep the normal project route on `C:/Users/Lynch/.zcode/tools/run-worker.ps1`; it passes the `app-server` argument and has been verified with both Gemini slots. Launch `D:/zcode/ZCode.exe` for the Desktop UI. Do not repair the bundle by manually copying or installing an unverified package; update/reinstall the official ZCode distribution if an interactive CLI is required.

## 2026-09-14 — SOR 查询诊断边界
- 诊断包 f52efc893c2b424bad728f56be76f138：两个车型文本解析零匹配、本地 400；列表 200/16 条；同录制仅部门 SOR 第一页成功。四个异常是两次请求的分层记录。不要误报为登录失败、SOR 全面不可用或四次失败。
- json-ok 的项目列表不证明 id/projectNo/projectName 存在；当前解析器和选择器均依赖这些字段。优化前先区分字段合同与真实零匹配；见 docs/SOR_QUERY_DIAGNOSTIC_20260914.md。

- 官方 SOR HAR 已补齐（2026-09-14）：list 必带观察到的 sorEnabled=true（201项）；查询 carTypeProject 与 carTypeProjectAll[0] 都传内部ID；导出附bizName=SOR。旧16项列表及名称参数合同需修正。独立XLSX 4833明细/408流程与查询total408对齐，勿混淆粒度。见SOR诊断报告补充章节。

- SOR上述三项合同已于2026-09-14修复；新增合成上下文切换测试能重现错误项目字典导致拒绝，四入口共用修正。全量2006 passed/3 skipped，新双EXE复测包VSE-SOR-Fix-20260914已验哈希与本地启动，内网成功仍待现场验证。

## 2026-09-15 EWO worker实际通道阻塞
- TASK-ewo-pure-association-20260915静态预检passed，网络预检Worker deadline exceeded，transport/preflight-blocked；未生成worktree或worker轮次。不把路由配置可用当成模型实际可用；禁止自动provider fallback或大规模GPT接管。
- supervisor的风险关键词会匹配objective中的否定描述（如No database）；准确描述纯函数职责、把排除职责放constraints能保留真实边界；不是给高风险实现重贴低风险标签。

- 2026-09-15 Gemini路由：取消Pro，仅3.8 Flash；旧pro槽位兼容映射Flash。此前EWO失败是Flash网络预检deadline，非Pro失败。新同30秒预算无工具探针25.77秒成功；尚不能区分上游/中继/启动延迟。doctor有独立Luna硬编码限制，勿混作网络故障。见docs/ZCODE_WORKER_RUNTIME.md。

## 2026-09-16 非 UI 严格审计发现

- `tests/test_version_and_usability.py:78` 仅设置 `VSE_TOOLBOX_DATABASE_PATH`，但 `core/db_manager.py:1059` 不读取该变量；`create_app()` 因而初始化真实 `data/vse_toolbox.db`。本轮执行该测试文件的非 UI 子集时，`test_settings_patch_and_read_preserves_advanced_values` 将 pytest 临时目录写入真实库的 `archiveDirectory`。原值未知，未擅自恢复或删除；修复测试隔离并由用户确认原值前，不要再次运行该 fixture。
- `project_status_manual_editability` 只复用了部分绑定规则，未复用策略层的长度/控制字符等边界校验。临时库实验证明 `match_rule_json={"incident":"FM-1\\u0000"}` 仍被判为可手工编辑，且 `apply_manual_update` 成功写入；这违反“异常持久化配置 fail-closed”的审计合同。应集中共享校验或在只读判定中调用同一严格规范化器。
- `core/project_status_contracts.py` 新增判定的 3 个 mypy 错误位于 `capabilities.get(... )` 的动态 `object` 迭代（约 91、106、129 行）；`core/version.py` 自身的聚焦 mypy 检查通过。版本功能还未接入打包元数据：当前 `VSE-WebUI.spec` 与 Windows workflow 未携带 `VERSION/version.json`，仅运行时环境变量不会自动写入 EXE。

## 2026-09-16 非 UI 严格复审（二轮修改）

- 第二轮已修复上一轮审计的测试库隔离、异常规则控制字符边界和 contracts 模块 mypy 问题。安全的版本/隔离选择集为 `10 passed, 1 deselected`，并核对默认数据库 mtime 未变化；项目状态/数据库选择集为 `329 passed`，额外后端/API/安全选择集为 `123 passed, 11 deselected`。
- `VSE-WebUI.spec:47` 仍无条件收集 `version.json`；在没有 `VSE_TOOLBOX_VERSION`、且仓库没有该文件的当前环境，直接 PyInstaller 构建退出码 1，错误为 `Unable to find ... version.json`。需要避免缺失文件失败，也要避免残留旧文件被静默打包。
- `.github/workflows/build-windows-exe.yml:101` 的 PowerShell `[System.Text.Encoding]::UTF8` 生成文件包含 `EF-BB-BF` BOM；`core/version.py:70` 以 UTF-8（非 `utf-8-sig`）读取，实际 `json.loads` 抛 `JSONDecodeError`，因此 CI 生成的版本元数据会被忽略。应统一写入/读取编码并增加冻结包验证。
- 上一轮真实库副作用仍待用户确认：`data/vse_toolbox.db` 的 `archiveDirectory` 原值未知，未自动恢复或清理。本轮新 fixture 未再次修改默认库。

## 2026-09-16 Codex 独立复审第三轮

- 第三轮版本发布链修复经独立验证通过：`VSE-WebUI.spec` 在无版本和带版本环境均能在隔离输出目录构建成功，且不在工作区生成残留 `version.json`；带版本冻结 EXE 的 `/api/version` 在清除运行时版本环境变量后仍返回嵌入的版本、channel、buildId；无版本冻结 EXE 返回安全回退。
- CI 的 `New-Object System.Text.UTF8Encoding $false` 实测 UTF-8 preamble 长度为 0；`core/version.py` 使用 `utf-8-sig` 兼容有 BOM/无 BOM 文件。版本/隔离测试、项目状态/数据库回归及静态检查均通过。
- 无新的非 UI 阻断项。不要忘记上一轮真实 `data/vse_toolbox.db` 的 `archiveDirectory` 副作用：原值未知，未自动恢复；处理前需用户确认。


### 2026-09-15 预检总预算修复验证

原30秒截止覆盖启动、session/create/subscribe/send和模型响应。现统一为60秒（源码默认、安装器、项目/全局配置、已安装运行时），仍为单次总截止且保留进程树清理。成功结果增加timings_seconds/elapsed_seconds/timeout_seconds，超时报告安全stage标签与耗时，不记录提示词或凭据。

安装后的真实3.8 Flash无工具预检30.172秒成功：create1.516、send0.062、模型响应28.594秒。该正常响应跨越旧30秒截止，验证原预算会误杀正常请求；不宣称已经定位原请求的服务商内部延迟原因。147 passed/1 skipped，地图检查通过。未重启原EWO实施。

## 2026-09-15 EWO Flash任务验证与边界
- 官方ZCode launcher恢复后两个Flash隔离任务产出已审查集成；state passed不替代diff核验：发现纯函数把未知小写state upper，测试也写了同一错误预期，主控修正并验红绿。工作簿另有regex大小写测试失败。
- 新解析器读取实际sheetData，真实111列表410数据行/406唯一编号+4空编号，关联不会按行序补ID。105项相关测试通过，但尚未Web集成或全量发布。
- 下一关键边界是主体scope：DomainSessionRegistry目前无显式principal，不可用domain常量或session对象id作为持久任务账号身份。

## 2026-09-15 EWO v2集成排错

- 配置CAS不能只加比较：get_project_status_update_policy原SELECT未返回sync_config_revision，必须一起补齐，否则重复保存被误判冲突。使用唯一上下文应用补丁，泛化old_binding锚点曾插入错误方法，定向测试已捕获并修复。
- 新源码增加详情页内容后，旧测试按6000字符截断造成假失败；改为按下一函数边界定位，保留原断言。
- 新身份必须同时进入发现、执行与分析item_key；只改关联函数仍会让同号/空号同属性行被分析层合并。v2仅用_source_item_id生成item_key，legacy不改。
- 候选预览也必须采用v2空值不清空规则；否则显示待清空而执行实际跳过。已补预览/执行一致性测试。
- schema14为旧EXE保护门槛；此前只有HTTP版本确认不足以约束旧二进制。升级测试保留legacy规则，模拟v13 runtime会在DDL前拒绝v14数据库。

## 2026-09-16 交付物控制台边界

- manualEditable必须由真实目标/集合绑定判断，mode或enabled单独不能代表已映射；异常配置拒绝编辑。DB事务内复核才能避免策略配置和手工保存之间竞态。
- 保留筛选DOM同时必须区分草稿、请求、成功显示条件；切页签时旧DOM仍可能读动态activeTab并串写，需锁定旧结果交互并保留切换/重试入口。
- EWO关联状态不等于官方业务状态，待签人与责任工程师不同字段；下载错误不能只藏在折叠诊断里。
- 本期PAA/NCR仅快照参考卡；不能擅自增加正式交付物或改变节点分母。验证与手工清单见docs/DELIVERABLE_CONSOLE_AUDIT_20260916.md和docs/DELIVERABLE_CONSOLE_UI_TODO_20260916.md。

## 2026-09-16 — 最新 WebUI 生产测试包

- 从当前含未提交控制台改动的工作区，以 `VSE-WebUI.spec` 使用 Python 3.12.10 / PyInstaller 6.21.0 构建单文件 `VSE-WebUI.exe`；构建退出码 0。当前主机 `upx` 不在 PATH，不能把本次 17.5 MB 包体当作已压缩产物；若未来有严格体积门槛，应在带 UPX 的受控构建环境重新构建并重新冒烟。
- 产物目录 `dist/VSE-WebUI-production-20260916/` 仅有 EXE 和生成的 `SHA256SUMS.txt`；传输 ZIP 只包含 EXE。EXE SHA-256 为 `c8738a1ac8273361350bb0a19405246627f8a637847adfd1a6a9afb8069ed98e`，ZIP SHA-256 为 `9042fd0bb2ec00c14e8e44c4fd6ae3295d8acaf66bada4adb249d88676becaa7`。
- `178 passed` 相关回归与三个修改 JS 的 Node 语法检查通过。将 EXE 复制到隔离 `.runtime` 目录，在子进程 PATH 仅含 Windows 系统目录、端口 5066 下启动；首页和 `/api/overview` 均 200，按 PID 结束后无残留进程。独立哈希、ZIP 单条目和完整 CRC 读取校验通过。
- 离线冒烟不等于企业内网/干净机器/Office/人工 UI 验收；WebUI 单包不含 Excel Worker，真实 Excel 功能必须部署同版本 `VSE-ExcelWorker.exe`。证据保留在 `.runtime/webui-build-20260916.log`、`.runtime/production-package-targeted-20260916.log` 和 `.runtime/webui-production-smoke-20260916/`。

## 2026-09-20 — 权限受限执行下的 pytest 假失败与 flake8 命名管道边界

- **症状**：受限文件策略下全量 pytest 在 **16 秒内报 1391 errors**（只有 905 passed），错误为 `PermissionError: [WinError 5] ...\Temp\dsh-*\pytest-of-Lynch`；单测 `--tb=long` 只在 `_pytest/pathlib.py:354 cleanup_dead_symlinks` 抛出，外观酷似产品缺陷。
- **根因**：该 basetemp 目录由更早一次被中断/受限的运行创建，之后对当前权限上下文**不可枚举也不可读取**（`Get-ChildItem`/`Get-Acl` 同样 WinError 5）；pytest 进入 `cleanup_dead_symlinks` 即失败，导致全部用例在 setup 阶段集体报错。改用工作区 basetemp（点号名与普通名都试过）同样复现，说明与目录名/磁盘无关，而与「目录由另一权限上下文的进程创建」有关。
- **处置（do-not-retry）**：不要反复重试默认 basetemp，不要改路径名碰运气，也不要当产品缺陷去查业务代码。删除/绕开被锁目录、让当前进程新建 basetemp 即可；本轮在获得完整文件权限后，删除旧目录并重跑直接恢复（2294 passed / 3 skipped）。判据：产品级失败会给出具体断言与堆栈；本案 1391 个错误全部集中在 setup 且发生在十余秒内，属环境层特征。
- **flake8 同名边界**：受限模式下 `python -m flake8`（默认多进程 Pool 需要命名管道）直接 `PermissionError [WinError 5] _winapi.CreateFile`；改用 `python -m flake8 -j 1` 可得可信结果，不需要放权。
- **`.runtime/` 写入**：同一受限模式下 `Tee-Object`/写文件到 `.runtime/` 会被拒（Access denied），只能用 `-j 1` 之外的替代方式或先取到完整文件权限；恢复权限后按 AGENTS.md 约定把日志写回 `.runtime/`。


## 2026-09-25 Expert Advisor broker 热更新与冒烟误报

修改 advisor_core.py 或 advisor_broker.py 后，运行中的 Windows 计划任务 broker 不会自动重载 Python 模块。曾出现 CLI 新进程 check 通过、broker 旧进程 live 在额度检查返回 7 的状态；该次任务的账本 launch_count=0，未调用模型。部署修改后应核对 broker 协议版本并重启已核实命令行身份的进程，再做无模型 check。脚本 scripts/smoke_workflow.py 的失败结果曾固定 model_call=true；现改为按匹配的 launch 行判定，防止配额拒绝误报实际调用。失败即停，不用换任务 ID 或档位重试。

## 2026-09-25 Expert Advisor 本地配额重置边界

重置本地顾问额度时不要删除 ledger-*.jsonl，也不要调用 Plus 账户重置。策略 local_quota_reset_at 只过滤该时间之前的 codex-readonly 启动用于本地自然日、任务和滚动上限；--status 的 prior_launches_preserved 显示历史启动数。修改 advisor_core.py 后必须升级 broker 健康协议并重启已核实身份的本机进程；仅改策略字段则服务每次请求会重新读取。用户授权重置后，115 项离线测试及两次合成 live 已通过。
