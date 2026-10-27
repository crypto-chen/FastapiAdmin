"""把同步任务排期统一为每日三次，并校验指标批次时间。

默认只预演，不写数据库；服务器上确认后加 ``--apply``。

用法（在 backend/ 目录、已激活的 conda 环境内）:
    python scripts/apply_three_times_schedule.py
    python scripts/apply_three_times_schedule.py --apply
    python scripts/apply_three_times_schedule.py --apply --restart-service fastapiadmin
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import false, select  # noqa: E402

from app.config.setting import settings  # noqa: E402
from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.schedule_plan import (  # noqa: E402
    METRIC_CALC_TIMES,
    SCHEDULE_TZ,
    build_daily_trigger,
    normalize_sync_cron,
)
from app.modules.metadata.model import MetaSyncJobModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SYNC_JOB_IDS = ("metric_calc:batch", "order_build:daily", "customer_build:daily")


def _format_metric_times() -> str:
    return ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in METRIC_CALC_TIMES)


def _assert_metric_schedule() -> None:
    expected = ((2, 30), (12, 20), (18, 20))
    if tuple(METRIC_CALC_TIMES) != expected:
        raise RuntimeError(
            f"指标批次时间不是预期的 02:30/12:20/18:20，当前为 {_format_metric_times()}"
        )


async def _load_jobs() -> list[MetaSyncJobModel]:
    async with async_db_session() as db:
        return list(
            (
                await db.execute(
                    select(MetaSyncJobModel).where(
                        MetaSyncJobModel.is_deleted == false(),
                        MetaSyncJobModel.status == 0,
                    )
                )
            )
            .scalars()
            .all()
        )


async def _apply_sync_schedule(apply: bool) -> list[tuple[int, str, str]]:
    jobs = await _load_jobs()
    changes: list[tuple[int, str, str]] = []
    for job in jobs:
        normalized = normalize_sync_cron(job.cron_expr)
        if normalized and normalized != job.cron_expr:
            changes.append((int(job.id), job.cron_expr, normalized))

    print(f"启用中的同步任务: {len(jobs)} 个；需要调整: {len(changes)} 个")
    for job_id, old_cron, new_cron in changes:
        print(f"  job {job_id}: {old_cron or '<empty>'} -> {new_cron}")

    if apply and changes:
        async with async_db_session() as db, db.begin():
            for job_id, _old_cron, new_cron in changes:
                job = await db.get(MetaSyncJobModel, job_id)
                if job is not None:
                    job.cron_expr = new_cron
        print(f"已写入数据库: {len(changes)} 个同步任务")
    elif not apply:
        print("预演模式：未写数据库。确认后加 --apply。")
    return changes


async def _verify_db_schedule() -> bool:
    jobs = await _load_jobs()
    bad: list[tuple[int, str]] = []
    for job in jobs:
        if not job.cron_expr:
            continue
        normalized = normalize_sync_cron(job.cron_expr)
        if normalized != job.cron_expr:
            bad.append((int(job.id), job.cron_expr))
    if bad:
        print(f"数据库校验失败：{len(bad)} 个任务仍未统一为每日三次")
        for job_id, cron_expr in bad:
            print(f"  job {job_id}: {cron_expr}")
        return False
    print("数据库校验通过：所有启用且已配置 Cron 的同步任务均为每日三次")
    return True


async def _verify_redis_next_runs() -> None:
    redis = Redis(
        host=settings.REDIS_HOST,
        port=int(settings.REDIS_PORT),
        db=int(settings.REDIS_DB_NAME),
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )
    try:
        items = await redis.zrange("apscheduler.run_times", 0, -1, withscores=True)
    finally:
        await redis.aclose()
    buckets: Counter[str] = Counter()
    for job_id, score in items:
        key = str(job_id)
        if key.startswith("meta_sync:") or key in SYNC_JOB_IDS:
            local = datetime.fromtimestamp(float(score), UTC).astimezone(SCHEDULE_TZ)
            buckets[local.strftime("%Y-%m-%d %H:%M")] += 1
    if not buckets:
        print("Redis 中未找到排期（后端可能未运行）；重启后端后再校验。")
        return
    print("Redis 下一轮排期:")
    for slot, count in sorted(buckets.items()):
        print(f"  {slot}  {count} 个任务")


def _verify_metric_trigger() -> None:
    _assert_metric_schedule()
    trigger = build_daily_trigger(METRIC_CALC_TIMES)
    cursor = datetime.now(SCHEDULE_TZ)
    previous = None
    fires: list[str] = []
    for _ in range(3):
        fire_time = trigger.get_next_fire_time(previous, cursor)
        if fire_time is None:
            break
        fires.append(fire_time.strftime("%H:%M"))
        previous = fire_time
        cursor = fire_time
    print(f"指标批次时间: {_format_metric_times()}；未来三次: {', '.join(fires)}")


def _restart_service(service: str) -> None:
    if not service:
        print("未指定 --restart-service：请按现有方式重启后端进程以加载新排期。")
        return
    if sys.platform.startswith("win"):
        command = ["powershell", "-NoProfile", "-Command", f"Restart-Service -Name '{service}' -Force"]
    else:
        command = ["systemctl", "restart", service]
    print(f"重启服务: {' '.join(command)}")
    subprocess.run(command, check=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="统一同步任务为每日三次，并校验指标批次时间")
    parser.add_argument("--apply", action="store_true", help="写入数据库；缺省只预演")
    parser.add_argument("--restart-service", default="", help="写入后重启的服务名（Windows 服务/systemd）")
    args = parser.parse_args()

    _verify_metric_trigger()
    changes = await _apply_sync_schedule(apply=args.apply)
    if args.apply:
        await _verify_db_schedule()
        await _verify_redis_next_runs()
        if changes:
            _restart_service(args.restart_service)
        elif args.restart_service:
            _restart_service(args.restart_service)
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
