# 插件重构遗漏行为恢复（2026-10-02）

任务：在插件宿主架构下补回上一业务分支（`feature/scheduled-deliverables-overview-excel`，顶端
`e2c58a3`）已实现、但重构遗漏的行为。基线 = 最新 `origin/refactor/plugin-host`（`d0dd01d`），
工作分支 `claude/restore-plugin-parity`。不新增业务体系，不恢复 `web/static/app.js` / 旧全局样式。

## 恢复方法

- 旧 9 批业务修复（`20cbbd4`、`a1af029`、`66ce4c7`、`7314cf1`、`e255512`、`23ac8be`、`90372fd`、
  `ed914ee`、`4e59d71`）**不整条 merge / cherry-pick**；以 e2c58a3 的最终实现与测试为准，按当前模块
  归属迁入。
- 后端：重构未触碰的文件（`services/*`、`core/report_*`、`core/section_rollup.py` 等）取自参考顶端；
  `core/db_manager.py` 的 PAA 改名按现有 facade 手工应用；`services/deliverable_form_analysis.py`、
  `web/app.py` 三方合并（base = `d15d0f2`，保留重构的 `core/form_registry.py` 推导）。
- 前端：旧 `app.js` 补丁按插件责任重写进 `plugins/project_overview/static/deliverable/`
  （Preact 组件 + 纯逻辑模块），旧源码文本断言测试**不恢复**，改为行为 / API / 真浏览器测试。

## 条目表（A1–A16 + NCR 诊断）

状态：已恢复 = 旧最终行为已迁入并有行为断言；保留 = 现有实现已满足，仅补回归守护。

| 编号 | 状态 | 当前责任位置 | 行为断言（测试） |
|---|---|---|---|
| A1 NCR 查询范围 | 已恢复 | `services/project_status_connectors.py`（`_ncr_filters`/`_collect_ncr_rows`）、`services/aras_department_mapping.py`（`parse_ncr_section_codes_input`）、`web/app.py`（配置保存/探测与同步共用解析器）、插件向导 `policy-logic.js`（NCR 无部门字段） | `test_ncr_filters_never_sends_department_as_section_code`、`test_ncr_collect_rows_ignores_binding_department_keeps_section_code_narrowing`（合成 6 行保留 6 行）、`test_parse_ncr_section_codes_input_whitelist_and_prefix_paste`、浏览器 `test_wizard_ncr_has_section_scope_instead_of_department` |
| A2 SOR 行合同 | 已恢复 | `services/tdc_crawler.py`（`flatten_sor_rows`）、连接器 TDC collect、`core/report_contracts.py`（`startUser`） | `test_flatten_sor_rows_*`、`test_tdc_sor_collect_flattens_application_rows_and_keeps_raw_json`、`…produces_f6c_aggregated_analysis_rows`、`test_tdc_sor_applicant_maps_measured_production_key` |
| A3 范围剔除 | 已恢复 | `services/scope_exclusion.py`（同步与定时归档共用）、`project_status_connectors.py`、`scheduled_archive_connectors.py`；向导 SOR 状态筛选入口在 `policy.js` | `tests/test_scope_exclusion.py`（7）、`test_exclude_tdc_scope_rows_*`、`test_aras_paa_collect_excludes_cancel_rows_and_keeps_raw_json`、浏览器 `test_sor_wizard_end_to_end_with_status_filter_and_real_binding` |
| A4 完成口径 | 已恢复 | `project_status_deliverable_analysis.py`、`deliverable_form_analysis.py`（数模 `4`→完成、`2`→审批中，未映射码透传）、来源标签 | `tests/test_project_status_deliverable_analysis.py`（6 项新增）、`test_tdc_in_flight_status_code_two_shows_text_and_not_completed`、浏览器 `test_data_model_has_section_counts_tab_and_completion_caliber`（卡片与明细同口径） |
| A5 TDC 导出软失败 | 已恢复 | 连接器 TDC collect（列表完整、附属 XLSX 失败 → 保留可发布数据并记录归档失败） | `test_tdc_connector_collect_tolerates_archive_export_failure` |
| A6 TDC 网关恢复 | 已恢复 | `services/tdc_crawler.py`（502/503/504 有界重试、Retry-After、次数/总等待上限）、`web/app.py`（`_tdc_error_response` 网关提示）、`deliverable/api.js`（`retryable`） | `test_query_page_*`（重试/上限/不重试 500 与传输异常）、`test_retryable_upstream_status_states_retry_semantics`、浏览器 `test_wizard_gateway_failure_shows_server_wording_without_config_prefix` |
| A7 科室归集 | 已恢复 | `core/section_rollup.py`（规范化匹配、冲突校验、24 个历史别名种子、“结构工程科→车身科”仅更正仍等于旧默认的已存规则） | `tests/test_section_rollup.py`（7 项新增）、浏览器 `test_data_model_section_board_and_filter_use_the_rollup_target`（`BE 结构工程科` 归入车身科） |
| A8 数模归集 | 已恢复 | `deliverable_form_analysis.py`（`SECTION_ROLLUP_FORM_KEYS` 含数模、`sectionCounts`）、插件 `form-analysis.js`（「按科室」页签 + 计数板）、`form-state.js` | `test_tdc_data_model_joins_section_rollup_with_counts_only`、`…section_filter_matches_alias_rows`、浏览器同上（板与筛选同口径） |
| A9 NCR 科室成本表 | 已恢复 | `core/report_cost_values.py`（费用解析单源）、`deliverable_form_analysis.py`（`sectionCosts`）、插件 `SectionCostsTable` + `chart-math.js`（`sectionCostRows`） | `test_ncr_detail_section_costs_with_rollup_and_signed_values`、`tests/test_report_cost_values.py`、`test_core_cost_sum_matches_section_costs_aggregate`、浏览器 `test_ncr_detail_cost_table_shows_four_metrics_with_valued_counts`（空值≠0、负值、点击筛选） |
| A10 聚合备注 | 已恢复 | `services/project_status_records.py`（“共 N 条；状态计数”、NCR 明细附四项费用合计、确定性排序、超长保总数/计数）；连接器、ewo_v2 **与映射取证/候选预览**均传同一报表类型 | `tests/test_project_status_records.py`（12）、`test_candidate_preview_note_is_byte_identical_to_the_executed_aggregate_note`（SOR/数模/PAA/NCR 明细） |
| A11 取证截止/取消/去重/轻量核验 | 已恢复 | 前端 `deliverable/discovery.js`（TDC 90s / Aras 240s、协作取消）；后端 `web/app.py`（向导会话有界缓存 + 声明总数、取消令牌注册表）、`project_status_discovery.py`（`observe_stability_sample`、顺序无关身份哈希子集基线、不一致原因） | `test_f10_*`、`test_mapping_discovery_f9a_session_cache_deduplicates`、浏览器 `test_wizard_client_deadline_cancels_server_side_and_is_retryable`、`test_client_deadline_cancels_the_running_crawl_on_the_server`、`test_wizard_reports_specific_stability_mismatch` |
| A12 Aras 后台取证 | 已恢复 | `web/app.py`（202 + taskId/statusUrl/paramsHash、同参数重新挂接、协作取消、重启孤儿任务由启动自检置 interrupted）+ 插件 `discovery.js`（握手→轮询→读结果→哈希校验） | `test_mapping_discovery_async_*`、浏览器 `test_wizard_runs_first_discovery_as_background_task_then_stability_check`、`…reattaches_to_the_same_inflight_task_after_reload`、`…discards_background_result_with_foreign_params_hash`、`test_cancelling_the_background_task_ends_the_wizard_with_a_restart_hint`、`test_wizard_end_to_end_against_real_backend_task_contract`、`test_ncr_wizard_end_to_end_saves_section_scope_declaration`（两次独立导出） |
| A13 PAA 未知阶段披露 | 已恢复 | `deliverable_form_analysis.py`（去灰桶、`unrecognizedStageCount`）、插件 `UnrecognizedNote` | `test_paa_matrix_drops_other_status_bucket_and_reports_unrecognized`、`test_ncr_progress_and_ewo_keep_other_status_bucket`、浏览器 `test_paa_board_drops_other_bucket_and_discloses_unrecognized` |
| A14 表格展示 | 已恢复 | `deliverable_form_analysis.py`（`sourceAbsentIndexes`、数模默认可见 16 列含最新审批记录）、插件 `form-state.js`/`form-analysis.js`（缺字段提示、派生「状态」列、长文本截断 + title）、`deliverable.css`（行表改 `max-content` 宽度，避免其他列被挤成单字宽） | `test_view_payload_exposes_source_absent_indexes`、浏览器 `test_sor_columns_with_no_source_key_are_marked_absent_not_blank`、`test_data_model_rows_show_status_column_and_truncate_long_text`（单行高度、title、全字段明细仍有全值）。注：表单明细表没有用户列偏好存储，“已存列偏好”仅适用于系统查询网格（未改动，互通键不变） |
| A15 PAA 名称 | 已恢复 | `core/db_manager.py`（种子“PAA流程” + 存量旧默认名幂等更正，不改自定义名）、`core/project_status_contracts.py`、`web/app.py` 目录、`display.js` | `test_seed_paa_deliverable_display_name`、`test_seed_renames_legacy_paa_report_name`、浏览器 `test_paa_display_name_is_paa_liucheng` |
| A16 表单请求恢复 | 已恢复（+新发现并修复 Preact 缺陷） | `form-analysis.js`（`FORM_VIEW_LIMITS` 超时、`viewStatus` 单一真相解锁、过期响应丢弃、守卫拦截计数）、`multi-select.js` | 浏览器 `test_view_timeout_unlocks_interaction_and_offers_retry`、`test_failed_tab_reload_unlocks_and_shows_retryable_error`、`test_stale_response_never_overwrites_the_latest_view`、`test_stale_failure_does_not_unlock_while_newer_request_is_in_flight`、`test_old_request_settling_after_navigation_does_not_touch_the_new_view`、`test_pick_survives_option_refresh_between_mousedown_and_click`、`test_multi_select_keyboard_behaviour_and_draft_feedback` |
| NCR 错误诊断 | 已恢复 | `services/aras_crawler.py`（`ArasNcrExportContractError`、无泄漏结构签名）、`web/app.py`（专用错误码 + 中文说明，沿用脱敏管道） | `test_ncr_export_contract_failures_carry_signature_without_body`、`test_ncr_export_contract_error_maps_to_dedicated_code_and_chinese_message` |
| 保留项 | 保留 | 圆环居中、鼠标/键盘跳转、无有效同步值占位、向导进度/失败文字、筛选草稿/请求/显示分离 | 浏览器 `test_progress_rings_centre_navigate_by_mouse_and_keyboard`、向导状态类测试；另补：刷新期间保留已渲染环图卡 + 空态提示（`status/progress.js`） |

## 本轮真实浏览器 / 真实后端联调额外发现并修复的缺陷

以下是旧最终实现（e2c58a3）里就存在、旧的源码文本测试看不出来的接线缺陷；真浏览器 + 真后端联调才暴露：

1. **候选预览与执行不一致**：预览仍走历史“单号：卡点”明细，而连接器写入“共 N 条；状态计数”。
   现预览/ewo_v2 取证传同一报表类型（4 个旧测试固定了“双方都不传”的默认值，已改为对真实调用路径断言）。
2. **NCR 向导「科室」选择无法保存**：向导写 `matchRule.sectionScope`，绑定校验不接受列表值/该键（422）。
   现 D7/D8 接受有界、去重的 `sectionScope` 声明（不是查询键、不进签名、高级设置保存时保留）。
3. **取消端点实际不可用**：`mapping-discovery/cancel` 复用了要求 `base_url` 的上游查询校验，前端只发
   `cancelToken` → 一律 400，服务端抓取继续跑。现取消端点不要求 `base_url`（同步路径与任务路径均验证抓取被停止）。
4. **Preact 多选“点选后立即被撤销”**：选中候选会移除其按钮，所在 `<label>` 的默认动作把点击转给新 token 的
   “×”按钮，刚选的值被删掉（旧 DOM 版本不存在该机制）。现取消控件自有按钮点击的默认动作；变异验证：去掉修复两条
   行为测试均失败。
5. **缺失列判定把 `null` 当成第 0 列**（`Number(null)=0`）：已收紧输入过滤并有测试。

## 未恢复 / 未验证 / 需现场验收

- **未迁入**：旧分支 `AGENTS.md` 的顾问路由（Astra 试用）条款、`memory/`/`docs/PLAN_*` 过程文档与
  `tests/frontend_behavior_gate.cjs`/`app_dom_stub.cjs`/变异自检（针对已删除的 `app.js`，被真浏览器行为测试取代）；
  旧 `tools/verify_js_block_scope.py` 随 `app.js` 退役而删除。
- **Windows / Office / 内网**：Windows 打包、onedir 升级、Excel COM、公司内网真实 Aras/TDC 取证均未在云端验证；
  全量 pytest 仍有 4 个基线 Windows 专属用例失败（`test_agent_supervisor` relay、`test_excel_worker_process_controller`
  source command、`test_tdc_probe_standalone` ×2；与本轮改动无关，基线同样失败）。
- **需现场确认**：（1）NCR 官方导出在内网对科室代码白名单的实际表现（向导不发送 seccode）；（2）数模状态码 3/6
  含义仍未确定（原样透传）；（3）D8 费用合计在真实 NCR 明细上的数值对账；（4）真实 Aras 单次导出不可中断，
  取消最长在当前导出结束后生效（约 240s 内）。
- **历史快照**：SOR 行扁平化、PAA/NCR CLOSE 完成口径、范围剔除、聚合备注摘要、归集规则迁移只对此后同步生效；
  修复前已存快照/分析缓存**需重新同步一次**才会刷新（不迁移、不删除用户数据）。

## 验证记录

- 聚焦：后端/API/DB/归档测试随本批迁入（旧分支 9 个重点测试文件全部迁入并通过）；插件逻辑
  `tests/test_plugin_overview_parity_logic.py`；真浏览器 `tests/test_plugin_overview_browser.py`（Chromium，1400px 与 420px，
  断言无 pageerror / console error / 横向滚动）。
- 全量：`python -m pytest -q -n 4`；基线（`d0dd01d`）2504 passed / 4 failed（Windows 专属）；
  本分支 2704 passed / 4 failed（同 4 项）。
- `flake8`（改动的生产文件与新测试）零告警；`node --check` 覆盖所有插件模块（`test_node_check_passes`）；
  `python tools/generate_project_map.py --check` verified。
