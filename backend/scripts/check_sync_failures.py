"""列出最近失败的「元数据同步任务」批次，便于快速定位取不到数的来源。

定时任务批次里指标"成功"但数据是旧的，往往是因为来源同步失败（例如聚水潭 IP 白名单、
金蝶账号登录失败）；本脚本把最近的失败批次连同错误摘要打印出来。

用法（backend 目录，dev 环境先设置 ENVIRONMENT=dev）：

    python scripts/check_sync_failures.py            # 最近 30 条失败批次
    python scripts/check_sync_failures.py --limit 100
    python scripts/check_sync_failures.py --days 3   # 只看最近 3 天
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    parser = argparse.ArgumentParser(description="列出最近失败的元数据同步批次")
    parser.add_argument("--limit", type=int, default=30, help="最多显示条数，默认 30")
    parser.add_argument("--days", type=int, default=0, help="只看最近 N 天（0=不限）")
    args = parser.parse_args()

    conditions = [MetaSyncRunModel.status == "failed"]
    if args.days > 0:
        conditions.append(MetaSyncRunModel.started_at >= datetime.now(UTC) - timedelta(days=args.days))

    async with async_db_session() as db:
        rows = (
            await db.execute(
                select(
                    MetaSyncRunModel.id,
                    MetaSyncRunModel.job_id,
                    MetaSyncRunModel.period_value,
                    MetaSyncRunModel.started_at,
                    MetaSyncRunModel.error,
                    MetaSyncJobModel.name,
                )
                .join(MetaSyncJobModel, MetaSyncJobModel.id == MetaSyncRunModel.job_id)
                .where(*conditions)
                .order_by(MetaSyncRunModel.id.desc())
                .limit(max(1, args.limit))
            )
        ).all()

    print("=" * 100)
    print(f"最近失败的同步批次：{len(rows)} 条" + (f"（最近 {args.days} 天）" if args.days else ""))
    print("=" * 100)
    if not rows:
        print("没有失败批次 ✅")
        await async_engine.dispose()
        return

    for run_id, job_id, period_value, started_at, error, job_name in rows:
        started = started_at.strftime("%Y-%m-%d %H:%M:%S") if started_at else "-"
        snippet = " ".join((error or "").split())[:220]
        print(f"[run {run_id}] {started} | 任务 {job_id} {job_name} | 期间 {period_value}")
        print(f"    错误: {snippet}")

    # 汇总：按任务统计，便于看频率
    summary: dict[str, int] = {}
    for _run_id, job_id, _period, _started, _error, job_name in rows:
        summary[f"{job_id} {job_name}"] = summary.get(f"{job_id} {job_name}", 0) + 1
    print("-" * 100)
    print("按任务汇总：")
    for key, count in sorted(summary.items(), key=lambda item: -item[1]):
        print(f"  {count:>3} 次  {key}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
