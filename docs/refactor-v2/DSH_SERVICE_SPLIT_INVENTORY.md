# DSH-V2-42 大服务渐进拆分清单

> **状态：已批准（主控，2026-11-01）**——§7 裁决见该节末“主控裁决记录”；后续拆分任务按 §4 逐项派发，每项仍须主控批准。
> **基线提交：`1619141`**（分支 `dsh/v2-42`；基线 = `refactor/ux-v2` 当前 HEAD，已含第 0/1 波）
> risk_class: `medium` ／ dispatch_gate: `lead_design_and_approval`（架构设计门）
> 本任务只产出本清单：**不移动、不修改任何生产代码或测试**（验证见 §8）。

本文件回答四个问题：

1. 现有 `*_impl` 包壳里，哪些只是"文件搬家 + 别名"，哪些是真正的职责拆分？判别标准是什么？（§1）
2. 六个重点领域的符号依赖长什么样：文件与行数、公开符号及调用方、内部高耦合私有符号、跨领域方向、循环依赖？（§2）
3. 后续每次只拆一个内聚职责时，每步必须守住哪些公开符号、import 路径与 monkeypatch 目标，现有黄金断言够不够，缺哪条必须先补？（§3、§4）
4. 本轮为什么没有代码变更？（§8）

---

## 0. 统计口径

本文件所有数字都可用下列命令复核。**由于本机 PATH 上没有 `rg`**（`rg` 不在 PATH，且常见安装位置均未命中），
§2 的调用方统计用等价的**带显式范围的 Python 扫描**完成（`services`/`web`/`core`/`tools`/`plugins`/`tests`
六个目录，跳过 `__pycache__`），行数用字节换行计数（等价 `wc -l`）。复核时 `rg` 可用则命令等价。

| 指标 | 复核命令（`rg` 可用时） | 本次实际执行 |
|---|---|---|
| 行数 | `wc -l services/aras_crawler.py` | `python -c "print(open('services/aras_crawler.py','rb').read().count(b'\n'))"` |
| 模块调用方数 | `rg -l "^\s*(from\|import)\s+services\.tdc_crawler\b" services web core tools plugins tests` | 范围化 Python 扫描（同上六目录） |
| 符号调用方数 | `rg -l "\bTDCCrawlerClient\b" services web core tools plugins tests` | 同上（按符号名全文匹配） |
| patch 目标 | `rg -n "setattr\(\s*(ps_boot\|crawler_boot\|connectors)," tests` | 别名解析脚本（含缩进/函数内 import） |

**表述约定**：本文件中"范围内未查到"一律表示"在上述六个目录、按上述命令未命中"，
**不表示全局不存在**（例如打包脚本、外部消费方、`.agents/` 下的运行记录不在统计范围内）。

**行数注意**：PowerShell `Get-Content | Measure-Object -Line` 会跳过空行，得出的数偏小（如
`aras_auth.py` 得 967 而真实为 1071）。本文件一律用换行计数，与 `wc -l` 一致。

---

## 1. 判别标准：`_impl` 包壳 ≠ 职责拆分

### 1.1 现状盘点（范围内查到两处 `_impl` 包壳 + 一处同名垫片）

| 位置 | 壳文件 | 实现文件 | 壳再导出名数 | 其中私有名 | 其中 stdlib/模块别名 |
|---|---|---|---|---|---|
| `services/deliverable_form_analysis/` | `__init__.py` 147 行 | `_impl.py` 2940 行 | **136** | **96** | 14 |
| `services/project_status_updates/` | `__init__.py` 80 行 | `_impl.py` 1430 行 | **69** | 20 | 9 |
| `services/project_status_updates.py` | 85 行（同名**垫片**） | 同上 `_impl.py` | 69 | 20 | 9 |

**两处包壳**（前两行）的形态完全一致：**原文件整体改名为 `_impl.py`，包 `__init__.py` 逐名
re-export 全部顶层名字**。第三行不是独立实现，而是同一个 `_impl.py` 的**同名模块垫片**（§1.2）。
两个壳文件的 docstring 自己就写明这是"整包壳"：

- `deliverable_form_analysis/__init__.py:2-8` —— "本包当前是「整包壳」：全部实现仍在 `_impl.py`（原文件逐字节未动）"
- `project_status_updates/__init__.py:2-8` —— 同上，并声明"黄金基线 `tests/golden/project_status_updates/` 锁行为"

**结论（范围内）**：这两处是**"文件搬家 + 别名"**，不是职责拆分。判据不是行数，而是下面三条实证：

1. **壳再导出了 stdlib 名**：`json`、`logging`、`dataclass`、`field`、`datetime`、`date`、`timedelta`、
   `timezone`、`Any`、`Mapping`、`Sequence`、`annotations`、`observed`、`calendar`、`hashlib`、`re`、`emit`。
   真实职责拆分不会把 `json` 变成包的公开面。
2. **壳再导出了 96 个私有名**（`deliverable_form_analysis`）。私有名的存在意义就是"不对外"，
   整包 re-export 等于把内部结构固化成契约。
3. **壳再导出了 `__all__` 本身**（`deliverable_form_analysis/__init__.py:118`），
   壳无法独立控制自己的公开面，`import *` 语义被 `_impl` 单方面决定。

### 1.2 同名模块与包并存：`services/project_status_updates.py` 已被包遮蔽

`services/project_status_updates.py` 与 `services/project_status_updates/` **同时存在于 git**
（`git ls-files` 三个路径都在：`project_status_updates.py`、`project_status_updates/__init__.py`、
`project_status_updates/_impl.py`）。该 `.py` 自称"过渡垫片"，靠设置 `__path__` 声明包身份。

**实测结果**（`python -c "import services.project_status_updates as m; print(m.__file__)"`）：

```
services.project_status_updates -> ...\services\project_status_updates\__init__.py
  is_package: True
```

即：Python 的 `FileFinder` 先查目录再查 `.py`，**同名包胜出，垫片在正常 import 路径下不可达**。
它只可能在"包目录缺失、只剩单文件"的场景（某些打包产物）生效。
这是本清单要求主控裁决的第 1 项（§7），本任务不动它。

### 1.3 web 层的"别名回导"（同样是搬家，不是拆分）

`web/app.py` 有两段 `# noqa: F401` 的纯别名回导：

| 位置 | 来源 | 回导名数 | 其中私有名 |
|---|---|---|---|
| `web/app.py:51` | `web.crawler_boot`（注释 `W13-06/07/09 迁移别名`） | **93** | **90** |
| `web/app.py:147` | `web.project_status_boot`（注释 `W13-09b 迁移别名`） | **45** | **42** |

即 W13-06/07/09 与 W13-09b 的"迁移"把路由体搬到了 `web/crawler_boot.py`（3019 行）与
`web/project_status_boot.py`（2967 行），但 `web.app` 仍保留全部旧名的绑定。
**这是"文件搬家 + 别名"的第二种形态**，而且带一个真实副作用（§5.1）：

> `from web.project_status_boot import _mapping_discovery_query_identity` 会在 `web.app` 里**复制一份引用**。
> 测试 `monkeypatch.setattr(ps_boot, "_mapping_discovery_query_identity", ...)` 只改 `ps_boot` 命名空间，
> **不会**改 `web.app` 里已绑定的那份。补丁是否生效取决于"调用点写在哪个模块"，与补丁写在哪无关。

### 1.4 判别标准（后续任务共用，5 条）

一条拆分只有在**全部满足**时才算"职责拆分"，否则只能记为"搬家 + 别名"：

| # | 判据 | 反例特征（= 仍是搬家） |
|---|---|---|
| D1 | 子模块只再导出**自己职责内**的符号 | 壳导出 `json`/`logging`/`datetime` 等 stdlib 名 |
| D2 | 子模块不再导出与职责无关的**私有**符号 | 96 个 `_` 名前缀符号被整包转发 |
| D3 | 拆分后**没有**任何模块同时依赖被拆开的两半 | 调用方仍在同一函数里混用两半的符号 |
| D4 | 被移动的调用点仍然**经由模块属性**调用（保持 patch 可达） | `from .x import _sleep` 后直接 `_sleep()`，使 `setattr("mod._sleep")` 静默失效 |
| D5 | 至少一条**黄金断言**在拆分前后逐键相等 | 只有单元测试，无 golden 基线 |

D4/D5 是本清单给后续任务设的硬门槛，理由见 §5.1 与 §3。

---

## 2. 六领域符号依赖

行数 = 换行计数。调用方数 = 六个目录中**命中该符号名**的文件数（含 `tests/`），
同一文件多命中记 1。数字偏"宽"（命名匹配而非严格 AST 解析），用于排序风险，不用于精确覆盖率。

### 2.1 表单分析

**文件与行数**

| 文件 | 行数 | 角色 |
|---|---|---|
| `services/deliverable_form_analysis/__init__.py` | 147 | 整包壳（136 名 re-export） |
| `services/deliverable_form_analysis/_impl.py` | 2940 | 全部实现 |

**公开符号与调用方**

| 符号 | 调用方文件数 | 分布 |
|---|---|---|
| `build_form_snapshot` | 18 | services, tests |
| `form_definition` | 17 | plugins, services, tests |
| `FORM_KEYS` | 7 | core, plugins, services, tests |
| `DeliverableFormAnalysisService` | 4 | web, tests |
| `TDC_DATA_MODEL_COMPLETED_STATUSES` | 2 | services, tests |
| `TDC_SYNC_EXCLUDED_STATUSES` | 2 | services |
| `SECTION_ROLLUP_FORM_KEYS` | 2 | web, tests |
| `normalize_tdc_report_status` | 2 | services |
| `summarize_form_rows` | 2 | services, tests |
| `normalize_form_rows` | 2 | tests |
| `FormSnapshotInput` | 2 | tests |
| `classify_overdue` / `aggregate_daily_trend` / `source_absent_indexes` | 各 1 | tests |
| `normalize_form_filters` / `normalize_overdue_thresholds` | 各 0 | 范围内未查到外部调用方 |

**内部高耦合私有符号**（拆分时的实际难点，均被壳整包转发）

- 官方列合并：`_OFFICIAL_JOIN_STATUSES`、`_OFFICIAL_JOIN_UNAVAILABLE`、`_OFFICIAL_STATUS_OK`、
  `_OFFICIAL_STATUS_NOT_REQUESTED`、`_OFFICIAL_SERIAL_KEYS`、`_OFFICIAL_PART_KEYS`、
  `_official_join_key`、`_official_join_marker`、`_official_merged_value`、`_merge_official_columns`、
  `_official_columns_payload`
- D5 数模归因：`_DATA_MODEL_ATTRIBUTION_KEYS`、`_GROUP_LABEL_SEPARATOR`、`_enrich_data_model_dimensions`、
  `_split_data_model_group_filters`、`_filter_rows_by_group_label`、`_data_model_link_payload`、
  `_data_model_group_status`
- 分区汇总：`_ROLLUP_REPORTS`、`_section_stage_matrix`、`_section_counts`、`_section_costs`、
  `_selected_sections`、`_attach_section_rollup_target`、`_filter_rows_by_section_rollup`
- 视图/过滤/图表：`_VIEW_FILTER_KEYS`、`_MULTI_FILTER_KEYS`、`_MULTI_FILTER_MAX_VALUES`、
  `_VIEW_FILTER_TEXT_LIMIT`、`_normalize_filter_text`、`_chart_payload`、`_filter_options`、
  `_recomputed_overdue_state`
- 逾期规则：`_OVERDUE_RULES`、`_TDC_DWELL_REPORTS`、`_TDC_OVERDUE_DWELL_DAYS`、
  `_OVERDUE_THRESHOLD_MIN/MAX`、`_NCR_PROGRESS_STAGE_DATE_LABELS`

**跨领域方向**

- 出边（`_impl.py:9-41`）：只依赖 `core.*`（diagnostic_recording / redaction / report_contracts /
  report_cost_values / section_rollup / form_registry / project_status_contracts）**加两个兄弟服务**
  `services.data_model_attribution`、`services.data_model_vehicle_links`（注释标明"D5 专属"）。
  → 在六个领域中它是**依赖图的底部**（最接近叶子）。
- 入边（31 个文件）：`project_status_connectors`、`project_status_deliverable_analysis`、
  `project_status_records`、`project_status_sync_runner`、`scope_exclusion`、`deliverable_statistics`、
  `scheduled_archive_runner`、`web/app.py`、`web/crawler_boot.py`、`plugins/deliverable_forms/backend.py`、
  `plugins/sign_daily/backend.py`，以及 20 个测试文件。

### 2.2 项目更新 / 项目状态

**文件与行数**

| 文件 | 行数 |
|---|---|
| `services/project_status_updates/__init__.py` | 80（壳） |
| `services/project_status_updates/_impl.py` | 1430 |
| `services/project_status_updates.py` | 85（被遮蔽的垫片，§1.2） |
| `services/project_status_connectors.py` | 982 |
| `services/project_status_sync_runner.py` | 978 |
| `services/project_status_deliverable_analysis.py` | 1458 |
| `services/project_status_discovery.py` | 1170 |
| `services/project_status_records.py` | 471 |
| `services/project_status_scheduler.py` | 346 |
| `services/project_status_analytics.py` | 178 |
| `web/project_status_boot.py` | 2967 |

**公开符号与调用方**

`services.project_status_updates`（20 个调用方文件）：

| 符号 | 调用方 | 符号 | 调用方 |
|---|---|---|---|
| `ProjectStatusUpdateService` | 11 | `compute_policy_config_digest` | 5 |
| `normalize_ewo_v2_rule` | 8 | `PROJECT_STATUS_EDITABLE_FIELDS` | 6 |
| `ConnectorSnapshot` | 7 | `project_status_supports_record_set` | 6 |
| `ConnectorCandidate` | 6 | `WatchlistError` | 6 |
| `ProjectStatusPolicyError` | 6 | `ProjectStatusConfigDigestMismatchError` | 1 |
| `normalize_serial_set` | 5 | `KEEP_CURRENT` | 1 |
| `load_watchlist` | 4 | `PROJECT_STATUS_SYNC_CONTRACTS` | 2 |
| `normalize_single_serial` | 4 | `SyncResult` | 3 |
| `multi_serial_enabled` | 4 | `observation_is_aggregate` | 4 |

`services.project_status_records`（23 个调用方文件）：
`compute_config_signature` 20、`observation_is_aggregate` 6、`build_aggregate_candidate_values` 5、
`record_identity` 4、`identified_records` 4、`authoritative_record_identity` 3、`identity_digest` 3、
`aggregate_fingerprint` 3、`aggregate_content_version` 2、`clean_identity` 2、`identity_fields` 2、
`authoritative_identity_field` 2、`compute_mapping_signature` 1、`normalize_candidate_value` 1。

`services.project_status_connectors`（15 个调用方文件）：
`TDCProjectStatusConnector` 9、`ArasProjectStatusConnector` 5、`RetryingConnector` 2、
`build_project_status_ewo_filters` 2。

`services.project_status_sync_runner`（15 个调用方文件）：
`SyncBindingContext` 10、`ProjectStatusSyncRunner` 7、`ConnectorRegistry` 7、
`create_production_registry` 7、`RunOnceResult` 1、`ProjectStatusConnector` 1、
`BindingReadiness`/`BindingRunResult` 0（范围内未查到外部调用方）。

`services.project_status_scheduler`（3）：`ProjectStatusSyncScheduler` 2、`get_global_scheduler` 2、
`set_global_scheduler` 2、`resolve_sync_interval` 1。
`services.project_status_analytics`（2）：`ProjectStatusAnalyticsService` 2。

**内部高耦合私有符号**

- `project_status_updates/_impl.py` 的 20 个私有名被壳转发，其中与策略校验强耦合：
  `_validate_ewo_v2_policy`、`_normalize_multi_serial_rule`、`_normalize_iso_date_value`、
  `_valid_section_scope`、`_section_scope_conflict_error`、`_multi_serial_rule_error`、
  `_valid_match_rule_values`、`_valid_mapping_source`、`_has_control_chars`、`_single_serial_error`、
  `_sanitize_value`、`_json_dumps`、`_json_loads`、`_contains_forbidden_config_key`，
  以及上限常量 `_SECTION_SCOPE_MAX_ITEMS`、`_SECTION_SCOPE_MAX_LEN`、`_SYNC_TEXT_LIMITS`、
  `_TEXT_LIMITS`、`_FORBIDDEN_CONFIG_FRAGMENTS`、`_logger`。
- `project_status_connectors.py`：19 个私有（`_snapshot`、`_ewo_v2_snapshot`、`_aggregate_snapshot`、
  `_identity`、`_stable_version`、`_read_official_snapshot_rows`、`_filter_ncr_rows_by_department`、
  `_emit_tdc_status_distribution` 等）+ 模块级 `_MAX_ROWS`（第 72 行，= `MAX_AGGREGATE_RECORDS`）。
- `project_status_deliverable_analysis.py`：24 个私有，签署人/阶段解析一族（`_signer_role_person`、
  `_signer_entries_from_text`、`_signer_pairs`、`_stage_filter`、`_department_filters`、`_item_stage`）。
- `project_status_discovery.py`：`_scalar`、`_key`、`_report_type`、`_aggregate_report`。

**跨领域方向**

```
project_status_connectors  --(模块级)-->  project_status_sync_runner   (connectors.py:39)
project_status_sync_runner --(函数内延迟)--> project_status_connectors (sync_runner.py:945)
project_status_connectors  -->  project_status_updates, project_status_records,
                               project_status_deliverable_analysis, deliverable_form_analysis,
                               scope_exclusion, tdc_official_rows, tdc_auth, tdc_crawler,
                               aras_auth, aras_crawler, aras_department_mapping
project_status_sync_runner -->  project_status_updates, project_status_deliverable_analysis,
                               deliverable_form_analysis, aras_auth, aras_crawler, tdc_auth, tdc_crawler
project_status_discovery   -->  project_status_records
project_status_updates/_impl --> project_status_records
project_status_deliverable_analysis --> deliverable_form_analysis
```

### 2.3 Aras

| 文件 | 行数 | 主要公开符号（调用方文件数） |
|---|---|---|
| `services/aras_crawler.py` | 1486 | `ArasCrawlerClient` 13、`ArasCrawlerError` 10、`ArasAuthenticationError` 7、`EWOReportFilters` 8、`PAAReportFilters` 6、`NCRApprovalFilters` 5、`EWOReportPage` 4、`PAAReportPage` 4、`ArasNcrExportContractError` 3、`CrawlCancelled` 3、`NCRExportResult` 1、`ArasHttpDiagnosticEvent` 0、`NCRDetailExportResult` 0、`NCRVaultFileLocation` 0 |
| `services/aras_auth.py` | 1071 | `ArasAuthError` 8、`ArasECMAuthClient` 7、`ArasLoginResult` 1、`ArasAuthHttpDiagnosticEvent` 0 |
| `services/aras_export.py` | 253 | `export_report_contract_csv` 2、`export_report_csv` 1、`export_ewo_report_csv` 1、`CSVExportResult` 1、`EWOExportResult` 0 |
| `services/aras_ncr_workbook.py` | 299 | `parse_ncr_workbook` 5、`NcrWorkbookRow` 3、`require_complete_workbook` 2、`NcrWorkbookError` 2、`NcrWorkbookOutcome` 2 |
| `services/aras_department_mapping.py` | 128 | `parse_ncr_section_codes_input` 3、`normalize_departments` 2、`resolve_ncr_section_codes` 2 |
| `services/aras_xml.py` | 67 | `sanitize_aras_xml` 2、`ArasXmlCaptureError` 2 |

**内部高耦合私有符号**：`aras_crawler` 24 个（`_soap_envelope`、`_parse_item_rows`、`_element`、
`_search_elements`、`_cdata`、`_parse_xml`、`_validate_download_file_name`、`_resolve_download_target`、
`_reject_html_download`、`_atomic_write_download`、`_validate_page_limits`、`_validate_crawl_limits`、
`_redact_diagnostic` 等）；`aras_auth` 27 个（`_LoginForm`、`_LoginFormParser`、`_RequestTrace`、
`_parse_login_form`、`_parse_advalidate_response`、`_is_valid_md5`、`_new_native_aras_session`、
`_validate_user_response_has_id`、`_validate_client_id`、`_validate_redirect_uri` 等）。

**跨领域方向**：`aras_auth --> aras_crawler`（单向，无回边）；`aras_export --> aras_crawler`。
入边来自 `project_status_connectors`、`project_status_sync_runner`、`scheduled_archive_connectors`、
`scheduled_archive_runner`、`ewo_export_transport`、`web/crawler_boot.py`、`web/ewo_enrichment.py`、
`web/host_boot.py`、`web/project_status_boot.py`。**Aras 不依赖 project_status 与 TDC**（范围内无入边反向）。

### 2.4 TDC

| 文件 | 行数 | 主要公开符号（调用方文件数） |
|---|---|---|
| `services/tdc_crawler.py` | 1823 | `TDCCrawlerError` 14、`TDCCrawlerClient` 11、`TDCDataModelFilters` 8、`flatten_sor_rows` 6、`TDCSORFilters` 5、`TDCPagedResult` 4、`CrawlCancelled` 3、`TDCHttpDiagnosticEvent` 2、`TDCAFaceFilters` 1、`TDCExportResult` 1、`flatten_sor_value` 1、`combine_diagnostic_hooks` 0 |
| `services/tdc_contract_probe.py` | 938 | `build_report` 2、`TDCContractProbeOptions` 1、`TDCContractProbeResult` 1、`validate_options` 1、`profile_rows` 1 |
| `services/tdc_auth.py` | 852 | `TDCAuthError` 10、`TDCPasswordAuthClient` 9、`TDCLoginResult` 3 |
| `services/tdc_export_cache.py` | 160 | `TDCExportCache` 5、`TDCExportCacheResult` 0 |
| `services/tdc_official_rows.py` | 95 | `read_official_tdc_rows` 5、`OfficialWorkbookTruncated` 4、`OfficialWorkbookContractError` 4、`official_contract_headers` 3、`OfficialWorkbookUnreadable` 3、`project_official_rows` 1、`OfficialWorkbookError` 0 |

**内部高耦合私有符号**：`tdc_crawler` 31 个，含重试一族 `_retry_after_seconds`、`_retry_wait_seconds`、
`_sleep`（第 83 行 `_sleep = time.sleep`）、`_RETRY_TOTAL_BUDGET_SECONDS`（第 81 行 = 20.0）、
分页一族 `_pagination_int`、`_validate_pagination`、`_compact_params`，以及诊断脱敏一族
`_safe_headers`、`_safe_query`、`_request_id`、`_elapsed_ms`、`_safe_filename`、`_content_disposition_filename`。
`tdc_auth` 23 个（与 `aras_auth` 结构高度同形：`_LoginForm`、`_LoginFormParser`、`_RequestTrace`、
`_new_native_tdc_session`、`_basic_authorization` 等）。

**跨领域方向**：`tdc_auth --> tdc_crawler`（单向）。`tdc_contract_probe` 只被 `tdc_probe_cli.py`
与 2 个测试引用（范围内），是**最孤立的 TDC 模块**。入边来自 `project_status_connectors`、
`project_status_sync_runner`、`scheduled_archive_connectors`、`scheduled_archive_runner`、
`web/crawler_boot.py`、`web/project_status_boot.py`。

### 2.5 发现（mapping discovery）

| 文件 | 行数 | 说明 |
|---|---|---|
| `services/project_status_discovery.py` | 1170 | `MappingDiscoveryService`（7 个调用方文件） |
| `web/project_status_boot.py` | 2967 | 会话缓存/取消登记实际住在 web 层：`_DISCOVERY_SESSION_MAX_ENTRIES`、`_DISCOVERY_SESSION_TTL_SECONDS`、`_get_discovery_session_cache`、`_set_discovery_session_cache`、`_get_discovery_session_cache_total`、`_register_discovery_cancel`、`_release_discovery_cancel`、`_MAPPING_DISCOVERY_TASKS`、`_MAPPING_DISCOVERY_TASKS_LOCK`、`_MAPPING_DISCOVERY_TERMINAL_STATUSES`、`_mapping_discovery_*`、`_stability_paged_sample`、`_STABILITY_SAMPLE_MAX_PAGES`、`_STABILITY_SAMPLE_PAGE_SIZE` |

**这是六个领域里唯一的"跨层内聚职责"**：一个业务能力（映射取证）被切成 service 类 + web 层会话缓存
两半，且缓存的可变状态（`_MAPPING_DISCOVERY_TASKS` + 锁）留在 web 模块的全局命名空间里。

**内部高耦合私有符号**：`_scalar`、`_key`、`_report_type`、`_aggregate_report`（service 侧）；
web 侧见上表（22 个私有名被 `web/app.py` 回导，其中 42 个私有名里有这些）。

**跨领域方向**：`project_status_discovery --> project_status_records`（第 17 行）；
函数内延迟 import `core.ewo_binding_v2`、`services.ewo_binding_records`（第 180、230、1081 行）。
入边：`web/app.py` + 4 个测试文件。**service 侧不反向依赖 web**（范围内无入边）。

### 2.6 交付物分析

| 文件 | 行数 | 主要公开符号（调用方文件数） |
|---|---|---|
| `services/project_status_deliverable_analysis.py` | 1458 | `ProjectStatusDeliverableAnalysisService` 7、`analysis_source_type` 3、`normalize_analysis_rows` 3、`summarize_analysis_items` 2、`normalize_ewo_stage` 1、`normalize_pending_signers` 1、`is_ewo_source_type` 1 |
| `services/deliverable_statistics.py` | 455 | 统计侧消费者（依赖 `deliverable_form_analysis`） |
| `web/app.py` | 745 | 注册 `app.extensions["deliverable_analysis"]`（第 426 行）与 `["deliverable_form_analysis"]`（第 466 行） |

**注意命名陷阱**：`CONTRACTS.md` C1 的服务字典里有 `deliverable_analysis` 与 `deliverable_form_analysis`
两个键，但**不存在 `services/deliverable_analysis.py` 模块**（实测 import 失败）。
`deliverable_analysis` 服务 = `ProjectStatusDeliverableAnalysisService`（`web/app.py:43,420,426`）。
后续任务若按服务名找模块会找错文件。

**内部高耦合私有符号**：24 个，集中在 EWO 阶段/签署人/科室过滤
（`_signer_role_person`、`_signer_entries_from_text`、`_signer_pairs`、`_stage_filter`、`_stage_filters`、
`_department_filters`、`_department_in_default_scope`、`_item_stage`、`_item_source_type`、
`_alert_type`、`_completed`、`_tdc_data_model_completed`、`_aras_record_close`）；
常量一族 `EWO_STAGES`、`EWO_ACTIVE_STAGES`、`EWO_TERMINAL_STAGE`、`EWO_IGNORED_STAGE`、
`EWO_DEFAULT_DEPARTMENTS`、`EWO_DEPARTMENT_KEYWORDS`、`EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION`、
`EWO_FIELD_LABELS`。

**跨领域方向**：出边只有一条 `--> deliverable_form_analysis`（第 21 行，
`TDC_DATA_MODEL_COMPLETED_STATUSES`）。入边：`project_status_connectors`、`project_status_records`、
`project_status_sync_runner`、`web/app.py`、`web/project_status_boot.py` + 8 个测试文件。

### 2.7 依赖方向总图与循环依赖

```
                       ┌──────────────────────────────┐
                       │  core/* (契约、存储、脱敏)    │
                       └──────────────▲───────────────┘
                                      │
   deliverable_form_analysis ─────────┘  （底部叶子；额外依赖两个兄弟服务）
        ▲   ▲   ▲
        │   │   └── project_status_deliverable_analysis
        │   └────── scope_exclusion ──┐
        └────────── project_status_records
                                          │
   aras_*  ──(单向)──► aras_crawler        │
   tdc_*   ──(单向)──► tdc_crawler         │
                                          ▼
                        project_status_connectors ◄──────┐
                              │  (模块级)                  │
                              ▼                            │ (函数内延迟, sync_runner.py:945)
                        project_status_sync_runner ───────┘
                              ▲
                        web/project_status_boot ──► web/crawler_boot
                              ▲                        ▲
                              └────── web/app.py ──────┘
```

**循环依赖（范围内查到 1 处）**

| 环 | 正向边 | 反向边 | 掩盖方式 |
|---|---|---|---|
| `project_status_connectors` ⇄ `project_status_sync_runner` | `connectors.py:39` 模块级 `from services.project_status_sync_runner import SyncBindingContext` | `sync_runner.py:945` **函数内** `from services.project_status_connectors import ...`（在 `create_production_registry()` 体内） | 延迟导入 |

这是**真实存在的环**，只是因为反向边写在函数体内才没在 import 期炸。
它的直接后果：`create_production_registry` 是"环的闭合点"，因此它同时成了 7 个调用方文件的入口
**和** 测试的 patch 目标（§5.1）。任何"把 connectors 拆走"的任务都必须先处理这条边，
否则会得到 `ImportError` 或更糟的静默降级。

**范围内未查到的其他环**：`aras_auth → aras_crawler`、`tdc_auth → tdc_crawler`、
`discovery → records`、`deliverable_analysis → form_analysis` 均为单向，未发现回边。

---

## 3. 黄金与契约测试现状（覆盖矩阵）

**基线实测**（本任务执行，未改动任何文件）：

```
python -m pytest tests/test_deliverable_form_analysis_golden.py \
                 tests/test_project_status_updates_golden.py \
                 tests/test_route_contract_snapshot.py -q -p no:cacheprovider
=> 18 passed in 5.86s
```

| 领域 | golden 目录 | 文件数/字节 | 锁定的入口 | 实际覆盖的 form key | 缺口 |
|---|---|---|---|---|---|
| 表单分析 | `tests/golden/form_analysis/` | 3 个（50.8KB / 17.3KB / 71.7KB） | `form_definition()`、`service.view()`、`service.rows()` | `VPI-T2-D3`、`tdc_sor`、`aras_ncr_progress` | **`tdc_data_model`、`aras_ncr_detail`、`aras_paa` 三个 key 无 golden**（6 个 key 只覆盖 3 个） |
| 项目更新 | `tests/golden/project_status_updates/` | 5 个（1.4–2.9KB） | `get_update_policy`、`update_update_policy`、`update_update_policy_rejected`、`apply_sync_update`、`list_updates` | — | `scheduler` / `analytics` / `connectors` / `sync_runner` **无 golden** |
| Aras | 范围内未查到 | — | — | — | **整域无 golden** |
| TDC | 范围内未查到 | — | — | — | **整域无 golden**（`tdc_contract_probe` 只有单测） |
| 发现 | 范围内未查到 | — | — | — | **整域无 golden** |
| 交付物分析 | 范围内未查到 | — | — | — | **整域无 golden** |
| 全局路由 | `tests/golden/routes.json` | 44.8KB | `create_app()` 全部路由（断言 ≥80 条） | — | 只锁**路由形状**（rule/method/endpoint/view_function/is_write/envelope/download），**不锁业务载荷** |

**关键数量关系**（决定后续任务能否开工）

- `FORM_KEYS` = 6 个：`tdc_sor`、`tdc_data_model`、`aras_ncr_detail`、`aras_ncr_progress`、`aras_paa`、`VPI-T2-D3`
- `SECTION_ROLLUP_FORM_KEYS` = 5 个：`tdc_data_model`、`aras_ncr_detail`、`aras_ncr_progress`、`aras_paa`、`VPI-T2-D3`
- golden 覆盖其中的 `aras_ncr_progress`、`VPI-T2-D3`（**2 / 5**）

即：**分区汇总路径有 3 个 key 完全没有黄金断言**，而 `SECTION_ROLLUP_FORM_KEYS` 本身是被
`web` 层直接 import 的公开符号（2 个调用方文件）。

---

## 4. 后续拆分任务序列

### 4.1 本序列的硬规则

1. **一个任务只拆一个内聚职责**，不允许"顺手"再拆第二个。
2. 每个任务开工前必须先在任务契约里冻结：**公开符号清单**（`from <mod> import X` 与 `<mod>.X` 两种
   用法都算）、**import 路径**、**monkeypatch 目标清单**（含 §5.1 的三类陷阱）。
3. 每个任务必须有一条**拆分前后逐键相等**的黄金断言（判据 D5）；缺的**先补测试再拆**，
   补测与拆分可以是同一批次的两个提交，但不允许"先拆再补"。
4. 拆分后仍须满足判据 D1–D4。
5. 由 lead 逐项批准后执行。

### 4.2 建议序列（按风险升序）

排序依据：**先拆有 golden 兜底的、再拆缺 golden 但耦合浅的、最后拆跨层且无 golden 的**。

---

#### T1 项目状态更新：watchlist 与多序列纯函数

| 项 | 内容 |
|---|---|
| 迁出职责 | 关注清单加载与多值序列规范化（纯函数，无 IO 副作用） |
| 迁出符号 | `load_watchlist`、`normalize_serial_set`、`normalize_single_serial`、`multi_serial_enabled`、`WatchlistError`、`MAX_WATCHLIST_BYTES`、`MULTI_SERIAL_DISABLED_MESSAGE`、`MULTI_SERIAL_EXTERNAL_KEY_MESSAGE`、`SCOPE_WATCHLIST` |
| 必须不变 | 上述 9 个名字继续可从 `services.project_status_updates` 与 `services.project_status_updates.<name>` 取得；壳 `__init__.py` 的 re-export 行保留 |
| monkeypatch 目标 | 范围内未查到直接 patch 这些名字（`tests/test_data_model_watchlist.py` 用真实实现） |
| 现有覆盖 | `tests/golden/project_status_updates/get_update_policy.json`（含 watchlist 载荷）、`tests/test_project_status_updates.py`、`tests/test_data_model_watchlist.py`、`tests/test_project_status_policy_api.py` |
| **缺口（必须先补）** | golden 只覆盖"策略读取成功"一条路径；`MULTI_SERIAL_DISABLED_MESSAGE` / `MULTI_SERIAL_EXTERNAL_KEY_MESSAGE` 两条拒绝分支在 golden 里没有对应变体 → 先补 2 个 policy 变体 golden |

---

#### T2 项目状态更新：策略校验与规范化纯函数

| 项 | 内容 |
|---|---|
| 迁出职责 | 更新策略的入参校验、规范化、禁用键扫描、JSON 编解码（全部纯函数） |
| 迁出符号 | `_validate_ewo_v2_policy`、`_normalize_multi_serial_rule`、`_normalize_iso_date_value`、`_valid_section_scope`、`_section_scope_conflict_error`、`_multi_serial_rule_error`、`_valid_match_rule_values`、`_valid_mapping_source`、`_has_control_chars`、`_single_serial_error`、`_sanitize_value`、`_json_dumps`、`_json_loads`、`_contains_forbidden_config_key`、`_SECTION_SCOPE_MAX_ITEMS`、`_SECTION_SCOPE_MAX_LEN`、`_SYNC_TEXT_LIMITS`、`_TEXT_LIMITS`、`_FORBIDDEN_CONFIG_FRAGMENTS` |
| 必须不变 | 这 19 个**私有**名当前经壳对外可见（§1.1），必须继续从包 `__init__` re-export，否则属收窄契约 |
| monkeypatch 目标 | 无直接命中；但 `tests/conftest.py:129-222` 的 `trace()` 按**名字字符串**补 `db.record_deliverable_config_audit`（见 §5.1 陷阱 3），T2 不得改变该方法的宿主 |
| 现有覆盖 | `tests/golden/project_status_updates/update_update_policy_rejected.json`（HTTP 422 形状）、`tests/test_bprime_config_audit_mixed.py`、`test_bprime_config_concurrency_digest.py`、`test_bprime_config_preread_*.py`、`tests/test_sync_scope_contract_guards.py` |
| **缺口** | rejected golden 只锁"某一条"拒绝形状，未按校验分支参数化 → 先按分支补参数化 golden（每个 `*_error` 构造函数一条） |

---

#### T3 表单分析：D5 数模归因适配层

| 项 | 内容 |
|---|---|
| 迁出职责 | `tdc_data_model` 专属的"项目件 / 架构件"分组与链接载荷（`_impl.py` 内注释已声明"D5 专属，其他交付物不引用"） |
| 迁出符号 | `_DATA_MODEL_ATTRIBUTION_KEYS`、`_GROUP_LABEL_SEPARATOR`、`_enrich_data_model_dimensions`、`_split_data_model_group_filters`、`_filter_rows_by_group_label`、`_data_model_link_payload`、`_data_model_group_status` |
| 必须不变 | 上述私有名继续经 `services.deliverable_form_analysis` 可见 |
| **monkeypatch 目标（关键）** | `tests/test_deliverable_form_analysis.py:344` 补 `"services.deliverable_form_analysis._impl.emit"`。若 `emit` 的**调用点**随职责迁出 `_impl`，该 patch 会**静默失效**（不报错、只是不再记录事件，而测试断言的是事件内容）→ 迁出后必须让新子模块也以模块属性方式调用 `emit`，并同步把 patch 目标改成新路径，或在新子模块中重新绑定 |
| 现有覆盖 | `tests/test_data_model_attribution.py`、`tests/test_data_model_vehicle_links.py`（单元级） |
| **缺口（阻塞）** | **`tdc_data_model` 这个 form key 没有 golden**（§3）。D5 是本文件里逻辑最绕的一段（历史上有过把 SOR 号当归属证据的错误），**无 golden 不得拆** → 先补第 4 个 form key 的 golden（`form_definition` / `view` / `rows` 三入口） |

---

#### T4 表单分析：官方列合并层

| 项 | 内容 |
|---|---|
| 迁出职责 | 官方导出列与列表行的 join / 合并 / 缺失标记 |
| 迁出符号 | `_OFFICIAL_JOIN_STATUSES`、`_OFFICIAL_JOIN_UNAVAILABLE`、`_OFFICIAL_STATUS_OK`、`_OFFICIAL_STATUS_NOT_REQUESTED`、`_OFFICIAL_SERIAL_KEYS`、`_OFFICIAL_PART_KEYS`、`_TDC_DATA_MODEL_DIAGNOSTIC_TYPE`、`_official_join_key`、`_official_join_marker`、`_official_merged_value`、`_merge_official_columns`、`_official_columns_payload` |
| 必须不变 | 上述 12 个名字的可见性；`tdc_sor` 的 `view`/`rows` 逐键不变 |
| monkeypatch 目标 | 同 T3（`_impl.emit`） |
| 现有覆盖 | golden `view.json`/`rows.json` 的 `tdc_sor`（走官方合并路径）、`aras_ncr_progress` |
| **缺口** | `aras_paa`、`tdc_data_model` 的合并路径无 golden → 先补这两个 key（与 T3 的补测可合并为同一个补测任务） |

---

#### T5 表单分析：分区汇总层

| 项 | 内容 |
|---|---|
| 迁出职责 | 科室分区矩阵与汇总（`SECTION_ROLLUP_FORM_KEYS` 声明的 5 个 form key 共用） |
| 迁出符号 | `_ROLLUP_REPORTS`、`SECTION_ROLLUP_FORM_KEYS`、`_section_stage_matrix`、`_section_counts`、`_section_costs`、`_selected_sections`、`_attach_section_rollup_target`、`_filter_rows_by_section_rollup` |
| 必须不变 | `SECTION_ROLLUP_FORM_KEYS` 是**公开符号**（web + tests 共 2 个调用方），import 路径不得变 |
| monkeypatch 目标 | 同 T3 |
| 现有覆盖 | golden 的 `VPI-T2-D3`、`aras_ncr_progress`（2 / 5） |
| **缺口（阻塞）** | `SECTION_ROLLUP_FORM_KEYS` 的 5 个 key 里 **3 个（`tdc_data_model`、`aras_ncr_detail`、`aras_paa`）无 golden** → 先补齐 |

---

#### T6 表单分析：视图过滤与图表载荷

| 项 | 内容 |
|---|---|
| 迁出职责 | 视图过滤键解析、多值上限、过滤选项、图表载荷、逾期状态重算 |
| 迁出符号 | `_VIEW_FILTER_KEYS`、`_MULTI_FILTER_KEYS`、`_MULTI_FILTER_MAX_VALUES`、`_VIEW_FILTER_TEXT_LIMIT`、`_RELATION_FIELD_BY_REPORT`、`_normalize_filter_text`、`normalize_form_filters`、`normalize_overdue_thresholds`、`_chart_payload`、`_filter_options`、`_recomputed_overdue_state` |
| 必须不变 | `normalize_form_filters` / `normalize_overdue_thresholds` 是**公开符号**（当前外部调用方 0，但仍属公开面） |
| monkeypatch 目标 | 同 T3 |
| 现有覆盖 | golden `view.json`（默认视图） |
| **缺口** | 过滤/图表只在默认参数下被 golden 覆盖，参数化分支无断言 → 先补参数化 golden（至少：多值超限、非法过滤键、逾期阈值上下界） |

---

#### T7 Aras：下载落盘与原子写

| 项 | 内容 |
|---|---|
| 迁出职责 | NCR 附件下载的文件名校验、目标解析、HTML 拒绝、原子写盘 |
| 迁出符号 | `_validate_download_file_name`、`_resolve_download_target`、`_reject_html_download`、`_atomic_write_download`、`NCRVaultFileLocation`（`NCRVaultFileLocation` 是公开符号，调用方 0，属公开面） |
| 必须不变 | `services.aras_crawler` 的 14 个公开符号与 `__all__`；`NCRVaultFileLocation` 路径不变 |
| monkeypatch 目标 | 范围内未查到对 `aras_crawler` 私有名的 patch（`tests/test_aras_crawler.py` 走合成响应） |
| 现有覆盖 | `tests/test_aras_crawler.py`、`tests/test_aras_paa_crawler.py`、`tests/test_aras_cli_web.py` |
| **缺口（阻塞）** | **整域无 golden** → 先补 `tests/golden/aras/` 或等价的契约快照（建议：一组合成 SOAP 响应 → 解析结果逐键 golden），否则拆完无法证明"下载语义未变" |

---

#### T8 Aras：OIDC 与登录表单解析

| 项 | 内容 |
|---|---|
| 迁出职责 | 登录页表单解析、ADValidate 响应解析、原生会话构造、client/redirect 参数校验 |
| 迁出符号 | `_LoginForm`、`_LoginFormParser`、`_RequestTrace`、`_parse_login_form`、`_parse_advalidate_response`、`_is_valid_md5`、`_new_native_aras_session`、`_is_login_page`、`_has_challenge`、`_validate_user_response_has_id`、`_validate_client_id`、`_validate_redirect_uri`、`_validate_random_value`、`_validate_timeout` |
| 必须不变 | `ArasECMAuthClient`、`ArasAuthError`、`ArasLoginResult`、`ArasAuthHttpDiagnosticEvent` 四个公开符号 |
| monkeypatch 目标 | `tests/test_aras_auth.py:704` 补的是 `_sys.platform`，与模块符号无关；**无直接 patch** |
| 现有覆盖 | `tests/test_aras_auth.py` |
| **缺口（阻塞）** | 无 golden；且 `aras_auth` 与 `tdc_auth` 结构同形（`_LoginForm`/`_LoginFormParser`/`_RequestTrace` 三件套几乎逐字重复）→ 建议本任务**只拆 Aras 一侧**，把"两侧共用化"留作独立评估（涉及跨域共享，属 lead 决策） |

---

#### T9 TDC：重试与分页记账

| 项 | 内容 |
|---|---|
| 迁出职责 | 重试预算、退避等待、Retry-After 解析、分页参数校验 |
| 迁出符号 | `_RETRY_TOTAL_BUDGET_SECONDS`、`_sleep`、`_retry_after_seconds`、`_retry_wait_seconds`、`_pagination_int`、`_validate_pagination` |
| 必须不变 | **`services.tdc_crawler._sleep` 与 `services.tdc_crawler._RETRY_TOTAL_BUDGET_SECONDS` 必须继续是"可被 `setattr` 的模块属性"** |
| **monkeypatch 目标（最高风险项）** | `tests/test_tdc_crawler.py` 补 `services.tdc_crawler._sleep` 与 `services.tdc_crawler._RETRY_TOTAL_BUDGET_SECONDS`。当前 `_sleep` 是模块级别名（`tdc_crawler.py:83` `_sleep = time.sleep`），**唯一调用点**是 `tdc_crawler.py:899` 的 `_sleep(wait)`。若拆分后新子模块写 `from .tdc_retry import _sleep` 再直接调用，patch 目标 `services.tdc_crawler._sleep` 就**再也拦不住**——测试仍会通过（因为真实 sleep 被预算截断），只是变慢且不再验证退避逻辑，属**静默失效**。必须保留 `services.tdc_crawler._sleep(...)` 的模块属性调用形式 |
| 现有覆盖 | `tests/test_tdc_crawler.py`、`tests/test_crawler_pagination_integrity.py`、`tests/test_pagination_integrity.py` |
| **缺口（阻塞）** | 无 golden；建议先补"给定合成 429/500 序列 → 重试次数与总耗时的确定性记录"golden（用假时钟），否则无法证明拆分未改退避语义 |

---

#### T10 发现：映射取证会话缓存

| 项 | 内容 |
|---|---|
| 迁出职责 | 发现会话的 TTL/LRU 缓存、并发任务登记、取消登记、稳定性抽样 |
| 迁出符号 | `_DISCOVERY_SESSION_MAX_ENTRIES`、`_DISCOVERY_SESSION_TTL_SECONDS`、`_get_discovery_session_cache`、`_set_discovery_session_cache`、`_get_discovery_session_cache_total`、`_register_discovery_cancel`、`_release_discovery_cancel`、`_MAPPING_DISCOVERY_TASKS`、`_MAPPING_DISCOVERY_TASKS_LOCK`、`_MAPPING_DISCOVERY_TERMINAL_STATUSES`、`_stability_paged_sample`、`_STABILITY_SAMPLE_MAX_PAGES`、`_STABILITY_SAMPLE_PAGE_SIZE` |
| 必须不变 | 这些名字当前经 `web/app.py:147` 回导（42 个私有名之一部分）；同时 `web/project_status_boot` 内部直接引用 → 两者都要能取到 |
| **monkeypatch 目标** | `web.project_status_boot._mapping_discovery_query_identity`（1 处，`tests/test_project_status_api.py:1603`）；`web.project_status_boot._build_tdc_client_from_payload`（29 处）——后者若随会话缓存一起搬家，**29 个调用点全部失效** |
| 现有覆盖 | `tests/test_project_status_discovery.py`、`tests/test_project_status_api.py`、`tests/test_data_model_identity_contract.py` |
| **缺口（阻塞）** | 无 golden；且这是**跨层职责**（service 类 + web 全局可变状态）→ 建议本任务降级为"先在 `services/` 内建一个纯会话对象并由 web 注入"，保持 `_build_tdc_client_from_payload` 在原地不动。需 lead 明确边界后再拆 |

---

#### T11 交付物分析：EWO 阶段与签署人规范化

| 项 | 内容 |
|---|---|
| 迁出职责 | EWO 阶段词表、签署人解析、科室过滤、完成/关闭判定（全部纯函数 + 常量） |
| 迁出符号 | `EWO_STAGES`、`EWO_ACTIVE_STAGES`、`EWO_TERMINAL_STAGE`、`EWO_IGNORED_STAGE`、`EWO_DEFAULT_DEPARTMENTS`、`EWO_DEPARTMENT_KEYWORDS`、`EWO_DEFAULT_RSP_DEPARTMENT_EXPRESSION`、`EWO_FIELD_LABELS`、`normalize_ewo_stage`、`normalize_pending_signers`、`_signer_role_person`、`_signer_entries_from_text`、`_signer_pairs`、`_stage_filter`、`_stage_filters`、`_department_filters`、`_department_in_default_scope`、`_item_stage`、`_item_source_type`、`_completed`、`_tdc_data_model_completed`、`_aras_record_close`、`_alert_type` |
| 必须不变 | `ProjectStatusDeliverableAnalysisService`、`normalize_analysis_rows`、`summarize_analysis_items`、`normalize_ewo_stage`、`normalize_pending_signers`、`is_ewo_source_type`、`analysis_source_type` 七个公开符号 |
| monkeypatch 目标 | 范围内未查到对该模块的直接 patch |
| 现有覆盖 | `tests/test_project_status_deliverable_analysis.py`、`tests/test_ewo_department_stage_feature.py`、`tests/test_ewo_v2_integration.py`、`tests/test_deliverable_analysis_paging.py` |
| **缺口（阻塞）** | 无 golden → 先补"合成 EWO 行集 → 分析结果逐键"golden |

---

### 4.3 补测任务（必须排在对应拆分之前）

| 补测任务 | 服务对象 | 内容 |
|---|---|---|
| G1 | T1 | `project_status_updates` golden 增补 2 个多序列拒绝变体 |
| G2 | T2 | `update_update_policy_rejected` 按校验分支参数化 |
| G3 | T3、T4、T5 | 表单分析 golden 增补 `tdc_data_model`、`aras_ncr_detail`、`aras_paa` 三个 form key（三入口 `form_definition`/`view`/`rows`） |
| G4 | T6 | 视图过滤参数化 golden（多值超限、非法键、逾期阈值边界） |
| G5 | T7、T8 | 新建 `tests/golden/aras/`：合成 SOAP/登录响应 → 解析结果逐键 |
| G6 | T9 | 假时钟 + 合成 429/500 序列 → 重试次数/总耗时确定性 golden |
| G7 | T10 | 发现会话缓存 TTL/LRU/取消登记的行为快照 |
| G8 | T11 | 合成 EWO 行集 → 分析结果逐键 golden |

**G3 是最高优先级**：它同时解锁 T3、T4、T5 三个任务，且当前 6 个 form key 有 3 个完全无 golden。

---

## 5. 高风险耦合清单

### 5.1 monkeypatch 目标（W13-09b 教训的三类陷阱）

**统计口径**：`tests/` 内，解析文件自身的 import 别名（含**缩进/函数内** import）后，
统计对目标模块的 `setattr(别名, "属性", ...)` / `patch.object(别名, "属性", ...)`。
字符串形式（`setattr("模块.属性", ...)`）单列。

| 目标模块 | 调用点数 | 目标属性（次数） |
|---|---|---|
| `web.app` | 57 | `DatabaseManager` **56**（分布于 51 个测试文件）、`app_root` 1（路由快照） |
| `web.crawler_boot` | 38 | `_shared_domain_session` 16、`ArasECMAuthClient` 5、`ArasCrawlerClient` 4、`TDCCrawlerClient` 3、`DIAGNOSTIC_DIR` 2、`MarkdownDiagnosticReport` 2、`_tdc_official_data_model_preview` 2、`_build_aras_client_from_payload` 2、`TDCPasswordAuthClient` 1、`_STATISTICS_MAX_HISTORY_ROWS` 1 |
| `web.project_status_boot` | 33 | `_build_tdc_client_from_payload` **29**、`create_production_registry` 1、`_build_aras_client_from_payload` 1、`_mapping_discovery_query_identity` 1、`_crawl_runner_from_request` 1 |
| `services.project_status_connectors` | 12 | `emit` 10、`_MAX_ROWS` 1、`_collect_ncr_rows` 1（类属性） |
| `services.tdc_crawler` | 2 | `_sleep` 1、`_RETRY_TOTAL_BUDGET_SECONDS` 1 |
| `services.aras_ncr_workbook` | 2 | `parse_ncr_workbook` 2（函数内 `import ... as workbook` 后 patch） |

**字符串形式目标**（不受别名解析影响，但同样是契约）

| 目标字符串 | 次数 | 位置 |
|---|---|---|
| `services.tdc_auth.requests.Session` | 5 | `tests/test_tdc_auth.py:406,438,468,492,538` |
| `services.aras_ncr_workbook.read_xlsx_workbook_preview` | 3 | `test_aras_ncr_workbook.py:32,173`、`test_scheduled_archive_connectors.py:365` |
| `services.deliverable_form_analysis._impl.emit` | 1 | `test_deliverable_form_analysis.py:344` |
| `services.project_status_connectors.emit` | 1 | `test_project_status_connectors.py:1103` |
| `services.tdc_official_rows.read_xlsx_preview` | 1 | `test_scheduled_archive_connectors.py:386` |
| `services.aras_export._verify_csv` | 1 | `test_aras_export.py:208` |
| `web.project_status_boot.create_production_registry` | 1 | `test_car_type_anchor_sync.py:149` |
| `web.app.create_app` | 1 | `test_webui_excel_worker_sentinel.py:161` |

**三类陷阱（后续任务必须逐条核对）**

| 陷阱 | 实证 | 后果 |
|---|---|---|
| **① 私有名是 patch 目标** | `services.tdc_crawler._sleep`、`._RETRY_TOTAL_BUDGET_SECONDS`、`._MAX_ROWS`、`._collect_ncr_rows`、`services.aras_export._verify_csv` | 拆分时"私有名可以随便挪"的直觉是错的；挪走后 patch 静默失效 |
| **② 函数内 import 生成别名** | `tests/test_project_status_connectors.py:1018,1074` 的 `import services.aras_ncr_workbook as workbook`；`conftest.py` 的按名补丁 | 只扫描模块级 import 的脚本会漏掉它们 |
| **③ 按名动态补丁（参数化目标）** | `tests/conftest.py:129-222` `trace()`：`name = "record_deliverable_config_audit"`，随后 `setattr(db, name, recorder)`，并靠 `getattr(db, name, missing)` 判断是否存在 | 若拆分把该方法从 `DatabaseManager` 挪走，`recorder_present` 变 `False`，**测试不报错但跟踪链断裂**（断言读的是 `log`，会得到空记录） |

**范围内未查到"多行 `setattr(` 且目标在后续行"的形式**（脚本专门检查，结果为空）；
唯一接近的是 `tests/test_deliverable_form_analysis.py:342-348` 的多行 `monkeypatch.setattr(`，
但目标字符串在同一行内，不构成漏改风险。

### 5.2 其他高耦合事实

| # | 事实 | 影响 |
|---|---|---|
| 1 | `web/app.py` 回导 93 + 45 个名字（90 + 42 私有） | 任何"改 boot 模块内部符号"的任务都要同步 `web/app.py` 的两段别名，否则 `AttributeError` 在 import 期暴露 |
| 2 | 别名绑定是**值拷贝** | patch boot 模块不影响 `web.app` 里已绑定的同名引用（§1.3） |
| 3 | `project_status_updates.py` 与同名包并存，包胜出 | 垫片不可达（§1.2）；删除与否需 lead 决策 |
| 4 | 壳再导出 stdlib 名（`json`/`logging`/`datetime`/`Any` 等 14 + 9 个） | 契约上存在 `from services.X import json` 的可用性；范围内未查到这种调用，但收窄即"收窄已发布接口"（CONTRACTS.md 修订规则） |
| 5 | `connectors` ⇄ `sync_runner` 的延迟导入环 | 拆任一侧都要先处理 `sync_runner.py:945` |
| 6 | `create_production_registry` 是环的闭合点，同时是 7 个调用方入口与 patch 目标 | 不能随便搬 |
| 7 | `deliverable_analysis` 服务名 ≠ 模块名 | 按服务名找文件会找错（§2.6） |
| 8 | `aras_auth` 与 `tdc_auth` 的 `_LoginForm`/`_LoginFormParser`/`_RequestTrace` 三件套同形 | 潜在共享化机会，但属跨域契约变更 |

---

## 6. 拆分粒度建议（供 lead 裁决）

`deliverable_form_analysis/_impl.py` 2940 行，按 §2.1 的私有符号聚类，天然可分成 5 个内聚块
（对应 T3–T6 加一个"归因/逾期规则"块）。建议**不要**按行数均分，而按"是否共享同一组私有符号"分：

| 块 | 代表符号 | 建议归属 |
|---|---|---|
| 规范化/清洗（`_safe_text`、`_parse_date`、`_clean_value`、`_number`） | 被其余全部块使用 | 保留在 `_impl`（基础设施层） |
| 逾期规则 | `_OVERDUE_RULES`、`classify_overdue`、`_TDC_DWELL_REPORTS` | T6 之前的独立块 |
| 官方列合并 | `_merge_official_columns` 一族 | T4 |
| D5 归因 | `_enrich_data_model_dimensions` 一族 | T3 |
| 分区汇总 | `_section_*` 一族 | T5 |
| 视图/过滤/图表 | `_VIEW_FILTER_*`、`_chart_payload` | T6 |

---

## 7. 待主控裁决项

| # | 事项 | 证据 | 需要 lead 定的事 |
|---|---|---|---|
| 1 | `services/project_status_updates.py` 垫片是否删除 | 与同名包并存；实测包胜出，垫片不可达（§1.2） | 确认打包清单（`*.spec`）是否仍需要它；若不需要，删除应作为独立任务而非搭车拆分 |
| 2 | 壳的 96 + 20 个私有名是否算公开契约 | §1.1、§5.2#4 | 若算，拆分必须继续 re-export；若不算，需一次显式的"收窄"决策（CONTRACTS.md 只允许加宽） |
| 3 | 补测任务（G1–G8）的归属 | §4.3 | 作为独立任务先行，还是并入对应拆分任务的第一阶段 |
| 4 | `connectors` ⇄ `sync_runner` 环是否本轮消除 | §2.7 | 消除方式（抽 `SyncBindingContext` 到独立模块 vs 保留延迟导入并加注释锁定） |
| 5 | `web/app.py` 别名回导何时退役 | 93 + 45 名（§1.3） | 退役顺序与是否与路由拆分同步 |
| 6 | 表单分析拆成几块 | §6 | 5 块是否合适；`_impl` 是否最终退化为"基础设施 + 重导出" |
| 7 | `aras_auth` / `tdc_auth` 同形三件套是否共享 | §5.2#8 | 跨域共享属契约变更，需 lead 判定 |
| 8 | T10（发现）边界 | §2.5 | service 侧只做纯会话对象、web 侧注入，是否可接受 |
| 9 | `deliverable_analysis` 服务名与模块名不一致是否要修 | §2.6 | 改名属公开契约变更，建议只在文档/注释层澄清 |


### 主控裁决记录（2026-11-01）

1. 垫片 `services/project_status_updates.py` 本轮保留。`VSE-TDC-Probe.spec:55` 引用的是模块名 `services.project_status_updates`（解析到包），不是垫片文件本身；删除垫片另开独立任务，需先跑 Probe 打包验证。
2. 壳的 96 + 20 个私有名按**兼容契约**对待：拆分时继续 re-export；任何收窄需单独批准。
3. G1–G8 补测作为**独立前置任务**先行；对应拆分任务在其补测合入前不得派发。
4. `connectors` ⇄ `sync_runner` 环本轮保留延迟导入并加注释锁定；抽离 `SyncBindingContext` 另开任务。
5. `web/app.py` 别名回导在所有领域拆分完成后作为独立任务退役，不与路由拆分同批。
6. 表单分析按 §6 拆 5 块；`_impl` 最终退化为“基础设施 + 重导出”。
7. `aras_auth`/`tdc_auth` 不在本轮共享（跨域契约变更）；DSH-V2-15 落地后再评估。
8. T10（发现）边界接受：service 侧只做纯会话对象，web 侧注入。
9. `deliverable_analysis` 命名不一致只在文档/注释层澄清，不改名。

---

## 8. 本任务未移动生产代码（验证记录）

**改动范围**：仅新增本文件 `docs/refactor-v2/DSH_SERVICE_SPLIT_INVENTORY.md`。
未修改任何 `services/`、`web/`、`core/`、`plugins/`、`tests/` 文件；未执行任何 git 索引/HEAD 操作。

| 验证命令 | 结果 |
|---|---|
| `git rev-parse --short HEAD` | `1619141` |
| `git branch --show-current` | `dsh/v2-42` |
| `git diff --check` | 无输出，退出码 0 |
| `git status --porcelain` | 仅 `docs/refactor-v2/DSH_SERVICE_SPLIT_INVENTORY.md` |
| `python -m pytest tests/test_deliverable_form_analysis_golden.py tests/test_project_status_updates_golden.py tests/test_route_contract_snapshot.py -q` | `18 passed in 5.86s`（基线绿，说明本清单的"现有黄金测试"一节对应的是真实可运行的基线） |

---

## 附录 A：本文件数据的一键复核

```powershell
# 1) 行数（wc -l 等价）
python -c "print(open('services/deliverable_form_analysis/_impl.py','rb').read().count(b'\n'))"

# 2) 壳的再导出规模（136 / 96 / 14）
python -c "
src=open('services/deliverable_form_analysis/__init__.py',encoding='utf-8').read()
body=src.split('_impl import (',1)[1].split(')',1)[0]
n=[x.strip() for x in body.replace('\n',' ').split(',') if x.strip()]
print('total',len(n),'private',len([x for x in n if x.startswith('_')]))"

# 3) 同名模块与包并存 + 谁胜出
git ls-files -- services/project_status_updates services/project_status_updates.py
python -c "import services.project_status_updates as m;print(m.__file__)"

# 4) 循环依赖的两条边
Select-String -Path services/project_status_connectors.py -Pattern 'from services.project_status_sync_runner'
Select-String -Path services/project_status_sync_runner.py -Pattern 'from services.project_status_connectors'

# 5) form key 与 golden 覆盖的差集
python -c "
from services.deliverable_form_analysis import _impl as m
print('FORM_KEYS', sorted(m.FORM_KEYS))
print('ROLLUP', sorted(m.SECTION_ROLLUP_FORM_KEYS))"

# 6) patch 目标（rg 可用时）
rg -n "setattr\(\s*(ps_boot|crawler_boot|connectors)\." tests
```

## 附录 B：本文件涉及的符号来源一览

| 章节 | 数据来源（只读） |
|---|---|
| §1 | `services/deliverable_form_analysis/__init__.py`、`services/project_status_updates/__init__.py`、`services/project_status_updates.py`、`web/app.py:51,147`、`PROJECT_MAP.md`（Production module index） |
| §2 | `services/*.py` 六个领域全部文件、`web/app.py`、`web/crawler_boot.py`、`web/project_status_boot.py`；调用方统计见 §0 |
| §3 | `tests/golden/`（`form_analysis/`、`project_status_updates/`、`routes.json`、`glossary_baseline.json`）、`tests/test_deliverable_form_analysis_golden.py`、`tests/test_project_status_updates_golden.py`、`tests/test_route_contract_snapshot.py` |
| §4 | §2 + §3 + `tests/conftest.py`、`docs/refactor-v2/CONTRACTS.md`（C8 路由兼容、C1 服务字典） |
| §5 | §0 的 patch 扫描、`tests/conftest.py:129-222` |
