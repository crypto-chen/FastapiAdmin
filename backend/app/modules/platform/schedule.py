"""平台指标每日快照：与指标轮次同频（每天 00/07/12/18 点）计算当月并落快照。"""

from __future__ import annotations

from datetime import datetime

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger
from app.core.schedule_plan import SYNC_SCHEDULE_TIMES, build_daily_trigger

from .service import PlatformAnalysisService

PLATFORM_METRIC_JOB_ID = "platform_metric_snapshot:daily"


async def execute_platform_metric_snapshot(period_value: str | None = None) -> None:
    """计算指定期间（默认当月）的平台指标快照。"""
    period = period_value or datetime.now().strftime("%Y-%m")
    async with async_db_session() as db, db.begin():
        result = await PlatformAnalysisService(db).build_snapshot(period)
    if result.get("status") == "success":
        logger.info(
            f"平台指标快照完成 {period}：版本 v{result['calc_version']}，"
            f"店铺 {result['shop_count']} 个，写入 {result['rows']} 行"
        )
    else:
        logger.info(f"平台指标快照跳过 {period}：{result.get('reason')}")


def register_platform_metric_jobs() -> None:
    try:
        scheduler.remove_job(PLATFORM_METRIC_JOB_ID)
    except Exception:  # noqa: BLE001 - 任务不存在时忽略
        pass
    scheduler.add_job(
        func=execute_platform_metric_snapshot,
        trigger=build_daily_trigger(SYNC_SCHEDULE_TIMES),
        id=PLATFORM_METRIC_JOB_ID,
        name="平台指标每日快照（当月）",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("平台指标快照任务已注册: platform_metric_snapshot:daily（每天 00:00, 07:00, 12:00, 18:00）")
