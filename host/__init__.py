# -*- coding: utf-8 -*-
"""Plugin host: manifest contract, host context and plugin registry.

The host owns lifecycle and shared services; feature plugins live under
``plugins/<id>/`` and integrate only through ``register(host)``. See
``docs/PLUGIN_REFACTOR_PLAN_20261001.md``.
"""

from host.context import HostContext
from host.plugin import HOST_API_VERSION, PluginManifest, PluginManifestError, load_manifest
from host.registry import PluginHost, PluginRecord, PluginRegistry, default_plugin_dirs

__all__ = [
    "HOST_API_VERSION",
    "HostContext",
    "PluginHost",
    "PluginManifest",
    "PluginManifestError",
    "PluginRecord",
    "PluginRegistry",
    "default_plugin_dirs",
    "load_manifest",
]
