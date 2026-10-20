"""一次性更新 REV-04 营销结算收入折算比例：10% → 18%。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.base_model import MappedBase
from app.core.database import async_db_session, async_engine
from app.modules.metric.model import MetricDefModel
from app.utils.import_util import ImportUtil

ImportUtil.find_models(MappedBase)

CODE = "marketing_total_income_settlement"
SCALE = 0.18


async def main() -> None:
    async with async_db_session() as db, db.begin():
        metric = (await db.execute(select(MetricDefModel).where(MetricDefModel.code == CODE))).scalars().first()
        if metric is None:
            raise SystemExit(f"未找到指标 {CODE}")
        measures = dict(metric.measures or {})
        before = measures.get("scale")
        measures["scale"] = SCALE
        metric.measures = measures
        metric.formula = f"(marketing_external_shipment_net_untaxed 当期值) × {SCALE}"
        metric.description = (
            "总收益（营销结算收入）= 对外出货未税销售额（净额）× 18%。 "
            "数据来源：本系统内下列指标的当期结果按系数折算；"
            "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
        )
        print(f"{CODE}: scale {before} -> {SCALE}")
        print(f"formula: {metric.formula}")
        print(f"measures: {metric.measures}")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
