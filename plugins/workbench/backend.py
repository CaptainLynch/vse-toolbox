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
GET   vehicle-models        车型清单配置 + 现有项目（含归档）在用的车型（只读派生）
PUT   vehicle-models        {codes}：整表替换车型清单配置，不修改任何项目的车型字段

车型清单只影响新建/编辑项目时的候选：初始为空（不预置、不编造任何车型代码），
写路由与其它写路由一样先过 ctx.local_guard()。

每个项目一个数据文件夹，由启动器在程序启动前选定（vse_boot/projects.py）。
直接从源码运行（没有启动器）时只有一个项目，新建和切换返回 409。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import request

#: 交付物的车型锚点就是主计划名称（project_status_phases.display_name）。
_PHASE_ID = "VPI-T2"

#: 车型清单配置上限：与「候选不编造、始终可手填」配套，只约束配置表本身。
_MAX_VEHICLE_MODELS = 200
_MAX_VEHICLE_CODE_LENGTH = 40


class VehicleModelsValidationError(ValueError):
    """车型清单请求不合法（字段级信息放在消息里，由路由转 400 ValidationError）。"""


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

    #: 车型清单配置表：只增不删的增量迁移，初始为空（不预置任何车型代码）。
    models_table = f"{host.table_prefix}vehicle_models"

    def _create_vehicle_models(conn) -> None:  # type: ignore[no-untyped-def]
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {models_table} ("
            "code TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
        )

    host.migrate([(1, _create_vehicle_models)])

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

    def project_snapshot() -> tuple[bool, str, list[dict[str, Any]]]:
        """现有项目列表（含归档）——车型清单的 inUse 与项目列表共用这一份查询。"""
        _api, projects, layout = managed()
        if layout is None:
            return False, "main", [view({"id": "main"}, "main")]
        registry = projects.ProjectRegistry(layout)
        active = registry.active_id
        return True, active, [view(project, active) for project in registry.projects()]

    def vehicles_in_use() -> list[str]:
        """现有项目（含归档）已在用的车型，去重升序；只读派生，不写回任何项目。"""
        seen: dict[str, str] = {}
        for project in project_snapshot()[2]:
            text = str(project.get("vehicle") or "").strip()
            if text:
                seen.setdefault(text.casefold(), text)
        return sorted(seen.values())

    def configured_vehicle_models() -> list[str]:
        with ctx.db.get_connection() as conn:
            rows = conn.execute(f"SELECT code FROM {models_table} ORDER BY rowid").fetchall()
        return [str(row["code"]) for row in rows]

    def validated_codes(payload: Any) -> list[str]:
        """strip → 非空 → ≤40 字符 → 大小写不敏感去重（保留首次写法）→ 总数 ≤200。"""
        if not isinstance(payload, dict) or not isinstance(payload.get("codes"), list):
            raise VehicleModelsValidationError("codes 必须是车型代码数组")
        raw = payload["codes"]
        codes: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, str):
                raise VehicleModelsValidationError(f"codes[{index}] 必须是文字")
            text = item.strip()
            if not text:
                raise VehicleModelsValidationError(f"codes[{index}] 不能为空")
            if len(text) > _MAX_VEHICLE_CODE_LENGTH:
                raise VehicleModelsValidationError(
                    f"codes[{index}] 不能超过 {_MAX_VEHICLE_CODE_LENGTH} 个字符"
                )
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            codes.append(text)
        if len(codes) > _MAX_VEHICLE_MODELS:
            raise VehicleModelsValidationError(
                f"车型清单最多 {_MAX_VEHICLE_MODELS} 项（去重后收到 {len(codes)} 项）"
            )
        return codes

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
        is_managed, active, items = project_snapshot()
        return ctx.json_ok({"managed": is_managed, "active": active, "projects": items})

    @bp.get("/vehicle-models")
    def vehicle_models_list():  # type: ignore[no-untyped-def]
        # json_ok 已带 Cache-Control: no-store：候选随时可能被别的窗口改掉。
        return ctx.json_ok({"configured": configured_vehicle_models(), "inUse": vehicles_in_use()})

    @bp.put("/vehicle-models")
    def vehicle_models_replace():  # type: ignore[no-untyped-def]
        guard = ctx.local_guard()
        if guard is not None:
            return guard
        try:
            codes = validated_codes(request.get_json(silent=True))
        except VehicleModelsValidationError as exc:
            return ctx.json_error(400, "ValidationError", str(exc))
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with ctx.db.get_connection() as conn:
            conn.execute(f"DELETE FROM {models_table}")
            conn.executemany(
                f"INSERT INTO {models_table} (code, created_at) VALUES (?, ?)",
                [(code, created_at) for code in codes],
            )
        return ctx.json_ok({"configured": codes})

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
