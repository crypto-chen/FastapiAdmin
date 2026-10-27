"""订单全链路构建调度。

每轮指标任务在同步完成后调用本模块，不再单独注册 02:10 任务。**每月 1 日的
00:00 轮次**先强制重拉上月各来源批次再构建上月，避免上月最后一天的变动丢失。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger
from app.core.schedule_plan import SCHEDULE_TZ, is_month_settlement_run
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel
from app.modules.metadata.sync import execute_meta_sync_job

from .build import (
    MO_OBJECT,
    ORDER_OBJECT_DOMESTIC,
    ORDER_OBJECT_EXPORT,
    ORDER_OBJECT_RETAIL,
    RETURN_OBJECT,
    SHIPMENT_OBJECT_DOMESTIC,
    SHIPMENT_OBJECT_EXPORT,
    build_period,
)

ORDER_BUILD_JOB_ID = "order_build:daily"

# 构建一单全链路要用的来源对象（回补/结转时按这些对象重拉）
SOURCE_OBJECT_CODES = [
    ORDER_OBJECT_DOMESTIC,
    ORDER_OBJECT_EXPORT,
    ORDER_OBJECT_RETAIL,
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


def recent_periods(count: int) -> list[str]:
    """最近 ``count`` 个期间（升序，含当期）。"""
    now = datetime.now()
    periods: list[str] = []
    year, month = now.year, now.month
    for _ in range(max(count, 1)):
        periods.append(f"{year}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(periods))


# 每天顺带回补的最近期数（含当期）：CRM 会**事后**更新订单的出库标记、下发时间等，
# 跨月发货的订单要重拉它接单月的批次才能拿到最新状态。
DAILY_LOOKBACK_PERIODS = 3

# 事后会被上游更新的来源（每天回补这几类即可；金蝶生产订单/客户列表变化少，不必每天重拉）
REFRESH_OBJECT_CODES = [
    ORDER_OBJECT_DOMESTIC,
    ORDER_OBJECT_EXPORT,
    ORDER_OBJECT_RETAIL,
    SHIPMENT_OBJECT_DOMESTIC,
    SHIPMENT_OBJECT_EXPORT,
    RETURN_OBJECT,
]


async def refresh_period_sources(
    period_value: str, object_codes: list[str] | None = None
) -> list[str]:
    """强制重拉该期间各来源批次，返回执行的任务名。

    ``object_codes`` 为空时重拉全部来源（首次回补用）；调度的每日回补只传
    ``REFRESH_OBJECT_CODES``，避免每天重复拉金蝶生产订单这类大批次。
    """
    executed: list[str] = []
    codes = object_codes or SOURCE_OBJECT_CODES
    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(MetaSyncJobModel.id, MetaSyncJobModel.name)
                .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
                .where(
                    SourceObjectModel.code.in_(codes),
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
    """调度入口：回补最近 ``DAILY_LOOKBACK_PERIODS`` 期（含当期）；每月 1 日先全量结转上月。

    为什么要往前回补：订单的「出库标记 / 出库日期 / 下推日期」是 CRM 事后更新的，
    9 月接单、10 月发货的订单，只重拉 10 月批次不会更新 9 月那条记录，
    必须把 9 月的订单批次也重拉一次再重建。
    """
    try:
        if datetime.now(SCHEDULE_TZ).day == 1 and is_month_settlement_run():
            period = previous_period()
            await refresh_period_sources(period)
            result = await build_one_period(period)
            logger.info(f"订单全链路上月结转 {period} 完成：{result}")
        for period in recent_periods(DAILY_LOOKBACK_PERIODS):
            is_current = period == current_period()
            # 当期批次本来就会同步，历史期需要显式重拉
            if not is_current:
                await refresh_period_sources(period, REFRESH_OBJECT_CODES)
            result = await build_one_period(period)
            logger.info(f"订单全链路构建 {period} 完成：{result}")
    except Exception as exc:  # noqa: BLE001 - 调度任务失败只记日志
        logger.exception(f"订单全链路构建失败：{exc}")
        raise


def register_order_build_job() -> None:
    """移除旧的独立 02:10 任务；构建由每轮指标任务串行调用。"""
    try:
        scheduler.remove_job(ORDER_BUILD_JOB_ID)
    except Exception:
        pass


async def reconcile_order_build_jobs() -> None:
    """启动时移除独立的订单构建任务（已并入指标轮次）。"""
    try:
        register_order_build_job()
        logger.info(f"订单全链路独立任务已移除: {ORDER_BUILD_JOB_ID}（改由指标轮次调用）")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"移除订单全链路独立任务失败: {exc}")
