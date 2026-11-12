"""企业微信通讯录 / 打卡定时同步任务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.core.ap_scheduler import scheduler
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.schedule_plan import SYNC_SCHEDULE_TIMES, build_daily_trigger

from .service import sync_checkin, sync_roster

CN_TZ = ZoneInfo("Asia/Shanghai")

WECOM_ROSTER_SYNC_JOB_ID = "wecom_sync:roster:daily"
WECOM_CHECKIN_SYNC_JOB_ID = "wecom_sync:checkin:daily"


async def execute_wecom_roster_sync_job() -> None:
    """每日同步企微通讯录。"""
    try:
        async with async_db_session() as db, db.begin():
            result = await sync_roster(db)
        logger.info(
            "企微通讯录同步完成："
            f"部门 {result['departments']}，人员 {result['users']}，"
            f"组织 +{result['orgs_created']}/~{result['orgs_updated']}，"
            f"人员 +{result['persons_created']}/~{result['persons_updated']}"
        )
    except CustomException as exc:
        logger.warning(f"企微通讯录同步跳过：{exc}")
    except Exception as exc:  # noqa: BLE001 - 定时任务不能把调度器打挂
        logger.error(f"企微通讯录同步失败：{exc}")


async def execute_wecom_checkin_sync_job(days_back: int = 3) -> None:
    """每日回补最近 N 天打卡（默认 D-3~D-1）。"""
    end_date = datetime.now(CN_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(1, int(days_back)) - 1)
    try:
        async with async_db_session() as db, db.begin():
            result = await sync_checkin(db, start_date, end_date)
        logger.info(
            f"企微打卡同步完成 {start_date}~{end_date}："
            f"人员 {result['actual_users']}/{result['expected_users']}，"
            f"新增 {result['created']}，更新 {result['updated']}，"
            f"失败批次 {len(result['errors'])}"
        )
    except CustomException as exc:
        logger.warning(f"企微打卡同步跳过：{exc}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"企微打卡同步失败：{exc}")


def register_wecom_sync_jobs() -> None:
    """注册/刷新通讯录与打卡同步任务。"""
    for job_id in (WECOM_ROSTER_SYNC_JOB_ID, WECOM_CHECKIN_SYNC_JOB_ID):
        try:
            scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001
            pass

    scheduler.add_job(
        func=execute_wecom_roster_sync_job,
        trigger=CronTrigger(hour=1, minute=30, timezone="Asia/Shanghai"),
        id=WECOM_ROSTER_SYNC_JOB_ID,
        name="企微通讯录同步（每日 01:30）",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        func=execute_wecom_checkin_sync_job,
        trigger=build_daily_trigger(SYNC_SCHEDULE_TIMES),
        args=[3],
        id=WECOM_CHECKIN_SYNC_JOB_ID,
        name="企微打卡同步（D-3~D-1，每日 0/7/12/18 点）",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )


async def reconcile_wecom_sync_jobs() -> None:
    """应用启动时注册任务；失败只告警，不影响主服务启动。"""
    try:
        register_wecom_sync_jobs()
        logger.info(
            "企微同步任务已注册："
            f"{WECOM_ROSTER_SYNC_JOB_ID}、{WECOM_CHECKIN_SYNC_JOB_ID}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"企微同步任务注册失败：{exc}")

