"""iBOM 报表手工导入暂存：代替**下一次**定时归档运行的 iBOM 自动抓取（方案 §6 用途 A）。

- 上传时就完整校验（表头变体 ``ibom``、行数上限、每行都有流水单号）；不合格直接拒绝，不留半成品。
- 数据日期必须是**当天**：手工报表合并进的是「此刻」的快照，旧报表会被当成今天的进度（评审 2026-11-20）。
- 暂存一份，**只用一次**：归档连接器取走即删除；超过有效期（30 分钟）未被取走视为作废。
- 内容与元数据存在**同一个文件**里、原子替换写入，读写不会交错（评审 2026-11-20）。
- 存放在数据目录 ``ibom_manual_feed/`` 下；插件与归档运行器用同一规则（``feed_dir_for``）。
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

from core.archive_store import ArchiveStore
from services.tdc_official_rows import (
    VARIANT_IBOM,
    OfficialWorkbookContractError,
    OfficialWorkbookError,
    OfficialWorkbookTruncated,
    read_official_tdc_rows_from_bytes,
)

FEED_TTL = timedelta(minutes=30)
#: 低于宿主请求体上限（16 MB，含 multipart 开销）。实测 43 张单的报表约 0.1 MB。
MAX_FEED_BYTES = 15 * 1024 * 1024
MAX_FEED_ROWS = 10001
FEED_DIR_NAME = "ibom_manual_feed"
_FEED_FILE = "pending.feed"
_CONSUMED_FILE = "consumed.json"
#: 本功能早期提交里的双文件格式（从未发布）；清理时一并删除，不留个人与零件数据。
_LEGACY_FILES = ("pending.bin", "pending.json")
_ENCRYPTED_REASONS = {"encrypted_container", "ole_container"}
_NAME_LIMIT = 120
_DEFAULT_NAMES = {True: "ibom_report.txt", False: "ibom_report.xlsx"}


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


def feed_dir_for(data_dir: Path | str) -> Path:
    """暂存目录 = 数据目录（数据库所在目录）/ ``ibom_manual_feed``；插件与归档运行器共用这一规则。"""
    return Path(data_dir) / FEED_DIR_NAME


def default_feed_dir() -> Path:
    from core.config import DATA_DIR

    return feed_dir_for(DATA_DIR)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def safe_feed_name(raw: object) -> tuple[str, bool]:
    """浏览器给的文件名 → (可安全写入归档目录的文件名, 是否为文本)。

    先按**完整**文件名判定 .txt，再截断（截断保留扩展名）；去掉客户端路径（两种分隔符）；
    不满足归档目录命名规则（保留字符、设备名、结尾点/空格）时退回默认名。
    """
    base = re.split(r"[\\/]", str(raw or "").strip())[-1]
    text = base.lower().endswith(".txt")
    extension = ".txt" if text else ".xlsx"
    stem = base[: -len(extension)] if base.lower().endswith(extension) else base
    stem = stem[: _NAME_LIMIT - len(extension)]
    name = f"{stem}{extension}" if stem.strip(" .") else _DEFAULT_NAMES[text]
    try:
        ArchiveStore._component(name)
    except Exception:
        name = _DEFAULT_NAMES[text]
    return name, text


def parse_feed_rows(content: bytes, *, text: bool) -> tuple[dict[str, object], ...]:
    """按 iBOM 表头变体读入；失败映射为 ``ManualFeedError``。每行都必须有流水单号。"""
    try:
        rows = read_official_tdc_rows_from_bytes(
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
    if any(not str(row.get("流水单号") or "").strip() for row in rows):
        raise ManualFeedError("E_ROW_WITHOUT_SERIAL", "报表里有流水单号为空的行，请确认导出的是原始报表")
    return rows


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
            raise ManualFeedError("E_TOO_LARGE", "文件超过大小上限（15 MB）")
        if not isinstance(data_date, date):
            raise ManualFeedError("E_DATE_REQUIRED", "需要确认这份报表的数据日期")
        today = self._clock().astimezone().date()
        if data_date != today:
            raise ManualFeedError(
                "E_DATE_NOT_TODAY", "只能上传当天导出的 iBOM 报表：它会和 TDC 的实时数据合并成此刻的快照"
            )
        name, text = safe_feed_name(file_name)
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
            "documents": len({str(row.get("流水单号") or "").strip() for row in rows}),
        }
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(meta, ensure_ascii=False).encode("utf-8") + b"\n" + content
        self._atomic_write(directory / _FEED_FILE, payload)
        return meta

    def pending(self) -> dict[str, object] | None:
        """当前待用的暂存元数据（过期的视为没有）；不取走。"""
        loaded = self._load()
        if loaded is None or self._expired(loaded[0]):
            return None
        return loaded[0]

    def take(self) -> ManualFeed | None:
        """取走并删除暂存；没有、过期或内容不符都返回 None（同时清掉）。"""
        loaded = self._load()
        if loaded is None:
            return None
        self.clear()
        meta, content = loaded
        if self._expired(meta) or not content or hashlib.sha256(content).hexdigest() != meta.get("sha256"):
            return None
        # 记下「哪一份被用掉了」，上传接口据此判断触发的同步是否真的用上了它（而不是从暂存为空倒推）。
        marker = {"sha256": meta.get("sha256"), "takenAt": self._clock().astimezone(timezone.utc).isoformat()}
        try:
            self._atomic_write(self.directory / _CONSUMED_FILE, json.dumps(marker).encode("utf-8"))
        except OSError:
            pass
        return ManualFeed(
            content=content,
            file_name=str(meta.get("fileName") or ""),
            data_date=str(meta.get("dataDate") or ""),
            text=bool(meta.get("text")),
            sha256=str(meta.get("sha256") or ""),
            uploaded_at=str(meta.get("uploadedAt") or ""),
        )

    def clear(self) -> None:
        for name in (_FEED_FILE, *_LEGACY_FILES):
            try:
                (self.directory / name).unlink()
            except FileNotFoundError:
                pass

    def was_consumed(self, sha256: str) -> bool:
        """这一份（按内容指纹）是否已被某次归档运行取走使用。"""
        try:
            marker = json.loads((self.directory / _CONSUMED_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(marker, dict) and bool(sha256) and marker.get("sha256") == sha256

    def void_if_pending(self, sha256: str) -> bool:
        """若暂存仍是这一份（未被取走），作废它；返回是否作废了。不会删掉别人后来上传的另一份。"""
        loaded = self._load()
        if loaded is None or loaded[0].get("sha256") != sha256:
            return False
        self.clear()
        return True

    def _load(self) -> tuple[dict[str, object], bytes] | None:
        try:
            raw = (self.directory / _FEED_FILE).read_bytes()
        except OSError:
            return None
        head, sep, content = raw.partition(b"\n")
        if not sep:
            return None
        try:
            meta = json.loads(head.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return (meta, content) if isinstance(meta, dict) else None

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
