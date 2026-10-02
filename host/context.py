# -*- coding: utf-8 -*-
"""HostContext: the only door through which plugins reach shared services.

插件不得 import ``web.app``，也不得自行实例化 ``DatabaseManager``：数据库、
凭据会话、任务执行器等都由宿主在 ``create_app`` 中创建一次，经这里交给
插件。这样宿主可以在测试中整体替换依赖，插件也不会绕开本机写保护。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from core.redaction import redact_sensitive_text

_PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")

JsonResponse = Any


def _default_redact(text: str) -> str:
    return redact_sensitive_text(text)


@dataclass(frozen=True)
class HostContext:
    """Shared services handed to every plugin's ``register(host)``.

    ``json_ok`` / ``json_error`` produce the host's ``{ok, data, error}``
    envelope; ``local_guard`` returns an error response when a mutation does
    not come from the local browser, else ``None``. Plugins must call it at
    the top of every write route.
    """

    db: Any
    data_dir: Path
    json_ok: Callable[..., JsonResponse]
    json_error: Callable[..., JsonResponse]
    local_guard: Callable[[], JsonResponse | None]
    services: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    redact: Callable[[str], str] = _default_redact

    def service(self, name: str) -> Any:
        """Return a shared host service by name (e.g. ``"settings_store"``)."""
        try:
            return self.services[name]
        except KeyError:
            raise LookupError(f"宿主未提供服务: {name}") from None

    def plugin_data_dir(self, plugin_id: str) -> Path:
        """Return (and create) the writable data directory owned by one plugin."""
        if not _PLUGIN_ID_PATTERN.match(plugin_id):
            raise ValueError("无效的插件 id")
        path = Path(self.data_dir) / "plugins" / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        return path
