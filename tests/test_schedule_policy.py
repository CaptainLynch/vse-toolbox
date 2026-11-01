# -*- coding: utf-8 -*-
"""Focused unit tests for services/schedule_policy.py (C4 固定时刻与当天补跑).

覆盖：
1. 默认时刻：同步北京时间 09:00 / 16:00，日报周一至周五 08:30（含调休覆盖表）；
2. 增删时刻与暂停：不可变绑定变更、暂停标 paused_skipped、恢复不补跑；
3. 开机/睡眠恢复只补当天，不补过去日期；
4. 时钟回拨与跨午夜不重复产出同一执行槽键；
5. 时区以参数注入：UTC 与洛杉矶（PDT 固定 -07:00）now 得出相同槽，UTC+8 回退等价；
6. 固定时刻与 interval 型互斥（ValueError）；纯计算模块无 I/O、无线程、无全局时钟读取。
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

import services.schedule_policy as sp
from core.time_rules import BEIJING_OFFSET

#: 洛杉矶夏令时 (PDT) 固定偏移：避免测试依赖本机 tzdata。
LA_PDT = timezone(timedelta(hours=-7), name="America/Los_Angeles")
#: 北京时间固定偏移（中国自 1992 年起无夏令时，与 Asia/Shanghai 等价）。
BEIJING = BEIJING_OFFSET

#: 2024-05-06 是周一。
MONDAY = date(2024, 5, 6)
TUESDAY = date(2024, 5, 7)
THURSDAY = date(2024, 5, 9)
FRIDAY = date(2024, 5, 10)
NEXT_MONDAY = date(2024, 5, 13)
SATURDAY = date(2024, 5, 4)
SUNDAY = date(2024, 5, 5)


def bj(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """构造北京时间 aware datetime。"""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=BEIJING)


def key_text(project: str, job: str, day: date, hour: int, minute: int) -> str:
    return f"{project}/{job}/{day.isoformat()}/{hour:02d}:{minute:02d}"


# ── 1. 默认时刻（验收标准 1） ─────────────────────────────────────────────────


def test_default_sync_times_are_beijing_0900_and_1600() -> None:
    binding = sp.sync_binding("proj-1")

    assert binding.kind == sp.JOB_KIND_FIXED
    assert binding.job_id == sp.SYNC_JOB_ID
    assert binding.times == (time(9, 0), time(16, 0))
    assert binding.workdays_only is False
    assert binding.paused is False


def test_daily_report_defaults_to_weekday_0830() -> None:
    binding = sp.daily_report_binding("proj-1")

    assert binding.job_id == sp.DAILY_REPORT_JOB_ID
    assert binding.times == (time(8, 30),)
    assert binding.workdays_only is True


def test_sync_slot_not_due_before_0900_and_due_at_0900() -> None:
    binding = sp.sync_binding("proj-1")

    assert sp.compute_due_slots(binding, now=bj(MONDAY, 8, 59)) == []

    due = sp.compute_due_slots(binding, now=bj(MONDAY, 9, 0))
    assert [slot.key.as_text() for slot in due] == [
        key_text("proj-1", sp.SYNC_JOB_ID, MONDAY, 9, 0)
    ]
    assert due[0].status == sp.STATUS_DUE
    assert due[0].scheduled_at == bj(MONDAY, 9, 0)
    assert due[0].is_catch_up is False


def test_sync_slots_at_1600_include_both_and_mark_catch_up() -> None:
    binding = sp.sync_binding("proj-1")

    due = sp.compute_due_slots(binding, now=bj(MONDAY, 16, 0))

    assert [slot.key.scheduled_time for slot in due] == [time(9, 0), time(16, 0)]
    assert [slot.is_catch_up for slot in due] == [True, False]
    assert all(slot.business_date == MONDAY for slot in due)


def test_daily_report_skips_weekend_and_runs_on_weekday() -> None:
    binding = sp.daily_report_binding("proj-1")

    assert sp.compute_due_slots(binding, now=bj(SATURDAY, 9, 0)) == []
    assert sp.compute_due_slots(binding, now=bj(SUNDAY, 9, 0)) == []

    due = sp.compute_due_slots(binding, now=bj(MONDAY, 8, 30))
    assert [slot.key.scheduled_time for slot in due] == [time(8, 30)]
    assert due[0].key.business_date == MONDAY


def test_on_time_tolerance_controls_catch_up_flag() -> None:
    binding = sp.sync_binding("proj-1")

    on_time = sp.compute_due_slots(binding, now=bj(MONDAY, 9, 5))
    late = sp.compute_due_slots(binding, now=bj(MONDAY, 9, 6))
    strict = sp.compute_due_slots(
        binding, now=bj(MONDAY, 9, 0, 1), on_time_tolerance=timedelta(0)
    )

    assert on_time[0].is_catch_up is False
    assert late[0].is_catch_up is True
    assert strict[0].is_catch_up is True
    with pytest.raises(ValueError):
        sp.compute_due_slots(binding, now=bj(MONDAY, 9, 0), on_time_tolerance=-1)


# ── 2. 时区注入（不依赖本机时区） ─────────────────────────────────────────────


def test_utc_and_los_angeles_now_produce_identical_slots() -> None:
    binding = sp.sync_binding("proj-1")
    utc_now = datetime(2024, 5, 6, 1, 0, tzinfo=timezone.utc)  # 北京 09:00
    la_now = utc_now.astimezone(LA_PDT)

    assert utc_now.timestamp() == la_now.timestamp()
    utc_slots = sp.compute_due_slots(binding, now=utc_now)
    la_slots = sp.compute_due_slots(binding, now=la_now)

    assert [slot.key.as_text() for slot in utc_slots] == [
        slot.key.as_text() for slot in la_slots
    ]
    assert utc_slots[0].key.business_date == MONDAY
    assert utc_slots[0].scheduled_at == bj(MONDAY, 9, 0)


def test_beijing_business_date_is_derived_from_utc_instant() -> None:
    binding = sp.sync_binding("proj-1")

    # UTC 2024-05-05T16:30Z == 北京 2024-05-06 00:30（周一，尚未到 09:00）
    before = datetime(2024, 5, 5, 16, 30, tzinfo=timezone.utc)
    # UTC 2024-05-06T01:00Z == 北京 2024-05-06 09:00
    at_slot = datetime(2024, 5, 6, 1, 0, tzinfo=timezone.utc)

    assert sp.compute_due_slots(binding, now=before) == []
    due = sp.compute_due_slots(binding, now=at_slot)
    assert due[0].key.business_date == MONDAY
    assert due[0].scheduled_at == bj(MONDAY, 9, 0)


def test_force_fallback_matches_zoneinfo_path() -> None:
    binding = sp.sync_binding("proj-1")
    now = bj(MONDAY, 17, 0)

    default_slots = sp.compute_due_slots(binding, now=now)
    fallback_slots = sp.compute_due_slots(binding, now=now, force_fallback=True)

    assert [slot.key.as_text() for slot in default_slots] == [
        slot.key.as_text() for slot in fallback_slots
    ]
    assert fallback_slots[0].scheduled_at.utcoffset() == timedelta(hours=8)


def test_iso_string_now_is_accepted() -> None:
    binding = sp.sync_binding("proj-1")

    due = sp.compute_due_slots(binding, now="2024-05-06T01:00:00Z")

    assert due[0].key.business_date == MONDAY
    assert due[0].scheduled_at == bj(MONDAY, 9, 0)


def test_naive_now_and_naive_string_are_rejected() -> None:
    binding = sp.sync_binding("proj-1")

    with pytest.raises(ValueError):
        sp.compute_due_slots(binding, now=datetime(2024, 5, 6, 9, 0))
    with pytest.raises(ValueError):
        sp.compute_due_slots(binding, now="2024-05-06T09:00:00")
    with pytest.raises(TypeError):
        sp.compute_due_slots(binding, now=MONDAY)


# ── 3. 增删时刻与暂停（验收标准 2） ──────────────────────────────────────────


def test_add_slot_time_is_sorted_idempotent_and_immutable() -> None:
    binding = sp.sync_binding("proj-1")

    added = sp.add_slot_time(binding, "12:00")
    again = sp.add_slot_time(added, time(12, 0))

    assert added.times == (time(9, 0), time(12, 0), time(16, 0))
    assert again.times == added.times
    assert binding.times == (time(9, 0), time(16, 0))  # 入参未被修改

    due = sp.compute_due_slots(added, now=bj(MONDAY, 12, 0))
    assert [slot.key.scheduled_time for slot in due] == [time(9, 0), time(12, 0)]


def test_remove_slot_time_is_idempotent_and_keeps_at_least_one() -> None:
    binding = sp.sync_binding("proj-1")

    removed = sp.remove_slot_time(binding, "16:00")
    assert removed.times == (time(9, 0),)
    assert sp.remove_slot_time(removed, "16:00") is removed  # 幂等

    with pytest.raises(ValueError):
        sp.remove_slot_time(removed, "09:00")
    with pytest.raises(ValueError):
        sp.set_slot_times(binding, ())
    assert sp.compute_due_slots(removed, now=bj(MONDAY, 17, 0))[0].key.scheduled_time == time(9, 0)


def test_set_slot_times_replaces_whole_set() -> None:
    binding = sp.sync_binding("proj-1")

    replaced = sp.set_slot_times(binding, ("10:15", "18:45", "10:15"))

    assert replaced.times == (time(10, 15), time(18, 45))
    assert sp.compute_due_slots(replaced, now=bj(MONDAY, 11, 0))[0].key.scheduled_time == time(10, 15)


def test_paused_binding_marks_paused_skipped_not_due() -> None:
    paused = sp.pause_binding(sp.sync_binding("proj-1"))

    due = sp.compute_due_slots(paused, now=bj(MONDAY, 17, 0))

    assert [slot.status for slot in due] == [
        sp.STATUS_PAUSED_SKIPPED,
        sp.STATUS_PAUSED_SKIPPED,
    ]
    assert [slot.is_catch_up for slot in due] == [False, False]


def test_project_level_pause_marks_paused_skipped() -> None:
    binding = sp.sync_binding("proj-1")

    due = sp.compute_due_slots(binding, now=bj(MONDAY, 9, 30), project_paused=True)

    assert [slot.status for slot in due] == [sp.STATUS_PAUSED_SKIPPED]


def test_paused_slots_already_persisted_are_not_reemitted() -> None:
    paused = sp.pause_binding(sp.sync_binding("proj-1"))
    first = sp.compute_due_slots(paused, now=bj(MONDAY, 17, 0))
    existing = [slot.key for slot in first]

    second = sp.compute_due_slots(paused, now=bj(MONDAY, 17, 30), existing_keys=existing)

    assert second == []


def test_resume_after_pause_does_not_backfill_skipped_slots() -> None:
    paused = sp.pause_binding(sp.sync_binding("proj-1"))
    skipped = sp.compute_due_slots(paused, now=bj(MONDAY, 10, 0))
    assert [slot.status for slot in skipped] == [sp.STATUS_PAUSED_SKIPPED]

    resumed = sp.resume_binding(paused)
    due = sp.compute_due_slots(
        resumed, now=bj(MONDAY, 10, 5), existing_keys=[slot.key for slot in skipped]
    )

    assert due == []
    assert sp.compute_due_slots(resumed, now=bj(MONDAY, 16, 0), existing_keys=[
        slot.key for slot in skipped
    ])[0].key.scheduled_time == time(16, 0)


def test_binding_mutation_helpers_reject_interval_bindings() -> None:
    interval = sp.interval_binding("proj-1", job_id="sync", interval_minutes=15)

    with pytest.raises(ValueError):
        sp.add_slot_time(interval, "09:00")
    with pytest.raises(ValueError):
        sp.remove_slot_time(interval, "09:00")
    with pytest.raises(ValueError):
        sp.set_slot_times(interval, ("09:00",))
    with pytest.raises(ValueError):
        sp.compute_due_slots(interval, now=bj(MONDAY, 9, 0))
    with pytest.raises(ValueError):
        sp.next_slot_at(interval, now=bj(MONDAY, 9, 0))


# ── 4. 开机/睡眠恢复只补当天 ─────────────────────────────────────────────────


def test_recovery_after_sleep_only_emits_today() -> None:
    binding = sp.sync_binding("proj-1")

    # 周一 08:00 之后机器睡眠，周四 10:00 才恢复：只补周四 09:00。
    due = sp.compute_due_slots(binding, now=bj(THURSDAY, 10, 0))

    assert len(due) == 1
    assert due[0].key.business_date == THURSDAY
    assert due[0].key.scheduled_time == time(9, 0)
    assert due[0].is_catch_up is True


def test_recovery_before_today_first_slot_emits_nothing() -> None:
    binding = sp.sync_binding("proj-1")

    assert sp.compute_due_slots(binding, now=bj(THURSDAY, 8, 0)) == []


def test_recovery_does_not_backfill_weekend_daily_reports() -> None:
    binding = sp.daily_report_binding("proj-1")

    # 周五 09:00 之后睡眠，周一 09:00 恢复：只产出周一 08:30，不补周五。
    due = sp.compute_due_slots(binding, now=bj(MONDAY, 9, 0))

    assert len(due) == 1
    assert due[0].key.business_date == MONDAY


def test_next_slot_at_skips_weekend_for_daily_report() -> None:
    binding = sp.daily_report_binding("proj-1")

    assert sp.next_slot_at(binding, now=bj(FRIDAY, 9, 0)) == bj(NEXT_MONDAY, 8, 30)


def test_next_slot_at_returns_none_when_paused() -> None:
    binding = sp.pause_binding(sp.sync_binding("proj-1"))

    assert sp.next_slot_at(binding, now=bj(MONDAY, 10, 0)) is None
    assert sp.next_slot_at(binding, now=bj(MONDAY, 10, 0), project_paused=True) is None


def test_next_slot_at_horizon_exhausted_returns_none() -> None:
    binding = sp.daily_report_binding("proj-1")
    overrides = {date(2024, 5, day): False for day in range(6, 31)}

    assert (
        sp.next_slot_at(
            binding, now=bj(MONDAY, 9, 0), workday_overrides=overrides, horizon_days=3
        )
        is None
    )


# ── 5. 时钟回拨与跨午夜（验收标准 3） ────────────────────────────────────────


def test_clock_rollback_does_not_reemit_existing_slots() -> None:
    binding = sp.sync_binding("proj-1")

    emitted = sp.compute_due_slots(binding, now=bj(MONDAY, 23, 0))
    assert len(emitted) == 2
    existing = [slot.key for slot in emitted]

    # 时钟回拨到同日 12:00：已产出的 09:00 槽不得再次产出。
    rolled_back = sp.compute_due_slots(
        binding, now=bj(MONDAY, 12, 0), existing_keys=existing
    )

    assert rolled_back == []


def test_clock_rollback_across_day_boundary_keeps_today_only() -> None:
    binding = sp.sync_binding("proj-1")
    existing = [slot.key for slot in sp.compute_due_slots(binding, now=bj(MONDAY, 23, 59))]

    # 回拨到周一 00:10：当天还没有到点槽，且不得回补周一之前。
    assert sp.compute_due_slots(binding, now=bj(MONDAY, 0, 10), existing_keys=existing) == []


def test_midnight_crossing_produces_distinct_business_dates() -> None:
    binding = sp.sync_binding("proj-1")

    late = sp.compute_due_slots(binding, now=bj(MONDAY, 23, 59))
    after_midnight = sp.compute_due_slots(
        binding, now=bj(TUESDAY, 0, 30), existing_keys=[slot.key for slot in late]
    )
    next_morning = sp.compute_due_slots(
        binding, now=bj(TUESDAY, 9, 0), existing_keys=[slot.key for slot in late]
    )

    assert [slot.key.business_date for slot in late] == [MONDAY, MONDAY]
    assert after_midnight == []
    assert [slot.key.as_text() for slot in next_morning] == [
        key_text("proj-1", sp.SYNC_JOB_ID, TUESDAY, 9, 0)
    ]


def test_compute_due_slots_is_deterministic_and_key_unique() -> None:
    binding = sp.set_slot_times(sp.sync_binding("proj-1"), ("09:00", "09:00", "16:00"))

    first = sp.compute_due_slots(binding, now=bj(MONDAY, 23, 59))
    second = sp.compute_due_slots(binding, now=bj(MONDAY, 23, 59))

    texts = [slot.key.as_text() for slot in first]
    assert texts == [slot.key.as_text() for slot in second]
    assert len(texts) == len(set(texts)) == 2


def test_slot_ledger_prevents_duplicate_emission_across_rollback() -> None:
    binding = sp.sync_binding("proj-1")
    ledger = sp.SlotLedger()

    first = ledger.extend(sp.compute_due_slots(binding, now=bj(MONDAY, 23, 0)))
    assert len(first) == 2
    assert len(ledger) == 2

    # 回拨后同一槽再次被算出，但台账拒绝重复登记。
    replayed = sp.compute_due_slots(binding, now=bj(MONDAY, 12, 0))
    assert len(replayed) == 1  # 09:00 被重新算出
    assert ledger.extend(replayed) == []
    assert replayed[0].key in ledger
    assert len(ledger) == 2

    # 次日新槽仍可登记。
    next_day = ledger.extend(sp.compute_due_slots(binding, now=bj(TUESDAY, 9, 0)))
    assert len(next_day) == 1
    assert len(ledger) == 3


def test_existing_keys_accept_text_mapping_and_slotkey() -> None:
    binding = sp.sync_binding("proj-1")
    slot_key = sp.SlotKey("proj-1", sp.SYNC_JOB_ID, MONDAY, time(9, 0))
    row = {"projectId": "proj-1", "jobId": sp.SYNC_JOB_ID, "businessDate": "2024-05-06", "scheduledTime": "16:00"}
    emitted = sp.compute_due_slots(binding, now=bj(MONDAY, 17, 0))

    due = sp.compute_due_slots(
        binding,
        now=bj(MONDAY, 17, 0),
        existing_keys=[slot_key.as_text(), sp.slot_key_from_mapping(row)],
    )
    by_slot = sp.compute_due_slots(binding, now=bj(MONDAY, 17, 0), existing_keys=emitted)
    ledger = sp.SlotLedger()
    ledger.extend(emitted)
    by_ledger = sp.compute_due_slots(binding, now=bj(MONDAY, 17, 0), existing_keys=ledger)

    assert due == []
    assert by_slot == []
    assert by_ledger == []
    assert list(ledger) == [slot.key.as_text() for slot in emitted]


# ── 6. 固定时刻与 interval 互斥 / 纯计算约束 ─────────────────────────────────


def test_mixed_binding_is_rejected() -> None:
    with pytest.raises(ValueError):
        sp.ScheduleBinding(
            project_id="proj-1",
            job_id="sync",
            kind=sp.JOB_KIND_FIXED,
            times=(time(9, 0),),
            interval_minutes=15,
        )
    with pytest.raises(ValueError):
        sp.ScheduleBinding(
            project_id="proj-1",
            job_id="sync",
            kind=sp.JOB_KIND_INTERVAL,
            times=(time(9, 0),),
            interval_minutes=15,
        )


def test_interval_binding_keeps_legacy_semantics() -> None:
    binding = sp.interval_binding("proj-1", job_id="sync", interval_minutes=15)

    assert binding.kind == sp.JOB_KIND_INTERVAL
    assert binding.times == ()
    assert binding.interval_minutes == 15

    with pytest.raises(ValueError):
        sp.interval_binding("proj-1", job_id="sync", interval_minutes=0)
    with pytest.raises(ValueError):
        sp.interval_binding("proj-1", job_id="sync", interval_minutes=True)


def test_fixed_binding_requires_at_least_one_time() -> None:
    with pytest.raises(ValueError):
        sp.ScheduleBinding(project_id="proj-1", job_id="sync", kind=sp.JOB_KIND_FIXED, times=())


def test_binding_and_slot_are_immutable() -> None:
    binding = sp.sync_binding("proj-1")
    slot = sp.compute_due_slots(binding, now=bj(MONDAY, 9, 0))[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        binding.paused = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        slot.status = sp.STATUS_PAUSED_SKIPPED  # type: ignore[misc]


def test_slot_key_text_mapping_and_roundtrip() -> None:
    key = sp.SlotKey("proj-1", "sync", MONDAY, time(9, 0))

    assert key.as_text() == "proj-1/sync/2024-05-06/09:00"
    assert key.as_tuple() == ("proj-1", "sync", MONDAY, time(9, 0))
    assert key.as_dict() == {
        "projectId": "proj-1",
        "jobId": "sync",
        "businessDate": "2024-05-06",
        "scheduledTime": "09:00",
    }
    assert sp.slot_key_from_mapping(key.as_dict()) == key
    assert sp.slot_key_from_mapping(
        {"project_id": "proj-1", "job_id": "sync", "business_date": MONDAY, "scheduled_time": "09:00"}
    ) == key


def test_slot_key_rejects_empty_identity_and_bad_time() -> None:
    with pytest.raises(ValueError):
        sp.SlotKey("", "sync", MONDAY, time(9, 0))
    with pytest.raises(ValueError):
        sp.SlotKey("proj-1", "", MONDAY, time(9, 0))
    with pytest.raises(ValueError):
        sp.SlotKey("proj-1", "sync", MONDAY, "25:00")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        sp.slot_key_from_mapping({"projectId": "p", "jobId": "j", "businessDate": "2024-05-06"})


def test_module_has_no_io_threads_or_global_clock() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "services" / "schedule_policy.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "sqlite3",
        "threading",
        "import web",
        "from web",
        "plugins",
        "datetime.now(",
        "date.today(",
        "time.time(",
        "now_utc",
        "os.environ",
        "open(",
    ):
        assert forbidden not in source, f"纯计算模块不得出现 {forbidden!r}"
    assert "from core.time_rules import" in source


# ── 7. 调休覆盖表 ────────────────────────────────────────────────────────────


def test_workday_override_turns_weekend_into_workday() -> None:
    binding = sp.daily_report_binding("proj-1")
    overrides = {SATURDAY: True}

    assert sp.is_workday(SATURDAY, overrides) is True
    assert sp.is_workday(SUNDAY, overrides) is False

    due = sp.compute_due_slots(binding, now=bj(SATURDAY, 8, 30), workday_overrides=overrides)
    assert [slot.key.business_date for slot in due] == [SATURDAY]


def test_workday_override_turns_weekday_into_holiday() -> None:
    binding = sp.daily_report_binding("proj-1")
    overrides = {"2024-05-06": False}

    assert sp.is_workday(MONDAY, overrides) is False
    assert sp.compute_due_slots(binding, now=bj(MONDAY, 9, 0), workday_overrides=overrides) == []


def test_workday_overrides_require_boolean_values() -> None:
    binding = sp.daily_report_binding("proj-1")

    with pytest.raises(ValueError):
        sp.compute_due_slots(binding, now=bj(MONDAY, 9, 0), workday_overrides={MONDAY: "yes"})
    with pytest.raises(TypeError):
        sp.is_workday(MONDAY, ["2024-05-06"])  # type: ignore[arg-type]
