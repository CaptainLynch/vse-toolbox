# -*- coding: utf-8 -*-
"""Find update packages the user received (e.g. Feishu saves them to Downloads).

Only ``*.vsepkg`` file names are listed; no other file is opened. A package is
offered only after its signature verifies, and installing it always needs the
user's confirmation (architecture §4.2, review R7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from vse_boot.layout import version_tuple
from vse_boot.packages import PACKAGE_SUFFIX, PackageError, peek_manifest, verify_app_package

_MAX_CANDIDATE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class Candidate:
    path: Path
    kind: str  # "app" | "plugin"
    version: str | None
    notes: str
    size: int


def default_watch_dirs() -> list[Path]:
    downloads = Path.home() / "Downloads"
    return [downloads] if downloads.is_dir() else []


def find_updates(
    folders: Iterable[Path],
    keys: Mapping[str, bytes],
    *,
    current_app_version: str | None,
    runtime_tag: str | None = None,
) -> list[Candidate]:
    """App packages newer than ``current_app_version`` (newest first), plus plugin packages.

    Plugin packages (format 1) are returned unverified with ``kind="plugin"``;
    the app's own plugin updater verifies them when the user imports them.
    """
    apps: dict[str, Candidate] = {}
    plugins: list[Candidate] = []
    unverified: list[tuple[tuple[int, int, int], Path, int, bytes]] = []
    for folder in folders:
        if not Path(folder).is_dir():
            continue
        for path in Path(folder).glob(f"*{PACKAGE_SUFFIX}"):
            try:
                size = path.stat().st_size
                if not path.is_file() or size > _MAX_CANDIDATE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            manifest = peek_manifest(data) or {}
            if manifest.get("format") == 1:
                plugins.append(Candidate(path=path, kind="plugin", version=None, notes="", size=size))
                continue
            if manifest.get("format") != 2:
                continue
            # 先按未校验的版本号过滤和排序，只对真正可能用到的包做完整校验（解压 + 逐文件哈希）。
            try:
                claimed = version_tuple(str(manifest.get("version")))
            except ValueError:
                continue
            if current_app_version and claimed <= version_tuple(current_app_version):
                continue
            unverified.append((claimed, path, size, data))
    kwargs = {"runtime_tag": runtime_tag} if runtime_tag else {}
    for claimed, path, size, data in sorted(unverified, key=lambda item: item[0], reverse=True):
        if ".".join(map(str, claimed)) in apps:
            continue  # 同一版本被下载了多次（"(1)""(2)" 副本）只校验、只保留一个
        try:
            verified = verify_app_package(data, keys, **kwargs)
        except PackageError:
            continue
        apps.setdefault(verified.version, Candidate(path=path, kind="app", version=verified.version, notes=verified.notes, size=size))
    ordered = sorted(apps.values(), key=lambda c: version_tuple(c.version or "0.0.0"), reverse=True)
    return ordered + sorted(plugins, key=lambda c: c.path.name)
