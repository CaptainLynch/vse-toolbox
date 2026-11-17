# -*- coding: utf-8 -*-
"""项目管理契约测试（docs/refactor-v2/CONTRACTS.md C3）。

测试重点：
1. 改名不动 id 与数据目录
2. PATCH 字段语义：省略 = 不改，显式 null = 清空（vehicle/departments 支持；name 不允许清空）
3. revision 递增与 expectedRevision 409 RevisionConflict 修订冲突检查
4. 归档保护：单项目禁止归档、当前项目引导先切换后归档（409 CurrentProjectArchived）
5. 归档永不物理删除任何项目数据
6. 旧 projects.json（缺 status / revision 字段、或使用 retired 布尔值）容忍读取与更新
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import web.app as web_app
from vse_boot import projects
from vse_boot.layout import InstallLayout

REPO = Path(__file__).resolve().parent.parent


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


@pytest.fixture()
def layout(tmp_path: Path) -> InstallLayout:
    """独立于 Web 客户端的注册表测试夹具：只在 tmp_path 下建安装布局。"""
    root = tmp_path / "VSE-Toolbox-registry"
    return InstallLayout(root).ensure()


def test_rename_preserves_id_and_data_root(client) -> None:  # type: ignore[no-untyped-def]
    """改名只修改显示名称，不改变项目 id，也不移动或删除底层数据目录。"""
    c, layout = client(True)
    created = c.post(
        "/api/p/workbench/projects",
        json={"name": "项目初始名称", "vehicle": "F610S", "departments": ["车身科"]},
    ).get_json()["data"]["project"]
    project_id = created["id"]
    assert project_id.startswith("p")

    # 在数据目录下放置标记文件，验证改名后目录与数据保持不动
    data_dir = layout.root / "projects" / project_id / "data"
    assert data_dir.is_dir()
    marker_file = data_dir / "marker.txt"
    marker_file.write_text("keep-me", encoding="utf-8")

    # 改名
    res = c.patch(f"/api/p/workbench/projects/{project_id}", json={"name": "全新项目名"})
    assert res.status_code == 200
    updated = res.get_json()["data"]["project"]
    assert updated["id"] == project_id
    assert updated["name"] == "全新项目名"

    # 数据目录与标记文件未受任何影响
    assert marker_file.is_file()
    assert marker_file.read_text(encoding="utf-8") == "keep-me"
    # 确认没有创建以新名称命名的目录
    assert not (layout.root / "projects" / "全新项目名").exists()


def test_patch_omitted_vs_explicit_null(client) -> None:  # type: ignore[no-untyped-def]
    """PATCH 字段语义：省略 = 不改；显式 null = 清空（vehicle/departments）；name 不允许清空。"""
    c, layout = client(True)
    c.post(
        "/api/p/workbench/projects",
        json={"name": "项目A", "vehicle": "F720", "departments": ["车身科", "内饰科"]},
    )

    # 1. 省略 vehicle 与 departments：只改 name，其他字段保持原样
    res1 = c.patch("/api/p/workbench/projects/p2", json={"name": "项目B"})
    assert res1.status_code == 200
    p1 = res1.get_json()["data"]["project"]
    assert p1["name"] == "项目B"
    assert p1["vehicle"] == "F720"
    assert p1["departments"] == ["车身科", "内饰科"]

    # 2. 显式 null：清空 vehicle 与 departments，省略 name 保持不变
    res2 = c.patch("/api/p/workbench/projects/p2", json={"vehicle": None, "departments": None})
    assert res2.status_code == 200
    p2 = res2.get_json()["data"]["project"]
    assert p2["name"] == "项目B"
    assert p2["departments"] == []
    # vehicle 的视图层对当前项目有「回退到主计划显示名」的既有行为（view()），
    # 清空与否要看存储值：registry 里的 vehicle 必须已清空。
    assert projects.ProjectRegistry(layout).get("p2")["vehicle"] == ""

    # 3. 显式 null 清空 name：不允许，返回 422 验证错误
    res_bad_null = c.patch("/api/p/workbench/projects/p2", json={"name": None})
    assert res_bad_null.status_code == 422
    assert res_bad_null.get_json()["error"]["type"] == "ValidationError"
    assert "清空" in res_bad_null.get_json()["error"]["message"] or "为空" in res_bad_null.get_json()["error"]["message"]

    # 4. 空白字符串清空 name：同样 422
    res_bad_blank = c.patch("/api/p/workbench/projects/p2", json={"name": "   "})
    assert res_bad_blank.status_code == 422
    assert res_bad_blank.get_json()["error"]["type"] == "ValidationError"


def test_revision_increment_and_conflict_409(client) -> None:  # type: ignore[no-untyped-def]
    """项目加 revision 字段，每次更新递增；expectedRevision 冲突返回 409 RevisionConflict。"""
    c, layout = client(True)
    c.post("/api/p/workbench/projects", json={"name": "修订测试", "vehicle": "F100"})

    registry = projects.ProjectRegistry(layout)
    assert registry.get("p2")["revision"] == 0

    # 首次更新：不带 expectedRevision，成功后 revision 变为 1
    res1 = c.patch("/api/p/workbench/projects/p2", json={"name": "修订版1"})
    assert res1.status_code == 200
    assert res1.get_json()["data"]["project"]["revision"] == 1
    assert projects.ProjectRegistry(layout).get("p2")["revision"] == 1

    # 第二次更新：携带匹配的 expectedRevision=1，成功后 revision 变为 2
    res2 = c.patch("/api/p/workbench/projects/p2", json={"name": "修订版2", "expectedRevision": 1})
    assert res2.status_code == 200
    assert res2.get_json()["data"]["project"]["revision"] == 2

    # 修订冲突：再次使用已失效的 expectedRevision=1，返回 409 RevisionConflict
    res_conflict = c.patch("/api/p/workbench/projects/p2", json={"name": "修订冲突版", "expectedRevision": 1})
    assert res_conflict.status_code == 409
    err = res_conflict.get_json()["error"]
    assert err["type"] == "RevisionConflict"
    assert "刷新" in err["message"]
    # 冲突未产生修改，revision 仍为 2
    assert projects.ProjectRegistry(layout).get("p2")["revision"] == 2
    assert projects.ProjectRegistry(layout).get("p2")["name"] == "修订版2"

    # 省略 expectedRevision 仍可正常更新
    res3 = c.patch("/api/p/workbench/projects/p2", json={"name": "修订版3"})
    assert res3.status_code == 200
    assert res3.get_json()["data"]["project"]["revision"] == 3


def test_archive_protection_current_and_single_project(client) -> None:  # type: ignore[no-untyped-def]
    """归档保护：只有一个项目时 409；当前 active 项目不可直接归档（引导先切换）。"""
    c, layout = client(True)

    # 1. 只有一个主项目时，不能归档
    res_single = c.post("/api/p/workbench/projects/main/archive")
    assert res_single.status_code == 409
    assert res_single.get_json()["error"]["type"] == "CurrentProjectArchived"

    # 2. 新建 p2，当前项目切换到了 p2
    c.post("/api/p/workbench/projects", json={"name": "次项目", "vehicle": "F200"})
    assert projects.ProjectRegistry(layout).active_id == "p2"

    # 3. 尝试归档当前项目 p2：返回 409，文案提示先切换
    res_cur = c.post("/api/p/workbench/projects/p2/archive")
    assert res_cur.status_code == 409
    err_cur = res_cur.get_json()["error"]
    assert err_cur["type"] == "CurrentProjectArchived"
    assert "切换" in err_cur["message"]

    # 4. 归档非当前项目 main：允许成功
    res_arch_main = c.post("/api/p/workbench/projects/main/archive")
    assert res_arch_main.status_code == 200
    assert res_arch_main.get_json()["data"]["project"]["status"] == "retired"

    # 5. main 归档后，只剩 p2 一个 active 项目；此时再尝试归档 p2 仍然返回 409
    res_last = c.post("/api/p/workbench/projects/p2/archive")
    assert res_last.status_code == 409
    assert res_last.get_json()["error"]["type"] == "CurrentProjectArchived"


def test_archive_never_physically_deletes_data(client) -> None:  # type: ignore[no-untyped-def]
    """归档不物理删除任何数据：数据文件夹保留，注册表与 GET 接口均保留该项目。"""
    c, layout = client(True)
    c.post("/api/p/workbench/projects", json={"name": "项目留存", "vehicle": "F300"})
    # 切回主项目，以便归档 p2
    c.post("/api/p/workbench/projects/main/switch")
    assert projects.ProjectRegistry(layout).active_id == "main"

    data_dir = layout.root / "projects" / "p2" / "data"
    test_db = data_dir / "custom.db"
    test_db.write_text("important-data", encoding="utf-8")

    # 执行归档
    res = c.post("/api/p/workbench/projects/p2/archive")
    assert res.status_code == 200

    # 物理文件完整保留
    assert data_dir.is_dir()
    assert test_db.is_file()
    assert test_db.read_text(encoding="utf-8") == "important-data"

    # 注册表与查询接口仍然包含该项目（status 为 retired）
    registry = projects.ProjectRegistry(layout)
    p2 = registry.get("p2")
    assert p2["status"] == "retired"
    assert any(p["id"] == "p2" for p in registry.projects())

    # GET /projects 载荷带有 status == 'retired'
    list_res = c.get("/api/p/workbench/projects").get_json()["data"]
    p2_item = next(p for p in list_res["projects"] if p["id"] == "p2")
    assert p2_item["status"] == "retired"


def test_tolerant_read_of_legacy_projects_json_and_update(layout: InstallLayout) -> None:  # type: ignore[no-untyped-def]
    """旧 projects.json（缺少 status/revision 字段，或包含 retired 布尔值）可容忍读取并正常更新。"""
    legacy_content = {
        "active": "main",
        "projects": [
            {"id": "main", "name": "旧版主项目", "vehicle": "F610S", "departments": []},
            {"id": "p2", "name": "旧版已退休项目", "vehicle": "F720", "departments": ["车身科"], "retired": True},
        ],
        "nextId": 2,
    }
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    (layout.state_dir / "projects.json").write_text(json.dumps(legacy_content, ensure_ascii=False), encoding="utf-8")

    registry = projects.ProjectRegistry(layout)
    main_p = registry.get("main")
    assert main_p["status"] == "active"
    assert main_p["revision"] == 0

    retired_p = registry.get("p2")
    assert retired_p["status"] == "retired"
    assert retired_p["revision"] == 0

    # 对旧项目进行更新：不报错，成功自增 revision 并保存完整结构
    updated = registry.update("main", name="升级后的主项目")
    assert updated["name"] == "升级后的主项目"
    assert updated["revision"] == 1
    assert updated["status"] == "active"

    reloaded = projects.ProjectRegistry(layout)
    assert reloaded.get("main")["revision"] == 1
