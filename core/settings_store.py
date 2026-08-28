"""Validation for non-sensitive local application settings."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from core.db_manager import DatabaseManager


PATH_KEYS = ("archiveDirectory", "excelDirectory", "temporaryDirectory", "diagnosticDirectory")
INTEGER_LIMITS = {
    "defaultDownloadMinutes": (5, 10080),
    "retryCount": (0, 10),
    "dueSoonDays": (0, 365),
    "cacheSnapshotCount": (1, 365),
    "retentionDays": (1, 3650),
}
DEFAULTS: dict[str, object] = {
    "archiveDirectory": "",
    "excelDirectory": "",
    "temporaryDirectory": "",
    "diagnosticDirectory": "",
    "defaultDownloadMinutes": 60,
    "retryCount": 2,
    "dueSoonDays": 7,
    "cacheSnapshotCount": 30,
    "retentionDays": 90,
}


class SettingsValidationError(ValueError):
    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("settings are invalid")
        self.fields = dict(fields)


def validate_local_directory(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("必须是路径字符串")
    text = value.strip()
    if not text:
        return ""
    if text.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
        raise ValueError("仅允许本机普通目录")
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("必须是绝对本机目录")
    resolved = path.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("路径必须指向目录")
    return str(resolved)


class SettingsStore:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get(self) -> dict[str, object]:
        return {**DEFAULTS, **self._db.get_app_settings()}

    def update(self, payload: Mapping[str, object]) -> dict[str, object]:
        unknown = set(payload) - set(DEFAULTS)
        errors: dict[str, str] = {}
        if unknown:
            errors["request"] = "包含不支持的设置"
        checked: dict[str, object] = {}
        for key in PATH_KEYS:
            if key not in payload:
                continue
            try:
                checked[key] = validate_local_directory(payload[key])
            except ValueError as exc:
                errors[key] = str(exc)
        for key, (minimum, maximum) in INTEGER_LIMITS.items():
            if key not in payload:
                continue
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                errors[key] = f"必须是 {minimum} 到 {maximum} 的整数"
            else:
                checked[key] = value
        if errors:
            raise SettingsValidationError(errors)
        return {**DEFAULTS, **self._db.update_app_settings(checked)}
