# -*- coding: utf-8 -*-
"""Command line / launcher entry.

    python -m vse_boot [run] [--root DIR]      start (default)
    python -m vse_boot stage FILE [--root DIR] verify and stage an app package
    python -m vse_boot status [--root DIR]
    python -m vse_boot rollback [--root DIR]   back to the previous version at next start

The frozen launcher (``VSE-Toolbox.exe``) also routes two internal forms:
``--app-child --app-dir D --port P`` (the app child process) and
``<app>/…/script.py args`` (the app asking for "python script.py", e.g. the
Excel worker).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
from pathlib import Path

from vse_boot.discover import find_updates
from vse_boot.layout import InstallLayout
from vse_boot.packages import PackageError, load_trusted_keys, stage_app, verify_app_package
from vse_boot.state import BootState, BootStateError

RUNTIME_KEYS = Path(__file__).resolve().parent / "trusted_keys.json"


def default_root() -> Path:
    env = os.environ.get("VSE_INSTALL_ROOT", "").strip()
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # 便携模式只在明确声明（portable.flag）或该目录已经是安装根时启用。
        # 否则统一用 %LOCALAPPDATA%\VSE-Toolbox：用户直接在「下载」里双击、或者下载了多份副本，
        # 数据都只落在一个地方，不会再散落到「下载」文件夹里。
        if (exe_dir / "portable.flag").is_file() or (exe_dir / "state" / "boot.json").is_file():
            return exe_dir
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "VSE-Toolbox"


def trusted_keys(layout: InstallLayout) -> dict[str, bytes]:
    """Keys shipped with the runtime, plus keys the current app version ships (rotation)."""
    paths = [RUNTIME_KEYS]
    current = BootState(layout).app.get("current")
    if current:
        paths.append(layout.app_dir(current) / "host" / "trusted_keys.json")
    return load_trusted_keys(paths)


def stage_file(layout: InstallLayout, path: Path) -> str:
    verified = verify_app_package(path.read_bytes(), trusted_keys(layout))
    stage_app(verified, layout)
    return verified.version


def _first_install(layout: InstallLayout) -> None:
    """No version installed yet: install the newest app package next to the launcher or in Downloads."""
    state = BootState(layout)
    if state.app["current"] or any(layout.staging_dir.glob("app-*")):
        return
    folders = [layout.root]
    if getattr(sys, "frozen", False):
        folders.insert(0, Path(sys.executable).resolve().parent)
    folders.append(Path.home() / "Downloads")
    candidates = [c for c in find_updates(folders, trusted_keys(layout), current_app_version=None) if c.kind == "app"]
    if candidates:
        version = stage_file(layout, candidates[0].path)
        print(f"首次安装：找到程序包 {candidates[0].path.name}（{version}）")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--app-child"]:
        from vse_boot.app_main import main as app_main

        return app_main(argv[1:])
    if argv and argv[0].lower().endswith(".py"):
        from vse_boot.app_main import run_app_script

        return run_app_script(Path(argv[0]), argv[1:])

    parser = argparse.ArgumentParser(prog="vse_boot", description="VSE Toolbox 启动与更新")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "stage", "status", "rollback"])
    parser.add_argument("file", nargs="?")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    layout = InstallLayout(Path(args.root) if args.root else default_root()).ensure()

    if args.command == "stage":
        if not args.file:
            parser.error("stage 需要更新包路径")
        try:
            version = stage_file(layout, Path(args.file))
        except (PackageError, OSError) as exc:
            _file_logger(layout)(f"无法安装 {Path(args.file).name}：{exc}")
            return 1
        _file_logger(layout)(f"已校验并暂存 {version}，下次启动时生效")
        return 0
    if args.command == "status":
        print(json.dumps(BootState(layout).status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "rollback":
        try:
            version = BootState(layout).rollback()
        except BootStateError as exc:
            print(exc)
            return 1
        print(f"下次启动将使用 {version}")
        return 0

    from vse_boot.supervisor import Supervisor, open_window

    log = _file_logger(layout)
    try:
        _first_install(layout)
    except (PackageError, OSError) as exc:
        log(f"首次安装失败：{exc}")
    show = open_window
    if os.environ.get("VSE_BOOT_NO_WINDOW"):
        # 自动化测试 / 无人值守：不打开窗口，只记录地址。
        show = lambda url, _layout: log(f"就绪：{url}")  # noqa: E731
    return Supervisor(layout, show=show, log=log).run()


def _file_logger(layout: InstallLayout):  # type: ignore[no-untyped-def]
    """Launcher messages go to ``state/launcher.log`` (the windowed exe has no console)."""
    path = layout.state_dir / "launcher.log"

    def log(message: str) -> None:
        from datetime import datetime

        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        print(line)
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    return log


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
