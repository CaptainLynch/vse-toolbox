# -*- coding: utf-8 -*-
"""
web/app.py — WEB 适配层：Flask 应用工厂 + /api/overview 路由

架构约束:
    - 唯一允许 import flask 的文件
    - 路由只做序列化与 HTTP 响应，不写业务 SQL
    - FLASK_HOST / FLASK_PORT 从 core.config 取值
    - service/core 层对 Flask 无感知
"""

import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.domain_identity import (DPAPICredentialProvider, DomainSessionRegistry, WindowsDPAPICredentialVault)

#: 交付物同步凭据在 Windows 凭据管理器中的引用名（与统一域账号登录共享）。
SYNC_CREDENTIAL_REF = "domain"
from core.config import FLASK_HOST, FLASK_PORT
from core.runtime_paths import app_root
from core.section_rollup import SectionRollupStore
from core.archive_store import ArchiveStore
from core.settings_store import SettingsStore
from core.db_manager import DatabaseManager
from core.version import get_app_version_info
from core.excel_tasks import (ApprovedExcelRoots, ExcelTaskRepository, load_production_excel_roots)
from core.excel_worker import ExcelTaskWorker
from services.project_status_updates import ProjectStatusUpdateService
from services.project_status_discovery import MappingDiscoveryService
from services.project_status_analytics import ProjectStatusAnalyticsService
from services.project_status_deliverable_analysis import ProjectStatusDeliverableAnalysisService
from services.deliverable_form_analysis import DeliverableFormAnalysisService
from services.scheduled_archive_admin import ScheduledArchiveAdminService
from services.excel_task_admin import ExcelTaskAdminService
from services.excel_worker_controller import ExcelWorkerController
from services.excel_worker_process_controller import ExcelWorkerProcessController
from services.tdc_export_cache import TDCExportCache

from web.crawler_boot import (  # noqa: F401  W13-06/07/09 迁移别名
    CrawlerRouteDeps,
    _ArasRequestError,
    _CSV_FORMULA_PREFIXES,
    _DEFAULT_ARAS_ALLOWED_HOSTS,
    _DELIVERABLES_CATALOG,
    _DELIVERABLE_CATEGORIES,
    _EXPORT_DEFAULT_MAX_PAGES,
    _EXPORT_DEFAULT_MAX_RECORDS,
    _EXPORT_PAGE_SIZE,
    _INVALID_ATTACHMENT_CHARS_RE,
    _NCR_PREVIEW_MAX_ROWS,
    _SENSITIVE_RESPONSE_KEYS,
    _STATISTICS_MAX_HISTORY_ROWS,
    _STRICT_NUMBER_LITERAL,
    _TDCRequestError,
    _TDC_CSV_NAME_RE,
    _TDC_DATA_MODEL_FIELDS,
    _TDC_DATA_MODEL_FILTER_NAMES,
    _TDC_MAX_PAGES_MAX,
    _TDC_MAX_RECORDS_MAX,
    _TDC_MERGED_MAX_ROWS,
    _TDC_OFFICIAL_PREVIEW_MAX_ROWS,
    _TDC_PAGE_MAX,
    _TDC_PAGE_SIZE_MAX,
    _TDC_SOR_FIELDS,
    _TDC_SOR_FILTER_NAMES,
    _TDC_XLSX_NAME_RE,
    _aras_error_response,
    _aras_xml_payload,
    _aras_xml_requested,
    _async_session_gate,
    _build_aras_client_from_payload,
    _build_tdc_client_from_payload,
    _clean_string_mapping,
    _close_owned_tdc_client,
    _crawl_runner_from_request,
    _csv_cell,
    _department_names,
    _ewo_filters_from_payload,
    _filter_payload,
    _json_error,
    _local_web_mutation_error,
    _loopback_hostname,
    _mapping_result_is_complete,
    _ncr_filters_from_payload,
    _ncr_preview_requested,
    _ncr_section_codes_from_filters,
    _ncr_table_payload,
    _none_if_blank,
    _normalize_allowed_host,
    _origin_tuple,
    _paa_department_from_filters,
    _paa_filters_from_payload,
    _positive_int,
    _request_payload,
    _safe_attachment_basename,
    _safe_rows,
    _safe_scalar,
    _safe_tdc_sor_rows,
    _safe_tdc_sor_value,
    _sanitize_error_message,
    _save_aras_client_diagnostic,
    _save_web_diagnostic_report,
    _shared_domain_session,
    _submit_background_task,
    _tdc_crawl,
    _tdc_data_model_export_bytes,
    _tdc_data_model_filters,
    _tdc_data_model_serial_query,
    _tdc_document_no,
    _tdc_document_nos,
    _tdc_error_response,
    _tdc_export,
    _tdc_export_cache_context,
    _tdc_file_name,
    _tdc_filter_string,
    _tdc_filters_from_payload,
    _tdc_merged_file_name,
    _tdc_official_data_model_preview,
    _tdc_official_export_bytes,
    _tdc_official_preview,
    _tdc_official_rows_csv,
    _tdc_official_sor_preview,
    _tdc_positive_int,
    _tdc_preview_source,
    _tdc_query,
    _tdc_result_data,
    _tdc_sor_export_bytes,
    _tdc_sor_filters,
    _validate_allowed_base_url,
    _validate_tdc_base_url,
    logger,
    register_crawler_routes,
)

from web.project_status_boot import (  # noqa: F401  W13-09b 迁移别名
    DELIVERABLE_FORM_LINKS,
    ProjectStatusRouteDeps,
    _DISCOVERY_CANCEL_LOCK,
    _DISCOVERY_CANCEL_MAX_TOKENS,
    _DISCOVERY_CANCEL_TOKENS,
    _DISCOVERY_CANCEL_TOKEN_RE,
    _DISCOVERY_SERIAL_SET_MAX_BYTES,
    _DISCOVERY_SERIAL_SET_TOO_LONG_MESSAGE,
    _DISCOVERY_SESSION_CACHE,
    _DISCOVERY_SESSION_LOCK,
    _DISCOVERY_SESSION_MAX_ENTRIES,
    _DISCOVERY_SESSION_TTL_SECONDS,
    _MAPPING_DISCOVERY_RULE_FIELDS,
    _MAPPING_DISCOVERY_TASKS,
    _MAPPING_DISCOVERY_TASKS_LOCK,
    _MAPPING_DISCOVERY_TERMINAL_STATUSES,
    _PROJECT_STATUS_TONES,
    _PROJECT_STATUS_VALUES,
    _STABILITY_SAMPLE_MAX_PAGES,
    _STABILITY_SAMPLE_PAGE_SIZE,
    _WIZARD_SESSION_ID_RE,
    _analysis_query_values,
    _deliverable_analysis_link,
    _deliverable_associations,
    _deliverable_form_link,
    _get_discovery_session_cache,
    _get_discovery_session_cache_total,
    _mapping_discovery_accepted_response,
    _mapping_discovery_params_hash,
    _mapping_discovery_query_identity,
    _mapping_discovery_serial_set,
    _narrow_discovery_rows_by_sections,
    _pagination_diagnostic,
    _project_status_payload,
    _project_status_validation_error,
    _register_discovery_cancel,
    _release_discovery_cancel,
    _require_complete_mapping_result,
    _serial_identity_diagnostic,
    _set_discovery_session_cache,
    _stability_paged_sample,
    _validate_project_status_milestones,
    _validate_project_status_phase,
    _validate_project_status_update,
    register_project_status_routes,
)


# 映射取证的取消登记：前端 abort 之后服务端必须真的停下来，否则"可取消"只是表面
# 文章（顾问 2026-09-28 提醒），而且重复点击会叠加多个后台全量抓取。
# TDC 的分页抓取支持协作式停止（should_stop 在每个分页边界被探测）；
# Aras 的整本工作簿导出是**单次** SOAP 调用，没有取消钩子，登记对它只是尽力而为。


# F9a: 向导会话内映射取证去重与复用。
# 作用域限定在单一向导会话（wizardSessionId）与相同的上游查询参数组合，TTL 180s，最多 32 个。
# 仅用于向导内部候选重选、指定部门重试等中间交互，sync-now 绝不复用此缓存。
# 缓存连带保存首次抓取时的上游声明总数：候选重选等缓存命中路径再次落观测时，
# 必须沿用同源声明总数（F10 稳定性基线），不能用去重后行数充当——否则上游存在
# 重复行时，采样端的声明总数会与基线假性失配。

# G5（2026-09-30）映射取证后台化：同一交付物同一时刻只允许一个在途取证任务。
# 重复提交（相同参数哈希）返回原任务（向导重开后经 statusUrl 重新挂接）；
# 参数不同的在途任务期间再提交返回 409，避免新旧取证结果互相污染
# （与 C1 的「过期请求」问题同构，绑定的是查询身份而非请求时序）。


_SENSITIVE_JSON_RE = re.compile(
    r"(?i)(['\"])(authorization|cookie|token|api_key|sid|sessionid|csrf|secret)\1(\s*:\s*)(['\"])(.*?)\4"
)
_SENSITIVE_PARAM_RE = re.compile(r"(?i)\b(token|api_key|sid|sessionid|csrf|secret)=([^&\s,;'\"}\])]+)")
_SENSITIVE_HEADER_RE = re.compile(
    r"(?i)\b(cookie|authorization)\b(\s*[:=]?\s*)(?:Bearer\s+)?([^,\s;'\"}\])]+)"
)
_SENSITIVE_BEARER_RE = re.compile(r"(?i)\bBearer\s+([^,\s;'\"}\])]+)")


#: Aras routes 的默认主机 allowlist；仅允许 ecm.sgmw.com.cn。
#: localhost/测试 host 只能通过 create_app(allowed_hosts=...) 或
#: app.config["ARAS_ALLOWED_HOSTS"] 显式注入。

#: TDC routes 的默认主机 allowlist；仅允许 tdc.sgmw.com.cn。
#: 测试 host 只能通过 create_app(tdc_allowed_hosts=...) 或
#: app.config["TDC_ALLOWED_HOSTS"] 显式注入。
_DEFAULT_TDC_ALLOWED_HOSTS: tuple[str, ...] = ("tdc.sgmw.com.cn",)

#: 全量 CSV 导出路由固定使用的边界（page_size 固定 2000，不可被请求覆盖）。


_TDC_XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: 合并导出产物是 CSV：同一套安全校验换扩展名（见 `_tdc_merged_file_name`）。
#: 「导出合并结果」同样以官方工作簿为数据源：读取上限与官方预览一致（含表头行）。


def _query_overview(db: DatabaseManager) -> dict[str, Any]:
    """从 DatabaseManager 查询概览数据，返回 dict（供 jsonify 使用）。"""
    with db.get_connection() as conn:
        project_rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM projects GROUP BY status"
        ).fetchall()
        deliverable_rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM deliverables GROUP BY status"
        ).fetchall()
        feishu_total = conn.execute("SELECT COUNT(*) FROM feishu_tasks").fetchone()[0]
        feishu_synced = conn.execute(
            "SELECT COUNT(*) FROM feishu_tasks WHERE synced=1"
        ).fetchone()[0]

    return {
        "projects": {row["status"]: row["cnt"] for row in project_rows},
        "deliverables": {row["status"]: row["cnt"] for row in deliverable_rows},
        "feishu": {"total": feishu_total, "synced": feishu_synced},
    }


def _enforce_local_web_access():
    """Reject non-local or cross-site requests to prevent DNS rebinding and cross-site attacks."""
    if not _loopback_hostname(request.remote_addr):
        return _json_error(403, "LocalAccessRequired", "此操作仅允许从本机访问")
    try:
        host_url = urlsplit(f"//{request.host}")
        host_name = host_url.hostname
        host_port = host_url.port or (443 if request.scheme == "https" else 80)
    except ValueError:
        return _json_error(403, "LocalAccessRequired", "请求主机不受信任")
    if not _loopback_hostname(host_name):
        return _json_error(403, "LocalAccessRequired", "请求主机不受信任")

    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    if sec_fetch_site == "cross-site":
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return _json_error(403, "CrossSiteRequest", "拒绝跨站写操作")
        if request.path.startswith("/api/"):
            return _json_error(403, "CrossSiteRequest", "拒绝跨站请求")

    origin = request.headers.get("Origin")
    if origin is not None:
        expected = (
            request.scheme.lower(),
            str(host_name).rstrip(".").lower(),
            host_port,
        )
        if _origin_tuple(origin.strip()) != expected:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                return _json_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
            if request.path.startswith("/api/"):
                return _json_error(403, "CrossSiteRequest", "请求来源与本机服务不一致")
    return None


#: 单值扁平化别名（项目选项等展示场景沿用既有调用点）。


def _archive_history_limit(value: Any, default: int = 100) -> int:
    """Parse archive history limits strictly; invalid input is never defaulted."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("limit must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("limit must be a positive integer") from exc
    if parsed < 1:
        raise ValueError("limit must be a positive integer")
    return parsed


# 稳定性采样在「所选科室第 1 页无命中」时最多翻到的页数（含第 1 页）。
# 有界的原因：稳定性核验是**同步请求**（用户在向导里等着），每翻一页都是一次上游
# 往返；全量抓取（crawl_*_all）才允许跑后台任务。10 页 × 50 行 = 500 行的采样窗口
# 足以覆盖「所选科室的行不在上游默认排序前 50 行」的常见情形，翻不到则按
# inconclusive 如实报「未判定」，而不是无限翻页拖死请求。


#: 发现侧多单号集合的字节预算：与保存侧 ``match_rule`` 的 4000 字符上限取更严的一侧
#: （关注清单预算 12 KB 更宽）。两侧不一致就会出现「能发现不能存」。


#: CSV 公式注入缓解：危险前导字符（Excel 会当公式执行）。
#: 严格数字字面量豁免：`-12.5` 这类文本必须保持数值语义，不能加 `'` 前缀。


#: 交付物 ↔ 统一表单分析 form_key 的后端单一映射（从
#: core.project_status_contracts.DELIVERABLE_LINK_REGISTRY 派生，仅保留
#: deliverable_id 非 None 的条目，deliverable_id → form_key）。payload 通过
#: formLink 下发给前端，前端不再各自维护该映射。


#: 历史快照装载的每请求累计行数上限。30 份历史快照 × 每份最多 20000 行的
#: 全量解码上界过大：按快照从新到旧装载，累计行数达到该上限即停止装载
#: 剩余历史（最新快照行不受影响；单份快照内部行数上限维持 db 层现状）。


#: 后台任务结果 JSON 工件的大小上限（与同步响应体量级一致的安全上限）。
_TASK_RESULT_MAX_BYTES = 64 * 1024 * 1024


def create_app(
    allowed_hosts: Sequence[str] | None = None,
    tdc_allowed_hosts: Sequence[str] | None = None,
    excel_roots: Mapping[str, Path | str] | None = None,
    excel_repository: ExcelTaskRepository | None = None,
    excel_worker_controller: ExcelWorkerController | ExcelWorkerProcessController | None = None,
    excel_worker_mode: str = "process",
    excel_clock: Callable[[], datetime] | None = None,
    project_status_clock: Callable[[], date] | None = None,
    archive_store: ArchiveStore | None = None,
    plugin_dirs: Sequence[Path] | None = None,
    plugin_only: Sequence[str] | None = None,
    boot_token: str | None = None,
) -> Flask:
    """Flask 应用工厂。

    `allowed_hosts` 覆盖 Aras 路由的主机 allowlist（默认仅 ecm.sgmw.com.cn）；
    `tdc_allowed_hosts` 覆盖 TDC 路由的主机 allowlist（默认仅 tdc.sgmw.com.cn）；
    localhost/测试 host 也可在创建后通过对应 app.config 键注入。
    `plugin_dirs` 覆盖插件搜索目录（默认源码 `plugins/`、冻结包 exe 同级 `plugins/`）；
    `plugin_only` 只加载指定 id 的插件（单插件沙箱）。
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(str(getattr(sys, "_MEIPASS"))) / "web"
    else:
        base_dir = Path(__file__).resolve().parent

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["ARAS_ALLOWED_HOSTS"] = (
        tuple(allowed_hosts) if allowed_hosts is not None else _DEFAULT_ARAS_ALLOWED_HOSTS
    )
    app.config["TDC_ALLOWED_HOSTS"] = (
        tuple(tdc_allowed_hosts) if tdc_allowed_hosts is not None else _DEFAULT_TDC_ALLOWED_HOSTS
    )

    version_info = get_app_version_info()
    app.config["APP_VERSION_INFO"] = version_info
    app.config["APP_VERSION"] = version_info.get("displayVersion", "开发工作区")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    app.before_request(_enforce_local_web_access)

    # C7 本机安全（W16-03）：启动交换票据 + 会话 Cookie + 写操作四件套。
    # 注册顺序在 loopback/Host 守卫之后：读请求行为不变，写请求需会话+Origin。
    from web.security import install_local_security

    install_local_security(app, boot_token=boot_token)

    @app.after_request
    def _plugin_static_revalidate(response):  # type: ignore[no-untyped-def]
        """插件静态资源走协商缓存（ETag/304），避免「代码改了界面没变」。

        插件前端是原生 ES module：子模块 import 不带版本号，浏览器一旦留下旧副本
        且没有 revalidate 提示，页面就会一直显示旧控件。这里约束插件静态目录和宿主外壳（/static/host/，同为 ES module），
        API 响应仍由各路由的 ``no-store`` 负责。
        """
        if request.path.startswith(("/plugins/", "/static/host/")) and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.errorhandler(413)
    @app.errorhandler(RequestEntityTooLarge)
    def _request_entity_too_large(error=None):
        return _json_error(413, "PayloadTooLarge", "请求体超过大小限制 (最大 16MB)")

    # DatabaseManager 实例化一次，init_database 只在启动时调用
    db = DatabaseManager()
    db.init_database()
    update_service = ProjectStatusUpdateService(db)
    discovery_service = MappingDiscoveryService(db)
    analytics_service = ProjectStatusAnalyticsService(db)
    deliverable_analysis_service = ProjectStatusDeliverableAnalysisService(
        db,
        clock=project_status_clock,
    )
    deliverable_form_service = DeliverableFormAnalysisService(db)
    section_rollup_store = SectionRollupStore(db)
    app.extensions["deliverable_analysis"] = deliverable_analysis_service


    settings_store = SettingsStore(db)
    domain_sessions = DomainSessionRegistry()
    credential_vault = WindowsDPAPICredentialVault(app_root() / "data" / "domain-credential.dpapi")
    tdc_export_cache = TDCExportCache()
    archive_admin_service = (
        ScheduledArchiveAdminService(db, archive_store=archive_store)
        if archive_store is not None
        else ScheduledArchiveAdminService(db)
    )
    archive_admin_service.set_credential_provider(DPAPICredentialProvider(credential_vault))
    app.extensions["scheduled_archive_admin"] = archive_admin_service
    app.extensions["settings_store"] = settings_store
    app.extensions["domain_sessions"] = domain_sessions
    from core.ewo_export_jobs import EWOExportJobs
    from services.ewo_enrichment import EWOEnrichment
    from web.ewo_enrichment import register_ewo_enrichment

    ewo_enrichment = EWOEnrichment(
        EWOExportJobs(db.db_path), Path(db.db_path).parent / 'ewo-downloads'
    )
    app.extensions["ewo_enrichment"] = ewo_enrichment
    register_ewo_enrichment(app, ewo_enrichment, domain_sessions, _local_web_mutation_error)

    from services.crawl_task_runner import CrawlTaskRunner, prune_old_artifacts
    crawl_downloads_dir = Path(db.db_path).parent / "downloads"
    crawl_task_runner = CrawlTaskRunner(db, downloads_dir=crawl_downloads_dir)
    swept_tasks = crawl_task_runner.startup_sweep()
    if swept_tasks > 0:
        logger.info("Crawl tasks startup sweep: %d orphan tasks marked interrupted", swept_tasks)
    pruned_artifacts = prune_old_artifacts(crawl_downloads_dir)
    if pruned_artifacts > 0:
        logger.info("Startup artifact pruning: %d expired files removed", pruned_artifacts)
    app.extensions["crawl_task_runner"] = crawl_task_runner
    app.extensions["domain_credential_vault"] = credential_vault
    app.extensions["tdc_export_cache"] = tdc_export_cache
    app.extensions["deliverable_form_analysis"] = deliverable_form_service
    if excel_roots is not None and excel_repository is not None:
        raise ValueError("provide excel_roots or excel_repository, not both")
    if excel_repository is None and excel_roots is not None:
        excel_repository = ExcelTaskRepository(db, ApprovedExcelRoots(excel_roots))
    excel_admin_service = (
        ExcelTaskAdminService(excel_repository, clock=excel_clock)
        if excel_repository is not None
        else None
    )
    app.extensions["excel_task_admin"] = excel_admin_service
    if excel_worker_controller is None and excel_repository is not None:
        if excel_worker_mode == "process":
            excel_worker_controller = ExcelWorkerProcessController(excel_repository)
        elif excel_worker_mode == "in_process":
            excel_worker_controller = ExcelWorkerController(lambda: ExcelTaskWorker(excel_repository))
        else:
            raise ValueError("excel_worker_mode must be 'process' or 'in_process'")
    app.extensions["excel_worker_controller"] = excel_worker_controller

    @app.route("/")
    def index():
        return render_template(
            "dashboard.html",
            app_version=app.config.get("APP_VERSION", "开发工作区"),
        )

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    # 版本与设置路由已迁入 web/host_boot.py（W13-02，路径/endpoint/信封不变）；
    # 注册放在设置服务就绪之后（见下方 register_host_service_routes 调用）。

    @app.route("/api/overview")
    def api_overview():
        try:
            data = _query_overview(db)
            return jsonify(data)
        except Exception as e:
            logger.exception("api/overview 查询失败")
            return jsonify({"error": str(e)}), 500

    # Excel 领域路由已迁入 web/excel_boot.py（W13-04，路径/endpoint/信封不变）。
    from web.excel_boot import ExcelRouteDeps, register_excel_routes

    register_excel_routes(
        app,
        ExcelRouteDeps(
            excel_admin_service=excel_admin_service,
            excel_worker_controller=excel_worker_controller,
            local_mutation_error=_local_web_mutation_error,
            json_error=_json_error,
            validation_error=_project_status_validation_error,
            safe_attachment_basename=_safe_attachment_basename,
        ),
    )

    # ── 统一任务中心门面与工件下载 (Unified Task Center API Facade) ──────────
    # 实现已迁入 web/tasks_boot.py（W13-03）；_CRAWL_TASK_TYPE_LABELS 随迁。

    # 任务中心统一路由已迁入 web/tasks_boot.py（W13-03，路径/endpoint/信封不变）。
    from web.tasks_boot import TasksRouteDeps, register_tasks_routes

    register_tasks_routes(
        app,
        TasksRouteDeps(
            db=db,
            crawl_task_runner=crawl_task_runner,
            excel_admin_service=excel_admin_service,
            excel_repository=excel_repository,
            local_mutation_error=_local_web_mutation_error,
            json_error=_json_error,
            safe_attachment_basename=_safe_attachment_basename,
        ),
    )

    # 设置路由已迁入 web/host_boot.py（W13-02）：settings 读改、本机选目录、
    # 统一域账号登录、会话清除。此处只做依赖注入。
    from web.host_boot import HostRouteDeps, register_host_service_routes

    host_deps = HostRouteDeps(
        settings_store=settings_store,
        domain_sessions=domain_sessions,
        credential_vault=credential_vault,
        excel_admin_service=excel_admin_service,
        tdc_export_cache=tdc_export_cache,
        local_mutation_error=_local_web_mutation_error,
        json_ok=_json_ok,
        json_error=_json_error,
        sanitize_error_message=_sanitize_error_message,
        validation_error=_project_status_validation_error,
    )
    register_host_service_routes(app, host_deps)

    # Aras 路由已迁入 web/crawler_boot.py（W13-06，路径/endpoint/信封不变）；
    # TDC 路由 W13-07 复用同一门面模块。
    from web.crawler_boot import (
        CrawlerRouteDeps,
        register_crawler_routes,
        register_form_catalog_routes,
        register_tdc_routes,
    )

    crawler_deps = CrawlerRouteDeps(
        db=db,
        crawl_task_runner=crawl_task_runner,
        domain_sessions=domain_sessions,
        tdc_export_cache=tdc_export_cache,
        excel_admin_service=excel_admin_service,
        sanitize_error_message=_sanitize_error_message,
        local_mutation_error=_local_web_mutation_error,
        json_ok=_json_ok,
        json_error=_json_error,
        deliverable_form_service=deliverable_form_service,
        section_rollup_store=section_rollup_store,
    )
    register_crawler_routes(app, crawler_deps)

    # TDC 报表路由（W13-07）与交付物表单/目录路由（W13-08）复用同一门面接线；
    # 路径/endpoint/信封不变。
    register_tdc_routes(app, crawler_deps)
    register_form_catalog_routes(app, crawler_deps)

    # 原件留存路由已迁入 web/archive_boot.py（W13-05，路径/endpoint/信封不变）。
    from web.archive_boot import ArchiveRouteDeps, register_archive_routes

    register_archive_routes(
        app,
        ArchiveRouteDeps(
            db=db,
            archive_admin_service=archive_admin_service,
            excel_admin_service=excel_admin_service,
            sanitize_error_message=_sanitize_error_message,
            local_mutation_error=_local_web_mutation_error,
            json_ok=_json_ok,
            json_error=_json_error,
            validation_error=_project_status_validation_error,
        ),
    )


    from web.project_status_boot import ProjectStatusRouteDeps, register_project_status_routes

    # 项目状态领域路由（W13-09b，路径/endpoint/信封不变）。必须在旧路由全部
    # 注册之后、插件加载之前完成注册。
    register_project_status_routes(
        app,
        ProjectStatusRouteDeps(
            db=db,
            analytics_service=analytics_service,
            archive_admin_service=archive_admin_service,
            deliverable_analysis_service=deliverable_analysis_service,
            discovery_service=discovery_service,
            project_status_clock=project_status_clock,
            section_rollup_store=section_rollup_store,
            update_service=update_service,
        ),
    )

    from web.diagnostics import install_diagnostics
    install_diagnostics(app, local_guard=_local_web_mutation_error)
    _install_plugin_host(app, db, plugin_dirs=plugin_dirs, plugin_only=plugin_only, host_deps=host_deps)
    return app


def _json_ok(data: Any = None, status: int = 200):
    response = jsonify({"ok": True, "data": data})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _install_plugin_host(
    app: Flask,
    db: DatabaseManager,
    *,
    plugin_dirs: Sequence[Path] | None,
    plugin_only: Sequence[str] | None,
    host_deps: Any = None,
) -> None:
    """加载 `plugins/` 下的功能插件；旧路由全部注册完成后再加载，插件不能覆盖它们。"""
    import mimetypes
    from types import MappingProxyType

    from host import HostContext, PluginRegistry

    # Windows 注册表可能把 .js 映射成 text/plain，浏览器会拒绝执行 ES Module。
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")

    if plugin_only is None:
        env_only = os.environ.get("VSE_TOOLBOX_PLUGIN_ONLY", "").strip()
        plugin_only = [item.strip() for item in env_only.split(",") if item.strip()] or None
    context = HostContext(
        db=db,
        data_dir=Path(db.db_path).parent,
        json_ok=_json_ok,
        json_error=_json_error,
        local_guard=_local_web_mutation_error,
        services=MappingProxyType(app.extensions),
    )
    from host.updates import PluginUpdates

    updates = PluginUpdates(context.data_dir / "plugin-updates")
    try:
        applied = updates.apply_pending()
    except OSError:
        logger.exception("applying staged plugin packages failed")
        applied = []
    for item in applied:
        logger.info("Plugin package %s %s activated", item["id"], item["version"])
    registry = PluginRegistry(plugin_dirs, only=plugin_only, overrides=updates.active_dirs())
    registry.load_all(app, context)
    for plugin_id, bundled_version in registry.superseded.items():
        logger.info("Plugin %s: bundled %s supersedes installed package", plugin_id, bundled_version)
        updates.supersede(plugin_id, bundled_version=bundled_version)
    # 已安装的新版本启动失败：切回上一版本（或随包内置版本）并当场重新加载。
    for record in list(registry.records):
        if record.source != "installed" or record.status == "loaded" or record.id is None:
            continue
        previous = updates.rollback(record.id, reason=record.error or record.status)
        fallback = updates.active_dirs().get(record.id) if previous else registry.bundled_dirs.get(record.id)
        logger.warning("Plugin %s rolled back to %s", record.id, previous or "bundled")
        if fallback is not None:
            registry.load_dir(app, context, fallback, source="installed" if previous else "bundled")
    app.extensions["plugin_registry"] = registry
    app.extensions["plugin_updates"] = updates

    @app.get("/api/host/manifest")
    def api_host_manifest():
        return _json_ok(registry.manifest_payload())

    def _updates_payload() -> dict[str, Any]:
        payload = updates.status()
        payload["plugins"] = [
            {
                "id": r.id,
                "name": r.manifest.name if r.manifest else r.path.name,
                "version": r.manifest.version if r.manifest else None,
                "status": r.status,
                "source": r.source,
            }
            for r in registry.records
        ]
        return payload

    @app.get("/api/host/updates")
    def api_host_updates():
        return _json_ok(_updates_payload())

    # 宿主更新路由已迁入 web/host_boot.py（W13-02，路径/endpoint/信封不变）；
    # updates/registry/_updates_payload 仍由本函数装配。
    from web.host_boot import register_host_update_routes

    if host_deps is not None:
        register_host_update_routes(
            app,
            updates=updates,
            registry=registry,
            updates_payload=_updates_payload,
            deps=host_deps,
        )


if __name__ == "__main__":
    excel_roots = load_production_excel_roots()
    app = create_app(excel_roots=excel_roots)
    raw_port = os.environ.get("VSE_TOOLBOX_PORT", "").strip()
    try:
        selected_port = int(raw_port) if raw_port else FLASK_PORT
    except ValueError:
        selected_port = FLASK_PORT
    if not 1 <= selected_port <= 65535:
        selected_port = FLASK_PORT
    if "--diagnostics" in sys.argv:
        try:
            app.extensions["diagnostic_recorder"].start()
        except Exception:
            print("诊断录制未能开启，请在页面诊断控件中检查状态。")
    app.run(host=FLASK_HOST, port=selected_port, debug=False, use_reloader=False)
