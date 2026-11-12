"""企业微信打卡工时计算。

口径与旧 PHP 接口 ``QwApi::getWorkTime`` 保持一致：

- 正常工时：每个出勤日 ``max(0, regular_work_sec - 5400)``；
- 加班：每个有打卡日 ``max(0, lastest_time - 当天规定下班时间 - 1800)``；
- 规定下班时间：``max(rule_info.checkintime[].off_work_sec)``，取不到兜底 18:00；
- ``lastest_time > 86400`` 视为跨夜打卡。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")

# 中午休息 12:00~13:30，共 1.5 小时
NOON_BREAK_SEC = 5400
# 加班结算扣除的吃饭时间 30 分钟
MEAL_BREAK_SEC = 1800
# 规则取不到下班时间时的兜底值：18:00
DEFAULT_OFF_WORK_SEC = 64800
# 超过次日 0 点视为跨夜打卡
CROSS_DAY_SEC = 86400
# 企微实际出数人数低于应统计人数的比例时给出告警
MIN_USER_RATIO = 0.3
# 营销人员工号前缀
DEFAULT_MARKETING_PREFIX = "YG20"
# 企微打卡日报单次查询跨度上限（按文档保守取 30 天）
CHECKIN_CHUNK_DAYS = 30
# 单次补数最大跨度，避免误传参数把接口拖死
MAX_RANGE_DAYS = 366


def as_int(value: Any, default: int = 0) -> int:
    """把接口里的数字/数字字符串转成 int，异常值退回默认值。"""
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def seconds_to_hhmmss(sec: int | None) -> str:
    """秒数转 HH:MM:SS；跨夜值会大于 24 小时（如 25:30:00）。"""
    total = max(0, as_int(sec))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def off_work_sec_from_rule(base_info: dict[str, Any]) -> int:
    """取当天规定下班时间（当日 0 点起的秒数）。"""
    rule = base_info.get("rule_info") or {}
    checkintime = rule.get("checkintime") or []
    if not isinstance(checkintime, list):
        return DEFAULT_OFF_WORK_SEC
    offsets = [as_int(item.get("off_work_sec")) for item in checkintime if isinstance(item, dict)]
    max_offset = max(offsets) if offsets else 0
    return max_offset if max_offset > 0 else DEFAULT_OFF_WORK_SEC


def parse_work_date(value: Any) -> date | None:
    """解析企微日报的日期字段（时间戳或 YYYY-MM-DD）。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and int(value) > 0:
        return datetime.fromtimestamp(int(value), CN_TZ).date()
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), CN_TZ).date()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_checkin_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """把企微日报的一条 ``datas`` 拍平成数据库行。"""
    base = item.get("base_info") or {}
    summary = item.get("summary_info") or {}
    userid = str(base.get("acctid") or base.get("userid") or "").strip()
    work_date = parse_work_date(base.get("date"))
    if not userid or work_date is None:
        return None

    latest = as_int(summary.get("lastest_time"))
    return {
        "userid": userid,
        "name": str(base.get("name") or ""),
        "work_date": work_date,
        "earliest_sec": as_int(summary.get("earliest_time")),
        "latest_sec": latest,
        "regular_work_sec": as_int(summary.get("regular_work_sec")),
        "off_work_sec": off_work_sec_from_rule(base),
        "cross_day": latest > CROSS_DAY_SEC,
        "raw_json": item,
    }


def iter_date_chunks(
    start: date,
    end: date,
    days: int = CHECKIN_CHUNK_DAYS,
) -> Iterable[tuple[date, date]]:
    """按闭区间切分日期，默认每段 30 天。"""
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    step = max(1, days)
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=step - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def daily_overtime_sec(latest_sec: int, off_work_sec: int) -> int:
    """单日加班秒数：超过规定下班时间后，再扣 30 分钟吃饭时间。"""
    if latest_sec <= off_work_sec:
        return 0
    return max(0, latest_sec - off_work_sec - MEAL_BREAK_SEC)


def aggregate_worktime(
    rows: Iterable[dict[str, Any]],
    active_users: dict[str, str],
    expected_user_count: int | None = None,
) -> dict[str, Any]:
    """按人、按天汇总正常工时与加班。"""
    # 同一人同一天只保留最后一条，避免重复数据被累加两次
    normalized: dict[tuple[str, date], dict[str, Any]] = {}
    for row in rows:
        userid = str(row.get("userid") or "").strip()
        if not userid:
            continue
        work_date = row.get("work_date")
        if isinstance(work_date, str):
            work_date = parse_work_date(work_date)
        if not isinstance(work_date, date):
            continue
        normalized[(userid, work_date)] = row

    by_user: dict[str, dict[str, Any]] = {}
    overtime_detail: list[dict[str, Any]] = []
    by_day: list[dict[str, Any]] = []
    cross_day_count = 0

    for (userid, work_date), row in sorted(normalized.items(), key=lambda item: (item[0][1], item[0][0])):
        name = str(row.get("name") or active_users.get(userid) or "")
        day_sec = as_int(row.get("regular_work_sec"))
        earliest = as_int(row.get("earliest_sec"))
        latest = as_int(row.get("latest_sec"))
        off_work = as_int(row.get("off_work_sec"), DEFAULT_OFF_WORK_SEC) or DEFAULT_OFF_WORK_SEC
        cross_day = bool(row.get("cross_day")) or latest > CROSS_DAY_SEC
        overtime_sec = daily_overtime_sec(latest, off_work)

        user = by_user.get(userid)
        if user is None:
            user = {
                "userid": userid,
                "name": name,
                "workDays": 0,
                "rawSec": 0,
                "regularSec": 0,
                "noonBreakSec": 0,
                "regularHours": 0.0,
                "overtimeSec": 0,
                "overtimeHours": 0.0,
                "overtimeDays": 0,
                "crossDays": 0,
            }
            by_user[userid] = user

        if day_sec > 0:
            user["workDays"] += 1
            user["rawSec"] += day_sec
            user["noonBreakSec"] += NOON_BREAK_SEC
            user["regularSec"] += max(0, day_sec - NOON_BREAK_SEC)

        if overtime_sec > 0:
            user["overtimeSec"] += overtime_sec
            user["overtimeDays"] += 1
            if cross_day:
                user["crossDays"] += 1
            cross_day_count += 1 if cross_day else 0
            overtime_detail.append(
                {
                    "date": work_date.isoformat(),
                    "userid": userid,
                    "name": name,
                    "lastestTime": seconds_to_hhmmss(latest),
                    "offWorkTime": seconds_to_hhmmss(off_work),
                    "crossDay": cross_day,
                    "sec": overtime_sec,
                    "hours": round(overtime_sec / 3600, 2),
                }
            )

        by_day.append(
            {
                "date": work_date.isoformat(),
                "userid": userid,
                "name": name,
                "earliestTime": seconds_to_hhmmss(earliest),
                "latestTime": seconds_to_hhmmss(latest),
                "offWorkTime": seconds_to_hhmmss(off_work),
                "regularSec": max(0, day_sec - NOON_BREAK_SEC) if day_sec > 0 else 0,
                "regularHours": round(max(0, day_sec - NOON_BREAK_SEC) / 3600, 2) if day_sec > 0 else 0.0,
                "overtimeSec": overtime_sec,
                "overtimeHours": round(overtime_sec / 3600, 2),
                "crossDay": cross_day,
            }
        )

    regular_detail: list[dict[str, Any]] = []
    by_user_list: list[dict[str, Any]] = []
    for user in sorted(by_user.values(), key=lambda item: item["userid"]):
        user["regularHours"] = round(user["regularSec"] / 3600, 2)
        user["overtimeHours"] = round(user["overtimeSec"] / 3600, 2)
        by_user_list.append(user)
        regular_detail.append(
            {
                "userid": user["userid"],
                "name": user["name"],
                "workDays": user["workDays"],
                "noonBreakHours": round(user["noonBreakSec"] / 3600, 2),
                "rawHours": round(user["rawSec"] / 3600, 2),
                "sec": user["regularSec"],
                "hours": user["regularHours"],
            }
        )

    total_regular = sum(user["regularSec"] for user in by_user.values())
    total_raw = sum(user["rawSec"] for user in by_user.values())
    total_break = sum(user["noonBreakSec"] for user in by_user.values())
    total_overtime = sum(user["overtimeSec"] for user in by_user.values())
    total_days = sum(user["workDays"] for user in by_user.values())
    expected = len(active_users) if expected_user_count is None else expected_user_count
    actual = len(by_user)

    warning: dict[str, Any] | None = None
    if expected == 0:
        warning = {"errcode": -4, "errmsg": "没有可统计的在职人员，请先同步企微通讯录"}
    elif actual == 0 or total_regular <= 0:
        warning = {"errcode": -2, "errmsg": "企微未返回有效打卡数据，可能是接口限频或尚未同步"}
    elif actual < ceil(expected * MIN_USER_RATIO):
        warning = {
            "errcode": -3,
            "errmsg": f"企微返回人数偏少({actual}/{expected})，可能不是完整数据",
        }

    missing_users = [
        {"userid": userid, "name": name}
        for userid, name in sorted(active_users.items())
        if userid not in by_user
    ]

    return {
        "regular": {
            "sec": total_regular,
            "hours": round(total_regular / 3600, 2),
            "rawSec": total_raw,
            "rawHours": round(total_raw / 3600, 2),
            "noonBreakSec": total_break,
            "noonBreakHours": round(total_break / 3600, 2),
            "workDays": total_days,
            "detail": regular_detail,
        },
        "overtime": {
            "sec": total_overtime,
            "hours": round(total_overtime / 3600, 2),
            "crossDayCount": cross_day_count,
            "detail": overtime_detail,
            "byUser": [
                {
                    "userid": user["userid"],
                    "name": user["name"],
                    "sec": user["overtimeSec"],
                    "hours": user["overtimeHours"],
                    "days": user["overtimeDays"],
                    "crossDays": user["crossDays"],
                }
                for user in by_user_list
                if user["overtimeDays"] > 0
            ],
        },
        "expectedUserCount": expected,
        "userCount": actual,
        "byUser": by_user_list,
        "byDay": by_day,
        "missingUsers": missing_users,
        "warning": warning,
    }

