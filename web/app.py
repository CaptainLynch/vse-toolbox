# -*- coding: utf-8 -*-
"""
web/app.py — WEB 适配层：Flask 应用工厂 + /api/overview 路由

架构约束:
    - 唯一允许 import flask 的文件
    - 路由只做序列化与 HTTP 响应，不写业务 SQL
    - FLASK_HOST / FLASK_PORT 从 core.config 取值
    - service/core 层对 Flask 无感知
"""

import logging
import re
import sys
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import FLASK_HOST, FLASK_PORT
from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text
from services.aras_crawler import (
    ArasCrawlerClient,
    ArasCrawlerError,
    EWOReportFilters,
    NCRApprovalFilters,
    PAAReportFilters,
)

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


def _build_aras_client_from_payload(payload: dict[str, Any]) -> ArasCrawlerClient:
    headers = _clean_string_mapping(payload.get("headers"))
    cookie = payload.get("cookie")
    if isinstance(cookie, str) and cookie.strip():
        headers["Cookie"] = cookie.strip()
    cookies = _clean_string_mapping(payload.get("cookies")) or None
    return ArasCrawlerClient(
        str(payload["base_url"]).strip(),
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
        change_type=_none_if_blank(filters.get("change_type")),
        othercondition=str(filters.get("othercondition") or "0").strip() or "0",
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def create_app() -> Flask:
    """Flask 应用工厂。"""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
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
            client = _build_aras_client_from_payload(payload)
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
            client = _build_aras_client_from_payload(payload)
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
            client = _build_aras_client_from_payload(payload)
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
            result = _build_aras_client_from_payload(payload).query_ncr_approval_progress(
                _ncr_filters_from_payload(payload)
            )
            return jsonify(
                {
                    "ok": True,
                    "data": {
                        "file_name": _safe_scalar(result.file_name),
                        "record_id": _safe_scalar(result.record_id),
                    },
                }
            )
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
            result = _build_aras_client_from_payload(payload).extract_ncr_approval_detail(
                _ncr_filters_from_payload(payload)
            )
            return jsonify({"ok": True, "data": {"file_name": _safe_scalar(result.file_name)}})
        except ArasCrawlerError as e:
            return _json_error(502, "ArasCrawlerError", _sanitize_error_message(e))
        except Exception as e:
            logger.warning("Aras NCR detail API failed: %s", type(e).__name__)
            return _json_error(500, type(e).__name__, _sanitize_error_message(e))

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
