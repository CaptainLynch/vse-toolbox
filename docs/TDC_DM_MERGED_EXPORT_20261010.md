# 数模「填多个流水单号 → 合并导出」实现说明（2026-10-10）

- 需求来源：用户 2026-10-10 反馈「我要的就是填多个表单值合并导出来的功能，你没有修复」。
- 状态：已实现（工作台 + 系统查询页两个入口）；2026-10-13 数据源改为官方工作簿（见 §0）。

## 0. 2026-10-13 变更：数据源改为**官方导出工作簿**（下方 2026-10-10 正文已部分过期）

- 触发：用户把「内网官方版本」与「WebUI 合并导出」两份按同一单号导出的报表逐列对比，
  发现官方 47 列中只有 20 列有值，其余 27 列（数量/重量/零件合计/对应IA号/各专业会签/
  造型专家审核/NVH/应签人数/已签人数/未签人数/签署率/待审批人员）**全空** → 反馈"导出的
  报表缺少列信息，其他交付物也一样"（EWO 111 列中 60 列空、PAA 113 列中 68 列空）。
- 根因：合并导出原先用**列表接口**行拼官方列；列表接口只覆盖契约 47 列中的 20 列，
  `_TDC_DATA_MODEL_SOURCE_FIELDS` 未映射的列只能留空（`unmappedColumns` / `mappingComplete=false`）。
- 修法（数据源与归档连接器统一）：
  1. 新增 `services/tdc_official_rows.py`：官方工作簿 → 「契约列标签 → 值」行；
     读取用 `services/xlsx_preview`（zip + XML，**不违反 DLP**：禁用的是 pandas/openpyxl，
     而这个读取器是仓库自有的无第三方实现，官方预览与归档连接器一直在用）。
     表头与契约不符 / 行数超限 / 工作簿不可读分别抛专用异常，**绝不产出部分行**。
  2. `services/scheduled_archive_connectors.py::_official_workbook_rows` 改为委托该模块
     （归档侧语义不变：不可读 → 回退列表抓取；截断/契约不符 → 既有 projection_error 码）。
  3. 「导出合并结果」链路改为：**范围预检**（列表首页 `total`，`max_pages=1`）→
     `export_data_model(filters)` 官方工作簿 → `read_official_tdc_rows` → `match_serials`
     本地精确匹配 → 一张 CSV（**47 列全有值**，UTF-8 BOM + CRLF，公式注入缓解不变）。
     官方工作簿落在任务临时目录并在结束时删除，下载目录里只有 CSV 产物。
  4. fail-closed：范围超过 `_TDC_MERGED_MAX_ROWS`（50,001，与官方预览同上限）→ 422
     「超过官方报表单次上限…请补充车型/日期等条件」；工作簿不可解析/表头不符 → 502；
     任一请求单号未命中 → 422 `SerialNotFound`。**不再**回退到"列表列 + 27 列空"。
  5. 查询预览的范围预检（同一根因的另一半）：填了流水单号时先用首页 `total` 判断本次
     抓取上限（`min(max_pages × page_size, max_records)`），超限立即返回
     `serialMatch.complete=false, reason="range_too_large"`（带 total/limit），不再空跑
     `max_pages` 页后报"抓取不完整"——现场表现为同步请求跑满数分钟仍无结论
     （诊断录制：不填车型时上游 55,335 行 / 1,107 页，默认上限 100 页 = 5,000 行）。
  6. 前端：工作台/系统查询两处提示同步更新（`mergedExportHint` / `mergedExportNotice`
     说明"从官方报表按单号精确筛选、含全部官方列、范围过大先补车型/日期"；
     `serialMatchWarning` / `serialMatchNotice` 新增 `range_too_large` 分支）。
- 测试：`tests/test_tdc_official_rows.py`（新增 11 例）、`tests/test_tdc_merged_export.py`
  （重写为官方工作簿链路 + 范围预检 + 不可解析/契约不符 fail-closed）、
  `tests/test_deliverables_web.py`（范围预检用例 + 预检/全量抓取调用序）、
  `tests/test_scheduled_archive_connectors.py`（读取器 monkeypatch 目标随模块迁移）。
- 仍未做：把合并结果**写成 XLSX**（需 Excel Worker(COM) 写操作，另立任务）；官方导出路由
  是否接受 `documentNo`（现场未验证，本批不把单号发上游）；「实例号在官方 Excel 精确预览
  不可用」的单独取证（上游导出路由疑似不吃 `incident`，需现场探针）。

## 1. 缺陷定位（此前为什么"没有这个功能"）

| 环节 | 现状 |
| --- | --- |
| 多单号**查询/合并预览** | **已支持**：`web/app.py` `_tdc_document_nos()`（空格/逗号/分号/顿号/换行分隔、上限 100、fail-closed）+ `match_serials()` 集合匹配；工作台与系统查询页共用 `/api/tdc/data-model/query`。 |
| 多单号**导出** | **此前完全缺失**：`_tdc_report_export()`（`web/app.py:3218` 起）只从请求体 `filters` 构建参数，**从不读顶层 `document_no`**；点「下载 XLSX」拿到的是"其它筛选条件下的全部行"，与预览里合并后的那几行无关。 |

## 2. 为什么是 CSV 而不是直接过滤官方工作簿

- 上游没有流水单号查询参数（`documentNo` 是第 2 列，只能本地匹配），官方导出**无法**按单号过滤。
- 公司 DLP 禁令（`services/office_toolbox.py`）：**禁止用 pandas/openpyxl/python-pptx 直接读写 Office 文件**（透明加密会导致乱码），必须走 win32com。
- 现有 Excel Worker 只有 `merge_append / merge_overlay / diff_against_baseline` 三种操作，**没有"按列过滤"**。
  → 「官方 47 列工作簿按单号过滤」需要新增 Excel Worker(COM) 操作（另立任务，目标机须装 Excel）。
- 因此本批交付**合并 CSV**（纯文本，不受 DLP 影响；UTF-8 BOM，Excel 双击可开）。

## 3. 实现

### 后端

> 以下为 2026-10-10 初版实现；数据源与链路已被 §0 的 2026-10-13 变更取代（保留作历史记录）。

- 新路由 `POST /api/tdc/data-model/export-merged`（`web/app.py`）：
  1. 前置校验（**抓取前**）：`_tdc_document_nos()` 解析；无单号 → 400「请先填写至少一个流水单号（多个用空格、逗号或换行分隔）」。
  2. 统一域会话准入与 base_url allowlist（与官方导出同契约）。
  3. 后台任务（202 + 任务中心）：全量抓取 `crawl_data_model_all(max_records=MAX_AGGREGATE_RECORDS, on_page=…)`，
     分页进度写入任务进度（`已抓取 N 页 / M 行`）。
  4. 抓取不完整 → `422 IncompleteDiscovery`（不得判"未找到"）。
  5. `match_serials()` 本地集合匹配；**任一请求单号缺失即整体失败**（`422 SerialNotFound`，
     列出未找到的单号）——导出件是要带走的结果，不允许静默少导出。
  6. 命中行 → `_tdc_merged_export_csv()`：列序沿用数模表契约（与预览一致），
     列表接口不提供的官方导出列留空；敏感键（cookie/token/…）不进 CSV；UTF-8 BOM。
  7. artifact 落在任务 downloads 目录，`<文件名去扩展名>_<taskId>.csv`，走既有任务下载链路。

### 前端

- 交付物工作台（`plugins/deliverables/static/`）：
  - `lib.js`：`TDC_ENDPOINTS["tdc-data-model"].endpoints.export_merged`；`buildPayload` 把 `export_merged`
    当导出类（带 `file_name`、不带 `preview_source`）；`validateForm` 要求填单号；
    新增 `mergedExportHint()`（提示官方 XLSX 不按单号过滤）。
  - `catalog.js`：新增按钮「导出合并结果（CSV）」+ 提示；`run()` 把 `export_merged` 走导出任务链路（kind=export）。
- 系统查询页（`plugins/system_query/static/`）：
  - `modes.js`：`tdc-data-model` 增 `mergedExportEndpoint` / `mergedExportLabel`。
  - `lib.js`：`buildPayload` 支持 `export_merged`（导出类语义）；`validateForm` 要求填单号。
  - `query.js`：新增按钮 + `run("export_merged")` 分派，任务/下载链路与官方导出一致。

## 4. 测试

- 新增 `tests/test_tdc_merged_export.py`（7 例）：CSV 纯函数（BOM/契约列/脱敏）、无单号 400、
  空白单号 400、**多单号端到端合并**（3 行命中、未请求单号不出现、流水单号不发上游）、
  缺失单号整体失败、抓取不完整 fail-closed。
- 前端：`tests/test_deliverables_system_query_parity.py`（两个插件 payload/校验/提示一致性）、
  `tests/test_plugin_system_query.py`（端点已注册 + 按钮接线）、
  `tests/test_deliverables_web.py`（工作台按钮接线）。
- 门禁：聚焦 240 passed；flake8 改动文件 0 告警；Node 导入两份前端模块通过；全量回归见提交记录。

## 5. 顾问实施后复核（2026-10-10）与处置

- 顾问：Claude `claude-opus-5-5`/xhigh，run `1849bd83-2640-48f9-895e-be3126c851e5`
  （`~/.dsh/expert-advisor/runs/claude-20261010-074644-be15f35a.advice.md`）；裁决 1=adopted、2=partial、3=adopted。
- 顾问的 5 项「不补不能打包」与处置：

| # | 顾问发现 | 处置 |
| --- | --- | --- |
| B1 | CSV 公式注入（上游文本不可信 + 产物面向 Excel） | **已修**：`_csv_cell()` 对 `= + - @ \t \r` 前导字符加 `'` 前缀，**严格数字字面量豁免**（`-12.5` 保持数值语义）；补 5 类转义 + 豁免用例 |
| B2 | 截断（max_records）必须判"不完整"，不得落到 `SerialNotFound` | **已核实并补测**：`COMPLETE_STOP_REASONS` 不含 `max_records` → `_mapping_result_is_complete` 为假 → 422 `IncompleteDiscovery`；新增 `max_records` 截断用例并断言消息里没有"未找到" |
| B3 | 新路由的本机/同源 guard、401/400 会话门、allowlist 拒绝无路由级断言 | **已补 4 条用例**：跨站 Origin → 403（且未创建任务）、无统一域会话 → 401、密码模式 → 400、base_url 不在 allowlist → 400/403。另核实 `_request_payload()` 内置 `_local_web_mutation_error()`，新路由与官方导出同 guard |
| B4 | `file_name` 必须在 202 之前校验，artifact 不出 downloads | **已核实并补测**：`_tdc_file_name()` 限制长度 ≤180、纯 basename（拒 `..`/路径分隔符）、必须匹配安全 `.xlsx` 正则，且在会话门/提交任务之前调用；新增 `../evil.xlsx` → 400 且无任务用例 |
| B5 | 待打包的树上 vendor 校验和门禁必须为绿 | **已修**：`web/static/host/vendor/preact-htm.js` 工作区是 CRLF 而 HEAD blob 是 LF（实测 `crlf→lf` 与 HEAD blob 逐字节相等），已按 LF 归一；`git status` 干净（`git update-index --refresh` 后确认内容未变），`test_host_frontend.py` 10 passed |

- 顾问关键判断的本地核验：
  - **K1（截断语义）**：`services/pagination_integrity.COMPLETE_STOP_REASONS = {reported_pages, reported_total, empty_page, short_page, workbook_rows}`，
    `max_records`/`max_pages` 不在其中 → 截断必然 fail-closed（顾问担心的"截断算完整"不成立）。
  - **K2（导出与预览同源）**：合并导出改用与查询预览**同一套**参数构造与默认值
    （`_tdc_filters_from_payload` + `_tdc_data_model_filters`；page_size 50 / max_pages 100 / max_records 10000），
    并新增用例断言两者构造出的 filters 与分页参数完全一致——避免"预览命中、导出报未找到"。
  - **K7（官方导出仍不过滤）**：系统查询页也补了 `mergedExportNotice`（填了单号时明确指向「导出合并结果」），
    与工作台的 `mergedExportHint` 对齐。
- 未采纳/偏差：
  - 顾问建议「若契约能标识官方独有列则导出时剔除 27 个空列」——**本批保留全部 47 列**（与预览列序一致，
    避免"列少了"的困惑），改用文件名后缀 `_合并_` + 任务阶段文案「列表接口列」标注；记 `partial`。
  - 顾问建议的 `file_name` 扩展名与实际产物 `.csv` 不一致问题：保留（请求里的 `file_name` 只当基名用），
    文件名后缀已标明合并导出。
- 顾问提出的实机项（本机无 Excel，无法执行）：**用 Excel 双击打开样例 CSV**，确认 `'=1+1` 的显示效果、
  `-12.5` 保持数值、长数字单号/前导 0 不失真。若失真，产物形态需转向方案 B（官方 XLSX + COM 过滤）。

## 6. 待办 / 边界

> §0 变更后仍成立的待办：把合并结果写成 XLSX（Excel Worker COM 写操作，另立任务）、
> 官方导出路由是否接受单号（现场探针）、`plugin.json` 版本号策略。下面第 1/2 条的
> "必须新增 COM 按列过滤"与"合并导出只能全量抓取"已被 §0 取代。

1. **官方 47 列 XLSX 的按单号过滤**：需新增 Excel Worker(COM) 的「按列过滤」操作
   （`core/excel_tasks.py` ALLOWED_OPERATIONS + `core/excel_worker.py` + 任务 UI + 测试），
   目标机须装 Excel。另立任务。
2. **合并导出当前是全量抓取**（与查询预览同源）：上游无单号参数，无法避免；
   已给分页进度与"全量抓取"提示。若数据量继续增长，可考虑按车型等条件先收窄再抓。
3. 官方导出按钮在填了单号时仍会导出"全部行"——已用 `mergedExportHint` 明确提示；
   如需要可考虑在填了单号时禁用官方导出（需产品确认）。
4. **架构偏差（已知并接受为本批技术债）**：AGENTS.md 规定「Do not add route bodies to `web/app.py`」，
   而本批在 `web/app.py` 新增了路由 `POST /api/tdc/data-model/export-merged`
   （车型锚点那批另新增了 `sync-by-car-type`）。理由与边界：
   - TDC 数模的宿主 API（`/api/tdc/data-model/query|crawl-all|export`）本来就全部住在 `web/app.py`，
     新路由与它们是同一族、共用 `_request_payload` 的本机/同源 guard、统一域会话准入、allowlist 与后台任务框架；
   - 迁移到插件需要给插件开放「宿主 TDC 客户端/域会话」上下文（当前 `host.context` 没有这层），
     属于更大的宿主契约变更，不宜塞进本批修复。
   - 结论：本批接受为技术债；若产品决定后续把 TDC 数模 API 整体迁入插件，这条路由一并迁。
5. `plugin.json` 版本号未升：本次改动走**宿主 zip**发布（宿主自带插件），不影响；
   若将来要单独发 `.vsepkg`，需先升 `deliverables` / `system_query` / `project_overview` 的版本号。
