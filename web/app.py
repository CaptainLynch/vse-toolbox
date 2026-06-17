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
from typing import Any

from flask import Flask, jsonify, render_template

from core.config import FLASK_HOST, FLASK_PORT
from core.db_manager import DatabaseManager

logger = logging.getLogger("vse_toolbox.web")


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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
