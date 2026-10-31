"""客户编码匹配自检（只读）。

校验：
- 订单全链路里零售单是否落到 LS 客户编码、是否还残留定制客户编码；
- 客户分析是否出现零售客户独立行（extra.is_retail=1）；
- STF-47 总客户数、STF-48 本月下单老客户数是否按编码去重。

用法：
    python scripts/check_customer_code_mapping.py
    python scripts/check_customer_code_mapping.py --period 2026-10
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.customer.model import CustomerAnalysisModel  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.modules.order.model import OrderFullChainModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

METRIC_CODES = (
    "marketing_person_total_customer_count",
    "marketing_person_old_customer_order_count",
    "marketing_person_repurchase_rate",
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="客户编码匹配自检")
    parser.add_argument("--period", default="2026-10", help="期间 YYYY-MM，默认 2026-10")
    args = parser.parse_args()
    period = args.period

    async with async_db_session() as db:
        order_version = (
            await db.execute(
                select(func.max(OrderFullChainModel.calc_version)).where(
                    OrderFullChainModel.period_value == period
                )
            )
        ).scalar()
        rows = (
            await db.execute(
                select(OrderFullChainModel.order_type, OrderFullChainModel.extra).where(
                    OrderFullChainModel.period_value == period,
                    OrderFullChainModel.calc_version == order_version,
                )
            )
        ).all()
        retail = [
            (extra or {}).get("customer_number") or ""
            for order_type, extra in rows
            if str(order_type or "") == "3"
        ]
        ls = sum(1 for code in retail if str(code).startswith("LS"))
        blank = sum(1 for code in retail if not str(code))
        print(
            f"[{period}] 订单全链路 v{order_version}：零售单 {len(retail)}，"
            f"LS 编码 {ls}，空编码 {blank}，其它编码 {len(retail) - ls - blank}"
        )

        cus_version = (
            await db.execute(
                select(func.max(CustomerAnalysisModel.calc_version)).where(
                    CustomerAnalysisModel.period_value == period
                )
            )
        ).scalar()
        cus_rows = (
            await db.execute(
                select(CustomerAnalysisModel.customer_code, CustomerAnalysisModel.extra).where(
                    CustomerAnalysisModel.period_value == period,
                    CustomerAnalysisModel.calc_version == cus_version,
                    CustomerAnalysisModel.is_aggregate == 0,
                )
            )
        ).all()
        retail_rows = sum(
            1 for _code, extra in cus_rows if str((extra or {}).get("is_retail")) == "1"
        )
        print(
            f"[{period}] 客户分析 v{cus_version}：客户行 {len(cus_rows)}，"
            f"零售客户行 {retail_rows}"
        )

        for code in METRIC_CODES:
            metric_id = (
                await db.execute(select(MetricDefModel.id).where(MetricDefModel.code == code))
            ).scalar()
            if metric_id is None:
                print(f"{code}: 指标定义不存在")
                continue
            total = (
                await db.execute(
                    select(MetricValueModel.value).where(
                        MetricValueModel.metric_id == metric_id,
                        MetricValueModel.period_value == period,
                        MetricValueModel.person_code.is_(None),
                    )
                    .order_by(MetricValueModel.calc_time.desc())
                    .limit(1)
                )
            ).scalars().first()
            print(f"{code}: 期间 {period} 合计 = {total}")


if __name__ == "__main__":
    asyncio.run(main())
