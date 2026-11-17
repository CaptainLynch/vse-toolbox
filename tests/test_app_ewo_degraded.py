"""EWO 导出子系统降级：迁移失败不得让整个 WebUI 启动失败。"""
import contextlib
import os
import unittest.mock as mock

import web.app as web_app
from core import ewo_export_jobs
from core.db_manager import DatabaseManager


@contextlib.contextmanager
def _isolated_app(monkeypatch, tmp_path):
    orig_db = web_app.DatabaseManager
    web_app.DatabaseManager = lambda: DatabaseManager(db_path=tmp_path / "degraded.db")
    try:
        with (
            mock.patch.object(web_app, "app_root", lambda: tmp_path, create=True),
            mock.patch("core.runtime_paths.app_root", lambda: tmp_path),
            mock.patch.dict(os.environ, {"VSE_TOOLBOX_PLUGIN_ONLY": ""}),
        ):
            yield web_app.create_app()
    finally:
        web_app.DatabaseManager = orig_db


def test_migration_failure_disables_only_the_export_subsystem(monkeypatch, tmp_path):
    def boom(self, path):
        raise ewo_export_jobs.ExportJobConflict("duplicate active rows block migration")

    monkeypatch.setattr(ewo_export_jobs.EWOExportJobs, "__init__", boom)
    app = _isolated_app(monkeypatch, tmp_path).__enter__()
    try:
        assert "EWO_EXPORT_DISABLED" in app.config
        assert "ExportJobConflict" in app.config["EWO_EXPORT_DISABLED"]
        # 增强导表未注册：路由不存在（而不是启动崩溃）。
        assert "ewo_enrichment" not in app.extensions
        client = app.test_client()
        response = client.post("/api/aras/ewo/enrichment/jobs", json={})
        assert response.status_code == 404
        # 其他功能仍然可用（任务中心能正常返回，内部对 ewo 库的失败有兜底）。
        assert client.get("/api/tasks").status_code == 200
    finally:
        app = None


def test_healthy_migration_registers_enrichment(monkeypatch, tmp_path):
    app = _isolated_app(monkeypatch, tmp_path).__enter__()
    try:
        assert "EWO_EXPORT_DISABLED" not in app.config
        assert "ewo_enrichment" in app.extensions
    finally:
        app = None
