"""客户分析数据自检（只读，不写库）。

校验：期间/版本分布、合计行、多值拼接字段、派生指标抽样。

用法：
    python scripts/check_customer_metrics.py
    python scripts/check_customer_metrics.py --period 2026-09
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
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    parser = argparse.ArgumentParser(description="客户分析数据自检")
    parser.add_argument("--period", default=None, help="期间，缺省检查全部")
    args = parser.parse_args()

    async with async_db_session() as db:
        statement = select(
            CustomerAnalysisModel.period_value,
            CustomerAnalysisModel.calc_version,
            CustomerAnalysisModel.is_aggregate,
            func.count().label("rows"),
        ).group_by(
            CustomerAnalysisModel.period_value,
            CustomerAnalysisModel.calc_version,
            CustomerAnalysisModel.is_aggregate,
        )
        if args.period:
            statement = statement.where(CustomerAnalysisModel.period_value == args.period)
        print("期间        版本  类型   行数")
        for period, version, is_agg, rows in (await db.execute(statement)).all():
            print(f"{period}  v{version}   {'合计' if is_agg else '客户'}   {rows}")

        statement = (
            select(CustomerAnalysisModel)
            .where(CustomerAnalysisModel.is_aggregate == 1)
            .order_by(CustomerAnalysisModel.period_value.desc(), CustomerAnalysisModel.calc_version.desc())
        )
        if args.period:
            statement = statement.where(CustomerAnalysisModel.period_value == args.period)
        print("\n合计行：")
        for row in (await db.execute(statement.limit(6))).scalars().all():
            extra = row.extra or {}
            print(
                f"  {row.period_value} v{row.calc_version}: 客户 {extra.get('CUS-43')} 个、订单 {row.order_count} 单、"
                f"接单未税 {row.intake_untaxed}、净额 {row.net_shipment}、毛利 {row.gross_profit}"
            )

        period = args.period or "2026-09"
        statement = (
            select(CustomerAnalysisModel)
            .where(CustomerAnalysisModel.is_aggregate == 0, CustomerAnalysisModel.period_value == period)
            .order_by(CustomerAnalysisModel.calc_version.desc(), CustomerAnalysisModel.intake_untaxed.desc())
            .limit(3)
        )
        print(f"\n客户抽样（{period}，接单未税 Top3）：")
        for row in (await db.execute(statement)).scalars().all():
            extra = row.extra or {}
            print(f"  {row.customer_name}（{row.customer_code}）v{row.calc_version}")
            print(
                f"    产品线={extra.get('CUS-09')} | SKU={extra.get('CUS-10')} | "
                f"订单类型={extra.get('CUS-11')} | 贸易={extra.get('CUS-05')}"
            )
            print(
                f"    接单未税={row.intake_untaxed} | 净额={row.net_shipment} | 毛利率={extra.get('CUS-29')} | "
                f"边际贡献={row.contribution_margin} | 结算收益={extra.get('CUS-32')} | 客单价={extra.get('CUS-42')}"
            )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
