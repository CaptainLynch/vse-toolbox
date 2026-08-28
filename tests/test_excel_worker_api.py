from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.excel_tasks import ApprovedExcelRoots, ExcelTaskRepository
from core.excel_worker import ExcelWorkerRunSummary
from services.excel_worker_controller import ExcelWorkerController
from services.excel_worker_process_controller import ExcelWorkerProcessController


class FakeWorker:
    def run(self, *, stop_event: threading.Event) -> ExcelWorkerRunSummary:
        stop_event.wait(0.01)
        return ExcelWorkerRunSummary(0, 0, 0, 0)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = DatabaseManager(tmp_path / "worker_api.db")
    db.init_database()
    root = tmp_path / "excel"
    root.mkdir()
    repo = ExcelTaskRepository(db, ApprovedExcelRoots({"default": root}))
    controller = ExcelWorkerController(FakeWorker)
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(excel_repository=repo, excel_worker_controller=controller)
    app.config.update(TESTING=True)
    return app.test_client(), controller


def _headers() -> dict[str, str]:
    return {
        "Host": "localhost:5000",
        "Origin": "http://localhost:5000",
        "Sec-Fetch-Site": "same-origin",
    }


def test_worker_status_start_stop(client) -> None:
    http, controller = client
    assert http.get("/api/excel-worker/status").get_json()["data"]["state"] == "stopped"
    started = http.post("/api/excel-worker/start", headers=_headers(), environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert started.status_code == 200
    assert started.get_json()["data"]["state"] == "running"
    conflict = http.post("/api/excel-worker/start", headers=_headers(), environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert conflict.status_code == 409
    stopped = http.post("/api/excel-worker/stop", headers=_headers(), environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert stopped.status_code == 200
    assert stopped.get_json()["data"]["state"] == "stopped"
    assert controller.status().state == "stopped"


def test_worker_mutations_reject_non_loopback(client) -> None:
    http, _ = client
    response = http.post(
        "/api/excel-worker/start",
        headers=_headers(),
        environ_base={"REMOTE_ADDR": "192.168.1.10"},
    )
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"


def test_worker_unconfigured_returns_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = DatabaseManager(tmp_path / "unconfigured.db")
    db.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    client = web_app.create_app().test_client()
    response = client.get("/api/excel-worker/status")
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"


def test_worker_start_missing_packaged_worker_returns_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "dist" / "VSE-WebUI"
    bin_dir.mkdir(parents=True)
    webui_exe = bin_dir / "VSE-WebUI.exe"
    webui_exe.write_text("", encoding="ascii")
    web_dir = tmp_path / "web"
    (web_dir / "templates").mkdir(parents=True)
    (web_dir / "static").mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(webui_exe))

    db = DatabaseManager(tmp_path / "worker_api.db")
    db.init_database()
    root = tmp_path / "excel"
    root.mkdir()
    repo = ExcelTaskRepository(db, ApprovedExcelRoots({"default": root}))
    controller = ExcelWorkerProcessController(repo)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(excel_repository=repo, excel_worker_controller=controller)
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post(
        "/api/excel-worker/start",
        headers=_headers(),
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "Excel worker start failed",
        },
    }
    assert str(tmp_path) not in response.get_data(as_text=True)


def test_worker_start_directory_packaged_worker_returns_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "dist" / "VSE-WebUI"
    bin_dir.mkdir(parents=True)
    webui_exe = bin_dir / "VSE-WebUI.exe"
    webui_exe.write_text("", encoding="ascii")
    worker_dir_as_exe = bin_dir / "VSE-ExcelWorker.exe"
    worker_dir_as_exe.mkdir()
    web_dir = tmp_path / "web"
    (web_dir / "templates").mkdir(parents=True)
    (web_dir / "static").mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(webui_exe))

    db = DatabaseManager(tmp_path / "worker_api.db")
    db.init_database()
    root = tmp_path / "excel"
    root.mkdir()
    repo = ExcelTaskRepository(db, ApprovedExcelRoots({"default": root}))
    controller = ExcelWorkerProcessController(repo)

    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db)
    app = web_app.create_app(excel_repository=repo, excel_worker_controller=controller)
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.post(
        "/api/excel-worker/start",
        headers=_headers(),
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload == {
        "ok": False,
        "error": {
            "type": "ServerError",
            "message": "Excel worker start failed",
        },
    }
    assert str(tmp_path) not in response.get_data(as_text=True)
