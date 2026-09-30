"""初始化营销中心「备货预测准确率」指标（派生指标，不新增来源对象/同步任务）。

口径（用户给定）：**备货预测准确率 = 零售出货未税 ÷ 当期备货生产入库 × 100%**

- 分子「零售出货未税」= 本系统已有的聚水潭指标
  `retail_outbound_untaxed_amount`（零售出库未税总金额，销售出库单）。
  备注：CRM 无零售出货接口（见 `seed_crm_shipment_metrics.py`），
  出货系列已确认零售出货口径取该聚水潭指标，这里沿用同一口径；
  若后续改用其它指标，只改本文件的 ``NUMERATOR_CODES``。
- 分母「当期备货生产入库」= `marketing_stockup_prod_instock`
  （营销中心当期备货生产入库指标，口径见 `seed_stockup_instock_metric.py`）。
- 取数类型 `kind = metric_ratio`：分子合计 ÷ 分母合计 × ``ratio_scale``；
  ``ratio_scale = 100`` → 结果按**百分数**输出（如 85.2 表示 85.2%），分母为 0 时取 0。

两个组成指标在计算时会由引擎按同一期间自动补齐缺结果，无需手工先算。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

依赖：
- 零售出库未税总金额：``python scripts/seed_jushuitan_metric.py``
- 当期备货生产入库：``python scripts/seed_stockup_instock_metric.py``

用法：
    python scripts/seed_stockup_forecast_accuracy_metric.py
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

METRIC_CODE = "marketing_stockup_forecast_accuracy"
METRIC_NAME = "营销中心备货预测准确率"

# 分子：零售出货未税（= 聚水潭「零售出库未税总金额」）
NUMERATOR_CODES = ["retail_outbound_untaxed_amount"]
# 分母：当期备货生产入库
DENOMINATOR_CODES = ["marketing_stockup_prod_instock"]
# 结果放大倍数：100 → 百分数
RATIO_SCALE = 100

MEASURES = {
    "kind": "metric_ratio",
    "numerator_metric_codes": NUMERATOR_CODES,
    "denominator_metric_codes": DENOMINATOR_CODES,
    "ratio_scale": RATIO_SCALE,
}
DIMENSIONS = {"org": False, "dept": False}

FORMULA = (
    f"（{' + '.join(NUMERATOR_CODES)} 当期值）÷（{' + '.join(DENOMINATOR_CODES)} 当期值）"
    f" × {RATIO_SCALE}"
)
DESCRIPTION = (
    "营销中心备货预测准确率 = 零售出货未税 ÷ 当期备货生产入库 × 100%："
    "分子零售出货未税取聚水潭「零售出库未税总金额」（retail_outbound_untaxed_amount，"
    "CRM 无零售出货接口，出货系列已确认该口径）；"
    "分母当期备货生产入库取「营销中心当期备货生产入库指标」"
    "（marketing_stockup_prod_instock：本期已审核生产入库单中需求单据 BH 开头的分录，"
    "生产订单物料含 C. 的只计一次整单金额，其余按 单价=Y订单金额÷生产数量 结转）；"
    "结果按百分数输出，分母为 0 时取 0。月指标，每日 02:30 重算当月，"
    "次月 1 日重拉上月并重算，每次计算保留 calc_version 版本。"
)


async def main() -> None:
    async with async_db_session() as db, db.begin():
        missing: list[str] = []
        for code in [*NUMERATOR_CODES, *DENOMINATOR_CODES]:
            exists = (
                await db.execute(select(MetricDefModel.id).where(MetricDefModel.code == code))
            ).scalars().first()
            if exists is None:
                missing.append(code)
        if missing:
            raise SystemExit(f"缺少组成指标 {missing}，请先执行对应 seed 脚本")

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
        metric.measures = MEASURES
        metric.source_entity_id = None  # 比率指标自身不取数
        metric.status = 0
        metric.description = DESCRIPTION
        await db.flush()
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    await async_engine.dispose()
    print("营销中心备货预测准确率指标初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
