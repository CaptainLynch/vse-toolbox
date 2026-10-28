# -*- coding: utf-8 -*-
"""Tray icon for the supervisor (pystray + Pillow, both in the runtime layer).

Closing the app window does not stop VSE Toolbox; the tray is where the user
reopens it, checks for updates, restarts or quits (architecture §5.3).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vse_boot.supervisor import Supervisor

UPDATES_ROUTE = "#p/settings/updates"


def _icon_image() -> Any:
    from PIL import Image, ImageDraw, ImageFont

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, size - 2, size - 2), radius=14, fill=(196, 103, 63, 255))
    try:
        font = ImageFont.truetype("seguisb.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2 + 1), "V", fill=(255, 255, 255, 255), font=font, anchor="mm")
    return image


class TrayHandle:
    def __init__(self, icon: Any) -> None:
        self._icon = icon

    def notify(self, text: str) -> None:
        self._icon.notify(text, "VSE Toolbox")

    def stop(self) -> None:
        self._icon.stop()


def start_tray(supervisor: "Supervisor") -> TrayHandle:
    import pystray

    def open_app(_icon: Any = None, _item: Any = None) -> None:
        if supervisor.url:
            supervisor.show(supervisor.url, supervisor.layout)

    def open_updates(_icon: Any = None, _item: Any = None) -> None:
        if supervisor.url:
            supervisor.show(supervisor.url + UPDATES_ROUTE, supervisor.layout)

    def restart(_icon: Any = None, _item: Any = None) -> None:
        supervisor.controls.restart.set()

    def quit_app(icon: Any, _item: Any = None) -> None:
        supervisor.controls.quit.set()
        icon.stop()

    def title(_item: Any) -> str:
        return f"VSE Toolbox {supervisor.version or ''}".strip()

    menu = pystray.Menu(
        pystray.MenuItem(title, open_app, default=True),
        pystray.MenuItem("检查更新", open_updates),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("重新启动", restart),
        pystray.MenuItem("退出（不再自动同步）", quit_app),
    )
    icon = pystray.Icon("vse-toolbox", _icon_image(), "VSE Toolbox", menu)
    threading.Thread(target=icon.run, name="vse-tray", daemon=True).start()
    return TrayHandle(icon)
