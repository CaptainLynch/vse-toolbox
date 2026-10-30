# -*- coding: utf-8 -*-
"""Focused unit tests for core/time_rules.py.

验证内容：
1. aware 往返一致性与 UTC/北京时间双向转换；
2. 纯日期 (pure_date) 不做时区转换、不发生跨时区跨天位移；
3. 无时区历史字段 (interpret_naive) 按 tdc/aras/local 解释，绝不追加 UTC Z；
4. 逾期状态机 (overdue_state) 边界条件：当天到期、due_soon 边界、completed 覆盖、跨月与年末；
5. Windows/精简环境下无 zoneinfo 数据库时的 UTC+8 兜底回退路径。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import pytest

import core.time_rules as tr
from core.time_rules import (
    BEIJING_OFFSET,
    InterpretedDatetime,
    OverdueState,
    format_beijing,
    get_beijing_tz,
    now_utc,
    overdue_state,
    pure_date,
    interpret_naive,
    to_beijing,
)


# ── 1. now_utc and get_beijing_tz Fallback ─────────────────────────────────────


def test_now_utc_returns_aware_utc() -> None:
    """now_utc() 必须返回 tzinfo=UTC 的 aware datetime。"""
    now = now_utc()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc
    assert now.utcoffset() == timedelta(0)


def test_get_beijing_tz_fallback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 无时区数据环境回退路径测试：ZoneInfo 不可用时平滑回退到固定 UTC+8。"""
    # 1. 显式强制回退路径
    fallback_tz = get_beijing_tz(force_fallback=True)
    assert fallback_tz == BEIJING_OFFSET
    assert fallback_tz.utcoffset(None) == timedelta(hours=8)

    # 2. 模拟系统未安装 tzdata 导致 ZoneInfo 抛出异常
    def _mock_zone_info(_name: str) -> None:
        raise tr.re.error("ZoneInfoNotFoundError simulated")

    import zoneinfo

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _mock_zone_info)
    tz = get_beijing_tz()
    assert tz == BEIJING_OFFSET
    assert tz.utcoffset(None) == timedelta(hours=8)


# ── 2. to_beijing and Aware Roundtrip ──────────────────────────────────────────


def test_to_beijing_aware_roundtrip() -> None:
    """aware UTC -> to_beijing() -> astimezone(UTC) 必须完全可逆且时间戳无漂移。"""
    test_cases = [
        datetime(2026, 10, 31, 14, 30, 0, tzinfo=timezone.utc),
        # 跨月：UTC 10月31日 20点 -> 北京时间 11月1日 04点
        datetime(2026, 10, 31, 20, 0, 0, tzinfo=timezone.utc),
        # 年末跨年：UTC 12月31日 20点 -> 北京时间 次年1月1日 04点
        datetime(2026, 12, 31, 20, 0, 0, tzinfo=timezone.utc),
        # 带微秒
        datetime(2026, 5, 1, 8, 12, 34, 567890, tzinfo=timezone.utc),
    ]

    for utc_dt in test_cases:
        # 路径 A: zoneinfo / 默认时区
        bj_dt = to_beijing(utc_dt)
        assert bj_dt.tzinfo is not None
        assert bj_dt.utcoffset() == timedelta(hours=8)
        assert bj_dt.timestamp() == utc_dt.timestamp()
        roundtrip_utc = bj_dt.astimezone(timezone.utc)
        assert roundtrip_utc == utc_dt

        # 路径 B: 强制固定 UTC+8 回退路径
        bj_fallback = to_beijing(utc_dt, force_fallback=True)
        assert bj_fallback.tzinfo == BEIJING_OFFSET
        assert bj_fallback.utcoffset() == timedelta(hours=8)
        assert bj_fallback.timestamp() == utc_dt.timestamp()
        assert bj_fallback.astimezone(timezone.utc) == utc_dt


def test_to_beijing_iso_string_with_tz() -> None:
    """支持带时区后缀（Z 或 +08:00 等）的 ISO 格式时间字符串转换为北京时间。"""
    # UTC 'Z' 格式
    dt1 = to_beijing("2026-10-03T01:23:45.123456Z")
    assert dt1.hour == 9
    assert dt1.minute == 23
    assert dt1.second == 45
    assert dt1.utcoffset() == timedelta(hours=8)

    # 已带 +08:00
    dt2 = to_beijing("2026-10-03T09:23:45+08:00")
    assert dt2.hour == 9
    assert dt2.minute == 23


def test_to_beijing_rejects_naive_and_pure_date() -> None:
    """严禁对 naive 时间或纯 date 进行盲目时区转换，必须显式拦截并给出清晰指引。"""
    # 1. naive datetime 被拦截
    naive_dt = datetime(2026, 10, 3, 9, 23)
    with pytest.raises(ValueError, match="interpret_naive"):
        to_beijing(naive_dt)

    # 2. naive 字符串被拦截
    with pytest.raises(ValueError, match="interpret_naive"):
        to_beijing("2026-10-03 09:23:00")

    # 3. 严格的纯 date 对象被拦截
    d = date(2026, 10, 3)
    with pytest.raises(TypeError, match="pure_date"):
        to_beijing(d)

    # 4. None / 空串
    with pytest.raises(TypeError, match="None"):
        to_beijing(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="不能为空"):
        to_beijing("   ")


def test_format_beijing() -> None:
    """format_beijing() 统一输出「YYYY-MM-DD HH:mm」格式。"""
    # aware UTC
    utc_dt = datetime(2026, 10, 3, 1, 23, 45, tzinfo=timezone.utc)
    assert format_beijing(utc_dt) == "2026-10-03 09:23"

    # ISO 字符串
    assert format_beijing("2026-10-03T01:23:45Z") == "2026-10-03 09:23"

    # 跨日转换：UTC 23:30 -> 北京时间次日 07:30
    utc_night = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    assert format_beijing(utc_night) == "2026-11-01 07:30"

    # 回退路径
    assert format_beijing(utc_dt, force_fallback=True) == "2026-10-03 09:23"


# ── 3. pure_date ───────────────────────────────────────────────────────────────


def test_pure_date_semantics_and_no_shift() -> None:
    """纯日期不做时区转换，原样返回 date，拒绝 datetime 与不合规字符串。"""
    # 1. 严格 date 输入
    orig = date(2026, 10, 31)
    assert pure_date(orig) is orig

    # 2. 合法 YYYY-MM-DD 字符串输入
    assert pure_date("2026-10-31") == date(2026, 10, 31)
    assert pure_date("  2026-01-05  ") == date(2026, 1, 5)

    # 3. 拒绝带时间的 datetime 对象（即使时间是 00:00）
    with pytest.raises(TypeError, match="只接受纯 date 对象"):
        pure_date(datetime(2026, 10, 31, 0, 0))

    # 4. 拒绝带时间的字符串（避免隐式截断产生歧义）
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        pure_date("2026-10-31T00:00:00Z")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        pure_date("2026-10-31 12:00:00")

    # 5. 拒绝斜杠或非标准格式
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        pure_date("2026/10/31")

    # 6. 拒绝不存在的日历日期
    with pytest.raises(ValueError, match="无效的日历日期"):
        pure_date("2026-02-30")

    # 7. 拒绝 None
    with pytest.raises(TypeError, match="None"):
        pure_date(None)  # type: ignore[arg-type]


# ── 4. interpret_naive (tdc, aras, local) ──────────────────────────────────────


def test_interpret_naive_tdc_at_least_two_cases() -> None:
    """TDC 来源无时区时间按北京时间解释，绝不追加 UTC Z。"""
    # 案例 1: 报表无时区字符串
    r1 = interpret_naive("2026-08-01 10:00:00", "tdc")
    assert isinstance(r1, InterpretedDatetime)
    assert r1.source == "tdc"
    assert r1.tz_name == "Asia/Shanghai"
    assert r1.dt.utcoffset() == timedelta(hours=8)
    assert r1.dt.hour == 10
    assert not r1.dt.isoformat().endswith("Z")
    assert "+08:00" in r1.dt.isoformat()
    assert "TDC" in r1.rationale

    # 案例 2: naive datetime 对象
    naive = datetime(2026, 5, 20, 16, 45)
    r2 = interpret_naive(naive, "tdc")
    assert r2.dt.utcoffset() == timedelta(hours=8)
    assert r2.dt.hour == 16
    assert r2.format_beijing() == "2026-05-20 16:45"


def test_interpret_naive_aras_at_least_two_cases() -> None:
    """ARAS 来源无时区时间按企业部署标准时间（北京时间）解释，绝不追加 UTC Z。"""
    # 案例 1: 审批历史无时区字符串
    r1 = interpret_naive("2026-09-01 09:15:00", "aras")
    assert r1.source == "aras"
    assert r1.dt.utcoffset() == timedelta(hours=8)
    assert r1.dt.hour == 9
    assert not r1.dt.isoformat().endswith("Z")
    assert "+08:00" in r1.dt.isoformat()
    assert "ARAS" in r1.rationale

    # 案例 2: 年末 naive datetime 对象
    naive = datetime(2026, 12, 31, 23, 59)
    r2 = interpret_naive(naive, "aras")
    assert r2.dt.utcoffset() == timedelta(hours=8)
    assert r2.dt.year == 2026
    assert r2.dt.month == 12
    assert r2.dt.day == 31
    assert r2.format_beijing() == "2026-12-31 23:59"


def test_interpret_naive_local_at_least_two_cases() -> None:
    """local 来源按宿主操作系统本地时区解释。"""
    # 案例 1: 本地时间字符串
    r1 = interpret_naive("2026-07-01 12:00:00", "local")
    assert r1.source == "local"
    assert r1.dt.tzinfo is not None
    assert "本地" in r1.rationale
    assert not r1.dt.isoformat().endswith("Z")

    # 案例 2: naive datetime 对象
    naive = datetime(2026, 1, 15, 8, 30)
    r2 = interpret_naive(naive, "local")
    assert r2.dt.hour == 8
    assert r2.source == "local"


def test_interpret_naive_rejections() -> None:
    """来源未知或已有时区信息时拒绝解释。"""
    # 未知来源
    with pytest.raises(ValueError, match="未知的数据来源"):
        interpret_naive("2026-08-01 10:00:00", "unknown_source")

    # 已经带 UTC 时区
    aware_dt = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="已包含时区信息"):
        interpret_naive(aware_dt, "tdc")

    # 已经带 Z 后缀字符串
    with pytest.raises(ValueError, match="已包含时区指示"):
        interpret_naive("2026-08-01T10:00:00Z", "tdc")

    # 已经带 +08:00 偏移字符串
    with pytest.raises(ValueError, match="已包含时区指示"):
        interpret_naive("2026-08-01T10:00:00+08:00", "aras")


def test_interpret_naive_access_and_dict() -> None:
    """InterpretedDatetime 支持属性访问、字典键访问与 to_dict 导出。"""
    res = interpret_naive("2026-08-01 10:00:00", "tdc")
    assert res.source == "tdc"
    assert res["source"] == "tdc"
    d = res.to_dict()
    assert d["source"] == "tdc"
    assert d["tz_name"] == "Asia/Shanghai"
    assert "datetime" in d
    assert "rationale" in d


# ── 5. overdue_state and Boundaries ────────────────────────────────────────────


def test_overdue_state_completed_override() -> None:
    """completed 为真值时永远为 ok，days 为 0，即使已过计划日期。"""
    today = date(2026, 8, 23)

    # 1. 计划日期已过，但已完成 -> ok
    res1 = overdue_state("2026-08-01", completed=True, today=today)
    assert res1.state == "ok"
    assert res1.days == 0
    assert res1.unset is False

    # 2. 计划日期在未来，已完成 -> ok
    res2 = overdue_state("2026-09-01", completed=True, today=today)
    assert res2.state == "ok"
    assert res2.days == 0

    # 3. 各种真值形式：1, "yes", 列表等
    assert overdue_state("2026-08-01", completed=1, today=today).state == "ok"
    assert overdue_state("2026-08-01", completed="true", today=today).state == "ok"

    # 4. 计划日期为空且已完成 -> ok 且 unset=True
    res4 = overdue_state(None, completed=True, today=today)
    assert res4.state == "ok"
    assert res4.days == 0
    assert res4.unset is True


def test_overdue_state_unset_planned_date() -> None:
    """planned_date 为空时返回 ok 且带 unset=True 标记。"""
    today = date(2026, 8, 23)

    # None
    r1 = overdue_state(None, completed=False, today=today)
    assert r1.state == "ok"
    assert r1.days == 0
    assert r1.unset is True

    # 空字符串
    r2 = overdue_state("", completed=False, today=today)
    assert r2.state == "ok"
    assert r2.days == 0
    assert r2.unset is True

    # 纯空格
    r3 = overdue_state("   ", completed=False, today=today)
    assert r3.state == "ok"
    assert r3.days == 0
    assert r3.unset is True


def test_overdue_state_today_boundary() -> None:
    """当天到期边界：planned == today 属于 due_soon，剩余 0 天。"""
    today = date(2026, 8, 23)
    res = overdue_state("2026-08-23", completed=False, today=today, due_soon_days=3)
    assert res.state == "due_soon"
    assert res.days == 0
    assert res.unset is False


def test_overdue_state_due_soon_boundaries() -> None:
    """due_soon_days 临界边界测试。"""
    today = date(2026, 8, 23)
    due_soon_days = 3

    # diff = 1 (2026-08-24): 即将到期，剩余 1 天
    r1 = overdue_state("2026-08-24", completed=False, today=today, due_soon_days=due_soon_days)
    assert r1.state == "due_soon"
    assert r1.days == 1

    # diff = 2 (2026-08-25): 即将到期，剩余 2 天
    r2 = overdue_state("2026-08-25", completed=False, today=today, due_soon_days=due_soon_days)
    assert r2.state == "due_soon"
    assert r2.days == 2

    # diff = 3 (2026-08-26): 即将到期正好压在边界上，剩余 3 天
    r3 = overdue_state("2026-08-26", completed=False, today=today, due_soon_days=due_soon_days)
    assert r3.state == "due_soon"
    assert r3.days == 3

    # diff = 4 (2026-08-27): 超过边界，属于正常未到期 (ok)，剩余 4 天
    r4 = overdue_state("2026-08-27", completed=False, today=today, due_soon_days=due_soon_days)
    assert r4.state == "ok"
    assert r4.days == 4

    # 自定义 due_soon_days=0 时：只有当天为 due_soon，次日即为 ok
    r_zero_today = overdue_state("2026-08-23", completed=False, today=today, due_soon_days=0)
    assert r_zero_today.state == "due_soon"
    assert r_zero_today.days == 0
    r_zero_tomorrow = overdue_state("2026-08-24", completed=False, today=today, due_soon_days=0)
    assert r_zero_tomorrow.state == "ok"
    assert r_zero_tomorrow.days == 1


def test_overdue_state_overdue_days() -> None:
    """已逾期计算：planned < today 时返回 state='overdue' 且 days 为正整数逾期天数。"""
    today = date(2026, 8, 23)

    # 逾期 1 天
    r1 = overdue_state("2026-08-22", completed=False, today=today)
    assert r1.state == "overdue"
    assert r1.days == 1

    # 逾期 5 天（对齐现有测试：2026-08-18 vs 2026-08-23）
    r5 = overdue_state("2026-08-18", completed=False, today=today)
    assert r5.state == "overdue"
    assert r5.days == 5


def test_overdue_state_cross_month_and_year_end() -> None:
    """跨月与年末日期边界计算（闰年、月份天数切换）。"""
    # 1. 跨月即将到期：1月31日 -> 2月1日（1天）
    r_month = overdue_state("2026-02-01", completed=False, today="2026-01-31", due_soon_days=3)
    assert r_month.state == "due_soon"
    assert r_month.days == 1

    # 2. 平年跨月逾期：3月1日看2月28日（已逾期1天）
    r_month_over = overdue_state("2026-02-28", completed=False, today="2026-03-01")
    assert r_month_over.state == "overdue"
    assert r_month_over.days == 1

    # 3. 闰年2月29日：2024-02-28 看 2024-02-29
    r_leap = overdue_state("2024-02-29", completed=False, today="2024-02-28", due_soon_days=3)
    assert r_leap.state == "due_soon"
    assert r_leap.days == 1

    # 4. 年末跨年即将到期：12月31日 -> 次年1月1日
    r_year = overdue_state("2027-01-01", completed=False, today="2026-12-31", due_soon_days=3)
    assert r_year.state == "due_soon"
    assert r_year.days == 1

    # 5. 年末跨年逾期：次年1月2日看上年12月31日
    r_year_over = overdue_state("2026-12-31", completed=False, today="2027-01-02")
    assert r_year_over.state == "overdue"
    assert r_year_over.days == 2


def test_overdue_state_today_injection() -> None:
    """today 参数支持注入 date、字符串或使用缺省（当前系统北京日期）。"""
    # 注入 date
    r1 = overdue_state("2026-08-25", completed=False, today=date(2026, 8, 23))
    assert r1.days == 2

    # 注入字符串
    r2 = overdue_state("2026-08-25", completed=False, today="2026-08-23")
    assert r2.days == 2

    # 缺省 today（不报错即可）
    r_default = overdue_state("2099-01-01", completed=False)
    assert r_default.state == "ok"
    assert r_default.days > 0


def test_overdue_state_access_conventions() -> None:
    """OverdueState 结构支持属性访问、下标解构、字典键访问与 to_dict。"""
    res = overdue_state("2026-08-25", completed=False, today="2026-08-23")
    # 属性
    assert res.state == "due_soon"
    assert res.days == 2
    assert res.unset is False
    # 字典键
    assert res["state"] == "due_soon"
    assert res["days"] == 2
    assert res["unset"] == False
    # 解构
    state, days, unset = res
    assert state == "due_soon"
    assert days == 2
    assert unset is False
    # to_dict
    assert res.to_dict() == {"state": "due_soon", "days": 2, "unset": False}
