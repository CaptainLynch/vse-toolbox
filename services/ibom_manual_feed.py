"""iBOM 报表手工导入暂存：代替**下一次**定时归档运行的 iBOM 自动抓取（方案 §6 用途 A）。

- 上传时就完整校验（表头变体 ``ibom``、行数上限）；不合格直接拒绝，不留半成品。
- 暂存一份，**只用一次**：归档连接器取走即删除；超过有效期（30 分钟）未被取走视为作废。
- 存放在数据目录 ``ibom_manual_feed/`` 下；插件与归档连接器用同一个默认目录。
- 手工文件没有 iBOM 的 ``totalCount`` 可核对，完整性由上传人确认的数据日期承担，并写进合并报告。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from services.tdc_official_rows import (
    VARIANT_IBOM,
    OfficialWorkbookContractError,
    OfficialWorkbookError,
    OfficialWorkbookTruncated,
    read_official_tdc_rows_from_bytes,
)

FEED_TTL = timedelta(minutes=30)
MAX_FEED_BYTES = 32 * 1024 * 1024
MAX_FEED_ROWS = 10001
_CONTENT = "pending.bin"
_META = "pending.json"
_ENCRYPTED_REASONS = {"encrypted_container", "ole_container"}


class ManualFeedError(ValueError):
    """上传的文件不能作为 iBOM 手工数据。``code`` 是前端可映射的闭集码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ManualFeed:
    content: bytes
    file_name: str
    data_date: str
    text: bool
    sha256: str
    uploaded_at: str


FEED_DIR_NAME = "ibom_manual_feed"


def feed_dir_for(data_dir: Path | str) -> Path:
    """暂存目录 = 数据目录（数据库所在目录）/ ``ibom_manual_feed``；插件与归档运行器共用这一规则。"""
    return Path(data_dir) / FEED_DIR_NAME


def default_feed_dir() -> Path:
    from core.config import DATA_DIR

    return feed_dir_for(DATA_DIR)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_text_name(name: str) -> bool:
    return name.lower().endswith(".txt")


def parse_feed_rows(content: bytes, *, text: bool) -> tuple[dict[str, object], ...]:
    """按 iBOM 表头变体读入；失败映射为 ``ManualFeedError``。"""
    try:
        return read_official_tdc_rows_from_bytes(
            content, "data_model", max_rows=MAX_FEED_ROWS, text=text, strict=True, variant=VARIANT_IBOM
        )
    except OfficialWorkbookTruncated:
        raise ManualFeedError("E_TOO_MANY_ROWS", "行数超过上限") from None
    except OfficialWorkbookContractError:
        raise ManualFeedError(
            "E_HEADER_MISMATCH", "表头与 iBOM「数模设计审核流程报表」不一致（第一列应为「序号」，其余 46 列与 TDC 相同）"
        ) from None
    except OfficialWorkbookError as exc:
        if str(getattr(exc, "reason", "")) in _ENCRYPTED_REASONS:
            raise ManualFeedError(
                "E_ENCRYPTED",
                "文件受终端加密，程序读不到内容。请用 Excel 打开后「另存为 → Unicode 文本 (*.txt)」再上传。",
            ) from None
        raise ManualFeedError("E_UNREADABLE", "文件读不出来（不是有效的 xlsx 或 Unicode 文本）") from None


class IBOMManualFeedStore:
    def __init__(self, directory: Path | None = None, *, clock: Callable[[], datetime] = _now) -> None:
        self._directory = Path(directory) if directory is not None else None
        self._clock = clock

    @property
    def directory(self) -> Path:
        return self._directory if self._directory is not None else default_feed_dir()

    def put(self, content: bytes, *, file_name: str, data_date: date) -> dict[str, object]:
        if not content:
            raise ManualFeedError("E_EMPTY", "文件是空的")
        if len(content) > MAX_FEED_BYTES:
            raise ManualFeedError("E_TOO_LARGE", "文件超过大小上限")
        if not isinstance(data_date, date):
            raise ManualFeedError("E_DATE_REQUIRED", "需要确认这份报表的数据日期")
        today = self._clock().astimezone().date()
        if data_date > today:
            raise ManualFeedError("E_DATE_FUTURE", "数据日期不能晚于今天")
        # 浏览器可能带上客户端路径（Windows 反斜杠）：两种分隔符都去掉，只留文件名。
        name = re.split(r"[\\/]", str(file_name or "").strip())[-1][:120] or "ibom.xlsx"
        text = _is_text_name(name)
        rows = parse_feed_rows(content, text=text)
        if not rows:
            raise ManualFeedError("E_EMPTY", "报表里没有数据行")
        meta = {
            "fileName": name,
            "dataDate": data_date.isoformat(),
            "text": text,
            "sha256": hashlib.sha256(content).hexdigest(),
            "uploadedAt": self._clock().astimezone(timezone.utc).isoformat(),
            "rows": len(rows),
            "documents": len({str(row.get("流水单号") or "").strip() for row in rows} - {""}),
        }
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        self._atomic_write(directory / _CONTENT, content)
        self._atomic_write(directory / _META, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        return meta

    def pending(self) -> dict[str, object] | None:
        """当前待用的暂存元数据（过期的视为没有）；不取走。"""
        meta = self._read_meta()
        if meta is None or self._expired(meta):
            return None
        return meta

    def take(self) -> ManualFeed | None:
        """取走并删除暂存；没有、过期或文件被篡改都返回 None（过期/篡改的同时清掉）。"""
        meta = self._read_meta()
        if meta is None:
            return None
        directory = self.directory
        try:
            content = (directory / _CONTENT).read_bytes()
        except OSError:
            content = b""
        self.clear()
        if self._expired(meta) or not content or hashlib.sha256(content).hexdigest() != meta.get("sha256"):
            return None
        return ManualFeed(
            content=content,
            file_name=str(meta.get("fileName") or ""),
            data_date=str(meta.get("dataDate") or ""),
            text=bool(meta.get("text")),
            sha256=str(meta.get("sha256") or ""),
            uploaded_at=str(meta.get("uploadedAt") or ""),
        )

    def clear(self) -> None:
        for name in (_CONTENT, _META):
            try:
                (self.directory / name).unlink()
            except FileNotFoundError:
                pass

    def _read_meta(self) -> dict[str, object] | None:
        try:
            meta = json.loads((self.directory / _META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return meta if isinstance(meta, dict) else None

    def _expired(self, meta: dict[str, object]) -> bool:
        try:
            uploaded = datetime.fromisoformat(str(meta.get("uploadedAt")))
        except ValueError:
            return True
        return self._clock() - uploaded > FEED_TTL

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
            os.replace(temp, path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
