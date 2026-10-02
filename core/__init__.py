# -*- coding: utf-8 -*-
"""Core package exports.

Keep package import lightweight.  Several small utilities such as redaction and
runtime paths are intentionally usable without loading SQLite or creating a
database connection.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DatabaseManager"]


def __getattr__(name: str) -> Any:
    if name == "DatabaseManager":
        from core.db_manager import DatabaseManager

        return DatabaseManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
