# -*- coding: utf-8 -*-
"""任务生命周期契约（契约 C6）：两态取消、幂等取消、retryOf、不定进度。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from tasks_boot import _augment_entry, _TASK_LIFECYCLE  # noqa: E402


def _base_entry(**overrides):
    entry = {
        "id": "crawl_test123",
        "raw_id": "test123",
        "category": "crawl",
        "status": "running",
        "is_active": True,
        "progress": {},
        "can_cancel": True,
    }
    entry.update(overrides)
    return entry


def teardown_function() -> None:
    # 进程内状态在用例间隔离
    _TASK_LIFECYCLE.clear_cancel_requested("crawl_test123", "test123", "crawl_x1", "x1")


def test_augment_marks_cancel_requested() -> None:
    entry = _base_entry()
    _TASK_LIFECYCLE.mark_cancel_requested("crawl_test123")
    augmented = _augment_entry(entry)
    assert augmented["cancelRequested"] is True


def test_augment_default_not_requested() -> None:
    augmented = _augment_entry(_base_entry())
    assert augmented["cancelRequested"] is False
    assert "retryOf" not in augmented


def test_augment_indeterminate_progress_for_active_without_total() -> None:
    augmented = _augment_entry(_base_entry(progress={}))
    assert augmented["progressIndeterminate"] is True


def test_augment_no_indeterminate_when_progress_known() -> None:
    augmented = _augment_entry(_base_entry(progress={"total": 10, "done": 5}))
    assert "progressIndeterminate" not in augmented


def test_augment_no_indeterminate_for_finished() -> None:
    augmented = _augment_entry(_base_entry(is_active=False, status="succeeded"))
    assert "progressIndeterminate" not in augmented


def test_retry_of_recorded_and_exposed() -> None:
    _TASK_LIFECYCLE.record_retry("crawl_new1", "crawl_old1")
    augmented = _augment_entry(_base_entry(id="crawl_new1", raw_id="new1"))
    assert augmented["retryOf"] == "crawl_old1"
