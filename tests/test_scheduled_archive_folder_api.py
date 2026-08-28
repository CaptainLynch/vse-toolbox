from __future__ import annotations

from pathlib import Path

import pytest

import web.app as web_app
from core.archive_store import ArchiveStore
from core.db_manager import DatabaseManager
from services.scheduled_archive_admin import ScheduledArchiveAdminService


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    database = DatabaseManager(tmp_path / "folders.db")
    database.init_database()
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: database)
    root = tmp_path / "archive"
    (root / "Aras" / "EWO" / "2026").mkdir(parents=True)
    (root / "TDC").mkdir()
    store = ArchiveStore({"default": root}, reserve_bytes=0)
    app = web_app.create_app(archive_store=store)
    app.config.update(TESTING=True)
    return app.test_client()


def test_folder_api_lists_relative_directories_without_absolute_paths(client) -> None:
    response = client.get("/api/scheduled-archive/folders")
    assert response.status_code == 200
    body = response.get_json()
    assert body["data"] == {
        "current": "",
        "parent": "",
        "folders": [
            {"name": "Aras", "relativePath": "Aras"},
            {"name": "TDC", "relativePath": "TDC"},
        ],
    }
    assert "archive" not in response.get_data(as_text=True).lower()

    nested = client.get("/api/scheduled-archive/folders?path=Aras/EWO")
    assert nested.status_code == 200
    assert nested.get_json()["data"] == {
        "current": "Aras/EWO",
        "parent": "Aras",
        "folders": [{"name": "2026", "relativePath": "Aras/EWO/2026"}],
    }


@pytest.mark.parametrize("path", ["../outside", "/absolute", "Aras\\EWO", "C:/temp"])
def test_folder_api_rejects_unsafe_paths(client, path: str) -> None:
    response = client.get("/api/scheduled-archive/folders", query_string={"path": path})
    assert response.status_code == 422
    assert response.get_json()["error"]["type"] == "ValidationError"


def test_folder_api_returns_not_found_without_disclosing_paths(client) -> None:
    response = client.get("/api/scheduled-archive/folders?path=missing")
    assert response.status_code == 404
    text = response.get_data(as_text=True)
    assert "missing" not in text
    assert "archive" not in text.lower()


def test_native_folder_picker_endpoint_is_local_and_returns_absolute_path(client) -> None:
    """The native picker remains local-only and returns the selected directory for a job override."""
    response = client.post(
        "/api/scheduled-archive/folders/native",
        json={"path": ""},
        headers={"Host": "127.0.0.1:5000"},
    )
    assert response.status_code in {200, 204, 503}
    if response.status_code == 200:
        body = response.get_json()
        assert body["ok"] is True
        selected = body["data"].get("path")
        assert selected is None or Path(str(selected)).is_absolute()


def test_native_folder_picker_returns_selected_local_directory(tmp_path: Path) -> None:
    """A native selection becomes the task directory and may be outside the global default root."""
    database = DatabaseManager(tmp_path / "native-picker.db")
    database.init_database()
    root = tmp_path / "archive"
    selected = root / "Aras" / "EWO"
    selected.mkdir(parents=True)
    store = ArchiveStore({"default": root}, reserve_bytes=0)
    service = ScheduledArchiveAdminService(
        database,
        archive_store=store,
        native_picker=lambda _initial: selected,
    )
    assert Path(str(service.pick_native_folder()["path"])).resolve() == selected.resolve()

    outside = tmp_path / "outside"
    outside.mkdir()
    escaping = ScheduledArchiveAdminService(
        database,
        archive_store=store,
        native_picker=lambda _initial: outside,
    )
    assert Path(str(escaping.pick_native_folder()["path"])).resolve() == outside.resolve()


def test_native_folder_picker_uses_existing_override_as_initial_directory(tmp_path: Path) -> None:
    """An existing task override is passed to the native picker as its initial directory."""
    database = DatabaseManager(tmp_path / "native-initial.db")
    database.init_database()
    default_root = tmp_path / "default-archive"
    default_root.mkdir()
    selected = tmp_path / "task-archive"
    selected.mkdir()
    initial_paths: list[Path] = []
    service = ScheduledArchiveAdminService(
        database,
        archive_store=ArchiveStore({"default": default_root}, reserve_bytes=0),
        native_picker=lambda initial: (initial_paths.append(initial) or selected),
    )

    result = service.pick_native_folder(str(selected))

    assert Path(str(result["path"])).resolve() == selected.resolve()
    assert initial_paths == [selected]


def test_archive_folder_listing_uses_configured_archive_root(tmp_path: Path) -> None:
    """The settings-page archive root and the scheduled archive browser use one root contract."""
    database = DatabaseManager(tmp_path / "configured-root.db")
    database.init_database()
    configured_root = tmp_path / "configured-archive"
    (configured_root / "tdc" / "data-model").mkdir(parents=True)
    database.update_app_settings({"archiveDirectory": str(configured_root)})
    service = ScheduledArchiveAdminService(database)
    result = service.list_folders()
    assert result["folders"] == [{"name": "tdc", "relativePath": "tdc"}]
