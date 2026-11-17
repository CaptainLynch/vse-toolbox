# -*- coding: utf-8 -*-
"""Child process entry: run one installed app version as a source tree.

The app version lives as plain ``.py`` files under ``app/<version>/``. It runs
exactly like a source checkout (``sys.frozen`` is cleared in a frozen launcher),
so every ``Path(__file__)``-relative lookup in the app keeps working; only the
data root comes from ``VSE_DATA_ROOT`` (set by the supervisor).
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
from pathlib import Path


def _enter_app(app_dir: Path) -> None:
    if getattr(sys, "frozen", False):
        # 运行时是冻结的启动器，但 app 本身是源码目录：按源码方式解析路径。
        sys.frozen = False  # type: ignore[attr-defined]
    os.environ["VSE_APP_DIR"] = str(app_dir)
    try:
        # core/version.py 的第 2 优先级：让界面显示真实的版本号。
        meta = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
        os.environ.setdefault("VSE_TOOLBOX_VERSION", str(meta["version"]))
    except (OSError, ValueError, KeyError):
        pass
    sys.path.insert(0, str(app_dir))
    os.chdir(app_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vse_boot.app_main")
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    app_dir = Path(args.app_dir).resolve()
    _enter_app(app_dir)
    import webui  # noqa: PLC0415 - resolved from the app directory just inserted

    return int(webui.main(["--port", str(args.port), "--no-browser"]) or 0)


def run_app_script(script: Path, argv: list[str]) -> int:
    """Act as ``python <script> <args>`` for an app script (e.g. the Excel worker CLI)."""
    script = script.resolve()
    # 只执行当前 app 版本目录里的脚本：启动器不能被当成通用的 Python 解释器使用。
    app_dir_env = os.environ.get("VSE_APP_DIR", "")
    if not app_dir_env:
        print("拒绝执行：不在 VSE Toolbox 程序内")
        return 2
    app_dir = Path(app_dir_env).resolve()
    if app_dir not in script.parents:
        print("拒绝执行：脚本不在当前程序目录内")
        return 2
    _enter_app(app_dir)
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *argv]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0) if not isinstance(exc.code, str) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
