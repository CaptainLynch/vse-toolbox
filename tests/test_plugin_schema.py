# -*- coding: utf-8 -*-
"""Per-plugin additive schema migrations (plugin_schema_versions)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import web.app as web_app
from core.db_manager import DatabaseManager
from core.repos.plugin_schema import plugin_table_prefix


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(tmp_path / "plugin-schema.db")
    manager.init_database()
    return manager


def _create(table: str):
    def step(conn: sqlite3.Connection) -> None:
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, name TEXT)")
    return step


def _add_column(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE p_demo_items ADD COLUMN note TEXT")


def _columns(db: DatabaseManager, table: str) -> set[str]:
    with db.get_connection() as conn:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_steps_apply_in_order_and_are_idempotent(db: DatabaseManager) -> None:
    assert db.table_exists("plugin_schema_versions")
    assert db.get_plugin_schema_version("demo") == 0
    steps = [(2, _add_column), (1, _create("p_demo_items"))]
    assert db.apply_plugin_migrations("demo", steps) == 2
    assert _columns(db, "p_demo_items") == {"id", "name", "note"}
    assert db.apply_plugin_migrations("demo", steps) == 2
    assert db.get_plugin_schema_version("demo") == 2


def test_failed_step_rolls_back_whole_step(db: DatabaseManager) -> None:
    def broken(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE p_demo_half (id INTEGER)")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        db.apply_plugin_migrations("demo", [(1, _create("p_demo_items")), (2, broken)])
    assert db.get_plugin_schema_version("demo") == 1
    assert db.table_exists("p_demo_items")
    assert not db.table_exists("p_demo_half")


def test_database_newer_than_plugin_is_kept(db: DatabaseManager) -> None:
    db.apply_plugin_migrations("demo", [(1, _create("p_demo_items")), (2, _add_column)])
    # 回滚到只认识 v1 的旧插件包：不报错、不降级。
    assert db.apply_plugin_migrations("demo", [(1, _create("p_demo_items"))]) == 2


@pytest.mark.parametrize("steps", [[(0, _add_column)], [(1, _add_column), (1, _add_column)]])
def test_invalid_versions_rejected(db: DatabaseManager, steps) -> None:
    with pytest.raises(ValueError):
        db.apply_plugin_migrations("demo", steps)


def test_invalid_plugin_id_rejected(db: DatabaseManager) -> None:
    with pytest.raises(ValueError):
        db.apply_plugin_migrations("../x", [(1, _add_column)])


def test_table_prefix() -> None:
    assert plugin_table_prefix("deliverable-forms") == "p_deliverable_forms_"


def test_plugin_host_migrate_during_register(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugin = plugins / "notes"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({
        "id": "notes", "name": "笔记", "version": "1.0.0", "hostApi": ">=1,<2",
    }), encoding="utf-8")
    (plugin / "backend.py").write_text(
        "def register(host):\n"
        "    table = host.table_prefix + 'items'\n"
        "    host.migrate([(1, lambda conn: conn.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))])\n"
        "    @host.blueprint.get('/count')\n"
        "    def count():\n"
        "        with host.context.db.get_connection() as conn:\n"
        "            n = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]\n"
        "        return host.context.json_ok({'count': n})\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "data" / "host.db"
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(db_path))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[plugins])
    client = app.test_client()
    assert client.get("/api/p/notes/count").get_json()["data"] == {"count": 0}
    assert db_cls(db_path).get_plugin_schema_version("notes") == 1
