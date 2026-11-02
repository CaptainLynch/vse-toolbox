# -*- coding: utf-8 -*-
"""Tray icon for the supervisor (pystray + Pillow, both in the runtime layer).

Closing the app window does not stop VSE Toolbox; the tray is where the user
reopens it, checks for updates, restarts or quits (architecture §5.3).

The tray also drains the app → launcher notification inbox (DSH-V2-28): the app
process writes ``state/notifications/<id>.json`` and this process consumes it
through :meth:`TrayHandle.notify`. The poller is plain Python (no pystray) so it
is unit-testable; only :func:`start_tray` touches pystray/Pillow.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from vse_boot.api import (
    NOTIFICATION_EVENTS,
    SENT_NOTIFICATIONS_FILE,
    available_updates,
    notification_id,
    notifications_dir,
    record_sent_notification,
    sent_notifications,
)

if TYPE_CHECKING:
    from vse_boot.layout import InstallLayout
    from vse_boot.supervisor import Supervisor

logger = logging.getLogger("vse_toolbox.tray")

UPDATES_ROUTE = "#p/settings/updates"

#: Inbox drain interval and update scan interval (seconds); injectable for tests.
NOTIFICATION_INTERVAL_SECONDS = 5.0
UPDATE_INTERVAL_SECONDS = 600.0
#: A balloon that keeps failing is dropped (recorded as sent) after this many attempts.
NOTIFICATION_ATTEMPTS = 3
#: Bad message files are parked here instead of being retried forever.
BAD_DIR_NAME = "bad"
#: Update notifications reuse the frozen ``update_found`` event.
UPDATE_EVENT = "update_found"
UPDATE_PROJECT_ID = "app"
UPDATE_TITLE = "发现新版本"

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


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
    def __init__(self, icon: Any, poller: "TrayNotificationPoller | None" = None) -> None:
        self._icon = icon
        self._poller = poller

    def notify(self, text: str) -> None:
        self._icon.notify(text, "VSE Toolbox")

    def attach_poller(self, poller: "TrayNotificationPoller") -> None:
        self._poller = poller

    def stop(self) -> None:
        if self._poller is not None:
            self._poller.stop()
        self._icon.stop()


class TrayNotificationPoller:
    """Drain the notification inbox into the tray and scan for new app versions.

    Started as a daemon thread by :func:`start_tray`. Every step is a public
    method so tests can drive it directly with a fake icon and fake clock.
    """

    def __init__(
        self,
        layout: "InstallLayout",
        handle: Any,
        *,
        interval: float = NOTIFICATION_INTERVAL_SECONDS,
        update_interval: float = UPDATE_INTERVAL_SECONDS,
        stop_event: threading.Event | None = None,
        available_updates_fn: Callable[[Any], list[Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._layout = layout
        self._handle = handle
        self._interval = interval
        self._update_interval = update_interval
        self._stop = stop_event or threading.Event()
        self._available_updates = available_updates_fn or available_updates
        self._clock = clock
        self._next_update = 0.0
        self._attempts: dict[str, int] = {}
        self._thread: threading.Thread | None = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self.run, name="vse-tray-notifications", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - the poll loop must survive any file
                logger.warning("tray notification poll failed: %s", type(exc).__name__)
            if self._stop.wait(self._interval):
                break

    def poll_once(self) -> None:
        """One poll cycle: update scan when due, then drain the inbox."""
        now = self._clock()
        if now >= self._next_update:
            self._next_update = now + self._update_interval
            self.check_updates()
        self.scan_once()

    # ── inbox drain ────────────────────────────────────────────────────

    def scan_once(self) -> int:
        """Deliver every valid message file once; return the number delivered."""
        directory = notifications_dir(self._layout)
        if not directory.is_dir():
            return 0
        delivered = 0
        already_sent = set(sent_notifications(self._layout))
        for path in sorted(directory.glob("*.json")):
            if path.name == SENT_NOTIFICATIONS_FILE:
                continue
            delivered += self._consume(path, already_sent)
        return delivered

    def _consume(self, path: Path, already_sent: set[str]) -> int:
        payload = self._load(path)
        if payload is None:
            self._quarantine(path)
            return 0
        message_id = payload["id"]
        if message_id in already_sent:
            # Crash between ledger write and file delete: never pop the same balloon twice.
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("tray notification cleanup failed: %s", type(exc).__name__)
            return 0
        text = f"{payload['title']}：{payload['body']}"
        try:
            self._handle.notify(text)
        except Exception as exc:  # noqa: BLE001 - a failed balloon is retried, then dropped
            attempts = self._attempts.get(message_id, 0) + 1
            self._attempts[message_id] = attempts
            logger.warning(
                "tray notification failed (%s/%s): %s",
                attempts,
                NOTIFICATION_ATTEMPTS,
                type(exc).__name__,
            )
            if attempts >= NOTIFICATION_ATTEMPTS:
                self._attempts.pop(message_id, None)
                self._deliver(path, message_id)
            return 0
        self._attempts.pop(message_id, None)
        self._deliver(path, message_id)
        return 1

    @staticmethod
    def _load(path: Path) -> dict[str, Any] | None:
        """Parse and validate one message file; ``None`` means it is a bad file."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        message_id = payload.get("id")
        if not isinstance(message_id, str) or not _ID_RE.match(message_id):
            return None
        if payload.get("event") not in NOTIFICATION_EVENTS:
            return None
        for field in ("projectId", "title", "body", "createdAt"):
            if not isinstance(payload.get(field), str):
                return None
        if not payload["title"].strip():
            return None
        return payload

    def _deliver(self, path: Path, message_id: str) -> None:
        """Record the id in the ledger, then delete the message file."""
        try:
            record_sent_notification(self._layout, message_id)
        except Exception as exc:  # noqa: BLE001 - keep the file so the next tick retries
            logger.warning("tray notification ledger write failed: %s", type(exc).__name__)
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("tray notification cleanup failed: %s", type(exc).__name__)

    def _quarantine(self, path: Path) -> None:
        directory = notifications_dir(self._layout) / BAD_DIR_NAME
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / path.name
            if target.exists():
                target = directory / f"{path.stem}-{int(time.time() * 1000)}{path.suffix}"
            os.replace(path, target)
            logger.warning("tray notification moved to bad/: %s", path.name)
        except OSError as exc:
            logger.warning("tray notification quarantine failed: %s", type(exc).__name__)

    # ── update discovery ──────────────────────────────────────────────

    def check_updates(self) -> int:
        """Publish one local notification per newly available app version."""
        try:
            candidates = list(self._available_updates(self._layout))
        except Exception as exc:  # noqa: BLE001 - a broken scan must not stop the poller
            logger.warning("update check failed: %s", type(exc).__name__)
            return 0
        published = 0
        for candidate in candidates:
            version = str(getattr(candidate, "version", "") or "")
            if not _VERSION_RE.match(version):
                continue
            try:
                if self._publish_update(version):
                    published += 1
            except Exception as exc:  # noqa: BLE001 - one version must not stop the rest
                logger.warning("update notification failed: %s", type(exc).__name__)
        return published

    def _publish_update(self, version: str) -> bool:
        """Write the frozen ``update_found`` message file (dedupe by ledger + file).

        The launcher process has no app layer (``services``/``core``), so the same
        frozen file format is written here instead of importing the publisher.
        """
        message_id = notification_id(UPDATE_EVENT, UPDATE_PROJECT_ID, version)
        directory = notifications_dir(self._layout)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{message_id}.json"
        if target.exists() or message_id in set(sent_notifications(self._layout)):
            return False
        payload = {
            "id": message_id,
            "event": UPDATE_EVENT,
            "projectId": UPDATE_PROJECT_ID,
            "title": UPDATE_TITLE,
            "body": f"{version} 已就绪，可在托盘菜单检查更新",
            "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        temp = directory / f"{message_id}.json.tmp"
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)
        return True


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
    handle = TrayHandle(icon)
    poller = TrayNotificationPoller(supervisor.layout, handle)
    handle.attach_poller(poller)
    poller.start()
    return handle


__all__ = [
    "NOTIFICATION_ATTEMPTS",
    "NOTIFICATION_INTERVAL_SECONDS",
    "UPDATE_INTERVAL_SECONDS",
    "TrayHandle",
    "TrayNotificationPoller",
    "start_tray",
]
