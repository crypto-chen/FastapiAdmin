"""校验 ORD-01（营销中心接单金额·未税）= ORD-01-a + ORD-01-b + ORD-01-c。

只读数据库，按每个期间的最新 calc_version 取公司合计行（dept_code 为空）比对。
用法：python scripts/verify_ord01_formula.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

ORD01 = "marketing_order_intake_untaxed"
COMPONENTS = [
    "marketing_domestic_order_untaxed",
    "marketing_export_order_untaxed",
    "marketing_retail_order_untaxed",
]
EPSILON = 0.005


async def latest_company_value(db, metric_id: int, period: str) -> float:
    version = (
        await db.execute(
            select(func.max(MetricValueModel.calc_version)).where(
                MetricValueModel.metric_id == metric_id,
                MetricValueModel.period_value == period,
            )
        )
    ).scalars().first()
    if version is None:
        return 0.0
    value = (
        await db.execute(
            select(func.sum(MetricValueModel.value)).where(
                MetricValueModel.metric_id == metric_id,
                MetricValueModel.period_value == period,
                MetricValueModel.calc_version == version,
                MetricValueModel.dept_code.is_(None),
            )
        )
    ).scalars().first()
    return float(value or 0.0)


async def main() -> int:
    async with async_db_session() as db:
        defs = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code.in_([ORD01, *COMPONENTS])))
        ).scalars().all()
        by_code = {item.code: item for item in defs}
        missing = [code for code in [ORD01, *COMPONENTS] if code not in by_code]
        if missing:
            print(f"FAIL 缺少指标定义: {', '.join(missing)}")
            return 1

        measures = dict(by_code[ORD01].measures or {})
        actual_components = list(measures.get("component_metric_codes") or [])
        if actual_components != COMPONENTS:
            print(f"FAIL ORD-01 组成指标配置不符: {actual_components}")
            return 1
        print(f"OK 公式: {by_code[ORD01].formula}")
        print(f"OK 组成指标: {', '.join(actual_components)}")

        periods = (
            await db.execute(
                select(MetricValueModel.period_value)
                .where(MetricValueModel.metric_id == by_code[ORD01].id)
                .group_by(MetricValueModel.period_value)
                .order_by(MetricValueModel.period_value.asc())
            )
        ).scalars().all()
        if not periods:
            print("FAIL ORD-01 没有任何计算结果")
            return 1

        failures = 0
        for period in periods:
            expected = 0.0
            parts: list[str] = []
            for code in COMPONENTS:
                value = await latest_company_value(db, by_code[code].id, str(period))
                expected += value
                parts.append(f"{code}={value:,.2f}")
            actual = await latest_company_value(db, by_code[ORD01].id, str(period))
            diff = actual - expected
            status = "OK" if abs(diff) <= EPSILON else "FAIL"
            if status == "FAIL":
                failures += 1
            print(f"{status} {period} ORD-01={actual:,.4f} 组成合计={expected:,.4f} 差额={diff:+.4f} | {' '.join(parts)}")
    await async_engine.dispose()
    print(f"{'PASS' if failures == 0 else 'FAIL'} 期间 {len(periods)} 个，失败 {failures} 个")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
