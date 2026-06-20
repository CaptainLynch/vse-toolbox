# -*- coding: utf-8 -*-
"""Runtime path helpers for source and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Return the writable application root.

    In source runs this is the repository root. In a PyInstaller single-file
    build this is the directory containing the generated executable, not the
    temporary extraction directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
