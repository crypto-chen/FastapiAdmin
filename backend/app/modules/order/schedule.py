"""订单全链路构建调度。

每天 **02:10** 构建当期（晚于源同步 02:00，早于指标计算 02:30）；
**每月 1 日**先强制重拉上月各来源批次再构建上月，避免上月最后一天的变动丢失。
"""

from __future__ import annotations

from datetime import date, datetime

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel
from app.modules.metadata.sync import execute_meta_sync_job

from .build import (
    MO_OBJECT,
    ORDER_OBJECT_DOMESTIC,
    ORDER_OBJECT_EXPORT,
    RETURN_OBJECT,
    SHIPMENT_OBJECT_DOMESTIC,
    SHIPMENT_OBJECT_EXPORT,
    build_period,
)

ORDER_BUILD_JOB_ID = "order_build:daily"
ORDER_BUILD_HOUR = 2
ORDER_BUILD_MINUTE = 10

# 构建一单全链路要用的来源对象（回补/结转时按这些对象重拉）
SOURCE_OBJECT_CODES = [
    ORDER_OBJECT_DOMESTIC,
    ORDER_OBJECT_EXPORT,
    SHIPMENT_OBJECT_DOMESTIC,
    SHIPMENT_OBJECT_EXPORT,
    RETURN_OBJECT,
    MO_OBJECT,
]


def current_period() -> str:
    return datetime.now().strftime("%Y-%m")


def previous_period() -> str:
    now = datetime.now()
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{year}-{month:02d}"


async def refresh_period_sources(period_value: str) -> list[str]:
    """强制重拉该期间各来源批次，返回执行的任务名。"""
    executed: list[str] = []
    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(MetaSyncJobModel.id, MetaSyncJobModel.name)
                .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
                .where(
                    SourceObjectModel.code.in_(SOURCE_OBJECT_CODES),
                    MetaSyncJobModel.status == 0,
                )
            )
        ).all()
    for job_id, name in rows:
        try:
            await execute_meta_sync_job(int(job_id), period_value=period_value)
            executed.append(str(name))
        except Exception as exc:  # noqa: BLE001 - 单个来源失败不阻断其它来源
            logger.warning(f"订单全链路：来源任务 {name} 重拉 {period_value} 失败：{exc}")
    return executed


async def build_one_period(period_value: str) -> dict:
    async with async_db_session() as db, db.begin():
        return await build_period(db, period_value)


async def execute_order_build_job() -> None:
    """调度入口：构建当期；每月 1 日先结转上月。"""
    try:
        if date.today().day == 1:
            period = previous_period()
            await refresh_period_sources(period)
            result = await build_one_period(period)
            logger.info(f"订单全链路上月结转 {period} 完成：{result}")
        period = current_period()
        result = await build_one_period(period)
        logger.info(f"订单全链路当期构建 {period} 完成：{result}")
    except Exception as exc:  # noqa: BLE001 - 调度任务失败只记日志
        logger.exception(f"订单全链路构建失败：{exc}")
        raise


def register_order_build_job() -> None:
    try:
        scheduler.remove_job(ORDER_BUILD_JOB_ID)
    except Exception:
        pass
    scheduler.add_job(
        func=execute_order_build_job,
        trigger=CronTrigger(
            second="0",
            minute=str(ORDER_BUILD_MINUTE),
            hour=str(ORDER_BUILD_HOUR),
            timezone="Asia/Shanghai",
        ),
        id=ORDER_BUILD_JOB_ID,
        name="订单全链路构建",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


async def reconcile_order_build_jobs() -> None:
    """启动时注册订单全链路构建任务。"""
    try:
        register_order_build_job()
        logger.info(
            f"订单全链路构建任务已注册: {ORDER_BUILD_JOB_ID}"
            f"（每天 {ORDER_BUILD_HOUR:02d}:{ORDER_BUILD_MINUTE:02d}）"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"注册订单全链路构建任务失败: {exc}")
