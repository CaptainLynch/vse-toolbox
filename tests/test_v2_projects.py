# -*- coding: utf-8 -*-
"""v2 多项目：一个项目一个数据文件夹，启动器按当前项目启动程序（需求 C1）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from vse_boot import projects, supervisor
from vse_boot.layout import InstallLayout
from vse_boot.state import BootState

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    return InstallLayout(tmp_path / "VSE-Toolbox").ensure()


def test_fresh_install_has_only_main_project_in_install_root(layout: InstallLayout) -> None:
    registry = projects.ProjectRegistry(layout)
    assert registry.active_id == "main"
    assert [p["id"] for p in registry.projects()] == ["main"]
    assert registry.data_root() == layout.root
    assert projects.active_database(layout) == layout.database


def test_create_switch_and_update_projects(layout: InstallLayout) -> None:
    registry = projects.ProjectRegistry(layout)
    created = registry.create(name="", vehicle=" F720 ", departments=["车身科", "车身科", "内饰科"])
    assert created["id"] == "p2"
    assert created["name"] == "F720"  # 名称留空时用车型
    assert created["departments"] == ["车身科", "内饰科"]
    assert (layout.root / "projects" / "p2" / "data").is_dir()
    registry.switch("p2")

    reloaded = projects.ProjectRegistry(layout)
    assert reloaded.active_id == "p2"
    assert projects.active_data_root(layout) == layout.root / "projects" / "p2"
    second = reloaded.create(name="第二个", vehicle="F610S")
    assert second["id"] == "p3"
    reloaded.update("p3", name="改名", departments=["车体科"])
    assert projects.ProjectRegistry(layout).get("p3")["name"] == "改名"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"name": "x", "vehicle": ""}, "请填写车型"),
        ({"name": "x" * 41, "vehicle": "F1"}, "不能超过"),
        ({"name": "a\x07", "vehicle": "F1"}, "不可见字符"),
        ({"name": "x", "vehicle": "F1", "departments": "车身科"}, "科室必须是列表"),
    ],
)
def test_create_rejects_bad_input(layout: InstallLayout, kwargs, message) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(projects.ProjectError, match=message):
        projects.ProjectRegistry(layout).create(**kwargs)


def test_duplicate_names_and_unknown_projects_are_rejected(layout: InstallLayout) -> None:
    registry = projects.ProjectRegistry(layout)
    registry.create(name="A", vehicle="F1")
    with pytest.raises(projects.ProjectError, match="同名"):
        registry.create(name="A", vehicle="F2")
    with pytest.raises(projects.ProjectError, match="没有这个项目"):
        registry.switch("p99")


def test_corrupt_registry_falls_back_to_main_and_never_reuses_folders(layout: InstallLayout) -> None:
    registry = projects.ProjectRegistry(layout)
    registry.create(name="A", vehicle="F1")
    registry.switch("p2")
    (layout.state_dir / "projects.json").write_text("{broken", encoding="utf-8")
    recovered = projects.ProjectRegistry(layout)
    assert recovered.active_id == "main"
    # p2 的文件夹还在：新项目必须换一个编号，不能接管旧数据。
    assert recovered.create(name="B", vehicle="F2")["id"] == "p3"


def test_supervisor_starts_app_on_active_project_data_root(layout: InstallLayout, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    registry = projects.ProjectRegistry(layout)
    registry.create(name="A", vehicle="F1")
    registry.switch("p2")
    seen: dict[str, str] = {}

    class FakePopen:
        pid = 1

        def __init__(self, command, cwd, env, **_kwargs):  # type: ignore[no-untyped-def]
            seen.update(env)

    monkeypatch.setattr(supervisor.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(supervisor._JOB, "assign", lambda child: None)
    app_dir = layout.app_dir("2.0.0")
    app_dir.mkdir(parents=True)
    supervisor.spawn_app(app_dir, 5000, layout)
    assert seen["VSE_DATA_ROOT"] == str(layout.root / "projects" / "p2")
    assert seen["VSE_INSTALL_ROOT"] == str(layout.root)


def test_failed_trial_restores_the_database_of_the_project_it_snapshotted(layout: InstallLayout) -> None:
    import sqlite3

    registry = projects.ProjectRegistry(layout)
    registry.create(name="A", vehicle="F1")
    registry.switch("p2")
    database = registry.database()
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('before')")
    state = BootState(layout)
    state.app.update(current="2.0.0", trial="2.1.0")
    state.save()
    layout.app_dir("2.1.0").mkdir(parents=True)
    sup = supervisor.Supervisor.__new__(supervisor.Supervisor)
    sup.layout = layout
    sup._snapshot_before_trial(state, "2.1.0")
    assert Path(state.app["trialSnapshot"]).parent == layout.snapshots_dir / "p2"
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE t SET v = 'migrated'")
    registry.switch("main")  # 试用期间切回主项目也不能把快照写进主项目的库
    BootState(layout).abandon("2.1.0", reason="test")
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "before"
    assert not layout.database.exists()


# ── 工作台「项目」接口 ──────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "data" / "host.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    monkeypatch.delenv("VSE_INSTALL_ROOT", raising=False)

    def make(managed: bool):  # type: ignore[no-untyped-def]
        root = tmp_path / "VSE-Toolbox"
        if managed:
            InstallLayout(root).ensure()
            monkeypatch.setenv("VSE_INSTALL_ROOT", str(root))
        app = web_app.create_app(plugin_dirs=[REPO / "plugins"], plugin_only=["workbench"])
        app.config.update(TESTING=True)
        return app.test_client(), InstallLayout(root)

    return make


def test_unmanaged_run_lists_one_project_named_after_the_phase_vehicle(client) -> None:  # type: ignore[no-untyped-def]
    c, _layout = client(False)
    data = c.get("/api/p/workbench/projects").get_json()["data"]
    assert data["managed"] is False
    assert data["projects"] == [{"id": "main", "name": "F610S", "vehicle": "F610S", "departments": [], "active": True}]
    response = c.post("/api/p/workbench/projects", json={"name": "A", "vehicle": "F1"})
    assert response.status_code == 409


def test_managed_create_switches_and_requests_restart(client) -> None:  # type: ignore[no-untyped-def]
    c, layout = client(True)
    response = c.post("/api/p/workbench/projects", json={"name": "", "vehicle": "F720", "departments": ["车身科"]})
    assert response.status_code == 200, response.get_json()
    assert layout.restart_request.is_file()
    registry = json.loads((layout.state_dir / "projects.json").read_text(encoding="utf-8"))
    assert registry["active"] == "p2"
    data = c.get("/api/p/workbench/projects").get_json()["data"]
    assert [(p["id"], p["name"], p["active"]) for p in data["projects"]] == [("main", "默认项目", False), ("p2", "F720", True)]

    layout.restart_request.unlink()
    switched = c.post("/api/p/workbench/projects/main/switch").get_json()["data"]
    assert switched["restarting"] is True and layout.restart_request.is_file()

    bad = c.post("/api/p/workbench/projects", json={"name": "x", "vehicle": ""})
    assert bad.status_code == 422
    assert "车型" in bad.get_json()["error"]["message"]
    assert c.patch("/api/p/workbench/projects/p2", json={"name": "新名字"}).status_code == 200
    assert c.post("/api/p/workbench/projects/p9/switch").status_code == 422


def test_subsystem_strategy_deliverable_is_retired_but_kept(client) -> None:  # type: ignore[no-untyped-def]
    """用户 2026-10-28：取消「子系统开发策略」——v2 页面靠 retired 隐藏，数据不删。"""
    c, _layout = client(False)
    app = web_app.create_app(plugin_dirs=[REPO / "plugins"], plugin_only=["workbench"])
    app.config.update(TESTING=True)
    items = app.test_client().get("/api/project-status").get_json()["data"]["deliverables"]
    retired = {d["id"] for d in items if d["retired"]}
    assert retired == {"VPI-T2-D1"}
    assert any(d["id"] == "VPI-T2-D1" for d in items)
