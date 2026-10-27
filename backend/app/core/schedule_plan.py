"""每日调度时间表与 Cron 组合工具。

同步任务和指标批次需要在同一天执行多个时点。APScheduler 的单个
``CronTrigger`` 无法表达多个时点的组合，因此这里统一
用分号分隔的多个 Cron 表达式，再组合成 ``OrTrigger``。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

SCHEDULE_TIMEZONE = "Asia/Shanghai"
SCHEDULE_TZ = ZoneInfo(SCHEDULE_TIMEZONE)

# 同步任务与指标批次统一使用四个每日时点。
SYNC_SCHEDULE_TIMES: tuple[tuple[int, int], ...] = ((0, 0), (7, 0), (12, 0), (18, 0))
METRIC_CALC_TIMES: tuple[tuple[int, int], ...] = SYNC_SCHEDULE_TIMES

MULTI_CRON_SEPARATOR = ";"


def _split_expressions(cron_expr: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]+", cron_expr or "") if part.strip()]


def _normalize_fields(expr: str) -> tuple[str, str, str, str, str, str, str]:
    """把 5/6/7 段 Cron 统一成 7 段，并兼容 Quartz 的 ``?``。"""
    fields = (expr or "").strip().split()
    if len(fields) == 5:
        fields = ["0", *fields]
    if len(fields) == 6:
        fields.append("*")
    if len(fields) != 7:
        raise ValueError("Cron 表达式格式错误，应为 5/6/7 段")
    fields = [field if field != "?" else "*" for field in fields]
    return tuple(fields)  # type: ignore[return-value]


def _format_cron(
    second: str,
    minute: str,
    hour: str,
    day: str = "*",
    month: str = "*",
    day_of_week: str = "?",
    year: str = "*",
) -> str:
    text = f"{second} {minute} {hour} {day} {month} {day_of_week}"
    if year and year != "*":
        text = f"{text} {year}"
    return text


def build_daily_trigger(
    times: tuple[tuple[int, int], ...],
    timezone: str = SCHEDULE_TIMEZONE,
) -> BaseTrigger:
    """把若干 ``(hour, minute)`` 组合成一个每日触发器。"""
    triggers = [
        CronTrigger(
            second="0",
            minute=str(minute),
            hour=str(hour),
            timezone=timezone,
        )
        for hour, minute in times
    ]
    if not triggers:
        raise ValueError("至少需要一个每日执行时点")
    return triggers[0] if len(triggers) == 1 else OrTrigger(triggers)


def build_cron_trigger(cron_expr: str) -> BaseTrigger:
    """解析单条或分号分隔的多条 Cron，返回组合触发器。"""
    expressions = _split_expressions(cron_expr)
    if not expressions:
        raise ValueError("Cron 表达式为空")
    triggers: list[BaseTrigger] = []
    for expr in expressions:
        second, minute, hour, day, month, day_of_week, year = _normalize_fields(expr)
        triggers.append(
            CronTrigger(
                second=second,
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                year=year,
                timezone=SCHEDULE_TIMEZONE,
            )
        )
    return triggers[0] if len(triggers) == 1 else OrTrigger(triggers)


def build_sync_cron(year: str = "*") -> str:
    """生成“00:00 + 07:00 + 12:00 + 18:00”的同步 Cron 字符串。"""
    return MULTI_CRON_SEPARATOR.join(
        _format_cron("0", str(minute), str(hour), year=year) for hour, minute in SYNC_SCHEDULE_TIMES
    )


DEFAULT_SYNC_CRON = build_sync_cron()


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_time(expr: str, hour: int, minute: int) -> bool:
    try:
        _second, minute_field, hour_field, _day, _month, _dow, _year = _normalize_fields(expr)
    except ValueError:
        return False
    return _as_int(hour_field) == hour and _as_int(minute_field) == minute


def normalize_sync_cron(cron_expr: str) -> str:
    """把既有的单次/每周同步 Cron 规范为每日 4 次。

    统一为 00:00、07:00、12:00、18:00；原有星期/日期限制会被移除。带固定年份
    的任务（例如零售推送的 2000 年永不触发任务）保持原样。
    """
    raw = (cron_expr or "").strip()
    if not raw:
        return raw
    expressions = _split_expressions(raw)

    try:
        _second, _minute, _hour, _day, _month, _dow, year = _normalize_fields(expressions[0])
    except (IndexError, ValueError):
        return raw
    if year != "*":
        return raw

    if all(any(_has_time(expr, hour, minute) for expr in expressions) for hour, minute in SYNC_SCHEDULE_TIMES):
        return raw
    return build_sync_cron()


def cron_has_fire_at(cron_expr: str, when: datetime, tolerance_seconds: int = 90) -> bool:
    """判断 Cron 是否会在 ``when`` 附近触发（用于筛选当轮应完成的同步任务）。"""
    trigger = build_cron_trigger(cron_expr)
    probe = when - timedelta(seconds=max(tolerance_seconds, 1))
    fire_time = trigger.get_next_fire_time(None, probe)
    if fire_time is None:
        return False
    if fire_time.tzinfo is None:
        fire_time = fire_time.replace(tzinfo=SCHEDULE_TZ)
    return abs((fire_time - when).total_seconds()) <= tolerance_seconds


def latest_schedule_slot(now: datetime | None = None) -> datetime:
    """返回当前应归属的最近一个每日批次时点。"""
    current = now or datetime.now(SCHEDULE_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SCHEDULE_TZ)
    candidates = [
        current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for hour, minute in SYNC_SCHEDULE_TIMES
    ]
    past = [candidate for candidate in candidates if candidate <= current]
    return max(past) if past else candidates[-1] - timedelta(days=1)


def is_month_settlement_run(now: datetime | None = None) -> bool:
    """当前是否归属 00:00 轮次（每月 1 日只在该轮次做上月结转）。"""
    slot = latest_schedule_slot(now)
    return slot.hour == 0 and slot.minute == 0
