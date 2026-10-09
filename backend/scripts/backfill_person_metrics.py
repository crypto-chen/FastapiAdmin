"""业务员指标期间回补：先按期间取数（来源明细批次），再按期间重算业务员指标。

用于把开发环境已验证的业务员指标在服务器上一次性补齐历史数据（服务器本身没有这些批次）。

```bash
# 回补 2025-01 ~ 2026-09（已存在成功批次时跳过，不重复取数）
python scripts/backfill_person_metrics.py --start 2025-01 --end 2026-09

# 强制重拉期间批次后再算（用于月末/口径调整后）
python scripts/backfill_person_metrics.py --start 2026-09 --end 2026-09 --refresh

# 只算某几个指标
python scripts/backfill_person_metrics.py --start 2026-09 --end 2026-09 --code marketing_person_order_intake_untaxed
```

说明：
- 数据源按指标 ``measures`` 里声明的来源对象自动收集；客户列表这类**无 month 参数**的接口
  只在开始前同步一次（后续期间复用同一份快照），其余明细接口按期间逐个取数。
- 指标计算走 ``run_metric_batch``（按依赖分层，含派生指标），失败项会汇总打印。
- 已经算过的期间重复执行只会再生成一个 ``calc_version``，不影响历史版本查询。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel  # noqa: E402
from app.modules.metadata.sync import execute_meta_sync_job  # noqa: E402
from app.modules.metric.batch import run_metric_batch  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

PERSON_CATEGORY = "营销中心-业务员"

# CLI 场景只保留控制台输出：默认日志文件被运行中的后端服务占用
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


def _months(start: str, end: str) -> list[str]:
    """``2025-01`` ~ ``2026-09`` 之间的整月列表（含首尾）。"""
    begin = datetime.strptime(start, "%Y-%m")
    finish = datetime.strptime(end, "%Y-%m")
    if begin > finish:
        raise SystemExit(f"起始期间不能晚于结束期间: {start} > {end}")
    periods: list[str] = []
    cursor = begin
    while cursor <= finish:
        periods.append(cursor.strftime("%Y-%m"))
        cursor = (
            datetime(cursor.year + 1, 1, 1) if cursor.month == 12 else datetime(cursor.year, cursor.month + 1, 1)
        )
    return periods


def _source_codes(measures: dict) -> set[str]:
    """从 measures 里收集来源对象编码（``source_object_code`` / ``order_source_object_code`` 等）。"""
    codes: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if "source_object_code" in str(key) and isinstance(value, str) and value.strip():
                    codes.add(value.strip())
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(measures or {})
    return codes


async def _load_targets(codes: list[str] | None):
    """返回 (指标定义列表, 来源对象快照列表, 来源对象按期间列表, 任务映射)。"""
    async with async_db_session() as db:
        query = select(MetricDefModel).where(
            MetricDefModel.category == PERSON_CATEGORY, MetricDefModel.is_deleted == False  # noqa: E712
        )
        if codes:
            query = query.where(MetricDefModel.code.in_(codes))
        metrics = (await db.execute(query.order_by(MetricDefModel.id.asc()))).scalars().all()
        if not metrics:
            raise SystemExit("没有找到业务员指标（分类 营销中心-业务员）；请先执行 seed_crm_person_metrics.py")

        source_codes: set[str] = set()
        for metric in metrics:
            source_codes |= _source_codes(metric.measures or {})
        if not source_codes:
            return [str(m.code) for m in metrics], [], [], {}

        objects = (
            await db.execute(
                select(SourceObjectModel.id, SourceObjectModel.code, SourceObjectModel.request_template).where(
                    SourceObjectModel.code.in_(sorted(source_codes))
                )
            )
        ).all()
        if len(objects) != len(source_codes):
            missing = source_codes - {row[1] for row in objects}
            raise SystemExit(f"来源对象不存在（先跑 seed 脚本）: {sorted(missing)}")

        snapshot_objects: list[tuple[int, str]] = []
        period_objects: list[tuple[int, str]] = []
        jobs_by_object: dict[int, list[int]] = {}
        for object_id, code, template in objects:
            job_ids = (
                await db.execute(
                    select(MetaSyncJobModel.id).where(
                        MetaSyncJobModel.source_object_id == object_id, MetaSyncJobModel.status == 0
                    )
                )
            ).scalars().all()
            if not job_ids:
                raise SystemExit(f"来源对象没有启用的同步任务: {code}")
            jobs_by_object[int(object_id)] = [int(item) for item in job_ids]
            if isinstance(template, dict) and template:
                period_objects.append((int(object_id), str(code)))
            else:
                snapshot_objects.append((int(object_id), str(code)))
    return [str(m.code) for m in metrics], snapshot_objects, period_objects, jobs_by_object


async def _batch_exists(job_id: int, period_value: str) -> bool:
    async with async_db_session() as db:
        run_id = (
            await db.execute(
                select(MetaSyncRunModel.id)
                .where(
                    MetaSyncRunModel.job_id == job_id,
                    MetaSyncRunModel.period_value == period_value,
                    MetaSyncRunModel.status == "success",
                )
                .limit(1)
            )
        ).scalars().first()
    return run_id is not None


async def _any_batch_exists(job_id: int) -> bool:
    """该任务是否已有任意一次成功批次（快照类来源只判断「同步过没有」）。"""
    async with async_db_session() as db:
        run_id = (
            await db.execute(
                select(MetaSyncRunModel.id)
                .where(MetaSyncRunModel.job_id == job_id, MetaSyncRunModel.status == "success")
                .limit(1)
            )
        ).scalars().first()
    return run_id is not None


async def main() -> None:
    parser = argparse.ArgumentParser(description="业务员指标期间回补（取数 + 重算）")
    parser.add_argument("--start", required=True, help="起始期间，如 2025-01")
    parser.add_argument("--end", required=True, help="结束期间，如 2026-09")
    parser.add_argument("--code", action="append", default=None, help="只回补指定指标编码，可重复")
    parser.add_argument("--refresh", action="store_true", help="已有批次也强制重拉")
    parser.add_argument("--skip-sync", action="store_true", help="只算指标，不重新取数")
    args = parser.parse_args()

    periods = _months(args.start, args.end)
    metric_codes, snapshots, period_objects, jobs_by_object = await _load_targets(args.code)
    print(f"待回补期间 {len(periods)} 个：{periods[0]} ~ {periods[-1]}")
    print(f"业务员指标 {len(metric_codes)} 个；快照来源 {len(snapshots)} 个；按期间来源 {len(period_objects)} 个")

    if not args.skip_sync:
        # 快照类来源（客户列表：无 month 参数）只在开始前同步一次
        for object_id, code in snapshots:
            for job_id in jobs_by_object[object_id]:
                if not args.refresh and await _any_batch_exists(job_id):
                    continue
                print(f"[取数] 快照来源 {code}（任务 {job_id}）")
                await execute_meta_sync_job(job_id, period_value=periods[-1])
        for period in periods:
            for object_id, code in period_objects:
                for job_id in jobs_by_object[object_id]:
                    if not args.refresh and await _batch_exists(job_id, period):
                        continue
                    print(f"[取数] {period} {code}（任务 {job_id}）")
                    await execute_meta_sync_job(job_id, period_value=period)

    failures: list[str] = []
    for period in periods:
        summary = await run_metric_batch(period_value=period, codes=metric_codes, label=f"业务员指标回补 {period}")
        failed = summary.get("failed") or []
        print(
            f"[计算] {period} 成功 {summary.get('success')}/{summary.get('metric_count')}"
            + (f"，失败 {failed}" if failed else "")
        )
        failures += [f"{period}:{item}" for item in failed]

    print()
    print(json.dumps({"periods": periods, "metric_count": len(metric_codes), "failed": failures}, ensure_ascii=False))
    await async_engine.dispose()
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
