# -*- coding: utf-8 -*-
"""Consistent SQLite snapshots taken before a trial version runs its migrations."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

KEEP_SNAPSHOTS = 3


def snapshot(database: Path, snapshots_dir: Path, *, tag: str) -> Path | None:
    """Copy ``database`` with the online backup API; ``None`` when there is no database yet."""
    if not database.is_file():
        return None
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = snapshots_dir / f"{database.stem}-{stamp}-{tag}.db"
    source = sqlite3.connect(database)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    _prune(snapshots_dir, database.stem)
    return target


def restore(snapshot_file: Path, database: Path) -> None:
    """Overwrite ``database`` with ``snapshot_file`` (the app process must be stopped)."""
    source = sqlite3.connect(snapshot_file)
    try:
        dest = sqlite3.connect(database)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _prune(snapshots_dir: Path, stem: str) -> None:
    # 同一秒内的多份快照 mtime 可能相同，再按文件名（含时间戳）排序，保证留下的是最新的。
    files = sorted(snapshots_dir.glob(f"{stem}-*.db"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    for old in files[KEEP_SNAPSHOTS:]:
        old.unlink(missing_ok=True)
