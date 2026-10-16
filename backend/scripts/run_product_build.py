"""手动构建产品线分析宽表。

用法：
    python scripts/run_product_build.py --period 2026-09
    python scripts/run_product_build.py --period 2026-07,2026-08,2026-09
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
from app.modules.product.build import build_period  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    parser = argparse.ArgumentParser(description="产品线分析宽表构建")
    parser.add_argument("--period", required=True, help="期间，逗号分隔，如 2026-08,2026-09")
    args = parser.parse_args()

    for period in [item.strip() for item in args.period.split(",") if item.strip()]:
        async with async_db_session() as db, db.begin():
            result = await build_period(db, period)
        print(
            f"[{period}] v{result['calc_version']} 产品线 {result['line_count']} 个、"
            f"SKU {result['sku_count']} 个、明细 {result['detail_count']} 行、"
            f"订单 {result['order_count']} 行、接单未税 {result['intake_untaxed_sum']}、"
            f"净额 {result['net_shipment_sum']}、命中型号字典 {result['matched_rows']} / "
            f"未命中 {result['unmatched_rows']}"
        )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
