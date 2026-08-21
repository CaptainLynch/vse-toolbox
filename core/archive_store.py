# -*- coding: utf-8 -*-
"""Controlled, atomic local archive storage and explicit retention cleanup."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping, Sequence

from core.runtime_paths import app_root

_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_BAD_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FORMULA = re.compile(r"^\s*[=+\-@]")
DEFAULT_MAX_BYTES = 20 * 1024 * 1024 * 1024


class ArchiveSafetyError(ValueError):
    pass


class ArchiveCapacityError(OSError):
    pass


@dataclass(frozen=True)
class ArchiveArtifact:
    relative_path: str
    artifact_type: str
    display_name: str
    size_bytes: int
    sha256: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "artifact_type": self.artifact_type,
            "display_name": self.display_name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class RetentionItem:
    relative_path: str
    size_bytes: int
    modified_at: str


class ArchiveStore:
    def __init__(
        self,
        approved_roots: Mapping[str, Path | str] | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        reserve_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        roots = dict(approved_roots or {"default": app_root() / "data" / "output" / "exports"})
        if not roots:
            raise ArchiveSafetyError("at least one approved root is required")
        self._roots: dict[str, Path] = {}
        for root_id, value in roots.items():
            safe_id = self._component(root_id)
            root = Path(value).expanduser().absolute()
            root.mkdir(parents=True, exist_ok=True)
            current = root
            while current.parent != current:
                if self._is_reparse(current):
                    raise ArchiveSafetyError(
                        "links/reparse points are not allowed in approved roots"
                    )
                current = current.parent
            self._roots[safe_id] = root.resolve(strict=True)
        if max_bytes <= 0 or reserve_bytes < 0:
            raise ValueError("archive capacity limits are invalid")
        self.max_bytes = int(max_bytes)
        self.reserve_bytes = int(reserve_bytes)

    @property
    def root_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._roots))

    @staticmethod
    def _component(value: object) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).strip().rstrip(". ")
        if not text or text in {".", ".."} or _BAD_COMPONENT.search(text):
            raise ArchiveSafetyError("archive path component is invalid")
        if text.split(".", 1)[0].upper() in _DEVICE_NAMES:
            raise ArchiveSafetyError("Windows device names are not allowed")
        return text

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        attrs = int(getattr(info, "st_file_attributes", 0))
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return path.is_symlink() or bool(attrs & reparse_flag)

    @classmethod
    def _assert_no_link(cls, root: Path, target: Path) -> None:
        current = target.absolute()
        while True:
            if current.exists() and cls._is_reparse(current):
                raise ArchiveSafetyError("links/reparse points are not allowed in archive paths")
            if current == root or current.parent == current:
                break
            current = current.parent

    def root(self, root_id: str = "default") -> Path:
        try:
            return self._roots[root_id]
        except KeyError as exc:
            raise ArchiveSafetyError("approved archive root is unknown") from exc

    def run_directory(self, source: str, report: str, run_id: str | int, *, root_id: str = "default", day: date | None = None) -> Path:
        root = self.root(root_id)
        parts = (self._component(source), self._component(report), (day or date.today()).isoformat(), self._component(run_id))
        directory = root.joinpath(*parts)
        self._assert_no_link(root, directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._assert_no_link(root, directory)
        resolved = directory.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ArchiveSafetyError("archive path escapes approved root")
        return resolved

    def _destination(self, directory: Path, name: str) -> Path:
        safe = self._component(Path(name).name)
        stem, suffix = Path(safe).stem, Path(safe).suffix
        candidate = directory / safe
        counter = 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        while candidate.exists():
            counter += 1
            candidate = directory / f"{stem}-{stamp}-{counter}{suffix}"
        self._assert_no_link(directory, candidate)
        return candidate

    def _preflight(self, directory: Path, expected_size: int | None) -> None:
        if expected_size is not None and (expected_size < 0 or expected_size > self.max_bytes):
            raise ArchiveCapacityError("archive exceeds the configured operational limit")
        free = shutil.disk_usage(directory).free
        required = self.reserve_bytes + (expected_size or 0)
        if free < required:
            raise ArchiveCapacityError("insufficient free disk space for archive")

    def _write_chunks(self, chunks: Iterable[bytes], *, source: str, report: str, run_id: str | int, file_name: str, artifact_type: str, root_id: str = "default", expected_size: int | None = None) -> ArchiveArtifact:
        directory = self.run_directory(source, report, run_id, root_id=root_id)
        self._preflight(directory, expected_size)
        fd, temp_name = tempfile.mkstemp(prefix=".partial-", dir=directory)
        total = 0
        digest = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as handle:
                for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise TypeError("archive stream must return bytes")
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ArchiveCapacityError("archive exceeds the configured operational limit")
                    handle.write(chunk)
                    digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            while True:
                destination = self._destination(directory, file_name)
                try:
                    os.link(temp_name, destination)
                    break
                except FileExistsError:
                    continue
            Path(temp_name).unlink()
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        root = self.root(root_id)
        relative = destination.relative_to(root).as_posix()
        return ArchiveArtifact(relative, self._component(artifact_type), destination.name, total, digest.hexdigest())

    def write_stream(self, stream: BinaryIO, *, chunk_size: int = 1024 * 1024, **kwargs: Any) -> ArchiveArtifact:
        def chunks() -> Iterable[bytes]:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    return
                yield chunk

        return self._write_chunks(chunks(), **kwargs)

    def write_bytes(self, payload: bytes, **kwargs: Any) -> ArchiveArtifact:
        return self.write_stream(io.BytesIO(payload), expected_size=len(payload), **kwargs)

    @staticmethod
    def _csv_cell(value: Any) -> str:
        text = "" if value is None else str(value)
        if "\x00" in text or any(ord(ch) < 32 and ch not in "\t\r\n" for ch in text):
            raise ArchiveSafetyError("CSV contains invalid control characters")
        return "'" + text if _FORMULA.match(text) else text

    def write_csv(self, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str], **kwargs: Any) -> ArchiveArtifact:
        names = list(fieldnames)

        def encoded_rows() -> Iterable[bytes]:
            yield b"\xef\xbb\xbf"
            for row in ({key: key for key in names}, *()):
                buffer = io.StringIO(newline="")
                csv.DictWriter(buffer, fieldnames=names).writerow(row)
                yield buffer.getvalue().encode("utf-8")
            for row in rows:
                buffer = io.StringIO(newline="")
                writer = csv.DictWriter(buffer, fieldnames=names, extrasaction="ignore")
                writer.writerow({key: self._csv_cell(row.get(key)) for key in names})
                yield buffer.getvalue().encode("utf-8")

        return self._write_chunks(encoded_rows(), **kwargs)

    def write_json(self, value: Any, **kwargs: Any) -> ArchiveArtifact:
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
        chunks = (part.encode("utf-8") for part in encoder.iterencode(value))
        return self._write_chunks(chunks, **kwargs)

    def plan_retention(self, *, root_id: str = "default", retention_days: int = 90, now: datetime | None = None) -> list[RetentionItem]:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        root = self.root(root_id)
        cutoff = (now or datetime.now(timezone.utc)).timestamp() - timedelta(days=retention_days).total_seconds()
        items: list[RetentionItem] = []
        for path in root.rglob("*"):
            self._assert_no_link(root, path)
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            items.append(RetentionItem(path.relative_to(root).as_posix(), path.stat().st_size, datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()))
        return sorted(items, key=lambda item: item.relative_path)

    def execute_retention(self, items: Sequence[RetentionItem], *, root_id: str = "default") -> tuple[str, ...]:
        root = self.root(root_id)
        removed: list[str] = []
        for item in items:
            relative = Path(item.relative_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ArchiveSafetyError("retention path is invalid")
            target = root.joinpath(*relative.parts)
            self._assert_no_link(root, target)
            resolved_parent = target.parent.resolve(strict=True)
            if not resolved_parent.is_relative_to(root):
                raise ArchiveSafetyError("retention path escapes approved root")
            if target.is_file():
                target.unlink()
                removed.append(relative.as_posix())
        return tuple(removed)
