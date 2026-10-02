# -*- coding: utf-8 -*-
"""Plugin manifest contract (``plugin.json``) and host API compatibility.

为什么用 JSON 而不是 TOML：README 承诺支持 Python 3.9，标准库 ``tomllib``
从 3.11 才有；宿主不为清单格式引入第三方依赖。

清单只描述插件“是什么、挂在哪里”，不包含可执行逻辑；校验失败的插件
整体拒绝加载，不做部分容错。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

#: 宿主当前提供的插件 API 版本（major.minor）。只做加法演进：新增能力升
#: minor，破坏性变更升 major。
HOST_API_VERSION = "1.0"

MANIFEST_FILE_NAME = "plugin.json"

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONSTRAINT_PATTERN = re.compile(r"^(>=|<=|==|>|<)\s*(\d+)(?:\.(\d+))?$")
_PAGE_KINDS = frozenset({"schema", "module"})
_ALLOWED_KEYS = frozenset(
    {"id", "name", "version", "hostApi", "entry", "description", "requires", "nav", "pages"}
)


class PluginManifestError(ValueError):
    """Raised when a ``plugin.json`` is missing, malformed or incompatible."""


@dataclass(frozen=True)
class PageEntry:
    """A page the plugin contributes; routed by the shell at ``#p/<plugin>/<page>``."""

    id: str
    title: str
    kind: str = "schema"
    module: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "title": self.title, "kind": self.kind}
        if self.module is not None:
            payload["module"] = self.module
        return payload


@dataclass(frozen=True)
class NavEntry:
    """A top-bar navigation entry pointing at one of the plugin's pages."""

    title: str
    page: str
    order: int = 100

    def to_payload(self) -> dict[str, Any]:
        return {"title": self.title, "page": self.page, "order": self.order}


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    host_api: str
    entry: str = "backend"
    description: str = ""
    requires: tuple[str, ...] = ()
    nav: tuple[NavEntry, ...] = field(default_factory=tuple)
    pages: tuple[PageEntry, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "hostApi": self.host_api,
            "description": self.description,
            "nav": [entry.to_payload() for entry in self.nav],
            "pages": [page.to_payload() for page in self.pages],
        }


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Read and validate ``<plugin_dir>/plugin.json``."""
    path = Path(plugin_dir) / MANIFEST_FILE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PluginManifestError(f"缺少 {MANIFEST_FILE_NAME}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginManifestError(f"{MANIFEST_FILE_NAME} 无法解析") from exc
    return parse_manifest(raw)


def parse_manifest(raw: Any) -> PluginManifest:
    if not isinstance(raw, Mapping):
        raise PluginManifestError("清单必须是 JSON 对象")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise PluginManifestError(f"清单包含未知字段: {', '.join(sorted(unknown))}")

    plugin_id = _required_str(raw, "id")
    if not _ID_PATTERN.match(plugin_id):
        raise PluginManifestError("id 只能包含小写字母、数字、- 和 _，以字母开头，长度 2~40")
    version = _required_str(raw, "version")
    if not _VERSION_PATTERN.match(version):
        raise PluginManifestError("version 必须是 MAJOR.MINOR.PATCH 形式")
    host_api = _required_str(raw, "hostApi")
    parse_host_api_spec(host_api)
    entry = raw.get("entry", "backend")
    if not isinstance(entry, str) or not _ENTRY_PATTERN.match(entry):
        raise PluginManifestError("entry 必须是合法的 Python 模块名")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise PluginManifestError("description 必须是字符串")
    requires = raw.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(item, str) and item for item in requires):
        raise PluginManifestError("requires 必须是模块名字符串数组")

    pages = tuple(_parse_page(item) for item in _list(raw, "pages"))
    page_ids = [page.id for page in pages]
    if len(set(page_ids)) != len(page_ids):
        raise PluginManifestError("pages 中存在重复的 id")
    nav = tuple(_parse_nav(item) for item in _list(raw, "nav"))
    for entry_item in nav:
        if entry_item.page not in page_ids:
            raise PluginManifestError(f"nav 指向不存在的页面: {entry_item.page}")

    return PluginManifest(
        id=plugin_id,
        name=_required_str(raw, "name"),
        version=version,
        host_api=host_api,
        entry=entry,
        description=description,
        requires=tuple(requires),
        nav=nav,
        pages=pages,
    )


def parse_host_api_spec(spec: str) -> tuple[tuple[str, tuple[int, int]], ...]:
    """Parse ``">=1,<2"`` into ``((">=", (1, 0)), ("<", (2, 0)))``."""
    parts = [part.strip() for part in spec.split(",") if part.strip()]
    if not parts:
        raise PluginManifestError("hostApi 不能为空")
    constraints = []
    for part in parts:
        match = _CONSTRAINT_PATTERN.match(part)
        if match is None:
            raise PluginManifestError(f"hostApi 约束无效: {part}")
        operator, major, minor = match.groups()
        constraints.append((operator, (int(major), int(minor or 0))))
    return tuple(constraints)


def host_api_compatible(spec: str, host_version: str = HOST_API_VERSION) -> bool:
    major, _, minor = host_version.partition(".")
    current = (int(major), int(minor or 0))
    for operator, bound in parse_host_api_spec(spec):
        if operator == ">=" and not current >= bound:
            return False
        if operator == ">" and not current > bound:
            return False
        if operator == "<=" and not current <= bound:
            return False
        if operator == "<" and not current < bound:
            return False
        if operator == "==" and current != bound:
            return False
    return True


def _required_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(f"缺少字段或字段为空: {key}")
    return value.strip()


def _list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise PluginManifestError(f"{key} 必须是数组")
    return value


def _parse_page(item: Any) -> PageEntry:
    if not isinstance(item, Mapping):
        raise PluginManifestError("pages 的每一项必须是对象")
    page_id = _required_str(item, "id")
    if not _ID_PATTERN.match(page_id):
        raise PluginManifestError(f"页面 id 无效: {page_id}")
    kind = item.get("kind", "schema")
    if kind not in _PAGE_KINDS:
        raise PluginManifestError(f"页面 kind 只能是 {', '.join(sorted(_PAGE_KINDS))}")
    module = item.get("module")
    if kind == "module":
        if not isinstance(module, str) or not module.endswith(".js") or "/" in module or "\\" in module:
            raise PluginManifestError("module 页面必须给出 static/ 下的 .js 文件名")
    elif module is not None:
        raise PluginManifestError("只有 module 页面可以声明 module")
    return PageEntry(id=page_id, title=_required_str(item, "title"), kind=kind, module=module)


def _parse_nav(item: Any) -> NavEntry:
    if not isinstance(item, Mapping):
        raise PluginManifestError("nav 的每一项必须是对象")
    order = item.get("order", 100)
    if not isinstance(order, int) or isinstance(order, bool):
        raise PluginManifestError("nav.order 必须是整数")
    return NavEntry(title=_required_str(item, "title"), page=_required_str(item, "page"), order=order)
