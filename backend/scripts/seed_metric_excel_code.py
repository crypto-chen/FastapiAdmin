"""回填指标定义的 Excel 科目编码（``metric_def.excel_code``）。

用法：
    python scripts/seed_metric_excel_code.py

口径：Excel 科目编码取自财务《核算指标》底稿的编码列（ORD / REV / COST / EXP / PER / CM / VA /
TM / PUSH / INV / AR / KPI 等），一个系统指标只保留一个主编码；Excel 里重复指向同一指标的
两处，取更规范的那个：EXP-01-t 与 INV-03 都指向库存资金占用费 → 取 ``INV-03``；
KPI-01 与 VA-02 都是结算收益率 → 取 ``VA-02``。

Excel 里系统暂时没有的指标（回款系列、平均人数、人工成本、人均指标等）不在本脚本内，
等系统补齐指标后再追加映射即可，脚本可重复执行。
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

# 系统指标编码 -> Excel 科目编码
EXCEL_CODE_MAP: dict[str, str] = {
    # 订单 ORD
    "marketing_order_intake_untaxed": "ORD-01",
    "marketing_domestic_order_untaxed": "ORD-01-a",
    "marketing_export_order_untaxed": "ORD-01-b",
    "marketing_retail_order_untaxed": "ORD-01-c",
    "marketing_batch_order_untaxed": "ORD-01-d",
    "marketing_sample_order_untaxed": "ORD-01-e",
    "marketing_stockup_order_untaxed": "ORD-01-f",
    "marketing_design_income_untaxed": "ORD-01-g",
    "marketing_quote_count": "ORD-02",
    "marketing_quote_success_rate": "ORD-03",
    "marketing_quote_profit_rate": "ORD-04",
    # 出货/收入 REV
    "marketing_external_shipment_net_untaxed": "REV-01",
    "marketing_goods_shipment_untaxed": "REV-01-a",
    "marketing_batch_shipment_untaxed": "REV-01-a-1",
    "marketing_sample_shipment_untaxed": "REV-01-a-2",
    "retail_outbound_untaxed_amount": "REV-01-a-3",
    "marketing_design_service_income_untaxed": "REV-01-b",
    "marketing_return_refund_untaxed": "REV-01-c",
    "marketing_total_income_settlement": "REV-04",
    # 列示成本 COST
    "marketing_material_cost_listed": "COST-01",
    "marketing_overhead_variable_listed": "COST-02",
    "marketing_overhead_fixed_listed": "COST-03",
    "marketing_product_cost_subtotal_listed": "COST-04",
    # 营销费用 EXP
    "marketing_total_expense": "EXP-01",
    "marketing_office_expense": "EXP-01-a",
    "marketing_travel_expense": "EXP-01-b",
    "marketing_vehicle_expense": "EXP-01-c",
    "marketing_low_value_consumables": "EXP-01-d",
    "marketing_telephone_expense": "EXP-01-e",
    "marketing_welfare_expense": "EXP-01-f",
    "marketing_intl_express_expense": "EXP-01-g",
    "marketing_domestic_express_expense": "EXP-01-h",
    "marketing_platform_expense": "EXP-01-i",
    "marketing_consulting_expense": "EXP-01-j",
    "marketing_after_sales_expense": "EXP-01-k",
    "marketing_utility_expense": "EXP-01-l",
    "marketing_promotion_expense": "EXP-01-m",
    "marketing_ecommerce_association_fee": "EXP-01-n",
    "marketing_repair_expense": "EXP-01-o",
    "marketing_it_service_expense": "EXP-01-p",
    "marketing_entertainment_expense": "EXP-01-q",
    "marketing_transport_expense": "EXP-01-r",
    "marketing_recruitment_expense": "EXP-01-s",
    "marketing_fixed_expense_subtotal": "EXP-02",
    "marketing_depreciation_expense": "EXP-02-a",
    "marketing_rent_property_expense": "EXP-02-b",
    # 总部分摊 PER-02
    "marketing_per02_total": "PER-02",
    "marketing_per02_hr_allocation": "PER-02-a",
    "marketing_per02_hr_variable": "PER-02-a-1",
    "marketing_per02_hr_fixed": "PER-02-a-2",
    "marketing_per02_finance_allocation": "PER-02-b",
    "marketing_per02_finance_variable": "PER-02-b-1",
    "marketing_per02_finance_fixed": "PER-02-b-2",
    "marketing_per02_ai_allocation": "PER-02-c",
    "marketing_per02_ai_variable": "PER-02-c-1",
    "marketing_per02_ai_fixed": "PER-02-c-2",
    # 边际贡献 / 结算 VA
    "marketing_variable_expense_total": "CM-01",
    "marketing_contribution_margin": "CM-02",
    "marketing_contribution_margin_rate": "CM-03",
    "marketing_fixed_expense_total": "CM-04",
    "marketing_settlement_income": "VA-01",
    "marketing_settlement_income_rate": "VA-02",
    "marketing_break_even_sales": "CM-05",
    "marketing_margin_of_safety_rate": "CM-06",
    # 工时 TM
    "marketing_regular_work_hours": "TM-01",
    "marketing_overtime_hours": "TM-02",
    "marketing_total_labor_hours": "TM-05",
    # 下推 PUSH
    "marketing_order_push_untaxed": "PUSH-01",
    "marketing_order_push_same_month": "PUSH-01-a",
    "marketing_order_push_prior_month": "PUSH-01-b",
    "marketing_push_period": "PUSH-02",
    "marketing_batch_push_period": "PUSH-02-a",
    "marketing_sample_push_period": "PUSH-02-b",
    "marketing_domestic_push_period": "PUSH-02-c",
    "marketing_export_push_period": "PUSH-02-d",
    "marketing_batch_domestic_push_period": "PUSH-02-e",
    "marketing_batch_export_push_period": "PUSH-02-f",
    "marketing_sample_domestic_push_period": "PUSH-02-g",
    "marketing_sample_export_push_period": "PUSH-02-h",
    "marketing_order_push_rate": "PUSH-03",
    # 库存 INV
    "marketing_inventory_total_untaxed": "INV-01",
    "marketing_external_order_inventory_untaxed": "INV-01-a",
    "marketing_stockup_order_instock": "INV-01-b",
    "marketing_stagnant_inventory_over90_untaxed": "INV-01-c",
    "marketing_inventory_avg_untaxed": "INV-02",
    "marketing_inventory_capital_cost": "INV-03",
    "marketing_inventory_turnover_days": "INV-04",
    "marketing_stockup_forecast_accuracy": "INV-05",
    "marketing_inventory_to_order_ratio": "INV-06",
    # 应收 AR
    "marketing_ar_balance": "AR-01",
    "marketing_ar_turnover_days": "AR-02",
    "marketing_ar_overdue": "AR-03",
    "marketing_overdue_rate": "AR-04",
    "marketing_bad_debt_provision": "AR-05",
    "marketing_cash_conversion_cycle": "AR-06",
    # KPI
    "marketing_value_added_per_hour": "KPI-04",
    "marketing_variable_expense_rate": "KPI-07",
    "marketing_fixed_expense_rate": "KPI-08",
    "marketing_manufacturing_cost_rate": "KPI-10",
    "marketing_cost_expense_rate": "KPI-13",
    "marketing_order_fulfillment_rate": "KPI-16",
    "marketing_platform_promotion_roi": "KPI-17",
    "marketing_order_price": "KPI-18",
    "marketing_repurchase_rate": "KPI-19",
    "marketing_return_rate": "KPI-20",
    "marketing_inventory_capital_cost_rate": "KPI-21",
}


async def main() -> None:
    updated: list[str] = []
    missing: list[str] = []
    async with async_db_session() as db, db.begin():
        metrics = (await db.execute(select(MetricDefModel))).scalars().all()
        by_code = {item.code: item for item in metrics}
        for code, excel_code in EXCEL_CODE_MAP.items():
            metric = by_code.get(code)
            if metric is None:
                missing.append(code)
                continue
            metric.excel_code = excel_code
            updated.append(code)

        # 不在映射里的指标清空编码，避免重命名后残留旧值
        for metric in metrics:
            if metric.code not in EXCEL_CODE_MAP and metric.excel_code:
                metric.excel_code = None

        no_excel_code = sorted(item.code for item in metrics if not item.excel_code)

    await async_engine.dispose()
    print(f"已回填 Excel 科目编码 {len(updated)} 个指标")
    if missing:
        print(f"⚠️ 系统里不存在的指标编码 {len(missing)} 个：{missing}")
    print(f"仍未配置 Excel 科目编码的指标 {len(no_excel_code)} 个：{no_excel_code}")


if __name__ == "__main__":
    asyncio.run(main())
