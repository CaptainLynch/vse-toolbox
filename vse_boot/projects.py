# -*- coding: utf-8 -*-
"""Projects: one data folder per project, chosen before the app process starts.

The app was built around a single project (phase ``VPI-T2`` and deliverables
``VPI-T2-D1..D8`` are literals in ~130 places), so instead of re-keying every
table the launcher keeps one complete data folder per project and starts the
app on the active one. Switching project = save the choice + restart the app
(a few seconds). Settings that are not per project — the saved domain password
— live in Windows Credential Manager and are shared automatically.

``state/projects.json``::

    {"active": "main",
     "projects": [{"id": "main", "name": "", "vehicle": "", "departments": [], "createdAt": "..."}]}

The ``main`` project is the install root itself, so installs from before
multi-project keep their data where it is. Other projects live in
``projects/<id>/`` (its ``data/`` folder holds the database).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from vse_boot.layout import InstallLayout

MAIN_ID = "main"
MAX_PROJECTS = 20
_ID_PATTERN = re.compile(r"^(main|p\d{1,4})$")
_MAX_NAME = 40
_MAX_VEHICLE = 40
_MAX_DEPARTMENTS = 12


class ProjectError(ValueError):
    """A request the user can fix (bad name, unknown project, too many projects)."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _registry_file(layout: InstallLayout) -> Path:
    return layout.state_dir / "projects.json"


def _clean_text(value: Any, *, limit: int, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProjectError(f"{label}必须是文字")
    text = value.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ProjectError(f"{label}包含不可见字符")
    if len(text) > limit:
        raise ProjectError(f"{label}不能超过 {limit} 个字")
    return text


def _clean_departments(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProjectError("科室必须是列表")
    result: list[str] = []
    for item in value:
        text = _clean_text(item, limit=_MAX_NAME, label="科室")
        if text and text not in result:
            result.append(text)
    if len(result) > _MAX_DEPARTMENTS:
        raise ProjectError(f"科室最多选 {_MAX_DEPARTMENTS} 个")
    return result


def _default_registry() -> dict[str, Any]:
    return {"active": MAIN_ID, "projects": [{"id": MAIN_ID, "name": "", "vehicle": "", "departments": [], "createdAt": None}]}


class ProjectRegistry:
    def __init__(self, layout: InstallLayout) -> None:
        self.layout = layout
        self.data = self._read()

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(_registry_file(self.layout).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 文件缺失或损坏都回到「只有主项目」：主项目的数据就在安装目录里，不会丢；
            # 其他项目的文件夹也还在，重新建同名项目不会覆盖它们（编号只增不复用）。
            return _default_registry()
        projects = [p for p in raw.get("projects", []) if isinstance(p, dict) and _ID_PATTERN.match(str(p.get("id", "")))]
        if not any(p["id"] == MAIN_ID for p in projects):
            projects.insert(0, _default_registry()["projects"][0])
        for project in projects:
            project.setdefault("name", "")
            project.setdefault("vehicle", "")
            project.setdefault("departments", [])
            project.setdefault("createdAt", None)
        active = raw.get("active")
        if active not in {p["id"] for p in projects}:
            active = MAIN_ID
        return {"active": active, "projects": projects, "nextId": int(raw.get("nextId") or 0)}

    def save(self) -> None:
        self.layout.state_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.layout.state_dir, prefix=".projects-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, _registry_file(self.layout))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── queries ──────────────────────────────────────────────────────

    @property
    def active_id(self) -> str:
        return str(self.data["active"])

    def projects(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self.data["projects"]]

    def get(self, project_id: str) -> dict[str, Any]:
        for project in self.data["projects"]:
            if project["id"] == project_id:
                return project
        raise ProjectError("没有这个项目，请刷新后再试")

    def data_root(self, project_id: str | None = None) -> Path:
        project_id = project_id or self.active_id
        if not _ID_PATTERN.match(project_id):
            raise ProjectError("项目编号无效")
        return self.layout.root if project_id == MAIN_ID else self.layout.root / "projects" / project_id

    def database(self, project_id: str | None = None) -> Path:
        return self.data_root(project_id) / "data" / "vse_toolbox.db"

    # ── changes ──────────────────────────────────────────────────────

    def create(self, *, name: Any, vehicle: Any, departments: Any = None) -> dict[str, Any]:
        clean_name = _clean_text(name, limit=_MAX_NAME, label="项目名称")
        clean_vehicle = _clean_text(vehicle, limit=_MAX_VEHICLE, label="车型")
        if not clean_vehicle:
            raise ProjectError("请填写车型，例如 F610S")
        if not clean_name:
            clean_name = clean_vehicle
        if len(self.data["projects"]) >= MAX_PROJECTS:
            raise ProjectError(f"最多 {MAX_PROJECTS} 个项目")
        if any(p["name"] == clean_name for p in self.data["projects"]):
            raise ProjectError("已经有同名项目了")
        existing = [int(p["id"][1:]) for p in self.data["projects"] if p["id"] != MAIN_ID]
        number = max([self.data.get("nextId") or 0, *existing, 1]) + 1
        # 编号只增不复用：删过的项目文件夹（若用户手工保留）不会被新项目接管。
        while (self.layout.root / "projects" / f"p{number}").exists():
            number += 1
        project = {
            "id": f"p{number}",
            "name": clean_name,
            "vehicle": clean_vehicle,
            "departments": _clean_departments(departments),
            "createdAt": _now(),
        }
        (self.data_root(project["id"]) / "data").mkdir(parents=True, exist_ok=True)
        self.data["projects"].append(project)
        self.data["nextId"] = number
        self.save()
        return dict(project)

    def update(self, project_id: str, *, name: Any = None, vehicle: Any = None, departments: Any = None) -> dict[str, Any]:
        project = self.get(project_id)
        if name is not None:
            clean_name = _clean_text(name, limit=_MAX_NAME, label="项目名称")
            if clean_name and any(p["name"] == clean_name and p["id"] != project_id for p in self.data["projects"]):
                raise ProjectError("已经有同名项目了")
            project["name"] = clean_name
        if vehicle is not None:
            project["vehicle"] = _clean_text(vehicle, limit=_MAX_VEHICLE, label="车型")
        if departments is not None:
            project["departments"] = _clean_departments(departments)
        self.save()
        return dict(project)

    def switch(self, project_id: str) -> dict[str, Any]:
        project = self.get(project_id)
        self.data["active"] = project_id
        self.save()
        return dict(project)


def active_data_root(layout: InstallLayout) -> Path:
    return ProjectRegistry(layout).data_root()


def active_database(layout: InstallLayout) -> Path:
    return ProjectRegistry(layout).database()
