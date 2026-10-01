# -*- coding: utf-8 -*-
"""Plugin discovery, loading and registration.

加载规则（勿破）：
- 每个插件是 ``plugins/<dir>/`` 下带 ``plugin.json`` 的目录；按目录名排序加载，
  结果可复现。
- 插件代码以包 ``vse_plugins.<id>`` 导入，插件内可以用相对导入；插件之间
  不得互相 import（由边界测试约束）。
- ``register(host)`` 只能往 ``host.blueprint`` 上挂路由；宿主在 register 成功后
  才把 Blueprint 注册进 Flask，失败的插件不会留下半注册的路由。
- 单个插件失败只记录状态与脱敏后的错误摘要，不影响宿主和其他插件启动。
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from flask import Blueprint, Flask

from host.context import HostContext
from host.plugin import (
    HOST_API_VERSION,
    MANIFEST_FILE_NAME,
    PluginManifest,
    PluginManifestError,
    host_api_compatible,
    load_manifest,
)

logger = logging.getLogger(__name__)

PLUGIN_PACKAGE = "vse_plugins"
API_PREFIX = "/api/p"
STATIC_PREFIX = "/plugins"
_ERROR_SUMMARY_LIMIT = 300


def default_plugin_dirs() -> list[Path]:
    """Plugin search paths for source runs and frozen (onedir) builds."""
    if getattr(sys, "frozen", False):
        return [Path(sys.executable).resolve().parent / "plugins"]
    return [Path(__file__).resolve().parent.parent / "plugins"]


@dataclass
class PluginRecord:
    """Load outcome of one plugin directory, as reported by ``/api/host/manifest``."""

    path: Path
    status: str
    manifest: PluginManifest | None = None
    error: str | None = None
    source: str = "bundled"

    @property
    def id(self) -> str | None:
        return self.manifest.id if self.manifest is not None else None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "directory": self.path.name, "source": self.source}
        if self.manifest is not None:
            payload.update(self.manifest.to_payload())
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass
class PluginHost:
    """Per-plugin facade passed to ``register(host)``."""

    manifest: PluginManifest
    context: HostContext
    blueprint: Blueprint
    plugin_dir: Path
    _data_dir: Path | None = field(default=None, repr=False)

    @property
    def data_dir(self) -> Path:
        if self._data_dir is None:
            self._data_dir = self.context.plugin_data_dir(self.manifest.id)
        return self._data_dir


class PluginRegistry:
    def __init__(
        self,
        search_paths: Sequence[Path] | None = None,
        *,
        host_api_version: str = HOST_API_VERSION,
        only: Iterable[str] | None = None,
        overrides: Mapping[str, Path] | None = None,
    ) -> None:
        self.search_paths = [Path(p) for p in (search_paths if search_paths is not None else default_plugin_dirs())]
        self.host_api_version = host_api_version
        self.only = frozenset(only) if only is not None else None
        # 已通过签名包安装并激活的版本：{插件 id: 目录}，优先于随包内置的同 id 插件。
        self.overrides = {key: Path(value) for key, value in (overrides or {}).items()}
        self.bundled_dirs: dict[str, Path] = {}
        self.records: list[PluginRecord] = []

    def discover(self) -> list[Path]:
        found: list[Path] = []
        for root in self.search_paths:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda p: p.name):
                if child.is_dir() and (child / MANIFEST_FILE_NAME).is_file():
                    found.append(child)
        return found

    def load_all(self, app: Flask, context: HostContext) -> list[PluginRecord]:
        _ensure_namespace_package()
        loaded_ids: set[str] = set()
        planned: list[tuple[Path, str]] = []
        overridden: set[str] = set()
        for plugin_dir in self.discover():
            try:
                plugin_id = load_manifest(plugin_dir).id
            except PluginManifestError:
                planned.append((plugin_dir, "bundled"))
                continue
            self.bundled_dirs.setdefault(plugin_id, plugin_dir)
            if plugin_id in self.overrides:
                overridden.add(plugin_id)
                planned.append((self.overrides[plugin_id], "installed"))
            else:
                planned.append((plugin_dir, "bundled"))
        for plugin_id in sorted(set(self.overrides) - overridden):
            planned.append((self.overrides[plugin_id], "installed"))
        for plugin_dir, source in planned:
            self.load_dir(app, context, plugin_dir, source=source, loaded_ids=loaded_ids)
        return self.records

    def load_dir(
        self,
        app: Flask,
        context: HostContext,
        plugin_dir: Path,
        *,
        source: str = "bundled",
        loaded_ids: set[str] | None = None,
    ) -> PluginRecord | None:
        """Load one plugin directory and record the outcome (used for rollback reloads too)."""
        _ensure_namespace_package()
        if loaded_ids is None:
            loaded_ids = {r.id for r in self.records if r.status == "loaded" and r.id is not None}
        record = self._load_one(app, context, plugin_dir, loaded_ids)
        if record is None:
            return None
        record.source = source
        self.records = [
            r for r in self.records
            if not (record.id is not None and r.id == record.id and r.status != "loaded")
        ]
        self.records.append(record)
        if record.status == "loaded" and record.id is not None:
            loaded_ids.add(record.id)
        return record

    def record_for(self, plugin_id: str) -> PluginRecord | None:
        return next((r for r in self.records if r.id == plugin_id), None)

    def manifest_payload(self) -> dict[str, Any]:
        nav = []
        for record in self.records:
            if record.status != "loaded" or record.manifest is None:
                continue
            for entry in record.manifest.nav:
                nav.append({"plugin": record.manifest.id, **entry.to_payload()})
        nav.sort(key=lambda item: (item["order"], item["plugin"], item["page"]))
        return {
            "hostApi": self.host_api_version,
            "plugins": [record.to_payload() for record in self.records],
            "nav": nav,
        }

    def _load_one(
        self,
        app: Flask,
        context: HostContext,
        plugin_dir: Path,
        loaded_ids: set[str],
    ) -> PluginRecord | None:
        try:
            manifest = load_manifest(plugin_dir)
        except PluginManifestError as exc:
            return PluginRecord(path=plugin_dir, status="invalid", error=str(exc))

        if self.only is not None and manifest.id not in self.only:
            return None
        if manifest.id in loaded_ids:
            return PluginRecord(path=plugin_dir, status="failed", manifest=manifest, error="插件 id 重复")
        if not host_api_compatible(manifest.host_api, self.host_api_version):
            return PluginRecord(
                path=plugin_dir,
                status="incompatible",
                manifest=manifest,
                error=f"需要宿主 API {manifest.host_api}，当前为 {self.host_api_version}",
            )
        missing = [name for name in manifest.requires if importlib.util.find_spec(name) is None]
        if missing:
            return PluginRecord(
                path=plugin_dir,
                status="failed",
                manifest=manifest,
                error=f"宿主缺少依赖: {', '.join(missing)}",
            )

        package_name = f"{PLUGIN_PACKAGE}.{manifest.id.replace('-', '_')}"
        blueprint_name = f"plugin_{manifest.id.replace('-', '_')}"
        blueprint = Blueprint(
            blueprint_name,
            package_name,
            root_path=str(plugin_dir),
            url_prefix=f"{API_PREFIX}/{manifest.id}",
        )
        try:
            _install_plugin_package(package_name, plugin_dir)
            module = importlib.import_module(f"{package_name}.{manifest.entry}")
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginManifestError(f"{manifest.entry}.py 未定义 register(host)")
            register(PluginHost(manifest=manifest, context=context, blueprint=blueprint, plugin_dir=plugin_dir))
            app.register_blueprint(blueprint)
            static_dir = plugin_dir / "static"
            if static_dir.is_dir():
                app.register_blueprint(
                    Blueprint(
                        f"{blueprint_name}_static",
                        package_name,
                        root_path=str(plugin_dir),
                        static_folder=str(static_dir),
                        static_url_path="/static",
                        url_prefix=f"{STATIC_PREFIX}/{manifest.id}",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - one plugin must never take the host down
            _uninstall_plugin_package(package_name)
            summary = context.redact(f"{type(exc).__name__}: {exc}")[:_ERROR_SUMMARY_LIMIT]
            logger.warning("Plugin %s failed to load: %s", manifest.id, summary)
            return PluginRecord(path=plugin_dir, status="failed", manifest=manifest, error=summary)

        logger.info("Plugin %s %s loaded", manifest.id, manifest.version)
        return PluginRecord(path=plugin_dir, status="loaded", manifest=manifest)


def _ensure_namespace_package() -> None:
    if PLUGIN_PACKAGE not in sys.modules:
        namespace = types.ModuleType(PLUGIN_PACKAGE)
        namespace.__path__ = []  # type: ignore[attr-defined]
        sys.modules[PLUGIN_PACKAGE] = namespace


def _install_plugin_package(package_name: str, plugin_dir: Path) -> None:
    _uninstall_plugin_package(package_name)
    package = types.ModuleType(package_name)
    package.__path__ = [str(plugin_dir)]  # type: ignore[attr-defined]
    package.__file__ = str(plugin_dir / "__init__.py")
    sys.modules[package_name] = package


def _uninstall_plugin_package(package_name: str) -> None:
    for name in [name for name in sys.modules if name == package_name or name.startswith(f"{package_name}.")]:
        del sys.modules[name]
