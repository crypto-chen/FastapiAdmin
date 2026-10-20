"""科目余额表改口径后：重新同步指定期间 + 重算所有依赖它的指标。

场景：科目余额表取数由「仅人民币」改为「综合本位币（FCURRENCY=0）」，
历史批次里的本位币列为空，必须按期间重拉批次，再重算全部读该表的指标（含其派生指标）。

用法：
    python scripts/resync_account_balance_and_recalc.py --period-from 2026-01 --period-to 2026-10
    python scripts/resync_account_balance_and_recalc.py --period 2026-09 --skip-sync   # 只重算
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel  # noqa: E402
from app.modules.metadata.sync import execute_meta_sync_job  # noqa: E402
from app.modules.metric.engine import execute_metric_calc, metric_dependency_codes  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SOURCE_OBJECT_CODE = "GL_RPT_AccountBalance"


async def load_plan() -> tuple[list[int], list[tuple[int, str]]]:
    """返回（科目余额表任务ID列表，需要重算的指标（含派生）按依赖顺序）。"""
    async with async_db_session() as db:
        jobs = (
            await db.execute(
                select(MetaSyncJobModel.id)
                .where(MetaSyncJobModel.source_object_id == 1, MetaSyncJobModel.status == 0)
                .order_by(MetaSyncJobModel.org_code.asc())
            )
        ).scalars().all()
        metrics = (await db.execute(select(MetricDefModel.id, MetricDefModel.code, MetricDefModel.measures))).all()

    depends: dict[str, list[str]] = {}
    roots: list[str] = []
    for _mid, code, measures in metrics:
        config = json.loads(measures) if isinstance(measures, str) else (measures or {})
        depends[str(code)] = metric_dependency_codes(config)
        if str(config.get("source_object_code") or "") == SOURCE_OBJECT_CODE:
            roots.append(str(code))

    ordered: list[str] = []
    seen: set[str] = set()
    layer = [code for code in roots if code not in seen]
    while layer:
        for code in layer:
            if code not in seen:
                seen.add(code)
                ordered.append(code)
        layer = [code for code, deps in depends.items() if code not in seen and (set(deps) & set(layer))]

    id_by_code = {str(code): int(mid) for mid, code, _ in metrics}
    plan = [(id_by_code[code], code) for code in ordered if code in id_by_code]
    return [int(item) for item in jobs], plan


async def main() -> None:
    parser = argparse.ArgumentParser(description="重新同步科目余额表并重算依赖指标")
    parser.add_argument("--period", action="append", default=None, help="期间值，可重复")
    parser.add_argument("--period-from", default=None, help="起始期间（含）")
    parser.add_argument("--period-to", default=None, help="结束期间（含）")
    parser.add_argument("--skip-sync", action="store_true", help="不重新同步，只重算指标")
    parser.add_argument("--log", default=None, help="日志文件")
    args = parser.parse_args()

    job_ids, plan = await load_plan()
    if args.period:
        periods = list(args.period)
    else:
        periods = [args.period_from or "2026-01", args.period_to or "2026-10"]
        start, end = periods
        periods = [f"{year}-{month:02d}" for year in range(int(start[:4]), int(end[:4]) + 1) for month in range(1, 13)
                   if start <= f"{year}-{month:02d}" <= end]

    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None

    def emit(line: str) -> None:
        text = f"[{datetime.now():%H:%M:%S}] {line}"
        print(text, flush=True)
        if log_handle:
            log_handle.write(text + "\n")
            log_handle.flush()

    emit(f"期间 {periods}；科目余额表任务 {len(job_ids)} 个；待重算指标 {len(plan)} 个")
    for period in periods:
        started = time.time()
        if not args.skip_sync:
            for index, job_id in enumerate(job_ids, start=1):
                try:
                    await execute_meta_sync_job(job_id, period_value=period)
                    emit(f"{period} 同步任务 {job_id} ({index}/{len(job_ids)}) 完成")
                except Exception as e:  # noqa: BLE001
                    emit(f"{period} 同步任务 {job_id} 失败: {type(e).__name__}: {e}")
        for metric_id, code in plan:
            try:
                summary = await execute_metric_calc(metric_id=metric_id, period_value=period)
                emit(f"{period} {code} -> {summary['total']}")
            except Exception as e:  # noqa: BLE001
                emit(f"{period} {code} 重算失败: {type(e).__name__}: {e}")
        emit(f"=== {period} 完成，用时 {time.time() - started:.0f}s ===")

    if log_handle:
        log_handle.close()
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
