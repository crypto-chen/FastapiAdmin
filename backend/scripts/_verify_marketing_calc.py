"""独立复核营销中心结算收益 / 安全边际率：只读数据库现有结果，按公式重算并对比。"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CODES = [
    "marketing_total_income_settlement",
    "marketing_variable_expense_total",
    "marketing_fixed_expense_total",
    "marketing_contribution_margin",
    "marketing_contribution_margin_rate",
    "marketing_break_even_sales",
    "marketing_settlement_income",
    "marketing_settlement_income_rate",
    "marketing_margin_of_safety_rate",
    "marketing_external_shipment_net_untaxed",
]

# 当前业务口径：营销结算收入 = 对外出货未税净额 × 18%
SETTLEMENT_RATE = 0.18


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:,.4f}"


async def latest_values() -> dict[str, dict[str, float]]:
    async with async_db_session() as db:
        defs = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code.in_(CODES)))
        ).scalars().all()
        result: dict[str, dict[str, float]] = {code: {} for code in CODES}
        for metric in defs:
            periods = (
                await db.execute(
                    select(MetricValueModel.period_value)
                    .where(MetricValueModel.metric_id == metric.id)
                    .group_by(MetricValueModel.period_value)
                )
            ).scalars().all()
            for period in sorted(periods):
                latest = (
                    await db.execute(
                        select(func.max(MetricValueModel.calc_version)).where(
                            MetricValueModel.metric_id == metric.id,
                            MetricValueModel.period_value == period,
                        )
                    )
                ).scalars().first()
                value = (
                    await db.execute(
                        select(func.sum(MetricValueModel.value)).where(
                            MetricValueModel.metric_id == metric.id,
                            MetricValueModel.period_value == period,
                            MetricValueModel.calc_version == latest,
                            MetricValueModel.dept_code.is_(None),
                        )
                    )
                ).scalars().first()
                result[metric.code][period] = float(value or 0)
        return result


async def main() -> None:
    values = await latest_values()
    periods = sorted(p for p in {p for item in values.values() for p in item} if p >= "2026-01")
    header = (
        "期间     | 总收益(实际/应为)                 | 变动费用      | 固定费用      | 边际贡献(实际/应为)        "
        "| 结算收益(实际/应为)        | 安全边际率(实际/应为)"
    )
    print(header)
    print("-" * len(header))
    mismatches: list[str] = []
    for period in periods:
        rev01 = values["marketing_external_shipment_net_untaxed"].get(period, 0.0)
        income = values["marketing_total_income_settlement"].get(period, 0.0)
        variable = values["marketing_variable_expense_total"].get(period, 0.0)
        fixed = values["marketing_fixed_expense_total"].get(period, 0.0)
        cm = values["marketing_contribution_margin"].get(period, 0.0)
        cm_rate = values["marketing_contribution_margin_rate"].get(period, 0.0)
        bep = values["marketing_break_even_sales"].get(period, 0.0)
        settlement = values["marketing_settlement_income"].get(period, 0.0)
        safety = values["marketing_margin_of_safety_rate"].get(period, 0.0)

        income_expected = round(rev01 * SETTLEMENT_RATE, 4)
        cm_expected = round(income_expected - variable, 4)
        cm_rate_expected = round(cm_expected / income * 100, 4) if income else 0.0
        bep_expected = round(fixed / cm_rate_expected * 100, 4) if cm_rate_expected else 0.0
        settlement_expected = round(cm_expected - fixed, 4)
        safety_expected = round((income - bep_expected) / income * 100, 4) if income else 0.0

        print(
            f"{period} | {_fmt(income):>13} / {_fmt(income_expected):<13} | {_fmt(variable):>13} | {_fmt(fixed):>13} "
            f"| {_fmt(cm):>12} / {_fmt(cm_expected):<12} "
            f"| {_fmt(settlement):>12} / {_fmt(settlement_expected):<12} "
            f"| {_fmt(safety):>10} / {_fmt(safety_expected):<10}"
        )
        if (
            abs(income - income_expected) > 0.01
            or abs(cm - cm_expected) > 0.01
            or abs(bep - bep_expected) > 0.01
        ):
            mismatches.append(period)
            print(
                f"        中间量：总收益 实际={_fmt(income)} 应为={_fmt(income_expected)}；"
                f"边际贡献率 实际={_fmt(cm_rate)} 应为={_fmt(cm_rate_expected)}；"
                f"盈亏平衡点 实际={_fmt(bep)} 应为={_fmt(bep_expected)}"
            )

    print(f"\n核对结果：{len(periods)} 个期间，{len(mismatches)} 个不一致")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
