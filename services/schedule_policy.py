# -*- coding: utf-8 -*-
"""固定时刻与当天补跑的纯计算内核（C4 调度契约的槽计算部分）。

职责边界（严格纯计算，无副作用）：
- 不读写 SQLite、不启动线程/定时器、不做任何文件或网络 I/O、不读取全局时钟。
- 当前时间与时区一律由调用方注入（``now`` 为带时区的 aware datetime 或 ISO 字符串）；
  时区口径固定为北京时间，复用 ``core.time_rules.get_beijing_tz`` 及其 UTC+8 回退，
  不依赖本机时区，也不依赖 tzdata 是否可用。
- 持久化（执行槽表）、租约、重试、托盘进程接线由 DSH-V2-19 / DSH-V2-20 承接；
  本模块当前**尚无生产调用方**，按计划由 19/20 接线。

对齐 docs/refactor-v2/CONTRACTS.md C4：
1. 默认时刻：同步每日北京时间 09:00、16:00；日报默认周一至周五 08:30，
   调休通过可选覆盖表（日期 -> 是否工作日）表达。
2. 执行槽唯一键：``projectId / jobId / businessDate / scheduledTime``（见 :class:`SlotKey`）。
3. 补跑：启动/睡眠恢复只补**当天**已到点且尚未产出的槽，绝不回补前几天。
4. 暂停：项目级/任务级暂停期间到点的槽标 ``paused_skipped`` 而不是 ``due``，不补跑。
5. 固定时刻型与 interval 型互斥：同一绑定混用即 ``ValueError``；本模块不计算 interval 槽。
6. 时钟回拨与跨午夜：给定已存在槽键集合时，计算结果不会重复产出同一槽键；
   回拨后已产出槽不会再次产出。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Iterator, Mapping

from core.time_rules import get_beijing_tz, pure_date, to_beijing

#: 绑定类型：固定时刻。
JOB_KIND_FIXED = "fixed"
#: 绑定类型：既有 15/30/60 分钟间隔（保持原语义，本模块不计算其槽）。
JOB_KIND_INTERVAL = "interval"

_JOB_KINDS = (JOB_KIND_FIXED, JOB_KIND_INTERVAL)

#: 槽状态：已到点，应当执行。
STATUS_DUE = "due"
#: 槽状态：暂停期间到点，跳过且不补跑。
STATUS_PAUSED_SKIPPED = "paused_skipped"

#: 项目状态同步任务 ID（默认每日 09:00 / 16:00）。
SYNC_JOB_ID = "project_status_sync"
#: 日报任务 ID（默认周一至周五 08:30）。
DAILY_REPORT_JOB_ID = "daily_report"

#: 默认同步时刻：北京时间 09:00、16:00。
DEFAULT_SYNC_TIMES: tuple[time, ...] = (time(9, 0), time(16, 0))
#: 默认日报时刻：北京时间 08:30。
DEFAULT_DAILY_REPORT_TIME = time(8, 30)

#: 到点后仍视为「准时」的容差；超出容差才标记为补跑（catch-up）。
DEFAULT_ON_TIME_TOLERANCE = timedelta(minutes=5)

#: ``next_slot_at`` 的默认搜索上限（天），避免无工作日时无限循环。
DEFAULT_NEXT_SLOT_HORIZON_DAYS = 370


# ── 内部校验工具 ──────────────────────────────────────────────────────────────


def _require_text(value: Any, field: str) -> str:
    """校验并规范化非空文本标识（project_id / job_id）。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    return text


def _normalize_time(value: Any) -> time:
    """把 ``time`` 或 ``HH:MM`` / ``HH:MM:SS`` 字符串规范化为 ``time``。"""
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("时刻字符串不能为空")
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
        raise ValueError(f"无法解析的时刻: {value!r}，应为 'HH:MM' 或 'HH:MM:SS'")
    raise TypeError(f"不支持的时刻类型: {type(value).__name__}")


def _normalize_times(values: Iterable[Any] | None) -> tuple[time, ...]:
    """规范化时刻集合：去重并按时间升序排列。"""
    if values is None:
        return ()
    normalized = {_normalize_time(item) for item in values}
    return tuple(sorted(normalized))


def _normalize_overrides(overrides: Mapping[Any, Any] | None) -> dict[date, bool]:
    """规范化调休覆盖表：键为日期（date 或 'YYYY-MM-DD'），值为严格布尔。"""
    if not overrides:
        return {}
    if not isinstance(overrides, Mapping):
        raise TypeError("workday_overrides 必须是 日期 -> 是否工作日 的映射")
    normalized: dict[date, bool] = {}
    for raw_day, raw_flag in overrides.items():
        if not isinstance(raw_flag, bool):
            raise ValueError(
                f"workday_overrides[{raw_day!r}] 必须是布尔值，收到 {type(raw_flag).__name__}"
            )
        normalized[pure_date(raw_day)] = raw_flag
    return normalized


def _is_workday(day: date, overrides: Mapping[date, bool]) -> bool:
    """工作日判定：覆盖表优先，缺省周一至周五。"""
    if day in overrides:
        return overrides[day]
    return day.weekday() < 5


def _normalize_tolerance(value: Any) -> timedelta:
    """规范化准时容差：接受 timedelta 或非负秒数。"""
    if isinstance(value, timedelta):
        tolerance = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        tolerance = timedelta(seconds=float(value))
    else:
        raise TypeError("on_time_tolerance 必须是 timedelta 或秒数")
    if tolerance < timedelta(0):
        raise ValueError("on_time_tolerance 不能为负数")
    return tolerance


def _normalize_now(now: Any, *, force_fallback: bool = False) -> datetime:
    """把注入的 now 转换为北京时间 aware datetime（不读取系统时钟）。"""
    tz = get_beijing_tz(force_fallback=force_fallback)
    if isinstance(now, str):
        return to_beijing(now, force_fallback=force_fallback)
    if type(now) is date:
        raise TypeError("now 必须是带时区的 datetime 或 ISO 字符串，纯日期无法确定当天时刻")
    if not isinstance(now, datetime):
        raise TypeError(f"不支持的 now 类型: {type(now).__name__}")
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(
            "now 必须是带时区的 aware datetime；本模块不读取全局时钟，请由调用方注入"
        )
    return now.astimezone(tz)


def _normalize_existing_keys(existing_keys: Iterable[Any] | None) -> set[str]:
    """规范化已存在槽键：接受 SlotKey、槽键文本或持久化行映射。"""
    normalized: set[str] = set()
    for item in existing_keys or ():
        if isinstance(item, Slot):
            normalized.add(item.key.as_text())
        elif isinstance(item, SlotKey):
            normalized.add(item.as_text())
        elif isinstance(item, str):
            text = item.strip()
            if text:
                normalized.add(text)
        elif isinstance(item, Mapping):
            normalized.add(slot_key_from_mapping(item).as_text())
        else:
            raise TypeError(f"不支持的槽键类型: {type(item).__name__}")
    return normalized


def _require_fixed(binding: "ScheduleBinding") -> None:
    """要求绑定为固定时刻型；interval 型交给既有间隔调度。"""
    if binding.kind != JOB_KIND_FIXED:
        raise ValueError(
            "本函数只适用于固定时刻 (fixed) 绑定；interval 型沿用既有间隔调度语义"
        )


# ── 值对象 ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, order=True)
class SlotKey:
    """执行槽唯一键：``projectId / jobId / businessDate / scheduledTime``。"""

    project_id: str
    job_id: str
    business_date: date
    scheduled_time: time

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _require_text(self.project_id, "project_id"))
        object.__setattr__(self, "job_id", _require_text(self.job_id, "job_id"))
        object.__setattr__(self, "business_date", pure_date(self.business_date))
        object.__setattr__(self, "scheduled_time", _normalize_time(self.scheduled_time))

    def as_tuple(self) -> tuple[str, str, date, time]:
        """返回四元组形式，便于与数据库主键/集合比较。"""
        return (self.project_id, self.job_id, self.business_date, self.scheduled_time)

    def as_text(self) -> str:
        """返回稳定文本形式：``projectId/jobId/YYYY-MM-DD/HH:MM``。"""
        return (
            f"{self.project_id}/{self.job_id}/"
            f"{self.business_date.isoformat()}/{self.scheduled_time.strftime('%H:%M')}"
        )

    def as_dict(self) -> dict[str, Any]:
        """返回契约字段名（camelCase）映射，供持久化层直接落库。"""
        return {
            "projectId": self.project_id,
            "jobId": self.job_id,
            "businessDate": self.business_date.isoformat(),
            "scheduledTime": self.scheduled_time.strftime("%H:%M"),
        }


@dataclass(frozen=True)
class Slot:
    """一个已到点的执行槽计算结果（不是持久记录）。"""

    key: SlotKey
    scheduled_at: datetime
    status: str = STATUS_DUE
    is_catch_up: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.key, SlotKey):
            raise TypeError("Slot.key 必须是 SlotKey")
        if self.scheduled_at.tzinfo is None or self.scheduled_at.tzinfo.utcoffset(
            self.scheduled_at
        ) is None:
            raise ValueError("Slot.scheduled_at 必须是带时区的 aware datetime")
        if self.status not in (STATUS_DUE, STATUS_PAUSED_SKIPPED):
            raise ValueError(f"未知槽状态: {self.status!r}")

    @property
    def business_date(self) -> date:
        return self.key.business_date

    @property
    def scheduled_time(self) -> time:
        return self.key.scheduled_time

    def as_dict(self) -> dict[str, Any]:
        """返回契约字段名（camelCase）映射。"""
        payload = self.key.as_dict()
        payload.update(
            {
                "scheduledAt": self.scheduled_at.isoformat(),
                "status": self.status,
                "isCatchUp": self.is_catch_up,
            }
        )
        return payload


@dataclass(frozen=True)
class ScheduleBinding:
    """一个项目/任务的调度绑定（不可变值对象）。

    ``kind`` 为 ``fixed`` 时使用 ``times``；为 ``interval`` 时使用 ``interval_minutes``。
    两者同时声明即视为混用，构造时直接 ``ValueError``（C4：同一绑定只能一种）。
    """

    project_id: str
    job_id: str
    kind: str = JOB_KIND_FIXED
    times: tuple[time, ...] = ()
    interval_minutes: int | None = None
    workdays_only: bool = False
    paused: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _require_text(self.project_id, "project_id"))
        object.__setattr__(self, "job_id", _require_text(self.job_id, "job_id"))
        kind = str(self.kind or "").strip().lower()
        if kind not in _JOB_KINDS:
            raise ValueError(f"未知绑定类型: {self.kind!r}，必须属于 {_JOB_KINDS}")
        object.__setattr__(self, "kind", kind)

        raw_times = tuple(self.times or ())
        if raw_times and self.interval_minutes is not None:
            raise ValueError(
                "同一绑定不得同时声明固定时刻与 interval 间隔；固定时刻型与 interval 型互斥"
            )

        if kind == JOB_KIND_FIXED:
            if self.interval_minutes is not None:
                raise ValueError("固定时刻型绑定不得声明 interval_minutes")
            normalized = _normalize_times(raw_times)
            if not normalized:
                raise ValueError("固定时刻型绑定至少需要一个时刻")
            object.__setattr__(self, "times", normalized)
        else:
            interval = self.interval_minutes
            if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
                raise ValueError("interval 型绑定需要正整数 interval_minutes")
            if raw_times:
                raise ValueError("interval 型绑定不得声明固定时刻")

        object.__setattr__(self, "workdays_only", bool(self.workdays_only))
        object.__setattr__(self, "paused", bool(self.paused))


class SlotLedger:
    """纯内存槽键台账：拒绝重复键，保证时钟回拨下不重复产出同一执行槽。

    只保存槽键文本，不做任何 I/O；持久化由调用方（DSH-V2-19）负责。
    """

    def __init__(self, keys: Iterable[Any] | None = None) -> None:
        self._keys: set[str] = _normalize_existing_keys(keys)

    @property
    def keys(self) -> frozenset[str]:
        """当前台账中的槽键文本集合（只读快照）。"""
        return frozenset(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def __iter__(self) -> Iterator[str]:
        """按文本升序迭代槽键，便于直接作为 ``existing_keys`` 传入。"""
        return iter(sorted(self._keys))

    def __contains__(self, slot_or_key: Any) -> bool:
        if isinstance(slot_or_key, Slot):
            return slot_or_key.key.as_text() in self._keys
        if isinstance(slot_or_key, SlotKey):
            return slot_or_key.as_text() in self._keys
        return str(slot_or_key).strip() in self._keys

    def register(self, slot: Slot) -> bool:
        """登记一个槽；返回 True 表示首次登记，False 表示重复（已产出过）。"""
        if not isinstance(slot, Slot):
            raise TypeError("SlotLedger.register 只接受 Slot")
        text = slot.key.as_text()
        if text in self._keys:
            return False
        self._keys.add(text)
        return True

    def extend(self, slots: Iterable[Slot]) -> list[Slot]:
        """批量登记，只返回首次登记的槽（重复槽被丢弃）。"""
        accepted: list[Slot] = []
        for slot in slots:
            if self.register(slot):
                accepted.append(slot)
        return accepted


# ── 绑定工厂 ──────────────────────────────────────────────────────────────────


def sync_binding(
    project_id: str,
    *,
    job_id: str = SYNC_JOB_ID,
    times: Iterable[Any] = DEFAULT_SYNC_TIMES,
    paused: bool = False,
) -> ScheduleBinding:
    """构造项目状态同步绑定（默认每日北京时间 09:00、16:00）。"""
    return ScheduleBinding(
        project_id=project_id,
        job_id=job_id,
        kind=JOB_KIND_FIXED,
        times=tuple(times),
        workdays_only=False,
        paused=paused,
    )


def daily_report_binding(
    project_id: str,
    *,
    job_id: str = DAILY_REPORT_JOB_ID,
    times: Iterable[Any] = (DEFAULT_DAILY_REPORT_TIME,),
    paused: bool = False,
) -> ScheduleBinding:
    """构造日报绑定（默认周一至周五北京时间 08:30）。"""
    return ScheduleBinding(
        project_id=project_id,
        job_id=job_id,
        kind=JOB_KIND_FIXED,
        times=tuple(times),
        workdays_only=True,
        paused=paused,
    )


def interval_binding(
    project_id: str,
    *,
    job_id: str,
    interval_minutes: int,
    paused: bool = False,
) -> ScheduleBinding:
    """构造 interval 型绑定（既有 15/30/60 分钟语义，本模块不计算其槽）。"""
    return ScheduleBinding(
        project_id=project_id,
        job_id=job_id,
        kind=JOB_KIND_INTERVAL,
        times=(),
        interval_minutes=interval_minutes,
        workdays_only=False,
        paused=paused,
    )


# ── 槽键转换 ──────────────────────────────────────────────────────────────────


def slot_key_from_mapping(row: Mapping[str, Any]) -> SlotKey:
    """从持久化行映射（camelCase 或 snake_case）还原槽键。"""
    if not isinstance(row, Mapping):
        raise TypeError("slot_key_from_mapping 需要映射类型")
    scheduled_time = row.get("scheduledTime", row.get("scheduled_time"))
    business_date = row.get("businessDate", row.get("business_date"))
    if scheduled_time is None:
        raise ValueError("槽行缺少 scheduledTime")
    if business_date is None:
        raise ValueError("槽行缺少 businessDate")
    return SlotKey(
        project_id=_require_text(row.get("projectId", row.get("project_id")), "projectId"),
        job_id=_require_text(row.get("jobId", row.get("job_id")), "jobId"),
        business_date=pure_date(business_date),
        scheduled_time=_normalize_time(scheduled_time),
    )


# ── 核心计算 ──────────────────────────────────────────────────────────────────


def is_workday(
    business_date: date | str,
    workday_overrides: Mapping[Any, Any] | None = None,
) -> bool:
    """判定业务日期是否为工作日（覆盖表优先，缺省周一至周五）。"""
    return _is_workday(pure_date(business_date), _normalize_overrides(workday_overrides))


def compute_due_slots(
    binding: ScheduleBinding,
    *,
    now: datetime | str,
    existing_keys: Iterable[Any] | None = None,
    workday_overrides: Mapping[Any, Any] | None = None,
    project_paused: bool = False,
    on_time_tolerance: Any = DEFAULT_ON_TIME_TOLERANCE,
    force_fallback: bool = False,
) -> list[Slot]:
    """计算「此刻应当产出的执行槽」，只覆盖 ``now`` 所在的北京业务日期。

    规则：
    - 只返回 ``scheduledTime <= now`` 的槽；未来时刻不产出。
    - 已存在于 ``existing_keys`` 的槽不重复产出（时钟回拨/重复 tick 幂等）。
    - 非工作日（``workdays_only`` 且当天非工作日）不产出任何槽。
    - 暂停（绑定级或 ``project_paused``）时到点槽标 ``paused_skipped``，不补跑。
    - 只补当天：``now`` 之前的日期一律不产出，即使进程刚从中断/睡眠恢复。
    - 超出 ``on_time_tolerance`` 才标记 ``is_catch_up=True``。
    """
    if not isinstance(binding, ScheduleBinding):
        raise TypeError("binding 必须是 ScheduleBinding")
    _require_fixed(binding)

    now_bj = _normalize_now(now, force_fallback=force_fallback)
    tz = now_bj.tzinfo
    business_date = now_bj.date()
    overrides = _normalize_overrides(workday_overrides)

    if binding.workdays_only and not _is_workday(business_date, overrides):
        return []

    existing = _normalize_existing_keys(existing_keys)
    paused = bool(binding.paused or project_paused)
    tolerance = _normalize_tolerance(on_time_tolerance)

    slots: list[Slot] = []
    seen: set[str] = set()
    for scheduled_time in binding.times:
        scheduled_at = datetime.combine(business_date, scheduled_time).replace(tzinfo=tz)
        if scheduled_at > now_bj:
            continue
        key = SlotKey(
            project_id=binding.project_id,
            job_id=binding.job_id,
            business_date=business_date,
            scheduled_time=scheduled_time,
        )
        text = key.as_text()
        if text in existing or text in seen:
            continue
        seen.add(text)
        slots.append(
            Slot(
                key=key,
                scheduled_at=scheduled_at,
                status=STATUS_PAUSED_SKIPPED if paused else STATUS_DUE,
                is_catch_up=(not paused) and (now_bj - scheduled_at) > tolerance,
            )
        )
    return slots


def next_slot_at(
    binding: ScheduleBinding,
    *,
    now: datetime | str,
    workday_overrides: Mapping[Any, Any] | None = None,
    project_paused: bool = False,
    force_fallback: bool = False,
    horizon_days: int = DEFAULT_NEXT_SLOT_HORIZON_DAYS,
) -> datetime | None:
    """计算下一个严格晚于 ``now`` 的固定时刻（北京时间 aware datetime）。

    暂停（绑定级或项目级）时返回 ``None``：暂停期间不排下一槽。
    ``horizon_days`` 内无可用时刻（例如覆盖表把所有日期都标为非工作日）时返回 ``None``。
    """
    if not isinstance(binding, ScheduleBinding):
        raise TypeError("binding 必须是 ScheduleBinding")
    _require_fixed(binding)
    if project_paused or binding.paused:
        return None
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days < 0:
        raise ValueError("horizon_days 必须是非负整数")

    now_bj = _normalize_now(now, force_fallback=force_fallback)
    tz = now_bj.tzinfo
    overrides = _normalize_overrides(workday_overrides)
    for offset in range(horizon_days + 1):
        day = now_bj.date() + timedelta(days=offset)
        if binding.workdays_only and not _is_workday(day, overrides):
            continue
        for scheduled_time in binding.times:
            candidate = datetime.combine(day, scheduled_time).replace(tzinfo=tz)
            if candidate > now_bj:
                return candidate
    return None


# ── 绑定变更（不可变返回） ────────────────────────────────────────────────────


def add_slot_time(binding: ScheduleBinding, scheduled_time: Any) -> ScheduleBinding:
    """新增一个固定时刻（幂等）；返回新的绑定，不修改入参。"""
    _require_fixed(binding)
    target = _normalize_time(scheduled_time)
    return replace(binding, times=tuple(sorted(set(binding.times) | {target})))


def remove_slot_time(binding: ScheduleBinding, scheduled_time: Any) -> ScheduleBinding:
    """删除一个固定时刻（幂等，不存在时原样返回）；至少保留一个时刻。"""
    _require_fixed(binding)
    target = _normalize_time(scheduled_time)
    remaining = tuple(item for item in binding.times if item != target)
    if len(remaining) == len(binding.times):
        return binding
    if not remaining:
        raise ValueError("固定时刻型绑定至少保留一个时刻；如需停止请使用 pause_binding")
    return replace(binding, times=remaining)


def set_slot_times(binding: ScheduleBinding, times: Iterable[Any]) -> ScheduleBinding:
    """整体替换固定时刻集合（去重升序）；返回新的绑定。"""
    _require_fixed(binding)
    normalized = _normalize_times(times)
    if not normalized:
        raise ValueError("固定时刻型绑定至少需要一个时刻")
    return replace(binding, times=normalized)


def pause_binding(binding: ScheduleBinding, paused: bool = True) -> ScheduleBinding:
    """设置绑定级暂停标志（任务级）；返回新的绑定。"""
    return replace(binding, paused=bool(paused))


def resume_binding(binding: ScheduleBinding) -> ScheduleBinding:
    """清除绑定级暂停标志；返回新的绑定。"""
    return replace(binding, paused=False)
