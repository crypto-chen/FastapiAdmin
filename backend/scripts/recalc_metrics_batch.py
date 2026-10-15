"""批量重算指定指标（口径调整后回填历史期间用）。

用法：
    python scripts/recalc_metrics_batch.py --code marketing_travel_expense --code marketing_vehicle_expense
    python scripts/recalc_metrics_batch.py --code marketing_total_expense --period 2026-09
    python scripts/recalc_metrics_batch.py --code marketing_total_expense --period-from 2026-01 --period-to 2026-10
    python scripts/recalc_metrics_batch.py --code marketing_total_expense --log recalc.log

期间三种写法：``--period``（可重复，精确指定）、``--period-from/--period-to``（闭区间，按已有期间过滤）、
都不传时按已有同步批次的全部期间依次重算。
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.engine import execute_metric_calc  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.modules.metadata.model import MetaSyncRunModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def available_periods() -> list[str]:
    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(MetaSyncRunModel.period_value)
                .where(MetaSyncRunModel.status == "success", MetaSyncRunModel.period_value.isnot(None))
                .group_by(MetaSyncRunModel.period_value)
                .order_by(MetaSyncRunModel.period_value.asc())
            )
        ).scalars().all()
    return [str(item) for item in rows]


async def metric_ids(codes: list[str]) -> list[tuple[int, str]]:
    async with async_db_session() as db:
        rows = (
            await db.execute(select(MetricDefModel.id, MetricDefModel.code).where(MetricDefModel.code.in_(codes)))
        ).all()
    found = {code: int(mid) for mid, code in rows}
    missing = [code for code in codes if code not in found]
    for code in missing:
        print(f"跳过（指标不存在）: {code}")
    return [(found[code], code) for code in codes if code in found]


async def main() -> None:
    parser = argparse.ArgumentParser(description="批量重算指标")
    parser.add_argument("--code", action="append", required=True, help="指标编码，可重复")
    parser.add_argument("--period", action="append", default=None, help="期间值，可重复；缺省为全部已有期间")
    parser.add_argument("--period-from", default=None, help="起始期间（含），如 2026-01")
    parser.add_argument("--period-to", default=None, help="结束期间（含），如 2026-10")
    parser.add_argument("--log", default=None, help="同时写入日志文件")
    args = parser.parse_args()

    if args.period:
        periods = list(args.period)
    else:
        periods = await available_periods()
        if args.period_from:
            periods = [item for item in periods if item >= args.period_from]
        if args.period_to:
            periods = [item for item in periods if item <= args.period_to]
    if not periods:
        raise SystemExit("没有匹配的期间，请检查 --period / --period-from / --period-to")
    plan = await metric_ids(args.code)
    print(f"期间 {len(periods)} 个，指标 {len(plan)} 个，共 {len(periods) * len(plan)} 次计算", flush=True)

    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None

    def emit(line: str) -> None:
        print(line, flush=True)
        if log_handle:
            log_handle.write(line + "\n")
            log_handle.flush()

    for period in periods:
        for metric_id, code in plan:
            started = time.time()
            try:
                summary = await execute_metric_calc(metric_id=metric_id, period_value=period)
                emit(f"{period} {code} -> {summary['total']} ({time.time() - started:.1f}s)")
            except Exception as e:  # noqa: BLE001
                emit(f"{period} {code} -> ERROR {type(e).__name__}: {e}")
        emit(f"=== {period} 完成 ===")

    if log_handle:
        log_handle.close()
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
