# -*- coding: utf-8 -*-
"""
web/app.py — WEB 适配层：Flask 应用工厂 + /api/overview 路由

架构约束:
    - 唯一允许 import flask 的文件
    - 路由只做序列化与 HTTP 响应，不写业务 SQL
    - FLASK_HOST / FLASK_PORT 从 core.config 取值
    - service/core 层对 Flask 无感知
"""

import io
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import FLASK_HOST, FLASK_PORT
from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text
from services.aras_crawler import (
    ArasCrawlerClient,
    ArasCrawlerError,
    DEFAULT_PAA_SELECT_FIELDS,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)
from services.aras_department_mapping import normalize_departments, resolve_ncr_section_codes
from services.aras_export import export_ewo_report_csv, export_report_csv

logger = logging.getLogger("vse_toolbox.web")

_SENSITIVE_JSON_RE = re.compile(
    r"(?i)(['\"])(authorization|cookie|token|api_key|sid|sessionid|csrf|secret)\1(\s*:\s*)(['\"])(.*?)\4"
)
_SENSITIVE_PARAM_RE = re.compile(r"(?i)\b(token|api_key|sid|sessionid|csrf|secret)=([^&\s,;'\"}\])]+)")
_SENSITIVE_HEADER_RE = re.compile(
    r"(?i)\b(cookie|authorization)\b(\s*[:=]?\s*)(?:Bearer\s+)?([^,\s;'\"}\])]+)"
)
_SENSITIVE_BEARER_RE = re.compile(r"(?i)\bBearer\s+([^,\s;'\"}\])]+)")

_SENSITIVE_RESPONSE_KEYS = {
    "raw_xml",
    "file_id",
    "authorization",
    "set-cookie",
    "cookie",
    "token",
    "api_key",
    "sid",
    "sessionid",
    "arasauth",
    "jsessionid",
    "csrf",
    "secret",
    "password",
}

#: Aras routes 的默认主机 allowlist；仅允许 ecm.sgmw.com.cn。
#: localhost/测试 host 只能通过 create_app(allowed_hosts=...) 或
#: app.config["ARAS_ALLOWED_HOSTS"] 显式注入。
_DEFAULT_ARAS_ALLOWED_HOSTS: tuple[str, ...] = ("ecm.sgmw.com.cn",)

#: 全量 CSV 导出路由固定使用的边界（page_size 固定 2000，不可被请求覆盖）。
_EXPORT_PAGE_SIZE = 2000
_EXPORT_DEFAULT_MAX_PAGES = 1000
_EXPORT_DEFAULT_MAX_RECORDS = 10000

_INVALID_ATTACHMENT_CHARS_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


class _ArasRequestError(ValueError):
    """Aras 请求级校验失败（主机 allowlist / filter 语义），映射为 HTTP 400。"""

    def __init__(self, message: str, error_type: str = "ValidationError") -> None:
        super().__init__(message)
        self.error_type = error_type


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


def _sanitize_error_message(exc: Exception) -> str:
    return redact_sensitive_text(exc, limit=240, collapse_newlines=True)


def _json_error(status: int, error_type: str, message: str):
    return jsonify({"ok": False, "error": {"type": error_type, "message": message}}), status


def _safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    safe: list[dict[str, str | None]] = []
    for row in rows:
        clean: dict[str, str | None] = {}
        for key, value in row.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_RESPONSE_KEYS:
                continue
            clean[key_text] = None if value is None else redact_sensitive_text(value)
        safe.append(clean)
    return safe


def _safe_scalar(value: Any) -> str:
    return redact_sensitive_text(value)


def _request_payload() -> tuple[dict[str, Any] | None, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, _json_error(400, "ValidationError", "JSON object body is required")
    if not str(payload.get("base_url") or "").strip():
        return None, _json_error(400, "ValidationError", "base_url is required")
    return payload, None


def _clean_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str) and key.strip() and item.strip():
            clean[key.strip()] = item.strip()
    return clean


def _normalize_allowed_host(entry: str) -> tuple[str, int | None]:
    """规范化 allowlist 条目 'host' / 'host:port'（小写；无端口表示任意端口）。"""
    text = str(entry).strip().lower()
    if not text:
        raise _ArasRequestError("ARAS_ALLOWED_HOSTS contains an empty host", "HostNotAllowed")
    try:
        parsed = urlsplit("//" + text)
        port = parsed.port
    except ValueError:
        raise _ArasRequestError("ARAS_ALLOWED_HOSTS contains an invalid host", "HostNotAllowed") from None
    hostname = parsed.hostname or ""
    if not hostname:
        raise _ArasRequestError("ARAS_ALLOWED_HOSTS contains an invalid host", "HostNotAllowed")
    return hostname, port


def _validate_allowed_base_url(base_url: str, allowed_hosts: Sequence[str]) -> None:
    """构造 Aras client 前执行主机 allowlist（fail-closed，拒绝任意主机）。"""
    try:
        parsed = urlsplit(str(base_url or "").strip())
        port = parsed.port
    except ValueError:
        raise _ArasRequestError("base_url is not a valid URL", "HostNotAllowed") from None
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise _ArasRequestError("base_url must use http or https", "HostNotAllowed")
    if parsed.username is not None or parsed.password is not None:
        raise _ArasRequestError("base_url must not contain userinfo", "HostNotAllowed")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise _ArasRequestError("base_url must include a host", "HostNotAllowed")
    default_port = 443 if scheme == "https" else 80
    if port is None or port == default_port:
        port = None  # 规范化 scheme 默认端口
    for entry in allowed_hosts:
        allowed_host, allowed_port = _normalize_allowed_host(entry)
        if hostname == allowed_host and (allowed_port is None or allowed_port == port):
            return
    raise _ArasRequestError("base_url host is not allowed", "HostNotAllowed")


def _build_aras_client_from_payload(
    payload: dict[str, Any],
    allowed_hosts: Sequence[str] | None = None,
) -> ArasCrawlerClient:
    base_url = str(payload["base_url"]).strip()
    hosts = tuple(allowed_hosts) if allowed_hosts is not None else _DEFAULT_ARAS_ALLOWED_HOSTS
    _validate_allowed_base_url(base_url, hosts)
    headers = _clean_string_mapping(payload.get("headers"))
    cookie = payload.get("cookie")
    if isinstance(cookie, str) and cookie.strip():
        headers["Cookie"] = cookie.strip()
    cookies = _clean_string_mapping(payload.get("cookies")) or None
    return ArasCrawlerClient(
        base_url,
        headers=headers,
        cookies=cookies,
        timeout=30.0,
    )


def _filter_payload(payload: dict[str, Any]) -> dict[str, Any]:
    filters = payload.get("filters", {})
    return filters if isinstance(filters, dict) else {}


def _none_if_blank(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _department_names(value: Any) -> list[str]:
    """把 department 字段解析为显示名列表（字符串按逗号分隔；空值 → 不筛选）。"""
    if value is None:
        return []
    if isinstance(value, str):
        names = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        names = [str(item).strip() for item in value if str(item).strip()]
    else:
        raise _ArasRequestError("department must be a string or a list of strings")
    return names


def _paa_department_from_filters(filters: dict[str, Any]) -> str | None:
    """PAA department：空值不筛；非空归一化后必须唯一系统部门，未知/多部门 400。"""
    names = _department_names(filters.get("department"))
    if not names:
        return None
    try:
        resolved = tuple(dict.fromkeys(normalize_departments(names)))
    except ValueError as exc:
        raise _ArasRequestError(str(exc)) from None
    if len(resolved) != 1:
        raise _ArasRequestError("department must resolve to a single system department")
    return resolved[0]


def _ncr_section_codes_from_filters(filters: dict[str, Any]) -> tuple[str, ...]:
    """NCR 业务 department → NCR 科室代码（未知部门 400）；高级 section_code 仍可用。"""
    names = _department_names(filters.get("department"))
    if not names:
        return ()
    try:
        return resolve_ncr_section_codes(names)
    except ValueError as exc:
        raise _ArasRequestError(str(exc)) from None


def _ewo_filters_from_payload(payload: dict[str, Any]) -> EWOReportFilters:
    filters = _filter_payload(payload)
    return EWOReportFilters(
        ewo_no=_none_if_blank(filters.get("ewo_no")),
        project_code=_none_if_blank(filters.get("project_code")),
        subject_keyword=_none_if_blank(filters.get("subject_keyword")),
        change_type=_none_if_blank(filters.get("change_type")),
        change_sub_type=_none_if_blank(filters.get("change_sub_type")),
        area=_none_if_blank(filters.get("area")),
        state=_none_if_blank(filters.get("state")),
        rsp_department=_none_if_blank(filters.get("rsp_department")),
        submit_start=_none_if_blank(filters.get("submit_start")),
        submit_end=_none_if_blank(filters.get("submit_end")),
    )


def _paa_filters_from_payload(payload: dict[str, Any]) -> PAAReportFilters:
    filters = _filter_payload(payload)
    return PAAReportFilters(
        paa_no=_none_if_blank(filters.get("paa_no")),
        ewo_no=_none_if_blank(filters.get("ewo_no")),
        state=_none_if_blank(filters.get("state")),
        area=_none_if_blank(filters.get("area")),
        base=_none_if_blank(filters.get("base")),
        vehicle_keyword=_none_if_blank(filters.get("vehicle_keyword")),
        submit_start=_none_if_blank(filters.get("submit_start")),
        submit_end=_none_if_blank(filters.get("submit_end")),
        mtl_rq_start=_none_if_blank(filters.get("mtl_rq_start")),
        mtl_rq_end=_none_if_blank(filters.get("mtl_rq_end")),
        department=_paa_department_from_filters(filters),
    )


def _ncr_filters_from_payload(payload: dict[str, Any]) -> NCRApprovalFilters:
    filters = _filter_payload(payload)
    project_names = filters.get("project_names", ())
    if isinstance(project_names, str):
        projects = tuple(item.strip() for item in project_names.split(",") if item.strip())
    elif isinstance(project_names, list):
        projects = tuple(str(item).strip() for item in project_names if str(item).strip())
    else:
        projects = ()
    return NCRApprovalFilters(
        buy_start=_none_if_blank(filters.get("buy_start")),
        buy_end=_none_if_blank(filters.get("buy_end")),
        pe_start=_none_if_blank(filters.get("pe_start")),
        pe_end=_none_if_blank(filters.get("pe_end")),
        ncr_no=_none_if_blank(filters.get("ncr_no")),
        project_names=projects,
        section_code=_none_if_blank(filters.get("section_code")),
        section_codes=_ncr_section_codes_from_filters(filters),
        change_type=_none_if_blank(filters.get("change_type")),
        othercondition=str(filters.get("othercondition") or "0").strip() or "0",
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_attachment_basename(name: str, fallback: str = "ncr_detail") -> str:
    """服务端安全 basename（去路径与控制字符），用于 Content-Disposition。"""
    base = Path(str(name or "")).name
    base = _INVALID_ATTACHMENT_CHARS_RE.sub("_", base).strip(" .")
    return base or fallback


def _send_csv_attachment(
    path: Path,
    page: Any,
    max_pages: int,
    max_records: int,
    temp_dir: Path,
):
    """以 attachment 返回 CSV；可能截断时用 X-Export-* headers 明确告知。

    send_file 的响应是 direct_passthrough，其 call_on_close 不会随 WSGI
    app_iter 关闭触发（werkzeug 已知行为）；因此先把文件读入内存并立即删除
    临时目录（无句柄占用），再以 BytesIO 发送，临时文件生命周期不会外泄。
    """
    truncated = len(page.rows) >= max_records or (page.page is not None and page.page >= max_pages)
    data = path.read_bytes()
    shutil.rmtree(temp_dir, ignore_errors=True)
    response = send_file(
        io.BytesIO(data),
        mimetype="text/csv",
        as_attachment=True,
        download_name=path.name,
    )
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["X-Export-Complete"] = "false" if truncated else "true"
    response.headers["X-Export-Truncated"] = "true" if truncated else "false"
    response.headers["X-Export-Row-Count"] = str(len(page.rows))
    return response


def create_app(allowed_hosts: Sequence[str] | None = None) -> Flask:
    """Flask 应用工厂。

    `allowed_hosts` 覆盖 Aras 路由的主机 allowlist（默认仅 ecm.sgmw.com.cn）；
    localhost/测试 host 也可在创建后通过 app.config["ARAS_ALLOWED_HOSTS"] 注入。
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["ARAS_ALLOWED_HOSTS"] = (
        tuple(allowed_hosts) if allowed_hosts is not None else _DEFAULT_ARAS_ALLOWED_HOSTS
    )

    # DatabaseManager 实例化一次，init_database 只在启动时调用
    db = DatabaseManager()
    db.init_database()

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/api/overview")
    def api_overview():
        try:
            data = _query_overview(db)
            return jsonify(data)
        except Exception as e:
            logger.exception("api/overview 查询失败")
            return jsonify({"error": str(e)}), 500

    @app.post("/api/aras/ewo/query")
    def api_aras_ewo_query():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.query_ewo_report(
                _ewo_filters_from_payload(payload),
                page=_positive_int(payload.get("page"), 1),
                page_size=_positive_int(payload.get("page_size"), 50),
                max_records=_positive_int(payload.get("max_records"), 2000),
            )
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "rows": _safe_rows(result.rows),
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
                    },
                }
            )
        except _ArasRequestError as e:
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras EWO API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/paa/query")
    def api_aras_paa_query():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.query_paa_report(
                _paa_filters_from_payload(payload),
                page=_positive_int(payload.get("page"), 1),
                page_size=_positive_int(payload.get("page_size"), 50),
                max_records=_positive_int(payload.get("max_records"), 2000),
            )
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "rows": _safe_rows(result.rows),
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
                    },
                }
            )
        except _ArasRequestError as e:
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras PAA API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/paa/crawl-all")
    def api_aras_paa_crawl_all():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.crawl_paa_report_all(
                _paa_filters_from_payload(payload),
                page_size=_positive_int(payload.get("page_size"), 50),
                max_pages=_positive_int(payload.get("max_pages"), 20),
                max_records=_positive_int(payload.get("max_records"), 2000),
            )
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "rows": _safe_rows(result.rows),
                        "page": result.page,
                        "item_ids": result.item_ids,
                        "count": len(result.rows),
                    },
                }
            )
        except _ArasRequestError as e:
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras PAA crawl-all API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/ncr/progress")
    def api_aras_ncr_progress():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        try:
            result = _build_aras_client_from_payload(
                payload, app.config["ARAS_ALLOWED_HOSTS"]
            ).query_ncr_approval_progress(_ncr_filters_from_payload(payload))
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "file_name": _safe_scalar(result.file_name),
                        "record_id": _safe_scalar(result.record_id),
                    },
                }
            )
        except _ArasRequestError as e:
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras NCR progress API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/ncr/detail")
    def api_aras_ncr_detail():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        try:
            result = _build_aras_client_from_payload(
                payload, app.config["ARAS_ALLOWED_HOSTS"]
            ).extract_ncr_approval_detail(_ncr_filters_from_payload(payload))
            return jsonify({"ok": True, "data": {"file_name": _safe_scalar(result.file_name)}})
        except _ArasRequestError as e:
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras NCR detail API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/ewo/export")
    def api_aras_ewo_export():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_ewo_export_"))
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            max_pages = _positive_int(payload.get("max_pages"), _EXPORT_DEFAULT_MAX_PAGES)
            max_records = _positive_int(payload.get("max_records"), _EXPORT_DEFAULT_MAX_RECORDS)
            page = client.crawl_ewo_report_all(
                _ewo_filters_from_payload(payload),
                page_size=_EXPORT_PAGE_SIZE,
                max_pages=max_pages,
                max_records=max_records,
            )
            export = export_ewo_report_csv(page, output_dir=temp_dir)
            return _send_csv_attachment(export.path, page, max_pages, max_records, temp_dir)
        except _ArasRequestError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.warning("Aras EWO export API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/paa/export")
    def api_aras_paa_export():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_paa_export_"))
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            max_pages = _positive_int(payload.get("max_pages"), _EXPORT_DEFAULT_MAX_PAGES)
            max_records = _positive_int(payload.get("max_records"), _EXPORT_DEFAULT_MAX_RECORDS)
            page = client.crawl_paa_report_all(
                _paa_filters_from_payload(payload),
                page_size=_EXPORT_PAGE_SIZE,
                max_pages=max_pages,
                max_records=max_records,
            )
            export = export_report_csv(
                page.rows,
                output_dir=temp_dir,
                report_name="paa",
                preferred_fields=DEFAULT_PAA_SELECT_FIELDS,
            )
            return _send_csv_attachment(export.path, page, max_pages, max_records, temp_dir)
        except _ArasRequestError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.warning("Aras PAA export API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    @app.post("/api/aras/ncr/detail/download")
    def api_aras_ncr_detail_download():
        payload, error_response = _request_payload()
        if error_response:
            return error_response
        assert payload is not None
        temp_dir = Path(tempfile.mkdtemp(prefix="aras_ncr_detail_"))
        try:
            client = _build_aras_client_from_payload(payload, app.config["ARAS_ALLOWED_HOSTS"])
            result = client.extract_ncr_approval_detail(_ncr_filters_from_payload(payload))
            file_name = getattr(result, "file_name", None)
            if not isinstance(file_name, str) or not file_name.strip():
                shutil.rmtree(temp_dir, ignore_errors=True)
                return _json_error(502, "ArasCrawlerError", "NCR detail did not produce a file_name")
            saved = client.download_ncr_detail_file(file_name.strip(), temp_dir)
            data = saved.read_bytes()
            shutil.rmtree(temp_dir, ignore_errors=True)
            response = send_file(
                io.BytesIO(data),
                as_attachment=True,
                download_name=_safe_attachment_basename(file_name.strip()),
            )
            return response
        except _ArasRequestError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error(400, e.error_type, _sanitize_error_message(e))
        except ArasCrawlerError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.warning("Aras NCR detail download API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
