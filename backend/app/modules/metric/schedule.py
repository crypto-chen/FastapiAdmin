"""指标计算调度。

**一个批次任务** + 每日刷新：每天 02:30（晚于数据源同步 02:00）按依赖分层重算一次
**当月**数值，每次计算保留一个 ``calc_version``，可按日期回溯当天的口径。

分层调度（见 ``batch.py``）保证组成指标先于派生指标完成；派生指标计算前还有一层
「组成指标当天算过」的新鲜度校验（见 ``engine._ensure_component_values``）兜底
单指标重算与开放接口触发。

另外在每月 1 日补一次**上月结转**：先把上月同步批次强制重拉（上月最后一天的
批次是当天 02:00 拉的，不含当天白天产生的单据），再重算上月指标。缺少这一步时，
月指标的月末最后一天数据会永久缺失。
"""

from __future__ import annotations

from datetime import date

from apscheduler.triggers.cron import CronTrigger

from app.core.ap_scheduler import scheduler
from app.core.logger import logger

from .batch import load_enabled_metrics, run_metric_batch
from .engine import previous_period_value

METRIC_CALC_JOB_PREFIX = "metric_calc:"
# 批次任务 job id：固定一个，覆盖全部启用指标（旧版为一指标一任务 ``metric_calc:{id}``）
METRIC_CALC_BATCH_JOB_ID = f"{METRIC_CALC_JOB_PREFIX}batch"
# 每天 02:30 重算（晚于科目余额表同步的 02:00）
METRIC_CALC_HOUR = 2
METRIC_CALC_MINUTE = 30


def _build_trigger() -> CronTrigger:
    return CronTrigger(
        second="0",
        minute=str(METRIC_CALC_MINUTE),
        hour=str(METRIC_CALC_HOUR),
        timezone="Asia/Shanghai",
    )


async def execute_metric_calc_job() -> None:
    """调度入口：按依赖分层重算全部启用指标的当前期间；每月 1 日先补算上月。"""
    try:
        metrics = await load_enabled_metrics()
        if not metrics:
            logger.warning("没有启用中的指标，跳过定时计算")
            return
        if date.today().day == 1:
            await _settle_previous_period(metrics)
        summary = await run_metric_batch(label="当期")
        logger.info(f"指标批次计算完成: {summary}")
    except Exception as e:
        logger.exception(f"指标批次计算失败: {e}")
        raise


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
    """注册/刷新批次计算任务（每天 02:30 一次）。"""
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
    )


async def reconcile_metric_calc_jobs() -> None:
    """启动时注册批次计算任务，并清掉旧版「一指标一任务」的残留调度。"""
    try:
        register_metric_calc_job()
        logger.info(
            f"指标批次计算任务已注册: {METRIC_CALC_BATCH_JOB_ID}"
            f"（每天 {METRIC_CALC_HOUR:02d}:{METRIC_CALC_MINUTE:02d}）"
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
