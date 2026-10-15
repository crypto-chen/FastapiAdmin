"""客户分析构建调度。

每天 **02:20** 构建当期（晚于订单全链路 02:10，早于指标计算 02:30）；
**每月 1 日**先构建上月，保证上月数据在月度结转时被固化。

说明：客户分析直接读 ``dwd_order_full_chain``，所以只需要重跑订单全链路即可拿到最新订单数据，
本任务不再单独回补 CRM 来源批次。
"""

from __future__ import annotations

from datetime import date, datetime

from apscheduler.triggers.cron import CronTrigger

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger

from .build import build_period

CUSTOMER_BUILD_JOB_ID = "customer_build:daily"
CUSTOMER_BUILD_HOUR = 2
CUSTOMER_BUILD_MINUTE = 20
DAILY_LOOKBACK_PERIODS = 3


def _shift_period(months: int = 1) -> str:
    now = datetime.now()
    year, month = (now.year - 1, 12) if now.month == months else (now.year, now.month - months)
    return f"{year}-{month:02d}"


def recent_periods(count: int) -> list[str]:
    now = datetime.now()
    periods: list[str] = []
    year, month = now.year, now.month
    for _ in range(max(count, 1)):
        periods.append(f"{year}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(periods))


async def build_one_period(period_value: str) -> dict:
    async with async_db_session() as db, db.begin():
        return await build_period(db, period_value)


async def execute_customer_build_job() -> None:
    """调度入口：每月 1 日先结转上月，再回补最近 3 期（含当期）。"""
    try:
        if date.today().day == 1:
            period = _shift_period(1)
            result = await build_one_period(period)
            logger.info(f"客户分析上月结转 {period} 完成：{result}")
        for period in recent_periods(DAILY_LOOKBACK_PERIODS):
            result = await build_one_period(period)
            logger.info(f"客户分析构建 {period} 完成：{result}")
    except Exception as exc:  # noqa: BLE001 - 调度任务失败只记日志
        logger.exception(f"客户分析构建失败：{exc}")
        raise


def register_customer_build_job() -> None:
    try:
        scheduler.remove_job(CUSTOMER_BUILD_JOB_ID)
    except Exception:
        pass
    scheduler.add_job(
        func=execute_customer_build_job,
        trigger=CronTrigger(
            second="0",
            minute=str(CUSTOMER_BUILD_MINUTE),
            hour=str(CUSTOMER_BUILD_HOUR),
            timezone="Asia/Shanghai",
        ),
        id=CUSTOMER_BUILD_JOB_ID,
        name="客户分析构建",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


async def reconcile_customer_build_jobs() -> None:
    """启动时注册客户分析构建任务。"""
    try:
        register_customer_build_job()
        logger.info(
            f"客户分析构建任务已注册: {CUSTOMER_BUILD_JOB_ID}"
            f"（每天 {CUSTOMER_BUILD_HOUR:02d}:{CUSTOMER_BUILD_MINUTE:02d}）"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"注册客户分析构建任务失败: {exc}")
