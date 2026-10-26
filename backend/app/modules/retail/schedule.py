"""聚水潭非淘系零售订单定时拉取。

- 每 10 分钟拉取最近 30 分钟（按修改时间），覆盖新增/变更订单；
- 每天 02:10 拉取最近 7 天，补齐延迟状态变化与漏单；
- 写入 `retail_order` / `retail_order_item`，页面「开放接口 → 零售订单同步」可见。

聚水潭订单查询接口不返回淘系/拼多多订单；淘系走奇门，拼多多走方舟。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config.setting import settings
from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.logger import logger
from app.modules.erp.jushuitan.model import JushuitanConnectionModel
from app.modules.erp.jushuitan.service import build_client

from .service import RetailSyncService

RETAIL_ORDER_SYNC_JOB_ID = "retail_order_sync:jushuitan:10m"
RETAIL_ORDER_SYNC_DAILY_JOB_ID = "retail_order_sync:jushuitan:daily"
CN_TZ = ZoneInfo("Asia/Shanghai")


async def _load_connection() -> JushuitanConnectionModel | None:
    async with async_db_session() as db:
        if settings.RETAIL_ORDER_SYNC_CONNECTION_ID:
            connection = await db.get(
                JushuitanConnectionModel, int(settings.RETAIL_ORDER_SYNC_CONNECTION_ID)
            )
        else:
            connection = (
                await db.execute(
                    select(JushuitanConnectionModel)
                    .where(JushuitanConnectionModel.status == 0)
                    .order_by(JushuitanConnectionModel.id.asc())
                    .limit(1)
                )
            ).scalars().first()
        if connection is None or connection.status == 1:
            return None
        return connection


async def execute_retail_order_sync_job(
    lookback_minutes: int | None = None,
    max_rows: int | None = None,
) -> None:
    """拉取最近一段时间的聚水潭订单并写入零售表。"""
    minutes = int(lookback_minutes or settings.RETAIL_ORDER_SYNC_LOOKBACK_MINUTES)
    limit = int(max_rows or settings.RETAIL_ORDER_SYNC_MAX_ROWS)
    end = datetime.now().replace(microsecond=0)
    begin = end - timedelta(minutes=max(minutes, 1))

    connection = await _load_connection()
    if connection is None:
        logger.warning("聚水潭订单定时同步跳过：没有启用的聚水潭连接")
        return

    rows: list[dict] = []
    async with build_client(connection) as client:
        async for row in client.iter_orders(
            begin,
            end,
            page_size=100,
            date_type=0,
        ):
            rows.append(row)
            if len(rows) >= limit:
                logger.warning(f"聚水潭订单定时同步达到上限 {limit}，本轮提前结束")
                break

    if not rows:
        logger.debug(f"聚水潭订单定时同步：{begin:%H:%M}~{end:%H:%M} 没有订单变化")
        return

    request_id = f"jst-auto-{end:%Y%m%d%H%M%S}"
    async with async_db_session() as db, db.begin():
        result = await RetailSyncService(db, app_id="jushuitan_schedule").pull_orders(
            rows,
            source="jushuitan",
            request_id=request_id,
            publish_metric=False,
        )
    logger.info(
        f"聚水潭订单定时同步完成 {begin:%H:%M}~{end:%H:%M}："
        f"收到 {result.received}，新增 {result.created}，更新 {result.updated}，"
        f"未变 {result.unchanged}，失败 {result.failed}"
    )


def register_retail_order_sync_job() -> None:
    """注册/刷新 10 分钟增量与每日 7 天补偿任务。"""
    interval = max(int(settings.RETAIL_ORDER_SYNC_INTERVAL_MINUTES), 1)
    for job_id in (RETAIL_ORDER_SYNC_JOB_ID, RETAIL_ORDER_SYNC_DAILY_JOB_ID):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    scheduler.add_job(
        func=execute_retail_order_sync_job,
        trigger=IntervalTrigger(minutes=interval, timezone="Asia/Shanghai"),
        id=RETAIL_ORDER_SYNC_JOB_ID,
        name=f"聚水潭零售订单同步（每 {interval} 分钟）",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
        next_run_time=datetime.now(CN_TZ) + timedelta(seconds=15),
    )
    scheduler.add_job(
        func=execute_retail_order_sync_job,
        trigger=CronTrigger(hour=2, minute=10, timezone="Asia/Shanghai"),
        args=[7 * 24 * 60, settings.RETAIL_ORDER_SYNC_MAX_ROWS],
        id=RETAIL_ORDER_SYNC_DAILY_JOB_ID,
        name="聚水潭零售订单 7 天补偿",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )


async def reconcile_retail_order_sync_jobs() -> None:
    try:
        register_retail_order_sync_job()
        logger.info(
            f"聚水潭零售订单同步任务已注册: {RETAIL_ORDER_SYNC_JOB_ID}"
            f"（每 {settings.RETAIL_ORDER_SYNC_INTERVAL_MINUTES} 分钟）"
            f"，每日 02:10 补偿最近 7 天"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"注册聚水潭零售订单同步任务失败: {exc}")
