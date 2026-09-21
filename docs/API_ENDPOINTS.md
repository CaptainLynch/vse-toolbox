# VSE Toolbox Web API 端点清单

> 状态：Generated
> 读者：Developer、Agent（API 任务）
> 权威来源：`web/app.py`、`web/diagnostics.py`、`web/ewo_enrichment.py` 路由装饰器；参数行为以代码和测试为准
> 默认读取：按 API/UI 任务读取
> 由 `tools/generate_api_endpoints.py` 从上述路由模块 AST 解析自动生成，
> 生成时间：2026-09-20 17:28，共 91 个端点。
> 手工新增路由后请重跑该脚本刷新本清单。

通用约定：

- 写操作（POST/PATCH/PUT/DELETE）仅接受本机回环访问（loopback 校验）。
- 响应统一为 `{"ok": true, "data": ...}` 或 `{"ok": false, "error": {...}}`。
- 本清单只列路由与方法，参数契约以 `web/app.py`、`web/diagnostics.py` 对应处理函数与测试为准。

## Aras 交互查询

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| POST | `/api/aras/ewo/export` | `api_aras_ewo_export` |
| POST | `/api/aras/ewo/query` | `api_aras_ewo_query` |
| POST | `/api/aras/ncr/detail` | `api_aras_ncr_detail` |
| POST | `/api/aras/ncr/detail/download` | `api_aras_ncr_detail_download` |
| POST | `/api/aras/ncr/progress` | `api_aras_ncr_progress` |
| POST | `/api/aras/ncr/progress/download` | `api_aras_ncr_progress_download` |
| POST | `/api/aras/paa/crawl-all` | `api_aras_paa_crawl_all` |
| POST | `/api/aras/paa/export` | `api_aras_paa_export` |
| POST | `/api/aras/paa/query` | `api_aras_paa_query` |
| POST | `/api/aras/ewo/enrichment/jobs` | `ewo_enrichment_prepare` |
| POST | `/api/aras/ewo/enrichment/jobs/<job_id>/run` | `ewo_enrichment_run` |
| POST | `/api/aras/ewo/enrichment/jobs/<job_id>/status` | `ewo_enrichment_status` |
| POST | `/api/aras/ewo/enrichment/jobs/restore` | `ewo_enrichment_restore` |

## Excel 任务

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/excel-artifacts/<int:artifact_id>` | `api_excel_artifact_detail` |
| GET | `/api/excel-artifacts/<int:artifact_id>/download` | `api_excel_artifact_download` |
| GET | `/api/excel-artifacts/<int:artifact_id>/download-audit` | `api_excel_artifact_download_audit` |
| GET | `/api/excel-artifacts/retention-plan` | `api_excel_artifacts_retention_plan` |
| GET | `/api/excel-roots` | `api_excel_roots_list` |
| GET | `/api/excel-tasks` | `api_excel_tasks_list` |
| POST | `/api/excel-tasks` | `api_excel_tasks_create` |
| GET | `/api/excel-tasks/<int:task_id>` | `api_excel_task_detail` |
| GET | `/api/excel-tasks/<int:task_id>/artifacts` | `api_excel_task_artifacts` |
| GET | `/api/excel-tasks/<int:task_id>/runs` | `api_excel_task_runs` |
| POST | `/api/excel-worker/start` | `api_excel_worker_start` |
| GET | `/api/excel-worker/status` | `api_excel_worker_status` |
| POST | `/api/excel-worker/stop` | `api_excel_worker_stop` |

## TDC 交互查询

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| POST | `/api/tdc/a-face/crawl-all` | `api_tdc_a_face_crawl_all` |
| POST | `/api/tdc/a-face/export` | `api_tdc_a_face_export` |
| POST | `/api/tdc/a-face/query` | `api_tdc_a_face_query` |
| POST | `/api/tdc/data-model/crawl-all` | `api_tdc_data_model_crawl_all` |
| POST | `/api/tdc/data-model/export` | `api_tdc_data_model_export` |
| POST | `/api/tdc/data-model/query` | `api_tdc_data_model_query` |
| POST | `/api/tdc/sor/car-type-projects` | `api_tdc_sor_car_type_projects` |
| POST | `/api/tdc/sor/crawl-all` | `api_tdc_sor_crawl_all` |
| POST | `/api/tdc/sor/export` | `api_tdc_sor_export` |
| POST | `/api/tdc/sor/query` | `api_tdc_sor_query` |

## 交付物目录与统一状态

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/deliverables/catalog` | `api_deliverables_catalog` |

## 安全诊断录制

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/diagnostics` | `diagnostic_status` |
| GET | `/api/diagnostics/bundles/<identity>` | `diagnostic_download` |
| POST | `/api/diagnostics/events` | `diagnostic_events` |
| POST | `/api/diagnostics/mark` | `diagnostic_mark` |
| POST | `/api/diagnostics/start` | `diagnostic_start` |
| POST | `/api/diagnostics/stop` | `diagnostic_stop` |

## 定时归档任务

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/scheduled-archive/config-audit` | `api_scheduled_archive_config_audit` |
| GET | `/api/scheduled-archive/folders` | `api_scheduled_archive_folders` |
| POST | `/api/scheduled-archive/folders/native` | `api_scheduled_archive_native_folder` |
| GET | `/api/scheduled-archive/jobs` | `api_scheduled_archive_jobs` |
| POST | `/api/scheduled-archive/jobs` | `api_scheduled_archive_job_create` |
| DELETE | `/api/scheduled-archive/jobs/<job_key>` | `api_scheduled_archive_job_archive` |
| PATCH | `/api/scheduled-archive/jobs/<job_key>` | `api_scheduled_archive_job_update` |
| POST | `/api/scheduled-archive/jobs/<job_key>/sync-now` | `api_scheduled_archive_sync_now` |
| GET | `/api/scheduled-archive/runs` | `api_scheduled_archive_runs` |
| GET | `/api/scheduled-archive/runs/<int:run_id>/artifacts` | `api_scheduled_archive_artifacts` |

## 总览

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET/POST | `/api/overview` | `api_overview` |

## 系统设置

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/settings` | `api_settings_get` |
| PATCH | `/api/settings` | `api_settings_update` |
| POST | `/api/settings/domain-login` | `api_domain_login` |
| POST | `/api/settings/folders/native` | `api_settings_native_folder` |
| DELETE | `/api/settings/sessions` | `api_domain_sessions_clear` |

## 统一表单分析

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/deliverable-forms/<form_key>/rows` | `api_deliverable_form_rows` |
| GET | `/api/deliverable-forms/<form_key>/statistics` | `api_deliverable_form_statistics` |
| GET | `/api/deliverable-forms/<form_key>/view` | `api_deliverable_form_view` |

## 页面与其他

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET/POST | `/` | `index` |
| GET | `/api/tasks` | `api_tasks_list` |
| GET | `/api/tasks/<task_id>` | `api_tasks_get` |
| POST | `/api/tasks/<task_id>/cancel` | `api_tasks_cancel` |
| GET | `/api/tasks/<task_id>/download` | `api_tasks_download` |
| GET | `/api/tasks/<task_id>/result` | `api_tasks_result` |
| POST | `/api/tasks/<task_id>/retry` | `api_tasks_retry` |
| GET | `/api/version` | `api_version` |
| GET | `/favicon.ico` | `favicon` |

## 项目状态与交付物

| 方法 | 路径 | 处理函数 |
| --- | --- | --- |
| GET | `/api/project-status` | `api_project_status` |
| GET | `/api/project-status/analytics` | `api_project_status_analytics` |
| PATCH | `/api/project-status/deliverables/<deliverable_id>` | `api_project_status_deliverable_update` |
| GET | `/api/project-status/deliverables/<deliverable_id>/analysis` | `api_project_status_deliverable_analysis` |
| GET | `/api/project-status/deliverables/<deliverable_id>/analysis/items` | `api_project_status_deliverable_analysis_items` |
| GET | `/api/project-status/deliverables/<deliverable_id>/candidate-preview` | `api_project_status_candidate_preview` |
| GET | `/api/project-status/deliverables/<deliverable_id>/chart-labels` | `api_project_status_chart_labels` |
| PUT | `/api/project-status/deliverables/<deliverable_id>/chart-labels` | `api_project_status_chart_labels_write` |
| GET | `/api/project-status/deliverables/<deliverable_id>/debug-bundle` | `api_project_status_debug_bundle` |
| GET | `/api/project-status/deliverables/<deliverable_id>/mapping-discovery` | `api_project_status_mapping_discovery_history` |
| POST | `/api/project-status/deliverables/<deliverable_id>/mapping-discovery` | `api_project_status_mapping_discovery` |
| POST | `/api/project-status/deliverables/<deliverable_id>/sync-now` | `api_project_status_sync_now` |
| GET | `/api/project-status/deliverables/<deliverable_id>/unified-status` | `api_project_status_unified_status` |
| GET | `/api/project-status/deliverables/<deliverable_id>/update-policy` | `api_project_status_update_policy` |
| PATCH | `/api/project-status/deliverables/<deliverable_id>/update-policy` | `api_project_status_update_policy_write` |
| PATCH | `/api/project-status/phases/<phase_id>` | `api_project_status_phase_update` |
| PATCH | `/api/project-status/phases/<phase_id>/milestones` | `api_project_status_milestones_update` |
| GET | `/api/project-status/runs` | `api_project_status_runs` |
| GET | `/api/project-status/runs/<int:run_id>/artifacts` | `api_project_status_run_artifacts` |
| GET | `/api/project-status/updates` | `api_project_status_updates` |
