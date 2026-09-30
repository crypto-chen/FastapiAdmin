"""初始化营销中心「现金转换周期」指标（CCC）。

口径（用户给定）：**现金转换周期 = 库存周转天数 + 应收周转天数 − 应付周转天数**。

新增 1 个月指标 ``marketing_cash_conversion_cycle``（``kind = metric_diff``，
自身不取数，值为加项合计 − 减项合计）：

- 加项：``marketing_inventory_turnover_days``（营销中心库存周转天数）
  + ``marketing_ar_turnover_days``（营销中心应收周转天数）；
- 减项：``marketing_ap_turnover_days``（营销中心应付周转天数）。

三个组成指标各自由所属脚本维护，计算时由引擎按同一期间自动补齐缺结果的组成指标
（仍缺结果按 0 计入并告警）：

- 库存周转天数：``backend/scripts/seed_marketing_stockup_inventory_metric.py``
- 应收周转天数：``backend/scripts/seed_marketing_ar_turnover_metric.py``
- 应付周转天数：``backend/scripts/seed_marketing_ap_turnover_metric.py``

单位：天（加项与减项都是天数口径，结果同为天数；``measures.unit`` 显式声明，
不依赖名称兜底）。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_marketing_cash_conversion_metric.py

依赖：先执行上面三个组成指标的 seed 脚本（本脚本只校验指标定义是否齐备，不校验结果是否存在）。
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

DIMENSIONS = {"org": False, "dept": False}
UNIT = "天"

METRIC_CODE = "marketing_cash_conversion_cycle"
METRIC_NAME = "营销中心现金转换周期"

# 加项：库存周转天数 + 应收周转天数
ADDEND_CODES = [
    "marketing_inventory_turnover_days",
    "marketing_ar_turnover_days",
]
# 减项：应付周转天数
SUBTRACT_CODES = ["marketing_ap_turnover_days"]

MEASURES = {
    "kind": "metric_diff",
    "addend_metric_codes": ADDEND_CODES,
    "subtrahend_metric_codes": SUBTRACT_CODES,
    "unit": UNIT,
}

FORMULA = "（营销中心库存周转天数 + 营销中心应收周转天数） − 营销中心应付周转天数"

RULE = (
    "现金转换周期 = 库存周转天数 + 应收周转天数 − 应付周转天数："
    "加项取「营销中心库存周转天数」（marketing_inventory_turnover_days，= 平均库存（未税）"
    "÷ 当期销售成本 × 30）与「营销中心应收周转天数」（marketing_ar_turnover_days，"
    "=【(期初应收余额 + 期末应收余额) ÷ 2】÷ 对外出货未税净额 × 30），"
    "减项取「营销中心应付周转天数」（marketing_ap_turnover_days，"
    "=【(期初应付账款 + 期末应付账款) ÷ 2】÷ 当期采购入库金额（含税）× 30）；"
    "差额指标 kind=metric_diff，加项合计 − 减项合计，单位天，公司整体口径"
)


async def main() -> None:
    async with async_db_session() as db, db.begin():
        codes = [*ADDEND_CODES, *SUBTRACT_CODES]
        existing = set(
            (await db.execute(select(MetricDefModel.code).where(MetricDefModel.code.in_(codes))))
            .scalars()
            .all()
        )
        missing = [code for code in codes if code not in existing]
        if missing:
            raise SystemExit(
                "缺少组成指标定义: " + ", ".join(missing) + "；请先执行对应 seed 脚本"
                "（库存 seed_marketing_stockup_inventory_metric.py /"
                " 应收 seed_marketing_ar_turnover_metric.py /"
                " 应付 seed_marketing_ap_turnover_metric.py）"
            )

        metric = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code == METRIC_CODE))
        ).scalars().first()
        if metric is None:
            metric = MetricDefModel(code=METRIC_CODE)
            db.add(metric)
        metric.name = METRIC_NAME
        metric.period_type = "month"
        metric.sensitivity = 0
        metric.formula = FORMULA
        metric.dimensions = DIMENSIONS
        metric.measures = dict(MEASURES)
        metric.source_entity_id = None
        metric.status = 0
        metric.description = (
            f"{RULE}；月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本；"
            "数据来源：本系统内库存 / 应收 / 应付周转天数当期结果。"
        )
        await db.flush()
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()
    print("营销中心现金转换周期指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
