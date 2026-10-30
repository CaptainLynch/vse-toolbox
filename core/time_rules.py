# -*- coding: utf-8 -*-
"""唯一时间与逾期内核 (Single Source of Truth for Time & Overdue Rules).

本模块定义统一的时间处理与逾期状态计算内核，集中收敛时区换算、纯日期隔离、
历史无时区字段解释与逾期状态机规则，避免各服务与报表实现口径分化。

核心原则：
1. aware UTC 为内部时间存储基准；北京时间 (Asia/Shanghai, UTC+8) 仅用于界面展示与导出。
2. 纯日期 (date) 与时间戳 (datetime) 严格正交隔离，绝不隐式混用，避免跨时区日期位移。
3. 历史无时区时间字段按数据源 (tdc/aras/local) 显式解释并标注依据，绝不默认追加 UTC Z 后缀。
4. 逾期状态判定为纯函数，支持基准日期 (today) 依赖注入，已完成状态永远为 ok。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
import re
from typing import Any, NamedTuple


#: 默认固定 UTC+8 时区，用于 Windows/精简环境下 zoneinfo 不可用时的回退。
#: 中国标准时间自 1992 年起无夏令时，在业务范围内固定 +08:00 偏移与 Asia/Shanghai 等价。
BEIJING_OFFSET = timezone(timedelta(hours=8), name="Asia/Shanghai")


def get_beijing_tz(*, force_fallback: bool = False) -> tzinfo:
    """获取北京时间时区对象。

    优先使用 Python 标准库 zoneinfo 获取 IANA 'Asia/Shanghai' 时区。
    在某些精简 Windows 环境或未安装 tzdata 的环境中，如果 zoneinfo 抛出
    ZoneInfoNotFoundError 或其它异常，则自动回退到固定 UTC+8 时区 (BEIJING_OFFSET)。
    中国标准时间自 1992 年起无夏令时，固定 +08:00 偏移完全满足生产口径。
    """
    if not force_fallback:
        try:
            import zoneinfo

            return zoneinfo.ZoneInfo("Asia/Shanghai")
        except Exception:
            # 捕获所有时区数据库不可用的异常，平滑回退到固定 +08:00 偏移
            pass
    return BEIJING_OFFSET


def now_utc() -> datetime:
    """获取当前时间的 aware UTC datetime。"""
    return datetime.now(timezone.utc)


def to_beijing(value: datetime | str, *, force_fallback: bool = False) -> datetime:
    """将 aware datetime 或带时区的 ISO 字符串转换为北京时间展示用 aware datetime。

    优先使用 zoneinfo Asia/Shanghai，若本机时区数据不可用则回退固定 UTC+8 实现。
    纯 date 对象或无时区 (naive) 时间将被拒绝，防止隐式时区猜测引发计算偏差。
    """
    if value is None:
        raise TypeError("value 不能为 None")

    tz = get_beijing_tz(force_fallback=force_fallback)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("时间字符串不能为空")
        # 兼容以 Z/z 结尾的 ISO 字符串（Python 3.10 及更早版本 fromisoformat 不支持直接解析 Z）
        if text.endswith("Z") or text.endswith("z"):
            normalized = text[:-1] + "+00:00"
        else:
            normalized = text
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError as err:
            raise ValueError(f"无法解析的时间字符串: {value!r}") from err

        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError(
                f"无时区时间字符串 {value!r} 无法直接转换为北京时间；"
                "请先使用 interpret_naive(value, source) 明确其业务来源与时区语义。"
            )
        return dt.astimezone(tz)

    # 注意：在 Python 中 isinstance(datetime, date) 为 True，因此必须先排除严格的 date 对象
    if type(value) is date:
        raise TypeError(
            "纯日期对象 (date) 禁止直接进行时区转换（可能引发日期跨天位移）；"
            "若需纯日期语义请使用 pure_date(value)。"
        )

    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                f"无时区 (naive) datetime {value!r} 无法直接转换为北京时间；"
                "请先使用 interpret_naive(value, source) 明确其业务来源与时区语义。"
            )
        return value.astimezone(tz)

    raise TypeError(f"不支持的时间转换类型: {type(value).__name__}")


def format_beijing(value: datetime | str, *, force_fallback: bool = False) -> str:
    """输出北京时间格式化字符串「YYYY-MM-DD HH:mm」。"""
    dt = to_beijing(value, force_fallback=force_fallback)
    return dt.strftime("%Y-%m-%d %H:%M")


def pure_date(value: date | str) -> date:
    """纯日期语义转换器。

    明确标注「纯日期，不做时区转换」语义。只接受严格的 date 对象（排除 datetime）
    或 'YYYY-MM-DD' 格式的纯日期字符串，原样返回 date。
    任何带时间分量、带时区或格式不符的输入均抛出异常，防止静默产生跨时区日期位移。
    """
    if value is None:
        raise TypeError("pure_date 不接受 None 输入")
    # datetime 是 date 的子类，必须严格排除带时间的 datetime 对象
    if isinstance(value, datetime):
        raise TypeError("pure_date 只接受纯 date 对象，不接受带时间或时区的 datetime 对象")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError(f"pure_date 仅接受 'YYYY-MM-DD' 格式纯日期字符串，收到: {value!r}")
        try:
            return date.fromisoformat(text)
        except ValueError as err:
            raise ValueError(f"无效的日历日期字符串: {value!r}") from err
    raise TypeError(f"pure_date 仅接受 date 或 YYYY-MM-DD 字符串，不支持的类型: {type(value).__name__}")


class InterpretedDatetime(NamedTuple):
    """带解释依据标注的无时区时间解释结果。"""

    dt: datetime
    source: str
    tz_name: str
    rationale: str

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if hasattr(self, item):
                return getattr(self, item)
            raise KeyError(item)
        # NamedTuple 元类不传播 __classcell__，零参 super() 在类体方法里会触发
        # RuntimeError（CPython typing 实现）；显式基类调用绕开。
        return tuple.__getitem__(self, item)

    def to_beijing(self, *, force_fallback: bool = False) -> datetime:
        """快速转为北京时间 aware datetime。"""
        return to_beijing(self.dt, force_fallback=force_fallback)

    def format_beijing(self, *, force_fallback: bool = False) -> str:
        """快速格式化为「YYYY-MM-DD HH:mm」北京时间字符串。"""
        return format_beijing(self.dt, force_fallback=force_fallback)

    def to_dict(self) -> dict[str, Any]:
        return {
            "datetime": self.dt.isoformat(),
            "source": self.source,
            "tz_name": self.tz_name,
            "rationale": self.rationale,
        }


def interpret_naive(
    value: datetime | str | date,
    source: str,
    *,
    force_fallback: bool = False,
) -> InterpretedDatetime:
    """解释历史无时区时间字段。

    按 source 属于 'tdc'、'aras'、'local' 三者之一进行确定性解释，
    返回带解释依据标注的结果，绝不默认追加 UTC Z 后缀（避免历史代码中
    将中国本地业务时间盲目当作 UTC 处理导致的 8 小时偏差）。

    - tdc: SGMW TDC 敏捷协同系统报表，按北京时间 (Asia/Shanghai, UTC+8) 解释。
    - aras: ARAS Innovator ECM 审批数据，按企业部署标准时间 (Asia/Shanghai, UTC+8) 解释。
    - local: 本地客户端/宿主系统时间，按当前操作系统本地时区解释。
    """
    if value is None:
        raise TypeError("value 不能为 None")

    source_key = str(source or "").strip().lower()
    if source_key not in ("tdc", "aras", "local"):
        raise ValueError(f"未知的数据来源: {source!r}，source 必须属于 'tdc'、'aras'、'local' 之一")

    if isinstance(value, datetime):
        if value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None:
            raise ValueError(f"value 已包含时区信息 ({value.tzinfo})，无需作为无时区历史字段解释")
        naive_dt = value
    elif type(value) is date:
        # 纯日期按当天零点补全为 naive datetime
        naive_dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("字符串不能为空")
        # 若已包含 UTC 'Z' 或显式时区偏移，则不属于 naive 时间
        if text.endswith("Z") or text.endswith("z") or re.search(r"[+-]\d{2}:\d{2}$", text):
            raise ValueError(f"字符串 {value!r} 已包含时区指示，无需作为无时区历史字段解释")
        # 统一将斜杠日期替换为破折号后解析
        normalized = text.replace("/", "-")
        try:
            naive_dt = datetime.fromisoformat(normalized)
        except ValueError:
            # 尝试纯日期格式解析
            parsed_d = pure_date(normalized)
            naive_dt = datetime.combine(parsed_d, datetime.min.time())
    else:
        raise TypeError(f"不支持的时间类型: {type(value).__name__}")

    if source_key == "tdc":
        tz = get_beijing_tz(force_fallback=force_fallback)
        aware_dt = naive_dt.replace(tzinfo=tz)
        tz_name = "Asia/Shanghai"
        rationale = "TDC 系统导出报表及协同接口时间戳按北京时间 (Asia/Shanghai, UTC+8) 解释，绝不追加 UTC Z 后缀"
    elif source_key == "aras":
        tz = get_beijing_tz(force_fallback=force_fallback)
        aware_dt = naive_dt.replace(tzinfo=tz)
        tz_name = "Asia/Shanghai"
        rationale = "ARAS Innovator ECM 审批流程时间戳按企业标准时间 (Asia/Shanghai, UTC+8) 解释，绝不追加 UTC Z 后缀"
    else:  # local
        # 宿主系统本地时间：按操作系统本地时区解释
        aware_dt = naive_dt.astimezone()
        tz_name = getattr(aware_dt.tzinfo, "key", None) or str(aware_dt.tzinfo)
        rationale = "本地客户端/宿主系统无时区时间戳按当前宿主操作系统本地时区解释，绝不默认追加 UTC Z 后缀"

    return InterpretedDatetime(dt=aware_dt, source=source_key, tz_name=tz_name, rationale=rationale)


class OverdueState(NamedTuple):
    """逾期状态机计算结果。"""

    state: str  # "ok" | "due_soon" | "overdue"
    days: int  # 逾期天数（若逾期）或剩余天数（若未逾期）
    unset: bool = False  # 是否未设置计划日期标记

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if hasattr(self, item):
                return getattr(self, item)
            raise KeyError(item)
        # NamedTuple 元类不传播 __classcell__，零参 super() 在类体方法里会触发
        # RuntimeError（CPython typing 实现）；显式基类调用绕开。
        return tuple.__getitem__(self, item)

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "days": self.days, "unset": self.unset}


def overdue_state(
    planned_date: date | str | None,
    completed: object,
    today: date | str | None = None,
    due_soon_days: int = 3,
) -> OverdueState:
    """计算逾期状态。

    返回 state 属于 'ok'、'due_soon'、'overdue' 之一，并附带天数 (days) 及 unset 标记。
    - completed 为真值时永远为 'ok'，days 为 0。
    - planned_date 为空时返回 'ok' 且 unset=True，days 为 0。
    - today 可注入，缺省为北京时间当前日期。
    - 当天到期 (planned == today) 属于 due_soon，days 为 0。
    - 逾期 (planned < today) 时 state='overdue'，days 为正整数逾期天数。
    - 即将到期 (0 <= planned - today <= due_soon_days) 时 state='due_soon'，days 为剩余天数。
    - 正常未到期 (planned - today > due_soon_days) 时 state='ok'，days 为剩余天数。
    """
    is_planned_empty = planned_date is None or (
        isinstance(planned_date, str) and not planned_date.strip()
    )

    if is_planned_empty:
        return OverdueState(state="ok", days=0, unset=True)

    if bool(completed):
        return OverdueState(state="ok", days=0, unset=False)

    p_date = pure_date(planned_date)
    t_date = pure_date(today) if today is not None else to_beijing(now_utc()).date()

    diff = (p_date - t_date).days

    if diff < 0:
        return OverdueState(state="overdue", days=-diff, unset=False)
    if diff <= due_soon_days:
        return OverdueState(state="due_soon", days=diff, unset=False)
    return OverdueState(state="ok", days=diff, unset=False)
