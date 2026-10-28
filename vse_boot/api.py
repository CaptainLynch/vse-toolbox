# -*- coding: utf-8 -*-
"""Small, stable entry points shared by the launcher CLI and the running app.

The app (``plugins/settings``) may import this module: it is part of the
runtime layer and does not depend on app code. Everything here works on an
install root; inside the app it comes from ``VSE_INSTALL_ROOT``, which the
supervisor sets for the app process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from vse_boot.discover import Candidate, find_updates
from vse_boot.layout import InstallLayout
from vse_boot.packages import load_trusted_keys, stage_app, verify_app_package
from vse_boot.state import BootState

RUNTIME_KEYS = Path(__file__).resolve().parent / "trusted_keys.json"


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


def status(layout: InstallLayout) -> dict[str, Any]:
    payload = BootState(layout).status()
    payload["staged"] = staged_versions(layout)
    return payload
