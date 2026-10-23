"""创建「零售数据-外部推送」同步任务（用于承接推送数据并回放指标批次）。

该任务不主动访问上游：``connector_type=push``，Cron 使用永不触发的表达式，
但保持 ``status=0``，这样指标引擎在找该来源对象的任务时仍能读到它。

用法::

    python scripts/seed_retail_push_job.py
    python scripts/seed_retail_push_job.py --cron "0 0 0 31 2 ?"
"""

from __future__ import annotations

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
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel, SourceSystemModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SYSTEM_CODE = "retail_push"
OBJECT_CODE = "/retail/orders/sync"
JOB_NAME = "零售数据-外部推送"
# 带 12:20/18:20 是为了绕过 normalize_sync_cron 的“每日三次”改写；
# 年份固定 2000，确保触发器永远不会再次执行（任务只承接推送回放）。
NEVER_CRON = "0 0 2 * * ? 2000;0 20 12 * * ? 2000;0 20 18 * * ? 2000"


async def main() -> None:
    parser = argparse.ArgumentParser(description="创建零售数据外部推送同步任务")
    parser.add_argument("--cron", default=NEVER_CRON, help="Cron 表达式，默认永不触发")
    parser.add_argument("--name", default=JOB_NAME, help="任务名称")
    args = parser.parse_args()

    async with async_db_session() as db, db.begin():
        system = (
            await db.execute(select(SourceSystemModel).where(SourceSystemModel.code == SYSTEM_CODE))
        ).scalars().first()
        if system is None:
            system = SourceSystemModel(
                code=SYSTEM_CODE,
                name="零售数据推送",
                connector_type="push",
                connection_id=None,
                status=0,
                description="外部系统主动推送零售订单（不主动拉取）",
            )
            db.add(system)
            await db.flush()
        else:
            system.connector_type = "push"
            system.status = 0

        source_object = (
            await db.execute(
                select(SourceObjectModel).where(
                    SourceObjectModel.system_id == system.id,
                    SourceObjectModel.code == OBJECT_CODE,
                )
            )
        ).scalars().first()
        if source_object is None:
            source_object = SourceObjectModel(
                system_id=system.id,
                code=OBJECT_CODE,
                name="零售订单推送",
                query_type="api",
                request_template={},
                status=0,
            )
            db.add(source_object)
            await db.flush()
        else:
            source_object.status = 0

        job = (
            await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.name == args.name))
        ).scalars().first()
        if job is None:
            job = MetaSyncJobModel(
                name=args.name,
                source_system_id=system.id,
                source_object_id=source_object.id,
                cron_expr=args.cron,
            )
            db.add(job)
        job.source_system_id = system.id
        job.source_object_id = source_object.id
        job.cron_expr = args.cron
        job.request_params = {}
        job.sync_mode = "full"
        job.status = 0
        job.description = "不主动取数；由 /open/v1/retail/orders/sync 推送后回放 meta_sync_run"
        await db.flush()
        print(f"来源系统 id={system.id}，来源对象 id={source_object.id}，同步任务 id={job.id}")
        print("把该 id 配置到开放应用的 retail_sync_job_id，即可让零售指标使用推送数据。")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
