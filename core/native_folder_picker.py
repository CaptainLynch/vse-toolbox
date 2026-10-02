# -*- coding: utf-8 -*-
"""Optional native Windows folder picker for the local WebUI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class NativeFolderPickerError(RuntimeError):
    """The local process cannot open a native folder picker."""


def choose_native_folder(initial_directory: Path | str | None = None) -> Path | None:
    """Open a native directory dialog and return the selected local directory."""
    if os.name != "nt":
        raise NativeFolderPickerError("native Windows folder picker is unavailable")
    try:
        import tkinter as tk
        from tkinter import filedialog
    except (ImportError, OSError) as exc:
        raise NativeFolderPickerError("native Windows folder picker is unavailable") from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        options: dict[str, object] = {
            "title": "选择归档文件夹",
            "mustexist": True,
        }
        if initial_directory:
            options["initialdir"] = str(Path(initial_directory).expanduser().absolute())
        askdirectory: Any = filedialog.askdirectory
        selected = askdirectory(**options)
        if not selected:
            return None
        return Path(str(selected)).expanduser().absolute()
    except Exception as exc:
        raise NativeFolderPickerError("无法打开 Windows 文件夹选择器") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


__all__ = ["NativeFolderPickerError", "choose_native_folder"]
