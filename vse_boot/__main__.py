# -*- coding: utf-8 -*-
"""Command line / launcher entry.

    python -m vse_boot [run] [--root DIR]      start (default)
    python -m vse_boot open FILE [--root DIR]  double-clicked .vsepkg: verify, stage, offer a restart
    python -m vse_boot stage FILE [--root DIR] verify and stage an app package (no dialogs)
    python -m vse_boot status [--root DIR]
    python -m vse_boot rollback [--root DIR]   back to the previous version at next start
    python -m vse_boot restart|quit [--root DIR]  ask the running instance to restart / quit

The frozen launcher (``VSE-Toolbox.exe``) also routes two internal forms:
``--app-child --app-dir D --port P`` (the app child process) and
``--window URL --profile DIR`` (the pywebview window child process, so that
``webview.start()`` runs on a process main thread), and
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

from vse_boot import api
from vse_boot.discover import find_updates
from vse_boot.layout import InstallLayout
from vse_boot.packages import PackageError
from vse_boot.state import BootState, BootStateError

# 兼容旧名称（测试与工具引用）
trusted_keys = api.trusted_keys
stage_file = api.stage_file


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


def _first_install(layout: InstallLayout, log) -> None:  # type: ignore[no-untyped-def]
    """No version installed yet: install the newest app package next to the launcher or in Downloads."""
    state = BootState(layout)
    if state.app["current"] or api.staged_versions(layout):
        return
    candidates = [c for c in find_updates(api.watch_dirs(layout), api.trusted_keys(layout), current_app_version=None) if c.kind == "app"]
    if candidates:
        version = api.stage_file(layout, candidates[0].path)
        log(f"首次安装：找到程序包 {candidates[0].path.name}（{version}）")


def _is_running(layout: InstallLayout) -> bool:
    from vse_boot.supervisor import InstanceLock

    lock = InstanceLock(layout.lock_file)
    if lock.acquire():
        lock.release()
        return False
    return True


def _open_package(layout: InstallLayout, path: Path, log) -> int:  # type: ignore[no-untyped-def]
    """Double-click flow: everything is a dialog, because the windowed exe has no console."""
    from vse_boot.association import ask

    try:
        version = api.stage_file(layout, path)
    except (PackageError, OSError) as exc:
        log(f"无法安装 {path.name}：{exc}")
        ask(f"无法安装这个更新包：\n{exc}", yes_no=False)
        return 1
    log(f"已校验并暂存 {version}（{path.name}）")
    if _is_running(layout):
        if ask(f"更新包校验通过：VSE Toolbox {version}。\n\n现在重启程序完成更新吗？（大约 10 秒）"):
            api.request_restart(layout)
        return 0
    if ask(f"更新包校验通过：VSE Toolbox {version}。\n\n现在启动 VSE Toolbox 吗？"):
        return _run(layout, log)
    return 0


def _run(layout: InstallLayout, log) -> int:  # type: ignore[no-untyped-def]
    from vse_boot.supervisor import Supervisor, open_window

    try:
        _first_install(layout, log)
    except (PackageError, OSError) as exc:
        log(f"首次安装失败：{exc}")
    headless = bool(os.environ.get("VSE_BOOT_NO_WINDOW"))
    if getattr(sys, "frozen", False) and not headless:
        try:
            from vse_boot.association import register

            if register(Path(sys.executable).resolve()):
                log("已关联 .vsepkg：以后双击更新包即可安装")
        except OSError as exc:
            log(f"无法关联 .vsepkg：{exc}")
    show = open_window
    tray = None
    if headless:
        # 自动化测试 / 无人值守：不打开窗口、不显示托盘，只记录地址。
        show = lambda url, _layout: log(f"就绪：{url}")  # noqa: E731
    else:
        try:
            from vse_boot.tray import start_tray

            tray = start_tray
        except ImportError:
            tray = None
    return Supervisor(layout, show=show, log=log, tray=tray).run()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--app-child"]:
        from vse_boot.app_main import main as app_main

        return app_main(argv[1:])
    if argv[:1] == ["--window"]:
        # pywebview 窗口子进程：start() 必须在本进程主线程，所以由这里直接跑（C1）。
        from vse_boot.supervisor import run_window

        return run_window(argv)
    if argv and argv[0].lower().endswith(".py"):
        from vse_boot.app_main import run_app_script

        return run_app_script(Path(argv[0]), argv[1:])

    parser = argparse.ArgumentParser(prog="vse_boot", description="VSE Toolbox 启动与更新")
    parser.add_argument(
        "command", nargs="?", default="run",
        choices=["run", "open", "stage", "status", "rollback", "restart", "quit"],
    )
    parser.add_argument("file", nargs="?")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    layout = InstallLayout(Path(args.root) if args.root else default_root()).ensure()
    log = _file_logger(layout)

    if args.command in ("open", "stage"):
        if not args.file:
            parser.error(f"{args.command} 需要更新包路径")
        if args.command == "open":
            return _open_package(layout, Path(args.file), log)
        try:
            version = api.stage_file(layout, Path(args.file))
        except (PackageError, OSError) as exc:
            log(f"无法安装 {Path(args.file).name}：{exc}")
            return 1
        log(f"已校验并暂存 {version}，下次启动时生效")
        return 0
    if args.command == "status":
        print(json.dumps(api.status(layout), ensure_ascii=False, indent=2))
        return 0
    if args.command == "rollback":
        try:
            version = BootState(layout).rollback()
        except BootStateError as exc:
            print(exc)
            return 1
        print(f"下次启动将使用 {version}")
        return 0
    if args.command == "restart":
        api.request_restart(layout)
        return 0
    if args.command == "quit":
        layout.state_dir.mkdir(parents=True, exist_ok=True)
        layout.quit_request.write_text("quit", encoding="utf-8")
        return 0
    return _run(layout, log)


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
