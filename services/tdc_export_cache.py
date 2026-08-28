# -*- coding: utf-8 -*-
"""Bounded, short-lived cache for official TDC XLSX exports.

The cache stores only the returned workbook bytes.  Cache keys are derived
from already-normalized, non-secret request parameters; credentials, cookies,
authorization headers, and DPAPI values are rejected from key material.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Mapping


_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "credential",
    "session",
    "csrf",
)


@dataclass(frozen=True)
class TDCExportCacheResult:
    """One cache lookup result."""

    content: bytes
    hit: bool


@dataclass(frozen=True)
class _CacheEntry:
    content: bytes
    expires_at: float


class TDCExportCache:
    """Thread-safe LRU cache with bounded entry count and byte capacity."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 180.0,
        max_entries: int = 4,
        max_bytes: int = 64 * 1024 * 1024,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("TDC export cache TTL must be positive")
        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("TDC export cache limits must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._max_bytes = int(max_bytes)
        self._clock = clock or time.monotonic
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._total_bytes = 0
        self._lock = threading.RLock()

    @staticmethod
    def make_key(
        *,
        report_type: str,
        base_url: str,
        filters: Mapping[str, object],
        namespace: str = "local",
    ) -> str:
        """Build a digest from safe, normalized request metadata only."""
        if not isinstance(filters, Mapping):
            raise TypeError("TDC export cache filters must be a mapping")
        safe_filters: dict[str, str] = {}
        for raw_key, raw_value in filters.items():
            key = str(raw_key).strip()
            lowered = key.lower().replace("-", "_")
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                raise ValueError("TDC export cache key cannot contain sensitive fields")
            safe_filters[key] = "" if raw_value is None else str(raw_value)
        payload = {
            "report_type": str(report_type).strip(),
            "base_url": str(base_url).strip().rstrip("/"),
            "filters": dict(sorted(safe_filters.items())),
            "namespace": str(namespace).strip(),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get_or_create(
        self,
        key: str,
        producer: Callable[[], bytes],
    ) -> TDCExportCacheResult:
        """Return a live entry or create one once for the requested key."""
        if not isinstance(key, str) or not key:
            raise ValueError("TDC export cache key is required")
        if not callable(producer):
            raise TypeError("TDC export cache producer must be callable")

        # Keep the lock during production so two simultaneous identical UI
        # requests cannot trigger two expensive official exports.
        with self._lock:
            now = self._clock()
            self._evict_expired(now)
            existing = self._entries.get(key)
            if existing is not None:
                self._entries.move_to_end(key)
                return TDCExportCacheResult(existing.content, True)

            content = producer()
            if not isinstance(content, bytes) or not content:
                raise ValueError("TDC export cache producer must return non-empty bytes")
            if len(content) > self._max_bytes:
                raise ValueError("TDC export exceeds the cache byte limit")
            entry = _CacheEntry(content=content, expires_at=now + self._ttl_seconds)
            self._entries[key] = entry
            self._total_bytes += len(content)
            self._evict_to_limits()
            return TDCExportCacheResult(content, False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0

    def __len__(self) -> int:
        with self._lock:
            self._evict_expired(self._clock())
            return len(self._entries)

    def _evict_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._remove(key)

    def _evict_to_limits(self) -> None:
        while self._entries and (
            len(self._entries) > self._max_entries or self._total_bytes > self._max_bytes
        ):
            _, entry = self._entries.popitem(last=False)
            self._total_bytes -= len(entry.content)

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes -= len(entry.content)


__all__ = ["TDCExportCache", "TDCExportCacheResult"]
