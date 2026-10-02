# -*- coding: utf-8 -*-
"""Frozen/source runtime path regression tests."""

from __future__ import annotations

from pathlib import Path

import core.runtime_paths as runtime_paths


def test_frozen_app_root_is_writable_executable_directory(monkeypatch, tmp_path: Path) -> None:
    exe_dir = tmp_path / "VSE-WebUI"
    exe_dir.mkdir()
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(exe_dir / "VSE-WebUI.exe"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert runtime_paths.app_root() == exe_dir.resolve()
    assert not (exe_dir / "data" / ".write_probe").exists()
