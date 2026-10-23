"""指标计算调度。

**一个批次任务** + 每日三次刷新：凌晨 02:30、中午 12:20、晚上 18:20 按依赖分层
重算一次**当月**数值，每次计算保留一个 ``calc_version``，可按日期回溯当天的口径。

分层调度（见 ``batch.py``）保证组成指标先于派生指标完成；派生指标计算前还有一层
「组成指标当天算过」的新鲜度校验（见 ``engine._ensure_component_values``）兜底
单指标重算与开放接口触发。

另外在每月 1 日的凌晨轮次补一次**上月结转**：先把上月同步批次强制重拉（上月最后
一天的批次是当天 02:00 拉的，不含当天白天产生的单据），再重算上月指标。缺少这一步
时，月指标的月末最后一天数据会永久缺失。
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.base import BaseTrigger

from app.core.ap_scheduler import scheduler
from app.core.logger import logger
from app.core.schedule_plan import (
    METRIC_CALC_TIMES,
    SCHEDULE_TZ,
    build_daily_trigger,
    is_daytime_run,
    latest_daytime_slot,
)

from .batch import load_enabled_metrics, run_metric_batch
from .engine import previous_period_value

METRIC_CALC_JOB_PREFIX = "metric_calc:"
# 批次任务 job id：固定一个，覆盖全部启用指标（旧版为一指标一任务 ``metric_calc:{id}``）
METRIC_CALC_BATCH_JOB_ID = f"{METRIC_CALC_JOB_PREFIX}batch"
# 每天 02:30、12:20、18:20 重算（凌晨轮次晚于科目余额表同步的 02:00）
METRIC_CALC_SCHEDULE = ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in METRIC_CALC_TIMES)


def _build_trigger() -> BaseTrigger:
    return build_daily_trigger(METRIC_CALC_TIMES)


async def execute_metric_calc_job() -> None:
    """调度入口：按依赖分层重算全部启用指标的当前期间；每月 1 日先补算上月。"""
    try:
        daytime = is_daytime_run()
        if daytime:
            await _refresh_daytime_upstream()
        metrics = await load_enabled_metrics()
        if not metrics:
            logger.warning("没有启用中的指标，跳过定时计算")
            return
        if datetime.now(SCHEDULE_TZ).day == 1 and not daytime:
            await _settle_previous_period(metrics)
        summary = await run_metric_batch(label="当期")
        logger.info(f"指标批次计算完成: {summary}")
    except Exception as e:
        logger.exception(f"指标批次计算失败: {e}")
        raise


async def _refresh_daytime_upstream() -> None:
    """日间轮次：先等同步完成，再重建订单/客户宽表，最后计算指标。

    凌晨轮次由各自的 02:00/02:10/02:20 任务完成，这里不重复执行。
    """
    from app.modules.metadata.sync import wait_for_sync_jobs

    slot = latest_daytime_slot()
    if slot is None:
        return
    await wait_for_sync_jobs(slot)

    from app.modules.order.schedule import execute_order_build_job

    try:
        await execute_order_build_job()
    except Exception as exc:  # noqa: BLE001 - 上游宽表失败时仍用现有版本算指标
        logger.exception(f"日间订单全链路构建失败，指标将使用现有宽表：{exc}")

    from app.modules.customer.schedule import execute_customer_build_job

    try:
        await execute_customer_build_job()
    except Exception as exc:  # noqa: BLE001 - 上游宽表失败时仍用现有版本算指标
        logger.exception(f"日间客户分析构建失败，指标将使用现有宽表：{exc}")


async def _settle_previous_period(metrics: list[dict]) -> None:
    """次月 1 日结转：按期间类型分组，强制重拉上期批次后按依赖分层重算上期。"""
    groups: dict[str, list[str]] = {}
    for item in metrics:
        period_value = previous_period_value(item.get("period_type") or "month")
        groups.setdefault(period_value, []).append(item["code"])
    for period_value, codes in sorted(groups.items()):
        try:
            summary = await run_metric_batch(
                period_value=period_value,
                codes=codes,
                refresh=True,
                label=f"上期结转 {period_value}",
            )
            logger.info(
                f"上期结转 {period_value} 完成: 指标 {summary['success']}/{summary['metric_count']}，"
                f"失败 {len(summary['failed'])}"
            )
        except Exception as e:
            # 上期结转失败不能拖垮当期计算
            logger.exception(f"上期结转 {period_value} 失败: {e}")


def register_metric_calc_job() -> None:
    """注册/刷新批次计算任务（每天 02:30、12:20、18:20）。"""
    try:
        scheduler.remove_job(METRIC_CALC_BATCH_JOB_ID)
    except Exception:
        pass
    scheduler.add_job(
        func=execute_metric_calc_job,
        trigger=_build_trigger(),
        id=METRIC_CALC_BATCH_JOB_ID,
        name="指标批次计算",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        # 服务在 02:30 前未启动或当天重启时，APScheduler 默认 1 秒的 misfire
        # 容忍度会把当天的批次直接跳过，指标就会一直停在前一天。这里不设容忍
        # 上限：启动后补跑一次（coalesce 保证只跑一次，max_instances 防叠加）。
        misfire_grace_time=None,
    )


async def reconcile_metric_calc_jobs() -> None:
    """启动时注册批次计算任务，并清掉旧版「一指标一任务」的残留调度。"""
    try:
        register_metric_calc_job()
        logger.info(
            f"指标批次计算任务已注册: {METRIC_CALC_BATCH_JOB_ID}"
            f"（每天 {METRIC_CALC_SCHEDULE}）"
        )
    except Exception as e:
        logger.error(f"恢复指标批次计算任务失败: {e}")
    try:
        for job in scheduler.get_jobs():
            job_id = str(job.id)
            if job_id.startswith(METRIC_CALC_JOB_PREFIX) and job_id != METRIC_CALC_BATCH_JOB_ID:
                scheduler.remove_job(job_id)
                logger.info(f"已移除旧版单指标计算任务 {job_id}（改为批次分层调度）")
    except Exception as e:
        logger.warning(f"清理旧版单指标计算任务失败（不影响批次任务）: {e}")
