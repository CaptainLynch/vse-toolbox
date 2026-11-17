# -*- coding: utf-8 -*-
"""Directory layout under one install root."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def version_tuple(version: str) -> tuple[int, int, int]:
    if not _VERSION_PATTERN.match(version or ""):
        raise ValueError(f"版本号无效: {version}")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


@dataclass(frozen=True)
class InstallLayout:
    root: Path

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def apps_dir(self) -> Path:
        return self.root / "app"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def staging_dir(self) -> Path:
        return self.state_dir / "staging"

    @property
    def snapshots_dir(self) -> Path:
        return self.state_dir / "db-snapshots"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "boot.json"

    @property
    def instance_file(self) -> Path:
        return self.state_dir / "instance.json"

    @property
    def restart_request(self) -> Path:
        return self.state_dir / "restart.request"

    @property
    def quit_request(self) -> Path:
        return self.state_dir / "quit.request"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "instance.lock"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def database(self) -> Path:
        return self.data_dir / "vse_toolbox.db"

    def app_dir(self, version: str) -> Path:
        version_tuple(version)
        return self.apps_dir / version

    def installed_app_versions(self) -> list[str]:
        if not self.apps_dir.is_dir():
            return []
        found = [p.name for p in self.apps_dir.iterdir() if p.is_dir() and _VERSION_PATTERN.match(p.name)]
        return sorted(found, key=version_tuple)

    def ensure(self) -> "InstallLayout":
        for path in (self.apps_dir, self.staging_dir, self.snapshots_dir, self.data_dir):
            path.mkdir(parents=True, exist_ok=True)
        return self
