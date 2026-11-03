# -*- coding: utf-8 -*-
"""应用进程 → 启动器托盘的本地通知发布端（DSH-V2-28）。

冻结契约（主控）：托盘在启动器进程内运行，应用进程只往
``layout.state_dir/notifications`` 写消息文件（``<id>.json``），启动器轮询后调用
``TrayHandle.notify``；已送达的 id 记在 ``sent.json``（最多 500 个，FIFO 截断）。

边界（勿破）：
- 不引入通知服务、不开端口、不用命名管道；复用既有 ``restart_request`` 文件旗标模式。
- 未由启动器托管（没有 ``VSE_INSTALL_ROOT``）时没有托盘：静默返回 ``False``。
- 任何 I/O 异常只记日志并返回 ``False``，绝不抛出、绝不阻塞调用方主流程。
- 只允许稳定分类文案：标题/正文经 ``core.redaction.redact_sensitive_text`` 脱敏并
  限长，另去掉 URL 与本地路径（错误原文、账号、路径不得进入托盘气泡）。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.redaction import redact_sensitive_text
#: 应用包可能运行在旧版启动器之上（分层更新：只装 app 包、不换启动器）。旧启动器的
#: ``vse_boot.api`` 没有通知收件箱接口——导入失败时通知整体关闭（等同未托管），
#: 绝不让应用因此启动失败。
try:
    from vse_boot.api import (
        NOTIFICATION_EVENTS,
        managed_layout,
        notification_id,
        notifications_dir,
        sent_notifications,
    )

    LAUNCHER_SUPPORTS_NOTIFICATIONS = True
except ImportError:  # 旧启动器：缺少 DSH-V2-28 的收件箱接口
    NOTIFICATION_EVENTS = frozenset({"sync_failed", "daily_ready", "update_found"})
    managed_layout = notification_id = notifications_dir = sent_notifications = None  # type: ignore[assignment]
    LAUNCHER_SUPPORTS_NOTIFICATIONS = False

if TYPE_CHECKING:
    from vse_boot.layout import InstallLayout

logger = logging.getLogger("vse_toolbox.user_notifications")

#: 事件闭集：与 ``vse_boot.api.NOTIFICATION_EVENTS`` 同一份冻结契约。
EVENTS = NOTIFICATION_EVENTS

#: 托盘气泡的长度上限（字符）。
TITLE_LIMIT = 40
BODY_LIMIT = 200

_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://\S+")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:\\[^\s]*")


def _stable_text(value: object, limit: int) -> str:
    """脱敏、去链接/路径、压成单行并限长；只用于稳定分类文案。"""
    text = redact_sensitive_text(value, collapse_newlines=True)
    text = _URL_RE.sub("[链接已省略]", text)
    text = _WINDOWS_PATH_RE.sub("[路径已省略]", text)
    return text[:limit]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish(
    event: str,
    *,
    project_id: str,
    key: str,
    title: str,
    body: str,
    layout: "InstallLayout | None" = None,
) -> bool:
    """Publish one tray notification; return ``True`` only when a new file was written.

    Dedupe is global per ``(event, project_id, key)``: an existing message file or an
    id already in the delivery ledger counts as published (``False``).
    """
    if event not in EVENTS:
        raise ValueError(f"unsupported notification event: {event}")
    if not LAUNCHER_SUPPORTS_NOTIFICATIONS:
        return False
    try:
        target_layout = layout if layout is not None else managed_layout()
        if target_layout is None:
            return False
        project = str(project_id)
        message_id = notification_id(event, project, str(key))
        directory = Path(notifications_dir(target_layout))
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{message_id}.json"
        if target.exists() or message_id in set(sent_notifications(target_layout)):
            return False
        payload = {
            "id": message_id,
            "event": event,
            "projectId": project,
            "title": _stable_text(title, TITLE_LIMIT),
            "body": _stable_text(body, BODY_LIMIT),
            "createdAt": _utc_now(),
        }
        temp = directory / f"{message_id}.json.tmp"
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)
        return True
    except Exception as exc:  # noqa: BLE001 - notifications must never break the caller
        logger.warning("tray notification publish failed (%s): %s", event, type(exc).__name__)
        return False


__all__ = ["BODY_LIMIT", "EVENTS", "TITLE_LIMIT", "publish"]
