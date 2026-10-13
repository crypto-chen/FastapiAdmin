"""手动构建订单全链路宽表（按期间，可多期间）。

用法：
    python scripts/run_order_build.py --period 2026-09
    python scripts/run_order_build.py --period 2026-07,2026-08,2026-09
    python scripts/run_order_build.py --period 2026-09 --keep-versions 5
    python scripts/run_order_build.py --period 2025-01 --refresh      # 先重拉该期间各来源批次再构建
    python scripts/run_order_build.py --all --refresh                 # 有订单批次的全部期间
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.order.build import build_period  # noqa: E402
from app.modules.order.schedule import refresh_period_sources  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def available_periods() -> list[str]:
    """有 CRM 订单批次的全部期间（升序）。"""
    from sqlalchemy import select

    from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel
    from app.modules.order.build import ORDER_OBJECT_DOMESTIC

    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(MetaSyncRunModel.period_value)
                .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
                .join(SourceObjectModel, SourceObjectModel.id == MetaSyncJobModel.source_object_id)
                .where(
                    SourceObjectModel.code == ORDER_OBJECT_DOMESTIC,
                    MetaSyncRunModel.status == "success",
                    MetaSyncRunModel.period_value.is_not(None),
                )
                .distinct()
                .order_by(MetaSyncRunModel.period_value.asc())
            )
        ).scalars().all()
    return [str(item) for item in rows if item]


async def main() -> None:
    parser = argparse.ArgumentParser(description="构建订单全链路宽表")
    parser.add_argument("--period", default=None, help="期间，如 2026-09；多个用逗号分隔")
    parser.add_argument("--all", action="store_true", help="构建全部可用期间")
    parser.add_argument("--refresh", action="store_true", help="构建前先按期间重拉各来源批次")
    parser.add_argument("--keep-versions", type=int, default=3, help="每个订单保留的版本数（默认 3）")
    args = parser.parse_args()

    if args.all:
        periods = await available_periods()
    elif args.period:
        periods = [item.strip() for item in args.period.split(",") if item.strip()]
    else:
        parser.error("必须提供 --period 或 --all")
    print(f"待构建期间 {len(periods)} 个：{periods[0]} ~ {periods[-1]}")

    for period in periods:
        if args.refresh:
            executed = await refresh_period_sources(period)
            print(f"  期间 {period} 重拉来源 {len(executed)} 个任务")
        async with async_db_session() as db, db.begin():
            result = await build_period(db, period, prune_versions=args.keep_versions)
        print(
            f"期间 {result['period_value']} 版本 v{result['calc_version']}："
            f"订单 {result['order_count']} 张，关联生产订单 {result['mo_linked_count']} 张，"
            f"成本缺失 {result['cost_missing_count']} 张"
        )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
