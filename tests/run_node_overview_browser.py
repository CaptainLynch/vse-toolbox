"""Opt-in browser smoke with an isolated SQLite DB and only local status routes."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from datetime import date

from flask import request
from werkzeug.serving import make_server
import web.app as web_app
from core.db_manager import DatabaseManager


def main():
    with tempfile.TemporaryDirectory() as directory:
        db = DatabaseManager(Path(directory) / "smoke.db")
        db.init_database()
        phase = db.get_project_status("VPI-T2")[0]
        db.replace_project_status_milestones("VPI-T2", [
            dict(id=None, name="第一评审", date="2026-08-10", status="进行中", type="current", sort_order=1),
            dict(id=None, name="第二评审", date="2026-08-15", status="未开始", type="planned", sort_order=2),
        ], str(phase["updated_at"]))
        original = web_app.DatabaseManager
        web_app.DatabaseManager = lambda: db
        try:
            app = web_app.create_app(project_status_clock=lambda: date(2026, 8, 20))
        finally:
            web_app.DatabaseManager = original

        @app.before_request
        def isolate():
            if not (request.path == "/" or request.path.startswith("/static/")
                    or request.path == "/api/project-status"
                    or request.path == "/api/project-status/phases/VPI-T2/milestones"):
                return {"ok": False, "error": "disabled in isolated browser smoke"}, 404

        server = make_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = dict(os.environ, NODE_OVERVIEW_URL=f"http://127.0.0.1:{server.server_port}")
            return subprocess.run(["node", "tests/node_overview_browser.cjs"], env=env).returncode
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    raise SystemExit(main())
