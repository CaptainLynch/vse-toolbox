# -*- coding: utf-8 -*-
"""Small, stable entry points shared by the launcher CLI and the running app.

The app (``plugins/settings``) may import this module: it is part of the
runtime layer and does not depend on app code. Everything here works on an
install root; inside the app it comes from ``VSE_INSTALL_ROOT``, which the
supervisor sets for the app process.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from vse_boot.discover import Candidate, find_updates
from vse_boot.layout import InstallLayout
from vse_boot.packages import load_trusted_keys, stage_app, verify_app_package
from vse_boot.state import BootState

RUNTIME_KEYS = Path(__file__).resolve().parent / "trusted_keys.json"

#: Closed set of tray notification events (frozen contract, DSH-V2-28).
NOTIFICATION_EVENTS = frozenset({"sync_failed", "daily_ready", "update_found"})
#: Inbox shared by the app process (publisher) and the launcher tray (consumer).
NOTIFICATIONS_DIR_NAME = "notifications"
#: Delivery ledger inside the inbox; newest ids last, FIFO-trimmed.
SENT_NOTIFICATIONS_FILE = "sent.json"
SENT_NOTIFICATIONS_LIMIT = 500


def managed_layout() -> InstallLayout | None:
    """The install this app process runs in, or ``None`` for a plain source run."""
    root = os.environ.get("VSE_INSTALL_ROOT", "").strip()
    return InstallLayout(Path(root)) if root else None


def trusted_keys(layout: InstallLayout) -> dict[str, bytes]:
    """Keys shipped with the runtime, plus keys the current app version ships (rotation)."""
    paths = [RUNTIME_KEYS]
    current = BootState(layout).app.get("current")
    if current:
        paths.append(layout.app_dir(current) / "host" / "trusted_keys.json")
    return load_trusted_keys(paths)


def watch_dirs(layout: InstallLayout) -> list[Path]:
    """Where received packages land: Downloads (Feishu default), the install root, the launcher folder."""
    dirs = [Path.home() / "Downloads", layout.root]
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    unique: list[Path] = []
    for path in dirs:
        if path not in unique:
            unique.append(path)
    return unique


def available_updates(layout: InstallLayout) -> list[Candidate]:
    current = BootState(layout).app.get("current")
    return [c for c in find_updates(watch_dirs(layout), trusted_keys(layout), current_app_version=current) if c.kind == "app"]


def stage_bytes(layout: InstallLayout, data: bytes) -> str:
    verified = verify_app_package(data, trusted_keys(layout))
    stage_app(verified, layout)
    BootState(layout).record("staged", verified.version, notes=verified.notes)
    return verified.version


def stage_file(layout: InstallLayout, path: Path) -> str:
    return stage_bytes(layout, Path(path).read_bytes())


def staged_versions(layout: InstallLayout) -> list[str]:
    if not layout.staging_dir.is_dir():
        return []
    return sorted(p.name[len("app-"):] for p in layout.staging_dir.glob("app-*") if (p / "staged.json").is_file())


def request_restart(layout: InstallLayout) -> None:
    """Ask the running supervisor to restart the app (installs staged versions)."""
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    layout.restart_request.write_text("restart", encoding="utf-8")


def notifications_dir(layout: InstallLayout) -> Path:
    """File inbox the app writes and the launcher tray drains (same pattern as ``restart_request``)."""
    return layout.state_dir / NOTIFICATIONS_DIR_NAME


def notification_id(event: str, project_id: str, key: str) -> str:
    """Stable id of one ``(event, project, key)``; the same id is never delivered twice."""
    material = f"{event}|{project_id}|{key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def sent_notifications(layout: InstallLayout) -> list[str]:
    """Ids already delivered to the tray, oldest first (corrupt/missing ledger reads as empty)."""
    path = notifications_dir(layout) / SENT_NOTIFICATIONS_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, str)][-SENT_NOTIFICATIONS_LIMIT:]


def record_sent_notification(layout: InstallLayout, notification: str) -> None:
    """Append one delivered id to the ledger, FIFO-trimmed and written atomically."""
    directory = notifications_dir(layout)
    directory.mkdir(parents=True, exist_ok=True)
    ids = [item for item in sent_notifications(layout) if item != notification]
    ids.append(notification)
    path = directory / SENT_NOTIFICATIONS_FILE
    temp = directory / f"{SENT_NOTIFICATIONS_FILE}.tmp"
    temp.write_text(
        json.dumps(ids[-SENT_NOTIFICATIONS_LIMIT:], ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temp, path)


def status(layout: InstallLayout) -> dict[str, Any]:
    payload = BootState(layout).status()
    payload["staged"] = staged_versions(layout)
    return payload
