# -*- coding: utf-8 -*-
"""Workbench plugin backend.

工作台页面主要编排宿主和其他插件已有的接口（/api/project-status、/api/settings、
/api/tasks、/api/p/sign-daily/state、/api/p/settings/app-updates …），不复制业务逻辑。
自有路由只有「项目」：

GET   projects               项目列表、当前项目、是否由启动器管理（retired 项目带 status 字段）
POST  projects               {name, vehicle, departments}：新建项目并切换过去（重启程序）
POST  projects/<id>/switch   切换到另一个项目（重启程序）
POST  projects/<id>/archive  归档项目（保留数据，当前项目不可直接归档）
PATCH projects/<id>          修改名称 / 车型 / 默认科室（支持 expectedRevision 修订检查）

每个项目一个数据文件夹，由启动器在程序启动前选定（vse_boot/projects.py）。
直接从源码运行（没有启动器）时只有一个项目，新建和切换返回 409。
"""

from __future__ import annotations

from typing import Any

from flask import request

#: 交付物的车型锚点就是主计划名称（project_status_phases.display_name）。
_PHASE_ID = "VPI-T2"


def _boot():  # type: ignore[no-untyped-def]
    """vse_boot belongs to the runtime layer; it is absent in old frozen builds."""
    try:
        from vse_boot import api, projects
    except ImportError:
        return None, None
    return api, projects


def register(host):
    ctx = host.context
    bp = host.blueprint

    def phase_vehicle() -> str:
        try:
            phase_row, _, _ = ctx.db.get_project_status(_PHASE_ID)
        except Exception:  # noqa: BLE001 - 读不到主计划只影响默认显示名
            return ""
        return str(phase_row["display_name"] or "") if phase_row else ""

    def view(project: dict[str, Any], active_id: str) -> dict[str, Any]:
        is_active = project["id"] == active_id
        vehicle = project.get("vehicle") or (phase_vehicle() if is_active else "")
        res: dict[str, Any] = {
            "id": project["id"],
            "name": project.get("name") or vehicle or "默认项目",
            "vehicle": vehicle,
            "departments": list(project.get("departments") or []),
            "active": is_active,
        }
        if "status" in project:
            res["status"] = project["status"]
        if "revision" in project:
            res["revision"] = int(project["revision"])
        return res

    def managed():  # type: ignore[no-untyped-def]
        api, projects = _boot()
        layout = api.managed_layout() if api else None
        return api, projects, layout

    def mutation(handler):  # type: ignore[no-untyped-def]
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            guard = ctx.local_guard()
            if guard is not None:
                return guard
            api, projects, layout = managed()
            if layout is None:
                return ctx.json_error(409, "NotManaged", "当前不是通过 VSE Toolbox 启动器运行，只能使用一个项目")
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                body = {}
            revision_err = getattr(projects, "RevisionConflictError", ())
            archive_err = getattr(projects, "CurrentProjectArchivedError", ())
            try:
                return handler(api, projects, layout, body, *args, **kwargs)
            except revision_err as exc:  # type: ignore[misc]
                return ctx.json_error(409, "RevisionConflict", str(exc))
            except archive_err as exc:  # type: ignore[misc]
                return ctx.json_error(409, "CurrentProjectArchived", str(exc))
            except projects.ProjectError as exc:
                return ctx.json_error(422, "ValidationError", str(exc))
            except OSError as exc:
                return ctx.json_error(500, "IOError", f"保存项目失败：{exc.strerror or exc}")
        wrapper.__name__ = handler.__name__
        return wrapper

    @bp.get("/projects")
    def projects_list():  # type: ignore[no-untyped-def]
        _api, projects, layout = managed()
        if layout is None:
            single = view({"id": "main"}, "main")
            return ctx.json_ok({"managed": False, "active": "main", "projects": [single]})
        registry = projects.ProjectRegistry(layout)
        active = registry.active_id
        return ctx.json_ok({"managed": True, "active": active, "projects": [view(p, active) for p in registry.projects()]})

    @bp.post("/projects")
    @mutation
    def projects_create(api, projects, layout, body):  # type: ignore[no-untyped-def]
        registry = projects.ProjectRegistry(layout)
        project = registry.create(name=body.get("name"), vehicle=body.get("vehicle"), departments=body.get("departments"))
        registry.switch(project["id"])
        api.request_restart(layout)
        return ctx.json_ok({"project": view(project, project["id"]), "message": f"已新建「{project['name']}」，正在切换过去"})

    @bp.post("/projects/<project_id>/switch")
    @mutation
    def projects_switch(api, projects, layout, body, project_id):  # type: ignore[no-untyped-def]
        registry = projects.ProjectRegistry(layout)
        if registry.active_id == project_id:
            return ctx.json_ok({"project": view(registry.get(project_id), project_id), "restarting": False})
        project = registry.switch(project_id)
        api.request_restart(layout)
        return ctx.json_ok({"project": view(project, project_id), "restarting": True,
                            "message": f"正在切换到「{project.get('name') or '默认项目'}」"})

    @bp.post("/projects/<project_id>/archive")
    @mutation
    def projects_archive(api, projects, layout, body, project_id):  # type: ignore[no-untyped-def]
        registry = projects.ProjectRegistry(layout)
        project = registry.archive(project_id)
        return ctx.json_ok({"project": view(project, registry.active_id),
                            "message": f"已归档「{project.get('name') or '默认项目'}」"})

    @bp.patch("/projects/<project_id>")
    @mutation
    def projects_update(api, projects, layout, body, project_id):  # type: ignore[no-untyped-def]
        registry = projects.ProjectRegistry(layout)
        update_kwargs: dict[str, Any] = {}
        if "name" in body:
            update_kwargs["name"] = body["name"]
        if "vehicle" in body:
            update_kwargs["vehicle"] = body["vehicle"]
        if "departments" in body:
            update_kwargs["departments"] = body["departments"]
        if "expectedRevision" in body:
            update_kwargs["expected_revision"] = body["expectedRevision"]
        project = registry.update(project_id, **update_kwargs)
        return ctx.json_ok({"project": view(project, registry.active_id)})

    return None
