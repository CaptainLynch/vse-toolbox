# -*- coding: utf-8 -*-
"""Unit tests for the bounded TDC official-export cache."""

from __future__ import annotations

import pytest

from services.tdc_export_cache import TDCExportCache


def test_cache_reuses_live_export_and_expires_entries() -> None:
    now = [100.0]
    cache = TDCExportCache(ttl_seconds=3, clock=lambda: now[0])
    calls = [0]

    def produce() -> bytes:
        calls[0] += 1
        return b"PK-official-xlsx"

    first = cache.get_or_create("same", produce)
    second = cache.get_or_create("same", produce)
    assert first.content == second.content == b"PK-official-xlsx"
    assert first.hit is False and second.hit is True
    assert calls == [1]

    now[0] = 103.0
    third = cache.get_or_create("same", produce)
    assert third.hit is False
    assert calls == [2]


def test_cache_evicts_oldest_entry_to_keep_limits() -> None:
    cache = TDCExportCache(max_entries=1, max_bytes=100)
    cache.get_or_create("one", lambda: b"one")
    cache.get_or_create("two", lambda: b"two")
    assert len(cache) == 1
    assert cache.get_or_create("one", lambda: b"new-one").hit is False


def test_cache_rejects_sensitive_key_fields_and_invalid_producers() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        TDCExportCache.make_key(
            report_type="data_model",
            base_url="https://tdc.example",
            filters={"password": "do-not-use"},
        )

    cache = TDCExportCache()
    with pytest.raises(ValueError, match="non-empty bytes"):
        cache.get_or_create("empty", lambda: b"")


def test_cache_key_does_not_embed_filter_values() -> None:
    key = TDCExportCache.make_key(
        report_type="data_model",
        base_url="https://tdc.example",
        filters={"projectModel": "PRIVATE-MODEL"},
        namespace="local-user",
    )
    assert "PRIVATE-MODEL" not in key
    assert "local-user" not in key
