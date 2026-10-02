# -*- coding: utf-8 -*-
"""Runtime path helpers for source and PyInstaller builds."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def app_root() -> Path:
    """Return the writable application root.

    In source runs this is the repository root. In a PyInstaller single-file
    build this is the directory containing the generated executable, not the
    temporary extraction directory.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [exe_dir]

        for env_name in ("LOCALAPPDATA", "APPDATA"):
            env_value = os.environ.get(env_name)
            if env_value:
                candidates.append(Path(env_value) / "VSE-Toolbox")

        candidates.append(Path.home() / "VSE-Toolbox")
        candidates.append(Path(tempfile.gettempdir()) / "VSE-Toolbox")

        for candidate in candidates:
            if _can_write_data_dir(candidate):
                return candidate

        return exe_dir
    return Path(__file__).resolve().parent.parent


def _can_write_data_dir(root: Path) -> bool:
    data_dir = root / "data"
    probe = data_dir / ".write_probe"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        return False
    return True
