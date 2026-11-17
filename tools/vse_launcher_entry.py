# -*- coding: utf-8 -*-
"""PyInstaller entry for ``VSE-Toolbox.exe`` (see VSE-Launcher.spec)."""

import multiprocessing
import os
import sys
import traceback
from pathlib import Path

from vse_boot.__main__ import main


def _report_crash(exc: BaseException) -> None:
    """The windowed exe has no console and a traceback dialog would block forever.

    Write the traceback to stderr when it is redirected (the app child's stderr is
    ``state/app-last-run.log``) and to ``state/launcher-crash.log`` of the install.
    """
    text = "".join(traceback.format_exception(exc))
    if sys.stderr is not None:
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
    root = os.environ.get("VSE_INSTALL_ROOT")
    if not root:
        return
    try:
        state = Path(root) / "state"
        state.mkdir(parents=True, exist_ok=True)
        with open(state / "launcher-crash.log", "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    # freeze_support() 必须最先执行，避免 multiprocessing 的派生进程被当成一次启动。
    multiprocessing.freeze_support()
    try:
        code = main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - last-resort guard for the windowed exe
        _report_crash(exc)
        code = 1
    sys.exit(code)
