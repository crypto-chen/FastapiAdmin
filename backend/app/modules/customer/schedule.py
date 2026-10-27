"""客户分析构建调度。

每轮指标任务在订单宽表重建后调用本模块，不再单独注册 02:20 任务。**每月 1 日的
00:00 轮次**先构建上月，保证上月数据在月度结转时被固化。

说明：客户分析直接读 ``dwd_order_full_chain``，所以只需要重跑订单全链路即可拿到最新订单数据，
本任务不再单独回补 CRM 来源批次。
"""

from __future__ import annotations

from datetime import datetime

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger
from app.core.schedule_plan import SCHEDULE_TZ, is_month_settlement_run

from .build import build_period

CUSTOMER_BUILD_JOB_ID = "customer_build:daily"
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
        if datetime.now(SCHEDULE_TZ).day == 1 and is_month_settlement_run():
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
    """移除旧的独立 02:20 任务；构建由每轮指标任务串行调用。"""
    try:
        scheduler.remove_job(CUSTOMER_BUILD_JOB_ID)
    except Exception:
        pass


async def reconcile_customer_build_jobs() -> None:
    """启动时移除独立的客户分析任务（已并入指标轮次）。"""
    try:
        register_customer_build_job()
        logger.info(f"客户分析独立任务已移除: {CUSTOMER_BUILD_JOB_ID}（改由指标轮次调用）")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"移除客户分析独立任务失败: {exc}")
