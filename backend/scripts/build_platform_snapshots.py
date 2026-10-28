"""按期间批量计算平台指标快照（platform_metric_snapshot）。

用法::

    cd backend

    # 指定区间（含首尾），逐月计算
    python scripts/build_platform_snapshots.py --begin 2026-01 --end 2026-10

    # 单个期间
    python scripts/build_platform_snapshots.py --period 2026-10

    # 只算有订单的期间（自动跳过空月份）
    python scripts/build_platform_snapshots.py --all

每次计算都会生成新的 ``calc_version``，不覆盖历史版本；期间没有零售订单时自动跳过。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.platform.service import PlatformAnalysisService  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


def _month_range(begin: str, end: str) -> list[str]:
    start_y, start_m = (int(part) for part in begin.split("-"))
    end_y, end_m = (int(part) for part in end.split("-"))
    if (end_y, end_m) < (start_y, start_m):
        raise SystemExit("--end 不能早于 --begin")
    periods: list[str] = []
    year, month = start_y, start_m
    while (year, month) <= (end_y, end_m):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return periods


async def _build(periods: list[str] | None) -> None:
    async with async_db_session() as db:
        service = PlatformAnalysisService(db)
        targets = periods or await service.periods()
    ok = skipped = 0
    for period in sorted(set(targets)):
        async with async_db_session() as db, db.begin():
            result = await PlatformAnalysisService(db).build_snapshot(period)
        if result.get("status") == "success":
            ok += 1
            print(
                f"[OK] {period}  v{result['calc_version']}  "
                f"店铺 {result['shop_count']} 个  写入 {result['rows']} 行  {result['batch_id']}"
            )
        else:
            skipped += 1
            print(f"[SKIP] {period}  {result.get('reason')}")
    await async_engine.dispose()
    print(f"完成：成功 {ok} 个期间，跳过 {skipped} 个")


def main() -> None:
    parser = argparse.ArgumentParser(description="批量计算平台指标快照")
    parser.add_argument("--period", help="单个期间 YYYY-MM")
    parser.add_argument("--all", action="store_true", help="所有有订单的期间")
    parser.add_argument("--begin", help="起始期间 YYYY-MM（与 --end 搭配）")
    parser.add_argument("--end", help="结束期间 YYYY-MM")
    args = parser.parse_args()

    if args.period:
        periods = [args.period.strip()]
    elif args.begin and args.end:
        periods = _month_range(args.begin.strip(), args.end.strip())
    elif args.all:
        periods = None
    else:
        raise SystemExit("请传 --period，或 --begin/--end，或 --all")
    asyncio.run(_build(periods))


if __name__ == "__main__":
    main()
