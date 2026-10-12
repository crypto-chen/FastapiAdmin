"""手动执行元数据同步任务（按期间回补历史数据）。

同步任务默认每天按 Cron 跑当期；历史月份需要手工触发一次，本脚本就是入口。
跑完可用 ``--show-latest`` 查看最近一次批次的落库结果。

用法：
    python scripts/run_meta_sync.py --job-id 77 --period 2026-09
    python scripts/run_meta_sync.py --name 生产订单-订单全链路 --period 2026-07,2026-08
    python scripts/run_meta_sync.py --job-id 77 --period 2026-06 --show-latest
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel  # noqa: E402
from app.modules.metadata.sync import execute_meta_sync_job  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def resolve_job(job_id: int | None, name: str | None) -> MetaSyncJobModel:
    async with async_db_session() as db:
        if job_id is not None:
            job = await db.get(MetaSyncJobModel, job_id)
        else:
            job = (
                await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.name == name))
            ).scalars().first()
    if job is None:
        raise SystemExit(f"同步任务不存在：job_id={job_id} name={name}")
    return job


async def show_latest(job_id: int, limit: int = 3) -> None:
    async with async_db_session() as db:
        runs = (
            await db.execute(
                select(MetaSyncRunModel)
                .where(MetaSyncRunModel.job_id == job_id)
                .order_by(MetaSyncRunModel.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    for run in runs:
        print(
            f"  批次 id={run.id} period={run.period_value} status={run.status} "
            f"rows={run.row_count}{(' error=' + str(run.error)) if run.error else ''}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="手动执行元数据同步任务")
    parser.add_argument("--job-id", type=int, default=None, help="同步任务ID（与 --name 二选一）")
    parser.add_argument("--name", default=None, help="同步任务名称（与 --job-id 二选一）")
    parser.add_argument("--period", default=None, help="期间，如 2026-09；多个用逗号分隔，缺省按当前时间")
    parser.add_argument("--show-latest", action="store_true", help="结束后打印最近批次结果")
    args = parser.parse_args()

    if args.job_id is None and not args.name:
        parser.error("必须提供 --job-id 或 --name")
    job = await resolve_job(args.job_id, args.name)
    print(f"同步任务 id={job.id} name={job.name} cron={job.cron_expr} status={job.status}")

    periods = [item.strip() for item in (args.period or "").split(",") if item.strip()] or [None]
    for period in periods:
        print(f"执行期间 {period or '（当前时间）'} ...")
        await execute_meta_sync_job(job.id, period_value=period)

    if args.show_latest:
        print("最近批次：")
        await show_latest(job.id, limit=max(len(periods), 3))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
